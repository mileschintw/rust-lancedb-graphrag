use std::fmt;
use std::future::Future;
use std::pin::Pin;
use tokio_util::sync::CancellationToken;

use crate::pb::lancet::v1::NodeErrorKind;
use super::WorkflowContext;

pub type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

pub trait QueryEmbeddingPort: Send + Sync {
    fn embed_variant_zero<'a>(
        &'a self,
        variant: &'a str,
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<f32>, NodeError>>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeError {
    pub kind: NodeErrorKind,
    pub message: String,
    pub session_id: Option<String>,
    pub correlation_id: Option<String>,
}

impl NodeError {
    pub fn new(kind: NodeErrorKind, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
            session_id: None,
            correlation_id: None,
        }
    }

    pub fn timeout(node_name: &str) -> Self {
        Self::new(
            NodeErrorKind::Timeout,
            format!("Node '{}' timed out", node_name),
        )
    }

    pub fn cancelled() -> Self {
        Self::new(NodeErrorKind::Cancelled, "Workflow execution cancelled")
    }

    pub fn with_context(mut self, session_id: Option<String>, correlation_id: Option<String>) -> Self {
        self.session_id = session_id;
        self.correlation_id = correlation_id;
        self
    }
}

impl fmt::Display for NodeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:?}: {}", self.kind, self.message)
    }
}

impl std::error::Error for NodeError {}

pub trait Node: Send + Sync {
    fn name(&self) -> &'static str;

    fn run<'a>(
        &'a self,
        ctx: &'a mut WorkflowContext,
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<(), NodeError>>;
}
