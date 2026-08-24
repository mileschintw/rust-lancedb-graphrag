// Package telemetry provides OpenTelemetry initialization, provider lifecycle,
// W3C propagation setup, and logging integration for the gateway service (D-36, D-38, D-43).
package telemetry

import (
	"context"
	"fmt"
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
)

var setupPropagatorOnce sync.Once

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

	cleanEndpoint := endpoint
	cleanEndpoint = strings.TrimPrefix(cleanEndpoint, "http://")
	cleanEndpoint = strings.TrimPrefix(cleanEndpoint, "https://")

	// Build trace exporter
	var spanExporter sdktrace.SpanExporter
	traceExp, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpoint(cleanEndpoint),
		otlptracegrpc.WithInsecure(),
	)
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
	metricExp, err := otlpmetricgrpc.New(ctx,
		otlpmetricgrpc.WithEndpoint(cleanEndpoint),
		otlpmetricgrpc.WithInsecure(),
	)
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
	logExp, err := otlploggrpc.New(ctx,
		otlploggrpc.WithEndpoint(cleanEndpoint),
		otlploggrpc.WithInsecure(),
	)
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
