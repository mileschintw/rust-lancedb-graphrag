//! Telemetry metrics test module.
//!
//! Tests the 10 D-35 operational metric instruments and their failure invariants (06.2-05-PLAN.md).

use std::collections::HashSet;
use opentelemetry_sdk::metrics::{InMemoryMetricExporter, PeriodicReader, SdkMeterProvider};

use crate::telemetry::metrics::*;

pub static METRIC_TEST_MUTEX: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

fn setup_test_meter() -> (InMemoryMetricExporter, SdkMeterProvider) {
    let exporter = InMemoryMetricExporter::default();
    let reader = PeriodicReader::builder(exporter.clone()).build();
    let meter_provider = SdkMeterProvider::builder()
        .with_reader(reader)
        .build();
    opentelemetry::global::set_meter_provider(meter_provider.clone());
    (exporter, meter_provider)
}

#[tokio::test]
async fn telemetry_metrics_registry_defines_exactly_ten_instruments() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();

    // Exercise all 10 instruments
    record_query_duration_ms(OUTCOME_COMPLETED, 120);
    record_retrieval_path_failure(PATH_DENSE, KIND_TIMEOUT);
    record_answer_degraded(BASIS_MIXED);
    record_citation_repair(ACTION_REPAIRED);
    record_generation_retry(RETRY_RECOVERED);
    record_evidence_set_size(5);
    record_ingest_document(INGEST_COMPLETED);
    record_ingest_chunks(12);
    record_index_rebuild_duration_ms(REBUILD_COMPLETED, 450);
    record_corpus_generation(1);

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();

    let mut metric_names = HashSet::new();
    for rm in &finished {
        for sm in rm.scope_metrics() {
            for m in sm.metrics() {
                metric_names.insert(m.name().to_string());
            }
        }
    }

    let expected_ten: HashSet<String> = [
        "lancet.rag.query.duration",
        "lancet.rag.retrieval.path_failures",
        "lancet.rag.answer.degraded",
        "lancet.rag.citation.repairs",
        "lancet.rag.generation.retries",
        "lancet.rag.evidence.set_size",
        "lancet.ingest.documents",
        "lancet.ingest.chunks",
        "lancet.index.rebuild.duration",
        "lancet.index.corpus_generation",
    ]
    .iter()
    .map(|s| s.to_string())
    .collect();

    assert_eq!(metric_names, expected_ten);
}

#[tokio::test]
async fn telemetry_metrics_attributes_are_bounded() {
    let _lock = METRIC_TEST_MUTEX.lock().await;

    // Verify all bounded dimension constants
    let query_outcomes = [OUTCOME_COMPLETED, OUTCOME_FAILED];
    assert_eq!(query_outcomes, ["completed", "failed"]);

    let paths = [PATH_DENSE, PATH_BM25, PATH_GRAPH];
    assert_eq!(paths, ["dense", "bm25", "graph"]);

    let failure_kinds = [KIND_TIMEOUT, KIND_ERROR, KIND_UNAVAILABLE];
    assert_eq!(failure_kinds, ["timeout", "error", "unavailable"]);

    let answer_bases = [BASIS_RETRIEVAL, BASIS_MIXED, BASIS_MODEL_ONLY];
    assert_eq!(answer_bases, ["retrieval", "mixed", "model_only"]);

    let citation_actions = [ACTION_REPAIRED, ACTION_DROPPED];
    assert_eq!(citation_actions, ["repaired", "dropped"]);

    let retry_outcomes = [RETRY_RECOVERED, RETRY_EXHAUSTED];
    assert_eq!(retry_outcomes, ["recovered", "exhausted"]);

    let ingest_outcomes = [INGEST_COMPLETED, INGEST_FAILED];
    assert_eq!(ingest_outcomes, ["completed", "failed"]);

    let rebuild_outcomes = [REBUILD_COMPLETED, REBUILD_FAILED];
    assert_eq!(rebuild_outcomes, ["completed", "failed"]);
}

#[tokio::test]
async fn telemetry_metrics_corpus_generation_gauge_is_numeric() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();

    record_corpus_generation(42);

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();

    let mut found_gauge = false;
    for rm in &finished {
        for sm in rm.scope_metrics() {
            for m in sm.metrics() {
                if m.name() == "lancet.index.corpus_generation" {
                    found_gauge = true;
                    if let opentelemetry_sdk::metrics::data::AggregatedMetrics::U64(
                        opentelemetry_sdk::metrics::data::MetricData::Gauge(gauge),
                    ) = m.data()
                    {
                        let data_points: Vec<_> = gauge.data_points().collect();
                        assert_eq!(data_points.len(), 1);
                        assert_eq!(data_points[0].value(), 42);
                        assert_eq!(data_points[0].attributes().count(), 0);
                    } else {
                        panic!("expected U64 Gauge metric aggregation, got {:?}", m.data());
                    }
                }
            }
        }
    }
    assert!(found_gauge, "lancet.index.corpus_generation gauge must be recorded");
}

#[tokio::test]
async fn telemetry_metrics_query_duration_outcome_set_is_exactly_two() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let outcomes = [OUTCOME_COMPLETED, OUTCOME_FAILED];
    assert_eq!(outcomes.len(), 2);
    assert_eq!(OUTCOME_COMPLETED, "completed");
    assert_eq!(OUTCOME_FAILED, "failed");
}

#[tokio::test]
async fn telemetry_metrics_no_instrument_carries_an_identifier_attribute() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();

    // Record data on all 10 instruments with standard bounded values
    record_query_duration_ms(OUTCOME_COMPLETED, 100);
    record_retrieval_path_failure(PATH_DENSE, KIND_TIMEOUT);
    record_answer_degraded(BASIS_MODEL_ONLY);
    record_citation_repair(ACTION_DROPPED);
    record_generation_retry(RETRY_EXHAUSTED);
    record_evidence_set_size(3);
    record_ingest_document(INGEST_FAILED);
    record_ingest_chunks(10);
    record_index_rebuild_duration_ms(REBUILD_FAILED, 500);
    record_corpus_generation(99);

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();

    let forbidden_keys = [
        "session_id",
        "session",
        "doc_id",
        "document_id",
        "trace_id",
        "span_id",
        "query",
        "prompt",
        "text",
        "message",
        "model",
        "filename",
    ];

    for rm in &finished {
        for sm in rm.scope_metrics() {
            for m in sm.metrics() {
                use opentelemetry_sdk::metrics::data::{AggregatedMetrics, MetricData};
                match m.data() {
                    AggregatedMetrics::U64(MetricData::Sum(sum)) => {
                        for dp in sum.data_points() {
                            for kv in dp.attributes() {
                                let key_str = kv.key.as_str().to_lowercase();
                                for forbidden in &forbidden_keys {
                                    assert!(!key_str.contains(forbidden), "forbidden key in attribute: {}", key_str);
                                }
                            }
                        }
                    }
                    AggregatedMetrics::U64(MetricData::Histogram(hist)) => {
                        for dp in hist.data_points() {
                            for kv in dp.attributes() {
                                let key_str = kv.key.as_str().to_lowercase();
                                for forbidden in &forbidden_keys {
                                    assert!(!key_str.contains(forbidden), "forbidden key in attribute: {}", key_str);
                                }
                            }
                        }
                    }
                    AggregatedMetrics::U64(MetricData::Gauge(gauge)) => {
                        for dp in gauge.data_points() {
                            for kv in dp.attributes() {
                                let key_str = kv.key.as_str().to_lowercase();
                                for forbidden in &forbidden_keys {
                                    assert!(!key_str.contains(forbidden), "forbidden key in attribute: {}", key_str);
                                }
                            }
                        }
                    }
                    _ => {}
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Task 2: Query-Path Metric Recording Tests
// ---------------------------------------------------------------------------

use std::sync::Arc;
use crate::generation::GroundingLimits;
use crate::retrieval::{Candidate, RetrievalSettings};
use crate::workflow::node::Node;
use crate::workflow::nodes::{AssemblePromptNode, ExtractGraphContextNode, GenerateAnswerNode, RetrieveHybridNode};
use crate::workflow::runner::{WorkflowEventSink, WorkflowRunner};
use crate::workflow::{EventSequence, WorkflowContext};

fn make_candidate(doc_id: &str, chunk_id: &str) -> Candidate {
    Candidate {
        document_id: doc_id.into(),
        chunk_id: chunk_id.into(),
        chunk_index: 0,
        char_start: 0,
        char_end: 10,
        content: "test content".into(),
        title: Some("title".into()),
        section_path: Some("root".into()),
        content_type: Some("text/plain".into()),
        embedding_model: None,
        ingested_at: None,
        score: 0.9,
    }
}

fn evidence_block_with_id(id: &str) -> crate::prompt::EvidenceBlock {
    crate::prompt::EvidenceBlock {
        id: id.into(),
        chunk_id: format!("chunk-{id}"),
        document_id: "doc-1".into(),
        chunk_index: 0,
        title: Some("title".into()),
        section_path: Some("Root".into()),
        content_type: Some("text/plain".into()),
        provenance: "test".into(),
        text: "Evidence text.".into(),
        score: 0.9,
        rank: 1,
        suspicious: false,
    }
}

fn find_sum_datapoints(
    finished: &[opentelemetry_sdk::metrics::data::ResourceMetrics],
    name: &str,
) -> Vec<(u64, Vec<(String, String)>)> {
    let mut dps = Vec::new();
    for rm in finished {
        for sm in rm.scope_metrics() {
            for m in sm.metrics() {
                if m.name() == name {
                    if let opentelemetry_sdk::metrics::data::AggregatedMetrics::U64(
                        opentelemetry_sdk::metrics::data::MetricData::Sum(sum),
                    ) = m.data()
                    {
                        for dp in sum.data_points() {
                            let attrs: Vec<(String, String)> = dp
                                .attributes()
                                .map(|kv| (kv.key.as_str().to_string(), kv.value.to_string()))
                                .collect();
                            dps.push((dp.value(), attrs));
                        }
                    }
                }
            }
        }
    }
    dps
}

fn find_hist_total_count(
    finished: &[opentelemetry_sdk::metrics::data::ResourceMetrics],
    name: &str,
) -> u64 {
    let mut count = 0;
    for rm in finished {
        for sm in rm.scope_metrics() {
            for m in sm.metrics() {
                if m.name() == name {
                    if let opentelemetry_sdk::metrics::data::AggregatedMetrics::U64(
                        opentelemetry_sdk::metrics::data::MetricData::Histogram(hist),
                    ) = m.data()
                    {
                        for dp in hist.data_points() {
                            count += dp.count();
                        }
                    }
                }
            }
        }
    }
    count
}

#[tokio::test]
async fn metrics_dense_degrade_increments_path_failure() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();

    let candidate = make_candidate("doc-1", "chunk-1");
    let node = RetrieveHybridNode::new(
        Some(Arc::new(crate::workflow::ports::FakeDenseRetrievalPort::failure(
            crate::workflow::NodeError::new(crate::pb::lancet::v1::NodeErrorKind::Timeout, "timeout"),
        ))),
        Some(Arc::new(crate::workflow::ports::FakeBm25RetrievalPort::success(vec![candidate]))),
        None,
        RetrievalSettings::default(),
    );

    let mut ctx = WorkflowContext::new(
        "s1".into(),
        "t1".into(),
        &crate::pb::lancet::v1::QueryRagRequest {
            query: "test".into(),
            ..Default::default()
        },
    );
    ctx.query_embedding = Some(vec![0.1; 128]);
    ctx.variants = vec!["test".into()];
    let cancel = tokio_util::sync::CancellationToken::new();

    let res = node.run(&mut ctx, &cancel).await;
    assert!(res.is_ok());
    assert!(ctx.notices.iter().any(|n| n.typed_code == crate::pb::lancet::v1::NoticeCode::RetrievalDegradedDense as i32));

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();
    let dps = find_sum_datapoints(&finished, "lancet.rag.retrieval.path_failures");
    assert_eq!(dps.len(), 1);
    assert_eq!(dps[0].0, 1);
    assert!(dps[0].1.contains(&("path".into(), "dense".into())));
    assert!(dps[0].1.contains(&("kind".into(), "timeout".into())));
}

#[tokio::test]
async fn metrics_bm25_degrade_increments_path_failure() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();

    let candidate = make_candidate("doc-1", "chunk-1");
    let node = RetrieveHybridNode::new(
        Some(Arc::new(crate::workflow::ports::FakeDenseRetrievalPort::success(vec![candidate]))),
        Some(Arc::new(crate::workflow::ports::FakeBm25RetrievalPort::failure(
            crate::workflow::NodeError::new(crate::pb::lancet::v1::NodeErrorKind::RetrievalFailed, "unavailable"),
        ))),
        None,
        RetrievalSettings::default(),
    );

    let mut ctx = WorkflowContext::new(
        "s1".into(),
        "t1".into(),
        &crate::pb::lancet::v1::QueryRagRequest {
            query: "test".into(),
            ..Default::default()
        },
    );
    ctx.query_embedding = Some(vec![0.1; 128]);
    ctx.variants = vec!["test".into()];
    let cancel = tokio_util::sync::CancellationToken::new();

    let res = node.run(&mut ctx, &cancel).await;
    assert!(res.is_ok());
    assert!(ctx.notices.iter().any(|n| n.typed_code == crate::pb::lancet::v1::NoticeCode::RetrievalDegradedBm25 as i32));

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();
    let dps = find_sum_datapoints(&finished, "lancet.rag.retrieval.path_failures");
    assert_eq!(dps.len(), 1);
    assert_eq!(dps[0].0, 1);
    assert!(dps[0].1.contains(&("path".into(), "bm25".into())));
    assert!(dps[0].1.contains(&("kind".into(), "unavailable".into())));
}

#[tokio::test]
async fn metrics_graph_timeout_and_unavailable_increment_distinct_kinds() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();
    let cancel = tokio_util::sync::CancellationToken::new();

    // 1. Timeout
    let node_timeout = ExtractGraphContextNode::new(None, Some(Arc::new(crate::workflow::ports::FakeGraphQueryPort::stall())));
    let mut ctx1 = WorkflowContext::new("s1".into(), "t1".into(), &crate::pb::lancet::v1::QueryRagRequest {
        query: "test".into(),
        ..Default::default()
    });
    ctx1.query_embedding = Some(vec![0.1; 128]);
    let _ = node_timeout.run(&mut ctx1, &cancel).await;

    // 2. Unavailable
    let node_unavail = ExtractGraphContextNode::new(None, None);
    let mut ctx2 = WorkflowContext::new("s2".into(), "t2".into(), &crate::pb::lancet::v1::QueryRagRequest {
        query: "test".into(),
        ..Default::default()
    });
    ctx2.query_embedding = Some(vec![0.1; 128]);
    let _ = node_unavail.run(&mut ctx2, &cancel).await;

    // 3. Operator ablation (disable_graph_context = true) -> must record NOTHING
    let node_ablation = ExtractGraphContextNode::new(
        None,
        Some(Arc::new(crate::workflow::ports::FakeGraphQueryPort::success(
            Vec::<crate::prompt::GraphFactBlock>::new(),
        ))),
    );
    let mut ctx3 = WorkflowContext::new("s3".into(), "t3".into(), &crate::pb::lancet::v1::QueryRagRequest {
        query: "test".into(),
        disable_graph_context: Some(true),
        ..Default::default()
    });
    ctx3.disable_graph_context = true;
    let _ = node_ablation.run(&mut ctx3, &cancel).await;

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();
    let dps = find_sum_datapoints(&finished, "lancet.rag.retrieval.path_failures");
    assert_eq!(dps.len(), 2, "exactly two failures recorded for graph, none for ablation");
    assert!(dps.iter().any(|(val, attrs)| *val == 1 && attrs.contains(&("path".into(), "graph".into())) && attrs.contains(&("kind".into(), "timeout".into()))));
    assert!(dps.iter().any(|(val, attrs)| *val == 1 && attrs.contains(&("path".into(), "graph".into())) && attrs.contains(&("kind".into(), "unavailable".into()))));
}

#[tokio::test]
async fn metrics_degraded_answer_counted_by_basis() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();
    let cancel = tokio_util::sync::CancellationToken::new();

    // 1. ModelOnly
    let (tx, _rx) = tokio::sync::mpsc::channel(16);
    let seq1 = Arc::new(EventSequence::new());
    let sink1 = WorkflowEventSink::new(tx, seq1, "t1".into(), "s1".into());
    let mut ctx1 = WorkflowContext::new("s1".into(), "t1".into(), &crate::pb::lancet::v1::QueryRagRequest::default());
    ctx1.answer_basis = crate::pb::lancet::v1::AnswerBasis::ModelOnly;
    WorkflowRunner::emit_terminal_once(&ctx1, &sink1, &cancel, 50, None).await;

    // 2. Mixed
    let (tx, _rx) = tokio::sync::mpsc::channel(16);
    let seq2 = Arc::new(EventSequence::new());
    let sink2 = WorkflowEventSink::new(tx, seq2, "t2".into(), "s2".into());
    let mut ctx2 = WorkflowContext::new("s2".into(), "t2".into(), &crate::pb::lancet::v1::QueryRagRequest::default());
    ctx2.answer_basis = crate::pb::lancet::v1::AnswerBasis::Mixed;
    WorkflowRunner::emit_terminal_once(&ctx2, &sink2, &cancel, 50, None).await;

    // 3. Retrieval -> not recorded
    let (tx, _rx) = tokio::sync::mpsc::channel(16);
    let seq3 = Arc::new(EventSequence::new());
    let sink3 = WorkflowEventSink::new(tx, seq3, "t3".into(), "s3".into());
    let mut ctx3 = WorkflowContext::new("s3".into(), "t3".into(), &crate::pb::lancet::v1::QueryRagRequest::default());
    ctx3.answer_basis = crate::pb::lancet::v1::AnswerBasis::Retrieval;
    WorkflowRunner::emit_terminal_once(&ctx3, &sink3, &cancel, 50, None).await;

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();
    let dps = find_sum_datapoints(&finished, "lancet.rag.answer.degraded");
    assert_eq!(dps.len(), 2);
    assert!(dps.iter().any(|(val, attrs)| *val == 1 && attrs.contains(&("answer_basis".into(), "model_only".into()))));
    assert!(dps.iter().any(|(val, attrs)| *val == 1 && attrs.contains(&("answer_basis".into(), "mixed".into()))));
    assert!(!dps.iter().any(|(_, attrs)| attrs.contains(&("answer_basis".into(), "retrieval".into()))));
}

#[tokio::test]
async fn metrics_citation_repair_and_drop_counted_separately() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();
    let cancel = tokio_util::sync::CancellationToken::new();

    let output = crate::generation::ModelOutput {
        answer: "Statement [ 1 ] and other [ 99 ]".into(),
        cited_evidence_ids: vec![],
        answer_basis: crate::generation::AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        usage: None,
    };
    let gen = Arc::new(crate::generation::FakeGenerator::new(Ok(output)));
    let limits = GroundingLimits::default_limits();
    let node = GenerateAnswerNode::new(Some(gen))
        .with_settings(limits, 200, 1.0)
        .with_citation_repair_enabled(true);

    let mut ctx = WorkflowContext::new("s1".into(), "t1".into(), &crate::pb::lancet::v1::QueryRagRequest::default());
    ctx.original_query = "query".into();
    ctx.evidence_blocks = vec![evidence_block_with_id("[1]")];

    let res = node.run(&mut ctx, &cancel).await;
    assert!(res.is_ok());

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();
    let dps = find_sum_datapoints(&finished, "lancet.rag.citation.repairs");
    assert_eq!(dps.len(), 2);
    assert!(dps.iter().any(|(val, attrs)| *val == 1 && attrs.contains(&("action".into(), "repaired".into()))));
    assert!(dps.iter().any(|(val, attrs)| *val == 1 && attrs.contains(&("action".into(), "dropped".into()))));
}

#[tokio::test]
async fn metrics_generation_retry_recorded_with_outcome() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();
    let cancel = tokio_util::sync::CancellationToken::new();

    // 1. Recovered retry (attempt 1 timeout, attempt 2 ok)
    let ok_output = crate::generation::ModelOutput {
        answer: "Grounded answer [1]".into(),
        cited_evidence_ids: vec!["1".into()],
        answer_basis: crate::generation::AnswerBasis::Retrieval,
        notices: vec![],
        warnings: vec![],
        usage: None,
    };
    let gen1 = Arc::new(crate::generation::FakeGenerator::with_responses(vec![
        Err(crate::generation::GenerationError::new(crate::generation::GenerationErrorKind::Timeout, "timeout")),
        Ok(ok_output.clone()),
    ]));
    let node1 = GenerateAnswerNode::new(Some(gen1));
    let mut ctx1 = WorkflowContext::new("s1".into(), "t1".into(), &crate::pb::lancet::v1::QueryRagRequest::default());
    ctx1.original_query = "query".into();
    ctx1.evidence_blocks = vec![evidence_block_with_id("1")];
    let res1 = node1.run(&mut ctx1, &cancel).await;
    assert!(res1.is_ok());

    // 2. Exhausted retry (attempt 1 timeout, attempt 2 timeout)
    let gen2 = Arc::new(crate::generation::FakeGenerator::with_responses(vec![
        Err(crate::generation::GenerationError::new(crate::generation::GenerationErrorKind::Timeout, "timeout 1")),
        Err(crate::generation::GenerationError::new(crate::generation::GenerationErrorKind::Timeout, "timeout 2")),
    ]));
    let node2 = GenerateAnswerNode::new(Some(gen2));
    let mut ctx2 = WorkflowContext::new("s2".into(), "t2".into(), &crate::pb::lancet::v1::QueryRagRequest::default());
    ctx2.original_query = "query".into();
    ctx2.evidence_blocks = vec![evidence_block_with_id("1")];
    let res2 = node2.run(&mut ctx2, &cancel).await;
    assert!(res2.is_err());

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();
    let dps = find_sum_datapoints(&finished, "lancet.rag.generation.retries");
    assert_eq!(dps.len(), 2);
    assert!(dps.iter().any(|(val, attrs)| *val == 1 && attrs.contains(&("outcome".into(), "recovered".into()))));
    assert!(dps.iter().any(|(val, attrs)| *val == 1 && attrs.contains(&("outcome".into(), "exhausted".into()))));
}

#[tokio::test]
async fn metrics_evidence_set_size_recorded_after_packing() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();
    let cancel = tokio_util::sync::CancellationToken::new();

    let node = AssemblePromptNode::new();

    // 1. Empty evidence with allow_model_only=true -> records 0
    let mut ctx1 = WorkflowContext::new("s1".into(), "t1".into(), &crate::pb::lancet::v1::QueryRagRequest {
        query: "test".into(),
        allow_model_only: Some(true),
        ..Default::default()
    });
    ctx1.allow_model_only = true;
    let res1 = node.run(&mut ctx1, &cancel).await;
    assert!(res1.is_ok());

    // 2. Packed evidence with 2 blocks -> records 2
    let mut ctx2 = WorkflowContext::new("s2".into(), "t2".into(), &crate::pb::lancet::v1::QueryRagRequest {
        query: "test".into(),
        ..Default::default()
    });
    ctx2.original_query = "test".into();
    ctx2.evidence_blocks = vec![
        evidence_block_with_id("d1"),
        evidence_block_with_id("d2"),
    ];
    let res2 = node.run(&mut ctx2, &cancel).await;
    assert!(res2.is_ok());

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();
    let hist_count = find_hist_total_count(&finished, "lancet.rag.evidence.set_size");
    assert_eq!(hist_count, 2);
}

#[tokio::test]
async fn metrics_query_duration_outcome_stays_two_valued() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();
    let cancel = tokio_util::sync::CancellationToken::new();

    let (tx, _rx) = tokio::sync::mpsc::channel(16);
    let seq = Arc::new(EventSequence::new());
    let sink = WorkflowEventSink::new(tx, seq, "t1".into(), "s1".into());
    let mut ctx = WorkflowContext::new("s1".into(), "t1".into(), &crate::pb::lancet::v1::QueryRagRequest::default());
    ctx.answer_basis = crate::pb::lancet::v1::AnswerBasis::Retrieval;
    // Add degrade notice
    ctx.add_notice(crate::workflow::notice(
        crate::pb::lancet::v1::NoticeCode::RetrievalDegradedDense,
        "dense degraded",
        crate::pb::lancet::v1::NoticeSeverity::Info,
    ));

    WorkflowRunner::emit_terminal_once(&ctx, &sink, &cancel, 80, None).await;

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();

    let dps_duration = find_hist_total_count(&finished, "lancet.rag.query.duration");
    assert_eq!(dps_duration, 1);

    let dps_degraded = find_sum_datapoints(&finished, "lancet.rag.answer.degraded");
    assert_eq!(dps_degraded.len(), 0, "no degraded answer increment when terminal basis is retrieval");
}

// ---------------------------------------------------------------------------
// Task 3: Ingestion & Index Metrics and Dashboard Cross-Check
// ---------------------------------------------------------------------------

#[tokio::test]
async fn metrics_ingest_document_completed_and_chunks_recorded() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();

    record_ingest_document(INGEST_COMPLETED);
    record_ingest_chunks(42);

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();

    let docs = find_sum_datapoints(&finished, "lancet.ingest.documents");
    assert_eq!(docs.len(), 1);
    assert_eq!(docs[0].0, 1);
    assert!(docs[0].1.contains(&("outcome".into(), "completed".into())));

    let chunks = find_sum_datapoints(&finished, "lancet.ingest.chunks");
    assert_eq!(chunks.len(), 1);
    assert_eq!(chunks[0].0, 42);
}

#[tokio::test]
async fn metrics_ingest_document_failed_recorded_without_chunks() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();

    record_ingest_document(INGEST_FAILED);

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();

    let docs = find_sum_datapoints(&finished, "lancet.ingest.documents");
    assert_eq!(docs.len(), 1);
    assert_eq!(docs[0].0, 1);
    assert!(docs[0].1.contains(&("outcome".into(), "failed".into())));

    let chunks = find_sum_datapoints(&finished, "lancet.ingest.chunks");
    assert_eq!(chunks.len(), 0, "no chunk metric increment on document failure");
}

#[tokio::test]
async fn metrics_index_rebuild_records_duration_and_corpus_generation() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();

    record_index_rebuild_duration_ms(REBUILD_COMPLETED, 120);
    record_corpus_generation(5);

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();

    let duration_count = find_hist_total_count(&finished, "lancet.index.rebuild.duration");
    assert_eq!(duration_count, 1);

    let mut found_gauge_val = None;
    for rm in &finished {
        for sm in rm.scope_metrics() {
            for m in sm.metrics() {
                if m.name() == "lancet.index.corpus_generation" {
                    if let opentelemetry_sdk::metrics::data::AggregatedMetrics::U64(
                        opentelemetry_sdk::metrics::data::MetricData::Gauge(gauge),
                    ) = m.data()
                    {
                        for dp in gauge.data_points() {
                            found_gauge_val = Some(dp.value());
                        }
                    }
                }
            }
        }
    }
    assert_eq!(found_gauge_val, Some(5));
}

#[tokio::test]
async fn metrics_index_rebuild_fault_records_failed_duration_without_advancing_generation() {
    let _lock = METRIC_TEST_MUTEX.lock().await;
    let (exporter, meter_provider) = setup_test_meter();

    record_corpus_generation(2);
    record_index_rebuild_duration_ms(REBUILD_FAILED, 50);

    let _ = meter_provider.force_flush();
    let finished = exporter.get_finished_metrics().unwrap();

    let duration_count = find_hist_total_count(&finished, "lancet.index.rebuild.duration");
    assert_eq!(duration_count, 1);

    let mut found_gauge_val = None;
    for rm in &finished {
        for sm in rm.scope_metrics() {
            for m in sm.metrics() {
                if m.name() == "lancet.index.corpus_generation" {
                    if let opentelemetry_sdk::metrics::data::AggregatedMetrics::U64(
                        opentelemetry_sdk::metrics::data::MetricData::Gauge(gauge),
                    ) = m.data()
                    {
                        for dp in gauge.data_points() {
                            found_gauge_val = Some(dp.value());
                        }
                    }
                }
            }
        }
    }
    assert_eq!(found_gauge_val, Some(2), "gauge remained at prior generation");
}

#[test]
fn dashboard_panels_resolve_to_defined_instruments() {
    let dashboard_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("deploy")
        .join("grafana")
        .join("dashboards")
        .join("lancet-rag-operations.json");

    assert!(dashboard_path.exists(), "dashboard json must exist at {:?}", dashboard_path);
    let content = std::fs::read_to_string(&dashboard_path).unwrap();
    let val: serde_json::Value = serde_json::from_str(&content).unwrap();

    let panels = val["panels"].as_array().expect("dashboard panels array");
    assert_eq!(panels.len(), 10, "dashboard must contain exactly 10 panels");

    let defined_prom_metric_stems = [
        "lancet_rag_query_duration_milliseconds",
        "lancet_rag_retrieval_path_failures_total",
        "lancet_rag_answer_degraded_total",
        "lancet_rag_citation_repairs_total",
        "lancet_rag_generation_retries_total",
        "lancet_rag_evidence_set_size",
        "lancet_ingest_documents_total",
        "lancet_ingest_chunks_total",
        "lancet_index_rebuild_duration_milliseconds",
        "lancet_index_corpus_generation",
    ];

    for panel in panels {
        let targets = panel["targets"].as_array().expect("panel targets array");
        assert!(!targets.is_empty(), "panel must have at least one target");
        for target in targets {
            let expr = target["expr"].as_str().expect("target expr string");
            let has_match = defined_prom_metric_stems.iter().any(|stem| expr.contains(stem));
            assert!(
                has_match,
                "panel query '{}' does not reference any known defined metric instrument stem",
                expr
            );
        }
    }
}

#[test]
fn collector_prometheus_exporter_has_no_namespace() {
    let config_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("deploy")
        .join("collector")
        .join("otel-collector-config.yaml");

    assert!(config_path.exists(), "collector config must exist at {:?}", config_path);
    let content = std::fs::read_to_string(&config_path).unwrap();

    let mut in_exporters = false;
    let mut in_prometheus = false;
    let mut prometheus_block = String::new();

    for line in content.lines() {
        if line.starts_with("exporters:") {
            in_exporters = true;
            continue;
        }
        if in_exporters {
            if !line.starts_with(' ') && !line.is_empty() {
                in_exporters = false;
                in_prometheus = false;
                continue;
            }
            if line.starts_with("  prometheus:") {
                in_prometheus = true;
                prometheus_block.push_str(line);
                prometheus_block.push('\n');
                continue;
            }
            if in_prometheus {
                if line.starts_with("  ") && !line.starts_with("    ") && !line.trim().is_empty() {
                    in_prometheus = false;
                    continue;
                }
                prometheus_block.push_str(line);
                prometheus_block.push('\n');
            }
        }
    }

    assert!(!prometheus_block.is_empty(), "prometheus exporter block must be found in otel-collector-config.yaml");
    assert!(prometheus_block.contains("endpoint:"), "prometheus exporter must configure an endpoint");
    assert!(!prometheus_block.contains("namespace:"), "prometheus exporter must not configure a namespace (extra prefix causes double prefixing)");
}

#[test]
fn grafana_traces_to_logs_maps_no_span_tag() {
    let config_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("deploy")
        .join("grafana")
        .join("provisioning")
        .join("datasources")
        .join("datasources.yaml");

    assert!(config_path.exists(), "datasources config must exist at {:?}", config_path);
    let content = std::fs::read_to_string(&config_path).unwrap();

    let mut in_traces_to_logs = false;
    let mut traces_indent = 0;
    let mut traces_block = String::new();

    let mut in_derived_fields = false;
    let mut derived_indent = 0;
    let mut derived_block = String::new();

    for line in content.lines() {
        let trimmed = line.trim();
        let leading_spaces = line.len() - line.trim_start().len();

        if trimmed.starts_with("tracesToLogsV2:") {
            in_traces_to_logs = true;
            traces_indent = leading_spaces;
            traces_block.push_str(line);
            traces_block.push('\n');
            continue;
        }

        if in_traces_to_logs {
            if !trimmed.is_empty() && leading_spaces <= traces_indent {
                in_traces_to_logs = false;
            } else {
                traces_block.push_str(line);
                traces_block.push('\n');
            }
        }

        if trimmed.starts_with("derivedFields:") {
            in_derived_fields = true;
            derived_indent = leading_spaces;
            derived_block.push_str(line);
            derived_block.push('\n');
            continue;
        }

        if in_derived_fields {
            if !trimmed.is_empty() && leading_spaces <= derived_indent {
                in_derived_fields = false;
            } else {
                derived_block.push_str(line);
                derived_block.push('\n');
            }
        }
    }

    assert!(
        !traces_block.is_empty(),
        "tracesToLogsV2 block must be found in datasources.yaml"
    );
    assert!(
        traces_block.contains("filterByTraceID: true"),
        "tracesToLogsV2 must have filterByTraceID: true (G-06.2-1)"
    );
    assert!(
        traces_block.contains("filterBySpanID: false"),
        "tracesToLogsV2 must have filterBySpanID: false (G-06.2-1)"
    );
    for line in traces_block.lines() {
        assert!(
            !line.trim().starts_with("tags:"),
            "tracesToLogsV2 must not have tags: mapping because trace_id is intrinsic span context (G-06.2-1): found line '{}'",
            line
        );
    }

    assert!(
        !derived_block.is_empty(),
        "derivedFields block must be found in datasources.yaml"
    );
    let has_matcher_type_label = derived_block
        .lines()
        .any(|l| l.trim() == "matcherType: label");
    assert!(
        has_matcher_type_label,
        "derivedFields must contain 'matcherType: label' because OTLP logs carry trace identity as Loki structured metadata (G-06.2-1)"
    );
    let has_matcher_regex_trace_id = derived_block
        .lines()
        .any(|l| l.trim() == "matcherRegex: trace_id" || l.trim() == "matcherRegex: \"trace_id\"");
    assert!(
        has_matcher_regex_trace_id,
        "derivedFields must contain 'matcherRegex: trace_id' or 'matcherRegex: \"trace_id\"' (G-06.2-1)"
    );
    assert!(
        !derived_block.contains("trace_id="),
        "derivedFields must not contain 'trace_id=' body regex pattern (G-06.2-1)"
    );
    assert!(
        !derived_block.contains("([0-9a-fA-F]+)"),
        "derivedFields must not contain capture group pattern '([0-9a-fA-F]+)' (G-06.2-1)"
    );
}

#[test]
fn duration_panels_query_histogram_buckets() {
    let dashboard_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("deploy")
        .join("grafana")
        .join("dashboards")
        .join("lancet-rag-operations.json");

    assert!(dashboard_path.exists(), "dashboard json must exist at {:?}", dashboard_path);
    let content = std::fs::read_to_string(&dashboard_path).unwrap();
    let val: serde_json::Value = serde_json::from_str(&content).unwrap();

    let panels = val["panels"].as_array().expect("dashboard panels array");
    assert!(!panels.is_empty(), "dashboard must contain panels");

    let histogram_stems = [
        "lancet_rag_query_duration_milliseconds",
        "lancet_rag_evidence_set_size",
        "lancet_index_rebuild_duration_milliseconds",
    ];

    let mut matched_histogram_stem_targets = 0;
    let mut matched_duration_panels = 0;

    for panel in panels {
        let title = panel["title"].as_str().unwrap_or("");
        let targets = panel["targets"].as_array().expect("panel targets array");

        let is_duration_panel = title.contains("Duration");
        if is_duration_panel {
            matched_duration_panels += 1;
            assert!(!targets.is_empty(), "duration panel '{title}' must have targets");
        }

        for target in targets {
            let expr = target["expr"].as_str().expect("target expr string");

            // Predicate 1: histogram stems must be queried as histograms
            for stem in &histogram_stems {
                if expr.contains(stem) {
                    matched_histogram_stem_targets += 1;
                    assert!(
                        expr.contains("histogram_quantile("),
                        "panel query '{expr}' reads histogram instrument '{stem}' but does not use histogram_quantile — G-06.2-2"
                    );
                    let bucket_suffix = format!("{stem}_bucket");
                    assert!(
                        expr.contains(&bucket_suffix),
                        "panel query '{expr}' reads histogram instrument '{stem}' but does not query _bucket — G-06.2-2"
                    );
                    let count_suffix = format!("{stem}_count");
                    assert!(
                        !expr.contains(&count_suffix),
                        "panel query '{expr}' reads histogram instrument '{stem}' via _count/rate (throughput) instead of _bucket via histogram_quantile (distribution) — G-06.2-2"
                    );
                }
            }

            // Predicate 2: a panel titled Duration must plot a duration
            if is_duration_panel {
                assert!(
                    expr.contains("histogram_quantile("),
                    "duration panel '{title}' query '{expr}' does not contain histogram_quantile( — G-06.2-2"
                );
                assert!(
                    expr.contains("_bucket"),
                    "duration panel '{title}' query '{expr}' does not contain _bucket — G-06.2-2"
                );
            }
        }
    }

    assert!(
        matched_histogram_stem_targets > 0,
        "at least one target must match a histogram instrument stem"
    );
    assert!(
        matched_duration_panels > 0,
        "at least one panel must have Duration in its title"
    );
}

#[test]
fn otel_internal_diagnostics_are_bounded() {
    use std::sync::atomic::Ordering;
    use std::time::{Duration, Instant};
    use tracing::Level;
    use tracing_subscriber::layer::SubscriberExt;
    use tracing_subscriber::Layer as _;
    use crate::telemetry::{BoundedOtelDiagnostics, OtelDiagnosticsFilter, DropOtelDiagnosticsFilter};

    let t0 = Instant::now();
    let bounded = BoundedOtelDiagnostics::new(1, Duration::from_secs(300));

    // Property 1: Application targets always pass and do not consume cap
    assert!(bounded.should_emit_at("lancet_engine::retrieval", &Level::INFO, t0));
    assert!(bounded.should_emit_at("lancet_engine::retrieval", &Level::ERROR, t0));
    assert!(bounded.should_emit_at("tower_http::trace", &Level::DEBUG, t0));

    // Property 2a: OTel debug/trace/info noise is dropped and does not consume cap
    assert!(!bounded.should_emit_at("opentelemetry", &Level::INFO, t0));
    assert!(!bounded.should_emit_at("opentelemetry_sdk::export", &Level::DEBUG, t0));
    assert!(!bounded.should_emit_at("opentelemetry_otlp::exporter", &Level::TRACE, t0));

    // Property 2b: OTel warn/error competes for the cap (1 emitted in 5m window)
    assert!(bounded.should_emit_at("opentelemetry_otlp::exporter", &Level::WARN, t0));
    for _ in 0..999 {
        assert!(!bounded.should_emit_at("opentelemetry_otlp::exporter", &Level::ERROR, t0));
    }

    // Property 3: Window re-arms after 5 minutes
    let t1 = t0 + Duration::from_secs(301);
    assert!(bounded.should_emit_at("opentelemetry_otlp::exporter", &Level::ERROR, t1));
    for _ in 0..999 {
        assert!(!bounded.should_emit_at("opentelemetry_otlp::exporter", &Level::ERROR, t1));
    }

    // Property 4 & 5: Composed layers and DropOtelDiagnosticsFilter
    #[derive(Default, Clone)]
    struct CountLayer {
        count: std::sync::Arc<std::sync::atomic::AtomicUsize>,
    }
    impl<S: tracing::Subscriber> tracing_subscriber::Layer<S> for CountLayer {
        fn on_event(
            &self,
            _event: &tracing::Event<'_>,
            _ctx: tracing_subscriber::layer::Context<'_, S>,
        ) {
            self.count.fetch_add(1, Ordering::SeqCst);
        }
    }

    let fmt_counter = CountLayer::default();
    let fmt_count = fmt_counter.count.clone();
    let filter_state = std::sync::Arc::new(BoundedOtelDiagnostics::new(1, Duration::from_secs(300)));
    let fmt_layer = fmt_counter.with_filter(OtelDiagnosticsFilter::new(filter_state));

    let bridge_counter = CountLayer::default();
    let bridge_count = bridge_counter.count.clone();
    let bridge_layer = bridge_counter.with_filter(DropOtelDiagnosticsFilter);

    let subscriber = tracing_subscriber::Registry::default()
        .with(fmt_layer)
        .with(bridge_layer);

    let _guard = tracing::subscriber::set_default(subscriber);

    // Emit application event
    tracing::info!(target: "lancet_engine::test", "app event");
    assert_eq!(fmt_count.load(Ordering::SeqCst), 1);
    assert_eq!(bridge_count.load(Ordering::SeqCst), 1);

    // Emit 10 OTel error events
    for _ in 0..10 {
        tracing::error!(target: "opentelemetry::sdk", "sdk export error");
    }
    // Fmt layer saw exactly 1 additional event (cap=1); bridge saw 0 additional events (all dropped)
    assert_eq!(fmt_count.load(Ordering::SeqCst), 2);
    assert_eq!(bridge_count.load(Ordering::SeqCst), 1);
}




