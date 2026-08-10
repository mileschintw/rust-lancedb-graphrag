# Phase 5: State Machine & Workflow Events - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-10
**Phase:** 5-State Machine & Workflow Events
**Areas discussed:** Answer streaming collision, Streaming transport, Retry/fallback scope, Checkpoint storage, Provider fallback, Error category on NodeFailed events, GraphRAG mandatoriness, Stream boundary & validation contract, Embedding fan-out, Identity (trace_id), Tracing spans

---

## Answer streaming collision

| Question | Selected |
|---|---|
| How should Phase 5 handle answer delivery given the structured-output/streaming collision? | **Event-level only** (vs. True token streaming, Hybrid) |
| Should the workflow still emit a distinct AnswerChunk event before FinalAnswer? | **AnswerChunk then FinalAnswer** (vs. FinalAnswer only, You decide) |
| When retrieval finds zero evidence, how should that flow through the state machine? | **Skip straight to Complete** (vs. Run AssemblePrompt/GenerateAnswer as no-ops, You decide) |

**Notes:** The advisor flagged this collision before it was presented — Phase 3 D-28 locks a validated JSON-schema generation call with no `stream:` support in `openrouter.rs`, incompatible with true token streaming without reworking the structured-output contract. User picked the lowest-risk option.

---

## Streaming transport

| Question | Selected |
|---|---|
| At the gRPC layer, how should workflow events reach Go? | **Convert QueryRAG to server-streaming** (vs. Add a new StreamQueryRAG RPC, You decide) |
| At the HTTP layer, how should /rag/query expose the event stream? | **Server-Sent Events (SSE)** (vs. Chunked NDJSON, WebSocket) |
| How granular should the client-visible event stream be? | **Coarse — one pair per pipeline node** (vs. Fine-grained sub-steps, You decide) |
| Does /rag/query become SSE-only, or keep a non-streaming option? | **SSE-only** (vs. Content-negotiated, You decide) |
| Does the SSE stream need reconnect/resume support? | **No resume support** (vs. Support resume via Last-Event-ID) |

**Notes:** Converting QueryRAG to streaming is a breaking change to the Phase 3 contract — accepted explicitly.

---

## Retry/fallback scope

| Question | Selected |
|---|---|
| Which nodes get automatic retry+backoff on failure? | **Generation only (matches Phase 3 D-29)** (vs. All I/O nodes uniformly, You decide) |
| For generation retries: how many attempts and what backoff? | **1 retry, no backoff** (vs. 2 retries with exponential backoff, You decide) |
| If generation still fails after the retry, what does the workflow do? | **Transition to Failed** (vs. You decide) |
| How should cancellation work over the long-lived streaming connection? | **Native connection-close propagation** (vs. Explicit CancelQuery RPC, You decide) |
| Should per-node timeouts use the plan doc's example values as defaults? | **Use plan doc defaults as-is** (vs. You decide) |

**Notes:** Explicitly scoped to avoid reopening Phase 6's DEBT-RAG-01/03 territory (degraded answer_basis, citation repair).

---

## Checkpoint storage

| Question | Selected |
|---|---|
| Where should lightweight workflow-state snapshots be saved? | **PostgreSQL-backed** (vs. In-memory only, JSON file dumps) |
| Should checkpoint rows have a retention/cleanup policy? | **Persist indefinitely** (vs. TTL-based cleanup, You decide) |
| Is there an API to fetch checkpoints, or direct DB inspection only? | **Direct DB inspection only** (vs. Add a GetWorkflowCheckpoint RPC, You decide) |
| Who writes checkpoint rows to Postgres? | **Rust sends checkpoint data to Go, Go writes it** (vs. Rust writes directly, You decide) |
| Should checkpoint writes block the query pipeline, or fire-and-forget? | **Fire-and-forget** (vs. Synchronous, You decide) |
| What does each checkpoint row's context payload contain? | **Full accumulated context per checkpoint** (vs. Incremental — just this node's new output, You decide) |

**Notes:** User chose Postgres despite being warned it means corpus content (chunk text, graph facts) lands in a table that currently holds only metadata — consistent with 04.1 D-33's existing accepted-risk framing (no redaction system).

---

## Provider fallback

| Question | Selected |
|---|---|
| Does Phase 5 add a configured backup model/provider for generation? | **Single provider, retry only** (vs. Configured backup model, You decide) |
| When the single retry fires, does it replay the exact same request? | **Exact same request replayed** (vs. You decide) |

---

## Error category on NodeFailed events

| Question | Selected |
|---|---|
| Should NodeFailed events expose the typed error category to the SSE client? | **Yes — expose category + human message** (vs. Generic failure message only, You decide) |
| Does the client see anything when a failed attempt triggers a retry, or only the final outcome? | **Final outcome only** (vs. Emit a transient NodeRetrying signal) |

---

## GraphRAG mandatoriness

| Question | Selected |
|---|---|
| Does the standalone QueryGraph RPC stay untouched, or get wrapped into state-machine nodes/events? | User's free-text answer requested clarification: "Make graph query a part of rag answering process. Always do the graph rag for answer a question, just like the vector search of chunk, both are mandatory." — followed up below. |
| Should a failed/no-match ExtractGraphContext step still let the query complete with vector+BM25-only evidence, or fail/degrade the whole query? | **Keep silent degrade (04.1 D-32 unchanged)** (vs. Graph result now required) |

**Notes:** Clarified that "mandatory" means the `ExtractGraphContext` node always *executes* (already true in shipped code), not that its success is required — 04.1 D-32's degrade-on-failure behavior is unchanged. The standalone `QueryGraph` RPC remains untouched and out of scope, confirmed separately.

---

## Stream boundary & validation contract

| Question | Selected |
|---|---|
| Does validation happen before the stream opens (preserving today's 4xx/trailer contract), or does everything become an in-stream event? | **Validate first, then open stream** (vs. Everything is in-stream including ReceiveQuery, You decide) |
| Once the stream is open and a node fails terminally, how does the client learn the request failed? | **NodeFailed + WorkflowCompleted(failed) events, stream then closes normally** (vs. You decide) |

**Notes:** Surfaced by the advisor — `gateway/main.go:282` reads gRPC trailer metadata (`main.rs:887-891`) for session/correlation IDs on error today; server-streaming only delivers trailers after the stream terminates, so this needed an explicit boundary decision. Resolves cleanly: `ReceiveQuery` stays in the tonic handler outside the state machine.

---

## Embedding fan-out

| Question | Selected |
|---|---|
| Should RetrieveHybrid embed only reformulation variant [0], or every variant? | **Embed variant [0] only (v1 default)** (vs. Embed every variant, You decide) |

---

## Identity (trace_id)

| Question | Selected |
|---|---|
| Does the state machine's trace_id reuse the existing correlation_id, or is it a new identifier? | **Reuse correlation_id as trace_id** (vs. New distinct trace_id, You decide) |

---

## Tracing spans

| Question | Selected |
|---|---|
| Does Phase 5 add per-node tracing spans, or is span instrumentation Phase 6's job? | **No — defer entirely to Phase 6** (vs. Yes, add spans now; You decide) |

---

## Claude's Discretion

- Exact Rust module/file layout for the `Node` trait, `WorkflowRunner`, and event types.
- Internal error type names and configuration key names for new timeout/retry/checkpoint knobs.
- Exact `WorkflowEvent` protobuf message shape (`oneof` vs. separate messages).
- Exact SSE framing details beyond "no resume support."

## Deferred Ideas

- Workflow metadata collection and per-node tracing spans → Phase 6 (OBS-01).
- `answer_basis: degraded/model_only` contract and citation repair → Phase 6 (DEBT-RAG-01/DEBT-RAG-03).
- Real query-reformulation strategies (HyDE, multi-query) → Phase 999.3 backlog.
- Descoped (not phase-deferred): configured backup model/provider, SSE reconnect/resume, explicit CancelQuery RPC, checkpoint-fetch API.
