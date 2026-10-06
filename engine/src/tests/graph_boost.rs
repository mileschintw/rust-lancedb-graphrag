//! Tests for the graph chunk boost in RetrieveHybrid (06.3.4.1-15, D-76, D-81).
//!
//! The graph's candidate chunks (`ctx.graph_chunk_candidates`, set by ExtractGraphContext) enter
//! fusion as a third RRF list. These tests pin the node's behaviour at the port level (the fakes)
//! and at the store level (the production port over a temp LanceDB store).

use std::cell::Cell;
use std::sync::{Arc, Mutex};

use arrow_array::{
    new_null_array, types::Float32Type, FixedSizeListArray, Int32Array, Int64Array, RecordBatch,
    StringArray,
};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

use crate::db::DatabaseManager;
use crate::pb::lancet::v1::{DocumentFilter, NodeErrorKind};
use crate::retrieval::dense::is_valid_chunk_id;
use crate::retrieval::{Candidate, RetrievalSettings};
use crate::service::ProductionDenseRetrievalPort;
use crate::testkit::test_query_request;
use crate::workflow::node::{Node, NodeError, QueryEmbeddingPort};
use crate::workflow::nodes::{ExtractGraphContextNode, RetrieveHybridNode};
use crate::workflow::ports::{
    DenseRetrievalPort, FakeBm25RetrievalPort, FakeDenseRetrievalPort, FakeGraphQueryPort,
    FakeQueryEmbeddingPort, GraphQueryOutput, GraphQueryPort,
};
use crate::workflow::WorkflowContext;

// ---- fixtures -------------------------------------------------------------------------------

const DOC_A: &str = "00000000-0000-4000-8000-0000000000b1";
const DOC_B: &str = "00000000-0000-4000-8000-0000000000b2";
const DOC_C: &str = "00000000-0000-4000-8000-0000000000b3";

fn chunk_id(doc: &str, index: i32) -> String {
    format!("{doc}:{index}")
}

/// A chunk row whose content names the path that produced it.
fn row(doc: &str, index: i32, source: &str, score: f64) -> Candidate {
    Candidate {
        document_id: doc.to_owned(),
        chunk_id: chunk_id(doc, index),
        chunk_index: index,
        char_start: 0,
        char_end: 10,
        content: format!("{source} {doc} {index}"),
        title: Some("Title".to_owned()),
        section_path: None,
        content_type: Some("text/plain".to_owned()),
        embedding_model: Some("test-model".to_owned()),
        ingested_at: Some(1),
        score,
    }
}

fn pin_settings() -> RetrievalSettings {
    RetrievalSettings {
        candidate_limit: 12,
        final_limit: 4,
        ..RetrievalSettings::default()
    }
}

fn new_context() -> WorkflowContext {
    WorkflowContext::new(
        "sess-boost".into(),
        "trace-boost".into(),
        &test_query_request("alpha", "00000000-0000-4000-8000-000000000001"),
    )
}

/// What the node publishes for one query, with each float as its exact bit pattern.
fn render_outcome(ctx: &WorkflowContext) -> String {
    let snapshot = ctx.snapshot.as_ref().expect("the node publishes a snapshot");
    let chunks = snapshot
        .retrieved_chunks
        .iter()
        .map(|chunk| {
            format!(
                "{}|{:016x}|{}",
                chunk.chunk_id,
                chunk.score.to_bits(),
                chunk.rank
            )
        })
        .collect::<Vec<_>>()
        .join("\n");
    let notices = ctx
        .notices
        .iter()
        .map(|notice| notice.code.clone())
        .collect::<Vec<_>>()
        .join(",");
    format!(
        "hash={}\nvariants={}\nvector={}\nbm25={}\nfinal={}\nnotices={}\n{}",
        snapshot.result_hash,
        snapshot.variant_count,
        ctx.vector_results.join(","),
        ctx.bm25_results.join(","),
        ctx.final_candidates.join(","),
        notices,
        chunks
    )
}

/// The dense and BM25 hits of the single-variant pin scenario.
fn single_variant_ports() -> (FakeDenseRetrievalPort, FakeBm25RetrievalPort) {
    (
        FakeDenseRetrievalPort::success(vec![
            row(DOC_A, 0, "dense", 0.9),
            row(DOC_A, 1, "dense", 0.8),
            row(DOC_B, 0, "dense", 0.7),
            row(DOC_C, 0, "dense", 0.6),
        ]),
        FakeBm25RetrievalPort::success(vec![
            row(DOC_B, 0, "bm25", 9.0),
            row(DOC_A, 0, "bm25", 7.0),
            row(DOC_C, 1, "bm25", 3.0),
        ]),
    )
}

/// The dense and BM25 hits of the three-variant pin scenario, each variant with its own BM25 list.
fn three_variant_ports() -> (FakeDenseRetrievalPort, FakeBm25RetrievalPort) {
    (
        FakeDenseRetrievalPort::success(vec![
            row(DOC_A, 0, "dense", 0.9),
            row(DOC_B, 0, "dense", 0.7),
        ]),
        FakeBm25RetrievalPort::with_map(vec![
            (
                "alpha".to_owned(),
                Ok(vec![row(DOC_A, 1, "bm25", 8.0), row(DOC_A, 0, "bm25", 6.0)]),
            ),
            (
                "beta".to_owned(),
                Ok(vec![row(DOC_A, 0, "bm25", 7.0), row(DOC_C, 1, "bm25", 5.0)]),
            ),
            (
                "gamma".to_owned(),
                Ok(vec![row(DOC_C, 1, "bm25", 9.0), row(DOC_B, 0, "bm25", 4.0)]),
            ),
        ]),
    )
}

/// Runs RetrieveHybrid over the given fakes. Returns the context and the dense fake, which
/// records the fetches made through it.
async fn run_node(
    dense: FakeDenseRetrievalPort,
    bm25: FakeBm25RetrievalPort,
    settings: RetrievalSettings,
    setup: impl FnOnce(&mut WorkflowContext),
) -> (WorkflowContext, Arc<FakeDenseRetrievalPort>) {
    let dense = Arc::new(dense);
    let node = RetrieveHybridNode::new(
        Some(Arc::clone(&dense) as Arc<dyn DenseRetrievalPort>),
        Some(Arc::new(bm25)),
        None,
        settings,
    );
    let mut ctx = new_context();
    setup(&mut ctx);
    node.run(&mut ctx, &CancellationToken::new())
        .await
        .expect("RetrieveHybrid must not fail");
    (ctx, dense)
}

fn flagged_chunks(ctx: &WorkflowContext) -> Vec<String> {
    ctx.evidence_blocks
        .iter()
        .filter(|block| block.graph_boosted)
        .map(|block| block.chunk_id.clone())
        .collect()
}

/// Captures the log lines emitted while the guard is alive on this thread.
#[derive(Clone)]
struct LogSink(Arc<Mutex<Vec<u8>>>);

impl std::io::Write for LogSink {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        self.0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

fn capture_logs() -> (tracing::subscriber::DefaultGuard, Arc<Mutex<Vec<u8>>>) {
    let sink = Arc::new(Mutex::new(Vec::new()));
    let writer = LogSink(Arc::clone(&sink));
    let subscriber = tracing_subscriber::fmt()
        .with_ansi(false)
        .with_writer(move || writer.clone())
        .finish();
    (tracing::subscriber::set_default(subscriber), sink)
}

fn captured(sink: &Arc<Mutex<Vec<u8>>>) -> String {
    String::from_utf8(
        sink.lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone(),
    )
    .expect("log output is UTF-8")
}

// ---- graph-off invariance, pinned against the node's output before this change ---------------

/// Recorded by running the node as it stood before the graph list existed (HEAD 8899b6b5 plus the
/// fusion change, which is inert without a list), over `single_variant_ports`.
const SINGLE_VARIANT_RECORDED: &str = "hash=a0143d4b4d422a290901dd00802d8d58ca47be7ede09594c52077c97f2cdacb5
variants=1
vector=00000000-0000-4000-8000-0000000000b1:0,00000000-0000-4000-8000-0000000000b1:1,00000000-0000-4000-8000-0000000000b2:0,00000000-0000-4000-8000-0000000000b3:0
bm25=00000000-0000-4000-8000-0000000000b2:0,00000000-0000-4000-8000-0000000000b1:0,00000000-0000-4000-8000-0000000000b3:1
final=00000000-0000-4000-8000-0000000000b1:0,00000000-0000-4000-8000-0000000000b2:0,00000000-0000-4000-8000-0000000000b1:1,00000000-0000-4000-8000-0000000000b3:1
notices=
00000000-0000-4000-8000-0000000000b1:0|3fa0a6c92bff7560|1
00000000-0000-4000-8000-0000000000b2:0|3fa0853aaffeef26|2
00000000-0000-4000-8000-0000000000b1:1|3f90842108421084|3
00000000-0000-4000-8000-0000000000b3:1|3f90410410410410|4";

/// Recorded the same way over `three_variant_ports` with the variants alpha, beta and gamma.
const THREE_VARIANT_RECORDED: &str = "hash=4bd7ea5baf3b8d2d69d3ddd82b8db259d562d27985ada45b5bda41bd0445d1f3
variants=3
vector=00000000-0000-4000-8000-0000000000b1:0,00000000-0000-4000-8000-0000000000b2:0
bm25=00000000-0000-4000-8000-0000000000b1:1,00000000-0000-4000-8000-0000000000b1:0,00000000-0000-4000-8000-0000000000b1:0,00000000-0000-4000-8000-0000000000b3:1,00000000-0000-4000-8000-0000000000b3:1,00000000-0000-4000-8000-0000000000b2:0
final=00000000-0000-4000-8000-0000000000b1:0,00000000-0000-4000-8000-0000000000b3:1,00000000-0000-4000-8000-0000000000b2:0,00000000-0000-4000-8000-0000000000b1:1
notices=
00000000-0000-4000-8000-0000000000b1:0|3fa0c9714fbcda3b|1
00000000-0000-4000-8000-0000000000b3:1|3fa0a6c92bff7560|2
00000000-0000-4000-8000-0000000000b2:0|3fa062928c418a4a|3
00000000-0000-4000-8000-0000000000b1:1|3f90842108421084|4";

#[tokio::test]
async fn graph_off_single_variant_outcome_matches_the_recorded_pre_change_output() {
    let (dense, bm25) = single_variant_ports();
    let (ctx, dense) = run_node(dense, bm25, pin_settings(), |_| {}).await;
    assert_eq!(render_outcome(&ctx), SINGLE_VARIANT_RECORDED);
    assert_eq!(ctx.graph_boosted_chunk_count, 0);
    assert!(flagged_chunks(&ctx).is_empty());
    assert!(dense.fetch_requests().is_empty(), "no graph candidates, no fetch");
}

#[tokio::test]
async fn a_stale_boosted_count_does_not_survive_a_graph_off_query() {
    let (dense, bm25) = single_variant_ports();
    let (ctx, _dense) = run_node(dense, bm25, pin_settings(), |ctx| {
        ctx.graph_boosted_chunk_count = 5;
    })
    .await;
    assert_eq!(ctx.graph_boosted_chunk_count, 0);
}

#[tokio::test]
async fn graph_off_three_variant_outcome_matches_the_recorded_pre_change_output() {
    let (dense, bm25) = three_variant_ports();
    let (ctx, dense) = run_node(dense, bm25, pin_settings(), |ctx| {
        ctx.variants = vec!["alpha".into(), "beta".into(), "gamma".into()];
    })
    .await;
    assert_eq!(render_outcome(&ctx), THREE_VARIANT_RECORDED);
    assert_eq!(ctx.graph_boosted_chunk_count, 0);
    assert!(flagged_chunks(&ctx).is_empty());
    assert!(dense.fetch_requests().is_empty());
}

#[tokio::test]
async fn candidates_offered_to_a_zero_graph_weight_leave_the_outcome_unchanged_and_are_not_fetched()
{
    let (dense, bm25) = single_variant_ports();
    let dense = dense.with_chunk_rows(vec![row(DOC_B, 3, "graph", 0.0)]);
    let settings = RetrievalSettings {
        graph_rrf_weight: 0.0,
        ..pin_settings()
    };
    let (ctx, dense) = run_node(dense, bm25, settings, |ctx| {
        ctx.graph_chunk_candidates = vec![chunk_id(DOC_B, 3)];
    })
    .await;
    assert_eq!(render_outcome(&ctx), SINGLE_VARIANT_RECORDED);
    assert_eq!(ctx.graph_boosted_chunk_count, 0);
    assert!(dense.fetch_requests().is_empty(), "an ignored list is not fetched");
}

// ---- the boost -------------------------------------------------------------------------------

#[tokio::test]
async fn a_graph_only_chunk_enters_the_retrieved_set_flagged_and_counted() {
    let dense = FakeDenseRetrievalPort::success(vec![
        row(DOC_A, 0, "dense", 0.9),
        row(DOC_A, 1, "dense", 0.8),
    ])
    .with_chunk_rows(vec![row(DOC_B, 3, "graph", 0.0)]);
    let (ctx, dense) = run_node(
        dense,
        FakeBm25RetrievalPort::success(vec![]),
        pin_settings(),
        |ctx| ctx.graph_chunk_candidates = vec![chunk_id(DOC_B, 3)],
    )
    .await;

    // The graph-only chunk scores what dense rank 1 scores, so it follows the dense chunk it
    // ties with and precedes the one below.
    assert_eq!(
        ctx.final_candidates,
        vec![chunk_id(DOC_A, 0), chunk_id(DOC_B, 3), chunk_id(DOC_A, 1)]
    );
    assert_eq!(flagged_chunks(&ctx), vec![chunk_id(DOC_B, 3)]);
    assert_eq!(ctx.graph_boosted_chunk_count, 1);
    let snapshot = ctx.snapshot.as_ref().unwrap();
    assert!(snapshot
        .retrieved_chunks
        .iter()
        .any(|chunk| chunk.chunk_id == chunk_id(DOC_B, 3)));
    assert_eq!(dense.fetch_requests(), vec![vec![chunk_id(DOC_B, 3)]]);
}

#[tokio::test]
async fn a_chunk_dense_also_found_is_boosted_once_and_moves_up() {
    let dense = FakeDenseRetrievalPort::success(vec![
        row(DOC_A, 0, "dense", 0.9),
        row(DOC_A, 1, "dense", 0.8),
        row(DOC_B, 0, "dense", 0.7),
    ])
    .with_chunk_rows(vec![row(DOC_B, 0, "graph", 0.0)]);
    let (ctx, _dense) = run_node(
        dense,
        FakeBm25RetrievalPort::success(vec![]),
        pin_settings(),
        |ctx| ctx.graph_chunk_candidates = vec![chunk_id(DOC_B, 0)],
    )
    .await;

    assert_eq!(
        ctx.final_candidates,
        vec![chunk_id(DOC_B, 0), chunk_id(DOC_A, 0), chunk_id(DOC_A, 1)],
        "dense rank 3 plus graph rank 1 outranks dense rank 1 alone, and the chunk appears once"
    );
    assert_eq!(flagged_chunks(&ctx), vec![chunk_id(DOC_B, 0)]);
    assert_eq!(ctx.graph_boosted_chunk_count, 1);
}

#[tokio::test]
async fn the_boosted_count_covers_the_final_retrieved_set_only() {
    let dense = FakeDenseRetrievalPort::success(vec![
        row(DOC_A, 0, "dense", 0.9),
        row(DOC_A, 1, "dense", 0.8),
    ])
    .with_chunk_rows(vec![row(DOC_B, 0, "graph", 0.0), row(DOC_B, 1, "graph", 0.0)]);
    let settings = RetrievalSettings {
        candidate_limit: 4,
        final_limit: 2,
        graph_rrf_weight: 0.1,
        ..RetrievalSettings::default()
    };
    let (ctx, dense) = run_node(
        dense,
        FakeBm25RetrievalPort::success(vec![
            row(DOC_A, 0, "bm25", 5.0),
            row(DOC_A, 1, "bm25", 4.0),
        ]),
        settings,
        |ctx| ctx.graph_chunk_candidates = vec![chunk_id(DOC_B, 0), chunk_id(DOC_B, 1)],
    )
    .await;

    assert_eq!(
        ctx.final_candidates,
        vec![chunk_id(DOC_A, 0), chunk_id(DOC_A, 1)],
        "two strong chunks fill the final set"
    );
    assert_eq!(dense.fetch_requests().len(), 1, "the graph chunks were still fetched");
    assert_eq!(ctx.graph_boosted_chunk_count, 0);
    assert!(flagged_chunks(&ctx).is_empty());
}

#[tokio::test]
async fn the_graph_list_is_fetched_once_and_applied_once_for_three_variants() {
    let (dense, bm25) = three_variant_ports();
    let dense = dense.with_chunk_rows(vec![row(DOC_B, 3, "graph", 0.0)]);
    let (ctx, dense) = run_node(dense, bm25, pin_settings(), |ctx| {
        ctx.variants = vec!["alpha".into(), "beta".into(), "gamma".into()];
        ctx.graph_chunk_candidates = vec![chunk_id(DOC_B, 3)];
    })
    .await;

    assert_eq!(dense.fetch_requests().len(), 1, "one fetch per query, not per variant");
    let snapshot = ctx.snapshot.as_ref().unwrap();
    let boosted = snapshot
        .retrieved_chunks
        .iter()
        .find(|chunk| chunk.chunk_id == chunk_id(DOC_B, 3))
        .expect("the graph-only chunk is in the retrieved set");
    assert_eq!(
        boosted.score,
        1.0 / 61.0,
        "its whole score is one graph contribution at rank 1, whatever the variant count"
    );
    assert_eq!(flagged_chunks(&ctx), vec![chunk_id(DOC_B, 3)]);
}

#[tokio::test]
async fn the_graph_node_hands_its_candidates_to_retrieval_through_the_context() {
    let embedding: Arc<dyn QueryEmbeddingPort> = Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 4]));
    let graph: Arc<dyn GraphQueryPort> = Arc::new(FakeGraphQueryPort::success_output(GraphQueryOutput {
        seed_count: 2,
        path_found: true,
        chunk_candidates: vec![chunk_id(DOC_B, 3)],
        ..GraphQueryOutput::default()
    }));
    let graph_node = ExtractGraphContextNode::new(Some(embedding), Some(graph));
    let dense = FakeDenseRetrievalPort::success(vec![row(DOC_A, 0, "dense", 0.9)])
        .with_chunk_rows(vec![row(DOC_B, 3, "graph", 0.0)]);
    let dense = Arc::new(dense);
    let retrieve_node = RetrieveHybridNode::new(
        Some(Arc::clone(&dense) as Arc<dyn DenseRetrievalPort>),
        Some(Arc::new(FakeBm25RetrievalPort::success(vec![]))),
        None,
        pin_settings(),
    );

    let mut ctx = new_context();
    let cancel = CancellationToken::new();
    graph_node.run(&mut ctx, &cancel).await.unwrap();
    retrieve_node.run(&mut ctx, &cancel).await.unwrap();

    assert_eq!(flagged_chunks(&ctx), vec![chunk_id(DOC_B, 3)]);
    assert_eq!(ctx.graph_boosted_chunk_count, 1);
}

// ---- candidate IDs ---------------------------------------------------------------------------

#[test]
fn only_a_canonical_lower_case_v4_uuid_and_an_unsigned_index_is_a_chunk_id() {
    let valid = [
        format!("{DOC_A}:0"),
        format!("{DOC_A}:12"),
        format!("{DOC_A}:2147483647"),
        "123e4567-e89b-42d3-a456-426614174000:7".to_owned(),
    ];
    for id in &valid {
        assert!(is_valid_chunk_id(id), "{id} must be accepted");
    }
    let upper = format!("{}:1", DOC_A.to_uppercase());
    let simple = format!("{}:1", DOC_A.replace('-', ""));
    let braced = format!("{{{DOC_A}}}:1");
    let urn = format!("urn:uuid:{DOC_A}:1");
    let version_one = "00000000-0000-1000-8000-0000000000b1:1".to_owned();
    let other_variant = "00000000-0000-4000-c000-0000000000b1:1".to_owned();
    let invalid = [
        String::new(),
        ":".to_owned(),
        DOC_A.to_owned(),
        format!("{DOC_A}:"),
        format!(":{DOC_A}"),
        format!("{DOC_A}:+3"),
        format!("{DOC_A}:-1"),
        format!("{DOC_A}:1.5"),
        format!("{DOC_A}:03"),
        format!("{DOC_A}:2147483648"),
        format!("{DOC_A}:99999999999999999999"),
        format!("{DOC_A}:1:2"),
        format!("{DOC_A}:1 "),
        format!(" {DOC_A}:1"),
        format!("{DOC_A}:1'"),
        format!("{DOC_A}'--:1"),
        "x' OR '1'='1".to_owned(),
        "not-an-id".to_owned(),
        upper,
        simple,
        braced,
        urn,
        version_one,
        other_variant,
    ];
    for id in &invalid {
        assert!(!is_valid_chunk_id(id), "{id:?} must be rejected");
    }
}

#[tokio::test]
async fn malformed_candidate_ids_are_dropped_before_the_fetch_and_logged_without_their_text() {
    let (_guard, sink) = capture_logs();
    let dense = FakeDenseRetrievalPort::success(vec![row(DOC_A, 0, "dense", 0.9)])
        .with_chunk_rows(vec![row(DOC_B, 3, "graph", 0.0)]);
    let (ctx, dense) = run_node(
        dense,
        FakeBm25RetrievalPort::success(vec![]),
        pin_settings(),
        |ctx| {
            ctx.graph_chunk_candidates = vec![
                chunk_id(DOC_B, 3),
                "x' OR '1'='1".to_owned(),
                "not-an-id".to_owned(),
                format!("{}:1", DOC_B.to_uppercase()),
                String::new(),
            ];
        },
    )
    .await;

    assert_eq!(
        dense.fetch_requests(),
        vec![vec![chunk_id(DOC_B, 3)]],
        "only the valid ID reaches the port"
    );
    assert_eq!(flagged_chunks(&ctx), vec![chunk_id(DOC_B, 3)]);
    let log = captured(&sink);
    assert!(log.contains("WARN"), "the drop is a warning: {log}");
    assert!(log.contains("dropped_count=4"), "the log counts the dropped IDs: {log}");
    for text in ["OR '1'", "not-an-id", &DOC_B.to_uppercase()] {
        assert!(!log.contains(text), "the log must not carry ID text {text:?}: {log}");
    }
}

#[tokio::test]
async fn when_every_candidate_is_malformed_nothing_is_fetched() {
    let (_guard, _sink) = capture_logs();
    let (dense, bm25) = single_variant_ports();
    let dense = dense.with_chunk_rows(vec![row(DOC_B, 3, "graph", 0.0)]);
    let (ctx, dense) = run_node(dense, bm25, pin_settings(), |ctx| {
        ctx.graph_chunk_candidates = vec!["x' OR '1'='1".to_owned(), "nope".to_owned()];
    })
    .await;
    assert!(dense.fetch_requests().is_empty());
    assert_eq!(render_outcome(&ctx), SINGLE_VARIANT_RECORDED);
}

#[tokio::test]
async fn a_repeated_candidate_id_is_fetched_once() {
    let dense = FakeDenseRetrievalPort::success(vec![row(DOC_A, 0, "dense", 0.9)])
        .with_chunk_rows(vec![row(DOC_B, 3, "graph", 0.0), row(DOC_B, 4, "graph", 0.0)]);
    let (_ctx, dense) = run_node(
        dense,
        FakeBm25RetrievalPort::success(vec![]),
        pin_settings(),
        |ctx| {
            ctx.graph_chunk_candidates = vec![
                chunk_id(DOC_B, 3),
                chunk_id(DOC_B, 3),
                chunk_id(DOC_B, 4),
            ];
        },
    )
    .await;
    assert_eq!(
        dense.fetch_requests(),
        vec![vec![chunk_id(DOC_B, 3), chunk_id(DOC_B, 4)]]
    );
}

// ---- failure and filters ---------------------------------------------------------------------

#[tokio::test]
async fn a_fetch_failure_degrades_to_the_graph_off_outcome_with_a_warning() {
    let (_guard, sink) = capture_logs();
    let (dense, bm25) = single_variant_ports();
    let secret_id = chunk_id(DOC_B, 3);
    let dense = dense.with_fetch_failure(NodeError::new(
        NodeErrorKind::RetrievalFailed,
        format!("lance exploded near {secret_id}"),
    ));
    let (ctx, dense) = run_node(dense, bm25, pin_settings(), |ctx| {
        ctx.graph_chunk_candidates = vec![secret_id.clone()];
    })
    .await;

    assert_eq!(dense.fetch_requests().len(), 1, "the fetch was attempted");
    assert_eq!(render_outcome(&ctx), SINGLE_VARIANT_RECORDED);
    assert_eq!(ctx.graph_boosted_chunk_count, 0);
    let log = captured(&sink);
    assert!(log.contains("WARN"), "the failure is a warning: {log}");
    assert!(
        !log.contains(&secret_id) && !log.contains("lance exploded"),
        "the log carries neither the ID nor the provider message: {log}"
    );
}

#[tokio::test]
async fn graph_chunks_outside_the_request_filter_never_enter() {
    let rows = vec![
        row(DOC_B, 3, "graph", 0.0),
        row(DOC_A, 5, "graph", 0.0),
        {
            let mut json = row(DOC_A, 6, "graph", 0.0);
            json.content_type = Some("application/json".to_owned());
            json
        },
    ];
    let candidates = vec![chunk_id(DOC_B, 3), chunk_id(DOC_A, 5), chunk_id(DOC_A, 6)];

    // A document filter: the chunk of another document is dropped, both of this one stay.
    let dense = FakeDenseRetrievalPort::success(vec![row(DOC_A, 0, "dense", 0.9)])
        .with_chunk_rows(rows.clone());
    let by_document = run_node(
        dense,
        FakeBm25RetrievalPort::success(vec![]),
        pin_settings(),
        |ctx| {
            ctx.filter = Some(DocumentFilter {
                document_ids: vec![DOC_A.to_owned()],
                content_types: vec![],
            });
            ctx.graph_chunk_candidates = candidates.clone();
        },
    )
    .await
    .0;
    assert_eq!(
        flagged_chunks(&by_document),
        vec![chunk_id(DOC_A, 5), chunk_id(DOC_A, 6)]
    );
    assert!(!by_document.final_candidates.contains(&chunk_id(DOC_B, 3)));

    // A content-type filter: only the plain-text chunk of that document stays.
    let dense =
        FakeDenseRetrievalPort::success(vec![row(DOC_A, 0, "dense", 0.9)]).with_chunk_rows(rows);
    let by_type = run_node(
        dense,
        FakeBm25RetrievalPort::success(vec![]),
        pin_settings(),
        |ctx| {
            ctx.filter = Some(DocumentFilter {
                document_ids: vec![DOC_A.to_owned()],
                content_types: vec!["text/plain".to_owned()],
            });
            ctx.graph_chunk_candidates = candidates.clone();
        },
    )
    .await
    .0;
    assert_eq!(flagged_chunks(&by_type), vec![chunk_id(DOC_A, 5)]);
}

// ---- the retrieved chunk representation ------------------------------------------------------

#[test]
fn an_evidence_block_carries_graph_provenance_without_changing_the_prompt_text() {
    use crate::prompt::{encode_evidence_block, EvidenceBlock};
    use crate::retrieval::{fuse_candidates, fuse_cross_variant_candidates};

    let settings = RetrievalSettings::default();
    let dense = fuse_candidates(vec![row(DOC_A, 0, "dense", 0.9)], vec![], &settings).unwrap();
    let fused = fuse_cross_variant_candidates(
        vec![dense],
        vec![row(DOC_A, 0, "graph", 0.0), row(DOC_B, 3, "graph", 0.0)],
        &settings,
    )
    .unwrap();
    let blocks: Vec<EvidenceBlock> = crate::prompt::assemble_evidence_blocks(&fused);
    assert!(blocks.iter().all(|block| block.graph_boosted));

    let plain = fuse_candidates(vec![row(DOC_A, 0, "dense", 0.9)], vec![], &settings).unwrap();
    let unflagged = crate::prompt::assemble_evidence_blocks(&plain);
    assert!(!unflagged[0].graph_boosted);

    // The prompt text of a block does not depend on the flag.
    let mut cleared = blocks[0].clone();
    cleared.graph_boosted = false;
    assert_eq!(
        encode_evidence_block(&blocks[0]).render_prompt_block(),
        encode_evidence_block(&cleared).render_prompt_block()
    );

    // A checkpoint omits the key when it is false, so a graph-off query serialises as before.
    let plain_json = serde_json::to_string(&unflagged[0]).unwrap();
    assert!(!plain_json.contains("graph_boosted"), "{plain_json}");
    let flagged_json = serde_json::to_string(&blocks[0]).unwrap();
    assert!(flagged_json.contains("\"graph_boosted\":true"), "{flagged_json}");
    let round_trip: EvidenceBlock = serde_json::from_str(&plain_json).unwrap();
    assert!(!round_trip.graph_boosted);
}

// ---- the production port over a store --------------------------------------------------------

fn store_path(name: &str) -> String {
    std::env::temp_dir()
        .join(format!("lancet-graphboost-{name}-{}", Uuid::new_v4()))
        .to_string_lossy()
        .into_owned()
}

/// Appends one `nodes` row per `(document, index, content)`.
async fn add_node_rows(nodes: &lancedb::Table, rows: &[(&str, i32, &str)]) {
    let schema = nodes.schema().await.unwrap();
    let count = rows.len();
    let embeddings = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
        (0..count).map(|_| Some(vec![Some(0.5_f32); 2048])).collect::<Vec<_>>(),
        2048,
    );
    let nullable = |name: &str| {
        new_null_array(schema.field_with_name(name).unwrap().data_type(), count)
    };
    let documents: Vec<Option<&str>> = rows.iter().map(|row| Some(row.0)).collect();
    let chunk_ids: Vec<String> = rows.iter().map(|row| chunk_id(row.0, row.1)).collect();
    let contents: Vec<Option<&str>> = rows.iter().map(|row| Some(row.2)).collect();
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from(documents)),
            Arc::new(StringArray::from(
                chunk_ids.iter().map(|id| Some(id.as_str())).collect::<Vec<_>>(),
            )),
            Arc::new(Int32Array::from(rows.iter().map(|row| row.1).collect::<Vec<_>>())),
            Arc::new(Int32Array::from(vec![0; count])),
            Arc::new(Int32Array::from(vec![10; count])),
            Arc::new(StringArray::from(contents)),
            Arc::new(embeddings),
            Arc::new(Int32Array::from(vec![4; count])),
            Arc::new(StringArray::from(vec![Some("o200k_base"); count])),
            Arc::new(StringArray::from(vec![Some("1"); count])),
            Arc::new(StringArray::from(vec![Some("Title"); count])),
            Arc::new(StringArray::from(vec![Some("Root"); count])),
            nullable("page_start"),
            nullable("page_end"),
            nullable("content_hash"),
            nullable("chunker_version"),
            Arc::new(StringArray::from(vec![Some("test-model"); count])),
            Arc::new(Int64Array::from(vec![Some(42); count])),
            Arc::new(StringArray::from(vec![Some("text/plain"); count])),
        ],
    )
    .unwrap();
    nodes.add(batch).execute().await.unwrap();
}

fn port_at(database: &DatabaseManager, nodes_version: u64) -> ProductionDenseRetrievalPort {
    ProductionDenseRetrievalPort {
        database: database.clone(),
        nodes_version,
        retrieval_settings: RetrievalSettings::default(),
    }
}

#[tokio::test]
async fn the_production_fetch_reads_the_pinned_nodes_version_not_the_latest() {
    let path = store_path("pinned");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let nodes = database.nodes_table().await.unwrap();

    add_node_rows(&nodes, &[(DOC_A, 0, "first generation")]).await;
    let first = nodes.version().await.unwrap();

    // A later generation replaces the chunk's content and adds a chunk that did not exist.
    nodes
        .delete(&format!("chunk_id = '{}'", chunk_id(DOC_A, 0)))
        .await
        .unwrap();
    add_node_rows(
        &nodes,
        &[(DOC_A, 0, "second generation"), (DOC_B, 1, "only later")],
    )
    .await;
    let latest = nodes.version().await.unwrap();
    assert!(latest > first);

    let cancel = CancellationToken::new();
    let ids = vec![chunk_id(DOC_A, 0), chunk_id(DOC_B, 1)];

    let at_first = port_at(&database, first)
        .fetch_chunks_by_id(&ids, &cancel)
        .await
        .unwrap();
    assert_eq!(
        at_first.iter().map(|c| c.content.as_str()).collect::<Vec<_>>(),
        vec!["first generation"],
        "the snapshot's version has the old content and not the later chunk"
    );

    let at_latest = port_at(&database, latest)
        .fetch_chunks_by_id(&ids, &cancel)
        .await
        .unwrap();
    assert_eq!(
        at_latest.iter().map(|c| c.content.as_str()).collect::<Vec<_>>(),
        vec!["second generation", "only later"]
    );

    drop(database);
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn the_production_fetch_returns_rows_in_request_order_and_skips_missing_ids() {
    let path = store_path("order");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let nodes = database.nodes_table().await.unwrap();
    add_node_rows(
        &nodes,
        &[(DOC_A, 0, "a0"), (DOC_B, 1, "b1"), (DOC_C, 2, "c2")],
    )
    .await;
    let version = nodes.version().await.unwrap();

    let rows = port_at(&database, version)
        .fetch_chunks_by_id(
            &[chunk_id(DOC_C, 2), chunk_id(DOC_A, 9), chunk_id(DOC_A, 0)],
            &CancellationToken::new(),
        )
        .await
        .unwrap();
    assert_eq!(
        rows.iter().map(|c| c.chunk_id.clone()).collect::<Vec<_>>(),
        vec![chunk_id(DOC_C, 2), chunk_id(DOC_A, 0)]
    );
    assert_eq!(rows[0].document_id, DOC_C);
    assert_eq!(rows[0].chunk_index, 2);
    assert_eq!(rows[0].content, "c2");
    assert_eq!(rows[0].content_type.as_deref(), Some("text/plain"));
    assert!(rows[0].score.is_finite());

    drop(database);
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn the_production_fetch_refuses_a_malformed_id_without_reading_any_row() {
    let path = store_path("malformed");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let nodes = database.nodes_table().await.unwrap();
    add_node_rows(&nodes, &[(DOC_A, 0, "a0")]).await;
    let version = nodes.version().await.unwrap();
    let port = port_at(&database, version);
    let cancel = CancellationToken::new();

    for bad in ["x' OR '1'='1", "not-an-id", ""] {
        let only_bad = port.fetch_chunks_by_id(&[bad.to_owned()], &cancel).await;
        assert!(only_bad.is_err(), "{bad:?} must be refused");
        let mixed = port
            .fetch_chunks_by_id(&[chunk_id(DOC_A, 0), bad.to_owned()], &cancel)
            .await;
        assert!(mixed.is_err(), "one bad ID refuses the whole call: {bad:?}");
    }
    assert_eq!(
        port.fetch_chunks_by_id(&[], &cancel).await.unwrap().len(),
        0,
        "an empty request reads nothing"
    );

    drop(database);
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn the_production_fetch_leaves_the_dense_substage_timings_alone() {
    use crate::workflow::nodes::retrieve::{DenseSubStageTimings, DENSE_SUBSTAGE_TIMINGS};

    let path = store_path("timings");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let nodes = database.nodes_table().await.unwrap();
    add_node_rows(&nodes, &[(DOC_A, 0, "a0")]).await;
    let version = nodes.version().await.unwrap();
    let port = port_at(&database, version);

    let after = DENSE_SUBSTAGE_TIMINGS
        .scope(
            Cell::new(DenseSubStageTimings {
                open_table_ms: 7.0,
                checkout_ms: 9.0,
            }),
            async {
                let cancel = CancellationToken::new();
                let rows = port
                    .fetch_chunks_by_id(&[chunk_id(DOC_A, 0)], &cancel)
                    .await
                    .unwrap();
                assert_eq!(rows.len(), 1);
                DENSE_SUBSTAGE_TIMINGS.with(|cell| cell.get())
            },
        )
        .await;
    assert_eq!(after.open_table_ms, 7.0, "the dense search's timings are not overwritten");
    assert_eq!(after.checkout_ms, 9.0);

    drop(database);
    let _ = std::fs::remove_dir_all(path);
}
