---
phase: 05-state-machine-workflow-events
plan: 20
subsystem: orchestration
tags: [generation, preflight, timeouts, workflow-runner, tokio]

requires:
  - phase: 05-state-machine-workflow-events
    provides: Generation adapter, workflow runner, and test fixtures from plans 05-13, 05-14, 05-16, 05-18, 05-19, 05-22
provides:
  - Asynchronous Generator and Node preparation hooks with default no-op implementations
  - OpenRouter capability preflight bootstrap separated from timed GenerateAnswer node execution
  - Worst-case paused-clock timing verification confirming two 30s provider attempts fit within the 65s node timer
  - Derived, non-enforced 102000ms whole-workflow bound documentation
  - Pre-deadline boundary tests for 4999ms reformulation and 9999ms retrieval operations
  - Bounded 5s happy-path receiver drain with AbortOnDrop cleanup
affects: [05-state-machine-workflow-events]

actuals:
  tokens: 1250
  tasks: 2
  commits: 1

tech-stack:
  added: []
  patterns: [bootstrap-preparation-seam, paused-clock-timing-proof, bounded-receiver-drain]

key-files:
  created: []
  modified:
    - engine/src/generation/mod.rs
    - engine/src/generation/openrouter.rs
    - engine/src/workflow/node.rs
    - engine/src/workflow/runner.rs
    - engine/src/workflow/nodes/generate.rs
    - engine/src/tests/workflow_phase5.rs

key-decisions:
  - "Capability preflight executes strictly as a preparation bootstrap before GenerateAnswer's 65000ms node timer begins."
  - "The 97000ms pre-preflight workflow arithmetic plus 5000ms preflight yields a derived, non-enforced 102000ms whole-workflow bound; independent node timers and uncapped SSE routes do not enforce this sum as a global ceiling."

patterns-established:
  - "Preparation hook pattern: Generator::prepare and Node::prepare allow optional bootstrap before elapsed timing."
  - "Paused-clock budget proof: Tokio time advancement validates worst-case multi-attempt retry deadlines deterministically."

requirements-completed: [ORCH-02, ORCH-03]

coverage:
  - id: D1
    description: "Capability preflight runs once as a bootstrap operation before GenerateAnswer node timer starts"
    requirement: "ORCH-02"
    verification:
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#workflow_phase5_generation_preflight_bootstrap_tracer"
        status: pass
    human_judgment: false
  - id: D2
    description: "Two 30000ms provider attempts complete after 5000ms preflight within 65000ms node timer"
    requirement: "ORCH-03"
    verification:
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#workflow_phase5_generation_preflight_worst_case_budget"
        status: pass
    human_judgment: false
  - id: D3
    description: "Pre-deadline 4999ms reformulation and 9999ms retrieval operations complete without timeout classification"
    requirement: "ORCH-03"
    verification:
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#workflow_phase5_reformulate_predeadline_4999ms_no_timeout"
        status: pass
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#workflow_phase5_retrieve_predeadline_9999ms_no_timeout"
        status: pass
    human_judgment: false
  - id: D4
    description: "Happy path event receiver drains under a 5-second timeout with AbortOnDrop cleanup"
    requirement: "ORCH-02"
    verification:
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#workflow_phase5_happy_path"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-08-18
status: complete
---

# Phase 05 Plan 20: Preflight Separation and Worst-Case Timing Proof Summary

**Separated capability preflight from the GenerateAnswer node timer and proved the two-attempt retry path fits the 65s node timer with paused-clock timing proofs and bounded receiver draining.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-08-18T05:39:00Z
- **Completed:** 2026-08-18T05:41:30Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- Implemented `Generator::prepare` and `Node::prepare` hooks so `GenerateAnswerNode` delegates preflight before node elapsed timing starts.
- Proved with Tokio paused-clock test `workflow_phase5_generation_preflight_worst_case_budget` that a 5s preflight followed by attempt 1 (30s timeout) and attempt 2 (30s success) completes under the 65s node timer.
- Verified 4999ms reformulation and 9999ms retrieval pre-deadline safety.
- Bound happy path receiver draining within a 5-second timeout with `AbortOnDrop` task cleanup.
- Ran the 9 production-binary exact filter tests successfully.

## Task Commits

1. **Task 1 & 2: Bootstrap generation capability and prove worst-case timing contracts** - (feat/test)

## Files Created/Modified

- `engine/src/generation/mod.rs` - Added default `Generator::prepare` hook.
- `engine/src/generation/openrouter.rs` - Integrated capability preflight in `prepare`.
- `engine/src/workflow/node.rs` - Added default `Node::prepare` hook.
- `engine/src/workflow/runner.rs` - Invoked `node.prepare()` prior to node timer and body.
- `engine/src/workflow/nodes/generate.rs` - Delegated `GenerateAnswerNode::prepare` to generator.
- `engine/src/tests/workflow_phase5.rs` - Added bootstrap tracer, worst-case timing, pre-deadline boundary, and bounded receiver tests.

## Decisions Made

- Capability preflight executes strictly as a preparation bootstrap before GenerateAnswer's 65000ms node timer begins.
- The 97000ms pre-preflight workflow arithmetic plus 5000ms preflight yields a derived, non-enforced 102000ms whole-workflow bound; independent node timers and uncapped SSE routes do not enforce this sum as a global ceiling.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Wave 19 plan 05-20 complete.
- Wave 20 (Plan 05-11) is the remaining plan in Phase 5.

---
*Phase: 05-state-machine-workflow-events*
*Completed: 2026-08-18*
