# Phase 6 Plan 06-16: Gap Closure for G-06-1 (D-18 Total-Drop Flag-Off Fail-Closed) and G-06-2 (Truncated Citation Resolution Drop) Summary

## Executive Summary
Plan 06-16 closed UAT gaps G-06-1 and G-06-2 following human review rulings:
1. **G-06-1**: Enforced fail-closed behavior on the D-18 total citation drop path in `GenerateAnswerNode` when `allow_model_only` is false (`ctx.allow_model_only = false`). Total citation drop only downgrades to `AnswerBasis::ModelOnly` when `allow_model_only` is explicitly opted into (`true`); otherwise it rejects the response with `NodeErrorKind::LlmGenerationFailed`.
2. **G-06-2**: Ensured citations referencing retrieved-but-truncated blocks (chunks excluded from the prompt-packed subset due to token budget) do not resolve or ship excerpts. The known-ID universe for marker repair and citation resolution is strictly bound to the prompt-packed subset (`ctx.evidence_blocks`). Citations naming truncated blocks are dropped with `CITATION_DROPPED` notices.

All 392 Rust tests across all targets pass cleanly, and all 7 test target invariants in `scripts/engine-test-targets.sh` are verified.

---

## Key Changes & Components

### 1. Flag-Dependent Total-Drop Gating (`engine/src/workflow/nodes/generate.rs`)
- In `GenerateAnswerNode::run` (around line 258), updated `effective_allow` calculation from `ctx.allow_model_only || total_drop` to strictly `ctx.allow_model_only`.
- When all citations drop (`total_drop = true`) and `ctx.allow_model_only` is `false`, `validate_grounding_with_limits` rejects the `into_model_only()` model output with `GenerationError::ModelOnlyNotAllowed`, which fails closed with `NodeError::new(NodeErrorKind::LlmGenerationFailed, ...)`.
- When `ctx.allow_model_only` is `true`, `validate_grounding_with_limits` permits `AnswerBasis::ModelOnly`, context is updated via `update_from_model_output`, and `CITATION_DROPPED` + `BASIS_RECONCILED` notices are emitted.

### 2. Truncated Block Citation Drop & Excerpt Suppression (`engine/src/workflow/nodes/generate.rs`, `engine/src/tests/workflow_phase5.rs`)
- `AssemblePromptNode` packs evidence up to token limits and updates `ctx.evidence_blocks` to contain only the prompt-packed subset.
- `GenerateAnswerNode` collects `evidence_ids` from `ctx.evidence_blocks`.
- Any citation referencing a truncated block (not present in `ctx.evidence_blocks`) fails marker resolution in `citations::resolve_markers`, gets marked `Resolution::Dropped`, is stripped from `repaired_answer`, and emits a `CITATION_DROPPED` notice. No structured citation or excerpt is shipped.

### 3. Regression Tests Added (`engine/src/tests/workflow_phase5.rs`, `engine/src/tests/workflow_phase5_production.rs`, `engine/src/tests.rs`)
- `openrouter_node_total_citation_loss_downgrades_basis_to_model_only`: verifies flag-on total drop succeeds through `OpenRouterGenerator`.
- `openrouter_node_total_citation_loss_flag_off_fails_closed`: verifies flag-off total drop fails closed with `LlmGenerationFailed` through `OpenRouterGenerator`.
- `citation_repair_total_drop_downgrades_basis_and_succeeds`: unit test verifying flag-on total drop produces `ModelOnly` and notices.
- `citation_repair_total_drop_flag_off_fails_closed`: unit test verifying flag-off total drop returns `NodeErrorKind::LlmGenerationFailed`.
- `citation_to_truncated_block_is_dropped_and_ships_no_excerpt_flag_off_fails_closed`: verifies citing truncated block with flag-off fails closed.
- `citation_to_truncated_block_is_dropped_and_ships_no_excerpt_flag_on_succeeds_model_only`: verifies citing truncated block with flag-on succeeds as `ModelOnly`.
- `citation_to_surviving_and_truncated_blocks_resolves_surviving_and_drops_truncated`: verifies surviving citation resolves with structured citation / excerpt while truncated citation is dropped with `CITATION_DROPPED` notice.
- `workflow_prompt_packing_truncation_drops_citation_to_truncated_block`: end-to-end workflow runner test verifying prompt token packing truncation dropping.

---

## Test Target Distribution & Invariants

| Target | Pre-Plan Count | Post-Plan Count | Delta |
|---|---|---|---|
| `engine (lib)` | 351 | 357 | +6 |
| `config_startup (test)` | 17 | 17 | 0 |
| `inspect_lancedb (bin)` | 18 | 18 | 0 |
| `engine (bin)` | 0 | 0 | 0 |
| `seed_rag_fixture (bin)` | 0 | 0 | 0 |
| **TOTAL** | **386** | **392** | **+6** |

All 7 invariants verified via `bash scripts/engine-test-targets.sh`.
