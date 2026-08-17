use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::pb::lancet::v1::{
    workflow_event::Event, AnswerChunkEvent, CheckpointEvent, FinalAnswerEvent, NodeCompletedEvent,
    NodeFailedEvent, NodeErrorKind, NodeStartedEvent, QueryRagResponse, WorkflowCompletedEvent,
    WorkflowEvent,
};
use super::WorkflowContext;

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
    let snapshot_json = serde_json::json!({
        "session_id": context.session_id,
        "trace_id": context.trace_id,
        "original_query": context.original_query,
        "variants": context.variants,
        "vector_results": context.vector_results,
        "bm25_results": context.bm25_results,
        "final_candidates": context.final_candidates,
    })
    .to_string();

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
) -> Event {
    Event::WorkflowCompleted(WorkflowCompletedEvent {
        success,
        duration_ms,
        error_kind: error_kind as i32,
        error_message: error_message.into(),
        final_response,
        notices: Vec::new(),
    })
}
