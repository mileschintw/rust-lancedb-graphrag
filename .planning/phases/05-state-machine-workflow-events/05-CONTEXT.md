# Phase 5: State Machine & Workflow Events - Context

**Gathered:** 2026-08-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Formalize the existing linear `query_rag` pipeline (`engine/src/main.rs:1346`+ — validate → embed → graph-augment → dense retrieve → BM25 retrieve → fuse → rerank → assemble prompt → generate) into a typed Rust state machine that streams workflow events from Rust → Go → client over the query path only. The ingestion worker loop is untouched — ORCH-01's "fixed RAG path" means `QueryRAG`, not ingestion.

In scope: the fixed node sequence (`ReformulateQuery -> RetrieveHybrid -> ExtractGraphContext -> AssemblePrompt -> GenerateAnswer -> Complete/Failed`), server-streaming `QueryRAG` over gRPC with SSE at the HTTP boundary, per-node timeouts, generation-only retry, native cancellation propagation, and PostgreSQL-backed lightweight checkpoints (ORCH-01 through ORCH-04), plus the `QueryReformulator` pass-through port (ORCH-05).

Out of scope: the `answer_basis: degraded/model_only` response contract and citation repair (DEBT-RAG-01/DEBT-RAG-03, Phase 6), full OpenTelemetry span export and workflow-metadata collection (Phase 6, OBS-01), real query-reformulation strategies (999.3 backlog), the standalone `QueryGraph` RPC (04.1, untouched by this phase), and provider/model fallback beyond a single retry (descoped, see D-14).

</domain>

<decisions>
## Implementation Decisions

### Answer Delivery & Streaming Model
- **D-01:** "Streaming" means workflow progress events, not LLM token streaming. Phase 3 D-28's validated JSON-schema generation call (answer text + citations + answer_basis + notices, via `openrouter.rs`'s `response_format`/`json_schema` pattern, lines ~289-458) stays unchanged. `AnswerChunk` fires exactly once, carrying the complete validated answer. — **Reversibility:** costly — moving to true token streaming later requires reworking the structured-output validation strategy (incremental JSON parsing or post-hoc validation against streamed text) and touches the generation contract locked in Phase 3.
- **D-02:** Keep both `AnswerChunk` and `FinalAnswer` as distinct event types even though v1 always emits exactly one `AnswerChunk`. Preserves forward compatibility — a future move to real token streaming (multiple `AnswerChunk`s) is a behavior change, not an event-contract change.
- **D-03:** When retrieval finds zero evidence (today's existing early-return with a `NO_EVIDENCE` notice, `main.rs:1508-1547`), the state machine skips straight from `RetrieveHybrid` to `Complete` — `AssemblePrompt`/`GenerateAnswer` are not entered even as no-ops. This is a valid successful completion, not a failure path.

### State Machine Boundary & Validation Contract
- **D-04:** `ReceiveQuery` (session_id/correlation_id parsing and minting, query validation) stays in the tonic handler, executed synchronously **before** the server-streaming response opens. A malformed request still returns a real gRPC `Status` / HTTP 4xx exactly as today — no stream opens for a rejected request. The state machine itself starts at `ReformulateQuery`. — **Reversibility:** one-way — reversing this retires the trailer-based error-identity pattern (`main.rs:887-891` sets `x-lancet-session-id`/correlation-id gRPC status metadata; `gateway/main.go`'s `trailerError` type at line 263 and the HTTP handler at line 693 both read it) that Go's error-response path already depends on.
- **D-05:** Once the stream is open (past validation), any node's terminal failure is reported entirely in-band: a `NodeFailed` event (carrying the typed error category, see D-22) followed by a terminal `WorkflowCompleted(failed)` event, then the SSE stream closes normally at the HTTP level (still committed to 200 — the failure is a payload, not a transport-level error).

### Pipeline Order & Node Behavior (refines `.discussion/lightweight_state_machine_plan.md`)
- **D-06:** The shipped pipeline order — graph augmentation (`ExtractGraphContext`) runs **before** hybrid retrieval (`RetrieveHybrid`) — is kept; the plan doc's node order (`RetrieveHybrid -> ExtractGraphContext`) is superseded for this codebase. Rationale: 04.1 D-18 seeds graph traversal from the query embedding, not from retrieved chunks, and the embedding step happens before retrieval in shipped code (`main.rs:1395` embed, `:1426` graph, `:1450` dense retrieval).
- **D-07:** `RetrieveHybrid` loops over the `QueryReformulator`'s `Vec<String>` variants and RRF-merges results across variants (reusing 999.3 D-04's RRF-merge pattern) rather than hard-indexing `[0]` — so 999.3's future real reformulation doesn't require rewriting this node.
- **D-08:** The query-embedding step (`main.rs:1395`) embeds only variant `[0]` in v1. Since the NoOp reformulator (999.3 D-02) always returns exactly one variant, this is behaviorally identical to today. Embedding fan-out across multiple variants is 999.3's problem to size and rate-limit when real reformulation lands.
- **D-09:** `ExtractGraphContext` always executes as a real pipeline node for every query (not conditionally skipped) — but its success is not required for the query to complete. 04.1 D-32's silent degrade to chunk-only evidence on graph seed-match failure/no-match is unchanged. "Mandatory" means the node always runs, not that its result is required.
- **D-10:** The standalone `QueryGraph` RPC (04.1 D-20/D-22/D-25) stays untouched — a separate one-shot gRPC-only endpoint, not wrapped into state-machine nodes/events. ORCH-01 scopes the state machine to the fixed RAG path (`QueryRAG`'s pipeline) only.

### Retry, Fallback & Cancellation
- **D-11:** Automatic retry is scoped to the generation node only — matches Phase 3 D-29's explicit deferral ("Phase 3 makes one generation attempt with no retries... Formal retry and provider-fallback orchestration remains Phase 5"). No other node (embedding, dense retrieval, BM25, graph) gets automatic retry in this phase.
- **D-12:** Generation gets exactly 1 retry, no backoff delay, replaying the exact same request (same model, temperature 0, top-p 1, same prompt). The retry exists purely to absorb transient provider errors (timeout, 5xx, rate limit), not to try an alternate strategy.
- **D-13:** If generation still fails after the retry, the workflow transitions to `Failed` (`NodeFailed` + `WorkflowCompleted(failed)`) — no fabricated answer, consistent with Phase 3 D-31. This phase does **not** add a model-only/degraded-answer-basis fallback response; that's `DEBT-RAG-01`, explicitly scoped to Phase 6.
- **D-14:** No configured backup model/provider for generation in v1 — single-provider-with-retry is the whole "provider fallback" story satisfying Phase 3 D-29. A genuine multi-provider/backup-model fallback is descoped, not deferred to a specific phase — revisit only if reliability requirements change.
- **D-15:** When the retry fires, the client sees nothing until the final outcome (`NodeCompleted` or `NodeFailed`) — no separate "retrying" event, consistent with D-20's coarse granularity.
- **D-16:** Cancellation relies on native connection-close propagation: client closes the SSE connection → Go cancels its gRPC stream context → Rust's tokio task observes context cancellation (extends Phase 3 D-30's existing pattern through the new streaming path). No new explicit `CancelQuery` RPC.
- **D-17:** Per-node timeouts use the plan doc's example values as defaults for four of five nodes: `ReformulateQuery` 5s, `HybridRetrieval` 10s, `GraphExtraction` 15s, `PromptAssembly` 2s. All configurable via the existing TOML+env override convention (Phase 2 D-26–D-30). **`LLMGeneration` uses two distinct, separately-configured timeouts, not one shared figure:** (1) the existing **per-attempt** provider timeout stays exactly 30s (`GENERATION_TIMEOUT` / `generation_timeout_secs`, `openrouter.rs:24`, `config.toml:35`, Phase 3 D-30 — unchanged, bounds a single `generate()` call); (2) a **new, separately-keyed node-level wall-clock budget** (`generation_node_timeout_ms`, default `65000`) bounds the `GenerateAnswer` *node* as a whole, wrapping up to two `generate()` calls per D-12's single retry — it must NOT reuse the `generation_timeout_secs` key. — **Amendment (2026-08-12, resolved via a `--reviews` checkpoint after cross-AI review flagged this HIGH-severity, `05-REVIEWS.md`):** the original text collapsed the node budget onto the 30s per-attempt figure, which left a `Timeout`-triggered retry unreachable in practice — attempt 1 alone could exhaust the entire node deadline, the exact failure condition `05-AI-SPEC.md:412` flags. Resolved as **Option A**: widen the node budget to ~65s (2× the per-attempt cap + slack for inter-attempt dispatch overhead, not the preflight) so the retry always has its full 30s available even in the worst case where attempt 1 consumes its entire per-attempt budget (65s ≥ 30s + 30s + 5s slack). `Timeout` remains in D-12's retryable error category alongside 5xx and rate-limit responses, unchanged — this amendment widens the node budget, it does not narrow what's retryable.

### Streaming Transport
- **D-18:** `QueryRAG` converts from unary to server-streaming gRPC — a stream of `WorkflowEvent` messages, the terminal event carrying the equivalent of today's `QueryRAGResponse`. — **Reversibility:** one-way — breaking change to the Phase 3 contract; `gateway/main.go`'s `QueryRAG` interface (line 207) and `grpcEngine.QueryRAG` (line 280) must be rewritten from request-response to stream consumption, and `gateway/main_test.go` must be updated.
- **D-19:** `/rag/query` becomes SSE-only (`text/event-stream`) at the HTTP layer — no content-negotiated fallback to the old single-JSON-response shape. Existing callers/tests must be updated to consume the event stream.
- **D-20:** Event granularity is coarse — one `NodeStarted`/`NodeCompleted` (or `NodeFailed`) pair per pipeline node (`ReformulateQuery`, `RetrieveHybrid`, `ExtractGraphContext`, `AssemblePrompt`, `GenerateAnswer`), plus `AnswerChunk`/`FinalAnswer`/`WorkflowCompleted`. No sub-step events (no separate dense-vector vs. BM25 events, no `NodeRetrying` events per D-15).
- **D-21:** No SSE reconnect/resume support (no Last-Event-ID event buffering/replay) — if the connection drops, the client re-issues the query. Matches PROJECT.md's local-first demo scope and its "avoid speculative hardening" constraint.

### Error Visibility
- **D-22:** `NodeFailed` events expose both the typed error category (from the plan doc's taxonomy: `InputValidation`, `RetrievalFailed`, `GraphQueryFailed`, `PromptAssemblyFailed`, `LlmGenerationFailed`, `Timeout`, `Cancelled`, `Internal`) and a human-readable message — not just a generic failure string. Lets the client UI distinguish transient-adjacent failures from fatal ones.

### Checkpointing (ORCH-04)
- **D-23:** Checkpoint snapshots are persisted to PostgreSQL (not memory-only, not JSON files) — durable and queryable alongside existing session/document metadata. Note: unlike the metadata Postgres currently holds, checkpoint context payloads carry corpus content (chunk text, graph facts, assembled prompt) — consistent with 04.1 D-33's existing "no redaction system, single-user local demo" accepted-risk framing; extend that acceptance to this table, no new mitigation needed.
- **D-24:** Checkpoint rows persist indefinitely — no TTL/retention cleanup job in v1, matching PROJECT.md's scope-discipline constraint.
- **D-25:** No new API/RPC to fetch checkpoints — direct DB inspection (psql or a local script) is the only access path in v1.
- **D-26:** Rust does **not** get its own Postgres connection. The Rust state machine sends checkpoint payloads to Go (alongside/within its workflow events over the streaming gRPC connection), and Go's existing Postgres connection persists them — preserves the established "Go owns Postgres, Rust owns LanceDB" boundary from Phase 2/3/04.1.
- **D-27:** Checkpoint writes are fire-and-forget — the query pipeline does not wait for Go to confirm the Postgres write before proceeding to the next node. A dropped/delayed checkpoint write never stalls or fails the user's actual query.
- **D-28:** Each checkpoint row's context payload is a full accumulated snapshot (everything gathered so far — original_query, reformulated_query variants, vector_results, bm25_results, graph_context, assembled_prompt, answer — whichever fields are populated by that point), not an incremental per-node diff.

### Identity
- **D-29:** The state machine's `trace_id` (used in events and checkpoints) reuses the existing per-request `correlation_id` (generated fresh per `QueryRAG` call, already used in `d1_status` error responses today, `main.rs:887-891`) — no new third identifier introduced alongside `session_id` and `correlation_id`.

### Observability Scope (explicitly deferred to Phase 6)
- **D-30:** Workflow metadata (`started_at`/`completed_at`, `reformulation_used`, `vector_count`, `bm25_count`, `graph_node_count`/`edge_count`, `prompt_tokens`, `completion_tokens`, `degraded_mode`) is **not** added to `WorkflowCompleted` or `RetrievalSnapshot` in this phase — Phase 6's OpenTelemetry/observability work (OBS-01) owns this.
- **D-31:** Per-node tracing spans (`query_reformulation`, `hybrid_retrieval`, `graph_context_extraction`, `prompt_assembly`, `llm_generation`, named in the plan doc) are **not** added in this phase — deferred entirely to Phase 6 alongside full OTel export. Nodes execute without new span instrumentation beyond the existing `query_rag` span.

### Claude's Discretion
- Exact Rust module/file layout for the `Node` trait, `WorkflowRunner`, and event types.
- Internal error type names and exact configuration key names for the new timeout/retry/checkpoint knobs (follow the existing TOML+env override convention).
- Exact `WorkflowEvent` protobuf message shape (`oneof` vs. separate messages per event type) — must carry the event types and payloads decided in D-01–D-31.
- Exact SSE framing details (event ID scheme, `retry:` field presence) beyond "no resume support" (D-21).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Primary Design Doc
- `.discussion/lightweight_state_machine_plan.md` — fixed node sequence, typed workflow context, event types, retry/timeout policy, checkpoint fields. **Note:** its node order (`RetrieveHybrid -> ExtractGraphContext`) is superseded by D-06 — read the decision above before following the doc's transition table literally.
- `.discussion/final_implementation_decision_document.md` — confirms the Go/Rust split-service boundary; contains no override of this phase's streaming-transport decisions (D-18/D-19).

### Requirements & Roadmap
- `.planning/ROADMAP.md` §Phase 5 (lines 312–323) — goal, requirements ORCH-01 through ORCH-05, success criteria.
- `.planning/REQUIREMENTS.md` — ORCH-01 through ORCH-05 definitions.

### Prior Phase Context (must not regress)
- `.planning/phases/999.3-query-reformulation-strategies/999.3-CONTEXT.md` — `QueryReformulator` trait shape (D-02: async `reformulate` → `Vec<String>`, NoOp returns `[original_query]`) and RRF-merge pattern (D-04) this phase's `RetrieveHybrid` node reuses per D-07.
- `.planning/phases/03-hybrid-retrieval-basic-rag-path/03-CONTEXT.md` — D-10 (400 on invalid input), D-18 (streaming deferred to Phase 5), D-24 (citation repair deferred to Phase 6), D-28 (structured-output generation contract, unchanged per D-01), D-29 (retry/provider-fallback deferred to Phase 5), D-30 (cancellation propagation pattern reused by D-16), D-31 (provider-error contract reused by D-13), D-39 (evidence token budget, unchanged).
- `.planning/phases/04.1-knowledge-graph-extraction-query-full-implementation/04.1-CONTEXT.md` — D-18 (graph traversal seeded from query embedding, informs D-06), D-20/D-22/D-25 (`QueryGraph` RPC contract, stays untouched per D-10), D-32 (silent degrade on graph failure, unchanged per D-09), D-33 (accepted risk / no redaction, extended to checkpoints per D-23).

### Existing Code (the pipeline this phase formalizes)
- `engine/src/main.rs:1346`+ — the `query_rag` tonic handler: validation/ID-minting (D-04's `ReceiveQuery` boundary), `d1_status` trailer-metadata pattern (lines 887–891), graph-before-retrieval order (line 1426 vs. 1450, D-06), zero-evidence early return (lines 1508–1547, D-03).
- `engine/src/generation/openrouter.rs:289-458` — the `response_format`/`json_schema` structured-output pattern this phase's D-01 leaves unchanged.
- `gateway/main.go` — `QueryRAG` interface (line 207), `grpcEngine.QueryRAG` + trailer read (lines 280–287), `/rag/query` route (line 468) and handler (line 691) — all rewritten for streaming per D-18/D-19.
- `proto/lancet/v1/lancet.proto` — `QueryRAGRequest`/`QueryRAGResponse` (lines 53–112), converts to server-streaming per D-18.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `engine/src/main.rs`'s `query_rag` handler — the existing linear pipeline (validate → embed → graph-augment → dense retrieve → BM25 → fuse → rerank → assemble prompt → generate) this phase's nodes are extracted from; the sequence and order are preserved (D-06), just wrapped in node/event/retry machinery.
- `engine/src/generation/mod.rs`'s `Generator` trait, `GenerationRequest` — unchanged, reused as-is per D-01.
- `gateway/main.go`'s `trailerError`/`grpcEngine` pattern — the error-identity contract D-04 preserves for pre-stream validation failures.

### Established Patterns
- TOML + env-var override convention (Phase 2 D-26–D-30) — the new per-node timeout, retry, and checkpoint knobs should follow this.
- Rust owns all RAG/vector/graph semantics; Go remains a thin HTTP/gRPC/PostgreSQL boundary — preserved by D-26 (checkpoint writes go through Go, not a new Rust DB connection).
- Existing `tracing::info_span!("query_rag", ...)` pattern — not extended with new per-node spans this phase (D-31).

### Integration Points
- `engine/src/main.rs`'s `query_rag` — refactor point: `ReceiveQuery` (validation/ID-minting) stays in the handler; `ReformulateQuery` onward becomes the state machine.
- `gateway/main.go` lines 207, 280–287, 468, 691 — `QueryRAG` interface, trailer handling, and the `/rag/query` handler all need rewriting to consume and re-emit a streamed response as SSE.
- `proto/lancet/v1/lancet.proto`'s `QueryRAG` RPC — converts from unary to server-streaming; new `WorkflowEvent` message type(s) needed.

</code_context>

<specifics>
## Specific Ideas

- The plan doc's example client-facing progress messages ("Reformulating query...", "Retrieved vector chunks...", "Extracted graph context...", "Generating answer...") map directly to the coarse per-node event granularity (D-20).
- Timeout defaults are taken verbatim from `.discussion/lightweight_state_machine_plan.md`: 5s / 10s / 15s / 2s / 30s for `ReformulateQuery` / `HybridRetrieval` / `GraphExtraction` / `PromptAssembly` / `LLMGeneration` respectively (D-17).

</specifics>

<deferred>
## Deferred Ideas

- **Workflow metadata collection** (started_at, token counts, node counts, degraded_mode) and **per-node tracing spans** — both explicitly deferred to Phase 6's OpenTelemetry/observability work (OBS-01). See D-30/D-31.
- **`answer_basis: degraded/model_only` response contract and citation repair** — remain `DEBT-RAG-01`/`DEBT-RAG-03`, Phase 6's hardening target (RAG-03). Not touched by this phase's retry/fallback mechanism (D-13/D-14).
- **Real query-reformulation strategies** (HyDE, multi-query expansion) — remain Phase 999.3 backlog scope; this phase only builds the pass-through port and the `RetrieveHybrid` node shape that can consume it (D-07/D-08).

Descoped (not deferred to any specific phase — revisit only if requirements change, not earmarked work):
- Configured backup model/provider for generation (D-14).
- SSE reconnect/resume support (D-21).
- Explicit `CancelQuery` RPC (D-16).
- Checkpoint-fetch API/RPC (D-25).

</deferred>

---

*Phase: 5-State Machine & Workflow Events*
*Context gathered: 2026-08-10*
