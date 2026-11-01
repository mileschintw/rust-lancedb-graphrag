# Metric guessing bias in RAG / multi-hop QA accuracy (yes/no constant baselines, abstention scoring)

Finding under test (2): on MultiHop-RAG (Tang & Yang 2024), the common accuracy metric rewards guessing on yes/no
(comparison/temporal) questions. Always answering "Yes" scores about 0.66 on the yes/no subset, and abstention is
scored the same as a wrong answer. Proposed fix: report yes/no and open questions separately, use balanced accuracy
on yes/no, and score abstention separately.

Overall verdict: **partially known.** Each of the two general principles has a well-cited precedent. (a) Binary QA
subsets need a majority-class baseline, per-type reporting or balancing; this is standard in VQA and BoolQ. (b)
Accuracy-only grading rewards guessing and should score abstention differently from errors; SimpleQA, CRAG and OpenAI
2025 all say so. What I could not find anywhere is the MultiHop-RAG-specific diagnosis: its yes/no label skew, the
~0.66 always-"Yes" baseline, and the fact that its official accuracy treats "insufficient information" on non-null
questions the same as a wrong answer. Neither the MultiHop-RAG paper nor its GitHub issues nor any follow-up I found
states it. The benchmark-specific measurement and the recommended reporting protocol for this benchmark appear new.
The underlying ideas do not.

## Q1. Has anyone documented yes/no label imbalance or trivial (majority/constant) baselines in MultiHop-RAG or similar multi-hop benchmarks?

### Takeaway
Not for MultiHop-RAG. The original paper describes comparison answers as "typically yes or no" but reports neither the
yes/no split nor any trivial baseline, and none of the 23 GitHub issues raises it. Majority-class and always-"yes"
baselines are well documented for older binary QA datasets (BoolQ 62%, VQA v1 yes/no ~71%, COCO-VQA "Is there a…" 79%
yes). For HotpotQA, the known critique is about single-hop shortcuts. I found no published always-"yes" figure for
HotpotQA comparison questions.

### Cited Findings
- MultiHop-RAG has 2,556 queries: Inference 816 (31.92%), Comparison 856 (33.49%), Temporal 583 (22.81%), Null 301
  (11.78%). The paper says comparison answers are "typically a definitive 'yes' or 'no'". Temporal answers are "typically
  a 'yes' or 'no' or a single temporal indicator word like 'before' or 'after'". — [MultiHop-RAG, Tang & Yang, HKUST,
  2024, arXiv 2401.15391](https://arxiv.org/html/2401.15391v1)
- The same paper gives no yes/no label distribution, no chance-level or majority baseline, and no formal definition of
  "Accuracy". It only says the response is compared with the ground truth, and that simple answers were chosen "to
  facilitate the use of a straightforward accuracy metric". — [arXiv 2401.15391](https://arxiv.org/html/2401.15391v1)
- Null queries expect "insufficient information" or similar. The paper does not say how that answer is matched, or how
  an "insufficient information" reply to a non-null query is scored. — [arXiv 2401.15391](https://arxiv.org/html/2401.15391v1)
- None of the 23 GitHub issues mentions label imbalance or guessing. — [MultiHop-RAG issues](https://github.com/yixuantt/MultiHop-RAG/issues?q=is%3Aissue)
- The closest issues are these:
  - #23 (2025) says the precision/recall/F1 in `qa_evaluate.py` collapse into plain accuracy.
    [#23](https://github.com/yixuantt/MultiHop-RAG/issues/23)
  - #13 (2024) says the whitespace-token `has_intersection` matcher treats "Yes," and "Yes" as different. The maintainer
    replied they would improve it and asked for non-LLM-judge suggestions.
    [#13](https://github.com/yixuantt/MultiHop-RAG/issues/13)
  - #12 shows yes/no label ambiguity: for "Was there no change…" questions, the gold answer "no" means "yes, there was a
    change", which the maintainer confirmed. [#12](https://github.com/yixuantt/MultiHop-RAG/issues/12)
- A secondary write-up notes that MultiHop-RAG gold answers are restricted to simple responses, which limits evaluation
  to straightforward accuracy. It gives no figures. — [Cobus Greyling, Substack](https://cobusgreyling.substack.com/p/multihop-rag)
- BoolQ (Clark et al., Google, NAACL 2019): 80.4% model accuracy, 90% for humans, 62% majority baseline (62.31% in the
  full text). The same paper notes that QuAC yes/no is 80% "yes". — [BoolQ, ACL Anthology N19-1300](https://aclanthology.org/N19-1300/)
- VQA (classic precedent for the per-type / balanced fix):
  - A COCO-VQA-trained model scored 86.3% on "yes" but 11.2% on "no" for TDIUC's balanced object-presence questions.
  - 79% of COCO-VQA "Is there a…" questions have "yes" as the answer.
  - The authors propose mean-per-type and normalized (per-answer-class) accuracy so that answer-prior exploitation
    cannot inflate scores.
  - Source: [Kafle & Kanan, ICCV 2017, arXiv 1703.09684](https://arxiv.org/html/1703.09684). The 86.3/11.2 figures
    came through a third-party summary, so check them in the PDF.
  - Answering "yes" to every VQAv1 yes/no question gives about 71% on that subset. — cited via
    [arXiv 2001.07059](https://arxiv.org/pdf/2001.07059). This is a secondary citation; the original is from the VQA
    balancing literature.
- HotpotQA (Min et al. 2019): more than half of the questions do not need multi-hop reasoning, and a no-context baseline
  does well on a multiple-choice version. — [Compositional Questions Do Not Necessitate Multi-hop Reasoning, arXiv 1904.12106](https://arxiv.org/pdf/1904.12106v1.pdf)
- HotpotQA comparison questions are often yes/no or one-of-two, and so are most exposed to lucky guessing. This is an
  informal blog, not peer-reviewed. — [benchmarkingagents.com](https://benchmarkingagents.com/hotpotqa)
- Some multi-hop work filters out HotpotQA yes/no items entirely so they do not distort the evaluation. —
  [arXiv 2010.09240](https://arxiv.org/pdf/2010.09240)
- StrategyQA is close to balanced, with about 46.8% "yes" (third-party figure), so a constant baseline is near 50% there
  and the problem is milder. — [alphaXiv StrategyQA page](https://www.alphaxiv.org/benchmarks/tel-aviv-university/strategyqa)
- LLM yes/no response bias varies by model and template. It is not a consistent "yes" bias. Sources:
  - CogSci 2025, "Estimating and correcting yes-no bias in language models":
    [eScholarship](https://escholarship.org/uc/item/2c04k26b)
  - Negative ("no") bias when the model lacks knowledge: [arXiv 2511.10881](https://arxiv.org/pdf/2511.10881)
  - "LLMs are Skeptics" on false negatives: [arXiv 2406.13929](https://arxiv.org/pdf/2406.13929)

### Inferences
- If MultiHop-RAG's yes/no gold labels are about 66% "Yes", the label skew sits close to BoolQ's 62% and below VQA's
  71–79%. The comparable benchmarks reported their majority baselines in their own papers. MultiHop-RAG did not, which
  is the specific omission.
- Because LLMs have their own model- and template-dependent yes/no bias, raw accuracy on a skewed subset mixes model
  prior with reasoning. Balanced accuracy, or per-class recall, removes the label-prior component. This is the VQA
  "normalized accuracy" argument applied to RAG.
- Issue #12's polarity ambiguity means part of the yes/no subset may be noisy in a way that interacts with any yes-bias.
  This is worth mentioning with the finding.

### Gaps
- I found no published yes/no split or always-"Yes" score for MultiHop-RAG, so the ~0.66 figure rests on the user's own
  count. I did not compute it myself.
- I found no published always-"yes" or majority baseline for the HotpotQA comparison subset or 2WikiMultihopQA
  comparison questions. These may exist in older papers my searches did not surface.

## Q2. Prior work on scoring abstention in QA/RAG (penalise confident errors more than "I don't know")

### Takeaway
This is well established in 2024–2026:
- SimpleQA separates correct / incorrect / not-attempted.
- CRAG scores hallucination −1 and "missing" 0.
- OpenAI's 2025 "Why language models hallucinate" argues that accuracy-only grading rewards guessing and recommends
  penalising confident errors more than abstention.
- An August 2026 preprint applies asymmetric scoring (+1 / −4 / 0) directly to RAG.

Treating abstention separately is therefore known. Pointing out that MultiHop-RAG's metric lacks it is a
benchmark-specific application.

### Cited Findings
- **OpenAI, "Why language models hallucinate" (Sept 5, 2025):**
  - Standard evaluation rewards guessing over admitting uncertainty, by analogy to multiple-choice tests: a guess has
    some chance of scoring, while "I don't know" guarantees zero.
  - Recommendation: "penalize confident errors more than you penalize uncertainty, and give partial credit for
    appropriate expressions of uncertainty". Mainstream accuracy metrics need rework, not just add-on tests.
  - SimpleQA example: gpt-5-thinking-mini abstains 52% with 26% errors, while o4-mini abstains 1% with 75% errors, at
    similar accuracy (22% vs 24%).
  - Source: [OpenAI blog/paper](https://openai.com/index/why-language-models-hallucinate/)
- **SimpleQA (Wei et al., OpenAI, Nov 2024):**
  - Grades each answer correct / incorrect / not attempted and reports overall-correct, correct-given-attempted, and
    their harmonic mean F.
  - The authors admit F still rewards guessing when performance is below 50%. They suggest +1 / 0 / negative-penalty
    scoring instead.
  - Source: [arXiv 2411.04368](https://arxiv.org/abs/2411.04368)
- **CRAG (Yang et al., Meta, NeurIPS 2024 D&B):**
  - Answers are labelled perfect / acceptable / missing / incorrect and scored 1 / 0.5 / 0 / −1. "Truthfulness" is the
    mean, and missing answers are preferred to incorrect ones.
  - Auto-eval score = (#accurate − #incorrect)/N.
  - The best industry RAG systems reach about 51% truthfulness.
  - Source: [arXiv 2406.04744](https://arxiv.org/pdf/2406.04744)
- KERAG uses truthfulness T = A − H (accuracy minus hallucination rate) with miss rate neutral, following CRAG. —
  [arXiv 2509.04716](https://arxiv.org/pdf/2509.04716)
- **"Why RAGs Hallucinate: Penalty-Aware Evaluation of RAG Systems with Knowledge-Gap Canaries" (Do Rosario et al., arXiv, Aug 2026):**
  - Volume accuracy rewards RAG guessing. The authors propose +1 / −4 / 0 scoring plus "knowledge-gap canaries" (answer
    absent from the KB).
  - Answer-when-answering accuracy was 97–98% across systems, but canary violation ranged 16.7–98.1%, and penalty
    scoring reorders systems for k = 1 to 9.
  - It does not cover yes/no or constant baselines, and does not use MultiHop-RAG. This is the closest RAG-specific
    work on the abstention half. Not yet peer-reviewed.
  - Source: [arXiv 2608.26385](https://arxiv.org/abs/2608.26385)
- **AbstentionBench (Kirichenko et al., Meta, June 2025):** 20 datasets on abstention. Reasoning fine-tuning degrades
  abstention by 24% on average, and scaling helps little. — [arXiv 2506.09038](https://arxiv.org/abs/2506.09038v1)
- **"Know Your Limits: A Survey of Abstention in LLMs" (Wen et al., UW/AI2, TACL 2025):** a framework for abstention
  from the query, model and human-values perspectives. — [arXiv 2407.18418](https://arxiv.org/abs/2407.18418)
- RAG benchmarks with an explicit abstention or negative-rejection axis include RGB (negative rejection) and
  LIT-RAGBench (Abstention category). — via search summary of [arXiv 2603.06198](https://arxiv.org/html/2603.06198).
  This came from a search snippet and was not fetched.
- **Selective answering in multi-hop QA (Sato et al., Sept 2026):** trains abstain-until-evidence-sufficient on
  HotpotQA/2Wiki/MuSiQue and reports an unsupported-answer rate. No yes/no or MultiHop-RAG analysis. —
  [arXiv 2609.01687](https://arxiv.org/abs/2609.01687)

### Inferences
- The proposed "treat abstention separately" fix should be framed as applying SimpleQA- or CRAG-style three-way scoring
  to MultiHop-RAG, not as a new idea.
- The two halves of the finding interact. On a yes/no subset with a 66% prior, an always-answer model gets a large free
  bonus over an abstaining one. Accuracy-only scoring therefore punishes calibrated abstention twice: the abstention
  earns 0, and the guess it replaced was worth about 0.66 in expectation. The OpenAI birthday example has a 1/365 guess
  value, so the incentive here is far stronger. I did not see this binary-prior-amplified version spelled out anywhere.

### Gaps
- I did not verify how MultiHop-RAG's `qa_evaluate.py` scores an "insufficient information" reply to a non-null
  question. From the matcher's design it is presumably a miss, the same as wrong. Confirm in the code.

## Q3. Critiques of LLM-judge / EM / accuracy metrics in RAG benchmarks

### Takeaway
Critiques exist, but they target other things: metric formula collapse and string-matching brittleness on MultiHop-RAG
(GitHub #13, #23), and coarse-grained end-to-end accuracy (CRAG's −1 for hallucination, the 2026 penalty-aware paper).
I found none that targets the yes/no prior or constant baselines on a RAG benchmark.

### Cited Findings
- MultiHop-RAG `qa_evaluate.py`:
  - The P/R/F1 reduce to accuracy (fp = fn = tn by construction). — [Issue #23](https://github.com/yixuantt/MultiHop-RAG/issues/23)
  - The token-intersection matcher is punctuation-brittle, and the maintainer wants a non-LLM semantic matcher. —
    [Issue #13](https://github.com/yixuantt/MultiHop-RAG/issues/13)
- CRAG's design is itself a critique of plain accuracy, since it penalises hallucination below a missing answer. —
  [arXiv 2406.04744](https://arxiv.org/pdf/2406.04744)
- Penalty-aware RAG evaluation argues that k = 0 (plain accuracy) is the degenerate case under which guessing is always
  rational. — [arXiv 2608.26385](https://arxiv.org/abs/2608.26385)
- For HotpotQA, answer-only accuracy on comparison questions without the supporting-fact score overstates multi-hop
  reasoning (informal). — [benchmarkingagents.com](https://benchmarkingagents.com/hotpotqa)

### Inferences
- A short note on MultiHop-RAG could combine four issues into one critique: no stated yes/no prior, no constant
  baseline, abstention scored as an error, and the existing matcher issues #12, #13 and #23. Together they make a
  coherent "the headline accuracy is not interpretable" argument that I did not find anywhere.

### Gaps
- I did not search RAGChecker (Amazon, 2024) or RAGAS-style judge critiques in this pass, so I cannot cite their
  specific claims here.
- I did not survey GraphRAG papers that report MultiHop-RAG accuracy (e.g. HippoRAG-style or LightRAG follow-ups) to see
  whether any of them reports yes/no splits.

## Q4. How close is the closest work, and what would be new?

### Takeaway
The closest precedents:
- **Constant-baseline half:** Kafle & Kanan 2017 (VQA yes-bias with per-type and normalized accuracy) and BoolQ 2019
  (62% majority baseline). Close in idea, but not RAG and not 2023+.
- **Abstention half:** OpenAI 2025, SimpleQA 2024, CRAG 2024, and penalty-aware RAG eval 2026. Close in idea, but none
  of them looks at binary-answer priors or at MultiHop-RAG.

New: (i) quantifying MultiHop-RAG's yes/no skew and the ~0.66 always-"Yes" score; (ii) showing that the official metric
scores abstention the same as error on this benchmark; (iii) the combined protocol for MultiHop-RAG (split yes/no from
open, balanced accuracy on yes/no, three-way abstention accounting). Verdict: **partially known.** The principles are
known, and the benchmark-specific diagnosis and fix appear new.

### Cited Findings
- Per-type / normalized accuracy to defeat yes-priors: [Kafle & Kanan 2017](https://openaccess.thecvf.com/content_iccv_2017/html/Kafle_An_Analysis_of_ICCV_2017_paper.html)
- Majority baseline reported with binary QA: [BoolQ 2019](https://aclanthology.org/N19-1300/)
- Accuracy-only grading rewards guessing: [OpenAI 2025](https://openai.com/index/why-language-models-hallucinate/);
  [SimpleQA 2024](https://arxiv.org/abs/2411.04368)
- Hallucination −1 vs missing 0 in a RAG benchmark: [CRAG 2024](https://arxiv.org/pdf/2406.04744)
- RAG-specific asymmetric scoring: [arXiv 2608.26385 (2026)](https://arxiv.org/abs/2608.26385)
- MultiHop-RAG paper and issues are silent on yes/no prior and abstention scoring:
  [arXiv 2401.15391](https://arxiv.org/html/2401.15391v1); [issues list](https://github.com/yixuantt/MultiHop-RAG/issues?q=is%3Aissue)

### Inferences
- To present this as a contribution, cite VQA/BoolQ for "report majority baselines and per-type metrics" and
  OpenAI/SimpleQA/CRAG for "score abstention separately". Then claim novelty only for the MultiHop-RAG measurement and
  its consequences, such as how many published RAG/GraphRAG gains on MultiHop-RAG fall within the constant-baseline
  margin.

### Gaps
- My searches cannot rule out an unindexed workshop paper or blog that computed MultiHop-RAG's yes/no ratio.
- Closed GitHub pull requests and discussions were not checked; only the issues list was.
