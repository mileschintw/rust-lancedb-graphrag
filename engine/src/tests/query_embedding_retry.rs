//! Tests for the bounded query-embedding retry (06.3.6-06, D-152).
//!
//! `ExtractGraphContext` asks for the query embedding once more after a timeout, pauses a short
//! jitter between the two attempts, counts the retry on the context and on the wire, and leaves
//! every other error alone. The timing tests run on a paused clock, so the elapsed time they read
//! is the exact sum of the timeouts and pauses the node waited, not a wall-clock sample.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use futures::future::BoxFuture;
use prost::Message;
use tokio::sync::mpsc;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use crate::generation::{AnswerBasis, FakeGenerator, ModelOutput};
use crate::pb::lancet::v1::{workflow_event::Event, NodeErrorKind, WorkflowMetadata};
use crate::prompt::{DEFAULT_ANSWER_TOKEN_BUDGET, DEFAULT_MAX_PROMPT_TOKENS};
use crate::retrieval::{Candidate, RetrievalSettings};
use crate::testkit::test_query_request;
use crate::workflow::events::EventSequence;
use crate::workflow::node::{Node, NodeError, QueryEmbeddingPort};
use crate::workflow::nodes::graph_context::{
    retry_jitter_ms, QUERY_EMBEDDING_ATTEMPTS, RETRY_JITTER_MAX_MS,
};
use crate::workflow::nodes::{
    AssemblePromptNode, ExtractGraphContextNode, GenerateAnswerNode, RetrieveHybridNode,
};
use crate::workflow::ports::{FakeBm25RetrievalPort, FakeDenseRetrievalPort};
use crate::workflow::{WorkflowContext, WorkflowEventSink, WorkflowRunner};

/// The per-attempt budget the tests give the node, the committed `query_embedding_timeout_ms`.
const ATTEMPT_MS: u64 = 2_000;

/// Longer than any attempt budget, so a call that stalls is always cut off by the timeout.
const STALL: Duration = Duration::from_secs(3_600);

const SESSION: &str = "00000000-0000-4000-8000-000000000152";

/// An embedder whose first `stalled_calls` calls never finish and whose later calls answer.
struct ScriptedEmbedder {
    stalled_calls: usize,
    answer: Result<Vec<f32>, NodeError>,
    calls: AtomicUsize,
}

impl ScriptedEmbedder {
    fn stalls_first(stalled_calls: usize) -> Self {
        Self {
            stalled_calls,
            answer: Ok(vec![0.5; 4]),
            calls: AtomicUsize::new(0),
        }
    }

    fn answers() -> Self {
        Self::stalls_first(0)
    }

    fn always_stalls() -> Self {
        Self::stalls_first(usize::MAX)
    }

    fn fails_with(error: NodeError) -> Self {
        Self {
            stalled_calls: 0,
            answer: Err(error),
            calls: AtomicUsize::new(0),
        }
    }

    fn calls(&self) -> usize {
        self.calls.load(Ordering::SeqCst)
    }
}

impl QueryEmbeddingPort for ScriptedEmbedder {
    fn embed_variant_zero<'a>(
        &'a self,
        _variant: &'a str,
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<f32>, NodeError>> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst);
        Box::pin(async move {
            if call < self.stalled_calls {
                tokio::time::sleep(STALL).await;
            }
            self.answer.clone()
        })
    }
}

fn node_over(embedder: &Arc<ScriptedEmbedder>) -> ExtractGraphContextNode {
    ExtractGraphContextNode::new(Some(Arc::clone(embedder) as Arc<dyn QueryEmbeddingPort>), None)
        .with_timeouts(ATTEMPT_MS, 1_000)
}

/// A context for a graph-off query, so the node ends right after the embedding step.
fn context_with_trace(trace_id: &str) -> WorkflowContext {
    let mut ctx = WorkflowContext::new(
        SESSION.into(),
        trace_id.into(),
        &test_query_request("what did Acme supply?", SESSION),
    );
    ctx.disable_graph_context = true;
    ctx
}

fn jitter_for(trace_id: &str) -> Duration {
    Duration::from_millis(retry_jitter_ms(trace_id, 1, RETRY_JITTER_MAX_MS))
}

#[tokio::test(start_paused = true)]
async fn a_first_attempt_success_takes_one_call_no_pause_and_counts_no_retry() {
    let embedder = Arc::new(ScriptedEmbedder::answers());
    let node = node_over(&embedder);
    let mut ctx = context_with_trace("trace-first-try");
    let started = Instant::now();

    node.run(&mut ctx, &CancellationToken::new()).await.unwrap();

    assert_eq!(embedder.calls(), 1);
    assert_eq!(ctx.query_embedding, Some(vec![0.5; 4]));
    assert_eq!(ctx.query_embedding_retries, 0);
    assert_eq!(started.elapsed(), Duration::ZERO, "no sleep on the happy path");
}

#[tokio::test(start_paused = true)]
async fn a_timeout_then_success_retries_once_after_the_jitter_and_counts_it() {
    let embedder = Arc::new(ScriptedEmbedder::stalls_first(1));
    let node = node_over(&embedder);
    let mut ctx = context_with_trace("trace-timeout-then-success");
    let started = Instant::now();

    node.run(&mut ctx, &CancellationToken::new()).await.unwrap();

    assert_eq!(embedder.calls(), 2);
    assert_eq!(ctx.query_embedding, Some(vec![0.5; 4]));
    assert_eq!(ctx.query_embedding_retries, 1);
    let jitter = jitter_for("trace-timeout-then-success");
    assert_eq!(
        started.elapsed(),
        Duration::from_millis(ATTEMPT_MS) + jitter,
        "one timed-out attempt, the jitter pause, then an immediate answer"
    );
    assert!(jitter <= Duration::from_millis(RETRY_JITTER_MAX_MS));
    assert!(
        !ctx.notices.iter().any(|n| n.code.contains("DEGRADED")),
        "a retried-then-successful record carries no degradation notice"
    );
}

#[tokio::test(start_paused = true)]
async fn two_timeouts_fail_the_node_with_the_existing_timeout_error() {
    let embedder = Arc::new(ScriptedEmbedder::always_stalls());
    let node = node_over(&embedder);
    let mut ctx = context_with_trace("trace-two-timeouts");
    let started = Instant::now();

    let error = node
        .run(&mut ctx, &CancellationToken::new())
        .await
        .expect_err("two timeouts must fail the node");

    assert_eq!(error.kind, NodeErrorKind::Timeout);
    assert_eq!(error.message, "Query embedding timed out");
    assert_eq!(embedder.calls(), 2, "one try and one retry, never a third");
    assert_eq!(ctx.query_embedding_retries, 1);
    assert!(ctx.query_embedding.is_none());
    assert_eq!(
        started.elapsed(),
        Duration::from_millis(2 * ATTEMPT_MS) + jitter_for("trace-two-timeouts"),
        "two full attempt budgets and one jitter pause"
    );
}

#[tokio::test(start_paused = true)]
async fn a_non_timeout_error_returns_at_once_without_a_retry() {
    let failure = NodeError::new(NodeErrorKind::Internal, "embedding provider refused");
    let embedder = Arc::new(ScriptedEmbedder::fails_with(failure.clone()));
    let node = node_over(&embedder);
    let mut ctx = context_with_trace("trace-provider-error");
    let started = Instant::now();

    let error = node
        .run(&mut ctx, &CancellationToken::new())
        .await
        .expect_err("a provider error must fail the node");

    assert_eq!(error, failure);
    assert_eq!(embedder.calls(), 1);
    assert_eq!(ctx.query_embedding_retries, 0);
    assert_eq!(started.elapsed(), Duration::ZERO);
}

#[tokio::test(start_paused = true)]
async fn a_cancel_during_the_jitter_pause_returns_cancelled_without_a_second_attempt() {
    // The cancel lands one millisecond after the first attempt times out, so it can only land
    // inside the pause when the pause is longer than that. Pick a trace id whose pause is.
    let trace_id = (0_u32..)
        .map(|n| format!("trace-cancel-{n}"))
        .find(|candidate| retry_jitter_ms(candidate, 1, RETRY_JITTER_MAX_MS) >= 2)
        .expect("some trace id has a pause of at least two milliseconds");
    let embedder = Arc::new(ScriptedEmbedder::stalls_first(1));
    let node = node_over(&embedder);
    let mut ctx = context_with_trace(&trace_id);
    let cancel = CancellationToken::new();
    let canceller = cancel.clone();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(ATTEMPT_MS + 1)).await;
        canceller.cancel();
    });
    let started = Instant::now();

    let error = node
        .run(&mut ctx, &cancel)
        .await
        .expect_err("a cancel during the pause must end the node");

    assert_eq!(error.kind, NodeErrorKind::Cancelled);
    assert_eq!(embedder.calls(), 1, "no second attempt after the cancel");
    assert!(ctx.query_embedding.is_none());
    assert_eq!(
        started.elapsed(),
        Duration::from_millis(ATTEMPT_MS + 1),
        "the pause ended at the cancel, not at the end of the jitter"
    );
}

#[test]
fn the_jitter_is_deterministic_per_trace_bounded_and_spread() {
    let mut seen = std::collections::BTreeSet::new();
    for n in 0_u32..500 {
        let trace_id = format!("trace-{n}");
        for attempt in 1..=QUERY_EMBEDDING_ATTEMPTS {
            let jitter = retry_jitter_ms(&trace_id, attempt, RETRY_JITTER_MAX_MS);
            assert!(jitter <= RETRY_JITTER_MAX_MS, "{trace_id}/{attempt}: {jitter}");
            assert_eq!(
                jitter,
                retry_jitter_ms(&trace_id, attempt, RETRY_JITTER_MAX_MS),
                "the same trace and attempt always pause the same time"
            );
            seen.insert(jitter);
        }
    }
    assert!(
        seen.len() > 100,
        "500 traces must spread over the 251-value range, saw {} distinct values",
        seen.len()
    );
    assert_eq!(retry_jitter_ms("any trace", 1, 0), 0, "a zero bound gives no pause");
    assert!(
        retry_jitter_ms("any trace", 1, u64::MAX) < u64::MAX,
        "the largest bound must not overflow"
    );
}

#[test]
fn the_attempt_count_is_one_try_plus_one_retry() {
    assert_eq!(QUERY_EMBEDDING_ATTEMPTS, 2);
}

// ---- the count on the wire ---------------------------------------------------------------------

fn dense_row() -> Candidate {
    Candidate {
        document_id: "00000000-0000-4000-8000-0000000000d1".to_owned(),
        chunk_id: "00000000-0000-4000-8000-0000000000d1:0".to_owned(),
        chunk_index: 0,
        char_start: 0,
        char_end: 10,
        content: "Acme supplied Beta Works.".to_owned(),
        title: Some("Title".to_owned()),
        section_path: None,
        content_type: Some("text/plain".to_owned()),
        embedding_model: Some("test-model".to_owned()),
        ingested_at: Some(1),
        score: 0.9,
    }
}

/// Runs the whole workflow over the fakes with this embedder and returns its metadata.
async fn wire_metadata(embedder: Arc<ScriptedEmbedder>) -> WorkflowMetadata {
    let (tx, mut rx) = mpsc::channel(100);
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-retry-wire".to_owned(),
        SESSION.to_owned(),
    );
    // Graph off, so the only thing that could mark the record degraded is the retry itself.
    let mut request = test_query_request("what did Acme supply?", SESSION);
    request.disable_graph_context = Some(true);
    let ctx = WorkflowContext::new(SESSION.to_owned(), "trace-retry-wire".to_owned(), &request);
    let mut runner = WorkflowRunner::new();
    runner.add_node(
        ExtractGraphContextNode::new(Some(embedder as Arc<dyn QueryEmbeddingPort>), None)
            .with_timeouts(ATTEMPT_MS, 1_000),
    );
    runner.add_node(RetrieveHybridNode::new(
        Some(Arc::new(FakeDenseRetrievalPort::success(vec![dense_row()]))),
        Some(Arc::new(FakeBm25RetrievalPort::success(vec![]))),
        None,
        RetrievalSettings {
            candidate_limit: 12,
            final_limit: 4,
            ..RetrievalSettings::default()
        },
    ));
    runner.add_node(AssemblePromptNode::with_settings(
        DEFAULT_MAX_PROMPT_TOKENS,
        DEFAULT_ANSWER_TOKEN_BUDGET,
        1.0,
    ));
    runner.add_node(GenerateAnswerNode::new(Some(Arc::new(FakeGenerator::new(Ok(
        ModelOutput {
            answer: "Acme supplied Beta Works [1].".to_owned(),
            cited_evidence_ids: vec!["[1]".to_owned()],
            answer_basis: AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            final_answer: None,
            usage: None,
        },
    ))))));
    runner
        .run_workflow(ctx, CancellationToken::new(), sink)
        .await;

    let mut completed = None;
    while let Ok(item) = rx.try_recv() {
        if let Ok(event) = item {
            if let Some(Event::WorkflowCompleted(done)) = event.event {
                completed = Some(done);
            }
        }
    }
    let completed = completed.expect("the workflow emits a terminal event");
    assert!(completed.success, "{}", completed.error_message);
    completed.metadata.expect("a completed workflow carries metadata")
}

/// The extra bytes a retry count of one adds to the encoded metadata: a two-byte key (tag 18,
/// varint) and a one-byte value.
const RETRY_FIELD_BYTES: usize = 3;

#[tokio::test(start_paused = true)]
async fn the_retry_count_reaches_the_wire_metadata_and_a_clean_record_omits_the_field() {
    let retried = wire_metadata(Arc::new(ScriptedEmbedder::stalls_first(1))).await;
    assert_eq!(retried.query_embedding_retries, 1);
    assert!(
        !retried.degraded_mode,
        "a retried-then-successful record is not degraded"
    );

    let clean = wire_metadata(Arc::new(ScriptedEmbedder::answers())).await;
    assert_eq!(clean.query_embedding_retries, 0);
    let with_one = WorkflowMetadata {
        query_embedding_retries: 1,
        ..clean.clone()
    };
    assert_eq!(
        with_one.encode_to_vec().len(),
        clean.encode_to_vec().len() + RETRY_FIELD_BYTES,
        "a zero count is not written, so a clean record keeps its bytes"
    );
}
