---
phase: 02-ingestion-chunking-vector-storage
verified: 2026-07-24T23:31:00Z
status: gaps_found
score: 9/10 must-haves verified
behavior_unverified: 1
behavior_unverified_items:
  - truth: "Go gateway successfully polls status via gRPC and updates local PostgreSQL."
    test: "Run ./verify-ingestion.sh against live PostgreSQL, engine, gateway, and OpenRouter."
    expected: "The upload reaches completed, reports a positive chunk count, and PostgreSQL matches the engine result."
    why_human: "Handler tests use a fake store and the PostgreSQL integration suite was skipped without TEST_DATABASE_URL."
---

# Phase 2: Ingestion, Chunking & Vector Storage Verification Report

**Phase Goal:** Ingest text/markdown, chunk, and store in LanceDB  
**Verified:** 2026-07-24T23:31:00Z  
**Status:** gaps_found

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Go gateway initializes storage and registers document upload/polling routes | ✓ VERIFIED | `gateway/main.go` registers POST/GET `/documents`; Go handler/build tests pass |
| 2 | Rust engine registers ingestion/status gRPC endpoints and a bounded background worker | ✓ VERIFIED | Proto RPCs exist; `spawn_worker` uses a bounded Tokio receiver; Rust tests pass |
| 3 | Structure-aware Markdown chunking preserves heading hierarchy | ✓ VERIFIED | `markdown_tracks_nested_heading_paths` and related chunker tests pass |
| 4 | Fixed-size chunking respects character windows and overlap | ✓ VERIFIED | `fixed_size_uses_character_offsets_and_bounded_overlap` passes |
| 5 | Token estimates use `o200k_base` | ✓ VERIFIED | Cached tokenizer implementation and token-estimation test pass |
| 6 | LanceDB tables initialize and fail fast on schema drift | ✓ VERIFIED | Initialization and deliberate schema-drift tests pass |
| 7 | OpenRouter embedding client enforces five-way concurrency and retry behavior | ✓ VERIFIED | Mock HTTP tests cover concurrency, timeouts, rate limits, and server errors |
| 8 | Async `EntityResolver` and `ExactMatchResolver` are callable during indexing | ✓ VERIFIED | Resolver unit test passes and `replace_document` invokes it for section resolution |
| 9 | One worker processes chunking, embeddings, graph persistence, status, replacement, and active-job-safe shutdown | ✓ VERIFIED | Worker integration, replacement, failure-state plumbing, and shutdown tests pass |
| 10 | Gateway polls gRPC and transactionally updates live PostgreSQL | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Handler/store wiring and SQL are present; fake-store tests pass, but live PostgreSQL/OpenRouter E2E was not run |

**Score:** 9/10 truths verified (1 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `gateway/db/schema.hcl` | PostgreSQL document schema | ✓ EXISTS + SUBSTANTIVE | Defines document metadata/status storage |
| `gateway/db/schema.sql` | Applied SQL schema | ✓ EXISTS + SUBSTANTIVE | Matches generated models |
| `proto/lancet/v1/lancet.proto` | Ingestion and status gRPC contracts | ✓ EXISTS + SUBSTANTIVE | Streaming ingest and status RPCs present |
| `engine/src/chunker/mod.rs` | Two chunking strategies and token estimation | ✓ EXISTS + SUBSTANTIVE | Markdown/fixed splitters and tokenizer implemented |
| `engine/src/chunker/tests.rs` | Chunker behavior coverage | ✓ EXISTS + SUBSTANTIVE | Strategy, offset, hierarchy, and token tests |
| `engine/src/client/mod.rs` | OpenRouter embedding client | ✓ EXISTS + SUBSTANTIVE | Auth, bounded concurrency, retry/backoff, dimension validation |
| `engine/src/client/tests.rs` | Embedding client tests | ✓ EXISTS + SUBSTANTIVE | Local mock server covers error and concurrency paths |
| `engine/src/db/mod.rs` | LanceDB schemas and resolver | ✓ EXISTS + SUBSTANTIVE | Four schemas, drift validation, resolver trait/default |
| `engine/src/db/tests.rs` | Database/resolver tests | ✓ EXISTS + SUBSTANTIVE | Initialization, drift, and exact-match tests |
| `engine/src/main.rs` | Complete ingestion service and worker | ✓ EXISTS + SUBSTANTIVE | Queue, UUID validation, indexing, persistence, status, shutdown |
| `gateway/main.go` | Upload and status polling API | ✓ EXISTS + SUBSTANTIVE | gRPC upload/status and PostgreSQL transaction adapter |
| `verify-ingestion.sh` | Live E2E validator | ✓ EXISTS + SUBSTANTIVE | Uploads, polls, checks positive chunk count and PostgreSQL |

**Artifacts:** 12/12 verified

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| Go upload route | Rust engine | Streaming `IngestDocument` gRPC | ✓ WIRED | `grpcEngine.Ingest` sends bounded chunks and closes the stream |
| Rust worker | Chunker → OpenRouter → LanceDB | `process_job` | ✓ WIRED | Explicit stage calls with document-scoped tracing |
| Go polling route | Rust status → PostgreSQL | `IngestionStatus` + transactional `UpdateStatus` | ✓ WIRED | Terminal-only reconciliation is implemented |
| HTTP client | Polling resource | `Location: /documents/{uuid}` | ✓ WIRED | Accepted upload returns a tested polling location |

**Wiring:** 4/4 connections verified

## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| DATA-01: Lightweight document ingestion | ✓ SATISFIED | - |
| DATA-02: Structure-aware and fixed-size chunking | ✓ SATISFIED | - |
| DATA-03: Persist chunks and metadata in LanceDB | ✓ SATISFIED | - |
| DATA-06: Community placeholders | ✓ SATISFIED | - |
| DATA-07: Nullable node summary fields and unsummarized refs | ✓ SATISFIED | - |
| DATA-08: Separate node/edge tables with nullable edge summary fields | ✗ BLOCKED | `edges_schema()` declares `summary` and `summary_vector` non-nullable |
| DATA-09: Async resolver trait and exact-match default | ✓ SATISFIED | - |
| RAG-06: Async ingestion worker | ✓ SATISFIED | - |

**Coverage:** 7/8 requirements satisfied

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `engine/src/db/mod.rs` | 146-147 | Edge placeholder summary fields are non-nullable contrary to DATA-08 | 🛑 Blocker | Requirement and roadmap success criterion are not met |
| `engine/src/main.rs` | 342-371 | Multi-table replacement uses destructive independent operations | ⚠️ Warning | Failure can leave a partial replacement rather than an atomic upsert |
| `gateway/main.go` | 205-217 | PostgreSQL row is inserted before engine enqueue with no compensation | ⚠️ Warning | Rejected ingestion leaves orphaned queued metadata |
| `gateway/main.go` | 241-244 | Conditional terminal update does not recover a concurrent lost race | ⚠️ Warning | A successful concurrent completion may return HTTP 500 |

**Anti-patterns:** 4 found (1 blocker, 3 warnings)

## Human Verification Required

### 1. Live upload, indexing, polling, and PostgreSQL reconciliation

**Test:** Start PostgreSQL, the Rust engine, and Go gateway with `OPENROUTER_API_KEY`, then run `./verify-ingestion.sh`.  
**Expected:** The upload returns a UUIDv4 polling location, reaches `completed` with a positive chunk count, and PostgreSQL contains the same terminal state/count.  
**Why human:** The current environment did not provide a live service stack, database test URL, or OpenRouter credentials.

## Gaps Summary

### Critical Gaps (Block Progress)

1. **DATA-08 edge summary nullability is incorrect**
   - Missing: Nullable `summary` and `summary_vector` fields on the LanceDB `edges` schema.
   - Impact: The phase does not meet an explicitly mapped requirement or roadmap success criterion, even though schema self-validation passes against the same incorrect expectation.
   - Fix: Change both edge fields to nullable, update persistence to support nullable placeholder values, and add schema assertions that check field nullability.

### Non-Critical Gaps (Can Defer)

1. **Replacement is retry-repairable, not atomic**
   - Issue: Old rows are deleted before all replacement batches commit.
   - Impact: A mid-write failure can temporarily remove a previously valid index.
   - Recommendation: Stage/version replacement rows and switch the active version after all writes succeed.

2. **Gateway failure/race reconciliation needs hardening**
   - Issue: Failed enqueue leaves queued metadata; concurrent terminal updates can return 500.
   - Impact: Operationally confusing orphan rows and transient errors under concurrency.
   - Recommendation: Add compensation/failure status and re-read on a conditional-update race.

## Recommended Fix Plan

### 02-05-PLAN.md: Close ingestion integrity gaps

**Objective:** Satisfy DATA-08 and harden failure/concurrency behavior found during phase verification.

**Tasks:**
1. Make edge placeholder summary fields nullable and add explicit Arrow schema nullability assertions.
2. Add staged/versioned replacement or another recoverable commit protocol, with write-boundary failure-injection tests.
3. Compensate failed gateway enqueue and re-read terminal rows after conditional-update races; run live E2E verification.

**Estimated scope:** Medium

## Verification Metadata

**Verification approach:** Goal-backward against all Phase 2 PLAN must-haves and mapped requirements  
**Must-haves source:** `02-01-PLAN.md` through `02-04-PLAN.md`, plus ROADMAP/REQUIREMENTS traceability  
**Automated checks:** Rust 20/20 tests + build; Go tests/build/vet; SQLC regeneration; Bash syntax; capability gates  
**Human checks required:** 1  
**Total verification time:** 8 min

---
*Verified: 2026-07-24T23:31:00Z*
*Verifier: Codex (inline per user constraint)*
