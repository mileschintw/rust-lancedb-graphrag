# v1.1 experiment plan (draft)

Status: draft for owner review, 2026-10-25. Findings and sources are in [RESEARCH.md](RESEARCH.md).

## Goal

Show where Lancet stands against reference points it did not choose, then improve it honestly:

- **Usable:** answer quality on held-out questions, compared with a standard pipeline on the same models.
- **Credible:** every decisional reading keeps the v1.0 guards: paired arms, a pre-registration committed before the
  paid run, Holm correction, fail-closed reporting, held-out read once per stage.

Non-goals: tuning until the graph looks good; reporting gains measured only against Lancet's own earlier versions.

## Stages

Each stage gates the next. Each stage gets its own pre-registration (arms, primary metric, decision rule) committed
before its held-out read.

| Stage | Question | Arms | Benchmark | Paid by |
|---|---|---|---|---|
| **S0 Baseline** | Where does Lancet stand against the MultiHop-RAG paper's own pipeline? | Lancet shipped default (hybrid + rerank + metadata); LlamaIndex paper config with Lancet's prompt | MultiHop-RAG held-out | OpenRouter, small |
| **S1 Chunking** | Do merged chunks of about 256 tokens beat paragraph fragments? | small vs merged chunks, each with graph off and on (deepseek extraction) | MultiHop-RAG dev, then held-out | OpenRouter, re-embed and re-extract, a few dollars |
| **S2 Reader** | How much does the answering model matter on identical context? | deepseek vs Claude reading the same replayed prompts | MultiHop-RAG held-out, S1's winning chunking | Claude Batch, about $2-4 per Sonnet arm |
| **S3 Writer and graph** | Does the extraction model matter where a graph has room to help? | closed-book; Lancet hybrid; Lancet + graph (deepseek writer); Lancet + graph (Claude writer); LlamaIndex; optional HippoRAG 2 | 2WikiMultiHopQA subset (or MuSiQue) | most of the Claude credit |

### S0 details

- Build the LlamaIndex arm per RESEARCH.md section 3: `SentenceSplitter(256, 25)`, dense top 20, rerank with
  `voyageai/rerank-2.5-lite`, keep 8, document metadata as in the paper, Lancet's generation prompt.
- Add evidence-substring Hits@4 to the harness and score every arm with it. Keep the chunk-ID Hits@4 as a
  Lancet-only secondary.
- Primary metric: `answer_usable` on the G population. Supporting: substring Hits@4, context tokens, latency.
- Expect the baseline may win today (256-token chunks vs Lancet's 55). That is the point of measuring first.
- Open item: how the arm enters the harness. Its records need the same journal shape, pairing and fail-closed rules.
  "Lancet's prompt" also includes the engine's strict `final_answer` schema (D-95), so copying the prompt text alone
  will not reproduce the `Answer:` line. A shared step that exports each arm's retrieved context, plus one generation
  step over it, would serve both S0 and S2's replay.

### S1 details

- Change the chunker to merge consecutive paragraphs up to a token target, keeping section boundaries. Decide first
  whether paragraph-per-chunk was a deliberate "structure-aware" choice, and write the new rule down.
- Rebuild a second store (new embeddings, new deepseek extraction); keep the v1.0 store untouched.
- Re-map gold evidence to the new chunks; compare arms on `answer_usable` and substring Hits@4 only.
- Change chunking and nothing else. Model changes wait for S2 and S3.

### S2 details

- Replay the exact packed prompts from S1's journal so both readers see identical context and rerank jitter cannot
  differ between arms. Open item: confirm the journal can rebuild the exact prompt; if not, add a prompt-dump switch to
  the engine first.
- Runs offline through the Batch API from a Python script; no Rust Anthropic adapter needed for this stage.
- Default reader: Sonnet 5.5 with thinking off (`between_tools`); decide whether to add Opus 5.5 after a pilot.

### S3 details

- Ingest the 2Wiki subset (passages already split; about 6,119 extraction calls).
- Claude extraction runs offline through Batch into graph side tables, as graph-v2 did; entity names re-embedded with
  Voyage.
- A closed-book arm guards against memorised Wikipedia answers; report gains over it.
- Pilot first: a few hundred chunks per candidate writer (Haiku 5.5, Sonnet 5.5, Opus 5.5) to measure real tokens and
  cost and to decide which writers get a full run.

## Budget sketch (estimates until pilots run)

| Item | Estimate |
|---|---|
| S0, S1 (OpenRouter only) | a few dollars plus re-embedding |
| S2 Sonnet reader, dev and held-out | about $10-20 of Claude credit |
| S3 pilots | under $5 |
| S3 Sonnet extraction (2Wiki, Batch) | about $7-14 |
| S3 Claude reader arms | about $10-20 |
| Reruns and preflights | about $15 |
| **Total Claude credit** | **about $45-75 of $200**, leaving room for an Opus writer point |

## Process

- No full GSD phase loop. One `EXPERIMENT-S{n}.md` per stage holds the hypothesis, arms, metrics, decision rule and,
  after the run, the result. Committed before the run, it is the pre-registration.
- Code changes (harness arm, substring Hits@4, chunker, prompt dump) go on branches with code review; small ones via
  `/gsd-quick` if convenient.
- New decisions get IDs continuing from v1.0 (next free D-ID) and are logged in the stage file.
- `.planning/` stays read-only as the v1.0 record.

## Open decisions

1. **Second benchmark:** 2WikiMultiHopQA (cheaper, clearest published graph gain, license from secondary sources) or
   MuSiQue (harder, CC BY 4.0 in the source repo, about twice the cost).
2. **Claude credit:** confirm it is Console API credit and when it expires.
3. **Graph baseline in S3:** HippoRAG 2 depends on a one-document OpenRouter embedding test; LightRAG is the fallback.
4. **Reader integration beyond S2:** build a native Anthropic Messages adapter in the engine, or use OpenRouter BYOK.
5. **Chunker intent:** confirm whether paragraph-level chunking was deliberate before S1 changes it.

## Risks

- S0 may show the baseline ahead. The plan treats that as the starting point, not a failure.
- Wikipedia contamination in S3 (closed-book arm mitigates).
- Holm families grow with arms; keep one plain and at most one graph baseline per benchmark.
- Claude runs lose temperature-0 determinism; the paired design tolerates it, but say so in the write-up.
