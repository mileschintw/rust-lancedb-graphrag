# S1 dev-run analysis (read-only agent, 2026-10-31)

Run: `eval/runs/2026-10-31-s1-multihop_rag_s1_dev` (PR #122). The agent recomputed every figure from `journal.jsonl`, `context_export.jsonl` and `questions.diag.jsonl` with `lancet_eval.metrics`, and the results match the report exactly. It read no held-out file. The coordinator spot-checked A1: for mhr-28fcbca6b7c7, `assembled_prompt` is byte-identical on small and small+graph.

## A. Measurement issues

- **A1. Reader nondeterminism at temperature 0.**
  - On 30/90 questions the small graph arm added no graph facts, and its prompt is byte-identical to the reference.
  - On those 30, 5 final lines differ and 3 flip answer_usable: 28fcbca6b7c7, e877f9f62d20, ab4e28055c90.
  - On the merged pair, 38 prompts are identical, 4 final lines differ and none flips.
  - Pooled: usable flips on 3/68 identical prompts (~4%), and some final-line change happens on 9/68 (~13%).
  - 3 of the graph arm's 10 n_neg are noise. On the 60 pairs whose prompts differ, graph is 2 pos / 7 neg, sign-test p = 0.18.
- **A2. answer_usable is lexical.**
  - ab4e28055c90: the reference is credited only because its line says "no lack of functionality". This counts as an n_neg for both comparisons.
  - f0d081eaba78: the merged n_pos is a word-order artifact ("Travis Kelce and Taylor Swift").
  - ad4eee299dc7: the plural "sportsbook" fails on every arm.
- **A3. Merged chunk-ID secondaries are wrong.**
  - paper_hits_at_10, mrr, map and all_gold_at_4 are exactly 0 for merged, because merged chunk IDs are scored against gold chunk IDs from the small store.
  - Text-based all-facts results: @4 merged 24 vs small 22; @8 merged 42 vs small 31.
  - `coverage_at_4` passes the small store's `chunk_size` (500) for the merged arm.
- **A4. evidence_hits_at_4 = 0.9000 on all four arms is real, and the equality is a coincidence.**
  - Each arm has 9 misses, 5 of them shared. Shared: 0acddcd35850, 0af0da5770fc, 134c1c2efb80, 1ba051fc3413, 7795b2d3f09e. Small only: 2387d75b7657, 30a5eba49707, 34a1caf20dde, 595a561a5063. Merged only: 28fcbca6b7c7, 78647ebebd50, 7e7714eeb997, 7f260d0f4e89.
  - The metric's "any one fact" rule saturates: 59% of questions hit at rank 1.
- **A5. No excerpt is truncated** (D-273 works). The longest merged excerpt is 1,484 characters.

## B. Graph harm (small store, 12 discordant pairs, 2 pos / 10 neg)

- 3 negatives are noise from identical prompts (A1).
- 6 look like real harm: 1ba051fc3413, c5df28893fc7, 69c23e400d3e, 7fd38ade9214, d45b677426c8, f5c92e5fce3c. The 7th, a27826d47dc0, comes with a wrong graph edge plus a chunk reorder.
- Patterns:
  - The added facts are mostly irrelevant, and the cited reasoning often supports the gold answer while the final line flips. 3 of the 4 correct→wrong flips went to "Yes". The yes counts are 38 against 34.
  - Junk entities:
    - Month names: the same two November/December edges appear in 3 questions and caused 2 temporal flips.
    - Publisher names: TechCrunch (49) and The Verge (25) are the top entities.
  - Degree capping does not explain the harm.
  - The harm repeats on the merged store for 1ba0, 69c2 and f5c9.

## C. Merged vs small (9 discordant pairs, 4 pos / 5 neg)

- Mostly an abstention reshuffle: 3 abstain→answer and 4 answer→abstain.
- Without the two lexical artifacts the count is 3 pos / 4 neg. Retrieval explains no pair.
- The +4.4 pt final_answer_em is formatting.

## D. Power

The test is an exact sign test, n = 90, at 80% power.

| Discordant rate | MDE at α = 0.05 | MDE at α = 0.025 |
|---|---|---|
| 10% | ~9.5 pt | ~10 pt |
| 13% | ~11 pt | ~12 pt |

- Merged's "no difference" is uninformative: the CI is [-7.8, +5.6], and the noise floor accounts for about half its discordants.
- The graph call points the right way but is weaker than 2 vs 10 suggests. Power for the observed 8.9 pt is about 0.46-0.57.

## E. Merged + graph (descriptive)

- 75/90 usable. Against merged: 2 pos / 5 neg, all on questions where the prompt changed.
- The same month and publisher junk edges appear, so the problem is in graph extraction or seeding.

## F. For S2 (replaying small/hybrid+rerank+metadata)

1. Expect ~4% usable flips with identical prompts. Consider 2-3 replicates or a noise-floor estimate before reading small deltas.
2. Lexical scoring penalises paraphrase and word order. Readers that format differently may gain or lose for non-substantive reasons.
3. Some questions fail on every arm: 0acddcd35850, 30a5eba49707, 595a561a5063, plus ad4eee299dc7 on the plural alone.
4. Abstention is the main source of reference errors: 4 of its 11 errors. Reader choice will likely move the abstain/answer balance more than accuracy.
5. Fix the chunk-ID secondaries (A3) before another non-small store is reported.
6. The null guards carry no information here: every arm abstains on 10/10 nulls.
