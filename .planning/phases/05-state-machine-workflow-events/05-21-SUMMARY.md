---
phase: 05-state-machine-workflow-events
plan: 21
subsystem: retrieval-fusion
tags: [rust, retrieval, rrf, serde, provenance, regression-tests]

# Dependency graph
requires:
  - phase: 05-16
    provides: variant-aware retrieval fusion and auditable retrieval snapshot seams
  - phase: 05-23
    provides: repaired Rust retrieval message construction and wire-contract tests
provides:
  - typed vector/BM25 provenance construction, filtering, and serialization
  - executable lowercase wire-compatibility and source-cleanup regression guards
affects: [05-22, 05-24, retrieval-response-serialization]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - explicit serde renames on typed provenance enum variants
    - exact Cargo module-path filters for focused library tests

key-files:
  created:
    - .planning/phases/05-state-machine-workflow-events/deferred-items.md
  modified:
    - engine/src/retrieval/fusion.rs
    - engine/src/retrieval/tests.rs

key-decisions:
  - "Use VariantProvenanceSource as the only source representation and let serde enum renames own lowercase wire values."
  - "Keep the existing variant fusion accumulation, RRF scores, ranks, and candidate ordering unchanged while replacing only the provenance type boundary."

patterns-established:
  - "Fusion source filters compare VariantProvenanceSource variants rather than free-form strings."
  - "Focused Cargo tests are executed with their registered module-qualified names when a leaf --exact filter selects zero tests."

requirements-completed: [ORCH-03, ORCH-04]

# Coverage metadata
coverage:
  - id: D1
    description: "Typed vector/BM25 provenance flows through construction and source-specific fusion filters."
    requirement: ORCH-03
    verification:
      - kind: unit
        ref: "engine/src/retrieval/tests.rs#fusion_variant_provenance_source_tracer"
        status: pass
      - kind: other
        ref: "source guards: no String provenance filter and no ineffective serde default"
        status: pass
    human_judgment: false
  - id: D2
    description: "Provenance serialization remains lowercase and RRF rank/score behavior remains stable."
    requirement: ORCH-04
    verification:
      - kind: unit
        ref: "engine/src/retrieval/tests.rs#fusion_variant_provenance_source_is_typed"
        status: pass
      - kind: unit
        ref: "cargo test --lib --manifest-path engine/Cargo.toml --locked"
        status: pass
    human_judgment: false

# Metrics
duration: 7 min
completed: 2026-08-18
status: complete
---

# Phase 05 Plan 21: Typed Fusion Provenance Summary

**Typed vector/BM25 provenance enum with serde-compatible lowercase output and executable regression guards**

## Performance

- **Duration:** 7 minutes
- **Started:** 2026-08-18T01:21:21Z
- **Completed:** 2026-08-18T01:28:54Z
- **Tasks:** 2
- **Files modified:** 2 planned Rust source/test files; 1 deferred-items tracking file created

## Accomplishments

- Replaced free-form `VariantProvenance.source` strings with the equality-comparable `VariantProvenanceSource` enum, using explicit serde names for stable `vector` and `bm25` JSON values.
- Migrated provenance construction and vector/BM25 source selection to enum variants, removed the ineffective serialize-only `#[serde(default)]`, and preserved the existing RRF accumulation, ranks, scores, and ordering.
- Added and executed focused tracer and typed-provenance tests, including exact source/rank/score/contribution assertions and lowercase JSON checks.

## Task Commits

Each task was committed atomically:

1. **Task 1: Carry typed provenance through fusion filters** - `28864e4` (feat)
2. **Task 2: Prove provenance serialization and cleanup guards** - `c5b6117` (test)

Plan metadata is committed separately after state and roadmap updates.

## Files Created/Modified

- `engine/src/retrieval/fusion.rs` - Defines the public serde provenance-source enum and uses it for construction and source filters; removes the dead serde default and manual string conversion.
- `engine/src/retrieval/tests.rs` - Adds the vector/BM25 tracer and typed serialization/filter regression test.
- `.planning/phases/05-state-machine-workflow-events/deferred-items.md` - Records unrelated baseline formatting and binary warning findings without expanding plan scope.

## Verification Results

- Source guards passed: no free-form `source == "vector"`/`"bm25"` filter and no ineffective serde default on `variant_provenance`.
- `retrieval::tests::fusion_variant_provenance_source_tracer` was registered exactly once and executed with `running 1 test`; it passed.
- `retrieval::tests::fusion_variant_provenance_source_is_typed` was registered exactly once and executed with `running 1 test`; it passed.
- The plan’s bare leaf `--exact` filters each reported `running 0 tests` with exit 0, so both were corrected to the registered module-qualified filters above; no zero-test result was accepted as proof.
- `cargo test --lib --manifest-path engine/Cargo.toml --locked` passed with 119 tests passed, 1 ignored, and 0 failures.
- `cargo check --bin engine --manifest-path engine/Cargo.toml --locked` passed; two pre-existing dead-code warnings are recorded in `deferred-items.md`.

## Decisions Made

- Kept the enum in `fusion.rs` and imported it through the existing public `fusion` module from retrieval tests, preserving the plan’s two-file implementation scope without adding a parallel re-export.
- Used explicit serde variant renames as the single wire-serialization path, avoiding a manual source-to-string conversion that could drift from the JSON contract.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Corrected the focused test import path**
- **Found during:** Task 1 registration/compile gate
- **Issue:** `VariantProvenanceSource` was intentionally defined in `fusion.rs` but was not re-exported by `retrieval/mod.rs`, so the initial test import through `super` failed to compile.
- **Fix:** Imported the enum through the existing `super::fusion` module in `retrieval/tests.rs`, staying within the plan’s file scope.
- **Files modified:** `engine/src/retrieval/tests.rs`
- **Verification:** Library test target compiled and registered the tracer exactly once; the tracer executed and passed.
- **Committed in:** `28864e4`

**2. [Rule 3 - Blocking] Corrected focused Cargo exact filters**
- **Found during:** Task 1 and Task 2 verification
- **Issue:** Cargo’s library harness requires the registered module-qualified name for `--exact`; each plan-provided leaf-name invocation exited 0 after running zero tests.
- **Fix:** Used the exact registered filters `retrieval::tests::fusion_variant_provenance_source_tracer` and `retrieval::tests::fusion_variant_provenance_source_is_typed` after independently checking one registration each.
- **Files modified:** None; verification command only.
- **Verification:** Each corrected command reported `running 1 test` and `1 passed`; the full library suite also passed.
- **Committed in:** `c5b6117` (Task 2; the tracer implementation was already committed in `28864e4`)

---

**Total deviations:** 2 auto-fixed (Rule 3: 2)
**Impact on plan:** Both fixes were necessary to compile or prove the intended focused tests; implementation scope remained limited to the two planned Rust files.

## Issues Encountered

- Repository-wide `cargo fmt --manifest-path engine/Cargo.toml -- --check` reports pre-existing formatting differences across unrelated files; no unrelated formatting changes were made.
- Binary compilation reports two pre-existing dead-code warnings in `engine/src/main.rs`; both are logged for later cleanup and are unrelated to typed fusion provenance.
- No authentication gates, user setup, or known stubs remain for this plan.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Fusion provenance is typed and wire-compatible for downstream Phase 05 retrieval/workflow plans.
- The remaining Phase 05 plans can consume `VariantProvenanceSource` without stringly source filters or an ineffective serde default.

---
*Phase: 05-state-machine-workflow-events*
*Completed: 2026-08-18*

## Self-Check: PASSED

- Summary file exists at the required phase path.
- Task commits `28864e4` and `c5b6117` are present in git history.
- The two focused tests and full library suite passed with genuinely executed tests.
- Summary content is free of whitespace errors under `git diff --check`.
