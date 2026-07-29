use std::{
    collections::HashMap,
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
use futures::future::BoxFuture;
use lancedb::Table;
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

use chunker::{chunk_fixed_size, chunk_markdown, estimate_tokens, Chunk};
use client::{OpenRouterClient, EMBEDDING_MODEL};
use engine::db::{DatabaseManager, EntityResolver, ExactMatchResolver};

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

#[derive(Debug, Clone, Deserialize)]
struct Settings {
    engine: EngineSettings,
}
#[derive(Debug, Clone, Deserialize)]
struct EngineSettings {
    grpc_addr: String,
    lancedb_path: String,
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
    builder
        .add_source(config::Environment::with_prefix("LANCET").separator("__"))
        .build()?
        .try_deserialize()
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

#[derive(Clone)]
pub struct LancetServiceImpl {
    table: Table,
    statuses: Arc<DashMap<String, IngestionStatus>>,
    queue: mpsc::Sender<IngestionJob>,
}

impl LancetServiceImpl {
    async fn persist_raw(&self, document_id: &str, data: &[u8]) -> Result<(), Status> {
        let predicate = format!("document_id = '{}'", sql_string(document_id));
        self.table.delete(&predicate).await.map_err(internal)?;
        let schema = self.table.schema().await.map_err(internal)?;
        let batch = RecordBatch::try_new(
            schema,
            vec![
                Arc::new(StringArray::from(vec![document_id])),
                Arc::new(BinaryArray::from_vec(vec![data])),
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
        self.persist_raw(&document_id, &raw).await?;
        self.statuses
            .insert(document_id.clone(), IngestionStatus::queued());
        permit.send(IngestionJob {
            document_id: document_id.clone(),
            filename,
            raw_data: raw,
            metadata,
            chunk_settings: parsed_settings.expect("parsed settings present for non-empty stream"),
        });
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
        let state = self
            .statuses
            .get(&id)
            .ok_or_else(|| Status::not_found("document status not found"))?;
        Ok(Response::new(GetIngestionStatusResponse {
            document_id: id,
            status: state.status.clone(),
            chunk_count: state.chunk_count,
            error_message: state.error_message.clone(),
        }))
    }

    async fn query_rag(
        &self,
        request: Request<QueryRagRequest>,
    ) -> Result<Response<QueryRagResponse>, Status> {
        let req = request.into_inner();
        Ok(Response::new(QueryRagResponse {
            answer: format!("Placeholder answer for: {}", req.query),
            citations: vec![],
            session_id: req.session_id,
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
        loop {
            let job = tokio::select! {
                biased;
                changed = shutdown.changed() => {
                    if changed.is_ok() && *shutdown.borrow() {
                        break;
                    }
                    continue;
                }
                job = receiver.recv() => match job {
                    Some(job) => job,
                    None => break,
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
    let table = database.staged_documents_table().await?;
    let embedder = Arc::new(OpenRouterClient::from_env()?);
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let worker = spawn_worker(receiver, statuses.clone(), database, embedder, shutdown_rx);
    let service = LancetServiceImpl {
        table,
        statuses,
        queue: sender,
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
