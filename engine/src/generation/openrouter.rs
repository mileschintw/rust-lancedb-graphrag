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
        emit_generation_output_rejected, BoxFuture, GenerationError, GenerationErrorKind,
        GenerationRequest, Generator, GroundingLimits, ModelOutput, RejectedOutput,
    },
    prompt::{pack_evidence_and_graph_prompt_with, PromptOptions},
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
    provider_order: Vec<String>,
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
            provider_order: Vec::new(),
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

    /// Pins the chat request to the given OpenRouter provider slugs, in order (D-191).
    ///
    /// An empty list, the default, sends no pin and keeps the request bytes of D-96.
    pub fn with_provider_order(mut self, order: Vec<String>) -> Self {
        self.provider_order = order;
        self
    }

    /// The provider slugs the chat request is pinned to, empty when unpinned (D-191).
    pub fn provider_order(&self) -> &[String] {
        &self.provider_order
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

/// Packs system policy, user prompt, and validation evidence blocks for OpenRouter structured generation.
///
/// Returns `(system_message, user_message, validation_evidence_blocks)`. `options` selects the
/// lever-gated policy sentences, the same ones the workflow's own prompt assembly carries.
/// When `evidence` is empty and `allow_model_only` is true, the ungrounded model-only prompt is packed
/// and the returned validation evidence slice is empty.
#[allow(clippy::too_many_arguments)]
pub(crate) async fn pack_openrouter_messages(
    question: &str,
    evidence: &[crate::prompt::EvidenceBlock],
    graph_facts: &[crate::prompt::GraphFactBlock],
    graph_weight: f64,
    evidence_budget: usize,
    max_output_tokens: usize,
    allow_model_only: bool,
    options: PromptOptions,
    cancel: &tokio_util::sync::CancellationToken,
) -> Result<(String, String, Vec<crate::prompt::EvidenceBlock>), GenerationError> {
    if cancel.is_cancelled() {
        return Err(GenerationError::new(
            GenerationErrorKind::Cancelled,
            "prompt assembly cancelled",
        ));
    }

    if evidence.is_empty() && allow_model_only {
        let system_msg = crate::prompt::model_only_system_policy().to_string();
        let user_msg = format!("Question: {}\n", question);
        return Ok((system_msg, user_msg, Vec::new()));
    }

    let packed_evidence = pack_evidence_and_graph_prompt_with(
        question,
        evidence,
        graph_facts,
        graph_weight,
        evidence_budget,
        max_output_tokens,
        cancel,
        options,
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
            "prompt assembly cancelled",
        ));
    }

    let system_msg = "You are a precise technical RAG engine.".to_string();
    let user_msg = packed_evidence.prompt;

    Ok((system_msg, user_msg, packed_evidence.evidence))
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

        let (system_msg, user_msg, _validation_evidence) = pack_openrouter_messages(
            &request.question,
            &request.evidence,
            &request.graph_facts,
            request.graph_weight,
            self.config.evidence_token_budget(),
            self.config.max_completion_tokens(),
            request.allow_model_only,
            request.prompt_options,
            &cancel,
        )
        .await?;

        if cancel.is_cancelled() {
            return Err(GenerationError::new(
                GenerationErrorKind::Cancelled,
                "OpenRouter request cancelled after prompt assembly",
            ));
        }

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
                    "enum": ["retrieval", "mixed", "model_only"]
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
                },
                "final_answer": {
                    "type": "string",
                    "maxLength": crate::generation::final_answer::MAX_FINAL_ANSWER_CHARS
                }
            },
            "required": [
                "answer",
                "cited_evidence_ids",
                "answer_basis",
                "notices",
                "warnings",
                "final_answer"
            ],
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
            reasoning: Some(ReasoningConfig {
                effort: "none".into(),
            }),
            response_format: ResponseFormat {
                format_type: "json_schema".into(),
                json_schema: JsonSchemaWrapper {
                    name: "model_output".into(),
                    strict: true,
                    schema: schema_json,
                },
            },
            provider: ProviderPreferences::for_order(self.config.provider_order()),
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

        emit_generation_served(
            request.correlation_id.as_deref(),
            served_field(chat_resp.id.as_ref()).as_deref(),
            served_field(chat_resp.model.as_ref()).as_deref(),
            served_field(chat_resp.provider.as_ref()).as_deref(),
        );

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
        let rejection = RejectionContext {
            content: &choice.message.content,
            finish_reason: choice.finish_reason.as_deref(),
            prompt_tokens: chat_resp.usage.as_ref().map(|usage| usage.prompt_tokens),
            completion_tokens: chat_resp.usage.as_ref().map(|usage| usage.completion_tokens),
            correlation_id: request.correlation_id.as_deref(),
        };

        match choice.finish_reason.as_deref() {
            Some("stop") => {}
            Some(other) => {
                return Err(rejection.reject(
                    "finish_reason",
                    GenerationError::new(
                        GenerationErrorKind::SchemaValidation,
                        format!("OpenRouter completion incomplete: finish_reason '{other}'"),
                    ),
                    None,
                ));
            }
            None => {
                return Err(rejection.reject(
                    "finish_reason",
                    GenerationError::new(
                        GenerationErrorKind::SchemaValidation,
                        "OpenRouter choice missing finish_reason",
                    ),
                    None,
                ));
            }
        }

        let content_str = &choice.message.content;
        let mut model_output: ModelOutput = serde_json::from_str(content_str).map_err(|err| {
            rejection.reject(
                "parse",
                GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!("failed to deserialize ModelOutput schema: {err}"),
                ),
                None,
            )
        })?;

        if let Some(usage) = chat_resp.usage {
            let limits = &self.config.grounding_limits;
            if usage.prompt_tokens > limits.evidence_token_budget() {
                return Err(rejection.reject(
                    "usage",
                    GenerationError::new(
                        GenerationErrorKind::SchemaValidation,
                        format!(
                            "OpenRouter prompt_tokens {} exceeds budget {}",
                            usage.prompt_tokens,
                            limits.evidence_token_budget()
                        ),
                    ),
                    Some(&model_output),
                ));
            }
            if usage.completion_tokens > limits.max_output_tokens() {
                return Err(rejection.reject(
                    "usage",
                    GenerationError::new(
                        GenerationErrorKind::SchemaValidation,
                        format!(
                            "OpenRouter completion_tokens {} exceeds budget {}",
                            usage.completion_tokens,
                            limits.max_output_tokens()
                        ),
                    ),
                    Some(&model_output),
                ));
            }
            let checked_total = usage
                .prompt_tokens
                .checked_add(usage.completion_tokens)
                .ok_or_else(|| {
                    rejection.reject(
                        "usage",
                        GenerationError::new(
                            GenerationErrorKind::SchemaValidation,
                            "OpenRouter token usage addition overflowed",
                        ),
                        Some(&model_output),
                    )
                })?;
            if usage.total_tokens > limits.total_tokens_ceiling()
                || usage.total_tokens < checked_total
            {
                return Err(rejection.reject(
                    "usage",
                    GenerationError::new(
                        GenerationErrorKind::SchemaValidation,
                        format!(
                            "OpenRouter total_tokens {} exceeds budget limit {}",
                            usage.total_tokens,
                            limits.total_tokens_ceiling()
                        ),
                    ),
                    Some(&model_output),
                ));
            }

            model_output.usage = Some(crate::generation::ModelUsage {
                prompt_tokens: usage.prompt_tokens,
                completion_tokens: usage.completion_tokens,
                total_tokens: usage.total_tokens,
            });
        }

        // Validate semantic grounding shape against limits per D-17, D-22, D-28
        let limits = self
            .config
            .grounding_limits
            .with_allow_model_only(request.allow_model_only);
        // 06.3.5-18: a cited grounded abstention the model labelled `model_only` is shape-checked
        // as the `retrieval` abstention it is. The adapter still returns the provider output
        // unchanged and emits no event: `GenerateAnswerNode` owns the one normalisation seam, so
        // the `generation_basis_normalised` event and the notice occur once per record.
        let validation_view = if request.evidence.is_empty() && request.allow_model_only {
            model_output.into_model_only()
        } else if let Some(normalised) = model_output.grounded_abstention_view(limits) {
            normalised
        } else {
            model_output.clone()
        };
        validation_view
            .validate_output_shape_with_limits(limits)
            .map_err(|err| rejection.reject("validate", err, Some(&model_output)))?;

        Ok(model_output)
    }
}

impl Generator for OpenRouterGenerator {
    fn model_id(&self) -> &str {
        &self.config.model
    }

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

/// Characters of a provider-supplied generation ID, model slug or provider name kept in the
/// `generation_served` event.
///
/// OpenRouter generation IDs, model slugs and provider names are short, so the bound only
/// matters when a provider sends something unexpected: it caps one log line. Raising it grows
/// every `generation_served` line in proportion.
const MAX_SERVED_FIELD_CHARS: usize = 128;

/// Returns the bounded text of a JSON string value, or `None` for an absent or non-string value.
///
/// The cut falls on a `char` boundary. A non-string value is dropped, never parsed, so it
/// cannot fail a generation.
fn served_field(value: Option<&serde_json::Value>) -> Option<String> {
    value
        .and_then(serde_json::Value::as_str)
        .map(|text| text.chars().take(MAX_SERVED_FIELD_CHARS).collect())
}

/// Emits one info-level `generation_served` event naming who served a provider response (D-96).
///
/// Drive 1b's provider map joins it to the journal by `correlation_id`. Every field is recorded
/// with the `Debug` sigil, so line breaks and quotes in provider text are escaped and the
/// rendered line stays one line; an absent value is not recorded. The event is INFO under the
/// `engine::` target, so it passes the D-90 default filter. It carries response metadata only,
/// never the prompt, the choice content, headers or the API key, and it only observes: it never
/// alters what the caller returns.
fn emit_generation_served(
    correlation_id: Option<&str>,
    generation_id: Option<&str>,
    response_model: Option<&str>,
    provider: Option<&str>,
) {
    tracing::info!(
        generation_served = true,
        correlation_id = correlation_id.map(tracing::field::debug),
        generation_id = generation_id.map(tracing::field::debug),
        gen_ai.response.model = response_model.map(tracing::field::debug),
        provider = provider.map(tracing::field::debug),
        "generation_served"
    );
}

#[derive(Serialize)]
struct ReasoningConfig {
    effort: String,
}

#[derive(Serialize)]
struct OpenRouterChatPayload {
    model: String,
    messages: Vec<ChatMessage>,
    temperature: f64,
    top_p: f64,
    max_completion_tokens: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    reasoning: Option<ReasoningConfig>,
    response_format: ResponseFormat,
    provider: ProviderPreferences,
}

/// OpenRouter provider-routing preferences sent with every chat request (D-96, D-191).
///
/// `require_parameters` makes OpenRouter route only to endpoints that support every parameter
/// the request sends: structured outputs, `reasoning`, `temperature`, `top_p` and max tokens.
/// It is hard-coded because it is a routing invariant of the strict-schema contract, not a
/// tunable. With no configured provider order, fallback among the qualifying endpoints stays on
/// and `require_parameters` is the only key under `provider` (D-96). A configured order adds
/// `order` and `allow_fallbacks = false`, which pins generation to those providers (D-191).
#[derive(Serialize)]
struct ProviderPreferences {
    require_parameters: bool,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    order: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    allow_fallbacks: Option<bool>,
}

impl ProviderPreferences {
    /// The preferences for a chat request pinned to `order`, unpinned when `order` is empty.
    fn for_order(order: &[String]) -> Self {
        Self {
            require_parameters: true,
            order: order.to_vec(),
            allow_fallbacks: (!order.is_empty()).then_some(false),
        }
    }
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

/// What a provider-side `generation_output_rejected` event may carry (D-91).
///
/// It holds the provider's choice content, its finish reason and token usage, plus the
/// request's correlation ID. It never borrows the request body, prompt, headers or API key.
struct RejectionContext<'a> {
    content: &'a str,
    finish_reason: Option<&'a str>,
    prompt_tokens: Option<u32>,
    completion_tokens: Option<u32>,
    correlation_id: Option<&'a str>,
}

impl RejectionContext<'_> {
    /// Emits one `generation_output_rejected` event for `err` and returns `err` untouched.
    ///
    /// The caller builds the error exactly as before, so the error kind and message cannot
    /// differ from the unobserved code path. `parsed` is the deserialized output when the
    /// rejection happens after parsing.
    fn reject(
        &self,
        stage: &'static str,
        err: GenerationError,
        parsed: Option<&ModelOutput>,
    ) -> GenerationError {
        emit_generation_output_rejected(&RejectedOutput {
            stage,
            reason: err.message(),
            correlation_id: self.correlation_id,
            finish_reason: self.finish_reason,
            prompt_tokens: self.prompt_tokens,
            completion_tokens: self.completion_tokens,
            answer_basis: parsed.map(|output| output.answer_basis.as_str()),
            model_cited_ids: parsed.map(|output| output.cited_evidence_ids.len()),
            markers_found: None,
            markers_resolved: None,
            total_drop: None,
            content: self.content,
        });
        err
    }
}

#[derive(Deserialize)]
struct OpenRouterChatResponse {
    choices: Vec<ChatChoice>,
    usage: Option<UsageMeta>,
    /// OpenRouter generation ID, read as a raw `Value` so a non-string never fails the parse.
    #[serde(default)]
    id: Option<serde_json::Value>,
    /// The model slug that served the request, read like `id`.
    #[serde(default)]
    model: Option<serde_json::Value>,
    /// The provider that served the request, read like `id`.
    #[serde(default)]
    provider: Option<serde_json::Value>,
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

#[cfg(test)]
mod tests {
    use super::ProviderPreferences;

    fn slugs(names: &[&str]) -> Vec<String> {
        names.iter().map(|name| (*name).to_string()).collect()
    }

    /// D-191: the `provider` object carries the order and `allow_fallbacks = false` after
    /// `require_parameters` when pinned, and is byte-identical to D-96's when unpinned.
    #[test]
    fn provider_object_bytes_with_and_without_the_pin() {
        let pinned =
            serde_json::to_string(&ProviderPreferences::for_order(&slugs(&["sail-research"])))
                .expect("preferences serialize");
        assert_eq!(
            pinned,
            r#"{"require_parameters":true,"order":["sail-research"],"allow_fallbacks":false}"#
        );

        let unpinned = serde_json::to_string(&ProviderPreferences::for_order(&[]))
            .expect("preferences serialize");
        assert_eq!(unpinned, r#"{"require_parameters":true}"#);

        let ordered = serde_json::to_string(&ProviderPreferences::for_order(&slugs(&[
            "sail-research",
            "other-provider",
        ])))
        .expect("preferences serialize");
        assert_eq!(
            ordered,
            r#"{"require_parameters":true,"order":["sail-research","other-provider"],"allow_fallbacks":false}"#,
            "the configured order is kept as written"
        );
    }
}
