# Phase 03 Plan 06 Execution Summary

## Plan Objective

Close the prompt and provider grounding-integrity blockers in the RAG-02 query path with one fail-closed evidence-to-validated-output path per D-17, D-22, D-23, D-28, D-29, D-31, and D-35 through D-39.

## Key Changes

1. **Hardened Prompt Boundary & Single-Boundary Encoding (`engine/src/prompt.rs`)**:
   - Implemented `EncodedEvidence` and `encode_evidence_block` to entity-escape all corpus-controlled metadata fields (`title`, `section_path`, `provenance`, `content_type`, and `text`), preventing raw tag forgery, attribute escaping, or instruction injection from breaking out of prompt boundaries (D-35, D-36, D-37).
   - Preserved raw internal `EvidenceBlock` metadata for downstream identity resolution and projection in Plan 03-09.
   - Updated `pack_evidence_prompt` to return `Result<PackedEvidence, PromptAssemblyError>`. Counted the first block against the allowed evidence token budget; if an over-budget first block or no evidence block fits, prompt assembly returns `PromptAssemblyError::NoEvidenceFits` fail-closed (D-23, D-39).
   - Added `bounded_unicode_excerpt` to guarantee Unicode scalar value iteration and prevent multibyte character splitting with an explicit truncation flag.

2. **Strict Deserialization & Grounding Validation (`engine/src/generation/mod.rs`)**:
   - Enforced `#[serde(deny_unknown_fields)]` on `ModelOutput` and `ModelUsage` (D-17).
   - Implemented `ModelOutput::validate_grounding(&self, packed_evidence: &[EvidenceBlock])`:
     - Rejects empty/blank answer text.
     - Rejects duplicate or unknown `cited_evidence_ids`.
     - Extracts inline answer markers (e.g. `[1]`) and validates exact set equality between cited IDs and inline markers.
     - Rejects unknown inline markers or mismatched ID sets before response assembly (D-22, D-28).

3. **Strict OpenRouter Contract & Finish Reason Enforcement (`engine/src/generation/openrouter.rs`)**:
   - Updated `OpenRouterChatPayload` to send `response_format` type `json_schema` with `strict: true`, explicit required properties, and `additionalProperties: false` at object boundaries.
   - Enforced `max_completion_tokens` parameter.
   - Added `finish_reason` validation on `ChatChoice`: non-`stop` (e.g. `length`, `content_filter`, missing) return a `GenerationError` fail-closed.
   - Removed silent retention/filtering of invalid citation IDs, propagating grounding validation errors without repair attempt per the D-24 repair deferral (D-24, D-29, D-31).

4. **Service Integration (`engine/src/main.rs`)**:
   - Updated `LancetServiceImpl::query_rag` to propagate prompt assembly and grounding validation errors through gRPC status codes before `QueryRagResponse` construction.

5. **Focused Regression Tests (`engine/src/generation/tests.rs`)**:
   - `adversarial_evidence_fields_cannot_forge_prompt_boundary`: Proves title, section path, provenance, content type, and text payloads with quotes, delimiters, mixed-case tags, and instructions round-trip purely as data inside exactly one engine-owned block structure and retain `suspicious = true`.
   - `prompt_rejects_over_budget_first_block_and_unicode_excerpt`: Verifies typed error on over-budget first block and multi-byte UTF-8 character boundary safety.
   - `model_output_marker_identity_validation`: Covers empty answer, unknown ID, duplicate ID, marker mismatch, and unknown JSON field rejections.
   - `openrouter_json_schema_and_finish_reason_contract`: Verifies strict JSON Schema payload generation and non-stop `finish_reason` failure handling.
   - `query_rag_happy_path_service`: Verified end-to-end service integration.

## Verification Results

Executed focused automated verification command:
- `adversarial_evidence_fields_cannot_forge_prompt_boundary`: PASSED
- `prompt_rejects_over_budget_first_block_and_unicode_excerpt`: PASSED
- `model_output_marker_identity_validation`: PASSED
- `openrouter_json_schema_and_finish_reason_contract`: PASSED
- `query_rag_happy_path_service`: PASSED

Full engine workspace test suite (`cargo test --manifest-path engine/Cargo.toml`):
- 15/15 lib tests PASSED
- 50/50 main integration tests PASSED
- 18/18 inspect_lancedb tests PASSED
- 5/5 config_startup tests PASSED

## Self-Check: PASSED
