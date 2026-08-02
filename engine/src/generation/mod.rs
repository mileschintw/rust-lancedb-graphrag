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

/// Token usage reported by a generation provider.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ModelUsage {
    pub prompt_tokens: u32,
    pub completion_tokens: u32,
    pub total_tokens: u32,
}

/// Closed provider-neutral output contract for structured generation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
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

/// A structured input request passed to a `Generator`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GenerationRequest {
    pub system_policy: String,
    pub question: String,
    pub evidence: Vec<EvidenceBlock>,
    pub session_id: Option<String>,
    pub correlation_id: Option<String>,
}

impl GenerationRequest {
    pub fn new(question: impl Into<String>, evidence: Vec<EvidenceBlock>) -> Self {
        Self {
            system_policy: "You are a precise technical RAG engine.".into(),
            question: question.into(),
            evidence,
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
