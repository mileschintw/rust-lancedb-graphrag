use std::io::{Read, Write};
use std::net::TcpListener;
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use engine::config::EffectiveRagSettings;
use engine::doc_meta::DocMeta;
use engine::generation::openrouter::{OpenRouterGenerationConfig, OpenRouterGenerator};
use engine::generation::Generator;
use engine::graph::context_strategy::GraphFact;
use engine::pb::lancet::v1::QueryRagRequest;
use engine::prompt::{EvidenceBlock, GraphFactBlock};
use engine::retrieval::{Candidate, FusedCandidate};
use engine::workflow::nodes::{AssemblePromptNode, GenerateAnswerNode};
use engine::workflow::{LeverSet, Node, WorkflowContext};
use serde_json::json;
use tokio_util::sync::CancellationToken;

use super::*;

const QUESTION: &str = "Which outlet reported that \"Acme\" bought Globex?";

/// Serves one HTTP request on a loopback port: returns the base URL and a handle yielding the
/// request body the server received.
fn serve_once(status: u16, response: String) -> (String, thread::JoinHandle<Vec<u8>>) {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind loopback");
    let url = format!("http://{}", listener.local_addr().expect("local addr"));
    let handle = thread::spawn(move || {
        listener
            .set_nonblocking(true)
            .expect("non-blocking listener");
        let start = Instant::now();
        let (mut stream, _) = loop {
            match listener.accept() {
                Ok(pair) => break pair,
                Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => {
                    assert!(
                        start.elapsed() < Duration::from_secs(10),
                        "no request arrived"
                    );
                    thread::sleep(Duration::from_millis(10));
                }
                Err(err) => panic!("accept failed: {err}"),
            }
        };
        stream.set_nonblocking(false).expect("blocking stream");
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .expect("read timeout");
        let mut buf = Vec::new();
        let mut chunk = [0_u8; 4096];
        let header_end = loop {
            let n = stream.read(&mut chunk).expect("read request");
            assert!(n > 0, "connection closed before the headers ended");
            buf.extend_from_slice(&chunk[..n]);
            if let Some(pos) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                break pos + 4;
            }
        };
        let headers = String::from_utf8_lossy(&buf[..header_end]).to_ascii_lowercase();
        let length: usize = headers
            .lines()
            .find_map(|line| line.strip_prefix("content-length:"))
            .map(|value| value.trim().parse().expect("content-length"))
            .expect("request carries content-length");
        while buf.len() < header_end + length {
            let n = stream.read(&mut chunk).expect("read body");
            assert!(n > 0, "connection closed before the body ended");
            buf.extend_from_slice(&chunk[..n]);
        }
        let reply = format!(
            "HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{response}",
            response.len()
        );
        stream.write_all(reply.as_bytes()).expect("write reply");
        buf[header_end..header_end + length].to_vec()
    });
    (url, handle)
}

fn chat_reply(model_output: serde_json::Value) -> String {
    json!({
        "id": "gen-test",
        "model": "test/model",
        "choices": [{
            "message": {"content": model_output.to_string()},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 900, "completion_tokens": 40, "total_tokens": 940}
    })
    .to_string()
}

fn config_for(settings: &EffectiveRagSettings, base: &str) -> OpenRouterGenerationConfig {
    OpenRouterGenerationConfig::from_effective_limits(
        "test/model",
        format!("{base}/chat/completions"),
        format!("{base}/models"),
        Duration::from_secs(10),
        settings.temperature,
        settings.top_p,
        settings.grounding_limits_arc(),
    )
    .expect("generation config")
    .with_provider_order(vec!["sail-research".to_owned()])
}

fn candidate(
    document_id: &str,
    chunk_index: i32,
    text: &str,
    title: Option<&str>,
) -> FusedCandidate {
    FusedCandidate {
        candidate: Candidate {
            document_id: document_id.to_owned(),
            chunk_id: format!("{document_id}:{chunk_index}"),
            chunk_index,
            char_start: 10,
            char_end: 90,
            content: text.to_owned(),
            title: title.map(str::to_owned),
            section_path: title.map(|_| "Root > Deal".to_owned()),
            content_type: title.map(|_| "text/markdown".to_owned()),
            embedding_model: Some("voyage".to_owned()),
            ingested_at: Some(1),
            score: 0.2,
        },
        fused_score: 0.031,
        vector_rank: Some(1),
        bm25_rank: None,
        vector_score: Some(0.8),
        bm25_score: None,
        variant_provenance: Vec::new(),
    }
}

/// The evidence and graph facts as the live engine builds them: `from_candidate`, the metadata
/// attached by `RetrieveHybrid`, and `GraphFact::new` over raw store values.
fn engine_context() -> (Vec<EvidenceBlock>, Vec<GraphFactBlock>) {
    let mut first = EvidenceBlock::from_candidate(
        0,
        &candidate(
            "doc-a",
            2,
            "Acme <b>announced</b> it will buy Globex & keep 'its' name.",
            Some("acme \"globex\".md"),
        ),
    );
    first.attach_evidence_meta(DocMeta {
        doc_title: Some("Acme to buy Globex".to_owned()),
        source: Some("The Verge".to_owned()),
        published_date: Some("2023-10-02".to_owned()),
    });
    let second = EvidenceBlock::from_candidate(
        1,
        &candidate("doc-b", 0, "Globex shareholders approved the deal.", None),
    );
    let fact = GraphFactBlock {
        fact: GraphFact::new(
            "Acme & Co",
            "ACQUIRED",
            "<Globex>",
            Some("Acme's \"deal\""),
            0.8,
        ),
    };
    (vec![first, second], vec![fact])
}

/// The export row `context_export.py` writes from a checkpoint holding these blocks.
fn export_row(blocks: &[EvidenceBlock], facts: &[GraphFactBlock]) -> String {
    let evidence: Vec<_> = blocks
        .iter()
        .map(|block| {
            let v = serde_json::to_value(block).expect("block json");
            let meta = &v["evidence_meta"];
            json!({
                "rank": v["rank"], "chunk_id": v["chunk_id"], "document_id": v["document_id"],
                "text": v["text"], "title": v["title"], "section_path": v["section_path"],
                "content_type": v["content_type"], "score": v["score"],
                "suspicious": v["suspicious"],
                "document_metadata": {
                    "source": meta["source"], "doc_title": meta["doc_title"],
                    "published_date": meta["published_date"]
                }
            })
        })
        .collect();
    json!({
        "corpus": "multihop_rag", "question_id": "q-1", "arm": "graph_on",
        "question": QUESTION, "evidence": evidence,
        "graph_facts": serde_json::to_value(facts).expect("facts json"),
        "assembled_prompt": "unused", "correlation_id": "trace-1"
    })
    .to_string()
}

fn levers() -> LeverSet {
    LeverSet::try_from_names(&["rerank".to_owned(), "evidence_metadata".to_owned()])
        .expect("levers")
}

fn row_of(line: &str) -> ExportRow {
    read_rows(line.as_bytes()).expect("row").remove(0)
}

#[test]
fn parse_args_reads_mode_input_and_levers() {
    let args = |list: &[&str]| parse_args(list.iter().map(|s| (*s).to_owned()));
    assert_eq!(
        args(&[
            "pack",
            "--input",
            "x.jsonl",
            "--levers",
            "rerank, evidence_metadata"
        ]),
        Ok(Command {
            mode: Mode::Pack,
            input: "x.jsonl".to_owned(),
            levers: Some(vec!["rerank".to_owned(), "evidence_metadata".to_owned()]),
            results: None,
        })
    );
    assert_eq!(
        args(&["generate", "--input", "x.jsonl", "--levers", ""]).map(|c| c.levers),
        Ok(Some(Vec::new())),
        "an empty --levers is no lever"
    );
    assert_eq!(
        args(&["generate", "--input", "x.jsonl"]).map(|c| (c.mode, c.levers)),
        Ok((Mode::Generate, None))
    );
    assert!(args(&["score", "--input", "x"]).is_err());
    assert!(args(&["pack"]).is_err(), "--input is required");
    assert!(args(&["pack", "--input", "x", "--bogus"]).is_err());
}

#[test]
fn chunk_index_comes_from_an_engine_chunk_id_and_is_zero_otherwise() {
    let (blocks, facts) = engine_context();
    let row = row_of(&export_row(&blocks, &facts));
    assert_eq!(chunk_index_of(&row.evidence[0]), 2);
    let mut external = row.evidence[0].clone();
    external.chunk_id = "5f0c-node-uuid".to_owned();
    assert_eq!(chunk_index_of(&external), 0);
}

#[test]
fn chunk_index_parses_both_separators_after_the_document_id() {
    let (blocks, facts) = engine_context();
    let row = row_of(&export_row(&blocks, &facts));
    let index_of = |document_id: &str, chunk_id: &str| {
        let mut entry = row.evidence[0].clone();
        entry.document_id = document_id.to_owned();
        entry.chunk_id = chunk_id.to_owned();
        chunk_index_of(&entry)
    };
    assert_eq!(index_of("doc", "doc#3"), 3, "LlamaIndex export shape");
    assert_eq!(index_of("doc", "doc:3"), 3, "engine shape");
    assert_eq!(
        index_of("a#b", "a#b#7"),
        7,
        "a document ID with # takes the last separator"
    );
    assert_eq!(
        index_of("a:b", "a:b:7"),
        7,
        "a document ID with : takes the last separator"
    );
    assert_eq!(index_of("a:b", "a:b#7"), 7);
    for chunk_id in [
        "doc#x",
        "doc#",
        "doc#-3",
        "doc#+3",
        "doc#2147483648",
        "doc:-1",
        "doc3",
        "other#3",
        "doc#1#3",
    ] {
        assert_eq!(index_of("doc", chunk_id), 0, "{chunk_id}");
    }
    assert_eq!(index_of("doc", "doc#2147483647"), i32::MAX);
}

#[test]
fn rebuilt_evidence_and_facts_equal_the_engine_built_ones() {
    let (blocks, facts) = engine_context();
    let row = row_of(&export_row(&blocks, &facts));
    let rebuilt = evidence_blocks(&row.evidence).expect("evidence");
    assert_eq!(rebuilt, blocks);
    assert_eq!(graph_fact_blocks(&row.graph_facts).expect("facts"), facts);
}

#[test]
fn a_graph_fact_that_does_not_round_trip_is_refused() {
    let unescaped = json!([{"fact": {
        "entity_a_name": "<raw>", "relation_type": "R", "entity_b_name": "B",
        "edge_summary": null, "score": 0.5
    }}]);
    let err = graph_fact_blocks(unescaped.as_array().expect("array")).expect_err("refused");
    assert!(err.contains("round-trip"), "{err}");
}

#[test]
fn read_rows_refuses_a_field_outside_the_contract() {
    let (blocks, facts) = engine_context();
    let mut row: serde_json::Value =
        serde_json::from_str(&export_row(&blocks, &facts)).expect("json");
    row["extra"] = json!(1);
    let err = read_rows(row.to_string().as_bytes()).expect_err("refused");
    assert!(err.contains("line 1"), "{err}");
}

/// #11 acceptance: for a fixture row, `pack` emits the body the engine's live path posts for the
/// same evidence, and its user message is the prompt `AssemblePrompt` checkpointed.
#[tokio::test]
async fn pack_body_equals_the_live_request_body() {
    let settings = EffectiveRagSettings::default();
    let reply = chat_reply(json!({
        "answer": "The Verge reported it [1].", "cited_evidence_ids": ["[1]"],
        "answer_basis": "retrieval", "notices": [], "warnings": [], "final_answer": "The Verge"
    }));
    let (base, server) = serve_once(200, reply);
    let config = config_for(&settings, &base);

    // The live path: the service's two nodes and the OpenRouter adapter, over engine-built blocks.
    let (blocks, facts) = engine_context();
    let live_generator: Arc<dyn Generator> = Arc::new(
        OpenRouterGenerator::new_with_config("test-key", config.clone()).expect("generator"),
    );
    let limits = settings.grounding_limits();
    let mut ctx = WorkflowContext::new(
        "s".to_owned(),
        "trace-1".to_owned(),
        &QueryRagRequest {
            query: QUESTION.to_owned(),
            ..Default::default()
        },
    );
    ctx.levers = levers();
    ctx.evidence_blocks = blocks.clone();
    ctx.graph_facts = facts.clone();
    let cancel = CancellationToken::new();
    AssemblePromptNode::with_settings(
        limits.evidence_token_budget() as usize,
        limits.max_output_tokens() as usize,
        settings.retrieval.graph_weight,
    )
    .run(&mut ctx, &cancel)
    .await
    .expect("assemble");
    GenerateAnswerNode::new(Some(live_generator))
        .with_settings(
            *limits,
            settings.citation_excerpt_max_chars,
            settings.retrieval.graph_weight,
        )
        .with_citation_repair_enabled(settings.workflow.citation_repair_enabled)
        .run(&mut ctx, &cancel)
        .await
        .expect("generate");
    let live_body = server.join().expect("server thread");

    let row = row_of(&export_row(&blocks, &facts));
    let tail = Tail::new(Mode::Pack, &settings, config, None);
    let line = tail.run_row(&row, levers()).await;
    assert_eq!(line.outcome, "success", "{:?}", line.error);
    let body = line.body.expect("body");
    assert_eq!(body.as_bytes(), live_body.as_slice());

    let parsed: serde_json::Value = serde_json::from_str(&body).expect("body json");
    assert_eq!(parsed["messages"][1]["role"], "user");
    assert_eq!(
        parsed["messages"][1]["content"],
        ctx.assembled_prompt.as_str()
    );
    assert!(ctx.assembled_prompt.contains("<SOURCE>The Verge</SOURCE>"));
}

#[tokio::test]
async fn pack_reports_a_row_the_engine_would_refuse() {
    let settings = EffectiveRagSettings::default();
    let config = config_for(&settings, "http://127.0.0.1:9");
    let (blocks, facts) = engine_context();
    let mut row = row_of(&export_row(&blocks, &facts));
    row.evidence.clear();
    let tail = Tail::new(Mode::Pack, &settings, config.clone(), None);
    let line = tail.run_row(&row, LeverSet::default()).await;
    assert_eq!(line.outcome, "error");
    assert_eq!(line.question_id, "q-1");

    let mut row = row_of(&export_row(&blocks, &facts));
    row.evidence.swap(0, 1);
    let line = Tail::new(Mode::Pack, &settings, config, None)
        .run_row(&row, LeverSet::default())
        .await;
    assert_eq!(line.error_type.as_deref(), Some("INVALID_ROW"));
}

#[tokio::test]
async fn generate_writes_the_rendered_answer_and_its_usage() {
    let settings = EffectiveRagSettings::default();
    let reply = chat_reply(json!({
        "answer": "The Verge reported it first [1].", "cited_evidence_ids": ["[1]"],
        "answer_basis": "retrieval", "notices": [], "warnings": [], "final_answer": "The Verge"
    }));
    let (base, server) = serve_once(200, reply);
    let config = config_for(&settings, &base);
    let reader: Arc<dyn Generator> = Arc::new(
        OpenRouterGenerator::new_with_config("test-key", config.clone()).expect("generator"),
    );
    let (blocks, facts) = engine_context();
    let row = row_of(&export_row(&blocks, &facts));
    let line = Tail::new(Mode::Generate, &settings, config, Some(reader))
        .run_row(&row, levers())
        .await;
    server.join().expect("server thread");

    assert_eq!(line.outcome, "success", "{:?}", line.error);
    assert_eq!(
        line.answer.as_deref(),
        Some("The Verge reported it first [1].\nAnswer: The Verge")
    );
    assert_eq!(line.final_answer.as_deref(), Some("The Verge"));
    assert_eq!(line.citations, Some(vec!["[1]".to_owned()]));
    let cited = line.structured_citations.expect("structured citations");
    assert_eq!(cited.len(), 1);
    assert_eq!(cited[0].chunk_id, "doc-a:2");
    assert_eq!(line.answer_basis.as_deref(), Some("ANSWER_BASIS_RETRIEVAL"));
    let usage = line.usage.expect("usage");
    assert_eq!(
        (
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.total_tokens
        ),
        (900, 40, 940)
    );
    assert!(line.body.is_none());
}

#[tokio::test]
async fn generate_turns_a_reader_failure_into_an_error_line() {
    let settings = EffectiveRagSettings::default();
    let (base, server) = serve_once(400, "{}".to_owned());
    let config = config_for(&settings, &base);
    let reader: Arc<dyn Generator> = Arc::new(
        OpenRouterGenerator::new_with_config("test-key", config.clone()).expect("generator"),
    );
    let (blocks, facts) = engine_context();
    let row = row_of(&export_row(&blocks, &facts));
    let line = Tail::new(Mode::Generate, &settings, config, Some(reader))
        .run_row(&row, levers())
        .await;
    server.join().expect("server thread");

    assert_eq!(line.outcome, "error");
    assert_eq!(
        line.error_type.as_deref(),
        Some("NODE_ERROR_KIND_LLM_GENERATION_FAILED")
    );
    assert!(line.error.expect("error").contains("HTTP 400"));
    assert!(line.answer.is_none());
}

#[test]
fn parse_args_reads_render_results() {
    let args = |list: &[&str]| parse_args(list.iter().map(|s| (*s).to_owned()));
    assert_eq!(
        args(&["render", "--input", "x.jsonl", "--results", "r.jsonl"])
            .map(|c| (c.mode, c.results)),
        Ok((Mode::Render, Some("r.jsonl".to_owned())))
    );
    assert!(
        args(&["render", "--input", "x.jsonl"]).is_err(),
        "render needs --results"
    );
    assert!(
        args(&["generate", "--input", "x.jsonl", "--results", "r.jsonl"]).is_err(),
        "only render reads --results"
    );
}

/// The model output `provider_stub` sends in these tests.
fn stub_output() -> serde_json::Value {
    json!({
        "answer": "The Verge reported it first [1].", "cited_evidence_ids": ["[1]"],
        "answer_basis": "retrieval", "notices": [], "warnings": [], "final_answer": "The Verge"
    })
}

/// A results-file line for the fixture row.
fn result_line(content: &str, finish_reason: &str) -> String {
    json!({
        "question_id": "q-1", "arm": "graph_on", "content": content,
        "finish_reason": finish_reason,
        "usage": {"prompt_tokens": 900, "completion_tokens": 40, "total_tokens": 940}
    })
    .to_string()
}

async fn render(results: &str) -> OutputLine {
    let settings = EffectiveRagSettings::default();
    let config = config_for(&settings, "http://127.0.0.1:9");
    let (blocks, facts) = engine_context();
    let row = row_of(&export_row(&blocks, &facts));
    let results = read_results(results.as_bytes()).expect("results");
    let tail = Tail::new(Mode::Render, &settings, config, None);
    tail.prepare()
        .await
        .expect("render makes no preflight call");
    tail.render_row(&row, levers(), &results).await
}

/// #50 acceptance: `render` over the output `generate` received writes the line `generate` wrote.
#[tokio::test]
async fn render_writes_the_line_generate_wrote() {
    let settings = EffectiveRagSettings::default();
    let (base, server) = serve_once(200, chat_reply(stub_output()));
    let config = config_for(&settings, &base);
    let reader: Arc<dyn Generator> = Arc::new(
        OpenRouterGenerator::new_with_config("test-key", config.clone()).expect("generator"),
    );
    let (blocks, facts) = engine_context();
    let row = row_of(&export_row(&blocks, &facts));
    let generated = Tail::new(Mode::Generate, &settings, config, Some(reader))
        .run_row(&row, levers())
        .await;
    server.join().expect("server thread");
    assert_eq!(generated.outcome, "success", "{:?}", generated.error);

    let rendered = render(&result_line(&stub_output().to_string(), "stop")).await;
    assert_eq!(
        serde_json::to_string(&rendered).expect("rendered json"),
        serde_json::to_string(&generated).expect("generated json")
    );
}

/// #50 acceptance: invalid JSON, a schema violation, an ungrounded citation and a refusal each
/// become an `error` line with an `error_type`.
#[tokio::test]
async fn render_turns_each_rejected_output_into_an_error_line() {
    let mut ungrounded = stub_output();
    ungrounded["answer"] = json!("The Verge reported it first [7].");
    ungrounded["cited_evidence_ids"] = json!(["[7]"]);
    let mut unknown_field = stub_output();
    unknown_field["confidence"] = json!(0.9);
    let cases = [
        ("invalid JSON", result_line("{not json", "stop")),
        (
            "schema violation",
            result_line(&unknown_field.to_string(), "stop"),
        ),
        (
            "ungrounded citation",
            result_line(&ungrounded.to_string(), "stop"),
        ),
        (
            "refusal",
            result_line(&stub_output().to_string(), "refusal"),
        ),
    ];
    for (case, results) in cases {
        let line = render(&results).await;
        assert_eq!(line.outcome, "error", "{case}");
        assert_eq!(line.question_id, "q-1", "{case}");
        assert!(line.error_type.is_some(), "{case}");
        assert!(line.error.is_some(), "{case}");
        assert!(line.answer.is_none(), "{case}");
    }
}

/// #50 acceptance: a row without a result line becomes an `error` line, never a missing line.
#[tokio::test]
async fn render_writes_an_error_line_for_a_row_without_a_result() {
    let other = result_line(&stub_output().to_string(), "stop").replace("q-1", "q-2");
    let line = render(&other).await;
    assert_eq!(line.outcome, "error");
    assert_eq!(line.error_type.as_deref(), Some("MISSING_RESULT"));
}

#[tokio::test]
async fn render_reports_a_keyed_result_line_it_cannot_read() {
    let line = render(r#"{"question_id": "q-1", "arm": "graph_on", "content": 3}"#).await;
    assert_eq!(line.outcome, "error");
    assert_eq!(line.error_type.as_deref(), Some("INVALID_RESULT"));
}

#[test]
fn read_results_refuses_an_unkeyed_or_repeated_line() {
    let err = read_results(r#"{"content": "x"}"#.as_bytes()).expect_err("no key");
    assert!(err.contains("line 1"), "{err}");
    let line = result_line("{}", "stop");
    let err = read_results(format!("{line}\n\n{line}\n").as_bytes()).expect_err("repeated");
    assert!(err.contains("line 3"), "{err}");
}
