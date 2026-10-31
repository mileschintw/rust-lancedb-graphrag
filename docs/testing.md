# Testing: tiers, budgets and CI

The suites run in three tiers (#44). Every lane runs the **fast tier**. The **slow tier** is opt-in and runs before a
merge or in the main checkout. The **live tier** needs PostgreSQL, the live stack or a paid API, and never runs in CI.
Run every command from the repository root.

## Fast tier

The default checks for every lane, and what CI runs. No test in it makes a network call or needs a secret, PostgreSQL,
the live stack or `data/lancedb-eval`.

```bash
cargo test --manifest-path engine/Cargo.toml --locked && sh scripts/engine-test-targets.sh
(cd gateway && go test -count=1 -short ./...) && sh scripts/gateway-test-targets.sh
uv run --project eval pytest -n auto --dist loadfile
```

When a change touches `baselines/llamaindex/` (or the `lancet_eval` code it imports), also run:

```bash
uv run --project baselines/llamaindex pytest baselines/llamaindex
```

- `-count=1` turns off Go's test cache, which could otherwise replay a cached pass for a test that reads the config
  files.
- `-short` skips `TestRAGQueryCrossRuntime`, which builds the Rust engine, and
  `TestRAGQueryClientDisconnectCancelsRustWorkflow`, which runs the bins it builds (slow tier).
- `-n auto --dist loadfile` runs the pytest suite on one worker per core, keeping each test file on one worker
  (pytest-xdist, in the eval dev group). Plain `uv run --project eval pytest` still works; it runs the same tests
  serially.
- The two `scripts/*-test-targets.sh` gates check that every Rust test target and every Go test package still compiles
  in with at least its floor of tests. A target that vanishes, drops below its floor, or appears without a floor
  fails by name. Adding tests needs no edit to either script. Lower a floor only in the commit that deletes or merges
  those tests, and name the tests that now cover them.

### Time budget

The fast tier has a budget of **5 minutes** on a 12-core Windows workstation with a warm `engine/target`, and each CI
job has its own limit (below). Measured on 2026-10-30 (#44), `CARGO_BUILD_JOBS=2`:

| Suite | Before #44 | After #44 | Budget |
|---|---|---|---|
| Rust: `cargo test` run, warm build | 102 s (lib 90 s) | 65 s (lib 50 s) | 2 min |
| Rust: `engine-test-targets.sh`, warm | — | 6 s | — |
| Go: `go test -count=1` (`-short` after), warm engine | 10 s | 3 s | 1 min |
| Go: `gateway-test-targets.sh` | — | 3 s | — |
| Python: `pytest` | 428 s serial, 1 failure | 85 s with `-n auto` (325 s serial), no failure | 3 min |

- A cold Rust build is not in the budget: 20 to 27 minutes here with `CARGO_BUILD_JOBS=2`. Keep `engine/target`
  between runs, and use sccache to share dependency builds between worktrees ([Engine builds across
  lanes](#engine-builds-across-lanes)).
- The Go row before #44 is fast only because the engine was already built: without `-short`, `TestRAGQueryCrossRuntime`
  runs `cargo build` for the `engine` and `seed_rag_fixture` bins, a full build on a cold checkout.
- A test that does not fit belongs in the slow tier. Mark it rather than raising the budget.

## Engine builds across lanes

Lanes build the engine at the same time, each in its own worktree, on one machine (12 logical cores, 32 GB RAM, of
which about 12 GB is free while lanes run). Three settings keep that fast without running out of memory (#56).

### Job count

Set `CARGO_BUILD_JOBS` from how many lanes build the engine at the same time. Briefs and the coordinator's notes copy
this table:

| Lanes building at once | `CARGO_BUILD_JOBS` per lane |
|---|---|
| 1 | 6 |
| 2 | 3 |
| 3 or more | 2 |

- The rule keeps about 6 rustc processes on the machine in total. On 2026-10-29, three or four lanes at the default
  job count (12 each) ran it out of memory: `cl.exe` 0xc000012d, rustc `STATUS_STACK_BUFFER_OVERRUN` and "only metadata
  stub found".
- A lane counts as building while its cargo build or test build runs, not for the whole time it is open. Most of a
  lane's time is editing and test runs, so two or three open lanes rarely all compile at once.
- The higher rows are untested here: the figures below were measured at `CARGO_BUILD_JOBS=2` while other lanes
  built. If a lane runs out of memory at its row's count, drop one row.
- `CARGO_BUILD_JOBS` is not in sccache's cache key (checked: a build at 5 jobs hit what a build at 2 had cached),
  so lanes on different rows still share dependency builds.

### sccache

[sccache](https://github.com/mozilla/sccache) caches each dependency crate's compiled output, so a second worktree
reuses what the first one built. It shares builds across worktrees without a shared `CARGO_TARGET_DIR`, which would
make the lanes wait on each other for cargo's lock on that directory.

Setup, once per machine (Windows):

1. Install it: `winget install --id Mozilla.sccache -e`.
2. Put the cache on a disk with room, in `%APPDATA%\Mozilla\sccache\config\config`. Every sccache server reads this
   file, whichever shell starts it:

   ```toml
   [cache.disk]
   dir = 'D:\sccache'
   size = 42949672960 # 40 GiB
   ```

   `SCCACHE_DIR` and `SCCACHE_CACHE_SIZE`, when set, override the file. A server keeps the settings it started with
   until it stops after 10 idle minutes.
3. Turn it on for every cargo build, in the user's `%USERPROFILE%\.cargo\config.toml`:

   ```toml
   [build]
   rustc-wrapper = "sccache"
   ```

   Keep `rustc-wrapper` out of the repository's `.cargo/config.toml`: CI has no sccache.

Rules for lanes:

- Leave `CARGO_TARGET_DIR` unset, so each lane builds in its own `engine/target`. sccache puts `CARGO_*`
  environment variables in the cache key, `CARGO_BUILD_JOBS` excepted, so a lane that sets one the others don't gets
  no hits from them: a measured second worktree hit 0.5% with `CARGO_TARGET_DIR` set and 63% without it. The same
  holds for the `CARGO_PROFILE_RELEASE_*` variables below: lanes that set them identically share release builds.
- Never run `sccache --stop-server` while another lane builds: its compiles fail.
- `sccache --show-stats` shows the hit rate. Expect about 60% on a second worktree. These never come from the cache:
  the `engine` crate itself (built incrementally), binaries and proc-macro crates, build scripts, and C code that
  build scripts compile.
- Without sccache: run a build with `RUSTC_WRAPPER=` (empty) to bypass it, or skip the setup. Everything works the
  same, only slower.

Undo the setup: remove the `[build]` lines from `%USERPROFILE%\.cargo\config.toml`, delete
`%APPDATA%\Mozilla\sccache\config\config` and the `SCCACHE_DIR`/`SCCACHE_CACHE_SIZE` user variables if set, run
`winget uninstall Mozilla.sccache`, and delete `D:\sccache`.

### Build profile

- `engine/Cargo.toml` builds `dev` and `test` with `debug = "line-tables-only"` (file and line in backtraces) and
  dependencies with no debug info. A cold `engine/target` went from 45 GB to 9.7 GB. CI turns debug info off for the
  `engine` crate too (`CARGO_PROFILE_DEV_DEBUG=0`).
- The repository's `.cargo/config.toml` links with `rust-lld` on Windows; it ships with Rust's
  `x86_64-pc-windows-msvc` toolchain. CI's `x86_64-unknown-linux-gnu` toolchain already uses lld. Cargo reads that
  file from the directory it runs in upward, so run cargo from inside the repository (the commands in this file run
  from the root).

### Integration binary

The integration tier needs the release `generate_from_context`, which the harness builds with `cargo run --release`.
For the tests, build it at `opt-level = 1`, about half the time of a full release build:

```bash
export CARGO_PROFILE_RELEASE_OPT_LEVEL=1 CARGO_PROFILE_RELEASE_INCREMENTAL=true
cargo build --manifest-path engine/Cargo.toml --locked --release --bin generate_from_context
LANCET_EVAL_INTEGRATION=1 uv run --project eval pytest eval/tests/test_run_external.py eval/tests/test_prompt_parity.py
```

- Keep both variables set for the pytest run too, or the harness's `cargo run --release` rebuilds at the full
  `opt-level = 3`. Each switch between the two rebuilds the release binaries.
- The prompt-parity and `provider_stub` tests pass at `opt-level = 1` (45 passed); the optimisation level does not
  change what the engine sends.
- Build eval drives, `inspect_lancedb` and anything you ship without these variables.

### Measurements

Measured on 2026-10-30 and 2026-10-31 (#56), `CARGO_BUILD_JOBS=2`, rust-lld (the machine's own cargo config already
used it before #56). "Other builds" is how many other lanes' cargo processes ran during the measurement (sampled
every 30 s).

| Build | Before #56 | After #56 | Other builds |
|---|---|---|---|
| Cold `cargo test` (build, then run) | 1,605 s (build 25 m 25 s) | 1,430 s (build 22 m 04 s), sccache filling an empty cache | 1 for all of before; 1, and 2 for a quarter of after |
| `cargo test` in a second worktree, sccache warm | same as cold (no shared cache; not re-run) | 991 s (build 15 m 04 s), 63% hits | none for most of it, 1 for a fifth |
| `engine/target` after a cold `cargo test` | 45 GB | 9.7 GB | — |
| Release `generate_from_context` | about 74 min (lanes 14 and 44, #56's issue) | 37 m 17 s at `opt-level = 1` | 0 to 2 |
| Integration tier, bin built | — | 35 s, 45 passed | — |

- The before row for the release build comes from earlier lanes on this machine and was not re-run here.
- CI caches the dependency build with `Swatinem/rust-cache`. #56 changes no CI setting: CI already builds with no
  debug info, which this profile also gives dependencies, so the cached `engine/target` should not grow. Not yet
  observed: no Rust cache had been saved when #56 was measured, because the first `main` run timed out on a test hang
  (#59), so neither the cache size nor a warm CI engine time is known. The PR run of #57 built cold in 16.5 minutes
  (clippy 5.5, `cargo test` build 8). The `Cargo.toml` change gives the cache a new key once; the old entry ages out
  after 7 days.

## Slow tier

Opt-in. Run it before a merge that touches the code these tests cover, or in the main checkout.

```bash
LANCET_SLOW_TESTS=1 uv run --project eval pytest -n auto --dist loadfile
uv run --project eval python -O -m pytest scripts/test_phase02_live_evidence.py
(cd gateway && go test -count=1 ./...)
LANCET_EVAL_INTEGRATION=1 uv run --project eval pytest eval/tests/test_run_external.py eval/tests/test_prompt_parity.py
```

What each command adds:

- `LANCET_SLOW_TESTS=1` runs the pytest tests marked `@pytest.mark.slow` (hook: `eval/tests/slow_tier.py`):
  - `test_score_levers.py::test_the_v1_0_lever_run_re_scores_and_re_compares_unchanged`, the v1.0 lever run of record
    re-scored and re-compared (about eight minutes; it was opted in by `LANCET_EVAL_RESCORE_LEVER_RUN=1` before #44);
  - `test_decay.py::test_restart_discriminator_spans_zero_inconclusive` (12 s);
  - `test_decay_materiality.py::test_contiguous_window_noise_flat_320_records_has_121_windows_and_no_fires` (7 s).
- `python -O` runs `test_wrong_model_is_rejected_in_optimized_isolated_subprocess`, which checks the Phase 2
  evidence helper's refusal with assertions stripped. It needs pytest itself under `-O`, so a default run skips it.
- `go test` without `-short` adds `TestRAGQueryCrossRuntime`, which builds the engine and checks one query across the
  Go and Rust runtimes against a loopback mock provider, and `TestRAGQueryClientDisconnectCancelsRustWorkflow`, which
  runs the bins it built.
- `LANCET_EVAL_INTEGRATION=1` builds the `generate_from_context` bin in release mode and runs it against the loopback
  `provider_stub` (seam S-C). The harness gives each `cargo run --release` 30 minutes, so a cold release build that
  takes longer times the tests out (about 70 minutes here with `CARGO_BUILD_JOBS=2`, 37 minutes at `opt-level = 1`).
  Build the bin first, at `opt-level = 1` ([Integration binary](#integration-binary)); the tests then take about
  30 seconds.

None of them makes a paid call. The v1.0 drive-2 re-score
(`test_score_deterministic.py::test_rescore_of_the_recorded_drive2_reproduces_its_report`) and the held-out
verdict re-reads (`test_recorded_gate_verdicts.py`) stay in the fast tier.

## Live tier

Never in CI, and only in the main checkout (worktrees lack the live store). Each needs something outside the repo:

- Go database tests: `TEST_DATABASE_URL` pointing at a PostgreSQL instance; they skip without it.
- The D-04 cross-runtime fixture: `LANCET_RUN_D04_FIXTURE=1` and its `LANCET_D04_*` variables (driven by the Go
  database tests).
- Rust `#[ignore]` live tests (`live_embedding_returns_shipped_dimension`, `openrouter_structured_output_smoke`): paid
  OpenRouter calls with `OPENROUTER_API_KEY`. Never run `cargo test -- --ignored` or `--include-ignored` without
  meaning to make those calls.
- Eval drives, probes and preflight against the live stack (`eval/README.md`).

## CI

`.github/workflows/ci.yml` runs the fast tier on pull requests to `main` and on pushes to `main`, on Linux. Pushing a
branch without a pull request runs nothing. A `changes` job decides which module jobs run from the changed paths:

| Job | Runs | Triggered by |
|---|---|---|
| `engine` | `cargo clippy --all-targets -- -D warnings`, `cargo test`, `scripts/engine-test-targets.sh` | `engine/**`, `config/**`, `deploy/**`, `scripts/engine-test-targets.sh` |
| `gateway` | `go test -count=1 -short ./...`, `scripts/gateway-test-targets.sh` | `gateway/**`, `config/**`, `scripts/gateway-test-targets.sh` |
| `eval` | ruff on the changed `eval/**/*.py` files, `pytest -n auto --dist loadfile` | `eval/**`, `scripts/**`, `config/**`, `proto/**`, `gateway/atlas.hcl`, `gateway/db/schema*.hcl`, `engine/src/{config,ingest,prompt}.rs`, `engine/src/generation/mod.rs`, `engine/src/workflow/mod.rs`, `docs/api-contract.md`, `docs/observability.md`, `docs/assets/**`, `.planning/**`, `.env.example`, `verify-ingestion.sh`, `verify-live-evidence.sh` |
| `llamaindex` | `pytest baselines/llamaindex` | `baselines/llamaindex/**`, `eval/src/**`, `eval/corpora/**`, `eval/pyproject.toml`, `eval/uv.lock`, `config/**` |
| `ci` | passes when every triggered job passed | always |

A change to the workflow file triggers every job. Any other path triggers none, so a pull request that changes only
docs no test reads runs only `changes` and `ci`.

- The shared paths are the files each module's tests read outside its own directory. When a test starts reading a
  new file outside its module, add that path to the module's filter in `ci.yml` and to this table.
- `main` carries legacy ruff findings, so the ruff step fails only on a rule a changed file has more findings of than
  at the pull request's base commit. A new file must be clean.
- Only pushes to `main` save the Rust build cache. A pull request's cache is scoped to its merge ref and no other run
  can read it, so saving it would only evict `main`'s. Debug info is off in CI to keep `engine/target` inside the
  runner's 14 GB disk and the repository's 10 GB cache.
- Job time limits: `engine` 45 minutes (a cold build after a cache eviction), every other job 10.
- CI environment settings the tests need, found on the first CI run (PR #57):
  - `engine` installs Ubuntu's `protobuf-compiler` and `libprotobuf-dev`. lance's build scripts run `protoc`, and their
    protos import the well-known types (`google/protobuf/empty.proto`), which only `libprotobuf-dev` ships. A local
    build needs both, or a protoc release that bundles its `include/` directory.
  - The eval pytest step sets `_TYPER_FORCE_DISABLE_TERMINAL=1`. Typer forces a Rich terminal when `GITHUB_ACTIONS`,
    `FORCE_COLOR` or `PY_COLORS` is set, and the ANSI codes break the CLI-help assertions. Set it locally too if your
    shell sets `FORCE_COLOR`.
  - The uv jobs set `UV_LINK_MODE=copy`. On Linux uv hardlinks installed files from its cache, and nltk refuses a
    multiply-linked data file.
- No job needs a secret, and no job runs under `pull_request_target`.
- The `eval` job runs the same fast tier as the lanes, including the tests that read committed held-out files offline
  (`eval/corpora/multihop_rag/questions.heldout.jsonl`, the `eval/runs/*heldout*` runs of record, and the v1.0
  held-out re-read in `test_recorded_gate_verdicts.py`). They never send a held-out question to the system, so CI
  makes no D-237 held-out read. The owner allowed this on 2026-10-30 (#44).

### Requiring CI before merge

Making pull requests pass CI before merging is a repository setting, not part of the workflow: in the repository's
branch protection (or a ruleset) for `main`, require the status check **`ci`**. Require only `ci`. The module jobs are
skipped whenever their paths do not change, and `ci` already fails when a triggered job fails.

### Platform limits

Checked against the GitHub docs on 2026-10-30 for this public repository:

- Standard GitHub-hosted runners are free with unlimited minutes for public repositories. The Linux runner has
  4 CPUs, 16 GB of RAM and a 14 GB SSD.
  ([GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners))
- The Free plan runs up to 20 concurrent jobs on standard runners. A job can run for up to 6 hours; a workflow run for
  up to 35 days. ([Actions limits](https://docs.github.com/en/actions/reference/limits))
- The Actions cache holds 10 GB per repository by default. Entries not read for 7 days are removed, and over the limit
  the least recently read go first. A pull request run can restore caches from its own branch, its base branch and the
  default branch; the caches it saves are scoped to its merge ref.
  ([Dependency caching](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching))
- A workflow skipped by a path filter leaves its required checks pending and blocks the merge; a job skipped by an
  `if:` reports success. Hence the single `ci` job instead of path filters on the workflow.
  ([Troubleshooting required status checks](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/collaborating-on-repositories-with-code-quality-features/troubleshooting-required-status-checks))
