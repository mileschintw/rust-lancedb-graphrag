"""Latency measurement extraction, censoring classification, and derivation."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lancet_eval.dimensions import NOTICE_CODE_GRAPH_TIMEOUT
from lancet_eval.thresholds import (
    COMMITTED_THRESHOLDS,
    DecisionThresholds,
    ThresholdError,
)

# Authoritative workflow node sequence from engine/src/workflow/runner.rs:490-523.
# Downstream relation: node B is downstream of node A if index(B) > index(A).
WORKFLOW_NODE_ORDER: tuple[str, ...] = (
    "ReformulateQuery",
    "ExtractGraphContext",
    "RetrieveHybrid",
    "AssemblePrompt",
    "GenerateAnswer",
)


class CensoringLabel(StrEnum):
    """Mutually exclusive classification labels for (record, node) observations."""

    OBSERVED = "OBSERVED"
    CENSORED_AT_CEILING = "CENSORED_AT_CEILING"
    CENSORED_NODE_TIMEOUT = "CENSORED_NODE_TIMEOUT"
    NOT_REACHED = "NOT_REACHED"
    INSTRUMENT_GAP = "INSTRUMENT_GAP"


# Additional inner-level label for graph operation timeouts inside ExtractGraphContext
LABEL_INNER_GRAPH_TIMEOUT = "CENSORED_INNER_GRAPH_OP"


def is_node_downstream(target_node: str, source_node: str) -> bool:
    """Return True if target_node is executed strictly after source_node."""
    if target_node not in WORKFLOW_NODE_ORDER or source_node not in WORKFLOW_NODE_ORDER:
        return False
    return WORKFLOW_NODE_ORDER.index(target_node) > WORKFLOW_NODE_ORDER.index(
        source_node
    )


def classify_node_observation(
    record: Any,
    node_name: str,
    ceiling_ms: float,
) -> tuple[CensoringLabel, list[str]]:
    """Classify a (record, node) pair into exactly one of 5 mutually exclusive labels.

    Returns the label and any secondary inner labels (e.g. CENSORED_INNER_GRAPH_OP).
    """
    secondary_labels: list[str] = []

    # 1. Check if node completed with timing
    timings = getattr(record, "node_timings", []) or []
    node_timing = next(
        (t for t in timings if getattr(t, "node_name", "") == node_name), None
    )

    if node_timing is not None:
        dur = float(getattr(node_timing, "duration_ms", 0.0) or 0.0)
        # Inner graph timeout notice check for ExtractGraphContext
        if node_name == "ExtractGraphContext":
            notices = getattr(record, "notices", []) or []
            has_graph_timeout = any(
                getattr(n, "typed_code", None) == NOTICE_CODE_GRAPH_TIMEOUT
                or getattr(n, "code", "") == "GRAPH_TIMEOUT"
                or getattr(n, "code", "") == str(NOTICE_CODE_GRAPH_TIMEOUT)
                for n in notices
            )
            if has_graph_timeout:
                secondary_labels.append(LABEL_INNER_GRAPH_TIMEOUT)

        if dur >= ceiling_ms:
            return CensoringLabel.CENSORED_AT_CEILING, secondary_labels
        return CensoringLabel.OBSERVED, secondary_labels

    # 2. Check if node failed with timeout (NodeErrorKind::Timeout = 1)
    failures = getattr(record, "node_failures", []) or []
    node_failure = next(
        (f for f in failures if getattr(f, "node_name", "") == node_name), None
    )
    if node_failure is not None:
        error_kind = getattr(node_failure, "error_kind", None)
        if error_kind == 1:
            return CensoringLabel.CENSORED_NODE_TIMEOUT, secondary_labels
        # If it failed with another error, downstream nodes are affected, but this
        # node itself failed
        return CensoringLabel.OBSERVED, secondary_labels

    # 3. Node has neither timing nor failure. Check if NOT_REACHED or INSTRUMENT_GAP.
    # Terminating condition A: any node upstream experienced a failure
    has_upstream_failure = any(
        is_node_downstream(node_name, getattr(f, "node_name", "")) for f in failures
    )
    if has_upstream_failure:
        return CensoringLabel.NOT_REACHED, secondary_labels

    # Terminating condition B: no-evidence break before AssemblePrompt / GenerateAnswer
    # (runner.rs:504-512 breaks if no evidence blocks or no-evidence notice)
    if node_name in ("AssemblePrompt", "GenerateAnswer"):
        notices = getattr(record, "notices", []) or []
        has_no_evidence = any(
            getattr(n, "code", "") == "NO_EVIDENCE"
            or getattr(n, "typed_code", None) == 1
            for n in notices
        )
        if has_no_evidence:
            return CensoringLabel.NOT_REACHED, secondary_labels
        # Also if retrieval completed with 0 chunks and no evidence
        retrieve_timing = next(
            (t for t in timings if getattr(t, "node_name", "") == "RetrieveHybrid"),
            None,
        )
        if retrieve_timing is None:
            # Retrieve didn't run or didn't complete
            return CensoringLabel.NOT_REACHED, secondary_labels

    # If neither timing nor failure and NOT downstream -> genuine instrument gap
    return CensoringLabel.INSTRUMENT_GAP, secondary_labels


@dataclass
class CensoringCensus:
    """Census of censoring labels per node across a record set."""

    total_records: int = 0
    node_counts: dict[str, dict[str, int]] = field(
        default_factory=lambda: {
            node: {lbl.value: 0 for lbl in CensoringLabel}
            for node in WORKFLOW_NODE_ORDER
        }
    )
    inner_labels: dict[str, int] = field(default_factory=dict)

    def add_observation(
        self,
        node_name: str,
        label: CensoringLabel,
        inner: list[str],
    ) -> None:
        """Record an observation in the census."""
        if node_name not in self.node_counts:
            self.node_counts[node_name] = {lbl.value: 0 for lbl in CensoringLabel}
        self.node_counts[node_name][label.value] += 1
        for in_lbl in inner:
            self.inner_labels[in_lbl] = self.inner_labels.get(in_lbl, 0) + 1


def compute_censoring_census(
    records: Sequence[Any],
    ceilings_by_node: dict[str, float],
) -> CensoringCensus:
    """Compute the 5-label censoring census across records and nodes."""
    census = CensoringCensus(total_records=len(records))
    for rec in records:
        for node in WORKFLOW_NODE_ORDER:
            ceil = ceilings_by_node.get(node, float("inf"))
            label, inner = classify_node_observation(rec, node, ceil)
            census.add_observation(node, label, inner)
    return census


def extract_node_durations(records: Sequence[Any]) -> dict[str, list[float]]:
    """Extract observed duration values grouped by node name.

    Records without a timing entry for a node are excluded and counted, never imputed.
    """
    results: dict[str, list[float]] = {node: [] for node in WORKFLOW_NODE_ORDER}
    for rec in records:
        for t in getattr(rec, "node_timings", []) or []:
            name = getattr(t, "node_name", "")
            if name in results and getattr(t, "duration_ms", None) is not None:
                results[name].append(float(t.duration_ms))
    return results


@dataclass(frozen=True)
class PercentileResult:
    """Result of percentile estimation with bootstrap confidence interval."""

    percentile: float
    ci_low: float
    ci_high: float
    sample_size: int
    censored_count: int = 0
    is_lower_bound: bool = False
    is_degenerate: bool = False
    is_available: bool = True
    reason: str = ""


def percentile_with_ci(
    data: Sequence[float],
    p: float = 0.95,
    ci: float = 0.95,
    seed: int = 42,
    censored_count: int = 0,
    min_sample_size: int = 2,
    refuse_on_censored: bool = False,
) -> PercentileResult:
    """Compute percentile and bootstrap CI using a local deterministic generator.

    Does not perturb the global random state.
    """
    n = len(data)
    if n == 0:
        return PercentileResult(
            percentile=0.0,
            ci_low=0.0,
            ci_high=0.0,
            sample_size=0,
            censored_count=censored_count,
            is_lower_bound=censored_count > 0,
            is_available=False,
            reason="Empty observation set: 0 usable observations",
        )

    if censored_count > 0 and refuse_on_censored:
        return PercentileResult(
            percentile=0.0,
            ci_low=0.0,
            ci_high=0.0,
            sample_size=n,
            censored_count=censored_count,
            is_lower_bound=True,
            is_available=False,
            reason=(
                f"Refused: observation set contains {censored_count} "
                "censored observation(s)"
            ),
        )

    sorted_data = sorted(data)
    idx = max(0, min(n - 1, int(math.ceil(p * n)) - 1))
    point_est = sorted_data[idx]

    if n == 1:
        return PercentileResult(
            percentile=point_est,
            ci_low=point_est,
            ci_high=point_est,
            sample_size=1,
            censored_count=censored_count,
            is_lower_bound=censored_count > 0,
            is_degenerate=True,
            is_available=True,
            reason="Single observation: interval is degenerate",
        )

    if n < min_sample_size:
        return PercentileResult(
            percentile=point_est,
            ci_low=point_est,
            ci_high=point_est,
            sample_size=n,
            censored_count=censored_count,
            is_lower_bound=censored_count > 0,
            is_available=False,
            reason=f"Sample size {n} below minimum required {min_sample_size}",
        )

    # Local generator seeded from parameter — leaves global random state untouched
    rng = random.Random(seed)
    boot_reps = 1000
    boot_percentiles: list[float] = []
    for _ in range(boot_reps):
        resample = [sorted_data[rng.randrange(n)] for _ in range(n)]
        resample.sort()
        b_idx = max(0, min(n - 1, int(math.ceil(p * n)) - 1))
        boot_percentiles.append(resample[b_idx])

    boot_percentiles.sort()
    alpha = (1.0 - ci) / 2.0
    low_idx = max(0, min(boot_reps - 1, int(math.ceil(alpha * boot_reps))))
    high_idx = max(0, min(boot_reps - 1, int(math.floor((1.0 - alpha) * boot_reps))))

    ci_low = min(point_est, boot_percentiles[low_idx])
    ci_high = max(point_est, boot_percentiles[high_idx])

    return PercentileResult(
        percentile=point_est,
        ci_low=ci_low,
        ci_high=ci_high,
        sample_size=n,
        censored_count=censored_count,
        is_lower_bound=censored_count > 0,
        is_degenerate=False,
        is_available=True,
        reason=(
            f"Percentile p{int(p * 100)} with {int(ci * 100)}% CI"
            + (" (censored lower bound)" if censored_count > 0 else "")
        ),
    )


@dataclass(frozen=True)
class ProposedBudgetRecord:
    """Durable record of a proposed timeout budget derived from inputs."""

    node_or_budget: str
    proposed_ms: int
    percentile_value_ms: float
    multiplier: float
    rule: str
    sample_size: int
    censored_status: str
    provenance: str
    is_invariant_driven: bool = False

    def recompute(self) -> int:
        """Verify the budget can be reproduced exactly from its own recorded inputs."""
        if "provider_contract" in self.rule:
            return self.proposed_ms
        base = self.percentile_value_ms * self.multiplier
        return int(math.ceil(base))


def derive_budget(
    name: str,
    percentile_res: PercentileResult,
    thresholds: DecisionThresholds | None = None,
    allowance_ms: float = 0.0,
    rule_name: str = "p95_multiplier_rule",
) -> ProposedBudgetRecord:
    """Derive proposed timeout budget using pre-committed threshold policy.

    Refuses with ThresholdError if no multiplier is committed.
    """
    if thresholds is None:
        raise ThresholdError(
            "Cannot derive budget without committed DecisionThresholds"
        )
    thresholds.validate_for_derivation()

    if not percentile_res.is_available:
        raise ValueError(
            f"Cannot derive budget for {name}: percentile unavailable "
            f"({percentile_res.reason})"
        )

    val = percentile_res.percentile * thresholds.multiplier + allowance_ms
    proposed = int(math.ceil(val))
    censored_status = (
        f"censored_lower_bound({percentile_res.censored_count})"
        if percentile_res.is_lower_bound
        else "clean"
    )

    return ProposedBudgetRecord(
        node_or_budget=name,
        proposed_ms=proposed,
        percentile_value_ms=percentile_res.percentile,
        multiplier=thresholds.multiplier,
        rule=rule_name,
        sample_size=percentile_res.sample_size,
        censored_status=censored_status,
        provenance=thresholds.provenance,
    )


def derive_provider_contract_budget(
    provider_attempt_count: int = 2,
    per_attempt_timeout_s: float = 30.0,
    slack_s: float = 5.0,
) -> ProposedBudgetRecord:
    """Derive generation node budget from provider contract.

    Follows engine/src/config.rs:333-344.
    Satisfies: generation_node >= 2 * generation_timeout_secs * 1000.
    """
    base_ms = provider_attempt_count * per_attempt_timeout_s * 1000.0
    slack_ms = slack_s * 1000.0
    total_ms = int(base_ms + slack_ms)
    prov = (
        "Provider contract per engine/src/config.rs:333-344 "
        "(not from measured generation latency)"
    )
    return ProposedBudgetRecord(
        node_or_budget="generation_node_timeout_ms",
        proposed_ms=total_ms,
        percentile_value_ms=0.0,
        multiplier=float(provider_attempt_count),
        rule="provider_contract (attempt_count * per_attempt_timeout + slack)",
        sample_size=0,
        censored_status="not_applicable_provider_contract",
        provenance=prov,
    )


@dataclass(frozen=True)
class NestingGroupReport:
    """Report for one nesting relationship in the workflow configuration."""

    outer_name: str
    outer_budget_ms: int
    inner_budgets: dict[str, int]
    inner_sum_ms: int
    slack_ms: int
    fires_first: str
    is_violation: bool
    adjusted_outer_ms: int
    is_invariant_driven: bool = False


@dataclass(frozen=True)
class FullNestingReport:
    """Full report of all nesting relationships across the seven workflow budgets."""

    groups: list[NestingGroupReport]
    has_violations: bool
    resolved_budgets: dict[str, int]


def check_nesting_invariants(
    budgets: dict[str, int],
    required_slack_ms: float = 500.0,
) -> FullNestingReport:
    """Audit nesting relationships in the 7-field budget set.

    Incoherence rule: outer budget must be strictly greater than inner sum + slack.
    If outer <= inner sum, it is reported as a violation, and the enclosing budget
    is RAISED to (inner sum + slack) with is_invariant_driven=True.
    Inner budgets are never shaved down.
    """
    resolved = dict(budgets)
    groups: list[NestingGroupReport] = []
    has_violations = False

    # Relationship 1: ExtractGraphContext contains query_embedding and graph_operation
    graph_node = resolved.get("graph_node_timeout_ms", 0)
    q_emb = resolved.get("query_embedding_timeout_ms", 0)
    g_op = resolved.get("graph_operation_timeout_ms", 0)
    inner_sum_1 = q_emb + g_op
    slack_1 = graph_node - inner_sum_1
    is_viol_1 = slack_1 < required_slack_ms
    adj_1 = graph_node
    inv_driven_1 = False
    if is_viol_1:
        has_violations = True
        adj_1 = int(math.ceil(inner_sum_1 + required_slack_ms))
        resolved["graph_node_timeout_ms"] = adj_1
        inv_driven_1 = True

    groups.append(
        NestingGroupReport(
            outer_name="graph_node_timeout_ms",
            outer_budget_ms=graph_node,
            inner_budgets={
                "query_embedding_timeout_ms": q_emb,
                "graph_operation_timeout_ms": g_op,
            },
            inner_sum_ms=inner_sum_1,
            slack_ms=slack_1,
            fires_first="graph_operation_timeout_ms"
            if g_op < graph_node
            else "graph_node_timeout_ms",
            is_violation=is_viol_1,
            adjusted_outer_ms=adj_1,
            is_invariant_driven=inv_driven_1,
        )
    )

    # Relationship 2: RetrieveHybrid contains query_embedding
    ret_node = resolved.get("retrieve_timeout_ms", 0)
    inner_sum_2 = q_emb
    slack_2 = ret_node - inner_sum_2
    is_viol_2 = slack_2 < required_slack_ms
    adj_2 = ret_node
    inv_driven_2 = False
    if is_viol_2:
        has_violations = True
        adj_2 = int(math.ceil(inner_sum_2 + required_slack_ms))
        resolved["retrieve_timeout_ms"] = adj_2
        inv_driven_2 = True

    groups.append(
        NestingGroupReport(
            outer_name="retrieve_timeout_ms",
            outer_budget_ms=ret_node,
            inner_budgets={"query_embedding_timeout_ms": q_emb},
            inner_sum_ms=inner_sum_2,
            slack_ms=slack_2,
            fires_first="query_embedding_timeout_ms"
            if q_emb < ret_node
            else "retrieve_timeout_ms",
            is_violation=is_viol_2,
            adjusted_outer_ms=adj_2,
            is_invariant_driven=inv_driven_2,
        )
    )

    return FullNestingReport(
        groups=groups,
        has_violations=has_violations,
        resolved_budgets=resolved,
    )


@dataclass(frozen=True)
class TwoCeilingReport:
    """Report comparing proposed budgets against the two distinct harness ceilings."""

    largest_single_node_budget_ms: int
    largest_single_node_name: str
    sse_read_timeout_ms: int
    single_exceeds_read_timeout: bool

    worst_case_sum_ms: int
    question_deadline_ms: int
    sum_exceeds_deadline: bool

    summary_message: str


def check_harness_ceilings(
    budgets: dict[str, int],
    sse_read_timeout_s: float,
    question_deadline_s: float,
) -> TwoCeilingReport:
    """Compare single node against read timeout and sum against deadline.

    These are structurally distinct comparisons: SSE read bounds per-node gap;
    question deadline bounds worst-case sum.
    """
    node_budget_keys = [
        "reformulate_timeout_ms",
        "retrieve_timeout_ms",
        "graph_node_timeout_ms",
        "prompt_timeout_ms",
        "generation_node_timeout_ms",
    ]
    single_max_val = 0
    single_max_name = ""
    for k in node_budget_keys:
        val = budgets.get(k, 0)
        if val > single_max_val:
            single_max_val = val
            single_max_name = k

    worst_case_sum = sum(budgets.get(k, 0) for k in node_budget_keys)
    read_limit_ms = int(sse_read_timeout_s * 1000)
    deadline_limit_ms = int(question_deadline_s * 1000)

    single_flag = single_max_val >= read_limit_ms
    sum_flag = worst_case_sum >= deadline_limit_ms

    msgs = []
    if single_flag:
        msgs.append(
            f"FLAG: Largest single node budget {single_max_name} ({single_max_val}ms) "
            f"meets or exceeds SSE read timeout ({read_limit_ms}ms)"
        )
    if sum_flag:
        msgs.append(
            f"FLAG: Worst-case sum of node budgets ({worst_case_sum}ms) "
            f"meets or exceeds question deadline ({deadline_limit_ms}ms)"
        )
    if not msgs:
        msgs.append(
            "PASS: Proposed budgets satisfy both harness ceilings independently."
        )

    return TwoCeilingReport(
        largest_single_node_budget_ms=single_max_val,
        largest_single_node_name=single_max_name,
        sse_read_timeout_ms=read_limit_ms,
        single_exceeds_read_timeout=single_flag,
        worst_case_sum_ms=worst_case_sum,
        question_deadline_ms=deadline_limit_ms,
        sum_exceeds_deadline=sum_flag,
        summary_message="; ".join(msgs),
    )


@dataclass(frozen=True)
class SampleSizeRequirement:
    """Minimum question count required to support bootstrap stratification."""

    min_questions: int
    total_cells: int
    min_cell_size: int
    binding_cell: str


def required_sample_size(
    min_stratum_cell_size: int,
    num_arms: int = 2,
    num_question_types: int = 2,
    num_segments: int = 2,
    num_windows: int = 2,
) -> SampleSizeRequirement:
    """Calculate minimum question count to satisfy min_stratum_cell_size."""
    if min_stratum_cell_size <= 0:
        raise ThresholdError(
            f"Minimum stratum cell size must be positive, got {min_stratum_cell_size!r}"
        )

    # Stratification factors: arm * question_type * segment * window
    # Each question produces 2 records (1 per arm).
    # Within each arm, questions are partitioned into segments and windows.
    # Questions per (question_type * segment * window) cell >= min_stratum_cell_size.
    # Total cells per arm = num_question_types * num_segments * num_windows.
    cells_per_arm = num_question_types * num_segments * num_windows
    min_q = min_stratum_cell_size * cells_per_arm
    binding_cell = (
        f"arm[2] x question_type[n={num_question_types}] "
        f"x segment[n={num_segments}] x window[n={num_windows}]"
    )

    return SampleSizeRequirement(
        min_questions=min_q,
        total_cells=cells_per_arm * num_arms,
        min_cell_size=min_stratum_cell_size,
        binding_cell=binding_cell,
    )


def guard_graph_operation_percentile(
    observed_data: Sequence[float],
    observed_graph_timeout_rate: float | None = None,
    thresholds: DecisionThresholds | None = None,
    p: float = 0.95,
    seed: int = 42,
    graph_timeout_rate: float | None = None,
    max_tolerated_rate: float | None = None,
) -> PercentileResult:
    """Compute graph operation percentile or report censored lower bound."""
    rate = (
        observed_graph_timeout_rate
        if observed_graph_timeout_rate is not None
        else (graph_timeout_rate if graph_timeout_rate is not None else 0.0)
    )
    thresh = thresholds or COMMITTED_THRESHOLDS
    max_tol = (
        max_tolerated_rate
        if max_tolerated_rate is not None
        else thresh.max_tolerated_graph_timeout_rate
    )

    if rate > max_tol:
        # Survivor guard trips: surviving sample is biased toward fast traversals
        return PercentileResult(
            percentile=max(observed_data) if observed_data else 0.0,
            ci_low=min(observed_data) if observed_data else 0.0,
            ci_high=float("inf"),
            sample_size=len(observed_data),
            censored_count=len(observed_data),
            is_lower_bound=True,
            is_available=True,
            reason=(
                f"Survivor guard tripped: observed graph-timeout rate {rate:.2%} "
                f"exceeds committed maximum {max_tol:.2%}. "
                "Graph operation percentile reported as censored lower bound."
            ),
        )

    return percentile_with_ci(
        observed_data,
        p=p,
        seed=seed,
        censored_count=0,
    )
