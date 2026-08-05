---
phase: 03-hybrid-retrieval-basic-rag-path
plan: "16"
subsystem: generation
tags: [rust, openrouter, limits, grounding, configuration]

requires:
  - phase: 03-hybrid-retrieval-basic-rag-path
    provides: 03-15 complete locked Rust test suite pass
provides:
  - Shared GroundingLimits carrier with service-safe limits (16,384 evidence, 4,096 output, 20,480 total)
  - Effective limits wired to OpenRouter adapter request, usage check, and ModelOutput grounding validation
  - Startup readiness rejection for above-ceiling configurations
affects:
  - phase 03 gap closure

tech-stack:
  added: []
  patterns:
    - Shared GroundingLimits carrier derived from EffectiveRagSettings
    - Readiness validation of service-safe resource ceilings before engine startup

key-files:
  created:
    - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-16-SUMMARY.md
  modified:
    - engine/src/generation/mod.rs
    - engine/src/generation/openrouter.rs
    - engine/src/generation/tests.rs
    - engine/src/main.rs
    - engine/tests/config_startup.rs

key-decisions:
  - "GroundingLimits carrier enforces evidence budget ceiling 16,384, max output tokens ceiling 4,096, and derived total ceiling 20,480"
  - "Above-ceiling evidence or output limits in EffectiveRagSettings fail engine startup before listening"

patterns-established:
  - "Single limits carrier passed to prompt packing, OpenRouter adapter request, and response grounding validation"

requirements-completed: [RAG-02]

coverage:
  - id: G1-adapter
    description: "Effective provider usage limits are respected for non-default in-limit responses and over-limit responses fail schema validation"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/generation/tests.rs#openrouter_effective_usage_limits"
        status: pass
    human_judgment: false
  - id: G1-startup
    description: "Configuration above service ceilings (16,385 evidence or 4,097 output) fails readiness before listening"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/tests/config_startup.rs#service_ceiling_rejects_above_effective_limits"
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-08-04
status: complete
---

# Phase 03 Plan 16: Service-Safe Provider Limits and Grounding Limits Carrier Summary

**Implementation of ADR-03-001 decision G1 establishing GroundingLimits as the single authoritative provider usage carrier across prompt packing, OpenRouter request construction, provider response usage checks, and startup readiness validation.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-08-04T21:31:00Z
- **Completed:** 2026-08-04T21:35:50Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Introduced `GroundingLimits` struct with service-safe ceilings of 16,384 evidence tokens, 4,096 output tokens, and 20,480 total tokens.
- Updated `ModelOutput::validate_grounding_with_limits` and `OpenRouterGenerationConfig` to consume `GroundingLimits`.
- Wired `EffectiveRagSettings` to derive `GroundingLimits` and reject above-ceiling configurations at startup before listening.
- Added `openrouter_effective_usage_limits` test proving non-default in-limit responses succeed while over-limit usage fails.
- Added `service_ceiling_rejects_above_effective_limits` integration test verifying readiness rejection and non-listening for above-ceiling values.

## Task Commits

1. **Task 1: Trace EffectiveRagSettings limits through provider usage validation** - `feat(03-16): implement GroundingLimits carrier and effective provider usage validation`
2. **Task 2: Prove service ceilings reject readiness-invalid configuration** - `test(03-16): add service_ceiling_rejects_above_effective_limits integration test`

## Files Created/Modified
- `engine/src/generation/mod.rs` - Added `GroundingLimits` carrier, constants, and `validate_grounding_with_limits`
- `engine/src/generation/openrouter.rs` - Updated `OpenRouterGenerationConfig` and `execute_one_call` to use `GroundingLimits`
- `engine/src/generation/tests.rs` - Added `openrouter_effective_usage_limits` mock adapter test
- `engine/src/main.rs` - Wired `EffectiveRagSettings` to validate `GroundingLimits` and added env overrides
- `engine/tests/config_startup.rs` - Added `service_ceiling_rejects_above_effective_limits` process test

## Decisions Made
- `GroundingLimits` is derived once in `EffectiveRagSettings::try_from_settings` and validated before startup.
- Provider usage validation in `OpenRouterGenerator` evaluates against configured `GroundingLimits` rather than hardcoded default constants.

## Deviations from Plan
None - plan executed as specified.

## Issues Encountered
None - all unit and process integration tests passed.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 03-16 complete and committed. Proceed to Plan 03-17.
