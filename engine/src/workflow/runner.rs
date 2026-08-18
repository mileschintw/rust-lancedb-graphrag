use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
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
    node::{Node, NodeError, NodeKind},
    WorkflowContext, WorkflowDependencies,
};

const MAX_PENDING_CHECKPOINTS: usize = 32;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClientEventDelivery {
    Sent,
    Closed,
    Cancelled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CheckpointDelivery {
    Sent,
    Pending,
    Closed,
    OwnershipFailure { sequence_ordinal: u64 },
}

type EventEnvelope = Result<WorkflowEvent, tonic::Status>;

#[derive(Clone)]
pub struct WorkflowEventSink {
    tx: mpsc::Sender<EventEnvelope>,
    sequence: Arc<EventSequence>,
    trace_id: String,
    session_id: String,
    pending_checkpoints: Arc<Mutex<VecDeque<WorkflowEvent>>>,
    terminal_emitted: Arc<AtomicBool>,
}

impl WorkflowEventSink {
    pub fn new(
        tx: mpsc::Sender<EventEnvelope>,
        sequence: Arc<EventSequence>,
        trace_id: String,
        session_id: String,
    ) -> Self {
        Self {
            tx,
            sequence,
            trace_id,
            session_id,
            pending_checkpoints: Arc::new(Mutex::new(VecDeque::new())),
            terminal_emitted: Arc::new(AtomicBool::new(false)),
        }
    }

    fn lock_pending_checkpoints(&self) -> std::sync::MutexGuard<'_, VecDeque<WorkflowEvent>> {
        self.pending_checkpoints
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn wrap_next_event(&self, event: Event) -> WorkflowEvent {
        let seq = self.sequence.next();
        events::wrap_event(
            event,
            seq,
            self.trace_id.clone(),
            self.session_id.clone(),
        )
    }

    async fn send_envelope(
        &self,
        event: WorkflowEvent,
        cancel: &CancellationToken,
    ) -> ClientEventDelivery {
        if self.tx.is_closed() {
            return ClientEventDelivery::Closed;
        }

        if self.tx.capacity() > 0 {
            return match self.tx.reserve().await {
                Ok(permit) => {
                    permit.send(Ok(event));
                    ClientEventDelivery::Sent
                }
                Err(_) => ClientEventDelivery::Closed,
            };
        }

        tokio::select! {
            biased;
            _ = cancel.cancelled() => ClientEventDelivery::Cancelled,
            result = self.tx.reserve() => match result {
                Ok(permit) => {
                    permit.send(Ok(event));
                    ClientEventDelivery::Sent
                }
                Err(_) => ClientEventDelivery::Closed,
            },
        }
    }

    async fn flush_pending_checkpoints(
        &self,
        cancel: &CancellationToken,
    ) -> ClientEventDelivery {
        loop {
            let Some(event) = self.lock_pending_checkpoints().pop_front() else {
                return ClientEventDelivery::Sent;
            };

            if self.tx.is_closed() {
                return ClientEventDelivery::Closed;
            }

            if self.tx.capacity() > 0 {
                match self.tx.reserve().await {
                    Ok(permit) => permit.send(Ok(event)),
                    Err(_) => return ClientEventDelivery::Closed,
                }
                continue;
            }

            tokio::select! {
                biased;
                _ = cancel.cancelled() => {
                    self.lock_pending_checkpoints().push_front(event);
                    return ClientEventDelivery::Cancelled;
                }
                result = self.tx.reserve() => match result {
                    Ok(permit) => permit.send(Ok(event)),
                    Err(_) => return ClientEventDelivery::Closed,
                },
            }
        }
    }

    /// Deliver a client-visible event with cancellation-aware backpressure.
    pub async fn send_event(
        &self,
        event: Event,
        cancel: &CancellationToken,
    ) -> ClientEventDelivery {
        let pending_delivery = self.flush_pending_checkpoints(cancel).await;
        if pending_delivery != ClientEventDelivery::Sent {
            return pending_delivery;
        }

        self.send_envelope(self.wrap_next_event(event), cancel).await
    }

    /// Convert a failed client delivery into cooperative workflow cancellation.
    pub async fn send_event_or_cancel(
        &self,
        event: Event,
        cancel: &CancellationToken,
    ) -> Result<(), NodeError> {
        match self.send_event(event, cancel).await {
            ClientEventDelivery::Sent => Ok(()),
            ClientEventDelivery::Closed => {
                cancel.cancel();
                Err(NodeError::cancelled())
            }
            ClientEventDelivery::Cancelled => Err(NodeError::cancelled()),
        }
    }

    /// Nonblocking checkpoint handoff. A full client channel retains the owned
    /// envelope in a bounded queue; it never silently drops the checkpoint.
    pub fn send_checkpoint(
        &self,
        checkpoint_type: impl Into<String>,
        context: &WorkflowContext,
    ) -> CheckpointDelivery {
        let sequence_ordinal = self.sequence.next();
        let event = self.wrap_event(events::checkpoint(
            checkpoint_type,
            sequence_ordinal,
            context,
        ));

        let mut pending = self.lock_pending_checkpoints();
        if !pending.is_empty() {
            if pending.len() >= MAX_PENDING_CHECKPOINTS {
                return CheckpointDelivery::OwnershipFailure { sequence_ordinal };
            }
            pending.push_back(event);
            return CheckpointDelivery::Pending;
        }
        drop(pending);

        match self.tx.try_send(Ok(event)) {
            Ok(()) => CheckpointDelivery::Sent,
            Err(mpsc::error::TrySendError::Full(Ok(event))) => {
                let mut pending = self.lock_pending_checkpoints();
                if pending.len() >= MAX_PENDING_CHECKPOINTS {
                    return CheckpointDelivery::OwnershipFailure { sequence_ordinal };
                }
                pending.push_back(event);
                CheckpointDelivery::Pending
            }
            Err(mpsc::error::TrySendError::Closed(Ok(_))) => CheckpointDelivery::Closed,
            Err(mpsc::error::TrySendError::Full(Err(_)))
            | Err(mpsc::error::TrySendError::Closed(Err(_))) => {
                CheckpointDelivery::OwnershipFailure { sequence_ordinal }
            }
        }
    }

    pub fn send_checkpoint_or_error(
        &self,
        checkpoint_type: impl Into<String>,
        context: &WorkflowContext,
        cancel: &CancellationToken,
    ) -> Result<(), NodeError> {
        match self.send_checkpoint(checkpoint_type, context) {
            CheckpointDelivery::Sent | CheckpointDelivery::Pending => Ok(()),
            CheckpointDelivery::Closed => {
                cancel.cancel();
                Err(NodeError::cancelled())
            }
            CheckpointDelivery::OwnershipFailure { sequence_ordinal } => Err(NodeError::new(
                NodeErrorKind::Internal,
                format!(
                    "Checkpoint envelope ownership capacity exhausted at sequence {sequence_ordinal}"
                ),
            )),
        }
    }

    pub fn pending_checkpoint_count(&self) -> usize {
        self.lock_pending_checkpoints().len()
    }

    fn wrap_event(&self, event: Event) -> WorkflowEvent {
        let sequence_ordinal = match &event {
            Event::Checkpoint(checkpoint) => checkpoint.sequence_ordinal,
            _ => unreachable!("checkpoint helper must pass a checkpoint event"),
        };
        events::wrap_event(
            event,
            sequence_ordinal,
            self.trace_id.clone(),
            self.session_id.clone(),
        )
    }

    pub fn trace_id(&self) -> &str {
        &self.trace_id
    }

    pub fn session_id(&self) -> &str {
        &self.session_id
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

    pub fn timeout_for_kind(&self, kind: NodeKind) -> Duration {
        match kind {
            NodeKind::ReformulateQuery => self.reformulate_timeout,
            NodeKind::ExtractGraphContext => self.graph_timeout,
            NodeKind::RetrieveHybrid => self.retrieve_timeout,
            NodeKind::AssemblePrompt => self.prompt_timeout,
            NodeKind::GenerateAnswer => self.generation_timeout,
        }
    }

    pub fn timeout_for_node(&self, name: &str) -> Duration {
        match name {
            "ReformulateQuery" => self.timeout_for_kind(NodeKind::ReformulateQuery),
            "ExtractGraphContext" => self.timeout_for_kind(NodeKind::ExtractGraphContext),
            "RetrieveHybrid" => self.timeout_for_kind(NodeKind::RetrieveHybrid),
            "AssemblePrompt" => self.timeout_for_kind(NodeKind::AssemblePrompt),
            "GenerateAnswer" => self.timeout_for_kind(NodeKind::GenerateAnswer),
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
        let kind = node.kind();
        let name = kind.name();
        sink.send_event_or_cancel(events::node_started(name, ""), cancel)
            .await?;

        let start_time = Instant::now();
        let node_timeout = self.timeout_for_kind(kind);

        let result = tokio::select! {
            biased;
            _ = cancel.cancelled() => Err(NodeError::cancelled()),
            res = timeout(node_timeout, node.run(ctx, cancel)) => match res {
                Ok(inner) => inner,
                Err(_) => {
                    cancel.cancel();
                    Err(NodeError::timeout(name))
                }
            },
        };

        let duration_ms = start_time.elapsed().as_millis() as i64;

        match &result {
            Ok(()) => {
                sink.send_event_or_cancel(events::node_completed(name, "", duration_ms), cancel)
                    .await?;
                match kind {
                    NodeKind::GenerateAnswer => {
                        sink.send_event_or_cancel(events::answer_chunk(ctx.answer.clone(), true), cancel)
                            .await?;
                    }
                    NodeKind::ReformulateQuery
                    | NodeKind::ExtractGraphContext
                    | NodeKind::RetrieveHybrid
                    | NodeKind::AssemblePrompt => {}
                }
                sink.send_checkpoint_or_error(kind.checkpoint_label(), ctx, cancel)?;
            }
            Err(err) => {
                sink.send_event_or_cancel(
                    events::node_failed(name, err.kind.clone(), &err.message, err.retryable),
                    cancel,
                )
                .await?;
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
            let kind = node.kind();

            match kind {
                NodeKind::AssemblePrompt | NodeKind::GenerateAnswer => {
                    if ctx.notices.iter().any(|n| n.code == "NO_EVIDENCE")
                        || (ctx.final_candidates.is_empty() && ctx.evidence_blocks.is_empty())
                    {
                        break;
                    }
                }
                NodeKind::ReformulateQuery
                | NodeKind::ExtractGraphContext
                | NodeKind::RetrieveHybrid => {}
            }

            if let Err(err) = self.run_node(node.as_ref(), &mut ctx, &cancel, &sink).await {
                overall_err = Some(err);
                break;
            }
        }

        let total_duration_ms = start_time.elapsed().as_millis() as i64;
        Self::emit_terminal_once(&ctx, &sink, &cancel, total_duration_ms, overall_err).await;
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
            .any(|n| matches!(n.kind(), NodeKind::AssemblePrompt | NodeKind::GenerateAnswer));
        if has_prompt_or_gen {
            self.run_workflow(ctx, cancel, sink).await;
        } else {
            let start_time = Instant::now();
            let mut overall_err: Option<NodeError> = None;

            for node in &self.nodes {
                if let Err(err) = self.run_node(node.as_ref(), &mut ctx, &cancel, &sink).await {
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
            Self::emit_terminal_once(&ctx, &sink, &cancel, total_duration_ms, overall_err).await;
        }
    }

    pub async fn emit_terminal_once(
        ctx: &WorkflowContext,
        sink: &WorkflowEventSink,
        cancel: &CancellationToken,
        duration_ms: i64,
        error: Option<NodeError>,
    ) {
        if sink
            .terminal_emitted
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return;
        }

        match error {
            None => {
                let response = ctx.to_query_rag_response();
                if sink
                    .send_event_or_cancel(events::final_answer(response.clone()), cancel)
                    .await
                    .is_err()
                {
                    return;
                }
                if sink
                    .send_checkpoint_or_error("terminal_success", ctx, cancel)
                    .is_err()
                {
                    return;
                }
                match sink
                    .send_event_or_cancel(
                        events::workflow_completed(
                            true,
                            duration_ms,
                            NodeErrorKind::Unspecified,
                            "",
                            Some(response),
                            ctx.notices.clone(),
                        ),
                        cancel,
                    )
                    .await
                {
                    Ok(()) | Err(_) => {}
                }
            }
            Some(err) => {
                match sink
                    .send_event_or_cancel(
                        events::workflow_completed(
                            false,
                            duration_ms,
                            err.kind,
                            err.message,
                            None,
                            ctx.notices.clone(),
                        ),
                        cancel,
                    )
                    .await
                {
                    Ok(()) | Err(_) => {}
                }
            }
        }
    }
}

impl Default for WorkflowRunner {
    fn default() -> Self {
        Self::new()
    }
}
