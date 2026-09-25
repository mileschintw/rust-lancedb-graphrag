# Plan 06.3.4.1-07 Executor Handoff

Written because the previous executor's context window filled up mid-Task-2. This is a
mid-task handoff, not a plan-level pause (Task 3 is a checkpoint, not reached yet).

## What's done, with commits

HEAD at handoff time: `368bb20d`.

**Task 1 (complete, committed):**
- `c3ad4748` test(06.3.4.1-07): RED for OI-02 journal forensics
- `18a80183` feat(06.3.4.1-07): GREEN — `oi02.py forensics` (journal_timeline, slice_table,
  hidden_gaps, idle_recovery), ranked hypotheses in the profile
- `351146fe` fix(06.3.4.1-07): corrected 4 evidence errors found on self-review (per-arm
  ExtractGraphContext mislabeling, prior_query_count 1→2, retrieve_timeout_ms downgraded to
  "unknown" with both candidates disclosed, added the Loki log-volume/WARN-ERROR check and a
  new telemetry/logging hypothesis)

Task 1's `<verify>` re-run clean at handoff time. `forensics.json` and the profile's
`## Full-pipeline diagnosis (07)` section are final and should not need further edits.

**Task 2 (in progress — tooling built and smoke-verified; primary replay NOT started):**
- `e739fe49` test(06.3.4.1-07): RED for provider_stub.py
- `ae5a3153` feat(06.3.4.1-07): GREEN — provider_stub.py, engine instrumentation
  (`db::lance_session_stats`/`lance_session_approx_num_items`, `service::emit_request_process_state`,
  `main.rs` telemetry_mode line, `retrieval_soak --export-embeddings`)
- `87f33e87` test(06.3.4.1-07): RED for replay-summary/check-arm
- `92cf84a5` feat(06.3.4.1-07): GREEN — `oi02.py replay-summary`/`check-arm`/`classify_m1`/`classify_m2`
- `368bb20d` feat(06.3.4.1-07): `scripts/oi02-replay.ps1` (+`-launch.ps1`, `-sampler.ps1`),
  verified via a real 2-question smoke run against the reconciled store copy — full commit
  message documents ~9 real Windows/PowerShell deviations found and fixed while getting the
  smoke run clean (see below, don't re-discover these).

All Python tests green: `uv run --project eval pytest eval/tests/test_oi02.py
eval/tests/test_oi02_replay.py eval/tests/test_provider_stub.py -q` → 68/68. Full eval suite
640/641 (the one failure is the pre-existing, already-documented `sys.flags.optimize`
interpreter-flag artifact, unrelated to this work). Rust: `cargo test --manifest-path
engine/Cargo.toml --locked` clean, `sh scripts/engine-test-targets.sh` unchanged at 540.

**Not yet done:** the store-matched soak baseline (`retrieval_soak --arm W --iterations 50`
against `data/lancedb-replay/`, → `replay/pre-fix/soak-baseline.json`), and the primary replay
itself (`-Label primary -Questions 175`, 350 records). Task 2's `<verify>`/acceptance criteria
are NOT yet met — the primary hasn't run.

## Uncommitted state

None. `git status --short` is clean at handoff. `data/lancedb-replay/` (store copy) and the
`lancet_replay` scratch database both exist on disk/in Postgres and are gitignored/expected —
reuse them, don't recreate.

## Running background processes

**None.** No engine, gateway, stub, or sampler process is running. Ports 50051/8080 are free
(confirmed via `Get-NetTCPConnection` immediately before writing this handoff). No PID to
track, no log to poll for an in-flight run.

## Exact next steps

1. **Run the project_root_pin guard** (per your own dispatch prompt) before touching anything.
2. **Build fresh binaries once, in a normal foreground shell** (never let `oi02-replay.ps1`
   build inline — see gotcha #1 below):
   ```
   CARGO_BUILD_JOBS=4 cargo build --manifest-path engine/Cargo.toml --locked --bin engine
   CARGO_BUILD_JOBS=4 cargo build --manifest-path engine/Cargo.toml --locked --bin retrieval_soak
   cd gateway && go build -o gateway-replay.exe . && cd ..
   ```
3. **Store-matched soak baseline** (fast, ~1-2 min): run
   `engine/target/debug/retrieval_soak.exe --arm W --iterations 50 --lancedb-path
   data/lancedb-replay` (the store copy already exists — reuse it, do not delete
   `data/lancedb-replay/` first). Record its RetrieveHybrid median as `soak_w_ms_reconciled`
   in `.planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/replay/pre-fix/soak-baseline.json`
   (a flat JSON object with that one key is enough — `replay-summary`'s M1 code reads exactly
   that key). `oi02-replay.ps1` itself never runs this step; it's a separate direct
   invocation per the plan's own Task 2 action text.
4. **Primary replay** (this is the long one — plan text estimates ~30-60 min per arm; if
   growth reproduces at anywhere near production's rate this could run for HOURS, per
   `forensics/timeline.json`'s own production wall-clock — the first 350 production records
   took 7.25 real hours. Launch it in the background and poll; do not block a foreground
   shell call, which caps at 10 minutes):
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/oi02-replay-launch.ps1 `
     -LogDir "<some temp dir>" -RunName primary `
     -ReplayArgsJoined "-Label|primary|-Phase|pre-fix|-Questions|175|-Retries|2|-Workers|1|-StageCap|1.00"
   ```
   (Stub delays default to 0 in the script; the plan wants them set to
   `forensics.json`'s `stub_delay_defaults` — embedding_ms=343.5, chat_ms=6970.5 — so add
   `-StubEmbedDelayMs|343|-StubChatDelayMs|6970` to the joined args before launching, unless
   you have a reason to deviate and disclose it.)
   Poll the launcher's `-RunName primary` done-marker file (`<LogDir>\primary.done`) — do
   NOT read the `.out.log` file while the process is still running (see gotcha #2). Once the
   done marker exists, read the log, then check `header.json`/`summary.json`/`check-arm
   --min-records 350` in `replay/pre-fix/primary/`.
5. Read M1/M2 from `replay/pre-fix/primary/summary.json`, write up
   `### Full-stack replay (07)` in the profile (fidelity table, M1/M2 readings, process/
   session-cache trends, live-store-untouched proof), commit as the Task 2 GREEN completion
   commit (this is still part of the existing Task 2 `feat` sequence — a new commit, not an
   amend).
6. **Then STOP at Task 3** exactly as the original dispatch specified: return the structured
   `checkpoint:human-verify`... no — Task 3 is `type="checkpoint:decision" gate="blocking"`.
   Present M1 (ratio, both references, met/not met) and M2 (grows/not grows/ambiguous) with
   the committed `flatness_verdict` beside them, the fidelity table, the top of `### Ranked
   hypotheses (07)`, and the proposed route + first 3-5 arms — per the checkpoint's own
   `<context>` block in the PLAN.md. Do not choose an option. Do not write a SUMMARY (Task 3
   is mid-plan, not plan-end). Update STATE.md only via `state.record-session --stopped-at
   "06.3.4.1-07 Task 3 checkpoint (decision)"` — do not run `advance-plan`/`update-progress`.

## Deviations and decisions already made (don't re-litigate)

All of these are explained in full in commit `368bb20d`'s message — short version:

1. **Never let `cargo build`/`cargo run`/`go run .`/`uv run python` execute inline inside
   `oi02-replay.ps1`'s own detached process tree.** `cargo run`/`go run .`/`uv run` all spawn
   a child process for the real long-lived binary; killing the wrapper's PID at teardown does
   NOT kill that child on Windows (repeatedly leaked orphaned `gateway.exe`/`python.exe`
   processes still holding ports). Fixed for engine, gateway, and the stub by building/
   resolving the artifact once and execing it directly (`engine/target/debug/engine.exe`,
   `gateway/gateway-replay.exe`, `eval/.venv/Scripts/python.exe`). `-SkipEngineBuild` defaults
   to `$true` — **you must pre-build the engine binary yourself** before launching (step 2
   above), or the script throws.
2. **Never read a `*> $log` -redirected file while the writer process is still running.**
   Windows/.NET buffered I/O produces genuinely torn/corrupted reads on a file another
   process has open for writing. Every "corrupted log" symptom hit during Task 2 traced back
   either to this (read-while-writing) or to gotcha #3 below — NOT to cargo/docker's own
   progress-bar output, despite several rounds of chasing that theory first. Poll the
   `.done` marker file's existence, then read the log only after it exists.
3. **The launcher's catch block must log `.Exception.Message`/`.ScriptStackTrace` as plain
   strings, never `$_ | Out-String` on the whole ErrorRecord.** PowerShell 5.1's default
   error-record formatting can include ANSI/VT100 sequences that corrupt a captured log.
   Already fixed in `scripts/oi02-replay-launch.ps1` — if you write any NEW wrapper script
   around `oi02-replay.ps1`, carry this forward.
4. **`docker compose` (any subcommand) also corrupts a captured log in this detached
   context**, even with `--ansi never --progress plain`. `oi02-replay.ps1` now uses
   `docker start`/`docker stop` on the five named containers directly instead — this assumes
   the containers already exist (true in this environment; they were created once via
   `docker compose up` previously). If you ever need to run this against an environment
   where the containers don't exist yet, you'll need to bring back a `docker compose up -d`
   call — expect it to corrupt the log again and route its own output to a discarded file
   independently (not through this script's main stream) rather than fighting the ANSI flags
   further.
5. **`Start-Job` produced zero samples for an entire run** in this detached tree (root cause
   not found). The process/TCP sampler now runs as `scripts/oi02-replay-sampler.ps1` via
   `Start-Process`, matching every other long-lived child in this script.
6. **OTLP connection sampling is `-State`-unfiltered** (not just Established) — a 5-second
   point sample missed short gRPC export bursts even though Loki independently confirmed the
   collector received engine telemetry throughout the same window. Don't narrow this back to
   Established-only without re-checking against Loki first.
7. **`stub-stats.json` is queried from `/__stub/stats` BEFORE killing the stub process**, not
   after (querying after always reads zeros — the earlier ordering silently zeroed out every
   count).
8. **LanceDB manifest filenames in this store are NOT small sequential integers** —
   `Get-LiveStateSnapshot` fingerprints via `(latest manifest filename as a string, manifest
   count)`, not a parsed `[int]` version (which overflowed).
9. **pg_dump/restore goes through `cmd /c` `<`/`>` redirection, never PowerShell's
   `Get-Content`/`Out-File`**, which corrupts embedded control characters inside JSON COPY
   data.
10. **`document_reconciliation_intents` has no `status` column** — it's `desired_status`,
    constrained to `'failed'` only; the "pending count" query is just `select count(*)` (row
    existence alone means pending).

## Known limitation, disclosed not fixed

`check-arm`'s `--same-config-as` field set and the full `check-arm` pass were only exercised
against the **smoke** arm (2 questions), not yet against a 150+/350-record arm. If something
about record volume changes behavior (e.g., the harness's own stage-cap or retry timing),
re-verify `check-arm` against the primary once it completes — don't assume the smoke pass
guarantees the primary passes too.

## Config decisions still open (carried into Task 3, not resolved by Task 2)

- `config_toml_at_drive_time` is recorded as `"unknown"` in `forensics.json` (see Task 1's fix
  commit `351146fe` for the full contradiction). The primary replay above uses whatever
  `config/config.toml`/`config.eval.toml` are checked out at HEAD (currently the WIDE
  06.3.3-derived-budget values, since `33e774bd` is already committed) — this is a disclosed
  fidelity gap against an unresolved historical fact, not a resolved match to production.
