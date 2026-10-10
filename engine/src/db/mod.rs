use std::{collections::HashSet, sync::Arc};

use arrow_schema::{DataType, Field, Schema, SchemaRef};
use lancedb::{Connection, Table};

pub mod backfill;

const EMBEDDING_DIMENSIONS: i32 = 2048;

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
        let connection = lancedb::connect(path)
            .execute()
            .await
            .map_err(|error| format!("failed to connect to LanceDB at {path}: {error}"))?;
        let manager = Self { connection };
        manager.initialize_tables().await?;
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

    async fn initialize_tables(&self) -> Result<(), String> {
        let existing = self
            .connection
            .table_names()
            .execute()
            .await
            .map_err(|error| format!("failed to list LanceDB tables: {error}"))?
            .into_iter()
            .collect::<HashSet<_>>();

        // Every table except the staging table is created or validated first, `nodes` included, so
        // a store whose `nodes` schema drifted fails closed before the staging table is touched
        // (C4). There is no automatic upgrade of `nodes`: the backfill bin is its only migrator.
        for (name, expected) in table_schemas() {
            if name == STAGED_TABLE {
                continue;
            }
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

        let staged = if existing.contains(STAGED_TABLE) {
            let table = self
                .connection
                .open_table(STAGED_TABLE)
                .execute()
                .await
                .map_err(|error| format!("failed to open LanceDB table {STAGED_TABLE}: {error}"))?;
            upgrade_staging_schema(&table).await?;
            table
        } else {
            self.connection
                .create_empty_table(STAGED_TABLE, staged_documents_v2_schema())
                .execute()
                .await
                .map_err(|error| {
                    format!("failed to create LanceDB table {STAGED_TABLE}: {error}")
                })?
        };
        validate_schema(STAGED_TABLE, &staged, &staged_documents_v2_schema()).await
    }

    /// Delegates to `finish_get_or_create` (tested directly with synthetic errors — see
    /// its doc comment). This wrapper's own two-line composition — resolving
    /// `open_table` and forwarding the result unmodified — has no test that would catch
    /// a regression introduced here specifically (e.g. reinlining the match and
    /// dropping the propagate arm) rather than in `finish_get_or_create` itself; a test
    /// for that would need a real, non-synthetic non-`TableNotFound` error out of a live
    /// `open_table` call, which is exactly the platform-sensitive induction this split
    /// was written to avoid (see `finish_get_or_create`'s doc comment). Known, accepted
    /// residual — flagged in 06.3.1-VERIFICATION.md rather than left implicit.
    async fn get_or_create_table(&self, name: &str) -> Result<Table, String> {
        let open_result = self.connection.open_table(name).execute().await;
        Self::finish_get_or_create(&self.connection, name, open_result).await
    }

    /// The decision-and-create logic `get_or_create_table` runs once `open_table` has
    /// already resolved. Split out so tests can drive it with a synthetic
    /// `Err(lancedb::Error)` — proving the fail-closed propagation branch itself,
    /// not just the standalone `is_table_not_found` classifier — without depending on
    /// inducing a real, platform-sensitive I/O error from `open_table` (D-24, D-25).
    async fn finish_get_or_create(
        connection: &Connection,
        name: &str,
        open_result: Result<Table, lancedb::Error>,
    ) -> Result<Table, String> {
        match open_result {
            Ok(tbl) => Ok(tbl),
            Err(err) if is_table_not_found(&err) => {
                let schemas = table_schemas();
                if let Some((_, expected)) = schemas.into_iter().find(|(n, _)| *n == name) {
                    let tbl = connection
                        .create_empty_table(name, expected)
                        .execute()
                        .await
                        .map_err(|error| format!("failed to create LanceDB table {name}: {error}"))?;
                    Ok(tbl)
                } else {
                    Err(format!("unknown LanceDB table {name}"))
                }
            }
            Err(err) => Err(format!("failed to open LanceDB table {name}: {err}")),
        }
    }

    pub async fn documents_table(&self) -> Result<Table, String> {
        self.get_or_create_table("documents").await
    }

    /// Durable queue-admission staging table.
    pub async fn staged_documents_table(&self) -> Result<Table, String> {
        self.get_or_create_table("staged_documents_v2").await
    }

    pub async fn nodes_table(&self) -> Result<Table, String> {
        self.get_or_create_table("nodes").await
    }

    pub async fn edges_table(&self) -> Result<Table, String> {
        self.get_or_create_table("edges").await
    }

    pub async fn entities_table(&self) -> Result<Table, String> {
        self.get_or_create_table("entities").await
    }

    pub async fn entity_edges_table(&self) -> Result<Table, String> {
        self.get_or_create_table("entity_edges").await
    }

    /// Accessor added for 06.3.4.1-04: the store has seven LanceDB tables
    /// (`table_schemas()` below), but only six had accessors before this
    /// (RESEARCH §D). The reconcile bin's before/after version record needs
    /// all seven, including `communities`, which is otherwise never written.
    pub async fn communities_table(&self) -> Result<Table, String> {
        self.get_or_create_table("communities").await
    }
}

/// The staging table's name.
const STAGED_TABLE: &str = "staged_documents_v2";

/// Upgrades a legacy staging table to the current 10-column schema in place (D-168).
///
/// Both legacy forms are recognised by strict field equality: the 6-column table without
/// `generation` gains `generation` (value 1, as before) and the three metadata columns in one
/// version, and the 7-column table gains the three metadata columns. Any other schema is left for
/// `validate_schema` to refuse. Existing rows keep every value and read null in the new columns.
async fn upgrade_staging_schema(table: &Table) -> Result<(), String> {
    let actual = table
        .schema()
        .await
        .map_err(|error| format!("failed to read schema for {STAGED_TABLE}: {error}"))?;
    let mut expressions = Vec::new();
    if actual.fields() == legacy_staged_documents_v2_schema().fields() {
        expressions.push(("generation".to_string(), "CAST(1 AS BIGINT)".to_string()));
    } else if actual.fields() != staged_documents_v2_pre_metadata_schema().fields() {
        return Ok(());
    }
    for column in ["doc_title", "source", "published_date"] {
        expressions.push((column.to_string(), "CAST(NULL AS STRING)".to_string()));
    }
    table
        .add_columns(
            lancedb::table::NewColumnTransform::SqlExpressions(expressions),
            None,
        )
        .await
        .map_err(|error| format!("failed to upgrade {STAGED_TABLE}: {error}"))?;
    Ok(())
}

async fn validate_schema(name: &str, table: &Table, expected: &SchemaRef) -> Result<(), String> {
    let actual = table
        .schema()
        .await
        .map_err(|error| format!("failed to read LanceDB schema for {name}: {error}"))?;
    if actual.fields() != expected.fields() {
        let nodes_hint = if name == "nodes"
            && actual.fields() == backfill::legacy_nodes_schema_v19().fields()
        {
            " A nodes table without the doc_title, source and published_date columns is migrated only by the backfill_evidence_metadata bin (--migrate-only for a store that is not the eval store); the engine never upgrades it."
        } else {
            ""
        };
        return Err(format!(
            "LanceDB schema drift detected for {name}. Remediation: schema reconciliation is fail-closed by design; rename or remove the stale LanceDB store directory and regenerate tables (e.g. via seed_rag_fixture or re-ingestion).{nodes_hint} Details - expected: {:?}, found: {:?}",
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
        Field::new("doc_title", DataType::Utf8, true),
        Field::new("source", DataType::Utf8, true),
        Field::new("published_date", DataType::Utf8, true),
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

pub fn entities_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("entity_id", DataType::Utf8, false),
        Field::new("name", DataType::Utf8, false),
        Field::new("entity_type", DataType::Utf8, false),
        Field::new("name_vector", vector(), false),
        Field::new("summary", DataType::Utf8, true),
        Field::new("summary_vector", vector(), true),
        Field::new("unsummarized_refs", list(DataType::Utf8), true),
        Field::new("community_ids", list(DataType::Int32), true),
        Field::new("source_chunk_ids", list(DataType::Utf8), false),
    ]))
}

pub fn entity_edges_schema() -> SchemaRef {
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

pub fn legacy_staged_documents_v2_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("document_id", DataType::Utf8, false),
        Field::new("filename", DataType::Utf8, false),
        Field::new("raw_content", DataType::Binary, false),
        Field::new("chunk_strategy", DataType::Utf8, false),
        Field::new("chunk_size", DataType::Int32, false),
        Field::new("chunk_overlap", DataType::Int32, false),
    ]))
}

/// The staging schema before the evidence-metadata columns: the 6-column legacy form plus `generation`.
pub fn staged_documents_v2_pre_metadata_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("document_id", DataType::Utf8, false),
        Field::new("filename", DataType::Utf8, false),
        Field::new("raw_content", DataType::Binary, false),
        Field::new("chunk_strategy", DataType::Utf8, false),
        Field::new("chunk_size", DataType::Int32, false),
        Field::new("chunk_overlap", DataType::Int32, false),
        Field::new("generation", DataType::Int64, false),
    ]))
}

/// The staging schema: the pre-metadata form plus the three nullable evidence-metadata columns
/// (D-168), so a staged document recovered after a restart keeps its `doc_title`, `source` and
/// `published_date`.
pub fn staged_documents_v2_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("document_id", DataType::Utf8, false),
        Field::new("filename", DataType::Utf8, false),
        Field::new("raw_content", DataType::Binary, false),
        Field::new("chunk_strategy", DataType::Utf8, false),
        Field::new("chunk_size", DataType::Int32, false),
        Field::new("chunk_overlap", DataType::Int32, false),
        Field::new("generation", DataType::Int64, false),
        Field::new("doc_title", DataType::Utf8, true),
        Field::new("source", DataType::Utf8, true),
        Field::new("published_date", DataType::Utf8, true),
    ]))
}

pub fn staged_documents_schema() -> SchemaRef {
    staged_documents_v2_schema()
}

fn table_schemas() -> [(&'static str, SchemaRef); 7] {
    [
        ("communities", communities_schema()),
        ("documents", documents_schema()),
        ("edges", edges_schema()),
        ("entities", entities_schema()),
        ("entity_edges", entity_edges_schema()),
        ("nodes", nodes_schema()),
        ("staged_documents_v2", staged_documents_v2_schema()),
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

/// Returns true only when the LanceDB error indicates the table was not found.
///
/// Pinned to lancedb 0.31.0: `lancedb::Error::TableNotFound { .. }`.
/// Every other open failure (I/O, timeout, runtime, corrupted data) must propagate
/// to prevent silent table recreation over live data (D-24).
fn is_table_not_found(err: &lancedb::Error) -> bool {
    matches!(err, lancedb::Error::TableNotFound { .. })
}

/// Reads the given table's Lance session cache size (bytes) and approximate item count.
///
/// Moved here from `retrieval_soak` (06.3.4.1-07 Task 2) so both the soak binary and the
/// production service can log the same counters. Returns `(None, None)` if the table's
/// dataset handle or session is unavailable (e.g. a freshly-created, never-opened table) --
/// never panics, since this is a diagnostic read, not a correctness-load-bearing path.
///
/// `size_bytes()` performs a full `deep_size_of` walk over the session's caches; per its own
/// `lance` doc comment this is "not trivial to compute", so callers on a hot path should not
/// call this on every single request (see `request_process_state`'s every-50th-request cadence
/// in `service.rs`, M-LOG-OVERHEAD).
pub async fn lance_session_stats(table: &Table) -> (Option<u64>, Option<usize>) {
    let Some(wrapper) = table.dataset() else {
        return (None, None);
    };
    match wrapper.get().await {
        Ok(dataset) => {
            let session = dataset.session();
            (Some(session.size_bytes()), Some(session.approx_num_items()))
        }
        Err(_) => (None, None),
    }
}

/// Cheap sibling of [`lance_session_stats`] that reads only `approx_num_items()` (a plain field
/// access), skipping `size_bytes()`'s full `deep_size_of` walk. For hot-path callers that need
/// only the item count on every call and the byte size on a sampled cadence (06.3.4.1-07 Task 2
/// `request_process_state`, M-LOG-OVERHEAD).
pub async fn lance_session_approx_num_items(table: &Table) -> Option<usize> {
    let wrapper = table.dataset()?;
    match wrapper.get().await {
        Ok(dataset) => Some(dataset.session().approx_num_items()),
        Err(_) => None,
    }
}

#[cfg(test)]
mod tests;
