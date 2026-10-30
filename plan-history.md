# Plan history

Finished work moved out of `plan.md`, newest first, for checking only; the plan is the source for anything current. Each block names when it moved and the coordinator that moved it.

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
