//! OpenTelemetry initialization, provider lifecycle, and subscriber composition.
//!
//! Provides the consolidated telemetry handle, OTLP provider builders,
//! install-free subscriber layer composition for tests, and the one process-global
//! subscriber installation for production (D-36, D-38, D-43).

pub mod metrics;
pub mod propagation;

use std::sync::Once;
use std::time::Duration;

use opentelemetry::propagation::TextMapCompositePropagator;
use opentelemetry::trace::TracerProvider as _;
use opentelemetry::KeyValue;
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::logs::{BatchLogProcessor, SdkLoggerProvider};
use opentelemetry_sdk::metrics::{PeriodicReader, SdkMeterProvider};
use opentelemetry_sdk::propagation::{BaggagePropagator, TraceContextPropagator};
use opentelemetry_sdk::trace::{Sampler, SdkTracerProvider};
use opentelemetry_sdk::Resource;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::Layer as _;
use tracing_subscriber::Registry;

use crate::config::TelemetryConfigSettings;

static INIT_PROPAGATOR: Once = Once::new();

/// Registers the global W3C trace-context and baggage composite propagator.
pub fn ensure_propagators() {
    INIT_PROPAGATOR.call_once(|| {
        let propagators: Vec<Box<dyn opentelemetry::propagation::TextMapPropagator + Send + Sync>> = vec![
            Box::new(TraceContextPropagator::new()),
            Box::new(BaggagePropagator::new()),
        ];
        opentelemetry::global::set_text_map_propagator(TextMapCompositePropagator::new(propagators));
    });
}

/// Builds the shared OpenTelemetry resource containing service and deployment metadata.
pub fn build_resource(settings: &TelemetryConfigSettings) -> Resource {
    Resource::builder()
        .with_service_name(settings.service_name.clone())
        .with_attributes([
            KeyValue::new("service.version", env!("CARGO_PKG_VERSION")),
            KeyValue::new("deployment.environment", settings.deployment_environment.clone()),
        ])
        .build()
}

/// Shared running cap for OpenTelemetry SDK internal diagnostics.
///
/// At `opentelemetry` 0.32 the SDK emits its own diagnostics as `tracing` events on
/// crate-named targets (`opentelemetry`, `opentelemetry_sdk`, `opentelemetry-otlp`);
/// `global::set_error_handler` no longer exists. Bounding therefore happens in the
/// subscriber, not in the SDK (D-38, G-06.2-4).
pub struct BoundedOtelDiagnostics {
    seen: std::sync::atomic::AtomicU64,
    limit: u64,
    window: std::time::Duration,
    window_start: std::sync::Mutex<Option<std::time::Instant>>,
}

impl BoundedOtelDiagnostics {
    pub fn new(limit: u64, window: std::time::Duration) -> Self {
        Self {
            seen: std::sync::atomic::AtomicU64::new(0),
            limit,
            window,
            window_start: std::sync::Mutex::new(None),
        }
    }

    /// Returns true when this event should reach the wrapped layer.
    ///
    /// Application targets always pass. OpenTelemetry construction/lifecycle chatter
    /// (TRACE/DEBUG/INFO) is dropped without consuming the cap. Only WARN/ERROR
    /// competes for the bounded slot. The slot re-arms after `window` (5 minutes).
    pub fn should_emit_at(&self, target: &str, level: &tracing::Level, now: std::time::Instant) -> bool {
        if !target.starts_with("opentelemetry") {
            return true;
        }
        if *level != tracing::Level::WARN && *level != tracing::Level::ERROR {
            return false;
        }

        let mut start_guard = self.window_start.lock().unwrap();
        match *start_guard {
            None => {
                *start_guard = Some(now);
                self.seen.store(0, std::sync::atomic::Ordering::Relaxed);
            }
            Some(start) => {
                if now.duration_since(start) >= self.window {
                    *start_guard = Some(now);
                    self.seen.store(0, std::sync::atomic::Ordering::Relaxed);
                }
            }
        }

        let seen = self.seen.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1;
        if seen == self.limit + 1 {
            eprintln!("WARNING: further OpenTelemetry export diagnostics suppressed for 5m (D-38)");
        }
        seen <= self.limit
    }
}

// Deliberately NOT Clone: nothing needs to clone this filter, `Filter<S>` does not
// require it, and deriving Clone would be the one remaining affordance for handing
// the counter to a second layer. Do not add a Clone derive.
pub struct OtelDiagnosticsFilter {
    state: std::sync::Arc<BoundedOtelDiagnostics>,
}

impl OtelDiagnosticsFilter {
    /// The ONLY way to build this filter. `engine/src/tests/telemetry_metrics.rs` is a
    /// sibling module, so it cannot name the private `state` field — a struct literal
    /// would not compile there. Keep the field private so no caller can smuggle a
    /// second reference to the counter into another layer.
    pub fn new(state: std::sync::Arc<BoundedOtelDiagnostics>) -> Self {
        Self { state }
    }
}

impl<S> tracing_subscriber::layer::Filter<S> for OtelDiagnosticsFilter {
    fn enabled(&self, meta: &tracing::Metadata<'_>, _cx: &tracing_subscriber::layer::Context<'_, S>) -> bool {
        self.state.should_emit_at(meta.target(), meta.level(), std::time::Instant::now())
    }
}

/// Stateless drop of all OpenTelemetry SDK internal diagnostics.
///
/// Applied to the appender bridge layer so SDK internal diagnostics never become
/// OTel log records. It holds NO counter: `Layered` evaluates the last-`.with()`'d
/// layer first, so a counting filter here would consume the fmt layer's cap before
/// the console ever saw the first export error.
#[derive(Clone, Copy)]
pub struct DropOtelDiagnosticsFilter;

impl<S> tracing_subscriber::layer::Filter<S> for DropOtelDiagnosticsFilter {
    fn enabled(&self, meta: &tracing::Metadata<'_>, _cx: &tracing_subscriber::layer::Context<'_, S>) -> bool {
        !meta.target().starts_with("opentelemetry")
    }
}

/// Holds active SDK signal providers for clean shutdown.
#[derive(Default)]
pub struct TelemetryHandle {
    pub tracer_provider: Option<SdkTracerProvider>,
    pub meter_provider: Option<SdkMeterProvider>,
    pub logger_provider: Option<SdkLoggerProvider>,
}

impl TelemetryHandle {
    /// Flushes and shuts down all active providers with bounded execution.
    pub fn shutdown(self) {
        if let Some(tp) = self.tracer_provider {
            let _ = tp.shutdown();
        }
        if let Some(mp) = self.meter_provider {
            let _ = mp.shutdown();
        }
        if let Some(lp) = self.logger_provider {
            let _ = lp.shutdown();
        }
    }
}

/// Builds telemetry providers and subscriber layers without installing anything globally.
///
/// This is the install-free seam used by tests with `tracing::subscriber::set_default`.
pub fn build_providers_and_layers(
    settings: &TelemetryConfigSettings,
) -> (TelemetryHandle, Box<dyn tracing::Subscriber + Send + Sync>) {
    ensure_propagators();
    let resource = build_resource(settings);

    let endpoint = settings.otlp_endpoint.trim();
    if endpoint.is_empty() {
        // Console-only mode: only fmt layer
        let fmt_layer = tracing_subscriber::fmt::layer();
        let subscriber = Registry::default().with(fmt_layer);
        return (TelemetryHandle::default(), Box::new(subscriber));
    }

    let sampler = if settings.sampler_ratio >= 1.0 {
        Sampler::AlwaysOn
    } else if settings.sampler_ratio <= 0.0 {
        Sampler::AlwaysOff
    } else {
        Sampler::TraceIdRatioBased(settings.sampler_ratio)
    };

    // Attempt to build OTLP span exporter
    let span_exporter_res = opentelemetry_otlp::SpanExporter::builder()
        .with_tonic()
        .with_endpoint(endpoint)
        .build();

    let tracer_provider = match span_exporter_res {
        Ok(exporter) => {
            let tp = SdkTracerProvider::builder()
                .with_resource(resource.clone())
                .with_sampler(sampler)
                .with_batch_exporter(exporter)
                .build();
            opentelemetry::global::set_tracer_provider(tp.clone());
            Some(tp)
        }
        Err(e) => {
            eprintln!("WARNING: Failed to initialize OTLP span exporter for {endpoint}: {e}");
            None
        }
    };

    // Attempt to build OTLP metric exporter
    let metric_exporter_res = opentelemetry_otlp::MetricExporter::builder()
        .with_tonic()
        .with_endpoint(endpoint)
        .build();

    let meter_provider = match metric_exporter_res {
        Ok(exporter) => {
            let reader = PeriodicReader::builder(exporter)
                .with_interval(Duration::from_secs(5))
                .build();
            let mp = SdkMeterProvider::builder()
                .with_resource(resource.clone())
                .with_reader(reader)
                .build();
            opentelemetry::global::set_meter_provider(mp.clone());
            Some(mp)
        }
        Err(e) => {
            eprintln!("WARNING: Failed to initialize OTLP metric exporter for {endpoint}: {e}");
            None
        }
    };

    // Attempt to build OTLP log exporter
    let log_exporter_res = opentelemetry_otlp::LogExporter::builder()
        .with_tonic()
        .with_endpoint(endpoint)
        .build();

    let logger_provider = match log_exporter_res {
        Ok(exporter) => {
            let processor = BatchLogProcessor::builder(exporter).build();
            let lp = SdkLoggerProvider::builder()
                .with_resource(resource)
                .with_log_processor(processor)
                .build();
            Some(lp)
        }
        Err(e) => {
            eprintln!("WARNING: Failed to initialize OTLP log exporter for {endpoint}: {e}");
            None
        }
    };

    let fmt_layer = tracing_subscriber::fmt::layer().with_filter(OtelDiagnosticsFilter::new(
        std::sync::Arc::new(BoundedOtelDiagnostics::new(1, std::time::Duration::from_secs(300))),
    ));

    let otel_trace_layer = tracer_provider.as_ref().map(|tp| {
        let tracer = tp.tracer(settings.service_name.clone());
        tracing_opentelemetry::layer().with_tracer(tracer)
    });

    let otel_log_layer = logger_provider.as_ref().map(|lp| {
        opentelemetry_appender_tracing::layer::OpenTelemetryTracingBridge::new(lp)
            .with_filter(DropOtelDiagnosticsFilter)
    });

    let subscriber = Registry::default()
        .with(fmt_layer)
        .with(otel_trace_layer)
        .with(otel_log_layer);

    (
        TelemetryHandle {
            tracer_provider,
            meter_provider,
            logger_provider,
        },
        Box::new(subscriber),
    )
}

/// Initializes OpenTelemetry and registers the one process-global tracing subscriber.
///
/// Must be called once during process startup after configuration is loaded.
pub fn init(settings: &TelemetryConfigSettings) -> TelemetryHandle {
    let (handle, subscriber) = build_providers_and_layers(settings);
    if let Err(e) = tracing::subscriber::set_global_default(subscriber) {
        eprintln!("WARNING: Failed to set global telemetry subscriber: {e}");
    }
    handle
}
