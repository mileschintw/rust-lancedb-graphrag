# Phase 6 Plan 06-13: Production Model-Only Packing & Schema Admission Summary

## Executive Summary
Plan 06-13 closed verification gap SC3 by aligning `AssemblePromptNode`'s model-only packing and the OpenRouter generator packing path so opted-in zero-evidence queries reach the model and return `MODEL_ONLY`. OpenRouter packing was extracted into `pack_openrouter_messages`, `GenerationRequest` was augmented with `allow_model_only` and plumbed from `WorkflowContext` across both `GenerateAnswerNode` and the tracer remainder, a dedicated ungrounded `model_only_system_policy` was introduced in `engine/src/prompt.rs`, and the outbound structured output `answer_basis` schema enum admitted `model_only`.

---

## Key Changes & Components

### 1. Extracted OpenRouter Packing Helper (`engine/src/generation/openrouter.rs`)
- Extracted `pub(crate) async fn pack_openrouter_messages(...) -> Result<(String, String, Vec<EvidenceBlock>), GenerationError>` as a crate-visible free function.
- When `evidence` is empty and `allow_model_only` is true:
  - Skips `pack_evidence_and_graph_prompt` (preventing fail-closed `EmptyEvidence` error).
  - Builds system message from `crate::prompt::model_only_system_policy()` and user prompt from the raw question.
  - Returns an empty `Vec<EvidenceBlock>` validation slice.
- When `evidence` is empty and `allow_model_only` is false:
  - Delegates to `pack_evidence_and_graph_prompt`, preserving pre-existing fail-closed `EmptyEvidence` behavior.
- In `OpenRouterGenerator::execute_one_call`:
  - Passes `grounding_limits.with_allow_model_only(request.allow_model_only)` and the returned validation slice to `validate_grounding_with_limits`.

### 2. Dedicated Model-Only System Policy (`engine/src/prompt.rs`)
- Added `pub fn model_only_system_policy() -> &'static str`:
  ```rust
  "System Policy: You are a precise technical assistant. Answer the user's question accurately using your general knowledge. No corpus evidence is provided for this request; do not cite evidence markers."
  ```
- Updated `pack_model_only_prompt` to format `model_only_system_policy()` and the question.
- Preserved `base_system_policy()` with grounded citation requirements for evidence-backed generation.

### 3. Outbound `answer_basis` Schema Admission (`engine/src/generation/openrouter.rs`)
- Extended `properties.answer_basis.enum` from `["retrieval", "mixed"]` to `["retrieval", "mixed", "model_only"]`.
- Required properties remained unchanged: `["answer", "cited_evidence_ids", "answer_basis", "notices", "warnings"]`.

### 4. Opt-in Request Flag Plumbing
- Added `pub allow_model_only: bool` to `GenerationRequest` (default `false` in constructor, included in `PartialEq`).
- Plumbed `req.allow_model_only = ctx.allow_model_only` in `GenerateAnswerNode::run` and `run_inline_prompt_generation_remainder`.

---

## Test Target Distribution & Invariants

| Target | Pre-Plan Count | Post-Plan Count | Delta |
|---|---|---|---|
| `engine (lib)` | 338 | 342 | +4 |
| `config_startup (test)` | 17 | 17 | 0 |
| `inspect_lancedb (bin)` | 18 | 18 | 0 |
| `engine (bin)` | 0 | 0 | 0 |
| `seed_rag_fixture (bin)` | 0 | 0 | 0 |
| **TOTAL** | **373** | **377** | **+4** |

### Verified Tests
- `generate_answer_node_model_only_empty_evidence_uses_production_packing_path`
- `model_only_opt_in_empty_evidence_production_shaped_runner_returns_model_only`
- `pack_model_only_prompt_uses_ungrounded_policy`
- `openrouter_empty_evidence_opt_in_reaches_chat_with_model_only_schema`
- `pack_evidence_and_graph_prompt_empty_evidence_still_errors_regardless_of_graph_facts`
- All 7 Rust test target invariants in `scripts/engine-test-targets.sh` passed cleanly.
