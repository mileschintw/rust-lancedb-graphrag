"""Decision thresholds and inputs committed before running measurement pass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ThresholdError(ValueError):
    """Raised when a required decision threshold is missing or uncommitted."""


@dataclass(frozen=True)
class DecisionThresholds:
    """Explicit decision inputs committed before measurement data is observed.

    Per D-14 and D-18, the multiplier and decay thresholds have no default values
    in this class definition so that uncommitted guesses cannot be shipped as policy.
    """

    multiplier: float
    decay_significance_threshold: float
    materiality_delta_ms: float
    window_fractions: tuple[float, float]
    segment_boundary_sizes: tuple[int, int]
    min_stratum_cell_size: int
    max_tolerated_graph_timeout_rate: float
    derivation_percentile: float = 0.95
    bootstrap_seed: int = 42
    slack_ms: float = 500.0
    provenance: str = ""

    def validate_for_derivation(self) -> None:
        """Assert required threshold inputs for budget derivation are present."""
        if self.multiplier is None or self.multiplier <= 0:
            raise ThresholdError(
                "Derivation requires positive committed multiplier, "
                f"got {self.multiplier!r}"
            )
        if not (0.0 < self.derivation_percentile < 1.0):
            raise ThresholdError(
                "Derivation requires percentile in (0, 1), "
                f"got {self.derivation_percentile!r}"
            )

    def validate_for_decay(self) -> None:
        """Assert required threshold inputs for decay detection are present."""
        if not (0.0 < self.decay_significance_threshold < 1.0):
            raise ThresholdError(
                "Decay detection requires significance threshold in (0, 1), "
                f"got {self.decay_significance_threshold!r}"
            )
        if self.materiality_delta_ms < 0:
            raise ThresholdError(
                "Decay detection requires non-negative materiality delta, "
                f"got {self.materiality_delta_ms!r}"
            )
        if len(self.window_fractions) != 2 or any(
            f <= 0 or f >= 0.5 for f in self.window_fractions
        ):
            raise ThresholdError(
                "Window fractions must be 2 positive fractions < 0.5, "
                f"got {self.window_fractions!r}"
            )
        if len(self.segment_boundary_sizes) != 2 or any(
            s <= 0 for s in self.segment_boundary_sizes
        ):
            raise ThresholdError(
                "Segment boundary sizes must be 2 positive counts, "
                f"got {self.segment_boundary_sizes!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary suitable for JSON serialization in run records."""
        return {
            "multiplier": self.multiplier,
            "derivation_percentile": self.derivation_percentile,
            "decay_significance_threshold": self.decay_significance_threshold,
            "materiality_delta_ms": self.materiality_delta_ms,
            "window_fractions": list(self.window_fractions),
            "segment_boundary_sizes": list(self.segment_boundary_sizes),
            "min_stratum_cell_size": self.min_stratum_cell_size,
            "max_tolerated_graph_timeout_rate": self.max_tolerated_graph_timeout_rate,
            "bootstrap_seed": self.bootstrap_seed,
            "slack_ms": self.slack_ms,
            "provenance": self.provenance,
        }


# Pre-committed decision inputs for Phase 06.3.3.
# Every decision input is locked before running measurement passes to ensure verdicts
# and proposed budgets are pure functions of data and committed policy.
COMMITTED_THRESHOLDS = DecisionThresholds(
    multiplier=1.5,
    derivation_percentile=0.95,
    decay_significance_threshold=0.05,
    materiality_delta_ms=500.0,
    window_fractions=(0.25, 0.25),
    segment_boundary_sizes=(30, 30),
    min_stratum_cell_size=10,
    max_tolerated_graph_timeout_rate=0.10,
    bootstrap_seed=42,
    slack_ms=500.0,
    provenance=(
        "Committed decision inputs per Phase 06.3.3: D-14 (multiplier=1.5, p95), "
        "D-18/D-19 (decay alpha=0.05, delta=500ms, window fractions 25%/25%), "
        "D-21 (segment boundary sizes 30/30), AI-SPEC bootstrap seed=42, "
        "min stratum cell size=10, max tolerated graph timeout rate=0.10, "
        "nesting invariant slack=500ms."
    ),
)

# Committed investigation floor for graph yield (06.3.4-STAGED-GATE.md §2).
GRAPH_YIELD_INVESTIGATION_FLOOR: float = 0.20

# 06.3.4.1 D-69/D-73: committed before paid drive 1 (AI-SPEC §5 #2/#4/#6).
CITATION_REJECTION_TRIPWIRE: float = 0.159
# 06.3.4.1 D-69/D-73: committed before paid drive 1 (AI-SPEC §5 #2/#4/#6).
CITATION_REJECTION_NULL_BASELINE: tuple[int, int] = (29, 42)
# 06.3.4.1 D-69/D-73: committed before paid drive 1 (AI-SPEC §5 #2/#4/#6).
SC2_TIMEOUT_DOMINANCE_RULE: str = "plurality_tie_is_dominant"
# 06.3.4.1 D-69/D-73: committed before paid drive 1 (AI-SPEC §5 #2/#4/#6).
FINAL_ANSWER_MISSING_REVIEW_RATE: float = 0.10

# 06.3.4.1 D-73: max(0.40, B_G + 0.10), ceil to 3 decimals; B_G = 37/90 (modal
# label 'yes') over the drawn non-null diagnostic sample in questions.diag.jsonl
# (eval/corpora/multihop_rag/, seed 42, all in G by construction); evaluated
# 2026-09-26; committed before paid drive 1. A miss triggers investigation
# (D-84), not suppression.
VECTOR_BASELINE_USABLE_FLOOR: float = 0.512

# 06.3.4.1 D-81/D-82/D-83: committed before paid drive 2 (AI-SPEC §5 #9/#11/#12).
# SC-4's Wilson clause: the 95% Wilson lower bound of the graph-presence headline
# must clear the 06.3.4 presence rate, 14/143 = 0.098 ("clearly above 9.8%").
GRAPH_PRESENCE_WILSON_LOWER_FLOOR: float = 0.098
# 06.3.4.1 D-81/D-82/D-83: committed before paid drive 2 (AI-SPEC §5 #9/#11/#12).
# SC-5's retrieval-composition floor: half the 0.20 yield floor (06.3.1 D-32).
GRAPH_COMPOSITION_CHANGE_FLOOR: float = 0.10
# 06.3.4.1 D-81/D-82/D-83: committed before paid drive 2 (AI-SPEC §5 #9/#11/#12).
# SC-5 PASS reading: n_pairs(V) >= 1 and either the composition change reaches
# GRAPH_COMPOSITION_CHANGE_FLOOR, or a paired delta in retrieval coverage@4 or
# `answer_usable` has a bootstrap CI that excludes 0 with n_pairs(V) >= 2.
# Direction is not part of the rule; a negative delta is reported (06.3.1 D-49).
SC5_VISIBILITY_RULE: str = "composition_floor_or_paired_ci_excludes_zero_n_ge_2"

# 06.3.4.1-32 (G-06.3.4.1-3a: CR-02 and WR-04), owner decision 2026-10-06. The unpark
# gates' coverage floor: a gate that scores a thin population MISSes instead of reading
# PASS. The value reuses `gate.py` STAGED_PAIRING_COVERAGE_FLOOR (06.3.1 D-44 as applied
# in 06.3.4, commit eb893ba1, 2026-09-09), fixed before any 06.3.4.1 drive data existed;
# it was not chosen by looking at any drive's coverage. It is applied at or above to
# n / |sample & G| (SC-3 and SC-4) and n / |sample & V| (SC-5), where the sample is the
# journal header corpus's questions: never to a corpus-wide G or V (398 / 291) and never
# to the journal-relative pairing_coverage. It governs gated drives whose journal
# header `created_at` follows its commit, so a re-read of drive 1, 1b or 2 under it is a
# labelled disclosure, not a re-adjudication, and their recorded gates-drive*.{md,json}
# are not rewritten (D-73).
UNPARK_GATE_COVERAGE_FLOOR: float = 0.80


@dataclass(frozen=True)
class MaterialDecayThresholds:
    """06.3.4.1 D-89: decay materiality relative to the node's own speed.

    Decay is present when either the significant slope, projected over
    `projection_horizon_records`, or the late-minus-early p95 delta reaches
    `materiality_threshold_ms(early_p95)`. Kept as a separate set so 06.3.3's
    `DecisionThresholds` (and the run records that serialize it) do not change shape.
    """

    base: DecisionThresholds
    projection_horizon_records: int
    relative_materiality_fraction: float
    materiality_floor_ms: float
    provenance: str

    def validate(self) -> None:
        """Assert the D-89 inputs are usable, then the base set's decay inputs."""
        if self.projection_horizon_records <= 0:
            raise ThresholdError(
                "D-89 requires a positive projection horizon, "
                f"got {self.projection_horizon_records!r}"
            )
        if not (0.0 < self.relative_materiality_fraction < 1.0):
            raise ThresholdError(
                "D-89 requires a relative materiality fraction in (0, 1), "
                f"got {self.relative_materiality_fraction!r}"
            )
        if self.materiality_floor_ms < 0:
            raise ThresholdError(
                "D-89 requires a non-negative materiality floor, "
                f"got {self.materiality_floor_ms!r}"
            )
        self.base.validate_for_decay()

    def materiality_threshold_ms(self, early_p95_ms: float) -> float:
        """The size a decay reading must reach: max(fraction x early p95, floor)."""
        return max(
            self.relative_materiality_fraction * early_p95_ms,
            self.materiality_floor_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dictionary for forensics records."""
        return {
            "projection_horizon_records": self.projection_horizon_records,
            "relative_materiality_fraction": self.relative_materiality_fraction,
            "materiality_floor_ms": self.materiality_floor_ms,
            "base": self.base.to_dict(),
            "provenance": self.provenance,
        }


# 06.3.4.1 D-89: committed before its first application beyond pass A (06.3.4.1-21).
COMMITTED_DECAY_THRESHOLDS_06341 = MaterialDecayThresholds(
    base=COMMITTED_THRESHOLDS,
    projection_horizon_records=658,
    relative_materiality_fraction=0.25,
    materiality_floor_ms=25.0,
    provenance=(
        "06.3.4.1 D-89 (user decision, 2026-09-28): amends D-64 for every decay and "
        "flatness reading in 06.3.4.1 (pass A re-gate, pass B, drive 1, drive 2). "
        "Decay is present when either the significant positive Theil-Sen slope "
        "projected over 658 records (the 06.3.4 drive's length) or the late-window p95 "
        "minus the early-window p95 reaches max(25% of the early-window p95, 25 ms); "
        "equality fires. Rationale: budgets are p95 x 1.5, i.e. 50% headroom, and "
        "decay is material once it would use half of that headroom. Base inputs "
        "(alpha 0.05, window fractions 25%/25%, p95, seed 42) are 06.3.3's "
        "COMMITTED_THRESHOLDS; its fixed 500 ms delta is not consulted. Censoring is "
        "unchanged: a censored or too-small set reads unavailable, never flat."
    ),
)


# 06.3.5 D-73: committed before the paid held-out drive (first paid request: the
# 06.3.5-14 rehearsal). Everything in this block lands in ONE commit; `run` refuses a
# `[split]` corpus unless that commit is an ancestor of a clean HEAD, and `score`
# refuses its report unless that commit predates the journal header's `created_at`.
# Nothing here is changed after data is seen (AI-SPEC 5 "Pre-registration block").


@dataclass(frozen=True)
class AblationPreRegistration:
    """06.3.5 D-111/D-121/D-122/D-123: the pre-registered inference of the ablation.

    Everything not named here is a secondary: reported with CIs, never called
    significant. Only a Holm rejection inside a family may be called significant.

    Attributes:
        primaries: The two primary dimensions; each is a 0/1 value per question.
        reference_arm: The arm every comparison is a delta against.
        comparison_arms: The arms compared with the reference arm.
        family: `per_primary` means one Holm family per primary, m = 3 each.
        family_alpha: Family-wise error rate of each family.
        test: The exact two-sided paired sign-flip test (exact McNemar).
        population: The complete-case population every paired value is read on.
        matching_rule: How a retrieved chunk is matched to gold, fixed before data.
        complete_case_floor: |P4| / |H_G| at or above; below it nothing is evaluable.
        bootstrap_b: Bootstrap resamples of the estimation-only CIs.
        bootstrap_seed: Seed of those CIs.
        provenance: Where the values come from.
    """

    primaries: tuple[str, ...]
    reference_arm: str
    comparison_arms: tuple[str, ...]
    family: str
    family_alpha: float
    test: str
    population: str
    matching_rule: str
    complete_case_floor: float
    bootstrap_b: int
    bootstrap_seed: int
    provenance: str


PREREGISTRATION_06_3_5 = AblationPreRegistration(
    primaries=("paper_hits_at_4", "answer_usable"),
    reference_arm="hybrid",
    comparison_arms=("dense-only", "bm25-only", "hybrid+graph"),
    family="per_primary",
    family_alpha=0.05,
    test="paired_sign_flip_exact_two_sided",
    population="P4: held-out G questions with ok(r) on all four arms",
    matching_rule="chunk_id_via_gold_chunks",
    complete_case_floor=0.80,
    bootstrap_b=10_000,
    bootstrap_seed=42,
    provenance=(
        "06.3.5 D-111 and the owner decisions of 2026-10-06, D-121 (answer_usable is "
        "read on P4), D-122 (the paper-metric headline excludes errored and partial "
        "records, with a script-faithful line beside it) and D-123 (two Holm families, "
        "one per primary, each at FWER 0.05; an exact two-sided paired sign-flip test; "
        "bootstrap CIs are estimation only). Across both primaries the family-wise "
        "error rate can reach 0.10 (Bonferroni bound), and the report states it. The "
        "0.80 complete-case floor is the 0.80 convention of gate.py "
        "STAGED_PAIRING_COVERAGE_FLOOR. Committed before the first paid request and "
        "never changed after data is seen."
    ),
)

# 06.3.5 D-114/D-119/D-73: committed before the paid held-out drive, so before the
# calibration worksheet exists. Applied separately to each judged dimension, to the QWK
# point estimate on the owner-scored slice, at or above; the 95% CI is disclosed, never
# decisive. Value: continuity with gate.py AGREEMENT_TARGET (0.70), inside Landis and
# Koch's "substantial" band (0.61-0.80) and above McHugh's 0.60 "inadequate" line.
# Those bands were proposed for unweighted kappa, so using them for QWK is a
# convention, not a derivation. At n = 20 the bootstrap CI on QWK is roughly +/-0.3 at
# its widest, so a judge whose long-run QWK sits at the floor is labelled calibrated
# close to a coin flip: "uncalibrated" means "not shown trustworthy", not "shown
# untrustworthy". gate.py AGREEMENT_TARGET and CALIBRATION_SIZE are not edited and gate
# nothing in 06.3.5.
JUDGE_QWK_TRUST_FLOOR: float = 0.70
# 06.3.5 D-113: fewer scored pairs than this (after judge-error attrition) reads
# "uncalibrated: slice attrition".
CALIBRATION_MIN_SCORED_PAIRS: int = 16
# 06.3.5 D-113: seed of the 20-item calibration slice draw (one random.Random stream).
CALIBRATION_DRAW_SEED: int = 42
# 06.3.5 D-112/D-86: judge-stage stop conditions, errors counted after the in-stage
# re-attempt. Halt when errors / calls exceeds the rate once at least the minimum
# number of calls has been made, or on this many consecutive errors (an outage or a
# bad key).
JUDGE_ERROR_RATE_TRIPWIRE: float = 0.05
JUDGE_ERROR_TRIPWIRE_MIN_CALLS: int = 50
JUDGE_CONSECUTIVE_ERROR_HALT: int = 5


# 06.3.6 D-137/D-167/D-171: the pre-registered selection rule of lever 2 (graph repair
# chosen by diagnosis). Committed before the 38-question diagnosis table exists, in ONE
# commit together with its predicate code (`graph_diagnosis.py`); the `table` command
# refuses unless that commit is an ancestor of a clean HEAD and the value is unchanged.
# Declarative content only: no class count appears anywhere, and no similarity
# threshold enters the rule.


@dataclass(frozen=True)
class GraphRepairRule:
    """06.3.6 D-137: how the GRAPH_UNAVAILABLE class split picks lever 2.

    Attributes:
        population: The records the table classifies, as a selector.
        expected_count: The population size; the table refuses any other size.
        classes: The four diagnosis classes.
        precedence: First-match order of the classes (D-171); the last is the residual.
        alias_predicate: The `alias_split` predicate (parameter-free, D-167).
        absent_predicate: The `absent` predicate.
        missing_edge_predicate: The `missing_edge` predicate.
        other_predicate: The `other` residual.
        plurality_rule: How the single-label counts select a lever.
        outcomes: The class-to-lever mapping, one `class -> lever` string each.
        provenance: Where the rule and its constants come from.
    """

    population: str
    expected_count: int
    classes: tuple[str, ...]
    precedence: tuple[str, ...]
    alias_predicate: str
    absent_predicate: str
    missing_edge_predicate: str
    other_predicate: str
    plurality_rule: str
    outcomes: tuple[str, ...]
    provenance: str


GRAPH_REPAIR_RULE_06_3_6 = GraphRepairRule(
    population=(
        "drive-2 records "
        "(eval/runs/2026-10-06-drive2-multihop_rag_diag/journal.jsonl) on arm label "
        "graph-on (legacy alias of hybrid+graph) carrying a notice with typed_code 10 "
        "(GRAPH_UNAVAILABLE)"
    ),
    expected_count=38,
    classes=("alias_split", "absent", "missing_edge", "other"),
    precedence=("alias_split", "absent", "missing_edge", "other"),
    alias_predicate=(
        "Name tokens are the normalised tokens of the engine's normalize_name "
        "(lower-case, non-alphanumerics including underscore separate tokens, a "
        "leading 'the' dropped when more words remain); two names are token-contained "
        "when one non-empty token set is a subset of the other (token, not substring). "
        "A mention is seeded when some seed's name tokens are token-contained with its "
        "tokens. alias_split holds when (a) two seeds a and b have no probe path "
        "through both, and an entity E, not a and not b, with the same entity_type as "
        "a, whose name tokens are token-contained with a's, whose source_chunk_ids "
        "include a gold chunk of the question, has an edge in either direction to b; "
        "or (b) a mention is unseeded, and an entity E whose name tokens are "
        "token-contained with the mention's, whose source_chunk_ids include a gold "
        "chunk of the question, has an edge in either direction to some seed. No "
        "similarity threshold is used."
    ),
    absent_predicate=(
        "Some mention has no entity anywhere in the entities table whose name tokens "
        "are token-contained with the mention's, AND no entity's source_chunk_ids "
        "intersects the gold chunk ids of the question."
    ),
    missing_edge_predicate=(
        "At least two distinct seeds, every mention seeded, alias_split false, the "
        "journal's graph_path_found false and graph_degree_capped_count equal to 0 "
        "(a field the journal did not record does not satisfy it)."
    ),
    other_predicate=(
        "The residual: a question for which none of the three predicates above holds "
        "(no mention extracted, hubs capped by DEGREE_CAP, pairs lost to the seed "
        "limit, and everything else)."
    ),
    plurality_rule=(
        "Single-label counts, the label being the first class in precedence order "
        "whose predicate holds. Strict plurality of alias_split selects "
        "entity_resolution; strict plurality of absent selects none; a plurality of "
        "missing_edge or of other, or any tie for the top count, selects "
        "graph_list_precision."
    ),
    outcomes=(
        "alias_split -> entity_resolution",
        "missing_edge -> graph_list_precision",
        "other -> graph_list_precision",
        "absent -> none",
        "any tie -> graph_list_precision",
    ),
    provenance=(
        "06.3.6 D-137 (the rule, committed before the table is regenerated and "
        "applied mechanically), D-167 (the alias_split predicate is parameter-free: "
        "token containment of normalised names with the same entity_type; it can "
        "under-detect vector-only aliases, which biases the plurality against "
        "selecting entity resolution, and the table and the run of record say so) and "
        "D-171 (first-match precedence alias_split, absent, missing_edge, other, "
        "chosen blind by the owner before any table existed; its effect is that a "
        "question with a visible alias a merge could fix counts toward entity "
        "resolution even if an unnamed mention may still block it, and the "
        "multi-membership matrix published beside the counts makes that visible). "
        "Never changed after the table exists; a later predicate fix is a new "
        "disclosed commit."
    ),
)


# 06.3.6 D-150/D-148/D-151/D-160/D-73: the classes the lever pre-registration is written
# in. Definitions only. The assignment of an instance, with every number a decision
# reads inside it, lands in the one D-154 freeze commit (D-73 compares that assignment's
# AST, so a loose constant beside it would not be protected); nothing here names it.


@dataclass(frozen=True)
class FamilySpec:
    """06.3.6 D-150: one Holm family, with one primary, its own arms and its own FWER.

    Attributes:
        primary: The family's primary dimension (`answer_usable` or `paper_hits_at_4`).
        role: `decisional` (may make a default) or `supporting` (retrieval claim only).
        arms: The arms compared with the reference arm; `m = len(arms)`, fixed before
            data and never changed after it.
        alpha: Family-wise error rate under Holm step-down.
    """

    primary: str
    role: str
    arms: tuple[str, ...]
    alpha: float


@dataclass(frozen=True)
class LeverPreRegistration:
    """06.3.6: the pre-registered inference, guards, gate floor and tripwire.

    Everything not named here is a secondary: reported with CIs, never called
    significant. Only a Holm rejection inside a family may be called significant.

    Attributes:
        reference_arm: The arm every comparison is a delta against.
        families: The Holm families, each with its own primary and arm set.
        descriptive_arms: Arms reported with CIs and never tested.
        test: The exact two-sided paired sign-flip test (exact McNemar).
        non_evaluable_rule: How a comparison below the coverage floor enters its family.
        population: How each comparison's population is formed.
        complete_case_floor: |P_X| / |H_G| at or above, per comparison; below it the
            comparison is not evaluable.
        matching_rule: How a retrieved chunk is matched to gold, fixed before data.
        bootstrap_b: Bootstrap resamples of the estimation-only CIs.
        bootstrap_seed: Seed of those CIs.
        null_guard_arms: The arms the null-abstention guard can veto (D-148).
        null_guard_predicate: The abstention predicate the guard reads.
        null_guard_margin: The guard fails when the abstention increase over the
            reference exceeds this share of the null pairs.
        null_guard_min_pair_fraction: The fraction of the null questions that must be
            paired for the guard to be evaluable; below it the guard fails closed.
        answer_mix_strata: The strata of the reported-only answer-mix guard.
        sc2_timeout_rate_floor: D-151: a dominant timeout class fails SC-2 only when
            timeouts / records in the reading reach this rate (per arm and pooled).
        rerank_degrade_tripwire_rate: O10: the drive halts when rerank degrades / rerank
            attempts exceeds this rate.
        rerank_degrade_tripwire_min_calls: O10: rerank attempts needed before the rate
            is evaluated.
        rerank_consecutive_degrade_halt: O10: the drive halts at this many consecutive
            rerank degrades; the preflight applies it to its pooled canary count.
        default_rule: When a lever may become a default.
        provenance: Where the values come from.
    """

    reference_arm: str
    families: tuple[FamilySpec, ...]
    descriptive_arms: tuple[str, ...]
    test: str
    non_evaluable_rule: str
    population: str
    complete_case_floor: float
    matching_rule: str
    bootstrap_b: int
    bootstrap_seed: int
    null_guard_arms: tuple[str, ...]
    null_guard_predicate: str
    null_guard_margin: float
    null_guard_min_pair_fraction: float
    answer_mix_strata: tuple[str, ...]
    sc2_timeout_rate_floor: float
    rerank_degrade_tripwire_rate: float
    rerank_degrade_tripwire_min_calls: int
    rerank_consecutive_degrade_halt: int
    default_rule: str
    provenance: str



# 06.3.6 D-154 freeze (2026-10-10): the ONE lever pre-registration. It lands in the single
# freeze commit that also holds every frozen lever parameter (prompt sentences, rerank and
# retrieve budgets, the graph-v2 precision variant, the unreported rerank-call cost ceiling,
# the dev ledger's final entry and the rehearsal and held-out corpus configs), before the
# rehearsal, which is the first paid held-out-side request. Every number a decision reads is
# INSIDE this assignment: the D-73 gate compares this assignment's AST only (gitcheck.py), so
# a loose constant beside it would not be protected. A corpus selects it through
# `[preregistration] token`, never through the 06.3.5 module constant. Nothing here changes
# after data is seen. Branch B of D-137 (graph_list_precision) built graph-v2, so the shape
# is the seven-arm one: m = 4 for answer_usable and m = 2 for paper_hits_at_4.
PREREGISTRATION_06_3_6 = LeverPreRegistration(
    reference_arm="hybrid",
    families=(
        FamilySpec(
            primary="answer_usable",
            role="decisional",
            arms=(
                "hybrid+rerank",
                "hybrid+graph-v2",
                "hybrid+metadata",
                "hybrid+answer-format",
            ),
            alpha=0.05,
        ),
        FamilySpec(
            primary="paper_hits_at_4",
            role="supporting",
            arms=("hybrid+rerank", "hybrid+graph-v2"),
            alpha=0.05,
        ),
    ),
    descriptive_arms=("hybrid+all", "hybrid+graph"),
    test="paired_sign_flip_exact_two_sided",
    non_evaluable_rule="p=1_m_unchanged",
    population="pairwise_per_comparison",
    complete_case_floor=0.80,
    matching_rule="chunk_id_via_gold_chunks",
    bootstrap_b=10_000,
    bootstrap_seed=42,
    null_guard_arms=("hybrid+metadata", "hybrid+answer-format"),
    null_guard_predicate="metrics.is_abstention",
    null_guard_margin=0.10,
    null_guard_min_pair_fraction=0.80,
    answer_mix_strata=("comparison_query", "binary_gold"),
    sc2_timeout_rate_floor=0.025,
    rerank_degrade_tripwire_rate=0.20,
    rerank_degrade_tripwire_min_calls=50,
    rerank_consecutive_degrade_halt=5,
    default_rule=(
        "default(X) iff X is in the decisional family; the run passed the post-drive "
        "provenance block; SC-1 and SC-2 (with sc2_timeout_rate_floor) read PASS on "
        "hybrid and on X; |P_X| / |H_G| >= complete_case_floor; Holm rejects X at FWER "
        "alpha with m fixed; delta(X) > 0; and, if X is in null_guard_arms, the null "
        "guard is evaluable and passes. If only the SC-1/SC-2 condition fails after "
        "D-110, X's default is an owner disposition, disclosed, never mechanical"
    ),
    provenance=(
        "06.3.6 D-150 (two Holm families with per-family arms; the paper Hits@4 family "
        "supports a retrieval claim only), D-161 (population pairwise per comparison "
        "and the 0.80 coverage floor, owner decision 2026-10-09), D-148 and D-162 (null "
        "guard: count rule, margin 0.10, at least 0.80 of the 43 null pairs, fail "
        "closed), D-163 (guard arms hybrid+metadata and hybrid+answer-format; "
        "Yes-share disclosure reported only), D-164 (SC-2 timeout-rate floor "
        "1/40 = (1 - 0.95) x 1/2 from COMMITTED_THRESHOLDS and "
        "COMMITTED_DECAY_THRESHOLDS_06341), D-174 (O10 rerank degrade tripwire: rate "
        "0.20 after 50 attempts, or 5 consecutive degrades), D-177 (O16 gate "
        "precondition of a default), D-123 (exact paired sign-flip test), D-73, D-129 "
        "(no held-out number motivates any value) and D-154 (frozen with every lever "
        "parameter in one commit). The arm set follows the committed D-137 selection "
        "graph_list_precision (commit 81f1b414), which built graph-v2: m = 4 and m = 2. "
        "Across both families the family-wise error rate can reach 0.10 (Bonferroni "
        "over two families); defaults read only the decisional family (at most 0.05), "
        "and the guards can only veto a rejection. Frozen on 2026-10-10, before the "
        "held-out cap checkpoint and the rehearsal, and never changed after data is "
        "seen."
    ),
)
