"""Statistical helpers for evaluation scoring and confidence intervals."""

from __future__ import annotations

import math

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
