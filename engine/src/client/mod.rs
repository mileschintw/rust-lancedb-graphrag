use std::time::Duration;

use futures::{stream, StreamExt, TryStreamExt};
use reqwest::{Client, StatusCode};
use serde::{Deserialize, Serialize};

const OPENROUTER_EMBEDDINGS_URL: &str = "https://openrouter.ai/api/v1/embeddings";
const EMBEDDING_MODEL: &str = "nvidia/llama-nemotron-embed-vl-1b-v2:free";
const MAX_CONCURRENCY: usize = 5;
const MAX_RETRIES: u32 = 3;
const INITIAL_BACKOFF: Duration = Duration::from_secs(1);

#[derive(Clone)]
pub struct OpenRouterClient {
    http: Client,
    api_key: String,
    endpoint: String,
    max_retries: u32,
    initial_backoff: Duration,
}

#[derive(Serialize)]
struct EmbeddingRequest<'a> {
    model: &'static str,
    input: [&'a str; 1],
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
    pub fn new(api_key: impl Into<String>) -> Result<Self, String> {
        let api_key = api_key.into();
        if api_key.trim().is_empty() {
            return Err("OpenRouter API key must not be empty".into());
        }
        let http = Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(|error| format!("failed to build OpenRouter HTTP client: {error}"))?;
        Ok(Self {
            http,
            api_key,
            endpoint: OPENROUTER_EMBEDDINGS_URL.into(),
            max_retries: MAX_RETRIES,
            initial_backoff: INITIAL_BACKOFF,
        })
    }

    pub fn from_env() -> Result<Self, String> {
        let api_key = std::env::var("OPENROUTER_API_KEY")
            .map_err(|_| "OPENROUTER_API_KEY is not configured".to_string())?;
        Self::new(api_key)
    }

    #[cfg(test)]
    fn for_test(endpoint: String, timeout: Duration, initial_backoff: Duration) -> Self {
        Self {
            http: Client::builder().timeout(timeout).build().unwrap(),
            api_key: "test-key".into(),
            endpoint,
            max_retries: MAX_RETRIES,
            initial_backoff,
        }
    }

    pub async fn get_embeddings(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, String> {
        let mut indexed = stream::iter(texts.iter().enumerate().map(|(index, text)| async move {
            self.embed_with_retry(text)
                .await
                .map(|embedding| (index, embedding))
        }))
        .buffer_unordered(MAX_CONCURRENCY)
        .try_collect::<Vec<_>>()
        .await?;
        indexed.sort_unstable_by_key(|(index, _)| *index);
        Ok(indexed
            .into_iter()
            .map(|(_, embedding)| embedding)
            .collect())
    }

    async fn embed_with_retry(&self, text: &str) -> Result<Vec<f32>, String> {
        let mut delay = self.initial_backoff;
        for attempt in 0..=self.max_retries {
            match self.send_embedding(text).await {
                Ok(embedding) => return Ok(embedding),
                Err(RequestFailure::Permanent(message)) => return Err(message),
                Err(RequestFailure::Retryable(message)) if attempt == self.max_retries => {
                    return Err(format!(
                        "OpenRouter embedding request failed after {} attempts: {message}",
                        self.max_retries + 1
                    ));
                }
                Err(RequestFailure::Retryable(_)) => {
                    tokio::time::sleep(delay).await;
                    delay = delay.saturating_mul(2);
                }
            }
        }
        unreachable!("retry loop always returns")
    }

    async fn send_embedding(&self, text: &str) -> Result<Vec<f32>, RequestFailure> {
        let response = self
            .http
            .post(&self.endpoint)
            .bearer_auth(&self.api_key)
            .json(&EmbeddingRequest {
                model: EMBEDDING_MODEL,
                input: [text],
            })
            .send()
            .await
            .map_err(|error| RequestFailure::Retryable(error.to_string()))?;
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
        let mut data = response
            .json::<EmbeddingResponse>()
            .await
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
        if embedding.len() != 2048 {
            return Err(RequestFailure::Permanent(format!(
                "OpenRouter returned embedding dimension {}, expected 2048",
                embedding.len()
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
