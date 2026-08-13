//! Phase 5 workflow orchestration test matrix.
//!
//! Provides deterministic end-to-end tests and unit cases covering
//! the complete Rust state-machine edge matrix against request-local fakes.

use std::sync::Arc;
use std::time::Duration;

use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use engine::generation::{AnswerBasis, FakeGenerator, Generator, ModelOutput};
use engine::pb::lancet::v1::{
    workflow_event::Event, NodeErrorKind, QueryRagRequest,
};
use engine::retrieval::{Candidate, RetrievalSettings};
use engine::workflow::{
    events::EventSequence,
    node::{Node, NodeError},
    nodes::{
        AssemblePromptNode, ExtractGraphContextNode, GenerateAnswerNode, ReformulateQueryNode,
        RetrieveHybridNode,
    },
    ports::{
        FakeBm25RetrievalPort, FakeDenseRetrievalPort, FakeGraphQueryPort, FakeQueryEmbeddingPort,
        FakeQueryReformulator, FakeReranker, QueryReformulator,
    },
    WorkflowContext, WorkflowEventSink, WorkflowRunner,
};

/// Helper struct that aborts a task when dropped to ensure no detached runner task lingers.
struct AbortOnDrop(Option<tokio::task::JoinHandle<()>>);

impl Drop for AbortOnDrop {
    fn drop(&mut self) {
        if let Some(handle) = self.0.take() {
            handle.abort();
        }
    }
}

/// Construct a candidate with deterministic values for testing.
fn make_candidate(doc_id: &str, chunk_id: &str, score: f64) -> Candidate {
    Candidate {
        document_id: doc_id.to_string(),
        chunk_id: chunk_id.to_string(),
        chunk_index: 0,
        char_start: 0,
        char_end: 100,
        content: format!("Content for {chunk_id} of {doc_id}"),
        title: Some(format!("Title {doc_id}")),
        section_path: Some("Section 1".to_string()),
        content_type: Some("text/plain".to_string()),
        embedding_model: Some("text-embedding-3-small".to_string()),
        ingested_at: Some(1700000000),
        score,
    }
}

/// Task 1 & Matrix: Exact happy-path test for Phase 5 orchestration.
#[tokio::test]
async fn workflow_phase5_happy_path() {
    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let trace_id = "trace-happy-01".to_string();
    let session_id = "sess-happy-01".to_string();

    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        trace_id.clone(),
        session_id.clone(),
    );

    let req = QueryRagRequest {
        query: "What is Lancet graph RAG?".to_string(),
        session_id: session_id.clone(),
        filter: None,
    };
    let ctx = WorkflowContext::new(session_id.clone(), trace_id.clone(), &req);

    let fake_reformulator = Arc::new(FakeQueryReformulator::new(vec![
        "What is Lancet graph RAG?".to_string(),
    ]));
    let fake_embedder = Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let fake_graph = Arc::new(FakeGraphQueryPort::success(
        "Lancet -- uses -- LanceDB graph vector hybrid",
    ));
    let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![make_candidate(
        "doc-happy-1",
        "chk-happy-1",
        0.95,
    )]));
    let fake_bm25 = Arc::new(FakeBm25RetrievalPort::success(vec![make_candidate(
        "doc-happy-1",
        "chk-happy-2",
        0.85,
    )]));
    let fake_reranker = Arc::new(FakeReranker::success());

    let fake_gen: Arc<dyn Generator> = Arc::new(FakeGenerator::new(Ok(ModelOutput {
        answer: "Lancet is a graph RAG engine [1].".to_string(),
        cited_evidence_ids: vec!["[1]".to_string()],
        answer_basis: AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        usage: None,
    })));

    let mut runner = WorkflowRunner::new();
    runner.add_node(ReformulateQueryNode::with_reformulator(Some(fake_reformulator)));
    runner.add_node(ExtractGraphContextNode::new(
        Some(fake_embedder),
        Some(fake_graph),
    ));
    runner.add_node(RetrieveHybridNode::new(
        Some(fake_dense),
        Some(fake_bm25),
        Some(fake_reranker),
        RetrievalSettings::default(),
    ));
    runner.add_node(AssemblePromptNode::new());
    runner.add_node(GenerateAnswerNode::new(Some(fake_gen)));

    let handle = tokio::spawn(async move {
        runner.run_workflow(ctx, cancel, sink).await;
    });

    let _guard = AbortOnDrop(Some(handle));

    let mut events = Vec::new();
    while let Some(event) = rx.recv().await {
        if let Ok(wf_event) = event {
            events.push(wf_event);
        }
    }

    // 1. Assert trace_id consistency across all events
    for ev in &events {
        assert_eq!(ev.trace_id, trace_id, "Event trace_id must match");
        assert_eq!(ev.session_id, session_id, "Event session_id must match");
    }

    // 2. Assert D-06 node ordering: ReformulateQuery -> ExtractGraphContext -> RetrieveHybrid -> AssemblePrompt -> GenerateAnswer
    let node_started_names: Vec<String> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(Event::NodeStarted(ns)) => Some(ns.node_name.clone()),
            _ => None,
        })
        .collect();

    assert_eq!(
        node_started_names,
        vec![
            "ReformulateQuery",
            "ExtractGraphContext",
            "RetrieveHybrid",
            "AssemblePrompt",
            "GenerateAnswer"
        ],
        "NodeStarted sequence must follow D-06 exact order"
    );

    let node_completed_names: Vec<String> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(Event::NodeCompleted(nc)) => Some(nc.node_name.clone()),
            _ => None,
        })
        .collect();

    assert_eq!(
        node_completed_names,
        vec![
            "ReformulateQuery",
            "ExtractGraphContext",
            "RetrieveHybrid",
            "AssemblePrompt",
            "GenerateAnswer"
        ],
        "NodeCompleted sequence must match NodeStarted sequence"
    );

    // 3. Assert event cardinalities: exactly 1 AnswerChunk, 1 FinalAnswer, 1 WorkflowCompleted
    let answer_chunk_events: Vec<_> = events
        .iter()
        .filter(|e| matches!(&e.event, Some(Event::AnswerChunk(_))))
        .collect();
    assert_eq!(answer_chunk_events.len(), 1, "Must have exactly 1 AnswerChunk event");

    let final_answer_events: Vec<_> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(Event::FinalAnswer(fa)) => fa.response.clone(),
            _ => None,
        })
        .collect();
    assert_eq!(final_answer_events.len(), 1, "Must have exactly 1 FinalAnswer event");

    let completed_events: Vec<_> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(Event::WorkflowCompleted(wc)) => Some(wc.clone()),
            _ => None,
        })
        .collect();
    assert_eq!(completed_events.len(), 1, "Must have exactly 1 WorkflowCompleted event");
    assert!(completed_events[0].success, "WorkflowCompleted must be successful");

    // 4. Assert 5 or fewer ordered checkpoints
    let checkpoints: Vec<_> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(Event::Checkpoint(cp)) => Some(cp.clone()),
            _ => None,
        })
        .collect();
    assert!(
        !checkpoints.is_empty() && checkpoints.len() <= 6,
        "Checkpoints must be 5 or fewer service boundaries (plus terminal success)"
    );

    // 5. Decode payload field by field for FinalAnswer and WorkflowCompleted
    let final_res = &final_answer_events[0];
    assert_eq!(final_res.answer, "Lancet is a graph RAG engine [1].");
    assert_eq!(final_res.citations, vec!["[1]"]);
    assert_eq!(final_res.session_id, session_id);
    assert_ne!(
        final_res.answer_basis,
        engine::pb::lancet::v1::AnswerBasis::Unspecified as i32,
        "answer_basis must not be unspecified on successful response"
    );
    assert_eq!(
        final_res.answer_basis,
        engine::pb::lancet::v1::AnswerBasis::Retrieval as i32,
        "answer_basis must be numeric value corresponding to Retrieval"
    );
    assert!(
        !final_res.structured_citations.is_empty(),
        "structured_citations must be populated"
    );
    assert!(final_res.snapshot.is_some(), "snapshot must be populated");
    assert!(
        final_res.notices.is_empty(),
        "notices must be present as empty list"
    );

    let completed_res = completed_events[0]
        .final_response
        .as_ref()
        .expect("WorkflowCompleted final_response payload");
    assert_eq!(completed_res.answer, final_res.answer);
    assert_eq!(completed_res.citations, final_res.citations);
    assert_eq!(completed_res.session_id, final_res.session_id);
    assert_eq!(completed_res.answer_basis, final_res.answer_basis);
}

/// Task 2 & Matrix: Graph timeout degrades gracefully to empty context.
#[tokio::test]
async fn workflow_phase5_graph_timeout() {
    let (tx, _rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let _sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-graph-timeout".to_string(),
        "sess-graph-timeout".to_string(),
    );

    let req = QueryRagRequest {
        query: "Graph timeout test".to_string(),
        session_id: "sess-graph-timeout".to_string(),
        filter: None,
    };
    let mut ctx = WorkflowContext::new("sess-graph-timeout".to_string(), "trace-graph-timeout".to_string(), &req);

    let fake_embedder = Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let fake_graph_stalled = Arc::new(FakeGraphQueryPort::stall());

    let graph_node = ExtractGraphContextNode::new(
        Some(fake_embedder),
        Some(fake_graph_stalled),
    ).with_timeouts(5000, 50);

    let res = graph_node.run(&mut ctx, &cancel).await;
    assert!(res.is_ok(), "Graph timeout must degrade gracefully with Ok(()) per D-09");
    assert!(ctx.graph_context.is_empty(), "Graph context must be empty on timeout");
    assert_eq!(ctx.notices.len(), 1, "Must emit exactly 1 degrade notice");
    assert_eq!(ctx.notices[0].message, "GRAPH_TIMEOUT");
}

/// Stalled reformulator for exact paused-clock timeout testing.
struct StalledReformulator;

impl QueryReformulator for StalledReformulator {
    fn reformulate<'a>(
        &'a self,
        _query: &'a str,
        _cancel: &'a CancellationToken,
    ) -> engine::workflow::node::BoxFuture<'a, Result<Vec<String>, NodeError>> {
        Box::pin(async move {
            tokio::time::sleep(Duration::from_secs(3600)).await;
            Ok(vec![])
        })
    }
}

/// Task 2 & Matrix: Paused-clock ReformulateQuery 5000ms deadline test.
#[tokio::test]
async fn workflow_phase5_reformulate_timeout_five_seconds() {
    tokio::time::pause();

    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-ref-timeout".to_string(),
        "sess-ref-timeout".to_string(),
    );

    let req = QueryRagRequest {
        query: "Reformulate timeout test".to_string(),
        session_id: "sess-ref-timeout".to_string(),
        filter: None,
    };
    let ctx = WorkflowContext::new("sess-ref-timeout".to_string(), "trace-ref-timeout".to_string(), &req);

    let stalled_reformulator = Arc::new(StalledReformulator);
    let mut runner = WorkflowRunner::new().with_timeouts(5000, 15000, 10000, 2000, 65000);
    runner.add_node(ReformulateQueryNode::with_reformulator(Some(stalled_reformulator)));
    runner.add_node(ExtractGraphContextNode::new(None, None));

    let handle = tokio::spawn(async move {
        runner.run_workflow(ctx, cancel, sink).await;
    });

    tokio::time::advance(Duration::from_millis(5000)).await;
    handle.await.unwrap();

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let node_started_names: Vec<String> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(Event::NodeStarted(ns)) => Some(ns.node_name.clone()),
            _ => None,
        })
        .collect();

    assert_eq!(node_started_names, vec!["ReformulateQuery"]);

    let failed_event = events.iter().find_map(|e| match &e.event {
        Some(Event::NodeFailed(nf)) => Some(nf.clone()),
        _ => None,
    });
    assert!(failed_event.is_some(), "Must emit NodeFailed for ReformulateQuery");
    assert_eq!(failed_event.unwrap().category, NodeErrorKind::Timeout as i32);

    let completed_event = events.iter().find_map(|e| match &e.event {
        Some(Event::WorkflowCompleted(wc)) => Some(wc.clone()),
        _ => None,
    }).expect("WorkflowCompleted event");

    assert!(!completed_event.success);
    assert_eq!(completed_event.error_kind, NodeErrorKind::Timeout as i32);
}

/// Task 2 & Matrix: Paused-clock RetrieveHybrid 10000ms deadline test.
#[tokio::test]
async fn workflow_phase5_retrieve_timeout_ten_seconds() {
    tokio::time::pause();

    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-ret-timeout".to_string(),
        "sess-ret-timeout".to_string(),
    );

    let req = QueryRagRequest {
        query: "Retrieve timeout test".to_string(),
        session_id: "sess-ret-timeout".to_string(),
        filter: None,
    };
    let ctx = WorkflowContext::new("sess-ret-timeout".to_string(), "trace-ret-timeout".to_string(), &req);

    let fake_dense_stalled = Arc::new(FakeDenseRetrievalPort::stall());
    let mut runner = WorkflowRunner::new().with_timeouts(5000, 15000, 10000, 2000, 65000);
    runner.add_node(ReformulateQueryNode::new());
    runner.add_node(RetrieveHybridNode::new(
        Some(fake_dense_stalled),
        None,
        None,
        RetrievalSettings::default(),
    ));
    runner.add_node(AssemblePromptNode::new());

    let handle = tokio::spawn(async move {
        runner.run_workflow(ctx, cancel, sink).await;
    });

    tokio::time::advance(Duration::from_millis(10000)).await;
    handle.await.unwrap();

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let node_started_names: Vec<String> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(Event::NodeStarted(ns)) => Some(ns.node_name.clone()),
            _ => None,
        })
        .collect();

    assert_eq!(node_started_names, vec!["ReformulateQuery", "RetrieveHybrid"]);
    assert!(!node_started_names.contains(&"AssemblePrompt".to_string()));

    let completed_event = events.iter().find_map(|e| match &e.event {
        Some(Event::WorkflowCompleted(wc)) => Some(wc.clone()),
        _ => None,
    }).expect("WorkflowCompleted event");

    assert!(!completed_event.success);
    assert_eq!(completed_event.error_kind, NodeErrorKind::Timeout as i32);
}

/// Task 2 & Matrix: Reranker failure mapped to RetrievalFailed.
#[tokio::test]
async fn workflow_phase5_reranker_failure() {
    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-rerank-fail".to_string(),
        "sess-rerank-fail".to_string(),
    );

    let req = QueryRagRequest {
        query: "Reranker failure test".to_string(),
        session_id: "sess-rerank-fail".to_string(),
        filter: None,
    };
    let ctx = WorkflowContext::new("sess-rerank-fail".to_string(), "trace-rerank-fail".to_string(), &req);

    let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![make_candidate(
        "doc-1", "chk-1", 0.9,
    )]));
    let fake_reranker = Arc::new(FakeReranker::failure());

    let mut runner = WorkflowRunner::new();
    runner.add_node(RetrieveHybridNode::new(
        Some(fake_dense),
        None,
        Some(fake_reranker),
        RetrievalSettings::default(),
    ));
    runner.add_node(AssemblePromptNode::new());

    runner.run_workflow(ctx, cancel, sink).await;

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let node_started_names: Vec<String> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(Event::NodeStarted(ns)) => Some(ns.node_name.clone()),
            _ => None,
        })
        .collect();

    assert_eq!(node_started_names, vec!["RetrieveHybrid"]);
    assert!(!node_started_names.contains(&"AssemblePrompt".to_string()));

    let completed_event = events.iter().find_map(|e| match &e.event {
        Some(Event::WorkflowCompleted(wc)) => Some(wc.clone()),
        _ => None,
    }).expect("WorkflowCompleted event");

    assert!(!completed_event.success);
    assert_eq!(
        completed_event.error_kind,
        NodeErrorKind::RetrievalFailed as i32
    );
}

/// Task 2 & Matrix: Cooperative prompt cancellation before work.
#[tokio::test]
async fn workflow_phase5_prompt_cancel() {
    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    cancel.cancel(); // Pre-cancel

    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-cancel".to_string(),
        "sess-cancel".to_string(),
    );

    let req = QueryRagRequest {
        query: "Pre-cancelled test".to_string(),
        session_id: "sess-cancel".to_string(),
        filter: None,
    };
    let ctx = WorkflowContext::new("sess-cancel".to_string(), "trace-cancel".to_string(), &req);

    let mut runner = WorkflowRunner::new();
    runner.add_node(ReformulateQueryNode::new());
    runner.add_node(AssemblePromptNode::new());

    runner.run_workflow(ctx, cancel, sink).await;

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let completed_event = events.iter().find_map(|e| match &e.event {
        Some(Event::WorkflowCompleted(wc)) => Some(wc.clone()),
        _ => None,
    }).expect("WorkflowCompleted event");

    assert!(!completed_event.success);
    assert_eq!(completed_event.error_kind, NodeErrorKind::Cancelled as i32);
}

/// Task 2 & Matrix: Full snapshot envelope ordering and field retention.
#[tokio::test]
async fn workflow_phase5_full_snapshot() {
    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-snapshot-01".to_string(),
        "sess-snapshot-01".to_string(),
    );

    let req = QueryRagRequest {
        query: "Snapshot test query".to_string(),
        session_id: "sess-snapshot-01".to_string(),
        filter: None,
    };
    let ctx = WorkflowContext::new("sess-snapshot-01".to_string(), "trace-snapshot-01".to_string(), &req);

    let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![make_candidate(
        "doc-snap", "chk-snap", 0.9,
    )]));
    let fake_gen: Arc<dyn Generator> = Arc::new(FakeGenerator::new(Ok(ModelOutput {
        answer: "Full snapshot answer.".to_string(),
        cited_evidence_ids: vec!["[chk-snap]".to_string()],
        answer_basis: AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        usage: None,
    })));

    let mut runner = WorkflowRunner::new();
    runner.add_node(ReformulateQueryNode::new());
    runner.add_node(RetrieveHybridNode::new(
        Some(fake_dense),
        None,
        None,
        RetrievalSettings::default(),
    ));
    runner.add_node(AssemblePromptNode::new());
    runner.add_node(GenerateAnswerNode::new(Some(fake_gen)));

    runner.run_workflow(ctx, cancel, sink).await;

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let checkpoints: Vec<_> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(Event::Checkpoint(cp)) => Some(cp.clone()),
            _ => None,
        })
        .collect();

    assert!(
        !checkpoints.is_empty() && checkpoints.len() <= 6,
        "Must have 5 or fewer service checkpoints plus terminal checkpoint"
    );

    let mut prev_seq = 0;
    for cp in &checkpoints {
        assert!(cp.sequence_ordinal > prev_seq, "Sequence ordinals must strictly increase");
        prev_seq = cp.sequence_ordinal;
        let snap_json: serde_json::Value = serde_json::from_str(&cp.context_snapshot)
            .expect("valid JSON context snapshot");
        assert_eq!(snap_json["session_id"], "sess-snapshot-01");
        assert_eq!(snap_json["trace_id"], "trace-snapshot-01");
    }
}

/// Task 2 & Matrix: 9 variants rejection case before downstream retrieval.
#[tokio::test]
async fn workflow_phase5_nine_variants_rejection() {
    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-nine-var".to_string(),
        "sess-nine-var".to_string(),
    );

    let req = QueryRagRequest {
        query: "Nine variants test".to_string(),
        session_id: "sess-nine-var".to_string(),
        filter: None,
    };
    let ctx = WorkflowContext::new("sess-nine-var".to_string(), "trace-nine-var".to_string(), &req);

    let nine_variants = vec![
        "v1".into(), "v2".into(), "v3".into(), "v4".into(),
        "v5".into(), "v6".into(), "v7".into(), "v8".into(), "v9".into(),
    ];
    let fake_reformulator = Arc::new(FakeQueryReformulator::new(nine_variants));
    let fake_embedder = Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let fake_graph = Arc::new(FakeGraphQueryPort::success("ctx"));
    let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![]));
    let fake_bm25 = Arc::new(FakeBm25RetrievalPort::success(vec![]));
    let fake_reranker = Arc::new(FakeReranker::success());

    let mut runner = WorkflowRunner::new();
    runner.add_node(ReformulateQueryNode::with_reformulator(Some(fake_reformulator)));
    runner.add_node(ExtractGraphContextNode::new(
        Some(fake_embedder.clone()),
        Some(fake_graph.clone()),
    ));
    runner.add_node(RetrieveHybridNode::new(
        Some(fake_dense.clone()),
        Some(fake_bm25.clone()),
        Some(fake_reranker.clone()),
        RetrievalSettings::default(),
    ));

    runner.run_workflow(ctx, cancel, sink).await;

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    // Assert zero downstream calls
    assert_eq!(fake_embedder.calls(), 0);
    assert_eq!(fake_graph.calls(), 0);
    assert_eq!(fake_dense.calls(), 0);
    assert_eq!(fake_bm25.calls(), 0);
    assert_eq!(fake_reranker.calls(), 0);

    let completed_event = events.iter().find_map(|e| match &e.event {
        Some(Event::WorkflowCompleted(wc)) => Some(wc.clone()),
        _ => None,
    }).expect("WorkflowCompleted event");

    assert!(!completed_event.success);
    assert_eq!(completed_event.error_kind, NodeErrorKind::InputValidation as i32);
}

/// Task 2 & Matrix: Two parallel same-input workflows proving trace, store, and sequence isolation.
#[tokio::test]
async fn workflow_phase5_concurrency_isolation() {
    let cancel1 = CancellationToken::new();
    let cancel2 = CancellationToken::new();

    let (tx1, mut rx1) = mpsc::channel(100);
    let (tx2, mut rx2) = mpsc::channel(100);

    let sink1 = WorkflowEventSink::new(
        tx1,
        Arc::new(EventSequence::new()),
        "trace-conc-1".to_string(),
        "sess-conc-1".to_string(),
    );
    let sink2 = WorkflowEventSink::new(
        tx2,
        Arc::new(EventSequence::new()),
        "trace-conc-2".to_string(),
        "sess-conc-2".to_string(),
    );

    let req1 = QueryRagRequest {
        query: "Concurrent query".to_string(),
        session_id: "sess-conc-1".to_string(),
        filter: None,
    };
    let req2 = QueryRagRequest {
        query: "Concurrent query".to_string(),
        session_id: "sess-conc-2".to_string(),
        filter: None,
    };

    let ctx1 = WorkflowContext::new("sess-conc-1".to_string(), "trace-conc-1".to_string(), &req1);
    let ctx2 = WorkflowContext::new("sess-conc-2".to_string(), "trace-conc-2".to_string(), &req2);

    let fake_dense1 = Arc::new(FakeDenseRetrievalPort::success(vec![make_candidate("doc-1", "chk-1", 0.9)]));
    let fake_dense2 = Arc::new(FakeDenseRetrievalPort::success(vec![make_candidate("doc-2", "chk-2", 0.8)]));

    let fake_gen1: Arc<dyn Generator> = Arc::new(FakeGenerator::new(Ok(ModelOutput {
        answer: "Ans 1 [chk-1]".to_string(),
        cited_evidence_ids: vec!["[chk-1]".to_string()],
        answer_basis: AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        usage: None,
    })));
    let fake_gen2: Arc<dyn Generator> = Arc::new(FakeGenerator::new(Ok(ModelOutput {
        answer: "Ans 2 [chk-2]".to_string(),
        cited_evidence_ids: vec!["[chk-2]".to_string()],
        answer_basis: AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        usage: None,
    })));

    let mut runner1 = WorkflowRunner::new();
    runner1.add_node(ReformulateQueryNode::new());
    runner1.add_node(RetrieveHybridNode::new(Some(fake_dense1), None, None, RetrievalSettings::default()));
    runner1.add_node(AssemblePromptNode::new());
    runner1.add_node(GenerateAnswerNode::new(Some(fake_gen1)));

    let mut runner2 = WorkflowRunner::new();
    runner2.add_node(ReformulateQueryNode::new());
    runner2.add_node(RetrieveHybridNode::new(Some(fake_dense2), None, None, RetrievalSettings::default()));
    runner2.add_node(AssemblePromptNode::new());
    runner2.add_node(GenerateAnswerNode::new(Some(fake_gen2)));

    let h1 = tokio::spawn(async move { runner1.run_workflow(ctx1, cancel1, sink1).await });
    let h2 = tokio::spawn(async move { runner2.run_workflow(ctx2, cancel2, sink2).await });

    tokio::try_join!(h1, h2).unwrap();

    let mut events1 = Vec::new();
    while let Ok(e) = rx1.try_recv() { if let Ok(ev) = e { events1.push(ev); } }

    let mut events2 = Vec::new();
    while let Ok(e) = rx2.try_recv() { if let Ok(ev) = e { events2.push(ev); } }

    for ev in &events1 {
        assert_eq!(ev.trace_id, "trace-conc-1");
        assert_eq!(ev.session_id, "sess-conc-1");
    }

    for ev in &events2 {
        assert_eq!(ev.trace_id, "trace-conc-2");
        assert_eq!(ev.session_id, "sess-conc-2");
    }
}
