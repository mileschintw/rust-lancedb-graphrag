use tokio_util::sync::CancellationToken;

use super::super::{
    node::{BoxFuture, Node, NodeError, NodeKind},
    WorkflowContext,
};
use crate::pb::lancet::v1::NodeErrorKind;
use crate::prompt::{
    pack_evidence_and_graph_prompt, PromptAssemblyError, DEFAULT_ANSWER_TOKEN_BUDGET,
    DEFAULT_MAX_PROMPT_TOKENS,
};

pub struct AssemblePromptNode {
    max_prompt_tokens: usize,
    answer_token_budget: usize,
    graph_weight: f64,
}

impl AssemblePromptNode {
    pub fn new() -> Self {
        Self {
            max_prompt_tokens: DEFAULT_MAX_PROMPT_TOKENS,
            answer_token_budget: DEFAULT_ANSWER_TOKEN_BUDGET,
            graph_weight: 1.0,
        }
    }

    pub fn with_budgets(max_prompt_tokens: usize, answer_token_budget: usize) -> Self {
        Self {
            max_prompt_tokens,
            answer_token_budget,
            graph_weight: 1.0,
        }
    }

    pub fn with_settings(
        max_prompt_tokens: usize,
        answer_token_budget: usize,
        graph_weight: f64,
    ) -> Self {
        Self {
            max_prompt_tokens,
            answer_token_budget,
            graph_weight,
        }
    }
}

impl Default for AssemblePromptNode {
    fn default() -> Self {
        Self::new()
    }
}

impl Node for AssemblePromptNode {
    fn kind(&self) -> NodeKind {
        NodeKind::AssemblePrompt
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

            if ctx.evidence_blocks.is_empty() {
                if !ctx.allow_model_only {
                    return Err(NodeError::new(
                        NodeErrorKind::PromptAssemblyFailed,
                        "No evidence blocks provided for prompt assembly",
                    ));
                }
                ctx.assembled_prompt = crate::prompt::pack_model_only_prompt(&ctx.original_query);
                crate::telemetry::metrics::record_evidence_set_size(0);
                return Ok(());
            }

            match pack_evidence_and_graph_prompt(
                &ctx.original_query,
                &ctx.evidence_blocks,
                &ctx.graph_facts,
                self.graph_weight,
                self.max_prompt_tokens,
                self.answer_token_budget,
                cancel,
            )
            .await
            {
                Ok(packed) => {
                    ctx.assembled_prompt = packed.prompt;
                    ctx.evidence_blocks = packed.evidence;
                    ctx.graph_facts = packed.graph_facts;
                    crate::telemetry::metrics::record_evidence_set_size(
                        ctx.evidence_blocks.len() as u64,
                    );
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
