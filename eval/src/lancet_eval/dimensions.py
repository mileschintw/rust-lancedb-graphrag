"""Evaluation dimension definitions, results, and registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

NOTICE_CODE_GRAPH_UNAVAILABLE = 10
NOTICE_CODE_GRAPH_ABLATION = 18


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
            if not self.reason or not self.reason.strip():
                raise ValueError(f"status {self.status!r} requires a non-blank reason")
        return self


DimensionBuilder = Callable[..., DimensionResult]

DIMENSION_REGISTRY: dict[str, DimensionBuilder] = {}

REGISTERED_DIMENSIONS: list[str] = [
    "unusable_record_rate",
    "vector_yield",
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


def make_graph_ablation_delta(
    *,
    graph_on_score: float,
    graph_on_n: int,
    graph_on_errors: int,
    graph_off_score: float,
    graph_off_n: int,
    graph_off_errors: int,
) -> DimensionResult:
    """Build DimensionResult for graph ablation comparison."""
    if graph_on_n == 0 and graph_off_n == 0:
        return DimensionResult(
            name="graph_ablation_delta",
            status="error",
            reason="No successfully evaluated records for graph-on or graph-off arms",
            n=0,
        )
    delta = graph_on_score - graph_off_score
    detail = {
        "graph_on_score": graph_on_score,
        "graph_on_n": float(graph_on_n),
        "graph_on_errors": float(graph_on_errors),
        "graph_off_score": graph_off_score,
        "graph_off_n": float(graph_off_n),
        "graph_off_errors": float(graph_off_errors),
        "delta": delta,
    }
    return DimensionResult(
        name="graph_ablation_delta",
        status="ok",
        score=delta,
        detail=detail,
        n=graph_on_n + graph_off_n,
    )


def make_groundedness_result(
    *,
    verdicts: list[int | float],
    judge_errors: int,
    skipped_no_evidence: int,
    total_sampled: int,
    calibration_exact_match: float | None = None,
    calibration_mad: float | None = None,
) -> DimensionResult:
    """Build DimensionResult for judged answer groundedness."""
    if not verdicts:
        if judge_errors > 0 and judge_errors == total_sampled:
            return DimensionResult(
                name="answer_groundedness",
                status="error",
                reason=f"All {judge_errors} judge calls failed with errors",
                n=0,
            )
        if skipped_no_evidence == total_sampled and total_sampled > 0:
            return DimensionResult(
                name="answer_groundedness",
                status="skipped",
                reason="No evidence returned in responses; groundedness undefined",
                n=0,
            )
        return DimensionResult(
            name="answer_groundedness",
            status="skipped",
            reason="No judged items available",
            n=0,
        )
    mean_val = sum(verdicts) / len(verdicts)
    detail: dict[str, float] = {
        "judged_n": float(len(verdicts)),
        "judge_errors": float(judge_errors),
        "skipped_no_evidence": float(skipped_no_evidence),
    }
    if calibration_exact_match is not None:
        detail["calibration_exact_match"] = float(calibration_exact_match)
    if calibration_mad is not None:
        detail["calibration_mad"] = float(calibration_mad)
    return DimensionResult(
        name="answer_groundedness",
        status="ok",
        score=mean_val,
        detail=detail,
        n=len(verdicts),
    )


def make_faithfulness_result(
    *,
    verdicts: list[int | float],
    judge_errors: int,
    skipped_no_evidence: int,
    total_sampled: int,
    calibration_exact_match: float | None = None,
    calibration_mad: float | None = None,
) -> DimensionResult:
    """Build DimensionResult for judged answer faithfulness."""
    if not verdicts:
        if judge_errors > 0 and judge_errors == total_sampled:
            return DimensionResult(
                name="answer_faithfulness",
                status="error",
                reason=f"All {judge_errors} judge calls failed with errors",
                n=0,
            )
        if skipped_no_evidence == total_sampled and total_sampled > 0:
            return DimensionResult(
                name="answer_faithfulness",
                status="skipped",
                reason="No evidence returned in responses; faithfulness undefined",
                n=0,
            )
        return DimensionResult(
            name="answer_faithfulness",
            status="skipped",
            reason="No judged items available",
            n=0,
        )
    mean_val = sum(verdicts) / len(verdicts)
    detail: dict[str, float] = {
        "judged_n": float(len(verdicts)),
        "judge_errors": float(judge_errors),
        "skipped_no_evidence": float(skipped_no_evidence),
    }
    if calibration_exact_match is not None:
        detail["calibration_exact_match"] = float(calibration_exact_match)
    if calibration_mad is not None:
        detail["calibration_mad"] = float(calibration_mad)
    return DimensionResult(
        name="answer_faithfulness",
        status="ok",
        score=mean_val,
        detail=detail,
        n=len(verdicts),
    )


def make_unusable_record_rate(
    *,
    records: list[Any],
) -> DimensionResult:
    """Build DimensionResult for unusable_record_rate scored over full journal."""
    from lancet_eval.stats import wilson_ci
    from lancet_eval.usability import is_usable

    n_journal = len(records)
    if n_journal == 0:
        return DimensionResult(
            name="unusable_record_rate",
            status="skipped",
            reason="Journal contains 0 records",
            n=0,
        )

    unusable_n = sum(1 for r in records if not is_usable(r))
    p, ci_lo, ci_hi = wilson_ci(unusable_n, n_journal)
    detail: dict[str, float] = {
        "unusable_n": float(unusable_n),
        "n_journal": float(n_journal),
        "unusable_rate": float(p),
        "ci_lower": float(ci_lo),
        "ci_upper": float(ci_hi),
    }
    return DimensionResult(
        name="unusable_record_rate",
        status="ok",
        score=p,
        detail=detail,
        n=n_journal,
    )


def make_vector_yield(
    *,
    records: list[Any],
) -> DimensionResult:
    """Build DimensionResult for vector_yield scored over usable records."""
    from lancet_eval.stats import wilson_ci

    if not records:
        return DimensionResult(
            name="vector_yield",
            status="skipped",
            reason="No usable records available to evaluate vector yield",
            n=0,
        )

    records_with_meta = [r for r in records if r.workflow_meta is not None]
    missing_meta_n = len(records) - len(records_with_meta)

    if not records_with_meta:
        return DimensionResult(
            name="vector_yield",
            status="skipped",
            reason="All usable records missing workflow_meta",
            detail={"missing_meta_n": float(missing_meta_n)},
            n=len(records),
        )

    positive_vector_n = sum(
        1 for r in records_with_meta if r.workflow_meta.vector_count > 0
    )
    n_denom = len(records_with_meta)
    p, ci_lo, ci_hi = wilson_ci(positive_vector_n, n_denom)
    mean_count = sum(
        r.workflow_meta.vector_count for r in records_with_meta
    ) / n_denom

    detail: dict[str, float] = {
        "mean_count": float(mean_count),
        "positive_n": float(positive_vector_n),
        "n_eval": float(n_denom),
        "missing_meta_n": float(missing_meta_n),
        "ci_lower": float(ci_lo),
        "ci_upper": float(ci_hi),
    }
    return DimensionResult(
        name="vector_yield",
        status="ok",
        score=p,
        detail=detail,
        n=len(records),
    )


