use std::sync::Arc;
use std::time::{Duration, Instant};
use futures::future::BoxFuture;
use tokio::sync::mpsc;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::pb::lancet::v1::{
    workflow_event::Event, NodeErrorKind, WorkflowEvent,
};
use super::{
    events::{self, EventSequence},
    node::{Node, NodeError},
    WorkflowContext, WorkflowDependencies,
};

pub struct WorkflowEventSink {
    tx: mpsc::Sender<Result<WorkflowEvent, tonic::Status>>,
    sequence: Arc<EventSequence>,
    trace_id: String,
    session_id: String,
}

impl WorkflowEventSink {
    pub fn new(
        tx: mpsc::Sender<Result<WorkflowEvent, tonic::Status>>,
        sequence: Arc<EventSequence>,
        trace_id: String,
        session_id: String,
    ) -> Self {
        Self {
            tx,
            sequence,
            trace_id,
            session_id,
        }
    }

    pub fn send_event(&self, event: Event) {
        let seq = self.sequence.next();
        let wf_event = events::wrap_event(
            event,
            seq,
            self.trace_id.clone(),
            self.session_id.clone(),
        );
        let _ = self.tx.try_send(Ok(wf_event));
    }

    pub fn trace_id(&self) -> &str {
        &self.trace_id
    }

    pub fn session_id(&self) -> &str {
        &self.session_id
    }

    pub fn next_sequence_ordinal(&self) -> u64 {
        self.sequence.next()
    }
}

pub struct WorkflowRunner {
    nodes: Vec<Box<dyn Node>>,
    reformulate_timeout: Duration,
    graph_timeout: Duration,
    retrieve_timeout: Duration,
    prompt_timeout: Duration,
    generation_timeout: Duration,
}

impl WorkflowRunner {
    pub fn new() -> Self {
        Self {
            nodes: Vec::new(),
            reformulate_timeout: Duration::from_millis(5000),
            graph_timeout: Duration::from_millis(15000),
            retrieve_timeout: Duration::from_millis(10000),
            prompt_timeout: Duration::from_millis(2000),
            generation_timeout: Duration::from_millis(65000),
        }
    }

    pub fn with_timeouts(
        mut self,
        reformulate_ms: u64,
        graph_ms: u64,
        retrieve_ms: u64,
        prompt_ms: u64,
        generation_ms: u64,
    ) -> Self {
        self.reformulate_timeout = Duration::from_millis(reformulate_ms);
        self.graph_timeout = Duration::from_millis(graph_ms);
        self.retrieve_timeout = Duration::from_millis(retrieve_ms);
        self.prompt_timeout = Duration::from_millis(prompt_ms);
        self.generation_timeout = Duration::from_millis(generation_ms);
        self
    }

    pub fn add_node<N: Node + 'static>(&mut self, node: N) {
        self.nodes.push(Box::new(node));
    }

    pub fn timeout_for_node(&self, name: &str) -> Duration {
        match name {
            "ReformulateQuery" => self.reformulate_timeout,
            "ExtractGraphContext" => self.graph_timeout,
            "RetrieveHybrid" => self.retrieve_timeout,
            "AssemblePrompt" => self.prompt_timeout,
            "GenerateAnswer" => self.generation_timeout,
            _ => Duration::from_millis(5000),
        }
    }

    pub async fn run_node(
        &self,
        node: &dyn Node,
        ctx: &mut WorkflowContext,
        cancel: &CancellationToken,
        sink: &WorkflowEventSink,
    ) -> Result<(), NodeError> {
        let name = node.name();
        sink.send_event(events::node_started(name, ""));

        let start_time = Instant::now();
        let node_timeout = self.timeout_for_node(name);

        let result = tokio::select! {
            biased;
            _ = cancel.cancelled() => Err(NodeError::cancelled()),
            res = timeout(node_timeout, node.run(ctx, cancel)) => match res {
                Ok(inner) => inner,
                Err(_) => Err(NodeError::timeout(name)),
            },
        };

        let duration_ms = start_time.elapsed().as_millis() as i64;

        match &result {
            Ok(()) => {
                sink.send_event(events::node_completed(name, "", duration_ms));
                if name == "GenerateAnswer" {
                    sink.send_event(events::answer_chunk(ctx.answer.clone(), true));
                }
                let seq = sink.next_sequence_ordinal();
                sink.send_event(events::checkpoint(format!("post_{}", name.to_lowercase()), seq, ctx));
            }
            Err(err) => {
                sink.send_event(events::node_failed(
                    name,
                    err.kind.clone(),
                    &err.message,
                    false,
                ));
            }
        }

        result
    }

    pub async fn run_workflow(
        &self,
        mut ctx: WorkflowContext,
        cancel: CancellationToken,
        sink: WorkflowEventSink,
    ) {
        let start_time = Instant::now();
        let mut overall_err: Option<NodeError> = None;

        for node in &self.nodes {
            let node_name = node.name();

            if (node_name == "AssemblePrompt" || node_name == "GenerateAnswer")
                && (ctx.notices.iter().any(|n| n.code == "NO_EVIDENCE")
                    || (ctx.final_candidates.is_empty() && ctx.evidence_blocks.is_empty()))
            {
                break;
            }

            if let Err(err) = self.run_node(node.as_ref(), &mut ctx, &cancel, &sink).await {
                overall_err = Some(err);
                break;
            }

            if node_name == "ReformulateQuery" && ctx.variants.len() > 8 {
                let err = NodeError::new(
                    NodeErrorKind::InputValidation,
                    format!(
                        "Query reformulator produced {} variants, exceeding maximum allowed limit of 8",
                        ctx.variants.len()
                    ),
                );
                sink.send_event(events::node_failed(
                    "ReformulateQuery",
                    err.kind.clone(),
                    &err.message,
                    false,
                ));
                overall_err = Some(err);
                break;
            }
        }

        let total_duration_ms = start_time.elapsed().as_millis() as i64;
        Self::emit_terminal_once(&ctx, &sink, total_duration_ms, overall_err);
    }

    pub async fn run_tracer<F>(
        &self,
        mut ctx: WorkflowContext,
        cancel: CancellationToken,
        sink: WorkflowEventSink,
        deps: &WorkflowDependencies,
        remainder_bridge: F,
    ) where
        F: for<'a> FnOnce(
            &'a mut WorkflowContext,
            &'a WorkflowDependencies,
            &'a WorkflowEventSink,
            &'a CancellationToken,
        ) -> BoxFuture<'a, Result<(), NodeError>>,
    {
        let has_prompt_or_gen = self
            .nodes
            .iter()
            .any(|n| n.name() == "AssemblePrompt" || n.name() == "GenerateAnswer");
        if has_prompt_or_gen {
            self.run_workflow(ctx, cancel, sink).await;
        } else {
            let start_time = Instant::now();
            let mut overall_err: Option<NodeError> = None;

            for node in &self.nodes {
                let node_name = node.name();
                if let Err(err) = self.run_node(node.as_ref(), &mut ctx, &cancel, &sink).await {
                    overall_err = Some(err);
                    break;
                }

                if node_name == "ReformulateQuery" && ctx.variants.len() > 8 {
                    let err = NodeError::new(
                        NodeErrorKind::InputValidation,
                        format!(
                            "Query reformulator produced {} variants, exceeding maximum allowed limit of 8",
                            ctx.variants.len()
                        ),
                    );
                    sink.send_event(events::node_failed(
                        "ReformulateQuery",
                        err.kind.clone(),
                        &err.message,
                        false,
                    ));
                    overall_err = Some(err);
                    break;
                }
            }

            if overall_err.is_none() {
                let is_zero_evidence = ctx.notices.iter().any(|n| n.code == "NO_EVIDENCE");

                if !is_zero_evidence {
                    if let Err(err) = remainder_bridge(&mut ctx, deps, &sink, &cancel).await {
                        overall_err = Some(err);
                    }
                }
            }

            let total_duration_ms = start_time.elapsed().as_millis() as i64;
            Self::emit_terminal_once(&ctx, &sink, total_duration_ms, overall_err);
        }
    }

    pub fn emit_terminal_once(
        ctx: &WorkflowContext,
        sink: &WorkflowEventSink,
        duration_ms: i64,
        error: Option<NodeError>,
    ) {
        match error {
            None => {
                let response = ctx.to_query_rag_response();
                sink.send_event(events::final_answer(response.clone()));
                let seq = sink.next_sequence_ordinal();
                sink.send_event(events::checkpoint("terminal_success", seq, ctx));
                sink.send_event(events::workflow_completed(
                    true,
                    duration_ms,
                    NodeErrorKind::Unspecified,
                    "",
                    Some(response),
                ));
            }
            Some(err) => {
                sink.send_event(events::workflow_completed(
                    false,
                    duration_ms,
                    err.kind,
                    err.message,
                    None,
                ));
            }
        }
    }
}

impl Default for WorkflowRunner {
    fn default() -> Self {
        Self::new()
    }
}
