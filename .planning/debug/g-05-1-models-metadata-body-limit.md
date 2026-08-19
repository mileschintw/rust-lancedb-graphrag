---
status: diagnosed
trigger: "G-05-1: Live OpenRouter end-to-end SSE run fails at GenerateAnswer with 'model capabilities response exceeds maximum body limit of 262144 bytes'."
created: 2026-08-19T06:15:00Z
updated: 2026-08-19T06:15:00Z
---

## Current Focus

hypothesis: "CONFIRMED. engine/src/generation/openrouter.rs:387-401 fetches the full model catalog from OpenRouter /api/v1/models and reads the body with crate::client::read_body_limited(). That function enforces MAX_PROVIDER_RESPONSE_BODY_BYTES = 256 * 1024 (262,144 bytes). Live OpenRouter /api/v1/models responses are multi-megabyte payloads listing all available models, which exceeds the 256KB limit and triggers BoundedBodyError::TooLarge -> GenerateAnswer node_failed."
test: "Inspect engine/src/client/mod.rs:15 (MAX_PROVIDER_RESPONSE_BODY_BYTES), engine/src/generation/openrouter.rs:386-402 (read_body_limited call in fetch_capabilities), and live OpenRouter models endpoint payload size."
expecting: "N/A — root cause confirmed."
next_action: "Handoff to gap planning."

## Symptoms

expected: |
  Start engine and gateway with real OPENROUTER_API_KEY, send POST /rag/query with Accept: text/event-stream.
  Observe node_started/node_completed for all five nodes, answer_chunk, final_answer, and workflow_completed{success:true}.
actual: |
  First 4 nodes (ReformulateQuery, ExtractGraphContext, RetrieveHybrid, AssemblePrompt) complete successfully.
  GenerateAnswer fails immediately with:
  event: node_failed
  data: {"error_kind":3,"error_message":"model capabilities response exceeds maximum body limit of 262144 bytes","node_name":"GenerateAnswer","retryable":false}
  event: workflow_completed
  data: {"error_kind":3,"error_message":"model capabilities response exceeds maximum body limit of 262144 bytes","notices":[],"success":false,"total_duration_ms":1569}
errors: |
  "model capabilities response exceeds maximum body limit of 262144 bytes"
reproduction: |
  Start engine with valid OPENROUTER_API_KEY, start gateway, execute curl /rag/query.
started: "2026-08-19 during Phase 05 UAT Test 1 live re-test."

## Root Cause

`engine/src/generation/openrouter.rs:387-401`:
`fetch_capabilities` queries OpenRouter's `/api/v1/models` endpoint (which returns the complete list of all models on OpenRouter) and delegates body reading to `crate::client::read_body_limited(response)`:

In `engine/src/client/mod.rs:15`:
`pub const MAX_PROVIDER_RESPONSE_BODY_BYTES: usize = 256 * 1024;` (256 KB).

While 256 KB is sufficient for embeddings and chat responses, OpenRouter's `/api/v1/models` catalog is significantly larger than 256 KB, causing `read_body_limited` to fail on live requests against OpenRouter.

## Suggested Fix Direction

1. Add a dedicated, larger body limit for model catalog queries (e.g. `MAX_MODELS_METADATA_BODY_BYTES = 10 * 1024 * 1024` / 10MB) or provide `read_body_limited_with_limit(response, max_bytes)` in `engine/src/client/mod.rs`.
2. Use this dedicated limit in `engine/src/generation/openrouter.rs` when querying `models_endpoint`.
