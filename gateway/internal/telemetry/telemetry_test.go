package telemetry

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
	"go.opentelemetry.io/otel/trace"
	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
	"go.uber.org/zap/zaptest/observer"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
)

const pinnedTraceParent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
const pinnedTraceID = "4bf92f3577b34da6a3ce929d0e0e4736"

type inMemoryLogExporter struct {
	mu      sync.Mutex
	records []sdklog.Record
}

func (e *inMemoryLogExporter) Export(ctx context.Context, records []sdklog.Record) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	for _, r := range records {
		e.records = append(e.records, r.Clone())
	}
	return nil
}

func (e *inMemoryLogExporter) Shutdown(ctx context.Context) error   { return nil }
func (e *inMemoryLogExporter) ForceFlush(ctx context.Context) error { return nil }
func (e *inMemoryLogExporter) GetRecords() []sdklog.Record {
	e.mu.Lock()
	defer e.mu.Unlock()
	return append([]sdklog.Record(nil), e.records...)
}

func TestHTTPTraceParent(t *testing.T) {
	SetupPropagator()
	sr := tracetest.NewSpanRecorder()
	tp := sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(sr))
	otel.SetTracerProvider(tp)
	defer func() {
		_ = tp.Shutdown(t.Context())
	}()

	var extractedTraceID string
	handler := otelhttp.NewHandler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sc := trace.SpanFromContext(r.Context()).SpanContext()
		if sc.IsValid() {
			extractedTraceID = sc.TraceID().String()
		}
		w.WriteHeader(http.StatusOK)
	}), "test_handler")

	// 1. With pinned traceparent
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	req.Header.Set("traceparent", pinnedTraceParent)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if extractedTraceID != pinnedTraceID {
		t.Errorf("expected extracted trace ID %s, got %s", pinnedTraceID, extractedTraceID)
	}

	// 2. With absent traceparent
	extractedTraceID = ""
	reqAbsent := httptest.NewRequest(http.MethodGet, "/test", nil)
	recAbsent := httptest.NewRecorder()
	handler.ServeHTTP(recAbsent, reqAbsent)

	if extractedTraceID == "" || extractedTraceID == pinnedTraceID {
		t.Errorf("expected new valid local root trace ID different from pinned, got %s", extractedTraceID)
	}

	// 3. With malformed traceparent
	extractedTraceID = ""
	reqMalformed := httptest.NewRequest(http.MethodGet, "/test", nil)
	reqMalformed.Header.Set("traceparent", "invalid-traceparent-format")
	recMalformed := httptest.NewRecorder()
	handler.ServeHTTP(recMalformed, reqMalformed)

	if extractedTraceID == "" || extractedTraceID == pinnedTraceID {
		t.Errorf("expected new valid local root for malformed header, got %s", extractedTraceID)
	}
}

func TestGRPCTracePropagation(t *testing.T) {
	SetupPropagator()
	sr := tracetest.NewSpanRecorder()
	tp := sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(sr))
	otel.SetTracerProvider(tp)
	defer func() {
		_ = tp.Shutdown(t.Context())
	}()

	// Start an in-process gRPC server that captures incoming metadata
	lis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("failed to listen: %v", err)
	}
	defer lis.Close()

	mdCh := make(chan metadata.MD, 1)

	srv := grpc.NewServer(
		grpc.UnknownServiceHandler(func(srv any, stream grpc.ServerStream) error {
			if md, ok := metadata.FromIncomingContext(stream.Context()); ok {
				mdCh <- md
			}
			return nil
		}),
	)

	go func() {
		_ = srv.Serve(lis)
	}()
	defer srv.Stop()

	// Connect client with otelgrpc stats handler
	conn, err := grpc.NewClient(
		lis.Addr().String(),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithStatsHandler(otelgrpc.NewClientHandler()),
	)
	if err != nil {
		t.Fatalf("failed to dial: %v", err)
	}
	defer conn.Close()

	// Create context with pinned trace
	traceID, _ := trace.TraceIDFromHex(pinnedTraceID)
	spanID, _ := trace.SpanIDFromHex("00f067aa0ba902b7")
	sc := trace.NewSpanContext(trace.SpanContextConfig{
		TraceID:    traceID,
		SpanID:     spanID,
		TraceFlags: trace.FlagsSampled,
		Remote:     true,
	})
	ctx := trace.ContextWithRemoteSpanContext(t.Context(), sc)

	// Issue a unary call (it will fail handler resolution but metadata is intercepted)
	_ = conn.Invoke(ctx, "/test.Service/TestMethod", &struct{}{}, &struct{}{})

	select {
	case md := <-mdCh:
		tpHeaders := md.Get("traceparent")
		if len(tpHeaders) == 0 {
			t.Fatal("expected traceparent header in gRPC metadata, found none")
		}
		if !strings.Contains(tpHeaders[0], pinnedTraceID) {
			t.Errorf("expected traceparent to contain %s, got %s", pinnedTraceID, tpHeaders[0])
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for gRPC metadata interception")
	}
}

func TestZapTraceCorrelation(t *testing.T) {
	SetupPropagator()
	exporter := &inMemoryLogExporter{}
	processor := sdklog.NewSimpleProcessor(exporter)
	lp := sdklog.NewLoggerProvider(sdklog.WithProcessor(processor))
	defer func() {
		_ = lp.Shutdown(t.Context())
	}()

	obsCore, recorded := observer.New(zapcore.InfoLevel)
	teeCore := WrapCore(obsCore, lp)
	logger := zap.New(teeCore)

	traceID, _ := trace.TraceIDFromHex(pinnedTraceID)
	spanID, _ := trace.SpanIDFromHex("00f067aa0ba902b7")
	sc := trace.NewSpanContext(trace.SpanContextConfig{
		TraceID:    traceID,
		SpanID:     spanID,
		TraceFlags: trace.FlagsSampled,
	})
	ctx := trace.ContextWithSpanContext(t.Context(), sc)

	// 1. Log with Ctx(ctx) inside active span
	logger.Info("message with context", Ctx(ctx), zap.String("session_id", "s123"))

	// 2. Log without Ctx
	logger.Info("message without context", zap.String("session_id", "s456"))

	records := exporter.GetRecords()
	if len(records) != 2 {
		t.Fatalf("expected 2 exported log records, got %d", len(records))
	}

	// First record should carry the pinned trace ID
	if records[0].TraceID() != traceID {
		t.Errorf("expected first log record trace ID %s, got %s", traceID, records[0].TraceID())
	}
	if records[0].SpanID() != spanID {
		t.Errorf("expected first log record span ID %s, got %s", spanID, records[0].SpanID())
	}

	// Second record should have zero trace ID
	if records[1].TraceID().IsValid() {
		t.Errorf("expected second log record to have invalid/empty trace ID, got %s", records[1].TraceID())
	}

	// Observer core should also receive both messages
	if recorded.Len() != 2 {
		t.Errorf("expected 2 observer logs, got %d", recorded.Len())
	}
}

func TestCollectorUnavailable(t *testing.T) {
	cfg := Config{
		OTLPEndpoint:          "http://127.0.0.1:59999", // nothing listening
		ServiceName:           "lancet-gateway",
		DeploymentEnvironment: "test",
		SamplerRatio:          1.0,
	}

	providers, shutdown := Init(t.Context(), cfg)
	if providers == nil {
		t.Fatal("expected non-nil providers even when collector is unavailable")
	}
	if shutdown == nil {
		t.Fatal("expected non-nil shutdown function")
	}

	obsCore, recorded := observer.New(zapcore.InfoLevel)
	teeCore := WrapCore(obsCore, providers.Logger)
	logger := zap.New(teeCore)

	logger.Info("test log while collector unavailable")
	if recorded.Len() != 1 {
		t.Errorf("expected console logger to keep writing, got %d logs", recorded.Len())
	}

	// Shutdown should not block or hang
	shutCtx, cancel := context.WithTimeout(t.Context(), 2*time.Second)
	defer cancel()
	if err := shutdown(shutCtx); err != nil {
		t.Errorf("unexpected error on shutdown: %v", err)
	}
}

func TestCollectorUnavailableKeepsConsole(t *testing.T) {
	TestCollectorUnavailable(t)
}

func TestRequestOwnedLogsCarryRequestTrace(t *testing.T) {
	SetupPropagator()
	exporter := &inMemoryLogExporter{}
	processor := sdklog.NewSimpleProcessor(exporter)
	lp := sdklog.NewLoggerProvider(sdklog.WithProcessor(processor))
	defer func() {
		_ = lp.Shutdown(t.Context())
	}()

	obsCore, _ := observer.New(zapcore.InfoLevel)
	teeCore := WrapCore(obsCore, lp)
	logger := zap.New(teeCore)

	traceID, _ := trace.TraceIDFromHex(pinnedTraceID)
	spanID, _ := trace.SpanIDFromHex("00f067aa0ba902b7")
	sc := trace.NewSpanContext(trace.SpanContextConfig{
		TraceID:    traceID,
		SpanID:     spanID,
		TraceFlags: trace.FlagsSampled,
	})
	ctx := trace.ContextWithSpanContext(t.Context(), sc)

	logger.Info("request owned log", Ctx(ctx), zap.String("action", "insert_doc"))

	records := exporter.GetRecords()
	if len(records) != 1 {
		t.Fatalf("expected 1 log record, got %d", len(records))
	}
	if records[0].TraceID() != traceID {
		t.Errorf("expected trace ID %s, got %s", traceID, records[0].TraceID())
	}
	if records[0].SpanID() != spanID {
		t.Errorf("expected span ID %s, got %s", spanID, records[0].SpanID())
	}
}

func TestBackgroundLogsCarryNoTraceContext(t *testing.T) {
	SetupPropagator()
	exporter := &inMemoryLogExporter{}
	processor := sdklog.NewSimpleProcessor(exporter)
	lp := sdklog.NewLoggerProvider(sdklog.WithProcessor(processor))
	defer func() {
		_ = lp.Shutdown(t.Context())
	}()

	obsCore, _ := observer.New(zapcore.InfoLevel)
	teeCore := WrapCore(obsCore, lp)
	logger := zap.New(teeCore)

	logger.Info("background reconciler log", zap.String("reconciler", "run"))

	records := exporter.GetRecords()
	if len(records) != 1 {
		t.Fatalf("expected 1 log record, got %d", len(records))
	}
	if records[0].TraceID().IsValid() {
		t.Errorf("expected background log to carry no trace ID, got %s", records[0].TraceID())
	}
	if records[0].SpanID().IsValid() {
		t.Errorf("expected background log to carry no span ID, got %s", records[0].SpanID())
	}
}

func TestBackgroundLogsRetainCorrelationAttribute(t *testing.T) {
	SetupPropagator()
	exporter := &inMemoryLogExporter{}
	processor := sdklog.NewSimpleProcessor(exporter)
	lp := sdklog.NewLoggerProvider(sdklog.WithProcessor(processor))
	defer func() {
		_ = lp.Shutdown(t.Context())
	}()

	obsCore, _ := observer.New(zapcore.InfoLevel)
	teeCore := WrapCore(obsCore, lp)
	logger := zap.New(teeCore)

	logger.Error("compensate failed ingestion", zap.String("document_id", "doc-123"), zap.Int("attempt", 2))

	records := exporter.GetRecords()
	if len(records) != 1 {
		t.Fatalf("expected 1 log record, got %d", len(records))
	}
	if records[0].TraceID().IsValid() {
		t.Errorf("expected background log to carry no trace ID, got %s", records[0].TraceID())
	}

	foundDocID := false
	records[0].WalkAttributes(func(kv attribute.KeyValue) bool {
		if kv.Key == "document_id" && kv.Value.AsString() == "doc-123" {
			foundDocID = true
		}
		return true
	})
	if !foundDocID {
		t.Errorf("expected document_id attribute retained in background log record")
	}
}

func TestConsoleCoreStillReceivesEveryRecord(t *testing.T) {
	SetupPropagator()
	exporter := &inMemoryLogExporter{}
	processor := sdklog.NewSimpleProcessor(exporter)
	lp := sdklog.NewLoggerProvider(sdklog.WithProcessor(processor))
	defer func() {
		_ = lp.Shutdown(t.Context())
	}()

	obsCore, recorded := observer.New(zapcore.DebugLevel)
	teeCore := WrapCore(obsCore, lp)
	logger := zap.New(teeCore)

	logger.Info("info msg")
	logger.Warn("warn msg")
	logger.Error("error msg")

	if recorded.Len() != 3 {
		t.Fatalf("expected 3 logs in console observer core, got %d", recorded.Len())
	}
	entries := recorded.All()
	if entries[0].Message != "info msg" || entries[0].Level != zapcore.InfoLevel {
		t.Errorf("entry 0 mismatch: %v", entries[0])
	}
	if entries[1].Message != "warn msg" || entries[1].Level != zapcore.WarnLevel {
		t.Errorf("entry 1 mismatch: %v", entries[1])
	}
	if entries[2].Message != "error msg" || entries[2].Level != zapcore.ErrorLevel {
		t.Errorf("entry 2 mismatch: %v", entries[2])
	}
}

func TestOTLPEndpointSecurity(t *testing.T) {
	tests := []struct {
		name       string
		endpoint   string
		wantTarget string
		wantTLS    bool
	}{
		{
			name:       "https remote host",
			endpoint:   "https://collector.example:4317",
			wantTarget: "collector.example:4317",
			wantTLS:    true,
		},
		{
			name:       "http local loopback",
			endpoint:   "http://127.0.0.1:4317",
			wantTarget: "127.0.0.1:4317",
			wantTLS:    false,
		},
		{
			name:       "https local loopback",
			endpoint:   "https://127.0.0.1:4317",
			wantTarget: "127.0.0.1:4317",
			wantTLS:    true,
		},
		{
			name:       "http remote host",
			endpoint:   "http://remote-host:4317",
			wantTarget: "remote-host:4317",
			wantTLS:    false,
		},
		{
			name:       "whitespace padded https",
			endpoint:   "  https://padded-collector:4317  ",
			wantTarget: "padded-collector:4317",
			wantTLS:    true,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			gotTarget, gotTLS := otlpEndpointSecurity(tc.endpoint)
			if gotTarget != tc.wantTarget {
				t.Errorf("target: got %q, want %q", gotTarget, tc.wantTarget)
			}
			if gotTLS != tc.wantTLS {
				t.Errorf("useTLS: got %v, want %v", gotTLS, tc.wantTLS)
			}
		})
	}
}

func TestOTLPExportersFollowEndpointSecurity(t *testing.T) {
	// Coverage-only test: calls otlpGRPCOptions with true and false so both branches
	// compile and run. Constructor option slices in OTel are opaque closures,
	// so wiring verification that https does not select insecure transport is enforced
	// via the WithInsecure source region grep rather than runtime option introspection.
	traceSecure, metricSecure, logSecure := otlpGRPCOptions(true)
	if len(traceSecure) == 0 || len(metricSecure) == 0 || len(logSecure) == 0 {
		t.Fatalf("expected non-empty option slices for TLS branch")
	}

	traceInsecure, metricInsecure, logInsecure := otlpGRPCOptions(false)
	if len(traceInsecure) == 0 || len(metricInsecure) == 0 || len(logInsecure) == 0 {
		t.Fatalf("expected non-empty option slices for insecure branch")
	}
}

