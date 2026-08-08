use std::{
    collections::{HashMap, HashSet},
    hash::{DefaultHasher, Hash, Hasher},
    path::Path,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use arrow_array::{
    new_null_array, types::Float32Type, BinaryArray, FixedSizeListArray, Float32Array, Int32Array,
    Int64Array, RecordBatch, StringArray,
};
use dashmap::DashMap;
use futures::{future::BoxFuture, StreamExt, TryStreamExt};
use lancedb::{
    query::{ExecutableQuery, QueryBase},
    Table,
};
use serde::Deserialize;
use tokio::{
    sync::{mpsc, watch},
    task::JoinHandle,
};
use tonic::{transport::Server, Request, Response, Status};
use arrow_array::Array;
use graph::escape_sql_literal;
use tracing::Instrument;
use uuid::Uuid;

mod chunker;
use engine::client;
use engine::db;
pub mod generation;
pub mod graph;
pub mod prompt;
mod rerank;
mod retrieval;

use chunker::{chunk_fixed_size, chunk_markdown, estimate_tokens, Chunk};
use client::{OpenRouterClient, OpenRouterEmbeddingConfig};
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
    IngestDocumentResponse, PingRequest, PingResponse, QueryGraphEdge, QueryGraphNode,
    QueryGraphRequest, QueryGraphResponse, QueryRagRequest, QueryRagResponse,
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

impl Default for Settings {
    fn default() -> Self {
        Self {
            engine: EngineSettings::default(),
            openrouter: OpenRouterSettings::default(),
        }
    }
}

fn default_seed_match_min_score() -> f64 {
    0.5
}

fn default_max_hop_cap() -> u32 {
    3
}

#[derive(Debug, Clone, Deserialize)]
pub struct GraphConfigSettings {
    #[serde(default = "default_seed_match_min_score")]
    pub seed_match_min_score: f64,
    #[serde(default = "default_max_hop_cap")]
    pub max_hop_cap: u32,
}

impl Default for GraphConfigSettings {
    fn default() -> Self {
        Self {
            seed_match_min_score: default_seed_match_min_score(),
            max_hop_cap: default_max_hop_cap(),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct GraphSettings {
    pub seed_match_min_score: f64,
    pub max_hop_cap: u32,
}

#[derive(Debug, Clone, Deserialize)]
pub struct EngineSettings {
    pub grpc_addr: String,
    pub lancedb_path: String,
    #[serde(default)]
    pub retrieval: RetrievalConfigSettings,
    #[serde(default)]
    pub graph: GraphConfigSettings,
}

impl Default for EngineSettings {
    fn default() -> Self {
        Self {
            grpc_addr: "[::1]:50051".into(),
            lancedb_path: "./data/lancedb".into(),
            retrieval: RetrievalConfigSettings::default(),
            graph: GraphConfigSettings::default(),
        }
    }
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
    #[serde(default = "default_weight")]
    pub graph_weight: f64,
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
            graph_weight: 1.0,
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
            graph_weight: self.graph_weight,
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

fn new_index_generation() -> String {
    format!("gen-{}", Uuid::new_v4())
}

#[derive(Debug, Clone, PartialEq)]
pub struct EffectiveRagSettings {
    pub retrieval: retrieval::RetrievalSettings,
    pub graph: GraphSettings,
    pub evidence_token_budget: usize,
    pub citation_excerpt_max_chars: usize,
    pub embedding_endpoint: String,
    pub embedding_model: String,
    pub generation_model: String,
    pub chat_endpoint: String,
    pub model_metadata_endpoint: String,
    pub generation_timeout_secs: u64,
    pub temperature: f64,
    pub top_p: f64,
    pub max_output_tokens: u32,
    pub index_generation: String,
    grounding_limits: Arc<generation::GroundingLimits>,
}

impl EffectiveRagSettings {
    pub fn grounding_limits(&self) -> &generation::GroundingLimits {
        &self.grounding_limits
    }

    pub fn grounding_limits_arc(&self) -> Arc<generation::GroundingLimits> {
        Arc::clone(&self.grounding_limits)
    }

    pub fn try_from_settings(settings: &Settings) -> Result<Self, String> {
        let retrieval = settings.engine.retrieval.to_retrieval_settings();
        let graph = GraphSettings {
            seed_match_min_score: settings.engine.graph.seed_match_min_score,
            max_hop_cap: settings.engine.graph.max_hop_cap,
        };
        let ev = u32::try_from(settings.engine.retrieval.evidence_token_budget)
            .map_err(|_| "evidence_token_budget exceeds u32::MAX".to_string())?;
        let limits = generation::GroundingLimits::new(ev, settings.openrouter.max_output_tokens)
            .map_err(|err| err.message().to_string())?;
        let effective = Self {
            retrieval,
            graph,
            evidence_token_budget: settings.engine.retrieval.evidence_token_budget,
            citation_excerpt_max_chars: settings.engine.retrieval.excerpt_max_chars,
            embedding_endpoint: settings.openrouter.embedding_endpoint.clone(),
            embedding_model: settings.openrouter.embedding_model.clone(),
            generation_model: settings.openrouter.generation_model.clone(),
            chat_endpoint: settings.openrouter.chat_endpoint.clone(),
            model_metadata_endpoint: settings.openrouter.model_metadata_endpoint.clone(),
            generation_timeout_secs: settings.openrouter.generation_timeout_secs,
            temperature: settings.openrouter.temperature,
            top_p: settings.openrouter.top_p,
            max_output_tokens: settings.openrouter.max_output_tokens,
            index_generation: new_index_generation(),
            grounding_limits: Arc::new(limits),
        };
        effective.validate()?;
        Ok(effective)
    }

    pub fn validate(&self) -> Result<(), String> {
        self.retrieval
            .validate()
            .map_err(|err| format!("invalid retrieval settings: {}", err.message()))?;
        if !self.graph.seed_match_min_score.is_finite()
            || self.graph.seed_match_min_score < 0.0
            || self.graph.seed_match_min_score > 1.0
        {
            return Err("invalid graph.seed_match_min_score: must be finite and between 0.0 and 1.0".into());
        }
        if self.graph.max_hop_cap == 0 || self.graph.max_hop_cap > graph::MAX_HOP_CAP {
            return Err(format!(
                "invalid graph.max_hop_cap: must be between 1 and {}",
                graph::MAX_HOP_CAP
            ));
        }
        if self.citation_excerpt_max_chars == 0 {
            return Err("invalid excerpt_max_chars: must be greater than 0".into());
        }
        if self.embedding_endpoint.trim().is_empty() {
            return Err("invalid embedding_endpoint: must not be empty".into());
        }
        if self.embedding_model.trim().is_empty() {
            return Err("invalid embedding_model: must not be empty".into());
        }
        if self.generation_model.trim().is_empty() {
            return Err("invalid generation_model: must not be empty".into());
        }
        if self.chat_endpoint.trim().is_empty() {
            return Err("invalid chat_endpoint: must not be empty".into());
        }
        if self.model_metadata_endpoint.trim().is_empty() {
            return Err("invalid model_metadata_endpoint: must not be empty".into());
        }
        if self.generation_timeout_secs == 0 {
            return Err("invalid generation_timeout_secs: must be greater than 0".into());
        }
        if !self.temperature.is_finite() || self.temperature < 0.0 || self.temperature > 2.0 {
            return Err("invalid temperature: must be finite and between 0.0 and 2.0".into());
        }
        if !self.top_p.is_finite() || self.top_p <= 0.0 || self.top_p > 1.0 {
            return Err("invalid top_p: must be finite and between 0.0 and 1.0".into());
        }
        if self.index_generation.trim().is_empty() {
            return Err("invalid index_generation: must not be empty".into());
        }
        Ok(())
    }
}

impl Default for EffectiveRagSettings {
    fn default() -> Self {
        Self::try_from_settings(&Settings::default()).expect("default settings must be valid")
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
    if let Ok(value) = std::env::var("LANCET_ENGINE__RETRIEVAL__EVIDENCE_TOKEN_BUDGET") {
        if let Ok(budget) = value.trim().parse::<usize>() {
            settings.engine.retrieval.evidence_token_budget = budget;
        }
    }
    if let Ok(value) = std::env::var("LANCET_OPENROUTER__MAX_OUTPUT_TOKENS") {
        if let Ok(tokens) = value.trim().parse::<u32>() {
            settings.openrouter.max_output_tokens = tokens;
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
    StagingAdd,
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

struct StagedJobRow {
    document_id: String,
    generation: i64,
    job: IngestionJob,
}

fn select_latest_staged_rows(rows: Vec<StagedJobRow>) -> Result<Vec<IngestionJob>, String> {
    let mut latest_by_doc: HashMap<String, StagedJobRow> = HashMap::new();

    for row in rows {
        match latest_by_doc.entry(row.document_id.clone()) {
            std::collections::hash_map::Entry::Vacant(entry) => {
                entry.insert(row);
            }
            std::collections::hash_map::Entry::Occupied(mut entry) => {
                if row.generation == entry.get().generation {
                    return Err(format!(
                        "ambiguous staged rows: duplicate generation {} for document {}",
                        row.generation, row.document_id
                    ));
                } else if row.generation > entry.get().generation {
                    entry.insert(row);
                }
            }
        }
    }

    let mut result_rows: Vec<StagedJobRow> = latest_by_doc.into_values().collect();
    result_rows.sort_by(|a, b| a.document_id.cmp(&b.document_id));
    Ok(result_rows.into_iter().map(|r| r.job).collect())
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

    let mut staged_rows = Vec::new();

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
        let generations = batch
            .column_by_name("generation")
            .map(|col| {
                col.as_any()
                    .downcast_ref::<Int64Array>()
                    .ok_or("invalid generation array type in staged_documents_v2")
            })
            .transpose()?;

        for i in 0..batch.num_rows() {
            let doc_id = doc_ids.value(i).to_string();
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
            let generation = match generations {
                Some(arr) => arr.value(i),
                None => 1,
            };

            let metadata = HashMap::from([
                ("chunk_strategy".to_string(), strategy),
                ("chunk_size".to_string(), size.to_string()),
                ("chunk_overlap".to_string(), overlap.to_string()),
            ]);

            let chunk_settings = parse_chunk_settings(&metadata).map_err(|error| {
                format!("malformed chunk settings in staging for document {doc_id}: {error}")
            })?;

            staged_rows.push(StagedJobRow {
                document_id: doc_id.clone(),
                generation,
                job: IngestionJob {
                    document_id: doc_id,
                    filename,
                    raw_data,
                    metadata,
                    chunk_settings,
                },
            });
        }
    }

    select_latest_staged_rows(staged_rows)
}

#[derive(Clone)]
pub struct LancetServiceImpl {
    table: Table,
    statuses: Arc<DashMap<String, IngestionStatus>>,
    queue: mpsc::Sender<IngestionJob>,
    nodes: Table,
    bm25_index: Arc<tokio::sync::RwLock<Bm25Index>>,
    pub effective_settings: EffectiveRagSettings,
    generator: Arc<dyn generation::Generator>,
    embedder: Arc<dyn EmbeddingProvider>,
    reranker: Arc<dyn rerank::Reranker>,
    pub database: DatabaseManager,
}

fn d1_status(
    code: tonic::Code,
    message: impl Into<String>,
    session_id: &str,
    correlation_id: &str,
    error_kind: &str,
) -> Status {
    let msg = message.into();
    tracing::warn!(%session_id, %correlation_id, %error_kind, "QueryRAG infrastructure failure: {msg}");
    let mut status = Status::new(code, msg);
    let metadata = status.metadata_mut();
    if let Ok(val) = session_id.parse() {
        metadata.insert("x-lancet-session-id", val);
    }
    if let Ok(val) = correlation_id.parse() {
        metadata.insert("x-lancet-correlation-id", val);
    }
    if let Ok(val) = error_kind.parse() {
        metadata.insert("x-lancet-error-kind", val);
    }
    status
}

async fn get_max_staged_generation(
    table: &Table,
    document_id: &str,
) -> Result<Option<i64>, String> {
    let pred = format!("document_id = '{}'", sql_string(document_id));
    let batches: Vec<RecordBatch> = table
        .query()
        .only_if(&pred)
        .execute()
        .await
        .map_err(|e| format!("query failed: {e}"))?
        .try_collect()
        .await
        .map_err(|e| format!("collect failed: {e}"))?;

    let mut max_g: Option<i64> = None;
    for batch in &batches {
        if let Some(col) = batch.column_by_name("generation") {
            let gen_arr = col
                .as_any()
                .downcast_ref::<Int64Array>()
                .ok_or_else(|| "invalid generation column type".to_string())?;
            for i in 0..batch.num_rows() {
                let g = gen_arr.value(i);
                max_g = Some(max_g.map_or(g, |current| current.max(g)));
            }
        }
    }
    Ok(max_g)
}

async fn persist_raw_with_boundary(
    table: &Table,
    job: &IngestionJob,
    boundary: &dyn ReplacementMutationBoundary,
) -> Result<(), String> {
    let old_max_gen = get_max_staged_generation(table, &job.document_id).await?;
    let new_gen = match old_max_gen {
        Some(g) => g.checked_add(1).ok_or("generation overflow")?,
        None => 1,
    };

    let schema = table.schema().await.map_err(|e| e.to_string())?;
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
            Arc::new(Int64Array::from(vec![new_gen])),
        ],
    )
    .map_err(|e| e.to_string())?;

    boundary
        .add(ReplacementMutation::StagingAdd, table, batch)
        .await?;

    let verify_pred = format!(
        "document_id = '{}' AND generation = {new_gen}",
        sql_string(&job.document_id)
    );
    let verified_batches: Vec<RecordBatch> = table
        .query()
        .only_if(&verify_pred)
        .execute()
        .await
        .map_err(|e| format!("verify query failed: {e}"))?
        .try_collect()
        .await
        .map_err(|e| format!("verify collect failed: {e}"))?;

    let verified_count: usize = verified_batches.iter().map(|b| b.num_rows()).sum();
    if verified_count == 0 {
        return Err(format!(
            "staged raw successor verification failed: document {} generation {} not readable",
            job.document_id, new_gen
        ));
    }

    if let Some(old_g) = old_max_gen {
        let delete_pred = format!(
            "document_id = '{}' AND generation <= {old_g}",
            sql_string(&job.document_id)
        );
        boundary
            .delete(ReplacementMutation::StagingDelete, table, &delete_pred)
            .await?;
    }

    Ok(())
}

impl LancetServiceImpl {
    async fn persist_raw(&self, job: &IngestionJob) -> Result<(), Status> {
        persist_raw_with_boundary(&self.table, job, &LanceDbReplacementMutationBoundary)
            .await
            .map_err(internal)
    }
}

fn internal(err: impl std::fmt::Display) -> Status {
    Status::internal(err.to_string())
}

fn snapshot_limit(value: usize, name: &str) -> Result<i32, Status> {
    i32::try_from(value)
        .map_err(|_| Status::internal(format!("validated {name} does not fit snapshot")))
}

fn snapshot_rrf_k(value: f64) -> Result<i32, Status> {
    if !value.is_finite() || value < 0.0 || value.fract() != 0.0 || value > i32::MAX as f64 {
        return Err(Status::internal(
            "validated rrf_k is outside the snapshot representation",
        ));
    }
    value
        .round()
        .to_string()
        .parse::<i32>()
        .map_err(|_| Status::internal("validated rrf_k is not a snapshot integer"))
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

pub(crate) enum GraphAugmentationOutcome {
    Succeeded {
        facts: Vec<graph::context_strategy::GraphFact>,
    },
    NoMatchFound,
    AttemptedAndFailed {
        reason: String,
    },
}

pub(crate) async fn attempt_graph_augmentation(
    database: &DatabaseManager,
    query_embedding: &[f32],
    settings: &GraphSettings,
) -> GraphAugmentationOutcome {
    let entities_table = match database.entities_table().await {
        Ok(t) => t,
        Err(e) => {
            return GraphAugmentationOutcome::AttemptedAndFailed {
                reason: format!("entities table error: {e}"),
            }
        }
    };

    let nearest = match entities_table
        .query()
        .nearest_to(query_embedding.to_vec())
    {
        Ok(q) => q,
        Err(e) => {
            return GraphAugmentationOutcome::AttemptedAndFailed {
                reason: format!("nearest_to error: {e}"),
            }
        }
    };

    let batches: Vec<arrow_array::RecordBatch> = match nearest
        .column("name_vector")
        .select(lancedb::query::Select::columns(&[
            "entity_id",
            "name",
            "entity_type",
            "_distance",
        ]))
        .limit(1)
        .execute()
        .await
    {
        Ok(s) => match s.try_collect().await {
            Ok(b) => b,
            Err(e) => {
                return GraphAugmentationOutcome::AttemptedAndFailed {
                    reason: format!("execute collect error: {e}"),
                }
            }
        },
        Err(e) => {
            return GraphAugmentationOutcome::AttemptedAndFailed {
                reason: format!("execute error: {e}"),
            }
        }
    };

    if batches.is_empty() || batches[0].num_rows() == 0 {
        return GraphAugmentationOutcome::NoMatchFound;
    }

    let seed_batch = &batches[0];
    let distance_col = match seed_batch
        .column_by_name("_distance")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::Float32Array>())
    {
        Some(c) => c,
        None => {
            return GraphAugmentationOutcome::AttemptedAndFailed {
                reason: "missing _distance column".into(),
            }
        }
    };
    let distance = distance_col.value(0) as f64;
    let seed_match_score = retrieval::dense::dense_score(distance);

    if seed_match_score < settings.seed_match_min_score {
        return GraphAugmentationOutcome::NoMatchFound;
    }

    let seed_id_col = match seed_batch
        .column_by_name("entity_id")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
    {
        Some(c) => c,
        None => {
            return GraphAugmentationOutcome::AttemptedAndFailed {
                reason: "missing entity_id column".into(),
            }
        }
    };
    let matched_entity_id = seed_id_col.value(0).to_string();

    let (entities_batch, edges_batch) =
        match graph::fetch_neighborhood(database, &matched_entity_id, 1, true).await {
            Ok(res) => res,
            Err(e) => {
                return GraphAugmentationOutcome::AttemptedAndFailed {
                    reason: format!("fetch_neighborhood kind: {:?}", e.kind),
                }
            }
        };

    let (entities_batch, edges_batch) =
        graph::narrow_via_cypher(&entities_batch, &edges_batch, &matched_entity_id, 1).await;

    let entity_id_col = match entities_batch
        .column_by_name("entity_id")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
    {
        Some(c) => c,
        None => return GraphAugmentationOutcome::Succeeded { facts: vec![] },
    };
    let name_col = match entities_batch
        .column_by_name("name")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
    {
        Some(c) => c,
        None => return GraphAugmentationOutcome::Succeeded { facts: vec![] },
    };

    let mut name_map = HashMap::new();
    for i in 0..entities_batch.num_rows() {
        if !entity_id_col.is_null(i) && !name_col.is_null(i) {
            name_map.insert(
                entity_id_col.value(i).to_string(),
                name_col.value(i).to_string(),
            );
        }
    }

    let source_col = match edges_batch
        .column_by_name("source_node_id")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
    {
        Some(c) => c,
        None => return GraphAugmentationOutcome::Succeeded { facts: vec![] },
    };
    let target_col = match edges_batch
        .column_by_name("target_node_id")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
    {
        Some(c) => c,
        None => return GraphAugmentationOutcome::Succeeded { facts: vec![] },
    };
    let rel_col = match edges_batch
        .column_by_name("relation_type")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>())
    {
        Some(c) => c,
        None => return GraphAugmentationOutcome::Succeeded { facts: vec![] },
    };
    let weight_col = match edges_batch
        .column_by_name("weight")
        .and_then(|c| c.as_any().downcast_ref::<arrow_array::Float32Array>())
    {
        Some(c) => c,
        None => return GraphAugmentationOutcome::Succeeded { facts: vec![] },
    };

    let mut facts = Vec::new();
    for i in 0..edges_batch.num_rows() {
        if !source_col.is_null(i)
            && !target_col.is_null(i)
            && !rel_col.is_null(i)
            && !weight_col.is_null(i)
        {
            let src_id = source_col.value(i);
            let tgt_id = target_col.value(i);
            let rel = rel_col.value(i);
            let weight = weight_col.value(i) as f64;

            if let (Some(src_name), Some(tgt_name)) =
                (name_map.get(src_id), name_map.get(tgt_id))
            {
                let score = seed_match_score * weight;
                facts.push(graph::context_strategy::GraphFact::new(
                    src_name, rel, tgt_name, None, score,
                ));
            }
        }
    }

    GraphAugmentationOutcome::Succeeded { facts }
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
        let query_span = tracing::info_span!("query_rag", graph_augmentation = tracing::field::Empty);
        async move {
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

            let correlation_id = Uuid::new_v4().to_string();

            let (doc_ids, content_types) = if let Some(ref filter) = req.filter {
                (filter.document_ids.clone(), filter.content_types.clone())
            } else {
                (vec![], vec![])
            };

            let query_request = QueryRequest::from_values(
                &req.query,
                doc_ids,
                content_types,
                &self.effective_settings.retrieval,
            )
            .map_err(|err| match err.kind {
                RetrievalErrorKind::EmptyQuery
                | RetrievalErrorKind::QueryTooLong
                | RetrievalErrorKind::InvalidDocumentId
                | RetrievalErrorKind::UnsupportedContentType
                | RetrievalErrorKind::EmptyFilterValue
                | RetrievalErrorKind::FilterLimitExceeded
                | RetrievalErrorKind::InvalidSettings => Status::invalid_argument(err.message()),
                RetrievalErrorKind::NonFiniteScore | RetrievalErrorKind::Snapshot => {
                    Status::internal(err.message())
                }
            })?;

            let query_embedding = match self
                .embedder
                .get_embeddings(&[query_request.query.clone()])
                .await
            {
                Ok(vecs) => {
                    if vecs.len() != 1
                        || vecs[0].len() != 2048
                        || vecs[0].iter().any(|f| !f.is_finite())
                    {
                        return Err(d1_status(
                            tonic::Code::Internal,
                            "embedding provider returned invalid payload",
                            &session_id,
                            &correlation_id,
                            "embedding_invalid_payload",
                        ));
                    }
                    vecs.into_iter().next().unwrap()
                }
                Err(err) => {
                    return Err(d1_status(
                        tonic::Code::Unavailable,
                        format!("embedding provider transport error: {err}"),
                        &session_id,
                        &correlation_id,
                        "embedding_transport",
                    ));
                }
            };

            let graph_outcome = attempt_graph_augmentation(
                &self.database,
                &query_embedding,
                &self.effective_settings.graph,
            )
            .await;

            tracing::Span::current().record(
                "graph_augmentation",
                match &graph_outcome {
                    GraphAugmentationOutcome::Succeeded { .. } => "succeeded",
                    GraphAugmentationOutcome::NoMatchFound => "no_match_found",
                    GraphAugmentationOutcome::AttemptedAndFailed { .. } => "attempted_and_failed",
                },
            );

            let graph_facts: Vec<prompt::GraphFactBlock> = match graph_outcome {
                GraphAugmentationOutcome::Succeeded { facts } => facts
                    .into_iter()
                    .map(|fact| prompt::GraphFactBlock { fact })
                    .collect(),
                _ => vec![],
            };

            let dense_retriever = DenseRetriever::new(self.nodes.clone());
            let dense_candidates = match dense_retriever
                .query(
                    &query_embedding,
                    &query_request,
                    &self.effective_settings.retrieval,
                )
                .await
            {
                Ok(candidates) => candidates,
                Err(err) => {
                    let (code, kind_str) = match err.kind {
                        RetrievalErrorKind::Snapshot => (tonic::Code::Unavailable, "dense_retrieval"),
                        RetrievalErrorKind::NonFiniteScore => {
                            (tonic::Code::Internal, "non_finite_score")
                        }
                        _ => (tonic::Code::Internal, "dense_retrieval_internal"),
                    };
                    return Err(d1_status(
                        code,
                        format!("dense retrieval failure: {}", err.message()),
                        &session_id,
                        &correlation_id,
                        kind_str,
                    ));
                }
            };

            let bm25_guard = self.bm25_index.read().await;
            let bm25_candidates = bm25_guard
                .retrieve(&query_request, &self.effective_settings.retrieval)
                .await
                .map_err(|err| Status::internal(err.to_string()))?;
            drop(bm25_guard);

            let fused = retrieval::fusion::fuse_candidates(
                dense_candidates,
                bm25_candidates,
                &self.effective_settings.retrieval,
            )
            .map_err(|err| match err.kind {
                RetrievalErrorKind::NonFiniteScore => {
                    Status::internal(format!("non-finite fusion score: {err}"))
                }
                _ => Status::internal(err.to_string()),
            })?;

            let reranked = self
                .reranker
                .rerank(fused)
                .await
                .map_err(|err| Status::internal(err.to_string()))?;

            let final_candidates: Vec<_> = reranked
                .into_iter()
                .take(self.effective_settings.retrieval.final_limit)
                .collect();

            if final_candidates.is_empty() {
                let snapshot = lancet::v1::RetrievalSnapshot {
                    index_generation: self.effective_settings.index_generation.clone(),
                    embedding_model: self.embedder.model_id().to_owned(),
                    vector_weight: self.effective_settings.retrieval.vector_weight,
                    bm25_weight: self.effective_settings.retrieval.bm25_weight,
                    rrf_k: snapshot_rrf_k(self.effective_settings.retrieval.rrf_k)?,
                    candidate_limit: snapshot_limit(
                        self.effective_settings.retrieval.candidate_limit,
                        "candidate_limit",
                    )?,
                    final_limit: snapshot_limit(
                        self.effective_settings.retrieval.final_limit,
                        "final_limit",
                    )?,
                    active_filter: Some(lancet::v1::DocumentFilter {
                        document_ids: query_request.filters.document_ids.clone(),
                        content_types: query_request.filters.content_types.clone(),
                    }),
                    result_hash: format!("{:x}", {
                        let hasher = DefaultHasher::new();
                        hasher.finish()
                    }),
                };

                return Ok(Response::new(QueryRagResponse {
                    answer: String::new(),
                    citations: vec![],
                    session_id,
                    answer_basis: lancet::v1::AnswerBasis::Unspecified as i32,
                    structured_citations: vec![],
                    notices: vec![lancet::v1::Notice {
                        code: "NO_EVIDENCE".to_string(),
                        message: "No completed corpus evidence matched the requested filters."
                            .to_string(),
                        severity: lancet::v1::NoticeSeverity::Info as i32,
                    }],
                    snapshot: Some(snapshot),
                }));
            }

            let evidence_blocks = prompt::assemble_evidence_blocks(&final_candidates);
            let limits = self.effective_settings.grounding_limits();
            let packed_evidence = prompt::pack_evidence_and_graph_prompt(
                &query_request.query,
                &evidence_blocks,
                &graph_facts,
                self.effective_settings.retrieval.graph_weight,
                limits.evidence_token_budget() as usize,
                limits.max_output_tokens() as usize,
            )
            .map_err(|err| Status::invalid_argument(format!("prompt assembly error: {err}")))?;

            let mut gen_req = generation::GenerationRequest::new(
                &query_request.query,
                packed_evidence.evidence.clone(),
            );
            gen_req.graph_facts = packed_evidence.graph_facts.clone();
            gen_req.graph_weight = self.effective_settings.retrieval.graph_weight;
            gen_req.session_id = Some(session_id.clone());
            gen_req.correlation_id = Some(correlation_id.clone());

        let model_output = self.generator.generate(gen_req).await.map_err(|err| {
            let (code, err_kind_str) = match err.kind {
                generation::GenerationErrorKind::InvalidRequest => {
                    (tonic::Code::InvalidArgument, "invalid_request")
                }
                generation::GenerationErrorKind::SupportedParameters => {
                    (tonic::Code::Internal, "supported_parameters")
                }
                generation::GenerationErrorKind::ProviderError => {
                    (tonic::Code::Internal, "provider_error")
                }
                generation::GenerationErrorKind::SchemaValidation => {
                    (tonic::Code::Internal, "schema_validation")
                }
                generation::GenerationErrorKind::Timeout => (tonic::Code::Internal, "timeout"),
                generation::GenerationErrorKind::Cancelled => (tonic::Code::Internal, "cancelled"),
                generation::GenerationErrorKind::SessionCorrelation => {
                    (tonic::Code::Internal, "session_correlation")
                }
            };
            d1_status(
                code,
                err.message(),
                &session_id,
                &correlation_id,
                err_kind_str,
            )
        })?;

        model_output
            .validate_grounding_with_limits(&packed_evidence.evidence, *limits)
            .map_err(|err| {
                d1_status(
                    tonic::Code::Internal,
                    err.message(),
                    &session_id,
                    &correlation_id,
                    "schema_validation",
                )
            })?;

        let resolved_citations = prompt::resolve_citations_with_max_chars(
            &model_output.cited_evidence_ids,
            &packed_evidence.evidence,
            self.effective_settings.citation_excerpt_max_chars,
        );

        if resolved_citations.len() != model_output.cited_evidence_ids.len() {
            return Err(Status::internal(
                "failed to resolve all cited evidence identities completely",
            ));
        }

        let proto_citations: Vec<String> = resolved_citations
            .iter()
            .map(|c| c.marker_id.clone())
            .collect();

        let proto_structured_citations: Vec<lancet::v1::StructuredCitation> = resolved_citations
            .iter()
            .map(|c| lancet::v1::StructuredCitation {
                chunk_id: c.chunk_id.clone(),
                document_id: c.document_id.clone(),
                title: c
                    .title
                    .as_deref()
                    .unwrap_or("Untitled Document")
                    .to_string(),
                section_path: c.section_path.as_deref().unwrap_or("Root").to_string(),
                excerpt: c.bounded_excerpt.clone(),
                is_truncated: c.is_truncated,
                score: c.score,
                rank: c.rank as i32,
                content_type: c.content_type.clone(),
            })
            .collect();

        let proto_answer_basis = match model_output.answer_basis {
            generation::AnswerBasis::Retrieval => lancet::v1::AnswerBasis::Retrieval as i32,
            generation::AnswerBasis::Mixed => lancet::v1::AnswerBasis::Mixed as i32,
            generation::AnswerBasis::ModelOnly => lancet::v1::AnswerBasis::ModelOnly as i32,
        };

        let mut proto_notices: Vec<lancet::v1::Notice> = Vec::new();
        for notice in &model_output.notices {
            proto_notices.push(lancet::v1::Notice {
                code: "NOTICE".to_string(),
                message: notice.clone(),
                severity: lancet::v1::NoticeSeverity::Info as i32,
            });
        }
        for warning in &model_output.warnings {
            proto_notices.push(lancet::v1::Notice {
                code: "WARNING".to_string(),
                message: warning.clone(),
                severity: lancet::v1::NoticeSeverity::Warning as i32,
            });
        }

        let snapshot = lancet::v1::RetrievalSnapshot {
            index_generation: self.effective_settings.index_generation.clone(),
            embedding_model: self.embedder.model_id().to_owned(),
            vector_weight: self.effective_settings.retrieval.vector_weight,
            bm25_weight: self.effective_settings.retrieval.bm25_weight,
            rrf_k: snapshot_rrf_k(self.effective_settings.retrieval.rrf_k)?,
            candidate_limit: snapshot_limit(
                self.effective_settings.retrieval.candidate_limit,
                "candidate_limit",
            )?,
            final_limit: snapshot_limit(
                self.effective_settings.retrieval.final_limit,
                "final_limit",
            )?,
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
        .instrument(query_span)
        .await
    }

    /// Traverses the knowledge graph from a seed entity and returns a hop-bounded neighborhood.
    ///
    /// The seed entity is identified by `seed_entity_id` (UUID) **or** by `seed_entity_name`
    /// (case-folded exact name lookup over the full entities table — no match returns
    /// `Status::not_found`). At least one of the two fields must be non-blank. Byte-ceiling
    /// validation on `seed_entity_name` and `relation_type_filter` runs before any table or
    /// scan operations (T-04.1-19, defence in depth against large-payload DoS). `hop_depth`
    /// must be an explicit value in `[1, effective ceiling]`; `0` is rejected, never defaulted.
    ///
    /// Traversal uses the `fetch_neighborhood` pipeline established in Plan 02, followed by
    /// `narrow_via_cypher` for Cypher membership verification (fail-open: returns the
    /// unconstrained neighbourhood if Cypher is unavailable). An optional `relation_type_filter`
    /// is applied as a post-narrowing edge predicate; when set, `nodes` is narrowed to exactly
    /// the endpoints of the surviving edges, keeping `nodes`/`edges` mutually consistent.
    ///
    /// The effective hop ceiling is `min(MAX_HOP_CAP, configured max_hop_cap)`.
    async fn query_graph(
        &self,
        request: Request<QueryGraphRequest>,
    ) -> Result<Response<QueryGraphResponse>, Status> {
        let req = request.into_inner();

        // ── Input validation (byte-ceiling checks before any DB ops) ─────────────────
        let seed_entity_name = req.seed_entity_name.trim().to_string();
        let seed_entity_id = req.seed_entity_id.trim().to_string();
        let relation_type_filter = req.relation_type_filter.trim().to_string();

        if seed_entity_name.len() > graph::MAX_SEED_ENTITY_NAME_BYTES {
            return Err(Status::invalid_argument(format!(
                "seed_entity_name exceeds {} byte limit",
                graph::MAX_SEED_ENTITY_NAME_BYTES
            )));
        }
        if relation_type_filter.len() > graph::MAX_RELATION_TYPE_FILTER_BYTES {
            return Err(Status::invalid_argument(format!(
                "relation_type_filter exceeds {} byte limit",
                graph::MAX_RELATION_TYPE_FILTER_BYTES
            )));
        }

        // ── Resolve seed entity UUID ─────────────────────────────────────────────────
        let resolved_seed_id: String = if !seed_entity_id.is_empty() {
            // Caller supplied an explicit UUID; validate it.
            let parsed =
                Uuid::parse_str(&seed_entity_id).map_err(|_| {
                    Status::invalid_argument("seed_entity_id must be a valid UUID string")
                })?;
            parsed.to_string()
        } else if !seed_entity_name.is_empty() {
            // Name-based lookup: read entity_id/name in full into memory (a small,
            // bounded scan — no secondary index exists on entities.name, and a
            // case-folded exact match cannot be pushed down as a LanceDB predicate;
            // T-04.1-19 accepts this table-scan-cost trade-off explicitly) and
            // case-fold both sides the same way this codebase's D-05 write-time
            // merge step does (`.trim().to_lowercase()`, mirrored from
            // extract_and_persist_entities), so a lookup finds exactly what the
            // write-time merge would have folded together.
            let entities_table = self
                .database
                .entities_table()
                .await
                .map_err(|e| Status::internal(format!("entities table error: {e}")))?;

            let batches: Vec<arrow_array::RecordBatch> = entities_table
                .query()
                .select(lancedb::query::Select::columns(&["entity_id", "name"]))
                .execute()
                .await
                .map_err(|e| Status::internal(format!("entity name lookup error: {e}")))?
                .try_collect()
                .await
                .map_err(|e| {
                    Status::internal(format!("entity name lookup collect error: {e}"))
                })?;

            let folded_query = seed_entity_name.trim().to_lowercase();
            let mut matched_ids: Vec<String> = Vec::new();
            for batch in &batches {
                let id_col = batch
                    .column_by_name("entity_id")
                    .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
                let name_col = batch
                    .column_by_name("name")
                    .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
                if let (Some(id_col), Some(name_col)) = (id_col, name_col) {
                    for i in 0..batch.num_rows() {
                        if id_col.is_null(i) || name_col.is_null(i) {
                            continue;
                        }
                        if name_col.value(i).trim().to_lowercase() == folded_query {
                            matched_ids.push(id_col.value(i).to_string());
                        }
                    }
                }
            }

            if matched_ids.is_empty() {
                return Err(Status::not_found(format!(
                    "no entity found with name '{seed_entity_name}'"
                )));
            }
            matched_ids.sort();
            if matched_ids.len() > 1 {
                // Defensive only: ExactMatchResolver already merges entities by
                // case-folded name at write time (D-05), so a duplicate here would
                // itself indicate that merge invariant drifted. Deterministic,
                // operator-visible, not request-failing.
                tracing::warn!(
                    name = %seed_entity_name,
                    count = matched_ids.len(),
                    "multiple entities matched case-folded name lookup; using lexicographically smallest entity_id"
                );
            }
            matched_ids.into_iter().next().expect("matched_ids checked non-empty above")
        } else {
            return Err(Status::invalid_argument(
                "at least one of seed_entity_id or seed_entity_name must be non-blank",
            ));
        };

        // ── Hop-depth clamping ───────────────────────────────────────────────────────
        // hop_depth = 0 is rejected outright (clamp_hop_cap_with_ceiling's own 0-check),
        // not silently treated as "unset" — a caller must supply an explicit >=1 value.
        let effective_depth = graph::clamp_hop_cap_with_ceiling(
            req.hop_depth,
            self.effective_settings.graph.max_hop_cap,
        )
        .map_err(|e| Status::invalid_argument(e.message().to_string()))?;

        // ── Neighborhood fetch + Cypher narrowing ────────────────────────────────────
        let (entities_batch, edges_batch) =
            graph::fetch_neighborhood(&self.database, &resolved_seed_id, effective_depth, true)
                .await
                .map_err(|e| Status::internal(format!("fetch_neighborhood: {:?}", e.kind)))?;

        let (entities_batch, edges_batch) =
            graph::narrow_via_cypher(&entities_batch, &edges_batch, &resolved_seed_id, effective_depth)
                .await;

        // ── Optional relation_type_filter ────────────────────────────────────────────
        let filter_applied = !relation_type_filter.is_empty();
        let edges_batch = if filter_applied {
            let rel_col = edges_batch
                .column_by_name("relation_type")
                .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
            if let Some(rel_col) = rel_col {
                let mask: arrow_array::BooleanArray = (0..edges_batch.num_rows())
                    .map(|i| {
                        Some(
                            !rel_col.is_null(i)
                                && rel_col.value(i) == relation_type_filter.as_str(),
                        )
                    })
                    .collect();
                arrow_select::filter::filter_record_batch(&edges_batch, &mask)
                    .unwrap_or(edges_batch)
            } else {
                edges_batch
            }
        } else {
            edges_batch
        };

        // ── Build QueryGraphResponse ─────────────────────────────────────────────────
        // Without a relation_type_filter: nodes is the full (Cypher-constrained,
        // seed-inclusive) entities_batch. With a filter: nodes is redefined as
        // exactly the entities that are an endpoint (source or target) of one of
        // the FILTERED edges — a strict subset, never the full unfiltered set, so
        // nodes/edges stay mutually consistent under filtering (never a node the
        // response's own edges don't reference, and never an edge pointing at a
        // node the response never lists).
        let node_source_batch: arrow_array::RecordBatch = if filter_applied {
            let src_col = edges_batch
                .column_by_name("source_node_id")
                .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
            let tgt_col = edges_batch
                .column_by_name("target_node_id")
                .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());

            let mut endpoint_ids: HashSet<String> = HashSet::new();
            if let (Some(src_col), Some(tgt_col)) = (src_col, tgt_col) {
                for i in 0..edges_batch.num_rows() {
                    if !src_col.is_null(i) {
                        endpoint_ids.insert(src_col.value(i).to_string());
                    }
                    if !tgt_col.is_null(i) {
                        endpoint_ids.insert(tgt_col.value(i).to_string());
                    }
                }
            }

            let entity_id_col_for_mask = entities_batch
                .column_by_name("entity_id")
                .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
            let node_mask: arrow_array::BooleanArray = (0..entities_batch.num_rows())
                .map(|i| {
                    Some(entity_id_col_for_mask.is_some_and(|col| {
                        !col.is_null(i) && endpoint_ids.contains(col.value(i))
                    }))
                })
                .collect();
            arrow_select::filter::filter_record_batch(&entities_batch, &node_mask)
                .unwrap_or_else(|_| entities_batch.clone())
        } else {
            entities_batch.clone()
        };

        let entity_id_col = node_source_batch
            .column_by_name("entity_id")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
        let entity_name_col = node_source_batch
            .column_by_name("name")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
        let entity_type_col = node_source_batch
            .column_by_name("entity_type")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());

        let mut nodes = Vec::with_capacity(node_source_batch.num_rows());
        if let (Some(id_col), Some(name_col), Some(type_col)) =
            (entity_id_col, entity_name_col, entity_type_col)
        {
            for i in 0..node_source_batch.num_rows() {
                nodes.push(QueryGraphNode {
                    entity_id: if id_col.is_null(i) { String::new() } else { id_col.value(i).to_string() },
                    name: if name_col.is_null(i) { String::new() } else { name_col.value(i).to_string() },
                    entity_type: if type_col.is_null(i) { String::new() } else { type_col.value(i).to_string() },
                });
            }
        }

        let src_col = edges_batch
            .column_by_name("source_node_id")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
        let tgt_col = edges_batch
            .column_by_name("target_node_id")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
        let rel_col = edges_batch
            .column_by_name("relation_type")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
        let weight_col = edges_batch
            .column_by_name("weight")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::Float32Array>());

        let mut edges = Vec::with_capacity(edges_batch.num_rows());
        if let (Some(src), Some(tgt), Some(rel)) = (src_col, tgt_col, rel_col) {
            for i in 0..edges_batch.num_rows() {
                edges.push(QueryGraphEdge {
                    source_entity_id: if src.is_null(i) { String::new() } else { src.value(i).to_string() },
                    target_entity_id: if tgt.is_null(i) { String::new() } else { tgt.value(i).to_string() },
                    relation_type: if rel.is_null(i) { String::new() } else { rel.value(i).to_string() },
                    weight: weight_col
                        .and_then(|w| if w.is_null(i) { None } else { Some(w.value(i)) })
                        .unwrap_or(1.0),
                });
            }
        }

        Ok(Response::new(QueryGraphResponse { nodes, edges }))
    }
}

trait EmbeddingProvider: Send + Sync {
    fn model_id(&self) -> &str {
        // Existing test doubles predate the model identity seam. Production
        // adapters override this with their configured provider identity.
        client::EMBEDDING_MODEL
    }

    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>>;
}

impl EmbeddingProvider for OpenRouterClient {
    fn model_id(&self) -> &str {
        OpenRouterClient::model_id(self)
    }

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
    embedding_model: &str,
) -> Result<(), String> {
    replace_document_with_faults(
        database,
        job,
        chunks,
        embeddings,
        embedding_model,
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
    embedding_model: &str,
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
                Arc::new(StringArray::from(vec![embedding_model; chunks.len()])),
                Arc::new(Int64Array::from(vec![Some(ingested_at); chunks.len()])),
                Arc::new(StringArray::from(vec![
                    Some(content_type(&job.filename));
                    chunks.len()
                ])),
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
    let embedding_model = embedder.model_id().to_owned();

    let database_span = tracing::info_span!("persist_document", document_id = %job.document_id, chunk_count = chunks.len());
    async {
        replace_document_with_faults(
            database,
            job,
            &chunks,
            &embeddings,
            &embedding_model,
            boundary,
        )
        .await
    }
    .instrument(database_span)
    .await?;
    Ok(i32::try_from(chunks.len()).unwrap_or(i32::MAX))
}

/// Summary of entity_edges row count changes on re-ingestion.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ExtractionPersistSummary {
    pub prior_entity_edges_count: usize,
    pub written_entity_edges_count: usize,
}

/// Extracts entities and relationships from a document and persists them to LanceDB.
///
/// Phase A (read-only): extracts per-chunk entities and relations, reading entities_table for exact match resolution.
/// Phase B (mutation): captures table versions, deletes existing entity_edges for document_id, and inserts updated/new entity and edge rows.
/// If Phase B fails, table versions are restored. This rollback is safe because document ingestion is serialized through spawn_worker_with_boundary.
pub(crate) async fn extract_and_persist_entities(
    database: &DatabaseManager,
    job: &IngestionJob,
    extraction_generator: &dyn graph::extraction::ExtractionGenerator,
    embedder: &dyn EmbeddingProvider,
) -> Result<ExtractionPersistSummary, String> {
    let (_strategy, chunks) = chunk_ingestion_job(job);
    let chunk_ids: Vec<String> = (0..chunks.len())
        .map(|index| format!("{}:{index}", job.document_id))
        .collect();

    // Phase A (read-only)
    let stream_items: Vec<(usize, String, String)> = chunks
        .iter()
        .enumerate()
        .filter_map(|(index, chunk)| {
            if chunk.content.trim().len() < graph::extraction::MIN_CHUNK_CONTENT_LENGTH {
                None
            } else {
                Some((index, chunk_ids[index].clone(), chunk.content.clone()))
            }
        })
        .collect();

    let mut indexed_results = futures::stream::iter(stream_items.into_iter().map(|(index, chunk_id, chunk_text)| {
        let doc_id = job.document_id.clone();
        async move {
            let req = graph::extraction::ExtractionRequest {
                chunk_id: chunk_id.clone(),
                document_id: doc_id,
                chunk_text,
            };
            let res = graph::extraction::extract_with_retry(extraction_generator, req).await;
            (index, chunk_id, res)
        }
    }))
    .buffer_unordered(5)
    .collect::<Vec<_>>()
    .await;

    indexed_results.sort_unstable_by_key(|(index, _, _)| *index);

    let mut chunk_outputs = Vec::new();
    for (_index, chunk_id, res) in indexed_results {
        match res {
            Ok(output) => chunk_outputs.push((chunk_id, output)),
            Err(e) => {
                tracing::warn!(
                    %job.document_id,
                    %chunk_id,
                    error = %e,
                    "entity extraction failed for chunk"
                );
            }
        }
    }

    let entities_table = database.entities_table().await.map_err(|e| e.to_string())?;
    let entity_edges_table = database.entity_edges_table().await.map_err(|e| e.to_string())?;

    // Read known entities for exact-match resolver
    let known_batches: Vec<arrow_array::RecordBatch> = entities_table
        .query()
        .select(lancedb::query::Select::columns(&[
            "entity_id",
            "name",
            "entity_type",
            "name_vector",
            "source_chunk_ids",
        ]))
        .execute()
        .await
        .map_err(|e| e.to_string())?
        .try_collect()
        .await
        .map_err(|e| e.to_string())?;

    struct ExistingEntity {
        entity_id: String,
        name: String,
        entity_type: String,
        name_vector: Vec<f32>,
        source_chunk_ids: Vec<String>,
    }

    let mut known_map: HashMap<String, ExistingEntity> = HashMap::new();
    for batch in &known_batches {
        let id_col = batch
            .column_by_name("entity_id")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
        let name_col = batch
            .column_by_name("name")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
        let type_col = batch
            .column_by_name("entity_type")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::StringArray>());
        let vec_col = batch
            .column_by_name("name_vector")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::FixedSizeListArray>());
        let chunks_col = batch
            .column_by_name("source_chunk_ids")
            .and_then(|c| c.as_any().downcast_ref::<arrow_array::ListArray>());

        if let (Some(id_col), Some(name_col), Some(type_col), Some(vec_col), Some(chunks_col)) =
            (id_col, name_col, type_col, vec_col, chunks_col)
        {
            for i in 0..batch.num_rows() {
                let entity_id = id_col.value(i).to_string();
                let name = name_col.value(i).to_string();
                let entity_type = type_col.value(i).to_string();
                let folded = name.trim().to_lowercase();

                let vec_values = vec_col.value(i);
                let float_vec = vec_values
                    .as_any()
                    .downcast_ref::<arrow_array::Float32Array>()
                    .map(|f| f.values().to_vec())
                    .unwrap_or_default();

                let chunks_arr = chunks_col.value(i);
                let str_chunks = chunks_arr
                    .as_any()
                    .downcast_ref::<arrow_array::StringArray>();
                let mut source_chunk_ids = Vec::new();
                if let Some(str_chunks) = str_chunks {
                    for j in 0..str_chunks.len() {
                        if !str_chunks.is_null(j) {
                            source_chunk_ids.push(str_chunks.value(j).to_string());
                        }
                    }
                }

                known_map.insert(
                    folded,
                    ExistingEntity {
                        entity_id,
                        name,
                        entity_type,
                        name_vector: float_vec,
                        source_chunk_ids,
                    },
                );
            }
        }
    }

    struct StagedEntity {
        entity_id: String,
        name: String,
        entity_type: String,
        name_vector: Option<Vec<f32>>,
        source_chunk_ids: Vec<String>,
        is_new: bool,
    }

    let mut resolved_entities: HashMap<String, StagedEntity> = HashMap::new();
    let mut chunk_entity_maps: HashMap<String, HashMap<String, String>> = HashMap::new();

    for (chunk_id, output) in &chunk_outputs {
        let mut chunk_map = HashMap::new();
        for entity in &output.entities {
            let folded = entity.name.trim().to_lowercase();
            let entity_id = if let Some(existing) = known_map.get(&folded) {
                let entry = resolved_entities.entry(folded.clone()).or_insert_with(|| {
                    StagedEntity {
                        entity_id: existing.entity_id.clone(),
                        name: existing.name.clone(),
                        entity_type: existing.entity_type.clone(),
                        name_vector: Some(existing.name_vector.clone()),
                        source_chunk_ids: existing.source_chunk_ids.clone(),
                        is_new: false,
                    }
                });
                if !entry.source_chunk_ids.contains(chunk_id) {
                    entry.source_chunk_ids.push(chunk_id.clone());
                }
                existing.entity_id.clone()
            } else if let Some(entry) = resolved_entities.get_mut(&folded) {
                if !entry.source_chunk_ids.contains(chunk_id) {
                    entry.source_chunk_ids.push(chunk_id.clone());
                }
                entry.entity_id.clone()
            } else {
                let new_id = Uuid::new_v4().to_string();
                resolved_entities.insert(
                    folded.clone(),
                    StagedEntity {
                        entity_id: new_id.clone(),
                        name: entity.name.clone(),
                        entity_type: entity.entity_type.clone(),
                        name_vector: None,
                        source_chunk_ids: vec![chunk_id.clone()],
                        is_new: true,
                    },
                );
                new_id
            };
            chunk_map.insert(folded, entity_id);
        }
        chunk_entity_maps.insert(chunk_id.clone(), chunk_map);
    }

    let new_names: Vec<String> = resolved_entities
        .values()
        .filter(|e| e.is_new)
        .map(|e| e.name.clone())
        .collect();

    let new_embeddings = if !new_names.is_empty() {
        embedder
            .get_embeddings(&new_names)
            .await
            .map_err(|e| e.to_string())?
    } else {
        vec![]
    };

    let mut name_to_emb: HashMap<String, Vec<f32>> = HashMap::new();
    for (name, emb) in new_names.into_iter().zip(new_embeddings.into_iter()) {
        name_to_emb.insert(name, emb);
    }

    for entity in resolved_entities.values_mut() {
        if entity.is_new {
            if let Some(emb) = name_to_emb.remove(&entity.name) {
                entity.name_vector = Some(emb);
            }
        }
    }

    struct StagedEdge {
        edge_id: String,
        source_node_id: String,
        target_node_id: String,
        relation_type: String,
        weight: f32,
        document_id: String,
    }

    let mut staged_edges = Vec::new();
    for (chunk_id, output) in &chunk_outputs {
        if let Some(chunk_map) = chunk_entity_maps.get(chunk_id) {
            for rel in &output.relations {
                let src_folded = rel.source.trim().to_lowercase();
                let tgt_folded = rel.target.trim().to_lowercase();

                if let (Some(src_id), Some(tgt_id)) =
                    (chunk_map.get(&src_folded), chunk_map.get(&tgt_folded))
                {
                    staged_edges.push(StagedEdge {
                        edge_id: Uuid::new_v4().to_string(),
                        source_node_id: src_id.clone(),
                        target_node_id: tgt_id.clone(),
                        relation_type: rel.relation_type.clone(),
                        weight: rel.confidence,
                        document_id: job.document_id.clone(),
                    });
                } else {
                    tracing::warn!(
                        %job.document_id,
                        %chunk_id,
                        source = %rel.source,
                        target = %rel.target,
                        "dropping relation with unmapped entity endpoint in chunk"
                    );
                }
            }
        }
    }

    // Phase B (mutation phase)
    let version_entities = entities_table.version().await.map_err(|e| e.to_string())?;
    let version_edges = entity_edges_table.version().await.map_err(|e| e.to_string())?;

    let edge_pred = format!("document_id = '{}'", escape_sql_literal(&job.document_id));
    let prior_batches: Vec<arrow_array::RecordBatch> = entity_edges_table
        .query()
        .only_if(&edge_pred)
        .execute()
        .await
        .map_err(|e| format!("count prior entity_edges failed: {e}"))?
        .try_collect()
        .await
        .map_err(|e| format!("count prior entity_edges collect failed: {e}"))?;
    let prior_entity_edges_count: usize = prior_batches.iter().map(|b| b.num_rows()).sum();

    let run_mutations = async {
        entity_edges_table
            .delete(&edge_pred)
            .await
            .map_err(|e| format!("delete entity_edges failed: {e}"))?;

        let updated_entities: Vec<&StagedEntity> = resolved_entities
            .values()
            .filter(|e| !e.is_new)
            .collect();
        for entity in &updated_entities {
            let ent_pred = format!("entity_id = '{}'", escape_sql_literal(&entity.entity_id));
            entities_table
                .delete(&ent_pred)
                .await
                .map_err(|e| format!("delete updated entity failed: {e}"))?;
        }

        let all_entities: Vec<&StagedEntity> = resolved_entities.values().collect();
        if !all_entities.is_empty() {
            let schema = db::entities_schema();
            let mut entity_ids = Vec::new();
            let mut names = Vec::new();
            let mut entity_types = Vec::new();
            let mut source_chunks_list = Vec::new();

            for e in &all_entities {
                entity_ids.push(e.entity_id.clone());
                names.push(e.name.clone());
                entity_types.push(e.entity_type.clone());
                source_chunks_list.push(e.source_chunk_ids.clone());
            }

            let num_rows = all_entities.len();
            let id_arr = Arc::new(arrow_array::StringArray::from(entity_ids));
            let name_arr = Arc::new(arrow_array::StringArray::from(names));
            let type_arr = Arc::new(arrow_array::StringArray::from(entity_types));
            let vec_arr = Arc::new(
                arrow_array::FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
                    all_entities.iter().map(|e| e.name_vector.as_ref().map(|v| v.iter().copied().map(Some))),
                    2048,
                ),
            );

            let mut chunk_builder =
                arrow_array::builder::ListBuilder::new(arrow_array::builder::StringBuilder::new());
            for chunk_ids in source_chunks_list {
                for cid in chunk_ids {
                    chunk_builder.values().append_value(cid);
                }
                chunk_builder.append(true);
            }
            let chunk_arr = Arc::new(chunk_builder.finish());

            let null_summary = new_null_array(schema.field(4).data_type(), num_rows);
            let null_summary_vec = new_null_array(schema.field(5).data_type(), num_rows);
            let null_refs = new_null_array(schema.field(6).data_type(), num_rows);
            let null_comm = new_null_array(schema.field(7).data_type(), num_rows);

            let batch = arrow_array::RecordBatch::try_new(
                schema,
                vec![
                    id_arr,
                    name_arr,
                    type_arr,
                    vec_arr,
                    null_summary,
                    null_summary_vec,
                    null_refs,
                    null_comm,
                    chunk_arr,
                ],
            )
            .map_err(|e| format!("build entities RecordBatch failed: {e}"))?;

            entities_table
                .add(batch)
                .execute()
                .await
                .map_err(|e| format!("add entities failed: {e}"))?;
        }

        if !staged_edges.is_empty() {
            let schema = db::entity_edges_schema();
            let mut edge_ids = Vec::new();
            let mut src_ids = Vec::new();
            let mut tgt_ids = Vec::new();
            let mut rel_types = Vec::new();
            let mut weights = Vec::new();
            let mut doc_ids = Vec::new();

            for edge in &staged_edges {
                edge_ids.push(edge.edge_id.clone());
                src_ids.push(edge.source_node_id.clone());
                tgt_ids.push(edge.target_node_id.clone());
                rel_types.push(edge.relation_type.clone());
                weights.push(edge.weight);
                doc_ids.push(edge.document_id.clone());
            }

            let num_rows = staged_edges.len();
            let edge_id_arr = Arc::new(arrow_array::StringArray::from(edge_ids));
            let src_arr = Arc::new(arrow_array::StringArray::from(src_ids));
            let tgt_arr = Arc::new(arrow_array::StringArray::from(tgt_ids));
            let rel_arr = Arc::new(arrow_array::StringArray::from(rel_types));
            let weight_arr = Arc::new(arrow_array::Float32Array::from(weights));
            let doc_arr = Arc::new(arrow_array::StringArray::from(doc_ids));

            let null_summary = new_null_array(schema.field(6).data_type(), num_rows);
            let null_summary_vec = new_null_array(schema.field(7).data_type(), num_rows);

            let batch = arrow_array::RecordBatch::try_new(
                schema,
                vec![
                    edge_id_arr,
                    src_arr,
                    tgt_arr,
                    rel_arr,
                    weight_arr,
                    doc_arr,
                    null_summary,
                    null_summary_vec,
                ],
            )
            .map_err(|e| format!("build entity_edges RecordBatch failed: {e}"))?;

            entity_edges_table
                .add(batch)
                .execute()
                .await
                .map_err(|e| format!("add entity_edges failed: {e}"))?;
        }

        let fresh_edges_table = database.entity_edges_table().await.map_err(|e| format!("open fresh entity_edges_table failed: {e}"))?;
        let written_batches: Vec<arrow_array::RecordBatch> = fresh_edges_table
            .query()
            .only_if(&edge_pred)
            .execute()
            .await
            .map_err(|e| format!("count written entity_edges failed: {e}"))?
            .try_collect()
            .await
            .map_err(|e| format!("count written entity_edges collect failed: {e}"))?;
        let written_entity_edges_count: usize = written_batches.iter().map(|b| b.num_rows()).sum();

        Ok(ExtractionPersistSummary {
            prior_entity_edges_count,
            written_entity_edges_count,
        })
    };

    match run_mutations.await {
        Ok(summary) => Ok(summary),
        Err(mut_err) => {
            tracing::error!(
                %job.document_id,
                error = %mut_err,
                "Phase B mutation failed, attempting table version restores"
            );
            let _ = restore_version(&entities_table, version_entities).await;
            let _ = restore_version(&entity_edges_table, version_edges).await;
            Err(mut_err)
        }
    }
}

fn spawn_worker(
    receiver: mpsc::Receiver<IngestionJob>,
    statuses: Arc<DashMap<String, IngestionStatus>>,
    database: DatabaseManager,
    embedder: Arc<dyn EmbeddingProvider>,
    extraction_generator: Arc<dyn graph::extraction::ExtractionGenerator>,
    shutdown: watch::Receiver<bool>,
) -> JoinHandle<()> {
    spawn_worker_with_boundary(
        receiver,
        statuses,
        database,
        embedder,
        extraction_generator,
        Arc::new(LanceDbReplacementMutationBoundary),
        shutdown,
    )
}

fn spawn_worker_with_boundary(
    receiver: mpsc::Receiver<IngestionJob>,
    statuses: Arc<DashMap<String, IngestionStatus>>,
    database: DatabaseManager,
    embedder: Arc<dyn EmbeddingProvider>,
    extraction_generator: Arc<dyn graph::extraction::ExtractionGenerator>,
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
                    match extract_and_persist_entities(
                        &database,
                        &job,
                        extraction_generator.as_ref(),
                        embedder.as_ref(),
                    )
                    .await
                    {
                        Ok(summary) => {
                            if summary.written_entity_edges_count < summary.prior_entity_edges_count {
                                tracing::warn!(
                                    %job.document_id,
                                    prior = summary.prior_entity_edges_count,
                                    written = summary.written_entity_edges_count,
                                    "graph completeness reduced on re-ingestion"
                                );
                            }
                        }
                        Err(err) => {
                            tracing::error!(
                                %job.document_id,
                                error = %err,
                                "extract_and_persist_entities failed, prior graph preserved"
                            );
                        }
                    }
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
    let effective_settings = EffectiveRagSettings::try_from_settings(&settings)
        .map_err(|err| format!("invalid RAG configuration: {err}"))?;
    let database = DatabaseManager::initialize(&settings.engine.lancedb_path).await?;
    let nodes = database.nodes_table().await?;
    let bm25_index = Bm25Index::from_table(&nodes, effective_settings.retrieval.bm25.clone())
        .await
        .map_err(|error| format!("initial BM25 snapshot build failed: {error}"))?;
    tracing::info!(document_count = bm25_index.len(), "BM25 snapshot built");
    let table = database.staged_documents_table().await?;
    let api_key = std::env::var("OPENROUTER_API_KEY")
        .map_err(|_| "OPENROUTER_API_KEY environment variable is not set")?;
    if api_key.trim().is_empty() {
        return Err("OPENROUTER_API_KEY environment variable must not be empty or blank".into());
    }
    let embedding_config = OpenRouterEmbeddingConfig::new(
        effective_settings.embedding_model.clone(),
        effective_settings.embedding_endpoint.clone(),
    )?;
    let embedder = Arc::new(OpenRouterClient::new_with_config(
        api_key.clone(),
        embedding_config,
    )?);
    let extraction_config = generation::openrouter::OpenRouterGenerationConfig::new(
        effective_settings.generation_model.clone(),
        effective_settings.chat_endpoint.clone(),
        effective_settings.model_metadata_endpoint.clone(),
        Duration::from_secs(effective_settings.generation_timeout_secs),
        0.0,
        1.0,
        768,
        768,
    )?;
    let extraction_generator: Arc<dyn graph::extraction::ExtractionGenerator> =
        Arc::new(graph::extraction::OpenRouterExtractionGenerator::new_with_config(
            api_key.clone(),
            extraction_config,
        )?);

    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);

    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        embedder.clone(),
        extraction_generator.clone(),
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

    let generation_config =
        generation::openrouter::OpenRouterGenerationConfig::from_effective_limits(
            effective_settings.generation_model.clone(),
            effective_settings.chat_endpoint.clone(),
            effective_settings.model_metadata_endpoint.clone(),
            Duration::from_secs(effective_settings.generation_timeout_secs),
            effective_settings.temperature,
            effective_settings.top_p,
            effective_settings.grounding_limits_arc(),
        )?;
    let generator: Arc<dyn generation::Generator> = Arc::new(
        generation::openrouter::OpenRouterGenerator::new_with_config(api_key, generation_config)?,
    );

    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
        nodes,
        bm25_index: Arc::new(tokio::sync::RwLock::new(bm25_index)),
        effective_settings,
        generator,
        embedder: embedder.clone(),
        reranker: Arc::new(rerank::NoOpReranker::new()),
        database: database.clone(),
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
