//! LanceDB-backed dense candidate selection.
//!
//! The caller supplies the already-computed embedding, while this module owns
//! the typed metadata predicate, bounded nearest-neighbor query, and canonical
//! candidate extraction. The normalized `QueryRequest` is revalidated here so
//! this path cannot interpolate unchecked caller values into LanceDB SQL.

use arrow_array::{
    Array, Float32Array, Float64Array, Int32Array, Int64Array, RecordBatch, StringArray,
};
use futures::TryStreamExt;
use lancedb::{
    query::{ExecutableQuery, QueryBase, Select},
    Table,
};
use std::collections::HashMap;
use uuid::Uuid;

use super::{
    Candidate, QueryFilters, QueryRequest, RetrievalError, RetrievalErrorKind, RetrievalSettings,
};

const DISTANCE_COLUMN: &str = "_distance";

/// The `nodes` columns a [`Candidate`] is built from.
const CANDIDATE_COLUMNS: [&str; 11] = [
    "document_id",
    "chunk_id",
    "chunk_index",
    "char_start",
    "char_end",
    "content",
    "title",
    "section_path",
    "embedding_model",
    "ingested_at",
    "content_type",
];

/// The score of a row read by chunk ID. Such a read ranks nothing, so the score is `0.0`; the
/// caller's order is the only ranking, and fusion uses that rank, never this score.
const FETCH_BY_ID_SCORE: f64 = 0.0;

/// Reads canonical completed-node rows through LanceDB nearest-vector search.
#[derive(Clone)]
pub struct DenseRetriever {
    table: Table,
}

impl std::fmt::Debug for DenseRetriever {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("DenseRetriever").finish_non_exhaustive()
    }
}

impl DenseRetriever {
    /// Creates a dense retriever over the canonical `nodes` table.
    pub fn new(table: Table) -> Self {
        Self { table }
    }

    /// Returns bounded nearest-neighbor candidates after applying typed filters.
    pub async fn query(
        &self,
        embedding: &[f32],
        request: &QueryRequest,
        settings: &RetrievalSettings,
    ) -> Result<Vec<Candidate>, RetrievalError> {
        settings.validate()?;
        if embedding.is_empty() || embedding.iter().any(|value| !value.is_finite()) {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidSettings,
                "dense query embedding must be non-empty and finite",
            ));
        }
        let request = request.validate(settings)?;
        let mut query = self
            .table
            .query()
            .nearest_to(embedding.to_vec())
            .map_err(|error| {
                RetrievalError::new(
                    RetrievalErrorKind::Snapshot,
                    format!("failed to prepare dense query: {error}"),
                )
            })?;
        query = query.column("embedding");
        if let Some(predicate) = filter_predicate(&request.filters) {
            query = query.only_if(predicate);
        }
        let mut columns = CANDIDATE_COLUMNS.to_vec();
        columns.push(DISTANCE_COLUMN);
        let batches: Vec<RecordBatch> = query
            .select(Select::columns(&columns))
            .limit(settings.candidate_limit)
            .execute()
            .await
            .map_err(|error| {
                RetrievalError::new(
                    RetrievalErrorKind::Snapshot,
                    format!("dense LanceDB query failed: {error}"),
                )
            })?
            .try_collect()
            .await
            .map_err(|error| {
                RetrievalError::new(
                    RetrievalErrorKind::Snapshot,
                    format!("dense LanceDB result collection failed: {error}"),
                )
            })?;

        let mut results = Vec::new();
        for batch in &batches {
            for row in 0..batch.num_rows() {
                let distance = distance_at(batch, row)?;
                let candidate = candidate_at(batch, row, dense_score(distance))?;
                results.push((distance, candidate));
            }
        }
        results.sort_by(|(left_distance, left), (right_distance, right)| {
            left_distance
                .total_cmp(right_distance)
                .then_with(|| left.sort_key().cmp(&right.sort_key()))
        });
        results.truncate(settings.candidate_limit);
        Ok(results
            .into_iter()
            .map(|(_, candidate)| candidate)
            .collect())
    }
}

impl DenseRetriever {
    /// Reads the rows of the given chunk IDs, in the order given, skipping IDs the table lacks.
    ///
    /// Every ID must be `<uuidv4>:<non-negative integer>` (see [`is_valid_chunk_id`]); a bad ID
    /// fails the whole call before any predicate is built. The rows carry no retrieval score.
    ///
    /// # Errors
    /// Returns an error for a malformed ID or a failed LanceDB read.
    pub async fn fetch_by_chunk_ids(
        &self,
        chunk_ids: &[String],
    ) -> Result<Vec<Candidate>, RetrievalError> {
        if chunk_ids.iter().any(|id| !is_valid_chunk_id(id)) {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidDocumentId,
                "a chunk id is not <uuidv4>:<chunk index>",
            ));
        }
        if chunk_ids.is_empty() {
            return Ok(Vec::new());
        }
        let values = chunk_ids
            .iter()
            .map(|id| format!("'{}'", escape_sql_literal(id)))
            .collect::<Vec<_>>();
        let batches: Vec<RecordBatch> = self
            .table
            .query()
            .only_if(format!("chunk_id IN ({})", values.join(", ")))
            .select(Select::columns(&CANDIDATE_COLUMNS))
            .limit(chunk_ids.len())
            .execute()
            .await
            .map_err(|error| {
                RetrievalError::new(
                    RetrievalErrorKind::Snapshot,
                    format!("chunk LanceDB query failed: {error}"),
                )
            })?
            .try_collect()
            .await
            .map_err(|error| {
                RetrievalError::new(
                    RetrievalErrorKind::Snapshot,
                    format!("chunk LanceDB result collection failed: {error}"),
                )
            })?;

        let mut rows: HashMap<String, Candidate> = HashMap::with_capacity(chunk_ids.len());
        for batch in &batches {
            for row in 0..batch.num_rows() {
                let candidate = candidate_at(batch, row, FETCH_BY_ID_SCORE)?;
                rows.entry(candidate.chunk_id.clone()).or_insert(candidate);
            }
        }
        // The caller's order, which is the graph's rank order. An ID the table lacks has no row,
        // and a repeated ID is returned once.
        Ok(chunk_ids.iter().filter_map(|id| rows.remove(id)).collect())
    }
}

/// Whether `value` is a chunk ID: `<uuidv4>:<chunk index>`.
///
/// The document part must be a UUIDv4 in its canonical lower-case hyphenated form (the form the
/// ingest path writes), and the index a decimal `i32` with no sign, no leading zero and no
/// whitespace. `Uuid::parse_str` alone also accepts upper-case, simple, braced and `urn:uuid:`
/// spellings, none of which can name a stored chunk, so the canonical rendering must equal the
/// input. A value that passes carries no character that is special in a SQL string literal.
pub fn is_valid_chunk_id(value: &str) -> bool {
    let Some((document_id, index)) = value.rsplit_once(':') else {
        return false;
    };
    let Ok(uuid) = Uuid::parse_str(document_id) else {
        return false;
    };
    uuid.get_version_num() == 4
        && uuid.get_variant() == uuid::Variant::RFC4122
        && uuid.hyphenated().to_string() == document_id
        && !index.is_empty()
        && index.bytes().all(|byte| byte.is_ascii_digit())
        && (index == "0" || !index.starts_with('0'))
        && index.parse::<i32>().is_ok()
}

/// Builds the candidate at `row` of a batch that carries every [`CANDIDATE_COLUMNS`] column.
fn candidate_at(batch: &RecordBatch, row: usize, score: f64) -> Result<Candidate, RetrievalError> {
    Ok(Candidate {
        document_id: required_string(batch, "document_id", row)?,
        chunk_id: required_string(batch, "chunk_id", row)?,
        chunk_index: required_i32(batch, "chunk_index", row)?,
        char_start: required_i32(batch, "char_start", row)?,
        char_end: required_i32(batch, "char_end", row)?,
        content: required_string(batch, "content", row)?,
        title: optional_string(batch, "title", row)?,
        section_path: optional_string(batch, "section_path", row)?,
        content_type: optional_string(batch, "content_type", row)?,
        embedding_model: optional_string(batch, "embedding_model", row)?,
        ingested_at: optional_i64(batch, "ingested_at", row)?,
        score,
    })
}

fn filter_predicate(filters: &QueryFilters) -> Option<String> {
    let mut clauses = Vec::new();
    if !filters.document_ids.is_empty() {
        let values = filters
            .document_ids
            .iter()
            .map(|value| format!("document_id = '{}'", escape_sql_literal(value)))
            .collect::<Vec<_>>();
        clauses.push(format!("({})", values.join(" OR ")));
    }
    if !filters.content_types.is_empty() {
        let values = filters
            .content_types
            .iter()
            .map(|value| format!("content_type = '{}'", escape_sql_literal(value)))
            .collect::<Vec<_>>();
        clauses.push(format!("({})", values.join(" OR ")));
    }
    (!clauses.is_empty()).then(|| clauses.join(" AND "))
}

fn escape_sql_literal(value: &str) -> String {
    value.replace('\'', "''")
}

pub fn dense_score(distance: f64) -> f64 {
    1.0 / (1.0 + distance.max(0.0))
}

fn column<'a>(batch: &'a RecordBatch, name: &str) -> Result<&'a dyn Array, RetrievalError> {
    batch
        .column_by_name(name)
        .map(|column| column.as_ref())
        .ok_or_else(|| {
            RetrievalError::new(
                RetrievalErrorKind::Snapshot,
                format!("dense LanceDB result did not return {name}"),
            )
        })
}

fn required_string(batch: &RecordBatch, name: &str, row: usize) -> Result<String, RetrievalError> {
    let values = column(batch, name)?
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| unexpected_type(name))?;
    if values.is_null(row) || values.value(row).trim().is_empty() {
        return Err(RetrievalError::new(
            RetrievalErrorKind::Snapshot,
            format!("dense LanceDB required field {name} is null or empty at row {row}"),
        ));
    }
    Ok(values.value(row).to_owned())
}

fn optional_string(
    batch: &RecordBatch,
    name: &str,
    row: usize,
) -> Result<Option<String>, RetrievalError> {
    let values = column(batch, name)?
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| unexpected_type(name))?;
    Ok((!values.is_null(row)).then(|| values.value(row).to_owned()))
}

fn required_i32(batch: &RecordBatch, name: &str, row: usize) -> Result<i32, RetrievalError> {
    let values = column(batch, name)?
        .as_any()
        .downcast_ref::<Int32Array>()
        .ok_or_else(|| unexpected_type(name))?;
    if values.is_null(row) {
        return Err(RetrievalError::new(
            RetrievalErrorKind::Snapshot,
            format!("dense LanceDB required field {name} is null at row {row}"),
        ));
    }
    Ok(values.value(row))
}

fn optional_i64(
    batch: &RecordBatch,
    name: &str,
    row: usize,
) -> Result<Option<i64>, RetrievalError> {
    let values = column(batch, name)?
        .as_any()
        .downcast_ref::<Int64Array>()
        .ok_or_else(|| unexpected_type(name))?;
    Ok((!values.is_null(row)).then(|| values.value(row)))
}

fn distance_at(batch: &RecordBatch, row: usize) -> Result<f64, RetrievalError> {
    let values = column(batch, DISTANCE_COLUMN)?;
    let distance = if let Some(values) = values.as_any().downcast_ref::<Float32Array>() {
        if values.is_null(row) {
            return Err(missing_distance(row));
        }
        values.value(row) as f64
    } else if let Some(values) = values.as_any().downcast_ref::<Float64Array>() {
        if values.is_null(row) {
            return Err(missing_distance(row));
        }
        values.value(row)
    } else {
        return Err(unexpected_type(DISTANCE_COLUMN));
    };
    if !distance.is_finite() {
        return Err(RetrievalError::new(
            RetrievalErrorKind::Snapshot,
            format!("dense LanceDB distance is not finite at row {row}"),
        ));
    }
    Ok(distance)
}

fn missing_distance(row: usize) -> RetrievalError {
    RetrievalError::new(
        RetrievalErrorKind::Snapshot,
        format!("dense LanceDB distance is null at row {row}"),
    )
}

fn unexpected_type(name: &str) -> RetrievalError {
    RetrievalError::new(
        RetrievalErrorKind::Snapshot,
        format!("dense LanceDB column {name} has an unexpected type"),
    )
}
