package db

import (
	"context"
	"errors"
	"os"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
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

func TestConditionalTerminalUpdateRace(t *testing.T) {
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
	defer tx.Rollback(ctx)
	q := New(tx)
	id := "race-document"
	if _, err := q.InsertDocument(ctx, InsertDocumentParams{ID: id, Filename: "race.txt", FileSize: 1, ChunkStrategy: "fixed", ChunkSize: 500, ChunkOverlap: 50}); err != nil {
		t.Fatal(err)
	}
	first, err := q.UpdateDocumentStatus(ctx, UpdateDocumentStatusParams{ID: id, Status: "failed", ChunkCount: 0})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := q.UpdateDocumentStatus(ctx, UpdateDocumentStatusParams{ID: id, Status: "completed", ChunkCount: 3}); err != pgx.ErrNoRows {
		t.Fatalf("second update = %v, want pgx.ErrNoRows", err)
	}
	got, err := q.GetDocument(ctx, id)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != first.Status || got.ChunkCount != first.ChunkCount {
		t.Fatalf("winner changed: %+v", got)
	}
}

func TestReconciliationIntentRecordAndClaim(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for database integration tests")
	}

	ctx := t.Context()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("create database pool: %v", err)
	}
	defer pool.Close()

	docID := "record-claim-" + uuid.NewString()

	t.Cleanup(func() {
		cleanupCtx := context.Background()
		_, _ = pool.Exec(cleanupCtx, "DELETE FROM documents WHERE id = $1", docID)
	})

	q := New(pool)

	_, err = q.InsertDocument(ctx, InsertDocumentParams{
		ID:            docID,
		Filename:      "test.txt",
		FileSize:      100,
		ChunkStrategy: "fixed-size",
		ChunkSize:     500,
		ChunkOverlap:  50,
	})
	if err != nil {
		t.Fatalf("insert document: %v", err)
	}

	intent, err := q.CreateReconciliationIntent(ctx, CreateReconciliationIntentParams{
		ID:            docID,
		DesiredStatus: "failed",
		ReasonClass:   "engine_admission_failed",
	})
	if err != nil {
		t.Fatalf("create reconciliation intent: %v", err)
	}

	if intent.DocumentID != docID {
		t.Errorf("got document_id %q, want %q", intent.DocumentID, docID)
	}
	if intent.DesiredStatus != "failed" {
		t.Errorf("got desired_status %q, want 'failed'", intent.DesiredStatus)
	}
	if intent.ReasonClass != "engine_admission_failed" {
		t.Errorf("got reason_class %q, want 'engine_admission_failed'", intent.ReasonClass)
	}
	if intent.RetryCount != 0 {
		t.Errorf("got retry_count %d, want 0", intent.RetryCount)
	}

	time.Sleep(20 * time.Millisecond)

	leaseTime := time.Now().UTC().Add(15 * time.Minute)
	claimed, err := q.ClaimDueReconciliationIntents(ctx, ClaimDueReconciliationIntentsParams{
		Limit: 10,
		NextAttemptAt: pgtype.Timestamp{
			Time:  leaseTime,
			Valid: true,
		},
	})
	if err != nil {
		t.Fatalf("claim due intents: %v", err)
	}

	var found *DocumentReconciliationIntent
	for i := range claimed {
		if claimed[i].DocumentID == docID {
			found = &claimed[i]
			break
		}
	}
	if found == nil {
		t.Fatalf("expected document %q in claimed intents batch", docID)
	}
}

func TestReconciliationIntentClaimLeaseIsExclusive(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for database integration tests")
	}

	ctx := t.Context()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("create database pool: %v", err)
	}
	defer pool.Close()

	docID := "exclusive-claim-" + uuid.NewString()

	t.Cleanup(func() {
		cleanupCtx := context.Background()
		_, _ = pool.Exec(cleanupCtx, "DELETE FROM documents WHERE id = $1", docID)
	})

	// Clear pre-existing documents to isolate claim batching
	_, _ = pool.Exec(ctx, "DELETE FROM documents")

	q := New(pool)

	_, err = q.InsertDocument(ctx, InsertDocumentParams{
		ID:            docID,
		Filename:      "exclusive.txt",
		FileSize:      200,
		ChunkStrategy: "fixed-size",
		ChunkSize:     500,
		ChunkOverlap:  50,
	})
	if err != nil {
		t.Fatalf("insert document: %v", err)
	}

	_, err = q.CreateReconciliationIntent(ctx, CreateReconciliationIntentParams{
		ID:            docID,
		DesiredStatus: "failed",
		ReasonClass:   "admission_rejected",
	})
	if err != nil {
		t.Fatalf("create reconciliation intent: %v", err)
	}

	time.Sleep(20 * time.Millisecond)

	var wg sync.WaitGroup
	claimedCount := 0
	var mu sync.Mutex

	leaseTime := time.Now().UTC().Add(10 * time.Minute)

	for range 2 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			connQueries := New(pool)
			claimed, claimErr := connQueries.ClaimDueReconciliationIntents(ctx, ClaimDueReconciliationIntentsParams{
				Limit: 1,
				NextAttemptAt: pgtype.Timestamp{
					Time:  leaseTime,
					Valid: true,
				},
			})
			if claimErr != nil {
				t.Errorf("claim error: %v", claimErr)
				return
			}
			for _, item := range claimed {
				if item.DocumentID == docID {
					mu.Lock()
					claimedCount++
					mu.Unlock()
				}
			}
		}()
	}

	wg.Wait()

	if claimedCount != 1 {
		t.Fatalf("expected exactly 1 claimer to receive due intent, got %d", claimedCount)
	}
}

func TestReconciliationIntentPersistsAcrossPoolRestart(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for database integration tests")
	}

	ctx := t.Context()
	docID := "persist-restart-" + uuid.NewString()

	pool1, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("create pool 1: %v", err)
	}

	t.Cleanup(func() {
		cleanupCtx := context.Background()
		p, err := pgxpool.New(cleanupCtx, databaseURL)
		if err == nil {
			_, _ = p.Exec(cleanupCtx, "DELETE FROM documents WHERE id = $1", docID)
			p.Close()
		}
	})

	q1 := New(pool1)
	_, err = q1.InsertDocument(ctx, InsertDocumentParams{
		ID:            docID,
		Filename:      "restart.txt",
		FileSize:      300,
		ChunkStrategy: "fixed-size",
		ChunkSize:     500,
		ChunkOverlap:  50,
	})
	if err != nil {
		t.Fatalf("insert document: %v", err)
	}

	created, err := q1.CreateReconciliationIntent(ctx, CreateReconciliationIntentParams{
		ID:            docID,
		DesiredStatus: "failed",
		ReasonClass:   "process_crash_recovery",
	})
	if err != nil {
		t.Fatalf("create intent: %v", err)
	}

	pool1.Close()

	pool2, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("create pool 2: %v", err)
	}
	defer pool2.Close()

	q2 := New(pool2)
	got, err := q2.GetReconciliationIntent(ctx, docID)
	if err != nil {
		t.Fatalf("get intent from pool 2: %v", err)
	}

	if got.DocumentID != created.DocumentID || got.ReasonClass != created.ReasonClass {
		t.Fatalf("retrieved intent from new pool %+v != expected %+v", got, created)
	}
}

func TestReconciliationIntentReschedulesAndCompletes(t *testing.T) {
	databaseURL := os.Getenv("TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("TEST_DATABASE_URL is required for database integration tests")
	}

	ctx := t.Context()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("create pool: %v", err)
	}
	defer pool.Close()

	docID := "resched-complete-" + uuid.NewString()

	t.Cleanup(func() {
		cleanupCtx := context.Background()
		_, _ = pool.Exec(cleanupCtx, "DELETE FROM documents WHERE id = $1", docID)
	})

	q := New(pool)

	_, err = q.InsertDocument(ctx, InsertDocumentParams{
		ID:            docID,
		Filename:      "resched.txt",
		FileSize:      400,
		ChunkStrategy: "fixed-size",
		ChunkSize:     500,
		ChunkOverlap:  50,
	})
	if err != nil {
		t.Fatalf("insert document: %v", err)
	}

	_, err = q.CreateReconciliationIntent(ctx, CreateReconciliationIntentParams{
		ID:            docID,
		DesiredStatus: "failed",
		ReasonClass:   "transient_db_error",
	})
	if err != nil {
		t.Fatalf("create intent: %v", err)
	}

	// 1. Non-terminal document row attempt to delete intent must NOT remove the intent
	tag, err := q.DeleteReconciliationIntent(ctx, docID)
	if err != nil {
		t.Fatalf("delete reconciliation intent on non-terminal doc: %v", err)
	}
	if tag.RowsAffected() != 0 {
		t.Fatalf("expected 0 rows deleted for non-terminal document, got %d", tag.RowsAffected())
	}

	// 2. Reschedule intent with incremented retry count and last error class
	nextAttempt := time.Now().UTC().Add(5 * time.Minute)
	rescheduled, err := q.RescheduleReconciliationIntent(ctx, RescheduleReconciliationIntentParams{
		DocumentID: docID,
		NextAttemptAt: pgtype.Timestamp{
			Time:  nextAttempt,
			Valid: true,
		},
		LastErrorClass: pgtype.Text{
			String: "connection_timeout",
			Valid:  true,
		},
	})
	if err != nil {
		t.Fatalf("reschedule intent: %v", err)
	}

	if rescheduled.RetryCount != 1 {
		t.Errorf("got retry_count %d, want 1", rescheduled.RetryCount)
	}
	if !rescheduled.LastErrorClass.Valid || rescheduled.LastErrorClass.String != "connection_timeout" {
		t.Errorf("got last_error_class %+v, want 'connection_timeout'", rescheduled.LastErrorClass)
	}

	// 3. Confirm document transitions to terminal status 'failed'
	_, err = q.UpdateDocumentStatus(ctx, UpdateDocumentStatusParams{
		ID:         docID,
		Status:     "failed",
		ChunkCount: 0,
		ErrorMessage: pgtype.Text{
			String: "reconciliation failed",
			Valid:  true,
		},
	})
	if err != nil {
		t.Fatalf("update document status: %v", err)
	}

	// 4. Delete intent after terminal status confirmed
	tag, err = q.DeleteReconciliationIntent(ctx, docID)
	if err != nil {
		t.Fatalf("delete reconciliation intent after terminal winner: %v", err)
	}
	if tag.RowsAffected() != 1 {
		t.Fatalf("expected 1 row deleted after terminal confirmation, got %d", tag.RowsAffected())
	}

	// 5. Verify intent no longer exists
	_, err = q.GetReconciliationIntent(ctx, docID)
	if !errors.Is(err, pgx.ErrNoRows) {
		t.Fatalf("expected pgx.ErrNoRows after deletion, got %v", err)
	}

	// 6. Idempotent deletion again returns 0 rows without error
	tag, err = q.DeleteReconciliationIntent(ctx, docID)
	if err != nil {
		t.Fatalf("idempotent delete intent: %v", err)
	}
	if tag.RowsAffected() != 0 {
		t.Fatalf("expected 0 rows deleted on idempotent call, got %d", tag.RowsAffected())
	}
}

