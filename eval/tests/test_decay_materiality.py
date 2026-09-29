"""Tests for the D-89 materiality rule (06.3.4.1-21).

Boundary cases run on hand-constructed `decay.TrendResult`,
`WindowComparisonResult` and `DecayVerdict` objects, not synthetic series: float
products of a fitted slope rarely land exactly on a threshold, and D-89 says equality
fires.
"""

from __future__ import annotations

import pytest

from lancet_eval import decay
from lancet_eval.decay_materiality import (
    analyze_material_decay,
    evaluate_material_decay,
)
from lancet_eval.flatness import FlatnessRecord, SoakNodeFailure, SoakNodeTiming
from lancet_eval.thresholds import (
    COMMITTED_DECAY_THRESHOLDS_06341,
    COMMITTED_THRESHOLDS,
    MaterialDecayThresholds,
    ThresholdError,
)


def _verdict(
    *,
    slope: float = 0.0,
    significant: bool = False,
    early_p95: float = 200.0,
    delta: float = 0.0,
    trend_available: bool = True,
    window_available: bool = True,
    censored: int = 0,
) -> decay.DecayVerdict:
    trend = decay.TrendResult(
        slope=slope,
        p_value=0.001 if significant else 0.9,
        is_significant=significant,
        is_censored=censored > 0,
        censored_count=censored,
        is_available=trend_available,
        reason="hand-built",
    )
    window = decay.WindowComparisonResult(
        early_window_size=80 if window_available else 0,
        early_percentile_ms=early_p95 if window_available else 0.0,
        late_window_size=80 if window_available else 0,
        late_percentile_ms=(early_p95 + delta) if window_available else 0.0,
        delta_ms=delta if window_available else 0.0,
        materiality_threshold_ms=500.0,
        is_materially_elevated=False,
        is_censored=censored > 0,
        censored_count=censored,
        is_available=window_available,
        reason="hand-built",
    )
    return decay.DecayVerdict(
        verdict_decay_present=False,
        prong_slope_fired=False,
        prong_window_fired=False,
        slope_statistic=slope,
        slope_threshold=0.05,
        window_delta_ms=delta if window_available else 0.0,
        window_threshold_ms=500.0,
        trend_result=trend,
        window_result=window,
        restart_result=None,
    )


# --- the committed D-89 set ----------------------------------------------------


def test_d89_set_carries_the_user_decided_numbers():
    rule = COMMITTED_DECAY_THRESHOLDS_06341

    assert rule.projection_horizon_records == 658
    assert rule.relative_materiality_fraction == 0.25
    assert rule.materiality_floor_ms == 25.0
    assert rule.base is COMMITTED_THRESHOLDS
    assert "D-89" in rule.provenance
    assert "D-64" in rule.provenance
    rule.validate()


def test_06_3_3_committed_thresholds_stay_byte_identical():
    # D-89 / D-64: 06.3.3's serialized decision inputs must not move.
    assert COMMITTED_THRESHOLDS.to_dict() == {
        "multiplier": 1.5,
        "derivation_percentile": 0.95,
        "decay_significance_threshold": 0.05,
        "materiality_delta_ms": 500.0,
        "window_fractions": [0.25, 0.25],
        "segment_boundary_sizes": [30, 30],
        "min_stratum_cell_size": 10,
        "max_tolerated_graph_timeout_rate": 0.10,
        "bootstrap_seed": 42,
        "slack_ms": 500.0,
        "provenance": (
            "Committed decision inputs per Phase 06.3.3: D-14 (multiplier=1.5, p95), "
            "D-18/D-19 (decay alpha=0.05, delta=500ms, window fractions 25%/25%), "
            "D-21 (segment boundary sizes 30/30), AI-SPEC bootstrap seed=42, "
            "min stratum cell size=10, max tolerated graph timeout rate=0.10, "
            "nesting invariant slack=500ms."
        ),
    }


def test_materiality_threshold_is_max_of_fraction_and_floor():
    rule = COMMITTED_DECAY_THRESHOLDS_06341

    assert rule.materiality_threshold_ms(200.0) == 50.0
    assert rule.materiality_threshold_ms(199.0) == 49.75
    assert rule.materiality_threshold_ms(80.0) == 25.0
    assert rule.materiality_threshold_ms(10.0) == 25.0


@pytest.mark.parametrize(
    ("horizon", "fraction", "floor"),
    [(0, 0.25, 25.0), (658, 0.0, 25.0), (658, 1.0, 25.0), (658, 0.25, -1.0)],
)
def test_material_decay_thresholds_validate_rejects_bad_inputs(
    horizon, fraction, floor
):
    bad = MaterialDecayThresholds(
        base=COMMITTED_THRESHOLDS,
        projection_horizon_records=horizon,
        relative_materiality_fraction=fraction,
        materiality_floor_ms=floor,
        provenance="test",
    )

    with pytest.raises(ThresholdError):
        bad.validate()


# --- boundary cases on hand-built verdicts --------------------------------------


def test_window_prong_fires_at_exact_equality_and_not_below():
    # early p95 200 ms -> threshold 50 ms.
    at_boundary = evaluate_material_decay(_verdict(early_p95=200.0, delta=50.0))
    below = evaluate_material_decay(_verdict(early_p95=200.0, delta=49.9))

    assert at_boundary.window_prong_fired is True
    assert at_boundary.decay_present is True
    assert at_boundary.materiality_threshold_ms == 50.0
    assert below.window_prong_fired is False
    assert below.decay_present is False


def test_window_prong_floor_governs_a_fast_node():
    # early p95 80 ms -> 25% is 20 ms, so the 25 ms floor applies.
    at_floor = evaluate_material_decay(_verdict(early_p95=80.0, delta=25.0))
    below_floor = evaluate_material_decay(_verdict(early_p95=80.0, delta=24.9))

    assert at_floor.materiality_threshold_ms == 25.0
    assert at_floor.window_prong_fired is True
    assert below_floor.window_prong_fired is False


def test_slope_prong_fires_at_exact_projected_boundary():
    # early p95 2632 ms -> threshold 658 ms; slope 1.0 ms/query projects exactly 658 ms.
    at_boundary = evaluate_material_decay(
        _verdict(slope=1.0, significant=True, early_p95=2632.0)
    )
    below = evaluate_material_decay(
        _verdict(slope=0.999, significant=True, early_p95=2632.0)
    )

    assert at_boundary.materiality_threshold_ms == 658.0
    assert at_boundary.projected_growth_ms == 658.0
    assert at_boundary.slope_prong_fired is True
    assert at_boundary.decay_present is True
    assert below.slope_prong_fired is False
    assert below.decay_present is False


def test_slope_prong_needs_significance():
    # 10 ms/query would project 6580 ms, but the trend is not significant.
    verdict = evaluate_material_decay(
        _verdict(slope=10.0, significant=False, early_p95=200.0)
    )

    assert verdict.slope_prong_available is True
    assert verdict.slope_prong_fired is False
    assert verdict.decay_present is False


def test_significant_negative_slope_does_not_fire():
    verdict = evaluate_material_decay(
        _verdict(slope=-5.0, significant=True, early_p95=200.0)
    )

    assert verdict.slope_prong_fired is False
    assert verdict.decay_present is False


def test_pass_a_shaped_slope_is_below_threshold():
    # BUDGETS' figures: slope +0.0330 ms/query, early p95 199.0 -> 21.7 ms < 49.75 ms.
    verdict = evaluate_material_decay(
        _verdict(slope=0.0330, significant=True, early_p95=199.0, delta=-6.0)
    )

    assert verdict.projected_growth_ms == pytest.approx(0.0330 * 658)
    assert verdict.materiality_threshold_ms == 49.75
    assert verdict.decay_present is False


def test_unavailable_window_makes_both_prongs_unavailable_never_flat():
    # A huge significant slope must not leak through when the window prong is
    # unavailable: the threshold cannot be computed without the early-window p95.
    verdict = evaluate_material_decay(
        _verdict(
            slope=50.0,
            significant=True,
            window_available=False,
            censored=1,
            trend_available=False,
        )
    )

    assert verdict.slope_prong_available is False
    assert verdict.window_prong_available is False
    assert verdict.materiality_threshold_ms is None
    assert verdict.decay_present is False
    assert verdict.reason == "unavailable"
    assert verdict.censored_count == 1


def test_window_unavailable_with_trend_available_still_reads_unavailable():
    verdict = evaluate_material_decay(
        _verdict(slope=50.0, significant=True, window_available=False)
    )

    assert verdict.slope_prong_available is False
    assert verdict.window_prong_available is False
    assert verdict.materiality_threshold_ms is None
    assert verdict.slope_prong_fired is False


# --- analyze_material_decay on record sets --------------------------------------


def _flat(n: int = 40, duration_ms: float = 100.0) -> list[FlatnessRecord]:
    return [
        FlatnessRecord(
            ordinal=i,
            node_timings=[
                SoakNodeTiming(node_name="RetrieveHybrid", duration_ms=duration_ms)
            ],
        )
        for i in range(1, n + 1)
    ]


def test_analyze_material_decay_flat_series_is_available_and_not_present():
    verdict = analyze_material_decay(_flat(40, 100.0))

    assert verdict.slope_prong_available is True
    assert verdict.window_prong_available is True
    assert verdict.decay_present is False
    assert verdict.reason == "flat"
    assert verdict.materiality_threshold_ms == 25.0
    assert verdict.rule_provenance == COMMITTED_DECAY_THRESHOLDS_06341.provenance


def test_analyze_material_decay_growing_series_is_present():
    records = [
        FlatnessRecord(
            ordinal=i,
            node_timings=[
                SoakNodeTiming(node_name="RetrieveHybrid", duration_ms=100.0 + i * 5.0)
            ],
        )
        for i in range(1, 41)
    ]

    verdict = analyze_material_decay(records)

    assert verdict.decay_present is True
    assert verdict.slope_prong_fired is True
    assert verdict.window_prong_fired is True
    assert verdict.reason == "decay_present"


def test_analyze_material_decay_censored_set_is_unavailable_not_flat():
    records = _flat(40, 100.0)
    records[10] = FlatnessRecord(
        ordinal=11,
        node_failures=[SoakNodeFailure(node_name="RetrieveHybrid", error_kind=1)],
    )

    verdict = analyze_material_decay(records)

    assert verdict.slope_prong_available is False
    assert verdict.window_prong_available is False
    assert verdict.decay_present is False
    assert verdict.reason == "unavailable"
    assert verdict.censored_count == 1


def test_analyze_material_decay_empty_and_tiny_sets_are_unavailable():
    for records in ([], _flat(3), _flat(7)):
        verdict = analyze_material_decay(records)

        assert verdict.window_prong_available is False
        assert verdict.slope_prong_available is False
        assert verdict.decay_present is False
        assert verdict.reason == "unavailable"
