"""Decision thresholds and inputs committed before running measurement pass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ThresholdError(ValueError):
    """Raised when a required decision threshold is missing or uncommitted."""


@dataclass(frozen=True)
class DecisionThresholds:
    """Explicit decision inputs committed before measurement data is observed.

    Per D-14 and D-18, the multiplier and decay thresholds have no default values
    in this class definition so that uncommitted guesses cannot be shipped as policy.
    """

    multiplier: float
    decay_significance_threshold: float
    materiality_delta_ms: float
    window_fractions: tuple[float, float]
    segment_boundary_sizes: tuple[int, int]
    min_stratum_cell_size: int
    max_tolerated_graph_timeout_rate: float
    derivation_percentile: float = 0.95
    bootstrap_seed: int = 42
    slack_ms: float = 500.0
    provenance: str = ""

    def validate_for_derivation(self) -> None:
        """Assert required threshold inputs for budget derivation are present."""
        if self.multiplier is None or self.multiplier <= 0:
            raise ThresholdError(
                "Derivation requires positive committed multiplier, "
                f"got {self.multiplier!r}"
            )
        if not (0.0 < self.derivation_percentile < 1.0):
            raise ThresholdError(
                "Derivation requires percentile in (0, 1), "
                f"got {self.derivation_percentile!r}"
            )

    def validate_for_decay(self) -> None:
        """Assert required threshold inputs for decay detection are present."""
        if not (0.0 < self.decay_significance_threshold < 1.0):
            raise ThresholdError(
                "Decay detection requires significance threshold in (0, 1), "
                f"got {self.decay_significance_threshold!r}"
            )
        if self.materiality_delta_ms < 0:
            raise ThresholdError(
                "Decay detection requires non-negative materiality delta, "
                f"got {self.materiality_delta_ms!r}"
            )
        if len(self.window_fractions) != 2 or any(
            f <= 0 or f >= 0.5 for f in self.window_fractions
        ):
            raise ThresholdError(
                "Window fractions must be 2 positive fractions < 0.5, "
                f"got {self.window_fractions!r}"
            )
        if len(self.segment_boundary_sizes) != 2 or any(
            s <= 0 for s in self.segment_boundary_sizes
        ):
            raise ThresholdError(
                "Segment boundary sizes must be 2 positive counts, "
                f"got {self.segment_boundary_sizes!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary suitable for JSON serialization in run records."""
        return {
            "multiplier": self.multiplier,
            "derivation_percentile": self.derivation_percentile,
            "decay_significance_threshold": self.decay_significance_threshold,
            "materiality_delta_ms": self.materiality_delta_ms,
            "window_fractions": list(self.window_fractions),
            "segment_boundary_sizes": list(self.segment_boundary_sizes),
            "min_stratum_cell_size": self.min_stratum_cell_size,
            "max_tolerated_graph_timeout_rate": self.max_tolerated_graph_timeout_rate,
            "bootstrap_seed": self.bootstrap_seed,
            "slack_ms": self.slack_ms,
            "provenance": self.provenance,
        }


# Pre-committed decision inputs for Phase 06.3.3.
# Every decision input is locked before running measurement passes to ensure verdicts
# and proposed budgets are pure functions of data and committed policy.
COMMITTED_THRESHOLDS = DecisionThresholds(
    multiplier=1.5,
    derivation_percentile=0.95,
    decay_significance_threshold=0.05,
    materiality_delta_ms=500.0,
    window_fractions=(0.25, 0.25),
    segment_boundary_sizes=(30, 30),
    min_stratum_cell_size=10,
    max_tolerated_graph_timeout_rate=0.10,
    bootstrap_seed=42,
    slack_ms=500.0,
    provenance=(
        "Committed decision inputs per Phase 06.3.3: D-14 (multiplier=1.5, p95), "
        "D-18/D-19 (decay alpha=0.05, delta=500ms, window fractions 25%/25%), "
        "D-21 (segment boundary sizes 30/30), AI-SPEC bootstrap seed=42, "
        "min stratum cell size=10, max tolerated graph timeout rate=0.10, "
        "nesting invariant slack=500ms."
    ),
)
