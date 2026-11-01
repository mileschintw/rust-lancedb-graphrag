# S3 writer extraction: run guide and spend record (#145)

This step runs the S3 writers over every 2Wiki passage, as `PREREGISTRATION_S3_WRITERS` in
`eval/src/lancet_eval/thresholds.py` fixes them:

- 6,119 passages, one request each. The unit is `title\ntext` (`twowiki.passage_unit`).
- The engine's extraction body.
- The writers deepseek (thinking off), Haiku 5.5 (off), Sonnet 5.5 and Opus 5.5 (on, effort low).
- Every writer runs on OpenRouter's Batch API.

It stores the raw outputs and their usage per passage. It builds no store and reads no question. Store builds, graph
ingestion, reader runs and S3's analysis pre-registration come later.

**Status:** the three Claude writers ran on 2026-11-01 and every request succeeded. deepseek has not run; see
[deepseek](#deepseek).

## Inputs

- **Passages.** Run `PYTHONUTF8=1 uv run --project eval python -m lancet_eval.twowiki fetch` first. It downloads
  `osunlp/HippoRAG_2@5ec05b38` into `eval/corpora/twowiki/.cache/` and refuses any file whose sha256 differs from
  the pinned one.
- **Spend.**
  - The owner pre-approved spend within reason (2026-11-01, relayed: "預算現在不用拿給我看了，只要是在合理範圍我們的credit可支付的情況下都直接同意").
  - This lane's ceilings are $70 of Claude credit (raised from $60 by the coordinator, 2026-11-01) for the Claude writers and $1.50 of OpenRouter credit for deepseek.
  - Each estimate is printed before its submit (D-258). An estimate over a ceiling stops the lane and goes back to the owner.
- **Deadline.** Every Claude batch must be submitted by the morning of 2026-11-02 (Pacific), because the Claude credit expires on 2026-11-03.

## Commands

`lancet_eval.s3_extract` runs on #117's `writer_pilot`: the same request bodies, Batch client, manifests, routing
check and answer parser. From the repo root, with `OPENROUTER_API_KEY` set:

```bash
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.s3_extract plan                       # free: chunks + estimates
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.s3_extract submit haiku-5.5           # paid: 13 batches
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.s3_extract submit sonnet-5.5
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.s3_extract submit opus-5.5 --parts 1  # paid: 500 passages
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.s3_extract fetch opus-5.5             # free, until finished
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.s3_extract plan                       # Opus re-projected
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.s3_extract submit opus-5.5            # paid: the other 12
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.s3_extract fetch <writer>             # each writer
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.s3_extract report                     # free: summary.json
```

Outputs are in `experiments/v1.1/s3-extract/`:

- **Committed:** the batch manifests (`<writer>.batch.json`, with batch IDs and body hashes) and `summary.json`.
- **Gitignored:** `chunks.jsonl` and `<writer>.results.jsonl`. They hold Wikipedia text (CC BY-SA), about 34 MB in
  all.
- **Rebuilding them:** `plan` rebuilds `chunks.jsonl` from the pinned passages. `fetch` rebuilds a writer's results
  from OpenRouter for as long as it keeps them (30 days, so until about 2026-12-01). A re-fetch keeps every answer
  that had already succeeded.

## Estimates

The estimates came from #117's pilot (1,803 MultiHop-RAG chunks) and were scaled to the 2Wiki units:

- **2Wiki units:** 666,392 o200k tokens in all: mean 109, median 72, maximum 1,537.
- **Input:** each unit's o200k tokens, plus the prompt overhead Claude billed per request (about 565 tokens, most of it the schema).
- **Output:** a linear fit of completion tokens on chunk tokens, capped at the largest answer the pilot saw.

| Writer | Estimate | Basis |
|---|---|---|
| Haiku 5.5 | $0.96 | the pilot's Haiku answers |
| Sonnet 5.5 | $19.01 | the pilot's Sonnet answers |
| Opus 5.5, part 1 (500) | $2.98 | the pilot's Sonnet answers (Opus was not in the pilot) |
| Opus 5.5, parts 2-13 (5,619) | $39.46 | Opus part 1's own answers: overhead 593, completion 235 + 2.99 × unit tokens |

Opus part 1 cost $3.40 against its $2.98 estimate. With the rest of Opus at $39.46, the projected Claude total came to
about $63-66, under the $70 ceiling. The rest of Opus was submitted on that projection.

## Result

The batches were submitted on 2026-11-01 between 11:10 and 11:18 UTC and had finished by 11:29 UTC. The figures
come from `summary.json`. Cost is tokens × list price × 0.5, the Batch API rate.

| Writer | Thinking | Succeeded | Errored | Schema-invalid | Runaways (#156) | Reasoning tokens | Input tokens | Output tokens | Cost |
|---|---|---|---|---|---|---|---|---|---|
| Haiku 5.5 | off | 6,119 | 0 | 0 | 0 | 0 | 4,312,977 | 3,639,506 | $1.13 |
| Sonnet 5.5 | on, effort low | 6,119 | 0 | 0 | 0 | 0 | 4,319,096 | 3,608,405 | $22.36 |
| Opus 5.5 | on, effort low | 6,119 | 0 | 0 | 0 | 0 | 4,319,096 | 3,467,046 | $43.31 |
| **Claude total** | | | | | | | | | **$66.80** |

- **Routing:** every answer came from provider Anthropic with `is_byok: true` (`writer_pilot.routing_problem` found no
  break), so the spend is on the Claude credit.
- **Runaways:** no Claude writer had one, meaning no answer ended with `finish_reason: length` (the deepseek failure in
  #156).
- **Thinking:** Sonnet and Opus at effort low reported 0 reasoning tokens on every passage, as Sonnet did in #117's
  pilot.
- **Opus part 1:** fetched twice. The second fetch replaced no answer.

## deepseek

deepseek is not run. The frozen constant gives it `openrouter_batch`, but #117's path sends deepseek only through the
sync API (D-278), and running it there would contradict the freeze. OpenRouter credit does not expire, so the choice
waits for the owner (coordinator, 2026-11-01). The options:

- **(a)** An addendum constant and a new D-ID that move deepseek to the sync API, as D-278 did for S2. This is the
  pinned Wafer endpoint the engine and #117 already use. Its cost is about $1, with about 1.3% runaways expected
  (#156).
- **(b)** Try deepseek on OpenRouter's Batch API, as frozen. Whether the Batch API honours the D-271 Wafer pin and its
  `max_price` is unverified, and a batch served by another provider would not be the v1.0 writer.
