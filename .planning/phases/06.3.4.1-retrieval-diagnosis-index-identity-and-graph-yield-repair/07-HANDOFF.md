# Plan 06.3.4.1-07 Executor Handoff (2026-09-25, Task 4 Route B in flight)

Written mid-flight while the `drive-era` arm runs in the background (could be minutes to hours
-- if growth reproduces, expect production-scale wall clock). Supersedes the prior handoff
(which covered building `stub-vectors.jsonl` and launching `primary-r2`). Read this file, then
the plan's Task 3/Task 4 text, then the profile's `### Full-stack replay: primary-r2 (07)` and
`### Starting gap (07)` sections for full context.

## Where things stand

HEAD at this handoff: `42199e73`. Tree clean except the running arm's untracked scratch files
under `data/replay/`, `data/lancedb-replay/`, `data/lancedb-replay-prereconcile/` (gitignored,
expected). A second git worktree exists at `../lancet-oi02-drive-era` (commit `33e774bd`,
drive_era_commit per `forensics.json`) with pre-built `engine/target/debug/engine.exe`,
`gateway/gateway-replay.exe`, and a synced `eval/.venv` -- **do not delete or rebuild these
until Task 7's cleanup**; Route B will very likely need more arms from this same worktree.

**Task 3 checkpoint: RESOLVED** (`rerun-primary`) and **executed** -- `primary-r2` ran, M1 not
met, M2 **ambiguous** (not "not grows" -- see the classifier bugfix below), routing to **Route
B**. Full detail in the profile's `### Full-stack replay: primary-r2 (07)` section.

**Commits in this continuation session, in order** (after `13150385`, the pause commit):
1. `12e965d8` / `0d339ae3` -- stub vector-map builder tooling (RED/GREEN)
2. `ef553b26` -- STATE.md back to `executing`
3. `5e0914a9` -- handoff before launching primary-r2
4. `74cf1a57` -- primary-r2 replay committed (evidence + profile write-up)
5. `23ea0209` / `1ec7aa33` -- **bug found and fixed during self-review**: `classify_m2`'s
   "not grows" branch read a fixed slice-3 instead of literally "the last full slice" the plan
   specifies -- at the 350-record/7-slice primary scale these are different slices (3 vs 6).
   Both `primary` and `primary-r2` reclassify from "not grows" to **"ambiguous"**.
6. `69a779b5` -- regenerated both `summary.json`s and corrected the profile's M2 write-up and
   routing conclusion. **Routing itself did not change** -- the plan's table already treats
   "not grows" and "ambiguous" identically (Route B) -- this was a labeling correction only.
7. `42199e73` -- extended `scripts/oi02-replay.ps1` with `-EngineLaunch worktree:<path>` /
   `-HarnessFrom worktree:<path>` / `-GatewayFrom worktree:<path>` (previously `-HarnessFrom`/
   `-GatewayFrom` were `ValidateSet('head')`-only -- unimplemented despite the plan naming
   `worktree:` for all three params) plus a scratch-DB naming fix (see below). Validated via a
   throwaway 2-question smoke, deleted after passing (see commit message for full evidence:
   4/4 chunk match against production, 0 embedding-vector mismatches between the reconciled and
   pre-reconcile store copies on the full 137-chunk overlap).

## M1/M2 readings that matter for routing (already committed, don't re-derive)

- **M1 (baseline, store-matched):** not met on both `primary` (ratio 4.71) and `primary-r2`
  (ratio 5.34), band 8.48-33.91. Real graph seeding (`primary-r2`) moved the ratio slightly but
  not into the band. Tracked as `### Starting gap (07)` in the profile -- **no arm has yet
  isolated a starting-gap-specific factor.**
- **M2 (growth):** **ambiguous** on both `primary` and `primary-r2` (see bugfix above) -- fails
  both the "grows" floor (>=1.5x at slice-3) and the "not grows" ceiling (<1.2x at the last
  slice). `primary-r2`'s real graph seeding (109/175 graph-on records got real unflagged
  traversal, vs 0/175 in the invalid first primary) did NOT change this outcome -- rules out
  "random vectors suppressed the growth mechanism" as an explanation.
- **Routing: Route B** (M2 not grows/ambiguous, whatever M1 reads) -- start with the drive-era
  whole stack, exactly as now in flight.

## A scratch-DB naming bug found and fixed during Route B setup (not yet in profile prose)

`$ScratchDbName` was a single shared `'lancet_replay'` regardless of `-StoreSource`. The
restore-from-dump logic only runs `if ($dbExists -ne '1')`, so a pre-reconcile arm would have
silently reused whatever schema state a prior reconciled-store arm already restored into
`lancet_replay`, instead of the pre-reconcile dump. Fixed: named `lancet_replay_prereconcile` /
`lancet_replay` by store source (`42199e73`). **Both scratch DBs now exist and are reused
across arms** -- `lancet_replay` (reconciled) and `lancet_replay_prereconcile` (pre-reconcile).
**Task 7's cleanup must drop BOTH** -- its current verify script only checks `lancet_replay`
by name; update it when you get there, or it will silently miss the second DB.

## The drive-era arm, in flight

Launched via the launcher, `-Label drive-era -Questions 75` (>=150 records per Route B's own
rule), all other config matching `primary-r2`'s stub delays (343/6970) so only the "drive-era
whole stack" factor changes:

```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/oi02-replay-launch.ps1 `
  -LogDir "<temp dir>" -RunName drive-era `
  -ReplayArgsJoined "-Label|drive-era|-Phase|pre-fix|-Questions|75|-Retries|2|-Workers|1|-StubEmbedDelayMs|343|-StubChatDelayMs|6970|-StoreSource|pre-reconcile|-EngineLaunch|worktree:D:/Repos/lancet-oi02-drive-era|-HarnessFrom|worktree:D:/Repos/lancet-oi02-drive-era|-GatewayFrom|worktree:D:/Repos/lancet-oi02-drive-era"
```

This is a **store-matched** arm (pre-reconcile copy, same store production ran on), so per the
plan's M1 rule its slice-0 RetrieveHybrid median compares **directly** against
`m1_reference_ms` (4,910.5 ms), band 2,455.25-9,821 ms -- NOT the ratio-based reconciled-store
formula `primary-r2` used.

**Do not build anything, run any other agent, or start any other soak while this runs.**

Poll the done marker (`<LogDir>\drive-era.done`), never read `drive-era.out.log` while the
process is still running (gotcha #2). Once done:

```bash
uv run --project eval python -m lancet_eval.oi02 check-arm \
  .planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/replay/pre-fix/drive-era \
  --min-records 150
```

Then read `replay/pre-fix/drive-era/summary.json` for `m1`/`m2` (same fields as primary-r2's,
now with `growth_check_slice_ms`/`last_slice_ms` both present post-bugfix). **Task 4's own
verdict classes are scaled to 150 records, not Task 2's 350-record thresholds** -- re-read the
plan's Task 4 action text ("Rules for every arm") before classifying: "grows" is slice-2 at
>=1.5x slice-0 with window delta >=500ms; "not grows" is slice-2 under 1.2x with window delta
under 500ms; otherwise ambiguous (extend to 350 records once if ambiguous, per the plan).
`classify_m2`'s `growth_index = min(3, len(slices)-1)` already resolves to slice-2 automatically
for a 3-slice/150-record arm (index 2 = last available), and the "last full slice" read is also
slice-2 for this arm scale -- the two checks coincide here, unlike the 350-record primary scale.

## Next steps after `drive-era` completes

1. `check-arm --min-records 150` (above), then read `summary.json`.
2. **If it grows:** per Route B step 2, run the HEAD engine with the pre-reconcile store
   (worktree harness and gateway, per the "Pre-reconcile store arms" rule) to separate code
   from store: `-EngineLaunch cargo-debug` (or `debug-exe` pointing at HEAD's own pre-built
   `engine/target/debug/engine.exe`) with `-HarnessFrom worktree:... -GatewayFrom worktree:...`
   still, `-StoreSource pre-reconcile`. If growth persists with HEAD engine, the pre-reconcile
   STORE is implicated -- find which environment factor HEAD code needs to grow (Route A's
   default order: obs-off, stderr sink, console-only telemetry, release, retries0, unpaced,
   gateway telemetry off). If growth disappears with HEAD engine, CODE is implicated --
   `git bisect` between `drive_era_commit` and the plan base (`forensics/plan-base-commit.txt`)
   with 150-record steps, unpaced if the ordinal test allows. Label each bisect arm `bisect-
   <sha7>`. If bisect finds the commit that removed growth, name the mechanism under Route A's
   criteria using the toggle pair `<sha>^`/`<sha>`, set `removed_at: <sha>` in
   `### Named mechanism (07)`, and set `REPRODUCING_ARM` to a HEAD-code arm in the growing
   arm's environment but on the RECONCILED store + HEAD harness (drive 1's actual conditions).
3. **If it does not grow (or ambiguous, extended to 350 and still ambiguous → not reproduced):**
   per Route B step 4, test each of these at most once, then STOP (reachable only in Route B):
   the pre-warm reading (N prior queries per Task 1's forensics -- check `forensics.json`'s
   `fresh_process`/prior-query-count fields for the warm-up size), stub pacing to production's
   per-slice GenerateAnswer/embedding medians, and the journaled real variants (confirm the
   replay's per-record text/variant set equals production's; re-run with journaled variants
   injected if any differ). Then write `### What remains untested (07)` -- growth still counts
   as reproduced-for-free only if Route A's arms found it; here it means Route B could not
   reproduce it either, so Task 5's options should NOT include a "growth reproduced" framing.
4. Either way, write `### Bisection (07)` (one row: drive-era, factor="whole stack", reference
   arm=primary-r2, n, slice medians, verdict, key counter slope) and continue per whichever
   branch above applies. Update `### Starting gap (07)` too -- this arm is store-matched, so if
   its M1 reads "met" (slice-0 within the 2,455-9,821ms band), that alone would be strong
   evidence the starting gap is a STORE or DRIVE-ERA-CODE factor, worth flagging prominently
   even before growth is resolved.
5. **Cap: at most 10 arms total in Task 4** (this drive-era arm is the first). Track the count.
6. **Stop at Task 5** with the structured `checkpoint:decision` (`gate="blocking"`) per the
   plan's own `<context>` block -- do not choose an option. The paid-replay pre-authorization
   (cap $0.25, `--stage-cap 0.25`) is recorded in `06.3.4.1-HANDOVER.md`; restate it at the
   checkpoint, prefer presenting it over running it yourself unless routing makes it the only
   remaining step.
7. Do not write a plan-level SUMMARY.md at Task 5 (mid-plan). STATE.md via `state.record-session`
   only, describing the checkpoint -- no `advance-plan`/`update-progress`.
8. If context fills again: update this file at the next clean committed point (after an arm's
   write-up is committed, never mid-arm), commit it, return a `## HANDOFF` message.

## Reminders carried forward (still true, don't re-discover)

All ten gotchas from the original `07-HANDOFF.md`, plus #11 (JournalWriter always appends --
never reuse a `-Label` that has run before without clearing its output first) from the prior
continuation handoff, still apply verbatim. New this session: the scratch-DB naming fix above,
and the worktree-support contract in `scripts/oi02-replay.ps1` (`42199e73`) -- pre-built
artifacts only for any `worktree:<path>` component (engine binary, gateway binary, synced
`eval/.venv`), same as HEAD's own `-SkipEngineBuild $true` default.

`config_toml_at_drive_time` is still `"unknown"` in `forensics.json`. The `drive-era` arm
above is the FIRST arm in this plan to actually read the drive-era commit's OWN
`config/config.eval.toml` (which had an explicit `[engine.workflow]` timeout block at that
commit, removed at HEAD as a no-op cleanup per `33e774bd`'s successor commits) -- this is
disclosed as part of "whole code delta" fidelity, not a new fidelity gap.
