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
//! not a snapshot to refresh. A default `Variation` renders exactly what the renderer rendered at
//! that HEAD; the later tests change only the request and, where a variation adds a snapshot field,
//! zero that field before rendering, so the same golden proves the variation changed nothing else.

use std::fmt::Write as _;
use std::sync::Arc;
use std::time::Duration;

use prost::Message;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::doc_meta::DocMetaMap;
use crate::generation::{AnswerBasis, FakeGenerator, ModelOutput};
use crate::pb::lancet::v1::{
    workflow_event::Event, QueryRagRequest, RetrievalMode, RetrievalSnapshot,
    WorkflowCompletedEvent,
};
use crate::prompt::{DEFAULT_ANSWER_TOKEN_BUDGET, DEFAULT_MAX_PROMPT_TOKENS};
use crate::rerank::Reranker;
use crate::retrieval::{
    fuse_candidates, fuse_cross_variant_candidates, Candidate, RetrievalSettings,
};
use crate::testkit::test_query_request;
use crate::workflow::events::EventSequence;
use crate::workflow::node::Node;
use crate::workflow::nodes::{
    AssemblePromptNode, ExtractGraphContextNode, GenerateAnswerNode, RetrieveHybridNode,
};
use crate::workflow::ports::{
    FakeBm25RetrievalPort, FakeDenseRetrievalPort, FakeGraphQueryPort, FakeQueryEmbeddingPort,
    FakeReranker, GraphQueryOutput,
};
use crate::workflow::{LeverSet, WorkflowContext, WorkflowEventSink, WorkflowRunner};

pub(super) const DOC_A: &str = "00000000-0000-4000-8000-0000000000d1";
pub(super) const DOC_B: &str = "00000000-0000-4000-8000-0000000000d2";

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
fn dense_rows() -> Vec<Candidate> {
    vec![
        row(DOC_A, 0, 0.9),
        row(DOC_A, 1, 0.8),
        row(DOC_A, 2, 0.7),
        row(DOC_A, 3, 0.6),
    ]
}

fn bm25_rows() -> Vec<Candidate> {
    vec![
        row(DOC_A, 1, 9.0),
        row(DOC_B, 1, 8.0),
        row(DOC_B, 0, 7.0),
        row(DOC_A, 0, 6.0),
    ]
}

fn dense_port() -> Arc<FakeDenseRetrievalPort> {
    Arc::new(
        FakeDenseRetrievalPort::success(dense_rows())
            // Reachable only through the by-ID fetch, so it enters the set only through the graph.
            .with_chunk_rows(vec![row(DOC_B, 3, 0.0)]),
    )
}

fn bm25_port() -> Arc<FakeBm25RetrievalPort> {
    Arc::new(FakeBm25RetrievalPort::success(bm25_rows()))
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

pub(super) fn hex(bytes: &[u8]) -> String {
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

/// How a scenario's request differs from the default request (D-99, D-100).
#[derive(Clone, Copy)]
pub(super) struct Variation {
    mode: RetrievalMode,
    include_ranking: bool,
    /// The raw `levers` the request names (06.3.6 D-136); empty is the default request.
    levers: &'static [i32],
    /// Serve the `rerank` lever from an identity reranker whose scores equal the fused scores
    /// (06.3.6 D-166), so the lever output must equal the lever-free output.
    identity_lever: bool,
    /// Zero the snapshot fields a variation adds (the mode echo, the ranking and the lever echo)
    /// before rendering, so what is compared is everything the variation must NOT change.
    strip_additions: bool,
}

impl Variation {
    pub(super) const DEFAULT: Self = Self {
        mode: RetrievalMode::Unspecified,
        include_ranking: false,
        levers: &[],
        identity_lever: false,
        strip_additions: false,
    };

    fn mode(mode: RetrievalMode) -> Self {
        Self {
            mode,
            ..Self::DEFAULT
        }
    }

    /// The same variation with `levers` set explicitly on the request, as a client would send it.
    pub(super) fn with_levers(self, levers: &'static [i32]) -> Self {
        Self { levers, ..self }
    }

    /// The same variation with the `rerank` lever served by an identity reranker.
    pub(super) fn with_identity_lever(self) -> Self {
        Self {
            identity_lever: true,
            ..self
        }
    }

    pub(super) fn with_ranking(self) -> Self {
        Self {
            include_ranking: true,
            ..self
        }
    }

    pub(super) fn stripped(self) -> Self {
        Self {
            strip_additions: true,
            ..self
        }
    }

    fn apply(&self, request: &mut QueryRagRequest) {
        request.retrieval_mode = self.mode as i32;
        request.include_pre_truncation_ranking = self.include_ranking;
        request.levers = self.levers.to_vec();
    }

    fn strip(&self, snapshot: &mut RetrievalSnapshot) {
        if self.strip_additions {
            snapshot.retrieval_mode = 0;
            snapshot.pre_truncation_ranking.clear();
            snapshot.levers.clear();
        }
    }
}

/// The fakes and settings one node-chain run uses, kept so a test can read their call counts.
pub(super) struct Fixture {
    embedding: Arc<FakeQueryEmbeddingPort>,
    dense: Arc<FakeDenseRetrievalPort>,
    bm25: Arc<FakeBm25RetrievalPort>,
    settings: RetrievalSettings,
    variants: Vec<String>,
    /// The service-wide reranker of the strict, lever-free path; `None` is the recorded fixture.
    reranker: Option<Arc<dyn Reranker>>,
    /// The `rerank` lever reranker, its own time limit and the node budget it nests in.
    lever: Option<(Arc<dyn Reranker>, Duration, Duration)>,
    /// The snapshot's per-document metadata (06.3.6 D-142); `None` is the recorded fixture.
    doc_meta: Option<Arc<DocMetaMap>>,
}

impl Fixture {
    /// The fixture the golden was recorded over.
    pub(super) fn recorded() -> Self {
        Self {
            embedding: Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 2048])),
            dense: dense_port(),
            bm25: bm25_port(),
            settings: settings(),
            variants: Vec::new(),
            reranker: None,
            lever: None,
            doc_meta: None,
        }
    }

    /// The same fixture over a snapshot that holds `doc_meta`.
    pub(super) fn with_doc_meta(self, doc_meta: Arc<DocMetaMap>) -> Self {
        Self {
            doc_meta: Some(doc_meta),
            ..self
        }
    }

    /// The same fixture with a service-wide reranker on the strict path.
    pub(super) fn with_reranker(self, reranker: Arc<dyn Reranker>) -> Self {
        Self {
            reranker: Some(reranker),
            ..self
        }
    }

    /// The same fixture with the `rerank` lever served by `reranker`.
    pub(super) fn with_lever(
        self,
        reranker: Arc<dyn Reranker>,
        rerank_timeout: Duration,
        node_budget: Duration,
    ) -> Self {
        Self {
            lever: Some((reranker, rerank_timeout, node_budget)),
            ..self
        }
    }

    /// The recorded fixture, with an identity lever reranker when `variation` asks for one.
    fn for_variation(variation: Variation) -> Self {
        let fixture = Self::recorded();
        if variation.identity_lever {
            fixture.with_lever(
                Arc::new(FakeReranker::success()),
                Duration::from_millis(1706),
                Duration::from_millis(2500),
            )
        } else {
            fixture
        }
    }

    fn retrieve_node(&self) -> RetrieveHybridNode {
        let node = RetrieveHybridNode::new(
            Some(self.dense.clone()),
            Some(self.bm25.clone()),
            self.reranker.clone(),
            self.settings.clone(),
        )
        .with_snapshot_metadata("lance-1", "test-model");
        let node = match &self.doc_meta {
            Some(doc_meta) => node.with_doc_meta(Arc::clone(doc_meta)),
            None => node,
        };
        match &self.lever {
            Some((reranker, timeout, budget)) => {
                node.with_rerank_lever(Some(reranker.clone()), *timeout, *budget)
            }
            None => node,
        }
    }
}

/// Runs `ExtractGraphContext`, `RetrieveHybrid` and `AssemblePrompt` in order, node by node, and
/// returns the context they left behind.
pub(super) async fn run_chain(
    fixture: &Fixture,
    disable_graph: bool,
    variation: Variation,
) -> WorkflowContext {
    let mut request = test_query_request("alpha", "sess-pin");
    request.disable_graph_context = Some(disable_graph);
    variation.apply(&mut request);
    let mut ctx = WorkflowContext::new("sess-pin".to_owned(), "trace-pin".to_owned(), &request);
    // Admission belongs to the service; the chain applies the same validated set.
    ctx.levers = LeverSet::try_from_wire(variation.levers).expect("the pin names declared levers");
    ctx.variants = fixture.variants.clone();
    let cancel = CancellationToken::new();

    let extract = ExtractGraphContextNode::new(
        Some(fixture.embedding.clone()),
        Some(Arc::new(FakeGraphQueryPort::success_output(path_output()))),
    );
    extract
        .run(&mut ctx, &cancel)
        .await
        .expect("extract graph context");
    fixture
        .retrieve_node()
        .run(&mut ctx, &cancel)
        .await
        .expect("retrieve hybrid");
    AssemblePromptNode::with_settings(DEFAULT_MAX_PROMPT_TOKENS, DEFAULT_ANSWER_TOKEN_BUDGET, 1.0)
        .run(&mut ctx, &cancel)
        .await
        .expect("assemble prompt");
    ctx
}

async fn node_chain(disable_graph: bool, variation: Variation) -> String {
    let mut ctx = run_chain(&Fixture::for_variation(variation), disable_graph, variation).await;
    if let Some(snapshot) = ctx.snapshot.as_mut() {
        variation.strip(snapshot);
    }
    render_context(&ctx)
}

/// The whole workflow over the same fakes, graph on, rendering the final response only. The
/// terminal event's `WorkflowMetadata` carries timings and is left out.
async fn runner_final_response(variation: Variation) -> String {
    let completed = run_runner(&Fixture::for_variation(variation), variation).await;
    assert!(completed.success, "{}", completed.error_message);
    let mut response = completed
        .final_response
        .expect("a successful run carries a final response");
    if let Some(snapshot) = response.snapshot.as_mut() {
        variation.strip(snapshot);
    }
    format!("final_response: {}\n", hex(&response.encode_to_vec()))
}

/// The whole workflow over `fixture` fakes with a `FakeGenerator`, graph on, returning the
/// terminal event.
pub(super) async fn run_runner(fixture: &Fixture, variation: Variation) -> WorkflowCompletedEvent {
    let (tx, mut rx) = mpsc::channel(100);
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-pin".to_owned(),
        "sess-pin".to_owned(),
    );
    let mut request = test_query_request("alpha", "sess-pin");
    variation.apply(&mut request);
    let mut ctx = WorkflowContext::new("sess-pin".to_owned(), "trace-pin".to_owned(), &request);
    ctx.levers = LeverSet::try_from_wire(variation.levers).expect("the pin names declared levers");

    let mut runner = WorkflowRunner::new();
    runner.add_node(ExtractGraphContextNode::new(
        Some(fixture.embedding.clone()),
        Some(Arc::new(FakeGraphQueryPort::success_output(path_output()))),
    ));
    runner.add_node(fixture.retrieve_node());
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
    completed.expect("the workflow emits a terminal event")
}

/// The three scenarios, framed `== <name> ==` as `graph_off_fusion` frames its own.
pub(super) async fn render_scenarios(variation: Variation) -> String {
    let mut current = String::new();
    for (name, rendered) in [
        ("graph_off_node_chain", node_chain(true, variation).await),
        ("graph_on_node_chain", node_chain(false, variation).await),
        (
            "runner_final_response",
            runner_final_response(variation).await,
        ),
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
        render_scenarios(Variation::DEFAULT).await,
        golden,
        "the default request through the node chain (== graph_off_node_chain ==, \
         == graph_on_node_chain ==, == runner_final_response ==) must match the output recorded \
         before retrieval_mode existed"
    );
}

// ---------------------------------------------------------------------------
// Retrieval modes and the pre-truncation ranking (Phase 06.3.5 plan 04, D-99, D-100, D-125)
// ---------------------------------------------------------------------------

const BM25_ORDER: [&str; 4] = [
    "00000000-0000-4000-8000-0000000000d1:1",
    "00000000-0000-4000-8000-0000000000d2:1",
    "00000000-0000-4000-8000-0000000000d2:0",
    "00000000-0000-4000-8000-0000000000d1:0",
];

fn ranking_of(ctx: &WorkflowContext) -> &[crate::pb::lancet::v1::RankedCandidate] {
    &ctx.snapshot
        .as_ref()
        .expect("RetrieveHybrid leaves a snapshot on the context")
        .pre_truncation_ranking
}

/// D-125 and D-99: bm25_only with the graph off is a BM25-only system. It takes no query
/// embedding, makes no dense call, and no row carries a dense rank.
#[tokio::test]
async fn bm25_only_with_the_graph_off_takes_no_embedding_and_makes_no_dense_call() {
    let fixture = Fixture::recorded();
    let variation = Variation::mode(RetrievalMode::Bm25Only).with_ranking();

    let ctx = run_chain(&fixture, true, variation).await;

    assert_eq!(fixture.embedding.calls(), 0, "no Voyage call for BM25 only");
    assert_eq!(fixture.dense.calls(), 0, "the dense port is never asked");
    assert!(
        fixture.dense.fetch_requests().is_empty(),
        "the graph is off, so there is no by-ID fetch either"
    );
    assert_eq!(
        fixture.bm25.calls(),
        1,
        "BM25 runs once for the one variant"
    );
    assert!(ctx.query_embedding.is_none());
    assert!(ctx.vector_results.is_empty(), "vector_count reads 0");
    assert_eq!(ctx.bm25_results.len(), BM25_ORDER.len());
    assert_eq!(ctx.final_candidates, BM25_ORDER);

    let snapshot = ctx.snapshot.as_ref().expect("a snapshot");
    assert_eq!(snapshot.retrieval_mode, RetrievalMode::Bm25Only as i32);
    let ranking = ranking_of(&ctx);
    assert!(!ranking.is_empty());
    assert!(
        ranking.iter().all(|row| row.vector_rank == 0),
        "no row carries a vector_rank: {ranking:?}"
    );
    assert!(ranking.iter().all(|row| row.bm25_rank > 0));
    assert!(
        ctx.notices
            .iter()
            .all(|notice| !notice.code.starts_with("RETRIEVAL_DEGRADED")),
        "a skipped path is not a degraded path: {:?}",
        ctx.notices
    );
}

/// D-125: with the graph on, graph seeding takes the vector, so bm25_only still embeds once and
/// still never calls the dense search.
#[tokio::test]
async fn bm25_only_with_the_graph_on_embeds_once_and_still_makes_no_dense_call() {
    let fixture = Fixture::recorded();

    let ctx = run_chain(&fixture, false, Variation::mode(RetrievalMode::Bm25Only)).await;

    assert_eq!(
        fixture.embedding.calls(),
        1,
        "graph seeding takes the vector"
    );
    assert_eq!(fixture.dense.calls(), 0, "retrieve_dense is never called");
    assert_eq!(fixture.bm25.calls(), 1);
    assert!(ctx.vector_results.is_empty());
    assert_eq!(
        ctx.snapshot.as_ref().map(|s| s.retrieval_mode),
        Some(RetrievalMode::Bm25Only as i32)
    );
}

/// D-125: the embedding is skipped for exactly one combination. Every other mode, graph off or on,
/// and the default request, takes the query embedding once.
#[tokio::test]
async fn the_query_embedding_is_taken_once_in_every_combination_but_bm25_only_graph_off() {
    // (mode, graph disabled, embedding calls)
    let table = [
        (RetrievalMode::Bm25Only, true, 0),
        (RetrievalMode::Bm25Only, false, 1),
        (RetrievalMode::DenseOnly, true, 1),
        (RetrievalMode::DenseOnly, false, 1),
        (RetrievalMode::Hybrid, true, 1),
        (RetrievalMode::Hybrid, false, 1),
        (RetrievalMode::Unspecified, true, 1),
        (RetrievalMode::Unspecified, false, 1),
    ];
    for (mode, disable_graph, expected) in table {
        let fixture = Fixture::recorded();
        run_chain(&fixture, disable_graph, Variation::mode(mode)).await;
        assert_eq!(
            fixture.embedding.calls(),
            expected,
            "{mode:?} with disable_graph_context={disable_graph}"
        );
    }
}

/// D-99: dense_only keeps the dense order, cut at `final_limit`, and no row carries a BM25 rank.
#[tokio::test]
async fn dense_only_final_list_is_the_dense_top_in_dense_order_without_bm25_ranks() {
    let fixture = Fixture {
        settings: RetrievalSettings {
            final_limit: 2,
            ..settings()
        },
        ..Fixture::recorded()
    };
    let variation = Variation::mode(RetrievalMode::DenseOnly).with_ranking();

    let ctx = run_chain(&fixture, true, variation).await;

    assert_eq!(fixture.dense.calls(), 1);
    assert_eq!(fixture.bm25.calls(), 0, "the BM25 path is skipped");
    let dense_top: Vec<String> = dense_rows()
        .into_iter()
        .take(2)
        .map(|c| c.chunk_id)
        .collect();
    assert_eq!(ctx.final_candidates, dense_top);
    assert!(ctx.bm25_results.is_empty());

    let ranking = ranking_of(&ctx);
    assert_eq!(
        ranking.len(),
        dense_rows().len(),
        "the ranking is not cut at final_limit"
    );
    assert!(
        ranking.iter().all(|row| row.bm25_rank == 0),
        "no row carries a bm25_rank: {ranking:?}"
    );
    let vector_ranks: Vec<i32> = ranking.iter().map(|row| row.vector_rank).collect();
    assert_eq!(vector_ranks, [1, 2, 3, 4]);
}

/// D-99: with two variants, bm25_only fuses the per-variant BM25 lists by the existing
/// cross-variant RRF. The expected list is built from the production fusion functions.
#[tokio::test]
async fn bm25_only_with_two_variants_equals_the_cross_variant_rrf_of_the_two_bm25_lists() {
    let first_variant = "alpha".to_owned();
    let second_variant = "alpha reworded".to_owned();
    let first_list = bm25_rows();
    let second_list = vec![row(DOC_B, 0, 5.0), row(DOC_A, 2, 4.0), row(DOC_A, 3, 3.0)];
    let fixture = Fixture {
        bm25: Arc::new(FakeBm25RetrievalPort::with_map(vec![
            (first_variant.clone(), Ok(first_list.clone())),
            (second_variant.clone(), Ok(second_list.clone())),
        ])),
        variants: vec![first_variant, second_variant],
        ..Fixture::recorded()
    };
    let settings = fixture.settings.clone();

    let ctx = run_chain(&fixture, true, Variation::mode(RetrievalMode::Bm25Only)).await;

    assert_eq!(fixture.bm25.calls(), 2, "BM25 runs once per variant");
    assert_eq!(fixture.dense.calls(), 0);
    assert_eq!(fixture.embedding.calls(), 0);
    let per_variant = vec![
        fuse_candidates(Vec::new(), first_list, &settings).expect("fuse the first variant"),
        fuse_candidates(Vec::new(), second_list, &settings).expect("fuse the second variant"),
    ];
    let expected: Vec<String> = fuse_cross_variant_candidates(per_variant, Vec::new(), &settings)
        .expect("fuse across the variants")
        .into_iter()
        .take(settings.final_limit)
        .map(|fused| fused.candidate.chunk_id)
        .collect();
    assert_eq!(ctx.final_candidates, expected);
    assert_ne!(
        ctx.final_candidates, BM25_ORDER,
        "the second variant must change the result, or this test shows nothing"
    );
}

/// D-100: the ranking flag leaves the answer path alone. Every scenario, rendered with the flag on
/// and the ranking cleared, equals the golden recorded before the flag existed. That covers the
/// final list, `result_hash`, the prompt and the runner's final response.
#[tokio::test]
async fn flag_on_scenarios_equal_the_recorded_golden_once_the_ranking_is_cleared() {
    let golden =
        include_str!("../retrieval/testdata/retrieve_node_default.golden").replace("\r\n", "\n");

    let flag_on = Variation::DEFAULT.with_ranking().stripped();

    assert_eq!(render_scenarios(flag_on).await, golden);
}

/// D-99: an explicit hybrid request runs the same paths as the default one. With only the
/// snapshot's mode echo zeroed, every scenario equals the recorded golden.
#[tokio::test]
async fn explicit_hybrid_scenarios_equal_the_recorded_golden_once_the_echo_is_zeroed() {
    let golden =
        include_str!("../retrieval/testdata/retrieve_node_default.golden").replace("\r\n", "\n");

    let explicit_hybrid = Variation::mode(RetrievalMode::Hybrid).stripped();

    assert_eq!(render_scenarios(explicit_hybrid).await, golden);
}

/// D-100: the ranking is bounded by `candidate_limit`, its head is the retrieved set in order with
/// matching rank and graph flag, and `fused_rank` runs contiguously from 1.
#[tokio::test]
async fn the_ranking_head_is_the_retrieved_set_and_fused_rank_is_contiguous() {
    for disable_graph in [true, false] {
        let fixture = Fixture::recorded();
        let ctx = run_chain(&fixture, disable_graph, Variation::DEFAULT.with_ranking()).await;
        let snapshot = ctx.snapshot.as_ref().expect("a snapshot");
        let ranking = ranking_of(&ctx);

        assert!(!ranking.is_empty(), "disable_graph_context={disable_graph}");
        assert!(ranking.len() <= fixture.settings.candidate_limit);
        assert!(ranking.len() > snapshot.retrieved_chunks.len());
        for (index, chunk) in snapshot.retrieved_chunks.iter().enumerate() {
            let row = &ranking[index];
            assert_eq!(row.chunk_id, chunk.chunk_id);
            assert_eq!(row.document_id, chunk.document_id);
            assert_eq!(i64::from(row.fused_rank), i64::from(chunk.rank));
            assert_eq!(row.graph_boosted, chunk.graph_boosted);
        }
        let fused_ranks: Vec<usize> = ranking.iter().map(|row| row.fused_rank as usize).collect();
        assert_eq!(fused_ranks, (1..=ranking.len()).collect::<Vec<_>>());
        assert!(ranking
            .iter()
            .all(|row| !row.chunk_id.is_empty() && !row.document_id.is_empty()));
        assert_eq!(
            ranking.iter().any(|row| row.graph_boosted),
            !disable_graph,
            "graph-boosted rows appear exactly when the graph is on"
        );
    }
}

/// D-100 tie order (specless edge: ordering): candidates with an exact fused-score tie keep the
/// order truncation uses. The ranking lists the fused order with no re-sort, so its head still
/// equals the retrieved set when the tie straddles `final_limit`.
#[tokio::test]
async fn a_fused_score_tie_straddling_final_limit_keeps_the_truncation_order_in_the_ranking() {
    let fixture = Fixture::recorded();
    let settings = fixture.settings.clone();
    let fused = fuse_cross_variant_candidates(
        vec![
            fuse_candidates(dense_rows(), bm25_rows(), &settings).expect("fuse the recorded lists")
        ],
        Vec::new(),
        &settings,
    )
    .expect("fuse across the one variant");
    assert_eq!(
        fused[settings.final_limit - 1].fused_score.to_bits(),
        fused[settings.final_limit].fused_score.to_bits(),
        "the fixture must hold an exact tie across the final limit"
    );
    let fused_order: Vec<String> = fused.iter().map(|f| f.candidate.chunk_id.clone()).collect();

    let ctx = run_chain(&fixture, true, Variation::DEFAULT.with_ranking()).await;

    let ranked_order: Vec<String> = ranking_of(&ctx)
        .iter()
        .map(|row| row.chunk_id.clone())
        .collect();
    assert_eq!(ranked_order, fused_order);
    assert_eq!(
        &ranked_order[..settings.final_limit],
        ctx.final_candidates.as_slice()
    );
}
