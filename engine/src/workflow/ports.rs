use std::sync::Arc;
use tokio_util::sync::CancellationToken;

use crate::pb::lancet::v1::DocumentFilter;
use crate::retrieval::{Candidate, FusedCandidate, RetrievalError, RetrievalErrorKind};
use super::node::{BoxFuture, NodeError};

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
    ) -> BoxFuture<'a, Result<String, NodeError>>;
}

pub trait DenseRetrievalPort: Send + Sync {
    fn retrieve_dense<'a>(
        &'a self,
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

pub struct FakeQueryReformulator {
    variants: Vec<String>,
}

impl FakeQueryReformulator {
    pub fn new(variants: Vec<String>) -> Self {
        Self { variants }
    }
}

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

pub struct FakeQueryEmbeddingPort {
    embedding: Result<Vec<f32>, NodeError>,
    stall: bool,
    call_count: std::sync::atomic::AtomicUsize,
}

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

impl super::node::QueryEmbeddingPort for FakeQueryEmbeddingPort {
    fn embed_variant_zero<'a>(
        &'a self,
        _variant: &'a str,
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<f32>, NodeError>> {
        self.call_count.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Box::pin(async move {
            if self.stall {
                tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            }
            self.embedding.clone()
        })
    }
}

pub struct FakeGraphQueryPort {
    graph_context: Result<String, NodeError>,
    stall: bool,
    call_count: std::sync::atomic::AtomicUsize,
}

impl FakeGraphQueryPort {
    pub fn success(context: impl Into<String>) -> Self {
        Self {
            graph_context: Ok(context.into()),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn failure(err: NodeError) -> Self {
        Self {
            graph_context: Err(err),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn stall() -> Self {
        Self {
            graph_context: Ok(String::new()),
            stall: true,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    pub fn calls(&self) -> usize {
        self.call_count.load(std::sync::atomic::Ordering::Relaxed)
    }
}

impl GraphQueryPort for FakeGraphQueryPort {
    fn query_graph<'a>(
        &'a self,
        _query_embedding: &'a [f32],
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<String, NodeError>> {
        self.call_count.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Box::pin(async move {
            if self.stall {
                tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            }
            self.graph_context.clone()
        })
    }
}

pub struct FakeDenseRetrievalPort {
    candidates: Result<Vec<Candidate>, NodeError>,
    stall: bool,
    call_count: std::sync::atomic::AtomicUsize,
}

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

impl DenseRetrievalPort for FakeDenseRetrievalPort {
    fn retrieve_dense<'a>(
        &'a self,
        _query_embedding: &'a [f32],
        _filter: Option<&'a DocumentFilter>,
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<Candidate>, NodeError>> {
        self.call_count.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Box::pin(async move {
            if self.stall {
                tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            }
            self.candidates.clone()
        })
    }
}

pub struct FakeBm25RetrievalPort {
    candidates_per_query: std::sync::Mutex<Vec<(String, Result<Vec<Candidate>, NodeError>)>>,
    default_candidates: Result<Vec<Candidate>, NodeError>,
    stall: bool,
    call_count: std::sync::atomic::AtomicUsize,
}

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

impl Bm25RetrievalPort for FakeBm25RetrievalPort {
    fn retrieve_bm25<'a>(
        &'a self,
        query: &'a str,
        _filter: Option<&'a DocumentFilter>,
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<Candidate>, NodeError>> {
        self.call_count.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
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

pub struct FakeReranker {
    call_count: std::sync::atomic::AtomicUsize,
    should_fail: bool,
}

impl FakeReranker {
    pub fn success() -> Self {
        Self {
            call_count: std::sync::atomic::AtomicUsize::new(0),
            should_fail: false,
        }
    }

    pub fn failure() -> Self {
        Self {
            call_count: std::sync::atomic::AtomicUsize::new(0),
            should_fail: true,
        }
    }

    pub fn calls(&self) -> usize {
        self.call_count.load(std::sync::atomic::Ordering::Relaxed)
    }
}

impl crate::rerank::Reranker for FakeReranker {
    fn rerank<'a>(
        &'a self,
        candidates: Vec<FusedCandidate>,
    ) -> BoxFuture<'a, Result<Vec<FusedCandidate>, RetrievalError>> {
        self.call_count.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Box::pin(async move {
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
