pub mod events;
pub mod levers;
pub mod node;
pub mod nodes;
pub mod ports;
pub mod runner;

use std::sync::Arc;
use tokio_util::sync::CancellationToken;

use crate::generation::ModelOutput;
use crate::pb::lancet::v1::{
    AnswerBasis, DocumentFilter, NodeErrorKind, Notice, NoticeCode, NoticeSeverity,
    QueryRagRequest, QueryRagResponse, RerankMetadata, RetrievalMode, RetrievalSnapshot,
    StructuredCitation,
};

pub use events::EventSequence;
pub use levers::{LeverError, LeverSet};
pub use node::{BoxFuture, Node, NodeError, NodeKind, QueryEmbeddingPort};
pub use nodes::{
    AssemblePromptNode, ExtractGraphContextNode, GenerateAnswerNode, ReformulateQueryNode,
    RetrieveHybridNode,
};
pub use ports::{
    Bm25RetrievalPort, DenseRetrievalPort, GraphQueryOutput, GraphQueryPort, NoOpQueryReformulator,
    QueryReformulator,
};
pub use runner::{WorkflowEventSink, WorkflowRunner};

pub const GRAPH_TIMEOUT: &str = "GRAPH_TIMEOUT";
pub const GRAPH_DEGRADED: &str = "GRAPH_DEGRADED";

/// Builds a [`Notice`] from a typed [`NoticeCode`].
///
/// This is the only permitted constructor for building notices.
/// The string `code` is derived from the enum value's generated string name by trimming
/// the `"NOTICE_CODE_"` prefix, ensuring string-based de-duplication and typed code consistency.
pub fn notice(code: NoticeCode, message: impl Into<String>, severity: NoticeSeverity) -> Notice /* */
{
    Notice {
        code: code
            .as_str_name()
            .trim_start_matches("NOTICE_CODE_")
            .to_string(),
        message: message.into(),
        severity: severity as i32,
        typed_code: code as i32,
    }
}

/// Returns the more conservative (weaker) of two answer bases, using the D-18 ordering
/// retrieval (strongest) > mixed > model_only (weakest). Reconciliation only ever moves
/// toward the weaker end of this order, never the stronger one.
fn weaker_basis(a: AnswerBasis, b: AnswerBasis) -> AnswerBasis {
    fn rank(basis: AnswerBasis) -> u8 {
        match basis {
            AnswerBasis::Retrieval => 2,
            AnswerBasis::Mixed => 1,
            AnswerBasis::ModelOnly | AnswerBasis::Unspecified => 0,
        }
    }
    if rank(a) <= rank(b) {
        a
    } else {
        b
    }
}

/// Lowercase label for an [`AnswerBasis`] used in reconciliation notice messages.
fn basis_label(basis: AnswerBasis) -> &'static str {
    match basis {
        AnswerBasis::Unspecified => "unspecified",
        AnswerBasis::Retrieval => "retrieval",
        AnswerBasis::Mixed => "mixed",
        AnswerBasis::ModelOnly => "model_only",
    }
}

#[derive(Debug, Clone)]
pub struct WorkflowContext {
    pub session_id: String,
    pub trace_id: String,
    pub original_query: String,
    pub filter: Option<DocumentFilter>,
    /// Whether graph context is disabled for this query run.
    ///
    /// Resolved once at admission from the request flag and never re-read from configuration downstream.
    pub disable_graph_context: bool,
    /// Which retrieval paths this query runs (D-99), exactly as the request named it.
    ///
    /// Resolved once at admission. An absent or unrecognised value is `Unspecified`, which
    /// [`runs_dense`](Self::runs_dense) and [`runs_bm25`](Self::runs_bm25) treat as `Hybrid`, and
    /// which the snapshot echoes as `0` so a default request's snapshot bytes do not change.
    pub retrieval_mode: RetrievalMode,
    /// Whether the snapshot carries the pre-rerank candidate ranking (D-100).
    ///
    /// Resolved once at admission from the request flag; `false` leaves the snapshot unchanged.
    pub include_pre_truncation_ranking: bool,
    /// The quality levers this query run switches on (D-136).
    ///
    /// Empty in [`new`](Self::new); set once at admission from the validated request and echoed on
    /// both snapshot literals. Never re-read from the request downstream.
    pub levers: LeverSet,
    /// Retries spent re-embedding the query after a retryable embedding failure (D-52); `0` until
    /// the retry path of a later plan sets it.
    pub query_embedding_retries: u32,
    /// How the rerank attempt ended (D-134); `None` when no rerank was attempted.
    pub rerank: Option<RerankMetadata>,
    /// Whether model-only answers are permitted when no evidence survives retrieval.
    ///
    /// Resolved once at admission in the order request, then configuration, then false (D-10/D-12), and never re-read downstream.
    pub allow_model_only: bool,
    pub variants: Vec<String>,
    pub query_embedding: Option<Vec<f32>>,
    pub graph_context: String,
    pub graph_facts: Vec<crate::prompt::GraphFactBlock>,
    pub vector_results: Vec<String>,
    pub bm25_results: Vec<String>,
    pub final_candidates: Vec<String>,
    pub evidence_blocks: Vec<crate::prompt::EvidenceBlock>,
    pub assembled_prompt: String,
    pub answer: String,
    pub citations: Vec<String>,
    pub answer_basis: AnswerBasis,
    pub structured_citations: Vec<StructuredCitation>,
    pub notices: Vec<Notice>,
    pub snapshot: Option<RetrievalSnapshot>,
    pub graph_node_count: u32,
    pub graph_edge_count: u32,
    /// D-06: counts graph-derived facts that actually reached the assembled prompt (influence).
    /// Distinct from graph_node_count and graph_edge_count, which measure graph presence.
    /// Non-zero presence with zero influence is a valid, expected outcome (e.g. graph weight 0.0 or low priority).
    pub graph_prompt_fact_count: u32,
    /// D-79: seeds the question mentions matched. Set when a graph query completes, so a
    /// graph-off, failed or timed-out query leaves it at `0`.
    pub graph_seed_count: u32,
    /// D-79: whether at least one seed-to-seed path was found. `false` when seeds matched but no
    /// path joined them, and also when the graph did not run.
    pub graph_path_found: bool,
    /// D-79: two-hop paths dropped because their intermediate entity was above the degree cap.
    pub graph_degree_capped_count: u32,
    /// D-79: document IDs of the seed entities' source chunks, sorted and de-duplicated.
    pub graph_seed_document_ids: Vec<String>,
    /// D-79, D-76: source-chunk IDs of the entities on the found paths, for the graph chunk
    /// boost. Empty when no path was found (decision `paths-only`, 06.3.4.1-13).
    pub graph_chunk_candidates: Vec<String>,
    /// D-76, D-81: how many chunks of the final retrieved set the graph list contributed to.
    /// Counted by RetrieveHybrid after the final limit; `0` for a graph-off query and for one
    /// whose graph list was empty, ignored or failed to fetch.
    pub graph_boosted_chunk_count: u32,
    pub generation_attempts: u32,
    pub started_at_ms: i64,
    pub prompt_tokens: u32,
    pub completion_tokens: u32,
}

impl WorkflowContext {
    pub fn new(session_id: String, trace_id: String, request: &QueryRagRequest) -> Self {
        Self {
            session_id,
            trace_id,
            original_query: request.query.clone(),
            filter: request.filter.clone(),
            disable_graph_context: request.disable_graph_context.unwrap_or(false),
            retrieval_mode: request.retrieval_mode(),
            include_pre_truncation_ranking: request.include_pre_truncation_ranking,
            levers: LeverSet::default(),
            query_embedding_retries: 0,
            rerank: None,
            allow_model_only: request.allow_model_only.unwrap_or(false),
            variants: Vec::new(),
            query_embedding: None,
            graph_context: String::new(),
            graph_facts: Vec::new(),
            vector_results: Vec::new(),
            bm25_results: Vec::new(),
            final_candidates: Vec::new(),
            evidence_blocks: Vec::new(),
            assembled_prompt: String::new(),
            answer: String::new(),
            citations: Vec::new(),
            answer_basis: AnswerBasis::Unspecified,
            structured_citations: Vec::new(),
            notices: Vec::new(),
            snapshot: None,
            graph_node_count: 0,
            graph_edge_count: 0,
            graph_prompt_fact_count: 0,
            graph_seed_count: 0,
            graph_path_found: false,
            graph_degree_capped_count: 0,
            graph_seed_document_ids: Vec::new(),
            graph_chunk_candidates: Vec::new(),
            graph_boosted_chunk_count: 0,
            generation_attempts: 0,
            started_at_ms: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_millis() as i64)
                .unwrap_or(0),
            prompt_tokens: 0,
            completion_tokens: 0,
        }
    }

    /// Whether the dense path runs for this query: every mode except `Bm25Only` (D-99).
    pub fn runs_dense(&self) -> bool {
        self.retrieval_mode != RetrievalMode::Bm25Only
    }

    /// Whether the BM25 path runs for this query: every mode except `DenseOnly` (D-99).
    pub fn runs_bm25(&self) -> bool {
        self.retrieval_mode != RetrievalMode::DenseOnly
    }

    pub fn add_notice(&mut self, notice: Notice) {
        if !self
            .notices
            .iter()
            .any(|n| n.code == notice.code && n.message == notice.message)
        {
            self.notices.push(notice);
        }
    }

    pub fn merge_notices(&mut self, new_notices: impl IntoIterator<Item = Notice>) {
        for notice in new_notices {
            self.add_notice(notice);
        }
    }

    pub fn to_query_rag_response(&self) -> QueryRagResponse {
        QueryRagResponse {
            answer: self.answer.clone(),
            citations: self.citations.clone(),
            session_id: self.session_id.clone(),
            answer_basis: self.answer_basis as i32,
            structured_citations: self.structured_citations.clone(),
            notices: self.notices.clone(),
            snapshot: self.snapshot.clone(),
        }
    }

    /// Publishes a validated model output into the context.
    ///
    /// This is the single D-95 render seam: `ctx.answer` becomes the answer plus the engine's
    /// own final `Answer:` line. Every caller validates first: the model-only, repair and
    /// repair-disabled branches of `GenerateAnswerNode`, and the inline generation remainder.
    /// So the rendered line never reaches validation, and both the streamed `answer_chunk` and
    /// the `final_answer` event read the same rendered `ctx.answer`.
    pub fn update_from_model_output(&mut self, output: &ModelOutput) {
        self.answer = output.rendered_answer();
        self.citations = output.cited_evidence_ids.clone();

        if let Some(usage) = &output.usage {
            self.prompt_tokens = usage.prompt_tokens;
            self.completion_tokens = usage.completion_tokens;
        }

        // D-18: conservative-wins reconciliation. The model self-reports a basis; the
        // engine's own observation is deliberately coarse — citations present means "at
        // least as strong as retrieval" (the engine has no independent way to tell
        // Retrieval from Mixed; that is the model's own admission), and citations absent
        // means the answer has no observable grounding left at all. Reconciliation takes
        // the weaker of the two and only ever weakens a claim: a model that self-reports
        // model-only while its citations resolve stays model-only. Conservative-wins still
        // holds at this seam. The one strengthening happens upstream, in `GenerateAnswerNode`:
        // a cited grounded abstention the model labelled model-only arrives here as retrieval,
        // by owner decision in 06.3.5-18, disclosed by the BASIS_RECONCILED notice and the
        // `generation_basis_normalised` event.
        let self_reported = match output.answer_basis {
            crate::generation::AnswerBasis::Retrieval => AnswerBasis::Retrieval,
            crate::generation::AnswerBasis::Mixed => AnswerBasis::Mixed,
            crate::generation::AnswerBasis::ModelOnly => AnswerBasis::ModelOnly,
        };
        let engine_observed = if output.cited_evidence_ids.is_empty() {
            AnswerBasis::ModelOnly
        } else {
            AnswerBasis::Retrieval
        };
        let reconciled = weaker_basis(self_reported, engine_observed);
        if reconciled != self_reported {
            self.add_notice(notice(
                NoticeCode::BasisReconciled,
                format!(
                    "model self-reported basis '{}' but the engine observed '{}'; reconciled to the more conservative basis '{}'",
                    basis_label(self_reported),
                    basis_label(engine_observed),
                    basis_label(reconciled)
                ),
                NoticeSeverity::Info,
            ));
        }
        self.answer_basis = reconciled;

        for n in &output.notices {
            self.add_notice(notice(
                NoticeCode::ModelNotice,
                n.clone(),
                NoticeSeverity::Info,
            ));
        }
        for w in &output.warnings {
            self.add_notice(notice(
                NoticeCode::ModelWarning,
                w.clone(),
                NoticeSeverity::Warning,
            ));
        }
    }
}

/// Derives whether a query run operated in degraded mode (D-31, D-41, §4.2).
///
/// True when any notice in the terminal notice set is in the included code set or when
/// the answer basis is anything other than Retrieval. Excluded codes (NoEvidence, ModelNotice,
/// ModelWarning, CitationRepaired, GraphAblation, and Unspecified) evaluate to false.
///
/// A `BasisReconciled` notice whose message is exactly
/// [`crate::generation::GROUNDED_ABSTENTION_NORMALISED_NOTICE`] discloses a grounded
/// `Insufficient information` answer that cites the evidence it checked, so it does not count
/// (D-158 IN-02). Every other reconciliation still does.
pub fn derive_degraded_mode(
    notices: &[Notice],
    answer_basis: AnswerBasis,
) -> bool {
    if answer_basis != AnswerBasis::Retrieval {
        return true;
    }
    for notice in notices {
        if let Ok(code) = NoticeCode::try_from(notice.typed_code) {
            match code {
                NoticeCode::BasisReconciled => {
                    if notice.message != crate::generation::GROUNDED_ABSTENTION_NORMALISED_NOTICE {
                        return true;
                    }
                }
                NoticeCode::GraphUnavailable
                | NoticeCode::GraphDegraded
                | NoticeCode::GraphTimeout
                | NoticeCode::RetrievalDegradedDense
                | NoticeCode::RetrievalDegradedBm25
                | NoticeCode::RetrievalFailed
                | NoticeCode::CitationDropped
                | NoticeCode::ModelOnly
                | NoticeCode::IndexRebuildFailed
                | NoticeCode::IndexStale
                | NoticeCode::IndexGenerationMismatch
                | NoticeCode::RerankDegraded => return true,
                NoticeCode::Unspecified
                | NoticeCode::NoEvidence
                | NoticeCode::ModelNotice
                | NoticeCode::ModelWarning
                | NoticeCode::CitationRepaired
                | NoticeCode::GraphAblation => {}
            }
        }
    }
    false
}

pub struct WorkflowDependencies {
    pub reformulator: Option<Arc<dyn QueryReformulator>>,
    pub embedding_port: Option<Arc<dyn QueryEmbeddingPort>>,
    pub graph_port: Option<Arc<dyn GraphQueryPort>>,
    pub dense_port: Option<Arc<dyn DenseRetrievalPort>>,
    pub bm25_port: Option<Arc<dyn Bm25RetrievalPort>>,
    pub reranker_port: Option<Arc<dyn crate::rerank::Reranker>>,
    pub generator: Option<Arc<dyn crate::generation::Generator>>,
    pub retrieval_settings: crate::retrieval::RetrievalSettings,
    pub graph_weight: f64,
    pub grounding_limits: crate::generation::GroundingLimits,
}

impl WorkflowDependencies {
    pub fn new() -> Self {
        Self {
            reformulator: None,
            embedding_port: None,
            graph_port: None,
            dense_port: None,
            bm25_port: None,
            reranker_port: None,
            generator: None,
            retrieval_settings: crate::retrieval::RetrievalSettings::default(),
            graph_weight: 0.0,
            grounding_limits: crate::generation::GroundingLimits::default_limits(),
        }
    }
}

impl Default for WorkflowDependencies {
    fn default() -> Self {
        Self::new()
    }
}

pub fn run_inline_prompt_generation_remainder<'a>(
    ctx: &'a mut WorkflowContext,
    deps: &'a WorkflowDependencies,
    sink: &'a WorkflowEventSink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<(), NodeError>> {
    Box::pin(async move {
        if cancel.is_cancelled() {
            return Err(NodeError::cancelled());
        }

        // 1. AssemblePrompt
        let name_prompt = "AssemblePrompt";
        sink.send_event_or_cancel(events::node_started(name_prompt, ""), cancel)
            .await?;

        let evidence_summary = ctx.final_candidates.join("\n");
        ctx.assembled_prompt = if ctx.graph_context.is_empty() {
            format!(
                "Query: {}\nEvidence:\n{}",
                ctx.original_query, evidence_summary
            )
        } else {
            format!(
                "Query: {}\nGraph Context:\n{}\nEvidence:\n{}",
                ctx.original_query, ctx.graph_context, evidence_summary
            )
        };

        sink.send_event_or_cancel(events::node_completed(name_prompt, "", 1), cancel)
            .await?;
        sink.send_checkpoint_or_error("post_assembleprompt", ctx, cancel)?;

        // 2. GenerateAnswer
        let name_gen = "GenerateAnswer";
        sink.send_event_or_cancel(events::node_started(name_gen, ""), cancel)
            .await?;

        if let Some(generator) = &deps.generator {
            let mut gen_req = crate::generation::GenerationRequest::new(
                ctx.original_query.clone(),
                ctx.evidence_blocks.clone(),
            );
            gen_req.graph_facts = ctx.graph_facts.clone();
            gen_req.graph_weight = deps.graph_weight;
            gen_req.allow_model_only = ctx.allow_model_only;
            gen_req.prompt_options = crate::prompt::PromptOptions::from_levers(ctx.levers);
            gen_req.session_id = Some(ctx.session_id.clone());
            gen_req.correlation_id = Some(ctx.trace_id.clone());
            gen_req.cancel = Some(cancel.clone());

            // D-12: Single retry loop for retryable errors
            let mut result = generator.generate(gen_req.clone()).await;
            if let Err(ref err) = result {
                let is_retryable = err.kind == crate::generation::GenerationErrorKind::Timeout
                    || err.kind == crate::generation::GenerationErrorKind::ProviderError;
                if is_retryable && !cancel.is_cancelled() {
                    result = generator.generate(gen_req).await;
                }
            }

            match result {
                Ok(output) => {
                    let limits = deps
                        .grounding_limits
                        .with_allow_model_only(ctx.allow_model_only);
                    let validation_res = if ctx.allow_model_only
                        && output.should_treat_as_model_only(ctx.evidence_blocks.is_empty())
                    {
                        let for_validation = output.into_model_only();
                        for_validation
                            .validate_grounding_with_limits(&ctx.evidence_blocks, limits)
                            .map(|_| for_validation)
                    } else {
                        output
                            .validate_grounding_with_limits(&ctx.evidence_blocks, limits)
                            .map(|_| output)
                    };

                    let validated_output = match validation_res {
                        Ok(out) => out,
                        Err(err) => {
                            let node_err =
                                NodeError::new(NodeErrorKind::LlmGenerationFailed, err.message())
                                    .with_context(
                                        Some(ctx.session_id.clone()),
                                        Some(ctx.trace_id.clone()),
                                    );
                            let _ = sink
                                .send_event_or_cancel(
                                    events::node_failed(
                                        name_gen,
                                        node_err.kind,
                                        &node_err.message,
                                        false,
                                    ),
                                    cancel,
                                )
                                .await;
                            return Err(node_err);
                        }
                    };

                    ctx.update_from_model_output(&validated_output);
                    if ctx.allow_model_only
                        && (ctx.evidence_blocks.is_empty()
                            || ctx.answer_basis == crate::pb::lancet::v1::AnswerBasis::ModelOnly)
                    {
                        ctx.answer_basis = crate::pb::lancet::v1::AnswerBasis::ModelOnly;
                        ctx.citations.clear();
                        ctx.structured_citations.clear();
                        ctx.add_notice(crate::workflow::notice(
                            crate::pb::lancet::v1::NoticeCode::ModelOnly,
                            "Answer generated from parametric model knowledge without corpus evidence.",
                            crate::pb::lancet::v1::NoticeSeverity::Info,
                        ));
                    }
                    sink.send_event_or_cancel(
                        events::answer_chunk(ctx.answer.clone(), true),
                        cancel,
                    )
                    .await?;
                    sink.send_event_or_cancel(events::node_completed(name_gen, "", 10), cancel)
                        .await?;
                    sink.send_checkpoint_or_error("post_generateanswer", ctx, cancel)?;
                }
                Err(err) => {
                    let node_err =
                        NodeError::new(NodeErrorKind::LlmGenerationFailed, err.message())
                            .with_context(Some(ctx.session_id.clone()), Some(ctx.trace_id.clone()));
                    let _ = sink
                        .send_event_or_cancel(
                            events::node_failed(name_gen, node_err.kind, &node_err.message, false),
                            cancel,
                        )
                        .await;
                    return Err(node_err);
                }
            }
        } else {
            let node_err = NodeError::new(
                NodeErrorKind::LlmGenerationFailed,
                "No generator configured for GenerateAnswer remainder",
            )
            .with_context(Some(ctx.session_id.clone()), Some(ctx.trace_id.clone()));
            let _ = sink
                .send_event_or_cancel(
                    events::node_failed(name_gen, node_err.kind, &node_err.message, false),
                    cancel,
                )
                .await;
            return Err(node_err);
        }

        Ok(())
    })
}
