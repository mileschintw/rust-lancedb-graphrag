---
title: "ADR-02-004: Deferral of Phase 02 Flaws to Final Phase for MVP Focus"
status: accepted
date: 2026-07-30
decider: Miles Chin
scope: Phase 02 Ingestion, Chunking & Vector Storage; subsequent MVP phases up to final hardening phase
source_material:
  - .planning/phases/02-ingestion-chunking-vector-storage/02-REVIEW.md
  - .planning/phases/02-ingestion-chunking-vector-storage/02-VERIFICATION.md
supersedes: none
superseded_by: none
---

# Purpose

This ADR records the decision to treat all currently open Phase 02 flaws (CR-01 through CR-04, WR-01 through WR-03, and the associated verification gaps) as accepted technical debt, deferred until the final hardening phase of the MVP. The primary goal of the project at this stage is to prove the possibility of all happy-path functions end-to-end before investing effort in durability, recovery, verification integrity, or failure-path correctness. The current Phase 02 target, which requires full trustworthy state across all restart, rollback, admission failure, and approval paths, is explicitly judged too strict for an early MVP. Deferred items will be revisited only after all must-have functions are implemented, and each will carry tracking, constraints, and escalation triggers. New flaws discovered during subsequent phases will be written down and deferred, with at most a few rounds of unit tests written for TDD purposes.

# Decision Summary

| ID | Finding | Decision | Priority | Target |
|---|---|---|---|---|
| CR-01 | Completed canonical ingestion can be downgraded to failed after engine restart | Defer | P1 | Final hardening phase |
| CR-02 | Rollback failure destroys replay state and can leave partial canonical data terminally failed | Defer | P1 | Final hardening phase |
| CR-03 | Failed admission can be stranded queued without durable reconciliation intent | Defer | P1 | Final hardening phase |
| CR-04 | Evidence helper forges human approval when approval flag omitted | Defer | P2 | Final hardening phase |
| WR-01 | Test cleanup can delete another process's fixtures and overwrite caller-owned files | Defer | P2 | Final hardening phase |
| WR-02 | Empty uploads become durable failed jobs and misleading 502 response | Defer | P2 | Final hardening phase |
| WR-03 | Cross-runtime recovery tests can hang indefinitely on failure | Defer | P3 | Final hardening phase |
| VER-16 | Completed canonical state not discoverable as completed after engine restart | Defer | P1 | Final hardening phase |
| VER-19 | Live-evidence fixtures not process-owned; full optimized suite fails | Defer | P3 | Final hardening phase |
| VER-20 | Human disclosure approval is forgeable via CLI default | Defer | P2 | Final hardening phase |

# Findings to Ship

None. All items are deferred.

# Findings Deferred, Rejected, or Accepted As-Is

## CR-01: Completed canonical ingestion can be downgraded to failed after engine restart

**Decision:** Defer.

**Problem:**
Successful replacement deletes the durable staging row before the worker publishes `completed` into the process-local `DashMap`. `get_ingestion_status` consults only that volatile map and the staging table; it never checks canonical documents or nodes. If the engine restarts before the gateway polls, the status RPC returns `NotFound`, and the gateway irreversibly transitions the PostgreSQL row to `failed` even though the canonical LanceDB generation completed successfully. (`engine/src/main.rs:508-538`, `engine/src/main.rs:902-904`, `engine/src/main.rs:1045-1053`, `gateway/main.go:562-582`)

**Decision rationale:**
For an MVP in a single-operator, local development environment, the happy path (upload -> process -> store) works. The failure mode requires a restart between canonical commit and gateway poll, which is rare in controlled development. Fixing this requires a durable terminal outcome state machine, which is significant work. The current phase goal is too strict for MVP speed.

**Minimum guardrail to ship now:**
- Document that engine restarts may cause completed ingestions to appear as failed.
- Avoid automated restarts during active ingestion in development.

**Known risk:**
- Likelihood now: Low
- Impact if realized: Medium
- Residual exposure: Completed work may be marked failed, requiring manual reconciliation.

**Current operating constraints:**
- Single-operator use only.
- No automated engine restarts during ingestion.
- Treat PostgreSQL status as advisory, not authoritative.

**Tracking:** DEBT-CR-01

**Target:**
Final hardening phase, before any production or multi-user exposure.

**Escalation trigger:**
- Engine restarts become frequent or automated.
- Multi-user or shared deployment begins.
- Data integrity issues are observed in practice.

**Future acceptance criteria:**
- Status RPC checks canonical document/node state after staging absence.
- Cross-runtime regression test passes: complete canonical mutation, restart Rust before gateway poll, assert PostgreSQL converges to completed.

## CR-02: Rollback failure destroys replay state and can leave partial canonical data terminally failed

**Decision:** Defer.

**Problem:**
`rollback_replacement` records errors from `restore_version` calls but attempts to delete staging regardless. The caller then handles every processing error with another unconditional staging deletion and publishes terminal `failed` when deletion succeeds. If any canonical table restoration fails while another succeeds, the durable replay row is removed while documents, nodes, and edges represent different generations. (`engine/src/main.rs:629-667`, `engine/src/main.rs:1056-1079`)

**Decision rationale:**
This is a failure-path defect. In MVP development, the happy path is the priority. Rollback failures during replacement are edge cases that can be addressed after core functionality is proven.

**Minimum guardrail to ship now:**
- Log rollback errors verbosely for manual inspection.
- Do not rely on automatic recovery from rollback failures.

**Known risk:**
- Likelihood now: Low
- Impact if realized: High
- Residual exposure: Partial canonical data may be terminally marked failed with no replay path.

**Current operating constraints:**
- Monitor logs during replacement operations.
- Manually verify canonical state after any rollback error.

**Tracking:** DEBT-CR-02

**Target:**
Final hardening phase.

**Escalation trigger:**
- Replacement operations become frequent.
- Automated testing begins to exercise rollback paths.
- Data corruption is observed.

**Future acceptance criteria:**
- Staging is not deleted when any canonical restore fails.
- Worker skips generic staging deletion and terminal publication for incomplete rollback.
- Injectable `restore_version` failure test proves staging remains and restarted worker can replay to consistent generation.

## CR-03: Failed admission can be stranded queued without durable reconciliation intent

**Decision:** Defer.

**Problem:**
`compensateFailedIngest` attempts `CreateReconciliationIntent` once and discards its error, then makes only five synchronous status-update attempts. A PostgreSQL interruption can make both the intent insert and all five updates fail, leaving a durable queued document with no reconciliation intent for the background claimant. (`gateway/main.go:275-319`)

**Decision rationale:**
This requires a database interruption during admission compensation, which is uncommon in local development. The happy path does not exercise this. Reconciliation design promises convergence independent of polling, but for MVP, polling is acceptable.

**Minimum guardrail to ship now:**
- Periodically poll for queued documents without intents during development.
- Manually inspect for stranded rows.

**Known risk:**
- Likelihood now: Low
- Impact if realized: Medium
- Residual exposure: Queued documents may never be processed or marked failed.

**Current operating constraints:**
- Single PostgreSQL instance, no high-availability setup.
- Manual monitoring of queued documents.

**Tracking:** DEBT-CR-03

**Target:**
Final hardening phase.

**Escalation trigger:**
- Database reliability issues arise.
- Background reconciliation becomes critical for operations.
- Automated deployment begins.

**Future acceptance criteria:**
- Queued document and reconciliation obligation are created atomically, or durable intent is confirmed before compensation exits.
- Regression test combines intent failure with five update failures, restores database, runs reconciler without GET, and asserts convergence to failed.

## CR-04: Evidence helper forges human approval when approval flag omitted

**Decision:** Defer.

**Problem:**
`build_attestation` and CLI argument default `human_approved` to true. `--human-review-approved` is a `store_true` argument whose default is already true, making omission indistinguishable from explicit approval. The success-path test invokes the gate without the flag and expects attestation retention, codifying the bypass. (`scripts/phase02_live_evidence.py:616-620`, `scripts/phase02_live_evidence.py:669-676`, `scripts/phase02_live_evidence.py:761-765`, `scripts/test_phase02_live_evidence.py:699-758`)

**Decision rationale:**
For a single-operator MVP, human approval is performed by the operator. The forgeable default does not introduce external risk. Privacy and compliance hardening are final-phase concerns.

**Minimum guardrail to ship now:**
- Operator must consciously review disclosures; do not rely on attestation as proof of review.

**Known risk:**
- Likelihood now: Low
- Impact if realized: Medium
- Residual exposure: Attestations may claim human approval that did not occur.

**Current operating constraints:**
- Single operator.
- No external parties rely on attestation provenance.

**Tracking:** DEBT-CR-04

**Target:**
Final hardening phase, before any compliance or multi-user use.

**Escalation trigger:**
- Attestations are used for external validation.
- Multiple operators or automated pipelines use the tool.

**Future acceptance criteria:**
- Default `human_approved` to false in function and parser.
- Reject attestation construction without explicit flag.
- Negative gate test proves omission preserves evidence and creates no attestation.

## WR-01: Test cleanup can delete another process's fixtures and overwrite caller-owned files

**Decision:** Defer.

**Problem:**
`tearDownClass` deletes every `.phase02-live-test-*` entry in the shared scripts directory. Concurrent test runs can delete each other's fixtures, and leftover matching directories cause `unlink` failures. The regression test removes its file via `addCleanup` before class teardown, so it never tests the dangerous sweep. Fixed filenames also overwrite pre-existing files. (`scripts/test_phase02_live_evidence.py:165-170`, `scripts/test_phase02_live_evidence.py:640-655`, `scripts/test_phase02_live_evidence.py:670-704`, `scripts/test_phase02_live_evidence.py:760-765`)

**Decision rationale:**
Test reliability issue, not runtime. MVP development can proceed with careful test execution (e.g., sequential runs). Full deterministic test suite is a hardening goal.

**Minimum guardrail to ship now:**
- Run tests sequentially, not in parallel.
- Clean workspace before test runs.

**Known risk:**
- Likelihood now: Medium
- Impact if realized: Low
- Residual exposure: Test failures and fixture corruption in shared environments.

**Current operating constraints:**
- Sequential test execution only.
- No concurrent test processes.

**Tracking:** DEBT-WR-01

**Target:**
Final hardening phase.

**Escalation trigger:**
- CI/CD pipelines are introduced.
- Multiple developers run tests concurrently.

**Future acceptance criteria:**
- Class-wide glob removed.
- Fixtures allocated under process/test-specific `TemporaryDirectory`.
- Full suite passes with foreign matching fixtures present.

## WR-02: Empty uploads become durable failed jobs and misleading 502 response

**Decision:** Defer.

**Problem:**
Go client sends first metadata-bearing stream frame only when reader yields bytes. Empty upload closes zero-message stream, which Rust rejects as `InvalidArgument("empty ingestion stream")`. HTTP handler does not reject zero-byte multipart file before inserting, so client input error creates queued row, compensates to failed, and returns 502 as if engine unavailable. (`gateway/main.go:208-249`, `gateway/main.go:512-545`, `engine/src/main.rs:457-483`)

**Decision rationale:**
Edge case in input validation. Happy path uses non-empty files. Can be addressed during hardening.

**Minimum guardrail to ship now:**
- Document that empty uploads are not supported.
- Client-side validation to prevent empty submissions.

**Known risk:**
- Likelihood now: Low
- Impact if realized: Low
- Residual exposure: Confusing error responses for invalid input.

**Current operating constraints:**
- Users must provide non-empty files.

**Tracking:** DEBT-WR-02

**Target:**
Final hardening phase.

**Escalation trigger:**
- Public API exposure.
- Client integrations are built.

**Future acceptance criteria:**
- HTTP 400 for zero-byte uploads before insert, or explicit support with first-frame metadata.
- Handler and gRPC-stream regressions for chosen contract.

## WR-03: Cross-runtime recovery tests can hang indefinitely on failure

**Decision:** Defer.

**Problem:**
Multiple Rust test and fixture loops poll state or stop files without deadline. D04 fixture's stop-file watcher starts after unbounded pre-server state loop. If startup never reaches serving, Go test fails bounded ping loop but deferred `cmd.Wait()` can block forever because stop file cannot affect unlaunched watcher. (`engine/src/tests.rs:731-735`, `engine/src/tests.rs:752-755`, `engine/src/tests.rs:795-799`, `engine/src/tests.rs:1422-1465`, `engine/src/tests.rs:1490-1497`, `gateway/main_test.go:1166-1170`, `gateway/main_test.go:1219-1223`)

**Decision rationale:**
Test infrastructure issue. Does not affect runtime. MVP development can tolerate occasional test hangs.

**Minimum guardrail to ship now:**
- Run tests with external timeouts (e.g., CI timeout).

**Known risk:**
- Likelihood now: Low
- Impact if realized: Low
- Residual exposure: Test suite hangs requiring manual intervention.

**Current operating constraints:**
- Manual test execution with supervision.

**Tracking:** DEBT-WR-03

**Target:**
Final hardening phase.

**Escalation trigger:**
- Automated testing is adopted.
- Test suite becomes part of CI.

**Future acceptance criteria:**
- All polling loops wrapped in `tokio::time::timeout`.
- Stop/cancellation observation launched before recovery waits.
- Go child process started with context deadline and bounded wait/kill fallback.

## VER-16: Completed canonical state not discoverable as completed after engine restart

**Decision:** Defer.

**Problem:**
This is the verification-level restatement of CR-01. The truth "A completed canonical ingestion remains discoverable as completed after an engine restart until PostgreSQL converges" failed because success deletes durable staging before publishing completion only to process-local registry. After restart, status checks only empty registry and staging table, returns NotFound, and gateway persists failed despite canonical LanceDB rows.

**Decision rationale:**
Same as CR-01. Deferred to final phase.

**Minimum guardrail to ship now:**
- Same as CR-01.

**Known risk:**
- Same as CR-01.

**Current operating constraints:**
- Same as CR-01.

**Tracking:** DEBT-CR-01

**Target:**
Final hardening phase.

**Escalation trigger:**
- Same as CR-01.

**Future acceptance criteria:**
- Same as CR-01.

## VER-19: Live-evidence fixtures not process-owned; full optimized suite fails

**Decision:** Defer.

**Problem:**
Truth "Live-evidence fixtures are process-owned and the full optimized suite passes" failed. Class-wide `.phase02-live-test-*` sweep remains. Verifier's full run executed 20 tests and ended with five errors, including PermissionError when tearDownClass tried Path.unlink on matching directory. Contradicts Plan 02-27 and ADR-02-003 D-07.

**Decision rationale:**
Same as WR-01. Test infrastructure debt.

**Minimum guardrail to ship now:**
- Same as WR-01.

**Known risk:**
- Same as WR-01.

**Current operating constraints:**
- Same as WR-01.

**Tracking:** DEBT-WR-01

**Target:**
Final hardening phase.

**Escalation trigger:**
- Same as WR-01.

**Future acceptance criteria:**
- Same as WR-01.

## VER-20: Human disclosure approval is forgeable via CLI default

**Decision:** Defer.

**Problem:**
Truth "Human disclosure approval is explicit, non-forgeable, and attached only after the blocking checkpoint" failed. CLI and function defaults fabricate approval when flag is omitted.

**Decision rationale:**
Same as CR-04.

**Minimum guardrail to ship now:**
- Same as CR-04.

**Known risk:**
- Same as CR-04.

**Current operating constraints:**
- Same as CR-04.

**Tracking:** DEBT-CR-04

**Target:**
Final hardening phase.

**Escalation trigger:**
- Same as CR-04.

**Future acceptance criteria:**
- Same as CR-04.

# Exit Conditions

The scope of this ADR is complete when:

1. All deferred items are recorded in a central debt register with tracking IDs, constraints, and escalation triggers.
2. The project roadmap explicitly notes that Phase 02 is complete at MVP level with known debt, and full durable correctness is deferred.
3. The final hardening phase is scheduled and includes all DEBT-CR-* and DEBT-WR-* items.
4. No placeholder marked `[TODO]` remains in this ADR.

# Review Triggers

Review this ADR before any of the following:

- Transition from single-operator local development to multi-user or shared deployment.
- Introduction of automated testing or CI/CD pipelines.
- Any production or external exposure of the system.
- Data integrity issues observed in practice.
- Compliance or privacy requirements are imposed.
- Start of the final hardening phase.

# Decisions Locked

- [x] All current Phase 02 flaws are deferred to the final hardening phase.
- [x] The current Phase 02 target of full trustworthy state across all failure paths is judged too strict for MVP.
- [x] The highest priority is proving the possibility of all happy-path functions before addressing flaws.
- [x] New flaws discovered will be written down and deferred, with at most a few rounds of unit tests for TDD.
- [x] Deferred items will only be addressed after all must-have functions are implemented.

# Open Items

None.