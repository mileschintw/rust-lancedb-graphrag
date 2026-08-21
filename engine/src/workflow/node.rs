use std::fmt;
use std::future::Future;
use std::pin::Pin;
use tokio_util::sync::CancellationToken;

use super::WorkflowContext;
use crate::pb::lancet::v1::NodeErrorKind;

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
    pub retryable: bool,
}

impl NodeError {
    pub fn new(kind: NodeErrorKind, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
            session_id: None,
            correlation_id: None,
            retryable: false,
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

    pub fn with_retryable(mut self, retryable: bool) -> Self {
        self.retryable = retryable;
        self
    }

    pub fn with_context(
        mut self,
        session_id: Option<String>,
        correlation_id: Option<String>,
    ) -> Self {
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

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum NodeKind {
    ReformulateQuery,
    ExtractGraphContext,
    RetrieveHybrid,
    AssemblePrompt,
    GenerateAnswer,
}

impl NodeKind {
    pub const ALL: [NodeKind; 5] = [
        NodeKind::ReformulateQuery,
        NodeKind::ExtractGraphContext,
        NodeKind::RetrieveHybrid,
        NodeKind::AssemblePrompt,
        NodeKind::GenerateAnswer,
    ];

    pub fn name(&self) -> &'static str {
        match self {
            NodeKind::ReformulateQuery => "ReformulateQuery",
            NodeKind::ExtractGraphContext => "ExtractGraphContext",
            NodeKind::RetrieveHybrid => "RetrieveHybrid",
            NodeKind::AssemblePrompt => "AssemblePrompt",
            NodeKind::GenerateAnswer => "GenerateAnswer",
        }
    }

    pub fn checkpoint_label(&self) -> &'static str {
        match self {
            NodeKind::ReformulateQuery => "post_reformulatequery",
            NodeKind::ExtractGraphContext => "post_extractgraphcontext",
            NodeKind::RetrieveHybrid => "post_retrievehybrid",
            NodeKind::AssemblePrompt => "post_assembleprompt",
            NodeKind::GenerateAnswer => "post_generateanswer",
        }
    }
}

impl fmt::Display for NodeKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.name())
    }
}

pub trait Node: Send + Sync {
    fn kind(&self) -> NodeKind;

    fn name(&self) -> &'static str {
        self.kind().name()
    }

    /// Prepare external capabilities before the node's elapsed-time budget
    /// starts. Most nodes have no bootstrap work.
    fn prepare<'a>(&'a self) -> BoxFuture<'a, Result<(), NodeError>> {
        Box::pin(async { Ok(()) })
    }

    fn run<'a>(
        &'a self,
        ctx: &'a mut WorkflowContext,
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<(), NodeError>>;
}
