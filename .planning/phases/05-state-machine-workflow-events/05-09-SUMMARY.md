---
phase: 05-state-machine-workflow-events
plan: 09
subsystem: workflow
tags: [workflow, timeouts, cancellation, production, stream-drop, settings]

# Dependency graph
requires:
  - phase: 05-state-machine-workflow-events (05-08)
    provides: Production workflow builder and five-node execution path
provides:
  - "Configurable production workflow timeout settings under engine.workflow"
  - "Runner-level immediate cancellation token trigger on node timeout"
  - "gRPC stream drop cancellation guard (CancelOnDropStream) for client disconnects"
  - "Full verification config overlay for live timeout testing (config/config.verify.toml)"
  - "Regression test coverage in workflow_phase5.rs, workflow_phase5_production.rs, and tests.rs"
affects: [05-12, 05-22]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Stream wrapper RAII drop guard triggering CancellationToken::cancel on client disconnect"
    - "Timeout branch explicit CancellationToken::cancel invocation prior to NodeFailed(Timeout) construction"

key-files:
  created:
    - .planning/phases/05-state-machine-workflow-events/05-09-SUMMARY.md
  modified:
    - config/config.verify.toml
    - engine/src/main.rs
    - engine/src/workflow/runner.rs
    - engine/src/tests.rs
    - engine/src/tests/workflow_phase5.rs
    - engine/src/tests/workflow_phase5_production.rs

key-decisions:
  - "Added WorkflowConfigSettings and typed WorkflowSettings to engine configuration with positive duration validation."
  - "Updated load_settings to support LANCET_ENGINE__WORKFLOW__* environment variable overrides for all 7 timeout knobs."
  - "Wired LancetServiceImpl::build_production_workflow to apply configured timeouts to WorkflowRunner and ExtractGraphContextNode."
  - "Updated WorkflowRunner::run_node to trigger cancel.cancel() upon node timeout expiry before returning NodeError::timeout."
  - "Wrapped the gRPC response receiver stream in CancelOnDropStream in query_rag to immediately cancel background node work when the client disconnects."
  - "Updated config/config.verify.toml with explicit workflow timeouts including generation_node_timeout_ms = 7000."

patterns-established:
  - "CancellationToken propagation and immediate teardown upon timeout expiry or response stream drop ensures no wasted background I/O or stalled provider calls."

requirements-completed: [ORCH-01, ORCH-02, ORCH-03]

coverage:
  - id: D-08
    description: "Production workflow timeout settings, stream drop cancellation, and node timeout cancellation"
    requirement: "ORCH-01"
    verification:
      - kind: automated
        ref: "cargo test --manifest-path engine/Cargo.toml --locked -- workflow_phase5_timeout_cancels_stalled_provider"
        status: pass
      - kind: automated
        ref: "cargo test --manifest-path engine/Cargo.toml --locked -- config_workflow_nested_env_overrides_match_contract"
        status: pass
      - kind: automated
        ref: "cargo test --manifest-path engine/Cargo.toml --locked -- workflow_phase5_settings_applied_to_production"
        status: pass
      - kind: automated
        ref: "cargo test --manifest-path engine/Cargo.toml --locked -- workflow_phase5_config_verify_generation_timeout"
        status: pass
---

# Plan 05-09 Summary: Production Workflow Timeout Wiring, Stream Cancellation, and Verification Overlay

## Work Accomplished
1. **Production Configuration & Environment Overrides**:
   - Added `WorkflowConfigSettings` and `WorkflowSettings` structs with serde defaults and validation verifying that all 7 timeout values are greater than 0:
     - `reformulate_timeout_ms` (5000)
     - `query_embedding_timeout_ms` (10000)
     - `retrieve_timeout_ms` (10000)
     - `graph_operation_timeout_ms` (4000)
     - `graph_node_timeout_ms` (15000)
     - `prompt_timeout_ms` (2000)
     - `generation_node_timeout_ms` (65000 in base config; 7000 in verification overlay)
   - Added environment variable parsing in `load_settings()` for `LANCET_ENGINE__WORKFLOW__*` keys.
   - Updated `LancetServiceImpl::build_production_workflow()` to configure timeouts dynamically from `EffectiveRagSettings.workflow`.

2. **Stream Drop and Timeout Cancellation Guards**:
   - Updated `WorkflowRunner::run_node()` to explicitly trigger `cancel.cancel()` when a node timeout expires, ensuring any in-flight provider calls or child tasks observing the token stop before returning `Err(NodeError::timeout(name))`.
   - Created `CancelOnDropStream` in `engine/src/main.rs` wrapping `ReceiverStream` to trigger `cancel.cancel()` when tonic client disconnects and drops the response stream.

3. **Verification Overlay & Regression Tests**:
   - Configured `config/config.verify.toml` with `[openrouter].generation_timeout_secs = 30` and all 7 workflow timeout values (with `generation_node_timeout_ms = 7000`), preserving `engine.lancedb_path`.
   - Added `config_workflow_timeout_overlays_match_contract` and `config_workflow_nested_env_overrides_match_contract` in `engine/src/tests.rs`.
   - Added `workflow_phase5_timeout_cancels_stalled_provider` in `engine/src/tests/workflow_phase5.rs`.
   - Added `workflow_phase5_settings_applied_to_production` and `workflow_phase5_config_verify_generation_timeout` in `engine/src/tests/workflow_phase5_production.rs`.
   - All 15 workflow phase 5 tests, config startup tests, and automated plan verification checks pass.
