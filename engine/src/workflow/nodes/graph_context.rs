use std::sync::Arc;
use std::time::Duration;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::super::{
    node::{BoxFuture, Node, NodeError, NodeKind, QueryEmbeddingPort},
    notice,
    ports::{GraphQueryOutput, GraphQueryPort},
    WorkflowContext,
};
use crate::pb::lancet::v1::{NodeErrorKind, NoticeCode, NoticeSeverity};

/// How many times the node asks for the query embedding: one try plus one retry (D-152).
///
/// A retry is taken only after a timeout. The per-attempt budget stays
/// `query_embedding_timeout_ms`, so the node can spend this many attempts plus one jitter pause
/// on the embedding alone, and `WorkflowSettings::validate` keeps that sum inside the graph node
/// budget. Raising this number raises that sum, and a non-timeout error is never retried.
pub const QUERY_EMBEDDING_ATTEMPTS: u32 = 2;

/// Upper bound, in milliseconds, of the pause before the query-embedding retry (D-152).
///
/// Small against the 2000 ms attempt, so the pause spreads simultaneous retries without eating
/// the graph budget. Counted once in the nesting rule that `WorkflowSettings::validate` enforces,
/// so raising it needs `graph_node_timeout_ms` raised with it.
pub const RETRY_JITTER_MAX_MS: u64 = 250;

/// Returns the pause, in milliseconds and at most `max_ms`, taken after a failed attempt.
///
/// The value is the first eight bytes of a blake3 hash over the trace id and the attempt number,
/// reduced modulo `max_ms + 1`, so one trace always pauses the same time and different traces
/// spread across the range without a random-number dependency.
pub fn retry_jitter_ms(trace_id: &str, attempt: u32, max_ms: u64) -> u64 {
    let mut hasher = blake3::Hasher::new();
    hasher.update(trace_id.as_bytes());
    hasher.update(&attempt.to_le_bytes());
    let digest = hasher.finalize();
    let mut head = [0_u8; 8];
    head.copy_from_slice(&digest.as_bytes()[..8]);
    u64::from_le_bytes(head) % max_ms.saturating_add(1)
}

pub struct ExtractGraphContextNode {
    embedding_port: Option<Arc<dyn QueryEmbeddingPort>>,
    graph_port: Option<Arc<dyn GraphQueryPort>>,
    embedding_timeout: Duration,
    graph_operation_timeout: Duration,
}

impl ExtractGraphContextNode {
    pub fn new(
        embedding_port: Option<Arc<dyn QueryEmbeddingPort>>,
        graph_port: Option<Arc<dyn GraphQueryPort>>,
    ) -> Self {
        Self {
            embedding_port,
            graph_port,
            embedding_timeout: Duration::from_millis(10000),
            graph_operation_timeout: Duration::from_millis(4000),
        }
    }

    pub fn with_timeouts(
        mut self,
        embedding_timeout_ms: u64,
        graph_operation_timeout_ms: u64,
    ) -> Self {
        self.embedding_timeout = Duration::from_millis(embedding_timeout_ms);
        self.graph_operation_timeout = Duration::from_millis(graph_operation_timeout_ms);
        self
    }
}

impl Default for ExtractGraphContextNode {
    fn default() -> Self {
        Self::new(None, None)
    }
}

impl Node for ExtractGraphContextNode {
    fn kind(&self) -> NodeKind {
        NodeKind::ExtractGraphContext
    }

    fn run<'a>(
        &'a self,
        ctx: &'a mut WorkflowContext,
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<(), NodeError>> {
        Box::pin(async move {
            if cancel.is_cancelled() {
                return Err(NodeError::cancelled());
            }

            if ctx.variants.is_empty() {
                ctx.variants.push(ctx.original_query.clone());
            }

            let variant_zero = &ctx.variants[0];

            // 1. Embedding prelude for variant 0
            //
            // D-125: the vector is read by the dense search and by graph seeding, and by nothing
            // else. A BM25-only request with the graph off needs neither, so it takes no
            // embedding and pays for no Voyage call or timeout. `runs_dense()` reads an
            // unspecified mode as hybrid, so only an explicit BM25-only request is skipped.
            let needs_query_embedding = ctx.runs_dense() || !ctx.disable_graph_context;
            if needs_query_embedding && ctx.query_embedding.is_none() {
                if let Some(embedder) = &self.embedding_port {
                    // D-152: one retry after a timeout, on every arm. Each attempt keeps the
                    // whole per-attempt budget. A first-attempt success never sleeps and never
                    // touches the retry count, so a lever-free record is unchanged.
                    let mut attempt = 1;
                    let vector = loop {
                        let embed_res = tokio::select! {
                            biased;
                            _ = cancel.cancelled() => return Err(NodeError::cancelled()),
                            res = timeout(self.embedding_timeout, embedder.embed_variant_zero(variant_zero, cancel)) => match res {
                                Ok(inner) => inner,
                                Err(_) => Err(NodeError::new(NodeErrorKind::Timeout, "Query embedding timed out")),
                            },
                        };

                        match embed_res {
                            Ok(vector) => break vector,
                            Err(err)
                                if err.kind == NodeErrorKind::Timeout
                                    && attempt < QUERY_EMBEDDING_ATTEMPTS =>
                            {
                                let jitter_ms =
                                    retry_jitter_ms(&ctx.trace_id, attempt, RETRY_JITTER_MAX_MS);
                                ctx.query_embedding_retries += 1;
                                // The event names the attempt and the pause, never the query.
                                tracing::warn!(attempt, jitter_ms, "query_embedding_retry");
                                tokio::select! {
                                    biased;
                                    _ = cancel.cancelled() => return Err(NodeError::cancelled()),
                                    _ = tokio::time::sleep(Duration::from_millis(jitter_ms)) => {}
                                }
                                attempt += 1;
                            }
                            Err(err) => return Err(err),
                        }
                    };
                    ctx.query_embedding = Some(vector);
                }
            }

            // Early return for caller-requested graph ablation
            if ctx.disable_graph_context {
                ctx.graph_context = String::new();
                ctx.graph_facts = Vec::new();
                ctx.add_notice(notice(
                    NoticeCode::GraphAblation,
                    "Graph context disabled by caller request",
                    NoticeSeverity::Info,
                ));
                return Ok(());
            }

            // 2. Graph augmentation operation
            let query_embedding = match &ctx.query_embedding {
                Some(emb) => emb.clone(),
                None => Vec::new(),
            };

            if let Some(graph_port) = &self.graph_port {
                // Mention extraction reads what the user wrote, so the port gets the original
                // question and not a reformulated variant.
                let question = ctx.original_query.clone();
                let graph_res = tokio::select! {
                    biased;
                    _ = cancel.cancelled() => return Err(NodeError::cancelled()),
                    res = timeout(self.graph_operation_timeout, graph_port.query_graph(&question, &query_embedding, cancel)) => match res {
                        Ok(inner) => inner,
                        Err(_) => Err(NodeError::new(NodeErrorKind::Timeout, "GRAPH_TIMEOUT")),
                    },
                };

                match graph_res {
                    Ok(output) => {
                        let GraphQueryOutput {
                            facts,
                            node_count,
                            edge_count,
                            seed_count,
                            path_found,
                            degree_capped_count,
                            seed_document_ids,
                            chunk_candidates,
                        } = output;
                        // D-79: recorded on every completed query, so seeds that found no path
                        // are visible. A graph-off, failed or timed-out query never gets here.
                        ctx.graph_seed_count = seed_count;
                        ctx.graph_path_found = path_found;
                        ctx.graph_degree_capped_count = degree_capped_count;
                        ctx.graph_seed_document_ids = seed_document_ids;
                        ctx.graph_chunk_candidates = chunk_candidates;
                        if facts.is_empty() {
                            ctx.graph_context = String::new();
                            ctx.graph_facts = Vec::new();
                            ctx.graph_node_count = 0;
                            ctx.graph_edge_count = 0;
                            ctx.add_notice(notice(
                                NoticeCode::GraphUnavailable,
                                "Graph query returned no facts for this query",
                                NoticeSeverity::Info,
                            ));
                            crate::telemetry::metrics::record_retrieval_path_failure(
                                crate::telemetry::metrics::PATH_GRAPH,
                                crate::telemetry::metrics::KIND_UNAVAILABLE,
                            );
                        } else {
                            ctx.graph_node_count = node_count;
                            ctx.graph_edge_count = edge_count;
                            // A path fact carries its readable text with the direction of every
                            // hop; a plain triple falls back to the entity -- relation -- entity line.
                            ctx.graph_context = facts
                                .iter()
                                .map(|f| match f.fact.edge_summary() {
                                    Some(path) => path.to_string(),
                                    None => format!(
                                        "{} -- {} -- {}",
                                        f.fact.entity_a_name(),
                                        f.fact.relation_type(),
                                        f.fact.entity_b_name()
                                    ),
                                })
                                .collect::<Vec<_>>()
                                .join("\n");
                            ctx.graph_facts = facts;
                        }
                    }
                    Err(err) => {
                        ctx.graph_context = String::new();
                        ctx.graph_facts = Vec::new();
                        let (code, msg, kind) = if err.kind == NodeErrorKind::Timeout {
                            (
                                NoticeCode::GraphTimeout,
                                if err.message.is_empty() {
                                    "GRAPH_TIMEOUT".to_string()
                                } else {
                                    err.message
                                },
                                crate::telemetry::metrics::KIND_TIMEOUT,
                            )
                        } else {
                            (
                                NoticeCode::GraphDegraded,
                                format!("graph_degrade: {}", err.message),
                                crate::telemetry::metrics::KIND_ERROR,
                            )
                        };
                        ctx.add_notice(notice(code, msg, NoticeSeverity::Info));
                        crate::telemetry::metrics::record_retrieval_path_failure(
                            crate::telemetry::metrics::PATH_GRAPH,
                            kind,
                        );
                        return Ok(());
                    }
                }
            } else {
                ctx.graph_context = String::new();
                ctx.graph_facts = Vec::new();
                ctx.add_notice(notice(
                    NoticeCode::GraphUnavailable,
                    "Graph context is not configured; answer produced from source chunks only",
                    NoticeSeverity::Info,
                ));
                crate::telemetry::metrics::record_retrieval_path_failure(
                    crate::telemetry::metrics::PATH_GRAPH,
                    crate::telemetry::metrics::KIND_UNAVAILABLE,
                );
            }

            Ok(())
        })
    }
}
