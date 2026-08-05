---
phase: 03-hybrid-retrieval-basic-rag-path
plan: 02
subsystem: generation
tags: [rust, prompt, evidence, openrouter, structured-output, reqwest]

# Dependency graph
requires:
  - phase: 03-hybrid-retrieval-basic-rag-path
    plan: 01
    provides: FusedCandidate retrieval candidates with RRF scoring and candidate metadata
provides:
  - Engine-owned EvidenceBlock prompt assembly, token budgeting, and delimiter escaping
  - Provider-neutral object-safe async Generator trait with Serde ModelOutput validation
  - Deterministic FakeGenerator for contract and prompt-boundary unit tests
  - Capability-checked one-shot OpenRouter adapter with supported_parameters preflight
affects: [03-03, 03-04, 03-05, RAG query coordinator]

# Tech tracking
tech-stack:
  added: []
  patterns: [untrusted evidence boundary, provider-neutral boxed-future trait, preflight supported_parameters metadata check]

key-files:
  created:
    - engine/src/prompt.rs
    - engine/src/generation/mod.rs
    - engine/src/generation/openrouter.rs
    - engine/src/generation/tests.rs
  modified:
    - engine/src/lib.rs
    - engine/src/main.rs

key-decisions:
  - "Reserve 2,048 tokens for answer generation budget before packing complete evidence blocks into prompt context."
  - "Escape <EVIDENCE> and <SYSTEM> tags (both case variants) to keep corpus text from forging prompt boundaries."
  - "Require OpenRouter model metadata to advertise response_format/structured_outputs in supported_parameters before making chat completions requests."
  - "Expose Generator as an object-safe Send + Sync boxed-future trait with OpenRouter as the production adapter and FakeGenerator for tests."

patterns-established:
  - "Retrieved corpus text is untrusted evidence; prompt assembly explicitly marks suspicious text and escapes delimiters."
  - "Numbered markers ([1]) resolve exclusively against engine-supplied evidence blocks."

requirements-completed: [RAG-02, RAG-04]

coverage:
  - id: D1
    description: "Provider-neutral Generator trait, closed ModelOutput, evidence packing, and marker resolution"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/generation/tests.rs#generation_bounded_evidence_valid_marker"
        status: pass
      - kind: unit
        ref: "engine/src/generation/tests.rs#prompt_evidence_budget_and_boundary"
        status: pass
      - kind: unit
        ref: "engine/src/generation/tests.rs#suspicious_evidence_remains_marked_unexecuted"
        status: pass
      - kind: unit
        ref: "engine/src/generation/tests.rs#corpus_conflict_returns_mixed_basis_with_disclosure"
        status: pass
    human_judgment: false
  - id: D2
    description: "Capability-checked one-shot OpenRouter adapter with supported_parameters preflight and structured output"
    requirement: RAG-04
    verification:
      - kind: unit
        ref: "engine/src/generation/tests.rs#openrouter_supported_parameters_one_call"
        status: pass
      - kind: other
        ref: "cargo test --manifest-path engine/Cargo.toml --locked"
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-08-02
status: complete
---

# Phase 03 Plan 02: Bounded Evidence Prompt Assembly and OpenRouter Adapter Summary

**Untrusted evidence prompt packaging, provider-neutral Generator trait, and capability-checked OpenRouter adapter**

## Performance

- **Duration:** 20 min
- **Started:** 2026-08-02T02:08:00Z
- **Completed:** 2026-08-02T02:28:00Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- Implemented `engine/src/prompt.rs` for whole-chunk evidence block assembly, token budget enforcement, delimiter escaping, and valid numbered marker resolution.
- Defined `engine/src/generation/mod.rs` with the provider-neutral `Generator` trait, closed `ModelOutput` schema, typed `GenerationError` classification, and deterministic `FakeGenerator`.
- Added `engine/src/generation/openrouter.rs` for one-shot OpenRouter structured output generation with preflight capability checks (`supported_parameters`).
- Implemented complete unit test coverage in `engine/src/generation/tests.rs` verifying prompt boundaries, marker resolution, suspicious evidence isolation, mixed answer basis disclosures, and OpenRouter mock requests.

## Task Commits

1. **Task 1: Trace fused candidates through bounded evidence and structured fake answer** - `feat(engine): add prompt evidence assembly and provider-neutral generator contract`
2. **Task 2: Implement capability-checked one-shot OpenRouter adapter** - `feat(engine): add OpenRouter generator adapter and contract tests`

## Files Created/Modified

- `engine/src/prompt.rs` - EvidenceBlock assembly, token budget packing, tag escaping, and marker resolution.
- `engine/src/generation/mod.rs` - Generator trait, ModelOutput, AnswerBasis, GenerationError, and FakeGenerator.
- `engine/src/generation/openrouter.rs` - Capability-checked OpenRouter chat completions adapter.
- `engine/src/generation/tests.rs` - Contract, prompt boundary, suspicious evidence, and OpenRouter mock tests.
- `engine/src/lib.rs` - Re-exported `prompt` and `generation` modules.
- `engine/src/main.rs` - Module declarations for `prompt` and `generation`.

## Decisions Made

- Token budget calculation reserves 2,048 tokens for answer generation before packing complete evidence chunks into context.
- Evidence delimiters `<EVIDENCE>`, `</EVIDENCE>`, `<SYSTEM>`, `</SYSTEM>` (and lowercase variants) are escaped so untrusted text cannot break out of evidence boundaries.
- Preflight model capabilities check (`supported_parameters`) ensures OpenRouter models advertise structured output capabilities before completing requests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated FusedCandidate field access in prompt assembly**
- **Found during:** Task 1 initial compilation
- **Issue:** `FusedCandidate` wraps inner candidate metadata in `.candidate`.
- **Fix:** Accessed `.candidate.<field>` for `document_id`, `title`, `section_path`, `content`, etc.
- **Files modified:** `engine/src/prompt.rs`, `engine/src/generation/tests.rs`
- **Verification:** Cargo compilation passed.

**2. [Rule 1 - Bug] Extended delimiter tag escaping to include lowercase variants**
- **Found during:** Task 1 test run (`suspicious_evidence_remains_marked_unexecuted`)
- **Issue:** Test fixture contained lowercase `<system>` tag which was not replaced by uppercase-only tag replacement.
- **Fix:** Added case variants for `<evidence>`, `</evidence>`, `<system>`, `</system>` tag escaping.
- **Files modified:** `engine/src/prompt.rs`
- **Verification:** `suspicious_evidence_remains_marked_unexecuted` passed cleanly.

**3. [Rule 3 - Blocking] Added self re-export in lib.rs for internal module references**
- **Found during:** Workspace test compilation
- **Issue:** Binary test target referenced `engine::db` while `lib.rs` lacked `extern crate self as engine`.
- **Fix:** Added `extern crate self as engine;` at top of `engine/src/lib.rs`.
- **Files modified:** `engine/src/lib.rs`
- **Verification:** All 80 workspace tests passed cleanly.

---

**Total deviations:** 3 auto-fixed (1 Rule 1, 2 Rule 3)
**Impact on plan:** All fixes were required for compilation and correct test verification; no scope changed.

## User Setup Required

- Setting `OPENROUTER_API_KEY` environment variable is required only when running the optional ignored live smoke test `openrouter_structured_output_smoke`. Normal automated tests use local mocks and fakes.

## Next Plan Readiness

- `03-02-PLAN.md` is complete. Wave 2 of Phase 03 is complete.
- Wave 3 (`03-03-PLAN.md`) is ready for execution.

---
*Phase: 03-hybrid-retrieval-basic-rag-path*
*Completed: 2026-08-02*
