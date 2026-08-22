# Phase 6 Plan 06-14: Citation Repair De-duplication Summary

## Executive Summary
Plan 06-14 closed verification gap SC5 by introducing first-occurrence de-duplication of citation IDs in both `GenerateAnswerNode`'s repair loop and `resolve_citations_with_max_chars` in `engine/src/prompt.rs`. Repeated markers (e.g. `[1]` appearing multiple times) and mixed-spelling markers mapping to the same evidence ID (e.g. `[ 7 ]` and `[7]`) now produce a single distinct citation ID in first-occurrence order, preventing downstream duplicate-ID rejections in `validate_grounding_with_limits` while preserving per-occurrence text span rewrites, repair notices, and zero-second-call invariants.

---

## Key Changes & Components

### 1. `GenerateAnswerNode` Repair De-duplication (`engine/src/workflow/nodes/generate.rs`)
- In `GenerateAnswerNode`'s repair handling:
  - `repaired_citations.push(id.clone())` is now guarded by `if !repaired_citations.contains(id)` for both `Resolution::Unchanged` and `Resolution::Repaired`.
  - All per-occurrence text edits (`edits.push((outcome.span, ...))`) and notices (`pending_notices.push(...)`) continue to be recorded for every occurrence.
  - Near-miss spans (e.g. `[ 7 ]`) emit `CITATION_REPAIRED` and rewrite the answer text even if an exact marker `[7]` also appears.

### 2. First-Occurrence Unique Structured Citations (`engine/src/prompt.rs`)
- In `resolve_citations_with_max_chars`:
  - Before constructing and appending a `StructuredCitation`, checks `!citations.iter().any(|c| c.marker_id == block.id || c.chunk_id == block.chunk_id)`.
  - Prevents fan-out of identical citations to wire responses when duplicate IDs are presented.

---

## Test Target Distribution & Invariants

| Target | Pre-Plan Count | Post-Plan Count | Delta |
|---|---|---|---|
| `engine (lib)` | 342 | 345 | +3 |
| `config_startup (test)` | 17 | 17 | 0 |
| `inspect_lancedb (bin)` | 18 | 18 | 0 |
| `engine (bin)` | 0 | 0 | 0 |
| `seed_rag_fixture (bin)` | 0 | 0 | 0 |
| **TOTAL** | **377** | **380** | **+3** |

### Verified Tests
- `citation_repair_enabled_repeated_marker_succeeds`
- `citation_repair_enabled_mixed_spelling_same_id_succeeds`
- `resolve_citations_with_max_chars_dedupes_duplicate_ids`
- `citation_repair_makes_no_additional_provider_call`
- All 7 Rust test target invariants in `scripts/engine-test-targets.sh` passed cleanly.
