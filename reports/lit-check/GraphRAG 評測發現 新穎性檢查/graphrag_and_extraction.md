# GraphRAG benefit vs hybrid RAG, and LLM-based KG extraction quality/cost/failure modes (novelty check for findings 5 and 6)

## Q1. Do GraphRAG vs vanilla/hybrid RAG benchmarks find little or no gain on news/fact retrieval (MultiHop-RAG) and gains on multi-hop entity reasoning (2Wiki)?

### Takeaway
Partially known, with one important difference. The literature agrees that graph retrieval matches or loses to plain RAG on simple fact lookup and helps on multi-hop and entity-chaining reasoning (2Wiki, MuSiQue, complex reasoning). But the closest direct comparison on MultiHop-RAG (Han et al. 2025) reports a modest graph gain there (+2 to +5 points overall, mostly on temporal queries) over a dense-only, top-10, no-rerank RAG baseline. A null result on MultiHop-RAG against a stronger hybrid BM25+vector+rerank baseline is therefore not directly reported anywhere I found. It is plausible, and consistent with "strong reranked RAG closes the gap" (GraphRAG-Bench), but it would be a new data point.

### Cited Findings
- **RAG vs. GraphRAG: A Systematic Evaluation and Key Insights** (Han et al., Michigan State Univ. et al., arXiv Feb 2025, v3 Mar 2026). Unified protocol on NQ, HotpotQA, MultiHop-RAG. MultiHop-RAG overall accuracy with Llama-3.1-70B: RAG 65.77, Community-GraphRAG (Local) 71.17, HippoRAG2 69.87, Community-GraphRAG (Global) 65.69, KG-GraphRAG (triplets only) 50.98. With 8B: RAG 67.02, HippoRAG2 70.27, Community-Local 69.01. — [arXiv 2502.11371 (html v2)](https://arxiv.org/html/2502.11371v2)
- Same paper: the graph gain on MultiHop-RAG comes almost entirely from **temporal** queries (RAG 25.7–30.7 vs graph methods ~43–59). RAG is best on **inference** queries (92–95). Global GraphRAG collapses on **null** queries (13–19%) because it hallucinates instead of declining. — [arXiv 2502.11371](https://arxiv.org/html/2502.11371v2)
- Same paper: the RAG baseline is dense-only (text-embedding-ada-002, ~256-token chunks, top-10), with no BM25 hybrid and no reranker. The graph was extracted by GPT-4o-mini. Swapping the extractor to GPT-4o moved Community-Local on MultiHop-RAG from 71.17 to 75.08 with a 70B reader, and from 69.01 to 68.74 with an 8B reader. — [arXiv 2502.11371](https://arxiv.org/html/2502.11371v2)
- Same paper: KG-only variants underperform because the graphs are incomplete. "Only around 65.8% of answer entities exist in the constructed KG" (HotpotQA), and 65.5% for NQ. — [arXiv 2502.11371](https://arxiv.org/html/2502.11371v2)
- **When to use Graphs in RAG: A Comprehensive Analysis for Graph Retrieval-Augmented Generation** (GraphRAG-Bench; ICLR 2026; arXiv Jun 2025). It states "GraphRAG often fails to outperform vanilla RAG on many NLP tasks" and "Basic RAG matches GraphRAG in simple fact retrieval". Novel corpus, fact retrieval accuracy: RAG+rerank 60.92, HippoRAG2 60.14, MS-GraphRAG 49.29. Complex reasoning: RAG+rerank 42.93, HippoRAG2 53.38, MS-GraphRAG 50.93. — [arXiv 2506.05690v3](https://arxiv.org/html/2506.05690v3); [ICLR 2026 poster](https://iclr.cc/virtual/2026/poster/10007992)
- Same paper: tokens per query are RAG 879, HippoRAG2 1,008, LightRAG ~100k, MS-GraphRAG global ~331k (the text and table disagree on some of these values). Graph density varies widely. Average degree: HippoRAG2 8.75, Fast-GraphRAG 3.19, LightRAG 2.10, MS-GraphRAG 1.48. Denser graphs go with higher recall. — [arXiv 2506.05690v3](https://arxiv.org/html/2506.05690v3)
- **HippoRAG 2 / "From RAG to Memory: Non-Parametric Continual Learning for LLMs"** (Gutiérrez et al., OSU, arXiv Feb 2025; arXiv 2502.14802). Per secondary summaries: 2Wiki Recall@5 is 76.5% for NV-Embed-v2 and 90.4% for HippoRAG 2, and 2Wiki F1 is about +9.5 over NV-Embed-v2. Earlier structure-augmented methods (RAPTOR, GraphRAG, LightRAG) "reduce performance on simple QA by 5–10 F1", which HippoRAG 2 avoids. These numbers are not verified against the primary PDF. — [emergentmind summary](https://www.emergentmind.com/topics/hipporag-2); [liner review](https://liner.com/review/from-rag-to-memory-nonparametric-continual-learning-for-large-language)
- **RAGU: A Multi-Step GraphRAG Engine with a Compact Domain-Adapted LLM** (ITMO et al., arXiv Jul 2026). Evaluates on 2WikiMultiHopQA, MuSiQue, BioASQ, and GraphRAG-Bench. It does not evaluate on MultiHop-RAG; it uses MultiHop-RAG only as training data. — [arXiv 2607.11683](https://arxiv.org/html/2607.11683)
- **When Is Graph Structure Worth Its Cost? The Case for Structure Pricing in RAG** (EffiRAG; Zhang et al., arXiv Sep 2026). Argues for jointly pricing ingestion and query cost against graph benefit. Evaluated on UltraDomain against LightRAG-hybrid, not on MultiHop-RAG or 2Wiki, and the abstract mentions no BM25 baseline. — [arXiv 2609.18099](https://arxiv.org/abs/2609.18099)

### Inferences
- The finding "graph gives no benefit on MultiHop-RAG vs hybrid BM25+vector+rerank" sits between two known results: Han et al. found a small graph gain against a weak dense-only baseline, and GraphRAG-Bench found reranked RAG ties graph on fact retrieval. That the gap closes once the baseline adds BM25 and a reranker is a plausible but unpublished extrapolation, so the result counts as **partially known / new as a specific data point**. It would be worth reporting by MultiHop-RAG query type, because Han et al. show the graph advantage is concentrated in temporal and comparison queries. A null overall result could hide a temporal-only gain.
- "Graph benefit is expected on 2WikiMultihopQA instead" is **well supported by prior work** (HippoRAG/HippoRAG 2, GraphRAG-Bench complex reasoning). This is a known expectation, not a finding.
- "The writer LLM did not explain answer differences" is **partially known**. RAGU reports that downstream QA is robust to the extractor (1–2 pp between a 7B model and gpt-oss-20b, ≤1.5 pp across 3B–14B). Han et al. report mixed extractor sensitivity (GPT-4o helped a 70B reader, not an 8B one). Neither tests a Claude Haiku/Sonnet/Opus or DeepSeek ladder.

### Gaps
- I found no paper that runs GraphRAG against hybrid BM25+dense+cross-encoder-rerank specifically on MultiHop-RAG. The MultiHop-RAG paper itself (Tang & Yang, 2024, arXiv 2401.15391) benchmarks embedding and reranker retrieval but predates graph methods. Not fetched here.
- HippoRAG 2 numbers come from secondary summaries, not the primary PDF.

## Q2. How does the extraction LLM affect KG quality, cost, and downstream QA (entity/relation counts, dangling edges)?

### Takeaway
Only partially known. Prior work shows extractor choice changes graph density and coverage but often moves downstream QA only a little, and practitioners note node counts vary by model and even by run. I found no published head-to-head of commercial extractors (DeepSeek vs Claude Haiku/Sonnet/Opus) reporting entity counts, relation counts, cost per chunk, and dangling-relation rates together. The specific numbers (Haiku +25% entities / +40% relations at lower cost per chunk; Sonnet far fewer dangling relations) appear **new**.

### Cited Findings
- RAGU: the extractor ablation (Meno-Lite-0.1 7B, Qwen2.5-7B/14B/32B, gemma-3-27b, gpt-oss-20b) shows downstream QA moves by only 1–2 pp. The authors attribute robustness to a consolidation stage, not extractor size. The pipeline "requires every relation endpoint to match a validated entity", which "eliminates spurious entity–relation mismatches". This is an explicit design fix for dangling relations, but the paper reports no dangling count. Per-document indexing cost: MS-GraphRAG ~40k tokens / ~$0.10 (gpt-4o), RAGU ~8k tokens / ~$0.001. — [arXiv 2607.11683](https://arxiv.org/html/2607.11683)
- Han et al.: changing the extractor from GPT-4o-mini to GPT-4o changed MultiHop-RAG accuracy by +3.9 (70B reader) and −0.3 (8B reader), and roughly 35% of answer entities were missing from the KG. — [arXiv 2502.11371](https://arxiv.org/html/2502.11371v2)
- GraphRAG-Bench: graph density (edges/nodes per 10k tokens) differs by up to ~6× across pipelines and correlates with recall. This is evidence that "more relations" can matter, though the paper does not isolate it. — [arXiv 2506.05690v3](https://arxiv.org/html/2506.05690v3)
- The LightRAG README recommends an LLM with ≥32B parameters for extraction, because extraction demands far more of the LLM than traditional RAG. — [HF mirror of README](https://huggingface.co/spaces/rm-lht/lightrag/blob/main/README.md?code=true) (mirror, not upstream)
- Practitioner note: "the number of nodes extracted varies with LLM used and even for different runs of the same LLM". Microsoft's estimate, cited secondhand, is that extraction is ~75% of indexing cost. — [Towards Data Science](https://towardsdatascience.com/graphrag-in-practice-how-to-build-cost-efficient-high-recall-retrieval-systems/); [blog](https://aloknecessary.github.io/blogs/graph-rag-vs-rag/) (secondary)
- Missing "bridge edges" from partial entity names, and relation hallucination, are named failure modes in related work. — [Toward Robust GraphRAG, arXiv 2603.14828](https://arxiv.org/pdf/2603.14828); [Beyond Chunk-Local Extraction, arXiv 2605.28004](https://arxiv.org/pdf/2605.28004)

### Inferences
- The dangling-relation metric is known as a concept: pipelines like RAGU validate endpoints, and MS-GraphRAG and LightRAG implicitly create or drop unmatched endpoints. I found no study that measures dangling rate across extractor models. **Sonnet << Haiku/DeepSeek on dangling relations is apparently new.**
- "Cheaper model extracts more" (Haiku > DeepSeek in entity and relation counts at lower cost per chunk) goes against the common "cheaper extractor = more misses" heuristic in practitioner blogs. It is a new and potentially interesting data point. Note that count is not precision: more relations could include more hallucinated ones.
- Combined with "writer did not explain answer differences", the story fits RAGU's and Han et al.'s results that QA is fairly insensitive to the extractor. That part is **corroborating, not new**.

### Gaps
- I found no paper or benchmark comparing DeepSeek V3/V4 vs Claude models as KG extractors.
- I found no published dangling-edge rates per model.

## Q3. Are degenerate repetition / whitespace runaway until max_tokens in structured (JSON) extraction known, especially for DeepSeek? What mitigations exist?

### Takeaway
The failure mode is **well known in general**. OpenAI's and DeepSeek's JSON-mode docs warn about whitespace-only output, constrained-decoding libraries cap consecutive whitespace, LightRAG added max_tokens caps for "endless output loops" in entity extraction, and GDELT documented extraction loops in 2023. What I did not find is a **measured rate** (1.3–1.8% of calls) and **cost share** (~half of output tokens) for DeepSeek in KG extraction. That quantification is apparently new.

### Cited Findings
- DeepSeek's official JSON Output guide says that if output "cannot be recognized as JSON, the API replaces the non-JSON content with spaces", that `content` "may contain only spaces (appearing empty, even when `finish_reason` is `stop`)", and that users should "set the `max_tokens` parameter reasonably". This is a documented, provider-side whitespace behavior. — [DeepSeek API docs: JSON mode](https://api-docs.deepseek.com/guides/json_mode)
- OpenAI's JSON-mode guidance, quoted in its community forum: without an instruction to produce JSON, "the model may generate an unending stream of whitespace until the generation reaches the token limit". — [OpenAI community thread](https://community.openai.com/t/json-mode-with-gpt-4-turbo-stops-after-1050-token/537116)
- LightRAG v1.4.8 added max-tokens and temperature configuration "to prevent excessively long or endless output loops during the entity relationship extraction phase". It notes that a higher temperature may mitigate infinite loops in some LLMs (e.g., Qwen3-30B), especially on table- or citation-dense chunks, and suggests a 9000-token cap sized as timeout × tokens/s. — [LightRAG v1.4.8 release](https://newreleases.io/project/github/HKUDS/LightRAG/release/v1.4.8)
- GDELT Project (Aug 2023): text-bison entity extraction looped, repeating one entity until the 1,024-token cap, at temperatures 0.0–0.3. Prompt edits and temperature changes did not fix it reliably. — [GDELT blog](https://blog.gdeltproject.org/llm-infinite-loops-in-llm-entity-extraction-when-temperature-basic-prompt-engineering-cant-fix-things/)
- Constrained decoding: lm-format-enforcer (used by vLLM guided_json) uses `MAX_CONSECUTIVE_WHITESPACES=12` to prevent infinite whitespace loops. Outlines users fix whitespace runaway and truncation with `whitespace_pattern=""`. — [LMFE #94](https://github.com/noamgat/lm-format-enforcer/issues/94); [Outlines discussion #692](https://redirect.github.com/outlines-dev/outlines/discussions/692)
- TruncProof (2026) notes that existing constrained-decoding approaches "cannot strictly enforce the maximum number of tokens", which leads to infinite generation or truncated JSON. — [HF papers 2605.13076](https://huggingface.co/papers/2605.13076.md)
- A similar degenerate loop has been reported for Claude: a single token repeated ~32k times until max tokens, ending as a normal-looking response. — [mirrored issue 82803](https://claudeissues.com/issue/82803-degenerate-repetition-loop-single-token-repeated-32k-times-until-max-tokens-sile)
- Community reports, unverified, describe looping and repetition in DeepSeek V3.2 around April 2026. — [Reddit snapshot](https://reddit.sentinel-team.org/posts/1swcp29/snapshots/2026-05-01T22%3A04%3A17.338364Z)

### Inferences
- Mitigations reported in the sources: set a tight max_tokens sized to the expected output, check `finish_reason=="length"` (and whitespace-only content) and retry, raise temperature slightly, put explicit JSON instructions and an example in the prompt, and cap consecutive whitespace in the grammar.
- Not stated by any source, but a direct implication: a runaway rate of ~1.5% that consumes ~50% of output tokens means a cap set near the p99 of normal output length would recover most of the wasted spend.
- Verdict for finding (6): the **phenomenon is known** and documented by DeepSeek itself (whitespace replacement in JSON mode). The **rate and cost share in a KG-extraction workload are apparently new**. Most likely cause: DeepSeek's JSON-mode whitespace substitution combined with a long max_tokens cap.

### Gaps
- I found no GitHub issue or paper quantifying the frequency of DeepSeek V3/V4 whitespace runaway or its token cost.
- I did not confirm whether the runaway occurs with `response_format=json_object` only or also in free-text mode.

## Overall verdicts (summary for the report writer)
- (5a) Graph gives no gain on MultiHop-RAG vs hybrid+rerank: **partially known / new data point**. The closest work (Han et al. 2025) shows a small gain against a weaker dense-only baseline, concentrated in temporal queries.
- (5b) Extractor LLM does not explain QA differences: **partially known** (RAGU 2026; Han et al. appendix). The DeepSeek and Claude ladder is new.
- (5c) Haiku extracts +25% entities and +40% relations at lower cost; Sonnet has far fewer dangling relations: **apparently new**. Endpoint validation exists as a design fix (RAGU), but nobody reports rates per model.
- (5d) Graph benefit expected on 2Wiki: **known** (HippoRAG 2, GraphRAG-Bench).
- (6) Whitespace runaway until max-token cap: **phenomenon known** (DeepSeek and OpenAI JSON-mode docs, LightRAG v1.4.8, GDELT 2023, constrained-decoding libraries). The **1.3–1.8% rate and ~50% output-token cost share are apparently new**.
