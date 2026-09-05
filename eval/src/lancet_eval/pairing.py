"""Ablation pairing, deduplication, and stratification helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lancet_eval.stats import BOOTSTRAP_B, BOOTSTRAP_SEED, bootstrap_mean_ci
from lancet_eval.usability import has_arm_provenance, is_usable

if TYPE_CHECKING:
    from lancet_eval.corpus import GoldQuestion
    from lancet_eval.journal import RunRecord


@dataclass(frozen=True)
class ArmPair:
    """Paired work units for a single question across graph-on and graph-off."""

    question_id: str
    graph_on: RunRecord
    graph_off: RunRecord
    gold_question: GoldQuestion


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

    total_distinct_questions = len(by_question)
    pairs: list[ArmPair] = []

    single_arm_usable_drops = 0
    missing_arm_drops = 0
    null_gold_drops = 0
    provenance_drops = 0

    for qid in sorted(by_question.keys()):
        arm_map = by_question[qid]
        rec_on = arm_map.get("graph-on")
        rec_off = arm_map.get("graph-off")

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
