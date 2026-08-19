---
phase: 05-state-machine-workflow-events
reviewed: 2026-08-19T02:02:00Z
depth: standard
files_reviewed: 37
files_reviewed_list:
  - .gitignore
  - buf.gen.yaml
  - buf.yaml
  - config/config.example.toml
  - config/config.toml
  - config/config.verify.toml
  - engine/src/bin/seed_rag_fixture.rs
  - engine/src/db/mod.rs
  - engine/src/db/tests.rs
  - engine/src/generation/mod.rs
  - engine/src/generation/openrouter.rs
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
  warning: 15
  info: 18
  total: 34
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-08-19T02:02:00Z (refresh at HEAD `e6e153f`)
**Depth:** standard
**Files Reviewed:** 37
**Status:** issues_found

## Summary

This is a **refresh** of the 2026-08-18T09:43:44Z review. Every finding below was re-derived
against the working tree at HEAD (`e6e153f`), not carried forward. The prior report predated
`edaf907` (d1_status restoration), `989003b` (generation_model switch), `967a897` (plan 05-25) and
`c815af1` (plan 05-26).

### Scope narrowing (recorded verbatim, on the record)

> This refresh's declared file set was 48 files. 11 files were deliberately excluded from
> line-by-line review and are NOT in `files_reviewed_list`; 37 were reviewed:
>   Generated code (machine output; wire contract proven by plan 05-23, regenerated from
>   `proto/lancet/v1/lancet.proto` and `gateway/db/query.sql`, both of which WERE reviewed):
>     - engine/src/pb/lancet/v1/lancet.v1.rs (15KB)
>     - gateway/proto/lancet/v1/lancet.pb.go (91KB)
>     - gateway/proto/lancet/v1/lancet_grpc.pb.go (12KB)
>     - gateway/db/query.sql.go (9KB)
>   Test files (claim-vs-actual test adequacy is the phase verifier's job, not code review's;
>   this exclusion is by *role*, not by size — it applies equally to the 1KB rerank tests):
>     - engine/src/tests.rs (7396 lines)
>     - engine/src/tests/workflow_phase5.rs (3152 lines)
>     - engine/src/tests/workflow_phase5_production.rs (1473 lines)
>     - engine/src/generation/tests.rs
>     - engine/src/retrieval/tests.rs
>     - engine/src/rerank/tests.rs
>     - gateway/main_test.go (3870 lines)
>
> Arithmetic: 48 declared - 11 excluded = 37 reviewed, matching `files_reviewed`.
>
> Two deviations from that blanket exclusion, both deliberate:
>   - `engine/src/db/tests.rs` (212 lines) was read in full and IS in `files_reviewed_list`; it
>     carries the plan 05-25 assertion and is explicitly in scope for this refresh (IN-15).
>   - `engine/src/tests.rs` and `gateway/main_test.go` carry the plan 05-26 hunks. Both remain
>     excluded from `files_reviewed_list` (so a downstream `--auto` re-review does not pull a
>     7396-line and a 3870-line test file back into full scope), but their `6243d2b..HEAD` diff
>     hunks (+50 and +4 lines respectively) WERE read. Neither hunk yielded a finding: the Rust
>     hunk adds env-override assertions, the Go hunk adds four env-map entries.

### Prior-finding ledger (persist / resolved / new)

**RESOLVED since the prior review (1):**
- **WR-05** (prior) — "`d1_status` was deleted; the engine no longer emits `x-lancet-*` trailers."
  **Fixed by `edaf907`.** `d1_status` now exists at `engine/src/main.rs:1159-1180` and is the
  error constructor on all three production pre-stream paths (`main.rs:1777`, `1786`, `1835`).
  The gateway reader at `gateway/main.go:771-783` now has a real producer. *(But the restored
  helper introduces a new defect of its own — WR-11.)*

**DROPPED as out of scope (1):**
- **IN-01** (prior) — "`engine/src/workflow/context.rs` never existed; SUMMARY overclaim." The
  target of that finding is a planning artifact (`05-01-SUMMARY.md`), which is excluded from
  code-review scope. The underlying code fact is unchanged and benign
  (`WorkflowContext` lives at `workflow/mod.rs:32`). Not re-filed.

**PERSIST, verified at HEAD (24):** prior CR-01 → CR-01; prior WR-01→WR-04 → WR-01→WR-04;
prior WR-06→WR-11 → WR-05→WR-10; prior IN-02→IN-13 and IN-15 → IN-01→IN-13. Prior IN-14
(config secrets scan) is **re-derived with a corrected premise** and promoted to WR-14: it stated
`config/config.toml` "is not part of this phase's diff," which is false for this refresh —
`config/config.toml` is in the declared file list and was changed by `989003b`.

**NEW in this refresh (10):** WR-11, WR-12, WR-13, WR-14, WR-15, IN-14, IN-15, IN-16, IN-17, IN-18.
WR-13/IN-15 cover plan 05-25 (`db/mod.rs`, `db/tests.rs`); IN-14 covers plan 05-26 (`main.rs`
env overrides); WR-11 covers the `edaf907` `d1_status` restoration; WR-14 covers `989003b`'s
config file now being in scope; IN-16 covers the `.gitignore` change.

### Assessment

**Production wiring — CONFIRMED GENUINE at HEAD.** `build_production_workflow`
(`main.rs:1560-1645`) registers all five nodes on the real `WorkflowRunner` with real adapters;
`query_rag` (`main.rs:1860-1895`) spawns `runner.run_workflow(...)` directly. No test-only path
carries production work. A second, inline, always-broken remainder path is still exported from
`workflow/mod.rs` (WR-05).

**Event emission.** NodeStarted / NodeCompleted / AnswerChunk / FinalAnswer / Checkpoint /
WorkflowCompleted are all emitted on the production path. One reachable defect (CR-01) drops
both `NodeFailed` and `WorkflowCompleted` and misclassifies `Timeout` as `Cancelled` under client
backpressure. Note that the `capacity() > 0` fast path at `runner.rs:90-98` is what *bounds*
CR-01 to the zero-capacity case — and it is itself a check-then-act race (WR-12).

**Rust→Go SSE transport.** Cancellation still propagates correctly (`CancelOnDropStream` cancels
the workflow token on stream drop; `r.Context().Err()` guards every write). The checkpoint
dispatcher's drain ordering is sound — re-verified: `nextEnvelope` drains `primary` → `overflow`
→ `pending` before ever parking at `checkpoint_sink.go:257`, and `Submit`/`Close` both mutate
`primary` under `d.mu`, so there is **no send-on-closed-channel race**. Its shutdown is
nonetheless unreachable (WR-01).

**Timeouts / retries.** Capability preflight is correctly hoisted out of the node timer into
`Node::prepare()` (`generate.rs:55-70`, `runner.rs:342-346`). The cross-field timeout invariants
the 2-attempt retry design depends on remain unvalidated and are still violated in a committed
config (WR-03); every non-2xx chat response is still classified retryable (WR-04).

**Checkpoint persistence.** SQL still goes through sqlc-generated parameterized statements
(`gateway/db/query.sql:116-133`) — **no injection**. Errors are still logged-and-discarded with no
retry, and `context_snapshot` still reaches a `jsonb NOT NULL` column unvalidated (WR-06).

**Config secrets scan.** No API keys or tokens are committed. `config/config.example.toml:1-3`
correctly routes the OpenRouter credential to `OPENROUTER_API_KEY`. `config/config.toml:3` carries
a default Postgres credential with `sslmode=disable` — **in scope this pass** (WR-14).

**Preflight-vs-committed-model check (new investigation).** `fetch_and_validate_capabilities`
(`openrouter.rs:417-441`) hard-fails `prepare()` unless the configured model is present in the
OpenRouter `/models` list *and* advertises one of `response_format` / `json_schema` /
`structured_outputs`. `config/config.toml:41` now pins
`generation_model = "dots-studio/dots-3-note-preview:free"`. Per `05-UAT.md:120` this value was
selected *specifically because* it was confirmed against the live `/api/v1/models` to advertise
structured-output support. **Not a finding** — recorded so the check is on the record rather than
assumed. `config/config.example.toml` still says `openai/gpt-4o-mini`, which is a documentation
drift, not a defect.

---

## Critical Issues

### CR-01: `run_node` cancels the workflow *before* emitting `NodeFailed`, poisoning its own delivery path

**File:** `engine/src/workflow/runner.rs:348-356`, `engine/src/workflow/runner.rs:361-371`, `engine/src/workflow/runner.rs:391-398`

**Issue:** On the preparation-failure branch (`runner.rs:349`) and the timeout branch
(`runner.rs:367`), `cancel.cancel()` is called *before* the corresponding `NodeFailed` event is
emitted. `send_event` → `flush_pending_checkpoints` (113-146) and `send_envelope` (100-110) use a
`biased` `tokio::select!` whose first arm is `cancel.cancelled()`. Once the token is already
cancelled, that arm wins deterministically whenever the slow path is taken.

**Precondition (stated so this is not read as speculation):** reachable when
`self.tx.capacity() == 0` — all 100 buffered events outstanding (`main.rs:1860`,
`mpsc::channel(100)`) — which is exactly what a slow SSE consumer produces via gRPC flow control
back onto the engine. Above zero capacity the fast path at `runner.rs:90-98` bypasses the
cancellation arm, which is why this is bounded rather than universal. In the zero-capacity state:

1. `NodeFailed` is never delivered — the client never learns which node failed.
2. `send_event_or_cancel` returns `NodeError::cancelled()`, and the `?` at line 354 / 396
   **replaces the real error**, so a `Timeout` is reported upward as `Cancelled`. The
   `return Err(err)` at line 355 is unreachable in this case.
3. `emit_terminal_once` (485) then runs with the same cancelled token, takes the same branch, and
   drops `WorkflowCompleted` too — the stream ends with no terminal event, and `terminal_emitted`
   is already latched (492-498) so nothing retries. The gateway then reports
   `STREAM_EOF_WITHOUT_TERMINAL` (`gateway/main.go:737-739`).

The detail that makes this unambiguous: **`cancel.cancel()` on the timeout branch is not needed to
stop the node.** `tokio::time::timeout` has already dropped the node future by the time line 367
runs. The call's only effect is to poison the sink's own delivery path.

**Fix:** Emit the failure event first, then cancel; never let a delivery failure replace the node
error.

```rust
// preparation branch (348-356)
if let Err(err) = preparation {
    let _ = sink
        .send_event_or_cancel(
            events::node_failed(name, err.kind.clone(), &err.message, err.retryable),
            cancel,
        )
        .await;                 // do NOT `?` — that would mask `err`
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

---

## Warnings

### WR-01: `dispatcher.Close()` is unreachable — buffered checkpoints are lost and an in-flight write is abandoned on every exit

**File:** `gateway/main.go:1076`, `gateway/main.go:1088-1089`, `gateway/checkpoint_sink.go:276-288`

**Issue:** `defer dispatcher.Close()` is registered at `main.go:1076`, but the only exit path from
`main` is `logger.Fatal("gateway stopped", ...)` at `main.go:1089`, and `zap.Logger.Fatal` calls
`os.Exit(1)` — **deferred functions do not run**. There is no signal handler and nothing calls
`server.Shutdown()`, so `ListenAndServe` never returns `http.ErrServerClosed` either. `Close()` is
dead in every realistic exit path, including SIGTERM in a container.

At exit, up to 1 (`primary`, cap 1) + 4 (`overflow`) + 16 (`pending`) buffered envelopes are
dropped unwritten, and any `SaveCheckpoint` in flight is abandoned. `defer pool.Close()`
(`main.go:1062`), `defer conn.Close()` (`main.go:1067`), `defer recCancel()` (`main.go:1069`) and
`defer logger.Sync()` (`main.go:1053`) are dead for the same reason.

**Fix:** Replace the fatal-exit shutdown with a graceful one so the existing `Close()` drain runs.

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

### WR-02: A terminal-checkpoint failure can suppress the client-visible `WorkflowCompleted`

**File:** `engine/src/workflow/runner.rs:510-515`

**Issue:** `emit_terminal_once` sends `FinalAnswer`, then
`send_checkpoint_or_error("terminal_success", ...)`, then `WorkflowCompleted`. If the checkpoint
returns `Err`, the function `return`s at line 514 and never emits `WorkflowCompleted`, with
`terminal_emitted` already latched so nothing retries. The client sees a `final_answer` frame
followed by an abrupt EOF; the gateway reports `STREAM_EOF_WITHOUT_TERMINAL`
(`gateway/main.go:737-739`).

Today the dangerous variant is unreachable: reaching line 510 requires
`send_event_or_cancel(final_answer)` to have returned `Sent` (guard at 503-509), which means
`flush_pending_checkpoints` drained `pending` to empty, so the immediately following
`send_checkpoint` sees `pending.is_empty()` (line 193), takes `try_send`, and can return at most
`Pending` — never `OwnershipFailure`. The remaining `Err` case is `Closed`, where
`WorkflowCompleted` was undeliverable anyway.

This is control flow in which an **observability** failure is structurally able to suppress a
**protocol** event, held safe only by a drain invariant that nothing asserts and that any
reordering of `emit_terminal_once` would break.

**Fix:** Make the terminal event unconditional; degrade the checkpoint to a log.

```rust
if let Err(err) = sink.send_checkpoint_or_error("terminal_success", ctx, cancel) {
    tracing::warn!(error = %err, "terminal checkpoint dropped; continuing to terminal event");
    // fall through — WorkflowCompleted must always be attempted
}
let _ = sink
    .send_event_or_cancel(
        events::workflow_completed(true, duration_ms, NodeErrorKind::Unspecified, "",
                                   Some(response), ctx.notices.clone()),
        cancel,
    )
    .await;
```

### WR-03: `WorkflowSettings::validate()` enforces only non-zero — the cross-field invariants the retry design depends on are unchecked, and a committed config already violates them

**File:** `engine/src/main.rs:258-280` (`WorkflowSettings::validate`, seven `== 0` checks), `config/config.verify.toml:12-19`, `engine/src/workflow/nodes/generate.rs:105`, `engine/src/workflow/nodes/generate.rs:127`

**Issue:** `GenerateAnswerNode::run` makes up to **two** provider attempts (`generate.rs:105` and
`generate.rs:127`) inside a **single** node timer. The design therefore requires
`generation_node_timeout_ms >= 2 * generation_timeout_secs * 1000`. Production
(`config/config.toml:17` = 65000 vs `config/config.toml:44` = 30s → 60000ms) satisfies this by 5s
— by coincidence, not by enforcement. `config/config.verify.toml` inverts it outright:
`generation_node_timeout_ms = 7000` against `generation_timeout_secs = 30`, so the node timer fires
before even the *first* attempt can complete and the retry budget is unreachable.

The same shape applies to graph: `ExtractGraphContextNode` runs `query_embedding_timeout_ms`
(10000, `graph_context.rs:74`) then `graph_operation_timeout_ms` (4000, `graph_context.rs:97`)
sequentially = 14000 inside `graph_node_timeout_ms` = 15000 — a 1s unenforced margin.
`validate()` accepts every inversion silently, in production.

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

**File:** `engine/src/generation/openrouter.rs:597-603`, `engine/src/workflow/nodes/generate.rs:116-128`

**Issue:** The chat path maps **all** unsuccessful HTTP statuses to
`GenerationErrorKind::ProviderError`. `GenerateAnswerNode` treats `ProviderError` as retryable
(`generate.rs:116-117`) and re-issues a byte-identical request. A permanently failing condition —
bad or expired API key (401), malformed payload (400), model not permitted (403), quota exhausted
(402) — therefore burns a second full `generation_timeout_secs` window and a second billable call
before failing, doubling user-visible latency on the most common misconfiguration.

The preflight path in the same file *does* discriminate correctly (`status.is_server_error()` →
`ProviderError`, else `SupportedParameters`, at `openrouter.rs:373-383`); the chat path does not.
The two should not disagree.

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

### WR-05: `run_inline_prompt_generation_remainder` is exported production API that can never succeed against the real generator

**File:** `engine/src/workflow/mod.rs:164-259`, `engine/src/workflow/runner.rs:438-483`

**Issue:** This `pub` function is dead in production (`query_rag` uses `run_workflow`; only tests
call `run_tracer`), but it is not merely a lower-fidelity duplicate — it is **broken by
construction**:

- Lines 200-203 build `GenerationRequest::new(ctx.original_query.clone(), vec![])` — **empty
  evidence**. `OpenRouterGenerator::execute_one_call` passes that into
  `pack_evidence_and_graph_prompt`, which returns `PromptAssemblyError::EmptyEvidence`
  (`prompt.rs:330-332`) → `GenerationErrorKind::InvalidRequest`. Against a real generator this
  path *always* fails.
- The `ctx.assembled_prompt` it builds at 181-188 is never transmitted anywhere.
- Lines 208-211 retry unconditionally on any error, ignoring the error class (contradicting the
  discriminating policy in `GenerateAnswerNode`) and without setting `gen_req.cancel`, so the
  retry is not cancellation-aware and the provider call cannot observe cancellation.
- Lines 190 and 218 emit hardcoded fake `duration_ms` values of `1` and `10`.

Shipping this as public API invites a caller to wire it up and get an always-failing pipeline.
`WorkflowDependencies` (`mod.rs:132-162`) exists solely to feed it and likewise has no production
consumer.

**Fix:** Gate `run_inline_prompt_generation_remainder`, `WorkflowRunner::run_tracer`, and
`WorkflowDependencies` behind `#[cfg(test)]` (or move them into the test module), or delete them.
If they must stay, pass `ctx.evidence_blocks.clone()` / `ctx.graph_facts.clone()` into the
request, set `gen_req.cancel`, and remove the unconditional retry.

### WR-06: Checkpoint persistence failures are swallowed, and `context_snapshot` is written to a `jsonb NOT NULL` column without validation

**File:** `gateway/checkpoint_sink.go:216-218`, `gateway/checkpoint_sink.go:111`, `gateway/db/schema.sql:51`

**Issue:** `loop()` discards the result: `_ = d.sink.SaveCheckpoint(context.Background(), env)`.
There is no retry and no dead-letter path — a transient Postgres error permanently loses that
checkpoint. `PostgresCheckpointSink` logs internally (116-118), but the `CheckpointSink` interface
makes no such guarantee and `InMemoryCheckpointSink` does not. `go-guidelines.md`'s modern-Go
error handling expects unchecked error returns to be handled explicitly rather than assigned to
`_`.

Separately, `ContextSnapshot` is passed through as raw `[]byte` (line 111) into a `jsonb NOT NULL`
column with no validation. `NewCheckpointEnvelopeFromEvent` (31-51) accepts whatever the engine
sent; an empty or non-JSON string produces `invalid input syntax for type json`, which is then
swallowed by the same discard. The Rust side happens to always emit valid JSON
(`events.rs:243-247`), but nothing on the Go side depends on or checks that.

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

### WR-07: Checkpoints submitted or retained after `Close()` are silently discarded

**File:** `gateway/checkpoint_sink.go:180-182`, `gateway/checkpoint_sink.go:196-207`, `gateway/main.go:800-805`

**Issue:** After `Close()` sets `d.closed`, `Submit` returns `DispatchPending` with the envelope
(180-182). The caller at `main.go:801-805` then calls `RetainPending`, which appends to
`d.pending` — but `loop()` has already exited, so nothing will ever drain it. The envelope is lost
with no error and no log. `RetainPending` returns an error only when the queue is *full*
(line 202), never when the dispatcher is closed, so the caller's error branch (`main.go:802-804`)
does not fire.

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

### WR-08: Hand-written `PartialEq for GenerationRequest` misuses `f64::EPSILON` and will silently ignore future fields

**File:** `engine/src/generation/mod.rs:392-403`

**Issue:** Two defects in one impl, introduced when the new `cancel` field forced removal of
`#[derive(PartialEq)]` (`mod.rs:376`, `mod.rs:389-390`):

1. Line 398 compares `graph_weight` with `(a - b).abs() < f64::EPSILON`. `f64::EPSILON` (~2.22e-16)
   is the ULP at 1.0. `graph_weight`'s validated range is `0.0..=16.0`; near the top of that range
   this is *stricter* than a meaningful tolerance (an exact-bit test wearing a tolerance's
   clothes), and for values near zero it reports equality for genuinely different numbers.
   `graph_weight` is a config value copied verbatim (`generate.rs:97`), never computed — a
   tolerance is not wanted at all.
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

### WR-09: Sequence ordinals are consumed on failed deliveries, producing gaps that look like lost events

**File:** `engine/src/workflow/runner.rs:71-79`, `engine/src/workflow/runner.rs:185-218`

**Issue:** `wrap_next_event` (line 72) and `send_checkpoint` (line 185) both call
`self.sequence.next()` *before* delivery is attempted. When delivery then returns `Closed`,
`Cancelled`, or `OwnershipFailure`, the ordinal is burned and never appears on the wire. Since
`WorkflowEvent.sequence_ordinal` is a strictly monotonic counter (`events.rs:250-264`) that a
consumer would naturally use for gap detection — and the gateway persists it as
`workflow_checkpoints.sequence_ordinal` for ordering — consumers cannot distinguish "event dropped
in transit" from "ordinal reserved then abandoned". `CheckpointDelivery::OwnershipFailure` even
reports the abandoned ordinal in its error text (232-237), confirming the gap is known at the
source but never communicated downstream.

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
        _ = cancel.cancelled() => return ClientEventDelivery::Cancelled,
        res = self.tx.reserve() => match res {
            Ok(p) => p,
            Err(_) => return ClientEventDelivery::Closed,
        },
    };
    permit.send(Ok(make(self.sequence.next()))); // ordinal issued only once capacity is held
    ClientEventDelivery::Sent
}
```

### WR-10: `WorkflowEventSink::wrap_event` panics via `unreachable!()` on a shared, cloneable sink

**File:** `engine/src/workflow/runner.rs:245-256`

**Issue:** `wrap_event` matches the event and calls `unreachable!("checkpoint helper must pass a
checkpoint event")` for any non-checkpoint variant. The invariant is enforced only by the single
current caller (`send_checkpoint`, line 186); nothing in the type system prevents a future caller
from passing another variant. `WorkflowEventSink` is `Clone` and is moved into the spawned workflow
task (`main.rs:1887-1892`), so a panic here aborts that task, drops `tx`, and terminates the client
stream with no terminal event and no diagnostic beyond a panic message. Per `rust-guidelines.md`
M-PANIC-IS-STOP, a panic means "stop the program" — a private formatting helper should not be able
to kill a request.

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

### WR-11 (NEW): Restored `d1_status` reflects an unvalidated, unbounded, client-supplied `session_id` into a gRPC trailer and thence an HTTP response header

**File:** `engine/src/main.rs:1159-1180`, `engine/src/main.rs:1775-1792`, `gateway/main.go:771-783`

**Issue:** `edaf907` restored trailer emission (correctly resolving prior WR-05), but the two
`invalid_session_id` call sites pass **`&raw_session_id`** — the client's rejected input, verbatim
and unbounded — as the `x-lancet-session-id` trailer value:

```rust
let raw_session_id = req.session_id.trim().to_string();   // main.rs:1775 — no length bound
let parsed = Uuid::parse_str(&raw_session_id).map_err(|_| {
    d1_status(tonic::Code::InvalidArgument, "session_id must be a valid UUIDv4 string",
              &raw_session_id, &correlation_id, "invalid_session_id")   // main.rs:1777-1783
})?;
```

There is **no length bound anywhere on this path**: the `query_max_bytes` ceiling applies only to
`query` (`main.rs:1808-1811`), and `session_id` is only ever `trim()`-ed. Three consequences, in
descending order of how directly the code proves them:

1. **Unbounded reflection into structured logs.** `d1_status` itself logs the raw value at `warn`
   on every rejected request (`main.rs:1168`):
   ```rust
   tracing::warn!(%session_id, %correlation_id, %error_kind, "QueryRAG pre-stream failure: {msg}");
   ```
   Arbitrary attacker-controlled content, one `warn` line per rejected request, with no rate limit
   and no length bound — log forging and log-volume amplification from an unauthenticated path.
2. **Unbounded reflection into an HTTP response header.** `gateway/main.go:773-775` promotes the
   trailer verbatim into `X-Lancet-Session-ID`, echoing the rejected input back to the caller.
3. **Inconsistent provenance.** On the success path the header comes from
   `firstFrame.GetSessionId()` (`main.go:714-716`), a server-validated UUID. On the error path it
   is raw attacker input. A consumer cannot tell which it got.

A multi-kilobyte `session_id` **may also** overflow the peer's HTTP/2
`SETTINGS_MAX_HEADER_LIST_SIZE` and convert a clean `InvalidArgument` into a connection-level
protocol failure — recorded as a plausible secondary effect, not verified against h2's behaviour
in this review.

*Verified not a finding:* header/CRLF injection is **not** possible here. `session_id.parse()`
(`main.rs:1170`) produces a `MetadataValue<Ascii>` and rejects any byte outside the printable-ASCII
header-value set, so a malformed value is silently skipped rather than injected. The residual risk
is size and provenance, not injection.

**Fix:** Bound and sanitize before reflecting *or* logging; echo a redacted marker rather than the
raw input.

```rust
const MAX_ECHOED_SESSION_ID: usize = 64; // UUIDv4 is 36 chars
let echoed = if raw_session_id.len() > MAX_ECHOED_SESSION_ID
    || !raw_session_id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-')
{
    "<rejected>"
} else {
    raw_session_id.as_str()
};
d1_status(tonic::Code::InvalidArgument, "session_id must be a valid UUIDv4 string",
          echoed, &correlation_id, "invalid_session_id")
```

Apply the same bound inside `d1_status` before the `tracing::warn!` so no caller can reintroduce
the log exposure.

### WR-12 (NEW): `send_envelope`'s `capacity() > 0` fast path is a check-then-act race that forfeits cancellation safety

**File:** `engine/src/workflow/runner.rs:90-98`, `engine/src/workflow/runner.rs:126-132`

**Issue:** Both `send_envelope` and `flush_pending_checkpoints` branch on `self.tx.capacity() > 0`
and, if true, call `self.tx.reserve().await` **outside** any `tokio::select!` with a
`cancel.cancelled()` arm:

```rust
if self.tx.capacity() > 0 {
    return match self.tx.reserve().await {          // no cancellation arm
        Ok(permit) => { permit.send(Ok(event)); ClientEventDelivery::Sent }
        Err(_) => ClientEventDelivery::Closed,
    };
}
```

`capacity()` is a snapshot. `WorkflowEventSink` is `Clone` (line 38-46) and is cloned into the
spawned task; nothing in the type prevents a second holder. If another sender consumes the last
permit between the `capacity()` read and the `reserve()`, this await blocks until a consumer drains
— with **no** cancellation escape. On a client that has stopped reading but not yet dropped the
stream, that parks the workflow task past its own cancellation.

This is also the mechanism that *bounds* CR-01: above zero capacity the cancellation arm is
skipped, which is why CR-01 only bites at `capacity() == 0`. The two behaviours are coupled and
should be fixed together.

**Fix:** Delete the fast path and always use the `biased` select — it costs nothing when capacity
is available, and removes the TOCTOU.

```rust
tokio::select! {
    biased;
    _ = cancel.cancelled() => ClientEventDelivery::Cancelled,
    result = self.tx.reserve() => match result {
        Ok(permit) => { permit.send(Ok(event)); ClientEventDelivery::Sent }
        Err(_) => ClientEventDelivery::Closed,
    },
}
```

(If the fast path exists deliberately so that already-cancelled workflows can still flush terminal
events, encode that intent explicitly with a `force: bool` parameter rather than inferring it from
a racy capacity reading — and then fix CR-01 by passing `force = true` on the failure paths.)

### WR-13 (NEW): Plan 05-25's remediation guidance is appended *after* two full schema dumps, where an operator will not see it

**File:** `engine/src/db/mod.rs:166-172`

**Issue:** The whole point of `967a897` was to make schema drift actionable. The guidance is placed
last:

```rust
return Err(format!(
    "LanceDB schema drift detected for {name}: expected {:?}, found {:?}. Remediation: schema \
     reconciliation is fail-closed by design; rename or remove the stale LanceDB store directory \
     and regenerate tables (e.g. via seed_rag_fixture or re-ingestion).",
    expected.fields(),
    actual.fields()
));
```

`expected.fields()` and `actual.fields()` are `Vec<FieldRef>` rendered with `{:?}` — for
`nodes_schema()` that is 19 `Field` structs, each with name, `DataType` (including the 2048-element
`FixedSizeList` descriptor), nullability and metadata map. The resulting string is multiple
kilobytes, and the one actionable sentence sits at the very end of it. This error propagates up
through `DatabaseManager::initialize` → engine startup, where it is logged as a single line. In
practice the operator sees a wall of `Field { name: ..., data_type: ... }` and the remediation
scrolls off.

`engine/src/db/tests.rs:107` asserts only `error.contains("Remediation: ...")`, which passes
regardless of position — so the test does not protect the property that actually matters.

**Fix:** Lead with the actionable sentence; put the diagnostic dumps last, and prefer a field-name
diff over a full `{:?}` of both schemas.

```rust
return Err(format!(
    "LanceDB schema drift detected for {name}. Remediation: schema reconciliation is fail-closed \
     by design; rename or remove the stale LanceDB store directory and regenerate tables \
     (e.g. via seed_rag_fixture or re-ingestion). Expected fields: {:?}; found fields: {:?}",
    expected.fields().iter().map(|f| f.name()).collect::<Vec<_>>(),
    actual.fields().iter().map(|f| f.name()).collect::<Vec<_>>(),
));
```

### WR-14 (NEW / re-derived from prior IN-14): `config/config.toml` commits a default Postgres credential with TLS disabled — and this file is in scope this pass

**File:** `config/config.toml:3`, `config/config.example.toml:7`, `gateway/main.go:1058`

**Issue:** The prior review recorded this as out-of-diff context. That premise is **false for this
refresh**: `config/config.toml` is in the declared file list and was changed by `989003b`.
Re-derived as an in-scope finding:

```toml
database_url = "postgres://postgres:postgres@localhost:5432/lancet?sslmode=disable"
```

This is the file `loadConfig()` (`gateway/main.go:983-1013`) reads by default, and the value is
handed straight to `pgxpool.New` at `main.go:1058` with no validation and no environment-source
requirement. Two properties make it worth flagging rather than waving through as a dev default:

- `sslmode=disable` is a *sticky* default. Anyone who repoints `database_url` at a non-localhost
  host by editing this line — the obvious action — carries plaintext transport with them.
- The credential-shaped literal in a tracked file trains operators to edit-in-place rather than
  override, and there is no fail-closed guard that rejects a default credential outside dev.

Viper's `AutomaticEnv` + `SetEnvKeyReplacer(".", "__")` (`main.go:69-71`) means
`LANCET_GATEWAY__DATABASE_URL` already works as an override for keys present in the config file —
so the mechanism to fix this exists and is simply not used.

`config/config.example.toml:1-3` correctly directs the OpenRouter credential to
`OPENROUTER_API_KEY` and is not part of this finding. **No API keys, tokens, or real secrets are
committed anywhere in the reviewed set.**

**Fix:** Blank the committed value and require the environment variable; fail closed if unset.

```toml
# Supplied via LANCET_GATEWAY__DATABASE_URL; never commit a real DSN.
database_url = ""
```

```go
if strings.TrimSpace(cfg.Gateway.DatabaseURL) == "" {
    return Config{}, errors.New("gateway.database_url must be set (LANCET_GATEWAY__DATABASE_URL)")
}
```

### WR-15 (NEW): `ReformulateQueryNode` enforces the 8-variant ceiling but not a non-empty floor, so an empty reformulator result silently degrades to zero evidence

**File:** `engine/src/workflow/nodes/reformulate.rs:43-66`

**Issue:** The validation is asymmetric. When a reformulator is configured, an over-limit result is
rejected with `InputValidation` (46-53), but an **empty** result is accepted verbatim:

```rust
if let Some(ref reformulator) = self.reformulator {
    let variants = reformulator.reformulate(&ctx.original_query, cancel).await?;
    if variants.len() > 8 { return Err(...); }
    ctx.variants = variants;                 // no is_empty() guard
} else if ctx.variants.is_empty() {
    ctx.variants.push(ctx.original_query.clone());   // fallback exists only on this branch
}
```

The `else` branch has an original-query fallback; the reformulator branch does not. With
`ctx.variants == []`, `RetrieveHybridNode::execute` re-inserts the original query at
`retrieve.rs:60-62` — so the *retrieval* recovers — but `ctx.snapshot.variant_count` is then `1`
while the reformulator actually produced `0`, and `ExtractGraphContextNode` (`graph_context.rs:64-68`)
applies its own independent re-insertion. Three separate places silently repair the same invariant,
each with different provenance consequences, and none of them records a notice.

Latent today (`NoOpQueryReformulator` always returns one element, `ports.rs:23`), but this is
exactly the code that activates when a real reformulator lands — the same activation event as
IN-02/IN-06.

**Fix:** Enforce the floor where the ceiling is enforced, and record the repair.

```rust
let variants = reformulator.reformulate(&ctx.original_query, cancel).await?;
if variants.is_empty() {
    return Err(NodeError::new(
        NodeErrorKind::InputValidation,
        "Query reformulator produced 0 variants; at least the original query is required",
    ));
}
if variants.len() > 8 { /* existing check */ }
ctx.variants = variants;
```

---

## Info

### IN-01: Widened `pub(crate)` → `pub` visibility is a consequence of the crate split, not test hygiene

**File:** `engine/src/main.rs:33-38`, `engine/src/lib.rs:3-11`, `engine/src/retrieval/bm25.rs:171`, `engine/src/retrieval/dense.rs:37`, `engine/src/retrieval/dense.rs:42`, `engine/src/retrieval/dense.rs:162`, `engine/src/retrieval/mod.rs:62`

**Issue:** `main.rs` uses `use engine::{generation, graph, prompt, rerank, retrieval}`. The binary
is a **separate crate** from the `engine` library, so every item it touches had to leave
`pub(crate)`. That is the correct mechanical consequence — but it permanently enlarges the
library's public API: `Bm25Index::from_table`, `DenseRetriever::new`, `DenseRetriever::query`,
`dense::dense_score`, and `RetrievalError::new` are now callable by any downstream consumer
without the surrounding validation that made them safe. This contradicts `rust-guidelines.md`
M-SINGLE-ITEM-PATH's intent of a deliberate, minimal public surface.

*Scope note:* the prior review's most security-relevant citation for this finding
(`graph::escape_sql_literal`, `engine/src/graph/mod.rs`) is **out of scope for this refresh** —
`engine/src/graph/*` is absent from the declared file list. It is not re-asserted here; only the
in-scope `retrieval::*` widenings are.

**Fix:** Introduce a `#[doc(hidden)] pub mod internal` re-export module, or gate these behind a
`binary-internals` Cargo feature, so the intended public surface stays small.

### IN-02: Production always takes the single-variant fusion path — cross-variant RRF is unexercised

**File:** `engine/src/main.rs:1586-1587`, `engine/src/workflow/ports.rs:23`, `engine/src/retrieval/fusion.rs:236-244`

**Issue:** `build_production_workflow` wires `NoOpQueryReformulator`, whose `reformulate` returns
`vec![query.to_string()]`. So `ctx.variants.len() == 1` always, `per_variant_fused` has exactly one
entry, and `fuse_cross_variant_candidates` hits the `len() == 1` early return at line 236. In
production the entire two-pass cross-variant RRF (plan 05-24), the 8-variant caps
(`reformulate.rs:46-53`, `fusion.rs:230-235`), and `RetrievalSnapshot.variant_count > 1` /
multi-element `variant_identities` are never reached. Recorded so the capability is not assumed
production-proven by this phase.

**Fix:** Document the intended activation path (a real reformulator) at
`build_production_workflow`, or mark plan 05-24's cross-variant behavior as production-unreached in
the phase verification record.

### IN-03: Single-variant fusion path skips the `candidate_limit` truncation the multi-variant path applies

**File:** `engine/src/retrieval/fusion.rs:236-244`, `engine/src/retrieval/fusion.rs:249-253`

**Issue:** The multi-variant path truncates each variant list with `.take(settings.candidate_limit)`
(line 252); the `len() == 1` early return (236-244) returns the list untouched. Because
`fuse_candidates` unions two sources each capped at `candidate_limit`, the single-variant result
can contain up to `2 * candidate_limit` entries where the multi-variant path caps at
`candidate_limit`. Only the downstream `final_limit` take (`retrieve.rs:165-168`) masks the
difference — and it changes which candidates reach the reranker.

**Fix:** Apply the same truncation on the single-variant branch:
`single_list.truncate(settings.candidate_limit);`

### IN-04: `WorkflowRunner::timeout_for_node` is dead code with a magic fallback

**File:** `engine/src/workflow/runner.rs:319-328`, `engine/src/workflow/runner.rs:241-243`

**Issue:** `timeout_for_node(&str)` has no production caller — all dispatch goes through the
exhaustive typed `timeout_for_kind(NodeKind)` at 309-317 (the only call site is
`run_node`, line 359). It duplicates that mapping via string matching and adds an
unreachable-in-practice `_ => Duration::from_millis(5000)` magic fallback: exactly the
stringly-typed dispatch the phase's `NodeKind` work set out to eliminate, and a
silent-wrong-timeout hazard if a node name is ever misspelled. `pending_checkpoint_count`
(241-243) is likewise test-only.

**Fix:** Delete `timeout_for_node`; gate `pending_checkpoint_count` behind `#[cfg(test)]`.

### IN-05: `buf.gen.yaml` `clean: false` is forced by a hand-written file inside the generated tree

**File:** `buf.gen.yaml:2`, `engine/src/pb/mod.rs:1-5`

**Issue:** The prost/tonic plugins write to `out: engine/src/pb`, and `engine/src/pb/mod.rs` is
**hand-written** — a 5-line `include!("lancet/v1/lancet.v1.rs")` wrapper. `clean: true` would
delete it on every regeneration, so the flip was necessary rather than careless. The cost is that
stale generated artifacts now survive: a removed or renamed proto message leaves a compilable,
importable orphan behind, and the generated tree can silently diverge from `proto/`. This phase
already required a hand-repair of generated Rust literals (commit `253d612`) — the symptom this
setting makes permanent.

**Fix:** Move the hand-written wrapper out of the generated tree (e.g. `engine/src/pb.rs`
declaring `#[path = "pb/lancet/v1/lancet.v1.rs"]`) and restore `clean: true`; otherwise add a CI
check that `git status` is clean after regeneration.

### IN-06: `ctx.bm25_results` accumulates duplicate chunk IDs across variants

**File:** `engine/src/workflow/nodes/retrieve.rs:115-117`

**Issue:** The per-variant loop pushes every BM25 candidate's `chunk_id` into `ctx.bm25_results`
with no deduplication, while `ctx.vector_results` (84-87) is assigned once from a deduplicated
dense list. With N variants, a chunk matched by every variant appears N times. `ctx.bm25_results`
is serialized verbatim into every checkpoint snapshot (`events.rs:188-189`), so the persisted
provenance record would misreport BM25 recall and grow super-linearly.

Currently latent: per IN-02, production runs exactly one variant, so the loop body executes once.
This activates the moment a real reformulator lands.

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

### IN-07: `uint64` → `int32` narrowing on `sequence_ordinal`

**File:** `gateway/checkpoint_sink.go:109`, `gateway/db/schema.sql:48`, `gateway/db/models.go:45`, `proto/lancet/v1/lancet.proto:182`, `proto/lancet/v1/lancet.proto:198`

**Issue:** `SequenceOrdinal: int32(env.SequenceOrdinal)` narrows a protobuf `uint64` (verified:
`uint64 sequence_ordinal` at `lancet.proto:182` and `:198`) to the schema's `integer` column with
no bounds check; values ≥ 2^31 wrap to negative. Not realistically
reachable (2^31 events in one workflow), but it is an unchecked lossy conversion on a persisted
ordering key.

**Fix:** Widen the column to `bigint` and the sqlc model to `int64`, or reject out-of-range values
explicitly before insert.

### IN-08: `notices` must be read from two different places depending on success

**File:** `gateway/main.go:853-868`

**Issue:** On success the gateway writes `final_response` (whose DTO already carries `notices`,
sourced from `WorkflowContext::to_query_rag_response` at `workflow/mod.rs:102`); on failure it
writes a top-level `wcPayload["notices"]`. Content is equivalent — this is not a loss — but a
client must check two locations depending on the `success` flag.

**Fix:** Always emit top-level `notices` on `workflow_completed`, in addition to `final_response`.

### IN-09: Seven redundant cancellation checks inside one prompt-packing loop

**File:** `engine/src/prompt.rs:446`, `:456`, `:484`, `:504-505`, `:510`, `:524`

**Issue:** `pack_evidence_and_graph_prompt` checks `cancel.is_cancelled()` at the top of the loop
(446), again inside each match arm (456, 484), again after `yield_now()` (505), and twice more
after the loop (510, 524). Between the arm checks and the post-yield check there is no `await`, so
those cannot observe a state change. The redundancy obscures where cancellation is actually
meaningful — the `yield_now().await` at 504 is the only true suspension point in the loop.

**Fix:** Keep the entry check (329), the post-`yield_now()` check (505), and one pre-return check;
delete 456, 484, and 510.

### IN-10: `let _ = &deps;` keep-alive hack in the spawned workflow task

**File:** `engine/src/main.rs:1889`, `engine/src/main.rs:1878`

**Issue:** `build_production_workflow` returns `(runner, deps)`, but `deps` has no production
consumer — the nodes already own their `Arc` clones (`main.rs:1608-1644`). The spawned task
contains `let _ = &deps;` purely to move the value into the closure and suppress an
unused-variable warning. A reader cannot tell whether that lifetime is load-bearing. Directly
coupled to WR-05: `WorkflowDependencies` exists only for the dead inline remainder.

**Fix:** Have `build_production_workflow` return only the runner (add a `#[cfg(test)]`-gated
variant returning `deps` for the tracer tests), and drop the `let _ = &deps;` line.

### IN-11: Model-capability cache never expires, and `ModelCapabilities` is written but never read

**File:** `engine/src/generation/openrouter.rs:234`, `engine/src/generation/openrouter.rs:339-353`

**Issue:** `capabilities_cache: HashMap<CapabilityKey, Arc<OnceCell<ModelCapabilities>>>` caches a
successful preflight for the entire process lifetime. If OpenRouter later withdraws
`response_format` / `structured_outputs` support for the configured model — a real risk given
`config/config.toml` now pins a `:free` *preview* model — the process keeps sending strict-schema
requests until restart. The success-only semantics are correct (errors leave the `OnceCell`
uninitialized, so they are retried); the missing TTL is the gap. Separately,
`ModelCapabilities.supports_structured_outputs` is constructed but never read (`let _caps = ...`
at line 348); the cell's mere existence carries the whole signal, making the struct field dead
weight.

**Fix:** Store `(ModelCapabilities, Instant)` and re-validate after a configurable TTL, or read
`supports_structured_outputs` at the call site so the field earns its place.

### IN-12: `workflow_checkpoints` has no uniqueness constraint on `(trace_id, sequence_ordinal)`

**File:** `gateway/db/schema.sql:45-57`, `gateway/db/schema.hcl:166-169`, `gateway/db/query.sql:116-133`

**Issue:** The table's primary key is a client-generated `uuid.NewString()`
(`checkpoint_sink.go:88`) in a `varchar(255)` column, and the
`(trace_id, sequence_ordinal, created_at)` index is explicitly `unique = false`
(`schema.hcl:167`). Any duplicate delivery or replay of the same checkpoint inserts a second row
indistinguishable from a legitimate one; nothing enforces at-most-once per ordinal, and the insert
is a plain `INSERT ... RETURNING *` with no conflict handling. This becomes load-bearing if WR-06's
recommended retry is ever added.

**Fix:** Make the index unique on `(trace_id, sequence_ordinal)` and change the statement to
`INSERT ... ON CONFLICT (trace_id, sequence_ordinal) DO NOTHING` so retried deliveries are
idempotent. Consider a native `uuid` column type for `id`.

### IN-13: `seed_rag_fixture` defines a local `f32` copy of `dense_score` and then asserts against its own copy

**File:** `engine/src/bin/seed_rag_fixture.rs:85-87`, `engine/src/retrieval/dense.rs:162-164`

**Issue:** The fixture binary defines `fn dense_score(distance: f32) -> f32 { 1.0 / (1.0 + distance) }`,
a near-duplicate of the production `retrieval::dense::dense_score(f64)` — which the phase made
`pub` (IN-01), so it is now directly importable. The local copy omits the production version's
`distance.max(0.0)` clamp, so a negative distance produces a different result. The two assertions
at the end of the fixture exercise the local copy, not the production function, so they prove
nothing about retrieval scoring (`rust-guidelines.md` M-TAUTOLOGICAL-TESTS). No production code
path is affected.

**Fix:** Delete the local helper and call `engine::retrieval::dense::dense_score` so the assertion
guards the production formula, or drop the two tautological assertions.

### IN-14 (NEW): Plan 05-26's new env overrides assign the raw, untrimmed value

**File:** `engine/src/main.rs:661-670`

**Issue:** The two overrides added by `c815af1` guard on the *trimmed* value but assign the
*untrimmed* one:

```rust
if let Ok(value) = std::env::var("LANCET_OPENROUTER__GENERATION_MODEL") {
    if !value.trim().is_empty() {
        settings.openrouter.generation_model = value;   // untrimmed
    }
}
```

`" openai/gpt-4o-mini "` passes the guard, passes `EffectiveRagSettings::validate()` (which also
only checks `trim().is_empty()`, `main.rs:540`), and lands verbatim in the outbound `model` field
and in the `/models` lookup key at `openrouter.rs:411`, where `m.id == self.config.model` fails
with a confusing "model metadata for ' openai/gpt-4o-mini ' not found" error. Consistent with the
five sibling string overrides at `main.rs:646-660`, so this is a pre-existing pattern the new code
inherited — but it is new code, so it is recorded here.

Related, and also pre-existing: the numeric overrides (`main.rs:611-645`) use
`if let Ok(val) = value.trim().parse::<u64>()`, so a typo like
`LANCET_ENGINE__WORKFLOW__GENERATION_NODE_TIMEOUT_MS=65s` is **silently ignored** and the config
value is used instead. A deployment-time misconfiguration produces no diagnostic at all.

**Fix:** Trim on assignment, and fail closed on unparseable numerics.

```rust
if let Ok(value) = std::env::var("LANCET_OPENROUTER__GENERATION_MODEL") {
    let trimmed = value.trim();
    if !trimmed.is_empty() {
        settings.openrouter.generation_model = trimmed.to_string();
    }
}
```

### IN-15 (NEW): Plan 05-25's test asserts on remediation *prose*, and leaks a temp directory on failure

**File:** `engine/src/db/tests.rs:106-108`, `engine/src/db/tests.rs:23-32`

**Issue:** Two test-reliability nits in `schema_drift_fails_database_initialization`:

1. Line 107 asserts `error.contains("Remediation: schema reconciliation is fail-closed by design")`
   — a 55-character substring of a human-facing prose sentence in `db/mod.rs:168`. Any wording
   improvement (including the one WR-13 recommends) breaks this test without any behavioural
   change. More importantly it verifies only *presence*, not the property that matters
   (operator-visible *placement*), so it does not actually protect the deliverable of plan 05-25.
2. `let _ = std::fs::remove_dir_all(path);` at line 108 is the last statement, not RAII. When
   either assertion fails, the `assert!` panics before cleanup and a LanceDB store is orphaned in
   `std::env::temp_dir()`. The same pattern appears at lines 56, 141, and 200.

**Fix:** Assert on a stable prefix/marker rather than prose, and make cleanup unconditional.

```rust
// db/mod.rs — stable, greppable marker independent of wording
const DRIFT_REMEDIATION_CODE: &str = "LANCEDB_SCHEMA_DRIFT";
// db/tests.rs
assert!(error.contains("LANCEDB_SCHEMA_DRIFT"));
```

Use a drop-guard (or `tempfile::TempDir`) so the store is removed even on panic.

### IN-16 (NEW): `.gitignore` now blanket-ignores `data/`, leaving two dead entries below it

**File:** `.gitignore:59-61`

**Issue:** `967a897` added `data/` immediately above the pre-existing, now-unreachable
`data/lancedb-verify-02-06/` and `data/.phase02-lancedb-preclean-*/` entries. Verified:
`git check-ignore -v data/lancedb` reports `.gitignore:59:data/`, and `git ls-files data/` is
empty, so nothing tracked was newly ignored — this does not break anything today.

The residual cost is that any file intentionally committed under `data/` in future (a small
regression fixture, a README explaining the layout) will be silently invisible to `git add`
without `-f`, and the two stale lines below now misdescribe the actual rule.

**Fix:** Delete lines 60-61 as redundant, and add a negation for anything meant to be tracked:

```gitignore
data/
!data/README.md
```

### IN-17 (NEW): `CheckpointEnvelope` carries four fields that are never persisted, and `NodeID` is always equal to `CheckpointType`

**File:** `gateway/checkpoint_sink.go:18-51`, `gateway/checkpoint_sink.go:90-96`, `gateway/db/models.go:39-46`

**Issue:** `NewCheckpointEnvelopeFromEvent` populates `SessionID`, `CorrelationID`,
`EventSequence`, and `TimestampMs`, but `SaveCheckpoint` writes only
`ID / TraceID / SequenceOrdinal / NodeName / ContextSnapshot / CreatedAt`. Grepped across all
non-test Go: those four fields have no reader anywhere. Two consequences:

- The `workflow_checkpoints` table has **no `session_id` column at all**, so persisted checkpoints
  cannot be queried by session — only by `trace_id`. Whether that is intended is not recorded
  anywhere.
- `NodeID` and `CheckpointType` are both assigned `cp.GetCheckpointType()` (lines 44-45), so the
  three-step fallback chain in `SaveCheckpoint` (90-96) can only ever collapse to
  `nodeName = env.CheckpointType`, and its second branch is dead.

`CorrelationID: ev.GetTraceId()` (line 41) also silently equates two distinct concepts that the
engine keeps separate.

**Fix:** Either persist the fields (add `session_id`, `event_sequence`, `timestamp_ms` columns) or
delete them from the envelope so the struct describes what is actually stored. Collapse the dead
fallback branch in `SaveCheckpoint`.

### IN-18 (NEW): `rrf_k` is truncated from `f64` to `i32` in the persisted retrieval snapshot

**File:** `engine/src/workflow/nodes/retrieve.rs:183`, `proto/lancet/v1/lancet.proto:94-97`

**Issue:** `rrf_k: self.settings.rrf_k as i32` narrows the `f64` fusion constant to the proto's
`int32` field. `rrf_k` is validated as a finite `1.0..=1_000_000.0` float and is used as an `f64`
in the actual RRF denominator (`fusion.rs:252-254`). A configured `60.5` is persisted and reported
as `60`.

The whole purpose of `RetrievalSnapshot` is reproducible provenance — misreporting the fusion
constant is precisely the class of drift it exists to prevent. Harmless with the current committed
value (`config/config.toml:29` = `60.0`), which is why this is Info rather than a Warning.
Verified in the proto: `double vector_weight = 3;` (line 94) and `double bm25_weight = 4;`
(line 95) sit directly above `int32 rrf_k = 5;` (line 96) in the same message — so the narrowing
is an inconsistency within a three-line span, not a considered wire-format decision.

**Fix:** Change `RetrievalSnapshot.rrf_k` to `double` in `proto/lancet/v1/lancet.proto` (matching
`vector_weight` / `bm25_weight`), regenerate, and drop the cast. If the wire type must stay
`int32`, reject non-integral `rrf_k` at config validation so the snapshot cannot lie.

---

_Reviewed: 2026-08-19T02:02:00Z (refresh at HEAD `e6e153f`)_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
