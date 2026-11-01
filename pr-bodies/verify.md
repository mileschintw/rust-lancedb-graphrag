## Summary

Four free checks from the literature novelty check, ahead of the write-up. Each new module reads committed files only and decides nothing.

```text
eval/src/lancet_eval/
├── constant_baseline.py   # #165: "Answer: Yes" / "Answer: No" scored by answer_usable, per pool
├── paired_ci.py           # #168: exact sign-flip p, inverted permutation CI, bootstrap, normal, per K
├── official_scorer.py     # #166: MultiHop-RAG's qa_evaluate.py (loaded from a path) vs answer_usable
└── relation_precision.py  # #169: sample extra relations, cheap OpenRouter judge, report
experiments/v1.1/
├── EXPLORE-S2-MERGED.md        # always-Yes 0.661 beside the yes/no table
├── EXPLORE-C-MHR-FULL.md       # always-Yes 0.537; permutation CIs; official-scorer section
├── EXPLORE-B-2WIKI-READERS.md  # +14.0 read three ways, K=1 vs K=2 rows
├── WRITER-PILOT.md             # precision of Haiku's extra relations
└── relation-precision/sample.jsonl  # the 150 judged relations
```

Findings:

- **#165:** always-Yes scores 0.661 on the D-237 dev pool (37 Yes / 19 No; S1, S2, S2X, S3M). On #149 C's fresh dev it scores only **0.537** (287 / 247). The "about 0.66" holds only for the 100-question pool. It agrees with `answer_kinds`' better constant (C's table shows 0.538 because it counts answers, not questions).
- **#168:** the 2Wiki Opus +14.0 interval was already a question-level bootstrap. Exact sign-flip p = 1.5e-05, permutation CI [+7.5, +20.5], bootstrap [+8.0, +20.5]. Paired with a single deepseek replicate (K = 1 on both sides), the lower bound stays above +7. C's intervals barely move (Opus +5.0, permutation [+2.3, +7.7]).
- **#166:** the official scorer is a whitespace-token overlap with no abstention case. An "Insufficient information" answer to an answerable question scores 0, the same as `answer_usable`. The two disagree only on punctuation (`Yes,` and `Google.`), which drops Sonnet below deepseek on C (0.743 against 0.756). Scored on the whole answer, it passes 9–37% of abstentions.
- **#169:** in a sample of 100 chunks, one extra relation each, Haiku's extras are 0.85 supported by the agent's writer-hidden labels and 0.91 by Llama 3.3 70B. deepseek's extras (the control) score 0.78 and 0.90. Judge cost about $0.003 of OpenRouter credit; no Claude credit.

## Evidence

- **Before:** the literature check flagged the always-Yes 0.66 as an unchecked count, and the 2Wiki +14 as needing a permutation or bootstrap interval.
  **After:** `python -m lancet_eval.constant_baseline --corpus multihop_rag_s2_dev --corpus multihop_rag_full_dev` → 0.661 / 0.537. `python -m lancet_eval.paired_ci --journal eval/runs/2026-11-01-explore-b-twowiki_s3b_dev/journal.jsonl --corpus twowiki_s3b_dev` → `opus-5.5 - deepseek | 100 | +14.0 | 1.5e-05 | [+7.5, +20.5] | [+8.0, +20.5] | [+7.6, +20.4]`.
- `uv run --project eval pytest -n auto --dist loadfile`: 3201 passed, 25 skipped. Ruff `--preview` is clean on the new files.

## Merge Danger

**Door:** two-way

The change adds new modules and Result text only. No existing code path, constant or committed run file changes.

**Blast Radius:** none

Result sections gain lines; frozen pre-registration text is untouched.

## Review

- Spec, blocker, handled: #169's "scaled to the pools" line multiplied a per-chunk precision by relation counts. Removed. The text and the docstring now say the precision is a mean over chunks.
- Spec, handled: the agent's labels were called "by hand". They are now "agent, writer hidden" (Claude Opus 5.5, not a human).
- Spec, handled: #166's wording said `official_scorer` runs the official `main`. It now says the per-reader rates call `extract_answer` and `has_intersection`, and that `main` reproduces the pooled accuracy.
- Standards, handled: the cost formula was written twice, so it now has one `usd()` helper. Added the missing docstrings in `relation_precision`.
- Standards, left as notes:
  - private helpers are used across modules (`metrics._ANSWER_LINE`, `writer_pilot._relation_pairs`/`_norm`); the repo has precedent for this.
  - `paired_ci.usable_by_replicate` repeats `explore_readout`'s loop shape.
  - the new CLIs take `--journal` where `explore_readout` takes `--run`.
  - `precision(rows, judge: str)` picks the field with `getattr`.
- Spec, scope notes left: #169 also judged a deepseek control sample; #166 also scored the whole answer and the null answers; #165's Result additions run two to three lines rather than one.

Closes #165
Closes #166
Closes #168
Closes #169

🤖 Generated with [Claude Code](https://claude.com/claude-code)
