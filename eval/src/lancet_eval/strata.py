"""D-40 per-question_type strata (RED stub; the implementation follows)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

STRATUM_TYPES = ("comparison_query", "inference_query", "temporal_query")


def type_strata(
    values: Mapping[str, float],
    qtype_of: Mapping[str, str],
    *,
    statistic: Literal["mean", "p50", "p95"] = "mean",
    interval: Literal["wilson", "bootstrap", "none"],
) -> dict[str, float]:
    """Stub."""
    return {}


def constant_yes_baselines(
    qids: Sequence[str], gold_by_qid: Mapping[str, Any]
) -> dict[str, float]:
    """Stub."""
    return {}


def paired_delta_strata(
    values_x: Mapping[str, float],
    values_ref: Mapping[str, float],
    qtype_of: Mapping[str, str],
) -> dict[str, float]:
    """Stub."""
    return {}
