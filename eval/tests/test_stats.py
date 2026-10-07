"""Tests for stats.py: the exact paired sign-flip and Holm step-down (D-123)."""

from __future__ import annotations

import ast
import random
from fractions import Fraction
from pathlib import Path

import pytest

from lancet_eval.stats import exact_signflip_p, holm_stepdown


def test_five_to_nothing_is_one_sixteenth() -> None:
    assert exact_signflip_p(5, 0) == Fraction(1, 16)


def test_no_discordant_pairs_gives_one() -> None:
    assert exact_signflip_p(0, 0) == 1


def test_a_perfectly_balanced_split_gives_one() -> None:
    assert exact_signflip_p(3, 3) == 1
    assert exact_signflip_p(20, 20) == 1


def test_the_p_value_is_symmetric_in_its_arguments() -> None:
    for pos, neg in [(12, 3), (30, 18), (9, 2), (5, 0)]:
        assert exact_signflip_p(pos, neg) == exact_signflip_p(neg, pos)


def test_hand_values() -> None:
    # nd=3, all one way: P(|S| >= 3) = 2/8
    assert exact_signflip_p(3, 0) == Fraction(1, 4)
    # nd=4, 3 vs 1: |S| = 2; P(|S| >= 2) = (C(4,0)+C(4,1)+C(4,3)+C(4,4))/16 = 10/16
    assert exact_signflip_p(3, 1) == Fraction(5, 8)


def test_the_result_is_an_exact_fraction() -> None:
    assert isinstance(exact_signflip_p(12, 3), Fraction)


def test_negative_counts_raise() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        exact_signflip_p(-1, 3)
    with pytest.raises(ValueError, match="non-negative"):
        exact_signflip_p(3, -1)


def _monte_carlo_p(
    n_pos: int, n_neg: int, flips: int = 10_000, seed: int = 42
) -> float:
    """The cross-check only: a seeded Monte Carlo sign-flip (not in stats.py)."""
    d = [1] * n_pos + [-1] * n_neg
    s_obs = abs(sum(d))
    rng = random.Random(seed)
    count = 0
    for _ in range(flips):
        s = sum(x if rng.random() < 0.5 else -x for x in d)
        count += abs(s) >= s_obs
    return (1 + count) / (1 + flips)


@pytest.mark.parametrize("pos,neg", [(12, 3), (30, 18), (20, 20), (9, 2)])
def test_exact_p_agrees_with_a_monte_carlo_sign_flip_within_three_se(
    pos: int, neg: int
) -> None:
    exact = float(exact_signflip_p(pos, neg))
    mc = _monte_carlo_p(pos, neg)
    se = (exact * (1 - exact) / 10_000) ** 0.5
    # A (1 + count) / (1 + B) estimate carries a 1/(B+1) offset; allow it as well.
    assert abs(mc - exact) <= 3 * se + 1 / 10_001


def test_holm_rejects_all_three_and_adjusts() -> None:
    reject, adjusted = holm_stepdown([0.001, 0.02, 0.04])
    assert reject == [True, True, True]
    assert adjusted == pytest.approx([0.003, 0.04, 0.04])


def test_holm_with_ties_rejects_none_and_orders_by_position() -> None:
    reject, adjusted = holm_stepdown([0.02, 0.02, 0.9])
    assert reject == [False, False, False]
    # (3-0)*0.02, (3-1)*0.02, (3-2)*0.9 with the running max
    assert adjusted == pytest.approx([0.06, 0.06, 0.9])


def test_holm_maps_decisions_back_to_input_positions() -> None:
    reject, adjusted = holm_stepdown([0.04, 0.001, 0.02])
    assert reject == [True, True, True]
    assert adjusted == pytest.approx([0.04, 0.003, 0.04])


def test_holm_stops_at_the_first_failure() -> None:
    # 0.001 passes (<= 0.05/3); 0.03 fails (> 0.05/2); 0.04 is then retained
    # even though 0.04 <= 0.05.
    reject, _ = holm_stepdown([0.001, 0.03, 0.04])
    assert reject == [True, False, False]


def test_holm_adjusted_p_is_capped_at_one() -> None:
    _, adjusted = holm_stepdown([0.6, 0.7, 0.9])
    assert adjusted == pytest.approx([1.0, 1.0, 1.0])


def test_holm_empty_family() -> None:
    assert holm_stepdown([]) == ([], [])


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1, 1.5])
def test_holm_rejects_an_alpha_outside_the_open_unit_interval(alpha: float) -> None:
    with pytest.raises(ValueError, match="alpha"):
        holm_stepdown([0.01], alpha=alpha)


def test_holm_rejects_a_p_value_outside_the_unit_interval() -> None:
    with pytest.raises(ValueError, match="p-value"):
        holm_stepdown([0.01, 1.2])


def test_stats_stays_stdlib_only() -> None:
    import lancet_eval.stats as stats_mod

    tree = ast.parse(Path(stats_mod.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots <= {
        "__future__",
        "math",
        "collections",
        "fractions",
        "random",
        "statistics",
    }
