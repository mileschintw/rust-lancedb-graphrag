---
title: "ADR-XXXX: Disposition of Phase 02 Refreshed Review Findings"
status: accepted
date: 2026-07-29
decider: mileschintw
scope: Phase 02 — ingestion, chunking, and vector storage (rust-lancedb-graphrag)
source_material:
  - .planning/phases/02-ingestion-chunking-vector-storage/02-REVIEW.md (commit 07f7cc868dad7ca2cd0fb77162c1cf705fccf4bd)
  - .planning/phases/02-ingestion-chunking-vector-storage/02-VERIFICATION.md (commit 87036aed5483c6cc29ee006ad605ccdc79e541c4)
---

# Purpose

This ADR records the disposition of five findings from the refreshed Phase 02 code review (3 critical, 2 warnings) conducted after plans 02-17 through 02-21 executed. Phase 02 targets local-first, trustworthy ingestion where PostgreSQL status and the last completed LanceDB index remain consistent through failures and concurrent polling. All five findings are locked as `ship`. A governing architectural constraint applies throughout: all chunking, RAG, and vector logic is owned by the Rust engine; the Go gateway is a thin interface layer (HTTP ⇄ gRPC ⇄ PostgreSQL status) with no chunking semantics of its own. The shared chunk-size ceiling is fixed at 1048576, well inside `int32` range, so a persisted value can never wrap.

# Decision Summary

| ID    | Finding                                                                    | Decision | Priority | Target               |
| ----- | -------------------------------------------------------------------------- | -------- | -------- | -------------------- |
| CR-01 | Camel-case sensitive fields bypass the privacy prohibition                 | Ship     | P0       | Phase 02 gap closure |
| CR-02 | Database integration test deletes all documents in the configured database | Ship     | P0       | Phase 02 gap closure |
| CR-03 | Graceful shutdown drops acknowledged queued ingestions                     | Ship     | P0       | Phase 02 gap closure |
| WR-01 | Unbounded chunk size wraps when persisted to PostgreSQL                    | Ship     | P1       | Phase 02 gap closure |
| WR-02 | Live-evidence test overwrites and deletes real runtime artifacts           | Ship     | P2       | Phase 02 gap closure |

# Findings to Ship

## CR-01: Camel-case sensitive fields bypass the privacy prohibition

**Decision:** Ship.

**Problem:**
`classify_sensitive_field` in `scripts/phase02_live_evidence.py:110-115,122-134` lowercases and strips non-alphanumeric separators but does not split camel-case. Aliases such as `rawContent`, `storedDocumentText`, `authorizationHeader`, and `bearerToken` normalize to `rawcontent`-style values that miss the underscore-form keywords, so the recursive checker accepts them. Reproduced directly: `{"rawContent":"do-not-publish"}` piped to `check-privacy` exited 0 with `privacy prohibition check: PASS`.

**Rationale:**
The privacy gate is the required fail-closed guard for Phase 02 challenge/evidence JSON. A bypass means the machine-wired prohibition (`MUST NOT accept credential, authorization-header, raw-upload, stored-document-text, or stored-chunk-content fields`) is false green — sensitive content can flow into evidence artifacts undetected. The fix is a quick and minor code change.

**Alternatives considered:**
- Expand the keyword list with pre-computed camel-case variants — rejected; enumerating aliases is brittle and does not scale to new field names.
- Reject any field name containing uppercase characters — rejected; over-broad and breaks legitimate keys.
- Canonicalize camel-case boundaries before matching — selected; one normalization step closes the whole alias class.

**Chosen implementation:**
- Insert camel-case splitting before the existing normalization: `snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()` then `canonical = re.sub(r"[^a-z0-9]", "", snake)`.
- Map canonical forms to the existing classes (e.g. `rawcontent` → `raw_content`).
- Add negative tests for each camel-case alias: `rawContent`, `storedDocumentText`, `authorizationHeader`, `bearerToken`, `chunkContent`, `credentialValue`.

**Estimated effort:** Small

**Acceptance criteria:**
- `classify_sensitive_field('rawContent')` returns the `raw_content` class, not `None`.
- Piping `{"rawContent":"do-not-publish"}` to `check-privacy` exits nonzero and never prints the value.
- The Python privacy suite passes with new fail-first camel-case cases.

**Risk if not fixed:**
Credentials, authorization headers, or raw document content pass the privacy gate and land in retained evidence artifacts, violating the phase's no-content/no-secret contract while the gate reports PASS.

**Consequences:**
- Good: One normalization rule closes the entire camel-case alias class.
- Bad: Slightly more complex classifier; new field-name conventions (e.g. kebab-case variants) still rely on the existing separator handling.

## CR-02: Database integration test deletes all documents in the configured database

**Decision:** Ship.

**Problem:**
`TestReconciliationIntentClaimLeaseIsExclusive` in `gateway/db/document_test.go:196-218` executes `DELETE FROM documents` with no predicate or transaction whenever `TEST_DATABASE_URL` is set. A mispointed environment variable turns an ordinary test run into deletion of every document in that database, cascading to reconciliation intents.

**Rationale:**
Mis-wiping an entire database is fatal and unacceptable for any verification surface. A test harness must be structurally incapable of destroying data outside its own fixture scope; relying on operators to set `TEST_DATABASE_URL` correctly is not a guardrail.

**Alternatives considered:**
- Wrap the delete in a transaction with rollback — rejected; still issues unqualified destructive SQL and adds fragility around test lifetime.
- Document a warning that `TEST_DATABASE_URL` must point at a disposable database — rejected; documentation does not prevent the failure mode.
- Scope all setup/cleanup to test-created IDs (or an isolated temporary database/schema) — selected; makes the destructive path impossible by construction.

**Chosen implementation:**
- Remove the unqualified `DELETE FROM documents`.
- Constrain cleanup to IDs the test created: `t.Cleanup(func() { _, _ = pool.Exec(context.Background(), "DELETE FROM documents WHERE id = $1", docID) })`.
- Prefer an isolated temporary database or schema per test run where practical.
- Add a sentinel-row regression test proving unrelated pre-existing rows survive the test.

**Estimated effort:** Small

**Acceptance criteria:**
- No test file issues `DELETE FROM documents` without a predicate.
- With a sentinel row inserted before the test, the sentinel row exists after the test completes.
- The integration suite passes against an isolated `TEST_DATABASE_URL`.

**Risk if not fixed:**
A single misconfigured environment variable causes full production or shared-database document loss during routine testing, with no recovery path.

**Consequences:**
- Good: Test runs become safe against any configured database.
- Bad: Requires disciplined fixture scoping; concurrent tests touching the same rows need explicit isolation.

## CR-03: Graceful shutdown drops acknowledged queued ingestions

**Decision:** Ship.

**Problem:**
In `engine/src/main.rs:867-881,931-959`, the worker's biased `select!` prioritizes the shutdown notification over `receiver.recv()` and breaks immediately. Jobs already accepted into the channel — acknowledged to clients and persisted only as staged raw bytes — are never processed. On restart the in-memory status map is empty; gateway polling (`gateway/main.go:548-578`) then treats engine `NotFound` as authoritative and marks the PostgreSQL document `failed`. The only shutdown test covers one active job, not queued jobs.

**Rationale:**
Graceful shutdown is a key function of the project, and it must work. Accepted-and-acknowledged work being silently abandoned and then falsely terminally failed directly defeats the phase outcome: "the last completed LanceDB index and PostgreSQL status remain trustworthy through failures." Because queueing and ingestion execution are engine-owned, the drain/recovery fix belongs in the Rust engine; the gateway's only role is to stop converting engine `NotFound` into a false terminal `failed` while durable staging exists.

**Alternatives considered:**
- Drain the queue during shutdown using the existing processing body — selected for in-memory accepted work (engine-side).
- Persist a durable staging recovery path that requeues staged rows on engine startup — selected as the restart-safe complement (engine-side); in-memory drain alone cannot cover crash or pre-drain kill.
- Have the gateway refuse to mark engine `NotFound` as terminal while a matching durable staging record exists — selected as the interface-side guard (gateway's only change).

**Chosen implementation:**
- Engine: stop new sends, then drain: `receiver.close(); while let Some(job) = receiver.recv().await { process_and_record_status(job).await; }`.
- Engine: implement startup recovery that requeues durable staged rows not yet processed.
- Gateway: gate the `NotFound → failed` transition on absence of a matching durable staging record; the gateway makes no ingestion decisions beyond reflecting engine/durable state.
- Engine tests: add a queued-at-shutdown test and a restart-recovery behavioral test.

**Estimated effort:** Medium

**Acceptance criteria:**
- With one active job and N queued jobs, graceful engine shutdown processes or durably requeues every acknowledged job; none is abandoned.
- After an engine restart, a previously queued document is processed to a terminal state without client intervention.
- Gateway polling never writes `failed` for a document with a matching unprocessed durable staging record.
- New queued-at-shutdown and restart-recovery tests pass in the engine suite.

**Risk if not fixed:**
Every graceful shutdown with a non-empty queue permanently loses acknowledged user work and records a false `failed` status, making PostgreSQL completion state untrustworthy.

**Consequences:**
- Good: Acknowledged ingestion becomes trustworthy across shutdown/restart, satisfying the phase's core outcome.
- Bad: Adds engine startup recovery logic and a gateway polling-side condition; shutdown latency grows with queue depth during drain.

## WR-01: Unbounded chunk size wraps when persisted to PostgreSQL

**Decision:** Ship.

**Problem:**
The gateway (`gateway/main.go:478-515`) accepts any positive machine-sized integer and casts it to `int32` for `InsertDocumentParams`. On 64-bit builds, `chunk_size=2147483648` passes validation and persists as a negative value, while Rust (`engine/src/main.rs:122-157`) receives and accepts the original positive value as `usize`. Persisted ingestion settings then lie about the chunking that ran.

**Rationale:**
Durable records that misdescribe executed behavior violate the phase's trust contract. Under the engine-owns-chunking constraint, the semantic ceiling is authoritative in the Rust engine; the gateway is a thin interface that parses and forwards, so it must never let an `int32` wrap persist a value the engine would reject. The fix is a quick and minor code change: bound before the cast, with the limit owned by the engine. The ceiling is set deliberately permissive at 1048576 (2²⁰, ~1M tokens) so realistic per-document chunking is never constrained, while the value still fits in `int32` (max 2147483647) with ~2× headroom — eliminating the wrap.

**Alternatives considered:**
- Widen the PostgreSQL column to bigint — rejected; does not bound absurd chunk sizes and changes schema for no functional gain.
- Validate only in the Rust engine and let the gateway persist unvalidated values — rejected; the gateway writes PostgreSQL before/regardless of engine execution, so a value the engine later rejects would already be durably recorded as the document's settings.
- Engine owns `maxChunkSize = 1048576` as the single source of truth; the gateway mirrors it as a thin interface-side guard before the `int32` cast — selected; keeps PostgreSQL truthful while keeping all chunk semantics in the engine.

**Chosen implementation:**
- Engine: enforce `MAX_CHUNK_SIZE = 1048576` in `parse_chunk_settings`; reject out-of-range metadata with a gRPC `InvalidArgument` error. This is the authoritative check.
- Gateway: mirror the bound as an interface guard — parse with `parsed, err := strconv.ParseInt(reqSize, 10, 32)` and reject `parsed < 1 || parsed > 1048576` with HTTP 400, so a wrapping value never reaches `InsertDocumentParams`.
- Keep the constant as one named value in each service (`MAX_CHUNK_SIZE` in Rust, `maxChunkSize` in Go) with a comment that the engine's definition is canonical; document the mirror until a shared config source exists.
- Boundary tests: engine rejects 1048577 via gRPC; gateway rejects 1048577 via HTTP 400; 1048576 is accepted and the PostgreSQL-stored value equals the engine-executed value.

**Estimated effort:** Small

**Acceptance criteria:**
- `chunk_size=2147483648` is rejected with HTTP 400 before any database write.
- The engine rejects `chunk_size=1048577` with gRPC `InvalidArgument` even if the gateway is bypassed.
- `chunk_size=1048576` is accepted by both services; the persisted `int32` equals the value the engine executes.
- Both services reference a single named constant value (1048576), with the Rust definition marked canonical.

**Risk if not fixed:**
Persisted settings can silently disagree with executed chunking, corrupting the durable record the user story depends on.

**Consequences:**
- Good: Persisted settings are guaranteed truthful for every accepted request; the engine remains the sole owner of chunk semantics, with the gateway as pure interface; the 1M-token ceiling constrains no realistic document.
- Bad: The bound is duplicated across two services until a shared config exists; a 1M-token single chunk can still be resource-heavy per embedding call, though admission queueing bounds concurrency.

## WR-02: Live-evidence test overwrites and deletes real runtime artifacts

**Decision:** Ship.

**Problem:**
`test_captured_inspector_arguments_explicit_path` in `scripts/test_phase02_live_evidence.py:481-489,570-572` writes directly to the real Phase 02 challenge/evidence runtime paths and unconditionally unlinks both in `finally`. Run concurrently with a human verification run, it can overwrite or delete that run's evidence.

**Rationale:**
Verification tooling must not destroy the evidence it exists to validate; the fix is a quick and minor code change. Until fixed, the full Python suite is unsafe to run alongside live verification.

**Alternatives considered:**
- Save and restore pre-existing files — acceptable minimum guardrail, but leaves concurrent-run interference possible.
- Run the harness in an isolated fixture checkout — rejected as heavier than needed for this phase.
- Parameterize the runtime-artifact paths so the test uses a temporary directory — selected; simple and fully isolates the test.

**Chosen implementation:**
- Parameterize `CHALLENGE_RUNTIME_PATH` and `EVIDENCE_RUNTIME_PATH` so tests inject temporary paths.
- Point the test at `tmp_path` fixtures instead of real runtime paths.
- As an interim guardrail, save and restore any pre-existing files rather than deleting them.

**Estimated effort:** Small

**Acceptance criteria:**
- The test runs with a pre-existing sentinel file at the real runtime path and the sentinel is byte-identical afterward.
- The full Python suite passes concurrently with a separate process holding open files at the real runtime paths.
- No test writes outside its injected fixture paths.

**Risk if not fixed:**
A routine test run can corrupt an in-progress human verification, making both the test and the verification untrustworthy.

**Consequences:**
- Good: Test and live verification can run concurrently without interference.
- Bad: Minor harness refactoring; path parameterization must be kept consistent with the shell runner.

# Findings Deferred, Rejected, or Accepted As-Is

None. All five findings are ship decisions.

# Exit Conditions

The scope of this ADR is complete when:

1. All five ship items meet their acceptance criteria.
2. The following verification commands pass:
   - `cargo test --manifest-path engine/Cargo.toml` (including new queued-at-shutdown, restart-recovery, and chunk-bound tests)
   - `go test -count=1 ./...` and `go vet ./...` from `gateway` (including the sentinel-row regression and interface-side bound tests)
   - `python -O -I scripts/test_phase02_live_evidence.py` (including camel-case fail-first cases)
   - The camel-case probe: `check-privacy` rejects `{"rawContent":"do-not-publish"}` with nonzero exit
3. No placeholder marked `[TODO]` remains in a path required for exit.
4. `02-VERIFICATION.md` re-verification closes the five corresponding gap entries.

# Review Triggers

Review this ADR before any of the following:

- Deployment model change (e.g. exposing the gateway beyond local-only use)
- Multi-user or multi-tenant change to ingestion or verification surfaces
- Change to the queueing or shutdown architecture (e.g. multiple workers, external queue)
- Any change to the engine/gateway responsibility split (e.g. moving chunk logic into the gateway or a third service)
- Introduction of new sensitive field-name conventions in challenge/evidence JSON
- Schema change to `documents` or `document_reconciliation_intents` affecting test fixture scoping
- Any proposal to raise `maxChunkSize` above 1048576 or lower it for cost control

# Decisions Locked

- [x] CR-01: ship camel-case canonicalization fix to the privacy classifier
- [x] CR-02: ship test-fixture scoping to eliminate unqualified `DELETE FROM documents`
- [x] CR-03: ship shutdown drain plus durable startup recovery in the engine; gateway stops false `NotFound → failed`
- [x] WR-01: ship engine-owned chunk-size bound of 1048576, mirrored as a thin gateway interface guard before the `int32` cast
- [x] WR-02: ship runtime-path parameterization for the live-evidence test harness
- [x] Architectural constraint: all chunk/RAG/vector logic is owned by the Rust engine; the Go gateway is a thin interface layer only
