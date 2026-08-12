---
phase: 5
reviewers: [antigravity, claude]
successful_reviewers: [antigravity, claude]
reviewed_at: 2026-08-12T18:15:52Z
plans_reviewed:
  - 05-01-PLAN.md
  - 05-02-PLAN.md
  - 05-03-PLAN.md
  - 05-04-PLAN.md
  - 05-05-PLAN.md
  - 05-06-PLAN.md
reviewer_models:
  antigravity: gemini-3.5-flash
  claude: opus
reviewer_effort: high
---

# Cross-AI Plan Review — Phase 5

## Antigravity Review (gemini-3.5-flash, high)

# Phase 5 Implementation Plan Review: State Machine & Workflow Events

This document provides a structured review of the proposed execution plans ([05-01-PLAN.md](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md), [05-06-PLAN.md](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-06-PLAN.md), [05-02-PLAN.md](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-02-PLAN.md), [05-03-PLAN.md](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md), [05-04-PLAN.md](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-04-PLAN.md), and [05-05-PLAN.md](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md)) designed to formalize Lancet's RAG orchestration into a Rust state machine with Go SSE streaming and PostgreSQL checkpoint persistence.

---

## 1. Summary
The proposed implementation plans present a highly complete, secure, and structurally sound approach to formalizing Lancet's linear RAG pipeline into a typed Rust state machine. The plans leverage a clever wave-based transition system—using a temporary Rust-only Buf compilation configuration (`buf.gen.yaml` with `clean: false`) in Wave 1 and restoring full Go/Rust coordination in Wave 2—to prevent intermediate build failures during the unary-to-streaming API migration. The architecture enforces clean separation of concerns, keeping `ReceiveQuery` validation synchronous before stream creation, and isolates storage operations via injectable ports (`GraphQueryPort`, `DenseRetrievalPort`, `Bm25RetrievalPort`) to allow for a deterministic Tier 1 test matrix. The design is optimized for resilience, addressing key asynchronous pitfalls through cooperative prompt-packing yield loops, a deterministic size-ladder truncation strategy for Postgres-backed checkpoints, and a non-blocking background queue for database writes.

---

## 2. Strengths
* **Safe gRPC/Protobuf Transition Path:** The use of `clean: false` and temporary Rust-only plugins in [buf.gen.yaml](file:///D:/Repos/lancet/buf.gen.yaml) in `05-01` ensures the Go gateway continues to compile using the old unary client during Rust refactoring, avoiding build breaks.
* **Synchronous Input Validation (D-04):** Keeping input validation and correlation/session ID minting synchronous before stream creation prevents allocation of stream resources for malformed requests.
* **Cooperative Prompt Packing:** Defining `PROMPT_YIELD_GRANULARITY` to yield execution control (`tokio::task::yield_now()`) after processing individual evidence blocks prevents heavy prompt tokenize/scoring loops from blocking tokio executor threads.
* **Deterministic Checkpoint Truncation (D-28):** The plan implements a strict size-limiting ladder (262,144-byte cap) that degrades fields progressively (assembled prompt -> evidence text -> candidate contents -> minimal fallback marker) to protect Postgres writes without stalling or failing RAG queries.
* **Non-Blocking Persistence (D-26/D-27):** Checkpoint snapshots are persisted in Go via a background worker using a bounded dispatcher (`checkpointPrimaryCapacity = 1`, `checkpointOverflowCapacity = 5`), ensuring database slowness never backpressures the response stream.
* **Injectable Port Boundaries:** The introduction of explicit traits mockable in unit/integration tests solves the lack of mockability for LanceDB and BM25 index lookups.
* **Integration Test Concurrency Safety:** The Postgres tests adhere strictly to the `AGENTS.md` review convention, utilizing isolated per-test schemas, dynamically binding `search_path`, and using `t.Fatalf` to fail immediately on query errors.

---

## 3. Concerns
* **Global Middleware Timeout Conflict (Severity: HIGH):**
  * *Context:* [gateway/main.go:464](file:///D:/Repos/lancet/gateway/main.go#L464) applies a global `middleware.Timeout(60*time.Second)` to all routes.
  * *Risk:* The sequential worst-case timeout for the state machine is `5s (Reformulate) + 10s (Retrieve) + 15s (Graph) + 2s (Prompt) + 65s (Generate with 1 retry) = 97s`. The Go gateway middleware will terminate the HTTP request at exactly 60 seconds, canceling the gRPC context and aborting the Rust engine before a slow-but-valid query with retries can succeed. While the plans state the route is outside the timeout, the exact isolation setup must be handled carefully.
* **Rate-Limit Failures on Non-Backoff Retries (Severity: MEDIUM):**
  * *Context:* Decision `D-12` specifies exactly 1 retry with no backoff delay, replaying the exact same request.
  * *Risk:* If the first attempt failed due to an OpenRouter rate limit (HTTP 429) or temporary provider overload (HTTP 503), retrying immediately without delay has a high probability of failing again, wasting the query's single retry attempt.
* **Out-of-Order Checkpoint Traversal Sorting (Severity: LOW):**
  * *Context:* Checkpoint rows in [gateway/db/schema.hcl](file:///D:/Repos/lancet/gateway/db/schema.hcl) are indexed and sorted via a non-unique composite index on `(trace_id, created_at)`.
  * *Risk:* Relying solely on `created_at` timestamp precision for chronological ordering of snapshots (e.g., Reformulate -> Graph -> Retrieve) can lead to out-of-order logs if multiple checkpoints are persisted in sub-millisecond proximity or concurrent background workers write them out of order.
* **Database Connection Leaks on Schema Drop (Severity: LOW):**
  * *Context:* Per-test schemas are dynamically created and dropped in Go integration tests.
  * *Risk:* If a test panics or database connections inside the active pool are not fully closed prior to dropping the schema, table descriptor leaks or active lock errors might occur on the Postgres instance.

---

## 4. Suggestions
* **Bypass Chi Timeout via Sub-Routing:** Explicitly isolate `/rag/query` from the global timeout middleware in [gateway/main.go](file:///D:/Repos/lancet/gateway/main.go) by restructuring the router initialization:
  ```go
  r.Group(func(r chi.Router) {
      r.Use(middleware.Timeout(60*time.Second))
      r.Post("/documents", a.createDocument)
      r.Get("/documents/{id}", a.getDocument)
  })
  r.Post("/rag/query", a.queryRAG) // Bypasses the 60s timeout
  ```
* **Add Jittered Backoff for Provider Errors:** Modify the retry logic in `GenerateAnswerNode` to wait a minimal, configurable baseline duration (e.g., 250ms–500ms) or parse standard `Retry-After` HTTP headers from provider responses before starting the second LLM generation call.
* **Introduce Step Sequence Ordinals:** Add an explicit `step_number` or `sequence_ordinal` integer column to the `workflow_checkpoints` table. This guarantees correct step-by-step sorting when querying database rows, regardless of timestamp resolution or thread write timing.
* **Ensure Explicit Connection Pool Closure in Tests:** In the integration test schema cleanup helper, ensure that `dbPool.Close()` is called to drain and sever all active pool connections before executing the `DROP SCHEMA <test_schema> CASCADE` statement.

---

## 5. Risk Assessment
* **Overall Risk Level:** **LOW-MEDIUM**
* **Justification:** The planning documents show high architectural maturity, providing explicit details on memory bounds, thread-yielding safety, and codegen isolation. Incorporating dependency injection for all data-plane layers and locking in a comprehensive test suite of 24 deterministic scenarios guarantees high test coverage. The risk is downgraded to Low-Medium because the only major points of friction—the global gateway timeout conflict and immediate provider retries—can be easily mitigated during execution.

---

## Claude Review (opus, high)

# Cross-AI Plan Review — Phase 5 (05-01 … 05-06)

**Basis:** All findings below were verified by reading `D:\Repos\lancet` directly (proto, engine, gateway, generated stubs, tests, config, sqlc/atlas). Line citations are from the current working tree at `f68ce15`.

---

## 1. Summary

This is a strong, unusually well-evidenced plan set. Almost every load-bearing citation checks out against source — `query_rag` at `engine/src/main.rs:1346`, `d1_status` at `:877`, `attempt_graph_augmentation` at `:1056-1236` (confirmed infallible-by-construction, no internal timeout), `fuse_candidates` at `engine/src/retrieval/fusion.rs:58`, the global chi timeout at `gateway/main.go:464`, the dual schema source (`gateway/sqlc.yaml` → `db/schema.sql` vs. `gateway/atlas.hcl` → `db/schema.hcl`), and all 21 Rust test names in 05-01's migration list. The wave ordering in `.planning/ROADMAP.md:327-349` now matches every `depends_on`, which closes the prior review's 05-04/05-05 coordination gap.

Three findings, however, are load-bearing enough to change execution. **(a)** 05-01's own verification gate cannot pass: an existing, unskipped Go test spawns the real Rust engine and calls it through the real *unary* Go client, so the moment 05-01 flips `QueryRAG` to server-streaming, `go test ./...` in `gateway` fails at runtime — the Rust-only `buf.gen.yaml` guard protects compile-time only. **(b)** The locked `generation_node_timeout_ms = 30000` collapses the node budget onto the pre-existing 30s *per-attempt* provider timeout, which is precisely the FAIL condition written into this phase's own `05-AI-SPEC.md:412` — D-12's retry becomes unreachable for the provider-timeout case it was written for. **(c)** The "pre-stream trailer identity" contract the plans preserve does not exist in the code as described, and after this phase no production path emits those trailers at all.

---

## 2. Strengths (verified, not restated from the plans)

- **05-01's Rust test-migration list is complete and accurate.** All 21 named test functions (`query_rag_happy_path_service`, `configured_evidence_token_budget_is_exact`, `graph_augmentation_attempted_and_failed_is_observable_end_to_end`, the five `query_rag_fail_closed_embedding_*`, etc.) exist exactly once in `engine/src/tests.rs`; there are 29 `.query_rag(` call sites, matching the plan's ~27 named tests plus the three calls inside `service_index_generation_is_opaque_and_stable`. This is not a speculative list.
- **The `futures::StreamExt` collision warning is real and non-obvious.** `engine/src/main.rs:14` already does `use futures::{future::BoxFuture, StreamExt, TryStreamExt};` — 05-01's instruction to alias `tokio_stream::StreamExt as TokioStreamExt` prevents a genuine ambiguity error.
- **The Tokio feature claim is correct.** `engine/Cargo.toml:8` declares only `features = ["rt-multi-thread", "macros"]` while the code already uses `tokio::sync::RwLock`/`mpsc` transitively; adding `time`/`sync` explicitly is warranted, and `tokio-util`/`tokio-stream` are genuinely absent.
- **05-06's config-contract extension targets the real test.** `engine/src/tests.rs:138-216` (`config_example_matches_effective_rag_contract`) does exactly what the plan describes: a `REQUIRED_EFFECTIVE_RAG_KEYS`/`ANNOTATIONS` pair, a section allowlist at `:180` (`"engine.retrieval" | "engine.retrieval.bm25" | "engine.graph" | "openrouter"`), an adjacent-comment marker assertion, and an exact set equality. "Extend the arrays, allowlist, and annotation checks" is a precise instruction, not a hand-wave.
- **05-06's negative greps are well-aimed.** `queryRAG\s+func\(...\)` matches `gateway/main_test.go:647` (two spaces). The `json\.Unmarshal\(recorder\.Body\.Bytes\(\),\s*&(?:res|resp|response)` guard catches exactly the three `/rag/query` success decodes (`:737`, `:820`, `:2168`) and correctly does *not* false-positive on `:2304` (`&parsed`, inside `TestWriteJSONEncodeFailureReturns500`).
- **`newHTTPServer` assertion is grounded.** `gateway/main.go:866-873` sets `ReadTimeout: 60s` and `ReadHeaderTimeout: 10s` with no `WriteTimeout`/`IdleTimeout` — so `TestHTTPServerKeepsReadBoundsWithoutResponseTimeout` checks real fields, and the analysis is correct (Go's `ReadTimeout` bounds request reads, not response writes, so it does not cap SSE).
- **The graph inner-timeout resolution is correctly motivated.** `attempt_graph_augmentation` (`engine/src/main.rs:1056-1236`) returns `GraphAugmentationOutcome` (`:1046-1054`) and never `Err`, and contains no `tokio::time::timeout` — so relying only on the runner's outer race genuinely would make the timeout sub-case behave differently from the logical-failure sub-case, contradicting D-09. 05-02's inner-deadline requirement is the right fix.
- **Generated-stub grep will work.** `gateway/proto/lancet/v1/lancet_grpc.pb.go:1-4` shows `protoc-gen-go-grpc v1.3.0` (non-generic style, e.g. `Recv() (*IngestDocumentRequest, error)` at `:186`), so 05-06's `Recv\(\) \(\*WorkflowEvent, error\)` assertion will match the new named client interface and cannot false-positive on the existing ingest stubs.
- **05-05's dual-schema requirement closes a real gap.** `gateway/sqlc.yaml:3` points at `db/schema.sql`; `gateway/atlas.hcl:7` points at `db/schema.hcl`; there is no migrations dir/Makefile enforcing parity. Requiring both is correct. `fakeStore` (`gateway/main_test.go:45`) is the sole `documentStore` implementer, so the interface-extension blast radius is genuinely small.

---

## 3. Concerns

### HIGH — 05-01's verification gate is unpassable; `TestRAGQueryCrossRuntime` breaks at runtime, not compile time

The reviewers' `buf.gen.yaml` drift finding was addressed at the **compile** layer (05-01 checks in a Rust-only template, hashes `gateway/proto/*` and `gateway/main.go`, runs `go build ./...`). But the drift is also a **runtime** hazard, and one existing test exercises it:

- `gateway/main_test.go:1893` `TestRAGQueryCrossRuntime` has **no build tag and no `t.Skip`** (the only `t.Skip` in the file is at `:1710`, for `TEST_DATABASE_URL`).
- It unconditionally builds the real engine (`:2026`, `cargo build … --bin engine`), starts it (`:2074`), and calls the gateway with the **real** client: `app{store: &fakeStore{}, engine: grpcEngine{client: client}, …}.routes().ServeHTTP(...)` at `gateway/main_test.go:2161`.
- After 05-01 lands, the Rust server serves `QueryRAG` as server-streaming while `grpcEngine.QueryRAG` (`gateway/main.go:280-287`) still invokes it as unary against stale stubs. grpc-go's unary `RecvMsg` performs a second receive and fails with a client-streaming protocol violation once a second message arrives — and the workflow emits at minimum `NodeStarted`/`NodeCompleted`/`WorkflowCompleted`. The assertions at `:2168-2180` (answer `DENSE_AND_LEXICAL_FIXTURE_MARKER [1]`, citation `[1]`, snapshot fields) cannot pass.

05-01 Task 2's `<automated>` block ends with `Push-Location gateway; go test ./...` and its `<verification>` states "the current unfiltered Go suite pass[es] at the wave boundary." That is contradicted by the source. **05-01 cannot be completed as written.**

*Fix:* either move the `TestRAGQueryCrossRuntime` migration into 05-01 (it is already in 05-06's list, so it would just move a wave earlier), or land 05-01+05-06 as one unit, or add an explicit, temporary skip with a plan-recorded removal obligation in 05-06.

### HIGH — `generation_node_timeout_ms = 30000` implements the failure condition this phase's own spec defines

- The provider already enforces **30s per attempt**: `GENERATION_TIMEOUT: Duration = Duration::from_secs(30)` (`engine/src/generation/openrouter.rs:24`), applied at `openrouter.rs:626` (`timeout(self.config.timeout, self.execute_one_call(request))`), configured as `generation_timeout_secs = 30` (`config/config.toml:35`).
- 05-06 Task 1 locks `generation_node_timeout_ms=30000` as the *node* deadline and 05-03 requires the retry to fit "using the remaining node budget."
- `05-AI-SPEC.md:265` (pitfall #3): *"If GenerateAnswer's D-17 node-level timeout is read as 30s total … the retry can never run — it becomes dead code."* `05-AI-SPEC.md:412` makes it an explicit eval **FAIL**: *"or the node-level budget collapses onto the 30s per-attempt figure such that D-12's retry can never fire."*
- Both plans acknowledge the conflict and resolve it toward the failing reading ("use the locked CONTEXT.md D-17 interpretation as authoritative over the alternative retry-budget interpretation in 05-AI-SPEC.md").

Consequence: D-12 names "timeout, 5xx, rate limit" as the retry's purpose. Under this configuration, **the timeout case can never retry** (attempt 1 consuming 30s exhausts the node deadline), and any attempt that fails slowly (e.g. 25s → 502) leaves ~5s — insufficient for a real replay. Only fast-failing provider errors retry. That is a materially weaker ORCH-03 than the requirement describes, delivered without flagging it as a scope reduction. Note this does *not* rescue the chi fix: worst case is still 5+10+15+2+30 = 62s > 60s, so 05-06's route exemption remains necessary.

*Fix:* this deserves a `checkpoint:decision` gate (05-05 already sets that precedent) rather than a silent resolution — either ~65s node budget per the AI-SPEC, or an explicit, recorded acceptance that "retry" means "fast-failure retry only" with `Timeout` removed from the retryable set so it isn't misleadingly advertised.

### HIGH — the "pre-stream trailer identity" contract is mis-described and silently retired

05-01's must_have asserts: *"invalid session or query input remains a trailer-bearing gRPC error."* Source says otherwise:

- Malformed `session_id` → `Status::invalid_argument("session_id must be a valid UUIDv4 string")` at `engine/src/main.rs:1356-1362` — **plain `Status`, no metadata**.
- `QueryRequest::from_values` failures → plain `Status::invalid_argument(...)` at `main.rs:1381-1392` — **no metadata**.
- The only trailer producer is `d1_status` (`main.rs:877-898`), and *every* current call site is post-validation infrastructure failure: embedding invalid payload (`:1408`), embedding transport (`:1417`), plus dense-retrieval/reranker/generation later — exactly the paths 05-01 moves in-stream.

So after Phase 5: no production path emits `x-lancet-session-id`/`-correlation-id`/`-error-kind` pre-stream, while `gateway/main.go:693-704` keeps forwarding them and 05-06 keeps four tests asserting the headers (`gateway/main_test.go:945`, `:995`, `:1045`, `:1095`) that will only ever pass against `trailerError` fakes. Meanwhile nothing in any plan requires the in-band `NodeFailed`/`WorkflowCompleted` path to surface session/correlation identity to the HTTP client at all (events carry `trace_id`, terminal carries `session_id`, but no response headers). **A client-visible identity contract disappears with no stated replacement**, and its regression tests become non-representative.

*Fix:* state explicitly what happens to `X-Lancet-*` on the SSE path (set them from the first event before flushing headers is the obvious move, and is compatible with 05-06's first-frame prefetch), and correct 05-01's truth statement.

### MEDIUM — the incremental node-migration bridge is never specified (05-01, 05-02)

05-01 introduces a runner with exactly one node (`ReformulateQueryNode`) yet requires every existing behavioral test — including `query_rag_happy_path_service` (`tests.rs:2181`) and the three `graph_augmentation_*_end_to_end` tests — to still produce a real terminal `QueryRAGResponse` through `drain_query_rag_stream`. That means ~90% of the pipeline (`main.rs:1395-1708`) must keep running as inline code alongside the runner, and the terminal event must be built from it. **Neither 05-01 nor 05-02 says how.** 05-02 then makes the vector `[Reformulate, ExtractGraphContext, RetrieveHybrid]` while prompt assembly and generation remain inline until 05-03.

This is the single largest unspecified mechanism in the phase: three plans each shrink an inline remainder that must keep ~25 assertions green, with no stated contract for how `WorkflowContext` hands off to the remainder or who emits `WorkflowCompleted`. Expect executor divergence and rework at each wave boundary.

### MEDIUM — cross-variant RRF: output shape and score semantics unspecified

`FusedCandidate` (`engine/src/retrieval/fusion.rs:16-23`) carries **single-valued** `vector_rank`, `bm25_rank`, `vector_score`, `bm25_score`. N reformulation variants produce N provenances per chunk. 05-02 requires the merge to "retain each candidate's source rank/score provenance" without saying whether the struct grows (breaking `rerank::Reranker`, `engine/src/rerank/mod.rs:12-15`, which takes/returns `Vec<FusedCandidate>`) or one variant's provenance is arbitrarily kept.

Worse, `fused_score` is **client-visible**: `engine/src/prompt.rs:62` sets `score: candidate.fused_score` on each evidence block, which flows to `StructuredCitation.score` in the proto response. A second RRF pass summing raw `1/(rrf_k + rank)` produces different magnitudes than `fuse_candidates`' *weighted* RRF (`fusion.rs:66-80`, weights applied and zero-weight sources skipped). 05-02 asks for a "one-variant equivalence" test but never says whether equivalence means *order* or *score identity* — under the former, a phase that promises "MUST NOT change existing retrieval semantics" silently changes an API field. (No existing test pins exact fused scores, so this would not be caught.)

### MEDIUM — `CheckpointHandoff` is over-built relative to its own requirements

D-27 is explicitly fire-and-forget ("a dropped/delayed checkpoint write never stalls or fails the user's actual query"); D-24 has no retention; D-25 has no fetch API; the feature is developer-debugging-only. The plans respond with: a 1-slot primary queue + 5-slot owned FIFO overflow, `Pending`/transport-closed/`Overflow` statuses, a detached drain, a mirrored Go `CheckpointDispatcher` with the same constants, a `Drain(ctx)` retry contract, and six dedicated tests (three Rust in 05-04, three Go in 05-05/05-06) plus three STRIDE entries (`T-05-05`, `T-05-27`, `T-05-28`). This is the most elaborated mechanism in the phase, attached to its least-consequential requirement, against `PROJECT.md`'s explicit "avoid overbuilding" / "scope discipline" constraint.

A concrete symptom: `test_workflow_checkpoint_sixth_record_reports_overflow` is listed in 05-04's *"complete service-level matrix"*, but the fixed 5-node workflow can emit at most 5 checkpoint records (and only 3 on the D-03 short-circuit path), so a sixth record is unreachable through `LancetServiceImpl::query_rag` — it can only be a direct unit test on `CheckpointHandoff`, contradicting the matrix's own framing and 05-04's prohibition against tests that "bypass `LancetServiceImpl` dependency construction."

### MEDIUM — several named Go transport tests have no stated deterministic mechanism

- `TestQueryRAGSSEFramesFlush` claims to assert "SSE frame boundaries and flushes." `httptest.ResponseRecorder` exposes a single `Flushed bool` and buffers everything — you cannot observe per-frame flush or that the first frame was prefetched *before* headers committed. Every existing `/rag/query` test uses `httptest.NewRecorder()` (`main_test.go:726`, `:809`, `:2160`). Without switching to `httptest.NewServer` + incremental body reads, this test passes trivially and proves nothing about streaming incrementality.
- `TestQueryRAGRouteTimeoutIsolation`: chi does not expose per-route middleware for introspection, and waiting out 60s is not viable. The plan gives no mechanism (e.g. making the timeout injectable) for making this deterministic.
- `TestQueryRAGFirstFramePrefetch` has the same observability problem as the flush test.

### LOW

- **05-05 internal inconsistency.** The `<action>` text lists `context_snapshot|jsonb|NO|<NULL>|<NULL>|<NULL>|<NULL>` (7 fields) while `<schema_inspection_contract>` and the executable `$expectedColumns` array use 8 (`…|<NULL>|<NULL>`). The SQL selects 8 fields, so the prose is wrong and the gate is right — but a reader following the prose will mis-author the row.
- **05-05 context gaps.** `depends_on: [05-03, 05-06, 05-04]` but `<context>` loads only `05-03-SUMMARY.md`. The executor will not have 05-06's summary despite Task 1 modifying `gateway/checkpoint_sink.go`, a file 05-06 creates (mitigated only by `read_first`).
- **Rust type names.** The prost-generated types are `QueryRagRequest`/`QueryRagResponse` (see `engine/src/tests.rs:2302`), not `QueryRAGResponse` as written throughout the Rust-side plan text including the `drain_query_rag_stream` signature.
- **Reranker failure is uncovered.** `query_rag_reranker_failure_skips_generation` exists (`tests.rs`), rerank sits inside 05-02's `RetrieveHybridNode` ("apply the existing final-limit/reranker path"), but no reranker scenario appears in 05-04's *"exhaustive"* 24-test matrix and `NodeErrorKind` has no natural category for it.
- **`config/config.verify.toml`** exists and is consumed by `scripts/phase02_live_evidence.py:179` but is not in 05-06's `files_modified`; the contract test only reads `config.example.toml` (`tests.rs:143`), so `config/config.toml`'s new section is unverified by the named tests.
- **05-01's `clean: false` rationale is inaccurate.** "set `clean: false` so existing unary Go outputs are preserved" — in a Rust-only template `gateway/proto` is not a plugin `out`, so buf could not clean it regardless. Harmless belt-and-braces, but the stated mechanism is wrong.

---

## 4. Suggestions

1. **Move the `TestRAGQueryCrossRuntime` migration into 05-01**, or merge 05-01+05-06 into one landing. Add an explicit runtime-drift note alongside the existing compile-time buf guard.
2. **Escalate the generation-timeout arithmetic to a `checkpoint:decision`** with two options (65s node budget per `05-AI-SPEC.md:305`, vs. 30s with `Timeout` removed from the retryable set and the reduction recorded), rather than resolving it inside plan prose.
3. **Add an explicit requirement that in-stream `NodeFailed`/terminal events populate `X-Lancet-Session-ID`/`-Correlation-ID`/`-Error-Kind` response headers** from the prefetched first frame, and correct 05-01's trailer truth statement (malformed input returns a bare `Status`, `main.rs:1356/1381`).
4. **Add a short "inline remainder contract" section to 05-01 and 05-02**: exactly which `main.rs` lines stay inline, how `WorkflowContext` is handed to them, and who emits the terminal event at each wave.
5. **Pin the cross-variant merge's output type and score contract**: either extend `FusedCandidate` with per-variant provenance (and accept the `Reranker` signature churn), or state that variant-0 provenance wins; and require the 1-variant path to be *score-identical*, not merely order-equivalent, so `StructuredCitation.score` does not shift.
6. **Right-size the checkpoint handoff**: keep bounded `try_send` + a drop counter (which is all D-27 asks for), and drop the 6-slot FIFO/`Pending`/`Overflow` machinery and its six tests — or, if kept, move `test_workflow_checkpoint_sixth_record_reports_overflow` out of the service-level matrix and label it a unit test.
7. **Specify the SSE test harness**: `httptest.NewServer` + `bufio.Scanner` over the live body for `TestQueryRAGFirstFramePrefetch`/`TestQueryRAGSSEFramesFlush`/`TestQueryRAGMidstreamRecvErrorClosesCleanly`, and make the route timeout injectable so `TestQueryRAGRouteTimeoutIsolation` is deterministic.
8. Add a reranker-failure scenario to 05-04's matrix, and fix the 05-05 column-spec typo plus the missing dependency summaries in `<context>`.

---

## 5. Risk Assessment

**Overall: HIGH.**

The design is sound and the evidence discipline is genuinely above average — most of what the plans assert about this repo is true, and the wave graph is now internally consistent. The risk is not conceptual, it is executional and concentrated in three places:

- **05-01 is currently un-completable** (its own `go test ./...` gate fails on `main_test.go:1893`). That alone blocks the wave chain, since every other plan depends transitively on it.
- **A locked configuration knowingly implements this phase's own documented eval failure** (`05-AI-SPEC.md:412`), silently reducing ORCH-03's delivered scope.
- **A client-visible identity contract is retired without replacement**, with its regression tests preserved in a form that can no longer detect the loss.

Per-plan: 05-01 **HIGH** (blocking gate defect + trailer mis-statement + unspecified inline bridge); 05-06 **HIGH** (retry arithmetic, unverifiable streaming tests, other half of the drift window); 05-03 **MEDIUM-HIGH** (retry deadline, otherwise strong); 05-02 **MEDIUM** (RRF output/score shape); 05-05 **MEDIUM** (well-grounded; minor spec/context defects); 05-04 **LOW-MEDIUM** (strongest plan; matrix/service-level inconsistency on the overflow case).

None of these require re-planning the phase. They require fixing 05-01's sequencing before execution begins, and making two deliberate decisions (generation budget, identity headers) explicit rather than implicit.

---

## Consensus Summary

The reviewers agree that the six plans are architecturally strong and aligned with the fixed RAG state-machine goal, but they do not agree that the plan set is ready to execute unchanged. The shared concern is concentrated in timing and boundary contracts; Claude additionally identified several concrete execution blockers that should be resolved before the first wave.

### Agreed Strengths

- The Rust/Go boundary and wave-based decomposition are coherent, with Rust owning orchestration/data-plane work and Go owning HTTP/SSE and PostgreSQL responsibilities.
- The plans take testability and failure handling seriously, including injectable retrieval seams, bounded checkpoint delivery, and the repository's isolated PostgreSQL fixture convention.
- The existing 60-second gateway timeout is recognized as a real constraint; both reviewers agree that route-level timeout isolation must be explicit and deterministic.

### Agreed Concerns

- **HIGH — End-to-end timeout/retry contract:** the planned node budgets and one-retry behavior can exceed the gateway's global 60-second timeout, while immediate/no-backoff retries are weak for provider throttling. Make route isolation and retry timing/error semantics an explicit, tested contract.
- **MEDIUM/HIGH — Checkpoint and event ordering contracts:** checkpoint persistence and streamed event handling need deterministic ordering and lifecycle guarantees; review the timestamp-only ordering assumption and ensure persistence cannot affect the response path.

### Divergent Views

- Antigravity assesses the plan set as LOW-MEDIUM risk and broadly approved after four targeted mitigations. Claude assesses it as HIGH risk because 05-01's existing cross-runtime test would fail once the RPC becomes streaming, the 30-second generation node budget can make timeout retries unreachable, and the pre-stream identity/trailer contract has no stated SSE replacement.
- Antigravity recommends adding retry backoff and stronger checkpoint ordering/cleanup safeguards. Claude instead prioritizes sequencing the runtime test migration, defining the inline-to-runner bridge, pinning cross-variant RRF score semantics, and making SSE/timeout tests use a live deterministic harness.
- Claude also flags scope proportionality for the six-slot checkpoint handoff and several plan-text/test-matrix inconsistencies; these are not raised by Antigravity and should be treated as targeted follow-up checks rather than consensus blockers.
