# Phase 05 Traceability Errata and Multi-Source Coverage

**Status:** Canonical Additive Traceability Record  
**Applies To:** Phase 05 State Machine Workflow Events (`05-01 through 05-07`)

---

## 1. Historical Requirement List Corrections

The following canonical corrections resolve requirement-list discrepancies between historical `PLAN.md` declarations and `SUMMARY.md` artifacts:

### Plan 05-02 Correction
- **Original Plan Declaration:** ORCH-01, ORCH-03, ORCH-05
- **Canonical Completed Requirements:**
  ```yaml
  requirements-completed: [ORCH-01, ORCH-03, ORCH-05]
  ```
- **Correction Note:** Plan 05-02 implemented graph augmentation ordering, multi-variant RRF fusion, and the `QueryReformulator` pass-through port.

### Plan 05-03 Correction
- **Original Plan Declaration:** ORCH-01, ORCH-02, ORCH-03
- **Canonical Completed Requirements:**
  ```yaml
  requirements-completed: [ORCH-01, ORCH-02, ORCH-03]
  ```
- **Correction Note:** Plan 05-03 implemented prompt assembly cancellation and generation single-retry logic within the workflow library.

---

## 2. Truthful Baseline Narrative Corrections

### Plan 05-03 Narrative Correction
- **Historical Claim:** Implied production five-node state machine query reachability.
- **Truthful Baseline Narrative:** State machine library structures and deterministic tests were implemented, but `LancetServiceImpl.query_rag` retained its legacy inline remainder until Plan 05-08 established production five-node reachability and real adapter wiring.

### Plan 05-06 Narrative Correction
- **Historical Claim:** Implied live runtime consumption of workflow timeout configuration overlays.
- **Truthful Baseline Narrative:** TOML configuration overlays (`config.toml`, `config.example.toml`, `config.verify.toml`) were authored and structurally verified, but the engine configuration parser and live runtime consumers remained to be wired in subsequent gap closure work (Plan 05-09).

---

## 3. Evidence Timing and Timeout Contract

The Phase 05 validation architecture establishes a strict distinction between evidence classes:
- **Semantic Test Evidence:** fast sub-second in-process deterministic tests using fake ports or paused virtual Tokio time prove semantic behavior (state transitions, lifecycle pairing, error classification, cancellation tokens, snapshot schemas, and boundary invariants).
- **Live Runtime Timeout Evidence:** The committed `config/config.verify.toml` setting `generation_node_timeout_ms = 7000` is verified through a live runtime timeout check executing against real configuration overlays and running engine harnesses. The provider attempt budget `openrouter.generation_timeout_secs = 30` outlasts the 7000ms node budget.

---

## 4. Frozen Historical Baseline Preservation

The executed artifacts `05-01 through 05-07` remain frozen historical records. Their pre-revision HEAD hashes are verified against working-tree blobs:

| Path | Frozen HEAD blob |
|---|---|
| `.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md` | `e3c47b65b844cb31e71cc1bde1e1b820d5c39dca` |
| `.planning/phases/05-state-machine-workflow-events/05-01-SUMMARY.md` | `c61ad716a1ad51c4d97d9ecfc88d454f47be6032` |
| `.planning/phases/05-state-machine-workflow-events/05-02-PLAN.md` | `9b6df6d4f0710b7e584ee00d3bccc0123dcf1b00` |
| `.planning/phases/05-state-machine-workflow-events/05-02-SUMMARY.md` | `4f0903fb097e6a6e4f17065dca4f0312dcb2df1b` |
| `.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md` | `ef4fb5f4b4f710413c6bf6dd21f823d1895769bf` |
| `.planning/phases/05-state-machine-workflow-events/05-03-SUMMARY.md` | `3fc8f104544b8df8118c3f1f45d2eb5c4bc3c98c` |
| `.planning/phases/05-state-machine-workflow-events/05-04-PLAN.md` | `9b654e6adbcc9b2be319e2ad1fb064f61f93f36c` |
| `.planning/phases/05-state-machine-workflow-events/05-04-SUMMARY.md` | `bbbb48dd2e5d58e4bc301c52f1fb76539796f6dc` |
| `.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md` | `6348461a98fffc00d4de450570ea87d804326ede` |
| `.planning/phases/05-state-machine-workflow-events/05-05-SUMMARY.md` | `a6881efb1021a4fff6203b5d41198bc236f8b894` |
| `.planning/phases/05-state-machine-workflow-events/05-06-PLAN.md` | `be228f3a36ddab2625611db392c1ae9d6c2cab37` |
| `.planning/phases/05-state-machine-workflow-events/05-06-SUMMARY.md` | `322bca1dbc14b5cebbcebeb9f99bdba9d66b7f44` |
| `.planning/phases/05-state-machine-workflow-events/05-07-PLAN.md` | `d026bbf9ae9fc29febcfd0230982ff6f68e07910` |
| `.planning/phases/05-state-machine-workflow-events/05-07-SUMMARY.md` | `b7bdad3e680f6a0473680ceab7548269ec3e5d0c` |

Verification rules:
- Assert working blob hash matches pre-revision HEAD hash for each path.
- Check `git diff --cached --name-only` and unstaged diffs for zero frozen-path modifications.
- Execute `git diff --check` to verify no whitespace errors.

---

## 5. Multi-Source Coverage Matrix (GOAL, REQ, RESEARCH, CONTEXT)

| Source Category | Item / Identifier | Scope & Requirement Mapping | Executable Closure Plans |
|---|---|---|---|
| **GOAL** | Phase 05 User Story | Formalize RAG pipeline into a Rust state machine with predictable lifecycle events, timeouts, and error handling | 05-08, 05-09, 05-10, 05-11, 05-13, 05-14, 05-15, 05-16 |
| **REQ** | ORCH-01 | Five-node state machine workflow: ReformulateQuery, ExtractGraphContext, RetrieveHybrid, AssemblePrompt, GenerateAnswer | 05-08, 05-10, 05-14 |
| **REQ** | ORCH-02 | Client-facing lifecycle events (NodeStarted, NodeCompleted, NodeFailed, AnswerChunk, FinalAnswer, WorkflowCompleted) | 05-08, 05-10, 05-11, 05-13, 05-19 |
| **REQ** | ORCH-03 | Cancellation tokens, node timeout budgets, and generation single-retry logic | 05-08, 05-09, 05-10, 05-13, 05-20 |
| **REQ** | ORCH-04 | Lossless accumulated checkpoint snapshots persisted to PostgreSQL via detached Go dispatcher | 05-08, 05-10, 05-11 |
| **REQ** | ORCH-05 | QueryReformulator pass-through port supporting multi-variant candidate generation | 05-08, 05-12, 05-24 |
| **RESEARCH** | R-01 to R-14 | Native Tokio runner, injectable port architecture, D-06 graph-first ordering, RRF fusion, graph degradation with `GRAPH_TIMEOUT`, stream error handling, schema isolation, and ASVS L1 boundary controls | 05-08 through 05-24 |
| **CONTEXT** | D-01 to D-10 | Event ordering, progress events, zero-evidence short-circuiting, pre-stream validation, graph degradation, variant-zero embedding, untouched standalone `QueryGraph` RPC | 05-08, 05-09, 05-10, 05-16, 05-24 |
| **CONTEXT** | D-11 to D-15 | Retry scoped strictly to GenerateAnswer, exactly 1 byte-identical retry, honest failure on exhaustion, no backup model, no intermediate retrying event | 05-10, 05-13 |
| **CONTEXT** | D-16 to D-22 | Connection-drop cancellation, per-node timeouts, server-streaming gRPC, SSE-only HTTP route, coarse events, no SSE resume, typed `NodeErrorKind` with `stream_error` codes | 05-08, 05-09, 05-10, 05-11, 05-14, 05-17 |
| **CONTEXT** | D-23 to D-29 | PostgreSQL checkpoint durability, D-24 indefinite retention, no fetch API, Go-owned DB connection, detached writes, full snapshots, `trace_id` reuse | 05-10, 05-11 |
| **CONTEXT** | D-30 to D-31 | Scope fences excluding token counting metadata and per-node OpenTelemetry spans from Phase 05 | 05-08, 05-10, 05-13 |

---

## 6. Review Finding and Gap Disposition Matrix

| Finding ID | Domain / Issue | Owning Plans & Tasks | Resolution Disposition |
|---|---|---|---|
| **SC1 / CR-02** | Inline remainder reachability | 05-08, 05-22 | 05-08 wires production five-node runner in `main.rs`; 05-22 retires `execute_inline_query_rag_remainder`. |
| **SC2 / CR-05** | Production event sink delivery | 05-08, 05-10, 05-11 | 05-08 streams live events; 05-10 enforces single ordinal sequencing and non-blocking delivery; 05-11 validates gateway SSE. |
| **SC3 / CR-01** | Workflow configuration wiring | 05-09 | Parse, validate, and apply all seven `[engine.workflow]` configuration parameters. |
| **SC4 / WR-08** | Incomplete snapshot provenance | 05-08, 05-10, 05-16, 05-21 | 05-08 captures graph facts and retrieval snapshots; 05-16 populates complete snapshot provenance; 05-21 enforces typed fusion provenance. |
| **WR-01 / WR-03** | Nine-variant validation & ordinals | 05-10 | Enforce validation before node completion; assign each sequence ordinal once. |
| **WR-02 / WR-04** | Generation retry classification | 05-10, 05-13 | 05-13 classifies OpenRouter preflight/retry errors; 05-10 reflects typed retryability in workflow events. |
| **WR-06 / WR-07** | Graph degradation & notices | 05-08, 05-16, 05-19 | Populate `GRAPH_TIMEOUT` notices on graph timeouts; deduplicate notices in 05-16; render notices in terminal responses in 05-19. |
| **WR-10 / WR-11** | Test port isolation | 05-15, 05-18 | Gate fake ports and generator test doubles behind `#[cfg(test)]` without breaking binary test seams. |
| **HIGH-01** | Protobuf module glue preservation | 05-17 | Retain hand-written `engine/src/pb/mod.rs` glue across `buf generate` invocations. |
| **HIGH-02** | Typed graph-carrier ownership | 05-08 | `GraphQueryPort` returns `Vec<GraphFactBlock>`, populated onto `WorkflowContext`. |
| **HIGH-04A/B** | BM25 index snapshot concurrency | 05-16, 05-18 | Production retrieval clones an immutable `Arc<Bm25Index>` snapshot; migrate all 18 test fixture constructions in 05-18. |
| **WARNING-01** | Binary vs library test target split | 05-09, 05-18 | Split production integration tests into binary targets and fake-port tests into library modules. |
| **WARNING-03** | Snapshot payload size budget | 05-10 | Full logical snapshot preserved per D-24/D-28; embedding vector represented by compact digest. |
| **BLOCKER-05** | HTTP disconnect propagation | 05-11 | Real `httptest.NewServer` disconnect cancellation tests verify Rust workflow cancellation and terminal event suppression. |
| **CR-06 / CR-07** | Gateway error visibility | 05-11 | Guard against nil responses and emit observable terminal `stream_error` events. |
| **LOW-5** | ROADMAP.md wave updates | Deferred | Plan frontmatter remains authoritative execution order. |

---

## 7. Plan Execution Sequence (Waves 7–18)

- **Wave 7:** 05-08 (Production Five-Node Runner & Adapters), 05-12 (Additive Traceability Errata)
- **Wave 8:** 05-09 (Workflow Timeouts & Cancellation Drops), 05-17 (Protobuf Wire Compatibility & Glue Preservation)
- **Wave 9:** 05-13 (OpenRouter Model Metadata Cache & Retry Classification), 05-23 (Rust Wire Contract & Literal Repair)
- **Wave 10:** 05-18 (Target Split & BM25 Fixture Migration)
- **Wave 11:** 05-14 (NodeKind Exhaustive Dispatch), 05-15 (Test Double Isolation)
- **Wave 12:** 05-16 (BM25 O(1) Snapshots & Retrieval Provenance)
- **Wave 13:** 05-21 (Typed Fusion Provenance)
- **Wave 14:** 05-24 (Two-Pass Multi-Variant RRF Fusion)
- **Wave 15:** 05-10 (Event Sequencer, Retry Classification & Checkpoint Digests)
- **Wave 16:** 05-19 (Terminal Notice Serialization & Error Formatting)
- **Wave 17:** 05-20 (Node Preparation & Wall-Clock Timing Assertions), 05-22 (Retire Inline Remainder)
- **Wave 18:** 05-11 (Gateway SSE Streaming, Disconnect Cancellation & PostgreSQL Checkpoints)
