//! Pins for the `levers` request contract (Phase 06.3.6, D-136, D-165).
//!
//! The tracer test sends one request that names a lever through the real service admission and
//! workflow over the existing fakes, and reads the lever back from the final snapshot. The
//! admission matrix rows live in [`super::bad_input_matrix`]; the byte-identity of the default
//! request is pinned by the three recorded goldens.

use std::sync::Arc;
use std::time::Duration;

use uuid::Uuid;

use engine::config::EffectiveRagSettings;
use engine::db::DatabaseManager;
use engine::generation;
use engine::ingest::{process_job, read_staged_jobs};
use engine::pb::lancet::v1::{Lever, QueryRagRequest, RerankOutcome};
use engine::rerank;
use engine::testkit::test_query_request;

use engine::workflow::LeverSet;

use crate::service::LeverResources;
use crate::workflow::nodes::retrieve::{rerank_allowance, RERANK_NODE_RESERVE_MS};
use crate::workflow::ports::FakeReranker;
use crate::workflow::WorkflowContext;

use super::retrieval_mode_pins::{render_scenarios, run_chain, run_runner, Fixture, Variation};
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
