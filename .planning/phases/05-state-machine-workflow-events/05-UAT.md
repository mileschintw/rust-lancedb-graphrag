---
status: diagnosed
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
  debug_session: ".planning/debug/g-05-1-engine-startup-blockers.md"
  root_cause: |
    Two independent root causes, both must be fixed before Test 1 can be attempted:

    BLOCKER A (engine won't start): engine/src/db/mod.rs::validate_schema (line
    161-174) does a strict fail-closed field-equality check with no migration
    path. Commit 2302f79 (2026-08-07, "feat(04.1-01): promote graph module and
    restructure graph schemas in LanceDB") removed community_ids, summary,
    summary_vector, unsummarized_refs from nodes_schema() (23 -> 19 fields),
    moving them onto the new entities_schema(). The local dev store at
    ./data/lancedb was created by a pre-2302f79 binary and was never
    regenerated, so it still has the wider 23-field schema on disk. This is
    stale local dev data, not REQUIREMENTS.md DATA-06/DATA-07 (still unchecked)
    arriving early — those fields were REMOVED from nodes on 2026-08-07, not
    added ahead of schedule. Only the nodes table is affected; the other 6
    tables (communities, documents, edges, entities, entity_edges,
    staged_documents_v2) already validate cleanly. Automated tests use
    isolated temp LanceDB paths so this is invisible to CI — it only surfaces
    against a long-lived, manually-run local dev instance.

    BLOCKER B (generation fails even once the engine starts): commit f776296
    (2026-08-18, today, single-line unreviewed chore commit) changed
    config/config.toml's [openrouter].generation_model from
    "openai/gpt-4o-mini" to "nvidia/nemotron-3.5-lightning:free" — confirmed
    via web search to be a REAL, currently-listed OpenRouter model (NVIDIA
    Nemotron 3.5 Lightning, released 2026-08-11), not invalid or misspelled.
    gateway/main_test.go's TestRAGQueryCrossRuntime and
    TestRAGQueryClientDisconnectCancelsRustWorkflow spawn the real engine
    binary and override OpenRouter endpoint URLs via env vars but never
    override generation_model, so the spawned engine reads the new model from
    ambient config.toml — while the tests' httptest mocks still hardcode a
    single canned /models entry for openai/gpt-4o-mini (5 call sites:
    main_test.go:2074,2111,2142,2397,3457). The "not found" error is test-double
    staleness, not an invalid model ID.

    RESOLVED post-diagnosis: queried OpenRouter's live /api/v1/models endpoint
    directly (no key needed for listing) for nvidia/nemotron-3.5-lightning:free's
    real supported_parameters — it does NOT include response_format,
    json_schema, or structured_outputs (only include_reasoning, max_tokens,
    reasoning, seed, temperature, tool_choice, tools, top_p). The engine's
    capability preflight (engine/src/generation/openrouter.rs:425-434) hard-requires
    one of the first three. So this model would ALSO fail live generation with
    a real API key — a third, now-confirmed failure mode beyond test-fixture
    staleness. User chose to switch generation_model to
    dots-studio/dots-3-note-preview:free instead (confirmed via the same live
    query to advertise both response_format and structured_outputs). Applied
    in config/config.toml (commit 989003b). gateway/main_test.go's 5 hardcoded
    openai/gpt-4o-mini mock call sites are unaffected by this switch (they were
    already stale relative to the prior nemotron value too) and still need a
    fix — either updated to the new model string or decoupled from ambient
    config.toml via a LANCET_OPENROUTER__GENERATION_MODEL env override (not
    currently in engine/src/main.rs's explicit override list at lines 601-670,
    would need to be added there for the override to be guaranteed to take
    effect per that code's own stated rationale for why the explicit list
    exists alongside the generic config::Environment source).
  artifacts:
    - path: "engine/src/db/mod.rs"
      issue: "validate_schema (161-174) has no migration path for the nodes table; nodes_schema() (19 fields) no longer matches the 23-field on-disk store left by pre-2302f79 local dev data."
    - path: "config/config.toml"
      issue: "RESOLVED — generation_model switched from nvidia/nemotron-3.5-lightning:free to dots-studio/dots-3-note-preview:free (commit 989003b) after confirming the former lacks structured-output support and the latter has it, via OpenRouter's live /api/v1/models. gateway/main_test.go's hardcoded mocks and config/config.example.toml (still openai/gpt-4o-mini) remain out of sync."
    - path: "gateway/main_test.go"
      issue: "Hardcodes openai/gpt-4o-mini in httptest /models mocks (lines 2074, 2111, 2142, 2397, 3457) and does not override LANCET_OPENROUTER__GENERATION_MODEL in the spawned engine's env (~line 2206), so it silently depends on ambient config.toml. Still needs a fix — the model value changed again (now dots-studio/dots-3-note-preview:free) so these mocks are stale regardless of which fix direction is chosen."
    - path: "engine/src/main.rs"
      issue: "Lines 601-670 maintain an explicit env-var override list (LANCET_OPENROUTER__EMBEDDING_ENDPOINT, MODEL_METADATA_ENDPOINT, CHAT_ENDPOINT, MAX_OUTPUT_TOKENS, etc.) alongside the generic config::Environment source, per the code's own comment about version-specific parsing reliability. generation_model is not in this explicit list — if the test-decoupling fix direction is chosen, it should be added here to guarantee LANCET_OPENROUTER__GENERATION_MODEL actually overrides config.toml."
  missing:
    - "Migrate or rebuild the local ./data/lancedb nodes table to the current 19-field schema (data-side fix), and re-seed/re-ingest so Test 1's retrieval still has real data to answer against."
    - "Decide whether validate_schema should stay strict-only or gain an explicit reconciliation path for known-safe column removals during future schema-restructure phases (code-side design decision, STATE.md currently records: fail startup on any LanceDB schema field drift)."
    - "Update gateway/main_test.go's 5 hardcoded openai/gpt-4o-mini mock call sites to match dots-studio/dots-3-note-preview:free, OR decouple the real-engine tests from ambient config.toml by adding generation_model to engine/src/main.rs's explicit env-override list and passing LANCET_OPENROUTER__GENERATION_MODEL in ragChildEnv (structurally prevents this exact class of break recurring on any future config.toml change)."
