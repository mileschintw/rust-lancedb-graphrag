---
phase: 05-state-machine-workflow-events
reviewed: 2026-08-19T05:40:00Z
head: bb58a60
depth: standard
files_reviewed: 33
files_reviewed_list:
  - .gitignore
  - buf.gen.yaml
  - buf.yaml
  - config/config.example.toml
  - config/config.toml
  - config/config.verify.toml
  - engine/src/bin/seed_rag_fixture.rs
  - engine/src/client/mod.rs
  - engine/src/db/mod.rs
  - engine/src/generation/mod.rs
  - engine/src/generation/openrouter.rs
  - engine/src/graph/mod.rs
  - engine/src/lib.rs
  - engine/src/main.rs
  - engine/src/pb/mod.rs
  - engine/src/prompt.rs
  - engine/src/retrieval/fusion.rs
  - engine/src/workflow/events.rs
  - engine/src/workflow/mod.rs
  - engine/src/workflow/node.rs
  - engine/src/workflow/nodes/assemble_prompt.rs
  - engine/src/workflow/nodes/generate.rs
  - engine/src/workflow/nodes/graph_context.rs
  - engine/src/workflow/nodes/mod.rs
  - engine/src/workflow/nodes/reformulate.rs
  - engine/src/workflow/nodes/retrieve.rs
  - engine/src/workflow/runner.rs
  - gateway/checkpoint_sink.go
  - gateway/db/query.sql
  - gateway/db/schema.hcl
  - gateway/db/schema.sql
  - gateway/main.go
  - proto/lancet/v1/lancet.proto
findings:
  critical: 0
  warning: 13
  info: 24
  total: 37
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-08-19T05:40:00Z
**HEAD:** `bb58a60`
**Depth:** standard
**Files Reviewed:** 33 (of 49 declared — see Scope narrowing)
**Status:** issues_found

## Summary

This is a **full re-derivation** at HEAD `bb58a60`, not a carry-forward. The prior report was
written at HEAD `e6e153f` and reported 1 Critical / 15 Warnings / 18 Info; 16 remediation commits
have landed since (`ac3db6e` … `ccef730`), and `05-REVIEW-FIX.md` claims all 16 are closed. Every
finding below was re-derived from the working tree and is renumbered from scratch. Findings
introduced **by** the remediation commits are called out explicitly.

**`critical: 0` is a real result, not an oversight.** Prior CR-01 (`run_node` cancelling the
workflow before emitting `NodeFailed`) is genuinely closed — verified at `runner.rs:342-351` and
`runner.rs:383-393`, where `NodeFailed` is now emitted first, the real `NodeError` is preserved
rather than replaced via `?`, and `cancel.cancel()` on the timeout branch moved after the emit. No
finding at HEAD rises to Critical. See the fix-verification table in §2. Nothing below has been
inflated to compensate.

**Of the 16 claimed fixes: 9 CLOSED, 4 PARTIALLY CLOSED, 1 NOT CLOSED, 2 REGRESSED.** The two
regressions are the highest-value items in this report: `5354d1e` deleted one un-cancellable
`reserve().await` and introduced another (WR-01), and `e8982d0` turned a non-zero-exit bind failure
into a silent exit 0 (WR-04). The one NOT CLOSED (prior WR-14) was closed against a **restated**
finding, not the one that was written.

### Scope narrowing (recorded verbatim, on the record)

> The raw `git diff --name-only 8d4db491bba31484f44dd6919b9c038e7e996a1a^..HEAD` surfaced
> **2,051 changed paths**, of which **2,002 are vendored GSD runtime installs** under `.codex/`,
> `.claude/` and `.agents/`. Those are tooling, not Phase 05 project source, and were excluded by
> the orchestrator before this agent was spawned. The declared in-scope set handed to this review
> is **49 files**. 33 were reviewed line-by-line and appear in `files_reviewed_list`. The
> remaining 16 were NOT reviewed line-by-line, for the reasons below.
>
> **Generated code — 5 files (machine output; the hand-written contracts they are generated from,
> `proto/lancet/v1/lancet.proto` and `gateway/db/query.sql`, WERE reviewed):**
>   - `engine/src/pb/lancet/v1/lancet.v1.rs`
>   - `gateway/proto/lancet/v1/lancet.pb.go`
>   - `gateway/proto/lancet/v1/lancet_grpc.pb.go`
>   - `gateway/db/query.sql.go`
>   - `gateway/db/models.go` (sqlc-generated; the persisted column set was instead verified from
>     `gateway/db/schema.sql:45-56` and `gateway/db/schema.hcl:136-170`, both reviewed)
>
> **Test files — 8 files.** Excluded by *role*, not by size: claim-vs-actual test adequacy is the
> phase verifier's job, not code review's. This exclusion applies equally to the 1 KB and the
> 7,000-line files.
>   - `engine/src/client/tests.rs`
>   - `engine/src/db/tests.rs` *(exception — see below)*
>   - `engine/src/generation/tests.rs`
>   - `engine/src/retrieval/tests.rs`
>   - `engine/src/tests.rs` *(exception — see below)*
>   - `engine/src/tests/workflow_phase5.rs` *(exception — see below)*
>   - `engine/src/tests/workflow_phase5_production.rs`
>   - `gateway/main_test.go`
>
>   **Three deliberate exceptions, read to verify specific fix claims** (these regions were read;
>   the files remain out of `files_reviewed_list` so a downstream `--auto` re-review does not pull
>   7,400- and 3,900-line test files into full scope):
>   - `engine/src/db/tests.rs:90-110` — the WR-13 drift assertion. Read; yielded WR-13 and IN-15.
>   - `engine/src/tests.rs:315-360` — the hunk `7da662a` touched for WR-03. Read; yielded IN-23.
>   - `engine/src/tests/workflow_phase5.rs:1740-1786` — the `zero_variants_are_rejected_before_retrieval`
>     test added by `ccef730` for WR-15. Read in full; it is a genuine regression test.
>
> **Reviewed only in targeted regions, not end to end — 3 files.** These are in
> `files_reviewed_list` because findings were derived from them, but coverage is partial and is
> disclosed here rather than implied complete:
>   - `engine/src/prompt.rs` (603 lines) — cancellation-check sites and `EmptyEvidence` path only.
>     Unchanged since `e6e153f`.
>   - `engine/src/graph/mod.rs` (669 lines) — SQL-predicate construction and `escape_sql_literal`
>     only. Unchanged since `e6e153f`.
>   - `engine/src/bin/seed_rag_fixture.rs` (396 lines) — the local `dense_score`/`content_hash`
>     helpers only. Unchanged since `e6e153f`.
>
> **Not opened at all — 3 files**, all unchanged since `e6e153f` and covered by the prior pass:
>   - `engine/src/graph/extraction.rs`
>   - `engine/src/retrieval/mod.rs`
>   - `engine/src/workflow/ports.rs`
>   (`ports.rs` behaviour relevant to WR-15 — `NoOpQueryReformulator` returning exactly one
>   variant — was confirmed indirectly from `reformulate.rs` and the prior report, not re-read.)
>
> Arithmetic: 49 declared − 5 generated − 8 test − 3 unopened = 33 reviewed.
>
> **Diff-scoped focus.** Only 14 non-planning source files changed between the prior review HEAD
> `e6e153f` and `bb58a60`: `engine/src/{client/mod.rs, client/tests.rs, db/mod.rs, generation/mod.rs,
> generation/openrouter.rs, main.rs, tests.rs, tests/workflow_phase5.rs, workflow/mod.rs,
> workflow/nodes/reformulate.rs, workflow/runner.rs}` and `gateway/{checkpoint_sink.go, main.go}`.
> Those 13 non-test files received the deepest scrutiny; the unchanged remainder was re-derived at
> the level needed to confirm prior findings still hold.

### Assessment

**Event delivery path (`runner.rs`) reviewed as a whole**, per instruction, rather than fix-by-fix.
Four remediations landed in this one file (`ac3db6e`, `7ea20f2`, `5354d1e`, plus WR-02's change).
Reading the resulting path end to end:

- The **`biased` cancellation arm is now universal** in `send_envelope` (86-101) and
  `flush_pending_checkpoints` (107-128). The `capacity() > 0` TOCTOU is gone. Confirmed.
- The **terminal event is now cancellation-immune** via `send_terminal_event` (161-170), which is
  what actually closes prior CR-01's tail (`WorkflowCompleted` no longer suppressed by a
  pre-cancelled token). But that function acquires its permit with a bare `self.tx.reserve().await`
  — **no cancellation arm and no timeout** (WR-01). The commit deleted one unbounded reserve and
  added another.
- **Ordinal gaps were not addressed at all.** `wrap_next_event` (71-79) still calls
  `sequence.next()` before `send_envelope` is attempted, and `send_checkpoint` (179) still
  allocates before `try_send`. `5354d1e`'s message names only WR-10 and WR-12; WR-09 was never in
  it (WR-03 below). Note that `send_terminal_event:168` allocates the ordinal *lazily*, inside
  `if let Ok(permit)` — so both idioms now sit in the same file and the correct one was applied in
  exactly one place.
- **One terminal-drop path survives.** `emit_terminal_once:499-505` still `return`s before
  `WorkflowCompleted` if `FinalAnswer` delivery fails, with `terminal_emitted` already latched
  (488-494). WR-02's fix removed the *checkpoint* early-return but not the *final_answer* one
  (WR-02 below).
- **No double-emission and no deadlock-on-closed-channel found.** `terminal_emitted` is a
  `compare_exchange` latch; `send_terminal_event` short-circuits on `tx.is_closed()`; a dropped
  receiver makes `reserve()` return `Err`, so a *closed* channel is safe. The exposure is a
  receiver that is alive but not draining.

**Rust→Go SSE transport.** Cancellation still propagates (`CancelOnDropStream::drop` at
`main.rs:1878-1882`). The checkpoint dispatcher's drain ordering is re-verified sound:
`nextEnvelope` drains `primary` → `overflow` → `pending` before parking at `checkpoint_sink.go:278`,
and `Submit`/`Close` both mutate under `d.mu`, so there is **no send-on-closed-channel race**. What
changed is that `Close()` is now *reachable* (WR-09 below).

**Secrets scan.** No API keys or tokens are committed. `config/config.example.toml:1-3` correctly
routes the OpenRouter credential to `OPENROUTER_API_KEY`. Both `config/config.toml:3` and
`config/config.example.toml:7` still carry a default Postgres DSN with `sslmode=disable` (WR-05).

**SQL construction.** Checkpoint persistence still goes through sqlc-generated parameterized
statements (`gateway/db/query.sql:116-133`) — **no injection**. The LanceDB/DataFusion predicate
paths use two identical hand-rolled quote-doubling escapers; every input was traced to a
UUID-validated or DB-sourced value, so **no exploitable path was found** (WR-11 is filed for
duplication and hazard, not as an injection finding).

---

## §2 Fix Verification (prior findings CR-01, WR-01 … WR-15)

**ID-space warning:** the IDs in this table are the **prior report's** IDs. The narrative findings
in §3/§4/§5 are renumbered from scratch and do **not** correspond. Prior IDs are prefixed `prior`.

| Prior ID | Commit | Verdict | Evidence actually read |
|---|---|---|---|
| **prior CR-01** — cancel before `NodeFailed` | `ac3db6e` | **CLOSED** | `runner.rs:342-351`: `send_event_or_cancel(node_failed…)` with `let _ =` runs *before* `cancel.cancel()`; `return Err(err)` preserves the real error. `runner.rs:383-393`: same shape; `cancel.cancel()` moved after the emit and gated to `NodeErrorKind::Timeout`. The `?`-masking is gone from both branches. |
| **prior WR-01** — `dispatcher.Close()` unreachable | `e8982d0` | **CLOSED** *(with a regression — see new WR-04)* | `main.go:1092-1110`: `signal.NotifyContext` + goroutine `ListenAndServe` + `<-sigCtx.Done()` + `server.Shutdown(15s)`; `main` now returns normally so defers run. Defer LIFO order verified at `main.go:1058/1067/1072/1075/1081/1093/1107` → `cancelShut, stop, dispatcher.Close, recCancel, conn.Close, pool.Close, logger.Sync`, i.e. the dispatcher drains while the pgx pool is still live. Correct. |
| **prior WR-02** — terminal checkpoint suppresses `WorkflowCompleted` | `7ea20f2` | **PARTIALLY CLOSED** | `runner.rs:506-508`: the checkpoint early-return is replaced by `tracing::warn!` and falls through. But `runner.rs:499-505` still `return`s before `WorkflowCompleted` when `send_event_or_cancel(final_answer)` fails, with `terminal_emitted` latched at 488-494. The class of defect (an upstream delivery failure suppressing the protocol terminal event) survives one step earlier. Re-filed as new **WR-02**. |
| **prior WR-03** — cross-field timeout invariants unvalidated | `7da662a` | **PARTIALLY CLOSED** | `main.rs:280-289` adds **only** the graph invariant (`graph_node_timeout_ms >= query_embedding + graph_operation`). The *primary* complaint — `generation_node_timeout_ms >= 2 × generation_timeout_secs × 1000`, the invariant the 2-attempt retry at `generate.rs:105`/`generate.rs:127` depends on — is **not** implemented. `config/config.verify.toml:19` still commits `generation_node_timeout_ms = 7000` against `generation_timeout_secs = 30` (line 9), the exact violating config the original finding cited. Re-filed as new **WR-06**. |
| **prior WR-04** — every non-2xx chat status retryable | `58cede3` | **CLOSED** | `openrouter.rs:602-612`: 5xx and `TOO_MANY_REQUESTS` → `ProviderError`; all other non-success → `InvalidRequest`. `generate.rs:116-120` retries only `Timeout`/`ProviderError`, so 400/401/402/403 now fail fast. |
| **prior WR-05** — `run_inline_prompt_generation_remainder` broken by construction | `0969a2b` | **PARTIALLY CLOSED** | `workflow/mod.rs:200-207` now passes `ctx.evidence_blocks`, sets `graph_facts`, and sets `gen_req.cancel`; `mod.rs:211-217` gates the retry to `Timeout`/`ProviderError`. So it can now succeed. But: (a) it is still `pub` with no production consumer — the finding's actual recommendation (`#[cfg(test)]` or delete) was not applied; (b) `graph_weight` is never set, diverging from `generate.rs:97`; (c) `mod.rs:240` and `mod.rs:259` still do `send_event_or_cancel(node_failed…).await?`, whose `?` replaces `node_err` with `Cancelled` — **the prior CR-01 defect verbatim, in a function `ac3db6e` did not touch**; (d) hardcoded `duration_ms` of `1` (`mod.rs:190`) and `10` (`mod.rs:224`) remain. Re-filed as new **WR-07**. |
| **prior WR-06** — checkpoint errors swallowed; `context_snapshot` unvalidated | `8b692a5` | **PARTIALLY CLOSED** | `checkpoint_sink.go:105-111`: `json.Valid` guard added — that half is **closed**. `checkpoint_sink.go:229-239`: the error is now logged, but only inside `if ps, ok := d.sink.(*PostgresCheckpointSink); ok && ps.logger != nil` — any other `CheckpointSink` implementation still discards silently. There is still **no retry and no dead-letter**, which was the substance of the finding. Re-filed as new **WR-08**. |
| **prior WR-07** — `RetainPending` accepts after `Close()` | `71fad09` | **CLOSED** | `checkpoint_sink.go:212-214`: `if d.closed { return errors.New("checkpoint dispatcher is closed") }` under `d.mu`. Caller at `main.go:807-809` logs the error via `a.logger.Error`. |
| **prior WR-08** — `PartialEq` misuses `f64::EPSILON` | `2a7c541` | **CLOSED** | `generation/mod.rs:394-413`: full `let Self { … cancel: _ } = self;` destructure (new fields will fail to compile) and `graph_weight.to_bits() == other.graph_weight.to_bits()`. |
| **prior WR-09** — ordinals consumed on failed delivery | `5354d1e` | **NOT CLOSED** | The `5354d1e` diff touches `runner.rs` only at the `capacity()` fast paths, `wrap_event`→`wrap_checkpoint_event`, `send_terminal_event`, and `emit_terminal_once`. `wrap_next_event` is unchanged: `runner.rs:71-79` calls `self.sequence.next()` and `runner.rs:141` then passes the built envelope to `send_envelope`, which can return `Cancelled`/`Closed`. `send_checkpoint:179` still allocates before `try_send`. The commit message itself names only WR-10 and WR-12. Re-filed as new **WR-03**. |
| **prior WR-10** — `unreachable!()` in `wrap_event` | `5354d1e` | **CLOSED** | `runner.rs:239-243`: the panic is replaced by `_ => self.sequence.next()`. The panic hazard is gone. The recommended *structural* fix (accept a `CheckpointEvent`, not an `Event`) was not applied, leaving a dead arm that silently burns an ordinal — filed as new **IN-19**, not as a reopen. |
| **prior WR-11** — unbounded `session_id` reflected into trailer + logs | `94275b6` | **CLOSED** | `main.rs:1164-1169`: `sanitize_header_value` filters to `is_ascii_graphic()` then `.take(max_len)`. `main.rs:1182-1185`: applied to `session_id` (128), `correlation_id` (128) and `error_kind` (64) **before** the `tracing::warn!` at 1186-1191 and before `metadata.insert` at 1194-1202. Both unbounded-reflection paths (log at `main.rs:1186`, header via `gateway/main.go:774-776`) are bounded and control-character-free. |
| **prior WR-12** — `capacity() > 0` check-then-act race | `5354d1e` | **REGRESSED** | The TOCTOU itself is **gone** — both fast paths deleted; `runner.rs:90-100` and `runner.rs:116-126` are now unconditional `biased` selects. **But the same commit added a new un-cancellable, un-timeouted `self.tx.reserve().await` at `runner.rs:167`**, plus `flush_pending_checkpoints(&uncancelled)` at `runner.rs:166` which loops the same unbounded reserve per pending envelope. One unbounded reserve was deleted and another introduced. Filed as new **WR-01**. |
| **prior WR-13** — drift guidance after multi-KB schema dumps | `4196dff` | **NOT CLOSED** | Production message **was** reordered — `db/mod.rs:167-171` now leads with `"LanceDB schema drift detected for {name}. Remediation: …"` and appends `"Details - expected: {:?}, found: {:?}"`. However `4196dff` **touches only `engine/src/db/mod.rs`** (`git show 4196dff --stat`): the test file was not modified, and `engine/src/db/tests.rs:107` still reads `assert!(error.contains("Remediation: schema reconciliation is fail-closed by design"))` — a presence assertion that passed *before* the reorder and passes *after* it. Per the stated criterion, the property the plan meant to deliver (operator-visible **placement**) has no regression protection. Re-filed as new **WR-13**. |
| **prior WR-14** — committed default Postgres DSN with `sslmode=disable` | `a007b89` | **NOT CLOSED** | `a007b89` adds `if strings.TrimSpace(cfg.Gateway.DatabaseURL) == ""` at `gateway/main.go:87-89` — a guard against an *empty* URL. That is not the finding that was written. `git log e6e153f..HEAD -- config/config.toml` is **empty**: `config/config.toml:3` still reads `postgres://postgres:postgres@localhost:5432/lancet?sslmode=disable`, and `config/config.example.toml:7` carries the same value. Because the committed config always supplies a non-empty DSN, the new guard is **inert in the shipped configuration** — it cannot fire. The fix report's row 28 restates the finding as "empty string allows unconfigured startup", which is a different finding. Re-filed unchanged as new **WR-05**. |
| **prior WR-15** — no non-empty floor on reformulator output | `ccef730` | **CLOSED** | `reformulate.rs:47-52`: `if variants.is_empty() { return Err(NodeError::new(NodeErrorKind::InputValidation, …)) }`, placed before the `> 8` ceiling check at 53-61. Regression test `zero_variants_are_rejected_before_retrieval` read in full at `engine/src/tests/workflow_phase5.rs:1740-1786`: it drives a `FakeQueryReformulator::new(vec![])` through the real runner, asserts `fake_embedder.calls() == 0` (proving the failure precedes retrieval) and asserts `WorkflowCompleted{ success: false, error_kind: InputValidation }`. This is a genuine behavioural test, not a tautology. |

**Tally:** CLOSED 9 · PARTIALLY CLOSED 4 · NOT CLOSED 1 · REGRESSED 2. (prior WR-01 counts as
CLOSED; the exit-code regression it introduced is filed separately as new WR-04 rather than
recharacterising the fix.)

---

## §3 Critical Issues

None at HEAD `bb58a60`. Prior CR-01 is closed — see the first row of §2.

---

## §4 Warnings

### WR-01: `send_terminal_event` acquires the client channel with no cancellation arm and no timeout — the workflow task can park indefinitely (REGRESSION, introduced by `5354d1e`)

**File:** `engine/src/workflow/runner.rs:161-170` (also `runner.rs:166`)

**Issue:** `5354d1e` removed the `capacity() > 0` TOCTOU (prior WR-12) but introduced a new
unbounded await in the same commit:

```rust
pub async fn send_terminal_event(&self, event: Event) {
    if self.tx.is_closed() {                              // 164 — snapshot, not a guarantee
        return;
    }
    let uncancelled = CancellationToken::new();           // 165 — deliberately un-cancellable
    let _ = self.flush_pending_checkpoints(&uncancelled).await;  // 166 — loops reserve() per envelope
    if let Ok(permit) = self.tx.reserve().await {         // 167 — no select!, no timeout
        permit.send(Ok(self.wrap_next_event(event)));
    }
}
```

The un-cancellable token is *intentional* — it is the mechanism that closes prior CR-01's tail, so
a cancellation arm cannot simply be reinstated. But nothing bounds the wait.

**Failure scenario (inputs/state → outcome):** a client opens `POST /rag/query`, reads a handful of
SSE frames, then stops reading without closing the connection (HTTP/2 flow-control window
exhausted, or a paused browser tab). The gateway's `stream.Recv()` loop blocks, so `rx`
(`main.rs:1885`, `mpsc::channel(100)`) is alive but undrained and fills. The workflow finishes and
calls `emit_terminal_once` → `send_terminal_event`. `tx.is_closed()` is false (the receiver still
exists), so line 167 parks. There is no cancellation escape and no timer. The spawned task
(`main.rs:1911-1915`) and everything it owns — the full `WorkflowContext`, all `Arc<dyn …>` port
clones, the evidence blocks and assembled prompt — are retained until the TCP connection actually
dies and `rx` is dropped.

**Bounded, and stated as such:** if the receiver is *dropped*, `tx` becomes closed and `reserve()`
returns `Err`, so the task exits. The exposure is the "alive but not draining" window, not a
permanent leak, which is why this is a Warning rather than a Critical. Sustained per-connection
accumulation cannot be demonstrated by reading alone.

`flush_pending_checkpoints(&uncancelled)` at line 166 has the same shape and can loop up to
`MAX_PENDING_CHECKPOINTS` (32, `runner.rs:19`) times before the terminal event is even attempted.

**Fix:** bound the wait with a timer rather than a token, since cancellation-immunity is the point.

```rust
pub async fn send_terminal_event(&self, event: Event) {
    const TERMINAL_DELIVERY_BUDGET: Duration = Duration::from_secs(5);
    if self.tx.is_closed() { return; }
    let uncancelled = CancellationToken::new();
    let _ = timeout(TERMINAL_DELIVERY_BUDGET, self.flush_pending_checkpoints(&uncancelled)).await;
    if let Ok(Ok(permit)) = timeout(TERMINAL_DELIVERY_BUDGET, self.tx.reserve()).await {
        permit.send(Ok(self.wrap_next_event(event)));
    }
}
```

### WR-02: `emit_terminal_once` still returns before `WorkflowCompleted` when `FinalAnswer` delivery fails, with the terminal latch already set

**File:** `engine/src/workflow/runner.rs:499-505`, `engine/src/workflow/runner.rs:488-494`

**Issue:** `7ea20f2` (prior WR-02) removed the *checkpoint* early-return at 506-508, and `5354d1e`
made the `WorkflowCompleted` send cancellation-immune. The **`FinalAnswer` early-return survives**:

```rust
if sink
    .send_event_or_cancel(events::final_answer(response.clone()), cancel)
    .await
    .is_err()
{
    return;                       // 504 — WorkflowCompleted never attempted
}
```

`terminal_emitted` was already latched by the `compare_exchange` at 488-494, so nothing retries.
The result is the asymmetry the two fixes were meant to eliminate: `WorkflowCompleted` is now
immune to cancellation *if it is reached*, but a cancelled `FinalAnswer` prevents it from being
reached at all.

**Failure scenario:** the workflow succeeds; the token is cancelled while `rx` is still alive. Then
`send_event_or_cancel` → `send_event` → `flush_pending_checkpoints`'s `biased` first arm
(`runner.rs:118`) wins, returns `Cancelled`, `send_event_or_cancel` maps it to
`Err(NodeError::cancelled())` (`runner.rs:156`), and line 504 returns. The stream ends with neither
`final_answer` nor `workflow_completed`; the gateway emits `STREAM_EOF_WITHOUT_TERMINAL`
(`gateway/main.go:743`).

**Reachability, stated precisely rather than asserted:** the window requires "cancelled but not yet
closed". `CancelOnDropStream::drop` (`main.rs:1878-1882`) calls `self.cancel.cancel()` in the `Drop`
body, *before* the struct's `inner` field (which owns `rx`) is dropped — so such a window does
exist by construction. However the client is already disconnecting inside it, so the user-visible
impact is bounded and could not be reproduced by reading alone. The finding is the structural one:
an observability/delivery failure on one event can still suppress the protocol terminal event.

**Fix:** route the terminal event through `send_terminal_event` unconditionally, exactly as the
error branch at 528 already does.

```rust
let _ = sink.send_event_or_cancel(events::final_answer(response.clone()), cancel).await;
if let Err(err) = sink.send_checkpoint_or_error("terminal_success", ctx, cancel) {
    tracing::warn!(error = %err, "terminal checkpoint dropped; continuing to terminal event");
}
sink.send_terminal_event(events::workflow_completed(
    true, duration_ms, NodeErrorKind::Unspecified, "", Some(response), ctx.notices.clone(),
)).await;
```

### WR-03: Sequence ordinals are still consumed on failed deliveries, producing gaps indistinguishable from lost events (prior WR-09 was never fixed)

**File:** `engine/src/workflow/runner.rs:71-79`, `engine/src/workflow/runner.rs:141`,
`engine/src/workflow/runner.rs:179`

**Issue:** `wrap_next_event` allocates the ordinal eagerly, before delivery is even attempted:

```rust
fn wrap_next_event(&self, event: Event) -> WorkflowEvent {
    let seq = self.sequence.next();          // 72 — allocated unconditionally
    events::wrap_event(event, seq, self.trace_id.clone(), self.session_id.clone())
}
…
self.send_envelope(self.wrap_next_event(event), cancel).await   // 141 — may return Cancelled/Closed
```

`send_checkpoint:179` does the same before `try_send`, and `CheckpointDelivery::OwnershipFailure`
(`runner.rs:226-231`) even reports the abandoned ordinal in its error text — proving the gap is
known at the source and never communicated downstream.

**Failure scenario:** the client receives ordinals 1..7. Node 4 fails; `NodeFailed` is built at
`runner.rs:386` (ordinal 8 allocated), `flush_pending_checkpoints` sees the token already cancelled
by a prior `send_event_or_cancel` and returns `Cancelled` — ordinal 8 is burned. The terminal event
then goes out as ordinal 9 (allocated lazily at `runner.rs:168`). A consumer doing gap detection on
`WorkflowEvent.sequence_ordinal` (a strictly monotonic counter, `events.rs:255-263`) sees 7 → 9 and
cannot tell "dropped in transit" from "reserved then abandoned". The gateway persists the same
value as `workflow_checkpoints.sequence_ordinal` (`gateway/db/schema.sql:49`) for ordering.

**Sharpening detail:** `send_terminal_event:168` allocates the ordinal *inside* `if let Ok(permit)`
— i.e. lazily, only once capacity is held. The correct idiom is present in this very file and was
applied to exactly one of the three call sites.

**Fix:** allocate on successful hand-off everywhere.

```rust
async fn send_envelope_lazy(
    &self,
    make: impl FnOnce(u64) -> WorkflowEvent,
    cancel: &CancellationToken,
) -> ClientEventDelivery {
    if self.tx.is_closed() { return ClientEventDelivery::Closed; }
    tokio::select! {
        biased;
        _ = cancel.cancelled() => ClientEventDelivery::Cancelled,
        res = self.tx.reserve() => match res {
            Ok(permit) => { permit.send(Ok(make(self.sequence.next()))); ClientEventDelivery::Sent }
            Err(_) => ClientEventDelivery::Closed,
        },
    }
}
```

(`send_checkpoint` needs the ordinal inside the payload, so it must either reserve first, or
explicitly document ordinal reservation as part of the wire contract.)

### WR-04: The gateway now exits with status 0 when it fails to bind (REGRESSION, introduced by `e8982d0`)

**File:** `gateway/main.go:1095-1100`

**Issue:** `e8982d0` replaced `logger.Fatal("gateway stopped", …)` — which calls `os.Exit(1)` — with:

```go
go func() {
    if err := server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
        logger.Error("gateway stopped", zap.Error(err))   // 1097 — no longer fatal
        stop()                                            // 1098 — unblocks <-sigCtx.Done()
    }
}()
```

`stop()` is the `context.CancelFunc` from `signal.NotifyContext` (`main.go:1092`), so cancelling it
unblocks `<-sigCtx.Done()` at `main.go:1103`; `main` then falls through the graceful-shutdown block
and **returns normally**, giving process exit status **0**.

**Failure scenario:** the gateway is deployed with `gateway.port = "8080"` on a host where 8080 is
already bound. `ListenAndServe` returns `listen tcp :8080: bind: address already in use`. One
`ERROR` line is written, then the process exits 0. systemd with `Restart=on-failure` will not
restart it; a Kubernetes `Deployment` records a `Completed` pod rather than `CrashLoopBackOff`; a CI
smoke test that checks `$?` passes. Before `e8982d0` this exited 1. The failure is now silent to
every supervisor.

**Fix:** distinguish the two exits.

```go
serveErr := make(chan error, 1)
go func() {
    if err := server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
        serveErr <- err
    }
    close(serveErr)
}()

var fatal error
select {
case err, ok := <-serveErr:
    if ok && err != nil {
        logger.Error("gateway stopped", zap.Error(err))
        fatal = err
    }
case <-sigCtx.Done():
    logger.Info("gateway shutting down")
}

shutCtx, cancelShut := context.WithTimeout(context.Background(), 15*time.Second)
defer cancelShut()
_ = server.Shutdown(shutCtx)

if fatal != nil {
    stop(); dispatcher.Close(); recCancel(); conn.Close(); pool.Close(); _ = logger.Sync()
    os.Exit(1)   // deferred cleanup already run explicitly
}
```

### WR-05: `config/config.toml` and `config/config.example.toml` still commit a default Postgres credential with TLS disabled; the new non-empty guard is inert (prior WR-14 NOT closed)

**File:** `config/config.toml:3`, `config/config.example.toml:7`, `gateway/main.go:87-89`,
`gateway/main.go:1063`

**Issue:** `a007b89` added

```go
if strings.TrimSpace(cfg.Gateway.DatabaseURL) == "" {
    return Config{}, errors.New("gateway.database_url must not be empty (set LANCET_GATEWAY__DATABASE_URL)")
}
```

but the finding was never about an empty URL. `git log e6e153f..HEAD -- config/config.toml` returns
no commits; line 3 is unchanged:

```toml
database_url = "postgres://postgres:postgres@localhost:5432/lancet?sslmode=disable"
```

`loadConfig()` (`main.go:57-88`) reads this file by default and the value goes straight to
`pgxpool.New` at `main.go:1063`. **The added guard can never fire in the shipped configuration**,
because `config.toml` always supplies a non-empty value — it protects only a deployment that has
already deleted the line.

**Failure scenario:** an operator repoints the service at a managed Postgres by editing line 3 in
place — the obvious action given a credential-shaped literal sits there. `sslmode=disable` travels
with the edit, and the DSN now carries plaintext credentials across a network boundary. Nothing
fails closed: the connection succeeds. Viper's `AutomaticEnv` +
`SetEnvKeyReplacer(".", "__")` (`main.go:71-73`) already makes `LANCET_GATEWAY__DATABASE_URL` work
as an override, so the safe mechanism exists and is unused.

**Fix:** blank the committed value so the existing guard becomes load-bearing, and reject
`sslmode=disable` outside development.

```toml
# Supplied via LANCET_GATEWAY__DATABASE_URL; never commit a real DSN.
database_url = ""
```

```go
if os.Getenv("LANCET_ENV") == "prod" && strings.Contains(cfg.Gateway.DatabaseURL, "sslmode=disable") {
    return Config{}, errors.New("gateway.database_url must not disable TLS in prod")
}
```

### WR-06: The retry-budget timeout invariant is still unenforced, and a committed config still violates it (prior WR-03 half-fixed)

**File:** `engine/src/main.rs:257-290`, `config/config.verify.toml:9`,
`config/config.verify.toml:19`, `engine/src/workflow/nodes/generate.rs:105`,
`engine/src/workflow/nodes/generate.rs:127`

**Issue:** `7da662a` added exactly one cross-field check (`main.rs:280-288`, the graph timer). The
invariant that the phase's retry design actually rests on was not added.
`GenerateAnswerNode::run` makes up to **two** provider attempts — `generate.rs:105` and
`generate.rs:127` — inside a **single** node timer (`runner.rs:354`, `runner.rs:359`), so it
requires `generation_node_timeout_ms >= 2 × generation_timeout_secs × 1000`.

**Failure scenario:** run the Phase 05 live verification with `LANCET_CONFIG_DIR` pointing at
`config/config.verify.toml`. `generation_timeout_secs = 30` (line 9) and
`generation_node_timeout_ms = 7000` (line 19). `validate()` accepts it — all seven `== 0` checks
pass and the graph check (10000 + 4000 ≤ 15000) passes. At runtime the node timer fires at 7 s,
23 s before the *first* provider attempt can even time out. The node always reports
`NodeErrorKind::Timeout`, the 2-attempt retry budget is provably unreachable, and no diagnostic
distinguishes this from a slow provider. Production (`config.toml:17` = 65000 vs 2 × 30000 = 60000)
satisfies it by 5 s **by coincidence, not by enforcement** — an operator raising
`generation_timeout_secs` to 35 silently breaks it.

**Fix:** validate where the provider timeout is in scope (`EffectiveRagSettings::try_from_settings`
already reads `settings.openrouter`).

```rust
pub fn validate_against_provider(&self, generation_timeout_secs: u64) -> Result<(), String> {
    const GENERATION_ATTEMPTS: u64 = 2; // GenerateAnswerNode performs up to 2 attempts
    let required = GENERATION_ATTEMPTS.saturating_mul(generation_timeout_secs.saturating_mul(1000));
    if self.generation_node_timeout_ms < required {
        return Err(format!(
            "generation_node_timeout_ms ({}) must be >= {} ({} attempts x {}s provider timeout)",
            self.generation_node_timeout_ms, required, GENERATION_ATTEMPTS, generation_timeout_secs
        ));
    }
    Ok(())
}
```

and correct `config/config.verify.toml:19` to `>= 60000` (or lower `generation_timeout_secs`).

### WR-07: `run_inline_prompt_generation_remainder` still masks the node error with `Cancelled`, never sets `graph_weight`, and remains public with no production consumer

**File:** `engine/src/workflow/mod.rs:231-241`, `engine/src/workflow/mod.rs:250-260`,
`engine/src/workflow/mod.rs:200-207`, `engine/src/workflow/mod.rs:164`

**Issue:** `0969a2b` fixed the always-fails-by-construction defect (empty evidence, no cancel token,
indiscriminate retry) but left three problems, one of which is the fixed Critical reappearing in a
function the Critical's fix did not touch:

```rust
sink.send_event_or_cancel(
    events::node_failed(name_gen, node_err.kind.clone(), &node_err.message, false),
    cancel,
)
.await?;                    // 240 — the `?` discards node_err and returns Cancelled
return Err(node_err);       // 241 — unreachable whenever delivery fails
```

Identical at `mod.rs:259`/`mod.rs:260`. This is exactly the shape `ac3db6e` corrected in
`runner.rs:383-393` (`let _ = …await;`), applied there and not here.

**Failure scenario:** the tracer path runs with the client channel full or the token already
cancelled; the generator returns `SchemaValidation`. `NodeFailed` cannot be delivered, so line 240's
`?` returns `NodeError::cancelled()`. `run_tracer:470-472` stores that as `overall_err`, and
`emit_terminal_once` reports `WorkflowCompleted{ success: false, error_kind: Cancelled }` — the real
`LlmGenerationFailed` cause is gone from every observable surface.

Two further residuals: (a) `gen_req.graph_weight` is never assigned (`mod.rs:200-207`), so this path
uses `GenerationRequest::new`'s default rather than the configured value that `generate.rs:97`
applies — the two paths can pack graph facts differently for the same request; (b) the function is
still `pub` (`mod.rs:164`) with no production consumer (`query_rag` uses `run_workflow`,
`main.rs:1914`; only `run_tracer` calls it), and `WorkflowDependencies` (`mod.rs:132-156`) exists
solely to feed it. The prior finding's recommendation — `#[cfg(test)]` or delete — was not applied.

**Fix:** apply the CR-01 pattern (`let _ = …await;` then `return Err(node_err);`), set
`gen_req.graph_weight`, and gate the function and `WorkflowDependencies` behind `#[cfg(test)]`.

### WR-08: Checkpoint sink errors are logged only for one concrete sink type, and there is still no retry or dead-letter path (prior WR-06 half-fixed)

**File:** `gateway/checkpoint_sink.go:229-239`, `gateway/checkpoint_sink.go:67-69`

**Issue:** `8b692a5` replaced `_ = d.sink.SaveCheckpoint(…)` with:

```go
if err := d.sink.SaveCheckpoint(context.Background(), env); err != nil {
    if ps, ok := d.sink.(*PostgresCheckpointSink); ok && ps.logger != nil {   // 231
        ps.logger.Warn("checkpoint dispatcher dropped envelope on sink error", …)
    }
}
```

The dispatcher type-asserts on a concrete implementation to reach a logger. Any other
`CheckpointSink` — `InMemoryCheckpointSink` (`checkpoint_sink.go:132-151`), or any future
implementation — falls through the `if` with the error **still discarded**, which is the original
defect. `CheckpointDispatcher` has no `logger` field of its own.

More importantly, the substance of the finding is untouched: there is **no retry and no
dead-letter**. A transient Postgres error (failover, connection storm, the 5 s `writeCtx` timeout at
`checkpoint_sink.go:113` expiring) permanently loses that checkpoint. The envelope is already popped
off `primary`/`overflow`/`pending` by `nextEnvelope` before `SaveCheckpoint` is called, so nothing
can recover it.

**Failure scenario:** Postgres is briefly unavailable during a 5-node workflow. All five checkpoints
drain out of the dispatcher, each fails, each produces one `WARN`, and the workflow's persisted
provenance record is empty — while `workflow_completed` reports `success: true` to the client. There
is no counter, no metric and no queryable trace of the loss.

**Fix:** give the dispatcher its own `*zap.Logger` (drop the type assertion), and add a bounded
retry with a dropped-envelope counter.

```go
type CheckpointDispatcher struct { …; logger *zap.Logger; dropped atomic.Uint64 }

if err := d.sink.SaveCheckpoint(ctx, env); err != nil {
    d.dropped.Add(1)
    if d.logger != nil {
        d.logger.Error("checkpoint permanently dropped",
            zap.String("trace_id", env.TraceID),
            zap.Uint64("sequence_ordinal", env.SequenceOrdinal),
            zap.Uint64("dropped_total", d.dropped.Load()),
            zap.Error(err))
    }
}
```

### WR-09: `dispatcher.Close()` has an unbounded drain — newly reachable because prior WR-01's fix made it live

**File:** `gateway/checkpoint_sink.go:297-309`, `gateway/checkpoint_sink.go:113`,
`gateway/main.go:1081`

**Issue:** `Close()` sets `d.closed`, closes `primary`, then blocks on `<-d.done` (line 308) until
`loop()` has drained every buffered envelope. Each iteration calls `SaveCheckpoint`, which uses a
**5-second** per-write context (`checkpoint_sink.go:113`). The buffers hold up to 1 (`primary`,
cap 1) + 4 (`overflow`) + 16 (`pending`) = **21 envelopes**. With Postgres unresponsive, `Close()`
blocks for roughly 21 × 5 s ≈ **105 seconds** with no ceiling of its own.

This code predates the remediation; what is new is its **reachability**. Before `e8982d0`,
`defer dispatcher.Close()` at `main.go:1081` never ran (`logger.Fatal` → `os.Exit`). It now runs on
every SIGTERM.

**Failure scenario:** a Kubernetes rolling update sends SIGTERM with the default
`terminationGracePeriodSeconds: 30`. `server.Shutdown` consumes up to 15 s
(`main.go:1108`) waiting for in-flight SSE streams, then the deferred `dispatcher.Close()`
starts a drain that can need 105 s. At t=30 s the kubelet sends SIGKILL: the pool is torn down
mid-write, remaining envelopes are lost anyway, and the graceful shutdown the fix was written to
provide does not complete. The two 15 s and 5 s budgets were chosen independently and do not
compose.

**Fix:** bound the drain and make the budget explicit.

```go
func (d *CheckpointDispatcher) CloseWithTimeout(budget time.Duration) error {
    d.mu.Lock()
    if !d.closed { d.closed = true; close(d.primary) }
    d.mu.Unlock()
    select {
    case <-d.done:
        return nil
    case <-time.After(budget):
        return errors.New("checkpoint dispatcher drain timed out")
    }
}
```

and call it explicitly after `server.Shutdown` with a budget that fits inside the pod grace period.

### WR-10: `result_hash` — the retrieval snapshot's reproducibility field — is computed with `DefaultHasher`, whose algorithm `std` documents as unspecified

**File:** `engine/src/workflow/nodes/retrieve.rs:170-173`,
`engine/src/workflow/nodes/retrieve.rs:187`, `engine/src/main.rs:2213-2217`,
`engine/src/bin/seed_rag_fixture.rs:79-83`

**Issue:**

```rust
let mut result_hasher = DefaultHasher::new();
for candidate in &taken_candidates {
    candidate.candidate.chunk_id.hash(&mut result_hasher);
}
…
result_hash: format!("{:x}", result_hasher.finish()),
```

**Premise stated exactly, because it is easy to get wrong:** `DefaultHasher::new()` is *not*
randomly seeded — it uses fixed keys, so the value is stable within a single build and across
process restarts. The defect is different: `std` explicitly documents `DefaultHasher`'s algorithm as
an implementation detail that may change between Rust releases, and `Hash` impls (notably `str`'s
length-prefixing) are likewise unspecified.

**Failure scenario:** `RetrievalSnapshot.result_hash` is serialized into every checkpoint
(`events.rs:152-158`, persisted to `workflow_checkpoints.context_snapshot`) and returned to the client
in `QueryRagResponse` — its whole purpose is reproducible provenance. The engine is rebuilt on a
newer Rust toolchain with no source change. The same query over the same index now emits a
different `result_hash`. Every historical checkpoint becomes incomparable to every new one, and a
reproducibility check reports drift where none occurred. The same pattern backs `content_hash`
(`main.rs:2213`), whose output is written into a persisted LanceDB `nodes` column at
`main.rs:2401-2404` — so the same cross-toolchain instability applies to already-ingested data.
*Its downstream consumers were not traced in this pass;* only the write site was verified. The seed
fixture (`seed_rag_fixture.rs:79-83`) carries a third copy of the pattern.

**Fix:** use a specified, version-stable hash for anything persisted as provenance.

```rust
// Cargo.toml: blake3 = "1"
let mut hasher = blake3::Hasher::new();
for candidate in &taken_candidates {
    hasher.update(candidate.candidate.chunk_id.as_bytes());
    hasher.update(b"\x00");   // unambiguous separator
}
let result_hash = hasher.finalize().to_hex().to_string();
```

### WR-11: Two identical hand-rolled SQL-literal escapers, applied to every LanceDB predicate

**File:** `engine/src/graph/mod.rs:289-291`, `engine/src/main.rs:2209-2211`

**Issue:** The same three-line function exists twice under two names:

```rust
pub fn escape_sql_literal(value: &str) -> String { value.replace('\'', "''") }   // graph/mod.rs:289
fn sql_string(value: &str) -> String { value.replace('\'', "''") }               // main.rs:2209
```

`main.rs:26` already imports `graph::escape_sql_literal`, and both are used in the *same file* —
`main.rs:2896` and `main.rs:2919` use `escape_sql_literal` while `main.rs:1051`, `main.rs:1119`,
`main.rs:1142`, `main.rs:1761`, `main.rs:2329` and `main.rs:3191` use `sql_string`. A reader cannot
tell whether the two are meant to differ.

**No exploitable path found, stated explicitly.** Every value reaching these predicates was traced:
`document_id` is UUID-validated by `validate_document_id` (`main.rs:1206-1216`); `seed_entity_id` is
UUID-parsed at `graph/mod.rs:313-319`; the `frontier`/`visited` ID sets at `graph/mod.rs:323-327`
and `graph/mod.rs:424-429` are read back out of the DB. `seed_entity_name` — the one
attacker-controlled string in this area — is byte-bounded at `main.rs:1949` and used for an
in-memory case-folded comparison (`main.rs:1997`), never spliced into a predicate. **This is filed
as duplication and latent hazard, not as an injection finding.**

The hazard is that quote-doubling alone is only sufficient because DataFusion's parser does not
treat backslash as an escape character in string literals. That is an undocumented dependency on a
third-party parser dialect, guarding a `pub` function (`graph/mod.rs:289`) that any caller can now
reach.

**Fix:** delete `sql_string`, keep the single `escape_sql_literal`, and document the dialect
assumption at its definition:

```rust
/// Escapes a value for interpolation into a DataFusion/LanceDB string literal.
/// Relies on the SQL-standard dialect (no backslash escapes in string literals);
/// see `only_if` predicate construction. Callers must still validate identifier
/// shape — this is not a substitute for parameterization.
pub fn escape_sql_literal(value: &str) -> String { value.replace('\'', "''") }
```

### WR-12: A checkpoint ownership failure aborts a *successful* node with no `NodeFailed` event

**File:** `engine/src/workflow/runner.rs:381`, `engine/src/workflow/runner.rs:226-231`,
`engine/src/workflow/runner.rs:188-190`

**Issue:** In `run_node`'s success branch:

```rust
sink.send_checkpoint_or_error(kind.checkpoint_label(), ctx, cancel)?;   // 381
```

The `?` propagates `CheckpointDelivery::OwnershipFailure` as
`NodeError::new(NodeErrorKind::Internal, "Checkpoint envelope ownership capacity exhausted at
sequence N")` and returns from `run_node` immediately — **without** emitting `NodeFailed`, because
the `Err(err)` arm at 383-393 belongs to `result`, which is `Ok(())` here.

**Failure scenario:** a slow SSE consumer lets `pending` reach `MAX_PENDING_CHECKPOINTS` = 32
(`runner.rs:19`, `runner.rs:188-190`). `RetrieveHybrid` completes successfully — `node_completed` is
already on the wire — and then its checkpoint hits the ownership ceiling. `run_workflow:424-427`
records the error and breaks; `emit_terminal_once` emits
`WorkflowCompleted{ success: false, error_kind: Internal }`. The client sees
`node_started → node_completed → workflow_completed(success=false)` for the same node, with **no
`node_failed`** anywhere in the stream — a sequence no consumer state machine would expect. It also
means a purely *observability* backpressure condition kills a request whose retrieval already
succeeded.

**Fix:** emit `NodeFailed` on this path too, and consider degrading ownership failure to a notice
rather than a request-killing error.

```rust
if let Err(err) = sink.send_checkpoint_or_error(kind.checkpoint_label(), ctx, cancel) {
    let _ = sink.send_event_or_cancel(
        events::node_failed(name, err.kind.clone(), &err.message, err.retryable), cancel,
    ).await;
    return Err(err);
}
```

### WR-13: The schema-drift test asserts presence, not placement — `4196dff`'s deliverable has no regression protection (prior WR-13 NOT closed)

**File:** `engine/src/db/tests.rs:106-108`, `engine/src/db/mod.rs:167-171`

**Issue:** `git show 4196dff --stat` shows **one file changed: `engine/src/db/mod.rs`**. The
production message was reordered correctly (`db/mod.rs:167-171` now leads with
`"LanceDB schema drift detected for {name}. Remediation: …"` and appends
`"Details - expected: {:?}, found: {:?}"`), but the test that was cited in the original finding as
inadequate is byte-for-byte unchanged:

```rust
assert!(error.contains("schema drift detected for documents"));                        // 106
assert!(error.contains("Remediation: schema reconciliation is fail-closed by design")); // 107
```

`contains` passed before the reorder and passes after it. The property the plan set out to deliver
— that the actionable sentence is **visible before** the multi-kilobyte `{:?}` dump of 19 `Field`
structs (each including a 2048-element `FixedSizeList` descriptor) — is not asserted anywhere.

**Failure scenario:** a future refactor moves the `Details - expected: …` fragment back in front of
the remediation sentence, or reintroduces the original single-`format!` ordering. The full Rust test
suite passes green. The operator-facing regression ships undetected, and the phase's own evidence
(the passing test) argues that it did not.

**Fix:** assert ordering, not presence.

```rust
let remediation_at = error.find("Remediation:").expect("remediation guidance present");
let details_at = error.find("Details - expected:").expect("schema details present");
assert!(
    remediation_at < details_at,
    "remediation guidance must precede the schema dump; got remediation@{remediation_at} details@{details_at}"
);
```

---

## §5 Info

### IN-01: Widened `pub(crate)` → `pub` visibility permanently enlarges the library's public surface

**File:** `engine/src/lib.rs:3-11`, `engine/src/main.rs:26`, `engine/src/graph/mod.rs:289`

**Issue:** The binary is a separate crate from the `engine` library (`lib.rs:1`
`extern crate self as engine;`), so every item `main.rs` touches had to leave `pub(crate)`.
Mechanically correct, but items like `graph::escape_sql_literal` are now callable by any downstream
consumer without the UUID validation that makes them safe (see WR-11). Contradicts
`rust-guidelines.md` M-SINGLE-ITEM-PATH's intent of a deliberate, minimal public surface.

**Fix:** a `#[doc(hidden)] pub mod internal` re-export module, or a `binary-internals` Cargo feature.

### IN-02: Production always takes the single-variant path — cross-variant RRF is unexercised

**File:** `engine/src/workflow/nodes/reformulate.rs:45`, `engine/src/retrieval/fusion.rs:236-244`

**Issue:** `build_production_workflow` wires `NoOpQueryReformulator`, which returns exactly one
variant. So `ctx.variants.len() == 1` always, and `fuse_cross_variant_candidates` hits the
`len() == 1` early return at `fusion.rs:236`. In production the two-pass cross-variant RRF, both
8-variant caps (`reformulate.rs:53`, `fusion.rs:225`), and multi-element `variant_identities` are
never reached. Recorded so the capability is not assumed production-proven by this phase.

**Fix:** document the activation path at `build_production_workflow`, or mark cross-variant
behaviour as production-unreached in the phase verification record.

### IN-03: The single-variant fusion path skips the `candidate_limit` truncation the multi-variant path applies

**File:** `engine/src/retrieval/fusion.rs:236-244`, `engine/src/retrieval/fusion.rs:249-253`

**Issue:** The multi-variant path truncates each list with `.take(settings.candidate_limit)`
(`fusion.rs:251`); the `len() == 1` early return returns the list untouched. Since `fuse_candidates`
unions two sources each capped at `candidate_limit`, the single-variant result can hold up to
`2 × candidate_limit` entries. Only the downstream `final_limit` take (`retrieve.rs:162-165`) masks
it — and it changes which candidates reach the reranker.

**Fix:** `single_list.truncate(settings.candidate_limit);` on the early-return branch.

### IN-04: `timeout_for_node` is dead code with a magic fallback; `pending_checkpoint_count` is test-only

**File:** `engine/src/workflow/runner.rs:313-322`, `engine/src/workflow/runner.rs:235-237`

**Issue:** `timeout_for_node(&str)` has no production caller — dispatch goes through the exhaustive
typed `timeout_for_kind(NodeKind)` at 303-311 (sole call site `runner.rs:354`). It duplicates that
mapping via string matching and adds an unreachable `_ => Duration::from_millis(5000)` magic
fallback: precisely the stringly-typed dispatch that `NodeKind` was introduced to eliminate, plus a
silent-wrong-timeout hazard if a name is ever misspelled.

**Fix:** delete `timeout_for_node`; gate `pending_checkpoint_count` behind `#[cfg(test)]`.

### IN-05: `buf.gen.yaml` `clean: false` is forced by a hand-written file inside the generated tree

**File:** `buf.gen.yaml:2`, `engine/src/pb/mod.rs:1-5`

**Issue:** The prost/tonic plugins write to `out: engine/src/pb`, and `engine/src/pb/mod.rs` is
hand-written — a 5-line `include!("lancet/v1/lancet.v1.rs")` wrapper that `clean: true` would delete
on every regeneration. The cost is that stale generated artifacts survive: a removed or renamed
proto message leaves a compilable, importable orphan and the generated tree can silently diverge
from `proto/`.

**Fix:** move the wrapper out of the generated tree (`engine/src/pb.rs` with
`#[path = "pb/lancet/v1/lancet.v1.rs"]`) and restore `clean: true`; otherwise add a CI check that
`git status` is clean after regeneration.

### IN-06: `ctx.bm25_results` accumulates duplicate chunk IDs across variants

**File:** `engine/src/workflow/nodes/retrieve.rs:112-114`

**Issue:** The per-variant loop pushes every BM25 candidate's `chunk_id` with no deduplication,
while `ctx.vector_results` (`retrieve.rs:80-83`) is assigned once from a deduplicated dense list.
With N variants, a chunk matched by all of them appears N times. `ctx.bm25_results` is serialized
verbatim into every checkpoint (`events.rs:186-187`), so persisted provenance would misreport BM25
recall and grow super-linearly. Latent today per IN-02.

**Fix:** guard the push with a `HashSet<String>` of seen chunk IDs.

### IN-07: `uint64` → `int32` narrowing on `sequence_ordinal`

**File:** `gateway/checkpoint_sink.go:119`, `gateway/db/schema.sql:49`,
`proto/lancet/v1/lancet.proto:182`, `proto/lancet/v1/lancet.proto:198`

**Issue:** `SequenceOrdinal: int32(env.SequenceOrdinal)` narrows a protobuf `uint64` (verified at
`lancet.proto:182` and `:198`) into an `integer` column with no bounds check; values ≥ 2³¹ wrap
negative. Not realistically reachable, but it is an unchecked lossy conversion on a persisted
ordering key.

**Fix:** widen the column to `bigint` and the sqlc model to `int64`, or reject out-of-range values.

### IN-08: `notices` must be read from two different places depending on `success`

**File:** `gateway/main.go:855-873`

**Issue:** On success the gateway writes `final_response` (whose DTO already carries `notices`, from
`WorkflowContext::to_query_rag_response`, `workflow/mod.rs:102`); on failure it writes a top-level
`wcPayload["notices"]`. Content is equivalent, but a client must check two locations depending on
the `success` flag.

**Fix:** always emit top-level `notices` on `workflow_completed`, in addition to `final_response`.

### IN-09: Seven cancellation checks in one prompt-packing function, most of which cannot observe a state change

**File:** `engine/src/prompt.rs:329`, `:446`, `:456`, `:484`, `:505`, `:510`, `:524`

**Issue:** `pack_evidence_and_graph_prompt` checks `cancel.is_cancelled()` at function entry (329),
at the loop top (446), inside each match arm (456, 484), after `yield_now()` (505), and twice more
after the loop (510, 524). Between the arm checks and the post-yield check there is no `await`, so
those cannot observe a change. The redundancy obscures where cancellation is actually meaningful —
the `yield_now().await` before 505 is the only true suspension point.

**Fix:** keep 329, 505 and one pre-return check; delete 456, 484 and 510.

### IN-10: `let _ = &deps;` keep-alive in the spawned workflow task

**File:** `engine/src/main.rs:1913`, `engine/src/main.rs:1902`

**Issue:** `build_production_workflow` returns `(runner, deps)` but `deps` has no production
consumer — the nodes already own their `Arc` clones. The spawned task contains `let _ = &deps;`
purely to move the value into the closure and suppress a warning; a reader cannot tell whether that
lifetime is load-bearing. Directly coupled to WR-07: `WorkflowDependencies` exists only for the dead
inline remainder.

**Fix:** return only the runner from `build_production_workflow` (with a `#[cfg(test)]` variant that
also returns `deps`), and delete the line.

### IN-11: Model-capability cache never expires, and `ModelCapabilities` is written but never read

**File:** `engine/src/generation/openrouter.rs:234`, `engine/src/generation/openrouter.rs:342-353`

**Issue:** `capabilities_cache: HashMap<CapabilityKey, Arc<OnceCell<ModelCapabilities>>>` caches a
successful preflight for the process lifetime. If OpenRouter later withdraws
`response_format`/`structured_outputs` for the configured model — a real risk given
`config/config.toml:41` pins a `:free` *preview* model — the process keeps sending strict-schema
requests until restart. Errors correctly leave the `OnceCell` uninitialized, so only the TTL is
missing. Separately, `ModelCapabilities.supports_structured_outputs` (`openrouter.rs:47`) is
constructed at `openrouter.rs:431-433` but never read (`let _caps = …` at `openrouter.rs:349`) — the
cell's existence carries the whole signal.

**Fix:** store `(ModelCapabilities, Instant)` and re-validate after a configurable TTL, or read the
field at the call site.

### IN-12: `workflow_checkpoints` has no uniqueness constraint on `(trace_id, sequence_ordinal)`

**File:** `gateway/db/schema.sql:46-56`, `gateway/db/schema.hcl:163-169`,
`gateway/db/query.sql:116-133`, `gateway/checkpoint_sink.go:90`

**Issue:** The primary key is a client-generated `uuid.NewString()` in a `varchar(255)` column, and
the `(trace_id, sequence_ordinal, created_at)` index is explicitly `unique = false`
(`schema.hcl:167`). Any duplicate delivery or replay inserts a second, indistinguishable row; the
statement is a plain `INSERT … RETURNING *` with no conflict handling. This becomes load-bearing the
moment WR-08's recommended retry is added.

**Fix:** make the index unique on `(trace_id, sequence_ordinal)` and change the statement to
`INSERT … ON CONFLICT (trace_id, sequence_ordinal) DO NOTHING`. Consider a native `uuid` type for
`id`.

### IN-13: `seed_rag_fixture` defines a local `f32` copy of `dense_score` and asserts against its own copy

**File:** `engine/src/bin/seed_rag_fixture.rs:85-87`

**Issue:** The fixture defines `fn dense_score(distance: f32) -> f32 { 1.0 / (1.0 + distance) }`, a
near-duplicate of the production `retrieval::dense::dense_score(f64)` — which this phase made `pub`
(IN-01), so it is directly importable. The local copy omits the production `distance.max(0.0)`
clamp, so a negative distance diverges. The fixture's closing assertions exercise the local copy, so
they prove nothing about retrieval scoring (`rust-guidelines.md` M-TAUTOLOGICAL-TESTS). No
production path is affected.

**Fix:** call `engine::retrieval::dense::dense_score`, or drop the two tautological assertions.

### IN-14: Env-var string overrides guard on the trimmed value but assign the untrimmed one; numeric overrides fail open

**File:** `engine/src/main.rs:655-679`, `engine/src/main.rs:611-654`

**Issue:** All seven string overrides share the pattern
`if !value.trim().is_empty() { settings.x = value; }` — assigning the **untrimmed** value.
`" openai/gpt-4o-mini "` passes the guard, passes `EffectiveRagSettings::validate()` (which also
only checks `trim().is_empty()`), and lands verbatim in the outbound `model` field and the `/models`
lookup key at `openrouter.rs:416`, producing a confusing
`"model metadata for ' openai/gpt-4o-mini ' not found"`.

Related: the numeric overrides use `if let Ok(val) = value.trim().parse::<u64>()`, so a typo like
`LANCET_ENGINE__WORKFLOW__GENERATION_NODE_TIMEOUT_MS=65s` is **silently ignored** and the config
value is used instead — a deployment-time misconfiguration with no diagnostic at all.

**Fix:** assign `value.trim().to_string()`, and return `Err` on unparseable numerics.

### IN-15: The schema-drift test asserts on human prose and leaks a temp directory on failure

**File:** `engine/src/db/tests.rs:106-108`

**Issue:** Two test-reliability nits alongside WR-13. (1) Line 107 asserts a 55-character substring
of a prose sentence in `db/mod.rs:168`; any wording improvement — including WR-13's recommended one
— breaks the test with no behavioural change. (2) `let _ = std::fs::remove_dir_all(path);` at line
108 is the last statement, not RAII: when either assertion fails the `assert!` panics first and a
LanceDB store is orphaned in `std::env::temp_dir()`. Same pattern at `db/tests.rs:56`, `:141`,
`:200`.

**Fix:** assert on a stable greppable marker (e.g. a `LANCEDB_SCHEMA_DRIFT` code constant in
`db/mod.rs`), and use `tempfile::TempDir` or a drop guard so cleanup survives a panic.

### IN-16: `.gitignore` blanket-ignores `data/`, leaving two dead entries below it

**File:** `.gitignore:59-61`

**Issue:** Line 59 `data/` sits immediately above the now-unreachable
`data/lancedb-verify-02-06/` (60) and `data/.phase02-lancedb-preclean-*/` (61). Nothing tracked was
newly ignored, so this breaks nothing today. The residual cost is that any file intentionally
committed under `data/` in future (a small regression fixture, a README explaining the layout) is
silently invisible to `git add` without `-f`, and the two stale lines misdescribe the actual rule.

**Fix:** delete lines 60-61 and add a negation for anything meant to be tracked, e.g.
`!data/README.md`.

### IN-17: `CheckpointEnvelope` carries four fields that are never persisted, and `NodeID` is always equal to `CheckpointType`

**File:** `gateway/checkpoint_sink.go:41-53`, `gateway/checkpoint_sink.go:92-98`,
`gateway/db/schema.sql:46-54`

**Issue:** `NewCheckpointEnvelopeFromEvent` populates `SessionID`, `CorrelationID`, `EventSequence`
and `TimestampMs`, but `SaveCheckpoint` writes only
`ID / TraceID / SequenceOrdinal / NodeName / ContextSnapshot / CreatedAt` — the table has **no
`session_id` column at all** (`schema.sql:46-54`), so checkpoints cannot be queried by session.
Whether that is intended is not recorded anywhere. Separately, `NodeID` and `CheckpointType` are
both assigned `cp.GetCheckpointType()` (lines 46-47), so the three-step fallback at 92-98 can only
collapse to `nodeName = env.CheckpointType` and its second branch is dead.
`CorrelationID: ev.GetTraceId()` (line 43) also silently equates two concepts the engine keeps
separate.

**Fix:** either persist the fields (add `session_id`, `event_sequence`, `timestamp_ms` columns) or
delete them from the envelope so the struct describes what is stored. Collapse the dead branch.

### IN-18: `rrf_k` is truncated from `f64` to `i32` in the persisted retrieval snapshot

**File:** `engine/src/workflow/nodes/retrieve.rs:183`, `proto/lancet/v1/lancet.proto:94-96`

**Issue:** `rrf_k: self.settings.rrf_k as i32` narrows the `f64` fusion constant to the proto's
`int32` field. `rrf_k` is validated as a finite `1.0..=1_000_000.0` float and used as `f64` in the
actual RRF denominator (`fusion.rs:252`). A configured `60.5` is persisted and reported as `60` —
in the one struct whose purpose is reproducible provenance. Harmless with the committed `60.0`.
Verified in the proto: `double vector_weight = 3;` (94) and `double bm25_weight = 4;` (95) sit
directly above `int32 rrf_k = 5;` (96), so the narrowing is an inconsistency within a three-line
span, not a considered wire decision.

**Fix:** change `RetrievalSnapshot.rrf_k` to `double` and regenerate, or reject non-integral `rrf_k`
at config validation so the snapshot cannot lie.

### IN-19 (NEW, from prior WR-10's fix): `wrap_checkpoint_event`'s fallback arm is dead code that silently burns an ordinal

**File:** `engine/src/workflow/runner.rs:239-243`

**Issue:** `5354d1e` replaced `unreachable!("checkpoint helper must pass a checkpoint event")` with
`_ => self.sequence.next()`. The panic hazard is correctly gone, but the recommended *structural*
fix (take a `CheckpointEvent`, not an `Event`) was not applied. The result is a dead arm — the sole
caller `send_checkpoint:180` always passes `Event::Checkpoint` — that, if ever reached, would
allocate a **second** ordinal for an event whose payload already carries a different one, silently
compounding WR-03's gap problem instead of failing loudly.

**Fix:** change the signature to `fn wrap_checkpoint_event(&self, checkpoint: CheckpointEvent)` and
read `checkpoint.sequence_ordinal` directly, so the arm cannot exist.

### IN-20 (NEW): `BoundedBodyError::TooLarge` always reports the 256 KB limit, even on the 10 MB path

**File:** `engine/src/client/mod.rs:26-30`, `engine/src/client/mod.rs:15-16`,
`engine/src/client/mod.rs:44-67`

**Issue:** `read_body_limited_with_limit` takes `max_bytes` as a parameter, but the `Display` impl
for `TooLarge` hardcodes `MAX_PROVIDER_RESPONSE_BODY_BYTES` (256 KB). `e831be3` added a second
caller using `MAX_MODELS_METADATA_BODY_BYTES` (10 MB), so a models-metadata overflow now renders as
"provider response exceeded maximum body limit of 262144 bytes" when the actual limit was
10485760 — a misleading diagnostic on the exact path the commit was written to widen. The
`openrouter.rs:393-396` call site happens to build its own correct message, which is why the defect
is latent rather than user-visible today.

**Fix:** carry the limit in the variant: `TooLarge { limit: usize }`.

### IN-21 (NEW, from prior WR-06's fix): checkpoint persistence errors are logged twice

**File:** `gateway/checkpoint_sink.go:107-110`, `gateway/checkpoint_sink.go:126-128`,
`gateway/checkpoint_sink.go:229-238`

**Issue:** `SaveCheckpoint` logs at `ERROR` on both the invalid-JSON path (107-110) and the insert
path (126-128), *and* returns the error; `loop()` then logs the same failure again at `WARN`
(231-237). Every failed checkpoint produces two log lines at two severities with the same
`trace_id`/`sequence_ordinal`, which will inflate alert counts and mislead anyone building on the
error rate.

**Fix:** log once. Either have `SaveCheckpoint` return the error silently and let the dispatcher own
the logging, or drop the dispatcher-level log.

### IN-22 (NEW): `CheckpointSnapshot::to_json` panics via `.expect` in the request path

**File:** `engine/src/workflow/events.rs:241-244`

**Issue:** `serde_json::to_string(self).expect("WorkflowContext checkpoint snapshot must serialize
as valid JSON")` runs inside the spawned workflow task (`main.rs:1902-1908`). A panic there aborts
the task, drops `tx`, and ends the client stream with no terminal event. Per
`rust-guidelines.md` M-PANIC-IS-STOP, a panic means "stop the program"; a serialization helper
should not be able to kill a request.

**Labelled not reproducible by reading, with the mechanism verified against the pinned dependency
rather than asserted from memory:** `Cargo.lock` pins `serde_json 1.0.151`, whose
`src/ser.rs:169-180` handles the value position as

```rust
fn serialize_f64(self, value: f64) -> Result<()> {
    match value.classify() {
        FpCategory::Nan | FpCategory::Infinite =>
            self.formatter.write_null(&mut self.writer).map_err(Error::io),
        _ => self.formatter.write_f64(&mut self.writer, value).map_err(Error::io),
    }
}
```

— i.e. a non-finite float in a **value** position serializes as `null`, it does **not** error. The
error path (`float_key_must_be_finite`, `src/ser.rs:1042-1045`) belongs to `MapKeySerializer`, which
applies only to floats used as **map keys**. `CheckpointSnapshot` has no map-keyed floats: every
float field (`CheckpointRetrievalSnapshot::{vector_weight, bm25_weight}`,
`CheckpointStructuredCitation::score`) is a struct field. No other error source was identified — all
remaining fields are plain owned types. So the `expect` appears unreachable at HEAD and this is
filed for the structural hazard only.

One second-order consequence worth noting: because non-finite floats become `null` rather than
failing, a NaN reranker `score` would be persisted silently as `"score": null` in
`workflow_checkpoints.context_snapshot` and would still pass the Go-side `json.Valid` guard at
`checkpoint_sink.go:105`. That is a provenance-fidelity gap, not a crash.

**Fix:** return `Result<String, serde_json::Error>` (or fall back to a minimal
`{"error":"snapshot_serialization_failed"}` literal, which also keeps the Go-side `json.Valid` guard
at `checkpoint_sink.go:105` satisfied).

### IN-23 (NEW): `7da662a`'s new graph timeout invariant has no negative test

**File:** `engine/src/main.rs:280-288`, `engine/src/tests.rs:315-360`

**Issue:** `7da662a` added the `graph_node_timeout_ms >= query_embedding + graph_operation` check to
`WorkflowSettings::validate()`, but the only test change was to `config_workflow_nested_env_overrides_match_contract`,
which merely **renumbered the fixture values** (`3333`/`4444`/`5555`/`6666`/`7777` →
`4444`/`3333`/`6666`/`7777`/`8888`) so the existing happy path would keep satisfying the new
inequality. No test asserts that a violating configuration is **rejected**. Nothing prevents the
check from being deleted or inverted without a test failing.

**Fix:** add a direct unit test.

```rust
#[test]
fn graph_node_timeout_below_component_sum_is_rejected() {
    let mut s = WorkflowSettings::default();
    s.query_embedding_timeout_ms = 10_000;
    s.graph_operation_timeout_ms = 4_000;
    s.graph_node_timeout_ms = 13_999;
    let err = s.validate().expect_err("must reject inverted graph timer");
    assert!(err.contains("graph_node_timeout_ms"));
}
```

### IN-24: `config/config.example.toml` documents a different generation model than `config/config.toml` ships

**File:** `config/config.example.toml:78`, `config/config.toml:41`

**Issue:** The example pins `generation_model = "openai/gpt-4o-mini"` while the shipped config pins
`"dots-studio/dots-3-note-preview:free"`. `fetch_and_validate_capabilities`
(`openrouter.rs:414-443`) hard-fails `prepare()` unless the configured model is present in the
OpenRouter `/models` list *and* advertises `response_format` / `json_schema` /
`structured_outputs`, so an operator who copies the example verbatim gets a startup-time preflight
failure if `gpt-4o-mini` ever stops advertising one of those. Documentation drift, not a defect —
recorded so the divergence is on the record rather than assumed intentional.

**Fix:** keep the example in sync with the shipped value, or add a comment explaining why they
differ.

---

_Reviewed: 2026-08-19T05:40:00Z (full re-derivation at HEAD `bb58a60`)_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
