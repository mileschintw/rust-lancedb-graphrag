# Plan history

Finished work moved out of `plan.md`, newest first, for checking only; the plan is the source for anything current. Each block names when it moved and the coordinator that moved it.

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
