---
status: complete
phase: 05-state-machine-workflow-events
source: [05-VERIFICATION.md]
started: 2026-08-18T10:06:50Z
updated: 2026-08-18T23:30:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Live OpenRouter end-to-end SSE run

expected: node_started/node_completed for all five nodes, one answer_chunk, one final_answer, one workflow_completed, no stream_error; the answer is grounded with real citations.
why_human: Every automated proof of the pipeline — including the decisive TestRAGQueryCrossRuntime — substitutes an httptest mock for OpenRouter's /embeddings, /models, and /chat/completions. The one live-provider test in the repo (generation::tests::openrouter_structured_output_smoke) is `#[ignore]` and did not run. Real provider latency, streaming semantics, and structured-output conformance have never been exercised against this state machine.
result: issue
reported: "Error: \"LanceDB schema drift detected for nodes: expected [...19 fields ending in content_type...], found [...same 19 fields plus community_ids, summary, summary_vector, unsummarized_refs]\" — engine.exe exits with code 1 on startup, before the gateway or /rag/query could even be reached."
severity: blocker

### 2. Decide and apply the disposition of the WR-05 `x-lancet-*` trailer regression

expected: Either engine/src/main.rs::query_rag re-attaches x-lancet-session-id / x-lancet-correlation-id / x-lancet-error-kind to its Status errors, or gateway/main.go:771-783 and the doubles at gateway/main_test.go:1089-1241 are deleted. Not both left as-is.
why_human: This is a cross-runtime contract ownership decision, not a defect with one correct fix. The engine side was deliberately deleted with the inline remainder in af42b10; whether the D-1 status metadata contract from Phase 03 is still wanted is a product/architecture call.
result: pass
resolution: "User chose option 1 (restore emission). Reinstated a `d1_status` helper in engine/src/main.rs and wired it into query_rag's two pre-stream error paths (invalid session_id; QueryRequest::from_values validation failures), re-attaching x-lancet-session-id / x-lancet-correlation-id / x-lancet-error-kind to the returned Status. gateway/main.go:771-783 and its test doubles at gateway/main_test.go:1089-1241 left as-is (contract restored, not deleted). Verified: cargo build clean; full engine suite 280/280 passing; go build/vet clean; TestQueryRAGRealInvalidRequestAndDisconnect and TestRAGQuerySSEFirstFrame still pass. Not exercised live end-to-end (blocked by the same engine-startup issue as Test 1)."

### 3. Reconcile Phase 05 traceability bookkeeping

expected: 05-11-SUMMARY's GATE-01/GATE-02/GATE-03 are corrected (or added to 05-12-TRACEABILITY-ERRATA.md), and REQUIREMENTS.md ORCH-01 and ORCH-05 are checked.
why_human: Requires a human decision on whether GATE-* were intended as new requirement IDs or were transcription noise; a verifier cannot invent the intent.
result: pass
resolution: "User chose: GATE-01/GATE-02 are new requirement IDs. Added both to REQUIREMENTS.md under Orchestration & State (marked satisfied, Phase 05), with descriptions from 05-11-SUMMARY's D2/D3 coverage. GATE-03 had zero coverage backing it in 05-11-SUMMARY.md — removed from its requirements-completed list rather than inventing a definition. Checked ORCH-01 and ORCH-05 in REQUIREMENTS.md (both evidenced complete). Documented the full reconciliation in 05-12-TRACEABILITY-ERRATA.md §8."

### 4. Review the 15 judgment-tier prohibitions carried forward from plans 05-01 through 05-07

expected: Each prohibition listed in the 05-VERIFICATION.md Prohibitions section is explicitly accepted or rejected by a human.
why_human: None declares a `verification:` tier, so all 15 are judgment-tier per ADR-550 D4. The verifier's spot-verdicts in the report are NON-AUTHORITATIVE and must never be absorbed into a silent pass.
result: pass
resolution: "User accepted all 15 prohibitions as-is, including the two flagged non-authoritative spot-verdicts (#7 DB tests silently skip in default go test ./... run; #15 05-07's file-touch prohibition cannot be re-derived at HEAD since later plans legitimately modified those files). No rejections; no new gaps from this test."

## Summary

total: 4
passed: 3
issues: 1
pending: 0
skipped: 0
blocked: 0

## Gaps

- gap_id: G-05-1
  truth: "Engine starts cleanly and completes a live /rag/query with node_started/node_completed for all five nodes, one answer_chunk, one final_answer, one workflow_completed, no stream_error."
  status: failed
  reason: "User reported: Error: \"LanceDB schema drift detected for nodes: expected [...19 fields...], found [...19 fields plus community_ids, summary, summary_vector, unsummarized_refs]\" — engine.exe exits with code 1 on startup, before the gateway or /rag/query could even be reached."
  severity: blocker
  test: 1
  artifacts: []  # Filled by diagnosis
  missing:
    - "Second, independent blocker discovered while re-verifying: config/config.toml's generation_model was changed to \"nvidia/nemotron-3.5-lightning:free\" in commit f776296, which OpenRouter's /models list does not recognize (\"model metadata for 'nvidia/nemotron-3.5-lightning:free' not found in OpenRouter list\"). Confirmed pre-existing on main (reproduced via TestRAGQueryCrossRuntime / TestRAGQueryClientDisconnectCancelsRustWorkflow with the schema-drift fix stashed out). Both issues must be resolved before Test 1 can be attempted."
