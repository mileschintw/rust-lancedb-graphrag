//! Typed query validation and deterministic retrieval contracts.
//!
//! This module owns the request and candidate types shared by the dense and
//! lexical paths. Query filters are normalized once and are safe to apply to
//! both paths before their candidate limits are enforced.

use std::{
    collections::HashSet,
    fmt::{Display, Formatter},
};

use futures::future::BoxFuture;
use serde::Serialize;
use uuid::Uuid;

pub mod bm25;
pub mod dense;
pub mod fusion;

pub use bm25::{Bm25Config, Bm25Index};
pub use dense::DenseRetriever;
pub use fusion::{fuse_candidates, fuse_cross_variant_candidates, FusedCandidate, VariantProvenance};

pub const DEFAULT_CANDIDATE_LIMIT: usize = 32;
pub const DEFAULT_FINAL_LIMIT: usize = 8;
pub const DEFAULT_QUERY_MAX_BYTES: usize = 8 * 1024;
pub const DEFAULT_MAX_DOCUMENT_IDS: usize = 100;
pub const DEFAULT_MAX_CONTENT_TYPES: usize = 16;

pub const MAX_SERVICE_CANDIDATE_LIMIT: usize = 500;
pub const MAX_SERVICE_FINAL_LIMIT: usize = 100;
pub const MAX_SERVICE_QUERY_MAX_BYTES: usize = 8192;
pub const MAX_SERVICE_FILTER_KEYS: usize = 32;
pub const MAX_SERVICE_FILTER_VALUES_PER_KEY: usize = 100;
pub const MAX_SERVICE_RRF_WEIGHT: f64 = 16.0;
pub const MAX_SERVICE_RRF_K: f64 = 1000000.0;

const SUPPORTED_CONTENT_TYPES: &[&str] = &["application/json", "text/markdown", "text/plain"];

/// Identifies a caller contract error or an unavailable retrieval snapshot.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RetrievalErrorKind {
    EmptyQuery,
    QueryTooLong,
    InvalidDocumentId,
    UnsupportedContentType,
    EmptyFilterValue,
    FilterLimitExceeded,
    InvalidSettings,
    NonFiniteScore,
    Snapshot,
}

/// A typed retrieval error with a stable category and human-readable context.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RetrievalError {
    pub kind: RetrievalErrorKind,
    message: String,
}

impl RetrievalError {
    pub fn new(kind: RetrievalErrorKind, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
        }
    }

    pub fn message(&self) -> &str {
        &self.message
    }
}

impl Display for RetrievalError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RetrievalError {}

/// Optional metadata constraints applied identically to dense and BM25 rows.
///
/// D-06 through D-10 define the global-corpus default and typed filter semantics.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct QueryFilters {
    pub document_ids: Vec<String>,
    pub content_types: Vec<String>,
}

impl QueryFilters {
    pub fn empty() -> Self {
        Self::default()
    }

    /// Validates, trims, lowercases content types, deduplicates, and sorts values.
    pub fn new(
        document_ids: Vec<String>,
        content_types: Vec<String>,
    ) -> Result<Self, RetrievalError> {
        Self::normalize_with_limits(
            document_ids,
            content_types,
            DEFAULT_MAX_DOCUMENT_IDS,
            DEFAULT_MAX_CONTENT_TYPES,
        )
    }

    pub(crate) fn normalize_with_limits(
        document_ids: Vec<String>,
        content_types: Vec<String>,
        max_document_ids: usize,
        max_content_types: usize,
    ) -> Result<Self, RetrievalError> {
        let document_ids = normalize_document_ids(document_ids, max_document_ids)?;
        let content_types = normalize_content_types(content_types, max_content_types)?;
        Ok(Self {
            document_ids,
            content_types,
        })
    }

    pub(crate) fn matches(&self, candidate: &Candidate) -> bool {
        let document_matches = self.document_ids.is_empty()
            || self
                .document_ids
                .binary_search(&candidate.document_id)
                .is_ok();
        let content_matches = self.content_types.is_empty()
            || candidate
                .content_type
                .as_deref()
                .is_some_and(|content_type| {
                    self.content_types
                        .binary_search(&content_type.to_ascii_lowercase())
                        .is_ok()
                });
        document_matches && content_matches
    }
}

fn normalize_document_ids(
    document_ids: Vec<String>,
    limit: usize,
) -> Result<Vec<String>, RetrievalError> {
    let mut values = HashSet::with_capacity(limit.min(document_ids.len()));
    for value in document_ids {
        let value = value.trim();
        if value.is_empty() {
            return Err(RetrievalError::new(
                RetrievalErrorKind::EmptyFilterValue,
                "document_ids must not contain empty values",
            ));
        }
        let id = Uuid::parse_str(value).map_err(|_| {
            RetrievalError::new(
                RetrievalErrorKind::InvalidDocumentId,
                format!("document_id filter is not a UUIDv4: {value}"),
            )
        })?;
        if id.get_version_num() != 4 || id.get_variant() != uuid::Variant::RFC4122 {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidDocumentId,
                format!("document_id filter is not a UUIDv4: {value}"),
            ));
        }
        values.insert(id.to_string());
        if values.len() > limit {
            return Err(RetrievalError::new(
                RetrievalErrorKind::FilterLimitExceeded,
                format!("document_ids filter exceeds the limit of {limit}"),
            ));
        }
    }
    let mut values: Vec<_> = values.into_iter().collect();
    values.sort_unstable();
    Ok(values)
}

fn normalize_content_types(
    content_types: Vec<String>,
    limit: usize,
) -> Result<Vec<String>, RetrievalError> {
    let mut values = HashSet::with_capacity(limit.min(content_types.len()));
    for value in content_types {
        let value = value.trim().to_ascii_lowercase();
        if value.is_empty() {
            return Err(RetrievalError::new(
                RetrievalErrorKind::EmptyFilterValue,
                "content_types must not contain empty values",
            ));
        }
        if !SUPPORTED_CONTENT_TYPES.contains(&value.as_str()) {
            return Err(RetrievalError::new(
                RetrievalErrorKind::UnsupportedContentType,
                format!("unsupported content type filter: {value}"),
            ));
        }
        values.insert(value);
        if values.len() > limit {
            return Err(RetrievalError::new(
                RetrievalErrorKind::FilterLimitExceeded,
                format!("content_types filter exceeds the limit of {limit}"),
            ));
        }
    }
    let mut values: Vec<_> = values.into_iter().collect();
    values.sort_unstable();
    Ok(values)
}

/// Bounded, normalized query settings shared by all retrieval paths.
///
/// D-03 through D-05 and D-54 through D-56 are represented here so both paths
/// receive one candidate, query, and filter-bound contract.
#[derive(Debug, Clone, PartialEq)]
pub struct RetrievalSettings {
    pub candidate_limit: usize,
    pub final_limit: usize,
    pub query_max_bytes: usize,
    pub max_document_ids: usize,
    pub max_content_types: usize,
    pub vector_weight: f64,
    pub bm25_weight: f64,
    pub graph_weight: f64,
    pub rrf_k: f64,
    pub bm25: Bm25Config,
}

impl Default for RetrievalSettings {
    fn default() -> Self {
        Self {
            candidate_limit: DEFAULT_CANDIDATE_LIMIT,
            final_limit: DEFAULT_FINAL_LIMIT,
            query_max_bytes: DEFAULT_QUERY_MAX_BYTES,
            max_document_ids: DEFAULT_MAX_DOCUMENT_IDS,
            max_content_types: DEFAULT_MAX_CONTENT_TYPES,
            vector_weight: 1.0,
            bm25_weight: 1.0,
            graph_weight: 1.0,
            rrf_k: 60.0,
            bm25: Bm25Config::default(),
        }
    }
}

impl RetrievalSettings {
    pub fn validate(&self) -> Result<(), RetrievalError> {
        if self.candidate_limit == 0 || self.candidate_limit > MAX_SERVICE_CANDIDATE_LIMIT {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidSettings,
                format!("candidate_limit must be between 1 and {MAX_SERVICE_CANDIDATE_LIMIT}"),
            ));
        }
        if self.final_limit == 0 || self.final_limit > MAX_SERVICE_FINAL_LIMIT {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidSettings,
                format!("final_limit must be between 1 and {MAX_SERVICE_FINAL_LIMIT}"),
            ));
        }
        if self.final_limit > self.candidate_limit {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidSettings,
                "final_limit must not exceed candidate_limit",
            ));
        }
        if self.query_max_bytes == 0 || self.query_max_bytes > MAX_SERVICE_QUERY_MAX_BYTES {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidSettings,
                format!("query_max_bytes must be between 1 and {MAX_SERVICE_QUERY_MAX_BYTES}"),
            ));
        }
        if self.max_document_ids == 0 || self.max_document_ids > MAX_SERVICE_FILTER_VALUES_PER_KEY {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidSettings,
                format!(
                    "max_document_ids must be between 1 and {MAX_SERVICE_FILTER_VALUES_PER_KEY}"
                ),
            ));
        }
        if self.max_content_types == 0 || self.max_content_types > MAX_SERVICE_FILTER_VALUES_PER_KEY
        {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidSettings,
                format!(
                    "max_content_types must be between 1 and {MAX_SERVICE_FILTER_VALUES_PER_KEY}"
                ),
            ));
        }
        if !self.vector_weight.is_finite()
            || self.vector_weight < 0.0
            || self.vector_weight > MAX_SERVICE_RRF_WEIGHT
        {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidSettings,
                format!(
                    "vector_weight must be finite and between 0.0 and {MAX_SERVICE_RRF_WEIGHT}"
                ),
            ));
        }
        if !self.bm25_weight.is_finite()
            || self.bm25_weight < 0.0
            || self.bm25_weight > MAX_SERVICE_RRF_WEIGHT
        {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidSettings,
                format!("bm25_weight must be finite and between 0.0 and {MAX_SERVICE_RRF_WEIGHT}"),
            ));
        }
        if self.vector_weight + self.bm25_weight == 0.0 {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidSettings,
                "at least one of vector_weight or bm25_weight must be greater than zero",
            ));
        }
        if !self.graph_weight.is_finite()
            || self.graph_weight < 0.0
            || self.graph_weight > MAX_SERVICE_RRF_WEIGHT
        {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidSettings,
                format!(
                    "graph_weight must be finite and between 0.0 and {MAX_SERVICE_RRF_WEIGHT}"
                ),
            ));
        }
        if !self.rrf_k.is_finite()
            || self.rrf_k <= 0.0
            || self.rrf_k.fract() != 0.0
            || self.rrf_k > MAX_SERVICE_RRF_K
        {
            return Err(RetrievalError::new(
                RetrievalErrorKind::InvalidSettings,
                format!("rrf_k must be a positive integral value up to {MAX_SERVICE_RRF_K}"),
            ));
        }
        self.bm25.validate()
    }
}

/// A validated question whose filter values are ready for both retrieval paths.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QueryRequest {
    pub query: String,
    pub filters: QueryFilters,
}

impl QueryRequest {
    pub fn new(query: impl Into<String>, filters: QueryFilters) -> Result<Self, RetrievalError> {
        let settings = RetrievalSettings::default();
        Self::normalize(query, filters, &settings)
    }

    /// Trims the question while preserving its generation-facing semantics.
    ///
    /// D-54 rejects empty questions, D-55 bounds UTF-8 bytes, and D-57 keeps
    /// normalization separate from the original caller-visible question.
    pub fn normalize(
        query: impl Into<String>,
        filters: QueryFilters,
        settings: &RetrievalSettings,
    ) -> Result<Self, RetrievalError> {
        settings.validate()?;
        let query = query.into();
        let query = query.trim().to_owned();
        if query.is_empty() {
            return Err(RetrievalError::new(
                RetrievalErrorKind::EmptyQuery,
                "query must not be empty or whitespace-only",
            ));
        }
        if query.len() > settings.query_max_bytes {
            return Err(RetrievalError::new(
                RetrievalErrorKind::QueryTooLong,
                format!(
                    "query exceeds the UTF-8 byte limit of {}",
                    settings.query_max_bytes
                ),
            ));
        }
        let filters = QueryFilters::normalize_with_limits(
            filters.document_ids,
            filters.content_types,
            settings.max_document_ids,
            settings.max_content_types,
        )?;
        Ok(Self { query, filters })
    }

    pub fn from_values(
        query: impl Into<String>,
        document_ids: Vec<String>,
        content_types: Vec<String>,
        settings: &RetrievalSettings,
    ) -> Result<Self, RetrievalError> {
        let filters = QueryFilters::normalize_with_limits(
            document_ids,
            content_types,
            settings.max_document_ids,
            settings.max_content_types,
        )?;
        Self::normalize(query, filters, settings)
    }

    pub(crate) fn validate(&self, settings: &RetrievalSettings) -> Result<Self, RetrievalError> {
        Self::normalize(self.query.clone(), self.filters.clone(), settings)
    }
}

/// Canonical evidence metadata and a full-precision score from one path.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Candidate {
    pub document_id: String,
    pub chunk_id: String,
    pub chunk_index: i32,
    pub char_start: i32,
    pub char_end: i32,
    pub content: String,
    pub title: Option<String>,
    pub section_path: Option<String>,
    pub content_type: Option<String>,
    pub embedding_model: Option<String>,
    pub ingested_at: Option<i64>,
    pub score: f64,
}

impl Candidate {
    pub(crate) fn sort_key(&self) -> (&str, i32, &str) {
        (&self.document_id, self.chunk_index, &self.chunk_id)
    }
}

/// Object-safe async retrieval seam used by dense, BM25, and later coordinators.
pub trait Retriever: Send + Sync {
    fn retrieve<'a>(
        &'a self,
        request: &'a QueryRequest,
        settings: &'a RetrievalSettings,
    ) -> BoxFuture<'a, Result<Vec<Candidate>, RetrievalError>>;
}

#[cfg(test)]
mod tests;
