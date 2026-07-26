---
phase: 02-ingestion-chunking-vector-storage
plan: 09
subsystem: testing
tags: [python, bash, openrouter, lancedb, postgresql, security]

# Dependency graph
requires:
  - phase: 02-07
    provides: rollback-safe replacement, nullable node summaries, and canceled-request compensation
  - phase: 02-08
    provides: locked OpenRouter timeout and durable LanceDB inspector facts
provides:
  - optimization-resistant isolated Python validation for Phase 02 challenge/evidence gates
  - inspector-derived provider/model/generation/count/continuity evidence
  - exact private runtime-artifact ignores and success-only dual cleanup
affects: [phase-02-live-evidence, ingestion-verification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - explicit ValidationError/require checks instead of optimization-sensitive assertions
    - untrusted inspector JSON piped into a standard-library evidence builder
    - final runtime-artifact cleanup only after current PostgreSQL/LanceDB comparison

key-files:
  created:
    - scripts/phase02_live_evidence.py
    - scripts/test_phase02_live_evidence.py
  modified:
    - .gitignore
    - verify-ingestion.sh
    - verify-live-evidence.sh

key-decisions:
  - "Run every challenge, evidence, freshness, privacy, and durable-store decision through explicit Python checks under isolated mode."
  - "Copy provider/model/generation/duplicate/stale/continuity facts directly from the Plan 02-08 inspector output; do not attest hardcoded verdicts."
  - "Keep challenge and evidence paths as exact ignored files and remove both only after final current-store reconciliation succeeds."
  - "Keep all fixtures and negative tests in scripts/test_phase02_live_evidence.py; production shell files contain no test-only harness."

patterns-established:
  - "The live gate uses parse-challenge, build-evidence, validate-gate, and compare-live-state helper subcommands."
  - "Failed validation returns nonzero without deleting either diagnostic runtime artifact."

requirements-completed: [DATA-01, DATA-02, DATA-03, DATA-06, DATA-07, DATA-08, DATA-09, RAG-06]

coverage:
  - id: D1
    description: "Challenge/evidence schema, provenance, UUID, timestamp, freshness, model, count, generation, continuity, and privacy failures are rejected under optimized isolated Python."
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "scripts/test_phase02_live_evidence.py::test_all_structured_failures_are_rejected_under_optimized_isolated_python"
        status: pass
      - kind: automated
        ref: "python -O -I scripts/test_phase02_live_evidence.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Evidence construction copies provider/model/generation/duplicate/stale/continuity facts from the sanitized durable inspector result and rejects current-store drift."
    requirement: DATA-03
    verification:
      - kind: unit
        ref: "scripts/test_phase02_live_evidence.py::test_current_store_drift_is_rejected_and_facts_are_copied_from_inspection"
        status: pass
      - kind: automated
        ref: "cargo test --manifest-path engine/Cargo.toml"
        status: pass
    human_judgment: false
  - id: D3
    description: "Both exact phase-local runtime JSON paths are ignored, and the final shell validator removes both only after the isolated live-state comparison."
    requirement: DATA-08
    verification:
      - kind: automated
        ref: "git check-ignore -q -- challenge runtime path"
        status: pass
      - kind: automated
        ref: "git check-ignore -q -- evidence runtime path"
        status: pass
      - kind: unit
        ref: "scripts/test_phase02_live_evidence.py::test_shell_gate_uses_isolated_helper_and_no_inline_acceptance_assertions"
        status: pass
    human_judgment: false
  - id: D4
    description: "The production live runner retains the real OpenRouter path while routing all acceptance logic through isolated helper subcommands."
    requirement: RAG-06
    verification:
      - kind: automated
        ref: "bash -n verify-ingestion.sh && bash -n verify-live-evidence.sh"
        status: pass
      - kind: automated
        ref: "go test ./... (gateway)"
        status: pass
    human_judgment: false
  - id: D5
    description: "The privacy prohibition remains an explicit unresolved final-live gate for credentials, headers, raw upload bytes, stored document text, and stored chunk content."
    requirement: DATA-01
    verification:
      - kind: other
        ref: "Plan 02-10 private provider run and final sanitized artifact/log review"
        status: unknown
    human_judgment: true
    rationale: "This deterministic plan rejects secret/content-shaped fields, but only the dependent private live run can establish the final no-disclosure evidence claim."

# Metrics
duration: 45 min
completed: 2026-07-26
status: complete
---

# Phase 02 Plan 09: Optimization-Resistant Live Evidence Summary

Fail-closed isolated live-gate validation now derives durable facts and performs success-only cleanup of both private runtime artifacts.

## Performance

- Duration: approximately 45 min
- Started: 2026-07-26T04:45:00Z (execution window; first task commit at 2026-07-26T05:08:22Z)
- Completed: 2026-07-26T05:21:49Z
- Tasks: 2
- Files modified: 5

## Accomplishments

- Added a standard-library validation helper with explicit nonzero failure paths for strict schemas, provenance, UUIDv4 IDs, ordered timestamps, freshness, provider/model, counts, embedding width, generation, continuity, privacy-shaped fields, and current-store equality.
- Replaced inline Python acceptance assertions in both live-gate shell scripts; the production runner now builds evidence from untrusted Plan 02-08 inspector JSON and preserves every derived integrity fact.
- Added optimized isolated negative tests, exact Git-ignore rules, and dual-artifact success-only cleanup ordering for the dependent real-provider gate.

## Task Commits

Each task was committed atomically with TDD RED/GREEN commits:

1. Task 1: Make one malformed-evidence path fail closed under optimized isolated Python — 58f0e59 (test RED), a02dbb0 (feat GREEN).
2. Task 2: Expand fail-closed validation, durable facts, exact ignores, and success cleanup — e0d11c9 (test RED), 0147d46 (feat GREEN).

Plan metadata: pending final state/roadmap metadata commit.

## Files Created/Modified

- scripts/phase02_live_evidence.py — isolated helper subcommands for challenge parsing, evidence construction, gate validation, and current durable-state comparison.
- scripts/test_phase02_live_evidence.py — sanitized optimized negative, provenance, drift, ignore, and shell-contract tests.
- verify-ingestion.sh — helper-driven challenge/document/evidence validation and inspector-derived evidence serialization.
- verify-live-evidence.sh — isolated validation/comparison and success-only removal of challenge plus evidence.
- .gitignore — exact private Phase 02 challenge/evidence rules.

## Decisions Made

- Python assert is not an acceptance mechanism; ValidationError and require remain active under python -O -I.
- The inspector output is untrusted input to evidence construction; generation, duplicate, stale, continuity, provider, and model values are copied and revalidated rather than fabricated.
- Cleanup is downstream of challenge/evidence validation, current PostgreSQL re-query, fresh LanceDB inspection, and field-by-field comparison.
- Tests use the repository's dedicated scripts module and sanitized temporary files; no fixtures or temporary harnesses are embedded in production code.

## Deviations from Plan

### Auto-fixed Issues

1. [Rule 3 - Blocking] Used writable file fixtures instead of restricted temporary directories.

- Found during: Task 1 RED verification.
- Issue: Python-created temporary directories received ACLs that prevented fixture-file writes and cleanup in this execution sandbox.
- Fix: Changed the test fixture setup to use uniquely named temporary files directly in the existing scripts test directory, with finally cleanup.
- Files modified: scripts/test_phase02_live_evidence.py.
- Verification: Optimized isolated suite passes and leaves no temporary files.
- Committed in: 58f0e59 / e0d11c9.

2. [Rule 1 - Bug] Corrected the inspector-fact test boundary.

- Found during: Task 2 GREEN verification.
- Issue: The test incorrectly required every durable field name to be duplicated in the shell wrapper even though the helper is the intended evidence boundary.
- Fix: Asserted the combined wrapper/helper contract while retaining the no-hardcoded-duplicate check in verify-ingestion.sh.
- Files modified: scripts/test_phase02_live_evidence.py.
- Verification: All optimized fixture tests pass.
- Committed in: 0147d46.

3. [Rule 3 - Blocking] Reran Bash/Git operations through approved normal tooling.

- Found during: Task 1 and Task 2 verification/commit.
- Issue: The sandbox denied the Bash launcher and .git/index.lock writes.
- Fix: Reran the prescribed bash -n checks and normal git add/git commit commands with scoped escalation; hooks remained enabled and no --no-verify flag was used.
- Files modified: None beyond planned files.
- Verification: Both shell checks and all four task commits completed successfully.
- Committed in: N/A (execution-environment adaptation).

Total deviations: 3 auto-fixed (2 implementation/test adjustments, 1 execution-environment adaptation).
Impact on plan: All planned deterministic validation, derived-fact, privacy-negative, ignore, and cleanup-order outcomes are implemented; no task was skipped and no package was installed.

## Issues Encountered

- No credentialed OpenRouter request was run in this autonomous deterministic plan. Plan 02-10 remains the required private final gate.
- The plan's privacy prohibition is intentionally still marked flagged_unverified; deterministic tests reject secret/content-shaped fields, while Plan 02-10 must confirm sanitized evidence and logs after the fresh real run.
- The legacy state.advance-plan and state.update-progress handlers could not parse this repository's frontmatter-only STATE layout; current plan/progress were reconciled manually after the handlers recorded the metric, decisions, session, and roadmap updates.
- Pre-existing RAG/graph query stubs remain outside this plan and are already recorded in the Phase 02 deferred-items ledger.

## Authentication Gates

None.

## Known Stubs

None in files created or modified by this plan.

## Next Phase Readiness

Plan 02-10 is authorized to issue a fresh restrictive challenge, perform one private production OpenRouter ingestion, directly reconcile current PostgreSQL/LanceDB state, run verify-live-evidence.sh --validate-gate, and require exit zero plus absence of both runtime artifacts. Bare approval, done, prior evidence, or this summary remains non-authoritative.

## Verification

- cargo test --manifest-path engine/Cargo.toml — PASS (25 engine tests and 13 inspector tests).
- go test ./... in gateway — PASS (gateway and gateway/db packages).
- python -O -I scripts/test_phase02_live_evidence.py with PYTHONOPTIMIZE=1 — PASS (5 tests).
- bash -n verify-ingestion.sh — PASS.
- bash -n verify-live-evidence.sh — PASS.
- Exact git check-ignore probes for challenge and evidence paths — PASS.
- Production/helper assertion scan — PASS; no Python assert remains in the validator or either shell wrapper.
- Working tree is clean; both runtime JSON artifacts are absent, ignored, untracked, and unstaged.

---
Phase: 02-ingestion-chunking-vector-storage
Completed: 2026-07-26

## Self-Check: PASSED

- Summary and all five planned implementation/test files exist.
- Task commits 58f0e59, a02dbb0, e0d11c9, and 0147d46 exist in Git history.
- Deterministic verification claims were rerun successfully before state updates.
