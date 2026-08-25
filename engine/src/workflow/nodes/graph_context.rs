use std::sync::Arc;
use std::time::Duration;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::super::{
    node::{BoxFuture, Node, NodeError, NodeKind, QueryEmbeddingPort},
    notice,
    ports::GraphQueryPort,
    WorkflowContext,
};
use crate::pb::lancet::v1::{NodeErrorKind, NoticeCode, NoticeSeverity};

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
            if ctx.query_embedding.is_none() {
                if let Some(embedder) = &self.embedding_port {
                    let embed_res = tokio::select! {
                        biased;
                        _ = cancel.cancelled() => return Err(NodeError::cancelled()),
                        res = timeout(self.embedding_timeout, embedder.embed_variant_zero(variant_zero, cancel)) => match res {
                            Ok(inner) => inner,
                            Err(_) => Err(NodeError::new(NodeErrorKind::Timeout, "Query embedding timed out")),
                        },
                    };

                    match embed_res {
                        Ok(vector) => {
                            ctx.query_embedding = Some(vector);
                        }
                        Err(err) => {
                            return Err(err);
                        }
                    }
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
                let graph_res = tokio::select! {
                    biased;
                    _ = cancel.cancelled() => return Err(NodeError::cancelled()),
                    res = timeout(self.graph_operation_timeout, graph_port.query_graph(&query_embedding, cancel)) => match res {
                        Ok(inner) => inner,
                        Err(_) => Err(NodeError::new(NodeErrorKind::Timeout, "GRAPH_TIMEOUT")),
                    },
                };

                match graph_res {
                    Ok(facts) => {
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
                            let mut unique_nodes = std::collections::HashSet::new();
                            for f in &facts {
                                unique_nodes.insert(f.fact.entity_a_name());
                                unique_nodes.insert(f.fact.entity_b_name());
                            }
                            ctx.graph_node_count = unique_nodes.len() as u32;
                            ctx.graph_edge_count = facts.len() as u32;
                            ctx.graph_context = facts
                                .iter()
                                .map(|f| {
                                    format!(
                                        "{} -- {} -- {}",
                                        f.fact.entity_a_name(),
                                        f.fact.relation_type(),
                                        f.fact.entity_b_name()
                                    )
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
