use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    thread,
    time::Duration,
};

use super::OpenRouterClient;

struct MockServer {
    endpoint: String,
    requests: Arc<AtomicUsize>,
    max_active: Arc<AtomicUsize>,
}

impl MockServer {
    fn start(statuses: Vec<u16>, response_delay: Duration) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let endpoint = format!("http://{}/embeddings", listener.local_addr().unwrap());
        let requests = Arc::new(AtomicUsize::new(0));
        let active = Arc::new(AtomicUsize::new(0));
        let max_active = Arc::new(AtomicUsize::new(0));
        let requests_for_thread = requests.clone();
        let max_for_thread = max_active.clone();
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
                thread::spawn(move || {
                    let now_active = active.fetch_add(1, Ordering::SeqCst) + 1;
                    max_active.fetch_max(now_active, Ordering::SeqCst);
                    read_request(&mut stream);
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
        }
    }
}

fn read_request(stream: &mut TcpStream) {
    stream
        .set_read_timeout(Some(Duration::from_secs(1)))
        .unwrap();
    let mut request = Vec::new();
    let mut buffer = [0; 4096];
    while !request.windows(4).any(|window| window == b"\r\n\r\n") {
        let Ok(read) = stream.read(&mut buffer) else {
            return;
        };
        if read == 0 {
            return;
        }
        request.extend_from_slice(&buffer[..read]);
    }
    let headers = String::from_utf8_lossy(&request);
    let content_length = headers
        .lines()
        .find_map(|line| {
            line.to_ascii_lowercase()
                .strip_prefix("content-length:")
                .map(str::trim)
                .and_then(|value| value.parse::<usize>().ok())
        })
        .unwrap_or(0);
    let body_start = request
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .unwrap()
        + 4;
    let mut remaining = content_length.saturating_sub(request.len() - body_start);
    while remaining > 0 {
        let read_len = remaining.min(buffer.len());
        let Ok(read) = stream.read(&mut buffer[..read_len]) else {
            return;
        };
        if read == 0 {
            return;
        }
        remaining -= read;
    }
}

fn write_response(stream: &mut TcpStream, status: u16) {
    let body = if status == 200 {
        let values = std::iter::repeat("0.25")
            .take(2048)
            .collect::<Vec<_>>()
            .join(",");
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

fn client(server: &MockServer, timeout: Duration) -> OpenRouterClient {
    OpenRouterClient::for_test(server.endpoint.clone(), timeout, Duration::from_millis(1))
}

#[tokio::test]
async fn retries_rate_limits_and_server_errors() {
    let server = MockServer::start(vec![429, 500, 200], Duration::ZERO);
    let embeddings = client(&server, Duration::from_secs(1))
        .get_embeddings(&["retry me".into()])
        .await
        .unwrap();
    assert_eq!(server.requests.load(Ordering::SeqCst), 3);
    assert_eq!(embeddings[0].len(), 2048);
}

#[tokio::test]
async fn retries_timed_out_requests_then_returns_error() {
    let server = MockServer::start(vec![200], Duration::from_millis(50));
    let error = client(&server, Duration::from_millis(5))
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
    let embeddings = client(&server, Duration::from_secs(1))
        .get_embeddings(&texts)
        .await
        .unwrap();
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
