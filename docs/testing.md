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

- A cold Rust build is not in the budget: about 20 minutes here (`cargo test --no-run`, 1,178 s). Keep
  `engine/target` between runs.
- The Go row before #44 is fast only because the engine was already built: without `-short`, `TestRAGQueryCrossRuntime`
  runs `cargo build` for the `engine` and `seed_rag_fixture` bins, a full build on a cold checkout.
- A test that does not fit belongs in the slow tier. Mark it rather than raising the budget.

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
  `provider_stub` (seam S-C). The first run includes a cold release build.

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
- No job needs a secret, and no job runs under `pull_request_target`.

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
