---
phase: 05-state-machine-workflow-events
plan: 27
type: execute
status: completed
executed_at: "2026-08-19T06:21:00.000Z"
requirements:
  - ORCH-01
  - ORCH-02
gap_closure: true
gap_ids:
  - G-05-1
files_modified:
  - engine/src/client/mod.rs
  - engine/src/client/tests.rs
  - engine/src/generation/openrouter.rs
  - engine/src/generation/tests.rs
---

# Plan 05-27 Execution Summary: OpenRouter Model Metadata Body Ceiling Expansion

## Overview

Plan 05-27 resolved UAT gap G-05-1's live execution blocker where OpenRouter's live `/api/v1/models` endpoint returns a multi-megabyte model catalog that exceeded the default 256 KB `MAX_PROVIDER_RESPONSE_BODY_BYTES` limit. This previously caused `GenerateAnswer` capability preflight to fail with `"model capabilities response exceeds maximum body limit of 262144 bytes"`.

## Key Changes

1. **`engine/src/client/mod.rs`**:
   - Introduced `MAX_MODELS_METADATA_BODY_BYTES = 10 * 1024 * 1024` (10 MiB limit for model catalogs).
   - Added `pub async fn read_body_limited_with_limit(response, max_bytes)` checking both `Content-Length` header and chunk stream accumulation.
   - Refactored `read_body_limited` to delegate to `read_body_limited_with_limit(response, MAX_PROVIDER_RESPONSE_BODY_BYTES)`.

2. **`engine/src/client/tests.rs`**:
   - Added unit tests for `read_body_limited_with_limit` verifying that custom limits accept large payloads (512 KB) under `MAX_MODELS_METADATA_BODY_BYTES` while rejecting responses that exceed configured limits (`Content-Length` and chunked transfer encoding).

3. **`engine/src/generation/openrouter.rs`**:
   - Updated `fetch_and_validate_capabilities()` to read the `/api/v1/models` catalog via `read_body_limited_with_limit(response, MAX_MODELS_METADATA_BODY_BYTES)`.
   - Updated error messaging to cite `MAX_MODELS_METADATA_BODY_BYTES`.
   - Preserved tight 256 KB bounds on embeddings and chat completion endpoints.

4. **`engine/src/generation/tests.rs`**:
   - Updated `openrouter_metadata_rejects_oversized_streaming_body` test to verify rejection against `MAX_MODELS_METADATA_BODY_BYTES + 1`.

## Verification

- `cargo test --manifest-path engine/Cargo.toml --locked client::tests` passed (14 passed, 0 failed).
- `cargo test --manifest-path engine/Cargo.toml --locked generation::openrouter` passed (exit code 0).
- `cargo test --manifest-path engine/Cargo.toml --locked` passed all 126 lib tests, 18 inspect_lancedb tests, and 9 config_startup tests.
