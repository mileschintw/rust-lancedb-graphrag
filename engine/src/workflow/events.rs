use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::Serialize;

use super::WorkflowContext;
use crate::pb::lancet::v1::{
    workflow_event::Event, AnswerChunkEvent, CheckpointEvent, DocumentFilter, FinalAnswerEvent,
    NodeCompletedEvent, NodeErrorKind, NodeFailedEvent, NodeStartedEvent, Notice, QueryRagResponse,
    RetrievalSnapshot, StructuredCitation, WorkflowCompletedEvent, WorkflowEvent,
};
use crate::prompt::{EvidenceBlock, GraphFactBlock};

/// The stable top-level keys written into every checkpoint context snapshot.
pub const CHECKPOINT_SNAPSHOT_KEYS: [&str; 19] = [
    "session_id",
    "trace_id",
    "original_query",
    "filter",
    "variants",
    "query_embedding",
    "graph_context",
    "graph_facts",
    "vector_results",
    "bm25_results",
    "final_candidates",
    "evidence_blocks",
    "assembled_prompt",
    "answer",
    "citations",
    "answer_basis",
    "structured_citations",
    "notices",
    "snapshot",
];

/// A stable representation of a document filter in checkpoint JSON.
#[derive(Debug, Clone, Serialize)]
pub struct CheckpointFilter {
    pub document_ids: Vec<String>,
    pub content_types: Vec<String>,
}

impl From<&DocumentFilter> for CheckpointFilter {
    fn from(filter: &DocumentFilter) -> Self {
        Self {
            document_ids: filter.document_ids.clone(),
            content_types: filter.content_types.clone(),
        }
    }
}

/// A fixed-size digest for a query embedding retained in checkpoint JSON.
#[derive(Debug, Clone, Serialize)]
pub struct QueryEmbeddingDigest {
    pub dimension: usize,
    pub hash: String,
}

impl QueryEmbeddingDigest {
    fn from_embedding(embedding: &[f32]) -> Self {
        let mut hash = 0xcbf29ce484222325_u64;
        for byte in (embedding.len() as u64).to_le_bytes() {
            hash ^= u64::from(byte);
            hash = hash.wrapping_mul(0x100000001b3_u64);
        }
        for value in embedding {
            for byte in value.to_bits().to_le_bytes() {
                hash ^= u64::from(byte);
                hash = hash.wrapping_mul(0x100000001b3_u64);
            }
        }

        Self {
            dimension: embedding.len(),
            hash: format!("{hash:016x}"),
        }
    }
}

/// A stable representation of a protobuf structured citation.
#[derive(Debug, Clone, Serialize)]
pub struct CheckpointStructuredCitation {
    pub chunk_id: String,
    pub document_id: String,
    pub title: String,
    pub section_path: String,
    pub excerpt: String,
    pub is_truncated: bool,
    pub score: f64,
    pub rank: i32,
    pub content_type: String,
}

impl From<&StructuredCitation> for CheckpointStructuredCitation {
    fn from(citation: &StructuredCitation) -> Self {
        Self {
            chunk_id: citation.chunk_id.clone(),
            document_id: citation.document_id.clone(),
            title: citation.title.clone(),
            section_path: citation.section_path.clone(),
            excerpt: citation.excerpt.clone(),
            is_truncated: citation.is_truncated,
            score: citation.score,
            rank: citation.rank,
            content_type: citation.content_type.clone(),
        }
    }
}

/// A stable representation of a protobuf notice retained in checkpoint JSON.
#[derive(Debug, Clone, Serialize)]
pub struct CheckpointNotice {
    pub code: String,
    pub message: String,
    pub severity: i32,
}

impl From<&Notice> for CheckpointNotice {
    fn from(notice: &Notice) -> Self {
        Self {
            code: notice.code.clone(),
            message: notice.message.clone(),
            severity: notice.severity,
        }
    }
}

/// A stable representation of the retrieval controls and provenance snapshot.
#[derive(Debug, Clone, Serialize)]
pub struct CheckpointRetrievalSnapshot {
    pub index_generation: String,
    pub embedding_model: String,
    pub vector_weight: f64,
    pub bm25_weight: f64,
    pub rrf_k: i32,
    pub candidate_limit: i32,
    pub final_limit: i32,
    pub active_filter: Option<CheckpointFilter>,
    pub result_hash: String,
    pub variant_count: u32,
    pub variant_identities: Vec<String>,
}

impl From<&RetrievalSnapshot> for CheckpointRetrievalSnapshot {
    fn from(snapshot: &RetrievalSnapshot) -> Self {
        Self {
            index_generation: snapshot.index_generation.clone(),
            embedding_model: snapshot.embedding_model.clone(),
            vector_weight: snapshot.vector_weight,
            bm25_weight: snapshot.bm25_weight,
            rrf_k: snapshot.rrf_k,
            candidate_limit: snapshot.candidate_limit,
            final_limit: snapshot.final_limit,
            active_filter: snapshot.active_filter.as_ref().map(CheckpointFilter::from),
            result_hash: snapshot.result_hash.clone(),
            variant_count: snapshot.variant_count,
            variant_identities: snapshot.variant_identities.clone(),
        }
    }
}

/// The canonical full accumulated WorkflowContext checkpoint contract.
///
/// Every field is emitted, including empty or absent values. The only compact
/// representation is `query_embedding`, whose raw vector is replaced with a
/// fixed-size digest containing its dimension and deterministic hash.
#[derive(Debug, Clone, Serialize)]
pub struct CheckpointSnapshot {
    #[serde(rename = "session_id")]
    pub session_id: String,
    #[serde(rename = "trace_id")]
    pub trace_id: String,
    #[serde(rename = "original_query")]
    pub original_query: String,
    #[serde(rename = "filter")]
    pub filter: Option<CheckpointFilter>,
    #[serde(rename = "variants")]
    pub variants: Vec<String>,
    #[serde(rename = "query_embedding")]
    pub query_embedding: Option<QueryEmbeddingDigest>,
    #[serde(rename = "graph_context")]
    pub graph_context: String,
    #[serde(rename = "graph_facts")]
    pub graph_facts: Vec<GraphFactBlock>,
    #[serde(rename = "vector_results")]
    pub vector_results: Vec<String>,
    #[serde(rename = "bm25_results")]
    pub bm25_results: Vec<String>,
    #[serde(rename = "final_candidates")]
    pub final_candidates: Vec<String>,
    #[serde(rename = "evidence_blocks")]
    pub evidence_blocks: Vec<EvidenceBlock>,
    #[serde(rename = "assembled_prompt")]
    pub assembled_prompt: String,
    #[serde(rename = "answer")]
    pub answer: String,
    #[serde(rename = "citations")]
    pub citations: Vec<String>,
    #[serde(rename = "answer_basis")]
    pub answer_basis: i32,
    #[serde(rename = "structured_citations")]
    pub structured_citations: Vec<CheckpointStructuredCitation>,
    #[serde(rename = "notices")]
    pub notices: Vec<CheckpointNotice>,
    #[serde(rename = "snapshot")]
    pub snapshot: Option<CheckpointRetrievalSnapshot>,
}

impl CheckpointSnapshot {
    /// Builds the canonical snapshot from the accumulated workflow context.
    pub fn from_context(context: &WorkflowContext) -> Self {
        Self {
            session_id: context.session_id.clone(),
            trace_id: context.trace_id.clone(),
            original_query: context.original_query.clone(),
            filter: context.filter.as_ref().map(CheckpointFilter::from),
            variants: context.variants.clone(),
            query_embedding: context
                .query_embedding
                .as_deref()
                .map(QueryEmbeddingDigest::from_embedding),
            graph_context: context.graph_context.clone(),
            graph_facts: context.graph_facts.clone(),
            vector_results: context.vector_results.clone(),
            bm25_results: context.bm25_results.clone(),
            final_candidates: context.final_candidates.clone(),
            evidence_blocks: context.evidence_blocks.clone(),
            assembled_prompt: context.assembled_prompt.clone(),
            answer: context.answer.clone(),
            citations: context.citations.clone(),
            answer_basis: context.answer_basis as i32,
            structured_citations: context
                .structured_citations
                .iter()
                .map(CheckpointStructuredCitation::from)
                .collect(),
            notices: context.notices.iter().map(CheckpointNotice::from).collect(),
            snapshot: context
                .snapshot
                .as_ref()
                .map(CheckpointRetrievalSnapshot::from),
        }
    }

    /// Serializes the full snapshot as valid JSON for the checkpoint envelope.
    pub fn to_json(&self) -> String {
        serde_json::to_string(self)
            .expect("WorkflowContext checkpoint snapshot must serialize as valid JSON")
    }
}

pub struct EventSequence {
    counter: AtomicU64,
}

impl EventSequence {
    pub fn new() -> Self {
        Self {
            counter: AtomicU64::new(1),
        }
    }

    pub fn next(&self) -> u64 {
        self.counter.fetch_add(1, Ordering::SeqCst)
    }
}

impl Default for EventSequence {
    fn default() -> Self {
        Self::new()
    }
}

pub fn now_timestamp_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

pub fn wrap_event(
    event: Event,
    sequence_ordinal: u64,
    trace_id: impl Into<String>,
    session_id: impl Into<String>,
) -> WorkflowEvent {
    WorkflowEvent {
        trace_id: trace_id.into(),
        session_id: session_id.into(),
        sequence_ordinal,
        timestamp_ms: now_timestamp_ms(),
        event: Some(event),
    }
}

pub fn node_started(node_name: impl Into<String>, inputs_summary: impl Into<String>) -> Event {
    Event::NodeStarted(NodeStartedEvent {
        node_name: node_name.into(),
        inputs_summary: inputs_summary.into(),
    })
}

pub fn node_completed(
    node_name: impl Into<String>,
    outputs_summary: impl Into<String>,
    duration_ms: i64,
) -> Event {
    Event::NodeCompleted(NodeCompletedEvent {
        node_name: node_name.into(),
        outputs_summary: outputs_summary.into(),
        duration_ms,
    })
}

pub fn node_failed(
    node_name: impl Into<String>,
    category: NodeErrorKind,
    message: impl Into<String>,
    retryable: bool,
) -> Event {
    Event::NodeFailed(NodeFailedEvent {
        node_name: node_name.into(),
        category: category as i32,
        message: message.into(),
        retryable,
    })
}

pub fn answer_chunk(chunk: impl Into<String>, is_final: bool) -> Event {
    Event::AnswerChunk(AnswerChunkEvent {
        chunk: chunk.into(),
        is_final,
    })
}

pub fn final_answer(response: QueryRagResponse) -> Event {
    Event::FinalAnswer(FinalAnswerEvent {
        response: Some(response),
    })
}

pub fn checkpoint(
    checkpoint_type: impl Into<String>,
    sequence_ordinal: u64,
    context: &WorkflowContext,
) -> Event {
    let snapshot_json = CheckpointSnapshot::from_context(context).to_json();

    Event::Checkpoint(CheckpointEvent {
        checkpoint_type: checkpoint_type.into(),
        sequence_ordinal,
        context_snapshot: snapshot_json,
    })
}

pub fn workflow_completed(
    success: bool,
    duration_ms: i64,
    error_kind: NodeErrorKind,
    error_message: impl Into<String>,
    final_response: Option<QueryRagResponse>,
    notices: Vec<Notice>,
    metadata: Option<crate::pb::lancet::v1::WorkflowMetadata>,
) -> Event {
    Event::WorkflowCompleted(WorkflowCompletedEvent {
        success,
        duration_ms,
        error_kind: error_kind as i32,
        error_message: error_message.into(),
        final_response,
        notices,
        metadata,
    })
}
