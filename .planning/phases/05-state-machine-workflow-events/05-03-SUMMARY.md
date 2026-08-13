---
phase: 05-state-machine-workflow-events
plan: 03
subsystem: engine
tags: [rust, prompt-assembly, generation, state-machine, workflow-nodes, retry]

# Dependency graph
requires:
  - phase: 05-state-machine-workflow-events
    plan: 01
    provides: State machine WorkflowRunner and event streaming infrastructure
provides:
  - Cooperative async prompt packing with CancellationToken yield checkpoints
  - AssemblePromptNode workflow node implementing Node trait
  - GenerateAnswerNode workflow node implementing Node trait with retry snapshotting
  - Fixed 5-node runner sequence (Reformulate -> ExtractGraph -> Retrieve -> Assemble -> Generate)
  - Zero-evidence short-circuiting and exact answer event cardinality
affects: [05-04, 05-05]

# Tech tracking
tech-stack:
  added: [cooperative async prompt assembly, retry snapshotting]
  patterns: [state-machine workflow node extraction, retry snapshotting with zero backoff]

key-files:
  created:
    - engine/src/workflow/nodes/assemble_prompt.rs
    - engine/src/workflow/nodes/generate.rs
  modified:
    - engine/src/prompt.rs
    - engine/src/workflow/mod.rs
    - engine/src/workflow/nodes/mod.rs
    - engine/src/workflow/nodes/retrieve.rs
    - engine/src/workflow/runner.rs
    - engine/src/main.rs
    - engine/src/generation/openrouter.rs
    - engine/src/generation/tests.rs
    - engine/src/tests.rs

key-decisions:
  - "Extracted prompt assembly and answer generation into explicit AssemblePromptNode and GenerateAnswerNode implementing the Node trait."
  - "Converted prompt packing functions to cooperative async with tokio::task::yield_now().await checkpoints and cancellation token checks."
  - "Configured GenerateAnswerNode to capture byte-identical GenerationRequest snapshots for immediate retries with zero backoff and outer timeout budget."
  - "Wired fixed 5-node workflow runner pipeline while retaining D-03 zero-evidence short-circuiting and single terminal ownership."

requirements-completed: [GEN-01, GEN-02, GEN-03, EVENT-03]
---

# Phase 05 Plan 03 Summary

Extracted prompt assembly and answer generation into explicit state machine workflow nodes (`AssemblePromptNode` and `GenerateAnswerNode`) implementing the `Node` trait. Converted `pack_evidence_and_graph_prompt` to cooperative async with cancellation checkpoints. Implemented generation retry snapshotting with zero backoff, outer deadline bounds, and exact event cardinality (1 `AnswerChunk`, 1 `FinalAnswer`, 1 `WorkflowCompleted`). Verified all focused unit tests and full suite tests pass.
