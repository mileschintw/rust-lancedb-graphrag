---
status: investigating
trigger: "Decide the intended flag-off semantics on the D-18 total-drop path"
created: 2026-08-22T20:26:00.000Z
updated: 2026-08-22T20:26:00.000Z
---

## Current Focus

hypothesis: "generate.rs lines 258-259 unconditionally sets effective_allow = ctx.allow_model_only || total_drop, which allows model-only fallback on total citation drop even when allow_model_only is false."
test: "Inspect generate.rs:258-272 and test cases"
expecting: "total_drop should only downgrade when ctx.allow_model_only is true; otherwise it should fail with LlmGenerationFailed"
next_action: "Update UAT and plan gap closure"

## Symptoms

expected: "When allow_model_only is false, D-18 total-drop must return LlmGenerationFailed instead of succeeding as MODEL_ONLY."
actual: "effective_allow = ctx.allow_model_only || total_drop makes the run succeed with MODEL_ONLY regardless of allow_model_only flag."
errors: "None (unexpected success instead of failure)"
reproduction: "Set allow_model_only = false, evidence ['[1]'], model returns answer_basis: 'retrieval' with cited_evidence_ids: ['[9]'] and answer text citing only [9]."
started: "Phase 6 D-18 implementation"

## Evidence

- timestamp: 2026-08-22T20:26:00.000Z
  checked: "engine/src/workflow/nodes/generate.rs:258"
  found: "let effective_allow = ctx.allow_model_only || total_drop; let limits = limits.with_allow_model_only(effective_allow);"
  implication: "When total_drop is true, effective_allow is forced to true even if ctx.allow_model_only is false, bypassing fail-closed validation."

## Resolution

root_cause: "In engine/src/workflow/nodes/generate.rs:258, effective_allow is computed as ctx.allow_model_only || total_drop. When allow_model_only is false and all citations are dropped, total_drop forces effective_allow to true, converting the result to AnswerBasis::ModelOnly and passing validation instead of failing closed with NodeErrorKind::LlmGenerationFailed."
fix: "Change effective_allow computation so total_drop only succeeds when ctx.allow_model_only is true (or do not OR total_drop into allow_model_only), ensuring LlmGenerationFailed is returned when allow_model_only is false."
verification: "Add unit test for allow_model_only=false on total-drop path verifying NodeErrorKind::LlmGenerationFailed."
files_changed:
  - "engine/src/workflow/nodes/generate.rs"
