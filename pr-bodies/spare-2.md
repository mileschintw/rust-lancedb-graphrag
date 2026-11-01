## Summary

Each arm now scores its chunk-ID retrieval metrics (Hits@4/@10, MRR@10, MAP@10, all-gold@4) against its own store. Before, every arm was scored against the v1.0 gold-chunk table and its chunk size, so a merged-store arm (D-251) read 0.

```diff
 gold sets for a record (score, compare-levers)
-  v1.0 gold-chunk table, for every arm
+  arm on the v1.0 store (unprefixed, small/)  -> the gold-chunk table, as before
+  arm on another store, with --chunk-text     -> sets built from that store's chunk text
+  arm on another store, without one           -> not evaluable (left out, as #125)
 chunk size for coverage / Recall@4 / nDCG@10
-  run-wide config.chunk_size
+  the arm's own [stores.<prefix>] size (o200k tokens for structure-merge)
```

A store's gold sets come from an `inspect_lancedb --chunk-text` dump of the chunks its arms ranked. There is one set per non-empty evidence fact. A set holds the ranked chunks whose text contains the fact under `metrics.gold_contained`, with the D-276 folds. Every chunk-ID metric reads only ranks 1–10, so matching against the ranked chunks gives the same value as matching against the whole store.

```text
lancet-eval chunk-ids --run RUN --store merged --out ids.jsonl     # prints the index_generation
inspect_lancedb --chunk-text ids.jsonl --generation lance-N --out dump.jsonl --lancedb-path <store>
lancet-eval score --run RUN --chunk-text merged=dump.jsonl
lancet-eval compare-levers --run RUN --chunk-text merged=dump.jsonl
```

```text
eval/src/lancet_eval/
├── store_gold.py         # new: dump reader, per-store gold sets, StoreGold, coverage_inputs (moved from #125)
├── score.py              # four-arm and script-faithful chunk-ID cells per store; per-arm chunk size
├── lever_comparison.py   # secondaries and hit4 per store
└── cli.py                # --chunk-text on score and compare-levers; new chunk-ids
```

`comparison.py` needs no change: `compare` already refuses store-prefixed arms. Only an arm on the v1.0 store needs a row in the gold-chunk table, so a run on the full 609-document stores with fresh questions passes that check. #164 still blocks such a run, because `score` always loads the v1.0 document map.

Closes #128

## Evidence

- **Before:** S1 dev run (`2026-10-31-s1-multihop_rag_s1_dev`): merged `paper_hits_at_10` = 0, against small's v1.0 chunk IDs.
  **After:** the same run re-scored on a copy with a read-only dump of `data/lancedb-eval-s1` (703 of 703 ranked chunks found):

  | 90 dev G questions | small/hybrid+rerank+metadata | merged/hybrid+rerank+metadata |
  |---|---|---|
  | Hits@4 | 0.900 | 0.900 |
  | Hits@10 | 0.956 | 0.967 |
  | MRR@10 | 0.773 | 0.746 |
  | MAP@10 | 0.409 | 0.407 |
  | all-gold@4 (compare-levers) | 0.244 | 0.267 |

  Without a dump, the merged cells are left out (not evaluable), and every small-store figure is identical with or without one.
- **The matching rule against the committed table:** on the v1.0 lever run with the existing v1.0 dump (`data/heldout-crosscheck-levers/2026-10-10`), the gold sets built from text equal the table on 803 of 804 evidence units over the ranked chunks. The remaining unit is a text-rule match the ID table lacks. Across 2,156 records, Hits@4, Hits@10 and MRR@10 never differ; MAP@10 differs on 4 records.
- **v1.0 figures unchanged:** the v1.0 lever run of record, re-scored on copies with this branch and with `origin/main`, gives identical `report.json` dimensions (306) and an identical `lever-comparison.json` payload. Against the recorded report, only `gold_containment` and `gold_containment_delta` differ, which is #152's existing D-276 drift (not fixed here). `test_the_v1_0_lever_run_re_scores_and_re_compares_unchanged` therefore fails the same way it does on main.
- **Tests:**
  - `test_store_gold.py` (13): matching with the D-276 folds, empty and unmatched facts, a missing ranked chunk, the digest check, per-store resolution, dump keys, `chunk-ids`, mixed generations, CLI pass-through and a store named twice.
  - `test_score_store_gold.py` (6): merged cells left out without a dump; merged scored from its own text with a dump; a missing chunk refused; per-store coverage chunk size; a store question with no record scored as a miss; a non-evaluable reference arm drops its deltas.
  - `test_lever_comparison_stores.py` (+2): merged secondaries evaluable with a dump; a short dump refused.
  - Fast tier: 3206 passed, 14 skipped. Four tests failed on a loaded machine (git timeouts and a cargo target check); all four pass when rerun alone.

## Review

Round 1 (code-review: Standards and Spec):
- **Blocker, fixed:** the script-faithful line passed `[]` gold to `paper_question_scores` for a question a dump-built store never ranked, and it raised. It now scores that question with all-unmatched units. Test added.
- **Blocker, fixed:** missing tests for per-store coverage chunk size through `score`, the delta guard for a reference arm with no gold sets, a store named twice in `--chunk-text`, mixed generations in `chunk-ids`, and `score --chunk-text`. All added.
- **Note, fixed:** evidence units now skip empty facts, as the gold-chunk table's probe does.
- **Note, fixed:** the copied `store_chunking` and v1.0-store predicate became shared helpers, and the reformat-only hunks were reverted.
- **Note, left:** `lever_comparison._coverage_inputs` is now a thin pass-through. It stays as the module's call site.
- **Note, left:** the test helpers import `_excerpt` / `_build` from other test modules, as the suite already does elsewhere.
- **Note, left:** a dump's generation is not checked against the run. The `chunk-ids` command prints the generation to pass to `--generation`.
- **Note, left:** `graph_ablation_delta` still uses the run-wide chunk size. It pairs only unprefixed (v1.0-store) arms.

Round 2 (the fix commit): no blocker. Two latent notes remain, with no case in today's question files: a whitespace-only fact is dropped here but kept by the Rust probe, and a question whose facts are all empty.

## Merge Danger

**Door:** two-way

Offline scoring only. Without `--chunk-text`, a v1.0-store arm scores exactly as before. A store-prefixed arm's chunk-ID cells change from a false 0 to "not evaluable".

**Blast Radius:** scoring

A re-score of an existing S1/S2 run changes its merged-store chunk-ID cells from 0 to absent, or with a dump to their real values. Coverage, Recall@4 and nDCG@10 for structure-merge arms now drop gold facts longer than the merged chunk, counted in o200k tokens. The runs of record under `eval/runs/` are not rewritten.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
