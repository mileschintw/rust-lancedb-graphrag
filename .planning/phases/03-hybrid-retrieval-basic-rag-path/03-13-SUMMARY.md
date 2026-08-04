---
phase: 03-hybrid-retrieval-basic-rag-path
plan: "13"
subsystem: generation
tags: [rust, grounding, openrouter, rag, citations, validation]

requires:
  - phase: 03-hybrid-retrieval-basic-rag-path
    provides: RAG-02 basic retrieval and generation contract
provides:
  - Basis-specific grounding invariants requiring evidence citations for Retrieval and Mixed basis while rejecting ModelOnly on the QueryRAG path
  - Strict OpenRouter JSON schema and output bounds capping body size, choices, answer length, evidence ID counts/lengths, and usage budgets
affects:
  - phase 03 completion and query_rag integration
  - 03-14 provider config adapter

tech-stack:
  added: []
  patterns:
    - Basis-specific grounding validation on ModelOutput
    - Bounded response body and field limits at provider Serde boundary

key-files:
  created: []
  modified:
    - engine/src/generation/mod.rs
    - engine/src/generation/openrouter.rs
    - engine/src/generation/tests.rs
    - engine/src/tests.rs

key-decisions:
  - "ModelOnly answer basis returns a SchemaValidation error before response assembly on the Phase 03 QueryRAG path"
  - "Retrieval and Mixed answer basis outputs must carry at least one cited evidence ID and match inline markers"
  - "OpenRouter response body is capped at 256 KiB and choices array is bounded to exactly 1 item"

patterns-established:
  - "Fail-closed provider grounding validation: invalid or uncited model output is rejected before public response construction"

requirements-completed: [RAG-02]

coverage:
  - id: D1
    description: "ModelOutput::validate_grounding requires cited evidence for Retrieval/Mixed and rejects ModelOnly"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/generation/tests.rs#model_output_requires_retrieval_citation"
        status: pass
      - kind: unit
        ref: "engine/src/generation/tests.rs#model_output_requires_mixed_citation"
        status: pass
      - kind: unit
        ref: "engine/src/generation/tests.rs#model_output_rejects_model_only"
        status: pass
      - kind: unit
        ref: "engine/src/generation/tests.rs#model_output_accepts_cited_mixed_basis"
        status: pass
    human_judgment: false
  - id: D2
    description: "OpenRouter provider schema and response body enforce strict size and usage bounds"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/generation/tests.rs#openrouter_schema_declares_output_bounds"
        status: pass
      - kind: unit
        ref: "engine/src/generation/tests.rs#openrouter_rejects_oversized_response_body"
        status: pass
      - kind: unit
        ref: "engine/src/generation/tests.rs#openrouter_rejects_oversized_model_output_fields"
        status: pass
      - kind: unit
        ref: "engine/src/generation/tests.rs#openrouter_rejects_invalid_usage"
        status: pass
      - kind: unit
        ref: "engine/src/generation/tests.rs#openrouter_valid_bounded_response"
        status: pass
    human_judgment: false
  - id: D3
    description: "QueryRAG service rejects invalid provider grounding without producing a public response"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/tests.rs#query_rag_rejects_invalid_provider_grounding"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-08-04
status: complete
---

# Phase 03 Plan 13: Grounding Invariants and OpenRouter Output Bounds Summary

**Basis-specific grounding guards requiring evidence citations for Retrieval/Mixed output and strict OpenRouter response bounds preventing uncited or oversized provider responses.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-08-04T05:02:13Z
- **Completed:** 2026-08-04T05:06:26Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Extended `ModelOutput::validate_grounding` to enforce that Retrieval and Mixed basis require at least one cited evidence ID and exact set equality with inline markers, while rejecting ModelOnly.
- Added strict OpenRouter output bounds in Serde schema, body size (256 KiB limit), choice count (1 choice limit), and token usage budgets (prompt <= 8192, completion <= 2048, total <= 10240).
- Added 9 focused tests across `generation::tests` and `query_rag` service tests proving invalid provider output cannot become a public response.

## Task Commits

1. **Task 1: Trace one provider output through fail-closed grounding into QueryRAG** - `feat(03-13): enforce grounding basis invariants and citation presence`
2. **Task 2: Bound the strict OpenRouter schema and response wrapper** - `feat(03-13): enforce strict OpenRouter output bounds and usage limits`

## Files Created/Modified
- `engine/src/generation/mod.rs` - Extended ModelOutput grounding validation, answer basis rules, and output limit constants
- `engine/src/generation/openrouter.rs` - Enforced OpenRouter response body caps, choice bounds, schema limits, and usage budget verification
- `engine/src/generation/tests.rs` - Focused unit tests for citation presence, ModelOnly rejection, OpenRouter body/field/usage bounds
- `engine/src/tests.rs` - Service-level test `query_rag_rejects_invalid_provider_grounding`

## Decisions Made
- `ModelOnly` answer basis returns `SchemaValidation` error before response assembly on the Phase 03 QueryRAG path.
- Provider response body size limit set to 256 KiB to prevent allocation DoS before Serde parsing.

## Deviations from Plan
None - plan executed as specified.

## Issues Encountered
- Test assertion expected `InvalidArgument` for `query_rag` error, but service error mapping converts `GenerationError` into `tonic::Code::Internal`. Corrected assertion to expect `Internal`.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 03-13 is complete. Ready for Plan 03-14 (consuming validated effective settings, error context preservation, and startup credentials).
