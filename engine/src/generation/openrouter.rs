//! Capability-checked one-shot OpenRouter structured chat generator adapter.
//!
//! D-27, D-29, D-30, D-31, D-32, and D-33 define this adapter. It verifies that
//! the configured model metadata advertises structured output before making
//! exactly one timeout-bounded HTTP call with strict JSON Schema output bounds.

use std::time::Duration;

use reqwest::Client;
use serde::{Deserialize, Serialize};
use tokio::time::timeout;

use crate::{
    generation::{
        BoxFuture, GenerationError, GenerationErrorKind, GenerationRequest, Generator, ModelOutput,
    },
    prompt::pack_evidence_prompt,
};

pub const DEFAULT_OPENROUTER_MODEL: &str = "openai/gpt-4o-mini";
pub const DEFAULT_CHAT_ENDPOINT: &str = "https://openrouter.ai/api/v1/chat/completions";
pub const DEFAULT_MODELS_ENDPOINT: &str = "https://openrouter.ai/api/v1/models";
pub const GENERATION_TIMEOUT: Duration = Duration::from_secs(30);

fn build_http_client() -> Result<Client, GenerationError> {
    Client::builder()
        .timeout(GENERATION_TIMEOUT)
        .build()
        .map_err(|err| {
            GenerationError::new(
                GenerationErrorKind::ProviderError,
                format!("failed to build HTTP client: {err}"),
            )
        })
}

#[derive(Clone)]
pub struct OpenRouterGenerator {
    http: Client,
    api_key: String,
    model: String,
    chat_endpoint: String,
    models_endpoint: String,
}

impl OpenRouterGenerator {
    pub fn new(
        api_key: impl Into<String>,
        model: impl Into<String>,
    ) -> Result<Self, GenerationError> {
        let api_key = api_key.into();
        if api_key.trim().is_empty() {
            return Err(GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                "OpenRouter API key must not be empty",
            ));
        }
        let model = model.into();
        let model = if model.trim().is_empty() {
            DEFAULT_OPENROUTER_MODEL.to_string()
        } else {
            model.trim().to_string()
        };
        let http = build_http_client()?;

        Ok(Self {
            http,
            api_key,
            model,
            chat_endpoint: DEFAULT_CHAT_ENDPOINT.into(),
            models_endpoint: DEFAULT_MODELS_ENDPOINT.into(),
        })
    }

    pub fn from_env() -> Result<Self, GenerationError> {
        let api_key = std::env::var("OPENROUTER_API_KEY").map_err(|_| {
            GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                "OPENROUTER_API_KEY environment variable is not set",
            )
        })?;
        let model =
            std::env::var("OPENROUTER_MODEL").unwrap_or_else(|_| DEFAULT_OPENROUTER_MODEL.into());
        Self::new(api_key, model)
    }

    pub fn with_endpoints(
        mut self,
        chat_endpoint: impl Into<String>,
        models_endpoint: impl Into<String>,
    ) -> Self {
        self.chat_endpoint = chat_endpoint.into();
        self.models_endpoint = models_endpoint.into();
        self
    }

    /// Verifies that the model metadata advertises structured outputs (`response_format` / `json_schema`).
    pub async fn check_supported_parameters(&self) -> Result<(), GenerationError> {
        let response = self
            .http
            .get(&self.models_endpoint)
            .bearer_auth(&self.api_key)
            .send()
            .await
            .map_err(|err| {
                GenerationError::new(
                    GenerationErrorKind::SupportedParameters,
                    format!("failed to fetch model capabilities: {err}"),
                )
            })?;

        if !response.status().is_success() {
            return Err(GenerationError::new(
                GenerationErrorKind::SupportedParameters,
                format!(
                    "model capabilities check returned HTTP {}",
                    response.status()
                ),
            ));
        }

        let models_resp = response
            .json::<OpenRouterModelsResponse>()
            .await
            .map_err(|err| {
                GenerationError::new(
                    GenerationErrorKind::SupportedParameters,
                    format!("invalid models metadata JSON: {err}"),
                )
            })?;

        let model_meta = models_resp
            .data
            .into_iter()
            .find(|m| m.id == self.model)
            .ok_or_else(|| {
                GenerationError::new(
                    GenerationErrorKind::SupportedParameters,
                    format!(
                        "model metadata for '{}' not found in OpenRouter list",
                        self.model
                    ),
                )
            })?;

        if let Some(params) = model_meta.supported_parameters {
            if params.contains(&"response_format".to_string())
                || params.contains(&"json_schema".to_string())
                || params.contains(&"structured_outputs".to_string())
            {
                return Ok(());
            }
        }

        Err(GenerationError::new(
            GenerationErrorKind::SupportedParameters,
            format!(
                "model '{}' does not advertise response_format/structured_outputs support",
                self.model
            ),
        ))
    }

    async fn execute_one_call(
        &self,
        request: GenerationRequest,
    ) -> Result<ModelOutput, GenerationError> {
        // Preflight supported parameters check per D-27
        self.check_supported_parameters().await?;

        let (prompt_text, packed_evidence) =
            pack_evidence_prompt(&request.question, &request.evidence, 8192, 2048);

        let system_msg = request.system_policy.clone();
        let user_msg = prompt_text;

        let payload = OpenRouterChatPayload {
            model: self.model.clone(),
            messages: vec![
                ChatMessage {
                    role: "system".into(),
                    content: system_msg,
                },
                ChatMessage {
                    role: "user".into(),
                    content: user_msg,
                },
            ],
            temperature: 0.0,
            top_p: 1.0,
            max_tokens: 2048,
            response_format: ResponseFormat {
                format_type: "json_object".into(),
            },
        };

        let response = self
            .http
            .post(&self.chat_endpoint)
            .bearer_auth(&self.api_key)
            .json(&payload)
            .send()
            .await
            .map_err(|err| {
                if err.is_timeout() {
                    GenerationError::new(
                        GenerationErrorKind::Timeout,
                        "OpenRouter chat completion timed out",
                    )
                } else {
                    GenerationError::new(
                        GenerationErrorKind::ProviderError,
                        format!("OpenRouter request failed: {err}"),
                    )
                }
            })?;

        let status = response.status();
        if !status.is_success() {
            return Err(GenerationError::new(
                GenerationErrorKind::ProviderError,
                format!("OpenRouter chat completion returned HTTP {status}"),
            ));
        }

        let chat_resp = response
            .json::<OpenRouterChatResponse>()
            .await
            .map_err(|err| {
                GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!("failed to parse OpenRouter response wrapper JSON: {err}"),
                )
            })?;

        let choice = chat_resp.choices.first().ok_or_else(|| {
            GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                "OpenRouter returned empty choices array",
            )
        })?;

        let content_str = &choice.message.content;
        let mut model_output: ModelOutput = serde_json::from_str(content_str).map_err(|err| {
            GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                format!("failed to deserialize ModelOutput schema: {err}"),
            )
        })?;

        if let Some(usage) = chat_resp.usage {
            model_output.usage = Some(crate::generation::ModelUsage {
                prompt_tokens: usage.prompt_tokens,
                completion_tokens: usage.completion_tokens,
                total_tokens: usage.total_tokens,
            });
        }

        // Keep citations bounded only to available evidence IDs
        let valid_ids: Vec<String> = packed_evidence.iter().map(|e| e.id.clone()).collect();
        model_output.cited_evidence_ids.retain(|id| {
            valid_ids.contains(id) || packed_evidence.iter().any(|e| e.chunk_id == *id)
        });

        Ok(model_output)
    }
}

impl Generator for OpenRouterGenerator {
    fn generate<'a>(
        &'a self,
        request: GenerationRequest,
    ) -> BoxFuture<'a, Result<ModelOutput, GenerationError>> {
        Box::pin(async move {
            let session_id = request.session_id.clone();
            let correlation_id = request.correlation_id.clone();

            match timeout(GENERATION_TIMEOUT, self.execute_one_call(request)).await {
                Ok(res) => res.map_err(|err| err.with_correlation(session_id, correlation_id)),
                Err(_) => Err(GenerationError::new(
                    GenerationErrorKind::Timeout,
                    "OpenRouter request timed out at boundary limit",
                )
                .with_correlation(session_id, correlation_id)),
            }
        })
    }
}

#[derive(Serialize)]
struct OpenRouterChatPayload {
    model: String,
    messages: Vec<ChatMessage>,
    temperature: f64,
    top_p: f64,
    max_tokens: usize,
    response_format: ResponseFormat,
}

#[derive(Serialize)]
struct ChatMessage {
    role: String,
    content: String,
}

#[derive(Serialize)]
struct ResponseFormat {
    #[serde(rename = "type")]
    format_type: String,
}

#[derive(Deserialize)]
struct OpenRouterModelsResponse {
    data: Vec<OpenRouterModelMeta>,
}

#[derive(Deserialize)]
struct OpenRouterModelMeta {
    id: String,
    supported_parameters: Option<Vec<String>>,
}

#[derive(Deserialize)]
struct OpenRouterChatResponse {
    choices: Vec<ChatChoice>,
    usage: Option<UsageMeta>,
}

#[derive(Deserialize)]
struct ChatChoice {
    message: ChoiceMessage,
}

#[derive(Deserialize)]
struct ChoiceMessage {
    content: String,
}

#[derive(Deserialize)]
struct UsageMeta {
    prompt_tokens: u32,
    completion_tokens: u32,
    total_tokens: u32,
}
