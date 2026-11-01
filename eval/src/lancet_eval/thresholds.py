"""Decision thresholds and inputs committed before running measurement pass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lancet_eval.arms import ExternalPipeline
from lancet_eval.reader_request import (
    ReaderDeclaration,
    ReaderPrice,
)


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
        null_guard_margin: The guard fails when the net abstention drop against the
            reference exceeds this share of the null pairs. The drop counts the null
            pairs where the reference abstains and the arm does not, minus the reverse
            (``evaluate_null_guard``: ``b - c``), so a larger value is a worse arm
            (06.4-03, review B-IN-07).
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


@dataclass(frozen=True)
class StagePreRegistration(LeverPreRegistration):
    """v1.1 (D-253): a stage's pre-registration, which may list external arms.

    Its arm labels may be external (D-247) or store-prefixed (D-251). Each stage writes
    its own constant of this type on its own branch; none is defined here.

    Its arm labels may also be reader arms (D-257, ``<arm>@<reader>``).

    Attributes:
        external_pipelines: ``(arm label, arms.ExternalPipeline)`` pairs, one per
            external arm; ``preregistration.external_pipelines_of`` reads them.
        readers: ``(reader name, reader_request.ReaderDeclaration)`` pairs, one per
            reader its reader arms name (slug, target, thinking, sync list price);
            ``preregistration.readers_of`` reads them.
    """

    external_pipelines: tuple[tuple[str, ExternalPipeline], ...] = ()
    readers: tuple[tuple[str, ReaderDeclaration], ...] = ()


#: D-274: the test of a replay stage with more than one replicate: the exact two-sided
#: sign-flip permutation on the per-question mean differences (stats.
#: exact_signflip_p_integer), with a paired t-test beside it as a cross-check.
REPLICATE_TEST = "paired_sign_flip_permutation_exact_two_sided"


@dataclass(frozen=True, kw_only=True)
class ReplayStagePreRegistration(StagePreRegistration):
    """v1.1 S2 (D-254, D-257): a stage that replays one earlier arm to Claude readers.

    Its reference arm is the carried arm, and every other arm is that arm under a
    reader (``<arm>@<reader>``); a constant that names any other base arm is refused
    when it is built. ``replay-init`` reads ``replay_source_arm`` to refuse carrying an
    arm the pre-registration did not fix (#109).

    The S2 constant of this type is not defined here yet. Its draft is the code block
    in experiments/v1.1/EXPERIMENT-S2.md, and RUN-S2.md has the runner add it in one
    commit, once S1's winner and the readers' targets are known. D-73 dates a constant
    by the first commit whose diff adds or removes its name anywhere in this file (`git
    log -S`), so that name appears in this file only from that commit on, comments
    included.

    Attributes:
        replay_source_arm: The canonical label of the S1 arm S2 replays (S1's winner,
            written in EXPERIMENT-S1.md › Result).
        replicates: D-274: how many independent answers every arm gives each question
            (K). Above 1, a question's score is the mean of its K answers, and the test
            must be ``REPLICATE_TEST``: the exact sign-flip permutation on the
            per-question mean differences.
        reference_price: D-277: the sync price, USD per million tokens, of the
            carried deepseek reader, at which its cost per answered question (D-257)
            and its replicates' spend are read. None reads the engine's list price
            (``measure.GENERATION_LIST_*``), as before D-277.
    """

    replay_source_arm: str
    replicates: int = 1
    reference_price: ReaderPrice | None = None

    def __post_init__(self) -> None:
        if self.replicates < 1:
            raise ThresholdError(
                f"replicates must be at least 1, got {self.replicates}"
            )
        if self.replicates > 1 and self.test != REPLICATE_TEST:
            raise ThresholdError(
                f"{self.replicates} replicates need test {REPLICATE_TEST!r} (D-274), "
                f"not {self.test!r}"
            )
        source = self.replay_source_arm
        labels = (
            self.reference_arm,
            *(a for family in self.families for a in family.arms),
            *self.descriptive_arms,
            *self.null_guard_arms,
        )
        stray = [a for a in labels if a.partition("@")[0] != source]
        if self.reference_arm != source or stray:
            raise ThresholdError(
                f"a replay stage's arms are replay_source_arm {source!r} and its "
                f"reader arms; got reference {self.reference_arm!r} and {stray}"
            )


#: The transports a writer's extraction may run on.
WRITER_TRANSPORTS = ("openrouter_batch",)
_LOWER_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True, kw_only=True)
class WriterPreRegistration:
    """v1.1 S3 (#145): what the writer extraction fixes, frozen before any spend (D-73).

    S3 compares graph writers (D-235). Each writer extracts every passage of the pinned
    2Wiki corpus once; the store builds, the reader runs and S3's analysis
    pre-registration (arms, K, Holm family, metrics) come later, in their own constant.
    A writer added after a constant reaches main gets its own constant of this type
    in its own commit, so a frozen one never changes.

    Attributes:
        dataset: The Hugging Face dataset the passages come from.
        dataset_revision: Its git revision (``twowiki.REVISION``).
        passages_file: The passages file at that revision.
        passages_sha256: sha256 of that file's bytes.
        passage_count: How many passages, so how many requests per writer.
        unit: What one request extracts.
        extraction_source: The repo file whose request body every writer starts from.
        extraction_source_blob: That file's git blob ID at the freeze, so a later edit
            to the prompt or schema is caught.
        request_rule: How each writer's request is built from that body.
        writers: ``(writer name, reader_request.ReaderDeclaration)`` pairs: slug,
            target, thinking, effort and sync list price per writer.
        transports: ``(writer name, transport)`` pairs, one per writer, out of
            ``WRITER_TRANSPORTS``.
        report_rule: What is stored and reported per writer.
        provenance: Where the values come from.
    """

    dataset: str
    dataset_revision: str
    passages_file: str
    passages_sha256: str
    passage_count: int
    unit: str
    extraction_source: str
    extraction_source_blob: str
    request_rule: str
    writers: tuple[tuple[str, ReaderDeclaration], ...]
    transports: tuple[tuple[str, str], ...]
    report_rule: str
    provenance: str

    def __post_init__(self) -> None:
        names = [name for name, _ in self.writers]
        if not names or len(set(names)) != len(names):
            raise ThresholdError(f"writers must be non-empty and unique, got {names}")
        transports = dict(self.transports)
        if sorted(transports) != sorted(names) or len(self.transports) != len(names):
            raise ThresholdError(
                f"transports name {sorted(transports)}, writers {sorted(names)}"
            )
        bad = {n: t for n, t in transports.items() if t not in WRITER_TRANSPORTS}
        if bad:
            raise ThresholdError(f"unknown transports {bad}; known {WRITER_TRANSPORTS}")
        between = [n for n, d in self.writers if d.thinking == "between_tools"]
        if between:
            raise ThresholdError(
                f"{between}: the Batch API refuses between_tools thinking (D-280)"
            )
        for field, value, size in (
            ("dataset_revision", self.dataset_revision, 40),
            ("passages_sha256", self.passages_sha256, 64),
            ("extraction_source_blob", self.extraction_source_blob, 40),
        ):
            if len(value) != size or not set(value) <= _LOWER_HEX:
                raise ThresholdError(f"{field} must be {size} lower-case hex digits")
        if self.passage_count < 1:
            raise ThresholdError(
                f"passage_count must be positive, not {self.passage_count}"
            )


# v1.1 S0 (D-238, D-252, D-261, D-262; experiments/v1.1/EXPERIMENT-S0.md): Lancet's
# shipped default against the MultiHop-RAG paper's LlamaIndex pipeline, read once on the
# held-out split (the first of D-237's two reads). Every number a reading uses is inside
# this assignment, which the D-73 check compares by AST; nothing here changes after data
# is seen.
PREREGISTRATION_S0 = StagePreRegistration(
    reference_arm="hybrid+rerank+metadata",
    families=(
        FamilySpec(
            primary="answer_usable",
            role="decisional",
            arms=("llamaindex",),
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
    null_guard_arms=("llamaindex",),
    null_guard_predicate="metrics.is_abstention",
    null_guard_margin=0.10,
    null_guard_min_pair_fraction=0.80,
    answer_mix_strata=("comparison_query", "binary_gold"),
    sc2_timeout_rate_floor=0.025,
    rerank_degrade_tripwire_rate=0.20,
    rerank_degrade_tripwire_min_calls=50,
    rerank_consecutive_degrade_halt=5,
    default_rule=(
        "S0 changes no default; it is the published starting point and does not gate "
        "S1 (D-252). One Holm family, m = 1: answer_usable of llamaindex against "
        "hybrid+rerank+metadata on the held-out G population, exact paired sign-flip, "
        "alpha 0.05. If the comparison is evaluable (|P| / |H_G| >= "
        "complete_case_floor) and Holm rejects, the arm with the higher answer_usable "
        "leads, but only if the null guard read in its direction passes (D-261): for "
        "llamaindex the guard as computed (net abstention drop b - c against the "
        "reference); for hybrid+rerank+metadata the same null pairs with b and c "
        "swapped (c - b). Each direction passes iff at least ceil(0.80 x |H_N|) null "
        "pairs exist and the net drop / pairs <= 0.10. A leader whose guard fails or "
        "is not evaluable is reported as a difference with a failed guard, and no lead "
        "is claimed. Without a rejection the reading is 'no significant difference'. "
        "Evidence Hits@4, context tokens and latency are supporting and never tested; "
        "chunk-ID Hits@4 is a Lancet-only secondary (D-250)"
    ),
    provenance=(
        "v1.1 S0. D-238 (two arms, one each), D-239 and D-252 (Holm m = 1, exact "
        "paired sign-flip, null guard on both arms), D-261 (the guard read in both "
        "directions, the leader's direction vetoes; owner 2026-10-30: "
        "'雙向讀，勝方須過'), D-262 (every number reused from PREREGISTRATION_06_3_6: "
        "alpha 0.05, guard margin 0.10 and pair fraction 0.80, complete-case floor "
        "0.80, bootstrap 10,000 seed 42, SC-2 timeout floor 0.025, rerank tripwire "
        "0.20 after 50 attempts or 5 consecutive; owner 2026-10-30: '全部沿用 v1.0'), "
        "D-247 and D-248 (the external arm and its pipeline), D-259 (the external "
        "reader runs with evidence_metadata only, which matches the shipped default's "
        "reader-side levers; rerank is retrieval-side), D-237 (this is held-out read 1 "
        "of 2; Confirm is read 2). Written 2026-10-30, before any S0 data."
    ),
    external_pipelines=(
        (
            "llamaindex",
            ExternalPipeline(
                framework="llama-index-core",
                framework_version="0.14.25",
                chunk_size=256,
                chunk_overlap=25,
                dense_top_k=20,
                rerank_model="voyageai/rerank-2.5-lite",
                keep=8,
            ),
        ),
    ),
)


# v1.1 S1 (D-241, D-242, D-251, D-252, D-262 to D-264;
# experiments/v1.1/EXPERIMENT-S1.md): paragraph fragments (the v1.0 `small` store)
# against merged ~256-token chunks (the `merged` store), each with the graph off and on,
# read on the levers-dev pool of 100 (90 G, 10 null). Direction-finding: the harness
# computes the paired differences, p-values and null guards, and the choice is applied
# by hand in EXPERIMENT-S1.md (D-252). The family is `decisional` only because the lever
# comparison needs one; its default-decision rows are not read. This constant gives the
# chunking reading and the small-store graph reading (both against small graph-off);
# PREREGISTRATION_S1_MERGED_GRAPH gives the merged-store graph reading of the same
# journal.
PREREGISTRATION_S1 = StagePreRegistration(
    reference_arm="small/hybrid+rerank+metadata",
    families=(
        FamilySpec(
            primary="answer_usable",
            role="decisional",
            arms=(
                "merged/hybrid+rerank+metadata",
                "small/hybrid+graph+rerank+metadata",
            ),
            alpha=0.05,
        ),
    ),
    descriptive_arms=("merged/hybrid+graph+rerank+metadata",),
    test="paired_sign_flip_exact_two_sided",
    non_evaluable_rule="p=1_m_unchanged",
    population="pairwise_per_comparison",
    complete_case_floor=0.80,
    matching_rule="chunk_id_via_gold_chunks",
    bootstrap_b=10_000,
    bootstrap_seed=42,
    null_guard_arms=(
        "merged/hybrid+rerank+metadata",
        "small/hybrid+graph+rerank+metadata",
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
        "Applied by hand in EXPERIMENT-S1.md, never by code (D-252). Chunking: adopt "
        "merged iff the paired answer_usable delta of merged/hybrid+rerank+metadata "
        "against small/hybrid+rerank+metadata on G is above 0 and its null guard "
        "passes (D-264); otherwise keep small. Graph, on the chosen store only "
        "(D-263): the graph joins iff the paired answer_usable delta of that store's "
        "graph-on arm against its graph-off arm is at least +0.05 and that "
        "comparison's null guard passes (D-264). Small store: the "
        "small/hybrid+graph+rerank+metadata row of this constant. Merged store: the "
        "merged/hybrid+graph+rerank+metadata row of PREREGISTRATION_S1_MERGED_GRAPH. A "
        "guard that fails or is not evaluable vetoes the choice it guards. p-values "
        "are reported, not used. Evidence Hits@4 is supporting; chunk-ID Hits@4 is not "
        "read for S1 (D-250, the gold is not re-mapped to merged chunks)"
    ),
    provenance=(
        "v1.1 S1. D-241 and D-242 (one 256-token o200k target, merge rule), D-251 (the "
        "merged store and store-prefixed arms), D-252 (direction-finding rule: merged "
        "if the delta is above 0 with the null guard; graph if at least +5 points; "
        "p-values reported, not used), D-259 (the levers-dev question set, the D-237 "
        "dev pool of 100: 90 G, 10 null), D-262 (every number reused from "
        "PREREGISTRATION_06_3_6; owner 2026-10-30: '全部沿用 v1.0'), D-263 (the graph "
        "rule on the chosen store; owner 2026-10-30: '在選中的 store 上套用'), D-264 "
        "(null guard margin 0.10 and pair fraction 0.80 on the 10 dev nulls, vetoing "
        "both choices; owner 2026-10-30: '沿用 0.10/0.80，兩個選擇都否決'). Written "
        "2026-10-30, before any S1 data."
    ),
)


# v1.1 S1, merged-store graph reading (D-263): PREREGISTRATION_S1 with merged graph-off
# as the reference, so the lever comparison pairs merged graph-on against it. Every
# number is PREREGISTRATION_S1's; only the arm roles differ (a test pins this). It is
# read with `build_lever_comparison(run, prereg=PREREGISTRATION_S1_MERGED_GRAPH)` over
# the S1 run (experiments/v1.1/RUN-S0-S1.md); the corpus token stays PREREGISTRATION_S1,
# so the D-73 check still runs on it.
PREREGISTRATION_S1_MERGED_GRAPH = StagePreRegistration(
    reference_arm="merged/hybrid+rerank+metadata",
    families=(
        FamilySpec(
            primary="answer_usable",
            role="decisional",
            arms=("merged/hybrid+graph+rerank+metadata",),
            alpha=0.05,
        ),
    ),
    descriptive_arms=(
        "small/hybrid+rerank+metadata",
        "small/hybrid+graph+rerank+metadata",
    ),
    test="paired_sign_flip_exact_two_sided",
    non_evaluable_rule="p=1_m_unchanged",
    population="pairwise_per_comparison",
    complete_case_floor=0.80,
    matching_rule="chunk_id_via_gold_chunks",
    bootstrap_b=10_000,
    bootstrap_seed=42,
    null_guard_arms=("merged/hybrid+graph+rerank+metadata",),
    null_guard_predicate="metrics.is_abstention",
    null_guard_margin=0.10,
    null_guard_min_pair_fraction=0.80,
    answer_mix_strata=("comparison_query", "binary_gold"),
    sc2_timeout_rate_floor=0.025,
    rerank_degrade_tripwire_rate=0.20,
    rerank_degrade_tripwire_min_calls=50,
    rerank_consecutive_degrade_halt=5,
    default_rule=(
        "The merged-store half of PREREGISTRATION_S1's graph rule (D-263): read only "
        "if S1 adopts merged. The graph joins iff the paired answer_usable delta of "
        "merged/hybrid+graph+rerank+metadata against merged/hybrid+rerank+metadata on "
        "G is at least +0.05 and its null guard passes (D-264). Applied by hand in "
        "EXPERIMENT-S1.md"
    ),
    provenance=(
        "v1.1 S1, D-252 and D-263: the merged-store graph comparison as its own "
        "reference pairing, because the lever comparison pairs every family arm with "
        "the constant's reference. Numbers as PREREGISTRATION_S1 (D-262, D-264). "
        "Written 2026-10-30, before any S1 data."
    ),
)


# v1.1 S2 (D-252, D-254 to D-260, D-265; experiments/v1.1/EXPERIMENT-S2.md): S1's
# winning arm, read by deepseek in S1 and carried into S2 (D-254, Q9), against the same
# packed prompts read by Haiku 5.5 (Claude batch) and Sonnet 5.5 (sync, D-280), on the
# levers-dev pool of 100 (90 G, 10 null), 5 answers per question and arm (D-274: the
# carried answer is deepseek's first). Direction-finding: the harness computes the
# paired differences, null guards and cost per answered question, and the choice is
# applied by hand in EXPERIMENT-S2.md (D-252). Added in one commit by RUN-S2.md step 4,
# after the pilot and before the run of record's replay-init (D-73).
PREREGISTRATION_S2 = ReplayStagePreRegistration(
    replay_source_arm="small/hybrid+rerank+metadata",
    reference_arm="small/hybrid+rerank+metadata",
    families=(
        FamilySpec(
            primary="answer_usable",
            role="decisional",
            arms=(
                "small/hybrid+rerank+metadata@haiku-5.5",
                "small/hybrid+rerank+metadata@sonnet-5.5",
            ),
            alpha=0.05,
        ),
    ),
    descriptive_arms=("small/hybrid+rerank+metadata@opus-5.5",),
    test="paired_sign_flip_permutation_exact_two_sided",
    non_evaluable_rule="p=1_m_unchanged",
    population="pairwise_per_comparison",
    complete_case_floor=0.80,
    matching_rule="chunk_id_via_gold_chunks",
    bootstrap_b=10_000,
    bootstrap_seed=42,
    null_guard_arms=(
        "small/hybrid+rerank+metadata@haiku-5.5",
        "small/hybrid+rerank+metadata@sonnet-5.5",
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
        "0.0448/0.30, as D-271 and config.toml record it; owner: "
        "'改用 Wafer 實際價 (Recommended)'), D-278 (deepseek's replicates through "
        "OpenRouter's sync API with D-271's full pin; owner: '改走同步 API "
        "(Recommended)'). Prices, USD per MTok: Haiku 5.5 0.10/0.50 "
        "and Sonnet 5.5 2/10 (decisions 2026-10-30); Opus 5.5 4/20, read "
        "2026-10-31 from https://platform.claude.com/docs/en/about-claude/pricing "
        "(D-269). Sonnet 5.5 is read over OpenRouter's sync API with "
        "between_tools, BYOK, since the Batch API refuses between_tools; D-260's "
        "native fallback is dropped (D-280; owner: '同步＋between_tools，pilot 驗證 "
        "(Recommended)'). Written 2026-10-31, before any S2 data."
    ),
    replicates=5,
    reference_price=ReaderPrice(input_per_mtok=0.0448, output_per_mtok=0.30),
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


# #143, exploratory (experiments/v1.1/EXPLORE-S2-MERGED.md): PREREGISTRATION_S2 moved to
# S1's merged graph-off arm at K = 2, its replicate 1 carried from the S1 run of record.
# Readers, transports, thinking, prices and every number are S2's, so each reader
# compares with S2's small-store run directly (a test pins this). It decides nothing and
# changes no S2 or S3 decision. Added in one commit before the run's replay-init (D-73).
PREREGISTRATION_S2X = ReplayStagePreRegistration(
    replay_source_arm="merged/hybrid+rerank+metadata",
    reference_arm="merged/hybrid+rerank+metadata",
    families=(
        FamilySpec(
            primary="answer_usable",
            role="decisional",
            arms=(
                "merged/hybrid+rerank+metadata@haiku-5.5",
                "merged/hybrid+rerank+metadata@sonnet-5.5",
            ),
            alpha=0.05,
        ),
    ),
    descriptive_arms=("merged/hybrid+rerank+metadata@opus-5.5",),
    test="paired_sign_flip_permutation_exact_two_sided",
    non_evaluable_rule="p=1_m_unchanged",
    population="pairwise_per_comparison",
    complete_case_floor=0.80,
    matching_rule="chunk_id_via_gold_chunks",
    bootstrap_b=10_000,
    bootstrap_seed=42,
    null_guard_arms=(
        "merged/hybrid+rerank+metadata@haiku-5.5",
        "merged/hybrid+rerank+metadata@sonnet-5.5",
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
        "Exploratory: this run decides nothing and changes no S2 or S3 decision; S2's "
        "reader choice stands (EXPERIMENT-S2.md). The family is decisional only "
        "because the lever comparison needs one. Read in EXPLORE-S2-MERGED.md, by "
        "hand: per reader, answer_usable and the abstention rate on the 90 G "
        "questions, split by whether every gold fact is in the context "
        "(metrics.gold_contained, evidence_split) and by yes/no against open "
        "questions, beside S2's small-store run; the paired deltas against "
        "deepseek and the null guards as the lever comparison prints them; "
        "reasoning_tokens; spend. Every arm answers "
        "each question 2 times, and every test is the exact sign-flip permutation on "
        "the per-question mean differences (D-274). The written predictions are "
        "checked, never tuned after the data"
    ),
    provenance=(
        "#143, owner 2026-11-01: '好，執行三個 reader K=2 跟補跑deepseek' (the three "
        "Claude readers at K=2, plus deepseek's replicate 2). Source: S1's run of "
        "record eval/runs/2026-10-31-s1-multihop_rag_s1_dev, arm "
        "merged/hybrid+rerank+metadata, replicate 1 carried (D-254). Everything else "
        "is PREREGISTRATION_S2's: readers and thinking (D-255, D-260, D-265, D-267, "
        "D-280), prices (D-269, D-277), deepseek's pinned sync replicates (D-278), "
        "the replicate test (D-274), the null guard numbers (D-264, D-269). Dev only "
        "(D-237), no held-out read. Written 2026-11-01, before any data of this run."
    ),
    replicates=2,
    reference_price=ReaderPrice(input_per_mtok=0.0448, output_per_mtok=0.30),
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


# v1.1 S3 writers (#145, D-73): what the 2Wiki writer extraction fixes, frozen before
# any extraction is paid for. It names the pinned passages, the extraction unit, the
# engine's request body and each writer's model and thinking; S3's analysis
# pre-registration (arms, K, Holm family, metrics) is a later constant. A writer added
# after this freeze gets its own WriterPreRegistration constant in its own commit.
PREREGISTRATION_S3_WRITERS = WriterPreRegistration(
    dataset="osunlp/HippoRAG_2",
    dataset_revision="5ec05b38deecc3318bb432c69865959c56058990",
    passages_file="2wikimultihopqa_corpus.json",
    passages_sha256="9d6e352952aafb18dab22bf8195039461321a44a949df902ae83bce134ad238a",
    passage_count=6_119,
    unit=(
        "One request per passage, in file order, taken as given: the passage's title "
        "and text joined by one newline (twowiki.passage_unit, HippoRAG 2's own form; "
        "about 37% of the texts do not name their title). No chunking and no length "
        "floor: the 41 units under the engine's 40-byte MIN_CHUNK_CONTENT_LENGTH are "
        "extracted too, so every writer gets the same 6,119 requests"
    ),
    extraction_source="engine/src/graph/extraction.rs",
    extraction_source_blob="54c926a6c07b4483eb394cb5ff4bf58dcd158dfb",
    request_rule=(
        "Every writer starts from the body OpenRouterExtractionGenerator::"
        "build_request_payload builds for the unit: its system message, its user "
        "message ('Extract entities and relationships:' and the unit), the strict "
        "json_schema 'knowledge_graph_extraction' and max_completion_tokens 16,384 "
        "(D-272). deepseek gets that body as the engine sends it: the model and "
        "provider pin config.toml holds (D-271) and reasoning {effort: none}. Each "
        "Claude writer gets it rewritten as S2's readers are (D-255, reader_request."
        "rewrite_pack_body): its slug, provider {only: [anthropic], allow_fallbacks: "
        "false} (BYOK, D-265), temperature and top_p removed, and reasoning per its "
        "thinking. The message text is the same for every writer; no few-shot "
        "example and no prompt caching (D-256)"
    ),
    writers=(
        (
            "deepseek",
            ReaderDeclaration(
                slug="deepseek/deepseek-v4-flash-0731",
                target="openrouter",
                thinking="off",
                price=ReaderPrice(input_per_mtok=0.0448, output_per_mtok=0.30),
            ),
        ),
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
                thinking="on",
                effort="low",
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
    transports=(
        ("deepseek", "openrouter_batch"),
        ("haiku-5.5", "openrouter_batch"),
        ("sonnet-5.5", "openrouter_batch"),
        ("opus-5.5", "openrouter_batch"),
    ),
    report_rule=(
        "Per writer and passage: the raw output and its usage (prompt, completion and "
        "reasoning tokens, cost, provider, is_byok) are stored; no store is built in "
        "this step. Per writer: its thinking setting and measured reasoning_tokens "
        "(no zero requirement), tokens and spend, and the failed, expired and "
        "schema-invalid outputs. A Claude writer's request must run BYOK (is_byok "
        "true, provider Anthropic). Every paid batch is submitted only after the "
        "owner's yes on its printed estimate (D-258)"
    ),
    provenance=(
        "#145, owner 2026-11-01: 'Start S3 prep'. Writers: D-235 (deepseek, Haiku 5.5, "
        "Sonnet 5.5), and Opus 5.5 added by the owner before this freeze merged "
        "(2026-11-01, relayed by the coordinator: '全部接受，同意 force-push'). "
        "Thinking: the lowest setting each model supports on the Batch API, "
        "one rule for every writer, each setting and its measured reasoning_tokens "
        "reported (owner 2026-11-01, relayed from a side session and confirmed to the "
        "coordinator: '是說haiku也不用一定要開low effort吧？…就直接變成off, off, low, "
        "low這樣？', 'Confirm'): deepseek off, Haiku 5.5 off, Sonnet 5.5 and Opus 5.5 "
        "on at effort low, all on the Batch API. Sync list prices, USD per MTok: "
        "deepseek 0.0448/0.30 (Wafer, D-277), Haiku 5.5 0.10/0.50 and Sonnet 5.5 2/10 "
        "(decisions 2026-10-30), Opus 5.5 4/20 (D-269); OpenRouter's Batch API bills "
        "Claude at half. "
        "Dataset: D-234; revision, file sha256 and licence (Apache-2.0 at "
        "github.com/Alab-NII/2wikimultihop) read 2026-11-01. Passage form: HippoRAG "
        "2's main.py. Extraction source blob: engine/src/graph/extraction.rs at "
        "639ee82f. Written 2026-11-01, before any 2Wiki extraction"
    ),
)


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
