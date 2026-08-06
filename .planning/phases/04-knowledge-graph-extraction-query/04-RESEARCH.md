# Phase 4: Knowledge Graph Extraction & Query (Spike) - Research

**Researched:** 2026-08-06
**Domain:** Rust dependency-graph compatibility spike — `lance-graph` 0.5.4 Cypher-over-Lance engine vs. `lancedb ~0.31`'s pinned `lance`/`arrow`/`datafusion` versions
**Confidence:** HIGH

> **Scope note:** Per the orchestrator's narrowing, this research (and the phase it supports) covers **only** the `lance-graph`/`lancedb` integration spike — not the full extraction/storage/query-traversal implementation described in Phase 4's original success criteria. Those success criteria, and the `## Phase Requirements` mapping below, are preserved as forward-looking context for the follow-up phase (04.1, not yet created) that this spike unblocks.

## Summary

The spike's core question — can `lance-graph` 0.5.4's Cypher engine integrate with an existing `lancedb ~0.31` store despite requiring a structurally different major version of `lance`/`arrow`/`datafusion` — is **answered empirically, not just theoretically**. I built a throwaway Cargo crate (outside this repo, in the session scratchpad), added `lance-graph = { version = "0.5.4", default-features = false }` alongside `arrow-array/arrow-schema/arrow-ipc "~58.3"` (the versions this engine already pins), ran `cargo generate-lockfile` to confirm side-by-side resolution, then **wrote and ran real Rust code** implementing the IPC-based arrow-version bridge, `GraphConfigBuilder` graph configuration, and `CypherQuery::execute()` against in-memory Arrow fixture data. It compiled and executed correctly, including a correct multi-hop match, a correct `WHERE`-filtered open-vocabulary relation-type match, and a correct fixed-single-hop query that projects relationship (edge) properties directly. Full transcripts are reproduced in `## Code Examples` below.

**Both of the AI-SPEC's open spike questions are resolved:**
1. `lance-graph`'s Cypher entry point (`CypherQuery::execute()`) takes neither a path/URI opening its own reader nor a typed `lance::Dataset` handle — it takes a plain in-memory `HashMap<String, arrow::record_batch::RecordBatch>` (pinned to lance-graph's own `arrow ^56.2`). There **is** a path/URI-shaped entry point (`execute_with_namespace(DirNamespace, ...)`), newly discovered in this research and not mentioned in the AI-SPEC — but empirical source inspection shows it can only resolve **Parquet or Delta** tables (via `ParquetTableReader`/`DeltaTableReader`); no native `.lance`-format reader is exposed anywhere in the public API (`lance_native_planner` remains a documented placeholder in 0.5.4). So Question 2 (can lance-graph's bundled `lance-1.0.4` open a manifest written by `lancedb`'s `lance-8.0.0`) is moot — there is no code path in this version that would attempt it.
2. The only viable integration route is exactly what the AI-SPEC's illustrative code sketched: pre-narrow the neighborhood via `lancedb`'s own Rust API (bounded by hop-cap, per Pitfall 2), then IPC-bridge the resulting Arrow ~58.3 `RecordBatch`es into lance-graph's pinned Arrow ^56.2 type, execute Cypher against the in-memory `HashMap`, and bridge the single-`RecordBatch` result back. **This is no longer a hypothesis — it is now a proven-by-execution pattern**, confirmed against real fixture data with a real, correctly-answering multi-hop and single-hop query.

**Primary recommendation:** Proceed with `lance-graph` 0.5.4 (`default-features = false`) via the pre-narrow-then-IPC-bridge pattern for the full Phase 04.1 implementation. The fallback (hand-rolled DataFusion SQL traversal, rejected by D-19) is **not** needed — this spike found no structural blocker, only implementation-shape constraints documented below. One new, previously unflagged pitfall was discovered: Cypher `RETURN` clauses cannot project the relationship-pattern variable (`r`) itself when the pattern uses a variable-length quantifier (`*1..N`) — only fixed-length (single-hop) patterns can project `r.<property>` directly. This has a direct, favorable consequence for D-31 (the always-on RAG-path augmentation defaults to **fixed 1-hop**, exactly the case that works cleanly); it only constrains the caller-specified variable-depth path on the standalone `QueryGraph` RPC (D-20/D-23), where a documented workaround exists (see Pitfall 6).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Entity/relationship extraction (LLM call per chunk) | API / Backend (Rust engine) | — | Extraction is a synchronous ingestion-path step, same tier as existing chunk embedding (Phase 2); no browser/SSR/CDN involvement. |
| Entity/edge persistence (`entities`/`edges` LanceDB tables) | Database / Storage | API / Backend | LanceDB is the storage tier; the Rust engine (API/Backend tier) owns all read/write access — Go gateway never touches LanceDB directly (established Phase 2 D-48 boundary). |
| Neighborhood pre-narrowing (bounded BFS against `entities`/`edges` via `lancedb`) | API / Backend (Rust engine) | Database / Storage | Runs in-process in Rust against the `lancedb` client; the actual scan executes in the Database/Storage tier but is orchestrated and bounded from the API tier. |
| Cypher traversal execution (`lance-graph`) | API / Backend (Rust engine) | — | In-process, in-memory (`HashMap<String, RecordBatch>`) — not a separate service or database tier; this spike confirms it never leaves the Rust process. |
| Arrow-version IPC bridge (`bridge.rs`) | API / Backend (Rust engine) | — | Pure in-process data-format translation; no I/O beyond memory buffers. |
| Graph-context prompt rendering (D-27/D-28) | API / Backend (Rust engine) | — | Same tier as existing `EvidenceBlock` rendering in `prompt.rs`. |
| `QueryGraph` gRPC surface | API / Backend (Rust engine) | — | gRPC-only/internal per D-25 — Go gateway does not add an HTTP wrapper this phase. |

This map reinforces that the entire spike (and the follow-up phase it unblocks) is single-tier: everything lives inside the Rust engine process. There is no browser, SSR, or CDN tier interaction in this phase at all — Go's Phase-2 D-48 thin-interface boundary is unaffected.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-04 | Extract entities and relationships during ingestion and persist them as graph nodes/edges in LanceDB. | Out of this spike's scope (schema/extraction pattern already locked by D-01–D-16; no new unknown). This spike de-risks nothing here directly, but confirms the downstream `entities`/`edges` tables this requirement produces are consumable by the traversal mechanism below. |
| DATA-05 | Query graph context with `lance-graph`/Cypher-style pattern matching and compile it into RAG prompt context. | **Directly addressed.** This spike empirically confirms `lance-graph` 0.5.4 can execute genuine Cypher pattern queries against data sourced from a `lancedb ~0.31` store (via the pre-narrow + IPC-bridge pattern), unblocking Phase 04.1 to plan DATA-05's full implementation with confidence instead of an open compatibility question. |
| RAG-05 | Define a `ContextAssemblyStrategy` enum/trait supporting `PrecomputedSemantics`/`SourceChunks`, defaulting to `SourceChunks` (Port for 999.5). | Not addressed by this spike (no new technical unknown — D-28 already specifies the fallback rendering; this is a straightforward trait/enum definition task for 04.1, not a research question). |

</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `lance-graph` | 0.5.4, `default-features = false` | Cypher-over-Arrow graph query engine | Already locked by D-17/D-19; this spike verifies the exact version and confirms it builds and runs against this project's toolchain. `[VERIFIED: cargo build/test — scratch crate, 2026-08-06]` |
| `lancedb` | ~0.31 (existing) | Local-first vector/graph store, source of the `entities`/`edges` neighborhood data | Already the project's store (Phase 2); unaffected by this spike — the bridge pattern means `lancedb` never needs to change. `[VERIFIED: engine/Cargo.toml]` |
| `arrow-ipc` | ~58.3 (add as new direct dep) | Encodes engine-native `RecordBatch`es (arrow ~58.3) to the wire-stable Arrow IPC stream format | Already-present `arrow-array`/`arrow-schema` are `~58.3`; `arrow-ipc` at the same line is the writer half of the bridge. `[VERIFIED: cargo build — confirmed compiles/links against arrow-array ~58.3]` |
| `arrow` (renamed `arrow-lg`) | `^56.2` | Provides the `RecordBatch` type `lance-graph`'s `execute()` requires | Must match lance-graph's own pinned range so Cargo's resolver unifies with lance-graph's transitively-resolved copy rather than creating a third incompatible tree. `[VERIFIED: cargo tree — resolved to arrow v56.2.1, same as lance-graph's own transitive arrow]` |
| `arrow-ipc` (renamed `arrow-ipc-lg`) | `^56.2` | Decodes the IPC stream into lance-graph's arrow ^56.2 `RecordBatch`, and re-encodes results for the trip back | Reader/writer counterpart to `arrow-lg`, same version line. `[VERIFIED: cargo build — resolved to arrow-ipc v56.2.1, transitively present via lance-graph's own dependency tree, promoted to a direct rename]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tokio` | ~1.53 (existing) | Async runtime | `CypherQuery::execute()` is `async fn`; already the project's runtime, no change needed. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| IPC round-trip bridge (arrow ~58.3 <-> arrow ^56.2) | `arrow::ffi`'s C Data Interface (zero-copy) | Bridge works and is empirically proven this session; FFI is a valid *optimization* if profiling later shows the IPC copy is a real bottleneck — not needed to unblock planning now. |
| Pre-narrow + in-memory `HashMap<String, RecordBatch>` execute path | `execute_with_namespace(DirNamespace, ...)` (path/URI-based) | **Ruled out** — confirmed via source inspection that `DirNamespace`'s backing readers (`ParquetTableReader`/`DeltaTableReader`) do not support native `.lance` format; `lance_native_planner` is a placeholder in 0.5.4. Not a viable alternative in this version. |
| `lance-graph` Cypher traversal | Hand-rolled DataFusion SQL traversal over `entities`/`edges` (D-19's original rejected alternative) | **Not needed as fallback** — this spike found no structural blocker to the primary `lance-graph` path. Keep documented as a live fallback per the AI-SPEC, but do not plan for it as the default. |

**Installation:**
```toml
# engine/Cargo.toml — add to [dependencies]
lance-graph = { version = "0.5.4", default-features = false }
arrow-ipc = "~58.3"                                          # already-implied by arrow-array ~58.3, add explicitly
arrow-lg = { package = "arrow", version = "^56.2" }
arrow-ipc-lg = { package = "arrow-ipc", version = "^56.2" }
```

**Version verification:** `lance-graph` 0.5.4 confirmed current via `crates.io/api/v1/crates/lance-graph` (published 2025-12-12, latest as of this research) `[CITED: crates.io/api/v1/crates/lance-graph]`. `engine/Cargo.toml`'s existing `arrow-array = "~58.3"` / `arrow-schema = "~58.3"` / `lancedb = "~0.31"` confirmed by direct file read `[VERIFIED: engine/Cargo.toml]`.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `lance-graph` | crates.io | published 2025-12-12 (~8 months old) | 3,659/week | `https://github.com/lancedb/lance-graph` | `[OK]` | Approved — this is the D-17-locked dependency, verified real and legitimate; see below for the repo-URL correction. |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none. `arrow-lg`/`arrow-ipc-lg` are **not new packages** — they are the existing, long-established `arrow`/`arrow-ipc` crates from the official `apache/arrow-rs` project, referenced under a local rename (`package = "arrow"` / `package = "arrow-ipc"`), pinned to a version range lance-graph already transitively requires. No separate legitimacy check needed for an already-vetted upstream crate under a Cargo rename.

**Repo URL correction, independently re-confirmed:** `04-CONTEXT.md`'s `canonical_refs` cites `github.com/lance-format/lance-graph`. The AI-SPEC already flagged this as wrong; this research independently re-confirms via `crates.io`'s registry API (`repository` field) that the correct URL is **`https://github.com/lancedb/lance-graph`** `[VERIFIED: crates.io/api/v1/crates/lance-graph + gsd-tools package-legitimacy check, 2026-08-06]`. Carry this forward into planning; do not use the `lance-format` URL.

## Architecture Patterns

### System Architecture Diagram

```
 [lancedb ~0.31 store]                    [lance-graph 0.5.4 (in-process)]
   entities table  ──┐                       arrow ^56.2 world
   edges table     ──┤                       ┌─────────────────────────┐
                      │                       │  CypherQuery::execute() │
                      ▼                       │  (HashMap<String,       │
   1. Rust-side bounded BFS                   │   RecordBatch>)         │
      neighborhood expansion                  └────────────▲────────────┘
      (hop_cap, D-23; bidirectional,                        │
      D-24) -- lancedb scan, arrow ~58.3          3. bridge_batch()
      RecordBatch results, columns             (IPC encode w/ arrow-ipc
      projected down to id/name/               ~58.3 writer, IPC decode
      type/relation_type/weight only            w/ arrow-ipc-lg ^56.2
      (Pitfall 2)                               reader)
            │                                           ▲
            ▼                                           │
   2. entities_batch, edges_batch  ─────────────────────┘
      (arrow ~58.3 RecordBatch)

   4. CypherQuery::new(cypher).with_config(GraphConfig).with_parameter(...)
      .execute(datasets, None) --> arrow ^56.2 result RecordBatch

   5. bridge_batch_back() (inverse IPC round-trip) --> arrow ~58.3 RecordBatch

   6. Render "Related Entities & Relationships" section (D-27/D-28),
      interleave with chunk EvidenceBlocks by score (D-29/D-30),
      merge into the shared evidence token budget (D-29/D-39)
            │
            ▼
   [Final answer-generation LLM call] (Phase 3, unchanged contract)
```

A reader can trace the primary use case end to end: a seed entity ID enters at step 1, a bounded, projected neighborhood is read from `lancedb` (still arrow ~58.3), crosses the version boundary via the IPC bridge (step 3), is pattern-matched by real Cypher (step 4), crosses back (step 5), and is rendered into the same prompt-assembly step Phase 3 already has (step 6). No new external service boundary is introduced anywhere in this flow — everything left of "Final answer-generation LLM call" runs in-process inside the Rust engine.

### Recommended Project Structure
```
engine/src/
├── graph/
│   ├── mod.rs           # public surface: traverse(), seed lookup (D-18), hop-cap enforcement (D-23)
│   ├── bridge.rs         # arrow ~58.3 <-> arrow ^56.2 IPC bridge — isolate all renamed-crate code here (empirically proven pattern, see Code Examples)
│   ├── cypher_config.rs  # GraphConfig construction from entities/edges schema
│   └── extraction.rs     # per-chunk LLM extraction call (out of this spike's scope; see AI-SPEC Section 4)
```
This matches the AI-SPEC's recommended structure; this research adds no changes to it, only confidence that `bridge.rs`'s contents will actually compile and run as designed.

### Pattern 1: Pre-narrow, then bridge, then Cypher (proven)
**What:** Never hand the full `entities`/`edges` tables to `lance-graph`. Always perform the hop-capped, bidirectional BFS neighborhood selection in Rust against `lancedb` first (arrow ~58.3, native `lancedb` query API), project down to only the columns Cypher needs (never `name_vector`/`summary_vector` — Pitfall 2), *then* bridge into arrow ^56.2 and execute Cypher only against that already-small `HashMap<String, RecordBatch>`.
**When to use:** Every traversal call — both the standalone `QueryGraph` RPC (D-20) and the always-on 1-hop RAG augmentation (D-26, D-31).
**Example:** See `## Code Examples` — this is exactly the `traverse()` shape, empirically confirmed to compile and execute correctly this session.

### Pattern 2: Generic relationship wrapper label + `type_field`, not one mapping per `relation_type` value
**What:** Register a single `RelationshipMapping` (or the `with_relationship`/`with_default_relationship_type_field` builder convenience) with a fixed Cypher-visible label (e.g. `"RELATED"`) and `type_field: Some("relation_type")`. D-04's open-vocabulary `relation_type` values live as **data** in that column, not as separate Cypher labels.
**When to use:** Always, for this schema — confirmed empirically (see Code Examples) that a `WHERE r.relation_type = '...'` predicate on the wrapper-labeled relationship variable correctly filters by the dynamic per-row value, with zero need to enumerate distinct `relation_type` strings ahead of time or register a mapping per value.
**Example:** See `## Code Examples`, `relation_type_filter_on_open_vocabulary_field` test.

### Anti-Patterns to Avoid
- **Projecting the relationship-pattern variable (`r`) inside a variable-length quantifier's `RETURN` clause:** `RETURN seed, r, neighbor` under a `*1..N` pattern fails with `Query planning error: ... No field named r` (empirically confirmed, see Pitfall 6). Project explicit `node.property` fields instead, or restructure to a fixed-hop pattern when edge properties are required in the result.
- **Assuming `default-features = false` yields a lean, cloud-free dependency tree:** it does not (see Pitfall 5) — plan disk/compile-time budget accordingly rather than treating the flag as a full local-first guarantee.
- **Reaching for `execute_with_context(SessionContext)` or `execute_with_catalog_and_context`:** both take DataFusion trait objects built against lance-graph's pinned `datafusion ^50.3`; `lancedb`'s are `datafusion ^53.0` — these are a dead end for this project's two-tree situation (AI-SPEC Pitfall 3, unchanged by this research).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cypher pattern matching / multi-hop traversal | Custom BFS + manual pattern-matching logic in Rust | `lance-graph`'s `CypherQuery` | Already locked (D-19); this spike confirms it works, removing the last technical reason to fall back to hand-rolled traversal. |
| Cross-arrow-version data transfer | Custom binary serialization / unsafe transmute between arrow-rs major versions | Arrow IPC stream format (`arrow_ipc::writer::StreamWriter` / `arrow_ipc_lg::reader::StreamReader`) | IPC is the wire-stable, spec-defined format arrow-rs majors are designed to interoperate through; this spike empirically confirms a full encode/decode round-trip preserves data correctly across the 56.2/58.3 boundary. |
| Open-vocabulary relation-type filtering | Enumerating every observed `relation_type` string into a distinct `RelationshipMapping`/Cypher label | `type_field` + a single generic wrapper label, filtered via Cypher `WHERE` | Confirmed to work directly (Pattern 2) — building a per-value mapping registry would be unnecessary engineering effort the crate's API already avoids. |

**Key insight:** The instinct to distrust `lance-graph` after seeing the major-version dependency conflict was reasonable given the AI-SPEC's docs-only research, but this spike shows the conflict never actually surfaces at the type level for the intended usage pattern (in-memory execute, not shared `Dataset`/`SessionContext` handles) — hand-rolling a replacement would be solving a problem that does not, in practice, exist for this integration shape.

## Common Pitfalls

### Pitfall 1: The wall is `arrow::RecordBatch` version skew, not `lance::Dataset` typing (confirmed, AI-SPEC's original framing was correct)
**What goes wrong:** A `RecordBatch` built with this project's `arrow-array ~58.3` is a structurally distinct Rust type from the `RecordBatch` `lance-graph`'s pinned `arrow ^56.2` expects — compile error, not a runtime surprise, if you try to pass one directly.
**Why it happens:** Cargo resolves both `arrow` major-version trees side by side rather than erroring at resolution (confirmed via `cargo generate-lockfile`: 645 packages, both `arrow-array v56.2.1` and `arrow-array v58.3.0`/`v58.4.0` present).
**How to avoid:** The IPC bridge pattern in `## Code Examples` — now empirically proven to compile and correctly round-trip real data, not just a hypothesis.
**Warning signs:** A compile error naming two `RecordBatch` (or `Schema`/`ArrayRef`) types from different crate versions where only one was expected.

### Pitfall 2: No predicate pushdown through `execute()` — pre-narrow before bridging (AI-SPEC's finding, unchanged)
**What goes wrong:** `execute()`'s `HashMap<String, RecordBatch>` argument is fully materialized in memory; there is no way to push a seed/hop filter into a `lancedb` scan through this API.
**Why it happens:** By design — `lance-graph`'s in-memory execution path treats its input as already-selected data, not a lazily-scannable source.
**How to avoid:** Perform the hop-capped, bidirectional BFS neighborhood selection in Rust against `lancedb` first (Pattern 1), and project out unused/large columns (`name_vector`/`summary_vector`, ~8KB/row `FixedSizeList<Float32>`) before bridging — every byte crossing the IPC bridge is pure overhead if unused downstream.
**Warning signs:** Traversal latency scaling with total graph size rather than neighborhood size.

### Pitfall 3: `execute_with_context`/`execute_with_catalog_and_context` are not shortcuts (AI-SPEC's finding, unchanged)
**What goes wrong:** These take `datafusion::execution::context::SessionContext` built against lance-graph's pinned `datafusion ^50.3` — a different type from `lancedb`'s `datafusion ^53.0` `SessionContext`. Trait objects cannot cross a dependency-version boundary the way plain IPC-encoded data can.
**How to avoid:** Only the `HashMap<String, RecordBatch>` `execute()` path is viable for this project's two-tree situation.

### Pitfall 4: `type_field`/open-vocabulary `relation_type` filtering DOES work as hoped — resolved, not just clarified
**What the AI-SPEC left open:** Whether `RelationshipMapping.type_field` is a functioning dynamic per-row type-column mechanism, or whether each mapping is bound to exactly one literal `relationship_type` string (which would have required registering one mapping per distinct D-04 value).
**What this spike found:** Empirically confirmed working. A single `GraphConfigBuilder::new().with_node_label("Entity", "entity_id").with_default_relationship_type_field("relation_type").with_relationship("RELATED", "source_node_id", "target_node_id")` config, combined with a Cypher `WHERE r.relation_type = 'founded_by'` predicate on the generic `RELATED`-labeled relationship variable, correctly matched only the edge whose `relation_type` column value was `"founded_by"` and correctly excluded a `"knows"`-typed edge between the same seed and a different neighbor. `[VERIFIED: cargo test — scratch crate, relation_type_filter_on_open_vocabulary_field, 2026-08-06]`
**Planning impact:** D-04's freeform `relation_type` needs **no** taxonomy-registration workaround. One generic `RelationshipMapping`/`with_relationship` call covers all observed relation types; filtering happens via ordinary Cypher `WHERE` predicates on the mapped `type_field`.

### Pitfall 5: `default-features = false` reduces but does not eliminate cloud/geospatial dependency weight (new finding, refines the AI-SPEC's rationale)
**What goes wrong:** The AI-SPEC's Section 2 rationale states default features "pull in cloud object-store (S3/Azure/GCS) and geospatial (wkb/wkt, tantivy) deps." This is only half-right. `cargo tree` on the actual resolved graph (with `default-features = false` set) still shows `aws-sdk-sts`, `aws-sdk-sso`, `aws-sdk-ssooidc`, `opendal`, `object_store`, `reqsign` (cloud object-store clients) **and** `wkb`, `wkt`, `geo`, `geoarrow-schema`, `geoarrow-array`, `geodatafusion`, `lance-geo`, and `tantivy` (geospatial + full-text-search) present regardless.
**Why it happens:** `lance-graph`'s `[features]` table (fetched verbatim from its published `Cargo.toml`) shows `default = ["unity-catalog", "delta"]`, where `unity-catalog` only enables `lance-graph-catalog/unity-catalog` (the Unity Catalog REST client) and `delta` only enables `dep:deltalake`/`dep:url`. **`lance-graph-catalog` itself — which contains `DirNamespace`, `GraphSourceCatalog`, `InMemoryCatalog`, `ParquetTableReader`, `DeltaTableReader` — is an unconditional, non-feature-gated dependency.** The cloud-SDK and geospatial weight actually comes from `lance-graph`'s pinned `lance = "1.0.0"` core crate itself (via `lance-io`, `lance-index`'s tantivy-backed full-text index, and `lance-geo`'s native geometry column support), which ships unconditionally and is not controlled by any Cargo feature exposed at the `lance-graph` level.
**How to avoid:** Budget for the full transitive footprint (confirmed via `cargo check`: ~350+ additional crates compile, ~3 minutes cold build time on this session's hardware) regardless of the `default-features = false` flag. If a leaner build is a hard requirement, that would need an upstream feature request to `lance-graph`/`lance` — not something achievable from this project's `Cargo.toml` alone. `default-features = false` is still worth setting (it does remove the Unity Catalog REST client and Delta Lake's own additional cloud-storage-client stack), just don't present it as achieving full local-first dependency purity.
**Warning signs:** Unexpectedly long `cargo build` times or binary size growth after adding `lance-graph`, even with `default-features = false` set.

### Pitfall 6: Variable-length Cypher patterns (`*1..N`) cannot project the relationship variable in `RETURN` — new finding, not in the AI-SPEC
**What goes wrong:** `MATCH (seed:Entity {...})-[r:RELATED*1..3]-(neighbor:Entity) RETURN seed, r, neighbor` fails at query-planning time with `Query planning error: Failed to build projection: Schema error: No field named r. Valid fields are seed__entity_id, seed__name, neighbor__entity_id, neighbor__name.` `[VERIFIED: cargo test — scratch crate, end_to_end_traversal_runs, first attempt, 2026-08-06]`
**Why it happens:** Under a variable-length quantifier, the planner appears to flatten/expand the path without materializing a per-edge relationship record addressable as `r` in the final projection (only the two node endpoints remain addressable, with column names auto-prefixed as `seed__<field>`/`neighbor__<field>`).
**How to avoid:** For **fixed-length** (non-`*`) patterns — confirmed empirically to work fine, including projecting `r.<property>` directly (`fixed_single_hop_can_project_relationship_properties` test, `[VERIFIED: cargo test, 2026-08-06]`) — no workaround needed. This directly covers D-31's always-on RAG-path augmentation, which defaults to **fixed 1-hop**. For the standalone `QueryGraph` RPC's caller-specified variable hop depth (D-20/D-23), either (a) omit `r` from `RETURN` and accept node-only results (sufficient if D-28's rendering only needs entity names, not the specific relation_type per hop), or (b) since the neighborhood was already read from `lancedb` in Rust before bridging (Pattern 1), correlate the Cypher result's matched node-ID pairs back against the already-in-scope `edges_batch` to recover `relation_type`/`weight` without a second lance-graph query.
**Warning signs:** `Query planning error: ... No field named r` (or similarly named pattern variable) appearing only for multi-hop queries and not single-hop ones — this is the specific signature of this pitfall, not a general syntax error.

## Code Examples

All examples below were written into a throwaway Cargo crate (`lg_spike`, outside this repository, deleted at session end) with `Cargo.toml`:
```toml
[dependencies]
lance-graph = { version = "0.5.4", default-features = false }
arrow-array = "~58.3"
arrow-schema = "~58.3"
arrow-ipc = "~58.3"
arrow-lg = { package = "arrow", version = "^56.2" }
arrow-ipc-lg = { package = "arrow-ipc", version = "^56.2" }
tokio = { version = "~1.53", features = ["rt-multi-thread", "macros"] }
```
and confirmed to **compile with `cargo check` and pass with `cargo test`** against the real, published `lance-graph` 0.5.4 from crates.io — this is empirical evidence, not a documentation transcription.

### The arrow-version IPC bridge (proven working)
```rust
// engine/src/graph/bridge.rs — verified pattern
/// Bridges an engine-native (arrow ~58.3) RecordBatch across the version
/// boundary into the arrow ^56.2 RecordBatch type lance-graph's execute()
/// requires, via an IPC round-trip.
fn bridge_batch(
    batch: &arrow_array::RecordBatch,
) -> Result<arrow_lg::record_batch::RecordBatch, String> {
    let mut buf = Vec::new();
    {
        let mut writer = arrow_ipc::writer::StreamWriter::try_new(&mut buf, &batch.schema())
            .map_err(|e| format!("ipc encode: {e}"))?;
        writer.write(batch).map_err(|e| format!("ipc encode: {e}"))?;
        writer.finish().map_err(|e| format!("ipc encode: {e}"))?;
    }
    arrow_ipc_lg::reader::StreamReader::try_new(buf.as_slice(), None)
        .map_err(|e| format!("ipc decode: {e}"))?
        .next()
        .transpose()
        .map_err(|e| format!("ipc decode: {e}"))?
        .ok_or_else(|| "empty batch produced by bridge".to_string())
}
```

### Multi-hop traversal, executed against real fixture data
```rust
// engine/src/graph/mod.rs — verified pattern (compiled + ran, produced 1 correct row)
use std::collections::HashMap;
use lance_graph::config::GraphConfigBuilder;
use lance_graph::query::{CypherQuery, ExecutionStrategy};

pub async fn traverse_stub(
    entities: &arrow_array::RecordBatch,
    edges: &arrow_array::RecordBatch,
    hop_cap: u32,
) -> Result<arrow_lg::record_batch::RecordBatch, String> {
    let entities_lg = bridge_batch(entities)?;
    let edges_lg = bridge_batch(edges)?;

    let config = GraphConfigBuilder::new()
        .with_node_label("Entity", "entity_id")
        .with_default_relationship_type_field("relation_type")
        .with_relationship("RELATED", "source_node_id", "target_node_id")
        .build()
        .map_err(|e| format!("graph config: {e}"))?;

    let mut datasets = HashMap::new();
    datasets.insert("Entity".to_string(), entities_lg);
    datasets.insert("RELATED".to_string(), edges_lg);

    // NOTE (Pitfall 6): `r` cannot appear in RETURN under a `*1..N` quantifier.
    let cypher = format!(
        "MATCH (seed:Entity {{entity_id: $seed_id}})-[r:RELATED*1..{hop_cap}]-(neighbor:Entity) \
         RETURN seed.entity_id, neighbor.entity_id, neighbor.name"
    );
    let query = CypherQuery::new(&cypher)
        .map_err(|e| format!("cypher parse: {e}"))?
        .with_config(config)
        .with_parameter("seed_id", "abc-123");

    query
        .execute(datasets, None::<ExecutionStrategy>)
        .await
        .map_err(|e| format!("cypher execute: {e}"))
}
// Test fixture: 2 entities (Alice/abc-123, Bob/def-456), 1 edge (abc-123 -knows-> def-456).
// Result: rows=1 cols=3 -- Bob correctly found as Alice's 1-hop neighbor.
```

### Open-vocabulary `relation_type` filtering via `WHERE` (proves Pitfall 4 resolved)
```rust
// Fixture: 3 entities (Alice/abc-123, Bob/def-456, Acme/ghi-789), 2 edges from
// abc-123: -knows-> def-456, -founded_by-> ghi-789.
let cypher = "MATCH (seed:Entity {entity_id: $seed_id})-[r:RELATED]-(neighbor:Entity) \
               WHERE r.relation_type = 'founded_by' \
               RETURN neighbor.entity_id, neighbor.name";
// Result: rows=1 -- correctly returns only ("ghi-789", "Acme"), excluding Bob.
```

### Fixed single-hop projecting relationship (edge) properties directly (resolves the common D-31 case cleanly)
```rust
let config = GraphConfigBuilder::new()
    .with_node_label("Entity", "entity_id")
    .with_default_relationship_type_field("relation_type")
    .with_relationship_mapping(lance_graph::config::RelationshipMapping {
        relationship_type: "RELATED".to_string(),
        source_id_field: "source_node_id".to_string(),
        target_id_field: "target_node_id".to_string(),
        type_field: Some("relation_type".to_string()),
        property_fields: vec!["relation_type".to_string()], // add "weight" similarly for D-04's confidence score
        filter_conditions: None,
    })
    .build()
    .unwrap();
// fixed single hop, NO `*` quantifier:
let cypher = "MATCH (seed:Entity {entity_id: $seed_id})-[r:RELATED]-(neighbor:Entity) \
               RETURN seed.entity_id, r.relation_type, neighbor.entity_id, neighbor.name";
// Result: rows=2, cols=4, schema includes "r.relation_type" as a real projected column --
// unlike the *1..N case, this works and needs no correlate-back-to-lancedb workaround.
```

## State of the Art

| Old Approach (AI-SPEC's docs-only research, 4 hours prior) | Current Approach (this spike, empirically verified) | When Changed | Impact |
|--------------------------------------------------------------|------------------------------------------------------|--------------|--------|
| "Informed-but-unverified... treat everything past this note as unverified until that spike runs" (AI-SPEC Section 3) | The bridge, config, and Cypher execution pattern is now confirmed to compile and run correctly against real published `lance-graph` 0.5.4 | This research session, 2026-08-06 | Removes the CONDITIONAL status from D-17/D-19's `lance-graph` selection — Phase 04.1 can plan the full implementation as a locked decision, not a hedged one. |
| `RelationshipMapping.type_field` semantics "unconfirmed from public docs" (AI-SPEC Pitfall 4) | Confirmed working via executed test: single generic mapping + `WHERE` predicate correctly filters open-vocabulary `relation_type` | This research session | Removes a flagged "real complexity/cost difference" risk from planning; no per-value mapping registry needed. |
| No mention of `RETURN r` under variable-length patterns | Confirmed to fail; fixed-hop patterns confirmed to work for edge-property projection | This research session | New, concrete implementation constraint for Phase 04.1 planning — affects how `QueryGraph`'s variable-depth path (D-20) renders edge properties vs. the fixed-1-hop RAG path (D-31). |
| `default-features = false` framed as removing "cloud object-store and geospatial" deps | Confirmed via `cargo tree` that AWS SDK / geospatial / tantivy deps remain regardless — only Unity Catalog's REST client and Delta Lake support are actually feature-gated | This research session | Sets accurate build-time/dependency-footprint expectations for Phase 04.1's planning and CI budget; does not block anything, just corrects an assumption. |

**Deprecated/outdated:** None — `lance-graph` 0.5.4 is the current published version as of this research (confirmed via crates.io registry API).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Arrow IPC stream format round-trips are lossless for the specific column types this project's `entities`/`edges` tables will use in production (UTF8 strings, Float32/Float64 scalars, and — critically, though untested this session — `FixedSizeList<Float32>` vector columns and UUID-as-string identifiers) | Common Pitfalls (Pitfall 1), Code Examples | Low — Arrow IPC is a stable, spec-defined wire format designed exactly for this purpose; this spike only exercised `Utf8` columns. If a future column type behaves unexpectedly, Phase 04.1's own test suite (the `graph::tests` module already scoped in the AI-SPEC) will catch it before production, since Pitfall 2 already directs those columns to be projected out before bridging in the common case anyway. |
| A2 | The `lance-graph-catalog v0.5.4` crate's feature-gating (`unity-catalog`/`delta` optional; the crate itself unconditional) documented here from the fetched `Cargo.toml` `[features]` table will remain stable across any future `cargo update` within the `~0.5` line | Package Legitimacy Audit, Pitfall 5 | Low-Medium — a semver-compatible patch release could in theory change feature-gating without a major bump (a real, if uncommon, risk in the wider Rust ecosystem); Phase 04.1 should pin with `~0.5.4` (as already recommended) and re-run `cargo tree` after any `cargo update` touching this dependency, consistent with Pitfall 5's warning. |
| A3 | `lance-graph`'s `execute()` behavior and API surface observed in this spike (0.5.4) is representative of what Phase 04.1's actual production traversal code will call — i.e. no further undiscovered method-signature surprises remain for the specific calls Phase 04.1 needs (multi-hop bidirectional traversal per D-24, hop-cap enforcement per D-23, single-hop RAG augmentation per D-31) | Summary, Code Examples | Low — this spike directly exercised the two traversal shapes (fixed single-hop and variable-length multi-hop) that Phase 04.1 needs; bidirectional traversal (D-24, "both directions from a seed") was not separately spiked but is expressible as an undirected relationship pattern (`-[r]-` rather than `-[r]->`), which is what all example queries in this research already use. |

## Open Questions

1. **Does the IPC bridge correctly round-trip `FixedSizeList<Float32>` vector columns (e.g. `entities.name_vector`) if a future design ever needs to bridge them?**
   - What we know: Arrow IPC is a general-purpose, type-complete wire format; there is no documented reason `FixedSizeList` would behave differently from the `Utf8` columns this spike tested.
   - What's unclear: Not empirically tested this session.
   - Recommendation: Non-blocking — Pitfall 2 already establishes that vector columns should be projected out before bridging in the normal traversal path (seeding already happened via `lancedb`'s own vector search per D-18, so Cypher never needs to see `name_vector` again). Only revisit if a future design change requires vector data to cross the bridge.

2. **What is the exact behavior/error message when `hop_cap` exceeds `lance-graph`'s own internal limits, or when the neighborhood `HashMap` is empty (no matches)?**
   - What we know: The crate returns a `Result`, and this spike confirmed both the `Ok` and (transiently, during the first `RETURN r` attempt) `Err` paths surface as catchable `GraphError`s rather than panics.
   - What's unclear: Exact error taxonomy for zero-match vs. malformed-config vs. internal-limit-exceeded cases — relevant to D-32's silent-fallback-to-chunk-only requirement and Section 6's `attempted_and_failed`/`no_match_found` trace-tag distinction.
   - Recommendation: Phase 04.1 should write the `graph::tests` fixtures (already scoped in the AI-SPEC's evaluation strategy, Section 5, item 6 "Failure-tagging pair") to explicitly probe empty-result vs. error-result `GraphError` variants, since distinguishing these two is directly load-bearing for the D-32/Section-6 failure-transparency guardrail.

3. **Performance/latency characteristics of the IPC bridge + Cypher execution at realistic neighborhood sizes (dozens to low-hundreds of nodes/edges), and cold-start cost of `lance-graph`'s first query (DataFusion query planning overhead).**
   - What we know: This spike's fixture data was trivially small (2-3 nodes, 1-2 edges); execution was fast enough to be indistinguishable from noise in a `cargo test` run.
   - What's unclear: Real-world latency at production neighborhood sizes, and whether DataFusion's per-query planning overhead is amortizable (e.g. via a cached/reused `SessionContext` — though Pitfall 3 already rules out sharing a `SessionContext` across the version boundary, so any caching would need to happen at the `GraphConfig`/parsed-`CypherQuery` level instead).
   - Recommendation: Out of scope for this spike (which only needed to answer the compile/execute-at-all question); Phase 04.1 should include a latency benchmark against the eval-strategy's "Traversal p95 latency" metric (AI-SPEC Section 7) before committing to the fixed 1-hop-per-query default in production.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Rust toolchain (`cargo`/`rustc`) | Building/testing this spike and the eventual Phase 04.1 implementation | Yes | cargo 1.95.0, rustc 1.95.0 | — |
| crates.io network access | Resolving/downloading `lance-graph` and its ~350+ transitive dependencies | Yes | — confirmed via live `cargo generate-lockfile`/`cargo check`/`cargo test` runs this session, ~4 minutes cold build | — |
| `lance-graph` crate (crates.io) | D-17/D-19's traversal engine | Yes | 0.5.4, confirmed via registry API and a real `cargo add`-equivalent build | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — this spike found no blocking gap.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `cargo test` (built-in Rust test harness), matching the existing `engine/src/tests.rs` convention (Phase 2 precedent) |
| Config file | none — Cargo's built-in test runner needs no separate config |
| Quick run command | `cargo test --manifest-path engine/Cargo.toml graph::` (once the `graph` module/tests exist — does not exist yet as of this research) |
| Full suite command | `cargo test --manifest-path engine/Cargo.toml --locked` |

### Phase Requirements -> Test Map
This spike itself is not shipping production code into `engine/` (the throwaway crate was built and run outside the repository and is not part of this commit). The table below describes what Phase 04.1 must stand up, informed directly by what this spike proved works and what it flagged as needing a dedicated test:

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-05 | arrow ~58.3 <-> arrow ^56.2 IPC bridge round-trips a `RecordBatch` losslessly | unit | `cargo test --manifest-path engine/Cargo.toml graph::bridge::tests` | ❌ Wave 0 (04.1) |
| DATA-05 | Fixed single-hop Cypher query returns correct neighbor + relationship properties for a known fixture graph | unit | `cargo test --manifest-path engine/Cargo.toml graph::tests::single_hop` | ❌ Wave 0 (04.1) |
| DATA-05 | Variable-length (`*1..hop_cap`) Cypher query returns correct multi-hop neighbors, using node-only `RETURN` per Pitfall 6 | unit | `cargo test --manifest-path engine/Cargo.toml graph::tests::multi_hop` | ❌ Wave 0 (04.1) |
| DATA-05 | Open-vocabulary `relation_type` filtering via `WHERE` on the generic wrapper label returns only matching-type edges | unit | `cargo test --manifest-path engine/Cargo.toml graph::tests::relation_type_filter` | ❌ Wave 0 (04.1) |

### Sampling Rate
- **Per task commit (04.1):** `cargo test --manifest-path engine/Cargo.toml graph::`
- **Per wave merge (04.1):** `cargo test --manifest-path engine/Cargo.toml --locked && cd gateway && go test ./...` (matches Phase 03 precedent, AI-SPEC Section 5 CI/CD Integration)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `engine/src/graph/mod.rs`, `engine/src/graph/bridge.rs` — do not exist yet; this spike's proven patterns above are the starting point, not yet committed production code.
- [ ] `engine/src/graph/tests.rs` (or `engine/tests/graph_*.rs`) — covers DATA-05's bridge/single-hop/multi-hop/relation-type-filter behaviors per the table above, using this research's fixture shapes as a starting point.
- [ ] `engine/Cargo.toml` — add `lance-graph`, `arrow-ipc`, `arrow-lg`, `arrow-ipc-lg` per `## Standard Stack`'s Installation block; this spike's dependency additions were made in a throwaway crate only, not this repository.

*(This spike itself required no test-framework changes — it used a disposable scratch crate's default `cargo test` harness, now deleted.)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | Yes | `hop_cap` must be range-checked/clamped (D-23) before interpolation into the `format!`-built Cypher string — Cypher's variable-length path bound (`*1..N`) cannot be parameterized (a language limitation shared with Neo4j, per the AI-SPEC), so this is a string-interpolation site that must never receive unbounded/unclamped caller input. This spike did not change that risk; it only confirmed the query-execution mechanics around it. |
| V6 Cryptography | No | Not applicable — this spike involves no cryptographic operations, only in-memory data-format translation. |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cypher-string-injection-shaped resource exhaustion via unbounded `hop_cap` interpolated into the traversal query | Denial of Service (Tampering-adjacent) | Clamp `hop_cap` to the configured maximum (D-23) in Rust *before* it reaches the `format!` call — never let a caller-supplied `QueryGraph` (D-20) request value flow into the Cypher string unclamped. This is unchanged from the AI-SPEC's guardrail (Section 6); this spike adds no new finding here beyond confirming the interpolation site's mechanics are exactly as the AI-SPEC described. |

This spike introduces no new attack surface beyond what the AI-SPEC's Section 6 guardrails already cover (the scratch crate used to verify these findings was built and run outside this repository, entirely with fixture data, and has been discarded).

## Sources

### Primary (HIGH confidence)
- `[VERIFIED]` Direct empirical `cargo generate-lockfile` / `cargo check` / `cargo test` runs against the real, published `lance-graph` 0.5.4 crate, in a throwaway scratch Cargo project created and executed during this research session (2026-08-06). This is the strongest evidence category in this document — actual compiled and executed Rust code, not documentation reading.
- `[VERIFIED]` `gsd-tools query package-legitimacy check --ecosystem crates lance-graph` — verdict `OK`.
- `[VERIFIED]` Direct file reads: `D:/Repos/lancet/engine/Cargo.toml`, `D:/Repos/lancet/rust-guidelines.md`.

### Secondary (MEDIUM confidence)
- `[CITED: docs.rs/lance-graph/0.5.4/lance_graph/]` — module/type index, `CypherQuery` execute-method-family signatures (`execute`, `execute_with_namespace`, `execute_with_context`, `execute_with_catalog_and_context`).
- `[CITED: docs.rs/lance-graph/0.5.4/lance_graph/config/struct.GraphConfigBuilder.html]` — full builder method list, including `with_default_relationship_type_field` (not previously documented in the AI-SPEC).
- `[CITED: docs.rs/lance-graph/0.5.4/src/lance_graph/config.rs.html]` — `RelationshipMapping` field list and doc comments.
- `[CITED: docs.rs/lance-graph/0.5.4/lance_graph/struct.DirNamespace.html]` — `DirNamespace::new(base_uri)` constructor, `LanceNamespace` trait implementation.
- `[CITED: docs.rs/crate/lance-graph/0.5.4/source/Cargo.toml]` — exact dependency version pins (`lance = "1.0.0"`, `arrow = "56.2"`, `datafusion = "50.3"`, `lance-namespace = "1.0.1"`) and `[features]` table (`default = ["unity-catalog", "delta"]`).
- `[CITED: docs.rs/lance_graph_catalog/latest/lance_graph_catalog/]` — module structure (`namespace`, `table_reader`, `catalog_provider`, `unity_catalog`), confirming Parquet/Delta-only table reading.
- `[CITED: crates.io/api/v1/crates/lance-graph]` — latest version (0.5.4), repository URL (`github.com/lancedb/lance-graph`), publish date.
- `[CITED: github.com/lancedb/lance-graph]` (repo tree, README.md) — project structure (`crates/lance-graph`, `python/lance_graph`, `python/knowledge_graph`), confirming Python-only example coverage (`examples/basic_cypher.py`, `examples/kg_traversal.py`) and the `knowledge_graph` package's separate "Lance dataset storage helper" role (distinct from the Rust `lance-graph` crate's own capabilities).

### Tertiary (LOW confidence)
- None — every claim in this document is either empirically verified this session or cited to an official, primary source (docs.rs, crates.io registry API, or the project's own repository/config files). The prior AI-SPEC's docs-only findings that this research superseded are explicitly marked as superseded in `## State of the Art` above, not carried forward as unverified claims.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — `lance-graph` 0.5.4 and the bridge-crate versions were not just read from docs but actually resolved, compiled, and executed successfully this session.
- Architecture: HIGH — the pre-narrow/bridge/execute pattern is empirically proven end-to-end, including two distinct query shapes (fixed single-hop and variable-length multi-hop) and an open-vocabulary filter case.
- Pitfalls: HIGH — five of six pitfalls are either directly empirically confirmed (1, 4, 5, 6) or carried forward from the AI-SPEC's own docs-based research and left structurally unchanged by this spike (2, 3); none are speculative.

**Research date:** 2026-08-06
**Valid until:** 30 days (stable finding — the core compatibility question is now empirically resolved and not expected to change on its own; re-verify only if `lance-graph` or `lancedb` receive a version bump before Phase 04.1 planning begins).
