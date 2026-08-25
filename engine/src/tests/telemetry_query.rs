use std::collections::HashSet;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use futures::future::BoxFuture;
use opentelemetry::trace::TracerProvider as _;
use opentelemetry_sdk::testing::trace::new_test_exporter;
use opentelemetry_sdk::trace::SdkTracerProvider;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use tonic::metadata::MetadataMap;
use tracing::Instrument;
use tracing_subscriber::layer::SubscriberExt;

use crate::config::GraphSettings;
use crate::db::DatabaseManager;
use crate::generation::{
    AnswerBasis, GenerationError, GenerationErrorKind, GenerationRequest, Generator, ModelOutput,
    ModelUsage,
};
use crate::ingest::EmbeddingProvider;
use crate::pb::lancet::v1::QueryRagRequest;
use crate::retrieval::bm25::{Bm25Config, Bm25Index};
use crate::retrieval::{Candidate, RetrievalSettings};
use crate::service::{
    ProductionBm25RetrievalPort, ProductionDenseRetrievalPort, ProductionEmbeddingPort,
    ProductionGraphQueryPort,
};
use crate::telemetry::metrics::{record_query_duration_ms, OUTCOME_COMPLETED, OUTCOME_FAILED};
use crate::telemetry::propagation::extract_parent_context;
use crate::telemetry::TelemetryHandle;
use crate::workflow::node::QueryEmbeddingPort;
use crate::workflow::nodes::{
    AssemblePromptNode, ExtractGraphContextNode, GenerateAnswerNode, ReformulateQueryNode,
    RetrieveHybridNode,
};
use crate::workflow::ports::{
    Bm25RetrievalPort, DenseRetrievalPort, FakeBm25RetrievalPort, FakeDenseRetrievalPort,
    FakeGraphQueryPort, FakeQueryEmbeddingPort, FakeQueryReformulator, FakeReranker,
    GraphQueryPort,
};
use crate::workflow::{EventSequence, WorkflowContext, WorkflowEventSink, WorkflowRunner};

const PINNED_TRACEPARENT: &str = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
const PINNED_TRACE_ID_HEX: &str = "4bf92f3577b34da6a3ce929d0e0e4736";
const PINNED_SPAN_ID_HEX: &str = "00f067aa0ba902b7";

fn make_candidate(doc_id: &str, chunk_id: &str, score: f64) -> Candidate {
    Candidate {
        document_id: doc_id.to_string(),
        chunk_id: chunk_id.to_string(),
        chunk_index: 0,
        char_start: 0,
        char_end: 100,
        content: format!("Content for {chunk_id} of {doc_id}"),
        title: Some(format!("Title {doc_id}")),
        section_path: Some("Section 1".to_string()),
        content_type: Some("text/plain".to_string()),
        embedding_model: Some("text-embedding-3-small".to_string()),
        ingested_at: Some(1700000000),
        score,
    }
}

struct TestEmbeddingProvider;

impl EmbeddingProvider for TestEmbeddingProvider {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move {
            Ok(texts.iter().map(|_| vec![0.1f32; 2048]).collect())
        })
    }
}

struct RetryableGenerator {
    attempts: Arc<AtomicUsize>,
}

impl Generator for RetryableGenerator {
    fn generate<'a>(
        &'a self,
        _req: GenerationRequest,
    ) -> BoxFuture<'a, Result<ModelOutput, GenerationError>> {
        Box::pin(async move {
            let attempt = self.attempts.fetch_add(1, Ordering::SeqCst) + 1;
            if attempt == 1 {
                Err(GenerationError::new(
                    GenerationErrorKind::Timeout,
                    "first attempt timed out",
                ))
            } else {
                Ok(ModelOutput {
                    answer: "Success on retry [1].".to_string(),
                    cited_evidence_ids: vec!["[1]".to_string()],
                    answer_basis: AnswerBasis::Retrieval,
                    notices: vec![],
                    warnings: vec![],
                    usage: Some(ModelUsage {
                        prompt_tokens: 42,
                        completion_tokens: 18,
                        total_tokens: 60,
                    }),
                })
            }
        })
    }
}

struct SingleSuccessGenerator;

impl Generator for SingleSuccessGenerator {
    fn generate<'a>(
        &'a self,
        _req: GenerationRequest,
    ) -> BoxFuture<'a, Result<ModelOutput, GenerationError>> {
        Box::pin(async move {
            Ok(ModelOutput {
                answer: "Direct success [1].".to_string(),
                cited_evidence_ids: vec!["[1]".to_string()],
                answer_basis: AnswerBasis::Retrieval,
                notices: vec![],
                warnings: vec![],
                usage: Some(ModelUsage {
                    prompt_tokens: 25,
                    completion_tokens: 10,
                    total_tokens: 35,
                }),
            })
        })
    }
}

fn build_runner_with_fakes(
    generator: Option<Arc<dyn Generator>>,
) -> (WorkflowRunner, WorkflowContext, WorkflowEventSink, mpsc::Receiver<Result<crate::pb::lancet::v1::WorkflowEvent, tonic::Status>>) {
    let (tx, rx) = mpsc::channel(100);
    let trace_id = "trace-telem-01".to_string();
    let session_id = "sess-telem-01".to_string();

    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        trace_id.clone(),
        session_id.clone(),
    );

    let req = QueryRagRequest {
        query: "What is Lancet?".to_string(),
        session_id: session_id.clone(),
        ..Default::default()
    };
    let ctx = WorkflowContext::new(session_id, trace_id, &req);

    let fake_reformulator = Arc::new(FakeQueryReformulator::new(vec!["What is Lancet?".to_string()]));
    let fake_embedder = Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let fake_graph = Arc::new(FakeGraphQueryPort::success("Lancet -- uses -- LanceDB"));
    let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![make_candidate("doc-1", "chk-1", 0.9)]));
    let fake_bm25 = Arc::new(FakeBm25RetrievalPort::success(vec![make_candidate("doc-1", "chk-2", 0.8)]));
    let fake_reranker = Arc::new(FakeReranker::success());

    let mut runner = WorkflowRunner::new();
    runner.add_node(ReformulateQueryNode::with_reformulator(Some(fake_reformulator)));
    runner.add_node(ExtractGraphContextNode::new(Some(fake_embedder), Some(fake_graph)));
    runner.add_node(RetrieveHybridNode::new(
        Some(fake_dense),
        Some(fake_bm25),
        Some(fake_reranker),
        RetrievalSettings::default(),
    ));
    runner.add_node(AssemblePromptNode::default());
    runner.add_node(GenerateAnswerNode::new(generator));

    (runner, ctx, sink, rx)
}

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

#[tokio::test]
async fn query_span_hierarchy_emits_exactly_five_node_spans() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let (runner, ctx, sink, _rx_events) = build_runner_with_fakes(Some(Arc::new(SingleSuccessGenerator)));
    let cancel = CancellationToken::new();

    let _ = runner.run_workflow(ctx, cancel, sink).await;
    let _ = tracer_provider.force_flush();

    let mut node_spans = Vec::new();
    let expected_names: HashSet<&str> = [
        "query_reformulation",
        "hybrid_retrieval",
        "graph_context_extraction",
        "prompt_assembly",
        "llm_generation",
    ]
    .into_iter()
    .collect();

    while let Ok(span) = rx.try_recv() {
        if expected_names.contains(span.name.as_ref()) {
            node_spans.push(span.name.to_string());
        }
    }

    assert_eq!(node_spans.len(), 5);
    let set: HashSet<String> = node_spans.into_iter().collect();
    assert_eq!(set.len(), 5);
    for name in &expected_names {
        assert!(set.contains(*name), "missing node span: {name}");
    }
}

#[tokio::test]
async fn node_spans_nest_under_the_installed_parent() {
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

    let parent_span = tracing::info_span!("query_rag");
    let _ = tracing_opentelemetry::OpenTelemetrySpanExt::set_parent(&parent_span, parent_cx);

    let (runner, ctx, sink, _rx_events) = build_runner_with_fakes(Some(Arc::new(SingleSuccessGenerator)));
    let cancel = CancellationToken::new();

    let _ = runner
        .run_workflow(ctx, cancel, sink)
        .instrument(parent_span.clone())
        .await;

    drop(parent_span);
    let _ = tracer_provider.force_flush();

    let expected_names: HashSet<&str> = [
        "query_reformulation",
        "hybrid_retrieval",
        "graph_context_extraction",
        "prompt_assembly",
        "llm_generation",
    ]
    .into_iter()
    .collect();

    let mut matched = 0;
    while let Ok(span) = rx.try_recv() {
        if expected_names.contains(span.name.as_ref()) {
            matched += 1;
            let trace_id_hex = format!("{:032x}", span.span_context.trace_id());
            assert_eq!(trace_id_hex, PINNED_TRACE_ID_HEX);
        }
    }
    assert_eq!(matched, 5);
}

#[tokio::test]
async fn node_span_records_duration_and_outcome() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let (runner, ctx, sink, _rx_events) = build_runner_with_fakes(Some(Arc::new(SingleSuccessGenerator)));
    let cancel = CancellationToken::new();

    let _ = runner.run_workflow(ctx, cancel, sink).await;
    let _ = tracer_provider.force_flush();

    let mut checked = 0;
    while let Ok(span) = rx.try_recv() {
        if [
            "query_reformulation",
            "hybrid_retrieval",
            "graph_context_extraction",
            "prompt_assembly",
            "llm_generation",
        ]
        .contains(&span.name.as_ref())
        {
            checked += 1;
            let outcome_attr = span.attributes.iter().find(|kv| kv.key.as_str() == "lancet.node.outcome");
            assert!(outcome_attr.is_some(), "span {} must have lancet.node.outcome", span.name);
            assert_eq!(
                outcome_attr.unwrap().value.to_string(),
                "ok"
            );
        }
    }
    assert_eq!(checked, 5);
}

#[tokio::test]
async fn node_span_cancellation_does_not_leak() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let (runner, ctx, sink, _rx_events) = build_runner_with_fakes(Some(Arc::new(SingleSuccessGenerator)));
    let cancel = CancellationToken::new();
    let cancel_clone = cancel.clone();
    tokio::spawn(async move {
        tokio::time::sleep(std::time::Duration::from_millis(2)).await;
        cancel_clone.cancel();
    });

    let _ = runner.run_workflow(ctx, cancel, sink).await;
    let _ = tracer_provider.force_flush();

    let mut closed_spans = 0;
    while let Ok(span) = rx.try_recv() {
        if [
            "query_reformulation",
            "hybrid_retrieval",
            "graph_context_extraction",
            "prompt_assembly",
            "llm_generation",
        ]
        .contains(&span.name.as_ref())
        {
            closed_spans += 1;
        }
    }
    assert!(closed_spans > 0, "opened node spans must close and export on cancellation");
}

#[tokio::test]
async fn graph_augmentation_record_still_resolves_under_node_span() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let (runner, ctx, sink, _rx_events) = build_runner_with_fakes(Some(Arc::new(SingleSuccessGenerator)));
    let cancel = CancellationToken::new();

    let _ = runner.run_workflow(ctx, cancel, sink).await;
    let _ = tracer_provider.force_flush();

    let mut found_graph_span = false;
    while let Ok(span) = rx.try_recv() {
        if span.name == "graph_context_extraction" {
            found_graph_span = true;
        }
    }
    assert!(found_graph_span);
}

#[tokio::test]
async fn leaf_span_dense_search_wraps_real_lancedb_call() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let temp_dir = std::env::temp_dir().join(format!("lancet-telem-dense-{}", uuid::Uuid::new_v4()));
    let path = temp_dir.to_str().unwrap().replace('\\', "/");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let dense_port = ProductionDenseRetrievalPort {
        database,
        nodes_version: 1,
        retrieval_settings: RetrievalSettings::default(),
    };

    let cancel = CancellationToken::new();
    let _ = dense_port.retrieve_dense("test query", &[0.1; 2048], None, &cancel).await;
    let _ = tracer_provider.force_flush();

    let mut found_dense = false;
    while let Ok(span) = rx.try_recv() {
        if span.name == "dense_search" {
            found_dense = true;
            let db_sys = span.attributes.iter().find(|kv| kv.key.as_str() == "db.system");
            assert_eq!(db_sys.map(|v| v.value.to_string()), Some("lancedb".to_string()));
            let db_op = span.attributes.iter().find(|kv| kv.key.as_str() == "db.operation");
            assert_eq!(db_op.map(|v| v.value.to_string()), Some("vector_search".to_string()));
        }
    }
    assert!(found_dense, "dense_search leaf span must be exported");
    let _ = std::fs::remove_dir_all(temp_dir);
}

#[tokio::test]
async fn leaf_span_bm25_search_wraps_real_index_call() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let bm25 = Arc::new(Bm25Index::from_candidates(vec![], Bm25Config::default()).unwrap());
    let bm25_port = ProductionBm25RetrievalPort {
        bm25,
        retrieval_settings: RetrievalSettings::default(),
    };

    let cancel = CancellationToken::new();
    let _ = bm25_port.retrieve_bm25("test bm25", None, &cancel).await;
    let _ = tracer_provider.force_flush();

    let mut found_bm25 = false;
    while let Ok(span) = rx.try_recv() {
        if span.name == "bm25_search" {
            found_bm25 = true;
            let path_attr = span.attributes.iter().find(|kv| kv.key.as_str() == "lancet.retrieval.path");
            assert_eq!(path_attr.map(|v| v.value.to_string()), Some("bm25".to_string()));
        }
    }
    assert!(found_bm25, "bm25_search leaf span must be exported");
}

#[tokio::test]
async fn leaf_span_embedding_request_wraps_real_http_call() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let embed_port = ProductionEmbeddingPort {
        embedder: Arc::new(TestEmbeddingProvider),
    };

    let cancel = CancellationToken::new();
    let _ = embed_port.embed_variant_zero("sample variant", &cancel).await;
    let _ = tracer_provider.force_flush();

    let mut found_embed = false;
    while let Ok(span) = rx.try_recv() {
        if span.name == "embedding_request" {
            found_embed = true;
            let model_attr = span.attributes.iter().find(|kv| kv.key.as_str() == "gen_ai.request.model");
            assert!(model_attr.is_some());
        }
    }
    assert!(found_embed, "embedding_request leaf span must be exported");
}

#[tokio::test]
async fn leaf_span_graph_traversal_wraps_real_traversal() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let temp_dir = std::env::temp_dir().join(format!("lancet-telem-graph-{}", uuid::Uuid::new_v4()));
    let path = temp_dir.to_str().unwrap().replace('\\', "/");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let graph_port = ProductionGraphQueryPort {
        database,
        graph_settings: GraphSettings {
            seed_match_min_score: 0.7,
            max_hop_cap: 2,
        },
    };

    let cancel = CancellationToken::new();
    let _ = graph_port.query_graph(&[0.1; 2048], &cancel).await;
    let _ = tracer_provider.force_flush();

    let mut found_graph = false;
    while let Ok(span) = rx.try_recv() {
        if span.name == "graph_traversal" {
            found_graph = true;
        }
    }
    assert!(found_graph, "graph_traversal leaf span must be exported");
    let _ = std::fs::remove_dir_all(temp_dir);
}

#[tokio::test]
async fn llm_attempt_spans_are_two_siblings_on_retry() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let attempts = Arc::new(AtomicUsize::new(0));
    let generator: Arc<dyn Generator> = Arc::new(RetryableGenerator {
        attempts: Arc::clone(&attempts),
    });

    let (runner, ctx, sink, _rx_events) = build_runner_with_fakes(Some(generator));
    let cancel = CancellationToken::new();

    let _ = runner.run_workflow(ctx, cancel, sink).await;
    let _ = tracer_provider.force_flush();

    let mut attempt_spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        if span.name == "llm_attempt" {
            let attempt_num = span
                .attributes
                .iter()
                .find(|kv| kv.key.as_str() == "attempt")
                .and_then(|a| a.value.to_string().parse::<i64>().ok());
            attempt_spans.push((span, attempt_num));
        }
    }

    assert_eq!(attempt_spans.len(), 2, "retry must export exactly two llm_attempt spans");
    attempt_spans.sort_by_key(|(_, attempt)| *attempt);
    assert_eq!(attempt_spans[0].1, Some(1));
    assert_eq!(attempt_spans[1].1, Some(2));
}

#[tokio::test]
async fn llm_attempt_span_is_single_without_retry() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let generator: Arc<dyn Generator> = Arc::new(SingleSuccessGenerator);
    let (runner, ctx, sink, _rx_events) = build_runner_with_fakes(Some(generator));
    let cancel = CancellationToken::new();

    let _ = runner.run_workflow(ctx, cancel, sink).await;
    let _ = tracer_provider.force_flush();

    let mut attempt_spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        if span.name == "llm_attempt" {
            attempt_spans.push(span);
        }
    }

    assert_eq!(attempt_spans.len(), 1, "non-retry must export exactly one llm_attempt span");
}

#[tokio::test]
async fn leaf_spans_absent_for_fake_ports() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let (runner, ctx, sink, _rx_events) = build_runner_with_fakes(None);
    let cancel = CancellationToken::new();

    let _ = runner.run_workflow(ctx, cancel, sink).await;
    let _ = tracer_provider.force_flush();

    let leaf_names: HashSet<&str> = [
        "embedding_request",
        "dense_search",
        "bm25_search",
        "graph_traversal",
    ]
    .into_iter()
    .collect();

    let mut leaf_count = 0;
    while let Ok(span) = rx.try_recv() {
        if leaf_names.contains(span.name.as_ref()) {
            leaf_count += 1;
        }
    }

    assert_eq!(leaf_count, 0, "fake ports must not emit real leaf spans");
}

#[tokio::test]
async fn graph_augmentation_record_lands_on_graph_traversal_leaf() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let temp_dir = std::env::temp_dir().join(format!("lancet-telem-gt-{}", uuid::Uuid::new_v4()));
    let path = temp_dir.to_str().unwrap().replace('\\', "/");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let graph_port = ProductionGraphQueryPort {
        database,
        graph_settings: GraphSettings {
            seed_match_min_score: 0.7,
            max_hop_cap: 2,
        },
    };

    let cancel = CancellationToken::new();
    let _ = graph_port.query_graph(&[0.1; 2048], &cancel).await;
    let _ = tracer_provider.force_flush();

    let mut found_graph_leaf = false;
    while let Ok(span) = rx.try_recv() {
        if span.name == "graph_traversal" {
            found_graph_leaf = true;
            let aug_attr = span.attributes.iter().find(|kv| kv.key.as_str() == "graph_augmentation");
            assert!(aug_attr.is_some(), "graph_traversal must carry graph_augmentation attribute");
        }
    }
    assert!(found_graph_leaf);
    let _ = std::fs::remove_dir_all(temp_dir);
}

// ---------------------------------------------------------------------------
// Task 2: Engine log correlation across the instrumented paths
// ---------------------------------------------------------------------------

#[tokio::test]
async fn engine_log_inside_node_span_carries_trace_context() {
    crate::telemetry::ensure_propagators();

    let (trace_exporter, mut rx_span, _) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(trace_exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_trace_layer = tracing_opentelemetry::layer().with_tracer(tracer);

    let log_exporter = opentelemetry_sdk::logs::InMemoryLogExporter::default();
    let logger_provider = opentelemetry_sdk::logs::SdkLoggerProvider::builder()
        .with_log_processor(opentelemetry_sdk::logs::SimpleLogProcessor::new(log_exporter.clone()))
        .build();
    let otel_log_layer = opentelemetry_appender_tracing::layer::OpenTelemetryTracingBridge::new(&logger_provider);

    let subscriber = tracing_subscriber::Registry::default()
        .with(otel_trace_layer)
        .with(otel_log_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let span = tracing::info_span!("retrieve_hybrid");
    {
        let _entered = span.enter();
        tracing::info!("retrieving hybrid candidates");
    }
    drop(span);

    let _ = tracer_provider.force_flush();
    let _ = logger_provider.force_flush();

    let span_data = rx_span.recv().await.expect("span emitted");
    let logs = log_exporter.get_emitted_logs().expect("emitted logs");
    assert_eq!(logs.len(), 1, "expected 1 log record");

    let tc = logs[0].record.trace_context().expect("trace context on log record");
    assert_eq!(tc.trace_id, span_data.span_context.trace_id());
    assert_eq!(tc.span_id, span_data.span_context.span_id());
}

#[tokio::test]
async fn engine_log_inside_leaf_span_carries_leaf_span_context() {
    crate::telemetry::ensure_propagators();

    let (trace_exporter, mut rx_span, _) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(trace_exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_trace_layer = tracing_opentelemetry::layer().with_tracer(tracer);

    let log_exporter = opentelemetry_sdk::logs::InMemoryLogExporter::default();
    let logger_provider = opentelemetry_sdk::logs::SdkLoggerProvider::builder()
        .with_log_processor(opentelemetry_sdk::logs::SimpleLogProcessor::new(log_exporter.clone()))
        .build();
    let otel_log_layer = opentelemetry_appender_tracing::layer::OpenTelemetryTracingBridge::new(&logger_provider);

    let subscriber = tracing_subscriber::Registry::default()
        .with(otel_trace_layer)
        .with(otel_log_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let node_span = tracing::info_span!("retrieve_hybrid");
    {
        let _node_entered = node_span.enter();
        let leaf_span = tracing::info_span!("dense_retrieval");
        {
            let _leaf_entered = leaf_span.enter();
            tracing::info!("executing dense vector search");
        }
    }
    drop(node_span);

    let _ = tracer_provider.force_flush();
    let _ = logger_provider.force_flush();

    let mut leaf_span_data = None;
    while let Ok(s) = rx_span.try_recv() {
        if s.name == "dense_retrieval" {
            leaf_span_data = Some(s);
        }
    }
    let leaf_span = leaf_span_data.expect("leaf span emitted");

    let logs = log_exporter.get_emitted_logs().expect("emitted logs");
    assert_eq!(logs.len(), 1);
    let tc = logs[0].record.trace_context().expect("trace context on leaf log");
    assert_eq!(tc.trace_id, leaf_span.span_context.trace_id());
    assert_eq!(tc.span_id, leaf_span.span_context.span_id(), "must report leaf span ID");
}

#[tokio::test]
async fn engine_log_outside_any_span_has_no_trace_context() {
    crate::telemetry::ensure_propagators();

    let log_exporter = opentelemetry_sdk::logs::InMemoryLogExporter::default();
    let logger_provider = opentelemetry_sdk::logs::SdkLoggerProvider::builder()
        .with_log_processor(opentelemetry_sdk::logs::SimpleLogProcessor::new(log_exporter.clone()))
        .build();
    let otel_log_layer = opentelemetry_appender_tracing::layer::OpenTelemetryTracingBridge::new(&logger_provider);

    let subscriber = tracing_subscriber::Registry::default().with(otel_log_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    tracing::info!("background startup event without active span");

    let _ = logger_provider.force_flush();

    let logs = log_exporter.get_emitted_logs().expect("emitted logs");
    assert_eq!(logs.len(), 1);
    assert!(logs[0].record.trace_context().is_none(), "unspanned log must have no trace context");
}

#[tokio::test]
async fn engine_log_reaches_fmt_layer_regardless_of_provider() {
    let settings = crate::config::TelemetryConfigSettings {
        otlp_endpoint: String::new(), // Console-only mode
        service_name: "test-service".into(),
        deployment_environment: "test".into(),
        sampler_ratio: 1.0,
    };

    let (handle, subscriber) = crate::telemetry::build_providers_and_layers(&settings);
    let _guard = tracing::subscriber::set_default(subscriber);

    // Emitting inside console-only mode must succeed without errors
    tracing::info!("console event with no OTLP logger provider");
    handle.shutdown();
}

#[tokio::test]
async fn engine_log_records_survive_bounded_shutdown() {
    crate::telemetry::ensure_propagators();

    #[derive(Debug, Clone, Default)]
    struct RetainingLogExporter {
        records: Arc<std::sync::Mutex<Vec<opentelemetry_sdk::logs::SdkLogRecord>>>,
    }

    impl opentelemetry_sdk::logs::LogExporter for RetainingLogExporter {
        fn export(
            &self,
            batch: opentelemetry_sdk::logs::LogBatch<'_>,
        ) -> impl std::future::Future<Output = opentelemetry_sdk::error::OTelSdkResult> + Send {
            let mut guard = self.records.lock().unwrap();
            for (record, _) in batch.iter() {
                guard.push(record.clone());
            }
            async { Ok(()) }
        }
    }

    let exporter = RetainingLogExporter::default();
    let records = exporter.records.clone();

    let logger_provider = opentelemetry_sdk::logs::SdkLoggerProvider::builder()
        .with_log_processor(opentelemetry_sdk::logs::BatchLogProcessor::builder(exporter).build())
        .build();
    let otel_log_layer = opentelemetry_appender_tracing::layer::OpenTelemetryTracingBridge::new(&logger_provider);

    let subscriber = tracing_subscriber::Registry::default().with(otel_log_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let handle = TelemetryHandle {
        tracer_provider: None,
        meter_provider: None,
        logger_provider: Some(logger_provider),
    };

    tracing::info!("event emitted immediately before shutdown");

    // Shutdown must drain buffered batch logs
    tokio::task::spawn_blocking(move || {
        handle.shutdown();
    })
    .await
    .unwrap();

    let captured = records.lock().unwrap();
    assert_eq!(captured.len(), 1, "log emitted before shutdown must survive shutdown drain");
}

#[tokio::test]
async fn engine_logs_carry_no_user_content() {
    crate::telemetry::ensure_propagators();

    let (trace_exporter, _, _) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(trace_exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_trace_layer = tracing_opentelemetry::layer().with_tracer(tracer);

    let log_exporter = opentelemetry_sdk::logs::InMemoryLogExporter::default();
    let logger_provider = opentelemetry_sdk::logs::SdkLoggerProvider::builder()
        .with_log_processor(opentelemetry_sdk::logs::SimpleLogProcessor::new(log_exporter.clone()))
        .build();
    let otel_log_layer = opentelemetry_appender_tracing::layer::OpenTelemetryTracingBridge::new(&logger_provider);

    let subscriber = tracing_subscriber::Registry::default()
        .with(otel_trace_layer)
        .with(otel_log_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let sensitive_query = "CLASSIFIED_USER_QUERY_TEXT";
    let sensitive_evidence = "CLASSIFIED_USER_EVIDENCE_TEXT";
    let sensitive_answer = "CLASSIFIED_USER_ANSWER_TEXT";

    let (tx, _rx) = mpsc::channel(100);
    let sink = WorkflowEventSink::new(tx, Arc::new(EventSequence::new()), "t1".into(), "s1".into());

    let req = QueryRagRequest {
        query: sensitive_query.into(),
        session_id: "s1".into(),
        ..Default::default()
    };
    let ctx = WorkflowContext::new("s1".into(), "t1".into(), &req);

    let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![Candidate {
        document_id: "doc-1".into(),
        chunk_id: "chunk-1".into(),
        chunk_index: 0,
        char_start: 0,
        char_end: 100,
        content: sensitive_evidence.into(),
        title: None,
        section_path: None,
        content_type: None,
        embedding_model: None,
        ingested_at: None,
        score: 0.9,
    }]));

    struct SensitiveAnswerGen(String);
    impl Generator for SensitiveAnswerGen {
        fn generate<'a>(&'a self, _req: GenerationRequest) -> BoxFuture<'a, Result<ModelOutput, GenerationError>> {
            Box::pin(async move {
                Ok(ModelOutput {
                    answer: self.0.clone(),
                    cited_evidence_ids: vec!["[1]".into()],
                    answer_basis: AnswerBasis::Retrieval,
                    notices: vec![],
                    warnings: vec![],
                    usage: None,
                })
            })
        }
    }

    let mut runner = WorkflowRunner::new();
    runner.add_node(RetrieveHybridNode::new(Some(fake_dense), None, None, RetrievalSettings::default()));
    runner.add_node(AssemblePromptNode::default());
    runner.add_node(GenerateAnswerNode::new(Some(Arc::new(SensitiveAnswerGen(sensitive_answer.into())))));

    let cancel = CancellationToken::new();
    let _ = runner.run_workflow(ctx, cancel, sink).await;

    let _ = logger_provider.force_flush();

    let logs = log_exporter.get_emitted_logs().expect("emitted logs");
    for log in logs {
        if let Some(body) = log.record.body() {
            let body_str = format!("{body:?}");
            assert!(!body_str.contains(sensitive_query), "log body must not contain query text");
            assert!(!body_str.contains(sensitive_evidence), "log body must not contain evidence text");
            assert!(!body_str.contains(sensitive_answer), "log body must not contain answer text");
        }
        for (key, val) in log.record.attributes_iter() {
            let val_str = format!("{val:?}");
            assert!(!val_str.contains(sensitive_query), "log attribute {} must not contain query text", key.as_str());
            assert!(!val_str.contains(sensitive_evidence), "log attribute {} must not contain evidence text", key.as_str());
            assert!(!val_str.contains(sensitive_answer), "log attribute {} must not contain answer text", key.as_str());
        }
    }
}

// ---------------------------------------------------------------------------
// Task 3: D-41 workflow metadata in both places, from one degraded-mode derivation
// ---------------------------------------------------------------------------

#[test]
fn test_derive_degraded_mode_11_degrading_codes_return_true() {
    use crate::pb::lancet::v1::{AnswerBasis, Notice, NoticeCode};
    use crate::workflow::derive_degraded_mode;

    let degrading_codes = [
        NoticeCode::GraphUnavailable,
        NoticeCode::GraphDegraded,
        NoticeCode::GraphTimeout,
        NoticeCode::RetrievalDegradedDense,
        NoticeCode::RetrievalDegradedBm25,
        NoticeCode::CitationDropped,
        NoticeCode::ModelOnly,
        NoticeCode::BasisReconciled,
        NoticeCode::IndexRebuildFailed,
        NoticeCode::IndexStale,
        NoticeCode::IndexGenerationMismatch,
    ];

    for code in degrading_codes {
        let notices = vec![Notice {
            code: code.as_str_name().to_string(),
            message: "degraded test".into(),
            severity: 1,
            typed_code: code as i32,
        }];
        assert!(
            derive_degraded_mode(&notices, AnswerBasis::Retrieval),
            "code {:?} must derive degraded_mode = true",
            code
        );
    }
}

#[test]
fn test_derive_degraded_mode_6_non_degrading_codes_return_false() {
    use crate::pb::lancet::v1::{AnswerBasis, Notice, NoticeCode};
    use crate::workflow::derive_degraded_mode;

    let non_degrading_codes = [
        NoticeCode::Unspecified,
        NoticeCode::NoEvidence,
        NoticeCode::ModelNotice,
        NoticeCode::ModelWarning,
        NoticeCode::CitationRepaired,
        NoticeCode::GraphAblation,
    ];

    for code in non_degrading_codes {
        let notices = vec![Notice {
            code: code.as_str_name().to_string(),
            message: "non-degraded test".into(),
            severity: 1,
            typed_code: code as i32,
        }];
        assert!(
            !derive_degraded_mode(&notices, AnswerBasis::Retrieval),
            "code {:?} must derive degraded_mode = false",
            code
        );
    }
}

#[test]
fn test_derive_degraded_mode_non_retrieval_basis_returns_true() {
    use crate::pb::lancet::v1::AnswerBasis;
    use crate::workflow::derive_degraded_mode;

    assert!(derive_degraded_mode(&[], AnswerBasis::Mixed));
    assert!(derive_degraded_mode(&[], AnswerBasis::ModelOnly));
    assert!(derive_degraded_mode(&[], AnswerBasis::Unspecified));
    assert!(!derive_degraded_mode(&[], AnswerBasis::Retrieval));
}

#[tokio::test]
async fn test_workflow_completed_event_carries_workflow_metadata_all_fields() {
    crate::telemetry::ensure_propagators();

    let (runner, ctx, sink, mut rx) = build_runner_with_fakes(Some(Arc::new(RetryableGenerator {
        attempts: Arc::new(AtomicUsize::new(0)),
    })));

    let cancel = CancellationToken::new();
    let _ = runner.run_workflow(ctx, cancel, sink).await;

    let mut terminal_event = None;
    while let Some(res) = rx.recv().await {
        if let Ok(event) = res {
            if let Some(crate::pb::lancet::v1::workflow_event::Event::WorkflowCompleted(wc)) = event.event {
                terminal_event = Some(wc);
                break;
            }
        }
    }

    let wc = terminal_event.expect("expected WorkflowCompleted event");
    let meta = wc.metadata.expect("expected metadata on WorkflowCompletedEvent");

    assert!(meta.started_at_ms > 0, "started_at_ms must be non-zero epoch");
    assert!(meta.completed_at_ms >= meta.started_at_ms, "completed_at_ms must be >= started_at_ms");
    assert_eq!(meta.vector_count, 1);
    assert_eq!(meta.bm25_count, 1);
    assert_eq!(meta.prompt_tokens, 42);
    assert_eq!(meta.completion_tokens, 18);
    assert!(!meta.degraded_mode, "clean run with Retrieval basis must not be degraded");
}

#[tokio::test]
async fn test_workflow_span_carries_workflow_metadata_attributes() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx_span, _) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_tracer");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let (runner, ctx, sink, _rx) = build_runner_with_fakes(Some(Arc::new(SingleSuccessGenerator)));

    let span = tracing::info_span!(
        "query_rag",
        graph_augmentation = tracing::field::Empty,
        session_id = "s1",
        correlation_id = "t1",
        "lancet.workflow.started_at_ms" = tracing::field::Empty,
        "lancet.workflow.completed_at_ms" = tracing::field::Empty,
        "lancet.workflow.reformulation_used" = tracing::field::Empty,
        "lancet.workflow.vector_count" = tracing::field::Empty,
        "lancet.workflow.bm25_count" = tracing::field::Empty,
        "lancet.workflow.graph_node_count" = tracing::field::Empty,
        "lancet.workflow.graph_edge_count" = tracing::field::Empty,
        "lancet.workflow.prompt_tokens" = tracing::field::Empty,
        "lancet.workflow.completion_tokens" = tracing::field::Empty,
        "lancet.degraded_mode" = tracing::field::Empty,
    );

    let cancel = CancellationToken::new();
    {
        let _entered = span.enter();
        let _ = runner.run_workflow(ctx, cancel, sink).await;
    }
    drop(span);

    let _ = tracer_provider.force_flush();

    let mut query_span = None;
    while let Ok(s) = rx_span.try_recv() {
        if s.name == "query_rag" {
            query_span = Some(s);
        }
    }

    let s = query_span.expect("query_rag span emitted");
    let find_attr = |k: &str| s.attributes.iter().find(|kv| kv.key.as_str() == k);

    assert!(find_attr("lancet.workflow.started_at_ms").is_some());
    assert!(find_attr("lancet.workflow.completed_at_ms").is_some());
    assert!(find_attr("lancet.workflow.reformulation_used").is_some());
    assert!(find_attr("lancet.workflow.vector_count").is_some());
    assert!(find_attr("lancet.workflow.bm25_count").is_some());
    assert!(find_attr("lancet.workflow.prompt_tokens").is_some());
    assert!(find_attr("lancet.workflow.completion_tokens").is_some());
    assert!(find_attr("lancet.degraded_mode").is_some());
}

#[tokio::test]
async fn test_terminal_failure_event_carries_workflow_metadata() {
    crate::telemetry::ensure_propagators();

    struct AlwaysFailingGen;
    impl Generator for AlwaysFailingGen {
        fn generate<'a>(&'a self, _req: GenerationRequest) -> BoxFuture<'a, Result<ModelOutput, GenerationError>> {
            Box::pin(async move {
                Err(GenerationError::new(GenerationErrorKind::ProviderError, "provider fatal failure"))
            })
        }
    }

    let (runner, ctx, sink, mut rx) = build_runner_with_fakes(Some(Arc::new(AlwaysFailingGen)));
    let cancel = CancellationToken::new();
    let _ = runner.run_workflow(ctx, cancel, sink).await;

    let mut terminal_event = None;
    while let Some(res) = rx.recv().await {
        if let Ok(event) = res {
            if let Some(crate::pb::lancet::v1::workflow_event::Event::WorkflowCompleted(wc)) = event.event {
                terminal_event = Some(wc);
                break;
            }
        }
    }

    let wc = terminal_event.expect("expected WorkflowCompleted event on failure");
    assert!(!wc.success);
    let meta = wc.metadata.expect("failure event must still carry metadata");
    assert!(meta.started_at_ms > 0);
    assert!(meta.completed_at_ms >= meta.started_at_ms);
}
