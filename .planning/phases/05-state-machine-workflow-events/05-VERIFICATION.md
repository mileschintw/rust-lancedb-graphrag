---
phase: 05-state-machine-workflow-events
verified: 2026-08-13T00:00:00Z
status: gaps_found
score: 1/5 roadmap success criteria verified (plus 5/14 plan-level truths)
behavior_unverified: 0
overrides_applied: 0
mode: mvp
unverified_prohibitions: 15 # unverified-prohibition — human review recommended (all judgment-tier, no verification tier declared; verdicts below are NON-AUTHORITATIVE)
gaps:
  - truth: "SC1 — RAG pipeline is formalized into a defined state machine."
    status: failed
    reason: "The state machine exists as a library only. The production `query_rag` handler registers exactly ONE node (a no-op pass-through) and delegates all real work to the pre-existing inline monolith `execute_inline_query_rag_remainder`. Four of the five nodes built in this phase are referenced only from test files."
    artifacts:
      - path: "engine/src/main.rs"
        issue: "Lines 1716-1717: `WorkflowRunner::new()` + exactly one `add_node(ReformulateQueryNode::new())`. `grep -c add_node src/main.rs` = 1. Lines 1738-1748 hand control to `execute_inline_query_rag_remainder` (defined 1234-1537), the unchanged monolithic path."
      - path: "engine/src/workflow/nodes/graph_context.rs"
        issue: "ExtractGraphContextNode constructed only in engine/src/tests.rs and engine/src/tests/workflow_phase5.rs. Zero production call sites."
      - path: "engine/src/workflow/nodes/retrieve.rs"
        issue: "RetrieveHybridNode — test-only construction. Zero production call sites. The D-07 cross-variant RRF and D-08 single variant-zero embedding contracts (05-02 truths 2 and 4) are therefore unreachable in production."
      - path: "engine/src/workflow/nodes/assemble_prompt.rs"
        issue: "AssemblePromptNode — test-only construction. 05-03 truth 1 ('The expanded runner replaces the prompt/generation inline remainder with AssemblePrompt and GenerateAnswer nodes') is false for the production runner."
      - path: "engine/src/workflow/nodes/generate.rs"
        issue: "GenerateAnswerNode — test-only construction. Its retry logic (lines 62-85) is unreachable in production."
      - path: "engine/src/workflow/runner.rs"
        issue: "The `variants.len() <= 8` admission step (lines 185-201, 240-256) and the D-03 zero-evidence short-circuit in `run_workflow` (173-178) execute only for runners the tests build. 05-02 truth 1 is not satisfied on the production path."
      - path: "engine/src/workflow/mod.rs"
        issue: "`run_inline_prompt_generation_remainder` (line 143) — the bridge that DOES emit per-node events and retry — is called only from engine/src/tests.rs (3 sites). Production uses main.rs's sink-less variant instead."
    missing:
      - "Register ExtractGraphContextNode, RetrieveHybridNode, AssemblePromptNode, GenerateAnswerNode on the production runner in main.rs::query_rag."
      - "Construct WorkflowDependencies from the real embedder / graph / dense / bm25 / reranker / generator adapters (currently built at main.rs:1719 with all seven fields None and never read)."
      - "Retire or reduce `execute_inline_query_rag_remainder` once the nodes carry the work."
  - truth: "SC2 — Workflow events (node started, chunk generated, completed) stream from Rust to Go to Client."
    status: failed
    reason: "The Rust→Go→SSE transport is genuinely and completely built. The producer is not: production emits lifecycle events for one no-op node only, and the `chunk generated` event never fires at all on the production path."
    artifacts:
      - path: "engine/src/main.rs"
        issue: "`execute_inline_query_rag_remainder` signature (1234-1239) takes `ctx`, `query_request`, `cancel` — no `WorkflowEventSink`. The closure at 1738 binds the sink as `_sink` and discards it. The real work is structurally incapable of emitting any event: no NodeStarted/NodeCompleted for graph, retrieve, prompt or generate."
      - path: "engine/src/workflow/events.rs"
        issue: "`answer_chunk` (line 88) has exactly three call sites: runner.rs:143 (guarded by `name == \"GenerateAnswer\"`, a node never registered in production) and workflow/mod.rs:193 and :214 (inside the test-only bridge). No production path can emit AnswerChunk. 05-03 truth 4's 'exactly one AnswerChunk' becomes exactly zero in production."
    missing:
      - "Thread the WorkflowEventSink through the real retrieval/prompt/generation work so node_started/node_completed fire per real node."
      - "Emit AnswerChunk on the production generation path."
  - truth: "SC3 — Node timeouts and retries handle failure scenarios predictably."
    status: failed
    reason: "The timeout machinery is applied to exactly one node — a no-op that pushes a String into a Vec and cannot hang — while every real I/O call (embedding, graph traversal, dense retrieval, BM25, rerank, prompt packing, LLM generation) runs unbounded. Production has no retry and no working cancellation."
    artifacts:
      - path: "engine/src/main.rs"
        issue: "EngineSettings (lines 172-179) declares only grpc_addr, lancedb_path, retrieval, graph. There is NO `workflow` field and no `deny_unknown_fields`, so the `[engine.workflow]` block (7 keys) in config/config.toml, config.example.toml and config.verify.toml is silently discarded by serde. `grep -rn 'reformulate_timeout_ms|generation_node_timeout_ms' --include=*.rs --include=*.go` over the repo returns ZERO hits — the keys are dead. 05-06 truth 4's explicit 5+15+10+2+65=97s budget arithmetic binds nothing shipped."
      - path: "engine/src/workflow/runner.rs"
        issue: "`with_timeouts` (line 84) is invoked from test files only (0 non-test call sites). `run_node` wraps `node.run()` in `timeout(...)` (line 131) but `run_tracer` awaits `remainder_bridge` bare (line 263) — no deadline on the real work. `grep -c 'timeout('` over main.rs lines 1234-1756 = 0."
      - path: "engine/src/workflow/nodes/graph_context.rs"
        issue: "`ExtractGraphContextNode::with_timeouts` (line 33) — the 4000ms graph-operation deadline nested inside the 15000ms backstop that 05-02 truth 3 requires — has zero non-test call sites."
      - path: "engine/src/main.rs"
        issue: "Production generation at line 1422 is a single `self.generator.generate(gen_req).await` with no retry. The D-12 single-retry contract lives in generate.rs:62-85 and mod.rs:184-188, both unreachable from production. 05-03 truth 3 (65s outer deadline around at most two 30s attempts) is unbacked in production."
      - path: "engine/src/main.rs"
        issue: "The CancellationToken created at line 1706 is never cancelled: `grep -rn 'cancel\\.cancel()'` over non-test src returns 0 hits, and there is no Drop guard tied to the response stream. The Go side does propagate disconnect (`a.engine.QueryRAG(r.Context(), req)`, gateway/main.go:697), but Rust never converts stream teardown into token cancellation, so the spawned task continues making paid LLM calls. 05-01 truth 4 and 05-03 truth 6 are not met in production; corroborates 05-REVIEW CR-04."
    missing:
      - "Add a `workflow` field to EngineSettings (plus `deny_unknown_fields` so dead config blocks fail loudly) and pass the parsed values to WorkflowRunner::with_timeouts in main.rs."
      - "Place every real I/O node under a node timeout (either by registering the nodes, or by bounding the remainder)."
      - "Wire a cancellation trigger to stream/receiver drop so client disconnect terminates the workflow."
  - truth: "SC4 — Snapshots of the workflow state can be captured for debugging."
    status: partial
    reason: "The capture-and-persist mechanism is fully built and wired end-to-end. The captured payload is hollow twice over: the snapshot serializer omits most of WorkflowContext by construction, and the three retrieval fields it does serialize are never populated by the production path."
    artifacts:
      - path: "engine/src/workflow/events.rs"
        issue: "`checkpoint()` (lines 101-122) serializes only session_id, trace_id, original_query, variants, vector_results, bm25_results, final_candidates. It OMITS graph_context, evidence_blocks, assembled_prompt, answer, citations, answer_basis, structured_citations, notices and snapshot. The 'full accumulated WorkflowContext' claimed by 05-03 truth 7, 05-04 truth 5 and 05-05 truth 5 is not what is serialized — this gap exists even on the library path the tests exercise."
      - path: "engine/src/main.rs"
        issue: "`grep -n 'ctx\\.(final_candidates|vector_results|bm25_results|evidence_blocks|variants)' src/main.rs` returns NOTHING. The production remainder sets only ctx.assembled_prompt, answer, citations, answer_basis, structured_citations, notices, snapshot. Every production checkpoint therefore records `vector_results: []`, `bm25_results: []`, `final_candidates: []` — the retrieval state a debugger would need is absent."
      - path: "gateway/main.go"
        issue: "Line 766 calls `a.dispatcher.Submit(env)` and discards the DispatchResult. checkpoint_sink.go:168-186 returns DispatchPending once the 1-slot channel and 4-slot overflow are full; that pending envelope is dropped with no retry and no log, contradicting 05-05 truth 4's 'reports an owned pending envelope instead of dropping an accepted record'. Corroborates 05-REVIEW CR-08."
    missing:
      - "Extend `events::checkpoint` to serialize the full WorkflowContext (graph_context, evidence_blocks, assembled_prompt, answer, citations, answer_basis, structured_citations, notices, snapshot)."
      - "Populate ctx.vector_results / bm25_results / final_candidates / evidence_blocks on the production path (falls out of closing SC1)."
      - "Handle DispatchPending in gateway/main.go rather than discarding it."
  - truth: "Plan traceability — every SUMMARY closes the requirement IDs its PLAN declared."
    status: failed
    reason: "Two summaries close requirement IDs that do not match their plan, and one closes IDs that do not exist in REQUIREMENTS.md at all."
    artifacts:
      - path: ".planning/phases/05-state-machine-workflow-events/05-03-SUMMARY.md"
        issue: "Declares `requirements-completed: [GEN-01, GEN-02, GEN-03, EVENT-03]`. Its PLAN declares `[ORCH-01, ORCH-02, ORCH-03]`, and none of GEN-01/GEN-02/GEN-03/EVENT-03 exist in .planning/REQUIREMENTS.md (grep returns zero hits)."
      - path: ".planning/phases/05-state-machine-workflow-events/05-02-SUMMARY.md"
        issue: "Declares `requirements-completed: [ORCH-03, RAG-01, RAG-02]` while its PLAN declares `[ORCH-01, ORCH-03, ORCH-05]`."
      - path: ".planning/phases/05-state-machine-workflow-events/05-06-SUMMARY.md"
        issue: "Claims it 'configured [engine.workflow] timeout overlays'. Only TOML was written; no code reads it."
      - path: ".planning/phases/05-state-machine-workflow-events/05-03-SUMMARY.md"
        issue: "Claims it 'Wired fixed 5-node workflow runner pipeline'. The production runner registers one node."
    missing:
      - "Correct the requirements-completed fields to the IDs the plans declared."
      - "Correct the two overclaiming SUMMARY narratives."
deferred: []
post_fix_regression_checks: # NOT open questions — each failure below is already proven statically. These are the runtime checks that should go GREEN once the gaps close.
  - test: "Start engine + gateway against config/config.toml, POST a real query to /rag/query, capture the raw SSE frame sequence."
    expected_after_fix: "node_started/node_completed for ReformulateQuery, ExtractGraphContext, RetrieveHybrid, AssemblePrompt, GenerateAnswer; at least one answer_chunk; then final_answer and workflow_completed."
    proven_current_behavior: "node_started(ReformulateQuery), node_completed(ReformulateQuery), final_answer, workflow_completed — no answer_chunk. Proven by the sink-less remainder signature (main.rs:1234-1239) and the answer_chunk call-site enumeration."
  - test: "SELECT context_snapshot FROM workflow_checkpoints ORDER BY created_at DESC LIMIT 5 after a real query."
    expected_after_fix: "Rows carry populated vector_results / bm25_results / final_candidates plus the rest of WorkflowContext."
    proven_current_behavior: "Rows exist and persist correctly, but those three arrays are always empty and nine other context fields are never serialized at all."
  - test: "Apply config/config.verify.toml (generation_node_timeout_ms = 7000) and query a deliberately slow provider."
    expected_after_fix: "Workflow fails with NodeErrorKind::Timeout at ~7s."
    proven_current_behavior: "The request runs to the provider's own timeout; [engine.workflow] is unread by serde (EngineSettings has no workflow field; zero symbol matches repo-wide)."
  - test: "Issue a query and disconnect the HTTP client mid-stream; watch engine logs and provider spend."
    expected_after_fix: "The workflow terminates promptly on disconnect."
    proven_current_behavior: "Go cancels the gRPC context, but Rust never calls cancel.cancel() (zero non-test sites) and holds no drop guard, so the spawned task runs to completion and the LLM call is paid for."
---

# Phase 5: State Machine & Workflow Events — Verification Report

**Phase Goal (User Story):** As a Lancet engineer, I want to formalize RAG orchestration into a Rust state machine, so that I can debug and extend the pipeline with predictable failure handling.
**Mode:** mvp
**Verified:** 2026-08-13
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## User Flow Coverage (MVP Mode)

The outcome clause — *"so that I can debug and extend the pipeline with predictable failure handling"* — is the success condition. Each step below is what the engineer would actually do.

| # | Step in the user story | Expected | Evidence in codebase | Status |
|---|------------------------|----------|----------------------|--------|
| 1 | Engineer reads the production request path and sees the RAG pipeline expressed as named states | `query_rag` registers the five nodes in D-06 order and the runner drives them | `engine/src/main.rs:1716-1717` registers ONE node; `1738-1748` delegates to `execute_inline_query_rag_remainder` (`engine/src/main.rs:1234-1537`), the pre-existing monolith. `grep -c add_node src/main.rs` = 1 | ✗ FAILED |
| 2 | Engineer watches a live query and sees each stage start and finish | SSE frames `node_started`/`node_completed` per real stage | Only ReformulateQuery emits them. The remainder takes no sink (signature `engine/src/main.rs:1234-1239`); the closure binds `_sink` and drops it (`:1738`) | ✗ FAILED |
| 3 | Engineer watches the answer arrive incrementally | `answer_chunk` SSE frames | `events::answer_chunk` call sites: `runner.rs:143` (gated on the never-registered GenerateAnswer node), `workflow/mod.rs:193`, `:214` (test-only bridge). Zero production emissions | ✗ FAILED |
| 4 | Engineer inspects a stored snapshot to debug a bad answer | `workflow_checkpoints` row with real retrieval state | Rows persist (`gateway/main.go:1014-1015` → `PostgresCheckpointSink` → sqlc `InsertWorkflowCheckpoint`), but the serializer omits 9 of 17 context fields and the 3 retrieval arrays it does emit are always `[]` | ⚠️ HOLLOW |
| 5 | Engineer tunes a node deadline in config and observes a predictable timeout | `[engine.workflow]` keys take effect | `EngineSettings` (`engine/src/main.rs:172-179`) has no `workflow` field and no `deny_unknown_fields`; the 7 config keys match zero `.rs`/`.go` symbols | ✗ FAILED |
| 6 | Engineer relies on a retry to absorb a transient LLM failure | One retry on retryable generation errors | Production: single `self.generator.generate(...)` at `engine/src/main.rs:1422`. Retry logic exists in `nodes/generate.rs:62-85` and `workflow/mod.rs:184-188`, both unreachable from production | ✗ FAILED |
| 7 | Engineer adds a new stage by implementing `Node` and registering it | Node trait + runner accept a new stage | `engine/src/workflow/node.rs` trait + `runner.rs:100` `add_node` are real and usable — extension is genuinely enabled *at the library level* | ✓ VERIFIED |
| 8 | Engineer swaps in a real query reformulator later (999.3) | `QueryReformulator` port + registered pass-through | `ports.rs:7-13` defines the trait; `ReformulateQueryNode` is registered in production and passes through (`reformulate.rs:44-49`) | ✓ VERIFIED |

**Flow verdict:** the *extend* half of the outcome clause is delivered (steps 7-8). The *debug* and *predictable failure handling* halves are not (steps 1-6). The flow is incomplete, so the sections below record detail rather than certifying the phase.

---

## Goal Achievement

### Observable Truths — Tier 1: ROADMAP Success Criteria (the contract)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | RAG pipeline is formalized into a defined state machine | ✗ FAILED | Library-only. `main.rs:1716-1717` registers 1 of 5 nodes; real work runs in `execute_inline_query_rag_remainder`. The 4 other nodes appear only in `src/tests.rs` and `src/tests/workflow_phase5.rs` |
| 2 | Workflow events (node started, chunk generated, completed) stream Rust → Go → Client | ✗ FAILED (transport half VERIFIED) | Go SSE relay and full event switch present and wired (`gateway/main.go:757-827`); producer emits lifecycle for one no-op node and never emits AnswerChunk |
| 3 | Node timeouts and retries handle failure scenarios predictably | ✗ FAILED | `with_timeouts` = 0 non-test call sites; `[engine.workflow]` unread by serde; `timeout(` count in the production query path (main.rs 1234-1756) = 0; no retry; `cancel.cancel()` = 0 non-test sites |
| 4 | Snapshots of the workflow state can be captured for debugging | ⚠️ PARTIAL (mechanism VERIFIED, payload HOLLOW) | Checkpoint events emitted and persisted to PostgreSQL end-to-end; the serializer omits 9 context fields and the 3 retrieval arrays are never populated in production |
| 5 | QueryReformulator trait defined with pass-through node in state machine (Port for 999.3) | ✓ VERIFIED | `ports.rs:7-13` trait; `ReformulateQueryNode` implements `Node`, registered at `main.rs:1717`, passes through at `reformulate.rs:47-49` |

**Tier 1 score:** 1/5 verified.

### Observable Truths — Tier 2: PLAN `must_haves.truths` (additive, cannot reduce scope)

Non-`[FLAGGED ASSUMPTION]` truths merged from all seven plans; those that merely restate a roadmap SC are folded into it.

| Plan | Truth (abridged) | Status | Evidence |
|------|------------------|--------|----------|
| 05-01 | Pre-stream ReceiveQuery validation before the stream opens | ✓ VERIFIED | `main.rs:1662-1701` validates session_id UUIDv4 and builds `QueryRequest` (returning `Status::invalid_argument`) before `mpsc::channel` at 1703 |
| 05-01 | Typed NodeStarted/NodeCompleted/AnswerChunk/NodeFailed/Checkpoint/WorkflowCompleted events with trace_id = correlation ID, no fabricated answer on failure | ⚠️ PARTIAL | All six types defined (`events.rs`) and trace_id = `correlation_id` (`main.rs:1711`). `emit_terminal_once` sends no response on failure (runner.rs:294-302) — D-13 honoured. But AnswerChunk is unreachable in production → folded into SC2 gap |
| 05-01 | Successful terminal preserves the complete QueryRAGResponse contract | ✓ VERIFIED | `WorkflowContext::to_query_rag_response` (mod.rs:74-84) maps all seven fields; production populates them at `main.rs:1529-1534`; Go `toQueryRAGResponseDTO` relays them |
| 05-01 | Cancellation is cooperative at the runner boundary, no task or receiver left alive | ✗ FAILED | Token never cancelled; spawned task outlives the dropped receiver → folded into SC3 gap |
| 05-01 | Every accepted checkpoint uses an explicit reliable/pending contract; bounded drop-only try_send is not acceptable | ✗ FAILED | Rust side is exactly the prohibited shape: `runner.rs:47` `let _ = self.tx.try_send(Ok(wf_event));` — checkpoints and all other events are dropped silently when the 100-slot channel fills. Go side returns DispatchPending but the caller discards it → folded into SC4 gap |
| 05-02 | Post-Reformulate `variants.len() <= 8` admission before any retrieval work; ExtractGraphContext before RetrieveHybrid per D-06 | ⚠️ LIBRARY-ONLY | Implemented at `runner.rs:185-201` / `240-256`; unreachable in production (one node registered) → folded into SC1 gap |
| 05-02 | QueryReformulator injectable pass-through with ordered variants; single variant-zero embedding per D-08 reused by retrieval; BM25 across every variant per D-07 | ⚠️ LIBRARY-ONLY | Present in `ports.rs`, `graph_context.rs`, `retrieve.rs`; production does its own embedding at `main.rs:1244` and single-query BM25 at `1312` → folded into SC1 gap |
| 05-02 | Graph 4000ms operation deadline strictly inside the 15000ms backstop; degradation to empty context per D-09 | ⚠️ LIBRARY-ONLY | `ExtractGraphContextNode::with_timeouts` (graph_context.rs:33) has 0 non-test call sites; production calls `attempt_graph_augmentation` (main.rs:1271) with the pre-existing graph settings → folded into SC3 gap |
| 05-02 | Retrieval/reranker error maps to RetrievalFailed and is distinct from zero evidence (D-03) | ✓ VERIFIED | Production preserves this: retrieval/rerank errors → `NodeErrorKind::RetrievalFailed` (main.rs:1304, 1316, 1330, 1341); empty candidates → NO_EVIDENCE notice + `Ok(())` (main.rs:1351-1389) |
| 05-03 | Runner replaces the inline remainder with AssemblePrompt + GenerateAnswer nodes | ✗ FAILED | Explicitly false for the production runner → SC1 gap |
| 05-03 | 65s outer generation deadline around at most two 30s attempts; immediate byte-identical retry | ⚠️ LIBRARY-ONLY | `generate.rs:60-85` snapshots the request and retries; `runner.rs:80` holds the 65s default. Production: one call, no deadline → SC3 gap |
| 05-03 | Exactly one AnswerChunk and one FinalAnswer on success; exhausted failure emits LlmGenerationFailed and no answer-shaped event | ⚠️ PARTIAL | Failure half VERIFIED (`main.rs:1422-1429` maps to LlmGenerationFailed; `emit_terminal_once` sends no response). Success half FAILED — zero AnswerChunks in production → SC2 gap |
| 05-03 / 05-04 / 05-05 | Every checkpoint serializes the **full** accumulated WorkflowContext | ✗ FAILED (even in the library) | `events.rs:106-115` serializes 7 of 17 fields; graph_context, evidence_blocks, assembled_prompt, answer, citations, answer_basis, structured_citations, notices and snapshot are never included → SC4 gap |
| 05-05 | `workflow_checkpoints` has exactly six columns with a `(trace_id, sequence_ordinal, created_at)` non-unique index; Go-generated UUID-string PK; JSONB snapshot | ✓ VERIFIED | `gateway/db/schema.sql:45-56` — id varchar PK, trace_id, sequence_ordinal int, node_name, context_snapshot jsonb, created_at + the exact index |
| 05-05 | Persistence detached from Recv/SSE; a blocked sink cannot delay FinalAnswer or fail the query | ✓ VERIFIED | `writeWorkflowEventSSE` submits and returns early (`gateway/main.go:763-768`); the dispatcher drains on its own goroutine with `context.Background()` |
| 05-05 | SSE data contains no checkpoint payload or raw context_snapshot JSON | ✓ VERIFIED | Checkpoint events `return` before the SSE switch (`gateway/main.go:768`); no `checkpoint` case in the event type switch |
| 05-05 | No Rust database client, no TTL cleanup, no fetch API, no serial checkpoint key | ✓ VERIFIED | No pg/sqlx/diesel dependency in `engine/Cargo.toml`; no postgres symbol in `engine/src`; PK is a varchar UUID |
| 05-06 | `/rag/query` is SSE-only, prefetches the first frame before HTTP 200, flushes incrementally, maps disconnect to gRPC cancellation, no JSON fallback | ✓ VERIFIED (Go side) | `gateway/main.go:697-733`: `QueryRAG(r.Context(), ...)`, `stream.Recv()` before `WriteHeader(200)`, `rc.Flush()` per frame, no JSON branch. (Rust's failure to act on the cancelled context is recorded under SC3.) |
| 05-06 | The global chi 60-second timeout cannot terminate `/rag/query` | ✓ VERIFIED | `middleware.Timeout(60*time.Second)` is applied in the group at `gateway/main.go:465-466`; `/rag/query` is registered in a separate group at `471-473` with no timeout middleware |
| 05-06 | Explicit 5+15(10+4)+10+2+65 = 97s node budget arithmetic, `generation_node_timeout_ms` distinct from the 30s per-attempt provider timeout | ✗ FAILED | The arithmetic exists only as TOML comments and Rust defaults; the config is never read → SC3 gap |
| 05-06 | Dispatcher drains primary-1 into owned overflow, reports a pending envelope instead of dropping, drains on close | ⚠️ PARTIAL | Dispatcher implements it correctly (`checkpoint_sink.go:147-205`, `Close` drains). The **caller** discards the DispatchPending result (`gateway/main.go:766`), so the accepted-record guarantee is lost at the seam → SC4 gap |
| 05-06 | One trace_id across every event and persisted checkpoint; SSE headers expose session/correlation identity | ✓ VERIFIED | `main.rs:1711` single correlation_id into the sink; `NewCheckpointEnvelopeFromEvent` reads `ev.GetTraceId()`; headers set at `gateway/main.go:713-718` |
| 05-07 | `NODE_ERROR_KIND_INPUT_VALIDATION = 9` appended, prior nine variants unchanged; generated Rust/Go bindings expose it | ✓ VERIFIED | `NodeErrorKind::InputValidation` is constructed at `runner.rs:186` and `241`; proto RPCs unchanged otherwise (`QueryGraph` still unary at `proto/lancet/v1/lancet.proto:12`) |

**Tier 2 score:** 5 fully verified (05-01 validation, 05-01 response contract, 05-02 retrieval-error taxonomy, 05-05 schema/detachment/SSE-hygiene/no-Rust-DB, 05-06 route topology/identity/proto) out of 14 non-duplicative plan truths. Every Tier-2 failure maps into an existing SC gap; none opens a new remediation area beyond the checkpoint-serializer omission, which is folded into the SC4 gap.

### Prohibitions (must-NOT checks)

All 15 prohibitions across the seven plans carry `status: unverified, flagged: true` and declare **no `verification:` tier**, so they are treated as judgment-tier. Per ADR-550 D4 the verdicts below are **NON-AUTHORITATIVE LLM-judge assessments** — `unverified-prohibition — human review recommended`. None is silently absorbed into a pass.

| # | Plan | Prohibition | Non-authoritative verdict | Evidence |
|---|------|-------------|---------------------------|----------|
| P1 | 05-01 | Stream must not expose raw provider token streaming or a JSON fallback transport | Did NOT happen | `gateway/main.go:757-827` emits typed SSE DTOs only; no JSON fallback branch; production emits no AnswerChunk at all, so no raw token path exists |
| P2 | 05-01 | Rust must not open PostgreSQL connections; QueryGraph's standalone API unchanged | Did NOT happen | No pg/sqlx/diesel in `engine/Cargo.toml`; no postgres symbol in `engine/src`; `rpc QueryGraph(...) returns (QueryGraphResponse)` still unary |
| P3 | 05-02 | Retrieval node must not hard-index variant zero for every source or silently discard non-finite scores | Did NOT happen *in the library* | `retrieve.rs` uses variant-0 for dense (per D-08) and iterates all variants for BM25. **Moot in production** — the node never runs |
| P4 | 05-02 | Standalone QueryGraph API must not be changed for this workflow node | Did NOT happen | Proto RPC unchanged; `query_graph` handler untouched by the workflow module |
| P5 | 05-03 | Generation node must not fabricate an answer, alter the retry request, emit raw provider chunks, or retry a non-generation node | Did NOT happen | `generate.rs:60-63,82` reuses a byte-identical `request_snapshot`; `emit_terminal_once` sends no response on failure; retry exists only inside GenerateAnswer |
| P6 | 05-03 | Prompt assembly must not omit graph/retrieval fields from the accumulated snapshot, or convert generation failure to success | **DID HAPPEN (omission half)** | `events.rs:106-115` omits `graph_context`, `evidence_blocks`, `assembled_prompt` and nine other fields from the checkpoint snapshot. The failure→success half did not happen |
| P7 | 05-04 | Tests must not use live provider/network timing or treat a skipped test as coverage | Did NOT happen | `tests/workflow_phase5.rs` uses `tokio::time::pause/advance` and `Fake*` ports; registration guards present |
| P8 | 05-04 | Matrix must not conflate zero evidence, graph degradation, retrieval failure, timeout, cancellation, exhausted generation | Did NOT happen | Distinct `NodeErrorKind` variants asserted per case |
| P9 | 05-05 | Checkpoint JSON must not be serialized into client SSE data or exposed via a fetch endpoint | Did NOT happen | Early `return` at `gateway/main.go:768`; no checkpoint case in the SSE switch; no fetch route |
| P10 | 05-05 | Rust must not own PostgreSQL; no serial sequencing or shared-schema claimant fixtures | Did NOT happen | Same evidence as P2; `id` is a varchar UUID, `main_test.go:2640` uses per-test isolated schemas |
| P11 | 05-06 | Gateway must not buffer the whole workflow, expose a JSON fallback, or let `/rag/query` inherit the 60s timeout | Did NOT happen | Frame-by-frame `rc.Flush()`; separate route group without `middleware.Timeout` |
| P12 | 05-06 | Go relay must not reinterpret Rust node semantics or expose provider secrets | Did NOT happen | The switch passes `node_name`, `error_kind` and payloads through opaquely; no secret fields in any DTO |
| P13 | 05-07 | Do not renumber/rename/remove the nine existing NodeErrorKind variants | Did NOT happen | Variant 9 appended; 0-8 intact |
| P14 | 05-07 | Do not hand-edit generated pb files | Cannot be verified statically | `engine/src/pb/mod.rs` was hand-restored per the 05-07 SUMMARY, but that file is module glue, not a buf output. Flagged for human review |
| P15 | 05-07 | Do not modify engine/src/workflow/*, gateway/main.go, gateway/main_test.go in plan 05-07 | Cannot be verified statically | Requires per-commit diff attribution. Flagged for human review |

**One prohibition (P6) appears violated and two (P14, P15) cannot be verified statically. All 15 remain flagged for human confirmation.**

### Deferred Items

None. `gsd` deferral check run against the milestone roadmap: Phase 6 (`Observability, Evaluation & Polish`; requirements RAG-03, OBS-01..04) covers OpenTelemetry, an offline eval script, README, and DEBT closure. It contains **no** success criterion about wiring workflow nodes into the request path. "Wire the state machine into production" is Phase 05's own goal and cannot be deferred to it.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `proto/lancet/v1/lancet.proto` | Server-streaming QueryRAG + typed event envelope | ✓ VERIFIED | All seven event messages generated and consumed on both sides |
| `engine/src/workflow/node.rs` | Node trait, context, ports, error contract | ✓ VERIFIED | 71 lines, trait implemented by all 5 nodes |
| `engine/src/workflow/events.rs` | Typed lifecycle/failure/terminal/checkpoint values | ⚠️ HOLLOW payload | 138 lines; `checkpoint()` serializes 7 of 17 context fields |
| `engine/src/workflow/runner.rs` | Cancellable runner, timeouts, terminal ownership | ⚠️ ORPHANED capabilities | `run_workflow` (the true 5-node driver) is never reached in production; `with_timeouts` never called outside tests |
| `engine/src/workflow/nodes/reformulate.rs` | Pass-through reformulation node | ✓ VERIFIED | Registered in production |
| `engine/src/workflow/nodes/graph_context.rs` | Graph context node | ⚠️ ORPHANED | Test-only construction |
| `engine/src/workflow/nodes/retrieve.rs` | Hybrid retrieval node | ⚠️ ORPHANED | Test-only construction |
| `engine/src/workflow/nodes/assemble_prompt.rs` | Prompt assembly node | ⚠️ ORPHANED | Test-only construction |
| `engine/src/workflow/nodes/generate.rs` | Generation node with retry | ⚠️ ORPHANED | Test-only construction; its retry is dead in production |
| `engine/src/workflow/ports.rs` | QueryReformulator + retrieval/graph ports | ✓ VERIFIED (trait), ℹ️ INFO | 362 lines, ~300 of which are `Fake*` test doubles with no `#[cfg(test)]` gate |
| `engine/src/main.rs` | Pre-stream validation + runner wiring | ⚠️ PARTIAL | Validation (1662-1701) is real and correct; runner wiring registers 1 node |
| `gateway/main.go` | gRPC stream → SSE relay | ✓ VERIFIED | Full event switch, correct SSE framing, identity headers, incremental flush, no inherited timeout |
| `gateway/checkpoint_sink.go` | Checkpoint dispatcher + PostgreSQL sink | ✓ VERIFIED (drop caveat at the caller) | 247 lines; wired at `main.go:1014-1015` and injected into `app` |
| `gateway/db/schema.sql` | `workflow_checkpoints` table + ordering index | ✓ VERIFIED | Lines 45-56 match the 05-05 column and index contract exactly |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `main.rs::query_rag` | `WorkflowRunner` | `add_node` × 5 | ✗ NOT_WIRED | Exactly one `add_node` call |
| `WorkflowRunner` | real retrieval/graph/prompt/generation | Node trait dispatch | ✗ NOT_WIRED | Bypassed via `remainder_bridge` |
| `WorkflowEventSink` | real work | sink passed into remainder | ✗ NOT_WIRED | Remainder has no sink parameter; closure discards `_sink` |
| `WorkflowDependencies` | real adapters | field injection | ✗ NOT_WIRED | Constructed with all seven fields `None` at main.rs:1719 and never read |
| `config [engine.workflow]` | `WorkflowRunner::with_timeouts` | serde → EngineSettings | ✗ NOT_WIRED | No `workflow` field on EngineSettings; zero symbol matches |
| Client disconnect | Rust `CancellationToken` | drop guard / `cancel()` | ✗ NOT_WIRED | Go propagates via `r.Context()`; Rust has zero `cancel.cancel()` sites and no drop guard |
| Rust `WorkflowEvent` stream | Go SSE frames | `writeWorkflowEventSSE` | ✓ WIRED | `gateway/main.go:757-827` |
| Checkpoint event | `workflow_checkpoints` table | dispatcher → `PostgresCheckpointSink` → sqlc | ✓ WIRED | `gateway/main.go:766`, `1014-1015`; `checkpoint_sink.go` |
| `QueryReformulator` trait | production pass-through | `ReformulateQueryNode` | ✓ WIRED | `main.rs:1717` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `events.rs::checkpoint` | `context.final_candidates` | never assigned on production path | No | ✗ HOLLOW |
| `events.rs::checkpoint` | `context.vector_results` | never assigned on production path | No | ✗ HOLLOW |
| `events.rs::checkpoint` | `context.bm25_results` | never assigned on production path | No | ✗ HOLLOW |
| `events.rs::checkpoint` | `context.variants` | `ReformulateQueryNode` fallback push | Yes, but always `[original_query]` | ⚠️ STATIC |
| `events.rs::checkpoint` | `graph_context`, `answer`, `notices`, `snapshot`, … | not serialized at all | N/A | ✗ DISCONNECTED |
| `emit_terminal_once` → `to_query_rag_response` | `answer`, `citations`, `snapshot`, `notices` | `execute_inline_query_rag_remainder` (1529-1534) | Yes | ✓ FLOWING |
| `gateway` SSE `final_answer` | `toQueryRAGResponseDTO` | Rust FinalAnswer event | Yes | ✓ FLOWING |

The final-answer contract survives the refactor intact — that part is genuinely delivered. The *debugging* payload does not.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Production registers all 5 nodes | `grep -c 'add_node' engine/src/main.rs` | `1` | ✗ FAIL |
| Timeouts configured in production | `grep -rn 'with_timeouts(' --include=*.rs src/ \| grep -v src/tests \| grep -v 'pub fn'` | `0` | ✗ FAIL |
| Remainder can emit events | `sed -n '1234,1240p' engine/src/main.rs \| grep -c sink` | `0` | ✗ FAIL |
| Any deadline on the real work | `sed -n '1234,1756p' engine/src/main.rs \| grep -c 'timeout('` | `0` | ✗ FAIL |
| Cancellation is ever triggered | `grep -rn 'cancel\.cancel()' --include=*.rs src/ \| grep -v src/tests` | `0` | ✗ FAIL |
| Config keys read anywhere | `grep -rn 'reformulate_timeout_ms\|generation_node_timeout_ms' --include=*.rs --include=*.go .` | `0` | ✗ FAIL |
| Rust opens no PostgreSQL connection | `grep -rniE 'pgx\|postgres\|sqlx\|diesel' engine/Cargo.toml engine/src` | `0` | ✓ PASS |
| Go SSE emits every event type | `grep -n 'eventType = ' gateway/main.go` | 6 types mapped | ✓ PASS |
| Checkpoint sink wired at startup | `grep -n 'NewPostgresCheckpointSink\|NewCheckpointDispatcher' gateway/main.go` | `1014`, `1015` | ✓ PASS |
| `/rag/query` escapes the 60s middleware | `grep -n 'middleware.Timeout\|/rag/query' gateway/main.go` | timeout at `466` (other group), route at `473` | ✓ PASS |
| `workflow_checkpoints` schema shape | `sed -n '45,57p' gateway/db/schema.sql` | 6 columns + exact index | ✓ PASS |
| Live SSE frame sequence | requires running engine + gateway + provider | — | ? deferred to post-fix regression checks |

### Probe Execution

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| — | `find scripts -path '*/tests/probe-*.sh'` | none found; no PLAN or SUMMARY declares a probe | N/A — not applicable to this phase |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|----------------|-------------|--------|----------|
| ORCH-01 | 05-01, 05-02, 05-06 | Lightweight Rust state machine for the fixed RAG path (query → reformulate → retrieve → graph → prompt → answer → complete/failed) | ✗ BLOCKED | Built as a library; production path registers 1 node and runs the monolith (`main.rs:1716-1748`) |
| ORCH-02 | 05-01, 05-03, 05-04, 05-05, 05-06, 05-07 | Emit client-facing workflow events (node started/completed/failed, answer chunks, final answer, completed) | ✗ BLOCKED (partial) | Wire contract + Go SSE relay delivered; production emits one node's lifecycle and never an AnswerChunk |
| ORCH-03 | 05-01, 05-02, 05-03, 05-04, 05-06 | Cancellation, timeouts, and retry/fallback for node execution | ✗ BLOCKED | Implemented in the library; zero production reachability (timeouts, retry and cancellation all unwired) |
| ORCH-04 | 05-05, 05-06 | Lightweight checkpoints/snapshots for workflow state during development and debugging | ⚠️ PARTIAL | Full Rust→Go→PostgreSQL persistence path wired and working; captured payload omits 9 context fields and carries no retrieval state |
| ORCH-05 | 05-01, 05-02 | Dedicated `reformulate` stage defaulting to pass-through, clean slot for 999.3 | ✓ SATISFIED | `QueryReformulator` trait (`ports.rs:7-13`), `ReformulateQueryNode` registered in production, pass-through behaviour at `reformulate.rs:47-49` |

**Orphaned requirements:** none — all five ORCH IDs mapped to this phase are claimed by at least one plan. Traceability defects in the SUMMARYs are recorded as a separate gap in the frontmatter.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `engine/src/workflow/mod.rs` | 143-222 | `run_inline_prompt_generation_remainder` — a second, divergent remainder used only by tests, whose behaviour (events + retry) differs from the production remainder it stands in for | 🛑 Blocker | The mechanism by which the suite stays green while production is unwired |
| `engine/src/main.rs` | 1719 | `WorkflowDependencies::new()` built with all seven port fields `None`, passed to `run_tracer`, never read | ⚠️ Warning | The dependency-injection seam is decoration; corroborates 05-REVIEW IN-04 |
| `engine/src/workflow/runner.rs` | 47 | `let _ = self.tx.try_send(Ok(wf_event));` | ⚠️ Warning | Every event, including checkpoints and the terminal event, is dropped silently on a full channel — the exact shape 05-01's must-have forbids; corroborates 05-REVIEW CR-05 |
| `engine/src/workflow/ports.rs` | 66-362 | ~300 lines of `Fake*` port doubles with no `#[cfg(test)]` gate | ⚠️ Warning | Test scaffolding compiled into the shipped binary |
| `engine/src/workflow/mod.rs` | 186-188 | Retry fires on *every* error class with no non-retryable guard (unlike `generate.rs:73-76`) | ℹ️ Info | Test-only path; corroborates 05-REVIEW WR-05 |
| `gateway/main.go` | 766 | `a.dispatcher.Submit(env)` return value discarded | ⚠️ Warning | `DispatchPending` checkpoints silently lost; corroborates 05-REVIEW CR-08 |
| `engine/src/workflow/runner.rs` | 142-146 | `answer_chunk` emission coupled to a hardcoded node-name string comparison | ℹ️ Info | Stringly-typed dispatch; corroborates 05-REVIEW IN-01 |
| `engine/src/workflow/ports.rs` | 15-35 | `NoOpQueryReformulator` is defined and re-exported but never instantiated anywhere | ℹ️ Info | Dead code — production's pass-through comes from the `else if` fallback in `reformulate.rs:47`, not from this type. Does not affect SC5 |
| all phase files | — | `grep -rn 'TBD\|FIXME\|XXX'` over `engine/src/workflow/`, `engine/src/main.rs`, `engine/src/prompt.rs`, `engine/src/generation/openrouter.rs`, `gateway/main.go`, `gateway/checkpoint_sink.go` | ✓ clean | No unreferenced debt markers |

### Why the green test suite is not evidence

The 177 Rust lib/bin tests, 9 integration tests, and the passing Go gateway suite were examined rather than trusted:

- The phase-5 orchestration tests (`engine/src/tests/workflow_phase5.rs`, `engine/src/tests.rs:7100-7830`) construct their **own** `WorkflowRunner`, call `add_node` for all five nodes themselves, inject `Fake*` ports, and bridge through `workflow::run_inline_prompt_generation_remainder`. Production constructs a different runner with one node and bridges through `LancetServiceImpl::execute_inline_query_rag_remainder`. **The two bridges are different functions with different behaviour** — the test one emits events and retries; the production one does neither.
- The one test that drives the production handler end-to-end, `query_rag_tracer` (`engine/src/tests.rs:2381-2470`), asserts only that the stream contains *at least one* NodeStarted, *at least one* NodeCompleted, *at least one* Checkpoint, and a WorkflowCompleted. All four are satisfied by the single no-op ReformulateQuery node. It never asserts an AnswerChunk, never asserts a node name, and never asserts the node count.
- The paused-clock timeout proofs in 05-04 call `WorkflowRunner::new().with_timeouts(...)` directly (`tests/workflow_phase5.rs:331, 397`; `tests.rs:7580`). Production never calls `with_timeouts`, so those proofs bind nothing shipped.

The suite proves the library is correct. It proves nothing about the request path.

### Corroboration of 05-REVIEW.md

| Review finding | Verdict | Note |
|----------------|---------|------|
| CR-01 `[engine.workflow]` entirely unwired | **CORROBORATED** | Independently confirmed via EngineSettings source + zero-hit symbol grep across `.rs` and `.go` |
| CR-02 production registers one node; real work has no timeout | **CORROBORATED** | Independently confirmed at `main.rs:1716-1748`; also found the stronger sink-discard consequence |
| CR-04 client disconnect does not cancel | **CORROBORATED** | Zero `cancel.cancel()` sites, no drop guard; Go side does propagate, Rust ignores it |
| CR-05 event delivery failures silently discarded | **CORROBORATED** | `runner.rs:47` `let _ = self.tx.try_send(...)` |
| CR-08 checkpoints dropped under load | **CORROBORATED** | `DispatchPending` returned at `checkpoint_sink.go:185`, discarded at `main.go:766` |
| WR-02 `retryable` hardcoded `false` | **CORROBORATED** | Every `events::node_failed` call site passes `false` |
| WR-03 sequence ordinals skip a value per checkpoint | **CORROBORATED** | `run_node` calls `next_sequence_ordinal()` and then `send_event` increments again (`runner.rs:145-146`) |
| IN-01 stringly-typed node dispatch | **CORROBORATED** | `runner.rs:104-113`, `142`, `173`, `185` |
| IN-04 `WorkflowDependencies` unused | **CORROBORATED** | `main.rs:1719`, all fields `None` |
| CR-03, CR-06, CR-07 | **NOT INDEPENDENTLY RE-VERIFIED** | Outside the five success criteria; the review's own evidence stands unchallenged |

### Post-Fix Regression Checks (not open questions)

Four runtime checks are listed in the frontmatter under `post_fix_regression_checks`. Each failure they describe is **already proven statically** — they are not uncertainty. They are the checks that should turn green once the gaps close: SSE frame sequence, checkpoint payload contents, timeout-config effectiveness, and disconnect behaviour. Each entry records both the expected post-fix result and the proven current behaviour, so a closure plan can use them directly as acceptance criteria.

### Gaps Summary

Phase 5 built a competent RAG state machine and then did not connect it to the product.

Every artifact the plans promised exists, is substantive, and is unit-tested: a `Node` trait, five node implementations, a runner with per-node deadlines and cooperative cancellation, a full typed event envelope, a Go SSE relay, and PostgreSQL-backed checkpoint persistence. Several of these are genuinely wired end-to-end and work: the Go transport (SSE-only route, first-frame prefetch, incremental flush, exempt from the 60s middleware), the checkpoint persistence path (correct six-column schema, detached dispatcher, no checkpoint data leaking into SSE, no Rust database client), the pre-stream request validation, and the preserved `QueryRAGResponse` contract.

The break is at one seam: `engine/src/main.rs:1716-1748`. Production builds a `WorkflowRunner`, registers a single no-op pass-through node, and hands the entire RAG pipeline to `execute_inline_query_rag_remainder` — the same monolithic function that existed before this phase, unchanged in structure and taking no event sink. Everything downstream follows from that one decision:

- **SC1** fails because four of five states never execute as states; the D-06 ordering, the `variants <= 8` admission gate, the D-07 cross-variant RRF and the D-08 single-embedding contract are all library behaviour with no production reachability.
- **SC2** fails because the function doing the work cannot emit events; `AnswerChunk` has zero reachable production call sites.
- **SC3** fails because `timeout()` guards exactly one node — one that pushes a `String` into a `Vec` and cannot hang — while embedding, graph traversal, dense retrieval, BM25, rerank, prompt packing and the LLM call all run unbounded, unretried and uncancellable. The `[engine.workflow]` block written to control them is discarded by serde before it reaches any code.
- **SC4** is half-delivered: the capture-and-persist plumbing is real, but the serializer emits 7 of 17 context fields and the three retrieval arrays it does emit are never populated — so nothing in `workflow_checkpoints` can answer a debugging question about retrieval. Notably this serializer omission is a genuine defect *even on the library path the tests exercise*, independent of the wiring failure.
- **SC5** genuinely passes on its own terms.

Measured against the user story's outcome clause — *"so that I can debug and extend the pipeline with predictable failure handling"* — the **extend** half is delivered (the trait and runner make adding a stage easy) and the **debug** and **predictable failure handling** halves are not. An engineer today sees one node's lifecycle in the SSE stream, no answer chunks, near-empty snapshots, deadlines that ignore configuration, and a workflow that keeps spending money after the client hangs up.

The remediation is concentrated rather than sprawling: register the four nodes on the production runner, build `WorkflowDependencies` from the real adapters instead of `None`, add a `workflow` field to `EngineSettings` (with `deny_unknown_fields` so a dead config block fails loudly next time), extend `events::checkpoint` to the full context, replace the drop-only `try_send` with the reliable/pending contract 05-01 required, and attach a cancellation trigger to stream drop. Closing SC1 that way closes most of SC2, SC3 and SC4 as a consequence.

---

_Verified: 2026-08-13_
_Verifier: Claude (gsd-verifier)_
