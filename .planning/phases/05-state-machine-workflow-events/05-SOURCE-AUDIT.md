# Phase 05 Multi-Source Plan Audit

Every in-scope item from the goal, requirements, research, and locked context is
assigned to an executable plan. Deferred and descoped items from
`05-CONTEXT.md` are excluded by source authority.

## Coverage Matrix

| Source | ID | Item | Plan | Status |
|---|---|---|---|---|
| GOAL | — | Rust state machine makes RAG orchestration predictable to debug and extend | 05-01, 05-02, 05-03 | COVERED |
| REQ | ORCH-01 | Fixed Rust state machine for query → reformulate → retrieve → graph → prompt → answer → complete/failed | 05-01, 05-02, 05-03, 05-04 | COVERED |
| REQ | ORCH-02 | Client-facing started/completed/failed/chunk/final/completed events | 05-01, 05-03, 05-05 | COVERED |
| REQ | ORCH-03 | Cancellation, timeouts, and generation-only retry behavior | 05-01, 05-03, 05-04 | COVERED |
| REQ | ORCH-04 | Durable workflow checkpoints/snapshots | 05-03, 05-05 | COVERED |
| REQ | ORCH-05 | Pass-through `QueryReformulator` port | 05-01, 05-02 | COVERED |
| RESEARCH | R-01 | Hand-rolled Rust `Node`/`WorkflowRunner` using native Tokio | 05-01 | COVERED |
| RESEARCH | R-02 | Server-streaming protobuf contract and one-point Rust-to-protobuf conversion | 05-01 | COVERED |
| RESEARCH | R-03 | Go first-frame SSE prefetch and exclusion from the global 60-second timeout | 05-01 | COVERED |
| RESEARCH | R-04 | Sub-second workflow timeout overrides and retry-vs-provider timeout arithmetic | 05-01, 05-03 | COVERED |
| RESEARCH | R-05 | Injectable graph, dense, and BM25 ports with production wrappers and fakes | 05-02, 05-04 | COVERED |
| RESEARCH | R-06 | Graph timeout/logical failure degrades without making the query fail | 05-02, 05-04 | COVERED |
| RESEARCH | R-07 | Cooperative prompt assembly cancellation rather than a non-preemptive blocking timeout | 05-03, 05-04 | COVERED |
| RESEARCH | R-08 | Exact one-retry classification, cancellation rendezvous, citation-resolution policy | 05-03, 05-04 | COVERED |
| RESEARCH | R-09 | Full-snapshot checkpoint DTO, bounded size ladder, explicit fallback shape | 05-03, 05-05 | COVERED |
| RESEARCH | R-10 | Atlas HCL, sqlc SQL source, generated model/query, and schema push | 05-05 | COVERED |
| RESEARCH | R-11 | Go detached checkpoint persistence, per-test schema isolation, canonical `TEST_DATABASE_URL` | 05-05 | COVERED |
| RESEARCH | R-12 | Tier 1 deterministic tests, Tier 2 real Go→Rust→PostgreSQL tests, full suites | 05-04, 05-05 | COVERED |
| RESEARCH | R-13 | Package legitimacy-approved `tokio-util` and `tokio-stream` additions | 05-01 | COVERED |
| RESEARCH | R-14 | ASVS L1 treatment of SSE, event, provider, and checkpoint boundaries | 05-01, 05-02, 05-03, 05-05 | COVERED |
| CONTEXT | D-01 | Progress events, one complete validated `AnswerChunk`, unchanged structured generation | 05-03 | COVERED |
| CONTEXT | D-02 | Distinct `AnswerChunk` and `FinalAnswer` event types | 05-01, 05-03 | COVERED |
| CONTEXT | D-03 | Zero-evidence success short-circuits to `Complete` | 05-02, 05-03, 05-04 | COVERED |
| CONTEXT | D-04 | Synchronous pre-stream validation and ID minting | 05-01 | COVERED |
| CONTEXT | D-05 | In-band post-stream failures and normal SSE close | 05-01, 05-04 | COVERED |
| CONTEXT | D-06 | Graph augmentation precedes hybrid retrieval | 05-02 | COVERED |
| CONTEXT | D-07 | Cross-variant RRF merge | 05-02 | COVERED |
| CONTEXT | D-08 | Embed only reformulation variant zero | 05-01, 05-02 | COVERED |
| CONTEXT | D-09 | Graph node always runs but success is not required | 05-02, 05-04 | COVERED |
| CONTEXT | D-10 | Standalone `QueryGraph` RPC remains untouched | 05-02 | COVERED |
| CONTEXT | D-11 | Retry only generation | 05-03 | COVERED |
| CONTEXT | D-12 | One no-backoff byte-identical generation retry | 05-03, 05-04 | COVERED |
| CONTEXT | D-13 | Honest failure after two generation failures, no fabricated answer | 05-03, 05-04 | COVERED |
| CONTEXT | D-14 | No backup provider/model | 05-03 | COVERED |
| CONTEXT | D-15 | No retrying event | 05-01, 05-03 | COVERED |
| CONTEXT | D-16 | Native SSE disconnect cancellation and no cancel RPC | 05-01, 05-04, 05-05 | COVERED |
| CONTEXT | D-17 | Default configurable per-attempt/node timeout values | 05-01, 05-03, 05-04 | COVERED |
| CONTEXT | D-18 | Unary-to-server-streaming `QueryRAG` | 05-01 | COVERED |
| CONTEXT | D-19 | SSE-only `/rag/query` | 05-01 | COVERED |
| CONTEXT | D-20 | Coarse node event granularity | 05-01, 05-04 | COVERED |
| CONTEXT | D-21 | No SSE resume/reconnect support | 05-01 | COVERED |
| CONTEXT | D-22 | Typed node failure categories plus safe messages | 05-01, 05-03, 05-04 | COVERED |
| CONTEXT | D-23 | PostgreSQL durable/queryable checkpoints with accepted local-only raw-content risk | 05-05 | COVERED |
| CONTEXT | D-24 | Indefinite checkpoint retention and no cleanup job | 05-05 | COVERED |
| CONTEXT | D-25 | No checkpoint fetch API/RPC | 05-05 | COVERED |
| CONTEXT | D-26 | Go owns PostgreSQL; Rust sends checkpoint events only | 05-05 | COVERED |
| CONTEXT | D-27 | Detached bounded checkpoint writes do not stall queries | 05-05 | COVERED |
| CONTEXT | D-28 | Full accumulated checkpoint snapshots | 05-03, 05-05 | COVERED |
| CONTEXT | D-29 | `trace_id` equals request `correlation_id`, distinct from `session_id` | 05-01, 05-05 | COVERED |
| CONTEXT | D-30 | No new workflow metadata or degraded-mode field | 05-02, 05-03, 05-05 | COVERED |
| CONTEXT | D-31 | No new per-node tracing spans; preserve existing query span | 05-01, 05-03 | COVERED |

## Review Disposition

All current actionable findings in `05-REVIEWS.md` are incorporated into the
five plans. The only intentionally rejected addition is a durable graph
failure-vs-no-match metadata field: D-30 defers workflow metadata and the
AI-SPEC defines the empty `graph_context` checkpoint diff as the Phase 5
degradation signal. Plans retain the bounded graph outcome internally for
sanitized diagnostics without adding a new checkpoint metadata contract.
