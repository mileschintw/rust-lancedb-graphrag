//! Entity and relationship extraction traits, openrouter adapter, and test fakes.

use std::{
    sync::Arc,
    sync::atomic::{AtomicUsize, Ordering},
    sync::Mutex,
};

use reqwest::Client;
use serde::{Deserialize, Serialize};

use crate::generation::{
    openrouter::OpenRouterGenerationConfig, BoxFuture, GenerationError, GenerationErrorKind,
};

pub const MIN_CHUNK_CONTENT_LENGTH: usize = 40;

/// A request to extract entities and relationships from a single chunk.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExtractionRequest {
    pub chunk_id: String,
    pub document_id: String,
    pub chunk_text: String,
}

/// Extracted entities and relationships output.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExtractionOutput {
    pub entities: Vec<ExtractedEntity>,
    pub relations: Vec<ExtractedRelation>,
}

/// An entity extracted from text.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExtractedEntity {
    pub name: String,
    pub entity_type: String,
}

/// A relationship extracted between two entities in text.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExtractedRelation {
    pub source: String,
    pub target: String,
    pub relation_type: String,
    pub confidence: f32,
}

/// Trait for extracting knowledge graph entities and relationships.
pub trait ExtractionGenerator: Send + Sync {
    fn extract<'a>(
        &'a self,
        request: ExtractionRequest,
    ) -> BoxFuture<'a, Result<ExtractionOutput, GenerationError>>;
}

/// Validates an ExtractionOutput's relation confidences.
///
/// Returns `Err` if any relation confidence is non-finite or outside [0.0, 1.0].
pub(crate) fn validate_extraction_output(output: &ExtractionOutput) -> Result<(), String> {
    for rel in &output.relations {
        if !rel.confidence.is_finite() || rel.confidence < 0.0 || rel.confidence > 1.0 {
            tracing::debug!(
                confidence = rel.confidence as f64,
                "extraction output field-level validation failure: confidence out of range"
            );
            return Err(format!(
                "relation confidence {} is out of range [0.0, 1.0]",
                rel.confidence
            ));
        }
    }
    Ok(())
}

/// Executes an extraction request with bounded retry logic (up to 2 retries, 3 total attempts).
///
/// Implements AI-SPEC §4b.1's bounded retry contract for extraction calls.
/// Logs carry only chunk_id, document_id, attempt number, and error kind/reason —
/// NEVER the raw extracted text or model output (a deliberate, documented deviation
/// from AI-SPEC §4b.1's literal instruction, preserving T-04.1-07 and GraphSpikeError
/// no-row-values-in-logs discipline).
pub(crate) async fn extract_with_retry(
    generator: &dyn ExtractionGenerator,
    request: ExtractionRequest,
) -> Result<ExtractionOutput, GenerationError> {
    let mut attempt = 1;
    let max_attempts = 3;

    loop {
        match generator.extract(request.clone()).await {
            Ok(output) => match validate_extraction_output(&output) {
                Ok(()) => return Ok(output),
                Err(val_err) => {
                    tracing::warn!(
                        chunk_id = %request.chunk_id,
                        document_id = %request.document_id,
                        attempt,
                        reason = "confidence_out_of_range",
                        "extraction output validation failed"
                    );
                    if attempt >= max_attempts {
                        return Err(GenerationError::new(
                            GenerationErrorKind::SchemaValidation,
                            format!("extraction output failed validation after retries: {val_err}"),
                        ));
                    }
                }
            },
            Err(err) => {
                tracing::warn!(
                    chunk_id = %request.chunk_id,
                    document_id = %request.document_id,
                    attempt,
                    reason = %err,
                    "extraction call failed"
                );
                if attempt >= max_attempts {
                    return Err(err);
                }
            }
        }
        attempt += 1;
    }
}

/// OpenRouter implementation of ExtractionGenerator using structured outputs.
#[derive(Clone)]
pub struct OpenRouterExtractionGenerator {
    http: Client,
    api_key: String,
    config: OpenRouterGenerationConfig,
}

impl OpenRouterExtractionGenerator {
    pub fn new_with_config(
        api_key: impl Into<String>,
        config: OpenRouterGenerationConfig,
    ) -> Result<Self, GenerationError> {
        let api_key = api_key.into();
        if api_key.trim().is_empty() {
            return Err(GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                "OpenRouter API key must not be empty for extraction",
            ));
        }

        let http = Client::builder()
            .timeout(config.timeout())
            .build()
            .map_err(|err| {
                GenerationError::new(
                    GenerationErrorKind::ProviderError,
                    format!("failed to build HTTP client for extraction: {err}"),
                )
            })?;

        Ok(Self {
            http,
            api_key,
            config,
        })
    }
    pub(crate) fn build_request_payload(&self, chunk_text: &str) -> serde_json::Value {
        let system_msg = "You are an entity and relationship extraction engine. Extract key entities and relationships from the provided text block into the requested JSON schema. Do not extract trivial or stopword entities.";
        let user_msg = format!("Extract entities and relationships:\n\nText:\n{}", chunk_text);

        let schema_json = serde_json::json!({
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": { "type": "string", "maxLength": 128 },
                            "entity_type": { "type": "string", "maxLength": 64 }
                        },
                        "required": ["name", "entity_type"],
                        "additionalProperties": false
                    },
                    "maxItems": 32
                },
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": { "type": "string", "maxLength": 128 },
                            "target": { "type": "string", "maxLength": 128 },
                            "relation_type": { "type": "string", "maxLength": 64 },
                            "confidence": { "type": "number", "minimum": 0.0, "maximum": 1.0 }
                        },
                        "required": ["source", "target", "relation_type", "confidence"],
                        "additionalProperties": false
                    },
                    "maxItems": 64
                }
            },
            "required": ["entities", "relations"],
            "additionalProperties": false
        });

        serde_json::json!({
            "model": self.config.model(),
            "messages": [
                { "role": "system", "content": system_msg },
                { "role": "user", "content": user_msg }
            ],
            "temperature": self.config.temperature(),
            "top_p": self.config.top_p(),
            "max_completion_tokens": self.config.max_completion_tokens(),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "knowledge_graph_extraction",
                    "strict": true,
                    "schema": schema_json
                }
            }
        })
    }
}

impl ExtractionGenerator for OpenRouterExtractionGenerator {
    fn extract<'a>(
        &'a self,
        request: ExtractionRequest,
    ) -> BoxFuture<'a, Result<ExtractionOutput, GenerationError>> {
        Box::pin(async move {
            let payload = self.build_request_payload(&request.chunk_text);

            let response = self
                .http
                .post(self.config.chat_endpoint())
                .bearer_auth(&self.api_key)
                .json(&payload)
                .send()
                .await
                .map_err(|err| {
                    if err.is_timeout() {
                        GenerationError::new(
                            GenerationErrorKind::Timeout,
                            "OpenRouter extraction timed out",
                        )
                    } else {
                        GenerationError::new(
                            GenerationErrorKind::ProviderError,
                            format!("OpenRouter extraction request failed: {err}"),
                        )
                    }
                })?;

            if !response.status().is_success() {
                return Err(GenerationError::new(
                    GenerationErrorKind::ProviderError,
                    format!("OpenRouter extraction returned HTTP {}", response.status()),
                ));
            }

            let body_bytes = crate::client::read_body_limited(response)
                .await
                .map_err(|err| match err {
                    crate::client::BoundedBodyError::TooLarge => GenerationError::new(
                        GenerationErrorKind::SchemaValidation,
                        "OpenRouter extraction response body exceeds limit",
                    ),
                    crate::client::BoundedBodyError::Read(msg) => GenerationError::new(
                        GenerationErrorKind::ProviderError,
                        format!("failed to read OpenRouter extraction response body: {msg}"),
                    ),
                })?;

            let chat_resp: serde_json::Value = serde_json::from_slice(&body_bytes).map_err(|err| {
                GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!("failed to parse OpenRouter response wrapper JSON: {err}"),
                )
            })?;

            let content_str = chat_resp["choices"][0]["message"]["content"]
                .as_str()
                .ok_or_else(|| {
                    GenerationError::new(
                        GenerationErrorKind::SchemaValidation,
                        "missing choices[0].message.content in OpenRouter response",
                    )
                })?;

            let output: ExtractionOutput = serde_json::from_str(content_str).map_err(|err| {
                GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!("failed to deserialize ExtractionOutput schema: {err}"),
                )
            })?;

            Ok(output)
        })
    }
}

/// Fake extraction generator for unit tests.
pub struct FakeExtractionGenerator {
    pub call_count: AtomicUsize,
    pub responses: Mutex<Vec<Result<ExtractionOutput, GenerationError>>>,
    pub keyed_responses:
        Mutex<std::collections::HashMap<String, Result<ExtractionOutput, GenerationError>>>,
    pub current_in_flight: Arc<AtomicUsize>,
    pub max_in_flight: Arc<AtomicUsize>,
    pub delay: Option<std::time::Duration>,
}

impl FakeExtractionGenerator {
    pub fn new(response: Result<ExtractionOutput, GenerationError>) -> Self {
        Self {
            call_count: AtomicUsize::new(0),
            responses: Mutex::new(vec![response]),
            keyed_responses: Mutex::new(std::collections::HashMap::new()),
            current_in_flight: Arc::new(AtomicUsize::new(0)),
            max_in_flight: Arc::new(AtomicUsize::new(0)),
            delay: None,
        }
    }

    pub fn with_responses(responses: Vec<Result<ExtractionOutput, GenerationError>>) -> Self {
        Self {
            call_count: AtomicUsize::new(0),
            responses: Mutex::new(responses),
            keyed_responses: Mutex::new(std::collections::HashMap::new()),
            current_in_flight: Arc::new(AtomicUsize::new(0)),
            max_in_flight: Arc::new(AtomicUsize::new(0)),
            delay: None,
        }
    }

    pub fn with_keyed_responses(
        responses: std::collections::HashMap<String, Result<ExtractionOutput, GenerationError>>,
    ) -> Self {
        Self {
            call_count: AtomicUsize::new(0),
            responses: Mutex::new(vec![]),
            keyed_responses: Mutex::new(responses),
            current_in_flight: Arc::new(AtomicUsize::new(0)),
            max_in_flight: Arc::new(AtomicUsize::new(0)),
            delay: None,
        }
    }

    pub fn with_delay(mut self, delay: std::time::Duration) -> Self {
        self.delay = Some(delay);
        self
    }

    pub fn max_observed_concurrency(&self) -> usize {
        self.max_in_flight.load(Ordering::SeqCst)
    }

    pub fn calls(&self) -> usize {
        self.call_count.load(Ordering::Relaxed)
    }
}

impl ExtractionGenerator for FakeExtractionGenerator {
    fn extract<'a>(
        &'a self,
        request: ExtractionRequest,
    ) -> BoxFuture<'a, Result<ExtractionOutput, GenerationError>> {
        Box::pin(async move {
            self.call_count.fetch_add(1, Ordering::Relaxed);
            let now = self.current_in_flight.fetch_add(1, Ordering::SeqCst) + 1;
            self.max_in_flight.fetch_max(now, Ordering::SeqCst);

            if let Some(delay) = self.delay {
                if !delay.is_zero() {
                    tokio::time::sleep(delay).await;
                }
            }

            let res = {
                let mut keyed_guard = self.keyed_responses.lock().unwrap();
                if let Some(resp) = keyed_guard.remove(&request.chunk_id) {
                    resp
                } else {
                    let mut guard = self.responses.lock().unwrap();
                    if guard.len() == 1 {
                        guard[0].clone()
                    } else if guard.is_empty() {
                        Err(GenerationError::new(
                            GenerationErrorKind::ProviderError,
                            "FakeExtractionGenerator ran out of responses",
                        ))
                    } else {
                        guard.remove(0)
                    }
                }
            };

            self.current_in_flight.fetch_sub(1, Ordering::SeqCst);
            res
        })
    }
}
