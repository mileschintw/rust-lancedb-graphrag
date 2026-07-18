package db

import (
	"context"
	"os"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestDocumentQueries(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for database integration tests")
	}

	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("create database pool: %v", err)
	}
	defer pool.Close()

	tx, err := pool.Begin(ctx)
	if err != nil {
		t.Fatalf("begin transaction: %v", err)
	}
	defer func() {
		if rollbackErr := tx.Rollback(ctx); rollbackErr != nil && rollbackErr != pgx.ErrTxClosed {
			t.Errorf("rollback transaction: %v", rollbackErr)
		}
	}()

	queries := New(tx)
	inserted, err := queries.InsertDocument(ctx, InsertDocumentParams{
		ID:            "test-document",
		Filename:      "document.txt",
		FileSize:      128,
		ChunkStrategy: "fixed",
		ChunkSize:     512,
		ChunkOverlap:  64,
	})
	if err != nil {
		t.Fatalf("insert document: %v", err)
	}
	if inserted.Status != "queued" || inserted.ChunkCount != 0 {
		t.Fatalf("unexpected queued document: %+v", inserted)
	}

	updated, err := queries.UpdateDocumentStatus(ctx, UpdateDocumentStatusParams{
		ID:         inserted.ID,
		Status:     "completed",
		ChunkCount: 3,
	})
	if err != nil {
		t.Fatalf("update document status: %v", err)
	}
	if updated.Status != "completed" || updated.ChunkCount != 3 {
		t.Fatalf("unexpected updated document: %+v", updated)
	}

	got, err := queries.GetDocument(ctx, inserted.ID)
	if err != nil {
		t.Fatalf("get document: %v", err)
	}
	if got.Filename != inserted.Filename || got.FileSize != inserted.FileSize {
		t.Fatalf("retrieved document did not match insertion: %+v", got)
	}
}
