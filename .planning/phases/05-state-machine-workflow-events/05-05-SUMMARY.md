---
phase: 05-state-machine-workflow-events
plan: 05
subsystem: gateway
tags: [go, postgresql, atlas, sqlc, checkpoint, persistence]

# Dependency graph
requires:
  - plan: 05-04
    provides: State-machine edge matrix test harness
  - plan: 05-06
    provides: Streaming contract and CheckpointDispatcher seam
provides:
  - Durable PostgreSQL workflow_checkpoints table and trace-order index
  - sqlc generated WorkflowCheckpoint models and InsertWorkflowCheckpoint query
  - Production PostgresCheckpointSink and detached persistence binding
  - Comprehensive unit and isolated PostgreSQL schema integration test suite
affects: []

# Tech tracking
tech-stack:
  added: [Atlas workflow_checkpoints table, sqlc InsertWorkflowCheckpoint, PostgresCheckpointSink]
  patterns: [detached PostgreSQL persistence, isolated test schema per test, full JSONB context snapshot]

key-files:
  created:
    - .planning/phases/05-state-machine-workflow-events/05-05-SUMMARY.md
  modified:
    - gateway/db/schema.hcl
    - gateway/db/schema.sql
    - gateway/db/query.sql
    - gateway/db/models.go
    - gateway/db/query.sql.go
    - gateway/checkpoint_sink.go
    - gateway/main.go
    - gateway/main_test.go

key-decisions:
  - "workflow_checkpoints uses UUID-string primary key, trace_id, sequence_ordinal, node_name, JSONB context_snapshot, and created_at with index (trace_id, sequence_ordinal, created_at)."
  - "Go generates UUID for row ID and executes InsertWorkflowCheckpoint using an independent background context so canceled requests do not delay or corrupt persistence."
  - "All checkpoint snapshot data is stripped from SSE DTOs and kept in PostgreSQL for audit and failure investigation."

requirements-completed: [ORCH-02, ORCH-04]
---

# Phase 05 Plan 05 Summary

Persisted ordered full workflow snapshots through the Go-owned PostgreSQL boundary using Atlas and sqlc.

## Key Changes
- **Atlas & SQL Schema**: Declared the 6-column `workflow_checkpoints` table with UUID-string `id` primary key, `trace_id`, `sequence_ordinal`, `node_name`, `context_snapshot` JSONB, and `created_at` timestamp in `gateway/db/schema.hcl` and `gateway/db/schema.sql`, indexed on `(trace_id, sequence_ordinal, created_at)`.
- **sqlc Generation**: Added `InsertWorkflowCheckpoint` parameterized query to `gateway/db/query.sql` and generated updated Go models in `gateway/db/models.go` and `gateway/db/query.sql.go`.
- **PostgresCheckpointSink**: Implemented `PostgresCheckpointSink` in `gateway/checkpoint_sink.go` using independent 5-second write contexts, bound to `CheckpointDispatcher` in `gateway/main.go`.
- **Integration Tests**: Added `TestWorkflowCheckpointSchemaArtifacts`, `TestWorkflowCheckpointTracer`, `TestWorkflowCheckpointPersistence`, `TestWorkflowCheckpointCancellationAtomicity`, `TestWorkflowCheckpointBackpressureDoesNotStallSSE`, and `TestQueryRAGRealInvalidRequestAndDisconnect` with isolated schema helpers (`newWorkflowCheckpointsIsolatedPostgres`).

## Verification
- `sqlc generate` executed cleanly.
- All Go unit and database-gated tests in `gateway` passed cleanly (`go test -v`).
