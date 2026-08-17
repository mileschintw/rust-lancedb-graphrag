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
