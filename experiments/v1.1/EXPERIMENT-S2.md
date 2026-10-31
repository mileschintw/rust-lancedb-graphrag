# S2 Reader: pre-registration

Status: **draft, not yet pre-registered.** RUN-S2.md step 1 pastes the constant below into `thresholds.py` with S1's
winner filled in. It becomes the pre-registration when step 4, with Sonnet 5.5's target settled by the pilot, commits
it with this file on a clean tree before the run of record's `replay-init` (D-73, D-240, D-253).
The **Result** section is filled in after the run and nothing above it changes.

How to run it: [RUN-S2.md](RUN-S2.md).

## Question

How much does the answering model matter on identical context? S2 keeps S1's retrieval and prompt fixed and changes
only the reader (PLAN.md › S2 details, D-235).

## Arms (D-254, D-257)

The deepseek arm is not re-run: `replay-init` carries S1's records of the winning arm into the S2 run, with their
context export rows and row hashes (Q9). Each Claude reader reads the same packed prompts, sent through a Claude batch
(D-254), with only the declared fields rewritten (D-255).

| Arm label | Reader | How it is read |
|---|---|---|
| `<S1 winner>` (reference) | `deepseek/deepseek-v4-flash-0731`, as in S1 | carried from the S1 run of record |
| `<S1 winner>@haiku-5.5` | Haiku 5.5 | OpenRouter batch, BYOK |
| `<S1 winner>@sonnet-5.5` | Sonnet 5.5 | OpenRouter batch, or the native Anthropic Message Batches API if the pilot says so (D-260) |
| `<S1 winner>@opus-5.5` | Opus 5.5 | only if D-252's condition holds; see *Opus 5.5* |

`<S1 winner>` is the arm EXPERIMENT-S1.md › Result names: the chosen store's `hybrid+rerank+metadata` arm, or its
graph-on arm if the graph joined (one of `small/hybrid+rerank+metadata`, `small/hybrid+graph+rerank+metadata`,
`merged/hybrid+rerank+metadata`, `merged/hybrid+graph+rerank+metadata`). Until S1's step 4.8, the draft constant and the
corpus hold the placeholder `S1_WINNER_UNSET` in its place. The corpus does not load while it stands.

## Data

Corpus `multihop_rag_s2_dev`: the S1 dev corpus's documents, questions (`questions.diag.jsonl`), split
(`heldout_split.json` role `dev`) and stores, copied section for section (a test pins this). The D-237 dev pool of
100 (90 G, 10 null). No held-out question is read, so S2 uses none of D-237's two held-out reads.

## Pre-registration constant

`PREREGISTRATION_S2`, a `ReplayStagePreRegistration`
([`eval/src/lancet_eval/thresholds.py`](../../eval/src/lancet_eval/thresholds.py)). Its draft is the block below:

- `replay_source_arm`: S1's winner. `replay-init` refuses to carry any other arm (#109).
- Reference: the carried deepseek arm. One `answer_usable` family: the Haiku 5.5 and Sonnet 5.5 reader arms. The
  family is `decisional` only because the lever comparison needs one; S2 is direction-finding.
- The null guard reads both reader arms.
- `readers`: the per-reader table below. The constant refuses any arm that is not `replay_source_arm` or one of its
  reader arms.

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
# levers-dev pool of 100 (90 G, 10 null). Direction-finding: the harness computes the
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
    descriptive_arms=(),
    test="paired_sign_flip_exact_two_sided",
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
        "own and stays eligible (D-270a). Reader choice: the eligible reader with "
        "the highest answer_usable point estimate on G wins, unless a cheaper "
        "eligible reader is within 0.02 (2 points) of it; with more than one such "
        "reader the cheapest wins (D-270b). Cheaper means a lower cost per answered "
        "question at sync list price x tokens (reader_comparison, D-257). Two "
        "Claude readers' point estimates are compared through their paired deltas "
        "against deepseek on the common population (D-270c). Opus 5.5 is run only "
        "if the sonnet-5.5 delta minus the haiku-5.5 delta is at least +0.05, "
        "through its own constant PREREGISTRATION_OPUS_S2, committed before its "
        "submit (D-267); this reading is unchanged by it. Default-model switch "
        "(D-245): Lancet's default generation model may change from deepseek to "
        "haiku-5.5 iff the haiku-5.5 row is not significantly worse (Holm over this "
        "family, m = 2, alpha 0.05, does not reject it with a negative delta; "
        "D-268), its point estimate is at least -0.03, its null guard passes, and "
        "its cost per answered question is below deepseek's; a separate product "
        "decision with its own reading. p-values are reported, not used, except in "
        "that Holm test"
    ),
    provenance=(
        "v1.1 S2. D-252 (direction-finding reader rule: highest point estimate wins "
        "unless a cheaper reader is within 2 points, null guard on every candidate, "
        "Opus only if Sonnet minus Haiku is at least +5 points; D-245 read as a "
        "paired Haiku vs deepseek comparison with a point estimate of at least -3 "
        "points), D-245 (default-model switch rule), D-254 (replay path; the "
        "deepseek arm is carried, not re-run), D-255 and D-260 (request rewrite and "
        "the per-reader thinking table: Haiku 5.5 off, Sonnet 5.5 between_tools, "
        "Opus 5.5 on at effort low), D-257 (reader arms, replay clauses, cost per "
        "answered question at sync list price; no evidence Hits@4), D-265 (clauses "
        "by reader target), D-237 (dev pool of 100, no held-out read), D-267 (Opus "
        "through its own constant; owner 2026-10-31: '另立常數 (Recommended)'), "
        "D-268 (Holm-adjusted p for D-245; owner: 'Holm 調整後 (Recommended)'), "
        "D-269 (numbers as D-262 and D-264; Opus over OpenRouter at list price; "
        "owner: '沿用 + 查牌價 (Recommended)'), D-270 (three readings of D-252; "
        "owner: '照草稿 (Recommended)'). Prices, USD per MTok: Haiku 5.5 0.10/0.50 "
        "and Sonnet 5.5 2/10 (decisions 2026-10-30); Opus 5.5 4/20, read "
        "2026-10-31 from https://platform.claude.com/docs/en/about-claude/pricing "
        "(D-269). Sonnet 5.5's target is openrouter unless the pilot (RUN-S2.md "
        "step 3) shows between_tools does not pass; then anthropic, "
        "claude-sonnet-5-5 (D-260). Written 2026-10-31, before any S2 data."
    ),
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
| Haiku 5.5 | `anthropic/claude-haiku-5.5` | OpenRouter | off: `reasoning: {enabled: false}` | 0.10 / 0.50 |
| Sonnet 5.5 | `anthropic/claude-sonnet-5.5` | OpenRouter (else native `claude-sonnet-5-5`) | `between_tools` | 2 / 10 |
| Opus 5.5, only if it joins (D-267) | `anthropic/claude-opus-5.5` | OpenRouter (D-269) | on, effort low | 4 / 20 (D-269) |

- A reader declared `off` or `between_tools` must report `reasoning_tokens` = 0; a record that does not is a provenance
  failure (D-255, D-260). Opus at effort low is exempt.
- On the native target, `is_byok` is null, the provider is `api.anthropic.com`, and the response must hold no
  `thinking` or `redacted_thinking` block (D-265).
- The Batch API bills half the list price. Cost per answered question is computed at the sync list price above, times
  the tokens, for every reader including deepseek (D-257). The actual batch spend is reported separately.

## Metrics

- **Primary:** `answer_usable` on the G population (90), paired per question against the carried deepseek arm.
- **Reported per reader:** paired differences, the null guard, and cost per answered question (`reader_comparison` in
  `lever-comparison.json`).
- **Not reported:** evidence Hits@4. The context is identical across readers (D-257).

## Decision rule (D-252, D-245)

Direction-finding on dev. The harness computes the paired deltas, null guards and cost per answered question. The
choice is applied by hand in the **Result** section. p-values are reported and not used, except in D-245's
not-significantly-worse test.

1. **Eligibility.** A Claude reader is a candidate only if its null guard passes (margin 0.10, pair fraction 0.80 on
   the 10 dev nulls: a net abstention drop of 2 or more with 10 null pairs fails; fewer than 8 null pairs is not
   evaluable). A failed or not-evaluable guard removes that reader. deepseek is the guard's reference and has no guard
   of its own; it stays a candidate (D-270a).
2. **Reader choice.** The candidate with the highest `answer_usable` point estimate wins, unless a cheaper candidate
   is within 2 points of it; with more than one such candidate, the cheapest wins (D-270b). "Cheaper" means a lower
   cost per answered question. Two Claude readers are compared through their paired deltas against deepseek on the
   common population (D-270c).
   The winner becomes S3's fixed reader.
3. **Opus 5.5.** Opus joins only if the Sonnet 5.5 delta minus the Haiku 5.5 delta is at least +5 points (D-252),
   through its own constant (D-267; see *Opus 5.5* below).
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

D-252 lets Opus join only after the first reading. Its reader row is declared in this constant now (Q13, D-269): Opus
5.5 over OpenRouter at $4 / $20 per MTok, Anthropic's list price read 2026-10-31 from
<https://platform.claude.com/docs/en/about-claude/pricing>. Its arm is not in this constant (D-267). If the condition
holds, `PREREGISTRATION_OPUS_S2` is written: this constant plus `<S1 winner>@opus-5.5` in the family and the null
guard. Its name does not start with `PREREGISTRATION_S2`, so it leaves this constant's D-73 date alone, and the first
reading stays as registered. It is read in its own run directory on its own corpus, `multihop_rag_s2_opus_dev`,
where Haiku 5.5 and Sonnet 5.5 are read again beside Opus 5.5 (RUN-S2.md step 8).

## Smallest detectable effect (D-237, D-239)

With 90 G pairs, a significant difference needs a net margin of about 2√d questions: for 15 to 30 discordant pairs,
9 to 12 net questions, **about 10 to 13 points**. That is why the rule reads point estimates. The 2-point
cheaper-reader band and the -3-point D-245 floor are 2 and 3 net questions of 90.

## Run constraints

- Main checkout, clean tree, at a commit that holds this file and the constant with the winner filled in (D-73).
  `replay-init` and `batch submit` on the run of record run the D-73 check before any paid call (#109).
- The pilot runs before that commit, from the working tree, in its own throwaway run directory made with
  `replay-init --pilot` (#109). Only a pilot run takes `batch submit --limit`.
- D-258: no mid-run cap; each submit prints a cost estimate and never refuses.
- No prompt caching (D-256).

## Decisions (D-267 to D-270)

The owner settled the draft's five open questions on 2026-10-31 (PLAN.md › S2 pre-registration decisions):

- **D-267:** Opus 5.5 joins through its own constant, `PREREGISTRATION_OPUS_S2`.
- **D-268:** D-245's "not significantly worse" reads the Holm-adjusted p (m = 2, alpha 0.05).
- **D-269:** S2 reuses D-262's and D-264's numbers; Opus 5.5 is read over OpenRouter at Anthropic's list price.
- **D-270:** D-252's three open readings are applied as drafted.

## Result

Not run yet.
