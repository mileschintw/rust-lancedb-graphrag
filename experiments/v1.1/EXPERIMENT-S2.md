# S2 Reader: pre-registration

Status: **draft, not yet pre-registered.** RUN-S2.md step 1 pastes the constant below into `thresholds.py` with S1's
winner filled in. It becomes the pre-registration when step 4, with Sonnet 5.5's target settled by the pilot, commits
it with this file on a clean tree before the run of record's `replay-init` (D-73, D-240, D-253).
The **Result** section is filled in after the run and nothing above it changes.

How to run it: [RUN-S2.md](RUN-S2.md).

## Question

How much does the answering model matter on identical context? S2 keeps S1's retrieval and prompt fixed and changes
only the reader (PLAN.md › S2 details, D-235).

## Arms (D-254, D-257, D-274)

Every arm answers each question **5 times** (K = 5, D-274), each answer its own batch request (`custom_id`
`<question ID>_r<k>`) and its own journal record (`replicate` 1 to 5). `replay-init` carries S1's records of the
winning arm into the S2 run, with their context export rows and row hashes (Q9): they are the deepseek arm's
replicate 1. Its replicates 2 to 5 are new deepseek answers to the same packed prompts, the engine's `pack` body sent
unrewritten through an OpenRouter batch with D-271's provider pin. Each Claude reader reads the same packed prompts,
sent through a Claude batch (D-254), with only the declared fields rewritten (D-255), 5 times.

| Arm label | Reader | How it is read |
|---|---|---|
| `<S1 winner>` (reference) | `deepseek/deepseek-v4-flash-0731`, as in S1 | replicate 1 carried from the S1 run of record; replicates 2 to 5 by OpenRouter batch, pinned to wafer/us (D-271), on OpenRouter credit |
| `<S1 winner>@haiku-5.5` | Haiku 5.5 | OpenRouter batch, BYOK |
| `<S1 winner>@sonnet-5.5` | Sonnet 5.5 | OpenRouter batch, or the native Anthropic Message Batches API if the pilot says so (D-260) |
| `<S1 winner>@opus-5.5` (descriptive) | Opus 5.5 | OpenRouter batch, BYOK, in parallel with the other two (D-267) |

The readers' sampling differs: deepseek at temperature 0, the Claude 5.5 readers at their default sampling (they take
no temperature) with the thinking setting of each row below. S2 compares each reader at the setting it is used with,
not under one decoding condition.

`<S1 winner>` is the arm EXPERIMENT-S1.md › Result names: the chosen store's `hybrid+rerank+metadata` arm, or its
graph-on arm if the graph joined (one of `small/hybrid+rerank+metadata`, `small/hybrid+graph+rerank+metadata`,
`merged/hybrid+rerank+metadata`, `merged/hybrid+graph+rerank+metadata`). Until S1's step 4.8, the draft constant and the
corpus hold the placeholder `S1_WINNER_UNSET` in its place. The corpus does not load while it stands.

## Data

Corpus `multihop_rag_s2_dev`: the S1 dev corpus's documents, questions (`questions.diag.jsonl`), split
(`heldout_split.json` role `dev`) and stores, copied section for section (a test pins this). The D-237 dev pool of
100 (90 G, 10 null), 5 answers per question and arm: 500 records per arm. No held-out question is read, so S2 uses none
of D-237's two held-out reads.

## Pre-registration constant

`PREREGISTRATION_S2`, a `ReplayStagePreRegistration`
([`eval/src/lancet_eval/thresholds.py`](../../eval/src/lancet_eval/thresholds.py)). Its draft is the block below:

- `replay_source_arm`: S1's winner. `replay-init` refuses to carry any other arm (#109).
- Reference: the carried deepseek arm. One `answer_usable` family: the Haiku 5.5 and Sonnet 5.5 reader arms. The
  family is `decisional` only because the lever comparison needs one; S2 is direction-finding.
- The null guard reads both reader arms.
- `descriptive_arms`: the Opus 5.5 reader arm (D-267).
- `readers`: the per-reader table below. The constant refuses any arm that is not `replay_source_arm` or one of its
  reader arms.
- `replicates=5` and `test="paired_sign_flip_permutation_exact_two_sided"` (D-274); the constant refuses replicates
  above 1 with any other test.

### The constant (draft)

RUN-S2.md copies this block into `thresholds.py`, after replacing `S1_WINNER_UNSET` with S1's winner. It is not in
`thresholds.py` until then. D-73 dates the constant by the first commit that adds its name to
that file, so the name must enter the file once, in the commit that freezes it. Until that commit the S2 corpus names
a constant that does not exist, and `resolve` refuses it. A test builds this block with each of S1's four arms and
checks it against the corpus and the readers table.

~~~python
# v1.1 S2 (D-252, D-254 to D-260, D-265; experiments/v1.1/EXPERIMENT-S2.md): S1's
# winning arm, read by deepseek in S1 and carried into S2 (D-254, Q9), against the same
# packed prompts read by Haiku 5.5 and Sonnet 5.5 through Claude batches, on the
# levers-dev pool of 100 (90 G, 10 null), 5 answers per question and arm (D-274: the
# carried answer is deepseek's first). Direction-finding: the harness computes the
# paired differences, null guards and cost per answered question, and the choice is
# applied by hand in EXPERIMENT-S2.md (D-252). Added in one commit by RUN-S2.md step 4,
# after the pilot and before the run of record's replay-init (D-73).
PREREGISTRATION_S2 = ReplayStagePreRegistration(
    replay_source_arm="S1_WINNER_UNSET",
    reference_arm="S1_WINNER_UNSET",
    families=(
        FamilySpec(
            primary="answer_usable",
            role="decisional",
            arms=(
                "S1_WINNER_UNSET@haiku-5.5",
                "S1_WINNER_UNSET@sonnet-5.5",
            ),
            alpha=0.05,
        ),
    ),
    descriptive_arms=("S1_WINNER_UNSET@opus-5.5",),
    test="paired_sign_flip_permutation_exact_two_sided",
    non_evaluable_rule="p=1_m_unchanged",
    population="pairwise_per_comparison",
    complete_case_floor=0.80,
    matching_rule="chunk_id_via_gold_chunks",
    bootstrap_b=10_000,
    bootstrap_seed=42,
    null_guard_arms=(
        "S1_WINNER_UNSET@haiku-5.5",
        "S1_WINNER_UNSET@sonnet-5.5",
    ),
    null_guard_predicate="metrics.is_abstention",
    null_guard_margin=0.10,
    null_guard_min_pair_fraction=0.80,
    answer_mix_strata=("comparison_query", "binary_gold"),
    sc2_timeout_rate_floor=0.025,
    rerank_degrade_tripwire_rate=0.20,
    rerank_degrade_tripwire_min_calls=50,
    rerank_consecutive_degrade_halt=5,
    default_rule=(
        "Applied by hand in EXPERIMENT-S2.md, never by code (D-252). Candidates: "
        "deepseek (the carried reference arm), haiku-5.5 and sonnet-5.5. A Claude "
        "reader is eligible iff its null guard passes; a failed or not-evaluable "
        "guard removes it. deepseek is the guard's reference, has no guard of its "
        "own and stays eligible (D-270a). Every arm answers each question 5 times; a "
        "question's score is its mean answer_usable over the 5, and every test is "
        "the exact sign-flip permutation on the per-question mean differences "
        "(D-274). Reader choice: the eligible reader with the lowest cost per "
        "answered question (sync list price x tokens over all 5 answers, "
        "reader_comparison, D-257) is the starting pick and wins, unless a dearer "
        "eligible reader is significantly better on answer_usable than it: every "
        "pair of eligible readers is tested on its own population "
        "(reader_comparison pairs), Holm runs once over all those pairs at alpha "
        "0.05, and a dearer reader whose pair with the pick Holm rejects with a "
        "positive delta is significantly better. Then the pick steps up to the "
        "cheapest such reader and the check repeats against the readers dearer "
        "than it; the pick no dearer reader beats wins (D-275, amending D-270b). A "
        "pick of the cheapest reads 'no larger difference detected', not equivalence: "
        "the smallest detectable effect is about 0.084 (8.4 points). opus-5.5 is a "
        "descriptive arm, run unconditionally beside the other two: reported with "
        "its paired delta and cost per answered question, outside the winner rule "
        "and the Holm family (D-267). Default-model switch "
        "(D-245): Lancet's default generation model may change from deepseek to "
        "haiku-5.5 iff the haiku-5.5 row is not significantly worse (Holm over this "
        "family, m = 2, alpha 0.05, does not reject it with a negative delta; "
        "D-268), its point estimate is at least -0.03, its null guard passes, and "
        "its cost per answered question is below deepseek's; a separate product "
        "decision with its own reading. p-values are reported, not used, except in "
        "the reader choice's and that switch's Holm tests"
    ),
    provenance=(
        "v1.1 S2. D-252 (direction-finding reader rule: highest point estimate wins "
        "unless a cheaper reader is within 2 points, null guard on every candidate; "
        "D-245 read as a "
        "paired Haiku vs deepseek comparison with a point estimate of at least -3 "
        "points), D-245 (default-model switch rule), D-254 (replay path; the "
        "deepseek arm is carried, not re-run), D-255 and D-260 (request rewrite and "
        "the per-reader thinking table: Haiku 5.5 off, Sonnet 5.5 between_tools, "
        "Opus 5.5 on at effort low), D-257 (reader arms, replay clauses, cost per "
        "answered question at sync list price; no evidence Hits@4), D-265 (clauses "
        "by reader target), D-237 (dev pool of 100, no held-out read), D-267 (Opus "
        "a descriptive arm, run unconditionally; supersedes D-252's 'Opus only if "
        "Sonnet minus Haiku is at least +5 points'; owner 2026-10-31: '是，無條件跑 "
        "(Recommended)'), "
        "D-268 (Holm-adjusted p for D-245; owner: 'Holm 調整後 (Recommended)'), "
        "D-269 (numbers as D-262 and D-264; Opus over OpenRouter at list price; "
        "owner: '沿用 + 查牌價 (Recommended)'), D-270 (three readings of D-252; "
        "owner: '照草稿 (Recommended)'), D-274 (5 replicates per question and arm, "
        "the sign-flip permutation on per-question means, a paired t cross-check, "
        "the bootstrap over questions; supersedes the sign test; owner: '全部 "
        "K=5'), D-275 (the cheapest eligible reader unless a dearer one is "
        "significantly better after Holm; amends D-270b; owner: '預設最便宜，顯著才"
        "換 (Recommended)'), D-277 (deepseek priced at Wafer's wafer/us price, "
        "0.0434/0.30, read 2026-10-31 from OpenRouter's endpoints API; owner: "
        "'改用 Wafer 實際價 (Recommended)'). Prices, USD per MTok: Haiku 5.5 0.10/0.50 "
        "and Sonnet 5.5 2/10 (decisions 2026-10-30); Opus 5.5 4/20, read "
        "2026-10-31 from https://platform.claude.com/docs/en/about-claude/pricing "
        "(D-269). Sonnet 5.5's target is openrouter unless the pilot (RUN-S2.md "
        "step 3) shows between_tools does not pass; then anthropic, "
        "claude-sonnet-5-5 (D-260). Written 2026-10-31, before any S2 data."
    ),
    replicates=5,
    reference_price=ReaderPrice(input_per_mtok=0.0434, output_per_mtok=0.30),
    readers=(
        (
            "haiku-5.5",
            ReaderDeclaration(
                slug="anthropic/claude-haiku-5.5",
                target="openrouter",
                thinking="off",
                price=ReaderPrice(input_per_mtok=0.10, output_per_mtok=0.50),
            ),
        ),
        (
            "sonnet-5.5",
            ReaderDeclaration(
                slug="anthropic/claude-sonnet-5.5",
                target="openrouter",
                thinking="between_tools",
                price=ReaderPrice(input_per_mtok=2.0, output_per_mtok=10.0),
            ),
        ),
        (
            "opus-5.5",
            ReaderDeclaration(
                slug="anthropic/claude-opus-5.5",
                target="openrouter",
                thinking="on",
                effort="low",
                price=ReaderPrice(input_per_mtok=4.0, output_per_mtok=20.0),
            ),
        ),
    ),
)
~~~

### Readers (Q4, Q10, Q13; D-255, D-257, D-260, D-265)

| Reader | Slug | Target | Thinking | Sync list price, USD per MTok (in / out) |
|---|---|---|---|---|
| deepseek (reference, `reference_price`, D-277) | `deepseek/deepseek-v4-flash-0731` | OpenRouter, pinned to wafer/us (D-271) | off: `reasoning: {effort: none}` | 0.0434 / 0.30, Wafer's wafer/us price |
| Haiku 5.5 | `anthropic/claude-haiku-5.5` | OpenRouter | off: `reasoning: {enabled: false}` | 0.10 / 0.50 |
| Sonnet 5.5 | `anthropic/claude-sonnet-5.5` | OpenRouter (else native `claude-sonnet-5-5`) | `between_tools` | 2 / 10 |
| Opus 5.5, descriptive (D-267) | `anthropic/claude-opus-5.5` | OpenRouter (D-269) | on, effort low | 4 / 20 (D-269) |

- A reader declared `off` or `between_tools` must report `reasoning_tokens` = 0; a record that does not is a provenance
  failure (D-255, D-260). Opus at effort low is exempt.
- On the native target, `is_byok` is null, the provider is `api.anthropic.com`, and the response must hold no
  `thinking` or `redacted_thinking` block (D-265).
- The Batch API bills half the list price. Cost per answered question is computed at the sync list price above, times
  the tokens, for every reader including deepseek (D-257), over all 5 answers of each question (D-274). The actual
  batch spend is reported separately.
- deepseek's price is the one D-271 pins it to, Wafer's wafer/us endpoint, read 2026-10-31 from OpenRouter's endpoints
  API for `deepseek/deepseek-v4-flash-0731` ($0.0434 / $0.30 per M tokens), not D-257's 2026-10-09 list price
  ($0.0137 / $1.28, `measure.GENERATION_LIST_*`). It is the constant's `reference_price`, so D-73 freezes it (D-277).
- deepseek's replicates 2 to 5 (D-274) are the `pack` body unrewritten. Their records must show the body's model, the
  body's pinned provider (wafer/us, D-271), `is_byok` false (OpenRouter credit) and 0 reasoning tokens (the body sends
  `reasoning: {effort: none}`); the body must carry the D-271 pin, or `batch submit` refuses it.

## Metrics

- **Primary:** `answer_usable` on the G population (90), paired per question against the carried deepseek arm, under
  D-276's normalisation: D-70's whole-token containment, with singular and plural folded together and list answers
  matched in any order, applied to every arm.
- **Secondary (D-276):** a dual judge, `openai/gpt-4o-mini` and Claude Sonnet 5.5, each told only the question, the
  gold answer and the extracted final line, never the arm. `lancet-eval judge-answers` reports per-arm judged rates
  for both judges beside the primary, and lists every disagreement (judge against judge, judge against the primary)
  for the owner. It decides nothing. Sonnet judging Claude readers is allowed for this secondary only (D-276); the
  disagreements on Claude arms measure self-preference.
- **Reported per reader:** paired differences, the null guard, and cost per answered question (`reader_comparison` in
  `lever-comparison.json`).
- **Not reported:** evidence Hits@4. The context is identical across readers (D-257).

## Decision rule (D-252, D-245, D-274, D-275)

Direction-finding on dev. The harness computes the paired deltas, null guards and cost per answered question. The
choice is applied by hand in the **Result** section. p-values are reported and not used, except in the reader
choice's and D-245's Holm tests.

0. **Scores and tests (D-274).** A question's score under an arm is its mean `answer_usable` over its 5 answers, and
   a question enters a comparison only when all 5 answers of both arms are ok. Every p-value is the exact two-sided
   sign-flip permutation test on the per-question mean differences (`raw_p`); the paired t-test beside it
   (`paired_t_p`) is a cross-check and decides nothing. CIs are the bootstrap over questions (10,000 resamples, seed
   42), each question carrying its 5 answers.
1. **Eligibility.** A Claude reader is a candidate only if its null guard passes (margin 0.10, pair fraction 0.80 on
   the 10 dev nulls). With 5 answers the guard pairs answer k of the reader with answer k of deepseek, so it counts 50
   null pairs: a net abstention drop of 6 or more of 50 fails (above 0.10), and fewer than 8 paired null questions is
   not evaluable. Only the pass or fail is read: the printed one-sided bound treats a question's 5 pairs as
   independent. A failed or not-evaluable guard removes that reader. deepseek is the guard's reference and has no
   guard of its own; it stays a candidate (D-270a).
2. **Reader choice (D-275, amending D-270b).** The candidate with the lowest cost per answered question is the
   starting pick, and it wins unless a dearer candidate is significantly better on `answer_usable` than it:
   - every pair of candidates is tested with D-274's test on that pair's own population (`reader_comparison` ›
     `pairs`);
   - Holm runs once over all those pairs (m = the number of candidate pairs, 3 with three candidates) at alpha 0.05,
     by hand from the pairs' `raw_p`;
   - a dearer candidate is significantly better when Holm rejects its pair with the pick and the delta favours it.
     The pick then steps up to the cheapest such candidate, and the check repeats against the candidates dearer than
     it. The pick no dearer candidate is significantly better than wins.

   Picking the cheapest reads "no larger difference detected" (see Smallest detectable effect), not equivalence.
   The winner becomes S3's fixed reader.
3. **Opus 5.5** is a descriptive arm (D-267): reported, never a candidate, and outside the Holm family (m = 2).
4. **Default-model switch (D-245).** Lancet's default generation model may change from deepseek to Haiku 5.5 only if
   all of these hold for the Haiku 5.5 row:
   - it is not significantly worse than deepseek: Holm over this family (m = 2, alpha 0.05) does not reject the
     Haiku row with a negative delta (D-268);
   - its point estimate is at least -3 points;
   - its null guard passes;
   - its cost per answered question is below deepseek's.

   This is a separate product decision with its own reading. S2 only records whether the rule holds.
5. **Other numbers**, as PREREGISTRATION_S1 (D-269, from D-262 and D-264): alpha 0.05, complete-case floor 0.80, bootstrap 10,000 with seed
   42. The SC-2 timeout floor and the rerank tripwire are carried in the constant, but no drive runs in S2.

### Opus 5.5

Opus 5.5 runs unconditionally, in the pilot and in the run of record, in parallel with Haiku 5.5 and Sonnet 5.5
(D-267, superseding D-252's "Opus 5.5 joins only if Sonnet minus Haiku is at least +5 points"). Its arm is in
`descriptive_arms`, so it is reported with its paired difference against deepseek and its cost per answered question,
but it is not a candidate and does not enter the Holm family. Its reader row (Q13, D-269): over OpenRouter, thinking on
at effort low (exempt from the `reasoning_tokens` clause, D-265), at $4 / $20 per MTok, Anthropic's list price read
2026-10-31 from <https://platform.claude.com/docs/en/about-claude/pricing>.

## Smallest detectable effect (D-237, D-239, D-275)

At K = 5 and n = 90 G pairs, two-sided alpha 0.05 and power 0.8, the expected smallest detectable effect is **about
8.4 points** (#127; `reports/noise-research.md` §3.2). The estimate takes the reader noise from S1's deepseek flip
rate on identical prompts (3 of 68, a within-question variance of about 0.022 per answer) and the rest of the
per-question variance from S1's discordance; with one answer per question it was about 10 points. Readers closer than
about 8 points are not told apart, so the rule picks the cheapest unless a dearer reader clears that bar. The Claude
readers' own noise is not known before the run: if it is well above deepseek's, the effect detectable is larger. The
-3-point D-245 floor is about 3 net questions of 90.

## Run constraints

- Main checkout, clean tree, at a commit that holds this file and the constant with the winner filled in (D-73).
  `replay-init` and `batch submit` on the run of record run the D-73 check before any paid call (#109).
- The pilot runs before that commit, from the working tree, in its own throwaway run directory made with
  `replay-init --pilot` (#109). Only a pilot run takes `batch submit --limit`.
- D-258: no mid-run cap; each submit prints a cost estimate and never refuses.
- No prompt caching (D-256).
- Four batch arms: the three readers and deepseek's replicates 2 to 5 (D-274). Each arm counts 500 records when it is
  complete; `score` checks replicate 1 only, so the run guide counts every replicate.

## Decisions (D-267 to D-270, D-274, D-275)

The owner settled the draft's five open questions on 2026-10-31 (PLAN.md › S2 pre-registration decisions):

- **D-267:** Opus 5.5 runs unconditionally as a descriptive arm, in parallel with the other readers.
- **D-268:** D-245's "not significantly worse" reads the Holm-adjusted p (m = 2, alpha 0.05).
- **D-269:** S2 reuses D-262's and D-264's numbers; Opus 5.5 is read over OpenRouter at Anthropic's list price.
- **D-270:** D-252's three open readings are applied as drafted.

After the S1 dev-run analysis, the owner added two more on 2026-10-31 (#123, #127):

- **D-274:** every arm answers each question 5 times; the per-question mean is tested by the exact sign-flip
  permutation, with a paired t cross-check and a bootstrap over questions. It supersedes the sign test for S2.
- **D-275:** the cheapest eligible reader wins unless a dearer one is significantly better after Holm (amends D-270b).

## Result

Not run yet.
