//! Pins for the `levers` request contract (Phase 06.3.6, D-136, D-165).
//!
//! The tracer test sends one request that names a lever through the real service admission and
//! workflow over the existing fakes, and reads the lever back from the final snapshot. The
//! admission matrix rows live in [`super::bad_input_matrix`]; the byte-identity of the default
//! request is pinned by the three recorded goldens.

use std::sync::Arc;
use std::time::Duration;

use prost::Message;
use uuid::Uuid;

use engine::config::EffectiveRagSettings;
use engine::db::DatabaseManager;
use engine::generation;
use engine::ingest::{process_job, read_staged_jobs};
use engine::pb::lancet::v1::{Lever, QueryRagRequest, RerankOutcome};
use engine::rerank;
use engine::testkit::test_query_request;

use engine::workflow::LeverSet;

use crate::doc_meta::{DocMeta, DocMetaMap};
use crate::service::LeverResources;
use crate::workflow::nodes::retrieve::{rerank_allowance, RERANK_NODE_RESERVE_MS};
use crate::workflow::ports::FakeReranker;
use crate::workflow::WorkflowContext;

use super::retrieval_mode_pins::{
    hex, render_scenarios, run_chain, run_runner, Fixture, Variation, DOC_A, DOC_B,
};
use super::{
    configured_service, database_path, reranker_query_fixture, stage_document, FailingReranker,
    FakeEmbedder, FakeGenerator, RecordingGenerator, RecordingReranker,
};

#[tokio::test]
async fn a_levers_request_is_admitted_and_echoed() {
    let path = database_path("levers-tracer");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let doc_id = Uuid::new_v4().to_string();
    stage_document(
        &database,
        &doc_id,
        b"# Levers Tracer\nThis document backs the levers admission and echo tracer.",
    )
    .await;
    let job = read_staged_jobs(&database)
        .await
        .unwrap()
        .into_iter()
        .next()
        .unwrap();
    process_job(&job, &database, &FakeEmbedder).await.unwrap();

    let fake_gen = Arc::new(FakeGenerator::new(Ok(generation::ModelOutput {
        answer: "Levers tracer answer [1].".into(),
        cited_evidence_ids: vec!["[1]".into()],
        answer_basis: generation::AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        final_answer: None,
        usage: None,
    })));
    let service = configured_service(
        &database,
        EffectiveRagSettings::default(),
        Arc::new(FakeEmbedder),
        fake_gen as Arc<dyn generation::Generator>,
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;

    let request = QueryRagRequest {
        levers: vec![Lever::BinaryAnswerFormat as i32],
        ..test_query_request(
            "What does the levers tracer document back?",
            "00000000-0000-4000-8000-0000000000e1",
        )
    };
    let response = super::execute_query_rag(&service, request)
        .await
        .expect("a request naming binary_answer_format must complete");
    let snapshot = response
        .snapshot
        .expect("a completed run carries a retrieval snapshot");
    assert_eq!(snapshot.levers, vec![Lever::BinaryAnswerFormat as i32]);

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// Identity and canonical order (Phase 06.3.6 plan 05 Task 3, D-136)
// ---------------------------------------------------------------------------

/// `retrieve_node_default.golden` was recorded before `retrieval_mode` or `levers` existed
/// (see `retrieval_mode_pins`). A request that names an explicit empty `levers` list renders the
/// same three scenarios, so the empty list is today's request and the default snapshot bytes are
/// unchanged.
#[tokio::test]
async fn an_explicit_empty_levers_list_renders_the_recorded_default_request_output() {
    let golden =
        include_str!("../retrieval/testdata/retrieve_node_default.golden").replace("\r\n", "\n");
    assert_eq!(
        render_scenarios(Variation::DEFAULT.with_levers(&[])).await,
        golden,
        "an explicit empty `levers` list must be byte-identical to the default request"
    );
}

#[test]
fn the_echo_is_ascending_enum_order_whatever_order_the_client_sent() {
    let sent_orders: [&[i32]; 4] = [&[3, 1], &[1, 3], &[4, 2, 3, 1], &[2, 4]];
    for sent in sent_orders {
        let echoed = LeverSet::try_from_wire(sent)
            .expect("these values are declared and distinct")
            .to_wire();
        let mut ascending = sent.to_vec();
        ascending.sort_unstable();
        assert_eq!(echoed, ascending, "echo of {sent:?}");
    }
    assert_eq!(LeverSet::try_from_wire(&[]).unwrap(), LeverSet::default());
    assert!(LeverSet::default().is_empty());
    assert!(LeverSet::default().to_wire().is_empty());
}

#[test]
fn a_lever_set_refuses_what_the_wire_may_not_carry() {
    let unknown = LeverSet::try_from_wire(&[99]).unwrap_err();
    assert!(unknown.is_unknown());
    assert_eq!(unknown.value(), 99);

    let unspecified = LeverSet::try_from_wire(&[Lever::Rerank as i32, 0]).unwrap_err();
    assert!(unspecified.is_unspecified());

    let negative = LeverSet::try_from_wire(&[-1]).unwrap_err();
    assert!(negative.is_negative());
    assert_eq!(negative.value(), -1);

    let duplicate = LeverSet::try_from_wire(&[3, 1, 3]).unwrap_err();
    assert!(duplicate.is_duplicate());
    assert_eq!(duplicate.value(), 3);
}

#[test]
fn a_lever_set_contains_exactly_the_levers_it_was_built_from() {
    let set =
        LeverSet::try_from_wire(&[Lever::BinaryAnswerFormat as i32, Lever::Rerank as i32]).unwrap();
    assert!(set.contains(Lever::Rerank));
    assert!(set.contains(Lever::BinaryAnswerFormat));
    assert!(!set.contains(Lever::EvidenceMetadata));
    assert!(!set.contains(Lever::GraphV2));
    assert!(!set.contains(Lever::Unspecified));
    assert!(!set.is_empty());
    assert_eq!(
        set.iter().collect::<Vec<_>>(),
        vec![Lever::Rerank, Lever::BinaryAnswerFormat]
    );
}

// ---------------------------------------------------------------------------
// The rerank lever (Phase 06.3.6 plan 09, D-131, D-133, D-134, D-135, D-166)
// ---------------------------------------------------------------------------

/// The chunk IDs of the snapshot's pre-truncation ranking, in order.
fn ranking_ids(ctx: &WorkflowContext) -> Vec<String> {
    ctx.snapshot
        .as_ref()
        .expect("RetrieveHybrid leaves a snapshot on the context")
        .pre_truncation_ranking
        .iter()
        .map(|row| row.chunk_id.clone())
        .collect()
}

const RERANK: &[i32] = &[Lever::Rerank as i32];

/// The notice codes in order, for comparing two runs.
fn notice_codes(notices: &[crate::pb::lancet::v1::Notice]) -> Vec<&str> {
    notices.iter().map(|notice| notice.code.as_str()).collect()
}

/// The `final_limit` of the `retrieval_mode_pins` fixture.
const FIXTURE_FINAL_LIMIT: usize = 4;

fn degrade_notices(
    notices: &[crate::pb::lancet::v1::Notice],
) -> Vec<&crate::pb::lancet::v1::Notice> {
    notices
        .iter()
        .filter(|notice| notice.code == "RERANK_DEGRADED")
        .collect()
}

/// D-166: an identity lever reranker whose scores equal the fused scores changes nothing the
/// default request shows, so the recorded pre-change output still holds with the lever on (the
/// lever echo is the one difference and is zeroed before rendering).
#[tokio::test]
async fn a_rerank_lever_over_an_identity_ranking_renders_the_recorded_default_request_output() {
    let golden =
        include_str!("../retrieval/testdata/retrieve_node_default.golden").replace("\r\n", "\n");
    let variation = Variation::DEFAULT
        .with_levers(RERANK)
        .with_identity_lever()
        .stripped();
    assert_eq!(
        render_scenarios(variation).await,
        golden,
        "the rerank lever over an identity ranking must match the recorded default request output"
    );
}

/// The same identity run with the ranking flag: the ranking, the final list and the result hash
/// equal the lever-free run.
#[tokio::test]
async fn an_identity_lever_leaves_the_ranking_the_final_list_and_the_result_hash_unchanged() {
    let flagged = Variation::DEFAULT.with_ranking();
    let free = run_chain(&Fixture::recorded(), false, flagged).await;
    let lever = run_chain(
        &Fixture::recorded().with_lever(
            Arc::new(FakeReranker::success()),
            Duration::from_millis(1706),
            Duration::from_millis(2500),
        ),
        false,
        flagged.with_levers(RERANK),
    )
    .await;
    let free_snapshot = free.snapshot.as_ref().unwrap();
    let lever_snapshot = lever.snapshot.as_ref().unwrap();
    assert_eq!(lever.vector_results, free.vector_results);
    assert_eq!(lever.bm25_results, free.bm25_results);
    assert_eq!(lever.final_candidates, free.final_candidates);
    assert_eq!(lever_snapshot.result_hash, free_snapshot.result_hash);
    assert_eq!(
        lever_snapshot.pre_truncation_ranking,
        free_snapshot.pre_truncation_ranking
    );
    assert_eq!(
        notice_codes(&lever.notices),
        notice_codes(&free.notices),
        "an identity ranking adds no notice"
    );
}

/// D-133: with a reranker that reorders the list, the pre-truncation ranking is the order after
/// it, so its first `final_limit` rows are the taken chunks in order.
#[tokio::test]
async fn the_pre_truncation_ranking_is_captured_after_the_reranker() {
    let variation = Variation::DEFAULT.with_ranking();
    let baseline = run_chain(&Fixture::recorded(), true, variation).await;
    let fused_ids = ranking_ids(&baseline);
    assert!(
        fused_ids.len() > FIXTURE_FINAL_LIMIT,
        "the fixture must have candidates beyond the final limit"
    );

    let rotating = RecordingReranker::new();
    let ctx = run_chain(
        &Fixture::recorded().with_reranker(rotating.clone()),
        true,
        variation,
    )
    .await;
    assert_eq!(rotating.calls(), 1);

    let mut rotated = fused_ids.clone();
    rotated.rotate_left(1);
    let ranking = ranking_ids(&ctx);
    assert_eq!(ranking, rotated, "the ranking is the post-rerank order");
    assert_ne!(ranking, fused_ids);
    assert_eq!(
        &ranking[..FIXTURE_FINAL_LIMIT],
        ctx.final_candidates.as_slice()
    );
    let positions: Vec<i32> = ctx
        .snapshot
        .as_ref()
        .unwrap()
        .pre_truncation_ranking
        .iter()
        .map(|row| row.fused_rank)
        .collect();
    assert_eq!(
        positions,
        (1..=ranking.len() as i32).collect::<Vec<_>>(),
        "fused_rank is the position after the reranker"
    );
}

/// A configured lever reranker is used only for a request that names the lever.
#[tokio::test]
async fn a_lever_reranker_is_not_called_for_a_request_that_does_not_name_the_lever() {
    let failing = Arc::new(FakeReranker::failure());
    let fixture = Fixture::recorded().with_lever(
        failing.clone(),
        Duration::from_millis(1706),
        Duration::from_millis(2500),
    );
    let ctx = run_chain(&fixture, true, Variation::DEFAULT).await;
    assert_eq!(failing.calls(), 0);
    assert!(degrade_notices(&ctx.notices).is_empty());
    assert!(ctx.rerank.is_none(), "no rerank was attempted");
}

/// D-134: a reranker that never answers is cut at its own limit under a paused clock, the fused
/// order is kept, one notice and the degraded outcome are recorded, and generation still runs.
#[tokio::test(start_paused = true)]
async fn a_stalled_lever_reranker_degrades_to_the_fused_order_and_generation_still_runs() {
    let free = run_runner(&Fixture::recorded(), Variation::DEFAULT).await;
    let free_ids: Vec<String> = free
        .final_response
        .as_ref()
        .and_then(|response| response.snapshot.as_ref())
        .expect("a lever-free run carries a snapshot")
        .retrieved_chunks
        .iter()
        .map(|chunk| chunk.chunk_id.clone())
        .collect();

    let stalled = Arc::new(FakeReranker::stall());
    let fixture = Fixture::recorded().with_lever(
        stalled.clone(),
        Duration::from_millis(200),
        Duration::from_millis(2500),
    );
    let completed = run_runner(&fixture, Variation::DEFAULT.with_levers(RERANK)).await;

    assert!(completed.success, "{}", completed.error_message);
    assert_eq!(stalled.calls(), 1);
    let response = completed.final_response.as_ref().expect("generation ran");
    assert!(!response.answer.is_empty(), "the query still generates");
    let ids: Vec<String> = response
        .snapshot
        .as_ref()
        .unwrap()
        .retrieved_chunks
        .iter()
        .map(|chunk| chunk.chunk_id.clone())
        .collect();
    assert_eq!(ids, free_ids, "the fused order is kept");

    let notices = degrade_notices(&completed.notices);
    assert_eq!(notices.len(), 1, "exactly one RERANK_DEGRADED notice");
    assert!(
        notices[0].message.contains("timeout"),
        "{}",
        notices[0].message
    );
    let rerank = completed
        .metadata
        .as_ref()
        .and_then(|metadata| metadata.rerank)
        .expect("a rerank attempt is wire-visible");
    assert_eq!(rerank.outcome, RerankOutcome::DegradedTimeout as i32);
    assert!(
        (200..=260).contains(&rerank.latency_ms),
        "the call is cut at its own limit: {} ms",
        rerank.latency_ms
    );
    assert!(!rerank.cost_reported);
}

/// D-134: every failure class keeps the fused order, adds one class-only notice and records the
/// matching outcome.
#[tokio::test]
async fn each_lever_failure_class_keeps_the_fused_order_and_records_its_outcome() {
    use crate::rerank::{RerankError, Reranked};

    let baseline = run_chain(&Fixture::recorded(), false, Variation::DEFAULT).await;
    let not_a_permutation = || {
        FakeReranker::scripted(
            vec![Reranked {
                index: 0,
                score: 1.0,
            }],
            None,
        )
    };
    let cases: Vec<(&str, FakeReranker, RerankOutcome, &str)> = vec![
        (
            "timeout",
            FakeReranker::failing_with(RerankError::timeout()),
            RerankOutcome::DegradedTimeout,
            "timeout",
        ),
        (
            "status",
            FakeReranker::failing_with(RerankError::status(429)),
            RerankOutcome::DegradedStatus,
            "status 429",
        ),
        (
            "transport",
            FakeReranker::failing_with(RerankError::transport()),
            RerankOutcome::DegradedTransport,
            "transport",
        ),
        (
            "malformed",
            FakeReranker::failing_with(RerankError::malformed()),
            RerankOutcome::DegradedMalformed,
            "malformed",
        ),
        (
            "invalid request",
            FakeReranker::failing_with(RerankError::invalid_request()),
            RerankOutcome::DegradedMalformed,
            "invalid request",
        ),
        (
            "a ranking that is not a permutation",
            not_a_permutation(),
            RerankOutcome::DegradedMalformed,
            "malformed",
        ),
    ];
    for (label, fake, outcome, class) in cases {
        let fixture = Fixture::recorded().with_lever(
            Arc::new(fake),
            Duration::from_millis(1706),
            Duration::from_millis(2500),
        );
        let ctx = run_chain(&fixture, false, Variation::DEFAULT.with_levers(RERANK)).await;
        assert_eq!(
            ctx.final_candidates, baseline.final_candidates,
            "{label}: the fused order is kept"
        );
        let notices = degrade_notices(&ctx.notices);
        assert_eq!(notices.len(), 1, "{label}: one notice");
        assert!(
            notices[0].message.contains(class),
            "{label}: the notice names the class: {}",
            notices[0].message
        );
        let rerank = ctx.rerank.expect("a rerank attempt is recorded");
        assert_eq!(rerank.outcome, outcome as i32, "{label}");
        assert!(
            !rerank.cost_reported && rerank.cost_credits == 0.0,
            "{label}"
        );
    }
}

/// D-135: the call is cut to what the node budget has left minus the reserve.
#[test]
fn the_rerank_call_is_cut_to_the_node_budget_left_minus_the_reserve() {
    let timeout = Duration::from_millis(1706);
    let budget = Duration::from_millis(2500);
    let reserve = Duration::from_millis(RERANK_NODE_RESERVE_MS);
    assert_eq!(rerank_allowance(timeout, budget, Duration::ZERO), timeout);
    assert_eq!(
        rerank_allowance(timeout, budget, Duration::from_millis(2400)),
        budget - Duration::from_millis(2400) - reserve
    );
    assert_eq!(
        rerank_allowance(timeout, budget, Duration::from_millis(2400)),
        Duration::from_millis(50)
    );
    assert_eq!(
        rerank_allowance(timeout, budget, budget - reserve),
        Duration::ZERO
    );
    assert_eq!(
        rerank_allowance(timeout, budget, Duration::from_millis(9000)),
        Duration::ZERO,
        "a spent budget never underflows"
    );
    assert_eq!(
        rerank_allowance(Duration::from_millis(100), budget, Duration::ZERO),
        Duration::from_millis(100),
        "the call's own limit still applies when the node has plenty left"
    );
}

/// D-135: a node budget with nothing left after the reserve degrades without any provider call.
#[tokio::test]
async fn a_spent_node_budget_degrades_without_calling_the_reranker() {
    let fake = Arc::new(FakeReranker::success());
    let fixture = Fixture::recorded().with_lever(
        fake.clone(),
        Duration::from_millis(1706),
        Duration::from_millis(RERANK_NODE_RESERVE_MS),
    );
    let ctx = run_chain(&fixture, false, Variation::DEFAULT.with_levers(RERANK)).await;
    assert_eq!(fake.calls(), 0, "no call may start inside the reserve");
    assert_eq!(degrade_notices(&ctx.notices).len(), 1);
    assert_eq!(
        ctx.rerank.expect("the attempt is recorded").outcome,
        RerankOutcome::DegradedTimeout as i32
    );
}

/// D-166: the relevance replaces the fused score, the final list and the prompt follow the
/// reranked order, and the metadata reports the call.
#[tokio::test]
async fn the_lever_relevance_replaces_the_score_and_the_prompt_follows_the_reranked_order() {
    use crate::rerank::Reranked;

    let flagged = Variation::DEFAULT.with_ranking();
    let baseline = run_chain(&Fixture::recorded(), false, flagged).await;
    let fused_ids = ranking_ids(&baseline);
    let count = fused_ids.len();
    assert!(count > FIXTURE_FINAL_LIMIT);

    // Reverse the fused order with distinct, strictly descending relevance scores.
    let relevance: Vec<f64> = (0..count).map(|rank| 0.95 - 0.1 * rank as f64).collect();
    let script: Vec<Reranked> = (0..count)
        .map(|rank| Reranked {
            index: count - 1 - rank,
            score: relevance[rank],
        })
        .collect();
    let fixture = Fixture::recorded().with_lever(
        Arc::new(FakeReranker::scripted(script, Some(4.4e-07))),
        Duration::from_millis(1706),
        Duration::from_millis(2500),
    );
    let ctx = run_chain(&fixture, false, flagged.with_levers(RERANK)).await;

    let mut reversed = fused_ids.clone();
    reversed.reverse();
    assert_eq!(
        ctx.final_candidates,
        reversed[..FIXTURE_FINAL_LIMIT].to_vec(),
        "the final list is the head of the reranked order"
    );
    assert_eq!(
        &ranking_ids(&ctx)[..FIXTURE_FINAL_LIMIT],
        ctx.final_candidates.as_slice()
    );

    let scores: Vec<f64> = ctx
        .evidence_blocks
        .iter()
        .map(|block| block.score)
        .collect();
    assert_eq!(
        scores,
        relevance[..FIXTURE_FINAL_LIMIT].to_vec(),
        "D-166: the relevance is the score"
    );
    let cited: Vec<f64> = ctx
        .snapshot
        .as_ref()
        .unwrap()
        .retrieved_chunks
        .iter()
        .map(|chunk| chunk.score)
        .collect();
    assert_eq!(
        cited, scores,
        "the citation score is the relevance on a rerank arm"
    );

    let positions: Vec<usize> = ctx
        .evidence_blocks
        .iter()
        .map(|block| {
            ctx.assembled_prompt
                .find(block.text.as_str())
                .unwrap_or_else(|| panic!("the prompt must hold {}", block.chunk_id))
        })
        .collect();
    assert!(
        positions.windows(2).all(|pair| pair[0] < pair[1]),
        "the prompt lists the evidence in the reranked order: {positions:?}"
    );

    let rerank = ctx.rerank.expect("the attempt is recorded");
    assert_eq!(rerank.outcome, RerankOutcome::Completed as i32);
    assert!(rerank.cost_reported);
    assert_eq!(rerank.cost_credits, 4.4e-07);
    assert!(
        degrade_notices(&ctx.notices).is_empty(),
        "a completed rerank adds no notice"
    );

    // The same list with no lever keeps the fused scores, so the overwrite is the lever's own.
    let free_scores: Vec<f64> = baseline
        .evidence_blocks
        .iter()
        .map(|block| block.score)
        .collect();
    assert_ne!(free_scores, scores);
}

// ---------------------------------------------------------------------------
// Admission and per-request selection through the real service (D-131, D-136)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn rerank_is_available_only_when_the_lever_reranker_is_wired() {
    let (path, mut service) = reranker_query_fixture(
        "levers-rerank-availability",
        1,
        RecordingGenerator::from_effective_settings(&EffectiveRagSettings::default()),
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;
    let snapshot = Arc::clone(&*service.corpus_store.read().await);
    assert!(!service
        .lever_availability(&snapshot)
        .is_available(Lever::Rerank));

    service.lever_resources = LeverResources {
        reranker: Some(Arc::new(FakeReranker::success())),
    };
    let availability = service.lever_availability(&snapshot);
    assert!(availability.is_available(Lever::Rerank));
    assert!(
        !availability.is_available(Lever::EvidenceMetadata),
        "wiring the reranker serves no other lever"
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn a_rerank_request_uses_the_lever_reranker_and_a_plain_request_uses_the_service_reranker() {
    let strict = FailingReranker::new();
    let lever = Arc::new(FakeReranker::success());
    let generator = RecordingGenerator::from_effective_settings(&EffectiveRagSettings::default());
    let (path, mut service) = reranker_query_fixture(
        "levers-rerank-selection",
        1,
        generator.clone(),
        strict.clone(),
    )
    .await;
    service.lever_resources = LeverResources {
        reranker: Some(lever.clone()),
    };

    let response = super::execute_query_rag(
        &service,
        QueryRagRequest {
            levers: RERANK.to_vec(),
            ..test_query_request("reranker evidence", "00000000-0000-4000-8000-0000000000e2")
        },
    )
    .await
    .expect("the lever reranker serves a request that names rerank");
    assert_eq!(
        response.snapshot.expect("a snapshot").levers,
        vec![Lever::Rerank as i32]
    );
    assert_eq!(lever.calls(), 1);
    assert_eq!(
        strict.calls(),
        0,
        "the lever path never touches the service reranker"
    );
    assert_eq!(generator.calls(), 1);

    let plain = super::execute_query_rag(
        &service,
        test_query_request("reranker evidence", "00000000-0000-4000-8000-0000000000e3"),
    )
    .await;
    assert!(
        plain.is_err(),
        "the lever-free path keeps its strict failure"
    );
    assert_eq!(strict.calls(), 1);
    assert_eq!(
        lever.calls(),
        1,
        "a plain request never calls the lever reranker"
    );
    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// The evidence metadata and binary answer format levers (Phase 06.3.6 plan 11 Task 2,
// D-136, D-142, D-145)
// ---------------------------------------------------------------------------

const METADATA: &[i32] = &[Lever::EvidenceMetadata as i32];
const BINARY: &[i32] = &[Lever::BinaryAnswerFormat as i32];

fn headline_meta() -> DocMeta {
    DocMeta {
        doc_title: Some("A real headline".to_owned()),
        source: Some("The Example Times".to_owned()),
        published_date: Some("2023-10-07".to_owned()),
    }
}

/// Metadata for document A of the `retrieval_mode_pins` fixture only; document B has none.
fn fixture_doc_meta() -> Arc<DocMetaMap> {
    Arc::new(DocMetaMap::from_entries([(
        DOC_A.to_owned(),
        headline_meta(),
    )]))
}

/// The text of one `== name ==` section of a recorded golden, up to the next section header.
fn golden_section<'a>(golden: &'a str, name: &str) -> &'a str {
    let header = format!("== {name} ==\n");
    let from = golden.find(&header).expect("the golden has the section") + header.len();
    let to = golden[from..]
        .find("\n== ")
        .map_or(golden.len(), |offset| from + offset);
    &golden[from..to]
}

/// D-145: `evidence_metadata` alone and `binary_answer_format` alone change only the prompt, so
/// the dense and BM25 lists, the final list and the snapshot (the result hash and the cited
/// chunks included) equal the recorded default-request golden, with the lever echo zeroed. The
/// prompt is the one thing that differs, so it is not compared here. The fixture holds metadata
/// for document A, so the lever has something to attach.
#[tokio::test]
async fn a_prompt_lever_alone_leaves_retrieval_equal_to_the_recorded_default_request_output() {
    let golden =
        include_str!("../retrieval/testdata/retrieve_node_default.golden").replace("\r\n", "\n");
    let section = golden_section(&golden, "graph_on_node_chain");
    let line = |prefix: &str| {
        section
            .lines()
            .find(|candidate| candidate.starts_with(prefix))
            .unwrap_or_else(|| panic!("the golden section has a {prefix} line"))
            .to_owned()
    };
    for levers in [METADATA, BINARY] {
        let fixture = Fixture::recorded().with_doc_meta(fixture_doc_meta());
        let ctx = run_chain(&fixture, false, Variation::DEFAULT.with_levers(levers)).await;
        let mut snapshot = ctx.snapshot.clone().expect("a snapshot");
        assert_eq!(snapshot.levers, levers.to_vec(), "the echo names the lever");
        snapshot.levers.clear();
        assert_eq!(
            format!("dense: {}", ctx.vector_results.join(",")),
            line("dense: "),
            "{levers:?}"
        );
        assert_eq!(
            format!("bm25: {}", ctx.bm25_results.join(",")),
            line("bm25: "),
            "{levers:?}"
        );
        assert_eq!(
            format!("final: {}", ctx.final_candidates.join(",")),
            line("final: "),
            "{levers:?}"
        );
        assert_eq!(
            format!("snapshot: {}", hex(&snapshot.encode_to_vec())),
            line("snapshot: "),
            "the snapshot, result hash and citations equal the golden for {levers:?}"
        );
    }
}

/// D-145: the pre-truncation ranking and the result hash equal the lever-free run's.
#[tokio::test]
async fn a_prompt_lever_alone_leaves_the_ranking_and_the_result_hash_unchanged() {
    let fixture = Fixture::recorded().with_doc_meta(fixture_doc_meta());
    let ranked = Variation::DEFAULT.with_ranking();
    let free = run_chain(&fixture, false, ranked).await;
    let free_snapshot = free.snapshot.as_ref().expect("a snapshot");
    assert!(!free_snapshot.pre_truncation_ranking.is_empty());
    for levers in [METADATA, BINARY] {
        let ctx = run_chain(&fixture, false, ranked.with_levers(levers)).await;
        let snapshot = ctx.snapshot.as_ref().expect("a snapshot");
        assert_eq!(ctx.final_candidates, free.final_candidates, "{levers:?}");
        assert_eq!(snapshot.result_hash, free_snapshot.result_hash, "{levers:?}");
        assert_eq!(
            snapshot.pre_truncation_ranking, free_snapshot.pre_truncation_ranking,
            "{levers:?}"
        );
    }
}

/// D-142, D-145: under the lever each block of a document with an entry carries that entry,
/// blocks of other documents carry `None`, and the headers reach the prompt for the first only.
#[tokio::test]
async fn the_metadata_lever_attaches_the_entry_of_each_blocks_document_and_nothing_else() {
    let fixture = Fixture::recorded().with_doc_meta(fixture_doc_meta());
    let ctx = run_chain(&fixture, true, Variation::DEFAULT.with_levers(METADATA)).await;

    let from_a = ctx
        .evidence_blocks
        .iter()
        .filter(|block| block.document_id == DOC_A)
        .count();
    let from_b = ctx
        .evidence_blocks
        .iter()
        .filter(|block| block.document_id == DOC_B)
        .count();
    assert!(from_a > 0 && from_b > 0, "the fixture serves both documents");
    for block in &ctx.evidence_blocks {
        if block.document_id == DOC_A {
            assert_eq!(block.evidence_meta.as_ref(), Some(&headline_meta()));
        } else {
            assert!(
                block.evidence_meta.is_none(),
                "a document without an entry carries no metadata"
            );
        }
    }
    assert_eq!(
        ctx.assembled_prompt
            .matches("<DOC_TITLE>A real headline</DOC_TITLE>")
            .count(),
        from_a
    );
    assert_eq!(
        ctx.assembled_prompt
            .matches("<SOURCE>The Example Times</SOURCE>")
            .count(),
        from_a
    );
    assert_eq!(
        ctx.assembled_prompt
            .matches("<PUBLISHED>2023-10-07</PUBLISHED>")
            .count(),
        from_a
    );
    assert!(ctx
        .assembled_prompt
        .contains(crate::prompt::EVIDENCE_METADATA_POLICY_SENTENCE));
}

/// With the lever off, even a snapshot that holds metadata attaches none and the prompt shows no
/// header; `binary_answer_format` alone attaches none either.
#[tokio::test]
async fn without_the_metadata_lever_no_block_carries_metadata_and_the_prompt_has_no_header() {
    let fixture = Fixture::recorded().with_doc_meta(fixture_doc_meta());
    for levers in [&[][..], BINARY] {
        let ctx = run_chain(&fixture, true, Variation::DEFAULT.with_levers(levers)).await;
        assert!(!ctx.evidence_blocks.is_empty());
        assert!(
            ctx.evidence_blocks
                .iter()
                .all(|block| block.evidence_meta.is_none()),
            "{levers:?}"
        );
        for tag in ["<DOC_TITLE>", "<SOURCE>", "<PUBLISHED>"] {
            assert!(!ctx.assembled_prompt.contains(tag), "{levers:?} {tag}");
        }
        assert!(!ctx
            .assembled_prompt
            .contains(crate::prompt::EVIDENCE_METADATA_POLICY_SENTENCE));
    }
}

/// D-145: the citation of a chunk keeps its filename title under the metadata lever, both in the
/// snapshot's retrieved chunks and on the evidence block.
#[tokio::test]
async fn a_metadata_arm_citation_title_equals_the_hybrid_arms_for_the_same_chunk() {
    let fixture = Fixture::recorded().with_doc_meta(fixture_doc_meta());
    let titles = |ctx: &WorkflowContext| -> Vec<(String, String)> {
        ctx.snapshot
            .as_ref()
            .expect("a snapshot")
            .retrieved_chunks
            .iter()
            .map(|chunk| (chunk.chunk_id.clone(), chunk.title.clone()))
            .collect()
    };
    let hybrid = run_chain(&fixture, false, Variation::DEFAULT).await;
    let metadata = run_chain(&fixture, false, Variation::DEFAULT.with_levers(METADATA)).await;
    assert!(!titles(&hybrid).is_empty());
    assert_eq!(titles(&metadata), titles(&hybrid));
    assert!(
        titles(&metadata).iter().all(|(_, title)| title == "Title"),
        "the real document title never replaces the citation title"
    );
    let block_titles = |ctx: &WorkflowContext| -> Vec<Option<String>> {
        ctx.evidence_blocks
            .iter()
            .map(|block| block.title.clone())
            .collect()
    };
    assert_eq!(block_titles(&metadata), block_titles(&hybrid));
}

/// D-136: `evidence_metadata` needs metadata in the snapshot. An empty map refuses it; a map with
/// one entry admits it; `binary_answer_format` needs nothing.
#[tokio::test]
async fn the_metadata_lever_is_available_only_when_the_snapshot_holds_metadata() {
    let (path, service) = reranker_query_fixture(
        "levers-metadata-availability",
        3,
        RecordingGenerator::from_effective_settings(&EffectiveRagSettings::default()),
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;
    let empty = Arc::clone(&*service.corpus_store.read().await);
    assert!(empty.doc_meta.is_empty());
    let availability = service.lever_availability(&empty);
    assert!(!availability.is_available(Lever::EvidenceMetadata));
    assert!(availability.is_available(Lever::BinaryAnswerFormat));

    let with_metadata = (*empty).clone().with_doc_meta(fixture_doc_meta());
    let availability = service.lever_availability(&with_metadata);
    assert!(availability.is_available(Lever::EvidenceMetadata));
    assert!(availability.is_available(Lever::BinaryAnswerFormat));
    assert!(
        !availability.is_available(Lever::GraphV2),
        "the metadata does not serve another lever"
    );
    let _ = std::fs::remove_dir_all(path);
}

/// Through the real service: the lever reaches the generation request as a prompt option and as
/// metadata on the evidence, and a request without the levers carries neither.
#[tokio::test]
async fn the_prompt_levers_reach_the_generation_request_through_the_service() {
    let generator = RecordingGenerator::from_effective_settings(&EffectiveRagSettings::default());
    let (path, service) = reranker_query_fixture(
        "levers-prompt-options",
        3,
        generator.clone(),
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;

    // A lever-free request first, to learn which documents the corpus serves.
    super::execute_query_rag(
        &service,
        test_query_request("reranker evidence", "00000000-0000-4000-8000-0000000000f1"),
    )
    .await
    .expect("a lever-free request completes");
    let first = generator.requests().remove(0);
    assert_eq!(first.prompt_options, crate::prompt::PromptOptions::default());
    assert!(first.evidence.iter().all(|block| block.evidence_meta.is_none()));
    let ids: Vec<String> = first
        .evidence
        .iter()
        .map(|block| block.document_id.clone())
        .collect();
    assert!(!ids.is_empty());

    // `binary_answer_format` needs nothing from the snapshot.
    super::execute_query_rag(
        &service,
        QueryRagRequest {
            levers: BINARY.to_vec(),
            ..test_query_request("reranker evidence", "00000000-0000-4000-8000-0000000000f2")
        },
    )
    .await
    .expect("binary_answer_format completes");
    let binary = generator.requests().remove(1);
    assert_eq!(
        binary.prompt_options,
        crate::prompt::PromptOptions {
            evidence_metadata: false,
            binary_answer_format: true
        }
    );
    assert!(binary.evidence.iter().all(|block| block.evidence_meta.is_none()));

    // `evidence_metadata` is refused until the snapshot holds metadata, then admitted.
    let metadata_request = || QueryRagRequest {
        levers: vec![Lever::EvidenceMetadata as i32, Lever::BinaryAnswerFormat as i32],
        ..test_query_request("reranker evidence", "00000000-0000-4000-8000-0000000000f3")
    };
    assert!(super::execute_query_rag(&service, metadata_request())
        .await
        .is_err());
    let prior = Arc::clone(&*service.corpus_store.read().await);
    let map = DocMetaMap::from_entries(ids.iter().map(|id| (id.clone(), headline_meta())));
    *service.corpus_store.write().await =
        Arc::new((*prior).clone().with_doc_meta(Arc::new(map)));

    let response = super::execute_query_rag(&service, metadata_request())
        .await
        .expect("the metadata lever is admitted once the snapshot holds metadata");
    assert_eq!(
        response.snapshot.expect("a snapshot").levers,
        vec![Lever::EvidenceMetadata as i32, Lever::BinaryAnswerFormat as i32]
    );
    let both = generator.requests().remove(2);
    assert_eq!(
        both.prompt_options,
        crate::prompt::PromptOptions {
            evidence_metadata: true,
            binary_answer_format: true
        }
    );
    assert!(!both.evidence.is_empty());
    assert!(both
        .evidence
        .iter()
        .all(|block| block.evidence_meta.as_ref() == Some(&headline_meta())));
    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// The metadata map across an index rebuild (Phase 06.3.6 plan 11 Task 2, D-142)
// ---------------------------------------------------------------------------

/// A service over an empty store whose snapshot already holds metadata, and that map.
async fn service_holding_metadata(
    name: &str,
) -> (String, crate::service::LancetServiceImpl, Arc<DocMetaMap>) {
    let path = database_path(name);
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let service = configured_service(
        &database,
        EffectiveRagSettings::default(),
        Arc::new(FakeEmbedder),
        RecordingGenerator::from_effective_settings(&EffectiveRagSettings::default()),
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;
    let map = fixture_doc_meta();
    {
        let mut store = service.corpus_store.write().await;
        let prior = Arc::clone(&*store);
        *store = Arc::new((*prior).clone().with_doc_meta(Arc::clone(&map)));
    }
    (path, service, map)
}

/// A snapshot that holds a non-empty map keeps that same map after a rebuild that succeeds, so an
/// ingest never silently turns `evidence_metadata` unavailable.
#[tokio::test]
async fn a_successful_rebuild_carries_the_metadata_map_forward() {
    let _lock = crate::ingest::REBUILD_TEST_MUTEX.lock().await;
    let (path, service, map) = service_holding_metadata("levers-meta-rebuild-ok").await;
    let swapped = crate::ingest::rebuild_and_swap(
        &service.database,
        &service.corpus_store,
        service.effective_settings.retrieval.bm25.clone(),
    )
    .await
    .expect("the rebuild succeeds");
    assert!(!swapped.rebuild_degraded);
    assert!(!swapped.doc_meta.is_empty());
    assert!(Arc::ptr_eq(&swapped.doc_meta, &map));
    let current = Arc::clone(&*service.corpus_store.read().await);
    assert!(Arc::ptr_eq(&current.doc_meta, &map));
    let _ = std::fs::remove_dir_all(path);
}

/// The degraded paths keep the prior snapshot whole, the metadata map included.
#[tokio::test]
async fn a_degraded_rebuild_keeps_the_prior_metadata_map() {
    let _lock = crate::ingest::REBUILD_TEST_MUTEX.lock().await;
    let (path, service, map) = service_holding_metadata("levers-meta-rebuild-degraded").await;
    let bm25 = service.effective_settings.retrieval.bm25.clone();

    // The injected fault at the head of the rebuild.
    crate::ingest::arm_rebuild_fail_next();
    let failure = crate::ingest::rebuild_and_swap(&service.database, &service.corpus_store, bm25.clone())
        .await
        .expect_err("the armed fault fails the rebuild");
    assert!(failure.contains("injected"), "{failure}");
    let current = Arc::clone(&*service.corpus_store.read().await);
    assert!(current.rebuild_degraded);
    assert!(Arc::ptr_eq(&current.doc_meta, &map), "injected fault");

    // The latest table version cannot be read.
    crate::ingest::arm_rebuild_checkout_fail_next();
    crate::ingest::rebuild_and_swap(&service.database, &service.corpus_store, bm25.clone())
        .await
        .expect_err("the armed checkout failure fails the rebuild");
    let current = Arc::clone(&*service.corpus_store.read().await);
    assert!(current.rebuild_degraded);
    assert!(Arc::ptr_eq(&current.doc_meta, &map), "checkout failure");

    // The graph index build fails.
    crate::ingest::rebuild_and_swap_with_graph_builder(
        &service.database,
        &service.corpus_store,
        bm25,
        &|_db| Box::pin(async { Err("injected graph index failure".to_string()) }),
    )
    .await
    .expect_err("the failing graph builder fails the rebuild");
    let current = Arc::clone(&*service.corpus_store.read().await);
    assert!(current.rebuild_degraded);
    assert!(Arc::ptr_eq(&current.doc_meta, &map), "graph index failure");
    let _ = std::fs::remove_dir_all(path);
}
