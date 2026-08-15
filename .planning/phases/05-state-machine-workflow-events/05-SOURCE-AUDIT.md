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
baseline and additive plan set. The revised graph/retrieval plan pins bounded cross-variant score
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

05-06 declares all seven timeout keys in the exact `[engine.workflow]`
configuration contract across all three overlays and tests
the exact-set/annotation/inequality rules. 05-05 makes checkpoint `id` the UUID
primary key. The review suggestion for automatic checkpoint cleanup is
explicitly rejected under D-24/D-25: indefinite retention and direct database
inspection remain the locked contract, with the local-demo storage tradeoff
accepted and no cleanup job added.

## Targeted continuation revision

The 05-02 admission correction is now assigned to the runner immediately after
`ReformulateQuery`: `variants.len() <= 8` is checked before
`ExtractGraphContext`, embedding, graph, dense/BM25 retrieval, RRF, reranking,
or provenance allocation, and the exact nine-variant test drives the full
runner while asserting zero downstream calls. All seven workflow timer keys
are now assigned consistently to `[engine.workflow]` across the three config
overlays, allowlist, annotations, exact-set checks, and validation matrix;
`openrouter.generation_timeout_secs` remains the separate per-attempt provider
timeout.

## Revision iteration 4 checker closure

The additive checker revision adds 05-13 as the Wave 9 owner of OpenRouter
capability preflight, successful-only caching, typed transient transport
classification, and the D-11/D-12 generation retry contract. 05-09 now owns
`config/config.verify.toml` and sets the provider-attempt budget to 30 seconds
while retaining the 7000ms live generation-node timeout proof. 05-14 is the
Wave 10 owner of exhaustive `NodeKind` dispatch; 05-15 owns prompt API and
fake-port boundaries; 05-16 owns graph notice/provenance/BM25 invariants; and
05-10 is the later Wave 12 owner of event delivery, terminal idempotence,
sequence integrity, and full snapshots. None of these plans owns OpenRouter
preflight or generation-attempt policy outside 05-13. 05-11 is Wave 13 and
depends explicitly on the corrected event, graph/retrieval, and retry
contracts. The 05-12 errata and validation mappings include 05-13 through
05-16, so GOAL, ORCH-01 through ORCH-05, RESEARCH, and D-01 through D-31 remain
traceable without changing executed artifacts.

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

## Revision continuation coverage (checker blockers and warnings)

This additive matrix supersedes the earlier six-plan description without
changing any executed artifact. Every item from the current independent
checker has an executable owner:

| Checker item | Root cause | Executable owner | Closure artifact / proof |
|---|---|---|---|
| Historical verification command sanity | Frozen executed plans predate the additive exact Cargo registration rule | 05-12 | Literal fourteen-path HEAD blob table, staged/unstaged path assertions, and `git diff --check` in the errata guard |
| Production adapter proof | 05-08 previously proved registration but not real service-field dependency construction | 05-08 source/body checks; 05-20 after 05-18 | `workflow_phase5_production_dependencies_are_real` body and builder source assertions in 05-08, followed by the exact registered binary filter after 05-18 owns `engine/src/tests.rs` registration |
| Task ownership | Tests and monolith retirement were described outside exact task file ownership | 05-08, 05-09, 05-18, 05-20 | Exact test-file and `workflow/mod.rs` ownership in task `<files>`, source/body and compile checks before the target split, and the deferred exact binary registration/run set in 05-20 |
| OpenRouter cross-plan contract | Preflight and GenerationRequest were incorrectly asserted as one byte contract | 05-13 | Separate preflight method/deadline/cache proof; only serialized GenerationRequest attempt 1/2 equality |
| Post-open SSE failure | Gateway silently ended after Recv error or EOF without a terminal frame | 05-11 | Raw `stream_error` SSE tests for `GRPC_RECV_ERROR` and `STREAM_EOF_WITHOUT_TERMINAL` after HTTP 200 |
| WR-10 / WR-11 | Public sync prompt wrappers and incomplete async docs were not executablely gated | 05-15 | Prompt API source/tests, graph_weight semantics, complete error docs, and cfg(test) sync helper boundary |
| Fake ports in production | Fake workflow ports had no compilation boundary | 05-15 | Six fake declarations cfg(test)-gated and source assertion |
| WR-06 / WR-07 | Graph code and notice replacement used untyped/overwriting outcomes | 05-16, 05-10 | Exact GRAPH_TIMEOUT/GRAPH_DEGRADED codes, ordered notice merge, and later terminal preservation tests |
| WR-09 | Multi-variant BM25 weighting was not auditable | 05-16 | Explicit RetrievalSnapshot.variant_count and variant_identities with focused test |
| WR-13 | Terminal helper allowed duplicate terminal emission | 05-10 | Atomic/idempotent guard and duplicate-terminal exact-one test |
| WR-14 | BM25 RwLock guard could survive an await | 05-16 | Owned immutable index snapshot, source guard, and stalled-retrieval/concurrent-ingestion regression |
| Scope sanity | 05-10 mixed typed NodeKind, event delivery, and snapshot concerns across eleven files | 05-14, 05-10 | 05-14 owns typed node dispatch; 05-10 now owns only runner/event/snapshot files and precise task ownership |

### Continuation source coverage

| Source | Items | Plans |
|---|---|---|
| GOAL | Production five-node state machine with predictable failure handling | 05-08, 05-09, 05-13, 05-14, 05-15, 05-16, 05-10, 05-11 |
| REQ | ORCH-01 | 05-08, 05-14, 05-16 |
| REQ | ORCH-02 | 05-08, 05-09, 05-10, 05-11, 05-13, 05-14, 05-15 |
| REQ | ORCH-03 | 05-08, 05-09, 05-10, 05-11, 05-13, 05-14, 05-15, 05-16 |
| REQ | ORCH-04 | 05-08, 05-10, 05-11, 05-12, 05-16 |
| REQ | ORCH-05 | 05-08, 05-12 |
| RESEARCH | Real adapter responsibility belongs to Rust; Go relays SSE and owns Postgres; 30s provider attempt is distinct from node budget; graph timeout degrades; fakes and deterministic fault seams are required | 05-08, 05-09, 05-11, 05-13, 05-15, 05-16 |
| CONTEXT | D-01..D-05 answer/event/prestream contracts | 05-08, 05-10, 05-11, 05-13, 05-14 |
| CONTEXT | D-06..D-10 graph/retrieval ordering and degradation | 05-08, 05-14, 05-16 |
| CONTEXT | D-11..D-17 retry, timeout, cancellation, and provider arithmetic | 05-09, 05-10, 05-13, 05-14 |
| CONTEXT | D-18..D-22 stream/SSE/event categories | 05-08, 05-10, 05-11, 05-14 |
| CONTEXT | D-23..D-29 checkpoint ownership, snapshot fidelity, identity | 05-10, 05-11, 05-12 |
| CONTEXT | D-30..D-31 metadata/tracing scope fences | 05-08, 05-10, 05-14, 05-16 |

The deferred ideas in `05-CONTEXT.md` remain excluded: no backup provider,
resume/fetch API, cancel RPC, workflow metadata, per-node spans, or degraded
mode field is introduced by these continuation plans.

## Revision continuation iteration 5

This additive iteration closes all four current checker blockers and four warnings without changing 05-01 through 05-07 artifacts. Each new source item has a task owner and a pending validation row in 05-VALIDATION.md.

| Checker item | Executable owner | Closure proof |
|---|---|---|
| cross_plan_data_contracts | 05-17 | Proto ownership, Buf generation, four checked-in generated bindings, every Rust/Go RetrievalSnapshot literal, field/tag assertions, and wire round-trip tests. |
| task_completeness target-aware fake seam | 05-18 then 05-15 | Library-only Phase 5 registration, target-correct imports, six-fake compile probe, binary compile guard, then cfg(test) gating. |
| WR-07 failure terminal notices | 05-19 | Typed WorkflowCompletedEvent.notices, Rust failure ordering/no-answer assertions, and raw Go SSE notice assertions. |
| verification_derivation timing | 05-20 | Generator/Node preparation hook before the node timer, paused-clock 5000 + 2 x 30000 proof, 4999ms boundary test, and bounded happy-path drain. |
| AGENTS.md Rust guidance | 05-10, 05-14, 05-15, 05-16, 05-17, 05-18, 05-19, 05-20, 05-21 | Every Rust-modifying task read_first names rust-guidelines.md; Go-modifying tasks name go-guidelines.md. |
| IN-02/IN-03 fusion cleanup | 05-21 | Typed provenance enum, enum filters, dead serde-default removal, serialization regression, and source guards. |
| IN-05 timing/liveness assertions | 05-20 | Exact 4999ms no-timeout registration and five-second workflow_phase5_happy_path receiver drain. |
| numeric factual authority | 05-12 | 05-RESEARCH.md contains the machine-checkable current validation authority marker and current named filters. |

### Iteration 5 multi-source coverage

| Source | Items | Plans |
|---|---|---|
| GOAL | Formalized Rust RAG state machine with predictable failures, streamed events, retries, snapshots, and ORCH-05 pass-through | 05-08, 05-09, 05-10, 05-11, 05-13, 05-14, 05-15, 05-16, 05-17, 05-18, 05-19, 05-20, 05-21 |
| REQ | ORCH-01 | 05-08, 05-14, 05-16, 05-17, 05-18, 05-20 |
| REQ | ORCH-02 | 05-08, 05-09, 05-10, 05-11, 05-13, 05-14, 05-15, 05-17, 05-18, 05-19, 05-20 |
| REQ | ORCH-03 | 05-08, 05-09, 05-10, 05-11, 05-13, 05-14, 05-15, 05-16, 05-18, 05-19, 05-20, 05-21 |
| REQ | ORCH-04 | 05-08, 05-10, 05-11, 05-12, 05-16, 05-17, 05-19, 05-21 |
| REQ | ORCH-05 | 05-08, 05-12 |
| RESEARCH | Buf is the protobuf source of truth; Rust owns orchestration; Go relays SSE; provider attempt and node budgets are distinct; fakes need an explicit test boundary; fusion provenance is typed | 05-08, 05-09, 05-11, 05-13, 05-15, 05-17, 05-18, 05-19, 05-20, 05-21 |
| CONTEXT | D-05 in-band typed failure and no fabricated answer | 05-17, 05-19, 05-20 |
| CONTEXT | D-07/D-08 variant fusion, ordered identities, and variant-zero embedding | 05-16, 05-17, 05-21 |
| CONTEXT | D-11/D-17 bounded retry, 30-second attempts, 5-second preflight, 65-second node timer | 05-09, 05-13, 05-20 |
| CONTEXT | D-18/D-19 streaming and SSE terminal mapping | 05-11, 05-17, 05-19 |
| CONTEXT | D-30 no generic workflow metadata | 05-08, 05-10, 05-16, 05-17, 05-19, 05-20, 05-21 |

No deferred idea is implemented: no backup provider, resume/fetch API, cancel RPC, generic workflow metadata, per-node spans, or degraded-mode field is added.

## Revision continuation iteration 6

This revision preserves the executed 05-01 through 05-07 baseline and keeps the current validation authority aligned with the executable plan graph. The production handoff and generated-binding boundary are split so each pending plan stays within its file-ownership target; the binary test-target no-run gate is ordered explicitly across 05-18, 05-15, 05-16, and 05-20.

| Checker item | Executable owner | Closure proof |
|---|---|---|
| 05-15 binary target gate | 05-15 Task 2 | After cfg(test) gating, run `cargo test --bin engine --manifest-path engine/Cargo.toml --locked --no-run` with immediate native `$LASTEXITCODE` handling. |
| Superseded validation exception | 05-12 Task 1 and 05-VALIDATION.md | 05-23 wire/compile repair -> 05-18 first complete binary no-run -> 05-15 cfg(test) rerun -> 05-16 BM25 rerun -> 05-20 rerun before binary list/exact; no accepted Waves 7–13 compile-break exception. |
| 05-08 scope ownership | 05-08 then 05-22 | 05-08 owns the seven-file production builder/context boundary; 05-22 owns prompt/generation provider reachability and exact production assertions. |
| 05-17 scope ownership | 05-17 then 05-23 | 05-17 owns schema, Buf configuration, and six generated bindings; 05-23 owns Rust literal compile repair and the Rust wire-contract regression. |

### Iteration 6 multi-source coverage

| Source | Items | Plans |
|---|---|---|
| GOAL | Formalized Rust RAG state machine with predictable failures, streamed events, retries, snapshots, and ORCH-05 pass-through | 05-08, 05-09, 05-10, 05-11, 05-12, 05-13, 05-14, 05-15, 05-16, 05-17, 05-18, 05-19, 05-20, 05-21, 05-22, 05-23 |
| REQ | ORCH-01 | 05-08, 05-14, 05-16, 05-17, 05-18, 05-20, 05-22, 05-23 |
| REQ | ORCH-02 | 05-08, 05-09, 05-10, 05-11, 05-13, 05-14, 05-15, 05-17, 05-18, 05-19, 05-20, 05-22, 05-23 |
| REQ | ORCH-03 | 05-08, 05-09, 05-10, 05-11, 05-13, 05-14, 05-15, 05-16, 05-18, 05-19, 05-20, 05-21, 05-22, 05-23 |
| REQ | ORCH-04 | 05-08, 05-10, 05-11, 05-12, 05-16, 05-17, 05-19, 05-21, 05-23 |
| REQ | ORCH-05 | 05-08, 05-12, 05-22 |
| RESEARCH | Buf source-of-truth generation, Rust-owned orchestration, typed graph-fact handoff, explicit fake-port boundary, binary test-target verification, and typed fusion provenance | 05-08, 05-12, 05-15, 05-16, 05-17, 05-18, 05-21, 05-22, 05-23 |
| CONTEXT | D-01/D-02 answer cardinality, D-03 zero-evidence completion, D-05 typed failure, D-06 ordering, D-07/D-08 provenance, D-09 graph degradation, D-30/D-31 metadata/tracing fences | 05-08, 05-14, 05-16, 05-17, 05-19, 05-20, 05-21, 05-22, 05-23 |

No deferred idea is implemented by this revision. The new plans add no provider, RPC, metadata, tracing, or persistence scope beyond the locked D-01 through D-31 contract.

## Revision continuation iteration 7

This revision preserves the executed 05-01 through 05-07 baseline, including the immutable 05-02 plan and summary, and preserves the reviewed scope of 05-21. The current checker blocker is closed additively by 05-24: the pending plan now owns the executable two-pass cross-variant fusion contract that 05-RESEARCH.md marks resolved but that the frozen 05-02 task text does not specify precisely enough.

| Checker item | Executable owner | Closure proof |
|---|---|---|
| Resolved cross-variant RRF algorithm | 05-24 Task 1 | RetrieveHybrid calls fuse_candidates once per admitted ordered variant, then calls fuse_cross_variant_candidates over the per-variant fused outputs; the helper documents the exact one-based-rank formula, finite-score handling, one-variant identity, metadata selection, and tie/order rules. |
| Exact two-variant assertion | 05-24 Task 1 | cross_variant_rrf_two_variant_exact_scores asserts numerical scores from two per-variant outputs and verifies retained vector/BM25 VariantProvenance. |
| Call-site and tie-order guard | 05-24 Task 2 | A RetrieveHybrid-region source guard checks the per-variant call count, later second-pass call, variant-zero dense branch, and absence of request flattening; a focused regression proves deterministic tie order. |
| Downstream integration ordering | 05-11 frontmatter | The final engine-to-gateway SSE/checkpoint plan now depends explicitly on 05-24, so cross-runtime evidence cannot precede the resolved retrieval contract. |

### Iteration 7 multi-source coverage

| Source | Items | Plans |
|---|---|---|
| GOAL | Formalized Rust RAG state machine with predictable failures, streamed events, retries, snapshots, and ORCH-05 pass-through | 05-08, 05-09, 05-10, 05-11, 05-12, 05-13, 05-14, 05-15, 05-16, 05-17, 05-18, 05-19, 05-20, 05-21, 05-22, 05-23, 05-24 |
| REQ | ORCH-01 | 05-08, 05-14, 05-16, 05-17, 05-18, 05-20, 05-22, 05-23, 05-24 |
| REQ | ORCH-02 | 05-08, 05-09, 05-10, 05-11, 05-13, 05-14, 05-15, 05-17, 05-18, 05-19, 05-20, 05-22, 05-23 |
| REQ | ORCH-03 | 05-08, 05-09, 05-10, 05-11, 05-13, 05-14, 05-15, 05-16, 05-18, 05-19, 05-20, 05-21, 05-22, 05-23, 05-24 |
| REQ | ORCH-04 | 05-08, 05-10, 05-11, 05-12, 05-16, 05-17, 05-19, 05-21, 05-23 |
| REQ | ORCH-05 | 05-08, 05-12, 05-22, 05-24 |
| RESEARCH | Resolved Pitfall 5/Open Question 2: one fuse_candidates call per variant, a second cross-variant RRF merge over per-variant fused outputs, documented one-based-rank scoring, deterministic tie/order behavior, and exact two-variant scores | 05-24 |
| RESEARCH | Buf source-of-truth generation, Rust-owned orchestration, typed graph-fact handoff, explicit fake-port boundary, binary test-target verification, and typed fusion provenance | 05-08, 05-12, 05-15, 05-16, 05-17, 05-18, 05-21, 05-22, 05-23 |
| CONTEXT | D-01/D-02 answer cardinality, D-03 zero-evidence completion, D-05 typed failure, D-06 ordering, D-07/D-08 two-pass variant fusion and variant-zero embedding, D-09 graph degradation, D-30/D-31 metadata/tracing fences | 05-08, 05-14, 05-16, 05-17, 05-19, 05-20, 05-21, 05-22, 05-23, 05-24 |

No deferred idea is implemented by this revision. Plan 05-24 adds no provider, RPC, metadata, tracing, persistence, or real reformulation strategy scope, and it does not alter the executed 05-02 artifact.
