# S0 Baseline: pre-registration

Status: pre-registered 2026-10-30, before any S0 data. This file and the constant it cites are committed before the
paid run (D-240, D-253). The **Result** section is filled in after the run and nothing above it changes.

How to run it: [RUN-S0-S1.md](RUN-S0-S1.md), step 3.

## Question

Where does Lancet stand against the MultiHop-RAG paper's own pipeline, on the same models and questions?

The baseline may win today (256-token chunks against Lancet's paragraph fragments). That is the point of measuring
first (PLAN.md › Risks).

## Arms (D-238)

| Arm label | Retrieval | Reader |
|---|---|---|
| `hybrid+rerank+metadata` (reference) | Lancet's shipped default on the v1.0 store `data/lancedb-eval`: hybrid dense + BM25, rerank with `voyageai/rerank-2.5-lite`, evidence metadata, graph off | the engine's live answer |
| `llamaindex` (external, D-247, D-248) | `llama-index-core` 0.14.25, `SentenceSplitter(256, 25)`, dense top 20 with `voyageai/voyage-4-large`, rerank with `voyageai/rerank-2.5-lite`, keep 8, title/source/published_at embedded with the text | the generate-only bin over the arm's context export, with the `evidence_metadata` lever only |

Both arms read with deepseek (`deepseek/deepseek-v4-flash-0731`, D-235) through the engine's packer, strict
`final_answer` schema and `Answer:` rendering, so the reader side differs only by the evidence each arm retrieved.
The external reader's `evidence_metadata`-only lever set matches the shipped default's reader-side levers; rerank is
retrieval-side (D-259). The external arm's pipeline is pre-registered field by field, and every external record must
echo it (D-247).

## Data and held-out budget

- Corpus `multihop_rag_s0_heldout`: the MultiHop-RAG held-out split, 351 questions (308 G, 43 null), split
  `heldout_split.json`, role `heldout`.
- This is **held-out read 1 of 2** in v1.1 (D-237). Confirm is read 2. Exporting the LlamaIndex arm over this corpus
  and driving the Lancet arm over it are both part of this one read; nothing else in S0 or S1 reads held-out.

## Pre-registration constant

`PREREGISTRATION_S0` in [`eval/src/lancet_eval/thresholds.py`](../../eval/src/lancet_eval/thresholds.py). The corpus
names it as `[preregistration] token`, so the D-73 check refuses to score a journal older than the commit that
introduced it, or a tree where its value changed.

## Metrics

- **Primary:** `answer_usable` on the G population (308), paired per question (`pairwise_per_comparison`).
- **Supporting, never tested:** evidence-substring Hits@4 (`evidence_hits_at_4`, D-250) for both arms; context tokens
  (o200k of the exported evidence); latency per arm (the external arm's latency is not comparable end to end).
- **Lancet-only secondary:** chunk-ID Hits@4 (`chunk_id_via_gold_chunks`).

## Decision rule (D-239, D-252, D-261, D-262)

S0 changes no default and does not gate S1. It is the published external claim.

1. One Holm family, m = 1: `llamaindex` against `hybrid+rerank+metadata` on `answer_usable`, exact two-sided paired
   sign-flip test, alpha 0.05.
2. The comparison is evaluable only if at least 0.80 of the 308 G questions pair (complete-case floor). Below it the
   reading is "not evaluable", with p = 1.
3. If Holm rejects, the arm with the higher `answer_usable` **leads**, but only if the null guard read **in its
   direction** passes (D-261):
   - `llamaindex` leads: the guard as `compare-levers` reports it, net abstention drop `b - c` over the null pairs,
     where `b` counts null pairs where the reference abstains and `llamaindex` does not.
   - `hybrid+rerank+metadata` leads: the same null pairs with `b` and `c` swapped, `c - b`.
   - Each direction passes iff at least ceil(0.80 × 43) = 35 null pairs exist and the net drop divided by the pairs
     is at most 0.10.
4. A leader whose guard fails or is not evaluable is reported as "a difference of X points with a failed null guard"
   and no lead is claimed. Without a rejection the reading is "no significant difference" with the paired delta and
   its CI.

Every number is the v1.0 lever reading's (`PREREGISTRATION_06_3_6`): alpha 0.05, guard margin 0.10 and pair
fraction 0.80, complete-case floor 0.80, bootstrap 10,000 with seed 42 for the estimation-only CIs, SC-2 timeout
floor 0.025, rerank tripwire 0.20 after 50 attempts or 5 consecutive degrades (D-262).

## Smallest detectable effect (D-239)

With 308 pairs the exact sign-flip test needs a net margin of about 2√d questions, where d is the number of
discordant pairs. The v1.0 held-out lever comparisons had 37 to 83 discordant pairs. That range puts the smallest
significant difference at 13 to 19 net questions, **about 4 to 6 points** of `answer_usable`, and the difference
detected with 80% power at about 5.5 to 8.5 points. Two arms that retrieve differently may disagree more often than
two Lancet levers did, which moves both figures toward the upper end.

## Run constraints

- Main checkout only, clean tree, at a commit that contains this file and the constant (D-73).
- No `--gate-stage`: `run-external` refuses a gate-stage journal.
- D-258: no mid-run cap. `--stage-cap` is required by the CLI and is set to an unreachable 100 USD; RUN-S0-S1.md
  prints the cost estimate before each paid step.

## Result

Not run yet.
