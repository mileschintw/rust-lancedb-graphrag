# Deferred Items

## Accepted Phase 03 MVP scope debt

Source of record: accepted MVP scope decision during Phase 03 planning (2026-07-31). The MVP proves one runnable happy path: a valid query searches the completed corpus through vector and BM25 retrieval, fuses bounded evidence, and receives one structured LLM answer. The items below are intentionally excluded from the current implementation plan; safeguards that are necessary to make that happy path trustworthy remain in scope.

The revised five-plan execution order distributes that same scope across retrieval/dependencies, provider contracts, gRPC/startup readiness, gateway/embedding configuration, and the isolated local cross-runtime proof. This split does not promote any item below into implementation; initial BM25 construction/readiness remains in scope, while dynamic restart/re-ingestion recovery remains `DEBT-RAG-04`.

### DEBT-RAG-01 — Degraded retrieval and model-only fallback

- **Rationale:** The first usable slice must prove retrieval-grounded generation before expanding behavior for missing, weak, unnecessary, or failed evidence.
- **Known risk:** A vector or BM25 failure, empty result, or weak result may currently fail the request or lack an explicit `model_only` answer basis instead of degrading transparently.
- **Current constraints:** MVP verification uses a valid query over a query-ready completed corpus where both retrieval paths succeed; do not claim degraded-mode support.
- **Trigger:** Any claim that RAG-03 is fully implemented, any deployment with unreliable indexes/providers, or any shared/public use.
- **Target:** Phase 06 hardening/evaluation, or earlier if the trigger occurs.
- **Future acceptance criteria:** One-path failure returns a useful surviving-path answer with a machine-readable warning; both-path failure returns an explicit model-only basis and notice with no citations; weak/empty evidence follows the documented answer-basis contract.

### DEBT-RAG-02 — Provider failure, timeout, retry, and fallback behavior

- **Rationale:** The MVP needs one successful provider call to prove the vertical path; orchestration retries and alternate-provider policy belong outside the first slice.
- **Known risk:** Provider timeout, cancellation, structured-output rejection, or transport failure may not yet have the final structured error and retry/fallback behavior.
- **Current constraints:** Use one bounded generation attempt with an injectable test provider; do not add retries or alternate-provider orchestration.
- **Trigger:** Provider instability, workflow orchestration, or a requirement for production-grade availability.
- **Target:** Phase 05 orchestration for retry/fallback policy, with Phase 06 hardening for evaluation.
- **Future acceptance criteria:** Timeout/cancellation and provider errors are classified and surfaced with session/correlation identity; retry and fallback policy is explicit, bounded, and tested without fabricating answers.

### DEBT-RAG-03 — Citation repair and transparent downgrade

- **Rationale:** The happy path can validate structured citation IDs against the supplied evidence; repair of malformed or unsupported model markers is a separate failure path.
- **Known risk:** Malformed or unsupported citation markers may be rejected or left without the final repair-and-downgrade behavior.
- **Current constraints:** Happy-path tests use valid structured citations that resolve to selected bounded evidence.
- **Trigger:** Any invalid-marker production trace or a requirement to claim full citation-integrity coverage.
- **Target:** Phase 06 hardening/evaluation.
- **Future acceptance criteria:** One bounded repair attempt is made without another provider call; unresolved markers are removed, the answer basis is downgraded transparently, and a machine-readable warning is emitted.

### DEBT-RAG-04 — Re-ingestion/restart recovery and cross-index atomic visibility

- **Rationale:** The MVP must build the initial BM25 snapshot before the first query-ready state, but replacement and restart recovery are broader lifecycle paths.
- **Known risk:** A future re-ingestion or restart could expose mixed vector/BM25 generations or serve before the lexical index is rebuilt.
- **Current constraints:** Build and verify the initial BM25 snapshot before accepting the first query; query tests use one completed corpus and must not claim replacement/restart freshness coverage.
- **Trigger:** Re-ingestion, engine restart during index updates, or any deployment where stale or mixed evidence is unacceptable.
- **Target:** Phase 06 hardening/evaluation.
- **Future acceptance criteria:** BM25 rebuild completes before readiness; old and new representations switch together; generation metadata proves no mixed evidence is served during replacement or recovery.

### DEBT-RAG-06 — Graph-extraction unavailability in RAG-03

- **Rationale:** Graph context extraction belongs to Phase 04; the Phase 03 happy path uses completed source chunks and does not depend on graph context.
- **Known risk:** If graph extraction is unavailable, the eventual full RAG-03 contract may not yet describe or test the resulting degraded response.
- **Current constraints:** Do not implement graph extraction or graph-failure fallback in Phase 03. The happy path must remain runnable from source chunks alone.
- **Trigger:** Phase 04 graph context becomes part of the query path, or RAG-03 is claimed complete across graph and retrieval failures.
- **Target:** Phase 04 for the typed graph-context seam; Phase 06 hardening/evaluation for full degraded behavior.
- **Future acceptance criteria:** Graph-unavailable queries retain a useful typed response or documented model-only/degraded basis, with machine-readable warning behavior and tests that do not require graph data for source-chunk queries.

This item is part of the explicit RAG-03 deferred scope. Phase 03 may preserve typed warning/answer-basis fields, but it must not claim graph-extraction failure handling or graph-backed degraded answers.

### DEBT-RAG-05 — Full invalid-input and filter edge coverage

- **Rationale:** The MVP exercises valid query and filter inputs needed for the end-to-end slice; exhaustive malformed, oversized, unmatched, and combinatorial input behavior can follow after the path is runnable.
- **Known risk:** Invalid requests may not yet receive every final HTTP/gRPC classification or bound-specific error.
- **Current constraints:** Keep basic contract validation and bounded evidence in the happy path; do not claim exhaustive negative-input coverage.
- **Trigger:** External callers, fuzzing/property testing, or a requirement for complete public API contract coverage.
- **Target:** Phase 06 hardening/evaluation.
- **Future acceptance criteria:** Empty/oversized queries, malformed IDs, unsupported content types, and filter limits are rejected before retrieval/provider work with stable HTTP 400 and gRPC `InvalidArgument` behavior.
