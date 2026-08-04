# Phase 03 Summary: Plan 03-07

## Objective
Close the core RAG-02 configuration blocker by threading one validated effective settings object from TOML to retrieval/evidence service state, provider configuration state, persistence identity input, prompt bounds, and `RetrievalSnapshot` per D-03 through D-05, D-23, D-25, D-27, D-30, D-32, D-33, D-39, D-46, and D-49.

## Key Changes
1. **Engine Retrieval Settings Validation** (`engine/src/retrieval/mod.rs`):
   - Added validation in `RetrievalSettings::validate` ensuring `rrf_k` is finite, non-fractional, and <= `i32::MAX as f64`.
   - Guaranteed `candidate_limit`, `final_limit`, `query_max_bytes`, `max_document_ids`, and `max_content_types` fit losslessly in 32-bit signed integer protobuf fields.

2. **Character-Bounded Citation Excerpts** (`engine/src/prompt.rs`):
   - Implemented `resolve_citations_with_max_chars(cited_ids, evidence, max_chars)` supporting configurable character truncation while delegating legacy calls with default 200.

3. **Effective RAG Settings & Service State Threading** (`engine/src/main.rs`):
   - Created `EffectiveRagSettings` encapsulating validated retrieval settings, token budgets, excerpt limits, provider models/endpoints, sampling parameters, timeouts, output limits, and an opaque service `index_generation` string (`gen-<uuid>`).
   - Updated `LancetServiceImpl` to hold `pub effective_settings: EffectiveRagSettings`.
   - Updated engine startup to validate TOML configuration before constructing database/resource handles and initialize `Bm25Index` using `effective_settings.retrieval.bm25` (incorporating D-46 boosts and D-49 BM25 parameters).
   - Modified `query_rag` to pass effective settings to query request building, dense/BM25 retrieval, prompt packing (`evidence_token_budget`), citation formatting (`citation_excerpt_max_chars`), and snapshot projection (`index_generation`, `embedding_model`).

4. **Integration & Unit Tests** (`engine/src/retrieval/tests.rs` & `engine/src/tests.rs`):
   - `retrieval_snapshot_values_are_lossless`: Validated integer limit bounds and non-fractional `rrf_k` assertion logic.
   - `configured_rag_settings_drive_service`: Verified that TOML settings flow into `RetrievalSnapshot`.
   - `configured_evidence_token_budget_is_exact`: Confirmed that `excerpt_max_chars` truncates citation excerpts cleanly.
   - `service_index_generation_is_opaque_and_stable`: Verified opaque `gen-<uuid>` generation stability across queries on a single service and uniqueness across service instances.
   - `invalid_effective_settings_rejected`: Ensured invalid settings are rejected at construction.

## Verification Results
- **Focused Unit & Service Tests**:
  - `retrieval_snapshot_values_are_lossless` PASSED
  - `configured_rag_settings_drive_service` PASSED
  - `configured_evidence_token_budget_is_exact` PASSED
  - `service_index_generation_is_opaque_and_stable` PASSED
- **Workspace Cargo Test Suite**: PASSED (All 55 engine unit/integration tests and config startup tests succeeded).

## Self-Check
- [x] Effective settings derived directly from TOML configuration and validated at startup
- [x] All 4 focused unit/integration tests written and passing
- [x] Full cargo test suite passing cleanly
- [x] Self-Check: PASSED
