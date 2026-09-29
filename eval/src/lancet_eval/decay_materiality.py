"""D-89 decay materiality for 06.3.4.1 (06.3.4.1-21).

06.3.3's committed decay rule (`decay.analyze_decay`) has no size floor on its slope
prong, so a +0.033 ms/query slope on a ~160 ms node fired it in pass A. D-89 amends D-64
for every decay and flatness reading in this phase: decay is present only when it is
material relative to the node's own speed, on both prongs. This module is a pure
function over `decay.analyze_decay`'s output; `decay.py` and 06.3.3's
`COMMITTED_THRESHOLDS` are untouched.

Censoring is unchanged (RESEARCH Pitfall 6): a censored or too-small set reads
`unavailable` on both D-89 prongs, never flat. Because the materiality threshold is
derived from the early-window p95, an unavailable window prong also makes the slope
prong unavailable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from lancet_eval import decay
from lancet_eval.thresholds import (
    COMMITTED_DECAY_THRESHOLDS_06341,
    MaterialDecayThresholds,
)


@dataclass(frozen=True)
class MaterialDecayVerdict:
    """The D-89 reading of one record set, with each prong's availability and inputs."""

    decay_present: bool
    slope_prong_available: bool
    slope_prong_fired: bool
    window_prong_available: bool
    window_prong_fired: bool
    slope_ms_per_query: float
    slope_p_value: float
    projected_growth_ms: float
    early_p95_ms: float
    late_p95_ms: float
    window_delta_ms: float
    materiality_threshold_ms: float | None
    censored_count: int
    unusable_dropped_count: int
    base_verdict: decay.DecayVerdict
    rule_provenance: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable projection (the base verdict is summarized, not nested)."""
        return {
            "decay_present": self.decay_present,
            "slope_prong_available": self.slope_prong_available,
            "slope_prong_fired": self.slope_prong_fired,
            "window_prong_available": self.window_prong_available,
            "window_prong_fired": self.window_prong_fired,
            "slope_ms_per_query": self.slope_ms_per_query,
            "slope_p_value": self.slope_p_value,
            "projected_growth_ms": self.projected_growth_ms,
            "early_p95_ms": self.early_p95_ms,
            "late_p95_ms": self.late_p95_ms,
            "window_delta_ms": self.window_delta_ms,
            "materiality_threshold_ms": self.materiality_threshold_ms,
            "censored_count": self.censored_count,
            "unusable_dropped_count": self.unusable_dropped_count,
            "reason": self.reason,
            "base_trend_reason": self.base_verdict.trend_result.reason,
            "base_window_reason": self.base_verdict.window_result.reason,
        }


def evaluate_material_decay(
    verdict: decay.DecayVerdict,
    rule: MaterialDecayThresholds = COMMITTED_DECAY_THRESHOLDS_06341,
) -> MaterialDecayVerdict:
    """Apply D-89 to an already-computed `decay.DecayVerdict` (pure, no I/O).

    Reads only `trend_result.is_available/.is_significant/.slope/.p_value` and
    `window_result.is_available/.early_percentile_ms/.late_percentile_ms/.delta_ms`.
    """
    trend = verdict.trend_result
    window = verdict.window_result
    censored_count = max(trend.censored_count, window.censored_count)

    if not window.is_available:
        # The threshold needs the early-window p95, so neither prong can be read. An
        # unavailable set is never flat.
        return MaterialDecayVerdict(
            decay_present=False,
            slope_prong_available=False,
            slope_prong_fired=False,
            window_prong_available=False,
            window_prong_fired=False,
            slope_ms_per_query=trend.slope,
            slope_p_value=trend.p_value,
            projected_growth_ms=0.0,
            early_p95_ms=window.early_percentile_ms,
            late_p95_ms=window.late_percentile_ms,
            window_delta_ms=window.delta_ms,
            materiality_threshold_ms=None,
            censored_count=censored_count,
            unusable_dropped_count=verdict.unusable_dropped_count,
            base_verdict=verdict,
            rule_provenance=rule.provenance,
            reason="unavailable",
        )

    threshold = rule.materiality_threshold_ms(window.early_percentile_ms)
    projected = trend.slope * rule.projection_horizon_records
    window_fired = window.delta_ms >= threshold
    slope_available = trend.is_available
    slope_fired = slope_available and trend.is_significant and projected >= threshold
    decay_present = slope_fired or window_fired

    return MaterialDecayVerdict(
        decay_present=decay_present,
        slope_prong_available=slope_available,
        slope_prong_fired=slope_fired,
        window_prong_available=True,
        window_prong_fired=window_fired,
        slope_ms_per_query=trend.slope,
        slope_p_value=trend.p_value,
        projected_growth_ms=projected,
        early_p95_ms=window.early_percentile_ms,
        late_p95_ms=window.late_percentile_ms,
        window_delta_ms=window.delta_ms,
        materiality_threshold_ms=threshold,
        censored_count=censored_count,
        unusable_dropped_count=verdict.unusable_dropped_count,
        base_verdict=verdict,
        rule_provenance=rule.provenance,
        reason=(
            "decay_present"
            if decay_present
            else "flat"
            if slope_available
            else "unavailable"
        ),
    )


def analyze_material_decay(
    records: Sequence[Any],
    rule: MaterialDecayThresholds = COMMITTED_DECAY_THRESHOLDS_06341,
    node_name: str = "RetrieveHybrid",
) -> MaterialDecayVerdict:
    """`decay.analyze_decay` under the rule's base inputs, then the D-89 test."""
    rule.validate()
    base = decay.analyze_decay(
        records, rule.base, restart_ordinal=None, node_name=node_name
    )
    return evaluate_material_decay(base, rule)


# 06.3.4.1 D-89 noise check: escalation rule committed before the check runs
# (06.3.4.1-21).
NOISE_WINDOW_RECORDS = 200
NOISE_ESCALATION_FRACTION = 0.05


# RED stubs (06.3.4.1-21 Task 2): trivial returns so the tests fail on assertions.
def first_uncensored(
    records: Sequence[Any], n: int, node_name: str = "RetrieveHybrid"
) -> list[Any]:
    return []


def noise_escalation(
    windows: int, fired_either: int, first_fired: bool, last_fired: bool
) -> bool:
    return False


def contiguous_window_noise(
    records: Sequence[Any],
    window: int = NOISE_WINDOW_RECORDS,
    rule: MaterialDecayThresholds = COMMITTED_DECAY_THRESHOLDS_06341,
) -> dict[str, Any]:
    return {}


def replay_arm_flips(
    replay_root: Any, contrast_journal: Any = None, contrast_first_n: int = 350
) -> dict[str, Any]:
    return {}


def main(argv: Sequence[str] | None = None) -> int:
    return 1
