"""D-40 per-question_type strata of the four-arm report, as float `detail` keys.

The strata are secondaries under D-111: they carry no p-value, are never Holm-tested
and are never decisive. Every key and value is a float, so `report.json` keeps its
schema (D-126). A stratum below `COMMITTED_THRESHOLDS.min_stratum_cell_size` carries
its n and its value only, never an interval (AI-SPEC section 6).

The three strata are the gold `question_type` values of the G population. `null_query`
is never a G stratum, so a question of any other type is refused (fail closed), and so
is a question missing from the type map.

Intervals reuse the `stats` helpers (Wilson for 0/1 rates, the percentile bootstrap at
`BOOTSTRAP_B` and `BOOTSTRAP_SEED` for means) and `p4.paired_delta`; this module has no
resampler of its own. Values are visited in sorted question-ID order, so a bootstrap
interval is reproducible.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import Any, Literal

from lancet_eval.p4 import paired_delta
from lancet_eval.stats import (
    BOOTSTRAP_B,
    BOOTSTRAP_SEED,
    bootstrap_mean_ci,
    percentile,
    wilson_ci,
)
from lancet_eval.thresholds import COMMITTED_THRESHOLDS

STRATUM_TYPES = ("comparison_query", "inference_query", "temporal_query")

_PERCENTILES = {"p50": 0.50, "p95": 0.95}


def _stratum_of(qid: str, qtype_of: Mapping[str, str]) -> str:
    qtype = qtype_of.get(qid)
    if qtype is None:
        raise ValueError(f"question {qid!r} has no question_type in the type map")
    if qtype not in STRATUM_TYPES:
        raise ValueError(
            f"question {qid!r} has question_type {qtype!r}, not a G stratum "
            f"(expected one of {list(STRATUM_TYPES)})"
        )
    return qtype


def _group(
    qids: Sequence[str], qtype_of: Mapping[str, str]
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {t: [] for t in STRATUM_TYPES}
    for qid in sorted(qids):
        groups[_stratum_of(qid, qtype_of)].append(qid)
    return groups


def _cell_size() -> int:
    return COMMITTED_THRESHOLDS.min_stratum_cell_size


def summarize(
    xs: Sequence[float], statistic: Literal["mean", "p50", "p95"] = "mean"
) -> float:
    """The mean, p50 or p95 of `xs` (the `stats.percentile` the latency rows use).

    Args:
        xs: The values; not empty.
        statistic: Which summary to take.

    Returns:
        The summary as a float.

    Raises:
        ValueError: If `xs` is empty.
    """
    if not xs:
        raise ValueError("cannot summarise an empty list of values")
    if statistic == "mean":
        return float(fmean(xs))
    return float(percentile(list(xs), _PERCENTILES[statistic]))


def type_strata(
    values: Mapping[str, float],
    qtype_of: Mapping[str, str],
    *,
    statistic: Literal["mean", "p50", "p95"] = "mean",
    interval: Literal["wilson", "bootstrap", "none"],
) -> dict[str, float]:
    """Per-type n, value and (at the cell size) interval of one per-question value.

    Args:
        values: Question ID to the per-question value of one dimension.
        qtype_of: Question ID to its gold `question_type`.
        statistic: The stratum value: the mean, or the p50 or p95 of the stratum (the
            `stats.percentile` the latency dimensions use).
        interval: `wilson` for a 0/1 rate, `bootstrap` for a mean, `none` for no
            interval. An interval is defined for the mean only.

    Returns:
        For each type: `type_<qt>_n`, `type_<qt>_value` when n is above zero, and
        `type_<qt>_ci_lower` and `type_<qt>_ci_upper` only when n is at least
        `COMMITTED_THRESHOLDS.min_stratum_cell_size` and `interval` is not `none`.
        Every value is a float.

    Raises:
        ValueError: If a question's type is missing or not one of the three G types,
            if `wilson` meets a value that is not 0 or 1, or if an interval is asked
            for a percentile statistic.
    """
    if interval != "none" and statistic != "mean":
        raise ValueError(f"no interval is defined for statistic {statistic!r}")
    groups = _group(list(values), qtype_of)
    if interval == "wilson":
        for qid, value in values.items():
            if value not in (0.0, 1.0):
                raise ValueError(
                    f"wilson strata need 0/1 values, question {qid!r} has {value!r}"
                )
    out: dict[str, float] = {}
    for qtype, qids in groups.items():
        xs = [float(values[q]) for q in qids]
        out[f"type_{qtype}_n"] = float(len(xs))
        if not xs:
            continue
        out[f"type_{qtype}_value"] = summarize(xs, statistic)
        if interval == "none" or len(xs) < _cell_size():
            continue
        if interval == "wilson":
            _, lo, hi = wilson_ci(round(sum(xs)), len(xs))
        else:
            _, lo, hi = bootstrap_mean_ci(xs, seed=BOOTSTRAP_SEED, b=BOOTSTRAP_B)
        out[f"type_{qtype}_ci_lower"] = float(lo)
        out[f"type_{qtype}_ci_upper"] = float(hi)
    return out


def constant_yes_baselines(
    qids: Sequence[str], gold_by_qid: Mapping[str, Any]
) -> dict[str, float]:
    """Per type, the share of the given questions whose gold answer is `yes`.

    This is the constant-"Yes" baseline each stratum of `answer_usable` is read beside
    (06.3.4.1 section 5 number 5). The rule is `unpark_gates`' SC-3 rule: the stripped,
    lower-cased gold answer equals `yes`. It covers exactly the question IDs given.

    Args:
        qids: The question IDs the stratum value was computed over.
        gold_by_qid: Question ID to an object with `gold_answer` and `question_type`.

    Returns:
        `type_<qt>_constant_yes_baseline` for each type with at least one question.

    Raises:
        ValueError: If a question's type is not one of the three G types.
    """
    qtype_of = {q: str(gold_by_qid[q].question_type) for q in qids}
    out: dict[str, float] = {}
    for qtype, members in _group(list(qids), qtype_of).items():
        if not members:
            continue
        yes = sum(
            1
            for q in members
            if str(gold_by_qid[q].gold_answer).strip().lower() == "yes"
        )
        out[f"type_{qtype}_constant_yes_baseline"] = float(yes / len(members))
    return out


def paired_delta_strata(
    values_x: Mapping[str, float],
    values_ref: Mapping[str, float],
    qtype_of: Mapping[str, str],
) -> dict[str, float]:
    """Per-type paired delta of arm X against the reference arm.

    Args:
        values_x: Question ID to the compared arm's per-question value.
        values_ref: Question ID to the reference arm's value; the same questions.
        qtype_of: Question ID to its gold `question_type`.

    Returns:
        For each type: `type_<qt>_n_pairs`, `type_<qt>_delta` (the mean paired
        difference) when n_pairs is above zero, and the bootstrap interval keys
        `type_<qt>_ci_lower` and `type_<qt>_ci_upper` only when n_pairs is at least
        `COMMITTED_THRESHOLDS.min_stratum_cell_size`. Every value is a float.

    Raises:
        ValueError: If the two maps do not cover the same questions, or a question's
            type is missing or not one of the three G types.
    """
    if set(values_x) != set(values_ref):
        raise ValueError("the two arms' values do not cover the same questions")
    out: dict[str, float] = {}
    for qtype, qids in _group(list(values_x), qtype_of).items():
        out[f"type_{qtype}_n_pairs"] = float(len(qids))
        if not qids:
            continue
        x = {q: float(values_x[q]) for q in qids}
        ref = {q: float(values_ref[q]) for q in qids}
        if len(qids) >= _cell_size():
            pd = paired_delta(x, ref)
            out[f"type_{qtype}_delta"] = float(pd.delta)
            out[f"type_{qtype}_ci_lower"] = float(pd.ci_lower)
            out[f"type_{qtype}_ci_upper"] = float(pd.ci_upper)
        else:
            out[f"type_{qtype}_delta"] = float(
                fmean(x.values()) - fmean(ref.values())
            )
    return out
