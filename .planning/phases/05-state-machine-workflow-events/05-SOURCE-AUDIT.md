# Phase 05 Multi-Source Plan Audit

Every in-scope item from the goal, requirements, research, and locked context is
assigned to an executable plan. Deferred and descoped items from
`05-CONTEXT.md` are excluded by source authority.

## Coverage Matrix

| Source | ID | Item | Plan | Status |
|---|---|---|---|---|
| GOAL | — | Rust state machine makes RAG orchestration predictable to debug and extend | 05-01, 05-02, 05-03, 05-06 | COVERED |
| REQ | ORCH-01 | Fixed Rust state machine for query → reformulate → retrieve → graph → prompt → answer → complete/failed | 05-01, 05-02, 05-03, 05-04 | COVERED |
| REQ | ORCH-02 | Client-facing started/completed/failed/chunk/final/completed events | 05-01, 05-03, 05-05, 05-06 | COVERED |
| REQ | ORCH-03 | Cancellation, timeouts, and generation-only retry behavior | 05-01, 05-03, 05-04, 05-06 | COVERED |
| REQ | ORCH-04 | Durable workflow checkpoints/snapshots | 05-03, 05-05 | COVERED |
| REQ | ORCH-05 | Pass-through `QueryReformulator` port | 05-01, 05-02 | COVERED |
| RESEARCH | R-01 | Hand-rolled Rust `Node`/`WorkflowRunner` using native Tokio | 05-01 | COVERED |
| RESEARCH | R-02 | Server-streaming protobuf contract and one-point Rust-to-protobuf conversion | 05-01, 05-06 | COVERED |
| RESEARCH | R-03 | Go first-frame SSE prefetch and exclusion from the global 60-second timeout | 05-06 | COVERED |
| RESEARCH | R-04 | Sub-second workflow timeout overrides and retry-vs-provider timeout arithmetic | 05-03, 05-06 | COVERED |
| RESEARCH | R-05 | Injectable graph, dense, and BM25 ports with production wrappers and fakes | 05-02, 05-04 | COVERED |
| RESEARCH | R-06 | Graph timeout/logical failure degrades without making the query fail | 05-02, 05-04 | COVERED |
| RESEARCH | R-07 | Cooperative prompt assembly cancellation rather than a non-preemptive blocking timeout | 05-03, 05-04 | COVERED |
| RESEARCH | R-08 | Exact one-retry classification, cancellation rendezvous, citation-resolution policy | 05-03, 05-04 | COVERED |
| RESEARCH | R-09 | Full-snapshot checkpoint DTO, bounded size ladder, explicit fallback shape | 05-03, 05-05 | COVERED |
| RESEARCH | R-10 | Atlas HCL, sqlc SQL source, generated model/query, and schema push | 05-05 | COVERED |
| RESEARCH | R-11 | Go detached checkpoint persistence, per-test schema isolation, canonical `TEST_DATABASE_URL` | 05-05 | COVERED |
| RESEARCH | R-12 | Tier 1 deterministic tests, Tier 2 real Go→Rust→PostgreSQL tests, full suites | 05-01, 05-02, 05-03, 05-04, 05-05, 05-06 | COVERED |
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
| CONTEXT | D-17 | Default configurable per-attempt/node timeout values, including the distinct 65000ms generation node budget | 05-03, 05-04, 05-06 | COVERED |
| CONTEXT | D-18 | Unary-to-server-streaming `QueryRAG` | 05-01, 05-06 | COVERED |
| CONTEXT | D-19 | SSE-only `/rag/query` | 05-06 | COVERED |
| CONTEXT | D-20 | Coarse node event granularity | 05-01, 05-04 | COVERED |
| CONTEXT | D-21 | No SSE resume/reconnect support | 05-01 | COVERED |
| CONTEXT | D-22 | Typed node failure categories plus safe messages | 05-01, 05-03, 05-04 | COVERED |
| CONTEXT | D-23 | PostgreSQL durable/queryable checkpoints with accepted local-only raw-content risk | 05-05 | COVERED |
| CONTEXT | D-24 | Indefinite checkpoint retention and no cleanup job | 05-05 | COVERED |
| CONTEXT | D-25 | No checkpoint fetch API/RPC | 05-05 | COVERED |
| CONTEXT | D-26 | Go owns PostgreSQL; Rust sends checkpoint events only | 05-05 | COVERED |
| CONTEXT | D-27 | Detached bounded checkpoint writes do not stall queries | 05-01, 05-03, 05-04, 05-05, 05-06 | COVERED |
| CONTEXT | D-28 | Full accumulated checkpoint snapshots | 05-03, 05-05 | COVERED |
| CONTEXT | D-29 | `trace_id` equals request `correlation_id`, distinct from `session_id` | 05-01, 05-05 | COVERED |
| CONTEXT | D-30 | No new workflow metadata or degraded-mode field | 05-02, 05-03, 05-05 | COVERED |
| CONTEXT | D-31 | No new per-node tracing spans; preserve existing query span | 05-01, 05-03 | COVERED |

## Review Disposition

All current actionable findings in `05-REVIEWS.md` are incorporated into the
six plans. The revised graph/retrieval plan pins bounded cross-variant score
and provenance semantics; the generation and gateway plans pin 65000ms versus
30000ms timeout arithmetic, route isolation, live SSE testing, generated-code
landing order, and no-backoff retry behavior; the checkpoint plans pin
sequence-ordinal ordering, generated model coverage, reliable pending/drain
ownership, and isolated-schema cleanup. The only intentionally rejected
addition is a durable graph failure-vs-no-match metadata field: D-30 defers
workflow metadata and the AI-SPEC defines the empty `graph_context` checkpoint
diff as the Phase 5 degradation signal. Plans retain the bounded graph outcome
internally for sanitized diagnostics without adding a new checkpoint metadata
contract.

## Revision iteration 1 checker closure

The checker-blocking corrections remain assigned to executable owners: every Go
verification command runs with `go -C gateway` and captures `$LASTEXITCODE`
immediately; the sixth-envelope dispatcher handoff is a direct Go unit test in
05-06 rather than a Rust-owned claim; prompt packing has bounded cancellation
checkpoints and `yield_now` granularity; both inline bridges specify their
field-level context mutation, partial-node event/checkpoint ownership, failure
return, and sole terminal emitter; 05-01 guards Rust-only code generation with
before/after hashes of existing Go outputs; and 05-02's runner path is
`engine/src/workflow/runner.rs`. The validation artifact is a populated,
pre-execution matrix with exact task commands and an explicit draft/false
Nyquist status, while the large 05-01/05-02/05-06 inventories carry
execution-visible atomicity rationales and the one-way tasks have preceding
locked-decision checkpoints. Focused registration guards now use immediate
command-failure checks and exact escaped test names rather than broad
alternation/count lower bounds.

## Revision iteration 2 checker closure

The second bounded checker pass is closed in the task actions and must-have
links, not only in plan-level prose. The Rust event/terminal contract, Go DTO,
and SSE frame map evidence-bearing `answer`, `citations`, `session_id`,
`answer_basis`, `structured_citations`, `notices`, and `snapshot` field by
field, with `snapshot` kept distinct from notices and durable checkpoint
`context_snapshot`; notices may be empty, and D-03 zero-evidence success
remains valid. Graph timeout has one shared semantic owner: a 4000ms inner
graph-operation deadline follows a 10000ms embedding prelude and fits before
the 15000ms runner backstop, while the backstop routes to the same successful
branch; tests assert one notice, successful completion, and no `NodeFailed`.
The eight-variant memory bound is fail-closed with typed rejection before
retrieval for an exact nine-variant input, so D-07's all-`Vec` RRF contract
cannot be silently truncated. The implementing task actions also cite the
previously under-traced locked decisions D-05, D-09, D-10, D-11, D-13, D-14,
D-15, D-17, D-20, D-21, D-24, D-25, D-26, D-30, and D-31, including explicit
absence assertions for the negative/deferred choices.

## Revision iteration 3 review closure

The review-driven revision keeps the six-plan/five-wave graph and makes each
new ownership boundary executable. 05-01 now owns migration of all 29 existing
Rust `.query_rag(` call sites in `engine/src/tests.rs` before the focused test
listing, and 05-06 owns every Go caller in the coordinated generated-API
landing; their shared protobuf/call-site transition remains effectively
atomic. The Rust-only `buf clean:true` concern is documented as a confirmed
non-issue once Go is absent from the configured output list, with the existing
before/after hash guard retained.

Query embedding is owned by the 05-01 `QueryEmbeddingPort`/`WorkflowContext`
seam and invoked by 05-02's graph-context prelude: the 10000ms embedding budget
plus 4000ms graph-operation budget fits strictly inside the 15000ms graph-node
backstop; embedding transport/invalid-vector failures are `RetrievalFailed`,
embedding timeout is `Timeout`, and `RetrieveHybrid` reuses the context vector
without embedding again. 05-03 explicitly owns the production
`engine/src/generation/openrouter.rs` call site, makes retry identity a complete
`GenerationRequest` equality assertion, and labels `assembled_prompt` as a
node-output checkpoint field rather than the adapter's wire repack.

05-06 declares all seven timeout keys in the exact `[engine.workflow]` and
`[engine.graph]` configuration contract across all three overlays and tests
the exact-set/annotation/inequality rules. 05-05 makes checkpoint `id` the UUID
primary key. The review suggestion for automatic checkpoint cleanup is
explicitly rejected under D-24/D-25: indefinite retention and direct database
inspection remain the locked contract, with the local-demo storage tradeoff
accepted and no cleanup job added.

## Spec-less fallback dispositions

The supplied edge probe found six unresolved items and no regular SPEC Edge
Coverage or Prohibitions sections. The plans surface them as flagged executable
assumptions: ORCH-01 unclassified state transitions (05-01/05-02), ORCH-02
unclassified event/transport behavior (05-01/05-04/05-06), ORCH-03 idempotency
(05-01/05-03/05-04) and concurrency (05-01/05-02/05-04/05-05/05-06), ORCH-04
unclassified checkpoint behavior (05-05), and ORCH-05 unclassified
pass-through behavior (05-02). Each plan's prohibition entries are explicitly
flagged `unverified` under the descriptor-less prohibition fallback; no wired
prohibition descriptor is claimed.
