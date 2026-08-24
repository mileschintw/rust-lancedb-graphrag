//! Telemetry ingestion test module.
//!
//! Implements test assertions for document ingestion traces, debounced index rebuilds,
//! and graph extraction leaf spans (06.2-04-PLAN.md).

use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;
use futures::future::BoxFuture;
use opentelemetry::trace::{SpanId, TracerProvider as _};
use opentelemetry_sdk::testing::trace::new_test_exporter;
use opentelemetry_sdk::trace::SdkTracerProvider;
use tokio::sync::{mpsc, watch};
use tracing_subscriber::layer::SubscriberExt;
use uuid::Uuid;

use crate::config::EffectiveRagSettings;
use crate::db::DatabaseManager;
use crate::generation::{BoxFuture as GenBoxFuture, GenerationError, GenerationErrorKind};
use crate::graph::extraction::{
    extract_with_retry, ExtractedEntity, ExtractedRelation, ExtractionGenerator, ExtractionOutput,
    ExtractionRequest,
};
use crate::ingest::{
    arm_rebuild_fail_next, inert_rebuild_tx, spawn_rebuild_debounce_task, spawn_worker,
    spawn_worker_with_boundary, EmbeddingProvider, IngestionJob,
    RebuildTriggerLinks, ReplacementMutation, QUEUE_CAPACITY,
};
use crate::tests::{configured_service, database_path, FakeEmbedder, FaultingReplacementMutationBoundary};

const PINNED_TRACEPARENT: &str = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
const PINNED_TRACE_ID_HEX: &str = "4bf92f3577b34da6a3ce929d0e0e4736";

struct TestFakeExtractionGenerator {
    output: ExtractionOutput,
}

impl TestFakeExtractionGenerator {
    fn new(output: ExtractionOutput) -> Self {
        Self { output }
    }
}

impl ExtractionGenerator for TestFakeExtractionGenerator {
    fn extract<'a>(&'a self, _request: ExtractionRequest) -> GenBoxFuture<'a, Result<ExtractionOutput, GenerationError>> {
        Box::pin(async move { Ok(self.output.clone()) })
    }
}

fn make_test_extraction_generator() -> Arc<dyn ExtractionGenerator> {
    Arc::new(TestFakeExtractionGenerator::new(ExtractionOutput {
        entities: vec![
            ExtractedEntity {
                name: "Alice".into(),
                entity_type: "person".into(),
            },
            ExtractedEntity {
                name: "Bob".into(),
                entity_type: "person".into(),
            },
        ],
        relations: vec![ExtractedRelation {
            source: "Alice".into(),
            target: "Bob".into(),
            relation_type: "knows".into(),
            confidence: 0.9,
        }],
    }))
}

fn test_fake_generator() -> Arc<dyn crate::generation::Generator> {
    Arc::new(crate::tests::FakeGenerator::new(Ok(crate::generation::ModelOutput {
        answer: "Test answer".into(),
        cited_evidence_ids: vec![],
        answer_basis: crate::generation::AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        usage: None,
    })))
}

struct RetryFailingExtractionGenerator {
    attempts: Arc<AtomicUsize>,
    output: ExtractionOutput,
}

impl ExtractionGenerator for RetryFailingExtractionGenerator {
    fn extract<'a>(&'a self, _request: ExtractionRequest) -> GenBoxFuture<'a, Result<ExtractionOutput, GenerationError>> {
        Box::pin(async move {
            let attempt = self.attempts.fetch_add(1, Ordering::SeqCst) + 1;
            if attempt < 3 {
                Err(GenerationError::new(
                    GenerationErrorKind::Timeout,
                    "injected extraction attempt failure",
                ))
            } else {
                Ok(self.output.clone())
            }
        })
    }
}

struct TestEntityEmbedder;

impl EmbeddingProvider for TestEntityEmbedder {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move {
            Ok(texts.iter().map(|_| vec![0.1f32; 2048]).collect())
        })
    }

    fn model_id(&self) -> &str {
        "text-embedding-3-small"
    }
}

struct D04FailingEmbedder;

impl EmbeddingProvider for D04FailingEmbedder {
    fn get_embeddings<'a>(
        &'a self,
        _texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move { Err("injected embedding failure".to_string()) })
    }
}

// ---------------------------------------------------------------------------
// Task 1 Tests: Ingestion Document Hierarchy and Context Carry
// ---------------------------------------------------------------------------

#[tokio::test]
async fn ingest_span_hierarchy_covers_document_stages() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_ingest_hierarchy");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-ingest-hierarchy");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);

    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(TestEntityEmbedder),
        make_test_extraction_generator(),
        shutdown_rx,
        inert_rebuild_tx(),
        RebuildTriggerLinks::default(),
    );

    let doc_id = Uuid::new_v4().to_string();
    sender
        .send(IngestionJob::new(
            doc_id.clone(),
            "sample.md".into(),
            b"# Title\n\nThis is a sufficiently long body of text for testing chunking and entity extraction.".to_vec(),
            HashMap::new(),
        ))
        .await
        .unwrap();
    drop(sender);
    worker.await.unwrap();

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let ingest_span = spans.iter().find(|s| s.name == "ingest_document").expect("ingest_document span");
    let index_span = spans.iter().find(|s| s.name == "index_document").expect("index_document span");
    let chunk_span = spans.iter().find(|s| s.name == "chunk_document").expect("chunk_document span");
    let embed_span = spans.iter().find(|s| s.name == "embed_document").expect("embed_document span");
    let persist_span = spans.iter().find(|s| s.name == "persist_document").expect("persist_document span");

    assert_eq!(index_span.parent_span_id, ingest_span.span_context.span_id());
    assert_eq!(chunk_span.parent_span_id, index_span.span_context.span_id());
    assert_eq!(embed_span.parent_span_id, index_span.span_context.span_id());
    assert_eq!(persist_span.parent_span_id, index_span.span_context.span_id());

    let trace_id = ingest_span.span_context.trace_id();
    assert_eq!(index_span.span_context.trace_id(), trace_id);
    assert_eq!(chunk_span.span_context.trace_id(), trace_id);
    assert_eq!(embed_span.span_context.trace_id(), trace_id);
    assert_eq!(persist_span.span_context.trace_id(), trace_id);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn ingest_graph_extraction_is_inside_the_document_trace() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_ingest_graph");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-ingest-graph");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);

    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(TestEntityEmbedder),
        make_test_extraction_generator(),
        shutdown_rx,
        inert_rebuild_tx(),
        RebuildTriggerLinks::default(),
    );

    let doc_id = Uuid::new_v4().to_string();
    sender
        .send(IngestionJob::new(
            doc_id.clone(),
            "graph.md".into(),
            b"# Graph Header\n\nAlice knows Bob and works on the database pipeline every day.".to_vec(),
            HashMap::new(),
        ))
        .await
        .unwrap();
    drop(sender);
    worker.await.unwrap();

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let ingest_span = spans.iter().find(|s| s.name == "ingest_document").expect("ingest_document span");
    let graph_span = spans.iter().find(|s| s.name == "graph_extraction").expect("graph_extraction span");

    assert_eq!(graph_span.parent_span_id, ingest_span.span_context.span_id());
    assert_eq!(graph_span.span_context.trace_id(), ingest_span.span_context.trace_id());

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn ingest_admission_context_crosses_the_queue() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_admission_queue");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-admission-queue");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);

    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(TestEntityEmbedder),
        make_test_extraction_generator(),
        shutdown_rx,
        inert_rebuild_tx(),
        RebuildTriggerLinks::default(),
    );

    let doc_id = Uuid::new_v4().to_string();
    let job = IngestionJob::new(
        doc_id.clone(),
        "trace_doc.md".into(),
        b"# Content\n\nTesting admission context propagation across tokio queue.".to_vec(),
        HashMap::new(),
    )
    .with_trace_parent(PINNED_TRACEPARENT);

    sender.send(job).await.unwrap();
    drop(sender);
    worker.await.unwrap();

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let ingest_span = spans.iter().find(|s| s.name == "ingest_document").expect("ingest_document span");
    let trace_id_hex = format!("{:032x}", ingest_span.span_context.trace_id());
    assert_eq!(trace_id_hex, PINNED_TRACE_ID_HEX);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn ingest_recovered_job_starts_a_new_root() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_recovered_root");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-recovered-root");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);

    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(TestEntityEmbedder),
        make_test_extraction_generator(),
        shutdown_rx,
        inert_rebuild_tx(),
        RebuildTriggerLinks::default(),
    );

    let doc_id = Uuid::new_v4().to_string();
    let job = IngestionJob::new(
        doc_id.clone(),
        "staged.md".into(),
        b"# Content\n\nRecovered staged job with no trace parent.".to_vec(),
        HashMap::new(),
    );
    assert!(job.trace_parent.is_none());

    sender.send(job).await.unwrap();
    drop(sender);
    worker.await.unwrap();

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let ingest_span = spans.iter().find(|s| s.name == "ingest_document").expect("ingest_document span");
    assert_eq!(ingest_span.parent_span_id, SpanId::INVALID);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn ingest_failure_branch_records_error_status() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_failure_status");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-failure-status");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);

    let boundary = FaultingReplacementMutationBoundary::new(ReplacementMutation::StagingDelete);
    let worker = spawn_worker_with_boundary(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(D04FailingEmbedder),
        make_test_extraction_generator(),
        Arc::new(boundary),
        shutdown_rx,
        inert_rebuild_tx(),
        RebuildTriggerLinks::default(),
    );

    let doc_id = Uuid::new_v4().to_string();
    let job = IngestionJob::new(
        doc_id.clone(),
        "fail.md".into(),
        b"# Content\n\nFailing embedder document.".to_vec(),
        HashMap::new(),
    );

    sender.send(job).await.unwrap();
    drop(sender);
    worker.await.unwrap();

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let ingest_span = spans.iter().find(|s| s.name == "ingest_document").expect("ingest_document span");
    assert!(matches!(ingest_span.status, opentelemetry::trace::Status::Error { .. }));

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn ingest_spans_carry_no_document_content() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_no_content");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-no-content");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);

    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(TestEntityEmbedder),
        make_test_extraction_generator(),
        shutdown_rx,
        inert_rebuild_tx(),
        RebuildTriggerLinks::default(),
    );

    let doc_id = Uuid::new_v4().to_string();
    let sensitive_content = "CONFIDENTIAL_PATIENT_RECORDS_DO_NOT_LEAK";
    let filename = "secret_report.pdf";
    sender
        .send(IngestionJob::new(
            doc_id.clone(),
            filename.into(),
            format!("# Header\n\n{sensitive_content}").into_bytes(),
            HashMap::new(),
        ))
        .await
        .unwrap();
    drop(sender);
    worker.await.unwrap();

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    assert!(!spans.is_empty());
    for span in &spans {
        for kv in &span.attributes {
            let val_str = kv.value.to_string();
            assert!(!val_str.contains(sensitive_content), "span {} leaked raw document text", span.name);
            assert!(!val_str.contains(filename), "span {} leaked filename", span.name);
        }
    }

    let _ = std::fs::remove_dir_all(path);
}

use crate::ingest::REBUILD_TEST_MUTEX;

// ---------------------------------------------------------------------------
// Task 2 Tests: Observable Index Rebuild with Trigger Links
// ---------------------------------------------------------------------------

#[tokio::test]
async fn index_rebuild_span_records_generation_transition() {
    let _lock = REBUILD_TEST_MUTEX.lock().await;
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_rebuild_transition");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-rebuild-trans");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let service = configured_service(
        &database,
        EffectiveRagSettings::default(),
        Arc::new(FakeEmbedder),
        test_fake_generator(),
        Arc::new(crate::rerank::NoOpReranker::new()),
    )
    .await;

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let (rebuild_tx, rebuild_rx) = watch::channel(0u64);
    let trigger_links = RebuildTriggerLinks::default();

    let debounce_task = spawn_rebuild_debounce_task(
        rebuild_rx,
        shutdown_rx,
        service.database.clone(),
        service.corpus_store.clone(),
        service.effective_settings.retrieval.bm25.clone(),
        Duration::from_millis(50),
        trigger_links,
    );

    rebuild_tx.send_modify(|v| *v += 1);
    tokio::time::sleep(Duration::from_millis(150)).await;
    shutdown_tx.send(true).unwrap();
    let _ = debounce_task.await;

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let rebuild_span = spans.iter().find(|s| s.name == "index_rebuild").expect("index_rebuild span");
    assert_eq!(rebuild_span.status, opentelemetry::trace::Status::Ok);

    let find_attr = |key: &str| -> Option<String> {
        rebuild_span.attributes.iter().find(|kv| kv.key.as_str() == key).map(|kv| kv.value.to_string())
    };

    assert!(find_attr("lancet.index.generation_before").is_some());
    assert!(find_attr("lancet.index.generation_after").is_some());
    assert_eq!(find_attr("lancet.index.rebuild.degraded").as_deref(), Some("false"));

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn index_rebuild_span_records_degraded_outcome() {
    let _lock = REBUILD_TEST_MUTEX.lock().await;
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_rebuild_degraded");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-rebuild-degraded");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let service = configured_service(
        &database,
        EffectiveRagSettings::default(),
        Arc::new(FakeEmbedder),
        test_fake_generator(),
        Arc::new(crate::rerank::NoOpReranker::new()),
    )
    .await;

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let (rebuild_tx, rebuild_rx) = watch::channel(0u64);
    let trigger_links = RebuildTriggerLinks::default();

    let debounce_task = spawn_rebuild_debounce_task(
        rebuild_rx,
        shutdown_rx,
        service.database.clone(),
        service.corpus_store.clone(),
        service.effective_settings.retrieval.bm25.clone(),
        Duration::from_millis(50),
        trigger_links,
    );

    arm_rebuild_fail_next();
    rebuild_tx.send_modify(|v| *v += 1);
    tokio::time::sleep(Duration::from_millis(150)).await;
    shutdown_tx.send(true).unwrap();
    let _ = debounce_task.await;

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let rebuild_span = spans.iter().find(|s| s.name == "index_rebuild").expect("index_rebuild span");
    assert!(matches!(rebuild_span.status, opentelemetry::trace::Status::Error { .. }));

    let find_attr = |key: &str| -> Option<String> {
        rebuild_span.attributes.iter().find(|kv| kv.key.as_str() == key).map(|kv| kv.value.to_string())
    };

    assert_eq!(find_attr("lancet.index.rebuild.degraded").as_deref(), Some("true"));

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn index_rebuild_span_links_all_triggering_documents() {
    let _lock = REBUILD_TEST_MUTEX.lock().await;
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_rebuild_links");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-rebuild-links");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let (rebuild_tx, rebuild_rx) = watch::channel(0u64);
    let trigger_links = RebuildTriggerLinks::default();

    let service = configured_service(
        &database,
        EffectiveRagSettings::default(),
        Arc::new(TestEntityEmbedder),
        test_fake_generator(),
        Arc::new(crate::rerank::NoOpReranker::new()),
    )
    .await;

    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(TestEntityEmbedder),
        make_test_extraction_generator(),
        shutdown_rx.clone(),
        rebuild_tx.clone(),
        trigger_links.clone(),
    );

    let debounce_task = spawn_rebuild_debounce_task(
        rebuild_rx,
        shutdown_rx,
        service.database.clone(),
        service.corpus_store.clone(),
        service.effective_settings.retrieval.bm25.clone(),
        Duration::from_millis(1200),
        trigger_links,
    );

    let mut doc_ids = Vec::new();
    for i in 0..5 {
        let doc_id = Uuid::new_v4().to_string();
        doc_ids.push(doc_id.clone());
        sender
            .send(IngestionJob::new(
                doc_id,
                format!("doc_{i}.md"),
                format!("# Doc {i}\n\nTesting debounced index rebuild link aggregation.").into_bytes(),
                HashMap::new(),
            ))
            .await
            .unwrap();
    }

    for doc_id in &doc_ids {
        while !statuses.contains_key(doc_id)
            || statuses.get(doc_id).map(|s| s.status.clone()) != Some("completed".into())
        {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }

    tokio::time::sleep(Duration::from_millis(1500)).await;
    let _ = shutdown_tx.send(true);
    let _ = debounce_task.await;
    drop(sender);
    let _ = worker.await;

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let rebuild_span = spans.iter().find(|s| s.name == "index_rebuild").expect("index_rebuild span");
    assert_eq!(rebuild_span.links.len(), 5);

    let find_attr = |key: &str| -> Option<String> {
        rebuild_span.attributes.iter().find(|kv| kv.key.as_str() == key).map(|kv| kv.value.to_string())
    };
    assert_eq!(find_attr("lancet.index.rebuild.trigger_count").as_deref(), Some("5"));

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn index_rebuild_span_is_not_parented_to_a_document() {
    let _lock = REBUILD_TEST_MUTEX.lock().await;
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_rebuild_root");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-rebuild-root");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let service = configured_service(
        &database,
        EffectiveRagSettings::default(),
        Arc::new(FakeEmbedder),
        test_fake_generator(),
        Arc::new(crate::rerank::NoOpReranker::new()),
    )
    .await;

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let (rebuild_tx, rebuild_rx) = watch::channel(0u64);
    let trigger_links = RebuildTriggerLinks::default();

    let debounce_task = spawn_rebuild_debounce_task(
        rebuild_rx,
        shutdown_rx,
        service.database.clone(),
        service.corpus_store.clone(),
        service.effective_settings.retrieval.bm25.clone(),
        Duration::from_millis(50),
        trigger_links,
    );

    rebuild_tx.send_modify(|v| *v += 1);
    tokio::time::sleep(Duration::from_millis(150)).await;
    shutdown_tx.send(true).unwrap();
    let _ = debounce_task.await;

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let rebuild_span = spans.iter().find(|s| s.name == "index_rebuild").expect("index_rebuild span");
    assert_eq!(rebuild_span.parent_span_id, SpanId::INVALID);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn index_rebuild_trigger_buffer_is_drained_per_rebuild() {
    let _lock = REBUILD_TEST_MUTEX.lock().await;
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_rebuild_drain");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-rebuild-drain");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let (rebuild_tx, rebuild_rx) = watch::channel(0u64);
    let trigger_links = RebuildTriggerLinks::default();

    let service = configured_service(
        &database,
        EffectiveRagSettings::default(),
        Arc::new(TestEntityEmbedder),
        test_fake_generator(),
        Arc::new(crate::rerank::NoOpReranker::new()),
    )
    .await;

    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(TestEntityEmbedder),
        make_test_extraction_generator(),
        shutdown_rx.clone(),
        rebuild_tx.clone(),
        trigger_links.clone(),
    );

    let debounce_task = spawn_rebuild_debounce_task(
        rebuild_rx,
        shutdown_rx,
        service.database.clone(),
        service.corpus_store.clone(),
        service.effective_settings.retrieval.bm25.clone(),
        Duration::from_millis(500),
        trigger_links,
    );

    // Ingest 2 jobs for first rebuild
    let mut first_ids = Vec::new();
    for i in 0..2 {
        let doc_id = Uuid::new_v4().to_string();
        first_ids.push(doc_id.clone());
        sender
            .send(IngestionJob::new(
                doc_id,
                format!("first_batch_{i}.md"),
                format!("# Heading\n\nFirst batch content {i}").into_bytes(),
                HashMap::new(),
            ))
            .await
            .unwrap();
    }

    for doc_id in &first_ids {
        while !statuses.contains_key(doc_id)
            || statuses.get(doc_id).map(|s| s.status.clone()) != Some("completed".into())
        {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }

    tokio::time::sleep(Duration::from_millis(700)).await;

    // Ingest 1 job for second rebuild
    let second_id = Uuid::new_v4().to_string();
    sender
        .send(IngestionJob::new(
            second_id.clone(),
            "second_batch_0.md".into(),
            b"# Heading\n\nSecond batch content".to_vec(),
            HashMap::new(),
        ))
        .await
        .unwrap();

    while !statuses.contains_key(&second_id)
        || statuses.get(&second_id).map(|s| s.status.clone()) != Some("completed".into())
    {
        tokio::time::sleep(Duration::from_millis(10)).await;
    }

    tokio::time::sleep(Duration::from_millis(700)).await;
    let _ = shutdown_tx.send(true);
    let _ = debounce_task.await;
    drop(sender);
    let _ = worker.await;

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let rebuild_spans: Vec<_> = spans.iter().filter(|s| s.name == "index_rebuild").collect();
    assert_eq!(rebuild_spans.len(), 2);
    assert_eq!(rebuild_spans[0].links.len(), 2);
    assert_eq!(rebuild_spans[1].links.len(), 1);

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// Task 3 Tests: Graph Extraction Leaf Spans
// ---------------------------------------------------------------------------

#[tokio::test]
async fn extraction_attempt_span_per_llm_attempt() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_extraction_attempt");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let attempts = Arc::new(AtomicUsize::new(0));
    let generator = RetryFailingExtractionGenerator {
        attempts: attempts.clone(),
        output: ExtractionOutput {
            entities: vec![ExtractedEntity {
                name: "Alpha".into(),
                entity_type: "concept".into(),
            }],
            relations: vec![],
        },
    };

    let req = ExtractionRequest {
        chunk_id: "chunk-01".into(),
        document_id: "doc-01".into(),
        chunk_text: "Alpha is a concept analyzed here.".into(),
    };

    let res = extract_with_retry(&generator, req).await;
    assert!(res.is_ok());
    assert_eq!(attempts.load(Ordering::SeqCst), 3);

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let attempt_spans: Vec<_> = spans.iter().filter(|s| s.name == "extraction_attempt").collect();
    assert_eq!(attempt_spans.len(), 3);

    let find_attr = |s: &opentelemetry_sdk::trace::SpanData, key: &str| -> Option<String> {
        s.attributes.iter().find(|kv| kv.key.as_str() == key).map(|kv| kv.value.to_string())
    };

    assert_eq!(find_attr(attempt_spans[0], "attempt").as_deref(), Some("1"));
    assert_eq!(find_attr(attempt_spans[0], "outcome").as_deref(), Some("call_failed"));

    assert_eq!(find_attr(attempt_spans[1], "attempt").as_deref(), Some("2"));
    assert_eq!(find_attr(attempt_spans[1], "outcome").as_deref(), Some("call_failed"));

    assert_eq!(find_attr(attempt_spans[2], "attempt").as_deref(), Some("3"));
    assert_eq!(find_attr(attempt_spans[2], "outcome").as_deref(), Some("ok"));
}

#[tokio::test]
async fn extraction_leaf_spans_nest_under_graph_extraction() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_extraction_leaves");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-extraction-leaves");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);

    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(TestEntityEmbedder),
        make_test_extraction_generator(),
        shutdown_rx,
        inert_rebuild_tx(),
        RebuildTriggerLinks::default(),
    );

    let doc_id = Uuid::new_v4().to_string();
    sender
        .send(IngestionJob::new(
            doc_id.clone(),
            "graph_leaves.md".into(),
            b"# Header\n\nAlice knows Bob and works with Charlie on graph extraction pipelines.".to_vec(),
            HashMap::new(),
        ))
        .await
        .unwrap();
    drop(sender);
    worker.await.unwrap();

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let graph_span = spans.iter().find(|s| s.name == "graph_extraction").expect("graph_extraction span");
    let attempt_span = spans.iter().find(|s| s.name == "extraction_attempt").expect("extraction_attempt span");
    let lookup_span = spans.iter().find(|s| s.name == "graph_entity_lookup").expect("graph_entity_lookup span");
    let embed_span = spans.iter().find(|s| s.name == "entity_name_embedding").expect("entity_name_embedding span");
    let persist_span = spans.iter().find(|s| s.name == "graph_entity_persist").expect("graph_entity_persist span");

    let graph_id = graph_span.span_context.span_id();
    assert_eq!(attempt_span.parent_span_id, graph_id);
    assert_eq!(lookup_span.parent_span_id, graph_id);
    assert_eq!(embed_span.parent_span_id, graph_id);
    assert_eq!(persist_span.parent_span_id, graph_id);

    let trace_id = graph_span.span_context.trace_id();
    assert_eq!(attempt_span.span_context.trace_id(), trace_id);
    assert_eq!(lookup_span.span_context.trace_id(), trace_id);
    assert_eq!(embed_span.span_context.trace_id(), trace_id);
    assert_eq!(persist_span.span_context.trace_id(), trace_id);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn graph_io_leaf_spans_wrap_real_lancedb_calls() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_graph_io");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-graph-io");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);

    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(TestEntityEmbedder),
        make_test_extraction_generator(),
        shutdown_rx,
        inert_rebuild_tx(),
        RebuildTriggerLinks::default(),
    );

    sender
        .send(IngestionJob::new(
            Uuid::new_v4().to_string(),
            "graph_io.md".into(),
            b"# Header\n\nAlice knows Bob and works with Charlie on database systems.".to_vec(),
            HashMap::new(),
        ))
        .await
        .unwrap();
    drop(sender);
    worker.await.unwrap();

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let lookup_span = spans.iter().find(|s| s.name == "graph_entity_lookup").expect("graph_entity_lookup span");
    let persist_span = spans.iter().find(|s| s.name == "graph_entity_persist").expect("graph_entity_persist span");

    let find_attr = |s: &opentelemetry_sdk::trace::SpanData, key: &str| -> Option<String> {
        s.attributes.iter().find(|kv| kv.key.as_str() == key).map(|kv| kv.value.to_string())
    };

    assert_eq!(find_attr(lookup_span, "db.system").as_deref(), Some("lancedb"));
    assert_eq!(find_attr(lookup_span, "db.operation").as_deref(), Some("select"));
    assert!(find_attr(lookup_span, "lancet.graph.known_entity_count").is_some());

    assert_eq!(find_attr(persist_span, "db.system").as_deref(), Some("lancedb"));
    assert_eq!(find_attr(persist_span, "db.operation").as_deref(), Some("mutate"));
    assert!(find_attr(persist_span, "lancet.graph.prior_entity_edges").is_some());
    assert!(find_attr(persist_span, "lancet.graph.written_entity_edges").is_some());

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn extraction_leaf_spans_carry_no_content() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_extraction_no_content");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-extraction-no-content");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);

    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(TestEntityEmbedder),
        make_test_extraction_generator(),
        shutdown_rx,
        inert_rebuild_tx(),
        RebuildTriggerLinks::default(),
    );

    let doc_id = Uuid::new_v4().to_string();
    let sensitive_text = "SECRET_PATIENT_DIAGNOSIS_DATA";
    sender
        .send(IngestionJob::new(
            doc_id.clone(),
            "diag.md".into(),
            format!("# Diagnosis\n\nAlice diagnosed {sensitive_text} with doctor Bob.").into_bytes(),
            HashMap::new(),
        ))
        .await
        .unwrap();
    drop(sender);
    worker.await.unwrap();

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let leaf_names: HashSet<&str> = [
        "extraction_attempt",
        "graph_entity_lookup",
        "entity_name_embedding",
        "graph_entity_persist",
    ]
    .into_iter()
    .collect();

    for span in spans.iter().filter(|s| leaf_names.contains(s.name.as_ref())) {
        for kv in &span.attributes {
            let val = kv.value.to_string();
            assert!(!val.contains(sensitive_text), "leaf span {} leaked chunk/content text", span.name);
            assert!(!val.contains("Alice"), "leaf span {} leaked entity name", span.name);
            assert!(!val.contains("Bob"), "leaf span {} leaked entity name", span.name);
            assert!(!val.contains("document_id ="), "leaf span {} leaked SQL predicate", span.name);
        }
    }

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn extraction_leaf_spans_absent_when_extraction_is_skipped() {
    crate::telemetry::ensure_propagators();

    let (exporter, mut rx, _rx_shutdown) = new_test_exporter();
    let tracer_provider = SdkTracerProvider::builder()
        .with_simple_exporter(exporter)
        .build();
    let tracer = tracer_provider.tracer("test_extraction_skipped");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);
    let subscriber = tracing_subscriber::Registry::default().with(otel_layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let path = database_path("telem-extraction-skipped");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);

    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(TestEntityEmbedder),
        make_test_extraction_generator(),
        shutdown_rx,
        inert_rebuild_tx(),
        RebuildTriggerLinks::default(),
    );

    // Below MIN_CHUNK_CONTENT_LENGTH (40 bytes)
    sender
        .send(IngestionJob::new(
            Uuid::new_v4().to_string(),
            "short.md".into(),
            b"tiny".to_vec(),
            HashMap::new(),
        ))
        .await
        .unwrap();
    drop(sender);
    worker.await.unwrap();

    let _ = tracer_provider.force_flush();

    let mut spans = Vec::new();
    while let Ok(span) = rx.try_recv() {
        spans.push(span);
    }

    let graph_span = spans.iter().find(|s| s.name == "graph_extraction");
    assert!(graph_span.is_some(), "graph_extraction span is always created");

    let attempt_spans: Vec<_> = spans.iter().filter(|s| s.name == "extraction_attempt").collect();
    let embed_spans: Vec<_> = spans.iter().filter(|s| s.name == "entity_name_embedding").collect();

    assert!(attempt_spans.is_empty(), "expected 0 extraction_attempt spans for skipped chunks");
    assert!(embed_spans.is_empty(), "expected 0 entity_name_embedding spans when no entities extracted");

    let _ = std::fs::remove_dir_all(path);
}
