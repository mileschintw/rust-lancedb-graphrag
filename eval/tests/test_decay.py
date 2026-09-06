"""Tests for decay detection, Theil-Sen slope, windowing, and restart checks."""

import pytest

from lancet_eval.decay import (
    DecayAnalysisError,
    analyze_decay,
    compute_theil_sen_trend,
    evaluate_restart_boundary,
    validate_and_sort_records,
)
from lancet_eval.journal import NodeTiming
from lancet_eval.measure import MeasurementRecord
from lancet_eval.thresholds import COMMITTED_THRESHOLDS, DecisionThresholds


def test_ordering_validation_shuffled_lines_accepted():
    """Assert entry point sorts by ordinal first: accepts shuffled, refuses gaps."""
    rec1 = MeasurementRecord(
        corpus="m",
        question_id="q1",
        graph_arm="on",
        ordinal=1,
        segment="s1",
        outcome="success",
    )
    rec2 = MeasurementRecord(
        corpus="m",
        question_id="q2",
        graph_arm="on",
        ordinal=2,
        segment="s1",
        outcome="success",
    )
    rec3 = MeasurementRecord(
        corpus="m",
        question_id="q3",
        graph_arm="on",
        ordinal=3,
        segment="s1",
        outcome="success",
    )

    # Shuffled order: [rec3, rec1, rec2]
    shuffled = [rec3, rec1, rec2]
    sorted_recs = validate_and_sort_records(shuffled)
    assert [r.ordinal for r in sorted_recs] == [1, 2, 3]

    # Duplicate ordinal
    rec_dup = MeasurementRecord(
        corpus="m",
        question_id="q4",
        graph_arm="on",
        ordinal=2,
        segment="s1",
        outcome="success",
    )
    with pytest.raises(DecayAnalysisError) as exc_dup:
        validate_and_sort_records([rec1, rec2, rec_dup])
    assert "Duplicate ordinal detected" in str(exc_dup.value)

    # Gap in ordinals (1, 3 - missing 2)
    with pytest.raises(DecayAnalysisError) as exc_gap:
        validate_and_sort_records([rec1, rec3])
    assert "Gap in ordinals detected" in str(exc_gap.value)


def test_synthetic_upward_trend_detection(synthetic_upward_latencies):
    """Assert known positive slope produces significant positive estimate."""
    ordinals = list(range(1, len(synthetic_upward_latencies) + 1))
    trend = compute_theil_sen_trend(
        ordinals, synthetic_upward_latencies, thresholds=COMMITTED_THRESHOLDS
    )
    assert trend.slope > 1.5
    assert trend.is_significant is True
    assert trend.p_value < COMMITTED_THRESHOLDS.decay_significance_threshold


def test_synthetic_flat_trend_detection(synthetic_flat_latencies):
    """Assert flat latencies produce slope near zero and no decay verdict."""
    ordinals = list(range(1, len(synthetic_flat_latencies) + 1))
    trend = compute_theil_sen_trend(
        ordinals, synthetic_flat_latencies, thresholds=COMMITTED_THRESHOLDS
    )
    assert abs(trend.slope) < 0.5
    assert trend.is_significant is False


def test_verdict_pure_function_of_committed_thresholds(synthetic_upward_latencies):
    """Assert same observations under different committed thresholds vary verdicts."""
    records = [
        MeasurementRecord(
            corpus="m",
            question_id=f"q{i}",
            graph_arm="graph-on",
            ordinal=i,
            segment="segment-1",
            outcome="success",
            question_type="multi_hop",
            node_timings=[NodeTiming(node_name="RetrieveHybrid", duration_ms=lat)],
        )
        for i, lat in enumerate(synthetic_upward_latencies, 1)
    ]

    # Threshold A: standard alpha 0.05, materiality delta 500ms
    v_a = analyze_decay(records, thresholds=COMMITTED_THRESHOLDS)

    # Threshold B: extremely strict significance threshold and massive materiality delta
    strict_thresh = DecisionThresholds(
        multiplier=1.5,
        derivation_percentile=0.95,
        decay_significance_threshold=1e-60,  # below float-precise p-value for n=100
        materiality_delta_ms=50000.0,  # massive materiality
        window_fractions=(0.25, 0.25),
        segment_boundary_sizes=(30, 30),
        min_stratum_cell_size=10,
        max_tolerated_graph_timeout_rate=0.10,
    )
    v_b = analyze_decay(records, thresholds=strict_thresh)

    assert v_a.verdict_decay_present is True
    assert v_b.verdict_decay_present is False
    # Names statistic value, threshold, and outcome for prongs
    assert v_a.slope_statistic == v_b.slope_statistic
    assert v_a.slope_threshold != v_b.slope_threshold


def test_censored_set_refused_or_flagged_never_flat(synthetic_all_at_ceiling_latencies):
    """Assert all-at-ceiling set is refused or flagged, never reported as flat."""
    ordinals = list(range(1, len(synthetic_all_at_ceiling_latencies) + 1))
    trend = compute_theil_sen_trend(
        ordinals,
        synthetic_all_at_ceiling_latencies,
        censored_count=len(synthetic_all_at_ceiling_latencies),
    )
    assert trend.is_censored is True
    assert not trend.is_available
    assert "saturated instrument" in trend.reason


def test_restart_discriminator_spans_zero_inconclusive():
    """Assert boundary discriminator returns inconclusive when CI spans zero."""
    seg1 = [190.0, 210.0] * 20
    seg2 = [190.0, 210.0] * 20
    res = evaluate_restart_boundary(seg1, seg2, thresholds=COMMITTED_THRESHOLDS)
    assert res.hypothesis == "inconclusive"
    assert "spans zero" in res.reason


def test_restart_discriminator_boundary_validations():
    """Assert discriminator refuses invalid segment labels or out of bounds restart."""
    # 3 segments
    recs_3_seg = [
        MeasurementRecord(
            corpus="m",
            question_id="q1",
            graph_arm="on",
            ordinal=1,
            segment="s1",
            outcome="success",
        ),
        MeasurementRecord(
            corpus="m",
            question_id="q2",
            graph_arm="on",
            ordinal=2,
            segment="s2",
            outcome="success",
        ),
        MeasurementRecord(
            corpus="m",
            question_id="q3",
            graph_arm="on",
            ordinal=3,
            segment="s1",
            outcome="success",
        ),
    ]
    with pytest.raises(DecayAnalysisError) as exc_seg:
        analyze_decay(recs_3_seg)
    assert "Segment labels change more than once" in str(exc_seg.value)

    # Restart ordinal out of bounds
    recs_ok = [
        MeasurementRecord(
            corpus="m",
            question_id="q1",
            graph_arm="on",
            ordinal=1,
            segment="s1",
            outcome="success",
        ),
        MeasurementRecord(
            corpus="m",
            question_id="q2",
            graph_arm="on",
            ordinal=2,
            segment="s2",
            outcome="success",
        ),
    ]
    with pytest.raises(DecayAnalysisError) as exc_ord:
        analyze_decay(recs_ok, restart_ordinal=999)
    assert "outside observed boundary" in str(exc_ord.value)


def test_stratification_reads_question_type_from_record():
    """Assert stratification reads stamped question_type and handles empty stratum."""
    recs = [
        MeasurementRecord(
            corpus="m",
            question_id="q1",
            graph_arm="graph-on",
            ordinal=1,
            segment="segment-1",
            outcome="success",
            question_type="bridge",
            node_timings=[NodeTiming(node_name="RetrieveHybrid", duration_ms=120.0)],
        ),
        MeasurementRecord(
            corpus="m",
            question_id="q2",
            graph_arm="graph-off",
            ordinal=2,
            segment="segment-1",
            outcome="success",
            question_type="comparison",
            node_timings=[NodeTiming(node_name="RetrieveHybrid", duration_ms=110.0)],
        ),
    ]
    verdict = analyze_decay(recs)
    assert "graph-on:bridge" in verdict.stratified_results
    assert "graph-off:comparison" in verdict.stratified_results
    assert verdict.stratified_results["graph-on:bridge"]["observation_count"] == 1
