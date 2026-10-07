"""Ablation pairing, deduplication, and stratification helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lancet_eval.arms import canonical_arm, resolve_arm
from lancet_eval.stats import BOOTSTRAP_B, BOOTSTRAP_SEED, bootstrap_mean_ci
from lancet_eval.usability import has_arm_provenance, is_usable

if TYPE_CHECKING:
    from lancet_eval.corpus import GoldQuestion
    from lancet_eval.journal import RunRecord


@dataclass(frozen=True)
class ArmPair:
    """Paired work units for a single question across graph-on and graph-off.

    `graph_on` and `graph_off` are the historical field names. `treatment` and
    `reference` read the same two records for a pair formed over any registry pair
    (`form_arm_pairs`): the treatment arm is stored as `graph_on`, the reference arm
    as `graph_off`.
    """

    question_id: str
    graph_on: RunRecord
    graph_off: RunRecord
    gold_question: GoldQuestion

    @property
    def treatment(self) -> RunRecord:
        """The treatment-arm record (the historical `graph_on` field)."""
        return self.graph_on

    @property
    def reference(self) -> RunRecord:
        """The reference-arm record (the historical `graph_off` field)."""
        return self.graph_off


@dataclass(frozen=True)
class JoinResult:
    """Outcome of form_pairs join with audit drop buckets."""

    pairs: list[ArmPair]
    single_arm_usable_drops: int
    missing_arm_drops: int
    null_gold_drops: int
    provenance_drops: int
    total_distinct_questions: int


@dataclass(frozen=True)
class PairedDeltaResult:
    """Outcome of differencing and bootstrapping a metric across pairs."""

    mean: float | None
    ci_lower: float | None
    ci_upper: float | None
    pair_count: int
    pairing_coverage: float
    answerable_count: int
    excluded_count: int
    is_degenerate: bool
    strata: dict[str, float]
    strata_counts: dict[str, int]
    join_result: JoinResult | None = None


def deduplicate_by_arm(records: list[RunRecord]) -> tuple[list[RunRecord], int]:
    """Collapse records keyed on (question_id, graph_arm), keeping the later occurrence.

    Returns:
        (deduplicated_records, collapsed_count)
    """
    last_by_key: dict[tuple[str, str], RunRecord] = {}
    for r in records:
        key = (r.question_id, r.graph_arm)
        last_by_key[key] = r

    # Preserve order of the surviving records based on their last appearance
    # or return them in deterministic order
    collapsed_count = len(records) - len(last_by_key)
    surviving_records = list(last_by_key.values())
    return surviving_records, collapsed_count


def form_pairs(
    records: list[RunRecord],
    gold_questions: dict[str, GoldQuestion],
) -> JoinResult:
    """Form inner-join pairs on question_id between graph-on and graph-off arms.

    Requirements:
      - Both records must satisfy is_usable (ADJACENCY EDGE)
      - The graph-off record must satisfy has_arm_provenance (PROVENANCE EDGE)
      - Null gold questions (is_null == True) are dropped (NULL EDGE)
      - Surviving pairs sorted by question_id ascending (ORDERING EDGE)
    """
    # Group by question_id
    by_question: dict[str, dict[str, RunRecord]] = {}
    for r in records:
        by_question.setdefault(r.question_id, {})[r.graph_arm] = r

    selected = {
        qid: (arm_map.get("graph-on"), arm_map.get("graph-off"))
        for qid, arm_map in by_question.items()
    }
    return _join_pairs(selected, gold_questions, treatment_needs_provenance=False)


def form_arm_pairs(
    records: list[RunRecord],
    gold_questions: dict[str, GoldQuestion],
    *,
    treatment_arm: str,
    reference_arm: str,
) -> JoinResult:
    """Form the `form_pairs` join over any two registry arms (D-101).

    Records are matched to an arm by canonical label, so a legacy `graph-off` record
    answers to `hybrid` and `graph-on` to `hybrid+graph`; the stored label is never
    rewritten. The treatment record is carried as `ArmPair.graph_on` (`.treatment`) and
    the reference record as `ArmPair.graph_off` (`.reference`). The edges are those of
    `form_pairs`; the GRAPH_ABLATION provenance edge applies to every side whose arm
    disables graph context, so for the legacy pair it is the reference alone.

    Args:
        records: Deduplicated records of any arms.
        gold_questions: Gold questions keyed by question ID.
        treatment_arm: Canonical label or alias of the treatment arm.
        reference_arm: Canonical label or alias of the reference arm.

    Returns:
        The join result; a record of a different arm is ignored, and counts toward
        `total_distinct_questions` only through its question.

    Raises:
        ValueError: If an arm is unknown, or one question has records under two
            stored labels that share a canonical form (an alias and its canonical
            label are never merged).
    """
    treatment = canonical_arm(treatment_arm)
    reference = canonical_arm(reference_arm)
    treatment_needs = resolve_arm(treatment).disable_graph_context

    by_question: dict[str, dict[str, RunRecord]] = {}
    stored: dict[tuple[str, str], str] = {}
    for r in records:
        by_question.setdefault(r.question_id, {})
        try:
            canonical = canonical_arm(r.graph_arm)
        except ValueError:
            continue
        if canonical not in (treatment, reference):
            continue
        seen = stored.setdefault((r.question_id, canonical), r.graph_arm)
        if seen != r.graph_arm:
            raise ValueError(
                f"question {r.question_id!r} has records under both "
                f"{seen!r} and {r.graph_arm!r}, which are the same arm "
                f"({canonical!r}); refusing to merge them"
            )
        by_question[r.question_id][canonical] = r

    selected = {
        qid: (arm_map.get(treatment), arm_map.get(reference))
        for qid, arm_map in by_question.items()
    }
    return _join_pairs(
        selected, gold_questions, treatment_needs_provenance=treatment_needs
    )


def _join_pairs(
    selected: dict[str, tuple[RunRecord | None, RunRecord | None]],
    gold_questions: dict[str, GoldQuestion],
    *,
    treatment_needs_provenance: bool,
) -> JoinResult:
    """The shared inner join of `form_pairs` and `form_arm_pairs`.

    `selected` maps each question to its `(treatment, reference)` records, either of
    which may be absent.
    """
    total_distinct_questions = len(selected)
    pairs: list[ArmPair] = []

    single_arm_usable_drops = 0
    missing_arm_drops = 0
    null_gold_drops = 0
    provenance_drops = 0

    for qid in sorted(selected.keys()):
        rec_on, rec_off = selected[qid]

        if rec_on is None or rec_off is None:
            missing_arm_drops += 1
            continue

        on_usable = is_usable(rec_on)
        off_usable = is_usable(rec_off)

        if on_usable != off_usable:
            single_arm_usable_drops += 1
            continue

        if not on_usable and not off_usable:
            single_arm_usable_drops += 1
            continue

        # Both are usable. Check provenance of graph-off
        if not has_arm_provenance(rec_off):
            provenance_drops += 1
            continue
        if treatment_needs_provenance and not has_arm_provenance(rec_on):
            provenance_drops += 1
            continue

        # Check null gold
        gold = gold_questions.get(qid)
        if gold is not None and gold.is_null:
            null_gold_drops += 1
            continue

        if gold is None:
            # If not in gold_map, treat as unanswerable/null drop
            null_gold_drops += 1
            continue

        pairs.append(
            ArmPair(
                question_id=qid,
                graph_on=rec_on,
                graph_off=rec_off,
                gold_question=gold,
            )
        )

    # Sort pairs by question_id ascending
    pairs.sort(key=lambda p: p.question_id)

    return JoinResult(
        pairs=pairs,
        single_arm_usable_drops=single_arm_usable_drops,
        missing_arm_drops=missing_arm_drops,
        null_gold_drops=null_gold_drops,
        provenance_drops=provenance_drops,
        total_distinct_questions=total_distinct_questions,
    )


def compute_paired_delta(
    pairs: list[ArmPair],
    score_fn: Callable[[RunRecord, GoldQuestion], float | None],
    *,
    coverage_denominator: int,
    answerable_count: int,
    seed: int = BOOTSTRAP_SEED,
    b: int = BOOTSTRAP_B,
    join_result: JoinResult | None = None,
) -> PairedDeltaResult:
    """Compute mean paired delta, bootstrap CI, and stratification by question_type.

    score_fn is called as score_fn(record, gold_question) -> float | None.
    If either arm returns None (or question has no gold), pair is excluded.
    """
    diffs: list[float] = []
    strata_diffs: dict[str, list[float]] = {}
    excluded_count = 0

    for pair in pairs:
        if pair.gold_question.is_null:
            excluded_count += 1
            continue

        s_on = score_fn(pair.graph_on, pair.gold_question)
        s_off = score_fn(pair.graph_off, pair.gold_question)

        if s_on is None or s_off is None:
            excluded_count += 1
            continue

        d = float(s_on - s_off)
        diffs.append(d)

        qtype = pair.gold_question.question_type or "unknown"
        strata_diffs.setdefault(qtype, []).append(d)

    n_pairs = len(diffs)
    coverage = (n_pairs / coverage_denominator) if coverage_denominator > 0 else 0.0

    if n_pairs == 0:
        return PairedDeltaResult(
            mean=None,
            ci_lower=None,
            ci_upper=None,
            pair_count=0,
            pairing_coverage=coverage,
            answerable_count=answerable_count,
            excluded_count=excluded_count,
            is_degenerate=False,
            strata={},
            strata_counts={},
            join_result=join_result,
        )

    if n_pairs == 1:
        val = diffs[0]
        strata_means = {
            t: float(sum(ds) / len(ds)) for t, ds in strata_diffs.items() if ds
        }
        strata_counts = {t: len(ds) for t, ds in strata_diffs.items() if ds}
        return PairedDeltaResult(
            mean=val,
            ci_lower=val,
            ci_upper=val,
            pair_count=1,
            pairing_coverage=coverage,
            answerable_count=answerable_count,
            excluded_count=excluded_count,
            is_degenerate=True,
            strata=strata_means,
            strata_counts=strata_counts,
            join_result=join_result,
        )

    mu, ci_lo, ci_hi = bootstrap_mean_ci(diffs, seed=seed, b=b)
    strata_means = {t: float(sum(ds) / len(ds)) for t, ds in strata_diffs.items() if ds}
    strata_counts = {t: len(ds) for t, ds in strata_diffs.items() if ds}

    return PairedDeltaResult(
        mean=mu,
        ci_lower=ci_lo,
        ci_upper=ci_hi,
        pair_count=n_pairs,
        pairing_coverage=coverage,
        answerable_count=answerable_count,
        excluded_count=excluded_count,
        is_degenerate=False,
        strata=strata_means,
        strata_counts=strata_counts,
        join_result=join_result,
    )
