---
status: diagnosed
trigger: "G-05-1: Engine fails to start / fails a live end-to-end RAG query for two independent reasons discovered during Phase 05 UAT."
created: 2026-08-18T23:35:00Z
updated: 2026-08-19T00:20:00Z
---

## Current Focus

hypothesis: "CONFIRMED both. BLOCKER A: stale local ./data/lancedb predates commit 2302f79 (04.1-01 restructure, 2026-08-07) which narrowed nodes_schema() by moving 4 fields to a new entities_schema(); strict fail-closed equality check in validate_schema() has no migration path for nodes. BLOCKER B: gateway/main_test.go hardcodes 'openai/gpt-4o-mini' in two httptest mocks with no generation_model env override for the spawned engine; commit f776296 changed config.toml's generation_model without updating those mocks, landing after the last regression-gate run. The new model ID itself is real (confirmed via web search) — the test failure is fixture staleness, not an invalid model."
test: "Read engine/src/db/mod.rs schema definitions and validate_schema(); git show on 2302f79 and 2621b0c; read seed_rag_fixture.rs; git show f776296; read gateway/main_test.go mock handlers and env injection around TestRAGQueryCrossRuntime; web search OpenRouter model listing; check regression-gate timing vs commit timestamps."
expecting: "N/A — investigation complete."
next_action: "Return ROOT CAUSE FOUND diagnosis to caller (goal: find_root_cause_only). Do not proceed to fix_and_verify."

## Symptoms

expected: |
  Start the engine and gateway with a real OPENROUTER_API_KEY, then curl /rag/query
  and watch the SSE frame sequence. Expect node_started/node_completed for all five
  nodes (ReformulateQuery, ExtractGraphContext, RetrieveHybrid, AssemblePrompt,
  GenerateAnswer), one answer_chunk, one final_answer, one workflow_completed, and
  no stream_error. The answer must be grounded with real citations.
actual: |
  Two independent blockers, either of which alone prevents the above from being observed:

  BLOCKER A (engine won't even start):
  Running `cargo run --manifest-path engine/Cargo.toml --bin engine` fails with:
  Error: "LanceDB schema drift detected for nodes: expected [...19 fields ending in
  content_type...], found [...same 19 fields plus community_ids, summary,
  summary_vector, unsummarized_refs]" — engine.exe exits with code 1 on startup,
  before the gateway or /rag/query could even be reached. The `expected` schema
  (what the running binary's code wants) is MISSING four columns that the `found`
  on-disk LanceDB table (./data/lancedb/nodes.lance) already HAS: community_ids,
  summary, summary_vector, unsummarized_refs. Note REQUIREMENTS.md DATA-06/DATA-07
  reference these exact fields as "Port for 999.1"/"Port for 999.4" — i.e. planned
  future work — yet the on-disk data already contains them, and the schema-drift
  check fails closed instead of tolerating extra nullable columns.

  BLOCKER B (even if the engine starts, generation fails):
  gateway integration tests that spawn the real engine binary (e.g.
  TestRAGQueryCrossRuntime, TestRAGQueryClientDisconnectCancelsRustWorkflow) fail
  with: "model metadata for 'nvidia/nemotron-3.5-lightning:free' not found in
  OpenRouter list". This is because config/config.toml's [openrouter]
  generation_model was changed from "openai/gpt-4o-mini" to
  "nvidia/nemotron-3.5-lightning:free" in commit f776296
  ("chore(05): update generation model to nvidia/nemotron-3.5-lightning in
  config.toml"), and that model ID does not resolve against OpenRouter's
  /models list (either it doesn't exist, is misspelled, or the mock/live models
  fixture used by tests doesn't recognize it).
errors: |
  Blocker A: `Error: "LanceDB schema drift detected for nodes: expected [...], found [...]"` (see full field lists above), engine.exe exit code 1.
  Blocker B: `node_failed` event with `error_kind=3`, `error_message="model metadata for 'nvidia/nemotron-3.5-lightning:free' not found in OpenRouter list"`, surfaced as a failing GenerateAnswer node in workflow_completed{success:false}.
reproduction: |
  Blocker A: `cargo run --manifest-path engine/Cargo.toml --bin engine` from a working tree with an existing ./data/lancedb directory that already has the newer nodes.lance schema (or any dev/test data dir populated by a schema-adding change).
  Blocker B: `cd gateway && go test ./... -count=1 -run 'TestRAGQueryCrossRuntime|TestRAGQueryClientDisconnectCancelsRustWorkflow'` (spawns the real engine binary, reads config/config.toml).
  Both were hit during Test 1 of the Phase 05 UAT session (.planning/phases/05-state-machine-workflow-events/05-UAT.md).
started: "Discovered 2026-08-18 during /gsd-verify-work 5 (Test 1). Blocker B's root commit (f776296) is the most recent commit in the repo, made today. Blocker A's timing relative to schema changes is unknown."

## Eliminated

- hypothesis: "BLOCKER A: on-disk nodes.lance schema drift is caused by DATA-06/DATA-07 future work outrunning the code (code stale relative to on-disk data)."
  evidence: "REQUIREMENTS.md DATA-06/DATA-07 are unchecked `[ ]` (not implemented) and no current code path writes community_ids/summary/summary_vector/unsummarized_refs onto the `nodes` table. git history shows the OPPOSITE direction: these 4 fields were REMOVED from nodes_schema() by commit 2302f79 (2026-08-07, 04.1-01 restructure) and moved onto the new entities_schema(). The on-disk data is stale/left over from BEFORE that commit, not ahead of it."
  timestamp: 2026-08-18T23:40:00Z
- hypothesis: "BLOCKER B: nvidia/nemotron-3.5-lightning:free is a fake/misspelled/nonexistent OpenRouter model ID."
  evidence: "Web search confirms nvidia/nemotron-3.5-lightning:free is a real OpenRouter-listed model (30B MoE, 3B active params, released 2026-08-11, has a free tier) — https://openrouter.ai/nvidia/nemotron-3.5-lightning:free. The 'not found' error in the reproduction steps comes from a Go httptest mock with a hardcoded canned /models response, not from OpenRouter's real catalog."
  timestamp: 2026-08-18T23:55:00Z

## Evidence

- timestamp: 2026-08-18T23:38:00Z
  checked: "engine/src/db/mod.rs nodes_schema()/validate_schema()/table_schemas()"
  found: "nodes_schema() (lines 194-216) currently declares exactly 19 fields ending in content_type. validate_schema() (line 161-174) does a strict `actual.fields() != expected.fields()` equality check and returns Err with the exact 'LanceDB schema drift detected for {name}: expected {...}, found {...}' message format seen in the bug report. initialize_tables() only has a special-cased additive-column migration for the legacy `staged_documents_v2` table (adding a `generation` column) — there is no equivalent migration path for `nodes`."
  implication: "Any existing on-disk `nodes` table with a different field set than the current 19-field nodes_schema() will hard-fail startup with no automatic reconciliation, by design (STATE.md decision '[Phase 02-03]: Fail startup on any LanceDB schema field drift.')."
- timestamp: 2026-08-18T23:41:00Z
  checked: "git show 2302f79 -- engine/src/db/mod.rs (commit '04.1-01: promote graph module and restructure graph schemas in LanceDB', 2026-08-07)"
  found: "This commit's diff removes exactly 4 fields from nodes_schema() in this order: community_ids, summary, summary_vector, unsummarized_refs (immediately after content_type) and creates a NEW entities_schema() that gains community_ids/summary/summary_vector/unsummarized_refs (reordered) plus entity-specific fields. table_schemas() grows from 5 to 7 entries (adds communities, entities, entity_edges)."
  implication: "The exact 4 extra fields reported in Blocker A's 'found' schema (community_ids, summary, summary_vector, unsummarized_refs), in the exact order reported (appended right after content_type), match precisely what nodes_schema() looked like BEFORE commit 2302f79. This is definitive: the on-disk ./data/lancedb/nodes.lance table was created by an engine binary built from code older than 2302f79 (2026-08-07), i.e. it predates the Phase 04.1-01 entity-table restructure by at least 11 days relative to today's UAT (2026-08-18)."
- timestamp: 2026-08-18T23:42:00Z
  checked: "git show 2621b0c -- engine/src/db/mod.rs (commit '02-03: initialize LanceDB schemas', original schema-creation commit)"
  found: "The original nodes_schema() from Phase 02-03 already included community_ids, summary, summary_vector, unsummarized_refs directly on the nodes table (in that exact order after content_type) — these were NOT added later; they were part of the schema from the very first commit that created it, and stayed there until 2302f79 moved them off nodes and onto the new entities table 04.1-01."
  implication: "Confirms the on-disk stale nodes.lance table could have existed anywhere from Phase 02 through immediately before 2302f79 landed (2026-08-07) — it is simply old local dev/manual-testing data at a fixed default path (./data/lancedb, config.toml's lancedb_path) that nobody deleted after the 04.1-01 schema restructure. Automated tests are unaffected because they use isolated temp LanceDB paths (t.TempDir()-based paths in gateway tests; per-test tmp paths in engine tests) — this class of bug can only surface via a persistent, manually-run local dev instance, which is exactly how UAT Test 1 hit it."
- timestamp: 2026-08-18T23:43:00Z
  checked: "engine/src/bin/seed_rag_fixture.rs"
  found: "Reads schema dynamically off the already-created nodes table (node.schema().await?) rather than hardcoding field lists, and only ever supplies values for the current 19-field nodes_schema(). Never writes community_ids/summary/summary_vector/unsummarized_refs onto nodes — those 4 fields are only ever written to the entities table in this seeder."
  implication: "Rules out the seeder as a current source of drift; it is schema-current and cannot recreate Blocker A's symptom against a freshly-initialized store. Confirms the stale on-disk table must predate 2302f79."
- timestamp: 2026-08-18T23:39:00Z
  checked: ".gitignore for data/lancedb and current worktree filesystem"
  found: ".gitignore excludes lancedb/ and .lancedb/ (and two Phase-02-specific verify/preclean dirs) but is not itself evidence of when a given local instance was created. This fresh worktree has no ./data/lancedb directory at all (`ls data/lancedb` -> No such file or directory)."
  implication: "The failure is dependent on pre-existing local/manual dev state (a long-lived engine data directory a developer has been running against since before 2026-08-07), not something reproducible from a clean checkout — consistent with why it was first caught during manual UAT rather than in CI/automated tests."
- timestamp: 2026-08-18T23:48:00Z
  checked: "git show f776296 -- config/config.toml"
  found: "Single-line chore commit (2026-08-18 04:51:03 -0700) changes [openrouter].generation_model from 'openai/gpt-4o-mini' to 'nvidia/nemotron-3.5-lightning:free'. No accompanying PLAN/CONTEXT/ADR/commit-body rationale found anywhere in .planning/ or git log --grep for 'nemotron' or 'generation_model' (only self-match). config/config.example.toml was NOT updated to match (still says openai/gpt-4o-mini), and no test double was updated in the same commit (commit touches only 1 file, 1 line)."
  implication: "This was an isolated, unreviewed config edit with no supporting design record — a config drift risk regardless of whether the target model is valid."
- timestamp: 2026-08-18T23:52:00Z
  checked: "engine/src/generation/openrouter.rs lines 403-423 (model capability preflight)"
  found: "Engine calls GET {models_endpoint}, deserializes the response, and does `models_resp.data.into_iter().find(|m| m.id == self.config.model)` — if no entry's `id` matches self.config.model (== config.toml's generation_model, read from the live/mocked endpoint at request time), it returns GenerationError::new(SupportedParameters, \"model metadata for '{model}' not found in OpenRouter list\")."
  implication: "This is a live existence+capability check against whatever /models endpoint the engine is pointed at — it is a legitimate strict check, not itself buggy. The question is only ever what the /models endpoint returns, and whether that matches config.toml's generation_model."
- timestamp: 2026-08-18T23:53:00Z
  checked: "gateway/main_test.go TestRAGQueryCrossRuntime (mock httptest server, lines ~2065-2157) and its env injection for the spawned engine subprocess (lines 2206-2213)"
  found: "The mock's /api/v1/models handler unconditionally returns a single hardcoded entry `{\"id\": \"openai/gpt-4o-mini\", \"supported_parameters\": [...]}` (line 2074) regardless of what the engine actually requests. The spawned engine's env only overrides LANCET_OPENROUTER__EMBEDDING_ENDPOINT / MODEL_METADATA_ENDPOINT / CHAT_ENDPOINT (i.e. where to send requests) — there is NO LANCET_OPENROUTER__GENERATION_MODEL override, so the engine subprocess reads generation_model from the ambient config/config.toml on disk. The chat-completion mock handler also hardcodes an assertion `request.Model != \"openai/gpt-4o-mini\"` (line 2111) and a canned response `\"model\": \"openai/gpt-4o-mini\"` (line 2142). A second occurrence of the same hardcoded 'openai/gpt-4o-mini' /models fixture exists at line 3457, inside TestRAGQueryClientDisconnectCancelsRustWorkflow's own mock."
  implication: "These two tests are tightly (implicitly) coupled to config/config.toml's generation_model value via the ambient config file, with zero override mechanism and zero assertion informing the reader why. Any change to config.toml's generation_model that isn't mirrored into these two hardcoded mock fixtures breaks both tests deterministically, independent of whether the new model is real."
- timestamp: 2026-08-18T23:56:00Z
  checked: "web search: OpenRouter nvidia/nemotron-3.5-lightning:free listing"
  found: "https://openrouter.ai/nvidia/nemotron-3.5-lightning:free — a real, currently-listed OpenRouter model (NVIDIA Nemotron 3.5 Lightning, 30B MoE / 3B active params, released 2026-08-11, has a free tier, 1M token context). It postdates my training cutoff, confirming it is not a hallucinated/misspelled ID."
  implication: "Blocker B's 'not found in OpenRouter list' error, AS REPRODUCED via the Go test suite, is a test-double staleness bug (mock fixture not updated to match config.toml), not evidence the model ID itself is invalid. Whether a genuine live /rag/query run (real OPENROUTER_API_KEY, real /models endpoint) would succeed with this model is a separate, not-yet-directly-observed question — Test 1 never reached GenerateAnswer live because Blocker A stopped the engine from starting at all. The model's structured-output/json_schema capability support (required by the capability preflight at openrouter.rs:425-434) is also unconfirmed from search results alone."
- timestamp: 2026-08-18T23:58:00Z
  checked: "git log timestamps: c8890c3 (gateway/main_test.go last touched, 2026-08-17 23:05, Phase 05-11) vs f776296 (config.toml change, 2026-08-18 04:51) vs STATE.md's 'Phase 05 post-execution gates run (2026-08-18)' regression-gate entry"
  found: "gateway/main_test.go's TestRAGQueryCrossRuntime/TestRAGQueryClientDisconnectCancelsRustWorkflow mocks were last written ~6 hours BEFORE f776296 landed, when config.toml still said openai/gpt-4o-mini (consistent/passing at that time). f776296 is the single most recent commit in the whole repo. STATE.md's regression-gate pass record predates it and does not mention it. TestRAGQueryCrossRuntime has no t.Skip/env gate (unlike the TEST_DATABASE_URL-gated DB tests) so it runs under plain `go test ./...`."
  implication: "f776296 was never covered by a regression-gate run — it is a small, single-line, ungated 'chore' commit made after the last full gate pass, which is exactly why the break wasn't caught before UAT."

- timestamp: 2026-08-19T00:10:00Z
  checked: "engine/src/db/mod.rs table_schemas() ordering (line 296-306) plus initialize_tables()'s `?`-propagating loop (line 74-107)"
  found: "table_schemas() iterates in fixed order: communities, documents, edges, entities, entity_edges, nodes, staged_documents_v2. initialize_tables() calls validate_schema per table inside a loop using `?`, so it returns on the FIRST failure. The reported error names only `nodes`."
  implication: "The user's on-disk store's communities/documents/edges/entities/entity_edges tables already validate cleanly against current schemas — only `nodes` has drifted. This narrows the viable fix to a targeted nodes-table migration/rebuild rather than wiping the whole ./data/lancedb store, and confirms staged_documents_v2 (last in the loop, never reached) has unknown validation status but has an existing precedent migration path (the additive `generation` column upgrade already in initialize_tables lines 83-97)."
- timestamp: 2026-08-19T00:12:00Z
  checked: "engine/src/main.rs default_generation_model()/OpenRouterSettings::default() (lines 99-104, 432-442)"
  found: "Both the serde default-value function and the Default impl hardcode generation_model = \"openai/gpt-4o-mini\" as the code-level fallback used when config.toml omits the field. config/config.example.toml:78 also still says openai/gpt-4o-mini (not updated by f776296)."
  implication: "openai/gpt-4o-mini is the only model value baked into the codebase's own defaults/examples/tests; nvidia/nemotron-3.5-lightning:free exists nowhere except config/config.toml's live override. This is a config-only change with no code-level counterpart, and config.example.toml is now inconsistent with config.toml (documentation drift, independent of whether the model change itself is desired)."
- timestamp: 2026-08-19T00:14:00Z
  checked: "Full enumeration of hardcoded 'openai/gpt-4o-mini' occurrences in gateway/main_test.go relevant to the two failing tests"
  found: "Line 2074 (TestRAGQueryCrossRuntime /models mock canned id), line 2111 (chat-completion request assertion), line 2142 (chat-completion canned response model field), line 2397 (post-hoc assertion on state.chatModel), line 3457 (TestRAGQueryClientDisconnectCancelsRustWorkflow's own separate /models mock canned id). Five total hardcoded occurrences across the two tests."
  implication: "A fixture-update fix direction must touch all five call sites (or all instances of a shared helper, if one is introduced) plus the equivalent block(s) inside TestRAGQueryClientDisconnectCancelsRustWorkflow; a decoupling fix (env override for generation_model in ragChildEnv at line 2206) avoids touching any of them by making the tests independent of config.toml's value entirely."
- timestamp: 2026-08-19T00:16:00Z
  checked: "Web search for nvidia/nemotron-3.5-lightning:free's supported_parameters (response_format/json_schema/structured_outputs) as returned by OpenRouter's live /api/v1/models endpoint"
  found: "Multiple searches returned marketing/review coverage confirming the model 'supports structured outputs' in a general sense (tool calls, JSON, agentic workflows) but none surfaced the literal supported_parameters array value from the /api/v1/models JSON payload itself — that field is not published in indexed blog/docs content, only in the live API response."
  implication: "UNRESOLVED BLIND SPOT: cannot confirm from static research alone whether this model would pass the engine's capability preflight (openrouter.rs:425-434, which requires response_format/json_schema/structured_outputs in supported_parameters) against the REAL OpenRouter endpoint. This is answerable in ~10 seconds by whoever has a live OPENROUTER_API_KEY (curl https://openrouter.ai/api/v1/models | jq of this one entry) but was not directly observed in this investigation. The two fix directions for Blocker B are conditioned on this unknown and are presented as a fork, not a single recommendation."

## Resolution

root_cause:
  - "BLOCKER A: engine/src/db/mod.rs::open_and_validate / initialize_tables performs a fail-closed, exact-field-equality LanceDB schema check (validate_schema, line 166: `actual.fields() != expected.fields()`) with no migration path for the `nodes` table. Commit 2302f79 (2026-08-07, Phase 04.1-01 graph-schema restructure) removed 4 fields (community_ids, summary, summary_vector, unsummarized_refs) from nodes_schema() and moved them onto a new entities_schema(), narrowing the code's expected nodes schema from 23 to 19 fields. The default local dev LanceDB store at ./data/lancedb (config.toml's engine.lancedb_path) was created by an engine binary built before that commit and was never regenerated/migrated afterward, so it still has the wider pre-04.1-01 schema. On next startup the strict equality check fails closed on the 4 extra (now-orphaned) columns, exiting with code 1 before the gateway/gRPC server ever starts."
  - "BLOCKER B: gateway/main_test.go's TestRAGQueryCrossRuntime and TestRAGQueryClientDisconnectCancelsRustWorkflow spawn the real engine binary against a httptest mock whose /api/v1/models handler hardcodes a single canned entry (id: openai/gpt-4o-mini) and whose chat-completion handler asserts/echoes the same hardcoded model string. These tests override the OpenRouter endpoint URLs via LANCET_OPENROUTER__*_ENDPOINT env vars for the spawned engine subprocess but never override generation_model, so the engine reads it from the ambient config/config.toml. Commit f776296 (2026-08-18, today, single-line unreviewed 'chore' commit with no design record) changed config.toml's [openrouter].generation_model from openai/gpt-4o-mini to nvidia/nemotron-3.5-lightning:free without updating either test's hardcoded mock fixture, and landed after the last full regression-gate run, so nothing caught the break before UAT. Separately confirmed via web search: nvidia/nemotron-3.5-lightning:free IS a real, currently-listed free-tier OpenRouter model (released 2026-08-11) — the 'not found' failure is test-double staleness, not proof the model ID is invalid; whether it would pass the engine's live structured-output capability preflight against the real OpenRouter /models endpoint is unconfirmed and untested."
fix: "Not applied — goal is find_root_cause_only. See suggested fix directions in the diagnosis report."
verification: ""
files_changed: []
