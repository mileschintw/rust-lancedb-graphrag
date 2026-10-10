use std::sync::Arc;
use tokio::sync::RwLock;
use tokio_util::sync::CancellationToken;

use super::node::{BoxFuture, NodeError};
use crate::doc_meta::DocMetaMap;
use crate::graph::index::GraphIndex;
use crate::pb::lancet::v1::DocumentFilter;
use crate::prompt::GraphFactBlock;
use crate::retrieval::bm25::Bm25Index;
use crate::retrieval::Candidate;

pub type Bm25IndexStore = Arc<RwLock<Arc<Bm25Index>>>;

pub fn corpus_generation_from_nodes_version(nodes_version: u64) -> String {
    format!("lance-{nodes_version}")
}

/// One immutable generation of the query-time indexes.
///
/// The BM25 index and the graph index are built together and swapped together inside one new
/// snapshot, so a query that holds an `Arc<CorpusSnapshot>` sees one generation of both and never
/// a mix. Neither index is mutated after the snapshot is built.
#[derive(Clone, Debug)]
pub struct CorpusSnapshot {
    pub bm25: Arc<Bm25Index>,
    /// Name, degree and source-chunk maps for mention seeding and seed-to-seed paths.
    pub graph_index: Arc<GraphIndex>,
    pub generation: String,
    pub nodes_version: u64,
    pub rebuild_degraded: bool,
    /// The publication, document title and date of each document that has them (06.3.6 D-142).
    ///
    /// Immutable for the life of the snapshot, so a query reads one consistent generation and
    /// needs no per-query store read. An empty map means the corpus carries no metadata and the
    /// `evidence_metadata` lever is unavailable. A rebuild carries the prior map forward until a
    /// fresh one replaces it, so an ingest never silently empties it.
    pub doc_meta: Arc<DocMetaMap>,
}

impl CorpusSnapshot {
    pub fn new(
        bm25: Arc<Bm25Index>,
        graph_index: Arc<GraphIndex>,
        nodes_version: u64,
        rebuild_degraded: bool,
    ) -> Self {
        Self {
            bm25,
            graph_index,
            generation: corpus_generation_from_nodes_version(nodes_version),
            nodes_version,
            rebuild_degraded,
            doc_meta: Arc::new(DocMetaMap::default()),
        }
    }

    /// The same snapshot holding `doc_meta` as its per-document evidence metadata.
    pub fn with_doc_meta(mut self, doc_meta: Arc<DocMetaMap>) -> Self {
        self.doc_meta = doc_meta;
        self
    }
}

pub type CorpusStore = Arc<RwLock<Arc<CorpusSnapshot>>>;

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

/// What one graph query hands to the `ExtractGraphContext` node (D-76, D-79).
///
/// `facts` are the seed-to-seed path facts for the prompt. The counts and lists describe how the
/// query went and are recorded on the workflow context for the wire fields and the chunk boost.
/// Seeds found with no path is a valid result: empty `facts`, `path_found = false` and no
/// chunk candidates.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct GraphQueryOutput {
    /// Path facts in rank order, ready for the prompt packer.
    pub facts: Vec<GraphFactBlock>,
    /// Distinct entities on the kept paths (the graph presence count, D-06).
    pub node_count: u32,
    /// Relations on the kept paths: one per hop (the graph presence count, D-06).
    pub edge_count: u32,
    /// Seeds the question mentions matched.
    pub seed_count: u32,
    /// Whether at least one seed-to-seed path was kept.
    pub path_found: bool,
    /// Two-hop paths dropped because their intermediate was above the degree cap.
    pub degree_capped_count: u32,
    /// Document IDs of the seeds' source chunks, sorted and de-duplicated.
    pub seed_document_ids: Vec<String>,
    /// Source-chunk IDs of the entities on the kept paths: the graph chunk candidates.
    pub chunk_candidates: Vec<String>,
}

impl GraphQueryOutput {
    /// An output that carries only facts, counted by their endpoint names and by fact.
    ///
    /// This is the shape a port that knows nothing about seeds or paths returns; the production
    /// port fills every field from the path result instead.
    pub fn from_facts(facts: Vec<GraphFactBlock>) -> Self {
        let mut unique_nodes = std::collections::HashSet::new();
        for fact in &facts {
            unique_nodes.insert(fact.fact.entity_a_name());
            unique_nodes.insert(fact.fact.entity_b_name());
        }
        let node_count = unique_nodes.len() as u32;
        let edge_count = facts.len() as u32;
        Self {
            facts,
            node_count,
            edge_count,
            ..Self::default()
        }
    }
}

pub trait GraphQueryPort: Send + Sync {
    /// Finds the graph facts for one question.
    ///
    /// `question` is the original question text, not a reformulated variant, because mention
    /// extraction reads what the user wrote. `query_embedding` is the variant-zero embedding the
    /// node already computed for retrieval.
    fn query_graph<'a>(
        &'a self,
        question: &'a str,
        query_embedding: &'a [f32],
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<GraphQueryOutput, NodeError>>;
}

pub trait DenseRetrievalPort: Send + Sync {
    fn retrieve_dense<'a>(
        &'a self,
        query: &'a str,
        query_embedding: &'a [f32],
        filter: Option<&'a DocumentFilter>,
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<Candidate>, NodeError>>;

    /// Reads the rows of the given chunk IDs from the same corpus generation as the dense search.
    ///
    /// Used for the graph chunk list (D-76): the rows must come from the snapshot's `nodes`
    /// version, never a later one, so the boost cannot read another generation. Rows come back
    /// in the order of `chunk_ids` with the IDs the generation lacks left out, and carry no
    /// retrieval score. The caller validates the IDs; an implementation that builds a predicate
    /// from them validates them again.
    fn fetch_chunks_by_id<'a>(
        &'a self,
        chunk_ids: &'a [String],
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
    graph_output: Result<GraphQueryOutput, NodeError>,
    stall: bool,
    call_count: std::sync::atomic::AtomicUsize,
    questions: std::sync::Mutex<Vec<String>>,
}

#[cfg(test)]
impl FakeGraphQueryPort {
    pub fn success(facts: impl IntoGraphFacts) -> Self {
        Self::success_output(GraphQueryOutput::from_facts(facts.into_graph_facts()))
    }

    /// A port that returns exactly `output`, seed and path fields included.
    pub fn success_output(output: GraphQueryOutput) -> Self {
        Self {
            graph_output: Ok(output),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
            questions: std::sync::Mutex::new(Vec::new()),
        }
    }

    pub fn failure(err: NodeError) -> Self {
        Self {
            graph_output: Err(err),
            stall: false,
            call_count: std::sync::atomic::AtomicUsize::new(0),
            questions: std::sync::Mutex::new(Vec::new()),
        }
    }

    pub fn failure_with_retryable(retryable: bool) -> Self {
        Self::failure(
            NodeError::new(
                crate::pb::lancet::v1::NodeErrorKind::GraphFailed,
                "synthetic graph query failure",
            )
            .with_retryable(retryable),
        )
    }

    pub fn stall() -> Self {
        Self {
            graph_output: Ok(GraphQueryOutput::default()),
            stall: true,
            call_count: std::sync::atomic::AtomicUsize::new(0),
            questions: std::sync::Mutex::new(Vec::new()),
        }
    }

    pub fn calls(&self) -> usize {
        self.call_count.load(std::sync::atomic::Ordering::Relaxed)
    }

    /// The question text of every call, in call order.
    pub fn questions(&self) -> Vec<String> {
        self.questions.lock().unwrap().clone()
    }
}

#[cfg(test)]
impl GraphQueryPort for FakeGraphQueryPort {
    fn query_graph<'a>(
        &'a self,
        question: &'a str,
        _query_embedding: &'a [f32],
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<GraphQueryOutput, NodeError>> {
        self.call_count
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        self.questions.lock().unwrap().push(question.to_string());
        Box::pin(async move {
            if self.stall {
                tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            }
            self.graph_output.clone()
        })
    }
}

#[cfg(test)]
pub struct FakeDenseRetrievalPort {
    candidates: Result<Vec<Candidate>, NodeError>,
    stall: bool,
    call_count: std::sync::atomic::AtomicUsize,
    /// The rows `fetch_chunks_by_id` can return, whatever the dense search returns.
    chunk_rows: Vec<Candidate>,
    fetch_failure: Option<NodeError>,
    /// The IDs of every `fetch_chunks_by_id` call, in call order.
    fetch_requests: std::sync::Mutex<Vec<Vec<String>>>,
}

#[cfg(test)]
impl FakeDenseRetrievalPort {
    pub fn success(candidates: Vec<Candidate>) -> Self {
        Self::with_candidates(Ok(candidates), false)
    }

    pub fn failure(err: NodeError) -> Self {
        Self::with_candidates(Err(err), false)
    }

    pub fn stall() -> Self {
        Self::with_candidates(Ok(vec![]), true)
    }

    fn with_candidates(candidates: Result<Vec<Candidate>, NodeError>, stall: bool) -> Self {
        Self {
            candidates,
            stall,
            call_count: std::sync::atomic::AtomicUsize::new(0),
            chunk_rows: Vec::new(),
            fetch_failure: None,
            fetch_requests: std::sync::Mutex::new(Vec::new()),
        }
    }

    /// The rows `fetch_chunks_by_id` looks IDs up in.
    pub fn with_chunk_rows(mut self, rows: Vec<Candidate>) -> Self {
        self.chunk_rows = rows;
        self
    }

    /// Makes every `fetch_chunks_by_id` call fail with `err`.
    pub fn with_fetch_failure(mut self, err: NodeError) -> Self {
        self.fetch_failure = Some(err);
        self
    }

    pub fn calls(&self) -> usize {
        self.call_count.load(std::sync::atomic::Ordering::Relaxed)
    }

    /// The ID list of every `fetch_chunks_by_id` call, in call order.
    pub fn fetch_requests(&self) -> Vec<Vec<String>> {
        self.fetch_requests.lock().unwrap().clone()
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

    fn fetch_chunks_by_id<'a>(
        &'a self,
        chunk_ids: &'a [String],
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<Candidate>, NodeError>> {
        self.fetch_requests.lock().unwrap().push(chunk_ids.to_vec());
        Box::pin(async move {
            if let Some(err) = &self.fetch_failure {
                return Err(err.clone());
            }
            // Rows in the order of the request, as the production port returns them.
            Ok(chunk_ids
                .iter()
                .filter_map(|id| self.chunk_rows.iter().find(|row| &row.chunk_id == id))
                .cloned()
                .collect())
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
    /// The error every call fails with.
    failure: Option<crate::rerank::RerankError>,
    stall: bool,
    /// The ranking and cost to answer with instead of the identity ranking.
    scripted: Option<(Vec<crate::rerank::Reranked>, Option<f64>)>,
}

#[cfg(test)]
impl FakeReranker {
    pub fn success() -> Self {
        Self {
            call_count: std::sync::atomic::AtomicUsize::new(0),
            failure: None,
            stall: false,
            scripted: None,
        }
    }

    pub fn failure() -> Self {
        Self::failing_with(crate::rerank::RerankError::transport())
    }

    /// Fails every call with `error`.
    pub fn failing_with(error: crate::rerank::RerankError) -> Self {
        Self {
            failure: Some(error),
            ..Self::success()
        }
    }

    pub fn stall() -> Self {
        Self {
            stall: true,
            ..Self::success()
        }
    }

    /// Answers every call with `ranked` and `cost_credits`, whatever the candidates are.
    pub fn scripted(ranked: Vec<crate::rerank::Reranked>, cost_credits: Option<f64>) -> Self {
        Self {
            scripted: Some((ranked, cost_credits)),
            ..Self::success()
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
        request: crate::rerank::RerankRequest<'a>,
    ) -> BoxFuture<'a, Result<crate::rerank::RerankOutput, crate::rerank::RerankError>> {
        self.call_count
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Box::pin(async move {
            if self.stall {
                tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
            }
            if let Some(error) = &self.failure {
                return Err(error.clone());
            }
            if let Some((ranked, cost_credits)) = &self.scripted {
                return Ok(crate::rerank::RerankOutput {
                    ranked: ranked.clone(),
                    cost_credits: *cost_credits,
                });
            }
            Ok(crate::rerank::RerankOutput {
                ranked: request
                    .candidates
                    .iter()
                    .enumerate()
                    .map(|(index, candidate)| crate::rerank::Reranked {
                        index,
                        score: candidate.fused_score,
                    })
                    .collect(),
                cost_credits: None,
            })
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
            .query_graph("question", &[0.1; 128], &cancel)
            .await
            .unwrap_err();
        assert!(!err_non_retryable.retryable);
        assert_eq!(
            err_non_retryable.kind,
            crate::pb::lancet::v1::NodeErrorKind::GraphFailed
        );

        let port_retryable = FakeGraphQueryPort::failure_with_retryable(true);
        let err_retryable = port_retryable
            .query_graph("question", &[0.1; 128], &cancel)
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
            reranker.rerank(crate::rerank::RerankRequest {
                query: "q",
                candidates: &[],
            }),
        )
        .await;
        assert!(
            res.is_err(),
            "FakeReranker::stall must not complete before timeout"
        );
        assert_eq!(reranker.calls(), 1);
    }
}
