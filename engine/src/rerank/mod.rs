//! Provider-neutral async reranking boundary.
//!
//! A [`Reranker`] scores the fused candidate list against the query and returns a ranking of the
//! candidates it was given. The port borrows the candidates, so a failing reranker can never lose
//! the fused list: the caller still holds it and decides whether to fail the query or keep the
//! fused order. [`NoOpReranker`] is the service-wide default and keeps the fused order; the
//! [`openrouter`] adapter is the quality lever selected per request.

use std::fmt;

use futures::future::BoxFuture;

use crate::retrieval::FusedCandidate;

pub mod openrouter;

/// What a reranker is asked to rank: the query and the candidates in fused order.
#[derive(Debug, Clone, Copy)]
pub struct RerankRequest<'a> {
    /// The text the candidates are scored against.
    pub query: &'a str,
    /// The fused candidates, best first. Indices in a [`RerankOutput`] refer to this slice.
    pub candidates: &'a [FusedCandidate],
}

/// One candidate's place in a reranking.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Reranked {
    /// Position of the candidate in [`RerankRequest::candidates`].
    pub index: usize,
    /// The relevance score the reranker gave it; finite.
    pub score: f64,
}

/// A reranking of every request candidate.
#[derive(Debug, Clone, PartialEq)]
pub struct RerankOutput {
    /// Every request candidate exactly once, best first.
    pub ranked: Vec<Reranked>,
    /// The cost the provider reported for the call, in credits; `None` when it reported none.
    pub cost_credits: Option<f64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RerankErrorKind {
    Status(u16),
    Timeout,
    Transport,
    Malformed,
    InvalidRequest,
}

/// A rerank call failed.
///
/// The message is the failure class only (`timeout`, `status 429`, `malformed`, `transport`,
/// `invalid request`). It never carries a provider response body, a transport error text or key
/// material, so it is safe to log and to put in a notice.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RerankError {
    kind: RerankErrorKind,
}

impl RerankError {
    /// The provider answered with a non-success HTTP status.
    pub fn status(code: u16) -> Self {
        Self {
            kind: RerankErrorKind::Status(code),
        }
    }

    /// The call did not finish within its time limit.
    pub fn timeout() -> Self {
        Self {
            kind: RerankErrorKind::Timeout,
        }
    }

    /// The request could not be sent or its reply could not be read.
    pub fn transport() -> Self {
        Self {
            kind: RerankErrorKind::Transport,
        }
    }

    /// The reply was not a valid ranking of the request candidates.
    pub fn malformed() -> Self {
        Self {
            kind: RerankErrorKind::Malformed,
        }
    }

    /// The request or the adapter configuration was refused before any call was made.
    pub fn invalid_request() -> Self {
        Self {
            kind: RerankErrorKind::InvalidRequest,
        }
    }

    /// The HTTP status of a provider refusal, when this is one.
    pub fn status_code(&self) -> Option<u16> {
        match self.kind {
            RerankErrorKind::Status(code) => Some(code),
            _ => None,
        }
    }

    /// Whether the call timed out.
    pub fn is_timeout(&self) -> bool {
        self.kind == RerankErrorKind::Timeout
    }

    /// Whether the request could not be sent or its reply read.
    pub fn is_transport(&self) -> bool {
        self.kind == RerankErrorKind::Transport
    }

    /// Whether the reply was not a valid ranking.
    pub fn is_malformed(&self) -> bool {
        self.kind == RerankErrorKind::Malformed
    }

    /// Whether the request was refused before any call was made.
    pub fn is_invalid_request(&self) -> bool {
        self.kind == RerankErrorKind::InvalidRequest
    }

    /// The failure class as a short phrase: `timeout`, `status <n>`, `malformed`, `transport` or
    /// `invalid request`.
    pub fn class(&self) -> String {
        match self.kind {
            RerankErrorKind::Status(code) => format!("status {code}"),
            RerankErrorKind::Timeout => "timeout".to_owned(),
            RerankErrorKind::Transport => "transport".to_owned(),
            RerankErrorKind::Malformed => "malformed".to_owned(),
            RerankErrorKind::InvalidRequest => "invalid request".to_owned(),
        }
    }
}

impl fmt::Display for RerankError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "rerank failed: {}", self.class())
    }
}

impl std::error::Error for RerankError {}

/// Object-safe asynchronous reranking port.
pub trait Reranker: Send + Sync {
    /// Ranks the request candidates, best first.
    ///
    /// # Errors
    ///
    /// Returns a [`RerankError`] when the call fails or its reply is not a ranking of every
    /// candidate. The candidates are borrowed, so the caller keeps the fused list either way.
    fn rerank<'a>(
        &'a self,
        request: RerankRequest<'a>,
    ) -> BoxFuture<'a, Result<RerankOutput, RerankError>>;
}

/// A no-op reranker that keeps the fused order and reports each candidate's fused score.
#[derive(Debug, Clone, Copy, Default)]
pub struct NoOpReranker;

impl NoOpReranker {
    pub fn new() -> Self {
        Self
    }
}

impl Reranker for NoOpReranker {
    fn rerank<'a>(
        &'a self,
        request: RerankRequest<'a>,
    ) -> BoxFuture<'a, Result<RerankOutput, RerankError>> {
        Box::pin(async move {
            Ok(RerankOutput {
                ranked: request
                    .candidates
                    .iter()
                    .enumerate()
                    .map(|(index, candidate)| Reranked {
                        index,
                        score: candidate.fused_score,
                    })
                    .collect(),
                cost_credits: None,
            })
        })
    }
}

/// Reorders `candidates` by `ranked`, pairing each with the relevance score it was given.
///
/// The candidates are borrowed and cloned into the new order, so a refused ranking leaves the
/// caller holding the fused list it can fall back to.
///
/// # Errors
///
/// Returns a malformed [`RerankError`] when `ranked` is not a permutation of the candidate
/// indices or holds a non-finite score; nothing is repaired by guessing.
pub fn reorder(
    candidates: &[FusedCandidate],
    ranked: &[Reranked],
) -> Result<Vec<(FusedCandidate, f64)>, RerankError> {
    if ranked.len() != candidates.len() || ranked.iter().any(|entry| !entry.score.is_finite()) {
        return Err(RerankError::malformed());
    }
    let mut seen = vec![false; candidates.len()];
    let mut reordered = Vec::with_capacity(candidates.len());
    for entry in ranked {
        let slot = seen
            .get_mut(entry.index)
            .ok_or_else(RerankError::malformed)?;
        if std::mem::replace(slot, true) {
            return Err(RerankError::malformed());
        }
        reordered.push((candidates[entry.index].clone(), entry.score));
    }
    Ok(reordered)
}

#[cfg(test)]
mod tests;
