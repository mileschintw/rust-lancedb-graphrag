use std::sync::Arc;
use std::time::Duration;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::pb::lancet::v1::{NodeErrorKind, Notice, NoticeSeverity};
use super::super::{
    node::{BoxFuture, Node, NodeError, QueryEmbeddingPort},
    ports::GraphQueryPort,
    WorkflowContext,
};

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
    fn name(&self) -> &'static str {
        "ExtractGraphContext"
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
                        ctx.graph_context = facts;
                    }
                    Err(err) => {
                        ctx.graph_context = String::new();
                        let notice_msg = if err.kind == NodeErrorKind::Timeout {
                            "GRAPH_TIMEOUT".to_string()
                        } else {
                            format!("graph_degrade: {}", err.message)
                        };
                        ctx.notices.push(Notice {
                            code: "GRAPH_TIMEOUT".into(),
                            message: notice_msg,
                            severity: NoticeSeverity::Info as i32,
                        });
                        return Ok(());
                    }
                }
            } else {
                ctx.graph_context = String::new();
            }

            Ok(())
        })
    }
}
