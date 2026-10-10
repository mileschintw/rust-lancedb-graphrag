//! One-off column backfill for the `nodes` table (Phase 06.3.6, D-144, C1, C2, C10).
//!
//! A `nodes` table written before the evidence-metadata columns carries 19 columns. The engine
//! never upgrades it: `DatabaseManager::initialize` and `open_and_validate` fail closed on that
//! schema, and this module is the only migrator. [`backfill_nodes_metadata`] appends `doc_title`,
//! `source` and `published_date` in a single `Table::add_columns` call whose reader yields the
//! three columns in the table's own scan order, keyed by `document_id` from a [`Sidecar`].
//! Chunks, embeddings, indexes and every old column stay as they are.
//!
//! The call is guarded on both sides. Before it, the schema must be exactly
//! [`legacy_nodes_schema_v19`], two scans of `document_id` must return the same sequence, and every
//! sidecar id must exist in `nodes`. After it, the schema must equal [`nodes_schema`] strictly; a
//! mismatch restores the prior version (which adds a version, C10). A second run fails with
//! "already exists", so a half-applied state is loud. Nothing here calls the table optimiser,
//! compaction or version cleanup, so every earlier version stays available for a restore.
//!
//! [`verify_backfill_on_copy`] runs the whole procedure on a copy of a store and reports the five
//! assertions the apply step is allowed to rely on.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::Path;
use std::sync::Arc;

use arrow_array::{
    Array, ArrayRef, Float32Array, Int32Array, Int64Array, RecordBatch, RecordBatchIterator,
    RecordBatchReader, StringArray,
};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase, Select};
use lancedb::table::NewColumnTransform;
use lancedb::Table;
use serde::{Deserialize, Serialize};

use super::nodes_schema;
use crate::service::{
    validate_doc_title, validate_document_id, validate_published_date, validate_source,
};

/// Rows per batch the reader hands to Lance. Any size works; the value only bounds memory.
const READER_BATCH_ROWS: usize = 500;

/// The sidecar schema version this module reads.
const SIDECAR_SCHEMA: u32 = 1;

/// The names of the three appended columns, in table order.
const METADATA_COLUMNS: [&str; 3] = ["doc_title", "source", "published_date"];

/// The 19-column `nodes` schema as it stood before the evidence-metadata columns were added.
///
/// A store written by an earlier engine carries exactly these fields. The backfill accepts
/// nothing else, so a table that drifted in any other way is refused rather than extended.
pub fn legacy_nodes_schema_v19() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("document_id", DataType::Utf8, false),
        Field::new("chunk_id", DataType::Utf8, false),
        Field::new("chunk_index", DataType::Int32, false),
        Field::new("char_start", DataType::Int32, false),
        Field::new("char_end", DataType::Int32, false),
        Field::new("content", DataType::Utf8, false),
        Field::new("embedding", super::vector(), false),
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
    ]))
}

/// The three metadata values of one document; each may be absent.
#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SidecarRow {
    /// The real document title.
    #[serde(default)]
    pub doc_title: Option<String>,
    /// The publication that carried the document.
    #[serde(default)]
    pub source: Option<String>,
    /// The publication date, `YYYY-MM-DD`.
    #[serde(default)]
    pub published_date: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SidecarFile {
    schema: u32,
    rows: BTreeMap<String, SidecarRow>,
}

/// The metadata of every document to backfill, keyed by `document_id`.
///
/// The file form is `{"schema": 1, "rows": {"<document_id>": {"doc_title", "source",
/// "published_date"}}}`. Every key is a UUIDv4, and every value passes the validators an ingest
/// request passes, so a backfilled value is one a fresh ingest would have accepted. An empty
/// string is stored as absent, as ingest stores it.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Sidecar {
    rows: BTreeMap<String, SidecarRow>,
}

impl Sidecar {
    /// A sidecar with no rows: every document reads null, which is what `--migrate-only` writes.
    pub fn empty() -> Self {
        Self::default()
    }

    /// Builds a sidecar from rows, validating every key and value.
    ///
    /// # Errors
    /// Returns the failure text for a key that is not a UUIDv4 or a value a fresh ingest would
    /// refuse. The text names the key and the document, never the value.
    pub fn from_rows(rows: BTreeMap<String, SidecarRow>) -> Result<Self, String> {
        let mut checked = BTreeMap::new();
        for (document_id, row) in rows {
            validate_document_id(&document_id)
                .map_err(|_| format!("sidecar key {document_id:?} is not a UUIDv4"))?;
            let row = SidecarRow {
                doc_title: non_empty(row.doc_title),
                source: non_empty(row.source),
                published_date: non_empty(row.published_date),
            };
            if let Some(value) = &row.doc_title {
                validate_doc_title(value)
                    .map_err(|error| format!("sidecar row {document_id}: {}", error.message()))?;
            }
            if let Some(value) = &row.source {
                validate_source(value)
                    .map_err(|error| format!("sidecar row {document_id}: {}", error.message()))?;
            }
            if let Some(value) = &row.published_date {
                validate_published_date(value)
                    .map_err(|error| format!("sidecar row {document_id}: {}", error.message()))?;
            }
            checked.insert(document_id, row);
        }
        Ok(Self { rows: checked })
    }

    /// Parses the sidecar file form.
    ///
    /// # Errors
    /// Returns the failure text for malformed JSON, an unknown field, a schema other than 1, or
    /// anything [`Sidecar::from_rows`] refuses.
    pub fn parse(json: &str) -> Result<Self, String> {
        let file: SidecarFile =
            serde_json::from_str(json).map_err(|error| format!("malformed sidecar: {error}"))?;
        if file.schema != SIDECAR_SCHEMA {
            return Err(format!(
                "sidecar schema {} is not supported; expected {SIDECAR_SCHEMA}",
                file.schema
            ));
        }
        Self::from_rows(file.rows)
    }

    /// Reads and parses the sidecar at `path`.
    ///
    /// # Errors
    /// Returns the failure text when the file cannot be read or parsed.
    pub fn load(path: &Path) -> Result<Self, String> {
        let text = std::fs::read_to_string(path)
            .map_err(|error| format!("failed to read sidecar {}: {error}", path.display()))?;
        Self::parse(&text)
    }

    /// The number of documents the sidecar names.
    pub fn len(&self) -> usize {
        self.rows.len()
    }

    /// Whether the sidecar names no document.
    pub fn is_empty(&self) -> bool {
        self.rows.is_empty()
    }

    /// The row of `document_id`, or `None` when the sidecar does not name it.
    pub fn get(&self, document_id: &str) -> Option<&SidecarRow> {
        self.rows.get(document_id)
    }

    /// The document ids the sidecar names, in order.
    pub fn document_ids(&self) -> impl Iterator<Item = &str> {
        self.rows.keys().map(String::as_str)
    }
}

fn non_empty(value: Option<String>) -> Option<String> {
    value.filter(|text| !text.is_empty())
}

/// What one successful [`backfill_nodes_metadata`] call did.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BackfillOutcome {
    /// The `nodes` version before the call.
    pub version_before: u64,
    /// The `nodes` version after the call; exactly one commit later.
    pub version_after: u64,
    /// The number of live rows that received values.
    pub rows: usize,
    /// The number of distinct documents in `nodes`.
    pub documents: usize,
    /// The documents in `nodes` the sidecar does not name; their rows read null.
    pub uncovered_document_ids: Vec<String>,
    /// Whether two scans of `document_id` returned the same sequence (always true on success).
    pub scan_stable: bool,
}

/// The table's schema classified against the two shapes this module knows.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NodesSchemaState {
    /// The 19-column schema before the metadata columns: ready for the backfill.
    Legacy19,
    /// The current 22-column schema: the backfill has already run.
    Current22,
    /// Any other shape.
    Other,
}

/// Classifies `schema` as the legacy 19-column form, the current 22-column form, or neither.
pub fn classify_nodes_schema(schema: &Schema) -> NodesSchemaState {
    if schema.fields() == legacy_nodes_schema_v19().fields() {
        NodesSchemaState::Legacy19
    } else if schema.fields() == nodes_schema().fields() {
        NodesSchemaState::Current22
    } else {
        NodesSchemaState::Other
    }
}

/// Refuses a schema that is not the legacy 19-column form, naming why.
fn require_legacy_schema(schema: &Schema) -> Result<(), String> {
    match classify_nodes_schema(schema) {
        NodesSchemaState::Legacy19 => Ok(()),
        NodesSchemaState::Current22 => Err(
            "column doc_title already exists in nodes: the metadata backfill was already applied, nothing was written"
                .to_owned(),
        ),
        NodesSchemaState::Other => {
            let has_any = METADATA_COLUMNS
                .iter()
                .any(|name| schema.field_with_name(name).is_ok());
            if has_any {
                Err("a metadata column already exists in nodes but the table is not the current 22-column schema; nothing was written".to_owned())
            } else {
                Err("nodes is not the legacy 19-column schema, so the backfill refuses it; nothing was written".to_owned())
            }
        }
    }
}

/// The metadata columns as the reader yields them: three nullable `Utf8` fields.
fn metadata_reader_schema() -> SchemaRef {
    Arc::new(Schema::new(
        METADATA_COLUMNS
            .iter()
            .map(|name| Field::new(*name, DataType::Utf8, true))
            .collect::<Vec<_>>(),
    ))
}

/// Builds the reader that yields the three columns for `ids`, one row per id in the given order.
fn build_reader(
    ids: &[String],
    sidecar: &Sidecar,
) -> Result<Box<dyn RecordBatchReader + Send>, String> {
    let schema = metadata_reader_schema();
    let mut batches = Vec::with_capacity(ids.len().div_ceil(READER_BATCH_ROWS));
    for chunk in ids.chunks(READER_BATCH_ROWS) {
        let rows: Vec<Option<&SidecarRow>> = chunk.iter().map(|id| sidecar.get(id)).collect();
        let titles = StringArray::from(
            rows.iter()
                .map(|row| row.and_then(|row| row.doc_title.as_deref()))
                .collect::<Vec<_>>(),
        );
        let sources = StringArray::from(
            rows.iter()
                .map(|row| row.and_then(|row| row.source.as_deref()))
                .collect::<Vec<_>>(),
        );
        let dates = StringArray::from(
            rows.iter()
                .map(|row| row.and_then(|row| row.published_date.as_deref()))
                .collect::<Vec<_>>(),
        );
        let columns: Vec<ArrayRef> = vec![Arc::new(titles), Arc::new(sources), Arc::new(dates)];
        batches.push(RecordBatch::try_new(schema.clone(), columns));
    }
    Ok(Box::new(RecordBatchIterator::new(batches, schema)))
}

async fn collect_columns(table: &Table, columns: &[&str]) -> Result<Vec<RecordBatch>, String> {
    table
        .query()
        .select(Select::columns(columns))
        .execute()
        .await
        .map_err(|error| format!("nodes scan failed: {error}"))?
        .try_collect()
        .await
        .map_err(|error| format!("nodes scan collection failed: {error}"))
}

/// `document_id` of every live row, in the table's scan order.
async fn scan_document_ids(table: &Table) -> Result<Vec<String>, String> {
    let mut ids = Vec::new();
    for batch in collect_columns(table, &["document_id"]).await? {
        let column = batch
            .column(0)
            .as_any()
            .downcast_ref::<StringArray>()
            .ok_or("nodes document_id is not a string column")?;
        for row in 0..column.len() {
            if column.is_null(row) {
                return Err("nodes holds a row with a null document_id".to_owned());
            }
            ids.push(column.value(row).to_owned());
        }
    }
    Ok(ids)
}

/// Restores `version` as a new latest version; the restore itself adds a version (C10).
async fn restore_prior_version(table: &Table, version: u64) -> Result<(), String> {
    crate::ingest::restore_version(table, version).await
}

/// Appends the three metadata columns to a legacy `nodes` table from `sidecar`.
///
/// The table handle must be at its latest version, not pinned by a checkout. On success the
/// table has exactly one new version and the strict [`nodes_schema`]; rows of a document the
/// sidecar does not name read null and are reported in the outcome.
///
/// # Errors
/// Returns the failure text, and writes nothing, when the schema is not the legacy 19-column
/// form (a table that already has the columns fails with "already exists"), the two scans of
/// `document_id` differ, or the sidecar names a document that `nodes` lacks. When the call
/// itself fails Lance commits nothing. When the post-state schema is not [`nodes_schema`] the
/// prior version is restored and the error says so.
pub async fn backfill_nodes_metadata(
    table: &Table,
    sidecar: &Sidecar,
) -> Result<BackfillOutcome, String> {
    backfill_with(table, sidecar, &nodes_schema(), None).await
}

/// [`backfill_nodes_metadata`] with the post-state schema and the reader's row ids supplied.
///
/// `reader_ids` replaces the ids the reader covers when it is `Some`; a test passes one id fewer
/// or more than the scan to prove Lance refuses a short or long reader. `expected` replaces the
/// schema the post-state is compared with; a test passes a different one to force the restore.
pub(crate) async fn backfill_with(
    table: &Table,
    sidecar: &Sidecar,
    expected: &SchemaRef,
    reader_ids: Option<Vec<String>>,
) -> Result<BackfillOutcome, String> {
    let schema_before = table
        .schema()
        .await
        .map_err(|error| format!("failed to read the nodes schema: {error}"))?;
    require_legacy_schema(&schema_before)?;
    let version_before = table
        .version()
        .await
        .map_err(|error| format!("failed to read the nodes version: {error}"))?;

    let ids = scan_document_ids(table).await?;
    if ids != scan_document_ids(table).await? {
        return Err(
            "two scans of nodes document_id returned different sequences; nothing was written"
                .to_owned(),
        );
    }
    let present: BTreeSet<&str> = ids.iter().map(String::as_str).collect();
    let absent: Vec<&str> = sidecar
        .document_ids()
        .filter(|id| !present.contains(id))
        .collect();
    if !absent.is_empty() {
        return Err(format!(
            "the sidecar names {} document id(s) absent from nodes (first: {}); nothing was written",
            absent.len(),
            absent[0]
        ));
    }
    let uncovered_document_ids: Vec<String> = present
        .iter()
        .filter(|id| sidecar.get(id).is_none())
        .map(|id| (*id).to_owned())
        .collect();

    let reader = build_reader(reader_ids.as_deref().unwrap_or(&ids), sidecar)?;
    let added = table
        .add_columns(NewColumnTransform::Reader(reader), None)
        .await
        .map_err(|error| format!("adding the metadata columns failed: {error}"))?;

    let schema_after = table
        .schema()
        .await
        .map_err(|error| format!("failed to read the nodes schema after the backfill: {error}"))?;
    let version_after = table
        .version()
        .await
        .map_err(|error| format!("failed to read the nodes version after the backfill: {error}"))?;
    if schema_after.fields() != expected.fields() || added.version != version_after {
        let restored = restore_prior_version(table, version_before).await;
        return Err(match restored {
            Ok(()) => format!(
                "the backfilled nodes table does not have the expected schema or version; restored version {version_before} as a new version"
            ),
            Err(error) => format!(
                "the backfilled nodes table does not have the expected schema or version and the restore of version {version_before} failed: {error}"
            ),
        });
    }

    Ok(BackfillOutcome {
        version_before,
        version_after,
        rows: ids.len(),
        documents: present.len(),
        uncovered_document_ids,
        scan_stable: true,
    })
}

/// Feeds the rows of one column into `hasher` so two scans compare bit for bit.
fn feed_column(hasher: &mut blake3::Hasher, array: &dyn Array) -> Result<(), String> {
    match array.data_type() {
        DataType::Utf8 => {
            let values = array
                .as_any()
                .downcast_ref::<StringArray>()
                .ok_or("a Utf8 column is not a StringArray")?;
            for row in 0..values.len() {
                if values.is_null(row) {
                    hasher.update(&[0]);
                } else {
                    hasher.update(&[1]);
                    hasher.update(values.value(row).as_bytes());
                    hasher.update(&[0xff]);
                }
            }
        }
        DataType::Int32 => {
            let values = array
                .as_any()
                .downcast_ref::<Int32Array>()
                .ok_or("an Int32 column is not an Int32Array")?;
            for row in 0..values.len() {
                if values.is_null(row) {
                    hasher.update(&[0]);
                } else {
                    hasher.update(&[1]);
                    hasher.update(&values.value(row).to_le_bytes());
                }
            }
        }
        DataType::Int64 => {
            let values = array
                .as_any()
                .downcast_ref::<Int64Array>()
                .ok_or("an Int64 column is not an Int64Array")?;
            for row in 0..values.len() {
                if values.is_null(row) {
                    hasher.update(&[0]);
                } else {
                    hasher.update(&[1]);
                    hasher.update(&values.value(row).to_le_bytes());
                }
            }
        }
        DataType::FixedSizeList(_, _) => {
            let lists = array
                .as_any()
                .downcast_ref::<arrow_array::FixedSizeListArray>()
                .ok_or("a FixedSizeList column is not a FixedSizeListArray")?;
            for row in 0..lists.len() {
                if lists.is_null(row) {
                    hasher.update(&[0]);
                    continue;
                }
                hasher.update(&[1]);
                let item = lists.value(row);
                let floats = item
                    .as_any()
                    .downcast_ref::<Float32Array>()
                    .ok_or("a vector column does not hold Float32 values")?;
                for index in 0..floats.len() {
                    hasher.update(&floats.value(index).to_le_bytes());
                }
            }
        }
        other => return Err(format!("no digest rule for column type {other:?}")),
    }
    Ok(())
}

/// The BLAKE3 digest of `column` over every live row, in the table's scan order.
pub(crate) async fn column_digest(table: &Table, column: &str) -> Result<String, String> {
    let mut hasher = blake3::Hasher::new();
    for batch in collect_columns(table, &[column]).await? {
        feed_column(&mut hasher, batch.column(0).as_ref())?;
    }
    Ok(hasher.finalize().to_hex().to_string())
}

/// The size and BLAKE3 hash of every file directly under `<table_dir>/data`, by file name.
pub(crate) fn data_file_hashes(
    table_dir: &Path,
) -> Result<BTreeMap<String, (u64, String)>, String> {
    let mut files = BTreeMap::new();
    let entries = match std::fs::read_dir(table_dir.join("data")) {
        Ok(entries) => entries,
        // A table with no fragment has no data directory yet.
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(files),
        Err(error) => {
            return Err(format!(
                "failed to list the data files of {}: {error}",
                table_dir.display()
            ))
        }
    };
    for entry in entries {
        let entry = entry.map_err(|error| format!("failed to read a data file entry: {error}"))?;
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let bytes = std::fs::read(&path)
            .map_err(|error| format!("failed to read {}: {error}", path.display()))?;
        files.insert(
            entry.file_name().to_string_lossy().into_owned(),
            (
                bytes.len() as u64,
                blake3::hash(&bytes).to_hex().to_string(),
            ),
        );
    }
    Ok(files)
}

/// The metadata columns of every live row, with `document_id`, in scan order.
async fn scan_metadata_rows(table: &Table) -> Result<Vec<(String, SidecarRow)>, String> {
    let mut rows = Vec::new();
    let columns = ["document_id", "doc_title", "source", "published_date"];
    for batch in collect_columns(table, &columns).await? {
        let text = |index: usize| -> Result<&StringArray, String> {
            batch
                .column(index)
                .as_any()
                .downcast_ref::<StringArray>()
                .ok_or_else(|| format!("nodes column {} is not a string column", columns[index]))
        };
        let (ids, titles, sources, dates) = (text(0)?, text(1)?, text(2)?, text(3)?);
        let optional = |array: &StringArray, row: usize| {
            (!array.is_null(row)).then(|| array.value(row).to_owned())
        };
        for row in 0..batch.num_rows() {
            rows.push((
                ids.value(row).to_owned(),
                SidecarRow {
                    doc_title: optional(titles, row),
                    source: optional(sources, row),
                    published_date: optional(dates, row),
                },
            ));
        }
    }
    Ok(rows)
}

/// The five assertions of a COPY verification (RESEARCH, "Lance add_columns on nodes").
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct CopyAssertions {
    /// 1: the 22-column schema holds strictly and the returned version is the table's version.
    pub schema_strict_22_columns: bool,
    /// 2: the row count is unchanged and `list_indices()` is empty before and after.
    pub rows_unchanged_and_no_indices: bool,
    /// 3: all 19 old column digests are equal, exactly one new version, old data files identical.
    pub digests_versions_and_files: bool,
    /// 4: the scan was stable, the sidecar covers every document, every value matches.
    pub scan_stable_and_sidecar_covered: bool,
    /// 5: uncovered rows are null, short and long readers changed nothing, a second run refused.
    pub uncovered_null_and_second_run_refused: bool,
}

/// What [`verify_backfill_on_copy`] measured on the copy.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct VerificationReport {
    /// The live row count before the backfill.
    pub rows_before: usize,
    /// The live row count after the backfill.
    pub rows_after: usize,
    /// The `nodes` version before anything ran.
    pub version_before: u64,
    /// The `nodes` version after the backfill.
    pub version_after: u64,
    /// The number of Lance indexes before the backfill.
    pub indices_before: usize,
    /// The number of Lance indexes after the backfill.
    pub indices_after: usize,
    /// How many of the 19 old column digests are equal before and after.
    pub column_digests_equal: usize,
    /// The old columns whose digest changed.
    pub column_digest_mismatches: Vec<String>,
    /// Whether every old data file is present after, byte for byte.
    pub old_data_files_byte_identical: bool,
    /// How many documents the sidecar names.
    pub sidecar_documents: usize,
    /// How many distinct documents `nodes` holds.
    pub nodes_documents: usize,
    /// The documents `nodes` holds that the sidecar does not name.
    pub uncovered_document_ids: Vec<String>,
    /// How many rows hold a value that differs from the sidecar (null for an uncovered document).
    pub value_mismatches: usize,
    /// Whether every row of an uncovered document reads null in all three columns.
    pub uncovered_rows_null: bool,
    /// The error a reader one row short produced.
    pub short_reader_error: String,
    /// The error a reader one row long produced.
    pub long_reader_error: String,
    /// Whether the two refused readers left the version and every data file as they were.
    pub bad_readers_left_state_unchanged: bool,
    /// The error the second run produced; it must say "already exists".
    pub second_run_error: String,
    /// The five assertions.
    pub assertions: CopyAssertions,
}

impl VerificationReport {
    /// Whether all five assertions hold.
    pub fn all_passed(&self) -> bool {
        let a = &self.assertions;
        a.schema_strict_22_columns
            && a.rows_unchanged_and_no_indices
            && a.digests_versions_and_files
            && a.scan_stable_and_sidecar_covered
            && a.uncovered_null_and_second_run_refused
    }
}

/// Everything captured about the legacy table before a change.
struct TableSnapshot {
    version: u64,
    rows: usize,
    indices: usize,
    digests: Vec<(String, String)>,
    files: BTreeMap<String, (u64, String)>,
}

async fn snapshot_table(table: &Table, table_dir: &Path) -> Result<TableSnapshot, String> {
    let schema = table
        .schema()
        .await
        .map_err(|error| format!("failed to read the nodes schema: {error}"))?;
    let mut digests = Vec::with_capacity(schema.fields().len());
    for field in schema.fields() {
        digests.push((
            field.name().clone(),
            column_digest(table, field.name()).await?,
        ));
    }
    Ok(TableSnapshot {
        version: table
            .version()
            .await
            .map_err(|error| format!("failed to read the nodes version: {error}"))?,
        rows: table
            .count_rows(None)
            .await
            .map_err(|error| format!("failed to count nodes rows: {error}"))?,
        indices: table
            .list_indices()
            .await
            .map_err(|error| format!("failed to list nodes indexes: {error}"))?
            .len(),
        digests,
        files: data_file_hashes(table_dir)?,
    })
}

/// Runs the backfill on a copy of a store and measures the five COPY assertions.
///
/// `store_path` is the directory of the copied LanceDB store; it is opened with a raw
/// `lancedb::connect`, so a 19-column `nodes` does not fail closed. The caller is responsible for
/// passing a copy: this function writes to it. The procedure: capture the legacy table (schema,
/// rows, indexes, 19 digests, data files); prove a reader one row short and one row long are
/// refused with the version and files unchanged; run the backfill; capture again and compare; read
/// every value back against the sidecar; run the backfill a second time and require "already
/// exists".
///
/// # Errors
/// Returns the failure text when the store cannot be opened, its `nodes` table is not the legacy
/// 19-column form, or any measurement cannot be taken. A failed assertion is not an error: it is
/// `false` in the report.
pub async fn verify_backfill_on_copy(
    store_path: &str,
    sidecar: &Sidecar,
) -> Result<VerificationReport, String> {
    let connection = lancedb::connect(store_path)
        .execute()
        .await
        .map_err(|error| format!("failed to connect to the copy at {store_path}: {error}"))?;
    let table = connection
        .open_table("nodes")
        .execute()
        .await
        .map_err(|error| format!("failed to open nodes in the copy: {error}"))?;
    let table_dir = Path::new(store_path).join("nodes.lance");

    let legacy_schema = table
        .schema()
        .await
        .map_err(|error| format!("failed to read the nodes schema: {error}"))?;
    require_legacy_schema(&legacy_schema)?;
    let before = snapshot_table(&table, &table_dir).await?;
    if before.rows > 0 && before.files.is_empty() {
        return Err(format!(
            "no data files found under {}; the copy cannot be verified",
            table_dir.display()
        ));
    }

    // A reader one row short and one row long must both be refused and change nothing.
    let ids = scan_document_ids(&table).await?;
    let (mut short_error, mut long_error) =
        ("skipped: no rows".to_owned(), "skipped: no rows".to_owned());
    let mut bad_readers_unchanged = true;
    if let Some(last) = ids.last() {
        let schema = nodes_schema();
        let short = backfill_with(
            &table,
            sidecar,
            &schema,
            Some(ids[..ids.len() - 1].to_vec()),
        )
        .await;
        short_error = short
            .err()
            .unwrap_or_else(|| "ACCEPTED (unexpected)".to_owned());
        let mut longer = ids.clone();
        longer.push(last.clone());
        let long = backfill_with(&table, sidecar, &schema, Some(longer)).await;
        long_error = long
            .err()
            .unwrap_or_else(|| "ACCEPTED (unexpected)".to_owned());
        let unchanged = table.version().await.ok() == Some(before.version)
            && data_file_hashes(&table_dir)? == before.files;
        bad_readers_unchanged = unchanged
            && !short_error.starts_with("ACCEPTED")
            && !long_error.starts_with("ACCEPTED");
    }

    let outcome = backfill_nodes_metadata(&table, sidecar).await?;

    let schema_after = table
        .schema()
        .await
        .map_err(|error| format!("failed to read the nodes schema after the backfill: {error}"))?;
    let after_version = table
        .version()
        .await
        .map_err(|error| format!("failed to read the nodes version after the backfill: {error}"))?;
    let rows_after = table
        .count_rows(None)
        .await
        .map_err(|error| format!("failed to count nodes rows after the backfill: {error}"))?;
    let indices_after = table
        .list_indices()
        .await
        .map_err(|error| format!("failed to list nodes indexes after the backfill: {error}"))?
        .len();
    let files_after = data_file_hashes(&table_dir)?;

    let mut digest_mismatches = Vec::new();
    for (name, digest) in &before.digests {
        if column_digest(&table, name).await? != *digest {
            digest_mismatches.push(name.clone());
        }
    }
    let old_files_identical = before
        .files
        .iter()
        .all(|(name, meta)| files_after.get(name) == Some(meta));

    let uncovered: BTreeSet<&str> = outcome
        .uncovered_document_ids
        .iter()
        .map(String::as_str)
        .collect();
    let mut value_mismatches = 0;
    let mut uncovered_rows_null = true;
    let by_document: HashMap<&str, &SidecarRow> = sidecar
        .document_ids()
        .filter_map(|id| sidecar.get(id).map(|row| (id, row)))
        .collect();
    for (document_id, row) in scan_metadata_rows(&table).await? {
        let expected = by_document.get(document_id.as_str()).copied();
        let expected_row = expected.cloned().unwrap_or_default();
        if row != expected_row {
            value_mismatches += 1;
        }
        if uncovered.contains(document_id.as_str()) && row != SidecarRow::default() {
            uncovered_rows_null = false;
        }
    }

    let second_run_error = backfill_nodes_metadata(&table, sidecar)
        .await
        .err()
        .unwrap_or_else(|| "ACCEPTED (unexpected)".to_owned());

    let assertions = CopyAssertions {
        schema_strict_22_columns: schema_after.fields() == nodes_schema().fields()
            && outcome.version_after == after_version,
        rows_unchanged_and_no_indices: before.rows == rows_after
            && before.indices == 0
            && indices_after == 0,
        digests_versions_and_files: digest_mismatches.is_empty()
            && after_version == before.version + 1
            && old_files_identical,
        scan_stable_and_sidecar_covered: outcome.scan_stable
            && outcome.uncovered_document_ids.is_empty()
            && value_mismatches == 0,
        uncovered_null_and_second_run_refused: uncovered_rows_null
            && bad_readers_unchanged
            && second_run_error.contains("already exists"),
    };
    Ok(VerificationReport {
        rows_before: before.rows,
        rows_after,
        version_before: before.version,
        version_after: after_version,
        indices_before: before.indices,
        indices_after,
        column_digests_equal: before.digests.len() - digest_mismatches.len(),
        column_digest_mismatches: digest_mismatches,
        old_data_files_byte_identical: old_files_identical,
        sidecar_documents: sidecar.len(),
        nodes_documents: outcome.documents,
        uncovered_document_ids: outcome.uncovered_document_ids,
        value_mismatches,
        uncovered_rows_null,
        short_reader_error: short_error,
        long_reader_error: long_error,
        bad_readers_left_state_unchanged: bad_readers_unchanged,
        second_run_error,
        assertions,
    })
}
