---
phase: 05-state-machine-workflow-events
plan: 26
type: execute
status: completed
executed_at: "2026-08-19T01:15:30.000Z"
requirements:
  - ORCH-01
  - ORCH-02
gap_closure: true
gap_ids:
  - G-05-1
files_modified:
  - engine/src/main.rs
  - engine/src/tests.rs
  - gateway/main_test.go
---

# Plan 05-26 Execution Summary: OpenRouter Model Overrides & Gateway Test Decoupling

## Overview

Plan 05-26 resolved UAT gap G-05-1 Blocker B by adding explicit environment variable override support for `LANCET_OPENROUTER__GENERATION_MODEL` and `LANCET_OPENROUTER__EMBEDDING_MODEL` in `engine/src/main.rs`, adding a dedicated unit test in `engine/src/tests.rs`, updating the `assertCleanRAGChildEnv` allowlist in `gateway/main_test.go`, and pinning `generation_model` to `openai/gpt-4o-mini` in both real-engine gateway integration tests (`TestRAGQueryCrossRuntime` and `TestRAGQueryClientDisconnectCancelsRustWorkflow`).

## Key Changes

1. **`engine/src/main.rs`**:
   - Added explicit env overrides in `load_settings()` for `LANCET_OPENROUTER__GENERATION_MODEL` and `LANCET_OPENROUTER__EMBEDDING_MODEL`.
2. **`engine/src/tests.rs`**:
   - Added unit test `config_openrouter_model_env_overrides_match_contract` (protected by `ENV_MUTEX`) asserting both `settings.openrouter` and `EffectiveRagSettings` properly reflect explicit env overrides.
3. **`gateway/main_test.go`**:
   - Added `LANCET_OPENROUTER__GENERATION_MODEL` and `LANCET_OPENROUTER__EMBEDDING_MODEL` to `assertCleanRAGChildEnv`'s allowed variable map.
   - Pinned `LANCET_OPENROUTER__GENERATION_MODEL=openai/gpt-4o-mini` in `ragChildEnv(...)` for `TestRAGQueryCrossRuntime` and `TestRAGQueryClientDisconnectCancelsRustWorkflow`, decoupling both tests from ambient `config/config.toml`.

## Verification

- `cargo test --manifest-path engine/Cargo.toml --locked config_openrouter_model_env_overrides_match_contract` passed (1 passed).
- `go test ./... -run "TestRAGQueryCrossRuntime|TestRAGQueryClientDisconnectCancelsRustWorkflow" -count=1` passed.
- Full gateway test suite `go test ./...` passed (exit code 0).
