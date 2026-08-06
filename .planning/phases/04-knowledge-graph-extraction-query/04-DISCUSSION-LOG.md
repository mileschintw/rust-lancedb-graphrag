# Phase 4: Knowledge Graph Extraction & Query - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-05
**Phase:** 4-Knowledge Graph Extraction & Query
**Areas discussed:** Entity & Relationship Extraction, Graph Node/Edge Schema Resolution, Graph Traversal & Query, RAG Prompt Integration (`--all` mode — all identified gray areas auto-selected, discussed interactively)

---

## Entity & Relationship Extraction

| Question | Options presented | Selected |
|---|---|---|
| Extraction timing relative to ingestion | Synchronous, blocking (recommended) / Background async job / You decide | ✓ Synchronous, blocking |
| Extraction call granularity | Per-chunk (recommended) / Per-document / You decide | ✓ Per-chunk |
| Entity typing | Open-domain freeform (recommended) / Fixed taxonomy / You decide | ✓ Open-domain freeform |
| relation_type / edges.weight population | Freeform relation_type + LLM confidence weight (recommended) / Freeform relation_type + fixed weight=1.0 / You decide | ✓ Freeform + LLM confidence weight |
| Wire up ExactMatchResolver during extraction? | Yes, wire it in now (recommended) / No, write all as new nodes / You decide | ✓ Yes, wire it in now |
| Extraction failure handling | Non-fatal, chunk keeps 0 entities (recommended) / Fatal, fails document / You decide | ✓ Non-fatal |
| Skip extraction on trivial chunks? | Yes, skip below min length (recommended) / No, always attempt / You decide | ✓ Yes, skip below min length |
| Extraction provider/client | Reuse Phase 3 Generator trait (recommended) / Separate extraction client / You decide | ✓ Reuse Phase 3 Generator trait |
| ExactMatchResolver dedup scope | Global, whole corpus (recommended) / Per-document only / You decide | ✓ Global, whole corpus |
| Extraction call concurrency | Yes, concurrent batches, reuse Phase 2 pattern (recommended) / Sequential / You decide | ✓ Yes, concurrent batches |

**Notes:** All answers matched the recommended option. Concurrency question was added later in an "explore more gray areas" round after the area's initial 4-question batch.

---

## Graph Node/Edge Schema Resolution

| Question | Options presented | Selected |
|---|---|---|
| Where do entity nodes live vs. the chunk `nodes` table? | New dedicated `entities` table (recommended) / Repurpose `nodes` as polymorphic / You decide | ✓ New dedicated `entities` table |
| Entity-to-chunk provenance link | `source_chunk_ids` list column (recommended) / Implicit MENTIONED_IN edges / You decide | ✓ `source_chunk_ids` list column |
| Edge scope | Entity-to-entity only (recommended) / Mixed chunk-to-entity and entity-to-entity / You decide | ✓ Entity-to-entity only |
| Schema-drift rule for new `entities` table | Yes, same fail-fast rule (recommended) / Relaxed for new tables only / You decide | ✓ Yes, same fail-fast rule |
| Dormant nodes-table columns (community_ids/summary/summary_vector/unsummarized_refs) | Leave in place, unused (recommended) / **Remove them from `nodes` now** / You decide | ✓ Remove them from `nodes` now |
| Migration handling for the resulting drift | Bump schema version, document manual recreation (recommended) / Add in-engine migration path / You decide | ✓ Bump schema version, document manual recreation |

**Notes:** The dormant-columns question was the one place the user deviated from the recommended option, choosing to remove the columns from `nodes` rather than leave them dormant. This raised a genuine tension with Phase 2's D-22 fail-fast/no-auto-migrate rule, which was surfaced as an explicit follow-up question and resolved by treating the documented manual-recreation requirement as satisfying D-22's "manual user intervention" clause rather than contradicting it.

---

## Graph Traversal & Query

| Question | Options presented | Selected |
|---|---|---|
| Traversal implementation, given assumed no `lance-graph` crate exists | Custom in-engine BFS/N-hop traversal (recommended) / Research/adopt a real graph crate / You decide | ✓ **User corrected the premise**: "Research and use the lance_graph crate" |
| Query seeding mechanism | Exact/normalized substring match (recommended) / Vector search against name embeddings / Run LLM extraction on query / You decide | ✓ Vector search against name embeddings |
| Traversal shape (asked before the lance-graph correction) | Fixed N-hop BFS (recommended) / Minimal Cypher-like parser / You decide | ✓ Fixed N-hop BFS |
| QueryGraph RPC contract (asked before the lance-graph correction) | Structured request (recommended) / Free-form Cypher string / You decide | ✓ Structured request |

**Mid-discussion correction:** After the user flagged that `lance-graph` should be researched rather than assumed nonexistent, a web search confirmed it's a real, actively maintained crate (63K+ downloads) — a Cypher-capable graph query engine translating Cypher into DataFusion SQL over Lance datasets ([crates.io/crates/lance-graph](https://crates.io/crates/lance-graph)). The traversal-shape and QueryGraph-contract questions were re-asked with this corrected context:

| Question (revisited) | Options presented | Selected |
|---|---|---|
| Traversal shape, with lance-graph confirmed real | Genuine Cypher pattern queries via lance-graph (recommended) / Fixed N-hop BFS / You decide | ✓ Genuine Cypher pattern queries via lance-graph |
| QueryGraph RPC contract, with lance-graph confirmed real | Structured request, kept (recommended) / Raw Cypher query string / You decide | ✓ Structured request (kept) |

Further questions in this area:

| Question | Options presented | Selected |
|---|---|---|
| name_vector population | Reuse existing OpenRouter embedding client (recommended) / Separate smaller model / You decide | ✓ Reuse existing OpenRouter embedding client |
| QueryGraph seed input shape | Explicit seed entity name/id only (recommended) / Natural-language text, embedded server-side / You decide | ✓ Explicit seed entity name/id only |
| Hop-depth bound | Yes, enforce configurable max hop cap e.g. 3 (recommended) / No explicit cap / You decide | ✓ Yes, enforce configurable max hop cap |
| Expose QueryGraph via Go HTTP? | Yes, add thin HTTP wrapper (recommended) / **No, gRPC-only/internal** / You decide | ✓ No, gRPC-only/internal for this phase |
| Traversal direction from seed entity | Both directions (recommended) / Outgoing only / You decide | ✓ Both directions |

**Notes:** Two deviations from recommended options in this area: (1) the lance-graph research correction, which changed the grounding for two other questions, and (2) keeping QueryGraph gRPC-only rather than adding an HTTP wrapper.

---

## RAG Prompt Integration (ContextAssemblyStrategy)

| Question | Options presented | Selected |
|---|---|---|
| Graph augmentation trigger | Always attempt seed-match, add context if found (recommended) / Opt-in request flag / You decide | ✓ Always attempt seed-match |
| Graph context placement in prompt | Separate non-citable section (recommended) / Citable EvidenceBlock-like entries / You decide | ✓ Separate non-citable section |
| SourceChunks fallback meaning (999.5 D-02/D-03) | Raw entity name + relation triple text (recommended) / Re-fetch original source chunks / You decide | ✓ Raw entity name + relation triple text |
| Evidence token budget sharing | Shared single budget (recommended) / Separate reserved sub-budget / You decide | ✓ Shared single budget |
| Packing priority within shared budget | Chunk evidence first, graph fills remainder (recommended) / **Interleaved by relevance score** / You decide | ✓ Interleaved by relevance score |
| Shared score scale for interleaving | Normalize both to [0,1] (recommended) / **Add configurable graph_weight multiplier** / You decide | ✓ Add configurable graph_weight multiplier (on top of normalization) |
| Default graph_weight value | 1.0, equal footing (recommended) / Lower than 1.0 / You decide | ✓ 1.0, equal footing |
| Default hop depth for always-on augmentation | 1-hop (recommended) / 2-hop / You decide | ✓ 1-hop |
| Query-time graph failure handling | Silently continue chunk-only (recommended) / Fail whole query / You decide | ✓ Silently continue chunk-only |

**Notes:** The user chose interleaving-by-score over the simpler chunk-first packing, which in turn required a follow-up on how to make graph and chunk scores comparable — resolved with a configurable weight multiplier rather than plain normalization alone.

---

## Claude's Discretion

- Exact minimum content-length threshold for skipping extraction on trivial chunks.
- Exact structured-output JSON schema for the per-chunk extraction call.
- Exact default value for the configurable max hop cap beyond "a small bounded number like 3."
- Entity/edge ID generation scheme (expected to follow the existing UUID convention).
- Internal module/file layout for extraction, traversal, and ContextAssemblyStrategy.
- Exact score-normalization method for merging graph-match and RRF-fused scores.

## Deferred Ideas

None — discussion stayed within phase scope for the entire session.
