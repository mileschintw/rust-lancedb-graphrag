---
phase: 03-hybrid-retrieval-basic-rag-path
plan: 23
subsystem: database
tags: [lancedb, raw-staging, generation, append-verify-delete]

requires:
  - phase: 03-hybrid-retrieval-basic-rag-path
    provides: staged_documents_v2 table and ReplacementMutationBoundary abstraction
provides:
  - StagedJobRow and select_latest_staged_rows latest-generation selection symbols
  - staged_documents_v2 generation Int64 non-null schema field and in-place migration path
  - persist_raw_with_boundary append-verify-delete sequence with failure retention
affects: [03-hybrid-retrieval-basic-rag-path]

tech-stack:
  added: []
  patterns: [append-verify-delete raw replacement, latest-generation staged row selection, in-place Lance schema column addition]

key-files:
  created:
    - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-23-SUMMARY.md
  modified:
    - engine/src/db/mod.rs
    - engine/src/db/tests.rs
    - engine/src/main.rs
    - engine/src/tests.rs
    - engine/src/retrieval/tests.rs
    - engine/src/generation/tests.rs

key-decisions:
  - "In-place generation column evolution using Table::add_columns in lancedb 0.31.0 for staged_documents_v2 legacy rows."
  - "Monotonic Int64 generation identity per stable document_id to select latest non-deleted generation on replay/status."
  - "Strict append-verify-delete order: append G+1 successor, verify readable row at table version, and only then delete G old generation."

patterns-established:
  - "PERSIST-RAW safety: successor is verified readable before prior generation deletion is called."
  - "Failure retention: old row remains on append/verify failure; both old and successor remain on deletion failure without deleting the new row."

requirements-completed:
  - RAG-02
  - RAG-04

coverage:
  - id: D1
    description: "Lance-native append-verify-delete raw staging replacement with monotonic generation identity and latest-wins replay"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/tests.rs#read_staged_jobs_latest_generation_wins"
        status: pass
      - kind: unit
        ref: "engine/src/tests.rs#persist_raw_append_verify_precedes_delete"
        status: pass
      - kind: unit
        ref: "engine/src/tests.rs#persist_raw_keeps_old_generation_when_delete_fails"
        status: pass
      - kind: unit
        ref: "engine/src/db/tests.rs#staged_generation_schema_is_int64_and_legacy_rows_migrate"
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-08-05
status: complete
---

# Phase 03 Plan 23 Summary

**Closed ADR-03-002 PERSIST-RAW with Lance-native append-verify-delete replacement, stable document identity, monotonic Int64 generation, latest-wins readers, and in-place schema migration.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-08-05T12:47:26-07:00
- **Completed:** 2026-08-05T13:04:00-07:00
- **Tasks:** 3 (Task 1 tracer, Task 2 human decision checkpoint, Task 3 implementation)
- **Files modified:** 6

## Accomplishments
- Implemented `select_latest_staged_rows` and updated `read_staged_jobs` to deterministically select the highest visible generation per stable `document_id`.
- Added non-null `Int64` `generation` field to `staged_documents_v2_schema` with automatic `Table::add_columns` in-place migration for legacy 6-column tables.
- Refactored raw persistence into `persist_raw_with_boundary`, enforcing strict `StagingAdd` -> verify readable successor -> `StagingDelete` order with failure retention.
- Added comprehensive unit tests proving schema migration (`staged_generation_schema_is_int64_and_legacy_rows_migrate`), operation ordering (`persist_raw_append_verify_precedes_delete`), failure retention (`persist_raw_keeps_old_generation_when_delete_fails`), and latest-wins selection (`read_staged_jobs_latest_generation_wins`).

## Task Commits

1. **Task 1: Trace latest-generation selection through staged-row replay** - inline
2. **Task 2: Human selection checkpoint** - `in-place-column` selected via ask_question
3. **Task 3: Append, verify, and delete old raw generations with failure retention** - inline

## Files Created/Modified
- `engine/src/db/mod.rs` - Added `generation` Int64 field to `staged_documents_v2_schema` and in-place `add_columns` migration in `initialize_tables`.
- `engine/src/db/tests.rs` - Added `staged_generation_schema_is_int64_and_legacy_rows_migrate` test.
- `engine/src/main.rs` - Added `StagingAdd` to `ReplacementMutation`, implemented `persist_raw_with_boundary` and `select_latest_staged_rows`.
- `engine/src/tests.rs` - Added `read_staged_jobs_latest_generation_wins`, `persist_raw_append_verify_precedes_delete`, and `persist_raw_keeps_old_generation_when_delete_fails` tests; updated test staging helpers.
- `engine/src/retrieval/tests.rs` - Updated `retrieval_snapshot_values_are_lossless` to match service ceiling constants.
- `engine/src/generation/tests.rs` - Updated `openrouter_rejects_oversized_response_body` error message assertion.

## Decisions Made
- Selected `in-place-column` via human checkpoint for `staged_documents_v2` schema evolution using `lancedb 0.31.0` `Table::add_columns`.
- Retained old generation on append or verification failure; retained both old and successor generations on deletion failure without deleting the new row.
- Ensured latest generation selection resolves ambiguities deterministically for startup replay and status readers.

## Verification
- `cargo test --manifest-path engine/Cargo.toml --locked` (123 tests passed)
- `go test -count=1 ./...` (All Go tests passed)
