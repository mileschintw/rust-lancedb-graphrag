pub mod events;
pub mod node;
pub mod nodes;
pub mod ports;
pub mod runner;

use std::sync::Arc;
use tokio_util::sync::CancellationToken;

use crate::pb::lancet::v1::{
    AnswerBasis, DocumentFilter, NodeErrorKind, Notice, NoticeSeverity, QueryRagRequest,
    QueryRagResponse, RetrievalSnapshot, StructuredCitation,
};
use crate::generation::ModelOutput;

pub use events::EventSequence;
pub use node::{BoxFuture, Node, NodeError, NodeKind, QueryEmbeddingPort};
pub use nodes::{
    AssemblePromptNode, ExtractGraphContextNode, GenerateAnswerNode, ReformulateQueryNode,
    RetrieveHybridNode,
};
pub use ports::{
    Bm25RetrievalPort, DenseRetrievalPort, GraphQueryPort, NoOpQueryReformulator,
    QueryReformulator,
};
pub use runner::{WorkflowEventSink, WorkflowRunner};

pub const GRAPH_TIMEOUT: &str = "GRAPH_TIMEOUT";
pub const GRAPH_DEGRADED: &str = "GRAPH_DEGRADED";

#[derive(Debug, Clone)]
pub struct WorkflowContext {
    pub session_id: String,
    pub trace_id: String,
    pub original_query: String,
    pub filter: Option<DocumentFilter>,
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
}

impl WorkflowContext {
    pub fn new(session_id: String, trace_id: String, request: &QueryRagRequest) -> Self {
        Self {
            session_id,
            trace_id,
            original_query: request.query.clone(),
            filter: request.filter.clone(),
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
        }
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

    pub fn update_from_model_output(&mut self, output: &ModelOutput) {
        self.answer = output.answer.clone();
        self.citations = output.cited_evidence_ids.clone();
        self.answer_basis = match output.answer_basis {
            crate::generation::AnswerBasis::Retrieval => AnswerBasis::Retrieval,
            crate::generation::AnswerBasis::Mixed => AnswerBasis::Mixed,
            crate::generation::AnswerBasis::ModelOnly => AnswerBasis::ModelOnly,
        };
        for n in &output.notices {
            self.add_notice(Notice {
                code: "NOTICE".into(),
                message: n.clone(),
                severity: NoticeSeverity::Info as i32,
            });
        }
        for w in &output.warnings {
            self.add_notice(Notice {
                code: "WARNING".into(),
                message: w.clone(),
                severity: NoticeSeverity::Warning as i32,
            });
        }
    }
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
            format!("Query: {}\nEvidence:\n{}", ctx.original_query, evidence_summary)
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
                    ctx.update_from_model_output(&output);
                    sink.send_event_or_cancel(events::answer_chunk(ctx.answer.clone(), true), cancel)
                        .await?;
                    sink.send_event_or_cancel(events::node_completed(name_gen, "", 10), cancel)
                        .await?;
                    sink.send_checkpoint_or_error("post_generateanswer", ctx, cancel)?;
                }
                Err(err) => {
                    let node_err = NodeError::new(NodeErrorKind::LlmGenerationFailed, err.message())
                        .with_context(Some(ctx.session_id.clone()), Some(ctx.trace_id.clone()));
                    sink.send_event_or_cancel(
                        events::node_failed(
                            name_gen,
                            node_err.kind.clone(),
                            &node_err.message,
                            false,
                        ),
                        cancel,
                    )
                    .await?;
                    return Err(node_err);
                }
            }
        } else {
            let node_err = NodeError::new(
                NodeErrorKind::LlmGenerationFailed,
                "No generator configured for GenerateAnswer remainder",
            )
            .with_context(Some(ctx.session_id.clone()), Some(ctx.trace_id.clone()));
            sink.send_event_or_cancel(
                events::node_failed(
                    name_gen,
                    node_err.kind.clone(),
                    &node_err.message,
                    false,
                ),
                cancel,
            )
            .await?;
            return Err(node_err);
        }

        Ok(())
    })
}
