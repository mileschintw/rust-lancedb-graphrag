# Deferred Items

## Pre-existing production stubs found during the 02-07 audit

- `engine/src/main.rs:329-330`: `query_rag` still returns a placeholder answer and empty citations. This predates 02-07 and belongs to the Phase 03 RAG implementation; it does not affect replacement rollback, retry convergence, or failed-ingest compensation.
- `engine/src/main.rs:340`: `query_graph` still returns a scaffolding status payload. This predates 02-07 and belongs to the Phase 04 graph-query implementation; it does not affect replacement rollback, retry convergence, or failed-ingest compensation.
