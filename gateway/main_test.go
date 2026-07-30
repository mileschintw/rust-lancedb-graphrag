package main

import (
	"bytes"
	"context"
	"errors"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"regexp"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"
	"go.uber.org/zap"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/lancet/gateway/db"
	pb "github.com/lancet/gateway/proto/lancet/v1"
)

type fakeStore struct {
	mu                    sync.Mutex
	document              db.Document
	documents             map[string]db.Document
	inserted              *db.InsertDocumentParams
	updated               *db.UpdateDocumentStatusParams
	insertErr             error
	getErr                error
	updateErr             error
	updateErrs            []error
	updateCalls           int
	getCalls              int
	winner                *db.Document
	updateCtx             context.Context
	updateSawLiveContext  bool
	rejectCanceledContext bool

	intents               map[string]db.DocumentReconciliationIntent
	createIntentErr       error
	claimIntentErr        error
	deleteIntentErr       error
	rescheduleIntentErr   error
	createIntentCalls     int
	claimIntentCalls      int
	deleteIntentCalls     int
	rescheduleIntentCalls int
}

func (s *fakeStore) Insert(_ context.Context, p db.InsertDocumentParams) (db.Document, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.insertErr != nil {
		return db.Document{}, s.insertErr
	}
	s.inserted = &p
	s.document = db.Document{ID: p.ID, Filename: p.Filename, FileSize: p.FileSize, Status: "queued"}
	if s.documents == nil {
		s.documents = make(map[string]db.Document)
	}
	s.documents[p.ID] = s.document
	return s.document, nil
}

func (s *fakeStore) Get(_ context.Context, id string) (db.Document, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.getCalls++
	if s.getCalls > 1 && s.winner != nil {
		return *s.winner, s.getErr
	}
	if s.documents != nil {
		if doc, ok := s.documents[id]; ok {
			return doc, s.getErr
		}
	}
	return s.document, s.getErr
}

func (s *fakeStore) UpdateStatus(ctx context.Context, p db.UpdateDocumentStatusParams) (db.Document, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.updateCtx = ctx
	s.updateSawLiveContext = ctx.Err() == nil
	if s.rejectCanceledContext && ctx.Err() != nil {
		return db.Document{}, ctx.Err()
	}
	s.updateCalls++
	if len(s.updateErrs) > 0 {
		err := s.updateErrs[0]
		s.updateErrs = s.updateErrs[1:]
		if err != nil {
			return db.Document{}, err
		}
	} else if s.updateErr != nil {
		return db.Document{}, s.updateErr
	}
	s.updated = &p
	s.document.Status = p.Status
	s.document.ChunkCount = p.ChunkCount
	s.document.ErrorMessage = p.ErrorMessage
	if s.documents != nil {
		if doc, ok := s.documents[p.ID]; ok {
			doc.Status = p.Status
			doc.ChunkCount = p.ChunkCount
			doc.ErrorMessage = p.ErrorMessage
			s.documents[p.ID] = doc
		}
	}
	return s.document, nil
}

func (s *fakeStore) CreateReconciliationIntent(_ context.Context, p db.CreateReconciliationIntentParams) (db.DocumentReconciliationIntent, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.createIntentCalls++
	if s.createIntentErr != nil {
		return db.DocumentReconciliationIntent{}, s.createIntentErr
	}
	docStatus := s.document.Status
	if s.documents != nil {
		if doc, ok := s.documents[p.ID]; ok {
			docStatus = doc.Status
		}
	}
	if docStatus != "" && docStatus != "queued" {
		return db.DocumentReconciliationIntent{}, pgx.ErrNoRows
	}
	if s.intents == nil {
		s.intents = make(map[string]db.DocumentReconciliationIntent)
	}
	intent := db.DocumentReconciliationIntent{
		DocumentID:    p.ID,
		DesiredStatus: p.DesiredStatus,
		ReasonClass:   p.ReasonClass,
		RetryCount:    0,
		NextAttemptAt: pgtype.Timestamp{Time: time.Now(), Valid: true},
	}
	s.intents[p.ID] = intent
	return intent, nil
}

func (s *fakeStore) ClaimDueReconciliationIntents(_ context.Context, p db.ClaimDueReconciliationIntentsParams) ([]db.DocumentReconciliationIntent, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.claimIntentCalls++
	if s.claimIntentErr != nil {
		return nil, s.claimIntentErr
	}
	var claimed []db.DocumentReconciliationIntent
	now := time.Now()
	for id, intent := range s.intents {
		if int32(len(claimed)) >= p.Limit {
			break
		}
		if !intent.NextAttemptAt.Valid || !intent.NextAttemptAt.Time.After(now) {
			intent.NextAttemptAt = p.NextAttemptAt
			s.intents[id] = intent
			claimed = append(claimed, intent)
		}
	}
	return claimed, nil
}

func (s *fakeStore) DeleteReconciliationIntent(_ context.Context, docID string) (pgconn.CommandTag, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.deleteIntentCalls++
	if s.deleteIntentErr != nil {
		return pgconn.CommandTag{}, s.deleteIntentErr
	}
	docStatus := s.document.Status
	if s.documents != nil {
		if doc, ok := s.documents[docID]; ok {
			docStatus = doc.Status
		}
	}
	if docStatus == "completed" || docStatus == "failed" {
		delete(s.intents, docID)
		return pgconn.NewCommandTag("DELETE 1"), nil
	}
	return pgconn.NewCommandTag("DELETE 0"), nil
}

func (s *fakeStore) RescheduleReconciliationIntent(_ context.Context, p db.RescheduleReconciliationIntentParams) (db.DocumentReconciliationIntent, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.rescheduleIntentCalls++
	if s.rescheduleIntentErr != nil {
		return db.DocumentReconciliationIntent{}, s.rescheduleIntentErr
	}
	intent, ok := s.intents[p.DocumentID]
	if !ok {
		return db.DocumentReconciliationIntent{}, pgx.ErrNoRows
	}
	intent.RetryCount++
	intent.NextAttemptAt = p.NextAttemptAt
	intent.LastErrorClass = p.LastErrorClass
	s.intents[p.DocumentID] = intent
	return intent, nil
}

func (s *fakeStore) GetReconciliationIntent(_ context.Context, docID string) (db.DocumentReconciliationIntent, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	intent, ok := s.intents[docID]
	if !ok {
		return db.DocumentReconciliationIntent{}, pgx.ErrNoRows
	}
	return intent, nil
}

func multipartRequest(t *testing.T, filename string, contents []byte) *http.Request {
	t.Helper()
	var body bytes.Buffer
	w := multipart.NewWriter(&body)
	part, err := w.CreateFormFile("file", filename)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := part.Write(contents); err != nil {
		t.Fatal(err)
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(http.MethodPost, "/documents", &body)
	req.Header.Set("Content-Type", w.FormDataContentType())
	return req
}

func TestCreateDocumentMapsFullQueueTo429(t *testing.T) {
	store := &fakeStore{}
	engine := engineFunc{ingest: func(context.Context, string, string, string, int, int, []byte) IngestOutcome {
		return IngestOutcome{Err: status.Error(codes.ResourceExhausted, "full")}
	}}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, multipartRequest(t, "../notes.txt", []byte("hello")))
	if recorder.Code != http.StatusTooManyRequests {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusTooManyRequests)
	}
	if store.inserted == nil || store.inserted.Filename != "notes.txt" || store.inserted.FileSize != 5 {
		t.Fatalf("unexpected insert params: %#v", store.inserted)
	}
	if !regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`).MatchString(store.inserted.ID) {
		t.Fatalf("document id is not UUIDv4: %q", store.inserted.ID)
	}
	if store.inserted.ChunkSize != defaultChunkSize || store.inserted.ChunkOverlap != defaultChunkOverlap {
		t.Fatalf("defaults = %d/%d", store.inserted.ChunkSize, store.inserted.ChunkOverlap)
	}
	if store.updated == nil || store.updated.Status != "failed" || !store.updated.ErrorMessage.Valid {
		t.Fatalf("queue failure was not compensated: %#v", store.updated)
	}
}

func TestCreateDocumentCompensatesGeneralEnqueueFailure(t *testing.T) {
	store := &fakeStore{}
	engine := engineFunc{ingest: func(context.Context, string, string, string, int, int, []byte) IngestOutcome { return IngestOutcome{Err: errors.New("engine down")} }}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, multipartRequest(t, "notes.txt", []byte("hello")))
	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("status = %d", recorder.Code)
	}
	if store.updated == nil || store.updated.Status != "failed" {
		t.Fatalf("failure was not compensated: %#v", store.updated)
	}
}

func TestCreateDocumentCompensatesWithDetachedContextAfterRequestCancellation(t *testing.T) {
	store := &fakeStore{rejectCanceledContext: true}
	req := multipartRequest(t, "notes.txt", []byte("hello"))
	requestCtx, cancelRequest := context.WithCancel(req.Context())
	req = req.WithContext(requestCtx)
	engine := engineFunc{ingest: func(context.Context, string, string, string, int, int, []byte) IngestOutcome {
		cancelRequest()
		return IngestOutcome{Err: errors.New("engine canceled before enqueue")}
	}}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)
	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusBadGateway)
	}
	if store.updated == nil || store.updated.Status != "failed" {
		t.Fatalf("canceled-request failure was not compensated: %#v", store.updated)
	}
	if !store.updateSawLiveContext {
		t.Fatal("compensation used an already-canceled context")
	}
	if store.updateCtx == nil {
		t.Fatal("compensation context was not recorded")
	}
	if _, ok := store.updateCtx.Deadline(); !ok {
		t.Fatal("compensation context has no finite deadline")
	}
	if store.updateCtx.Err() == nil {
		t.Fatal("compensation context was not canceled after the update")
	}
}

func TestCreateDocumentReturnsPollingLocation(t *testing.T) {
	store := &fakeStore{}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engineFunc{}, logger: zap.NewNop()}.routes().ServeHTTP(recorder, multipartRequest(t, "notes.txt", []byte("hello")))
	if recorder.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusAccepted)
	}
	if got, want := recorder.Header().Get("Location"), "/documents/"+store.inserted.ID; got != want {
		t.Fatalf("Location = %q, want %q", got, want)
	}
}

func TestCreateDocumentConvergesLostAcknowledgement(t *testing.T) {
	store := &fakeStore{}
	engine := engineFunc{
		ingest: func(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, b []byte) IngestOutcome {
			return IngestOutcome{Ambiguous: true, Err: errors.New("stream closed abruptly")}
		},
		status: &pb.GetIngestionStatusResponse{Status: "queued"},
	}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, multipartRequest(t, "notes.txt", []byte("hello")))
	if recorder.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusAccepted)
	}
	if store.updated != nil && store.updated.Status == "failed" {
		t.Fatalf("accepted engine state was wrongly compensated to failed: %#v", store.updated)
	}
}

func TestCreateDocumentRejectsMismatchedAdmissionIdentity(t *testing.T) {
	store := &fakeStore{}
	engine := engineFunc{
		ingest: func(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, b []byte) IngestOutcome {
			return IngestOutcome{Err: errors.New("mismatched id")}
		},
	}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, multipartRequest(t, "notes.txt", []byte("hello")))
	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusBadGateway)
	}
}

func TestGetDocumentPollsAndPersistsNonTerminalStatus(t *testing.T) {
	store := &fakeStore{document: db.Document{ID: "doc-1", Filename: "notes.txt", Status: "queued"}}
	engine := engineFunc{status: &pb.GetIngestionStatusResponse{DocumentId: "doc-1", Status: "completed", ChunkCount: 3}}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/documents/doc-1", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusOK)
	}
	if store.updated == nil || store.updated.Status != "completed" || store.updated.ChunkCount != 3 {
		t.Fatalf("unexpected status update: %#v", store.updated)
	}
	if store.updated.ErrorMessage != (pgtype.Text{}) {
		t.Fatalf("unexpected error message: %#v", store.updated.ErrorMessage)
	}
}

func TestGetDocumentDoesNotPersistNonTerminalEngineStatus(t *testing.T) {
	store := &fakeStore{document: db.Document{ID: "doc-1", Filename: "notes.txt", Status: "queued"}}
	engine := engineFunc{status: &pb.GetIngestionStatusResponse{DocumentId: "doc-1", Status: "processing"}}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/documents/doc-1", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusOK)
	}
	if store.updated != nil {
		t.Fatalf("non-terminal status must not be persisted: %#v", store.updated)
	}
}

func TestGetDocumentPersistsFailedStatusAndError(t *testing.T) {
	store := &fakeStore{document: db.Document{ID: "doc-1", Filename: "notes.txt", Status: "processing"}}
	engine := engineFunc{status: &pb.GetIngestionStatusResponse{DocumentId: "doc-1", Status: "failed", ErrorMessage: "embedding failed"}}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/documents/doc-1", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusOK)
	}
	if store.updated == nil || store.updated.Status != "failed" {
		t.Fatalf("failed status was not persisted: %#v", store.updated)
	}
	if !store.updated.ErrorMessage.Valid || store.updated.ErrorMessage.String != "embedding failed" {
		t.Fatalf("unexpected error message: %#v", store.updated.ErrorMessage)
	}
}

func TestGetDocumentRejectsMismatchedStatusIdentity(t *testing.T) {
	store := &fakeStore{document: db.Document{ID: "doc-1", Filename: "notes.txt", Status: "queued"}}
	engine := engineFunc{status: &pb.GetIngestionStatusResponse{DocumentId: "other-id", Status: "completed", ChunkCount: 3}}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/documents/doc-1", nil))
	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusBadGateway)
	}
	if store.updated != nil {
		t.Fatalf("mismatched status updated store: %#v", store.updated)
	}
}

func TestGetDocumentReturnsTerminalRaceWinner(t *testing.T) {
	winner := db.Document{ID: "doc-1", Filename: "notes.txt", Status: "completed", ChunkCount: 9}
	store := &fakeStore{document: db.Document{ID: "doc-1", Filename: "notes.txt", Status: "queued"}, updateErr: pgx.ErrNoRows, winner: &winner}
	engine := engineFunc{status: &pb.GetIngestionStatusResponse{DocumentId: "doc-1", Status: "completed", ChunkCount: 3}}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/documents/doc-1", nil))
	if recorder.Code != http.StatusOK || store.getCalls != 2 {
		t.Fatalf("status/calls = %d/%d", recorder.Code, store.getCalls)
	}
}

func TestGetDocumentRejectsNonterminalRaceReread(t *testing.T) {
	store := &fakeStore{document: db.Document{ID: "doc-1", Filename: "notes.txt", Status: "queued"}, updateErr: pgx.ErrNoRows}
	engine := engineFunc{status: &pb.GetIngestionStatusResponse{DocumentId: "doc-1", Status: "completed", ChunkCount: 3}}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/documents/doc-1", nil))
	if recorder.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d", recorder.Code)
	}
}

func TestCompensationRetriesUntilTerminalConvergence(t *testing.T) {
	store := &fakeStore{updateErrs: []error{errors.New("db busy"), errors.New("db busy")}}
	noSleep := func(int) {}
	a := app{store: store, logger: zap.NewNop(), retrySleep: noSleep}
	a.compensateFailedIngest("doc-1", errors.New("ingest error"))
	if store.updated == nil || store.updated.Status != "failed" {
		t.Fatalf("compensation failed to converge: %#v", store.updated)
	}
	if store.updateCalls != 3 {
		t.Fatalf("updateCalls = %d, want 3", store.updateCalls)
	}
}

func TestCompensationAcceptsTerminalRaceWinner(t *testing.T) {
	winner := db.Document{ID: "doc-1", Status: "completed"}
	store := &fakeStore{updateErr: pgx.ErrNoRows, winner: &winner}
	noSleep := func(int) {}
	a := app{store: store, logger: zap.NewNop(), retrySleep: noSleep}
	a.compensateFailedIngest("doc-1", errors.New("ingest error"))
	if store.getCalls < 1 {
		t.Fatalf("getCalls = %d, expected winner check", store.getCalls)
	}
}

func TestGetDocumentRepairsAuthoritativeEngineNotFound(t *testing.T) {
	store := &fakeStore{document: db.Document{ID: "doc-1", Filename: "notes.txt", Status: "queued"}}
	engine := engineFunc{statusErr: status.Error(codes.NotFound, "not found")}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/documents/doc-1", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusOK)
	}
	if store.updated == nil || store.updated.Status != "failed" {
		t.Fatalf("NotFound was not repaired: %#v", store.updated)
	}
}

func TestGetDocumentLeavesTransientEngineFailureQueued(t *testing.T) {
	store := &fakeStore{document: db.Document{ID: "doc-1", Filename: "notes.txt", Status: "queued"}}
	engine := engineFunc{statusErr: status.Error(codes.Unavailable, "engine unavailable")}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/documents/doc-1", nil))
	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusBadGateway)
	}
	if store.updated != nil {
		t.Fatalf("transient error updated store: %#v", store.updated)
	}
}

func TestCreateDocumentChunkSizeBoundaries(t *testing.T) {
	t.Run("boundary 1048576 accepted", func(t *testing.T) {
		store := &fakeStore{}
		var body bytes.Buffer
		w := multipart.NewWriter(&body)
		part, _ := w.CreateFormFile("file", "notes.txt")
		part.Write([]byte("hello"))
		w.WriteField("chunk_size", "1048576")
		w.WriteField("chunk_overlap", "50")
		w.Close()

		req := httptest.NewRequest(http.MethodPost, "/documents", &body)
		req.Header.Set("Content-Type", w.FormDataContentType())

		engineCalled := false
		var passedChunkSize int
		engine := engineFunc{ingest: func(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, b []byte) IngestOutcome {
			engineCalled = true
			passedChunkSize = chunkSize
			return IngestOutcome{}
		}}

		recorder := httptest.NewRecorder()
		app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)
		if recorder.Code != http.StatusAccepted {
			t.Fatalf("status = %d, want 202", recorder.Code)
		}
		if store.inserted == nil {
			t.Fatal("expected store insert")
		}
		if store.inserted.ChunkSize != 1048576 {
			t.Fatalf("stored chunkSize = %d, want 1048576", store.inserted.ChunkSize)
		}
		if !engineCalled || passedChunkSize != 1048576 {
			t.Fatalf("engine called=%v with chunkSize=%d, want 1048576", engineCalled, passedChunkSize)
		}
	})

	t.Run("1048577 rejected with 400", func(t *testing.T) {
		store := &fakeStore{}
		engineCalled := false
		engine := engineFunc{ingest: func(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, b []byte) IngestOutcome {
			engineCalled = true
			return IngestOutcome{}
		}}
		var body bytes.Buffer
		w := multipart.NewWriter(&body)
		part, _ := w.CreateFormFile("file", "notes.txt")
		part.Write([]byte("hello"))
		w.WriteField("chunk_size", "1048577")
		w.Close()

		req := httptest.NewRequest(http.MethodPost, "/documents", &body)
		req.Header.Set("Content-Type", w.FormDataContentType())

		recorder := httptest.NewRecorder()
		app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)
		if recorder.Code != http.StatusBadRequest {
			t.Fatalf("status = %d, want 400", recorder.Code)
		}
		if store.inserted != nil {
			t.Fatalf("unexpected store insert: %#v", store.inserted)
		}
		if engineCalled {
			t.Fatal("engine was called for rejected chunk_size")
		}
	})

	t.Run("2147483648 rejected with 400", func(t *testing.T) {
		store := &fakeStore{}
		engineCalled := false
		engine := engineFunc{ingest: func(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, b []byte) IngestOutcome {
			engineCalled = true
			return IngestOutcome{}
		}}
		var body bytes.Buffer
		w := multipart.NewWriter(&body)
		part, _ := w.CreateFormFile("file", "notes.txt")
		part.Write([]byte("hello"))
		w.WriteField("chunk_size", "2147483648")
		w.Close()

		req := httptest.NewRequest(http.MethodPost, "/documents", &body)
		req.Header.Set("Content-Type", w.FormDataContentType())

		recorder := httptest.NewRecorder()
		app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)
		if recorder.Code != http.StatusBadRequest {
			t.Fatalf("status = %d, want 400", recorder.Code)
		}
		if store.inserted != nil {
			t.Fatalf("unexpected store insert: %#v", store.inserted)
		}
		if engineCalled {
			t.Fatal("engine was called for overflow chunk_size")
		}
	})
}

func TestGetDocumentRecoverableStagingRemainsQueued(t *testing.T) {
	store := &fakeStore{document: db.Document{ID: "doc-1", Filename: "notes.txt", Status: "queued"}}
	engine := engineFunc{status: &pb.GetIngestionStatusResponse{DocumentId: "doc-1", Status: "queued"}}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/documents/doc-1", nil))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusOK)
	}
	if store.updateCalls != 0 {
		t.Fatalf("queued staging status triggered unexpected updateCalls: %d", store.updateCalls)
	}
	if store.updated != nil {
		t.Fatalf("queued staging status modified store: %#v", store.updated)
	}
}

func TestGetDocumentNotFoundMarksFailedAfterRustConfirmsAbsence(t *testing.T) {
	t.Run("NotFound marks failed in store", func(t *testing.T) {
		store := &fakeStore{document: db.Document{ID: "doc-1", Filename: "notes.txt", Status: "queued"}}
		engine := engineFunc{statusErr: status.Error(codes.NotFound, "not found in registry or staging")}
		recorder := httptest.NewRecorder()
		app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/documents/doc-1", nil))
		if recorder.Code != http.StatusOK {
			t.Fatalf("status = %d, want %d", recorder.Code, http.StatusOK)
		}
		if store.updated == nil || store.updated.Status != "failed" {
			t.Fatalf("NotFound did not mark document as failed: %#v", store.updated)
		}
	})

	t.Run("NotFound returns terminal winner if update loses race", func(t *testing.T) {
		winner := db.Document{ID: "doc-1", Filename: "notes.txt", Status: "completed", ChunkCount: 5}
		store := &fakeStore{document: db.Document{ID: "doc-1", Filename: "notes.txt", Status: "queued"}, updateErr: pgx.ErrNoRows, winner: &winner}
		engine := engineFunc{statusErr: status.Error(codes.NotFound, "not found")}
		recorder := httptest.NewRecorder()
		app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/documents/doc-1", nil))
		if recorder.Code != http.StatusOK {
			t.Fatalf("status = %d, want %d", recorder.Code, http.StatusOK)
		}
		if store.getCalls != 2 {
			t.Fatalf("getCalls = %d, want 2", store.getCalls)
		}
	})
}

type engineFunc struct {
	ingest    func(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, b []byte) IngestOutcome
	status    *pb.GetIngestionStatusResponse
	statusErr error
}

func (e engineFunc) Ingest(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, src io.Reader) IngestOutcome {
	data, err := io.ReadAll(src)
	if err != nil {
		return IngestOutcome{Err: err}
	}
	if e.ingest == nil {
		return IngestOutcome{}
	}
	return e.ingest(ctx, id, filename, strategy, chunkSize, chunkOverlap, data)
}

func (e engineFunc) IngestionStatus(ctx context.Context, id string) (*pb.GetIngestionStatusResponse, error) {
	if e.statusErr != nil {
		return nil, e.statusErr
	}
	if e.status == nil {
		return nil, errors.New("status unavailable")
	}
	docID := e.status.DocumentId
	if docID == "" {
		docID = id
	}
	return &pb.GetIngestionStatusResponse{
		DocumentId:   docID,
		Status:       e.status.Status,
		ChunkCount:   e.status.ChunkCount,
		ErrorMessage: e.status.ErrorMessage,
	}, nil
}

func (engineFunc) Ping(context.Context) (time.Duration, error) { return time.Millisecond, nil }

func TestCreateDocumentChunkSettingsContract(t *testing.T) {
	t.Run("omitted settings use defaults", func(t *testing.T) {
		store := &fakeStore{}
		recorder := httptest.NewRecorder()
		app{store: store, engine: engineFunc{}, logger: zap.NewNop()}.routes().ServeHTTP(recorder, multipartRequest(t, "notes.txt", []byte("hello")))
		if recorder.Code != http.StatusAccepted {
			t.Fatalf("status = %d, want %d", recorder.Code, http.StatusAccepted)
		}
		if store.inserted == nil {
			t.Fatal("expected insert params")
		}
		if store.inserted.ChunkStrategy != "structure-aware" || store.inserted.ChunkSize != 500 || store.inserted.ChunkOverlap != 50 {
			t.Fatalf("unexpected inserted chunk params: %#v", store.inserted)
		}
	})

	t.Run("custom valid fixed-size settings", func(t *testing.T) {
		store := &fakeStore{}
		var body bytes.Buffer
		w := multipart.NewWriter(&body)
		part, _ := w.CreateFormFile("file", "notes.txt")
		part.Write([]byte("hello"))
		w.WriteField("chunk_strategy", "fixed-size")
		w.WriteField("chunk_size", "800")
		w.WriteField("chunk_overlap", "100")
		w.Close()

		req := httptest.NewRequest(http.MethodPost, "/documents", &body)
		req.Header.Set("Content-Type", w.FormDataContentType())

		recorder := httptest.NewRecorder()
		app{store: store, engine: engineFunc{}, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)
		if recorder.Code != http.StatusAccepted {
			t.Fatalf("status = %d, want %d", recorder.Code, http.StatusAccepted)
		}
		if store.inserted.ChunkStrategy != "fixed-size" || store.inserted.ChunkSize != 800 || store.inserted.ChunkOverlap != 100 {
			t.Fatalf("unexpected custom chunk params: %#v", store.inserted)
		}
	})

	t.Run("json document converts to fixed-size", func(t *testing.T) {
		store := &fakeStore{}
		recorder := httptest.NewRecorder()
		app{store: store, engine: engineFunc{}, logger: zap.NewNop()}.routes().ServeHTTP(recorder, multipartRequest(t, "doc.json", []byte("{}")))
		if recorder.Code != http.StatusAccepted {
			t.Fatalf("status = %d, want %d", recorder.Code, http.StatusAccepted)
		}
		if store.inserted.ChunkStrategy != "fixed-size" {
			t.Fatalf("expected json to persist as fixed-size, got %q", store.inserted.ChunkStrategy)
		}
	})

	t.Run("invalid strategy returns 400", func(t *testing.T) {
		store := &fakeStore{}
		var body bytes.Buffer
		w := multipart.NewWriter(&body)
		part, _ := w.CreateFormFile("file", "notes.txt")
		part.Write([]byte("hello"))
		w.WriteField("chunk_strategy", "invalid-strategy")
		w.Close()

		req := httptest.NewRequest(http.MethodPost, "/documents", &body)
		req.Header.Set("Content-Type", w.FormDataContentType())

		recorder := httptest.NewRecorder()
		app{store: store, engine: engineFunc{}, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)
		if recorder.Code != http.StatusBadRequest {
			t.Fatalf("status = %d, want 400", recorder.Code)
		}
	})

	t.Run("invalid size returns 400", func(t *testing.T) {
		store := &fakeStore{}
		var body bytes.Buffer
		w := multipart.NewWriter(&body)
		part, _ := w.CreateFormFile("file", "notes.txt")
		part.Write([]byte("hello"))
		w.WriteField("chunk_size", "0")
		w.Close()

		req := httptest.NewRequest(http.MethodPost, "/documents", &body)
		req.Header.Set("Content-Type", w.FormDataContentType())

		recorder := httptest.NewRecorder()
		app{store: store, engine: engineFunc{}, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)
		if recorder.Code != http.StatusBadRequest {
			t.Fatalf("status = %d, want 400", recorder.Code)
		}
	})

	t.Run("overlap >= size returns 400", func(t *testing.T) {
		store := &fakeStore{}
		var body bytes.Buffer
		w := multipart.NewWriter(&body)
		part, _ := w.CreateFormFile("file", "notes.txt")
		part.Write([]byte("hello"))
		w.WriteField("chunk_size", "500")
		w.WriteField("chunk_overlap", "500")
		w.Close()

		req := httptest.NewRequest(http.MethodPost, "/documents", &body)
		req.Header.Set("Content-Type", w.FormDataContentType())

		recorder := httptest.NewRecorder()
		app{store: store, engine: engineFunc{}, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)
		if recorder.Code != http.StatusBadRequest {
			t.Fatalf("status = %d, want 400", recorder.Code)
		}
	})
}

type fakeStream struct {
	pb.LancetService_IngestDocumentClient
	requests []*pb.IngestDocumentRequest
}

func (f *fakeStream) Send(req *pb.IngestDocumentRequest) error {
	f.requests = append(f.requests, req)
	return nil
}

func (f *fakeStream) CloseAndRecv() (*pb.IngestDocumentResponse, error) {
	if len(f.requests) > 0 {
		return &pb.IngestDocumentResponse{DocumentId: f.requests[0].DocumentId, Success: true}, nil
	}
	return &pb.IngestDocumentResponse{Success: true}, nil
}

type fakeGrpcClient struct {
	pb.LancetServiceClient
	stream pb.LancetService_IngestDocumentClient
}

func (f *fakeGrpcClient) IngestDocument(ctx context.Context, opts ...grpc.CallOption) (pb.LancetService_IngestDocumentClient, error) {
	return f.stream, nil
}

func TestGrpcEngineStreamsChunkSettings(t *testing.T) {
	stream := &fakeStream{}
	engine := grpcEngine{client: &fakeGrpcClient{stream: stream}}
	ctx := t.Context()
	outcome := engine.Ingest(ctx, "doc-123", "guide.md", "structure-aware", 500, 50, bytes.NewReader([]byte("chunk data payload")))
	if outcome.Err != nil {
		t.Fatalf("unexpected ingest error: %v", outcome.Err)
	}
	if len(stream.requests) == 0 {
		t.Fatal("expected gRPC stream requests")
	}
	first := stream.requests[0]
	if first.Metadata == nil {
		t.Fatal("expected first frame metadata")
	}
	if first.Metadata["chunk_strategy"] != "structure-aware" || first.Metadata["chunk_size"] != "500" || first.Metadata["chunk_overlap"] != "50" {
		t.Fatalf("unexpected first frame metadata: %#v", first.Metadata)
	}
	for i, req := range stream.requests[1:] {
		if req.Metadata != nil {
			t.Fatalf("subsequent frame %d carried metadata: %#v", i+1, req.Metadata)
		}
	}
}

func TestGatewayAddressIsLoopback(t *testing.T) {
	if got, want := formatListenAddr("8080"), "127.0.0.1:8080"; got != want {
		t.Fatalf("formatListenAddr(\"8080\") = %q, want %q", got, want)
	}
	if got, want := formatListenAddr("127.0.0.1:9090"), "127.0.0.1:9090"; got != want {
		t.Fatalf("formatListenAddr(\"127.0.0.1:9090\") = %q, want %q", got, want)
	}
}

func TestDurableReconcilerMoreThanFiveFailures(t *testing.T) {
	store := &fakeStore{updateErr: errors.New("db busy")}
	noSleep := func(int) {}
	engine := engineFunc{ingest: func(context.Context, string, string, string, int, int, []byte) IngestOutcome {
		return IngestOutcome{Err: status.Error(codes.ResourceExhausted, "full")}
	}}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop(), retrySleep: noSleep}.routes().ServeHTTP(recorder, multipartRequest(t, "notes.txt", []byte("hello")))
	if recorder.Code != http.StatusTooManyRequests {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusTooManyRequests)
	}
	if store.updateCalls != 5 {
		t.Fatalf("updateCalls = %d, want 5", store.updateCalls)
	}
	if store.inserted == nil {
		t.Fatal("expected inserted params")
	}
	docID := store.inserted.ID
	intent, err := store.GetReconciliationIntent(t.Context(), docID)
	if err != nil {
		t.Fatalf("expected reconciliation intent for %s: %v", docID, err)
	}
	if intent.DesiredStatus != "failed" || intent.ReasonClass != "failed_admission" {
		t.Fatalf("unexpected intent content: %#v", intent)
	}
}

func TestDurableReconcilerConvergesWithoutGet(t *testing.T) {
	doc := db.Document{ID: "doc-1", Filename: "notes.txt", Status: "queued"}
	store := &fakeStore{document: doc}
	_, err := store.CreateReconciliationIntent(t.Context(), db.CreateReconciliationIntentParams{
		ID:            "doc-1",
		DesiredStatus: "failed",
		ReasonClass:   "failed_admission",
	})
	if err != nil {
		t.Fatalf("create intent error: %v", err)
	}
	rec := newDurableReconciler(store, zap.NewNop())
	rec.reconcileBatch(t.Context())

	if store.document.Status != "failed" {
		t.Fatalf("status = %q, want failed", store.document.Status)
	}
	if _, err := store.GetReconciliationIntent(t.Context(), "doc-1"); !errors.Is(err, pgx.ErrNoRows) {
		t.Fatalf("expected intent deleted, got: %v", err)
	}
	if store.getCalls != 0 {
		t.Fatalf("getCalls = %d, want 0 (converged without client/reconciler GET)", store.getCalls)
	}
}

func TestDurableReconcilerIgnoresRequestCancellation(t *testing.T) {
	store := &fakeStore{rejectCanceledContext: true, updateErr: errors.New("db unavailable")}
	noSleep := func(int) {}
	req := multipartRequest(t, "notes.txt", []byte("hello"))
	reqCtx, cancelReq := context.WithCancel(req.Context())
	req = req.WithContext(reqCtx)

	engine := engineFunc{ingest: func(context.Context, string, string, string, int, int, []byte) IngestOutcome {
		cancelReq()
		return IngestOutcome{Err: errors.New("engine unreachable")}
	}}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop(), retrySleep: noSleep}.routes().ServeHTTP(recorder, req)
	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusBadGateway)
	}
	if store.createIntentCalls != 1 {
		t.Fatalf("createIntentCalls = %d, want 1", store.createIntentCalls)
	}
	if store.inserted == nil {
		t.Fatal("expected insert params")
	}
	if _, err := store.GetReconciliationIntent(context.Background(), store.inserted.ID); err != nil {
		t.Fatalf("intent was not persisted despite request cancellation: %v", err)
	}
}

func TestDurableReconcilerRestartRecovery(t *testing.T) {
	doc := db.Document{ID: "doc-1", Filename: "notes.txt", Status: "queued"}
	store := &fakeStore{document: doc, updateErr: errors.New("temporary DB error")}
	_, _ = store.CreateReconciliationIntent(t.Context(), db.CreateReconciliationIntentParams{
		ID:            "doc-1",
		DesiredStatus: "failed",
		ReasonClass:   "failed_admission",
	})

	// Reconciler 1 runs a cycle during DB outage
	rec1 := newDurableReconciler(store, zap.NewNop())
	rec1.reconcileBatch(t.Context())

	// Intent remains, retry count incremented
	intent, err := store.GetReconciliationIntent(t.Context(), "doc-1")
	if err != nil {
		t.Fatalf("expected intent to survive outage: %v", err)
	}
	if intent.RetryCount != 1 {
		t.Fatalf("retryCount = %d, want 1", intent.RetryCount)
	}

	// Reconciler 1 stops (process exit). DB recovers. Reconciler 2 starts over same store.
	store.mu.Lock()
	store.updateErr = nil
	// Reset NextAttemptAt to now so it is due for rec2
	intent.NextAttemptAt = pgtype.Timestamp{Time: time.Now(), Valid: true}
	store.intents["doc-1"] = intent
	store.mu.Unlock()

	rec2 := newDurableReconciler(store, zap.NewNop())
	rec2.reconcileBatch(t.Context())

	if store.document.Status != "failed" {
		t.Fatalf("status = %q, want failed after restart", store.document.Status)
	}
	if _, err := store.GetReconciliationIntent(t.Context(), "doc-1"); !errors.Is(err, pgx.ErrNoRows) {
		t.Fatalf("intent was not cleaned up after restart: %v", err)
	}
}

func TestDurableReconcilerPreservesTerminalWinner(t *testing.T) {
	winner := db.Document{ID: "doc-1", Filename: "notes.txt", Status: "completed", ChunkCount: 15}
	store := &fakeStore{document: winner, updateErr: pgx.ErrNoRows, winner: &winner}
	store.intents = map[string]db.DocumentReconciliationIntent{
		"doc-1": {DocumentID: "doc-1", DesiredStatus: "failed", ReasonClass: "failed_admission"},
	}

	rec := newDurableReconciler(store, zap.NewNop())
	rec.reconcileBatch(t.Context())

	if store.document.Status != "completed" {
		t.Fatalf("terminal completed winner was overwritten: status = %q", store.document.Status)
	}
	if _, err := store.GetReconciliationIntent(t.Context(), "doc-1"); !errors.Is(err, pgx.ErrNoRows) {
		t.Fatalf("stale intent was not deleted for terminal winner: %v", err)
	}
}

func TestDurableReconcilerBoundedBatchAndBackoff(t *testing.T) {
	store := &fakeStore{
		documents: map[string]db.Document{
			"doc-1": {ID: "doc-1", Status: "queued"},
			"doc-2": {ID: "doc-2", Status: "queued"},
		},
		updateErrs: []error{errors.New("db error for doc-1")},
	}
	now := time.Now()
	store.intents = map[string]db.DocumentReconciliationIntent{
		"doc-1": {DocumentID: "doc-1", DesiredStatus: "failed", NextAttemptAt: pgtype.Timestamp{Time: now, Valid: true}},
		"doc-2": {DocumentID: "doc-2", DesiredStatus: "failed", NextAttemptAt: pgtype.Timestamp{Time: now, Valid: true}},
	}

	rec := newDurableReconciler(store, zap.NewNop())
	rec.reconcileBatch(t.Context())

	// doc-2 should have succeeded and its intent deleted
	doc2 := store.documents["doc-2"]
	if doc2.Status != "failed" {
		t.Fatalf("doc-2 status = %q, want failed", doc2.Status)
	}
	if _, err := store.GetReconciliationIntent(t.Context(), "doc-2"); !errors.Is(err, pgx.ErrNoRows) {
		t.Fatalf("doc-2 intent was not deleted: %v", err)
	}

	// doc-1 should have failed and its intent rescheduled
	intent1, err := store.GetReconciliationIntent(t.Context(), "doc-1")
	if err != nil {
		t.Fatalf("doc-1 intent should still exist: %v", err)
	}
	if intent1.RetryCount != 1 {
		t.Fatalf("doc-1 retryCount = %d, want 1", intent1.RetryCount)
	}
	if !intent1.LastErrorClass.Valid || intent1.LastErrorClass.String != "reconciliation_update_failed" {
		t.Fatalf("unexpected last error class: %#v", intent1.LastErrorClass)
	}
}

func TestDurableReconcilerStopsCleanly(t *testing.T) {
	store := &fakeStore{}
	rec := newDurableReconciler(store, zap.NewNop())
	rec.interval = 5 * time.Millisecond

	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan struct{})
	go func() {
		rec.Run(ctx)
		close(done)
	}()

	time.Sleep(20 * time.Millisecond)
	cancel()

	select {
	case <-done:
		// Stopped cleanly
	case <-time.After(1 * time.Second):
		t.Fatal("reconciler did not stop within timeout after context cancellation")
	}
}
