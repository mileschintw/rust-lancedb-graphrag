"""Standard-library agreement metrics: quadratic weighted kappa and Spearman rho.

Implements quadratic weighted kappa and Spearman rank correlation with ties
resolved by the mid-rank convention, using the Python standard library only.
Includes bootstrap confidence intervals via row resampling.

Golden vectors referenced in test suite:
- Quadratic weighted kappa: Cohen (1968) nominal/ordinal weighted scale formulation,
  verified against exact rational weights on integer ratings.
- Spearman rank correlation: Zar (2010) Biostatistical Analysis tied-ranks formulation,
  computed via Pearson correlation of mid-ranks.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

# Disjoint state code constants (D-48)
# calibration_state: 0.0, 1.0, 2.0
CALIBRATION_STATE_NONE = 0.0
CALIBRATION_STATE_BELOW_TARGET = 1.0
CALIBRATION_STATE_SATISFIED = 2.0

# calibration_kappa_state: 10.0, 11.0
KAPPA_STATE_COMPUTED = 10.0
KAPPA_STATE_UNDEFINED_EXPECTED_AGREEMENT = 11.0

# calibration_spearman_state: 20.0, 21.0
SPEARMAN_STATE_COMPUTED = 20.0
SPEARMAN_STATE_UNDEFINED_ZERO_VARIANCE = 21.0


@dataclass(frozen=True)
class AgreementResult:
    """Result of an agreement metric computation.

    value is None if and only if the calculation is mathematically undefined
    (e.g., zero variance or vanished expected agreement).
    """

    value: float | None
    state: str  # "computed", "undefined_zero_variance", "undefined_expected_agreement"


def quadratic_weighted_kappa(
    rater1: Sequence[int],
    rater2: Sequence[int],
    *,
    min_rating: int = 1,
    max_rating: int = 5,
) -> AgreementResult:
    """Compute quadratic weighted kappa over two equal-length integer sequences.

    Args:
        rater1: Sequence of integer ratings from first rater.
        rater2: Sequence of integer ratings from second rater.
        min_rating: Minimum possible rating on the rubric scale (default 1).
        max_rating: Maximum possible rating on the rubric scale (default 5).

    Returns:
        AgreementResult with value and state string.
    Raises:
        ValueError: If sequences have unequal length, are empty,
            or min_rating >= max_rating.
    """
    n1 = len(rater1)
    n2 = len(rater2)
    if n1 != n2:
        raise ValueError(
            f"Sequences must have equal length, got rater1={n1} and rater2={n2}"
        )
    if n1 == 0:
        raise ValueError("Input sequences must not be empty")
    if min_rating >= max_rating:
        raise ValueError(
            f"min_rating ({min_rating}) must be strictly less than "
            f"max_rating ({max_rating})"
        )

    k = max_rating - min_rating + 1
    scale_span = float(max_rating - min_rating)

    # Build observed confusion matrix
    # Dimensions: k x k
    obs: list[list[int]] = [[0] * k for _ in range(k)]
    for r1, r2 in zip(rater1, rater2, strict=True):
        if not (min_rating <= r1 <= max_rating):
            raise ValueError(
                f"Rating {r1} in rater1 out of bounds [{min_rating}, {max_rating}]"
            )
        if not (min_rating <= r2 <= max_rating):
            raise ValueError(
                f"Rating {r2} in rater2 out of bounds [{min_rating}, {max_rating}]"
            )
        obs[r1 - min_rating][r2 - min_rating] += 1

    total = float(n1)

    # Marginals
    m1 = [sum(obs[i][j] for j in range(k)) / total for i in range(k)]
    m2 = [sum(obs[i][j] for i in range(k)) / total for j in range(k)]

    # Weights: w_ij = 1 - (i - j)^2 / (max - min)^2
    # Agreement: P_o = sum(w_ij * O_ij / total)
    # Expected: P_e = sum(w_ij * m1_i * m2_j)
    # Denominator: 1 - P_e
    p_o = 0.0
    p_e = 0.0
    for i in range(k):
        for j in range(k):
            diff = float(i - j)
            w = 1.0 - (diff * diff) / (scale_span * scale_span)
            p_o += w * (obs[i][j] / total)
            p_e += w * (m1[i] * m2[j])

    den = 1.0 - p_e
    if abs(den) < 1e-12:
        return AgreementResult(value=None, state="undefined_expected_agreement")

    if abs(p_o - 1.0) < 1e-12:
        return AgreementResult(value=1.0, state="computed")

    kappa = (p_o - p_e) / den
    # Clamp small numeric precision overshoots
    kappa = max(-1.0, min(1.0, kappa))
    return AgreementResult(value=kappa, state="computed")


def compute_mid_ranks(seq: Sequence[float | int]) -> list[float]:
    """Compute ranks for a sequence with ties resolved via mid-rank convention."""
    n = len(seq)
    if n == 0:
        return []
    # Sort indices by value
    sorted_indices = sorted(range(n), key=lambda i: seq[i])

    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        val = seq[sorted_indices[i]]
        while j < n and seq[sorted_indices[j]] == val:
            j += 1
        # Indices from i to j - 1 are tied
        # 1-based ranks are (i + 1) to j
        avg_rank = (i + 1 + j) / 2.0
        for idx in range(i, j):
            ranks[sorted_indices[idx]] = avg_rank
        i = j

    return ranks


def spearman_rank_correlation(
    rater1: Sequence[float | int],
    rater2: Sequence[float | int],
) -> AgreementResult:
    """Compute Spearman rank correlation over two equal-length sequences.

    Ties are resolved using the mid-rank convention.

    Args:
        rater1: First sequence of ratings/scores.
        rater2: Second sequence of ratings/scores.

    Returns:
        AgreementResult with value and state string.
    Raises:
        ValueError: If sequences have unequal length or are empty.
    """
    n1 = len(rater1)
    n2 = len(rater2)
    if n1 != n2:
        raise ValueError(
            f"Sequences must have equal length, got rater1={n1} and rater2={n2}"
        )
    if n1 == 0:
        raise ValueError("Input sequences must not be empty")

    r1 = compute_mid_ranks(rater1)
    r2 = compute_mid_ranks(rater2)

    mean1 = sum(r1) / float(n1)
    mean2 = sum(r2) / float(n2)

    var1 = sum((x - mean1) ** 2 for x in r1)
    var2 = sum((y - mean2) ** 2 for y in r2)

    if var1 < 1e-12 or var2 < 1e-12:
        return AgreementResult(value=None, state="undefined_zero_variance")

    cov = sum((r1[i] - mean1) * (r2[i] - mean2) for i in range(n1))
    rho = cov / math.sqrt(var1 * var2)
    rho = max(-1.0, min(1.0, rho))
    return AgreementResult(value=rho, state="computed")


def _percentile(xs: list[float], q: float) -> float:
    """Calculate percentile with linear interpolation on sorted values."""
    if not xs:
        raise ValueError("percentile input xs must not be empty")
    ys = sorted(xs)
    n = len(ys)
    if n == 1:
        return float(ys[0])
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return float(ys[lo] * (1.0 - frac) + ys[hi] * frac)


def bootstrap_agreement_ci(
    rater1: Sequence[int],
    rater2: Sequence[int],
    metric: str,
    *,
    min_rating: int = 1,
    max_rating: int = 5,
    seed: int = 42,
    b: int = 1000,
) -> tuple[float, float] | None:
    """Calculate seeded bootstrap 95% CI for kappa or spearman via row resampling.

    Args:
        rater1: First sequence of ratings.
        rater2: Second sequence of ratings.
        metric: Either 'kappa' or 'spearman'.
        min_rating: Scale min rating (used for kappa).
        max_rating: Scale max rating (used for kappa).
        seed: Deterministic random seed.
        b: Number of bootstrap resamples (default 1000).

    Returns:
        (ci_lower, ci_upper) or None if statistic is undefined on base input.
    """
    if len(rater1) != len(rater2) or len(rater1) == 0:
        return None

    if metric == "kappa":
        base_res = quadratic_weighted_kappa(
            rater1, rater2, min_rating=min_rating, max_rating=max_rating
        )
    elif metric == "spearman":
        base_res = spearman_rank_correlation(rater1, rater2)
    else:
        raise ValueError(f"Unknown metric '{metric}', expected 'kappa' or 'spearman'")

    if base_res.value is None or base_res.state != "computed":
        return None

    n = len(rater1)
    if n == 1:
        return base_res.value, base_res.value

    rng = random.Random(seed)
    estimates: list[float] = []

    for _ in range(b):
        sampled_indices = [rng.randrange(n) for _ in range(n)]
        s1 = [rater1[idx] for idx in sampled_indices]
        s2 = [rater2[idx] for idx in sampled_indices]

        if metric == "kappa":
            res = quadratic_weighted_kappa(
                s1, s2, min_rating=min_rating, max_rating=max_rating
            )
        else:
            res = spearman_rank_correlation(s1, s2)

        if res.value is not None and not math.isnan(res.value):
            estimates.append(res.value)

    if not estimates:
        return None

    estimates.sort()
    ci_lo = _percentile(estimates, 0.025)
    ci_hi = _percentile(estimates, 0.975)
    return ci_lo, ci_hi
