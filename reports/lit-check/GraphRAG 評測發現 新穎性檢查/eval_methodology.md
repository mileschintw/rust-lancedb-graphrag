# Statistical rigor in LLM / RAG evaluation: novelty check for findings (4) and (7)

Scope: finding (4) covers power with about 90 questions (only about 8-point differences detectable), Opus vs deepseek on about 880 fresh MultiHop-RAG questions (+5.0, 95% CI +2.4..+7.8) and on 2Wiki (+14, 100 dev), and a 5-replicate variance decomposition showing that most variance lies across questions, so K=2 to 3 buys about 3-4% precision for +50% cost. Finding (7) covers the methodology: pre-registration with frozen constants committed before runs, a held-out split read once, blinding, Holm correction, a sign-flip permutation test on per-question means, and a paired bootstrap.

## Q1. How closely does Anthropic's "Adding Error Bars to Evals" (Miller, 2024) cover finding 4?

### Takeaway
Very closely. Miller (Anthropic, Nov 2024) states the same variance decomposition (across-question variance plus within-question variance divided by K), says that once within-question variance divided by K is small, more resamples barely help, recommends paired differences, and gives a power and minimum-detectable-effect formula. Finding 4's *method* is therefore textbook as of 2024. What is new is the *empirical instance*: the measured numbers on a GraphRAG/RAG stack with real model pairs.

### Cited Findings
- Paper: "Adding Error Bars to Evals: A Statistical Approach to Language Model Evaluations", Evan Miller, Anthropic, arXiv 2411.00640 (Nov 2024); blog dated Nov 19, 2024. — [arXiv](https://arxiv.org/abs/2411.00640); [Anthropic blog](https://www.anthropic.com/research/statistical-approach-to-model-evals)
- Five recommendations: (1) report SEM and a CI from the CLT; (2) cluster SEs on the unit of randomization, since clustered SEs were sometimes over 3x larger than naive SEs on popular evals; (3) reduce within-question variance by resampling K times and averaging per question (Inspect "epochs"), or by using next-token probabilities; (4) use paired differences, because frontier models' question scores correlate at about 0.3-0.7; (5) run a power analysis to choose the number of questions and resamples. — [Anthropic blog](https://www.anthropic.com/research/statistical-approach-to-model-evals)
- Variance decomposition by the law of total variance: Var(mean) = (Var(x) + E[σ²])/n, and resampling K times divides the within-question term by K. Once E[σ²]/K is much smaller than Var(x), "increasing K further will have little effect on the standard error". In the uniform-difficulty example, K=1 to 2 cuts variance by 1/3 and K=4 by 1/2, with a ceiling of 2/3. — [arXiv HTML](https://arxiv.org/html/2411.00640)
- Power formula: n = (z_{α/2} + z_β)² (ω² + σ_A²/K_A + σ_B²/K_B) / δ², inverted to get the minimum detectable effect δ. Example: detecting δ=3 points at α=0.05 with 80% power needs about 969 questions, so the paper suggests new evals include at least 1,000. Example: with n=198, raising K from 1 to 10 lowers the minimum detectable effect only from 13.2% to 7.5%. — [arXiv HTML](https://arxiv.org/html/2411.00640)
- The paper calls paired differences a "free" variance reduction; with correlation 0.5, the variance falls by one-third. — [arXiv HTML](https://arxiv.org/html/2411.00640)
- The paper does not discuss pre-registration, permutation tests, or multiple-comparison corrections. It mentions bootstrapping only to say it is usually unnecessary. — [arXiv HTML](https://arxiv.org/html/2411.00640)

### Inferences
- "With about 90 questions only about 8-point differences are detectable" is a direct application of Miller's MDE formula. By the same formula, about 1,000 questions are needed for a 3-point effect, so the about-880 fresh-question design matches Miller's recommendation almost exactly. This is known practice applied correctly, not a new idea.
- "More questions beat more replicates" is Miller's own conclusion when Var(x) dominates E[σ²]/K. What the project adds is an *empirical measurement* of that ratio on multi-hop RAG with an LLM judge or exact-match scoring, plus a cost figure (+50% cost for about 3-4% precision). Few published works report this split for RAG specifically; I found none that does.
- The +5.0 [2.4, 7.8] Opus vs deepseek result is a model-comparison data point, not a methods contribution.

### Gaps
- I did not verify whether Miller's paper reports measured within/across variance ratios on real benchmarks or only illustrative ones. The fetched summary gives illustrative numbers only.

## Q2. Other related work: Meta variance paper, Dror, power in NLP, tinyBenchmarks, reproducibility

### Takeaway
A dense body of work from 2018 to 2025 already establishes significance testing, power analysis, benchmark variance, and repeated-run uncertainty for LLM evals. Bowyer et al. (ICML 2025) warns specifically that CLT intervals are too narrow below a few hundred items, which bears directly on the 90- and 100-question splits. G-theory papers from 2026 frame the items vs replications vs judges trade-off formally.

### Cited Findings
- **Madaan et al., "Quantifying Variance in Evaluation Benchmarks"** (Meta, arXiv 2406.10229, Jun 2024; NeurIPS 2024 workshop). The authors trained 10 Llama-2-7B models that differ only by seed and analysed about 280 models. Seed variance is usually smaller than bootstrapped 95% CIs. Benchmarks with fewer examples show notably higher variance. IRT-based subsetting increases seed variance and reduces monotonicity. Relevance: this is training-seed variance, not inference-replicate variance, but it reaches the same "fewer items, noisier" conclusion. — [arXiv](https://arxiv.org/html/2406.10229v1); [NeurIPS](https://neurips.cc/virtual/2024/106953)
- **Card et al., "With Little Power Comes Great Responsibility"** (Stanford and others, EMNLP 2020). A meta-analysis finds underpowered experiments common in NLP. The paper recommends simulation-based power analysis, warns against post-hoc power, and releases notebooks. Relevance: classic precedent for "only about 8-point differences are detectable with 90 questions". — [ACL Anthology](https://aclanthology.org/2020.emnlp-main.745); [code](https://www.github.com/dallascard/NLP-power-analysis)
- **Dror et al., "The Hitchhiker's Guide to Testing Statistical Significance in NLP"** (Technion, ACL 2018). A review of 2017 ACL and TACL papers found significance testing often skipped or misapplied. The paper proposes a protocol for choosing a test and was later expanded into a 2020 book. Relevance: classic precedent for paired, permutation, and bootstrap testing in NLP. — [ACL Anthology](https://aclanthology.org/P18-1128/)
- **Bowyer, Aitchison, Ivanova, "Position: Don't Use the CLT in LLM Evals With Fewer Than a Few Hundred Datapoints"** (ICML 2025 spotlight position paper, arXiv 2503.01747). CLT error bars "dramatically underestimate uncertainty" on small benchmarks. The authors recommend Bayesian or exact frequentist alternatives and release the `bayes_evals` library. Relevance: supports using a permutation test or bootstrap rather than CLT on the 90/100-question sets. — [arXiv](https://arxiv.org/abs/2503.01747); [ML Anthology](https://mlanthology.org/icml/2025/bowyer2025icml-position)
- **Heineman et al., "Signal and Noise: A Framework for Reducing Uncertainty in LM Evaluation"** (arXiv 2508.13144, NeurIPS 2025; authors include Hajishirzi, Lo, Dodge). The paper defines benchmark signal (ability to separate models) and noise (step-to-step variability) and shows that a higher signal-to-noise ratio gives better small-scale decisions. It covers 30 benchmarks and 465 models. — [arXiv](https://arxiv.org/abs/2508.13144); [NeurIPS](https://neurips.cc/virtual/2025/poster/115712). An Emergent Mind summary cites 375 models, which conflicts with the paper's 465; trust the paper.
- **Maia Polo et al., "tinyBenchmarks"** (ICML 2024, arXiv 2402.14992). IRT-curated sets of 100 examples estimate MMLU accuracy within about 1.9%. Relevance: the point here is estimating a *single model's* level. It is not about detecting *differences* between models, and Madaan et al. show that IRT subsets increase seed variance. Small curated sets are not a substitute for power in paired comparisons. — [arXiv](https://arxiv.org/abs/2402.14992); [PMLR](https://proceedings.mlr.press/v235/maia-polo24a.html)
- **Blackwell, Barry, Cohn, "Towards Reproducible LLM Evaluation: Quantifying Uncertainty in LLM Benchmark Scores"** (arXiv 2410.03492, NAACL 2025). The authors vary repeats from 1 to 30 on a 100-question benchmark and a 5,760-question benchmark. Models are non-deterministic even at temperature 0 with a fixed seed. The paper gives cost-effective guidance on repeated sampling. Relevance: closest precedent for the "5 replicates" design; it studies replicate count but not a question-vs-replicate cost trade-off on RAG. — [arXiv](https://arxiv.org/abs/2410.03492)
- **G-theory applied to LLM evals (2026).** Messing, "Hidden Measurement Error in LLM Pipelines..." (arXiv 2604.11581) treats prompt, judge, and replication as facets and finds that some pipeline variance does not shrink with more items. "Ask Which, Not How Good: Sizing Benchmarks Scored by an LLM" (arXiv 2609.27787) argues that for system comparisons, items buy nothing against the system×judge component and only more judges do. Relevance: the formal version of "more questions vs more replicates", and it adds the judge facet as a caveat. — [2604.11581](https://arxiv.org/html/2604.11581v3); [2609.27787](https://arxiv.org/pdf/2609.27787) (I saw these only as search excerpts and did not read the full text.)
- **RAG-specific statistics.** ARES (Stanford, arXiv 2311.09476, 2023) ranks RAG systems with 95% CIs built by prediction-powered inference, combining a small human-labelled set with LLM-judge labels. — [arXiv](https://arxiv.org/pdf/2311.09476). Some 2026 RAG papers use paired bootstrap on per-question judge scores (arXiv 2607.22592; 2604.08595) or Benjamini-Hochberg correction (2607.24781). — [2607.22592](https://arxiv.org/pdf/2607.22592); [2604.08595](https://arxiv.org/pdf/2604.08595); [2607.24781](https://arxiv.org/pdf/2607.24781) (search excerpts only).

### Inferences
- Every component of finding 4 has a published precedent: MDE/power (Card 2020, Miller 2024), the paired design (Miller), small-n CLT caveats (Bowyer 2025), replicates vs items (Miller, Blackwell, G-theory papers). Finding 4 is **already known** as methodology.
- The partly distinctive element is an empirically measured question-vs-replicate variance split, with a cost per precision point, *on a multi-hop RAG / GraphRAG pipeline*. I found no paper reporting that for RAG. Practitioner portfolios rarely show it.
- Caveat to raise in the write-up: with an LLM judge, the G-theory work suggests a judge facet that neither more questions nor more replicates can reduce. If the project scored with a fixed judge, say so, or show it used deterministic scoring such as EM/F1.

### Gaps
- I found no paper that reports a question-vs-replicate variance decomposition on MultiHop-RAG or 2WikiMultiHopQA specifically. Absence is based on a limited search (about 15 queries).
- I did not read 2609.27787 in full, so its exact claims about item sizing are from a search excerpt.

## Q3. Is pre-registration / blinding / held-out discipline used in ML and in LLM/RAG evaluation?

### Takeaway
Pre-registration has an established but niche history in ML/NLP: NeurIPS pre-registration workshops in 2020 and 2021 (PMLR v181), plus NAACL 2021 and EACL 2023 discussion papers. Holdout-reuse theory is classic (Dwork et al., Science 2015). In LLM evaluation, preregistration shows up only in scattered 2026 single-author preprints, and I found no RAG evaluation paper that pre-registers or blinds its analysis. Blinding (no scoring of held-out runs until the analysis plan is frozen) is the rarest element.

### Cited Findings
- **NeurIPS 2020 workshop, "The pre-registration experiment: an alternative publication model for ML research".** Papers are reviewed on their protocol before results exist; the workshop was motivated by "beat the SOTA" incentives and missing negative results. — [NeurIPS 2020](https://neurips.cc/virtual/2020/workshop/16158)
- **NeurIPS 2021 "Pre-registration workshop"** (Dec 13, 2021), a full pre-registration review cycle with proceedings in PMLR vol. 181. — [NeurIPS 2021](https://neurips.cc/virtual/2021/workshop/21885); [PMLR v181](https://proceedings.mlr.press/v181). I found no later edition.
- **van Miltenburg, van der Lee, Krahmer, "Preregistering NLP research"** (NAACL 2021, arXiv 2103.06944) proposes preregistration for NLP. **Søgaard, Hershcovich, de Lhoneux, "A Two-Sided Discussion of Preregistration of NLP Research"** (EACL 2023) weighs the downsides: risk of p-hacking, flag-planting, and a push toward confirmatory work; exploratory reclassification must stay possible. — [EACL 2023 ACL Anthology](https://aclanthology.org/2023.eacl-main.6); [arXiv 2302.10086](https://arxiv.org/abs/2302.10086). (I saw the 2021 paper only as a citation.)
- **Dwork, Feldman, Hardt, Pitassi, Reingold, Roth, "The reusable holdout: Preserving validity in adaptive data analysis"** (Science 349(6248), 2015). Adaptive reuse of a holdout causes spurious discoveries; access the holdout only through a differentially private mechanism. — [Google Research blog](https://research.google/blog/the-reusable-holdout-preserving-validity-in-adaptive-data-analysis/); [arXiv 1506.02629](https://arxiv.org/abs/1506.02629)
- **Roelofs et al., "A Meta-Analysis of Overfitting in Machine Learning"** (NeurIPS 2019). In over 100 Kaggle competitions with a private test set scored once, the authors found little evidence of substantial overfitting from public-holdout reuse. Relevance: an empirical counterpoint showing that the read-once discipline is the standard mitigation. — [NeurIPS 2019](https://papers.nips.cc/paper/9117-a-meta-analysis-of-overfitting-in-machine-learning)
- **Recent LLM/ML preprints using preregistration (2026).** Tamba, "Position Bias is Hidden Behind Ceiling Effects: A Permutation Diagnostic for LLM Benchmarks" (arXiv 2607.20864, Jul 2026) commits falsifier predictions and expected effect-size ranges as a SHA-256 hash posted before runs. Its Section 5.4, "Preregistration without a registered-report venue", describes a git tag plus a public hash plus a data snapshot. The paper cites no prior preregistration literature and admits some post-hoc refinements. — [arXiv](https://arxiv.org/html/2607.20864v1). Also "Clean Engineering, Unstable Measurement: A Preregistered Reliability Failure of Black-Box LLM Observers" (arXiv 2609.04198) — [arXiv](https://arxiv.org/pdf/2609.04198). Two biology foundation-model preprints use a locked test set scored once (2608.26170) and an access ledger for the test split (2608.00152). — [2608.26170](https://arxiv.org/pdf/2608.26170); [2608.00152](https://arxiv.org/pdf/2608.00152)
- An extended search for a position paper arguing for preregistering LLM benchmarks found none. — (search result, no source to cite)

### Inferences
- Each piece of finding 7 is **known**: Holm correction, sign-flip permutation test on paired per-question means, paired bootstrap (Dror 2018), pre-registration (NeurIPS 2020/21, NAACL 2021, EACL 2023), and the read-once holdout (Dwork 2015, Kaggle practice).
- The **combination**, applied to a RAG/GraphRAG evaluation, is **uncommon to apparently new in practice**: git-committed frozen constants, a read-once held-out split, *blinded* scoring until the analysis plan is frozen, and Holm across the family. The closest analog (Tamba 2026) is a single-author LLM benchmark preprint using a git-tag-plus-hash protocol, not RAG, and without the blinding step.
- Blinding, meaning not *scoring* held-out runs until the plan is frozen, mirrors "blind analysis" in particle physics and clinical trials. I found no LLM or RAG eval paper that describes it explicitly.

### Gaps
- I did not search particle-physics blind-analysis literature. It would be a citable classic precedent, but I have no verified link.
- I have no quantitative survey of how often RAG papers report CIs or significance. A claim that it is "rare" rests on the absence of hits, not on a measured rate.

## Q4. What is genuinely new vs standard best practice? (verdicts and portfolio distinctiveness)

### Takeaway
None of the statistical techniques is new. Finding 4 is **known** methodology with a **partly new empirical result** (a measured variance split and cost trade-off on multi-hop RAG). Finding 7 is a **known set of practices** whose **end-to-end use in RAG evaluation is uncommon**. For an applied LLM engineer's portfolio, both stand out a lot: they show rigor that most RAG blog posts and many papers lack. Frame them as "applied Miller 2024 / Bowyer 2025 / Card 2020 correctly, with pre-registration and blinding", not as methodological novelty.

### Cited Findings
- Standard practice, which most frontier-lab eval guidance already recommends, covers SEM/CI, clustered SEs, paired tests, power analysis, and resampling. — [Anthropic, Miller 2024](https://www.anthropic.com/research/statistical-approach-to-model-evals)
- Small-sample CLT intervals are unreliable, so prefer permutation or bootstrap on the 90/100-item sets; the project's choice aligns with this guidance. — [Bowyer et al. 2025](https://arxiv.org/abs/2503.01747)
- Underpowered comparisons are the common failure mode in NLP. — [Card et al. 2020](https://aclanthology.org/2020.emnlp-main.745)
- Preregistration in ML remains a niche, workshop-level practice, and NLP has open debate about its costs. — [NeurIPS 2021 workshop](https://neurips.cc/virtual/2021/workshop/21885); [Søgaard et al. 2023](https://aclanthology.org/2023.eacl-main.6)

### Inferences
Verdict per finding:

| Finding element | Verdict | Closest work |
|---|---|---|
| (4a) about 90 questions means only about 8-point MDE | Known (direct application of the power/MDE formula) | Miller 2024 (arXiv 2411.00640); Card et al. 2020 |
| (4b) about 880 fresh questions, Opus vs deepseek +5.0 [2.4, 7.8]; 2Wiki +14 | Known method; new data point (a model comparison, not a methods contribution) | Miller 2024 recommends n of 1,000 or more and paired differences |
| (4c) variance mostly across questions; K=2 to 3 buys about 3-4% precision for +50% cost | Partially known: the theory is in Miller 2024, Blackwell 2024/25, and G-theory 2026; an empirical measurement on multi-hop RAG appears new | Miller 2024; Blackwell et al. (arXiv 2410.03492); Messing (arXiv 2604.11581) |
| (7a) pre-registration with frozen constants committed in git | Known in ML/NLP and rare in LLM eval; closest is Tamba 2026's git-tag-plus-hash protocol | NeurIPS 2020/21 workshops; Søgaard 2023; arXiv 2607.20864 |
| (7b) held-out split read once | Standard (lockbox / Kaggle private leaderboard); theory in Dwork 2015 | Dwork et al. 2015; Roelofs et al. 2019 |
| (7c) blinding until the analysis plan is frozen | Known in physics and clinical trials; I found no LLM/RAG eval precedent, so it looks uncommon to new in this domain | none found in LLM/RAG |
| (7d) Holm, sign-flip permutation on per-question means, paired bootstrap | Standard textbook NLP significance practice | Dror et al. 2018; Bowyer 2025 (small-n caveat) |

- Portfolio framing: the distinctive signal is *discipline and honest power accounting*: admitting the 90-question set could not resolve differences under 8 points, then collecting about 880 fresh questions. It is not new statistics. Citing Miller 2024 and Bowyer 2025 explicitly strengthens the credibility of the portfolio piece.
- A possible weak spot reviewers may probe: an LLM judge facet (2609.27787), and whether 100 2Wiki dev questions get CLT-based or permutation-based CIs (Bowyer 2025).

### Gaps
- I could not confirm any industry RAG-eval tool (RAGAS, TruLens, and others) that ships pre-registration or blinding features. I did not search this directly.
