// Package telemetry provides OpenTelemetry initialization, provider lifecycle,
// W3C propagation setup, and logging integration for the gateway service (D-36, D-38, D-43).
package telemetry

import (
	"context"
	"fmt"
	"io"
	"os"
	"strings"
	"sync"
	"time"

	"go.opentelemetry.io/contrib/bridges/otelzap"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploggrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/log"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/propagation"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
	"go.opentelemetry.io/otel/trace"
	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
	"google.golang.org/grpc/credentials"
)

var (
	setupPropagatorOnce   sync.Once
	setupErrorHandlerOnce sync.Once
)

type boundedErrorHandler struct {
	sink        io.Writer
	limit       uint64
	window      time.Duration
	now         func() time.Time
	mu          sync.Mutex
	windowStart time.Time
	seen        uint64
}

var _ otel.ErrorHandler = (*boundedErrorHandler)(nil)

func newBoundedErrorHandler(w io.Writer, limit uint64, window time.Duration, now func() time.Time) *boundedErrorHandler {
	if now == nil {
		now = time.Now
	}
	return &boundedErrorHandler{
		sink:   w,
		limit:  limit,
		window: window,
		now:    now,
	}
}

func (h *boundedErrorHandler) Handle(err error) {
	h.mu.Lock()
	defer h.mu.Unlock()

	now := h.now()
	if h.windowStart.IsZero() || now.Sub(h.windowStart) >= h.window {
		h.seen = 0
		h.windowStart = now
	}

	h.seen++
	if h.seen <= h.limit {
		fmt.Fprintf(h.sink, "WARNING: OpenTelemetry export error: %v\n", err)
	} else if h.seen == h.limit+1 {
		fmt.Fprintf(h.sink, "WARNING: further OpenTelemetry export errors suppressed for 5m (D-38)\n")
	}
}

// SetupErrorHandler registers the bounded error handler for OpenTelemetry background exporters.
func SetupErrorHandler() {
	setupErrorHandlerOnce.Do(func() {
		otel.SetErrorHandler(newBoundedErrorHandler(os.Stderr, 1, 5*time.Minute, nil))
	})
}

// otlpEndpointSecurity parses the configured endpoint URL and extracts the gRPC target host:port
// along with a boolean indicating whether TLS transport credentials should be used (CR-04, D-84).
func otlpEndpointSecurity(endpoint string) (target string, useTLS bool) {
	trimmed := strings.TrimSpace(endpoint)
	if strings.HasPrefix(trimmed, "https://") {
		return strings.TrimPrefix(trimmed, "https://"), true
	}
	return strings.TrimPrefix(trimmed, "http://"), false
}

// otlpGRPCOptions constructs the gRPC exporter options for traces, metrics, and logs based on TLS requirement.
func otlpGRPCOptions(useTLS bool) (
	traceOpts []otlptracegrpc.Option,
	metricOpts []otlpmetricgrpc.Option,
	logOpts []otlploggrpc.Option,
) {
	if useTLS {
		tlsCreds := credentials.NewClientTLSFromCert(nil, "")
		return []otlptracegrpc.Option{otlptracegrpc.WithTLSCredentials(tlsCreds)},
			[]otlpmetricgrpc.Option{otlpmetricgrpc.WithTLSCredentials(tlsCreds)},
			[]otlploggrpc.Option{otlploggrpc.WithTLSCredentials(tlsCreds)}
	}
	return []otlptracegrpc.Option{otlptracegrpc.WithInsecure()},
		[]otlpmetricgrpc.Option{otlpmetricgrpc.WithInsecure()},
		[]otlploggrpc.Option{otlploggrpc.WithInsecure()}
}

// Config carries telemetry configuration parameters for the gateway.
type Config struct {
	OTLPEndpoint          string
	ServiceName           string
	DeploymentEnvironment string
	SamplerRatio          float64
}

// Providers holds the initialized signal providers.
type Providers struct {
	Tracer trace.TracerProvider
	Meter  metric.MeterProvider
	Logger log.LoggerProvider

	tp *sdktrace.TracerProvider
	mp *sdkmetric.MeterProvider
	lp *sdklog.LoggerProvider
}

// SetupPropagator registers the composite W3C trace-context and baggage propagator globally.
func SetupPropagator() {
	setupPropagatorOnce.Do(func() {
		otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
			propagation.TraceContext{},
			propagation.Baggage{},
		))
	})
}

// Init initializes OpenTelemetry providers.
// It never returns an error: if exporter construction fails, it emits a bounded warning
// and returns providers that do not export (D-38).
func Init(ctx context.Context, cfg Config) (*Providers, func(context.Context) error) {
	SetupErrorHandler()
	SetupPropagator()

	serviceName := cfg.ServiceName
	if strings.TrimSpace(serviceName) == "" {
		serviceName = "lancet-gateway"
	}
	deployEnv := cfg.DeploymentEnvironment
	if strings.TrimSpace(deployEnv) == "" {
		deployEnv = "dev"
	}

	res, _ := resource.Merge(
		resource.Default(),
		resource.NewWithAttributes(
			semconv.SchemaURL,
			semconv.ServiceName(serviceName),
			semconv.ServiceVersion("0.1.0"),
			semconv.DeploymentEnvironment(deployEnv),
		),
	)

	endpoint := strings.TrimSpace(cfg.OTLPEndpoint)
	if endpoint == "" {
		// Degrade to no-op / local providers with no exporters
		tp := sdktrace.NewTracerProvider(sdktrace.WithResource(res))
		mp := sdkmetric.NewMeterProvider(sdkmetric.WithResource(res))
		lp := sdklog.NewLoggerProvider(sdklog.WithResource(res))

		otel.SetTracerProvider(tp)
		otel.SetMeterProvider(mp)

		providers := &Providers{
			Tracer: tp,
			Meter:  mp,
			Logger: lp,
			tp:     tp,
			mp:     mp,
			lp:     lp,
		}

		shutdown := func(sCtx context.Context) error {
			_ = tp.Shutdown(sCtx)
			_ = mp.Shutdown(sCtx)
			_ = lp.Shutdown(sCtx)
			return nil
		}
		return providers, shutdown
	}

	cleanEndpoint, useTLS := otlpEndpointSecurity(endpoint)
	traceOpts, metricOpts, logOpts := otlpGRPCOptions(useTLS)

	// Build trace exporter
	var spanExporter sdktrace.SpanExporter
	allTraceOpts := append([]otlptracegrpc.Option{otlptracegrpc.WithEndpoint(cleanEndpoint)}, traceOpts...)
	traceExp, err := otlptracegrpc.New(ctx, allTraceOpts...)
	if err != nil {
		fmt.Fprintf(os.Stderr, "WARNING: Failed to initialize OTLP trace exporter for %s: %v\n", endpoint, err)
	} else {
		spanExporter = traceExp
	}

	// Sampler
	var sampler sdktrace.Sampler
	if cfg.SamplerRatio >= 1.0 {
		sampler = sdktrace.AlwaysSample()
	} else if cfg.SamplerRatio <= 0.0 {
		sampler = sdktrace.NeverSample()
	} else {
		sampler = sdktrace.ParentBased(sdktrace.TraceIDRatioBased(cfg.SamplerRatio))
	}

	var tpOpts []sdktrace.TracerProviderOption
	tpOpts = append(tpOpts, sdktrace.WithResource(res), sdktrace.WithSampler(sampler))
	if spanExporter != nil {
		tpOpts = append(tpOpts, sdktrace.WithBatcher(spanExporter))
	}
	tp := sdktrace.NewTracerProvider(tpOpts...)
	otel.SetTracerProvider(tp)

	// Build metric exporter
	var metricReader sdkmetric.Reader
	allMetricOpts := append([]otlpmetricgrpc.Option{otlpmetricgrpc.WithEndpoint(cleanEndpoint)}, metricOpts...)
	metricExp, err := otlpmetricgrpc.New(ctx, allMetricOpts...)
	if err != nil {
		fmt.Fprintf(os.Stderr, "WARNING: Failed to initialize OTLP metric exporter for %s: %v\n", endpoint, err)
	} else {
		metricReader = sdkmetric.NewPeriodicReader(metricExp, sdkmetric.WithInterval(5*time.Second))
	}

	var mpOpts []sdkmetric.Option
	mpOpts = append(mpOpts, sdkmetric.WithResource(res))
	if metricReader != nil {
		mpOpts = append(mpOpts, sdkmetric.WithReader(metricReader))
	}
	mp := sdkmetric.NewMeterProvider(mpOpts...)
	otel.SetMeterProvider(mp)

	// Build log exporter
	var logProcessor sdklog.Processor
	allLogOpts := append([]otlploggrpc.Option{otlploggrpc.WithEndpoint(cleanEndpoint)}, logOpts...)
	logExp, err := otlploggrpc.New(ctx, allLogOpts...)
	if err != nil {
		fmt.Fprintf(os.Stderr, "WARNING: Failed to initialize OTLP log exporter for %s: %v\n", endpoint, err)
	} else {
		logProcessor = sdklog.NewBatchProcessor(logExp)
	}

	var lpOpts []sdklog.LoggerProviderOption
	lpOpts = append(lpOpts, sdklog.WithResource(res))
	if logProcessor != nil {
		lpOpts = append(lpOpts, sdklog.WithProcessor(logProcessor))
	}
	lp := sdklog.NewLoggerProvider(lpOpts...)

	providers := &Providers{
		Tracer: tp,
		Meter:  mp,
		Logger: lp,
		tp:     tp,
		mp:     mp,
		lp:     lp,
	}

	shutdown := func(sCtx context.Context) error {
		_ = tp.Shutdown(sCtx)
		_ = mp.Shutdown(sCtx)
		_ = lp.Shutdown(sCtx)
		return nil
	}

	return providers, shutdown
}

// WrapCore returns a zapcore.Core that tees logs to the existing base core and otelzap core.
func WrapCore(base zapcore.Core, lp log.LoggerProvider) zapcore.Core {
	otelCore := otelzap.NewCore("github.com/lancet/gateway", otelzap.WithLoggerProvider(lp))
	return zapcore.NewTee(base, otelCore)
}

// Ctx returns the zap field recognized by otelzap to attach request context to log records.
func Ctx(ctx context.Context) zap.Field {
	return zap.Field{Key: "context", Type: zapcore.SkipType, Interface: ctx}
}

// Meter returns a Meter bound to the gateway's instrumentation scope.
func Meter() metric.Meter {
	return otel.GetMeterProvider().Meter("lancet-gateway")
}
