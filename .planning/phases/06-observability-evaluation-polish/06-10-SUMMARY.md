# Phase 6 Plan 06-10: Support Model-Only Answers (Opt-In) Summary

## Executive Summary
Plan 06-10 implemented explicit, per-request, default-off opt-in support for model-only answers when no corpus evidence survives retrieval (resolving DEBT-RAG-01 / D-10 / D-11 / D-12 / D-84). The opt-in is configured via `[engine.workflow].allow_model_only_answers = false`, overridable via environment variable `LANCET_ENGINE__WORKFLOW__ALLOW_MODEL_ONLY_ANSWERS` (parsed with strict fail-closed validation), and resolved once at request admission with precedence: Request override -> Configuration -> `false`. When opted in, both grounding guards and zero-evidence runner short-circuit gates are bypassed, prompt assembly constructs an ungrounded prompt using `pack_model_only_prompt`, and the generator returns an honest, ungrounded response citing zero evidence blocks with a dedicated `NoticeCode::ModelOnly` notice.

---

## Configuration & Admission Details

### Configuration Key & Environment Variable
- **TOML Key**: `engine.workflow.allow_model_only_answers = false` in `config/config.toml` under `[engine.workflow]`.
- **Environment Variable**: `LANCET_ENGINE__WORKFLOW__ALLOW_MODEL_ONLY_ANSWERS`.
- **Exact Fail-Closed Error Message**:
  ```
  LANCET_ENGINE__WORKFLOW__ALLOW_MODEL_ONLY_ANSWERS must be true/false, got <value>
  ```
- **Resolution Order**:
  ```rust
  ctx.allow_model_only = req.allow_model_only.unwrap_or(self.effective_settings.workflow.allow_model_only_answers);
  ```
  Resolved once at admission in `engine/src/service.rs` and carried on `WorkflowContext.allow_model_only`. Downstream execution never re-reads environment or configuration.

---

## Grounding & Workflow Contract

### Grounding Validation Guards
In `engine/src/generation/mod.rs`, `GroundingLimits` was extended with `allow_model_only: bool` and `with_allow_model_only(mut self, allow_model_only: bool) -> Self`.
1. **Guard 1 (Basis acceptance)**:
   ```rust
   if !limits.allow_model_only && self.answer_basis == AnswerBasis::ModelOnly {
       return Err(GenerationError::new(
           GenerationErrorKind::SchemaValidation,
           "ModelOnly answer basis is not supported on Phase 03 QueryRAG path",
       ));
   }
   ```
2. **Guard 2 (Citation requirement)**:
   ```rust
   if self.cited_evidence_ids.is_empty()
       && (!limits.allow_model_only || self.answer_basis != AnswerBasis::ModelOnly)
   {
       return Err(GenerationError::new(
           GenerationErrorKind::SchemaValidation,
           format!(
               "answer basis '{}' requires at least one cited evidence ID",
               self.answer_basis
           ),
       ));
   }
   ```

### Prompt Assembly & Dedicated Helper
- **Helper in `engine/src/prompt.rs`**: `pub fn pack_model_only_prompt(question: &str) -> String`
- **Assembled Prompt Shape**:
  ```rust
  format!("{}\n\nQuestion: {}\n", base_system_policy(), question)
  ```
- **`AssemblePromptNode`**: When `ctx.evidence_blocks.is_empty()`, if `!ctx.allow_model_only`, returns `NodeErrorKind::PromptAssemblyFailed` ("No evidence blocks provided for prompt assembly"). If `ctx.allow_model_only`, populates `ctx.assembled_prompt = pack_model_only_prompt(&ctx.original_query)` and succeeds.

### Zero-Evidence Gate Bypass
- In `engine/src/workflow/runner.rs`, both the production gate (including both disjuncts) and tracer remainder gate check `!ctx.allow_model_only` before breaking/skipping.
- In `engine/src/workflow/nodes/generate.rs` and `run_inline_prompt_generation_remainder`:
  When opted in on zero evidence:
  - `ctx.answer_basis = AnswerBasis::ModelOnly`
  - `ctx.citations.clear()`
  - `ctx.structured_citations.clear()`
  - Emits verbatim notice:
    ```rust
    crate::workflow::notice(
        NoticeCode::ModelOnly,
        "Answer generated from parametric model knowledge without corpus evidence.",
        NoticeSeverity::Info,
    )
    ```

---

## Test Target Distribution & Invariants

| Target | Pre-Task Count | Post-Task Count | Delta |
|---|---|---|---|
| `engine (lib)` | 298 | 311 | +13 |
| `config_startup (test)` | 9 | 13 | +4 |
| `inspect_lancedb (bin)` | 18 | 18 | 0 |
| `engine (bin)` | 0 | 0 | 0 |
| `seed_rag_fixture (bin)` | 0 | 0 | 0 |
| **TOTAL** | **325** | **342** | **+17** |

All 7 Rust test target invariants in `scripts/engine-test-targets.sh` verified cleanly.
All clippy, fmt, locked cargo tests, and Go gateway tests pass cleanly.
