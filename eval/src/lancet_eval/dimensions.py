"""Evaluation dimension definitions, results, and registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

NOTICE_CODE_NO_EVIDENCE = 1
NOTICE_CODE_GRAPH_TIMEOUT = 2
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
    "bm25_yield",
    "retrieve_latency_ms",
    "graph_presence_rate",
    "graph_influence_rate",
    "graph_latency_ms",
    "retrieval_evidence_coverage",
    "context_precision_at_k",
    "ranking_quality",
    "answer_exact_match",
    "answer_f1",
    "answer_faithfulness",
    "answer_groundedness",
    "graph_ablation_delta",
    "graph_ablation_delta_exact_match",
    "graph_ablation_delta_f1",
    "graph_ablation_delta_context_precision",
    "graph_ablation_delta_ranking_quality",
    "graph_ablation_latency_delta",
    "graph_ablation_prompt_token_delta",
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


def make_paired_ablation_delta(
    *,
    name: str = "graph_ablation_delta",
    paired_result: Any,
    seed: int = 42,
    reason_on_empty: str = (
        "No paired usable (graph-on, graph-off) records on same question_id"
    ),
) -> DimensionResult:
    """Build DimensionResult for a paired ablation delta over ArmPairs."""
    res = paired_result
    detail: dict[str, float] = {
        "n_pairs": float(res.pair_count),
        "pairing_coverage": float(res.pairing_coverage),
        "n_answerable_in_sample": float(res.answerable_count),
        "bootstrap_seed": float(seed),
        "excluded_unscorable_pairs": float(res.excluded_count),
    }
    if res.join_result is not None:
        jr = res.join_result
        detail["single_arm_usable_drops"] = float(jr.single_arm_usable_drops)
        detail["missing_arm_drops"] = float(jr.missing_arm_drops)
        detail["null_gold_drops"] = float(jr.null_gold_drops)
        detail["provenance_drops"] = float(jr.provenance_drops)

    if res.ci_lower is not None:
        detail["ci_lower"] = float(res.ci_lower)
    if res.ci_upper is not None:
        detail["ci_upper"] = float(res.ci_upper)
    if res.is_degenerate:
        detail["degenerate_ci"] = 1.0

    # Stratified per-type deltas and counts
    for qtype, diff_mean in res.strata.items():
        detail[f"delta_{qtype}"] = float(diff_mean)
        if qtype in res.strata_counts:
            detail[f"n_pairs_{qtype}"] = float(res.strata_counts[qtype])

    if res.pair_count == 0 or res.mean is None:
        return DimensionResult(
            name=name,
            status="error",
            reason=reason_on_empty,
            detail=detail,
            n=0,
        )

    return DimensionResult(
        name=name,
        status="ok",
        score=res.mean,
        detail=detail,
        n=res.pair_count,
    )


def make_groundedness_result(
    *,
    verdicts: list[int | float],
    judge_errors: int,
    skipped_no_evidence: int,
    total_sampled: int,
    calibration_exact_match: float | None = None,
    calibration_mad: float | None = None,
    calibration_kappa: float | None = None,
    calibration_spearman: float | None = None,
    calibration_kappa_state: float | None = None,
    calibration_spearman_state: float | None = None,
    calibration_state: float | None = None,
    calibration_kappa_ci_lower: float | None = None,
    calibration_kappa_ci_upper: float | None = None,
    calibration_spearman_ci_lower: float | None = None,
    calibration_spearman_ci_upper: float | None = None,
    calibration_pairs_n: float | None = None,
    calibration_excluded_n: float | None = None,
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
    if calibration_kappa is not None:
        detail["calibration_kappa"] = float(calibration_kappa)
    if calibration_spearman is not None:
        detail["calibration_spearman"] = float(calibration_spearman)
    if calibration_kappa_state is not None:
        detail["calibration_kappa_state"] = float(calibration_kappa_state)
    if calibration_spearman_state is not None:
        detail["calibration_spearman_state"] = float(calibration_spearman_state)
    if calibration_state is not None:
        detail["calibration_state"] = float(calibration_state)
    if calibration_kappa_ci_lower is not None:
        detail["calibration_kappa_ci_lower"] = float(calibration_kappa_ci_lower)
    if calibration_kappa_ci_upper is not None:
        detail["calibration_kappa_ci_upper"] = float(calibration_kappa_ci_upper)
    if calibration_spearman_ci_lower is not None:
        detail["calibration_spearman_ci_lower"] = float(calibration_spearman_ci_lower)
    if calibration_spearman_ci_upper is not None:
        detail["calibration_spearman_ci_upper"] = float(calibration_spearman_ci_upper)
    if calibration_pairs_n is not None:
        detail["calibration_pairs_n"] = float(calibration_pairs_n)
    if calibration_excluded_n is not None:
        detail["calibration_excluded_n"] = float(calibration_excluded_n)
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
    calibration_kappa: float | None = None,
    calibration_spearman: float | None = None,
    calibration_kappa_state: float | None = None,
    calibration_spearman_state: float | None = None,
    calibration_state: float | None = None,
    calibration_kappa_ci_lower: float | None = None,
    calibration_kappa_ci_upper: float | None = None,
    calibration_spearman_ci_lower: float | None = None,
    calibration_spearman_ci_upper: float | None = None,
    calibration_pairs_n: float | None = None,
    calibration_excluded_n: float | None = None,
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
    if calibration_kappa is not None:
        detail["calibration_kappa"] = float(calibration_kappa)
    if calibration_spearman is not None:
        detail["calibration_spearman"] = float(calibration_spearman)
    if calibration_kappa_state is not None:
        detail["calibration_kappa_state"] = float(calibration_kappa_state)
    if calibration_spearman_state is not None:
        detail["calibration_spearman_state"] = float(calibration_spearman_state)
    if calibration_state is not None:
        detail["calibration_state"] = float(calibration_state)
    if calibration_kappa_ci_lower is not None:
        detail["calibration_kappa_ci_lower"] = float(calibration_kappa_ci_lower)
    if calibration_kappa_ci_upper is not None:
        detail["calibration_kappa_ci_upper"] = float(calibration_kappa_ci_upper)
    if calibration_spearman_ci_lower is not None:
        detail["calibration_spearman_ci_lower"] = float(calibration_spearman_ci_lower)
    if calibration_spearman_ci_upper is not None:
        detail["calibration_spearman_ci_upper"] = float(calibration_spearman_ci_upper)
    if calibration_pairs_n is not None:
        detail["calibration_pairs_n"] = float(calibration_pairs_n)
    if calibration_excluded_n is not None:
        detail["calibration_excluded_n"] = float(calibration_excluded_n)
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
    collapsed_records_n: int = 0,
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
        "collapsed_records_n": float(collapsed_records_n),
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
    retrieve_latencies: list[float] | None = None,
) -> DimensionResult:
    """Build DimensionResult for vector_yield scored over usable records."""
    from lancet_eval.stats import percentile, wilson_ci

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
    mean_count = sum(r.workflow_meta.vector_count for r in records_with_meta) / n_denom

    detail: dict[str, float] = {
        "mean_count": float(mean_count),
        "positive_n": float(positive_vector_n),
        "n_eval": float(n_denom),
        "missing_meta_n": float(missing_meta_n),
        "ci_lower": float(ci_lo),
        "ci_upper": float(ci_hi),
    }

    if retrieve_latencies:
        detail["retrieve_p50_ms"] = percentile(retrieve_latencies, 0.50)
        detail["retrieve_p95_ms"] = percentile(retrieve_latencies, 0.95)

    return DimensionResult(
        name="vector_yield",
        status="ok",
        score=p,
        detail=detail,
        n=len(records),
    )


def make_bm25_yield(
    *,
    records: list[Any],
    retrieve_latencies: list[float] | None = None,
) -> DimensionResult:
    """Build DimensionResult for bm25_yield scored over usable records."""
    from lancet_eval.stats import percentile, wilson_ci

    if not records:
        return DimensionResult(
            name="bm25_yield",
            status="skipped",
            reason="No usable records available to evaluate BM25 yield",
            n=0,
        )

    records_with_meta = [r for r in records if r.workflow_meta is not None]
    missing_meta_n = len(records) - len(records_with_meta)

    if not records_with_meta:
        return DimensionResult(
            name="bm25_yield",
            status="skipped",
            reason="All usable records missing workflow_meta",
            detail={"missing_meta_n": float(missing_meta_n)},
            n=len(records),
        )

    positive_bm25_n = sum(
        1 for r in records_with_meta if r.workflow_meta.bm25_count > 0
    )
    n_denom = len(records_with_meta)
    p, ci_lo, ci_hi = wilson_ci(positive_bm25_n, n_denom)
    mean_count = sum(r.workflow_meta.bm25_count for r in records_with_meta) / n_denom

    detail: dict[str, float] = {
        "mean_count": float(mean_count),
        "positive_n": float(positive_bm25_n),
        "n_eval": float(n_denom),
        "missing_meta_n": float(missing_meta_n),
        "ci_lower": float(ci_lo),
        "ci_upper": float(ci_hi),
    }

    if retrieve_latencies:
        detail["retrieve_p50_ms"] = percentile(retrieve_latencies, 0.50)
        detail["retrieve_p95_ms"] = percentile(retrieve_latencies, 0.95)

    return DimensionResult(
        name="bm25_yield",
        status="ok",
        score=p,
        detail=detail,
        n=len(records),
    )


def make_retrieve_latency_ms(
    *,
    records: list[Any],
) -> DimensionResult:
    """Build DimensionResult for retrieve_latency_ms scored over usable records."""
    from lancet_eval.stats import percentile

    if not records:
        return DimensionResult(
            name="retrieve_latency_ms",
            status="skipped",
            reason="No usable records available to evaluate RetrieveHybrid latency",
            n=0,
        )

    durations: list[float] = []
    for r in records:
        for nt in r.node_timings:
            if nt.node_name == "RetrieveHybrid":
                durations.append(nt.duration_ms)
                break

    missing_timing_n = len(records) - len(durations)

    if not durations:
        return DimensionResult(
            name="retrieve_latency_ms",
            status="skipped",
            reason="All usable records missing RetrieveHybrid node timing",
            detail={"missing_timing_n": float(missing_timing_n)},
            n=len(records),
        )

    p50 = percentile(durations, 0.50)
    p95 = percentile(durations, 0.95)

    detail: dict[str, float] = {
        "retrieve_p95_ms": float(p95),
        "missing_timing_n": float(missing_timing_n),
        "n_eval": float(len(durations)),
    }
    return DimensionResult(
        name="retrieve_latency_ms",
        status="ok",
        score=p50,
        detail=detail,
        n=len(records),
    )


def make_graph_presence_rate(
    *,
    records: list[Any],
) -> DimensionResult:
    """Build DimensionResult for graph_presence_rate over usable graph-on records."""
    from lancet_eval.stats import wilson_ci

    graph_on_records = [r for r in records if r.graph_arm == "graph-on"]
    if not graph_on_records:
        return DimensionResult(
            name="graph_presence_rate",
            status="skipped",
            reason="No usable graph-on records available to evaluate graph presence",
            n=0,
        )

    records_with_meta = [r for r in graph_on_records if r.workflow_meta is not None]
    missing_meta_n = len(graph_on_records) - len(records_with_meta)

    if not records_with_meta:
        return DimensionResult(
            name="graph_presence_rate",
            status="skipped",
            reason="All usable graph-on records missing workflow_meta",
            detail={"missing_meta_n": float(missing_meta_n)},
            n=len(graph_on_records),
        )

    positive_graph_n = sum(
        1
        for r in records_with_meta
        if r.workflow_meta.graph_node_count > 0 or r.workflow_meta.graph_edge_count > 0
    )
    n_denom = len(records_with_meta)
    p, ci_lo, ci_hi = wilson_ci(positive_graph_n, n_denom)

    # MultiHop-RAG floor is 0.20
    floor_val = 0.20
    floor_miss = 1.0 if p < floor_val else 0.0

    # NoMatchFound complement:
    # Among usable graph-on records whose graph node completed
    # (ExtractGraphContext timing, no failure, no GRAPH_TIMEOUT notice)
    completed_graph_records = [
        r
        for r in records_with_meta
        if any(nt.node_name == "ExtractGraphContext" for nt in r.node_timings)
        and not any(nf.node_name == "ExtractGraphContext" for nf in r.node_failures)
        and not any(
            n.typed_code == NOTICE_CODE_GRAPH_TIMEOUT or n.code == "GRAPH_TIMEOUT"
            for n in r.notices
        )
    ]

    no_match_rate = 0.0
    if completed_graph_records:
        no_match_count = sum(
            1
            for r in completed_graph_records
            if r.workflow_meta.graph_node_count == 0
            and r.workflow_meta.graph_edge_count == 0
            and not any(
                n.typed_code == NOTICE_CODE_GRAPH_UNAVAILABLE
                or n.code == "GRAPH_UNAVAILABLE"
                for n in r.notices
            )
        )
        no_match_rate = no_match_count / len(completed_graph_records)

    detail: dict[str, float] = {
        "positive_n": float(positive_graph_n),
        "n_eval": float(n_denom),
        "missing_meta_n": float(missing_meta_n),
        "ci_lower": float(ci_lo),
        "ci_upper": float(ci_hi),
        "investigation_floor": float(floor_val),
        "floor_miss": float(floor_miss),
        "no_match_rate": float(no_match_rate),
        "completed_graph_n": float(len(completed_graph_records)),
    }
    return DimensionResult(
        name="graph_presence_rate",
        status="ok",
        score=p,
        detail=detail,
        n=len(graph_on_records),
    )


def make_graph_influence_rate(
    *,
    records: list[Any],
) -> DimensionResult:
    """Build DimensionResult for graph_influence_rate over usable graph-on records."""
    from lancet_eval.stats import wilson_ci

    graph_on_records = [r for r in records if r.graph_arm == "graph-on"]
    if not graph_on_records:
        return DimensionResult(
            name="graph_influence_rate",
            status="skipped",
            reason="No usable graph-on records available to evaluate graph influence",
            n=0,
        )

    records_with_influence = [
        r
        for r in graph_on_records
        if r.workflow_meta is not None
        and r.workflow_meta.graph_prompt_fact_count is not None
    ]
    missing_influence_n = len(graph_on_records) - len(records_with_influence)

    if not records_with_influence:
        return DimensionResult(
            name="graph_influence_rate",
            status="skipped",
            reason=(
                "All usable graph-on records lack graph_prompt_fact_count "
                "(engine field not yet emitted or absent)"
            ),
            detail={"missing_influence_n": float(missing_influence_n)},
            n=len(graph_on_records),
        )

    positive_influence_n = sum(
        1 for r in records_with_influence if r.workflow_meta.graph_prompt_fact_count > 0
    )
    n_denom = len(records_with_influence)
    p, ci_lo, ci_hi = wilson_ci(positive_influence_n, n_denom)

    detail: dict[str, float] = {
        "positive_n": float(positive_influence_n),
        "n_eval": float(n_denom),
        "missing_influence_n": float(missing_influence_n),
        "ci_lower": float(ci_lo),
        "ci_upper": float(ci_hi),
    }
    return DimensionResult(
        name="graph_influence_rate",
        status="ok",
        score=p,
        detail=detail,
        n=len(graph_on_records),
    )


def make_graph_latency_ms(
    *,
    records: list[Any],
) -> DimensionResult:
    """Build DimensionResult for graph_latency_ms over attempting usable records."""
    from lancet_eval.stats import percentile
    from lancet_eval.usability import attempted_graph

    attempting_records = [r for r in records if attempted_graph(r)]
    if not attempting_records:
        return DimensionResult(
            name="graph_latency_ms",
            status="skipped",
            reason="No usable records attempted the graph node",
            n=0,
        )

    durations: list[float] = []
    for r in attempting_records:
        for nt in r.node_timings:
            if nt.node_name == "ExtractGraphContext":
                durations.append(nt.duration_ms)
                break

    missing_timing_n = len(attempting_records) - len(durations)

    if not durations:
        return DimensionResult(
            name="graph_latency_ms",
            status="skipped",
            reason=(
                "All graph-attempting records missing ExtractGraphContext node timing"
            ),
            detail={"missing_timing_n": float(missing_timing_n)},
            n=len(attempting_records),
        )

    p50 = percentile(durations, 0.50)
    p95 = percentile(durations, 0.95)

    detail: dict[str, float] = {
        "graph_p95_ms": float(p95),
        "missing_timing_n": float(missing_timing_n),
        "n_eval": float(len(durations)),
    }
    return DimensionResult(
        name="graph_latency_ms",
        status="ok",
        score=p50,
        detail=detail,
        n=len(attempting_records),
    )


def make_wire_contract_conformance(
    *,
    records: list[Any],
) -> DimensionResult:
    """Build DimensionResult for wire_contract_conformance scored over FULL journal."""
    from lancet_eval.stats import wilson_ci
    from lancet_eval.usability import is_self_contradictory

    n_journal = len(records)
    if n_journal == 0:
        return DimensionResult(
            name="wire_contract_conformance",
            status="skipped",
            reason="Journal contains 0 records",
            n=0,
        )

    violations = 0
    unparseable_n = 0
    contradiction_n = 0

    for r in records:
        if is_self_contradictory(r):
            violations += 1
            if r.error_type is not None:
                unparseable_n += 1
            else:
                contradiction_n += 1

    conformance_n = n_journal - violations
    p, ci_lo, ci_hi = wilson_ci(conformance_n, n_journal)

    detail: dict[str, float] = {
        "n_journal": float(n_journal),
        "conforming_n": float(conformance_n),
        "violations_n": float(violations),
        "unparseable_n": float(unparseable_n),
        "contradiction_n": float(contradiction_n),
        "ci_lower": float(ci_lo),
        "ci_upper": float(ci_hi),
    }
    return DimensionResult(
        name="wire_contract_conformance",
        status="ok",
        score=p,
        detail=detail,
        n=n_journal,
    )
