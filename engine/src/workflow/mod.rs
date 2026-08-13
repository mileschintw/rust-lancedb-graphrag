pub mod events;
pub mod node;
pub mod nodes;
pub mod runner;

use std::sync::Arc;
use serde::{Deserialize, Serialize};
use tokio_util::sync::CancellationToken;

use crate::pb::lancet::v1::{
    AnswerBasis, DocumentFilter, Notice, QueryRagRequest, QueryRagResponse, RetrievalSnapshot,
    StructuredCitation,
};
use crate::generation::ModelOutput;

pub use events::EventSequence;
pub use node::{BoxFuture, Node, NodeError, QueryEmbeddingPort};
pub use nodes::ReformulateQueryNode;
pub use runner::{WorkflowEventSink, WorkflowRunner};

#[derive(Debug, Clone)]
pub struct WorkflowContext {
    pub session_id: String,
    pub trace_id: String,
    pub original_query: String,
    pub filter: Option<DocumentFilter>,
    pub variants: Vec<String>,
    pub query_embedding: Option<Vec<f32>>,
    pub graph_context: String,
    pub vector_results: Vec<String>,
    pub bm25_results: Vec<String>,
    pub final_candidates: Vec<String>,
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
            vector_results: Vec::new(),
            bm25_results: Vec::new(),
            final_candidates: Vec::new(),
            assembled_prompt: String::new(),
            answer: String::new(),
            citations: Vec::new(),
            answer_basis: AnswerBasis::Unspecified,
            structured_citations: Vec::new(),
            notices: Vec::new(),
            snapshot: None,
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
    }
}

pub struct WorkflowDependencies {
    pub embedding_port: Option<Arc<dyn QueryEmbeddingPort>>,
}

impl WorkflowDependencies {
    pub fn new() -> Self {
        Self {
            embedding_port: None,
        }
    }
}

impl Default for WorkflowDependencies {
    fn default() -> Self {
        Self::new()
    }
}

pub fn run_inline_query_rag_remainder(
    ctx: &mut WorkflowContext,
    deps: &WorkflowDependencies,
    _sink: &WorkflowEventSink,
    cancel: &CancellationToken,
) -> Result<(), NodeError> {
    if cancel.is_cancelled() {
        return Err(NodeError::cancelled());
    }

    if ctx.query_embedding.is_none() && !ctx.variants.is_empty() {
        if let Some(_port) = &deps.embedding_port {
            // Placeholder for tracer bridge embedding call
        }
    }

    Ok(())
}
