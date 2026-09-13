"""Tests for DimensionResult validation and registry."""

import pytest
from pydantic import ValidationError

from lancet_eval.dimensions import (
    DIMENSION_REGISTRY,
    OBS_04_PLACEHOLDER,
    REGISTERED_DIMENSIONS,
    DimensionResult,
)


def test_dimension_result_valid_ok() -> None:
    dim = DimensionResult(name="test_dim", status="ok", score=0.42)
    assert dim.name == "test_dim"
    assert dim.status == "ok"
    assert dim.score == 0.42
    assert dim.reason is None


def test_dimension_result_ok_without_score_raises() -> None:
    with pytest.raises(ValidationError, match="status 'ok' requires a score"):
        DimensionResult(name="test_dim", status="ok")


def test_dimension_result_ok_with_reason_raises() -> None:
    with pytest.raises(ValidationError, match="status 'ok' cannot have a reason"):
        DimensionResult(
            name="test_dim",
            status="ok",
            score=0.85,
            reason="forbidden reason",
        )


def test_dimension_result_skipped_with_score_raises() -> None:
    with pytest.raises(ValidationError, match="status 'skipped' cannot carry a score"):
        DimensionResult(
            name="test_dim",
            status="skipped",
            score=0.0,
            reason="Skipped reason",
        )


def test_dimension_result_skipped_without_reason_raises() -> None:
    with pytest.raises(
        ValidationError, match="status 'skipped' requires a non-blank reason"
    ):
        DimensionResult(name="test_dim", status="skipped")


def test_dimension_result_error_with_blank_reason_raises() -> None:
    with pytest.raises(
        ValidationError, match="status 'error' requires a non-blank reason"
    ):
        DimensionResult(name="test_dim", status="error", reason="   ")


def test_dimension_result_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DimensionResult(
            name="test_dim",  # type: ignore[call-arg]
            status="ok",
            score=1.0,
            bogus_field=123,  # type: ignore[call-arg]
        )


def test_registered_dimensions_inventory() -> None:
    expected = [
        "unusable_record_rate",
        "vector_yield",
        "bm25_yield",
        "retrieve_latency_ms",
        "graph_presence_rate",
        "graph_influence_rate",
        "graph_latency_ms",
        "retrieval_evidence_coverage",
        "context_precision_at_k",
        "ranking_quality",
        "answer_exact_match",
        "answer_f1",
        "answer_faithfulness",
        "answer_groundedness",
        "graph_ablation_delta",
        "abstention_on_unanswerable",
        "wire_contract_conformance",
        "community_summary_quality",
        "run_traceability",
    ]
    for dim in expected:
        assert dim in REGISTERED_DIMENSIONS


def test_obs_04_placeholder_registered() -> None:

    assert "community_summary_quality" in DIMENSION_REGISTRY
    built = DIMENSION_REGISTRY["community_summary_quality"]()
    assert built.name == "community_summary_quality"
    assert built.status == "skipped"
    assert built.score is None
    assert built.detail == {}
    assert built.reason is not None
    assert "999.1" in built.reason
    assert OBS_04_PLACEHOLDER.status == "skipped"


def test_in02_graph_yield_investigation_floor_relocated() -> None:
    """Proves GRAPH_YIELD_INVESTIGATION_FLOOR is defined in thresholds and re-exported."""
    import lancet_eval.dimensions as D
    import lancet_eval.gate as G
    import lancet_eval.thresholds as T

    assert hasattr(T, "GRAPH_YIELD_INVESTIGATION_FLOOR")
    assert G.GRAPH_YIELD_INVESTIGATION_FLOOR is T.GRAPH_YIELD_INVESTIGATION_FLOOR
    assert D.GRAPH_YIELD_INVESTIGATION_FLOOR is T.GRAPH_YIELD_INVESTIGATION_FLOOR
    assert T.GRAPH_YIELD_INVESTIGATION_FLOOR == 0.20


def test_judged_slice_state_constants_and_mapping() -> None:
    """Proves judged slice state constants and mapping exist with expected values."""
    from lancet_eval.dimensions import (
        JUDGED_SLICE_STATE_CAP_BOUND,
        JUDGED_SLICE_STATE_CAP_STOPPED,
        JUDGED_SLICE_STATE_COMPLETED,
        JUDGED_SLICE_STATE_NOT_JUDGED,
        JUDGED_SLICE_STATES,
    )

    expected = {
        JUDGED_SLICE_STATE_NOT_JUDGED: "not_judged",
        JUDGED_SLICE_STATE_COMPLETED: "completed",
        JUDGED_SLICE_STATE_CAP_BOUND: "cap_bound",
        JUDGED_SLICE_STATE_CAP_STOPPED: "cap_stopped",
    }
    assert JUDGED_SLICE_STATES == expected


def test_make_groundedness_and_faithfulness_results_carry_provenance() -> None:
    """Proves make_groundedness_result and make_faithfulness_result carry provenance in detail."""
    from lancet_eval.dimensions import (
        JUDGED_SLICE_STATE_CAP_BOUND,
        make_faithfulness_result,
        make_groundedness_result,
    )

    g_res = make_groundedness_result(
        verdicts=[5.0, 4.0],
        judge_errors=0,
        skipped_no_evidence=0,
        total_sampled=2,
        judged_slice_committed=5,
        verdicts_obtained=2,
        judged_slice_state=JUDGED_SLICE_STATE_CAP_BOUND,
    )
    assert g_res.detail["judged_slice_committed"] == 5.0
    assert g_res.detail["verdicts_obtained"] == 2.0
    assert g_res.detail["judged_slice_state"] == JUDGED_SLICE_STATE_CAP_BOUND

    f_res = make_faithfulness_result(
        verdicts=[4.0, 4.0],
        judge_errors=0,
        skipped_no_evidence=0,
        total_sampled=2,
        judged_slice_committed=5,
        verdicts_obtained=2,
        judged_slice_state=JUDGED_SLICE_STATE_CAP_BOUND,
    )
    assert f_res.detail["judged_slice_committed"] == 5.0
    assert f_res.detail["verdicts_obtained"] == 2.0
    assert f_res.detail["judged_slice_state"] == JUDGED_SLICE_STATE_CAP_BOUND


def test_make_groundedness_and_faithfulness_results_carry_usage_absent_fallback_count() -> None:
    """Proves make_groundedness_result and make_faithfulness_result carry usage_absent_fallback_count in detail and err_detail."""
    from lancet_eval.dimensions import (
        make_faithfulness_result,
        make_groundedness_result,
    )

    # Success case with verdicts
    g_res = make_groundedness_result(
        verdicts=[5.0],
        judge_errors=0,
        skipped_no_evidence=0,
        total_sampled=1,
        usage_absent_fallback_count=2,
    )
    assert g_res.detail["usage_absent_fallback_count"] == 2.0

    f_res = make_faithfulness_result(
        verdicts=[4.0],
        judge_errors=0,
        skipped_no_evidence=0,
        total_sampled=1,
        usage_absent_fallback_count=2.0,
    )
    assert f_res.detail["usage_absent_fallback_count"] == 2.0

    # Error case without verdicts
    g_err = make_groundedness_result(
        verdicts=[],
        judge_errors=1,
        skipped_no_evidence=0,
        total_sampled=1,
        usage_absent_fallback_count=1,
    )
    assert g_err.detail["usage_absent_fallback_count"] == 1.0

    f_err = make_faithfulness_result(
        verdicts=[],
        judge_errors=1,
        skipped_no_evidence=0,
        total_sampled=1,
        usage_absent_fallback_count=1.0,
    )
    assert f_err.detail["usage_absent_fallback_count"] == 1.0

    # Default (None) omits key
    g_def = make_groundedness_result(
        verdicts=[5.0],
        judge_errors=0,
        skipped_no_evidence=0,
        total_sampled=1,
    )
    assert "usage_absent_fallback_count" not in g_def.detail


