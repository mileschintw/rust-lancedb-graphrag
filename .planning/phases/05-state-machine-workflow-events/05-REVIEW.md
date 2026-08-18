---
phase: 05-state-machine-workflow-events
reviewed: 2026-08-18T09:43:44Z
depth: standard
files_reviewed: 36
files_reviewed_list:
  - buf.gen.yaml
  - buf.yaml
  - config/config.example.toml
  - config/config.toml
  - config/config.verify.toml
  - engine/src/bin/seed_rag_fixture.rs
  - engine/src/generation/mod.rs
  - engine/src/generation/openrouter.rs
  - engine/src/graph/extraction.rs
  - engine/src/graph/mod.rs
  - engine/src/lib.rs
  - engine/src/main.rs
  - engine/src/pb/mod.rs
  - engine/src/prompt.rs
  - engine/src/retrieval/bm25.rs
  - engine/src/retrieval/dense.rs
  - engine/src/retrieval/fusion.rs
  - engine/src/retrieval/mod.rs
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
  - gateway/db/schema.hcl
  - gateway/db/schema.sql
  - gateway/main.go
  - proto/lancet/v1/lancet.proto
findings:
  critical: 1
  warning: 11
  info: 15
  total: 27
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-08-18T09:43:44Z
**Depth:** standard
**Files Reviewed:** 36
**Status:** issues_found

## Summary

### Scope narrowing (recorded verbatim, on the record)

> This phase's full changed-file set was 47 files / 1233KB. 11 files (787KB) were deliberately
> excluded from line-by-line review and are NOT in files_reviewed_list:
>   Generated code (machine output, wire contract already proven by plan 05-23):
>     - engine/src/pb/lancet/v1/lancet.v1.rs (15KB)
>     - gateway/proto/lancet/v1/lancet.pb.go (91KB)
>     - gateway/proto/lancet/v1/lancet_grpc.pb.go (12KB)
>     - gateway/db/query.sql.go (9KB)
>   Test files (claim-vs-actual test adequacy is the phase verifier's job, not code review's):
>     - engine/src/tests.rs (258KB)
>     - engine/src/tests/workflow_phase5.rs (120KB)
>     - engine/src/tests/workflow_phase5_production.rs (57KB)
>     - engine/src/generation/tests.rs (61KB)
>     - engine/src/retrieval/tests.rs (35KB)
>     - engine/src/rerank/tests.rs (1KB)
>     - gateway/main_test.go (127KB)

### Assessment

**Review focus item 1 — production wiring: CONFIRMED GENUINE.** `LancetServiceImpl::build_production_workflow`
(`engine/src/main.rs:1523-1609`) registers all five nodes on the real `WorkflowRunner` with real adapters
(`ProductionEmbeddingPort`, `ProductionGraphQueryPort`, `ProductionDenseRetrievalPort`,
`ProductionBm25RetrievalPort`, the real reranker, and the real `OpenRouterGenerator`).
`query_rag` (`main.rs:1728-1833`) calls `runner.run_workflow(...)` directly — not `run_tracer`, not an
inline bridge. The old `execute_inline_query_rag_remainder` was deleted in this diff. No test-only path
carries the real work. (But a *second*, inline, always-broken remainder path is still exported from
`workflow/mod.rs` — WR-06.)

**Review focus item 2 — event emission:** NodeStarted / NodeCompleted / AnswerChunk / FinalAnswer /
Checkpoint / WorkflowCompleted are all emitted on the production path. One reachable defect (CR-01)
drops both `NodeFailed` and `WorkflowCompleted` and misclassifies a `Timeout` as `Cancelled` under
client backpressure; one further path (WR-02) is latent behind an unenforced invariant.

**Review focus item 3 — Rust→Go SSE transport:** cancellation propagates correctly (`r.Context()` is the
gRPC call context; `CancelOnDropStream` cancels the workflow token when the stream is dropped). No
goroutine leak in `queryRAG`; the `r.Context().Err()` guards around every write are correct. The
checkpoint dispatcher's ordering and drain logic are sound — but its shutdown is unreachable (WR-01).

**Review focus item 4 — timeouts/retries:** capability preflight is correctly moved out of the node
timer into `Node::prepare()` (`generate.rs:55-70`, `runner.rs:342-359`), which is the right fix for
deadline accounting. But the cross-field timeout invariants the 2-attempt retry design depends on are
unvalidated and are already violated in a committed config (WR-03), and every non-2xx chat response is
classified retryable (WR-04).

**Review focus item 5 — checkpoint persistence:** SQL goes through sqlc-generated parameterized
statements (`gateway/db/query.sql:116-133`) — **no injection**. Errors are logged but swallowed with no
retry, and `context_snapshot` is not validated before hitting a `jsonb NOT NULL` column (WR-07).

**Review focus item 6 — config secrets scan: CLEAN.** No API keys, tokens, or credentials introduced.
`config/config.example.toml:2-3` correctly directs the OpenRouter key to the `OPENROUTER_API_KEY`
environment variable. See IN-14 for a pre-existing, out-of-diff note on `config/config.toml`.

**Coverage note:** `engine/src/bin/seed_rag_fixture.rs` (213-line diff) was read in full; it is a
fixture-seeding binary with no production call path. One nit recorded as IN-15.

## Critical Issues

### CR-01: `run_node` cancels the workflow *before* emitting `NodeFailed`, poisoning its own delivery path

**File:** `engine/src/workflow/runner.rs:348-356`, `engine/src/workflow/runner.rs:361-371`, `engine/src/workflow/runner.rs:391-398`

**Issue:** On both the preparation-failure branch (348) and the timeout branch (361-371),
`cancel.cancel()` is called *before* the corresponding `NodeFailed` event is emitted. `send_event` →
`flush_pending_checkpoints` (134-144) and `send_envelope` (100-110) use a `biased` `tokio::select!`
whose first arm is `cancel.cancelled()`. Once the token is already cancelled, that arm wins
deterministically whenever the slow path is taken.

**Precondition (stated so this is not read as speculation):** reachable when `self.tx.capacity() == 0`
— all 100 buffered events outstanding (`main.rs:1798`, `mpsc::channel(100)`) — which is exactly what a
slow SSE consumer produces via gRPC flow control back onto the engine. In that state:

1. `NodeFailed` is never delivered — the client never learns which node failed.
2. `send_event_or_cancel` returns `NodeError::cancelled()`, and the `?` at line 354 / 396 **replaces the
   real error**, so a `Timeout` is reported upward as `Cancelled`. Note the `return Err(err)` at line
   355 is unreachable in this case.
3. `emit_terminal_once` (485) then runs with the same cancelled token, takes the same branch, and drops
   `WorkflowCompleted` too — the stream ends with no terminal event at all, and `terminal_emitted` is
   already latched (492-498) so nothing retries.

The detail that makes this unambiguous: **`cancel.cancel()` on the timeout branch is not needed to stop
the node.** `tokio::time::timeout` has already dropped the node future by the time line 367 runs. The
call's only effect is to poison the sink's own delivery path.

**Fix:** Emit the failure event first, then cancel; never let a delivery failure replace the node error.

```rust
// preparation branch (348-356)
if let Err(err) = preparation {
    let _ = sink
        .send_event_or_cancel(
            events::node_failed(name, err.kind.clone(), &err.message, err.retryable),
            cancel,
        )
        .await;                 // do not `?` — that would mask `err`
    cancel.cancel();
    return Err(err);
}

// timeout branch (361-371): drop the cancel() entirely — timeout() already dropped the future
res = timeout(node_timeout, node.run(ctx, cancel)) => match res {
    Ok(inner) => inner,
    Err(_) => Err(NodeError::timeout(name)),
},

// failure-emit branch (391-398)
Err(err) => {
    let _ = sink
        .send_event_or_cancel(
            events::node_failed(name, err.kind.clone(), &err.message, err.retryable),
            cancel,
        )
        .await;                 // preserve `err`; never replace it with Cancelled
}
```

## Warnings

### WR-01: `dispatcher.Close()` is unreachable — buffered checkpoints are lost and an in-flight write is abandoned on every exit

**File:** `gateway/main.go:1075-1076`, `gateway/main.go:1088-1089`, `gateway/checkpoint_sink.go:276-288`

**Issue:** `defer dispatcher.Close()` is registered at `main.go:1076`, but the only exit path from `main`
is `logger.Fatal("gateway stopped", ...)` at `main.go:1089`, and `zap.Logger.Fatal` calls `os.Exit(1)` —
**deferred functions do not run**. There is no signal handler and nothing calls `server.Shutdown()`, so
`ListenAndServe` never returns `http.ErrServerClosed` either. `Close()` is therefore dead in every
realistic exit path (including SIGTERM in a container).

Consequence is bounded but real: at exit, up to 1 (`primary`, cap 1) + 4 (`overflow`) + 16 (`pending`)
buffered envelopes are dropped without being written, and any `SaveCheckpoint` in flight is abandoned
mid-transaction rather than being allowed to finish. `defer pool.Close()` (`main.go:1062`) and
`defer conn.Close()` (`main.go:1067`) are dead for the same reason.

*(Verified not a finding: the dispatcher's drain order is correct. `nextEnvelope` drains `primary` →
`overflow` → `pending` before ever blocking at line 257, and `Submit` can only return `DispatchPending`
when both `primary` and `overflow` are full — impossible while a receiver is parked. Retained envelopes
always drain once the current `SaveCheckpoint` returns. No lost wakeup exists.)*

**Fix:** Replace the fatal-exit shutdown with a graceful one so the existing `Close()` drain actually runs.

```go
go func() {
    if err := server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
        logger.Error("gateway stopped", zap.Error(err))
    }
}()
sigCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
defer stop()
<-sigCtx.Done()
shutCtx, cancelShut := context.WithTimeout(context.Background(), 15*time.Second)
defer cancelShut()
_ = server.Shutdown(shutCtx)
dispatcher.Close() // now actually reached; drains primary/overflow/pending
```

### WR-02: A terminal-checkpoint failure can suppress the client-visible `WorkflowCompleted` — held safe only by an unenforced invariant

**File:** `engine/src/workflow/runner.rs:510-515`

**Issue:** `emit_terminal_once` sends `FinalAnswer`, then `send_checkpoint_or_error("terminal_success", ...)`,
then `WorkflowCompleted`. If the checkpoint returns `Err`, the function `return`s at line 514 and never
emits `WorkflowCompleted`, with `terminal_emitted` already latched so nothing retries. The client sees a
`final_answer` frame followed by an abrupt EOF; the gateway reports `STREAM_EOF_WITHOUT_TERMINAL`
(`main.go:737-739`).

Today the dangerous variant is unreachable: reaching line 510 requires `send_event_or_cancel(final_answer)`
to have returned `Sent` (guard at 506-509), which means `flush_pending_checkpoints` drained `pending` to
empty, so the immediately following `send_checkpoint` sees `pending.is_empty()`, takes `try_send`, and
can return at most `Pending` — never `OwnershipFailure { len >= 32 }`. The remaining `Err` case is
`Closed`, where `WorkflowCompleted` was undeliverable anyway.

This is control flow in which an **observability** failure is structurally able to suppress a
**protocol** event, held safe only by a drain invariant that nothing asserts and that any reordering of
`emit_terminal_once` would break.

**Fix:** Make the terminal event unconditional; degrade the checkpoint to a log.

```rust
if let Err(err) = sink.send_checkpoint_or_error("terminal_success", ctx, cancel) {
    tracing::warn!(error = %err, "terminal checkpoint dropped; continuing to terminal event");
    // fall through — WorkflowCompleted must always be attempted
}
match sink
    .send_event_or_cancel(
        events::workflow_completed(true, duration_ms, NodeErrorKind::Unspecified, "",
                                   Some(response), ctx.notices.clone()),
        cancel,
    )
    .await
{ Ok(()) | Err(_) => {} }
```

### WR-03: `WorkflowSettings::validate()` enforces only non-zero — the cross-field invariants the retry design depends on are unchecked, and one committed config already violates them

**File:** `engine/src/main.rs` (`WorkflowSettings::validate`, the seven `== 0` checks), `config/config.verify.toml:9-19`, `engine/src/workflow/nodes/generate.rs:105-128`

**Issue:** `GenerateAnswerNode::run` makes up to **two** provider attempts inside a **single** node timer
(`generate.rs:105` and `generate.rs:127`). The design therefore requires
`generation_node_timeout_ms >= 2 * generation_timeout_secs * 1000`. Production (`config/config.toml`)
satisfies this by 5s (65000 vs 60000) — by coincidence, not by enforcement.
`config/config.verify.toml` inverts it outright: `generation_node_timeout_ms = 7000` against
`generation_timeout_secs = 30`, so the node timer fires before even the *first* attempt can complete and
the retry budget is unreachable.

The same shape applies to graph: `ExtractGraphContextNode` runs `query_embedding_timeout_ms` (10000)
then `graph_operation_timeout_ms` (4000) = 14000 inside `graph_node_timeout_ms` = 15000 — a 1s
unenforced margin. `validate()` accepts every inversion silently, in production.

**Fix:** Validate the cross-field relations where the provider timeout is in scope
(`EffectiveRagSettings::try_from_settings`, which already reads `settings.openrouter`).

```rust
pub fn validate_against_provider(&self, generation_timeout_secs: u64) -> Result<(), String> {
    const GENERATION_ATTEMPTS: u64 = 2; // GenerateAnswerNode performs up to 2 attempts
    let required = GENERATION_ATTEMPTS
        .saturating_mul(generation_timeout_secs.saturating_mul(1000));
    if self.generation_node_timeout_ms < required {
        return Err(format!(
            "generation_node_timeout_ms ({}) must be >= {} ({} attempts x {}s provider timeout)",
            self.generation_node_timeout_ms, required, GENERATION_ATTEMPTS, generation_timeout_secs
        ));
    }
    let graph_required = self.query_embedding_timeout_ms + self.graph_operation_timeout_ms;
    if self.graph_node_timeout_ms < graph_required {
        return Err(format!(
            "graph_node_timeout_ms ({}) must be >= query_embedding_timeout_ms + graph_operation_timeout_ms ({})",
            self.graph_node_timeout_ms, graph_required
        ));
    }
    Ok(())
}
```

### WR-04: Every non-2xx chat response is classified `ProviderError`, so a 401/400 is retried for a second full provider timeout

**File:** `engine/src/generation/openrouter.rs:599-604`, `engine/src/workflow/nodes/generate.rs:116-128`

**Issue:** `execute_one_call` maps **all** unsuccessful HTTP statuses to
`GenerationErrorKind::ProviderError`. `GenerateAnswerNode` treats `ProviderError` as retryable
(`generate.rs:116-117`) and immediately re-issues a byte-identical request. A permanently failing
condition — bad or expired API key (401), malformed payload (400), model not permitted (403), quota
exhausted (402) — therefore burns a second full `generation_timeout_secs` window and a second billable
call before failing, and doubles user-visible latency on the most common misconfiguration.

The preflight path in the same file *does* discriminate correctly
(`status.is_server_error()` → `ProviderError`, else `SupportedParameters`, at `openrouter.rs:363-374`);
the chat path does not. The two should not disagree.

**Fix:** Mirror the preflight classification on the chat path.

```rust
let status = response.status();
if !status.is_success() {
    let kind = if status.is_server_error()
        || status == reqwest::StatusCode::TOO_MANY_REQUESTS
    {
        GenerationErrorKind::ProviderError      // transient -> retryable
    } else {
        GenerationErrorKind::InvalidRequest     // 4xx -> do not retry
    };
    return Err(GenerationError::new(
        kind,
        format!("OpenRouter chat completion returned HTTP {status}"),
    ));
}
```

### WR-05: `d1_status` was deleted — the engine no longer emits the `x-lancet-*` trailers the gateway still reads

**File:** `engine/src/main.rs` (removed `d1_status` helper), `gateway/main.go:771-783`

**Issue:** `handlePreStreamError` reads `x-lancet-session-id`, `x-lancet-correlation-id`, and
`x-lancet-error-kind` from gRPC trailer metadata and promotes them to response headers. This diff
deleted `d1_status`, the only production code that attached that metadata. A repo-wide grep for
`x-lancet` under `engine/src` now matches **only** `engine/src/tests.rs:2493-2499` — the contract is
satisfied exclusively by a test double. In production, every pre-stream failure
(`main.rs:1737-1744` session-id validation, `main.rs:1756-1773` query validation) now returns a bare
`Status` with empty trailers, so the gateway silently sets none of those headers. Green tests here
prove the fake, not the engine.

**Fix:** Restore trailer attachment on the production pre-stream error paths in `query_rag`, or delete
the gateway-side reader and its assertions so the contract is not silently half-implemented.

```rust
fn tagged_status(code: tonic::Code, message: impl Into<String>,
                 session_id: &str, correlation_id: &str, error_kind: &str) -> Status {
    let mut status = Status::new(code, message.into());
    let md = status.metadata_mut();
    if let Ok(v) = session_id.parse()     { md.insert("x-lancet-session-id", v); }
    if let Ok(v) = correlation_id.parse() { md.insert("x-lancet-correlation-id", v); }
    if let Ok(v) = error_kind.parse()     { md.insert("x-lancet-error-kind", v); }
    status
}
```

### WR-06: `run_inline_prompt_generation_remainder` is exported production API that can never succeed against the real generator

**File:** `engine/src/workflow/mod.rs:164-259`, `engine/src/workflow/runner.rs:438-483`

**Issue:** This `pub` function is dead in production (`query_rag` uses `run_workflow`; only tests call
`run_tracer`), but it is not merely a lower-fidelity duplicate — it is **broken by construction**:

- Lines 201-203 build `GenerationRequest::new(ctx.original_query.clone(), vec![])` — **empty evidence**.
  `OpenRouterGenerator::execute_one_call` passes that straight into `pack_evidence_and_graph_prompt`,
  which returns `PromptAssemblyError::EmptyEvidence` (`prompt.rs:330-332`) →
  `GenerationErrorKind::InvalidRequest`. Against a real generator this path *always* fails.
- The `ctx.assembled_prompt` it builds at 180-188 is never transmitted anywhere.
- Lines 208-211 retry unconditionally on any error, ignoring the error class (contradicting the
  discriminating policy in `GenerateAnswerNode`) and without setting `req.cancel`, so the retry is not
  cancellation-aware.
- Lines 190 and 218 emit hardcoded fake `duration_ms` values of `1` and `10`.

Shipping this as public API invites a caller to wire it up and get an always-failing pipeline.
`WorkflowDependencies` (`mod.rs:132-162`) exists solely to feed it and likewise has no production
consumer.

**Fix:** Gate `run_inline_prompt_generation_remainder`, `WorkflowRunner::run_tracer`, and
`WorkflowDependencies` behind `#[cfg(test)]` (or move them into the test module), or delete them. If
they must stay, pass `ctx.evidence_blocks.clone()` / `ctx.graph_facts.clone()` into the request, set
`req.cancel`, and remove the unconditional retry.

### WR-07: Checkpoint persistence failures are swallowed, and `context_snapshot` is written to a `jsonb NOT NULL` column without validation

**File:** `gateway/checkpoint_sink.go:216-218`, `gateway/checkpoint_sink.go:111`, `gateway/db/schema.sql:52`

**Issue:** `loop()` discards the result: `_ = d.sink.SaveCheckpoint(context.Background(), env)`. There is
no retry and no dead-letter path — a transient Postgres error permanently loses that checkpoint.
`PostgresCheckpointSink` logs internally (line 116-118), but the interface makes no such guarantee and
`InMemoryCheckpointSink` does not. Go guidelines require unchecked error returns to be handled
explicitly rather than assigned to `_`.

Separately, `ContextSnapshot` is passed through as raw `[]byte` into a `jsonb NOT NULL` column with no
validation. `NewCheckpointEnvelopeFromEvent` (31-51) accepts whatever the engine sent; an empty or
non-JSON string produces `invalid input syntax for type json`, which is then swallowed by the same
discard.

**Fix:**

```go
// SaveCheckpoint — fail fast and legibly instead of at the wire
if !json.Valid([]byte(env.ContextSnapshot)) {
    return fmt.Errorf("checkpoint %s/%d has invalid JSON context_snapshot",
        env.TraceID, env.SequenceOrdinal)
}

// loop()
if d.sink != nil {
    if err := d.sink.SaveCheckpoint(context.Background(), env); err != nil {
        d.recordDropped(env, err) // counter / dead-letter; at minimum an explicit log at this level
    }
}
```

### WR-08: Checkpoints submitted or retained after `Close()` are silently discarded

**File:** `gateway/checkpoint_sink.go:180-182`, `gateway/checkpoint_sink.go:196-207`, `gateway/main.go:800-805`

**Issue:** After `Close()` sets `d.closed`, `Submit` returns `DispatchPending` with the envelope
(lines 180-182). The caller at `main.go:801-805` then calls `RetainPending`, which appends to
`d.pending` — but `loop()` has already exited, so nothing will ever drain it. The envelope is lost with
no error and no log. `RetainPending` returns an error only when the queue is *full*, never when the
dispatcher is closed, so the caller's error branch (`main.go:802-804`) does not fire.

**Fix:**

```go
func (d *CheckpointDispatcher) RetainPending(env *CheckpointEnvelope) error {
    if env == nil { return nil }
    d.mu.Lock()
    defer d.mu.Unlock()
    if d.closed {
        return errors.New("checkpoint dispatcher is closed")
    }
    if len(d.pending) >= 16 {
        return errors.New("checkpoint pending queue is full")
    }
    d.pending = append(d.pending, env)
    return nil
}
```

### WR-09: Hand-written `PartialEq for GenerationRequest` misuses `f64::EPSILON` and will silently ignore future fields

**File:** `engine/src/generation/mod.rs:394-404`

**Issue:** Two defects in one impl, introduced when the new `cancel` field forced removal of
`#[derive(PartialEq)]` (`mod.rs:376`, `mod.rs:390-391`):

1. Line 400 compares `graph_weight` with `(a - b).abs() < f64::EPSILON`. `f64::EPSILON` (~2.22e-16) is
   the ULP at 1.0. `graph_weight`'s validated range is `0.0..=16.0`; near the top of that range this is
   *stricter* than a meaningful tolerance (an exact-bit test wearing a tolerance's clothes), and for
   values near zero it reports equality for genuinely different numbers. `graph_weight` is a config
   value copied verbatim, never computed — a tolerance is not wanted at all.
2. Because the impl is manual, any field added to `GenerationRequest` is silently excluded from
   equality — and this type's equality is exactly what the phase's "byte-identical retry snapshot"
   assertions rest on.

**Fix:** Compare exactly, and destructure so new fields break the build.

```rust
impl PartialEq for GenerationRequest {
    fn eq(&self, other: &Self) -> bool {
        let Self { system_policy, question, evidence, graph_facts, graph_weight,
                   session_id, correlation_id, cancel: _ } = self; // new fields fail to compile
        *system_policy == other.system_policy
            && *question == other.question
            && *evidence == other.evidence
            && *graph_facts == other.graph_facts
            && graph_weight.to_bits() == other.graph_weight.to_bits()
            && *session_id == other.session_id
            && *correlation_id == other.correlation_id
    }
}
```

### WR-10: Sequence ordinals are consumed on failed deliveries, producing gaps that look like lost events

**File:** `engine/src/workflow/runner.rs:71-79`, `engine/src/workflow/runner.rs:185-217`

**Issue:** `wrap_next_event` (line 72) and `send_checkpoint` (line 185) both call `self.sequence.next()`
*before* delivery is attempted. When delivery then returns `Closed`, `Cancelled`, or
`OwnershipFailure`, the ordinal is burned and never appears on the wire. Since
`WorkflowEvent.sequence_ordinal` is a strictly monotonic counter (`events.rs:250-264`) that a consumer
would naturally use for gap detection — and the gateway persists it as
`workflow_checkpoints.sequence_ordinal` for ordering — consumers cannot distinguish "event dropped in
transit" from "ordinal reserved then abandoned". `CheckpointDelivery::OwnershipFailure` even reports the
abandoned ordinal in its error text (line 232-237), confirming the gap is known at the source but never
communicated downstream.

**Fix:** Allocate the ordinal only on successful hand-off, keeping the cancellation-aware reserve.

```rust
async fn send_envelope_lazy(
    &self,
    make: impl FnOnce(u64) -> WorkflowEvent,
    cancel: &CancellationToken,
) -> ClientEventDelivery {
    if self.tx.is_closed() { return ClientEventDelivery::Closed; }
    let permit = tokio::select! {
        biased;
        _ = cancel.cancelled() => return ClientEventDelivery::Cancelled, // keep cancellation safety
        res = self.tx.reserve() => match res {
            Ok(p) => p,
            Err(_) => return ClientEventDelivery::Closed,
        },
    };
    permit.send(Ok(make(self.sequence.next()))); // ordinal issued only once capacity is held
    ClientEventDelivery::Sent
}
```

### WR-11: `WorkflowEventSink::wrap_event` panics via `unreachable!()` on a shared, cloneable sink

**File:** `engine/src/workflow/runner.rs:245-256`

**Issue:** `wrap_event` matches the event and calls `unreachable!("checkpoint helper must pass a
checkpoint event")` for any non-checkpoint variant. The invariant is enforced only by the single current
caller (`send_checkpoint`, line 186); nothing in the type system prevents a future caller from passing
another variant. `WorkflowEventSink` is `Clone` and is moved into the spawned workflow task
(`main.rs:1824-1830`), so a panic here aborts that task, drops `tx`, and terminates the client stream
with no terminal event and no diagnostic beyond a panic message. A private formatting helper should not
be able to kill a request.

**Fix:** Make the invariant structural rather than a runtime assertion.

```rust
fn wrap_checkpoint_event(&self, checkpoint: CheckpointEvent) -> WorkflowEvent {
    let sequence_ordinal = checkpoint.sequence_ordinal;
    events::wrap_event(
        Event::Checkpoint(checkpoint),
        sequence_ordinal,
        self.trace_id.clone(),
        self.session_id.clone(),
    )
}
```

## Info

### IN-01: `engine/src/workflow/context.rs` never existed — benign SUMMARY overclaim, no missing deliverable

**File:** `engine/src/workflow/mod.rs:31-52`

**Issue:** Verified as requested. `git log --all -- engine/src/workflow/context.rs` returns **no
history**, and the file is absent from `engine/src/workflow/` (which contains only `events.rs`,
`mod.rs`, `node.rs`, `nodes/`, `ports.rs`, `runner.rs`). `pub struct WorkflowContext` is defined at
`workflow/mod.rs:32` with its full impl (`new`, `add_notice`, `merge_notices`, `to_query_rag_response`,
`update_from_model_output`) at lines 54-130. **Confirmed benign**: the type was folded into `mod.rs`;
nothing is missing. Plan 05-01's `SUMMARY.md` `key-files.created` entry is simply inaccurate.

**Fix:** Correct plan 05-01 `SUMMARY.md` to list `engine/src/workflow/mod.rs` instead of
`engine/src/workflow/context.rs`.

### IN-02: Widened `pub(crate)` → `pub` visibility is a consequence of the crate split, not test hygiene

**File:** `engine/src/main.rs:33-38`, `engine/src/graph/mod.rs:289`, `engine/src/graph/mod.rs:647`, `engine/src/graph/extraction.rs:87`, `engine/src/retrieval/bm25.rs:171`, `engine/src/retrieval/dense.rs:37`, `engine/src/retrieval/dense.rs:42`, `engine/src/retrieval/dense.rs:162`, `engine/src/retrieval/mod.rs:62`

**Issue:** `main.rs` changed from declaring its own `pub mod generation/graph/prompt` + `mod rerank/retrieval`
to `use engine::{generation, graph, prompt, rerank, retrieval}`. The binary is a **separate crate** from
the `engine` library, so every item it touches had to leave `pub(crate)`. That is the correct mechanical
consequence — but it permanently enlarges the library's public API: notably `graph::escape_sql_literal`,
`graph::narrow_via_cypher`, `Bm25Index::from_table`, `DenseRetriever::new`, `DenseRetriever::query`,
`dense::dense_score`, `graph::extraction::extract_with_retry`, and `RetrievalError::new`.
`escape_sql_literal` is security-relevant (single-quote doubling for LanceDB predicates) and is now
callable by any downstream consumer without the surrounding validation that made it safe.

**Fix:** Introduce a `#[doc(hidden)] pub mod internal` re-export module, or gate these behind a
`binary-internals` Cargo feature, so the intended public surface stays small.

### IN-03: Production always takes the single-variant fusion path — cross-variant RRF is unexercised

**File:** `engine/src/main.rs:1548-1549`, `engine/src/workflow/ports.rs:37-45`, `engine/src/retrieval/fusion.rs:236-244`

**Issue:** `build_production_workflow` wires `NoOpQueryReformulator`, whose `reformulate` returns
`vec![query.to_string()]`. So `ctx.variants.len() == 1` always, `per_variant_fused` has exactly one
entry, and `fuse_cross_variant_candidates` hits the `len() == 1` early return at line 236. In production
the entire two-pass cross-variant RRF (plan 05-24), the 8-variant caps (`reformulate.rs:47-55`,
`fusion.rs:225-230`), and `RetrievalSnapshot.variant_count > 1` / multi-element `variant_identities` are
never reached. Recorded so the capability is not assumed production-proven by this phase.

**Fix:** Document the intended activation path (a real reformulator) at `build_production_workflow`, or
mark plan 05-24's cross-variant behavior as production-unreached in the phase verification record.

### IN-04: Single-variant fusion path skips the `candidate_limit` truncation the multi-variant path applies

**File:** `engine/src/retrieval/fusion.rs:236-244`, `engine/src/retrieval/fusion.rs:249-252`

**Issue:** The multi-variant path truncates each variant list with `.take(settings.candidate_limit)`
(line 251); the `len() == 1` early return (236-244) returns the list untouched. Because `fuse_candidates`
unions two sources each capped at `candidate_limit`, the single-variant result can contain up to
`2 * candidate_limit` entries where the multi-variant path caps at `candidate_limit`. Only the
downstream `final_limit` take (`retrieve.rs:165-168`) masks the difference — and it changes which
candidates reach the reranker.

**Fix:** Apply the same truncation on the single-variant branch:
`single_list.truncate(settings.candidate_limit);`

### IN-05: `WorkflowRunner::timeout_for_node` is dead code with a magic fallback

**File:** `engine/src/workflow/runner.rs:319-328`, `engine/src/workflow/runner.rs:241-243`

**Issue:** `timeout_for_node(&str)` has no production caller — all dispatch goes through the exhaustive
typed `timeout_for_kind(NodeKind)` at 309-317. It duplicates that mapping via string matching and adds
an unreachable-in-practice `_ => Duration::from_millis(5000)` magic fallback: exactly the stringly-typed
dispatch the phase's `NodeKind` work set out to eliminate, and a silent-wrong-timeout hazard if a node
name is ever misspelled. `pending_checkpoint_count` (241-243) is likewise test-only.

**Fix:** Delete `timeout_for_node`; gate `pending_checkpoint_count` behind `#[cfg(test)]`.

### IN-06: `buf.gen.yaml` `clean: true` → `clean: false` is likely forced by a hand-written file inside the generated tree

**File:** `buf.gen.yaml:2`, `engine/src/pb/mod.rs`

**Issue:** The plugin writes to `out: engine/src/pb`, and `engine/src/pb/mod.rs` is **hand-written** — a
5-line `include!("lancet/v1/lancet.v1.rs")` wrapper. `clean: true` would delete it on every
regeneration, so the flip was probably necessary rather than careless. The cost is that stale generated
artifacts now survive: a removed or renamed proto message leaves a compilable, importable orphan behind,
and the generated tree can silently diverge from `proto/`. This diff already required a hand-repair of
generated Rust literals (commit `253d612 fix(05-23): repair exhaustive Rust message literals after
protobuf generation`) — the symptom this setting makes permanent.

**Fix:** Move the hand-written wrapper out of the generated tree (e.g. `engine/src/pb.rs` declaring
`#[path = "pb/lancet/v1/lancet.v1.rs"]`) and restore `clean: true`; otherwise add a CI check that
`git status` is clean after regeneration.

### IN-07: `ctx.bm25_results` accumulates duplicate chunk IDs across variants

**File:** `engine/src/workflow/nodes/retrieve.rs:115-117`

**Issue:** The per-variant loop pushes every BM25 candidate's `chunk_id` into `ctx.bm25_results` with no
deduplication, while `ctx.vector_results` (84-87) is assigned once from a deduplicated dense list. With
N variants, a chunk matched by every variant appears N times. `ctx.bm25_results` is serialized verbatim
into every checkpoint snapshot (`events.rs:188`; one of the 19 declared `CHECKPOINT_SNAPSHOT_KEYS`), so
the persisted provenance record would misreport BM25 recall and grow super-linearly.

Currently latent: per IN-03, production runs exactly one variant, so the loop body executes once. This
activates the moment a real reformulator lands.

**Fix:**

```rust
let mut seen_bm25 = std::collections::HashSet::new();
// inside the variant loop
for candidate in &bm25_candidates {
    if seen_bm25.insert(candidate.chunk_id.clone()) {
        ctx.bm25_results.push(candidate.chunk_id.clone());
    }
}
```

### IN-08: `uint64` → `int32` narrowing on `sequence_ordinal`

**File:** `gateway/checkpoint_sink.go:109`, `gateway/db/schema.sql:47`, `gateway/db/models.go:45`

**Issue:** `SequenceOrdinal: int32(env.SequenceOrdinal)` narrows a protobuf `uint64` to the schema's
`integer` column with no bounds check; values ≥ 2^31 wrap to negative. Not realistically reachable
(2^31 events in one workflow), but it is an unchecked lossy conversion on a persisted ordering key.

**Fix:** Widen the column to `bigint` and the sqlc model to `int64`, or reject out-of-range values
explicitly before insert.

### IN-09: `notices` must be read from two different places depending on success

**File:** `gateway/main.go:853-868`

**Issue:** On success the gateway writes `final_response` (whose DTO already carries `notices`, sourced
from `WorkflowContext::to_query_rag_response` at `workflow/mod.rs:102`); on failure it writes a
top-level `wcPayload["notices"]`. Content is equivalent — this is not a loss — but a client must check
two locations depending on the `success` flag.

**Fix:** Always emit top-level `notices` on `workflow_completed`, in addition to `final_response`.

### IN-10: Seven redundant cancellation checks inside one prompt-packing loop

**File:** `engine/src/prompt.rs:446`, `:456`, `:484`, `:504-505`, `:510`, `:524`

**Issue:** `pack_evidence_and_graph_prompt` checks `cancel.is_cancelled()` at the top of the loop (446),
again inside each match arm (456, 484), again after `yield_now()` (505), and twice more after the loop
(510, 524). Between the arm checks and the post-yield check there is no `await`, so those cannot observe
a state change. The redundancy obscures where cancellation is actually meaningful — the
`yield_now().await` at 504 is the only true suspension point in the loop.

**Fix:** Keep the entry check (329), the post-`yield_now()` check (505), and one pre-return check;
delete 456, 484, and 510.

### IN-11: `let _ = &deps;` keep-alive hack in the spawned workflow task

**File:** `engine/src/main.rs:1826`, `engine/src/main.rs:1815`

**Issue:** `build_production_workflow` returns `(runner, deps)`, but `deps` has no production consumer —
the nodes already own their `Arc` clones. The spawned task contains `let _ = &deps;` purely to move the
value into the closure and suppress an unused-variable warning. A reader cannot tell whether that
lifetime is load-bearing.

**Fix:** Have `build_production_workflow` return only the runner (add a `#[cfg(test)]`-gated variant
returning `deps` for the tracer tests), and drop the `let _ = &deps;` line.

### IN-12: Model-capability cache never expires, and `ModelCapabilities` is written but never read

**File:** `engine/src/generation/openrouter.rs:234`, `engine/src/generation/openrouter.rs:325-345`

**Issue:** `capabilities_cache: HashMap<CapabilityKey, Arc<OnceCell<ModelCapabilities>>>` caches a
successful preflight for the entire process lifetime. If OpenRouter later withdraws
`response_format` / `structured_outputs` support for the configured model, the process keeps sending
strict-schema requests until restart. The success-only semantics are correct (errors leave the
`OnceCell` uninitialized, so they are retried) — the missing TTL is the gap. Separately,
`ModelCapabilities.supports_structured_outputs` is constructed but never read (`let _caps = ...` at
line 341); the cell's mere existence carries the whole signal, making the struct field dead weight.

**Fix:** Store `(ModelCapabilities, Instant)` and re-validate after a configurable TTL, or read
`supports_structured_outputs` at the call site so the field earns its place.

### IN-13: `workflow_checkpoints` has no uniqueness constraint on `(trace_id, sequence_ordinal)`

**File:** `gateway/db/schema.sql:45-56`, `gateway/db/schema.hcl:136-172`, `gateway/db/query.sql:116-133`

**Issue:** The new table's primary key is a client-generated `uuid.NewString()`
(`checkpoint_sink.go:88`) in a `varchar(255)` column, and the `(trace_id, sequence_ordinal, created_at)`
index is explicitly `unique = false` (`schema.hcl:167`). Any duplicate delivery or replay of the same
checkpoint inserts a second row indistinguishable from a legitimate one; nothing enforces at-most-once
per ordinal, and the insert is a plain `INSERT ... RETURNING *` with no conflict handling.

**Fix:** Make the index unique on `(trace_id, sequence_ordinal)` and change the statement to
`INSERT ... ON CONFLICT (trace_id, sequence_ordinal) DO NOTHING` so retried deliveries are idempotent.
Consider a native `uuid` column type for `id`.

### IN-14: Config secrets scan result — clean; pre-existing dev credential noted for the record

**File:** `config/config.example.toml:1-3`, `config/config.toml:3`, `config/config.verify.toml`

**Issue:** Recording the scan outcome required by the review brief. **No API keys, tokens, or secrets
are committed** in any config file. `config/config.example.toml:2-3` explicitly instructs that the
OpenRouter credential be supplied via `OPENROUTER_API_KEY` and never committed — correct.
`config/config.toml:3` contains `postgres://postgres:postgres@localhost:5432/lancet?sslmode=disable`,
a local development default. This file is **not part of this phase's diff** (only
`config/config.verify.toml` changed), so it is logged as pre-existing context, not as a phase finding.

**Fix:** In a follow-up unrelated to this phase, source `gateway.database_url` from an environment
variable so no credential-shaped string lives in the repository.

### IN-15: `seed_rag_fixture` defines a local `f32` copy of `dense_score` and then asserts against its own copy

**File:** `engine/src/bin/seed_rag_fixture.rs:85-87`, `engine/src/retrieval/dense.rs:162`

**Issue:** The fixture binary defines `fn dense_score(distance: f32) -> f32 { 1.0 / (1.0 + distance) }`,
a near-duplicate of the production `retrieval::dense::dense_score(f64)` — which this same diff made
`pub` (IN-02), so it is now directly importable. The local copy also omits the production version's
`distance.max(0.0)` clamp, so a negative distance produces a different result. The two assertions at the
end of the fixture (`assert_eq!(dense_score(0.0), 1.0)` and `assert!(dense_score(0.0) >= 0.5)`) exercise
the local copy, not the production function, so they prove nothing about retrieval scoring. No
production code path is affected — this is a fixture-only binary.

**Fix:** Delete the local helper and call `engine::retrieval::dense::dense_score` so the assertion
actually guards the production formula, or drop the two tautological assertions.

---

_Reviewed: 2026-08-18T09:43:44Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
