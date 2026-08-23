# Phase 6 Plan 06-15: Grounding Validator Split, Inline Remainder Gate & SC3/SC5 Proofs Summary

## Executive Summary
Plan 06-15 closed verification gaps SC3 (D-10, D-11, D-12) and SC5 (D-14) by relocating the grounding validator's marker checks out of the provider adapter (`OpenRouterGenerator`) into the workflow seam (`GenerateAnswerNode` and `run_inline_prompt_generation_remainder`). The provider adapter now enforces non-repairable output shape validation against limits, while marker grounding, repair normalization, dropping, and basis reconciliation are owned downstream by the workflow layer. The published inline remainder generation path is gated against ungrounded outputs before context mutation. All five adapter-driven integration tests verify end-to-end execution through the real `OpenRouterGenerator` against local mock HTTP servers.

---

## Key Changes & Components

### 1. Published Inline Generation Remainder Gate (`engine/src/workflow/mod.rs`, `engine/src/service.rs`)
- Added `pub grounding_limits: crate::generation::GroundingLimits` to `WorkflowDependencies` (defaulting to `GroundingLimits::default_limits()`).
- Initialized `grounding_limits: *self.effective_settings.grounding_limits()` in `service.rs`'s `build_query_rag_runner`.
- Gated `run_inline_prompt_generation_remainder` before any `ctx` mutation with `validate_grounding_with_limits`, emitting `events::node_failed` on rejection.
- Verified with unit test `inline_remainder_rejects_ungrounded_model_output`.

### 2. Validator Decomposition (`engine/src/generation/mod.rs`)
- Split `validate_grounding_with_limits` into two distinct public methods:
  - `validate_output_shape_with_limits(&self, limits: GroundingLimits) -> Result<(), GenerationError>`: shape checks (model-only allowance, non-empty answer, length bounds, notice/warning bounds, token usage ceiling).
  - `validate_marker_grounding(&self, packed_evidence: &[EvidenceBlock]) -> Result<(), GenerationError>`: semantic marker checks (duplicate cited IDs, known ID membership, inline marker membership, set equality).
- Recomposed `validate_grounding_with_limits` as the sequential composition of shape checks followed by marker checks, preserving all existing caller contracts and error strings verbatim.

### 3. Reduced Adapter Gate & Prompt Guidance (`engine/src/generation/openrouter.rs`, `engine/src/prompt.rs`)
- In `OpenRouterGenerator::execute_one_call`, replaced full grounding validation with `validate_output_shape_with_limits` evaluated against a model-only view when opted in with empty evidence.
- Raw model output is returned unconverted to the caller.
- Appended explicit sentence to `prompt::model_only_system_policy()` instructing `answer_basis` to be `model_only` with empty `cited_evidence_ids`.

### 4. Engine-Decided Model-Only Basis in Workflow Node (`engine/src/workflow/nodes/generate.rs`)
- In branch 1 of `GenerateAnswerNode`, validated `for_validation` (`output.into_model_only()`) with `validate_grounding_with_limits` and passed `&for_validation` to `update_from_model_output`, ensuring the engine deterministically decides `AnswerBasis::ModelOnly`.

---

## Threat Disposition: T-06-15-03

- **Threat ID**: `T-06-15-03` (Spoofing / Known-ID universe widening from packed evidence subset to `ctx.evidence_blocks`)
- **Severity / Disposition**: `medium / mitigate`
- **Accepted Residual**: Post-split, marker checks bind to `ctx.evidence_blocks` (the full retrieved set) rather than the packed subset, so a marker naming a retrieved block that was truncated out of the prompt resolves rather than causing fail-closed rejection. Every surviving citation still binds to a real retrieved chunk via `resolve_citations`, and `resolve_markers` drops unresolved markers rather than guessing.
- **Status**: Confirmed unchanged as planned during execution.

---

## Mock Chat Response Bodies for Adapter-Driven Tests

All five tests in `engine/src/tests/workflow_phase5_production.rs` drive a real `OpenRouterGenerator` against a mock HTTP server without hardcoding the asserted outcome:

1. `openrouter_node_optin_empty_evidence_retrieval_basis_still_yields_model_only` (SC3 Opt-in Engine Decision):
   ```json
   {
     "answer": "This is a model-only answer.",
     "cited_evidence_ids": [],
     "answer_basis": "retrieval",
     "notices": [],
     "warnings": []
   }
   ```
2. `openrouter_node_standalone_near_miss_marker_is_repaired` (SC5 Standalone Near-Miss Repair):
   ```json
   {
     "answer": "Padded standalone marker [ 7 ] in text.",
     "cited_evidence_ids": ["[7]"],
     "answer_basis": "retrieval",
     "notices": [],
     "warnings": []
   }
   ```
3. `openrouter_node_strict_visible_unresolvable_marker_is_dropped` (SC5 Strict-Visible Marker Drop):
   ```json
   {
     "answer": "Answer with healthy [1] and unresolvable [9].",
     "cited_evidence_ids": ["[1]"],
     "answer_basis": "retrieval",
     "notices": [],
     "warnings": []
   }
   ```
4. `openrouter_node_total_citation_loss_downgrades_basis_to_model_only` (SC5 Total Citation Loss Downgrade):
   ```json
   {
     "answer": "Answer citing only unresolvable [9].",
     "cited_evidence_ids": ["[9]"],
     "answer_basis": "retrieval",
     "notices": [],
     "warnings": []
   }
   ```
5. `openrouter_node_model_only_flag_off_stays_fail_closed` (SC3 Flag-off Fail-closed):
   - No mock response body returned; fails closed before chat dispatch (`chat_calls == 0`).

---

## Test Target Distribution & Invariants

| Target | Pre-Plan Count | Post-Plan Count | Delta |
|---|---|---|---|
| `engine (lib)` | 345 | 351 | +6 |
| `config_startup (test)` | 17 | 17 | 0 |
| `inspect_lancedb (bin)` | 18 | 18 | 0 |
| `engine (bin)` | 0 | 0 | 0 |
| `seed_rag_fixture (bin)` | 0 | 0 | 0 |
| **TOTAL** | **380** | **386** | **+6** |

All 7 Rust test target invariants in `scripts/engine-test-targets.sh` verified and passing cleanly.
