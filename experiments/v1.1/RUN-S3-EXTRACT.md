# S3 writer extraction: run guide and spend record (#145)

This step runs the S3 writers over every 2Wiki passage, as `PREREGISTRATION_S3_WRITERS` in
`eval/src/lancet_eval/thresholds.py` fixes them:

- 6,119 passages, one request each. The unit is `title\ntext` (`twowiki.passage_unit`).
- The engine's extraction body.
- The writers deepseek (thinking off), Haiku 5.5 (off), Sonnet 5.5 and Opus 5.5 (on, effort low).
- Every writer runs on OpenRouter's Batch API.

It stores the raw outputs and their usage per passage. It builds no store and reads no question. Store builds, graph
ingestion, reader runs and S3's analysis pre-registration come later.

**Status: draft.** The commands below come from extending #117's `writer_pilot` script once #117 merges.

## Inputs

- **Passages.** Run `PYTHONUTF8=1 uv run --project eval python -m lancet_eval.twowiki fetch` first. It downloads
  `osunlp/HippoRAG_2@5ec05b38` into `eval/corpora/twowiki/.cache/` and refuses any file whose sha256 differs from
  the pinned one.
- **Spend.**
  - The owner pre-approved spend within reason (2026-11-01, relayed: "預算現在不用拿給我看了，只要是在合理範圍我們的credit可支付的情況下都直接同意").
  - This lane's ceilings are $70 of Claude credit (raised from $60 by the coordinator, 2026-11-01) for all four Claude-credit writers and $1.50 of OpenRouter credit for deepseek.
  - Each estimate is printed before its submit (D-258). An estimate over a ceiling stops the lane and goes back to the owner.
- **Deadline.** Every Claude batch must be submitted by the morning of 2026-11-02 (Pacific), because the Claude credit expires on 2026-11-03.

## Preliminary estimate (before the script exists)

These figures are measured from #117's writer pilot (1,803 MultiHop-RAG chunks, Haiku and Sonnet at their S3
settings) and scaled to the 2Wiki units.

- **2Wiki units.** 666,392 o200k tokens in all: mean 109, median 72, maximum 1,537.
- **Prompt overhead.** Claude reports about 565 prompt tokens per request beyond the chunk text, most of it the schema.
- **Output.** Completion tokens grew linearly with chunk length in the pilot: Haiku about 128 + 3.6 × chunk tokens,
  Sonnet about 136 + 3.6 × chunk tokens. 1,425 of the units are longer than the pilot's longest chunk (139 tokens),
  so those are extrapolated. The "capped" column limits each unit to the pilot's largest answer.

| Writer | Input | Output | Batch cost |
|---|---|---|---|
| Haiku 5.5 | 4.1M | 3.0-3.2M | about $1.0 |
| Sonnet 5.5 | 4.1M | 3.0-3.25M | about $19-20 |
| Opus 5.5 | 4.1M | 3.0-3.25M, assumed equal to Sonnet (not measured) | about $38-41 |
| **Claude total** | | | **about $58-62** |
| deepseek (OpenRouter) | about 1M | about 2.5M | under $1 at full price |

The Claude total is close to the ceiling, so the run goes in stages. Haiku and Sonnet go first. Opus's first part
then gives a measured projection before the rest of Opus is submitted.

## Spend record

Batch IDs and costs go here per writer and part, as they are submitted and fetched.
