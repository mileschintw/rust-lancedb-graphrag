"""Tests for DimensionResult validation and registry."""

import pytest
from pydantic import ValidationError

from lancet_eval.dimensions import (
    DIMENSION_REGISTRY,
    OBS_04_PLACEHOLDER,
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


def test_dimension_result_skipped_with_score_raises() -> None:
    with pytest.raises(
        ValidationError, match="status 'skipped' cannot carry a score"
    ):
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
