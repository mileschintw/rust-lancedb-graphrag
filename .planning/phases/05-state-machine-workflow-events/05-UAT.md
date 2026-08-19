---
status: complete
phase: 05-state-machine-workflow-events
source: [05-VERIFICATION.md]
started: 2026-08-18T10:06:50Z
updated: 2026-08-19T06:10:00Z
regapped: 2026-08-19T03:20:00Z  # merged fresh human_verification items from the 05-VERIFICATION.md re-verification at HEAD 721485c; Tests 2-4 and their recorded human resolutions preserved verbatim
---

## Current Test

[testing complete]

## Tests

### 1. Live OpenRouter end-to-end SSE run

expected: node_started/node_completed for all five nodes, one answer_chunk, one final_answer, one workflow_completed, no stream_error; the answer is grounded with real citations.
why_human: Every automated proof of the pipeline — including the decisive TestRAGQueryCrossRuntime — substitutes an httptest mock for OpenRouter's /embeddings, /models, and /chat/completions. The one live-provider test in the repo (generation::tests::openrouter_structured_output_smoke) is `#[ignore]` and did not run. Real provider latency, streaming semantics, and structured-output conformance have never been exercised against this state machine.
result: issue
reported: "GenerateAnswer failed: model capabilities response exceeds maximum body limit of 262144 bytes; workflow_completed success: false"
severity: blocker
prior_result: issue
prior_reported: "Error: \"LanceDB schema drift detected for nodes: expected [...19 fields ending in content_type...], found [...same 19 fields plus community_ids, summary, summary_vector, unsummarized_refs]\" — engine.exe exits with code 1 on startup, before the gateway or /rag/query could even be reached."
prior_severity: blocker
unblocked_by: |
  Both G-05-1 root causes are now closed in code (plans 05-25 and 05-26, commits 967a897 and c815af1):
    - Blocker A: validate_schema carries an actionable remediation clause (engine/src/db/mod.rs:167-172);
      the stale local store was rebuilt. Verified empirically this pass — inspect_lancedb.exe reaches and
      passes DatabaseManager::open_and_validate against ./data/lancedb. data/lancedb.pre-05-25.bak preserved.
    - Blocker B: explicit LANCET_OPENROUTER__GENERATION_MODEL / __EMBEDDING_MODEL overrides added
      (engine/src/main.rs:661-668); gateway real-engine tests no longer read ambient config.toml for the model.
  Closing the blockers UNBLOCKS this test; it does not constitute it. The run still needs a real
  OPENROUTER_API_KEY and a human observer.
added_risk: |
  Per 05-VERIFICATION.md WARN-NEW-01: after 05-26 the real-engine tests pin openai/gpt-4o-mini while
  production ships dots-studio/dots-3-note-preview:free, so the structured-output capability preflight
  at engine/src/generation/openrouter.rs:425-434 is now exercised by NO automated test. This makes the
  live run more necessary, not less.

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

### 5. Restore Postgres and run the 11 TEST_DATABASE_URL-gated tests

expected: All 11 PASS — `TestWorkflowCheckpointPersistence`, `TestWorkflowCheckpointCancellationAtomicity`, `TestWorkflowCheckpointPendingDrainAndPersistence`, `TestEmbeddingFailureRestartConvergesAcrossRuntime`, plus the 7 gateway/db document/reconciliation-intent tests.
command: |
  docker compose up -d postgres
  cd gateway && TEST_DATABASE_URL=postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable go test . ./db -count=1
why_human: These 11 tests are TEST_DATABASE_URL-gated and SKIPPED in the 2026-08-19 regression-gate run (Docker Desktop not running; nothing listening on 127.0.0.1:5432). SC4's persistence half — FIFO drain ordering (primary -> overflow -> pending) and cancellation atomicity — is a state-transition invariant. The presence of InsertWorkflowCheckpoint (gateway/checkpoint_sink.go:106-115) and RetainPending (main.go:802) proves the code is wired, not that the ordering invariant holds. The prior verification counted these as PASS against a container that is no longer up; that evidence is not reproducible at HEAD.
result: pass
resolution: "All 11 TEST_DATABASE_URL-gated tests ran and passed against local Postgres (TestWorkflowCheckpointPersistence, TestWorkflowCheckpointCancellationAtomicity, TestWorkflowCheckpointPendingDrainAndPersistence, TestEmbeddingFailureRestartConvergesAcrossRuntime, and 7 gateway/db tests)."

### 6. Decide the disposition of CR-01 + WR-12 (coupled cancellation-path defects in engine/src/workflow/runner.rs)

expected: Either the `capacity()` fast path at runner.rs:90-98 is deleted in favour of the unconditional biased select (the review's recommended fix, with the failure event emitted before `cancel.cancel()`), or the current behaviour is explicitly accepted with the buffer-depth invariant recorded as a load-bearing assumption.
why_human: Not a gap today. The verifier re-derived the arithmetic from source at HEAD — the sink channel is per-request `mpsc::channel(100)` (main.rs:1861) with no production `.clone()`, and a workflow emits at most ~19 events (~30 with every node retried), so `capacity()` never reaches 0, the biased arm is never entered, and SC3 is not compromised. But that guard is an emergent property of a size constant, not an enforced invariant. It becomes live if per-token streaming AnswerChunks are added (planned 999.x), the 100-slot buffer is reduced, or the sink is cloned/shared. This is a design-debt acceptance decision, not a defect with one correct fix.
result: pass
resolution: "User accepted Option 1: current behaviour accepted with the buffer-depth invariant (mpsc::channel(100) vs ~19 events) recorded as a load-bearing assumption."

## Summary

total: 6
passed: 5
issues: 1
pending: 0
skipped: 0
blocked: 0

## Gaps

- gap_id: G-05-1
  truth: "Engine starts cleanly and completes a live /rag/query with node_started/node_completed for all five nodes, one answer_chunk, one final_answer, one workflow_completed, no stream_error."
  status: failed
  reason: "User reported: GenerateAnswer failed: model capabilities response exceeds maximum body limit of 262144 bytes; workflow_completed success: false"
  severity: blocker
  test: 1
  debug_session: ".planning/debug/g-05-1-engine-startup-blockers.md"
  root_cause: |
    Live OpenRouter /api/v1/models response body exceeds MAX_PROVIDER_RESPONSE_BODY_BYTES (262,144 bytes / 256 KB) in engine/src/generation/openrouter.rs:387-401 via read_body_limited, causing GenerateAnswer capability check to fail on live runs.
  artifacts:
    - path: "engine/src/generation/openrouter.rs"
      issue: "model capability preflight uses read_body_limited with 256KB ceiling; OpenRouter full models list is larger than 256KB"
  missing:
    - "Increase body limit for models metadata endpoint or stream/filter OpenRouter models response"

