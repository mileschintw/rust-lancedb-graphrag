"""Tests for the 06.3.5 pre-registration constants and the D-73 ordering gates."""

from __future__ import annotations

import dataclasses

import pytest

from lancet_eval import thresholds


def test_the_preregistration_values_are_the_owner_decisions() -> None:
    pre = thresholds.PREREGISTRATION_06_3_5
    assert isinstance(pre, thresholds.AblationPreRegistration)
    assert pre.primaries == ("paper_hits_at_4", "answer_usable")
    assert pre.reference_arm == "hybrid"
    assert pre.comparison_arms == ("dense-only", "bm25-only", "hybrid+graph")
    assert pre.family == "per_primary"
    assert pre.family_alpha == 0.05
    assert pre.test == "paired_sign_flip_exact_two_sided"
    assert pre.population.startswith("P4")
    assert pre.matching_rule == "chunk_id_via_gold_chunks"
    assert pre.complete_case_floor == 0.80
    assert pre.bootstrap_b == 10_000
    assert pre.bootstrap_seed == 42


def test_the_preregistration_provenance_names_its_decisions() -> None:
    provenance = thresholds.PREREGISTRATION_06_3_5.provenance
    for token in ("D-111", "D-121", "D-122", "D-123", "2026-10-06"):
        assert token in provenance
    assert "never changed after data is seen" in provenance


def test_the_preregistration_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        thresholds.PREREGISTRATION_06_3_5.reference_arm = "dense-only"  # type: ignore[misc]


def test_the_primaries_and_bootstrap_agree_with_the_harness_constants() -> None:
    from lancet_eval import stats

    pre = thresholds.PREREGISTRATION_06_3_5
    assert pre.bootstrap_b == stats.BOOTSTRAP_B
    assert pre.bootstrap_seed == stats.BOOTSTRAP_SEED


def test_the_judge_and_calibration_constants() -> None:
    assert thresholds.JUDGE_QWK_TRUST_FLOOR == 0.70
    assert thresholds.CALIBRATION_MIN_SCORED_PAIRS == 16
    assert thresholds.CALIBRATION_DRAW_SEED == 42
    assert thresholds.JUDGE_ERROR_RATE_TRIPWIRE == 0.05
    assert thresholds.JUDGE_ERROR_TRIPWIRE_MIN_CALLS == 50
    assert thresholds.JUDGE_CONSECUTIVE_ERROR_HALT == 5


def test_the_trust_floor_keeps_continuity_with_the_legacy_target() -> None:
    from lancet_eval import gate

    # Continuity (D-119): the same number in a separate constant; gate.py is untouched.
    assert thresholds.JUDGE_QWK_TRUST_FLOOR == gate.AGREEMENT_TARGET
    assert gate.CALIBRATION_SIZE == 12
