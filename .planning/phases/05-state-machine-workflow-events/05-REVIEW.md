---
phase: 05-state-machine-workflow-events
reviewed: 2026-08-13T00:00:00Z
depth: standard
files_reviewed: 31
files_reviewed_list:
  - config/config.example.toml
  - config/config.toml
  - config/config.verify.toml
  - engine/src/generation/openrouter.rs
  - engine/src/generation/tests.rs
  - engine/src/lib.rs
  - engine/src/main.rs
  - engine/src/pb/mod.rs
  - engine/src/prompt.rs
  - engine/src/retrieval/fusion.rs
  - engine/src/retrieval/mod.rs
  - engine/src/tests.rs
  - engine/src/tests/workflow_phase5.rs
  - engine/src/workflow/events.rs
  - engine/src/workflow/mod.rs
  - engine/src/workflow/node.rs
  - engine/src/workflow/nodes/assemble_prompt.rs
  - engine/src/workflow/nodes/generate.rs
  - engine/src/workflow/nodes/graph_context.rs
  - engine/src/workflow/nodes/mod.rs
  - engine/src/workflow/nodes/reformulate.rs
  - engine/src/workflow/nodes/retrieve.rs
  - engine/src/workflow/ports.rs
  - engine/src/workflow/runner.rs
  - gateway/checkpoint_sink.go
  - gateway/db/models.go
  - gateway/db/query.sql
  - gateway/db/schema.sql
  - gateway/main.go
  - gateway/main_test.go
  - proto/lancet/v1/lancet.proto
findings:
  critical: 8
  warning: 14
  info: 5
  total: 27
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-08-13
**Depth:** standard
**Files Reviewed:** 31
**Status:** issues_found

## Summary

Phase 05 built a Rust workflow state machine (`engine/src/workflow/`) with per-node
timeouts, retries, event streaming and checkpoint persistence, plus a Go SSE bridge and a
PostgreSQL checkpoint sink.

The individual pieces are mostly well-shaped in isolation. The problem is at the seams:
**almost none of the new state machine is actually wired into the production request
path**, and the parts that are wired have no cancellation, no timeout, and silently drop
the events that constitute the phase's core contract.

Three structural facts drive most of the Critical findings:

1. `config/*.toml` ships a fully documented `[engine.workflow]` section with seven timeout
   knobs. `EngineSettings` has no `workflow` field, so the whole section is silently
   discarded by serde and `WorkflowRunner::with_timeouts` is never called outside tests.
2. `query_rag` registers exactly one node (`ReformulateQueryNode`, with no reformulator, so
   it is a no-op copy). `ExtractGraphContext`, `RetrieveHybrid`, `AssemblePrompt` and
   `GenerateAnswer` are never registered in production — all real work runs through
   `execute_inline_query_rag_remainder`, which is wrapped in **no** timeout and **no**
   cancellation select.
3. The `CancellationToken` created in `query_rag` is never cancelled by anything, and the
   spawned task handle is dropped. Client disconnect does not stop the workflow.

`engine/src/tests/workflow_phase5.rs` exercises `run_workflow` with all five nodes
registered — a configuration that never occurs in production — so the suite passes green
while shipping a materially different code path. Treat green tests here as evidence about
the library, not about the service.

Also flagged: fabricated evidence text synthesized into the grounding path
(`assemble_prompt.rs`), a nil-pointer dereference reachable from engine-controlled wire data
in the Go SSE writer, silent loss of stream errors and checkpoints at the gateway, and
`retryable` being hardcoded `false` and then dropped entirely at the wire boundary.

---

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: `[engine.workflow]` timeout configuration is entirely unwired and silently ignored

**File:** `engine/src/main.rs:171-179`, `engine/src/main.rs:1716`, `config/config.toml:10-17`, `config/config.verify.toml:7-14`, `config/config.example.toml:15-29`

**Issue:** `config.toml`, `config.example.toml` and `config.verify.toml` all define an
`[engine.workflow]` table with `reformulate_timeout_ms`, `query_embedding_timeout_ms`,
`retrieve_timeout_ms`, `graph_operation_timeout_ms`, `graph_node_timeout_ms`,
`prompt_timeout_ms` and `generation_node_timeout_ms`. `EngineSettings` (main.rs:171-179)
declares only `grpc_addr`, `lancedb_path`, `retrieval` and `graph`. There is no
`deny_unknown_fields`, so serde discards the entire section without error.

`query_rag` then builds the runner with `WorkflowRunner::new()` (main.rs:1716), which uses
hardcoded defaults (runner.rs:76-80). `with_timeouts` is referenced only from test files
(`engine/src/tests/workflow_phase5.rs:331,397`, `engine/src/tests.rs:7580,7167`).

Consequences:
- Every deployment silently runs the hardcoded 5000/15000/10000/2000/65000 ms values.
- `config.verify.toml` sets 50/100/100/40/150/20/7000 ms specifically so verification runs
  can observe timeout behaviour. Those values have **zero effect**; any verification result
  that claimed to prove timeout semantics proved nothing.
- Operators have no way to tune node deadlines and get no error telling them so.

**Fix:** Add the settings struct and thread it through. Also make unknown keys loud so this
class of drift fails at startup instead of silently.

```rust
// engine/src/main.rs
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkflowConfigSettings {
    #[serde(default = "default_reformulate_timeout_ms")] pub reformulate_timeout_ms: u64,
    #[serde(default = "default_query_embedding_timeout_ms")] pub query_embedding_timeout_ms: u64,
    #[serde(default = "default_retrieve_timeout_ms")] pub retrieve_timeout_ms: u64,
    #[serde(default = "default_graph_operation_timeout_ms")] pub graph_operation_timeout_ms: u64,
    #[serde(default = "default_graph_node_timeout_ms")] pub graph_node_timeout_ms: u64,
    #[serde(default = "default_prompt_timeout_ms")] pub prompt_timeout_ms: u64,
    #[serde(default = "default_generation_node_timeout_ms")] pub generation_node_timeout_ms: u64,
}

pub struct EngineSettings {
    // ...
    #[serde(default)]
    pub workflow: WorkflowConfigSettings,
}

// and at the construction site (main.rs:1716):
let wf = &self.effective_settings.workflow;
let mut runner = workflow::WorkflowRunner::new().with_timeouts(
    wf.reformulate_timeout_ms,
    wf.graph_node_timeout_ms,
    wf.retrieve_timeout_ms,
    wf.prompt_timeout_ms,
    wf.generation_node_timeout_ms,
);
```

Add `validate()` rules mirroring the documented `range=>0` comments, and reject zero.

---

### CR-02: Production `query_rag` registers only one node — the state machine is bypassed, and the real work runs with no timeout

**File:** `engine/src/main.rs:1716-1753`, `engine/src/workflow/runner.rs:259-267`

**Issue:** `query_rag` does:

```rust
let mut runner = workflow::WorkflowRunner::new();
runner.add_node(workflow::nodes::ReformulateQueryNode::new());   // no reformulator -> no-op
```

`ExtractGraphContextNode`, `RetrieveHybridNode`, `AssemblePromptNode` and
`GenerateAnswerNode` are never added. `run_tracer` therefore takes the `else` branch
(runner.rs:229) and delegates all real work to `remainder_bridge`, which is awaited
**bare** at runner.rs:263:

```rust
if let Err(err) = remainder_bridge(&mut ctx, deps, &sink, &cancel).await {
```

There is no `timeout(...)` and no `tokio::select!` on `cancel.cancelled()` around it.
Inside `execute_inline_query_rag_remainder` (main.rs:1234-1537) `cancel` is checked exactly
once, at line 1240, and is never consulted again. Neither `embedder.get_embeddings`
(main.rs:1244), `attempt_graph_augmentation` (main.rs:1271), `DenseRetriever::query`
(main.rs:1294), the BM25 `RwLock` acquisition (main.rs:1311), nor `reranker.rerank`
(main.rs:1335) carries a deadline.

Consequences:
- A hung embedding provider, a hung LanceDB scan, or a BM25 write-lock holder stalls the
  workflow **forever**. No terminal event is emitted, so the gRPC stream never closes and
  the gateway holds an open SSE connection and goroutine indefinitely. Unbounded resource
  growth in the streaming path.
- All the phase's timeout, retry and per-node event machinery (`node_started` /
  `node_completed` for retrieval, prompt assembly, generation) is inert in production.
  Clients see events for `ReformulateQuery` and then a terminal event, nothing in between.
- `NodeErrorKind::Cancelled` is mapped at main.rs:1425 but the generator never produces it
  and the bridge cannot be cancelled, so that arm is unreachable.

**Fix:** Either register the real nodes (preferred — that is what the phase built), or wrap
the bridge in the same select/timeout envelope `run_node` uses:

```rust
// engine/src/workflow/runner.rs, run_tracer else-branch
let bridge_result = tokio::select! {
    biased;
    _ = cancel.cancelled() => Err(NodeError::cancelled()),
    res = timeout(self.remainder_timeout, remainder_bridge(&mut ctx, deps, &sink, &cancel)) => match res {
        Ok(inner) => inner,
        Err(_) => Err(NodeError::timeout("InlineRemainder")),
    },
};
if let Err(err) = bridge_result { overall_err = Some(err); }
```

If registering the nodes, fix CR-03 first — otherwise fabrication goes live.

---

### CR-03: `AssemblePromptNode` fabricates evidence text and feeds it into the grounding path

**File:** `engine/src/workflow/nodes/assemble_prompt.rs:55-77`

**Issue:** When `ctx.evidence_blocks` is empty but `ctx.final_candidates` is not, the node
synthesizes evidence blocks out of thin air:

```rust
text: format!("Content of chunk {}", chunk_id),
document_id: format!("doc_{}", chunk_id),
title: Some("Document".into()),
provenance: format!("document_id=doc_{}, chunk_index={}", chunk_id, idx),
score: 1.0,
```

These blocks are passed to `pack_evidence_and_graph_prompt` and become the literal
`messages[1].content` sent to the LLM. `GenerateAnswerNode` then resolves the model's
citations against them (`generate.rs:90`), producing `StructuredCitation` entries with
invented `document_id`, `title` and `excerpt`, and `score: 1.0`.

This is fabricated provenance in a RAG system whose entire contract is grounded, citable
answers. `answer_basis` will read `RETRIEVAL`.

The same class of defect exists at `engine/src/workflow/mod.rs:210-218`, where the absence
of a generator produces `ctx.answer = format!("Answer for {}", ctx.original_query)` with
`answer_basis = AnswerBasis::Retrieval`, emitted as a genuine `answer_chunk(is_final=true)`
and then `final_answer` + `workflow_completed(success=true)`. A downstream consumer cannot
distinguish this placeholder from a real grounded answer.

**Latency note:** both are currently unreachable in production because of CR-02. The
obvious fix for CR-02 is "register the nodes", at which point CR-03 becomes live. Fix both
together.

**Fix:** Never synthesize evidence. If `evidence_blocks` is empty, fail or emit
`NO_EVIDENCE`:

```rust
let evidence = ctx.evidence_blocks.clone();
if evidence.is_empty() {
    return Err(NodeError::new(
        NodeErrorKind::PromptAssemblyFailed,
        "No retrieved evidence blocks available for prompt assembly",
    ));
}
```

Delete the placeholder-answer branch in `mod.rs:210-218`; a missing generator is a
configuration error and must return `NodeErrorKind::LlmGenerationFailed`, as
`GenerateAnswerNode` already correctly does (`generate.rs:44-51`).

---

### CR-04: Client disconnect does not cancel the workflow — orphaned tasks keep making paid LLM calls

**File:** `engine/src/main.rs:1706`, `engine/src/main.rs:1730-1753`, `engine/src/workflow/runner.rs:47`

**Issue:**

```rust
let cancel = tokio_util::sync::CancellationToken::new();   // main.rs:1706
// ...
tokio::spawn(async move { runner.run_tracer(ctx, cancel.clone(), sink, ...).await });  // handle dropped
Ok(Response::new(stream))
```

Nothing ever calls `cancel.cancel()`. There is no `DropGuard`, no `drop_guard()` moved into
the stream, and no hook on the `ReceiverStream` being dropped. The `JoinHandle` is
discarded, so the task is fully detached — the test helper `AbortOnDrop`
(`tests/workflow_phase5.rs:32-40`) exists in the test suite but has no production analogue.

When a client disconnects, tonic drops the response stream, which drops the
`mpsc::Receiver`. `WorkflowEventSink::send_event` (runner.rs:47) then does:

```rust
let _ = self.tx.try_send(Ok(wf_event));
```

`try_send` returns `Err(Closed)` and the error is discarded. The workflow never learns the
consumer is gone and runs to completion — including the embedding call, the LanceDB
scans, and the OpenRouter chat completion. Every abandoned request continues to burn
provider quota and DB connections.

**Fix:** Tie the token's lifetime to the stream and cancel on send failure. Hold the
`DropGuard` inside a wrapper stream whose `Drop` cancels the token, so a dropped response
stream cancels the workflow:

```rust
struct GuardedStream<S> {
    inner: S,
    _guard: tokio_util::sync::DropGuard,   // cancels `cancel` when this stream is dropped
}

impl<S: Stream + Unpin> Stream for GuardedStream<S> {
    type Item = S::Item;
    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        Pin::new(&mut self.inner).poll_next(cx)
    }
}

let stream: Self::QueryRAGStream = Box::pin(GuardedStream {
    inner: tokio_stream::wrappers::ReceiverStream::new(rx),
    _guard: cancel.clone().drop_guard(),
});
```

Additionally, make the sink cancel on `Err(Closed)` so an in-flight node stops as soon as
the first undeliverable event is detected:

```rust
// engine/src/workflow/runner.rs
pub fn send_event(&self, event: Event) -> Result<(), SendError> {
    // ...
    match self.tx.try_send(Ok(wf_event)) {
        Ok(()) => Ok(()),
        Err(mpsc::error::TrySendError::Closed(_)) => { self.cancel.cancel(); Err(SendError::Closed) }
        Err(mpsc::error::TrySendError::Full(_))   => { self.dropped.fetch_add(1, Relaxed); Err(SendError::Full) }
    }
}
```

Also keep the `JoinHandle` (or use a `JoinSet` / `TaskTracker`) so shutdown can drain
in-flight workflows instead of aborting the process with detached work outstanding.

---

### CR-05: Event delivery failures are silently discarded — the "exactly one terminal event" contract is unenforceable

**File:** `engine/src/workflow/runner.rs:47`, `engine/src/main.rs:1703`

**Issue:** `send_event` discards the `try_send` result unconditionally. Two distinct failure
modes are swallowed:

- `Closed` — the live defect covered by CR-04.
- `Full` — the channel is `mpsc::channel(100)` (main.rs:1703). If the gateway consumer is
  slower than the engine producer, `try_send` drops events on the floor. There is no
  reserve, no backpressure, and no priority for terminal frames, so
  `FinalAnswer` and `WorkflowCompleted` — emitted last, when the buffer is fullest — are the
  frames most likely to be lost. A client then sees a stream that simply stops.

**Scope honesty:** today's production path emits roughly six events per request, so the
`Full` branch is latent, not actively firing. The defect is that the phase's stated
invariant ("exactly one terminal event per workflow") is enforced by nothing: there is no
counter, no reserve, no error path, and a drop is undetectable by either side. As soon as
CR-02 is fixed and the full node set emits `node_started`/`node_completed`/`checkpoint`
per node plus streamed answer chunks, the buffer becomes reachable.

**Fix:** Reserve capacity for terminal frames and make loss observable.

```rust
// Blocking send with a bounded wait for terminal frames:
pub async fn send_terminal(&self, event: Event) {
    let wf_event = /* ... */;
    if let Err(err) = self.tx.send(Ok(wf_event)).await {
        tracing::error!(trace_id = %self.trace_id, "terminal event undeliverable: {err}");
    }
}
```

Use `send_terminal` from `emit_terminal_once` (runner.rs:283-301), keep `try_send` for
best-effort progress frames, and increment a `dropped_events` counter that is reported in
the terminal event so consumers know the stream was lossy.

Note that `send_terminal` is `async`, so `emit_terminal_once` (`pub fn`, runner.rs:274)
must become `async fn`. Both call sites (runner.rs:205 and :270) are already inside `async
fn`, so the change is mechanical.

---

### CR-06: `toQueryRAGResponseDTO` dereferences a nil `*pb.QueryRAGResponse` — panic reachable from engine wire data

**File:** `gateway/main.go:875-950`, call site `gateway/main.go:804`

**Issue:**

```go
case *pb.WorkflowEvent_FinalAnswer:
    eventType = "final_answer"
    payload = toQueryRAGResponseDTO(e.FinalAnswer.GetResponse())   // line 804 — unguarded
```

`GetResponse()` returns `nil` whenever `FinalAnswerEvent.response` is unset (it is an
optional message field in proto3, `proto/lancet/v1/lancet.proto:175-177`).
`toQueryRAGResponseDTO` then does raw field access on the pointer:

```go
if len(resp.Citations) > 0 {          // line 877 — nil deref
for _, sc := range resp.StructuredCitations {  // line 882
if resp.Snapshot != nil {              // line 912
Answer: resp.Answer,                   // line 942
```

All of these panic on a nil receiver. The sibling call site at line 813 **does** guard
(`if e.WorkflowCompleted.GetFinalResponse() != nil`), which makes the omission at 804 an
inconsistency rather than a deliberate invariant.

This is engine-controlled input crossing a trust boundary: a version-skewed engine, a
proto default, or any future code path that emits `FinalAnswerEvent{}` without a response
crashes the HTTP handler goroutine. `net/http` recovers per-connection, but the connection
is torn down mid-SSE with no error frame, and the panic is logged as an unhandled crash.

`gateway/main_test.go` has no coverage for a nil `FinalAnswer` response
(the only `FinalAnswer` fixtures at lines 707 and 2380 always populate it).

**Fix:**

```go
func toQueryRAGResponseDTO(resp *pb.QueryRAGResponse) queryRAGResponseDTO {
	if resp == nil {
		return queryRAGResponseDTO{
			Citations:           []string{},
			StructuredCitations: []structuredCitationDTO{},
			Notices:             []noticeDTO{},
		}
	}
	// ... existing body
}
```

Better still, switch every field access to the generated getters (`resp.GetCitations()`,
`resp.GetAnswer()`, …), which are nil-safe by construction. Add a table test with
`&pb.FinalAnswerEvent{}` (no response).

---

### CR-07: Gateway silently swallows stream errors — clients cannot distinguish success from failure

**File:** `gateway/main.go:725-735`

**Issue:**

```go
for {
    ev, recvErr := stream.Recv()
    if errors.Is(recvErr, io.EOF) { break }
    if recvErr != nil { break }          // lines 730-732
    a.writeWorkflowEventSSE(w, rc, ev)
}
```

Any non-EOF gRPC error — `Unavailable`, `DeadlineExceeded`, `Internal`, `ResourceExhausted`,
engine crash mid-stream — is discarded. The handler returns, the SSE response ends
normally with HTTP 200 already committed, and the client receives a truncated stream with
no `workflow_completed` frame and no error frame. The error is not even logged
(`a.logger` is available on the `app` struct at main.go:292 and unused here).

Combined with CR-05 (terminal frames droppable on the Rust side) and CR-02 (workflows that
can hang forever), a client has no reliable way to detect a failed query. This defeats the
error-taxonomy work done in `NodeErrorKind` (`proto/lancet/v1/lancet.proto:138-149`) — the
taxonomy exists but never reaches the client on the transport-failure path.

**Fix:** Emit a terminal SSE error frame and log.

```go
for {
	ev, recvErr := stream.Recv()
	if errors.Is(recvErr, io.EOF) {
		break
	}
	if recvErr != nil {
		st := status.Convert(recvErr)
		a.logger.Error("rag stream aborted",
			zap.String("code", st.Code().String()), zap.Error(recvErr))
		payload, _ := json.Marshal(map[string]any{
			"code":    st.Code().String(),
			"message": st.Message(),
		})
		fmt.Fprintf(w, "event: stream_error\ndata: %s\n\n", payload)
		_ = rc.Flush()
		break
	}
	a.writeWorkflowEventSSE(w, rc, ev)
}
```

Also consider a client-side watchdog: if EOF arrives without a `workflow_completed` having
been seen, synthesize a `stream_error` frame so the "exactly one terminal event" contract
holds end-to-end.

---

### CR-08: Checkpoints are silently dropped under load and lost on shutdown — and a test blesses the drop

**File:** `gateway/main.go:763-768`, `gateway/checkpoint_sink.go:168-189`, `gateway/checkpoint_sink.go:204-247`

**Issue:** Three compounding defects in the checkpoint persistence path.

*(a) Dispatch result ignored.* `main.go:766` calls `a.dispatcher.Submit(env)` and throws the
`DispatchResult` away. `Submit` (checkpoint_sink.go:168-189) has a primary channel of
capacity **1** and an overflow slice capped at **4**. Beyond that it returns
`DispatchPending` and the envelope is never persisted, never retried, and never logged.
`gateway/main_test.go:2480-2502`
(`TestCheckpointDispatcherSixthEnvelopeReturnsPending`) explicitly asserts that the 6th
in-flight envelope returns `DispatchPending` — so the drop behaviour is pinned by a test
while the sole production caller ignores it. Workflow snapshots are the phase's durability
story; a five-deep buffer with a silent floor is not durability.

*(b) Overflow discarded on `Close`.* `nextEnvelope` (checkpoint_sink.go:204-234) drains
`overflow` first, but when it reaches the blocking `env, ok := <-d.primary` at line 229 and
the channel is closed by `Close()`, it returns `nil` immediately (line 232) **without
re-checking `overflow`**. Any envelope appended to `overflow` while the loop was parked on
that receive is lost at shutdown. `main.go:1016` (`defer dispatcher.Close()`) makes this
the normal shutdown path.

*(c) `SaveCheckpoint` ignores its own `ctx`.* `checkpoint_sink.go:80` accepts
`ctx context.Context` and then never uses it — line 99 builds the write context from
`context.Background()`. The parameter is dead and shutdown cannot cancel an in-flight
write. This also violates the Go convention that a passed `ctx` governs the call.

**Fix:**

```go
// main.go — surface the drop
if res := a.dispatcher.Submit(env); res.Kind == DispatchPending {
	a.logger.Warn("checkpoint dropped: dispatcher saturated",
		zap.String("trace_id", env.TraceID),
		zap.Uint64("sequence_ordinal", env.SequenceOrdinal))
}
```

```go
// checkpoint_sink.go — drain overflow after close
env, ok := <-d.primary
if !ok {
	d.mu.Lock()
	defer d.mu.Unlock()
	if len(d.overflow) > 0 {
		next := d.overflow[0]
		d.overflow = d.overflow[1:]
		return next
	}
	return nil
}
return env
```

```go
// checkpoint_sink.go:99 — honour the caller's context
writeCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
```

Size the primary channel to the real event rate (checkpoints are emitted once per node),
and prefer bounded blocking with a deadline over a 5-deep silent floor.

---

## Warnings

### WR-01: `ReformulateQuery` emits `node_completed` and then `node_failed` for the same node

**File:** `engine/src/workflow/runner.rs:185-201`, duplicated at `:240-256`

**Issue:** The >8-variant validation runs *after* `run_node` has already returned `Ok(())`.
By that point `run_node` has emitted `node_completed` (runner.rs:141) and a
`post_reformulatequery` checkpoint (runner.rs:146). The runner then emits `node_failed` for
the same `"ReformulateQuery"` node.

A consumer tracking per-node lifecycle sees a node transition
`started -> completed -> failed`, and the checkpoint written to
`workflow_checkpoints` records a state that the workflow subsequently rejected. This
directly violates the phase's event-cardinality contract.

**Fix:** Validate inside `ReformulateQueryNode::run` so the failure is the node's own
result, and the runner never emits a completion for it:

```rust
// engine/src/workflow/nodes/reformulate.rs
const MAX_VARIANTS: usize = 8;

let variants = reformulator.reformulate(&ctx.original_query, cancel).await?;
if variants.len() > MAX_VARIANTS {
    return Err(NodeError::new(
        NodeErrorKind::InputValidation,
        format!("Query reformulator produced {} variants, exceeding maximum of {MAX_VARIANTS}", variants.len()),
    ));
}
ctx.variants = variants;
```

This also removes the copy-pasted block duplicated verbatim at runner.rs:185-201 and
:240-256.

---

### WR-02: `retryable` is hardcoded `false` everywhere and then dropped at the wire boundary

**File:** `engine/src/workflow/runner.rs:153`, `:197`, `:251`; `engine/src/workflow/mod.rs:205`; `gateway/main.go:789-795`

**Issue:** `NodeFailedEvent.retryable` exists in the proto
(`proto/lancet/v1/lancet.proto:166`). Every emission site in the engine passes the literal
`false`:

```rust
sink.send_event(events::node_failed(name, err.kind.clone(), &err.message, false));
```

This includes `NodeErrorKind::Timeout` and `RetrievalFailed`, which are precisely the
retryable classes. The gateway then omits the field entirely from the SSE payload
(main.go:791-795 forwards only `node_name`, `error_kind`, `error_message`).

The field is dead in both directions: a client can never distinguish a transient timeout
from a permanent validation failure, and the engine's own retry policy
(`generate.rs:73-75`) knows the answer but never publishes it.

**Fix:** Derive it from the error kind and forward it.

```rust
// engine/src/workflow/node.rs
impl NodeError {
    pub fn is_retryable(&self) -> bool {
        matches!(
            self.kind,
            NodeErrorKind::Timeout | NodeErrorKind::RetrievalFailed | NodeErrorKind::GraphFailed
        )
    }
}
// call sites:
sink.send_event(events::node_failed(name, err.kind.clone(), &err.message, err.is_retryable()));
```

```go
// gateway/main.go:791
payload = map[string]any{
	"node_name":     e.NodeFailed.GetNodeName(),
	"error_kind":    int32(e.NodeFailed.GetCategory()),
	"error_message": e.NodeFailed.GetMessage(),
	"retryable":     e.NodeFailed.GetRetryable(),
}
```

---

### WR-03: Sequence ordinals skip a value per checkpoint, defeating gap-based loss detection

**File:** `engine/src/workflow/runner.rs:145-146`, `:284-285`; `engine/src/workflow/mod.rs:169-170`, `:195-196`, `:216-217`; `gateway/checkpoint_sink.go:42-45`

**Issue:**

```rust
let seq = sink.next_sequence_ordinal();                       // consumes N
sink.send_event(events::checkpoint(format!("post_{}", ...), seq, ctx));  // envelope consumes N+1
```

`next_sequence_ordinal()` calls `self.sequence.next()` (runner.rs:59), which is a
`fetch_add`. `send_event` then calls `self.sequence.next()` again (runner.rs:40). So every
checkpoint burns two ordinals: the inner `CheckpointEvent.sequence_ordinal` gets `N`, the
enclosing `WorkflowEvent.sequence_ordinal` gets `N+1`.

The envelope stream therefore contains deliberate gaps. A consumer cannot use
`ordinal[i+1] == ordinal[i] + 1` to detect a genuinely dropped event — which is exactly the
detection mechanism that CR-05 makes necessary.

The gateway compounds the confusion by carrying both numbers under similar names
(`checkpoint_sink.go:42` `EventSequence: ev.GetSequenceOrdinal()`, `:45`
`SequenceOrdinal: cp.GetSequenceOrdinal()`), and then persists the *inner* one to
`workflow_checkpoints.sequence_ordinal` (`checkpoint_sink.go:105`) while the *envelope* one
is discarded.

**Fix:** Assign the envelope ordinal once and reuse it for the inner field.

```rust
// engine/src/workflow/runner.rs
pub fn send_event_with_ordinal(&self, build: impl FnOnce(u64) -> Event) -> u64 {
    let seq = self.sequence.next();
    let wf_event = events::wrap_event(build(seq), seq, self.trace_id.clone(), self.session_id.clone());
    let _ = self.tx.try_send(Ok(wf_event));
    seq
}
// call site:
sink.send_event_with_ordinal(|seq| events::checkpoint(format!("post_{}", name.to_lowercase()), seq, ctx));
```

Then remove `next_sequence_ordinal()` from the public API so it cannot be misused.

---

### WR-04: OpenRouter preflight breaks retry classification and shares the generation timeout budget

**File:** `engine/src/generation/openrouter.rs:371-376`, `:290-302`; `engine/src/workflow/nodes/generate.rs:72-83`

**Issue:** `execute_one_call` begins with `self.check_supported_parameters().await?`
(openrouter.rs:376), and the whole thing is wrapped in
`timeout(self.config.timeout, self.execute_one_call(request))` (openrouter.rs:629).

Two consequences:

(a) **Transient network failures become permanently non-retryable.** Any transport error in
the preflight is mapped to `GenerationErrorKind::SupportedParameters`
(openrouter.rs:297-302). `GenerateAnswerNode` treats that kind as non-retryable
(generate.rs:73-75):

```rust
if err1.kind == GenerationErrorKind::InvalidRequest
    || err1.kind == GenerationErrorKind::SupportedParameters
{
    Err(err1)     // no retry
}
```

So a momentary DNS blip or connection reset while fetching `/models` — an unambiguously
retryable condition — is classified as a hard capability failure and the request fails
without a second attempt.

(b) **Budget sharing.** The preflight consumes the same `config.timeout` as the generation
call. A slow `/models` response eats the generation deadline. With two attempts
(generate.rs:82) and a 30s per-attempt timeout, the worst case is ~60s against a 65s node
budget — one config change to `generation_timeout_secs` breaks that relationship silently
(and per CR-01 the node budget is not configurable at all).

**Fix:** Distinguish transport failure from capability denial, and hoist the preflight out
of the per-request path:

```rust
// Separate the kinds so retry classification is correct:
.map_err(|err| GenerationError::new(
    if err.is_timeout() || err.is_connect() { GenerationErrorKind::ProviderError }
    else { GenerationErrorKind::SupportedParameters },
    format!("failed to fetch model capabilities: {err}"),
))?
```

Then cache the capability result (it is a property of the configured model, not of the
request) behind a `OnceCell` or verify it once at startup, and give the preflight its own
short deadline separate from the generation budget.

---

### WR-05: `run_inline_prompt_generation_remainder` retries unconditionally on every error class

**File:** `engine/src/workflow/mod.rs:184-188`

**Issue:**

```rust
// D-12: Single retry loop
let mut result = generator.generate(gen_req.clone()).await;
if result.is_err() && !cancel.is_cancelled() {
    result = generator.generate(gen_req).await;
}
```

Unlike `GenerateAnswerNode` (generate.rs:72-83), which correctly excludes `InvalidRequest`
and `SupportedParameters`, this path retries on **every** error kind — including HTTP 401
(bad API key), HTTP 400 (malformed request), and schema-validation failures. Retrying an
authentication failure is a textbook retry storm: it doubles load against a provider that
has already definitively refused, for every request, under an outage.

It also builds the generation request with **empty evidence**
(`GenerationRequest::new(ctx.original_query.clone(), vec![])`, mod.rs:177-180), which
discards `ctx.evidence_blocks` entirely — a separate correctness bug in the same function.

This function is currently referenced only from `engine/src/tests.rs` (lines 7134, 7210,
7323), so it is dead production code carrying live bugs.

**Fix:** Either delete it (it duplicates `AssemblePromptNode` + `GenerateAnswerNode` with
inferior behaviour), or align its retry predicate and evidence handling with
`generate.rs`. Given CR-02, deleting it and registering the real nodes is the right move.

---

### WR-06: Graph degradation labels every failure `GRAPH_TIMEOUT`, including non-timeouts

**File:** `engine/src/workflow/nodes/graph_context.rs:114-127`

**Issue:**

```rust
let notice_msg = if err.kind == NodeErrorKind::Timeout {
    "GRAPH_TIMEOUT".to_string()
} else {
    format!("graph_degrade: {}", err.message)
};
ctx.notices.push(Notice {
    code: "GRAPH_TIMEOUT".into(),   // always GRAPH_TIMEOUT
    ...
});
```

The message discriminates but the `code` does not. A graph backend returning a hard error
(connection refused, malformed response, permission denied) is reported to the client under
code `GRAPH_TIMEOUT`. `Notice.code` is the machine-readable field — clients and dashboards
key off it — so every graph failure is misattributed as a latency problem. Note also that
`NodeErrorKind::GraphFailed` exists in the proto
(`proto/lancet/v1/lancet.proto:145`) and is never used anywhere in the engine.

**Fix:**

```rust
let (code, message) = if err.kind == NodeErrorKind::Timeout {
    ("GRAPH_TIMEOUT", "Graph augmentation exceeded its deadline".to_string())
} else {
    ("GRAPH_DEGRADED", format!("graph_degrade: {}", err.message))
};
ctx.notices.push(Notice {
    code: code.into(),
    message,
    severity: NoticeSeverity::Warning as i32,   // a degraded answer is not INFO
});
```

---

### WR-07: Notices are overwritten, not merged, when the inline remainder runs

**File:** `engine/src/main.rs:1383-1387`, `engine/src/main.rs:1533`

**Issue:** The node path appends notices (`retrieve.rs:159` `ctx.notices.push`,
`graph_context.rs:121` `ctx.notices.push`, `workflow/mod.rs:95,101` `self.notices.push`).
The inline remainder **assigns**:

```rust
ctx.notices = vec![v1::Notice { code: "NO_EVIDENCE".to_string(), ... }];   // main.rs:1383
// ...
ctx.notices = proto_notices;                                              // main.rs:1533
```

Any notice accumulated before the bridge runs — a `GRAPH_TIMEOUT` degradation notice being
the obvious case — is silently erased and never reaches the client. The user is told the
answer is fully grounded when it was produced with the graph subsystem down.

Latent today because the only registered node (`ReformulateQuery`) emits no notices, but it
becomes live the moment CR-02 is addressed.

A distinct but related discard exists on the failure path: `emit_terminal_once`'s
`Some(err)` arm (`engine/src/workflow/runner.rs:294-301`) emits `workflow_completed` with
`final_response: None`, so `ctx.notices` is dropped unconditionally whenever the workflow
fails. A client that gets a `GRAPH_TIMEOUT` degradation followed by a later node failure
learns about neither.

**Fix:**

```rust
ctx.notices.extend(proto_notices);
```

and for the zero-evidence branch, push rather than replace:

```rust
ctx.notices.push(v1::Notice { code: "NO_EVIDENCE".into(), ... });
```

For the terminal failure path, carry the accumulated notices through — either by populating
`final_response` on failure or by adding a `notices` field to `WorkflowCompletedEvent`.

---

### WR-08: `RetrieveHybridNode` writes a `RetrievalSnapshot` with empty provenance fields

**File:** `engine/src/workflow/nodes/retrieve.rs:145-155`

**Issue:**

```rust
ctx.snapshot = Some(RetrievalSnapshot {
    index_generation: "".into(),
    embedding_model: "".into(),
    // ...
    result_hash: "".into(),
});
```

Three of the snapshot's provenance fields are blank. The inline path populates all three
(`main.rs:1500-1526`: real `index_generation`, `embedder.model_id()`, and a hash over the
final candidate chunk IDs). A snapshot exists to make a result auditable and reproducible;
one with no index generation, no embedding model and no result hash cannot serve that
purpose, and a consumer comparing snapshots across the two paths will see spurious
differences.

**Fix:** Pass the required provenance into the node at construction time:

```rust
pub struct RetrieveHybridNode {
    // ...
    index_generation: String,
    embedding_model: String,
}
// and compute the hash the same way main.rs:1520-1526 does, over taken_candidates.
```

---

### WR-09: Multi-variant RRF changes what `bm25_weight` means, and the snapshot cannot reproduce it

**File:** `engine/src/retrieval/fusion.rs:80-120`, `engine/src/workflow/nodes/retrieve.rs:145-155`

**Issue:** `fuse_variant_candidates` sums a BM25 RRF contribution for each of up to 8
variants against a **single** dense contribution (fusion.rs:88-101 adds vector candidates
for variant 0 only; fusion.rs:104-120 loops over every variant's BM25 list). Summing across
runs is standard RRF and is not itself wrong.

The problem is the contract. A chunk that ranks well across all 8 variants accumulates up to
8× the BM25 mass, so the effective lexical/dense balance is `bm25_weight × variant_count`
versus `vector_weight × 1`. The configured `bm25_weight = 1.0`
(`config/config.toml:26`) no longer describes the balance the system actually applies, and
it varies per request with the reformulator's output.

`RetrievalSnapshot` records `bm25_weight`, `vector_weight`, `rrf_k`, `candidate_limit` and
`final_limit` (`proto/lancet/v1/lancet.proto`, populated at retrieve.rs:145-155) but **no
variant count and no variant list**. A result therefore cannot be reproduced from its own
snapshot.

**Fix:** Either normalize BM25 contributions by variant count so `bm25_weight` retains its
meaning, or — better — record the variance in the snapshot so it stays auditable:

```protobuf
message RetrievalSnapshot {
  // ...
  uint32 variant_count = 10;
  repeated string variants = 11;
}
```

Document the chosen semantics next to `bm25_weight` in `config.example.toml`.

---

### WR-10: Public `*_sync` prompt helpers exist only for tests and panic when called from async

**File:** `engine/src/prompt.rs:234-253`, `:255-278`

**Issue:** Both `pack_evidence_prompt_sync` and `pack_evidence_and_graph_prompt_sync` are
documented as "Synchronous bridge for test callers" yet are `pub` on a library module. Each
constructs a fresh Tokio runtime and calls `block_on`:

```rust
let runtime = tokio::runtime::Builder::new_current_thread()
    .enable_all()
    .build()
    .expect("build test runtime");
runtime.block_on(pack_evidence_prompt(...))
```

Calling either from inside an async context panics with "Cannot start a runtime from within
a runtime". This is a public, safe-looking API whose only failure mode is a panic in the
caller's runtime — contrary to `rust-guidelines.md` M-PANIC-IS-STOP ("It is not valid to use
panics to handle self-inflicted error conditions") and M-PANIC-ON-BUG. The `.expect("build
test runtime")` message also leaks test vocabulary into a shipped panic.

Their only callers are `engine/src/generation/tests.rs` and `engine/src/tests.rs`.

**Fix:** Gate them out of the production surface:

```rust
#[cfg(test)]
pub(crate) fn pack_evidence_prompt_sync(...) -> Result<PackedEvidence, PromptAssemblyError> { ... }
```

Or delete them and make the tests `#[tokio::test]` — most already are.

---

### WR-11: `pack_evidence_and_graph_prompt` lost its entire doc block when it became `async`

**File:** `engine/src/prompt.rs:288-300`

**Issue:** The async conversion deleted the function's documentation wholesale — the summary
sentence, the `graph_weight` semantics paragraph explaining the `graph_weight == 0.0`
hard-exclusion rule, and the `# Errors` section enumerating `EmptyEvidence` and
`NoEvidenceFits`. The function is `pub` and now has zero doc comments while gaining a new
failure mode (`PromptAssemblyError::Cancelled`, prompt.rs:140) that is documented nowhere.

`rust-guidelines.md` M-CANONICAL-DOCS requires a summary sentence and an `# Errors` section
for public fallible items; M-FIRST-DOC-SENTENCE requires the summary. This is a regression
in behaviour-critical documentation, not a cosmetic one — the zero-weight exclusion rule is
non-obvious and was the subject of a prior review.

**Fix:** Restore the deleted block and add the new error condition:

```rust
/// Packs evidence chunks and optional graph facts into prompt context after reserving the answer budget.
///
/// [... restore the graph_weight paragraph ...]
///
/// # Errors
/// Returns [`PromptAssemblyError::EmptyEvidence`] if `evidence` is empty [...].
/// Returns [`PromptAssemblyError::NoEvidenceFits`] if [...].
/// Returns [`PromptAssemblyError::Cancelled`] if `cancel` is triggered before or during packing.
pub async fn pack_evidence_and_graph_prompt(...)
```

---

### WR-12: `workflow_checkpoints` grows without bound and persists raw user queries

**File:** `gateway/db/schema.sql:41-52`, `gateway/db/query.sql:107-124`, `engine/src/workflow/events.rs:106-115`

**Issue:** Every node emits a checkpoint, and `InsertWorkflowCheckpoint` is insert-only.
There is no retention policy, no TTL, no partitioning, and no delete query anywhere in
`query.sql`. The table accumulates one row per node per request forever.

The payload is not small and is not anonymous — `events.rs:106-115` serializes:

```rust
"original_query": context.original_query,
"variants": context.variants,
"vector_results": context.vector_results,
"bm25_results": context.bm25_results,
"final_candidates": context.final_candidates,
```

so every user query and its reformulations are stored indefinitely in `context_snapshot`
(`jsonb NOT NULL`). That is a privacy and data-retention exposure with no stated lifecycle.

Two secondary issues in the same area:
- There is no unique constraint on `(trace_id, sequence_ordinal)`; only a non-unique index
  exists (schema.sql:51). Duplicate or replayed checkpoints insert silently.
- `context_snapshot` is `jsonb NOT NULL`. If a `CheckpointEvent` ever arrives with an empty
  `context_snapshot` (the proto3 default for an unset string), the insert fails on invalid
  JSON and the checkpoint is lost with only a log line (`checkpoint_sink.go:112-114`).

**Fix:** Add a retention job and a uniqueness guarantee:

```sql
ALTER TABLE workflow_checkpoints
  ADD CONSTRAINT workflow_checkpoints_trace_seq_key UNIQUE (trace_id, sequence_ordinal);

-- name: DeleteExpiredWorkflowCheckpoints :execresult
DELETE FROM workflow_checkpoints WHERE created_at < $1;
```

Use `ON CONFLICT DO NOTHING` in `InsertWorkflowCheckpoint`, guard empty snapshots in
`SaveCheckpoint`, and decide explicitly whether `original_query` belongs in a durable store
— if it does, document the retention window.

---

### WR-13: `emit_terminal_once` guarantees nothing — its name asserts an invariant it does not enforce

**File:** `engine/src/workflow/runner.rs:274-304`, callers at `:205` and `:270`

**Issue:** `emit_terminal_once` is a plain associated function with no state, no guard, and
no idempotency:

```rust
pub fn emit_terminal_once(
    ctx: &WorkflowContext,
    sink: &WorkflowEventSink,
    duration_ms: i64,
    error: Option<NodeError>,
) {
```

Nothing prevents two calls from emitting two `WorkflowCompleted` events. It is `pub`, so any
caller inside or outside the crate can invoke it repeatedly. The name is a load-bearing
claim about the phase's central invariant, and it is false.

**Reachability:** not reachable today. `run_tracer` is a strict if/else (runner.rs:227 vs
:229), so exactly one terminal emission occurs per run. The defect is that the invariant is
maintained by code shape rather than by any enforcement: a future fallthrough, an added
early-return branch, or an external caller invoking `run_workflow` and then
`emit_terminal_once` would ship two terminal events, and the gateway forwards both as
`workflow_completed` SSE frames (main.go:805-816) with no dedup. Filed as a WARNING rather
than Critical because no current call path produces the double emission.

Relatedly, the success path emits three frames — `final_answer` (runner.rs:283),
`checkpoint("terminal_success")` (runner.rs:285), and `workflow_completed` carrying the
same `QueryRagResponse` again (runner.rs:286-292). This duplication is proto-sanctioned
(`WorkflowCompletedEvent.final_response` is field 5, deliberately present), so it is
redundancy rather than incorrectness — but it does mean the full response payload is cloned
and sent twice on every successful request.

**Fix:** Make the invariant structural.

```rust
pub struct WorkflowEventSink {
    // ...
    terminal_emitted: std::sync::atomic::AtomicBool,
}

impl WorkflowEventSink {
    pub fn emit_terminal(&self, /* ... */) {
        if self.terminal_emitted.swap(true, Ordering::SeqCst) {
            debug_assert!(false, "terminal event emitted twice for trace {}", self.trace_id);
            tracing::error!(trace_id = %self.trace_id, "duplicate terminal event suppressed");
            return;
        }
        // ... emit
    }
}
```

Move the function onto the sink (which owns the channel and the sequence) and make it
`pub(crate)`. Add a test asserting exactly one `WorkflowCompleted` across both `run_workflow`
and `run_tracer` branches.

---

### WR-14: BM25 read guard is held across an unbounded, uncancellable await — a stuck query can wedge ingestion

**File:** `engine/src/main.rs:1311-1321`, `engine/src/main.rs:864`

**Issue:**

```rust
let bm25_guard = self.bm25_index.read().await;
let bm25_candidates = bm25_guard
    .retrieve(query_request, &self.effective_settings.retrieval)
    .await
    .map_err(...)?;
drop(bm25_guard);
```

`bm25_index` is `Arc<tokio::sync::RwLock<Bm25Index>>` (main.rs:864). The read guard is held
across the `retrieve(...).await`, and per CR-02 that await has no deadline and no
cancellation check. `tokio::sync::RwLock` is write-preferring, so a single long-running read
also blocks every subsequent reader once a writer is queued.

The writer here is the ingestion pipeline's index rebuild. So a BM25 retrieve that stalls —
or, per CR-04, an abandoned request whose workflow keeps running after the client
disconnected — holds the read lock indefinitely and blocks index updates for the lifetime of
the stuck request. This is a liveness failure, not a throughput concern.

The `?` on line 1320 is also an early return that occurs **before** the explicit
`drop(bm25_guard)` at line 1321; the guard is released by scope exit in that case, which is
correct but makes the explicit drop misleading.

**Fix:** Bound the awaited work and shorten the critical section.

```rust
let bm25_candidates = {
    let bm25_guard = self.bm25_index.read().await;
    tokio::select! {
        biased;
        _ = cancel.cancelled() => return Err(workflow::NodeError::cancelled()),
        res = tokio::time::timeout(retrieve_deadline, bm25_guard.retrieve(query_request, &self.effective_settings.retrieval)) => match res {
            Ok(inner) => inner.map_err(|err| workflow::NodeError::new(v1::NodeErrorKind::RetrievalFailed, err.to_string()))?,
            Err(_) => return Err(workflow::NodeError::new(v1::NodeErrorKind::Timeout, "BM25 retrieval timed out")),
        },
    }
};
```

Better still, snapshot the immutable index state (e.g. behind an `arc-swap`) so readers never
hold a lock across an await at all. Cross-references CR-02 (no deadline) and CR-04 (no
cancellation), which together make the unbounded hold reachable in production.

---

## Info

### IN-01: Node dispatch is keyed on stringly-typed names

**File:** `engine/src/workflow/runner.rs:104-113`, `:123`, `:142`, `:146`, `:173`, `:185`, `:226`, `:240`

**Issue:** `timeout_for_node` matches on `&str` literals (`"ReformulateQuery"`,
`"ExtractGraphContext"`, …) with a silent `_ => Duration::from_millis(5000)` fallback, and
the same literals are re-compared at seven other sites. A typo or a renamed node silently
falls through to the 5s default instead of failing to compile.

**Fix:** Introduce a `NodeKind` enum, have `Node::kind(&self) -> NodeKind`, and make
`timeout_for_node` an exhaustive `match` with no wildcard. Per `rust-guidelines.md`
M-DESIGN-FOR-AI / C-NEWTYPE, prefer strong types over primitive obsession.

---

### IN-02: `#[serde(default)]` on a `Serialize`-only struct is a no-op

**File:** `engine/src/retrieval/fusion.rs:33-34`

**Issue:**

```rust
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct FusedCandidate {
    // ...
    #[serde(default)]
    pub variant_provenance: Vec<VariantProvenance>,
}
```

`#[serde(default)]` only affects `Deserialize`, which `FusedCandidate` does not derive. The
attribute is dead and suggests a deserialization path that does not exist.

**Fix:** Remove the attribute, or add `Deserialize` if round-tripping is intended.

---

### IN-03: Provenance filtering compares source strings instead of the `Source` enum

**File:** `engine/src/retrieval/fusion.rs:130-146`

**Issue:** `VariantProvenance.source` is a `String`, and selection filters on
`p.source == "vector"` / `p.source == "bm25"`. The enum `Source` already exists
(fusion.rs:180-184) and is converted to a string on the way in. A typo in either literal
silently yields an empty filter and falls through to the `unwrap_or` branch.

Relatedly, the `.unwrap_or((value.vector_rank, value.vector_score))` fallbacks are
unreachable: `variant_provenance` is always populated whenever the corresponding
accumulator fields are set.

**Fix:** Store `source: Source` (deriving `Serialize` with a rename) and filter on the enum
variant.

---

### IN-04: `WorkflowDependencies` is constructed in production but entirely unused

**File:** `engine/src/main.rs:1719`, `engine/src/workflow/runner.rs:213`, `:218`

**Issue:** `query_rag` builds `WorkflowDependencies::new()` — every field `None` — passes it
to `run_tracer`, which passes it to the bridge closure, which binds it as `_deps`
(main.rs:1738) and ignores it. The whole struct and its plumbing are dead weight on the
production path. The port traits it holds (`QueryReformulator`, `QueryEmbeddingPort`,
`GraphQueryPort`, `DenseRetrievalPort`, `Bm25RetrievalPort`) are consumed only by tests.

**Fix:** Once CR-02 is addressed the dependencies should be populated from
`LancetServiceImpl` and injected into the real nodes. Until then, drop the parameter rather
than shipping a dead injection seam.

---

### IN-05: Timeout tests cannot distinguish the configured deadline from any shorter one

**File:** `engine/src/tests/workflow_phase5.rs:311-373`, `:377-441`

**Issue:** `workflow_phase5_reformulate_timeout_five_seconds` pauses the clock, advances
exactly 5000 ms, and asserts a `Timeout`. It never asserts that **no** timeout has fired at
4999 ms, so the test passes identically if the deadline were 100 ms — or, per CR-01, if the
configured value is ignored entirely. The same pattern applies to the 10 s retrieve test.

**Fix:** Add a negative half:

```rust
tokio::time::advance(Duration::from_millis(4_999)).await;
assert!(rx.try_recv().is_ok() || true); // no NodeFailed yet
assert!(!events_contain_node_failed(&mut rx), "must not time out before the deadline");
tokio::time::advance(Duration::from_millis(1)).await;
// now assert the Timeout
```

More importantly, add an end-to-end test that drives the timeout value **from parsed
config**, which would have caught CR-01.

Separately, `workflow_phase5_happy_path`'s drain loop (`tests/workflow_phase5.rs:132-136`)
calls `rx.recv().await` until the sender drops, with no `tokio::time::timeout` wrapper.
`AbortOnDrop` only fires after the loop exits, so a stalled workflow hangs the test rather
than failing it — a CI hang instead of a red build. Wrap the drain in
`tokio::time::timeout(Duration::from_secs(5), ...)`.

---

_Reviewed: 2026-08-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
