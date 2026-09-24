use std::cell::Cell;
use std::sync::{Arc, Mutex};
use std::time::Instant;
use tokio_util::sync::CancellationToken;

use super::super::{
    node::{BoxFuture, Node, NodeError, NodeKind},
    notice,
    ports::{Bm25RetrievalPort, DenseRetrievalPort},
    WorkflowContext,
};
use crate::pb::lancet::v1::{NodeErrorKind, NoticeCode, NoticeSeverity};
use crate::rerank::Reranker;
use crate::retrieval::{fuse_candidates, fuse_cross_variant_candidates, RetrievalSettings};

pub const DEFAULT_RETRIEVED_EXCERPT_MAX_CHARS: usize = 512;

/// Per-query LanceDB dense sub-stage durations for the `nodes` table.
///
/// `ProductionDenseRetrievalPort::retrieve_dense` (`service.rs`) writes this value once it has
/// timed its own `open_table`/`checkout` calls; `RetrieveHybridNode::execute` reads it back
/// after the dense retrieval call returns to populate the `retrieve_hybrid_substages` event
/// (OI-02, D-64/D-65). This is a task-local side channel rather than a `DenseRetrievalPort`
/// trait change so the port's signature and the node's result/timing contract stay unchanged
/// (06.3.4.1-03 Task 1).
#[derive(Debug, Clone, Copy, Default)]
pub struct DenseSubStageTimings {
    pub open_table_ms: f64,
    pub checkout_ms: f64,
}

tokio::task_local! {
    /// Scoped once per [`RetrieveHybridNode::execute`] call. Reading outside that scope (e.g.
    /// a test exercising `ProductionDenseRetrievalPort` directly) is a benign no-op: the write
    /// in `service.rs` uses `try_with` and silently discards the timing rather than panicking.
    pub static DENSE_SUBSTAGE_TIMINGS: Cell<DenseSubStageTimings>;
}

/// Full per-query RetrieveHybrid sub-stage breakdown, mirroring the fields logged by the
/// `retrieve_hybrid_substages` tracing event. Exposed via
/// [`RetrieveHybridNode::substage_report_handle`] for diagnostic callers (the OI-02 soak bin,
/// `engine/src/bin/retrieval_soak.rs`) that need per-node granularity even when the node is
/// driven indirectly through `WorkflowRunner::run_workflow` (06.3.4.1-03).
#[derive(Debug, Clone, Copy, Default)]
pub struct RetrieveSubStageReport {
    pub open_table_ms: f64,
    pub checkout_ms: f64,
    pub dense_ms: f64,
    pub bm25_ms: f64,
    pub fusion_ms: f64,
    /// Wall time of the whole `execute_inner` body, from just after the cancellation check to
    /// just before it emits this report — i.e. the same span `WorkflowRunner::run_node` times
    /// as the `RetrieveHybrid` node's own duration, available here so a caller driving this
    /// node through `WorkflowRunner` (arm W) gets an equivalent `retrieve_ms` without needing
    /// to wrap the call itself.
    pub total_ms: f64,
}

pub struct RetrieveHybridNode {
    dense_port: Option<Arc<dyn DenseRetrievalPort>>,
    bm25_port: Option<Arc<dyn Bm25RetrievalPort>>,
    reranker: Option<Arc<dyn Reranker>>,
    settings: RetrievalSettings,
    index_generation: String,
    embedding_model: String,
    rebuild_degraded: bool,
    excerpt_max_chars: usize,
    /// Not read by production code. A `Mutex`, not a `Cell`, because `Node: Send + Sync`
    /// requires `Sync` even though in practice each instance serves exactly one request
    /// (`build_production_workflow` constructs a fresh node per `query_rag` call).
    substage_report: Arc<Mutex<RetrieveSubStageReport>>,
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
            rebuild_degraded: false,
            excerpt_max_chars: DEFAULT_RETRIEVED_EXCERPT_MAX_CHARS,
            substage_report: Arc::new(Mutex::new(RetrieveSubStageReport::default())),
        }
    }

    /// Returns a handle to this node's most-recently-completed query's sub-stage timings.
    ///
    /// Call this before handing the node to a [`super::super::runner::WorkflowRunner`] (which
    /// takes ownership) if the caller needs to read the report back afterward.
    pub fn substage_report_handle(&self) -> Arc<Mutex<RetrieveSubStageReport>> {
        Arc::clone(&self.substage_report)
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

    pub fn with_rebuild_degraded(mut self, rebuild_degraded: bool) -> Self {
        self.rebuild_degraded = rebuild_degraded;
        self
    }

    pub fn with_excerpt_max_chars(mut self, max_chars: usize) -> Self {
        self.excerpt_max_chars = max_chars;
        self
    }

    pub async fn execute(
        &self,
        ctx: &mut WorkflowContext,
        cancel: &CancellationToken,
    ) -> Result<(), NodeError> {
        DENSE_SUBSTAGE_TIMINGS
            .scope(
                Cell::new(DenseSubStageTimings::default()),
                self.execute_inner(ctx, cancel),
            )
            .await
    }

    /// The node body proper, scoped by [`execute`](Self::execute) so
    /// [`DENSE_SUBSTAGE_TIMINGS`] is available for the P1 sub-stage tracing event below.
    async fn execute_inner(
        &self,
        ctx: &mut WorkflowContext,
        cancel: &CancellationToken,
    ) -> Result<(), NodeError> {
        let node_start = Instant::now();
        // Reset up front so a caller reading `substage_report_handle()` after an early-return
        // error below (fusion/reranker failure, cancellation) observes zeros rather than a
        // stale report from a prior successful call on this same node instance.
        *self
            .substage_report
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = RetrieveSubStageReport::default();
        if cancel.is_cancelled() {
            return Err(NodeError::cancelled());
        }

        if self.rebuild_degraded {
            ctx.add_notice(notice(
                NoticeCode::IndexRebuildFailed,
                "Corpus index rebuild failed; serving prior generation.",
                NoticeSeverity::Warning,
            ));
        }

        if ctx.variants.is_empty() {
            ctx.variants.push(ctx.original_query.clone());
        }

        // D-33: Seed snapshot with pre-retrieval provenance before any await point.
        // If RetrieveHybrid stalls or fails, this seed survives the dropped node future,
        // allowing emit_terminal_once to attach partial_snapshot to WorkflowCompletedEvent.
        // On the successful path, step 4 below overwrites this seed with the completed snapshot
        // including retrieved chunks and result_hash.
        // An empty result_hash on a partial snapshot is the sentinel distinguishing
        // "never ran to completion" from "completed with 0 results".
        ctx.snapshot = Some(crate::pb::lancet::v1::RetrievalSnapshot {
            index_generation: self.index_generation.clone(),
            embedding_model: self.embedding_model.clone(),
            vector_weight: self.settings.vector_weight,
            bm25_weight: self.settings.bm25_weight,
            rrf_k: self.settings.rrf_k as i32,
            candidate_limit: self.settings.candidate_limit as i32,
            final_limit: self.settings.final_limit as i32,
            active_filter: ctx.filter.clone(),
            result_hash: String::new(),
            variant_count: ctx.variants.len() as u32,
            variant_identities: ctx.variants.clone(),
            retrieved_chunks: Vec::new(),
        });

        let embedding = ctx.query_embedding.as_deref().unwrap_or(&[]);

        // 1. Dense retrieval for variant-zero embedding
        let dense_start = Instant::now();
        let dense_candidates = if let Some(dense_port) = &self.dense_port {
            match dense_port
                .retrieve_dense(&ctx.original_query, embedding, ctx.filter.as_ref(), cancel)
                .await
            {
                Ok(c) => c,
                Err(err) => {
                    let msg = if err.message.is_empty() {
                        err.kind
                            .as_str_name()
                            .trim_start_matches("NODE_ERROR_KIND_")
                            .to_string()
                    } else {
                        format!(
                            "{}: {}",
                            err.kind
                                .as_str_name()
                                .trim_start_matches("NODE_ERROR_KIND_"),
                            err.message
                        )
                    };
                    ctx.add_notice(notice(
                        NoticeCode::RetrievalDegradedDense,
                        msg,
                        NoticeSeverity::Info,
                    ));
                    let kind = match err.kind {
                        NodeErrorKind::Timeout => crate::telemetry::metrics::KIND_TIMEOUT,
                        _ if err.message.to_lowercase().contains("unavailable") => {
                            crate::telemetry::metrics::KIND_UNAVAILABLE
                        }
                        _ => crate::telemetry::metrics::KIND_ERROR,
                    };
                    crate::telemetry::metrics::record_retrieval_path_failure(
                        crate::telemetry::metrics::PATH_DENSE,
                        kind,
                    );
                    Vec::new()
                }
            }
        } else {
            Vec::new()
        };
        let dense_ms = dense_start.elapsed().as_secs_f64() * 1000.0;

        ctx.vector_results = dense_candidates
            .iter()
            .map(|c| c.chunk_id.clone())
            .collect();
        ctx.bm25_results.clear();

        // 2. Per-variant BM25 and single-variant fusion pass
        let variants = ctx.variants.clone();
        let mut per_variant_fused = Vec::with_capacity(variants.len());
        let mut bm25_ms_total = 0.0_f64;
        let mut fusion_ms_total = 0.0_f64;
        for (variant_index, variant) in variants.iter().enumerate() {
            if cancel.is_cancelled() {
                return Err(NodeError::cancelled());
            }

            let vector_candidates = if variant_index == 0 {
                dense_candidates.clone()
            } else {
                Vec::new()
            };

            let bm25_start = Instant::now();
            let bm25_candidates = if let Some(bm25_port) = &self.bm25_port {
                match bm25_port
                    .retrieve_bm25(variant, ctx.filter.as_ref(), cancel)
                    .await
                {
                    Ok(c) => c,
                    Err(err) => {
                        let msg = if err.message.is_empty() {
                            err.kind
                                .as_str_name()
                                .trim_start_matches("NODE_ERROR_KIND_")
                                .to_string()
                        } else {
                            format!(
                                "{}: {}",
                                err.kind
                                    .as_str_name()
                                    .trim_start_matches("NODE_ERROR_KIND_"),
                                err.message
                            )
                        };
                        ctx.add_notice(notice(
                            NoticeCode::RetrievalDegradedBm25,
                            msg,
                            NoticeSeverity::Info,
                        ));
                        let kind = match err.kind {
                            NodeErrorKind::Timeout => crate::telemetry::metrics::KIND_TIMEOUT,
                            _ if err.message.to_lowercase().contains("unavailable") => {
                                crate::telemetry::metrics::KIND_UNAVAILABLE
                            }
                            _ => crate::telemetry::metrics::KIND_ERROR,
                        };
                        crate::telemetry::metrics::record_retrieval_path_failure(
                            crate::telemetry::metrics::PATH_BM25,
                            kind,
                        );
                        Vec::new()
                    }
                }
            } else {
                Vec::new()
            };
            bm25_ms_total += bm25_start.elapsed().as_secs_f64() * 1000.0;

            for candidate in &bm25_candidates {
                ctx.bm25_results.push(candidate.chunk_id.clone());
            }

            let fuse_start = Instant::now();
            let fused_i = match fuse_candidates(vector_candidates, bm25_candidates, &self.settings)
            {
                Ok(fused) => fused,
                Err(err) => {
                    return Err(NodeError::new(
                        NodeErrorKind::RetrievalFailed,
                        format!("Fusion failed: {}", err),
                    ));
                }
            };
            fusion_ms_total += fuse_start.elapsed().as_secs_f64() * 1000.0;

            per_variant_fused.push(fused_i);
        }

        // 3. Second pass: cross-variant RRF fusion
        let cross_fuse_start = Instant::now();
        let fused_candidates =
            match fuse_cross_variant_candidates(per_variant_fused, &self.settings) {
                Ok(fused) => fused,
                Err(err) => {
                    return Err(NodeError::new(
                        NodeErrorKind::RetrievalFailed,
                        format!("Cross-variant fusion failed: {}", err),
                    ));
                }
            };
        fusion_ms_total += cross_fuse_start.elapsed().as_secs_f64() * 1000.0;

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

        let mut result_hasher = blake3::Hasher::new();
        for candidate in &taken_candidates {
            result_hasher.update(candidate.candidate.chunk_id.as_bytes());
            result_hasher.update(b"\x00");
        }

        ctx.evidence_blocks = crate::prompt::assemble_evidence_blocks(&taken_candidates);
        ctx.final_candidates = ctx
            .evidence_blocks
            .iter()
            .map(|b| b.chunk_id.clone())
            .collect();

        let retrieved_chunks: Vec<crate::pb::lancet::v1::StructuredCitation> = ctx
            .evidence_blocks
            .iter()
            .map(|block| {
                let (excerpt, is_truncated) =
                    crate::prompt::bounded_unicode_excerpt(&block.text, self.excerpt_max_chars);
                crate::pb::lancet::v1::StructuredCitation {
                    chunk_id: block.chunk_id.clone(),
                    document_id: block.document_id.clone(),
                    title: block
                        .title
                        .clone()
                        .unwrap_or_else(|| "Untitled Document".into()),
                    section_path: block.section_path.clone().unwrap_or_else(|| "Root".into()),
                    excerpt,
                    is_truncated,
                    score: block.score,
                    rank: block.rank as i32,
                    content_type: block
                        .content_type
                        .clone()
                        .unwrap_or_else(|| "text/plain".into()),
                }
            })
            .collect();

        ctx.snapshot = Some(crate::pb::lancet::v1::RetrievalSnapshot {
            index_generation: self.index_generation.clone(),
            embedding_model: self.embedding_model.clone(),
            vector_weight: self.settings.vector_weight,
            bm25_weight: self.settings.bm25_weight,
            rrf_k: self.settings.rrf_k as i32,
            candidate_limit: self.settings.candidate_limit as i32,
            final_limit: self.settings.final_limit as i32,
            active_filter: ctx.filter.clone(),
            result_hash: result_hasher.finalize().to_hex().to_string(),
            variant_count: ctx.variants.len() as u32,
            variant_identities: ctx.variants.clone(),
            retrieved_chunks,
        });

        // 5. Zero evidence check
        if ctx.final_candidates.is_empty() {
            ctx.add_notice(notice(
                NoticeCode::NoEvidence,
                "No completed corpus evidence matched the requested filters.",
                NoticeSeverity::Info,
            ));
        }

        // P1 production instrumentation (OI-02, D-64/D-65): one structured event per query
        // reporting RetrieveHybrid's sub-stage durations plus tokio's stable runtime counters.
        // Deliberately carries no query text or chunk content (M-LOG-STRUCTURED). Read via
        // `try_with` rather than `with`: this function only ever runs inside the
        // `DENSE_SUBSTAGE_TIMINGS.scope(...)` established by `execute`, so this is always
        // `Ok`, but a direct unit-test call to a private helper should degrade to zero
        // sub-stage timings rather than panic.
        let substage_timings = DENSE_SUBSTAGE_TIMINGS
            .try_with(|cell| cell.get())
            .unwrap_or_default();
        let report = RetrieveSubStageReport {
            open_table_ms: substage_timings.open_table_ms,
            checkout_ms: substage_timings.checkout_ms,
            dense_ms,
            bm25_ms: bm25_ms_total,
            fusion_ms: fusion_ms_total,
            total_ms: node_start.elapsed().as_secs_f64() * 1000.0,
        };
        *self
            .substage_report
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = report;
        let runtime_metrics = tokio::runtime::Handle::current().metrics();
        tracing::info!(
            open_table_ms = report.open_table_ms,
            checkout_ms = report.checkout_ms,
            dense_ms = report.dense_ms,
            bm25_ms = report.bm25_ms,
            fusion_ms = report.fusion_ms,
            alive_tasks = runtime_metrics.num_alive_tasks(),
            global_queue = runtime_metrics.global_queue_depth(),
            "retrieve_hybrid_substages"
        );

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
        Box::pin(async move { self.execute(ctx, cancel).await })
    }
}
