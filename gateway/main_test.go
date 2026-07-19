package main

import (
	"bytes"
	"context"
	"errors"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgtype"
	"go.uber.org/zap"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/lancet/gateway/db"
	pb "github.com/lancet/gateway/proto/lancet/v1"
)

type fakeStore struct {
	document db.Document
	inserted *db.InsertDocumentParams
	updated  *db.UpdateDocumentStatusParams
}

func (s *fakeStore) Insert(_ context.Context, p db.InsertDocumentParams) (db.Document, error) {
	s.inserted = &p
	s.document = db.Document{ID: p.ID, Filename: p.Filename, FileSize: p.FileSize, Status: "queued"}
	return s.document, nil
}

func (s *fakeStore) Get(context.Context, string) (db.Document, error) {
	return s.document, nil
}

func (s *fakeStore) UpdateStatus(_ context.Context, p db.UpdateDocumentStatusParams) (db.Document, error) {
	s.updated = &p
	s.document.Status = p.Status
	s.document.ChunkCount = p.ChunkCount
	s.document.ErrorMessage = p.ErrorMessage
	return s.document, nil
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
	engine := engineFunc{ingest: func(context.Context, string, string, []byte) error {
		return status.Error(codes.ResourceExhausted, "full")
	}}
	recorder := httptest.NewRecorder()
	app{store: store, engine: engine, logger: zap.NewNop()}.routes().ServeHTTP(recorder, multipartRequest(t, "../notes.txt", []byte("hello")))
	if recorder.Code != http.StatusTooManyRequests {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusTooManyRequests)
	}
	if store.inserted == nil || store.inserted.Filename != "notes.txt" || store.inserted.FileSize != 5 {
		t.Fatalf("unexpected insert params: %#v", store.inserted)
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

type engineFunc struct {
	ingest func(context.Context, string, string, []byte) error
	status *pb.GetIngestionStatusResponse
}

func (e engineFunc) Ingest(ctx context.Context, id, filename string, src io.Reader) error {
	data, err := io.ReadAll(src)
	if err != nil {
		return err
	}
	if e.ingest == nil {
		return nil
	}
	return e.ingest(ctx, id, filename, data)
}

func (e engineFunc) IngestionStatus(context.Context, string) (*pb.GetIngestionStatusResponse, error) {
	if e.status == nil {
		return nil, errors.New("status unavailable")
	}
	return e.status, nil
}

func (engineFunc) Ping(context.Context) (time.Duration, error) { return time.Millisecond, nil }
