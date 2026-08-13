use tokio_util::sync::CancellationToken;

use crate::pb::lancet::v1::NodeErrorKind;
use crate::prompt::{
    pack_evidence_and_graph_prompt, EvidenceBlock, PromptAssemblyError,
    DEFAULT_ANSWER_TOKEN_BUDGET, DEFAULT_MAX_PROMPT_TOKENS,
};
use super::super::{
    node::{BoxFuture, Node, NodeError},
    WorkflowContext,
};

pub struct AssemblePromptNode {
    max_prompt_tokens: usize,
    answer_token_budget: usize,
}

impl AssemblePromptNode {
    pub fn new() -> Self {
        Self {
            max_prompt_tokens: DEFAULT_MAX_PROMPT_TOKENS,
            answer_token_budget: DEFAULT_ANSWER_TOKEN_BUDGET,
        }
    }

    pub fn with_budgets(max_prompt_tokens: usize, answer_token_budget: usize) -> Self {
        Self {
            max_prompt_tokens,
            answer_token_budget,
        }
    }
}

impl Default for AssemblePromptNode {
    fn default() -> Self {
        Self::new()
    }
}

impl Node for AssemblePromptNode {
    fn name(&self) -> &'static str {
        "AssemblePrompt"
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

            let evidence = if ctx.evidence_blocks.is_empty() {
                if ctx.final_candidates.is_empty() {
                    Vec::new()
                } else {
                    ctx.final_candidates
                        .iter()
                        .enumerate()
                        .map(|(idx, chunk_id)| EvidenceBlock {
                            id: format!("[{}]", idx + 1),
                            chunk_id: chunk_id.clone(),
                            document_id: format!("doc_{}", chunk_id),
                            chunk_index: idx as i32,
                            title: Some("Document".into()),
                            section_path: Some("Root".into()),
                            content_type: Some("text/plain".into()),
                            provenance: format!("document_id=doc_{}, chunk_index={}", chunk_id, idx),
                            text: format!("Content of chunk {}", chunk_id),
                            score: 1.0,
                            rank: idx + 1,
                            suspicious: false,
                        })
                        .collect()
                }
            } else {
                ctx.evidence_blocks.clone()
            };

            if evidence.is_empty() {
                return Err(NodeError::new(
                    NodeErrorKind::PromptAssemblyFailed,
                    "No evidence blocks provided for prompt assembly",
                ));
            }

            match pack_evidence_and_graph_prompt(
                &ctx.original_query,
                &evidence,
                &[],
                1.0,
                self.max_prompt_tokens,
                self.answer_token_budget,
                cancel,
            )
            .await
            {
                Ok(packed) => {
                    ctx.assembled_prompt = packed.prompt;
                    ctx.evidence_blocks = packed.evidence;
                    Ok(())
                }
                Err(PromptAssemblyError::Cancelled) => Err(NodeError::cancelled()),
                Err(err) => Err(NodeError::new(
                    NodeErrorKind::PromptAssemblyFailed,
                    err.to_string(),
                )),
            }
        })
    }
}
