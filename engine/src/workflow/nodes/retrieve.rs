use std::sync::Arc;
use tokio_util::sync::CancellationToken;

use crate::pb::lancet::v1::{NodeErrorKind, Notice, NoticeSeverity};
use crate::rerank::Reranker;
use crate::retrieval::{fuse_variant_candidates, RetrievalSettings};
use super::super::{
    node::{BoxFuture, Node, NodeError, NodeKind},
    ports::{Bm25RetrievalPort, DenseRetrievalPort},
    WorkflowContext,
};

pub struct RetrieveHybridNode {
    dense_port: Option<Arc<dyn DenseRetrievalPort>>,
    bm25_port: Option<Arc<dyn Bm25RetrievalPort>>,
    reranker: Option<Arc<dyn Reranker>>,
    settings: RetrievalSettings,
}

impl RetrieveHybridNode {
    pub fn new(
        dense_port: Option<Arc<dyn DenseRetrievalPort>>,
        bm25_port: Option<Arc<dyn Bm25RetrievalPort>>,
        reranker: Option<Arc<dyn Reranker>>,
        settings: RetrievalSettings,
    ) -> Self {
        Self {
            dense_port,
            bm25_port,
            reranker,
            settings,
        }
    }
}

impl Default for RetrieveHybridNode {
    fn default() -> Self {
        Self::new(None, None, None, RetrievalSettings::default())
    }
}

impl Node for RetrieveHybridNode {
    fn kind(&self) -> NodeKind {
        NodeKind::RetrieveHybrid
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

            let embedding = ctx.query_embedding.as_deref().unwrap_or(&[]);

            // 1. Dense retrieval for variant-zero embedding
            let dense_candidates = if let Some(dense_port) = &self.dense_port {
                match dense_port
                    .retrieve_dense(embedding, ctx.filter.as_ref(), cancel)
                    .await
                {
                    Ok(c) => c,
                    Err(err) => return Err(err),
                }
            } else {
                Vec::new()
            };

            // 2. BM25 retrieval for each variant
            let mut bm25_per_variant = Vec::with_capacity(ctx.variants.len());
            if let Some(bm25_port) = &self.bm25_port {
                for variant in &ctx.variants {
                    if cancel.is_cancelled() {
                        return Err(NodeError::cancelled());
                    }
                    match bm25_port
                        .retrieve_bm25(variant, ctx.filter.as_ref(), cancel)
                        .await
                    {
                        Ok(c) => bm25_per_variant.push(c),
                        Err(err) => return Err(err),
                    }
                }
            } else {
                for _ in &ctx.variants {
                    bm25_per_variant.push(Vec::new());
                }
            }

            // Record raw results in context
            ctx.vector_results = dense_candidates
                .iter()
                .map(|c| c.chunk_id.clone())
                .collect();
            ctx.bm25_results = bm25_per_variant
                .iter()
                .flat_map(|v| v.iter().map(|c| c.chunk_id.clone()))
                .collect();

            // 3. Fusion
            let fused_candidates = match fuse_variant_candidates(
                dense_candidates,
                bm25_per_variant,
                &self.settings,
            ) {
                Ok(fused) => fused,
                Err(err) => {
                    return Err(NodeError::new(
                        NodeErrorKind::RetrievalFailed,
                        format!("Fusion failed: {}", err),
                    ));
                }
            };

            // 4. Reranking
            let final_fused = if let Some(reranker) = &self.reranker {
                match reranker.rerank(fused_candidates).await {
                    Ok(reranked) => reranked,
                    Err(err) => {
                        return Err(NodeError::new(
                            NodeErrorKind::RetrievalFailed,
                            format!("Reranker failure: {}", err),
                        ));
                    }
                }
            } else {
                fused_candidates
            };

            let taken_candidates: Vec<_> = final_fused
                .into_iter()
                .take(self.settings.final_limit)
                .collect();

            ctx.evidence_blocks = crate::prompt::assemble_evidence_blocks(&taken_candidates);
            ctx.final_candidates = ctx.evidence_blocks.iter().map(|b| b.chunk_id.clone()).collect();

            ctx.snapshot = Some(crate::pb::lancet::v1::RetrievalSnapshot {
                index_generation: "".into(),
                embedding_model: "".into(),
                vector_weight: self.settings.vector_weight,
                bm25_weight: self.settings.bm25_weight,
                rrf_k: self.settings.rrf_k as i32,
                candidate_limit: self.settings.candidate_limit as i32,
                final_limit: self.settings.final_limit as i32,
                active_filter: ctx.filter.clone(),
                result_hash: "".into(),
            });

            // 5. Zero evidence check
            if ctx.final_candidates.is_empty() {
                ctx.notices.push(Notice {
                    code: "NO_EVIDENCE".into(),
                    message: "No completed corpus evidence matched the requested filters.".into(),
                    severity: NoticeSeverity::Info as i32,
                });
            }

            Ok(())
        })
    }
}
