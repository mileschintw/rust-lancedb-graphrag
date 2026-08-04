use std::{
    collections::{HashMap, HashSet},
    hash::{DefaultHasher, Hash, Hasher},
    path::Path,
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use arrow_array::{
    new_null_array, types::Float32Type, BinaryArray, FixedSizeListArray, Float32Array, Int32Array,
    Int64Array, RecordBatch, StringArray,
};
use dashmap::DashMap;
use futures::{future::BoxFuture, TryStreamExt};
use lancedb::{query::ExecutableQuery, Table};
use serde::Deserialize;
use tokio::{
    sync::{mpsc, watch},
    task::JoinHandle,
};
use tonic::{transport::Server, Request, Response, Status};
use tracing::Instrument;
use uuid::Uuid;

mod chunker;
mod client;
pub mod generation;
pub mod prompt;
mod rerank;
mod retrieval;

use chunker::{chunk_fixed_size, chunk_markdown, estimate_tokens, Chunk};
use client::{OpenRouterClient, EMBEDDING_MODEL};
use engine::db::{DatabaseManager, EntityResolver, ExactMatchResolver};
use retrieval::{
    Bm25Config, Bm25Index, DenseRetriever, QueryRequest, RetrievalErrorKind, Retriever,
};

pub mod lancet {
    pub mod v1 {
        include!("pb/lancet/v1/lancet.v1.rs");
    }
}

use lancet::v1::lancet_service_server::{LancetService, LancetServiceServer};
use lancet::v1::{
    GetIngestionStatusRequest, GetIngestionStatusResponse, IngestDocumentRequest,
    IngestDocumentResponse, PingRequest, PingResponse, QueryGraphRequest, QueryGraphResponse,
    QueryRagRequest, QueryRagResponse,
};

const MAX_DOCUMENT_BYTES: usize = 10 << 20;
const QUEUE_CAPACITY: usize = 100;

fn default_candidate_limit() -> usize {
    32
}
fn default_final_limit() -> usize {
    8
}
fn default_query_max_bytes() -> usize {
    8192
}
fn default_max_document_ids() -> usize {
    100
}
fn default_max_content_types() -> usize {
    16
}
fn default_weight() -> f64 {
    1.0
}
fn default_rrf_k() -> f64 {
    60.0
}
fn default_evidence_token_budget() -> usize {
    8192
}
fn default_excerpt_max_chars() -> usize {
    512
}
fn default_k1() -> f64 {
    1.2
}
fn default_b() -> f64 {
    0.75
}
fn default_title_boost() -> f64 {
    2.0
}
fn default_section_boost() -> f64 {
    1.5
}
fn default_embedding_endpoint() -> String {
    "https://openrouter.ai/api/v1/embeddings".into()
}
fn default_embedding_model() -> String {
    "nvidia/llama-nemotron-embed-vl-1b-v2:free".into()
}
fn default_generation_model() -> String {
    "openai/gpt-4o-mini".into()
}
fn default_chat_endpoint() -> String {
    "https://openrouter.ai/api/v1/chat/completions".into()
}
fn default_models_endpoint() -> String {
    "https://openrouter.ai/api/v1/models".into()
}
fn default_generation_timeout_secs() -> u64 {
    30
}
fn default_temperature() -> f64 {
    0.0
}
fn default_top_p() -> f64 {
    1.0
}
fn default_max_output_tokens() -> u32 {
    2048
}

#[derive(Debug, Clone, Deserialize)]
pub struct Settings {
    pub engine: EngineSettings,
    #[serde(default)]
    pub openrouter: OpenRouterSettings,
}

#[derive(Debug, Clone, Deserialize)]
pub struct EngineSettings {
    pub grpc_addr: String,
    pub lancedb_path: String,
    #[serde(default)]
    pub retrieval: RetrievalConfigSettings,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Bm25ConfigSettings {
    #[serde(default = "default_k1")]
    pub k1: f64,
    #[serde(default = "default_b")]
    pub b: f64,
    #[serde(default = "default_weight")]
    pub content_boost: f64,
    #[serde(default = "default_title_boost")]
    pub title_boost: f64,
    #[serde(default = "default_section_boost")]
    pub section_boost: f64,
}

impl Default for Bm25ConfigSettings {
    fn default() -> Self {
        Self {
            k1: 1.2,
            b: 0.75,
            content_boost: 1.0,
            title_boost: 2.0,
            section_boost: 1.5,
        }
    }
}

impl Bm25ConfigSettings {
    pub fn to_bm25_config(&self) -> Bm25Config {
        Bm25Config {
            k1: self.k1,
            b: self.b,
            content_boost: self.content_boost,
            title_boost: self.title_boost,
            section_path_boost: self.section_boost,
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct RetrievalConfigSettings {
    #[serde(default = "default_candidate_limit")]
    pub candidate_limit: usize,
    #[serde(default = "default_final_limit")]
    pub final_limit: usize,
    #[serde(default = "default_query_max_bytes")]
    pub query_max_bytes: usize,
    #[serde(default = "default_max_document_ids")]
    pub max_document_ids: usize,
    #[serde(default = "default_max_content_types")]
    pub max_content_types: usize,
    #[serde(default = "default_weight")]
    pub vector_weight: f64,
    #[serde(default = "default_weight")]
    pub bm25_weight: f64,
    #[serde(default = "default_rrf_k")]
    pub rrf_k: f64,
    #[serde(default = "default_evidence_token_budget")]
    pub evidence_token_budget: usize,
    #[serde(default = "default_excerpt_max_chars")]
    pub excerpt_max_chars: usize,
    #[serde(default)]
    pub bm25: Bm25ConfigSettings,
}

impl Default for RetrievalConfigSettings {
    fn default() -> Self {
        Self {
            candidate_limit: 32,
            final_limit: 8,
            query_max_bytes: 8192,
            max_document_ids: 100,
            max_content_types: 16,
            vector_weight: 1.0,
            bm25_weight: 1.0,
            rrf_k: 60.0,
            evidence_token_budget: 8192,
            excerpt_max_chars: 512,
            bm25: Bm25ConfigSettings::default(),
        }
    }
}

impl RetrievalConfigSettings {
    pub fn to_retrieval_settings(&self) -> retrieval::RetrievalSettings {
        retrieval::RetrievalSettings {
            candidate_limit: self.candidate_limit,
            final_limit: self.final_limit,
            query_max_bytes: self.query_max_bytes,
            max_document_ids: self.max_document_ids,
            max_content_types: self.max_content_types,
            vector_weight: self.vector_weight,
            bm25_weight: self.bm25_weight,
            rrf_k: self.rrf_k,
            bm25: self.bm25.to_bm25_config(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct OpenRouterSettings {
    #[serde(default = "default_embedding_endpoint")]
    pub embedding_endpoint: String,
    #[serde(default = "default_embedding_model")]
    pub embedding_model: String,
    #[serde(default = "default_generation_model")]
    pub generation_model: String,
    #[serde(default = "default_chat_endpoint")]
    pub chat_endpoint: String,
    #[serde(default = "default_models_endpoint", alias = "models_endpoint")]
    pub model_metadata_endpoint: String,
    #[serde(default = "default_generation_timeout_secs")]
    pub generation_timeout_secs: u64,
    #[serde(default = "default_temperature")]
    pub temperature: f64,
    #[serde(default = "default_top_p")]
    pub top_p: f64,
    #[serde(default = "default_max_output_tokens")]
    pub max_output_tokens: u32,
}

impl Default for OpenRouterSettings {
    fn default() -> Self {
        Self {
            embedding_endpoint: "https://openrouter.ai/api/v1/embeddings".into(),
            embedding_model: "nvidia/llama-nemotron-embed-vl-1b-v2:free".into(),
            generation_model: "openai/gpt-4o-mini".into(),
            chat_endpoint: "https://openrouter.ai/api/v1/chat/completions".into(),
            model_metadata_endpoint: "https://openrouter.ai/api/v1/models".into(),
            generation_timeout_secs: 30,
            temperature: 0.0,
            top_p: 1.0,
            max_output_tokens: 2048,
        }
    }
}

fn load_settings() -> Result<Settings, config::ConfigError> {
    let base_path = if let Ok(dir) = std::env::var("LANCET_CONFIG_DIR") {
        if !dir.trim().is_empty() {
            let trimmed = dir.trim().trim_end_matches(['/', '\\']);
            format!("{trimmed}/config")
        } else if std::path::Path::new("../config/config.toml").exists() {
            "../config/config".to_string()
        } else {
            "config/config".to_string()
        }
    } else if std::path::Path::new("../config/config.toml").exists() {
        "../config/config".to_string()
    } else {
        "config/config".to_string()
    };
    let mut builder = config::Config::builder().add_source(config::File::with_name(&base_path));
    if let Ok(environment) = std::env::var("LANCET_ENV") {
        if !environment.trim().is_empty() {
            let env_path = format!("{base_path}.{}", environment.trim());
            builder = builder.add_source(config::File::with_name(&env_path).required(false));
        }
    }
    let mut settings: Settings = builder
        .add_source(config::Environment::with_prefix("LANCET").separator("__"))
        .build()?
        .try_deserialize()?;

    // Keep the process-test and deployment override names explicit at the
    // boundary. This also makes the double-underscore contract independent of
    // config crate version-specific environment parsing details.
    if let Ok(value) = std::env::var("LANCET_ENGINE__GRPC_ADDR") {
        if !value.trim().is_empty() {
            settings.engine.grpc_addr = value;
        }
    }
    if let Ok(value) = std::env::var("LANCET_ENGINE__LANCEDB_PATH") {
        if !value.trim().is_empty() {
            settings.engine.lancedb_path = value;
        }
    }
    if let Ok(value) = std::env::var("LANCET_OPENROUTER__EMBEDDING_ENDPOINT") {
        if !value.trim().is_empty() {
            settings.openrouter.embedding_endpoint = value;
        }
    }
    if let Ok(value) = std::env::var("LANCET_OPENROUTER__MODEL_METADATA_ENDPOINT") {
        if !value.trim().is_empty() {
            settings.openrouter.model_metadata_endpoint = value;
        }
    }
    if let Ok(value) = std::env::var("LANCET_OPENROUTER__CHAT_ENDPOINT") {
        if !value.trim().is_empty() {
            settings.openrouter.chat_endpoint = value;
        }
    }
    Ok(settings)
}

#[derive(Debug, Clone)]
struct IngestionStatus {
    status: String,
    chunk_count: i32,
    error_message: String,
}
impl IngestionStatus {
    fn queued() -> Self {
        Self {
            status: "queued".into(),
            chunk_count: 0,
            error_message: String::new(),
        }
    }
}

const DEFAULT_CHUNK_SIZE: usize = 500;
const DEFAULT_CHUNK_OVERLAP: usize = 50;
pub const MAX_CHUNK_SIZE: usize = 1048576;

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct ChunkSettings {
    pub strategy: String,
    pub size: usize,
    pub overlap: usize,
}

impl Default for ChunkSettings {
    fn default() -> Self {
        Self {
            strategy: "structure-aware".into(),
            size: DEFAULT_CHUNK_SIZE,
            overlap: DEFAULT_CHUNK_OVERLAP,
        }
    }
}

fn parse_chunk_settings(metadata: &HashMap<String, String>) -> Result<ChunkSettings, Status> {
    let strategy = metadata
        .get("chunk_strategy")
        .ok_or_else(|| Status::invalid_argument("missing metadata key: chunk_strategy"))?;
    if strategy != "structure-aware" && strategy != "fixed-size" {
        return Err(Status::invalid_argument(format!(
            "invalid chunk_strategy: {strategy}"
        )));
    }
    let size_str = metadata
        .get("chunk_size")
        .ok_or_else(|| Status::invalid_argument("missing metadata key: chunk_size"))?;
    let size: usize = size_str
        .parse()
        .map_err(|_| Status::invalid_argument("invalid chunk_size: must be a positive integer"))?;
    if size == 0 {
        return Err(Status::invalid_argument(
            "invalid chunk_size: must be greater than 0",
        ));
    }
    if size > MAX_CHUNK_SIZE {
        return Err(Status::invalid_argument(format!(
            "invalid chunk_size: must not exceed {MAX_CHUNK_SIZE}"
        )));
    }
    let overlap_str = metadata
        .get("chunk_overlap")
        .ok_or_else(|| Status::invalid_argument("missing metadata key: chunk_overlap"))?;
    let overlap: usize = overlap_str.parse().map_err(|_| {
        Status::invalid_argument("invalid chunk_overlap: must be a non-negative integer")
    })?;
    if overlap >= size {
        return Err(Status::invalid_argument(
            "invalid chunk_overlap: must be smaller than chunk_size",
        ));
    }
    Ok(ChunkSettings {
        strategy: strategy.clone(),
        size,
        overlap,
    })
}

#[derive(Debug)]
pub struct IngestionJob {
    pub document_id: String,
    pub filename: String,
    pub raw_data: Vec<u8>,
    pub metadata: HashMap<String, String>,
    pub chunk_settings: ChunkSettings,
}

impl IngestionJob {
    pub fn new(
        document_id: String,
        filename: String,
        raw_data: Vec<u8>,
        metadata: HashMap<String, String>,
    ) -> Self {
        let chunk_settings = parse_chunk_settings(&metadata).unwrap_or_default();
        Self {
            document_id,
            filename,
            raw_data,
            metadata,
            chunk_settings,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ReplacementMutation {
    EdgesDelete,
    NodesDelete,
    DocumentsDelete,
    DocumentsAdd,
    NodesAdd,
    EdgesAdd,
    StagingDelete,
}

trait ReplacementMutationBoundary: Send + Sync {
    fn delete<'a>(
        &self,
        boundary: ReplacementMutation,
        table: &'a Table,
        predicate: &'a str,
    ) -> BoxFuture<'a, Result<(), String>>;

    fn add<'a>(
        &self,
        boundary: ReplacementMutation,
        table: &'a Table,
        batch: RecordBatch,
    ) -> BoxFuture<'a, Result<(), String>>;

    fn field_with_name<'a>(
        &self,
        schema: &'a arrow_schema::Schema,
        name: &str,
    ) -> Result<&'a arrow_schema::Field, String> {
        schema
            .field_with_name(name)
            .map_err(|error| format!("validated schema missing field {name}: {error}"))
    }
}

struct LanceDbReplacementMutationBoundary;

impl ReplacementMutationBoundary for LanceDbReplacementMutationBoundary {
    fn delete<'a>(
        &self,
        boundary: ReplacementMutation,
        table: &'a Table,
        predicate: &'a str,
    ) -> BoxFuture<'a, Result<(), String>> {
        Box::pin(async move {
            table
                .delete(predicate)
                .await
                .map(|_| ())
                .map_err(|error| format!("{boundary:?}: {error}"))
        })
    }

    fn add<'a>(
        &self,
        boundary: ReplacementMutation,
        table: &'a Table,
        batch: RecordBatch,
    ) -> BoxFuture<'a, Result<(), String>> {
        Box::pin(async move {
            table
                .add(batch)
                .execute()
                .await
                .map(|_| ())
                .map_err(|error| format!("{boundary:?}: {error}"))
        })
    }
}

fn chunk_ingestion_job(job: &IngestionJob) -> (&'static str, Vec<Chunk>) {
    let is_json = Path::new(&job.filename)
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("json"));
    let strategy = if is_json || job.chunk_settings.strategy == "fixed-size" {
        "fixed-size"
    } else {
        "structure-aware"
    };
    let target_size = job.chunk_settings.size;
    let overlap = job.chunk_settings.overlap;
    let text = String::from_utf8_lossy(&job.raw_data);
    let mut chunks = if strategy == "fixed-size" {
        chunk_fixed_size(&text, target_size, overlap)
    } else {
        chunk_markdown(&text, target_size, overlap)
    };
    for chunk in &mut chunks {
        chunk.estimated_tokens = estimate_tokens(&chunk.content);
    }
    (strategy, chunks)
}

pub async fn read_staged_jobs(database: &DatabaseManager) -> Result<Vec<IngestionJob>, String> {
    let table = database.staged_documents_table().await?;
    let batches: Vec<RecordBatch> = table
        .query()
        .execute()
        .await
        .map_err(|error| format!("failed to query staged_documents_v2: {error}"))?
        .try_collect()
        .await
        .map_err(|error| format!("failed to collect staged_documents_v2 rows: {error}"))?;

    let mut jobs = Vec::new();
    let mut seen_ids = HashSet::new();

    for batch in &batches {
        let doc_ids = batch
            .column_by_name("document_id")
            .ok_or("staged_documents_v2 missing document_id column")?
            .as_any()
            .downcast_ref::<StringArray>()
            .ok_or("invalid document_id array type in staged_documents_v2")?;
        let filenames = batch
            .column_by_name("filename")
            .ok_or("staged_documents_v2 missing filename column")?
            .as_any()
            .downcast_ref::<StringArray>()
            .ok_or("invalid filename array type in staged_documents_v2")?;
        let raw_contents = batch
            .column_by_name("raw_content")
            .ok_or("staged_documents_v2 missing raw_content column")?
            .as_any()
            .downcast_ref::<BinaryArray>()
            .ok_or("invalid raw_content array type in staged_documents_v2")?;
        let strategies = batch
            .column_by_name("chunk_strategy")
            .ok_or("staged_documents_v2 missing chunk_strategy column")?
            .as_any()
            .downcast_ref::<StringArray>()
            .ok_or("invalid chunk_strategy array type in staged_documents_v2")?;
        let sizes = batch
            .column_by_name("chunk_size")
            .ok_or("staged_documents_v2 missing chunk_size column")?
            .as_any()
            .downcast_ref::<Int32Array>()
            .ok_or("invalid chunk_size array type in staged_documents_v2")?;
        let overlaps = batch
            .column_by_name("chunk_overlap")
            .ok_or("staged_documents_v2 missing chunk_overlap column")?
            .as_any()
            .downcast_ref::<Int32Array>()
            .ok_or("invalid chunk_overlap array type in staged_documents_v2")?;

        for i in 0..batch.num_rows() {
            let doc_id = doc_ids.value(i).to_string();
            if !seen_ids.insert(doc_id.clone()) {
                continue;
            }
            if validate_document_id(&doc_id).is_err() {
                return Err(format!("malformed staged document_id: {doc_id}"));
            }
            let filename = filenames.value(i).to_string();
            let raw_data = raw_contents.value(i).to_vec();
            let strategy = strategies.value(i).to_string();
            let size = usize::try_from(sizes.value(i))
                .map_err(|_| format!("negative chunk_size in staging for document {doc_id}"))?;
            let overlap = usize::try_from(overlaps.value(i))
                .map_err(|_| format!("negative chunk_overlap in staging for document {doc_id}"))?;

            let metadata = HashMap::from([
                ("chunk_strategy".to_string(), strategy),
                ("chunk_size".to_string(), size.to_string()),
                ("chunk_overlap".to_string(), overlap.to_string()),
            ]);

            let chunk_settings = parse_chunk_settings(&metadata).map_err(|error| {
                format!("malformed chunk settings in staging for document {doc_id}: {error}")
            })?;

            jobs.push(IngestionJob {
                document_id: doc_id,
                filename,
                raw_data,
                metadata,
                chunk_settings,
            });
        }
    }

    Ok(jobs)
}

#[derive(Clone)]
pub struct LancetServiceImpl {
    table: Table,
    statuses: Arc<DashMap<String, IngestionStatus>>,
    queue: mpsc::Sender<IngestionJob>,
    nodes: Table,
    bm25_index: Arc<tokio::sync::RwLock<Bm25Index>>,
    retrieval_settings: retrieval::RetrievalSettings,
    generator: Arc<dyn generation::Generator>,
    embedder: Arc<dyn EmbeddingProvider>,
}

impl LancetServiceImpl {
    async fn persist_raw(&self, job: &IngestionJob) -> Result<(), Status> {
        let predicate = format!("document_id = '{}'", sql_string(&job.document_id));
        self.table.delete(&predicate).await.map_err(internal)?;
        let schema = self.table.schema().await.map_err(internal)?;
        let batch = RecordBatch::try_new(
            schema,
            vec![
                Arc::new(StringArray::from(vec![job.document_id.as_str()])),
                Arc::new(StringArray::from(vec![job.filename.as_str()])),
                Arc::new(BinaryArray::from_vec(vec![job.raw_data.as_slice()])),
                Arc::new(StringArray::from(vec![job
                    .chunk_settings
                    .strategy
                    .as_str()])),
                Arc::new(Int32Array::from(vec![i32::try_from(
                    job.chunk_settings.size,
                )
                .unwrap_or(i32::MAX)])),
                Arc::new(Int32Array::from(vec![i32::try_from(
                    job.chunk_settings.overlap,
                )
                .unwrap_or(i32::MAX)])),
            ],
        )
        .map_err(internal)?;
        self.table.add(batch).execute().await.map_err(internal)?;
        Ok(())
    }
}

fn internal(err: impl std::fmt::Display) -> Status {
    Status::internal(err.to_string())
}

fn validate_document_id(document_id: &str) -> Result<(), Status> {
    let id = Uuid::parse_str(document_id)
        .map_err(|_| Status::invalid_argument("document_id must be a UUIDv4 string"))?;
    if id.get_version_num() != 4 || id.get_variant() != uuid::Variant::RFC4122 {
        return Err(Status::invalid_argument(
            "document_id must be a UUIDv4 string",
        ));
    }
    Ok(())
}

#[tonic::async_trait]
impl LancetService for LancetServiceImpl {
    async fn ping(&self, request: Request<PingRequest>) -> Result<Response<PingResponse>, Status> {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(internal)?
            .as_millis() as i64;
        Ok(Response::new(PingResponse {
            value: format!("pong: {}", request.into_inner().value),
            timestamp,
        }))
    }

    async fn ingest_document(
        &self,
        request: Request<tonic::Streaming<IngestDocumentRequest>>,
    ) -> Result<Response<IngestDocumentResponse>, Status> {
        let mut stream = request.into_inner();
        let mut document_id = String::new();
        let mut filename = String::new();
        let mut metadata = HashMap::new();
        let mut raw = Vec::new();
        let mut first_frame = true;
        let mut parsed_settings = None;
        while let Some(message) = stream.message().await? {
            if first_frame {
                first_frame = false;
                document_id = message.document_id.clone();
                filename = message.filename.clone();
                metadata = message.metadata.clone();
                parsed_settings = Some(parse_chunk_settings(&metadata)?);
            } else {
                if !message.metadata.is_empty() {
                    return Err(Status::invalid_argument(
                        "stream metadata must not be provided on subsequent frames",
                    ));
                }
            }
            if message.document_id != document_id {
                return Err(Status::invalid_argument(
                    "stream contains multiple document ids",
                ));
            }
            if raw.len() + message.chunk_data.len() > MAX_DOCUMENT_BYTES {
                return Err(Status::resource_exhausted("document exceeds 10MB"));
            }
            raw.extend_from_slice(&message.chunk_data);
        }
        if document_id.is_empty() {
            return Err(Status::invalid_argument("empty ingestion stream"));
        }
        validate_document_id(&document_id)?;
        let permit = self
            .queue
            .clone()
            .try_reserve_owned()
            .map_err(|_| Status::resource_exhausted("ingestion queue is full"))?;
        let job = IngestionJob {
            document_id: document_id.clone(),
            filename,
            raw_data: raw,
            metadata,
            chunk_settings: parsed_settings.expect("parsed settings present for non-empty stream"),
        };
        self.persist_raw(&job).await?;
        self.statuses
            .insert(document_id.clone(), IngestionStatus::queued());
        permit.send(job);
        Ok(Response::new(IngestDocumentResponse {
            document_id,
            success: true,
            message: "queued".into(),
        }))
    }

    async fn get_ingestion_status(
        &self,
        request: Request<GetIngestionStatusRequest>,
    ) -> Result<Response<GetIngestionStatusResponse>, Status> {
        let id = request.into_inner().document_id;
        if let Some(state) = self.statuses.get(&id) {
            return Ok(Response::new(GetIngestionStatusResponse {
                document_id: id,
                status: state.status.clone(),
                chunk_count: state.chunk_count,
                error_message: state.error_message.clone(),
            }));
        }
        let predicate = format!("document_id = '{}'", sql_string(&id));
        match self.table.count_rows(Some(predicate)).await {
            Ok(count) => {
                if count > 0 {
                    Ok(Response::new(GetIngestionStatusResponse {
                        document_id: id,
                        status: "queued".into(),
                        chunk_count: 0,
                        error_message: String::new(),
                    }))
                } else {
                    Err(Status::not_found("document status not found"))
                }
            }
            Err(error) => Err(Status::unavailable(format!(
                "staged_documents_v2 query failed: {error}"
            ))),
        }
    }

    async fn query_rag(
        &self,
        request: Request<QueryRagRequest>,
    ) -> Result<Response<QueryRagResponse>, Status> {
        let req = request.into_inner();

        let session_id = if req.session_id.trim().is_empty() {
            Uuid::new_v4().to_string()
        } else {
            let parsed = Uuid::parse_str(req.session_id.trim()).map_err(|_| {
                Status::invalid_argument("session_id must be a valid UUIDv4 string")
            })?;
            if parsed.get_version_num() != 4 || parsed.get_variant() != uuid::Variant::RFC4122 {
                return Err(Status::invalid_argument(
                    "session_id must be a valid UUIDv4 string",
                ));
            }
            parsed.to_string()
        };

        let (doc_ids, content_types) = if let Some(ref filter) = req.filter {
            (filter.document_ids.clone(), filter.content_types.clone())
        } else {
            (vec![], vec![])
        };

        let query_request =
            QueryRequest::from_values(&req.query, doc_ids, content_types, &self.retrieval_settings)
                .map_err(|err| match err.kind {
                    RetrievalErrorKind::EmptyQuery
                    | RetrievalErrorKind::QueryTooLong
                    | RetrievalErrorKind::InvalidDocumentId
                    | RetrievalErrorKind::UnsupportedContentType
                    | RetrievalErrorKind::EmptyFilterValue
                    | RetrievalErrorKind::FilterLimitExceeded
                    | RetrievalErrorKind::InvalidSettings => {
                        Status::invalid_argument(err.message())
                    }
                    RetrievalErrorKind::Snapshot => Status::internal(err.message()),
                })?;

        let query_embedding = match self
            .embedder
            .get_embeddings(&[query_request.query.clone()])
            .await
        {
            Ok(vecs) if !vecs.is_empty() && vecs[0].len() == 2048 => vecs[0].clone(),
            _ => vec![0.25; 2048],
        };

        let dense_retriever = DenseRetriever::new(self.nodes.clone());
        let dense_candidates = dense_retriever
            .query(&query_embedding, &query_request, &self.retrieval_settings)
            .await
            .unwrap_or_default();

        let bm25_guard = self.bm25_index.read().await;
        let bm25_candidates = bm25_guard
            .retrieve(&query_request, &self.retrieval_settings)
            .await
            .map_err(|err| Status::internal(err.to_string()))?;
        drop(bm25_guard);

        let fused = retrieval::fusion::fuse_candidates(
            dense_candidates,
            bm25_candidates,
            &self.retrieval_settings,
        )
        .map_err(|err| Status::internal(err.to_string()))?;

        let final_candidates: Vec<_> = fused
            .into_iter()
            .take(self.retrieval_settings.final_limit)
            .collect();

        let evidence_blocks = prompt::assemble_evidence_blocks(&final_candidates);
        let packed_evidence = prompt::pack_evidence_prompt(
            &query_request.query,
            &evidence_blocks,
            prompt::DEFAULT_MAX_PROMPT_TOKENS,
            prompt::DEFAULT_ANSWER_TOKEN_BUDGET,
        )
        .map_err(|err| Status::invalid_argument(format!("prompt assembly error: {err}")))?;

        let mut gen_req =
            generation::GenerationRequest::new(&query_request.query, packed_evidence.evidence.clone());
        gen_req.session_id = Some(session_id.clone());

        let model_output =
            self.generator
                .generate(gen_req)
                .await
                .map_err(|err| match err.kind {
                    generation::GenerationErrorKind::InvalidRequest => {
                        Status::invalid_argument(err.message())
                    }
                    _ => Status::internal(err.message()),
                })?;

        model_output
            .validate_grounding(&packed_evidence.evidence)
            .map_err(|err| Status::internal(err.message()))?;

        let resolved_citations =
            prompt::resolve_citations(&model_output.cited_evidence_ids, &packed_evidence.evidence);

        let proto_citations: Vec<String> = resolved_citations
            .iter()
            .map(|c| c.marker_id.clone())
            .collect();

        let proto_structured_citations: Vec<lancet::v1::StructuredCitation> = resolved_citations
            .iter()
            .enumerate()
            .map(|(idx, c)| lancet::v1::StructuredCitation {
                chunk_id: c.chunk_id.clone(),
                document_id: c.document_id.clone(),
                title: c.provenance.clone(),
                section_path: "".to_string(),
                excerpt: c.bounded_excerpt.clone(),
                is_truncated: false,
                score: final_candidates
                    .get(idx)
                    .map(|fc| fc.fused_score)
                    .unwrap_or(0.0),
                rank: (idx + 1) as i32,
                content_type: "".to_string(),
            })
            .collect();

        let proto_answer_basis = match model_output.answer_basis {
            generation::AnswerBasis::Retrieval => lancet::v1::AnswerBasis::Retrieval as i32,
            generation::AnswerBasis::Mixed => lancet::v1::AnswerBasis::Mixed as i32,
            generation::AnswerBasis::ModelOnly => lancet::v1::AnswerBasis::ModelOnly as i32,
        };

        let proto_notices: Vec<lancet::v1::Notice> = model_output
            .notices
            .iter()
            .map(|n| lancet::v1::Notice {
                code: "NOTICE".to_string(),
                message: n.clone(),
                severity: lancet::v1::NoticeSeverity::Info as i32,
            })
            .collect();

        let snapshot = lancet::v1::RetrievalSnapshot {
            index_generation: "v1".to_string(),
            embedding_model: "nvidia/llama-nemotron-embed-vl-1b-v2:free".to_string(),
            vector_weight: self.retrieval_settings.vector_weight,
            bm25_weight: self.retrieval_settings.bm25_weight,
            rrf_k: self.retrieval_settings.rrf_k as i32,
            candidate_limit: self.retrieval_settings.candidate_limit as i32,
            final_limit: self.retrieval_settings.final_limit as i32,
            active_filter: Some(lancet::v1::DocumentFilter {
                document_ids: query_request.filters.document_ids.clone(),
                content_types: query_request.filters.content_types.clone(),
            }),
            result_hash: format!("{:x}", {
                let mut hasher = DefaultHasher::new();
                for c in &final_candidates {
                    c.candidate.chunk_id.hash(&mut hasher);
                }
                hasher.finish()
            }),
        };

        Ok(Response::new(QueryRagResponse {
            answer: model_output.answer,
            citations: proto_citations,
            session_id,
            answer_basis: proto_answer_basis,
            structured_citations: proto_structured_citations,
            notices: proto_notices,
            snapshot: Some(snapshot),
        }))
    }

    async fn query_graph(
        &self,
        _request: Request<QueryGraphRequest>,
    ) -> Result<Response<QueryGraphResponse>, Status> {
        Ok(Response::new(QueryGraphResponse {
            result_json: r#"{"status":"scaffolding"}"#.into(),
        }))
    }
}

trait EmbeddingProvider: Send + Sync {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>>;
}

impl EmbeddingProvider for OpenRouterClient {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move { OpenRouterClient::get_embeddings(self, texts).await })
    }
}

fn sql_string(value: &str) -> String {
    value.replace('\'', "''")
}

fn content_hash(content: &str) -> String {
    let mut hasher = DefaultHasher::new();
    content.hash(&mut hasher);
    format!("{:016x}", hasher.finish())
}

fn content_type(filename: &str) -> &'static str {
    match Path::new(filename)
        .extension()
        .and_then(|extension| extension.to_str())
    {
        Some(extension) if extension.eq_ignore_ascii_case("json") => "application/json",
        Some(extension) if extension.eq_ignore_ascii_case("md") => "text/markdown",
        _ => "text/plain",
    }
}

#[allow(dead_code)]
async fn replace_document(
    database: &DatabaseManager,
    job: &IngestionJob,
    chunks: &[Chunk],
    embeddings: &[Vec<f32>],
) -> Result<(), String> {
    replace_document_with_faults(
        database,
        job,
        chunks,
        embeddings,
        &LanceDbReplacementMutationBoundary,
    )
    .await
}

async fn restore_version(table: &Table, version: u64) -> Result<(), String> {
    table
        .checkout(version)
        .await
        .map_err(|error| format!("checkout rollback version {version}: {error}"))?;
    table
        .restore()
        .await
        .map_err(|error| format!("restore rollback version {version}: {error}"))
}

#[allow(clippy::too_many_arguments)]
async fn rollback_replacement(
    database: &DatabaseManager,
    documents: &Table,
    documents_version: u64,
    nodes: &Table,
    nodes_version: u64,
    edges: &Table,
    edges_version: u64,
    predicate: &str,
    mutations: &dyn ReplacementMutationBoundary,
    original: String,
) -> Result<(), String> {
    let mut rollback_errors = Vec::new();
    for result in [
        restore_version(documents, documents_version).await,
        restore_version(nodes, nodes_version).await,
        restore_version(edges, edges_version).await,
    ] {
        if let Err(error) = result {
            rollback_errors.push(error);
        }
    }
    if let Ok(staged) = database.staged_documents_table().await {
        if let Err(error) = mutations
            .delete(ReplacementMutation::StagingDelete, &staged, predicate)
            .await
        {
            rollback_errors.push(error);
        }
    }
    if rollback_errors.is_empty() {
        Err(original)
    } else {
        Err(format!(
            "{original}; rollback failures: {}",
            rollback_errors.join("; ")
        ))
    }
}

async fn replace_document_with_faults(
    database: &DatabaseManager,
    job: &IngestionJob,
    chunks: &[Chunk],
    embeddings: &[Vec<f32>],
    mutations: &dyn ReplacementMutationBoundary,
) -> Result<(), String> {
    if chunks.len() != embeddings.len() {
        return Err(format!(
            "embedding count {} does not match chunk count {}",
            embeddings.len(),
            chunks.len()
        ));
    }
    if embeddings.iter().any(|embedding| embedding.len() != 2048) {
        return Err("all embeddings must contain exactly 2048 dimensions".into());
    }

    let documents = database.documents_table().await?;
    let nodes = database.nodes_table().await?;
    let edges = database.edges_table().await?;
    let documents_version = documents
        .version()
        .await
        .map_err(|error| error.to_string())?;
    let nodes_version = nodes.version().await.map_err(|error| error.to_string())?;
    let edges_version = edges.version().await.map_err(|error| error.to_string())?;
    let predicate = format!("document_id = '{}'", sql_string(&job.document_id));
    let operation = async {
        let staged = database
            .staged_documents_table()
            .await
            .map_err(|error| error.to_string())?;

        // Delete dependent rows first so retries cannot retain stale chunks or graph links.
        mutations
            .delete(ReplacementMutation::EdgesDelete, &edges, &predicate)
            .await?;
        mutations
            .delete(ReplacementMutation::NodesDelete, &nodes, &predicate)
            .await?;
        mutations
            .delete(ReplacementMutation::DocumentsDelete, &documents, &predicate)
            .await?;

        let documents_batch = RecordBatch::try_new(
            documents
                .schema()
                .await
                .map_err(|error| error.to_string())?,
            vec![
                Arc::new(StringArray::from(vec![job.document_id.as_str()])),
                Arc::new(BinaryArray::from_vec(vec![job.raw_data.as_slice()])),
            ],
        )
        .map_err(|error| error.to_string())?;
        mutations
            .add(
                ReplacementMutation::DocumentsAdd,
                &documents,
                documents_batch,
            )
            .await?;

        if chunks.is_empty() {
            mutations
                .delete(ReplacementMutation::StagingDelete, &staged, &predicate)
                .await?;
            return Ok(());
        }

        let chunk_ids: Vec<String> = (0..chunks.len())
            .map(|index| format!("{}:{index}", job.document_id))
            .collect();
        let ingested_at = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| error.to_string())?
            .as_millis() as i64;
        let flat_embeddings: Vec<f32> = embeddings.iter().flatten().copied().collect();
        let embedding_array = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
            embeddings
                .iter()
                .map(|embedding| Some(embedding.iter().copied().map(Some))),
            2048,
        );
        debug_assert_eq!(
            flat_embeddings.len(),
            chunks.len() * 2048,
            "validated embedding dimensions must remain stable"
        );
        let node_schema = nodes.schema().await.map_err(|error| error.to_string())?;
        let nullable = |name: &str| -> Result<Arc<dyn arrow_array::Array>, String> {
            let field = mutations.field_with_name(&node_schema, name)?;
            Ok(new_null_array(field.data_type(), chunks.len()))
        };
        let section_paths: Vec<Option<&str>> = chunks
            .iter()
            .map(|chunk| chunk.section_path.as_deref())
            .collect();
        let hashes: Vec<String> = chunks
            .iter()
            .map(|chunk| content_hash(&chunk.content))
            .collect();
        let batch = RecordBatch::try_new(
            node_schema.clone(),
            vec![
                Arc::new(StringArray::from(vec![
                    job.document_id.as_str();
                    chunks.len()
                ])),
                Arc::new(StringArray::from(
                    chunk_ids.iter().map(String::as_str).collect::<Vec<_>>(),
                )),
                Arc::new(Int32Array::from_iter_values(
                    (0..chunks.len()).map(|index| i32::try_from(index).unwrap_or(i32::MAX)),
                )),
                Arc::new(Int32Array::from_iter_values(chunks.iter().map(|chunk| {
                    i32::try_from(chunk.char_start).unwrap_or(i32::MAX)
                }))),
                Arc::new(Int32Array::from_iter_values(
                    chunks
                        .iter()
                        .map(|chunk| i32::try_from(chunk.char_end).unwrap_or(i32::MAX)),
                )),
                Arc::new(StringArray::from(
                    chunks
                        .iter()
                        .map(|chunk| chunk.content.as_str())
                        .collect::<Vec<_>>(),
                )),
                Arc::new(embedding_array),
                Arc::new(Int32Array::from_iter_values(
                    chunks.iter().map(|chunk| chunk.estimated_tokens),
                )),
                Arc::new(StringArray::from(vec!["o200k_base"; chunks.len()])),
                Arc::new(StringArray::from(vec!["1"; chunks.len()])),
                Arc::new(StringArray::from(vec![
                    Some(job.filename.as_str());
                    chunks.len()
                ])),
                Arc::new(StringArray::from(section_paths)),
                nullable("page_start")?,
                nullable("page_end")?,
                Arc::new(StringArray::from(
                    hashes.iter().map(String::as_str).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(vec!["1"; chunks.len()])),
                Arc::new(StringArray::from(vec![EMBEDDING_MODEL; chunks.len()])),
                Arc::new(Int64Array::from(vec![Some(ingested_at); chunks.len()])),
                Arc::new(StringArray::from(vec![
                    Some(content_type(&job.filename));
                    chunks.len()
                ])),
                nullable("community_ids")?,
                nullable("summary")?,
                nullable("summary_vector")?,
                nullable("unsummarized_refs")?,
            ],
        )
        .map_err(|error| error.to_string())?;
        mutations
            .add(ReplacementMutation::NodesAdd, &nodes, batch)
            .await?;

        let resolver = ExactMatchResolver;
        let mut known_sections = Vec::<String>::new();
        let mut section_targets = HashMap::<String, String>::new();
        let mut edge_sources = Vec::<String>::new();
        let mut edge_targets = Vec::<String>::new();
        let mut relation_types = Vec::<String>::new();
        for (index, chunk) in chunks.iter().enumerate() {
            let mut target = index
                .checked_sub(1)
                .map(|previous| chunk_ids[previous].clone());
            let mut relation = "next_chunk";
            if let Some(section) = chunk.section_path.as_deref() {
                if let Some(resolved) = resolver.resolve(section, &known_sections).await? {
                    target = section_targets.get(&resolved).cloned();
                    relation = "same_section";
                } else {
                    known_sections.push(section.to_owned());
                    section_targets.insert(section.to_owned(), chunk_ids[index].clone());
                }
            }
            if let Some(target) = target {
                edge_sources.push(chunk_ids[index].clone());
                edge_targets.push(target);
                relation_types.push(relation.to_owned());
            }
        }
        if !edge_sources.is_empty() {
            let edge_ids: Vec<String> = edge_sources
                .iter()
                .enumerate()
                .map(|(index, _)| format!("{}:edge:{index}", job.document_id))
                .collect();
            let edge_schema = edges.schema().await.map_err(|error| error.to_string())?;
            let edge_nullable = |name: &str| -> Result<Arc<dyn arrow_array::Array>, String> {
                let field = mutations.field_with_name(&edge_schema, name)?;
                Ok(new_null_array(field.data_type(), edge_sources.len()))
            };
            let edge_batch = RecordBatch::try_new(
                edge_schema.clone(),
                vec![
                    Arc::new(StringArray::from(
                        edge_ids.iter().map(String::as_str).collect::<Vec<_>>(),
                    )),
                    Arc::new(StringArray::from(
                        edge_sources.iter().map(String::as_str).collect::<Vec<_>>(),
                    )),
                    Arc::new(StringArray::from(
                        edge_targets.iter().map(String::as_str).collect::<Vec<_>>(),
                    )),
                    Arc::new(StringArray::from(
                        relation_types
                            .iter()
                            .map(String::as_str)
                            .collect::<Vec<_>>(),
                    )),
                    Arc::new(Float32Array::from(vec![1.0; edge_sources.len()])),
                    Arc::new(StringArray::from(vec![
                        job.document_id.as_str();
                        edge_sources.len()
                    ])),
                    edge_nullable("summary")?,
                    edge_nullable("summary_vector")?,
                ],
            )
            .map_err(|error| error.to_string())?;
            mutations
                .add(ReplacementMutation::EdgesAdd, &edges, edge_batch)
                .await?;
        }
        mutations
            .delete(ReplacementMutation::StagingDelete, &staged, &predicate)
            .await?;
        Ok(())
    }
    .await;

    match operation {
        Ok(()) => Ok(()),
        Err(error) => {
            rollback_replacement(
                database,
                &documents,
                documents_version,
                &nodes,
                nodes_version,
                &edges,
                edges_version,
                &predicate,
                mutations,
                error,
            )
            .await
        }
    }
}

#[allow(dead_code)]
async fn process_job(
    job: &IngestionJob,
    database: &DatabaseManager,
    embedder: &dyn EmbeddingProvider,
) -> Result<i32, String> {
    process_job_with_boundary(job, database, embedder, &LanceDbReplacementMutationBoundary).await
}

async fn process_job_with_boundary(
    job: &IngestionJob,
    database: &DatabaseManager,
    embedder: &dyn EmbeddingProvider,
    boundary: &dyn ReplacementMutationBoundary,
) -> Result<i32, String> {
    let chunk_span = tracing::info_span!("chunk_document", document_id = %job.document_id);
    let (strategy, chunks) = chunk_span.in_scope(|| chunk_ingestion_job(job));
    tracing::info!(
        document_id = %job.document_id,
        chunk_strategy = strategy,
        chunk_count = chunks.len(),
        "chunking completed"
    );

    let texts = chunks
        .iter()
        .map(|chunk| chunk.content.clone())
        .collect::<Vec<_>>();
    let embedding_span = tracing::info_span!("embed_document", document_id = %job.document_id, chunk_count = chunks.len());
    let embeddings = async { embedder.get_embeddings(&texts).await }
        .instrument(embedding_span)
        .await?;

    let database_span = tracing::info_span!("persist_document", document_id = %job.document_id, chunk_count = chunks.len());
    async { replace_document_with_faults(database, job, &chunks, &embeddings, boundary).await }
        .instrument(database_span)
        .await?;
    Ok(i32::try_from(chunks.len()).unwrap_or(i32::MAX))
}

fn spawn_worker(
    receiver: mpsc::Receiver<IngestionJob>,
    statuses: Arc<DashMap<String, IngestionStatus>>,
    database: DatabaseManager,
    embedder: Arc<dyn EmbeddingProvider>,
    shutdown: watch::Receiver<bool>,
) -> JoinHandle<()> {
    spawn_worker_with_boundary(
        receiver,
        statuses,
        database,
        embedder,
        Arc::new(LanceDbReplacementMutationBoundary),
        shutdown,
    )
}

fn spawn_worker_with_boundary(
    receiver: mpsc::Receiver<IngestionJob>,
    statuses: Arc<DashMap<String, IngestionStatus>>,
    database: DatabaseManager,
    embedder: Arc<dyn EmbeddingProvider>,
    boundary: Arc<dyn ReplacementMutationBoundary>,
    mut shutdown: watch::Receiver<bool>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        let mut receiver = receiver;
        let mut shutdown_triggered = false;
        loop {
            let job = if shutdown_triggered {
                match receiver.recv().await {
                    Some(job) => job,
                    None => break,
                }
            } else {
                tokio::select! {
                    biased;
                    changed = shutdown.changed() => {
                        if changed.is_ok() && *shutdown.borrow() {
                            shutdown_triggered = true;
                            receiver.close();
                            match receiver.recv().await {
                                Some(job) => job,
                                None => break,
                            }
                        } else {
                            continue;
                        }
                    }
                    job = receiver.recv() => match job {
                        Some(job) => job,
                        None => break,
                    }
                }
            };
            statuses.insert(
                job.document_id.clone(),
                IngestionStatus {
                    status: "processing".into(),
                    chunk_count: 0,
                    error_message: String::new(),
                },
            );
            let document_id = job.document_id.clone();
            let span = tracing::info_span!(
                "index_document",
                document_id = %document_id,
                bytes = job.raw_data.len()
            );
            match async {
                process_job_with_boundary(&job, &database, embedder.as_ref(), boundary.as_ref())
                    .await
            }
            .instrument(span)
            .await
            {
                Ok(chunk_count) => {
                    statuses.insert(
                        document_id,
                        IngestionStatus {
                            status: "completed".into(),
                            chunk_count,
                            error_message: String::new(),
                        },
                    );
                    tracing::info!(%job.document_id, chunk_count, "indexing completed");
                }
                Err(error) => {
                    let predicate = format!("document_id = '{}'", sql_string(&document_id));
                    let delete_res = async {
                        let staged = database
                            .staged_documents_table()
                            .await
                            .map_err(|e| e.to_string())?;
                        boundary
                            .delete(ReplacementMutation::StagingDelete, &staged, &predicate)
                            .await
                    }
                    .await;

                    match delete_res {
                        Ok(()) => {
                            tracing::error!(%job.document_id, %error, "indexing failed");
                            statuses.insert(
                                document_id,
                                IngestionStatus {
                                    status: "failed".into(),
                                    chunk_count: 0,
                                    error_message: error,
                                },
                            );
                        }
                        Err(delete_err) => {
                            tracing::error!(
                                %job.document_id,
                                %error,
                                %delete_err,
                                "indexing failed and staging delete failed; retaining row queued for replay"
                            );
                            statuses.remove(&document_id);
                        }
                    }
                }
            }
        }
    })
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();
    let settings = load_settings()?;
    let database = DatabaseManager::initialize(&settings.engine.lancedb_path).await?;
    let nodes = database.nodes_table().await?;
    let bm25_index = Bm25Index::from_table(&nodes, Bm25Config::default()).await?;
    tracing::info!(document_count = bm25_index.len(), "BM25 snapshot built");
    let table = database.staged_documents_table().await?;
    let embedder = Arc::new(OpenRouterClient::from_env_with_endpoint(
        &settings.openrouter.embedding_endpoint,
    )?);
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        embedder.clone(),
        shutdown_rx,
    );

    let staged_jobs = read_staged_jobs(&database).await?;
    for job in staged_jobs {
        statuses.insert(job.document_id.clone(), IngestionStatus::queued());
        sender
            .send(job)
            .await
            .map_err(|_| "worker exited during replay send")?;
    }

    let generator: Arc<dyn generation::Generator> = Arc::new(
        generation::openrouter::OpenRouterGenerator::new(
            std::env::var("OPENROUTER_API_KEY").unwrap_or_else(|_| "fake-key".to_owned()),
            &settings.openrouter.generation_model,
        )?
        .with_endpoints(
            &settings.openrouter.chat_endpoint,
            &settings.openrouter.model_metadata_endpoint,
        ),
    );

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        retrieval_settings: settings.engine.retrieval.to_retrieval_settings(),
        generator,
        embedder: embedder.clone(),
    };

    let addr = settings.engine.grpc_addr.parse()?;
    tracing::info!(%addr, "Rust RAG Engine serving");
    Server::builder()
        .add_service(LancetServiceServer::new(service))
        .serve_with_shutdown(addr, async {
            let _ = tokio::signal::ctrl_c().await;
            let _ = shutdown_tx.send(true);
        })
        .await?;
    worker.await?;
    Ok(())
}

#[cfg(test)]
mod tests;
