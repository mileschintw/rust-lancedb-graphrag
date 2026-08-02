//! Provider-neutral async reranking boundary.
//!
//! Phase 03 supplies only the deterministic pass-through implementation. A
//! later reranker can replace it without changing retrieval or evidence types.

use futures::future::BoxFuture;

use crate::retrieval::{FusedCandidate, RetrievalError};

/// Object-safe asynchronous reranking port.
pub trait Reranker: Send + Sync {
    fn rerank<'a>(
        &'a self,
        candidates: Vec<FusedCandidate>,
    ) -> BoxFuture<'a, Result<Vec<FusedCandidate>, RetrievalError>>;
}

/// A no-op reranker that preserves candidate order and every field byte-for-byte.
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
        candidates: Vec<FusedCandidate>,
    ) -> BoxFuture<'a, Result<Vec<FusedCandidate>, RetrievalError>> {
        Box::pin(async move { Ok(candidates) })
    }
}

#[cfg(test)]
mod tests;
