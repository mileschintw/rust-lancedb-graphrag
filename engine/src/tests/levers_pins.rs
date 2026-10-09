//! Pins for the `levers` request contract (Phase 06.3.6, D-136, D-165).
//!
//! The tracer test sends one request that names a lever through the real service admission and
//! workflow over the existing fakes, and reads the lever back from the final snapshot. The
//! admission matrix rows live in [`super::bad_input_matrix`]; the byte-identity of the default
//! request is pinned by the three recorded goldens.

use std::sync::Arc;

use uuid::Uuid;

use engine::config::EffectiveRagSettings;
use engine::db::DatabaseManager;
use engine::generation;
use engine::ingest::{process_job, read_staged_jobs};
use engine::pb::lancet::v1::{Lever, QueryRagRequest};
use engine::rerank;
use engine::testkit::test_query_request;

use engine::workflow::LeverSet;

use super::retrieval_mode_pins::{render_scenarios, Variation};
use super::{configured_service, database_path, stage_document, FakeEmbedder, FakeGenerator};

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
    let set = LeverSet::try_from_wire(&[Lever::BinaryAnswerFormat as i32, Lever::Rerank as i32])
        .unwrap();
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
