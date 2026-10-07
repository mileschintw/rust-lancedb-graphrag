//! Provider-neutral generation interface, closed output schema, and errors.
//!
//! D-27 through D-33 define this boundary. Generation is injected via the
//! object-safe async `Generator` trait, returning a Serde-validated `ModelOutput`.

use std::{
    fmt::{Display, Formatter},
    future::Future,
    pin::Pin,
};

#[cfg(test)]
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Mutex,
};

use serde::{Deserialize, Serialize};

use crate::prompt::EvidenceBlock;

pub mod citations;
pub mod final_answer;
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

impl AnswerBasis {
    /// The snake_case name used on the wire and in log events.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Retrieval => "retrieval",
            Self::Mixed => "mixed",
            Self::ModelOnly => "model_only",
        }
    }
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
    /// The model's shortest answer, which the engine renders as the last `Answer:` line (D-95).
    ///
    /// `None` when the provider sent no value, and then skipped on serialization so an
    /// output without it serializes exactly as before D-95.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub final_answer: Option<String>,
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

/// Shared carrier governing evidence token budget, max output tokens, total usage ceiling,
/// and whether model-only answers are permitted.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct GroundingLimits {
    evidence_token_budget: u32,
    max_output_tokens: u32,
    total_tokens_ceiling: u32,
    /// Whether model-only answers are permitted when no evidence survives retrieval.
    ///
    /// When true, grounding validation accepts `AnswerBasis::ModelOnly` and permits an empty
    /// `cited_evidence_ids` list *only* for model-only answers. When false, both conditions are rejected.
    allow_model_only: bool,
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
            allow_model_only: false,
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

    pub fn allow_model_only(&self) -> bool {
        self.allow_model_only
    }

    pub fn with_allow_model_only(mut self, allow_model_only: bool) -> Self {
        self.allow_model_only = allow_model_only;
        self
    }
}

impl ModelOutput {
    /// The answer text the engine publishes: the answer plus the rendered final `Answer:` line.
    ///
    /// Call this only after validation (D-95): validation reads the model's own `answer`, and
    /// the rendered line is added afterwards at the single publication seam. Without a usable
    /// `final_answer` the result is `answer` byte-identical.
    pub fn rendered_answer(&self) -> String {
        final_answer::render_final_answer_line(&self.answer, self.final_answer.as_deref())
    }

    /// Whether the engine would publish this output as an `Answer: Insufficient information`.
    ///
    /// The check reads the last line the engine renders and, when the model wrote one, its own
    /// trailing `Answer:` segment; see [`final_answer::abstains`] for the exact tolerances.
    pub fn is_abstention(&self) -> bool {
        final_answer::abstains(&self.answer, self.final_answer.as_deref())
    }

    /// The `retrieval`-basis view of a cited grounded abstention that the model labelled `model_only`.
    ///
    /// Returns `Some` only when `limits` has no model-only opt-in, the output self-reports
    /// [`AnswerBasis::ModelOnly`], it cites at least one evidence ID and
    /// [`is_abstention`](Self::is_abstention) holds. The result equals `self` in every field
    /// except `answer_basis`, which is [`AnswerBasis::Retrieval`]. This implements the owner
    /// decision of 2026-10-07 recorded in plan 06.3.5-18: a grounded abstention names the
    /// evidence blocks it checked, so `model_only` is a mislabelled self-report. An abstention
    /// that cites nothing is deliberately excluded; widening to it is a deferred owner decision.
    ///
    /// The caller must still run the full existing validation on the returned view, so every
    /// shape, length, budget and cited-ID check applies to it as to any other output.
    pub fn grounded_abstention_view(&self, limits: GroundingLimits) -> Option<ModelOutput> {
        if limits.allow_model_only()
            || self.answer_basis != AnswerBasis::ModelOnly
            || self.cited_evidence_ids.is_empty()
            || !self.is_abstention()
        {
            return None;
        }
        let mut view = self.clone();
        view.answer_basis = AnswerBasis::Retrieval;
        Some(view)
    }

    pub fn validate_grounding(
        &self,
        packed_evidence: &[EvidenceBlock],
    ) -> Result<(), GenerationError> {
        self.validate_grounding_with_limits(packed_evidence, GroundingLimits::default_limits())
    }

    pub fn validate_output_shape_with_limits(
        &self,
        limits: GroundingLimits,
    ) -> Result<(), GenerationError> {
        if !limits.allow_model_only && self.answer_basis == AnswerBasis::ModelOnly {
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

        if self.cited_evidence_ids.is_empty()
            && (!limits.allow_model_only || self.answer_basis != AnswerBasis::ModelOnly)
        {
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

        Ok(())
    }

    pub fn validate_marker_grounding(
        &self,
        packed_evidence: &[EvidenceBlock],
    ) -> Result<(), GenerationError> {
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

    pub fn validate_grounding_with_limits(
        &self,
        packed_evidence: &[EvidenceBlock],
        limits: GroundingLimits,
    ) -> Result<(), GenerationError> {
        self.validate_output_shape_with_limits(limits)?;
        self.validate_marker_grounding(packed_evidence)
    }

    /// Whether this output should be treated as model-only: either it self-reports
    /// [`AnswerBasis::ModelOnly`], or `no_evidence` records that zero evidence survived
    /// retrieval (the D-10 opt-in decision point).
    pub fn should_treat_as_model_only(&self, no_evidence: bool) -> bool {
        no_evidence || self.answer_basis == AnswerBasis::ModelOnly
    }

    /// Clones this output with citations cleared and the basis forced to model-only.
    ///
    /// Used at the D-10 opt-in site, where the engine — not the model's own claim —
    /// decides the run is model-only; feeding the result back through
    /// [`crate::workflow::WorkflowContext::update_from_model_output`] keeps basis
    /// assignment at that single seam rather than adding a second one.
    pub fn into_model_only(&self) -> Self {
        let mut clone = self.clone();
        clone.cited_evidence_ids.clear();
        clone.answer_basis = AnswerBasis::ModelOnly;
        clone
    }

    /// Clones this output with `answer` and `cited_evidence_ids` replaced, leaving
    /// every other field — including the self-reported basis — untouched.
    ///
    /// Used by the D-14 citation-repair pass to feed the post-strip answer and the
    /// post-repair citation list back into validation and context re-entry without
    /// pre-judging the answer basis; reconciliation of the basis happens only at
    /// [`crate::workflow::WorkflowContext::update_from_model_output`].
    pub fn with_answer_and_citations(
        &self,
        answer: String,
        cited_evidence_ids: Vec<String>,
    ) -> Self {
        let mut clone = self.clone();
        clone.answer = answer;
        clone.cited_evidence_ids = cited_evidence_ids;
        clone
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
#[derive(Debug, Clone, Serialize)]
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
    /// Whether model-only answers are permitted when no evidence survives retrieval.
    pub allow_model_only: bool,
    pub session_id: Option<String>,
    pub correlation_id: Option<String>,
    #[serde(skip)]
    pub cancel: Option<tokio_util::sync::CancellationToken>,
}

impl PartialEq for GenerationRequest {
    fn eq(&self, other: &Self) -> bool {
        let Self {
            system_policy,
            question,
            evidence,
            graph_facts,
            graph_weight,
            allow_model_only,
            session_id,
            correlation_id,
            cancel: _,
        } = self;
        *system_policy == other.system_policy
            && *question == other.question
            && *evidence == other.evidence
            && *graph_facts == other.graph_facts
            && graph_weight.to_bits() == other.graph_weight.to_bits()
            && *allow_model_only == other.allow_model_only
            && *session_id == other.session_id
            && *correlation_id == other.correlation_id
    }
}

impl GenerationRequest {
    pub fn new(question: impl Into<String>, evidence: Vec<EvidenceBlock>) -> Self {
        Self {
            system_policy: "You are a precise technical RAG engine.".into(),
            question: question.into(),
            evidence,
            graph_facts: Vec::new(),
            graph_weight: 1.0,
            allow_model_only: false,
            session_id: None,
            correlation_id: None,
            cancel: None,
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

/// The fixed notice text attached to a record whose `model_only` basis the engine normalised.
///
/// It carries typed code `BASIS_RECONCILED` (15) and is fixed text with no interpolation, so
/// the harness counter in `eval/scripts/basis_normalisation_counts.py` identifies a normalised
/// record by exact equality with this string. Changing it requires changing
/// `NORMALISED_NOTICE_MESSAGE` in that script in the same commit, which a harness test
/// enforces by reading this literal from the source. The literal must stay on one line, with
/// no `\` continuation and no `concat!`, so that test can read it with a regular expression.
pub const GROUNDED_ABSTENTION_NORMALISED_NOTICE: &str = "grounded abstention: the model self-reported answer basis 'model_only' on an 'Answer: Insufficient information' answer that cites the evidence blocks it checked; the engine normalised the basis to 'retrieval'";

/// Characters of a rejected model output kept from its start.
///
/// Sized so a complete `ModelOutput` JSON object with a normal answer fits, which makes a
/// parse failure show whether valid JSON precedes the trailing text. Raising it grows every
/// `generation_output_rejected` line and the Loki export in proportion.
pub(crate) const REJECTED_OUTPUT_HEAD_CHARS: usize = 2000;

/// Characters of a rejected model output kept from its end.
///
/// Sized to hold the trailing text after a complete JSON object, such as D-71's
/// `Answer:` line. Raising it grows every `generation_output_rejected` line.
pub(crate) const REJECTED_OUTPUT_TAIL_CHARS: usize = 500;

/// Splits `text` into its first and last characters for a bounded log excerpt.
///
/// Returns the head, the tail and the total character count. Both cuts fall on `char`
/// boundaries. The tail never overlaps the head, so it is empty when the whole text fits in
/// the head and shorter than [`REJECTED_OUTPUT_TAIL_CHARS`] when only a little remains.
pub(crate) fn bounded_excerpt(text: &str) -> (String, String, usize) {
    let total = text.chars().count();
    let head: String = text.chars().take(REJECTED_OUTPUT_HEAD_CHARS).collect();
    let tail_chars = total
        .saturating_sub(REJECTED_OUTPUT_HEAD_CHARS)
        .min(REJECTED_OUTPUT_TAIL_CHARS);
    let tail: String = text.chars().skip(total - tail_chars).collect();
    (head, tail, total)
}

/// What is known about a rejected `GenerateAnswer` output, borrowed for one log event.
///
/// Holds model output and engine-derived counts only. It has no field for the prompt, the
/// evidence, request headers or the API key, so none of them can reach the event.
#[derive(Debug)]
pub(crate) struct RejectedOutput<'a> {
    /// Where the output was rejected: `parse`, `finish_reason`, `usage` or `validate`.
    pub stage: &'static str,
    /// The engine's unchanged error message for this rejection.
    pub reason: &'a str,
    pub correlation_id: Option<&'a str>,
    pub finish_reason: Option<&'a str>,
    pub prompt_tokens: Option<u32>,
    pub completion_tokens: Option<u32>,
    pub answer_basis: Option<&'a str>,
    /// Length of the model's own `cited_evidence_ids` list.
    pub model_cited_ids: Option<usize>,
    pub markers_found: Option<usize>,
    pub markers_resolved: Option<usize>,
    pub total_drop: Option<bool>,
    /// The model output the excerpt is cut from.
    pub content: &'a str,
}

/// Emits one info-level `generation_output_rejected` event for a rejected output.
///
/// Every free-text field (`reason`, `correlation_id`, `finish_reason`, `answer_basis`,
/// `raw_head`, `raw_tail`) is recorded with the `Debug` sigil, so newlines and quotes in
/// model output are escaped and the rendered line stays one line. The event is INFO under the
/// `engine::` target, so it passes the D-90 default filter. It only observes: it never
/// alters the error the caller returns.
pub(crate) fn emit_generation_output_rejected(r: &RejectedOutput<'_>) {
    let (raw_head, raw_tail, raw_chars) = bounded_excerpt(r.content);
    tracing::info!(
        generation_output_rejected = true,
        stage = r.stage,
        reason = ?r.reason,
        correlation_id = r.correlation_id.map(tracing::field::debug),
        finish_reason = r.finish_reason.map(tracing::field::debug),
        prompt_tokens = r.prompt_tokens,
        completion_tokens = r.completion_tokens,
        answer_basis = r.answer_basis.map(tracing::field::debug),
        model_cited_ids = r.model_cited_ids,
        markers_found = r.markers_found,
        markers_resolved = r.markers_resolved,
        total_drop = r.total_drop,
        raw_chars = raw_chars,
        raw_head = ?raw_head,
        raw_tail = ?raw_tail,
        "generation_output_rejected"
    );
}

/// Provider-neutral object-safe async trait for structured generation.
pub trait Generator: Send + Sync {
    /// Returns the provider model identifier used by this generator.
    ///
    /// The default returns `"unspecified"` so existing test doubles remain source-compatible.
    fn model_id(&self) -> &str {
        "unspecified"
    }

    /// Prepare provider capabilities before the timed generation node body.
    ///
    /// The default is intentionally a successful no-op so existing generators
    /// remain source-compatible while adapters that need capability discovery
    /// can opt in.
    fn prepare<'a>(&'a self) -> BoxFuture<'a, Result<(), GenerationError>> {
        Box::pin(async { Ok(()) })
    }

    fn generate<'a>(
        &'a self,
        request: GenerationRequest,
    ) -> BoxFuture<'a, Result<ModelOutput, GenerationError>>;
}

/// Deterministic fake generator for unit tests and local contract verification.
#[cfg(test)]
pub struct FakeGenerator {
    pub call_count: AtomicUsize,
    pub responses: Mutex<Vec<Result<ModelOutput, GenerationError>>>,
    pub stall: bool,
}

#[cfg(test)]
impl FakeGenerator {
    pub fn new(response: Result<ModelOutput, GenerationError>) -> Self {
        Self {
            call_count: AtomicUsize::new(0),
            responses: Mutex::new(vec![response]),
            stall: false,
        }
    }

    pub fn with_responses(responses: Vec<Result<ModelOutput, GenerationError>>) -> Self {
        Self {
            call_count: AtomicUsize::new(0),
            responses: Mutex::new(responses),
            stall: false,
        }
    }

    pub fn stall() -> Self {
        Self {
            call_count: AtomicUsize::new(0),
            responses: Mutex::new(vec![]),
            stall: true,
        }
    }

    pub fn malformed_citation_near_miss(query: &str) -> Self {
        Self::new(Ok(ModelOutput {
            answer: format!("{query} answer with near miss citation (1)."),
            cited_evidence_ids: vec!["(1)".into()],
            answer_basis: AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            final_answer: None,
            usage: None,
        }))
    }

    pub fn malformed_citation_unresolvable() -> Self {
        Self::new(Ok(ModelOutput {
            answer: "Answer with unresolvable marker [9999].".into(),
            cited_evidence_ids: vec!["[9999]".into()],
            answer_basis: AnswerBasis::Retrieval,
            notices: vec![],
            warnings: vec![],
            final_answer: None,
            usage: None,
        }))
    }

    pub fn calls(&self) -> usize {
        self.call_count.load(Ordering::Relaxed)
    }
}

#[cfg(test)]
impl Generator for FakeGenerator {
    fn generate<'a>(
        &'a self,
        request: GenerationRequest,
    ) -> BoxFuture<'a, Result<ModelOutput, GenerationError>> {
        Box::pin(async move {
            self.call_count.fetch_add(1, Ordering::Relaxed);
            if self.stall {
                tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            }
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
