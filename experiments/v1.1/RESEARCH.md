# v1.1 research: why the graph lost, external baselines, second benchmark

Status: research notes, 2026-10-25. Nothing here is a result of record. The per-type numbers below are a descriptive
recount of an existing journal, not a pre-registered reading.

## 1. Starting question

*MemoryTax: The Bitter Lesson of Agent Memory* (arXiv 2610.29823) ran four memory methods (full context, BM25, Mem0,
Zep) and three coding agents with GPT-4o-mini, GPT-6 Luna and Claude Opus 5.5 as writers and readers. One finding is
that agent memory "has a ceiling, set by the model that writes it: a stronger reader does not recover what a weaker
writer left out" (on Zep, GPT-4o-mini wrote and read at 43%; Opus reading the same graph reached 45%; Opus writing and
reading reached 87%). Its broader thesis is that designed memory is a costly patch for a weak model, and that keeping
the raw history for a strong model to search does better.

Two limits matter when carrying this over. The study is small by its own account: one LoCoMo conversation (419 turns,
152 questions) and one run per cell. And its memory stores *replace* the raw history for the reader, while Lancet
always keeps the raw chunks and adds the graph as one more ranked list, which is the safeguard the paper recommends.

Lancet's graph was extracted and read by the same cheap model, and the graph never beat plain hybrid on held-out
([evaluation.md](../../docs/evaluation.md#graph-cost-reconciled)). Was the extractor the cause?

## 2. What the existing store and runs show ($0 probes)

**Extractor provenance.** The `data/lancedb-eval` graph was written 2026-08-31 to 2026-09-02, most likely by
`deepseek/deepseek-v4-flash-0731` with `reasoning: {effort: none}` (inferred from table write times against the repin
plan and commit times, not from a recorded field), 768 max output tokens, one call per chunk.
Extraction reuses `generation_model` (`engine/src/main.rs:138`). Quick task 260831-az7 made the switch. Graph-v2
(D-138) merged aliases and did no re-extraction.

**Extraction quality is not obviously the bottleneck.**

| Probe | Reading |
|---|---|
| Junk entities (schema words such as `string`, `type` as names) | 295 of 27,855 (about 1%); 60 chunks have only junk |
| Chunks with no entity at all | 4,721 of 18,576 (25%); 3,182 chunks are under 40 characters (`MIN_CHUNK_CONTENT_LENGTH`) and never reach extraction, so at most about 1,539 (8%) are extractor misses |
| Edge sample | mostly sensible, e.g. `Chris Paul -PLAYS_FOR-> Phoenix Suns`; relation names are free-form with mixed case |
| Held-out graph-arm questions with `GRAPH_UNAVAILABLE` | 149 of 351 |
| ... of those, questions with 2 or more capitalised mentions that exactly match an entity name | 106 of 149 (71%); 172 of 202 among questions that did get graph facts |

Seeding takes no model call (D-75), so for most no-fact questions the entities exist and the failure is in seeding or
path search, not in extraction. The mention regex is crude, so treat 71% as a rough figure.

**The benchmark's question shape works against an entity graph.** `answer_usable` on held-out G questions, lever run
`eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout/`:

| Question type | n | hybrid | +graph | +rerank | +metadata |
|---|---|---|---|---|---|
| inference | 105 | 0.962 | 0.962 | 0.981 | 0.971 |
| comparison | 125 | 0.448 | 0.456 | 0.544 | 0.552 |
| temporal | 78 | 0.244 | 0.205 | 0.385 | 0.295 |

- Inference questions are at the ceiling.
- Comparison and temporal questions turn on *which outlet said what, and when*. The entity graph stores neither
  publisher nor date, which is why the metadata lever helped and the graph did not.
- Questions name every entity, so there is no bridge entity for path search to find.

**The chunker emits paragraph fragments.** `append_region` (`engine/src/chunker/mod.rs:144`) turns every `\n\n`
paragraph into its own chunk and never merges short paragraphs. `target_size` (500, counted in characters, not
tokens) only splits long paragraphs. The store's 18,576 chunks average 204 characters (median 170), about 55 tokens.
The MultiHop-RAG paper used 256-token chunks, roughly five times larger. Effects:

- Eight retrieved chunks hold about 500 tokens of evidence per question (o200k; mean 504, median 504 on the 10-10
  `hybrid` arm; 544 with rerank), without the article context around each fragment. The paper's top 6 chunks of 256
  tokens would hold up to about 1,500.
- Extraction sees one paragraph at a time, so cross-paragraph references ("he", "the company") are lost.
- v1.0 recorded chunking comparison (DATA-02) as out of scope and unmeasured.

**This agrees with the literature.** Han et al. (arXiv 2502.11371, Table 2, verified 2026-10-25) on MultiHop-RAG,
Llama 3.1-8B generator:

| Method | Inference | Comparison | Temporal | Overall |
|---|---|---|---|---|
| RAG | 92.16 | 57.59 | 30.70 | 67.02 |
| KG-GraphRAG (triplets + text) | 67.40 | 34.70 | 17.15 | 48.51 |
| Community-GraphRAG (local) | 86.89 | 60.63 | 50.60 | 69.01 |

The 70B generator shows the same order. The paper's graphs were built with GPT-4o-mini, also a small writer model.
Lancet's graph is closest to the KG-GraphRAG kind, though it fuses graph-found chunks into RRF rather than feeding
triplets alone. Xiang et al. (arXiv 2506.05690) report the same split: plain RAG wins fact
retrieval, graphs win complex reasoning and summarisation.

**Conclusion.** Re-extracting with a stronger model alone is unlikely to make the graph win on MultiHop-RAG. Chunk
size and question shape matter more. The writer-model question is better tested on a benchmark where a graph has
room to help.

## 3. External baseline

Goal: claims of the form "Lancet X% vs a standard pipeline Y%" on the same questions and models, so the reference
point is not one Lancet chose.

### MultiHop-RAG paper configuration (recommended plain baseline)

From the paper and its repo (`yixuantt/MultiHop-RAG`, pins `llama-index==0.9.40`):

- `SentenceSplitter(chunk_size=256, chunk_overlap=25)` (overlap is in the code only), `VectorStoreIndex`, each
  document carrying title, source and published_at metadata.
- Dense top 20, `bge-reranker-large` keeps top_n = K (paper reports K = 10 and K = 4).
- Generation: top 6 chunks, 2,048-token cap, `gpt-3.5-turbo-1106` at temperature 0; the prompt is not in the paper.
- The repo's QA scorer counts a hit when prediction and gold share any one token. That is looser than
  `answer_usable`, so the paper's QA accuracies are not comparable to Lancet's.
- The repo's retrieval scorer counts a gold evidence fact as found when it appears (whitespace removed) as a
  substring of a retrieved chunk. It does not depend on chunk IDs.

### Candidates compared

| | LlamaIndex | LangChain | Haystack | MS GraphRAG | LightRAG | HippoRAG 2 |
|---|---|---|---|---|---|---|
| Used as a paper baseline | yes (MultiHop-RAG; Han et al.) | none found | none found | yes | yes | yes, most cited graph baseline 2025-26 |
| OpenRouter + Voyage | `OpenAILike` / `OpenAILikeEmbedding` | works with a flag | unverified | LiteLLM; set vector size 1024 | official OpenAI-compatible demo | base URLs exist; embedding endpoint support is an open README TODO (unverified) |
| Indexing LLM tokens (MuSiQue, HippoRAG 2 Table 12) | embeddings only | embeddings only | embeddings only | 115.5M in / 36.1M out | 68.5M / 18.3M | 9.2M / 3.0M |
| Output usable for Hits@4 | yes | yes | yes | no (community summaries) | no (mixed entity/relation/chunk context) | yes (ranked passages) |
| License; last release seen | MIT; core 0.14.25 (2026-09-21) | MIT | Apache-2.0 | MIT | MIT; 1.5.7 (2026-09-02) | MIT; PyPI 2.0.0a4 (2025-06, may be stale) |

Recommendation: the paper's LlamaIndex configuration as the one plain baseline; HippoRAG 2 as the optional graph
baseline if a one-document test embeds through OpenRouter, else LightRAG (scored on `answer_usable` only).

### Fairness rules

1. Same 346 documents, same questions, same embedding, rerank and generation models.
2. Primary arm: the framework's retrieval with Lancet's generation prompt. Without the `Answer:` line,
   `answer_usable` would fail the baseline on format alone. Han et al. and HippoRAG 2 also used one shared generation
   step across methods. A framework-default-prompt run may be reported as a secondary, non-decisional check.
3. Fixed k = 8 final chunks; report context tokens per arm.
4. Score Hits@4 for every arm, Lancet included, by evidence-substring match, not chunk ID. This also keeps Hits@4
   comparable after a re-chunk.
5. Swap `bge-reranker-large` for `voyageai/rerank-2.5-lite`, so the difference isolates Lancet's hybrid retrieval
   and graph. Whether LlamaIndex has a Voyage rerank postprocessor is unverified.
6. One plain baseline and at most one graph baseline, because every arm joins the Holm family.
7. Check whether OpenRouter forwards Voyage's `input_type` (query vs document); if Lancet sends it and the framework
   cannot, the embeddings differ.

## 4. Second benchmark

| Benchmark | Corpus (rough tokens) | Questions | Answers / gold evidence | License | Contamination | Published graph vs plain RAG |
|---|---|---|---|---|---|---|
| MultiHop-RAG (current) | post-cutoff news | 4 types | short / yes | in use | low | triplet KG loses; community graph helps temporal |
| **2WikiMultiHopQA** (HippoRAG 2 subset) | 6,119 passages, about 0.75M | 1,000; bridge, comparison, inference, compositional | short / supporting facts | Apache-2.0 (secondary sources only) | high (Wikipedia) | HippoRAG 2 71.0 vs dense 61.5 F1; recall@5 90.4 vs 76.5 |
| MuSiQue (HippoRAG 2 subset) | 11,656 passages, about 1.5M | 1,000; 2-4 hop | short / supporting paragraphs | CC BY 4.0 (in repo) | high | 48.6 vs 45.7 F1 |
| HotpotQA (HippoRAG 2 subset) | 9,811 passages, about 1.6M | 1,000 | short / supporting facts | CC BY-SA 4.0 (secondary) | very high | flat, 75.5 vs 75.3 |
| GraphRAG-Bench Novel (2506.05690) | about 1.1M | about 2.0k | mostly sentences; official scoring uses an LLM judge | MIT | medium (Gutenberg) | complex reasoning 53.4 vs 42.9; fact retrieval tie |
| GraphRAG-Bench Medical | about 0.25M | about 2.06k | as Novel | NCCN text copyright unclear | low-medium | small gain |
| CRAG (Meta) | web pages per question | 4,409 | short / no gold passages | CC BY-NC 4.0 | medium | none found |
| FRAMES (Google) | full Wikipedia articles; size unverified | 824 | mostly short; scoring unverified | Apache-2.0 | high | none found |

Token counts are file bytes divided by 4 and slightly overstate the text. Two different 2025 benchmarks are named
GraphRAG-Bench; the textbook one (2506.02404) has no license and copyrighted sources.

Recommendation: keep MultiHop-RAG as primary. Add the 2WikiMultiHopQA subset from `osunlp/HippoRAG_2` as the second
benchmark: real bridge entities, short gold answers, gold evidence, the clearest published graph gain, and a small
pre-split corpus. MuSiQue is the alternative if a license stated in the source repo and harder questions matter more
than cost. Because Wikipedia sets are likely memorised, add a closed-book (no retrieval) arm and report gains over it.

## 5. Cost inputs (estimates, before any pilot)

Claude API list prices (cached 2026-10-06): Haiku 5.5 $0.10 / $0.50, Sonnet 5.5 $2 / $10, Opus 5.5 $4 / $20 per
million input / output tokens; Batch is 50% off.

| Job | Haiku 5.5 | Sonnet 5.5 | Opus 5.5 |
|---|---|---|---|
| Re-extract MultiHop-RAG graph, 18,576 calls, Batch | about $1-2 | about $21-43 | about $52-116 |
| Extract 2Wiki subset, about 6,119 calls, Batch (scaled) | under $1 | about $7-14 | about $17-38 |
| Answer one 351-question arm, synchronous | about $0.2 | about $3-4 | about $6-9 |

Per call: about 350 input tokens (system, schema, about 55-token chunk) and 300 output tokens assumed. Thinking
tokens, Claude's tokenizer and structured-output overhead are not measured yet; a pilot of a few hundred calls per model
replaces these estimates.

Engineering facts that affect cost and design:

- OpenRouter calls do not draw on Anthropic credit unless BYOK is configured; BYOK fees are unchecked.
- Direct Anthropic calls reject `temperature` / `top_p` (400 on every model since 2026-10-21), which the engine sends.
  Extraction uses OpenAI-style `response_format`; Anthropic uses `output_config.format`.
- Opus 5.5 thinking cannot be disabled; Sonnet 5.5 turns it off with `thinking: {type: "between_tools"}`.
- Batch pricing needs an offline path (a script writing graph side tables, as graph-v2 did); the synchronous Rust
  ingest cannot use it.

## Sources

- MemoryTax (starting question): https://arxiv.org/html/2610.29823
- MultiHop-RAG: https://arxiv.org/html/2401.15391, https://github.com/yixuantt/MultiHop-RAG
- Han et al., RAG vs. GraphRAG: https://arxiv.org/html/2502.11371v2
- HippoRAG 2: https://arxiv.org/html/2502.14802v2, https://huggingface.co/datasets/osunlp/HippoRAG_2,
  https://github.com/OSU-NLP-Group/HippoRAG
- GraphRAG-Bench (Xiang et al.): https://arxiv.org/html/2506.05690v3, https://github.com/GraphRAG-Bench/GraphRAG-Benchmark
- GraphRAG-Bench (Xiao et al.): https://arxiv.org/abs/2506.02404
- Other graph comparisons: https://arxiv.org/pdf/2508.06105, https://arxiv.org/pdf/2606.30093,
  https://arxiv.org/html/2604.09666v1 (its dense baseline is not comparable)
- MuSiQue: https://github.com/StonyBrookNLP/musique; licenses of 2Wiki and HotpotQA via https://arxiv.org/pdf/2411.00369
- FRAMES: https://huggingface.co/datasets/google/frames-benchmark; CRAG: https://github.com/facebookresearch/CRAG
- LlamaIndex: https://developers.llamaindex.ai/python/framework-api-reference/embeddings/openai_like
- LightRAG: https://github.com/HKUDS/LightRAG; MS GraphRAG: https://microsoft.github.io/graphrag/config/yaml/
- OpenRouter embeddings: https://openrouter.ai/docs/api/reference/embeddings
