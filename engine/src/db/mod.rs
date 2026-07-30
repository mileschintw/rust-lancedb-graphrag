use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
};

use arrow_array::{BinaryArray, Int32Array, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use futures::TryStreamExt;
use lancedb::{query::ExecutableQuery, Connection, Table};

const EMBEDDING_DIMENSIONS: i32 = 2048;

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct LegacyMigrationEntry {
    pub filename: String,
    pub chunk_strategy: String,
    pub chunk_size: usize,
    pub chunk_overlap: usize,
}

#[derive(Debug, Clone, Default)]
pub struct LegacyMigrationManifest {
    pub entries: HashMap<String, LegacyMigrationEntry>,
}

#[derive(Clone)]
pub struct DatabaseManager {
    connection: Connection,
}

impl std::fmt::Debug for DatabaseManager {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("DatabaseManager").finish()
    }
}

impl DatabaseManager {
    /// Initializes LanceDB store and creates required tables.
    pub async fn initialize(path: &str) -> Result<Self, String> {
        Self::initialize_with_migration(path, None).await
    }

    /// Initializes LanceDB store and executes legacy staging migration if manifest is provided.
    pub async fn initialize_with_migration(
        path: &str,
        manifest: Option<&LegacyMigrationManifest>,
    ) -> Result<Self, String> {
        let connection = lancedb::connect(path)
            .execute()
            .await
            .map_err(|error| format!("failed to connect to LanceDB at {path}: {error}"))?;
        let manager = Self { connection };
        manager.initialize_tables(manifest).await?;
        Ok(manager)
    }

    /// Opens an existing LanceDB store and validates required schemas without mutations.
    ///
    /// # Errors
    /// Returns an error if connection fails, a required table is missing, or schema drift is detected.
    pub async fn open_and_validate(path: &str) -> Result<Self, String> {
        let connection = lancedb::connect(path)
            .execute()
            .await
            .map_err(|error| format!("failed to connect to LanceDB at {path}: {error}"))?;

        let existing = connection
            .table_names()
            .execute()
            .await
            .map_err(|error| format!("failed to list LanceDB tables: {error}"))?
            .into_iter()
            .collect::<HashSet<_>>();

        if existing.contains("staged_documents") {
            let legacy_table = connection
                .open_table("staged_documents")
                .execute()
                .await
                .map_err(|error| format!("failed to open LanceDB legacy staged_documents table: {error}"))?;
            let count = legacy_table
                .count_rows(None)
                .await
                .map_err(|error| format!("failed to count rows in legacy staged_documents: {error}"))?;
            if count > 0 {
                return Err(format!(
                    "unmigrated legacy staged documents found in staged_documents table (count: {count}). Explicit migration manifest or disposition required"
                ));
            }
        }

        for (name, expected) in table_schemas() {
            if !existing.contains(name) {
                return Err(format!("LanceDB missing required table class: {name}"));
            }
            let table = connection
                .open_table(name)
                .execute()
                .await
                .map_err(|error| format!("failed to open LanceDB table {name}: {error}"))?;
            validate_schema(name, &table, &expected).await?;
        }

        Ok(Self { connection })
    }

    async fn initialize_tables(
        &self,
        manifest: Option<&LegacyMigrationManifest>,
    ) -> Result<(), String> {
        let mut existing = self
            .connection
            .table_names()
            .execute()
            .await
            .map_err(|error| format!("failed to list LanceDB tables: {error}"))?
            .into_iter()
            .collect::<HashSet<_>>();

        if existing.contains("staged_documents") {
            let legacy_table = self
                .connection
                .open_table("staged_documents")
                .execute()
                .await
                .map_err(|error| format!("failed to open LanceDB legacy staged_documents table: {error}"))?;
            let count = legacy_table
                .count_rows(None)
                .await
                .map_err(|error| format!("failed to count rows in legacy staged_documents: {error}"))?;
            if count > 0 {
                let manifest = manifest.ok_or_else(|| {
                    format!(
                        "unmigrated legacy staged documents found in staged_documents table (count: {count}). Explicit migration manifest or disposition required"
                    )
                })?;

                let batches: Vec<RecordBatch> = legacy_table
                    .query()
                    .execute()
                    .await
                    .map_err(|error| format!("failed to query legacy staged_documents: {error}"))?
                    .try_collect()
                    .await
                    .map_err(|error| format!("failed to collect legacy staged_documents: {error}"))?;

                let mut doc_ids = Vec::new();
                let mut filenames = Vec::new();
                let mut raw_contents = Vec::new();
                let mut strategies = Vec::new();
                let mut sizes = Vec::new();
                let mut overlaps = Vec::new();

                for batch in &batches {
                    let doc_id_array = batch
                        .column_by_name("document_id")
                        .ok_or("legacy staged_documents missing document_id column")?
                        .as_any()
                        .downcast_ref::<StringArray>()
                        .ok_or("invalid document_id array type in legacy staged_documents")?;
                    let raw_array = batch
                        .column_by_name("raw_content")
                        .ok_or("legacy staged_documents missing raw_content column")?
                        .as_any()
                        .downcast_ref::<BinaryArray>()
                        .ok_or("invalid raw_content array type in legacy staged_documents")?;

                    for i in 0..batch.num_rows() {
                        let id = doc_id_array.value(i).to_string();
                        let raw = raw_array.value(i).to_vec();
                        let entry = manifest.entries.get(&id).ok_or_else(|| {
                            format!("migration manifest missing entry for legacy document {id}")
                        })?;

                        if entry.chunk_strategy != "structure-aware"
                            && entry.chunk_strategy != "fixed-size"
                        {
                            return Err(format!(
                                "invalid chunk_strategy in manifest for document {id}: {}",
                                entry.chunk_strategy
                            ));
                        }
                        if entry.chunk_size == 0 || entry.chunk_size > 1048576 {
                            return Err(format!(
                                "invalid chunk_size in manifest for document {id}: {}",
                                entry.chunk_size
                            ));
                        }
                        if entry.chunk_overlap >= entry.chunk_size {
                            return Err(format!(
                                "invalid chunk_overlap in manifest for document {id}: {}",
                                entry.chunk_overlap
                            ));
                        }

                        doc_ids.push(id);
                        filenames.push(entry.filename.clone());
                        raw_contents.push(raw);
                        strategies.push(entry.chunk_strategy.clone());
                        sizes.push(
                            i32::try_from(entry.chunk_size).map_err(|_| "chunk_size overflow")?,
                        );
                        overlaps.push(
                            i32::try_from(entry.chunk_overlap)
                                .map_err(|_| "chunk_overlap overflow")?,
                        );
                    }
                }

                let migrated_batch = RecordBatch::try_new(
                    staged_documents_v2_schema(),
                    vec![
                        Arc::new(StringArray::from(
                            doc_ids.iter().map(String::as_str).collect::<Vec<_>>(),
                        )),
                        Arc::new(StringArray::from(
                            filenames.iter().map(String::as_str).collect::<Vec<_>>(),
                        )),
                        Arc::new(BinaryArray::from_vec(
                            raw_contents.iter().map(Vec::as_slice).collect::<Vec<_>>(),
                        )),
                        Arc::new(StringArray::from(
                            strategies.iter().map(String::as_str).collect::<Vec<_>>(),
                        )),
                        Arc::new(Int32Array::from(sizes)),
                        Arc::new(Int32Array::from(overlaps)),
                    ],
                )
                .map_err(|error| format!("failed to construct migrated RecordBatch: {error}"))?;

                let v2_table = if existing.contains("staged_documents_v2") {
                    self.connection
                        .open_table("staged_documents_v2")
                        .execute()
                        .await
                        .map_err(|error| {
                            format!("failed to open LanceDB staged_documents_v2 table: {error}")
                        })?
                } else {
                    self.connection
                        .create_empty_table("staged_documents_v2", staged_documents_v2_schema())
                        .execute()
                        .await
                        .map_err(|error| {
                            format!("failed to create LanceDB staged_documents_v2 table: {error}")
                        })?
                };

                v2_table
                    .add(migrated_batch)
                    .execute()
                    .await
                    .map_err(|error| {
                        format!("failed to write migrated rows to staged_documents_v2: {error}")
                    })?;
                existing.insert("staged_documents_v2".to_string());
            }
        }

        for (name, expected) in table_schemas() {
            let table = if existing.contains(name) {
                self.connection
                    .open_table(name)
                    .execute()
                    .await
                    .map_err(|error| format!("failed to open LanceDB table {name}: {error}"))?
            } else {
                self.connection
                    .create_empty_table(name, expected.clone())
                    .execute()
                    .await
                    .map_err(|error| format!("failed to create LanceDB table {name}: {error}"))?
            };
            validate_schema(name, &table, &expected).await?;
        }
        Ok(())
    }

    pub async fn documents_table(&self) -> Result<Table, String> {
        self.connection
            .open_table("documents")
            .execute()
            .await
            .map_err(|error| format!("failed to open LanceDB documents table: {error}"))
    }

    /// Durable queue-admission staging table.
    pub async fn staged_documents_table(&self) -> Result<Table, String> {
        self.connection
            .open_table("staged_documents_v2")
            .execute()
            .await
            .map_err(|error| format!("failed to open LanceDB staged_documents_v2 table: {error}"))
    }

    pub async fn nodes_table(&self) -> Result<Table, String> {
        self.connection
            .open_table("nodes")
            .execute()
            .await
            .map_err(|error| format!("failed to open LanceDB nodes table: {error}"))
    }

    pub async fn edges_table(&self) -> Result<Table, String> {
        self.connection
            .open_table("edges")
            .execute()
            .await
            .map_err(|error| format!("failed to open LanceDB edges table: {error}"))
    }
}

async fn validate_schema(name: &str, table: &Table, expected: &SchemaRef) -> Result<(), String> {
    let actual = table
        .schema()
        .await
        .map_err(|error| format!("failed to read LanceDB schema for {name}: {error}"))?;
    if actual.fields() != expected.fields() {
        return Err(format!(
            "LanceDB schema drift detected for {name}: expected {:?}, found {:?}",
            expected.fields(),
            actual.fields()
        ));
    }
    Ok(())
}

fn vector() -> DataType {
    DataType::FixedSizeList(
        Arc::new(Field::new("item", DataType::Float32, true)),
        EMBEDDING_DIMENSIONS,
    )
}

fn list(data_type: DataType) -> DataType {
    DataType::List(Arc::new(Field::new("item", data_type, true)))
}

pub fn documents_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("document_id", DataType::Utf8, false),
        Field::new("raw_content", DataType::Binary, false),
    ]))
}

pub fn nodes_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("document_id", DataType::Utf8, false),
        Field::new("chunk_id", DataType::Utf8, false),
        Field::new("chunk_index", DataType::Int32, false),
        Field::new("char_start", DataType::Int32, false),
        Field::new("char_end", DataType::Int32, false),
        Field::new("content", DataType::Utf8, false),
        Field::new("embedding", vector(), false),
        Field::new("token_estimate", DataType::Int32, false),
        Field::new("token_estimate_scheme", DataType::Utf8, false),
        Field::new("token_estimate_version", DataType::Utf8, false),
        Field::new("title", DataType::Utf8, true),
        Field::new("section_path", DataType::Utf8, true),
        Field::new("page_start", DataType::Int32, true),
        Field::new("page_end", DataType::Int32, true),
        Field::new("content_hash", DataType::Utf8, true),
        Field::new("chunker_version", DataType::Utf8, true),
        Field::new("embedding_model", DataType::Utf8, true),
        Field::new("ingested_at", DataType::Int64, true),
        Field::new("content_type", DataType::Utf8, true),
        Field::new("community_ids", list(DataType::Int32), true),
        Field::new("summary", DataType::Utf8, true),
        Field::new("summary_vector", vector(), true),
        Field::new("unsummarized_refs", list(DataType::Utf8), true),
    ]))
}

pub fn edges_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("edge_id", DataType::Utf8, false),
        Field::new("source_node_id", DataType::Utf8, false),
        Field::new("target_node_id", DataType::Utf8, false),
        Field::new("relation_type", DataType::Utf8, false),
        Field::new("weight", DataType::Float32, false),
        Field::new("document_id", DataType::Utf8, false),
        Field::new("summary", DataType::Utf8, true),
        Field::new("summary_vector", vector(), true),
    ]))
}

pub fn communities_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("community_id", DataType::Int32, false),
        Field::new("level", DataType::Int32, false),
        Field::new("title", DataType::Utf8, false),
        Field::new("summary", DataType::Utf8, false),
        Field::new("summary_vector", vector(), false),
        Field::new("nodes", list(DataType::Utf8), false),
    ]))
}

pub fn staged_documents_v2_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("document_id", DataType::Utf8, false),
        Field::new("filename", DataType::Utf8, false),
        Field::new("raw_content", DataType::Binary, false),
        Field::new("chunk_strategy", DataType::Utf8, false),
        Field::new("chunk_size", DataType::Int32, false),
        Field::new("chunk_overlap", DataType::Int32, false),
    ]))
}

pub fn staged_documents_schema() -> SchemaRef {
    staged_documents_v2_schema()
}

fn table_schemas() -> [(&'static str, SchemaRef); 5] {
    [
        ("documents", documents_schema()),
        ("staged_documents_v2", staged_documents_v2_schema()),
        ("nodes", nodes_schema()),
        ("edges", edges_schema()),
        ("communities", communities_schema()),
    ]
}

#[tonic::async_trait]
pub trait EntityResolver: Send + Sync {
    async fn resolve(
        &self,
        entity: &str,
        known_entities: &[String],
    ) -> Result<Option<String>, String>;
}

#[derive(Debug, Default)]
pub struct ExactMatchResolver;

#[tonic::async_trait]
impl EntityResolver for ExactMatchResolver {
    async fn resolve(
        &self,
        entity: &str,
        known_entities: &[String],
    ) -> Result<Option<String>, String> {
        Ok(known_entities
            .iter()
            .find(|known| known.as_str() == entity)
            .cloned())
    }
}

#[cfg(test)]
mod tests;
