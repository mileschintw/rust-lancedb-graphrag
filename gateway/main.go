package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/spf13/viper"
	"go.uber.org/zap"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"

	"github.com/lancet/gateway/db"
	pb "github.com/lancet/gateway/proto/lancet/v1"
)

const maxUploadBytes int64 = 10 << 20
const streamBufferSize = 64 << 10

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

type engine interface {
	Ingest(context.Context, string, string, io.Reader) error
	IngestionStatus(context.Context, string) (*pb.GetIngestionStatusResponse, error)
	Ping(context.Context) (time.Duration, error)
}

type grpcEngine struct{ client pb.LancetServiceClient }

func (e grpcEngine) Ingest(ctx context.Context, id, filename string, src io.Reader) error {
	stream, err := e.client.IngestDocument(ctx)
	if err != nil {
		return err
	}
	buf := make([]byte, streamBufferSize)
	for {
		n, readErr := src.Read(buf)
		if n > 0 {
			if err := stream.Send(&pb.IngestDocumentRequest{DocumentId: id, Filename: filename, ChunkData: append([]byte(nil), buf[:n]...)}); err != nil {
				return err
			}
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return readErr
		}
	}
	_, err = stream.CloseAndRecv()
	return err
}
func (e grpcEngine) IngestionStatus(ctx context.Context, id string) (*pb.GetIngestionStatusResponse, error) {
	return e.client.GetIngestionStatus(ctx, &pb.GetIngestionStatusRequest{DocumentId: id})
}
func (e grpcEngine) Ping(ctx context.Context) (time.Duration, error) {
	start := time.Now()
	_, err := e.client.Ping(ctx, &pb.PingRequest{Value: "ping"})
	return time.Since(start), err
}

type app struct {
	store  documentStore
	engine engine
	logger *zap.Logger
}

func (a app) routes() http.Handler {
	r := chi.NewRouter()
	r.Use(middleware.RequestID, middleware.RealIP, middleware.Recoverer, middleware.Timeout(60*time.Second))
	r.Get("/health", a.health)
	r.Post("/documents", a.createDocument)
	r.Get("/documents/{id}", a.getDocument)
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
	id, err := newDocumentID()
	if err != nil {
		http.Error(w, "could not allocate document id", http.StatusInternalServerError)
		return
	}
	doc, err := a.store.Insert(r.Context(), db.InsertDocumentParams{ID: id, Filename: filepath.Base(header.Filename), FileSize: header.Size, ChunkStrategy: "recursive", ChunkSize: 512, ChunkOverlap: 64})
	if err != nil {
		a.logger.Error("insert document", zap.Error(err))
		http.Error(w, "could not queue document", http.StatusInternalServerError)
		return
	}
	if err := a.engine.Ingest(r.Context(), id, doc.Filename, io.LimitReader(file, maxUploadBytes+1)); err != nil {
		if status.Code(err) == codes.ResourceExhausted {
			http.Error(w, "ingestion queue is full", http.StatusTooManyRequests)
			return
		}
		http.Error(w, "engine ingestion failed", http.StatusBadGateway)
		return
	}
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
	if doc.Status != "completed" && doc.Status != "failed" {
		state, err := a.engine.IngestionStatus(r.Context(), doc.ID)
		if err != nil {
			http.Error(w, "could not poll ingestion status", http.StatusBadGateway)
			return
		}
		errText := pgtype.Text{String: state.GetErrorMessage(), Valid: state.GetErrorMessage() != ""}
		doc, err = a.store.UpdateStatus(r.Context(), db.UpdateDocumentStatusParams{ID: doc.ID, Status: state.GetStatus(), ChunkCount: state.GetChunkCount(), ErrorMessage: errText})
		if err != nil {
			http.Error(w, "could not update document status", http.StatusInternalServerError)
			return
		}
	}
	writeJSON(w, http.StatusOK, doc)
}

func newDocumentID() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(b[:]), nil
}
func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
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
	server := &http.Server{Addr: fmt.Sprintf(":%s", cfg.Gateway.Port), Handler: app{store: postgresStore{pool}, engine: grpcEngine{pb.NewLancetServiceClient(conn)}, logger: logger}.routes(), ReadHeaderTimeout: 10 * time.Second}
	logger.Info("gateway listening", zap.String("addr", server.Addr))
	if err := server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		logger.Fatal("gateway stopped", zap.Error(err))
	}
}
