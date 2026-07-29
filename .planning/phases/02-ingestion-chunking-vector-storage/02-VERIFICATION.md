---
phase: 02-ingestion-chunking-vector-storage
verified: 2026-07-29T11:04:51Z
status: gaps_found
score: "12/19 must-haves verified"
behavior_unverified: 2
overrides_applied: 0
unverified_prohibitions: 1
re_verification:
  previous_status: gaps_found
  previous_score: "11/23"
  gaps_closed:
    - "LANCET_CONFIG_DIR startup, valid-request metadata forwarding, durable failed-admission reconciliation, read-only inspection, non-finite embedding rejection, and real schema-field rollback are now implemented and covered."
  gaps_remaining:
    - "Camel-case sensitive field aliases bypass the Python privacy classifier."
    - "Acknowledged queued work is discarded during graceful engine shutdown and later marked failed by polling."
    - "The database integration test can delete every documents row in the configured database."
    - "Oversized chunk settings wrap when stored in PostgreSQL, making persisted settings untruthful."
    - "The live-evidence test writes and deletes the real runtime-artifact paths."
  regressions: []
gaps:
  - truth: "Persisted PostgreSQL chunk settings exactly describe the settings executed by Rust for every accepted request."
    status: failed
    reason: "The gateway accepts a positive machine-sized value, casts it to int32 for PostgreSQL, and passes the original int to gRPC; 2147483648 therefore persists as a negative value while Rust receives a positive value."
    artifacts:
      - path: "gateway/main.go"
        issue: "createDocument validates only positive Atoi results at lines 478-515 before int32 casts."
      - path: "engine/src/main.rs"
        issue: "parse_chunk_settings has no shared upper bound, so it accepts the positive streamed value."
    missing:
      - "Apply one explicit maximum before the gateway cast and in Rust metadata parsing."
      - "Add boundary tests for max, max+1, and PostgreSQL/gRPC equality."
  - truth: "The privacy prohibition fails closed for every normalized forbidden credential, authorization, raw-content, document-text, and chunk-content field class."
    status: failed
    reason: "classify_sensitive_field lowercases and separates punctuation but does not split camel case; the verifier reproduced classify_sensitive_field('rawContent') returning None."
    artifacts:
      - path: "scripts/phase02_live_evidence.py"
        issue: "Lines 110-115 accept rawContent, storedDocumentText, authorizationHeader, and bearerToken aliases."
      - path: "scripts/test_phase02_live_evidence.py"
        issue: "The passing privacy tests contain no camel-case aliases."
    missing:
      - "Canonicalize camel-case boundaries before matching and add fail-first cases for each camel-case alias."
      - "Run the complete Python gate only after its runtime-artifact harness is isolated."
  - truth: "Every acknowledged queued ingestion either reaches a terminal state during graceful shutdown or is durably recovered on restart; polling must not turn accepted work into a false failed result."
    status: failed
    reason: "spawn_worker_with_boundary gives shutdown priority and immediately breaks before receiver.recv(); gateway polling then treats engine NotFound as authoritative and writes failed."
    artifacts:
      - path: "engine/src/main.rs"
        issue: "Lines 867-881 break on shutdown without draining queued jobs or persisting recovery work."
      - path: "gateway/main.go"
        issue: "Lines 558-579 convert engine NotFound for queued/processing rows to failed."
      - path: "engine/src/tests.rs"
        issue: "The only shutdown test covers an active job, not a job already accepted into the queue."
    missing:
      - "Drain accepted jobs before exit or durably requeue staged rows on startup."
      - "Do not terminally fail a matching durable staged row solely because the restarted engine returns NotFound."
      - "Add queued-at-shutdown and restart-recovery behavioral tests."
  - truth: "Phase 02 database verification is isolated and cannot delete documents outside data created by its own test."
    status: failed
    reason: "TestReconciliationIntentClaimLeaseIsExclusive executes DELETE FROM documents with no predicate whenever TEST_DATABASE_URL is set."
    artifacts:
      - path: "gateway/db/document_test.go"
        issue: "Lines 196-218 clean only the generated ID but first delete the entire documents table."
    missing:
      - "Use a per-test database/schema or constrain all setup and cleanup to IDs created by the test."
      - "Add a sentinel-row integration regression proving the test preserves unrelated data."
  - truth: "The live-evidence verification harness cannot overwrite or delete a concurrent human run's challenge or evidence."
    status: failed
    reason: "test_captured_inspector_arguments_explicit_path writes to the real phase runtime paths and unconditionally unlinks both in finally."
    artifacts:
      - path: "scripts/test_phase02_live_evidence.py"
        issue: "Lines 481-572 use CHALLENGE_RUNTIME_PATH and EVIDENCE_RUNTIME_PATH instead of an isolated fixture root."
    missing:
      - "Parameterize runtime paths or run the harness in an isolated fixture checkout."
      - "Save and restore pre-existing files until isolation is in place."
behavior_unverified_items:
  - truth: "The complete issued_at to generated_at run window fails for its dedicated duration classification."
    test: "Use matching challenge and evidence identities with a controlled clock, then exceed only the complete run window."
    expected: "The validator exits nonzero for the complete-run-window reason rather than an earlier identity or freshness failure."
    why_human: "The current overlong fixture changes evidence.issued_at and takes an earlier validation branch; the accepted DEBT-BU-01 records this missing proof."
  - truth: "Caller-owned input remains byte-for-byte unchanged after a successful run and representative early and post-upload failures."
    test: "Run the live runner with a caller-owned sample across success and representative failures, comparing SHA-256 and bytes after each invocation."
    expected: "The caller file survives unchanged; only script-created temporary input is removed."
    why_human: "The present automated test covers one early failure only; success and post-upload paths require live service/provider state."
prohibition_results:
  - statement: "MUST NOT accept credential, authorization-header, raw-upload, stored-document-text, or stored-chunk-content fields in Phase 02 challenge/evidence JSON."
    verification: test
    status: failed
    reason: "The Python classifier misses camel-case aliases, so its standalone privacy gate accepts rawContent."
  - statement: "MUST NOT expose credentials, authorization headers, raw upload bytes, stored document text, or stored chunk content through runtime or service logs."
    verification: judgment
    status: unverified
    flagged: true
    reason: "Private terminal/service logs and a fresh credentialed run are not available to this codebase audit."
human_verification:
  - test: "After the blocker fixes, execute a fresh local credentialed ingestion and direct PostgreSQL/LanceDB reinspection."
    expected: "The HTTP reply, PostgreSQL row, engine status, and explicit-path LanceDB facts agree for one canonical generation."
    why_human: "Provider credentials, service lifecycle, and current durable state are external to the static/test audit."
  - test: "Review private terminal and service logs from that fresh run."
    expected: "No credential, authorization header, raw upload, document text, or chunk content is disclosed."
    why_human: "This is the judgment-tier privacy prohibition."
---

# Phase 2: Ingestion, Chunking & Vector Storage Verification Report

**Phase Goal:** As a Lancet API user, I want to ingest and safely replace text or Markdown documents, so that the last completed LanceDB index and PostgreSQL status remain trustworthy through failures and concurrent polling.

**Verified:** 2026-07-29T11:04:51Z
**Status:** gaps_found
**Re-verification:** Yes — after Plans 02-17 through 02-21

## User Flow Coverage

| Step | Expected | Evidence in the current codebase | Status |
|---|---|---|---|
| Upload | `POST /documents` accepts a multipart text/Markdown document and returns a polling location | `gateway/main.go:449-546`; `go test -count=1 ./...` passed | ✓ VERIFIED |
| Persist settings | PostgreSQL records exactly the chunk strategy/size/overlap Rust executes | First-frame metadata is wired, but `int` → `int32` conversion at `gateway/main.go:478-515` overflows accepted large values | ✗ FAILED |
| Index and replace | The single worker chunks, embeds, writes LanceDB, rolls back a failed replacement, and retries cleanly | Rust suite passed: worker, replacement-boundary, schema rollback, and inspector tests | ✓ VERIFIED |
| Poll/reconcile | Ambiguous admission and definite non-admission converge without a later client poll | Durable reconciliation intent/reconciler is wired in `gateway/main.go:271-428`; Go suite passed | ✓ VERIFIED |
| Survive shutdown | Acknowledged queued jobs remain trustworthy across a graceful shutdown/restart | Worker breaks before consuming queued jobs; gateway converts post-restart NotFound to failed | ✗ FAILED |
| Outcome | The last completed index and PostgreSQL status remain trustworthy through failure and concurrent polling | Privacy enforcement, chunk-setting truthfulness, shutdown recovery, and safe verification remain broken | ✗ FAILED |

The MVP outcome clause is not achieved. The normal ingestion path works, but an accepted document can be falsely failed after shutdown, and the declared safety/verification controls do not fail closed.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | HTTP upload creates a PostgreSQL-backed polling record for text/Markdown input. | ✓ VERIFIED | Gateway handler and full Go suite passed. |
| 2 | Rust receives validated streamed bytes and uses one sequential worker. | ✓ VERIFIED | `cargo test` passed `worker_indexes_jobs_and_records_real_chunk_count` and metadata-contract tests. |
| 3 | Persisted settings always equal Rust-executed settings. | ✗ FAILED | Accepted `2147483648` can persist as negative `int32` while Rust receives positive `usize`. |
| 4 | Structure-aware/fixed-size chunking and o200k token estimates work. | ✓ VERIFIED | Full Rust chunker suite passed. |
| 5 | The OpenRouter client enforces the locked timeout/retry/concurrency contract. | ✓ VERIFIED | Full Rust suite passed the production-builder timeout and retry/concurrency tests. |
| 6 | Chunks, embeddings, metadata, and graph rows persist in LanceDB. | ✓ VERIFIED | Worker and real-LanceDB inspector fixtures passed. |
| 7 | Failed same-ID replacements roll back and a clean retry converges. | ✓ VERIFIED | `replacement_failure_boundaries_preserve_prior_generation_and_retry_converges` passed. |
| 8 | Failed admission has durable PostgreSQL reconciliation independent of GET polling. | ✓ VERIFIED | Intent schema/query surface and reconciler are production-wired; Go suite passed. |
| 9 | Lost acknowledgement, terminal races, NotFound repair, and response identity are guarded. | ✓ VERIFIED | Current gateway flows and named Go suite coverage pass. |
| 10 | The engine honors `LANCET_CONFIG_DIR` from a config-less working directory. | ✓ VERIFIED | All three `config_startup` integration tests passed. |
| 11 | Community/node/edge placeholder schemas have the required nullable fields. | ✓ VERIFIED | Rust DB schema tests passed. |
| 12 | `EntityResolver` and the production-used `ExactMatchResolver` exist. | ✓ VERIFIED | DB resolver test passed and production worker imports the shared DB module. |
| 13 | Inspector validation is read-only, non-disclosing, and rejects null/NaN/+∞/−∞ vectors; true schema drift rolls back without killing the worker. | ✓ VERIFIED | 18 inspector tests and the active-worker schema-fault test passed. |
| 14 | Privacy checks reject every forbidden normalized field class. | ✗ FAILED | `rawContent` is classified as `None`; the passing suite lacks camel-case cases. |
| 15 | A fresh provider-backed run is independently traceable to current durable state. | ⚠ PRESENT_BEHAVIOR_UNVERIFIED | Code and deterministic tests exist, but no retained challenge/evidence or live service/provider result was available. |
| 16 | Complete-run-window and full caller-owned-input cleanup invariants hold. | ⚠ PRESENT_BEHAVIOR_UNVERIFIED | Existing fixtures miss the dedicated run-window branch and live success/post-upload file preservation. |
| 17 | Queued acknowledged work survives shutdown/restart without false failure. | ✗ FAILED | Shutdown wins the biased select and breaks; no recovery exists. |
| 18 | Database verification cannot delete data outside its fixture scope. | ✗ FAILED | Integration test issues unqualified `DELETE FROM documents`. |
| 19 | Live-evidence tests cannot destroy concurrent runtime evidence. | ✗ FAILED | The process-argument test writes/deletes the real runtime paths. |

**Score:** 12/19 truths verified; 2 present but behavior-unverified.

### Roadmap Success Criteria

All seven narrow roadmap criteria have substantive implementation and automated evidence: HTTP upload, gRPC chunking, LanceDB storage, schema placeholders, resolver, and worker structure. They do not cover the shutdown/recovery, privacy, and verification-isolation failures above, so satisfying those criteria alone does not establish the user-story outcome.

## Required Artifacts

| Artifact group | L1/L2 | Wiring and data flow | Status |
|---|---|---|---|
| `gateway/main.go`, generated PostgreSQL queries, and schema | Exists and substantive | HTTP → PostgreSQL → gRPC → polling/reconciler is wired; setting overflow and shutdown repair are unsafe | ⚠ PARTIAL |
| `proto/lancet/v1/lancet.proto` and generated bindings | Exists and substantive | First-frame metadata and status RPCs are used by Go and Rust | ✓ VERIFIED |
| `engine/src/chunker/*`, `engine/src/client/*` | Exists and substantive | Worker invokes chunker/client; full Rust behavioral tests pass | ✓ VERIFIED |
| `engine/src/db/*`, `engine/src/main.rs`, `engine/src/tests.rs` | Exists and substantive | Worker → replacement → LanceDB flows; rollback/error paths pass, queued-shutdown path fails | ⚠ PARTIAL |
| `engine/src/bin/inspect_lancedb.rs` and its tests | Exists and substantive | Uses `DatabaseManager::open_and_validate`, real fixture data, and class-only errors | ✓ VERIFIED |
| `scripts/phase02_live_evidence.py`, shell runners, and Python tests | Exists and substantive | Config path and explicit inspector flow are wired; privacy classifier and test isolation are defective | ✗ PARTIAL |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| HTTP upload | PostgreSQL | `InsertDocument` | ✓ WIRED | Handler persists the document before streaming and tests cover the normal route. |
| PostgreSQL settings | gRPC first frame | `grpcEngine.Ingest` metadata | ⚠ PARTIAL | Valid values flow, but no upper-bound prevents the stored/executed mismatch. |
| gRPC intake | Tokio worker | bounded channel / `spawn_worker_with_boundary` | ✗ NOT SAFE | Acceptance is wired but shutdown drops queued receiver items. |
| Worker | LanceDB replacement | `process_job_with_boundary` | ✓ WIRED | Rollback/retry and schema-fault tests exercise this path. |
| Definitive non-admission | durable PostgreSQL intent | `compensateFailedIngest` / `durableReconciler` | ✓ WIRED | Production handoff and background reconciliation are present. |
| Inspector | existing LanceDB tables | `open_and_validate` | ✓ WIRED | Missing-table and immutability fixtures passed. |
| Live validator | privacy and exact store selection | Python helper before inspection | ✗ NOT SAFE | Camel-case aliases bypass the privacy checker; its full regression harness is unsafe to run concurrently. |

## Data-Flow Trace (Level 4)

| Artifact | Data variable | Source | Produces real data | Status |
|---|---|---|---|---|
| Gateway upload | `Document` status/chunk settings | multipart values → `InsertDocument` | Yes for normal values; `int32` storage can corrupt oversized settings | ⚠ PARTIAL |
| Rust worker | `IngestionJob` / chunks / embeddings | gRPC stream → queue → chunker/client → LanceDB | Yes; real embedded-LanceDB fixtures pass | ✓ FLOWING |
| Durable reconciler | `document_reconciliation_intents` | PostgreSQL claim/lease/update queries | Yes in Go tests; unrelated queued engine jobs have no recovery contract | ⚠ PARTIAL |
| Inspector | row-derived identity/integrity facts | explicit LanceDB path and filtered table reads | Yes; adversarial fixtures pass | ✓ FLOWING |
| Live evidence | challenge/evidence privacy and path facts | Python validator plus exact inspector path | Real inputs are parsed, but camel-case privacy classification is hollow | ✗ HOLLOW GUARD |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Gateway and DB packages | `go test -count=1 ./...` in `gateway` | Passed; integration test requiring `TEST_DATABASE_URL` did not run | ✓ PASS, coverage limitation |
| Go static analysis | `go vet ./...` in `gateway` | Passed | ✓ PASS |
| Rust implementation | `cargo test --manifest-path engine/Cargo.toml` | 4 DB + 24 engine + 18 inspector + 3 config-startup tests passed | ✓ PASS |
| Rust lint/format | `cargo clippy --all-targets -- -D warnings`; `cargo fmt -- --check` | Both passed | ✓ PASS |
| Python privacy subset | `python -O -I scripts/test_phase02_live_evidence.py -k privacy` | 4 tests passed, none exercises camel-case aliases | ✓ PASS, misleading coverage |
| Camel-case privacy probe | `python -O -I -c "...classify_sensitive_field('rawContent')..."` | Printed `None` | ✗ FAIL |
| Shell syntax | Git Bash `-n` for both shell scripts | Passed | ✓ PASS |
| Full Python live-evidence suite | Not run | Contains a test that writes/deletes real runtime artifacts; unsafe until isolated | ? SKIPPED FOR SAFETY |

## Probe Execution

No `probe-*.sh` scripts are declared or present. The executable Phase 02 checks are the Rust, Go, Python, and Bash surfaces above.

## Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|---|---|---|---|---|
| DATA-01 | 02-01, 04-07, 09-12, 15-19, 21 | Ingest lightweight text-like documents | ⚠ PARTIAL | Upload route works, but accepted queued work can be lost at shutdown and privacy validation fails closed incorrectly. |
| DATA-02 | 02-01, 02, 05, 06, 09, 10, 16, 17, 21 | Structure-aware and fixed-size chunking | ⚠ PARTIAL | Both implementations work; accepted oversized settings make persisted metadata false. |
| DATA-03 | 02-03, 05-10, 12-16, 20-21 | Persist chunks and metadata in LanceDB | ⚠ PARTIAL | Persistence/rollback tests pass, but a queued accepted job can be abandoned before persistence. |
| DATA-06 | 02-03, 05, 06, 09, 10, 13, 16, 20 | Community IDs and communities placeholder table | ✓ SATISFIED | DB schema and read-only validation tests pass. |
| DATA-07 | 02-03, 05-07, 09, 10, 13, 14, 16, 20 | Nullable node summary fields | ✓ SATISFIED | Canonical schema and Arrow-null tests pass. |
| DATA-08 | 02-03, 05-10, 13, 14, 16, 20 | Separate node/edge tables and edge summaries | ✓ SATISFIED | Schema/inspector fixtures pass. |
| DATA-09 | 02-03, 09, 10, 13, 16, 20 | Async resolver and exact-match default | ✓ SATISFIED | Resolver tests and worker use pass. |
| RAG-06 | 02-02, 04-07, 09, 10, 14, 16, 20 | Async background worker structure | ⚠ PARTIAL | Worker exists and processes active work, but graceful shutdown loses queued accepted work. |

Every Phase 02 requirement ID declared in plan frontmatter is accounted for. No requirement ID is orphaned from the plans.

## Fresh Review Finding Impact

| Review finding | Independent current-code verdict | Goal impact |
|---|---|---|
| CR-01 camel-case privacy bypass | CONFIRMED: `rawContent` classifies as `None` | BLOCKER — test-tier privacy prohibition fails. |
| CR-02 unqualified test deletion | CONFIRMED: `DELETE FROM documents` has no predicate | BLOCKER — running the integration suite against a mispointed DB can cause data loss. |
| CR-03 queued shutdown loss | CONFIRMED: shutdown has priority over `receiver.recv`; gateway writes failed after NotFound | BLOCKER — directly defeats trustworthy accepted-ingestion status. |
| WR-01 oversized chunk settings wrap | CONFIRMED: positive `int` is narrowed to `int32` without a bound | BLOCKER — durable settings can lie about executed chunking. |
| WR-02 live test destroys runtime artifacts | CONFIRMED: test uses real paths and unlinks them in `finally` | WARNING — verification can corrupt concurrent run evidence; treated as a failed harness truth. |

The accepted Phase 02 debt record covers only the older local-only/resource-bound and two behavior-proof boundaries. It does not accept or schedule these fresh review findings; no later roadmap success criterion clearly addresses them, so none is deferred.

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `gateway/db/document_test.go` | 214 | Unqualified destructive SQL in an integration test | 🛑 BLOCKER | Can erase all documents in the configured database. |
| `engine/src/main.rs` | 867-881 | Shutdown-priority receive loop | 🛑 BLOCKER | Drops accepted queued documents. |
| `scripts/phase02_live_evidence.py` | 110-115 | Incomplete normalization guard | 🛑 BLOCKER | Lets camel-case sensitive fields pass the privacy checker. |
| `scripts/test_phase02_live_evidence.py` | 481-572 | Test reuses live runtime paths | ⚠ WARNING | Can overwrite/delete in-progress validation evidence. |
| `engine/src/main.rs` | 420 | Placeholder RAG response | ℹ INFO | Explicitly deferred to Phase 03; outside this phase's ingestion scope. |

No unreferenced `TBD`, `FIXME`, or `XXX` markers were found in Phase 02 implementation files.

## Human Verification Required

These checks remain required after the blocking fixes; they do not turn the current `gaps_found` disposition into a pass.

### 1. Fresh provider and durable-store reconciliation

**Test:** Run a fresh local credentialed ingestion after issuing a new challenge, then inspect HTTP, PostgreSQL, engine status, and the explicit LanceDB path.

**Expected:** All sources name the same document ID and completed generation; count, provider/model, vector width, and continuity agree.

**Why human:** Provider credentials and service lifecycle are external to this code audit.

### 2. Exact run-window and caller-file invariants

**Test:** Execute the two `behavior_unverified_items` scenarios with a controlled clock and caller-owned sample.

**Expected:** The dedicated run-window failure occurs, and input bytes remain unchanged on success and representative failure paths.

**Why human:** Current fixtures do not exercise those runtime branches.

### 3. Private disclosure surfaces

**Test:** Review private shell/service logs from the fresh run.

**Expected:** No credential, authorization header, raw bytes, stored document text, or stored chunk content is present.

**Why human:** Logs are intentionally unavailable to this repository audit.

## Gaps Summary

Phase 02 has a real normal-path implementation and many prior gaps are closed, but the phase goal remains unachieved. The five blockers above prevent the system from claiming trustworthy completion: a user-accepted queued job can be falsely terminally failed after shutdown; chunk metadata can disagree with the actual work; the privacy guard is bypassable; and verification code can delete unrelated data or active evidence.

---

_Verified: 2026-07-29T11:04:51Z_
_Verifier: the agent (gsd-verifier)_

## Verification Complete
