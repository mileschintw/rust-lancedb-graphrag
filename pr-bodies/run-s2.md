Records the S2 run of record (RUN-S2.md steps 5 to 8): the run directory `eval/runs/2026-11-01-s2-multihop_rag_s2_dev`
and EXPERIMENT-S2.md › Result. The finding is that deepseek stays the reader and S3 takes it as the fixed reader.

## What changed

- `eval/runs/2026-11-01-s2-multihop_rag_s2_dev/` contains:
  - the journal: 2,000 records, 500 per arm;
  - the context export;
  - the four batch manifests;
  - `report.json`, `lever-comparison.{json,md}`;
  - `answer-judge.json` and its cache.
- `experiments/v1.1/EXPERIMENT-S2.md` › Result: the choice, counts, the reader table, the null guards, the Holm
  arithmetic, D-245, the thinking setting as run with measured `reasoning_tokens` (the owner's ruling of 2026-11-01),
  the answer judges, the batch IDs and the spend. Nothing above Result changes.

## Result in short

| Arm | answer_usable | Δ vs deepseek | Cost per answered question |
|---|---|---|---|
| deepseek (reference) | 0.853 | — | $0.00024 |
| Haiku 5.5 | 0.693 | −16.0 pts (raw p 4.9e-5) | $0.00097 |
| Sonnet 5.5 | 0.791 | −6.2 pts (raw p 0.061) | $0.0179 |
| Opus 5.5 (descriptive) | 0.824 | −2.9 pts | $0.0329 |

- **Null guards:** every Claude reader's guard against deepseek is NOT EVALUABLE.
  - It got 35 null pairs, against the 40 needed.
  - The cause is 7 deepseek answers that `render` rejected on three null questions (billed, so never retried).
  - So no Claude reader is a candidate, and deepseek wins.
- **Holm, all three readers treated as candidates:** this gives the same pick.
- **D-245:** the switch to Haiku 5.5 does not hold.
- **Spend:** about $14.38, inside the step 6 ceiling. Sonnet's `batch_spend` prints at the batch rate (half its real
  cost); #139 tracks that.

## Checks

- Every arm reached 500 records:
  - Haiku, Sonnet and Opus: 500 successes each.
  - deepseek: 493 successes and 7 render errors.
  - Every Routing line shows 0 misrouted.
- Before `replay-init` and each submit, `git status --short -- eval/src/lancet_eval` printed nothing (D-73).
- `PYTHONUTF8=1 uv run --project eval pytest -p no:xdist -q eval/tests/test_s2_preregistration.py eval/tests/test_s2_run_guide.py`:
  `22 passed, 1 skipped`.
- The judges ran with 0 failed requests. There are 14 disagreements for the owner to review.

## Review

There was no code review round: this PR holds only run records and the Result text the guide asks for.

Refs #139
Refs #108

🤖 Generated with [Claude Code](https://claude.com/claude-code)
