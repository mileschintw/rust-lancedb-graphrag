"""Tests for latency percentiles, bootstrap CI, derivation, and nesting."""

import random

import pytest

from lancet_eval.latency import (
    check_harness_ceilings,
    check_nesting_invariants,
    derive_budget,
    derive_provider_contract_budget,
    guard_graph_operation_percentile,
    percentile_with_ci,
    required_sample_size,
)
from lancet_eval.thresholds import (
    COMMITTED_THRESHOLDS,
    ThresholdError,
)


def test_bootstrap_determinism_and_reproducibility():
    """Assert identical bounds on repeated calls and after re-seeding."""
    data = [100.0, 150.0, 200.0, 250.0, 300.0, 350.0, 400.0, 450.0]
    res1 = percentile_with_ci(data, p=0.95, seed=42)
    res2 = percentile_with_ci(data, p=0.95, seed=42)
    assert res1.percentile == res2.percentile
    assert res1.ci_low == res2.ci_low
    assert res1.ci_high == res2.ci_high


def test_bootstrap_isolation_from_global_random():
    """Assert computing percentile does not disturb global random sequence."""
    random.seed(999)
    draw1_before = random.random()
    draw2_before = random.random()

    # Reset global seed to 999
    random.seed(999)
    d1 = random.random()
    assert d1 == draw1_before

    # Compute percentile (uses local Random(42))
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    percentile_with_ci(data, p=0.95, seed=42)

    # Next global draw should match draw2_before exactly
    d2 = random.random()
    assert d2 == draw2_before


def test_interval_ordering():
    """Assert ci_low <= point_estimate <= ci_high for sample."""
    data = [50.0, 80.0, 120.0, 130.0, 190.0, 220.0, 310.0, 450.0]
    res = percentile_with_ci(data, p=0.95, ci=0.95, seed=42)
    assert res.ci_low <= res.percentile <= res.ci_high


def test_small_sample_and_empty_outcomes():
    """Assert small samples produce stated-reason outcome and empty returns 0 count."""
    # Empty
    res_empty = percentile_with_ci([], p=0.95)
    assert res_empty.sample_size == 0
    assert not res_empty.is_available
    assert len(res_empty.reason) > 0

    # Single observation
    res_single = percentile_with_ci([123.0], p=0.95)
    assert res_single.sample_size == 1
    assert res_single.percentile == 123.0
    assert res_single.is_degenerate is True

    # n < min_sample_size (e.g. min_sample_size=5)
    res_small = percentile_with_ci([10.0, 20.0], p=0.95, min_sample_size=5)
    assert not res_small.is_available
    assert "below minimum" in res_small.reason


def test_censoring_propagates_to_percentile():
    """Assert percentile over censored set is flagged as lower bound."""
    data = [100.0, 200.0, 300.0]
    res = percentile_with_ci(data, p=0.95, censored_count=5)
    assert res.is_lower_bound is True
    assert res.censored_count == 5
    assert "censored lower bound" in res.reason

    # Refusal mode
    res_refused = percentile_with_ci(
        data, p=0.95, censored_count=2, refuse_on_censored=True
    )
    assert not res_refused.is_available
    assert "Refused" in res_refused.reason


def test_provider_contract_generation_budget():
    """Assert generation budget satisfies engine provider rule with provenance."""
    attempt_count = 2
    per_attempt_s = 30.0
    slack_s = 5.0
    rec = derive_provider_contract_budget(
        provider_attempt_count=attempt_count,
        per_attempt_timeout_s=per_attempt_s,
        slack_s=slack_s,
    )
    # Engine rule: generation_node >= 2 * generation_timeout_secs * 1000
    engine_floor_ms = attempt_count * int(per_attempt_s * 1000)
    assert rec.proposed_ms >= engine_floor_ms
    assert "Provider contract" in rec.provenance
    assert rec.sample_size == 0


def test_derivation_refuses_without_committed_multiplier():
    """Assert derive_budget refuses when no multiplier is provided."""
    pct = percentile_with_ci([100.0, 200.0, 300.0], p=0.95)
    with pytest.raises(ThresholdError):
        derive_budget("retrieve_timeout_ms", pct, thresholds=None)


def test_proposed_budget_recomputes_from_recorded_inputs():
    """Assert proposed budget recomputes identically from its own recorded fields."""
    pct = percentile_with_ci([100.0, 200.0, 300.0], p=0.95)
    rec = derive_budget("retrieve_timeout_ms", pct, thresholds=COMMITTED_THRESHOLDS)
    recomputed = rec.recompute()
    assert recomputed == rec.proposed_ms


def test_full_nesting_report_and_conflict_resolution():
    """Assert nesting report identifies violations and raises enclosing budget."""
    # Under-configured outer budget:
    # graph_node=12000 < query_embedding(10000) + graph_operation(4000) = 14000
    budgets = {
        "graph_node_timeout_ms": 12000,
        "query_embedding_timeout_ms": 10000,
        "graph_operation_timeout_ms": 4000,
        "retrieve_timeout_ms": 15000,
        "prompt_timeout_ms": 2000,
        "generation_node_timeout_ms": 65000,
    }
    rep = check_nesting_invariants(budgets, required_slack_ms=500.0)
    assert rep.has_violations is True
    # Enumerates multiple groups (count > 1)
    assert len(rep.groups) > 1

    # Conflict resolution: outer raised to inner_sum(14000) + slack(500) = 14500
    resolved = rep.resolved_budgets
    assert resolved["graph_node_timeout_ms"] == 14500
    # Inner budgets untouched
    assert resolved["query_embedding_timeout_ms"] == 10000
    assert resolved["graph_operation_timeout_ms"] == 4000

    # Verify invariant-driven flag on group
    graph_grp = next(g for g in rep.groups if g.outer_name == "graph_node_timeout_ms")
    assert graph_grp.is_invariant_driven is True
    assert graph_grp.is_violation is True


def test_nesting_report_equality_is_violation():
    """Assert nesting report flags equality between enclosing and inner sum."""
    # Enclosing equals inner sum exactly (14000 == 10000 + 4000)
    budgets = {
        "graph_node_timeout_ms": 14000,
        "query_embedding_timeout_ms": 10000,
        "graph_operation_timeout_ms": 4000,
        "retrieve_timeout_ms": 15000,
    }
    rep = check_nesting_invariants(budgets, required_slack_ms=500.0)
    graph_grp = next(g for g in rep.groups if g.outer_name == "graph_node_timeout_ms")
    assert graph_grp.is_violation is True
    assert rep.resolved_budgets["graph_node_timeout_ms"] == 14500


def test_two_ceiling_report_mirror_cases():
    """Assert two ceilings flags max-vs-read and sum-vs-deadline independently."""
    # Exceeds read timeout only
    b1 = {"retrieve_timeout_ms": 305000, "prompt_timeout_ms": 1000}
    r1 = check_harness_ceilings(b1, sse_read_timeout_s=300.0, question_deadline_s=600.0)
    assert r1.single_exceeds_read_timeout is True
    assert r1.sum_exceeds_deadline is False

    # Exceeds deadline only
    b2 = {
        "retrieve_timeout_ms": 250000,
        "graph_node_timeout_ms": 250000,
        "generation_node_timeout_ms": 150000,
    }
    r2 = check_harness_ceilings(b2, sse_read_timeout_s=300.0, question_deadline_s=600.0)
    assert r2.single_exceeds_read_timeout is False
    assert r2.sum_exceeds_deadline is True


def test_required_sample_size_calculation():
    """Assert required_sample_size returns minimum count keeping cells >= min."""
    req = required_sample_size(
        min_stratum_cell_size=10,
        num_arms=2,
        num_question_types=2,
        num_segments=2,
        num_windows=2,
    )
    # Cells per arm = 2 * 2 * 2 = 8 cells. Min questions = 10 * 8 = 80 questions
    assert req.min_questions == 80
    assert req.min_cell_size == 10
    assert "arm" in req.binding_cell

    with pytest.raises(ThresholdError):
        required_sample_size(min_stratum_cell_size=0)


def test_graph_timeout_survivor_guard():
    """Assert graph percentile is censored lower bound when rate > threshold."""
    data = [200.0, 350.0, 500.0]
    # Rate 0.25 > threshold 0.10 -> survivor guard trips
    res_censored = guard_graph_operation_percentile(
        data, graph_timeout_rate=0.25, max_tolerated_rate=0.10
    )
    assert res_censored.is_lower_bound is True
    assert "Survivor guard tripped" in res_censored.reason

    # Rate 0.05 <= threshold 0.10 -> derivable percentile
    res_clean = guard_graph_operation_percentile(
        data, graph_timeout_rate=0.05, max_tolerated_rate=0.10
    )
    assert res_clean.is_lower_bound is False
    assert res_clean.is_available is True
