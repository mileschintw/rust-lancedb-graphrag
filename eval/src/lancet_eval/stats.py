"""Statistical helpers for evaluation scoring and confidence intervals."""

from __future__ import annotations

import math
from collections.abc import Sequence
from fractions import Fraction
from math import comb

BOOTSTRAP_B = 10_000
BOOTSTRAP_SEED = 42


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Calculate Wilson score interval for a binomial proportion.

    Returns:
        (p, lower_bound, upper_bound)
    Raises:
        ValueError if n <= 0.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    p = k / n
    z2 = z * z
    den = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / den
    half = z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n) / den
    return p, max(0.0, center - half), min(1.0, center + half)


def percentile(xs: list[float], q: float) -> float:
    """Calculate percentile with linear interpolation on sorted values.

    Args:
        xs: list of numeric values (must be non-empty)
        q: quantile in [0, 1]

    Returns:
        Interpolated percentile value.
    Raises:
        ValueError if xs is empty.
    """
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


def bootstrap_mean_ci(
    diffs: list[float],
    *,
    seed: int = BOOTSTRAP_SEED,
    b: int = BOOTSTRAP_B,
) -> tuple[float, float, float]:
    """Calculate nonparametric bootstrap percentile 95% CI of the mean.

    Args:
        diffs: list of per-question differences.
        seed: PRNG seed for deterministic resampling.
        b: number of bootstrap resamples (default 10,000).

    Returns:
        (mean, ci_lower, ci_upper)
    Raises:
        ValueError if diffs is empty.
    """
    import random
    from statistics import mean

    n = len(diffs)
    if n == 0:
        raise ValueError("n_pairs=0: diffs must not be empty")
    mu = float(mean(diffs))
    if n == 1:
        return mu, mu, mu

    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(b):
        acc = 0.0
        for _ in range(n):
            acc += diffs[rng.randrange(n)]
        means.append(acc / n)
    means.sort()
    ci_lo = float(means[int(0.025 * b)])
    ci_hi = float(means[min(b - 1, int(0.975 * b))])
    return mu, ci_lo, ci_hi


def exact_signflip_p(n_pos: int, n_neg: int) -> Fraction:
    """Exact two-sided paired sign-flip p-value on 0/+-1 differences (D-123).

    With `n_pos` pairs favouring one arm and `n_neg` the other (ties dropped), flipping
    the sign of each discordant difference independently with probability 1/2 gives
    `S = 2K - nd`, `K ~ Binomial(nd, 1/2)`, `nd = n_pos + n_neg`. The p-value is
    `P(|S| >= |n_pos - n_neg|)`. For 0/1 outcomes this is the exact McNemar test. It is
    computed with integer arithmetic only, so it is reproducible and carries no seed.

    Args:
        n_pos: Discordant pairs where the first arm scored higher.
        n_neg: Discordant pairs where the second arm scored higher.

    Returns:
        The two-sided p-value as an exact `Fraction`; `1` when there are no
        discordant pairs.

    Raises:
        ValueError: If a count is negative.
    """
    if n_pos < 0 or n_neg < 0:
        raise ValueError(f"counts must be non-negative, got ({n_pos}, {n_neg})")
    nd = n_pos + n_neg
    if nd == 0:
        return Fraction(1)
    s_obs = abs(n_pos - n_neg)
    tail = sum(comb(nd, k) for k in range(nd + 1) if abs(2 * k - nd) >= s_obs)
    return Fraction(tail, 2**nd)


def holm_stepdown(
    ps: Sequence[float], alpha: float = 0.05
) -> tuple[list[bool], list[float]]:
    """Holm step-down multiplicity correction at family-wise error `alpha` (D-123).

    The p-values are ordered ascending with a stable sort, so tied p-values keep input
    order. The i-th smallest (0-based `rank`) is rejected while it is at most
    `alpha / (m - rank)`; the first failure stops the procedure, and every later
    hypothesis is retained. The adjusted p-value is the running maximum of
    `min(1, (m - rank) * p)`, so it never decreases along the ordering.

    Args:
        ps: The family's p-values, in the caller's order.
        alpha: Family-wise error rate, strictly between 0 and 1.

    Returns:
        `(reject, adjusted)`, both in the caller's input order.

    Raises:
        ValueError: If `alpha` is outside (0, 1) or a p-value is outside [0, 1].
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if any(not 0.0 <= p <= 1.0 for p in ps):
        raise ValueError("every p-value must be in [0, 1]")
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    reject = [False] * m
    adjusted = [0.0] * m
    running = 0.0
    stopped = False
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * ps[i]))
        adjusted[i] = running
        if not stopped and ps[i] <= alpha / (m - rank):
            reject[i] = True
        else:
            stopped = True
    return reject, adjusted
