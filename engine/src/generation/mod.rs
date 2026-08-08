//! Provider-neutral generation interface, closed output schema, and errors.
//!
//! D-27 through D-33 define this boundary. Generation is injected via the
//! object-safe async `Generator` trait, returning a Serde-validated `ModelOutput`.

use std::{
    fmt::{Display, Formatter},
    future::Future,
    pin::Pin,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Mutex,
    },
};

use serde::{Deserialize, Serialize};

use crate::prompt::EvidenceBlock;

pub mod openrouter;

pub type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

/// Typed answer basis distinguishing retrieval-backed, mixed, and model-only answers.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AnswerBasis {
    Retrieval,
    Mixed,
    ModelOnly,
}

impl Display for AnswerBasis {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Retrieval => write!(f, "retrieval"),
            Self::Mixed => write!(f, "mixed"),
            Self::ModelOnly => write!(f, "model_only"),
        }
    }
}

use std::collections::HashSet;

/// Token usage reported by a generation provider.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(deny_unknown_fields)]
pub struct ModelUsage {
    pub prompt_tokens: u32,
    pub completion_tokens: u32,
    pub total_tokens: u32,
}

/// Closed provider-neutral output contract for structured generation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModelOutput {
    pub answer: String,
    #[serde(default)]
    pub cited_evidence_ids: Vec<String>,
    pub answer_basis: AnswerBasis,
    #[serde(default)]
    pub notices: Vec<String>,
    #[serde(default)]
    pub warnings: Vec<String>,
    #[serde(default)]
    pub usage: Option<ModelUsage>,
}

pub const MAX_ANSWER_CHARS: usize = 16_384;
pub const MAX_CITED_EVIDENCE_IDS: usize = 64;
pub const MAX_EVIDENCE_ID_CHARS: usize = 128;
pub const MAX_NOTICES_WARNINGS_ITEMS: usize = 32;
pub const MAX_NOTICE_WARNING_CHARS: usize = 1_024;
pub const DEFAULT_EVIDENCE_TOKEN_BUDGET: u32 = 8_192;
pub const DEFAULT_MAX_OUTPUT_TOKENS: u32 = 2_048;
pub const MAX_TOTAL_TOKENS_BUDGET: u32 = DEFAULT_EVIDENCE_TOKEN_BUDGET + DEFAULT_MAX_OUTPUT_TOKENS;

pub const MAX_SERVICE_EVIDENCE_TOKEN_BUDGET: u32 = 16_384;
pub const MAX_SERVICE_OUTPUT_TOKENS: u32 = 4_096;
pub const MAX_SERVICE_TOTAL_TOKENS: u32 =
    MAX_SERVICE_EVIDENCE_TOKEN_BUDGET + MAX_SERVICE_OUTPUT_TOKENS;

/// Shared carrier governing evidence token budget, max output tokens, and total usage ceiling.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct GroundingLimits {
    evidence_token_budget: u32,
    max_output_tokens: u32,
    total_tokens_ceiling: u32,
}

impl GroundingLimits {
    pub fn new(
        evidence_token_budget: u32,
        max_output_tokens: u32,
    ) -> Result<Self, GenerationError> {
        if evidence_token_budget == 0 || evidence_token_budget > MAX_SERVICE_EVIDENCE_TOKEN_BUDGET {
            return Err(GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                format!(
                    "evidence_token_budget {} exceeds service ceiling {}",
                    evidence_token_budget, MAX_SERVICE_EVIDENCE_TOKEN_BUDGET
                ),
            ));
        }
        if max_output_tokens == 0 || max_output_tokens > MAX_SERVICE_OUTPUT_TOKENS {
            return Err(GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                format!(
                    "max_output_tokens {} exceeds service ceiling {}",
                    max_output_tokens, MAX_SERVICE_OUTPUT_TOKENS
                ),
            ));
        }
        let total_tokens_ceiling = evidence_token_budget
            .checked_add(max_output_tokens)
            .ok_or_else(|| {
                GenerationError::new(
                    GenerationErrorKind::InvalidRequest,
                    "token budget addition overflowed",
                )
            })?;
        if total_tokens_ceiling > MAX_SERVICE_TOTAL_TOKENS {
            return Err(GenerationError::new(
                GenerationErrorKind::InvalidRequest,
                format!(
                    "derived total_tokens_ceiling {} exceeds service ceiling {}",
                    total_tokens_ceiling, MAX_SERVICE_TOTAL_TOKENS
                ),
            ));
        }
        Ok(Self {
            evidence_token_budget,
            max_output_tokens,
            total_tokens_ceiling,
        })
    }

    pub fn default_limits() -> Self {
        Self::new(DEFAULT_EVIDENCE_TOKEN_BUDGET, DEFAULT_MAX_OUTPUT_TOKENS)
            .expect("default grounding limits must be valid")
    }

    pub fn evidence_token_budget(&self) -> u32 {
        self.evidence_token_budget
    }

    pub fn max_output_tokens(&self) -> u32 {
        self.max_output_tokens
    }

    pub fn total_tokens_ceiling(&self) -> u32 {
        self.total_tokens_ceiling
    }
}

impl ModelOutput {
    pub fn validate_grounding(
        &self,
        packed_evidence: &[EvidenceBlock],
    ) -> Result<(), GenerationError> {
        self.validate_grounding_with_limits(packed_evidence, GroundingLimits::default_limits())
    }

    pub fn validate_grounding_with_limits(
        &self,
        packed_evidence: &[EvidenceBlock],
        limits: GroundingLimits,
    ) -> Result<(), GenerationError> {
        if self.answer_basis == AnswerBasis::ModelOnly {
            return Err(GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                "ModelOnly answer basis is not supported on Phase 03 QueryRAG path",
            ));
        }

        if self.answer.trim().is_empty() {
            return Err(GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                "Model answer text must not be empty or blank",
            ));
        }

        if self.answer.chars().count() > MAX_ANSWER_CHARS {
            return Err(GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                format!("answer exceeds maximum length of {MAX_ANSWER_CHARS} characters"),
            ));
        }

        if self.cited_evidence_ids.is_empty() {
            return Err(GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                format!(
                    "answer basis '{}' requires at least one cited evidence ID",
                    self.answer_basis
                ),
            ));
        }

        if self.cited_evidence_ids.len() > MAX_CITED_EVIDENCE_IDS {
            return Err(GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                format!(
                    "cited_evidence_ids count {} exceeds limit {MAX_CITED_EVIDENCE_IDS}",
                    self.cited_evidence_ids.len()
                ),
            ));
        }

        for id in &self.cited_evidence_ids {
            if id.chars().count() > MAX_EVIDENCE_ID_CHARS {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!("cited_evidence_id length exceeds limit {MAX_EVIDENCE_ID_CHARS}"),
                ));
            }
        }

        if self.notices.len() > MAX_NOTICES_WARNINGS_ITEMS {
            return Err(GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                format!(
                    "notices count {} exceeds limit {MAX_NOTICES_WARNINGS_ITEMS}",
                    self.notices.len()
                ),
            ));
        }

        for notice in &self.notices {
            if notice.chars().count() > MAX_NOTICE_WARNING_CHARS {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!("notice length exceeds limit {MAX_NOTICE_WARNING_CHARS}"),
                ));
            }
        }

        if self.warnings.len() > MAX_NOTICES_WARNINGS_ITEMS {
            return Err(GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                format!(
                    "warnings count {} exceeds limit {MAX_NOTICES_WARNINGS_ITEMS}",
                    self.warnings.len()
                ),
            ));
        }

        for warning in &self.warnings {
            if warning.chars().count() > MAX_NOTICE_WARNING_CHARS {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!("warning length exceeds limit {MAX_NOTICE_WARNING_CHARS}"),
                ));
            }
        }

        if let Some(usage) = &self.usage {
            if usage.prompt_tokens > limits.evidence_token_budget {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!(
                        "prompt_tokens {} exceeds budget {}",
                        usage.prompt_tokens, limits.evidence_token_budget
                    ),
                ));
            }
            if usage.completion_tokens > limits.max_output_tokens {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!(
                        "completion_tokens {} exceeds budget {}",
                        usage.completion_tokens, limits.max_output_tokens
                    ),
                ));
            }
            let checked_total = usage
                .prompt_tokens
                .checked_add(usage.completion_tokens)
                .ok_or_else(|| {
                    GenerationError::new(
                        GenerationErrorKind::SchemaValidation,
                        "token usage addition overflowed",
                    )
                })?;
            if usage.total_tokens > limits.total_tokens_ceiling
                || usage.total_tokens < checked_total
            {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!(
                        "total_tokens {} exceeds calculated/budget limit",
                        usage.total_tokens
                    ),
                ));
            }
        }

        // Check for duplicate cited evidence IDs
        let mut seen_cited = HashSet::new();
        for id in &self.cited_evidence_ids {
            if !seen_cited.insert(id.as_str()) {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!("cited_evidence_ids contains duplicate ID '{id}'"),
                ));
            }
        }

        let known_ids: HashSet<&str> = packed_evidence.iter().map(|e| e.id.as_str()).collect();

        // Check that all cited_evidence_ids are known
        for id in &self.cited_evidence_ids {
            if !known_ids.contains(id.as_str()) {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!("cited_evidence_id '{id}' is not in packed evidence"),
                ));
            }
        }

        // Extract inline markers like [1], [2] from answer text
        let inline_markers = extract_inline_markers(&self.answer);
        let mut inline_set = HashSet::new();
        for marker in &inline_markers {
            if !known_ids.contains(marker.as_str()) {
                return Err(GenerationError::new(
                    GenerationErrorKind::SchemaValidation,
                    format!("inline marker '{marker}' in answer is not in packed evidence"),
                ));
            }
            inline_set.insert(marker.as_str());
        }

        // Validate exact set equality between cited_evidence_ids and inline answer markers
        if seen_cited != inline_set {
            return Err(GenerationError::new(
                GenerationErrorKind::SchemaValidation,
                format!(
                    "mismatch between cited_evidence_ids ({:?}) and inline markers ({:?})",
                    self.cited_evidence_ids, inline_markers
                ),
            ));
        }

        Ok(())
    }
}

fn extract_inline_markers(text: &str) -> Vec<String> {
    let mut markers = Vec::new();
    let bytes = text.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'[' {
            let start = i;
            i += 1;
            let mut is_num = false;
            while i < bytes.len() && bytes[i].is_ascii_digit() {
                is_num = true;
                i += 1;
            }
            if is_num && i < bytes.len() && bytes[i] == b']' {
                markers.push(text[start..=i].to_string());
            }
        } else {
            i += 1;
        }
    }
    markers
}

/// A structured input request passed to a `Generator`.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct GenerationRequest {
    pub system_policy: String,
    pub question: String,
    pub evidence: Vec<EvidenceBlock>,
    pub graph_facts: Vec<crate::prompt::GraphFactBlock>,
    /// Configurable multiplier (D-30) applied to normalized graph-fact scores
    /// before they compete with chunk evidence for the shared prompt token
    /// budget; `0.0` hard-excludes graph facts. This is the single source both
    /// `main.rs`'s pre-check and the provider adapter's actual outbound call
    /// read from — never independently derived in two places.
    pub graph_weight: f64,
    pub session_id: Option<String>,
    pub correlation_id: Option<String>,
}

impl GenerationRequest {
    pub fn new(question: impl Into<String>, evidence: Vec<EvidenceBlock>) -> Self {
        Self {
            system_policy: "You are a precise technical RAG engine.".into(),
            question: question.into(),
            evidence,
            graph_facts: Vec::new(),
            graph_weight: 1.0,
            session_id: None,
            correlation_id: None,
        }
    }
}

/// Category of a generation failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GenerationErrorKind {
    InvalidRequest,
    SupportedParameters,
    ProviderError,
    SchemaValidation,
    Timeout,
    Cancelled,
    SessionCorrelation,
}

/// A typed generation error retaining correlation identity without leaking credentials or raw data.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GenerationError {
    pub kind: GenerationErrorKind,
    pub message: String,
    pub session_id: Option<String>,
    pub correlation_id: Option<String>,
}

impl GenerationError {
    pub fn new(kind: GenerationErrorKind, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
            session_id: None,
            correlation_id: None,
        }
    }

    pub fn with_correlation(
        mut self,
        session_id: Option<String>,
        correlation_id: Option<String>,
    ) -> Self {
        self.session_id = session_id;
        self.correlation_id = correlation_id;
        self
    }

    pub fn message(&self) -> &str {
        &self.message
    }
}

impl Display for GenerationError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?}: {}", self.kind, self.message)
    }
}

impl std::error::Error for GenerationError {}

/// Provider-neutral object-safe async trait for structured generation.
pub trait Generator: Send + Sync {
    fn generate<'a>(
        &'a self,
        request: GenerationRequest,
    ) -> BoxFuture<'a, Result<ModelOutput, GenerationError>>;
}

/// Deterministic fake generator for unit tests and local contract verification.
pub struct FakeGenerator {
    pub call_count: AtomicUsize,
    pub responses: Mutex<Vec<Result<ModelOutput, GenerationError>>>,
}

impl FakeGenerator {
    pub fn new(response: Result<ModelOutput, GenerationError>) -> Self {
        Self {
            call_count: AtomicUsize::new(0),
            responses: Mutex::new(vec![response]),
        }
    }

    pub fn with_responses(responses: Vec<Result<ModelOutput, GenerationError>>) -> Self {
        Self {
            call_count: AtomicUsize::new(0),
            responses: Mutex::new(responses),
        }
    }

    pub fn calls(&self) -> usize {
        self.call_count.load(Ordering::Relaxed)
    }
}

impl Generator for FakeGenerator {
    fn generate<'a>(
        &'a self,
        request: GenerationRequest,
    ) -> BoxFuture<'a, Result<ModelOutput, GenerationError>> {
        Box::pin(async move {
            self.call_count.fetch_add(1, Ordering::Relaxed);
            let mut guard = self.responses.lock().unwrap();
            if guard.is_empty() {
                Err(GenerationError::new(
                    GenerationErrorKind::ProviderError,
                    "FakeGenerator ran out of configured responses",
                )
                .with_correlation(request.session_id, request.correlation_id))
            } else {
                let res = guard.remove(0);
                res.map_err(|err| err.with_correlation(request.session_id, request.correlation_id))
            }
        })
    }
}

#[cfg(test)]
pub mod tests;
