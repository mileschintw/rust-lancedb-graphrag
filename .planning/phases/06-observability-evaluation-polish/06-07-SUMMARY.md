# Plan 06-07 Summary: Protobuf Additive Schema Growth, Notice Codes, and Workflow Metadata

## Overview
Plan 06-07 established the shared additive wire contract for the remainder of Phase 6 by extending `proto/lancet/v1/lancet.proto`, regenerating Rust and Go bindings in lockstep, enforcing a single typed notice constructor in the engine (`engine::workflow::notice`), updating the zero-evidence runner gates to compare typed enum values, exposing HTTP request edge flags on the gateway, and embedding the 10-field workflow metadata object in the SSE terminal event frame.

---

## 1. Pre-Edit Reproducibility Verification
Before making any edits, the untouched working tree verified exact reproducibility against pinned remote plugins:
1. `buf lint`: clean exit 0
2. `buf format --diff --exit-code`: clean exit 0
3. `buf generate`: clean exit 0
4. `git status --porcelain`: 0 modified files (working tree clean)

---

## 2. Checkpoint Decision (Task 0)
- **Mode**: YOLO / Non-Interactive Batch (`mode: "yolo"` in `.planning/config.json`).
- **Resume Signal**: `research-corrected` (recommended first option).
- **Decisions Recorded**:
  - Excluded tag 17 from enum definition; declared `reserved 17;` in `lancet.proto` because graph retrieval is never an independent retrieval path alongside dense and BM25 in the hybrid retrieval node.
  - Tag 18 declared as `NOTICE_CODE_GRAPH_ABLATION` for Phase 6 Plan 06-08 (`disable_graph_context`).
  - Contentless model notices/warnings mapped to `NOTICE_CODE_MODEL_NOTICE = 4` and `NOTICE_CODE_MODEL_WARNING = 5`.
  - ROADMAP SC4 token `RETRIEVAL_DEGRADED` mapped to path-specific codes `RETRIEVAL_DEGRADED_DENSE` (tag 11) and `RETRIEVAL_DEGRADED_BM25` (tag 16).

---

## 3. Published NoticeCode Enum Vocabulary

| Tag Number | Enum Identifier | Derived Wire String (`.code`) | Rationale / Emission Site |
|------------|-----------------|--------------------------------|---------------------------|
| 0 | `NOTICE_CODE_UNSPECIFIED` | `UNSPECIFIED` | Proto default / fallback |
| 1 | `NOTICE_CODE_NO_EVIDENCE` | `NO_EVIDENCE` | `engine/src/workflow/nodes/retrieve.rs` |
| 2 | `NOTICE_CODE_GRAPH_TIMEOUT` | `GRAPH_TIMEOUT` | `engine/src/workflow/nodes/graph_context.rs` |
| 3 | `NOTICE_CODE_GRAPH_DEGRADED` | `GRAPH_DEGRADED` | `engine/src/workflow/nodes/graph_context.rs` |
| 4 | `NOTICE_CODE_MODEL_NOTICE` | `MODEL_NOTICE` | `engine/src/workflow/mod.rs` (`update_from_model_output`) |
| 5 | `NOTICE_CODE_MODEL_WARNING` | `MODEL_WARNING` | `engine/src/workflow/mod.rs` (`update_from_model_output`) |
| 10 | `NOTICE_CODE_GRAPH_UNAVAILABLE` | `GRAPH_UNAVAILABLE` | Plan 06-08 graph node unreachable / unconfigured |
| 11 | `NOTICE_CODE_RETRIEVAL_DEGRADED_DENSE` | `RETRIEVAL_DEGRADED_DENSE` | Plan 06-09 dense retrieval error (ROADMAP SC4) |
| 12 | `NOTICE_CODE_CITATION_REPAIRED` | `CITATION_REPAIRED` | Plan 06-11 citation reconciliation repair |
| 13 | `NOTICE_CODE_CITATION_DROPPED` | `CITATION_DROPPED` | Plan 06-11 hallucinated citation dropped |
| 14 | `NOTICE_CODE_MODEL_ONLY` | `MODEL_ONLY` | Plan 06-10 fallback to parametric model-only |
| 15 | `NOTICE_CODE_BASIS_RECONCILED` | `BASIS_RECONCILED` | Plan 06-10 answer basis reconciliation |
| 16 | `NOTICE_CODE_RETRIEVAL_DEGRADED_BM25` | `RETRIEVAL_DEGRADED_BM25` | Plan 06-09 BM25 index query degradation (ROADMAP SC4) |
| 17 | `reserved 17;` | N/A | Reserved: Unreachable graph retrieval in hybrid retrieval fusion |
| 18 | `NOTICE_CODE_GRAPH_ABLATION` | `GRAPH_ABLATION` | Plan 06-08 graph extraction disabled by edge flag |
| 20 | `NOTICE_CODE_INDEX_REBUILD_FAILED` | `INDEX_REBUILD_FAILED` | Reserved for Phase 6.1 (dynamic corpus mutation) |
| 21 | `NOTICE_CODE_INDEX_STALE` | `INDEX_STALE` | Reserved for Phase 6.1 (dynamic corpus mutation) |
| 22 | `NOTICE_CODE_INDEX_GENERATION_MISMATCH` | `INDEX_GENERATION_MISMATCH` | Reserved for Phase 6.1 (dynamic corpus mutation) |

---

## 4. Regeneration Commit (`464d568`)
Task 1 produced and committed exactly five modified files across proto definition, generated Rust bindings, generated Go bindings, and buf lockfiles:
1. `proto/lancet/v1/lancet.proto`
2. `engine/src/pb/lancet/v1/lancet.v1.rs`
3. `gateway/proto/lancet/v1/lancet.pb.go`
4. `engine/Cargo.lock`
5. `gateway/go.sum`

---

## 5. Workflow Metadata Wire Framing & Defaults
`WorkflowCompletedEvent.metadata` embeds the 10-field `WorkflowMetadata` struct:
1. `started_at_ms`: `int64`
2. `completed_at_ms`: `int64`
3. `reformulation_used`: `bool`
4. `vector_count`: `uint32`
5. `bm25_count`: `uint32`
6. `graph_node_count`: `uint32`
7. `graph_edge_count`: `uint32`
8. `prompt_tokens`: `uint32`
9. `completion_tokens`: `uint32`
10. `degraded_mode`: `bool`

Where the engine has not yet wired runtime population (to be implemented across plans 06-08 through 06-11), default zero values are emitted and mapped without fabricating measurements.

---

## 6. Test Target Distributions

### Rust (`scripts/engine-test-targets.sh`)
- `engine (lib)`: 271 tests (+5 new tests in `workflow_phase5.rs`)
- `engine (bin)`: 0 tests
- `inspect_lancedb (bin)`: 18 tests
- `seed_rag_fixture (bin)`: 0 tests
- `config_startup (test)`: 9 tests
- **TOTAL**: 298 tests (verified green)

### Go (`scripts/gateway-test-targets.sh`)
- `gateway`: 64 tests (+2 new tests in `main_test.go`)
- `gateway/db`: 7 tests
- `gateway/internal/sse`: 8 tests
- **TOTAL**: 79 tests (verified green)

---

## 7. Commits
- `464d568`: `feat(06-07): declare notice codes, edge request flags, and workflow metadata in proto`
- `f97d8c5`: `feat(06-07): introduce typed notice constructor, derive string code, and migrate gates`
- `a22f102`: `feat(06-07): expose edge flags on gateway, map typed notice code, and embed workflow metadata frame`
