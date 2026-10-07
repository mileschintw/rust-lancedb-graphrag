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
