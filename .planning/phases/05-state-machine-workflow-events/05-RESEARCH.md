# Phase 5: State Machine & Workflow Events - Research

**Researched:** 2026-08-10
**Domain:** Rust async orchestration (hand-rolled state machine) + Go gRPC-to-SSE gateway rewrite + PostgreSQL checkpoint schema
**Confidence:** HIGH (Rust engine side, verified against live code) / MEDIUM (Go gateway side, net-new pattern in this codebase, verified against live code but no precedent to compare against) / LOW-MEDIUM (general Go SSE idioms, web-sourced)

> **Relationship to `05-AI-SPEC.md`:** That file is the authoritative, already-locked design contract for the Rust `Node`/`WorkflowRunner` pattern, versions, imports, pitfalls, and evaluation strategy — read it first, this document does not restate it. This RESEARCH.md's job is (a) verifying the AI-SPEC's code citations against the actual current source (several were unverified from a different session), and (b) covering what the AI-SPEC leaves thin: the Go gateway rewrite (D-18/D-19), the proto shape, the PostgreSQL checkpoint schema/migration mechanics, the config sub-second-timeout gap, and one concrete resolution recommendation for the AI-SPEC's flagged open design question (dimension 4, graph-timeout vs. D-09).

## Summary

This phase has two structurally different halves. The **Rust half** (engine/) is additive and low-risk: the `query_rag` handler's existing linear pipeline is already decomposed into clearly separable stages with `Arc<dyn Trait>`-injected ports for `Generator` and `EmbeddingProvider` (both already have deterministic test doubles — `FakeGenerator` exists today). Wrapping this in a `Node`/`WorkflowRunner` state machine is primarily new module scaffolding around code that already works, verified directly at `engine/src/main.rs:1346-1708`.

The **Go half** (gateway/) is the higher-risk, more novel half. `QueryRAG` today is a plain unary gRPC call proxied to a JSON HTTP response (`gateway/main.go:280-715`) — this phase converts it to consume a server-streaming gRPC response and forward it as SSE, a pattern with **zero existing precedent** in this codebase (the only existing streaming RPC, `IngestDocument`, is client-streaming, not server-streaming — verified: `proto/lancet/v1/lancet.proto:9`). Three concrete risks were found here that the AI-SPEC does not cover: (1) the global chi `middleware.Timeout(60*time.Second)` applied to *all* routes (`gateway/main.go:464`) will silently kill the SSE stream before `GenerateAnswer`'s ~65s node-level budget can ever complete — this must be resolved per-route, not left as-is; (2) 14+ existing test call sites in `gateway/main_test.go` assert the old unary-JSON `QueryRAGResponse` shape and must be rewritten, not just extended; (3) the PostgreSQL checkpoint table needs a net-new Atlas HCL schema entry + sqlc query, following the existing `documents`/`document_reconciliation_intents` pattern, with no `jsonb` column precedent yet in this repo to copy from.

One AI-SPEC-flagged open question (dimension 4: does `ExtractGraphContext`'s 15s *timeout* fail the query or degrade it, per D-09) has a concrete resolution recommendation below, grounded in the fact that the existing `attempt_graph_augmentation` function (`main.rs:1056-1236`) is **already infallible by construction** — it returns an outcome enum (`Succeeded`/`NoMatchFound`/`AttemptedAndFailed`), never a `Result`/`Err`, to its caller. The natural, minimal-surprise design is to keep that property: give `ExtractGraphContextNode` its own inner timeout race and fold a timeout into a new `AttemptedAndFailed`-shaped degrade path, so the node's `Node::run` always returns `Ok(())` to the runner — never triggering the runner's uniform `Err → NodeFailed → WorkflowCompleted(failed)` propagation for this node specifically.

**Primary recommendation:** Build the Rust `Node`/`WorkflowRunner` scaffold exactly as specified in `05-AI-SPEC.md` Section 3–4; treat the Go gateway rewrite as the phase's real engineering risk and budget a dedicated plan/wave for it (proto codegen → Go stream-consume-and-forward-as-SSE → checkpoint persistence → full test-suite rewrite), not a trailing afterthought to the Rust work.

## User Constraints (from CONTEXT.md)

### Locked Decisions
See `.planning/phases/05-state-machine-workflow-events/05-CONTEXT.md` `<decisions>` (D-01 through D-31) — copied in full below for planner convenience; treat as authoritative, do not re-derive.

**Answer Delivery & Streaming Model:** D-01 (progress events, not token streaming — `AnswerChunk` fires exactly once with the full validated answer), D-02 (keep `AnswerChunk`/`FinalAnswer` as distinct event types for forward compatibility), D-03 (zero-evidence early return skips straight `RetrieveHybrid → Complete`, a valid success not a failure).

**State Machine Boundary & Validation Contract:** D-04 (`ReceiveQuery` — session/correlation ID mint + validation — stays synchronous in the tonic handler, before the stream opens; state machine starts at `ReformulateQuery`), D-05 (once the stream is open, all failures report in-band: `NodeFailed` → `WorkflowCompleted(failed)`, SSE closes normally, still HTTP 200).

**Pipeline Order & Node Behavior:** D-06 (graph augmentation runs *before* hybrid retrieval — supersedes the plan doc's node order), D-07 (`RetrieveHybrid` RRF-merges across `QueryReformulator` variants, not hard-indexed `[0]`), D-08 (query embedding embeds only variant `[0]` in v1 — NoOp reformulator makes this behaviorally identical to today), D-09 (`ExtractGraphContext` always runs; success is not required — "mandatory" means always-runs, not always-required), D-10 (`QueryGraph` RPC stays untouched, separate from this state machine).

**Retry, Fallback & Cancellation:** D-11 (retry scoped to generation node only), D-12 (exactly 1 retry, no backoff, byte-identical replay), D-13 (both attempts failing → `Failed`, no fabricated answer), D-14 (no backup model/provider — descoped, not deferred), D-15 (no "retrying" event — client sees nothing until final outcome), D-16 (cancellation = native connection-close propagation, no new RPC), D-17 (per-node timeouts: `ReformulateQuery` 5s, `HybridRetrieval` 10s, `GraphExtraction` 15s, `PromptAssembly` 2s, `LLMGeneration` 30s per-attempt).

**Streaming Transport:** D-18 (`QueryRAG` unary → server-streaming `WorkflowEvent` stream), D-19 (`/rag/query` becomes SSE-only, no content-negotiated fallback), D-20 (coarse event granularity — one `NodeStarted`/`NodeCompleted`-or-`NodeFailed` pair per node, no sub-step events), D-21 (no SSE reconnect/resume support).

**Error Visibility:** D-22 (`NodeFailed` carries typed category from taxonomy: `InputValidation`, `RetrievalFailed`, `GraphQueryFailed`, `PromptAssemblyFailed`, `LlmGenerationFailed`, `Timeout`, `Cancelled`, `Internal`, plus human-readable message).

**Checkpointing (ORCH-04):** D-23 (PostgreSQL-backed, durable, queryable — extends 04.1 D-33's accepted-risk/no-redaction framing to checkpoint payloads), D-24 (no TTL/retention cleanup in v1), D-25 (no fetch API — direct DB inspection only), D-26 (Rust does NOT get its own Postgres connection — sends checkpoint payloads to Go over the streaming gRPC connection, Go's existing Postgres connection persists them), D-27 (fire-and-forget — checkpoint writes never block/stall the query), D-28 (full accumulated snapshot per checkpoint, not incremental diff).

**Identity:** D-29 (`trace_id` reuses the existing per-request `correlation_id`, no new identifier).

**Observability Scope (deferred to Phase 6):** D-30 (workflow metadata — token counts, node counts, `degraded_mode` — not added this phase), D-31 (per-node tracing spans not added this phase).

### Claude's Discretion
- Exact Rust module/file layout for the `Node` trait, `WorkflowRunner`, and event types.
- Internal error type names and exact configuration key names for the new timeout/retry/checkpoint knobs (follow the existing TOML+env override convention).
- Exact `WorkflowEvent` protobuf message shape (`oneof` vs. separate messages per event type) — must carry the event types and payloads decided in D-01–D-31.
- Exact SSE framing details (event ID scheme, `retry:` field presence) beyond "no resume support" (D-21).

### Deferred Ideas (OUT OF SCOPE)
- **Workflow metadata collection** and **per-node tracing spans** — Phase 6's OpenTelemetry/observability work (OBS-01). See D-30/D-31.
- **`answer_basis: degraded/model_only` response contract and citation repair** — `DEBT-RAG-01`/`DEBT-RAG-03`, Phase 6's hardening target (RAG-03). Not touched by this phase's retry/fallback mechanism.
- **Real query-reformulation strategies** (HyDE, multi-query expansion) — Phase 999.3 backlog. This phase only builds the pass-through port and the `RetrieveHybrid` node shape that can consume it.
- **Descoped (not earmarked to any phase):** configured backup model/provider (D-14), SSE reconnect/resume (D-21), explicit `CancelQuery` RPC (D-16), checkpoint-fetch API/RPC (D-25).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ORCH-01 | Lightweight Rust state machine for the fixed RAG path | `Node`/`WorkflowRunner` pattern per AI-SPEC Section 3; verified refactor seams in `main.rs:1346-1708` below |
| ORCH-02 | Emit client-facing workflow events (started/completed/failed, chunks, final, completed) | Proto `oneof` shape recommendation below; Go SSE-forwarding pattern below |
| ORCH-03 | Cancellation, timeouts, retry/fallback behavior for node execution | AI-SPEC's `tokio::select!` pattern (verified sound); Go-side `r.Context().Done()` chain documented below; config sub-second-timeout gap flagged below |
| ORCH-04 | Lightweight checkpoints/snapshots for workflow state | Atlas HCL + sqlc schema/migration mechanics documented below (net-new pattern, no `jsonb` precedent) |
| ORCH-05 | `QueryReformulator` port, pass-through node, clean expansion slot | Confirmed net-new — no existing `QueryReformulator` in codebase; 999.3 D-02's trait shape documented below |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Fixed RAG state machine execution (node sequence, timeouts, retry) | API / Backend (Rust engine) | — | Owns all RAG/vector/graph semantics per established project boundary (Phase 2/3/04.1 convention); no client or gateway involvement in orchestration logic |
| Workflow event emission (`NodeStarted`/`Completed`/`Failed`/chunks) | API / Backend (Rust engine) | API / Backend (Go gateway, forwarding only) | Rust produces events; Go is a pure relay converting gRPC stream frames to SSE frames, no event semantics added or interpreted |
| SSE delivery to client | Frontend-facing Backend (Go gateway) | Browser / Client (SSE consumer) | Go owns the HTTP/SSE transport boundary per established "Go = thin HTTP/gRPC/Postgres boundary" convention; client-side is out of scope (no product-facing web UI per REQUIREMENTS.md Out of Scope) |
| Checkpoint persistence (Postgres write) | Database / Storage (via Go) | API / Backend (Go, as write executor) | D-26 explicitly assigns Postgres ownership to Go — Rust never opens its own Postgres connection, preserving "Go owns Postgres, Rust owns LanceDB" |
| Cancellation propagation (client disconnect → Rust node abort) | API / Backend (both tiers) | — | Spans both tiers: Go detects HTTP-level disconnect via `r.Context().Done()`, propagates through the gRPC stream context, Rust's `CancellationToken` fan-out observes it — a single logical chain crossing the tier boundary, not owned by either tier alone |
| `QueryReformulator` port (pass-through) | API / Backend (Rust engine) | — | Pure in-process Rust trait, no I/O boundary crossed; 999.3's future real strategies stay in this tier |

## Standard Stack

### Core (Rust — engine/)

| Library | Version (verified) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `tokio` | `~1.53` (already a dependency; add `time`, `sync` features explicitly) | Async runtime, timers, channels | Already the engine's runtime; `time`/`sync` features currently only present transitively — must be declared explicitly for D-16/D-17's first-class use |
| `tokio-util` | `~0.7` → registry current `0.7.19` `[VERIFIED: crates.io via cargo search]` | `CancellationToken` fan-out primitive | Net-new dependency for D-16. Default (empty) feature set is sufficient — `sync` module carries no feature gate; do not add `"full"` |
| `tokio-stream` | `~0.1` → registry current `0.1.19` `[VERIFIED: crates.io via cargo search]` | `ReceiverStream` wrapper for the server-streaming gRPC response | Net-new *direct* dependency (currently only pulled in transitively by tonic/tokio) — needed to wrap an `mpsc::Receiver` as the tonic response stream type |
| `tonic` / `tonic-prost` / `prost` | `~0.14` (already pinned) → registry current `0.14.6` `[VERIFIED: crates.io via cargo search]` | gRPC server, protobuf codegen | Already dependencies; no version bump needed — server-streaming codegen support already present in this version line |

### Supporting (Go — gateway/, already present, no new deps required)

| Library | Version (from go.mod, verified) | Purpose | When to Use |
|---------|---------|---------|-------------|
| `google.golang.org/grpc` | `v1.82.1` | gRPC client consuming the new server-streaming `QueryRAG` | Already used for all Go↔Rust calls; server-streaming client (`Recv()` loop) is new usage of an existing dependency, not a new package |
| `github.com/go-chi/chi/v5` | `v5.3.1` | HTTP router | Existing; **the global `middleware.Timeout(60*time.Second)` at `gateway/main.go:464` needs a route-specific override for `/rag/query`** — see Common Pitfalls |
| `github.com/jackc/pgx/v5` | `v5.10.0` | PostgreSQL driver | Existing; supports `jsonb` natively (`pgtype.JSONB`) even though no `jsonb` column exists in the schema yet — needed for the D-28 checkpoint payload column |
| `sqlc` | `v1.31.1` (from generated header comment in `gateway/db/query.sql.go`) | SQL-to-Go codegen | Existing convention (`gateway/sqlc.yaml`) — add checkpoint queries to `gateway/db/query.sql`, regenerate |
| Atlas (HCL schema) | — (schema-as-code, no version pin found in repo) | Postgres migration tool | Existing convention (`gateway/atlas.hcl`, `gateway/db/schema.hcl`) — add a `workflow_checkpoints` table block following the `documents`/`document_reconciliation_intents` pattern |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled `Node`/`WorkflowRunner` | `statig`/`rust-fsm` (macro-driven FSM crates) | Already ruled out in `05-AI-SPEC.md` Section 2 — branching-DSL overhead not needed for a fixed linear sequence; not re-litigated here |
| `mpsc::Sender::send().await` for checkpoint writes | `try_send` / detached `tokio::spawn` | AI-SPEC pitfall #4 already resolves this in favor of non-blocking send — confirmed correct given D-27's fire-and-forget requirement |
| chi's global `middleware.Timeout` left as-is | Per-route timeout (chi supports `r.With(middleware.Timeout(d)).Post(...)` per-route grouping) or exempting `/rag/query` from the blanket 60s and giving it its own longer/absent timeout | The global 60s timeout will fire before `GenerateAnswer`'s ~65s node budget completes even on the happy path — this is not optional to fix, see Common Pitfalls |
| JSON/text column for checkpoint payload | `jsonb` column (pgx/v5 supports it natively) | `jsonb` gives queryability (D-23's "durable and queryable" framing) without a redaction system; a plain `text` column defeats the "queryable" half of D-23's rationale |

**Installation:**
```toml
# engine/Cargo.toml — additions
tokio = { version = "~1.53", features = ["rt-multi-thread", "macros", "time", "sync"] }
tokio-util = "~0.7"
tokio-stream = "~0.1"
```
No new Go module dependencies — `grpc`, `pgx/v5`, `chi` are already present in `gateway/go.mod`; only new *usage* (server-streaming client, `jsonb` column type) of existing packages.

**Version verification:** Verified via `cargo search` against the live crates.io registry (2026-08-10): `tokio-util = "0.7.19"`, `tokio-stream = "0.1.19"`, `tonic = "0.14.6"` — all consistent with the `~` version ranges already used in this project's `Cargo.toml`.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `tokio-util` | crates.io | published 2018-02-01 (~8 yrs) | ~11.5M/week | github.com/tokio-rs/tokio | OK | Approved |
| `tokio-stream` | crates.io | published 2020-12-03 (~5.7 yrs) | ~7.2M/week | github.com/tokio-rs/tokio | OK | Approved |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none. Both are first-party `tokio-rs` org crates, high download volume, no postinstall scripts (N/A for Cargo — no build-script network/filesystem risk flagged).

Ran via `gsd-tools query package-legitimacy check --ecosystem crates tokio-util tokio-stream` — both returned `OK` with no reasons flagged. Cross-checked against crates.io directly via `cargo search` for current version numbers (see Standard Stack table).

## Architecture Patterns

### System Architecture Diagram

```
Client (SSE consumer, curl/browser EventSource)
  |
  | POST /rag/query  (HTTP, request body unchanged)
  v
Go Gateway (gateway/main.go)
  |  1. Same validation/DTO-decode as today (queryRAG handler, ~line 655)
  |  2. Opens gRPC server-streaming call: engine.QueryRAG(ctx, req) -> stream
  |  3. Sets response headers: Content-Type: text/event-stream, Cache-Control: no-cache
  |  4. Loop: stream.Recv() -> WorkflowEvent -> encode as SSE "data: {...}\n\n" -> Flush()
  |     - select on r.Context().Done() alongside Recv() to detect client disconnect
  |     - on WorkflowEvent carrying a checkpoint payload: fire-and-forget goroutine
  |       writes to Postgres (D-26/D-27) -- does NOT block the Recv()/Flush() loop
  v
Rust Engine (engine/src/main.rs query_rag handler + new workflow/ module)
  |  1. ReceiveQuery (D-04): session/correlation ID mint + validation -- SYNCHRONOUS,
  |     pre-stream. On failure: real gRPC Status/trailer (d1_status pattern), no stream opens.
  |  2. On success: open mpsc::channel<WorkflowEvent>, wrap as ReceiverStream, return as
  |     the tonic streaming Response; spawn WorkflowRunner::run against the fixed node Vec.
  v
WorkflowRunner (new: engine/src/workflow/runner.rs)
  |  For each node in [ReformulateQuery, RetrieveHybrid, ExtractGraphContext,
  |                     AssemblePrompt, GenerateAnswer]:
  |    tokio::select! { biased;
  |      _ = cancel.cancelled() => NodeFailed{Cancelled}
  |      res = timeout(node_timeout, node.run(&mut ctx, &cancel)) => ... }
  |    emit NodeStarted / NodeCompleted|NodeFailed via the mpsc::Sender (try_send, D-27)
  |    D-03: RetrieveHybrid empty -> short-circuit straight to Complete (no AssemblePrompt/Generate)
  v
Each Node wraps EXISTING pipeline logic (unchanged domain code, verified below):
  ReformulateQueryNode  -> QueryReformulator port (NEW trait, ORCH-05, NoOp default)
  RetrieveHybridNode    -> DenseRetriever + BM25 + fuse_candidates (existing, RRF across
                            reformulation variants per D-07)
  ExtractGraphContextNode -> attempt_graph_augmentation (existing, ALREADY infallible-by-
                            construction outcome enum -- see Common Pitfalls/Open Questions)
  AssemblePromptNode    -> pack_evidence_and_graph_prompt (existing, unchanged D-01)
  GenerateAnswerNode    -> generation::Generator::generate (existing, unchanged D-01),
                            owns the D-12 single-retry loop (call once, retry once on failure)
  |
  v
Checkpoint snapshot (D-28: full WorkflowContext snapshot, not diff) sent as part of the
same WorkflowEvent stream back through Go to Postgres (D-26)
```

### Recommended Project Structure
```
engine/src/
├── workflow/
│   ├── mod.rs           # WorkflowContext struct; public re-exports
│   ├── node.rs           # Node trait (BoxFuture-shaped, mirrors generation::Generator),
│   │                      # NodeError + NodeErrorKind (mirrors GenerationError/-Kind, D-22)
│   ├── runner.rs          # WorkflowRunner: select!-based timeout/cancel race, D-12 retry
│   ├── events.rs          # WorkflowEvent enum (mirrors proto oneof), checkpoint builder (D-28)
│   └── nodes/
│       ├── reformulate.rs
│       ├── retrieve.rs        # RRF-merge across reformulation variants (D-07) -- see Open
│       │                       # Questions for how this composes with existing fuse_candidates
│       ├── graph_context.rs   # wraps attempt_graph_augmentation; owns inner timeout race
│       │                       # to preserve D-09's "always runs, not required" for the
│       │                       # timeout sub-case too (see Common Pitfalls #1)
│       ├── assemble_prompt.rs
│       └── generate.rs        # wraps generation::Generator, owns D-12 retry loop
├── main.rs               # query_rag handler: ReceiveQuery boundary stays (D-04),
│                          # constructs WorkflowContext + WorkflowRunner, streams events
└── generation/            # UNCHANGED this phase (D-01)

gateway/
├── main.go                # queryRAG handler rewritten: gRPC stream consume -> SSE forward
├── db/
│   ├── schema.hcl          # + workflow_checkpoints table block (Atlas)
│   ├── query.sql           # + InsertWorkflowCheckpoint query (sqlc source)
│   └── query.sql.go        # regenerated by sqlc
proto/lancet/v1/
└── lancet.proto            # QueryRAG: unary -> server-streaming; + WorkflowEvent oneof message
```

### Pattern 1: Rust `Node`/`WorkflowRunner` (authoritative — see `05-AI-SPEC.md` Section 3)
Do not re-derive this pattern — `05-AI-SPEC.md`'s Entry Point Pattern, Key Abstractions table, and 5 documented pitfalls are the canonical source. This RESEARCH.md confirms the pattern's prerequisites hold in the live codebase:
- `BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>` already exists at `engine/src/generation/mod.rs:22` — the exact type `Node` should mirror. `[VERIFIED: engine/src/generation/mod.rs:22]`
- `Generator::generate` already wraps its one HTTP call in `tokio::time::timeout(self.config.timeout, self.execute_one_call(request))` **per attempt** (`engine/src/generation/openrouter.rs:626`), with `GENERATION_TIMEOUT = Duration::from_secs(30)` (`openrouter.rs:24`) — confirming the AI-SPEC's pitfall #3 arithmetic (30s is per-attempt, the node-level ~65s budget is a new, separate figure). `[VERIFIED: engine/src/generation/openrouter.rs:24,626]`
- `M-ERRORS-CANONICAL-STRUCTS` (`rust-guidelines.md:2966`) is already the house pattern in this codebase — `GenerationError { kind: GenerationErrorKind, message: String, session_id: Option<String>, correlation_id: Option<String> }` (`generation/mod.rs:404-423`) is the exact shape `NodeError`/`NodeErrorKind` (D-22's taxonomy) should mirror: an `ErrorKind` enum plus a struct carrying message + correlation identity, `Display` implemented, no `thiserror`/`anyhow` dependency present in `engine/Cargo.toml` (this is an application crate per `M-APP-ERROR`, so `anyhow`-style errors would also be permissible, but matching the existing `GenerationError` shape keeps the new `NodeError` consistent with the rest of the crate). `[VERIFIED: engine/src/generation/mod.rs:404-423, rust-guidelines.md M-ERRORS-CANONICAL-STRUCTS]`

```rust
// Mirrors generation::GenerationError/-Kind exactly (engine/src/generation/mod.rs:404-423)
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NodeErrorKind {
    InputValidation,
    RetrievalFailed,
    GraphQueryFailed,      // reserved for genuine node error paths, NOT timeout-as-degrade
    PromptAssemblyFailed,
    LlmGenerationFailed,
    Timeout,
    Cancelled,
    Internal,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeError {
    pub kind: NodeErrorKind,
    pub message: String,
    pub session_id: Option<String>,
    pub correlation_id: Option<String>,
}
```

### Pattern 2: Go gRPC-stream-to-SSE forwarding (net-new to this codebase)
`[CITED: general Go stdlib pattern, LOW-MEDIUM confidence — no official Go docs directly fetched this session, corroborated across multiple third-party sources]`

```go
// gateway/main.go — queryRAG handler, rewritten shape (illustrative)
func (a app) queryRAG(w http.ResponseWriter, r *http.Request) {
    // ... existing body decode/validation unchanged ...

    stream, err := a.engine.QueryRAGStream(r.Context(), req) // new gRPC server-streaming call
    if err != nil {
        // same trailerError pre-stream-open handling as today (D-04's boundary
        // is unchanged: a malformed request still gets a real 4xx before any
        // SSE framing begins)
        writeQueryRAGError(w, err)
        return
    }

    w.Header().Set("Content-Type", "text/event-stream")
    w.Header().Set("Cache-Control", "no-cache")
    w.Header().Set("Connection", "keep-alive")
    w.WriteHeader(http.StatusOK)
    flusher, ok := w.(http.Flusher)
    if !ok {
        http.Error(w, "streaming unsupported", http.StatusInternalServerError)
        return
    }

    for {
        select {
        case <-r.Context().Done():
            // client disconnected (or chi's route-specific timeout fired) --
            // returning here lets the deferred gRPC stream context cancel,
            // propagating to Rust's CancellationToken fan-out (D-16)
            return
        default:
        }
        event, err := stream.Recv()
        if err == io.EOF {
            return // WorkflowCompleted was the terminal frame; stream closed normally
        }
        if err != nil {
            // mid-stream transport error -- log; SSE has no standard "error frame"
            // beyond closing the connection (D-21: no reconnect/resume anyway)
            return
        }
        if cp := event.GetCheckpoint(); cp != nil {
            go a.persistCheckpoint(cp) // D-27: fire-and-forget, does not block the loop below
        }
        payload, _ := json.Marshal(toWorkflowEventDTO(event))
        fmt.Fprintf(w, "data: %s\n\n", payload)
        flusher.Flush()
    }
}
```

Key points this pattern must get right (not covered by the AI-SPEC, which is Rust-only):
1. **`r.Context().Done()` is the Go-side half of D-16's cancellation chain.** The AI-SPEC's pitfall #2 documents the Rust-side half (`mpsc::Sender::send` failure / `tx.closed()`). The full chain is: client closes SSE connection → `http.Server` cancels `r.Context()` → the `select` above returns → the deferred `stream.CloseSend()`/context cancellation on the gRPC client call propagates to the Rust server's stream context → Rust's `ReceiverStream`/`Sender` observes the drop. Both halves must be implemented for D-16 to actually work end-to-end; implementing only the Rust half (as AI-SPEC's pitfall #2 describes) is necessary but not sufficient.
2. **The route needs its own timeout, distinct from the global 60s.** See Common Pitfalls below — this is the single highest-priority Go-side finding.
3. **SSE has no standard mid-stream error frame.** A transport-level `stream.Recv()` error (not a `NodeFailed` WorkflowEvent, which is D-05's in-band success path) can only be represented by closing the connection — there's no protocol-level way to signal "gateway lost the gRPC stream mid-flight" to an EventSource client beyond disconnection. This is consistent with D-21 (no reconnect support) but worth being explicit about for the planner: this is a real (if narrow) failure mode with no in-band signal, distinct from D-05's "failures are in-band" guarantee, which only covers failures the *Rust engine itself* detects and reports as `NodeFailed`.

### Pattern 3: Atlas + sqlc checkpoint table (net-new, follows existing convention exactly)
`[VERIFIED: gateway/db/schema.hcl, gateway/sqlc.yaml, gateway/db/query.sql]`

```hcl
# gateway/db/schema.hcl -- new table, following the documents/
# document_reconciliation_intents pattern already in this file (verified above)
table "workflow_checkpoints" {
  schema = schema.public
  column "trace_id" {
    null = false
    type = varchar(255)   # = correlation_id, D-29 -- not a primary key alone,
                            # multiple checkpoint rows share one trace_id
  }
  column "node_name" {
    null = false
    type = varchar(100)
  }
  column "context_snapshot" {
    null = false
    type = jsonb            # D-28: full accumulated snapshot, not a diff --
                              # jsonb chosen over text for D-23's "queryable" requirement;
                              # pgx/v5 supports jsonb natively, no new Go dependency needed
  }
  column "created_at" {
    null    = false
    type    = timestamp
    default = sql("CURRENT_TIMESTAMP")
  }
  # No primary key on a single column -- (trace_id, node_name, created_at) composite,
  # or a surrogate serial/uuid id column -- Claude's Discretion, follow the `users` table's
  # serial-id precedent if a surrogate key is preferred.
}
```

### Anti-Patterns to Avoid
- **Wrapping the D-03 zero-evidence early return as a no-op node run.** D-03 is explicit: `AssemblePrompt`/`GenerateAnswer` never receive even a no-op `NodeStarted`. This must be runner-level short-circuit logic, not a node that immediately returns `Ok(())`.
- **Reusing `GENERATION_TIMEOUT` (30s) as the `GenerateAnswer` node's wall-clock budget.** Confirmed real bug risk (AI-SPEC pitfall #3, verified against live code above) — the node-level timeout needs its own, larger config value.
- **Treating `attempt_graph_augmentation`'s existing `AttemptedAndFailed` outcome as sufficient for the new timeout case.** That variant already exists for logical failures (table/query errors) but the function currently has **no internal timeout of its own** — a hang inside it (e.g. a slow LanceDB `nearest_to` query) would today just make `query_rag` slow, not fail. Wrapping it in the runner's outer `tokio::select!` timeout without also giving the node its own inner timeout+degrade path collapses a hang into a hard `NodeFailed`/`WorkflowCompleted(failed)`, contradicting D-09. See Common Pitfalls #1 and Open Questions.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cancellation fan-out to in-flight async work | A custom `Arc<AtomicBool>` + polling flag | `tokio_util::sync::CancellationToken` | Purpose-built, zero-feature-flag-overhead, already the AI-SPEC's locked choice |
| Distinguishing "ran out of time" from "client hung up" | A single `tokio::time::timeout()` call (returns the same `Elapsed` for both) | `tokio::select! { _ = cancel.cancelled() => ..., res = timeout(...) => ... }` | A bare `timeout()` cannot tell D-22's `Timeout` and `Cancelled` categories apart — this is exactly AI-SPEC pitfall #3's root cause if skipped |
| Generation retry/error classification | A generic `retry_n_times(fn, n)` helper applied uniformly | The existing `GenerationErrorKind`-scoped retry already implicit in `Generator::generate`'s error taxonomy — D-11 explicitly scopes retry to the generation node ONLY, a generic retry wrapper risks accidentally being reused elsewhere against D-11 |
| Deterministic test doubles for retry/timeout scenarios | New mocking framework or trait-object mocking library | `FakeGenerator` (`engine/src/generation/mod.rs:466-490`) already exists and exactly satisfies AI-SPEC's stated testability requirement ("inject a test double that ... fail[s] on the Nth call") for the `Generator` port — reuse directly, do not rebuild | Verified: `FakeGenerator::with_responses(Vec<Result<...>>)` + `call_count` atomic already gives exactly the scenario-5/6/7 fixture the eval strategy needs |

**Key insight:** Most of this phase's "don't hand-roll" risk is not about pulling in an external crate (there is deliberately none, per the locked AI-SPEC framework decision) — it's about *not re-deriving* patterns (error-struct shape, `BoxFuture` object-safety workaround, retry test doubles) that already exist correctly elsewhere in this exact codebase. The dominant efficient path is "mirror `generation/mod.rs`", not "invent something new."

## Runtime State Inventory

Not a rename/refactor/migration phase in the classic sense (no identifier renamed, no data relocated) — skipping the formal 5-category table. However, D-18/D-19 constitute an **API contract migration** (unary → streaming, JSON → SSE) with real blast radius, documented as a dedicated subsection because it is exactly the kind of "what still assumes the old shape" question that inventory exists to answer:

**Callers/tests asserting the old unary `QueryRAGResponse` JSON shape (must all be rewritten, not merely extended) `[VERIFIED: grep against gateway/main_test.go]`:**
- `gateway/main_test.go` — 14 distinct test functions construct a `queryRAG: func(...) (*pb.QueryRAGResponse, error)` fake and/or POST to `/rag/query` expecting a single synchronous JSON body (lines ~647-1218, plus the full end-to-end integration test at ~2120-2174 that spawns the real Rust engine binary and asserts a single decoded `QueryRAGResponse`).
- `gateway/main.go`'s `engine` interface (`QueryRAG(context.Context, *pb.QueryRAGRequest) (*pb.QueryRAGResponse, error)`, line 207) and `grpcEngine.QueryRAG` (lines 280-287) — both must change shape to a streaming client method; every implementer of the `engine` interface in tests (the `engineFunc` fake at `main_test.go:647-684`) must be updated in lockstep.
- The chi route registration itself (`main.go:468`) is unaffected in path/method, only in response Content-Type and the removal of the blanket `middleware.Timeout(60*time.Second)` applicability (see Common Pitfalls).

**Not found / no action needed:**
- No stored data references the old response shape (no Postgres table persists `QueryRAGResponse` today).
- No OS-registered state, no secrets/env vars reference this RPC's shape.
- No build artifacts depend on the unary shape beyond the generated `pb` package itself, which regenerates cleanly from the updated `.proto`.

## Common Pitfalls

### Pitfall 1: Global chi timeout will kill the SSE stream before the workflow can finish
**What goes wrong:** `gateway/main.go:464` applies `middleware.Timeout(60*time.Second)` to *every* route via `r.Use(...)`. `GenerateAnswer`'s node-level budget (per AI-SPEC's own sizing guidance, ~65s to accommodate two 30s-per-attempt generation calls plus the other four nodes' timeouts) already exceeds 60s on its own — the SSE connection will be forcibly cancelled by Go's own middleware before a legitimate happy-path query with a slow-but-successful retry can complete, even with zero client-side issues.
**Why it happens:** `middleware.Timeout` was sized for the old synchronous unary-JSON response pattern, where a 60s ceiling was a reasonable circuit breaker. It was never revisited for a workflow whose own documented worst-case latency (5+10+15+2+65 = 97s sequential worst case) now exceeds it.
**How to avoid:** Give `/rag/query` its own route-scoped timeout (chi supports per-route middleware via `r.With(middleware.Timeout(d)).Post(...)` or a route group) sized to exceed the sum of all five node timeouts plus slack, or remove the blanket timeout for this route entirely and rely solely on D-16's cancellation chain + the node-level timeouts to bound the request. **This must be an explicit planning decision, not left as a residual default** — verified this session, not present in the AI-SPEC.
**Warning signs:** A Tier 2 (Go+Postgres) integration test that legitimately exercises the retry-vs-timeout arithmetic scenario (AI-SPEC reference dataset scenario #7) will flake or fail with a spurious `context deadline exceeded` around the 60s mark if this isn't fixed first.

### Pitfall 2: `ExtractGraphContext`'s timeout sub-case needs the node to own its own inner timeout, not just rely on the runner's outer one
**What goes wrong:** If `ExtractGraphContextNode::run` simply calls `attempt_graph_augmentation(...).await` and lets the `WorkflowRunner`'s outer `tokio::select!` timeout race be the only timeout enforcement, a slow graph query produces `Err(NodeError::timeout(...))` from the node, which the runner's uniform control flow (`Err(err) => emit NodeFailed; return Err(err)`) turns into `WorkflowCompleted(failed)` — contradicting D-09's "mandatory but non-required" framing, which the AI-SPEC's own dimension-4 eval criterion explicitly flags as unresolved.
**Why it happens:** `attempt_graph_augmentation` (verified live, `main.rs:1056-1236`) is *already* infallible-by-construction for logical failures — it returns `GraphAugmentationOutcome::AttemptedAndFailed { reason }` rather than `Err` for e.g. a LanceDB query error — but it has **no internal timeout of its own today**. A hang inside it currently just makes `query_rag` slow; nothing degrades it. Naively wrapping it in only the runner's outer timeout accidentally makes the *timeout* case behave differently (hard failure) from the *logical failure* case (silent degrade) for the same node, which is almost certainly not the intended semantics given D-09 draws no such distinction.
**How to avoid (recommendation, not yet a locked decision — see Open Questions):** Give `ExtractGraphContextNode::run` its own inner `tokio::select!`/`timeout()` race around the call to `attempt_graph_augmentation`, and treat a timeout exactly like `AttemptedAndFailed` — record the degrade reason into `WorkflowContext` (empty `graph_context`, per dimension 4's checkpoint-diff mechanism) and return `Ok(())` to the runner. This keeps `ExtractGraphContextNode`'s outer behavior uniform with every other node (the runner's `tokio::select!` still applies as a *backstop*, but the node's own inner timeout should fire first in the normal case since it should be sized ≤ the outer D-17 budget) while preserving D-09's "always runs, never required" contract for both failure sub-cases.
**Warning signs:** AI-SPEC reference dataset scenario #4 (graph timeout) is explicitly a placeholder pending this resolution — if planning doesn't resolve this, that scenario cannot be written to a concrete pass/fail assertion.

### Pitfall 3: No injectable "stall past a duration" test double exists for the graph-query or dense-retrieval path
**What goes wrong:** AI-SPEC Section 5's testability requirements state "the `Generator` port and the graph-query port each need an injectable test double that can stall past a given duration or fail on the Nth call." The `Generator` port already has this (`FakeGenerator`, verified above). The graph-query path does **not** — `attempt_graph_augmentation` takes a concrete `&DatabaseManager` (`main.rs:1056-1060`, verified — `DatabaseManager` is a `pub struct`, not a trait, `gateway/db/mod.rs:9`... wait, `engine/src/db/mod.rs:9`), and `RetrieveHybrid`'s dense-retrieval path (`DenseRetriever::new(self.nodes.clone())`, `main.rs:1450`) is similarly built directly against concrete LanceDB table handles, not an injected trait.
**Why it happens:** Only `Generator` and `EmbeddingProvider` (`main.rs:1971`) are behind `Arc<dyn Trait>` ports today — graph augmentation and dense retrieval were never abstracted this way because Phase 3/04.1 had no need to swap implementations.
**How to avoid:** This is a genuine Wave 0 gap the planner must size explicitly: either (a) introduce a minimal trait seam around graph-query and dense-retrieval sufficient to inject a stall/fail-on-Nth-call double for Tier 1 tests, or (b) accept that timeout-enforcement tests for `ExtractGraphContext`/`RetrieveHybrid` (AI-SPEC reference dataset scenario #8, parametrized across non-generation nodes) must run against a real (test-fixture) LanceDB instance with an artificially slow query, which is far less deterministic than a mock and directly undermines the "deterministic, not dependent on real latency/flakiness" requirement AI-SPEC Section 5 states for these scenarios. Flag for the planner as a concrete task, not an assumed given.
**Warning signs:** If the plan doesn't include a task introducing this seam (or an explicit accepted-risk note choosing option (b)), the timeout-enforcement eval scenarios for these two nodes will be unwritable to the same determinism standard as the generation-node scenarios.

### Pitfall 4: Existing config convention is whole-seconds (`_secs`), but tests need sub-second timeout overrides
**What goes wrong:** AI-SPEC Section 5 states "every per-node timeout value ... must be overridable via the existing TOML+env convention down to sub-second values for tests. Without this, a Tier 1 timeout-enforcement test literally waits out a [multi-second] budget per test case." The existing convention, verified live in `config/config.toml`, uses whole-second integer keys: `generation_timeout_secs = 30`.
**Why it happens:** No sub-second config precedent exists in this codebase yet — the `_secs` naming convention itself implies integer-seconds granularity, which is fine for production defaults (5s/10s/15s/2s/65s) but directly blocks fast, deterministic tests that need to shrink these to e.g. 50ms.
**How to avoid:** The new per-node timeout config keys should either (a) use a naming convention that doesn't imply integer-seconds (e.g. `*_timeout_ms` as `u64` milliseconds, still trivially convertible to `Duration`), or (b) keep `_secs` naming but accept `f64`/fractional-seconds values. Either is a small, explicit decision the planner should make once, rather than leaving each node's timeout config ad hoc.
**Warning signs:** A test that tries to set `LANCET_WORKFLOW__REFORMULATE_TIMEOUT_SECS=0` (or a fractional value into an integer-typed field) either fails to deserialize or floors to a useless 0/1s value.

### Pitfall 5: `RetrieveHybrid`'s RRF-merge-across-variants (D-07) doesn't map cleanly onto the existing single-pass `fuse_candidates`
**What goes wrong:** The existing `retrieval::fusion::fuse_candidates(vector_candidates, bm25_candidates, settings)` (`engine/src/retrieval/fusion.rs:58`, verified) RRF-merges exactly one dense-candidate list against exactly one BM25-candidate list — it has no concept of "N reformulation variants." D-07 requires looping over the `QueryReformulator`'s `Vec<String>` and RRF-merging *across* those variants too, on top of the existing dense/BM25 merge per variant.
**Why it happens:** `fuse_candidates` predates ORCH-05/999.3 — it was designed and correctly scoped for single-query fusion in Phase 3.
**How to avoid:** This composition needs an explicit design choice during planning (not resolved by this research or the AI-SPEC): either (a) accumulate all variants' dense/BM25 candidate lists into two flat lists before a single `fuse_candidates` call (relies on rank position alone being variant-agnostic, which RRF's rank-based scoring tolerates reasonably well), or (b) call `fuse_candidates` once per variant producing N `FusedCandidate` lists, then RRF-merge *those* lists together in a second pass (requires either reusing/adapting the internal `rrf_add` logic or writing a second small merge function). Since NoOp reformulator (999.3 D-02) always returns exactly one variant in v1, this is currently behaviorally inert either way — but the node's shape should be built to already support N variants correctly, per D-07's explicit rationale ("so 999.3's future real reformulation doesn't require rewriting this node").
**Warning signs:** If `RetrieveHybridNode` is written assuming exactly one variant (e.g. flattening `Vec<String>` and only ever using index `[0]`), it silently violates D-07 even though it will pass all v1 tests (since NoOp only ever produces one variant) — this is exactly the kind of bug that only surfaces when 999.3 lands.

## Code Examples

### Existing `Generator` DI pattern to mirror for new node ports
```rust
// engine/src/main.rs:870-874 -- VERIFIED live pattern; Node ports should follow this
// Arc<dyn Trait> injection shape exactly (constructed once, shared across requests)
pub struct RagEngineService {
    pub effective_settings: EffectiveRagSettings,
    generator: Arc<dyn generation::Generator>,
    embedder: Arc<dyn EmbeddingProvider>,
    reranker: Arc<dyn rerank::Reranker>,
    pub database: DatabaseManager,
}
```

### Existing `FakeGenerator` test double (reuse directly, do not rebuild)
```rust
// engine/src/generation/mod.rs:466-505 -- VERIFIED live code
pub struct FakeGenerator {
    pub call_count: AtomicUsize,
    pub responses: Mutex<Vec<Result<ModelOutput, GenerationError>>>,
}
impl FakeGenerator {
    pub fn with_responses(responses: Vec<Result<ModelOutput, GenerationError>>) -> Self { /* ... */ }
    pub fn calls(&self) -> usize { /* ... */ }
}
// Generator impl increments call_count and pops from `responses` -- exactly the
// "fail on Nth call" shape needed for D-12/D-13 retry-scenario tests (AI-SPEC
// reference dataset scenarios 5, 6, 7).
```

### Existing `d1_status` trailer pattern D-04 preserves (unchanged, pre-stream path only)
```rust
// engine/src/main.rs:877-898 -- VERIFIED live code. This is the ONLY place trailer
// metadata (x-lancet-session-id / -correlation-id / -error-kind) is emitted --
// it applies solely to the pre-stream ReceiveQuery validation-failure path (D-04).
// Once the stream opens, in-stream failures are reported via WorkflowEvent (D-05),
// NOT via this trailer mechanism -- do not try to extend d1_status to in-stream errors.
fn d1_status(code: tonic::Code, message: impl Into<String>, session_id: &str,
             correlation_id: &str, error_kind: &str) -> Status { /* ... */ }
```

### Existing gRPC Go proxy pattern to extend for streaming
```go
// gateway/main.go:280-287 -- VERIFIED live code, today's UNARY shape.
// The streaming replacement follows the same trailerError-on-pre-stream-failure
// idea but returns a stream.Recv()-consuming client method instead of a single resp.
func (e grpcEngine) QueryRAG(ctx context.Context, req *pb.QueryRAGRequest) (*pb.QueryRAGResponse, error) {
    var trailer metadata.MD
    resp, err := e.client.QueryRAG(ctx, req, grpc.Trailer(&trailer))
    if err != nil {
        return resp, trailerError{err: err, trailer: trailer}
    }
    return resp, nil
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `QueryRAG` unary gRPC → single synchronous JSON HTTP response | Server-streaming gRPC → SSE (`text/event-stream`) | This phase (D-18/D-19) | Breaking, one-way client-contract change — every existing caller/test must be rewritten (see Runtime State Inventory) |
| Graph augmentation / retrieval failures handled ad hoc inline in `query_rag` | Typed `NodeError`/`NodeErrorKind` taxonomy surfaced as in-band `NodeFailed` events | This phase (D-22) | Existing `d1_status`/`Status` error reporting stays for pre-stream (D-04) failures only; a new, parallel in-stream error-reporting mechanism is introduced for everything after the stream opens |
| No workflow-level checkpointing | PostgreSQL-backed, full-snapshot checkpoints per node boundary | This phase (D-23/D-28, ORCH-04) | New Atlas-managed table, new sqlc query, new Go-side write path off the streaming gRPC connection |

**Deprecated/outdated:** None — this phase does not deprecate or remove any existing capability; it wraps/extends the existing pipeline. The unary `QueryRAGResponse` proto message itself is not deleted (D-18 keeps its fields as "the terminal event carrying the equivalent" payload inside the new streaming contract), only the RPC's cardinality changes.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | prost generates a `oneof` field as `Option<enum>` nested in a generated submodule (e.g. `workflow_event::Event`), matching the recommended proto shape below | Architecture Patterns / proto design | Low — this is extremely well-established, stable prost behavior across all recent versions; not verified via live docs this session (context7 MCP was unavailable in this environment) but has near-zero risk of being wrong |
| A2 | Go SSE pattern (`http.Flusher` + `r.Context().Done()` select loop) is the correct/idiomatic approach for this handler | Architecture Patterns / Pattern 2 | Low-Medium — corroborated across multiple independent web sources (see Sources) but not verified against an official Go stdlib doc page this session; the core APIs (`http.Flusher`, `context.Context`) are stable stdlib and unlikely to have changed semantics |
| A3 | chi's `middleware.Timeout` behavior on an already-headers-sent streaming response is to cancel `r.Context()` without double-writing a response (rather than panicking or corrupting the stream) | Common Pitfalls #1 | Medium — this is inferred from general `net/http` timeout-middleware behavior, not verified against chi's specific source this session; if wrong, the planner's fix (route-specific timeout) is still correct, but the exact failure mode description in Pitfall #1 could be imprecise |

**Recommendation:** A1 and A2 are low-risk, standard-library/first-party-crate behaviors well within normal training-knowledge reliability — no user confirmation needed before planning proceeds. A3 should be spot-checked with a small manual test (curl a slow endpoint through the existing chi middleware stack) during Wave 0 rather than assumed, since it directly affects how Pitfall #1's fix is implemented (some timeout middleware designs write a 503 even after partial writes, which would corrupt SSE framing).

## Open Questions (RESOLVED)

1. **(RESOLVED)** **Does `ExtractGraphContext`'s D-17 timeout fail the query or degrade it, per D-09?**
   - What we know: D-09 says the node "always runs... success is not required." `attempt_graph_augmentation` is already infallible-by-construction for logical failures (returns an outcome enum, never `Err`). AI-SPEC's own dimension-4 eval criterion explicitly flags this as unresolved and reserves reference-dataset scenario #4 for whatever answer planning gives.
   - What's unclear: Whether D-09's "mandatory but non-required" framing was intended to cover the timeout sub-case specifically, or only logical/no-match failures.
   - Recommendation: Give `ExtractGraphContextNode` its own inner timeout race (see Common Pitfalls #2) so a graph timeout degrades exactly like `AttemptedAndFailed` — uniform node failure-policy across the runner, D-09 honored for both failure sub-cases. This is a semantic reading of D-09, not a technical fact — confirm with the user/CONTEXT.md owner before locking it into the plan, since it's the kind of interpretation call the AI-SPEC explicitly declined to make unilaterally.
   - **Resolution:** Locked exactly as recommended in 05-02-PLAN.md Task 1's `ExtractGraphContextNode` (`engine/src/workflow/nodes/graph_context.rs`) — an inner `tokio::select!` timeout race degrades a genuine graph timeout identically to `AttemptedAndFailed` (`ctx.graph_context` stays empty, `WorkflowCompleted{success: true}`), proven by a Tier 1 test with a genuinely-stalled `FakeGraphQueryPort`.

2. **(RESOLVED)** **How should `RetrieveHybrid`'s RRF-merge-across-reformulation-variants (D-07) compose with the existing single-pass `fuse_candidates` function?**
   - What we know: `fuse_candidates` merges one dense list + one BM25 list via RRF today; D-07 requires merging across N reformulation variants too.
   - What's unclear: Whether this should be "flatten all variants' candidates into two lists, one `fuse_candidates` call" or "N `fuse_candidates` calls (one per variant), then a second RRF pass over the N `FusedCandidate` lists."
   - Recommendation: Since v1's NoOp reformulator makes this behaviorally inert (always exactly one variant), either approach passes v1 tests — but the planner should pick one explicitly (flatten-then-fuse is simpler and reuses `fuse_candidates` unmodified; two-pass is more semantically correct for N>1 variants but requires new merge code) rather than let it be decided implicitly by whichever is easiest to write against a single-variant NoOp.
   - **Resolution:** Locked to the two-pass approach in 05-02-PLAN.md Task 2 (`RetrieveHybridNode`) — one `fuse_candidates` call per `QueryReformulator` variant, then a new cross-variant RRF merge function (in `engine::retrieval::fusion`) over the per-variant `FusedCandidate` lists, with an explicit documented scoring formula proven by an exact-score assertion (not just relative order) against a 2-variant fake.

3. **(RESOLVED)** **Should the graph-query and dense-retrieval paths get an injectable test double this phase, or is real-fixture-based timeout testing accepted for v1?**
   - What we know: `Generator` and `EmbeddingProvider` already have trait-based DI + fakes; graph augmentation and dense retrieval do not (see Common Pitfalls #3).
   - What's unclear: Whether introducing this seam is in-scope for this phase (it's not explicitly named in ORCH-01 through ORCH-05) or should be accepted as a testing gap/technical debt like several other Phase 2/3 items already tracked in `STATE.md`.
   - Recommendation: Size it as an explicit Wave 0 task if the planner wants full parity with the AI-SPEC's stated testability requirements; otherwise, explicitly document it as accepted debt (consistent with this project's established pattern of `DEBT-*` tracking) rather than silently under-delivering on the timeout-enforcement eval dimension for these two nodes.
   - **Resolution:** Sized in-scope, not accepted as debt. 05-02-PLAN.md Task 1 defines `GraphQueryPort`/`DenseRetrievalPort` traits (`engine/src/workflow/ports.rs`) plus production wrapper implementations and `FakeGraphQueryPort`/`FakeDenseRetrievalPort` test doubles, giving both paths the same injectable-seam parity `Generator`/`EmbeddingProvider` already had.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Rust toolchain (2021 edition) | engine/ build | assumed present (existing crate builds today) | — | — |
| Go toolchain | gateway/ build | assumed present (existing module builds today) — `go.mod` declares `go 1.25.0` | 1.25.0 | — |
| PostgreSQL | ORCH-04 checkpoint persistence | ✓ (docker-compose service `db`, `postgres:16-alpine`) `[VERIFIED: docker-compose.yml]` | 16-alpine | — |
| Atlas CLI | Schema migration for `workflow_checkpoints` table | not verified this session (assumed present given `gateway/atlas.hcl` already drives existing migrations) | — | If absent, migration can be hand-written as raw SQL against `gateway/db/schema.sql` and reconciled with Atlas later |
| sqlc CLI | Regenerating `gateway/db/query.sql.go` after adding the checkpoint query | not verified this session (assumed present given `gateway/db/query.sql.go`'s generated header shows `sqlc v1.31.1`) | v1.31.1 (from generated file header) | — |
| Jaeger (docker-compose) | Not used by this phase (D-31 defers tracing spans to Phase 6) | ✓ present but irrelevant to this phase's scope | 2.19.0 | — |

**Missing dependencies with no fallback:** none identified — this phase adds no new external service dependencies beyond what's already in `docker-compose.yml`.

**Missing dependencies with fallback:** Atlas/sqlc CLI availability not directly probed this session; both have a manual-SQL fallback path if unavailable in the execution environment.

## Validation Architecture

> `workflow.nyquist_validation` = `true` in `.planning/config.json` — section included per protocol. This phase's own `05-AI-SPEC.md` Section 5 already contains an exceptionally thorough two-tier eval strategy (9 dimensions, 15 reference scenarios, Tier 1 Rust/`cargo test` + Tier 2 Go/`go test`+Postgres) — this section summarizes it for the planner's Wave-mapping purposes rather than re-deriving it.

### Test Framework
| Property | Value |
|----------|-------|
| Framework (Rust) | `cargo test`, existing `engine/tests/config_startup.rs` spawn-the-binary pattern as Tier 1 precedent |
| Framework (Go) | `go test`, existing `gateway/main_test.go` fake-engine + real-engine-spawn patterns (verified: the ~2120-2174 block already spawns the real Rust binary and dials real gRPC — direct precedent for Tier 2) |
| Config file | none dedicated — uses `engine/Cargo.toml`'s built-in test harness and `gateway/go.mod`'s built-in test tooling |
| Quick run command | `cargo test --manifest-path engine/Cargo.toml --locked` / `cd gateway && go test ./... -short` |
| Full suite command | `.planning/config.json`'s configured `test_command`: `cargo test --manifest-path engine/Cargo.toml --locked && (cd gateway && go test ./...)` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ORCH-01 | State machine executes fixed node sequence in D-06 order | unit/integration (Rust) | `cargo test --test workflow_events` (per AI-SPEC Section 5) | ❌ Wave 0 |
| ORCH-02 | Workflow events stream correctly (cardinality, ordering) | unit (Rust, Tier 1) | `cargo test --test workflow_events` | ❌ Wave 0 |
| ORCH-03 | Timeout/retry/cancellation enforced correctly | unit (Rust, Tier 1, fault-injected) | `cargo test --test workflow_events -- timeout cancel` | ❌ Wave 0 — blocked on Pitfall #3/#4 resolutions first |
| ORCH-04 | Checkpoint rows land in Postgres with full-snapshot fidelity | integration (Go, Tier 2) | `cd gateway && go test ./... -run TestCheckpointPersistence` | ❌ Wave 0 |
| ORCH-05 | `QueryReformulator` pass-through node behaves as NoOp today | unit (Rust) | `cargo test reformulate` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cargo test --manifest-path engine/Cargo.toml --locked` (Tier 1 subset relevant to the touched node)
- **Per wave merge:** Full `test_command` from `.planning/config.json` (both Rust and Go suites)
- **Phase gate:** Full suite green, including Tier 2 Go+Postgres integration, before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `engine/tests/workflow_events.rs` (or similar) — Tier 1 harness spawning the engine binary and driving the streaming `QueryRAG` RPC directly, per AI-SPEC Section 5's Tier 1 description
- [ ] Sub-second-overridable timeout config keys (Common Pitfall #4) — must exist before any timeout-enforcement test can run fast
- [ ] Injectable stall/fail-on-Nth-call test double for the graph-query and/or dense-retrieval path (Common Pitfall #3, Open Question 3) — or an explicit accepted-debt decision in its place
- [ ] `gateway/db/schema.hcl` + `query.sql` + regenerated `query.sql.go` for `workflow_checkpoints` — needed before any Tier 2 checkpoint-persistence test can run
- [ ] `gateway/main_test.go` rewrite of the `engine` interface fake (`engineFunc`) to a streaming shape — blocks every existing `/rag/query` test from compiling once D-18 lands, must land in the same wave as the Go handler rewrite

## Security Domain

> `security_enforcement` = `true`, `security_asvs_level` = 1 in `.planning/config.json` — section included per protocol.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V1 Architecture, Design and Threat Modeling | Yes | This RESEARCH.md's Architectural Responsibility Map + the AI-SPEC's Critical Failure Modes (Section 1) together constitute the threat model for this phase's new surface |
| V4 Access Control | No (unchanged) | No new authZ/authN surface introduced — same trust boundary as existing `QueryRAG`, single-user local demo per PROJECT.md |
| V5 Input Validation | Yes (unchanged) | `QueryRequest::from_values` validation (`main.rs:1376-1393`) stays exactly where it is, pre-stream (D-04) — no new validation surface, but its position relative to the new streaming boundary must not regress |
| V7 Error Handling and Logging | Yes | D-22's typed `NodeErrorKind` taxonomy IS this phase's V7 control — replaces ad hoc error strings with a closed, loggable taxonomy; `d1_status`'s existing session/correlation-scoped `tracing::warn!` pattern (`main.rs:885`) should be mirrored for in-stream `NodeFailed` logging too |
| V12 Files and Resources | Marginal | Checkpoint payloads persist raw corpus content (chunk text, graph facts, assembled prompts) to Postgres — D-23 explicitly extends 04.1 D-33's accepted-risk/no-redaction framing; this is a **documented accepted risk, not a new mitigation gap** — do not treat it as something this phase must newly solve |
| V13 API and Web Service | Yes | The new server-streaming `QueryRAG` RPC and SSE endpoint are new API surface; D-19's "no content-negotiated fallback" (SSE-only) is itself a scope-reduction that avoids a dual-contract attack surface |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Checkpoint-channel/event-channel exhaustion as a resource-exhaustion vector (a slow/never-draining consumer causing unbounded buffered events in Rust) | Denial of Service | D-27's `try_send`-with-drop (not unbounded queue growth) is the mitigation — AI-SPEC pitfall #4 and dimension-9's eval already cover this; this research adds no new mitigation, just confirms it's the correct STRIDE framing |
| Unbounded SSE connection lifetime enabling slow-loris-style resource pinning (one client holding a long-lived stream open indefinitely) | Denial of Service | D-16's cancellation propagation + a bounded per-request node-timeout budget (Common Pitfall #1's fix) together cap worst-case per-request resource hold time; genuine rate-limiting/connection-count-limiting is out of scope per PROJECT.md's local-first, single-user, avoid-speculative-hardening framing |
| Checkpoint row content (raw corpus text) as an information-disclosure vector if the Postgres instance is ever exposed beyond localhost | Information Disclosure | Explicitly accepted risk per D-23/04.1 D-33 — not a gap this phase introduces or must close; `docker-compose.yml`'s Postgres port binding (`127.0.0.1:5432:5432`, verified) already scopes exposure to localhost, consistent with the accepted-risk framing |

## Sources

### Primary (HIGH confidence — verified directly against live repository code this session)
- `engine/src/main.rs` (lines 870-898, 1046-1054, 1056-1236, 1346-1708, 1971) — `query_rag` handler, `d1_status`, `attempt_graph_augmentation`/`GraphAugmentationOutcome`, `EmbeddingProvider` trait
- `engine/src/generation/mod.rs` (lines 1-140, 395-505) — `BoxFuture` alias, `Generator` trait, `GenerationError`/`GenerationErrorKind`, `FakeGenerator`
- `engine/src/generation/openrouter.rs` (lines 1-40, 600-636) — `GENERATION_TIMEOUT`, per-attempt `timeout()` wrapping in `Generator::generate`
- `engine/src/retrieval/fusion.rs` (lines 58-165) — `fuse_candidates` single-pass RRF implementation
- `engine/Cargo.toml`, `gateway/go.mod` — current dependency versions
- `gateway/main.go` (lines 190-330, 460-780) — `engine` interface, `trailerError`, `grpcEngine.QueryRAG`, chi router + global `middleware.Timeout`, `queryRAG` HTTP handler
- `gateway/main_test.go` (grep of `QueryRAG`/`queryRAG`/`/rag/query` occurrences) — blast-radius enumeration
- `proto/lancet/v1/lancet.proto` (full file) — current RPC/message shapes
- `gateway/db/schema.hcl`, `gateway/sqlc.yaml`, `gateway/db/db.go`, `gateway/db/query.sql` — Atlas/sqlc convention
- `docker-compose.yml` — Postgres/Jaeger service definitions
- `config/config.toml` (grep) — existing `generation_timeout_secs` whole-seconds convention
- `rust-guidelines.md` (M-ERRORS-CANONICAL-STRUCTS, M-APP-ERROR, M-PANIC-*, M-ASYNC-STACK-SIZE, M-YIELD-POINTS sections) — error-struct and async-correctness conventions
- `go-guidelines.md` — modern Go 1.25 feature guidance (detected via `go.mod`'s `go 1.25.0`)
- `cargo search tokio-util / tokio-stream / tonic` — live crates.io registry version confirmation
- `gsd-tools query package-legitimacy check --ecosystem crates tokio-util tokio-stream` — both `OK`

### Secondary (MEDIUM confidence)
- `05-AI-SPEC.md` — already-locked design contract; treated as authoritative for the Rust `Node`/`WorkflowRunner` pattern itself (not independently re-verified beyond the specific line citations checked above, several of which were confirmed accurate and a few of which needed correction — e.g. `attempt_graph_augmentation`'s exact infallibility shape was more specific than the AI-SPEC's framing implied)
- `.discussion/lightweight_state_machine_plan.md` — original design doc, superseded in node order by D-06 per CONTEXT.md, otherwise consistent with what was found in code

### Tertiary (LOW-MEDIUM confidence — web-sourced, not independently verified against official docs this session)
- Go SSE handler pattern (`http.Flusher`, `r.Context().Done()` for disconnect detection) — corroborated across https://oneuptime.com/blog/post/2026-01-25-server-sent-events-streaming-go/view, https://matttproud.com/blog/posts/context-cancellation-and-server-libraries.html, https://alexanderobregon.substack.com/p/go-http-handlers-and-connection-lifecycle — general pattern only, `context7`/official Go doc MCP tools were unavailable in this session's environment
- prost `oneof` codegen shape (`Option<enum>` in a generated submodule) — training-knowledge only this session (`[ASSUMED]`, see Assumptions Log A1), not independently re-verified against prost's own docs this session

## Metadata

**Confidence breakdown:**
- Rust engine standard stack/architecture: HIGH — every load-bearing claim (BoxFuture location, GENERATION_TIMEOUT value, per-attempt timeout wrapping, DI pattern, FakeGenerator shape, attempt_graph_augmentation's infallibility) verified directly against live code this session, several correcting or sharpening what the AI-SPEC's own (unverified-this-session) citations implied.
- Go gateway architecture: MEDIUM — all current-state claims (interface shapes, trailer pattern, test call sites, chi timeout, Atlas/sqlc convention) verified directly against live code; the *target*-state pattern (SSE forwarding) is net-new to this codebase and only corroborated via general web sources, not an internal precedent to copy.
- Package versions: HIGH — verified via live `cargo search` against crates.io and `gsd-tools` package-legitimacy check this session.
- Security domain: MEDIUM — ASVS category mapping is a reasoned application of a general framework to this phase's scope, not a domain-specific verified standard; the "accepted risk" framing for V12 is copied verbatim from already-locked prior-phase decisions (D-23/04.1 D-33), not re-derived.

**Research date:** 2026-08-10
**Valid until:** 30 days (stable — no fast-moving external dependencies; the Rust/Go ecosystem versions pinned here are unlikely to require re-verification within a normal phase-execution timeframe)

## Current Validation Authority (2026-08-13 continuation)

The historical validation map above is retained as research history. For the current checker continuation, the machine-checkable authority is the following artifact and named filters:

CURRENT_VALIDATION_AUTHORITY: .planning/phases/05-state-machine-workflow-events/05-VALIDATION.md
CURRENT_RUST_TEST_FILE: engine/src/tests/workflow_phase5.rs
CURRENT_GO_TEST_MODULE: gateway
VALIDATION_MAP_SUPERSESSION: historical examples above are superseded for current execution by 05-VALIDATION.md, the current Rust test file, the gateway module, and the named filters below.

| Plan | Current Rust named filters | Current Go named filters |
|---|---|---|
| 05-08 | production test bodies for workflow_phase5_production_five_node; workflow_phase5_production_dependencies_are_real; workflow_phase5_production_context_population; workflow_phase5_production_reachability (source/body and compile checks only; exact binary runs deferred to 05-20) | — |
| 05-09 | workflow_phase5_settings_applied_to_production; workflow_phase5_config_verify_generation_timeout | — |
| 05-10 | workflow_phase5_event_delivery_tracer; workflow_phase5_checkpoint_full_snapshot; workflow_phase5_terminal_idempotence | — |
| 05-11 | — | TestRAGQueryCrossRuntime; TestRAGQueryPostOpenRecvFailureSSE; TestRAGQueryEOFWithoutTerminalSSE; TestRAGQueryClientDisconnectCancelsRustWorkflow; TestRetrievalSnapshotWireContract; TestWorkflowCheckpointPendingDrainAndPersistence |
| 05-12 | — | — |
| 05-13 | openrouter_preflight_transport_is_retryable; openrouter_capabilities_cache_success_only; openrouter_capabilities_cache_single_flight; production bodies for workflow_phase5_generation_retry_tracer and workflow_phase5_generation_retry_exhausted (any early binary list/exact runs are non-authoritative pre-handoff semantic checks; 05-20-02 is authoritative) | — |
| 05-14 | production bodies for workflow_phase5_nodekind_tracer; workflow_phase5_nodekind_dispatch; workflow_phase5_nodekind_exhaustive (early binary list/exact runs are non-authoritative pre-handoff semantic checks; 05-20-02 is authoritative) | — |
| 05-15 | workflow_phase5_prompt_api_surface; workflow_phase5_prompt_graph_weight_semantics; workflow_phase5_fake_ports_test_only | — |
| 05-16 | workflow_phase5_graph_notice_merge; workflow_phase5_retrieval_snapshot_variants; workflow_phase5_bm25_snapshot_releases_lock | — |
| 05-17 | retrieval_snapshot_variant_provenance_wire_contract | — (Go wire fixture owned by 05-11) |
| 05-18 | workflow_phase5_happy_path; workflow_phase5_library_target_fake_ports_compile | — |
| 05-19 | workflow_phase5_failure_terminal_notices_tracer; workflow_phase5_failure_terminal_preserves_notices_without_answer_events | TestRAGQueryFailureTerminalNoticesSSE |
| 05-20 | workflow_phase5_generation_preflight_bootstrap_tracer; workflow_phase5_generation_preflight_worst_case_budget; workflow_phase5_reformulate_predeadline_4999ms_no_timeout; workflow_phase5_retrieve_predeadline_9999ms_no_timeout; workflow_phase5_happy_path; workflow_phase5_production_five_node; workflow_phase5_production_dependencies_are_real; workflow_phase5_generation_retry_tracer; workflow_phase5_generation_retry_exhausted; workflow_phase5_nodekind_tracer; workflow_phase5_nodekind_dispatch; workflow_phase5_nodekind_exhaustive; workflow_phase5_production_context_population; workflow_phase5_production_reachability (authoritative exact binary runs after 05-18, 05-15, and 05-16 no-run gates) | — |
| 05-21 | fusion_variant_provenance_source_tracer; fusion_variant_provenance_source_is_typed | — |

The 05-20 retrieval predeadline entry uses the exact filter `workflow_phase5_retrieve_predeadline_9999ms_no_timeout` with `cargo test --lib --manifest-path engine/Cargo.toml --locked -- --exact workflow_phase5_retrieve_predeadline_9999ms_no_timeout --nocapture`; required evidence is a deterministic 9999ms retrieval completing without `Timeout` classification at the 10000ms boundary. The production-binary filters listed on the 05-20 row are the authoritative post-handoff evidence after 05-18 registers `workflow_phase5_production.rs` in `engine/src/tests.rs` and 05-15/05-16 rerun the ordered binary no-run gates; early 05-13/05-14 binary filters, when retained, are explicitly non-authoritative semantic checks.

All current Cargo commands use a literal-safe list guard, immediate native exit handling, an exact registration assertion, and one exact filter per run. All current Go commands use explicit `go -C gateway` module execution with immediate native exit handling.

For 05-11, the definitive cancellation filter is `go -C gateway test -run '^TestRAGQueryClientDisconnectCancelsRustWorkflow$' -count=1`. Required evidence is a real `httptest.NewServer` plus `http.Client` request that closes the live SSE response after `GenerateAnswer` `node_started`, observes cancellation on the stalled provider request context, records no later node/answer/workflow_completed/stream_error event, and proves no second provider call.
