use std::sync::Arc;
use tokio::sync::RwLock;
use tokio_util::sync::CancellationToken;

use super::node::{BoxFuture, NodeError};
use crate::pb::lancet::v1::DocumentFilter;
use crate::prompt::GraphFactBlock;
use crate::retrieval::bm25::Bm25Index;
use crate::retrieval::Candidate;
#[cfg(test)]
use crate::retrieval::{FusedCandidate, RetrievalError, RetrievalErrorKind};

pub type Bm25IndexStore = Arc<RwLock<Arc<Bm25Index>>>;

pub trait QueryReformulator: Send + Sync {
    fn reformulate<'a>(
        &'a self,
        query: &'a str,
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<String>, NodeError>>;
}

pub struct NoOpQueryReformulator;

impl NoOpQueryReformulator {
    pub fn new() -> Self {
        Self
    }
}

impl Default for NoOpQueryReformulator {
    fn default() -> Self {
        Self::new()
    }
}

impl QueryReformulator for NoOpQueryReformulator {
    fn reformulate<'a>(
        &'a self,
        query: &'a str,
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<String>, NodeError>> {
        Box::pin(async move { Ok(vec![query.to_string()]) })
    }
}

pub trait GraphQueryPort: Send + Sync {
    fn query_graph<'a>(
        &'a self,
        query_embedding: &'a [f32],
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<GraphFactBlock>, NodeError>>;
}

pub trait DenseRetrievalPort: Send + Sync {
    fn retrieve_dense<'a>(
        &'a self,
        query: &'a str,
        query_embedding: &'a [f32],
        filter: Option<&'a DocumentFilter>,
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<Candidate>, NodeError>>;
}

pub trait Bm25RetrievalPort: Send + Sync {
    fn retrieve_bm25<'a>(
        &'a self,
        query: &'a str,
        filter: Option<&'a DocumentFilter>,
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<Candidate>, NodeError>>;
}

// ---------------------------------------------------------------------------
// Request-Local Fake Implementations for Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
pub struct FakeQueryReformulator {
    variants: Vec<String>,
}

#[cfg(test)]
impl FakeQueryReformulator {
    pub fn new(variants: Vec<String>) -> Self {
        Self { variants }
    }
}

#[cfg(test)]
impl QueryReformulator for FakeQueryReformulator {
    fn reformulate<'a>(
        &'a self,
        _query: &'a str,
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<String>, NodeError>> {
        let variants = self.variants.clone();
        Box::pin(async move { Ok(variants) })
    }
}

#[cfg(test)]
pub struct FakeQueryEmbeddingPort {
    embedding: Result<Vec<f32>, NodeError>,
    stall: bool,
    call_count: std::sync::atomic::AtomicUsize,
}

#[cfg(test)]
impl FakeQueryEmbeddingPort {
    pub fn success(embedding: Vec<f32>) -> Self {
        Self {
            embedding: Ok(embedding),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn failure(err: NodeError) -> Self {
        Self {
            embedding: Err(err),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn stall() -> Self {
        Self {
            embedding: Ok(vec![]),
            stall: true,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn calls(&self) -> usize {
        self.call_count.load(std::sync::atomic::Ordering::Relaxed)
    }
}

#[cfg(test)]
impl super::node::QueryEmbeddingPort for FakeQueryEmbeddingPort {
    fn embed_variant_zero<'a>(
        &'a self,
        _variant: &'a str,
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<f32>, NodeError>> {
        self.call_count
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Box::pin(async move {
            if self.stall {
                tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            }
            self.embedding.clone()
        })
    }
}

#[cfg(test)]
pub trait IntoGraphFacts {
    fn into_graph_facts(self) -> Vec<crate::prompt::GraphFactBlock>;
}

#[cfg(test)]
impl IntoGraphFacts for Vec<crate::prompt::GraphFactBlock> {
    fn into_graph_facts(self) -> Vec<crate::prompt::GraphFactBlock> {
        self
    }
}

#[cfg(test)]
impl IntoGraphFacts for &[crate::prompt::GraphFactBlock] {
    fn into_graph_facts(self) -> Vec<crate::prompt::GraphFactBlock> {
        self.to_vec()
    }
}

#[cfg(test)]
impl IntoGraphFacts for &str {
    fn into_graph_facts(self) -> Vec<crate::prompt::GraphFactBlock> {
        let parts: Vec<&str> = self.split("--").map(|s| s.trim()).collect();
        let fact = if parts.len() >= 3 {
            crate::graph::context_strategy::GraphFact::new(parts[0], parts[1], parts[2], None, 1.0)
        } else {
            crate::graph::context_strategy::GraphFact::new(self, "related_to", self, None, 1.0)
        };
        vec![crate::prompt::GraphFactBlock { fact }]
    }
}

#[cfg(test)]
impl IntoGraphFacts for String {
    fn into_graph_facts(self) -> Vec<crate::prompt::GraphFactBlock> {
        self.as_str().into_graph_facts()
    }
}

#[cfg(test)]
impl IntoGraphFacts for Vec<String> {
    fn into_graph_facts(self) -> Vec<crate::prompt::GraphFactBlock> {
        self.iter()
            .flat_map(|s| s.as_str().into_graph_facts())
            .collect()
    }
}

#[cfg(test)]
impl IntoGraphFacts for Vec<&str> {
    fn into_graph_facts(self) -> Vec<crate::prompt::GraphFactBlock> {
        self.into_iter()
            .flat_map(|s| s.into_graph_facts())
            .collect()
    }
}

#[cfg(test)]
pub struct FakeGraphQueryPort {
    graph_facts: Result<Vec<crate::prompt::GraphFactBlock>, NodeError>,
    stall: bool,
    call_count: std::sync::atomic::AtomicUsize,
}

#[cfg(test)]
impl FakeGraphQueryPort {
    pub fn success(facts: impl IntoGraphFacts) -> Self {
        Self {
            graph_facts: Ok(facts.into_graph_facts()),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn failure(err: NodeError) -> Self {
        Self {
            graph_facts: Err(err),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn failure_with_retryable(retryable: bool) -> Self {
        Self {
            graph_facts: Err(NodeError::new(
                crate::pb::lancet::v1::NodeErrorKind::GraphFailed,
                "synthetic graph query failure",
            )
            .with_retryable(retryable)),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn stall() -> Self {
        Self {
            graph_facts: Ok(vec![]),
            stall: true,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn calls(&self) -> usize {
        self.call_count.load(std::sync::atomic::Ordering::Relaxed)
    }
}

#[cfg(test)]
impl GraphQueryPort for FakeGraphQueryPort {
    fn query_graph<'a>(
        &'a self,
        _query_embedding: &'a [f32],
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<crate::prompt::GraphFactBlock>, NodeError>> {
        self.call_count
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Box::pin(async move {
            if self.stall {
                tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            }
            self.graph_facts.clone()
        })
    }
}

#[cfg(test)]
pub struct FakeDenseRetrievalPort {
    candidates: Result<Vec<Candidate>, NodeError>,
    stall: bool,
    call_count: std::sync::atomic::AtomicUsize,
}

#[cfg(test)]
impl FakeDenseRetrievalPort {
    pub fn success(candidates: Vec<Candidate>) -> Self {
        Self {
            candidates: Ok(candidates),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn failure(err: NodeError) -> Self {
        Self {
            candidates: Err(err),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn stall() -> Self {
        Self {
            candidates: Ok(vec![]),
            stall: true,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn calls(&self) -> usize {
        self.call_count.load(std::sync::atomic::Ordering::Relaxed)
    }
}

#[cfg(test)]
impl DenseRetrievalPort for FakeDenseRetrievalPort {
    fn retrieve_dense<'a>(
        &'a self,
        _query: &'a str,
        _query_embedding: &'a [f32],
        _filter: Option<&'a DocumentFilter>,
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<Candidate>, NodeError>> {
        self.call_count
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Box::pin(async move {
            if self.stall {
                tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            }
            self.candidates.clone()
        })
    }
}

#[cfg(test)]
pub struct FakeBm25RetrievalPort {
    candidates_per_query: std::sync::Mutex<Vec<(String, Result<Vec<Candidate>, NodeError>)>>,
    default_candidates: Result<Vec<Candidate>, NodeError>,
    stall: bool,
    call_count: std::sync::atomic::AtomicUsize,
}

#[cfg(test)]
impl FakeBm25RetrievalPort {
    pub fn success(candidates: Vec<Candidate>) -> Self {
        Self {
            candidates_per_query: std::sync::Mutex::new(Vec::new()),
            default_candidates: Ok(candidates),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn with_map(map: Vec<(String, Result<Vec<Candidate>, NodeError>)>) -> Self {
        Self {
            candidates_per_query: std::sync::Mutex::new(map),
            default_candidates: Ok(vec![]),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn failure(err: NodeError) -> Self {
        Self {
            candidates_per_query: std::sync::Mutex::new(Vec::new()),
            default_candidates: Err(err),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn stall() -> Self {
        Self {
            candidates_per_query: std::sync::Mutex::new(Vec::new()),
            default_candidates: Ok(vec![]),
            stall: true,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn calls(&self) -> usize {
        self.call_count.load(std::sync::atomic::Ordering::Relaxed)
    }
}

#[cfg(test)]
impl Bm25RetrievalPort for FakeBm25RetrievalPort {
    fn retrieve_bm25<'a>(
        &'a self,
        query: &'a str,
        _filter: Option<&'a DocumentFilter>,
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<Candidate>, NodeError>> {
        self.call_count
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let query_str = query.to_string();
        Box::pin(async move {
            if self.stall {
                tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            }
            let map = self.candidates_per_query.lock().unwrap();
            for (q, res) in map.iter() {
                if q == &query_str {
                    return res.clone();
                }
            }
            self.default_candidates.clone()
        })
    }
}

#[cfg(test)]
pub struct FakeReranker {
    call_count: std::sync::atomic::AtomicUsize,
    should_fail: bool,
    stall: bool,
}

#[cfg(test)]
impl FakeReranker {
    pub fn success() -> Self {
        Self {
            call_count: std::sync::atomic::AtomicUsize::new(0),
            should_fail: false,
            stall: false,
        }
    }

    pub fn failure() -> Self {
        Self {
            call_count: std::sync::atomic::AtomicUsize::new(0),
            should_fail: true,
            stall: false,
        }
    }

    pub fn stall() -> Self {
        Self {
            call_count: std::sync::atomic::AtomicUsize::new(0),
            should_fail: false,
            stall: true,
        }
    }

    pub fn calls(&self) -> usize {
        self.call_count.load(std::sync::atomic::Ordering::Relaxed)
    }
}

#[cfg(test)]
impl crate::rerank::Reranker for FakeReranker {
    fn rerank<'a>(
        &'a self,
        candidates: Vec<FusedCandidate>,
    ) -> BoxFuture<'a, Result<Vec<FusedCandidate>, RetrievalError>> {
        self.call_count
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Box::pin(async move {
            if self.stall {
                tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            }
            if self.should_fail {
                Err(RetrievalError::new(
                    RetrievalErrorKind::Snapshot,
                    "deterministic fake reranker failure",
                ))
            } else {
                Ok(candidates)
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rerank::Reranker;

    #[tokio::test]
    async fn fake_graph_query_port_failure_with_retryable_flag() {
        let cancel = CancellationToken::new();
        let port_non_retryable = FakeGraphQueryPort::failure_with_retryable(false);
        let err_non_retryable = port_non_retryable
            .query_graph(&[0.1; 128], &cancel)
            .await
            .unwrap_err();
        assert!(!err_non_retryable.retryable);
        assert_eq!(
            err_non_retryable.kind,
            crate::pb::lancet::v1::NodeErrorKind::GraphFailed
        );

        let port_retryable = FakeGraphQueryPort::failure_with_retryable(true);
        let err_retryable = port_retryable
            .query_graph(&[0.1; 128], &cancel)
            .await
            .unwrap_err();
        assert!(err_retryable.retryable);
        assert_eq!(
            err_retryable.kind,
            crate::pb::lancet::v1::NodeErrorKind::GraphFailed
        );
    }

    #[tokio::test]
    async fn fake_reranker_stall_can_be_cancelled() {
        let reranker = FakeReranker::stall();
        let res = tokio::time::timeout(
            std::time::Duration::from_millis(50),
            reranker.rerank(vec![]),
        )
        .await;
        assert!(res.is_err(), "FakeReranker::stall must not complete before timeout");
        assert_eq!(reranker.calls(), 1);
    }
}
