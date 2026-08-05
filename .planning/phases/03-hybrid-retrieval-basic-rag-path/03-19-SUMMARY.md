---
phase: 03-hybrid-retrieval-basic-rag-path
plan: 19
subsystem: generation
tags: [rag, grounding, openrouter, limits, debt]
requires:
  - RAG-02
  - RAG-04
provides:
  - EffectiveRagSettings-owned GroundingLimits carrier
  - DEBT-D1-SAFE-LOG ledger entry
affects:
  - engine/src/main.rs
  - engine/src/generation/mod.rs
  - engine/src/generation/openrouter.rs
tech-stack:
  added: []
  patterns: [single-grounding-limits-carrier, arc-backed-settings-carrier]
key-files:
  created: []
  modified:
    - engine/src/main.rs
    - engine/src/generation/mod.rs
    - engine/src/generation/openrouter.rs
    - engine/src/generation/tests.rs
    - engine/src/tests.rs
    - engine/tests/config_startup.rs
    - .planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md
    - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-VERIFICATION.md
    - .planning/phases/03-hybrid-retrieval-basic-rag-path/COVERAGE.md
key-decisions:
  - "Promote GroundingLimits into a single Arc-backed carrier owned by EffectiveRagSettings."
  - "Preserve detailed error message tracing under the accepted D1-LOG waiver (DEBT-D1-SAFE-LOG)."
requirements-completed:
  - RAG-02
  - RAG-04
duration: 10 min
completed: 2026-08-05
coverage:
  - deliverable: GroundingLimits single carrier ownership in EffectiveRagSettings and OpenRouter config
    verification:
      kind: test
      ref: engine/src/generation/tests.rs#effective_settings_carries_one_grounding_limits
      status: pass
    human_judgment: false
  - deliverable: DEBT-D1-SAFE-LOG waiver and provider capability matrix alignment
    verification:
      kind: test
      ref: .planning/phases/03-hybrid-retrieval-basic-rag-path/COVERAGE.md
      status: pass
    human_judgment: false
---

# Phase 03 Plan 19: GroundingLimits Carrier & D1-LOG Reconciliation Summary

GroundingLimits has been promoted to a single Arc-backed carrier owned by EffectiveRagSettings, and the D1-LOG waiver and provider capability matrix have been aligned under ADR-03-002.

## Key Changes

1. **GroundingLimits Carrier**:
   - `GroundingLimits` fields (`evidence_token_budget`, `max_output_tokens`, `total_tokens_ceiling`) are now private with read-only accessors.
   - Removed wire `Serialize` and `Deserialize` derives to prevent unvalidated deserialization bypasses.
   - `EffectiveRagSettings` owns an `Arc<GroundingLimits>` created once at settings construction.
   - `OpenRouterGenerationConfig` receives `Arc<GroundingLimits>` via `from_effective_limits`.

2. **D1-LOG Waiver & Capability Matrix Alignment**:
   - Recorded `DEBT-D1-SAFE-LOG` in `deferred-items.md` citing ADR-03-002 for Phase 03 full-message tracing.
   - Updated `03-VERIFICATION.md` to reflect `D1-LOG` accepted waiver status.
   - Added gap-closure ownership rows to `COVERAGE.md` while preserving explicit opt-out boundaries.

## Verification

- `cargo test --manifest-path engine/Cargo.toml --locked grounding_limits` passed.
- `cargo test --manifest-path engine/Cargo.toml --locked --test config_startup service_ceiling_rejects_above_effective_limits` passed.
- Task 2 artifact verification script passed.

## Self-Check: PASSED
