# Phase 4: Knowledge Graph Extraction & Query - Context

**Gathered:** 2026-08-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract entities and relationships from chunks during ingestion using the existing provider-neutral LLM generation seam, persist them as a knowledge graph in new LanceDB tables, and let RAG queries traverse that graph (via the real `lance-graph` Cypher-over-Lance engine) to compile additional context into the prompt alongside the existing Phase 3 hybrid-retrieval evidence. Also define the `ContextAssemblyStrategy` trait/enum (Port for 999.5) with a working `SourceChunks` fallback.

Community summaries, LLM-assisted node/edge summarization, and semantic (vector-similarity) entity-resolution beyond exact match remain backlog (999.1, 999.4, 999.6) — this phase only needs to leave the schema and trait shapes those backlog phases already specified, not implement their behavior.

</domain>

<decisions>
## Implementation Decisions

### Entity & Relationship Extraction
- **D-01:** Entity/relationship extraction runs synchronously during ingestion, blocking document completion — same execution model as the existing embedding-generation step.
- **D-02:** Extraction runs at per-chunk granularity: one LLM structured-extraction call per chunk (matches the GraphRAG "text unit" pattern and preserves `char_start`/`char_end`-level provenance).
- **D-03:** Entity types are open-domain freeform strings assigned by the LLM — no fixed taxonomy/enum.
- **D-04:** `relation_type` is a freeform LLM-assigned string (e.g. `"founded_by"`); `edges.weight` stores an LLM-reported confidence score (0.0–1.0), not a fixed placeholder.
- **D-05:** The existing `ExactMatchResolver` (`EntityResolver` trait, scaffolded in Phase 2) is wired into extraction to merge duplicate entity mentions by case-normalized exact name match, scoped **globally across the whole corpus** (not per-document). — **Reversibility:** costly — once entities are merged globally, narrowing resolution to per-document later requires re-splitting merged nodes and re-attributing `source_chunk_ids`.
- **D-06:** Extraction failure for a single chunk is non-fatal: the chunk keeps zero entities and the document still reaches `completed` status. Extraction is additive graph enrichment, not a precondition for a document being queryable via existing hybrid retrieval.
- **D-07:** Chunks below a minimum content-length threshold skip the extraction call entirely (exact threshold is implementer discretion).
- **D-08:** Extraction reuses the existing provider-neutral `Generator` trait (OpenRouter, from Phase 3) rather than a separate extraction-specific client.
- **D-09:** Extraction calls for chunks within one document run concurrently in batches, reusing the Phase 2 D-20 pattern (up to 5 concurrent OpenRouter requests) rather than sequentially.

### Graph Node/Edge Schema Resolution
- **D-10:** Extracted entities are stored in a **new dedicated `entities` table**, separate from the existing chunk-level `nodes` table. — **Reversibility:** one-way — merging the tables back later requires redesigning every entities-table consumer (extraction writer, resolver, traversal seed lookup) around a shared polymorphic schema.
- **D-11:** The `entities` table carries `name`, `entity_type`, `name_vector`, `summary` (nullable), `summary_vector` (nullable), `unsummarized_refs` (nullable list), and `community_ids` (nullable list) — these summary/community columns move from `nodes` to `entities`, where they conceptually belong.
- **D-12:** Entities link back to their source chunk(s) via a `source_chunk_ids` list column on the `entities` table (not via implicit `MENTIONED_IN` edges).
- **D-13:** `edges.source_node_id`/`target_node_id` reference entity IDs only (entity-to-entity relationships). Edges never connect a chunk to an entity.
- **D-14:** The new `entities` table follows the same Phase 2 D-22 fail-fast/no-auto-migrate schema-drift rule — any drift aborts engine startup with a clear error.
- **D-15:** The dormant `community_ids`/`summary`/`summary_vector`/`unsummarized_refs` columns already shipped on the chunk `nodes` table in Phase 2 are **removed** now that `entities` owns that data. — **Reversibility:** one-way — this is itself a drift-inducing schema change against an already-shipped table.
- **D-16:** The `nodes`-table column removal is handled by bumping the schema version and documenting that upgrading past this phase requires deleting the local LanceDB directory and re-ingesting (no in-engine auto-migration) — consistent with D-22's "manual user intervention" clause, not a contradiction of it.

### Graph Traversal & Query
- **D-17:** Graph traversal uses the real **`lance-graph` crate** ([crates.io/crates/lance-graph](https://crates.io/crates/lance-graph) — a Cypher-capable graph query engine translating Cypher into DataFusion SQL over Lance datasets), not a hand-rolled BFS implementation. Confirmed real via web search after an initial incorrect assumption that no such crate existed. — **Reversibility:** costly — swapping traversal engines later means rewriting every Cypher-pattern call site and re-verifying node/edge dataset compatibility.
- **D-18:** A RAG query seeds graph traversal via **vector search against the `entities.name_vector` column** — not exact substring match, not a second LLM extraction call on the query text.
- **D-19:** Traversal is expressed as genuine Cypher pattern queries executed via `lance-graph`, not fixed-hop BFS logic hand-rolled in Rust.
- **D-20:** The standalone `QueryGraph` RPC accepts a **structured request** (seed entity name/id, hop depth, optional `relation_type` filter) rather than a raw Cypher query string, even though `lance-graph` could safely parse one — keeps the public contract typed and bounded, matching the `QueryRAG` convention from Phase 3.
- **D-21:** `entities.name_vector` is populated by reusing the existing OpenRouter embedding client/model (same one used for chunk embeddings), generated when an entity node is created or its canonical name changes via resolution.
- **D-22:** `QueryGraph` accepts only an explicit seed entity name/id — no natural-language query text embedded server-side (that seeding logic lives in the main `/rag/query` path per D-18, keeping the two RPCs' responsibilities distinct).
- **D-23:** Both `QueryGraph` and the auto-triggered RAG augmentation enforce a **configurable maximum hop cap** (e.g. default 3) bounding caller-controllable traversal cost, consistent with existing bounded-input patterns (Phase 3 D-55/D-56).
- **D-24:** The always-on RAG-path traversal follows edges in **both directions** from a seed entity (entity as source OR target), not outgoing-only — otherwise relationships where the seed is the edge's target would be silently missed.
- **D-25:** `QueryGraph` remains **gRPC-only/internal** for this phase — the Go gateway does not add an HTTP wrapper (e.g. `POST /graph/query`) for it.

### RAG Prompt Integration (ContextAssemblyStrategy)
- **D-26:** Every `/rag/query` call automatically attempts entity seed-matching; graph context is added to the prompt only when matches are found. No new opt-in request flag is added to the Phase 3 `QueryRAG` contract.
- **D-27:** Graph context appears in the compiled prompt as a **separate "Related Entities & Relationships" section**, distinct from the numbered chunk-evidence citations (`[1]`, `[2]`). Graph facts are **not** citable `EvidenceBlock`-like entries in v1 — this keeps Phase 3's citation-marker/validation contract untouched.
- **D-28:** Per the `ContextAssemblyStrategy`'s `PrecomputedSemantics`/`SourceChunks` distinction (999.5 D-02/D-03): since entity/edge `summary` columns are null in v1, "falling back to source chunks" concretely means rendering the **raw entity name + relation triple text** (e.g. `"A —founded_by→ B"`), not re-fetching the original source chunk text via `source_chunk_ids`.
- **D-29:** Graph context and chunk evidence **share a single evidence token budget** (Phase 3 D-39) rather than separate reserved allocations, and are **interleaved by relevance score** across both sources rather than packed chunk-evidence-first.
- **D-30:** Interleaving uses a configurable `graph_weight` multiplier (default **1.0**, equal footing with chunk evidence) applied to normalized graph-match scores before merging with normalized RRF-fused chunk scores — mirrors the Phase 3 pattern of defaulting RRF's vector/BM25 weights to 1.0 each with config overrides.
- **D-31:** The always-on RAG-path graph augmentation defaults to **1-hop** traversal (distinct from the caller-specified hop depth on the standalone `QueryGraph` RPC), bounding latency/prompt-size impact on every query.
- **D-32:** If entity seed-matching or the `lance-graph` traversal fails/errors at query time, the query **silently continues with chunk-only evidence** rather than failing the whole request — graph augmentation is additive/optional and must not make the already-shipped Phase 3 hybrid-retrieval path fragile to a new dependency.

### Claude's Discretion
- Exact minimum content-length threshold for skipping extraction (D-07).
- Exact structured-output JSON schema for the per-chunk extraction call (entity list, relation list shape).
- Exact default value for the configurable maximum hop cap beyond "a small bounded number like 3" (D-23).
- Entity/edge ID generation scheme (expected to follow the existing UUID convention used for `document_id`/`chunk_id`).
- Internal module/file layout for the extraction pipeline, traversal query builder, and `ContextAssemblyStrategy` implementation.
- Exact normalization method (min-max vs. other) for merging graph-match and RRF-fused scores under D-29/D-30.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Roadmap
- `.planning/ROADMAP.md` §Phase 4 — goal, requirements (DATA-04, DATA-05, RAG-05), and success criteria this phase must satisfy.
- `.planning/REQUIREMENTS.md` — DATA-04, DATA-05, RAG-05 definitions and their "Port for 999.x" annotations.

### Prior Phase Context (must not regress)
- `.planning/phases/02-ingestion-chunking-vector-storage/02-CONTEXT.md` — original `nodes`/`edges` LanceDB schema (D-21–D-25), the fail-fast/no-auto-migrate schema-drift rule (D-22), and the OpenRouter embedding client/model conventions (D-17–D-20) this phase reuses for `name_vector`.
- `.planning/phases/03-hybrid-retrieval-basic-rag-path/03-CONTEXT.md` — the `EvidenceBlock`/citation-marker contract (D-21–D-24), the evidence token-budget mechanism (D-39), the `QueryRAG` request shape (D-19), and the explicit deferral of graph context extraction to Phase 4.

### Backlog Extension Ports (schema/trait shapes to leave clean, not implement)
- `.planning/phases/999.1-community-summaries/999.1-CONTEXT.md` — `community_ids` field and placeholder `communities` table this phase's schema must remain compatible with.
- `.planning/phases/999.4-llm-assisted-synthesis-at-ingestion-time/999.4-CONTEXT.md` — `summary`/`summary_vector`/`unsummarized_refs` column intent (now on `entities`, per D-11) and the double-vector-embedding rationale (`name_vector` vs `summary_vector`).
- `.planning/phases/999.5-compile-time-semantics-on-graph-nodes/999.5-CONTEXT.md` — the exact `ContextAssemblyStrategy` (`PrecomputedSemantics`/`SourceChunks`) contract this phase implements the fallback for (D-28).
- `.planning/phases/999.6-knowledge-drift-detection-and-node-merging/999.6-CONTEXT.md` — the `EntityResolver` trait contract this phase wires up via `ExactMatchResolver` (D-05), and the future `SemanticLinkResolver`/vector-candidate-generation direction this phase's `name_vector` column (D-18/D-21) sets up for.

### Architecture
- `.discussion/final_implementation_decision_document.md` — Go/Rust split-service boundaries; Go stays a thin interface (relevant to D-25's decision not to add an HTTP wrapper).
- `.discussion/lightweight_state_machine_plan.md` — future orchestration integration points this phase's graph augmentation step must fit into cleanly ahead of Phase 5.

### New External Dependency
- [crates.io/crates/lance-graph](https://crates.io/crates/lance-graph) — Cypher-capable graph query engine for Lance datasets (D-17, D-19); not yet in `engine/Cargo.toml`, must be added.
- [docs.rs/lance-graph](https://docs.rs/lance-graph) — API reference.
- [github.com/lance-format/lance-graph](https://github.com/lance-format/lance-graph) — source repository.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `engine/src/db/mod.rs` — `nodes_schema()`, `edges_schema()`, `communities_schema()`, `table_schemas()` (currently 5 tables: `documents`, `staged_documents_v2`, `nodes`, `edges`, `communities`); `EntityResolver` trait and `ExactMatchResolver` pass-through (lines ~267–289) ready to wire into extraction.
- `engine/src/generation/mod.rs` — `Generator` trait, `GenerationRequest`, `ModelOutput`, `FakeGenerator` test double — the extraction call should follow this same seam rather than building a parallel one.
- `engine/src/prompt.rs` — `EvidenceBlock` (chunk-shaped, built via `EvidenceBlock::from_candidate`), `DEFAULT_ANSWER_TOKEN_BUDGET`/`DEFAULT_MAX_PROMPT_TOKENS` — graph context needs its own representation alongside this, per D-27.
- `engine/src/main.rs` — existing `query_graph()` handler (~line 1424) is a literal `{"status":"scaffolding"}` stub to replace; `nodes_table()`/`edges_table()` accessors already used in the replacement-mutation delete path (~lines 1572–1588, 2001).

### Established Patterns
- Rust owns all chunking/vector/retrieval/graph semantics; Go remains a thin HTTP/gRPC/PostgreSQL-status interface (D-48 from Phase 2) — reinforces D-25's decision to keep `QueryGraph` gRPC-only.
- Config-driven defaults with TOML + env override convention (Phase 2 D-26–D-30) — the new `graph_weight`, hop-cap, and min-content-length knobs should follow this.
- Concurrent OpenRouter batching (Phase 2 D-20, up to 5 concurrent calls) — the pattern D-09 reuses for extraction.

### Integration Points
- `engine/Cargo.toml` — currently only `lancedb = "~0.31"`; add `lance-graph` as a new dependency.
- `proto/lancet/v1/lancet.proto` — `QueryGraphRequest`/`QueryGraphResponse` (lines 113–119) are bare `{query: string} -> {result_json: string}` stubs; must be redesigned per D-20 into a structured request/response.
- `engine/src/main.rs` ingestion path — wherever chunks are persisted to `nodes_table()`, the extraction step (D-01/D-02) hooks in synchronously right after chunk embedding, before the document is marked `completed`.
- Query path — wherever Phase 3's RRF fusion produces `FusedCandidate`s for `EvidenceBlock::from_candidate`, the new graph-augmentation step (D-18, D-24, D-26, D-29) hooks in alongside it to produce the merged, interleaved evidence set.

</code_context>

<specifics>
## Specific Ideas

- `lance-graph` (real crate, not previously known to be in the dependency tree) is the concrete mechanism satisfying REQUIREMENTS.md's "lance-graph/Cypher-style pattern matching" wording — this was discovered mid-discussion via web search, correcting an initial wrong assumption that no such crate existed.
- The `entities` table is a clean split from the chunk-level `nodes` table specifically to avoid touching Phase 3's already-shipped hybrid-retrieval queries against `nodes`.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (Community summaries, LLM-assisted summarization, and semantic/vector-based entity resolution beyond exact match remain correctly scoped to backlog phases 999.1/999.4/999.6, per existing ROADMAP.md structure — not newly deferred by this discussion.)

</deferred>

---

*Phase: 4-Knowledge Graph Extraction & Query*
*Context gathered: 2026-08-05*
