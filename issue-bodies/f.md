Owner decision 2026-11-01 (coordinator session): "全部接受" (item F and design principles 1-7 of the coordinator's package).

## Why

S2's analysis showed that `answer_usable` rewards guessing on yes/no questions: constant-Yes scores about 0.66. On partial evidence, deepseek answers anyway, while the Claude readers abstain. S3's pre-registration needs a fixed metric first. The owner also accepted design principles that need D-IDs.

## Ask

1. **Metric:** in `score`/`compare-levers`, report `answer_usable` separately for yes/no and open questions. Also report a guessing-adjusted figure for yes/no: for example balanced accuracy, or the excess over the better constant answer. Pick one and justify it in the D-ID.
   - Never change a frozen pre-registration's decisional metric; the new figures are additions.
   - Also add the evidence-complete/partial split (`gold_contained` on the context; #143 has `evidence_split.py`) as a reported secondary.
2. **D-IDs in `experiments/v1.1/PLAN.md`**, each with the owner's words ("全部接受", 2026-11-01):
   1. Claude writers for large runs; cost rule at list prices; deepseek stays the baseline writer; the default writer is decided after #117.
   2. Opus is the ceiling point; as a reader, K=1 on key cells only.
   3. Per-model K from S2's measured variance: Sonnet and Opus K=1, deepseek and Haiku K=2-3; budget goes to more questions.
   4. Extract once per writer and share each graph across readers.
   5. A pre-registered two-stage design: screen small, then run the finalists in full.
   6. The metric fix above, required before S3's pre-registration.
   7. One held-out read per benchmark, packing every decisional hypothesis into it with Holm. This amends D-237's global count.
   8. Raise the D-246 caps for this credit window, owner: "只要是在合理範圍我們的credit可支付的情況下都直接同意". Per-lane ceilings are set by the coordinator.
   9. The thinking rule confirmed 2026-11-01: the lowest setting each model supports on the Batch API; report each setting and its measured reasoning_tokens.

## Files

- `eval/src/lancet_eval/score.py`, `lever_comparison.py` (reported secondaries only) and their tests
- `experiments/v1.1/PLAN.md` › Decisions (new D-IDs)
