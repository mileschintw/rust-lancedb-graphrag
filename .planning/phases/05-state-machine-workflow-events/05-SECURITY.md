---
phase: 05
slug: state-machine-workflow-events
# `verified` here is documentation-level: see "Verification Depth" below
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-08-19
---

# Phase 05 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Built retroactively from the `<threat_model>` blocks of the 26 Phase 05 PLAN files that carry one.

---

## Verification Depth — read this first

This document was produced by `/gsd-secure-phase 5` in **State B** (no prior SECURITY.md).
At the Step 4 gate the operator selected **"Accept all open — document in accepted risks log"**,
so the `gsd-security-auditor` subagent was **not** spawned.

What that means for the statuses below:

- The 15 `accept`-disposition threats are **closed by documentation** — their PLAN-time rationale
  is transcribed verbatim into the Accepted Risks Log. This is the closure the gate authorised.
- The 99 `mitigate`-disposition threats are recorded as **closed by plan-declared mitigation**.
  Their mitigation text is the plan author's declaration, carried forward as written.
  **This run performed no independent per-threat verification that each control actually landed
  in the implementation.** Grep-level (ASVS L1) evidence collection was skipped along with the auditor.
- Independent evidence for Phase 05 that *does* exist lives in sibling artifacts, not here:
  `05-VERIFICATION.md`, `05-VALIDATION.md`, `05-REVIEW.md`, `05-REVIEW-FIX.md`, `05-SOURCE-AUDIT.md`.

To obtain verified mitigation evidence, re-run `/gsd-secure-phase 5` and select
**"Verify all open threats"** at the gate.

### Threat-model coverage gap

`05-27-PLAN.md` (gap closure G-05-1) carries **no `<threat_model>` block** — it is the only
Phase 05 plan without one. That plan raises the OpenRouter model-catalog response ceiling from
256 KB (`MAX_PROVIDER_RESPONSE_BODY_BYTES`) to 10 MB (`MAX_MODELS_METADATA_BODY_BYTES`) in
`engine/src/client/mod.rs` and `engine/src/generation/openrouter.rs`. That is a memory-bound
change on a provider-response path and is exactly the kind of surface a STRIDE register covers.
No threat ID has been minted for it here — inventing one would misrepresent the plan-time register.
It is recorded as an **open coverage gap** for a future audit.

---

## Trust Boundaries

Union of the trust boundaries declared across the 26 plan threat models. The PLAN template
declares `Boundary` and `Description` only; the `Data Crossing` column of the SECURITY template
is folded into the description.

| Boundary | Description |
|----------|-------------|
| BM25 index lock to async retrieval | A read guard held across await can block ingestion and create resource denial. |
| Cargo library test target to cfg(test) workflow fakes | Test-only code crosses the compilation boundary while production binary code must not depend on it. |
| Client request to Rust service | Query text, session, correlation, and filters are untrusted before validation. |
| Configuration file to Rust settings | Operator-controlled TOML can contain unknown or unsafe timeout values. |
| Engine startup log output -> operator terminal | The improved error message is diagnostic text only, surfaced to whoever runs the binary. |
| Errata document to future automation | Machine checks consume exact identifiers and coverage declarations. |
| Fusion model to serialized response | Provenance values cross the Rust response serialization boundary. |
| Fusion provenance -> serialized retrieval result | Inner vector/BM25 provenance crosses the Rust response boundary and must remain attributable. |
| GenerateAnswer to provider attempts | Retry timing controls external request volume and node completion. |
| Generated protobuf fields to Rust literals | New fields must be initialized at every exhaustive construction site. |
| Generation error classification to workflow event | Internal provider details become a safe typed category and retryability signal. |
| Go dispatcher to PostgreSQL | Checkpoint envelopes cross into parameterized persistence under bounded asynchronous backpressure. |
| Go gateway -> Rust gRPC stream | HTTP cancellation and generated protobuf frames cross the runtime boundary. |
| Go gateway to browser/client | SSE payloads are client-visible and must not include checkpoint snapshots or provider secrets. |
| Go sink -> PostgreSQL | Detached writes cross into the durable database using the existing Go-owned connection. |
| Go test harness -> spawned engine subprocess env | `ragChildEnv(...)` constructs the full environment handed to the real `engine.exe`/`seed_rag_fixture.exe` child process; this is the only channel besides config.toml through which the test controls engine behavior. |
| Graph adapter outcome to workflow notice | Timeout and degradation must not be confused or silently erase prior diagnostics. |
| HTTP and gRPC stream lifetime to Rust task | Client disconnect is an asynchronous teardown signal that controls paid and resource-intensive work. |
| HTTP client -> Go SSE route | Untrusted request/headers and connection lifetime cross into gateway request handling. |
| HTTP request lifetime to detached dispatcher lifetime | Client cancellation must stop query work without silently discarding already-owned checkpoint records. |
| Historical artifacts to current verification | Reviewers must not treat an overclaiming summary as executable proof. |
| Local filesystem (developer machine) -> engine process | `LANCET_ENGINE__LANCEDB_PATH` / `seed_rag_fixture --lancedb-path` accept an operator-supplied filesystem path; the engine reads/writes LanceDB tables at that path with process-level permissions. |
| Node implementation to runner dispatch | A missing or fallback match can skip timeout, event, or failure semantics. |
| NodeFailedEvent.category / WorkflowCompletedEvent.error_kind -> SSE client | The typed error category crosses the gRPC-stream-to-SSE boundary and becomes client-visible JSON; this plan inherits, and does not modify, D-22's existing category+message design. |
| Per-variant candidates -> cross-variant RRF | Candidate ranks and scores influence final ordering and can carry non-finite or adversarial values. |
| Phase test module to workflow ports | Tests import fake implementations that can affect event and state assertions. |
| PostgreSQL -> test inspection | Integration fixtures create isolated schemas and inspect ordered rows. |
| Production query handler to binary test harness | Untrusted request validation, node ordering, event cardinality, and failure behavior cross the production test boundary. |
| Protobuf event stream to gateway SSE | Typed event data is mapped into browser/client JSON over an HTTP stream. |
| Protobuf schema to generated artifacts | Buf transforms the checked-in schema into Rust and Go runtime types. |
| Public prompt API to callers | Documentation and error semantics govern how cancellation and graph context are interpreted. |
| Reformulation output to downstream adapters | Excess variants can amplify work and must be rejected before fan-out. |
| Reformulation variants -> RetrieveHybrid | Ordered variant strings and their retrieval outputs control bounded per-variant work. |
| Reformulation variants to retrieval snapshot | Multiple variants affect result provenance and must remain auditable. |
| Retrieval ports to fusion provenance | Dense and BM25 source labels influence which candidates are included in source-specific calculations. |
| Rust GenerateAnswer node to provider attempt loop | A transient failure can cause an additional paid request and must remain bounded. |
| Rust adapter to OpenRouter capability endpoint | Provider responses and transport failures determine whether generation may proceed or retry. |
| Rust checkpoint event -> Go SQL parameters | Provider-derived and accumulated context bytes enter a parameterized persistence path. |
| Rust checkpoint event -> Go dispatcher | Full snapshot payloads cross the runtime boundary and must remain bounded, ordered, and non-blocking to query progress. |
| Rust checkpoint frame -> Go dispatcher | Full workflow context crosses into a bounded asynchronous persistence handoff. |
| Rust engine <-> Go gateway wire contract (buf-generated types) | proto/lancet/v1/lancet.proto is the single source of truth for both runtimes' NodeErrorKind discriminants; drift between the checked-in Rust and Go generated files would silently corrupt cross-service error-category interpretation. |
| Rust engine to Go gateway | Generated messages cross the runtime boundary with published field numbers. |
| Rust gRPC stream to Go gateway | Untrusted or failed upstream frames cross into SSE mapping and must retain typed identity. |
| Rust generated message to encoded wire bytes | Descriptor tags and round-trip values cross the serialization boundary. |
| Rust generation node -> external provider | Prompt, model settings, and retry behavior cross the provider boundary. |
| Rust workflow -> generated protobuf | Internal state and failure details are serialized into a client-visible event envelope. |
| Rust workflow runner to protobuf event sink | Untrusted or degraded node outcomes become client-visible terminal events. |
| Rust workflow to Go stream | Workflow events and checkpoint snapshots cross the gRPC stream boundary and must retain identity and type separation. |
| Rust workflow to event receiver | A closed or saturated receiver can otherwise lose lifecycle or terminal evidence or stall the query. |
| Rust workflow to external providers and stores | Embedding, graph, retrieval, and generation calls may stall or fail independently. |
| Rust workflow to retrieval and model adapters | External database, graph, embedding, reranker, and provider calls can stall, fail, or return malformed data. |
| Source artifacts to follow-up plans | Requirement and decision identifiers guide implementation and must not be silently rewritten. |
| Terminal state to client | Duplicate or fabricated terminal events could misrepresent workflow success. |
| Test fixtures to production build | Fake ports can accidentally become runtime dependencies if compilation boundaries are absent. |
| Tokio timer to test harness | Paused-clock tests can falsely pass or hang if scheduling and receiver cleanup are not bounded. |
| Typed error to event contract | Retryability must describe the actual provider/node state. |
| Workflow runner to provider preparation | A capability request can delay or fail before generation starts. |
| WorkflowContext to checkpoint JSON | Full accumulated state crosses a persistence boundary and must retain identity and field separation. |
| WorkflowContext to prompt/generation adapters | Typed graph facts and evidence cross into provider-facing request construction. |
| client -> Rust tonic stream | Untrusted request fields and client cancellation cross into the workflow runner. |
| client disconnect -> detached persistence | Request cancellation can overlap a background insert and must not create partial JSON. |
| config/config.toml -> engine process (production boundary, unaffected by this plan) | Ambient file the engine reads by default; this plan's override exists specifically so the two tests stop depending on it. |
| focused registration guard -> CI command | Shell filtering determines whether the intended tests actually ran. |
| graph failure -> workflow context | A graph backend timeout/error determines whether evidence is degraded or the query fails. |
| provider response -> client event stream | Untrusted structured output becomes validated answer events. |
| retrieval candidates -> RRF accumulator | Untrusted or malformed source scores can affect ranking and memory use. |
| test fixture -> workflow ports | Controlled fakes inject failures, delays, malformed scores, and cancellation points. |
| workflow -> event/checkpoint assertions | Test collection observes all client-visible and persistence-bound outcomes. |
| workflow context -> prompt serializer | Retrieved/graph text becomes a provider request and checkpoint payload. |
| workflow request -> injected retrieval ports | Query text, embeddings, graph queries, and candidate scores reach multiple async implementations. |

---

## Threat Register

114 threats across 26 plans. `Plan` records the originating PLAN file so duplicate-looking
IDs stay attributable (e.g. `T-05-02` belongs to 05-01; 05-02 uses `T-05-02-01`…`-05`).
IDs are reproduced verbatim — note that 05-25/05-26 use a dot (`T-05.25-01`), not a dash.

| Plan | Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|------|-----------|----------|-----------|----------|-------------|------------|--------|
| 05-01 | T-05-01 | Tampering | QueryRAG request validation | high | mitigate | Validate and mint identity before stream creation; malformed input is a plain typed Status. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-01 | T-05-02 | Information disclosure | WorkflowEvent failure/checkpoint payload | medium | mitigate | Use D-22 safe human messages, preserve typed kinds, and keep provider/raw secrets out of event fields. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-01 | T-05-03 | Denial of service | runner/event/checkpoint channels | high | mitigate | Bound channels, select cancellation first, and require pending/overflow delivery semantics instead of silent loss. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-01 | T-05-04 | Spoofing | trace_id/session_id | medium | mitigate | Derive trace_id from validated request correlation_id and keep session_id distinct per D-29. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-01 | T-05-SC | Tampering | Cargo dependency transition | high | mitigate | Use the approved package-legitimacy audit for existing `tokio-util`/`tokio-stream` dependencies and run locked generation/build checks. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-02 | T-05-02-01 | Denial of service | cross-variant RRF accumulator | high | mitigate | Reject more than eight variants with typed InputValidation before retrieval; for admitted inputs cap per-source candidates, process finite scores only, and assert bounded provenance memory without truncating D-07 contributions. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-02 | T-05-02-02 | Tampering | candidate scores/ranks | high | mitigate | Reject non-finite scores and contributions and use deterministic tie-breaking before reranking. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-02 | T-05-02-03 | Information disclosure | graph/retrieval error messages | medium | mitigate | Store only sanitized degrade/failure details and map external events to D-22 safe messages. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-02 | T-05-02-04 | Denial of service | graph/retrieval async calls | high | mitigate | Use injectable per-node timeouts, cancellation-first selection, and inner graph timeout degradation. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-02 | T-05-02-05 | Spoofing | variant/provenance identity | medium | mitigate | Preserve request-local ordered variant indices and trace context; do not accept caller-supplied provenance. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-03 | T-05-03-01 | Tampering | generation retry request | high | mitigate | Capture the first request and assert byte-identical retry parameters with a two-call ceiling. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-03 | T-05-03-02 | Information disclosure | prompt/checkpoint/event payload | high | mitigate | Preserve existing provider redaction/safe error conventions and validate structured output before emitting answer fields. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-03 | T-05-03-03 | Denial of service | generation node deadline | high | mitigate | Keep 65s outer and 30s per-attempt budgets distinct, race cancellation first, and test sub-second overrides. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-03 | T-05-03-04 | Spoofing | answer/terminal success events | high | mitigate | Centralize terminal ownership and emit answer events only after schema validation and successful node completion. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-03 | T-05-03-05 | Repudiation | full workflow snapshots | medium | mitigate | Include trace_id, sequence_ordinal, and all accumulated context fields at every node boundary. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-04 | T-05-04-01 | Denial of service | detached workflow tasks | high | mitigate | AbortOnDrop guard, cancellation cases, and task-count assertions prove no lingering runner. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-04 | T-05-04-02 | Tampering | fake scores/event taxonomy | medium | mitigate | Assert exact error categories, finite score rejection, event ordering, and no success fabrication. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-04 | T-05-04-03 | Repudiation | checkpoint snapshots | medium | mitigate | Assert trace identity, sequence ordinals, full accumulated fields, and explicit pending ownership. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-04 | T-05-04-04 | Tampering | test registration | high | mitigate | Filter comments/headers and require positive focused-test counts so skipped coverage cannot pass silently. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-05 | T-05-05-01 | Injection | InsertWorkflowCheckpoint | high | mitigate | Use generated parameterized sqlc insert, never string-built SQL, and validate JSONB through the database. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-05 | T-05-05-02 | Information disclosure | context_snapshot JSONB/SSE DTO | high | mitigate | Keep raw snapshots in the explicitly accepted durable boundary, strip them from SSE, and log only safe failure metadata. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-05 | T-05-05-03 | Denial of service | detached sink/dispatcher | high | mitigate | Reuse primary-1/overflow-5/pending ownership, bounded write context, drain on close, and prove FinalAnswer is not blocked. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-05 | T-05-05-04 | Repudiation | trace/order columns | medium | mitigate | Persist trace_id and sequence_ordinal and index/query them together; do not rely on timestamp ordering. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-05 | T-05-05-05 | Tampering | integration test isolation | high | mitigate | Use unique per-test schema for every writer/reader and make setup/snapshot errors fatal. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-06 | T-05-06-01 | Denial of service | SSE route timeout/flush | high | mitigate | Remove only `/rag/query` from the blanket 60-second timeout, retain node-level bounds, and flush incrementally without whole-stream buffering. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-06 | T-05-06-02 | Spoofing | SSE identity headers | high | mitigate | Copy identity only from prefetched Rust event fields; retain trace_id consistency and do not accept client-supplied identity as authoritative. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-06 | T-05-06-03 | Information disclosure | SSE/checkpoint serialization | medium | mitigate | Forward typed safe event fields, keep checkpoint frames transport-only, and preserve D-22 safe error messages. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-06 | T-05-06-04 | Denial of service | checkpoint overflow | high | mitigate | Own FIFO overflow and pending envelopes, drain on close, and make acceptance results explicit instead of silently dropping full-channel records. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-06 | T-05-06-05 | Tampering | generated protobuf/API boundary | high | mitigate | Generate Rust and Go from the same proto in one task and run compile plus cross-runtime tests before completion. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-07 | T-05-07-01 | Tampering | proto/lancet/v1/lancet.proto NodeErrorKind enum | medium | mitigate | Append-only: NODE_ERROR_KIND_INPUT_VALIDATION is added at the next unused wire number (9); <verify> greps that all nine existing variants keep their exact number and name, so no already-serialized or in-flight NodeFailedEvent from either runtime can be reinterpreted as a different category after this change ships. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-07 | T-05-07-02 | Tampering | engine/src/pb/lancet/v1/lancet.v1.rs, gateway/proto/lancet/v1/lancet.pb.go | medium | mitigate | Both files are produced exclusively by `buf generate` (clean: true) from the single proto source of truth, never hand-edited; <verify> greps the regenerated content structurally and a git-diff scope guard confirms no hand-written Go/Rust logic file was touched in the same change. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-07 | T-05-07-03 | Information disclosure | NodeFailedEvent.category exposed to SSE/gRPC clients | low | accept | The category is only a client-visible enum discriminant (InputValidation), not free-form text; this plan adds no new message-construction call site (05-02 owns that), and D-22 already approved exposing typed categories to clients as the intended UX — no new mitigation is needed beyond what D-22 already accepted. | closed — accepted risk |
| 05-08 | T-05-08-01 | Tampering | `query_rag` request context | high | mitigate | Validate session, correlation, query, and filter before creating the stream; carry the validated request into every adapter. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-08 | T-05-08-02 | Denial of service | Production retrieval and generation adapters | high | mitigate | Route all work through cancellable workflow nodes so the timeout and disconnect plans can bound every real I/O operation. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-08 | T-05-08-03 | Information disclosure | Workflow event and checkpoint boundary | medium | mitigate | Keep checkpoint JSON in checkpoint events only and keep provider errors typed and human-safe; Go SSE mapping is covered by 05-11. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-08 | T-05-08-04 | Spoofing | Session and trace identity | medium | mitigate | Set trace_id from correlation_id per D-29 and use the validated session identity for every event and snapshot. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-08 | T-05-08-05 | Repudiation | Production workflow history | medium | mitigate | Populate full context and preserve node identity so later checkpoint rows can explain the request path. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-09 | T-05-09-01 | Tampering | `[engine.workflow]` parser | high | mitigate | Deny unknown workflow fields and reject non-positive values before the engine starts serving requests. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-09 | T-05-09-02 | Denial of service | Node deadlines | high | mitigate | Apply per-node and nested operation timeouts to the real adapters, including the 65-second generation outer budget. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-09 | T-05-09-03 | Denial of service | Client disconnect cancellation | high | mitigate | Tie stream drop and sender closure to CancellationToken cancellation and cancellation-first selects. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-09 | T-05-09-04 | Information disclosure | Provider error handling | medium | mitigate | Preserve typed safe NodeError categories and do not expose provider credentials or raw transport details in stream failures. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-09 | T-05-09-05 | Repudiation | Timeout versus cancellation classification | medium | mitigate | Add deterministic tests that distinguish Timeout from Cancelled and retain trace/session identity on terminal events. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-10 | T-05-10-01 | Denial of service | WorkflowEventSink | high | mitigate | Use cancellation-aware client sends and bounded owned checkpoint pending state; surface closed/saturated outcomes. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-10 | T-05-10-02 | Tampering | Event and checkpoint ordinals | high | mitigate | Allocate one ordinal per outer event and serialize the same value inside the checkpoint payload. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-10 | T-05-10-03 | Tampering | Terminal emission | high | mitigate | Guard all terminal paths with one atomic compare-and-set and test duplicate completion. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-10 | T-05-10-04 | Information disclosure | Checkpoint serializer | medium | mitigate | Keep full snapshot JSON in checkpoint events only and keep it out of the response DTO. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-10 | T-05-10-05 | Repudiation | Workflow history | medium | mitigate | Preserve notices, trace/session identity, complete context, and ordered lifecycle events for reconstruction. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-10 | T-05-10-06 | Denial of service | Indefinitely retained checkpoint payload | medium | mitigate | D-24 retains the complete D-28 logical snapshot; keep evidence/prompt/answer/retrieval content lossless, encode any internal query embedding as a deterministic fixed-size digest, record serialized size, and add no public fetch or compaction surface. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-11 | T-05-11-01 | Information disclosure | SSE response mapping | high | mitigate | Keep checkpoint payloads out of SSE DTOs, guard nil responses, and log transport errors without emitting raw provider details. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-11 | T-05-11-02 | Tampering | Checkpoint envelope identity | high | mitigate | Preserve trace, session, node, and one-source sequence ordinals through envelope creation and parameterized insert. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-11 | T-05-11-03 | Denial of service | Dispatcher backpressure | high | mitigate | Use bounded pending ownership, nonblocking handoff, explicit failure, and deterministic drain on Close. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-11 | T-05-11-04 | Spoofing | Request and gRPC correlation | medium | mitigate | Forward validated session and correlation identity and assert it in raw SSE and database tests. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-11 | T-05-11-05 | Information disclosure | Raw checkpoint query content | medium | accept | D-23 explicitly accepts local raw-content checkpoint storage for this phase; access remains behind the Go-owned database boundary and no client fetch API is added. | closed — accepted risk |
| 05-11 | T-05-11-06 | Repudiation | Workflow checkpoint history | medium | mitigate | Persist full snapshots and ordered rows, use isolated schemas in tests, and fail query errors rather than treating missing evidence as success. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-12 | T-05-12-01 | Tampering | Traceability errata | medium | mitigate | Validate exact plan-declared ORCH lists, source headings, and preservation language with an automated check. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-12 | T-05-12-02 | Repudiation | Historical plan and summary record | medium | mitigate | Preserve executed files and document the difference between baseline evidence and follow-up closure. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-12 | T-05-12-03 | Information disclosure | Planning artifacts | low | accept | The artifact contains engineering traceability only and does not add runtime data or credentials. | closed — accepted risk |
| 05-12 | T-05-12-04 | Tampering | Historical Phase 05 PLAN/SUMMARY paths | high | mitigate | Compare all fourteen current blobs with their immutable pre-revision HEAD hashes, reject staged or unstaged changes to those paths, and fail on any `git diff --check` error. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-13 | T-05-13-01 | Denial of service | Capability preflight | high | mitigate | Give preflight a dedicated short timeout and cache only successful capability responses so a slow or failed endpoint cannot consume the generation attempt budget or poison future calls. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-13 | T-05-13-02 | Denial of service | GenerateAnswer retry loop | high | mitigate | Enforce one immediate retry, preserve the exact request, check cancellation before retry, and prohibit a third attempt or alternate provider. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-13 | T-05-13-03 | Tampering | Provider error classification | high | mitigate | Map transport, capability, and generation outcomes through explicit typed error kinds and test retryability from the resulting state rather than a caller literal. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-13 | T-05-13-04 | Information disclosure | Provider failure messages | medium | mitigate | Emit safe typed NodeError messages without credentials, raw request bodies, or provider secrets. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-13 | T-05-13-05 | Repudiation | Generation attempt history | medium | mitigate | Capture request identity and exact attempt counts in focused local harness tests while retaining D-15's absence of a retrying event. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-14 | T-05-14-01 | Tampering | NodeKind dispatch | high | mitigate | Use a closed enum and exhaustive typed matches for every runner decision. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-14 | T-05-14-02 | Denial of service | Reformulation fan-out | high | mitigate | Reject nine variants before downstream adapter calls and completion. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-14 | T-05-14-03 | Tampering | NodeFailed.retryable | medium | mitigate | Forward typed NodeError retryability from 05-13; do not use a caller literal. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-14 | T-05-14-04 | Repudiation | Node lifecycle history | medium | mitigate | Preserve exact five-node labels and D-06 order in typed dispatch tests. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-15 | T-05-15-01 | Tampering | Prompt assembly semantics | medium | mitigate | Document and test graph_weight and cancellation behavior against the existing prompt implementation. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-15 | T-05-15-02 | Denial of service | Synchronous prompt wrappers | medium | mitigate | Remove public blocking wrappers or gate them to tests so production async paths cannot block the runtime. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-15 | T-05-15-03 | Tampering | Fake workflow ports | high | mitigate | cfg(test)-gate all six fake definitions and assert their source boundaries. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-15 | T-05-15-04 | Information disclosure | Prompt errors | medium | mitigate | Preserve typed safe errors and do not add raw provider or prompt content to public docs or events. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-16 | T-05-16-01 | Tampering | Graph notice codes | high | mitigate | Use exact GRAPH_TIMEOUT/GRAPH_DEGRADED codes and typed merge tests. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-16 | T-05-16-02 | Repudiation | Workflow notices | medium | mitigate | Append and preserve earlier notice entries through later outcomes and checkpoints. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-16 | T-05-16-03 | Tampering | RetrievalSnapshot provenance | medium | mitigate | Persist variant_count and ordered identities beside result provenance. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-16 | T-05-16-04 | Denial of service | BM25 RwLock | high | mitigate | Snapshot an Arc handle before await, migrate the 1 production and 18 test construction sites, and use a test-owned writer during a stalled retrieval to prove the lock is released. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-17 | T-05-17-01 | Tampering | RetrievalSnapshot and WorkflowCompletedEvent tags | critical | mitigate | Use only additive tags 10/11 and 6, preserve existing tags, and verify source plus generated field names. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-17 | T-05-17-02 | Tampering | Buf-generated bindings and hand-written module glue | high | mitigate | Guard mod.rs before/after generation, require exact output inventory, run lint, and compare repeated-generation hashes. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-17 | T-05-17-03 | Information disclosure | variant_identities payload | medium | mitigate | Carry only D-07/D-08 accepted ordered identities and exclude D-30 generic metadata. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-17 | T-05-17-SC | Tampering | npm/pip/cargo installs | high | accept | This plan adds no package-manager dependency or install task; the slopcheck register is not applicable. | closed — accepted risk |
| 05-18 | T-05-18-01 | Tampering | Target registration and cfg(test) seam | high | mitigate | Assert one library registration, no binary registration, exact library test execution, and binary compilation. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-18 | T-05-18-02 | Denial of service | Phase workflow test harness | medium | mitigate | Keep the compile probe side-effect free and require exact named test execution so a skipped module cannot satisfy the gate. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-18 | T-05-18-03 | Repudiation | Fake workflow ports | low | mitigate | Reference every named fake in a registered library test and preserve the existing concrete fixture behavior. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-18 | T-05-18-SC | Tampering | npm/pip/cargo installs | high | accept | This plan adds no package-manager dependency or install task; the standard slopcheck register is not applicable to this target-registration change. | closed — accepted risk |
| 05-19 | T-05-19-01 | Tampering | Failed WorkflowCompleted terminal | critical | mitigate | Pass cloned accumulated notices, keep success false and final_response absent, and assert event order and answer-event exclusion. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-19 | T-05-19-02 | Repudiation | Degraded notices on failure | high | mitigate | Preserve code, message, severity, and order in typed protobuf notices and assert the same values in raw SSE. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-19 | T-05-19-03 | Information disclosure | Gateway terminal JSON | medium | mitigate | Serialize only the typed Notice fields and omit final_response for failed terminals; do not add generic workflow metadata. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-19 | T-05-19-SC | Tampering | npm/pip/cargo installs | high | accept | This plan adds no package-manager dependency or install task; the standard slopcheck register is not applicable to terminal-event wiring. | closed — accepted risk |
| 05-20 | T-05-20-01 | Denial of service | Capability bootstrap | critical | mitigate | Run the dedicated preflight deadline before the node timer, preserve cancellation, and assert the preflight cannot consume the generation-node retry window. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-20 | T-05-20-02 | Denial of service | GenerateAnswer retry loop | critical | mitigate | Bound provider attempts at 30000ms, allow exactly one retry, assert two attempts in the paused-clock test, and reject a third attempt. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-20 | T-05-20-03 | Tampering | Workflow timeout configuration | high | mitigate | Consume the 05-09-owned seven-key configuration, assert the 65000ms generation-node budget with inter-attempt slack, and record the 102000ms figure as a derived, non-enforced whole-workflow bound from the 97-second pre-preflight total plus the additive 5000ms capability preflight; explicitly accept that no global deadline enforces this sum unless one is added, without introducing a competing timeout value. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-20 | T-05-20-04 | Denial of service | workflow_phase5_happy_path receiver | medium | mitigate | Wrap receiver draining in a five-second timeout and retain AbortOnDrop cleanup for the spawned runner. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-20 | T-05-20-05 | Denial of service | Gateway request and workflow lifetime | medium | accept | Per D-17, D-18, D-19, and D-21, `/rag/query` remains outside the legacy 60-second chi middleware and has no new global workflow deadline or resume mechanism; request-context/client-disconnect cancellation and independent node timers are the accepted whole-request lifetime boundary for this phase, while 05-20 proves only the derived component arithmetic. | closed — accepted risk |
| 05-20 | T-05-20-SC | Tampering | npm/pip/cargo installs | high | accept | This plan adds no package-manager dependency or install task; the standard slopcheck register is not applicable to timer-boundary changes. | closed — accepted risk |
| 05-21 | T-05-21-01 | Tampering | Provenance source filter | high | mitigate | Use an equality-comparable enum at construction and filter sites and assert vector/BM25 source behavior in the retrieval test module. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-21 | T-05-21-02 | Repudiation | Candidate provenance serialization | medium | mitigate | Preserve lowercase serialized values and exact rank/score assertions so source attribution remains inspectable. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-21 | T-05-21-03 | Information disclosure | Serde field behavior | low | mitigate | Remove the ineffective default and keep the existing serialized field shape without adding unrelated metadata. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-21 | T-05-21-SC | Tampering | npm/pip/cargo installs | high | accept | This plan adds no package-manager dependency or install task; the standard slopcheck register is not applicable to fusion type cleanup. | closed — accepted risk |
| 05-22 | T-05-22-01 | Tampering | GraphFactBlock prompt/generation handoff | high | mitigate | Pass one typed WorkflowContext vector into both prompt packing and GenerationRequest, then assert the marker at the actual provider boundary. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-22 | T-05-22-02 | Spoofing | Production node/event assertions | high | mitigate | Invoke the named production builder and require exact D-06 NodeStarted order plus D-01/D-02 event cardinality in the binary target. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-22 | T-05-22-03 | Information disclosure | Provider-facing workflow context | medium | mitigate | Preserve D-30/D-31 exclusions and assert typed facts without adding generic metadata or tracing spans. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-22 | T-05-22-04 | Denial of service | Zero-evidence and graph-degradation branches | medium | mitigate | Require zero-evidence short-circuiting and bounded typed degradation instead of entering prompt/generation or fabricating output. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-22 | T-05-22-SC | Tampering | npm/pip/cargo installs | high | accept | This plan adds no package-manager dependency or install task; the slopcheck register is not applicable. | closed — accepted risk |
| 05-23 | T-05-23-01 | Tampering | Rust message construction sites | high | mitigate | Enumerate every literal, require explicit new fields, and compile both library and binary targets. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-23 | T-05-23-02 | Tampering | RetrievalSnapshot wire encoding | critical | mitigate | Assert tags 1 through 11, encode/decode populated values, and require exact test registration. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-23 | T-05-23-03 | Information disclosure | variant_identities | medium | mitigate | Restrict the wire test to D-07/D-08 ordered identities and exclude generic metadata under D-30. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-23 | T-05-23-SC | Tampering | npm/pip/cargo installs | high | accept | This plan adds no package-manager dependency or install task; the slopcheck register is not applicable. | closed — accepted risk |
| 05-24 | T-05-24-01 | Denial of service | RetrieveHybrid variant loop | high | mitigate | Consume only the already-admitted maximum of eight variants, invoke bounded per-variant fusion once each, preserve candidate limits, and retain no unbounded flattened request accumulator. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-24 | T-05-24-02 | Tampering | cross-variant score accumulator | high | mitigate | Use the documented one-based-rank formula, reject non-finite contributions/totals, and apply deterministic tie/order rules proved by exact tests. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-24 | T-05-24-03 | Repudiation | VariantProvenance retention | medium | mitigate | Carry every inner vector/BM25 provenance contribution through the second pass and assert its exact retention in the two-variant regression. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-24 | T-05-24-SC | Tampering | npm/pip/cargo installs | high | accept | This plan adds no package-manager dependency or install task; no package legitimacy decision is introduced. | closed — accepted risk |
| 05-25 | T-05.25-01 | Tampering | `LANCET_ENGINE__LANCEDB_PATH` / `seed_rag_fixture --lancedb-path` | low | accept | Pre-existing, unchanged behavior: both already accept an operator-controlled path (config.toml default + explicit override); this plan does not widen that surface, and the tool is a local dev/test utility, not a network-facing service. | closed — accepted risk |
| 05-25 | T-05.25-02 | Information Disclosure | validate_schema's error message | low | accept | The added remediation clause is generic operational guidance (rename/regenerate the store); it does not reveal secrets, credentials, or row-level data — only static field-schema mismatches already present in the pre-existing error format. | closed — accepted risk |
| 05-26 | T-05.26-01 | Tampering | `assertCleanRAGChildEnv` allowlist / `ragChildEnv(...)` | low | mitigate | The new `LANCET_OPENROUTER__GENERATION_MODEL` and `LANCET_OPENROUTER__EMBEDDING_MODEL` entries are added to the explicit allowlist (same treatment as sibling endpoint overrides) so `assertCleanRAGChildEnv` still fails the test if any *other*, unexpected `LANCET_*`/`OPENROUTER_*` variable leaks into the spawned child — the allowlist stays a closed set. | closed — blanket acceptance AR-05-16 (plan-declared mitigation, unverified this run) |
| 05-26 | T-05.26-02 | Tampering | engine/src/main.rs's new override blocks | low | accept | Mirrors the existing empty-string-guarded pattern used by the other `LANCET_OPENROUTER__*` overrides; only deliberately non-empty values take effect, at the same trust level as config.toml itself (both are operator/process-launcher controlled, not attacker-controlled network input). | closed — accepted risk |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above `workflow.security_block_on` (high) count toward `threats_open`*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

### Severity / disposition tally

| Severity | mitigate | accept | total |
|----------|----------|--------|-------|
| critical | 5 | 0 | 5 |
| high | 50 | 8 | 58 |
| medium | 41 | 2 | 43 |
| low | 3 | 5 | 8 |
| **total** | **99** | **15** | **114** |

---

## Accepted Risks Log

All 15 `accept`-disposition threats from the Phase 05 plan-time registers, accepted at the
`/gsd-secure-phase 5` Step 4 gate on 2026-08-19. Rationale is the PLAN-time text, verbatim.
The eight `-SC` entries are supply-chain slopcheck registers asserting the plan introduces no
package-manager dependency; they carried `high` severity and were the blocking set before this
acceptance was recorded.

| Risk ID | Threat Ref | Severity | Rationale | Accepted By | Date |
|---------|------------|----------|-----------|-------------|------|
| AR-05-01 | T-05-07-03 (05-07) | low | The category is only a client-visible enum discriminant (InputValidation), not free-form text; this plan adds no new message-construction call site (05-02 owns that), and D-22 already approved exposing typed categories to clients as the intended UX — no new mitigation is needed beyond what D-22 already accepted. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-02 | T-05-11-05 (05-11) | medium | D-23 explicitly accepts local raw-content checkpoint storage for this phase; access remains behind the Go-owned database boundary and no client fetch API is added. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-03 | T-05-12-03 (05-12) | low | The artifact contains engineering traceability only and does not add runtime data or credentials. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-04 | T-05-17-SC (05-17) | high | This plan adds no package-manager dependency or install task; the slopcheck register is not applicable. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-05 | T-05-18-SC (05-18) | high | This plan adds no package-manager dependency or install task; the standard slopcheck register is not applicable to this target-registration change. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-06 | T-05-19-SC (05-19) | high | This plan adds no package-manager dependency or install task; the standard slopcheck register is not applicable to terminal-event wiring. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-07 | T-05-20-05 (05-20) | medium | Per D-17, D-18, D-19, and D-21, `/rag/query` remains outside the legacy 60-second chi middleware and has no new global workflow deadline or resume mechanism; request-context/client-disconnect cancellation and independent node timers are the accepted whole-request lifetime boundary for this phase, while 05-20 proves only the derived component arithmetic. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-08 | T-05-20-SC (05-20) | high | This plan adds no package-manager dependency or install task; the standard slopcheck register is not applicable to timer-boundary changes. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-09 | T-05-21-SC (05-21) | high | This plan adds no package-manager dependency or install task; the standard slopcheck register is not applicable to fusion type cleanup. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-10 | T-05-22-SC (05-22) | high | This plan adds no package-manager dependency or install task; the slopcheck register is not applicable. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-11 | T-05-23-SC (05-23) | high | This plan adds no package-manager dependency or install task; the slopcheck register is not applicable. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-12 | T-05-24-SC (05-24) | high | This plan adds no package-manager dependency or install task; no package legitimacy decision is introduced. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-13 | T-05.25-01 (05-25) | low | Pre-existing, unchanged behavior: both already accept an operator-controlled path (config.toml default + explicit override); this plan does not widen that surface, and the tool is a local dev/test utility, not a network-facing service. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-14 | T-05.25-02 (05-25) | low | The added remediation clause is generic operational guidance (rename/regenerate the store); it does not reveal secrets, credentials, or row-level data — only static field-schema mismatches already present in the pre-existing error format. | operator (gate: accept-all) | 2026-08-19 |
| AR-05-15 | T-05.26-02 (05-26) | low | Mirrors the existing empty-string-guarded pattern used by the other `LANCET_OPENROUTER__*` overrides; only deliberately non-empty values take effect, at the same trust level as config.toml itself (both are operator/process-launcher controlled, not attacker-controlled network input). | operator (gate: accept-all) | 2026-08-19 |
| AR-05-16 | 99 mitigate-disposition threats (all Phase 05 plans) | high | Operator elected "Accept all open — document only" at the `/gsd-secure-phase 5` Step 4 gate, explicitly declining per-threat mitigation verification for the 55 critical/high and 44 medium/low `mitigate` threats. Closure rests on the plan-time mitigation declarations recorded in the register above, plus sibling evidence in `05-VERIFICATION.md` / `05-VALIDATION.md` / `05-REVIEW.md` / `05-SOURCE-AUDIT.md` — not on this run. | operator (gate: accept-all) | 2026-08-19 |

This blanket entry exists so the 99 `mitigate` rows have a real closure mechanism. Without it a future audit run would find no documented basis for their status and legitimately reopen all 99, including the 55 at critical/high.


---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-08-19 | 114 | 114 | 0 | `/gsd-secure-phase 5` (orchestrator; auditor subagent declined at gate) |

### Security Audit 2026-08-19

| Metric | Count |
|--------|-------|
| Threats found | 114 |
| Closed | 114 |
| Open | 0 |
| Closed by documented acceptance (per-threat, AR-05-01…15) | 15 |
| Closed by blanket acceptance AR-05-16 (plan-declared mitigation, not independently verified) | 99 |
| Plans with no threat model | 1 (05-27) |

Preliminary classification found `threats_open: 8` — the `high`/`accept` `-SC` threats, OPEN
only because no SECURITY.md existed to document them. Recording them in the Accepted Risks Log
above closes them. No ASVS L1 short-circuit was taken; the Step 4 gate was presented and answered.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter
- [ ] Mitigation controls independently verified against implementation — **not done**; re-run with "Verify all open threats"
- [ ] Threat model authored for 05-27 (G-05-1 provider body-limit change)

**Approval:** verified 2026-08-19 (documentation-level; see *Verification Depth* above)
