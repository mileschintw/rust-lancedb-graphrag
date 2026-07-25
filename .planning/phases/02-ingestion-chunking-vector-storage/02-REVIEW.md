---
phase: 02-ingestion-chunking-vector-storage
reviewed: 2026-07-25T23:11:24Z
depth: standard
files_reviewed: 26
files_reviewed_list:
  - .gitignore
  - config/config.toml
  - config/config.dev.toml
  - config/config.verify.toml
  - engine/Cargo.toml
  - engine/Cargo.lock
  - engine/src/main.rs
  - engine/src/chunker/mod.rs
  - engine/src/chunker/tests.rs
  - engine/src/client/mod.rs
  - engine/src/client/tests.rs
  - engine/src/db/mod.rs
  - engine/src/db/tests.rs
  - engine/src/bin/inspect_lancedb.rs
  - gateway/go.mod
  - gateway/go.sum
  - gateway/main.go
  - gateway/main_test.go
  - gateway/db/schema.hcl
  - gateway/db/schema.sql
  - gateway/db/query.sql
  - gateway/db/query.sql.go
  - gateway/db/document_test.go
  - proto/lancet/v1/lancet.proto
  - verify-ingestion.sh
  - verify-live-evidence.sh
findings:
  critical: 4
  warning: 2
  info: 0
  total: 6
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-25T23:11:24Z
**Depth:** standard
**Files Reviewed:** 26
**Status:** issues_found

## Summary

The ingestion implementation compiles and its unit suites pass, but it is not safe to ship as reviewed. Four blockers affect replacement durability and the integrity/privacy of the live gate. Two additional warnings can leave PostgreSQL metadata permanently stale or accepted jobs stranded after restart.

Validation performed without reading runtime challenge/evidence contents or credentials:

- `cargo test --manifest-path engine/Cargo.toml`: passed (21 engine tests and 4 inspector-target tests).
- `go test ./...` from `gateway/`: passed.
- Git ignore metadata check: neither phase-local runtime JSON path is ignored.
- Shell execution could not be repeated in this Windows sandbox because the Bash service returned `E_ACCESSDENIED`; both scripts were still reviewed line by line.

## Narrative Findings (AI reviewer)

### Critical Issues

#### CR-01: Runtime challenge and evidence artifacts are not Git-ignored

**Classification:** BLOCKER
**Files:** `.gitignore:120-123`, `verify-live-evidence.sh:179`
**Issue:** The repository ignore rules end without entries for either phase-local runtime JSON artifact. The validator consumes only the challenge after success and leaves the evidence file in the worktree. The scripts merely verify that the files are untracked and unstaged at specific moments; a later `git add -A` can stage the retained evidence. This violates the explicit short-lived/private artifact contract and creates an avoidable disclosure path for challenge/evidence data.
**Fix:** Add exact phase-local ignore entries (including the hidden challenge) and remove both artifacts after successful validation, preferably from an EXIT cleanup that is enabled only once validation has completed. Also add a test that requires `git check-ignore` to succeed for both paths.

#### CR-02: Every security decision in the live gate disappears under Python optimization

**Classification:** BLOCKER
**Files:** `verify-live-evidence.sh:70-93`, `verify-ingestion.sh:72-77`, `verify-ingestion.sh:162-170`
**Issue:** Schema, challenge binding, UUID, freshness, provider/model, row-count, and stale-generation checks are implemented with Python `assert`. Python removes these statements when `PYTHONOPTIMIZE` is set or the interpreter is launched with `-O`; a direct probe confirmed that `python -O -c "assert False"` exits successfully. In that environment the validator can accept malformed, stale, replayed, or mismatched evidence as long as the few subsequently accessed fields parse. This defeats the gate's primary trust boundary.
**Fix:** Replace every security-relevant assertion with explicit validation that raises a dedicated exception or exits nonzero, and invoke Python in isolated mode (`-I`) so `PYTHON*` environment variables cannot weaken execution. Add negative tests under `PYTHONOPTIMIZE=1` for mismatched challenge, stale timestamps, extra/secret-bearing fields, and incorrect store counts.

#### CR-03: The LanceDB inspector fabricates the provider/model/staleness verdict

**Classification:** BLOCKER
**Files:** `engine/src/bin/inspect_lancedb.rs:99-124`, `verify-ingestion.sh:164-167`, `verify-ingestion.sh:190-191`
**Issue:** The inspector checks only that the `embedding_model` column has UTF-8 type, then emits the provider, locked model, and `stale_generation: false` as constants. It does not read node values, generation timestamps, content hashes, or uniqueness. The evidence writer likewise hardcodes `duplicate_generation: False`. Consequently the final gate can report the locked provider/model and “no stale/duplicate generation” for rows that contain a different model, stale values, or duplicates. A 2048-wide schema plus positive row count is not proof of those claims.
**Fix:** Query sanitized aggregates for the recorded UUID: distinct persisted model values, minimum/maximum ingestion timestamp, duplicate chunk/edge IDs, expected chunk-index cardinality, and generation identity. Derive provider/model, duplicate, and stale booleans from those results and fail closed when they cannot be proven. Do not select or emit raw content, chunk content, headers, or credentials.

#### CR-04: Real LanceDB write failures bypass rollback and can destroy the prior generation

**Classification:** BLOCKER
**File:** `engine/src/main.rs:424-453`, `engine/src/main.rs:568-572`, `engine/src/main.rs:656-660`
**Issue:** Rollback is invoked only when the synthetic fault injector returns an error after a boundary. Actual failures from deleting edges/nodes/documents or adding document/node/edge batches return immediately through `?`. For example, if the prior rows are deleted and `documents.add` or `nodes.add` fails, the previous completed generation is already gone and no captured version is restored. This directly violates the recoverable same-ID replacement contract and risks data loss.
**Fix:** Build all batches before mutation, execute the entire mutation sequence inside a result-producing block, and route every error after the version snapshots through `rollback_replacement`. Track which tables were mutated, preserve the original error, and add deterministic failing-table tests for every delete/add operation—not only post-write fault callbacks.

### Warnings

#### WR-01: Failed-ingest compensation reuses a canceled request context

**Classification:** WARNING
**Files:** `gateway/main.go:169-175`, `gateway/main.go:225-226`
**Issue:** When streaming fails because the client disconnects or the request timeout fires, `createDocument` calls compensation with the same canceled `r.Context()`. PostgreSQL immediately rejects the update, leaving the already-inserted row in `queued` even though the upload was not admitted. The log records the failure, but no later process reconciles this orphan.
**Fix:** Run compensation with a short bounded context detached from request cancellation, such as `context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)`. Add a handler test whose request context is canceled during `Ingest` and assert that the persisted row becomes terminal.

#### WR-02: Accepted queued jobs are discarded on shutdown and never recovered

**Classification:** WARNING
**Files:** `engine/src/main.rs:247-255`, `engine/src/main.rs:722-733`, `engine/src/main.rs:785-797`
**Issue:** The service acknowledges ingestion only after writing a staging row and enqueueing the job, but the biased shutdown branch exits before draining pending jobs. On restart, the status map and channel are recreated empty and staged rows are not scanned or re-enqueued. Those acknowledged uploads remain staged while PostgreSQL remains nonterminal; subsequent polling receives “status not found” from the engine and can never converge without manual intervention.
**Fix:** Either drain the accepted queue before shutdown or implement startup recovery that enumerates staged documents, reconstructs jobs with their filename/metadata, re-enqueues them, and restores queryable status. Persist enough staging metadata to make recovery deterministic, and add a restart test with at least one active and one pending job.

---

_Reviewed: 2026-07-25T23:11:24Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
