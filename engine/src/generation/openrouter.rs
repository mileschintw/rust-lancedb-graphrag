//! Capability-checked one-shot OpenRouter structured chat generator adapter.
//!
//! D-27, D-29, D-30, D-31, D-32, and D-33 define this adapter. It verifies that
//! the configured model metadata advertises structured output before making
//! exactly one timeout-bounded HTTP call with strict JSON Schema output bounds.

use std::{collections::HashMap, sync::Arc, time::Duration};

use reqwest::Client;
use serde::{Deserialize, Serialize};
use tokio::time::timeout;

use crate::{
    generation::{
        BoxFuture, GenerationError, GenerationErrorKind, GenerationRequest, Generator,
        GroundingLimits, ModelOutput,
    },
    prompt::pack_evidence_and_graph_prompt,
};

pub const DEFAULT_OPENROUTER_MODEL: &str = "openai/gpt-4o-mini";
pub const DEFAULT_CHAT_ENDPOINT: &str = "https://openrouter.ai/api/v1/chat/completions";
pub const DEFAULT_MODELS_ENDPOINT: &str = "https://openrouter.ai/api/v1/models";
pub const GENERATION_TIMEOUT: Duration = Duration::from_secs(30);
pub const DEFAULT_PREFLIGHT_TIMEOUT: Duration = Duration::from_secs(5);
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

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct CapabilityKey {
    pub models_endpoint: String,
    pub model: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ModelCapabilities {
    pub supports_structured_outputs: bool,
}

#[derive(Debug, Clone)]
pub struct OpenRouterGenerationConfig {
    model: String,
    chat_endpoint: String,
    models_endpoint: String,
    timeout: Duration,
    preflight_timeout: Duration,
    temperature: f64,
    top_p: f64,
    pub grounding_limits: Arc<GroundingLimits>,
}

impl OpenRouterGenerationConfig {
    #[allow(clippy::too_many_arguments)]
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
            preflight_timeout: DEFAULT_PREFLIGHT_TIMEOUT,
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

    pub fn with_preflight_timeout(mut self, timeout: Duration) -> Self {
        self.preflight_timeout = timeout;
        self
    }

    pub fn preflight_timeout(&self) -> Duration {
        self.preflight_timeout
    }

    pub fn max_completion_tokens(&self) -> usize {
        self.grounding_limits.max_output_tokens() as usize
    }

    pub fn evidence_token_budget(&self) -> usize {
        self.grounding_limits.evidence_token_budget() as usize
    }

    pub fn model(&self) -> &str {
        &self.model
    }

    pub fn chat_endpoint(&self) -> &str {
        &self.chat_endpoint
    }

    pub fn models_endpoint(&self) -> &str {
        &self.models_endpoint
    }

    pub fn timeout(&self) -> Duration {
        self.timeout
    }

    pub fn temperature(&self) -> f64 {
        self.temperature
    }

    pub fn top_p(&self) -> f64 {
        self.top_p
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
        if self.preflight_timeout.is_zero() {
            return Err(GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                "OpenRouter preflight timeout must be greater than zero",
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
    capabilities_cache: Arc<
        tokio::sync::Mutex<HashMap<CapabilityKey, Arc<tokio::sync::OnceCell<ModelCapabilities>>>>,
    >,
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
            capabilities_cache: Arc::new(tokio::sync::Mutex::new(HashMap::new())),
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

    pub fn with_preflight_timeout(mut self, timeout: Duration) -> Self {
        self.config.preflight_timeout = timeout;
        self
    }

    pub async fn prepare(&self) -> Result<(), GenerationError> {
        self.check_supported_parameters().await
    }

    /// Verifies that the model metadata advertises structured outputs (`response_format` / `json_schema`).
    /// Uses the single-flight successful-only cache keyed by `(models_endpoint, model)`.
    pub async fn check_supported_parameters(&self) -> Result<(), GenerationError> {
        let key = CapabilityKey {
            models_endpoint: self.config.models_endpoint.clone(),
            model: self.config.model.clone(),
        };

        let cell = {
            let mut cache = self.capabilities_cache.lock().await;
            cache
                .entry(key)
                .or_insert_with(|| Arc::new(tokio::sync::OnceCell::new()))
                .clone()
        };

        let _caps = cell
            .get_or_try_init(|| async { self.fetch_and_validate_capabilities().await })
            .await?;

        Ok(())
    }

    async fn fetch_and_validate_capabilities(&self) -> Result<ModelCapabilities, GenerationError> {
        let preflight_fut = async {
            let response = self
                .http
                .get(&self.config.models_endpoint)
                .bearer_auth(&self.api_key)
                .send()
                .await
                .map_err(|err| {
                    GenerationError::new(
                        GenerationErrorKind::ProviderError,
                        format!("failed to fetch model capabilities: {err}"),
                    )
                })?;

            let status = response.status();
            if !status.is_success() {
                let kind = if status.is_server_error() {
                    GenerationErrorKind::ProviderError
                } else {
                    GenerationErrorKind::SupportedParameters
                };
                return Err(GenerationError::new(
                    kind,
                    format!("model capabilities check returned HTTP {status}"),
                ));
            }

            let body_bytes = crate::client::read_body_limited_with_limit(
                response,
                crate::client::MAX_MODELS_METADATA_BODY_BYTES,
            )
            .await
            .map_err(|err| match err {
                crate::client::BoundedBodyError::TooLarge => GenerationError::new(
                    GenerationErrorKind::SupportedParameters,
                    format!(
                        "model capabilities response exceeds maximum body limit of {} bytes",
                        crate::client::MAX_MODELS_METADATA_BODY_BYTES
                    ),
                ),
                crate::client::BoundedBodyError::Read(msg) => GenerationError::new(
                    GenerationErrorKind::ProviderError,
                    format!("failed to read model capabilities response body: {msg}"),
                ),
            })?;

            let models_resp = serde_json::from_slice::<OpenRouterModelsResponse>(&body_bytes)
                .map_err(|err| {
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
                    return Ok(ModelCapabilities {
                        supports_structured_outputs: true,
                    });
                }
            }

            Err(GenerationError::new(
                GenerationErrorKind::SupportedParameters,
                format!(
                    "model '{}' does not advertise response_format/structured_outputs support",
                    self.config.model
                ),
            ))
        };

        match timeout(self.config.preflight_timeout, preflight_fut).await {
            Ok(res) => res,
            Err(_) => Err(GenerationError::new(
                GenerationErrorKind::ProviderError,
                format!(
                    "model capabilities check timed out after {:?}",
                    self.config.preflight_timeout
                ),
            )),
        }
    }

    async fn execute_one_call(
        &self,
        request: GenerationRequest,
    ) -> Result<ModelOutput, GenerationError> {
        let cancel = request.cancel.clone().unwrap_or_default();
        if cancel.is_cancelled() {
            return Err(GenerationError::new(
                GenerationErrorKind::Cancelled,
                "OpenRouter request cancelled before prompt assembly",
            ));
        }

        // This is the call site whose packed prompt becomes the real outbound
        // `messages[1].content` — it reads `request.graph_facts` and
        // `request.graph_weight` from the request it was actually handed, not a
        // separately-derived value, so a configured graph_weight provably
        // reaches the wire (REVIEWS.md HIGH).
        let packed_evidence = pack_evidence_and_graph_prompt(
            &request.question,
            &request.evidence,
            &request.graph_facts,
            request.graph_weight,
            self.config.evidence_token_budget(),
            self.config.max_completion_tokens(),
            &cancel,
        )
        .await
        .map_err(|err| match err {
            crate::prompt::PromptAssemblyError::Cancelled => {
                GenerationError::new(GenerationErrorKind::Cancelled, "prompt assembly cancelled")
            }
            _ => GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                format!("prompt assembly failed: {err}"),
            ),
        })?;

        if cancel.is_cancelled() {
            return Err(GenerationError::new(
                GenerationErrorKind::Cancelled,
                "OpenRouter request cancelled after prompt assembly",
            ));
        }

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

        let send_fut = self
            .http
            .post(&self.config.chat_endpoint)
            .bearer_auth(&self.api_key)
            .json(&payload)
            .send();

        let response = tokio::select! {
            res = send_fut => res.map_err(|err| {
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
            })?,
            _ = cancel.cancelled() => {
                return Err(GenerationError::new(
                    GenerationErrorKind::Cancelled,
                    "OpenRouter request cancelled",
                ));
            }
        };

        let status = response.status();
        if !status.is_success() {
            let kind =
                if status.is_server_error() || status == reqwest::StatusCode::TOO_MANY_REQUESTS {
                    GenerationErrorKind::ProviderError
                } else {
                    GenerationErrorKind::InvalidRequest
                };
            return Err(GenerationError::new(
                kind,
                format!("OpenRouter chat completion returned HTTP {status}"),
            ));
        }

        if cancel.is_cancelled() {
            return Err(GenerationError::new(
                GenerationErrorKind::Cancelled,
                "OpenRouter request cancelled",
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

        if cancel.is_cancelled() {
            return Err(GenerationError::new(
                GenerationErrorKind::Cancelled,
                "OpenRouter request cancelled",
            ));
        }

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
    fn prepare<'a>(&'a self) -> BoxFuture<'a, Result<(), GenerationError>> {
        Box::pin(async move { self.check_supported_parameters().await })
    }

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
