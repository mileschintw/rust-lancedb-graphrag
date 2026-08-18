package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/spf13/viper"
	"go.uber.org/zap"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"

	"github.com/lancet/gateway/db"
	pb "github.com/lancet/gateway/proto/lancet/v1"
)

const maxUploadBytes int64 = 10 << 20
const maxRAGQueryBodyBytes int64 = 32 << 10
const streamBufferSize = 64 << 10
const defaultChunkSize = 500
const defaultChunkOverlap = 50

// Authoritative Rust MAX_CHUNK_SIZE ceiling mirror
const maxChunkSize = 1048576

const ingestCompensationTimeout = 5 * time.Second

type Config struct {
	Gateway struct {
		Port        string `mapstructure:"port"`
		DatabaseURL string `mapstructure:"database_url"`
		EngineAddr  string `mapstructure:"engine_addr"`
	} `mapstructure:"gateway"`
}

func loadConfig() (Config, error) {
	v := viper.New()
	dir := os.Getenv("LANCET_CONFIG_DIR")
	if dir == "" {
		for _, candidate := range []string{"../config", "./config"} {
			if _, err := os.Stat(filepath.Join(candidate, "config.toml")); err == nil {
				dir = candidate
				break
			}
		}
	}
	v.SetConfigName("config")
	v.SetConfigType("toml")
	v.AddConfigPath(dir)
	v.SetEnvPrefix("LANCET")
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "__"))
	v.AutomaticEnv()
	if err := v.ReadInConfig(); err != nil {
		return Config{}, err
	}
	if environment := os.Getenv("LANCET_ENV"); environment != "" {
		v.SetConfigName("config." + environment)
		if err := v.MergeInConfig(); err != nil {
			return Config{}, err
		}
	}
	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

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

type IngestOutcome struct {
	Ambiguous bool
	Err       error
}

type engine interface {
	Ingest(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, src io.Reader) IngestOutcome
	IngestionStatus(context.Context, string) (*pb.GetIngestionStatusResponse, error)
	Ping(context.Context) (time.Duration, error)
	QueryRAG(context.Context, *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error)
}

type grpcEngine struct{ client pb.LancetServiceClient }

func (e grpcEngine) Ingest(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, src io.Reader) IngestOutcome {
	stream, err := e.client.IngestDocument(ctx)
	if err != nil {
		return IngestOutcome{Err: err}
	}
	buf := make([]byte, streamBufferSize)
	firstFrame := true
	for {
		n, readErr := src.Read(buf)
		if n > 0 {
			req := &pb.IngestDocumentRequest{
				DocumentId: id,
				ChunkData:  append([]byte(nil), buf[:n]...),
			}
			if firstFrame {
				firstFrame = false
				req.Filename = filename
				req.Metadata = map[string]string{
					"chunk_strategy": strategy,
					"chunk_size":     strconv.Itoa(chunkSize),
					"chunk_overlap":  strconv.Itoa(chunkOverlap),
				}
			}
			if err := stream.Send(req); err != nil {
				return IngestOutcome{Err: err}
			}
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return IngestOutcome{Err: readErr}
		}
	}
	resp, err := stream.CloseAndRecv()
	if err != nil {
		return IngestOutcome{Ambiguous: true, Err: err}
	}
	if !resp.GetSuccess() || resp.GetDocumentId() != id {
		return IngestOutcome{Err: fmt.Errorf("ingest rejected: success=%v, document_id=%q", resp.GetSuccess(), resp.GetDocumentId())}
	}
	return IngestOutcome{}
}
func (e grpcEngine) IngestionStatus(ctx context.Context, id string) (*pb.GetIngestionStatusResponse, error) {
	return e.client.GetIngestionStatus(ctx, &pb.GetIngestionStatusRequest{DocumentId: id})
}
func (e grpcEngine) Ping(ctx context.Context) (time.Duration, error) {
	start := time.Now()
	_, err := e.client.Ping(ctx, &pb.PingRequest{Value: "ping"})
	return time.Since(start), err
}
type trailerError struct {
	err     error
	trailer metadata.MD
}

func (e trailerError) Error() string {
	return e.err.Error()
}

func (e trailerError) GRPCStatus() *status.Status {
	return status.Convert(e.err)
}

func (e trailerError) Trailer() metadata.MD {
	return e.trailer
}

func (e grpcEngine) QueryRAG(ctx context.Context, req *pb.QueryRAGRequest) (pb.LancetService_QueryRAGClient, error) {
	var trailer metadata.MD
	stream, err := e.client.QueryRAG(ctx, req, grpc.Trailer(&trailer))
	if err != nil {
		return nil, trailerError{err: err, trailer: trailer}
	}
	return stream, nil
}

type app struct {
	store      documentStore
	engine     engine
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
		Query:     body.Query,
		SessionId: body.SessionID,
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
		a.writeWorkflowEventSSE(w, rc, firstFrame)
	}

	for {
		if r.Context().Err() != nil {
			return
		}
		ev, recvErr := stream.Recv()
		if errors.Is(recvErr, io.EOF) {
			if !sawWorkflowCompleted && r.Context().Err() == nil {
				a.writeStreamErrorSSE(w, rc, "STREAM_EOF_WITHOUT_TERMINAL", "stream ended before workflow_completed")
			}
			return
		}
		if recvErr != nil {
			if r.Context().Err() == nil {
				a.writeStreamErrorSSE(w, rc, "GRPC_RECV_ERROR", recvErr.Error())
			}
			return
		}
		if r.Context().Err() != nil {
			return
		}
		if ev.GetWorkflowCompleted() != nil {
			sawWorkflowCompleted = true
		}
		a.writeWorkflowEventSSE(w, rc, ev)
	}
}

func (a app) writeStreamErrorSSE(w http.ResponseWriter, rc *http.ResponseController, code, message string) {
	payload := map[string]any{
		"code":    code,
		"message": message,
	}
	dataBytes, err := json.Marshal(payload)
	if err != nil {
		return
	}
	fmt.Fprintf(w, "event: stream_error\ndata: %s\n\n", dataBytes)
	_ = rc.Flush()
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

func (a app) writeWorkflowEventSSE(w http.ResponseWriter, rc *http.ResponseController, ev *pb.WorkflowEvent) {
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

	var eventType string
	var payload any

	switch e := ev.Event.(type) {
	case *pb.WorkflowEvent_NodeStarted:
		eventType = "node_started"
		payload = map[string]any{
			"node_name":        e.NodeStarted.GetNodeName(),
			"inputs_summary":   e.NodeStarted.GetInputsSummary(),
			"sequence_ordinal": ev.GetSequenceOrdinal(),
		}
	case *pb.WorkflowEvent_NodeCompleted:
		eventType = "node_completed"
		payload = map[string]any{
			"node_name":       e.NodeCompleted.GetNodeName(),
			"outputs_summary": e.NodeCompleted.GetOutputsSummary(),
			"duration_ms":     e.NodeCompleted.GetDurationMs(),
		}
	case *pb.WorkflowEvent_NodeFailed:
		eventType = "node_failed"
		payload = map[string]any{
			"node_name":     e.NodeFailed.GetNodeName(),
			"error_kind":    int32(e.NodeFailed.GetCategory()),
			"error_message": e.NodeFailed.GetMessage(),
			"retryable":     e.NodeFailed.GetRetryable(),
		}
	case *pb.WorkflowEvent_AnswerChunk:
		eventType = "answer_chunk"
		payload = map[string]any{
			"chunk_text": e.AnswerChunk.GetChunk(),
			"is_final":   e.AnswerChunk.GetIsFinal(),
		}
	case *pb.WorkflowEvent_FinalAnswer:
		eventType = "final_answer"
		payload = toQueryRAGResponseDTO(e.FinalAnswer.GetResponse())
	case *pb.WorkflowEvent_WorkflowCompleted:
		eventType = "workflow_completed"
		wcPayload := map[string]any{
			"success":           e.WorkflowCompleted.GetSuccess(),
			"total_duration_ms": e.WorkflowCompleted.GetDurationMs(),
			"error_kind":        int32(e.WorkflowCompleted.GetErrorKind()),
			"error_message":     e.WorkflowCompleted.GetErrorMessage(),
		}
		if e.WorkflowCompleted.GetFinalResponse() != nil {
			wcPayload["final_response"] = toQueryRAGResponseDTO(e.WorkflowCompleted.GetFinalResponse())
		} else {
			notices := make([]noticeDTO, 0, len(e.WorkflowCompleted.GetNotices()))
			for _, n := range e.WorkflowCompleted.GetNotices() {
				if n == nil {
					continue
				}
				notices = append(notices, noticeDTO{
					Code:     n.Code,
					Message:  n.Message,
					Severity: int32(n.Severity),
				})
			}
			wcPayload["notices"] = notices
		}
		payload = wcPayload
	default:
		return
	}

	dataBytes, err := json.Marshal(payload)
	if err != nil {
		return
	}

	fmt.Fprintf(w, "event: %s\ndata: %s\n\n", eventType, dataBytes)
	_ = rc.Flush()
}

type queryRAGResponseDTO struct {
	Answer              string                   `json:"answer"`
	Citations           []string                 `json:"citations"`
	SessionID           string                   `json:"session_id"`
	AnswerBasis         int32                    `json:"answer_basis"`
	StructuredCitations []structuredCitationDTO  `json:"structured_citations"`
	Notices             []noticeDTO              `json:"notices"`
	Snapshot            *retrievalSnapshotDTO    `json:"snapshot"`
}

type structuredCitationDTO struct {
	ChunkID      string  `json:"chunk_id"`
	DocumentID   string  `json:"document_id"`
	Title        string  `json:"title"`
	SectionPath  string  `json:"section_path"`
	Excerpt      string  `json:"excerpt"`
	IsTruncated  bool    `json:"is_truncated"`
	Score        float64 `json:"score"`
	Rank         int32   `json:"rank"`
	ContentType  string  `json:"content_type"`
}

type noticeDTO struct {
	Code     string `json:"code"`
	Message  string `json:"message"`
	Severity int32  `json:"severity"`
}

type documentFilterDTO struct {
	DocumentIDs  []string `json:"document_ids"`
	ContentTypes []string `json:"content_types"`
}

type retrievalSnapshotDTO struct {
	IndexGeneration string             `json:"index_generation"`
	EmbeddingModel  string             `json:"embedding_model"`
	VectorWeight    float64            `json:"vector_weight"`
	Bm25Weight      float64            `json:"bm25_weight"`
	RrfK            int32              `json:"rrf_k"`
	CandidateLimit  int32              `json:"candidate_limit"`
	FinalLimit      int32              `json:"final_limit"`
	ActiveFilter    *documentFilterDTO `json:"active_filter"`
	ResultHash      string             `json:"result_hash"`
}

func toQueryRAGResponseDTO(resp *pb.QueryRAGResponse) queryRAGResponseDTO {
	if resp == nil {
		return queryRAGResponseDTO{
			Citations:           make([]string, 0),
			StructuredCitations: make([]structuredCitationDTO, 0),
			Notices:             make([]noticeDTO, 0),
		}
	}
	citations := make([]string, 0)
	if len(resp.Citations) > 0 {
		citations = resp.Citations
	}

	structuredCitations := make([]structuredCitationDTO, 0)
	for _, sc := range resp.StructuredCitations {
		if sc == nil {
			continue
		}
		structuredCitations = append(structuredCitations, structuredCitationDTO{
			ChunkID:     sc.ChunkId,
			DocumentID:  sc.DocumentId,
			Title:       sc.Title,
			SectionPath: sc.SectionPath,
			Excerpt:     sc.Excerpt,
			IsTruncated: sc.IsTruncated,
			Score:       sc.Score,
			Rank:        sc.Rank,
			ContentType: sc.ContentType,
		})
	}

	notices := make([]noticeDTO, 0)
	for _, n := range resp.Notices {
		if n == nil {
			continue
		}
		notices = append(notices, noticeDTO{
			Code:     n.Code,
			Message:  n.Message,
			Severity: int32(n.Severity),
		})
	}

	var snapshot *retrievalSnapshotDTO
	if resp.Snapshot != nil {
		var activeFilter *documentFilterDTO
		if resp.Snapshot.ActiveFilter != nil {
			docIDs := make([]string, 0)
			if len(resp.Snapshot.ActiveFilter.DocumentIds) > 0 {
				docIDs = resp.Snapshot.ActiveFilter.DocumentIds
			}
			contentTypes := make([]string, 0)
			if len(resp.Snapshot.ActiveFilter.ContentTypes) > 0 {
				contentTypes = resp.Snapshot.ActiveFilter.ContentTypes
			}
			activeFilter = &documentFilterDTO{
				DocumentIDs:  docIDs,
				ContentTypes: contentTypes,
			}
		}
		snapshot = &retrievalSnapshotDTO{
			IndexGeneration: resp.Snapshot.IndexGeneration,
			EmbeddingModel:  resp.Snapshot.EmbeddingModel,
			VectorWeight:    resp.Snapshot.VectorWeight,
			Bm25Weight:      resp.Snapshot.Bm25Weight,
			RrfK:            resp.Snapshot.RrfK,
			CandidateLimit:  resp.Snapshot.CandidateLimit,
			FinalLimit:      resp.Snapshot.FinalLimit,
			ActiveFilter:    activeFilter,
			ResultHash:      resp.Snapshot.ResultHash,
		}
	}

	return queryRAGResponseDTO{
		Answer:              resp.Answer,
		Citations:           citations,
		SessionID:           resp.SessionId,
		AnswerBasis:         int32(resp.AnswerBasis),
		StructuredCitations: structuredCitations,
		Notices:             notices,
		Snapshot:            snapshot,
	}
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
	logger, err := zap.NewDevelopment()
	if err != nil {
		panic(err)
	}
	defer logger.Sync()
	cfg, err := loadConfig()
	if err != nil {
		logger.Fatal("load configuration", zap.Error(err))
	}
	pool, err := pgxpool.New(context.Background(), cfg.Gateway.DatabaseURL)
	if err != nil {
		logger.Fatal("connect postgres", zap.Error(err))
	}
	defer pool.Close()
	conn, err := grpc.NewClient(cfg.Gateway.EngineAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		logger.Fatal("dial engine", zap.Error(err))
	}
	defer conn.Close()

	recCtx, recCancel := context.WithCancel(context.Background())
	defer recCancel()
	reconciler := newDurableReconciler(postgresStore{pool}, logger)
	go reconciler.Run(recCtx)

	sink := NewPostgresCheckpointSink(pool, logger)
	dispatcher := NewCheckpointDispatcher(sink)
	defer dispatcher.Close()

	server := newHTTPServer(
		formatListenAddr(cfg.Gateway.Port),
		app{
			store:      postgresStore{pool},
			engine:     grpcEngine{pb.NewLancetServiceClient(conn)},
			logger:     logger,
			dispatcher: dispatcher,
		}.routes(),
	)
	logger.Info("gateway listening", zap.String("addr", server.Addr))
	if err := server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		logger.Fatal("gateway stopped", zap.Error(err))
	}
}


