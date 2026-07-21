---
phase: 02-ingestion-chunking-vector-storage
plan: 02
subsystem: ingestion
tags: [rust, markdown, chunking, tiktoken, tokio]
requires:
  - phase: 02-01
    provides: bounded ingestion queue and background worker scaffold
provides:
  - structure-aware Markdown chunking with heading hierarchy paths
  - fixed-size Unicode character windows with bounded overlap
  - o200k_base token estimation and ingestion-worker chunk integration
affects: [02-03, vector-storage, embeddings]
tech-stack:
  added: [pulldown-cmark, tiktoken-rs]
  patterns: [metadata-driven chunk strategy, JSON fixed-size fallback, cached tokenizer]
key-files:
  created: [engine/src/chunker/mod.rs, engine/src/chunker/tests.rs]
  modified: [engine/Cargo.toml, engine/Cargo.lock, engine/src/main.rs]
key-decisions:
  - "Force JSON uploads through fixed-size chunking even when structure-aware is requested."
  - "Cache the o200k_base tokenizer in OnceLock and attach token estimates before downstream persistence."
patterns-established:
  - "Chunk offsets are Unicode character offsets, not byte offsets."
  - "Ingestion metadata controls chunk_strategy, chunk_size, and chunk_overlap with safe defaults."
requirements-completed: [DATA-02, RAG-06]
coverage:
  - id: D1
    description: "Markdown and plain text are split with structure-aware section context and bounded windows."
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "engine/src/chunker/tests.rs; cargo test chunker::tests"
        status: pass
    human_judgment: false
  - id: D2
    description: "Worker selects chunk strategy, computes real chunk counts, and attaches o200k_base token estimates."
    requirement: RAG-06
    verification:
      - kind: integration
        ref: "engine/src/main.rs tests; cargo test tests::"
        status: pass
    human_judgment: false
duration: 57m
completed: 2026-07-21
status: complete
---

# Phase 02 Plan 02: Rust Markdown Chunker & Token Estimation Summary

**Unicode-safe Markdown/fixed-window chunking with cached o200k token estimation integrated into the ingestion worker**

## Performance

- **Duration:** 57m
- **Started:** 2026-07-21T04:38:00Z
- **Completed:** 2026-07-21T05:35:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added structure-aware Markdown chunking that preserves nested heading paths and splits oversized blocks safely.
- Added fixed-size character windows with bounded overlap and raw JSON fallback behavior.
- Replaced mock byte-derived worker counts with real chunks and cached `o200k_base` token estimates.

## Task Commits

1. **Task 1: Chunking and token-estimation library** - `37885df`
2. **Task 2: Ingestion-worker integration** - `07db3c4`

## Files Created/Modified

- `engine/src/chunker/mod.rs` - Chunk model, Markdown/fixed-size strategies, heading paths, and token estimation.
- `engine/src/chunker/tests.rs` - Unicode, overlap, Markdown hierarchy, JSON, and tokenizer unit tests.
- `engine/src/main.rs` - Metadata-driven strategy selection and real worker chunk processing.
- `engine/Cargo.toml` - Adds `pulldown-cmark` and `tiktoken-rs`.
- `engine/Cargo.lock` - Locks the new dependency graph.

## Decisions Made

- JSON filenames always force fixed-size chunking to avoid interpreting JSON strings as Markdown structure.
- Chunk size/overlap come from ingestion metadata with 512/64 defaults and positive-value validation.
- Tokenizer initialization is cached with `OnceLock` to avoid rebuilding the BPE for every chunk.

## Deviations from Plan

None - plan scope and acceptance criteria were implemented as written.

## Issues Encountered

- Initial Rust verification spent over ten minutes compiling the LanceDB/Arrow graph. Timeout wrappers returned before child Cargo processes exited; the active compile was allowed to finish, after which focused tests completed normally.
- Subagent Git-index escalation did not surface to the user, so verified changes were committed through the orchestrator approval channel.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 02-03 can consume `Chunk` values and their token estimates for embeddings and LanceDB persistence.
- No known blockers remain for the next wave.

## Self-Check: PASSED

- `cargo fmt -- --check`
- `cargo test chunker::tests -- --nocapture` — 6 passed
- `cargo test tests:: -- --nocapture` — 10 passed

---
*Phase: 02-ingestion-chunking-vector-storage*
*Completed: 2026-07-21*
