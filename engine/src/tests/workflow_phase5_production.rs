use std::sync::Arc;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use crate::{
    db::DatabaseManager,
    generation::{self, AnswerBasis, ModelOutput},
    rerank,
    tests::{configured_service, database_path, FakeEmbedder, FakeGenerator},
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
        Arc::new(FakeGenerator::new(Ok(ModelOutput {
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
    let generator: Arc<dyn generation::Generator> = Arc::new(FakeGenerator::new(Ok(ModelOutput {
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
        Arc::new(FakeGenerator::new(Ok(ModelOutput {
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
        Arc::new(FakeGenerator::new(Ok(ModelOutput {
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

#[tokio::test]
async fn workflow_phase5_generation_retry_tracer() {
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::time::Duration;
    use serde_json::json;

    let listener = TcpListener::bind("127.0.0.1:0").expect("bind local mock server");
    let addr = listener.local_addr().unwrap();

    let models_calls = Arc::new(AtomicUsize::new(0));
    let chat_calls = Arc::new(AtomicUsize::new(0));
    let captured_chat_requests = Arc::new(std::sync::Mutex::new(Vec::new()));

    let models_calls_server = Arc::clone(&models_calls);
    let chat_calls_server = Arc::clone(&chat_calls);
    let captured_chat_requests_server = Arc::clone(&captured_chat_requests);

    let server_handle = std::thread::spawn(move || {
        listener.set_nonblocking(true).unwrap();
        let start = std::time::Instant::now();
        let mut conn_count = 0;
        while conn_count < 3 && start.elapsed() < Duration::from_secs(5) {
            match listener.accept() {
                Ok((mut stream, _)) => {
                    conn_count += 1;
                    stream.set_nonblocking(false).unwrap();
                    stream.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
                    let mut buf = [0u8; 8192];
                    let n = stream.read(&mut buf).unwrap_or(0);
                    let req_str = String::from_utf8_lossy(&buf[..n]).to_string();

                    if req_str.contains("GET /models") {
                        models_calls_server.fetch_add(1, Ordering::SeqCst);
                        let body = json!({
                            "data": [{
                                "id": "mock/retry-model",
                                "supported_parameters": ["response_format", "json_schema"]
                            }]
                        }).to_string();
                        let resp = format!(
                            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                            body.len(), body
                        );
                        let _ = stream.write_all(resp.as_bytes());
                    } else if req_str.contains("POST /chat") {
                        let count = chat_calls_server.fetch_add(1, Ordering::SeqCst);
                        captured_chat_requests_server.lock().unwrap().push(req_str);
                        if count == 0 {
                            // First attempt: transient 500 error
                            let resp = "HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
                            let _ = stream.write_all(resp.as_bytes());
                        } else {
                            // Second attempt: success
                            let model_output = json!({
                                "answer": "Retried answer [1].",
                                "cited_evidence_ids": ["[1]"],
                                "answer_basis": "retrieval",
                                "notices": [],
                                "warnings": []
                            }).to_string();
                            let chat_resp = json!({
                                "choices": [{
                                    "message": {
                                        "role": "assistant",
                                        "content": model_output
                                    },
                                    "finish_reason": "stop"
                                }]
                            }).to_string();
                            let resp = format!(
                                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                                chat_resp.len(), chat_resp
                            );
                            let _ = stream.write_all(resp.as_bytes());
                        }
                    }
                }
                Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    std::thread::sleep(Duration::from_millis(10));
                }
                Err(_) => break,
            }
        }
    });

    let config = generation::openrouter::OpenRouterGenerationConfig::new(
        "mock/retry-model",
        format!("http://{addr}/chat"),
        format!("http://{addr}/models"),
        Duration::from_secs(5),
        0.0,
        1.0,
        2048,
        8192,
    )
    .unwrap()
    .with_preflight_timeout(Duration::from_millis(2000));

    let generator = Arc::new(generation::openrouter::OpenRouterGenerator::new_with_config("test-key", config).unwrap());

    // 1. Explicitly prepare capabilities and verify cache
    generator.check_supported_parameters().await.expect("prepare succeeds");
    generator.check_supported_parameters().await.expect("cached prepare succeeds");
    assert_eq!(models_calls.load(Ordering::SeqCst), 1, "capabilities must be cached after 1 call");

    // 2. Run GenerateAnswer node
    let req = QueryRagRequest {
        query: "What is retry tracer query?".into(),
        session_id: "00000000-0000-4000-8000-000000000077".into(),
        filter: None,
    };
    let mut ctx = WorkflowContext::new(
        "00000000-0000-4000-8000-000000000077".into(),
        "trace-retry-test".into(),
        &req,
    );
    ctx.evidence_blocks = vec![crate::prompt::EvidenceBlock {
        id: "[1]".to_string(),
        chunk_id: "chk-retry-1".to_string(),
        document_id: "doc-retry-1".to_string(),
        chunk_index: 0,
        title: Some("Title".to_string()),
        section_path: Some("Section".to_string()),
        content_type: Some("text/plain".to_string()),
        provenance: "provenance".to_string(),
        text: "Evidence for retry tracer".to_string(),
        score: 0.95,
        rank: 1,
        suspicious: false,
    }];

    let generate_node = workflow::nodes::GenerateAnswerNode::new(Some(generator));
    let cancel = CancellationToken::new();

    generate_node.run(&mut ctx, &cancel).await.expect("retry succeeds on 2nd attempt");

    assert_eq!(chat_calls.load(Ordering::SeqCst), 2, "exactly two chat attempts");
    assert_eq!(ctx.answer.as_str(), "Retried answer [1].");

    server_handle.join().expect("server join");

    let requests = captured_chat_requests.lock().unwrap();
    assert_eq!(requests.len(), 2);
    let body1 = requests[0].split_once("\r\n\r\n").unwrap().1;
    let body2 = requests[1].split_once("\r\n\r\n").unwrap().1;
    assert_eq!(body1, body2, "GenerationRequest payloads must be byte-identical on retry");
}

#[tokio::test]
async fn workflow_phase5_openrouter_cancellation_propagates() {
    use std::io::Read;
    use std::net::TcpListener;
    use std::time::Duration;
    use crate::generation::Generator;

    let listener = TcpListener::bind("127.0.0.1:0").expect("bind local mock server");
    let addr = listener.local_addr().unwrap();

    let server_handle = std::thread::spawn(move || {
        if let Ok((mut stream, _)) = listener.accept() {
            let mut buf = [0u8; 4096];
            let _ = stream.read(&mut buf);
            // Stalls without replying
            std::thread::sleep(Duration::from_millis(500));
        }
    });

    let config = generation::openrouter::OpenRouterGenerationConfig::new(
        "mock/cancel-model",
        format!("http://{addr}/chat"),
        format!("http://{addr}/models"),
        Duration::from_secs(30),
        0.0,
        1.0,
        2048,
        8192,
    )
    .unwrap();

    let generator = Arc::new(generation::openrouter::OpenRouterGenerator::new_with_config("test-key", config).unwrap());

    let cancel = CancellationToken::new();
    let evidence = vec![crate::prompt::EvidenceBlock {
        id: "[1]".to_string(),
        chunk_id: "chk-cancel-1".to_string(),
        document_id: "doc-cancel-1".to_string(),
        chunk_index: 0,
        title: Some("Title".to_string()),
        section_path: Some("Section".to_string()),
        content_type: Some("text/plain".to_string()),
        provenance: "provenance".to_string(),
        text: "Evidence for cancellation test".to_string(),
        score: 0.95,
        rank: 1,
        suspicious: false,
    }];
    let mut req = generation::GenerationRequest::new("Question?", evidence);
    req.cancel = Some(cancel.clone());

    let cancel_trigger = cancel.clone();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(50)).await;
        cancel_trigger.cancel();
    });

    let result = generator.generate(req).await;
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert_eq!(err.kind, generation::GenerationErrorKind::Cancelled);

    server_handle.join().expect("server join");
}

#[tokio::test]
async fn workflow_phase5_generation_retry_exhausted() {
    use std::sync::atomic::{AtomicUsize, Ordering};

    let call_count = Arc::new(AtomicUsize::new(0));
    let call_count_gen = Arc::clone(&call_count);

    struct ExhaustedFakeGenerator {
        count: Arc<AtomicUsize>,
    }

    impl generation::Generator for ExhaustedFakeGenerator {
        fn generate<'a>(
            &'a self,
            _request: generation::GenerationRequest,
        ) -> generation::BoxFuture<'a, Result<ModelOutput, generation::GenerationError>> {
            Box::pin(async move {
                self.count.fetch_add(1, Ordering::SeqCst);
                Err(generation::GenerationError::new(
                    generation::GenerationErrorKind::ProviderError,
                    "Transient 503 Service Unavailable",
                ))
            })
        }
    }

    let generator: Arc<dyn generation::Generator> = Arc::new(ExhaustedFakeGenerator {
        count: call_count_gen,
    });

    let generate_node = workflow::nodes::GenerateAnswerNode::new(Some(generator));
    let req = QueryRagRequest {
        query: "Exhausted query?".into(),
        session_id: "00000000-0000-4000-8000-000000000088".into(),
        filter: None,
    };
    let mut ctx = WorkflowContext::new(
        "00000000-0000-4000-8000-000000000088".into(),
        "trace-exhausted".into(),
        &req,
    );
    let cancel = CancellationToken::new();

    let res = generate_node.run(&mut ctx, &cancel).await;
    assert!(res.is_err(), "must fail when retries are exhausted");
    let err = res.unwrap_err();
    assert_eq!(err.kind, v1::NodeErrorKind::LlmGenerationFailed);
    assert!(!err.retryable, "exhausted error must be non-retryable");
    assert_eq!(call_count.load(Ordering::SeqCst), 2, "must attempt exactly 2 times");
    assert!(ctx.answer.is_empty(), "no answer may be fabricated on failure");
}

#[tokio::test]
async fn workflow_phase5_nodekind_tracer() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use workflow::node::NodeKind;

    struct NineVariantReformulator;
    impl workflow::ports::QueryReformulator for NineVariantReformulator {
        fn reformulate<'a>(
            &'a self,
            _query: &'a str,
            _cancel: &'a CancellationToken,
        ) -> workflow::node::BoxFuture<'a, Result<Vec<String>, workflow::node::NodeError>> {
            Box::pin(async move {
                Ok((1..=9).map(|i| format!("variant {i}")).collect())
            })
        }
    }

    struct SpyEmbedder {
        calls: Arc<AtomicUsize>,
    }
    impl workflow::node::QueryEmbeddingPort for SpyEmbedder {
        fn embed_variant_zero<'a>(
            &'a self,
            _variant: &'a str,
            _cancel: &'a CancellationToken,
        ) -> workflow::node::BoxFuture<'a, Result<Vec<f32>, workflow::node::NodeError>> {
            Box::pin(async move {
                self.calls.fetch_add(1, Ordering::SeqCst);
                Ok(vec![0.0; 2048])
            })
        }
    }

    struct SpyGraphPort {
        calls: Arc<AtomicUsize>,
    }
    impl workflow::ports::GraphQueryPort for SpyGraphPort {
        fn query_graph<'a>(
            &'a self,
            _embedding: &'a [f32],
            _cancel: &'a CancellationToken,
        ) -> workflow::node::BoxFuture<'a, Result<Vec<crate::prompt::GraphFactBlock>, workflow::node::NodeError>> {
            Box::pin(async move {
                self.calls.fetch_add(1, Ordering::SeqCst);
                Ok(vec![])
            })
        }
    }

    let embed_calls = Arc::new(AtomicUsize::new(0));
    let graph_calls = Arc::new(AtomicUsize::new(0));

    let reformulate_node = workflow::nodes::ReformulateQueryNode::with_reformulator(Some(Arc::new(NineVariantReformulator)));
    assert_eq!(reformulate_node.kind(), NodeKind::ReformulateQuery);
    assert_eq!(reformulate_node.name(), "ReformulateQuery");

    let extract_node = workflow::nodes::ExtractGraphContextNode::new(
        Some(Arc::new(SpyEmbedder { calls: Arc::clone(&embed_calls) })),
        Some(Arc::new(SpyGraphPort { calls: Arc::clone(&graph_calls) })),
    );
    let retrieve_node = workflow::nodes::RetrieveHybridNode::default();
    let prompt_node = workflow::nodes::AssemblePromptNode::default();
    let generate_node = workflow::nodes::GenerateAnswerNode::default();

    let mut runner = workflow::WorkflowRunner::new();
    assert_eq!(runner.timeout_for_kind(NodeKind::ReformulateQuery).as_millis(), 5000);
    runner.add_node(reformulate_node);
    runner.add_node(extract_node);
    runner.add_node(retrieve_node);
    runner.add_node(prompt_node);
    runner.add_node(generate_node);

    let req = QueryRagRequest {
        query: "Nine variant admission rejection test".into(),
        session_id: "00000000-0000-4000-8000-000000000091".into(),
        filter: None,
    };
    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-tracer-test".into(),
        "00000000-0000-4000-8000-000000000091".into(),
    );
    let ctx = WorkflowContext::new("00000000-0000-4000-8000-000000000091".into(), "trace-tracer-test".into(), &req);

    runner.run_workflow(ctx, cancel, sink).await;

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    // 1. Exactly one NodeStarted for ReformulateQuery
    let started_nodes: Vec<String> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(v1::workflow_event::Event::NodeStarted(ns)) => Some(ns.node_name.clone()),
            _ => None,
        })
        .collect();
    assert_eq!(started_nodes, vec!["ReformulateQuery".to_string()]);

    // 2. Exactly one NodeFailed for ReformulateQuery with category InputValidation
    let failed_nodes: Vec<(String, i32, String, bool)> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(v1::workflow_event::Event::NodeFailed(nf)) => {
                Some((nf.node_name.clone(), nf.category, nf.message.clone(), nf.retryable))
            }
            _ => None,
        })
        .collect();
    assert_eq!(failed_nodes.len(), 1);
    let (failed_name, category, error_msg, retryable) = &failed_nodes[0];
    assert_eq!(failed_name, "ReformulateQuery");
    assert_eq!(*category, v1::NodeErrorKind::InputValidation as i32);
    assert!(error_msg.contains("exceeding maximum allowed limit of 8"));
    assert!(!retryable);

    // 3. No NodeCompleted for ReformulateQuery
    let completed_nodes: Vec<String> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(v1::workflow_event::Event::NodeCompleted(nc)) => Some(nc.node_name.clone()),
            _ => None,
        })
        .collect();
    assert!(completed_nodes.is_empty(), "No NodeCompleted should be emitted for rejected node");

    // 4. No checkpoint for post_reformulatequery
    let checkpoints: Vec<String> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(v1::workflow_event::Event::Checkpoint(cp)) => Some(cp.checkpoint_type.clone()),
            _ => None,
        })
        .collect();
    assert!(checkpoints.is_empty(), "No checkpoint should be emitted on early admission failure");

    // 5. Zero downstream port calls
    assert_eq!(embed_calls.load(Ordering::SeqCst), 0, "No embedding calls on reformulate rejection");
    assert_eq!(graph_calls.load(Ordering::SeqCst), 0, "No graph calls on reformulate rejection");

    // 6. Terminal WorkflowCompleted with success = false
    let terminal = events
        .iter()
        .find_map(|e| match &e.event {
            Some(v1::workflow_event::Event::WorkflowCompleted(wc)) => Some(wc),
            _ => None,
        })
        .expect("Terminal WorkflowCompleted must be emitted");
    assert!(!terminal.success);
    assert_eq!(terminal.error_kind, v1::NodeErrorKind::InputValidation as i32);
}

#[tokio::test]
async fn workflow_phase5_nodekind_dispatch() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use workflow::node::NodeKind;

    let reformulate = workflow::nodes::ReformulateQueryNode::new();
    let graph_context = workflow::nodes::ExtractGraphContextNode::new(None, None);
    let retrieve = workflow::nodes::RetrieveHybridNode::default();

    assert_eq!(reformulate.kind(), NodeKind::ReformulateQuery);
    assert_eq!(graph_context.kind(), NodeKind::ExtractGraphContext);
    assert_eq!(retrieve.kind(), NodeKind::RetrieveHybrid);

    assert_eq!(reformulate.name(), "ReformulateQuery");
    assert_eq!(graph_context.name(), "ExtractGraphContext");
    assert_eq!(retrieve.name(), "RetrieveHybrid");

    let runner = workflow::WorkflowRunner::new();
    assert_eq!(runner.timeout_for_kind(NodeKind::ReformulateQuery).as_millis(), 5000);
    assert_eq!(runner.timeout_for_kind(NodeKind::ExtractGraphContext).as_millis(), 15000);
    assert_eq!(runner.timeout_for_kind(NodeKind::RetrieveHybrid).as_millis(), 10000);

    assert_eq!(NodeKind::ReformulateQuery.checkpoint_label(), "post_reformulatequery");
    assert_eq!(NodeKind::ExtractGraphContext.checkpoint_label(), "post_extractgraphcontext");
    assert_eq!(NodeKind::RetrieveHybrid.checkpoint_label(), "post_retrievehybrid");

    // Verify D-08 variant-zero embedding and D-07 all-variant retrieval
    struct MockEmbedder {
        embedded_variants: Arc<std::sync::Mutex<Vec<String>>>,
    }
    impl workflow::node::QueryEmbeddingPort for MockEmbedder {
        fn embed_variant_zero<'a>(
            &'a self,
            variant: &'a str,
            _cancel: &'a CancellationToken,
        ) -> workflow::node::BoxFuture<'a, Result<Vec<f32>, workflow::node::NodeError>> {
            let v = variant.to_string();
            Box::pin(async move {
                self.embedded_variants.lock().unwrap().push(v);
                Ok(vec![0.1; 2048])
            })
        }
    }

    struct MockBm25Port {
        retrieved_variants: Arc<std::sync::Mutex<Vec<String>>>,
    }
    impl workflow::ports::Bm25RetrievalPort for MockBm25Port {
        fn retrieve_bm25<'a>(
            &'a self,
            query: &'a str,
            _filter: Option<&'a v1::DocumentFilter>,
            _cancel: &'a CancellationToken,
        ) -> workflow::node::BoxFuture<'a, Result<Vec<crate::retrieval::Candidate>, workflow::node::NodeError>> {
            let q = query.to_string();
            Box::pin(async move {
                self.retrieved_variants.lock().unwrap().push(q);
                Ok(vec![])
            })
        }
    }

    let embedded = Arc::new(std::sync::Mutex::new(Vec::new()));
    let retrieved = Arc::new(std::sync::Mutex::new(Vec::new()));

    let mut ctx = WorkflowContext::new(
        "00000000-0000-4000-8000-000000000092".into(),
        "trace-dispatch".into(),
        &QueryRagRequest {
            query: "Multi variant query".into(),
            session_id: "00000000-0000-4000-8000-000000000092".into(),
            filter: None,
        },
    );
    ctx.variants = vec!["variant_0".into(), "variant_1".into(), "variant_2".into()];

    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-dispatch".into(),
        "00000000-0000-4000-8000-000000000092".into(),
    );

    let graph_node = workflow::nodes::ExtractGraphContextNode::new(
        Some(Arc::new(MockEmbedder { embedded_variants: Arc::clone(&embedded) })),
        None,
    );
    runner.run_node(&graph_node, &mut ctx, &cancel, &sink).await.unwrap();

    // D-08: Only variant zero embedded
    assert_eq!(*embedded.lock().unwrap(), vec!["variant_0".to_string()]);

    let retrieve_node = workflow::nodes::RetrieveHybridNode::new(
        None,
        Some(Arc::new(MockBm25Port { retrieved_variants: Arc::clone(&retrieved) })),
        None,
        Default::default(),
    );
    runner.run_node(&retrieve_node, &mut ctx, &cancel, &sink).await.unwrap();

    // D-07: All variants retrieved
    assert_eq!(*retrieved.lock().unwrap(), vec!["variant_0".to_string(), "variant_1".to_string(), "variant_2".to_string()]);

    // Check typed retryability forwarding without extra retrying event (D-15)
    struct FailingDensePort;
    impl workflow::ports::DenseRetrievalPort for FailingDensePort {
        fn retrieve_dense<'a>(
            &'a self,
            _embedding: &'a [f32],
            _filter: Option<&'a v1::DocumentFilter>,
            _cancel: &'a CancellationToken,
        ) -> workflow::node::BoxFuture<'a, Result<Vec<crate::retrieval::Candidate>, workflow::node::NodeError>> {
            Box::pin(async move {
                Err(workflow::node::NodeError::new(v1::NodeErrorKind::RetrievalFailed, "Transient DB connection drop")
                    .with_retryable(true))
            })
        }
    }

    let failing_retrieve_node = workflow::nodes::RetrieveHybridNode::new(
        Some(Arc::new(FailingDensePort)),
        None,
        None,
        Default::default(),
    );
    let fail_res = runner.run_node(&failing_retrieve_node, &mut ctx, &cancel, &sink).await;
    assert!(fail_res.is_err());
    let err = fail_res.unwrap_err();
    assert!(err.retryable);

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let failed_retrieve = events.iter().find_map(|e| match &e.event {
        Some(v1::workflow_event::Event::NodeFailed(nf)) if nf.node_name == "RetrieveHybrid" => Some(nf),
        _ => None,
    }).expect("NodeFailed event for RetrieveHybrid must exist");
    assert!(failed_retrieve.retryable, "NodeFailed.retryable must be true when forwarded from NodeError");
}

#[tokio::test]
async fn workflow_phase5_nodekind_exhaustive() {
    use workflow::node::NodeKind;

    // 1. Closed enum of exactly 5 variants
    assert_eq!(NodeKind::ALL.len(), 5);
    assert_eq!(
        NodeKind::ALL,
        [
            NodeKind::ReformulateQuery,
            NodeKind::ExtractGraphContext,
            NodeKind::RetrieveHybrid,
            NodeKind::AssemblePrompt,
            NodeKind::GenerateAnswer,
        ]
    );

    // 2. All 5 production nodes implement Node::kind returning matching variant
    let n1 = workflow::nodes::ReformulateQueryNode::new();
    let n2 = workflow::nodes::ExtractGraphContextNode::new(None, None);
    let n3 = workflow::nodes::RetrieveHybridNode::default();
    let n4 = workflow::nodes::AssemblePromptNode::new();
    let n5 = workflow::nodes::GenerateAnswerNode::new(None);

    assert_eq!(n1.kind(), NodeKind::ReformulateQuery);
    assert_eq!(n2.kind(), NodeKind::ExtractGraphContext);
    assert_eq!(n3.kind(), NodeKind::RetrieveHybrid);
    assert_eq!(n4.kind(), NodeKind::AssemblePrompt);
    assert_eq!(n5.kind(), NodeKind::GenerateAnswer);

    // 3. Exhaustive runner timeouts and checkpoint labels
    let runner = workflow::WorkflowRunner::new();
    for kind in NodeKind::ALL {
        let name = kind.name();
        let timeout = runner.timeout_for_kind(kind);
        let cp_label = kind.checkpoint_label();

        match kind {
            NodeKind::ReformulateQuery => {
                assert_eq!(name, "ReformulateQuery");
                assert_eq!(timeout.as_millis(), 5000);
                assert_eq!(cp_label, "post_reformulatequery");
            }
            NodeKind::ExtractGraphContext => {
                assert_eq!(name, "ExtractGraphContext");
                assert_eq!(timeout.as_millis(), 15000);
                assert_eq!(cp_label, "post_extractgraphcontext");
            }
            NodeKind::RetrieveHybrid => {
                assert_eq!(name, "RetrieveHybrid");
                assert_eq!(timeout.as_millis(), 10000);
                assert_eq!(cp_label, "post_retrievehybrid");
            }
            NodeKind::AssemblePrompt => {
                assert_eq!(name, "AssemblePrompt");
                assert_eq!(timeout.as_millis(), 2000);
                assert_eq!(cp_label, "post_assembleprompt");
            }
            NodeKind::GenerateAnswer => {
                assert_eq!(name, "GenerateAnswer");
                assert_eq!(timeout.as_millis(), 65000);
                assert_eq!(cp_label, "post_generateanswer");
            }
        }
    }

    // 4. Exhaustive D-03 zero-evidence skip in full workflow
    let mut zero_ev_runner = workflow::WorkflowRunner::new();
    zero_ev_runner.add_node(workflow::nodes::ReformulateQueryNode::new());
    zero_ev_runner.add_node(workflow::nodes::ExtractGraphContextNode::new(None, None));
    zero_ev_runner.add_node(workflow::nodes::RetrieveHybridNode::default());
    zero_ev_runner.add_node(workflow::nodes::AssemblePromptNode::new());
    zero_ev_runner.add_node(workflow::nodes::GenerateAnswerNode::new(None));

    let req = QueryRagRequest {
        query: "Zero evidence exhaustive query".into(),
        session_id: "00000000-0000-4000-8000-000000000093".into(),
        filter: None,
    };
    let (tx, mut rx) = mpsc::channel(100);
    let cancel = CancellationToken::new();
    let sink = WorkflowEventSink::new(
        tx,
        Arc::new(EventSequence::new()),
        "trace-exhaustive".into(),
        "00000000-0000-4000-8000-000000000093".into(),
    );
    let ctx = WorkflowContext::new("00000000-0000-4000-8000-000000000093".into(), "trace-exhaustive".into(), &req);

    zero_ev_runner.run_workflow(ctx, cancel, sink).await;

    let mut events = Vec::new();
    while let Ok(item) = rx.try_recv() {
        if let Ok(wf_event) = item {
            events.push(wf_event);
        }
    }

    let started_nodes: Vec<String> = events
        .iter()
        .filter_map(|e| match &e.event {
            Some(v1::workflow_event::Event::NodeStarted(ns)) => Some(ns.node_name.clone()),
            _ => None,
        })
        .collect();

    assert_eq!(
        started_nodes,
        vec!["ReformulateQuery", "ExtractGraphContext", "RetrieveHybrid"]
    );
    assert!(!started_nodes.contains(&"AssemblePrompt".to_string()));
    assert!(!started_nodes.contains(&"GenerateAnswer".to_string()));

    let terminal = events
        .iter()
        .find_map(|e| match &e.event {
            Some(v1::workflow_event::Event::WorkflowCompleted(wc)) => Some(wc),
            _ => None,
        })
        .expect("Terminal WorkflowCompleted must be emitted");
    assert!(terminal.success);
}

