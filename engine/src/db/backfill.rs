//! One-off column backfill for the `nodes` table (Phase 06.3.6, D-144).

use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;

use arrow_schema::{DataType, Field, Schema, SchemaRef};
use lancedb::Table;
use serde::{Deserialize, Serialize};

use super::nodes_schema;

/// The 19-column `nodes` schema as it stood before the evidence-metadata columns were added.
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
pub struct SidecarRow {
    /// The real document title.
    pub doc_title: Option<String>,
    /// The publication that carried the document.
    pub source: Option<String>,
    /// The publication date, `YYYY-MM-DD`.
    pub published_date: Option<String>,
}

/// The metadata of every document to backfill, keyed by `document_id` (stub).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Sidecar {
    rows: BTreeMap<String, SidecarRow>,
}

impl Sidecar {
    /// A sidecar with no rows.
    pub fn empty() -> Self {
        Self::default()
    }

    /// Builds a sidecar from rows without validating them (stub).
    ///
    /// # Errors
    /// Never fails in the stub.
    pub fn from_rows(rows: BTreeMap<String, SidecarRow>) -> Result<Self, String> {
        Ok(Self { rows })
    }

    /// Parses nothing (stub).
    ///
    /// # Errors
    /// Never fails in the stub.
    pub fn parse(_json: &str) -> Result<Self, String> {
        Ok(Self::default())
    }

    /// Reads nothing (stub).
    ///
    /// # Errors
    /// Never fails in the stub.
    pub fn load(_path: &Path) -> Result<Self, String> {
        Ok(Self::default())
    }

    /// The number of documents the sidecar names.
    pub fn len(&self) -> usize {
        self.rows.len()
    }

    /// Whether the sidecar names no document.
    pub fn is_empty(&self) -> bool {
        self.rows.is_empty()
    }

    /// The row of `document_id`.
    pub fn get(&self, document_id: &str) -> Option<&SidecarRow> {
        self.rows.get(document_id)
    }

    /// The document ids the sidecar names, in order.
    pub fn document_ids(&self) -> impl Iterator<Item = &str> {
        self.rows.keys().map(String::as_str)
    }
}

/// What one successful backfill call did.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct BackfillOutcome {
    /// The `nodes` version before the call.
    pub version_before: u64,
    /// The `nodes` version after the call.
    pub version_after: u64,
    /// The number of live rows that received values.
    pub rows: usize,
    /// The number of distinct documents in `nodes`.
    pub documents: usize,
    /// The documents in `nodes` the sidecar does not name.
    pub uncovered_document_ids: Vec<String>,
    /// Whether two scans of `document_id` returned the same sequence.
    pub scan_stable: bool,
}

/// The table's schema classified against the two shapes this module knows.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NodesSchemaState {
    /// The 19-column schema before the metadata columns.
    Legacy19,
    /// The current 22-column schema.
    Current22,
    /// Any other shape.
    Other,
}

/// Classifies `schema` (stub: always `Other`).
pub fn classify_nodes_schema(_schema: &Schema) -> NodesSchemaState {
    NodesSchemaState::Other
}

fn untouched(version: u64) -> BackfillOutcome {
    BackfillOutcome {
        version_before: version,
        version_after: version,
        rows: 0,
        documents: 0,
        uncovered_document_ids: Vec::new(),
        scan_stable: false,
    }
}

/// Changes nothing (stub).
///
/// # Errors
/// Fails only when the version cannot be read.
pub async fn backfill_nodes_metadata(
    table: &Table,
    _sidecar: &Sidecar,
) -> Result<BackfillOutcome, String> {
    let version = table.version().await.map_err(|error| error.to_string())?;
    Ok(untouched(version))
}

/// Changes nothing (stub).
pub(crate) async fn backfill_with(
    table: &Table,
    _sidecar: &Sidecar,
    _expected: &SchemaRef,
    _reader_ids: Option<Vec<String>>,
) -> Result<BackfillOutcome, String> {
    let version = table.version().await.map_err(|error| error.to_string())?;
    Ok(untouched(version))
}

/// Digests nothing (stub).
pub(crate) async fn column_digest(_table: &Table, _column: &str) -> Result<String, String> {
    Ok(String::new())
}

/// Lists nothing (stub).
pub(crate) fn data_file_hashes(
    _table_dir: &Path,
) -> Result<BTreeMap<String, (u64, String)>, String> {
    Ok(BTreeMap::new())
}

/// The five assertions of a COPY verification.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct CopyAssertions {
    /// 1: the 22-column schema holds strictly.
    pub schema_strict_22_columns: bool,
    /// 2: rows unchanged and no indexes.
    pub rows_unchanged_and_no_indices: bool,
    /// 3: digests, versions and files.
    pub digests_versions_and_files: bool,
    /// 4: scan stability and coverage.
    pub scan_stable_and_sidecar_covered: bool,
    /// 5: nulls, refused readers and the second run.
    pub uncovered_null_and_second_run_refused: bool,
}

/// What the verification measured.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct VerificationReport {
    /// Rows before.
    pub rows_before: usize,
    /// Rows after.
    pub rows_after: usize,
    /// Version before.
    pub version_before: u64,
    /// Version after.
    pub version_after: u64,
    /// Indexes before.
    pub indices_before: usize,
    /// Indexes after.
    pub indices_after: usize,
    /// Equal digests.
    pub column_digests_equal: usize,
    /// Changed digests.
    pub column_digest_mismatches: Vec<String>,
    /// Old files identical.
    pub old_data_files_byte_identical: bool,
    /// Sidecar documents.
    pub sidecar_documents: usize,
    /// Nodes documents.
    pub nodes_documents: usize,
    /// Uncovered documents.
    pub uncovered_document_ids: Vec<String>,
    /// Mismatching rows.
    pub value_mismatches: usize,
    /// Uncovered rows null.
    pub uncovered_rows_null: bool,
    /// Short reader error.
    pub short_reader_error: String,
    /// Long reader error.
    pub long_reader_error: String,
    /// Refused readers changed nothing.
    pub bad_readers_left_state_unchanged: bool,
    /// Second run error.
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

/// Verifies nothing (stub): every assertion is false.
///
/// # Errors
/// Never fails in the stub.
pub async fn verify_backfill_on_copy(
    _store_path: &str,
    sidecar: &Sidecar,
) -> Result<VerificationReport, String> {
    let _ = nodes_schema();
    Ok(VerificationReport {
        rows_before: 0,
        rows_after: 0,
        version_before: 0,
        version_after: 0,
        indices_before: 0,
        indices_after: 0,
        column_digests_equal: 0,
        column_digest_mismatches: Vec::new(),
        old_data_files_byte_identical: false,
        sidecar_documents: sidecar.len(),
        nodes_documents: 0,
        uncovered_document_ids: Vec::new(),
        value_mismatches: 0,
        uncovered_rows_null: false,
        short_reader_error: String::new(),
        long_reader_error: String::new(),
        bad_readers_left_state_unchanged: false,
        second_run_error: String::new(),
        assertions: CopyAssertions {
            schema_strict_22_columns: false,
            rows_unchanged_and_no_indices: false,
            digests_versions_and_files: false,
            scan_stable_and_sidecar_covered: false,
            uncovered_null_and_second_run_refused: false,
        },
    })
}
