use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
};

use engine::pb::lancet;
use engine::pb::lancet::v1::*;
use super::*;

pub mod workflow_phase5;

use arrow_array::{Array, BinaryArray, Int64Array, StringArray};
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase};
use tokio::sync::Notify;

const REQUIRED_EFFECTIVE_RAG_KEYS: &[&str] = &[
    "engine.retrieval.candidate_limit",
    "engine.retrieval.final_limit",
    "engine.retrieval.query_max_bytes",
    "engine.retrieval.max_document_ids",
    "engine.retrieval.max_content_types",
    "engine.retrieval.vector_weight",
    "engine.retrieval.bm25_weight",
    "engine.retrieval.graph_weight",
    "engine.retrieval.rrf_k",
    "engine.retrieval.evidence_token_budget",
    "engine.retrieval.excerpt_max_chars",
    "engine.retrieval.bm25.k1",
    "engine.retrieval.bm25.b",
    "engine.retrieval.bm25.content_boost",
    "engine.retrieval.bm25.title_boost",
    "engine.retrieval.bm25.section_boost",
    "engine.graph.seed_match_min_score",
    "engine.graph.max_hop_cap",
    "engine.workflow.reformulate_timeout_ms",
    "engine.workflow.query_embedding_timeout_ms",
    "engine.workflow.retrieve_timeout_ms",
    "engine.workflow.graph_operation_timeout_ms",
    "engine.workflow.graph_node_timeout_ms",
    "engine.workflow.prompt_timeout_ms",
    "engine.workflow.generation_node_timeout_ms",
    "openrouter.embedding_endpoint",
    "openrouter.embedding_model",
    "openrouter.generation_model",
    "openrouter.chat_endpoint",
    "openrouter.models_endpoint",
    "openrouter.generation_timeout_secs",
    "openrouter.temperature",
    "openrouter.top_p",
    "openrouter.max_output_tokens",
];

const REQUIRED_EFFECTIVE_RAG_ANNOTATIONS: &[(&str, &str)] = &[
    (
        "engine.retrieval.candidate_limit",
        "unit=count; range=1..=500",
    ),
    ("engine.retrieval.final_limit", "unit=count; range=1..=100"),
    (
        "engine.retrieval.query_max_bytes",
        "unit=UTF-8 bytes; range=1..=8192",
    ),
    (
        "engine.retrieval.max_document_ids",
        "unit=count; range=1..=100",
    ),
    (
        "engine.retrieval.max_content_types",
        "unit=count; range=1..=100",
    ),
    (
        "engine.retrieval.vector_weight",
        "unit=unitless; range=finite 0.0..=16.0 and combined >0",
    ),
    (
        "engine.retrieval.bm25_weight",
        "unit=unitless; range=finite 0.0..=16.0 and combined >0",
    ),
    (
        "engine.retrieval.graph_weight",
        "unit=unitless; range=finite 0.0..=16.0",
    ),
    (
        "engine.retrieval.rrf_k",
        "unit=rank constant; range=integer 1.0..=1000000.0",
    ),
    (
        "engine.retrieval.evidence_token_budget",
        "unit=tokens; range=>0",
    ),
    (
        "engine.retrieval.excerpt_max_chars",
        "unit=Unicode characters; range=>0",
    ),
    ("engine.retrieval.bm25.k1", "unit=unitless; range=finite >0"),
    (
        "engine.retrieval.bm25.b",
        "unit=unitless; range=finite 0..=1",
    ),
    (
        "engine.retrieval.bm25.content_boost",
        "unit=unitless; range=finite >0",
    ),
    (
        "engine.retrieval.bm25.title_boost",
        "unit=unitless; range=finite >0",
    ),
    (
        "engine.retrieval.bm25.section_boost",
        "unit=unitless; range=finite >0",
    ),
    (
        "engine.graph.seed_match_min_score",
        "unit=unitless; range=finite 0.0..=1.0",
    ),
    ("engine.graph.max_hop_cap", "unit=count; range=1..=3"),
    (
        "engine.workflow.reformulate_timeout_ms",
        "unit=milliseconds; range=>0",
    ),
    (
        "engine.workflow.query_embedding_timeout_ms",
        "unit=milliseconds; range=>0",
    ),
    (
        "engine.workflow.retrieve_timeout_ms",
        "unit=milliseconds; range=>0",
    ),
    (
        "engine.workflow.graph_operation_timeout_ms",
        "unit=milliseconds; range=>0",
    ),
    (
        "engine.workflow.graph_node_timeout_ms",
        "unit=milliseconds; range=>0",
    ),
    (
        "engine.workflow.prompt_timeout_ms",
        "unit=milliseconds; range=>0",
    ),
    (
        "engine.workflow.generation_node_timeout_ms",
        "unit=milliseconds; range=>0",
    ),
    (
        "openrouter.embedding_endpoint",
        "unit=URL string; range=nonblank",
    ),
    (
        "openrouter.embedding_model",
        "unit=provider identifier; range=nonblank",
    ),
    (
        "openrouter.generation_model",
        "unit=provider identifier; range=nonblank",
    ),
    (
        "openrouter.chat_endpoint",
        "unit=URL string; range=nonblank",
    ),
    (
        "openrouter.models_endpoint",
        "unit=URL string; range=nonblank",
    ),
    (
        "openrouter.generation_timeout_secs",
        "unit=seconds; range=>0",
    ),
    ("openrouter.temperature", "unit=unitless; range=finite 0..2"),
    ("openrouter.top_p", "unit=unitless; range=finite 0..1"),
    ("openrouter.max_output_tokens", "unit=tokens; range=>0"),
];

#[test]
fn config_example_matches_effective_rag_contract() {
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("engine manifest must have a repository parent");
    let config_path = repo_root.join("config/config.example.toml");
    let raw = fs::read_to_string(&config_path).expect("read operator configuration example");
    let settings: Settings = config::Config::builder()
        .add_source(config::File::from_str(&raw, config::FileFormat::Toml))
        .build()
        .expect("parse operator configuration example")
        .try_deserialize()
        .expect("deserialize operator configuration example through Settings");
    let effective = EffectiveRagSettings::try_from_settings(&settings)
        .expect("operator configuration example must construct EffectiveRagSettings");
    effective
        .validate()
        .expect("operator configuration example must validate");

    let lines: Vec<&str> = raw.lines().collect();
    let mut section = "";
    let mut observed = BTreeMap::<String, usize>::new();
    for (line_number, raw_line) in lines.iter().enumerate() {
        let line = raw_line.trim();
        if line.starts_with('[') && line.ends_with(']') {
            section = &line[1..line.len() - 1];
            continue;
        }
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((key, _value)) = line.split_once('=') else {
            continue;
        };
        let key = key.trim();
        let key_lower = key.to_ascii_lowercase();
        assert!(
            !key_lower.contains("api_key") && !key_lower.contains("secret"),
            "configuration example must not assign credentials: line {}",
            line_number + 1
        );
        if !matches!(
            section,
            "engine.retrieval" | "engine.retrieval.bm25" | "engine.graph" | "engine.workflow" | "openrouter"
        ) {
            continue;
        }
        let full_key = format!("{section}.{key}");
        *observed.entry(full_key.clone()).or_default() += 1;
        let marker = REQUIRED_EFFECTIVE_RAG_ANNOTATIONS
            .iter()
            .find_map(|(candidate, marker)| (*candidate == full_key).then_some(*marker))
            .unwrap_or_else(|| panic!("missing contract annotation mapping for {full_key}"));
        let previous_comment = line_number
            .checked_sub(1)
            .and_then(|index| lines.get(index))
            .map(|line| line.trim())
            .unwrap_or_default();
        assert!(
            previous_comment.starts_with('#') && previous_comment.contains(marker),
            "line {} for {full_key} must have adjacent annotation `{marker}`",
            line_number + 1
        );
    }

    let observed_keys: BTreeSet<String> = observed.keys().cloned().collect();
    let required_keys: BTreeSet<String> = REQUIRED_EFFECTIVE_RAG_KEYS
        .iter()
        .map(|key| (*key).to_owned())
        .collect();
    assert_eq!(
        observed_keys, required_keys,
        "effective RAG sections must contain exactly the documented key set"
    );
    for key in REQUIRED_EFFECTIVE_RAG_KEYS {
        assert_eq!(
            observed.get(*key).copied(),
            Some(1),
            "effective RAG key {key} must occur exactly once"
        );
    }
}

#[test]
fn config_workflow_timeout_overlays_match_contract() {
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("cargo manifest dir parent");

    let overlays = ["config.toml", "config.example.toml", "config.verify.toml"];
    let timeout_keys = [
        "reformulate_timeout_ms",
        "query_embedding_timeout_ms",
        "retrieve_timeout_ms",
        "graph_operation_timeout_ms",
        "graph_node_timeout_ms",
        "prompt_timeout_ms",
        "generation_node_timeout_ms",
    ];

    for overlay_name in overlays {
        let overlay_path = repo_root.join("config").join(overlay_name);
        let content = std::fs::read_to_string(&overlay_path)
            .unwrap_or_else(|_| panic!("read {}", overlay_path.display()));

        for key in timeout_keys {
            assert!(
                content.contains(key),
                "{} must contain workflow timeout key {}",
                overlay_name,
                key
            );
        }
    }
}

#[tokio::test]
async fn query_rag_stream() {
    let path = database_path("query-rag-stream-contract");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    stage_document(
        &database,
        &doc_id,
        b"# Stream Contract\nThis document tests query_rag_stream contract.",
    )
    .await;

    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();

    process_job(&job, &database, &FakeEmbedder).await.unwrap();

    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, Bm25Config::default())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, _receiver) = mpsc::channel(QUEUE_CAPACITY);

    let fake_gen = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Stream contract answer [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: EffectiveRagSettings::default(),
        generator: fake_gen.clone(),
        embedder: Arc::new(FakeEmbedder),
        database: database.clone(),
    };

    let req = QueryRagRequest {
        query: "Stream contract test".into(),
        session_id: "00000000-0000-4000-8000-000000000004".into(),
        filter: None,
    };

    let response_res = service.query_rag(tonic::Request::new(req)).await;
    assert!(response_res.is_ok());

    let mut stream = response_res.unwrap().into_inner();
    let mut event_count = 0;
    while let Some(item) = stream.next().await {
        assert!(item.is_ok());
        event_count += 1;
    }
    assert!(event_count > 0);

    let _ = std::fs::remove_dir_all(path);
}


struct FakeEmbedder;

impl EmbeddingProvider for FakeEmbedder {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move { Ok(texts.iter().map(|_| vec![0.25; 2048]).collect()) })
    }
}

#[derive(Debug, Clone, PartialEq)]
struct RecordedGenerationConfig {
    model: String,
    chat_endpoint: String,
    models_endpoint: String,
    timeout: std::time::Duration,
    temperature: f64,
    top_p: f64,
    max_output_tokens: usize,
}

struct RecordingEmbeddingProvider {
    configured_model: String,
    requests: Arc<std::sync::Mutex<Vec<Vec<String>>>>,
}

impl RecordingEmbeddingProvider {
    fn from_effective_settings(settings: &EffectiveRagSettings) -> Arc<Self> {
        client::OpenRouterEmbeddingConfig::new(
            settings.embedding_model.clone(),
            settings.embedding_endpoint.clone(),
        )
        .expect("effective embedding settings must construct the production config");
        Arc::new(Self {
            configured_model: settings.embedding_model.clone(),
            requests: Arc::new(std::sync::Mutex::new(Vec::new())),
        })
    }

    fn requests(&self) -> Vec<Vec<String>> {
        self.requests.lock().unwrap().clone()
    }
}

impl EmbeddingProvider for RecordingEmbeddingProvider {
    fn model_id(&self) -> &str {
        &self.configured_model
    }

    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move {
            self.requests.lock().unwrap().push(texts.to_vec());
            Ok(texts.iter().map(|_| vec![0.25; 2048]).collect())
        })
    }
}

struct RecordingGenerator {
    config: RecordedGenerationConfig,
    requests: Arc<std::sync::Mutex<Vec<generation::GenerationRequest>>>,
    response: generation::ModelOutput,
}

struct RecordingReranker {
    call_count: std::sync::atomic::AtomicUsize,
    inputs: std::sync::Mutex<Vec<Vec<retrieval::FusedCandidate>>>,
}

impl RecordingReranker {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            call_count: std::sync::atomic::AtomicUsize::new(0),
            inputs: std::sync::Mutex::new(Vec::new()),
        })
    }

    fn calls(&self) -> usize {
        self.call_count.load(std::sync::atomic::Ordering::Relaxed)
    }

    fn inputs(&self) -> Vec<Vec<retrieval::FusedCandidate>> {
        self.inputs.lock().unwrap().clone()
    }
}

impl rerank::Reranker for RecordingReranker {
    fn rerank<'a>(
        &'a self,
        mut candidates: Vec<retrieval::FusedCandidate>,
    ) -> BoxFuture<'a, Result<Vec<retrieval::FusedCandidate>, retrieval::RetrievalError>> {
        self.call_count
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        self.inputs.lock().unwrap().push(candidates.clone());
        Box::pin(async move {
            if candidates.len() > 1 {
                candidates.rotate_left(1);
            }
            Ok(candidates)
        })
    }
}

struct FailingReranker {
    call_count: std::sync::atomic::AtomicUsize,
}

impl FailingReranker {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            call_count: std::sync::atomic::AtomicUsize::new(0),
        })
    }

    fn calls(&self) -> usize {
        self.call_count.load(std::sync::atomic::Ordering::Relaxed)
    }
}

impl rerank::Reranker for FailingReranker {
    fn rerank<'a>(
        &'a self,
        _candidates: Vec<retrieval::FusedCandidate>,
    ) -> BoxFuture<'a, Result<Vec<retrieval::FusedCandidate>, retrieval::RetrievalError>> {
        self.call_count
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Box::pin(async {
            Err(retrieval::RetrievalError::new(
                retrieval::RetrievalErrorKind::Snapshot,
                "deterministic reranker failure",
            ))
        })
    }
}

impl RecordingGenerator {
    fn from_effective_settings(settings: &EffectiveRagSettings) -> Arc<Self> {
        generation::openrouter::OpenRouterGenerationConfig::from_effective_limits(
            settings.generation_model.clone(),
            settings.chat_endpoint.clone(),
            settings.model_metadata_endpoint.clone(),
            std::time::Duration::from_secs(settings.generation_timeout_secs),
            settings.temperature,
            settings.top_p,
            settings.grounding_limits_arc(),
        )
        .expect("effective generation settings must construct the production config");
        Arc::new(Self {
            config: RecordedGenerationConfig {
                model: settings.generation_model.clone(),
                chat_endpoint: settings.chat_endpoint.clone(),
                models_endpoint: settings.model_metadata_endpoint.clone(),
                timeout: std::time::Duration::from_secs(settings.generation_timeout_secs),
                temperature: settings.temperature,
                top_p: settings.top_p,
                max_output_tokens: settings.max_output_tokens as usize,
            },
            requests: Arc::new(std::sync::Mutex::new(Vec::new())),
            response: generation::ModelOutput {
                answer: "Configured answer [1].".into(),
                cited_evidence_ids: vec!["[1]".into()],
                answer_basis: generation::AnswerBasis::Retrieval,
                notices: vec![],
                warnings: vec![],
                usage: None,
            },
        })
    }

    fn requests(&self) -> Vec<generation::GenerationRequest> {
        self.requests.lock().unwrap().clone()
    }

    fn calls(&self) -> usize {
        self.requests.lock().unwrap().len()
    }
}

impl generation::Generator for RecordingGenerator {
    fn generate<'a>(
        &'a self,
        request: generation::GenerationRequest,
    ) -> BoxFuture<'a, Result<generation::ModelOutput, generation::GenerationError>> {
        Box::pin(async move {
            self.requests.lock().unwrap().push(request);
            Ok(self.response.clone())
        })
    }
}

struct BlockingEmbedder {
    started: Arc<Notify>,
    release: Arc<Notify>,
}

impl EmbeddingProvider for BlockingEmbedder {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move {
            self.started.notify_one();
            self.release.notified().await;
            Ok(texts.iter().map(|_| vec![0.25; 2048]).collect())
        })
    }
}

struct SingleBlockEmbedder {
    started: Arc<Notify>,
    release: Arc<Notify>,
    blocked: Arc<std::sync::atomic::AtomicBool>,
}

impl EmbeddingProvider for SingleBlockEmbedder {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move {
            if !self.blocked.swap(true, std::sync::atomic::Ordering::SeqCst) {
                self.started.notify_one();
                self.release.notified().await;
            }
            Ok(texts.iter().map(|_| vec![0.25; 2048]).collect())
        })
    }
}

struct FaultingReplacementMutationBoundary {
    fail_at: ReplacementMutation,
}

impl FaultingReplacementMutationBoundary {
    fn new(fail_at: ReplacementMutation) -> Self {
        Self { fail_at }
    }
}

impl ReplacementMutationBoundary for FaultingReplacementMutationBoundary {
    fn delete<'a>(
        &self,
        boundary: ReplacementMutation,
        table: &'a Table,
        predicate: &'a str,
    ) -> BoxFuture<'a, Result<(), String>> {
        if boundary == self.fail_at {
            return Box::pin(async move {
                Err(format!("injected replacement failure at {boundary:?}"))
            });
        }
        LanceDbReplacementMutationBoundary.delete(boundary, table, predicate)
    }

    fn add<'a>(
        &self,
        boundary: ReplacementMutation,
        table: &'a Table,
        batch: RecordBatch,
    ) -> BoxFuture<'a, Result<(), String>> {
        if boundary == self.fail_at {
            return Box::pin(async move {
                Err(format!("injected replacement failure at {boundary:?}"))
            });
        }
        LanceDbReplacementMutationBoundary.add(boundary, table, batch)
    }
}

fn database_path(test_name: &str) -> String {
    std::env::temp_dir()
        .join(format!("lancet-worker-{test_name}-{}", Uuid::new_v4()))
        .to_string_lossy()
        .into_owned()
}

async fn query_rows(table: &Table, predicate: &str) -> Vec<RecordBatch> {
    table
        .query()
        .only_if(predicate)
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap()
}

fn row_count(rows: &[RecordBatch]) -> usize {
    rows.iter().map(RecordBatch::num_rows).sum()
}

fn string_values(rows: &[RecordBatch], column: &str) -> BTreeSet<String> {
    rows.iter()
        .flat_map(|batch| {
            batch
                .column_by_name(column)
                .unwrap()
                .as_any()
                .downcast_ref::<StringArray>()
                .unwrap()
                .iter()
                .map(|value| value.unwrap().to_owned())
                .collect::<Vec<_>>()
        })
        .collect()
}

fn int64_values(rows: &[RecordBatch], column: &str) -> BTreeSet<i64> {
    rows.iter()
        .flat_map(|batch| {
            batch
                .column_by_name(column)
                .unwrap()
                .as_any()
                .downcast_ref::<Int64Array>()
                .unwrap()
                .iter()
                .map(|value| value.unwrap())
                .collect::<Vec<_>>()
        })
        .collect()
}

fn int32_values(rows: &[RecordBatch], column: &str) -> BTreeSet<i32> {
    rows.iter()
        .flat_map(|batch| {
            batch
                .column_by_name(column)
                .unwrap()
                .as_any()
                .downcast_ref::<Int32Array>()
                .unwrap()
                .iter()
                .map(|value| value.unwrap())
                .collect::<Vec<_>>()
        })
        .collect()
}

fn null_count(rows: &[RecordBatch], column: &str) -> usize {
    rows.iter()
        .map(|batch| batch.column_by_name(column).unwrap().null_count())
        .sum()
}

fn binary_hash(rows: &[RecordBatch], column: &str) -> u64 {
    let values = rows
        .iter()
        .flat_map(|batch| {
            batch
                .column_by_name(column)
                .unwrap()
                .as_any()
                .downcast_ref::<BinaryArray>()
                .unwrap()
                .iter()
                .map(|value| {
                    let mut hasher = DefaultHasher::new();
                    value.unwrap().hash(&mut hasher);
                    hasher.finish()
                })
                .collect::<Vec<_>>()
        })
        .collect::<Vec<_>>();
    assert_eq!(values.len(), 1);
    values[0]
}

#[derive(Debug, Eq, PartialEq)]
struct CanonicalState {
    raw_hash: u64,
    node_ids: BTreeSet<String>,
    node_indexes: BTreeSet<i32>,
    edge_ids: BTreeSet<String>,
    edge_sources: BTreeSet<String>,
    edge_targets: BTreeSet<String>,
    generations: BTreeSet<i64>,
    summary_null_count: usize,
}

async fn canonical_state(database: &DatabaseManager, document_id: &str) -> CanonicalState {
    let predicate = format!("document_id = '{}'", sql_string(document_id));
    let documents = query_rows(&database.documents_table().await.unwrap(), &predicate).await;
    let nodes = query_rows(&database.nodes_table().await.unwrap(), &predicate).await;
    let edges = query_rows(&database.edges_table().await.unwrap(), &predicate).await;
    assert_eq!(row_count(&documents), 1);
    CanonicalState {
        raw_hash: binary_hash(&documents, "raw_content"),
        node_ids: string_values(&nodes, "chunk_id"),
        node_indexes: int32_values(&nodes, "chunk_index"),
        edge_ids: string_values(&edges, "edge_id"),
        edge_sources: string_values(&edges, "source_node_id"),
        edge_targets: string_values(&edges, "target_node_id"),
        generations: int64_values(&nodes, "ingested_at"),
        summary_null_count: null_count(&edges, "summary"),
    }

}

async fn stage_document(database: &DatabaseManager, document_id: &str, raw_data: &[u8]) {
    stage_document_with_settings(
        database,
        document_id,
        "document.md",
        raw_data,
        "structure-aware",
        500,
        50,
    )
    .await;
}

async fn stage_document_with_settings(
    database: &DatabaseManager,
    document_id: &str,
    filename: &str,
    raw_data: &[u8],
    strategy: &str,
    size: usize,
    overlap: usize,
) {
    let table = database.staged_documents_table().await.unwrap();
    let batch = RecordBatch::try_new(
        table.schema().await.unwrap(),
        vec![
            Arc::new(StringArray::from(vec![document_id])),
            Arc::new(StringArray::from(vec![filename])),
            Arc::new(BinaryArray::from_vec(vec![raw_data])),
            Arc::new(StringArray::from(vec![strategy])),
            Arc::new(Int32Array::from(vec![i32::try_from(size).unwrap()])),
            Arc::new(Int32Array::from(vec![i32::try_from(overlap).unwrap()])),
            Arc::new(Int64Array::from(vec![1])),
        ],
    )
    .unwrap();
    table.add(batch).execute().await.unwrap();
}

fn test_extraction_generator() -> Arc<dyn crate::graph::extraction::ExtractionGenerator> {
    Arc::new(crate::graph::extraction::FakeExtractionGenerator::new(Ok(
        crate::graph::extraction::ExtractionOutput {
            entities: vec![],
            relations: vec![],
        },
    )))
}

fn configured_settings(lancedb_path: &str) -> Settings {
    Settings {
        engine: EngineSettings {
            grpc_addr: "127.0.0.1:0".into(),
            lancedb_path: lancedb_path.into(),
            retrieval: RetrievalConfigSettings {
                candidate_limit: 4,
                final_limit: 2,
                query_max_bytes: 4096,
                max_document_ids: 7,
                max_content_types: 5,
                vector_weight: 0.7,
                bm25_weight: 0.3,
                graph_weight: 1.0,
                rrf_k: 17.0,
                evidence_token_budget: 4096,
                excerpt_max_chars: 23,
                bm25: Bm25ConfigSettings {
                    k1: 1.7,
                    b: 0.65,
                    content_boost: 1.8,
                    title_boost: 3.5,
                    section_boost: 2.25,
                },
            },
            graph: GraphConfigSettings::default(),
        },
        openrouter: OpenRouterSettings {
            embedding_endpoint: "https://example.test/v1/embeddings".into(),
            embedding_model: "custom/embed-v11".into(),
            generation_model: "custom/generation-v7".into(),
            chat_endpoint: "https://example.test/v1/chat/completions".into(),
            model_metadata_endpoint: "https://example.test/v1/models".into(),
            generation_timeout_secs: 15,
            temperature: 0.2,
            top_p: 0.95,
            max_output_tokens: 1024,
        },
    }
}

async fn configured_service(
    database: &DatabaseManager,
    effective_settings: EffectiveRagSettings,
    embedder: Arc<dyn EmbeddingProvider>,
    generator: Arc<dyn generation::Generator>,
    reranker: Arc<dyn rerank::Reranker>,
) -> LancetServiceImpl {
    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, effective_settings.retrieval.bm25.clone())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, _receiver) = mpsc::channel(QUEUE_CAPACITY);
    LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        effective_settings,
        generator,
        embedder,
        reranker,
        database: database.clone(),
    }
}

#[tokio::test]
async fn replacement_documents_add_failure_rolls_back_and_retry_converges() {
    let path = database_path("documents-add-failure");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let document_id = Uuid::new_v4().to_string();
    let old_job = IngestionJob::new(
        document_id.clone(),
        "old.md".into(),
        b"# One\n\nfirst\n\n# Two\n\nsecond".to_vec(),
        HashMap::new(),
    );
    let (_, old_chunks) = chunk_ingestion_job(&old_job);
    let old_embeddings = vec![vec![0.25; 2048]; old_chunks.len()];
    replace_document(
        &database,
        &old_job,
        &old_chunks,
        &old_embeddings,
        client::EMBEDDING_MODEL,
    )
    .await
    .unwrap();
    stage_document(&database, &document_id, b"replacement staging row").await;
    let old_state = canonical_state(&database, &document_id).await;

    let replacement_job = IngestionJob::new(
        document_id.clone(),
        "replacement.md".into(),
        b"# Replacement\n\nnew content\n\n# Other\n\nmore content".to_vec(),
        HashMap::new(),
    );
    let (_, replacement_chunks) = chunk_ingestion_job(&replacement_job);
    let replacement_embeddings = vec![vec![0.75; 2048]; replacement_chunks.len()];
    let failure = FaultingReplacementMutationBoundary::new(ReplacementMutation::DocumentsAdd);

    let error = replace_document_with_faults(
        &database,
        &replacement_job,
        &replacement_chunks,
        &replacement_embeddings,
        client::EMBEDDING_MODEL,
        &failure,
    )
    .await
    .unwrap_err();
    assert!(error.contains("DocumentsAdd"));
    assert_eq!(canonical_state(&database, &document_id).await, old_state);
    assert_eq!(
        database
            .staged_documents_table()
            .await
            .unwrap()
            .count_rows(Some(format!("document_id = '{document_id}'")))
            .await
            .unwrap(),
        0
    );

    std::thread::sleep(std::time::Duration::from_millis(2));
    replace_document(
        &database,
        &replacement_job,
        &replacement_chunks,
        &replacement_embeddings,
        client::EMBEDDING_MODEL,
    )
    .await
    .unwrap();
    let replacement_state = canonical_state(&database, &document_id).await;
    assert_ne!(replacement_state.raw_hash, old_state.raw_hash);
    assert_ne!(replacement_state.generations, old_state.generations);
    assert_eq!(replacement_state.node_ids.len(), replacement_chunks.len());
    assert_eq!(replacement_state.generations.len(), 1);
    assert_eq!(
        database
            .staged_documents_table()
            .await
            .unwrap()
            .count_rows(Some(format!("document_id = '{document_id}'")))
            .await
            .unwrap(),
        0
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn replacement_failure_boundaries_preserve_prior_generation_and_retry_converges() {
    let boundaries = [
        ReplacementMutation::EdgesDelete,
        ReplacementMutation::NodesDelete,
        ReplacementMutation::DocumentsDelete,
        ReplacementMutation::DocumentsAdd,
        ReplacementMutation::NodesAdd,
        ReplacementMutation::EdgesAdd,
        ReplacementMutation::StagingDelete,
    ];
    for boundary in boundaries {
        let path = database_path(&format!("boundary-{boundary:?}"));
        let database = DatabaseManager::initialize(&path).await.unwrap();
        let document_id = Uuid::new_v4().to_string();
        let old_job = IngestionJob::new(
            document_id.clone(),
            "old.md".into(),
            b"# One\n\nfirst\n\n# Two\n\nsecond".to_vec(),
            HashMap::new(),
        );
        let (_, old_chunks) = chunk_ingestion_job(&old_job);
        let old_embeddings = vec![vec![0.25; 2048]; old_chunks.len()];
        replace_document(
            &database,
            &old_job,
            &old_chunks,
            &old_embeddings,
            client::EMBEDDING_MODEL,
        )
        .await
        .unwrap();
        stage_document(&database, &document_id, b"replacement staging row").await;
        let old_state = canonical_state(&database, &document_id).await;
        assert_eq!(old_state.edge_ids.len(), 3);
        assert_eq!(old_state.summary_null_count, old_state.edge_ids.len());


        let replacement_job = IngestionJob::new(
            document_id.clone(),
            "replacement.md".into(),
            b"# Three\n\nnew content\n\n# Four\n\nmore content".to_vec(),
            HashMap::new(),
        );
        let (_, replacement_chunks) = chunk_ingestion_job(&replacement_job);
        let replacement_embeddings = vec![vec![0.75; 2048]; replacement_chunks.len()];
        let failure = FaultingReplacementMutationBoundary::new(boundary);
        let error = replace_document_with_faults(
            &database,
            &replacement_job,
            &replacement_chunks,
            &replacement_embeddings,
            client::EMBEDDING_MODEL,
            &failure,
        )
        .await
        .unwrap_err();
        assert!(error.contains(&format!("{boundary:?}")));
        assert_eq!(canonical_state(&database, &document_id).await, old_state);
        let expected_staged_count = if boundary == ReplacementMutation::StagingDelete {
            1
        } else {
            0
        };
        assert_eq!(
            database
                .staged_documents_table()
                .await
                .unwrap()
                .count_rows(Some(format!("document_id = '{document_id}'")))
                .await
                .unwrap(),
            expected_staged_count
        );

        std::thread::sleep(std::time::Duration::from_millis(2));
        replace_document(
            &database,
            &replacement_job,
            &replacement_chunks,
            &replacement_embeddings,
            client::EMBEDDING_MODEL,
        )
        .await
        .unwrap();
        let current = canonical_state(&database, &document_id).await;
        let expected_indexes = (0..replacement_chunks.len())
            .map(|index| i32::try_from(index).unwrap())
            .collect::<BTreeSet<_>>();
        assert_ne!(current.raw_hash, old_state.raw_hash);
        assert_eq!(current.node_indexes, expected_indexes);
        assert_eq!(current.node_ids.len(), replacement_chunks.len());
        assert_eq!(current.edge_ids.len(), current.edge_sources.len());
        assert_eq!(current.edge_ids.len(), current.edge_targets.len());
        assert!(current.edge_sources.is_subset(&current.node_ids));
        assert!(current.edge_targets.is_subset(&current.node_ids));
        assert_eq!(current.generations.len(), 1);
        assert_eq!(current.summary_null_count, current.edge_ids.len());

        assert_eq!(
            database
                .staged_documents_table()
                .await
                .unwrap()
                .count_rows(Some(format!("document_id = '{document_id}'")))
                .await
                .unwrap(),
            0
        );
        let _ = std::fs::remove_dir_all(path);
    }
}

#[tokio::test]
async fn persisted_node_summary_is_arrow_null() {
    let path = database_path("summary-null");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let _repeated = DatabaseManager::initialize(&path).await.unwrap();
    let first_connection = lancedb::connect(&path).execute().await.unwrap();
    let second_connection = lancedb::connect(&path).execute().await.unwrap();
    assert_eq!(
        first_connection
            .open_table("communities")
            .execute()
            .await
            .unwrap()
            .count_rows(None)
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        second_connection
            .open_table("communities")
            .execute()
            .await
            .unwrap()
            .count_rows(None)
            .await
            .unwrap(),
        0
    );
    let empty_job = IngestionJob::new(
        Uuid::new_v4().to_string(),
        "empty.md".into(),
        Vec::new(),
        HashMap::new(),
    );
    let (_, empty_chunks) = chunk_ingestion_job(&empty_job);
    assert!(empty_chunks.is_empty());
    replace_document(
        &database,
        &empty_job,
        &empty_chunks,
        &[],
        client::EMBEDDING_MODEL,
    )
    .await
    .unwrap();
    let empty_predicate = format!("document_id = '{}'", sql_string(&empty_job.document_id));
    assert_eq!(
        database
            .documents_table()
            .await
            .unwrap()
            .count_rows(Some(empty_predicate.clone()))
            .await
            .unwrap(),
        1
    );
    assert_eq!(
        database
            .nodes_table()
            .await
            .unwrap()
            .count_rows(Some(empty_predicate.clone()))
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        database
            .edges_table()
            .await
            .unwrap()
            .count_rows(Some(empty_predicate))
            .await
            .unwrap(),
        0
    );
    let document_id = Uuid::new_v4().to_string();
    let job = IngestionJob::new(
        document_id,
        "summary.md".into(),
        b"# Summary\n\ncontent".to_vec(),
        HashMap::new(),
    );
    let (_, chunks) = chunk_ingestion_job(&job);
    let embeddings = vec![vec![0.25; 2048]; chunks.len()];
    replace_document(
        &database,
        &job,
        &chunks,
        &embeddings,
        client::EMBEDDING_MODEL,
    )
    .await
    .unwrap();
    let rows = query_rows(
        &database.edges_table().await.unwrap(),
        &format!("document_id = '{}'", sql_string(&job.document_id)),
    )
    .await;
    let summary = rows[0]
        .column_by_name("summary")
        .unwrap()
        .as_any()
        .downcast_ref::<StringArray>()
        .unwrap();
    assert_eq!(summary.null_count(), row_count(&rows));
    let summary_field = database
        .edges_table()
        .await
        .unwrap()
        .schema()
        .await
        .unwrap()
        .field_with_name("summary")
        .unwrap()
        .clone();
    assert!(summary_field.is_nullable());

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn worker_indexes_jobs_and_records_real_chunk_count() {
    let path = database_path("indexes");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);
    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(FakeEmbedder),
        test_extraction_generator(),
        shutdown_rx,
    );
    let document_id = Uuid::new_v4().to_string();
    sender
        .send(IngestionJob::new(
            document_id.clone(),
            "document.md".into(),
            b"# One\n\nfirst\n\n# Two\n\nsecond".to_vec(),
            HashMap::new(),
        ))
        .await
        .unwrap();
    drop(sender);
    worker.await.unwrap();
    let state = statuses.get(&document_id).unwrap();
    assert_eq!(state.status, "completed");
    assert_eq!(state.chunk_count, 4);
    drop(state);
    let nodes = database.nodes_table().await.unwrap();
    assert_eq!(nodes.count_rows(None).await.unwrap(), 4);
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn worker_replaces_existing_document_rows() {
    let path = database_path("replace");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);
    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(FakeEmbedder),
        test_extraction_generator(),
        shutdown_rx,
    );
    let document_id = Uuid::new_v4().to_string();
    for raw_data in [
        b"# One\n\nfirst\n\n# Two\n\nsecond".to_vec(),
        b"replacement".to_vec(),
    ] {
        sender
            .send(IngestionJob::new(
                document_id.clone(),
                "document.md".into(),
                raw_data,
                HashMap::new(),
            ))
            .await
            .unwrap();
    }
    drop(sender);
    worker.await.unwrap();

    let predicate = format!("document_id = '{document_id}'");
    assert_eq!(
        database
            .documents_table()
            .await
            .unwrap()
            .count_rows(Some(predicate.clone()))
            .await
            .unwrap(),
        1
    );
    assert_eq!(
        database
            .nodes_table()
            .await
            .unwrap()
            .count_rows(Some(predicate))
            .await
            .unwrap(),
        1
    );
    let state = statuses.get(&document_id).unwrap();
    assert_eq!(state.status, "completed");
    assert_eq!(state.chunk_count, 1);
    drop(state);
    let _ = std::fs::remove_dir_all(path);
}

struct FaultingSchemaFieldBoundary {
    fail_field: String,
    enabled: Arc<std::sync::atomic::AtomicBool>,
}

impl FaultingSchemaFieldBoundary {
    fn new(fail_field: &str) -> (Self, Arc<std::sync::atomic::AtomicBool>) {
        let enabled = Arc::new(std::sync::atomic::AtomicBool::new(false));
        (
            Self {
                fail_field: fail_field.to_owned(),
                enabled: enabled.clone(),
            },
            enabled,
        )
    }
}

impl ReplacementMutationBoundary for FaultingSchemaFieldBoundary {
    fn delete<'a>(
        &self,
        boundary: ReplacementMutation,
        table: &'a Table,
        predicate: &'a str,
    ) -> BoxFuture<'a, Result<(), String>> {
        LanceDbReplacementMutationBoundary.delete(boundary, table, predicate)
    }

    fn add<'a>(
        &self,
        boundary: ReplacementMutation,
        table: &'a Table,
        batch: RecordBatch,
    ) -> BoxFuture<'a, Result<(), String>> {
        LanceDbReplacementMutationBoundary.add(boundary, table, batch)
    }

    fn field_with_name<'a>(
        &self,
        schema: &'a arrow_schema::Schema,
        name: &str,
    ) -> Result<&'a arrow_schema::Field, String> {
        if name == self.fail_field && self.enabled.load(std::sync::atomic::Ordering::SeqCst) {
            return Err(format!(
                "validated nodes schema missing field {name}: injected schema field error"
            ));
        }
        LanceDbReplacementMutationBoundary.field_with_name(schema, name)
    }
}

#[tokio::test]
async fn schema_field_lookup_failure_rolls_back_and_worker_survives() {
    let path = database_path("schema-lookup-survival");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);

    let (boundary, fault_enabled) = FaultingSchemaFieldBoundary::new("page_start");

    let worker = spawn_worker_with_boundary(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(FakeEmbedder),
        test_extraction_generator(),
        Arc::new(boundary),
        shutdown_rx,
    );

    let document_id_1 = Uuid::new_v4().to_string();
    let job_1 = IngestionJob::new(
        document_id_1.clone(),
        "job1.md".into(),
        b"# One\n\nfirst section".to_vec(),
        HashMap::new(),
    );
    sender.send(job_1).await.unwrap();

    while !statuses.contains_key(&document_id_1)
        || statuses.get(&document_id_1).unwrap().status == "processing"
    {
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    assert_eq!(statuses.get(&document_id_1).unwrap().status, "completed");

    let initial_state = canonical_state(&database, &document_id_1).await;

    // Enable the schema field lookup fault for the replacement job
    fault_enabled.store(true, std::sync::atomic::Ordering::SeqCst);

    let replacement_job = IngestionJob::new(
        document_id_1.clone(),
        "job2.md".into(),
        b"# Replacement\n\nreplacement section".to_vec(),
        HashMap::new(),
    );
    stage_document(&database, &document_id_1, b"replacement staging row").await;
    sender.send(replacement_job).await.unwrap();

    while statuses.get(&document_id_1).unwrap().status == "processing"
        || statuses.get(&document_id_1).unwrap().status == "completed"
    {
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }

    let status_2 = statuses.get(&document_id_1).unwrap().clone();
    assert_eq!(status_2.status, "failed");
    assert!(
        status_2
            .error_message
            .contains("validated nodes schema missing field page_start"),
        "unexpected error message: {}",
        status_2.error_message
    );

    assert_eq!(
        canonical_state(&database, &document_id_1).await,
        initial_state
    );
    assert_eq!(
        database
            .staged_documents_table()
            .await
            .unwrap()
            .count_rows(Some(format!("document_id = '{document_id_1}'")))
            .await
            .unwrap(),
        0
    );

    // Disable fault for subsequent job
    fault_enabled.store(false, std::sync::atomic::Ordering::SeqCst);

    let document_id_3 = Uuid::new_v4().to_string();
    let job_3 = IngestionJob::new(
        document_id_3.clone(),
        "job3.md".into(),
        b"# Three\n\nthird document".to_vec(),
        HashMap::new(),
    );
    sender.send(job_3).await.unwrap();

    while !statuses.contains_key(&document_id_3)
        || statuses.get(&document_id_3).unwrap().status == "processing"
    {
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    assert_eq!(statuses.get(&document_id_3).unwrap().status, "completed");
    assert!(statuses.get(&document_id_3).unwrap().chunk_count > 0);

    drop(sender);
    worker.await.unwrap();
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn shutdown_waits_for_active_document_to_finish() {
    let path = database_path("shutdown");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let started = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database,
        Arc::new(BlockingEmbedder {
            started: started.clone(),
            release: release.clone(),
        }),
        test_extraction_generator(),
        shutdown_rx,
    );
    let document_id = Uuid::new_v4().to_string();
    sender
        .send(IngestionJob::new(
            document_id.clone(),
            "document.md".into(),
            b"active document".to_vec(),
            HashMap::new(),
        ))
        .await
        .unwrap();
    started.notified().await;
    shutdown_tx.send(true).unwrap();
    release.notify_one();
    worker.await.unwrap();

    assert_eq!(statuses.get(&document_id).unwrap().status, "completed");
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn bounded_queue_rejects_work_when_full() {
    let (sender, _receiver) = mpsc::channel(1);
    sender
        .try_send(IngestionJob::new(
            "one".into(),
            "one.txt".into(),
            vec![b'x'],
            HashMap::new(),
        ))
        .unwrap();
    assert!(sender
        .try_send(IngestionJob::new(
            "two".into(),
            "two.txt".into(),
            vec![b'y'],
            HashMap::new(),
        ))
        .is_err());
}

#[test]
fn json_forces_fixed_size_and_populates_token_counts() {
    let job = IngestionJob::new(
        "json".into(),
        "DATA.JSON".into(),
        br##"{"heading":"# not markdown"}"##.to_vec(),
        HashMap::from([
            ("chunk_strategy".into(), "structure-aware".into()),
            ("chunk_size".into(), "10".into()),
            ("chunk_overlap".into(), "2".into()),
        ]),
    );
    let (strategy, chunks) = chunk_ingestion_job(&job);
    assert_eq!(strategy, "fixed-size");
    assert!(chunks.len() > 1);
    assert!(chunks.iter().all(|chunk| chunk.section_path.is_none()));
    assert!(chunks.iter().all(|chunk| chunk.estimated_tokens > 0));
}

#[test]
fn empty_strategy_defaults_to_structure_aware() {
    let job = IngestionJob::new(
        "markdown".into(),
        "guide.md".into(),
        b"# Setup\n\nInstall it.".to_vec(),
        HashMap::new(),
    );
    let (strategy, chunks) = chunk_ingestion_job(&job);
    assert_eq!(strategy, "structure-aware");
    assert!(chunks
        .iter()
        .any(|chunk| chunk.section_path.as_deref() == Some("/Setup")));
}

#[test]
fn rejects_non_v4_document_ids() {
    assert!(validate_document_id("not-a-uuid").is_err());
    assert!(validate_document_id("00000000-0000-1000-8000-000000000000").is_err());
    assert!(validate_document_id(&Uuid::new_v4().to_string()).is_ok());
}

#[test]
fn chunk_metadata_contract_valid_custom_settings() {
    let metadata = HashMap::from([
        ("chunk_strategy".into(), "fixed-size".into()),
        ("chunk_size".into(), "800".into()),
        ("chunk_overlap".into(), "100".into()),
    ]);
    let settings = parse_chunk_settings(&metadata).unwrap();
    assert_eq!(
        settings,
        ChunkSettings {
            strategy: "fixed-size".into(),
            size: 800,
            overlap: 100,
        }
    );
    let job = IngestionJob::new(
        "doc-1".into(),
        "notes.txt".into(),
        b"some long content for chunking test".to_vec(),
        metadata,
    );
    let (strategy, chunks) = chunk_ingestion_job(&job);
    assert_eq!(strategy, "fixed-size");
    assert!(!chunks.is_empty());
}

#[test]
fn chunk_metadata_contract_invalid_metadata_rejected() {
    let missing_key = HashMap::from([("chunk_strategy".into(), "fixed-size".into())]);
    assert!(parse_chunk_settings(&missing_key).is_err());

    let invalid_strategy = HashMap::from([
        ("chunk_strategy".into(), "recursive".into()),
        ("chunk_size".into(), "500".into()),
        ("chunk_overlap".into(), "50".into()),
    ]);
    assert!(parse_chunk_settings(&invalid_strategy).is_err());

    let zero_size = HashMap::from([
        ("chunk_strategy".into(), "fixed-size".into()),
        ("chunk_size".into(), "0".into()),
        ("chunk_overlap".into(), "0".into()),
    ]);
    assert!(parse_chunk_settings(&zero_size).is_err());

    let overlap_too_large = HashMap::from([
        ("chunk_strategy".into(), "fixed-size".into()),
        ("chunk_size".into(), "500".into()),
        ("chunk_overlap".into(), "500".into()),
    ]);
    assert!(parse_chunk_settings(&overlap_too_large).is_err());
}

#[tokio::test]
async fn shutdown_drains_acknowledged_queue() {
    let path = database_path("shutdown-drain");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let started = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let blocked = Arc::new(std::sync::atomic::AtomicBool::new(false));

    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(SingleBlockEmbedder {
            started: started.clone(),
            release: release.clone(),
            blocked,
        }),
        test_extraction_generator(),
        shutdown_rx,
    );

    let doc_id_1 = Uuid::new_v4().to_string();
    let doc_id_2 = Uuid::new_v4().to_string();
    let doc_id_3 = Uuid::new_v4().to_string();

    let job_1 = IngestionJob::new(
        doc_id_1.clone(),
        "doc1.md".into(),
        b"active job 1".to_vec(),
        HashMap::new(),
    );
    let job_2 = IngestionJob::new(
        doc_id_2.clone(),
        "doc2.md".into(),
        b"queued job 2".to_vec(),
        HashMap::new(),
    );
    let job_3 = IngestionJob::new(
        doc_id_3.clone(),
        "doc3.md".into(),
        b"queued job 3".to_vec(),
        HashMap::new(),
    );

    stage_document(&database, &doc_id_1, b"active job 1").await;
    stage_document(&database, &doc_id_2, b"queued job 2").await;
    stage_document(&database, &doc_id_3, b"queued job 3").await;

    statuses.insert(doc_id_1.clone(), IngestionStatus::queued());
    statuses.insert(doc_id_2.clone(), IngestionStatus::queued());
    statuses.insert(doc_id_3.clone(), IngestionStatus::queued());

    sender.send(job_1).await.unwrap();
    sender.send(job_2).await.unwrap();
    sender.send(job_3).await.unwrap();

    started.notified().await;
    shutdown_tx.send(true).unwrap();

    release.notify_one();
    worker.await.unwrap();

    assert_eq!(statuses.get(&doc_id_1).unwrap().status, "completed");
    assert_eq!(statuses.get(&doc_id_2).unwrap().status, "completed");
    assert_eq!(statuses.get(&doc_id_3).unwrap().status, "completed");

    let staged_table = database.staged_documents_table().await.unwrap();
    assert_eq!(staged_table.count_rows(None).await.unwrap(), 0);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn startup_recovery_processes_staged_document() {
    let path = database_path("startup-recovery");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    stage_document_with_settings(
        &database,
        &doc_id,
        "custom_file.md",
        b"# Heading\n\nCustom content for recovery test.",
        "fixed-size",
        200,
        20,
    )
    .await;

    drop(database);

    let reopened_db = DatabaseManager::initialize(&path).await.unwrap();
    let recovered_jobs = read_staged_jobs(&reopened_db).await.unwrap();
    assert_eq!(recovered_jobs.len(), 1);

    let job = &recovered_jobs[0];
    assert_eq!(job.document_id, doc_id);
    assert_eq!(job.filename, "custom_file.md");
    assert_eq!(job.chunk_settings.strategy, "fixed-size");
    assert_eq!(job.chunk_settings.size, 200);
    assert_eq!(job.chunk_settings.overlap, 20);

    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);

    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        reopened_db.clone(),
        Arc::new(FakeEmbedder),
        test_extraction_generator(),
        shutdown_rx,
    );

    statuses.insert(job.document_id.clone(), IngestionStatus::queued());
    sender
        .send(recovered_jobs.into_iter().next().unwrap())
        .await
        .unwrap();
    drop(sender);

    worker.await.unwrap();

    assert_eq!(statuses.get(&doc_id).unwrap().status, "completed");
    let staged_table = reopened_db.staged_documents_table().await.unwrap();
    assert_eq!(staged_table.count_rows(None).await.unwrap(), 0);

    let _ = std::fs::remove_dir_all(path);
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

#[tokio::test]
async fn startup_recovery_exceeds_queue_capacity_without_deadlock() {
    let path = database_path("exceeds-capacity");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let job_count = QUEUE_CAPACITY + 1;
    let mut staged_ids = Vec::new();
    for _ in 0..job_count {
        let doc_id = Uuid::new_v4().to_string();
        staged_ids.push(doc_id.clone());
        stage_document(&database, &doc_id, b"# Test\n\nContent").await;
    }

    let result = tokio::time::timeout(std::time::Duration::from_secs(60), async {
        let statuses = Arc::new(DashMap::new());
        let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
        let (_shutdown_tx, shutdown_rx) = watch::channel(false);

        let worker = spawn_worker(
            receiver,
            statuses.clone(),
            database.clone(),
            Arc::new(FakeEmbedder),
            test_extraction_generator(),
            shutdown_rx,
        );

        let staged_jobs = read_staged_jobs(&database).await.unwrap();
        assert_eq!(staged_jobs.len(), job_count);

        for job in staged_jobs {
            statuses.insert(job.document_id.clone(), IngestionStatus::queued());
            sender.send(job).await.unwrap();
        }

        drop(sender);
        worker.await.unwrap();

        for id in &staged_ids {
            let state = statuses.get(id).unwrap();
            assert_eq!(state.status, "completed");
        }
        let remaining_staged = database
            .staged_documents_table()
            .await
            .unwrap()
            .count_rows(None)
            .await
            .unwrap();
        assert_eq!(remaining_staged, 0);
    })
    .await;

    assert!(
        result.is_ok(),
        "startup recovery timed out (deadlock detected)"
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn startup_recovery_fails_when_worker_exits() {
    let path = database_path("worker-exits-replay");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();
    stage_document(&database, &doc_id, b"# Test\n\nContent").await;

    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    drop(receiver);

    let staged_jobs = read_staged_jobs(&database).await.unwrap();
    assert_eq!(staged_jobs.len(), 1);

    let send_res = sender.send(staged_jobs.into_iter().next().unwrap()).await;
    assert!(send_res.is_err(), "replay send must fail when worker exits");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn staging_read_error_is_unavailable() {
    let path = database_path("staging-read-error");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let doc_id = Uuid::new_v4().to_string();
    stage_document(&database, &doc_id, b"staged content").await;

    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, _receiver) = mpsc::channel(QUEUE_CAPACITY);

    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, Bm25Config::default())
        .await
        .unwrap();
    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: EffectiveRagSettings::default(),
        generator: Arc::new(generation::FakeGenerator::new(Ok(
            generation::ModelOutput {
                answer: "Fake answer".into(),
                cited_evidence_ids: vec![],
                answer_basis: generation::AnswerBasis::Retrieval,
                notices: vec![],
                warnings: vec![],
                usage: None,
            },
        ))),
        embedder: Arc::new(FakeEmbedder),
        database: database.clone(),
    };

    let _ = std::fs::remove_dir_all(&path);

    let err = service
        .get_ingestion_status(tonic::Request::new(GetIngestionStatusRequest {
            document_id: doc_id,
        }))
        .await
        .unwrap_err();

    assert_eq!(err.code(), tonic::Code::Unavailable);
}

#[tokio::test]
async fn staging_delete_failure_remains_replayable() {
    let path = database_path("delete-failure-replayable");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();
    stage_document(&database, &doc_id, b"# Document\n\nContent").await;

    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);

    let boundary = FaultingReplacementMutationBoundary::new(ReplacementMutation::StagingDelete);
    let worker = spawn_worker_with_boundary(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(D04FailingEmbedder),
        test_extraction_generator(),
        Arc::new(boundary),
        shutdown_rx,
    );

    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    sender.send(job).await.unwrap();
    drop(sender);
    worker.await.unwrap();

    assert!(!statuses.contains_key(&doc_id) || statuses.get(&doc_id).unwrap().status != "failed");

    let staged_count = database
        .staged_documents_table()
        .await
        .unwrap()
        .count_rows(Some(format!("document_id = '{doc_id}'")))
        .await
        .unwrap();
    assert_eq!(staged_count, 1);

    let table = database.staged_documents_table().await.unwrap();
    let (dummy_tx, _dummy_rx) = mpsc::channel(QUEUE_CAPACITY);
    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, Bm25Config::default())
        .await
        .unwrap();
    let service = LancetServiceImpl {
        table,
        statuses: statuses.clone(),
        queue: dummy_tx,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: EffectiveRagSettings::default(),
        generator: Arc::new(generation::FakeGenerator::new(Ok(
            generation::ModelOutput {
                answer: "Fake answer".into(),
                cited_evidence_ids: vec![],
                answer_basis: generation::AnswerBasis::Retrieval,
                notices: vec![],
                warnings: vec![],
                usage: None,
            },
        ))),
        embedder: Arc::new(FakeEmbedder),
        database: database.clone(),
    };

    let status_res = service
        .get_ingestion_status(tonic::Request::new(GetIngestionStatusRequest {
            document_id: doc_id.clone(),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(status_res.status, "queued");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn embedding_failure_restart_converges_cross_store() {
    let path = database_path("embedding-fail-restart-converges");
    let doc_id = Uuid::new_v4().to_string();

    {
        let db1 = DatabaseManager::initialize(&path).await.unwrap();
        stage_document(&db1, &doc_id, b"# Restart Test\n\nContent").await;
        let statuses = Arc::new(DashMap::new());
        let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
        let (_shutdown_tx, shutdown_rx) = watch::channel(false);

        let boundary = FaultingReplacementMutationBoundary::new(ReplacementMutation::StagingDelete);
        let worker = spawn_worker_with_boundary(
            receiver,
            statuses.clone(),
            db1.clone(),
            Arc::new(D04FailingEmbedder),
            test_extraction_generator(),
            Arc::new(boundary),
            shutdown_rx,
        );

        let job = read_staged_jobs(&db1)
            .await
            .unwrap()
            .into_iter()
            .next()
            .unwrap();
        sender.send(job).await.unwrap();
        drop(sender);
        worker.await.unwrap();

        let staged_count = db1
            .staged_documents_table()
            .await
            .unwrap()
            .count_rows(Some(format!("document_id = '{doc_id}'")))
            .await
            .unwrap();
        assert_eq!(staged_count, 1);

        let docs_count = db1
            .documents_table()
            .await
            .unwrap()
            .count_rows(Some(format!("document_id = '{doc_id}'")))
            .await
            .unwrap();
        assert_eq!(docs_count, 0);
    }

    {
        let db2 = DatabaseManager::initialize(&path).await.unwrap();
        let statuses = Arc::new(DashMap::new());
        let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
        let (_shutdown_tx, shutdown_rx) = watch::channel(false);

        let worker = spawn_worker(
            receiver,
            statuses.clone(),
            db2.clone(),
            Arc::new(FakeEmbedder),
            test_extraction_generator(),
            shutdown_rx,
        );

        let staged_jobs = read_staged_jobs(&db2).await.unwrap();
        assert_eq!(staged_jobs.len(), 1);

        for job in staged_jobs {
            statuses.insert(job.document_id.clone(), IngestionStatus::queued());
            sender.send(job).await.unwrap();
        }

        drop(sender);
        worker.await.unwrap();

        assert_eq!(statuses.get(&doc_id).unwrap().status, "completed");

        let staged_count = db2
            .staged_documents_table()
            .await
            .unwrap()
            .count_rows(Some(format!("document_id = '{doc_id}'")))
            .await
            .unwrap();
        assert_eq!(staged_count, 0);

        let docs_count = db2
            .documents_table()
            .await
            .unwrap()
            .count_rows(Some(format!("document_id = '{doc_id}'")))
            .await
            .unwrap();
        assert_eq!(docs_count, 1);

        let state = canonical_state(&db2, &doc_id).await;
        assert_eq!(state.generations.len(), 1);
    }

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn d04_cross_runtime_grpc_fixture() {
    let flag = std::env::var("LANCET_RUN_D04_FIXTURE").unwrap_or_default();
    if flag != "1" && flag != "true" {
        return;
    }

    let doc_id = std::env::var("LANCET_D04_DOC_ID").expect("LANCET_D04_DOC_ID required");
    let listen_addr =
        std::env::var("LANCET_D04_LISTEN_ADDR").expect("LANCET_D04_LISTEN_ADDR required");
    let lancedb_path =
        std::env::var("LANCET_D04_LANCEDB_PATH").expect("LANCET_D04_LANCEDB_PATH required");
    let mode = std::env::var("LANCET_D04_MODE").expect("LANCET_D04_MODE required");
    let stop_file = std::env::var("LANCET_D04_STOP_FILE").expect("LANCET_D04_STOP_FILE required");

    let database = DatabaseManager::initialize(&lancedb_path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (shutdown_tx, shutdown_rx) = watch::channel(false);

    let worker = if mode == "fail-delete" {
        stage_document(
            &database,
            &doc_id,
            b"# Fail Delete\n\nCross-runtime D04 test content",
        )
        .await;
        let boundary = FaultingReplacementMutationBoundary::new(ReplacementMutation::StagingDelete);
        let w = spawn_worker_with_boundary(
            receiver,
            statuses.clone(),
            database.clone(),
            Arc::new(D04FailingEmbedder),
            test_extraction_generator(),
            Arc::new(boundary),
            shutdown_rx,
        );

        let staged_jobs = read_staged_jobs(&database).await.unwrap();
        for job in staged_jobs {
            statuses.insert(job.document_id.clone(), IngestionStatus::queued());
            sender.send(job).await.unwrap();
        }

        while statuses.contains_key(&doc_id) {
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }

        let staged_count = database
            .staged_documents_table()
            .await
            .unwrap()
            .count_rows(Some(format!("document_id = '{doc_id}'")))
            .await
            .unwrap();
        assert_eq!(staged_count, 1);
        let docs_count = database
            .documents_table()
            .await
            .unwrap()
            .count_rows(Some(format!("document_id = '{doc_id}'")))
            .await
            .unwrap();
        assert_eq!(docs_count, 0);
        w
    } else if mode == "restart-success" {
        let w = spawn_worker(
            receiver,
            statuses.clone(),
            database.clone(),
            Arc::new(FakeEmbedder),
            test_extraction_generator(),
            shutdown_rx,
        );

        let staged_jobs = read_staged_jobs(&database).await.unwrap();
        for job in staged_jobs {
            statuses.insert(job.document_id.clone(), IngestionStatus::queued());
            sender.send(job).await.unwrap();
        }

        loop {
            if let Some(st) = statuses.get(&doc_id) {
                if st.status == "completed" {
                    break;
                }
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
        let staged_count = database
            .staged_documents_table()
            .await
            .unwrap()
            .count_rows(Some(format!("document_id = '{doc_id}'")))
            .await
            .unwrap();
        assert_eq!(staged_count, 0);
        w
    } else {
        panic!("unknown LANCET_D04_MODE: {mode}");
    };

    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, Bm25Config::default())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: EffectiveRagSettings::default(),
        generator: Arc::new(generation::FakeGenerator::new(Ok(
            generation::ModelOutput {
                answer: "Fake answer".into(),
                cited_evidence_ids: vec![],
                answer_basis: generation::AnswerBasis::Retrieval,
                notices: vec![],
                warnings: vec![],
                usage: None,
            },
        ))),
        embedder: Arc::new(FakeEmbedder),
        database: database.clone(),
    };

    let addr: std::net::SocketAddr = listen_addr.parse().unwrap();
    let stop_path = std::path::PathBuf::from(&stop_file);

    let (grpc_shutdown_tx, grpc_shutdown_rx) = tokio::sync::oneshot::channel::<()>();

    tokio::spawn(async move {
        loop {
            if stop_path.exists() {
                let _ = grpc_shutdown_tx.send(());
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        }
    });

    Server::builder()
        .add_service(LancetServiceServer::new(service))
        .serve_with_shutdown(addr, async move {
            let _ = grpc_shutdown_rx.await;
            let _ = shutdown_tx.send(true);
        })
        .await
        .unwrap();

    let _ = worker.await;
}

#[tokio::test]
async fn status_falls_back_to_staged_document() {
    let path = database_path("status-fallback");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    stage_document(&database, &doc_id, b"staged raw content").await;

    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, Bm25Config::default())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, _receiver) = mpsc::channel(QUEUE_CAPACITY);

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: EffectiveRagSettings::default(),
        generator: Arc::new(generation::FakeGenerator::new(Ok(
            generation::ModelOutput {
                answer: "Fake answer".into(),
                cited_evidence_ids: vec![],
                answer_basis: generation::AnswerBasis::Retrieval,
                notices: vec![],
                warnings: vec![],
                usage: None,
            },
        ))),
        embedder: Arc::new(FakeEmbedder),
        database: database.clone(),
    };

    let status_res = service
        .get_ingestion_status(tonic::Request::new(GetIngestionStatusRequest {
            document_id: doc_id.clone(),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(status_res.document_id, doc_id);
    assert_eq!(status_res.status, "queued");
    assert_eq!(status_res.chunk_count, 0);

    let missing_id = Uuid::new_v4().to_string();
    let not_found_err = service
        .get_ingestion_status(tonic::Request::new(GetIngestionStatusRequest {
            document_id: missing_id,
        }))
        .await
        .unwrap_err();

    assert_eq!(not_found_err.code(), tonic::Code::NotFound);

    let _ = std::fs::remove_dir_all(path);
}

#[test]
fn chunk_size_boundaries_are_engine_authoritative() {
    let valid_boundary = HashMap::from([
        ("chunk_strategy".into(), "fixed-size".into()),
        ("chunk_size".into(), "1048576".into()),
        ("chunk_overlap".into(), "100".into()),
    ]);
    let settings = parse_chunk_settings(&valid_boundary).unwrap();
    assert_eq!(settings.size, 1048576);

    let exceeded_boundary = HashMap::from([
        ("chunk_strategy".into(), "fixed-size".into()),
        ("chunk_size".into(), "1048577".into()),
        ("chunk_overlap".into(), "100".into()),
    ]);
    let err = parse_chunk_settings(&exceeded_boundary).unwrap_err();
    assert_eq!(err.code(), tonic::Code::InvalidArgument);

    let overflow_boundary = HashMap::from([
        ("chunk_strategy".into(), "fixed-size".into()),
        ("chunk_size".into(), "2147483648".into()),
        ("chunk_overlap".into(), "100".into()),
    ]);
    let err_overflow = parse_chunk_settings(&overflow_boundary).unwrap_err();
    assert_eq!(err_overflow.code(), tonic::Code::InvalidArgument);
}

async fn collect_query_rag_stream<S>(mut stream: S) -> Result<QueryRagResponse, tonic::Status>
where
    S: tokio_stream::Stream<Item = Result<engine::pb::lancet::v1::WorkflowEvent, tonic::Status>> + Unpin,
{
    let mut last_response = None;
    while let Some(res) = stream.next().await {
        let event = res?;
        if let Some(ref e) = event.event {
            match e {
                engine::pb::lancet::v1::workflow_event::Event::FinalAnswer(ref fa) => {
                    if let Some(ref resp) = fa.response {
                        last_response = Some(resp.clone());
                    }
                }
                engine::pb::lancet::v1::workflow_event::Event::WorkflowCompleted(ref wc) => {
                    if wc.success {
                        if let Some(ref resp) = wc.final_response {
                            last_response = Some(resp.clone());
                        }
                    } else {
                        let code = match engine::pb::lancet::v1::NodeErrorKind::try_from(wc.error_kind) {
                            Ok(engine::pb::lancet::v1::NodeErrorKind::Timeout) => tonic::Code::DeadlineExceeded,
                            Ok(engine::pb::lancet::v1::NodeErrorKind::Cancelled) => tonic::Code::Cancelled,
                            Ok(engine::pb::lancet::v1::NodeErrorKind::RetrievalFailed) => tonic::Code::Unavailable,
                            Ok(engine::pb::lancet::v1::NodeErrorKind::PromptAssemblyFailed) => tonic::Code::InvalidArgument,
                            _ => tonic::Code::Internal,
                        };
                        let mut status = tonic::Status::new(code, wc.error_message.clone());
                        if let Ok(sess_val) = tonic::metadata::MetadataValue::try_from(&event.session_id) {
                            status.metadata_mut().insert("x-lancet-session-id", sess_val);
                        }
                        if let Ok(corr_val) = tonic::metadata::MetadataValue::try_from(&event.trace_id) {
                            status.metadata_mut().insert("x-lancet-correlation-id", corr_val);
                        }
                        status.metadata_mut().insert(
                            "x-lancet-error-kind",
                            tonic::metadata::MetadataValue::from_static("retrieval_failed"),
                        );
                        return Err(status);
                    }
                }
                _ => {}
            }
        }
    }
    last_response.ok_or_else(|| tonic::Status::internal("stream ended without terminal response"))
}

async fn execute_query_rag(
    service: &LancetServiceImpl,
    req: QueryRagRequest,
) -> Result<QueryRagResponse, tonic::Status> {
    let stream_res = service.query_rag(tonic::Request::new(req)).await?;
    collect_query_rag_stream(stream_res.into_inner()).await
}

#[tokio::test]
async fn query_rag_tracer() {
    let path = database_path("query-rag-tracer");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    stage_document(
        &database,
        &doc_id,
        b"# Tracer Document\nThis is tracer document content for state-machine event streaming.",
    )
    .await;

    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();

    process_job(&job, &database, &FakeEmbedder).await.unwrap();

    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, Bm25Config::default())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, _receiver) = mpsc::channel(QUEUE_CAPACITY);

    let fake_gen = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Tracer answer [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: EffectiveRagSettings::default(),
        generator: fake_gen.clone(),
        embedder: Arc::new(FakeEmbedder),
        database: database.clone(),
    };

    let req = QueryRagRequest {
        query: "What is tracer document content?".into(),
        session_id: "00000000-0000-4000-8000-000000000002".into(),
        filter: None,
    };

    let response_res = service.query_rag(tonic::Request::new(req)).await;
    assert!(response_res.is_ok());

    let mut stream = response_res.unwrap().into_inner();
    let mut events = Vec::new();
    while let Some(item) = stream.next().await {
        let event = item.expect("Stream item should be Ok");
        events.push(event);
    }

    assert!(!events.is_empty(), "Stream should contain events");

    let event_types: Vec<_> = events
        .iter()
        .filter_map(|e| e.event.as_ref())
        .collect();

    let has_node_started = event_types.iter().any(|e| matches!(e, engine::pb::lancet::v1::workflow_event::Event::NodeStarted(_)));
    let has_node_completed = event_types.iter().any(|e| matches!(e, engine::pb::lancet::v1::workflow_event::Event::NodeCompleted(_)));
    let has_checkpoint = event_types.iter().any(|e| matches!(e, engine::pb::lancet::v1::workflow_event::Event::Checkpoint(_)));
    let has_completed = event_types.iter().any(|e| matches!(e, engine::pb::lancet::v1::workflow_event::Event::WorkflowCompleted(_)));

    assert!(has_node_started, "Must contain NodeStarted event");
    assert!(has_node_completed, "Must contain NodeCompleted event");
    assert!(has_checkpoint, "Must contain Checkpoint event");
    assert!(has_completed, "Must contain WorkflowCompleted event");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn query_rag_happy_path_service() {
    let path = database_path("query-rag-happy-path");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    stage_document(
        &database,
        &doc_id,
        b"# Lancet Architecture\n\nThe core Lancet architecture uses Rust for retrieval.",
    )
    .await;

    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();

    process_job(&job, &database, &FakeEmbedder).await.unwrap();

    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, Bm25Config::default())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, _receiver) = mpsc::channel(QUEUE_CAPACITY);

    let fake_gen = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Lancet uses Rust for retrieval [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: EffectiveRagSettings::default(),
        generator: fake_gen.clone(),
        embedder: Arc::new(FakeEmbedder),
        database: database.clone(),
    };

    let req = QueryRagRequest {
        query: "What language does Lancet use for retrieval?".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: None,
    };

    let response = execute_query_rag(&service, req).await.unwrap();

    assert_eq!(response.answer, "Lancet uses Rust for retrieval [1].");
    assert_eq!(response.session_id, "00000000-0000-4000-8000-000000000001");
    assert_eq!(
        response.answer_basis,
        lancet::v1::AnswerBasis::Retrieval as i32
    );
    assert_eq!(response.citations, vec!["[1]".to_string()]);
    assert_eq!(response.structured_citations.len(), 1);
    assert_eq!(response.structured_citations[0].document_id, doc_id);
    assert!(response.snapshot.is_some());
    let snap = response.snapshot.unwrap();
    assert!(!snap.result_hash.is_empty());
    assert_eq!(fake_gen.calls(), 1);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn configured_provider_settings_reach_query_requests() {
    let path = database_path("configured-provider-settings-reach-query");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let document_id = Uuid::new_v4().to_string();
    stage_document_with_settings(
        &database,
        &document_id,
        "configured.md",
        b"# Configured Retrieval\n\nThe configured provider query reaches every consumer.",
        "structure-aware",
        500,
        50,
    )
    .await;

    let settings = configured_settings(&path);
    let effective_settings = EffectiveRagSettings::try_from_settings(&settings).unwrap();
    let embedder = RecordingEmbeddingProvider::from_effective_settings(&effective_settings);
    let generator = RecordingGenerator::from_effective_settings(&effective_settings);
    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    process_job(&job, &database, embedder.as_ref())
        .await
        .unwrap();

    let service = configured_service(
        &database,
        effective_settings.clone(),
        embedder.clone(),
        generator.clone(),
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;
    let response = execute_query_rag(
        &service,
        QueryRagRequest {
            query: "configured provider query".into(),
            session_id: "00000000-0000-4000-8000-000000000111".into(),
            filter: None,
        },
    )
    .await
    .unwrap();

    assert_eq!(embedder.requests().len(), 2);
    assert_eq!(
        embedder.requests()[1],
        vec!["configured provider query".to_string()]
    );
    assert_eq!(generator.calls(), 1);
    let generation_request = &generator.requests()[0];
    assert_eq!(generation_request.question, "configured provider query");
    assert!(!generation_request.evidence.is_empty());
    assert_eq!(generator.config.model, effective_settings.generation_model);
    assert_eq!(
        generator.config.chat_endpoint,
        effective_settings.chat_endpoint
    );
    assert_eq!(
        generator.config.models_endpoint,
        effective_settings.model_metadata_endpoint
    );
    assert_eq!(
        generator.config.timeout,
        std::time::Duration::from_secs(effective_settings.generation_timeout_secs)
    );
    assert_eq!(generator.config.temperature, effective_settings.temperature);
    assert_eq!(generator.config.top_p, effective_settings.top_p);
    assert_eq!(
        generator.config.max_output_tokens,
        usize::try_from(effective_settings.max_output_tokens).unwrap()
    );

    let snapshot = response.snapshot.unwrap();
    assert_eq!(snapshot.candidate_limit, 4);
    assert_eq!(snapshot.final_limit, 2);
    assert_eq!(snapshot.vector_weight, 0.7);
    assert_eq!(snapshot.bm25_weight, 0.3);
    assert_eq!(snapshot.rrf_k, 17);
    assert_eq!(snapshot.embedding_model, "custom/embed-v11");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn configured_embedding_identity_persists_and_reports() {
    let path = database_path("configured-embedding-identity");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let document_id = Uuid::new_v4().to_string();
    stage_document(
        &database,
        &document_id,
        b"# Identity\n\nConfigured identity content.",
    )
    .await;

    let settings = configured_settings(&path);
    let effective_settings = EffectiveRagSettings::try_from_settings(&settings).unwrap();
    let embedder = RecordingEmbeddingProvider::from_effective_settings(&effective_settings);
    let generator = RecordingGenerator::from_effective_settings(&effective_settings);
    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    process_job(&job, &database, embedder.as_ref())
        .await
        .unwrap();

    let nodes = database.nodes_table().await.unwrap();
    let rows = query_rows(
        &nodes,
        &format!("document_id = '{}'", sql_string(&document_id)),
    )
    .await;
    assert_eq!(
        string_values(&rows, "embedding_model"),
        BTreeSet::from([embedder.configured_model.clone()])
    );

    let service = configured_service(
        &database,
        effective_settings.clone(),
        embedder.clone(),
        generator,
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;
    let response = execute_query_rag(
        &service,
        QueryRagRequest {
            query: "configured identity content".into(),
            session_id: "00000000-0000-4000-8000-000000000112".into(),
            filter: None,
        },
    )
    .await
    .unwrap();

    assert_eq!(
        embedder.configured_model,
        effective_settings.embedding_model
    );
    assert_eq!(
        response.snapshot.unwrap().embedding_model,
        embedder.configured_model
    );

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn configured_bm25_and_evidence_settings_reach_query() {
    let path = database_path("configured-bm25-and-evidence");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let document_id = Uuid::new_v4().to_string();
    stage_document_with_settings(
        &database,
        &document_id,
        "bm25.md",
        "needle configured lexical evidence with Unicode π and enough text to truncate safely."
            .as_bytes(),
        "structure-aware",
        500,
        50,
    )
    .await;

    let settings = configured_settings(&path);
    let effective_settings = EffectiveRagSettings::try_from_settings(&settings).unwrap();
    let embedder = RecordingEmbeddingProvider::from_effective_settings(&effective_settings);
    let generator = RecordingGenerator::from_effective_settings(&effective_settings);
    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    process_job(&job, &database, embedder.as_ref())
        .await
        .unwrap();

    let service = configured_service(
        &database,
        effective_settings.clone(),
        embedder,
        generator.clone(),
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;
    let response = execute_query_rag(
        &service,
        QueryRagRequest {
            query: "needle configured lexical evidence".into(),
            session_id: "00000000-0000-4000-8000-000000000113".into(),
            filter: None,
        },
    )
    .await
    .unwrap();

    let request = &generator.requests()[0];
    assert_eq!(request.evidence.len(), 1);
    assert!(request.evidence[0].text.contains("needle"));
    assert_eq!(response.structured_citations.len(), 1);
    assert_eq!(response.structured_citations[0].excerpt.chars().count(), 23);
    assert!(response.structured_citations[0].is_truncated);
    assert_eq!(response.snapshot.as_ref().unwrap().candidate_limit, 4);
    assert_eq!(response.snapshot.as_ref().unwrap().final_limit, 2);
    assert_eq!(response.snapshot.as_ref().unwrap().rrf_k, 17);
    assert_eq!(
        service.effective_settings.retrieval.bm25,
        effective_settings.retrieval.bm25
    );

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn configured_rag_settings_drive_service() {
    let path = database_path("rag-settings-drive-service");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    stage_document(
        &database,
        &doc_id,
        b"# Custom Settings\n\nContent for testing custom RAG configuration.",
    )
    .await;

    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();

    process_job(&job, &database, &FakeEmbedder).await.unwrap();

    let settings = Settings {
        engine: EngineSettings {
            grpc_addr: "[::1]:50051".into(),
            lancedb_path: path.clone(),
            retrieval: RetrievalConfigSettings {
                candidate_limit: 16,
                final_limit: 4,
                query_max_bytes: 4096,
                max_document_ids: 50,
                max_content_types: 8,
                vector_weight: 0.8,
                bm25_weight: 0.2,
                graph_weight: 1.0,
                rrf_k: 30.0,
                evidence_token_budget: 4096,
                excerpt_max_chars: 128,
                bm25: Bm25ConfigSettings {
                    k1: 1.5,
                    b: 0.8,
                    content_boost: 1.5,
                    title_boost: 3.0,
                    section_boost: 2.0,
                },
            },
            graph: GraphConfigSettings::default(),
        },
        openrouter: OpenRouterSettings {
            embedding_endpoint: "https://example.com/api/v1/embeddings".into(),
            embedding_model: "custom/embed-v1".into(),
            generation_model: "custom/gen-v1".into(),
            chat_endpoint: "https://example.com/api/v1/chat/completions".into(),
            model_metadata_endpoint: "https://example.com/api/v1/models".into(),
            generation_timeout_secs: 15,
            temperature: 0.2,
            top_p: 0.9,
            max_output_tokens: 1024,
        },
    };

    let effective_settings = EffectiveRagSettings::try_from_settings(&settings).unwrap();
    let configured_embedder =
        RecordingEmbeddingProvider::from_effective_settings(&effective_settings);
    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, effective_settings.retrieval.bm25.clone())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, _receiver) = mpsc::channel(QUEUE_CAPACITY);

    let fake_gen = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Custom answer [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: effective_settings.clone(),
        generator: fake_gen,
        embedder: configured_embedder,
        database: database.clone(),
    };

    let req = QueryRagRequest {
        query: "What is testing custom configuration?".into(),
        session_id: "00000000-0000-4000-8000-000000000002".into(),
        filter: None,
    };

    let response = execute_query_rag(&service, req).await.unwrap();

    assert!(response.snapshot.is_some());
    let snap = response.snapshot.unwrap();
    assert_eq!(snap.candidate_limit, 16);
    assert_eq!(snap.final_limit, 4);
    assert_eq!(snap.vector_weight, 0.8);
    assert_eq!(snap.bm25_weight, 0.2);
    assert_eq!(snap.rrf_k, 30);
    assert_eq!(snap.embedding_model, "custom/embed-v1");
    assert_eq!(snap.index_generation, effective_settings.index_generation);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn configured_evidence_token_budget_is_exact() {
    let path = database_path("evidence-token-budget-exact");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let long_text = "This is a very long section content designed to test character-based citation excerpt truncation in the structured citation payload. ".repeat(10);
    stage_document(&database, &doc_id, long_text.as_bytes()).await;

    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();

    process_job(&job, &database, &FakeEmbedder).await.unwrap();

    let mut settings = Settings::default();
    settings.engine.retrieval.evidence_token_budget = 8192;
    settings.engine.retrieval.excerpt_max_chars = 30;

    let effective_settings = EffectiveRagSettings::try_from_settings(&settings).unwrap();
    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, effective_settings.retrieval.bm25.clone())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, _receiver) = mpsc::channel(QUEUE_CAPACITY);

    let fake_gen = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Answer with excerpt test [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings,
        generator: fake_gen,
        embedder: Arc::new(FakeEmbedder),
        database: database.clone(),
    };

    let req = QueryRagRequest {
        query: "Excerpt test query?".into(),
        session_id: "00000000-0000-4000-8000-000000000003".into(),
        filter: None,
    };

    let response = execute_query_rag(&service, req).await.unwrap();

    assert_eq!(response.structured_citations.len(), 1);
    let citation = &response.structured_citations[0];
    assert_eq!(citation.excerpt.chars().count(), 30);
    assert!(citation.is_truncated);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn service_index_generation_is_opaque_and_stable() {
    let path1 = database_path("opaque-stable-gen-1");
    let database1 = DatabaseManager::initialize(&path1).await.unwrap();
    let doc_id1 = Uuid::new_v4().to_string();
    stage_document(&database1, &doc_id1, b"# Test Document 1\n\nContent 1").await;
    let job1 = read_staged_jobs(&database1)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    process_job(&job1, &database1, &FakeEmbedder).await.unwrap();

    let effective_settings1 = EffectiveRagSettings::default();
    let nodes1 = database1.nodes_table().await.unwrap();
    let bm25_index1 = Bm25Index::from_table(&nodes1, effective_settings1.retrieval.bm25.clone())
        .await
        .unwrap();
    let table1 = database1.staged_documents_table().await.unwrap();
    let (sender1, _receiver1) = mpsc::channel(QUEUE_CAPACITY);
    let model_out1 = generation::ModelOutput {
        answer: "Answer 1 [1].".into(),
        cited_evidence_ids: vec!["[1]".into()],
        answer_basis: generation::AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        usage: None,
    };
    let fake_gen1 = Arc::new(generation::FakeGenerator::with_responses(vec![
        Ok(model_out1.clone()),
        Ok(model_out1),
    ]));

    let service1 = LancetServiceImpl {
        table: table1,
        statuses: Arc::new(DashMap::new()),
        queue: sender1,
        nodes: nodes1,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index1)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: effective_settings1,
        generator: fake_gen1,
        embedder: Arc::new(FakeEmbedder),
        database: database1.clone(),
    };

    let req1 = QueryRagRequest {
        query: "Query 1".into(),
        session_id: "00000000-0000-4000-8000-000000000004".into(),
        filter: None,
    };
    let req2 = QueryRagRequest {
        query: "Query 2".into(),
        session_id: "00000000-0000-4000-8000-000000000005".into(),
        filter: None,
    };

    let res1 = execute_query_rag(&service1, req1).await.unwrap();
    let res2 = execute_query_rag(&service1, req2).await.unwrap();

    let gen1 = res1.snapshot.as_ref().unwrap().index_generation.clone();
    let gen2 = res2.snapshot.as_ref().unwrap().index_generation.clone();

    assert!(!gen1.is_empty());
    assert_ne!(gen1, "v1");
    assert_eq!(
        gen1, gen2,
        "two queries on the same service must report the same generation"
    );

    let effective_settings2 = EffectiveRagSettings::default();
    let path2 = database_path("opaque-stable-gen-2");
    let database2 = DatabaseManager::initialize(&path2).await.unwrap();
    let doc_id2 = Uuid::new_v4().to_string();
    stage_document(&database2, &doc_id2, b"# Test Document 2\n\nContent 2").await;
    let job2 = read_staged_jobs(&database2)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    process_job(&job2, &database2, &FakeEmbedder).await.unwrap();

    let nodes2 = database2.nodes_table().await.unwrap();
    let bm25_index2 = Bm25Index::from_table(&nodes2, effective_settings2.retrieval.bm25.clone())
        .await
        .unwrap();
    let table2 = database2.staged_documents_table().await.unwrap();
    let (sender2, _receiver2) = mpsc::channel(QUEUE_CAPACITY);
    let service2 = LancetServiceImpl {
        table: table2,
        statuses: Arc::new(DashMap::new()),
        queue: sender2,
        nodes: nodes2,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index2)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: effective_settings2,
        generator: Arc::new(generation::FakeGenerator::new(Ok(
            generation::ModelOutput {
                answer: "Answer 2 [1].".into(),
                cited_evidence_ids: vec!["[1]".into()],
                answer_basis: generation::AnswerBasis::Retrieval,
                notices: vec![],
                warnings: vec![],
                usage: None,
            },
        ))),
        embedder: Arc::new(FakeEmbedder),
        database: database2.clone(),
    };

    let req3 = QueryRagRequest {
        query: "Query 3".into(),
        session_id: "00000000-0000-4000-8000-000000000006".into(),
        filter: None,
    };
    let res3 = execute_query_rag(&service2, req3).await.unwrap();
    let gen3 = res3.snapshot.as_ref().unwrap().index_generation.clone();

    assert_ne!(
        gen1, gen3,
        "separately constructed service must report a different generation"
    );

    let _ = std::fs::remove_dir_all(path1);
    let _ = std::fs::remove_dir_all(path2);
}

#[test]
fn invalid_effective_settings_rejected() {
    let mut settings = Settings::default();
    settings.openrouter.embedding_model = "  ".into();
    assert!(EffectiveRagSettings::try_from_settings(&settings).is_err());

    let mut settings2 = Settings::default();
    settings2.openrouter.temperature = 5.0;
    assert!(EffectiveRagSettings::try_from_settings(&settings2).is_err());

    let mut settings3 = Settings::default();
    settings3.engine.retrieval.rrf_k = 60.5;
    assert!(EffectiveRagSettings::try_from_settings(&settings3).is_err());
}

#[tokio::test]
async fn query_rag_citation_identity_and_notices() {
    let path = database_path("query-rag-citation-identity-and-notices");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id_1 = "00000000-0000-4000-8000-000000000001".to_string();
    let doc_id_2 = "00000000-0000-4000-8000-000000000002".to_string();

    stage_document_with_settings(
        &database,
        &doc_id_1,
        "Document Alpha",
        b"# Document Alpha\nFirst document content block with very long detailed text for testing query_rag citation identity and notices truncation check.",
        "structure-aware",
        500,
        50,
    )
    .await;

    stage_document_with_settings(
        &database,
        &doc_id_2,
        "Document Beta",
        b"# Document Beta\nSecond document content block with very long detailed text for testing unicode truncation check.",
        "structure-aware",
        500,
        50,
    )
    .await;

    let jobs = read_staged_jobs(&database).await.unwrap();
    for job in jobs {
        process_job(&job, &database, &FakeEmbedder).await.unwrap();
    }

    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, Bm25Config::default())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, _receiver) = mpsc::channel(QUEUE_CAPACITY);

    let fake_gen = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Answer citing second block only [2].".into(),
            cited_evidence_ids: vec!["[2]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec!["Notice msg A".into()],
            warnings: vec!["Warning msg B".into()],
            usage: None,
        },
    )));

    let mut settings = Settings::default();
    settings.engine.retrieval.excerpt_max_chars = 20;
    let effective_settings = EffectiveRagSettings::try_from_settings(&settings).unwrap();

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings,
        generator: fake_gen.clone(),
        embedder: Arc::new(FakeEmbedder),
        database: database.clone(),
    };

    let req = QueryRagRequest {
        query: "document content".into(),
        session_id: "00000000-0000-4000-8000-000000000099".into(),
        filter: None,
    };

    let response = execute_query_rag(&service, req).await.unwrap();

    assert_eq!(response.answer, "Answer citing second block only [2].");
    assert_eq!(response.citations, vec!["[2]".to_string()]);
    assert_eq!(response.structured_citations.len(), 1);

    let sc = &response.structured_citations[0];
    assert_eq!(sc.document_id, doc_id_1);
    assert_eq!(sc.title, "Document Alpha");
    assert_eq!(sc.section_path, "/Document Alpha");
    assert_eq!(sc.content_type, "text/plain");
    assert_eq!(sc.rank, 2);
    assert!(sc.excerpt.chars().count() <= 20);
    assert!(sc.is_truncated);

    assert_eq!(response.notices.len(), 2);
    assert_eq!(response.notices[0].code, "NOTICE");
    assert_eq!(response.notices[0].message, "Notice msg A");
    assert_eq!(
        response.notices[0].severity,
        lancet::v1::NoticeSeverity::Info as i32
    );
    assert_eq!(response.notices[1].code, "WARNING");
    assert_eq!(response.notices[1].message, "Warning msg B");
    assert_eq!(
        response.notices[1].severity,
        lancet::v1::NoticeSeverity::Warning as i32
    );

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn query_rag_rejects_unknown_marker_without_response() {
    let path = database_path("query-rag-rejects-unknown-marker");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    stage_document(
        &database,
        &doc_id,
        b"# Document Gamma\n\nContent for gamma document.",
    )
    .await;

    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    process_job(&job, &database, &FakeEmbedder).await.unwrap();

    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, Bm25Config::default())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, _receiver) = mpsc::channel(QUEUE_CAPACITY);

    let fake_gen = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Answer citing nonexistent marker [99].".into(),
            cited_evidence_ids: vec!["[99]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: EffectiveRagSettings::default(),
        generator: fake_gen.clone(),
        embedder: Arc::new(FakeEmbedder),
        database: database.clone(),
    };

    let req = QueryRagRequest {
        query: "gamma document".into(),
        session_id: "00000000-0000-4000-8000-000000000088".into(),
        filter: None,
    };

    let res = execute_query_rag(&service, req).await;
    assert!(res.is_err());

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn query_rag_rejects_invalid_provider_grounding() {
    let path = database_path("query-rag-rejects-invalid-provider-grounding");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    stage_document(
        &database,
        &doc_id,
        b"# Document Grounding\n\nContent for grounding test document.",
    )
    .await;

    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    process_job(&job, &database, &FakeEmbedder).await.unwrap();

    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, Bm25Config::default())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, _receiver) = mpsc::channel(QUEUE_CAPACITY);

    let fake_gen = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Model-only response without grounding.".into(),
            cited_evidence_ids: vec![],
            answer_basis: generation::AnswerBasis::ModelOnly,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: EffectiveRagSettings::default(),
        generator: fake_gen.clone(),
        embedder: Arc::new(FakeEmbedder),
        database: database.clone(),
    };

    let req = QueryRagRequest {
        query: "grounding test document".into(),
        session_id: "00000000-0000-4000-8000-000000000099".into(),
        filter: None,
    };

    let res = execute_query_rag(&service, req).await;
    assert!(res.is_err());
    let status = res.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Internal);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn query_rag_generation_error_preserves_identity() {
    let path = database_path("query-rag-generation-error-preserves-identity");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    stage_document(
        &database,
        &doc_id,
        b"# Document Identity\n\nContent for identity preservation test.",
    )
    .await;

    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    process_job(&job, &database, &FakeEmbedder).await.unwrap();

    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, Bm25Config::default())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, _receiver) = mpsc::channel(QUEUE_CAPACITY);

    let failing_gen = Arc::new(generation::FakeGenerator::new(Err(
        generation::GenerationError::new(
            generation::GenerationErrorKind::ProviderError,
            "OpenRouter API rate limit",
        ),
    )));

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: EffectiveRagSettings::default(),
        generator: failing_gen,
        embedder: Arc::new(FakeEmbedder),
        database: database.clone(),
    };

    let session_id = "00000000-0000-4000-8000-000000000077";
    let req = QueryRagRequest {
        query: "identity preservation test".into(),
        session_id: session_id.into(),
        filter: None,
    };

    let stream_res = service.query_rag(tonic::Request::new(req)).await.unwrap();
    let mut stream = stream_res.into_inner();
    let mut completed = None;
    while let Some(res) = stream.next().await {
        let ev = res.unwrap();
        if let Some(engine::pb::lancet::v1::workflow_event::Event::WorkflowCompleted(ref wc)) = ev.event {
            completed = Some((ev.clone(), wc.clone()));
        }
    }
    let (ev, wc) = completed.expect("WorkflowCompleted event");
    assert!(!wc.success);
    assert_eq!(wc.error_message, "OpenRouter API rate limit");
    assert_eq!(ev.session_id, session_id);
    assert!(Uuid::parse_str(&ev.trace_id).is_ok());

    let _ = std::fs::remove_dir_all(path);
}

async fn reranker_query_fixture(
    test_name: &str,
    final_limit: usize,
    generator: Arc<dyn generation::Generator>,
    reranker: Arc<dyn rerank::Reranker>,
) -> (String, LancetServiceImpl) {
    let path = database_path(test_name);
    let database = DatabaseManager::initialize(&path).await.unwrap();
    for label in ["Alpha", "Beta", "Gamma"] {
        let document_id = Uuid::new_v4().to_string();
        let content = format!("# {label}\n\nReranker evidence {label} content.");
        stage_document(&database, &document_id, content.as_bytes()).await;
    }

    let jobs = read_staged_jobs(&database).await.unwrap();
    for job in jobs {
        process_job(&job, &database, &FakeEmbedder).await.unwrap();
    }

    let mut settings = Settings::default();
    settings.engine.retrieval.candidate_limit = 8;
    settings.engine.retrieval.final_limit = final_limit;
    let effective_settings = EffectiveRagSettings::try_from_settings(&settings).unwrap();
    let service = configured_service(
        &database,
        effective_settings,
        Arc::new(FakeEmbedder),
        generator,
        reranker,
    )
    .await;
    (path, service)
}

#[tokio::test]
async fn query_rag_invokes_recording_reranker_once() {
    let reranker = RecordingReranker::new();
    let generator = RecordingGenerator::from_effective_settings(&EffectiveRagSettings::default());
    let (path, service) = reranker_query_fixture(
        "query-rag-recording-reranker-once",
        1,
        generator.clone(),
        reranker.clone(),
    )
    .await;

    execute_query_rag(
        &service,
        QueryRagRequest {
            query: "reranker evidence".into(),
            session_id: "00000000-0000-4000-8000-000000000201".into(),
            filter: None,
        },
    )
    .await
    .unwrap();

    let inputs = reranker.inputs();
    assert_eq!(reranker.calls(), 1);
    assert_eq!(inputs.len(), 1);
    assert!(inputs[0].len() > service.effective_settings.retrieval.final_limit);
    assert_eq!(generator.calls(), 1);
    assert_eq!(generator.requests()[0].evidence.len(), 1);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn query_rag_grounding_uses_reranked_identity() {
    let reranker = RecordingReranker::new();
    let generator = RecordingGenerator::from_effective_settings(&EffectiveRagSettings::default());
    let (path, service) = reranker_query_fixture(
        "query-rag-reranked-grounding-identity",
        1,
        generator.clone(),
        reranker.clone(),
    )
    .await;

    let response = execute_query_rag(
        &service,
        QueryRagRequest {
            query: "reranker evidence".into(),
            session_id: "00000000-0000-4000-8000-000000000202".into(),
            filter: None,
        },
    )
    .await
    .unwrap();

    let input = &reranker.inputs()[0];
    assert!(input.len() > 1);
    let expected_chunk_id = input[1].candidate.chunk_id.clone();
    let generated_evidence = &generator.requests()[0].evidence;
    assert_eq!(generated_evidence.len(), 1);
    assert_eq!(generated_evidence[0].chunk_id, expected_chunk_id);
    assert_eq!(response.structured_citations.len(), 1);
    assert_eq!(response.structured_citations[0].chunk_id, expected_chunk_id);
    assert_eq!(response.citations, vec!["[1]".to_string()]);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn query_rag_noop_reranker_preserves_fused_order() {
    let generator = RecordingGenerator::from_effective_settings(&EffectiveRagSettings::default());
    let (path, service) = reranker_query_fixture(
        "query-rag-noop-reranker-order",
        2,
        generator.clone(),
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;

    let query_request = QueryRequest::from_values(
        "reranker evidence",
        vec![],
        vec![],
        &service.effective_settings.retrieval,
    )
    .unwrap();
    let dense_candidates = DenseRetriever::new(service.nodes.clone())
        .query(
            &vec![0.25; 2048],
            &query_request,
            &service.effective_settings.retrieval,
        )
        .await
        .unwrap();
    let bm25_candidates = service
        .bm25_index
        .read()
        .await
        .retrieve(&query_request, &service.effective_settings.retrieval)
        .await
        .unwrap();
    let expected = retrieval::fusion::fuse_candidates(
        dense_candidates,
        bm25_candidates,
        &service.effective_settings.retrieval,
    )
    .unwrap();
    let expected_chunk_ids: Vec<_> = expected
        .iter()
        .take(service.effective_settings.retrieval.final_limit)
        .map(|candidate| candidate.candidate.chunk_id.clone())
        .collect();

    execute_query_rag(
        &service,
        QueryRagRequest {
            query: "reranker evidence".into(),
            session_id: "00000000-0000-4000-8000-000000000203".into(),
            filter: None,
        },
    )
    .await
    .unwrap();
    let actual_chunk_ids: Vec<_> = generator.requests()[0]
        .evidence
        .iter()
        .map(|evidence| evidence.chunk_id.clone())
        .collect();
    assert_eq!(actual_chunk_ids, expected_chunk_ids);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn query_rag_reranker_failure_skips_generation() {
    let reranker = FailingReranker::new();
    let generator = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "This answer must never be generated".into(),
            cited_evidence_ids: vec![],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));
    let (path, service) = reranker_query_fixture(
        "query-rag-failing-reranker",
        1,
        generator.clone(),
        reranker.clone(),
    )
    .await;

    let result = execute_query_rag(
        &service,
        QueryRagRequest {
            query: "reranker evidence".into(),
            session_id: "00000000-0000-4000-8000-000000000204".into(),
            filter: None,
        },
    )
    .await;

    assert!(result.is_err());
    assert_eq!(reranker.calls(), 1);
    assert_eq!(generator.calls(), 0);

    let _ = std::fs::remove_dir_all(path);
}

struct FailingEmbedder(String);

impl EmbeddingProvider for FailingEmbedder {
    fn get_embeddings<'a>(
        &'a self,
        _texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        let msg = self.0.clone();
        Box::pin(async move { Err(msg) })
    }
}

struct PayloadEmbedder(Vec<Vec<f32>>);

impl EmbeddingProvider for PayloadEmbedder {
    fn get_embeddings<'a>(
        &'a self,
        _texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        let vecs = self.0.clone();
        Box::pin(async move { Ok(vecs) })
    }
}

#[tokio::test]
async fn query_rag_fail_closed_embedding_transport() {
    let path = database_path("query-rag-fc-emb-trans");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let effective_settings = EffectiveRagSettings::default();
    let embedder = Arc::new(FailingEmbedder("network unreachable".into()));
    let generator = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Should not be called [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));
    let reranker = Arc::new(rerank::NoOpReranker::new());

    let service = configured_service(
        &database,
        effective_settings,
        embedder,
        generator.clone(),
        reranker,
    )
    .await;

    let req = QueryRagRequest {
        query: "What is Lancet?".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: None,
    };

    let status = execute_query_rag(&service, req)
        .await
        .expect_err("embedding transport error fails closed");
    assert_eq!(status.code(), tonic::Code::Unavailable);
    assert!(status.metadata().get("x-lancet-error-kind").is_some());
    assert_eq!(
        status
            .metadata()
            .get("x-lancet-session-id")
            .unwrap()
            .to_str()
            .unwrap(),
        "00000000-0000-4000-8000-000000000001"
    );
    assert!(status.metadata().get("x-lancet-correlation-id").is_some());
    assert_eq!(generator.calls(), 0);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn query_rag_fail_closed_embedding_empty_payload() {
    let path = database_path("query-rag-fc-emb-empty");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let effective_settings = EffectiveRagSettings::default();
    let embedder = Arc::new(PayloadEmbedder(vec![]));
    let generator = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Should not be called [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));
    let reranker = Arc::new(rerank::NoOpReranker::new());

    let service = configured_service(
        &database,
        effective_settings,
        embedder,
        generator.clone(),
        reranker,
    )
    .await;

    let req = QueryRagRequest {
        query: "What is Lancet?".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: None,
    };

    let status = execute_query_rag(&service, req)
        .await
        .expect_err("empty embedding payload fails closed");
    assert_eq!(status.code(), tonic::Code::Unavailable);
    assert!(status.metadata().get("x-lancet-error-kind").is_some());
    assert_eq!(generator.calls(), 0);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn query_rag_fail_closed_embedding_multi_vector() {
    let path = database_path("query-rag-fc-emb-multi");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let effective_settings = EffectiveRagSettings::default();
    let embedder = Arc::new(PayloadEmbedder(vec![vec![0.25; 2048], vec![0.25; 2048]]));
    let generator = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Should not be called [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));
    let reranker = Arc::new(rerank::NoOpReranker::new());

    let service = configured_service(
        &database,
        effective_settings,
        embedder,
        generator.clone(),
        reranker,
    )
    .await;

    let req = QueryRagRequest {
        query: "What is Lancet?".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: None,
    };

    let status = execute_query_rag(&service, req)
        .await
        .expect_err("multi vector payload fails closed");
    assert_eq!(status.code(), tonic::Code::Unavailable);
    assert!(status.metadata().get("x-lancet-error-kind").is_some());
    assert_eq!(generator.calls(), 0);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn query_rag_fail_closed_embedding_wrong_dimension() {
    let path = database_path("query-rag-fc-emb-dim");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let effective_settings = EffectiveRagSettings::default();
    let embedder = Arc::new(PayloadEmbedder(vec![vec![0.25; 512]]));
    let generator = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Should not be called [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));
    let reranker = Arc::new(rerank::NoOpReranker::new());

    let service = configured_service(
        &database,
        effective_settings,
        embedder,
        generator.clone(),
        reranker,
    )
    .await;

    let req = QueryRagRequest {
        query: "What is Lancet?".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: None,
    };

    let status = execute_query_rag(&service, req)
        .await
        .expect_err("wrong dimension vector fails closed");
    assert_eq!(status.code(), tonic::Code::Unavailable);
    assert!(status.metadata().get("x-lancet-error-kind").is_some());
    assert_eq!(generator.calls(), 0);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn query_rag_fail_closed_embedding_non_finite() {
    let path = database_path("query-rag-fc-emb-nan");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let effective_settings = EffectiveRagSettings::default();
    let mut vec_nan = vec![0.25; 2048];
    vec_nan[10] = f32::NAN;
    let embedder = Arc::new(PayloadEmbedder(vec![vec_nan]));
    let generator = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Should not be called [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));
    let reranker = Arc::new(rerank::NoOpReranker::new());

    let service = configured_service(
        &database,
        effective_settings,
        embedder,
        generator.clone(),
        reranker,
    )
    .await;

    let req = QueryRagRequest {
        query: "What is Lancet?".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: None,
    };

    let status = execute_query_rag(&service, req)
        .await
        .expect_err("non finite vector fails closed");
    assert_eq!(status.code(), tonic::Code::Unavailable);
    assert!(status.metadata().get("x-lancet-error-kind").is_some());
    assert_eq!(generator.calls(), 0);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn query_rag_fail_closed_dense_snapshot() {
    let path = database_path("query-rag-fc-dense-snap");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let effective_settings = EffectiveRagSettings::default();
    let embedder = Arc::new(FakeEmbedder);
    let generator = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Should not be called [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));
    let reranker = Arc::new(rerank::NoOpReranker::new());

    let malformed_nodes = database.edges_table().await.unwrap();
    let bm25_nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&bm25_nodes, effective_settings.retrieval.bm25.clone())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(dashmap::DashMap::new());
    let (sender, _receiver) = tokio::sync::mpsc::channel(QUEUE_CAPACITY);

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes: malformed_nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        effective_settings,
        generator: generator.clone(),
        embedder,
        reranker,
        database: database.clone(),
    };

    let req = QueryRagRequest {
        query: "What is Lancet?".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: None,
    };

    let status = execute_query_rag(&service, req)
        .await
        .expect_err("dense snapshot error fails closed");
    assert_eq!(status.code(), tonic::Code::Unavailable);
    assert!(status.metadata().get("x-lancet-error-kind").is_some());
    assert_eq!(generator.calls(), 0);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn query_rag_valid_zero_match() {
    let path = database_path("query-rag-zero-match");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let effective_settings = EffectiveRagSettings::default();
    let embedder = Arc::new(FakeEmbedder);
    let generator = Arc::new(generation::FakeGenerator::new(Ok(
        generation::ModelOutput {
            answer: "Should not be called [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        },
    )));
    let reranker = Arc::new(rerank::NoOpReranker::new());

    let service = configured_service(
        &database,
        effective_settings,
        embedder,
        generator.clone(),
        reranker,
    )
    .await;

    let req = QueryRagRequest {
        query: "What is Lancet?".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: Some(DocumentFilter {
            document_ids: vec!["00000000-0000-4000-8000-000000000999".into()],
            content_types: vec![],
        }),
    };

    let resp = execute_query_rag(&service, req).await.unwrap();
    assert_eq!(resp.answer, "");
    assert!(resp.citations.is_empty());
    assert!(resp.structured_citations.is_empty());
    assert_eq!(resp.session_id, "00000000-0000-4000-8000-000000000001");
    assert_eq!(
        resp.answer_basis,
        lancet::v1::AnswerBasis::Unspecified as i32
    );
    assert_eq!(resp.notices.len(), 1);
    assert_eq!(resp.notices[0].code, "NO_EVIDENCE");
    assert_eq!(
        resp.notices[0].message,
        "No completed corpus evidence matched the requested filters."
    );
    assert_eq!(
        resp.notices[0].severity,
        lancet::v1::NoticeSeverity::Info as i32
    );
    assert!(resp.snapshot.is_some());
    assert_eq!(generator.calls(), 0);

    let _ = std::fs::remove_dir_all(path);
}

#[test]
fn effective_settings_carries_one_grounding_limits() {
    let settings = Settings::default();
    let effective = EffectiveRagSettings::try_from_settings(&settings).unwrap();
    let limits = effective.grounding_limits();
    assert_eq!(limits.evidence_token_budget(), 8192);
    assert_eq!(limits.max_output_tokens(), 2048);
    assert_eq!(limits.total_tokens_ceiling(), 10240);

    let arc_limits = effective.grounding_limits_arc();
    assert_eq!(arc_limits.as_ref(), limits);
}

#[tokio::test]
async fn read_staged_jobs_latest_generation_wins() {
    let doc_id = "00000000-0000-4000-8000-000000000001";
    let job_v1 = IngestionJob {
        document_id: doc_id.to_string(),
        filename: "doc_v1.txt".to_string(),
        raw_data: b"version 1".to_vec(),
        metadata: HashMap::from([
            ("chunk_strategy".to_string(), "fixed-size".to_string()),
            ("chunk_size".to_string(), "500".to_string()),
            ("chunk_overlap".to_string(), "50".to_string()),
        ]),
        chunk_settings: crate::parse_chunk_settings(&HashMap::from([
            ("chunk_strategy".to_string(), "fixed-size".to_string()),
            ("chunk_size".to_string(), "500".to_string()),
            ("chunk_overlap".to_string(), "50".to_string()),
        ]))
        .unwrap(),
    };

    let job_v2 = IngestionJob {
        document_id: doc_id.to_string(),
        filename: "doc_v2.txt".to_string(),
        raw_data: b"version 2".to_vec(),
        metadata: HashMap::from([
            ("chunk_strategy".to_string(), "fixed-size".to_string()),
            ("chunk_size".to_string(), "500".to_string()),
            ("chunk_overlap".to_string(), "50".to_string()),
        ]),
        chunk_settings: crate::parse_chunk_settings(&HashMap::from([
            ("chunk_strategy".to_string(), "fixed-size".to_string()),
            ("chunk_size".to_string(), "500".to_string()),
            ("chunk_overlap".to_string(), "50".to_string()),
        ]))
        .unwrap(),
    };

    let rows = vec![
        StagedJobRow {
            document_id: doc_id.to_string(),
            generation: 1,
            job: job_v1,
        },
        StagedJobRow {
            document_id: doc_id.to_string(),
            generation: 2,
            job: job_v2,
        },
    ];

    let selected = select_latest_staged_rows(rows).unwrap();
    assert_eq!(selected.len(), 1);
    assert_eq!(selected[0].filename, "doc_v2.txt");
    assert_eq!(selected[0].raw_data, b"version 2");
}

fn temp_db_path(test_name: &str) -> String {
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir()
        .join(format!("lancet-{test_name}-{nonce}"))
        .to_string_lossy()
        .into_owned()
}

#[tokio::test]
async fn persist_raw_append_verify_precedes_delete() {
    let path = temp_db_path("persist-raw-order");
    let manager = DatabaseManager::initialize(&path).await.unwrap();
    let staged_table = manager.staged_documents_table().await.unwrap();

    let doc_id = "00000000-0000-4000-8000-000000000001";
    let job1 = IngestionJob::new(
        doc_id.to_string(),
        "v1.txt".to_string(),
        b"raw v1".to_vec(),
        HashMap::from([
            ("chunk_strategy".to_string(), "fixed-size".to_string()),
            ("chunk_size".to_string(), "500".to_string()),
            ("chunk_overlap".to_string(), "50".to_string()),
        ]),
    );

    persist_raw_with_boundary(&staged_table, &job1, &LanceDbReplacementMutationBoundary)
        .await
        .unwrap();

    let job2 = IngestionJob::new(
        doc_id.to_string(),
        "v2.txt".to_string(),
        b"raw v2".to_vec(),
        HashMap::from([
            ("chunk_strategy".to_string(), "fixed-size".to_string()),
            ("chunk_size".to_string(), "500".to_string()),
            ("chunk_overlap".to_string(), "50".to_string()),
        ]),
    );

    let recorded_calls = Arc::new(std::sync::Mutex::new(Vec::new()));
    struct RecordingBoundary(Arc<std::sync::Mutex<Vec<ReplacementMutation>>>);
    impl ReplacementMutationBoundary for RecordingBoundary {
        fn delete<'a>(
            &self,
            boundary: ReplacementMutation,
            table: &'a Table,
            predicate: &'a str,
        ) -> BoxFuture<'a, Result<(), String>> {
            self.0.lock().unwrap().push(boundary);
            Box::pin(async move {
                table
                    .delete(predicate)
                    .await
                    .map(|_| ())
                    .map_err(|e| e.to_string())
            })
        }
        fn add<'a>(
            &self,
            boundary: ReplacementMutation,
            table: &'a Table,
            batch: RecordBatch,
        ) -> BoxFuture<'a, Result<(), String>> {
            self.0.lock().unwrap().push(boundary);
            Box::pin(async move {
                table
                    .add(batch)
                    .execute()
                    .await
                    .map(|_| ())
                    .map_err(|e| e.to_string())
            })
        }
    }

    let rec_boundary = RecordingBoundary(recorded_calls.clone());
    persist_raw_with_boundary(&staged_table, &job2, &rec_boundary)
        .await
        .unwrap();

    let calls = recorded_calls.lock().unwrap().clone();
    assert_eq!(
        calls,
        vec![
            ReplacementMutation::StagingAdd,
            ReplacementMutation::StagingDelete
        ]
    );

    let staged_jobs = read_staged_jobs(&manager).await.unwrap();
    assert_eq!(staged_jobs.len(), 1);
    assert_eq!(staged_jobs[0].filename, "v2.txt");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn persist_raw_keeps_old_generation_when_delete_fails() {
    let path = temp_db_path("persist-raw-fail-delete");
    let manager = DatabaseManager::initialize(&path).await.unwrap();
    let staged_table = manager.staged_documents_table().await.unwrap();

    let doc_id = "00000000-0000-4000-8000-000000000001";
    let job1 = IngestionJob::new(
        doc_id.to_string(),
        "v1.txt".to_string(),
        b"raw v1".to_vec(),
        HashMap::from([
            ("chunk_strategy".to_string(), "fixed-size".to_string()),
            ("chunk_size".to_string(), "500".to_string()),
            ("chunk_overlap".to_string(), "50".to_string()),
        ]),
    );

    persist_raw_with_boundary(&staged_table, &job1, &LanceDbReplacementMutationBoundary)
        .await
        .unwrap();

    let job2 = IngestionJob::new(
        doc_id.to_string(),
        "v2.txt".to_string(),
        b"raw v2".to_vec(),
        HashMap::from([
            ("chunk_strategy".to_string(), "fixed-size".to_string()),
            ("chunk_size".to_string(), "500".to_string()),
            ("chunk_overlap".to_string(), "50".to_string()),
        ]),
    );

    struct DeleteFaultBoundary;
    impl ReplacementMutationBoundary for DeleteFaultBoundary {
        fn delete<'a>(
            &self,
            _boundary: ReplacementMutation,
            _table: &'a Table,
            _predicate: &'a str,
        ) -> BoxFuture<'a, Result<(), String>> {
            Box::pin(async move { Err("injected delete failure".to_string()) })
        }
        fn add<'a>(
            &self,
            _boundary: ReplacementMutation,
            table: &'a Table,
            batch: RecordBatch,
        ) -> BoxFuture<'a, Result<(), String>> {
            Box::pin(async move {
                table
                    .add(batch)
                    .execute()
                    .await
                    .map(|_| ())
                    .map_err(|e| e.to_string())
            })
        }
    }

    let res = persist_raw_with_boundary(&staged_table, &job2, &DeleteFaultBoundary).await;
    assert!(res.is_err(), "must fail when delete fails");

    let staged_jobs = read_staged_jobs(&manager).await.unwrap();
    assert_eq!(staged_jobs.len(), 1);
    assert_eq!(staged_jobs[0].filename, "v2.txt");

    let _ = std::fs::remove_dir_all(path);
}

#[test]
fn ingestion_chunking_min_length() {
    assert_eq!(crate::graph::extraction::MIN_CHUNK_CONTENT_LENGTH, 40);
}

#[tokio::test]
async fn extraction_chunk_field_propagation() {
    let path = database_path("extraction-chunk-propagation");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let text = "# Section Title\n\n"
        .to_string()
        + &"This is a long sentence with enough characters to pass the min chunk content length requirement. ".repeat(3);

    let job = IngestionJob::new(
        doc_id.clone(),
        "propagation.md".into(),
        text.as_bytes().to_vec(),
        HashMap::new(),
    );

    let captured_requests = Arc::new(tokio::sync::Mutex::new(Vec::new()));
    let capturer = captured_requests.clone();

    struct CapturingGenerator(Arc<tokio::sync::Mutex<Vec<super::graph::extraction::ExtractionRequest>>>);

    impl super::graph::extraction::ExtractionGenerator for CapturingGenerator {
        fn extract<'a>(
            &'a self,
            request: super::graph::extraction::ExtractionRequest,
        ) -> BoxFuture<'a, Result<super::graph::extraction::ExtractionOutput, generation::GenerationError>>
        {
            let cap = self.0.clone();
            Box::pin(async move {
                cap.lock().await.push(request);
                Ok(super::graph::extraction::ExtractionOutput {
                    entities: vec![],
                    relations: vec![],
                })
            })
        }
    }

    super::extract_and_persist_entities(&database, &job, &CapturingGenerator(capturer), &FakeEmbedder)
        .await
        .unwrap();

    let reqs = captured_requests.lock().await;
    assert!(!reqs.is_empty());
    for req in reqs.iter() {
        assert_eq!(req.document_id, doc_id);
        assert!(!req.chunk_id.is_empty());
        assert!(!req.chunk_text.is_empty());
    }

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn exact_match_entity_deduplication() {
    let path = database_path("exact-match-dedup");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let text = "# Section 1\n\nAcme Corp is an organization that builds high quality software widgets.\n\n# Section 2\n\nACME CORP continues to expand its organization product catalog globally.";

    let job = IngestionJob::new(
        doc_id.clone(),
        "dedup.md".into(),
        text.as_bytes().to_vec(),
        HashMap::new(),
    );

    let fake_gen = super::graph::extraction::FakeExtractionGenerator::new(Ok(
        super::graph::extraction::ExtractionOutput {
            entities: vec![super::graph::extraction::ExtractedEntity {
                name: "Acme Corp".into(),
                entity_type: "organization".into(),
            }],
            relations: vec![],
        },
    ));

    super::extract_and_persist_entities(&database, &job, &fake_gen, &FakeEmbedder)
        .await
        .unwrap();

    let entities_table = database.entities_table().await.unwrap();
    let count = entities_table.count_rows(None).await.unwrap();
    assert_eq!(count, 1, "Acme Corp and ACME CORP must deduplicate to single entity");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn cross_document_entity_resolution() {
    let path = database_path("cross-doc-entity-res");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let text1 = "# Doc 1\n\nAcme Corp is a company building widgets in the global marketplace.";
    let job1 = IngestionJob::new(
        Uuid::new_v4().to_string(),
        "doc1.md".into(),
        text1.as_bytes().to_vec(),
        HashMap::new(),
    );

    let fake_gen = super::graph::extraction::FakeExtractionGenerator::new(Ok(
        super::graph::extraction::ExtractionOutput {
            entities: vec![super::graph::extraction::ExtractedEntity {
                name: "Acme Corp".into(),
                entity_type: "organization".into(),
            }],
            relations: vec![],
        },
    ));

    super::extract_and_persist_entities(&database, &job1, &fake_gen, &FakeEmbedder)
        .await
        .unwrap();

    let text2 = "# Doc 2\n\nacme corp provides widget solutions to clients worldwide daily.";
    let job2 = IngestionJob::new(
        Uuid::new_v4().to_string(),
        "doc2.md".into(),
        text2.as_bytes().to_vec(),
        HashMap::new(),
    );

    super::extract_and_persist_entities(&database, &job2, &fake_gen, &FakeEmbedder)
        .await
        .unwrap();

    let entities_table = database.entities_table().await.unwrap();
    assert_eq!(entities_table.count_rows(None).await.unwrap(), 1);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn unmapped_relation_endpoint_dropped() {
    let path = database_path("unmapped-rel-endpoint");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let text = "# Section\n\nAlice works with Bob in the organization department today.";
    let job = IngestionJob::new(
        doc_id,
        "unmapped.md".into(),
        text.as_bytes().to_vec(),
        HashMap::new(),
    );

    let fake_gen = super::graph::extraction::FakeExtractionGenerator::new(Ok(
        super::graph::extraction::ExtractionOutput {
            entities: vec![super::graph::extraction::ExtractedEntity {
                name: "Alice".into(),
                entity_type: "person".into(),
            }],
            relations: vec![super::graph::extraction::ExtractedRelation {
                source: "Alice".into(),
                target: "Bob".into(), // Bob is not in entities!
                relation_type: "works_with".into(),
                confidence: 0.9,
            }],
        },
    ));

    super::extract_and_persist_entities(&database, &job, &fake_gen, &FakeEmbedder)
        .await
        .unwrap();

    let edges_table = database.entity_edges_table().await.unwrap();
    assert_eq!(edges_table.count_rows(None).await.unwrap(), 0, "Unmapped relation endpoint must be dropped");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn attempt_graph_augmentation_scoring_and_neighborhood() {
    let path = database_path("attempt-graph-aug");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let settings = GraphSettings {
        seed_match_min_score: 0.5,
        max_hop_cap: 3,
    };

    let outcome = super::attempt_graph_augmentation(&database, &[0.0; 2048], &settings).await;
    assert!(matches!(outcome, super::GraphAugmentationOutcome::NoMatchFound));

    let _ = std::fs::remove_dir_all(path);
}

#[test]
fn prompt_evidence_packing_graph_fact_rendering() {
    use crate::prompt::{
        pack_evidence_and_graph_prompt_sync, assemble_evidence_blocks, GraphFactBlock,
    };
    use crate::graph::context_strategy::GraphFact;

    let candidate = crate::retrieval::FusedCandidate {
        candidate: crate::retrieval::Candidate {
            document_id: "doc-1".into(),
            chunk_id: "chk-1".into(),
            chunk_index: 0,
            char_start: 0,
            char_end: 20,
            content: "Content chunk text".into(),
            title: Some("Title".into()),
            section_path: Some("/Sec".into()),
            content_type: Some("text/markdown".into()),
            embedding_model: None,
            ingested_at: None,
            score: 0.9,
        },
        fused_score: 0.9,
        vector_rank: Some(1),
        bm25_rank: None,
        vector_score: Some(0.9),
        bm25_score: None,
        variant_provenance: Vec::new(),
    };

    let blocks = assemble_evidence_blocks(&[candidate]);
    let facts = vec![GraphFactBlock {
        fact: GraphFact::new("Alice", "knows", "Bob", None, 0.85),
    }];

    let packed =
        pack_evidence_and_graph_prompt_sync("Who knows Bob?", &blocks, &facts, 1.0, 4096, 512).unwrap();
    assert!(packed.prompt.contains("## Related Entities & Relationships"));
    assert!(packed.prompt.contains("Alice —knows→ Bob"));
    assert_eq!(packed.graph_facts.len(), 1);
}

#[tokio::test]
async fn query_rag_span_and_request_threading() {
    let path = database_path("query-rag-span-threading");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    stage_document(&database, &doc_id, b"# Test\n\nContent for RAG query threading.").await;

    let job = read_staged_jobs(&database).await.unwrap().into_iter().next().unwrap();
    process_job(&job, &database, &FakeEmbedder).await.unwrap();

    let settings = EffectiveRagSettings::default();
    let service = configured_service(
        &database,
        settings,
        Arc::new(FakeEmbedder),
        Arc::new(generation::FakeGenerator::new(Ok(generation::ModelOutput {
            answer: "Answer [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        }))),
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;

    let req = QueryRagRequest {
        query: "RAG query".into(),
        session_id: Uuid::new_v4().to_string(),
        filter: None,
    };

    let res = execute_query_rag(&service, req).await;
    assert!(res.is_ok());

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn extraction_runs_concurrently_and_skips_short_chunks() {
    let path = database_path("extraction-concurrent-skip");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let long_para = "This is a long sentence with enough characters to pass the min chunk content length requirement. ".repeat(3);
    // 7 chunks total: chunk 0 short, chunks 1..=6 long
    let text = format!("Short\n\n{long_para}\n\n{long_para}\n\n{long_para}\n\n{long_para}\n\n{long_para}\n\n{long_para}");

    let job = IngestionJob::new(
        doc_id.clone(),
        "concurrent.md".into(),
        text.as_bytes().to_vec(),
        HashMap::new(),
    );

    let failing_chunk_id = format!("{doc_id}:3");
    let mut keyed_responses = HashMap::new();
    keyed_responses.insert(
        failing_chunk_id.clone(),
        Err(generation::GenerationError::new(
            generation::GenerationErrorKind::ProviderError,
            "simulated extraction failure",
        )),
    );
    // For other long chunks (1, 2, 4, 5, 6), provide valid responses
    for idx in [1, 2, 4, 5, 6] {
        let cid = format!("{doc_id}:{idx}");
        keyed_responses.insert(
            cid,
            Ok(graph::extraction::ExtractionOutput {
                entities: vec![graph::extraction::ExtractedEntity {
                    name: format!("Entity {idx}"),
                    entity_type: "concept".into(),
                }],
                relations: vec![],
            }),
        );
    }

    let fake_gen = graph::extraction::FakeExtractionGenerator::with_keyed_responses(keyed_responses);

    let res = super::extract_and_persist_entities(&database, &job, &fake_gen, &FakeEmbedder).await;
    assert!(res.is_ok(), "D-06: per-chunk extraction failure must not fail function");

    // Short chunk (index 0) skipped (0 calls); 5 long chunks succeed (5 calls); chunk 3 fails and retries 3 times under extract_with_retry (3 calls); total 8 calls
    assert_eq!(fake_gen.calls(), 8, "Short chunk skipped, 5 chunks called once, 1 chunk called 3 times on retries");

    let entities_table = database.entities_table().await.unwrap();
    let count = entities_table.count_rows(None).await.unwrap();
    assert_eq!(count, 5, "5 entities from successful chunks persisted");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn extraction_reingestion_is_idempotent_by_construction() {
    let path = database_path("extraction-reingest-idempotent");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let long_para = "This is a long sentence with enough characters to pass the min chunk content length requirement. ".repeat(3);
    let text = format!("# Section 1\n\n{long_para}\n\n# Section 2\n\n{long_para}");

    let mut metadata = HashMap::new();
    metadata.insert("chunk_strategy".to_string(), "fixed-size".to_string());
    metadata.insert("chunk_size".to_string(), "100".to_string());
    metadata.insert("chunk_overlap".to_string(), "10".to_string());

    let job = IngestionJob::new(
        doc_id.clone(),
        "idempotent.md".into(),
        text.as_bytes().to_vec(),
        metadata,
    );

    let cid_0 = format!("{doc_id}:0");
    let cid_1 = format!("{doc_id}:1");

    let mut keyed_1 = HashMap::new();
    keyed_1.insert(
        cid_0.clone(),
        Ok(graph::extraction::ExtractionOutput {
            entities: vec![graph::extraction::ExtractedEntity {
                name: "Widget".into(),
                entity_type: "product".into(),
            }],
            relations: vec![],
        }),
    );
    keyed_1.insert(
        cid_1.clone(),
        Ok(graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity {
                    name: "Widget".into(),
                    entity_type: "product".into(),
                },
                graph::extraction::ExtractedEntity {
                    name: "Gadget".into(),
                    entity_type: "product".into(),
                },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: "Widget".into(),
                target: "Gadget".into(),
                relation_type: "connected_to".into(),
                confidence: 0.9,
            }],
        }),
    );

    let fake_gen = graph::extraction::FakeExtractionGenerator::with_keyed_responses(keyed_1);

    // First ingestion call
    super::extract_and_persist_entities(&database, &job, &fake_gen, &FakeEmbedder)
        .await
        .unwrap();

    let entities_table = database.entities_table().await.unwrap();
    let edges_table = database.entity_edges_table().await.unwrap();
    let entity_count_1 = entities_table.count_rows(None).await.unwrap();
    let edge_count_1 = edges_table.count_rows(None).await.unwrap();

    assert_eq!(entity_count_1, 2);
    assert_eq!(edge_count_1, 1);

    // Second ingestion call in direct sequence with fresh responses
    let mut keyed_2 = HashMap::new();
    keyed_2.insert(
        cid_0,
        Ok(graph::extraction::ExtractionOutput {
            entities: vec![graph::extraction::ExtractedEntity {
                name: "Widget".into(),
                entity_type: "product".into(),
            }],
            relations: vec![],
        }),
    );
    keyed_2.insert(
        cid_1,
        Ok(graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity {
                    name: "Widget".into(),
                    entity_type: "product".into(),
                },
                graph::extraction::ExtractedEntity {
                    name: "Gadget".into(),
                    entity_type: "product".into(),
                },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: "Widget".into(),
                target: "Gadget".into(),
                relation_type: "connected_to".into(),
                confidence: 0.9,
            }],
        }),
    );

    let fake_gen_2 = graph::extraction::FakeExtractionGenerator::with_keyed_responses(keyed_2);

    super::extract_and_persist_entities(&database, &job, &fake_gen_2, &FakeEmbedder)
        .await
        .unwrap();

    let entities_table_2 = database.entities_table().await.unwrap();
    let edges_table_2 = database.entity_edges_table().await.unwrap();
    let entity_count_2 = entities_table_2.count_rows(None).await.unwrap();
    let edge_count_2 = edges_table_2.count_rows(None).await.unwrap();

    assert_eq!(entity_count_2, 2);
    assert_eq!(edge_count_2, 1);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn cross_document_entity_merge_still_works_under_concurrency() {
    let path = database_path("cross-doc-merge-concurrent");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let long_para = "This is a long sentence with enough characters to pass the min chunk content length requirement. ".repeat(3);

    let doc1_id = Uuid::new_v4().to_string();
    let text1 = format!("# Doc 1\n\nAcme Corp is a company building widgets.\n\n{long_para}");
    let job1 = IngestionJob::new(doc1_id.clone(), "doc1.md".into(), text1.as_bytes().to_vec(), HashMap::new());

    let fake_gen1 = graph::extraction::FakeExtractionGenerator::new(Ok(graph::extraction::ExtractionOutput {
        entities: vec![graph::extraction::ExtractedEntity {
            name: "Acme Corp".into(),
            entity_type: "organization".into(),
        }],
        relations: vec![],
    }));

    super::extract_and_persist_entities(&database, &job1, &fake_gen1, &FakeEmbedder)
        .await
        .unwrap();

    let doc2_id = Uuid::new_v4().to_string();
    let text2 = format!("# Doc 2\n\nacme corp provides widget solutions.\n\n{long_para}");
    let job2 = IngestionJob::new(doc2_id.clone(), "doc2.md".into(), text2.as_bytes().to_vec(), HashMap::new());

    let fake_gen2 = graph::extraction::FakeExtractionGenerator::new(Ok(graph::extraction::ExtractionOutput {
        entities: vec![graph::extraction::ExtractedEntity {
            name: "Acme Corp".into(),
            entity_type: "organization".into(),
        }],
        relations: vec![],
    }));

    super::extract_and_persist_entities(&database, &job2, &fake_gen2, &FakeEmbedder)
        .await
        .unwrap();

    let entities_table = database.entities_table().await.unwrap();
    assert_eq!(entities_table.count_rows(None).await.unwrap(), 1, "Exactly one Acme Corp entity row");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn stale_entity_survives_document_replacement() {
    let path = database_path("stale-entity-survives");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let text1 = "Acme Corp is an organization building software widgets in the global marketplace.";
    stage_document(&database, &doc_id, text1.as_bytes()).await;
    let job1 = read_staged_jobs(&database).await.unwrap().into_iter().next().unwrap();

    let fake_gen1 = graph::extraction::FakeExtractionGenerator::new(Ok(graph::extraction::ExtractionOutput {
        entities: vec![graph::extraction::ExtractedEntity {
            name: "Acme Corp".into(),
            entity_type: "organization".into(),
        }],
        relations: vec![],
    }));

    process_job(&job1, &database, &FakeEmbedder).await.unwrap();
    super::extract_and_persist_entities(&database, &job1, &fake_gen1, &FakeEmbedder).await.unwrap();

    let entities_table = database.entities_table().await.unwrap();
    assert_eq!(entities_table.count_rows(None).await.unwrap(), 1);

    // Replace document with Acme-free content
    let text2 = "Widgets are manufactured with high quality materials in automated factories daily.";
    stage_document(&database, &doc_id, text2.as_bytes()).await;
    let job2 = read_staged_jobs(&database).await.unwrap().into_iter().next().unwrap();

    let fake_gen2 = graph::extraction::FakeExtractionGenerator::new(Ok(graph::extraction::ExtractionOutput {
        entities: vec![graph::extraction::ExtractedEntity {
            name: "Widget".into(),
            entity_type: "product".into(),
        }],
        relations: vec![],
    }));

    process_job(&job2, &database, &FakeEmbedder).await.unwrap();
    super::extract_and_persist_entities(&database, &job2, &fake_gen2, &FakeEmbedder).await.unwrap();

    let fresh_entities_table = database.entities_table().await.unwrap();
    // Acme Corp entity row remains present (v1 documented behavior)
    assert_eq!(fresh_entities_table.count_rows(None).await.unwrap(), 2, "Stale entity Acme Corp survives document replacement");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn stale_source_chunk_ids_can_reference_unrelated_replacement_content() {
    let path = database_path("stale-chunk-unrelated");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let text1 = "Acme Corp is an organization building software widgets in the global marketplace.";
    stage_document(&database, &doc_id, text1.as_bytes()).await;
    let job1 = read_staged_jobs(&database).await.unwrap().into_iter().next().unwrap();

    let fake_gen1 = graph::extraction::FakeExtractionGenerator::new(Ok(graph::extraction::ExtractionOutput {
        entities: vec![graph::extraction::ExtractedEntity {
            name: "Acme Corp".into(),
            entity_type: "organization".into(),
        }],
        relations: vec![],
    }));

    process_job(&job1, &database, &FakeEmbedder).await.unwrap();
    super::extract_and_persist_entities(&database, &job1, &fake_gen1, &FakeEmbedder).await.unwrap();

    // Replace document with Acme-free content at chunk index 0 holding unrelated text
    let text2 = "Unrelated replacement paragraph about widgets and high quality manufacturing.";
    stage_document(&database, &doc_id, text2.as_bytes()).await;
    let job2 = read_staged_jobs(&database).await.unwrap().into_iter().next().unwrap();

    let fake_gen2 = graph::extraction::FakeExtractionGenerator::new(Ok(graph::extraction::ExtractionOutput {
        entities: vec![],
        relations: vec![],
    }));

    process_job(&job2, &database, &FakeEmbedder).await.unwrap();
    super::extract_and_persist_entities(&database, &job2, &fake_gen2, &FakeEmbedder).await.unwrap();

    let chunk_0_id = format!("{doc_id}:0");
    let nodes_table = database.nodes_table().await.unwrap();
    let batches: Vec<RecordBatch> = nodes_table
        .query()
        .only_if(format!("chunk_id = '{}'", escape_sql_literal(&chunk_0_id)))
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap();

    assert_eq!(batches.len(), 1);
    let content_col = batches[0].column_by_name("content").unwrap().as_any().downcast_ref::<StringArray>().unwrap();
    let new_content = content_col.value(0);

    assert!(new_content.contains("Unrelated replacement paragraph"));
    assert!(!new_content.contains("Acme Corp"));

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn extraction_concurrency_bound_is_observed_not_assumed() {
    let path = database_path("extraction-concurrency-bound");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let long_para = "This is a long sentence with enough characters to pass the min chunk content length requirement. ".repeat(3);
    let mut paragraphs = Vec::new();
    for i in 0..12 {
        paragraphs.push(format!("# Section {i}\n\n{long_para}"));
    }
    let text = paragraphs.join("\n\n");

    let job = IngestionJob::new(
        doc_id.clone(),
        "bound.md".into(),
        text.as_bytes().to_vec(),
        HashMap::new(),
    );

    let mut keyed_responses = HashMap::new();
    for i in 0..12 {
        let cid = format!("{doc_id}:{i}");
        keyed_responses.insert(
            cid,
            Ok(graph::extraction::ExtractionOutput {
                entities: vec![graph::extraction::ExtractedEntity {
                    name: format!("Entity {i}"),
                    entity_type: "concept".into(),
                }],
                relations: vec![],
            }),
        );
    }

    let fake_gen = graph::extraction::FakeExtractionGenerator::with_keyed_responses(keyed_responses)
        .with_delay(Duration::from_millis(20));

    super::extract_and_persist_entities(&database, &job, &fake_gen, &FakeEmbedder)
        .await
        .unwrap();

    let max_conc = fake_gen.max_observed_concurrency();
    assert!(max_conc <= 5, "Max observed concurrency must be <= 5 (bound held), got {max_conc}");
    assert!(max_conc >= 2, "Max observed concurrency must be >= 2 (real overlap occurred), got {max_conc}");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn extraction_retries_then_succeeds_within_attempt_budget() {
    let path = database_path("extraction-retry-success");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let text = "This is a long sentence with enough characters to pass the min chunk content length requirement. ".repeat(3);
    let job = IngestionJob::new(
        doc_id.clone(),
        "retry_success.md".into(),
        text.as_bytes().to_vec(),
        HashMap::new(),
    );

    let fake_gen = graph::extraction::FakeExtractionGenerator::with_responses(vec![
        Err(generation::GenerationError::new(
            generation::GenerationErrorKind::SchemaValidation,
            "transient schema validation failure",
        )),
        Ok(graph::extraction::ExtractionOutput {
            entities: vec![graph::extraction::ExtractedEntity {
                name: "RetrySuccess".into(),
                entity_type: "concept".into(),
            }],
            relations: vec![],
        }),
    ]);

    let res = super::extract_and_persist_entities(&database, &job, &fake_gen, &FakeEmbedder).await;
    assert!(res.is_ok());

    assert_eq!(fake_gen.calls(), 2, "Must retry once and succeed on 2nd attempt");

    let entities_table = database.entities_table().await.unwrap();
    assert_eq!(entities_table.count_rows(None).await.unwrap(), 1);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn extraction_retry_exhaustion_yields_zero_entities_not_function_failure() {
    let path = database_path("extraction-retry-exhaustion");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let text = "This is a long sentence with enough characters to pass the min chunk content length requirement. ".repeat(3);
    let job = IngestionJob::new(
        doc_id.clone(),
        "retry_exhaustion.md".into(),
        text.as_bytes().to_vec(),
        HashMap::new(),
    );

    let fake_gen = graph::extraction::FakeExtractionGenerator::with_responses(vec![
        Err(generation::GenerationError::new(
            generation::GenerationErrorKind::ProviderError,
            "attempt 1 fail",
        )),
        Err(generation::GenerationError::new(
            generation::GenerationErrorKind::ProviderError,
            "attempt 2 fail",
        )),
        Err(generation::GenerationError::new(
            generation::GenerationErrorKind::ProviderError,
            "attempt 3 fail",
        )),
    ]);

    let res = super::extract_and_persist_entities(&database, &job, &fake_gen, &FakeEmbedder).await;
    assert!(res.is_ok(), "D-06: retry exhaustion yields zero entities, not function failure");

    assert_eq!(fake_gen.calls(), 3, "Must attempt 3 times total");

    let entities_table = database.entities_table().await.unwrap();
    assert_eq!(entities_table.count_rows(None).await.unwrap(), 0);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn extraction_output_with_out_of_range_confidence_is_rejected_before_persistence() {
    let path = database_path("extraction-confidence-range");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let text = "This is a long sentence with enough characters to pass the min chunk content length requirement. ".repeat(3);
    let job = IngestionJob::new(
        doc_id.clone(),
        "confidence_range.md".into(),
        text.as_bytes().to_vec(),
        HashMap::new(),
    );

    let fake_gen = graph::extraction::FakeExtractionGenerator::with_responses(vec![
        Ok(graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity { name: "Alice".into(), entity_type: "person".into() },
                graph::extraction::ExtractedEntity { name: "Bob".into(), entity_type: "person".into() },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: "Alice".into(),
                target: "Bob".into(),
                relation_type: "knows".into(),
                confidence: 1.5,
            }],
        }),
        Ok(graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity { name: "Alice".into(), entity_type: "person".into() },
                graph::extraction::ExtractedEntity { name: "Bob".into(), entity_type: "person".into() },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: "Alice".into(),
                target: "Bob".into(),
                relation_type: "knows".into(),
                confidence: 1.5,
            }],
        }),
        Ok(graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity { name: "Alice".into(), entity_type: "person".into() },
                graph::extraction::ExtractedEntity { name: "Bob".into(), entity_type: "person".into() },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: "Alice".into(),
                target: "Bob".into(),
                relation_type: "knows".into(),
                confidence: 0.8,
            }],
        }),
    ]);

    let res = super::extract_and_persist_entities(&database, &job, &fake_gen, &FakeEmbedder).await;
    assert!(res.is_ok());
    assert_eq!(fake_gen.calls(), 3);

    let edges_table = database.entity_edges_table().await.unwrap();
    assert_eq!(edges_table.count_rows(None).await.unwrap(), 1, "3rd attempt valid output persisted");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn extract_and_persist_entities_preserves_prior_graph_on_forced_persistence_failure() {
    let path = database_path("extraction-forced-failure");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let text = "This is a long sentence with enough characters to pass the min chunk content length requirement. ".repeat(3);
    let job = IngestionJob::new(
        doc_id.clone(),
        "forced_fail.md".into(),
        text.as_bytes().to_vec(),
        HashMap::new(),
    );

    let fake_gen_1 = graph::extraction::FakeExtractionGenerator::new(Ok(
        graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity { name: "Node1".into(), entity_type: "concept".into() },
                graph::extraction::ExtractedEntity { name: "Node2".into(), entity_type: "concept".into() },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: "Node1".into(),
                target: "Node2".into(),
                relation_type: "links_to".into(),
                confidence: 0.9,
            }],
        },
    ));

    let res1 = super::extract_and_persist_entities(&database, &job, &fake_gen_1, &FakeEmbedder).await;
    assert!(res1.is_ok());

    let edges_table = database.entity_edges_table().await.unwrap();
    let pred = format!("document_id = '{}'", escape_sql_literal(&doc_id));
    let prior_batches: Vec<RecordBatch> = edges_table
        .query()
        .only_if(&pred)
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap();

    let prior_row_count = prior_batches.iter().map(|b| b.num_rows()).sum::<usize>();
    assert!(prior_row_count > 0);

    let prior_edge_ids: Vec<String> = prior_batches
        .iter()
        .flat_map(|b| {
            let col = b.column_by_name("edge_id").unwrap().as_any().downcast_ref::<StringArray>().unwrap();
            (0..b.num_rows()).map(|i| col.value(i).to_string()).collect::<Vec<_>>()
        })
        .collect();

    let fake_gen_2 = graph::extraction::FakeExtractionGenerator::new(Ok(
        graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity { name: "Node3New".into(), entity_type: "concept".into() },
            ],
            relations: vec![],
        },
    ));

    let res2 = super::extract_and_persist_entities(&database, &job, &fake_gen_2, &FailingEmbedder("injected embedding failure".into())).await;
    assert!(res2.is_err(), "Must return Err on forced infrastructure failure during Phase B");

    let post_batches: Vec<RecordBatch> = edges_table
        .query()
        .only_if(&pred)
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap();

    let post_row_count = post_batches.iter().map(|b| b.num_rows()).sum::<usize>();
    assert_eq!(post_row_count, prior_row_count, "Row count must be preserved after Phase B rollback");

    let post_edge_ids: Vec<String> = post_batches
        .iter()
        .flat_map(|b| {
            let col = b.column_by_name("edge_id").unwrap().as_any().downcast_ref::<StringArray>().unwrap();
            (0..b.num_rows()).map(|i| col.value(i).to_string()).collect::<Vec<_>>()
        })
        .collect();

    assert_eq!(post_edge_ids, prior_edge_ids, "Edge IDs must be byte-identical after rollback");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn extraction_persist_summary_reports_coverage_regression() {
    let path = database_path("extraction-coverage-regression");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();

    let long_para = "This is a long sentence with enough characters to pass the min chunk content length requirement. ".repeat(3);
    let text = format!("# Section 1\n\n{long_para}\n\n# Section 2\n\n{long_para}");

    let mut metadata = HashMap::new();
    metadata.insert("chunk_strategy".to_string(), "fixed-size".to_string());
    metadata.insert("chunk_size".to_string(), "100".to_string());
    metadata.insert("chunk_overlap".to_string(), "10".to_string());

    let job = IngestionJob::new(
        doc_id.clone(),
        "regression.md".into(),
        text.as_bytes().to_vec(),
        metadata,
    );

    let cid_0 = format!("{doc_id}:0");
    let cid_1 = format!("{doc_id}:1");

    let mut keyed_1 = HashMap::new();
    keyed_1.insert(
        cid_0.clone(),
        Ok(graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity { name: "E1".into(), entity_type: "concept".into() },
                graph::extraction::ExtractedEntity { name: "E2".into(), entity_type: "concept".into() },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: "E1".into(),
                target: "E2".into(),
                relation_type: "rel1".into(),
                confidence: 0.9,
            }],
        }),
    );
    keyed_1.insert(
        cid_1,
        Ok(graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity { name: "E3".into(), entity_type: "concept".into() },
                graph::extraction::ExtractedEntity { name: "E4".into(), entity_type: "concept".into() },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: "E3".into(),
                target: "E4".into(),
                relation_type: "rel2".into(),
                confidence: 0.9,
            }],
        }),
    );

    let fake_gen_1 = graph::extraction::FakeExtractionGenerator::with_keyed_responses(keyed_1);
    let summary1 = super::extract_and_persist_entities(&database, &job, &fake_gen_1, &FakeEmbedder).await.unwrap();
    assert_eq!(summary1.written_entity_edges_count, 2);

    let mut keyed_2 = HashMap::new();
    keyed_2.insert(
        cid_0,
        Ok(graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity { name: "E1".into(), entity_type: "concept".into() },
                graph::extraction::ExtractedEntity { name: "E2".into(), entity_type: "concept".into() },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: "E1".into(),
                target: "E2".into(),
                relation_type: "rel1".into(),
                confidence: 0.9,
            }],
        }),
    );

    let fake_gen_2 = graph::extraction::FakeExtractionGenerator::with_keyed_responses(keyed_2);
    let summary2 = super::extract_and_persist_entities(&database, &job, &fake_gen_2, &FakeEmbedder).await.unwrap();

    assert_eq!(summary2.prior_entity_edges_count, 2);
    assert_eq!(summary2.written_entity_edges_count, 1);
    assert!(summary2.written_entity_edges_count < summary2.prior_entity_edges_count, "Coverage regression reported in summary");

    let _ = std::fs::remove_dir_all(path);
}

// ── QueryGraph handler ─────────────────────────────────────────────────────────────────────────

/// Construct a minimal LancetServiceImpl wrapping an already-initialized DB for query_graph tests.
async fn query_graph_service_with_db(database: DatabaseManager) -> LancetServiceImpl {
    let nodes = database.nodes_table().await.unwrap();
    let bm25_index = Bm25Index::from_table(&nodes, Bm25Config::default())
        .await
        .unwrap();
    let table = database.staged_documents_table().await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, _receiver) = mpsc::channel(QUEUE_CAPACITY);
    LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        effective_settings: EffectiveRagSettings::default(),
        generator: Arc::new(generation::FakeGenerator::new(Ok(generation::ModelOutput {
            answer: "unused".into(),
            cited_evidence_ids: vec![],
            answer_basis: generation::AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        }))),
        embedder: Arc::new(FakeEmbedder),
        database,
    }
}

/// Construct a minimal LancetServiceImpl backed by a real (but empty) DB for query_graph tests.
async fn query_graph_service(path: &str) -> LancetServiceImpl {
    let database = DatabaseManager::initialize(path).await.unwrap();
    query_graph_service_with_db(database).await
}

/// Seeds a real two-hop entity graph via `extract_and_persist_entities` (mirrors
/// production entity/relation persistence, per D-05's write-time merge convention):
/// `Alice --knows--> Bob --works_at--> Acme`, two distinct edges with distinct
/// `relation_type`s and distinct confidences (persisted as `weight`).
async fn seed_two_hop_graph(path: &str) -> DatabaseManager {
    let database = DatabaseManager::initialize(path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();
    let text = "# Graph Fixture\n\nAlice knows Bob who works at Acme Corporation every single day.";
    let job = IngestionJob::new(
        doc_id,
        "graph-fixture.md".into(),
        text.as_bytes().to_vec(),
        HashMap::new(),
    );

    let fake_gen = graph::extraction::FakeExtractionGenerator::new(Ok(
        graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity {
                    name: "Alice".into(),
                    entity_type: "person".into(),
                },
                graph::extraction::ExtractedEntity {
                    name: "Bob".into(),
                    entity_type: "person".into(),
                },
                graph::extraction::ExtractedEntity {
                    name: "Acme".into(),
                    entity_type: "organization".into(),
                },
            ],
            relations: vec![
                graph::extraction::ExtractedRelation {
                    source: "Alice".into(),
                    target: "Bob".into(),
                    relation_type: "knows".into(),
                    confidence: 0.9,
                },
                graph::extraction::ExtractedRelation {
                    source: "Bob".into(),
                    target: "Acme".into(),
                    relation_type: "works_at".into(),
                    confidence: 0.8,
                },
            ],
        },
    ));

    super::extract_and_persist_entities(&database, &job, &fake_gen, &FakeEmbedder)
        .await
        .unwrap();

    database
}

/// Seeds a single real edge `source_name --relation_type--> target_name` via
/// `extract_and_persist_entities`.
async fn seed_single_edge_graph(
    path: &str,
    source_name: &str,
    target_name: &str,
    relation_type: &str,
) -> DatabaseManager {
    let database = DatabaseManager::initialize(path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();
    let text = format!(
        "# Graph Fixture\n\n{source_name} {relation_type} {target_name} in this scenario every day."
    );
    let job = IngestionJob::new(
        doc_id,
        "graph-edge-fixture.md".into(),
        text.as_bytes().to_vec(),
        HashMap::new(),
    );

    let fake_gen = graph::extraction::FakeExtractionGenerator::new(Ok(
        graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity {
                    name: source_name.into(),
                    entity_type: "person".into(),
                },
                graph::extraction::ExtractedEntity {
                    name: target_name.into(),
                    entity_type: "person".into(),
                },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: source_name.into(),
                target: target_name.into(),
                relation_type: relation_type.into(),
                confidence: 0.75,
            }],
        },
    ));

    super::extract_and_persist_entities(&database, &job, &fake_gen, &FakeEmbedder)
        .await
        .unwrap();

    database
}

/// Blank `seed_entity_id` and blank `seed_entity_name` together must be rejected
/// as `InvalidArgument` before any table scan is attempted.
#[tokio::test]
async fn query_graph_validates_both_blank_seed_inputs_before_db_ops() {
    use engine::pb::lancet::v1::lancet_service_server::LancetService;
    let path = database_path("query-graph-blank-seed");
    let service = query_graph_service(&path).await;

    let err = service
        .query_graph(tonic::Request::new(QueryGraphRequest {
            seed_entity_id: "".into(),
            seed_entity_name: "".into(),
            hop_depth: 1,
            relation_type_filter: "".into(),
        }))
        .await
        .unwrap_err();

    assert_eq!(
        err.code(),
        tonic::Code::InvalidArgument,
        "blank seed must be rejected as InvalidArgument"
    );
    assert!(
        err.message().contains("non-blank"),
        "error message must mention non-blank requirement, got: {}",
        err.message()
    );

    let _ = std::fs::remove_dir_all(path);
}

/// A `seed_entity_name` exceeding `MAX_SEED_ENTITY_NAME_BYTES` must be rejected as
/// `InvalidArgument`, not `NotFound` — proving the length check runs BEFORE the
/// case-folded lookup, not merely instead of it. Constructed as a real, short,
/// stored entity's name padded past the byte ceiling: if the length check were
/// missing or ran after the lookup, the padded name would fail to case-fold-match
/// the shorter stored name and surface as `NotFound`, not `InvalidArgument`.
#[tokio::test]
async fn query_graph_rejects_oversized_seed_entity_name() {
    use engine::pb::lancet::v1::lancet_service_server::LancetService;
    use graph::MAX_SEED_ENTITY_NAME_BYTES;

    let path = database_path("query-graph-oversized-seed-name");
    let database = seed_single_edge_graph(&path, "Al", "Bo", "knows").await;
    let service = query_graph_service_with_db(database).await;

    let padded_name = format!("Al{}", "x".repeat(MAX_SEED_ENTITY_NAME_BYTES));
    assert!(padded_name.len() > MAX_SEED_ENTITY_NAME_BYTES);

    let err = service
        .query_graph(tonic::Request::new(QueryGraphRequest {
            seed_entity_id: "".into(),
            seed_entity_name: padded_name,
            hop_depth: 1,
            relation_type_filter: "".into(),
        }))
        .await
        .unwrap_err();
    assert_eq!(
        err.code(),
        tonic::Code::InvalidArgument,
        "oversized name must be rejected as InvalidArgument (length check runs before lookup), not NotFound; got: {err:?}"
    );
    assert!(
        err.message().contains("seed_entity_name"),
        "error must mention seed_entity_name, got: {}",
        err.message()
    );

    let _ = std::fs::remove_dir_all(path);
}

/// A `relation_type_filter` exceeding `MAX_RELATION_TYPE_FILTER_BYTES` must be rejected
/// as `InvalidArgument`, checked before `fetch_neighborhood`/`narrow_via_cypher` run at
/// all — validation-only, does not require a matching-seed fixture (unlike Test 8).
#[tokio::test]
async fn query_graph_rejects_oversized_relation_type_filter() {
    use engine::pb::lancet::v1::lancet_service_server::LancetService;
    use graph::MAX_RELATION_TYPE_FILTER_BYTES;

    let path = database_path("query-graph-oversized-relation-filter");
    let service = query_graph_service(&path).await;

    let oversized_filter = "y".repeat(MAX_RELATION_TYPE_FILTER_BYTES + 1);
    let err = service
        .query_graph(tonic::Request::new(QueryGraphRequest {
            seed_entity_id: "".into(),
            seed_entity_name: "Alice".into(),
            hop_depth: 1,
            relation_type_filter: oversized_filter,
        }))
        .await
        .unwrap_err();
    assert_eq!(err.code(), tonic::Code::InvalidArgument);
    assert!(
        err.message().contains("relation_type_filter"),
        "error must mention relation_type_filter, got: {}",
        err.message()
    );

    let _ = std::fs::remove_dir_all(path);
}

/// A syntactically invalid UUID in `seed_entity_id` must be rejected as `InvalidArgument`.
#[tokio::test]
async fn query_graph_rejects_malformed_seed_id() {
    use engine::pb::lancet::v1::lancet_service_server::LancetService;
    let path = database_path("query-graph-bad-uuid");
    let service = query_graph_service(&path).await;

    let err = service
        .query_graph(tonic::Request::new(QueryGraphRequest {
            seed_entity_id: "not-a-valid-uuid".into(),
            seed_entity_name: "".into(),
            hop_depth: 1,
            relation_type_filter: "".into(),
        }))
        .await
        .unwrap_err();

    assert_eq!(
        err.code(),
        tonic::Code::InvalidArgument,
        "invalid UUID must be rejected as InvalidArgument"
    );
    assert!(
        err.message().contains("seed_entity_id"),
        "error message must mention seed_entity_id, got: {}",
        err.message()
    );

    let _ = std::fs::remove_dir_all(path);
}

/// A `hop_depth` of `0` or above the configured ceiling must return `InvalidArgument`
/// WITHOUT any `fetch_neighborhood` call occurring: the seed UUID is well-formed but
/// does not exist in the (empty) DB, so if the hop-depth check were skipped or ran
/// after `fetch_neighborhood`, the handler would instead return `Ok` with an empty
/// response (fetch_neighborhood tolerates a nonexistent seed) — a distinguishable
/// success/failure discriminator, not merely a status-code check.
#[tokio::test]
async fn query_graph_rejects_out_of_range_hop_depth() {
    use engine::pb::lancet::v1::lancet_service_server::LancetService;
    let path = database_path("query-graph-hop-depth-range");
    let service = query_graph_service(&path).await;

    let err_zero = service
        .query_graph(tonic::Request::new(QueryGraphRequest {
            seed_entity_id: Uuid::new_v4().to_string(),
            seed_entity_name: "".into(),
            hop_depth: 0,
            relation_type_filter: "".into(),
        }))
        .await
        .unwrap_err();
    assert_eq!(
        err_zero.code(),
        tonic::Code::InvalidArgument,
        "hop_depth=0 must be rejected as InvalidArgument, not silently defaulted to 1; got: {err_zero:?}"
    );

    let err_over = service
        .query_graph(tonic::Request::new(QueryGraphRequest {
            seed_entity_id: Uuid::new_v4().to_string(),
            seed_entity_name: "".into(),
            hop_depth: graph::MAX_HOP_CAP + 1,
            relation_type_filter: "".into(),
        }))
        .await
        .unwrap_err();
    assert_eq!(err_over.code(), tonic::Code::InvalidArgument);

    let _ = std::fs::remove_dir_all(path);
}

/// The redesign's core proof: a `hop_depth = 2` call against a fixture
/// `seed --knows--> neighbor1 --works_at--> neighbor2` (two distinct edges, distinct
/// `relation_type`s) returns `QueryGraphEdge` entries for BOTH edges with correct
/// `relation_type`/`weight` — proving the induced-neighborhood design recovers what
/// the correlate-back design cannot for a 2-hop path, and that the response-affecting
/// `narrow_via_cypher` step is correctness-preserving on real, non-adversarial data.
#[tokio::test]
async fn query_graph_recovers_multi_hop_edge_relation_properties() {
    use engine::pb::lancet::v1::lancet_service_server::LancetService;
    let path = database_path("query-graph-multihop-recover");
    let database = seed_two_hop_graph(&path).await;
    let service = query_graph_service_with_db(database).await;

    let resp = service
        .query_graph(tonic::Request::new(QueryGraphRequest {
            seed_entity_id: "".into(),
            seed_entity_name: "Alice".into(),
            hop_depth: 2,
            relation_type_filter: "".into(),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(
        resp.edges.len(),
        2,
        "both hops' edges must be present, got: {:?}",
        resp.edges
    );
    let by_relation: std::collections::HashMap<&str, &QueryGraphEdge> = resp
        .edges
        .iter()
        .map(|e| (e.relation_type.as_str(), e))
        .collect();

    let knows_edge = by_relation.get("knows").expect("knows edge must be present");
    assert!(
        (knows_edge.weight - 0.9).abs() < 1e-4,
        "knows edge weight must be ~0.9, got {}",
        knows_edge.weight
    );

    let works_edge = by_relation
        .get("works_at")
        .expect("works_at edge must be present");
    assert!(
        (works_edge.weight - 0.8).abs() < 1e-4,
        "works_at edge weight must be ~0.8, got {}",
        works_edge.weight
    );

    assert_eq!(
        resp.nodes.len(),
        3,
        "unfiltered response must include the seed plus both hop neighbors, got: {:?}",
        resp.nodes
    );

    let _ = std::fs::remove_dir_all(path);
}

/// A `hop_depth = 2` call with a `relation_type_filter` set, against a fixture where
/// only ONE of the two hops' edges matches, returns exactly that one matching edge
/// and exactly its two endpoint entities in `.nodes` — nothing from the non-matching
/// first hop, and the seed itself absent from `.nodes` since it is not an endpoint of
/// the matching second edge — proving nodes/edges stay mutually consistent under
/// filtering rather than a full-neighborhood response.
#[tokio::test]
async fn query_graph_relation_filter_correct_at_hop_depth_two() {
    use engine::pb::lancet::v1::lancet_service_server::LancetService;
    let path = database_path("query-graph-relation-filter-hop2");
    let database = seed_two_hop_graph(&path).await;
    let service = query_graph_service_with_db(database).await;

    let resp = service
        .query_graph(tonic::Request::new(QueryGraphRequest {
            seed_entity_id: "".into(),
            seed_entity_name: "Alice".into(),
            hop_depth: 2,
            relation_type_filter: "works_at".into(),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(
        resp.edges.len(),
        1,
        "only the matching hop-2 edge must survive filtering, got: {:?}",
        resp.edges
    );
    assert_eq!(resp.edges[0].relation_type, "works_at");

    assert_eq!(
        resp.nodes.len(),
        2,
        "nodes must be exactly the matching edge's two endpoints, got: {:?}",
        resp.nodes
    );
    let node_names: std::collections::HashSet<&str> =
        resp.nodes.iter().map(|n| n.name.as_str()).collect();
    assert!(node_names.contains("Bob"));
    assert!(node_names.contains("Acme"));
    assert!(
        !node_names.contains("Alice"),
        "seed must be absent — it is not an endpoint of the matching edge"
    );

    let _ = std::fs::remove_dir_all(path);
}

/// A `relation_type_filter` matching ZERO edges in the fetched neighborhood returns
/// `Ok` with empty `.nodes` and empty `.edges` — never `Status::not_found` (a filter
/// matching nothing is a valid, successful "no matching relationships" answer).
#[tokio::test]
async fn query_graph_relation_filter_returns_empty_on_no_match() {
    use engine::pb::lancet::v1::lancet_service_server::LancetService;
    let path = database_path("query-graph-relation-filter-empty");
    let database = seed_two_hop_graph(&path).await;
    let service = query_graph_service_with_db(database).await;

    let resp = service
        .query_graph(tonic::Request::new(QueryGraphRequest {
            seed_entity_id: "".into(),
            seed_entity_name: "Alice".into(),
            hop_depth: 2,
            relation_type_filter: "nonexistent_relation".into(),
        }))
        .await
        .expect("a filter matching zero edges must be Ok, not an error")
        .into_inner();

    assert!(resp.nodes.is_empty(), "zero matching edges must yield empty nodes");
    assert!(resp.edges.is_empty(), "zero matching edges must yield empty edges");

    let _ = std::fs::remove_dir_all(path);
}

/// A seed that is only ever the TARGET of an edge (never the source) still returns
/// that edge in the response (D-24 bidirectionality, reused from `fetch_neighborhood`).
#[tokio::test]
async fn query_graph_bidirectional_seed_as_target() {
    use engine::pb::lancet::v1::lancet_service_server::LancetService;
    let path = database_path("query-graph-bidir-seed-target");
    let database = seed_single_edge_graph(&path, "Carol", "Dave", "mentors").await;
    let service = query_graph_service_with_db(database).await;

    let resp = service
        .query_graph(tonic::Request::new(QueryGraphRequest {
            seed_entity_id: "".into(),
            seed_entity_name: "Dave".into(),
            hop_depth: 1,
            relation_type_filter: "".into(),
        }))
        .await
        .unwrap()
        .into_inner();

    assert_eq!(
        resp.edges.len(),
        1,
        "seed-as-target edge must still be returned (D-24 bidirectionality), got: {:?}",
        resp.edges
    );
    assert_eq!(resp.edges[0].relation_type, "mentors");
    let node_names: std::collections::HashSet<&str> =
        resp.nodes.iter().map(|n| n.name.as_str()).collect();
    assert!(node_names.contains("Carol"));
    assert!(node_names.contains("Dave"));

    let _ = std::fs::remove_dir_all(path);
}

/// With no `relation_type_filter` set, `QueryGraphResponse.nodes` includes the seed
/// entity itself plus every entity reachable within `hop_depth` hops — the explicit
/// response-semantics contract for the unfiltered case.
#[tokio::test]
async fn query_graph_nodes_include_seed_when_unfiltered() {
    use engine::pb::lancet::v1::lancet_service_server::LancetService;
    let path = database_path("query-graph-nodes-include-seed");
    let database = seed_two_hop_graph(&path).await;
    let service = query_graph_service_with_db(database).await;

    let resp = service
        .query_graph(tonic::Request::new(QueryGraphRequest {
            seed_entity_id: "".into(),
            seed_entity_name: "Alice".into(),
            hop_depth: 1,
            relation_type_filter: "".into(),
        }))
        .await
        .unwrap()
        .into_inner();

    let node_names: std::collections::HashSet<&str> =
        resp.nodes.iter().map(|n| n.name.as_str()).collect();
    assert!(
        node_names.contains("Alice"),
        "unfiltered response must include the seed entity itself"
    );
    assert!(
        node_names.contains("Bob"),
        "unfiltered response must include the 1-hop neighbor"
    );
    assert_eq!(
        resp.nodes.len(),
        2,
        "hop_depth=1 must not include the 2-hop-away Acme, got: {:?}",
        resp.nodes
    );

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// 04.1-05: score-interleaved graph-fact packing under a validated, configurable
// graph_weight, plus end-to-end graph_augmentation observability.
// ---------------------------------------------------------------------------

/// Builds a `FusedCandidate` with a controllable `fused_score`/`score` for
/// score-interleaving fixtures.
fn candidate_with_score(id_hint: &str, text: &str, score: f64) -> crate::retrieval::FusedCandidate {
    crate::retrieval::FusedCandidate {
        candidate: crate::retrieval::Candidate {
            document_id: format!("doc-{id_hint}"),
            chunk_id: format!("chk-{id_hint}"),
            chunk_index: 0,
            char_start: 0,
            char_end: text.len() as i32,
            content: text.into(),
            title: Some("Title".into()),
            section_path: Some("/Sec".into()),
            content_type: Some("text/markdown".into()),
            embedding_model: None,
            ingested_at: None,
            score,
        },
        fused_score: score,
        vector_rank: Some(1),
        bm25_rank: None,
        vector_score: Some(score),
        bm25_score: None,
        variant_provenance: Vec::new(),
    }
}

/// Test 1 (04.1-05 Task 1): a single reserved chunk block with a high fused
/// score is placed ahead of a low-scoring graph fact in the packed prompt.
#[test]
fn graph_facts_interleave_by_normalized_score() {
    use crate::graph::context_strategy::GraphFact;
    use crate::prompt::{assemble_evidence_blocks, pack_evidence_and_graph_prompt_sync, GraphFactBlock};

    let candidate = candidate_with_score(
        "hi",
        "High scoring chunk content about the retrieval engine.",
        0.95,
    );
    let evidence = assemble_evidence_blocks(&[candidate]);
    let facts = vec![GraphFactBlock {
        fact: GraphFact::new("Alice", "knows", "Bob", None, 0.1),
    }];

    let packed = pack_evidence_and_graph_prompt_sync("Question?", &evidence, &facts, 1.0, 8192, 512)
        .expect("pack succeeds");

    let evidence_pos = packed
        .prompt
        .find("<EVIDENCE")
        .expect("evidence block rendered");
    let graph_pos = packed
        .prompt
        .find("<GRAPH_FACT")
        .expect("graph fact rendered");
    assert!(
        evidence_pos < graph_pos,
        "the single reserved chunk evidence block must appear ahead of the graph fact"
    );
    assert_eq!(packed.evidence.len(), 1);
    assert_eq!(packed.graph_facts.len(), 1);
}

/// Test 2 (04.1-05 Task 1, Behavior spec — not independently named in
/// `<verify>` but exercised by the same code path as Test 7): with a token
/// budget too small to fit both the second chunk block and the graph fact,
/// the graph fact competes for and wins the shared budget beyond the single
/// reserved slot, excluding the lower-priority second chunk block.
#[test]
fn graph_fact_competes_for_shared_budget_beyond_reserved_slot() {
    use crate::graph::context_strategy::GraphFact;
    use crate::prompt::{assemble_evidence_blocks, pack_evidence_and_graph_prompt_sync, GraphFactBlock};

    let reserved = candidate_with_score(
        "reserved",
        "Reserved top evidence block content for the question asked.",
        0.9,
    );
    let padding = "supplementary detail padding ".repeat(15);
    let second = candidate_with_score(
        "second",
        &format!("Low scoring second chunk block: {padding}"),
        0.2,
    );
    let evidence = assemble_evidence_blocks(&[reserved, second]);
    let facts = vec![GraphFactBlock {
        fact: GraphFact::new("Alice", "knows", "Bob", None, 0.9),
    }];

    let packed = pack_evidence_and_graph_prompt_sync("Question?", &evidence, &facts, 1.0, 330, 32)
        .expect("pack succeeds");

    assert_eq!(
        packed.evidence.len(),
        1,
        "the low-scoring second chunk block must be excluded, packed evidence: {:?}",
        packed.evidence
    );
    assert_eq!(
        packed.graph_facts.len(),
        1,
        "the graph fact must be included, competing for the shared budget"
    );
    assert!(!packed.prompt.contains("padding"));
    assert!(packed.prompt.contains("<GRAPH_FACT"));
}

#[test]
fn pack_evidence_and_graph_prompt_breaks_exact_ties_in_evidence_favor() {
    use crate::graph::context_strategy::GraphFact;
    use crate::prompt::{assemble_evidence_blocks, pack_evidence_and_graph_prompt_sync, GraphFactBlock};

    let reserved = candidate_with_score(
        "reserved",
        "Reserved top evidence block content for the question asked today.",
        0.99,
    );
    let tied_evidence = candidate_with_score(
        "tied",
        "Second evidence block content also relevant to the question today.",
        0.5,
    );
    let evidence = assemble_evidence_blocks(&[reserved, tied_evidence]);
    let facts = vec![GraphFactBlock {
        fact: GraphFact::new("Alice", "knows", "Bob", None, 0.5),
    }];

    let packed = pack_evidence_and_graph_prompt_sync("Question?", &evidence, &facts, 1.0, 350, 16)
        .expect("pack succeeds");

    assert_eq!(packed.evidence.len(), 2);
    assert_eq!(packed.graph_facts.len(), 0);
}

/// Test 3 (04.1-05 Task 1): `graph_weight = 0.0` hard-excludes graph facts
/// from the packed prompt regardless of their raw match score.
#[test]
fn graph_weight_zero_excludes_graph_facts() {
    use crate::graph::context_strategy::GraphFact;
    use crate::prompt::{assemble_evidence_blocks, pack_evidence_and_graph_prompt_sync, GraphFactBlock};

    let candidate = candidate_with_score(
        "only",
        "Sole evidence block content for the question asked.",
        0.5,
    );
    let evidence = assemble_evidence_blocks(&[candidate]);
    let facts = vec![GraphFactBlock {
        fact: GraphFact::new("Alice", "knows", "Bob", None, 0.99),
    }];

    let packed = pack_evidence_and_graph_prompt_sync("Question?", &evidence, &facts, 0.0, 8192, 512)
        .expect("pack succeeds");

    assert!(!packed.prompt.contains("<GRAPH_FACT"));
    assert!(packed.graph_facts.is_empty());
}

/// Test 3b (04.1-05 Task 1, the discriminating case Test 3 alone cannot
/// prove): with a deliberately abundant token budget that would fit every
/// chunk block AND every graph fact, `graph_weight = 0.0` STILL excludes
/// every graph fact — the exclusion is unconditional, not an artifact of a
/// tight budget.
#[test]
fn graph_weight_zero_excludes_graph_facts_even_with_abundant_budget() {
    use crate::graph::context_strategy::GraphFact;
    use crate::prompt::{assemble_evidence_blocks, pack_evidence_and_graph_prompt_sync, GraphFactBlock};

    let candidate = candidate_with_score(
        "only",
        "Sole evidence block content for the question asked.",
        0.5,
    );
    let evidence = assemble_evidence_blocks(&[candidate]);
    let facts = vec![GraphFactBlock {
        fact: GraphFact::new("Alice", "knows", "Bob", None, 0.99),
    }];

    let packed = pack_evidence_and_graph_prompt_sync("Question?", &evidence, &facts, 0.0, 65536, 512)
        .expect("pack succeeds");

    assert!(!packed.prompt.contains("<GRAPH_FACT"));
    assert!(packed.graph_facts.is_empty());
}

/// Test 3c (must-resolve #3, empty-slice panic guard, evidence side): an
/// empty `evidence` slice returns `Err(EmptyEvidence)` regardless of
/// `graph_facts` content — D-27 forbids a compiled answer resting on graph
/// facts alone.
#[test]
fn pack_evidence_and_graph_prompt_empty_evidence_still_errors_regardless_of_graph_facts() {
    use crate::graph::context_strategy::GraphFact;
    use crate::prompt::{
        pack_evidence_and_graph_prompt_sync, EvidenceBlock, GraphFactBlock, PromptAssemblyError,
    };

    let facts = vec![GraphFactBlock {
        fact: GraphFact::new("Alice", "knows", "Bob", None, 0.9),
    }];
    let empty_evidence: Vec<EvidenceBlock> = Vec::new();

    let err = pack_evidence_and_graph_prompt_sync("Question?", &empty_evidence, &facts, 1.0, 8192, 512)
        .expect_err("empty evidence must error even with non-empty graph facts");
    assert_eq!(err, PromptAssemblyError::EmptyEvidence);
}

/// Test 3d (must-resolve #3, empty-slice panic guard, graph-facts side): a
/// non-empty `evidence` slice with an EMPTY `graph_facts` slice returns
/// `Ok(..)` with zero `<GRAPH_FACT>` blocks — no panic, no error.
#[test]
fn pack_evidence_and_graph_prompt_empty_graph_facts_does_not_panic() {
    use crate::prompt::{assemble_evidence_blocks, pack_evidence_and_graph_prompt_sync, GraphFactBlock};

    let candidate = candidate_with_score(
        "only",
        "Sole evidence block content for the question asked.",
        0.5,
    );
    let evidence = assemble_evidence_blocks(&[candidate]);
    let empty_facts: Vec<GraphFactBlock> = Vec::new();

    let packed = pack_evidence_and_graph_prompt_sync("Question?", &evidence, &empty_facts, 1.0, 8192, 512)
        .expect("pack succeeds without panicking on an empty graph_facts slice");
    assert!(!packed.prompt.contains("<GRAPH_FACT"));
    assert!(packed.graph_facts.is_empty());
}

/// Test 4 (04.1-05 Task 1, corrected per REVIEWS.md MEDIUM): every packed
/// chunk `EvidenceBlock` keeps its stable, originally-assigned `[N]` marker
/// regardless of where score-interleaving places it in the packed sequence —
/// markers are never renumbered to reflect "sequential in packed order".
#[test]
fn packed_chunk_markers_stay_stable_under_interleaving() {
    use crate::prompt::{assemble_evidence_blocks, pack_evidence_and_graph_prompt_sync};

    let block0 = candidate_with_score(
        "a",
        "Reserved first block content for the question about retrieval.",
        0.9,
    );
    let block1 = candidate_with_score(
        "b",
        "Low scoring second block content padded out a bit further today.",
        0.1,
    );
    let block2 = candidate_with_score(
        "c",
        "High scoring third block content that outranks the second block.",
        0.8,
    );
    let evidence = assemble_evidence_blocks(&[block0, block1, block2]);
    assert_eq!(evidence[0].id, "[1]");
    assert_eq!(evidence[1].id, "[2]");
    assert_eq!(evidence[2].id, "[3]");

    let packed = pack_evidence_and_graph_prompt_sync("Question?", &evidence, &[], 1.0, 8192, 512)
        .expect("pack succeeds");

    assert_eq!(
        packed.evidence.len(),
        3,
        "all three blocks fit within the generous budget"
    );
    // The reserved block is always first; the remaining two are admitted by
    // descending normalized score — block2 (id "[3]") outranks block1 (id
    // "[2]") and is therefore packed BEFORE it, yet neither marker is
    // renumbered to reflect its new packed position.
    assert_eq!(packed.evidence[0].id, "[1]");
    assert_eq!(packed.evidence[1].id, "[3]");
    assert_eq!(packed.evidence[2].id, "[2]");

    let ids: std::collections::HashSet<&str> =
        packed.evidence.iter().map(|block| block.id.as_str()).collect();
    assert_eq!(ids.len(), 3, "no two packed blocks share a marker");
}

/// Test 5 (04.1-05 Task 1): `RetrievalSettings::validate()` rejects a
/// non-finite, negative, or excessively large `graph_weight` with the same
/// discipline already applied to `vector_weight`/`bm25_weight` — but, unlike
/// those two, `graph_weight == 0.0` alone is a valid explicit opt-out.
#[test]
fn graph_weight_validation_rejects_non_finite_negative_and_oversized() {
    let nan_weight = crate::retrieval::RetrievalSettings {
        graph_weight: f64::NAN,
        ..crate::retrieval::RetrievalSettings::default()
    };
    assert!(nan_weight.validate().is_err());

    let negative_weight = crate::retrieval::RetrievalSettings {
        graph_weight: -0.5,
        ..crate::retrieval::RetrievalSettings::default()
    };
    assert!(negative_weight.validate().is_err());

    let oversized_weight = crate::retrieval::RetrievalSettings {
        graph_weight: crate::retrieval::MAX_SERVICE_RRF_WEIGHT + 1.0,
        ..crate::retrieval::RetrievalSettings::default()
    };
    assert!(oversized_weight.validate().is_err());

    let zero_weight = crate::retrieval::RetrievalSettings {
        graph_weight: 0.0,
        ..crate::retrieval::RetrievalSettings::default()
    };
    assert!(
        zero_weight.validate().is_ok(),
        "graph_weight == 0.0 is a valid explicit opt-out, unlike vector_weight/bm25_weight which forbid a combined zero"
    );

    let valid_weight = crate::retrieval::RetrievalSettings {
        graph_weight: 2.5,
        ..crate::retrieval::RetrievalSettings::default()
    };
    assert!(valid_weight.validate().is_ok());
}

/// Test 6 (04.1-05 Task 1): the reserve-one-citable-chunk rule (Plan 02)
/// still holds under interleaving — a graph fact scored high enough that
/// unbounded interleaving would exclude the sole chunk block still leaves
/// that chunk block packed, because it is reserved before any competition.
#[test]
fn reserve_one_citable_chunk_holds_under_interleaving() {
    use crate::graph::context_strategy::GraphFact;
    use crate::prompt::{assemble_evidence_blocks, pack_evidence_and_graph_prompt_sync, GraphFactBlock};

    let sole_chunk = candidate_with_score(
        "sole",
        "The one and only reserved chunk block content for this question.",
        0.1,
    );
    let evidence = assemble_evidence_blocks(&[sole_chunk]);
    let facts = vec![GraphFactBlock {
        fact: GraphFact::new("Alice", "knows", "Bob", None, 0.99),
    }];

    // Budget sized to fit only the reserved chunk block itself -- no room
    // left for the graph fact's header + body, even though the graph fact's
    // raw score would dominate an unreserved competition.
    let packed = pack_evidence_and_graph_prompt_sync("Question?", &evidence, &facts, 1.0, 300, 16)
        .expect("the reserved chunk block always fits, regardless of graph fact score");

    assert_eq!(
        packed.evidence.len(),
        1,
        "the sole chunk block is always reserved"
    );
    assert_eq!(packed.evidence[0].id, "[1]");
}

fn read_mock_http_request(stream: &mut std::net::TcpStream) -> String {
    use std::io::Read;
    stream
        .set_read_timeout(Some(std::time::Duration::from_secs(2)))
        .expect("set mock read timeout");
    let mut request = Vec::new();
    let mut buffer = [0_u8; 4096];
    loop {
        if let Some(header_end) = request.windows(4).position(|window| window == b"\r\n\r\n") {
            let headers = String::from_utf8_lossy(&request[..header_end]);
            let content_length = headers
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .and_then(|value| value.trim().parse::<usize>().ok())
                })
                .unwrap_or(0);
            if request.len() >= header_end + 4 + content_length {
                break;
            }
        }
        let read = stream.read(&mut buffer).expect("read mock request");
        assert!(read > 0, "mock request ended before its body was received");
        request.extend_from_slice(&buffer[..read]);
    }
    String::from_utf8(request).expect("mock request must be UTF-8")
}

fn write_mock_json_response(stream: &mut std::net::TcpStream, payload: serde_json::Value) {
    use std::io::Write;
    let body = payload.to_string();
    let response = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.len(),
        body
    );
    stream
        .write_all(response.as_bytes())
        .expect("write mock response");
}

/// Runs a single real `query_rag` call through `LancetServiceImpl` and a real
/// local mock HTTP server, capturing the raw outbound `POST /chat/completions`
/// request body. Returns the captured body so the caller can assert on what
/// was actually sent to the provider.
async fn capture_chat_request_body(database: &DatabaseManager, graph_weight: f64) -> String {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind local mock server");
    let addr = listener.local_addr().unwrap();
    let captured_chat: Arc<std::sync::Mutex<Option<String>>> = Arc::new(std::sync::Mutex::new(None));
    let captured_chat_for_server = captured_chat.clone();

    let server_handle = std::thread::spawn(move || {
        let (mut models_stream, _) = listener.accept().expect("accept models request");
        let _ = read_mock_http_request(&mut models_stream);
        write_mock_json_response(
            &mut models_stream,
            serde_json::json!({
                "data": [{
                    "id": "mock/graph-weight-model",
                    "supported_parameters": ["response_format", "json_schema"]
                }]
            }),
        );

        let (mut chat_stream, _) = listener.accept().expect("accept chat request");
        let chat_request = read_mock_http_request(&mut chat_stream);
        *captured_chat_for_server.lock().unwrap() = Some(chat_request);
        write_mock_json_response(
            &mut chat_stream,
            serde_json::json!({
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": serde_json::json!({
                            "answer": "Mock answer [1].",
                            "cited_evidence_ids": ["[1]"],
                            "answer_basis": "retrieval",
                            "notices": [],
                            "warnings": []
                        }).to_string()
                    },
                    "finish_reason": "stop"
                }]
            }),
        );
    });

    let settings = Settings {
        engine: EngineSettings {
            grpc_addr: "127.0.0.1:0".into(),
            lancedb_path: "unused-lancedb-path".into(),
            retrieval: RetrievalConfigSettings {
                candidate_limit: 4,
                final_limit: 2,
                query_max_bytes: 8192,
                max_document_ids: 100,
                max_content_types: 16,
                vector_weight: 0.0,
                bm25_weight: 1.0,
                graph_weight,
                rrf_k: 60.0,
                evidence_token_budget: 382,
                excerpt_max_chars: 512,
                bm25: Bm25ConfigSettings::default(),
            },
            graph: GraphConfigSettings {
                seed_match_min_score: 0.0,
                max_hop_cap: 1,
            },
        },
        openrouter: OpenRouterSettings {
            embedding_endpoint: "https://example.test/v1/embeddings".into(),
            embedding_model: "test/embed".into(),
            generation_model: "mock/graph-weight-model".into(),
            chat_endpoint: format!("http://{addr}/chat/completions"),
            model_metadata_endpoint: format!("http://{addr}/models"),
            generation_timeout_secs: 5,
            temperature: 0.0,
            top_p: 1.0,
            max_output_tokens: 32,
        },
    };

    let effective_settings = EffectiveRagSettings::try_from_settings(&settings)
        .expect("fixture settings must construct EffectiveRagSettings");

    let generation_config = generation::openrouter::OpenRouterGenerationConfig::from_effective_limits(
        effective_settings.generation_model.clone(),
        effective_settings.chat_endpoint.clone(),
        effective_settings.model_metadata_endpoint.clone(),
        std::time::Duration::from_secs(effective_settings.generation_timeout_secs),
        effective_settings.temperature,
        effective_settings.top_p,
        effective_settings.grounding_limits_arc(),
    )
    .expect("generation config must be valid");
    let generator: Arc<dyn generation::Generator> = Arc::new(
        generation::openrouter::OpenRouterGenerator::new_with_config("test-key", generation_config)
            .expect("generator must construct"),
    );

    let service = configured_service(
        database,
        effective_settings,
        Arc::new(FakeEmbedder),
        generator,
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;

    let response = execute_query_rag(
        &service,
        QueryRagRequest {
            query: "keystone retrieval architecture explanation".into(),
            session_id: Uuid::new_v4().to_string(),
            filter: None,
        },
    )
    .await
    .expect("query_rag succeeds through the real generator and mock provider");
    assert_eq!(response.answer, "Mock answer [1].");

    server_handle.join().expect("mock server thread completed");
    let chat_request = captured_chat
        .lock()
        .unwrap()
        .take()
        .expect("chat request was captured");
    chat_request
        .split_once("\r\n\r\n")
        .map(|(_, body)| body.to_string())
        .expect("captured chat request has a body")
}

/// Test 7 (04.1-05 Task 1, REVIEWS.md HIGH): a full `query_rag` call, through
/// the real `LancetServiceImpl` and a real local mock HTTP server capturing
/// the outbound OpenRouter request body, run twice against the same fixture —
/// once with `graph_weight = 1.0` (the graph fact outranks the second chunk
/// block and reaches the real wire payload) and once with `graph_weight =
/// 0.0` (the graph fact is hard-excluded before packing, never reaching the
/// wire, and the second chunk block fills the freed budget instead) —
/// proving the configured value reaches the real outbound provider request,
/// not merely an intermediate `PackedEvidence` value.
#[tokio::test]
async fn graph_weight_reaches_actual_provider_request_body() {
    let path = database_path("graph-weight-reaches-provider-body");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    // Two real chunk candidates: the reserved top block, and a second,
    // competing block that ranks lower under pure BM25 weighting
    // (vector_weight = 0.0 eliminates FakeEmbedder's constant-vector dense
    // tie, so ranking is deterministically driven by keyword overlap).
    let doc_a = Uuid::new_v4().to_string();
    stage_document(
        &database,
        &doc_a,
        b"# Reserved Chunk\n\nKeystone retrieval architecture explanation for the primary reserved evidence block.",
    )
    .await;
    let job_a = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    process_job(&job_a, &database, &FakeEmbedder).await.unwrap();

    let doc_b = Uuid::new_v4().to_string();
    stage_document(
        &database,
        &doc_b,
        b"# Second Chunk\n\nA secondary supplementary passage that barely touches retrieval in passing today.",
    )
    .await;
    let job_b = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    process_job(&job_b, &database, &FakeEmbedder).await.unwrap();

    // A single real graph fact, reachable from the query's embedding via
    // FakeEmbedder's constant vector (seed_match_min_score = 0.0 admits any
    // match; max_hop_cap = 1 returns exactly one edge).
    let graph_job = IngestionJob::new(
        Uuid::new_v4().to_string(),
        "graph-weight-fixture.md".into(),
        b"# Graph Fixture\n\nAlice knows Bob in this fixture scenario every single day.".to_vec(),
        HashMap::new(),
    );
    let fake_extraction_gen = graph::extraction::FakeExtractionGenerator::new(Ok(
        graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity {
                    name: "Alice".into(),
                    entity_type: "person".into(),
                },
                graph::extraction::ExtractedEntity {
                    name: "Bob".into(),
                    entity_type: "person".into(),
                },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: "Alice".into(),
                target: "Bob".into(),
                relation_type: "knows".into(),
                confidence: 0.9,
            }],
        },
    ));
    super::extract_and_persist_entities(&database, &graph_job, &fake_extraction_gen, &FakeEmbedder)
        .await
        .unwrap();

    let weighted_body = capture_chat_request_body(&database, 1.0).await;
    assert!(
        weighted_body.contains("<GRAPH_FACT"),
        "graph_weight = 1.0: the graph fact must reach the real outbound chat request body, got: {weighted_body}"
    );
    assert!(
        !weighted_body.contains("secondary supplementary passage"),
        "graph_weight = 1.0: the lower-priority second chunk block must be excluded when the graph fact outranks it, got: {weighted_body}"
    );

    let excluded_body = capture_chat_request_body(&database, 0.0).await;
    assert!(
        !excluded_body.contains("<GRAPH_FACT"),
        "graph_weight = 0.0: graph facts must be hard-excluded from the real outbound chat request body, got: {excluded_body}"
    );
    assert!(
        excluded_body.contains("secondary supplementary passage"),
        "graph_weight = 0.0: the second chunk block must fill the freed budget, got: {excluded_body}"
    );

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// 04.1-05 Task 2: prove `graph_augmentation` outcome tagging is observable
// through the full `/rag/query` handler for all three outcomes, via a real
// async-safe tracing capture layer (not only Plan 02's isolated-function
// tests).
// ---------------------------------------------------------------------------

/// Test-only `tracing_subscriber::layer::Layer` that captures every recorded
/// `graph_augmentation` field value it observes.
struct GraphAugmentationCaptureLayer {
    captured: Arc<std::sync::Mutex<Vec<String>>>,
}

struct GraphAugmentationVisitor<'a> {
    captured: &'a Arc<std::sync::Mutex<Vec<String>>>,
}

impl tracing::field::Visit for GraphAugmentationVisitor<'_> {
    fn record_str(&mut self, field: &tracing::field::Field, value: &str) {
        if field.name() == "graph_augmentation" {
            self.captured.lock().unwrap().push(value.to_string());
        }
    }

    fn record_debug(&mut self, field: &tracing::field::Field, value: &dyn std::fmt::Debug) {
        if field.name() == "graph_augmentation" {
            self.captured.lock().unwrap().push(format!("{value:?}"));
        }
    }
}

impl<S> tracing_subscriber::layer::Layer<S> for GraphAugmentationCaptureLayer
where
    S: tracing::Subscriber,
{
    fn on_record(
        &self,
        _id: &tracing::span::Id,
        values: &tracing::span::Record<'_>,
        _ctx: tracing_subscriber::layer::Context<'_, S>,
    ) {
        let mut visitor = GraphAugmentationVisitor {
            captured: &self.captured,
        };
        values.record(&mut visitor);
    }
}

/// Test 1 (04.1-05 Task 2): a full `query_rag` call whose seed vector-search
/// finds a matching entity and whose traversal returns at least one neighbor
/// records `graph_augmentation = "succeeded"` on the request's tracing span.
#[tokio::test(flavor = "current_thread")]
async fn graph_augmentation_succeeded_is_observable_end_to_end() {
    use engine::pb::lancet::v1::lancet_service_server::LancetService;
    use tracing_subscriber::layer::SubscriberExt;

    let path = database_path("graph-aug-succeeded-observable");
    let database = seed_single_edge_graph(&path, "Alice", "Bob", "knows").await;
    let service = query_graph_service_with_db(database).await;

    let captured: Arc<std::sync::Mutex<Vec<String>>> = Arc::new(std::sync::Mutex::new(Vec::new()));
    let layer = GraphAugmentationCaptureLayer {
        captured: captured.clone(),
    };
    let subscriber = tracing_subscriber::registry().with(layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let response = execute_query_rag(
        &service,
        QueryRagRequest {
            query: "Alice knows Bob".into(),
            session_id: Uuid::new_v4().to_string(),
            filter: None,
        },
    )
    .await
    .expect("query_rag returns Ok even with graph-only context and no chunk evidence");
    assert!(
        response.notices.iter().any(|n| n.code == "NO_EVIDENCE"),
        "this fixture has no chunk evidence, only graph context"
    );

    let captured = captured.lock().unwrap();
    assert_eq!(captured.as_slice(), ["succeeded"]);

    let _ = std::fs::remove_dir_all(path);
}

/// Test 2 (04.1-05 Task 2): a full `query_rag` call whose seed vector-search
/// finds no entity above `seed_match_min_score` records `graph_augmentation =
/// "no_match_found"` on the span, and the query still returns a normal
/// response.
#[tokio::test(flavor = "current_thread")]
async fn graph_augmentation_no_match_found_is_observable_end_to_end() {
    use engine::pb::lancet::v1::lancet_service_server::LancetService;
    use tracing_subscriber::layer::SubscriberExt;

    let path = database_path("graph-aug-no-match-observable");
    let service = query_graph_service(&path).await;

    let captured: Arc<std::sync::Mutex<Vec<String>>> = Arc::new(std::sync::Mutex::new(Vec::new()));
    let layer = GraphAugmentationCaptureLayer {
        captured: captured.clone(),
    };
    let subscriber = tracing_subscriber::registry().with(layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let response = execute_query_rag(
        &service,
        QueryRagRequest {
            query: "no entities exist in this corpus".into(),
            session_id: Uuid::new_v4().to_string(),
            filter: None,
        },
    )
    .await
    .expect("query_rag returns Ok even when no entity matches and no chunk evidence exists");
    assert!(response.notices.iter().any(|n| n.code == "NO_EVIDENCE"));

    let captured = captured.lock().unwrap();
    assert_eq!(captured.as_slice(), ["no_match_found"]);

    let _ = std::fs::remove_dir_all(path);
}

/// Test 3 (04.1-05 Task 2): a full `query_rag` call under a real forced-fault
/// (deleted LanceDB directory for `entities`) records `graph_augmentation =
/// "attempted_and_failed"` on the span, and the query STILL returns
/// successfully (D-32) — proving the tag is purely observational and never
/// changes the response contract.
#[tokio::test(flavor = "current_thread")]
async fn graph_augmentation_attempted_and_failed_is_observable_end_to_end() {
    use engine::pb::lancet::v1::lancet_service_server::LancetService;
    use tracing_subscriber::layer::SubscriberExt;

    let path = database_path("graph-aug-attempted-failed-observable");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    // Force a real fault: delete the entities table's on-disk LanceDB
    // directory after initialization, so `entities_table()` genuinely fails
    // to open rather than simulating the error path.
    let entities_dir = std::path::Path::new(&path).join("entities.lance");
    std::fs::remove_dir_all(&entities_dir)
        .expect("remove entities.lance to force a real table-open failure");

    let service = query_graph_service_with_db(database).await;

    let captured: Arc<std::sync::Mutex<Vec<String>>> = Arc::new(std::sync::Mutex::new(Vec::new()));
    let layer = GraphAugmentationCaptureLayer {
        captured: captured.clone(),
    };
    let subscriber = tracing_subscriber::registry().with(layer);
    let _guard = tracing::subscriber::set_default(subscriber);

    let response = execute_query_rag(
        &service,
        QueryRagRequest {
            query: "entities table is corrupted".into(),
            session_id: Uuid::new_v4().to_string(),
            filter: None,
        },
    )
    .await
    .expect(
        "query_rag still returns Ok with chunk-only (or NO_EVIDENCE) evidence per D-32, \
         even when graph augmentation attempted and failed",
    );
    assert!(response.notices.iter().any(|n| n.code == "NO_EVIDENCE"));

    let captured = captured.lock().unwrap();
    assert_eq!(captured.as_slice(), ["attempted_and_failed"]);

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// 04.1-06: Gap closure for CR-01, WR-01, and MAX_TOTAL_EDGES
// ---------------------------------------------------------------------------

#[tokio::test]
async fn fetch_neighborhood_returns_both_edges_when_two_documents_share_identical_fact() {
    let path = database_path("fetch-neighborhood-dedup-edge-id");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let doc_a = Uuid::new_v4().to_string();
    let job_a = IngestionJob::new(
        doc_a.clone(),
        "doc_a.md".into(),
        b"Alice knows Bob. This is paragraph one with sufficient content length.".to_vec(),
        HashMap::new(),
    );

    let doc_b = Uuid::new_v4().to_string();
    let job_b = IngestionJob::new(
        doc_b.clone(),
        "doc_b.md".into(),
        b"Alice knows Bob. This is paragraph two with sufficient content length.".to_vec(),
        HashMap::new(),
    );

    let fake_gen = graph::extraction::FakeExtractionGenerator::new(Ok(
        graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity {
                    name: "Alice".into(),
                    entity_type: "person".into(),
                },
                graph::extraction::ExtractedEntity {
                    name: "Bob".into(),
                    entity_type: "person".into(),
                },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: "Alice".into(),
                target: "Bob".into(),
                relation_type: "knows".into(),
                confidence: 0.9,
            }],
        },
    ));

    super::extract_and_persist_entities(&database, &job_a, &fake_gen, &FakeEmbedder)
        .await
        .unwrap();
    super::extract_and_persist_entities(&database, &job_b, &fake_gen, &FakeEmbedder)
        .await
        .unwrap();

    // Verify both documents exist in entity_edges_table separately
    let edges_table = database.entity_edges_table().await.unwrap();
    let doc_a_edges: Vec<arrow_array::RecordBatch> = edges_table
        .query()
        .only_if(format!("document_id = '{doc_a}'"))
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap();
    let doc_b_edges: Vec<arrow_array::RecordBatch> = edges_table
        .query()
        .only_if(format!("document_id = '{doc_b}'"))
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap();

    let doc_a_count: usize = doc_a_edges.iter().map(|b| b.num_rows()).sum();
    let doc_b_count: usize = doc_b_edges.iter().map(|b| b.num_rows()).sum();
    assert_eq!(doc_a_count, 1);
    assert_eq!(doc_b_count, 1);

    let entities_table = database.entities_table().await.unwrap();
    let alice_batches: Vec<arrow_array::RecordBatch> = entities_table
        .query()
        .only_if("name = 'Alice'".to_string())
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap();

    let alice_id_col = alice_batches[0]
        .column_by_name("entity_id")
        .unwrap()
        .as_any()
        .downcast_ref::<arrow_array::StringArray>()
        .unwrap();
    let alice_id = alice_id_col.value(0);

    let (_entities_batch, edges_batch) = graph::fetch_neighborhood(&database, alice_id, 1, true)
        .await
        .expect("fetch_neighborhood must succeed");

    assert_eq!(edges_batch.num_rows(), 2, "both documents' edges must survive dedup");

    let edge_id_col = edges_batch
        .column_by_name("edge_id")
        .expect("edge_id column must exist in fetch_neighborhood result")
        .as_any()
        .downcast_ref::<arrow_array::StringArray>()
        .unwrap();

    let unique_edge_ids: std::collections::HashSet<&str> =
        (0..edges_batch.num_rows()).map(|i| edge_id_col.value(i)).collect();
    assert_eq!(unique_edge_ids.len(), 2, "two distinct edge_id values must exist");

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn fetch_neighborhood_rejects_oversized_edge_batch() {
    use arrow_schema::{DataType, Field, Schema};

    let path = database_path("fetch-neighborhood-rejects-oversized-edge-batch");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let seed_id = Uuid::new_v4().to_string();

    let mut edge_ids = Vec::new();
    let mut sources = Vec::new();
    let mut targets = Vec::new();
    let mut rel_types = Vec::new();
    let mut weights = Vec::new();
    let mut doc_ids = Vec::new();

    let over_limit = graph::MAX_TOTAL_EDGES + 1;
    let shared_doc_id = Uuid::new_v4().to_string();

    for _ in 0..over_limit {
        edge_ids.push(Uuid::new_v4().to_string());
        sources.push(seed_id.clone());
        targets.push(Uuid::new_v4().to_string());
        rel_types.push("related_to".to_string());
        weights.push(0.5_f32);
        doc_ids.push(shared_doc_id.clone());
    }

    let edges_schema = Arc::new(Schema::new(vec![
        Field::new("edge_id", DataType::Utf8, false),
        Field::new("source_node_id", DataType::Utf8, false),
        Field::new("target_node_id", DataType::Utf8, false),
        Field::new("relation_type", DataType::Utf8, false),
        Field::new("weight", DataType::Float32, false),
        Field::new("document_id", DataType::Utf8, false),
    ]));

    let batch = RecordBatch::try_new(
        edges_schema,
        vec![
            Arc::new(StringArray::from(edge_ids)),
            Arc::new(StringArray::from(sources)),
            Arc::new(StringArray::from(targets)),
            Arc::new(StringArray::from(rel_types)),
            Arc::new(arrow_array::Float32Array::from(weights)),
            Arc::new(StringArray::from(doc_ids)),
        ],
    )
    .unwrap();

    let edges_table = database.entity_edges_table().await.unwrap();
    edges_table.add(batch).execute().await.unwrap();

    let err = graph::fetch_neighborhood(&database, &seed_id, 1, true)
        .await
        .expect_err("fetch_neighborhood must reject when accumulated edges exceed MAX_TOTAL_EDGES");

    assert_eq!(err.kind, graph::GraphSpikeErrorKind::Bridge);
    assert!(
        err.message().contains("MAX_TOTAL_EDGES"),
        "error message must mention MAX_TOTAL_EDGES, got: {}",
        err.message()
    );

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn fetch_neighborhood_rejects_oversized_final_hop_frontier() {
    use arrow_schema::{DataType, Field, Schema};

    let path = database_path("fetch-neighborhood-rejects-oversized-final-hop-frontier");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let seed_id = Uuid::new_v4().to_string();
    let hub_id = Uuid::new_v4().to_string();
    let shared_doc_id = Uuid::new_v4().to_string();

    let edges_schema = Arc::new(Schema::new(vec![
        Field::new("edge_id", DataType::Utf8, false),
        Field::new("source_node_id", DataType::Utf8, false),
        Field::new("target_node_id", DataType::Utf8, false),
        Field::new("relation_type", DataType::Utf8, false),
        Field::new("weight", DataType::Float32, false),
        Field::new("document_id", DataType::Utf8, false),
    ]));

    // Hop 1: seed_id -> hub_id
    let hop1_batch = RecordBatch::try_new(
        edges_schema.clone(),
        vec![
            Arc::new(StringArray::from(vec![Uuid::new_v4().to_string()])),
            Arc::new(StringArray::from(vec![seed_id.clone()])),
            Arc::new(StringArray::from(vec![hub_id.clone()])),
            Arc::new(StringArray::from(vec!["parent".to_string()])),
            Arc::new(arrow_array::Float32Array::from(vec![0.5_f32])),
            Arc::new(StringArray::from(vec![shared_doc_id.clone()])),
        ],
    )
    .unwrap();

    // Hop 2: hub_id -> MAX_FRONTIER_SIZE + 1 targets
    let over_limit = graph::MAX_FRONTIER_SIZE + 1;
    let mut edge_ids = Vec::new();
    let mut sources = Vec::new();
    let mut targets = Vec::new();
    let mut rel_types = Vec::new();
    let mut weights = Vec::new();
    let mut doc_ids = Vec::new();

    for _ in 0..over_limit {
        edge_ids.push(Uuid::new_v4().to_string());
        sources.push(hub_id.clone());
        targets.push(Uuid::new_v4().to_string());
        rel_types.push("child".to_string());
        weights.push(0.5_f32);
        doc_ids.push(shared_doc_id.clone());
    }

    let hop2_batch = RecordBatch::try_new(
        edges_schema,
        vec![
            Arc::new(StringArray::from(edge_ids)),
            Arc::new(StringArray::from(sources)),
            Arc::new(StringArray::from(targets)),
            Arc::new(StringArray::from(rel_types)),
            Arc::new(arrow_array::Float32Array::from(weights)),
            Arc::new(StringArray::from(doc_ids)),
        ],
    )
    .unwrap();

    let edges_table = database.entity_edges_table().await.unwrap();
    edges_table.add(hop1_batch).execute().await.unwrap();
    edges_table.add(hop2_batch).execute().await.unwrap();

    let err = graph::fetch_neighborhood(&database, &seed_id, 2, true)
        .await
        .expect_err("fetch_neighborhood must reject when final hop frontier exceeds MAX_FRONTIER_SIZE");

    assert_eq!(err.kind, graph::GraphSpikeErrorKind::Bridge);
    assert!(
        err.message().contains("MAX_FRONTIER_SIZE"),
        "error message must mention MAX_FRONTIER_SIZE, got: {}",
        err.message()
    );

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn fetch_neighborhood_accepts_in_bounds_neighborhood_despite_raw_recount_exceeding_max_total_edges() {
    use arrow_schema::{DataType, Field, Schema};

    let path = database_path("fetch-neighborhood-accepts-in-bounds-neighborhood-despite-raw-recount");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let seed_id = Uuid::new_v4().to_string();
    let hub1_id = Uuid::new_v4().to_string();
    let hub2_id = Uuid::new_v4().to_string();
    let leaf_id = Uuid::new_v4().to_string();
    let shared_doc_id = Uuid::new_v4().to_string();

    let mut edge_ids = Vec::new();
    let mut sources = Vec::new();
    let mut targets = Vec::new();
    let mut rel_types = Vec::new();
    let mut weights = Vec::new();
    let mut doc_ids = Vec::new();

    // Row 0: seed -> hub1
    edge_ids.push(Uuid::new_v4().to_string());
    sources.push(seed_id.clone());
    targets.push(hub1_id.clone());
    rel_types.push("parent".to_string());
    weights.push(0.5_f32);
    doc_ids.push(shared_doc_id.clone());

    // Row 1: hub1 -> hub2
    edge_ids.push(Uuid::new_v4().to_string());
    sources.push(hub1_id.clone());
    targets.push(hub2_id.clone());
    rel_types.push("parent".to_string());
    weights.push(0.5_f32);
    doc_ids.push(shared_doc_id.clone());

    // Rows 2..499 (497 rows): hub2 -> leaf (same leaf_id for all 497 rows)
    for _ in 2..499 {
        edge_ids.push(Uuid::new_v4().to_string());
        sources.push(hub2_id.clone());
        targets.push(leaf_id.clone());
        rel_types.push("child".to_string());
        weights.push(0.5_f32);
        doc_ids.push(shared_doc_id.clone());
    }

    let edges_schema = Arc::new(Schema::new(vec![
        Field::new("edge_id", DataType::Utf8, false),
        Field::new("source_node_id", DataType::Utf8, false),
        Field::new("target_node_id", DataType::Utf8, false),
        Field::new("relation_type", DataType::Utf8, false),
        Field::new("weight", DataType::Float32, false),
        Field::new("document_id", DataType::Utf8, false),
    ]));

    let batch = RecordBatch::try_new(
        edges_schema,
        vec![
            Arc::new(StringArray::from(edge_ids)),
            Arc::new(StringArray::from(sources)),
            Arc::new(StringArray::from(targets)),
            Arc::new(StringArray::from(rel_types)),
            Arc::new(arrow_array::Float32Array::from(weights)),
            Arc::new(StringArray::from(doc_ids)),
        ],
    )
    .unwrap();

    let edges_table = database.entity_edges_table().await.unwrap();
    edges_table.add(batch).execute().await.unwrap();

    let (_entities_batch, edges_batch) = graph::fetch_neighborhood(&database, &seed_id, 3, true)
        .await
        .expect("fetch_neighborhood must accept in-bounds neighborhood despite raw recounted edges exceeding MAX_TOTAL_EDGES");

    assert_eq!(edges_batch.num_rows(), 499);

    let edge_id_col = edges_batch
        .column_by_name("edge_id")
        .and_then(|c| c.as_any().downcast_ref::<StringArray>())
        .expect("edges_batch must carry edge_id column");

    let distinct_edge_ids: std::collections::HashSet<&str> =
        (0..edges_batch.num_rows()).map(|i| edge_id_col.value(i)).collect();

    assert_eq!(distinct_edge_ids.len(), 499);

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// 04.1-07: Queue-driven extraction proof and GraphFact orientation test
// ---------------------------------------------------------------------------

struct KeyedEmbedder {
    vectors: std::collections::HashMap<String, Vec<f32>>,
    default_vector: Vec<f32>,
}

impl EmbeddingProvider for KeyedEmbedder {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move {
            Ok(texts
                .iter()
                .map(|t| {
                    self.vectors
                        .get(t)
                        .cloned()
                        .unwrap_or_else(|| self.default_vector.clone())
                })
                .collect())
        })
    }
}

#[tokio::test]
async fn worker_queue_extracted_graph_facts_reach_provider_request_body() {
    let path = database_path("worker-queue-graph-facts");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let doc_a = Uuid::new_v4().to_string();
    stage_document(
        &database,
        &doc_a,
        b"# Reserved Chunk\n\nKeystone retrieval architecture explanation for the primary reserved evidence block.",
    )
    .await;
    let job_a = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    process_job(&job_a, &database, &FakeEmbedder).await.unwrap();

    let statuses = Arc::new(dashmap::DashMap::new());
    let (tx, rx) = tokio::sync::mpsc::channel(QUEUE_CAPACITY);
    let fake_gen = graph::extraction::FakeExtractionGenerator::new(Ok(
        graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity {
                    name: "Alice".into(),
                    entity_type: "person".into(),
                },
                graph::extraction::ExtractedEntity {
                    name: "Bob".into(),
                    entity_type: "person".into(),
                },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: "Alice".into(),
                target: "Bob".into(),
                relation_type: "knows".into(),
                confidence: 0.9,
            }],
        },
    ));

    let (_shutdown_tx, shutdown_rx) = tokio::sync::watch::channel(false);
    let worker_db = database.clone();
    let worker_statuses = statuses.clone();
    let worker = spawn_worker(
        rx,
        worker_statuses,
        worker_db,
        Arc::new(FakeEmbedder),
        Arc::new(fake_gen),
        shutdown_rx,
    );

    let graph_doc_id = Uuid::new_v4().to_string();
    let graph_job = IngestionJob::new(
        graph_doc_id.clone(),
        "graph-worker-fixture.md".into(),
        b"# Graph Fixture\n\nAlice knows Bob in this fixture scenario every single day.".to_vec(),
        HashMap::new(),
    );
    tx.send(graph_job).await.unwrap();
    drop(tx);

    worker.await.unwrap();

    let status_entry = statuses.get(&graph_doc_id).expect("status must exist");
    assert_eq!(status_entry.status, "completed");

    let entity_count = database.entities_table().await.unwrap().count_rows(None).await.unwrap();
    let edge_count = database.entity_edges_table().await.unwrap().count_rows(None).await.unwrap();
    assert_eq!(entity_count, 2);
    assert_eq!(edge_count, 1);

    let body = capture_chat_request_body(&database, 1.0).await;
    assert!(
        body.contains("<GRAPH_FACT"),
        "body must contain <GRAPH_FACT, got: {body}"
    );

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn graph_fact_preserves_stored_edge_orientation_when_seed_is_target() {
    let path = database_path("graph-fact-orientation-seed-target");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let mut vector_map = std::collections::HashMap::new();
    vector_map.insert("Carol".to_string(), vec![0.9_f32; 2048]);
    vector_map.insert("Dave".to_string(), vec![-0.9_f32; 2048]);

    let embedder = KeyedEmbedder {
        vectors: vector_map,
        default_vector: vec![0.1_f32; 2048],
    };

    let doc_id = Uuid::new_v4().to_string();
    let job = IngestionJob::new(
        doc_id,
        "mentors.md".into(),
        b"# Mentorship\n\nCarol mentors Dave in software engineering.".to_vec(),
        HashMap::new(),
    );

    let fake_gen = graph::extraction::FakeExtractionGenerator::new(Ok(
        graph::extraction::ExtractionOutput {
            entities: vec![
                graph::extraction::ExtractedEntity {
                    name: "Carol".into(),
                    entity_type: "person".into(),
                },
                graph::extraction::ExtractedEntity {
                    name: "Dave".into(),
                    entity_type: "person".into(),
                },
            ],
            relations: vec![graph::extraction::ExtractedRelation {
                source: "Carol".into(),
                target: "Dave".into(),
                relation_type: "mentors".into(),
                confidence: 0.75,
            }],
        },
    ));

    super::extract_and_persist_entities(&database, &job, &fake_gen, &embedder)
        .await
        .unwrap();

    let dave_vector = vec![-0.9_f32; 2048];
    let settings = GraphSettings {
        seed_match_min_score: 0.0,
        max_hop_cap: 3,
    };

    let outcome = attempt_graph_augmentation(&database, &dave_vector, &settings).await;
    if let GraphAugmentationOutcome::Succeeded { facts } = outcome {
        assert_eq!(facts.len(), 1);
        assert_eq!(facts[0].entity_a_name(), "Carol");
        assert_eq!(facts[0].entity_b_name(), "Dave");
    } else {
        panic!("expected GraphAugmentationOutcome::Succeeded");
    }

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn workflow_retrieve_graph() {
    use crate::workflow::Node;
    let (tx, _rx) = tokio::sync::mpsc::channel(100);
    let cancel = tokio_util::sync::CancellationToken::new();
    let sink = crate::workflow::WorkflowEventSink::new(
        tx,
        Arc::new(crate::workflow::EventSequence::new()),
        "test-trace".into(),
        "test-session".into(),
    );

    let req = QueryRagRequest {
        query: "rust test".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: None,
    };
    let ctx = crate::workflow::WorkflowContext::new("test-session".into(), "test-trace".into(), &req);

    let fake_embedder = Arc::new(crate::workflow::ports::FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let fake_graph = Arc::new(crate::workflow::ports::FakeGraphQueryPort::success("fact1 -- rel -- fact2"));
    let fake_dense = Arc::new(crate::workflow::ports::FakeDenseRetrievalPort::success(vec![
        crate::retrieval::Candidate {
            document_id: "doc-1".into(),
            chunk_id: "chunk-1".into(),
            chunk_index: 0,
            char_start: 0,
            char_end: 10,
            content: "dense content".into(),
            title: None,
            section_path: None,
            content_type: Some("text/plain".into()),
            embedding_model: None,
            ingested_at: None,
            score: 0.9,
        }
    ]));
    let fake_bm25 = Arc::new(crate::workflow::ports::FakeBm25RetrievalPort::success(vec![]));

    let mut runner = crate::workflow::WorkflowRunner::new();
    runner.add_node(crate::workflow::nodes::ReformulateQueryNode::new());
    runner.add_node(crate::workflow::nodes::ExtractGraphContextNode::new(Some(fake_embedder.clone()), Some(fake_graph.clone())));
    runner.add_node(crate::workflow::nodes::RetrieveHybridNode::new(
        Some(fake_dense.clone()),
        Some(fake_bm25.clone()),
        None,
        crate::retrieval::RetrievalSettings::default(),
    ));

    let deps = crate::workflow::WorkflowDependencies::new();
    runner.run_tracer(ctx, cancel, sink, &deps, |ctx, deps, sink, cancel| Box::pin(async move { crate::workflow::run_inline_prompt_generation_remainder(ctx, deps, sink, cancel).await })).await;

    assert_eq!(fake_embedder.calls(), 1);
    assert_eq!(fake_graph.calls(), 1);
    assert_eq!(fake_dense.calls(), 1);
    assert_eq!(fake_bm25.calls(), 1);
}

#[tokio::test]
async fn graph_timeout_degrades_to_empty_context() {
    use crate::workflow::Node;
    let (tx, _rx) = tokio::sync::mpsc::channel(100);
    let cancel = tokio_util::sync::CancellationToken::new();
    let sink = crate::workflow::WorkflowEventSink::new(
        tx,
        Arc::new(crate::workflow::EventSequence::new()),
        "test-trace".into(),
        "test-session".into(),
    );

    let req = QueryRagRequest {
        query: "graph timeout test".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: None,
    };
    let mut ctx = crate::workflow::WorkflowContext::new("test-session".into(), "test-trace".into(), &req);

    let fake_embedder = Arc::new(crate::workflow::ports::FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let fake_graph_stalled = Arc::new(crate::workflow::ports::FakeGraphQueryPort::stall());

    let graph_node = crate::workflow::nodes::ExtractGraphContextNode::new(
        Some(fake_embedder),
        Some(fake_graph_stalled),
    ).with_timeouts(5000, 50);

    let res = graph_node.run(&mut ctx, &cancel).await;
    assert!(res.is_ok(), "Graph timeout must degrade gracefully with Ok(()) per D-09");
    assert!(ctx.graph_context.is_empty(), "Graph context must be empty on timeout");
    assert_eq!(ctx.notices.len(), 1, "Must emit exactly 1 degrade notice");
    assert_eq!(ctx.notices[0].message, "GRAPH_TIMEOUT");
}

#[tokio::test]
async fn zero_evidence_short_circuits_generation() {
    use crate::workflow::Node;
    let (tx, mut rx) = tokio::sync::mpsc::channel(100);
    let cancel = tokio_util::sync::CancellationToken::new();
    let sink = crate::workflow::WorkflowEventSink::new(
        tx,
        Arc::new(crate::workflow::EventSequence::new()),
        "test-trace".into(),
        "test-session".into(),
    );

    let req = QueryRagRequest {
        query: "zero evidence test".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: None,
    };
    let ctx = crate::workflow::WorkflowContext::new("test-session".into(), "test-trace".into(), &req);

    let fake_embedder = Arc::new(crate::workflow::ports::FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let fake_dense_empty = Arc::new(crate::workflow::ports::FakeDenseRetrievalPort::success(vec![]));
    let fake_bm25_empty = Arc::new(crate::workflow::ports::FakeBm25RetrievalPort::success(vec![]));

    let mut runner = crate::workflow::WorkflowRunner::new();
    runner.add_node(crate::workflow::nodes::ReformulateQueryNode::new());
    runner.add_node(crate::workflow::nodes::ExtractGraphContextNode::new(Some(fake_embedder), None));
    runner.add_node(crate::workflow::nodes::RetrieveHybridNode::new(
        Some(fake_dense_empty),
        Some(fake_bm25_empty),
        None,
        crate::retrieval::RetrievalSettings::default(),
    ));

    let deps = crate::workflow::WorkflowDependencies::new();
    runner.run_tracer(ctx, cancel, sink, &deps, |ctx, deps, sink, cancel| Box::pin(async move { crate::workflow::run_inline_prompt_generation_remainder(ctx, deps, sink, cancel).await })).await;

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let node_started_names: Vec<String> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(v1::workflow_event::Event::NodeStarted(ns)) => Some(ns.node_name.clone()),
            _ => None,
        })
        .collect();

    assert!(node_started_names.contains(&"ReformulateQuery".to_string()));
    assert!(node_started_names.contains(&"ExtractGraphContext".to_string()));
    assert!(node_started_names.contains(&"RetrieveHybrid".to_string()));
    assert!(!node_started_names.contains(&"AssemblePrompt".to_string()));
    assert!(!node_started_names.contains(&"GenerateAnswer".to_string()));
}

#[tokio::test]
async fn reranker_failure_maps_to_retrieval_failed() {
    use crate::workflow::Node;
    let (tx, _rx) = tokio::sync::mpsc::channel(100);
    let cancel = tokio_util::sync::CancellationToken::new();
    let sink = crate::workflow::WorkflowEventSink::new(
        tx,
        Arc::new(crate::workflow::EventSequence::new()),
        "test-trace".into(),
        "test-session".into(),
    );

    let req = QueryRagRequest {
        query: "reranker failure test".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: None,
    };
    let mut ctx = crate::workflow::WorkflowContext::new("test-session".into(), "test-trace".into(), &req);

    let fake_dense = Arc::new(crate::workflow::ports::FakeDenseRetrievalPort::success(vec![
        crate::retrieval::Candidate {
            document_id: "doc-1".into(),
            chunk_id: "chunk-1".into(),
            chunk_index: 0,
            char_start: 0,
            char_end: 10,
            content: "content".into(),
            title: None,
            section_path: None,
            content_type: Some("text/plain".into()),
            embedding_model: None,
            ingested_at: None,
            score: 0.9,
        }
    ]));
    let fake_failing_reranker = Arc::new(crate::workflow::ports::FakeReranker::failure());

    let retrieve_node = crate::workflow::nodes::RetrieveHybridNode::new(
        Some(fake_dense),
        None,
        Some(fake_failing_reranker),
        crate::retrieval::RetrievalSettings::default(),
    );

    let res = retrieve_node.run(&mut ctx, &cancel).await;
    assert!(res.is_err());
    let err = res.unwrap_err();
    assert_eq!(err.kind, v1::NodeErrorKind::RetrievalFailed);
    assert!(err.message.contains("Reranker failure"));
}

#[tokio::test]
async fn nine_variants_are_rejected_before_retrieval() {
    use crate::workflow::Node;
    let (tx, mut rx) = tokio::sync::mpsc::channel(100);
    let cancel = tokio_util::sync::CancellationToken::new();
    let sink = crate::workflow::WorkflowEventSink::new(
        tx,
        Arc::new(crate::workflow::EventSequence::new()),
        "test-trace".into(),
        "test-session".into(),
    );

    let req = QueryRagRequest {
        query: "9 variants test".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: None,
    };
    let ctx = crate::workflow::WorkflowContext::new("test-session".into(), "test-trace".into(), &req);

    let nine_variants: Vec<String> = (0..9).map(|i| format!("variant-{i}")).collect();
    let fake_reformulator = Arc::new(crate::workflow::ports::FakeQueryReformulator::new(nine_variants));
    let fake_embedder = Arc::new(crate::workflow::ports::FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let fake_graph = Arc::new(crate::workflow::ports::FakeGraphQueryPort::success("graph facts"));
    let fake_dense = Arc::new(crate::workflow::ports::FakeDenseRetrievalPort::success(vec![]));
    let fake_bm25 = Arc::new(crate::workflow::ports::FakeBm25RetrievalPort::success(vec![]));

    let mut runner = crate::workflow::WorkflowRunner::new();
    runner.add_node(crate::workflow::nodes::ReformulateQueryNode::with_reformulator(Some(fake_reformulator)));
    runner.add_node(crate::workflow::nodes::ExtractGraphContextNode::new(Some(fake_embedder.clone()), Some(fake_graph.clone())));
    runner.add_node(crate::workflow::nodes::RetrieveHybridNode::new(
        Some(fake_dense.clone()),
        Some(fake_bm25.clone()),
        None,
        crate::retrieval::RetrievalSettings::default(),
    ));

    let deps = crate::workflow::WorkflowDependencies::new();

    runner.run_tracer(ctx, cancel, sink, &deps, |ctx, deps, sink, cancel| Box::pin(async move { crate::workflow::run_inline_prompt_generation_remainder(ctx, deps, sink, cancel).await })).await;

    assert_eq!(fake_embedder.calls(), 0, "No embedding call must be made when >8 variants are produced");
    assert_eq!(fake_graph.calls(), 0, "No graph call must be made when >8 variants are produced");
    assert_eq!(fake_dense.calls(), 0, "No dense retrieval call must be made when >8 variants are produced");
    assert_eq!(fake_bm25.calls(), 0, "No BM25 retrieval call must be made when >8 variants are produced");

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let failed_event = events.iter().find_map(|e| match &e.event {
        Some(v1::workflow_event::Event::WorkflowCompleted(wc)) => Some(wc),
        _ => None,
    }).expect("WorkflowCompleted event must be emitted");

    assert!(!failed_event.success);
    assert_eq!(failed_event.error_kind, v1::NodeErrorKind::InputValidation as i32);
}

#[tokio::test]
async fn workflow_generation_tracer() {
    use engine::pb::lancet::v1;
    use engine::workflow::EventSequence;
    use std::sync::Arc;
    use tokio::sync::mpsc;
    use tokio_util::sync::CancellationToken;

    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sequence = Arc::new(EventSequence::new());
    let sink = engine::workflow::WorkflowEventSink::new(tx, sequence, "trace-gen".into(), "sess-gen".into());

    let req = v1::QueryRagRequest {
        session_id: "sess-gen".into(),
        query: "What is Lancet engine architecture?".into(),
        filter: None,
    };
    let ctx = engine::workflow::WorkflowContext::new("sess-gen".into(), "trace-gen".into(), &req);

    let fake_reformulator = Arc::new(engine::workflow::ports::FakeQueryReformulator::new(vec!["query variant".into()]));
    let fake_embedder = Arc::new(engine::workflow::ports::FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let fake_graph = Arc::new(engine::workflow::ports::FakeGraphQueryPort::success("graph context fact"));

    let candidate = candidate_with_score("1", "Lancet uses Rust state machine for RAG orchestration.", 0.95).candidate;
    let fake_dense = Arc::new(engine::workflow::ports::FakeDenseRetrievalPort::success(vec![candidate.clone()]));
    let fake_bm25 = Arc::new(engine::workflow::ports::FakeBm25RetrievalPort::success(vec![candidate]));

    let model_out = engine::generation::ModelOutput {
        answer: "Lancet uses a Rust state machine.".into(),
        cited_evidence_ids: vec!["[1]".into()],
        answer_basis: engine::generation::AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        usage: None,
    };
    let fake_generator: Arc<dyn engine::generation::Generator> = Arc::new(engine::generation::FakeGenerator::new(Ok(model_out)));

    let mut runner = engine::workflow::WorkflowRunner::new();
    runner.add_node(engine::workflow::nodes::ReformulateQueryNode::with_reformulator(Some(fake_reformulator)));
    runner.add_node(engine::workflow::nodes::ExtractGraphContextNode::new(Some(fake_embedder), Some(fake_graph)));
    runner.add_node(engine::workflow::nodes::RetrieveHybridNode::new(
        Some(fake_dense),
        Some(fake_bm25),
        None,
        engine::retrieval::RetrievalSettings::default(),
    ));
    runner.add_node(engine::workflow::nodes::AssemblePromptNode::new());
    runner.add_node(engine::workflow::nodes::GenerateAnswerNode::new(Some(fake_generator)));

    runner.run_workflow(ctx, cancel, sink).await;

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let chunk_count = events.iter().filter(|e| matches!(&e.event, Some(v1::workflow_event::Event::AnswerChunk(_)))).count();
    let final_count = events.iter().filter(|e| matches!(&e.event, Some(v1::workflow_event::Event::FinalAnswer(_)))).count();
    assert_eq!(chunk_count, 1, "Exactly one AnswerChunk event must be emitted");
    assert_eq!(final_count, 1, "Exactly one FinalAnswer event must be emitted");

    let completed = events.iter().find_map(|e| match &e.event {
        Some(v1::workflow_event::Event::WorkflowCompleted(wc)) => Some(wc),
        _ => None,
    }).expect("WorkflowCompleted event must be emitted");

    assert!(completed.success);
    assert!(completed.final_response.is_some());
}

#[tokio::test]
async fn generation_retry_request_is_byte_identical() {
    use engine::generation::{GenerationError, GenerationErrorKind, GenerationRequest, Generator, ModelOutput};
    use engine::workflow::EventSequence;
    use std::sync::{Arc, Mutex};
    use tokio::sync::mpsc;
    use tokio_util::sync::CancellationToken;

    struct CapturingGenerator {
        requests: Mutex<Vec<GenerationRequest>>,
    }

    impl Generator for CapturingGenerator {
        fn generate<'a>(
            &'a self,
            request: GenerationRequest,
        ) -> engine::generation::BoxFuture<'a, Result<ModelOutput, GenerationError>> {
            Box::pin(async move {
                let mut reqs = self.requests.lock().unwrap();
                reqs.push(request.clone());
                if reqs.len() == 1 {
                    Err(GenerationError::new(
                        GenerationErrorKind::ProviderError,
                        "Transient HTTP 503 error",
                    ))
                } else {
                    Ok(ModelOutput {
                        answer: "Retried answer succeeded".into(),
                        cited_evidence_ids: vec!["[1]".into()],
                        answer_basis: engine::generation::AnswerBasis::Retrieval,
                        notices: vec![],
                        warnings: vec![],
                        usage: None,
                    })
                }
            })
        }
    }

    let capturing_gen = Arc::new(CapturingGenerator {
        requests: Mutex::new(Vec::new()),
    });

    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sequence = Arc::new(EventSequence::new());
    let sink = engine::workflow::WorkflowEventSink::new(tx, sequence, "trace-retry".into(), "sess-retry".into());

    let req = engine::pb::lancet::v1::QueryRagRequest {
        session_id: "sess-retry".into(),
        query: "Byte identical query?".into(),
        filter: None,
    };
    let mut ctx = engine::workflow::WorkflowContext::new("sess-retry".into(), "trace-retry".into(), &req);
    ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
        id: "[1]".into(),
        chunk_id: "c1".into(),
        document_id: "d1".into(),
        chunk_index: 0,
        title: Some("Doc".into()),
        section_path: Some("Sec".into()),
        content_type: Some("text/plain".into()),
        provenance: "prov".into(),
        text: "Sample text".into(),
        score: 0.9,
        rank: 1,
        suspicious: false,
    }];

    let node = engine::workflow::nodes::GenerateAnswerNode::new(Some(capturing_gen.clone() as Arc<dyn engine::generation::Generator>));

    let runner = engine::workflow::WorkflowRunner::new();
    let res = runner.run_node(&node, &mut ctx, &cancel, &sink).await;
    assert!(res.is_ok(), "GenerateAnswer must succeed on retry attempt 2");

    let reqs = capturing_gen.requests.lock().unwrap().clone();
    assert_eq!(reqs.len(), 2, "Must make exactly 2 generation attempts");
    assert_eq!(reqs[0], reqs[1], "Captured GenerationRequest across attempt 1 and attempt 2 must be byte/field-identical");

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let failed_events = events.iter().filter(|e| matches!(&e.event, Some(engine::pb::lancet::v1::workflow_event::Event::NodeFailed(_)))).count();
    assert_eq!(failed_events, 0, "No retrying/failed event emitted during internal node retry");
}

#[tokio::test]
async fn generation_outer_timeout_allows_retry() {
    use engine::generation::{GenerationError, GenerationErrorKind, GenerationRequest, Generator, ModelOutput};
    use engine::workflow::EventSequence;
    use std::sync::{Arc, Mutex};
    use tokio::sync::mpsc;
    use tokio_util::sync::CancellationToken;

    struct SlowFirstGenerator {
        calls: Mutex<usize>,
    }

    impl Generator for SlowFirstGenerator {
        fn generate<'a>(
            &'a self,
            _request: GenerationRequest,
        ) -> engine::generation::BoxFuture<'a, Result<ModelOutput, GenerationError>> {
            Box::pin(async move {
                let mut count = self.calls.lock().unwrap();
                *count += 1;
                if *count == 1 {
                    Err(GenerationError::new(
                        GenerationErrorKind::Timeout,
                        "Attempt 1 provider timeout",
                    ))
                } else {
                    Ok(ModelOutput {
                        answer: "Attempt 2 fast answer".into(),
                        cited_evidence_ids: vec!["[1]".into()],
                        answer_basis: engine::generation::AnswerBasis::Retrieval,
                        notices: vec![],
                        warnings: vec![],
                        usage: None,
                    })
                }
            })
        }
    }

    let slow_gen = Arc::new(SlowFirstGenerator {
        calls: Mutex::new(0),
    });

    let (tx, _rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sequence = Arc::new(EventSequence::new());
    let sink = engine::workflow::WorkflowEventSink::new(tx, sequence, "trace-timeout".into(), "sess-timeout".into());

    let req = engine::pb::lancet::v1::QueryRagRequest {
        session_id: "sess-timeout".into(),
        query: "Timeout query?".into(),
        filter: None,
    };
    let mut ctx = engine::workflow::WorkflowContext::new("sess-timeout".into(), "trace-timeout".into(), &req);
    ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
        id: "[1]".into(),
        chunk_id: "c1".into(),
        document_id: "d1".into(),
        chunk_index: 0,
        title: Some("Doc".into()),
        section_path: Some("Sec".into()),
        content_type: Some("text/plain".into()),
        provenance: "prov".into(),
        text: "Sample text".into(),
        score: 0.9,
        rank: 1,
        suspicious: false,
    }];

    let node = engine::workflow::nodes::GenerateAnswerNode::new(Some(slow_gen.clone() as Arc<dyn engine::generation::Generator>));

    let runner = engine::workflow::WorkflowRunner::new().with_timeouts(5000, 15000, 10000, 2000, 65000);
    let res = runner.run_node(&node, &mut ctx, &cancel, &sink).await;

    assert!(res.is_ok(), "Outer node timeout budget of 65000ms must allow attempt 2 retry to succeed");
    assert_eq!(*slow_gen.calls.lock().unwrap(), 2);
}

#[tokio::test]
async fn generation_cancellation_between_attempts() {
    use engine::generation::{GenerationError, GenerationErrorKind, GenerationRequest, Generator, ModelOutput};
    use engine::workflow::EventSequence;
    use std::sync::{Arc, Mutex};
    use tokio::sync::mpsc;
    use tokio_util::sync::CancellationToken;

    struct CancellingGenerator {
        calls: Mutex<usize>,
        cancel: CancellationToken,
    }

    impl Generator for CancellingGenerator {
        fn generate<'a>(
            &'a self,
            _request: GenerationRequest,
        ) -> engine::generation::BoxFuture<'a, Result<ModelOutput, GenerationError>> {
            Box::pin(async move {
                let mut count = self.calls.lock().unwrap();
                *count += 1;
                if *count == 1 {
                    self.cancel.cancel();
                    Err(GenerationError::new(
                        GenerationErrorKind::ProviderError,
                        "Attempt 1 transient error",
                    ))
                } else {
                    Ok(ModelOutput {
                        answer: "Should not be reached".into(),
                        cited_evidence_ids: vec!["[1]".into()],
                        answer_basis: engine::generation::AnswerBasis::Retrieval,
                        notices: vec![],
                        warnings: vec![],
                        usage: None,
                    })
                }
            })
        }
    }

    let cancel = CancellationToken::new();
    let cancelling_gen = Arc::new(CancellingGenerator {
        calls: Mutex::new(0),
        cancel: cancel.clone(),
    });

    let (tx, mut rx) = mpsc::channel(100);
    let sequence = Arc::new(EventSequence::new());
    let sink = engine::workflow::WorkflowEventSink::new(tx, sequence, "trace-cancel".into(), "sess-cancel".into());

    let req = engine::pb::lancet::v1::QueryRagRequest {
        session_id: "sess-cancel".into(),
        query: "Cancel query?".into(),
        filter: None,
    };
    let mut ctx = engine::workflow::WorkflowContext::new("sess-cancel".into(), "trace-cancel".into(), &req);
    ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
        id: "[1]".into(),
        chunk_id: "c1".into(),
        document_id: "d1".into(),
        chunk_index: 0,
        title: Some("Doc".into()),
        section_path: Some("Sec".into()),
        content_type: Some("text/plain".into()),
        provenance: "prov".into(),
        text: "Sample text".into(),
        score: 0.9,
        rank: 1,
        suspicious: false,
    }];

    let node = engine::workflow::nodes::GenerateAnswerNode::new(Some(cancelling_gen.clone() as Arc<dyn engine::generation::Generator>));

    let runner = engine::workflow::WorkflowRunner::new();
    let res = runner.run_node(&node, &mut ctx, &cancel, &sink).await;

    assert!(res.is_err());
    let err = res.unwrap_err();
    assert_eq!(err.kind, engine::pb::lancet::v1::NodeErrorKind::Cancelled);
    assert_eq!(*cancelling_gen.calls.lock().unwrap(), 1, "Attempt 2 must not be triggered when cancellation token is cancelled between attempts");

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }
    let chunk_count = events.iter().filter(|e| matches!(&e.event, Some(engine::pb::lancet::v1::workflow_event::Event::AnswerChunk(_)))).count();
    assert_eq!(chunk_count, 0, "No AnswerChunk event must be emitted on cancelled generation");
}

#[tokio::test]
async fn answer_events_have_exact_cardinality() {
    use engine::pb::lancet::v1;
    use engine::workflow::EventSequence;
    use std::sync::Arc;
    use tokio::sync::mpsc;
    use tokio_util::sync::CancellationToken;

    // Scenario A: Happy path with evidence
    {
        let (tx, mut rx) = mpsc::channel(100);
        let cancel = CancellationToken::new();
        let sequence = Arc::new(EventSequence::new());
        let sink = engine::workflow::WorkflowEventSink::new(tx, sequence, "trace-card-a".into(), "sess-card-a".into());

        let req = v1::QueryRagRequest { session_id: "sess-card-a".into(), query: "Card A".into(), filter: None };
        let ctx = engine::workflow::WorkflowContext::new("sess-card-a".into(), "trace-card-a".into(), &req);

        let candidate = candidate_with_score("1", "Content 1", 0.9).candidate;
        let fake_dense = Arc::new(engine::workflow::ports::FakeDenseRetrievalPort::success(vec![candidate]));
        let fake_gen: Arc<dyn engine::generation::Generator> = Arc::new(engine::generation::FakeGenerator::new(Ok(engine::generation::ModelOutput {
            answer: "Answer A".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: engine::generation::AnswerBasis::Retrieval,
            notices: vec![], warnings: vec![], usage: None,
        })));

        let mut runner = engine::workflow::WorkflowRunner::new();
        runner.add_node(engine::workflow::nodes::RetrieveHybridNode::new(Some(fake_dense), None, None, engine::retrieval::RetrievalSettings::default()));
        runner.add_node(engine::workflow::nodes::AssemblePromptNode::new());
        runner.add_node(engine::workflow::nodes::GenerateAnswerNode::new(Some(fake_gen)));

        runner.run_workflow(ctx, cancel, sink).await;

        let mut events = Vec::new();
        while let Ok(item) = rx.try_recv() {
            if let Ok(wf_event) = item { events.push(wf_event); }
        }

        let answer_chunks = events.iter().filter(|e| matches!(&e.event, Some(v1::workflow_event::Event::AnswerChunk(_)))).count();
        let final_answers = events.iter().filter(|e| matches!(&e.event, Some(v1::workflow_event::Event::FinalAnswer(_)))).count();
        assert_eq!(answer_chunks, 1, "Happy path emits exactly 1 AnswerChunk");
        assert_eq!(final_answers, 1, "Happy path emits exactly 1 FinalAnswer");
    }

    // Scenario B: Zero evidence path
    {
        let (tx, mut rx) = mpsc::channel(100);
        let cancel = CancellationToken::new();
        let sequence = Arc::new(EventSequence::new());
        let sink = engine::workflow::WorkflowEventSink::new(tx, sequence, "trace-card-b".into(), "sess-card-b".into());

        let req = v1::QueryRagRequest { session_id: "sess-card-b".into(), query: "Card B".into(), filter: None };
        let ctx = engine::workflow::WorkflowContext::new("sess-card-b".into(), "trace-card-b".into(), &req);

        let fake_dense = Arc::new(engine::workflow::ports::FakeDenseRetrievalPort::success(vec![]));

        let mut runner = engine::workflow::WorkflowRunner::new();
        runner.add_node(engine::workflow::nodes::RetrieveHybridNode::new(Some(fake_dense), None, None, engine::retrieval::RetrievalSettings::default()));
        runner.add_node(engine::workflow::nodes::AssemblePromptNode::new());
        runner.add_node(engine::workflow::nodes::GenerateAnswerNode::new(None));

        runner.run_workflow(ctx, cancel, sink).await;

        let mut events = Vec::new();
        while let Ok(item) = rx.try_recv() {
            if let Ok(wf_event) = item { events.push(wf_event); }
        }

        let answer_chunks = events.iter().filter(|e| matches!(&e.event, Some(v1::workflow_event::Event::AnswerChunk(_)))).count();
        let final_answers = events.iter().filter(|e| matches!(&e.event, Some(v1::workflow_event::Event::FinalAnswer(_)))).count();
        assert_eq!(answer_chunks, 0, "Zero evidence path emits 0 AnswerChunk");
        assert_eq!(final_answers, 1, "Zero evidence path emits exactly 1 FinalAnswer");
    }

    // Scenario C: Exhausted generation failure
    {
        let (tx, mut rx) = mpsc::channel(100);
        let cancel = CancellationToken::new();
        let sequence = Arc::new(EventSequence::new());
        let sink = engine::workflow::WorkflowEventSink::new(tx, sequence, "trace-card-c".into(), "sess-card-c".into());

        let req = v1::QueryRagRequest { session_id: "sess-card-c".into(), query: "Card C".into(), filter: None };
        let ctx = engine::workflow::WorkflowContext::new("sess-card-c".into(), "trace-card-c".into(), &req);

        let candidate = candidate_with_score("1", "Content 1", 0.9).candidate;
        let fake_dense = Arc::new(engine::workflow::ports::FakeDenseRetrievalPort::success(vec![candidate]));
        let failing_gen: Arc<dyn engine::generation::Generator> = Arc::new(engine::generation::FakeGenerator::new(Err(engine::generation::GenerationError::new(
            engine::generation::GenerationErrorKind::ProviderError,
            "Permanent failure",
        ))));

        let mut runner = engine::workflow::WorkflowRunner::new();
        runner.add_node(engine::workflow::nodes::RetrieveHybridNode::new(Some(fake_dense), None, None, engine::retrieval::RetrievalSettings::default()));
        runner.add_node(engine::workflow::nodes::AssemblePromptNode::new());
        runner.add_node(engine::workflow::nodes::GenerateAnswerNode::new(Some(failing_gen)));

        runner.run_workflow(ctx, cancel, sink).await;

        let mut events = Vec::new();
        while let Ok(item) = rx.try_recv() {
            if let Ok(wf_event) = item { events.push(wf_event); }
        }

        let answer_chunks = events.iter().filter(|e| matches!(&e.event, Some(v1::workflow_event::Event::AnswerChunk(_)))).count();
        let final_answers = events.iter().filter(|e| matches!(&e.event, Some(v1::workflow_event::Event::FinalAnswer(_)))).count();
        assert_eq!(answer_chunks, 0, "Failing generation emits 0 AnswerChunk");
        assert_eq!(final_answers, 0, "Failing generation emits 0 FinalAnswer");
    }
}

#[tokio::test]
async fn workflow_answer_contract_preserves_all_fields() {
    use engine::pb::lancet::v1;
    use engine::workflow::EventSequence;
    use std::sync::Arc;
    use tokio::sync::mpsc;
    use tokio_util::sync::CancellationToken;

    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sequence = Arc::new(EventSequence::new());
    let sink = engine::workflow::WorkflowEventSink::new(tx, sequence, "trace-fields".into(), "sess-fields".into());

    let req = v1::QueryRagRequest { session_id: "sess-fields".into(), query: "Preserve fields query".into(), filter: None };
    let ctx = engine::workflow::WorkflowContext::new("sess-fields".into(), "trace-fields".into(), &req);

    let candidate = candidate_with_score("100", "Evidence text for fields preservation test.", 0.88).candidate;
    let fake_dense = Arc::new(engine::workflow::ports::FakeDenseRetrievalPort::success(vec![candidate]));

    let model_out = engine::generation::ModelOutput {
        answer: "Detailed answer string preserving fields.".into(),
        cited_evidence_ids: vec!["[1]".into()],
        answer_basis: engine::generation::AnswerBasis::Retrieval,
        notices: vec!["Notice 1".into()],
        warnings: vec!["Warning 1".into()],
        usage: None,
    };
    let fake_gen: Arc<dyn engine::generation::Generator> = Arc::new(engine::generation::FakeGenerator::new(Ok(model_out)));

    let mut runner = engine::workflow::WorkflowRunner::new();
    runner.add_node(engine::workflow::nodes::RetrieveHybridNode::new(Some(fake_dense), None, None, engine::retrieval::RetrievalSettings::default()));
    runner.add_node(engine::workflow::nodes::AssemblePromptNode::new());
    runner.add_node(engine::workflow::nodes::GenerateAnswerNode::new(Some(fake_gen)));

    runner.run_workflow(ctx, cancel, sink).await;

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item { events.push(wf_event); }
    }

    let final_answer_event = events.iter().find_map(|e| match &e.event {
        Some(v1::workflow_event::Event::FinalAnswer(fa)) => fa.response.clone(),
        _ => None,
    }).expect("FinalAnswer must contain QueryRagResponse");

    assert_eq!(final_answer_event.answer, "Detailed answer string preserving fields.");
    assert_eq!(final_answer_event.citations, vec!["[1]"]);
    assert_eq!(final_answer_event.session_id, "sess-fields");
    assert_eq!(final_answer_event.answer_basis, v1::AnswerBasis::Retrieval as i32);
    assert!(!final_answer_event.structured_citations.is_empty());
    assert_eq!(final_answer_event.structured_citations[0].chunk_id, "chk-100");
    assert_eq!(final_answer_event.structured_citations[0].document_id, "doc-100");
    assert_eq!(final_answer_event.notices.len(), 2);
    assert!(final_answer_event.snapshot.is_some());
    let snapshot = final_answer_event.snapshot.as_ref().unwrap();
    assert_eq!(snapshot.candidate_limit, 32);
    assert_eq!(snapshot.final_limit, 8);
}

#[tokio::test]
async fn prompt_packing_cancellation_is_cooperative() {
    use engine::prompt::{assemble_evidence_blocks, pack_evidence_and_graph_prompt, PromptAssemblyError};
    use tokio_util::sync::CancellationToken;

    let mut fused = Vec::new();
    for i in 0..100 {
        fused.push(candidate_with_score(&format!("{i}"), &format!("Large content block {i} for cancellation testing. ").repeat(20), 0.9 - (i as f64 * 0.001)));
    }

    let evidence = assemble_evidence_blocks(&fused);
    let cancel = CancellationToken::new();
    cancel.cancel();

    let res = pack_evidence_and_graph_prompt("Cancellation test?", &evidence, &[], 1.0, 65536, 2048, &cancel).await;
    assert_eq!(res, Err(PromptAssemblyError::Cancelled), "Cooperative prompt packing must return Cancelled when cancellation token is pre-cancelled");
}






