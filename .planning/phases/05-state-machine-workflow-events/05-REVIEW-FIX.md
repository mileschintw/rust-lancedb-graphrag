# Phase 5: Code Review Fix Report

**Date:** 2026-08-19  
**Scope:** critical_warning (13 Warnings addressed, 0 Criticals)  
**Status:** All issues resolved

---

## Fixed Issues

### WR-01: send_terminal_event delivery hangs indefinitely if consumer stops polling
- **Files Modified:** `engine/src/workflow/runner.rs`
- **Fix Details:** Wrapped both `flush_pending_checkpoints(&uncancelled)` and `self.tx.reserve()` in 5-second `tokio::time::timeout` blocks to ensure terminal completion guarantees under connection drops.
- **Commit:** `0c96720`

### WR-02: emit_terminal_once early return on final_answer delivery error
- **Files Modified:** `engine/src/workflow/runner.rs`
- **Fix Details:** Replaced early `is_err()` return on `final_answer` delivery with `let _ = ...;`, ensuring the terminal `WorkflowCompleted` event is always sent to close the stream.
- **Commit:** `0c96720`

### WR-03: wrap_next_event eagerly allocates sequence ordinals before reserve
- **Files Modified:** `engine/src/workflow/runner.rs`
- **Fix Details:** Shifted event sequence ordinal assignment to lazy evaluation inside `send_event_lazy` only after `self.tx.reserve().await` yields a valid send permit.
- **Commit:** `0c96720`

### WR-04: ListenAndServe error path calls stop() then exits 0 from main()
- **Files Modified:** `gateway/main.go`
- **Fix Details:** Refactored `main()` into `run() error` with explicit server error channel, ensuring fatal listen errors trigger full deferred cleanup and exit with non-zero status code (`os.Exit(1)`).
- **Commit:** `fe83e71`

### WR-05: Hardcoded database_url with sslmode=disable committed to git
- **Files Modified:** `config/config.toml`, `config/config.example.toml`, `gateway/main.go`, `gateway/main_test.go`
- **Fix Details:** Blanked `database_url` in committed config files, added explicit `gateway.database_url` non-empty requirement in `loadConfig()`, and added validation rejecting `sslmode=disable` when `LANCET_ENV=prod`.
- **Commit:** `fe83e71`

### WR-06: WorkflowSettings::validate() does not enforce generation_node_timeout_ms >= 2 * provider timeout
- **Files Modified:** `engine/src/main.rs`, `engine/src/tests.rs`
- **Fix Details:** Added `validate_against_provider(&self, generation_timeout_secs: u64)` to `WorkflowSettings` asserting the 2x provider retry attempt budget invariant, with comprehensive unit tests.
- **Commit:** `c9278c0`

### WR-07: run_inline_prompt_generation_remainder silently swallows node_err on send_event_or_cancel failure
- **Files Modified:** `engine/src/workflow/mod.rs`, `engine/src/main.rs`
- **Fix Details:** Replaced `?` with non-overwriting `let _ = ...;` when emitting `node_failed` events in remainder generation, preserving the root causal `node_err` on channel failure, and assigned `deps.graph_weight` to `GenerationRequest`.
- **Commit:** `34b7185`

### WR-08: CheckpointDispatcher error handling drops envelopes on sink error without logger or drop counter
- **Files Modified:** `gateway/checkpoint_sink.go`
- **Fix Details:** Added `logger *zap.Logger` and `dropped atomic.Uint64` counter to `CheckpointDispatcher`, added `NewCheckpointDispatcherWithLogger`, and added bounded 3-attempt retry before dropping.
- **Commit:** `fe83e71`

### WR-09: CheckpointDispatcher.Close() unbounded drain loop
- **Files Modified:** `gateway/checkpoint_sink.go`, `gateway/main_test.go`
- **Fix Details:** Implemented `CloseWithTimeout(budget time.Duration) error` to bound dispatcher shutdown to 10 seconds, preventing gateway shutdown hangs.
- **Commit:** `fe83e71`

### WR-10: DefaultHasher is not specified / randomized across runs
- **Files Modified:** `engine/Cargo.toml`, `engine/Cargo.lock`, `engine/src/workflow/nodes/retrieve.rs`, `engine/src/main.rs`, `engine/src/bin/seed_rag_fixture.rs`, `engine/src/tests.rs`
- **Fix Details:** Replaced standard library `DefaultHasher` with deterministic cryptographic `blake3` hashing for `result_hash` and `content_hash`.
- **Commit:** `1ef8d4c`, `158a83a`, `5f12870`

### WR-11: Duplicate and inconsistent SQL literal escaping logic
- **Files Modified:** `engine/src/graph/mod.rs`, `engine/src/main.rs`, `engine/src/tests.rs`
- **Fix Details:** Unified all SQL string literal escaping to `graph::escape_sql_literal`, removed duplicate `sql_string`, and added SQL dialect contract documentation.
- **Commit:** `69bf224`, `5f12870`

### WR-12: run_node: send_checkpoint_or_error with ? aborts successful node without NodeFailed event
- **Files Modified:** `engine/src/workflow/runner.rs`
- **Fix Details:** Caught checkpoint errors in `run_node` and emitted a corresponding `events::node_failed` before returning `Err(err)`.
- **Commit:** `0c96720`

### WR-13: schema_drift_fails_database_initialization does not verify remediation placement
- **Files Modified:** `engine/src/db/tests.rs`
- **Fix Details:** Added assertion verifying `remediation_pos < details_pos` to guarantee human-actionable remediation instructions appear before the voluminous schema dump.
- **Commit:** `486bc51`

---

## Verification Results

1. **Rust Test Suite:**
   ```
   cargo test --manifest-path engine/Cargo.toml --locked
   test result: ok. 128 passed; 0 failed; 0 ignored; finished in 32.87s
   test result: ok. 18 passed; 0 failed; 0 ignored; finished in 1.59s
   test result: ok. 9 passed; 0 failed; 0 ignored; finished in 1.15s
   ```

2. **Go Test Suite:**
   ```
   go test ./...
   ok      github.com/lancet/gateway       10.943s
   ok      github.com/lancet/gateway/db    (cached)
   ```
