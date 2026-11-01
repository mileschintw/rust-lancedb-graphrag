# Reader abstention in RAG, and how it interacts with evidence completeness and chunk size (novelty check, 2023–2026)

Findings under test:
- (1) Claude Sonnet/Opus readers score below deepseek-v4-flash on "answer usable" accuracy on MultiHop-RAG. They lose mainly by abstaining ("not enough information") on partial evidence, not by answering wrongly. With complete evidence (larger merged chunks), their abstention drops from 0.27 to 0.07 and they nearly catch up.
- (3) Chunking × reader interaction: larger merged chunks help the Claude readers, which abstain, but not the cheaper model.

## Q1: Which papers and benchmarks study LLM abstention or over-refusal in RAG when context is insufficient or partial?

### Takeaway
This area is well studied. Negative rejection (RGB, 2023), sufficient context (Google, ICLR 2025), FaithEval's unanswerable contexts, CRAG's "missing" category, Trust-Score/Trust-Align, AbstentionBench, RefusalBench and LIT-RAGBench all measure whether a reader abstains appropriately. Most of them focus on under-abstention (hallucinating when context is insufficient). Over-abstention (refusing when the answer is actually derivable) gets less attention, but LIT-RAGBench and RefusalBench measure it directly.

### Cited Findings
- **RGB** (Chen, Lin, Han, Sun; AAAI 2024; arXiv Sep 2023) tests four RAG abilities, including *negative rejection* (signalling insufficient information when retrieved docs lack the answer) and *information integration* (multi-document questions). The six LLMs tested "struggled noticeably with negative rejection, information integration". Sources: [arXiv 2309.01431](https://arxiv.org/abs/2309.01431v2), [AAAI](https://ojs.aaai.org/index.php/AAAI/article/view/29728)
- **Sufficient Context: A New Lens on RAG Systems** (Joren et al., Google, ICLR 2025, arXiv 2411.06037) separates context failures from model failures.
  - Proprietary models (Gemini, GPT, Claude) answer well when context is sufficient but often answer wrongly instead of abstaining when it is insufficient. Open models abstain or hallucinate often even with sufficient context.
  - Datasets: MuSiQue-Ans, HotpotQA (both multi-hop) and FreshQA.
  - Sources: [ICLR proceedings](https://proceedings.iclr.cc/paper_files/paper/2025/hash/33dffa2e3d2ab74a783d1a8c292f66d9-Abstract-Conference.html), [Google Research](https://research.google/pubs/sufficient-context-a-new-lens-on-retrieval-augmented-generation-systems/)
- Same paper, Table 4 (curated, human-labelled subset). Abstention rate under sufficient vs insufficient context — [arXiv HTML](https://arxiv.org/html/2411.06037):

  | Model | Abstention, sufficient context | Abstention, insufficient context |
  |---|---|---|
  | Claude 3.5 Sonnet | 11.1% (highest of the 5 models) | 53.8% |
  | GPT-4o | 4.8% | 61.5% |
  | Gemini 1.5 Pro | 1.6% | 50.0% |
  | Gemini 1.5 Flash | 4.8% | 73.1% |
  | Gemma 27B | 3.2% | 55.8% |

- Same paper: adding RAG context *lowers* overall abstention. Claude 3.5 Sonnet goes from 84.1% closed-book to 52% with RAG, GPT-4o from 34.4% to 31.2%, Gemini 1.5 Pro from 100% to 18.6%. The paper says RAG "paradoxically reduces the model's ability to abstain from answering when appropriate". It also reports that SOTA LLMs still answer correctly 35–62% of the time with insufficient context, and that 55.4% of instances in standard datasets have insufficient context. Sources: [arXiv HTML](https://arxiv.org/html/2411.06037), [ICLR abstract](https://iclr.cc/virtual/2025/poster/30092)
- **FaithEval** (Ming et al., Salesforce AI Research, ICLR 2025, arXiv 2410.03727) has an "unanswerable context" task, built by removing evidence while keeping the passage coherent. Per the abstract, "larger models do not necessarily exhibit improved faithfulness". A secondary summary reports that the best model reached only 71.8% on unanswerable contexts even with CoT; I did not verify this against the paper. Sources: [arXiv](https://arxiv.org/html/2410.03727v3), [ICLR](https://proceedings.iclr.cc/paper_files/paper/2025/hash/48404cd9ce03946c6b7177691f3267a1-Abstract-Conference.html)
- **CRAG** (Meta, NeurIPS 2024 D&B, arXiv 2406.04744) scores accurate = 1, missing ("I don't know") = 0 and incorrect = −1, with truthfulness = accuracy − hallucination rate. Under this scheme abstention beats a wrong answer. Source: [arXiv](https://arxiv.org/pdf/2406.04744)
- **Trust-Score / Trust-Align** (Song et al., arXiv 2409.11242, Sep 2024 – Mar 2025) scores whether a model correctly refuses or answers based only on the supplied documents, so the reader is measured separately from retrieval quality. It also trains refusal behaviour with DPO. Source: [arXiv](https://arxiv.org/abs/2409.11242)
- **AbstentionBench** (Kirichenko et al., FAIR Meta, NeurIPS 2025, arXiv 2506.09038) covers 35k+ unanswerable questions across 20 datasets and 20 frontier LLMs. Reasoning fine-tuning lowers abstention by about 24% on average, and "scaling models is of little use". Source: [arXiv](https://arxiv.org/abs/2506.09038v1)
- **RefusalBench** (arXiv 2510.10390, NeurIPS 2025) studies selective refusal in grounded LMs using 176 perturbation strategies on 30+ models. Some models refuse over 60% of *answerable* queries, which is direct evidence of over-refusal. Claude models were used to generate the benchmark data, not evaluated as readers. Sources: [arXiv](https://arxiv.org/html/2510.10390v1), [NeurIPS](https://neurips.cc/virtual/2025/122468)
- **LIT-RAGBench** (Itai et al., arXiv 2603.06198, Mar/Apr 2026) is the closest model-specific evidence.
  - It measures *over-abstention*: abstaining when the context actually contains enough information.
  - **Claude-Sonnet-4 has the highest average over-abstention rate (0.259; 0.370 in English, 0.148 in Japanese)** of the 15 models tested. The paper calls this "a strong tendency to over-abstain".
  - Other rates: GPT-4.1 0.083, GPT-5 0.065, Gemini-2.5-Pro 0.046, Gemini-2.5-Flash 0.065, Llama-3.1-8B 0.213.
  - The authors flag a small sample size.
  - DeepSeek models are not in the table.
  - Source: [arXiv HTML](https://arxiv.org/html/2603.06198)
- **GRACE** (arXiv 2601.04525) trains answer-vs-abstain behaviour with an evidence-sufficiency reward. Source: [alphaXiv](https://www.alphaxiv.org/abs/2601.04525v1)
- **"Learning Evidence Sufficiency Boundaries for Selective Answering in Grounded Multi-Hop QA"** (arXiv 2609.01687, 2026). Only a fragment was indexed, so I could not verify its contents. Source: [arXiv](https://arxiv.org/pdf/2609.01687)
- **NovelHopQA** (arXiv 2506.02000): when one required chunk is missing from the top-k, models fail to complete the multi-hop chain. Source: [arXiv](https://arxiv.org/pdf/2506.02000)

### Inferences
- The finding that readers abstain much more on insufficient or partial context than on sufficient context is thoroughly established (Sufficient Context Table 4; RGB; FaithEval).
- Abstention dropping when evidence becomes complete is the expected direction under these papers. The size of the drop (0.27 → 0.07) is consistent with Sufficient Context's insufficient-vs-sufficient gap (roughly 50% vs under 12%).
- Two documented results back the claim that Claude specifically is conservative. Claude 3.5 Sonnet had the highest sufficient-context abstention (11.1%) and the highest closed-book abstention (84.1%) in Sufficient Context. Claude-Sonnet-4 had the highest over-abstention in LIT-RAGBench.

### Gaps
- None of these papers includes DeepSeek V3/V4-family models next to Claude in an abstention breakdown.
- Neither the MultiHop-RAG paper (Tang & Yang, arXiv 2401.15391) nor any follow-up I found reports abstention rates per reader. The original paper tested GPT-4, GPT-3.5, PaLM, Claude-2, Llama2-70B and Mixtral on retrieved chunks, but I could not find a Claude-2 abstention figure. Source: [arXiv](https://arxiv.org/abs/2401.15391v1)

## Q2: Is it documented that stronger or safer models abstain more, get penalised by accuracy metrics, and so lose to cheaper models that guess?

### Takeaway
The mechanism is known and widely discussed: accuracy-only grading rewards guessing over abstaining, and models that abstain look worse. OpenAI's 2025 hallucination paper makes this argument, and AA-Omniscience shows the leaderboard reversing for Claude when wrong answers are penalised. I found no published RAG study showing a cheap model *beating* Claude on accuracy specifically because Claude over-abstains on partial multi-hop evidence. That specific instance is not documented.

### Cited Findings
- **OpenAI, "Why language models hallucinate"** (Kalai et al., Sep 2025) argues that standard evaluations score models in a way that rewards guessing over acknowledging uncertainty. "Accuracy-only scoreboards dominate leaderboards and model cards". The proposed fix is to penalise confident errors more than abstention. Source: [OpenAI](https://openai.com/index/why-language-models-hallucinate/)
- The OpenAI post's SimpleQA comparison, as restated by secondary summaries (not verified against the original):

  | Model | Accuracy | Errors | Abstention |
  |---|---|---|---|
  | gpt-5-thinking-mini | ~22% | 26% | 52% |
  | o4-mini | ~24% | 75% | 1% |

  The model that guesses wins on accuracy despite making far more errors. Sources: [OpenAI](https://openai.com/index/why-language-models-hallucinate/), [llmbase summary](https://llmbase.ai/news/openai-language-models-hallucinate-due-to-evaluation-incentives-research-shows)
- **AA-Omniscience** (Artificial Analysis, Nov 2025, arXiv 2511.13029) scores +1 correct, −1 incorrect, 0 abstain. Anthropic models had the lowest hallucination rates. Claude 4.1 Opus led the Omniscience Index (4.8). General intelligence poorly predicted the index. Sources: [Artificial Analysis](https://artificialanalysis.ai/articles/aa-omniscience-knowledge-hallucination-benchmark), [arXiv](https://arxiv.org/abs/2511.13029)
- **CRAG** also gives a missing answer (0) a better score than a hallucination (−1), so leaderboard ranks depend on the metric. Source: [arXiv](https://arxiv.org/pdf/2406.04744)
- **LIT-RAGBench** describes over-abstention as a trade-off: abstaining more can be cautious behaviour but doesn't necessarily make a model more useful. Claude-Sonnet-4 ranks worst on this metric. Source: [arXiv HTML](https://arxiv.org/html/2603.06198)
- **"Honesty over Accuracy: Reinforced Hesitation"** (arXiv 2511.11500) reports that frontier models rarely hesitate even when wrong answers carry explicit penalties (non-RAG tasks: GSM8K, MedQA, GPQA). This runs in the opposite direction to Claude's RAG conservativeness, which suggests abstention propensity depends on the task and the model. Sources: [arXiv](https://arxiv.org/pdf/2511.11500), [search summary](https://chatpaper.com/paper/209478)
- **Sufficient Context** offers a counterpoint: in its main results, proprietary models (Claude included) *hallucinate more than they abstain* when context is insufficient. Claude is the most abstention-prone of them, but it is not described as an over-abstainer in absolute terms. Source: [arXiv HTML](https://arxiv.org/html/2411.06037)

### Inferences
- Verdict on finding (1), the mechanism (abstention depresses accuracy-style metrics; Claude is unusually conservative in RAG): **known.** OpenAI 2025, AA-Omniscience and CRAG cover the metric argument. Sufficient Context and LIT-RAGBench cover Claude's conservativeness.
- Verdict on finding (1) as a specific observation: **partially known; the specifics look new.** The observation is that on MultiHop-RAG, an "answer usable" metric ranks deepseek-v4-flash above Claude Sonnet/Opus mainly because of abstention, and the gap closes when evidence is completed. I found no paper that:
  - compares DeepSeek and Claude readers this way;
  - decomposes a multi-hop RAG accuracy gap into abstain vs wrong per reader;
  - or shows the ranking reversing as evidence completeness is manipulated within the same pipeline (the 0.27 → 0.07 abstention drop).
- To present this as a contribution, frame it as a replication and extension of Sufficient Context and LIT-RAGBench to 2026 readers (Claude 4.x vs DeepSeek V4) on MultiHop-RAG, plus a controlled completeness intervention. It is not a new phenomenon.

### Gaps
- No independent abstention measurements for DeepSeek-V4-flash were found in any benchmark.
- The SimpleQA numbers from the OpenAI post were not verified against the primary paper.

## Q3: Is there work showing chunk size or context completeness interacts with the reader model, i.e. different readers benefit differently from chunking?

### Takeaway
Plenty of work shows chunk size matters and that the best size depends on the dataset, the embedding model and the source text. LongRAG shows large retrieval units work well with strong long-context readers. I found no study that crosses chunk size with several reader LLMs and reports an interaction, especially one explained by reader abstention. Finding (3) appears **apparently new**, with LongRAG and Sufficient Context as the nearest neighbours.

### Cited Findings
- **LongRAG** (Jiang, Ma, Chen; Waterloo; arXiv 2406.15319, 2024) switches from 100-word passages to 4K+-token retrieval units read by long-context readers (GPT-4o, Gemini-1.5-Pro).
  - Recall@1 on NQ rises from 52% to 71%. Recall@2 on HotpotQA rises from 47% to 72%.
  - End-to-end EM is 62.7 (NQ) and 64.3 (HotpotQA) with no training.
  - It does not compare weak and strong readers on the same chunk sizes.
  - Source: [arXiv](https://arxiv.org/abs/2406.15319v3)
- **"Rethinking Chunk Size for Long-Document Retrieval"** (Fraunhofer IAIS, arXiv 2505.21700) covers 6 datasets and 2 embedding models. There is no universal best chunk size; it depends on the dataset and the embedding model's biases. This is about retrieval only, not the reader. Source: [arXiv](https://arxiv.org/html/2505.21700v2)
- **"The Effect of Text Chunk Size on RAG Performance"** (Garrido-Lestache Belinchon, arXiv 2607.24767, 2026) finds the best size depends on the source text's structure and writing style. The abstract does not report per-generator differences. Source: [arXiv](https://arxiv.org/abs/2607.24767)
- Engineering blogs give single-model or generator-agnostic sweet spots: Arize suggests 300–500 tokens, with a decline above 1000; LlamaIndex suggests about 1024. Neither isolates the reader. Sources: [Arize](https://arize.com/blog-course/evaluation-of-llm-rag-chunking-strategy/), [LlamaIndex](https://www.llamaindex.ai/blog/evaluating-the-ideal-chunk-size-for-a-rag-system-using-llamaindex-6207e5d3fec5)
- **Sufficient Context** shows *indirectly* that sufficiency changes readers differently: their abstention rates under insufficient vs sufficient context differ by model (Table 4). Larger chunks that turn insufficient context into sufficient context would therefore help high-abstention readers most. The paper does not vary chunk size. Source: [arXiv HTML](https://arxiv.org/html/2411.06037)
- **NovelHopQA** reports that multi-hop chains break when one required chunk is missing from the top-k. That is the failure larger merged chunks would fix. Source: [arXiv](https://arxiv.org/pdf/2506.02000)

### Inferences
- The causal story behind finding (3) follows from published pieces. Larger chunks raise evidence completeness, as LongRAG's recall gains show. Completeness lowers abstention most for conservative readers, per Sufficient Context and LIT-RAGBench. A reader that already guesses on partial evidence gains less.
- The *measured* interaction is not published as far as I found:
  - a chunk-size × reader-model effect in which larger merged chunks help Claude but not DeepSeek;
  - attributed to abstention through a per-reader breakdown of abstain vs wrong answers.
- Verdict on finding (3): **apparently new**, with the caveat that it is predictable from prior work. A reviewer would probably cite LongRAG and Sufficient Context as anticipating it.

### Gaps
- The full text of the 2026 chunk-size papers (2607.24767, 2601.14123, 2603.06976) was not checked. One of them may run several generators.
- I found no paper that reports "answer usable" or abstention per reader across chunk sizes on MultiHop-RAG specifically.
- GraphRAG-specific evaluations (e.g. GraphRAG-Bench) were not searched for reader-abstention breakdowns.
