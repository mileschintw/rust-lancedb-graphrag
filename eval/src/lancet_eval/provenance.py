"""Placeholder for the RED step; replaced by the arm-provenance conformance check."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lancet_eval.journal import RunRecord


@dataclass(frozen=True)
class ProvenanceFailure:
    """One broken clause."""

    code: str
    label: str
    detail: str


@dataclass(frozen=True)
class SnapshotExpectations:
    """Expected snapshot config."""

    rrf_k: int
    candidate_limit: int
    final_limit: int
    vector_weight: float
    bm25_weight: float


SNAPSHOT_EXPECTATIONS = SnapshotExpectations(
    rrf_k=60, candidate_limit=32, final_limit=8, vector_weight=1.0, bm25_weight=1.0
)
ZERO_TOLERANCE_CODES = frozenset("abcdf")


def provenance_failures(
    record: RunRecord, *, expected: SnapshotExpectations = SNAPSHOT_EXPECTATIONS
) -> list[ProvenanceFailure]:
    """Placeholder."""
    return []


def is_ok(record: RunRecord) -> bool:
    """Placeholder."""
    return False
