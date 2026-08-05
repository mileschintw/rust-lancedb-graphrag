//! Unicode-aware BM25 indexing over the completed LanceDB node snapshot.
//!
//! The analyzer normalizes only the derived term view. Each candidate retains
//! its original content and nullable provenance for later evidence assembly.

use std::{
    collections::{BTreeSet, HashMap, HashSet},
    fmt::{Display, Formatter},
};

use arrow_array::{Array, Int32Array, Int64Array, RecordBatch, StringArray};
use futures::{future::BoxFuture, TryStreamExt};
use lancedb::{
    query::{ExecutableQuery, QueryBase, Select},
    Table,
};
use unicode_casefold::UnicodeCaseFold;
use unicode_normalization::UnicodeNormalization;
use unicode_segmentation::UnicodeSegmentation;

use super::{Candidate, QueryRequest, RetrievalError, RetrievalSettings, Retriever};

const FIELD_COUNT: usize = 3;

/// Tunable BM25 parameters and source-field boosts.
///
/// D-46 and D-49 define the field weights and BM25 defaults.
#[derive(Debug, Clone, PartialEq)]
pub struct Bm25Config {
    pub k1: f64,
    pub b: f64,
    pub content_boost: f64,
    pub title_boost: f64,
    pub section_path_boost: f64,
}

impl Default for Bm25Config {
    fn default() -> Self {
        Self {
            k1: 1.2,
            b: 0.75,
            content_boost: 1.0,
            title_boost: 2.0,
            section_path_boost: 1.5,
        }
    }
}

impl Bm25Config {
    pub fn validate(&self) -> Result<(), RetrievalError> {
        if !self.k1.is_finite()
            || self.k1 <= 0.0
            || !self.b.is_finite()
            || !(0.0..=1.0).contains(&self.b)
            || !self.content_boost.is_finite()
            || !self.title_boost.is_finite()
            || !self.section_path_boost.is_finite()
            || self.content_boost < 0.0
            || self.title_boost < 0.0
            || self.section_path_boost < 0.0
        {
            return Err(RetrievalError::new(
                super::RetrievalErrorKind::InvalidSettings,
                "BM25 k1/b and field boosts are outside their valid ranges",
            ));
        }
        Ok(())
    }
}

/// Identifies a row that prevented the initial lexical snapshot from building.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Bm25BuildError {
    pub row: usize,
    pub field: String,
    pub reason: String,
}

impl Bm25BuildError {
    fn row(row: usize, field: impl Into<String>, reason: impl Into<String>) -> Self {
        Self {
            row,
            field: field.into(),
            reason: reason.into(),
        }
    }

    fn source(reason: impl Into<String>) -> Self {
        Self::row(0, "snapshot", reason)
    }
}

impl Display for Bm25BuildError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "BM25 snapshot row {} field {}: {}",
            self.row, self.field, self.reason
        )
    }
}

impl std::error::Error for Bm25BuildError {}

#[derive(Debug, Clone)]
struct IndexedDocument {
    candidate: Candidate,
    fields: [HashMap<String, u32>; FIELD_COUNT],
    lengths: [usize; FIELD_COUNT],
}

/// A deterministic, global-statistics BM25 snapshot of completed chunks.
#[derive(Debug, Clone)]
pub struct Bm25Index {
    config: Bm25Config,
    documents: Vec<IndexedDocument>,
    document_frequency: HashMap<String, usize>,
    average_field_lengths: [f64; FIELD_COUNT],
}

impl Bm25Index {
    pub fn from_candidates(
        candidates: Vec<Candidate>,
        config: Bm25Config,
    ) -> Result<Self, Bm25BuildError> {
        config
            .validate()
            .map_err(|error| Bm25BuildError::source(error.to_string()))?;
        let mut documents = Vec::with_capacity(candidates.len());
        for (row, candidate) in candidates.into_iter().enumerate() {
            validate_candidate(row, &candidate)?;
            let field_values = [
                candidate.content.as_str(),
                candidate.title.as_deref().unwrap_or_default(),
                candidate.section_path.as_deref().unwrap_or_default(),
            ];
            let fields = field_values.map(|value| term_counts(&analyze(value)));
            let lengths: [usize; FIELD_COUNT] = std::array::from_fn(|index| {
                fields[index].values().map(|count| *count as usize).sum()
            });
            documents.push(IndexedDocument {
                candidate,
                fields,
                lengths,
            });
        }

        let mut document_frequency = HashMap::new();
        let mut totals = [0usize; FIELD_COUNT];
        for document in &documents {
            let mut document_terms = HashSet::new();
            for (index, field) in document.fields.iter().enumerate() {
                totals[index] += document.lengths[index];
                document_terms.extend(field.keys().cloned());
            }
            for term in document_terms {
                *document_frequency.entry(term).or_insert(0) += 1;
            }
        }
        let count = documents.len().max(1) as f64;
        let average_field_lengths = totals.map(|total| (total as f64 / count).max(1.0));
        Ok(Self {
            config,
            documents,
            document_frequency,
            average_field_lengths,
        })
    }

    /// Builds a snapshot by reading the canonical completed-node columns.
    pub(crate) async fn from_table(
        table: &Table,
        config: Bm25Config,
    ) -> Result<Self, Bm25BuildError> {
        let batches: Vec<RecordBatch> = table
            .query()
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
            ]))
            .execute()
            .await
            .map_err(|error| Bm25BuildError::source(format!("LanceDB query failed: {error}")))?
            .try_collect()
            .await
            .map_err(|error| {
                Bm25BuildError::source(format!("LanceDB result collection failed: {error}"))
            })?;

        let mut candidates = Vec::new();
        for batch in &batches {
            let document_ids = required_string_column(batch, "document_id")?;
            let chunk_ids = required_string_column(batch, "chunk_id")?;
            let chunk_indexes = int32_column(batch, "chunk_index")?;
            let char_starts = int32_column(batch, "char_start")?;
            let char_ends = int32_column(batch, "char_end")?;
            let contents = required_string_column(batch, "content")?;
            let titles = optional_string_column(batch, "title")?;
            let section_paths = optional_string_column(batch, "section_path")?;
            let embedding_models = optional_string_column(batch, "embedding_model")?;
            let ingested_at = optional_i64_column(batch, "ingested_at")?;
            let content_types = optional_string_column(batch, "content_type")?;

            for row in 0..batch.num_rows() {
                candidates.push(Candidate {
                    document_id: required_value(document_ids, row, "document_id")?,
                    chunk_id: required_value(chunk_ids, row, "chunk_id")?,
                    chunk_index: required_value_i32(chunk_indexes, row, "chunk_index")?,
                    char_start: required_value_i32(char_starts, row, "char_start")?,
                    char_end: required_value_i32(char_ends, row, "char_end")?,
                    content: required_value(contents, row, "content")?,
                    title: optional_value(titles, row),
                    section_path: optional_value(section_paths, row),
                    content_type: optional_value(content_types, row),
                    embedding_model: optional_value(embedding_models, row),
                    ingested_at: optional_value_i64(ingested_at, row),
                    score: 0.0,
                });
            }
        }
        Self::from_candidates(candidates, config)
    }

    pub fn query(
        &self,
        request: &QueryRequest,
        settings: &RetrievalSettings,
    ) -> Result<Vec<Candidate>, RetrievalError> {
        settings.validate()?;
        let terms = analyze(&request.query).into_iter().collect::<BTreeSet<_>>();
        if terms.is_empty() {
            return Ok(Vec::new());
        }

        let mut results = Vec::with_capacity(self.documents.len());
        for document in &self.documents {
            if !request.filters.matches(&document.candidate) {
                continue;
            }
            let score = self.score(document, &terms);
            if score > 0.0 {
                let mut candidate = document.candidate.clone();
                candidate.score = score;
                results.push(candidate);
            }
        }
        results.sort_by(|left, right| {
            right
                .score
                .total_cmp(&left.score)
                .then_with(|| left.sort_key().cmp(&right.sort_key()))
        });
        results.truncate(settings.candidate_limit);
        Ok(results)
    }

    fn score(&self, document: &IndexedDocument, terms: &BTreeSet<String>) -> f64 {
        let document_count = self.documents.len() as f64;
        terms.iter().fold(0.0, |score, term| {
            let Some(&frequency) = self.document_frequency.get(term) else {
                return score;
            };
            let idf =
                ((document_count - frequency as f64 + 0.5) / (frequency as f64 + 0.5)).ln_1p();
            let field_boosts = [
                self.config.content_boost,
                self.config.title_boost,
                self.config.section_path_boost,
            ];
            score
                + document
                    .fields
                    .iter()
                    .zip(document.lengths)
                    .zip(self.average_field_lengths)
                    .zip(field_boosts)
                    .map(|(((field, length), average), boost)| {
                        let term_frequency = field.get(term).copied().unwrap_or(0) as f64;
                        if term_frequency == 0.0 || boost == 0.0 {
                            return 0.0;
                        }
                        let normalization = self.config.k1
                            * (1.0 - self.config.b
                                + self.config.b * (length as f64 / average.max(1.0)));
                        boost * idf * (term_frequency * (self.config.k1 + 1.0))
                            / (term_frequency + normalization)
                    })
                    .sum::<f64>()
        })
    }

    pub fn len(&self) -> usize {
        self.documents.len()
    }

    pub fn is_empty(&self) -> bool {
        self.documents.is_empty()
    }
}

impl Retriever for Bm25Index {
    fn retrieve<'a>(
        &'a self,
        request: &'a QueryRequest,
        settings: &'a RetrievalSettings,
    ) -> BoxFuture<'a, Result<Vec<Candidate>, RetrievalError>> {
        Box::pin(async move { self.query(request, settings) })
    }
}

/// Applies NFKC, full Unicode case folding, UAX#29 word boundaries, and
/// technical identifier subtokens without stemming or stop-word removal.
///
/// D-44, D-45, and D-48 require this same analyzer for index and query text.
pub fn analyze(value: &str) -> Vec<String> {
    let normalized = value.nfkc().collect::<String>();
    let mut tokens = Vec::new();
    for word in normalized.unicode_words() {
        let whole = fold(word);
        if !whole.is_empty() {
            tokens.push(whole);
        }
        for part in identifier_parts(word) {
            let part = fold(&part);
            if !part.is_empty() && tokens.last() != Some(&part) {
                tokens.push(part);
            }
        }
    }
    tokens
}

fn fold(value: &str) -> String {
    value.case_fold().collect()
}

fn identifier_parts(value: &str) -> Vec<String> {
    let chars: Vec<char> = value.chars().collect();
    let mut parts = Vec::new();
    let mut start = 0;
    for index in 0..chars.len() {
        let separator = matches!(chars[index], '_' | '-');
        let next_is_lower = chars.get(index + 1).is_some_and(|next| next.is_lowercase());
        let camel_boundary = index > start
            && ((chars[index - 1].is_lowercase() && chars[index].is_uppercase())
                || (chars[index - 1].is_uppercase()
                    && chars[index].is_uppercase()
                    && next_is_lower));
        if camel_boundary {
            let part: String = chars[start..index].iter().collect();
            if !part.is_empty() {
                parts.push(part);
            }
            start = index;
        }
        if separator {
            let part: String = chars[start..index].iter().collect();
            if !part.is_empty() {
                parts.push(part);
            }
            start = index + 1;
        }
    }
    if start < chars.len() {
        parts.push(chars[start..].iter().collect());
    }
    parts
}

fn term_counts(tokens: &[String]) -> HashMap<String, u32> {
    let mut counts = HashMap::with_capacity(tokens.len());
    for token in tokens {
        *counts.entry(token.clone()).or_insert(0) += 1;
    }
    counts
}

fn validate_candidate(row: usize, candidate: &Candidate) -> Result<(), Bm25BuildError> {
    for (field, value) in [
        ("document_id", candidate.document_id.as_str()),
        ("chunk_id", candidate.chunk_id.as_str()),
        ("content", candidate.content.as_str()),
    ] {
        if value.trim().is_empty() {
            return Err(Bm25BuildError::row(
                row,
                field,
                format!(
                    "document_id={} chunk_id={}: required value must not be empty or whitespace-only",
                    candidate.document_id, candidate.chunk_id
                ),
            ));
        }
    }
    Ok(())
}

fn required_string_column<'a>(
    batch: &'a RecordBatch,
    name: &str,
) -> Result<&'a StringArray, Bm25BuildError> {
    batch
        .column_by_name(name)
        .ok_or_else(|| Bm25BuildError::source(format!("LanceDB query did not return {name}")))?
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| {
            Bm25BuildError::source(format!("LanceDB column {name} has an unexpected type"))
        })
}

fn optional_string_column<'a>(
    batch: &'a RecordBatch,
    name: &str,
) -> Result<&'a StringArray, Bm25BuildError> {
    required_string_column(batch, name)
}

fn int32_column<'a>(batch: &'a RecordBatch, name: &str) -> Result<&'a Int32Array, Bm25BuildError> {
    batch
        .column_by_name(name)
        .ok_or_else(|| Bm25BuildError::source(format!("LanceDB query did not return {name}")))?
        .as_any()
        .downcast_ref::<Int32Array>()
        .ok_or_else(|| {
            Bm25BuildError::source(format!("LanceDB column {name} has an unexpected type"))
        })
}

fn optional_i64_column<'a>(
    batch: &'a RecordBatch,
    name: &str,
) -> Result<&'a Int64Array, Bm25BuildError> {
    batch
        .column_by_name(name)
        .ok_or_else(|| Bm25BuildError::source(format!("LanceDB query did not return {name}")))?
        .as_any()
        .downcast_ref::<Int64Array>()
        .ok_or_else(|| {
            Bm25BuildError::source(format!("LanceDB column {name} has an unexpected type"))
        })
}

fn required_value(values: &StringArray, row: usize, field: &str) -> Result<String, Bm25BuildError> {
    if values.is_null(row) {
        return Err(Bm25BuildError::row(row, field, "required value is null"));
    }
    Ok(values.value(row).to_owned())
}

fn required_value_i32(values: &Int32Array, row: usize, field: &str) -> Result<i32, Bm25BuildError> {
    if values.is_null(row) {
        return Err(Bm25BuildError::row(row, field, "required value is null"));
    }
    Ok(values.value(row))
}

fn optional_value(values: &StringArray, row: usize) -> Option<String> {
    (!values.is_null(row)).then(|| values.value(row).to_owned())
}

fn optional_value_i64(values: &Int64Array, row: usize) -> Option<i64> {
    (!values.is_null(row)).then(|| values.value(row))
}
