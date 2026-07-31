# Phase 3: Hybrid Retrieval & Basic RAG Path - Context

**Gathered:** 2026-07-30
**Status:** Accepted MVP scope override recorded 2026-07-31; ready for execution after explicit approval

## Accepted MVP Scope Override — 2026-07-31

The accepted Phase 03 MVP proves only one trustworthy happy path: a valid query over a completed, query-ready corpus where both dense-vector and BM25 retrieval succeed, the results are deterministically fused into bounded evidence, and one provider-neutral LLM call returns a structured answer whose valid citations resolve to that evidence. Basic validation, bounds, untrusted-evidence framing, and the initial BM25 build/readiness gate remain in scope only as safeguards for that path.

The earlier broader target behavior is preserved for later hardening, but it is not a Phase 03 acceptance lock. Decision IDs D-11 through D-16, D-24, and D-41 through D-43 are future target contracts deferred from this phase and must not be represented as delivered by the five MVP plans. `deferred-items.md` is the current source of record for the deferred behavior, rationale, triggers, targets, and future acceptance criteria.

<domain>
## Phase Boundary

Implement the Rust-owned valid-query path over a completed LanceDB corpus by combining successful dense vector and in-memory BM25 retrieval, applying valid typed metadata filters, deterministic fusion, deduplication, bounded untrusted evidence, and one provider-neutral structured generation call. Expose the unary Go `POST /rag/query` endpoint through the existing gRPC boundary and return valid structured citations that resolve to the selected evidence.

The initial BM25 snapshot must be built before the first query-ready state and a build failure must prevent that state; this is the minimum safeguard required to make the MVP happy path trustworthy. Dynamic re-ingestion switching and restart-specific recovery/readiness behavior remain future targets under `DEBT-RAG-04`.

Degraded retrieval, model-only fallback, citation repair/downgrade, graph-unavailability behavior, and lifecycle recovery are not Phase 03 acceptance behavior. They remain documented target contracts in the decision list and the deferred ledger.

Graph context extraction remains Phase 4. Formal workflow orchestration, streaming events, node retries, and provider fallback remain Phase 5. Evaluation-driven tuning and full observability remain Phase 6.

</domain>

<decisions>
## Implementation Decisions

### Decision status under the accepted MVP override

The decisions below remain useful target contracts, but the following groups are deferred from Phase 03 acceptance and are tracked in `deferred-items.md`: D-11 through D-16 under `DEBT-RAG-01`, D-24 under `DEBT-RAG-03`, and D-41 through D-43 under `DEBT-RAG-04`. Phase 03 may carry typed fields or initial-build safeguards needed by the valid path; that compatibility capacity is not implementation or acceptance of the deferred behavior.

### Hybrid Ranking and Candidate Flow
- **D-01:** Fuse dense-vector and BM25 rankings with Reciprocal Rank Fusion (RRF).
- **D-02:** Deduplicate merged results by `chunk_id`; one result retains both source ranks and one fused score.
- **D-03:** Default vector and BM25 weights to `1.0` each, with configuration overrides.
- **D-04:** Make the RRF rank constant configurable and default it to `k = 60`.
- **D-05:** Keep the previously decided configurable retrieval candidate pool and final-context limits. Phase 3 supplies the `NoOpReranker` pass-through port; full reranking remains Phase 999.2.

### Metadata Scope and Filtering
- **D-06:** Search the global completed corpus when filters are absent.
- **D-07:** The v1 query contract exposes optional `document_ids` and `content_types` filters.
- **D-08:** Values combine with OR inside one filter field and AND across filter fields.
- **D-09:** Apply the same filters to dense and BM25 candidate selection before RRF fusion.
- **D-10:** Reject malformed document IDs and unsupported content types with gRPC `InvalidArgument` / HTTP `400`; valid filters that match nothing produce empty evidence rather than a validation error.

### Degraded Retrieval and Answer Basis
- **D-11 (future target; DEBT-RAG-01):** If one retrieval path fails, continue with the surviving path and mark the response degraded.
- **D-12 (future target; DEBT-RAG-01):** If both retrieval paths fail, continue to the LLM and allow a model-only answer with warnings for both failed paths.
- **D-13 (future target; DEBT-RAG-01):** Retrieval results never block generation merely because evidence is empty, weak, or unnecessary; the LLM may answer from model-owned knowledge to maximize usefulness.
- **D-14 (future target behavior; DEBT-RAG-01):** The full contract reports `answer_basis` as `retrieval`, `mixed`, or `model_only`. Phase 03 carries the typed field for the valid retrieval-backed response only.
- **D-15 (future target; DEBT-RAG-01):** Degraded responses include structured, machine-readable warnings naming unavailable retrieval paths.
- **D-16 (future target; DEBT-RAG-01):** A model-only response includes both `answer_basis: "model_only"` and a separate human-readable notice such as “Answered using model knowledge without retrieved evidence.” Its citation list is empty.
- **D-17:** The generation call evaluates evidence use and returns the proposed answer basis through validated structured output; no separate relevance-classification call is added.

### HTTP, gRPC, Session, and Citation Contract
- **D-18:** The Go gateway exposes unary `POST /rag/query`; streaming remains Phase 5.
- **D-19:** The request carries query text, an optional session ID, and optional typed filters.
- **D-20:** Validate caller-supplied session IDs. When absent, generate a UUID and always return the effective session ID.
- **D-21:** Replace string-only citations with structured evidence citations containing `chunk_id`, `document_id`, source filename/title when available, section path, bounded excerpt, truncation status, and retrieval metadata.
- **D-22:** Retrieval-backed and mixed answer text uses inline numbered markers (`[1]`, `[2]`) that resolve to structured citation objects.
- **D-23:** Citation excerpts contain only a relevant passage up to a configurable limit and explicitly report truncation; never return the full chunk by default.
- **D-24 (future target; DEBT-RAG-03):** Validate every generated citation marker against supplied evidence. Make one bounded repair attempt for malformed or unknown markers. If repair still fails, remove unsupported citations, downgrade the answer to `model_only`, and emit a citation-integrity warning. Phase 03 validates only structured markers that are already valid and resolvable.
- **D-25:** Return a compact retrieval snapshot containing index generation, embedding model, RRF parameters and weights, candidate limits, and active filters.

### LLM Provider and Generation Contract
- **D-26:** Define a provider-neutral async Rust generation trait with injectable test implementations.
- **D-27:** Use OpenRouter as the default adapter and keep the generation model configurable.
- **D-28:** Request validated structured model output containing answer text, cited evidence IDs, answer basis, and notices; validate it before assembling the public response.
- **D-29:** Phase 3 makes one generation attempt with no retries. Formal retry and provider-fallback orchestration remains Phase 5.
- **D-30:** Apply a configurable generation timeout defaulting to 30 seconds and propagate client cancellation to provider work.
- **D-31:** If generation fails, return a structured provider error with session/correlation identity and no fabricated answer or extractive substitute.
- **D-32:** Default sampling to temperature `0` and top-p `1`, both configurable.
- **D-33:** Reserve a configurable default of 2,048 output tokens.
- **D-34:** Lead with a direct, concise answer, add detail proportional to the question, place citations next to supported claims, and do not force a fixed section template.

### Prompt Assembly and Trust Boundary
- **D-35:** Treat all retrieved document content as untrusted evidence. It may supply facts but cannot override system rules, alter tool behavior, or become executable model instruction.
- **D-36:** Frame chunks as isolated structured evidence blocks with engine-generated IDs and provenance. Escape delimiter-like source text so documents cannot forge prompt boundaries.
- **D-37:** Keep apparent prompt-injection text available as marked evidence, never obey it, and flag it as suspicious for diagnostics rather than silently removing it.
- **D-38:** For corpus-specific questions, prefer retrieved evidence when it conflicts with model knowledge. Disclose the conflict, separate external model knowledge, and classify the result as `mixed`.
- **D-39:** Reserve the configured answer budget first, then pack complete evidence chunks in RRF order until the evidence token budget is exhausted. Never split a chunk or citation boundary blindly.

### Cross-Index Freshness and Recovery
- **D-40:** `completed` ingestion means both the LanceDB vector representation and BM25 entries are query-ready.
- **D-41 (future target; DEBT-RAG-04):** Re-ingestion keeps the previous completed document version searchable until both new representations can switch together.
- **D-42 (future restart target; DEBT-RAG-04):** On engine restart, rebuild BM25 from canonical completed LanceDB chunks before the query service reports ready or accepts queries. Phase 03 proves only the initial BM25 build before the first query-ready state.
- **D-43 (future restart-failure target; DEBT-RAG-04):** Fail engine startup clearly if the BM25 rebuild fails; do not silently enter permanent vector-only degradation. Phase 03 keeps the equivalent initial-build failure guard, but does not claim restart recovery behavior.

### BM25 Analysis and Scoring
- **D-44:** Use Unicode-aware tokenization with NFKC normalization and Unicode case folding. Preserve original source text for prompts and citations.
- **D-45:** Do not apply stemming or stop-word removal in v1.
- **D-46:** Index chunk content, title, and section path. Default configurable field boosts are content `1.0`, title `2.0`, and section path `1.5`.
- **D-47:** Multi-term lexical queries allow any term to match; BM25 cumulative relevance rewards chunks matching more terms.
- **D-48:** Index technical identifiers both as normalized whole tokens and as camel-case, underscore, and hyphen subtokens.
- **D-49:** Default configurable BM25 parameters to `k1 = 1.2` and `b = 0.75`; tune later using Phase 6 evaluation evidence.
- **D-50:** Calculate document-frequency statistics over the global completed corpus. Metadata filters constrain candidates without redefining IDF.

### Determinism and Reproducibility
- **D-51:** Resolve equal RRF scores by best individual source rank, then `document_id`, `chunk_index`, and `chunk_id`.
- **D-52:** Rank using full-precision scores. Round only serialized diagnostic values to a fixed precision.
- **D-53:** For the same normalized query, filters, index generation, and configuration, return exactly the same ordered chunk IDs.

### Query Validation and Bounds
- **D-54:** Reject empty or whitespace-only questions before retrieval or provider calls with gRPC `InvalidArgument` / HTTP `400`.
- **D-55:** Enforce a configurable 8 KiB UTF-8 query limit before provider calls.
- **D-56:** Default configurable filter limits to 100 document IDs and 16 content types. Normalize and deduplicate values before enforcing the limits.
- **D-57:** Trim outer whitespace and preserve the original question semantics for generation. Derive separate normalized views for BM25 and embedding retrieval.

### the agent's Discretion
- Exact Rust module/file layout, internal error type names, configuration key names, fixed API score-display precision, default citation-excerpt limit, and the initial configurable OpenRouter generation model remain implementation details.
- These details must preserve the decisions and public behavior above.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements and Phase Boundary
- `.planning/ROADMAP.md` — Phase 3 goal, current requirements RAG-02/RAG-04, the explicit RAG-03 Phase 06 hardening target, success criteria, and boundaries with Phases 4–6.
- `.planning/REQUIREMENTS.md` — active hybrid-retrieval and reranker-port requirements plus the deferred RAG-03 traceability entry.

### Architecture and Ownership
- `.discussion/final_implementation_decision_document.md` — authoritative Go control-plane / Rust data-plane split and custom hybrid-retrieval direction.
- `.discussion/lightweight_state_machine_plan.md` — future fixed workflow, typed context, degraded-mode, citation, timeout, and prompt-assembly boundaries; Phase 3 must leave clean integration points without implementing the Phase 5 state machine.
- `.planning/phases/02-ingestion-chunking-vector-storage/02-CONTEXT.md` — global-corpus behavior, LanceDB schema, embedding model/dimensions, provider conventions, and the locked rule that Rust owns RAG/vector semantics while Go remains a thin boundary.

### Extension Port
- `.planning/phases/999.2-reranking/999.2-CONTEXT.md` — async `Reranker` contract, `NoOpReranker`, configurable fetch/final limits, and soft reranker fallback.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `engine/src/main.rs` — tonic `LancetServiceImpl`, existing `QueryRAG` placeholder, ingestion status/recovery machinery, and Rust-owned engine integration point.
- `engine/src/db/mod.rs` — canonical LanceDB `nodes` schema already stores `document_id`, `chunk_id`, `chunk_index`, `content`, 2,048-dimension embeddings, title, section path, content type, and embedding model.
- `engine/src/client/mod.rs` — existing async OpenRouter embedding client patterns, timeout handling, configuration, and injectable seams that can guide—but must not couple—the provider-neutral generation adapter.
- `proto/lancet/v1/lancet.proto` — existing unary `QueryRAG` RPC and basic answer/session/citation messages that require backward-aware extension.

### Established Patterns
- Rust owns chunking, vector, retrieval, recovery, and RAG semantics; Go handles HTTP, gRPC forwarding, and PostgreSQL/session metadata.
- The codebase uses tonic/prost for the shared contract, Tokio async execution, structured tracing, configuration overlays, and fail-fast schema validation.
- Completed data lives canonically in LanceDB; BM25 is a derived in-memory index rebuilt from completed chunks.
- Initial startup uses the completed-corpus BM25 readiness safeguard; re-ingestion atomicity and restart recovery remain future targets under `DEBT-RAG-04`.

### Integration Points
- `gateway/main.go` currently registers `/health` and document routes only; add a thin `POST /rag/query` handler and a `QueryRAG` method on the gateway engine interface.
- `proto/lancet/v1/lancet.proto` must carry typed filters, structured citations, answer basis, degradation warnings, retrieval snapshot metadata, and the effective session ID.
- `engine/src/main.rs` currently returns a placeholder answer; route it through new retrieval, BM25, fusion, prompt assembly, and generation modules while keeping the tonic handler thin.
- Engine startup must build the derived BM25 index before query readiness, and ingestion/re-ingestion completion must coordinate vector and lexical visibility.

</code_context>

<specifics>
## Specific Ideas

- RRF defaults: vector weight `1.0`, BM25 weight `1.0`, `k = 60`.
- BM25 defaults: `k1 = 1.2`, `b = 0.75`; content/title/section-path boosts `1.0`/`2.0`/`1.5`.
- Request defaults: 8 KiB query limit, 100 document IDs, 16 content types.
- Generation defaults: 30-second timeout, no Phase 3 retries, temperature `0`, top-p `1`, and 2,048 output tokens.
- Future model-only target: a model-only answer should visibly say it used model knowledge without retrieved evidence while keeping that notice separate from generated answer text; this is tracked under `DEBT-RAG-01` and is not a Phase 03 acceptance criterion.

</specifics>

<deferred>
## Deferred Ideas

- Graph context extraction, graph-query contribution to prompts, and `ContextAssemblyStrategy` implementation remain Phase 4.
- Formal state-machine nodes, streaming answer events, node retries, provider fallback, and orchestration cancellation policy remain Phase 5.
- Evaluation-driven tuning of RRF/BM25 weights, field boosts, thresholds, generation parameters, and quality claims remains Phase 6.
- Full OpenTelemetry cross-service tracing and benchmark/evaluation reporting remain Phase 6.
- Non-NoOp external/local reranker implementations remain Phase 999.2; Phase 3 creates only the async port and pass-through implementation.

</deferred>

---

*Phase: 3-Hybrid Retrieval & Basic RAG Path*
*Context gathered: 2026-07-30*
