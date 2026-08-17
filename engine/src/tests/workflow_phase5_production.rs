use std::sync::Arc;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::{
    db::DatabaseManager,
    generation::{self, AnswerBasis, ModelOutput},
    rerank,
    tests::{configured_service, database_path, FakeEmbedder},
    workflow::{
        self,
        events::EventSequence,
        node::Node,
        WorkflowContext, WorkflowEventSink,
    },
};
use engine::pb::lancet::v1::{self, QueryRagRequest};

#[tokio::test]
async fn workflow_phase5_production_five_node() {
    let path = database_path("prod-five-node");
    let db = DatabaseManager::initialize(&path).await.unwrap();
    let service = configured_service(
        &db,
        crate::EffectiveRagSettings::default(),
        Arc::new(FakeEmbedder),
        Arc::new(generation::FakeGenerator::new(Ok(ModelOutput {
            answer: "Production answer".into(),
            cited_evidence_ids: vec![],
            answer_basis: AnswerBasis::ModelOnly,
            notices: vec![],
            warnings: vec![],
            usage: None,
        }))),
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;

    let (runner, _deps) = service.build_production_workflow();
    assert_eq!(runner.timeout_for_node("ReformulateQuery").as_millis(), 5000);
    assert_eq!(runner.timeout_for_node("ExtractGraphContext").as_millis(), 15000);
    assert_eq!(runner.timeout_for_node("RetrieveHybrid").as_millis(), 10000);
    assert_eq!(runner.timeout_for_node("AssemblePrompt").as_millis(), 2000);
    assert_eq!(runner.timeout_for_node("GenerateAnswer").as_millis(), 65000);

    let req = QueryRagRequest {
        query: "What is Lancet production workflow?".into(),
        session_id: "00000000-0000-4000-8000-000000000001".into(),
        filter: None,
    };
    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "test-trace".into(),
        "00000000-0000-4000-8000-000000000001".into(),
    );
    let ctx = WorkflowContext::new("00000000-0000-4000-8000-000000000001".into(), "test-trace".into(), &req);

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
            Some(v1::workflow_event::Event::NodeStarted(ns)) => Some(ns.node_name.clone()),
            _ => None,
        })
        .collect();

    assert!(node_started_names.contains(&"ReformulateQuery".to_string()));
    assert!(node_started_names.contains(&"ExtractGraphContext".to_string()));
    assert!(node_started_names.contains(&"RetrieveHybrid".to_string()));
    // Zero evidence short-circuits before AssemblePrompt / GenerateAnswer per D-03
    let terminal = events
        .iter()
        .find_map(|e| match &e.event {
            Some(v1::workflow_event::Event::WorkflowCompleted(wc)) => Some(wc),
            _ => None,
        })
        .expect("WorkflowCompleted event must be emitted");
    assert!(terminal.success);
}

#[tokio::test]
async fn workflow_phase5_production_dependencies_are_real() {
    let path = database_path("prod-deps-real");
    let db = DatabaseManager::initialize(&path).await.unwrap();
    let embedder: Arc<dyn crate::EmbeddingProvider> = Arc::new(FakeEmbedder);
    let generator: Arc<dyn generation::Generator> = Arc::new(generation::FakeGenerator::new(Ok(ModelOutput {
        answer: "Answer".into(),
        cited_evidence_ids: vec![],
        answer_basis: AnswerBasis::ModelOnly,
        notices: vec![],
        warnings: vec![],
        usage: None,
    })));
    let reranker: Arc<dyn rerank::Reranker> = Arc::new(rerank::NoOpReranker::new());

    let service = configured_service(
        &db,
        crate::EffectiveRagSettings::default(),
        Arc::clone(&embedder),
        Arc::clone(&generator),
        Arc::clone(&reranker),
    )
    .await;

    // Construction 1 and construction 2 verify cheap handle reuse without reinitialization
    let (_runner1, deps1) = service.build_production_workflow();
    let (_runner2, deps2) = service.build_production_workflow();

    // Verify that Arc::clone is used and Arc::ptr_eq / strong_count proves handle reuse across constructions
    assert!(Arc::ptr_eq(&service.reranker, deps1.reranker_port.as_ref().unwrap()));
    assert!(Arc::ptr_eq(&service.reranker, deps2.reranker_port.as_ref().unwrap()));
    assert!(Arc::ptr_eq(&service.generator, deps1.generator.as_ref().unwrap()));
    assert!(Arc::ptr_eq(&service.generator, deps2.generator.as_ref().unwrap()));
    let strong_count = Arc::strong_count(&service.reranker);
    assert!(strong_count >= 3, "Arc::strong_count must reflect shared handles across construction calls");
}

#[tokio::test]
async fn workflow_phase5_production_context_population() {
    let path = database_path("prod-ctx-pop");
    let db = DatabaseManager::initialize(&path).await.unwrap();
    let service = configured_service(
        &db,
        crate::EffectiveRagSettings::default(),
        Arc::new(FakeEmbedder),
        Arc::new(generation::FakeGenerator::new(Ok(ModelOutput {
            answer: "Populated answer".into(),
            cited_evidence_ids: vec![],
            answer_basis: AnswerBasis::ModelOnly,
            notices: vec![],
            warnings: vec![],
            usage: None,
        }))),
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;

    let req = QueryRagRequest {
        query: "Populate context test".into(),
        session_id: "00000000-0000-4000-8000-000000000002".into(),
        filter: None,
    };
    let mut ctx = WorkflowContext::new("00000000-0000-4000-8000-000000000002".into(), "trace-ctx".into(), &req);
    let cancel = CancellationToken::new();

    let (_runner, deps) = service.build_production_workflow();
    let reformulate_node = workflow::nodes::ReformulateQueryNode::with_reformulator(deps.reformulator.clone());
    reformulate_node.run(&mut ctx, &cancel).await.unwrap();
    assert_eq!(ctx.variants, vec!["Populate context test"]);

    let graph_node = workflow::nodes::ExtractGraphContextNode::new(deps.embedding_port.clone(), deps.graph_port.clone());
    graph_node.run(&mut ctx, &cancel).await.unwrap();
    assert!(ctx.query_embedding.is_some());
    assert_eq!(ctx.query_embedding.as_ref().unwrap().len(), 2048);

    let retrieve_node = workflow::nodes::RetrieveHybridNode::new(
        deps.dense_port.clone(),
        deps.bm25_port.clone(),
        deps.reranker_port.clone(),
        deps.retrieval_settings.clone(),
    );
    retrieve_node.run(&mut ctx, &cancel).await.unwrap();
    assert!(ctx.snapshot.is_some());
}

#[tokio::test]
async fn workflow_phase5_settings_applied_to_production() {
    let path = database_path("prod-settings-applied");
    let db = DatabaseManager::initialize(&path).await.unwrap();

    let mut custom_settings = crate::EffectiveRagSettings::default();
    custom_settings.workflow = crate::WorkflowSettings {
        reformulate_timeout_ms: 1234,
        query_embedding_timeout_ms: 2345,
        retrieve_timeout_ms: 3456,
        graph_operation_timeout_ms: 4567,
        graph_node_timeout_ms: 5678,
        prompt_timeout_ms: 6789,
        generation_node_timeout_ms: 7890,
    };

    let service = configured_service(
        &db,
        custom_settings,
        Arc::new(FakeEmbedder),
        Arc::new(generation::FakeGenerator::new(Ok(ModelOutput {
            answer: "Settings answer".into(),
            cited_evidence_ids: vec![],
            answer_basis: AnswerBasis::ModelOnly,
            notices: vec![],
            warnings: vec![],
            usage: None,
        }))),
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;

    let (runner, _deps) = service.build_production_workflow();
    assert_eq!(runner.timeout_for_node("ReformulateQuery").as_millis(), 1234);
    assert_eq!(runner.timeout_for_node("ExtractGraphContext").as_millis(), 5678);
    assert_eq!(runner.timeout_for_node("RetrieveHybrid").as_millis(), 3456);
    assert_eq!(runner.timeout_for_node("AssemblePrompt").as_millis(), 6789);
    assert_eq!(runner.timeout_for_node("GenerateAnswer").as_millis(), 7890);
}

struct SlowLiveProvider {
    call_count: Arc<std::sync::atomic::AtomicUsize>,
    started: Arc<tokio::sync::Notify>,
}

impl generation::Generator for SlowLiveProvider {
    fn generate<'a>(
        &'a self,
        _request: generation::GenerationRequest,
    ) -> generation::BoxFuture<'a, Result<ModelOutput, generation::GenerationError>> {
        Box::pin(async move {
            self.call_count.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            self.started.notify_one();
            // Stalls for 30s (the openrouter attempt budget)
            tokio::time::sleep(std::time::Duration::from_secs(30)).await;
            Err(generation::GenerationError::new(
                generation::GenerationErrorKind::ProviderError,
                "Slow provider finished after 30s",
            ))
        })
    }
}

#[tokio::test]
async fn workflow_phase5_config_verify_generation_timeout() {
    let repo_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("repo root parent");
    let base_config_path = repo_root.join("config/config.toml");
    let base_raw = std::fs::read_to_string(&base_config_path).expect("read config.toml");
    let verify_config_path = repo_root.join("config/config.verify.toml");
    let verify_raw = std::fs::read_to_string(&verify_config_path).expect("read config.verify.toml");
    let settings: crate::Settings = config::Config::builder()
        .add_source(config::File::from_str(&base_raw, config::FileFormat::Toml))
        .add_source(config::File::from_str(&verify_raw, config::FileFormat::Toml))
        .build()
        .expect("parse config with verify overlay")
        .try_deserialize()
        .expect("deserialize config with verify overlay");

    let effective_settings = crate::EffectiveRagSettings::try_from_settings(&settings)
        .expect("effective settings from config.verify.toml");
    assert_eq!(effective_settings.workflow.generation_node_timeout_ms, 7000);
    assert_eq!(effective_settings.generation_timeout_secs, 30);

    let path = database_path("prod-verify-gen-timeout");
    let db = DatabaseManager::initialize(&path).await.unwrap();

    let call_count = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let started = Arc::new(tokio::sync::Notify::new());
    let slow_generator = Arc::new(SlowLiveProvider {
        call_count: Arc::clone(&call_count),
        started: Arc::clone(&started),
    });

    let service = configured_service(
        &db,
        effective_settings,
        Arc::new(FakeEmbedder),
        slow_generator,
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await;

    let (runner, deps) = service.build_production_workflow();
    assert_eq!(runner.timeout_for_node("GenerateAnswer").as_millis(), 7000);

    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-verify-timeout".into(),
        "00000000-0000-4000-8000-000000000099".into(),
    );

    let req = QueryRagRequest {
        query: "Verify live generation node timeout".into(),
        session_id: "00000000-0000-4000-8000-000000000099".into(),
        filter: None,
    };
    let mut ctx = WorkflowContext::new(
        "00000000-0000-4000-8000-000000000099".into(),
        "trace-verify-timeout".into(),
        &req,
    );

    // Provide evidence so AssemblePrompt and GenerateAnswer are reached
    ctx.evidence_blocks = vec![crate::prompt::EvidenceBlock {
        id: "[1]".to_string(),
        chunk_id: "chk-live-1".to_string(),
        document_id: "doc-live-1".to_string(),
        chunk_index: 0,
        title: Some("Title".to_string()),
        section_path: Some("Section".to_string()),
        content_type: Some("text/plain".to_string()),
        provenance: "provenance".to_string(),
        text: "Live test evidence".to_string(),
        score: 0.9,
        rank: 1,
        suspicious: false,
    }];

    let generate_node = workflow::nodes::GenerateAnswerNode::new(deps.generator.clone());
    let start_instant = std::time::Instant::now();

    let res = runner.run_node(&generate_node, &mut ctx, &cancel, &sink).await;
    let elapsed = start_instant.elapsed();

    assert!(res.is_err(), "GenerateAnswer must time out");
    let err = res.unwrap_err();
    assert_eq!(err.kind, v1::NodeErrorKind::Timeout);
    assert!(cancel.is_cancelled(), "stream cancellation token must be cancelled on timeout");

    // Wall-clock time should be near 7000ms, and materially below 30000ms (provider budget)
    assert!(
        elapsed >= std::time::Duration::from_millis(6500) && elapsed < std::time::Duration::from_millis(15000),
        "elapsed time ({:?}) must be close to configured 7000ms generation_node_timeout_ms and well below 30s",
        elapsed
    );

    // Check emitted events
    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(ev) = item {
            events.push(ev);
        }
    }
    let started_ev = events.iter().find(|e| matches!(&e.event, Some(v1::workflow_event::Event::NodeStarted(ns)) if ns.node_name == "GenerateAnswer"));
    assert!(started_ev.is_some(), "NodeStarted for GenerateAnswer must be observed");

    let failed_ev = events.iter().find_map(|e| match &e.event {
        Some(v1::workflow_event::Event::NodeFailed(nf)) if nf.node_name == "GenerateAnswer" => Some(nf),
        _ => None,
    });
    let failed = failed_ev.expect("NodeFailed for GenerateAnswer must be observed");
    assert_eq!(failed.category, v1::NodeErrorKind::Timeout as i32);
    assert_eq!(call_count.load(std::sync::atomic::Ordering::SeqCst), 1);
}
