//! Tests for the graph seeding diagnostics and the per-chunk graph flag on the wire
//! (06.3.4.1-16, D-79, D-81).
//!
//! `WorkflowMetadata` carries `graph_seed_count`, `graph_path_found`, `graph_boosted_chunk_count`,
//! `graph_degree_capped_count` and `graph_seed_document_ids`; every chunk of the snapshot's
//! `retrieved_chunks` carries `graph_boosted`. The tests drive the real runner over the fakes (so
//! the values come from the context the nodes filled, not from the test), then once over the
//! production ports and a temp store.

use std::sync::Arc;

use futures::StreamExt;
use prost::Message;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::db::DatabaseManager;
use crate::generation::{
    AnswerBasis, FakeGenerator, GenerationError, GenerationErrorKind, Generator, ModelOutput,
};
use crate::pb::lancet::v1::{
    workflow_event::Event, StructuredCitation, WorkflowCompletedEvent, WorkflowMetadata,
};
use crate::prompt::{DEFAULT_ANSWER_TOKEN_BUDGET, DEFAULT_MAX_PROMPT_TOKENS};
use crate::retrieval::{Candidate, RetrievalSettings};
use crate::testkit::test_query_request;
use crate::workflow::events::EventSequence;
use crate::workflow::nodes::{
    AssemblePromptNode, ExtractGraphContextNode, GenerateAnswerNode, RetrieveHybridNode,
};
use crate::workflow::ports::{
    FakeBm25RetrievalPort, FakeDenseRetrievalPort, FakeGraphQueryPort, FakeQueryEmbeddingPort,
    GraphQueryOutput,
};
use crate::workflow::{WorkflowContext, WorkflowEventSink, WorkflowRunner};

const DOC_A: &str = "00000000-0000-4000-8000-0000000000c1";
const DOC_B: &str = "00000000-0000-4000-8000-0000000000c2";

fn chunk_id(doc: &str, index: i32) -> String {
    format!("{doc}:{index}")
}

fn row(doc: &str, index: i32, score: f64) -> Candidate {
    Candidate {
        document_id: doc.to_owned(),
        chunk_id: chunk_id(doc, index),
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

/// What the graph port reports for a query whose seeds were joined by a path to chunk `B:3`.
fn path_output() -> GraphQueryOutput {
    GraphQueryOutput {
        seed_count: 2,
        path_found: true,
        // Not zero, so a field copied from the wrong source cannot pass by being zero.
        degree_capped_count: 3,
        seed_document_ids: vec![DOC_A.to_owned(), DOC_B.to_owned()],
        chunk_candidates: vec![chunk_id(DOC_B, 3)],
        ..GraphQueryOutput::default()
    }
}

fn answering_generator() -> Arc<dyn Generator> {
    Arc::new(FakeGenerator::new(Ok(ModelOutput {
        answer: "An answer [1].".to_owned(),
        cited_evidence_ids: vec!["[1]".to_owned()],
        answer_basis: AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        final_answer: None,
        usage: None,
    })))
}

fn failing_generator() -> Arc<dyn Generator> {
    Arc::new(FakeGenerator::new(Err(GenerationError::new(
        GenerationErrorKind::ProviderError,
        "synthetic permanent failure",
    ))))
}

/// Runs the whole workflow over the fakes and returns the terminal event.
///
/// The dense port finds two chunks; the one the graph names (`B:3`) is only reachable through the
/// by-ID fetch, so it enters the retrieved set only when the graph list is applied.
async fn run_workflow(
    graph: Option<GraphQueryOutput>,
    disable_graph: bool,
    generator: Arc<dyn Generator>,
) -> WorkflowCompletedEvent {
    let (tx, mut rx) = mpsc::channel(100);
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-wire".to_owned(),
        "sess-wire".to_owned(),
    );
    let mut request = test_query_request("alpha", "sess-wire");
    request.disable_graph_context = Some(disable_graph);
    let ctx = WorkflowContext::new("sess-wire".to_owned(), "trace-wire".to_owned(), &request);

    let dense = Arc::new(
        FakeDenseRetrievalPort::success(vec![row(DOC_A, 0, 0.9), row(DOC_A, 1, 0.8)])
            .with_chunk_rows(vec![row(DOC_B, 3, 0.0)]),
    );
    let mut runner = WorkflowRunner::new();
    runner.add_node(ExtractGraphContextNode::new(
        Some(Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 2048]))),
        graph.map(|output| Arc::new(FakeGraphQueryPort::success_output(output)) as _),
    ));
    runner.add_node(RetrieveHybridNode::new(
        Some(dense),
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
    runner.add_node(GenerateAnswerNode::new(Some(generator)));
    runner
        .run_workflow(ctx, CancellationToken::new(), sink)
        .await;

    let mut completed = None;
    while let Ok(item) = rx.try_recv() {
        if let Ok(event) = item {
            if let Some(Event::WorkflowCompleted(wc)) = event.event {
                completed = Some(wc);
            }
        }
    }
    completed.expect("the workflow emits a terminal event")
}

/// The snapshot a terminal event carries: the final response's on success, the partial one on
/// failure.
fn snapshot_of(completed: &WorkflowCompletedEvent) -> &crate::pb::lancet::v1::RetrievalSnapshot {
    completed
        .final_response
        .as_ref()
        .and_then(|response| response.snapshot.as_ref())
        .or(completed.partial_snapshot.as_ref())
        .expect("a terminal event carries a retrieval snapshot")
}

fn flagged(completed: &WorkflowCompletedEvent) -> Vec<String> {
    snapshot_of(completed)
        .retrieved_chunks
        .iter()
        .filter(|chunk| chunk.graph_boosted)
        .map(|chunk| chunk.chunk_id.clone())
        .collect()
}

// ---- the metadata and the flag over the fakes -------------------------------------------------

#[tokio::test]
async fn a_graph_on_workflow_emits_the_seeding_diagnostics_and_flags_one_retrieved_chunk() {
    let completed = run_workflow(Some(path_output()), false, answering_generator()).await;
    assert!(completed.success, "{}", completed.error_message);

    let meta = completed.metadata.as_ref().expect("metadata is present");
    assert_eq!(meta.graph_seed_count, 2);
    assert!(meta.graph_path_found);
    assert_eq!(meta.graph_boosted_chunk_count, 1);
    assert_eq!(meta.graph_degree_capped_count, 3);
    assert_eq!(
        meta.graph_seed_document_ids,
        vec![DOC_A.to_owned(), DOC_B.to_owned()]
    );

    // Exactly one retrieved chunk is flagged, and it is the graph's; the others say so explicitly.
    assert_eq!(flagged(&completed), vec![chunk_id(DOC_B, 3)]);
    let retrieved = &snapshot_of(&completed).retrieved_chunks;
    assert!(retrieved.len() >= 3, "dense found two, the graph added one");
    assert_eq!(
        meta.graph_boosted_chunk_count as usize,
        retrieved.iter().filter(|chunk| chunk.graph_boosted).count(),
        "the count and the per-chunk flags describe the same final set"
    );
}

#[tokio::test]
async fn the_generators_cited_chunks_never_carry_the_flag() {
    // The flag belongs to the retrieved set (D-81); a citation says only which chunk was cited.
    let completed = run_workflow(Some(path_output()), false, answering_generator()).await;
    let response = completed.final_response.as_ref().expect("a final response");
    assert!(
        !response.structured_citations.is_empty(),
        "the answer cites the first chunk"
    );
    assert!(response
        .structured_citations
        .iter()
        .all(|citation| !citation.graph_boosted));
}

#[tokio::test]
async fn a_graph_off_workflow_emits_zero_diagnostics_and_flags_no_chunk() {
    // A caller-requested ablation: the port exists but is never asked.
    let completed = run_workflow(Some(path_output()), true, answering_generator()).await;
    assert!(completed.success, "{}", completed.error_message);
    let meta = completed.metadata.as_ref().expect("metadata is present");
    assert_eq!(meta.graph_seed_count, 0);
    assert!(!meta.graph_path_found);
    assert_eq!(meta.graph_boosted_chunk_count, 0);
    assert_eq!(meta.graph_degree_capped_count, 0);
    assert!(meta.graph_seed_document_ids.is_empty());
    assert!(flagged(&completed).is_empty());

    // No graph port at all is the same.
    let without_port = run_workflow(None, false, answering_generator()).await;
    let meta = without_port.metadata.as_ref().expect("metadata is present");
    assert_eq!(meta.graph_seed_count, 0);
    assert!(meta.graph_seed_document_ids.is_empty());
    assert!(flagged(&without_port).is_empty());
}

#[tokio::test]
async fn seeds_without_a_path_are_visible_on_the_wire_and_boost_nothing() {
    // Paths-only: seeds that no path joins give no chunk candidates, but the seeding is measured.
    let output = GraphQueryOutput {
        seed_count: 2,
        path_found: false,
        degree_capped_count: 1,
        seed_document_ids: vec![DOC_A.to_owned(), DOC_B.to_owned()],
        chunk_candidates: vec![],
        ..GraphQueryOutput::default()
    };
    let completed = run_workflow(Some(output), false, answering_generator()).await;
    let meta = completed.metadata.as_ref().expect("metadata is present");
    assert_eq!(meta.graph_seed_count, 2);
    assert!(!meta.graph_path_found);
    assert_eq!(meta.graph_degree_capped_count, 1);
    assert_eq!(
        meta.graph_seed_document_ids,
        vec![DOC_A.to_owned(), DOC_B.to_owned()]
    );
    assert_eq!(meta.graph_boosted_chunk_count, 0);
    assert!(flagged(&completed).is_empty());
}

#[tokio::test]
async fn a_failed_workflow_still_carries_the_diagnostics_and_the_flag() {
    // Generation fails after retrieval, so the diagnostics are on a failure record too, and the
    // partial snapshot carries the flags.
    let completed = run_workflow(Some(path_output()), false, failing_generator()).await;
    assert!(!completed.success);
    let meta = completed.metadata.as_ref().expect("metadata is present");
    assert_eq!(meta.graph_seed_count, 2);
    assert!(meta.graph_path_found);
    assert_eq!(meta.graph_boosted_chunk_count, 1);
    assert_eq!(meta.graph_degree_capped_count, 3);
    assert_eq!(meta.graph_seed_document_ids.len(), 2);
    assert_eq!(flagged(&completed), vec![chunk_id(DOC_B, 3)]);
}

// ---- the wire format --------------------------------------------------------------------------

#[test]
fn the_new_fields_use_the_next_free_tags_and_survive_a_round_trip() {
    // Tag keys are `(tag << 3) | wire_type`: varint is 0, length-delimited is 2.
    let only = |meta: WorkflowMetadata| meta.encode_to_vec();
    assert_eq!(
        only(WorkflowMetadata {
            graph_seed_count: 5,
            ..WorkflowMetadata::default()
        }),
        vec![12 << 3, 5]
    );
    assert_eq!(
        only(WorkflowMetadata {
            graph_path_found: true,
            ..WorkflowMetadata::default()
        }),
        vec![13 << 3, 1]
    );
    assert_eq!(
        only(WorkflowMetadata {
            graph_boosted_chunk_count: 7,
            ..WorkflowMetadata::default()
        }),
        vec![14 << 3, 7]
    );
    assert_eq!(
        only(WorkflowMetadata {
            graph_degree_capped_count: 9,
            ..WorkflowMetadata::default()
        }),
        vec![15 << 3, 9]
    );
    // Tag 16 is 0x82 0x01 as a two-byte varint key.
    assert_eq!(
        only(WorkflowMetadata {
            graph_seed_document_ids: vec!["d".to_owned()],
            ..WorkflowMetadata::default()
        }),
        vec![0x82, 0x01, 1, b'd']
    );
    assert_eq!(
        StructuredCitation {
            graph_boosted: true,
            ..StructuredCitation::default()
        }
        .encode_to_vec(),
        vec![10 << 3, 1]
    );

    let metadata = WorkflowMetadata {
        started_at_ms: 1,
        graph_prompt_fact_count: 4,
        graph_seed_count: 2,
        graph_path_found: true,
        graph_boosted_chunk_count: 1,
        graph_degree_capped_count: 3,
        graph_seed_document_ids: vec![DOC_A.to_owned(), DOC_B.to_owned()],
        ..WorkflowMetadata::default()
    };
    let decoded = WorkflowMetadata::decode(metadata.encode_to_vec().as_slice()).unwrap();
    assert_eq!(decoded, metadata);
    let citation = StructuredCitation {
        chunk_id: "c".to_owned(),
        graph_boosted: true,
        ..StructuredCitation::default()
    };
    assert_eq!(
        StructuredCitation::decode(citation.encode_to_vec().as_slice()).unwrap(),
        citation
    );
}

#[test]
fn a_message_written_before_the_fields_existed_decodes_to_their_defaults() {
    // A message from an older engine has none of tags 12 to 16: tags up to 11 only.
    let older = WorkflowMetadata {
        vector_count: 6,
        graph_prompt_fact_count: 2,
        ..WorkflowMetadata::default()
    }
    .encode_to_vec();
    let decoded = WorkflowMetadata::decode(older.as_slice()).unwrap();
    assert_eq!(decoded.vector_count, 6);
    assert_eq!(decoded.graph_prompt_fact_count, 2);
    assert_eq!(decoded.graph_seed_count, 0);
    assert!(!decoded.graph_path_found);
    assert!(decoded.graph_seed_document_ids.is_empty());
}

#[test]
fn the_workflow_span_declares_and_records_the_two_new_fields() {
    // Recording a field the span never declared is a silent no-op, so the declaration in the
    // service and the record in the runner are pinned together.
    let service = include_str!("../service.rs");
    let runner = include_str!("../workflow/runner.rs");
    for field in ["graph_seed_count", "graph_path_found"] {
        let name = format!("\"lancet.workflow.{field}\"");
        assert!(
            service.contains(&format!("{name} = tracing::field::Empty")),
            "service.rs must declare {name} on the query_rag span"
        );
        assert!(
            runner.contains(&format!("record({name}, ")),
            "runner.rs must record {name}"
        );
    }
    // Counts and a boolean only: nothing that names a question or an entity goes on the span.
    assert!(!runner.contains("lancet.workflow.graph_seed_document_ids"));
}

// ---- the production ports ---------------------------------------------------------------------

/// A graph-on question over the production ports and a temp store: the values on the wire come
/// from the real graph index and the real chunk fetch.
#[tokio::test]
async fn a_production_graph_on_query_puts_the_seed_documents_and_the_boost_on_the_wire() {
    use crate::graph::extraction::{
        ExtractedEntity, ExtractedRelation, ExtractionOutput, FakeExtractionGenerator,
    };
    use crate::ingest::{extract_and_persist_entities, process_job, read_staged_jobs};
    use crate::pb::lancet::v1::lancet_service_server::LancetService;
    use crate::tests::{query_rag_graph_service_with_db, stage_document, FakeEmbedder};

    const FILLER_ONE: &str = "00000000-0000-4000-8000-0000000000f1";
    const FILLER_TWO: &str = "00000000-0000-4000-8000-0000000000f2";
    const GRAPH_DOC: &str = "ffffffff-ffff-4fff-8fff-fffffffffff1";

    let path = format!(
        "{}/lancet-graph-wire-{}",
        std::env::temp_dir().display(),
        uuid::Uuid::new_v4()
    );
    let database = DatabaseManager::initialize(&path).await.unwrap();
    for (document_id, text) in [
        (FILLER_ONE, "Compost heaps need turning every week."),
        (FILLER_TWO, "Rain barrels fill during the autumn."),
        (GRAPH_DOC, "Tomato seedlings prefer a sunny windowsill."),
    ] {
        stage_document(&database, document_id, text.as_bytes()).await;
    }
    let jobs = read_staged_jobs(&database).await.unwrap();
    for job in &jobs {
        process_job(job, &database, &FakeEmbedder).await.unwrap();
    }
    let graph_job = jobs
        .iter()
        .find(|job| job.document_id == GRAPH_DOC)
        .expect("the graph document was staged");
    let extraction = FakeExtractionGenerator::new(Ok(ExtractionOutput {
        entities: vec![
            ExtractedEntity {
                name: "Alice".into(),
                entity_type: "person".into(),
            },
            ExtractedEntity {
                name: "Bob".into(),
                entity_type: "person".into(),
            },
        ],
        relations: vec![ExtractedRelation {
            source: "Alice".into(),
            target: "Bob".into(),
            relation_type: "knows".into(),
            confidence: 0.9,
        }],
    }));
    extract_and_persist_entities(&database, graph_job, &extraction, &FakeEmbedder)
        .await
        .unwrap();

    let mut service = query_rag_graph_service_with_db(database).await;
    service.effective_settings.retrieval.candidate_limit = 2;
    service.effective_settings.retrieval.final_limit = 2;

    let mut stream = service
        .query_rag(tonic::Request::new(test_query_request(
            "Alice knows Bob",
            "00000000-0000-4000-8000-000000000001",
        )))
        .await
        .expect("query_rag opens a stream")
        .into_inner();
    let mut completed = None;
    while let Some(item) = stream.next().await {
        if let Some(Event::WorkflowCompleted(wc)) = item.expect("a stream item").event {
            completed = Some(wc);
        }
    }
    let completed = completed.expect("the stream ends with a terminal event");

    let meta = completed.metadata.as_ref().expect("metadata is present");
    assert_eq!(meta.graph_seed_count, 2, "Alice and Bob are the seeds");
    assert!(meta.graph_path_found);
    assert_eq!(meta.graph_degree_capped_count, 0);
    assert_eq!(
        meta.graph_seed_document_ids,
        vec![GRAPH_DOC.to_owned()],
        "both seeds come from one document, listed once"
    );
    assert_eq!(meta.graph_boosted_chunk_count, 1);
    assert_eq!(flagged(&completed), vec![chunk_id(GRAPH_DOC, 0)]);
    let unflagged = snapshot_of(&completed)
        .retrieved_chunks
        .iter()
        .filter(|chunk| !chunk.graph_boosted)
        .count();
    assert_eq!(unflagged, 1, "the other retrieved place is a dense filler");

    drop(service);
    let _ = std::fs::remove_dir_all(path);
}
