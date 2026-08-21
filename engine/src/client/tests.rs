use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

use super::{OpenRouterClient, OpenRouterEmbeddingConfig};

struct MockServer {
    endpoint: String,
    requests: Arc<AtomicUsize>,
    max_active: Arc<AtomicUsize>,
    request_bodies: Arc<Mutex<Vec<String>>>,
}

impl MockServer {
    fn start(statuses: Vec<u16>, response_delay: Duration) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let endpoint = format!("http://{}/embeddings", listener.local_addr().unwrap());
        let requests = Arc::new(AtomicUsize::new(0));
        let active = Arc::new(AtomicUsize::new(0));
        let max_active = Arc::new(AtomicUsize::new(0));
        let request_bodies = Arc::new(Mutex::new(Vec::new()));
        let requests_for_thread = requests.clone();
        let max_for_thread = max_active.clone();
        let bodies_for_thread = request_bodies.clone();
        thread::spawn(move || {
            for connection in listener.incoming() {
                let Ok(mut stream) = connection else { break };
                let request_number = requests_for_thread.fetch_add(1, Ordering::SeqCst);
                let status = statuses
                    .get(request_number)
                    .copied()
                    .or_else(|| statuses.last().copied())
                    .unwrap_or(200);
                let active = active.clone();
                let max_active = max_for_thread.clone();
                let request_bodies = bodies_for_thread.clone();
                thread::spawn(move || {
                    let now_active = active.fetch_add(1, Ordering::SeqCst) + 1;
                    max_active.fetch_max(now_active, Ordering::SeqCst);
                    if let Some(body) = read_request(&mut stream) {
                        request_bodies.lock().unwrap().push(body);
                    }
                    thread::sleep(response_delay);
                    write_response(&mut stream, status);
                    active.fetch_sub(1, Ordering::SeqCst);
                });
            }
        });
        Self {
            endpoint,
            requests,
            max_active,
            request_bodies,
        }
    }
}

fn read_request(stream: &mut TcpStream) -> Option<String> {
    stream
        .set_read_timeout(Some(Duration::from_secs(1)))
        .unwrap();
    let mut request = Vec::new();
    let mut buffer = [0; 4096];
    while !request.windows(4).any(|window| window == b"\r\n\r\n") {
        let Ok(read) = stream.read(&mut buffer) else {
            return None;
        };
        if read == 0 {
            return None;
        }
        request.extend_from_slice(&buffer[..read]);
    }
    let header_end = request
        .windows(4)
        .position(|window| window == b"\r\n\r\n")?;
    let headers = String::from_utf8_lossy(&request[..header_end]);
    let content_length = headers
        .lines()
        .find_map(|line| {
            line.to_ascii_lowercase()
                .strip_prefix("content-length:")
                .map(str::trim)
                .and_then(|value| value.parse::<usize>().ok())
        })
        .unwrap_or(0);
    let body_start = header_end + 4;
    let mut body = request[body_start..].to_vec();
    let mut remaining = content_length.saturating_sub(body.len());
    while remaining > 0 {
        let read_len = remaining.min(buffer.len());
        let Ok(read) = stream.read(&mut buffer[..read_len]) else {
            return None;
        };
        if read == 0 {
            return None;
        }
        body.extend_from_slice(&buffer[..read]);
        remaining -= read;
    }
    String::from_utf8(body).ok()
}

fn write_response(stream: &mut TcpStream, status: u16) {
    let body = if status == 200 {
        let values = vec!["0.25"; 2048].join(",");
        format!(r#"{{"data":[{{"embedding":[{values}]}}]}}"#)
    } else {
        r#"{"error":"temporary"}"#.into()
    };
    let reason = if status == 200 {
        "OK"
    } else if status == 429 {
        "Too Many Requests"
    } else {
        "Server Error"
    };
    let response = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(response.as_bytes());
}

fn client(server: &MockServer, max_retries: u32) -> OpenRouterClient {
    OpenRouterClient::for_test(
        server.endpoint.clone(),
        max_retries,
        Duration::from_millis(1),
    )
}

#[tokio::test]
async fn production_client_times_out_at_locked_ten_seconds() {
    let server = MockServer::start(vec![200], Duration::from_secs(11));
    let started = Instant::now();
    let client = OpenRouterClient::for_test(server.endpoint.clone(), 0, Duration::ZERO);

    let error = client
        .get_embeddings(&["too slow for production".into()])
        .await
        .unwrap_err();
    let elapsed = started.elapsed();
    let error = error.to_ascii_lowercase();

    assert!(
        error.contains("timed out") || error.contains("timeout"),
        "expected a timeout error, got: {error}"
    );
    assert!(
        elapsed >= Duration::from_secs(9),
        "request returned before the locked timeout: {elapsed:?}"
    );
    assert!(
        elapsed < Duration::from_secs(15),
        "request exceeded the narrow timeout tolerance: {elapsed:?}"
    );
}

#[tokio::test]
async fn retries_rate_limits_and_server_errors() {
    let server = MockServer::start(vec![429, 500, 200], Duration::ZERO);
    let embeddings = client(&server, 3)
        .get_embeddings(&["retry me".into()])
        .await
        .unwrap();
    assert_eq!(server.requests.load(Ordering::SeqCst), 3);
    assert_eq!(embeddings[0].len(), 2048);
}

#[tokio::test]
async fn retries_server_errors_then_returns_error() {
    let server = MockServer::start(vec![500, 500, 500, 500], Duration::ZERO);
    let error = client(&server, 3)
        .get_embeddings(&["too slow".into()])
        .await
        .unwrap_err();
    assert!(error.contains("after 4 attempts"));
    assert_eq!(server.requests.load(Ordering::SeqCst), 4);
}

#[tokio::test]
async fn caps_parallel_embedding_requests_at_five() {
    let server = MockServer::start(vec![200], Duration::from_millis(30));
    let texts = (0..12)
        .map(|index| format!("text {index}"))
        .collect::<Vec<_>>();
    let embeddings = client(&server, 3).get_embeddings(&texts).await.unwrap();
    assert_eq!(embeddings.len(), texts.len());
    assert_eq!(server.max_active.load(Ordering::SeqCst), 5);
}

#[test]
fn rejects_empty_api_keys_without_exposing_credentials() {
    let error = match OpenRouterClient::new("  ") {
        Ok(_) => panic!("empty keys must be rejected"),
        Err(error) => error,
    };
    assert_eq!(error, "OpenRouter API key must not be empty");
}

#[tokio::test]
async fn client_embedding_endpoint_override() {
    let server = MockServer::start(vec![200], Duration::ZERO);
    let client = OpenRouterClient::for_test(server.endpoint.clone(), 0, Duration::ZERO);
    let embeddings = client
        .get_embeddings(&["test endpoint override".into()])
        .await
        .unwrap();
    assert_eq!(server.requests.load(Ordering::SeqCst), 1);
    assert_eq!(embeddings[0].len(), 2048);
}

#[tokio::test]
async fn embedding_request_uses_effective_model() {
    let server = MockServer::start(vec![200], Duration::ZERO);
    let model = "custom/embedding-model";
    let config = OpenRouterEmbeddingConfig::new(model, server.endpoint.clone()).unwrap();
    let client = OpenRouterClient::new_with_config("test-secret", config).unwrap();

    client
        .get_embeddings(&["configured model request".into()])
        .await
        .unwrap();

    assert_eq!(client.model_id(), model);
    let body = server
        .request_bodies
        .lock()
        .unwrap()
        .first()
        .cloned()
        .unwrap();
    let body: serde_json::Value = serde_json::from_str(&body).unwrap();
    assert_eq!(body["model"], model);
}

#[tokio::test]
async fn embedding_config_preserves_bounds_and_redaction() {
    let server = MockServer::start(vec![500, 500, 500, 500], Duration::ZERO);
    let config = OpenRouterEmbeddingConfig::new("custom/embedding-model", server.endpoint).unwrap();

    assert_eq!(config.timeout, Duration::from_secs(10));
    assert_eq!(config.max_retries, 3);
    assert_eq!(config.max_concurrency, 5);
    assert_eq!(config.expected_dimension, 2048);

    let secret = "secret-must-not-appear";
    let error = OpenRouterClient::new_with_config(secret, config)
        .unwrap()
        .get_embeddings(&["redaction".into()])
        .await
        .unwrap_err();
    assert!(
        !error.contains(secret),
        "provider error leaked the credential"
    );
}

#[tokio::test]
async fn bounded_provider_body_accepts_exact_limit() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    thread::spawn(move || {
        if let Ok((mut stream, _)) = listener.accept() {
            let mut buf = [0u8; 1024];
            let _ = stream.read(&mut buf);
            let body = vec![b'a'; 262144];
            let header = format!("HTTP/1.1 200 OK\r\nContent-Length: 262144\r\n\r\n");
            let _ = stream.write_all(header.as_bytes());
            let _ = stream.write_all(&body);
        }
    });

    let client = reqwest::Client::new();
    let resp = client.get(format!("http://{addr}")).send().await.unwrap();
    let bytes = super::read_body_limited(resp).await.unwrap();
    assert_eq!(bytes.len(), 262144);
}

#[tokio::test]
async fn bounded_provider_body_rejects_chunked_limit_plus_one() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    thread::spawn(move || {
        if let Ok((mut stream, _)) = listener.accept() {
            let mut buf = [0u8; 1024];
            let _ = stream.read(&mut buf);
            let header = "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n";
            let _ = stream.write_all(header.as_bytes());
            let chunk_data = vec![b'b'; 262145];
            let chunk_header = format!("{:x}\r\n", chunk_data.len());
            let _ = stream.write_all(chunk_header.as_bytes());
            let _ = stream.write_all(&chunk_data);
            let _ = stream.write_all(b"\r\n0\r\n\r\n");
        }
    });

    let client = reqwest::Client::new();
    let resp = client.get(format!("http://{addr}")).send().await.unwrap();
    let err = super::read_body_limited(resp).await.unwrap_err();
    assert!(matches!(err, super::BoundedBodyError::TooLarge));
}

#[tokio::test]
async fn embedding_client_rejects_oversized_streaming_body() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    thread::spawn(move || {
        if let Ok((mut stream, _)) = listener.accept() {
            let mut buf = [0u8; 1024];
            let _ = stream.read(&mut buf);
            let header = "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n";
            let _ = stream.write_all(header.as_bytes());
            let chunk_data = vec![b' '; 262145];
            let chunk_header = format!("{:x}\r\n", chunk_data.len());
            let _ = stream.write_all(chunk_header.as_bytes());
            let _ = stream.write_all(&chunk_data);
            let _ = stream.write_all(b"\r\n0\r\n\r\n");
        }
    });

    let endpoint = format!("http://{addr}/embeddings");
    let client = OpenRouterClient::for_test(endpoint, 0, Duration::ZERO);
    let err = client.get_embeddings(&["test".into()]).await.unwrap_err();
    assert!(
        err.contains("invalid embedding response"),
        "got error: {err}"
    );
}

#[tokio::test]
async fn read_body_limited_with_limit_accepts_payload_within_custom_limit() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    let payload_size = 512 * 1024; // 512 KB (exceeds default 256KB but within 10MB)
    thread::spawn(move || {
        if let Ok((mut stream, _)) = listener.accept() {
            let mut buf = [0u8; 1024];
            let _ = stream.read(&mut buf);
            let body = vec![b'x'; payload_size];
            let header = format!("HTTP/1.1 200 OK\r\nContent-Length: {payload_size}\r\n\r\n");
            let _ = stream.write_all(header.as_bytes());
            let _ = stream.write_all(&body);
        }
    });

    let client = reqwest::Client::new();
    let resp = client.get(format!("http://{addr}")).send().await.unwrap();
    let bytes = super::read_body_limited_with_limit(resp, super::MAX_MODELS_METADATA_BODY_BYTES)
        .await
        .unwrap();
    assert_eq!(bytes.len(), payload_size);
}

#[tokio::test]
async fn read_body_limited_with_limit_rejects_content_length_exceeding_custom_limit() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    let limit = 1024;
    thread::spawn(move || {
        if let Ok((mut stream, _)) = listener.accept() {
            let mut buf = [0u8; 1024];
            let _ = stream.read(&mut buf);
            let header = format!("HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n", limit + 1);
            let _ = stream.write_all(header.as_bytes());
        }
    });

    let client = reqwest::Client::new();
    let resp = client.get(format!("http://{addr}")).send().await.unwrap();
    let err = super::read_body_limited_with_limit(resp, limit)
        .await
        .unwrap_err();
    assert!(matches!(err, super::BoundedBodyError::TooLarge));
}

#[tokio::test]
async fn read_body_limited_with_limit_rejects_chunked_stream_exceeding_custom_limit() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    let limit = 1024;
    thread::spawn(move || {
        if let Ok((mut stream, _)) = listener.accept() {
            let mut buf = [0u8; 1024];
            let _ = stream.read(&mut buf);
            let header = "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n";
            let _ = stream.write_all(header.as_bytes());
            let chunk_data = vec![b'c'; limit + 1];
            let chunk_header = format!("{:x}\r\n", chunk_data.len());
            let _ = stream.write_all(chunk_header.as_bytes());
            let _ = stream.write_all(&chunk_data);
            let _ = stream.write_all(b"\r\n0\r\n\r\n");
        }
    });

    let client = reqwest::Client::new();
    let resp = client.get(format!("http://{addr}")).send().await.unwrap();
    let err = super::read_body_limited_with_limit(resp, limit)
        .await
        .unwrap_err();
    assert!(matches!(err, super::BoundedBodyError::TooLarge));
}
