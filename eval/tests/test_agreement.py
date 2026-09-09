"""Tests for quadratic weighted kappa and Spearman rank correlation."""

import inspect
import math
import random
import sys

import pytest

import lancet_eval.agreement as agreement_mod
from lancet_eval.agreement import (
    bootstrap_agreement_ci,
    compute_mid_ranks,
    quadratic_weighted_kappa,
    spearman_rank_correlation,
)


def test_no_third_party_imports() -> None:
    """Proves agreement.py imports only standard library modules."""
    with open(agreement_mod.__file__, encoding="utf-8") as f:
        tree_src = f.read()

    import ast

    parsed = ast.parse(tree_src)
    stdlib_modules = sys.stdlib_module_names

    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0]
                assert root_pkg in stdlib_modules, (
                    f"Non-stdlib import found: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_pkg = node.module.split(".")[0]
                assert root_pkg in stdlib_modules, (
                    f"Non-stdlib import found: {node.module}"
                )


def test_kappa_golden_vector_exact_rational() -> None:
    """Proves kappa matches exact theoretical Cohen (1968) calculation.

    For 3-category scale [1, 3] with ratings:
    rater1 = [1, 1, 2, 2, 3, 3]
    rater2 = [1, 2, 2, 3, 2, 3]
    Theoretical Po = 0.875, Pe = 0.70833333, (Po - Pe)/(1 - Pe) = 4/7.
    """
    rater1 = [1, 1, 2, 2, 3, 3]
    rater2 = [1, 2, 2, 3, 2, 3]

    res = quadratic_weighted_kappa(rater1, rater2, min_rating=1, max_rating=3)
    assert res.state == "computed"
    assert res.value is not None
    assert res.value == pytest.approx(4.0 / 7.0, abs=1e-6)


def test_spearman_golden_vector_with_ties_zar() -> None:
    """Proves Spearman rank correlation handles ties via mid-rank convention.

    Reference: Zar, J.H. (2010), Biostatistical Analysis, 5th ed.
    X = [1, 2, 3, 4, 5]
    Y = [5, 6, 7, 8, 7]
    Mid-ranks for ties (7, 7) are 3.5. Pearson correlation is 8 / sqrt(95).
    """
    x = [1, 2, 3, 4, 5]
    y = [5, 6, 7, 8, 7]

    res = spearman_rank_correlation(x, y)
    assert res.state == "computed"
    assert res.value is not None
    expected = 8.0 / math.sqrt(95.0)
    assert res.value == pytest.approx(expected, abs=1e-6)


def test_mid_rank_convention_correctness() -> None:
    """Proves compute_mid_ranks assigns average ranks to tied entries."""
    seq = [5, 1, 2, 2, 4]
    ranks = compute_mid_ranks(seq)
    # Expected: 1->1.0, 2->2.5, 2->2.5, 4->4.0, 5->5.0
    assert ranks == [5.0, 1.0, 2.5, 2.5, 4.0]


def test_perfect_chance_and_disagreement_kappa() -> None:
    """Proves perfect, chance, and disagreement kappa behaviors."""
    # Perfect agreement
    r1 = [1, 2, 3, 4, 5]
    r2 = [1, 2, 3, 4, 5]
    res_perf = quadratic_weighted_kappa(r1, r2, min_rating=1, max_rating=5)
    assert res_perf.state == "computed"
    assert res_perf.value == pytest.approx(1.0)

    # Systematic disagreement
    r_opp1 = [1, 1, 1, 1, 2, 2]
    r_opp2 = [5, 5, 5, 5, 4, 4]
    res_opp = quadratic_weighted_kappa(r_opp1, r_opp2, min_rating=1, max_rating=5)
    assert res_opp.state == "computed"
    assert res_opp.value is not None and res_opp.value < 0.0


def test_degenerate_kappa_vanished_expected_agreement() -> None:
    """Proves vanishing expected agreement returns undefined_expected_agreement."""
    # When both raters give only category 3, expected agreement is 1.0, 1 - Pe = 0.0
    r1 = [3, 3, 3, 3, 3]
    r2 = [3, 3, 3, 3, 3]
    res = quadratic_weighted_kappa(r1, r2, min_rating=1, max_rating=5)
    assert res.value is None
    assert res.state == "undefined_expected_agreement"


def test_degenerate_spearman_zero_variance() -> None:
    """Proves zero variance sequence returns undefined_zero_variance."""
    r1 = [3, 3, 3, 3, 3]
    r2 = [1, 2, 3, 4, 5]
    res = spearman_rank_correlation(r1, r2)
    assert res.value is None
    assert res.state == "undefined_zero_variance"


def test_no_nans_returned() -> None:
    """Proves neither function ever returns float('nan')."""
    fixtures = [
        ([1, 2, 3], [1, 2, 3]),
        ([3, 3, 3], [3, 3, 3]),
        ([1, 2, 3], [3, 2, 1]),
        ([1, 1, 2, 2], [2, 2, 1, 1]),
    ]
    for f1, f2 in fixtures:
        k_res = quadratic_weighted_kappa(f1, f2, min_rating=1, max_rating=5)
        if k_res.value is not None:
            assert not math.isnan(k_res.value)
        s_res = spearman_rank_correlation(f1, f2)
        if s_res.value is not None:
            assert not math.isnan(s_res.value)


def test_scale_bounds_signature_and_enforcement() -> None:
    """Proves kappa takes scale bounds as arguments and enforces them."""
    sig = inspect.signature(quadratic_weighted_kappa)
    assert "min_rating" in sig.parameters
    assert "max_rating" in sig.parameters
    assert sig.parameters["min_rating"].default == 1
    assert sig.parameters["max_rating"].default == 5

    # Out of bounds raises
    with pytest.raises(ValueError, match="out of bounds"):
        quadratic_weighted_kappa([1, 4], [1, 4], min_rating=1, max_rating=3)

    # Valid within bounds computes
    res = quadratic_weighted_kappa([1, 3], [1, 3], min_rating=1, max_rating=3)
    assert res.state == "computed"
    assert res.value == pytest.approx(1.0)


def test_permutation_invariance() -> None:
    """Proves both functions invariant when sequences permuted together."""
    r1 = [1, 2, 3, 4, 5, 2, 3]
    r2 = [1, 1, 3, 4, 4, 2, 5]

    k_orig = quadratic_weighted_kappa(r1, r2, min_rating=1, max_rating=5).value
    s_orig = spearman_rank_correlation(r1, r2).value

    # Permute pairs
    pairs = list(zip(r1, r2, strict=False))
    rng = random.Random(123)
    rng.shuffle(pairs)
    p1, p2 = zip(*pairs, strict=False)

    k_perm = quadratic_weighted_kappa(p1, p2, min_rating=1, max_rating=5).value
    s_perm = spearman_rank_correlation(p1, p2).value

    assert k_orig == pytest.approx(k_perm)
    assert s_orig == pytest.approx(s_perm)


def test_input_validation() -> None:
    """Proves both functions reject unequal lengths and empty inputs."""
    with pytest.raises(ValueError, match="equal length"):
        quadratic_weighted_kappa([1, 2], [1])
    with pytest.raises(ValueError, match="equal length"):
        spearman_rank_correlation([1, 2], [1])

    with pytest.raises(ValueError, match="must not be empty"):
        quadratic_weighted_kappa([], [])
    with pytest.raises(ValueError, match="must not be empty"):
        spearman_rank_correlation([], [])

    with pytest.raises(ValueError, match="strictly less than"):
        quadratic_weighted_kappa([1], [1], min_rating=5, max_rating=5)


def test_bootstrap_ci_reproducibility_and_bounds() -> None:
    """Proves bootstrap CI brackets point estimate and handles None."""
    r1 = [1, 2, 3, 4, 5, 2, 3, 4, 5, 1, 2, 4]
    r2 = [1, 2, 2, 4, 5, 3, 3, 4, 4, 1, 3, 4]

    k_pt = quadratic_weighted_kappa(r1, r2, min_rating=1, max_rating=5).value
    assert k_pt is not None

    ci1 = bootstrap_agreement_ci(r1, r2, "kappa", min_rating=1, max_rating=5, seed=42)
    ci2 = bootstrap_agreement_ci(r1, r2, "kappa", min_rating=1, max_rating=5, seed=42)
    assert ci1 == ci2
    assert ci1 is not None
    assert ci1[0] <= k_pt <= ci1[1]

    # Degenerate input returns None for CI
    d_ci = bootstrap_agreement_ci(
        [3, 3, 3], [3, 3, 3], "kappa", min_rating=1, max_rating=5
    )
    assert d_ci is None
