---
phase: 05-state-machine-workflow-events
plan: 24
type: execute
status: completed
executed_at: "2026-08-18T03:58:00.000Z"
requirements:
  - ORCH-05
files_modified:
  - engine/src/retrieval/fusion.rs
  - engine/src/retrieval/mod.rs
  - engine/src/workflow/nodes/retrieve.rs
  - engine/src/retrieval/tests.rs
---

# Plan 05-24 Execution Summary: Close Resolved Cross-Variant RRF Contract

## Overview

Plan 05-24 (Wave 17) closed the resolved cross-variant RRF contract across reformulation variants with a deterministic two-pass architecture:
1. Retained `fuse_candidates` as the stable single-variant vector-plus-BM25 helper.
2. Introduced `fuse_cross_variant_candidates` as the only second-pass cross-variant fusion helper, with documented exact scoring (`sum(1.0 / (rrf_k + rank))`), finite validation guards, metadata retention from the highest inner fused score, and deterministic 4-tier tie-breaking.
3. Completely retired `fuse_variant_candidates` from definition, export, and call sites across the codebase.
4. Structured `RetrieveHybridNode` to execute single-variant `fuse_candidates` per admitted variant (dense on variant zero only, BM25 per variant) and merge the resulting per-variant fused candidate lists via `fuse_cross_variant_candidates`.
5. Updated existing pinning tests (`fusion_cross_variant_tracer`, `variant_zero_one_variant_matches_existing_scores`, `cross_variant_provenance_is_bounded`) to exercise the two-pass architecture and verify re-tagged variant indices and bounded provenance.
6. Registered `cross_variant_rrf_two_variant_exact_scores` (end-to-end RetrieveHybrid path tracer) and `cross_variant_rrf_tie_order_is_deterministic` (tie resolution and serialized stability).

## Key Changes

1. **`engine/src/retrieval/fusion.rs`**:
   - `fuse_candidates`: Single-pass vector + BM25 fusion with variant index 0.
   - `fuse_cross_variant_candidates`: Second-pass RRF merge with two-pass provenance re-tagging (`prov.variant_index = variant_index`), exact scoring, and deterministic tie ordering.
   - Removed `fuse_variant_candidates`.
2. **`engine/src/retrieval/mod.rs`**:
   - Re-exported `fuse_cross_variant_candidates` and removed `fuse_variant_candidates`.
3. **`engine/src/workflow/nodes/retrieve.rs`**:
   - Implemented `RetrieveHybridNode::execute` with per-variant `for (variant_index, variant) in ctx.variants.iter().enumerate()` loop calling `fuse_candidates` once per variant (variant 0 dense branch), followed by `fuse_cross_variant_candidates`.
4. **`engine/src/retrieval/tests.rs`**:
   - Updated existing fusion tests to use two-pass helpers.
   - Added `cross_variant_rrf_two_variant_exact_scores` verifying exact formula `1/61 + 1/62`.
   - Added `cross_variant_rrf_tie_order_is_deterministic` asserting deterministic ordering across repeated runs and serialization.

## Verification & Determinism

- **Task 1 Verification**:
  - `cross_variant_rrf_two_variant_exact_scores`, `fusion_cross_variant_tracer`, `variant_zero_one_variant_matches_existing_scores`, and `cross_variant_provenance_is_bounded` passed.
- **Task 2 Verification**:
  - Source guards verified: exactly one `fuse_candidates` call inside the variant loop, `fuse_cross_variant_candidates` called after the loop, variant-0 dense branch present, no `flat_map`/`flatten` request-level flattening, and zero occurrences of `fuse_variant_candidates`.
  - `cross_variant_rrf_tie_order_is_deterministic` and all 126 library tests passed.
