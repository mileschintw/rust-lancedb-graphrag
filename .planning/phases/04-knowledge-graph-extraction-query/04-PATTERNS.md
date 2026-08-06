# Phase 4: Knowledge Graph Extraction & Query (Spike) - Pattern Map

**Mapped:** 2026-08-06
**Files analyzed:** 4 (spike-scoped; full DATA-04/DATA-05 implementation file set is out of scope per SPIDR narrowing)
**Analogs found:** 4 / 4

## Scope Note

Per the orchestrator's narrowing (see RESEARCH.md scope note), Phase 04 is a compatibility **spike**, not the full extraction/query implementation. The spike's core empirical work (throwaway crate, `lg_spike`) was built and run **outside this repository and deleted** — no production code from that work exists to pattern-match against. This phase's own PLAN.md is expected to be small: at minimum a `engine/Cargo.toml` dependency addition, and — if the planner opts to check in a proof-of-concept per VALIDATION.md's "and/or a checked-in proof-of-concept" allowance — a minimal `engine/src/graph/{mod.rs,bridge.rs}` pair mirroring RESEARCH.md's proven code. This PATTERNS.md covers both: the config-file edit and the two most likely new Rust files, using the closest existing analogs in `engine/src/`.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `engine/Cargo.toml` | config | — | (self — existing file, additive edit only) | exact |
| `engine/src/graph/mod.rs` | service (module root + public traversal surface) | transform (in-memory Arrow bridge + Cypher execute) | `engine/src/retrieval/mod.rs` | role-match |
| `engine/src/graph/bridge.rs` | utility (pure data-format translation) | transform | `engine/src/retrieval/bm25.rs` (submodule with focused pure-function responsibility, registered via `pub mod` in `mod.rs`) | role-match |
| `engine/src/graph/tests.rs` (or inline `#[cfg(test)] mod tests` block) | test | — | `engine/src/retrieval/tests.rs` | exact |

## Pattern Assignments

### `engine/Cargo.toml` (config)

**Analog:** itself — existing `[dependencies]` block

**Current pattern** (`D:/Repos/lancet/engine/Cargo.toml` lines 6-27):
```toml
[dependencies]
tokio = { version = "~1.53", features = ["rt-multi-thread", "macros"] }
tonic = "~0.14"
...
lancedb = "~0.31"
serde = { version = "~1.0", features = ["derive"] }
serde_json = "~1.0"
arrow-array = "~58.3"
arrow-schema = "~58.3"
...
```

**Additions per RESEARCH.md `## Standard Stack` Installation block** — append, do not reorder existing lines:
```toml
lance-graph = { version = "0.5.4", default-features = false }
arrow-ipc = "~58.3"
arrow-lg = { package = "arrow", version = "^56.2" }
arrow-ipc-lg = { package = "arrow-ipc", version = "^56.2" }
```
Note: `arrow-array = "~58.3"` / `arrow-schema = "~58.3"` already exist in the file — do not duplicate, only add the four new lines above. `tokio` already has `rt-multi-thread`/`macros` features, sufficient for `CypherQuery::execute()`'s `async fn`.

---

### `engine/src/graph/mod.rs` (module root, transform)

**Analog:** `engine/src/retrieval/mod.rs`

**Module doc-comment + submodule registration pattern** (`engine/src/retrieval/mod.rs` lines 1-22):
```rust
//! Typed query validation and deterministic retrieval contracts.
//!
//! This module owns the request and candidate types shared by the dense and
//! lexical paths. ...

use std::{
    collections::HashSet,
    fmt::{Display, Formatter},
};

use futures::future::BoxFuture;
use serde::Serialize;
use uuid::Uuid;

pub mod bm25;
pub mod dense;
pub mod fusion;

pub use bm25::{Bm25Config, Bm25Index};
pub use dense::DenseRetriever;
pub use fusion::{fuse_candidates, FusedCandidate};
```
Apply the same shape to `engine/src/graph/mod.rs`: a module doc-comment describing the pre-narrow/bridge/execute pipeline, `pub mod bridge;`, and re-exports of the public traversal entry point (`traverse()`, per RESEARCH.md's `Recommended Project Structure`).

**Error-kind + typed-error pattern** (`engine/src/retrieval/mod.rs` lines 40-59) — follow this shape for graph errors instead of RESEARCH.md's ad hoc `String` errors in the spike code:
```rust
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RetrievalErrorKind {
    EmptyQuery,
    QueryTooLong,
    InvalidDocumentId,
    ...
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RetrievalError {
    pub kind: RetrievalErrorKind,
    message: String,
}
```
If the phase's plan introduces any traversal code beyond the raw bridge (unlikely for a pure spike commit), prefer this typed-error convention over `Result<T, String>` to match project style — RESEARCH.md's proven snippets use `String` only because they were written in a disposable scratch crate, not against this codebase's conventions.

**Async DB-manager init pattern for reference** (`engine/src/db/mod.rs` lines 1-10, 20-30) — shows the project's `Result<Self, String>` + `.map_err(|error| format!(...))` convention used throughout `engine/src/db/mod.rs`; the RESEARCH.md bridge functions already follow this same `map_err(|e| format!("..."))` idiom, so no change needed there — it already matches house style.

---

### `engine/src/graph/bridge.rs` (utility, transform)

**Analog:** `engine/src/retrieval/bm25.rs` (focused, pure-function submodule pattern; registered via `pub mod bm25;` in `mod.rs`, consumed via `use super::bm25::...` from `tests.rs`)

**Core content — this is RESEARCH.md's already-empirically-verified code**, to be copied near-verbatim if this phase checks in a proof-of-concept (`04-RESEARCH.md` lines 213-236):
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

**Traversal entry point** (`04-RESEARCH.md` lines 239-281, the `traverse_stub` function) — belongs in `mod.rs` per the recommended structure, calling `bridge_batch` from `bridge.rs`:
```rust
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
    // ... see RESEARCH.md for full body, including the hop_cap-into-Cypher-string
    // interpolation site that MUST be clamped per the Security Domain guardrail
    // (V5 Input Validation, RESEARCH.md line 400).
}
```

**Security note carried into this pattern:** `hop_cap` is interpolated directly into a `format!`-built Cypher string (Cypher's `*1..N` bound cannot be parameterized). Any code that builds this string in `engine/src/graph/mod.rs` MUST clamp/range-check `hop_cap` before interpolation — mirrors existing bounded-input patterns already in `engine/src/retrieval/mod.rs` (`MAX_SERVICE_CANDIDATE_LIMIT`, `MAX_SERVICE_FINAL_LIMIT` constants, lines 30-31).

---

### `engine/src/graph/tests.rs` (test)

**Analog:** `engine/src/retrieval/tests.rs`

**Fixture-builder + `#[test]` pattern** (`engine/src/retrieval/tests.rs` lines 1-40):
```rust
use std::sync::Arc;

use arrow_array::{
    new_null_array, types::Float32Type, FixedSizeListArray, Int32Array, Int64Array, RecordBatch,
    StringArray,
};
use engine::db::DatabaseManager;
use uuid::Uuid;

use super::bm25::analyze;
use super::{
    fuse_candidates, Bm25Config, Bm25Index, Candidate, DenseRetriever, QueryFilters, QueryRequest,
    RetrievalErrorKind, RetrievalSettings, MAX_SERVICE_CANDIDATE_LIMIT, MAX_SERVICE_FINAL_LIMIT,
};

fn candidate(document_id: &str, chunk_id: &str, content: &str) -> Candidate {
    Candidate { /* ... field-by-field fixture builder ... */ }
}

#[test]
fn bm25_full_unicode_analyzer_and_global_idf() {
    let first = Uuid::new_v4().to_string();
    ...
}
```
Apply this shape to `engine/src/graph/tests.rs`: a small `entities_batch()`/`edges_batch()` `arrow_array::RecordBatch` fixture-builder function (mirroring RESEARCH.md's "2 entities / 1 edge" and "3 entities / 2 edges" fixtures), then `#[test]` functions per RESEARCH.md's proven cases: bridge round-trip, single-hop with edge-property projection, multi-hop node-only, and open-vocabulary `relation_type` `WHERE` filter (RESEARCH.md `## Code Examples`, all four already have exact expected-row-count assertions documented).

**Module registration for tests:** `engine/src/lib.rs` (all 8 lines) shows every top-level module (`client`, `db`, `generation`, `prompt`, `rerank`, `retrieval`) declared via `pub mod X;`. Adding `pub mod graph;` to this file is required for the new module to be part of the crate and reachable by `cargo test --manifest-path engine/Cargo.toml graph::` (RESEARCH.md's own quoted test command).

---

## Shared Patterns

### Typed `Result<T, String>` + `.map_err(|e| format!("context: {e}"))`
**Source:** `engine/src/db/mod.rs` lines 20-30, and consistently used in RESEARCH.md's own proven `bridge_batch`/`traverse_stub` snippets.
**Apply to:** All new `graph::` functions — this already matches house convention, no adaptation needed.

### Module doc-comment + `pub mod` submodule registration + `pub use` re-export
**Source:** `engine/src/retrieval/mod.rs` lines 1-22.
**Apply to:** `engine/src/graph/mod.rs` — register `bridge` as a submodule, re-export `traverse`/`traverse_stub` as the public surface.

### Fixture-builder-function + `#[test]` per-case test file
**Source:** `engine/src/retrieval/tests.rs`.
**Apply to:** `engine/src/graph/tests.rs` — one fixture builder, one `#[test]` per RESEARCH.md-proven scenario (bridge round-trip, single-hop, multi-hop, relation-type filter).

### Crate-root module registration
**Source:** `engine/src/lib.rs` (all existing top-level `pub mod` lines).
**Apply to:** Add `pub mod graph;` alongside the existing 6 entries, alphabetically positioned between `generation` and `prompt`.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| Full `entities`/`edges` extraction pipeline, `ContextAssemblyStrategy` trait, `QueryGraph` gRPC redesign | service/controller | request-response, event-driven | Explicitly out of this spike phase's scope per the SPIDR narrowing — deferred to Phase 04.1. RESEARCH.md's `## Architecture Patterns` → `Recommended Project Structure` lists `cypher_config.rs` and `extraction.rs` as part of the eventual module, but these are 04.1 deliverables, not this phase's. Do not pattern-map them here; re-run pattern mapping for 04.1 against whatever this phase actually commits. |

## Metadata

**Analog search scope:** `engine/src/` (all `.rs` files), `engine/Cargo.toml`
**Files scanned:** `engine/src/lib.rs`, `engine/src/retrieval/mod.rs`, `engine/src/retrieval/tests.rs`, `engine/src/db/mod.rs`, `engine/src/generation/mod.rs` (module-seam reference), `engine/Cargo.toml`
**Pattern extraction date:** 2026-08-06
</content>
