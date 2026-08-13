use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use super::super::{
    node::{BoxFuture, Node, NodeError},
    ports::QueryReformulator,
    WorkflowContext,
};

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
    fn name(&self) -> &'static str {
        "ReformulateQuery"
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
                let variants = reformulator.reformulate(&ctx.original_query, cancel).await?;
                ctx.variants = variants;
            } else if ctx.variants.is_empty() {
                ctx.variants.push(ctx.original_query.clone());
            }

            Ok(())
        })
    }
}
