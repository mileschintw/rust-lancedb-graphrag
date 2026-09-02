use std::time::Duration;

use futures::{stream, StreamExt, TryStreamExt};
use reqwest::{Client, StatusCode};
use serde::{Deserialize, Serialize};

const OPENROUTER_EMBEDDINGS_URL: &str = "https://openrouter.ai/api/v1/embeddings";
pub const EMBEDDING_MODEL: &str = "voyageai/voyage-4-large";
const EMBEDDING_DIMENSION: usize = 2048;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(45);
pub const DEFAULT_EMBEDDING_CONCURRENCY: usize = 12;
const MAX_CONCURRENCY: usize = DEFAULT_EMBEDDING_CONCURRENCY;
const MAX_RETRIES: u32 = 6;
const INITIAL_BACKOFF: Duration = Duration::from_secs(2);

pub const MAX_PROVIDER_RESPONSE_BODY_BYTES: usize = 256 * 1024;
pub const MAX_MODELS_METADATA_BODY_BYTES: usize = 10 * 1024 * 1024;

#[derive(Debug)]
pub enum BoundedBodyError {
    TooLarge,
    Read(String),
}

impl std::fmt::Display for BoundedBodyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::TooLarge => write!(
                f,
                "provider response exceeded maximum body limit of {MAX_PROVIDER_RESPONSE_BODY_BYTES} bytes"
            ),
            Self::Read(err) => write!(f, "failed to read provider response body: {err}"),
        }
    }
}

impl std::error::Error for BoundedBodyError {}

pub async fn read_body_limited(response: reqwest::Response) -> Result<Vec<u8>, BoundedBodyError> {
    read_body_limited_with_limit(response, MAX_PROVIDER_RESPONSE_BODY_BYTES).await
}

pub async fn read_body_limited_with_limit(
    mut response: reqwest::Response,
    max_bytes: usize,
) -> Result<Vec<u8>, BoundedBodyError> {
    if let Some(content_length) = response.content_length() {
        if content_length > max_bytes as u64 {
            return Err(BoundedBodyError::TooLarge);
        }
    }

    let mut buffer = Vec::new();

    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|err| BoundedBodyError::Read(err.to_string()))?
    {
        if buffer.len() + chunk.len() > max_bytes {
            return Err(BoundedBodyError::TooLarge);
        }
        buffer.extend_from_slice(&chunk);
    }

    Ok(buffer)
}

fn build_http_client(timeout: Duration) -> Result<Client, reqwest::Error> {
    Client::builder().timeout(timeout).build()
}

#[derive(Debug, Clone)]
pub struct OpenRouterEmbeddingConfig {
    pub model: String,
    pub endpoint: String,
    pub timeout: Duration,
    pub max_retries: u32,
    pub max_concurrency: usize,
    pub expected_dimension: usize,
}

impl OpenRouterEmbeddingConfig {
    pub fn new(model: impl Into<String>, endpoint: impl Into<String>) -> Result<Self, String> {
        let config = Self {
            model: model.into(),
            endpoint: endpoint.into(),
            timeout: REQUEST_TIMEOUT,
            max_retries: MAX_RETRIES,
            max_concurrency: MAX_CONCURRENCY,
            expected_dimension: EMBEDDING_DIMENSION,
        };
        config.validate()?;
        Ok(config)
    }

    pub fn new_with_concurrency(
        model: impl Into<String>,
        endpoint: impl Into<String>,
        max_concurrency: usize,
    ) -> Result<Self, String> {
        let mut config = Self::new(model, endpoint)?;
        config.max_concurrency = max_concurrency;
        config.validate()?;
        Ok(config)
    }

    fn validate(&self) -> Result<(), String> {
        if self.model.trim().is_empty() {
            return Err("OpenRouter embedding model must not be empty".into());
        }
        if self.endpoint.trim().is_empty() {
            return Err("OpenRouter embedding endpoint must not be empty".into());
        }
        if self.timeout.is_zero() {
            return Err("OpenRouter embedding timeout must be greater than zero".into());
        }
        if self.max_concurrency == 0 {
            return Err("OpenRouter embedding concurrency must be greater than zero".into());
        }
        if self.expected_dimension == 0 {
            return Err("OpenRouter embedding dimension must be greater than zero".into());
        }
        Ok(())
    }
}

#[derive(Clone)]
pub struct OpenRouterClient {
    http: Client,
    api_key: String,
    config: OpenRouterEmbeddingConfig,
    initial_backoff: Duration,
}

#[derive(Serialize)]
struct EmbeddingRequest<'a> {
    model: &'a str,
    input: [&'a str; 1],
    dimensions: usize,
}

#[derive(Deserialize)]
struct EmbeddingResponse {
    data: Vec<EmbeddingData>,
}

#[derive(Deserialize)]
struct EmbeddingData {
    embedding: Vec<f32>,
}

impl OpenRouterClient {
    pub fn new_with_config(
        api_key: impl Into<String>,
        config: OpenRouterEmbeddingConfig,
    ) -> Result<Self, String> {
        let api_key = api_key.into();
        if api_key.trim().is_empty() {
            return Err("OpenRouter API key must not be empty".into());
        }
        config.validate()?;
        let http = build_http_client(config.timeout)
            .map_err(|error| format!("failed to build OpenRouter HTTP client: {error}"))?;
        Ok(Self {
            http,
            api_key,
            config,
            initial_backoff: INITIAL_BACKOFF,
        })
    }

    pub fn new_with_endpoint(
        api_key: impl Into<String>,
        endpoint: impl Into<String>,
    ) -> Result<Self, String> {
        let config = OpenRouterEmbeddingConfig::new(EMBEDDING_MODEL, endpoint)?;
        Self::new_with_config(api_key, config)
    }

    pub fn new(api_key: impl Into<String>) -> Result<Self, String> {
        Self::new_with_endpoint(api_key, OPENROUTER_EMBEDDINGS_URL)
    }

    pub fn from_env() -> Result<Self, String> {
        let api_key = std::env::var("OPENROUTER_API_KEY")
            .map_err(|_| "OPENROUTER_API_KEY is not configured".to_string())?;
        Self::new(api_key)
    }

    pub fn from_env_with_endpoint(endpoint: impl Into<String>) -> Result<Self, String> {
        let api_key = std::env::var("OPENROUTER_API_KEY")
            .map_err(|_| "OPENROUTER_API_KEY is not configured".to_string())?;
        Self::new_with_endpoint(api_key, endpoint)
    }

    pub fn from_env_with_config(config: OpenRouterEmbeddingConfig) -> Result<Self, String> {
        let api_key = std::env::var("OPENROUTER_API_KEY")
            .map_err(|_| "OPENROUTER_API_KEY is not configured".to_string())?;
        Self::new_with_config(api_key, config)
    }

    pub fn model_id(&self) -> &str {
        &self.config.model
    }

    #[cfg(test)]
    fn for_test(endpoint: String, max_retries: u32, initial_backoff: Duration) -> Self {
        let config = OpenRouterEmbeddingConfig {
            model: EMBEDDING_MODEL.to_owned(),
            endpoint,
            timeout: REQUEST_TIMEOUT,
            max_retries,
            max_concurrency: MAX_CONCURRENCY,
            expected_dimension: EMBEDDING_DIMENSION,
        };
        Self {
            http: build_http_client(config.timeout).unwrap(),
            api_key: "test-key".into(),
            config,
            initial_backoff,
        }
    }

    pub async fn get_embeddings(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, String> {
        let client = self.clone();
        let mut indexed =
            stream::iter(texts.iter().cloned().enumerate().map(move |(index, text)| {
                let client = client.clone();
                async move {
                    client
                        .embed_with_retry(&text)
                        .await
                        .map(|embedding| (index, embedding))
                }
            }))
            .buffer_unordered(self.config.max_concurrency)
            .try_collect::<Vec<_>>()
            .await?;
        indexed.sort_unstable_by_key(|(index, _)| *index);
        Ok(indexed
            .into_iter()
            .map(|(_, embedding)| embedding)
            .collect())
    }

    async fn embed_with_retry(&self, text: &str) -> Result<Vec<f32>, String> {
        let trimmed = text.trim();
        if trimmed.is_empty() {
            return Ok(vec![0.0; self.config.expected_dimension]);
        }
        let mut delay = self.initial_backoff;
        for attempt in 0..=self.config.max_retries {
            match self.send_embedding(text).await {
                Ok(embedding) => return Ok(embedding),
                Err(RequestFailure::Permanent(message)) => return Err(message),
                Err(RequestFailure::Retryable(message)) if attempt == self.config.max_retries => {
                    return Err(format!(
                        "OpenRouter embedding request failed after {} attempts: {message}",
                        self.config.max_retries + 1
                    ));
                }
                Err(RequestFailure::Retryable(_)) => {
                    tokio::time::sleep(delay).await;
                    delay = delay.saturating_mul(2).min(Duration::from_secs(30));
                }
            }
        }
        unreachable!("retry loop always returns")
    }

    async fn send_embedding(&self, text: &str) -> Result<Vec<f32>, RequestFailure> {
        let response = self
            .http
            .post(&self.config.endpoint)
            .bearer_auth(&self.api_key)
            .json(&EmbeddingRequest {
                model: &self.config.model,
                input: [text],
                dimensions: self.config.expected_dimension,
            })
            .send()
            .await
            .map_err(|error| {
                let message = if error.is_timeout() {
                    "OpenRouter request timed out".to_string()
                } else {
                    error.to_string()
                };
                RequestFailure::Retryable(message)
            })?;
        let status = response.status();
        if status == StatusCode::TOO_MANY_REQUESTS || status.is_server_error() {
            return Err(RequestFailure::Retryable(format!(
                "OpenRouter returned HTTP {status}"
            )));
        }
        if !status.is_success() {
            return Err(RequestFailure::Permanent(format!(
                "OpenRouter returned HTTP {status}"
            )));
        }
        let body_bytes = read_body_limited(response).await.map_err(|err| match err {
            BoundedBodyError::TooLarge => {
                RequestFailure::Permanent(format!("invalid embedding response: {err}"))
            }
            BoundedBodyError::Read(msg) => {
                RequestFailure::Retryable(format!("failed to read embedding response: {msg}"))
            }
        })?;
        let mut data = serde_json::from_slice::<EmbeddingResponse>(&body_bytes)
            .map_err(|error| {
                RequestFailure::Permanent(format!("invalid embedding response: {error}"))
            })?
            .data;
        if data.len() != 1 {
            return Err(RequestFailure::Permanent(format!(
                "OpenRouter returned {} embeddings for one input",
                data.len()
            )));
        }
        let embedding = data.remove(0).embedding;
        if embedding.len() != self.config.expected_dimension {
            return Err(RequestFailure::Permanent(format!(
                "OpenRouter returned embedding dimension {}, expected {}",
                embedding.len(),
                self.config.expected_dimension
            )));
        }
        Ok(embedding)
    }
}

enum RequestFailure {
    Retryable(String),
    Permanent(String),
}

#[cfg(test)]
mod tests;
