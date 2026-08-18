use std::sync::Arc;
use tokio_util::sync::CancellationToken;

use crate::generation::{
    GenerationErrorKind, GenerationRequest, Generator, GroundingLimits,
};
use crate::pb::lancet::v1::NodeErrorKind;
use crate::prompt::resolve_citations_with_max_chars;
use super::super::{
    node::{BoxFuture, Node, NodeError, NodeKind},
    WorkflowContext,
};

pub struct GenerateAnswerNode {
    generator: Option<Arc<dyn Generator>>,
    grounding_limits: GroundingLimits,
    citation_excerpt_max_chars: usize,
    graph_weight: f64,
}

impl GenerateAnswerNode {
    pub fn new(generator: Option<Arc<dyn Generator>>) -> Self {
        Self {
            generator,
            grounding_limits: GroundingLimits::default_limits(),
            citation_excerpt_max_chars: 200,
            graph_weight: 1.0,
        }
    }

    pub fn with_settings(
        mut self,
        grounding_limits: GroundingLimits,
        citation_excerpt_max_chars: usize,
        graph_weight: f64,
    ) -> Self {
        self.grounding_limits = grounding_limits;
        self.citation_excerpt_max_chars = citation_excerpt_max_chars;
        self.graph_weight = graph_weight;
        self
    }
}

impl Default for GenerateAnswerNode {
    fn default() -> Self {
        Self::new(None)
    }
}

impl Node for GenerateAnswerNode {
    fn kind(&self) -> NodeKind {
        NodeKind::GenerateAnswer
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

            let generator = match &self.generator {
                Some(g) => g,
                None => {
                    return Err(NodeError::new(
                        NodeErrorKind::LlmGenerationFailed,
                        "No generator configured for GenerateAnswer node",
                    ));
                }
            };

            let mut req = GenerationRequest::new(
                ctx.original_query.clone(),
                ctx.evidence_blocks.clone(),
            );
            req.graph_facts = ctx.graph_facts.clone();
            req.graph_weight = self.graph_weight;
            req.session_id = Some(ctx.session_id.clone());
            req.correlation_id = Some(ctx.trace_id.clone());
            req.cancel = Some(cancel.clone());

            let request_snapshot = req;

            // Attempt 1
            let result1 = generator.generate(request_snapshot.clone()).await;

            let final_result = match result1 {
                Ok(output) => Ok(output),
                Err(err1) => {
                    if cancel.is_cancelled() || err1.kind == GenerationErrorKind::Cancelled {
                        return Err(NodeError::cancelled()
                            .with_context(Some(ctx.session_id.clone()), Some(ctx.trace_id.clone())));
                    }

                    // Only retry transient errors (Timeout and transient ProviderError)
                    let is_retryable = err1.kind == GenerationErrorKind::Timeout
                        || err1.kind == GenerationErrorKind::ProviderError;

                    if !is_retryable {
                        Err(err1)
                    } else {
                        // Retry attempt 2 immediately with byte-identical request snapshot
                        if cancel.is_cancelled() {
                            return Err(NodeError::cancelled()
                                .with_context(Some(ctx.session_id.clone()), Some(ctx.trace_id.clone())));
                        }
                        generator.generate(request_snapshot.clone()).await
                    }
                }
            };

            match final_result {
                Ok(output) => {
                    output
                        .validate_grounding_with_limits(&ctx.evidence_blocks, self.grounding_limits)
                        .map_err(|err| {
                            NodeError::new(NodeErrorKind::LlmGenerationFailed, err.message())
                                .with_context(
                                    Some(ctx.session_id.clone()),
                                    Some(ctx.trace_id.clone()),
                                )
                        })?;
                    ctx.update_from_model_output(&output);
                    let resolved_citations = resolve_citations_with_max_chars(
                        &ctx.citations,
                        &ctx.evidence_blocks,
                        self.citation_excerpt_max_chars,
                    );
                    if resolved_citations.len() != ctx.citations.len() {
                        return Err(NodeError::new(
                            NodeErrorKind::LlmGenerationFailed,
                            "failed to resolve all cited evidence identities completely",
                        )
                        .with_context(
                            Some(ctx.session_id.clone()),
                            Some(ctx.trace_id.clone()),
                        ));
                    }
                    ctx.structured_citations = resolved_citations
                        .iter()
                        .map(|c| crate::pb::lancet::v1::StructuredCitation {
                            chunk_id: c.chunk_id.clone(),
                            document_id: c.document_id.clone(),
                            title: c.title.as_deref().unwrap_or("Untitled Document").to_string(),
                            section_path: c.section_path.as_deref().unwrap_or("Root").to_string(),
                            excerpt: c.bounded_excerpt.clone(),
                            is_truncated: c.is_truncated,
                            score: c.score,
                            rank: c.rank as i32,
                            content_type: c.content_type.clone(),
                        })
                        .collect();
                    Ok(())
                }
                Err(err) => {
                    if cancel.is_cancelled() || err.kind == GenerationErrorKind::Cancelled {
                        return Err(NodeError::cancelled()
                            .with_context(Some(ctx.session_id.clone()), Some(ctx.trace_id.clone())));
                    }
                    let node_kind = match err.kind {
                        GenerationErrorKind::Timeout => NodeErrorKind::Timeout,
                        _ => NodeErrorKind::LlmGenerationFailed,
                    };
                    Err(NodeError::new(node_kind, err.message())
                        .with_retryable(false)
                        .with_context(Some(ctx.session_id.clone()), Some(ctx.trace_id.clone())))
                }
            }
        })
    }
}
