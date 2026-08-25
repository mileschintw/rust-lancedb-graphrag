//! OpenTelemetry metrics instrumentation and recording helpers.
//!
//! Provides the global meter accessor and domain-specific metric recording functions
//! using bounded dimensions only (D-35, D-42).
//!
//! # Degradation Predicate Note
//! The `lancet.rag.answer.degraded` counter predicate is `answer_basis != RETRIEVAL`
//! (recording `BASIS_MIXED` or `BASIS_MODEL_ONLY`). This is deliberately narrower
//! than `06-AI-SPEC.md` section 4.2's `degraded_mode` wire flag, which also fires
//! when specific degrade notices are present even if `answer_basis == RETRIEVAL`.
//! `BASIS_RETRIEVAL` is defined in the constant set for enum completeness, but has
//! no producer by construction.

use opentelemetry::KeyValue;

// --- Query Duration Constants ---
/// Outcome constant for successfully completed queries.
pub const OUTCOME_COMPLETED: &str = "completed";
/// Outcome constant for failed queries.
pub const OUTCOME_FAILED: &str = "failed";

// --- Retrieval Path & Failure Kind Constants ---
/// Path constant for dense embedding retrieval.
pub const PATH_DENSE: &str = "dense";
/// Path constant for BM25 lexical retrieval.
pub const PATH_BM25: &str = "bm25";
/// Path constant for graph retrieval.
pub const PATH_GRAPH: &str = "graph";

/// Kind constant for timeout failures.
pub const KIND_TIMEOUT: &str = "timeout";
/// Kind constant for generic error failures.
pub const KIND_ERROR: &str = "error";
/// Kind constant for unavailable components.
pub const KIND_UNAVAILABLE: &str = "unavailable";

// --- Answer Basis Constants ---
/// Answer basis constant for standard grounded retrieval.
pub const BASIS_RETRIEVAL: &str = "retrieval";
/// Answer basis constant for mixed evidence answers.
pub const BASIS_MIXED: &str = "mixed";
/// Answer basis constant for ungrounded model-only answers.
pub const BASIS_MODEL_ONLY: &str = "model_only";

// --- Citation Action Constants ---
/// Action constant for repaired citation markers.
pub const ACTION_REPAIRED: &str = "repaired";
/// Action constant for dropped citation markers.
pub const ACTION_DROPPED: &str = "dropped";

// --- Generation Retry Outcome Constants ---
/// Outcome constant for recovered retry attempt.
pub const RETRY_RECOVERED: &str = "recovered";
/// Outcome constant for exhausted retry attempts.
pub const RETRY_EXHAUSTED: &str = "exhausted";

// --- Ingestion Outcome Constants ---
/// Outcome constant for successfully ingested document.
pub const INGEST_COMPLETED: &str = "completed";
/// Outcome constant for failed document ingestion.
pub const INGEST_FAILED: &str = "failed";

// --- Index Rebuild Outcome Constants ---
/// Outcome constant for successfully rebuilt index.
pub const REBUILD_COMPLETED: &str = "completed";
/// Outcome constant for failed index rebuild.
pub const REBUILD_FAILED: &str = "failed";

/// Returns a [`Meter`] bound to the engine's instrumentation scope.
pub fn meter() -> opentelemetry::metrics::Meter {
    opentelemetry::global::meter("lancet-engine")
}

/// Records the total query duration in milliseconds with the bounded `outcome` attribute.
pub fn record_query_duration_ms(outcome: &'static str, millis: u64) {
    let histogram = meter()
        .u64_histogram("lancet.rag.query.duration")
        .with_unit("ms")
        .with_description("RAG query duration in milliseconds")
        .build();
    histogram.record(millis, &[KeyValue::new("outcome", outcome)]);
}

/// Records a retrieval path failure event with bounded `path` and `kind` attributes.
pub fn record_retrieval_path_failure(path: &'static str, kind: &'static str) {
    let counter = meter()
        .u64_counter("lancet.rag.retrieval.path_failures")
        .with_description("RAG retrieval path failures")
        .build();
    counter.add(1, &[KeyValue::new("path", path), KeyValue::new("kind", kind)]);
}

/// Records a degraded answer production with the terminal `answer_basis` attribute.
pub fn record_answer_degraded(answer_basis: &'static str) {
    let counter = meter()
        .u64_counter("lancet.rag.answer.degraded")
        .with_description("RAG degraded answers produced")
        .build();
    counter.add(1, &[KeyValue::new("answer_basis", answer_basis)]);
}

/// Records a citation marker repair or drop action with the bounded `action` attribute.
pub fn record_citation_repair(action: &'static str) {
    let counter = meter()
        .u64_counter("lancet.rag.citation.repairs")
        .with_description("RAG citation marker repair actions")
        .build();
    counter.add(1, &[KeyValue::new("action", action)]);
}

/// Records an LLM generation retry event with bounded `outcome` attribute.
pub fn record_generation_retry(outcome: &'static str) {
    let counter = meter()
        .u64_counter("lancet.rag.generation.retries")
        .with_description("RAG LLM generation retries")
        .build();
    counter.add(1, &[KeyValue::new("outcome", outcome)]);
}

/// Records the packed evidence set size in block count.
pub fn record_evidence_set_size(count: u64) {
    let histogram = meter()
        .u64_histogram("lancet.rag.evidence.set_size")
        .with_description("RAG packed evidence set block counts")
        .build();
    histogram.record(count, &[]);
}

/// Records an ingested document outcome with bounded `outcome` attribute.
pub fn record_ingest_document(outcome: &'static str) {
    let counter = meter()
        .u64_counter("lancet.ingest.documents")
        .with_description("Ingested documents count")
        .build();
    counter.add(1, &[KeyValue::new("outcome", outcome)]);
}

/// Records chunk count from a successfully ingested document.
pub fn record_ingest_chunks(count: u64) {
    let counter = meter()
        .u64_counter("lancet.ingest.chunks")
        .with_description("Ingested chunks count")
        .build();
    counter.add(count, &[]);
}

/// Records index rebuild duration in milliseconds with bounded `outcome` attribute.
pub fn record_index_rebuild_duration_ms(outcome: &'static str, millis: u64) {
    let histogram = meter()
        .u64_histogram("lancet.index.rebuild.duration")
        .with_unit("ms")
        .with_description("Index rebuild and swap duration in milliseconds")
        .build();
    histogram.record(millis, &[KeyValue::new("outcome", outcome)]);
}

/// Records the current index corpus generation as numeric nodes version.
pub fn record_corpus_generation(nodes_version: u64) {
    let gauge = meter()
        .u64_gauge("lancet.index.corpus_generation")
        .with_description("Current index corpus generation as numeric nodes version")
        .build();
    gauge.record(nodes_version, &[]);
}

