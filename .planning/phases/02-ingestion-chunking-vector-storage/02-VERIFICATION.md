---
phase: 02-ingestion-chunking-vector-storage
verified: 2026-07-30T09:58:31Z
status: gaps_found
score: "15/20 must-haves verified"
behavior_unverified: 0
overrides_applied: 0
unverified_prohibitions: 2
re_verification:
  previous_status: gaps_found
  previous_score: "14/19"
  gaps_closed:
    - "All three global reconciliation claim/lease tests now use isolated per-test schemas and fatal public-count snapshot reads."
    - "Startup replay now spawns the worker before bounded sends; the queue-capacity regression passed."
    - "Staging read errors now return gRPC Unavailable rather than authoritative NotFound."
    - "Pre-replacement terminal failure retains replayable staging when staging deletion fails; the isolated cross-runtime restart test passed."
    - "Privacy diagnostics now omit raw forbidden keys and values."
    - "ADR-02-003 D-02 superseded the unused legacy migration contract with one current-schema staging initializer; repeated non-empty initialization passed."
    - "The retained provider-backed attestation was directly reinspected against current PostgreSQL and LanceDB state."
  gaps_remaining:
    - "A completed canonical ingestion can become authoritative NotFound after Rust restarts before PostgreSQL observes completion."
    - "Incomplete canonical rollback can still delete staging and publish terminal failed."
    - "Failed admission can lose both its reconciliation intent and all finite terminal updates."
    - "Attestation construction records human approval when no approval flag is supplied."
    - "The optimized Python suite still performs a class-wide fixture glob and does not pass."
  regressions:
    - "02-27-SUMMARY.md says the class-wide fixture glob was removed, but scripts/test_phase02_live_evidence.py:166-170 still contains it."
gaps:
  - truth: "A completed canonical ingestion remains discoverable as completed after an engine restart until PostgreSQL converges."
    status: failed
    reason: "Success deletes durable staging before publishing completion only to the process-local registry. After restart, status checks only the empty registry and staging table, returns NotFound, and the gateway persists failed despite canonical LanceDB rows."
    artifacts:
      - path: "engine/src/main.rs"
        issue: "get_ingestion_status checks only statuses and staged_documents_v2 (lines 508-538); success deletes staging at lines 902-904 and publishes completed only to DashMap at lines 1045-1053."
      - path: "gateway/main.go"
        issue: "Engine NotFound irreversibly transitions queued/processing PostgreSQL rows to failed at lines 562-582."
    missing:
      - "Persist terminal engine outcome durably or derive completed status and authoritative chunk count from canonical LanceDB state."
      - "Add a completion-then-Rust-restart-before-gateway-poll cross-runtime regression."
  - truth: "A failed canonical rollback retains replayable staging and never exposes a split generation as terminal."
    status: failed
    reason: "rollback_replacement attempts staging deletion even after one or more restore_version failures, and the worker error path performs another unconditional staging deletion before publishing failed."
    artifacts:
      - path: "engine/src/main.rs"
        issue: "Lines 629-667 delete staging independently of rollback_errors; lines 1056-1079 delete staging again and publish terminal failed."
    missing:
      - "Represent incomplete rollback as a distinct replayable/fatal result."
      - "Do not delete staging or publish terminal status when any canonical restore fails."
      - "Add restore_version fault injection and restart-convergence coverage."
  - truth: "Every definitive failed admission leaves either a terminal PostgreSQL row or a confirmed durable reconciliation intent."
    status: failed
    reason: "compensateFailedIngest discards the single CreateReconciliationIntent error and stops after five UpdateStatus failures. A database interruption can therefore strand a queued row with no claimable repair work."
    artifacts:
      - path: "gateway/main.go"
        issue: "Lines 278-319 ignore intent persistence failure and bound terminal updates to five attempts."
      - path: "gateway/main_test.go"
        issue: "The fake store exposes createIntentErr and updateErrs, but no test combines an intent failure with five update failures and reconciler-only recovery."
    missing:
      - "Atomically create the queued row and reconciliation obligation, or require confirmed durable intent/terminal state before compensation exits."
      - "Add a create-intent failure plus five-update-failures regression that converges without GET."
  - truth: "A retained attestation can claim human disclosure approval only after explicit human approval is supplied."
    status: failed
    reason: "Both build_attestation and argparse default human_approved to true. Parsing build-attestation without --human-review-approved returned True, and the shell success test omits the flag while expecting success."
    artifacts:
      - path: "scripts/phase02_live_evidence.py"
        issue: "human_approved defaults true at lines 616-620 and 761-765; lines 669-676 serialize approval and fixed checkpoint provenance."
      - path: "scripts/test_phase02_live_evidence.py"
        issue: "test_attestation_retention_and_private_cleanup_on_success invokes --validate-gate without --human-review-approved at lines 742-755."
    missing:
      - "Default approval false and reject attestation construction without the explicit flag."
      - "Add a negative gate test proving omission preserves evidence and creates no attestation."
  - truth: "The optimized live-evidence suite cleans only fixtures owned by its process and passes deterministically."
    status: failed
    reason: "The class-wide .phase02-live-test-* sweep remains. The verifier's full python -O -I run executed 20 tests and ended with five errors, including PermissionError when tearDownClass tried Path.unlink on a matching directory."
    artifacts:
      - path: "scripts/test_phase02_live_evidence.py"
        issue: "Lines 166-170 globally glob and unlink files or directories owned by any process, contradicting Plan 02-27 and ADR-02-003 D-07."
    missing:
      - "Remove tearDownClass global sweeping."
      - "Track and clean only exact process-owned files/directories, using shutil.rmtree for directories."
      - "Make the full optimized isolated suite pass from a workspace containing a foreign matching fixture."
deferred:
  - truth: "Network authentication, authorization, TLS, and principal quotas."
    addressed_in: "Phase 6 / before any non-loopback or shared exposure"
    evidence: "DEBT-CR-04 remains accepted while the explicit loopback-only, trusted single-user constraint holds."
  - truth: "Pre-admission bounds for hostile slow, concurrent, bulk, scheduled, or uncontrolled ingestion."
    addressed_in: "Phase 6 / before its trigger"
    evidence: "DEBT-CR-05 remains accepted while ingestion is trusted, local, manual, and non-concurrent."
  - truth: "Dedicated complete-run-window branch proof."
    addressed_in: "Phase 6 / v1 MVP closure"
    evidence: "DEBT-BU-01 remains accepted while the live gate is not claimed as release, audit, public, or shared-deployment evidence."
  - truth: "Exhaustive caller-owned input preservation proof across live success and representative failures."
    addressed_in: "Phase 6 / v1 MVP closure"
    evidence: "DEBT-BU-02 remains accepted while the runner is not claimed safe for arbitrary user-owned source files."
prohibition_results:
  - statement: "MUST NOT emit raw document bytes, chunk content, credentials, or attacker-controlled storage values in recovery/status diagnostics."
    verification: test
    status: unverified
    flagged: true
    reason: "Source inspection found category/context logging, but no wired negative test exercises recovery and status diagnostics with attacker-controlled values."
  - statement: "MUST NOT disclose provider credentials, authorization headers, raw uploads, stored document/chunk content, or attacker-controlled secret-bearing keys in evidence, logs, summaries, staged files, or commits."
    verification: judgment
    status: unverified
    flagged: true
    reason: "The retained attestation's approval provenance is forgeable by omitting a CLI flag, so it cannot independently establish that the private log review happened."
---

# Phase 2: Ingestion, Chunking & Vector Storage Verification Report

**Phase Goal:** As a Lancet API user, I want to ingest and safely replace text or Markdown documents, so that the last completed LanceDB index and PostgreSQL status remain trustworthy through failures and concurrent polling.

**Verified:** 2026-07-30T09:58:31Z
**Status:** gaps_found
**Re-verification:** Yes — after Plans 02-25 through 02-28

## User Flow Coverage

| Step | Expected | Current-code evidence | Status |
|---|---|---|---|
| Upload | Submit text/Markdown to `POST /documents` and receive a pollable record | `gateway/main.go:453-549`; Go suite passed | ✓ VERIFIED |
| Configure | Persist and execute the same bounded chunk settings | Go and Rust both enforce `MAX_CHUNK_SIZE=1048576`; metadata tests passed | ✓ VERIFIED |
| Accept | Durably stage recoverable input before Rust acknowledges queue admission | `persist_raw` precedes registry insertion and `permit.send` | ✓ VERIFIED |
| Process | Chunk, embed, and atomically replace canonical LanceDB rows | Normal path and mutation-boundary tests pass, but rollback restoration failure can destroy replay state | ✗ FAILED |
| Recover | Restart and failure handling preserve the last completed generation and truthful status | Capacity replay and delete-failure replay pass; completed-before-poll restart and rollback failure do not | ✗ FAILED |
| Poll | PostgreSQL converges from authoritative Rust/durable state | Rust can report NotFound for a completed canonical generation; failed admission can lack repair intent | ✗ FAILED |
| Outcome | Last completed LanceDB index and PostgreSQL status remain trustworthy | Four correctness/evidence defects plus the broken deterministic gate prevent this outcome | ✗ FAILED |

The MVP outcome clause is not achieved. A normal provider-backed run currently reinspects successfully, but the promised trustworthiness does not hold across all restart, rollback, admission-failure, and approval paths.

## Goal Achievement

### Observable Truths

The 20 truths below deduplicate the seven roadmap success criteria, all 28 PLAN frontmatter contracts, the prior verification truths, and the new 02-25 through 02-28 closure contracts.

| # | Truth | Status | Evidence |
|---:|---|---|---|
| 1 | HTTP upload creates a PostgreSQL-backed polling record for text/Markdown and lightweight text-like input. | ✓ VERIFIED | Handler wiring and Go tests pass. |
| 2 | Rust validates streamed identity/metadata and processes jobs through one bounded sequential worker. | ✓ VERIFIED | Stream, queue, shutdown, and capacity-replay tests pass. |
| 3 | PostgreSQL chunk settings equal the metadata and settings Rust executes. | ✓ VERIFIED | Go/Rust settings and ceiling tests pass. |
| 4 | Fixed-size and structure-aware chunking plus `o200k_base` token estimation work. | ✓ VERIFIED | Rust chunker tests pass. |
| 5 | OpenRouter uses the locked timeout, retry, ordering, and concurrency contract. | ✓ VERIFIED | Production-builder timeout/retry/concurrency tests pass. |
| 6 | Chunks, embeddings, metadata, nodes, and edges persist to canonical LanceDB schemas. | ✓ VERIFIED | Real embedded-store and inspector fixtures pass. |
| 7 | Every failed same-ID replacement preserves or restores one replayable canonical generation. | ✗ FAILED | Mutation failures pass, but a `restore_version` failure can still delete staging and publish failed. |
| 8 | Definitive failed admission has durable reconciliation independent of GET polling. | ✗ FAILED | Intent creation failure is discarded and terminal retries are finite. |
| 9 | Lost acknowledgement, terminal races, and response identity are guarded. | ✓ VERIFIED | Go behavior tests pass. |
| 10 | Rust honors `LANCET_CONFIG_DIR` and configuration precedence from a config-less CWD. | ✓ VERIFIED | Three process-level tests pass. |
| 11 | Community/node/edge placeholder schemas contain all required nullable fields. | ✓ VERIFIED | Schema and null-placeholder tests pass. |
| 12 | `EntityResolver` and production-used `ExactMatchResolver` exist. | ✓ VERIFIED | Trait, implementation, worker call, and test are present. |
| 13 | Inspector is read-only/non-disclosing and rejects invalid vectors; schema lookup faults roll back without killing the worker. | ✓ VERIFIED | Inspector and active-worker fault tests pass. |
| 14 | Privacy classification rejects separator/camel-case aliases using category-only safe paths. | ✓ VERIFIED | Both direct raw-content and secret-bearing-key probes failed closed without echoing values/keys. |
| 15 | The retained provider-backed run is traceable to matching current PostgreSQL and LanceDB state. | ✓ VERIFIED | `--reinspect-attestation` independently passed for document `5e3655db-4749-4015-a674-5aff5cbda0b6`. |
| 16 | Every acknowledged job remains truthful through shutdown, completion, restart, storage error, and terminal publication. | ✗ FAILED | Completed canonical state is not a status authority after restart; incomplete rollback can destroy replay state. |
| 17 | Every global claim/lease database test is isolated and fails on snapshot read errors. | ✓ VERIFIED | Source audit plus three named PostgreSQL integration tests passed against isolated schemas. |
| 18 | Tests cannot replace or delete the real Phase 02 challenge/evidence artifacts. | ✓ VERIFIED | Explicit runtime paths are injected; successful gate cleanup targets only the canonical private pair. |
| 19 | Live-evidence fixtures are process-owned and the full optimized suite passes. | ✗ FAILED | Global glob remains; full suite ran 20 tests and produced five errors. |
| 20 | Human disclosure approval is explicit, non-forgeable, and attached only after the blocking checkpoint. | ✗ FAILED | CLI and function defaults fabricate approval when the flag is omitted. |

**Score:** 15/20 truths verified; 0 present-but-behavior-unverified.

### Roadmap Success Criteria

| # | Roadmap criterion | Status | Evidence |
|---:|---|---|---|
| 1 | Upload via Go HTTP API | ✓ VERIFIED | Handler and tests exist and pass. |
| 2 | Rust receives via gRPC and chunks | ✓ VERIFIED | Stream/chunker/worker tests pass. |
| 3 | Chunks and embeddings stored in LanceDB | ✓ VERIFIED | Real embedded-store tests and current attestation reinspection pass. |
| 4 | Community IDs and communities placeholder schema | ✓ VERIFIED | Canonical schema test passes. |
| 5 | Node/edge summary placeholder columns | ✓ VERIFIED | Nullable schema and persisted-null tests pass. |
| 6 | `EntityResolver` / `ExactMatchResolver` | ✓ VERIFIED | Trait, implementation, production call, and test exist. |
| 7 | Tokio channel worker structure | ✓ VERIFIED | Bounded single worker and recovery/drain tests pass. |

All seven narrow criteria exist, but they are insufficient to establish the stronger MVP outcome clause in the current authoritative goal.

### Plan Contract Disposition

| Plans | Verdict | Independent disposition |
|---|---|---|
| 02-01–02-04 | VERIFIED / PARTIAL | Scaffolding, chunking, schemas, worker, and polling exist; polling inherits the current completed-restart status defect. |
| 02-05–02-07 | PARTIAL | Nullable schemas and ordinary rollback/retry pass; restore failure can still delete staging. |
| 02-08 | VERIFIED | Timeout and durable inspector contracts pass. |
| 02-09–02-10 | PARTIAL | Challenge/evidence and current-store validation work; full optimized suite and disclosure provenance do not. |
| 02-11 | FAILED | Durable reconciliation can be lost when intent creation and all finite updates fail. |
| 02-12–02-14 | VERIFIED | Freshness, explicit path, vector validation, rollback routing, and lint contracts pass. |
| 02-15–02-16 | SUPERSEDED / PARTIAL | Node prohibition tooling was intentionally replaced by Plan 02-21's Python-only gate; private review remains unproven because approval is forgeable. |
| 02-17–02-18 | VERIFIED | Config directory, settings propagation, loopback constraint, and durable intent schema/query surface exist. |
| 02-19 | FAILED | Reconciler works when an intent exists, but failed admission does not guarantee intent durability. |
| 02-20 | VERIFIED | Read-only inspector and schema-fault worker-survival contracts pass. |
| 02-21 | PARTIAL | Python-only classifier/store resolution works; the complete Python gate does not pass. |
| 02-22–02-24 | VERIFIED / SUPERSEDED | Drain, staged status, ceilings, canonical-path safety, and database isolation pass; ADR-02-003 D-02 formally replaced the unused legacy migration branch. |
| 02-25 | PARTIAL | Worker-first replay, status-read errors, and delete-failure replay pass; completed restart and incomplete rollback remain unsafe. |
| 02-26 | VERIFIED | Claim/lease test isolation, fatal snapshots, and `AGENTS.md` review convention pass. |
| 02-27 | FAILED | Privacy diagnostics pass, but the claimed removal of the global cleanup glob did not occur. |
| 02-28 | FAILED | Current live reinspection passes, but the deterministic Python suite fails and approval can be fabricated. |

## Required Artifacts

| Artifact group | Existence/substance | Wiring/data flow | Status |
|---|---|---|---|
| `gateway/main.go`, PostgreSQL schema/queries | Substantive | HTTP → PostgreSQL → gRPC → poll/reconcile is wired; failed-admission durability is incomplete | ✗ PARTIAL |
| `gateway/db/document_test.go`, `AGENTS.md` | Substantive | All global claimants use isolated pools; snapshot reads are fatal | ✓ VERIFIED |
| `engine/src/main.rs` | Substantive | Stream → staging → queue → worker → LanceDB is wired; completed-restart and rollback-error paths are broken | ✗ PARTIAL |
| `engine/src/db/mod.rs`, DB tests | Substantive | One current-schema staging initializer and canonical schemas are wired | ✓ VERIFIED |
| `engine/src/chunker/*`, `engine/src/client/*` | Substantive | Production worker calls both; tests pass | ✓ VERIFIED |
| `engine/src/bin/inspect_lancedb.rs`, inspector tests | Substantive | Read-only current-store reinspection passed | ✓ VERIFIED |
| `scripts/phase02_live_evidence.py` | Substantive | Privacy/current-store/attestation commands are wired; approval default is unsafe | ✗ PARTIAL |
| `scripts/test_phase02_live_evidence.py` | Substantive | Test suite is runnable but global cleanup is destructive and the full run fails | ✗ FAILED |
| `02-LIVE-ATTESTATION.json` | Exists, ignored, untracked, privacy-clean | Current PostgreSQL/LanceDB reinspection passed; human-approval provenance is forgeable | ✗ PARTIAL |
| Challenge/evidence runtime pair | Absent by successful-gate design | Removal after attestation is expected | ✓ VERIFIED |
| `scripts/test_phase02_privacy_prohibition.cjs` | Missing | Superseded by the explicit Python-only Plan 02-21 contract | ✓ SUPERSEDED |
| `COVERAGE.md` plan path | Root path missing | The intended matrix exists at `.planning/phases/02-ingestion-chunking-vector-storage/COVERAGE.md` | ⚠ PATH MISMATCH |

The artifact verifier evaluated 60 declared artifact entries. Five literal paths were absent: two transient runtime files expected to be removed, two superseded Node artifacts, and one `COVERAGE.md` path mismatch with an existing phase-local equivalent.

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| HTTP upload | PostgreSQL | `InsertDocument` before gRPC | ✓ WIRED | Settings and bounds are persisted before streaming. |
| PostgreSQL settings | Rust chunker | first-frame gRPC metadata | ✓ WIRED | Exact values are parsed and executed. |
| gRPC admission | durable staging/queue | `persist_raw` then `permit.send` | ✓ WIRED | Acknowledged input is recoverable. |
| Startup staging | worker | worker-first bounded replay | ✓ WIRED | Capacity and receiver-exit tests pass. |
| Worker normal path | canonical LanceDB | chunk/embed/replace/delete staging | ✓ WIRED | Normal and injected mutation tests pass. |
| Completed canonical state | status RPC | durable terminal lookup | ✗ NOT WIRED | Status RPC never consults canonical documents/nodes after registry loss. |
| Rollback failure | replayable staging | restore outcome gates deletion | ✗ NOT WIRED | Staging deletion proceeds despite restore errors. |
| Failed admission | durable reconciliation | confirmed intent or terminal row | ✗ NOT WIRED | Intent error is ignored and retries are finite. |
| Rust status | PostgreSQL polling | gRPC status and conditional update | ⚠ PARTIAL | Gateway is correct only when Rust NotFound is a complete durable absence proof. |
| Privacy CLI | classifier | recursive safe structural traversal | ✓ WIRED | Raw keys/values are omitted. |
| Provider attestation | PostgreSQL/LanceDB | retained UUID plus direct reinspection | ✓ WIRED | Current reinspection passed. |
| Human checkpoint | attestation approval | explicit approval flag | ✗ NOT WIRED | Omitted flag still produces `approved=true`. |

## Data-Flow Trace (Level 4)

| Artifact | Data | Source → sink | Produces trustworthy data | Status |
|---|---|---|---|---|
| Gateway upload | ID/settings/status | multipart → PostgreSQL → gRPC | Yes on normal admission | ✓ FLOWING |
| Rust worker | raw bytes/chunks/embeddings | gRPC → staging → queue → LanceDB | Normal path yes; rollback failure unsafe | ✗ PARTIAL |
| Engine status | queued/terminal state | registry/staging → gRPC → PostgreSQL | No after completed-state registry loss | ✗ DISCONNECTED TERMINAL SOURCE |
| Reconciliation | failed-admission intent | handler → PostgreSQL intents → claimant | No when initial intent insert and updates fail | ✗ PARTIAL |
| Live attestation | UUID/count/schema facts | evidence → retained digest → direct current-store reinspection | Structural facts yes | ✓ FLOWING |
| Human approval | checkpoint judgment | CLI flag → attestation | No; default true bypasses checkpoint provenance | ✗ HOLLOW APPROVAL |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Full Rust workspace | `cargo test --manifest-path engine/Cargo.toml --locked` | 60 passed across library, engine, inspector, and config tests | ✓ PASS |
| Rust formatting/lint | `cargo fmt ... --check`; `cargo clippy --all-targets --all-features --locked -- -D warnings` | Both passed | ✓ PASS |
| Full Go workspace | `go test -count=1 ./...` | All packages passed; integration tests skip without an injected URL | ✓ PASS WITH SCOPE NOTE |
| Go vet | `go vet ./...` | Exit 0; Go telemetry emitted a non-fatal local token warning | ✓ PASS |
| PostgreSQL claim isolation | Three named `TestReconciliationIntent...` tests with documented local `TEST_DATABASE_URL` | All three passed against per-test schemas | ✓ PASS |
| Cross-runtime delete-failure restart | `TestEmbeddingFailureRestartConvergesAcrossRuntime` with isolated PostgreSQL | Passed in 6.22s | ✓ PASS |
| Full optimized Python gate | `python -O -I scripts/test_phase02_live_evidence.py` | 20 ran; 5 errors, including global cleanup/ACL failures | ✗ FAIL |
| Privacy probes | `check-privacy` with `rawContent` and secret-bearing key | Both exited 1; output contained only normalized class and `subject.member` | ✓ PASS |
| Attestation syntax/privacy | `validate-attestation`; `check-privacy` | Both passed | ✓ PASS |
| Current live reinspection | `bash verify-live-evidence.sh --reinspect-attestation ...` | `Attested live state reinspected successfully` | ✓ PASS |
| Approval omission | Parse `build-attestation --evidence dummy.json` without approval flag | `human_approved=True` | ✗ FAIL |

Passing suites do not cover the four critical error paths: completed-before-poll restart, `restore_version` failure, simultaneous intent/update loss, and omitted human approval. The full Python suite failure independently violates Plans 02-27 and 02-28.

## Probe Execution

No conventional `probe-*.sh` files are declared or present.

| Probe | Command | Result | Status |
|---|---|---|---|
| Phase-declared attestation reinspection | `bash ./verify-live-evidence.sh --reinspect-attestation --attestation .../02-LIVE-ATTESTATION.json` | Current PostgreSQL/LanceDB state matched the retained attestation | ✓ PASS |

## Requirements Coverage

All eight Phase 02 requirement IDs appear in PLAN frontmatter; no additional Phase 02 requirement is orphaned.

| Requirement | Description | Status | Evidence |
|---|---|---|---|
| DATA-01 | Ingest Markdown, plain text, JSON, and text-like sources | ✓ SATISFIED | HTTP/gRPC ingestion and JSON fixed-size routing pass; empty-upload semantics remain a warning. |
| DATA-02 | Fixed-size and structure-aware chunking | ✓ SATISFIED | Chunker and settings tests pass. |
| DATA-03 | Persist chunks and metadata in LanceDB | ✓ SATISFIED | Canonical persistence and live reinspection pass; the stronger phase durability goal still fails. |
| DATA-06 | `community_ids` and communities placeholder | ✓ SATISFIED | Schema tests pass. |
| DATA-07 | Nullable node summary fields and refs | ✓ SATISFIED | Schema and persisted-null tests pass. |
| DATA-08 | Separate nodes/edges with nullable edge summaries | ✓ SATISFIED | Schema and inspector tests pass. |
| DATA-09 | Async resolver and exact-match default | ✓ SATISFIED | Trait, implementation, production use, and test exist. |
| RAG-06 | Async background worker structure | ✓ SATISFIED | Bounded Tokio worker, drain, and replay tests pass. |

The unchecked boxes in `.planning/REQUIREMENTS.md` are consistent with Phase 02 remaining open, even though each narrow requirement has implementation evidence. Goal-level durability and truthfulness are stricter than these terse requirement descriptions.

## Anti-Patterns and Warnings

No unreferenced `TBD`, `FIXME`, or `XXX` marker was found in the inspected Phase 02 implementation files.

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `scripts/test_phase02_live_evidence.py` | 166-170 | Class-wide fixture glob and `Path.unlink` | 🛑 BLOCKER | Deletes foreign fixtures, fails on directories, and breaks the required full suite. |
| `gateway/main.go` | 278-319 | Ignored durable-intent error plus finite compensation | 🛑 BLOCKER | Can strand a queued row without background repair. |
| `scripts/phase02_live_evidence.py` | 619, 764 | Approval defaults true | 🛑 BLOCKER | Automated callers can forge human checkpoint provenance. |
| `gateway/main.go` | 453-525 | No explicit zero-byte decision before insert/stream | ⚠ WARNING | Empty input becomes a durable failed row and HTTP 502 rather than a clear client contract. |
| `engine/src/tests.rs` | 1422-1465, 1490-1497 | Unbounded fixture polling loops | ⚠ WARNING | A failed cross-runtime state transition can hang until the outer Go timeout/kill path. |
| `engine/src/main.rs` | 547 | QueryRAG placeholder | ℹ INFO | Explicitly belongs to later Phase 3; not a Phase 02 gap. |

## Human Verification Required

### 1. Explicit Private Disclosure Review

**Test:** After the approval-default defect and five blocking gaps are fixed, issue a fresh challenge, run one provider-backed ingestion privately, invoke the final gate with an explicit approval action, and review gateway, Rust, provider, and verifier output.

**Expected:** One UUID/count converges across HTTP, PostgreSQL, engine status, and LanceDB; no credential, authorization header, raw upload, document/chunk content, or attacker-controlled secret key appears; omitting approval must fail and preserve the evidence.

**Why human:** Private service logs and the disclosure judgment are not available to repository-only verification. The present attestation cannot substitute because its approval can be generated without the flag.

### 2. Recovery Diagnostic Prohibition

**Test:** Exercise restart/status failure diagnostics with inert sentinel-bearing document metadata and storage errors.

**Expected:** Only document identity and safe error classes/context appear; no raw bytes, chunk/provider content, credentials, or attacker-controlled storage values are emitted.

**Why human:** The test-tier prohibition currently has no wired negative test covering recovery/status logs.

## Deferred Items

`DEBT-CR-04`, `DEBT-CR-05`, `DEBT-BU-01`, and `DEBT-BU-02` remain visible and non-blocking while their accepted triggers are false. None of the five current gaps matches a later roadmap phase goal or success criterion; all concern Phase 02's own trustworthy-ingestion outcome and verification integrity.

## Gaps Summary

Plans 02-25 through 02-28 genuinely closed worker-first replay, storage-read error propagation, isolated PostgreSQL claims, category-only privacy diagnostics, and current provider-backed reinspection. They did not complete the phase goal.

Five blockers remain. Two break the core Rust durability/status state machine, one can strand failed admission in PostgreSQL, one makes human approval forgeable, and one leaves the required deterministic Python gate destructive and failing. The last defect also directly falsifies the 02-27 summary claim that the global cleanup glob was removed.

Phase 02 must remain open and must not advance as achieved.

---

_Verified: 2026-07-30T09:58:31Z_
_Verifier: the agent (gsd-verifier)_
