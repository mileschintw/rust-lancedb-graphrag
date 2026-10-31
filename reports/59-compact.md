Lane 59 relay worker (relay:work). Worktree D:\Repos\lancet\.claude\worktrees\lane-59-c47b6e, branch claude/lane-59-c47b6e, head baa4ed76 (pushed, clean). Records: D:/Repos/lancet-coord. Brief: briefs/59.md, "Closes: #59 #61".
Rulings: the user widened the lane to #61 ("併進 lane 59 (Recommended)", 2026-10-30). The coordinator approved converting every test set_default site to ScopedSubscriber (telemetry_ingest/metrics, the telemetry/mod.rs tests, plus graph/generation/rerank tests, graph_boost, levers_pins, workflow_phase5), with the guard in engine/src/testkit.rs, test-only, and a timeout panic that names the guard. It also asked for the PR #62 flake to be fixed and named in the PR body, not on the Closes lines.
Done:
- #59: deadlock in tracing-core (provider shutdown under LOCKED_DISPATCHERS). ScopedSubscriber owns an Arc and drops the subscriber on the test thread; 10 s panic "ScopedSubscriber: ...".
- PR #62 flake: tracing-core caches interest on its single-dispatcher path. Fixed with the always-registered OFF `Disabled` dispatcher.
- #61: the three rebuild fault hooks are thread_local.
- Review rounds 1-3 done, no blocker. Opened #64 for REBUILD_COUNTER.
Evidence (scratchpad of this session, ...\223bc948-...\scratchpad):
- Before at main 107d92cb: 9 pass, 1 hang of 10 at --test-threads=4 (before-full/run-9.log).
- Deterministic models: repro/ and repro-interest/.
- Head 00580c44: t4 19/20, a flake in the guard's own test, which led to the Arc fix; default threads 5/5.
- Head baa4ed76: t4 16/16 before the stop.
Left, in order, at baa4ed76 (git fetch first; if main touched my files, merge origin/main and redo the review delta):
1. Build the lib test exe (`cargo test --manifest-path engine/Cargo.toml --locked --lib --no-run`) and copy it.
2. From engine/: `bash <scratch>/loop.sh <exe> 20 300 final3-t4`, then `bash <scratch>/loop-default.sh <exe> 5 300 final3-default`.
3. `cargo test --manifest-path engine/Cargo.toml --locked && sh scripts/engine-test-targets.sh`, then `cargo clippy --manifest-path engine/Cargo.toml --locked --all-targets -- -D warnings`.
4. Fill AFTER_T4, AFTER_DEFAULT and CHECKS in pr-bodies/59.md. Run `relay.py ready`.
5. Write reports/59.md in Traditional Chinese. Include the suggested CI change for after lane 56 merges: `timeout-minutes: 25` on the ci.yml engine "fast-tier tests" step.
6. `relay.py status D:/Repos/lancet-coord 59 --state done`.
Rules:
- Every cargo command with CARGO_BUILD_JOBS=2. Never set CARGO_TARGET_DIR or CARGO_PROFILE_*; the SCCACHE_DIR prefix is optional.
- Run long jobs in the background. Push the branch only; no PR.
- Run relay.py as `py -3 -I C:/Users/user3/.claude/plugins/cache/relay/relay/0.1.0/tools/relay.py`.
Do not touch: engine/Cargo.toml, .cargo/config.toml, docs/testing.md, .github/workflows/ci.yml, generate_from_context.rs, product telemetry code (including the telemetry/mod.rs:339 doc line), non-test ingest.rs code, .planning/, .discussion/, eval/runs/, config/.
