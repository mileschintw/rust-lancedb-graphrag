use std::sync::Arc;
use tokio_util::sync::CancellationToken;

use crate::generation::{GenerationErrorKind, GenerationRequest, Generator};
use crate::pb::lancet::v1::NodeErrorKind;
use crate::prompt::resolve_citations;
use super::super::{
    node::{BoxFuture, Node, NodeError},
    WorkflowContext,
};

pub struct GenerateAnswerNode {
    generator: Option<Arc<dyn Generator>>,
}

impl GenerateAnswerNode {
    pub fn new(generator: Option<Arc<dyn Generator>>) -> Self {
        Self { generator }
    }
}

impl Default for GenerateAnswerNode {
    fn default() -> Self {
        Self::new(None)
    }
}

impl Node for GenerateAnswerNode {
    fn name(&self) -> &'static str {
        "GenerateAnswer"
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
            req.session_id = Some(ctx.session_id.clone());
            req.correlation_id = Some(ctx.trace_id.clone());

            let request_snapshot = req;

            // Attempt 1
            let result1 = generator.generate(request_snapshot.clone()).await;

            let final_result = match result1 {
                Ok(output) => Ok(output),
                Err(err1) => {
                    if cancel.is_cancelled() {
                        return Err(NodeError::cancelled());
                    }

                    // Non-retryable errors
                    if err1.kind == GenerationErrorKind::InvalidRequest
                        || err1.kind == GenerationErrorKind::SupportedParameters
                    {
                        Err(err1)
                    } else {
                        // Retry attempt 2 immediately with byte-identical request snapshot
                        if cancel.is_cancelled() {
                            return Err(NodeError::cancelled());
                        }
                        generator.generate(request_snapshot.clone()).await
                    }
                }
            };

            match final_result {
                Ok(output) => {
                    ctx.update_from_model_output(&output);
                    ctx.structured_citations = resolve_citations(&ctx.citations, &ctx.evidence_blocks)
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
                    if cancel.is_cancelled() {
                        return Err(NodeError::cancelled());
                    }
                    let node_kind = match err.kind {
                        GenerationErrorKind::Timeout => NodeErrorKind::Timeout,
                        _ => NodeErrorKind::LlmGenerationFailed,
                    };
                    Err(NodeError::new(node_kind, err.message())
                        .with_context(Some(ctx.session_id.clone()), Some(ctx.trace_id.clone())))
                }
            }
        })
    }
}
