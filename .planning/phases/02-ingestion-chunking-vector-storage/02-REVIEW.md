---
phase: 02-ingestion-chunking-vector-storage
reviewed: 2026-07-26T07:19:32Z
depth: deep
files_reviewed: 13
files_reviewed_list:
  - .gitignore
  - engine/src/inspect_lancedb_tests.rs
  - engine/src/bin/inspect_lancedb.rs
  - engine/src/client/mod.rs
  - engine/src/client/tests.rs
  - engine/src/main.rs
  - engine/src/tests.rs
  - gateway/main_test.go
  - gateway/main.go
  - scripts/phase02_live_evidence.py
  - scripts/test_phase02_live_evidence.py
  - verify-ingestion.sh
  - verify-live-evidence.sh
findings:
  critical: 6
  warning: 4
  info: 0
  total: 10
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-26T07:19:32Z
**Depth:** deep
**Files Reviewed:** 13
**Status:** issues_found

## Narrative Findings (AI reviewer)

### Summary

The deep review traced ingestion admission from the Go HTTP handler through the gRPC stream and Rust queue, terminal PostgreSQL reconciliation, LanceDB replacement/rollback, durable inspection, and the challenge-bound live-evidence gate. Six blockers and four warnings were found.

Mechanical checks passed for `cargo fmt`, all 38 Rust tests across the engine and inspector, the optimized isolated Python suite, all Go tests, and `go vet`. Those suites do not exercise the blocker paths below. Three defects were reproduced directly: evidence bound to a one-year-old challenge was accepted, `verify-ingestion.sh` deleted a caller-owned sample on an early failure, and `inspect_lancedb --lancedb-path ...` failed from a config-less directory because it still loaded configuration. `cargo clippy --all-targets -- -D warnings` failed.

### Critical Issues

#### CR-01: A lost gRPC acknowledgement is misclassified as a rejected ingestion

**Classification:** BLOCKER

**File:** `gateway/main.go:149-150, 228-235`; `engine/src/main.rs:285-303`

**Issue:** The Rust service persists staging data, inserts the in-memory `queued` status, and sends the job before returning its response. If that response is lost, times out, or is canceled after admission, `CloseAndRecv` returns an error even though the worker owns the job. The gateway treats every such error as definitive non-admission and immediately writes PostgreSQL `failed`. The worker can then complete LanceDB indexing while PostgreSQL remains terminally failed, and later GETs will never poll the engine because only `queued`/`processing` rows are reconciled.

**Fix:**

```go
// Return a typed admission result from grpcEngine.Ingest.
reply, err := stream.CloseAndRecv()
if err != nil {
	return &AdmissionError{Err: err, Ambiguous: true}
}
if !reply.GetSuccess() || reply.GetDocumentId() != id {
	return &AdmissionError{Err: errors.New("engine rejected admission"), Definitive: true}
}
return nil
```

For an ambiguous error, use a detached bounded context to query an authoritative engine admission/status endpoint with bounded retries. Return an accepted polling location when the job exists; mark PostgreSQL failed only after a definitive rejection/non-admission result. Add a test where the engine records `queued` but the final acknowledgement is lost and prove PostgreSQL is not changed to `failed`.

#### CR-02: Failed compensation permanently strands PostgreSQL in `queued`

**Classification:** BLOCKER

**File:** `gateway/main.go:170-178, 228-235, 251-255`

**Issue:** Compensation is a single best-effort `UpdateStatus` call. On a transient PostgreSQL error or timeout, the code only logs and returns 429/502. The row remains `queued`, there is no retry/outbox/reconciler, and a later GET polls an engine job that was never admitted; an engine `NotFound` is converted to another 502 without repairing the row. This directly contradicts the function's claim that it prevents indefinitely queued metadata.

**Fix:** Persist a compensation/reconciliation intent durably in the same transaction that inserts the queued row, clear it only after authoritative engine admission, and process outstanding intents until the PostgreSQL terminal transition succeeds. At minimum, add bounded retries plus a background reconciler for queued rows and handle authoritative engine `NotFound` by conditionally transitioning the row to `failed`. Add a test with `updateErr` set and prove eventual terminal convergence rather than only checking the HTTP response.

#### CR-03: The gate accepts evidence bound to an arbitrarily old challenge

**Classification:** BLOCKER

**File:** `scripts/phase02_live_evidence.py:185-196, 271-277`

**Issue:** `validate_challenge` rejects future issue times but never rejects old ones. Evidence freshness is measured only from `generated_at`; therefore an old challenge and old durable ingestion can be replayed by issuing fresh `run_started_at`/`generated_at` values. A direct reproduction passed validation with `issued_at=2025-07-26` and current 2026 evidence, violating the fresh post-change challenge and replay-resistant acceptance contract.

**Fix:**

```python
MAX_CHALLENGE_AGE = dt.timedelta(minutes=30)

current = now or dt.datetime.now(UTC)
require(issued_at <= current + MAX_FUTURE_SKEW, "challenge.issued_at is in the future")
require(current - issued_at <= MAX_CHALLENGE_AGE, "challenge.issued_at is stale")
```

Also bound the complete run window (`generated_at - issued_at`) to the allowed gate duration and add optimized isolated tests for a stale challenge paired with otherwise fresh, valid evidence.

#### CR-04: The live runner deletes caller-owned input files

**Classification:** BLOCKER

**File:** `verify-ingestion.sh:18-24, 37-43, 115-118`

**Issue:** Any positional argument is assigned to `sample_file`, and the unconditional EXIT trap deletes every non-empty `sample_file`. A caller-supplied document is therefore destroyed on success or failure. This was reproduced by invoking the script with a reviewer-created input while omitting the API key: the script exited at the credential check and still removed the supplied file.

**Fix:**

```bash
sample_file=""
sample_is_temporary=false

cleanup() {
  if "$sample_is_temporary" && [[ -n "$sample_file" ]]; then
    rm -f -- "$sample_file"
  fi
  # clean up only other script-owned paths
}

if [[ -z "$sample_file" ]]; then
  sample_file="$(mktemp "./.live-ingestion-sample.XXXXXX")"
  sample_is_temporary=true
fi
```

Add a shell-level regression that passes a caller-owned sample, forces an early failure, and verifies the file remains byte-for-byte intact.

#### CR-05: `--lancedb-path` still requires unrelated configuration

**Classification:** BLOCKER

**File:** `engine/src/bin/inspect_lancedb.rs:342-348`

**Issue:** `path.unwrap_or(settings_path()?)` eagerly evaluates `settings_path()` even when `--lancedb-path` was supplied. Running the built inspector from a directory without `config/config.toml` and passing an explicit database path failed with `configuration file "config/config" not found`. The advertised explicit-path mode is unusable in precisely the isolated diagnostic context it is meant to support.

**Fix:**

```rust
let database_path = match path {
    Some(path) => path,
    None => settings_path()?,
};
let database = DatabaseManager::initialize(&database_path).await?;
```

Add a process-level test that runs from a config-less temporary working directory with `--lancedb-path` and verifies the failure, if any, comes from the explicit store's data invariants rather than configuration lookup.

#### CR-06: The durable inspector accepts embeddings with invalid child values

**Classification:** BLOCKER

**File:** `engine/src/bin/inspect_lancedb.rs:122-138`

**Issue:** `FixedSizeListArray::null_count()` checks only parent list slots. The canonical Arrow schema makes the Float32 child field nullable, so a 2048-wide list containing null child elements has parent `null_count() == 0` and passes the inspector. Non-finite float values are likewise never checked. The final gate can therefore attest a corrupt/non-usable embedding generation as valid.

**Fix:**

```rust
let values = embeddings
    .values()
    .as_any()
    .downcast_ref::<Float32Array>()
    .ok_or_else(|| "LanceDB embedding child values have an unexpected type".to_owned())?;
if values.null_count() != 0 {
    return Err("LanceDB embedding vectors contain null elements".to_owned());
}
if values.iter().flatten().any(|value| !value.is_finite()) {
    return Err("LanceDB embedding vectors contain non-finite elements".to_owned());
}
```

Extend the real-LanceDB fixtures with null-child and non-finite vectors and require both cases to fail closed.

### Warnings

#### WR-01: Schema-field `expect` calls can bypass rollback and kill the worker

**Classification:** WARNING

**File:** `engine/src/main.rs:528-533, 594-600, 642-651`

**Issue:** Missing node/edge fields panic instead of returning through the replacement operation's `Result`. If schema drift or corruption appears after startup, the panic bypasses `rollback_replacement`, leaves the active status in `processing`, and terminates the sole worker task.

**Fix:** Replace each `expect` with a schema-derived helper returning `Result<ArrayRef, String>` and propagate with `?`, ensuring every post-version-capture schema failure reaches the rollback funnel. Add a fault test for schema-field lookup failure.

#### WR-02: Gateway trusts gRPC response identity without validation

**Classification:** WARNING

**File:** `gateway/main.go:149-150, 252-259`

**Issue:** The ingestion response is discarded, and status polling does not verify that `state.DocumentId` equals the requested PostgreSQL ID. A malformed or misrouted engine response can therefore be applied to the wrong document.

**Fix:** Require ingestion `success == true` and matching `document_id`; require every status response's `document_id` to equal `doc.ID` before persisting status/count. Return 502 on mismatch and add adversarial mismatch tests.

#### WR-03: The generic `bin/` ignore hides future Rust source binaries

**Classification:** WARNING

**File:** `.gitignore:71-77`

**Issue:** The unanchored `bin/` rule matches `engine/src/bin/`. The current inspector is tracked, but any newly created Rust binary under that standard Cargo directory is silently ignored; `git check-ignore -v --no-index engine/src/bin/future_inspector.rs` resolves to this rule.

**Fix:** Remove the redundant rule or anchor it to the repository root as `/bin/`. Keep the explicit `gateway/gateway` and `gateway/gateway.exe` rules for Go outputs.

#### WR-04: The all-target Rust lint gate is red

**Classification:** WARNING

**File:** `engine/src/bin/inspect_lancedb.rs:1-2`; `engine/src/client/tests.rs:101-106`

**Issue:** `cargo clippy --manifest-path engine/Cargo.toml --all-targets -- -D warnings` exits 101. Re-including `db/mod.rs` as a private binary module makes `EntityResolver` and `ExactMatchResolver` dead code in the inspector target, and the mock response builder triggers `clippy::manual-repeat-n`. A warnings-as-errors quality gate cannot pass.

**Fix:** Expose the shared database module through a library target and import it from both binaries instead of recompiling the whole module with `#[path]`. Replace `repeat(...).take(2048)` with `std::iter::repeat_n("0.25", 2048)`, then rerun the exact all-target command.

---

_Reviewed: 2026-07-26T07:19:32Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
