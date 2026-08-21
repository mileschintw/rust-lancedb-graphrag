package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
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

	"github.com/lancet/gateway/db"
	"github.com/lancet/gateway/internal/config"
	"github.com/lancet/gateway/internal/engineclient"
	"github.com/lancet/gateway/internal/sse"
	_ "github.com/lancet/gateway/internal/telemetry"
	pb "github.com/lancet/gateway/proto/lancet/v1"
)

const maxUploadBytes int64 = 10 << 20
const maxRAGQueryBodyBytes int64 = 32 << 10
const defaultChunkSize = 500
const defaultChunkOverlap = 50

// Authoritative Rust MAX_CHUNK_SIZE ceiling mirror
const maxChunkSize = 1048576

const ingestCompensationTimeout = 5 * time.Second

type documentStore interface {
	Insert(context.Context, db.InsertDocumentParams) (db.Document, error)
	Get(context.Context, string) (db.Document, error)
	UpdateStatus(context.Context, db.UpdateDocumentStatusParams) (db.Document, error)
	CreateReconciliationIntent(context.Context, db.CreateReconciliationIntentParams) (db.DocumentReconciliationIntent, error)
	ClaimDueReconciliationIntents(context.Context, db.ClaimDueReconciliationIntentsParams) ([]db.DocumentReconciliationIntent, error)
	DeleteReconciliationIntent(context.Context, string) (pgconn.CommandTag, error)
	RescheduleReconciliationIntent(context.Context, db.RescheduleReconciliationIntentParams) (db.DocumentReconciliationIntent, error)
	GetReconciliationIntent(context.Context, string) (db.DocumentReconciliationIntent, error)
}

type postgresStore struct{ pool *pgxpool.Pool }

func (s postgresStore) Insert(ctx context.Context, p db.InsertDocumentParams) (db.Document, error) {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return db.Document{}, err
	}
	defer tx.Rollback(ctx)
	doc, err := db.New(tx).InsertDocument(ctx, p)
	if err != nil {
		return db.Document{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return db.Document{}, err
	}
	return doc, nil
}
func (s postgresStore) Get(ctx context.Context, id string) (db.Document, error) {
	return db.New(s.pool).GetDocument(ctx, id)
}
func (s postgresStore) UpdateStatus(ctx context.Context, p db.UpdateDocumentStatusParams) (db.Document, error) {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return db.Document{}, err
	}
	defer tx.Rollback(ctx)
	doc, err := db.New(tx).UpdateDocumentStatus(ctx, p)
	if err != nil {
		return db.Document{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return db.Document{}, err
	}
	return doc, nil
}
func (s postgresStore) CreateReconciliationIntent(ctx context.Context, p db.CreateReconciliationIntentParams) (db.DocumentReconciliationIntent, error) {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return db.DocumentReconciliationIntent{}, err
	}
	defer tx.Rollback(ctx)
	intent, err := db.New(tx).CreateReconciliationIntent(ctx, p)
	if err != nil {
		return db.DocumentReconciliationIntent{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return db.DocumentReconciliationIntent{}, err
	}
	return intent, nil
}
func (s postgresStore) ClaimDueReconciliationIntents(ctx context.Context, p db.ClaimDueReconciliationIntentsParams) ([]db.DocumentReconciliationIntent, error) {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	intents, err := db.New(tx).ClaimDueReconciliationIntents(ctx, p)
	if err != nil {
		return nil, err
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, err
	}
	return intents, nil
}
func (s postgresStore) DeleteReconciliationIntent(ctx context.Context, id string) (pgconn.CommandTag, error) {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return pgconn.CommandTag{}, err
	}
	defer tx.Rollback(ctx)
	tag, err := db.New(tx).DeleteReconciliationIntent(ctx, id)
	if err != nil {
		return pgconn.CommandTag{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return pgconn.CommandTag{}, err
	}
	return tag, nil
}
func (s postgresStore) RescheduleReconciliationIntent(ctx context.Context, p db.RescheduleReconciliationIntentParams) (db.DocumentReconciliationIntent, error) {
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return db.DocumentReconciliationIntent{}, err
	}
	defer tx.Rollback(ctx)
	intent, err := db.New(tx).RescheduleReconciliationIntent(ctx, p)
	if err != nil {
		return db.DocumentReconciliationIntent{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return db.DocumentReconciliationIntent{}, err
	}
	return intent, nil
}
func (s postgresStore) GetReconciliationIntent(ctx context.Context, id string) (db.DocumentReconciliationIntent, error) {
	return db.New(s.pool).GetReconciliationIntent(ctx, id)
}

type app struct {
	store      documentStore
	engine     engineclient.Engine
	logger     *zap.Logger
	retrySleep func(int)
	dispatcher *CheckpointDispatcher
}

func (a app) backoff(attempt int) {
	if a.retrySleep != nil {
		a.retrySleep(attempt)
		return
	}
	time.Sleep(time.Duration(attempt*50) * time.Millisecond)
}

// compensateFailedIngest prevents an admission failure from leaving an
// indefinitely queued PostgreSQL row. The original gRPC error remains the
// response authority; a compensation failure is operational detail only.
func (a app) compensateFailedIngest(id string, ingestErr error) {
	intentCtx, intentCancel := context.WithTimeout(context.Background(), ingestCompensationTimeout)
	_, _ = a.store.CreateReconciliationIntent(intentCtx, db.CreateReconciliationIntentParams{
		ID:            id,
		DesiredStatus: "failed",
		ReasonClass:   "failed_admission",
	})
	intentCancel()

	errText := pgtype.Text{String: "engine ingestion failed", Valid: true}
	params := db.UpdateDocumentStatusParams{
		ID:           id,
		Status:       "failed",
		ChunkCount:   0,
		ErrorMessage: errText,
	}

	for attempt := 1; attempt <= 5; attempt++ {
		ctx, cancel := context.WithTimeout(context.Background(), ingestCompensationTimeout)
		_, err := a.store.UpdateStatus(ctx, params)
		cancel()
		if err == nil {
			delCtx, delCancel := context.WithTimeout(context.Background(), ingestCompensationTimeout)
			_, _ = a.store.DeleteReconciliationIntent(delCtx, id)
			delCancel()
			return
		}
		if errors.Is(err, pgx.ErrNoRows) {
			checkCtx, checkCancel := context.WithTimeout(context.Background(), ingestCompensationTimeout)
			winner, getErr := a.store.Get(checkCtx, id)
			checkCancel()
			if getErr == nil && (winner.Status == "completed" || winner.Status == "failed") {
				delCtx, delCancel := context.WithTimeout(context.Background(), ingestCompensationTimeout)
				_, _ = a.store.DeleteReconciliationIntent(delCtx, id)
				delCancel()
				return
			}
		}
		a.logger.Error("compensate failed ingestion", zap.String("document_id", id), zap.Int("attempt", attempt), zap.Error(ingestErr), zap.Error(err))
		a.backoff(attempt)
	}
}

type durableReconciler struct {
	store       documentStore
	logger      *zap.Logger
	interval    time.Duration
	batchSize   int32
	leaseWindow time.Duration
	nowFunc     func() time.Time
	maxBackoff  time.Duration
}

func newDurableReconciler(store documentStore, logger *zap.Logger) *durableReconciler {
	return &durableReconciler{
		store:       store,
		logger:      logger,
		interval:    1 * time.Second,
		batchSize:   10,
		leaseWindow: 30 * time.Second,
		nowFunc:     time.Now,
		maxBackoff:  60 * time.Second,
	}
}

func (r *durableReconciler) Run(ctx context.Context) {
	r.reconcileBatch(ctx)
	ticker := time.NewTicker(r.interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			r.reconcileBatch(ctx)
		}
	}
}

func (r *durableReconciler) reconcileBatch(ctx context.Context) {
	if ctx.Err() != nil {
		return
	}
	now := r.nowFunc()
	leaseExpiry := now.Add(r.leaseWindow)

	claimCtx, claimCancel := context.WithTimeout(ctx, 5*time.Second)
	intents, err := r.store.ClaimDueReconciliationIntents(claimCtx, db.ClaimDueReconciliationIntentsParams{
		Limit:         r.batchSize,
		NextAttemptAt: pgtype.Timestamp{Time: leaseExpiry, Valid: true},
	})
	claimCancel()
	if err != nil {
		if !errors.Is(err, context.Canceled) && ctx.Err() == nil {
			r.logger.Error("claim due reconciliation intents", zap.Error(err))
		}
		return
	}

	for _, intent := range intents {
		if ctx.Err() != nil {
			return
		}
		r.reconcileOne(ctx, intent)
	}
}

func (r *durableReconciler) reconcileOne(ctx context.Context, intent db.DocumentReconciliationIntent) {
	workCtx, workCancel := context.WithTimeout(ctx, 5*time.Second)
	defer workCancel()

	errText := pgtype.Text{String: "engine ingestion failed", Valid: true}
	_, err := r.store.UpdateStatus(workCtx, db.UpdateDocumentStatusParams{
		ID:           intent.DocumentID,
		Status:       intent.DesiredStatus,
		ChunkCount:   0,
		ErrorMessage: errText,
	})

	if err == nil {
		_, _ = r.store.DeleteReconciliationIntent(workCtx, intent.DocumentID)
		return
	}

	if errors.Is(err, pgx.ErrNoRows) {
		doc, getErr := r.store.Get(workCtx, intent.DocumentID)
		if getErr == nil && (doc.Status == "completed" || doc.Status == "failed") {
			_, _ = r.store.DeleteReconciliationIntent(workCtx, intent.DocumentID)
			return
		}
	}

	r.rescheduleIntent(workCtx, intent, err)
}

func (r *durableReconciler) rescheduleIntent(ctx context.Context, intent db.DocumentReconciliationIntent, cause error) {
	now := r.nowFunc()
	nextRetry := intent.RetryCount + 1
	backoffSec := 1 << min(nextRetry, 10)
	backoffDur := time.Duration(backoffSec) * time.Second
	if backoffDur > r.maxBackoff {
		backoffDur = r.maxBackoff
	}
	nextAttemptAt := now.Add(backoffDur)

	_, err := r.store.RescheduleReconciliationIntent(ctx, db.RescheduleReconciliationIntentParams{
		DocumentID:     intent.DocumentID,
		NextAttemptAt:  pgtype.Timestamp{Time: nextAttemptAt, Valid: true},
		LastErrorClass: pgtype.Text{String: "reconciliation_update_failed", Valid: true},
	})
	if err != nil {
		r.logger.Error("reschedule reconciliation intent", zap.String("document_id", intent.DocumentID), zap.Error(err), zap.Error(cause))
	}
}

func (a app) routes() http.Handler {
	r := chi.NewRouter()
	r.Group(func(r chi.Router) {
		r.Use(middleware.RequestID, middleware.RealIP, middleware.Recoverer)
		r.Post("/rag/query", a.queryRAG)
	})
	r.Group(func(r chi.Router) {
		r.Use(middleware.RequestID, middleware.RealIP, middleware.Recoverer, middleware.Timeout(60*time.Second))
		r.Get("/health", a.health)
		r.Post("/documents", a.createDocument)
		r.Get("/documents/{id}", a.getDocument)
	})
	return r
}

func (a app) health(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	latency, err := a.engine.Ping(ctx)
	if err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"status": "error", "engine": map[string]string{"status": "unreachable"}})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "engine": map[string]any{"status": "ok", "latency_ms": latency.Milliseconds()}})
}

func (a app) createDocument(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxUploadBytes+(1<<20))
	if err := r.ParseMultipartForm(maxUploadBytes); err != nil {
		http.Error(w, "multipart upload exceeds 10MB or is invalid", http.StatusRequestEntityTooLarge)
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		http.Error(w, "file field is required", http.StatusBadRequest)
		return
	}
	defer file.Close()
	if header.Size > maxUploadBytes {
		http.Error(w, "file exceeds 10MB", http.StatusRequestEntityTooLarge)
		return
	}

	strategy := "structure-aware"
	if reqStrategy := r.FormValue("chunk_strategy"); reqStrategy != "" {
		if reqStrategy != "structure-aware" && reqStrategy != "fixed-size" {
			http.Error(w, "invalid chunk_strategy", http.StatusBadRequest)
			return
		}
		strategy = reqStrategy
	}
	if strings.EqualFold(filepath.Ext(header.Filename), ".json") {
		strategy = "fixed-size"
	}

	chunkSize := defaultChunkSize
	if reqSize := r.FormValue("chunk_size"); reqSize != "" {
		parsedSize, err := strconv.ParseInt(reqSize, 10, 32)
		if err != nil || parsedSize <= 0 || parsedSize > maxChunkSize {
			http.Error(w, "invalid chunk_size", http.StatusBadRequest)
			return
		}
		chunkSize = int(parsedSize)
	}

	chunkOverlap := defaultChunkOverlap
	if reqOverlap := r.FormValue("chunk_overlap"); reqOverlap != "" {
		parsedOverlap, err := strconv.Atoi(reqOverlap)
		if err != nil || parsedOverlap < 0 {
			http.Error(w, "invalid chunk_overlap", http.StatusBadRequest)
			return
		}
		chunkOverlap = parsedOverlap
	}

	if chunkOverlap >= chunkSize {
		http.Error(w, "chunk_overlap must be smaller than chunk_size", http.StatusBadRequest)
		return
	}

	id, err := newDocumentID()
	if err != nil {
		http.Error(w, "could not allocate document id", http.StatusInternalServerError)
		return
	}
	doc, err := a.store.Insert(r.Context(), db.InsertDocumentParams{
		ID:            id,
		Filename:      filepath.Base(header.Filename),
		FileSize:      header.Size,
		ChunkStrategy: strategy,
		ChunkSize:     int32(chunkSize),
		ChunkOverlap:  int32(chunkOverlap),
	})
	if err != nil {
		a.logger.Error("insert document", zap.Error(err))
		http.Error(w, "could not queue document", http.StatusInternalServerError)
		return
	}
	outcome := a.engine.Ingest(r.Context(), id, doc.Filename, strategy, chunkSize, chunkOverlap, io.LimitReader(file, maxUploadBytes+1))
	if outcome.Err != nil {
		if outcome.Ambiguous {
			checkCtx, checkCancel := context.WithTimeout(context.Background(), 5*time.Second)
			statusResp, statusErr := a.engine.IngestionStatus(checkCtx, id)
			checkCancel()
			if statusErr == nil && statusResp.GetDocumentId() == id {
				st := statusResp.GetStatus()
				if st == "queued" || st == "processing" || st == "completed" || st == "failed" {
					w.Header().Set("Location", "/documents/"+doc.ID)
					writeJSON(w, http.StatusAccepted, doc)
					return
				}
			}
		}
		a.compensateFailedIngest(id, outcome.Err)
		if status.Code(outcome.Err) == codes.ResourceExhausted {
			http.Error(w, "ingestion queue is full", http.StatusTooManyRequests)
			return
		}
		http.Error(w, "engine ingestion failed", http.StatusBadGateway)
		return
	}
	w.Header().Set("Location", "/documents/"+doc.ID)
	writeJSON(w, http.StatusAccepted, doc)
}

func (a app) getDocument(w http.ResponseWriter, r *http.Request) {
	doc, err := a.store.Get(r.Context(), chi.URLParam(r, "id"))
	if errors.Is(err, pgx.ErrNoRows) {
		http.Error(w, "document not found", http.StatusNotFound)
		return
	}
	if err != nil {
		http.Error(w, "could not load document", http.StatusInternalServerError)
		return
	}
	if doc.Status == "queued" || doc.Status == "processing" {
		state, err := a.engine.IngestionStatus(r.Context(), doc.ID)
		if err != nil {
			if status.Code(err) == codes.NotFound {
				errText := pgtype.Text{String: "engine document not found", Valid: true}
				repairedDoc, updateErr := a.store.UpdateStatus(r.Context(), db.UpdateDocumentStatusParams{
					ID:           doc.ID,
					Status:       "failed",
					ChunkCount:   0,
					ErrorMessage: errText,
				})
				if errors.Is(updateErr, pgx.ErrNoRows) {
					winner, getErr := a.store.Get(r.Context(), doc.ID)
					if getErr == nil && (winner.Status == "completed" || winner.Status == "failed") {
						repairedDoc = winner
						updateErr = nil
					}
				}
				if updateErr == nil {
					writeJSON(w, http.StatusOK, repairedDoc)
					return
				}
			}
			http.Error(w, "could not poll ingestion status", http.StatusBadGateway)
			return
		}
		if state.GetDocumentId() != doc.ID {
			http.Error(w, "mismatched status document id", http.StatusBadGateway)
			return
		}
		if state.GetStatus() == "completed" || state.GetStatus() == "failed" {
			errText := pgtype.Text{String: state.GetErrorMessage(), Valid: state.GetErrorMessage() != ""}
			doc, err = a.store.UpdateStatus(r.Context(), db.UpdateDocumentStatusParams{ID: doc.ID, Status: state.GetStatus(), ChunkCount: state.GetChunkCount(), ErrorMessage: errText})
			if errors.Is(err, pgx.ErrNoRows) {
				winner, getErr := a.store.Get(r.Context(), doc.ID)
				if getErr == nil && (winner.Status == "completed" || winner.Status == "failed") {
					doc = winner
					err = nil
				} else if getErr != nil {
					err = getErr
				} else {
					err = errors.New("terminal status update lost without a terminal winner")
				}
			}
			if err != nil {
				http.Error(w, "could not update document status", http.StatusInternalServerError)
				return
			}
		}
	}
	writeJSON(w, http.StatusOK, doc)
}

type ragQueryRequestBody struct {
	Query     string `json:"query"`
	SessionID string `json:"session_id"`
	Filter    *struct {
		DocumentIDs  []string `json:"document_ids"`
		ContentTypes []string `json:"content_types"`
	} `json:"filter"`
	AllowModelOnly      *bool `json:"allow_model_only"`
	DisableGraphContext *bool `json:"disable_graph_context"`
}

func (a app) queryRAG(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, maxRAGQueryBodyBytes)
	defer r.Body.Close()

	var body ragQueryRequestBody
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(&body); err != nil {
		var maxErr *http.MaxBytesError
		if errors.As(err, &maxErr) {
			http.Error(w, "request body too large", http.StatusRequestEntityTooLarge)
			return
		}
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}
	if err := dec.Decode(&struct{}{}); err != io.EOF {
		var maxErr *http.MaxBytesError
		if errors.As(err, &maxErr) {
			http.Error(w, "request body too large", http.StatusRequestEntityTooLarge)
			return
		}
		http.Error(w, "invalid request body", http.StatusBadRequest)
		return
	}

	req := &pb.QueryRAGRequest{
		Query:               body.Query,
		SessionId:           body.SessionID,
		AllowModelOnly:      body.AllowModelOnly,
		DisableGraphContext: body.DisableGraphContext,
	}
	if body.Filter != nil {
		req.Filter = &pb.DocumentFilter{
			DocumentIds:  body.Filter.DocumentIDs,
			ContentTypes: body.Filter.ContentTypes,
		}
	}

	stream, err := a.engine.QueryRAG(r.Context(), req)
	if err != nil {
		a.handlePreStreamError(w, err)
		return
	}

	firstFrame, err := stream.Recv()
	if err != nil {
		a.handlePreStreamError(w, err)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	if sid := firstFrame.GetSessionId(); sid != "" {
		w.Header().Set("X-Lancet-Session-ID", sid)
	}
	if cid := firstFrame.GetTraceId(); cid != "" {
		w.Header().Set("X-Lancet-Correlation-ID", cid)
	}

	w.WriteHeader(http.StatusOK)

	rc := http.NewResponseController(w)
	var sawWorkflowCompleted bool
	if firstFrame.GetWorkflowCompleted() != nil {
		sawWorkflowCompleted = true
	}
	if r.Context().Err() == nil {
		a.writeWorkflowEvent(w, rc, firstFrame)
	}

	for {
		if r.Context().Err() != nil {
			return
		}
		ev, recvErr := stream.Recv()
		if errors.Is(recvErr, io.EOF) {
			if !sawWorkflowCompleted && r.Context().Err() == nil {
				sse.WriteStreamError(w, rc, sse.ErrCodeStreamEOFWithoutTerminal, "stream ended before workflow_completed")
			}
			return
		}
		if recvErr != nil {
			if r.Context().Err() == nil {
				sse.WriteStreamError(w, rc, sse.ErrCodeGRPCRecvError, recvErr.Error())
			}
			return
		}
		if r.Context().Err() != nil {
			return
		}
		if ev.GetWorkflowCompleted() != nil {
			sawWorkflowCompleted = true
		}
		a.writeWorkflowEvent(w, rc, ev)
	}
}

func (a app) writeWorkflowEvent(w http.ResponseWriter, rc *http.ResponseController, ev *pb.WorkflowEvent) {
	if ev == nil {
		return
	}

	if cp := ev.GetCheckpoint(); cp != nil {
		if a.dispatcher != nil {
			env := NewCheckpointEnvelopeFromEvent(ev)
			res := a.dispatcher.Submit(env)
			if res.Kind == DispatchPending && res.Envelope != nil {
				if err := a.dispatcher.RetainPending(res.Envelope); err != nil && a.logger != nil {
					a.logger.Error("retain pending checkpoint failed", zap.Error(err), zap.String("trace_id", env.TraceID))
				}
			}
		}
		return
	}

	sse.WriteWorkflowEvent(w, rc, ev)
}

func (a app) handlePreStreamError(w http.ResponseWriter, err error) {
	if te, ok := err.(interface{ Trailer() metadata.MD }); ok {
		tr := te.Trailer()
		if vals := tr.Get("x-lancet-session-id"); len(vals) > 0 && vals[0] != "" {
			w.Header().Set("X-Lancet-Session-ID", vals[0])
		}
		if vals := tr.Get("x-lancet-correlation-id"); len(vals) > 0 && vals[0] != "" {
			w.Header().Set("X-Lancet-Correlation-ID", vals[0])
		}
		if vals := tr.Get("x-lancet-error-kind"); len(vals) > 0 && vals[0] != "" {
			w.Header().Set("X-Lancet-Error-Kind", vals[0])
		}
	}

	if status.Code(err) == codes.InvalidArgument {
		http.Error(w, status.Convert(err).Message(), http.StatusBadRequest)
		return
	}
	http.Error(w, "engine query failed", http.StatusBadGateway)
}

func newDocumentID() (string, error) {
	id, err := uuid.NewRandom()
	if err != nil {
		return "", err
	}
	return id.String(), nil
}
func writeJSON(w http.ResponseWriter, code int, v any) {
	var buf bytes.Buffer
	if err := json.NewEncoder(&buf).Encode(v); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(`{"error":"internal server error"}`))
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_, _ = w.Write(buf.Bytes())
}

func formatListenAddr(port string) string {
	if strings.Contains(port, ":") {
		return port
	}
	return "127.0.0.1:" + port
}

func newHTTPServer(addr string, handler http.Handler) *http.Server {
	return &http.Server{
		Addr:              addr,
		Handler:           handler,
		ReadTimeout:       60 * time.Second,
		ReadHeaderTimeout: 10 * time.Second,
	}
}

func main() {
	if err := run(); err != nil {
		os.Exit(1)
	}
}

func run() error {
	logger, err := zap.NewDevelopment()
	if err != nil {
		return err
	}
	defer logger.Sync()
	cfg, err := config.Load()
	if err != nil {
		logger.Error("load configuration", zap.Error(err))
		return err
	}
	pool, err := pgxpool.New(context.Background(), cfg.Gateway.DatabaseURL)
	if err != nil {
		logger.Error("connect postgres", zap.Error(err))
		return err
	}
	defer pool.Close()
	conn, err := grpc.NewClient(cfg.Gateway.EngineAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		logger.Error("dial engine", zap.Error(err))
		return err
	}
	defer conn.Close()

	recCtx, recCancel := context.WithCancel(context.Background())
	defer recCancel()
	reconciler := newDurableReconciler(postgresStore{pool}, logger)
	go reconciler.Run(recCtx)

	sink := NewPostgresCheckpointSink(pool, logger)
	dispatcher := NewCheckpointDispatcherWithLogger(sink, logger)
	defer dispatcher.Close()

	server := newHTTPServer(
		formatListenAddr(cfg.Gateway.Port),
		app{
			store:      postgresStore{pool},
			engine:     engineclient.New(pb.NewLancetServiceClient(conn)),
			logger:     logger,
			dispatcher: dispatcher,
		}.routes(),
	)
	sigCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	serveErr := make(chan error, 1)
	go func() {
		if err := server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
			logger.Error("gateway stopped", zap.Error(err))
			serveErr <- err
		}
		close(serveErr)
	}()
	logger.Info("gateway listening", zap.String("addr", server.Addr))

	var fatal error
	select {
	case err, ok := <-serveErr:
		if ok && err != nil {
			fatal = err
		}
	case <-sigCtx.Done():
		logger.Info("gateway shutting down")
	}

	shutCtx, cancelShut := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancelShut()
	if err := server.Shutdown(shutCtx); err != nil {
		logger.Warn("gateway server shutdown error", zap.Error(err))
	}
	return fatal
}


