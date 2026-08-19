package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"maps"
	"math"
	"mime/multipart"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
	"go.uber.org/zap"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"

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
	for _, id := range slices.Sorted(maps.Keys(s.intents)) {
		intent := s.intents[id]
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
	engine := engineFunc{ingest: func(context.Context, string, string, string, int, int, []byte) IngestOutcome {
		return IngestOutcome{Err: errors.New("engine down")}
	}}
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

type fakeQueryRAGStream struct {
	grpc.ClientStream
	ctx    context.Context
	events []*pb.WorkflowEvent
	index  int
	err    error
}

func (s *fakeQueryRAGStream) Recv() (*pb.WorkflowEvent, error) {
	if s.index >= len(s.events) {
		if s.err != nil {
			return nil, s.err
		}
		return nil, io.EOF
	}
	ev := s.events[s.index]
	s.index++
	return ev, nil
}

func (s *fakeQueryRAGStream) Header() (metadata.MD, error) {
	return nil, nil
}

func (s *fakeQueryRAGStream) Trailer() metadata.MD {
	if s.err != nil {
		if te, ok := s.err.(interface{ Trailer() metadata.MD }); ok {
			return te.Trailer()
		}
	}
	return nil
}

func (s *fakeQueryRAGStream) Context() context.Context {
	if s.ctx != nil {
		return s.ctx
	}
	return context.Background()
}

func newSingleResponseStream(resp *pb.QueryRAGResponse, err error) pb.LancetService_QueryRAGClient {
	if err != nil && resp == nil {
		return &fakeQueryRAGStream{err: err}
	}
	var events []*pb.WorkflowEvent
	if resp != nil {
		events = []*pb.WorkflowEvent{
			{
				SessionId:       resp.GetSessionId(),
				TraceId:         "00000000-0000-4000-8000-000000000099",
				SequenceOrdinal: 1,
				TimestampMs:     time.Now().UnixMilli(),
				Event: &pb.WorkflowEvent_NodeStarted{
					NodeStarted: &pb.NodeStartedEvent{
						NodeName:      "ReformulateQuery",
						InputsSummary: "inputs",
					},
				},
			},
			{
				SessionId:       resp.GetSessionId(),
				TraceId:         "00000000-0000-4000-8000-000000000099",
				SequenceOrdinal: 2,
				TimestampMs:     time.Now().UnixMilli(),
				Event: &pb.WorkflowEvent_FinalAnswer{
					FinalAnswer: &pb.FinalAnswerEvent{
						Response: resp,
					},
				},
			},
			{
				SessionId:       resp.GetSessionId(),
				TraceId:         "00000000-0000-4000-8000-000000000099",
				SequenceOrdinal: 3,
				TimestampMs:     time.Now().UnixMilli(),
				Event: &pb.WorkflowEvent_WorkflowCompleted{
					WorkflowCompleted: &pb.WorkflowCompletedEvent{
						Success:       true,
						FinalResponse: resp,
					},
				},
			},
		}
	}
	return &fakeQueryRAGStream{events: events, err: err}
}

type sseEvent struct {
	Event string
	Data  string
}

func parseSSEEvents(body string) []sseEvent {
	var events []sseEvent
	lines := strings.Split(body, "\n")
	var currentEvent, currentData string
	for _, line := range lines {
		line = strings.TrimRight(line, "\r")
		if strings.HasPrefix(line, "event: ") {
			currentEvent = strings.TrimPrefix(line, "event: ")
		} else if strings.HasPrefix(line, "data: ") {
			currentData = strings.TrimPrefix(line, "data: ")
		} else if line == "" && (currentEvent != "" || currentData != "") {
			events = append(events, sseEvent{Event: currentEvent, Data: currentData})
			currentEvent = ""
			currentData = ""
		}
	}
	if currentEvent != "" || currentData != "" {
		events = append(events, sseEvent{Event: currentEvent, Data: currentData})
	}
	return events
}

func parseTerminalResponseDTO(body string) (queryRAGResponseDTO, error) {
	events := parseSSEEvents(body)
	for _, ev := range events {
		if ev.Event == "final_answer" {
			var dto queryRAGResponseDTO
			err := json.Unmarshal([]byte(ev.Data), &dto)
			return dto, err
		}
		if ev.Event == "workflow_completed" {
			var wc struct {
				FinalResponse *queryRAGResponseDTO `json:"final_response"`
			}
			if err := json.Unmarshal([]byte(ev.Data), &wc); err == nil && wc.FinalResponse != nil {
				return *wc.FinalResponse, nil
			}
		}
	}
	return queryRAGResponseDTO{}, fmt.Errorf("no terminal response found in SSE body: %s", body)
}

type engineFunc struct {
	ingest    func(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, b []byte) IngestOutcome
	status    *pb.GetIngestionStatusResponse
	statusErr error
	queryRAG  func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error)
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

func (e engineFunc) QueryRAG(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
	if e.queryRAG != nil {
		return e.queryRAG(ctx, req)
	}
	return nil, errors.New("queryRAG unimplemented")
}

func (engineFunc) Ping(context.Context) (time.Duration, error) { return time.Millisecond, nil }

func TestRAGQueryNoResults(t *testing.T) {
	store := &fakeStore{}
	sessionID := "00000000-0000-4000-8000-000000000055"
	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			resp := &pb.QueryRAGResponse{
				Answer:              "",
				Citations:           []string{},
				SessionId:           sessionID,
				AnswerBasis:         pb.AnswerBasis_ANSWER_BASIS_UNSPECIFIED,
				StructuredCitations: []*pb.StructuredCitation{},
				Notices: []*pb.Notice{
					{
						Code:     "NO_EVIDENCE",
						Message:  "No completed corpus evidence matched the requested filters.",
						Severity: pb.NoticeSeverity_NOTICE_SEVERITY_INFO,
					},
				},
				Snapshot: &pb.RetrievalSnapshot{
					IndexGeneration: "gen-1",
					EmbeddingModel:  "nvidia/llama-nemotron-embed-vl-1b-v2:free",
					VectorWeight:    0.5,
					Bm25Weight:      0.5,
					RrfK:            60,
					CandidateLimit:  20,
					FinalLimit:      5,
					ActiveFilter: &pb.DocumentFilter{
						DocumentIds:  []string{"00000000-0000-4000-8000-000000000999"},
						ContentTypes: []string{},
					},
					ResultHash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
				},
			}
			return newSingleResponseStream(resp, nil), nil
		},
	}

	bodyStr := `{"query":"test query","session_id":"` + sessionID + `"}`
	req := httptest.NewRequest(http.MethodPost, "/rag/query", strings.NewReader(bodyStr)).WithContext(t.Context())
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusOK)
	}

	dto, err := parseTerminalResponseDTO(recorder.Body.String())
	if err != nil {
		t.Fatalf("unmarshal error = %v", err)
	}

	if dto.Answer != "" {
		t.Fatalf("answer = %v, want empty string", dto.Answer)
	}
	if len(dto.Citations) != 0 {
		t.Fatalf("citations = %v, want empty array", dto.Citations)
	}
	if len(dto.StructuredCitations) != 0 {
		t.Fatalf("structured_citations = %v, want empty array", dto.StructuredCitations)
	}
	if dto.AnswerBasis != 0 {
		t.Fatalf("answer_basis = %v, want 0", dto.AnswerBasis)
	}
	if dto.SessionID != sessionID {
		t.Fatalf("session_id = %v, want %s", dto.SessionID, sessionID)
	}

	if len(dto.Notices) != 1 {
		t.Fatalf("notices = %v, want 1 notice", dto.Notices)
	}
	if dto.Notices[0].Code != "NO_EVIDENCE" {
		t.Fatalf("notice code = %v, want NO_EVIDENCE", dto.Notices[0].Code)
	}
	if dto.Notices[0].Message != "No completed corpus evidence matched the requested filters." {
		t.Fatalf("notice message = %v", dto.Notices[0].Message)
	}
	if dto.Notices[0].Severity != 1 {
		t.Fatalf("notice severity = %v, want 1", dto.Notices[0].Severity)
	}

	if dto.Snapshot == nil {
		t.Fatalf("snapshot is nil")
	}
}

func TestRAGQueryValidMapping(t *testing.T) {
	store := &fakeStore{}
	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			if req.GetQuery() != "what is lancet?" {
				t.Errorf("query = %q, want %q", req.GetQuery(), "what is lancet?")
			}
			resp := &pb.QueryRAGResponse{
				Answer:      "Lancet is a hybrid RAG system.",
				Citations:   []string{"doc-1#chunk-0"},
				SessionId:   "gen-sess-100",
				AnswerBasis: pb.AnswerBasis_ANSWER_BASIS_RETRIEVAL,
				StructuredCitations: []*pb.StructuredCitation{
					{
						DocumentId: "doc-1",
						Excerpt:    "Lancet RAG engine",
					},
				},
				Notices: []*pb.Notice{
					{
						Code:    "NOTICE_1",
						Message: "Retrieval complete",
					},
				},
				Snapshot: &pb.RetrievalSnapshot{
					CandidateLimit: 32,
				},
			}
			return newSingleResponseStream(resp, nil), nil
		},
	}

	reqBody := `{"query": "what is lancet?"}`
	req := httptest.NewRequest(http.MethodPost, "/rag/query", strings.NewReader(reqBody)).WithContext(t.Context())
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusOK)
	}

	dto, err := parseTerminalResponseDTO(recorder.Body.String())
	if err != nil {
		t.Fatalf("invalid sse response: %v", err)
	}

	if dto.Answer != "Lancet is a hybrid RAG system." {
		t.Errorf("answer = %v", dto.Answer)
	}
	if dto.SessionID != "gen-sess-100" {
		t.Errorf("session_id = %v", dto.SessionID)
	}
	if dto.AnswerBasis != int32(pb.AnswerBasis_ANSWER_BASIS_RETRIEVAL) {
		t.Errorf("answer_basis = %v", dto.AnswerBasis)
	}
	if len(dto.Citations) != 1 || dto.Citations[0] != "doc-1#chunk-0" {
		t.Errorf("citations = %v", dto.Citations)
	}
	if len(dto.StructuredCitations) != 1 {
		t.Errorf("structured_citations missing or invalid")
	}
	if len(dto.Notices) != 1 {
		t.Errorf("notices missing or invalid")
	}
	if dto.Snapshot == nil {
		t.Errorf("snapshot missing or invalid")
	}
}

func TestRAGQueryCallerSessionAndFilters(t *testing.T) {
	store := &fakeStore{}
	var receivedReq *pb.QueryRAGRequest
	var receivedSawLiveContext bool

	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			receivedReq = req
			receivedSawLiveContext = ctx.Err() == nil
			resp := &pb.QueryRAGResponse{
				Answer:    "Filtered answer",
				SessionId: req.GetSessionId(),
			}
			return newSingleResponseStream(resp, nil), nil
		},
	}

	body := `{"query":"test filter","session_id":"caller-sess-999","filter":{"document_ids":["doc-a","doc-b"],"content_types":["text/markdown"]}}`
	req := httptest.NewRequest(http.MethodPost, "/rag/query", strings.NewReader(body)).WithContext(t.Context())
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusOK)
	}

	if receivedReq == nil {
		t.Fatal("engine QueryRAG was not called")
	}
	if receivedReq.GetSessionId() != "caller-sess-999" {
		t.Errorf("session_id = %q, want caller-sess-999", receivedReq.GetSessionId())
	}
	if filter := receivedReq.GetFilter(); filter == nil {
		t.Fatal("filter is nil")
	} else {
		if !slices.Contains(filter.GetDocumentIds(), "doc-a") || !slices.Contains(filter.GetDocumentIds(), "doc-b") {
			t.Errorf("document_ids = %v", filter.GetDocumentIds())
		}
		if !slices.Contains(filter.GetContentTypes(), "text/markdown") {
			t.Errorf("content_types = %v", filter.GetContentTypes())
		}
	}
	if !receivedSawLiveContext {
		t.Errorf("request context not live during query execution")
	}
}

func TestRAGQueryRejectsUnknownOrTrailingJSON(t *testing.T) {
	store := &fakeStore{}
	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			return newSingleResponseStream(&pb.QueryRAGResponse{Answer: "should not be called"}, nil), nil
		},
	}
	router := app{store: store, engine: engine, logger: zap.NewNop()}.routes()

	tests := []struct {
		name string
		body string
	}{
		{"unknown field", `{"query":"test","unknown_field":"value"}`},
		{"trailing json", `{"query":"test"}{"extra":"data"}`},
		{"malformed json", `{"query":`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/rag/query", strings.NewReader(tt.body)).WithContext(t.Context())
			req.Header.Set("Content-Type", "application/json")
			recorder := httptest.NewRecorder()
			router.ServeHTTP(recorder, req)
			if recorder.Code != http.StatusBadRequest {
				t.Fatalf("[%s] status = %d, want 400", tt.name, recorder.Code)
			}
		})
	}
}

func TestRAGQueryInvalidArgumentStatus(t *testing.T) {
	store := &fakeStore{}
	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			return nil, status.Error(codes.InvalidArgument, "invalid query parameter: empty string")
		},
	}

	req := httptest.NewRequest(http.MethodPost, "/rag/query", strings.NewReader(`{"query":""}`)).WithContext(t.Context())
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)

	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusBadRequest)
	}
}

func TestRAGQueryProviderErrorPreservesIdentity(t *testing.T) {
	store := &fakeStore{}
	sessionID := "00000000-0000-4000-8000-000000000077"
	correlationID := "00000000-0000-4000-8000-000000000099"
	errKind := "provider_error"

	tr := metadata.Pairs(
		"x-lancet-session-id", sessionID,
		"x-lancet-correlation-id", correlationID,
		"x-lancet-error-kind", errKind,
	)
	failingErr := trailerError{
		err:     status.Error(codes.Internal, "OpenRouter API rate limit"),
		trailer: tr,
	}

	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			return nil, failingErr
		},
	}

	bodyStr := `{"query":"test query","session_id":"` + sessionID + `"}`
	req := httptest.NewRequest(http.MethodPost, "/rag/query", strings.NewReader(bodyStr)).WithContext(t.Context())
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)

	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusBadGateway)
	}

	if got := strings.TrimSpace(recorder.Body.String()); got != "engine query failed" {
		t.Fatalf("body = %q, want %q", got, "engine query failed")
	}

	if got := recorder.Header().Get("X-Lancet-Session-ID"); got != sessionID {
		t.Fatalf("X-Lancet-Session-ID = %q, want %q", got, sessionID)
	}

	if got := recorder.Header().Get("X-Lancet-Correlation-ID"); got != correlationID {
		t.Fatalf("X-Lancet-Correlation-ID = %q, want %q", got, correlationID)
	}

	if got := recorder.Header().Get("X-Lancet-Error-Kind"); got != errKind {
		t.Fatalf("X-Lancet-Error-Kind = %q, want %q", got, errKind)
	}
}

func TestRAGQueryEmbeddingTransportIdentity(t *testing.T) {
	store := &fakeStore{}
	sessionID := "00000000-0000-4000-8000-000000000088"
	correlationID := "00000000-0000-4000-8000-000000000099"
	errKind := "embedding_transport"

	tr := metadata.Pairs(
		"x-lancet-session-id", sessionID,
		"x-lancet-correlation-id", correlationID,
		"x-lancet-error-kind", errKind,
	)
	failingErr := trailerError{
		err:     status.Error(codes.Unavailable, "embedding provider unreachable"),
		trailer: tr,
	}

	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			return nil, failingErr
		},
	}

	bodyStr := `{"query":"test query","session_id":"` + sessionID + `"}`
	req := httptest.NewRequest(http.MethodPost, "/rag/query", strings.NewReader(bodyStr)).WithContext(t.Context())
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)

	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusBadGateway)
	}

	if got := strings.TrimSpace(recorder.Body.String()); got != "engine query failed" {
		t.Fatalf("body = %q, want %q", got, "engine query failed")
	}

	if got := recorder.Header().Get("X-Lancet-Session-ID"); got != sessionID {
		t.Fatalf("X-Lancet-Session-ID = %q, want %q", got, sessionID)
	}

	if got := recorder.Header().Get("X-Lancet-Correlation-ID"); got != correlationID {
		t.Fatalf("X-Lancet-Correlation-ID = %q, want %q", got, correlationID)
	}

	if got := recorder.Header().Get("X-Lancet-Error-Kind"); got != errKind {
		t.Fatalf("X-Lancet-Error-Kind = %q, want %q", got, errKind)
	}
}

func TestRAGQueryEmbeddingInvalidPayloadIdentity(t *testing.T) {
	store := &fakeStore{}
	sessionID := "00000000-0000-4000-8000-000000000088"
	correlationID := "00000000-0000-4000-8000-000000000099"
	errKind := "embedding_invalid_payload"

	tr := metadata.Pairs(
		"x-lancet-session-id", sessionID,
		"x-lancet-correlation-id", correlationID,
		"x-lancet-error-kind", errKind,
	)
	failingErr := trailerError{
		err:     status.Error(codes.Internal, "embedding payload invalid"),
		trailer: tr,
	}

	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			return nil, failingErr
		},
	}

	bodyStr := `{"query":"test query","session_id":"` + sessionID + `"}`
	req := httptest.NewRequest(http.MethodPost, "/rag/query", strings.NewReader(bodyStr)).WithContext(t.Context())
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)

	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusBadGateway)
	}

	if got := strings.TrimSpace(recorder.Body.String()); got != "engine query failed" {
		t.Fatalf("body = %q, want %q", got, "engine query failed")
	}

	if got := recorder.Header().Get("X-Lancet-Session-ID"); got != sessionID {
		t.Fatalf("X-Lancet-Session-ID = %q, want %q", got, sessionID)
	}

	if got := recorder.Header().Get("X-Lancet-Correlation-ID"); got != correlationID {
		t.Fatalf("X-Lancet-Correlation-ID = %q, want %q", got, correlationID)
	}

	if got := recorder.Header().Get("X-Lancet-Error-Kind"); got != errKind {
		t.Fatalf("X-Lancet-Error-Kind = %q, want %q", got, errKind)
	}
}

func TestRAGQueryDenseRetrievalIdentity(t *testing.T) {
	store := &fakeStore{}
	sessionID := "00000000-0000-4000-8000-000000000088"
	correlationID := "00000000-0000-4000-8000-000000000099"
	errKind := "dense_retrieval"

	tr := metadata.Pairs(
		"x-lancet-session-id", sessionID,
		"x-lancet-correlation-id", correlationID,
		"x-lancet-error-kind", errKind,
	)
	failingErr := trailerError{
		err:     status.Error(codes.Unavailable, "dense query failed"),
		trailer: tr,
	}

	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			return nil, failingErr
		},
	}

	bodyStr := `{"query":"test query","session_id":"` + sessionID + `"}`
	req := httptest.NewRequest(http.MethodPost, "/rag/query", strings.NewReader(bodyStr)).WithContext(t.Context())
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)

	if recorder.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusBadGateway)
	}

	if got := strings.TrimSpace(recorder.Body.String()); got != "engine query failed" {
		t.Fatalf("body = %q, want %q", got, "engine query failed")
	}

	if got := recorder.Header().Get("X-Lancet-Session-ID"); got != sessionID {
		t.Fatalf("X-Lancet-Session-ID = %q, want %q", got, sessionID)
	}

	if got := recorder.Header().Get("X-Lancet-Correlation-ID"); got != correlationID {
		t.Fatalf("X-Lancet-Correlation-ID = %q, want %q", got, correlationID)
	}

	if got := recorder.Header().Get("X-Lancet-Error-Kind"); got != errKind {
		t.Fatalf("X-Lancet-Error-Kind = %q, want %q", got, errKind)
	}
}

type trackingReadCloser struct {
	io.Reader
	closed bool
}

func (t *trackingReadCloser) Close() error {
	t.closed = true
	if c, ok := t.Reader.(io.Closer); ok {
		return c.Close()
	}
	return nil
}

func TestRAGQueryRejectsOversizedBody(t *testing.T) {
	store := &fakeStore{}
	engineCalls := 0
	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			engineCalls++
			return newSingleResponseStream(&pb.QueryRAGResponse{Answer: "should not be called"}, nil), nil
		},
	}

	prefix := `{"query":"`
	suffix := `"}`
	paddingLen := int(maxRAGQueryBodyBytes) + 1 - len(prefix) - len(suffix)
	bodyStr := prefix + strings.Repeat("a", paddingLen) + suffix

	tracking := &trackingReadCloser{Reader: strings.NewReader(bodyStr)}
	req := httptest.NewRequest(http.MethodPost, "/rag/query", tracking).WithContext(t.Context())
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)

	if recorder.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusRequestEntityTooLarge)
	}
	if !tracking.closed {
		t.Fatal("expected request body to be closed")
	}
	if engineCalls != 0 {
		t.Fatalf("engine calls = %d, want 0", engineCalls)
	}
}

func TestRAGQueryRejectsHugeFilterBody(t *testing.T) {
	store := &fakeStore{}
	engineCalls := 0
	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			engineCalls++
			return newSingleResponseStream(&pb.QueryRAGResponse{Answer: "should not be called"}, nil), nil
		},
	}

	var docIDs []string
	for i := range 2000 {
		docIDs = append(docIDs, fmt.Sprintf("doc-id-filter-%04d-padding-string-for-large-size", i))
	}
	filterObj := map[string]any{
		"query":  "test",
		"filter": map[string]any{"document_ids": docIDs},
	}
	bodyBytes, err := json.Marshal(filterObj)
	if err != nil {
		t.Fatalf("marshal huge filter body: %v", err)
	}
	if int64(len(bodyBytes)) <= maxRAGQueryBodyBytes {
		t.Fatalf("huge filter body size %d <= maxRAGQueryBodyBytes %d", len(bodyBytes), maxRAGQueryBodyBytes)
	}

	tracking := &trackingReadCloser{Reader: bytes.NewReader(bodyBytes)}
	req := httptest.NewRequest(http.MethodPost, "/rag/query", tracking).WithContext(t.Context())
	req.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()

	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, req)

	if recorder.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusRequestEntityTooLarge)
	}
	if !tracking.closed {
		t.Fatal("expected request body to be closed")
	}
	if engineCalls != 0 {
		t.Fatalf("engine calls = %d, want 0", engineCalls)
	}
}

func TestHTTPServerReadTimeouts(t *testing.T) {
	server := newHTTPServer("127.0.0.1:8080", nil)
	if server.ReadTimeout != 60*time.Second {
		t.Errorf("ReadTimeout = %v, want 60s", server.ReadTimeout)
	}
	if server.ReadHeaderTimeout != 10*time.Second {
		t.Errorf("ReadHeaderTimeout = %v, want 10s", server.ReadHeaderTimeout)
	}
}

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

func startD04RustFixture(t *testing.T, docID, listenAddr, lancedbPath, mode, stopFile string) *exec.Cmd {
	t.Helper()
	cmd := exec.Command("cargo", "test", "--manifest-path", "../engine/Cargo.toml", "--locked", "tests::d04_cross_runtime_grpc_fixture", "--", "--exact", "--nocapture")
	cmd.Env = append(os.Environ(),
		"LANCET_RUN_D04_FIXTURE=1",
		"LANCET_D04_DOC_ID="+docID,
		"LANCET_D04_LISTEN_ADDR="+listenAddr,
		"LANCET_D04_LANCEDB_PATH="+lancedbPath,
		"LANCET_D04_MODE="+mode,
		"LANCET_D04_STOP_FILE="+stopFile,
	)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		t.Fatalf("start Rust D04 fixture: %v", err)
	}
	return cmd
}

func newD04IsolatedPostgres(t *testing.T, databaseURL string) (*postgresStore, *pgxpool.Pool, string) {
	t.Helper()
	ctx := context.Background()
	adminPool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("create admin pool: %v", err)
	}
	schemaName := "d04_schema_" + strings.ReplaceAll(uuid.NewString(), "-", "_")
	_, err = adminPool.Exec(ctx, fmt.Sprintf(`
		CREATE SCHEMA %q;
		CREATE TABLE %q.documents (LIKE public.documents INCLUDING ALL);
		CREATE TABLE %q.document_reconciliation_intents (LIKE public.document_reconciliation_intents INCLUDING ALL);
		ALTER TABLE %q.document_reconciliation_intents ADD CONSTRAINT document_reconciliation_intents_document_id_fkey FOREIGN KEY (document_id) REFERENCES %q.documents (id) ON UPDATE NO ACTION ON DELETE CASCADE;
	`, schemaName, schemaName, schemaName, schemaName, schemaName))
	if err != nil {
		adminPool.Close()
		t.Fatalf("create isolated D04 schema: %v", err)
	}

	connConfig, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		_, _ = adminPool.Exec(ctx, fmt.Sprintf("DROP SCHEMA %q CASCADE", schemaName))
		adminPool.Close()
		t.Fatalf("parse database URL: %v", err)
	}
	if connConfig.ConnConfig.RuntimeParams == nil {
		connConfig.ConnConfig.RuntimeParams = make(map[string]string)
	}
	connConfig.ConnConfig.RuntimeParams["search_path"] = schemaName

	isolatedPool, err := pgxpool.NewWithConfig(ctx, connConfig)
	if err != nil {
		_, _ = adminPool.Exec(ctx, fmt.Sprintf("DROP SCHEMA %q CASCADE", schemaName))
		adminPool.Close()
		t.Fatalf("create isolated pool: %v", err)
	}

	t.Cleanup(func() {
		cleanupCtx := context.Background()
		isolatedPool.Close()
		_, _ = adminPool.Exec(cleanupCtx, fmt.Sprintf("DROP SCHEMA %q CASCADE", schemaName))
		adminPool.Close()
	})

	return &postgresStore{pool: isolatedPool}, isolatedPool, schemaName
}

func getFreePort(t *testing.T) int {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("get free port: %v", err)
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port
}

type lancedbInspection struct {
	DocumentID             string `json:"document_id"`
	Provider               string `json:"provider"`
	EmbeddingModel         string `json:"embedding_model"`
	DocumentRows           int    `json:"document_rows"`
	StagedDocumentRows     int    `json:"staged_document_rows"`
	NodeRows               int    `json:"node_rows"`
	EdgeRows               int    `json:"edge_rows"`
	EmbeddingWidth         int    `json:"embedding_width"`
	GenerationCount        int    `json:"generation_count"`
	DuplicateGeneration    bool   `json:"duplicate_generation"`
	StaleGeneration        bool   `json:"stale_generation"`
	ChunkIndexesContiguous bool   `json:"chunk_indexes_contiguous"`
}

func TestEmbeddingFailureRestartConvergesAcrossRuntime(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for database integration tests")
	}

	ctx := t.Context()
	store, pool, _ := newD04IsolatedPostgres(t, databaseURL)
	_ = pool

	docID := uuid.NewString()
	q := db.New(store.pool)
	_, err := q.InsertDocument(ctx, db.InsertDocumentParams{
		ID:            docID,
		Filename:      "cross_runtime_d04.md",
		FileSize:      128,
		ChunkStrategy: "structure-aware",
		ChunkSize:     500,
		ChunkOverlap:  50,
	})
	if err != nil {
		t.Fatalf("insert initial document to isolated pg: %v", err)
	}

	tempDir := t.TempDir()
	lancedbPath := tempDir + "/lancedb"
	stopFile := tempDir + "/stop_signal"

	port := getFreePort(t)
	listenAddr := fmt.Sprintf("127.0.0.1:%d", port)

	cmd1 := startD04RustFixture(t, docID, listenAddr, lancedbPath, "fail-delete", stopFile)
	defer func() {
		_ = os.WriteFile(stopFile, []byte("stop"), 0644)
		_ = cmd1.Wait()
	}()

	conn1, err := grpc.NewClient(listenAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatalf("dial engine1: %v", err)
	}
	defer conn1.Close()
	engine1 := grpcEngine{client: pb.NewLancetServiceClient(conn1)}

	pingSuccess := false
	for range 300 {
		if _, pingErr := engine1.Ping(ctx); pingErr == nil {
			pingSuccess = true
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if !pingSuccess {
		t.Fatal("engine1 failed to start serving ping")
	}

	application := app{store: store, engine: engine1, logger: zap.NewNop()}
	router := application.routes()

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/documents/"+docID, nil)
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("GET /documents/%s code = %d, want 200", docID, rec.Code)
	}

	docAfterFail, err := store.Get(ctx, docID)
	if err != nil {
		t.Fatalf("get doc from isolated pg: %v", err)
	}
	if docAfterFail.Status != "queued" || docAfterFail.ChunkCount != 0 {
		t.Fatalf("after fail-delete, isolated pg row = %+v, want queued/0", docAfterFail)
	}

	if err := os.WriteFile(stopFile, []byte("stop"), 0644); err != nil {
		t.Fatalf("write stop signal: %v", err)
	}
	_ = cmd1.Wait()
	conn1.Close()
	_ = os.Remove(stopFile)

	port2 := getFreePort(t)
	listenAddr2 := fmt.Sprintf("127.0.0.1:%d", port2)
	cmd2 := startD04RustFixture(t, docID, listenAddr2, lancedbPath, "restart-success", stopFile)
	defer func() {
		_ = os.WriteFile(stopFile, []byte("stop"), 0644)
		_ = cmd2.Wait()
	}()

	conn2, err := grpc.NewClient(listenAddr2, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatalf("dial engine2: %v", err)
	}
	defer conn2.Close()
	engine2 := grpcEngine{client: pb.NewLancetServiceClient(conn2)}

	pingSuccess2 := false
	for range 300 {
		if _, pingErr := engine2.Ping(ctx); pingErr == nil {
			pingSuccess2 = true
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if !pingSuccess2 {
		t.Fatal("engine2 failed to start serving ping")
	}

	app2 := app{store: store, engine: engine2, logger: zap.NewNop()}
	router2 := app2.routes()

	completed := false
	for range 50 {
		rec2 := httptest.NewRecorder()
		req2 := httptest.NewRequest(http.MethodGet, "/documents/"+docID, nil)
		router2.ServeHTTP(rec2, req2)
		if rec2.Code == http.StatusOK {
			docCheck, err := store.Get(ctx, docID)
			if err == nil && docCheck.Status == "completed" {
				if docCheck.ChunkCount <= 0 {
					t.Fatalf("completed doc has non-positive chunk count: %d", docCheck.ChunkCount)
				}
				completed = true
				break
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	if !completed {
		t.Fatal("isolated pg row failed to transition to completed after restart")
	}

	_ = os.WriteFile(stopFile, []byte("stop"), 0644)
	_ = cmd2.Wait()
	conn2.Close()

	out, err := exec.Command("cargo", "run", "--manifest-path", "../engine/Cargo.toml", "--locked", "--bin", "inspect_lancedb", "--", "--document-id", docID, "--lancedb-path", lancedbPath).Output()
	if err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			t.Fatalf("inspect_lancedb failed: %v, stderr: %s", err, string(exitErr.Stderr))
		}
		t.Fatalf("inspect_lancedb failed: %v", err)
	}

	var inspection lancedbInspection
	if err := json.Unmarshal(out, &inspection); err != nil {
		t.Fatalf("unmarshal inspect_lancedb json: %v, raw: %s", err, string(out))
	}

	docCheck, _ := store.Get(ctx, docID)
	if inspection.DocumentRows != 1 {
		t.Fatalf("inspection document_rows = %d, want 1", inspection.DocumentRows)
	}
	if inspection.StagedDocumentRows != 0 {
		t.Fatalf("inspection staged_document_rows = %d, want 0", inspection.StagedDocumentRows)
	}
	if inspection.NodeRows != int(docCheck.ChunkCount) {
		t.Fatalf("inspection node_rows = %d, want matching pg chunk count %d", inspection.NodeRows, docCheck.ChunkCount)
	}
	if inspection.EmbeddingWidth != 2048 {
		t.Fatalf("inspection embedding_width = %d, want 2048", inspection.EmbeddingWidth)
	}
	if inspection.GenerationCount != 1 {
		t.Fatalf("inspection generation_count = %d, want 1", inspection.GenerationCount)
	}
	if inspection.DuplicateGeneration || inspection.StaleGeneration {
		t.Fatalf("inspection duplicate/stale generation flagged: %+v", inspection)
	}
	if !inspection.ChunkIndexesContiguous {
		t.Fatal("inspection chunk_indexes_contiguous = false, want true")
	}
}

type ragMockState struct {
	mu                 sync.Mutex
	embeddingCalls     int
	metadataCalls      int
	chatCalls          int
	chatModel          string
	chatEvidence       string
	chatUsageReturned  bool
	strictChatObserved bool
}

func TestRAGQueryCrossRuntime(t *testing.T) {
	repoRoot, err := filepath.Abs("..")
	if err != nil {
		t.Fatalf("resolve repository root: %v", err)
	}

	state := &ragMockState{}
	mock := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.Header.Get("Authorization") != "Bearer test-key" {
			http.Error(w, "unexpected authorization", http.StatusUnauthorized)
			return
		}

		switch r.URL.Path {
		case "/api/v1/embeddings":
			if r.Method != http.MethodPost {
				http.Error(w, "embedding endpoint requires POST", http.StatusMethodNotAllowed)
				return
			}
			var request struct {
				Model string   `json:"model"`
				Input []string `json:"input"`
			}
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil || request.Model != "nvidia/llama-nemotron-embed-vl-1b-v2:free" || len(request.Input) != 1 {
				http.Error(w, "invalid embedding request", http.StatusBadRequest)
				return
			}
			state.mu.Lock()
			state.embeddingCalls++
			state.mu.Unlock()
			vector := make([]float32, 2048)
			vector[0] = 1
			_ = json.NewEncoder(w).Encode(map[string]any{"data": []any{map[string]any{"embedding": vector}}})

		case "/api/v1/models":
			if r.Method != http.MethodGet {
				http.Error(w, "metadata endpoint requires GET", http.StatusMethodNotAllowed)
				return
			}
			state.mu.Lock()
			state.metadataCalls++
			state.mu.Unlock()
			_ = json.NewEncoder(w).Encode(map[string]any{"data": []any{map[string]any{
				"id":                   "openai/gpt-4o-mini",
				"supported_parameters": []string{"response_format", "structured_outputs"},
			}}})

		case "/api/v1/chat/completions":
			if r.Method != http.MethodPost {
				http.Error(w, "chat endpoint requires POST", http.StatusMethodNotAllowed)
				return
			}
			var request struct {
				Model    string `json:"model"`
				Messages []struct {
					Role    string `json:"role"`
					Content string `json:"content"`
				} `json:"messages"`
				Temperature         float64 `json:"temperature"`
				TopP                float64 `json:"top_p"`
				MaxCompletionTokens int     `json:"max_completion_tokens"`
				ResponseFormat      struct {
					Type       string `json:"type"`
					JSONSchema struct {
						Name   string         `json:"name"`
						Strict bool           `json:"strict"`
						Schema map[string]any `json:"schema"`
					} `json:"json_schema"`
				} `json:"response_format"`
			}
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
				t.Logf("chat completion JSON decode error: %v", err)
				http.Error(w, "invalid chat request JSON", http.StatusBadRequest)
				return
			}
			schema := request.ResponseFormat.JSONSchema.Schema
			addProps, hasAddProps := schema["additionalProperties"].(bool)
			reqFields, _ := schema["required"].([]any)
			hasRequired := len(reqFields) >= 5

			if request.Model != "openai/gpt-4o-mini" || len(request.Messages) != 2 || request.Messages[0].Role != "system" || request.Messages[1].Role != "user" || request.Temperature != 0 || request.TopP != 1 || request.MaxCompletionTokens != 2048 || request.ResponseFormat.Type != "json_schema" || !request.ResponseFormat.JSONSchema.Strict || !hasAddProps || addProps || !hasRequired {
				t.Logf("CONTRACT FAIL: model=%q msgs=%d temp=%v top_p=%v max_tokens=%d type=%q strict=%v hasAddProps=%v addProps=%v hasRequired=%v reqFields=%#v",
					request.Model, len(request.Messages), request.Temperature, request.TopP, request.MaxCompletionTokens, request.ResponseFormat.Type, request.ResponseFormat.JSONSchema.Strict, hasAddProps, addProps, hasRequired, reqFields)
				http.Error(w, "strict chat request contract failed", http.StatusBadRequest)
				return
			}
			if !strings.Contains(request.Messages[1].Content, "DENSE_FIXTURE_MARKER") ||
				!strings.Contains(request.Messages[1].Content, "LEXICAL_FIXTURE_IDENTIFIER_2026") ||
				!strings.Contains(request.Messages[1].Content, "GRAPH_FIXTURE_MARKER_SEED") ||
				!strings.Contains(request.Messages[1].Content, "GRAPH_FIXTURE_MARKER_NEIGHBOR") ||
				!strings.Contains(request.Messages[1].Content, "GRAPH_FIXTURE_MARKER_RELATION") {
				t.Logf("EVIDENCE FAIL: content=%q", request.Messages[1].Content)
				http.Error(w, "retrieval evidence is incomplete", http.StatusBadRequest)
				return
			}
			state.mu.Lock()
			state.chatCalls++
			state.chatModel = request.Model
			state.chatEvidence = request.Messages[1].Content
			state.chatUsageReturned = true
			state.strictChatObserved = true
			state.mu.Unlock()
			modelOutput, _ := json.Marshal(map[string]any{
				"answer":             "DENSE_AND_LEXICAL_FIXTURE_MARKER [1]",
				"cited_evidence_ids": []string{"[1]"},
				"answer_basis":       "retrieval",
				"notices":            []string{},
				"warnings":           []string{},
			})
			_ = json.NewEncoder(w).Encode(map[string]any{
				"id":    "local-chat-completion",
				"model": "openai/gpt-4o-mini",
				"choices": []any{map[string]any{
					"message":       map[string]any{"content": string(modelOutput)},
					"finish_reason": "stop",
				}},
				"usage": map[string]any{
					"prompt_tokens":     17,
					"completion_tokens": 9,
					"total_tokens":      26,
				},
			})

		default:
			http.NotFound(w, r)
		}
	}))
	defer mock.Close()

	tempRoot := t.TempDir()
	lancedbPath := filepath.Join(tempRoot, "lancedb")
	releasedPath := filepath.Join(tempRoot, "lancedb-released")
	defer releaseRAGPath(t, lancedbPath, releasedPath)
	port := getFreePort(t)
	engineAddr := fmt.Sprintf("127.0.0.1:%d", port)

	build := exec.Command("cargo", "build", "--manifest-path", filepath.Join(repoRoot, "engine", "Cargo.toml"), "--locked", "--target-dir", filepath.Join(repoRoot, "engine", "target"), "--bin", "engine", "--bin", "seed_rag_fixture")
	build.Dir = repoRoot
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build engine and fixture seeder: %v\n%s", err, output)
	}

	enginePath := filepath.Join(repoRoot, "engine", "target", "debug", "engine.exe")
	seederPath := filepath.Join(repoRoot, "engine", "target", "debug", "seed_rag_fixture.exe")
	if runtime.GOOS != "windows" {
		enginePath = filepath.Join(repoRoot, "engine", "target", "debug", "engine")
		seederPath = filepath.Join(repoRoot, "engine", "target", "debug", "seed_rag_fixture")
	}
	if _, err := os.Stat(enginePath); err != nil {
		t.Fatalf("resolved engine executable is unavailable: %v", err)
	}
	if _, err := os.Stat(seederPath); err != nil {
		t.Fatalf("resolved fixture seeder executable is unavailable: %v", err)
	}

	seederEnv := ragChildEnv()
	assertCleanRAGChildEnv(t, seederEnv)
	seeder := exec.Command(seederPath, "--lancedb-path", lancedbPath)
	seeder.Dir = repoRoot
	seeder.Env = seederEnv
	if err := seeder.Start(); err != nil {
		t.Fatalf("start fixture seeder: %v", err)
	}
	seedDone := make(chan error, 1)
	go func() { seedDone <- seeder.Wait() }()
	select {
	case err := <-seedDone:
		if err != nil {
			t.Fatalf("fixture seeder failed: %v", err)
		}
	case <-time.After(30 * time.Second):
		terminateRAGProcess(seeder, seedDone)
		t.Fatal("fixture seeder did not exit within 30 seconds")
	}

	engineEnv := ragChildEnv(
		"LANCET_ENGINE__GRPC_ADDR="+engineAddr,
		"LANCET_ENGINE__LANCEDB_PATH="+lancedbPath,
		"LANCET_OPENROUTER__EMBEDDING_ENDPOINT="+mock.URL+"/api/v1/embeddings",
		"LANCET_OPENROUTER__MODEL_METADATA_ENDPOINT="+mock.URL+"/api/v1/models",
		"LANCET_OPENROUTER__CHAT_ENDPOINT="+mock.URL+"/api/v1/chat/completions",
		"LANCET_OPENROUTER__GENERATION_MODEL=openai/gpt-4o-mini",
		"OPENROUTER_API_KEY=test-key",
	)
	assertCleanRAGChildEnv(t, engineEnv)
	engineCmd := exec.Command(enginePath)
	engineCmd.Dir = repoRoot
	engineCmd.Env = engineEnv
	var conn *grpc.ClientConn
	var cancelRAGContext context.CancelFunc = func() {}
	stdout, err := engineCmd.StdoutPipe()
	if err != nil {
		t.Fatalf("capture engine stdout: %v", err)
	}
	stderr, err := engineCmd.StderrPipe()
	if err != nil {
		t.Fatalf("capture engine stderr: %v", err)
	}
	if err := engineCmd.Start(); err != nil {
		t.Fatalf("start Rust engine: %v", err)
	}
	engineDone := make(chan struct{})
	var engineErr error
	go func() {
		engineErr = engineCmd.Wait()
		close(engineDone)
	}()
	lines := make(chan string, 64)
	go scanRAGOutput(stdout, lines)
	go scanRAGOutput(stderr, lines)
	var engineLines []string
	defer func() {
		cancelRAGContext()
		if conn != nil {
			_ = conn.Close()
		}
		terminateRAGProcess(engineCmd, nil)
		select {
		case <-engineDone:
		case <-time.After(10 * time.Second):
			t.Errorf("engine did not exit within 10 seconds after process-tree teardown")
		}
	}()

	served := false
	serveDeadline := time.After(30 * time.Second)
	for !served {
		select {
		case line := <-lines:
			engineLines = append(engineLines, line)
			if strings.Contains(line, "Rust RAG Engine serving") {
				served = true
			}
		case <-engineDone:
			t.Fatalf("Rust engine exited before readiness: %v", engineErr)
		case <-serveDeadline:
			t.Fatal("Rust engine did not emit serving milestone within 30 seconds")
		}
	}

	engineCtx, cancel := context.WithTimeout(t.Context(), 30*time.Second)
	cancelRAGContext = cancel
	conn, err = grpc.NewClient(engineAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatalf("dial exact Rust gRPC endpoint: %v", err)
	}
	client := pb.NewLancetServiceClient(conn)
	pinged := false
	var lastPingErr error
	pingDeadline := time.Now().Add(30 * time.Second)
	for delay := 10 * time.Millisecond; time.Now().Before(pingDeadline); delay = min(delay*2, 250*time.Millisecond) {
		pingCtx, pingCancel := context.WithTimeout(engineCtx, 2*time.Second)
		_, pingErr := client.Ping(pingCtx, &pb.PingRequest{Value: "ping"})
		lastPingErr = pingErr
		pingCancel()
		if pingErr == nil {
			pinged = true
			break
		}
		select {
		case <-engineDone:
			t.Fatalf("Rust engine exited during Ping readiness probe: %v", engineErr)
		default:
		}
		time.Sleep(delay)
	}
	if !pinged {
		t.Fatalf("generated gRPC Ping did not succeed within 30 seconds: %v; engine output: %s", lastPingErr, strings.Join(engineLines, " | "))
	}

	server := httptest.NewServer(app{store: &fakeStore{}, engine: grpcEngine{client: client}, logger: zap.NewNop()}.routes())
	defer server.Close()

	httpClient := &http.Client{}
	requestBody := `{"query":"What does LEXICAL_FIXTURE_IDENTIFIER_2026 prove?","session_id":"00000000-0000-4000-8000-000000000006"}`
	httpReq, err := http.NewRequestWithContext(t.Context(), http.MethodPost, server.URL+"/rag/query", strings.NewReader(requestBody))
	if err != nil {
		t.Fatalf("create request: %v", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "text/event-stream")

	httpResp, err := httpClient.Do(httpReq)
	if err != nil {
		t.Fatalf("execute request: %v", err)
	}
	defer httpResp.Body.Close()

	if httpResp.StatusCode != http.StatusOK {
		t.Fatalf("real /rag/query status = %d; engine output: %s", httpResp.StatusCode, strings.Join(engineLines, " | "))
	}

	rawBodyBytes, err := io.ReadAll(httpResp.Body)
	if err != nil {
		t.Fatalf("read SSE response body: %v", err)
	}
	bodyStr := string(rawBodyBytes)

	sseEvs := parseSSEEvents(bodyStr)
	var hasStreamError bool
	seenNodes := make(map[string]struct{})
	var sawAnswerChunk, sawFinalAnswer, sawWorkflowCompleted bool
	for _, ev := range sseEvs {
		if ev.Event == "stream_error" {
			hasStreamError = true
		}
		if ev.Event == "node_started" || ev.Event == "node_completed" {
			var nodePayload struct {
				NodeName string `json:"node_name"`
			}
			_ = json.Unmarshal([]byte(ev.Data), &nodePayload)
			seenNodes[ev.Event+":"+nodePayload.NodeName] = struct{}{}
		}
		if ev.Event == "answer_chunk" {
			sawAnswerChunk = true
		}
		if ev.Event == "final_answer" {
			sawFinalAnswer = true
		}
		if ev.Event == "workflow_completed" {
			sawWorkflowCompleted = true
		}
	}
	if hasStreamError {
		t.Fatalf("unexpected stream_error in SSE events: %s", bodyStr)
	}
	for _, node := range []string{"ReformulateQuery", "ExtractGraphContext", "RetrieveHybrid", "AssemblePrompt", "GenerateAnswer"} {
		if _, ok := seenNodes["node_started:"+node]; !ok {
			t.Fatalf("missing node_started for %s in %s", node, bodyStr)
		}
		if _, ok := seenNodes["node_completed:"+node]; !ok {
			t.Fatalf("missing node_completed for %s in %s", node, bodyStr)
		}
	}
	if !sawAnswerChunk {
		t.Fatalf("missing answer_chunk event in %s", bodyStr)
	}
	if !sawFinalAnswer {
		t.Fatalf("missing final_answer event in %s", bodyStr)
	}
	if !sawWorkflowCompleted {
		t.Fatalf("missing workflow_completed event in %s", bodyStr)
	}

	dto, err := parseTerminalResponseDTO(bodyStr)
	if err != nil {
		t.Fatalf("decode real /rag/query response: %v; body: %s", err, bodyStr)
	}
	if dto.SessionID != "00000000-0000-4000-8000-000000000006" {
		t.Fatalf("effective session_id = %q", dto.SessionID)
	}
	if dto.Answer != "DENSE_AND_LEXICAL_FIXTURE_MARKER [1]" || dto.AnswerBasis != int32(pb.AnswerBasis_ANSWER_BASIS_RETRIEVAL) {
		t.Fatalf("grounded answer = %q, basis = %v", dto.Answer, dto.AnswerBasis)
	}
	if len(dto.Citations) != 1 || dto.Citations[0] != "[1]" || len(dto.StructuredCitations) != 1 || dto.StructuredCitations[0].DocumentID != "00000000-0000-4000-8000-000000000005" {
		t.Fatalf("citation provenance = %#v / %#v", dto.Citations, dto.StructuredCitations)
	}
	if dto.Snapshot == nil || dto.Snapshot.EmbeddingModel != "nvidia/llama-nemotron-embed-vl-1b-v2:free" || dto.Snapshot.CandidateLimit != 32 {
		t.Fatalf("retrieval snapshot = %#v", dto.Snapshot)
	}
	if dto.Notices == nil {
		t.Fatalf("notices must be non-nil slice")
	}
	state.mu.Lock()
	chatCalls, metadataCalls, embeddingCalls := state.chatCalls, state.metadataCalls, state.embeddingCalls
	chatEvidence, chatModel, usageReturned, strictChat := state.chatEvidence, state.chatModel, state.chatUsageReturned, state.strictChatObserved
	state.mu.Unlock()
	if embeddingCalls != 1 || metadataCalls != 1 || chatCalls != 1 || chatModel != "openai/gpt-4o-mini" || !usageReturned || !strictChat {
		t.Fatalf("mock call contract = embeddings:%d metadata:%d chat:%d model:%q usage:%v strict:%v", embeddingCalls, metadataCalls, chatCalls, chatModel, usageReturned, strictChat)
	}
	if !strings.Contains(chatEvidence, "DENSE_FIXTURE_MARKER") ||
		!strings.Contains(chatEvidence, "LEXICAL_FIXTURE_IDENTIFIER_2026") ||
		!strings.Contains(chatEvidence, "GRAPH_FIXTURE_MARKER_SEED") ||
		!strings.Contains(chatEvidence, "GRAPH_FIXTURE_MARKER_NEIGHBOR") ||
		!strings.Contains(chatEvidence, "GRAPH_FIXTURE_MARKER_RELATION") {
		t.Fatalf("Rust-owned evidence omitted graph, dense or lexical fixture content")
	}
}

func TestRAGQuerySSEFirstFrame(t *testing.T) {
	sessionID := "00000000-0000-4000-8000-000000000055"
	correlationID := "00000000-0000-4000-8000-000000000099"
	docID := "00000000-0000-4000-8000-000000000001"

	resp := &pb.QueryRAGResponse{
		Answer:      "First frame test answer [1]",
		Citations:   []string{"[1]"},
		SessionId:   sessionID,
		AnswerBasis: pb.AnswerBasis_ANSWER_BASIS_RETRIEVAL,
		StructuredCitations: []*pb.StructuredCitation{
			{
				ChunkId:     "c1",
				DocumentId:  docID,
				Title:       "Doc Title",
				SectionPath: "/section",
				Excerpt:     "excerpt",
				Rank:        1,
				ContentType: "text/plain",
			},
		},
		Notices: []*pb.Notice{},
		Snapshot: &pb.RetrievalSnapshot{
			IndexGeneration: "gen-1",
			EmbeddingModel:  "nvidia/llama-nemotron-embed-vl-1b-v2:free",
			CandidateLimit:  32,
			FinalLimit:      8,
		},
	}

	events := []*pb.WorkflowEvent{
		{
			SessionId:       sessionID,
			TraceId:         correlationID,
			SequenceOrdinal: 1,
			Event: &pb.WorkflowEvent_NodeStarted{
				NodeStarted: &pb.NodeStartedEvent{
					NodeName:      "ReformulateQuery",
					InputsSummary: "inputs",
				},
			},
		},
		{
			SessionId:       sessionID,
			TraceId:         correlationID,
			SequenceOrdinal: 2,
			Event: &pb.WorkflowEvent_FinalAnswer{
				FinalAnswer: &pb.FinalAnswerEvent{
					Response: resp,
				},
			},
		},
		{
			SessionId:       sessionID,
			TraceId:         correlationID,
			SequenceOrdinal: 3,
			Event: &pb.WorkflowEvent_WorkflowCompleted{
				WorkflowCompleted: &pb.WorkflowCompletedEvent{
					Success:       true,
					FinalResponse: resp,
				},
			},
		},
	}

	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			return &fakeQueryRAGStream{events: events}, nil
		},
	}

	server := httptest.NewServer(app{store: &fakeStore{}, engine: engine, logger: zap.NewNop()}.routes())
	defer server.Close()

	reqBody := `{"query":"first frame test","session_id":"` + sessionID + `"}`
	httpReq, err := http.NewRequestWithContext(t.Context(), http.MethodPost, server.URL+"/rag/query", strings.NewReader(reqBody))
	if err != nil {
		t.Fatalf("create request error: %v", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "text/event-stream")

	res, err := http.DefaultClient.Do(httpReq)
	if err != nil {
		t.Fatalf("execute request error: %v", err)
	}
	defer res.Body.Close()

	if res.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", res.StatusCode)
	}

	if contentType := res.Header.Get("Content-Type"); !strings.HasPrefix(contentType, "text/event-stream") {
		t.Fatalf("Content-Type = %q, want text/event-stream", contentType)
	}

	if got := res.Header.Get("X-Lancet-Session-ID"); got != sessionID {
		t.Fatalf("X-Lancet-Session-ID = %q, want %q", got, sessionID)
	}
	if got := res.Header.Get("X-Lancet-Correlation-ID"); got != correlationID {
		t.Fatalf("X-Lancet-Correlation-ID = %q, want %q", got, correlationID)
	}

	bodyBytes, err := io.ReadAll(res.Body)
	if err != nil {
		t.Fatalf("read body error: %v", err)
	}

	bodyStr := string(bodyBytes)
	sseEvs := parseSSEEvents(bodyStr)
	if len(sseEvs) < 2 {
		t.Fatalf("expected at least 2 SSE events, got %d: %s", len(sseEvs), bodyStr)
	}

	if sseEvs[0].Event != "node_started" {
		t.Fatalf("first event = %q, want node_started", sseEvs[0].Event)
	}

	dto, err := parseTerminalResponseDTO(bodyStr)
	if err != nil {
		t.Fatalf("parse terminal DTO error: %v", err)
	}

	if dto.Answer != "First frame test answer [1]" {
		t.Fatalf("answer = %q", dto.Answer)
	}
	if dto.SessionID != sessionID {
		t.Fatalf("session_id = %q", dto.SessionID)
	}
	if dto.AnswerBasis != int32(pb.AnswerBasis_ANSWER_BASIS_RETRIEVAL) {
		t.Fatalf("answer_basis = %d", dto.AnswerBasis)
	}
	if len(dto.Citations) != 1 || dto.Citations[0] != "[1]" {
		t.Fatalf("citations = %v", dto.Citations)
	}
	if len(dto.StructuredCitations) != 1 || dto.StructuredCitations[0].DocumentID != docID {
		t.Fatalf("structured_citations = %#v", dto.StructuredCitations)
	}
	if dto.Snapshot == nil || dto.Snapshot.EmbeddingModel != "nvidia/llama-nemotron-embed-vl-1b-v2:free" {
		t.Fatalf("snapshot = %#v", dto.Snapshot)
	}
	if dto.Notices == nil {
		t.Fatalf("notices must be non-nil slice")
	}
}

func TestRAGQueryFailureTerminalNoticesSSE(t *testing.T) {
	sessionID := "00000000-0000-4000-8000-000000000055"
	correlationID := "00000000-0000-4000-8000-000000000099"

	events := []*pb.WorkflowEvent{
		{
			SessionId:       sessionID,
			TraceId:         correlationID,
			SequenceOrdinal: 1,
			Event: &pb.WorkflowEvent_NodeStarted{
				NodeStarted: &pb.NodeStartedEvent{
					NodeName:      "ExtractGraphContext",
					InputsSummary: "inputs",
				},
			},
		},
		{
			SessionId:       sessionID,
			TraceId:         correlationID,
			SequenceOrdinal: 2,
			Event: &pb.WorkflowEvent_NodeFailed{
				NodeFailed: &pb.NodeFailedEvent{
					NodeName:  "ExtractGraphContext",
					Category:  pb.NodeErrorKind_NODE_ERROR_KIND_TIMEOUT,
					Message:   "graph timed out",
					Retryable: false,
				},
			},
		},
		{
			SessionId:       sessionID,
			TraceId:         correlationID,
			SequenceOrdinal: 3,
			Event: &pb.WorkflowEvent_WorkflowCompleted{
				WorkflowCompleted: &pb.WorkflowCompletedEvent{
					Success:       false,
					DurationMs:    120,
					ErrorKind:     pb.NodeErrorKind_NODE_ERROR_KIND_TIMEOUT,
					ErrorMessage:  "graph timed out",
					FinalResponse: nil,
					Notices: []*pb.Notice{
						{
							Code:     "GRAPH_TIMEOUT",
							Message:  "Graph query timed out",
							Severity: pb.NoticeSeverity_NOTICE_SEVERITY_WARNING,
						},
						{
							Code:     "GRAPH_DEGRADED",
							Message:  "Graph context degraded",
							Severity: pb.NoticeSeverity_NOTICE_SEVERITY_INFO,
						},
					},
				},
			},
		},
	}

	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			return &fakeQueryRAGStream{events: events}, nil
		},
	}

	server := httptest.NewServer(app{store: &fakeStore{}, engine: engine, logger: zap.NewNop()}.routes())
	defer server.Close()

	reqBody := `{"query":"failure terminal test","session_id":"` + sessionID + `"}`
	httpReq, err := http.NewRequestWithContext(t.Context(), http.MethodPost, server.URL+"/rag/query", strings.NewReader(reqBody))
	if err != nil {
		t.Fatalf("create request error: %v", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "text/event-stream")

	res, err := http.DefaultClient.Do(httpReq)
	if err != nil {
		t.Fatalf("execute request error: %v", err)
	}
	defer res.Body.Close()

	if res.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", res.StatusCode)
	}

	if contentType := res.Header.Get("Content-Type"); !strings.HasPrefix(contentType, "text/event-stream") {
		t.Fatalf("Content-Type = %q, want text/event-stream", contentType)
	}

	if got := res.Header.Get("X-Lancet-Session-ID"); got != sessionID {
		t.Fatalf("X-Lancet-Session-ID = %q, want %q", got, sessionID)
	}
	if got := res.Header.Get("X-Lancet-Correlation-ID"); got != correlationID {
		t.Fatalf("X-Lancet-Correlation-ID = %q, want %q", got, correlationID)
	}

	bodyBytes, err := io.ReadAll(res.Body)
	if err != nil {
		t.Fatalf("read body error: %v", err)
	}

	bodyStr := string(bodyBytes)
	sseEvs := parseSSEEvents(bodyStr)
	if len(sseEvs) != 3 {
		t.Fatalf("expected 3 SSE events, got %d: %s", len(sseEvs), bodyStr)
	}

	for _, ev := range sseEvs {
		if ev.Event == "answer_chunk" {
			t.Fatalf("unexpected answer_chunk event in failure stream: %s", ev.Data)
		}
		if ev.Event == "final_answer" {
			t.Fatalf("unexpected final_answer event in failure stream: %s", ev.Data)
		}
	}

	var nodeFailedIdx, workflowCompletedIdx = -1, -1
	for i, ev := range sseEvs {
		if ev.Event == "node_failed" {
			nodeFailedIdx = i
		}
		if ev.Event == "workflow_completed" {
			workflowCompletedIdx = i
		}
	}

	if nodeFailedIdx == -1 {
		t.Fatalf("missing node_failed event in SSE stream: %s", bodyStr)
	}
	if workflowCompletedIdx == -1 {
		t.Fatalf("missing workflow_completed event in SSE stream: %s", bodyStr)
	}
	if nodeFailedIdx >= workflowCompletedIdx {
		t.Fatalf("node_failed (%d) must precede workflow_completed (%d)", nodeFailedIdx, workflowCompletedIdx)
	}

	wcData := sseEvs[workflowCompletedIdx].Data
	var rawFields map[string]json.RawMessage
	if err := json.Unmarshal([]byte(wcData), &rawFields); err != nil {
		t.Fatalf("unmarshal workflow_completed data error: %v", err)
	}

	if _, exists := rawFields["final_response"]; exists {
		t.Fatalf("final_response must be omitted on failed terminal, got: %s", string(rawFields["final_response"]))
	}

	var wcPayload struct {
		Success         bool        `json:"success"`
		TotalDurationMs int64       `json:"total_duration_ms"`
		ErrorKind       int32       `json:"error_kind"`
		ErrorMessage    string      `json:"error_message"`
		Notices         []noticeDTO `json:"notices"`
	}
	if err := json.Unmarshal([]byte(wcData), &wcPayload); err != nil {
		t.Fatalf("unmarshal typed workflow_completed payload error: %v", err)
	}

	if wcPayload.Success {
		t.Fatalf("expected success=false, got %v", wcPayload.Success)
	}
	if wcPayload.ErrorKind != int32(pb.NodeErrorKind_NODE_ERROR_KIND_TIMEOUT) {
		t.Fatalf("error_kind = %d, want %d", wcPayload.ErrorKind, pb.NodeErrorKind_NODE_ERROR_KIND_TIMEOUT)
	}
	if wcPayload.ErrorMessage != "graph timed out" {
		t.Fatalf("error_message = %q, want 'graph timed out'", wcPayload.ErrorMessage)
	}

	if len(wcPayload.Notices) != 2 {
		t.Fatalf("expected 2 notices, got %d: %#v", len(wcPayload.Notices), wcPayload.Notices)
	}
	if wcPayload.Notices[0].Code != "GRAPH_TIMEOUT" || wcPayload.Notices[0].Message != "Graph query timed out" || wcPayload.Notices[0].Severity != int32(pb.NoticeSeverity_NOTICE_SEVERITY_WARNING) {
		t.Fatalf("notices[0] mismatch: %#v", wcPayload.Notices[0])
	}
	if wcPayload.Notices[1].Code != "GRAPH_DEGRADED" || wcPayload.Notices[1].Message != "Graph context degraded" || wcPayload.Notices[1].Severity != int32(pb.NoticeSeverity_NOTICE_SEVERITY_INFO) {
		t.Fatalf("notices[1] mismatch: %#v", wcPayload.Notices[1])
	}
}

func TestCheckpointDispatcherSixthEnvelopeReturnsPending(t *testing.T) {
	dispatcher := NewCheckpointDispatcher(nil)

	for i := range 5 {
		env := &CheckpointEnvelope{
			SessionID:       "sess-1",
			SequenceOrdinal: uint64(i + 1),
		}
		res := dispatcher.Submit(env)
		if res.Kind != DispatchAccepted {
			t.Fatalf("envelope %d submitted, expected Accepted, got %v", i+1, res.Kind)
		}
	}

	sixthEnv := &CheckpointEnvelope{
		SessionID:       "sess-1",
		SequenceOrdinal: 6,
		NodeID:          "sixth-node",
	}
	res := dispatcher.Submit(sixthEnv)
	if res.Kind != DispatchPending {
		t.Fatalf("6th envelope submitted, expected DispatchPending, got %v", res.Kind)
	}
	if res.Envelope != sixthEnv {
		t.Fatalf("expected 6th envelope returned in Pending result, got %v", res.Envelope)
	}

	dispatcher.Close()
}

func ragChildEnv(extra ...string) []string {
	baseline := map[string]bool{
		"COMSPEC": true, "PATH": true, "PATHEXT": true, "SYSTEMROOT": true,
		"TEMP": true, "TMP": true, "USERPROFILE": true, "WINDIR": true,
	}
	env := make([]string, 0, len(baseline)+len(extra))
	for _, entry := range os.Environ() {
		key, _, ok := strings.Cut(entry, "=")
		if ok && baseline[strings.ToUpper(key)] {
			env = append(env, entry)
		}
	}
	return append(env, extra...)
}

func assertCleanRAGChildEnv(t *testing.T, env []string) {
	t.Helper()
	allowed := map[string]bool{
		"LANCET_ENGINE__GRPC_ADDR":                   true,
		"LANCET_ENGINE__LANCEDB_PATH":                true,
		"LANCET_OPENROUTER__EMBEDDING_ENDPOINT":      true,
		"LANCET_OPENROUTER__MODEL_METADATA_ENDPOINT": true,
		"LANCET_OPENROUTER__CHAT_ENDPOINT":           true,
		"LANCET_OPENROUTER__GENERATION_MODEL":        true,
		"LANCET_OPENROUTER__EMBEDDING_MODEL":         true,
		"OPENROUTER_API_KEY":                         true,
	}
	for _, entry := range env {
		key, _, _ := strings.Cut(entry, "=")
		upper := strings.ToUpper(key)
		if (strings.HasPrefix(upper, "LANCET_") || strings.HasPrefix(upper, "OPENROUTER_")) && !allowed[key] {
			t.Fatalf("unexpected application environment in child: %s", key)
		}
		if strings.HasPrefix(upper, "CONFIG_") || strings.HasPrefix(upper, "DATABASE_") || strings.HasPrefix(upper, "TEST_DATABASE_") || strings.HasPrefix(upper, "RUST_LOG") {
			t.Fatalf("application environment leaked into child: %s", key)
		}
	}
}

func scanRAGOutput(reader io.Reader, lines chan<- string) {
	for scanner := bufio.NewScanner(reader); scanner.Scan(); {
		select {
		case lines <- scanner.Text():
		default:
		}
	}
}

func terminateRAGProcess(cmd *exec.Cmd, done chan error) {
	if cmd == nil || cmd.Process == nil {
		return
	}
	if runtime.GOOS == "windows" {
		_ = exec.Command("taskkill", "/PID", strconv.Itoa(cmd.Process.Pid), "/T", "/F").Run()
	}
	if done != nil {
		select {
		case <-done:
			return
		case <-time.After(10 * time.Second):
		}
	}
	_ = cmd.Process.Kill()
}

func releaseRAGPath(t *testing.T, source, released string) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for {
		if err := os.Rename(source, released); err == nil {
			if err := os.RemoveAll(released); err != nil {
				t.Fatalf("remove released LanceDB path: %v", err)
			}
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("isolated LanceDB path remained locked: %s", source)
		}
		time.Sleep(100 * time.Millisecond)
	}
}

func TestWriteJSONEncodeFailureReturns500(t *testing.T) {
	t.Run("nan causes 500 without commit", func(t *testing.T) {
		recorder := httptest.NewRecorder()
		unencodable := struct {
			Val float64 `json:"val"`
		}{
			Val: math.NaN(),
		}
		writeJSON(recorder, http.StatusOK, unencodable)
		if recorder.Code != http.StatusInternalServerError {
			t.Fatalf("status = %d, want 500", recorder.Code)
		}
		if !strings.Contains(recorder.Body.String(), "error") {
			t.Fatalf("expected error body, got: %s", recorder.Body.String())
		}
	})

	t.Run("encodable returns requested status and json body", func(t *testing.T) {
		recorder := httptest.NewRecorder()
		encodable := map[string]string{"status": "ok"}
		writeJSON(recorder, http.StatusOK, encodable)
		if recorder.Code != http.StatusOK {
			t.Fatalf("status = %d, want 200", recorder.Code)
		}
		if recorder.Header().Get("Content-Type") != "application/json" {
			t.Fatalf("content-type = %s, want application/json", recorder.Header().Get("Content-Type"))
		}
		var parsed map[string]string
		if err := json.Unmarshal(recorder.Body.Bytes(), &parsed); err != nil {
			t.Fatalf("failed to parse json response: %v", err)
		}
		if parsed["status"] != "ok" {
			t.Fatalf("parsed status = %s, want ok", parsed["status"])
		}
	})
}

func newWorkflowCheckpointsIsolatedPostgres(t *testing.T, databaseURL string) (*postgresStore, *pgxpool.Pool, string) {
	t.Helper()
	ctx := context.Background()
	adminPool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("create admin pool: %v", err)
	}
	schemaName := "cp_schema_" + strings.ReplaceAll(uuid.NewString(), "-", "_")
	_, err = adminPool.Exec(ctx, fmt.Sprintf(`
		CREATE SCHEMA %q;
		CREATE TABLE %q.users (LIKE public.users INCLUDING ALL);
		CREATE TABLE %q.documents (LIKE public.documents INCLUDING ALL);
		CREATE TABLE %q.document_reconciliation_intents (LIKE public.document_reconciliation_intents INCLUDING ALL);
		CREATE TABLE %q.workflow_checkpoints (LIKE public.workflow_checkpoints INCLUDING ALL);
		ALTER TABLE %q.document_reconciliation_intents ADD CONSTRAINT document_reconciliation_intents_document_id_fkey FOREIGN KEY (document_id) REFERENCES %q.documents (id) ON UPDATE NO ACTION ON DELETE CASCADE;
	`, schemaName, schemaName, schemaName, schemaName, schemaName, schemaName, schemaName))
	if err != nil {
		adminPool.Close()
		t.Fatalf("create isolated workflow_checkpoints schema: %v", err)
	}

	connConfig, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		_, _ = adminPool.Exec(ctx, fmt.Sprintf("DROP SCHEMA %q CASCADE", schemaName))
		adminPool.Close()
		t.Fatalf("parse database URL: %v", err)
	}
	if connConfig.ConnConfig.RuntimeParams == nil {
		connConfig.ConnConfig.RuntimeParams = make(map[string]string)
	}
	connConfig.ConnConfig.RuntimeParams["search_path"] = schemaName

	isolatedPool, err := pgxpool.NewWithConfig(ctx, connConfig)
	if err != nil {
		_, _ = adminPool.Exec(ctx, fmt.Sprintf("DROP SCHEMA %q CASCADE", schemaName))
		adminPool.Close()
		t.Fatalf("create isolated pool: %v", err)
	}

	t.Cleanup(func() {
		cleanupCtx := context.Background()
		isolatedPool.Close()
		_, _ = adminPool.Exec(cleanupCtx, fmt.Sprintf("DROP SCHEMA %q CASCADE", schemaName))
		adminPool.Close()
	})

	return &postgresStore{pool: isolatedPool}, isolatedPool, schemaName
}

func TestWorkflowCheckpointSchemaArtifacts(t *testing.T) {
	hclBytes, err := os.ReadFile("db/schema.hcl")
	if err != nil {
		t.Fatalf("read schema.hcl: %v", err)
	}
	hcl := string(hclBytes)

	sqlBytes, err := os.ReadFile("db/schema.sql")
	if err != nil {
		t.Fatalf("read schema.sql: %v", err)
	}
	sqlStr := string(sqlBytes)

	queryBytes, err := os.ReadFile("db/query.sql")
	if err != nil {
		t.Fatalf("read query.sql: %v", err)
	}
	queryStr := string(queryBytes)

	requiredCols := []string{"id", "trace_id", "sequence_ordinal", "node_name", "context_snapshot", "created_at"}
	for _, col := range requiredCols {
		if !strings.Contains(hcl, `column "`+col+`"`) {
			t.Fatalf("schema.hcl missing column: %s", col)
		}
		if !strings.Contains(sqlStr, `"`+col+`"`) {
			t.Fatalf("schema.sql missing column: %s", col)
		}
	}

	if !strings.Contains(hcl, `table "workflow_checkpoints"`) {
		t.Fatalf("schema.hcl missing table workflow_checkpoints")
	}
	if !strings.Contains(sqlStr, `CREATE TABLE "public"."workflow_checkpoints"`) {
		t.Fatalf("schema.sql missing CREATE TABLE workflow_checkpoints")
	}

	if !strings.Contains(hcl, "workflow_checkpoints_trace_id_sequence_ordinal_created_at") {
		t.Fatalf("schema.hcl missing index workflow_checkpoints_trace_id_sequence_ordinal_created_at")
	}
	if !strings.Contains(sqlStr, "workflow_checkpoints_trace_id_sequence_ordinal_created_at") {
		t.Fatalf("schema.sql missing index workflow_checkpoints_trace_id_sequence_ordinal_created_at")
	}

	if !strings.Contains(queryStr, "InsertWorkflowCheckpoint") {
		t.Fatalf("query.sql missing InsertWorkflowCheckpoint")
	}

	var cp db.WorkflowCheckpoint
	_ = cp.ID
	_ = cp.TraceID
	_ = cp.SequenceOrdinal
	_ = cp.NodeName
	_ = cp.ContextSnapshot
	_ = cp.CreatedAt

	var params db.InsertWorkflowCheckpointParams
	_ = params.ID
	_ = params.TraceID
	_ = params.SequenceOrdinal
	_ = params.NodeName
	_ = params.ContextSnapshot
	_ = params.CreatedAt

	if strings.Contains(strings.ToLower(hcl), "ttl") || strings.Contains(strings.ToLower(sqlStr), "ttl") {
		t.Fatalf("schema contains prohibited TTL / retention cleanup")
	}
}

func TestWorkflowCheckpointTracer(t *testing.T) {
	ev := &pb.WorkflowEvent{
		SessionId:       "sess-123",
		TraceId:         "trace-456",
		SequenceOrdinal: 1,
		TimestampMs:     1234567890,
		Event: &pb.WorkflowEvent_Checkpoint{
			Checkpoint: &pb.CheckpointEvent{
				CheckpointType:  "reformulate",
				SequenceOrdinal: 1,
				ContextSnapshot: `{"original_query":"test query","reformulated_query":"test query reformulated"}`,
			},
		},
	}

	env := NewCheckpointEnvelopeFromEvent(ev)
	if env == nil {
		t.Fatalf("expected non-nil envelope")
	}
	if env.TraceID != "trace-456" {
		t.Fatalf("trace_id = %s, want trace-456", env.TraceID)
	}
	if env.SequenceOrdinal != 1 {
		t.Fatalf("sequence_ordinal = %d, want 1", env.SequenceOrdinal)
	}
	if env.NodeID != "reformulate" {
		t.Fatalf("node_id = %s, want reformulate", env.NodeID)
	}

	inMem := NewInMemoryCheckpointSink()
	disp := NewCheckpointDispatcher(inMem)
	res := disp.Submit(env)
	if res.Kind != DispatchAccepted {
		t.Fatalf("dispatch result = %v, want DispatchAccepted", res.Kind)
	}
	disp.Close()

	cps := inMem.Checkpoints()
	if len(cps) != 1 {
		t.Fatalf("in-memory checkpoints count = %d, want 1", len(cps))
	}
	if cps[0].TraceID != "trace-456" {
		t.Fatalf("checkpoint trace_id = %s, want trace-456", cps[0].TraceID)
	}

	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL != "" {
		ctx := t.Context()
		_, pool, _ := newWorkflowCheckpointsIsolatedPostgres(t, databaseURL)
		pgSink := NewPostgresCheckpointSink(pool, nil)
		pgDisp := NewCheckpointDispatcher(pgSink)
		pgDisp.Submit(env)
		pgDisp.Close()

		var count int
		err := pool.QueryRow(ctx, "SELECT COUNT(*) FROM workflow_checkpoints WHERE trace_id = $1", "trace-456").Scan(&count)
		if err != nil {
			t.Fatalf("query count: %v", err)
		}
		if count != 1 {
			t.Fatalf("persisted count = %d, want 1", count)
		}
	}

	dto := toQueryRAGResponseDTO(&pb.QueryRAGResponse{
		Answer:    "hello",
		Citations: []string{"doc1"},
	})
	dtoBytes, err := json.Marshal(dto)
	if err != nil {
		t.Fatalf("marshal dto: %v", err)
	}
	if strings.Contains(string(dtoBytes), "context_snapshot") || strings.Contains(string(dtoBytes), "reformulate") {
		t.Fatalf("SSE DTO leaked checkpoint snapshot data: %s", string(dtoBytes))
	}
}

func TestWorkflowCheckpointPersistence(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for database integration tests")
	}

	ctx := t.Context()
	_, pool, _ := newWorkflowCheckpointsIsolatedPostgres(t, databaseURL)
	sink := NewPostgresCheckpointSink(pool, nil)
	dispatcher := NewCheckpointDispatcher(sink)

	traceID := "trace-persistence-" + uuid.NewString()

	envs := []*CheckpointEnvelope{
		{
			SessionID:       "sess-p",
			CorrelationID:   traceID,
			TraceID:         traceID,
			NodeID:          "reformulate",
			SequenceOrdinal: 1,
			ContextSnapshot: `{"original_query":"q1","reformulated_query":"q1_ref"}`,
			CreatedAt:       time.Now(),
		},
		{
			SessionID:       "sess-p",
			CorrelationID:   traceID,
			TraceID:         traceID,
			NodeID:          "retrieve",
			SequenceOrdinal: 2,
			ContextSnapshot: `{"vector_results":["c1","c2"],"bm25_results":["c1"]}`,
			CreatedAt:       time.Now(),
		},
		{
			SessionID:       "sess-p",
			CorrelationID:   traceID,
			TraceID:         traceID,
			NodeID:          "generate",
			SequenceOrdinal: 3,
			ContextSnapshot: `{"assembled_prompt":"prompt text","answer":"final ans"}`,
			CreatedAt:       time.Now(),
		},
	}

	for _, e := range envs {
		res := dispatcher.Submit(e)
		if res.Kind != DispatchAccepted {
			t.Fatalf("submit failed for ordinal %d: %v", e.SequenceOrdinal, res.Kind)
		}
	}
	dispatcher.Close()

	rows, err := pool.Query(ctx, "SELECT id, trace_id, sequence_ordinal, node_name, context_snapshot, created_at FROM workflow_checkpoints WHERE trace_id = $1 ORDER BY sequence_ordinal ASC", traceID)
	if err != nil {
		t.Fatalf("query checkpoints: %v", err)
	}
	defer rows.Close()

	var fetched []*db.WorkflowCheckpoint
	for rows.Next() {
		var r db.WorkflowCheckpoint
		if err := rows.Scan(&r.ID, &r.TraceID, &r.SequenceOrdinal, &r.NodeName, &r.ContextSnapshot, &r.CreatedAt); err != nil {
			t.Fatalf("scan checkpoint row: %v", err)
		}
		fetched = append(fetched, &r)
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("rows err: %v", err)
	}

	if len(fetched) != 3 {
		t.Fatalf("fetched count = %d, want 3", len(fetched))
	}

	for i, r := range fetched {
		expectedOrdinal := int32(i + 1)
		if r.SequenceOrdinal != expectedOrdinal {
			t.Fatalf("row %d ordinal = %d, want %d", i, r.SequenceOrdinal, expectedOrdinal)
		}
		if r.TraceID != traceID {
			t.Fatalf("row %d trace_id = %s, want %s", i, r.TraceID, traceID)
		}
		if len(r.ContextSnapshot) == 0 {
			t.Fatalf("row %d context_snapshot is empty", i)
		}
		var js map[string]any
		if err := json.Unmarshal(r.ContextSnapshot, &js); err != nil {
			t.Fatalf("row %d context_snapshot invalid json: %v", i, err)
		}
	}
}

func TestWorkflowCheckpointCancellationAtomicity(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for database integration tests")
	}

	ctx := t.Context()
	_, pool, _ := newWorkflowCheckpointsIsolatedPostgres(t, databaseURL)
	sink := NewPostgresCheckpointSink(pool, nil)

	traceID := "trace-cancel-" + uuid.NewString()
	env := &CheckpointEnvelope{
		SessionID:       "sess-c",
		CorrelationID:   traceID,
		TraceID:         traceID,
		NodeID:          "assemble_prompt",
		SequenceOrdinal: 1,
		ContextSnapshot: `{"assembled_prompt":"valid prompt"}`,
		CreatedAt:       time.Now(),
	}

	dispatcher := NewCheckpointDispatcher(sink)
	res := dispatcher.Submit(env)
	if res.Kind != DispatchAccepted {
		t.Fatalf("submit: %v", res.Kind)
	}
	dispatcher.Close()

	var count int
	err := pool.QueryRow(ctx, "SELECT COUNT(*) FROM workflow_checkpoints WHERE trace_id = $1", traceID).Scan(&count)
	if err != nil {
		t.Fatalf("query count: %v", err)
	}
	if count != 1 {
		t.Fatalf("persisted count after dispatcher = %d, want 1", count)
	}

	canceledCtx, cancel := context.WithCancel(ctx)
	cancel()
	directTraceID := "trace-direct-cancel-" + uuid.NewString()
	directEnv := &CheckpointEnvelope{
		SessionID:       "sess-c",
		CorrelationID:   directTraceID,
		TraceID:         directTraceID,
		NodeID:          "assemble_prompt",
		SequenceOrdinal: 1,
		ContextSnapshot: `{"assembled_prompt":"valid prompt"}`,
		CreatedAt:       time.Now(),
	}
	if err := sink.SaveCheckpoint(canceledCtx, directEnv); err == nil {
		t.Fatalf("expected error saving with directly canceled context, got nil")
	}
}

func TestWorkflowCheckpointBackpressureDoesNotStallSSE(t *testing.T) {
	inMem := NewInMemoryCheckpointSink()
	dispatcher := NewCheckpointDispatcher(inMem)

	traceID := "trace-bp-" + uuid.NewString()

	start := time.Now()
	for i := range 10 {
		env := &CheckpointEnvelope{
			SessionID:       "sess-bp",
			CorrelationID:   traceID,
			TraceID:         traceID,
			NodeID:          fmt.Sprintf("node_%d", i),
			SequenceOrdinal: uint64(i + 1),
			ContextSnapshot: `{"data":"ok"}`,
			CreatedAt:       time.Now(),
		}
		res := dispatcher.Submit(env)
		if res.Kind != DispatchAccepted && res.Kind != DispatchPending {
			t.Fatalf("submit kind = %v, expected Accepted or Pending", res.Kind)
		}
	}
	duration := time.Since(start)
	if duration > 1*time.Second {
		t.Fatalf("dispatcher.Submit stalled for %v; backpressure delayed caller", duration)
	}

	dispatcher.Close()

	cps := inMem.Checkpoints()
	if len(cps) == 0 {
		t.Fatalf("expected dispatched checkpoints in sink")
	}
}

func TestQueryRAGRealInvalidRequestAndDisconnect(t *testing.T) {
	req, err := http.NewRequestWithContext(t.Context(), "POST", "/rag/query", strings.NewReader(`{"invalid_json":`))
	if err != nil {
		t.Fatalf("create request: %v", err)
	}
	recorder := httptest.NewRecorder()

	a := app{}
	a.routes().ServeHTTP(recorder, req)

	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400 Bad Request", recorder.Code)
	}

	if strings.Contains(recorder.Body.String(), "context_snapshot") {
		t.Fatalf("error response body leaked context_snapshot: %s", recorder.Body.String())
	}
}

func TestRAGQueryPostOpenRecvFailureSSE(t *testing.T) {
	sessionID := "00000000-0000-4000-8000-000000000055"
	correlationID := "00000000-0000-4000-8000-000000000099"

	events := []*pb.WorkflowEvent{
		{
			SessionId:       sessionID,
			TraceId:         correlationID,
			SequenceOrdinal: 1,
			Event: &pb.WorkflowEvent_NodeStarted{
				NodeStarted: &pb.NodeStartedEvent{
					NodeName:      "ReformulateQuery",
					InputsSummary: "inputs",
				},
			},
		},
	}

	stream := &fakeQueryRAGStream{
		events: events,
		err:    status.Error(codes.Unavailable, "engine crashed mid-stream"),
	}

	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			return stream, nil
		},
	}

	server := httptest.NewServer(app{store: &fakeStore{}, engine: engine, logger: zap.NewNop()}.routes())
	defer server.Close()

	reqBody := `{"query":"post open recv fail test","session_id":"` + sessionID + `"}`
	httpReq, err := http.NewRequestWithContext(t.Context(), http.MethodPost, server.URL+"/rag/query", strings.NewReader(reqBody))
	if err != nil {
		t.Fatalf("create request error: %v", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "text/event-stream")

	res, err := http.DefaultClient.Do(httpReq)
	if err != nil {
		t.Fatalf("execute request error: %v", err)
	}
	defer res.Body.Close()

	if res.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want %d (StatusOK)", res.StatusCode, http.StatusOK)
	}
	if contentType := res.Header.Get("Content-Type"); !strings.HasPrefix(contentType, "text/event-stream") {
		t.Fatalf("Content-Type = %q, want text/event-stream", contentType)
	}

	bodyBytes, err := io.ReadAll(res.Body)
	if err != nil {
		t.Fatalf("read body error: %v", err)
	}
	bodyStr := string(bodyBytes)
	sseEvs := parseSSEEvents(bodyStr)

	var streamErrorEvent *sseEvent
	var sawWorkflowCompleted bool
	for i, ev := range sseEvs {
		if ev.Event == "stream_error" {
			streamErrorEvent = &sseEvs[i]
		}
		if ev.Event == "workflow_completed" {
			sawWorkflowCompleted = true
		}
	}

	if streamErrorEvent == nil {
		t.Fatalf("expected stream_error event in SSE stream, got: %s", bodyStr)
	}
	if !strings.Contains(streamErrorEvent.Data, "GRPC_RECV_ERROR") {
		t.Fatalf("stream_error data missing GRPC_RECV_ERROR code: %s", streamErrorEvent.Data)
	}
	if sawWorkflowCompleted {
		t.Fatalf("workflow_completed must not be sent on mid-stream gRPC failure: %s", bodyStr)
	}
}

func TestRAGQueryEOFWithoutTerminalSSE(t *testing.T) {
	sessionID := "00000000-0000-4000-8000-000000000055"
	correlationID := "00000000-0000-4000-8000-000000000099"

	events := []*pb.WorkflowEvent{
		{
			SessionId:       sessionID,
			TraceId:         correlationID,
			SequenceOrdinal: 1,
			Event: &pb.WorkflowEvent_NodeStarted{
				NodeStarted: &pb.NodeStartedEvent{
					NodeName:      "ReformulateQuery",
					InputsSummary: "inputs",
				},
			},
		},
	}

	engine := engineFunc{
		queryRAG: func(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
			return &fakeQueryRAGStream{events: events}, nil
		},
	}

	server := httptest.NewServer(app{store: &fakeStore{}, engine: engine, logger: zap.NewNop()}.routes())
	defer server.Close()

	reqBody := `{"query":"eof without terminal test","session_id":"` + sessionID + `"}`
	httpReq, err := http.NewRequestWithContext(t.Context(), http.MethodPost, server.URL+"/rag/query", strings.NewReader(reqBody))
	if err != nil {
		t.Fatalf("create request error: %v", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "text/event-stream")

	res, err := http.DefaultClient.Do(httpReq)
	if err != nil {
		t.Fatalf("execute request error: %v", err)
	}
	defer res.Body.Close()

	if res.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want %d (StatusOK)", res.StatusCode, http.StatusOK)
	}
	if contentType := res.Header.Get("Content-Type"); !strings.HasPrefix(contentType, "text/event-stream") {
		t.Fatalf("Content-Type = %q, want text/event-stream", contentType)
	}

	bodyBytes, err := io.ReadAll(res.Body)
	if err != nil {
		t.Fatalf("read body error: %v", err)
	}
	bodyStr := string(bodyBytes)
	sseEvs := parseSSEEvents(bodyStr)

	var streamErrorEvent *sseEvent
	for i, ev := range sseEvs {
		if ev.Event == "stream_error" {
			streamErrorEvent = &sseEvs[i]
		}
	}

	if streamErrorEvent == nil {
		t.Fatalf("expected stream_error event on EOF without terminal completion, got: %s", bodyStr)
	}
	if !strings.Contains(streamErrorEvent.Data, "STREAM_EOF_WITHOUT_TERMINAL") {
		t.Fatalf("stream_error data missing STREAM_EOF_WITHOUT_TERMINAL code: %s", streamErrorEvent.Data)
	}
}

func TestRAGQueryClientDisconnectCancelsRustWorkflow(t *testing.T) {
	repoRoot, err := filepath.Abs("..")
	if err != nil {
		t.Fatalf("resolve repository root: %v", err)
	}

	chatStarted := make(chan struct{}, 1)
	chatCanceled := make(chan struct{}, 1)
	var chatCalls atomic.Int32

	mock := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.Header.Get("Authorization") != "Bearer test-key" {
			http.Error(w, "unexpected authorization", http.StatusUnauthorized)
			return
		}

		switch r.URL.Path {
		case "/api/v1/embeddings":
			var request struct {
				Model string   `json:"model"`
				Input []string `json:"input"`
			}
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
				http.Error(w, "invalid embedding request", http.StatusBadRequest)
				return
			}
			vector := make([]float32, 2048)
			vector[0] = 1
			_ = json.NewEncoder(w).Encode(map[string]any{"data": []any{map[string]any{"embedding": vector}}})

		case "/api/v1/models":
			_ = json.NewEncoder(w).Encode(map[string]any{"data": []any{map[string]any{
				"id":                   "openai/gpt-4o-mini",
				"supported_parameters": []string{"response_format", "structured_outputs"},
			}}})

		case "/api/v1/chat/completions":
			_, _ = io.Copy(io.Discard, r.Body)
			_ = r.Body.Close()
			chatCalls.Add(1)
			select {
			case chatStarted <- struct{}{}:
			default:
			}
			select {
			case <-r.Context().Done():
				select {
				case chatCanceled <- struct{}{}:
				default:
				}
				return
			case <-time.After(10 * time.Second):
				http.Error(w, "timeout waiting for cancellation", http.StatusGatewayTimeout)
				return
			}

		default:
			http.NotFound(w, r)
		}
	}))
	defer mock.Close()

	tempRoot := t.TempDir()
	lancedbPath := filepath.Join(tempRoot, "lancedb")
	releasedPath := filepath.Join(tempRoot, "lancedb-released")
	defer releaseRAGPath(t, lancedbPath, releasedPath)
	port := getFreePort(t)
	engineAddr := fmt.Sprintf("127.0.0.1:%d", port)

	enginePath := filepath.Join(repoRoot, "engine", "target", "debug", "engine.exe")
	seederPath := filepath.Join(repoRoot, "engine", "target", "debug", "seed_rag_fixture.exe")
	if runtime.GOOS != "windows" {
		enginePath = filepath.Join(repoRoot, "engine", "target", "debug", "engine")
		seederPath = filepath.Join(repoRoot, "engine", "target", "debug", "seed_rag_fixture")
	}

	seederEnv := ragChildEnv()
	assertCleanRAGChildEnv(t, seederEnv)
	seeder := exec.Command(seederPath, "--lancedb-path", lancedbPath)
	seeder.Dir = repoRoot
	seeder.Env = seederEnv
	if output, err := seeder.CombinedOutput(); err != nil {
		t.Fatalf("run fixture seeder: %v\n%s", err, output)
	}

	engineEnv := ragChildEnv(
		"LANCET_ENGINE__GRPC_ADDR="+engineAddr,
		"LANCET_ENGINE__LANCEDB_PATH="+lancedbPath,
		"LANCET_OPENROUTER__EMBEDDING_ENDPOINT="+mock.URL+"/api/v1/embeddings",
		"LANCET_OPENROUTER__MODEL_METADATA_ENDPOINT="+mock.URL+"/api/v1/models",
		"LANCET_OPENROUTER__CHAT_ENDPOINT="+mock.URL+"/api/v1/chat/completions",
		"LANCET_OPENROUTER__GENERATION_MODEL=openai/gpt-4o-mini",
		"OPENROUTER_API_KEY=test-key",
	)
	assertCleanRAGChildEnv(t, engineEnv)
	engineCmd := exec.Command(enginePath)
	engineCmd.Dir = repoRoot
	engineCmd.Env = engineEnv
	var conn *grpc.ClientConn
	stdout, err := engineCmd.StdoutPipe()
	if err != nil {
		t.Fatalf("capture engine stdout: %v", err)
	}
	stderr, err := engineCmd.StderrPipe()
	if err != nil {
		t.Fatalf("capture engine stderr: %v", err)
	}
	if err := engineCmd.Start(); err != nil {
		t.Fatalf("start Rust engine: %v", err)
	}
	engineDone := make(chan struct{})
	go func() {
		_ = engineCmd.Wait()
		close(engineDone)
	}()
	lines := make(chan string, 64)
	go scanRAGOutput(stdout, lines)
	go scanRAGOutput(stderr, lines)
	defer func() {
		if conn != nil {
			_ = conn.Close()
		}
		terminateRAGProcess(engineCmd, nil)
		<-engineDone
	}()

	var mu sync.Mutex
	var engineLines []string
	servedChan := make(chan struct{})
	var servedOnce sync.Once
	go func() {
		for line := range lines {
			mu.Lock()
			engineLines = append(engineLines, line)
			mu.Unlock()
			if strings.Contains(line, "Rust RAG Engine serving") {
				servedOnce.Do(func() { close(servedChan) })
			}
		}
	}()

	select {
	case <-servedChan:
	case <-engineDone:
		t.Fatal("Rust engine exited before readiness")
	case <-time.After(30 * time.Second):
		t.Fatal("Rust engine did not emit serving milestone within 30 seconds")
	}

	conn, err = grpc.NewClient(engineAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatalf("dial exact Rust gRPC endpoint: %v", err)
	}
	client := pb.NewLancetServiceClient(conn)

	pinged := false
	var lastPingErr error
	pingDeadline := time.Now().Add(30 * time.Second)
	for delay := 10 * time.Millisecond; time.Now().Before(pingDeadline); delay = min(delay*2, 250*time.Millisecond) {
		pingCtx, pingCancel := context.WithTimeout(t.Context(), 2*time.Second)
		_, pingErr := client.Ping(pingCtx, &pb.PingRequest{Value: "ping"})
		lastPingErr = pingErr
		pingCancel()
		if pingErr == nil {
			pinged = true
			break
		}
		select {
		case <-engineDone:
			t.Fatalf("Rust engine exited during Ping readiness probe")
		default:
		}
		time.Sleep(delay)
	}
	if !pinged {
		t.Fatalf("generated gRPC Ping did not succeed within 30 seconds: %v", lastPingErr)
	}

	gwServer := httptest.NewServer(app{store: &fakeStore{}, engine: grpcEngine{client: client}, logger: zap.NewNop()}.routes())
	defer gwServer.Close()

	httpClient := &http.Client{}
	clientCtx, clientCancel := context.WithCancel(t.Context())
	defer clientCancel()
	requestBody := `{"query":"What does LEXICAL_FIXTURE_IDENTIFIER_2026 prove?","session_id":"00000000-0000-4000-8000-000000000007"}`
	httpReq, err := http.NewRequestWithContext(clientCtx, http.MethodPost, gwServer.URL+"/rag/query", strings.NewReader(requestBody))
	if err != nil {
		t.Fatalf("create request: %v", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "text/event-stream")

	resp, err := httpClient.Do(httpReq)
	if err != nil {
		t.Fatalf("execute request: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", resp.StatusCode)
	}

	reader := bufio.NewReader(resp.Body)
	for {
		line, readErr := reader.ReadString('\n')
		if readErr != nil {
			break
		}
		if strings.Contains(line, "GenerateAnswer") {
			break
		}
	}

	select {
	case <-chatStarted:
	case <-time.After(10 * time.Second):
		t.Fatal("chat completions call was not received by mock provider within 10s")
	}

	resp.Body.Close()
	clientCancel()

	select {
	case <-chatCanceled:
	case <-time.After(5 * time.Second):
		t.Fatalf("mock OpenRouter did not observe request context cancellation within 5s; engine output: %s", strings.Join(engineLines, " | "))
	}

	time.Sleep(200 * time.Millisecond)
	if calls := chatCalls.Load(); calls != 1 {
		t.Fatalf("expected exactly 1 chat call, got %d", calls)
	}
}

func TestRetrievalSnapshotWireContract(t *testing.T) {
	orig := &pb.RetrievalSnapshot{
		IndexGeneration: "gen-12345",
		EmbeddingModel:  "nvidia/llama-nemotron-embed-vl-1b-v2:free",
		VectorWeight:    1.0,
		Bm25Weight:      1.0,
		RrfK:            60,
		CandidateLimit:  32,
		FinalLimit:      8,
		ActiveFilter: &pb.DocumentFilter{
			DocumentIds:  []string{"doc-1", "doc-2"},
			ContentTypes: []string{"text/markdown"},
		},
		ResultHash:        "hash-abcdef0123456789",
		VariantCount:      3,
		VariantIdentities: []string{"orig", "var1", "var2"},
	}

	data, err := proto.Marshal(orig)
	if err != nil {
		t.Fatalf("proto.Marshal failed: %v", err)
	}

	var roundtrip pb.RetrievalSnapshot
	if err := proto.Unmarshal(data, &roundtrip); err != nil {
		t.Fatalf("proto.Unmarshal failed: %v", err)
	}

	if roundtrip.IndexGeneration != orig.IndexGeneration ||
		roundtrip.EmbeddingModel != orig.EmbeddingModel ||
		roundtrip.VectorWeight != orig.VectorWeight ||
		roundtrip.Bm25Weight != orig.Bm25Weight ||
		roundtrip.RrfK != orig.RrfK ||
		roundtrip.CandidateLimit != orig.CandidateLimit ||
		roundtrip.FinalLimit != orig.FinalLimit ||
		roundtrip.ResultHash != orig.ResultHash {
		t.Fatalf("scalar fields mismatch after roundtrip: got %#v, want %#v", roundtrip, orig)
	}

	if roundtrip.VariantCount != 3 {
		t.Fatalf("VariantCount = %d, want 3", roundtrip.VariantCount)
	}

	if len(roundtrip.VariantIdentities) != 3 ||
		roundtrip.VariantIdentities[0] != "orig" ||
		roundtrip.VariantIdentities[1] != "var1" ||
		roundtrip.VariantIdentities[2] != "var2" {
		t.Fatalf("VariantIdentities = %#v, want %#v", roundtrip.VariantIdentities, orig.VariantIdentities)
	}
}

type gatingCheckpointSink struct {
	target CheckpointSink
	gate   chan struct{}
}

func (g *gatingCheckpointSink) SaveCheckpoint(ctx context.Context, env *CheckpointEnvelope) error {
	<-g.gate
	return g.target.SaveCheckpoint(ctx, env)
}

func TestWorkflowCheckpointPendingDrainAndPersistence(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is not set")
	}

	_, pool, _ := newWorkflowCheckpointsIsolatedPostgres(t, databaseURL)

	realSink := NewPostgresCheckpointSink(pool, zap.NewNop())
	gate := make(chan struct{})
	gatedSink := &gatingCheckpointSink{
		target: realSink,
		gate:   gate,
	}
	dispatcher := NewCheckpointDispatcher(gatedSink)

	traceID := uuid.NewString()

	canonicalSnapshot := `{
		"session_id": "00000000-0000-4000-8000-000000000001",
		"trace_id": "` + traceID + `",
		"original_query": "test query",
		"variants": ["test query"],
		"vector_results": [],
		"bm25_results": [],
		"final_candidates": [],
		"graph_context": null,
		"graph_facts": [],
		"evidence_blocks": [],
		"assembled_prompt": null,
		"answer": null,
		"citations": [],
		"answer_basis": 0,
		"structured_citations": [],
		"notices": [],
		"snapshot": null,
		"query_embedding": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
		"snapshot_state": "accumulated"
	}`

	if !json.Valid([]byte(canonicalSnapshot)) {
		t.Fatalf("canonicalSnapshot is not valid JSON")
	}

	var acceptedCount, pendingCount int
	for i := 1; i <= 10; i++ {
		env := &CheckpointEnvelope{
			TraceID:         traceID,
			SequenceOrdinal: uint64(i),
			NodeID:          fmt.Sprintf("Node-%d", i),
			CheckpointType:  "NodeCompleted",
			ContextSnapshot: canonicalSnapshot,
			CreatedAt:       time.Now(),
		}
		res := dispatcher.Submit(env)
		if res.Kind == DispatchAccepted {
			acceptedCount++
		} else if res.Kind == DispatchPending {
			pendingCount++
			if res.Envelope != env {
				t.Fatalf("envelope %d expected res.Envelope to match env", i)
			}
			if err := dispatcher.RetainPending(res.Envelope); err != nil {
				t.Fatalf("retain pending envelope %d: %v", i, err)
			}
		} else {
			t.Fatalf("envelope %d unexpected dispatch result kind: %v", i, res.Kind)
		}
	}
	if acceptedCount < 4 {
		t.Fatalf("expected at least 4 accepted envelopes, got %d", acceptedCount)
	}
	if pendingCount < 4 {
		t.Fatalf("expected at least 4 pending envelopes, got %d", pendingCount)
	}

	close(gate)
	dispatcher.Close()

	rows, err := pool.Query(t.Context(), `
		SELECT id, trace_id, sequence_ordinal, node_name, context_snapshot, created_at
		FROM workflow_checkpoints
		WHERE trace_id = $1
		ORDER BY sequence_ordinal ASC
	`, traceID)
	if err != nil {
		t.Fatalf("query workflow_checkpoints: %v", err)
	}
	defer rows.Close()

	type persistedRow struct {
		ID              string
		TraceID         string
		SequenceOrdinal int32
		NodeName        string
		ContextSnapshot []byte
		CreatedAt       time.Time
	}

	var persisted []persistedRow
	for rows.Next() {
		var r persistedRow
		if err := rows.Scan(&r.ID, &r.TraceID, &r.SequenceOrdinal, &r.NodeName, &r.ContextSnapshot, &r.CreatedAt); err != nil {
			t.Fatalf("scan workflow_checkpoint row: %v", err)
		}
		persisted = append(persisted, r)
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("rows error: %v", err)
	}

	if len(persisted) != 10 {
		t.Fatalf("expected 10 persisted checkpoints, got %d", len(persisted))
	}

	requiredKeys := []string{
		"session_id", "trace_id", "original_query", "variants",
		"vector_results", "bm25_results", "final_candidates",
		"graph_context", "graph_facts", "evidence_blocks",
		"assembled_prompt", "answer", "citations", "answer_basis",
		"structured_citations", "notices", "snapshot", "query_embedding", "snapshot_state",
	}

	for i, r := range persisted {
		expectedOrdinal := int32(i + 1)
		if r.SequenceOrdinal != expectedOrdinal {
			t.Fatalf("row %d sequence_ordinal = %d, want %d", i, r.SequenceOrdinal, expectedOrdinal)
		}
		if r.NodeName != fmt.Sprintf("Node-%d", expectedOrdinal) {
			t.Fatalf("row %d node_name = %q, want %q", i, r.NodeName, fmt.Sprintf("Node-%d", expectedOrdinal))
		}
		if !json.Valid(r.ContextSnapshot) {
			t.Fatalf("row %d context_snapshot is not valid JSON", i)
		}

		var snapshotMap map[string]any
		if err := json.Unmarshal(r.ContextSnapshot, &snapshotMap); err != nil {
			t.Fatalf("row %d unmarshal context_snapshot: %v", i, err)
		}

		for _, k := range requiredKeys {
			if _, exists := snapshotMap[k]; !exists {
				t.Fatalf("row %d context_snapshot missing exact required key %q", i, k)
			}
		}
	}
}

