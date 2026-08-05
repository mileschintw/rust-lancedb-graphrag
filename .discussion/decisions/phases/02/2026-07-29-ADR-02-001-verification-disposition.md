---
title: "ADR-02-001: Phase 02 Verification Finding Disposition"
status: accepted
date: 2026-07-29
decider: mileschintw
scope: phase-02-ingestion-chunking-vector-storage
source_review:
  commit: 8af6c537485fd07dde07bc783cf2681a0a8dc9f3
  review: .planning/phases/02-ingestion-chunking-vector-storage/02-REVIEW.md
  verification: .planning/phases/02-ingestion-chunking-vector-storage/02-VERIFICATION.md
---

# Phase 02 Verification Finding Disposition

## Purpose

This record captures the disposition of the current Phase 02 verification findings.

The project is a personal local-first side project. It is not intended for public deployment or multi-tenant access at this stage. Decisions therefore prioritize:

- Data correctness and durable-state integrity
- Prevention of accidental credential or document-content disclosure
- Reliable local developer workflows
- Minimal runtime and operational complexity
- Deferral of internet-facing abuse protection until deployment scope changes

A finding marked `ship` must have a concrete implementation and behavioral acceptance test before Phase 02 is considered complete.

A finding marked `defer` is accepted as known debt. It must be revisited when its trigger condition occurs, or before the stated target milestone.

## Runtime Boundaries

Production service runtime consists only of:

- Go gateway binary
- Rust engine binary
- PostgreSQL
- LanceDB data store
- Configured embedding provider access

Python is a developer and verification-tooling dependency only. Python must not be required to start, serve, ingest, poll, or recover the Go/Rust application services.

Python is required only for:

- Challenge and evidence JSON validation
- Privacy-prohibition fixture tests
- Local and CI verification commands

Node.js is not a required runtime or verification dependency after WR-01 and WR-02 are completed.

## Decision Summary

| ID    | Finding                                                          |             Decision | Priority | Target                               |
| ----- | ---------------------------------------------------------------- | -------------------: | -------: | ------------------------------------ |
| CR-01 | Rust ignores `LANCET_CONFIG_DIR`                                 |                 Ship |       P2 | Phase 02                             |
| CR-02 | Gateway metadata differs from executed Rust chunk settings       |                 Ship |       P0 | Phase 02                             |
| CR-03 | Failed-admission compensation is not durably reconciled          |                 Ship |       P0 | Phase 02                             |
| CR-04 | Upload endpoint is unauthenticated and binds all interfaces      | Defer with guardrail |       P2 | Before any network/shared deployment |
| CR-05 | Queue does not bound pre-buffer upload resources                 |                Defer |       P2 | Before external or concurrent use    |
| CR-06 | Inspector error can disclose persisted untrusted values          |                 Ship |       P0 | Phase 02                             |
| WR-01 | Privacy test is skipped when Node is absent                      |                 Ship |       P1 | Phase 02                             |
| WR-02 | Node privacy vocabulary differs from Python validation           |                 Ship |       P1 | Phase 02                             |
| WR-03 | Closure tests do not prove their named behavior                  |                 Ship |       P1 | Phase 02                             |
| WR-04 | Verification scripts fall back after config errors               |                 Ship |       P1 | Phase 02                             |
| WR-05 | Inspector mutates a store during verification                    |                 Ship |       P1 | Phase 02                             |
| BU-01 | Complete run-window rejection is not behaviorally proven         |                Defer |       P3 | v1 MVP closure                       |
| BU-02 | Caller-owned file preservation is not fully proven               |                Defer |       P3 | v1 MVP closure                       |
| BU-03 | NaN and infinity embedding rejection is not behaviorally proven  |                 Ship |       P1 | Phase 02                             |
| BU-04 | Missing schema field rollback and worker survival are not proven |                 Ship |       P1 | Phase 02                             |

---

# Findings to Ship

## CR-01: Honor `LANCET_CONFIG_DIR`

**Decision:** Ship.

**Problem:** The Go gateway supports `LANCET_CONFIG_DIR`, but the Rust engine only searches repository-relative configuration paths. Running the engine from a config-less working directory fails even when `LANCET_CONFIG_DIR` points to a valid configuration directory.

**Rationale:** This is a small, localized change that removes a confusing environment-dependent startup failure. It also makes gateway and engine configuration behavior consistent.

**Chosen implementation:**

- Resolve `LANCET_CONFIG_DIR` first when present.
- Fall back to the current default configuration-directory discovery only when it is absent.
- Load `config.toml` and any optional environment overlay from the chosen directory.
- Apply `LANCET_` environment overrides after loading file-based configuration.

**Estimated effort:** Small, less than one hour.

**Acceptance criteria:**

- Running the built Rust engine from a temporary config-less working directory succeeds when `LANCET_CONFIG_DIR=<repo>/config`.
- Existing repository-relative startup behavior remains working when `LANCET_CONFIG_DIR` is unset.
- A process-level regression test covers both cases.

**Risk if not fixed:** Local scripts or future deployment layouts can start the gateway but fail to start the engine.

---

## CR-02: Make persisted chunk metadata match executed settings

**Decision:** Ship.

**Problem:** PostgreSQL stores `chunk_strategy = "recursive"`, but Rust does not implement a strategy under that name. The Go gRPC client also omits metadata, causing Rust to silently use its own `structure-aware` and default size/overlap values.

**Rationale:** The persisted document record must truthfully describe how the document was chunked. This is a core data-correctness requirement even for a local project.

**Chosen implementation:**

- Define canonical strategy identifiers shared by Go and Rust, initially `structure-aware` and `fixed-size`.
- Replace the gateway-side `recursive` value with the canonical Rust-supported strategy.
- Send `chunk_strategy`, `chunk_size`, and `chunk_overlap` in the first gRPC streamed request.
- Validate metadata presence and consistency in Rust.
- Reject unknown strategy values rather than silently falling back to `structure-aware`.
- Treat the Rust engine as the authority for allowed strategy values, but make the gateway validate before persistence where practical.

**Estimated effort:** Medium.

**Acceptance criteria:**

- A document persisted as `structure-aware`, `500`, `50` is received and used as exactly those values by Rust.
- A document persisted as `fixed-size`, with non-default size/overlap, is received and used exactly by Rust.
- Unknown or missing strategies are rejected with an explicit error.
- PostgreSQL metadata, gRPC request metadata, and engine execution settings match in an end-to-end test.

**Risk if not fixed:** Database metadata lies about document processing, making debugging, replacement, and future configurable chunking unreliable.

---

## CR-03: Durable failed-admission reconciliation

**Decision:** Ship.

**Problem:** When engine admission definitively fails, the gateway attempts to change PostgreSQL status from `queued` to `failed` only five times. If all attempts fail, no durable task remains to repair the row, so it can remain queued forever.

**Rationale:** PostgreSQL status is part of the project’s durable source of truth. A local database outage, restart, or transient connection error must not leave a document in a permanent false queued state.

**Chosen implementation:**

- Add a durable reconciliation-intent table, for example `document_reconciliation_intents`.
- Create the intent transactionally with the queued document record whenever definitive non-admission requires compensation.
- Store document ID, desired terminal status, reason class, retry count, next attempt time, last error class, and lifecycle timestamps.
- Run a single background reconciler in the gateway process.
- Claim due intents safely, retry conditional PostgreSQL terminal transition with bounded work per cycle and exponential backoff.
- Keep the intent until a terminal row is confirmed or another verified terminal winner exists.
- Preserve request-path retries for responsiveness, but hand off to the durable intent after they are exhausted.
- Keep `GET /documents/:id` repair behavior as a secondary recovery path, not the only recovery mechanism.
- Delete intent record once the terminal state is confirmed.

**Estimated effort:** Medium to large.

**Acceptance criteria:**

- Simulate more than five consecutive PostgreSQL update failures after definitive engine non-admission.
- Confirm that the document initially remains `queued` while the reconciliation intent persists.
- Restore PostgreSQL availability without issuing any client `GET`.
- Confirm the background reconciler transitions the row to `failed` and marks/removes the intent.
- Restart the gateway while an intent is pending; after restart and DB recovery, confirm eventual terminal convergence.
- Confirm idempotence when the document is already terminal due to another valid path.

**Risk if not fixed:** A document can remain indefinitely queued and no longer accurately represent engine admission state.

**Consequences:**

- Good: Durable eventual convergence across transient failures and process restarts.
- Bad: Adds a table, migration, worker lifecycle, retry policy, and tests.

---

## CR-06: Do not disclose persisted untrusted values in inspector errors

**Decision:** Ship.

**Problem:** The inspector interpolates an unknown persisted `embedding_model` value into an error message. The value is durable but untrusted; a corrupt row could contain content or a credential-like string.

**Rationale:** This remains important for local use because logs, terminal output, CI output, and AI-agent sessions can copy or retain diagnostic content.

**Chosen implementation:**

- Return a class-only error such as `LanceDB contains an unknown embedding_model`.
- Do not serialize unknown persisted field values in inspector errors.
- Review equivalent diagnostic paths for direct interpolation of persisted document content, chunk text, authorization values, or secrets.

**Estimated effort:** Small.

**Acceptance criteria:**

- A fixture with a sentinel secret-like unknown `embedding_model` fails inspection.
- The error identifies the invalid field class but does not contain the sentinel value.
- A regression test asserts the output does not contain the persisted fixture value.

**Risk if not fixed:** Sensitive or document-derived values can leak through local diagnostics, logs, CI output, or agent context.

---

## WR-01 and WR-02: Consolidate privacy validation in Python

**Decision:** Ship.

**Problem:** The final gate conditionally skips the Node privacy test when Node is unavailable. Separately, the Node implementation recognizes fewer forbidden field classes than the Python validator.

**Rationale:** A mandatory check must not silently disappear, and multiple independent forbidden-field vocabularies will drift. The project already has Python external-validation tooling, so Python becomes the single implementation for this validation.

**Chosen implementation:**

- Move all privacy prohibition logic and fixtures into `scripts/phase02_live_evidence.py` or a Python module imported by it.
- Move Node-specific privacy tests to Python tests.
- Delete `scripts/test_phase02_privacy_prohibition.cjs` once equivalent Python coverage exists.
- Remove Node as a verification prerequisite.
- Maintain one canonical normalized forbidden-field classifier.
- Validate keys recursively and case-insensitively, according to the final policy.
- Make `verify-live-evidence.sh --validate-gate` fail if the Python privacy check cannot execute.

**Estimated effort:** Small to medium.

**Acceptance criteria:**

- A clean fixture passes.
- One known-bad fixture exists for each forbidden field category.
- At minimum, fixtures cover `credential`, `secret`, `bearer`, `authorization_header`, `raw_content`, `document_text`, and `chunk_content`.
- The privacy test is executed by the final verification gate without requiring Node.
- Python unavailable or privacy validation failure causes a nonzero gate exit.

**Risk if not fixed:** The final verification gate may pass without a mandatory privacy check, or miss a forbidden field class.

**Consequences:**

- Good: One validation implementation, fewer runtime dependencies, consistent coverage.
- Bad: Python remains a required external verification runtime.

---

## WR-03: Replace false-positive closure tests

**Decision:** Ship.

**Problem:** Several named tests do not exercise the behavior claimed by their names. Examples include a schema-field test that injects a mutation failure instead of a missing schema field, and a run-window test that fails earlier due to challenge mismatch.

**Rationale:** A passing test that validates the wrong failure mode provides false confidence and is worse than an explicitly missing test.

**Chosen implementation:**

- Rewrite each test around its actual required fault condition.
- Assert specific error classification, durable postcondition, and liveness property, not only `is_err()` or nonzero exit.
- Keep test names aligned with injected condition and asserted outcome.

**Estimated effort:** Medium.

**Acceptance criteria:**

- Schema-drift test injects an actual missing field after version capture.
- Test proves rollback preserves prior generation.
- Test proves failed status is recorded.
- Test proves the worker accepts and completes a subsequent clean job.
- Run-window test uses matching challenge/evidence identity and fails specifically due to exceeding run duration.
- Explicit-path test captures actual spawned inspector arguments instead of searching source text.

**Risk if not fixed:** Future changes can break critical recovery behavior while the suite still appears green.

---

## WR-04: Fail closed on verification configuration errors

**Decision:** Ship.

**Problem:** Verification scripts tolerate TOML parsing failures and fall back to a hardcoded or caller-working-directory-relative LanceDB path. The scripts can therefore inspect a stale or incorrect store.

**Rationale:** A verification command must verify the intended store or fail. A false green result is more damaging than an explicit setup error.

**Chosen implementation:**

- Parse committed TOML strictly.
- Require a non-empty `engine.lancedb_path`.
- Resolve relative store paths against repository root, not caller CWD.
- Abort on invalid TOML, missing key, empty path, unexpected path type, or missing expected store contract.
- Print only the resolved path and non-sensitive diagnosis when failing.

**Estimated effort:** Small.

**Acceptance criteria:**

- Invalid TOML returns nonzero and does not invoke the inspector.
- Missing `engine.lancedb_path` returns nonzero.
- A relative configured path resolves identically from repository root and a different CWD.
- The final script invocation uses the expected explicit `--lancedb-path`.

**Risk if not fixed:** Verification can report success for the wrong database.

---

## WR-05: Keep inspection read-only

**Decision:** Ship.

**Problem:** The inspector uses `DatabaseManager::initialize`, which creates missing tables before examining the store. A missing table can be recreated and hidden from the inspection result.

**Rationale:** A diagnostic verifier must not modify the evidence it is evaluating.

**Chosen implementation:**

- Add a read-only open-and-validate path separate from engine startup initialization.
- Require expected LanceDB tables to already exist.
- Validate schema and data without creating, restoring, or mutating tables.
- Keep creation and migration behavior only in engine startup paths.

**Estimated effort:** Medium.

**Acceptance criteria:**

- Inspecting a healthy existing store performs no table creation or mutation.
- Inspecting a store with a missing required table fails nonzero.
- The missing table remains missing after inspection.
- Existing inspector functionality still validates model, vector width, generation continuity, and edge integrity.

**Risk if not fixed:** The verification tool can alter durable state and conceal corruption or setup failures.

---

## BU-03: Prove non-finite embedding rejection

**Decision:** Ship.

**Problem:** Production validation checks embedding values for finiteness, but existing tests cover only null child values and do not prove rejection of NaN, positive infinity, or negative infinity.

**Rationale:** Embeddings are core durable data. Invalid floating-point vectors can corrupt retrieval behavior and make stored data difficult to diagnose.

**Chosen implementation:**

- Add real LanceDB fixtures containing each invalid Float32 child type:
  - Null
  - NaN
  - Positive infinity
  - Negative infinity
- Run the inspector against each fixture.
- Ensure errors contain no vector value or persisted content.

**Estimated effort:** Small.

**Acceptance criteria:**

- Each of the four fixtures exits nonzero.
- Each error identifies the invalid vector class without printing data values.
- A valid finite fixture passes.

**Risk if not fixed:** Invalid vectors may be accepted without regression protection.

---

## BU-04: Prove rollback and worker survival after missing schema fields

**Decision:** Ship.

**Problem:** Existing tests do not inject a real missing schema field after version capture and do not confirm worker liveness after failure.

**Rationale:** A single worker crash can block all future local ingestion jobs. Schema drift is uncommon, but its recovery behavior needs a trustworthy regression test.

**Chosen implementation:**

- Add a controlled fault-injection seam for schema field lookup after version capture.
- Force a true missing-field error.
- Route the error through the same rollback funnel used by production code.
- Verify worker state and submit a subsequent clean job.

**Estimated effort:** Medium.

**Acceptance criteria:**

- A preexisting completed generation remains unchanged after the injected missing-field failure.
- The failed job reaches a terminal failed status.
- Staging cleanup and rollback invariants hold.
- The worker remains alive.
- A following valid job completes successfully and leaves one canonical generation.

**Risk if not fixed:** A schema issue could terminate the worker or leave replacement state inconsistent.

---

# Findings Deferred With Known Risk

## CR-04: Network exposure, authentication, and TLS

**Decision:** Defer with a minimum local-only guardrail.

**Problem:** `POST /documents` has no authentication or authorization and the server can bind all interfaces. A reachable caller could submit data using the service’s provider credential and consume storage or provider quota.

**Deferral rationale:** The current project is a local personal side project and is not intended to accept requests from outside the local machine.

**Minimum guardrail to ship now:**

- Bind the gateway explicitly to `127.0.0.1:<port>` or `localhost:<port>`.
- Do not use `:<port>` as the default listener address.
- Document that this project is local-only and must not be exposed through port forwarding, public ingress, reverse proxying, shared LAN binding, or a tunnel.

**Known risk:** If the service is later exposed to another host or the public internet, unauthenticated users could consume OpenRouter quota and local database/storage capacity.

**Likelihood now:** Low, assuming explicit loopback binding.

**Impact if exposed:** Medium to high, due to provider cost, data ingestion, and local resource consumption.

**Tracking:** `DEBT-CR-04`.

**Target:** Before shared-network, remote, public, multi-user, container-host, VM-host, or cloud deployment.

**Escalation trigger:** Immediately reclassify to blocking if any non-loopback bind, reverse proxy, tunnel, port-forward, shared host, or external caller is introduced.

**Future acceptance criteria:**

- Authentication and authorization occur before body processing.
- TLS is terminated at a trusted ingress or configured directly.
- Per-principal request and ingestion quotas exist.
- The default listener and deployment documentation are safe for the intended deployment model.

---

## CR-05: Resource bounds before queue admission

**Decision:** Defer.

**Problem:** The gateway lacks full body read deadlines and concurrent upload limits. Rust buffers a streamed upload before reserving queue capacity, so the bounded worker queue does not bound concurrent pre-admission memory or connection time.

**Deferral rationale:** This is a single-user local project. Large local uploads are intentional, and hostile slow-client/concurrent-client behavior is outside the present threat model.

**Known risk:** Multiple local invocations, accidental large uploads, or future external access can consume memory or keep connections open before queue admission.

**Likelihood now:** Low.

**Impact now:** Medium, primarily local memory pressure or a hung process.

**Current operating constraint:**

- Only one trusted local user invokes ingestion.
- Do not expose the gateway outside loopback.
- Avoid intentionally launching many simultaneous uploads.
- Keep input sizes within the current intended local limits.

**Tracking:** `DEBT-CR-05`.

**Target:** Before any external/shared access, background bulk ingestion, automated concurrent ingestion, or expected files larger than the current 10 MiB stream limit.

**Escalation trigger:** Reclassify as blocking when introducing remote access, parallel ingestion, scheduled ingestion, or a use case that expects uncontrolled file size/concurrency.

**Future acceptance criteria:**

- Gateway has `ReadTimeout`, `WriteTimeout`, and `IdleTimeout`.
- A bounded upload semaphore is acquired before reading multipart body bytes.
- Rust reserves or otherwise accounts for admission capacity before full in-memory buffering.
- Slow-body, concurrent-stream, permit-release, and memory-bound tests pass.

---

## BU-01: Complete run-window validation

**Decision:** Defer.

**Problem:** The current overlong-run test fails earlier because challenge/evidence identity mismatches. It does not prove that the intended complete run-window duration branch rejects an excessive run.

**Deferral rationale:** This affects the rigor of the live-evidence gate, not normal local document ingestion or durable indexing. Existing freshness and identity checks still offer partial protection.

**Known risk:** An overlong evidence run may not be rejected for the intended duration reason.

**Likelihood now:** Low.

**Impact now:** Low.

**Tracking:** `DEBT-BU-01`.

**Target:** v1 MVP closure, before claiming the live evidence gate is fully verified.

**Escalation trigger:** Reclassify as blocking when the live gate becomes release criteria, CI release criteria, or evidence for a public/shared deployment.

**Future acceptance criteria:**

- Use a controlled clock.
- Use matching challenge/evidence identity and issue times.
- Exceed only the allowed `issued_at` to `generated_at` duration.
- Assert the dedicated complete-run-window error classification.

---

## BU-02: Caller-owned input preservation across all paths

**Decision:** Defer.

**Problem:** Current automation covers one early failure path but does not prove that caller-owned input survives successful execution and all representative error paths.

**Deferral rationale:** The destructive ownership bug was addressed in implementation. Full live-success coverage requires provider/service state and is not necessary for current local iteration.

**Known risk:** A future shell-script change could reintroduce accidental deletion of a caller-owned input file in an untested path.

**Likelihood now:** Low.

**Impact now:** Medium to high if the caller supplies an irreplaceable document.

**Current operating constraint:**

- Do not pass the only copy of an important document to live verification scripts.
- Use a copied fixture or version-controlled sample as script input.
- Prefer script-created temporary sample files for local verification.

**Tracking:** `DEBT-BU-02`.

**Target:** v1 MVP closure.

**Escalation trigger:** Reclassify as blocking before documenting the live runner as safe for arbitrary user-owned source files.

**Future acceptance criteria:**

- Run successful and representative early/post-upload failure paths with a caller-owned fixture.
- Compare file SHA-256 before and after each run.
- Confirm byte-for-byte equality for every path.
- Confirm script-created temporary files are removed only when owned by the script.

---

# Phase 02 Exit Conditions

Phase 02 may be considered complete under the current local-first scope when all `ship` findings in this record meet their acceptance criteria and the following commands pass:

```bash
cargo fmt --manifest-path engine/Cargo.toml -- --check
cargo test --manifest-path engine/Cargo.toml
cargo clippy --manifest-path engine/Cargo.toml --all-targets -- -D warnings

cd gateway
go test -count=1 ./...
go vet ./...
```

The external validation suite must run through Python only after WR-01 and WR-02 are completed.

Deferred items remain visible as known debt and do not become silently accepted as verified behavior.

# Review Triggers

This decision record must be reviewed before any of the following changes:

- Binding the gateway to a non-loopback address
- Using a reverse proxy, tunnel, port-forward, container ingress, or cloud host
- Allowing another person, process, or machine to call the gateway
- Adding bulk, scheduled, concurrent, or automated ingestion
- Increasing intended upload size beyond the current local limit
- Treating live-evidence output as a release, security, or external-audit artifact
- Declaring the v1 MVP complete