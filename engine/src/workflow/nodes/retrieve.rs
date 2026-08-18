use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

use crate::pb::lancet::v1::{NodeErrorKind, Notice, NoticeSeverity};
use crate::rerank::Reranker;
use crate::retrieval::{fuse_candidates, fuse_cross_variant_candidates, RetrievalSettings};
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
    index_generation: String,
    embedding_model: String,
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
            index_generation: String::new(),
            embedding_model: String::new(),
        }
    }

    pub fn with_snapshot_metadata(
        mut self,
        index_generation: impl Into<String>,
        embedding_model: impl Into<String>,
    ) -> Self {
        self.index_generation = index_generation.into();
        self.embedding_model = embedding_model.into();
        self
    }

    pub async fn execute(
        &self,
        ctx: &mut WorkflowContext,
        cancel: &CancellationToken,
    ) -> Result<(), NodeError> {
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
                .retrieve_dense(
                    &ctx.original_query,
                    embedding,
                    ctx.filter.as_ref(),
                    cancel,
                )
                .await
            {
                Ok(c) => c,
                Err(err) => return Err(err),
            }
        } else {
            Vec::new()
        };

        ctx.vector_results = dense_candidates
            .iter()
            .map(|c| c.chunk_id.clone())
            .collect();
        ctx.bm25_results.clear();

        // 2. Per-variant BM25 and single-variant fusion pass
        let mut per_variant_fused = Vec::with_capacity(ctx.variants.len());
        for (variant_index, variant) in ctx.variants.iter().enumerate() {
            if cancel.is_cancelled() {
                return Err(NodeError::cancelled());
            }

            let vector_candidates = if variant_index == 0 {
                dense_candidates.clone()
            } else {
                Vec::new()
            };

            let bm25_candidates = if let Some(bm25_port) = &self.bm25_port {
                match bm25_port
                    .retrieve_bm25(variant, ctx.filter.as_ref(), cancel)
                    .await
                {
                    Ok(c) => c,
                    Err(err) => return Err(err),
                }
            } else {
                Vec::new()
            };

            for candidate in &bm25_candidates {
                ctx.bm25_results.push(candidate.chunk_id.clone());
            }

            let fused_i = match fuse_candidates(
                vector_candidates,
                bm25_candidates,
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

            per_variant_fused.push(fused_i);
        }

        // 3. Second pass: cross-variant RRF fusion
        let fused_candidates = match fuse_cross_variant_candidates(
            per_variant_fused,
            &self.settings,
        ) {
            Ok(fused) => fused,
            Err(err) => {
                return Err(NodeError::new(
                    NodeErrorKind::RetrievalFailed,
                    format!("Cross-variant fusion failed: {}", err),
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

        let mut result_hasher = DefaultHasher::new();
        for candidate in &taken_candidates {
            candidate.candidate.chunk_id.hash(&mut result_hasher);
        }

        ctx.evidence_blocks = crate::prompt::assemble_evidence_blocks(&taken_candidates);
        ctx.final_candidates = ctx.evidence_blocks.iter().map(|b| b.chunk_id.clone()).collect();

        ctx.snapshot = Some(crate::pb::lancet::v1::RetrievalSnapshot {
            index_generation: self.index_generation.clone(),
            embedding_model: self.embedding_model.clone(),
            vector_weight: self.settings.vector_weight,
            bm25_weight: self.settings.bm25_weight,
            rrf_k: self.settings.rrf_k as i32,
            candidate_limit: self.settings.candidate_limit as i32,
            final_limit: self.settings.final_limit as i32,
            active_filter: ctx.filter.clone(),
            result_hash: format!("{:x}", result_hasher.finish()),
            variant_count: ctx.variants.len() as u32,
            variant_identities: ctx.variants.clone(),
        });

        // 5. Zero evidence check
        if ctx.final_candidates.is_empty() {
            ctx.add_notice(Notice {
                code: "NO_EVIDENCE".into(),
                message: "No completed corpus evidence matched the requested filters.".into(),
                severity: NoticeSeverity::Info as i32,
            });
        }

        Ok(())
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
            self.execute(ctx, cancel).await
        })
    }
}
