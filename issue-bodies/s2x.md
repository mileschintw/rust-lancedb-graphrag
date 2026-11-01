Owner decision 2026-11-01 (coordinator session): "好，執行三個 reader K=2 跟補跑deepseek".

## Why

S2 (PR #142) kept deepseek as the reader. A post-hoc split of S2's records by whether every gold fact is in the reader's context (strict span match, `metrics.gold_contained`) shows the Claude readers lose almost only by abstaining when evidence is partial:

| S2, small store | evidence complete (31 G) | evidence partial (59 G) | abstain, partial |
|---|---|---|---|
| deepseek | 0.890 | 0.834 | 13.2% |
| Haiku 5.5 | 0.806 | 0.634 | 25.4% |
| Sonnet 5.5 | 0.935 | 0.715 | 25.4% |
| Opus 5.5 | 0.968 | 0.749 | 21.7% |

Every Sonnet and Opus loss to deepseek is a yes/no question with partial evidence. S1's merged store (`merged/hybrid+rerank+metadata`) gives complete evidence on 42 of 90 G questions instead of 31 (about 3x the context words).

## Ask

An **exploratory** reader run on the merged store. It decides nothing and changes no S2 or S3 decision.

- Source: S1's run of record `eval/runs/2026-10-31-s1-multihop_rag_s1_dev`, arm `merged/hybrid+rerank+metadata` (replicate 1 carried).
- Readers at K=2: Haiku 5.5, Sonnet 5.5 and Opus 5.5, plus deepseek replicate 2. Each reader uses its S2 transport and thinking config, so it compares with S2 directly:
  - Haiku: batch, thinking off.
  - Sonnet: OpenRouter sync with `between_tools` (D-280).
  - Opus: batch at effort low.
  - deepseek: sync, pinned as in D-278.
- Dev only, with no held-out read.
- Write the predictions down before the paid run:
  - Every Claude reader abstains less on the questions whose evidence goes from partial (small) to complete (merged).
  - Sonnet and Opus close the gap to deepseek on merged.
- Report, per reader and per store (S2 small vs this run merged):
  - `answer_usable` and the abstention rate, split by evidence complete/partial and by yes/no vs open questions;
  - reasoning_tokens;
  - spend.
- Estimate about $7 (Sonnet sync about $3.5, Opus about $3.4, Haiku about $0.08, deepseek about $0.02); ceiling $15.

## Files

- New: `eval/corpora/multihop_rag_s2x_dev.toml`
- `eval/src/lancet_eval/thresholds.py` › a new pre-registration constant for this run (D-73 freeze commit; `PREREGISTRATION_S2` is never edited)
- New: run dir under `eval/runs/` (its name must pass `test_journal.py`'s lever-run exemption)
- New: `experiments/v1.1/EXPLORE-S2-MERGED.md` (predictions, then result)
- Tests for the new corpus and pre-registration, as S2 has
