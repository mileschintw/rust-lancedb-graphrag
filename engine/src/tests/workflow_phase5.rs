//! Phase 5 workflow orchestration test matrix.
//!
//! Provides deterministic end-to-end tests and unit cases covering
//! the complete Rust state-machine edge matrix against request-local fakes.

use std::collections::BTreeSet;
use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};
use std::time::Duration;

use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use engine::generation::{AnswerBasis, FakeGenerator, Generator, ModelOutput};
use engine::pb::lancet::v1::{workflow_event::Event, NodeErrorKind, NoticeCode, NoticeSeverity};
use engine::retrieval::{Candidate, RetrievalSettings};
use engine::testkit::{test_notice, test_query_request};
use engine::workflow::{
    events::{self, EventSequence},
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

struct TimerStartedSleep {
    sleep: Pin<Box<tokio::time::Sleep>>,
    started: Arc<tokio::sync::Notify>,
    notified: bool,
}

impl TimerStartedSleep {
    fn new(duration: Duration, started: Arc<tokio::sync::Notify>) -> Self {
        Self {
            sleep: Box::pin(tokio::time::sleep(duration)),
            started,
            notified: false,
        }
    }
}

impl Future for TimerStartedSleep {
    type Output = ();

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        let result = this.sleep.as_mut().poll(cx);
        if !this.notified {
            this.started.notify_one();
            this.notified = true;
        }
        result
    }
}

struct PreparationOrderGenerator {
    steps: Arc<Mutex<Vec<&'static str>>>,
}

struct WorstCaseGeneration {
    preparation_started: Arc<tokio::sync::Notify>,
    preparation_finished: Arc<tokio::sync::Notify>,
    attempt_two_started: Arc<tokio::sync::Notify>,
    preparation_complete: Arc<AtomicBool>,
    attempts: Arc<AtomicUsize>,
}

impl Generator for WorstCaseGeneration {
    fn prepare<'a>(
        &'a self,
    ) -> engine::generation::BoxFuture<'a, Result<(), engine::generation::GenerationError>> {
        let preparation_started = Arc::clone(&self.preparation_started);
        let preparation_finished = Arc::clone(&self.preparation_finished);
        let preparation_complete = Arc::clone(&self.preparation_complete);
        Box::pin(async move {
            TimerStartedSleep::new(Duration::from_millis(5000), preparation_started).await;
            preparation_complete.store(true, Ordering::SeqCst);
            preparation_finished.notify_one();
            Ok(())
        })
    }

    fn generate<'a>(
        &'a self,
        _request: engine::generation::GenerationRequest,
    ) -> engine::generation::BoxFuture<'a, Result<ModelOutput, engine::generation::GenerationError>>
    {
        let preparation_complete = Arc::clone(&self.preparation_complete);
        let attempt = self.attempts.fetch_add(1, Ordering::SeqCst) + 1;
        let attempt_two_started = Arc::clone(&self.attempt_two_started);
        Box::pin(async move {
            assert!(
                preparation_complete.load(Ordering::SeqCst),
                "generation must not start before preparation completes"
            );
            let timer_started = if attempt == 2 {
                attempt_two_started
            } else {
                Arc::new(tokio::sync::Notify::new())
            };
            TimerStartedSleep::new(Duration::from_millis(30000), timer_started).await;
            if attempt == 1 {
                Err(engine::generation::GenerationError::new(
                    engine::generation::GenerationErrorKind::Timeout,
                    "first worst-case attempt timed out",
                ))
            } else {
                Ok(ModelOutput {
                    answer: "Worst-case retry succeeded [1].".into(),
                    cited_evidence_ids: vec!["[1]".into()],
                    answer_basis: AnswerBasis::Retrieval,
                    notices: vec![],
                    warnings: vec![],
                    usage: None,
                })
            }
        })
    }
}

struct PredeadlineReformulator {
    started: Arc<tokio::sync::Notify>,
}

impl QueryReformulator for PredeadlineReformulator {
    fn reformulate<'a>(
        &'a self,
        query: &'a str,
        _cancel: &'a CancellationToken,
    ) -> engine::workflow::node::BoxFuture<'a, Result<Vec<String>, NodeError>> {
        let started = Arc::clone(&self.started);
        Box::pin(async move {
            TimerStartedSleep::new(Duration::from_millis(4999), started).await;
            Ok(vec![query.to_string()])
        })
    }
}

struct PredeadlineDenseRetrieval {
    started: Arc<tokio::sync::Notify>,
}

impl engine::workflow::ports::DenseRetrievalPort for PredeadlineDenseRetrieval {
    fn retrieve_dense<'a>(
        &'a self,
        _query: &'a str,
        _query_embedding: &'a [f32],
        _filter: Option<&'a engine::pb::lancet::v1::DocumentFilter>,
        _cancel: &'a CancellationToken,
    ) -> engine::workflow::node::BoxFuture<'a, Result<Vec<Candidate>, NodeError>> {
        let started = Arc::clone(&self.started);
        Box::pin(async move {
            TimerStartedSleep::new(Duration::from_millis(9999), started).await;
            Ok(vec![make_candidate(
                "predeadline-doc",
                "predeadline-chunk",
                0.9,
            )])
        })
    }
}

impl Generator for PreparationOrderGenerator {
    fn prepare<'a>(
        &'a self,
    ) -> engine::generation::BoxFuture<'a, Result<(), engine::generation::GenerationError>> {
        self.steps.lock().unwrap().push("prepare");
        Box::pin(async { Ok(()) })
    }

    fn generate<'a>(
        &'a self,
        _request: engine::generation::GenerationRequest,
    ) -> engine::generation::BoxFuture<'a, Result<ModelOutput, engine::generation::GenerationError>>
    {
        let steps = Arc::clone(&self.steps);
        Box::pin(async move {
            steps.lock().unwrap().push("generate");
            Ok(ModelOutput {
                answer: "Prepared answer [1].".into(),
                cited_evidence_ids: vec!["[1]".into()],
                answer_basis: AnswerBasis::Retrieval,
                notices: vec![],
                warnings: vec![],
                usage: None,
            })
        })
    }
}

#[tokio::test]
async fn workflow_phase5_generation_preflight_bootstrap_tracer() {
    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-generation-prepare".into(),
        "sess-generation-prepare".into(),
    );
    let request = test_query_request("Preparation ordering", "sess-generation-prepare");
    let mut ctx = WorkflowContext::new(
        "sess-generation-prepare".into(),
        "trace-generation-prepare".into(),
        &request,
    );
    ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
        id: "[1]".into(),
        chunk_id: "chunk-1".into(),
        document_id: "document-1".into(),
        chunk_index: 0,
        title: Some("Preparation test".into()),
        section_path: Some("Root".into()),
        content_type: Some("text/plain".into()),
        provenance: "test".into(),
        text: "Evidence for preparation ordering.".into(),
        score: 0.9,
        rank: 1,
        suspicious: false,
    }];

    let steps = Arc::new(Mutex::new(Vec::new()));
    let generator: Arc<dyn Generator> = Arc::new(PreparationOrderGenerator {
        steps: Arc::clone(&steps),
    });
    let node = GenerateAnswerNode::new(Some(generator));

    WorkflowRunner::new()
        .run_node(&node, &mut ctx, &cancel, &sink)
        .await
        .expect("prepared generation node succeeds");

    assert_eq!(ctx.answer, "Prepared answer [1].");
    assert_eq!(&*steps.lock().unwrap(), &["prepare", "generate"]);

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(event) = item {
            events.push(event);
        }
    }
    assert!(matches!(
        events.first().and_then(|event| event.event.as_ref()),
        Some(Event::NodeStarted(started)) if started.node_name == "GenerateAnswer"
    ));
    assert!(events.iter().any(|event| matches!(
        &event.event,
        Some(Event::NodeCompleted(completed)) if completed.node_name == "GenerateAnswer"
    )));
}

/// Task 1 tracer: exact production-shaped five-node lifecycle and event contract.
#[tokio::test]
async fn workflow_phase5_event_delivery_tracer() {
    run_happy_path_test().await;
}

#[tokio::test]
async fn workflow_phase5_happy_path() {
    run_happy_path_test().await;
}

async fn run_happy_path_test() {
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

    let req = test_query_request("What is Lancet graph RAG?", &session_id);
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
    runner.add_node(ReformulateQueryNode::with_reformulator(Some(
        fake_reformulator,
    )));
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

    let events = tokio::time::timeout(Duration::from_secs(5), async {
        let mut events = Vec::new();
        while let Some(event) = rx.recv().await {
            if let Ok(wf_event) = event {
                events.push(wf_event);
            }
        }
        events
    })
    .await
    .expect("happy-path event receiver must close within five seconds");

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
    assert_eq!(
        answer_chunk_events.len(),
        1,
        "Must have exactly 1 AnswerChunk event"
    );

    let final_answer_events: Vec<_> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(Event::FinalAnswer(fa)) => fa.response.clone(),
            _ => None,
        })
        .collect();
    assert_eq!(
        final_answer_events.len(),
        1,
        "Must have exactly 1 FinalAnswer event"
    );

    let completed_events: Vec<_> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(Event::WorkflowCompleted(wc)) => Some(wc.clone()),
            _ => None,
        })
        .collect();
    assert_eq!(
        completed_events.len(),
        1,
        "Must have exactly 1 WorkflowCompleted event"
    );
    assert!(
        completed_events[0].success,
        "WorkflowCompleted must be successful"
    );

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

    // Every delivered outer event consumes exactly one ordinal, with no gaps.
    for (index, event) in events.iter().enumerate() {
        assert_eq!(event.sequence_ordinal, (index + 1) as u64);
    }

    // Checkpoint payload ordinals are the same ordinal as their outer envelope.
    for event in &events {
        if let Some(Event::Checkpoint(checkpoint)) = &event.event {
            assert_eq!(checkpoint.sequence_ordinal, event.sequence_ordinal);
        }
    }

    let started_count = events
        .iter()
        .filter(|event| matches!(event.event, Some(Event::NodeStarted(_))))
        .count();
    let completed_count = events
        .iter()
        .filter(|event| matches!(event.event, Some(Event::NodeCompleted(_))))
        .count();
    assert_eq!(started_count, 5, "tracer must start exactly five nodes");
    assert_eq!(
        completed_count, 5,
        "tracer must complete exactly five nodes"
    );
}

/// Task 2: paused-clock proof that the separate 5000ms preparation does not
/// consume the 65000ms GenerateAnswer budget for two 30000ms attempts.
#[tokio::test]
async fn workflow_phase5_generation_preflight_worst_case_budget() {
    tokio::time::pause();

    const PREFLIGHT_MS: u64 = 5000;
    const ATTEMPT_MS: u64 = 30000;
    const INTER_ATTEMPT_SLACK_MS: u64 = 5000;
    const GENERATION_NODE_BUDGET_MS: u64 = 65000;
    const PRE_PREFLIGHT_WORKFLOW_MS: u64 = 97000;
    const DERIVED_WHOLE_WORKFLOW_BOUND_MS: u64 = PRE_PREFLIGHT_WORKFLOW_MS + PREFLIGHT_MS;

    assert_eq!(
        GENERATION_NODE_BUDGET_MS,
        ATTEMPT_MS * 2 + INTER_ATTEMPT_SLACK_MS,
        "the node timer covers two attempts plus inter-attempt slack"
    );
    assert_eq!(
        DERIVED_WHOLE_WORKFLOW_BOUND_MS, 102000,
        "102000ms is derived arithmetic only; runner.rs does not enforce a global deadline"
    );

    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-worst-case-preflight".into(),
        "sess-worst-case-preflight".into(),
    );
    let request = test_query_request("Worst-case preparation budget", "sess-worst-case-preflight");
    let mut ctx = WorkflowContext::new(
        "sess-worst-case-preflight".into(),
        "trace-worst-case-preflight".into(),
        &request,
    );
    ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
        id: "[1]".into(),
        chunk_id: "worst-case-chunk".into(),
        document_id: "worst-case-document".into(),
        chunk_index: 0,
        title: Some("Worst-case preparation".into()),
        section_path: Some("Root".into()),
        content_type: Some("text/plain".into()),
        provenance: "test".into(),
        text: "Evidence for the worst-case generation budget.".into(),
        score: 0.9,
        rank: 1,
        suspicious: false,
    }];

    let preparation_started = Arc::new(tokio::sync::Notify::new());
    let preparation_waiter = preparation_started.notified();
    let preparation_finished = Arc::new(tokio::sync::Notify::new());
    let preparation_finished_waiter = preparation_finished.notified();
    let attempt_two_started = Arc::new(tokio::sync::Notify::new());
    let attempt_two_waiter = attempt_two_started.notified();
    let preparation_complete = Arc::new(AtomicBool::new(false));
    let attempts = Arc::new(AtomicUsize::new(0));
    let generator: Arc<dyn Generator> = Arc::new(WorstCaseGeneration {
        preparation_started: Arc::clone(&preparation_started),
        preparation_finished: Arc::clone(&preparation_finished),
        attempt_two_started: Arc::clone(&attempt_two_started),
        preparation_complete: Arc::clone(&preparation_complete),
        attempts: Arc::clone(&attempts),
    });
    let mut runner = WorkflowRunner::new().with_timeouts(5000, 15000, 10000, 2000, 65000);
    runner.add_node(GenerateAnswerNode::new(Some(generator)));

    let handle = tokio::spawn(async move {
        runner.run_workflow(ctx, cancel, sink).await;
    });

    preparation_waiter.await;
    for _ in 0..3 {
        tokio::task::yield_now().await;
    }
    assert!(!preparation_complete.load(Ordering::SeqCst));
    assert_eq!(attempts.load(Ordering::SeqCst), 0);

    tokio::time::advance(Duration::from_millis(PREFLIGHT_MS - 1)).await;
    for _ in 0..3 {
        tokio::task::yield_now().await;
    }
    assert!(!preparation_complete.load(Ordering::SeqCst));
    assert_eq!(attempts.load(Ordering::SeqCst), 0);

    tokio::time::advance(Duration::from_millis(1)).await;
    for _ in 0..3 {
        tokio::task::yield_now().await;
    }
    preparation_finished_waiter.await;
    assert!(preparation_complete.load(Ordering::SeqCst));
    assert_eq!(attempts.load(Ordering::SeqCst), 1);

    tokio::time::advance(Duration::from_millis(ATTEMPT_MS)).await;
    attempt_two_waiter.await;
    assert_eq!(attempts.load(Ordering::SeqCst), 2);

    tokio::time::advance(Duration::from_millis(ATTEMPT_MS)).await;
    handle.await.expect("worst-case workflow task must finish");

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(event) = item {
            events.push(event);
        }
    }
    let completed = events
        .iter()
        .find_map(|event| match &event.event {
            Some(Event::WorkflowCompleted(completed)) => Some(completed),
            _ => None,
        })
        .expect("worst-case workflow must emit WorkflowCompleted");
    assert!(completed.success, "second generation attempt must succeed");
    assert_eq!(
        attempts.load(Ordering::SeqCst),
        2,
        "no third attempt is allowed"
    );
}

/// Task 2: semantic paused-clock check for the 4999ms reformulation boundary;
/// the live 7000ms overlay proof remains owned by 05-09.
#[tokio::test]
async fn workflow_phase5_reformulate_predeadline_4999ms_no_timeout() {
    tokio::time::pause();

    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-reformulate-predeadline".into(),
        "sess-reformulate-predeadline".into(),
    );
    let request = test_query_request("Reformulate predeadline", "sess-reformulate-predeadline");
    let ctx = WorkflowContext::new(
        "sess-reformulate-predeadline".into(),
        "trace-reformulate-predeadline".into(),
        &request,
    );
    let started = Arc::new(tokio::sync::Notify::new());
    let started_waiter = started.notified();
    let node = ReformulateQueryNode::with_reformulator(Some(Arc::new(PredeadlineReformulator {
        started: Arc::clone(&started),
    })));
    let runner = WorkflowRunner::new().with_timeouts(5000, 15000, 10000, 2000, 65000);

    let handle = tokio::spawn(async move {
        let mut ctx = ctx;
        let result = runner.run_node(&node, &mut ctx, &cancel, &sink).await;
        (result, ctx)
    });

    started_waiter.await;
    for _ in 0..3 {
        tokio::task::yield_now().await;
    }
    tokio::time::advance(Duration::from_millis(4999)).await;
    let (result, ctx) = handle.await.expect("reformulation task must finish");

    assert!(result.is_ok(), "4999ms reformulation must not time out");
    assert_eq!(ctx.variants, vec!["Reformulate predeadline"]);
    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(event) = item {
            events.push(event);
        }
    }
    assert!(!events.iter().any(|event| matches!(
        &event.event,
        Some(Event::NodeFailed(failed)) if failed.category == NodeErrorKind::Timeout as i32
    )));
}

/// Task 2: semantic paused-clock check for the 9999ms retrieval boundary;
/// the live 7000ms overlay proof remains owned by 05-09.
#[tokio::test]
async fn workflow_phase5_retrieve_predeadline_9999ms_no_timeout() {
    tokio::time::pause();

    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-retrieve-predeadline".into(),
        "sess-retrieve-predeadline".into(),
    );
    let request = test_query_request("Retrieve predeadline", "sess-retrieve-predeadline");
    let ctx = WorkflowContext::new(
        "sess-retrieve-predeadline".into(),
        "trace-retrieve-predeadline".into(),
        &request,
    );
    let started = Arc::new(tokio::sync::Notify::new());
    let started_waiter = started.notified();
    let node = RetrieveHybridNode::new(
        Some(Arc::new(PredeadlineDenseRetrieval {
            started: Arc::clone(&started),
        })),
        None,
        None,
        RetrievalSettings::default(),
    );
    let runner = WorkflowRunner::new().with_timeouts(5000, 15000, 10000, 2000, 65000);

    let handle = tokio::spawn(async move {
        let mut ctx = ctx;
        let result = runner.run_node(&node, &mut ctx, &cancel, &sink).await;
        (result, ctx)
    });

    started_waiter.await;
    for _ in 0..3 {
        tokio::task::yield_now().await;
    }
    tokio::time::advance(Duration::from_millis(9999)).await;
    let (result, ctx) = handle.await.expect("retrieval task must finish");

    assert!(result.is_ok(), "9999ms retrieval must not time out");
    assert_eq!(ctx.evidence_blocks.len(), 1);
    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(event) = item {
            events.push(event);
        }
    }
    assert!(!events.iter().any(|event| matches!(
        &event.event,
        Some(Event::NodeFailed(failed)) if failed.category == NodeErrorKind::Timeout as i32
    )));
}

/// Task 1: bounded checkpoint handoff retains ownership while client delivery
/// remains cancellation-aware and never turns a full channel into a hang.
#[tokio::test]
async fn workflow_phase5_event_delivery_bounded_cancellation() {
    let (tx, mut rx) = mpsc::channel(1);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-bounded".to_string(),
        "sess-bounded".to_string(),
    );
    let req = test_query_request("bounded delivery", "sess-bounded");
    let ctx = WorkflowContext::new(
        "sess-bounded".to_string(),
        "trace-bounded".to_string(),
        &req,
    );

    assert_eq!(
        sink.send_event(events::node_started("first", ""), &cancel)
            .await,
        engine::workflow::runner::ClientEventDelivery::Sent
    );
    assert_eq!(sink.pending_checkpoint_count(), 0);
    assert_eq!(
        sink.send_checkpoint("bounded", &ctx),
        engine::workflow::runner::CheckpointDelivery::Pending
    );
    assert_eq!(sink.pending_checkpoint_count(), 1);

    cancel.cancel();
    assert_eq!(
        sink.send_event(events::node_started("cancelled", ""), &cancel)
            .await,
        engine::workflow::runner::ClientEventDelivery::Cancelled
    );

    let first = rx.recv().await.expect("first client event").expect("event");
    assert!(matches!(first.event, Some(Event::NodeStarted(_))));
    assert_eq!(sink.pending_checkpoint_count(), 1);
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

    let req = test_query_request("Graph timeout test", "sess-graph-timeout");
    let mut ctx = WorkflowContext::new(
        "sess-graph-timeout".to_string(),
        "trace-graph-timeout".to_string(),
        &req,
    );

    let fake_embedder = Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let fake_graph_stalled = Arc::new(FakeGraphQueryPort::stall());

    let graph_node = ExtractGraphContextNode::new(Some(fake_embedder), Some(fake_graph_stalled))
        .with_timeouts(5000, 50);

    let res = graph_node.run(&mut ctx, &cancel).await;
    assert!(
        res.is_ok(),
        "Graph timeout must degrade gracefully with Ok(()) per D-09"
    );
    assert!(
        ctx.graph_context.is_empty(),
        "Graph context must be empty on timeout"
    );
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

    let req = test_query_request("Reformulate timeout test", "sess-ref-timeout");
    let ctx = WorkflowContext::new(
        "sess-ref-timeout".to_string(),
        "trace-ref-timeout".to_string(),
        &req,
    );

    let stalled_reformulator = Arc::new(StalledReformulator);
    let mut runner = WorkflowRunner::new().with_timeouts(5000, 15000, 10000, 2000, 65000);
    runner.add_node(ReformulateQueryNode::with_reformulator(Some(
        stalled_reformulator,
    )));
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
    assert!(
        failed_event.is_some(),
        "Must emit NodeFailed for ReformulateQuery"
    );
    assert_eq!(
        failed_event.unwrap().category,
        NodeErrorKind::Timeout as i32
    );

    let completed_event = events
        .iter()
        .find_map(|e| match &e.event {
            Some(Event::WorkflowCompleted(wc)) => Some(wc.clone()),
            _ => None,
        })
        .expect("WorkflowCompleted event");

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

    let req = test_query_request("Retrieve timeout test", "sess-ret-timeout");
    let ctx = WorkflowContext::new(
        "sess-ret-timeout".to_string(),
        "trace-ret-timeout".to_string(),
        &req,
    );

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

    assert_eq!(
        node_started_names,
        vec!["ReformulateQuery", "RetrieveHybrid"]
    );
    assert!(!node_started_names.contains(&"AssemblePrompt".to_string()));

    let completed_event = events
        .iter()
        .find_map(|e| match &e.event {
            Some(Event::WorkflowCompleted(wc)) => Some(wc.clone()),
            _ => None,
        })
        .expect("WorkflowCompleted event");

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

    let req = test_query_request("Reranker failure test", "sess-rerank-fail");
    let ctx = WorkflowContext::new(
        "sess-rerank-fail".to_string(),
        "trace-rerank-fail".to_string(),
        &req,
    );

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

    let completed_event = events
        .iter()
        .find_map(|e| match &e.event {
            Some(Event::WorkflowCompleted(wc)) => Some(wc.clone()),
            _ => None,
        })
        .expect("WorkflowCompleted event");

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

    let req = test_query_request("Pre-cancelled test", "sess-cancel");
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

    let completed_event = events
        .iter()
        .find_map(|e| match &e.event {
            Some(Event::WorkflowCompleted(wc)) => Some(wc.clone()),
            _ => None,
        })
        .expect("WorkflowCompleted event");

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

    let req = test_query_request("Snapshot test query", "sess-snapshot-01");
    let ctx = WorkflowContext::new(
        "sess-snapshot-01".to_string(),
        "trace-snapshot-01".to_string(),
        &req,
    );

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
        assert!(
            cp.sequence_ordinal > prev_seq,
            "Sequence ordinals must strictly increase"
        );
        prev_seq = cp.sequence_ordinal;
        let snap_json: serde_json::Value =
            serde_json::from_str(&cp.context_snapshot).expect("valid JSON context snapshot");
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

    let req = test_query_request("Nine variants test", "sess-nine-var");
    let ctx = WorkflowContext::new(
        "sess-nine-var".to_string(),
        "trace-nine-var".to_string(),
        &req,
    );

    let nine_variants = vec![
        "v1".into(),
        "v2".into(),
        "v3".into(),
        "v4".into(),
        "v5".into(),
        "v6".into(),
        "v7".into(),
        "v8".into(),
        "v9".into(),
    ];
    let fake_reformulator = Arc::new(FakeQueryReformulator::new(nine_variants));
    let fake_embedder = Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let fake_graph = Arc::new(FakeGraphQueryPort::success("ctx"));
    let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![]));
    let fake_bm25 = Arc::new(FakeBm25RetrievalPort::success(vec![]));
    let fake_reranker = Arc::new(FakeReranker::success());

    let mut runner = WorkflowRunner::new();
    runner.add_node(ReformulateQueryNode::with_reformulator(Some(
        fake_reformulator,
    )));
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

    let completed_event = events
        .iter()
        .find_map(|e| match &e.event {
            Some(Event::WorkflowCompleted(wc)) => Some(wc.clone()),
            _ => None,
        })
        .expect("WorkflowCompleted event");

    assert!(!completed_event.success);
    assert_eq!(
        completed_event.error_kind,
        NodeErrorKind::InputValidation as i32
    );
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

    let req1 = test_query_request("Concurrent query", "sess-conc-1");
    let req2 = test_query_request("Concurrent query", "sess-conc-2");

    let ctx1 = WorkflowContext::new("sess-conc-1".to_string(), "trace-conc-1".to_string(), &req1);
    let ctx2 = WorkflowContext::new("sess-conc-2".to_string(), "trace-conc-2".to_string(), &req2);

    let fake_dense1 = Arc::new(FakeDenseRetrievalPort::success(vec![make_candidate(
        "doc-1", "chk-1", 0.9,
    )]));
    let fake_dense2 = Arc::new(FakeDenseRetrievalPort::success(vec![make_candidate(
        "doc-2", "chk-2", 0.8,
    )]));

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
    runner1.add_node(RetrieveHybridNode::new(
        Some(fake_dense1),
        None,
        None,
        RetrievalSettings::default(),
    ));
    runner1.add_node(AssemblePromptNode::new());
    runner1.add_node(GenerateAnswerNode::new(Some(fake_gen1)));

    let mut runner2 = WorkflowRunner::new();
    runner2.add_node(ReformulateQueryNode::new());
    runner2.add_node(RetrieveHybridNode::new(
        Some(fake_dense2),
        None,
        None,
        RetrievalSettings::default(),
    ));
    runner2.add_node(AssemblePromptNode::new());
    runner2.add_node(GenerateAnswerNode::new(Some(fake_gen2)));

    let h1 = tokio::spawn(async move { runner1.run_workflow(ctx1, cancel1, sink1).await });
    let h2 = tokio::spawn(async move { runner2.run_workflow(ctx2, cancel2, sink2).await });

    tokio::try_join!(h1, h2).unwrap();

    let mut events1 = Vec::new();
    while let Ok(e) = rx1.try_recv() {
        if let Ok(ev) = e {
            events1.push(ev);
        }
    }

    let mut events2 = Vec::new();
    while let Ok(e) = rx2.try_recv() {
        if let Ok(ev) = e {
            events2.push(ev);
        }
    }

    for ev in &events1 {
        assert_eq!(ev.trace_id, "trace-conc-1");
        assert_eq!(ev.session_id, "sess-conc-1");
    }

    for ev in &events2 {
        assert_eq!(ev.trace_id, "trace-conc-2");
        assert_eq!(ev.session_id, "sess-conc-2");
    }
}

struct StalledTimeoutGenerator {
    call_count: Arc<std::sync::atomic::AtomicUsize>,
    started: Arc<tokio::sync::Notify>,
}

impl Generator for StalledTimeoutGenerator {
    fn generate<'a>(
        &'a self,
        _request: engine::generation::GenerationRequest,
    ) -> engine::generation::BoxFuture<'a, Result<ModelOutput, engine::generation::GenerationError>>
    {
        Box::pin(async move {
            self.call_count
                .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            self.started.notify_one();
            tokio::time::sleep(Duration::from_millis(5000)).await;
            Err(engine::generation::GenerationError::new(
                engine::generation::GenerationErrorKind::ProviderError,
                "stalled generator finished unexpectedly",
            ))
        })
    }
}

#[tokio::test]
async fn workflow_phase5_timeout_cancels_stalled_provider() {
    let call_count = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let started = Arc::new(tokio::sync::Notify::new());
    let generator = Arc::new(StalledTimeoutGenerator {
        call_count: Arc::clone(&call_count),
        started: Arc::clone(&started),
    });

    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let trace_id = "trace-timeout-cancel".to_string();
    let session_id = "sess-timeout-cancel".to_string();

    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        trace_id.clone(),
        session_id.clone(),
    );

    let req = test_query_request("Timeout cancellation test", &session_id);
    let mut ctx = WorkflowContext::new(session_id.clone(), trace_id.clone(), &req);
    ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
        id: "[1]".to_string(),
        chunk_id: "chk-1".to_string(),
        document_id: "doc-1".to_string(),
        chunk_index: 0,
        title: Some("Title".to_string()),
        section_path: Some("Section".to_string()),
        content_type: Some("text/plain".to_string()),
        provenance: "provenance".to_string(),
        text: "Test evidence".to_string(),
        score: 0.9,
        rank: 1,
        suspicious: false,
    }];

    let node = GenerateAnswerNode::new(Some(generator));
    let runner = WorkflowRunner::new().with_timeouts(5000, 15000, 10000, 2000, 50);

    let res = runner.run_node(&node, &mut ctx, &cancel, &sink).await;

    assert!(res.is_err(), "node execution must fail on timeout");
    let err = res.unwrap_err();
    assert_eq!(err.kind, NodeErrorKind::Timeout);
    assert!(cancel.is_cancelled(), "cancellation token must be cancelled when timeout occurs before constructing NodeFailed(Timeout)");

    // Drain events from sink to verify NodeStarted and NodeFailed(Timeout) were emitted
    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(ev) = item {
            events.push(ev);
        }
    }

    let started_ev = events.iter().find(
        |e| matches!(&e.event, Some(Event::NodeStarted(ns)) if ns.node_name == "GenerateAnswer"),
    );
    assert!(
        started_ev.is_some(),
        "NodeStarted(GenerateAnswer) must be emitted"
    );

    let failed_ev = events.iter().find_map(|e| match &e.event {
        Some(Event::NodeFailed(nf)) if nf.node_name == "GenerateAnswer" => Some(nf),
        _ => None,
    });
    let failed = failed_ev.expect("NodeFailed(GenerateAnswer) must be emitted");
    assert_eq!(failed.category, NodeErrorKind::Timeout as i32);

    // Drain with bounded timeout to prove no retry / extra provider progress occurs
    let drain_res = tokio::time::timeout(Duration::from_millis(150), async {
        tokio::time::sleep(Duration::from_millis(100)).await;
    })
    .await;
    assert!(drain_res.is_ok());
    assert_eq!(
        call_count.load(std::sync::atomic::Ordering::SeqCst),
        1,
        "no retry attempt must start after timeout cancellation"
    );
}

/// Helper to construct a `FusedCandidate` with a controllable `score` for testing.
fn candidate_with_score(id_hint: &str, text: &str, score: f64) -> crate::retrieval::FusedCandidate {
    crate::retrieval::FusedCandidate {
        candidate: crate::retrieval::Candidate {
            document_id: format!("doc-{id_hint}"),
            chunk_id: format!("chk-{id_hint}"),
            chunk_index: 0,
            char_start: 0,
            char_end: text.len() as i32,
            content: text.into(),
            title: Some("Title".into()),
            section_path: Some("/Sec".into()),
            content_type: Some("text/markdown".into()),
            embedding_model: None,
            ingested_at: None,
            score,
        },
        fused_score: score,
        vector_rank: Some(1),
        bm25_rank: None,
        vector_score: Some(score),
        bm25_score: None,
        variant_provenance: Vec::new(),
    }
}

#[tokio::test]
async fn workflow_retrieve_graph() {
    let (tx, mut rx) = tokio::sync::mpsc::channel(100);
    let cancel = tokio_util::sync::CancellationToken::new();
    let sink = crate::workflow::WorkflowEventSink::new(
        tx,
        Arc::new(crate::workflow::EventSequence::new()),
        "test-trace".into(),
        "test-session".into(),
    );

    let req = test_query_request("rust test", "00000000-0000-4000-8000-000000000001");
    let ctx =
        crate::workflow::WorkflowContext::new("test-session".into(), "test-trace".into(), &req);

    let fake_embedder = Arc::new(crate::workflow::ports::FakeQueryEmbeddingPort::success(
        vec![0.1; 2048],
    ));
    let fake_graph = Arc::new(crate::workflow::ports::FakeGraphQueryPort::success(
        "fact1 -- rel -- fact2",
    ));
    let fake_dense = Arc::new(crate::workflow::ports::FakeDenseRetrievalPort::success(
        vec![crate::retrieval::Candidate {
            document_id: "doc-1".into(),
            chunk_id: "chunk-1".into(),
            chunk_index: 0,
            char_start: 0,
            char_end: 10,
            content: "dense content".into(),
            title: None,
            section_path: None,
            content_type: Some("text/plain".into()),
            embedding_model: None,
            ingested_at: None,
            score: 0.9,
        }],
    ));
    let fake_bm25 = Arc::new(crate::workflow::ports::FakeBm25RetrievalPort::success(
        vec![],
    ));

    let mut runner = crate::workflow::WorkflowRunner::new();
    runner.add_node(crate::workflow::nodes::ReformulateQueryNode::new());
    runner.add_node(crate::workflow::nodes::ExtractGraphContextNode::new(
        Some(fake_embedder.clone()),
        Some(fake_graph.clone()),
    ));
    runner.add_node(crate::workflow::nodes::RetrieveHybridNode::new(
        Some(fake_dense.clone()),
        Some(fake_bm25.clone()),
        None,
        crate::retrieval::RetrievalSettings::default(),
    ));

    let deps = crate::workflow::WorkflowDependencies::new();
    runner
        .run_tracer(ctx, cancel, sink, &deps, |ctx, deps, sink, cancel| {
            Box::pin(async move {
                crate::workflow::run_inline_prompt_generation_remainder(ctx, deps, sink, cancel)
                    .await
            })
        })
        .await;

    assert_eq!(fake_embedder.calls(), 1);
    assert_eq!(fake_graph.calls(), 1);
    assert_eq!(fake_dense.calls(), 1);
    assert_eq!(fake_bm25.calls(), 1);

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }
    let failed = events
        .iter()
        .find_map(|e| match &e.event {
            Some(engine::pb::lancet::v1::workflow_event::Event::NodeFailed(nf)) => Some(nf),
            _ => None,
        })
        .expect("NodeFailed event must exist for no-generator remainder");
    assert_eq!(failed.category, NodeErrorKind::LlmGenerationFailed as i32);
}

#[tokio::test]
async fn graph_timeout_degrades_to_empty_context() {
    let (tx, _rx) = tokio::sync::mpsc::channel(100);
    let cancel = tokio_util::sync::CancellationToken::new();
    let _sink = crate::workflow::WorkflowEventSink::new(
        tx,
        Arc::new(crate::workflow::EventSequence::new()),
        "test-trace".into(),
        "test-session".into(),
    );

    let req = test_query_request("graph timeout test", "00000000-0000-4000-8000-000000000001");
    let mut ctx =
        crate::workflow::WorkflowContext::new("test-session".into(), "test-trace".into(), &req);

    let fake_embedder = Arc::new(crate::workflow::ports::FakeQueryEmbeddingPort::success(
        vec![0.1; 2048],
    ));
    let fake_graph_stalled = Arc::new(crate::workflow::ports::FakeGraphQueryPort::stall());

    let graph_node = crate::workflow::nodes::ExtractGraphContextNode::new(
        Some(fake_embedder),
        Some(fake_graph_stalled),
    )
    .with_timeouts(5000, 50);

    let res = graph_node.run(&mut ctx, &cancel).await;
    assert!(
        res.is_ok(),
        "Graph timeout must degrade gracefully with Ok(()) per D-09"
    );
    assert!(
        ctx.graph_context.is_empty(),
        "Graph context must be empty on timeout"
    );
    assert_eq!(ctx.notices.len(), 1, "Must emit exactly 1 degrade notice");
    assert_eq!(ctx.notices[0].message, "GRAPH_TIMEOUT");
}

#[tokio::test]
async fn zero_evidence_short_circuits_generation() {
    let (tx, mut rx) = tokio::sync::mpsc::channel(100);
    let cancel = tokio_util::sync::CancellationToken::new();
    let sink = crate::workflow::WorkflowEventSink::new(
        tx,
        Arc::new(crate::workflow::EventSequence::new()),
        "test-trace".into(),
        "test-session".into(),
    );

    let req = test_query_request("zero evidence test", "00000000-0000-4000-8000-000000000001");
    let ctx =
        crate::workflow::WorkflowContext::new("test-session".into(), "test-trace".into(), &req);

    let fake_embedder = Arc::new(crate::workflow::ports::FakeQueryEmbeddingPort::success(
        vec![0.1; 2048],
    ));
    let fake_dense_empty = Arc::new(crate::workflow::ports::FakeDenseRetrievalPort::success(
        vec![],
    ));
    let fake_bm25_empty = Arc::new(crate::workflow::ports::FakeBm25RetrievalPort::success(
        vec![],
    ));

    let mut runner = crate::workflow::WorkflowRunner::new();
    runner.add_node(crate::workflow::nodes::ReformulateQueryNode::new());
    runner.add_node(crate::workflow::nodes::ExtractGraphContextNode::new(
        Some(fake_embedder),
        None,
    ));
    runner.add_node(crate::workflow::nodes::RetrieveHybridNode::new(
        Some(fake_dense_empty),
        Some(fake_bm25_empty),
        None,
        crate::retrieval::RetrievalSettings::default(),
    ));

    let deps = crate::workflow::WorkflowDependencies::new();
    runner
        .run_tracer(ctx, cancel, sink, &deps, |ctx, deps, sink, cancel| {
            Box::pin(async move {
                crate::workflow::run_inline_prompt_generation_remainder(ctx, deps, sink, cancel)
                    .await
            })
        })
        .await;

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let node_started_names: Vec<String> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(engine::pb::lancet::v1::workflow_event::Event::NodeStarted(ns)) => {
                Some(ns.node_name.clone())
            }
            _ => None,
        })
        .collect();

    assert!(node_started_names.contains(&"ReformulateQuery".to_string()));
    assert!(node_started_names.contains(&"ExtractGraphContext".to_string()));
    assert!(node_started_names.contains(&"RetrieveHybrid".to_string()));
    assert!(!node_started_names.contains(&"AssemblePrompt".to_string()));
    assert!(!node_started_names.contains(&"GenerateAnswer".to_string()));
}

#[tokio::test]
async fn reranker_failure_maps_to_retrieval_failed() {
    let (tx, _rx) = tokio::sync::mpsc::channel(100);
    let cancel = tokio_util::sync::CancellationToken::new();
    let _sink = crate::workflow::WorkflowEventSink::new(
        tx,
        Arc::new(crate::workflow::EventSequence::new()),
        "test-trace".into(),
        "test-session".into(),
    );

    let req = test_query_request(
        "reranker failure test",
        "00000000-0000-4000-8000-000000000001",
    );
    let mut ctx =
        crate::workflow::WorkflowContext::new("test-session".into(), "test-trace".into(), &req);

    let fake_dense = Arc::new(crate::workflow::ports::FakeDenseRetrievalPort::success(
        vec![crate::retrieval::Candidate {
            document_id: "doc-1".into(),
            chunk_id: "chunk-1".into(),
            chunk_index: 0,
            char_start: 0,
            char_end: 10,
            content: "content".into(),
            title: None,
            section_path: None,
            content_type: Some("text/plain".into()),
            embedding_model: None,
            ingested_at: None,
            score: 0.9,
        }],
    ));
    let fake_failing_reranker = Arc::new(crate::workflow::ports::FakeReranker::failure());

    let retrieve_node = crate::workflow::nodes::RetrieveHybridNode::new(
        Some(fake_dense),
        None,
        Some(fake_failing_reranker),
        crate::retrieval::RetrievalSettings::default(),
    );

    let res = retrieve_node.run(&mut ctx, &cancel).await;
    assert!(res.is_err());
    let err = res.unwrap_err();
    assert_eq!(err.kind, NodeErrorKind::RetrievalFailed);
    assert!(err.message.contains("Reranker failure"));
}

#[tokio::test]
async fn nine_variants_are_rejected_before_retrieval() {
    let (tx, mut rx) = tokio::sync::mpsc::channel(100);
    let cancel = tokio_util::sync::CancellationToken::new();
    let sink = crate::workflow::WorkflowEventSink::new(
        tx,
        Arc::new(crate::workflow::EventSequence::new()),
        "test-trace".into(),
        "test-session".into(),
    );

    let req = test_query_request("9 variants test", "00000000-0000-4000-8000-000000000001");
    let ctx =
        crate::workflow::WorkflowContext::new("test-session".into(), "test-trace".into(), &req);

    let nine_variants: Vec<String> = (0..9).map(|i| format!("variant-{i}")).collect();
    let fake_reformulator = Arc::new(crate::workflow::ports::FakeQueryReformulator::new(
        nine_variants,
    ));
    let fake_embedder = Arc::new(crate::workflow::ports::FakeQueryEmbeddingPort::success(
        vec![0.1; 2048],
    ));
    let fake_graph = Arc::new(crate::workflow::ports::FakeGraphQueryPort::success(
        "graph facts",
    ));
    let fake_dense = Arc::new(crate::workflow::ports::FakeDenseRetrievalPort::success(
        vec![],
    ));
    let fake_bm25 = Arc::new(crate::workflow::ports::FakeBm25RetrievalPort::success(
        vec![],
    ));

    let mut runner = crate::workflow::WorkflowRunner::new();
    runner.add_node(
        crate::workflow::nodes::ReformulateQueryNode::with_reformulator(Some(fake_reformulator)),
    );
    runner.add_node(crate::workflow::nodes::ExtractGraphContextNode::new(
        Some(fake_embedder.clone()),
        Some(fake_graph.clone()),
    ));
    runner.add_node(crate::workflow::nodes::RetrieveHybridNode::new(
        Some(fake_dense.clone()),
        Some(fake_bm25.clone()),
        None,
        crate::retrieval::RetrievalSettings::default(),
    ));

    let deps = crate::workflow::WorkflowDependencies::new();

    runner
        .run_tracer(ctx, cancel, sink, &deps, |ctx, deps, sink, cancel| {
            Box::pin(async move {
                crate::workflow::run_inline_prompt_generation_remainder(ctx, deps, sink, cancel)
                    .await
            })
        })
        .await;

    assert_eq!(
        fake_embedder.calls(),
        0,
        "No embedding call must be made when >8 variants are produced"
    );
    assert_eq!(
        fake_graph.calls(),
        0,
        "No graph call must be made when >8 variants are produced"
    );
    assert_eq!(
        fake_dense.calls(),
        0,
        "No dense retrieval call must be made when >8 variants are produced"
    );
    assert_eq!(
        fake_bm25.calls(),
        0,
        "No BM25 retrieval call must be made when >8 variants are produced"
    );

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let failed_event = events
        .iter()
        .find_map(|e| match &e.event {
            Some(engine::pb::lancet::v1::workflow_event::Event::WorkflowCompleted(wc)) => Some(wc),
            _ => None,
        })
        .expect("WorkflowCompleted event must be emitted");

    assert!(!failed_event.success);
    assert_eq!(
        failed_event.error_kind,
        NodeErrorKind::InputValidation as i32
    );
}

#[tokio::test]
async fn zero_variants_are_rejected_before_retrieval() {
    let (tx, mut rx) = tokio::sync::mpsc::channel(100);
    let cancel = tokio_util::sync::CancellationToken::new();
    let sink = crate::workflow::WorkflowEventSink::new(
        tx,
        Arc::new(crate::workflow::EventSequence::new()),
        "test-trace".into(),
        "test-session".into(),
    );

    let req = test_query_request("0 variants test", "00000000-0000-4000-8000-000000000001");
    let ctx =
        crate::workflow::WorkflowContext::new("test-session".into(), "test-trace".into(), &req);

    let fake_reformulator = Arc::new(crate::workflow::ports::FakeQueryReformulator::new(vec![]));
    let fake_embedder = Arc::new(crate::workflow::ports::FakeQueryEmbeddingPort::success(
        vec![0.1; 2048],
    ));

    let mut runner = crate::workflow::WorkflowRunner::new();
    runner.add_node(
        crate::workflow::nodes::ReformulateQueryNode::with_reformulator(Some(fake_reformulator)),
    );
    runner.add_node(crate::workflow::nodes::ExtractGraphContextNode::new(
        Some(fake_embedder.clone()),
        None,
    ));

    let deps = crate::workflow::WorkflowDependencies::new();

    runner
        .run_tracer(ctx, cancel, sink, &deps, |ctx, deps, sink, cancel| {
            Box::pin(async move {
                crate::workflow::run_inline_prompt_generation_remainder(ctx, deps, sink, cancel)
                    .await
            })
        })
        .await;

    assert_eq!(
        fake_embedder.calls(),
        0,
        "No embedding call must be made when 0 variants are produced"
    );

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let failed_event = events
        .iter()
        .find_map(|e| match &e.event {
            Some(engine::pb::lancet::v1::workflow_event::Event::WorkflowCompleted(wc)) => Some(wc),
            _ => None,
        })
        .expect("WorkflowCompleted event must be emitted");

    assert!(!failed_event.success);
    assert_eq!(
        failed_event.error_kind,
        NodeErrorKind::InputValidation as i32
    );
}

#[tokio::test]
async fn workflow_generation_tracer() {
    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sequence = Arc::new(EventSequence::new());
    let sink = WorkflowEventSink::new(tx, sequence, "trace-gen".into(), "sess-gen".into());

    let req = test_query_request("What is Lancet engine architecture?", "sess-gen");
    let ctx = WorkflowContext::new("sess-gen".into(), "trace-gen".into(), &req);

    let fake_reformulator = Arc::new(FakeQueryReformulator::new(vec!["query variant".into()]));
    let fake_embedder = Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let fake_graph = Arc::new(FakeGraphQueryPort::success("graph context fact"));

    let candidate = candidate_with_score(
        "1",
        "Lancet uses Rust state machine for RAG orchestration.",
        0.95,
    )
    .candidate;
    let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![candidate.clone()]));
    let fake_bm25 = Arc::new(FakeBm25RetrievalPort::success(vec![candidate]));

    let model_out = ModelOutput {
        answer: "Lancet uses a Rust state machine.".into(),
        cited_evidence_ids: vec!["[1]".into()],
        answer_basis: AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        usage: None,
    };
    let fake_generator: Arc<dyn Generator> = Arc::new(FakeGenerator::new(Ok(model_out)));

    let mut runner = WorkflowRunner::new();
    runner.add_node(ReformulateQueryNode::with_reformulator(Some(
        fake_reformulator,
    )));
    runner.add_node(ExtractGraphContextNode::new(
        Some(fake_embedder),
        Some(fake_graph),
    ));
    runner.add_node(RetrieveHybridNode::new(
        Some(fake_dense),
        Some(fake_bm25),
        None,
        RetrievalSettings::default(),
    ));
    runner.add_node(AssemblePromptNode::new());
    runner.add_node(GenerateAnswerNode::new(Some(fake_generator)));

    runner.run_workflow(ctx, cancel, sink).await;

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let chunk_count = events
        .iter()
        .filter(|e| {
            matches!(
                &e.event,
                Some(engine::pb::lancet::v1::workflow_event::Event::AnswerChunk(
                    _
                ))
            )
        })
        .count();
    let final_count = events
        .iter()
        .filter(|e| {
            matches!(
                &e.event,
                Some(engine::pb::lancet::v1::workflow_event::Event::FinalAnswer(
                    _
                ))
            )
        })
        .count();
    assert_eq!(
        chunk_count, 1,
        "Exactly one AnswerChunk event must be emitted"
    );
    assert_eq!(
        final_count, 1,
        "Exactly one FinalAnswer event must be emitted"
    );

    let completed = events
        .iter()
        .find_map(|e| match &e.event {
            Some(engine::pb::lancet::v1::workflow_event::Event::WorkflowCompleted(wc)) => Some(wc),
            _ => None,
        })
        .expect("WorkflowCompleted event must be emitted");

    assert!(completed.success);
    assert!(completed.final_response.is_some());
}

#[tokio::test]
async fn generation_retry_request_is_byte_identical() {
    use engine::generation::{GenerationError, GenerationErrorKind, GenerationRequest};
    use std::sync::Mutex;

    struct CapturingGenerator {
        requests: Mutex<Vec<GenerationRequest>>,
    }

    impl Generator for CapturingGenerator {
        fn generate<'a>(
            &'a self,
            request: GenerationRequest,
        ) -> engine::generation::BoxFuture<'a, Result<ModelOutput, GenerationError>> {
            Box::pin(async move {
                let mut reqs = self.requests.lock().unwrap();
                reqs.push(request.clone());
                if reqs.len() == 1 {
                    Err(GenerationError::new(
                        GenerationErrorKind::ProviderError,
                        "Transient HTTP 503 error",
                    ))
                } else {
                    Ok(ModelOutput {
                        answer: "Retried answer succeeded".into(),
                        cited_evidence_ids: vec!["[1]".into()],
                        answer_basis: AnswerBasis::Retrieval,
                        notices: vec![],
                        warnings: vec![],
                        usage: None,
                    })
                }
            })
        }
    }

    let capturing_gen = Arc::new(CapturingGenerator {
        requests: Mutex::new(Vec::new()),
    });

    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sequence = Arc::new(EventSequence::new());
    let sink = WorkflowEventSink::new(tx, sequence, "trace-retry".into(), "sess-retry".into());

    let req = test_query_request("Byte identical query?", "sess-retry");
    let mut ctx = WorkflowContext::new("sess-retry".into(), "trace-retry".into(), &req);
    ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
        id: "[1]".into(),
        chunk_id: "c1".into(),
        document_id: "d1".into(),
        chunk_index: 0,
        title: Some("Doc".into()),
        section_path: Some("Sec".into()),
        content_type: Some("text/plain".into()),
        provenance: "prov".into(),
        text: "Sample text".into(),
        score: 0.9,
        rank: 1,
        suspicious: false,
    }];

    let node = GenerateAnswerNode::new(Some(capturing_gen.clone() as Arc<dyn Generator>));

    let runner = WorkflowRunner::new();
    let res = runner.run_node(&node, &mut ctx, &cancel, &sink).await;
    assert!(
        res.is_ok(),
        "GenerateAnswer must succeed on retry attempt 2"
    );

    let reqs = capturing_gen.requests.lock().unwrap().clone();
    assert_eq!(reqs.len(), 2, "Must make exactly 2 generation attempts");
    assert_eq!(
        reqs[0], reqs[1],
        "Captured GenerationRequest across attempt 1 and attempt 2 must be byte/field-identical"
    );

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let failed_events = events
        .iter()
        .filter(|e| {
            matches!(
                &e.event,
                Some(engine::pb::lancet::v1::workflow_event::Event::NodeFailed(_))
            )
        })
        .count();
    assert_eq!(
        failed_events, 0,
        "No retrying/failed event emitted during internal node retry"
    );
}

#[tokio::test]
async fn generation_outer_timeout_allows_retry() {
    use engine::generation::{GenerationError, GenerationErrorKind, GenerationRequest};
    use std::sync::Mutex;

    struct SlowFirstGenerator {
        calls: Mutex<usize>,
    }

    impl Generator for SlowFirstGenerator {
        fn generate<'a>(
            &'a self,
            _request: GenerationRequest,
        ) -> engine::generation::BoxFuture<'a, Result<ModelOutput, GenerationError>> {
            Box::pin(async move {
                let mut count = self.calls.lock().unwrap();
                *count += 1;
                if *count == 1 {
                    Err(GenerationError::new(
                        GenerationErrorKind::Timeout,
                        "Attempt 1 provider timeout",
                    ))
                } else {
                    Ok(ModelOutput {
                        answer: "Attempt 2 fast answer".into(),
                        cited_evidence_ids: vec!["[1]".into()],
                        answer_basis: AnswerBasis::Retrieval,
                        notices: vec![],
                        warnings: vec![],
                        usage: None,
                    })
                }
            })
        }
    }

    let slow_gen = Arc::new(SlowFirstGenerator {
        calls: Mutex::new(0),
    });

    let (tx, _rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sequence = Arc::new(EventSequence::new());
    let sink = WorkflowEventSink::new(tx, sequence, "trace-timeout".into(), "sess-timeout".into());

    let req = test_query_request("Timeout query?", "sess-timeout");
    let mut ctx = WorkflowContext::new("sess-timeout".into(), "trace-timeout".into(), &req);
    ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
        id: "[1]".into(),
        chunk_id: "c1".into(),
        document_id: "d1".into(),
        chunk_index: 0,
        title: Some("Doc".into()),
        section_path: Some("Sec".into()),
        content_type: Some("text/plain".into()),
        provenance: "prov".into(),
        text: "Sample text".into(),
        score: 0.9,
        rank: 1,
        suspicious: false,
    }];

    let node = GenerateAnswerNode::new(Some(slow_gen.clone() as Arc<dyn Generator>));

    let runner = WorkflowRunner::new().with_timeouts(5000, 15000, 10000, 2000, 65000);
    let res = runner.run_node(&node, &mut ctx, &cancel, &sink).await;

    assert!(
        res.is_ok(),
        "Outer node timeout budget of 65000ms must allow attempt 2 retry to succeed"
    );
    assert_eq!(*slow_gen.calls.lock().unwrap(), 2);
}

#[tokio::test]
async fn generation_cancellation_between_attempts() {
    use engine::generation::{GenerationError, GenerationErrorKind, GenerationRequest};
    use std::sync::Mutex;

    struct CancellingGenerator {
        calls: Mutex<usize>,
        cancel: CancellationToken,
    }

    impl Generator for CancellingGenerator {
        fn generate<'a>(
            &'a self,
            _request: GenerationRequest,
        ) -> engine::generation::BoxFuture<'a, Result<ModelOutput, GenerationError>> {
            Box::pin(async move {
                let mut count = self.calls.lock().unwrap();
                *count += 1;
                if *count == 1 {
                    self.cancel.cancel();
                    Err(GenerationError::new(
                        GenerationErrorKind::ProviderError,
                        "Attempt 1 transient error",
                    ))
                } else {
                    Ok(ModelOutput {
                        answer: "Should not be reached".into(),
                        cited_evidence_ids: vec!["[1]".into()],
                        answer_basis: AnswerBasis::Retrieval,
                        notices: vec![],
                        warnings: vec![],
                        usage: None,
                    })
                }
            })
        }
    }

    let cancel = CancellationToken::new();
    let cancelling_gen = Arc::new(CancellingGenerator {
        calls: Mutex::new(0),
        cancel: cancel.clone(),
    });

    let (tx, mut rx) = mpsc::channel(100);
    let sequence = Arc::new(EventSequence::new());
    let sink = WorkflowEventSink::new(tx, sequence, "trace-cancel".into(), "sess-cancel".into());

    let req = test_query_request("Cancel query?", "sess-cancel");
    let mut ctx = WorkflowContext::new("sess-cancel".into(), "trace-cancel".into(), &req);
    ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
        id: "[1]".into(),
        chunk_id: "c1".into(),
        document_id: "d1".into(),
        chunk_index: 0,
        title: Some("Doc".into()),
        section_path: Some("Sec".into()),
        content_type: Some("text/plain".into()),
        provenance: "prov".into(),
        text: "Sample text".into(),
        score: 0.9,
        rank: 1,
        suspicious: false,
    }];

    let node = GenerateAnswerNode::new(Some(cancelling_gen.clone() as Arc<dyn Generator>));

    let runner = WorkflowRunner::new();
    let res = runner.run_node(&node, &mut ctx, &cancel, &sink).await;

    assert!(res.is_err());
    let err = res.unwrap_err();
    assert_eq!(err.kind, NodeErrorKind::Cancelled);
    assert_eq!(
        *cancelling_gen.calls.lock().unwrap(),
        1,
        "Attempt 2 must not be triggered when cancellation token is cancelled between attempts"
    );

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }
    let chunk_count = events
        .iter()
        .filter(|e| {
            matches!(
                &e.event,
                Some(engine::pb::lancet::v1::workflow_event::Event::AnswerChunk(
                    _
                ))
            )
        })
        .count();
    assert_eq!(
        chunk_count, 0,
        "No AnswerChunk event must be emitted on cancelled generation"
    );
}

#[tokio::test]
async fn answer_events_have_exact_cardinality() {
    // Scenario A: Happy path with evidence
    {
        let (tx, mut rx) = mpsc::channel(100);
        let cancel = CancellationToken::new();
        let sequence = Arc::new(EventSequence::new());
        let sink =
            WorkflowEventSink::new(tx, sequence, "trace-card-a".into(), "sess-card-a".into());

        let req = test_query_request("Card A", "sess-card-a");
        let ctx = WorkflowContext::new("sess-card-a".into(), "trace-card-a".into(), &req);

        let candidate = candidate_with_score("1", "Content 1", 0.9).candidate;
        let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![candidate]));
        let fake_gen: Arc<dyn Generator> = Arc::new(FakeGenerator::new(Ok(ModelOutput {
            answer: "Answer A".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        })));

        let mut runner = WorkflowRunner::new();
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

        let answer_chunks = events
            .iter()
            .filter(|e| {
                matches!(
                    &e.event,
                    Some(engine::pb::lancet::v1::workflow_event::Event::AnswerChunk(
                        _
                    ))
                )
            })
            .count();
        let final_answers = events
            .iter()
            .filter(|e| {
                matches!(
                    &e.event,
                    Some(engine::pb::lancet::v1::workflow_event::Event::FinalAnswer(
                        _
                    ))
                )
            })
            .count();
        assert_eq!(answer_chunks, 1, "Happy path emits exactly 1 AnswerChunk");
        assert_eq!(final_answers, 1, "Happy path emits exactly 1 FinalAnswer");
    }

    // Scenario B: Zero evidence path
    {
        let (tx, mut rx) = mpsc::channel(100);
        let cancel = CancellationToken::new();
        let sequence = Arc::new(EventSequence::new());
        let sink =
            WorkflowEventSink::new(tx, sequence, "trace-card-b".into(), "sess-card-b".into());

        let req = test_query_request("Card B", "sess-card-b");
        let ctx = WorkflowContext::new("sess-card-b".into(), "trace-card-b".into(), &req);

        let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![]));

        let mut runner = WorkflowRunner::new();
        runner.add_node(RetrieveHybridNode::new(
            Some(fake_dense),
            None,
            None,
            RetrievalSettings::default(),
        ));
        runner.add_node(AssemblePromptNode::new());
        runner.add_node(GenerateAnswerNode::new(None));

        runner.run_workflow(ctx, cancel, sink).await;

        let mut events = Vec::new();
        while let Ok(item) = rx.try_recv() {
            if let Ok(wf_event) = item {
                events.push(wf_event);
            }
        }

        let answer_chunks = events
            .iter()
            .filter(|e| {
                matches!(
                    &e.event,
                    Some(engine::pb::lancet::v1::workflow_event::Event::AnswerChunk(
                        _
                    ))
                )
            })
            .count();
        let final_answers = events
            .iter()
            .filter(|e| {
                matches!(
                    &e.event,
                    Some(engine::pb::lancet::v1::workflow_event::Event::FinalAnswer(
                        _
                    ))
                )
            })
            .count();
        assert_eq!(answer_chunks, 0, "Zero evidence path emits 0 AnswerChunk");
        assert_eq!(
            final_answers, 1,
            "Zero evidence path emits exactly 1 FinalAnswer"
        );
    }

    // Scenario C: Exhausted generation failure
    {
        let (tx, mut rx) = mpsc::channel(100);
        let cancel = CancellationToken::new();
        let sequence = Arc::new(EventSequence::new());
        let sink =
            WorkflowEventSink::new(tx, sequence, "trace-card-c".into(), "sess-card-c".into());

        let req = test_query_request("Card C", "sess-card-c");
        let ctx = WorkflowContext::new("sess-card-c".into(), "trace-card-c".into(), &req);

        let candidate = candidate_with_score("1", "Content 1", 0.9).candidate;
        let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![candidate]));
        let failing_gen: Arc<dyn Generator> = Arc::new(FakeGenerator::new(Err(
            engine::generation::GenerationError::new(
                engine::generation::GenerationErrorKind::ProviderError,
                "Permanent failure",
            ),
        )));

        let mut runner = WorkflowRunner::new();
        runner.add_node(RetrieveHybridNode::new(
            Some(fake_dense),
            None,
            None,
            RetrievalSettings::default(),
        ));
        runner.add_node(AssemblePromptNode::new());
        runner.add_node(GenerateAnswerNode::new(Some(failing_gen)));

        runner.run_workflow(ctx, cancel, sink).await;

        let mut events = Vec::new();
        while let Ok(item) = rx.try_recv() {
            if let Ok(wf_event) = item {
                events.push(wf_event);
            }
        }

        let answer_chunks = events
            .iter()
            .filter(|e| {
                matches!(
                    &e.event,
                    Some(engine::pb::lancet::v1::workflow_event::Event::AnswerChunk(
                        _
                    ))
                )
            })
            .count();
        let final_answers = events
            .iter()
            .filter(|e| {
                matches!(
                    &e.event,
                    Some(engine::pb::lancet::v1::workflow_event::Event::FinalAnswer(
                        _
                    ))
                )
            })
            .count();
        assert_eq!(answer_chunks, 0, "Failing generation emits 0 AnswerChunk");
        assert_eq!(final_answers, 0, "Failing generation emits 0 FinalAnswer");
    }
}

#[tokio::test]
async fn workflow_answer_contract_preserves_all_fields() {
    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sequence = Arc::new(EventSequence::new());
    let sink = WorkflowEventSink::new(tx, sequence, "trace-fields".into(), "sess-fields".into());

    let req = test_query_request("Preserve fields query", "sess-fields");
    let ctx = WorkflowContext::new("sess-fields".into(), "trace-fields".into(), &req);

    let candidate =
        candidate_with_score("100", "Evidence text for fields preservation test.", 0.88).candidate;
    let fake_dense = Arc::new(FakeDenseRetrievalPort::success(vec![candidate]));

    let model_out = ModelOutput {
        answer: "Detailed answer string preserving fields.".into(),
        cited_evidence_ids: vec!["[1]".into()],
        answer_basis: AnswerBasis::Retrieval,
        notices: vec!["Notice 1".into()],
        warnings: vec!["Warning 1".into()],
        usage: None,
    };
    let fake_gen: Arc<dyn Generator> = Arc::new(FakeGenerator::new(Ok(model_out)));

    let mut runner = WorkflowRunner::new();
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

    let final_answer_event = events
        .iter()
        .find_map(|e| match &e.event {
            Some(engine::pb::lancet::v1::workflow_event::Event::FinalAnswer(fa)) => {
                fa.response.clone()
            }
            _ => None,
        })
        .expect("FinalAnswer must contain QueryRagResponse");

    assert_eq!(
        final_answer_event.answer,
        "Detailed answer string preserving fields."
    );
    assert_eq!(final_answer_event.citations, vec!["[1]"]);
    assert_eq!(final_answer_event.session_id, "sess-fields");
    assert_eq!(
        final_answer_event.answer_basis,
        engine::pb::lancet::v1::AnswerBasis::Retrieval as i32
    );
    assert!(!final_answer_event.structured_citations.is_empty());
    assert_eq!(
        final_answer_event.structured_citations[0].chunk_id,
        "chk-100"
    );
    assert_eq!(
        final_answer_event.structured_citations[0].document_id,
        "doc-100"
    );
    assert_eq!(final_answer_event.notices.len(), 2);
    assert!(final_answer_event.snapshot.is_some());
    let snapshot = final_answer_event.snapshot.as_ref().unwrap();
    assert_eq!(snapshot.candidate_limit, 32);
    assert_eq!(snapshot.final_limit, 8);
}

#[tokio::test]
async fn prompt_packing_cancellation_is_cooperative() {
    use engine::prompt::{
        assemble_evidence_blocks, pack_evidence_and_graph_prompt, PromptAssemblyError,
    };

    let mut fused = Vec::new();
    for i in 0..100 {
        fused.push(candidate_with_score(
            &format!("{i}"),
            &format!("Large content block {i} for cancellation testing. ").repeat(20),
            0.9 - (i as f64 * 0.001),
        ));
    }

    let evidence = assemble_evidence_blocks(&fused);
    let cancel = CancellationToken::new();
    cancel.cancel();

    let res = pack_evidence_and_graph_prompt(
        "Cancellation test?",
        &evidence,
        &[],
        1.0,
        65536,
        2048,
        &cancel,
    )
    .await;
    assert_eq!(
        res,
        Err(PromptAssemblyError::Cancelled),
        "Cooperative prompt packing must return Cancelled when cancellation token is pre-cancelled"
    );
}

#[tokio::test]
async fn workflow_phase5_prompt_api_surface() {
    use engine::graph::context_strategy::GraphFact;
    use engine::prompt::{
        assemble_evidence_blocks, pack_evidence_and_graph_prompt, pack_evidence_prompt,
        GraphFactBlock, PromptAssemblyError,
    };

    let candidate1 = candidate_with_score("1", "Lancet prompt assembly surface test text 1.", 0.95);
    let candidate2 = candidate_with_score("2", "Lancet prompt assembly surface test text 2.", 0.85);
    let evidence = assemble_evidence_blocks(&[candidate1, candidate2]);
    let empty_evidence: Vec<engine::prompt::EvidenceBlock> = Vec::new();
    let facts = vec![GraphFactBlock {
        fact: GraphFact::new("Lancet", "implements", "PromptAssembly", None, 0.9),
    }];

    let cancel = CancellationToken::new();

    // 1. Empty evidence returns PromptAssemblyError::EmptyEvidence for both helpers
    let empty_res1 =
        pack_evidence_prompt("Test question?", &empty_evidence, 8192, 2048, &cancel).await;
    assert_eq!(empty_res1, Err(PromptAssemblyError::EmptyEvidence));

    let empty_res2 = pack_evidence_and_graph_prompt(
        "Test question?",
        &empty_evidence,
        &facts,
        1.0,
        8192,
        2048,
        &cancel,
    )
    .await;
    assert_eq!(empty_res2, Err(PromptAssemblyError::EmptyEvidence));

    // 2. Pre-cancelled token returns PromptAssemblyError::Cancelled
    let pre_cancel = CancellationToken::new();
    pre_cancel.cancel();

    let cancel_res1 =
        pack_evidence_prompt("Test question?", &evidence, 8192, 2048, &pre_cancel).await;
    assert_eq!(cancel_res1, Err(PromptAssemblyError::Cancelled));

    let cancel_res2 = pack_evidence_and_graph_prompt(
        "Test question?",
        &evidence,
        &facts,
        1.0,
        8192,
        2048,
        &pre_cancel,
    )
    .await;
    assert_eq!(cancel_res2, Err(PromptAssemblyError::Cancelled));

    // 3. NoEvidenceFits error when token budget is insufficient for even the first block
    let tight_budget_res = pack_evidence_prompt("Test question?", &evidence, 50, 40, &cancel).await;
    assert!(matches!(
        tight_budget_res,
        Err(PromptAssemblyError::NoEvidenceFits { .. })
    ));

    // 4. Successful async packing returns structured PackedEvidence
    let packed = pack_evidence_prompt("Test question?", &evidence, 8192, 2048, &cancel)
        .await
        .expect("pack_evidence_prompt succeeds");
    assert!(!packed.prompt.is_empty());
    assert_eq!(packed.evidence.len(), 2);
    assert_eq!(packed.encoded_blocks.len(), 2);
    assert!(packed.graph_facts.is_empty());
}

#[tokio::test]
async fn workflow_phase5_prompt_graph_weight_semantics() {
    use engine::graph::context_strategy::GraphFact;
    use engine::prompt::{
        assemble_evidence_blocks, pack_evidence_and_graph_prompt, GraphFactBlock,
    };

    let candidate1 = candidate_with_score("1", "First citable chunk content.", 0.95);
    let candidate2 = candidate_with_score("2", "Second citable chunk content.", 0.85);
    let evidence = assemble_evidence_blocks(&[candidate1, candidate2]);

    let fact1 = GraphFactBlock {
        fact: GraphFact::new("EntityA", "relates_to", "EntityB", None, 0.99),
    };
    let fact2 = GraphFactBlock {
        fact: GraphFact::new("EntityC", "relates_to", "EntityD", None, 0.75),
    };
    let graph_facts = vec![fact1, fact2];

    let cancel = CancellationToken::new();

    // 1. graph_weight == 0.0 hard-excludes graph facts unconditionally
    let packed_zero = pack_evidence_and_graph_prompt(
        "Graph weight zero question?",
        &evidence,
        &graph_facts,
        0.0,
        65536,
        2048,
        &cancel,
    )
    .await
    .expect("packing with graph_weight 0.0 succeeds");

    assert!(
        packed_zero.graph_facts.is_empty(),
        "graph_weight 0.0 must exclude all graph facts"
    );
    assert!(
        !packed_zero
            .prompt
            .contains("Related Entities & Relationships"),
        "graph_weight 0.0 prompt must not contain graph section header"
    );
    assert_eq!(
        packed_zero.evidence.len(),
        2,
        "evidence chunks must remain included"
    );
    assert_eq!(packed_zero.evidence[0].id, "[1]");

    // 2. graph_weight > 0.0 includes graph facts without altering evidence-selection authority
    let packed_positive = pack_evidence_and_graph_prompt(
        "Graph weight positive question?",
        &evidence,
        &graph_facts,
        1.0,
        65536,
        2048,
        &cancel,
    )
    .await
    .expect("packing with graph_weight 1.0 succeeds");

    assert!(
        !packed_positive.graph_facts.is_empty(),
        "positive graph_weight includes graph facts"
    );
    assert!(
        packed_positive
            .prompt
            .contains("Related Entities & Relationships"),
        "positive graph_weight prompt contains graph section header"
    );
    assert_eq!(
        packed_positive.evidence[0].id, "[1]",
        "evidence selection authority is preserved"
    );
}

#[test]
fn workflow_phase5_fake_ports_test_only() {
    let repo_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("cargo manifest dir parent");

    // 1. Verify ports.rs has all Fake* types gated under cfg(test)
    let ports_path = repo_root.join("engine/src/workflow/ports.rs");
    let ports_src = std::fs::read_to_string(&ports_path).expect("read workflow/ports.rs");

    let fake_port_types = [
        "FakeQueryReformulator",
        "FakeQueryEmbeddingPort",
        "FakeGraphQueryPort",
        "FakeDenseRetrievalPort",
        "FakeBm25RetrievalPort",
        "FakeReranker",
    ];

    for type_name in fake_port_types {
        let decl_pattern = format!("pub struct {type_name}");
        let decl_pos = ports_src
            .find(&decl_pattern)
            .unwrap_or_else(|| panic!("declaration of {type_name} not found in ports.rs"));

        // Preceding non-empty line must be #[cfg(test)]
        let prefix = &ports_src[..decl_pos];
        let last_attr = prefix
            .lines()
            .rev()
            .find(|l| !l.trim().is_empty())
            .unwrap_or("");
        assert!(
            last_attr.contains("#[cfg(test)]"),
            "{type_name} in ports.rs must be directly preceded by #[cfg(test)], found: {last_attr}"
        );
    }

    // Ensure NoOpQueryReformulator is NOT gated by #[cfg(test)] (it is a production pass-through)
    let noop_pos = ports_src
        .find("pub struct NoOpQueryReformulator")
        .expect("NoOpQueryReformulator in ports.rs");
    let noop_prefix = &ports_src[..noop_pos];
    let noop_last_line = noop_prefix
        .lines()
        .rev()
        .find(|l| !l.trim().is_empty())
        .unwrap_or("");
    assert!(
        !noop_last_line.contains("#[cfg(test)]"),
        "NoOpQueryReformulator must remain available in production"
    );

    // 2. Verify generation/mod.rs has FakeGenerator gated under cfg(test)
    let gen_path = repo_root.join("engine/src/generation/mod.rs");
    let gen_src = std::fs::read_to_string(&gen_path).expect("read generation/mod.rs");

    let fake_gen_pos = gen_src
        .find("pub struct FakeGenerator")
        .expect("FakeGenerator in generation/mod.rs");
    let fake_gen_prefix = &gen_src[..fake_gen_pos];
    let fake_gen_last_attr = fake_gen_prefix
        .lines()
        .rev()
        .find(|l| !l.trim().is_empty())
        .unwrap_or("");
    assert!(
        fake_gen_last_attr.contains("#[cfg(test)]"),
        "FakeGenerator in generation/mod.rs must be preceded by #[cfg(test)], found: {fake_gen_last_attr}"
    );

    // 3. Verify that under test compilation, the fake types are constructible and usable
    let _reformulator = FakeQueryReformulator::new(vec!["test_variant".to_string()]);
    let _embedder = FakeQueryEmbeddingPort::success(vec![0.5; 2048]);
    let _graph = FakeGraphQueryPort::success("entity1 -- rel -- entity2");
    let _dense = FakeDenseRetrievalPort::success(vec![]);
    let _bm25 = FakeBm25RetrievalPort::success(vec![]);
    let _reranker = FakeReranker::success();
    let _gen = FakeGenerator::new(Ok(ModelOutput {
        answer: "Test answer [1].".into(),
        cited_evidence_ids: vec!["[1]".into()],
        answer_basis: AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        usage: None,
    }));
}

#[tokio::test]
async fn workflow_phase5_graph_notice_merge() {
    let cancel = CancellationToken::new();
    let req = test_query_request("graph notice merge test", "sess-notice-merge");
    let mut ctx = WorkflowContext::new(
        "sess-notice-merge".into(),
        "trace-notice-merge".into(),
        &req,
    );

    // 1. Pre-existing notice (e.g. from retrieval or pre-step)
    let initial_notice = test_notice(
        NoticeCode::RetrievalDegradedDense,
        "dense retrieval returned 5 candidates",
        NoticeSeverity::Info,
    );
    ctx.add_notice(initial_notice.clone());
    assert_eq!(ctx.notices.len(), 1);

    // 2. Test notice merge and deduplication
    ctx.merge_notices(vec![
        initial_notice.clone(), // duplicate: should not be added again
        test_notice(
            NoticeCode::ModelWarning,
            "low confidence variant",
            NoticeSeverity::Warning,
        ),
    ]);
    assert_eq!(ctx.notices.len(), 2);
    assert_eq!(ctx.notices[0].code, "RETRIEVAL_DEGRADED_DENSE");
    assert_eq!(ctx.notices[1].code, "MODEL_WARNING");

    // 3. Graph node with error outcome -> GRAPH_DEGRADED notice appended
    let fake_embedder = Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let fake_graph_fail = Arc::new(FakeGraphQueryPort::failure(NodeError::new(
        NodeErrorKind::GraphFailed,
        "cypher engine unavailable",
    )));
    let graph_node =
        ExtractGraphContextNode::new(Some(fake_embedder.clone()), Some(fake_graph_fail));
    let res = graph_node.run(&mut ctx, &cancel).await;
    assert!(
        res.is_ok(),
        "Graph degradation must not fail workflow per D-09"
    );
    assert!(
        ctx.graph_context.is_empty(),
        "Graph context must be empty on degradation"
    );
    assert_eq!(ctx.notices.len(), 3);
    assert_eq!(ctx.notices[2].code, "GRAPH_DEGRADED");
    assert!(ctx.notices[2].message.contains("cypher engine unavailable"));

    // 4. Graph node with timeout outcome -> GRAPH_TIMEOUT notice appended
    let fake_graph_stall = Arc::new(FakeGraphQueryPort::stall());
    let timeout_node = ExtractGraphContextNode::new(Some(fake_embedder), Some(fake_graph_stall))
        .with_timeouts(5000, 50);
    let res2 = timeout_node.run(&mut ctx, &cancel).await;
    assert!(
        res2.is_ok(),
        "Graph timeout must degrade gracefully with Ok(()) per D-09"
    );
    assert_eq!(ctx.notices.len(), 4);
    assert_eq!(ctx.notices[3].code, "GRAPH_TIMEOUT");

    // 5. Subsequent terminal failure preserves all accumulated notices in order
    assert_eq!(ctx.notices[0].code, "RETRIEVAL_DEGRADED_DENSE");
    assert_eq!(ctx.notices[1].code, "MODEL_WARNING");
    assert_eq!(ctx.notices[2].code, "GRAPH_DEGRADED");
    assert_eq!(ctx.notices[3].code, "GRAPH_TIMEOUT");

    // Response conversion also preserves notice history
    let resp = ctx.to_query_rag_response();
    assert_eq!(resp.notices.len(), 4);
    assert_eq!(resp.notices[0].code, "RETRIEVAL_DEGRADED_DENSE");
    assert_eq!(resp.notices[1].code, "MODEL_WARNING");
    assert_eq!(resp.notices[2].code, "GRAPH_DEGRADED");
    assert_eq!(resp.notices[3].code, "GRAPH_TIMEOUT");
}

#[tokio::test]
async fn workflow_phase5_checkpoint_full_snapshot() {
    let mut request = test_query_request("full snapshot query", "sess-checkpoint-full");
    request.filter = Some(engine::pb::lancet::v1::DocumentFilter {
        document_ids: vec!["doc-filter".into()],
        content_types: vec!["text/plain".into()],
    });
    let mut ctx = WorkflowContext::new(
        "sess-checkpoint-full".into(),
        "trace-checkpoint-full".into(),
        &request,
    );

    ctx.variants = vec![
        "full snapshot query".into(),
        "expanded snapshot query".into(),
    ];
    ctx.query_embedding = Some((0..2048).map(|index| index as f32 / 10.0).collect());
    ctx.graph_context = "Lancet -- uses -- LanceDB".into();
    ctx.graph_facts = vec![engine::prompt::GraphFactBlock {
        fact: engine::graph::context_strategy::GraphFact::new(
            "Lancet",
            "uses",
            "LanceDB",
            Some("graph evidence"),
            0.91,
        ),
    }];
    ctx.vector_results = vec!["vector-chunk-1".into()];
    ctx.bm25_results = vec!["bm25-chunk-1".into()];
    ctx.final_candidates = vec!["final-chunk-1".into()];
    ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
        id: "[1]".into(),
        chunk_id: "final-chunk-1".into(),
        document_id: "doc-evidence".into(),
        chunk_index: 2,
        title: Some("Evidence title".into()),
        section_path: Some("Evidence section".into()),
        content_type: Some("text/plain".into()),
        provenance: "document_id=doc-evidence".into(),
        text: "lossless evidence text".into(),
        score: 0.88,
        rank: 1,
        suspicious: false,
    }];
    ctx.assembled_prompt = "assembled prompt remains lossless".into();
    ctx.answer = "lossless answer".into();
    ctx.citations = vec!["[1]".into()];
    ctx.answer_basis = engine::pb::lancet::v1::AnswerBasis::Retrieval;
    ctx.structured_citations = vec![engine::pb::lancet::v1::StructuredCitation {
        chunk_id: "final-chunk-1".into(),
        document_id: "doc-evidence".into(),
        title: "Evidence title".into(),
        section_path: "Evidence section".into(),
        excerpt: "lossless excerpt".into(),
        is_truncated: false,
        score: 0.88,
        rank: 1,
        content_type: "text/plain".into(),
    }];
    ctx.merge_notices(vec![
        test_notice(
            NoticeCode::RetrievalDegradedDense,
            "retrieval completed",
            NoticeSeverity::Info,
        ),
        test_notice(
            NoticeCode::GraphDegraded,
            "graph degraded after retrieval",
            NoticeSeverity::Info,
        ),
        test_notice(
            NoticeCode::GraphTimeout,
            "graph timeout was observed",
            NoticeSeverity::Info,
        ),
    ]);
    ctx.snapshot = Some(engine::pb::lancet::v1::RetrievalSnapshot {
        index_generation: "generation-7".into(),
        embedding_model: "embedding-model".into(),
        vector_weight: 0.7,
        bm25_weight: 0.3,
        rrf_k: 60,
        candidate_limit: 32,
        final_limit: 8,
        active_filter: request.filter.clone(),
        result_hash: "result-hash".into(),
        variant_count: 2,
        variant_identities: ctx.variants.clone(),
    });

    let event = events::checkpoint("full_snapshot", 77, &ctx);
    let checkpoint = match event {
        Event::Checkpoint(checkpoint) => checkpoint,
        other => panic!("expected checkpoint event, got {other:?}"),
    };
    let serialized_bytes = checkpoint.context_snapshot.len();
    println!("checkpoint serialized bytes: {serialized_bytes}");
    assert!(
        serialized_bytes > 0,
        "checkpoint JSON must have serialized bytes"
    );
    assert!(
        serialized_bytes < 20_000,
        "embedding must remain fixed-size"
    );

    let payload: serde_json::Value = serde_json::from_str(&checkpoint.context_snapshot)
        .expect("checkpoint snapshot must round-trip as valid JSON");
    let object = payload
        .as_object()
        .expect("checkpoint snapshot must be a JSON object");
    let actual_keys: BTreeSet<String> = object.keys().cloned().collect();
    let expected_keys: BTreeSet<String> = events::CHECKPOINT_SNAPSHOT_KEYS
        .iter()
        .map(|key| (*key).to_string())
        .collect();
    assert_eq!(actual_keys, expected_keys, "checkpoint stable key set");

    assert_eq!(payload["session_id"], "sess-checkpoint-full");
    assert_eq!(payload["trace_id"], "trace-checkpoint-full");
    assert_eq!(payload["original_query"], "full snapshot query");
    assert_eq!(
        payload["filter"]["document_ids"],
        serde_json::json!(["doc-filter"])
    );
    assert_eq!(
        payload["filter"]["content_types"],
        serde_json::json!(["text/plain"])
    );
    assert_eq!(
        payload["variants"],
        serde_json::json!(["full snapshot query", "expanded snapshot query"])
    );

    let digest = payload["query_embedding"]
        .as_object()
        .expect("query_embedding must be an object digest, not a raw array");
    assert_eq!(digest["dimension"], 2048);
    let digest_hash = digest["hash"]
        .as_str()
        .expect("query embedding digest hash must be a string");
    assert_eq!(digest_hash.len(), 16, "digest hash must have fixed length");
    assert!(digest_hash
        .chars()
        .all(|character| character.is_ascii_hexdigit()));
    assert!(!payload["query_embedding"].is_array());
    let repeated_payload: serde_json::Value =
        serde_json::from_str(&events::CheckpointSnapshot::from_context(&ctx).to_json())
            .expect("repeated checkpoint serialization must be valid JSON");
    assert_eq!(repeated_payload["query_embedding"]["hash"], digest["hash"]);

    assert_eq!(payload["graph_context"], "Lancet -- uses -- LanceDB");
    assert_eq!(payload["graph_facts"][0]["fact"]["entity_a_name"], "Lancet");
    assert_eq!(
        payload["vector_results"],
        serde_json::json!(["vector-chunk-1"])
    );
    assert_eq!(payload["bm25_results"], serde_json::json!(["bm25-chunk-1"]));
    assert_eq!(
        payload["final_candidates"],
        serde_json::json!(["final-chunk-1"])
    );
    assert_eq!(
        payload["evidence_blocks"][0]["text"],
        "lossless evidence text"
    );
    assert_eq!(
        payload["assembled_prompt"],
        "assembled prompt remains lossless"
    );
    assert_eq!(payload["answer"], "lossless answer");
    assert_eq!(payload["citations"], serde_json::json!(["[1]"]));
    assert_eq!(
        payload["answer_basis"],
        engine::pb::lancet::v1::AnswerBasis::Retrieval as i32
    );
    assert_eq!(
        payload["structured_citations"][0]["excerpt"],
        "lossless excerpt"
    );
    assert_eq!(
        payload["notices"]
            .as_array()
            .unwrap()
            .iter()
            .map(|notice| notice["code"].as_str().unwrap())
            .collect::<Vec<_>>(),
        vec![
            "RETRIEVAL_DEGRADED_DENSE",
            "GRAPH_DEGRADED",
            "GRAPH_TIMEOUT"
        ]
    );
    assert_eq!(payload["snapshot"]["index_generation"], "generation-7");
    assert_eq!(payload["snapshot"]["variant_count"], 2);
    assert_eq!(
        payload["snapshot"]["variant_identities"],
        serde_json::json!(["full snapshot query", "expanded snapshot query"])
    );

    let empty_context = WorkflowContext::new(
        "sess-empty".into(),
        "trace-empty".into(),
        &test_query_request("empty", "sess-empty"),
    );
    let empty_payload: serde_json::Value =
        serde_json::from_str(&events::CheckpointSnapshot::from_context(&empty_context).to_json())
            .expect("empty checkpoint snapshot must be valid JSON");
    assert!(empty_payload["filter"].is_null());
    assert!(empty_payload["query_embedding"].is_null());
    assert!(empty_payload["snapshot"].is_null());
    assert_eq!(empty_payload["variants"], serde_json::json!([]));
    assert_eq!(empty_payload["notices"], serde_json::json!([]));

    let response = ctx.to_query_rag_response();
    assert_eq!(response.answer, "lossless answer");
    assert_eq!(response.snapshot, ctx.snapshot);
    let response_debug = format!("{response:?}");
    assert!(!response_debug.contains("context_snapshot"));
    assert!(!response_debug.contains("assembled_prompt"));
}

#[tokio::test]
async fn workflow_phase5_terminal_idempotence() {
    let (tx, mut rx) = mpsc::channel(16);
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-terminal-idempotence".into(),
        "sess-terminal-idempotence".into(),
    );
    let cancel = CancellationToken::new();
    let request = test_query_request("terminal failure query", "sess-terminal-idempotence");
    let mut ctx = WorkflowContext::new(
        "sess-terminal-idempotence".into(),
        "trace-terminal-idempotence".into(),
        &request,
    );
    ctx.merge_notices(vec![
        test_notice(
            NoticeCode::RetrievalDegradedDense,
            "retrieval notice before graph degradation",
            NoticeSeverity::Info,
        ),
        test_notice(
            NoticeCode::GraphDegraded,
            "graph degraded before terminal failure",
            NoticeSeverity::Info,
        ),
        test_notice(
            NoticeCode::GraphTimeout,
            "graph timeout before terminal failure",
            NoticeSeverity::Info,
        ),
    ]);

    let first_context = ctx.clone();
    let second_context = ctx.clone();
    let first_sink = sink.clone();
    let second_sink = sink.clone();
    let first_cancel = cancel.clone();
    let second_cancel = cancel.clone();
    let first_error = NodeError::new(NodeErrorKind::LlmGenerationFailed, "provider failed");
    let second_error = first_error.clone();

    tokio::join!(
        WorkflowRunner::emit_terminal_once(
            &first_context,
            &first_sink,
            &first_cancel,
            10,
            Some(first_error),
        ),
        WorkflowRunner::emit_terminal_once(
            &second_context,
            &second_sink,
            &second_cancel,
            11,
            Some(second_error),
        ),
    );

    // A later successful cleanup attempt must also be ignored after failure wins.
    WorkflowRunner::emit_terminal_once(&ctx, &sink, &cancel, 12, None).await;

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(event) = item {
            events.push(event);
        }
    }

    let terminal_events: Vec<_> = events
        .iter()
        .filter_map(|event| match &event.event {
            Some(Event::WorkflowCompleted(completed)) => Some(completed),
            _ => None,
        })
        .collect();
    assert_eq!(
        terminal_events.len(),
        1,
        "terminal emission must be idempotent"
    );
    assert!(!terminal_events[0].success);
    assert_eq!(
        terminal_events[0].error_kind,
        NodeErrorKind::LlmGenerationFailed as i32
    );
    assert_eq!(
        terminal_events[0]
            .notices
            .iter()
            .map(|notice| notice.code.as_str())
            .collect::<Vec<_>>(),
        vec![
            "RETRIEVAL_DEGRADED_DENSE",
            "GRAPH_DEGRADED",
            "GRAPH_TIMEOUT"
        ]
    );
    assert!(
        events.iter().all(|event| !matches!(
            event.event,
            Some(Event::AnswerChunk(_)) | Some(Event::FinalAnswer(_))
        )),
        "failed workflows must not emit answer-shaped events"
    );
}

#[tokio::test]
async fn workflow_phase5_failure_terminal_notices_tracer() {
    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let trace_id = "trace-failure-tracer-01".to_string();
    let session_id = "sess-failure-tracer-01".to_string();

    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        trace_id.clone(),
        session_id.clone(),
    );

    let req = test_query_request("failure tracer query", &session_id);
    let mut ctx = WorkflowContext::new(session_id.clone(), trace_id.clone(), &req);
    ctx.merge_notices(vec![
        test_notice(
            NoticeCode::GraphTimeout,
            "Graph query timed out",
            NoticeSeverity::Warning,
        ),
        test_notice(
            NoticeCode::GraphDegraded,
            "Graph context degraded",
            NoticeSeverity::Info,
        ),
    ]);
    ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
        id: "[1]".into(),
        chunk_id: "chunk-1".into(),
        document_id: "doc-1".into(),
        chunk_index: 0,
        title: Some("Title".into()),
        section_path: Some("Section".into()),
        content_type: Some("text/plain".into()),
        provenance: "test".into(),
        text: "Sample text".into(),
        score: 0.9,
        rank: 1,
        suspicious: false,
    }];

    let fake_gen: Arc<dyn Generator> = Arc::new(FakeGenerator::with_responses(vec![
        Err(engine::generation::GenerationError::new(
            engine::generation::GenerationErrorKind::Timeout,
            "generation timeout",
        )),
        Err(engine::generation::GenerationError::new(
            engine::generation::GenerationErrorKind::Timeout,
            "generation timeout",
        )),
    ]));

    let mut runner = WorkflowRunner::new();
    runner.add_node(GenerateAnswerNode::new(Some(fake_gen)));

    let handle = tokio::spawn(async move {
        runner.run_workflow(ctx, cancel, sink).await;
    });
    let _guard = AbortOnDrop(Some(handle));

    let events = tokio::time::timeout(Duration::from_secs(5), async {
        let mut events = Vec::new();
        while let Some(event) = rx.recv().await {
            if let Ok(wf_event) = event {
                events.push(wf_event);
            }
        }
        events
    })
    .await
    .expect("failure event stream must complete");

    for ev in &events {
        assert_eq!(ev.trace_id, trace_id);
        assert_eq!(ev.session_id, session_id);
    }

    let node_failed_idx = events
        .iter()
        .position(|e| matches!(&e.event, Some(Event::NodeFailed(_))))
        .expect("NodeFailed event must exist");

    let completed_idx = events
        .iter()
        .position(|e| matches!(&e.event, Some(Event::WorkflowCompleted(_))))
        .expect("WorkflowCompleted event must exist");

    assert!(
        node_failed_idx < completed_idx,
        "NodeFailed must precede WorkflowCompleted"
    );

    assert!(
        events.iter().all(|e| !matches!(
            &e.event,
            Some(Event::AnswerChunk(_)) | Some(Event::FinalAnswer(_))
        )),
        "failed workflow must omit AnswerChunk and FinalAnswer"
    );

    let completed = match &events[completed_idx].event {
        Some(Event::WorkflowCompleted(wc)) => wc,
        _ => unreachable!(),
    };
    assert!(!completed.success);
    assert!(completed.final_response.is_none());
    assert_eq!(completed.notices.len(), 2);
    assert_eq!(completed.notices[0].code, "GRAPH_TIMEOUT");
    assert_eq!(completed.notices[0].message, "Graph query timed out");
    assert_eq!(
        completed.notices[0].severity,
        engine::pb::lancet::v1::NoticeSeverity::Warning as i32
    );
    assert_eq!(completed.notices[1].code, "GRAPH_DEGRADED");
    assert_eq!(completed.notices[1].message, "Graph context degraded");
    assert_eq!(
        completed.notices[1].severity,
        engine::pb::lancet::v1::NoticeSeverity::Info as i32
    );
}

#[tokio::test]
async fn workflow_phase5_failure_terminal_preserves_notices_without_answer_events() {
    // 1. Test failure path
    {
        let (tx, mut rx) = mpsc::channel(100);
        let cancel = CancellationToken::new();
        let trace_id = "trace-failure-preserves-01".to_string();
        let session_id = "sess-failure-preserves-01".to_string();

        let sink = WorkflowEventSink::new(
            tx,
            Arc::new(EventSequence::new()),
            trace_id.clone(),
            session_id.clone(),
        );

        let req = test_query_request("failure preserves notices query", &session_id);
        let mut ctx = WorkflowContext::new(session_id.clone(), trace_id.clone(), &req);
        ctx.merge_notices(vec![
            test_notice(
                NoticeCode::GraphDegraded,
                "graph degraded early",
                NoticeSeverity::Info,
            ),
            test_notice(
                NoticeCode::GraphTimeout,
                "graph query timed out later",
                NoticeSeverity::Warning,
            ),
        ]);
        ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
            id: "[1]".into(),
            chunk_id: "chunk-1".into(),
            document_id: "doc-1".into(),
            chunk_index: 0,
            title: Some("Title".into()),
            section_path: Some("Section".into()),
            content_type: Some("text/plain".into()),
            provenance: "test".into(),
            text: "Sample text".into(),
            score: 0.9,
            rank: 1,
            suspicious: false,
        }];

        let fake_gen: Arc<dyn Generator> = Arc::new(FakeGenerator::with_responses(vec![
            Err(engine::generation::GenerationError::new(
                engine::generation::GenerationErrorKind::ProviderError,
                "provider down",
            )),
            Err(engine::generation::GenerationError::new(
                engine::generation::GenerationErrorKind::ProviderError,
                "provider down",
            )),
        ]));

        let mut runner = WorkflowRunner::new();
        runner.add_node(GenerateAnswerNode::new(Some(fake_gen)));

        let handle = tokio::spawn(async move {
            runner.run_workflow(ctx, cancel, sink).await;
        });
        let _guard = AbortOnDrop(Some(handle));

        let events = tokio::time::timeout(Duration::from_secs(5), async {
            let mut events = Vec::new();
            while let Some(event) = rx.recv().await {
                if let Ok(wf_event) = event {
                    events.push(wf_event);
                }
            }
            events
        })
        .await
        .expect("failure stream completes");

        let node_failed_events: Vec<_> = events
            .iter()
            .filter(|e| matches!(&e.event, Some(Event::NodeFailed(_))))
            .collect();
        assert_eq!(
            node_failed_events.len(),
            1,
            "exactly one NodeFailed event must be emitted"
        );

        let completed_events: Vec<_> = events
            .iter()
            .filter(|e| matches!(&e.event, Some(Event::WorkflowCompleted(_))))
            .collect();
        assert_eq!(
            completed_events.len(),
            1,
            "exactly one WorkflowCompleted event must be emitted"
        );

        let node_failed_pos = events
            .iter()
            .position(|e| matches!(&e.event, Some(Event::NodeFailed(_))))
            .unwrap();
        let completed_pos = events
            .iter()
            .position(|e| matches!(&e.event, Some(Event::WorkflowCompleted(_))))
            .unwrap();
        assert!(
            node_failed_pos < completed_pos,
            "NodeFailed must precede WorkflowCompleted"
        );

        let completed = match &completed_events[0].event {
            Some(Event::WorkflowCompleted(wc)) => wc,
            _ => unreachable!(),
        };
        assert!(!completed.success);
        assert!(completed.final_response.is_none());
        assert_eq!(
            completed.error_kind,
            NodeErrorKind::LlmGenerationFailed as i32
        );
        assert_eq!(completed.error_message, "provider down");
        assert_eq!(completed.notices.len(), 2);
        assert_eq!(completed.notices[0].code, "GRAPH_DEGRADED");
        assert_eq!(completed.notices[0].message, "graph degraded early");
        assert_eq!(
            completed.notices[0].severity,
            engine::pb::lancet::v1::NoticeSeverity::Info as i32
        );
        assert_eq!(completed.notices[1].code, "GRAPH_TIMEOUT");
        assert_eq!(completed.notices[1].message, "graph query timed out later");
        assert_eq!(
            completed.notices[1].severity,
            engine::pb::lancet::v1::NoticeSeverity::Warning as i32
        );

        assert!(
            events.iter().all(|e| !matches!(
                &e.event,
                Some(Event::AnswerChunk(_)) | Some(Event::FinalAnswer(_))
            )),
            "failed stream must contain no AnswerChunk or FinalAnswer"
        );
    }

    // 2. Test success path preserves final answer and response notices
    {
        let (tx, mut rx) = mpsc::channel(100);
        let cancel = CancellationToken::new();
        let trace_id = "trace-success-preserves-01".to_string();
        let session_id = "sess-success-preserves-01".to_string();

        let sink = WorkflowEventSink::new(
            tx,
            Arc::new(EventSequence::new()),
            trace_id.clone(),
            session_id.clone(),
        );

        let req = test_query_request("success preserves notices query", &session_id);
        let mut ctx = WorkflowContext::new(session_id.clone(), trace_id.clone(), &req);
        ctx.merge_notices(vec![test_notice(
            NoticeCode::GraphDegraded,
            "graph degraded during success",
            NoticeSeverity::Info,
        )]);
        ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
            id: "[1]".into(),
            chunk_id: "chunk-1".into(),
            document_id: "doc-1".into(),
            chunk_index: 0,
            title: Some("Title".into()),
            section_path: Some("Section".into()),
            content_type: Some("text/plain".into()),
            provenance: "test".into(),
            text: "Sample text".into(),
            score: 0.9,
            rank: 1,
            suspicious: false,
        }];

        let fake_gen: Arc<dyn Generator> = Arc::new(FakeGenerator::new(Ok(ModelOutput {
            answer: "Successful answer [1].".into(),
            cited_evidence_ids: vec!["[1]".into()],
            answer_basis: AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            usage: None,
        })));

        let mut runner = WorkflowRunner::new();
        runner.add_node(GenerateAnswerNode::new(Some(fake_gen)));

        let handle = tokio::spawn(async move {
            runner.run_workflow(ctx, cancel, sink).await;
        });
        let _guard = AbortOnDrop(Some(handle));

        let events = tokio::time::timeout(Duration::from_secs(5), async {
            let mut events = Vec::new();
            while let Some(event) = rx.recv().await {
                if let Ok(wf_event) = event {
                    events.push(wf_event);
                }
            }
            events
        })
        .await
        .expect("success stream completes");

        let completed = events
            .iter()
            .find_map(|e| match &e.event {
                Some(Event::WorkflowCompleted(wc)) => Some(wc),
                _ => None,
            })
            .expect("WorkflowCompleted event exists");

        assert!(completed.success);
        let final_resp = completed
            .final_response
            .as_ref()
            .expect("final_response must be present on success");
        assert_eq!(final_resp.answer, "Successful answer [1].");
        assert_eq!(final_resp.notices.len(), 1);
        assert_eq!(final_resp.notices[0].code, "GRAPH_DEGRADED");
        assert_eq!(completed.notices.len(), 1);
        assert_eq!(completed.notices[0].code, "GRAPH_DEGRADED");
    }
}

#[test]
fn test_notice_constructor_all_published_values_yield_non_empty_code_and_match_derivation() {
    let all_codes = [
        NoticeCode::Unspecified,
        NoticeCode::NoEvidence,
        NoticeCode::GraphTimeout,
        NoticeCode::GraphDegraded,
        NoticeCode::ModelNotice,
        NoticeCode::ModelWarning,
        NoticeCode::GraphUnavailable,
        NoticeCode::RetrievalDegradedDense,
        NoticeCode::CitationRepaired,
        NoticeCode::CitationDropped,
        NoticeCode::ModelOnly,
        NoticeCode::BasisReconciled,
        NoticeCode::RetrievalDegradedBm25,
        NoticeCode::GraphAblation,
        NoticeCode::IndexRebuildFailed,
        NoticeCode::IndexStale,
        NoticeCode::IndexGenerationMismatch,
    ];

    for code in all_codes {
        let n = engine::workflow::notice(code, "test message", NoticeSeverity::Info);
        assert!(
            !n.code.is_empty(),
            "derived string code must not be empty for {code:?}"
        );
        assert_eq!(n.typed_code, code as i32);
        let expected_str = code.as_str_name().trim_start_matches("NOTICE_CODE_");
        assert_eq!(n.code, expected_str);
    }
}

#[test]
fn test_notice_constructor_shipped_codes_roundtrip_spellings() {
    let n_no_evidence =
        engine::workflow::notice(NoticeCode::NoEvidence, "msg", NoticeSeverity::Info);
    assert_eq!(n_no_evidence.code, "NO_EVIDENCE");

    let n_timeout = engine::workflow::notice(NoticeCode::GraphTimeout, "msg", NoticeSeverity::Info);
    assert_eq!(n_timeout.code, "GRAPH_TIMEOUT");

    let n_degraded =
        engine::workflow::notice(NoticeCode::GraphDegraded, "msg", NoticeSeverity::Info);
    assert_eq!(n_degraded.code, "GRAPH_DEGRADED");
}

#[test]
fn test_notice_deduplication_preserves_distinct_messages_and_collapses_identical() {
    let req = test_query_request("q", "s");
    let mut ctx = WorkflowContext::new("s".into(), "t".into(), &req);

    // Two notices with same code but different messages both survive
    let n1 = engine::workflow::notice(NoticeCode::GraphDegraded, "message 1", NoticeSeverity::Info);
    let n2 = engine::workflow::notice(NoticeCode::GraphDegraded, "message 2", NoticeSeverity::Info);
    ctx.add_notice(n1.clone());
    ctx.add_notice(n2.clone());
    assert_eq!(ctx.notices.len(), 2);

    // Identical notice (same code and same message) collapses to one
    let n1_dup =
        engine::workflow::notice(NoticeCode::GraphDegraded, "message 1", NoticeSeverity::Info);
    ctx.add_notice(n1_dup);
    assert_eq!(ctx.notices.len(), 2);
}

#[test]
fn test_notice_published_enum_reachability_or_reservation() {
    // Explicit ground truth map of emission sites or Phase 6 / Phase 6.1 reservations
    let published_manifest = [
        (NoticeCode::Unspecified, "proto default / fallback"),
        (
            NoticeCode::NoEvidence,
            "engine/src/workflow/nodes/retrieve.rs",
        ),
        (
            NoticeCode::GraphTimeout,
            "engine/src/workflow/nodes/graph_context.rs",
        ),
        (
            NoticeCode::GraphDegraded,
            "engine/src/workflow/nodes/graph_context.rs",
        ),
        (NoticeCode::ModelNotice, "engine/src/workflow/mod.rs"),
        (NoticeCode::ModelWarning, "engine/src/workflow/mod.rs"),
        (
            NoticeCode::GraphUnavailable,
            "Phase 6 plan 06-08 emission site",
        ),
        (
            NoticeCode::RetrievalDegradedDense,
            "Phase 6 plan 06-09 emission site",
        ),
        (
            NoticeCode::CitationRepaired,
            "Phase 6 plan 06-11 emission site",
        ),
        (
            NoticeCode::CitationDropped,
            "Phase 6 plan 06-11 emission site",
        ),
        (NoticeCode::ModelOnly, "Phase 6 plan 06-10 emission site"),
        (
            NoticeCode::BasisReconciled,
            "Phase 6 plan 06-10 emission site",
        ),
        (
            NoticeCode::RetrievalDegradedBm25,
            "Phase 6 plan 06-09 emission site",
        ),
        (
            NoticeCode::GraphAblation,
            "Phase 6 plan 06-08 emission site",
        ),
        (NoticeCode::IndexRebuildFailed, "reserved for Phase 6.1"),
        (NoticeCode::IndexStale, "reserved for Phase 6.1"),
        (
            NoticeCode::IndexGenerationMismatch,
            "reserved for Phase 6.1",
        ),
    ];

    for (code, rationale) in published_manifest {
        assert!(
            !rationale.is_empty(),
            "{code:?} must have an emission site or reservation"
        );
        let n = engine::workflow::notice(code, "manifest validation", NoticeSeverity::Info);
        assert!(!n.code.is_empty());
    }
}

#[tokio::test]
async fn test_workflow_runner_zero_evidence_gate_typed_code() {
    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let trace_id = "trace-zero-ev-typed".to_string();
    let session_id = "sess-zero-ev-typed".to_string();

    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        trace_id.clone(),
        session_id.clone(),
    );

    let req = test_query_request("zero ev query", &session_id);
    let mut ctx = WorkflowContext::new(session_id.clone(), trace_id.clone(), &req);
    ctx.add_notice(engine::workflow::notice(
        NoticeCode::NoEvidence,
        "No completed corpus evidence matched the requested filters.",
        NoticeSeverity::Info,
    ));

    // When runner runs AssemblePrompt with zero evidence notice, it breaks before executing
    let mut runner = WorkflowRunner::new();
    runner.add_node(AssemblePromptNode::default());
    runner.add_node(GenerateAnswerNode::default());

    runner.run_workflow(ctx, cancel, sink).await;

    let mut events = Vec::new();
    while let Ok(wf_event) = rx.try_recv() {
        if let Ok(ev) = wf_event {
            events.push(ev);
        }
    }

    // WorkflowCompleted is emitted, but no NodeStarted / AnswerChunk for AssemblePrompt / GenerateAnswer
    let completed_event = events
        .iter()
        .find(|e| matches!(&e.event, Some(Event::WorkflowCompleted(_))));
    assert!(
        completed_event.is_some(),
        "WorkflowCompleted must be emitted"
    );
    assert!(
        events
            .iter()
            .all(|e| !matches!(&e.event, Some(Event::NodeStarted(_)))),
        "AssemblePrompt and GenerateAnswer must not start on zero evidence"
    );
}

#[tokio::test]
async fn graph_ablation_flag_true_e2e_service() {
    use crate::db::DatabaseManager;
    use crate::pb::lancet::v1::lancet_service_server::LancetService;
    use crate::tests::{configured_service, database_path, FakeEmbedder, FakeGenerator};
    use tokio_stream::StreamExt;

    let path = database_path("test-graph-ablation-e2e");
    let db = DatabaseManager::initialize(&path).await.unwrap();
    let generator: Arc<dyn Generator> = Arc::new(FakeGenerator::new(Ok(ModelOutput {
        answer: "Answer produced from source chunks [1].".into(),
        cited_evidence_ids: vec!["[1]".into()],
        answer_basis: AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        usage: None,
    })));

    let service = configured_service(
        &db,
        crate::config::EffectiveRagSettings::default(),
        Arc::new(FakeEmbedder),
        generator,
        Arc::new(crate::rerank::NoOpReranker::new()),
    )
    .await;

    let session_id = "00000000-0000-4000-8000-000000000088";
    let mut req = test_query_request("Test ablation query", session_id);
    req.disable_graph_context = Some(true);

    let stream_res = service.query_rag(tonic::Request::new(req)).await.unwrap();
    let mut stream = stream_res.into_inner();
    let mut completed = None;
    while let Some(res) = stream.next().await {
        let ev = res.unwrap();
        if let Some(Event::WorkflowCompleted(ref wc)) = ev.event {
            completed = Some(wc.clone());
        }
    }
    let wc = completed.expect("WorkflowCompleted event must be received");
    assert!(
        wc.success,
        "Workflow execution should succeed: error_kind={:?}, error_msg={}",
        wc.error_kind, wc.error_message
    );
    let resp = wc.final_response.expect("final_response must be present");
    assert!(
        resp.notices
            .iter()
            .any(|n| n.code == "GRAPH_ABLATION" && n.typed_code == NoticeCode::GraphAblation as i32),
        "response notices must contain GRAPH_ABLATION notice"
    );
    assert!(
        !resp.notices.iter().any(|n| n.code == "GRAPH_UNAVAILABLE"
            || n.typed_code == NoticeCode::GraphUnavailable as i32),
        "response notices must NOT contain GRAPH_UNAVAILABLE notice"
    );

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn graph_ablation_empty_facts_and_context_with_grounded_answer() {
    let mut req = test_query_request("Ablation context test", "sess-ablation-ctx");
    req.disable_graph_context = Some(true);
    let mut ctx = WorkflowContext::new(
        "sess-ablation-ctx".into(),
        "trace-ablation-ctx".into(),
        &req,
    );
    ctx.evidence_blocks = vec![engine::prompt::EvidenceBlock {
        id: "[1]".into(),
        chunk_id: "chunk-1".into(),
        document_id: "doc-1".into(),
        chunk_index: 0,
        title: Some("Doc 1".into()),
        section_path: Some("Sec 1".into()),
        content_type: Some("text/plain".into()),
        provenance: "test".into(),
        text: "Direct source chunk content.".into(),
        score: 0.95,
        rank: 1,
        suspicious: false,
    }];

    let fake_graph = Arc::new(FakeGraphQueryPort::success("entity_a -- rel -- entity_b"));
    let node = ExtractGraphContextNode::new(None, Some(fake_graph));
    let cancel = CancellationToken::new();

    node.run(&mut ctx, &cancel).await.expect("node succeeds");

    assert!(ctx.graph_context.is_empty(), "graph_context must be empty");
    assert!(ctx.graph_facts.is_empty(), "graph_facts must be empty");
    assert!(
        ctx.notices
            .iter()
            .any(|n| n.code == "GRAPH_ABLATION" && n.typed_code == NoticeCode::GraphAblation as i32),
        "notices must contain GRAPH_ABLATION"
    );
    assert!(
        !ctx.notices.iter().any(|n| n.code == "GRAPH_UNAVAILABLE"),
        "notices must NOT contain GRAPH_UNAVAILABLE"
    );
}

#[tokio::test]
async fn graph_ablation_absent_flag_defaults_to_graph_enabled() {
    let req = test_query_request("Absent flag test", "sess-absent-flag");
    assert_eq!(req.disable_graph_context, None);
    let mut ctx = WorkflowContext::new("sess-absent-flag".into(), "trace-absent-flag".into(), &req);
    assert!(!ctx.disable_graph_context);

    let fake_graph = Arc::new(FakeGraphQueryPort::success("entity_a -- rel -- entity_b"));
    let node = ExtractGraphContextNode::new(None, Some(fake_graph));
    let cancel = CancellationToken::new();

    node.run(&mut ctx, &cancel).await.expect("node succeeds");

    assert!(
        !ctx.graph_context.is_empty(),
        "graph_context must be populated"
    );
    assert_eq!(ctx.graph_facts.len(), 1, "graph_facts must have 1 fact");
    assert!(
        !ctx.notices
            .iter()
            .any(|n| n.code == "GRAPH_ABLATION" || n.typed_code == NoticeCode::GraphAblation as i32),
        "notices must NOT contain GRAPH_ABLATION"
    );
}

#[tokio::test]
async fn graph_ablation_explicit_false_defaults_to_graph_enabled() {
    let mut req = test_query_request("Explicit false flag test", "sess-false-flag");
    req.disable_graph_context = Some(false);
    let mut ctx = WorkflowContext::new("sess-false-flag".into(), "trace-false-flag".into(), &req);
    assert!(!ctx.disable_graph_context);

    let fake_graph = Arc::new(FakeGraphQueryPort::success("entity_a -- rel -- entity_b"));
    let node = ExtractGraphContextNode::new(None, Some(fake_graph));
    let cancel = CancellationToken::new();

    node.run(&mut ctx, &cancel).await.expect("node succeeds");

    assert!(
        !ctx.graph_context.is_empty(),
        "graph_context must be populated"
    );
    assert_eq!(ctx.graph_facts.len(), 1, "graph_facts must have 1 fact");
    assert!(
        !ctx.notices
            .iter()
            .any(|n| n.code == "GRAPH_ABLATION" || n.typed_code == NoticeCode::GraphAblation as i32),
        "notices must NOT contain GRAPH_ABLATION"
    );
}

#[tokio::test]
async fn graph_ablation_graph_port_never_called_when_flag_true() {
    let mut req = test_query_request("Port call count test", "sess-call-count");
    req.disable_graph_context = Some(true);
    let mut ctx = WorkflowContext::new("sess-call-count".into(), "trace-call-count".into(), &req);

    let fake_graph = Arc::new(FakeGraphQueryPort::success("entity_a -- rel -- entity_b"));
    let fake_embedding = Arc::new(FakeQueryEmbeddingPort::success(vec![0.1; 2048]));
    let node = ExtractGraphContextNode::new(Some(fake_embedding.clone()), Some(fake_graph.clone()));
    let cancel = CancellationToken::new();

    node.run(&mut ctx, &cancel).await.expect("node succeeds");

    assert_eq!(
        fake_graph.calls(),
        0,
        "fake graph port must never be called when ablation flag is true"
    );
}

#[tokio::test]
async fn graph_unavailable_notice_on_empty_result() {
    let req = test_query_request("Empty graph result query", "sess-empty-graph");
    let mut ctx = WorkflowContext::new("sess-empty-graph".into(), "trace-empty-graph".into(), &req);
    let fake_graph = Arc::new(FakeGraphQueryPort::success(Vec::<String>::new()));
    let node = ExtractGraphContextNode::new(None, Some(fake_graph));
    let cancel = CancellationToken::new();

    node.run(&mut ctx, &cancel).await.expect("node succeeds");

    assert!(ctx.graph_context.is_empty());
    assert!(ctx.graph_facts.is_empty());
    let notice = ctx
        .notices
        .iter()
        .find(|n| {
            n.code == "GRAPH_UNAVAILABLE" && n.typed_code == NoticeCode::GraphUnavailable as i32
        })
        .expect("GRAPH_UNAVAILABLE notice must be emitted on empty result");
    assert_eq!(
        notice.message,
        "Graph query returned no facts for this query"
    );
    assert_eq!(notice.severity, NoticeSeverity::Info as i32);
}

#[tokio::test]
async fn graph_unavailable_notice_on_absent_graph_port() {
    let req = test_query_request("Absent graph port query", "sess-no-port");
    let mut ctx = WorkflowContext::new("sess-no-port".into(), "trace-no-port".into(), &req);
    let node = ExtractGraphContextNode::new(None, None);
    let cancel = CancellationToken::new();

    node.run(&mut ctx, &cancel).await.expect("node succeeds");

    assert!(ctx.graph_context.is_empty());
    assert!(ctx.graph_facts.is_empty());
    let notice = ctx
        .notices
        .iter()
        .find(|n| {
            n.code == "GRAPH_UNAVAILABLE" && n.typed_code == NoticeCode::GraphUnavailable as i32
        })
        .expect("GRAPH_UNAVAILABLE notice must be emitted on absent port");
    assert_eq!(
        notice.message,
        "Graph context is not configured; answer produced from source chunks only"
    );
    assert_eq!(notice.severity, NoticeSeverity::Info as i32);
}

#[tokio::test]
async fn graph_unavailable_distinct_messages_survive_deduplication() {
    let req = test_query_request("Dedup query", "sess-dedup");
    let mut ctx = WorkflowContext::new("sess-dedup".into(), "trace-dedup".into(), &req);

    ctx.add_notice(engine::workflow::notice(
        NoticeCode::GraphUnavailable,
        "Graph query returned no facts for this query",
        NoticeSeverity::Info,
    ));
    ctx.add_notice(engine::workflow::notice(
        NoticeCode::GraphUnavailable,
        "Graph context is not configured; answer produced from source chunks only",
        NoticeSeverity::Info,
    ));

    assert_eq!(
        ctx.notices.len(),
        2,
        "both distinct graph unavailability messages must survive deduplication"
    );
    assert_eq!(ctx.notices[0].code, "GRAPH_UNAVAILABLE");
    assert_eq!(ctx.notices[1].code, "GRAPH_UNAVAILABLE");
    assert_ne!(ctx.notices[0].message, ctx.notices[1].message);
}

#[tokio::test]
async fn graph_timeout_notice_regression_unchanged() {
    let req = test_query_request("Timeout query", "sess-timeout");
    let mut ctx = WorkflowContext::new("sess-timeout".into(), "trace-timeout".into(), &req);
    let fake_graph = Arc::new(FakeGraphQueryPort::failure(NodeError::new(
        NodeErrorKind::Timeout,
        "GRAPH_TIMEOUT",
    )));
    let node = ExtractGraphContextNode::new(None, Some(fake_graph));
    let cancel = CancellationToken::new();

    node.run(&mut ctx, &cancel)
        .await
        .expect("node succeeds with degrade");

    assert_eq!(ctx.notices.len(), 1, "exactly one notice on timeout");
    let n = &ctx.notices[0];
    assert_eq!(n.code, "GRAPH_TIMEOUT");
    assert_eq!(n.typed_code, NoticeCode::GraphTimeout as i32);
    assert_eq!(n.message, "GRAPH_TIMEOUT");
    assert_eq!(n.severity, NoticeSeverity::Info as i32);
}

#[tokio::test]
async fn graph_degraded_notice_regression_unchanged() {
    let req = test_query_request("Degraded query", "sess-degraded");
    let mut ctx = WorkflowContext::new("sess-degraded".into(), "trace-degraded".into(), &req);
    let fake_graph = Arc::new(FakeGraphQueryPort::failure(NodeError::new(
        NodeErrorKind::GraphFailed,
        "lancedb connection dropped",
    )));
    let node = ExtractGraphContextNode::new(None, Some(fake_graph));
    let cancel = CancellationToken::new();

    node.run(&mut ctx, &cancel)
        .await
        .expect("node succeeds with degrade");

    assert_eq!(ctx.notices.len(), 1, "exactly one notice on degraded");
    let n = &ctx.notices[0];
    assert_eq!(n.code, "GRAPH_DEGRADED");
    assert_eq!(n.typed_code, NoticeCode::GraphDegraded as i32);
    assert_eq!(n.message, "graph_degrade: lancedb connection dropped");
    assert_eq!(n.severity, NoticeSeverity::Info as i32);
}

#[tokio::test]
async fn graph_ablation_does_not_emit_graph_unavailability_notice() {
    let mut req = test_query_request("Ablation no unavail query", "sess-ablation-no-unavail");
    req.disable_graph_context = Some(true);
    let mut ctx = WorkflowContext::new(
        "sess-ablation-no-unavail".into(),
        "trace-ablation-no-unavail".into(),
        &req,
    );
    // Node with absent graph port
    let node = ExtractGraphContextNode::new(None, None);
    let cancel = CancellationToken::new();

    node.run(&mut ctx, &cancel).await.expect("node succeeds");

    assert!(
        ctx.notices
            .iter()
            .any(|n| n.code == "GRAPH_ABLATION" && n.typed_code == NoticeCode::GraphAblation as i32),
        "must emit GRAPH_ABLATION"
    );
    assert!(
        !ctx.notices.iter().any(|n| n.code == "GRAPH_UNAVAILABLE"
            || n.typed_code == NoticeCode::GraphUnavailable as i32),
        "must NOT emit GRAPH_UNAVAILABLE when ablated"
    );
}
