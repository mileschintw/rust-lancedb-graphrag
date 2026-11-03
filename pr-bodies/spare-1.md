Records S3's held-out reader grid on 2Wiki: 15 of its 24 cells, run blind, with every run directory committed in full. The other 9 Claude cells wait for new credit.

Closes #163

## Why

#163 asks for S3's held-out reader grid: 4 readers by 6 context columns over 2Wiki's 900 held-out questions. #173 froze its run plan (`RUN_PLAN_S3_HELDOUT`, D-291) and added the harness it needs. This PR is the run of record. Nothing is scored until a separate analysis constant is frozen (D-291).

## What changes

- **Run directories** under `eval/runs/` (13 directories), committed in full, as the owner asked ("全都公開repo備份全文"):
  - the six runs of record: closed-book, hybrid, graph-deepseek, graph-haiku, graph-sonnet and graph-opus;
  - the five deepseek drives they were carried from;
  - two `-rerun` directories for the retrieval-timeout reruns.
- **Large files:** the 4 files over 50 MB are gzipped, each beside a `README.md` with its unpack command and the SHA-256 of the unpacked file, checked before the commit.
- **Per directory:** a `.gitattributes` of `* -text`, and `question_types.json` (#167, no answers).
- **`experiments/v1.1/RUN-S3-HELDOUT.md`, Result section:**
  - which cells ran and which wait;
  - the owner's rulings, quoted;
  - the four graph table sets' counts, and a check that the store's own tables are unchanged;
  - where the run differed from the guide;
  - spend;
  - per run directory: counts per arm and replicate, every error line, batch IDs, thinking, reasoning tokens and spend.

## Cells

| Column | deepseek (K=2) | Haiku (K=2) | Sonnet (K=1) | Opus (K=1) |
|---|---|---|---|---|
| closed-book | ran | ran | ran | ran |
| hybrid | ran | ran | ran | ran |
| graph-deepseek | ran | ran | waits | ran |
| graph-haiku | ran | ran | waits (optional) | waits |
| graph-sonnet | ran | waits | waits (optional) | waits |
| graph-opus | ran | waits | waits (optional) | waits |

A waiting cell needs only `batch submit` and `batch fetch` on its committed run directory.

## Spend

- **Claude:** $34.50 of the $36.50 ceiling, which the owner raised from $34.50 ("Raise cap to ~$36.5").
- **OpenRouter:** $4.82 by the records, of the $6 ceiling, which the owner raised from $3 ("Raise to $6 (Recommended)"). The account balance fell $2.80.

## How it differed from the guide

- **A drive was set aside.** The first graph-deepseek drive ran while three graph imports were still writing. Retrieval slowed, the rerank tripwire stopped the drive after 5 records ($0.005), and the drive was rerun from empty.
- **Four `RetrieveHybrid timed out` records were rerun**, blind, as the owner approved. The rerun records are appended after the original errors, which stay in the journal. Two succeeded; two timed out again with the machine idle and stay errors.
- **One question has a single deepseek answer.** On graph-haiku, `122324e8…` succeeded only on its rerun. Its replicate-2 slot already holds a `base_error` record, which `batch submit` treats as final, so its second deepseek answer would need a harness change.
- **Two questions are over length for Claude.** On the hybrid and graph columns, every Claude reader failed `f06252fc…` and `a1d9a65c…`: Claude's tokenizer counts their packed prompts above the engine's 8,192 budget. The errors are billed and final.

## Testing

- No code changes. `eval/src` is unchanged, so `batch submit` passed its D-73 check on every submit.
- Every submit reported 0 routing breaks: no answer was billed outside BYOK or the declared provider.
- Before each push, the files were scanned for the OpenRouter key and every KEY/TOKEN/SECRET environment value: 0 hits. "Bearer" appears only in corpus text ("Standard-Bearer").
- The store's own tables were compared against a listing taken before the first import: all 116,282 files are unchanged.

## Review

There is no code change, so one review ran on the Result section, against the guide's **Record** list and the lane brief. It cross-checked counts against the journals and found no blocker:

- every arm and replicate count matches the journals;
- every error line sums to its row;
- the 15-of-24 cell table is correct;
- the Claude total checks;
- no answers, gold or scores appear.

**Notes fixed:**
- Hybrid's Claude spend is $16.60, its rows' sum, not $16.61.
- There are seven sync runs, not six.
- The order of the Haiku batches and the reruns is stated.
- Drive rows show `n/a` reasoning tokens instead of 0.
- Error lines are said to give 8-character ID prefixes.
- The coordinator's relayed plan is set apart from the owner's quote.
- Directory headings moved one level down.
- The tokenizer explanation for the two over-length prompts is marked as likely.

**Notes left:**
- The rerun drives' spend and the import embeddings are not itemised; the Result says so.
- "core" and "optional" are defined in the guide's **Cells** section, not repeated in the Result.
- Sonnet's 0 reasoning tokens on hybrid against 2,006 on closed-book is measured, not explained.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
