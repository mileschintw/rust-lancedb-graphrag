"""Decay detection for retrieval latency measurement passes.

Answers whether retrieval latency trends upward with query ordinal, evaluated
against pre-committed decision thresholds.

Note on Usability Predicate:
The usability predicate (is_usable) is deliberately NOT applied to filter records
prior to censoring, percentile, or trend analysis in this module. Applying is_usable
would discard every record whose retrieval node failed or timed out — precisely
the clipped tail observations this instrument is built to detect and count.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from lancet_eval.latency import percentile_with_ci
from lancet_eval.thresholds import (
    COMMITTED_THRESHOLDS,
    DecisionThresholds,
)


class DecayAnalysisError(ValueError):
    """Raised when record ordering is corrupted, gapped, or invalid."""


@dataclass(frozen=True)
class TrendResult:
    """Result of rank-based Theil-Sen slope estimation and trend significance."""

    slope: float
    p_value: float
    is_significant: bool
    is_censored: bool
    censored_count: int
    is_available: bool
    reason: str


@dataclass(frozen=True)
class WindowComparisonResult:
    """Result of early-versus-late window latency comparison."""

    early_window_size: int
    early_percentile_ms: float
    late_window_size: int
    late_percentile_ms: float
    delta_ms: float
    materiality_threshold_ms: float
    is_materially_elevated: bool
    is_censored: bool
    censored_count: int
    is_available: bool
    reason: str


@dataclass(frozen=True)
class RestartDiscriminatorResult:
    """Result of segment-boundary restart comparison between tail and head."""

    segment1_tail_size: int
    segment1_tail_p95_ms: float
    segment2_head_size: int
    segment2_head_p95_ms: float
    delta_ms: float
    ci_low: float
    ci_high: float
    hypothesis: str  # "process_state", "accumulated_store_state", or "inconclusive"
    is_censored: bool
    censored_count: int
    is_available: bool
    reason: str


@dataclass(frozen=True)
class DecayVerdict:
    """Combined decay verdict across trend, window, and restart prongs."""

    verdict_decay_present: bool
    prong_slope_fired: bool
    prong_window_fired: bool
    slope_statistic: float
    slope_threshold: float
    window_delta_ms: float
    window_threshold_ms: float
    trend_result: TrendResult
    window_result: WindowComparisonResult
    restart_result: RestartDiscriminatorResult | None
    stratified_results: dict[str, Any] = field(default_factory=dict)
    provenance: str = ""


def _normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def validate_and_sort_records(records: Sequence[Any]) -> list[Any]:
    """Sort records by recorded ordinal and validate uniqueness and monotonicity.

    Physical journal line order is explicitly NOT required to be monotonic:
    records are sorted by their recorded dispatch ordinal first. The sorted
    sequence must then be unique and gap-free.
    """
    if not records:
        return []

    # Sort strictly by dispatch ordinal first
    try:
        sorted_records = sorted(records, key=lambda r: int(r.ordinal))
    except Exception as exc:
        raise DecayAnalysisError(
            f"Records missing integer ordinal field: {exc}"
        ) from exc

    seen_ordinals: set[int] = set()
    prev_ord: int | None = None

    for r in sorted_records:
        ord_val = int(r.ordinal)
        if ord_val in seen_ordinals:
            raise DecayAnalysisError(
                f"Duplicate ordinal detected: ordinal {ord_val} appears more than once"
            )
        seen_ordinals.add(ord_val)

        if prev_ord is not None and ord_val != prev_ord + 1:
            raise DecayAnalysisError(
                f"Gap in ordinals detected: expected {prev_ord + 1}, found {ord_val}"
            )
        prev_ord = ord_val

    return sorted_records


def compute_theil_sen_trend(
    ordinals: Sequence[int],
    latencies: Sequence[float],
    thresholds: DecisionThresholds | None = None,
    censored_count: int = 0,
) -> TrendResult:
    """Estimate slope using Theil-Sen pairwise medians and Mann-Kendall test.

    Pure stdlib implementation.
    """
    thresh = thresholds or COMMITTED_THRESHOLDS
    n = len(latencies)

    if censored_count > 0:
        return TrendResult(
            slope=0.0,
            p_value=1.0,
            is_significant=False,
            is_censored=True,
            censored_count=censored_count,
            is_available=False,
            reason=(
                f"Trend analysis refused: observation set contains {censored_count} "
                "censored observations. "
                "A saturated instrument cannot be treated as flat."
            ),
        )

    if n < 4:
        return TrendResult(
            slope=0.0,
            p_value=1.0,
            is_significant=False,
            is_censored=False,
            censored_count=0,
            is_available=False,
            reason=f"Insufficient sample size for trend analysis (n={n} < 4)",
        )

    # 1. Theil-Sen slope: median of all pairwise slopes
    slopes: list[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            dx = ordinals[j] - ordinals[i]
            if dx != 0:
                slopes.append((latencies[j] - latencies[i]) / float(dx))

    slopes.sort()
    med_idx = len(slopes) // 2
    slope_est = (
        slopes[med_idx]
        if len(slopes) % 2 != 0
        else 0.5 * (slopes[med_idx - 1] + slopes[med_idx])
    )

    # 2. Mann-Kendall S statistic
    s = 0
    for i in range(n):
        for j in range(i + 1, n):
            diff = latencies[j] - latencies[i]
            if diff > 0:
                s += 1
            elif diff < 0:
                s -= 1

    var_s = (n * (n - 1) * (2 * n + 5)) / 18.0
    if s > 0:
        z = (s - 1.0) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1.0) / math.sqrt(var_s)
    else:
        z = 0.0

    p_val = math.erfc(abs(z) / math.sqrt(2.0))
    is_sig = (p_val < thresh.decay_significance_threshold) and (slope_est > 0.0)

    return TrendResult(
        slope=slope_est,
        p_value=p_val,
        is_significant=is_sig,
        is_censored=False,
        censored_count=0,
        is_available=True,
        reason=(
            f"Theil-Sen slope = {slope_est:.4f} ms/query, "
            f"p-value = {p_val:.4f} (alpha = {thresh.decay_significance_threshold})"
        ),
    )


def compare_early_late_windows(
    latencies: Sequence[float],
    thresholds: DecisionThresholds | None = None,
    censored_count: int = 0,
) -> WindowComparisonResult:
    """Compare latency p95 between early and late fractions of observations."""
    thresh = thresholds or COMMITTED_THRESHOLDS
    n = len(latencies)

    if censored_count > 0:
        return WindowComparisonResult(
            early_window_size=0,
            early_percentile_ms=0.0,
            late_window_size=0,
            late_percentile_ms=0.0,
            delta_ms=0.0,
            materiality_threshold_ms=thresh.materiality_delta_ms,
            is_materially_elevated=False,
            is_censored=True,
            censored_count=censored_count,
            is_available=False,
            reason=(
                f"Window comparison refused: "
                f"{censored_count} censored observation(s) present."
            ),
        )

    if n < 8:
        return WindowComparisonResult(
            early_window_size=0,
            early_percentile_ms=0.0,
            late_window_size=0,
            late_percentile_ms=0.0,
            delta_ms=0.0,
            materiality_threshold_ms=thresh.materiality_delta_ms,
            is_materially_elevated=False,
            is_censored=False,
            censored_count=0,
            is_available=False,
            reason=f"Insufficient sample size for windowing (n={n} < 8)",
        )

    f_early, f_late = thresh.window_fractions
    w_early_n = max(2, int(math.floor(n * f_early)))
    w_late_n = max(2, int(math.floor(n * f_late)))

    early_slice = latencies[:w_early_n]
    late_slice = latencies[-w_late_n:]

    p_early = percentile_with_ci(
        early_slice, p=thresh.derivation_percentile, seed=thresh.bootstrap_seed
    ).percentile
    p_late = percentile_with_ci(
        late_slice, p=thresh.derivation_percentile, seed=thresh.bootstrap_seed
    ).percentile
    delta = p_late - p_early
    is_elevated = delta >= thresh.materiality_delta_ms

    return WindowComparisonResult(
        early_window_size=w_early_n,
        early_percentile_ms=p_early,
        late_window_size=w_late_n,
        late_percentile_ms=p_late,
        delta_ms=delta,
        materiality_threshold_ms=thresh.materiality_delta_ms,
        is_materially_elevated=is_elevated,
        is_censored=False,
        censored_count=0,
        is_available=True,
        reason=(
            f"Early p95 = {p_early:.1f}ms (n={w_early_n}), "
            f"Late p95 = {p_late:.1f}ms (n={w_late_n}), "
            f"Delta = {delta:.1f}ms (threshold = {thresh.materiality_delta_ms:.1f}ms)"
        ),
    )


def evaluate_restart_boundary(
    segment1_latencies: Sequence[float],
    segment2_latencies: Sequence[float],
    thresholds: DecisionThresholds | None = None,
    censored_count: int = 0,
    seed: int = 42,
) -> RestartDiscriminatorResult:
    """Compare segment-1 tail against segment-2 head.

    Discriminates process state vs accumulated store state.
    """
    thresh = thresholds or COMMITTED_THRESHOLDS
    tail_n, head_n = thresh.segment_boundary_sizes

    if censored_count > 0:
        return RestartDiscriminatorResult(
            segment1_tail_size=0,
            segment1_tail_p95_ms=0.0,
            segment2_head_size=0,
            segment2_head_p95_ms=0.0,
            delta_ms=0.0,
            ci_low=0.0,
            ci_high=0.0,
            hypothesis="inconclusive",
            is_censored=True,
            censored_count=censored_count,
            is_available=False,
            reason=f"Restart analysis refused: {censored_count} censored observations.",
        )

    if len(segment1_latencies) < tail_n or len(segment2_latencies) < head_n:
        return RestartDiscriminatorResult(
            segment1_tail_size=len(segment1_latencies),
            segment1_tail_p95_ms=0.0,
            segment2_head_size=len(segment2_latencies),
            segment2_head_p95_ms=0.0,
            delta_ms=0.0,
            ci_low=0.0,
            ci_high=0.0,
            hypothesis="inconclusive",
            is_censored=False,
            censored_count=0,
            is_available=False,
            reason=(
                f"Insufficient observations at boundary: need {tail_n}/{head_n}, "
                f"got {len(segment1_latencies)}/{len(segment2_latencies)}"
            ),
        )

    tail = list(segment1_latencies[-tail_n:])
    head = list(segment2_latencies[:head_n])

    p_tail = percentile_with_ci(
        tail, p=thresh.derivation_percentile, seed=seed
    ).percentile
    p_head = percentile_with_ci(
        head, p=thresh.derivation_percentile, seed=seed
    ).percentile
    delta = p_head - p_tail

    # Bootstrap difference CI
    rng = random.Random(seed)
    boot_deltas: list[float] = []
    for _ in range(1000):
        t_boot = [tail[rng.randrange(tail_n)] for _ in range(tail_n)]
        h_boot = [head[rng.randrange(head_n)] for _ in range(head_n)]
        pt = percentile_with_ci(
            t_boot, p=thresh.derivation_percentile, seed=seed
        ).percentile
        ph = percentile_with_ci(
            h_boot, p=thresh.derivation_percentile, seed=seed
        ).percentile
        boot_deltas.append(ph - pt)

    boot_deltas.sort()
    ci_low = boot_deltas[int(0.025 * len(boot_deltas))]
    ci_high = boot_deltas[int(0.975 * len(boot_deltas))]

    # Hypothesis discrimination:
    # If interval spans 0 -> inconclusive
    # If delta < 0 and ci_high < 0 -> latency reset -> process_state
    # If delta >= 0 and ci_low > 0 -> latency stayed elevated -> accumulated_store_state
    if ci_low <= 0.0 <= ci_high:
        hyp = "inconclusive"
        reason = (
            f"Boundary delta {delta:.1f}ms 95% CI [{ci_low:.1f}, {ci_high:.1f}] "
            "spans zero: inconclusive."
        )
    elif delta < 0.0:
        hyp = "process_state"
        reason = (
            f"Boundary delta {delta:.1f}ms shows latency reset in segment 2: "
            "supports process state hypothesis."
        )
    else:
        hyp = "accumulated_store_state"
        reason = (
            f"Boundary delta {delta:.1f}ms shows latency remained elevated: "
            "supports accumulated store state hypothesis."
        )

    return RestartDiscriminatorResult(
        segment1_tail_size=tail_n,
        segment1_tail_p95_ms=p_tail,
        segment2_head_size=head_n,
        segment2_head_p95_ms=p_head,
        delta_ms=delta,
        ci_low=ci_low,
        ci_high=ci_high,
        hypothesis=hyp,
        is_censored=False,
        censored_count=0,
        is_available=True,
        reason=reason,
    )


def analyze_decay(
    records: Sequence[Any],
    thresholds: DecisionThresholds | None = None,
    restart_ordinal: int | None = None,
    node_name: str = "RetrieveHybrid",
) -> DecayVerdict:
    """Analyze retrieval latency decay over measurement records.

    Evaluates against committed decision thresholds. Sorts by ordinal first,
    verifies sequence validity, extracts latencies, and computes prongs.
    """
    thresh = thresholds or COMMITTED_THRESHOLDS
    thresh.validate_for_decay()

    sorted_records = validate_and_sort_records(records)
    if not sorted_records:
        empty_trend = TrendResult(
            slope=0.0,
            p_value=1.0,
            is_significant=False,
            is_censored=False,
            censored_count=0,
            is_available=False,
            reason="Empty record set",
        )
        empty_win = WindowComparisonResult(
            early_window_size=0,
            early_percentile_ms=0.0,
            late_window_size=0,
            late_percentile_ms=0.0,
            delta_ms=0.0,
            materiality_threshold_ms=thresh.materiality_delta_ms,
            is_materially_elevated=False,
            is_censored=False,
            censored_count=0,
            is_available=False,
            reason="Empty record set",
        )
        return DecayVerdict(
            verdict_decay_present=False,
            prong_slope_fired=False,
            prong_window_fired=False,
            slope_statistic=0.0,
            slope_threshold=thresh.decay_significance_threshold,
            window_delta_ms=0.0,
            window_threshold_ms=thresh.materiality_delta_ms,
            trend_result=empty_trend,
            window_result=empty_win,
            restart_result=None,
            provenance=thresh.provenance,
        )

    # Extract ordinals, latencies, and check censoring
    ordinals: list[int] = []
    latencies: list[float] = []
    censored_count = 0

    seg1_latencies: list[float] = []
    seg2_latencies: list[float] = []
    seen_segments: list[str] = []

    # Stratified accumulators: (arm, question_type) -> list of latencies
    strata: dict[tuple[str, str], list[float]] = {}

    for r in sorted_records:
        ord_val = int(r.ordinal)
        ordinals.append(ord_val)
        seg = getattr(r, "segment", "segment-1")
        if not seen_segments or seen_segments[-1] != seg:
            seen_segments.append(seg)

        arm = getattr(r, "graph_arm", "")
        q_type = getattr(r, "question_type", "")
        strata_key = (arm, q_type)
        if strata_key not in strata:
            strata[strata_key] = []

        # Find duration for node_name
        timings = getattr(r, "node_timings", []) or []
        t = next((t for t in timings if getattr(t, "node_name", "") == node_name), None)
        failures = getattr(r, "node_failures", []) or []
        f = next(
            (f for f in failures if getattr(f, "node_name", "") == node_name), None
        )

        if f is not None and getattr(f, "error_kind", None) == 1:
            censored_count += 1
            continue

        if t is not None and getattr(t, "duration_ms", None) is not None:
            dur = float(t.duration_ms)
            latencies.append(dur)
            strata[strata_key].append(dur)
            if seg == "segment-1":
                seg1_latencies.append(dur)
            elif seg == "segment-2":
                seg2_latencies.append(dur)

    # Validate segment transitions if segment-2 is present
    if len(seen_segments) > 2:
        raise DecayAnalysisError(
            f"Segment labels change more than once: observed {seen_segments!r}"
        )

    restart_res: RestartDiscriminatorResult | None = None
    if restart_ordinal is not None:
        min_ord = ordinals[0] if ordinals else 0
        max_ord = ordinals[-1] if ordinals else 0
        if not (min_ord <= restart_ordinal <= max_ord):
            raise DecayAnalysisError(
                f"Recorded restart ordinal {restart_ordinal} lies "
                f"outside observed boundary [{min_ord}, {max_ord}]"
            )
        restart_res = evaluate_restart_boundary(
            seg1_latencies,
            seg2_latencies,
            thresholds=thresh,
            censored_count=censored_count,
            seed=thresh.bootstrap_seed,
        )

    # Compute prongs
    trend_res = compute_theil_sen_trend(
        ordinals[: len(latencies)],
        latencies,
        thresholds=thresh,
        censored_count=censored_count,
    )
    win_res = compare_early_late_windows(
        latencies,
        thresholds=thresh,
        censored_count=censored_count,
    )

    # Combined verdict
    prong_slope = trend_res.is_significant
    prong_window = win_res.is_materially_elevated
    decay_present = prong_slope or prong_window

    # Stratified summary
    strat_summary: dict[str, Any] = {}
    for (arm_k, type_k), vals in strata.items():
        label = f"{arm_k}:{type_k}"
        if not vals:
            strat_summary[label] = {
                "observation_count": 0,
                "reason": "Stratum has 0 usable observations",
                "percentile_p95": 0.0,
            }
        else:
            pct = percentile_with_ci(
                vals, p=thresh.derivation_percentile, seed=thresh.bootstrap_seed
            )
            strat_summary[label] = {
                "observation_count": len(vals),
                "percentile_p95": pct.percentile,
                "reason": pct.reason,
            }

    return DecayVerdict(
        verdict_decay_present=decay_present,
        prong_slope_fired=prong_slope,
        prong_window_fired=prong_window,
        slope_statistic=trend_res.slope,
        slope_threshold=thresh.decay_significance_threshold,
        window_delta_ms=win_res.delta_ms,
        window_threshold_ms=thresh.materiality_delta_ms,
        trend_result=trend_res,
        window_result=win_res,
        restart_result=restart_res,
        stratified_results=strat_summary,
        provenance=thresh.provenance,
    )
