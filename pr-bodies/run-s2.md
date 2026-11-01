Freezes the S2 pre-registration (RUN-S2.md step 4, D-73) before the run of record. This is the commit that adds the
name `PREREGISTRATION_S2` to `thresholds.py`, so D-73 dates the constant by it. From the merge on, the constant is
never edited.

## What changed

- `eval/src/lancet_eval/thresholds.py`: the `PREREGISTRATION_S2` block from EXPERIMENT-S2.md › The constant, pasted
  by RUN-S2.md step 1 with S1's winner `small/hybrid+rerank+metadata` in place of `S1_WINNER_UNSET`. The Sonnet
  reader row is `target="openrouter"`, `thinking="between_tools"` (D-280).
- `eval/corpora/multihop_rag_s2_dev.toml`: the four arm labels carry S1's winner; the `DRAFT` header sentences are
  gone.
- `experiments/v1.1/EXPERIMENT-S2.md`: status is "pre-registered 2026-11-01, before any S2 data"; S1's winner is
  named under Arms.

## Why now

The pilot (RUN-S2.md steps 2 and 3, re-run on `ad8ed74f` after #140) passed every step 3 row: Haiku, Sonnet (sync,
`between_tools`) and Opus 25/25 each through Anthropic with `is_byok` true; Sonnet's `reasoning_tokens` 0; deepseek
20/20 on Wafer; the strict schema accepted by all three readers; `0 replay clause failure(s)`. The pilot run is
deleted, as step 3 says. No S2 data exists yet.

## Checks

- `PYTHONUTF8=1 uv run --project eval pytest -p no:xdist -q eval/tests/test_s2_preregistration.py eval/tests/test_s2_run_guide.py`:
  `22 passed, 1 skipped`.
- `git log --oneline -S PREREGISTRATION_S2 -- eval/src/lancet_eval/thresholds.py` names only this commit.

After the merge, the run lane runs `git switch main`, `git pull --ff-only`, and checks that
`git log --oneline -1 -- eval/src/lancet_eval/thresholds.py` prints "Pre-register S2: ..." and
`git status --short -- eval/src/lancet_eval` prints nothing, before step 5.

## Review

No code review round: the change is the guide's own pasted block, the corpus labels and two status lines, checked by
the S2 pre-registration tests above.

Refs #108

🤖 Generated with [Claude Code](https://claude.com/claude-code)
