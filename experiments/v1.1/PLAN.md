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
- How the arm enters the harness is settled by D-247 to D-250: LlamaIndex retrieves and writes a context export, a
  generate-only engine bin answers over it with the engine's own packer, strict `final_answer` schema (D-95) and
  `Answer:` rendering, and the harness journals the result as an external arm with its own fail-closed clauses.

### S1 details

- Paragraph-per-chunk was deliberate: it comes from the original structure-aware chunker (D-07, D-08: Markdown AST,
  headings and paragraphs as split markers). S1 keeps that design and adds the merge step it lacks (D-242): paragraph
  and heading boundaries stay the only split points, consecutive paragraphs in the same section merge up to the
  target, a paragraph longer than the target still splits by window, and no chunk crosses a heading.
- One target, 256 tokens (o200k), chosen to match the MultiHop-RAG paper (D-241). It replaces D-09's 500-character
  default for the S1 store only; no size sweep.
- Rebuild a second store (new embeddings, new deepseek extraction); keep the v1.0 store untouched.
- Compare arms on `answer_usable` and evidence Hits@4 only. Evidence Hits@4 matches gold evidence text, not chunk
  IDs, so the gold evidence is not re-mapped to the new chunks and chunk-ID Hits@4 is not reported for S1.
- Change chunking and nothing else. Model changes wait for S2 and S3.

### S2 details

- Replay the exact packed prompts from S1's journal so both readers see identical context and rerank jitter cannot
  differ between arms. The journal cannot rebuild the exact prompt (it keeps 512-character excerpts and no prompt), so
  the prompts come from each run's context export (D-249), not from a new engine prompt-dump switch.
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

Note (2026-10-30, D-255 facts): at current list prices (Sonnet 5.5 $2/$10, Haiku 5.5 $0.10/$0.50 per MTok, Batch
half) an S2 dev arm costs about $0.5 with Sonnet and $0.03 with Haiku, so the S2 rows above are far too high. The
other rows were not re-estimated. D-258 makes these figures a budget, not hard stops.

## Process

- No full GSD phase loop. One `EXPERIMENT-S{n}.md` per stage holds the hypothesis, arms, metrics, decision rule and,
  after the run, the result. Committed before the run, it is the pre-registration.
- Code changes (harness arm, substring Hits@4, chunker, prompt dump) go on their own branches with a code review
  before merge. The GSD harness has been removed from main; no GSD commands are part of this plan.
- This plan merges to main through a PR before S0 starts, so experiment branches can reference it.
- New decisions get IDs continuing from v1.0 (next free D-ID). A stage's own decisions are logged in its stage file;
  decisions that span stages are logged under Decisions below. A decision that meets the ADR bar (hard to reverse,
  surprising without context, a real trade-off) also gets an ADR in `docs/adr/`, linked from its D-ID.
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

### Code preparation decisions

Accepted by the owner on 2026-10-29. Terms follow [GLOSSARY.md](../../GLOSSARY.md).

- **D-247 External arm path.** An external arm retrieves outside Lancet and writes a context export. A generate-only
  engine bin reads it and runs the engine's own packer, strict `model_output` schema and `render_final_answer_line`:
  mode `pack` (no network; emits the request body, used for prompt parity and S2 request building) and mode
  `generate` (calls the configured reader). Rendering batch results is left to S2's own branch. Lancet arms keep their
  live gateway answer; each Lancet record gets a free check that re-packing its context export reproduces the
  checkpoint's `assembled_prompt` byte for byte. External records go into the same `journal.jsonl` with the same
  `RunRecord` shape and resume key, under an explicit external record kind with its own fail-closed clauses: a
  context export row with exactly k = 8 ranked evidence entries for every success record, every `document_id` in
  `document_map`, a pipeline-config echo equal to the pre-registration, one index fingerprint per arm, and the same
  generation model and provider as the Lancet arms. `index_generation` is checked per arm, not per journal. No engine
  snapshot fields are faked. The S0 Lancet arm is a new registry row, `hybrid+rerank+metadata`.
- **D-248 LlamaIndex arm.** A separate uv project, `baselines/llamaindex/`, pinned to current `llama-index-core`
  (0.14.25, not the paper's 0.9.40). Embeddings `voyageai/voyage-4-large` through OpenRouter (check that `input_type`
  passes through); rerank `voyageai/rerank-2.5-lite` through the same endpoint Lancet's rerank client uses, via a
  custom postprocessor; the same 346 documents Lancet seeds. Title, source and published_at go into the embedded text
  as in the paper; in the prompt they reach the reader as DocMeta tags, the same format as Lancet's metadata lever,
  with no duplicate in the node text. Its only output is the context export.
- **D-249 Context export from checkpoints.** The journal cannot rebuild the prompt. After each drive the harness
  exports the `terminal_success` checkpoint of every record from Postgres, joined on `correlation_id` (the engine's
  `trace_id`), into `context_export.jsonl` in the run directory: one row per question and arm with the question,
  ranked evidence (rank, chunk ID, document ID, full text, title, section, document metadata), graph facts and, for
  Lancet arms, `assembled_prompt`. It is a sixth required run artifact for v1.1 runs. `lancet-eval export-context
  --run <dir>` re-exports. `score` fails closed when a success record has no export row; a record that ended with no
  evidence exports an empty list. No engine prompt-dump switch is added. The S2 replay states which provider fields it
  rewrites, since the engine's `provider.require_parameters` and `order` cannot be sent for Claude.
- **D-250 Evidence Hits@4 and context tokens.** Evidence Hits@4 reuses `paper_question_scores` with `text_matcher`
  (spaces and newlines removed, case-sensitive substring) over the final evidence ranks 1-4 handed to the reader,
  with text from the context export, on the G population only, under the metric name `evidence_hits_at_4`. Hits@10,
  MRR and MAP are not reported (only 8 ranks exist). Chunk-ID Hits@4 stays a Lancet-only secondary. Context tokens are
  o200k counts of the exported evidence text; provider `prompt_tokens` is recorded but not compared across arms.
  Latency is reported per arm; the external arm's latency is marked not comparable end to end.
- **D-251 Merge chunker and S1 store.** A new chunk strategy (`structure-merge`) counts `chunk_size` and
  `chunk_overlap` in o200k tokens; `structure-aware` and D-09 are unchanged. A heading line opens the first chunk of
  its section and counts toward the target; no chunk holds the end of one section and the start of the next.
  Paragraphs merge greedily up to 256 tokens. A paragraph over 256 tokens closes the open chunk and splits into
  256-token windows with a 25-token overlap, never merged with neighbours. Merged chunks under 40 characters are
  kept; the extraction skip threshold is unchanged. The S1 store uses overlay `config.eval-s1.toml`,
  `data/lancedb-eval-s1` and Postgres schema `lancet_eval_s1`; `seed`, `reseed` and `preflight` take store and schema
  as parameters and refuse the v1.0 `data/lancedb-eval` and `lancet_eval`. Both stores' arms go into one journal with
  the store in the arm label (for example `small/hybrid+rerank+metadata`); `run --arms` drives one store's subset, and
  preflight refuses a stack whose store differs from the arm's declared store. S1 graph-on arms use the basic graph
  context (`disable_graph_context: false`, no `graph_v2` lever) on both stores.
- **D-252 Stage rules.**
  - S0: a decisional held-out reading, Holm family m = 1 (Lancet default vs LlamaIndex, `answer_usable`, exact paired
    sign-flip), null guard on both arms. Published as the external claim; it does not gate S1.
  - S1 (direction-finding, dev): adopt merged if `answer_usable` (merged-off minus small-off) has a point estimate
    above 0 and the null guard passes; the graph joins the final configuration only if merged-on minus merged-off is
    at least +5 points. p-values are reported, not used. Evidence Hits@4 is supporting.
  - S2 (direction-finding, dev): the reader with the highest `answer_usable` point estimate wins, unless a cheaper
    reader is within 2 points; every candidate passes the null guard. Opus 5.5 joins only if Sonnet minus Haiku is at
    least +5 points. D-245 is decided on this reading as a paired Haiku vs deepseek comparison that also requires a
    point estimate of at least -3 points.
  - S3: a decisional reading on the 2Wiki held-out part, read once, Holm family m = 3: graph-deepseek vs hybrid,
    graph-Haiku vs graph-deepseek, graph-Sonnet vs graph-deepseek. Closed-book, LlamaIndex and HippoRAG 2 are
    descriptive. The 2Wiki dev part serves the pilot and preflight only.
  - Confirm: a decisional held-out reading (second and last), Holm family m = 2: final configuration vs v1.0 default,
    final configuration vs LlamaIndex, on `answer_usable` with the null guard.
  - The harness computes paired differences, p-values and null guards; the choice on a direction-finding reading is
    applied by hand in its stage file. No automatic choice code.
- **D-253 Pre-registration form.** Each stage's pre-registration is a constant in `eval/src/lancet_eval/thresholds.py`
  (as `PREREGISTRATION_06_3_6`), cited by its `EXPERIMENT-S{n}.md` and committed with it before the paid run, so the
  D-73 git check still applies. Code preparation only makes the harness accept such constants (new arm labels,
  external arms, primary metric `evidence_hits_at_4`); each stage writes its own constant on its own branch.

### S2 code preparation decisions

Accepted by the owner on 2026-10-30. Facts checked that day: the engine's system message is one sentence, and the
static policy (about 400 o200k tokens) opens the user message; Sonnet 5.5 costs $2/$10 per MTok and Haiku 5.5
$0.10/$0.50, Batch half of that; Sonnet 5.5 rejects `thinking: disabled` and takes only `between_tools`, Haiku 5.5
takes `disabled` at effort high or below; OpenRouter maps `reasoning: {enabled: false}` to `thinking: disabled` and
documents no `between_tools`; Anthropic rejects `temperature` and `top_p` since API version 2026-10-21.

- **D-254 S2 replay path.** Harness subcommands, as `run-external`: `batch submit` packs each export row of the
  replayed S1 arm with `generate_from_context pack`, rewrites it per reader (D-255), prints a cost estimate and submits
  one batch per reader arm (`custom_id` = question ID, a manifest with the batch ID and a body hash per request written
  first, a second submit refused while one is pending, `--limit N` for the pilot, `--retry-errors` for failed requests
  only); `batch fetch` is re-runnable and journals each result once through a new `render` mode of the bin, which runs
  `generate`'s validation and `Answer:` rendering over a given output. Errored and expired requests become error
  records. The deepseek arm is not re-run: S1's records of the replayed arm are carried into the S2 run. `--arms`
  picks the replayed arm; the S2 stage file names S1's winner.
- **D-255 Claude request rewrite.** Only declared fields change: `model`; `provider` becomes
  `{only: ["anthropic"], allow_fallbacks: false}` (no `require_parameters`, no `order`); `temperature` and `top_p` are
  removed; `reasoning` follows a per-reader thinking table in the pre-registration (Haiku 5.5 `{enabled: false}`;
  Sonnet 5.5 `between_tools`; Opus 5.5, if it joins under D-252, thinking on at effort low). Every other byte stays as
  `pack` emits it. If the pilot shows OpenRouter cannot pass `between_tools`, the Sonnet arm goes through the native
  Anthropic Message Batches API with a converted Messages body (same message text); the converter is built with S2.
  A thinking-off reader with `reasoning_tokens > 0` fails closed.
- **D-256 No prompt caching.** The cacheable prefix is about 400 tokens, below the 512-token minimum of Haiku 5.5 and
  Sonnet 5.5, and a breakpoint would split the user message into parts that deepseek did not get. Even if it cached,
  a 351-question Sonnet sync reading would save about $0.25. Not built for S2 or later sync readings; revisit only if
  a shared prefix grows past the minimum (for example S3 few-shot extraction). Supersedes the reader row of the
  Prompt caching table below.
- **D-257 Reader arms.** Labels `<S1 arm>@<reader>` (for example `merged/hybrid+rerank+metadata@haiku-5.5`). A replay
  record kind with its own fail-closed clauses: the export row equals the source arm's row (hash); the sent body equals
  the `pack` body plus the declared rewrite; the model is the declared reader; `is_byok` is true and the provider is
  Anthropic; `reasoning_tokens` per D-255; the batch ID recorded. The carried deepseek records keep their export rows,
  source run and hash, so the S2 run directory scores alone. The report gives `answer_usable` on G, paired
  differences and the null guard per reader, and cost per answered question at sync list price × tokens for every
  reader (price table in the pre-registration; actual batch spend reported apart). No evidence Hits@4 for S2. Native
  target: see D-265.
- **D-258 Spend caps without truncation** (amends D-246). No stage stops halfway: a half-run arm is unusable and its
  spend sunk. A cost estimate is printed before a submit or a drive and never refuses. `run-external --stage-cap`
  stays built, but stage files set no cap or an unreachable one. D-246's figures remain the budget, not hard stops.
- **D-259 Code-prep follow-ups.** The bin reads the chunk index from `<document_id>#<n>` as well, so external evidence
  shows its real `chunk_index` (#47); the LlamaIndex export keeps `#`, since a `:` ID would look like a Lancet chunk
  ID. The external reader runs with `evidence_metadata` only, which matches the shipped default's reader-side levers
  (rerank is retrieval-side); S0's pre-registration states this and requires nothing more. The external record's
  generation model and provider order are taken from the `pack` body. S1's pre-registration constant is named
  `PREREGISTRATION_S1`, and S1 reads the levers-dev question set (the D-237 dev pool of 100).
- **D-260 Sonnet 5.5 thinking over OpenRouter** (owner ruling, 2026-10-30: "照 lane 51 的做法"). The OpenRouter body for
  a `between_tools` reader keeps #51's encoding: `reasoning` is dropped and a top-level `thinking: {type:
  "between_tools"}` is added. The paid S2 pilot checks `reasoning_tokens`; if OpenRouter drops the field, the arm goes
  through the native Anthropic Message Batches API (D-255). The replay clause on `reasoning_tokens` follows this: a
  reader declared `off` or `between_tools` must report 0, and a thinking-on reader (Opus 5.5 at effort low, D-252) is
  exempt.

### S0 and S1 pre-registration decisions

Decided by the owner on 2026-10-30, answering the S0/S1 pre-registration questions (lane prereg-s01). The stage files
are [EXPERIMENT-S0.md](EXPERIMENT-S0.md) and [EXPERIMENT-S1.md](EXPERIMENT-S1.md); the constants are
`PREREGISTRATION_S0`, `PREREGISTRATION_S1` and `PREREGISTRATION_S1_MERGED_GRAPH` in
`eval/src/lancet_eval/thresholds.py`; the run order is [RUN-S0-S1.md](RUN-S0-S1.md).

- **D-261 S0 null guard in both directions** (owner: "雙向讀，勝方須過"). D-252's "null guard on both arms" is read
  as one guard per direction over the same null pairs: `llamaindex` against the Lancet default as the lever
  comparison computes it (`b - c`), and the Lancet default against `llamaindex` with `b` and `c` swapped (`c - b`).
  An arm leads only if Holm rejects and the guard in its own direction passes; otherwise the difference is reported
  with the failed guard and no lead is claimed.
- **D-262 S0 and S1 reuse the v1.0 numbers** (owner: "全部沿用 v1.0"). alpha 0.05, null-guard margin 0.10 and pair
  fraction 0.80, complete-case floor 0.80, bootstrap 10,000 with seed 42, SC-2 timeout floor 0.025, rerank tripwire
  0.20 after 50 attempts or 5 consecutive degrades, all as in `PREREGISTRATION_06_3_6`.
- **D-263 S1 graph rule on the chosen store** (owner: "在選中的 store 上套用"). D-252's +5-point graph rule is read on
  the store S1 keeps: small graph-on against small graph-off if small is kept, merged graph-on against merged
  graph-off if merged is adopted. The lever comparison pairs every family arm with one reference, so the merged-store
  comparison has its own constant, `PREREGISTRATION_S1_MERGED_GRAPH`, equal to `PREREGISTRATION_S1` except for the
  arm roles.
- **D-264 S1 null guard vetoes both choices** (owner: "沿用 0.10/0.80，兩個選擇都否決"). On the 10 dev nulls the guard
  keeps margin 0.10 (a net abstention drop above 0.10 of the null pairs fails: 2 or more with 10 pairs, 1 or more with
  8 or 9) and pair fraction 0.80 (at least 8 null pairs). It is
  read for the chunking choice and for the graph choice; a failed or not-evaluable guard vetoes the choice it guards.
- **D-265 Replay clauses by reader target** (owner: "新增 D-ID", 2026-10-31; built in #90 for #82). The `is_byok`,
  `provider` and `reasoning_tokens` clauses depend on the reader's `target`. OpenRouter target: unchanged, `is_byok`
  is true and the provider is `"Anthropic"`. Native Anthropic target (D-255, D-260): `is_byok` is null, since that
  response reports none, and the provider is the endpoint host `"api.anthropic.com"` (`REPLAY_PROVIDERS` in
  `eval/src/lancet_eval/provenance.py`), since a native Message Batches result names no provider; a reader whose
  thinking is not `on` must record `content_block_types`, none of them `thinking` or `redacted_thinking`, and
  `reasoning_tokens` must still be 0. A thinking-on reader (Opus 5.5 at effort low) stays exempt. A new `prompt`
  clause: the `pack` body's user message (`parity.user_message`) equals the carried base row's `assembled_prompt` byte
  for byte, so the reader saw the prompt deepseek saw. Supersedes D-257's `is_byok`/provider wording for the native
  target.
- **D-266 S1 not-evaluable comparison and integer graph reading** (owner: "照建議 (Recommended)", 2026-10-31; #105).
  A comparison row with `evaluable: false` (fewer than 72 of the 90 dev G pairs, below the 0.80 complete-case floor)
  keeps small for the chunking choice and keeps the graph out for the graph choice, the same as a not-evaluable null
  guard (D-264). The graph rule's +5 points is read from the row's integers, `n_pos - n_neg >= ceil(0.05 * n_pairs)`,
  not from the float `delta`, which can print `0.049999999999999996` for exactly +5 points at 80 pairs. Amends the
  reading of D-252 and D-263; `PREREGISTRATION_S1` and `PREREGISTRATION_S1_MERGED_GRAPH` are unchanged. Written
  before any S1 data.

### S2 pre-registration decisions

Decided by the owner on 2026-10-31, answering the five open questions of the S2 draft (lane 110, #110). The stage
file is [EXPERIMENT-S2.md](EXPERIMENT-S2.md); its draft constant enters `eval/src/lancet_eval/thresholds.py` once, by
[RUN-S2.md](RUN-S2.md) step 4, because D-73 dates a constant by the first commit that adds its name to that file.

- **D-267 Opus 5.5 runs unconditionally as a descriptive arm** (owner: "是，無條件跑 (Recommended)", 2026-10-31, first
  decided in the owner's side session: "可以，都轉告coordinator"). The `<S1 winner>@opus-5.5` arm is in the S2 constant's
  `descriptive_arms` and the S2 corpus. It is read in the S2 pilot and submitted in the run of record in parallel with
  Haiku 5.5 and Sonnet 5.5. It is reported, with its paired difference against deepseek and its cost per answered
  question, but it does not enter D-252's winner rule or the Holm family, so m stays 2 (D-268). It is thinking on at
  effort low, so the replay clauses' thinking-on exemption applies (D-265). The owner's reason: the $200 Claude credit
  is lost if unused, so neither the cost nor the gate matters. Supersedes D-252's "Opus 5.5 joins only if Sonnet minus
  Haiku is at least +5 points" for S2.
- **D-268 D-245's "not significantly worse" reads the Holm-adjusted p** (owner: "Holm 調整後 (Recommended)",
  2026-10-31). Haiku 5.5 is significantly worse than deepseek only if Holm, over the S2 family (m = 2: Haiku 5.5 and
  Sonnet 5.5 against deepseek, alpha 0.05), rejects the Haiku row and its delta is negative. The raw p is reported,
  not read.
- **D-269 S2 reuses the v1.0 numbers; Opus at list price over OpenRouter** (owner: "沿用 + 查牌價 (Recommended)",
  2026-10-31). S2 takes D-262's and D-264's numbers: alpha 0.05, null-guard margin 0.10 and pair fraction 0.80,
  complete-case floor 0.80, bootstrap 10,000 with seed 42 (the SC-2 floor and rerank tripwire are carried, and no drive
  runs). Opus 5.5's reader row is `anthropic/claude-opus-5.5` over OpenRouter, like Haiku 5.5, at Anthropic's list
  price of $4 / $20 per MTok (input / output), read 2026-10-31 from
  https://platform.claude.com/docs/en/about-claude/pricing (claude.com/pricing agrees).
- **D-270 Three readings of D-252's S2 rule** (owner: "照草稿 (Recommended)", 2026-10-31). (a) deepseek is the null
  guard's reference and has no guard of its own; it stays a candidate. (b) If more than one cheaper reader is within
  2 points of the leader, the cheapest of them wins. (c) Two Claude readers are compared through their paired deltas
  against deepseek on the common population, since the lever comparison pairs each family arm with the reference
  only. Amends the reading of D-252; written before any S2 data.
- **D-271 deepseek generation and graph extraction pinned to Wafer US under a price cap** (owner: "照做
  (Recommended)", 2026-10-31; #118). Amends D-191. Both the engine's generation request and its graph extraction
  request send `provider: {order: ["wafer/us"], allow_fallbacks: false, max_price: {prompt: 0.07, completion: 0.45}}`
  (generation keeps D-96's `require_parameters: true` beside it; extraction sends none, as before). `max_price` is in
  US dollars per million tokens; OpenRouter refuses a request that no allowed endpoint can serve under the cap. Before
  this, extraction sent no provider pin, and generation was pinned to `sail-research` with no variant, so OpenRouter
  could serve any Sail Research endpoint: **S0's generation ran on `sail-research`**, so S0 and S1 differ in serving
  provider. Reason (owner's OpenRouter stats for `deepseek/deepseek-v4-flash-0731`, 2026-10-31): wafer/us lists
  0.0448 / 0.30 $/M with P50 / P90 / P99 latency 0.33 / 0.58 / 3.39 s, against sail-research's 0.15 / 0.30 $/M and
  0.95 / 1.74 / 3.85 s; baidu (90% promotional discount) and deepinfra (P99 5.55 s) were excluded. The cap leaves
  headroom over Wafer's list price and stops a silent move to a dearer endpoint. Syntax checked 2026-10-31 against
  https://openrouter.ai/docs/guides/routing/provider-selection: `max_price` is an object of `prompt` / `completion`
  (also `request`, `image`) in $ per million tokens, and an `order` slug may name one endpoint as
  `provider[/variant][/region]`. That page does not list `wafer/us` itself; the slug is the owner's, read from the
  model's provider list. Set in `config/config.toml` (`generation_provider_order`, `generation_max_price_prompt`,
  `generation_max_price_completion`); not environment-overridable. Must merge before S1 step 4.2.
- **D-272 Extraction output cap raised from 768 to 16,384 tokens, extraction timeout 120 s** (owner: "停、修、重建 (Recommended)", 2026-10-31;
  #118). The S1 seed lost about 18% of chunks to graph extraction: at 113 of 346 documents, 215 of 1,226 chunks failed
  all 3 attempts, every one a SchemaValidation "EOF while parsing", a truncated JSON answer. The engine built the
  extraction request's `max_completion_tokens` from a hard-coded 768 in `engine/src/main.rs` (not from
  `max_output_tokens = 2048`, which is generation's and is unchanged). Extraction now sends its own cap,
  `EXTRACTION_MAX_COMPLETION_TOKENS = 16384` in `engine/src/graph/extraction.rs`, apart from the generation limits
  (which stop at 4,096). Sizing: a schema-maximal answer (32 entities, 64 relations, every string at `maxLength`,
  pretty-printed) is about 35,600 bytes, estimated at about 11,900 tokens at 3 bytes a token; 16,384 holds that with a
  25% margin, and a test pins it. Billing is per token produced. wafer/us lists a max completion of 943,718 tokens
  (OpenRouter endpoints API, 2026-10-31). The seed was stopped; the S1 store is rebuilt after this merges.
  Extraction also gets its own HTTP timeout, `EXTRACTION_TIMEOUT = 120 s` (the coordinator's call within the owner's
  answer above): at wafer/us's P50 of about 112 tokens/s a schema-maximal answer takes about 106 s, and 2,000 to 4,000
  tokens can pass 30 s at its P99 of about 43 tokens/s, so the old 30 s would turn truncations into timeouts.
  Generation keeps `generation_timeout_secs = 30` and `max_output_tokens = 2048`, so S0/S1 generation stays
  comparable. The token estimate assumes English text; a non-ASCII maximal answer (about one token per character)
  would not fit, which the MultiHop-RAG news corpus does not reach. The rebuild's `extraction_attempt` outcomes
  (`call_failed` with a timeout or a truncation) are the check.
- **D-273 S1 excerpt cap 2,048 characters** (owner: "開 lane 修 #120 (Recommended)", 2026-10-31; #120). S1's step
  1.5 preflight failed `corpus_generation` on a truncated excerpt: `[engine.retrieval] excerpt_max_chars = 512` in
  `config/config.toml` cut nearly every merged chunk, and `fact_matches_excerpt` reads a truncated excerpt as
  UNDECIDABLE, so evidence Hits@4 (one of S1's two metrics) would have been mostly undecidable for the merged arms.
  Measured read-only from the built store (`data/lancedb-eval-s1`, `nodes.content`, 3,953 chunks, 2026-10-31): the
  longest S1 chunk is 1,489 Unicode characters (p50 990, p90 1,201, p99 1,339), and 3,708 chunks exceed 512.
  `config/config.eval-s1.toml` now sets `excerpt_max_chars = 2048`, 37% above the longest chunk; a test holds the cap
  at least 25% above 1,489. This changes measurement only, so "change chunking and nothing else" holds: the cap
  (`citation_excerpt_max_chars`) shapes only the excerpts of `RetrievalSnapshot.retrieved_chunks` (RetrieveNode) and of
  the resolved citations (GenerateAnswerNode, after generation); the prompt is packed from the full evidence block text.
  The judge reads citation excerpts under its own 1,500-character per-passage budget, so at 512 it would have seen S1
  passages cut and v1.0 passages whole; 2,048 removes that difference.
  The v1.0 arm (`config.toml`, `config.eval.toml`) stays at 512, which its 55-token chunks never reach. Applies to every
  arm run under `LANCET_ENV=eval-s1`; no re-seed is needed, since excerpts are cut at query time.
- **D-274 S2 reads K = 5 replicates per question and arm, tested by sign-flip permutation** (owner: "全部 K=5",
  2026-10-31; #123). Supersedes the exact sign test for S2's comparisons (D-123 as D-269 carries it). The S1 dev run
  showed the deepseek reader flipping `answer_usable` on about 4% of byte-identical prompts (3 of 68), at temperature
  0, and the Claude 5.5 readers take no temperature, so resampling is the only noise control. Every S2 arm (deepseek,
  Haiku 5.5, Sonnet 5.5, Opus 5.5) answers each of the 100 dev questions 5 times, each answer its own batch request
  (`custom_id` `<question ID>_r<k>`) and its own journal record (`RunRecord.replicate`, 1 to 5; a unit is a question,
  an arm and a replicate). The deepseek arm's replicate 1 is S1's carried answer; replicates 2 to 5 are new answers to
  the same `pack` body, sent unrewritten through an OpenRouter batch, which carries D-271's pin (wafer/us,
  `allow_fallbacks: false`, `max_price`); they are replay records with their own clauses (`provenance`: the body hash
  is the `pack` body's, nothing rewritten, the body's model, `is_byok` false on OpenRouter credit, the pinned provider,
  0 reasoning tokens when the body turns reasoning off). A question's score is the mean `answer_usable` over its 5
  answers; a question enters a comparison only when all 5 answers of both arms are ok. Main test: the exact two-sided
  sign-flip permutation test on the per-question mean differences (each times 5 is an integer, so the 2^n sign
  vectors are counted exactly, with no seed; `stats.exact_signflip_p_integer`), Holm over the family as before. Cross
  check: a paired t-test on the same differences, reported beside it (`paired_t_p`) and never read for a decision.
  CI: the percentile bootstrap over questions, 10,000 resamples with seed 42, each question carrying its 5 answers
  (the bootstrap resamples the per-question means). The null guard pairs replicate k of the arm with replicate k of
  the reference, so its counts are 5 times the questions' and its net loss rate is the mean per-question abstention
  drop; the 0.80 pair floor still counts questions. Its pass or fail is read; the one-sided bound printed beside it
  treats the 5 pairs of a question as independent, so it is too narrow and is not read. A question with a failed or
  missing answer under an arm leaves that arm's reader row (cost and usable share) as it leaves its pairs. Written into `PREREGISTRATION_S2` as `replicates=5` and `test=
  "paired_sign_flip_permutation_exact_two_sided"` (`thresholds.REPLICATE_TEST`). Journals before S2 have no
  `replicate` field, read as replicate 1, and score and compare byte-identically (six committed runs re-scored in
  memory, 2026-10-31). `report.json` reads each unit's replicate 1; the 5-answer reading is `compare-levers`'.
  Evidence (owner's research, 2026-10-31): Miller 2024 (arXiv 2411.00640), Thinking Machines 2025 on batch
  invariance, Atil et al. (arXiv 2408.04667), Bowyer et al. (arXiv 2503.01747). Cost: about $13 of Claude credit
  (ceiling about $30, BYOK) and about $0.7 of OpenRouter credit for the deepseek replicates.
- **D-275 S2 reader rule: the cheapest eligible reader, unless a dearer one is significantly better** (owner:
  "預設最便宜，顯著才換 (Recommended)", 2026-10-31; #127). Amends D-270b (and D-252's "highest point estimate unless a
  cheaper reader is within 2 points"). The candidates are deepseek and the Claude readers whose null guard passes
  (D-270a). The candidate with the lowest cost per answered question (D-257, sync list price times tokens, over all 5
  replicates) is the starting pick, and it wins unless a dearer candidate is significantly better on `answer_usable`
  than it. Significance: every pair of candidates is tested with D-274's test on that pair's population (the
  `reader_comparison` pairs), Holm runs once over all those pairs (m = the number of candidate pairs, 3 with three
  candidates) at alpha 0.05, and a dearer reader is significantly better when Holm rejects its pair with the current
  pick with a positive delta. When one is, the pick steps up to the cheapest such reader and the check repeats
  against the readers dearer than it; the pick no dearer candidate is significantly better than wins. So a dearer
  reader that beats a cheaper one is never passed over for that cheaper one. The pairs' raw p-values are in
  `lever-comparison.json`; Holm over them is applied by hand. (The owner's words fix the rule; the step-up for more
  than one dearer candidate and Holm over all candidate pairs are this lane's reading of them.) The 2-point
  margin was far below both the noise floor (about 4% flips) and the smallest detectable effect, so the
  old winner could be picked by noise. The pre-registration states the expected smallest detectable effect, about 8.4
  points at K = 5 and n = 90 (two-sided 0.05, power 0.8; #127), so picking the cheapest reads as "no larger difference
  detected", not as equivalence. Opus 5.5 stays descriptive (D-267), and D-245's default-model switch is unchanged.
- **D-276 Answer normalisation and a dual-judge secondary** (owner: "正規化＋裁判當次要 (Recommended)" and
  "gpt-4o-mini＋Sonnet 雙裁判", 2026-10-31; #124). Amends D-70's `answer_usable` for v1.1, applied to every arm.
  - *Normalisation (primary).* `gold_contained` keeps D-70's whole-token containment ("no" never matches "not") and
    adds two folds. A token also matches its plural or singular: a token of four letters or more ending in `s` (not
    `ss`, `us` or `is`, holding no digit, and not a listed non-plural such as "news") may drop its `s`, drop `es`
    after s, x, z, ch or sh when three letters or more remain, or turn `ies` into `y` ("houses"/"house",
    "boxes"/"box", "movies"/"movie"); nothing else changes, so "plane" never meets "plan", "1990s" never meets
    "1990", and "uses" never meets "US". A list gold, with items separated by
    commas (not inside a number such as "1,200"), semicolons, `&` or "and", also matches when every item is
    contained in a span of its own, in any order ("Johnson & Johnson" needs two "johnson" tokens). Both folds only
    turn misses into hits. Known looseness, left to the judges: the list fold reads "and" inside a name ("Barnes and
    Noble") as a separator, and matches items under a negation ("neither Alice nor Bob"). S1's three artifact cases: "Travis
    Kelce and Taylor Swift" and "sportsbook" now match; "no lack of functionality" for a "no" gold still matches,
    since the folds are lexical, and is left to the judges. `final_answer_em` (exact equality) and the null guard's
    abstention predicate (`is_abstention`, equality with "insufficient information") are unchanged. The
    `gold_containment` diagnostics, which call `gold_contained` on the whole answer, take the folds too.
    `metrics.answer_rule("d70")` keeps the old rule selectable: v1.0's recorded reports were written under D-70, and
    their re-read guards pin it.
  - *Dual judge (secondary).* `lancet-eval judge-answers --run <dir>` asks `openai/gpt-4o-mini` (the v1.0 judge) and
    Claude Sonnet 5.5 over OpenRouter BYOK whether each G record's extracted final line is equivalent to the gold.
    Each judge sees only the question, the gold answer and the line as written (citation markers removed, not
    normalised), never the arm, so one verdict serves every arm that wrote the same line. Each replicate is judged.
    It writes `answer-judge.json`: per-arm rates for the primary and both judges (a judge's rate over the records
    it judged; failed requests are counted apart), and every record where the three disagree, for the owner to
    review. A cost estimate is printed first (D-258). The
    judges decide nothing; the primary stays `answer_usable`.
  - *Same-family exception.* The v1.0 rule that a judge is never the generator (`score.py`) stays for v1.0 scoring.
    The Sonnet judge is allowed for this secondary only, because the dual-judge design measures self-preference:
    Sonnet's verdicts on Claude readers' lines are compared with gpt-4o-mini's, a family distinct from every S2
    reader.
  - *S0 and S1 re-scored* (in memory, 2026-10-31; nothing under `eval/runs/` rewritten). S0: no `answer_usable`
    value changes on either arm (224 of 308 G each), so its reading stands. S1: six records turn usable (the order
    and plural cases). Small graph-off 0.8778 to 0.9000, merged graph-off 0.8667 to 0.8778, small graph-on 0.7889
    to 0.8111, merged graph-on 0.8333 to 0.8444. Chunking delta -1.1 to -2.2 points (n_pos 4 to 3, n_neg 5), so
    small is still kept; small-store graph delta -8.9 points both ways and merged-store graph -3.3 points both ways;
    every null guard passes. No S0 or S1 decision changes.
- **D-277 S2 prices deepseek at Wafer's wafer/us price, inside the pre-registration** (owner: "改用 Wafer 實際價
  (Recommended)", 2026-10-31; #133, audit-s2 P1). Amends D-257's deepseek price for S2. D-275 starts from the reader
  with the lowest cost per answered question, and deepseek was priced at D-257's 2026-10-09 OpenRouter list price
  ($0.0137 / $1.28 per M tokens, `measure.GENERATION_LIST_*`). At S1's tokens that put deepseek within about 3% of
  Haiku 5.5, so the starting pick would hang on tokenizer and answer-length noise, and that price lay outside
  `PREREGISTRATION_S2`, where D-73 could not freeze it. D-271 pins deepseek to Wafer's wafer/us endpoint, so S2 prices
  it there: $0.0448 in / $0.30 out per M tokens, the Wafer price D-271 and `config/config.toml` record (the
  owner's OpenRouter stats, 2026-10-31). OpenRouter's endpoints API listed $0.0434 in for wafer/us the same day; the
  3% difference cannot move the starting pick, and the recorded figure is the one D-271 was decided on. It is the constant's `reference_price` (a field of `ReplayStagePreRegistration`), read by `compare-levers`
  for the deepseek reader row and by `batch submit` for the deepseek replicates' estimate; without it both keep the
  list price, so earlier runs read as before. `measure.py`'s v1.0 constants are unchanged.
- **D-278 deepseek's S2 replicates go through OpenRouter's sync API** (owner: "改走同步 API (Recommended)",
  2026-10-31; #133, audit-s2 B1). Amends D-274's transport for deepseek; the Claude readers keep their batches.
  D-274 sent deepseek's replicates 2 to 5 through an OpenRouter batch, which cannot work. OpenRouter's Batch API takes
  only `only` and `allow_fallbacks` in its batch-level `provider` (`order`, `sort` and every other routing preference
  are rejected), a `provider` inside a request body does not route the batch, and
  `deepseek/deepseek-v4-flash-0731` has no batch variant (its only deepseek batch model is `deepseek-v4.1-flash`,
  served by Sail Research and DeepInfra), so a batch submit returns 400 (checked 2026-10-31:
  https://openrouter.ai/docs/batch-quickstart, https://openrouter.ai/docs/api/api-reference/batch/create-a-batch and
  `GET /api/v1/models`). Each deepseek replicate is now the engine's `pack` body, unrewritten, posted alone to
  `POST /api/v1/chat/completions`, so D-271's whole pin routes it (`order: ["wafer/us"]`, `allow_fallbacks: false`,
  `max_price`) on the same model as S1's answer. `batch submit` on the deepseek arm prints the D-258 estimate first,
  then sends one request at a time and journals every 20 (`batch.SYNC_CHUNK`) under a `sync-` ID, so a crash loses at
  most 20 billed answers and a rerun sends only the replicates that hold no record. A failed request is a retryable
  error record (`--retry-errors`). The replay clauses are unchanged: the body hash, nothing rewritten, the body's
  model, `is_byok` false, the pinned provider, reasoning off with 0 tokens. Full price, no batch discount: about $0.08
  of OpenRouter credit for 400 answers at D-277's Wafer price.
- **D-279 An OpenRouter batch row's `is_byok` is its batch's** (owner: "開 lane，batch 層 is_byok (Recommended)",
  2026-10-31; #137). Amends D-265's source of `is_byok` for OpenRouter batches. The S2 pilot's Haiku 5.5 and Opus 5.5
  batches (`batch-1793513172-NhwtnmeA5URdHsPsd9jp`, `batch-1793513183-UANxDGyr1uRrJb2Y8eEf`, both `completed` and
  billed over BYOK) showed that each row of a finished batch's `results` carries its chat completion in
  `response.body` beside a `status_code`, and that a row's `usage` reports token counts but no `is_byok` or cost: only
  the batch-level `usage` reports `is_byok: true` (with `cost: 0` and the upstream cost). So every row of a batch takes
  the batch-level `usage.is_byok`, and the `is_byok` clause reads that value; a batch that reports none, or false, fails
  the clause on every row. The row's own `provider` (`Anthropic`) and `model` (the undated slug) are still checked per
  row; the batch-level `model` is dated. A row with a non-2xx `status_code`, or no body, is an `errored` record, and a
  batch that fails as a whole puts its `error.message` into each request's error record. D-278's sync replies report
  `is_byok` per reply and are unchanged.

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

Note (2026-10-30, D-256): the reader row is superseded. The engine's system message is one sentence; the static
policy (about 400 tokens) opens the user message, below the 512-token minimum, so no reader breakpoint is sent.

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
