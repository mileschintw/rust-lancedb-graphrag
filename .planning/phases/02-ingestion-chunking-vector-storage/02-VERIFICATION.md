---
phase: 02-ingestion-chunking-vector-storage
verified: 2026-07-29T02:28:16Z
status: gaps_found
score: "11/23 must-haves verified"
behavior_unverified: 4
overrides_applied: 0
unverified_prohibitions: 2
re_verification:
  previous_status: gaps_found
  previous_score: "11/18"
  gaps_closed:
    - "Ambiguous final gRPC acknowledgement loss is resolved against authoritative engine status and no longer automatically marks an admitted document failed."
    - "Stale challenges, caller-owned sample deletion, nested Rust source ignores, explicit inspector path resolution, and embedding child validation were implemented."
    - "Current Rust, Go, Python, Bash, lint, and privacy fixture gates are green."
  gaps_remaining:
    - "Definitive non-admission compensation is bounded to five attempts and has no durable handoff."
    - "The privacy prohibition is still not fully machine-wired or human-verifiable from retained evidence."
  regressions: []
gaps:
  - truth: "The Rust engine honors the supported LANCET_CONFIG_DIR configuration root and can start from a config-less working directory."
    status: failed
    reason: "engine/src/main.rs ignores LANCET_CONFIG_DIR; an independent process probe exited 1 with configuration file \"config/config\" not found."
    artifacts:
      - path: "engine/src/main.rs"
        issue: "load_settings at lines 58-73 probes only ../config/config.toml and config/config.toml."
    missing:
      - "Resolve the base and environment overlay from LANCET_CONFIG_DIR before applying LANCET_ overrides."
      - "Add a process-level engine startup/config test from a config-less directory."
  - truth: "The chunk strategy, size, and overlap recorded in PostgreSQL are the values the Rust engine receives and executes."
    status: failed
    reason: "The gateway records the non-canonical strategy \"recursive\" and sends no metadata, while Rust defaults to structure-aware and silently maps unknown strategies to structure-aware."
    artifacts:
      - path: "gateway/main.go"
        issue: "grpcEngine.Ingest lines 134-160 omits request Metadata; createDocument line 260 persists ChunkStrategy \"recursive\"."
      - path: "engine/src/main.rs"
        issue: "chunk_ingestion_job lines 173-199 treats every non-fixed strategy as structure-aware."
    missing:
      - "Persist a canonical strategy name and stream the persisted strategy, size, and overlap."
      - "Reject unknown strategies and add an end-to-end metadata propagation test."
  - truth: "Every definitive non-admission eventually reaches a terminal PostgreSQL state without requiring a later client poll."
    status: failed
    reason: "compensateFailedIngest stops after five failed updates and records no durable reconciliation intent; its passing test succeeds on attempt three and does not exercise exhaustion."
    artifacts:
      - path: "gateway/main.go"
        issue: "Lines 199-217 return after a fixed five-attempt loop with no durable handoff."
      - path: "gateway/main_test.go"
        issue: "TestCompensationRetriesUntilTerminalConvergence at lines 291-302 covers two transient failures only."
    missing:
      - "Persist reconciliation work transactionally and retry until terminal convergence or a terminal winner."
      - "Add an exhaustion/restart test that proves eventual repair without a GET request."
  - truth: "The network-facing ingestion path is authorized and bounded before request bodies and gRPC streams consume unbounded concurrent resources."
    status: failed
    reason: "POST /documents has no authentication or quota middleware, the server binds all interfaces, lacks body read/write/idle deadlines and an upload semaphore, and Rust reserves queue capacity only after buffering the full stream."
    artifacts:
      - path: "gateway/main.go"
        issue: "Lines 219-225 expose upload directly; line 389 binds :port with only ReadHeaderTimeout."
      - path: "engine/src/main.rs"
        issue: "Lines 255-288 buffer up to 10 MiB per stream before try_reserve_owned."
    missing:
      - "Bind loopback for a local-only product or add authenticated/TLS ingress with quotas."
      - "Add HTTP body deadlines, a bounded upload semaphore, and pre-buffer engine admission."
      - "Exercise slow-body and concurrent-stream exhaustion paths."
  - truth: "The durable inspector is read-only and never emits untrusted persisted content through diagnostic errors."
    status: failed
    reason: "An unknown embedding_model value is interpolated into an error, and the inspector calls DatabaseManager::initialize, which creates any missing tables before inspection."
    artifacts:
      - path: "engine/src/bin/inspect_lancedb.rs"
        issue: "Lines 196-199 serialize the unknown stored model value; line 366 uses the mutating initializer."
      - path: "engine/src/db/mod.rs"
        issue: "initialize_tables at lines 24-49 creates absent tables."
    missing:
      - "Return a class-only unknown-model error."
      - "Provide a read-only open-and-validate path that fails when an expected table is absent."
  - truth: "The live gate fails closed on missing prerequisites and inspects exactly the committed verification store before cleanup."
    status: failed
    reason: "Node privacy enforcement is optional, malformed TOML falls back to regex/hardcoded paths, relative paths depend on caller CWD, and the declared summaries-to-challenge preflight key link is absent."
    artifacts:
      - path: "verify-live-evidence.sh"
        issue: "Lines 80-103 issue a challenge without checking 02-11 through 02-15 summaries or full closure gates; lines 135-153 skip Node and tolerate config errors."
      - path: "verify-ingestion.sh"
        issue: "Lines 153-166 tolerate configuration errors and may inspect a fallback store."
      - path: "scripts/test_phase02_live_evidence.py"
        issue: "The explicit-path test at lines 359-364 searches source text instead of capturing process arguments."
    missing:
      - "Require Node and strict TOML parsing, resolve the store against repository root, validate it, and abort on any error."
      - "Wire the deterministic-closure preflight into challenge issuance."
      - "Use a config-less fake-command harness to assert exact inspector arguments."
  - truth: "The structured privacy prohibition has complete test-tier enforcement and covers every forbidden field class."
    status: failed
    reason: "The prohibition descriptors omit check_rule, the Node vocabulary is narrower than the production validator, and final validation silently skips the check if Node is unavailable."
    artifacts:
      - path: ".planning/phases/02-ingestion-chunking-vector-storage/02-15-PLAN.md"
        issue: "Lines 46-51 define check_kind, check_target, and fixtures but no check_rule."
      - path: ".planning/phases/02-ingestion-chunking-vector-storage/02-16-PLAN.md"
        issue: "Lines 84-89 repeat the incomplete descriptor."
      - path: "scripts/test_phase02_privacy_prohibition.cjs"
        issue: "Lines 6-14 omit credential, bearer, authorization_header, raw_content, document_text, and chunk_content classes recognized by the Python validator."
    missing:
      - "Add the required deterministic check_rule projection."
      - "Share one canonical forbidden-field classifier and add a known-bad fixture for each class."
      - "Fail closed when the privacy test runner is unavailable."
behavior_unverified_items:
  - truth: "The complete issued_at to generated_at run window is rejected for the intended duration reason under optimized isolated Python."
    test: "Use matching challenge/evidence issued_at values and a controlled clock so the complete-run-window branch, not challenge mismatch or stale-challenge validation, is exercised."
    expected: "The helper exits nonzero with the complete-run-window classification."
    why_human: "The current overlong-run case changes only evidence.issued_at and fails earlier on challenge mismatch; the branch is not behaviorally proven."
  - truth: "Caller-owned input survives both successful ingestion and every early-failure path."
    test: "Run the live script once successfully and at representative pre-upload/post-upload failures with a caller-owned file, then compare bytes."
    expected: "The caller file remains byte-for-byte unchanged in every case."
    why_human: "The automated test exercises one early failure only; success requires live services/provider state."
  - truth: "The inspector rejects NaN, positive infinity, and negative infinity child values."
    test: "Persist one fixture for each non-finite Float32 variant and run the inspector against each."
    expected: "Each invocation fails closed without printing the vector or stored value."
    why_human: "The production is_finite branch is present, but the named test creates only a null child."
  - truth: "A real missing schema field after version capture rolls back, records failed worker state, keeps the worker alive, and permits clean retry."
    test: "Inject an actual missing-field lookup after version capture and assert all canonical rows, worker state, worker liveness, and retry convergence."
    expected: "The prior generation remains, failed state is recorded, the worker accepts another job, and retry produces one generation."
    why_human: "The named schema-field test injects NodesAdd instead and checks neither worker state nor liveness."
unverified_prohibition_items:
  - statement: "MUST NOT accept credential, authorization-header, raw-upload, stored-document-text, or stored-chunk-content fields in Phase 02 challenge/evidence JSON."
    verification: test
    status: unverified
    flagged: true
    reason: "Descriptor lacks check_rule; classifier coverage and final-gate execution are incomplete."
  - statement: "MUST NOT expose credentials, authorization headers, raw upload bytes, stored document text, or stored chunk content through runtime/service logs, summaries, staged files, or commits."
    verification: judgment
    status: unverified
    flagged: true
    reason: "Transient artifacts and private logs are unavailable, and the inspector has a confirmed persisted-value disclosure sink."
---

# Phase 2: Ingestion, Chunking & Vector Storage Verification Report

**Phase Goal:** As a Lancet API user, I want to ingest and safely replace text or Markdown documents, so that the last completed LanceDB index and PostgreSQL status remain trustworthy through failures and concurrent polling.
**Verified:** 2026-07-29T02:28:16Z
**Status:** gaps_found
**Re-verification:** Yes — fresh verification after Plans 02-11 through 02-16

## User Flow Coverage

User story: “As a Lancet API user, I want to ingest and safely replace text or Markdown documents, so that the last completed LanceDB index and PostgreSQL status remain trustworthy through failures and concurrent polling.”

| Step | Expected | Current evidence | Status |
|---|---|---|---|
| Submit a document | A text or Markdown file is accepted and a polling location is returned | `gateway/main.go:239-290`; Go tests pass | ✓ VERIFIED |
| Queue the same persisted settings | PostgreSQL and Rust agree on strategy, size, and overlap | `gateway/main.go:134-160,260`; metadata is omitted and `"recursive"` is not a Rust strategy | ✗ FAILED |
| Chunk, embed, and index | The worker uses the locked chunker/OpenRouter contracts and persists canonical LanceDB rows | `engine/src/main.rs:698-729`; Rust tests and current durable inspection pass | ✓ VERIFIED |
| Safely replace | Every tested canonical mutation failure preserves the prior generation and retry converges | `engine/src/main.rs:681-695`; replacement boundary tests pass | ✓ VERIFIED |
| Poll concurrent terminal state | Lost acknowledgement, terminal races, NotFound, and response identity converge safely | `gateway/main.go:266-353`; focused Go tests pass | ✓ VERIFIED |
| Recover definitive admission failure | A failed admission cannot remain queued after bounded request work ends | `gateway/main.go:199-217`; compensation can exhaust without durable handoff | ✗ FAILED |
| Outcome | The last completed index and PostgreSQL status remain trustworthy through failures and concurrent polling | Happy-path stores converge, but config, metadata, compensation, resource-bound, inspector, and privacy gaps remain | ✗ FAILED |

The MVP outcome clause is not achieved. The happy path exists, but the failure semantics required by “safely replace” and “remain trustworthy” are not consistently true.

## Goal Achievement

### Observable Truths

The 23 truths below are the deduplicated roadmap/PLAN contract. All 75 literal PLAN truth statements are traced in the next table.

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Users can upload text or Markdown and receive a PostgreSQL-backed polling record. | ✓ VERIFIED | `gateway/main.go:239-290`; Go suite passes. |
| 2 | Persisted chunk settings are exactly the settings executed by Rust. | ✗ FAILED | PostgreSQL stores `"recursive"`; gRPC metadata is empty; Rust defaults independently. |
| 3 | Rust honors `LANCET_CONFIG_DIR` and starts outside the repository. | ✗ FAILED | Independent process probe exited 1 with `configuration file "config/config" not found`. |
| 4 | Rust receives streamed bytes, validates identity/size, and dispatches a single-consumer worker. | ✓ VERIFIED | `engine/src/main.rs:255-303,748-793`; tests pass. |
| 5 | Ingestion capacity is bounded before concurrent bodies/streams consume memory and connection time. | ✗ FAILED | Queue reserve occurs only after full buffering; gateway lacks upload concurrency/body deadlines. |
| 6 | Structure-aware/fixed chunking and o200k token estimates use 500/50 defaults. | ✓ VERIFIED | `engine/src/chunker/mod.rs:24-74`; chunker tests pass. |
| 7 | OpenRouter uses the locked model, 2048 dimensions, 10-second timeout, four attempts, 1/2/4 backoff, and cap five. | ✓ VERIFIED | `engine/src/client/mod.rs:7-16,77-115`; timeout/retry/concurrency tests pass. |
| 8 | Raw bytes, chunks, metadata, embeddings, and graph edges flow to LanceDB. | ✓ VERIFIED | Worker/persistence tests pass; current inspector reports one document, two nodes, one edge. |
| 9 | Canonical replacement mutation failures roll back and retry converges to one generation. | ✓ VERIFIED | Both replacement failure/retry tests pass. |
| 10 | Lost acknowledgement, terminal race, NotFound repair, and response identity are handled. | ✓ VERIFIED | `gateway/main.go:266-353`; named Go tests pass. |
| 11 | Definitive non-admission always reaches a terminal PostgreSQL state. | ✗ FAILED | Five-attempt compensation can stop with the row queued. |
| 12 | Nodes/edges/communities schemas contain all Phase 02 placeholder fields with required nullability. | ✓ VERIFIED | `engine/src/db/mod.rs:122-185`; schema tests pass. |
| 13 | Async `EntityResolver` and production-used `ExactMatchResolver` exist. | ✓ VERIFIED | `engine/src/db/mod.rs:188-212`; use at `engine/src/main.rs:603-628`; test passes. |
| 14 | Explicit-path inspection derives current model/generation/continuity/edge facts. | ✓ VERIFIED | Process test passes; current durable reinspection passed. |
| 15 | Every null/non-finite embedding child variant is behaviorally rejected. | ⚠ PRESENT_BEHAVIOR_UNVERIFIED | Code uses `is_finite`, but the test creates only a null child. |
| 16 | Inspection is read-only and errors cannot disclose persisted values. | ✗ FAILED | Unknown model is interpolated; initialization creates absent tables. |
| 17 | Challenge freshness, exact ignores, success-only cleanup, and caller-owned-file gating are present. | ✓ VERIFIED | Python suite, ignore probes, Bash syntax, and source wiring pass; full caller-file coverage remains below. |
| 18 | Live validation requires all prerequisites and selects exactly the committed store. | ✗ FAILED | Optional Node, permissive config fallback, relative path, and absent preflight key link. |
| 19 | A fresh post-closure OpenRouter run is independently challenge-bound and converged across HTTP, PostgreSQL, engine status, and LanceDB. | ? UNCERTAIN | Current PostgreSQL/LanceDB rows converge, but deleted artifacts prevent provenance replay and HTTP/engine status was unavailable. |
| 20 | Structured privacy enforcement covers every forbidden field class. | ✗ FAILED | Missing `check_rule`, narrower Node classifier, optional final invocation. |
| 21 | Nondeterministic credential/log/content surfaces are proven non-disclosing. | ✗ FAILED | Historical human review is only a summary claim; inspector has a confirmed disclosure sink. |
| 22 | Schema-lookup drift after snapshot is behaviorally proven to roll back without killing the worker. | ⚠ PRESENT_BEHAVIOR_UNVERIFIED | Production Result funnel exists; the named test injects `NodesAdd`, not missing schema. |
| 23 | Complete run-window and caller-owned-file cleanup invariants are behaviorally proven. | ⚠ PRESENT_BEHAVIOR_UNVERIFIED | Current tests miss the intended overlong reason and successful caller-file path. |

**Score:** 11/23 merged truths verified; 4 present but behavior-unverified; 1 external/historical truth uncertain; 7 failed.

### All PLAN Truth Traceability

This table accounts for every literal `must_haves.truths` entry. “Not verified” items are identified by concern rather than repeating superseded duplicates.

| Plan | Truths verified | Artifacts / key links | Non-verified contract items |
|---|---:|---|---|
| 02-01 | 1/2 | 3 artifacts exist; HTTP route wired | Rust startup/config truth fails on `LANCET_CONFIG_DIR`. |
| 02-02 | 3/3 | Chunker files substantive and production-wired | None. |
| 02-03 | 3/3 | Client/database files substantive and production-wired | None. |
| 02-04 | 2/2 | Gateway/worker files substantive and wired | None. |
| 02-05 | 9/10 | Replacement/inspector/live-tool links mostly wired | Enqueue-failure terminal compensation is not durable. |
| 02-06 | 4/6 | Transient JSON artifacts intentionally absent; code links present | Historical provider provenance is uncertain; validator can select wrong store. |
| 02-07 | 5/5 | Rollback/null/compensation artifacts and named links exist | The bounded compensation truth passes literally; eventual durability fails later 02-11 truth. |
| 02-08 | 4/4 | Client/inspector durable-row links verified | None. |
| 02-09 | 5/6 | Python and inspector links wired; exact ignores pass | Broad fail-closed gate claim fails on prerequisites/store selection. |
| 02-10 | 1/6 | Runtime artifacts absent after claimed cleanup | Four historical live-run truths are not independently replayable; privacy truth fails. |
| 02-11 | 3/5 | Ambiguity/NotFound/identity links wired | Fixed-cap compensation contradicts both “eventually” and “until terminal” truths. |
| 02-12 | 3/4 | Ownership and ignore links present | Complete-run-window behavioral test fails for the wrong reason. |
| 02-13 | 3/4 | Explicit path/shared DB links wired | Non-finite variants lack behavioral fixtures. |
| 02-14 | 3/4 | Result funnel wired; Clippy green | “Missing-field/worker survival” test does not exercise its named behavior. |
| 02-15 | 2/4 | Test/fixture links exist | Descriptor/classifier incomplete; nondeterministic review cannot be independently verified. |
| 02-16 | 1/7 | Explicit-path command text present | Summary-to-challenge link absent; live claims historical; privacy incomplete; script-argument test is source-only. |

Literal PLAN accounting: **52/75 verified**. The headline score uses merged truths so repeated live-gate and gap-closure wording does not inflate the denominator.

## Required Artifacts

| Artifact | L1/L2 | Wiring/data flow | Status |
|---|---|---|---|
| `gateway/main.go` | Exists, 394 lines, substantive | HTTP → PostgreSQL → gRPC → polling flows; settings/reconciliation/security incomplete | ✗ PARTIAL |
| `gateway/db/schema.sql`, `schema.hcl`, `query.sql`, generated queries | Exist and substantive | Insert/Get/conditional Update used by gateway and DB tests | ✓ VERIFIED |
| `proto/lancet/v1/lancet.proto` | Exists, substantive | Generated Go/Rust clients include metadata and status RPCs | ✓ VERIFIED |
| `engine/src/chunker/mod.rs` and tests | Exist, substantive | Called by `process_job`; tests pass | ✓ VERIFIED |
| `engine/src/client/mod.rs` and tests | Exist, substantive | Production worker uses `OpenRouterClient`; behavioral tests pass | ✓ VERIFIED |
| `engine/src/db/mod.rs`, `lib.rs`, and tests | Exist, substantive | Shared by engine/inspector; real LanceDB rows flow | ✓ VERIFIED |
| `engine/src/main.rs` and tests | Exist, substantive | gRPC → queue → chunker → OpenRouter → replacement is wired | ⚠ PARTIAL |
| `engine/src/bin/inspect_lancedb.rs` and tests | Exist, substantive | Durable data flows, but inspection mutates missing-table state and can disclose a stored value | ✗ PARTIAL |
| `scripts/phase02_live_evidence.py` and tests | Exist, substantive | Shell subcommands use isolated Python; some named tests are false positives | ⚠ PARTIAL |
| `verify-ingestion.sh`, `verify-live-evidence.sh` | Exist, Bash syntax passes | Live path wired; prerequisites/store resolution fail open | ✗ PARTIAL |
| Privacy Node test and two fixtures | Exist, substantive | Environment subject injection works for current fixtures | ✗ PARTIAL |
| `.gitignore` | Exists | Exact private artifacts ignored; nested Rust source no longer ignored | ✓ VERIFIED |
| Phase-local challenge/evidence JSON | Intentionally absent | Absence is expected after cleanup but prevents independent provenance replay | ? HISTORICAL |

## Key Link and Data-Flow Verification

| From | To | Via | Status | Evidence |
|---|---|---|---|---|
| HTTP upload | PostgreSQL | `InsertDocument` | ✓ WIRED | `gateway/main.go:260`; current row exists. |
| HTTP upload | Rust gRPC | client stream | ⚠ PARTIAL | Bytes/identity flow, metadata does not. |
| Rust gRPC | bounded worker | reserved mpsc permit | ⚠ PARTIAL | Wired, but reservation follows full stream buffering. |
| Worker | chunker → OpenRouter → LanceDB | `process_job` / replacement | ✓ FLOWING | Tests and current durable rows pass. |
| Replacement errors | rollback | single post-snapshot result funnel | ✓ WIRED | Exact mutation tests pass. |
| Ambiguous acknowledgement | engine status | detached lookup | ✓ WIRED | Named lost-ack test passes. |
| Definitive rejection | PostgreSQL terminal state | compensation | ✗ NOT DURABLE | Stops after five attempts. |
| Inspector | current LanceDB | explicit path/filter projections | ⚠ PARTIAL | Data flows; read-only/privacy properties fail. |
| Deterministic closure | challenge issuance | preflight | ✗ NOT WIRED | `--prepare-gate` does not check closure summaries/full gates. |
| Live validator | privacy test | Node test | ⚠ OPTIONAL | Executed only when `node` is found. |
| Live scripts | verification store | TOML → `--lancedb-path` | ⚠ PARTIAL | Argument exists; parsing can fall back or be CWD-relative. |
| Prohibition descriptor | Node test/fixture | check metadata | ✗ PARTIAL | `check_rule` is missing and vocabulary is incomplete. |

## Current Durable Data Trace

The UUID from `02-16-SUMMARY.md` was used only as a locator; the current stores were queried independently.

| Source | Current result | Assessment |
|---|---|---|
| PostgreSQL | `completed|2|recursive|500|50`, created `2026-07-29 01:54:32.647427` | Terminal row exists and count is positive; strategy is non-canonical. |
| Explicit-path LanceDB inspector | one document, zero staged rows, two nodes, one edge, width 2048, one generation, locked model, contiguous indexes | Current PostgreSQL/LanceDB counts converge. |
| `02-16-SUMMARY.md` | Claims three nodes and two edges | Not current/accurate evidence; summary counts differ from durable rows. |
| Challenge/evidence JSON | Both absent, ignored, untracked, unstaged | Expected cleanup, but exact challenge/time/privacy provenance is no longer independently auditable. |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Rust implementation | `cargo test --manifest-path engine/Cargo.toml` | 4 lib + 22 engine + 11 inspector tests passed | ✓ PASS |
| Rust format | `cargo fmt --manifest-path engine/Cargo.toml -- --check` | Exit 0 | ✓ PASS |
| Rust all-target lint | `cargo clippy --manifest-path engine/Cargo.toml --all-targets -- -D warnings` | Exit 0 | ✓ PASS |
| Gateway and DB | `go test -count=1 ./...` | All packages passed | ✓ PASS |
| Go static analysis | `go vet ./...` | Exit 0 | ✓ PASS |
| Optimized isolated evidence suite | `PYTHONOPTIMIZE=1 python -O -I scripts/test_phase02_live_evidence.py` | 7 tests passed; a cp950 reader-thread decode warning occurred | ✓ PASS with portability warning |
| Shell parse | Git Bash `-n` for both scripts | Exit 0 | ✓ PASS |
| Privacy clean control | `GSD_PROHIB_SUBJECT=...clean.json node --test ...` | 1 test passed | ✓ PASS |
| Privacy known-bad fixture | Same command with violation fixture | Exit 1; fixture value absent from output | ✓ FAIL-FIRST |
| Engine config override | Run built engine from config-less temp CWD with `LANCET_CONFIG_DIR=<repo>/config` | Exit 1: config file not found | ✗ FAIL |
| Current store reconciliation | PostgreSQL read + explicit inspector for recorded UUID | Both report count 2, completed, one generation | ✓ PASS |

No provider request, upload, service startup, or data mutation was performed. The inspector was run only after confirming all five expected LanceDB table directories already existed.

## Probe Execution

No `probe-*.sh` scripts are declared or present. Phase verification surfaces are the Rust/Go/Python/Node tests, Bash syntax, and the credential-dependent live gate.

## Requirements Coverage

| Requirement | Source plans | Status | Actual evidence / limitation |
|---|---|---|---|
| DATA-01 | 02-01, 02-04–02-16 | ⚠ PARTIAL | Upload works and current data completed, but PostgreSQL metadata can lie and definitive rejection may remain queued. |
| DATA-02 | 02-01, 02-02, 02-05–02-16 | ⚠ PARTIAL | Both chunkers and tokenizer work; API-to-engine settings propagation is broken. |
| DATA-03 | 02-03, 02-05–02-16 | ✓ SATISFIED | Chunks/metadata/embeddings persist; rollback/retry tests and current data pass. |
| DATA-06 | 02-03, 02-05–02-16 | ✓ SATISFIED | `community_ids` and idempotent communities table verified. |
| DATA-07 | 02-03, 02-05–02-16 | ✓ SATISFIED | Nullable node summary fields and persisted null placeholder verified. |
| DATA-08 | 02-03, 02-05–02-16 | ✓ SATISFIED | Separate nodes/edges and nullable edge summaries verified. |
| DATA-09 | 02-03, 02-09–02-16 | ✓ SATISFIED | Async trait/default resolver exist, are tested, and are used during indexing. |
| RAG-06 | 02-02, 02-04–02-16 | ✓ SATISFIED | Single-consumer Tokio worker and shutdown test pass. |

No Phase 02 requirement IDs are orphaned from the plans. The two partial requirements are enough to fail the user-story outcome even though all seven narrow roadmap success criteria have concrete implementation.

## Fresh Review Finding Impact

Every finding in `02-REVIEW.md` was independently checked against current code.

| Finding | Independent verdict | Phase impact |
|---|---|---|
| CR-01 engine ignores `LANCET_CONFIG_DIR` | CONFIRMED by source and process failure | BLOCKER: violates D-27/startup truth. |
| CR-02 PostgreSQL chunk settings do not reach Rust | CONFIRMED | BLOCKER: durable API record is not trustworthy. |
| CR-03 compensation is not eventually durable | CONFIRMED | BLOCKER: directly violates phase outcome. |
| CR-04 unauthenticated all-interface upload | CONFIRMED | BLOCKER under configured high-security enforcement; provider/storage abuse is possible. |
| CR-05 queue does not bound pre-admission resources | CONFIRMED | BLOCKER: queue-full tests do not cover slow/concurrent buffering. |
| CR-06 inspector emits unknown persisted model | CONFIRMED | BLOCKER: violates privacy must-NOT. |
| WR-01 Node privacy check is optional | CONFIRMED | Warning folded into live-gate/privacy gaps. |
| WR-02 Node vocabulary is narrower | CONFIRMED | Warning plus test-tier prohibition failure. |
| WR-03 closure tests are false positives | CONFIRMED | Four behavior truths remain unverified. |
| WR-04 store selection falls back | CONFIRMED | Warning folded into live-gate gap. |
| WR-05 inspector mutates missing-table state | CONFIRMED | Warning folded into inspector gap. |

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `.planning/ROADMAP.md` | 33 | Still reports `10/16 plans executed`; 02-11 through 02-16 remain unchecked | ⚠ WARNING | Planning bookkeeping contradicts the submitted completion state; it does not change the code verdict. |
| `engine/src/main.rs` | 328 | Placeholder RAG response | ℹ INFO | Phase 3 scope; explicitly covered by later roadmap phase, not a Phase 02 gap. |
| `engine/src/main.rs` | 339 | Graph scaffolding response | ℹ INFO | Phase 4 scope; explicitly deferred. |

No unreferenced `TBD`, `FIXME`, or `XXX` debt markers were found in Phase 02 files.

## Human Verification Required

### 1. Fresh live-run provenance

**Test:** Issue a new challenge only after fixing the blocking gaps, run the private OpenRouter ingestion, and retain a redacted audit receipt that can be independently matched to current PostgreSQL/LanceDB state.
**Expected:** HTTP, PostgreSQL, engine status, and explicit-path LanceDB identity/count/model/generation facts agree.
**Why human:** Credentials and live provider/network state are external, while current challenge/evidence artifacts were deleted.

### 2. Private disclosure surfaces

**Test:** Review private shell and service logs plus staged/committed files after the fresh run.
**Expected:** No credential, authorization header, raw bytes, stored document text, or chunk content appears.
**Why human:** This is the judgment-tier prohibition; repository tests cannot inspect private terminal/service output.

### 3. Behavior-unverified invariants

Perform the four tests listed in `behavior_unverified_items` after their fixtures/harnesses are corrected. These do not change the present `gaps_found` verdict, but they must remain visible for the end-of-phase UAT sink.

## Deferred Items

No blocking gap is clearly assigned to a later milestone phase. Phase 3/4 cover the existing RAG/graph placeholders only; they do not cover configuration, ingestion reconciliation, admission bounds, inspector safety, or privacy enforcement.

## Gaps Summary

Phase 02 has a working happy path and most replacement mechanics are strong, but the goal is not achieved. Seven blocker groups remain:

1. Rust deployment configuration is broken outside repository-relative working directories.
2. PostgreSQL chunk metadata does not describe what Rust executed.
3. failed admission can remain queued after five compensation attempts.
4. the exposed upload path is neither authorized nor bounded before buffering.
5. inspection can mutate evidence and disclose untrusted persisted values.
6. the live gate can skip prerequisites/privacy checks or inspect a fallback store.
7. the privacy prohibition descriptor and classifier remain incomplete.

The current green suites do not exercise these paths. Four additional behavior-dependent truths remain present but unproven, and the historical credentialed-run/privacy claims still require human verification after the blockers close.

---

_Verified: 2026-07-29T02:28:16Z_
_Verifier: the agent (gsd-verifier)_

## Verification Complete
