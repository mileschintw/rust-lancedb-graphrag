package main

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"go.uber.org/zap"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	pb "github.com/lancet/gateway/proto/lancet/v1"
)

type HealthResponse struct {
	Status string         `json:"status"`
	Engine EngineStatus   `json:"engine"`
}

type EngineStatus struct {
	Status    string `json:"status"`
	LatencyMs int64  `json:"latency_ms,omitempty"`
}

func main() {
	// Initialize Zap Logger
	logger, err := zap.NewDevelopment()
	if err != nil {
		panic(err)
	}
	defer logger.Sync()

	engineAddr := os.Getenv("ENGINE_ADDR")
	if engineAddr == "" {
		engineAddr = "localhost:50051"
	}

	logger.Info("Starting Go Gateway", zap.String("engine_addr", engineAddr))

	// Setup gRPC connection to Rust Engine
	conn, err := grpc.Dial(engineAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		logger.Fatal("Failed to dial gRPC engine", zap.Error(err))
	}
	defer conn.Close()

	client := pb.NewLancetServiceClient(conn)

	// Setup Chi HTTP Router
	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(60 * time.Second))

	// Health check endpoint
	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
		defer cancel()

		start := time.Now()
		resp, err := client.Ping(ctx, &pb.PingRequest{Value: "ping"})
		latency := time.Since(start).Milliseconds()

		w.Header().Set("Content-Type", "application/json")

		if err != nil {
			logger.Error("Engine ping failed", zap.Error(err))
			w.WriteHeader(http.StatusServiceUnavailable)
			json.NewEncoder(w).Encode(HealthResponse{
				Status: "error",
				Engine: EngineStatus{
					Status: "unreachable",
				},
			})
			return
		}

		logger.Info("Engine ping succeeded", zap.String("response", resp.GetValue()), zap.Int64("latency_ms", latency))
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(HealthResponse{
			Status: "ok",
			Engine: EngineStatus{
				Status:    "ok",
				LatencyMs: latency,
			},
		})
	})

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	logger.Info("Listening on HTTP port", zap.String("port", port))
	if err := http.ListenAndServe(":"+port, r); err != nil {
		logger.Fatal("HTTP server failed", zap.Error(err))
	}
}
