use tokio_util::sync::CancellationToken;
use super::super::{node::{BoxFuture, Node, NodeError}, WorkflowContext};

pub struct ReformulateQueryNode;

impl ReformulateQueryNode {
    pub fn new() -> Self {
        Self
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

            if ctx.variants.is_empty() {
                ctx.variants.push(ctx.original_query.clone());
            }

            Ok(())
        })
    }
}
