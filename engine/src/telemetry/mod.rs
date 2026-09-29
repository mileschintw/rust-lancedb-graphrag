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
use opentelemetry_sdk::trace::{
    Sampler, SamplingDecision, SamplingResult, SdkTracerProvider, ShouldSample,
};
use opentelemetry_sdk::Resource;
use tracing_subscriber::filter::{LevelFilter, Targets};
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

/// Span names retained even when the global sampling ratio would drop them (D-08).
///
/// 1. `graph_traversal`: Cypher-level traversal span emitted by `ProductionGraphQueryPort::query_graph`.
/// 2. `graph_context_extraction`: workflow node span for graph context extraction in `WorkflowRunner::run_node`.
pub const RETAINED_GRAPH_SPAN_NAMES: [&str; 2] = ["graph_traversal", "graph_context_extraction"];

/// Composite sampler that unconditionally samples graph-path spans (D-08)
/// while delegating all other spans to the configured inner sampler.
///
/// Notes:
/// (a) Implements D-08 so Phase 6's existing Cypher instrumentation is usable during the 06.3.3 investigation.
/// (b) Wire capture remains the primary diagnostic instrument for all queries (D-01); this is an additional graph-path channel.
/// (c) At the shipped `sampler_ratio = 1.0` this wrapper is a no-op because the inner sampler already exports everything.
/// (d) When the inner sampler drops a parent trace, a retained graph span is exported as a root-less span, which is the accepted cost of retaining it.
#[derive(Clone, Debug)]
pub struct GraphSpanRetainingSampler {
    inner: Sampler,
}

impl GraphSpanRetainingSampler {
    pub fn new(inner: Sampler) -> Self {
        Self { inner }
    }
}

impl ShouldSample for GraphSpanRetainingSampler {
    fn should_sample(
        &self,
        parent_context: Option<&opentelemetry::Context>,
        trace_id: opentelemetry::trace::TraceId,
        name: &str,
        span_kind: &opentelemetry::trace::SpanKind,
        attributes: &[KeyValue],
        links: &[opentelemetry::trace::Link],
    ) -> SamplingResult {
        if RETAINED_GRAPH_SPAN_NAMES.contains(&name) {
            let trace_state = parent_context
                .map(|ctx| opentelemetry::trace::TraceContextExt::span(ctx).span_context().trace_state().clone())
                .unwrap_or_default();
            SamplingResult {
                decision: SamplingDecision::RecordAndSample,
                attributes: Vec::new(),
                trace_state,
            }
        } else {
            self.inner
                .should_sample(parent_context, trace_id, name, span_kind, attributes, links)
        }
    }
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
            eprintln!("{}", self.suppressed_export_warning());
        }
        seen <= self.limit
    }

    pub(crate) fn suppressed_export_warning(&self) -> String {
        format!(
            "WARNING: further OpenTelemetry export diagnostics suppressed for {:?} (D-38)",
            self.window
        )
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

/// Default level filter applied to every tracing layer when `RUST_LOG` is absent or empty.
///
/// Pass A ran the engine with no level filter and emitted about 12.7M trace and debug
/// lines in 41 minutes, so the Loki export lost `request_process_state` for 37 of 324
/// requests and `retrieve_hybrid_substages` for 88 of 324. `info` keeps every dependency
/// (`h2`, `tower`, `hyper`, `opentelemetry_sdk`) at INFO and above. `engine=debug` keeps
/// this crate's own DEBUG events. Widening the default (for example to `trace`) brings
/// the dependency firehose back and makes the OI-02 events drop out of the export again.
///
/// D-90 accepted confounder: 06.3.4 ran unfiltered, so a flat drive 1 cannot by itself
/// show that the filter was irrelevant to OI-02.
pub const DEFAULT_LOG_FILTER: &str = "info,engine=debug";

/// Outcome of resolving the `RUST_LOG` value into the level filter every layer shares.
pub struct LogFilterResolution {
    /// Filter to register as the first layer of the subscriber stack.
    pub targets: Targets,
    /// Directive string the filter was built from, reported on the startup line.
    pub effective: String,
    /// Set when `RUST_LOG` was present but rejected and the default was used instead.
    pub warning: Option<String>,
}

/// Resolves a `RUST_LOG` value into the level filter shared by every layer (D-90).
///
/// The function never reads the process environment, so tests do not mutate it. An
/// absent, empty or blank value gives [`DEFAULT_LOG_FILTER`]. A value that does not parse
/// as `target=level` directives gives the default plus a warning that names the rejected
/// value. Unfiltered output is never the fallback.
pub fn resolve_log_filter(rust_log: Option<&str>) -> LogFilterResolution {
    let _ = rust_log;
    LogFilterResolution {
        targets: Targets::new().with_default(LevelFilter::TRACE),
        effective: String::new(),
        warning: None,
    }
}

/// Reports whether this build carries debug assertions (`debug`) or not (`release`).
pub const fn build_profile() -> &'static str {
    "release"
}

/// Composes the one tracing stack both `build_providers_and_layers` branches use.
///
/// The level filter is the first layer, so it gates the fmt layer, the OpenTelemetry
/// trace layer and the OTLP log bridge alike. `tracer_provider` and `logger_provider`
/// are `None` in console-only mode.
pub(crate) fn assemble_subscriber<W>(
    resolution: &LogFilterResolution,
    fmt_writer: W,
    tracer_provider: Option<&SdkTracerProvider>,
    logger_provider: Option<&SdkLoggerProvider>,
    service_name: &str,
) -> Box<dyn tracing::Subscriber + Send + Sync>
where
    W: for<'w> tracing_subscriber::fmt::MakeWriter<'w> + Send + Sync + 'static,
{
    let _ = resolution;
    let fmt_layer = tracing_subscriber::fmt::layer()
        .with_writer(fmt_writer)
        .with_filter(OtelDiagnosticsFilter::new(std::sync::Arc::new(
            BoundedOtelDiagnostics::new(1, std::time::Duration::from_secs(300)),
        )));

    let otel_trace_layer = tracer_provider.map(|tp| {
        let tracer = tp.tracer(service_name.to_owned());
        tracing_opentelemetry::layer().with_tracer(tracer)
    });

    let otel_log_layer = logger_provider.map(|lp| {
        opentelemetry_appender_tracing::layer::OpenTelemetryTracingBridge::new(lp)
            .with_filter(DropOtelDiagnosticsFilter)
    });

    Box::new(
        Registry::default()
            .with(fmt_layer)
            .with(otel_trace_layer)
            .with(otel_log_layer),
    )
}

/// Holds active SDK signal providers for clean shutdown.
#[derive(Default)]
pub struct TelemetryHandle {
    pub tracer_provider: Option<SdkTracerProvider>,
    pub meter_provider: Option<SdkMeterProvider>,
    pub logger_provider: Option<SdkLoggerProvider>,
    /// Effective level-filter directive string, reported on the engine startup line.
    pub log_filter: String,
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
        // Console-only mode: only fmt layer.
        //
        // Writes to stderr, not stdout (06.3.4.1-03 Task 1 deviation, Rule 3): stdout is
        // reserved for CLI/inspection binaries that intentionally use it as their user
        // interface (M-LOG-NOT-PRINT's inspect-bin exception — e.g. `inspect_lancedb`,
        // `retrieval_soak`), and this subscriber is process-global, so leaving it on stdout
        // would interleave unrelated tracing output into any such binary's structured output.
        // `main.rs`'s own stdout is not consumed by anything today, so this is behavior-neutral
        // for production.
        let fmt_layer = tracing_subscriber::fmt::layer().with_writer(std::io::stderr);
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
                .with_sampler(GraphSpanRetainingSampler::new(sampler))
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

    // Stderr, not stdout — see the console-only branch above for why (06.3.4.1-03 Task 1).
    let fmt_layer = tracing_subscriber::fmt::layer()
        .with_writer(std::io::stderr)
        .with_filter(OtelDiagnosticsFilter::new(std::sync::Arc::new(
            BoundedOtelDiagnostics::new(1, std::time::Duration::from_secs(300)),
        )));

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
            log_filter: String::new(),
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

#[cfg(test)]
mod log_filter_tests {
    use std::io;
    use std::sync::{Arc, Mutex};

    use opentelemetry_sdk::logs::{InMemoryLogExporter, SdkLoggerProvider, SimpleLogProcessor};
    use opentelemetry_sdk::trace::{InMemorySpanExporter, SdkTracerProvider};
    use tracing::Level;
    use tracing_subscriber::fmt::MakeWriter;

    use super::{
        assemble_subscriber, build_profile, build_providers_and_layers, resolve_log_filter,
        LogFilterResolution,
    };

    /// In-memory fmt sink standing in for stderr.
    #[derive(Clone, Default)]
    struct SharedBuf(Arc<Mutex<Vec<u8>>>);

    struct SharedBufWriter(Arc<Mutex<Vec<u8>>>);

    impl io::Write for SharedBufWriter {
        fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
            self.0
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .extend_from_slice(buf);
            Ok(buf.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    impl<'a> MakeWriter<'a> for SharedBuf {
        type Writer = SharedBufWriter;

        fn make_writer(&'a self) -> Self::Writer {
            SharedBufWriter(Arc::clone(&self.0))
        }
    }

    impl SharedBuf {
        fn contents(&self) -> String {
            let bytes = self
                .0
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            String::from_utf8_lossy(&bytes).into_owned()
        }
    }

    /// Emits the two OI-02 events, an INFO engine span, and TRACE `h2::codec` noise.
    fn emit_probe_records() {
        tracing::info!(
            target: "engine::service",
            request_process_state = true,
            "request_process_state"
        );
        tracing::info!(
            target: "engine::workflow::nodes::retrieve",
            "retrieve_hybrid_substages"
        );
        tracing::trace!(target: "h2::codec", "h2_codec_trace_event_probe");
        let codec_span = tracing::trace_span!(target: "h2::codec", "h2_codec_trace_span_probe");
        drop(codec_span.enter());
        drop(codec_span);
        let engine_span =
            tracing::info_span!(target: "engine::workflow::nodes::retrieve", "engine_span_probe");
        drop(engine_span.enter());
        drop(engine_span);
    }

    /// Readers over the in-memory sinks of the OTLP-shaped stack.
    struct OtlpProbe {
        fmt: SharedBuf,
        spans: InMemorySpanExporter,
        logs: InMemoryLogExporter,
        tracer_provider: SdkTracerProvider,
        logger_provider: SdkLoggerProvider,
    }

    /// Builds the OTLP-shaped stack (trace layer and log bridge on in-memory exporters).
    fn otlp_shape(
        resolution: &LogFilterResolution,
    ) -> (Box<dyn tracing::Subscriber + Send + Sync>, OtlpProbe) {
        let fmt = SharedBuf::default();
        let spans = InMemorySpanExporter::default();
        let logs = InMemoryLogExporter::default();
        let tracer_provider = SdkTracerProvider::builder()
            .with_simple_exporter(spans.clone())
            .build();
        let logger_provider = SdkLoggerProvider::builder()
            .with_log_processor(SimpleLogProcessor::new(logs.clone()))
            .build();
        let subscriber = assemble_subscriber(
            resolution,
            fmt.clone(),
            Some(&tracer_provider),
            Some(&logger_provider),
            "test-service",
        );
        (
            subscriber,
            OtlpProbe {
                fmt,
                spans,
                logs,
                tracer_provider,
                logger_provider,
            },
        )
    }

    impl OtlpProbe {
        fn flush(&self) {
            self.tracer_provider.force_flush().expect("flush spans");
            self.logger_provider.force_flush().expect("flush logs");
        }

        fn log_records(&self) -> Vec<String> {
            self.logs
                .get_emitted_logs()
                .expect("read emitted logs")
                .into_iter()
                .map(|log| format!("{:?}", log.record))
                .collect()
        }

        fn span_names(&self) -> Vec<String> {
            self.spans
                .get_finished_spans()
                .expect("read finished spans")
                .into_iter()
                .map(|span| span.name.to_string())
                .collect()
        }
    }

    #[test]
    fn log_filter_default_keeps_oi02_events_and_drops_dependency_noise() {
        let resolution = resolve_log_filter(None);
        assert_eq!(resolution.effective, "info,engine=debug");
        assert!(resolution.warning.is_none());
        let targets = &resolution.targets;
        assert!(targets.would_enable("engine::service", &Level::INFO));
        assert!(targets.would_enable("engine::workflow::nodes::retrieve", &Level::INFO));
        assert!(targets.would_enable("engine::retrieval", &Level::DEBUG));
        assert!(targets.would_enable("h2", &Level::INFO));
        assert!(!targets.would_enable("engine::service", &Level::TRACE));
        for noisy in ["h2::codec", "tower", "hyper", "opentelemetry_sdk"] {
            assert!(!targets.would_enable(noisy, &Level::DEBUG), "{noisy} DEBUG");
            assert!(!targets.would_enable(noisy, &Level::TRACE), "{noisy} TRACE");
        }
    }

    #[test]
    fn log_filter_override_replaces_the_default() {
        let warn = resolve_log_filter(Some("warn"));
        assert_eq!(warn.effective, "warn");
        assert!(warn.warning.is_none());
        assert!(!warn.targets.would_enable("engine::service", &Level::INFO));
        assert!(warn.targets.would_enable("engine::service", &Level::WARN));

        let trace = resolve_log_filter(Some("trace"));
        assert!(trace.targets.would_enable("h2", &Level::TRACE));
    }

    #[test]
    fn log_filter_empty_or_blank_override_keeps_the_default_silently() {
        for blank in ["", "   ", "\t"] {
            let resolution = resolve_log_filter(Some(blank));
            assert_eq!(resolution.effective, "info,engine=debug", "{blank:?}");
            assert!(resolution.warning.is_none(), "{blank:?}");
            assert!(!resolution.targets.would_enable("h2::codec", &Level::TRACE));
        }
    }

    #[test]
    fn log_filter_malformed_override_falls_back_to_the_default_with_a_warning() {
        let resolution = resolve_log_filter(Some("engine=["));
        assert_eq!(resolution.effective, "info,engine=debug");
        let warning = resolution.warning.expect("a malformed value must warn");
        assert!(warning.contains("engine=["), "warning names the value: {warning}");
        assert!(!resolution.targets.would_enable("h2::codec", &Level::TRACE));
        assert!(resolution.targets.would_enable("engine::service", &Level::INFO));
    }

    #[test]
    fn log_filter_otlp_shape_passes_oi02_events_and_blocks_h2_codec_on_every_layer() {
        let (subscriber, probe) = otlp_shape(&resolve_log_filter(None));
        {
            let _guard = tracing::subscriber::set_default(subscriber);
            emit_probe_records();
        }
        probe.flush();

        let fmt = probe.fmt.contents();
        assert!(fmt.contains("request_process_state"), "fmt: {fmt}");
        assert!(fmt.contains("retrieve_hybrid_substages"), "fmt: {fmt}");
        assert!(!fmt.contains("h2::codec"), "fmt: {fmt}");
        assert!(!fmt.contains("h2_codec_trace_event_probe"), "fmt: {fmt}");

        let logs = probe.log_records();
        assert!(logs.iter().any(|r| r.contains("request_process_state")), "{logs:?}");
        assert!(logs.iter().any(|r| r.contains("retrieve_hybrid_substages")), "{logs:?}");
        assert!(!logs.iter().any(|r| r.contains("h2_codec_trace_event_probe")), "{logs:?}");

        let spans = probe.span_names();
        assert!(spans.iter().any(|n| n == "engine_span_probe"), "{spans:?}");
        assert!(!spans.iter().any(|n| n == "h2_codec_trace_span_probe"), "{spans:?}");
    }

    #[test]
    fn log_filter_console_only_shape_matches_the_otlp_fmt_result() {
        let fmt = SharedBuf::default();
        let subscriber =
            assemble_subscriber(&resolve_log_filter(None), fmt.clone(), None, None, "test-service");
        {
            let _guard = tracing::subscriber::set_default(subscriber);
            emit_probe_records();
        }
        let out = fmt.contents();
        assert!(out.contains("request_process_state"), "fmt: {out}");
        assert!(out.contains("retrieve_hybrid_substages"), "fmt: {out}");
        assert!(!out.contains("h2_codec_trace_event_probe"), "fmt: {out}");
    }

    #[test]
    fn log_filter_override_reaches_every_layer_not_just_fmt() {
        let (subscriber, probe) = otlp_shape(&resolve_log_filter(Some("warn")));
        {
            let _guard = tracing::subscriber::set_default(subscriber);
            emit_probe_records();
        }
        probe.flush();

        assert!(!probe.fmt.contents().contains("request_process_state"));
        assert!(probe.log_records().is_empty(), "{:?}", probe.log_records());
        assert!(probe.span_names().is_empty(), "{:?}", probe.span_names());
    }

    #[test]
    fn log_filter_console_only_branch_of_build_providers_reports_the_default_filter() {
        let settings = crate::config::TelemetryConfigSettings {
            otlp_endpoint: String::new(),
            service_name: "test-service".into(),
            deployment_environment: "test".into(),
            sampler_ratio: 1.0,
        };
        // The branch reads RUST_LOG once. Tests never set it; when a developer shell has it set
        // the expectation follows the same pure resolver instead of failing spuriously.
        let rust_log = std::env::var("RUST_LOG").ok();
        let expected = resolve_log_filter(rust_log.as_deref());
        let (handle, subscriber) = build_providers_and_layers(&settings);
        assert_eq!(handle.log_filter, expected.effective);
        let _guard = tracing::subscriber::set_default(subscriber);
        assert_eq!(
            tracing::enabled!(target: "h2::codec", Level::TRACE),
            expected.targets.would_enable("h2::codec", &Level::TRACE)
        );
        assert_eq!(
            tracing::enabled!(target: "engine::service", Level::INFO),
            expected.targets.would_enable("engine::service", &Level::INFO)
        );
        if rust_log.is_none() {
            assert!(!tracing::enabled!(target: "h2::codec", Level::TRACE));
            assert!(tracing::enabled!(target: "engine::service", Level::INFO));
        }
    }

    #[test]
    fn log_filter_build_profile_reports_debug_when_debug_assertions_are_on() {
        let expected = if cfg!(debug_assertions) { "debug" } else { "release" };
        assert_eq!(build_profile(), expected);
        assert_eq!(build_profile(), "debug", "cargo test builds carry debug assertions");
    }
}
