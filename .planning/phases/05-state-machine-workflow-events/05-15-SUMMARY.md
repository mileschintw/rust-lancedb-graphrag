---
phase: 05-state-machine-workflow-events
plan: 15
type: execute
status: completed
executed_at: "2026-08-17T22:02:00.000Z"
requirements:
  - ORCH-05
files_modified:
  - engine/src/prompt.rs
  - engine/src/workflow/ports.rs
  - engine/src/generation/mod.rs
  - engine/src/tests.rs
  - engine/src/tests/workflow_phase5.rs
  - engine/src/tests/workflow_phase5_production.rs
---

# Plan 05-15 Execution Summary: Prompt API Documentation and Test-Double Hygiene

## Overview

Plan 05-15 (Wave 14) addressed prompt API documentation gaps and test-double hygiene without altering the locked prompt protocol or workflow state machine semantics:
1. Documented `pack_evidence_prompt` and `pack_evidence_and_graph_prompt` with rustdoc summaries adhering to guidelines (M-FIRST-DOC-SENTENCE, M-CANONICAL-DOCS), explicit `# Errors` (documenting `EmptyEvidence`, `NoEvidenceFits`, `Cancelled`), `# Graph Weight Semantics`, and `# Cancellation`.
2. Gated synchronous helpers `pack_evidence_prompt_sync` and `pack_evidence_and_graph_prompt_sync` under `#[cfg(test)] pub(crate)`.
3. Gated all test fakes (`FakeQueryReformulator`, `FakeQueryEmbeddingPort`, `IntoGraphFacts`, `FakeGraphQueryPort`, `FakeDenseRetrievalPort`, `FakeBm25RetrievalPort`, `FakeReranker`, `FakeGenerator`) under `#[cfg(test)]` in `engine/src/workflow/ports.rs` and `engine/src/generation/mod.rs`, preserving `NoOpQueryReformulator` and production port traits in ungated production code.
4. Added exact regression tests in `engine/src/tests/workflow_phase5.rs`:
   - `workflow_phase5_prompt_api_surface`
   - `workflow_phase5_prompt_graph_weight_semantics`
   - `workflow_phase5_fake_ports_test_only` (including source assertions verifying `#[cfg(test)]` annotations on fake declarations).

## Key Changes

1. **`engine/src/prompt.rs`**:
   - Added canonical rustdoc to `pack_evidence_prompt` and `pack_evidence_and_graph_prompt`.
   - Annotated `pack_evidence_prompt_sync` and `pack_evidence_and_graph_prompt_sync` with `#[cfg(test)] #[allow(dead_code)] pub(crate)`.
2. **`engine/src/workflow/ports.rs`**:
   - Annotated all `Fake*` structs, the `IntoGraphFacts` trait, and their implementations with `#[cfg(test)]`.
   - Kept production traits and `NoOpQueryReformulator` ungated.
   - Scoped test-only imports under `#[cfg(test)]`.
3. **`engine/src/generation/mod.rs`**:
   - Annotated `FakeGenerator` and its implementations with `#[cfg(test)]`.
   - Scoped test-only sync types under `#[cfg(test)]`.
4. **`engine/src/tests/workflow_phase5.rs`**:
   - Added `workflow_phase5_prompt_api_surface` covering empty evidence, pre-cancellation, token budget fitting, and structured output.
   - Added `workflow_phase5_prompt_graph_weight_semantics` verifying `graph_weight == 0.0` exclusion and positive `graph_weight` interleaving.
   - Added `workflow_phase5_fake_ports_test_only` asserting source-level `#[cfg(test)]` gating and test-mode usability.
5. **`engine/src/tests.rs` & `engine/src/tests/workflow_phase5_production.rs`**:
   - Added binary test-scoped `FakeGenerator` and updated callers to maintain binary test target compile cleanliness without relying on ungated production exports.

## Verification

- **Task 1 Verification**:
  - Test registration check for `workflow_phase5_prompt_api_surface` and `workflow_phase5_prompt_graph_weight_semantics` passed.
  - `cargo test --lib --manifest-path engine/Cargo.toml --locked -- --exact workflow_phase5_prompt_api_surface --nocapture` passed.
  - `cargo test --lib --manifest-path engine/Cargo.toml --locked -- --exact workflow_phase5_prompt_graph_weight_semantics --nocapture` passed.
- **Task 2 Verification**:
  - `cargo test --lib --manifest-path engine/Cargo.toml --locked -- --exact workflow_phase5_fake_ports_test_only --nocapture` passed.
  - `cargo test --bin engine --manifest-path engine/Cargo.toml --locked --no-run` passed.
  - Full library test suite `cargo test --lib --manifest-path engine/Cargo.toml --locked` passed with 0 failures and 0 warnings.
