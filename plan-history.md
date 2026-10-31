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
