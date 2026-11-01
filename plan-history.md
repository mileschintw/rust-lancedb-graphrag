# Plan history

Finished work moved out of `plan.md`, newest first, for checking only; the plan is the source for anything current. Each block names when it moved and the coordinator that moved it.

## Lane 68 merged (moved 2026-10-31, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 68, #68, dev-role scoring: session local_698777e7-e8f4-479a-8181-1d7d2e5cab68, branch `claude/lane-68-db7b79` @ bea798b0. PR #83 was opened and merged 2026-10-31 under the standing auto-PR rule, once `ci` passed (eval 2m42s). #68 closed. On a dev-role corpus, `score` and `compare-levers` now read the dev population (real S1 split 90 G / 10 null), and held-out output stays byte-identical. The main checkout was not fast-forwarded, because run-s01 is active.

## Lanes 65 and 67 merged (moved 2026-10-31, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- **Lane 65**, #65 (two-store S1 context export):
  - Session local_b7cfc571-373e-4470-bddf-1aab4c6c0242, branch `claude/lane-65-53b502` @ 679e1fb2.
  - PR #72 merged 2026-10-31, opened and merged under the standing auto-PR rule after `ci` passed (eval 2m40s). #65 closed.
- **Lane 67**, #67 + #69 (S1 seed chunking; S1 identity schema):
  - Session local_dd601ae8-4af5-4751-8aa3-86e68c29b59f, branch `claude/lane-67-ddf8d3` @ 3f37a770.
  - PR #73 merged 2026-10-31 as c69d4868 (auto-PR rule, `ci` passed, eval 1m36s). #67 and #69 closed.
  - The S1 chunking check is `lancet-eval preflight --corpus multihop_rag_s1_dev --store eval-s1` (check `store_chunking`).

## Lane prereg-s01 merged (moved 2026-10-31, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane prereg-s01, the S0/S1 pre-registration and run guide (no issue): session local_d5df8b19-d4ed-4c18-b9b6-7e7ff2b0372e, branch `claude/lane-prereg-s01-73d291` @ 5e7f0232. PR #70 was merged 2026-10-31 as 5aedae9f on the user's "開 PR，CI 過了就 merge (Recommended)", after `ci` passed (eval 2m37s).
  - **Adds:** `EXPERIMENT-S0.md`, `EXPERIMENT-S1.md` and `RUN-S0-S1.md`; D-261 to D-264, the user's four answers, all "(Recommended)": the S0 null guard read both ways with the winner required to pass; v1.0 thresholds kept for S0 and S1; the S1 graph rule applied on the chosen store; the S1 dev null guard 0.10/0.80, which vetoes both choices. Also the stage constants `PREREGISTRATION_S1` and `PREREGISTRATION_S1_MERGED_GRAPH` (the latter needs the guide's manual D-73 check).
  - **Found and filed:** #65, #67 and #68. Fast tier 2739 passed. S0 can run now. S1 waits on #65, #67, #68 and #69.

## Lane 54 merged (moved 2026-10-31, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 54, #54 Reader comparison and cost: session local_c8000942-9af7-443f-833d-077017fa96fd, branch `claude/lane-54-5835c0` @ 1af22049. PR #66 merged 2026-10-31 as f06a020b on the user's "開 PR，CI 過了就 merge (Recommended)" after `ci` passed (eval 2m3s). #54 closed. Eval fast tier 2726 passed; slow v1.0 re-score unchanged (35 passed). Interpretations accepted by the user: "answered" = `answer_usable` true on G; carried deepseek arms priced at `measure.GENERATION_*_PRICE_PER_1M` (0.14/1.28); batch rate = declared sync × 0.5; `reasoning_tokens` counted inside `completion_tokens`. Note for #53 is on its roadmap row (`compute_spend` needs `readers=`).

## Lane 47 merged (moved 2026-10-30, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 47, #47 External evidence shows chunk_index=0: session local_f74dc425-7470-4904-974a-b8e78264bf9e, branch `claude/lane-47-239abf` @ a596c66a. PR #62 merged 2026-10-30 as 2c9ca064 on the user's "開 PR，CI 過了就 merge (Recommended)". The first engine job (14m49s) failed on the flaky `graph_augmentation_attempted_and_failed_is_observable_end_to_end` (tracing interest caching, unrelated; lane 59 fixes it). A rerun of the failed job passed (engine 12m13s), per the user's rerun-once rule. #47 closed. `chunk_index_of` parses `:` and `#`; Lancet pack byte-identical. Follow-up #61 (rebuild-hook race) was folded into lane 59. `engine/target` (49 GB) deleted. Engine CI time for #58: 12m13s on the rerun (> 8 min; decide after #56 merges).

## Lane 52 merged (moved 2026-10-30, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 52, #52 Reader arms and the replay record kind: session local_f927678d-e609-4878-ab6d-f5b300b78106, branch `claude/lane-52-f0a385` @ ffa05c99. PR #63 merged 2026-10-30 as 72c6d2c8 on the user's "開 PR，CI 過了就 merge (Recommended)" after `ci` passed (eval 1m42s; engine and gateway skipped). #52 closed. Adds reader-arm labels, the replay record kind (9 zero-tolerance clauses), `replay-init`, and D-260 (ruling 7). Eval fast tier 2716 passed; v1.0 re-score slow checks byte-identical. Coordinator calls: the ruff bar is "no new errors" on files with pre-existing errors; GLOSSARY terms wait until S2 settles. For #53/#54: replay record fields and journal header keys are in PR #63's "For #53 and #54" section; each batch success record needs an export row (the carried base row with `arm` set to the reader-arm label).

## Lane 51 merged (moved 2026-10-30 22:11 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 51, #51 Request rewrite for Claude readers: session local_5e80f874-0b01-4ce9-bd16-ea728c6cb66f, branch `claude/lane-51-ff04eb` @ 3d46e6b1. PR #60 merged 2026-10-30 as 107d92cb on the user's "開 PR，CI 過了就 merge (Recommended)" after `ci` passed (eval 1m27s; engine and gateway skipped by path filter). #51 closed. New `reader_request.py`, 43 tests, 4 golden bodies; eval fast tier 2676 passed. Its open question became ruling 7 (between_tools encoding). Note for #52: `pack_body.json` is hand-built from `OpenRouterChatPayload` (schema keys sorted); the real `pack` end-to-end check is #52's integration test (Q14).

## Lane 44 merged (moved 2026-10-30 18:42 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 44, #44 test-suite tiering, time budget and CI: session local_926e074a-57c2-4ee7-8614-c320ca44dced, branch `claude/lane-44-fc59e2` @ dbab8f18. Fast/slow/live tiers in `docs/testing.md`; per-target floors replace hardcoded Rust/Go counts; `.github/workflows/ci.yml` path-filtered per module, single required check `ci`; 15 low-value tests deleted and 6 rewritten or trimmed per the user's review of `reports/44-deletion-candidates.md`. User rulings: "列清單給我審", "全照建議 (Recommended)", "照做 (Recommended)", "加進 lane 44 (Recommended)", "允許 (Recommended)" (CI reads committed held-out files offline). The first CI run took four pushes to fix environment gaps: protoc plus `libprotobuf-dev`, `_TYPER_FORCE_DISABLE_TERMINAL=1`, `UV_LINK_MODE=copy`, and ANSI-safe floor parsing. PR #57 merged 2026-10-30 as 44744ee2 on the user's "開 PR，CI 過了就 merge (Recommended)" once `ci` passed (engine job 16m31s, cold cache). #44 closed. `engine/target` deleted. project.md checks updated to the fast tier on the user's "更新 (Recommended)". Branch protection requiring `ci` is the user's repo setting, not yet set.

## S2 grill → spec → tickets round (moved 2026-10-30 15:35 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Reminder (user's request 2026-10-29 18:48 -0700, "#7 到 #15 全部 merge 之後、S1 付費跑分之前，提醒我跑 S2 程式碼準備的 grill → spec → tickets（範圍見 #6 的留言）") given 2026-10-30 14:42 -0700 after #14 merged. On the user's "幫我開一個新session做 grill → spec → tickets 這套流程以及所有相關需要決策的事務", the coordinator started decision session local_ab3487b9-5b99-46f4-8d1c-2ed3f5e8f4b6 (branch `claude/s2-code-prep-spec-491e69`). Outcome: spec #49; tickets #50 (`render`), #51 (Claude request rewrite), #52 (reader arms, replay record kind), #53 (batch submit/fetch), #54 (reader comparison and cost); #44 and #47 attached with decisions; D-254 to D-259 in PR #55 (open). Every answer with the user's words is in `decisions-2026-10-30.md` (Q1-Q15, #47, #44, lane 14 and lane 15 open points). Key rulings: no mid-run spend caps (D-258 amends D-246; `run-external --stage-cap` stays, set unreachable); no prompt caching (D-256); #47 = bin also parses `<document_id>#<n>` (D-259); #44 runs first and alone; `PREREGISTRATION_S1` kept; S1 keeps the levers-dev question set.

## Lane 46 merged (moved 2026-10-30 15:02 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 46, #46 stage cap for run-external: session local_7db515c9-3df3-4e94-b36a-0f6f18740672, branch `claude/lane-46-dce2c9` @ 4d7bb524 (eval only). Required `--stage-cap`, checked before each 16-row batch against `compute_spend` over the whole journal; may overshoot by one batch, like `run`. PR #48 merged 2026-10-30 as 087d72dc on the user's "開 PR 並 merge (Recommended)" (no CI). #46 closed. No engine/target was built.

## Lane 14 merged; v1.1 code prep (#6) closed (moved 2026-10-30 14:42 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 14, #14 run-external: session local_148e4c13-9ad9-4dfa-8467-7fc587f47794, branch `claude/lane-14-f3ca8e` @ ce6faac8 (eval only; widened to `cli.py` › `export-context`'s one call to `run.write_context_export`; `context_export.py` unchanged). Batches of 16 per bin call, each appended to the journal; generation model/provider order taken from the `pack` body; reader lever `evidence_metadata` only (D-248). PR #45 merged 2026-10-30 as 00d73ff5 on the user's "開 PR 並 merge (Recommended)" (no CI). #14 and #6 closed. `engine/target` deleted. Follow-ups opened on the user's answers: #46 (stage cap), #47 (chunk_index in external provenance). Notes kept by the lane: run-external header has no `max_retries` marker; atomic export write duplicated 3x; generate's citations/answer_basis/final_answer not kept on RunRecord; `duration_ms` 0.0 for external.

## Lane 25 merged (moved 2026-10-30 13:59 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 25, #25 clippy `-D warnings`: session local_335ebf28-cea5-4abd-bdf9-dc8a3d7ceb27, branch `claude/lane-25-edb296` @ 51bbd491. 23 lint fixes in 13 engine files, no `#[allow]`, test count unchanged (982). PR #43 merged 2026-10-30 as fd7df9ec on the user's "開 PR 並 merge (Recommended)" (no CI). #25 closed; carries #11's clippy criterion. `engine/target` deleted. Note: `rustfmt --check` has a pre-existing diff in `engine/src/bin/diag_probe.rs` (not in any check).

## Lane 39 merged (moved 2026-10-30 13:51 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 39, #39 `_delta_dimension` reference keys: session local_acd47167-e78a-4cc6-a3b6-40b9a77ecfe0, branch `claude/lane-39-decbe9` @ e96f00a0 (eval only). `hybrid` reference keeps `mean_hybrid`/`count_hybrid`, others get `*_reference` (same rule as #36); v1.0 held-out `report.json` equal on all 187 dimensions, drive2 unchanged. PR #42 merged 2026-10-30 as 1a84d7eb on the user's "開 PR 並 merge (Recommended)" (no CI). #39 closed. No engine/target was built.

## Lanes 34 and 36 merged (moved 2026-10-30 13:33 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 34, #34 compare bound to the 06.3.5 arms: session local_f2485cb2-2a83-46cb-a547-1370f331e4e1, branch `claude/lane-34-56a8ff` @ 09f1f530 (eval only). Chose the up-front refusal (`_require_06_3_5_corpus`), pointing to `compare-levers`; `_ARM_SLUGS` removed; v1.0 comparison outputs byte-identical. PR #40 merged 2026-10-30 as 9dd01fe0 on the user's "開 PR 並 merge (Recommended)" (no CI). #34 closed. No engine/target was built.
- Lane 36, #36 judged delta detail keys: session local_af37bee0-c864-4551-88c1-ee2a7097144b, branch `claude/lane-36-d5a37e` @ 8c471911 (eval only). `hybrid` reference keeps the v1.0 names, other references get `*_reference`; v1.0 held-out `report.json` equal on all 187 dimensions. PR #41 merged 2026-10-30 as 6a2cffb7 on the user's "開 PR 並 merge (Recommended)" (no CI). #36 closed. Opened #39. No engine/target was built.

## Lanes 11 and 30 merged (moved 2026-10-29 23:58 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 11, #11 generate-only engine bin and prompt parity check: session local_d66def13-7ecf-400a-948a-1c4190ee4f40, branch `claude/lane-11-3e9042` @ d670aa76. PR #37 merged 2026-10-29 as 2d552980 on the user's "開 PR 並 merge (Recommended)" (no CI). #11 closed. Engine test targets now 982. Clippy criterion carried by #25 (ruling 5). `engine/target` deleted.
- Lane 30, #30 judged scoring and calibration keep store-prefixed arms: session local_4757ad58-ec8e-41c5-a84a-a2da25bd7ce7, branch `claude/lane-30-1bb6ad` @ c508ca4f (eval only; widened to `judge_stage.py` and `CalibrationKeyRow`, option A). PR #38 merged 2026-10-29 as 546655c9 on the user's "開 PR 並 merge (Recommended)" (no CI). #30 closed. Opened #34 and #36.

## Lane 29 merged (moved 2026-10-29 23:26 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 29, #29 raw-event dirs for store-prefixed arms: session local_9450bd63-4293-40ea-b77c-2049d7d385d8, branch `claude/lane-29-192208` @ b4240359 (eval only). PR #35 merged 2026-10-29 as 8763cd08 on the user's "開 PR 並 merge (Recommended)" (no CI). #29 closed. No engine/target was built.

## Lanes 15 and 23 merged (moved 2026-10-29 23:01 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 15, #15 Store-prefixed arms and the S1 corpus: session local_3028b84a-992d-4853-9f02-e64406d045c5, branch `claude/lane-15-d4af27` @ acae0905. PR #32 merged 2026-10-29 as b93d3487 on the user's "開 PR 並 merge (Recommended)" (no CI). #15 closed. Carried #18's score-side reader. Opened #29, #30. `engine/target` deleted. Note: `StoreChunking` is declared but not yet checked against a built store (S1 store build).
- Lane 23, #23 flaky engine lib tests: session local_152dde96-4043-4687-bcae-ec7c450545a5, branch `claude/lane-23-737211` @ 9a1cc57a. PR #33 merged 2026-10-29 as 55d89e7a on the user's "開 PR 並 merge (Recommended)" (no CI). #23 closed. Test seam: `#[cfg(test)]` thread-local meter in `engine/src/telemetry/metrics.rs`; lib+bin count unchanged (856). `engine/target` deleted. From now on, engine lib flakes are not expected; a lane failure there is real.

## Lane 13 merged (moved 2026-10-29 22:52 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 13, #13 LlamaIndex baseline project: session local_2cb496f3-680b-426e-b0e7-d4710ae7e26c, branch `claude/lane-13-08d1ed` @ f3b462e0 (rerank on chunk text only, ruling 6). PR #31 merged 2026-10-29 as 059c7513 on the user's "開 PR 並 merge (Recommended)" (no CI). #13 closed. `engine/target` and its C: scratchpad target deleted. Live `input_type` and 346-doc export checks deferred to S0 (plan › Waiting for the user to be present). Notes: `baselines/llamaindex/uv.lock` locks the harness deps, so any `eval/pyproject.toml` change needs `uv lock` there too; `write_outputs` replaces two files in sequence.

## Lanes 10 and 20 merged (moved 2026-10-29 22:08 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 10, #10 Evidence Hits@4 and context tokens: session local_22f42b71-55f9-4aa8-aad2-1f9f39e36c0e, branch `claude/lane-10-ea13ed` @ 3d1305fd. PR #27 merged 2026-10-29 as e7a3dfe5 on the user's "開 PR 並 merge (Recommended)" (no CI). #10 closed. Adds `tiktoken` to eval. Opt-in v1.0 lever re-score test: `LANCET_EVAL_RESCORE_LEVER_RUN=1` (~9.5 min). `engine/target` deleted.
- Lane 20, #20 `run` exits non-zero on export failure: session local_d52ca4b3-d72c-4c36-b380-04a573500818, branch `claude/lane-20-474a4b` @ 10d0c923. PR #28 merged 2026-10-29 as 0371b730 on the user's "開 PR 並 merge (Recommended)" (no CI). #20 closed. `engine/target` deleted. Lanes 11 and 15 told to catch up (cli.py, score.py, levers_fixture.py).

## Lane 16 merged (moved 2026-10-29 21:47 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 16, #16 Shell scripts LF: session local_8cc16651-c299-4094-964f-a2cfabe355a2, branch `claude/lane-16-dcd7b8` @ 5c2b072d (`.gitattributes` only). PR #26 merged 2026-10-29 21:47 -0700 as 5f6030e0 on the user's "先開PR並merge，我再compact" (no CI). #16 closed as completed. Lane opened #23. `engine/target` deleted after merge. From now on root pytest has 1 known `scripts/` failure (the `python -O` test), not 5.

## Lane 12 merged (moved 2026-10-29 21:35 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 12, #12 Score external arm records fail-closed: session local_5f2c01f8-0943-4b5d-b4bb-92caa4b4a8f7, branch `claude/lane-12-eb8ff8` @ 7bc4eb76. PR #24 merged 2026-10-29 21:35 -0700 as d15652a0 on the user's "開 PR 並 merge (Recommended)" (no CI). #12 closed as completed. Lane saw the flaky engine tests filed as #23 (opened by lane 16). `engine/target` deleted after merge.

## Lane 9 merged (moved 2026-10-29 20:20 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 9, #9 S1 store isolation + #18 per-store document map: session local_480eb168-cfbd-41d1-8c41-a352e6f35553, branch `claude/lane-9-fa5fe0` @ dc443cfb (caught up with main after #19). PR #22 merged 2026-10-29 20:20 -0700 as f7deeed6 on the user's "先追 main 重跑，再開 PR 並 merge (Recommended)" (no CI). #9 and #18 closed as completed. #18's score-side reader handed to #15. Live Atlas steps deferred (see plan › Waiting for the user to be present).

## Lane 8 merged (moved 2026-10-29 20:12 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 8, #8 structure-merge chunk strategy: session local_4a84ea68-2849-4f35-8017-514e7501aaf3, branch `claude/lane-8-e87587` @ 0435995b. PR #21 merged 2026-10-29 20:12 -0700 as 60f021d6 on the user's "開 PR 並 merge (Recommended)" (no CI). #8 closed as completed. Also fixed main's pre-existing clippy `never_loop` in `engine/src/generation/tests.rs`; set `scripts/engine-test-targets.sh` to TOTAL 973 / lib 856. Note for #15: `structure-merge` sizes are tokens (256/25); the gateway's unset default 500/50 would be read as tokens.

## Lane 7 merged (moved 2026-10-29 20:01 -0700, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 7, #7 Context export from engine checkpoints: session local_62fc0cbb-8a7d-4976-a2c6-5d117782e414, branch `claude/lane-7-91faeb` @ 07efa9df. PR #19 merged 2026-10-29 20:01 -0700 as 8c252d47 on the user's "開 PR 並 merge" (no CI exists). #7 closed as completed.
- Follow-up #20 (`run` exits non-zero on export failure) opened on the user's "開 issue (Recommended)".

## audit-s012 finished (moved 2026-10-31, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Read-only paper audit of the S0/S1/S2 pipelines, session local_0b05ece6-b691-41ff-ab64-1658bbffdae1. It had no branch commits and no PR (`ready` lists it as "branch not pushed", which is expected). It filed #74 to #82 and commented on #49, #53 and #78; the report is `reports/audit-s012.md`. S0 had no code blocker. #74, #75 and #76 were carried into brief run-s01, #79 got lane 79, #80 and #82 got lane 80, which failed to start, #81 got lane 81, and #77 and #78 block nothing.

## Lane 79 merged (moved 2026-10-31, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b)

- Lane 79, #79 (S1 seed failed rows, run guide recovery, S1 document map commit): session local_1bcc1f38-7e77-4d99-8d8c-a80616cd1707, branch `claude/lane-79-415c90` @ 17801a6c. PR #85 merged 2026-10-31 under the auto-PR rule after `ci` passed (engine 9m3s, eval 2m6s). #79 closed. Main checkout not fast-forwarded (run-s01 active).

## Lanes 50, 81, 84 merged (moved 2026-10-31, coordinator local_e5497074-397c-4170-ba22-60a6e066d35b, unattended)

- Lane 50, #50 (engine `render` mode for batch results): session local_966633ab-d14a-4d0a-b91e-32999fa2a658, branch `claude/lane-50-c453ac` @ d61c2b0b. Paused for the S0 HOLD, then reran the release build, clippy and the integration tier (46 passed). PR #86 merged 2026-10-31 ~04:03 -0700 under the auto-PR rule after `ci` passed. Its PR body's "For #53" section carries the render CLI, the results-line schema and `--levers`.
- Lane 81, #81 (S2 reader rows: deepseek priced at the budget ceiling, per-reader rows unpaired): session local_73abd391-fc59-4104-8901-ddc3156a2e76, branch `claude/lane-81-559d88` @ 61c2333f. PR #87 merged ~04:03 after `ci` passed. It merged before #90 (lane 80), so lane 80 owns the test_reader_comparison.py overlap.
- Lane 84, #84 (run_psql cp950 decode): session local_50f4f434-be2a-4a71-bf1a-79762e0f6183, branch `claude/lane-84-c98881` @ 16602691. All five subprocess call sites now decode as UTF-8, with a cp950 regression test. PR #88 merged ~04:03 after `ci` passed. S1 no longer needs `PYTHONUTF8=1`.
- All three lanes' engine/target were deleted; the main checkout was fast-forwarded to 2b16415f, and `lane-80-base` was reset to it.
- Lane 80, #80 + #82 (replay-init S2 corpus; target-specific replay clauses + prompt clause): session local_9dd7f249-d7ac-4ef8-b63a-01fba8cb80fa (restart; the first session failed with "config-hooks-refused"), branch `claude/lane-80-8015a4` @ 12ee4c4c. It merged origin/main after #87 and resolved the test_reader_comparison.py overlap. PR #90 merged 2026-10-31 ~04:08 -0700 after `ci` passed. #80 and #82 closed. Its engine/target was deleted. The main checkout was fast-forwarded to f9cd90c1. GO #53 sent.
- Lane 59, #59 + #61 (telemetry_query CI hang; PR #62's tracing flake): session local_c2bb79da-b215-4c0b-932a-492cfac1a805, branch `claude/lane-59-c47b6e` @ baa4ed76. Final loops passed 20/20 at t4 and 5/5 at the default thread count, plus the fast tier and clippy. PR #91 merged 2026-10-31 ~04:55 -0700 after `ci` passed. #59 and #61 closed. #64 is now startable on the user's yes.
- Lane 53, #53 (batch submit and fetch): session local_52506005-0052-4550-9ba5-b4037844160e, branch `claude/lane-53-f21668` @ 8953897f. Built after GO #53 against #50's render and #80's replay fields. It went through three review rounds with no blocker, and the fast tier, slow re-score and integration tests passed. No paid batch was submitted. PR #92 merged ~04:55 after `ci` passed. #53 closed. Both lanes' engine/target were deleted; the main checkout is at cc10774e.
- Unattended note 2026-10-31 ~05:20 -0700: main's push run at dc8a6ccc (the merge of #91) failed engine on `graph_augmentation_attempted_and_failed_is_observable_end_to_end` (`left: []`). PR #71 failed the same test twice. Opened #93 under the follow-up permission. PR #71 is held, not Stuck, because main itself is red. Lane 59 was asked to diagnose only.

## 2026-10-31 afternoon: S0 record, #93 fix, #49 closed

- **run-s01:** PR #89 (S0 run of record) merged 2026-10-31 as b3fba1c5 on the user's "直接合併 (Recommended)". The worktree D:/Repos/lancet-run-s01 was removed. D:/s0-run-backup/ is left for the user to delete by hand (the coordinator's delete was blocked as a protected path).
- **#93:** PR #94 from `lane-93` (lane 59's test-only fix) was opened on the user's "好，開始 lane 93" and merged as 0fc830e8 after `ci` passed (engine 3m27s).
- **#49 (parent):** closed on the user's "關掉 (Recommended)".
- **#95** (D-265) was opened on the user's "新增 D-ID (Recommended)".
- **Lane 56 (#56):** PR #71 merged 2026-10-31 at 343d29db after #94 fixed #93 (ci green). D:/lane56-targets is to be deleted (user: "等 lane 59 merge 後再跑 (Recommended)").
  - D:/lane56-targets: the coordinator's delete was blocked as a protected path; left for the user to delete by hand.
- **Lane 74 (#74, #75):** PR #96 merged 2026-10-31 at c566a7cc (ci green). **Lane 95 (#95):** PR #97 merged 2026-10-31 at 266600d4 (ci green); D-265 is on main.
- **Lane 98 (#98, #99):** PR #101 merged 2026-10-31 (ci green). #98 is clean. #99: neither S0 arm sent input_type, and the step 2.1 live check showed it is forwarded.
- **Lane 76 (#76):** PR #102 merged 2026-10-31 (ci green). The stub serves /rerank, the export takes an endpoint override, and the S0 rehearsal corpus was added.
- **Lane 77 (#77, #78):** PR #103 merged 2026-10-31 at d03eae08 (ci green). **Lane 64 (#64):** PR #104 merged 2026-10-31 at d839f7b5 (ci green). Every S1 prerequisite in the approved path is now on main.
- **Lane 107 (#107):** PR #112 merged 2026-10-31 (ci green). The OpenRouter batch payload sends endpoint, model and provider ahead of requests.
- **Lane 105 (#105, #106, #113):** PR #111 merged 2026-10-31 at 9e80334c (ci green). D-266 is in, and the S1 step 4 guide fixes and paste-safe snippets are on main.
- **Lane 109 (#109):** PR #115 merged 2026-10-31 at b48149e6 (ci green). It adds the D-73 check before spend, `replay-init --pilot`, and the replay_source_arm and completeness checks.
- **Lane 110 (#110):** PR #116 merged 2026-10-31 at cf9adf3f (ci green). It adds the S2 type, a draft constant in EXPERIMENT-S2.md (kept out of thresholds.py, D-73), RUN-S2.md, the S2 dev corpus, a .gitignore line, and D-267 to D-270. The old branch `claude/peaceful-robinson-2e31dd` must never be merged.
- **Lane 118 (#118):** PR #119 merged 2026-10-31 as aedd4723 (ci green). Adds the wafer/us pin with max_price (D-271), the extraction cap 16384 and 120 s timeout (D-272). Re-scoring S0 now needs its recorded provider order (score.py reads config.toml).

- **Lane 120 merged** 2026-10-31: PR #121 (closes #120), merge 971094f5. S1 overlay `excerpt_max_chars = 2048` (D-273; longest S1 chunk 1,489 chars; measurement-only, never reaches the prompt). Ran in lane 118's reused session (new sessions cannot start over Remote Control), branch `lane-120`. User: "開 lane 修 #120 (Recommended)", "Start lane 120".

- **S1 recorded** 2026-10-31: PR #122 merged (16b9ebe5), run `eval/runs/2026-10-31-s1-multihop_rag_s1_dev`. Keep small, graph out; S2 `replay_source_arm` = `small/hybrid+rerank+metadata`. S1 total spend about $3.1-3.7 (step 1 ~$2.4-3.0, step 4 $0.67).

- **Lane 125 merged (2026-10-31):** PR #129 at a858a339, merge b3f50d49, closes #125. Session local_7141a026-cb3b-4eaa-8c8c-0fe3f215cb87 (reused). Merged-store chunk-ID secondaries are now not evaluable; coverage_at_4 uses each store's chunk size; S1 decision rows byte-identical; EXPERIMENT-S1.md › Result carries the note.

- **Lane 124 merged (2026-10-31):** PR #131 at b5d4c7b8, merge 95d98ff0, closes #124. D-276: answer normalisation (plural folding, order-free lists), dual judge gpt-4o-mini + Sonnet 5.5 (`judge-answers`), S0 0 flips, S1 6 records flip, no decision change.
- **Lane 123 merged (2026-10-31):** PR #132 at 5937b119, merge 7aa4c50c, closes #123 and #127. D-274 (K=5 replicates, RunRecord.replicate, exact permutation on per-question means, question bootstrap), D-275 (cheapest eligible reader unless a dearer one is significant after Holm). Old runs score byte-identically. Session local_7141a026 reused.
- **Lane 134 merged (2026-10-31):** PR #135 at 4e5e5bb7, merge ad219cc2, closes #134 (RUN-S2 guide: git status rule, #108 via pilot, cost table by credit, PYTHONUTF8). Deepseek submit lines handed to lane 133.
- **Lane 133 merged (2026-10-31):** PR #136 at e34a9f3d, merge f3f036ee, closes #133. D-277 (deepseek Wafer price in the S2 pre-registration), D-278 (deepseek replicates via sync /chat/completions), Sonnet judge BYOK fail-closed, fetch mismatch summary, target clauses on errored replay records.
- **Lane 137 merged (2026-10-31):** PR #140 at c5f2bf13, merge ad8ed74f, closes #137 and #138. D-279 (OpenRouter batch rows from response.body; is_byok from batch-level usage), D-280 (Sonnet via OpenRouter BYOK sync, between_tools kept; native batch fallback dropped).
- **run-s2 pilot 1 (2026-10-31):** blocked after pilot 1 (~$0.35 spent): #137 (batch result shape, is_byok batch-level) and #138 (Sonnet between_tools refused by the Batch API). #138: user asked "所以是為甚麼被拒絕？不是有的batch API", then chose "先免費試原生 batch (Recommended)": run-s2 probes native Sonnet (step 3, --limit 2, ≤$0.13); refused → sync (D-280 in lane 137), accepted → native per D-260. Re-pilot approved: "同意，約 $0.6（上限 $1.5） (Recommended)"; GO once #137 (and the #138 fix) merges. Told to revert the step 1 paste in the main checkout. Haiku/Opus pilot: strict schema accepted (#108), provider Anthropic, reasoning 0; deepseek passes every row

- **run-s2, steps 4-8 (2026-11-01):** GO after both compacts (user: "先compact run-s2跟你，然後再一次全部跑完"). Step 4 freeze PR #141 merged (15a20fdd). Steps 5-7: four arms 500/500 (deepseek 493 ok + 7 billed render errors on 3 null questions → every Claude-vs-deepseek null guard NOT EVALUABLE, 35/40 pairs). answer_usable: deepseek 0.853, Haiku 0.693 (-16.0, Holm-rejected), Sonnet 0.791 (-6.2, n.s.), Opus 0.824 (descriptive). deepseek wins; D-245 fails. Opus reasoning_tokens 2,399 (4.8/record); others 0. Dual judges agree within ~2 pts; 14 disagreements listed. Step 8 PR #142: first CI fail (test_journal no-levers exemption lacked "-s2-"), fixed 1ac01fc4, merged 0344ade8. Spend ~$14.38 (batch_spend prints Sonnet at half: #139).

## Lane 143 (merged 2026-11-01, unattended)

| 143 | #143 | local_ed178c0c-c52d-4b0d-adfc-1716596a661f | started 2026-11-01 on the user's "好，執行三個 reader K=2 跟補跑deepseek": exploratory merged-store reader run, K=2 (Haiku, Sonnet sync, Opus, + deepseek replicate 2), ~$7, ceiling $15. Freeze PR #144 merged 639ee82f (first CI fail: ruff line length, fixed by amending to c767bff1); "continue" sent. Flow: freeze PR → coordinator merges → "continue" → paid run in main checkout → record PR (merge on green, standing instruction 1) | — |
| #143 | now (lane 143) | — | none | exploratory merged-store readers: `multihop_rag_s2x_dev.toml`, new prereg constant in `thresholds.py`, run dir, `EXPLORE-S2-MERGED.md` | limited: paid ~$7 (approved) |
- Merged: freeze PR #144 (639ee82f), record PR #151 (5422656f). S2X spend ~$7.50. Both predictions hold on point estimates (moved-question abstention: Sonnet 0.267→0.067, Opus 0.227→0.067, Haiku 0.293→0.267; gap to deepseek Sonnet -6.2→-5.6, Opus -2.9→-2.2; overall change <1 point, within noise). Partial yes/no: Claude abstains 39-52%, deepseek 24%. Null guards evaluable, all pass. No decision; deepseek stays reader.

## Lane 147 (merged 2026-11-01, unattended)

| 147 | #147 | local_104e6592-6081-4db7-9dff-6b240ae49211 | started 2026-11-01 (unattended): metric fix (yes/no split, guess-adjusted, evidence split as reported secondaries) + D-IDs for principles 1-9; free | — |
| #147 | now (lane 147) | — | none | `score.py`, `lever_comparison.py`, `PLAN.md` › Decisions | free |
- Merged PR #153 (ce3773f2): answer_usable by kind (yes/no, open), balanced accuracy, evidence split; D-281..D-289. Opened #152 (slow-tier v1.0 re-score drift since D-276).

## Lane 117 (merged 2026-11-01, unattended)

| 117 | #117 | local_cb4d73f6-3280-45c7-beb4-29ac541d651d | started 2026-11-01 on the user's "Start #117": writer pilot in its own worktree (never the main checkout); thinking per the confirmed ruling (Haiku off, Sonnet effort low, batch); free work done (2951e977); **paid gate approved 2026-11-01, user: "Approve, in stages"**: canaries → 4 Haiku + Sonnet batch 1 → project Sonnet from batch 1, continue if ≤ $15 else ask → deepseek sync; ceilings Claude $20, OpenRouter $1; batches by the morning of 2026-11-02 | — |
| #117 | after S2 submit | — | none | writer pilot: Haiku/Sonnet subset extraction (30-50 docs), cost and quality, no store; BYOK check (user: "是，排在 S2 後 (Recommended)") | limited: paid, before the credit expires 2026-11-03 |
- Merged PR #155 (8f313127). deepseek 1,803 chunks $0.245 OR. Recommendation: Haiku as third writer (cheaper per chunk than deepseek on Batch, no runaways, ~25% more entities, ~40% more relations); Sonnet only if affordable (14 dangling vs 238, ~20x Haiku's price). Follow-up #156 (deepseek runaways).

## Lane 149 (merged 2026-11-01, unattended)

| 149 | #149 | local_0c64611e-c641-4167-b6c3-364ca0fdeead | started 2026-11-01 (unattended): B 2Wiki hybrid readers + C full-MHR fresh split, store, readers; freeze PR(s) → main checkout (2nd, after 143) → Claude readers tonight (ceiling Claude $70, OpenRouter $3) | — |
| #149 | now (lane 149) | — | #145 (2Wiki pin/split, part B) | 2Wiki + full-MHR corpus configs, fresh split file, prereg constants, `EXPLORE-B/C` docs | limited: paid (pre-approved), store builds (approved) |
- Merged freeze PR #157 (68c100a5) and record PR #159. Claude $30.82, OpenRouter ~$1.50. Run dirs kept out of git (public repo, retrieved article text); sha256 manifest in explore-bc-runs.json; dirs in data/lane149-runs/ (owner to confirm).

## Lane 148 (merged 2026-11-01, unattended)

| 148 | #148 | local_4b47d05b-1a55-4b82-a4da-a3b9193706f8 | started 2026-11-01 (unattended): MHR writer grid on S1 subset; freeze PR → Claude extraction tonight (ceiling Claude $40, OpenRouter $1.50); graph import + reading after main checkout (3rd) | — |
| #148 | now (lane 148) | — | #117 (script) | `multihop_rag_s3m_dev.toml`, prereg constant, extraction import path, `EXPLORE-S3-MHR-WRITERS.md` | limited: paid (pre-approved, ceilings) |
- Merged freeze PR #154 (03fcb908) and PR #160 (76ee82d4). Claude ~$37.8 (Haiku $1.43, Sonnet $29.14, Opus spot $7.21), OpenRouter ~$2.03 extraction + phase 3. Reading: open / does not explain (deepseek +1.7, Haiku/Sonnet -3.3); verdict() went one-sided → two-sided after the data, both readings reported (owner to note).

## Lane 146 (stopped 2026-11-01)

| 146 | #146 (prep) | local_97bc85b5-3b3c-469c-8a5b-d7eb5514737a | started 2026-11-01 on "Confirm and start": full-corpus stores, LlamaIndex 609, run plan + prereg drafts (free) | main checkout after spare-1 |
- Stopped: owner "Pause #146" (relayed "可以，先暫停"). Branch claude/lane-146-6286dc at ac782ac4: merged-store code, LlamaIndex 609-doc persisted index, WIP EXPERIMENT-CONFIRM.md; no paid calls; main checkout untouched (reports/146.md). Focus moves to S3 core (#163), a one-page results summary, then agentic retrieval / graph community summaries.

- Lane 146 (#146 merged-store code only): merged as PR #170 (9eb2f2bf) 2026-11-01; progress comment posted on #146. Row: | 146 | #146 (merged-store code only) | local_97bc85b5-3b3c-469c-8a5b-d7eb5514737a | resumed 2026-11-01 (owner: "可以，就這麼辦"): PR with merged-store code only; run plan/prereg stay unfrozen drafts; progress comment for #146 | PR on done |
- Lane spare-2 #128: merged as PR #171 (0313af73) 2026-11-01; #128 closed; lane continues on #164.
- Lane 145 (#145): merged as PR #172 2026-11-01 (deepseek 6,119/6,119 sync, $1.12, 42 runaways; 8-shard deviation recorded). Row: | 145 | #145 | local_b792b8dc-3864-43f1-8564-58de4475b13b | done at c239a969: deepseek 6,119/6,119 sync, $1.12, 42 runaways; full text committed; PR #172 open, CI running | — |
- Lane spare-2 #164: merged as PR #174 (19998782) 2026-11-01; #164 closed. Row: | spare-2 | #164 | local_945630cc-9acd-4111-b020-a38a766b222f | #164 done at 084746bb (branch lane-spare-2-164; external arms name their store via `[documents] external_store`, option A); PR #174 open, CI running | — |
- Lane spare-1 #163 freeze: merged as PR #173 (512a48a6) 2026-11-01 (D-291; freeze commit 99b9d29e).
- Lane verify (#165 #166 #168 #169): merged as PR #175 2026-11-01. Row: | verify | #165 #166 #168 #169 | local_fadb6e62-e59c-4873-ab7a-71a071124519 | done at 8e591424; PR #175 open, CI running. Findings: always-Yes 0.661 on D-237 dev but 0.537 on C; 2Wiki Opus +14.0 [+7.5, +20.5] exact; Haiku extra relations 0.85 supported by hand vs deepseek 0.78 | merge on green |
