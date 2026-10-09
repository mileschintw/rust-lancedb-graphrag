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
