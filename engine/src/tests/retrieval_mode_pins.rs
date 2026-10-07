//! Byte-identity pin for the default request through the retrieval node chain
//! (Phase 06.3.5, D-99, D-100).
//!
//! `retrieval/testdata/graph_off_fusion.golden` pins fusion only and never runs
//! `RetrieveHybridNode`, so it cannot show that the default request stays byte-identical once a
//! retrieval mode exists, or that a flag-on ranking leaves the node output unchanged. The golden
//! here is a node-level baseline: `ExtractGraphContextNode`, then `RetrieveHybridNode`, then
//! `AssemblePromptNode` over the existing fakes, graph off and graph on, plus one full
//! `WorkflowRunner` run with `FakeGenerator`.
//!
//! Recording rule: the golden was recorded once at the pre-change HEAD named in the pin's
//! provenance comment, before any engine or proto edit of Phase 06.3.5. It is never regenerated
//! from the code under test; a later change that moves it is a behaviour change to be justified,
//! not a snapshot to refresh. The renderer uses only symbols that existed at that HEAD.

use std::fmt::Write as _;
use std::sync::Arc;

use prost::Message;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::generation::{AnswerBasis, FakeGenerator, ModelOutput};
use crate::pb::lancet::v1::{workflow_event::Event, WorkflowCompletedEvent};
use crate::prompt::{DEFAULT_ANSWER_TOKEN_BUDGET, DEFAULT_MAX_PROMPT_TOKENS};
use crate::retrieval::{Candidate, RetrievalSettings};
use crate::testkit::test_query_request;
use crate::workflow::events::EventSequence;
use crate::workflow::node::Node;
use crate::workflow::nodes::{
    AssemblePromptNode, ExtractGraphContextNode, GenerateAnswerNode, RetrieveHybridNode,
};
use crate::workflow::ports::{
    FakeBm25RetrievalPort, FakeDenseRetrievalPort, FakeGraphQueryPort, FakeQueryEmbeddingPort,
    GraphQueryOutput,
};
use crate::workflow::{WorkflowContext, WorkflowEventSink, WorkflowRunner};

const DOC_A: &str = "00000000-0000-4000-8000-0000000000d1";
const DOC_B: &str = "00000000-0000-4000-8000-0000000000d2";

fn row(doc: &str, index: i32, score: f64) -> Candidate {
    Candidate {
        document_id: doc.to_owned(),
        chunk_id: format!("{doc}:{index}"),
        chunk_index: index,
        char_start: 0,
        char_end: 10,
        content: format!("content of {doc} {index}"),
        title: Some("Title".to_owned()),
        section_path: None,
        content_type: Some("text/plain".to_owned()),
        embedding_model: Some("test-model".to_owned()),
        ingested_at: Some(1),
        score,
    }
}

/// Dense finds `A:0 A:1 A:2 A:3`, BM25 finds `A:1 B:1 B:0 A:0`. `A:1` and `A:0` are found by both
/// paths. `A:2` (dense rank 3 only) and `B:0` (BM25 rank 3 only) fuse to the exact same score,
/// and only one of them survives the final limit of four, so the tie-break is pinned too.
fn dense_port() -> Arc<FakeDenseRetrievalPort> {
    Arc::new(
        FakeDenseRetrievalPort::success(vec![
            row(DOC_A, 0, 0.9),
            row(DOC_A, 1, 0.8),
            row(DOC_A, 2, 0.7),
            row(DOC_A, 3, 0.6),
        ])
        // Reachable only through the by-ID fetch, so it enters the set only through the graph.
        .with_chunk_rows(vec![row(DOC_B, 3, 0.0)]),
    )
}

fn bm25_port() -> Arc<FakeBm25RetrievalPort> {
    Arc::new(FakeBm25RetrievalPort::success(vec![
        row(DOC_A, 1, 9.0),
        row(DOC_B, 1, 8.0),
        row(DOC_B, 0, 7.0),
        row(DOC_A, 0, 6.0),
    ]))
}

/// What the graph port reports for a query whose seeds were joined by a path to chunk `B:3`.
fn path_output() -> GraphQueryOutput {
    GraphQueryOutput {
        seed_count: 2,
        path_found: true,
        degree_capped_count: 3,
        seed_document_ids: vec![DOC_A.to_owned(), DOC_B.to_owned()],
        chunk_candidates: vec![format!("{DOC_B}:3")],
        ..GraphQueryOutput::default()
    }
}

fn settings() -> RetrievalSettings {
    RetrievalSettings {
        candidate_limit: 12,
        final_limit: 4,
        ..RetrievalSettings::default()
    }
}

fn retrieve_node() -> RetrieveHybridNode {
    RetrieveHybridNode::new(Some(dense_port()), Some(bm25_port()), None, settings())
        .with_snapshot_metadata("lance-1", "test-model")
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// Everything the node chain left on the context that the wire or the prompt can show, with every
/// float as its exact bit pattern.
fn render_context(ctx: &WorkflowContext) -> String {
    let mut out = String::new();
    writeln!(out, "dense: {}", ctx.vector_results.join(",")).unwrap();
    writeln!(out, "bm25: {}", ctx.bm25_results.join(",")).unwrap();
    writeln!(out, "final: {}", ctx.final_candidates.join(",")).unwrap();
    for block in &ctx.evidence_blocks {
        writeln!(
            out,
            "block|{}|{}|{}|{}|{:?}|{:?}|{:?}|{}|{}|{:016x}|{}|{}|{}",
            block.id,
            block.chunk_id,
            block.document_id,
            block.chunk_index,
            block.title,
            block.section_path,
            block.content_type,
            block.provenance,
            block.text,
            block.score.to_bits(),
            block.rank,
            block.suspicious,
            block.graph_boosted
        )
        .unwrap();
    }
    writeln!(out, "prompt:\n{}", ctx.assembled_prompt).unwrap();
    let codes: Vec<&str> = ctx
        .notices
        .iter()
        .map(|notice| notice.code.as_str())
        .collect();
    writeln!(out, "notices: {}", codes.join(",")).unwrap();
    let snapshot = ctx
        .snapshot
        .as_ref()
        .expect("RetrieveHybrid leaves a snapshot on the context");
    writeln!(out, "snapshot: {}", hex(&snapshot.encode_to_vec())).unwrap();
    out
}

/// Runs `ExtractGraphContext`, `RetrieveHybrid` and `AssemblePrompt` in order, node by node.
async fn node_chain(disable_graph: bool) -> String {
    let mut request = test_query_request("alpha", "sess-pin");
    request.disable_graph_context = Some(disable_graph);
    let mut ctx = WorkflowContext::new("sess-pin".to_owned(), "trace-pin".to_owned(), &request);
    let cancel = CancellationToken::new();

    let extract = ExtractGraphContextNode::new(
        Some(Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 2048]))),
        Some(Arc::new(FakeGraphQueryPort::success_output(path_output()))),
    );
    extract
        .run(&mut ctx, &cancel)
        .await
        .expect("extract graph context");
    retrieve_node()
        .run(&mut ctx, &cancel)
        .await
        .expect("retrieve hybrid");
    AssemblePromptNode::with_settings(DEFAULT_MAX_PROMPT_TOKENS, DEFAULT_ANSWER_TOKEN_BUDGET, 1.0)
        .run(&mut ctx, &cancel)
        .await
        .expect("assemble prompt");
    render_context(&ctx)
}

/// The whole workflow over the same fakes, graph on, rendering the final response only. The
/// terminal event's `WorkflowMetadata` carries timings and is left out.
async fn runner_final_response() -> String {
    let (tx, mut rx) = mpsc::channel(100);
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-pin".to_owned(),
        "sess-pin".to_owned(),
    );
    let request = test_query_request("alpha", "sess-pin");
    let ctx = WorkflowContext::new("sess-pin".to_owned(), "trace-pin".to_owned(), &request);

    let mut runner = WorkflowRunner::new();
    runner.add_node(ExtractGraphContextNode::new(
        Some(Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 2048]))),
        Some(Arc::new(FakeGraphQueryPort::success_output(path_output()))),
    ));
    runner.add_node(retrieve_node());
    runner.add_node(AssemblePromptNode::with_settings(
        DEFAULT_MAX_PROMPT_TOKENS,
        DEFAULT_ANSWER_TOKEN_BUDGET,
        1.0,
    ));
    runner.add_node(GenerateAnswerNode::new(Some(Arc::new(FakeGenerator::new(
        Ok(ModelOutput {
            answer: "An answer [1].".to_owned(),
            cited_evidence_ids: vec!["[1]".to_owned()],
            answer_basis: AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            final_answer: None,
            usage: None,
        }),
    )))));
    runner
        .run_workflow(ctx, CancellationToken::new(), sink)
        .await;

    let mut completed: Option<WorkflowCompletedEvent> = None;
    while let Ok(item) = rx.try_recv() {
        if let Ok(event) = item {
            if let Some(Event::WorkflowCompleted(wc)) = event.event {
                completed = Some(wc);
            }
        }
    }
    let completed = completed.expect("the workflow emits a terminal event");
    assert!(completed.success, "{}", completed.error_message);
    let response = completed
        .final_response
        .expect("a successful run carries a final response");
    format!("final_response: {}\n", hex(&response.encode_to_vec()))
}

/// The three default-request scenarios, framed `== <name> ==` as `graph_off_fusion` frames its own.
async fn render_default_scenarios() -> String {
    let mut current = String::new();
    for (name, rendered) in [
        ("graph_off_node_chain", node_chain(true).await),
        ("graph_on_node_chain", node_chain(false).await),
        ("runner_final_response", runner_final_response().await),
    ] {
        current.push_str(&format!("== {name} ==\n{rendered}\n"));
    }
    current
}

// ---------------------------------------------------------------------------
// The default request through the node chain (Phase 06.3.5 plan 01, D-99, D-100)
//
// `retrieval/testdata/retrieve_node_default.golden` was recorded by running the node chain above
// as it stood at 00fed3e424832650d2103b51b83f50b9335be1c4, before `retrieval_mode` existed and before any
// 06.3.5 engine or proto edit. The expected text is never rebuilt from the code under test.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn default_request_node_chain_is_byte_identical_to_the_recorded_pre_change_output() {
    let golden =
        include_str!("../retrieval/testdata/retrieve_node_default.golden").replace("\r\n", "\n");
    assert_eq!(
        render_default_scenarios().await,
        golden,
        "the default request through the node chain (== graph_off_node_chain ==, \
         == graph_on_node_chain ==, == runner_final_response ==) must match the output recorded \
         before retrieval_mode existed"
    );
}
