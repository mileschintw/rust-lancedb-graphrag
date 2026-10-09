use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

use serde_json::json;

use super::openrouter::{
    OpenRouterReranker, RerankConfig, DEFAULT_RERANK_ENDPOINT, DEFAULT_RERANK_MODEL,
    RERANK_MAX_BODY_BYTES,
};
use super::{reorder, NoOpReranker, RerankError, RerankOutput, RerankRequest, Reranked, Reranker};
use crate::retrieval::{Candidate, FusedCandidate};

fn fused_candidate(chunk_id: &str, score: f64) -> FusedCandidate {
    FusedCandidate {
        candidate: Candidate {
            document_id: "00000000-0000-4000-8000-000000000001".to_owned(),
            chunk_id: chunk_id.to_owned(),
            chunk_index: 2,
            char_start: 10,
            char_end: 30,
            content: "untrusted evidence".to_owned(),
            title: Some("Title".to_owned()),
            section_path: Some("Section".to_owned()),
            content_type: None,
            embedding_model: Some("model".to_owned()),
            ingested_at: Some(42),
            score,
        },
        fused_score: score / 3.0,
        vector_rank: Some(1),
        bm25_rank: Some(2),
        vector_score: Some(score),
        bm25_score: Some(score / 2.0),
        variant_provenance: Vec::new(),
    }
}

fn fused_candidates(n: usize) -> Vec<FusedCandidate> {
    (0..n)
        .map(|index| {
            let mut candidate =
                fused_candidate(&format!("chunk-{index}"), 0.9 - index as f64 / 10.0);
            candidate.candidate.content = format!("document text {index}");
            candidate
        })
        .collect()
}

#[tokio::test]
async fn noop_reranker_returns_the_identity_ranking_with_fused_scores() {
    let input = fused_candidates(3);
    let implementation = NoOpReranker::new();
    let reranker: &dyn Reranker = &implementation;
    let output = reranker
        .rerank(RerankRequest {
            query: "q",
            candidates: &input,
        })
        .await
        .unwrap();
    assert_eq!(output.cost_credits, None);
    let expected: Vec<Reranked> = input
        .iter()
        .enumerate()
        .map(|(index, candidate)| Reranked {
            index,
            score: candidate.fused_score,
        })
        .collect();
    assert_eq!(output.ranked, expected);
}

fn ranking(entries: &[(usize, f64)]) -> Vec<Reranked> {
    entries
        .iter()
        .map(|&(index, score)| Reranked { index, score })
        .collect()
}

#[test]
fn reorder_applies_a_permutation_and_pairs_each_candidate_with_its_score() {
    let reordered = reorder(
        fused_candidates(3),
        &ranking(&[(2, 0.9), (0, 0.5), (1, 0.1)]),
    )
    .unwrap();
    let ids: Vec<&str> = reordered
        .iter()
        .map(|(candidate, _)| candidate.candidate.chunk_id.as_str())
        .collect();
    assert_eq!(ids, ["chunk-2", "chunk-0", "chunk-1"]);
    let scores: Vec<f64> = reordered.iter().map(|(_, score)| *score).collect();
    assert_eq!(scores, [0.9, 0.5, 0.1]);
}

#[test]
fn reorder_refuses_what_is_not_a_permutation_of_the_candidates() {
    let bad_rankings = [
        ranking(&[(0, 1.0), (0, 0.5), (1, 0.1)]),
        ranking(&[(0, 1.0), (1, 0.5)]),
        ranking(&[(0, 1.0), (1, 0.5), (3, 0.1)]),
        ranking(&[(0, 1.0), (1, f64::NAN), (2, 0.1)]),
        ranking(&[(0, 1.0), (1, 0.5), (2, f64::INFINITY)]),
    ];
    for ranked in bad_rankings {
        let error = reorder(fused_candidates(3), &ranked).unwrap_err();
        assert!(error.is_malformed(), "{ranked:?}");
    }
}

// ---------------------------------------------------------------------------
// The OpenRouter adapter over a local mock server (D-131, C11)
// ---------------------------------------------------------------------------

const SENTINEL_KEY: &str = "sk-or-test-SENTINEL-8f3a1c";
const SLUG: &str = "voyageai/rerank-2.5-lite";

fn read_http_request(stream: &mut TcpStream) -> String {
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .expect("set mock read timeout");
    let mut request = Vec::new();
    let mut buffer = [0_u8; 4096];
    loop {
        if let Some(header_end) = request.windows(4).position(|window| window == b"\r\n\r\n") {
            let headers = String::from_utf8_lossy(&request[..header_end]);
            let content_length = headers
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .and_then(|value| value.trim().parse::<usize>().ok())
                })
                .unwrap_or(0);
            if request.len() >= header_end + 4 + content_length {
                break;
            }
        }
        let read = stream.read(&mut buffer).expect("read mock request");
        assert!(read > 0, "mock request ended before its body was received");
        request.extend_from_slice(&buffer[..read]);
    }
    String::from_utf8(request).expect("mock request must be UTF-8")
}

fn accept_with_deadline(listener: &TcpListener) -> TcpStream {
    let start = Instant::now();
    listener
        .set_nonblocking(true)
        .expect("set listener non-blocking");
    loop {
        match listener.accept() {
            Ok((stream, _)) => {
                stream.set_nonblocking(false).expect("set stream blocking");
                return stream;
            }
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                assert!(
                    start.elapsed() < Duration::from_secs(5),
                    "the mock server was never called"
                );
                thread::sleep(Duration::from_millis(10));
            }
            Err(error) => panic!("mock accept failed: {error}"),
        }
    }
}

/// What the mock server answers with.
struct Reply {
    status: u16,
    body: String,
    delay: Duration,
}

impl Reply {
    fn ok(body: serde_json::Value) -> Self {
        Self::status(200, body.to_string())
    }

    fn status(status: u16, body: impl Into<String>) -> Self {
        Self {
            status,
            body: body.into(),
            delay: Duration::ZERO,
        }
    }
}

/// Serves exactly one request and returns the URL and a handle yielding the raw request text.
fn serve_once(reply: Reply) -> (String, thread::JoinHandle<String>) {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind local mock server");
    let url = format!("http://{}/api/v1/rerank", listener.local_addr().unwrap());
    let handle = thread::spawn(move || {
        let mut stream = accept_with_deadline(&listener);
        let request = read_http_request(&mut stream);
        thread::sleep(reply.delay);
        let head = format!(
            "HTTP/1.1 {} Mock\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            reply.status,
            reply.body.len()
        );
        // The client may drop the connection first (an oversized or timed-out reply), which makes
        // a large write fail on Windows; the request text is what the test needs.
        let _ = stream.write_all(head.as_bytes());
        let _ = stream.write_all(reply.body.as_bytes());
        request
    });
    (url, handle)
}

fn reranker(url: &str, timeout: Duration) -> OpenRouterReranker {
    OpenRouterReranker::new(SENTINEL_KEY, RerankConfig::new(url, SLUG, timeout).unwrap())
        .expect("a non-blank key builds the adapter")
}

fn reply_body(model: &str, results: &[(usize, f64)]) -> serde_json::Value {
    json!({
        "id": "gen-test",
        "model": model,
        "provider": "VoyageAI by MongoDB",
        "results": results
            .iter()
            .map(|(index, score)| json!({"index": index, "relevance_score": score}))
            .collect::<Vec<_>>(),
        "usage": {"cost": 4.4e-07, "total_tokens": 22},
    })
}

async fn call(
    reranker: &OpenRouterReranker,
    candidates: &[FusedCandidate],
) -> Result<RerankOutput, RerankError> {
    reranker
        .rerank(RerankRequest {
            query: "what is rrf",
            candidates,
        })
        .await
}

#[tokio::test]
async fn the_request_is_one_post_with_the_bearer_key_and_the_exact_body() {
    let (url, server) = serve_once(Reply::ok(reply_body(
        "rerank-2.5-lite",
        &[(0, 0.9), (1, 0.8), (2, 0.1)],
    )));
    let candidates = fused_candidates(3);
    let result = call(&reranker(&url, Duration::from_secs(5)), &candidates).await;

    let request = server.join().expect("mock server thread");
    let (head, body) = request
        .split_once("\r\n\r\n")
        .expect("a request with a body");
    assert!(head.starts_with("POST /api/v1/rerank HTTP/1.1"), "{head}");
    assert!(
        head.to_ascii_lowercase()
            .contains(&format!("authorization: bearer {SENTINEL_KEY}").to_ascii_lowercase()),
        "the bearer key must be sent: {head}"
    );
    let body: serde_json::Value = serde_json::from_str(body).expect("the body is JSON");
    assert_eq!(
        body,
        json!({
            "model": SLUG,
            "query": "what is rrf",
            "documents": ["document text 0", "document text 1", "document text 2"],
            "top_n": 3,
            "provider": {"allow_fallbacks": false},
        })
    );
    result.expect("a valid reply is accepted");
}

#[tokio::test]
async fn equal_scores_break_by_index_whatever_order_the_reply_lists_them() {
    let (url, server) = serve_once(Reply::ok(reply_body(
        "rerank-2.5-lite",
        &[(1, 0.9), (0, 0.9), (2, 0.1)],
    )));
    let output = call(
        &reranker(&url, Duration::from_secs(5)),
        &fused_candidates(3),
    )
    .await
    .unwrap();
    server.join().unwrap();
    let indices: Vec<usize> = output.ranked.iter().map(|entry| entry.index).collect();
    assert_eq!(indices, [0, 1, 2]);
    assert_eq!(output.ranked[0].score, 0.9);
    assert_eq!(output.cost_credits, Some(4.4e-07));
}

#[tokio::test]
async fn a_higher_score_outranks_a_lower_index() {
    let (url, server) = serve_once(Reply::ok(reply_body(
        "rerank-2.5-lite",
        &[(0, 0.2), (1, 0.7), (2, 0.4)],
    )));
    let output = call(
        &reranker(&url, Duration::from_secs(5)),
        &fused_candidates(3),
    )
    .await
    .unwrap();
    server.join().unwrap();
    let indices: Vec<usize> = output.ranked.iter().map(|entry| entry.index).collect();
    assert_eq!(indices, [1, 2, 0]);
}

#[tokio::test]
async fn a_reply_without_usage_reports_no_cost() {
    let mut body = reply_body("rerank-2.5-lite", &[(0, 0.9), (1, 0.1)]);
    body.as_object_mut().unwrap().remove("usage");
    let (url, server) = serve_once(Reply::ok(body));
    let output = call(
        &reranker(&url, Duration::from_secs(5)),
        &fused_candidates(2),
    )
    .await
    .unwrap();
    server.join().unwrap();
    assert_eq!(output.cost_credits, None);
}

#[tokio::test]
async fn the_reply_model_is_accepted_bare_full_or_dated_and_refused_otherwise() {
    for (model, accepted) in [
        (Some("rerank-2.5-lite"), true),
        (Some("voyageai/rerank-2.5-lite"), true),
        (Some("rerank-2.5-lite-20260101"), true),
        (Some("rerank-v3.5"), false),
        (Some("cohere/rerank-v3.5"), false),
        (Some(""), false),
        (None, false),
    ] {
        let mut body = reply_body("placeholder", &[(0, 0.9), (1, 0.1)]);
        match model {
            Some(model) => body["model"] = json!(model),
            None => {
                body.as_object_mut().unwrap().remove("model");
            }
        }
        let (url, server) = serve_once(Reply::ok(body));
        let result = call(
            &reranker(&url, Duration::from_secs(5)),
            &fused_candidates(2),
        )
        .await;
        server.join().unwrap();
        match (accepted, result) {
            (true, Ok(_)) => {}
            (false, Err(error)) if error.is_malformed() => {}
            (_, other) => panic!("model {model:?} (accepted: {accepted}) gave {other:?}"),
        }
    }
}

#[tokio::test]
async fn every_reply_that_is_not_a_ranking_of_all_documents_is_malformed() {
    let model = "rerank-2.5-lite";
    let non_finite = r#"{"model":"rerank-2.5-lite","results":[{"index":0,"relevance_score":1e999},{"index":1,"relevance_score":0.5},{"index":2,"relevance_score":0.1}]}"#;
    let cases = [
        (
            "duplicate index",
            reply_body(model, &[(0, 0.9), (0, 0.8), (2, 0.1)]).to_string(),
        ),
        (
            "index out of range",
            reply_body(model, &[(0, 0.9), (1, 0.8), (3, 0.1)]).to_string(),
        ),
        (
            "missing index",
            reply_body(model, &[(0, 0.9), (2, 0.1), (2, 0.1)]).to_string(),
        ),
        (
            "fewer results than documents",
            reply_body(model, &[(0, 0.9), (1, 0.8)]).to_string(),
        ),
        (
            "more results than documents",
            reply_body(model, &[(0, 0.9), (1, 0.8), (2, 0.7), (3, 0.6)]).to_string(),
        ),
        ("non-finite score", non_finite.to_owned()),
        ("not JSON", "<html>bad gateway</html>".to_owned()),
        ("results missing", json!({"model": model}).to_string()),
    ];
    for (label, body) in cases {
        let (url, server) = serve_once(Reply::status(200, body));
        let result = call(
            &reranker(&url, Duration::from_secs(5)),
            &fused_candidates(3),
        )
        .await;
        server.join().unwrap();
        let error = result.expect_err(label);
        assert!(error.is_malformed(), "{label}: {error:?}");
    }
}

#[tokio::test]
async fn each_listed_status_maps_to_a_status_error_with_that_code() {
    for code in [
        400_u16, 401, 402, 403, 404, 413, 429, 500, 502, 503, 524, 529,
    ] {
        let (url, server) = serve_once(Reply::status(
            code,
            format!("{{\"error\":\"{SENTINEL_KEY}\"}}"),
        ));
        let result = call(
            &reranker(&url, Duration::from_secs(5)),
            &fused_candidates(2),
        )
        .await;
        server.join().unwrap();
        let error = result.expect_err("a non-success status is an error");
        assert_eq!(error.status_code(), Some(code));
        assert!(!error.is_malformed() && !error.is_timeout() && !error.is_transport());
        assert_eq!(error.class(), format!("status {code}"));
    }
}

#[tokio::test]
async fn a_refused_connection_is_a_transport_error() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/api/v1/rerank", listener.local_addr().unwrap());
    drop(listener);
    // Connecting to a closed loopback port can take a second or two on Windows, so the limit is
    // well above that and the error must still be a refusal, not a timeout.
    let result = call(
        &reranker(&url, Duration::from_secs(10)),
        &fused_candidates(2),
    )
    .await;
    assert!(result.expect_err("nothing listens").is_transport());
}

#[tokio::test]
async fn a_reply_that_outlasts_the_call_limit_is_a_timeout() {
    let mut reply = Reply::ok(reply_body("rerank-2.5-lite", &[(0, 0.9), (1, 0.1)]));
    reply.delay = Duration::from_millis(800);
    let (url, server) = serve_once(reply);
    let result = call(
        &reranker(&url, Duration::from_millis(150)),
        &fused_candidates(2),
    )
    .await;
    server.join().unwrap();
    assert!(result.expect_err("too slow").is_timeout());
}

#[tokio::test]
async fn a_body_larger_than_the_cap_is_malformed() {
    let reply = Reply::status(200, "x".repeat(RERANK_MAX_BODY_BYTES + 1024));
    let (url, server) = serve_once(reply);
    let result = call(
        &reranker(&url, Duration::from_secs(5)),
        &fused_candidates(2),
    )
    .await;
    server.join().unwrap();
    assert!(result.expect_err("over the cap").is_malformed());
}

#[tokio::test]
async fn a_reply_between_the_default_cap_and_the_rerank_cap_is_read() {
    // The reply echoes every document, so it can pass the 256 KiB default; 1 MiB must still parse.
    let mut body = reply_body("rerank-2.5-lite", &[(0, 0.9), (1, 0.1)]);
    body["padding"] = json!("p".repeat(300 * 1024));
    let (url, server) = serve_once(Reply::ok(body));
    let output = call(
        &reranker(&url, Duration::from_secs(5)),
        &fused_candidates(2),
    )
    .await;
    server.join().unwrap();
    assert!(output.is_ok(), "{output:?}");
}

#[tokio::test]
async fn an_empty_candidate_list_returns_without_a_provider_call() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let url = format!("http://{}/api/v1/rerank", listener.local_addr().unwrap());
    let output = call(&reranker(&url, Duration::from_secs(5)), &[])
        .await
        .unwrap();
    assert!(output.ranked.is_empty());
    assert_eq!(output.cost_credits, None);
    let accepted = listener.accept();
    assert!(
        matches!(&accepted, Err(error) if error.kind() == std::io::ErrorKind::WouldBlock),
        "no request may reach the provider for an empty list: {accepted:?}"
    );
}

#[tokio::test]
async fn a_blank_query_is_refused_before_any_call() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let url = format!("http://{}/api/v1/rerank", listener.local_addr().unwrap());
    let candidates = fused_candidates(2);
    let error = reranker(&url, Duration::from_secs(5))
        .rerank(RerankRequest {
            query: "   ",
            candidates: &candidates,
        })
        .await
        .unwrap_err();
    assert!(error.is_invalid_request());
    assert!(listener.accept().is_err(), "no request may be sent");
}

#[test]
fn a_blank_key_or_a_blank_config_value_is_refused() {
    let timeout = Duration::from_secs(1);
    assert!(RerankConfig::new("", SLUG, timeout)
        .unwrap_err()
        .is_invalid_request());
    assert!(RerankConfig::new("http://x/y", "  ", timeout)
        .unwrap_err()
        .is_invalid_request());
    assert!(RerankConfig::new("http://x/y", SLUG, Duration::ZERO)
        .unwrap_err()
        .is_invalid_request());
    let config = RerankConfig::new("http://x/y", SLUG, timeout).unwrap();
    assert!(OpenRouterReranker::new("   ", config.clone())
        .unwrap_err()
        .is_invalid_request());
    assert!(OpenRouterReranker::new("", config)
        .unwrap_err()
        .is_invalid_request());
}

#[test]
fn the_error_phrases_carry_the_class_and_nothing_else() {
    for (error, class) in [
        (RerankError::timeout(), "timeout"),
        (RerankError::transport(), "transport"),
        (RerankError::malformed(), "malformed"),
        (RerankError::invalid_request(), "invalid request"),
        (RerankError::status(429), "status 429"),
    ] {
        assert_eq!(error.class(), class);
        assert_eq!(error.to_string(), format!("rerank failed: {class}"));
    }
}

#[derive(Clone, Default)]
struct LogBuffer(Arc<Mutex<Vec<u8>>>);

struct LogWriter(Arc<Mutex<Vec<u8>>>);

impl std::io::Write for LogWriter {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        self.0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

impl<'a> tracing_subscriber::fmt::MakeWriter<'a> for LogBuffer {
    type Writer = LogWriter;

    fn make_writer(&'a self) -> Self::Writer {
        LogWriter(Arc::clone(&self.0))
    }
}

impl LogBuffer {
    fn contents(&self) -> String {
        let bytes = self
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        String::from_utf8_lossy(&bytes).into_owned()
    }
}

#[tokio::test]
async fn the_key_never_appears_in_an_error_a_log_event_or_a_debug_rendering() {
    let logs = LogBuffer::default();
    let subscriber = tracing_subscriber::fmt()
        .with_writer(logs.clone())
        .with_max_level(tracing::Level::TRACE)
        .finish();
    let _guard = tracing::subscriber::set_default(subscriber);

    let mut renderings = Vec::new();
    // A provider refusal that echoes the key in its body, a malformed reply that does the same
    // and a transport failure: every error class a provider reply can produce.
    let (url, server) = serve_once(Reply::status(
        401,
        format!("{{\"error\":\"bad key {SENTINEL_KEY}\"}}"),
    ));
    let adapter = reranker(&url, Duration::from_secs(5));
    let error = call(&adapter, &fused_candidates(2)).await.unwrap_err();
    server.join().unwrap();
    renderings.push(format!("{error} | {error:?}"));

    let (url, server) = serve_once(Reply::status(200, format!("not json {SENTINEL_KEY}")));
    let error = call(
        &reranker(&url, Duration::from_secs(5)),
        &fused_candidates(2),
    )
    .await
    .unwrap_err();
    server.join().unwrap();
    renderings.push(format!("{error} | {error:?}"));

    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}/api/v1/rerank", listener.local_addr().unwrap());
    drop(listener);
    let error = call(
        &reranker(&url, Duration::from_secs(10)),
        &fused_candidates(2),
    )
    .await
    .unwrap_err();
    renderings.push(format!("{error} | {error:?}"));

    renderings.push(format!("{adapter:?}"));
    renderings.push(format!(
        "{:?}",
        RerankConfig::new(&url, SLUG, Duration::from_secs(1)).unwrap()
    ));

    for rendering in &renderings {
        assert!(
            !rendering.contains(SENTINEL_KEY) && !rendering.contains("bad key"),
            "a rendering leaked: {rendering}"
        );
    }
    let log_text = logs.contents();
    assert!(
        log_text.contains("rerank_call"),
        "each call must log one event: {log_text}"
    );
    assert!(
        !log_text.contains(SENTINEL_KEY),
        "the key must never reach a log event"
    );
}

#[test]
fn the_adapter_never_spawns_a_task() {
    let source = include_str!("openrouter.rs");
    for forbidden in ["tokio::spawn", "spawn_blocking", "JoinSet"] {
        assert!(
            !source.contains(forbidden),
            "the rerank call is awaited in place and never detached: found {forbidden}"
        );
    }
}

#[test]
fn the_rerank_defaults_agree_across_the_adapter_and_both_config_files() {
    for (name, raw) in [
        (
            "config/config.toml",
            include_str!("../../../config/config.toml"),
        ),
        (
            "config/config.example.toml",
            include_str!("../../../config/config.example.toml"),
        ),
    ] {
        let parsed = ::config::Config::builder()
            .add_source(::config::File::from_str(raw, ::config::FileFormat::Toml))
            .build()
            .expect("configuration file parses");
        assert_eq!(
            parsed
                .get::<String>("openrouter.rerank_endpoint")
                .ok()
                .as_deref(),
            Some(DEFAULT_RERANK_ENDPOINT),
            "{name} [openrouter] rerank_endpoint"
        );
        assert_eq!(
            parsed
                .get::<String>("openrouter.rerank_model")
                .ok()
                .as_deref(),
            Some(DEFAULT_RERANK_MODEL),
            "{name} [openrouter] rerank_model"
        );
    }
}
