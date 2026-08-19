# Phase 05 Code Review Fix Report

**Phase:** 05-state-machine-workflow-events  
**Date:** 2026-08-19  
**Fix Scope:** Critical and Warning findings (`critical_warning`)  
**Status:** Complete  

---

## 1. Summary of Remediated Findings

| ID | Severity | Description | Target File(s) | Status | Commit |
|---|---|---|---|---|---|
| **CR-01** | Critical | `run_node` cancels workflow *before* emitting `NodeFailed`, poisoning delivery path | `engine/src/workflow/runner.rs` | Fixed | `ac3db6e` |
| **WR-01** | Warning | `dispatcher.Close()` unreachable due to `logger.Fatal` in `main` without graceful shutdown | `gateway/main.go` | Fixed | `e8982d0` |
| **WR-02** | Warning | Terminal-checkpoint failure suppresses client-visible `WorkflowCompleted` | `engine/src/workflow/runner.rs` | Fixed | `7ea20f2` |
| **WR-03** | Warning | `WorkflowSettings::validate()` cross-field retry invariants unchecked | `engine/src/main.rs`, `engine/src/tests.rs` | Fixed | `7da662a` |
| **WR-04** | Warning | Non-2xx chat response mapped indiscriminately to `ProviderError` causing useless retries on 400/401 | `engine/src/generation/openrouter.rs` | Fixed | `58cede3` |
| **WR-05** | Warning | `run_inline_prompt_generation_remainder` forwards empty evidence and drops cancel token | `engine/src/workflow/mod.rs` | Fixed | `0969a2b` |
| **WR-06** | Warning | Checkpoint persistence failures swallowed and `context_snapshot` unvalidated JSON | `gateway/checkpoint_sink.go` | Fixed | `8b692a5` |
| **WR-07** | Warning | Checkpoints submitted or retained after `Close()` silently lost | `gateway/checkpoint_sink.go` | Fixed | `71fad09` |
| **WR-08** | Warning | `PartialEq for GenerationRequest` misuses `f64::EPSILON` and ignores future fields | `engine/src/generation/mod.rs` | Fixed | `2a7c541` |
| **WR-09** | Warning | Sequence ordinals consumed on failed deliveries creating gaps | `engine/src/workflow/runner.rs` | Fixed | `5354d1e` |
| **WR-10** | Warning | `WorkflowEventSink::wrap_event` panics via `unreachable!()` on non-checkpoint event | `engine/src/workflow/runner.rs` | Fixed | `5354d1e` |
| **WR-11** | Warning | `d1_status` reflects unbounded client-supplied `session_id` into headers and logs | `engine/src/main.rs` | Fixed | `94275b6` |
| **WR-12** | Warning | `send_envelope` `capacity() > 0` fast path is a check-then-act race | `engine/src/workflow/runner.rs` | Fixed | `5354d1e` |
| **WR-13** | Warning | LanceDB schema drift remediation guidance placed after giant debug dumps | `engine/src/db/mod.rs` | Fixed | `4196dff` |
| **WR-14** | Warning | Gateway `database_url` empty string allows unconfigured startup | `gateway/main.go` | Fixed | `a007b89` |
| **WR-15** | Warning | `ReformulateQueryNode` accepts empty variants from reformulator without floor check | `engine/src/workflow/nodes/reformulate.rs`, `engine/src/tests/workflow_phase5.rs` | Fixed | `ccef730` |

---

## 2. Details of Applied Fixes

### CR-01: `run_node` NodeFailed Emission Before Cancellation
- Emitted `NodeFailed` event to `sink` *before* invoking `cancel.cancel()` across preparation, execution, and timeout error branches in `engine/src/workflow/runner.rs`.
- Preserved the underlying `NodeError` rather than discarding it with `?` or masking it as `Cancelled`.
- Verified timeout cancellation latching in `tests::workflow_phase5_timeout_cancels_stalled_provider`.

### WR-01: Gateway Graceful Shutdown
- Added `signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)` to `gateway/main.go`.
- Replaced ungraceful `logger.Fatal` server exit with `server.Shutdown` with a 15-second timeout, guaranteeing all deferred cleanup routines (`dispatcher.Close()`, `recCancel()`, `conn.Close()`, `pool.Close()`, `logger.Sync()`) run to completion.

### WR-02: Non-Blocking Terminal Checkpoint Failure
- Replaced early return on `send_checkpoint_or_error("terminal_success")` failure with a warning log, ensuring `WorkflowCompleted` event is delivered to the client stream even if the terminal checkpoint write fails.

### WR-03: Cross-Field Graph Node Timeout Invariant Validation
- Added cross-field validation to `WorkflowSettings::validate()` ensuring `graph_node_timeout_ms >= query_embedding_timeout_ms + graph_operation_timeout_ms`.
- Updated test configuration in `engine/src/tests.rs` to maintain the valid graph timer inequality.

### WR-04: Chat Completion Error Discrimination
- Updated `engine/src/generation/openrouter.rs` to map HTTP 5xx and 429 to `GenerationErrorKind::ProviderError` (retryable) while mapping HTTP 4xx client errors to `GenerationErrorKind::InvalidRequest` (fail-fast, no useless retries).

### WR-05: Remainder Generator Evidence and Cancellation Forwarding
- Updated `run_inline_prompt_generation_remainder` in `engine/src/workflow/mod.rs` to pass `ctx.evidence_blocks`, set `graph_facts`, forward the cancellation token `cancel`, and restrict retry attempts to transient/retryable errors (`Timeout`, `ProviderError`).

### WR-06: Checkpoint JSON Validation and Sink Error Handling
- Added `json.Valid([]byte(env.ContextSnapshot))` validation in `PostgresCheckpointSink.SaveCheckpoint` before executing SQL insert.
- Updated `CheckpointDispatcher.loop()` to log warnings on sink errors rather than discarding them silently.

### WR-07: Closed Dispatcher RetainPending Rejection
- Added check `if d.closed { return errors.New("checkpoint dispatcher is closed") }` under mutex lock in `CheckpointDispatcher.RetainPending`.

### WR-08: Exact Bitwise Float Equality in PartialEq
- Replaced inaccurate `(self.graph_weight - other.graph_weight).abs() < f64::EPSILON` with `graph_weight.to_bits() == other.graph_weight.to_bits()` and explicit struct destructuring in `PartialEq for GenerationRequest`.

### WR-09, WR-10, WR-12: Event Sink Concurrency & Terminal Delivery
- Removed check-then-act `capacity() > 0` bypass in `send_envelope` and `flush_pending_checkpoints`.
- Renamed `wrap_event` to `wrap_checkpoint_event` and removed the `unreachable!()` panic on non-checkpoint events.
- Added `send_terminal_event` to ensure `WorkflowCompleted` is always delivered over the client channel `tx` even when internal cancellation has triggered.

### WR-11: Trailing Session ID Bounding and Sanitization
- Added `sanitize_header_value` in `engine/src/main.rs` to filter non-ASCII graphic characters and bound length to 128 characters before reflection in `x-lancet-*` headers and log warnings.

### WR-13: LanceDB Schema Drift Remediation Guidance Ordering
- Moved remediation guidance to the front of the error message before the verbose schema fields dump in `engine/src/db/mod.rs`.

### WR-14: Database URL Validation
- Added check `strings.TrimSpace(cfg.Gateway.DatabaseURL) == ""` in `gateway/main.go:loadConfig` to reject unconfigured database URLs at gateway startup.

### WR-15: Reformulation Non-Empty Floor Enforcement
- Enforced `variants.is_empty()` check in `ReformulateQueryNode` to return `NodeErrorKind::InputValidation` when a query reformulator produces 0 variants.
- Added regression test `zero_variants_are_rejected_before_retrieval` in `engine/src/tests/workflow_phase5.rs`.

---

## 3. Verification Suite Results

### Rust Engine (`cargo test`)
```
test result: ok. 126 passed (lib); 18 passed (bin inspect_lancedb); 9 passed (tests/config_startup.rs); 1 passed (bin/seed_rag_fixture); 0 failed; finished in 32.80s
```

### Go Gateway (`go test ./...`)
```
ok  	github.com/lancet/gateway	9.142s
ok  	github.com/lancet/gateway/db	(cached)
```
