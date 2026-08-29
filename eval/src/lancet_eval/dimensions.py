"""Evaluation dimension definitions, results, and registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DimensionResult(BaseModel):
    """Result of an evaluation dimension with cross-field consistency validation."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["ok", "skipped", "error"]
    score: float | None = None
    detail: dict[str, float] = Field(default_factory=dict)
    reason: str | None = None
    n: int = 0

    @model_validator(mode="after")
    def _validate_consistency(self) -> Self:
        if self.status == "ok":
            if self.score is None:
                raise ValueError("status 'ok' requires a score")
            if self.reason is not None:
                raise ValueError("status 'ok' cannot have a reason")
        elif self.status in ("skipped", "error"):
            if self.score is not None:
                raise ValueError(
                    f"status {self.status!r} cannot carry a score, got {self.score}"
                )
            if self.detail:
                raise ValueError(
                    f"status {self.status!r} cannot carry detail, got {self.detail}"
                )
            if not self.reason or not self.reason.strip():
                raise ValueError(f"status {self.status!r} requires a non-blank reason")
        return self


DimensionBuilder = Callable[..., DimensionResult]

DIMENSION_REGISTRY: dict[str, DimensionBuilder] = {}

REGISTERED_DIMENSIONS: list[str] = [
    "retrieval_evidence_coverage",
    "context_precision_at_k",
    "ranking_quality",
    "answer_exact_match",
    "answer_f1",
    "answer_faithfulness",
    "answer_groundedness",
    "graph_ablation_delta",
    "abstention_on_unanswerable",
    "wire_contract_conformance",
    "community_summary_quality",
    "run_traceability",
]


def register_dimension(name: str, builder: DimensionBuilder) -> None:
    """Register a dimension builder in the global registry."""
    DIMENSION_REGISTRY[name] = builder


OBS_04_PLACEHOLDER = DimensionResult(
    name="community_summary_quality",
    status="skipped",
    reason=(
        "Deferred to Phase 999.1 (community summaries not yet implemented in engine)"
    ),
)
register_dimension("community_summary_quality", lambda: OBS_04_PLACEHOLDER)
