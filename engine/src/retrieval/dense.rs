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

use super::{
    Candidate, QueryFilters, QueryRequest, RetrievalError, RetrievalErrorKind, RetrievalSettings,
};

const DISTANCE_COLUMN: &str = "_distance";

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
        let batches: Vec<RecordBatch> = query
            .select(Select::columns(&[
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
                DISTANCE_COLUMN,
            ]))
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
                let candidate = Candidate {
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
                    score: dense_score(distance),
                };
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
