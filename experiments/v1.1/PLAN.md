# v1.1 experiment plan (draft)

Status: draft for owner review, 2026-10-25. Findings and sources are in [RESEARCH.md](RESEARCH.md).

## Goal

Show where Lancet stands against reference points it did not choose, then improve it honestly:

- **Usable:** answer quality on held-out questions, compared with a standard pipeline on the same models.
- **Credible:** every decisional reading keeps the v1.0 guards: paired arms, a pre-registration committed before the
  paid run, Holm correction, fail-closed reporting, and a fixed budget of held-out reads (D-237).

Non-goals: tuning until the graph looks good; reporting gains measured only against Lancet's own earlier versions.

## Stages

Each stage gates the next. Each stage gets its own pre-registration (arms, primary metric, decision rule) committed
before its paid run.

| Stage | Question | Arms | Benchmark | Paid by |
|---|---|---|---|---|
| **S0 Baseline** | Where does Lancet stand against the MultiHop-RAG paper's own pipeline? | Lancet shipped default (hybrid + rerank + metadata); LlamaIndex paper config with Lancet's prompt | MultiHop-RAG held-out | OpenRouter, small |
| **S1 Chunking** | Do merged chunks of about 256 tokens beat paragraph fragments? | small vs merged chunks, each with graph off and on (deepseek extraction) | MultiHop-RAG dev | OpenRouter, re-embed and re-extract, a few dollars |
| **S2 Reader** | How much does the answering model matter on identical context? | deepseek vs Haiku 5.5 vs Sonnet 5.5 reading the same replayed prompts | MultiHop-RAG dev, S1's chosen chunking | Claude Batch, about $2-4 per Sonnet arm, cents per Haiku arm |
| **S3 Writer and graph** | Does the extraction model matter where a graph has room to help? | closed-book; Lancet hybrid; Lancet + graph with deepseek, Haiku 5.5 and Sonnet 5.5 as writers; LlamaIndex; optional HippoRAG 2; one reader fixed by S2 | 2WikiMultiHopQA subset (HippoRAG 2 packaging) | most of the Claude credit |
| **Confirm** | Does the configuration chosen on dev hold on held-out? | v1.0 default vs the final configuration from S1 and S2, plus the LlamaIndex baseline | MultiHop-RAG held-out (second and last read) | small |

### S0 details

- Two arms only (D-238): Lancet's shipped default (hybrid + rerank + evidence metadata, graph off) and the LlamaIndex
  arm per RESEARCH.md section 3: `SentenceSplitter(256, 25)`, dense top 20, rerank with `voyageai/rerank-2.5-lite`,
  keep 8, title/source/published_at metadata attached as in the paper, Lancet's generation prompt.
- Add evidence-substring Hits@4 to the harness and score every arm with it. Keep the chunk-ID Hits@4 as a
  Lancet-only secondary.
- Primary metric: `answer_usable` on the G population. Supporting: substring Hits@4, context tokens, latency.
- Expect the baseline may win today (256-token chunks vs Lancet's 55). That is the point of measuring first.
- Open item: how the arm enters the harness. Its records need the same journal shape, pairing and fail-closed rules.
  "Lancet's prompt" also includes the engine's strict `final_answer` schema (D-95), so copying the prompt text alone
  will not reproduce the `Answer:` line. A shared step that exports each arm's retrieved context, plus one generation
  step over it, would serve both S0 and S2's replay.

### S1 details

- Paragraph-per-chunk was deliberate: it comes from the original structure-aware chunker (D-07, D-08: Markdown AST,
  headings and paragraphs as split markers). S1 keeps that design and adds the merge step it lacks (D-242): paragraph
  and heading boundaries stay the only split points, consecutive paragraphs in the same section merge up to the
  target, a paragraph longer than the target still splits by window, and no chunk crosses a heading.
- One target, 256 tokens (o200k), chosen to match the MultiHop-RAG paper (D-241). It replaces D-09's 500-character
  default for the S1 store only; no size sweep.
- Rebuild a second store (new embeddings, new deepseek extraction); keep the v1.0 store untouched.
- Re-map gold evidence to the new chunks; compare arms on `answer_usable` and substring Hits@4 only.
- Change chunking and nothing else. Model changes wait for S2 and S3.

### S2 details

- Replay the exact packed prompts from S1's journal so both readers see identical context and rerank jitter cannot
  differ between arms. Open item: confirm the journal can rebuild the exact prompt; if not, add a prompt-dump switch to
  the engine first.
- Runs offline through OpenRouter's Batch API from a Python script (see Model access); no Rust Anthropic adapter
  needed for this stage.
- Readers: deepseek (the v1.0 reader), Haiku 5.5 and Sonnet 5.5. Three points show whether answer quality keeps
  rising with reader strength or saturates. Thinking off where the model allows it (Haiku 5.5: disabled at effort high
  or below; Sonnet 5.5: `between_tools`). Opus 5.5 only if Sonnet clearly beats Haiku.
- The winning reader becomes S3's fixed reader. If Haiku 5.5 beats deepseek, also consider making it Lancet's default
  generation model (cheaper and better), as a separate product decision with its own reading.

### S3 details

- Benchmark: the 2WikiMultiHopQA subset from `osunlp/HippoRAG_2` (1,000 questions, 6,119 passages, about 0.75M
  tokens), decided 2026-10-25 (see Decisions). Ingest its passages as given (already split; about 6,119 extraction
  calls).
- Before any run, confirm the license from the dataset's original source (Apache-2.0 so far comes from secondary
  sources only) and record the exact dataset revision used.
- Claude extraction runs offline through Batch into graph side tables, as graph-v2 did; entity names re-embedded with
  Voyage.
- A closed-book arm guards against memorised Wikipedia answers; report gains over it.
- Writers: deepseek (v1.0 writer), Haiku 5.5 and Sonnet 5.5. Sonnet is kept even if Haiku already beats deepseek on
  general benchmarks: the writer claim needs a clearly stronger point, or a null result cannot tell "the writer does
  not matter" from "the writers were too close". Opus 5.5 joins only if the pilot shows a large Haiku-to-Sonnet
  extraction gap (the trend has not saturated).
- The reader stays fixed (S2's winner) so differences belong to the writer. A Sonnet-reader point on one or two key
  arms is allowed only as a descriptive reading outside the decisional family.
- Pilot first: a few hundred chunks per candidate writer to measure real tokens, thinking tokens and cost on this task.
  General benchmark rankings do not transfer automatically to entity extraction.

## Budget sketch (estimates until pilots run)

| Item | Estimate |
|---|---|
| S0, S1 (OpenRouter only) | a few dollars plus re-embedding |
| S2 Sonnet reader, dev | about $3-8 of Claude credit |
| S2 Haiku reader, dev | under $1 |
| Confirm, held-out (final reader) | about $4-10 |
| S3 pilots | under $5 |
| S3 Haiku extraction (2Wiki, Batch) | under $1 |
| S3 Sonnet extraction (2Wiki, Batch) | about $7-14 |
| S3 Claude reader arms | about $10-20 |
| Reruns and preflights | about $15 |
| **Total Claude credit** | **about $45-75 of $200**, leaving room for an Opus writer point |

## Process

- No full GSD phase loop. One `EXPERIMENT-S{n}.md` per stage holds the hypothesis, arms, metrics, decision rule and,
  after the run, the result. Committed before the run, it is the pre-registration.
- Code changes (harness arm, substring Hits@4, chunker, prompt dump) go on their own branches with a code review
  before merge. The GSD harness has been removed from main; no GSD commands are part of this plan.
- This plan merges to main through a PR before S0 starts, so experiment branches can reference it.
- New decisions get IDs continuing from v1.0 (next free D-ID) and are logged in the stage file.
- `.planning/` stays read-only as the v1.0 record.

## Decisions

IDs continue from v1.0's last (D-233). All were accepted by the owner on 2026-10-25.

- **D-234 Second benchmark: 2WikiMultiHopQA** (owner, 2026-10-25). It has real bridge entities, short gold answers with
  supporting facts, the clearest published graph gain (HippoRAG 2 71.0 vs dense 61.5 F1) and the smallest pre-split
  corpus. MuSiQue was the alternative (harder, CC BY 4.0 in its repo, about twice the extraction cost). MultiHop-RAG
  stays the primary benchmark.
- **D-235 Model roles** (owner, 2026-10-25). S0 and S1 keep deepseek for writing and reading, so their numbers connect to
  v1.0. S2 compares readers (deepseek, Haiku 5.5, Sonnet 5.5) on identical prompts. S3 compares writers (deepseek,
  Haiku 5.5, Sonnet 5.5) with one fixed reader. Opus 5.5 is conditional on pilot results.
- **D-236 Engine-path Claude calls use OpenRouter BYOK** (owner, 2026-10-25), not a native adapter; see Model access.
- **D-237 Held-out budget.** MultiHop-RAG held-out (351: 308 G, 43 null) is read twice in v1.1: once in S0 to set the
  starting point, once in Confirm with the final configuration. Every S1 and S2 choice is made on dev. The dev pool is
  only 100 questions (90 G, 10 null), so dev readings are direction-finding: they can only show large effects, and
  only the Confirm reading is decisional for MultiHop-RAG.
- **D-238 S0 arms.** Lancet's shipped default against the LlamaIndex paper configuration with document metadata
  attached, one arm each. No extra plain-hybrid arm.
- **D-239 Decision rule.** Reuse the v1.0 form: paired comparisons on `answer_usable` with a Holm family per reading,
  the null-abstention guard, pre-registration committed before the paid run. Each stage file states the smallest
  effect its sample can detect (about 4-5 points on 308 held-out pairs).
- **D-240 Process.** No GSD; stage files are the pre-registrations; this plan merges to main by PR before S0.
- **D-241 Chunk target.** 256 tokens, to match the paper; no sweep.
- **D-242 Chunker merge rule.** Keep D-07/D-08 split markers; add merging of consecutive same-section paragraphs up to
  the target (see S1 details).
- **D-243 2Wiki split.** Before any 2Wiki run, fix a dev/held-out split of the 1,000 questions with a committed seed
  and record its SHA-256 in each journal header, as MultiHop-RAG does. The held-out part is read once.
- **D-244 2Wiki metrics.** `answer_usable` is decisional. Token F1 and EM are reported alongside for readers who know
  the literature, with a note that published numbers used other models and are not directly comparable.
- **D-245 Default-model switch rule.** Lancet's default generation model changes from deepseek to Haiku 5.5 only if,
  on the reading that decides it, Haiku's `answer_usable` is not significantly worse than deepseek's, the null guard
  holds, and cost per answered question is lower. Written into the S2 stage file before S2 runs.
- **D-246 Spend caps** (hard stops, not estimates): S0 $5 and S1 $15 of OpenRouter credit; S2 $30, S3 $110 and
  Confirm $10 of Claude credit. Claude total cap $150, leaving $50 of the $200 in reserve. A stage that hits its cap
  stops and is re-planned.

## Model access

Two paths, chosen by where the call happens:

- **Offline jobs (S2 replay, S3 Claude extraction):** Python scripts submit to OpenRouter's Batch API
  (`POST /api/v1/batches`) with the BYOK key, at about 50% off. Each request body is the same chat-completions body
  the engine sends, so batch and engine requests cannot drift apart, and deepseek arms can use the same path. The
  Anthropic Message Batches API directly is the fallback if a needed feature does not pass through.
- **Calls made by the engine (any live Claude reader or extraction):** OpenRouter with the Anthropic key added as a
  BYOK key. No native Anthropic adapter in the engine unless this path fails.

What OpenRouter's docs and one test call showed (2026-10-25):

| Question | Finding | Source |
|---|---|---|
| BYOK fee | 5% of the list-price cost, deducted from OpenRouter credits, but pay-as-you-go includes a free BYOK allowance of $25,000 per month measured at list price. At this plan's scale (under $200) the fee is effectively zero. | BYOK docs page |
| Will the Anthropic credit actually be used? | Not by default. The test call was served by "Claude Platform on AWS", not Anthropic. Set the key's shared-capacity fallback to "Never use shared capacity" and restrict the provider (`provider.only`) so requests run only through the BYOK key; check `is_byok: true` in the response usage. | BYOK docs; test call |
| `temperature` / `top_p` | Ignored, not rejected. Claude 5.x models list neither in `supported_parameters`, providers ignore unknown parameters by default, and a Haiku 5.5 call with `temperature: 0, top_p: 1` succeeded. The engine needs no change, but temperature-0 determinism is gone for Claude arms. Do not set `provider.require_parameters: true`, which would route no provider. | models API; provider-selection docs; test call |
| `response_format` (extraction schema) | Claude 5.x models list `response_format` and `structured_outputs`, so the engine's OpenAI-style extraction request may work unchanged. Confirm in the pilot. | models API |
| `reasoning: {effort: none}` (sent by the engine) | How OpenRouter maps it for Haiku 5.5 and Sonnet 5.5 is unverified. Check `reasoning_tokens` in the pilot's usage. | not verified |
| BYOK in practice | After the owner added the key: a sync Haiku 5.5 call returned `provider: Anthropic`, `is_byok: true`, OpenRouter cost 0. | test call |
| `:batch` model variants | The `anthropic/claude-*:batch` slugs cannot be called on `/chat/completions` (404, "AnthropicBatchAdapter"). Batch runs through the separate Batch API instead: submit with the normal slug (`anthropic/claude-haiku-5.5`), one model and one endpoint per batch, requests inline as `{custom_id, body}` (no JSONL upload), `endpoint`/`model`/`provider` fields before `requests`, results inline from `GET /api/v1/batches/{id}` matched by `custom_id`, 24-hour window, results kept 30 days. Pin `provider: {only: ["anthropic"]}`; BYOK batches skip the balance check. Unknown parameters are dropped as on the sync API; `stream`, `speed` and Anthropic beta features are not supported. | Batch API docs; test submit |
| End-to-end batch test | Submitted 2026-10-25: two Haiku 5.5 requests (one with `temperature: 0`, one with a strict `json_schema` `response_format`), pinned to Anthropic. Completed in 10.9 minutes, 2 of 2 succeeded, `provider: Anthropic`, `is_byok: true`, OpenRouter cost 0, upstream cost billed at the batch rate (half price). The temperature request answered normally (parameter dropped); the schema request returned valid JSON (`{"word": "yes"}`). The schema added about 184 prompt tokens (202 vs 18), a measured input for extraction cost estimates. `reasoning_tokens` was 0 with no reasoning setting sent. | test batch `batch-1792978663-0z5qxO2SosYhWBRRNDtP` |

Test calls so far cost $0.0000038 of OpenRouter credit plus BYOK traffic billed to Anthropic.

### Prompt caching

With Claude, caching is opt-in per request. Prices relative to base input: 5-minute write 1.25x, 1-hour write 2x, read
0.1x (0.05x on Opus 5.5). Prefixes under 512 tokens (Haiku 5.5, Sonnet 5.5) silently do not cache.

| Request type | Cache? | How |
|---|---|---|
| Reader (S2 replay, Claude reader arms) | Yes | One explicit `cache_control` breakpoint at the end of the static system prompt (about 700-800 tokens, a rough count from the source), before the per-question evidence. No top-level automatic caching: its breakpoint would land after the unique tail and only write. |
| Extraction (S3) | No | The system prompt plus schema is about 300 tokens, under the 512 minimum. Revisit only if the pilot adds few-shot examples, which must then be identical for every writer. |
| Engine path with deepseek (S0, S1) | No change | Not a Claude path. |

TTL by start-to-start gap between requests sharing the prefix:

- **Batch jobs: 1 hour.** Batch order and timing are outside our control and can stretch past 5 minutes, so 5-minute
  entries may expire unread. The 2x write is paid once per arm on about 1,000 tokens.
- **Sequential sync runs: 5 minutes.** Requests seconds apart keep refreshing the entry; 1 hour would only double the
  write price.

Notes: parallel requests cannot read an entry still being written, so the first wave of a batch misses; each arm's
prompt variant (metadata, graph) has its own entry. Savings at this scale are small (about $0.6 per Sonnet arm of 351
questions, cents per Haiku arm). Verify with `usage.cache_read_input_tokens > 0` after the first request of an arm;
zero means some prefix bytes differ per request. Whether `cache_control` passes through OpenRouter's Batch API is
unverified; check it in the pilot.

## Open decisions

1. **2Wiki license:** confirm Apache-2.0 from the original dataset source before publishing results.
2. **Claude credit:** confirm it is Console API credit and when it expires.
3. **Graph baseline in S3:** HippoRAG 2 depends on a one-document OpenRouter embedding test; LightRAG is the fallback.
4. **BYOK batch path:** sync and batch calls are confirmed BYOK end to end (2026-10-25). Left for the pilot:
   `cache_control` passing through the Batch API, and how the engine's `reasoning: {effort: none}` maps for Claude.

## Risks

- S0 may show the baseline ahead. The plan treats that as the starting point, not a failure.
- Wikipedia contamination in S3 (closed-book arm mitigates).
- Holm families grow with arms; keep one plain and at most one graph baseline per benchmark.
- Claude runs lose temperature-0 determinism; the paired design tolerates it, but say so in the write-up.
