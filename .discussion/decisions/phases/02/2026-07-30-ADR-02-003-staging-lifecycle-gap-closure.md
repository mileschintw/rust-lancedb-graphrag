---
title: "ADR-02-003: Disposition of Phase 02 Re-Verification Gaps — Staging Lifecycle State Machine"
status: accepted
date: 2026-07-30
decider: mileschintw
scope: Phase 02 — ingestion, chunking, and vector storage (rust-lancedb-graphrag)
source_material:
  - .planning/phases/02-ingestion-chunking-vector-storage/02-REVIEW.md (refreshed 2026-07-30T03:15:25Z, commit d9f90ee)
  - .planning/phases/02-ingestion-chunking-vector-storage/02-VERIFICATION.md (refreshed 2026-07-30T03:24:26Z, commit 0409b38)
supersedes: none
related:
  - 2026-07-29-ADR-02-001-verification-disposition.md
  - 2026-07-29-ADR-02-002-refreshed-review-disposition.md
---

# ADR-02-003: Disposition of Phase 02 Re-Verification Gaps — Staging Lifecycle State Machine

**Status:** accepted
**Date:** 2026-07-30
**Decider:** mileschintw

## Context

Plans 02-22 through 02-24 closed the five literal defects recorded in ADR-02-002 (camel-case privacy aliases, unqualified `DELETE FROM documents`, shutdown queue drain, chunk-size ceiling, live-evidence path isolation). Independent re-review and re-verification on 2026-07-30 confirmed those literal fixes but found the phase still not shippable: six critical blockers (CR-01 through CR-06) and two warnings (WR-01, WR-02), with verification at 14/19 must-haves and status `gaps_found`.

Four of the six blockers (CR-02, CR-03, CR-04, CR-05) share one root cause: the durable staging lifecycle is not a complete state machine across startup replay, migration, storage read failure, and terminal worker failure. The remaining findings concern database-test cross-row mutation (CR-01, WR-02), privacy diagnostic disclosure (CR-06), and test fixture ownership (WR-01).

The governing architectural constraint from ADR-02-002 still applies: all chunking, RAG, and vector logic is owned by the Rust engine; the Go gateway is a thin interface layer (HTTP ⇄ gRPC ⇄ PostgreSQL status). The project is in MVP development; there is no production data, and CI/lint-level enforcement tooling is explicitly out of scope as too heavy for this stage.

## Decisions

### D-01 (CR-02): Startup replay ordering — spawn worker before replay sends

**Decision:** Move `spawn_worker` ahead of the recovery loop. Replay sends into the bounded channel (capacity 100) are consumed as they are enqueued, so any number of staged jobs can be recovered without deadlock.

**Contract:**

1. `spawn_worker` executes before the replay loop over `staged_jobs` (`engine/src/main.rs:1071-1080`).
2. The startup contract is preserved: all recovered jobs must be admitted to the queue before the gRPC listener serves traffic.
3. If `sender.send()` fails because the worker exited during replay, startup fails immediately — no silent continuation.
4. Regression: a production-order test with more staged jobs than `QUEUE_CAPACITY`. The existing `startup_recovery_processes_staged_document` test starts the worker before its single send and therefore does not exercise production ordering or capacity.

### D-02 (CR-03): Remove the legacy staging migration path entirely

**Decision:** Delete `initialize_with_migration` and its manifest validation logic. A single staging table design (the current v2 schema) replaces the versioned pair; `DatabaseManager::initialize` is the only initialization entry point.

**Rationale:** The project is in MVP development. There is no legacy production data; the migration path was designed for data that does not exist and can never complete safely across a normal restart. Removing it eliminates the non-idempotent transition, the duplicate-ID hazard on re-run, and the permanent restart-failure loop in one cut.

**Contract:**

1. `initialize_with_migration` and manifest verification are removed; normal startup over an existing non-empty staging table must be accepted and idempotent.
2. Replay idempotency is guaranteed by D-01's replay flow plus the staging lifecycle invariant in D-04, not by a migration marker.
3. The `legacy_staging_transition_is_versioned_and_lossless` test is removed; replace with a test proving `initialize` is idempotent over an existing non-empty staging table.

**Future note:** If real durable data ever exists post-MVP and a schema transition is needed, introduce explicit schema versioning with a versioned migration marker (legacy row IDs + content hashes) at that time. Do not resurrect the removed path.

### D-03 (CR-04): NotFound only after proven absence; staging read errors map to Unavailable

**Decision:** `get_ingestion_status` returns gRPC `NotFound` only after a successful `count_rows` proves the document is absent from both the in-memory registry and durable staging. Every staging query failure is mapped with `map_err` to gRPC `Unavailable` carrying error context.

**Semantic contract:** `NotFound` means *proven absent*. "Could not check" is never reported as absence.

**Rationale:** The gateway treats engine `NotFound` as authoritative proof of absence and irreversibly writes PostgreSQL `failed`. Collapsing transient storage failures (timeout, lock, corrupted query) into `NotFound` recreates the exact false-terminal state that staging-aware polling was designed to prevent. The gateway already treats non-`NotFound` errors as non-terminal and continues polling, so the gateway requires zero changes.

**Regression:** error-injection test proving that a staging read failure leaves the PostgreSQL row non-terminal.

### D-04 (CR-05): Fail-closed staging delete before any terminal status

**Decision:** A terminal `failed` status may only be published after the staging row has been successfully deleted. If the delete fails, the job remains recoverable (non-terminal status), the error is logged, and restart replay converges the job.

**Core invariant:** *A staging row exists if and only if the job is replayable; a terminal status is only legal after staging is cleared.*

**Contract:**

1. The delete-before-terminal rule applies to all terminal paths, including pre-replacement embedding failures (`engine/src/main.rs:927-955,1045-1055`) and rollback failures that leave staging behind.
2. If staging delete fails, the worker does not publish terminal status; the durable staging row guarantees a later replay attempt.
3. Regression: fail embedding → gateway persists the result → engine restart → PostgreSQL and LanceDB converge to the same terminal state.

**Convergence note:** D-01 through D-04 together complete the staging lifecycle state machine: `persist_raw` precedes admission acknowledgement (existing), worker-first replay ordering (D-01), single staging table with idempotent init (D-02), errors never masquerade as absence (D-03), and terminal status requires staging removal (D-04).

### D-05 (CR-01 + WR-02): Isolated-pool test migration plus review checklist; fail on snapshot errors

**Decision:**

1. Migrate `TestReconciliationIntentRecordAndClaim` (`gateway/db/document_test.go:116-196`) to `createIsolatedTestPool`; all fixtures are created through the returned claimant pool. No batch claim may execute against the configured public schema.
2. Add a code review checklist convention to the repository's review guidance: every claim/lease-style integration test must use an isolated per-test schema. CI/lint enforcement is explicitly rejected as too heavy for MVP.
3. Fix WR-02 in the same pass: every public-count snapshot query error in the isolated lease tests must `t.Fatalf` immediately; a failed before/after read must never be compared as zero-valued counts (a false pass).

### D-06 (CR-06): Category-only privacy diagnostics

**Decision:** Privacy failure diagnostics report only the normalized field class and a structural location composed exclusively of safe tokens (container names, array indices). Raw JSON keys are never interpolated into diagnostics.

**Rationale:** Keys are untrusted input and can themselves carry credentials or document content; the reproduced probe (`{"Bearer SENTINEL_NOT_SECRET":"x"}`) printed the sensitive key verbatim to stderr. Redaction/hash alternatives were rejected: the locatability they preserve does not justify a residual disclosure surface in verification tooling, and class + structural path is sufficient to locate the offending field.

**Regression:** subprocess test with an inert secret-bearing key proving stderr contains no raw key and exits nonzero.

### D-07 (WR-01): Per-process fixture ownership in the live-evidence suite

**Decision:** Remove the shared-directory `.phase02-live-test-*` glob from `tearDownClass`. The suite tracks only paths created by the current test process and cleans exactly those via `addCleanup`/context managers; directories are removed with `shutil.rmtree`, not `Path.unlink()`.

**Rationale:** The global glob both deletes fixtures owned by other concurrent processes and raises on matching directories. For MVP, concurrency risk is accepted as nonexistent, so the deeper isolation of tempfile-rooted fixtures is unnecessary; per-run ownership is the correct minimal fix.

## Consequences

**Positive:**

- The durable staging lifecycle becomes a complete, single-invariant state machine (D-01–D-04), eliminating startup deadlock, non-restartable initialization, false-terminal polling, and cross-store split-brain as a class.
- Engine `NotFound` regains a trustworthy meaning; gateway polling logic needs no changes.
- Deleting the legacy migration removes dead code and an entire failure category rather than patching it.
- Test-suite hazards (cross-schema mutation, false-pass assertions, destructive fixture cleanup, secret-bearing diagnostics) are removed at their sources.

**Negative / accepted trade-offs:**

- Fail-closed staging delete (D-04) means a persistently failing staging delete keeps a job non-terminal indefinitely. This is intentional: retry forever is preferable to split-brain.
- Review-checklist enforcement (D-05) relies on human discipline; automated CI/lint guards are deferred until post-MVP.
- Orphaned fixtures from a crashed test process are no longer swept by the next run (D-07); accepted under the MVP no-concurrency assumption.

**Follow-ups:**

- `/gsd-plan-phase 02 --gaps` to plan implementation of D-01 through D-07.
- Post-implementation, rerun the full Python optimized suite in a clean environment and the named PostgreSQL integration tests against an isolated database.
- Human verification items from 02-VERIFICATION.md (fresh provider-backed cross-store run and private disclosure review) remain required after the fixes land.
- Accepted debt items `DEBT-CR-04`, `DEBT-CR-05`, `DEBT-BU-01`, and `DEBT-BU-02` remain non-blocking under their recorded constraints and are unaffected by this ADR.

---

_Decided: 2026-07-30_
_Decider: mileschintw_
