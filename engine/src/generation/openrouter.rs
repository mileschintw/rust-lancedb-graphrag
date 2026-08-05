//! Capability-checked one-shot OpenRouter structured chat generator adapter.
//!
//! D-27, D-29, D-30, D-31, D-32, and D-33 define this adapter. It verifies that
//! the configured model metadata advertises structured output before making
//! exactly one timeout-bounded HTTP call with strict JSON Schema output bounds.

use std::{sync::Arc, time::Duration};

use reqwest::Client;
use serde::{Deserialize, Serialize};
use tokio::time::timeout;

use crate::{
    generation::{
        BoxFuture, GenerationError, GenerationErrorKind, GenerationRequest, Generator,
        GroundingLimits, ModelOutput,
    },
    prompt::pack_evidence_prompt,
};

pub const DEFAULT_OPENROUTER_MODEL: &str = "openai/gpt-4o-mini";
pub const DEFAULT_CHAT_ENDPOINT: &str = "https://openrouter.ai/api/v1/chat/completions";
pub const DEFAULT_MODELS_ENDPOINT: &str = "https://openrouter.ai/api/v1/models";
pub const GENERATION_TIMEOUT: Duration = Duration::from_secs(30);
const DEFAULT_TEMPERATURE: f64 = 0.0;
const DEFAULT_TOP_P: f64 = 1.0;
const DEFAULT_MAX_COMPLETION_TOKENS: usize = 2048;

fn build_http_client(timeout: Duration) -> Result<Client, GenerationError> {
    Client::builder().timeout(timeout).build().map_err(|err| {
        GenerationError::new(
            GenerationErrorKind::ProviderError,
            format!("failed to build HTTP client: {err}"),
        )
    })
}

#[derive(Debug, Clone)]
pub struct OpenRouterGenerationConfig {
    model: String,
    chat_endpoint: String,
    models_endpoint: String,
    timeout: Duration,
    temperature: f64,
    top_p: f64,
    pub grounding_limits: Arc<GroundingLimits>,
}

impl OpenRouterGenerationConfig {
    pub fn new(
        model: impl Into<String>,
        chat_endpoint: impl Into<String>,
        models_endpoint: impl Into<String>,
        timeout: Duration,
        temperature: f64,
        top_p: f64,
        max_completion_tokens: usize,
        evidence_token_budget: usize,
    ) -> Result<Self, GenerationError> {
        let limits = GroundingLimits::new(
            u32::try_from(evidence_token_budget).map_err(|_| {
                GenerationError::new(
                    GenerationErrorKind::InvalidRequest,
                    "evidence_token_budget exceeds u32::MAX",
                )
            })?,
            u32::try_from(max_completion_tokens).map_err(|_| {
                GenerationError::new(
                    GenerationErrorKind::InvalidRequest,
                    "max_completion_tokens exceeds u32::MAX",
                )
            })?,
        )?;
        Self::from_effective_limits(
            model,
            chat_endpoint,
            models_endpoint,
            timeout,
            temperature,
            top_p,
            Arc::new(limits),
        )
    }

    pub fn from_effective_limits(
        model: impl Into<String>,
        chat_endpoint: impl Into<String>,
        models_endpoint: impl Into<String>,
        timeout: Duration,
        temperature: f64,
        top_p: f64,
        limits: Arc<GroundingLimits>,
    ) -> Result<Self, GenerationError> {
        let config = Self {
            model: model.into(),
            chat_endpoint: chat_endpoint.into(),
            models_endpoint: models_endpoint.into(),
            timeout,
            temperature,
            top_p,
            grounding_limits: limits,
        };
        config.validate()?;
        Ok(config)
    }

    pub fn with_grounding_limits(
        model: impl Into<String>,
        chat_endpoint: impl Into<String>,
        models_endpoint: impl Into<String>,
        timeout: Duration,
        temperature: f64,
        top_p: f64,
        limits: GroundingLimits,
    ) -> Result<Self, GenerationError> {
        Self::from_effective_limits(
            model,
            chat_endpoint,
            models_endpoint,
            timeout,
            temperature,
            top_p,
            Arc::new(limits),
        )
    }

    pub fn max_completion_tokens(&self) -> usize {
        self.grounding_limits.max_output_tokens() as usize
    }

    pub fn evidence_token_budget(&self) -> usize {
        self.grounding_limits.evidence_token_budget() as usize
    }

    fn validate(&self) -> Result<(), GenerationError> {
        if self.model.trim().is_empty() {
            return Err(GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                "OpenRouter generation model must not be empty",
            ));
        }
        if self.chat_endpoint.trim().is_empty() {
            return Err(GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                "OpenRouter chat endpoint must not be empty",
            ));
        }
        if self.models_endpoint.trim().is_empty() {
            return Err(GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                "OpenRouter models endpoint must not be empty",
            ));
        }
        if self.timeout.is_zero() {
            return Err(GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                "OpenRouter generation timeout must be greater than zero",
            ));
        }
        if !self.temperature.is_finite() || self.temperature < 0.0 || self.temperature > 2.0 {
            return Err(GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                "OpenRouter temperature must be finite and between 0.0 and 2.0",
            ));
        }
        if !self.top_p.is_finite() || self.top_p <= 0.0 || self.top_p > 1.0 {
            return Err(GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                "OpenRouter top_p must be finite and between 0.0 and 1.0",
            ));
        }
        Ok(())
    }
}

#[derive(Clone)]
pub struct OpenRouterGenerator {
    http: Client,
    api_key: String,
    config: OpenRouterGenerationConfig,
}

impl OpenRouterGenerator {
    pub fn new_with_config(
        api_key: impl Into<String>,
        config: OpenRouterGenerationConfig,
    ) -> Result<Self, GenerationError> {
        let api_key = api_key.into();
        if api_key.trim().is_empty() {
            return Err(GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                "OpenRouter API key must not be empty",
            ));
        }
        config.validate()?;
        let http = build_http_client(config.timeout)?;

        Ok(Self {
            http,
            api_key,
            config,
        })
    }

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
        let config = OpenRouterGenerationConfig::new(
            model,
            DEFAULT_CHAT_ENDPOINT,
            DEFAULT_MODELS_ENDPOINT,
            GENERATION_TIMEOUT,
            DEFAULT_TEMPERATURE,
            DEFAULT_TOP_P,
            DEFAULT_MAX_COMPLETION_TOKENS,
            crate::generation::DEFAULT_EVIDENCE_TOKEN_BUDGET as usize,
        )?;
        Self::new_with_config(api_key, config)
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

    pub fn from_env_with_config(
        config: OpenRouterGenerationConfig,
    ) -> Result<Self, GenerationError> {
        let api_key = std::env::var("OPENROUTER_API_KEY").map_err(|_| {
            GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                "OPENROUTER_API_KEY environment variable is not set",
            )
        })?;
        Self::new_with_config(api_key, config)
    }

    pub fn with_endpoints(
        mut self,
        chat_endpoint: impl Into<String>,
        models_endpoint: impl Into<String>,
    ) -> Self {
        self.config.chat_endpoint = chat_endpoint.into();
        self.config.models_endpoint = models_endpoint.into();
        self
    }

    /// Verifies that the model metadata advertises structured outputs (`response_format` / `json_schema`).
    pub async fn check_supported_parameters(&self) -> Result<(), GenerationError> {
        let response = self
            .http
            .get(&self.config.models_endpoint)
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

        let body_bytes =
            crate::client::read_body_limited(response)
                .await
                .map_err(|err| match err {
                    crate::client::BoundedBodyError::TooLarge => GenerationError::new(
                        GenerationErrorKind::SupportedParameters,
                        format!(
                            "model capabilities response exceeds maximum body limit of {} bytes",
                            crate::client::MAX_PROVIDER_RESPONSE_BODY_BYTES
                        ),
                    ),
                    crate::client::BoundedBodyError::Read(msg) => GenerationError::new(
                        GenerationErrorKind::SupportedParameters,
                        format!("failed to read model capabilities response body: {msg}"),
                    ),
                })?;

        let models_resp =
            serde_json::from_slice::<OpenRouterModelsResponse>(&body_bytes).map_err(|err| {
                GenerationError::new(
                    GenerationErrorKind::SupportedParameters,
                    format!("invalid models metadata JSON: {err}"),
                )
            })?;

        let model_meta = models_resp
            .data
            .into_iter()
            .find(|m| m.id == self.config.model)
            .ok_or_else(|| {
                GenerationError::new(
                    GenerationErrorKind::SupportedParameters,
                    format!(
                        "model metadata for '{}' not found in OpenRouter list",
                        self.config.model
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
                self.config.model
            ),
        ))
    }

    async fn execute_one_call(
        &self,
        request: GenerationRequest,
    ) -> Result<ModelOutput, GenerationError> {
        // Preflight supported parameters check per D-27
        self.check_supported_parameters().await?;

        let packed_evidence = pack_evidence_prompt(
            &request.question,
            &request.evidence,
            self.config.evidence_token_budget(),
            self.config.max_completion_tokens(),
        )
        .map_err(|err| {
            GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                format!("prompt assembly failed: {err}"),
            )
        })?;

        let system_msg = request.system_policy.clone();
        let user_msg = packed_evidence.prompt;

        let schema_json = serde_json::json!({
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "maxLength": crate::generation::MAX_ANSWER_CHARS
                },
                "cited_evidence_ids": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "maxLength": crate::generation::MAX_EVIDENCE_ID_CHARS
                    },
                    "maxItems": crate::generation::MAX_CITED_EVIDENCE_IDS
                },
                "answer_basis": {
                    "type": "string",
                    "enum": ["retrieval", "mixed"]
                },
                "notices": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "maxLength": crate::generation::MAX_NOTICE_WARNING_CHARS
                    },
                    "maxItems": crate::generation::MAX_NOTICES_WARNINGS_ITEMS
                },
                "warnings": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "maxLength": crate::generation::MAX_NOTICE_WARNING_CHARS
                    },
                    "maxItems": crate::generation::MAX_NOTICES_WARNINGS_ITEMS
                }
            },
            "required": ["answer", "cited_evidence_ids", "answer_basis", "notices", "warnings"],
            "additionalProperties": false
        });

        let payload = OpenRouterChatPayload {
            model: self.config.model.clone(),
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
            temperature: self.config.temperature,
            top_p: self.config.top_p,
            max_completion_tokens: self.config.max_completion_tokens(),
            response_format: ResponseFormat {
                format_type: "json_schema".into(),
                json_schema: JsonSchemaWrapper {
                    name: "model_output".into(),
                    strict: true,
                    schema: schema_json,
                },
            },
        };

        let response = self
            .http
            .post(&self.config.chat_endpoint)
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

        let body_bytes =
            crate::client::read_body_limited(response)
                .await
                .map_err(|err| match err {
                    crate::client::BoundedBodyError::TooLarge => GenerationError::new(
                        GenerationErrorKind::SchemaValidation,
                        format!(
                            "OpenRouter response body exceeds maximum body limit of {} bytes",
                            crate::client::MAX_PROVIDER_RESPONSE_BODY_BYTES
                        ),
                    ),
                    crate::client::BoundedBodyError::Read(msg) => GenerationError::new(
                        GenerationErrorKind::ProviderError,
                        format!("failed to read OpenRouter response body: {msg}"),
                    ),
                })?;

        let chat_resp: OpenRouterChatResponse =
            serde_json::from_slice(&body_bytes).map_err(|err| {
                GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!("failed to parse OpenRouter response wrapper JSON: {err}"),
                )
            })?;

        if chat_resp.choices.len() != 1 {
            return Err(GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                format!(
                    "OpenRouter must return exactly 1 choice, got {}",
                    chat_resp.choices.len()
                ),
            ));
        }

        let choice = &chat_resp.choices[0];

        match choice.finish_reason.as_deref() {
            Some("stop") => {}
            Some(other) => {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!("OpenRouter completion incomplete: finish_reason '{other}'"),
                ));
            }
            None => {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    "OpenRouter choice missing finish_reason",
                ));
            }
        }

        let content_str = &choice.message.content;
        let mut model_output: ModelOutput = serde_json::from_str(content_str).map_err(|err| {
            GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                format!("failed to deserialize ModelOutput schema: {err}"),
            )
        })?;

        if let Some(usage) = chat_resp.usage {
            let limits = &self.config.grounding_limits;
            if usage.prompt_tokens > limits.evidence_token_budget() {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!(
                        "OpenRouter prompt_tokens {} exceeds budget {}",
                        usage.prompt_tokens,
                        limits.evidence_token_budget()
                    ),
                ));
            }
            if usage.completion_tokens > limits.max_output_tokens() {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!(
                        "OpenRouter completion_tokens {} exceeds budget {}",
                        usage.completion_tokens,
                        limits.max_output_tokens()
                    ),
                ));
            }
            let checked_total = usage
                .prompt_tokens
                .checked_add(usage.completion_tokens)
                .ok_or_else(|| {
                    GenerationError::new(
                        GenerationErrorKind::SchemaValidation,
                        "OpenRouter token usage addition overflowed",
                    )
                })?;
            if usage.total_tokens > limits.total_tokens_ceiling()
                || usage.total_tokens < checked_total
            {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!(
                        "OpenRouter total_tokens {} exceeds budget limit {}",
                        usage.total_tokens,
                        limits.total_tokens_ceiling()
                    ),
                ));
            }

            model_output.usage = Some(crate::generation::ModelUsage {
                prompt_tokens: usage.prompt_tokens,
                completion_tokens: usage.completion_tokens,
                total_tokens: usage.total_tokens,
            });
        }

        // Validate semantic grounding against packed evidence IDs per D-17, D-22, D-28
        model_output.validate_grounding_with_limits(
            &packed_evidence.evidence,
            *self.config.grounding_limits,
        )?;

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

            match timeout(self.config.timeout, self.execute_one_call(request)).await {
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
    max_completion_tokens: usize,
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
    json_schema: JsonSchemaWrapper,
}

#[derive(Serialize)]
struct JsonSchemaWrapper {
    name: String,
    strict: bool,
    schema: serde_json::Value,
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
    finish_reason: Option<String>,
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
