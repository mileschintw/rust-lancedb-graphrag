# S1 Chunking: pre-registration

Status: pre-registered 2026-10-30, before any S1 data. This file and the constants it cites are committed before the
paid run (D-240, D-253). The **Result** section is filled in after the run and nothing above it changes.

How to run it: [RUN-S0-S1.md](RUN-S0-S1.md), steps 1 and 4.

## Question

Do merged chunks of about 256 tokens beat paragraph fragments, and does the graph help on the chunking S1 keeps?

S1 changes chunking and nothing else (PLAN.md › S1 details): same reader (deepseek), same levers (rerank + evidence
metadata), the basic graph context for the graph-on arms (no `graph_v2`).

## Arms (D-251)

| Arm label | Store | Graph |
|---|---|---|
| `small/hybrid+rerank+metadata` (reference) | v1.0 `data/lancedb-eval`, `structure-aware`, 500/50 characters (D-09) | off |
| `small/hybrid+graph+rerank+metadata` | same | basic graph context on |
| `merged/hybrid+rerank+metadata` | S1 `data/lancedb-eval-s1`, `structure-merge`, 256/25 o200k tokens (D-241, D-242, D-251) | off |
| `merged/hybrid+graph+rerank+metadata` | same, with its own deepseek extraction | basic graph context on |

## Data

Corpus `multihop_rag_s1_dev`: the levers-dev question set (`questions.diag.jsonl`, `heldout_split.json` role `dev`),
the D-237 dev pool of 100 (90 G, 10 null) (D-259). No held-out question is read.

## Pre-registration constants

In [`eval/src/lancet_eval/thresholds.py`](../../eval/src/lancet_eval/thresholds.py):

- `PREREGISTRATION_S1`, the corpus token. Reference `small/hybrid+rerank+metadata`; it pairs
  `merged/hybrid+rerank+metadata` (the chunking reading) and `small/hybrid+graph+rerank+metadata` (the small-store
  graph reading) against it.
- `PREREGISTRATION_S1_MERGED_GRAPH`, the merged-store graph reading of the same journal: reference
  `merged/hybrid+rerank+metadata`, paired with `merged/hybrid+graph+rerank+metadata`. The lever comparison pairs
  every family arm with one reference, so this second pairing needs its own constant. It differs from
  `PREREGISTRATION_S1` only in the arm roles (a test pins this). The D-73 check runs on the corpus token.

The family in both constants is `decisional` only because the lever comparison needs one; S1 is direction-finding,
and the `default_decisions` rows of `lever-comparison.json` are not read.

## Metrics

- **Primary:** `answer_usable` on the G population (90), paired per question.
- **Supporting:** evidence-substring Hits@4 (`evidence_hits_at_4`), which matches gold evidence text, so it reads the
  same on both stores. Context tokens per arm.
- **Not reported:** chunk-ID Hits@4. The gold chunks are not re-mapped to merged chunks (PLAN.md › S1 details), so any
  chunk-ID figure the report prints for a `merged/` arm is not read.

## Decision rule (D-252, D-262 to D-264)

Direction-finding on dev. The harness computes the paired deltas, p-values and null guards; the choice is applied by
hand in the **Result** section. p-values are reported and not used.

1. **Chunking.** Adopt merged iff the paired `answer_usable` delta of `merged/hybrid+rerank+metadata` against
   `small/hybrid+rerank+metadata` is **above 0** and that comparison's null guard passes. Otherwise keep small (a delta
   of exactly 0 keeps small).
2. **Graph, on the chosen store only (D-263).** The graph joins S1's configuration iff the paired `answer_usable`
   delta of the chosen store's graph-on arm against its graph-off arm is **at least +0.05** (+5 points) and that
   comparison's null guard passes.
   - Small kept: the `small/hybrid+graph+rerank+metadata` row of `lever-comparison.json` (`PREREGISTRATION_S1`).
   - Merged adopted: the `merged/hybrid+graph+rerank+metadata` row of `lever-comparison-merged-graph.json`
     (`PREREGISTRATION_S1_MERGED_GRAPH`).
   - On 90 fully paired questions, +5 points means a net gain of at least 5 questions (4 of 90 is 4.4 points).
3. **Null guard (D-264).** Margin 0.10 and pair fraction 0.80 on the 10 dev nulls: a guard fails when the net
   abstention drop exceeds 0.10 of the null pairs (2 or more with 10 pairs; 1 or more with 8 or 9), and is not
   evaluable with fewer than 8 null pairs. A failed or not-evaluable guard vetoes the choice it guards.
4. The other numbers are the v1.0 lever reading's (D-262): complete-case floor 0.80, bootstrap 10,000 with seed 42,
   SC-2 timeout floor 0.025. The constants also carry the rerank tripwire (0.20 after 50 attempts or 5 consecutive
   degrades), but the drive applies no tripwire to a dev-role corpus (`run.rerank_tripwire_for`), so it does not act
   in S1.

S1's result is the configuration S2 replays: the chosen store and graph state of the `hybrid+rerank+metadata` arm
(D-254, D-257). The final configuration is confirmed on held-out only in Confirm (D-237).

## Smallest detectable effect (D-237, D-239)

With 90 G pairs, a significant difference needs a net margin of about 2√d questions. For 15 to 30 discordant pairs
that is 9 to 12 net questions, **about 10 to 13 points**. Dev readings can only show large effects; that is why the
rule uses point estimates, not p-values.

## Run constraints

- Main checkout only, clean tree, at a commit that contains this file and the constants (D-73).
- The merged store is a second store; `data/lancedb-eval` and `lancet_eval` are never modified (D-251).
- Each store's arms are driven against their own stack into one journal (`run --arms`, D-251).
- The merged store is built only after #67 merges: until then `seed --store eval-s1` uploads without the store's
  chunking and the gateway falls back to `structure-aware`, so the "merged" store would repeat the v1.0 chunking.
- The S1 store's preflight and identity gate need #69 (the identity check reads only `lancet_eval`).
- The two-store context export needs #65 or the stopgap in RUN-S0-S1.md step 4.
- Scoring needs #68: until it lands, `score` and `compare-levers` read only held-out IDs and refuse a dev-role run.
- `PREREGISTRATION_S1_MERGED_GRAPH` is not the corpus token, so `compare-levers` does not check it; the RUN-S0-S1.md
  recipe runs the same D-73 check on it before reading it.
- D-258: no mid-run cap; `--stage-cap` is set to an unreachable 100 USD.

## Result

Not run yet.
