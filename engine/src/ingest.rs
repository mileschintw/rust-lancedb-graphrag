//! Staged-document ingestion pipeline, chunking, embeddings, LanceDB mutations, and background workers.
//!
//! Owns the staged-document ingestion pipeline: job admission and chunk settings,
//! the embedding-provider abstraction, staged-row reading and generation selection,
//! the LanceDB replacement/rollback boundary, and the background worker.

use std::{
    collections::HashMap,
    path::Path,
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use arrow_array::{
    new_null_array, types::Float32Type, Array, BinaryArray, FixedSizeListArray, Float32Array,
    Int32Array, Int64Array, RecordBatch, StringArray,
};
use dashmap::DashMap;
use futures::{future::BoxFuture, StreamExt, TryStreamExt};
use lancedb::{
    query::{ExecutableQuery, QueryBase},
    Table,
};
use tokio::{
    sync::{mpsc, watch},
    task::JoinHandle,
};
use tonic::Status;
use tracing::Instrument;
use uuid::Uuid;

use crate::chunker::{chunk_fixed_size, chunk_markdown, estimate_tokens, Chunk};
use crate::client::{self, OpenRouterClient};
use crate::db::{self, DatabaseManager, EntityResolver, ExactMatchResolver};
use crate::graph::{self, escape_sql_literal};

pub const MAX_DOCUMENT_BYTES: usize = 10 << 20;
pub const QUEUE_CAPACITY: usize = 100;

#[derive(Debug, Clone)]
pub struct IngestionStatus {
    pub status: String,
    pub chunk_count: i32,
    pub error_message: String,
}

impl IngestionStatus {
    pub fn queued() -> Self {
        Self {
            status: "queued".into(),
            chunk_count: 0,
            error_message: String::new(),
        }
    }
}

pub const DEFAULT_CHUNK_SIZE: usize = 500;
pub const DEFAULT_CHUNK_OVERLAP: usize = 50;
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

pub fn parse_chunk_settings(metadata: &HashMap<String, String>) -> Result<ChunkSettings, Status> {
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

#[derive(Debug, Clone)]
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
pub enum ReplacementMutation {
    EdgesDelete,
    NodesDelete,
    DocumentsDelete,
    DocumentsAdd,
    NodesAdd,
    EdgesAdd,
    StagingAdd,
    StagingDelete,
}

pub trait ReplacementMutationBoundary: Send + Sync {
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

pub struct LanceDbReplacementMutationBoundary;

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

pub fn chunk_ingestion_job(job: &IngestionJob) -> (&'static str, Vec<Chunk>) {
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

pub struct StagedJobRow {
    pub document_id: String,
    pub generation: i64,
    pub job: IngestionJob,
}

pub fn select_latest_staged_rows(rows: Vec<StagedJobRow>) -> Result<Vec<IngestionJob>, String> {
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

fn validate_document_id_internal(document_id: &str) -> Result<(), Status> {
    let id = Uuid::parse_str(document_id)
        .map_err(|_| Status::invalid_argument("document_id must be a UUIDv4 string"))?;
    if id.get_version_num() != 4 || id.get_variant() != uuid::Variant::RFC4122 {
        return Err(Status::invalid_argument(
            "document_id must be a UUIDv4 string",
        ));
    }
    Ok(())
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
            if validate_document_id_internal(&doc_id).is_err() {
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

pub async fn get_max_staged_generation(
    table: &Table,
    document_id: &str,
) -> Result<Option<i64>, String> {
    let pred = format!("document_id = '{}'", escape_sql_literal(document_id));
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

pub async fn persist_raw_with_boundary(
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
        escape_sql_literal(&job.document_id)
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
            escape_sql_literal(&job.document_id)
        );
        boundary
            .delete(ReplacementMutation::StagingDelete, table, &delete_pred)
            .await?;
    }

    Ok(())
}

pub fn content_hash(content: &str) -> String {
    let mut hasher = blake3::Hasher::new();
    hasher.update(content.as_bytes());
    hasher.finalize().to_hex().to_string()
}

pub fn content_type(filename: &str) -> &'static str {
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
pub async fn replace_document(
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

pub async fn restore_version(table: &Table, version: u64) -> Result<(), String> {
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
pub async fn rollback_replacement(
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

pub async fn replace_document_with_faults(
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
    let predicate = format!("document_id = '{}'", escape_sql_literal(&job.document_id));
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
pub async fn process_job(
    job: &IngestionJob,
    database: &DatabaseManager,
    embedder: &dyn EmbeddingProvider,
) -> Result<i32, String> {
    process_job_with_boundary(job, database, embedder, &LanceDbReplacementMutationBoundary).await
}

pub async fn process_job_with_boundary(
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
pub struct ExtractionPersistSummary {
    pub prior_entity_edges_count: usize,
    pub written_entity_edges_count: usize,
}

/// Extracts entities and relationships from a document and persists them to LanceDB.
///
/// Phase A (read-only): extracts per-chunk entities and relations, reading entities_table for exact match resolution.
/// Phase B (mutation): captures table versions, deletes existing entity_edges for document_id, and inserts updated/new entity and edge rows.
/// If Phase B fails, table versions are restored. This rollback is safe because document ingestion is serialized through spawn_worker_with_boundary.
pub async fn extract_and_persist_entities(
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

    let mut indexed_results = futures::stream::iter(stream_items.into_iter().map(
        |(index, chunk_id, chunk_text)| {
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
        },
    ))
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
    let entity_edges_table = database
        .entity_edges_table()
        .await
        .map_err(|e| e.to_string())?;

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
                let entry =
                    resolved_entities
                        .entry(folded.clone())
                        .or_insert_with(|| StagedEntity {
                            entity_id: existing.entity_id.clone(),
                            name: existing.name.clone(),
                            entity_type: existing.entity_type.clone(),
                            name_vector: Some(existing.name_vector.clone()),
                            source_chunk_ids: existing.source_chunk_ids.clone(),
                            is_new: false,
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
    for (name, emb) in new_names.into_iter().zip(new_embeddings) {
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
    let version_edges = entity_edges_table
        .version()
        .await
        .map_err(|e| e.to_string())?;

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

        let updated_entities: Vec<&StagedEntity> =
            resolved_entities.values().filter(|e| !e.is_new).collect();
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
            let vec_arr = Arc::new(arrow_array::FixedSizeListArray::from_iter_primitive::<
                Float32Type,
                _,
                _,
            >(
                all_entities
                    .iter()
                    .map(|e| e.name_vector.as_ref().map(|v| v.iter().copied().map(Some))),
                2048,
            ));

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

        let fresh_edges_table = database
            .entity_edges_table()
            .await
            .map_err(|e| format!("open fresh entity_edges_table failed: {e}"))?;
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

pub trait EmbeddingProvider: Send + Sync {
    fn model_id(&self) -> &str {
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

static REBUILD_COUNTER: std::sync::atomic::AtomicUsize =
    std::sync::atomic::AtomicUsize::new(0);

pub fn rebuild_invocation_count() -> usize {
    REBUILD_COUNTER.load(std::sync::atomic::Ordering::Relaxed)
}

pub fn reset_rebuild_invocation_count() {
    REBUILD_COUNTER.store(0, std::sync::atomic::Ordering::Relaxed);
}

#[cfg(test)]
static REBUILD_FAIL_NEXT: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);

#[cfg(test)]
pub fn arm_rebuild_fail_next() {
    REBUILD_FAIL_NEXT.store(true, std::sync::atomic::Ordering::SeqCst);
}

#[cfg(test)]
pub fn clear_rebuild_fail_next() {
    REBUILD_FAIL_NEXT.store(false, std::sync::atomic::Ordering::SeqCst);
}

#[cfg(test)]
static REBUILD_CHECKOUT_FAIL_NEXT: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);

#[cfg(test)]
pub fn arm_rebuild_checkout_fail_next() {
    REBUILD_CHECKOUT_FAIL_NEXT.store(true, std::sync::atomic::Ordering::SeqCst);
}

#[cfg(test)]
pub fn clear_rebuild_checkout_fail_next() {
    REBUILD_CHECKOUT_FAIL_NEXT.store(false, std::sync::atomic::Ordering::SeqCst);
}

pub fn inert_rebuild_channel() -> (watch::Sender<u64>, watch::Receiver<u64>) {
    watch::channel(0)
}

pub fn inert_rebuild_tx() -> watch::Sender<u64> {
    watch::channel(0).0
}

pub async fn rebuild_and_swap(
    database: &DatabaseManager,
    corpus_store: &crate::workflow::ports::CorpusStore,
    bm25_settings: crate::retrieval::Bm25Config,
) -> Result<Arc<crate::workflow::ports::CorpusSnapshot>, String> {
    REBUILD_COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);

    #[cfg(test)]
    {
        if REBUILD_FAIL_NEXT.swap(false, std::sync::atomic::Ordering::SeqCst) {
            tracing::error!("rebuild_and_swap injected fault triggered");
            let prior = {
                let guard = corpus_store.read().await;
                Arc::clone(&*guard)
            };
            let degraded_snapshot = Arc::new(crate::workflow::ports::CorpusSnapshot {
                bm25: Arc::clone(&prior.bm25),
                generation: prior.generation.clone(),
                nodes_version: prior.nodes_version,
                rebuild_degraded: true,
            });
            let mut write_guard = corpus_store.write().await;
            *write_guard = degraded_snapshot;
            return Err("injected rebuild failure".into());
        }
    }

    let nodes_latest = database
        .nodes_table()
        .await
        .map_err(|err| format!("failed to open nodes table: {err}"))?;

    #[cfg(test)]
    let checkout_res = if REBUILD_CHECKOUT_FAIL_NEXT.swap(false, std::sync::atomic::Ordering::SeqCst) {
        Err(lancedb::Error::Runtime {
            message: "injected checkout_latest failure".into(),
        })
    } else {
        nodes_latest.checkout_latest().await
    };
    #[cfg(not(test))]
    let checkout_res = nodes_latest.checkout_latest().await;

    if let Err(err) = checkout_res {
        tracing::error!("nodes table checkout_latest failed: {err}");
        let prior = {
            let guard = corpus_store.read().await;
            Arc::clone(&*guard)
        };
        let degraded_snapshot = Arc::new(crate::workflow::ports::CorpusSnapshot {
            bm25: Arc::clone(&prior.bm25),
            generation: prior.generation.clone(),
            nodes_version: prior.nodes_version,
            rebuild_degraded: true,
        });
        let mut write_guard = corpus_store.write().await;
        *write_guard = degraded_snapshot;
        return Err(format!("nodes table checkout_latest failed: {err}"));
    }

    let nodes_version = nodes_latest
        .version()
        .await
        .map_err(|err| format!("failed to read nodes table version: {err}"))?;

    // Build BM25 index off the write lock
    let new_bm25 = match crate::retrieval::Bm25Index::from_table(&nodes_latest, bm25_settings).await {
        Ok(idx) => idx,
        Err(err) => {
            tracing::error!("BM25 rebuild from nodes table failed: {err}");
            let prior = {
                let guard = corpus_store.read().await;
                Arc::clone(&*guard)
            };
            let degraded_snapshot = Arc::new(crate::workflow::ports::CorpusSnapshot {
                bm25: Arc::clone(&prior.bm25),
                generation: prior.generation.clone(),
                nodes_version: prior.nodes_version,
                rebuild_degraded: true,
            });
            let mut write_guard = corpus_store.write().await;
            *write_guard = degraded_snapshot;
            return Err(format!("BM25 rebuild failed: {err}"));
        }
    };

    let new_snapshot = Arc::new(crate::workflow::ports::CorpusSnapshot {
        bm25: Arc::new(new_bm25),
        generation: crate::workflow::ports::corpus_generation_from_nodes_version(nodes_version),
        nodes_version,
        rebuild_degraded: false,
    });

    // Swap under a short write lock
    {
        let mut write_guard = corpus_store.write().await;
        *write_guard = Arc::clone(&new_snapshot);
    }
    tracing::info!(
        generation = %new_snapshot.generation,
        nodes_version = new_snapshot.nodes_version,
        "BM25 index rebuilt and swapped successfully"
    );

    Ok(new_snapshot)
}

pub fn spawn_rebuild_debounce_task(
    mut rebuild_rx: watch::Receiver<u64>,
    mut shutdown_rx: watch::Receiver<bool>,
    database: DatabaseManager,
    corpus_store: crate::workflow::ports::CorpusStore,
    bm25_settings: crate::retrieval::Bm25Config,
    debounce_duration: std::time::Duration,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        loop {
            // 1. Wait for notification or shutdown
            tokio::select! {
                biased;
                changed = shutdown_rx.changed() => {
                    if changed.is_ok() && *shutdown_rx.borrow() {
                        tracing::debug!("rebuild debounce task shutting down");
                        break;
                    }
                }
                changed = rebuild_rx.changed() => {
                    if changed.is_err() {
                        tracing::debug!("rebuild watch channel closed, debounce task exiting");
                        break;
                    }
                }
            }

            // 2. Debounce quiet period: reset sleep timer whenever a new change arrives
            loop {
                let sleep_fut = tokio::time::sleep(debounce_duration);
                tokio::pin!(sleep_fut);

                tokio::select! {
                    biased;
                    changed = shutdown_rx.changed() => {
                        if changed.is_ok() && *shutdown_rx.borrow() {
                            tracing::debug!("rebuild debounce task shutting down during quiet period");
                            return;
                        }
                    }
                    _ = &mut sleep_fut => {
                        break;
                    }
                    changed = rebuild_rx.changed() => {
                        if changed.is_err() {
                            return;
                        }
                        continue;
                    }
                }
            }

            // 3. Execute rebuild and swap
            let _ = rebuild_and_swap(&database, &corpus_store, bm25_settings.clone()).await;
        }
    })
}

pub fn spawn_worker(
    receiver: mpsc::Receiver<IngestionJob>,
    statuses: Arc<DashMap<String, IngestionStatus>>,
    database: DatabaseManager,
    embedder: Arc<dyn EmbeddingProvider>,
    extraction_generator: Arc<dyn graph::extraction::ExtractionGenerator>,
    shutdown: watch::Receiver<bool>,
    rebuild_tx: watch::Sender<u64>,
) -> JoinHandle<()> {
    spawn_worker_with_boundary(
        receiver,
        statuses,
        database,
        embedder,
        extraction_generator,
        Arc::new(LanceDbReplacementMutationBoundary),
        shutdown,
        rebuild_tx,
    )
}

pub fn spawn_worker_with_boundary(
    receiver: mpsc::Receiver<IngestionJob>,
    statuses: Arc<DashMap<String, IngestionStatus>>,
    database: DatabaseManager,
    embedder: Arc<dyn EmbeddingProvider>,
    extraction_generator: Arc<dyn graph::extraction::ExtractionGenerator>,
    boundary: Arc<dyn ReplacementMutationBoundary>,
    mut shutdown: watch::Receiver<bool>,
    rebuild_tx: watch::Sender<u64>,
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
                            if summary.written_entity_edges_count < summary.prior_entity_edges_count
                            {
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
                    let _ = rebuild_tx.send_modify(|v| *v = v.wrapping_add(1));
                    tracing::info!(%job.document_id, chunk_count, "indexing completed");
                }
                Err(error) => {
                    let predicate = format!("document_id = '{}'", escape_sql_literal(&document_id));
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
