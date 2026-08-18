---
phase: 05-state-machine-workflow-events
plan: 19
type: execute
status: completed
executed_at: "2026-08-18T03:55:00.000Z"
requirements:
  - ORCH-02
  - ORCH-03
  - ORCH-04
files_modified:
  - engine/src/workflow/events.rs
  - engine/src/workflow/runner.rs
  - engine/src/tests/workflow_phase5.rs
  - gateway/main.go
  - gateway/main_test.go
---

# Plan 05-19 Execution Summary: Preserve Failure Terminal Notices

## Overview

Plan 05-19 (Wave 17) wired accumulated context notices through failure terminal events from the Rust workflow runner to the Go gateway raw SSE event stream while keeping failure terminals answer-free:
1. Extended Rust WorkflowCompletedEvent construction and emission to pass accumulated context notices on both success and failure paths with no fabricated answers or final_response payload on failure.
2. Updated Gateway writeWorkflowEventSSE to map WorkflowCompletedEvent.notices into noticeDTO{code, message, severity} shape on failure terminals while omitting final_response.
3. Added Rust tracer workflow_phase5_failure_terminal_notices_tracer and comprehensive test workflow_phase5_failure_terminal_preserves_notices_without_answer_events.
4. Added Go raw SSE test TestRAGQueryFailureTerminalNoticesSSE to verify HTTP 200, ordered notice DTO shape, absence of final_response, absence of answer_chunk/final_answer, and in-band stream completion.

## Key Changes

1. **gateway/main.go**:
   - In writeWorkflowEventSSE, when e.WorkflowCompleted.GetFinalResponse() == nil, mapped e.WorkflowCompleted.GetNotices() to []noticeDTO on wcPayload["notices"].
2. **gateway/main_test.go**:
   - Added TestRAGQueryFailureTerminalNoticesSSE testing HTTP 200, headers, event sequence (node_failed before workflow_completed), absence of answer events, omission of final_response, and exact notice order/content.
3. **engine/src/tests/workflow_phase5.rs**:
   - Added workflow_phase5_failure_terminal_notices_tracer to assert failure terminal notice preservation and absence of answer chunks.
   - Added workflow_phase5_failure_terminal_preserves_notices_without_answer_events verifying both failure and success notice retention paths.

## Verification & Determinism

- **Task 1 Verification**:
  - workflow_phase5_failure_terminal_notices_tracer and TestRAGQueryFailureTerminalNoticesSSE passed.
- **Task 2 Verification**:
  - workflow_phase5_failure_terminal_preserves_notices_without_answer_events passed.
- **Task 3 Verification**:
  - TestRAGQueryFailureTerminalNoticesSSE passed in Go gateway test suite.
- **Full test suites**:
  - All Go gateway tests and engine library tests passed.
