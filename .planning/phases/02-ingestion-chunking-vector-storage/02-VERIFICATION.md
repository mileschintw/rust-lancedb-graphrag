---
phase: 02-ingestion-chunking-vector-storage
verified: 2026-07-25T23:19:56Z
status: gaps_found
score: 8/14 must-haves verified
behavior_unverified: 1
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 9/10
  gaps_closed:
    - "DATA-08 edge summary and summary_vector schema fields are now nullable."
    - "The gateway re-reads a winning terminal row after a conditional-update race."
  gaps_remaining:
    - "Actual LanceDB write/delete failures do not enter replacement rollback."
  regressions: []
gaps:
  - truth: "OpenRouter embedding calls use the locked 10-second timeout per call, then three retries after the initial request for four maximum attempts total with 1/2/4-second backoff (D-19)."
    status: failed
    reason: "The production reqwest client is configured with a 30-second timeout, contrary to locked decision D-19."
    artifacts:
      - path: "engine/src/client/mod.rs"
        issue: "OpenRouterClient::new uses Duration::from_secs(30)."
    missing:
      - "Use the locked 10-second production request timeout and assert it through a behaviorally meaningful timeout test."
  - truth: "A failed same-ID replacement at any canonical write boundary restores the prior completed LanceDB generation."
    status: failed
    reason: "Rollback is invoked only for synthetic post-write fault callbacks. Real delete/add/schema/staging errors return through ? after canonical mutation and bypass rollback."
    artifacts:
      - path: "engine/src/main.rs"
        issue: "Lines 424-453, 568-572, and 656-660 return real LanceDB errors directly; rollback calls exist only after ReplacementFaultInjector callbacks."
      - path: "engine/src/main.rs"
        issue: "No test implements ReplacementFaultInjector or injects a failing LanceDB delete/add; the documented `cargo test ... replacement` matched no tests."
    missing:
      - "Route every mutation error after version capture through rollback_replacement."
      - "Add deterministic failing-table tests for every canonical delete/add boundary and prove prior rows remain queryable."
  - truth: "The live evidence gate rejects malformed, replayed, stale, challenge-mismatched, or store-mismatched evidence in every supported environment."
    status: failed
    reason: "Security decisions are Python assert statements and disappear under optimization; `python -O -c \"assert False\"` exited 0 in this verification."
    artifacts:
      - path: "verify-live-evidence.sh"
        issue: "Lines 70-93 and 171-177 use assert for schema, provenance, freshness, model, counts, and live-store comparisons."
      - path: "verify-ingestion.sh"
        issue: "Lines 72-77 and 162-170 use assert for challenge and store validation."
    missing:
      - "Replace asserts with explicit fail-closed validation and invoke Python in isolated mode."
      - "Add negative self-tests under PYTHONOPTIMIZE=1."
  - truth: "The LanceDB inspector derives provider, persisted model, duplicate-generation, and stale-generation verdicts from stored rows."
    status: failed
    reason: "The inspector checks only schema type/count/width, then emits constant provider/model/stale values; the evidence writer separately hardcodes duplicate_generation false."
    artifacts:
      - path: "engine/src/bin/inspect_lancedb.rs"
        issue: "Lines 99-124 create an unused empty model set and serialize fixed provider/model/stale_generation values."
      - path: "verify-ingestion.sh"
        issue: "Line 190 serializes duplicate_generation as False without a derived inspection result."
    missing:
      - "Read sanitized aggregates for persisted model values, generation timestamps, chunk/edge uniqueness, and chunk-index continuity."
      - "Fail closed when provider/model/duplicate/stale facts cannot be derived."
  - truth: "Challenge/evidence runtime artifacts remain private and cannot be accidentally staged after validation."
    status: failed
    reason: "Neither exact runtime JSON path is Git-ignored, and successful validation removes only the challenge while leaving evidence behind."
    artifacts:
      - path: ".gitignore"
        issue: "No rule ignores either Phase 02 runtime JSON artifact; git check-ignore failed for both paths."
      - path: "verify-live-evidence.sh"
        issue: "Line 179 removes only the challenge after validation."
    missing:
      - "Add exact ignore rules for both runtime files."
      - "Remove both artifacts after successful validation and test ignore/cleanup behavior."
  - truth: "Nullable node summary placeholders remain Arrow null during persistence."
    status: failed
    reason: "The schema is nullable, but persistence writes an empty non-null string for every node summary."
    artifacts:
      - path: "engine/src/main.rs"
        issue: "Line 562 constructs `StringArray::from(vec![Some(\"\"); chunks.len()])` for node summary."
    missing:
      - "Create the node summary column with schema-derived new_null_array."
      - "Add a persisted-row null-count assertion."
behavior_unverified_items:
  - truth: "Retrying after each injected same-ID replacement failure converges to exactly one canonical generation with no stale nodes or edges."
    test: "Inject a failure at each actual document/node/edge delete and add boundary, verify the old generation, retry, then inspect canonical/staged counts and identifiers."
    expected: "The prior generation survives each failure and the retry leaves one current generation, no staging row, no duplicate IDs, and no stale rows."
    why_human: "No named behavioral test exercises failed replacement followed by retry; the current inspector also hardcodes its stale/duplicate verdicts."
---

# Phase 2: Ingestion, Chunking & Vector Storage Verification Report

**Phase Goal:** Ingest text/markdown, chunk, and store in LanceDB  
**Verified:** 2026-07-25T23:19:56Z  
**Status:** gaps_found  
**Re-verification:** Yes — previous DATA-08/race gaps were rechecked and newer integrity/live-gate must-haves were verified from code.

## MVP Format Guard

ROADMAP marks this phase `mode: mvp`, but `user-story.validate` returns `false` for `Ingest text/markdown, chunk, and store in LanceDB`. Canonical MVP user-flow coverage cannot be generated until the goal is reformatted with `$gsd-mvp-phase 2`. The technical goal-backward verification below was completed because the verification assignment explicitly required it.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Users can upload a lightweight text document through the Go HTTP API | ✓ VERIFIED | `gateway/main.go:198-235` enforces multipart/size limits, inserts metadata, streams to the engine, and returns 202 with a polling location; Go tests pass. |
| 2 | Rust receives the upload through gRPC and applies structure-aware/fixed-size chunking with 500/50 defaults and o200k estimates | ✓ VERIFIED | `engine/src/main.rs:238-260`, `engine/src/main.rs:101-147`, chunker implementation/tests; Rust suite passes. |
| 3 | Production indexing calls the locked OpenRouter model, bounds concurrency at five, and persists 2048-wide embeddings | ✓ VERIFIED | `engine/src/client/mod.rs` and `process_job`; mock client tests pass. The fresh credentialed 02-06 run is limited evidence that one real provider-backed run completed, not that the evidence gate is secure. |
| 4 | Chunks, metadata, raw document, and edges flow into embedded LanceDB | ✓ VERIFIED | `process_job` calls `replace_document`; real-table worker replacement test passes and schemas are wired through `DatabaseManager`. |
| 5 | Community/node/edge placeholder schemas satisfy DATA-06/07/08 | ✓ VERIFIED | `engine/src/db/mod.rs:125-181`; edge nullability and drift tests pass. |
| 6 | Async `EntityResolver` and exact-match implementation are callable during indexing | ✓ VERIFIED | Trait/implementation in `engine/src/db/mod.rs`; resolver test and `replace_document` usage at lines 586-604. |
| 7 | A bounded single-consumer Tokio worker processes jobs and gateway polling reconciles terminal PostgreSQL status | ✓ VERIFIED | Worker at `engine/src/main.rs:713-778`, polling at `gateway/main.go:238-271`; Rust/Go tests pass and the fresh live run proves one successful reconciliation. |
| 8 | Gateway compensates ordinary enqueue failures and returns a winning terminal race row | ✓ VERIFIED | `gateway/main.go:169-175,225-231,256-264`; focused handler and PostgreSQL race tests pass. Cancellation reliability remains a warning below. |
| 9 | OpenRouter uses the locked 10-second timeout per call, then three retries after the initial request for four maximum attempts total with 1/2/4-second backoff | ✗ FAILED | Production client uses `Duration::from_secs(30)` at `engine/src/client/mod.rs:43`, contrary to D-19's canonical contract. Current Plans 02-08 through 02-10 supersede any executed historical wording that implies three attempts total. |
| 10 | Every actual canonical write failure restores the prior generation | ✗ FAILED | Real LanceDB errors bypass rollback; only post-write synthetic callback errors invoke it. |
| 11 | Failure followed by retry provably converges without stale/duplicate generations | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | No failed-replacement/retry test exists; the inspector cannot provide the claimed verdict. |
| 12 | Persisted nullable summary placeholders are Arrow nulls | ✗ FAILED | Edge placeholders are null, but node summary is persisted as `Some(\"\")`. |
| 13 | Live-gate validation and artifact privacy fail closed | ✗ FAILED | Optimizable Python asserts, missing ignore rules, and retained evidence violate the gate contract. |
| 14 | Inspector/evidence verdicts are derived from durable state | ✗ FAILED | Provider/model/stale/duplicate verdicts are constants rather than queried facts. |

**Score:** 8/14 truths verified (1 present, behavior-unverified)

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `gateway/main.go` | Upload, compensation, polling, PostgreSQL reconciliation | ✓ SUBSTANTIVE + WIRED | Routes and store/engine calls are active; cancellation compensation is incomplete. |
| `engine/src/chunker/mod.rs` | Markdown/fixed-size chunking and token estimates | ✓ SUBSTANTIVE + WIRED | Called from worker and covered by passing behavioral tests. |
| `engine/src/client/mod.rs` | OpenRouter client | ⚠️ PARTIAL | Real client is wired, but production timeout violates D-19. |
| `engine/src/db/mod.rs` | Drift-validated LanceDB schemas and resolver | ✓ SUBSTANTIVE + WIRED | Five tables including internal staging initialize; canonical schemas meet requirements. |
| `engine/src/main.rs` | Ingestion service, worker, persistence/replacement | ✗ PARTIAL | Main path works, but actual mutation failures bypass rollback and node summary placeholder is non-null. |
| `engine/src/bin/inspect_lancedb.rs` | Direct derived durable-state verdict | ✗ HOLLOW | Counts/width are queried; model/provider/stale/duplicate facts are fabricated or absent. |
| `verify-ingestion.sh` | Challenge-bound live runner and sanitized evidence | ✗ UNSAFE | Assertions can be optimized away; duplicate verdict is hardcoded. |
| `verify-live-evidence.sh` | Strict final validator and cleanup | ✗ UNSAFE | Assertions can be optimized away; evidence is retained and runtime paths are not ignored. |

## Key Link and Data-Flow Verification

| From | To | Status | Details |
|------|----|--------|---------|
| Go upload handler | Rust `IngestDocument` stream | ✓ WIRED | 64KB streaming and response mapping are implemented. |
| Rust worker | Chunker → OpenRouter → LanceDB | ✓ WIRED | `process_job` carries real chunk text to embeddings and batches to persistence. |
| LanceDB mutation error | `rollback_replacement` | ✗ NOT WIRED | Only synthetic `faults.after(...)` errors reach rollback. |
| Gateway ingest failure | PostgreSQL failed compensation | ⚠️ PARTIAL | Works with a live request context; a canceled request reuses the canceled context. |
| Runtime evidence | Direct inspector facts | ✗ HOLLOW | Counts/width flow; provider/model/stale/duplicate conclusions do not. |
| Accepted staging row | Startup recovery/re-enqueue | ✗ NOT WIRED (warning) | Startup opens staging but never enumerates it or reconstructs jobs. |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Rust implementation/tests | `cargo test --manifest-path engine/Cargo.toml` | 21 engine + 4 inspector-linked tests passed | ✓ PASS |
| Go gateway/tests | `go test ./...` from `gateway` | Packages passed; telemetry emitted a non-fatal access warning | ✓ PASS |
| Script syntax/self-test | Git Bash `-n` for both scripts and `verify-live-evidence.sh --self-test` | Exit 0 outside restricted shell | ✓ PASS |
| Python optimization bypass | `python -O -c "assert False; print('assertion-elided')"` | Printed `assertion-elided`, exit 0 | ✗ FAIL |
| Runtime artifact ignore | `git check-ignore` on both exact JSON paths | Neither path ignored | ✗ FAIL |
| Replacement failure coverage | Test enumeration and fault-injector usage search | No fault implementation/test; 02-05's replacement filter matched no tests | ✗ FAIL |

No credentialed provider request was repeated. Short-lived challenge/evidence contents, API keys, and uploaded content were not inspected or recreated.

## Requirements Coverage

| Requirement | Source Plans | Status | Evidence / qualification |
|-------------|--------------|--------|--------------------------|
| DATA-01 | 02-01, 02-04, 02-05, 02-06 | ✓ SATISFIED | Upload and status reconciliation work; canceled-request compensation remains a reliability warning. |
| DATA-02 | 02-01, 02-02, 02-05, 02-06 | ✓ SATISFIED | Both chunkers and locked defaults are implemented/tested. |
| DATA-03 | 02-03, 02-05, 02-06 | ✓ SATISFIED | Chunks/metadata persist in LanceDB; safe replacement is an added must-have and currently fails. |
| DATA-06 | 02-03, 02-05, 02-06 | ✓ SATISFIED | `community_ids` and communities table exist and initialize idempotently. |
| DATA-07 | 02-03, 02-05, 02-06 | ✓ SATISFIED | Nullable schema fields and refs exist; the stricter persisted-null plan truth fails for node summary. |
| DATA-08 | 02-03, 02-05, 02-06 | ✓ SATISFIED | Separate tables and nullable edge summary fields are present. |
| DATA-09 | 02-03 | ✓ SATISFIED | Async trait and exact-match default are implemented and used. |
| RAG-06 | 02-02, 02-04, 02-05, 02-06 | ✓ SATISFIED | Bounded async worker exists; accepted pending work has no restart reconciliation. |

No Phase 02 requirement ID is orphaned from PLAN frontmatter.

## Independently Validated Review Findings

| Finding | Verdict | Evidence |
|---------|---------|----------|
| CR-01 runtime artifacts not ignored/cleaned | CONFIRMED BLOCKER | Both `git check-ignore` probes fail; validator deletes only challenge. |
| CR-02 Python asserts optimized away | CONFIRMED BLOCKER | Security checks are assertions; direct `python -O` probe exits successfully. |
| CR-03 inspector verdicts hardcoded | CONFIRMED BLOCKER | Inspector serializes constant provider/model/stale; runner hardcodes duplicate false. |
| CR-04 real write failures bypass rollback | CONFIRMED BLOCKER | Direct `?` returns after mutation; rollback only follows synthetic callbacks. |
| WR-01 canceled request breaks compensation | CONFIRMED WARNING | The same `r.Context()` is passed to ingest and compensation; no detached timeout or cancellation test exists. |
| WR-02 accepted queued work is lost across restart | CONFIRMED WARNING | Biased shutdown discards pending jobs; startup does not scan staging or restore statuses. This also matches D-15's intentional pending-discard decision, but the acknowledged upload remains unreconciled. |

## Anti-Patterns

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `engine/src/main.rs` | 424-453, 568-572, 656-660 | Mutation errors bypass rollback | 🛑 BLOCKER | Prior completed generation can be destroyed. |
| `verify-live-evidence.sh` | 70-93, 171-177 | Security checks use `assert` | 🛑 BLOCKER | Optimized Python can accept invalid evidence. |
| `engine/src/bin/inspect_lancedb.rs` | 99-124 | Hardcoded verdicts | 🛑 BLOCKER | Gate attests facts it did not inspect. |
| `.gitignore` / validator | — / 179 | Private artifacts not ignored; evidence retained | 🛑 BLOCKER | Accidental disclosure/staging risk. |
| `engine/src/main.rs` | 562 | Nullable placeholder stored as empty string | 🛑 BLOCKER | Plan truth is observably false. |
| `gateway/main.go` | 225-226 | Compensation reuses request context | ⚠️ WARNING | Canceled uploads can remain queued forever. |
| `engine/src/main.rs` | 722-733, 785-797 | No restart recovery | ⚠️ WARNING | Acknowledged pending jobs can strand staging/PostgreSQL state. |

The `QueryRAG` placeholder in `engine/src/main.rs` predates and is outside the Phase 02 ingestion goal; it is not classified as a Phase 02 blocker.

## Human Verification Required

No additional credentialed or visual check is requested while deterministic blockers remain. The one behavior-unverified retry invariant should be converted into a named automated failure-injection test rather than accepted manually.

## Gaps Summary and Next Action

Phase 02 demonstrates a working happy-path ingestion/chunking/LanceDB flow, and all eight mapped requirements have implementation evidence. It is nevertheless **not complete** against the expanded Phase 02 must-haves: recoverable replacement is not wired to real storage errors, live-gate acceptance/privacy can be bypassed or misrepresented, and persisted node summary placeholders violate the explicit null contract.

Concrete next action: run `$gsd-plan-phase 2 --gaps` using the structured gaps above. The closure plan should first fix actual-error rollback and add failing-table tests, then make the live gate fail closed with derived inspector results and private artifact cleanup, then correct node null persistence and the 10-second timeout. After implementation, re-run verification without another credentialed live request until the non-secret gate tests pass.

---

_Verified: 2026-07-25T23:19:56Z_  
_Verifier: the agent (gsd-verifier)_
