use super::super::{
    node::{BoxFuture, Node, NodeError, NodeKind},
    ports::QueryReformulator,
    WorkflowContext,
};
use crate::pb::lancet::v1::NodeErrorKind;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

pub struct ReformulateQueryNode {
    reformulator: Option<Arc<dyn QueryReformulator>>,
}

impl ReformulateQueryNode {
    pub fn new() -> Self {
        Self { reformulator: None }
    }

    pub fn with_reformulator(reformulator: Option<Arc<dyn QueryReformulator>>) -> Self {
        Self { reformulator }
    }
}

impl Default for ReformulateQueryNode {
    fn default() -> Self {
        Self::new()
    }
}

impl Node for ReformulateQueryNode {
    fn kind(&self) -> NodeKind {
        NodeKind::ReformulateQuery
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

            if let Some(ref reformulator) = self.reformulator {
                let variants = reformulator
                    .reformulate(&ctx.original_query, cancel)
                    .await?;
                if variants.is_empty() {
                    return Err(NodeError::new(
                        NodeErrorKind::InputValidation,
                        "Query reformulator produced 0 variants; at least 1 variant is required",
                    ));
                }
                if variants.len() > 8 {
                    return Err(NodeError::new(
                        NodeErrorKind::InputValidation,
                        format!(
                            "Query reformulator produced {} variants, exceeding maximum allowed limit of 8",
                            variants.len()
                        ),
                    ));
                }
                ctx.variants = variants;
            } else if ctx.variants.is_empty() {
                ctx.variants.push(ctx.original_query.clone());
            } else if ctx.variants.len() > 8 {
                return Err(NodeError::new(
                    NodeErrorKind::InputValidation,
                    format!(
                        "Query reformulator produced {} variants, exceeding maximum allowed limit of 8",
                        ctx.variants.len()
                    ),
                ));
            }

            Ok(())
        })
    }
}
