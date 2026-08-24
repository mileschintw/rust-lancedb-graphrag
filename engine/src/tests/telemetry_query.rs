use opentelemetry::trace::TracerProvider as _;
use opentelemetry_sdk::testing::trace::new_test_exporter;
use opentelemetry_sdk::trace::SdkTracerProvider;
use tonic::metadata::MetadataMap;
use tracing_subscriber::layer::SubscriberExt;

use crate::telemetry::metrics::{record_query_duration_ms, OUTCOME_COMPLETED, OUTCOME_FAILED};
use crate::telemetry::propagation::extract_parent_context;
use crate::telemetry::TelemetryHandle;

const PINNED_TRACEPARENT: &str = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
const PINNED_TRACE_ID_HEX: &str = "4bf92f3577b34da6a3ce929d0e0e4736";
const PINNED_SPAN_ID_HEX: &str = "00f067aa0ba902b7";

#[tokio::test]
async fn test_query_rag_propagates_w3c_traceparent() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);

    let _guard = tracing::subscriber::set_default(subscriber);

    let mut metadata = MetadataMap::new();
    metadata.insert("traceparent", PINNED_TRACEPARENT.parse().unwrap());

    let parent_cx = extract_parent_context(&metadata);
    let span = tracing::info_span!("query_rag");
    let _ = tracing_opentelemetry::OpenTelemetrySpanExt::set_parent(&span, parent_cx);

    {
        let _entered = span.enter();
        tracing::info!("executing query inside span");
    }
    drop(span);

    let _ = tracer_provider.force_flush();

    let emitted_span = rx.recv().await.expect("expected exported span");
    let trace_id_hex = format!("{:032x}", emitted_span.span_context.trace_id());
    let parent_span_id_hex = format!("{:016x}", emitted_span.parent_span_id);

    assert_eq!(trace_id_hex, PINNED_TRACE_ID_HEX);
    assert_eq!(parent_span_id_hex, PINNED_SPAN_ID_HEX);
}

#[tokio::test]
async fn test_query_rag_untraced_request_generates_new_root_span() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);

    let _guard = tracing::subscriber::set_default(subscriber);

    let metadata = MetadataMap::new();
    let parent_cx = extract_parent_context(&metadata);
    let span = tracing::info_span!("query_rag");
    let _ = tracing_opentelemetry::OpenTelemetrySpanExt::set_parent(&span, parent_cx);

    {
        let _entered = span.enter();
        tracing::info!("executing untraced query");
    }
    drop(span);

    let _ = tracer_provider.force_flush();

    let emitted_span = rx.recv().await.expect("expected exported span");
    assert!(emitted_span.span_context.is_valid());
    let trace_id_hex = format!("{:032x}", emitted_span.span_context.trace_id());
    assert_ne!(trace_id_hex, "00000000000000000000000000000000");
    assert_ne!(trace_id_hex, PINNED_TRACE_ID_HEX);
}

#[tokio::test]
async fn test_query_rag_malformed_traceparent_fails_open() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);

    let _guard = tracing::subscriber::set_default(subscriber);

    let mut metadata = MetadataMap::new();
    metadata.insert("traceparent", "invalid-traceparent-format".parse().unwrap());

    let parent_cx = extract_parent_context(&metadata);
    let span = tracing::info_span!("query_rag");
    let _ = tracing_opentelemetry::OpenTelemetrySpanExt::set_parent(&span, parent_cx);

    {
        let _entered = span.enter();
        tracing::info!("executing query with malformed header");
    }
    drop(span);

    let _ = tracer_provider.force_flush();

    let emitted_span = rx.recv().await.expect("expected exported span");
    assert!(emitted_span.span_context.is_valid());
    let trace_id_hex = format!("{:032x}", emitted_span.span_context.trace_id());
    assert_ne!(trace_id_hex, "00000000000000000000000000000000");
}

#[test]
fn test_record_query_duration_ms() {
    record_query_duration_ms(OUTCOME_COMPLETED, 150);
    record_query_duration_ms(OUTCOME_FAILED, 500);
}

#[test]
fn test_telemetry_handle_shutdown_is_bounded() {
    let handle = TelemetryHandle {
        tracer_provider: None,
        meter_provider: None,
        logger_provider: None,
    };
    handle.shutdown();
}
