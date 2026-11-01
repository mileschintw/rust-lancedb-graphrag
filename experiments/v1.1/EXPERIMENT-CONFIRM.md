# Confirm: full MultiHop-RAG on a fresh held-out set (draft)

Status: **draft, 2026-11-01, for the owner's review. Nothing here is frozen.** The run plan below is frozen first, as a
D-73 constant in its own commit. The analysis plan ([ANALYSIS-CONFIRM.md](ANALYSIS-CONFIRM.md)) is frozen separately,
before any held-out run is scored (#163's blinding rule). The run guide is [RUN-CONFIRM.md](RUN-CONFIRM.md).

Owner, 2026-11-01 (#146): "可以，就這麼做". The plan they confirmed: confirm on a fresh MultiHop-RAG held-out of
1,056 questions, read once, collected in stages under the blinding rule; a 2 x 4 grid of chunking {small, merged} x
readers {deepseek K=2, Haiku 5.5 K=2, Sonnet 5.5 K=1 Batch, Opus 5.5 K=1}, whose key hypothesis is the chunking x
reader interaction; LlamaIndex rebuilt on all 609 documents with the deepseek reader; LlamaIndex with Opus optional.

## Why

S0 to S2 read 90 G dev questions on a 346-document subset, which detects only gaps of about 8 points (#146). Run C
(EXPLORE-C-MHR-FULL.md) read 1,000 fresh dev questions on all 609 documents and moved two S2 readings: Opus 5.5 led
deepseek by 5.0 points (95% CI +2.4 to +7.8) and Sonnet 5.5 tied it. S2X (EXPLORE-S2-MERGED.md) saw merged chunks cut
the Claude readers' abstention, not deepseek's. Both were dev reads that decide nothing. This stage tests them once, on
questions no run has read.

## Held-out set

- **The 1,056 held-out IDs of `eval/corpora/multihop_rag/fresh_split.json`** (#149, seed 149, split sha256
  `30d3dee89824cf4ef89b960a26889a2f1f8bed9128a47d341b93da0376d80e7d`). #149 built it from question IDs alone and
  reserved its held-out part for #146; no run has read one of its questions, and nothing has sorted them into G and
  null. This stage reuses it as it is and designs no new split.
- **Not yet written to disk.** #149 wrote only the dev rows (`questions.fresh_dev.jsonl`). The held-out rows are
  written from the IDs once the run plan is frozen (RUN-CONFIRM.md, step 2), by a script that prints no question
  text. G and null are told apart from the rows' answers only by `score`, after the analysis plan is frozen.
- **Held-out budget.** D-287 allows one held-out read per benchmark, and S0 already read MultiHop-RAG's D-105
  held-out set. This set is disjoint from it (#149's derivation rule). Open question 1 asks whether D-287's "one read"
  is per held-out set, so this read is allowed, or needs a new D-ID.

## Stores

| Column | Store | Chunking | Built by |
|---|---|---|---|
| small | `eval-full` (`full/`) | structure-aware 500/50, as the v1.0 store | #149 (run C), reused as built: no write |
| merged | `eval-full-merged` (`fullmerged/`) | structure-merge 256/25, as S1's store | #146 prep (RUN-CONFIRM.md, step 0) |
| LlamaIndex | `data/llamaindex-full` (persisted index) | `SentenceSplitter(256, 25)`, the paper's | #146 prep (RUN-CONFIRM.md, step 0) |

Both Lancet stores hold all 609 articles of MultiHop-RAG's `corpus.json` (pinned by sha256) with no graph. The merged
store keeps S1's excerpt cap of 2,048 characters (D-273). The LlamaIndex export carries `eval-full`'s document IDs.

## Run plan (to freeze as the D-73 constant)

Every cell is listed and none is ruled out (#163's rule). A cell is descriptive unless the analysis plan names it.

| Cell | Arm label | Reader | K | Transport, thinking |
|---|---|---|---|---|
| 1 | `full/hybrid+rerank+metadata` | deepseek | 2 | replicate 1 driven by `run`; replicate 2 OpenRouter sync, pinned (D-271, D-278) |
| 2 | `full/hybrid+rerank+metadata@haiku-5.5` | Haiku 5.5 | 2 | OpenRouter Batch, BYOK, thinking off |
| 3 | `full/hybrid+rerank+metadata@sonnet-5.5` | Sonnet 5.5 | 1 | OpenRouter Batch, BYOK, effort low (D-289; open question 3) |
| 4 | `full/hybrid+rerank+metadata@opus-5.5` | Opus 5.5 | 1 | OpenRouter Batch, BYOK, effort low |
| 5 | `fullmerged/hybrid+rerank+metadata` | deepseek | 2 | as cell 1 |
| 6 | `fullmerged/hybrid+rerank+metadata@haiku-5.5` | Haiku 5.5 | 2 | as cell 2 |
| 7 | `fullmerged/hybrid+rerank+metadata@sonnet-5.5` | Sonnet 5.5 | 1 | as cell 3 |
| 8 | `fullmerged/hybrid+rerank+metadata@opus-5.5` | Opus 5.5 | 1 | as cell 4 |
| 9 | `llamaindex` (external, `eval-full` IDs) | deepseek | 2 | engine generate-only bin over the export (D-247), as cell 1's reader |
| 10 (optional) | `llamaindex@opus-5.5` | Opus 5.5 | 1 | as cell 4; run only on the owner's yes |

- **Must-run:** cells 1 to 9. Cell 10 is optional (owner, #146).
- **Questions:** all 1,056 held-out questions in every cell; 1,056 x K records per cell.
- **Prompts:** each Claude reader reads the context its deepseek cell retrieved (D-257 replay), so the two columns
  differ only in chunking.
- **Partial cells** are allowed (#163): a cell may be submitted in stages, and a cell cut short is reported as such.
- **Constant.** A new `ReplayStagePreRegistration`, `PREREGISTRATION_CONFIRM`, or the run-plan type #163 adds,
  whichever #163 lands. Fields as `PREREGISTRATION_EXPLORE_C` with: two replay sources (`full/` and `fullmerged/`), or
  one constant per column if the type takes one source; `reader_replicates` Sonnet 1 and Opus 1; Sonnet's transport
  Batch; the external arm `llamaindex` with the pipeline echo of `data/llamaindex-full/index_manifest.json`; the corpus
  `multihop_rag_confirm_heldout` (written at freeze: RUN-CONFIRM.md, step 1). Its family and test fields are left to
  the analysis plan's freeze, if the type allows; otherwise they are declared descriptive here and the analysis plan
  is an addendum constant, as `PREREGISTRATION_S3_WRITERS_SYNC` is to S3's.

## Cost estimate

From run C's measured spend per answer (1,000 questions, small store), scaled to 1,056 questions. Merged prompts
carry 8 chunks of 256 tokens against 8 of 500, so the merged column costs at most the small column's figure.

| Item | Small column | Merged column (at most) |
|---|---|---|
| Haiku 5.5, Batch, 2,112 answers | $0.71 | $0.71 |
| Sonnet 5.5, Batch, 1,056 answers (run C's sync spend halved) | $7.50 | $7.50 |
| Opus 5.5, Batch, 1,056 answers | $14.31 | $14.31 |
| **Claude, per column** | **$22.52** | **$22.52** |

- **Claude, cells 2 to 8:** at most about $45. The owner's figure was about $61; this one is lower because Sonnet goes
  through Batch here, where run C sent it sync.
- **Cell 10 (optional):** at most about $14.
- **OpenRouter:** drives about $1.03 per column and deepseek's second replicate about $0.21 per column; the LlamaIndex
  export (1,056 query embeddings and rerank calls, at most about $0.34) and its deepseek answers (about $0.45 for K =
  2): about $3.3, under the owner's $10.
- **Prep (this lane, embeddings only):** the merged store's build and the LlamaIndex index, about $0.19 each by the
  D-258 estimate over 6,297,171 article characters.

## Order and blinding

1. Freeze this run plan (D-73 constant, own commit), after the owner's review.
2. Write the held-out corpus and question rows; drive cells 1 and 5; export and drive cell 9; carry and submit the
   Claude cells (RUN-CONFIRM.md).
3. No `score`, `compare-levers`, `explore_readout` or answer judge reads a held-out run until the analysis plan is
   frozen (#163's D-ID). Counts, routing and error lines may be read; answers may not.
4. Freeze the analysis plan; score once.

## Before the run

- **#163** lands the blinding D-ID and, possibly, a run-plan type this constant uses.
- **#128** (lane spare-2): per-store gold chunk sets and chunk sizes, so Hits@10 and MRR@10 compare with the paper.
- **#164**: `score` loads the v1.0 document map for every journal and so refuses one on the full corpus; the external
  arm's document IDs need `eval-full`'s map.

## Open questions for the owner

1. **D-287.** Is this a second held-out read of MultiHop-RAG (allowed only by a new D-ID), or the first read of a new
   held-out set (allowed as is)? Recommended: a new D-ID that reads D-287 per held-out set, since the sets are disjoint
   and this one was reserved before any read.
2. **Decisional metric.** `answer_usable` (S0 to S2's) or, per D-286, yes/no balanced accuracy beside open
   `answer_usable`. Settled in the analysis plan, not here; the run plan is the same either way.
3. **Sonnet's thinking on Batch.** D-289 says the lowest setting the Batch API supports; #163's owner rule says effort
   low. Run C sent Sonnet sync with `between_tools` (D-280), so its numbers do not carry over exactly. Recommended:
   effort low, as in #163.
4. **LlamaIndex reader K.** Cell 9 at K = 2, as deepseek's Lancet cells, so the equivalence test pairs like with like.
