"""Committed decision inputs, stage spend caps, and staged-gate evaluation for Phase 06.3.4."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from lancet_eval.config import repo_root
from lancet_eval.report import CorpusReport

# --- Committed Decision Inputs (AI-SPEC §5 / D-32, D-44, D-48) ---
# Boundary semantics are part of the lock:
# - Coverage floor: at-or-above (>= 0.80)
# - Yield floor: at-or-above (>= 0.20)
# - Complement trigger: strictly above (> 0.80)
STAGED_PAIRING_COVERAGE_FLOOR: float = 0.80
GRAPH_YIELD_INVESTIGATION_FLOOR: float = 0.20
COMPLEMENT_TRIGGER: float = 0.80
STAGED_SIZE: int = 50
CALIBRATION_SIZE: int = 12
AGREEMENT_TARGET: float = 0.70


class StagedGateVerdict(BaseModel):
    """Structured verdict from evaluating a staged drive against committed floors."""

    model_config = ConfigDict(extra="forbid")

    overall_status: str  # "pass", "hold", "investigate", "error"
    d44_staged_coverage: float | None = None
    harness_pairing_coverage: float
    distinct_questions_in_journal: int
    d44_coverage_ceiling: float
    d44_coverage_denominator: int
    headroom_answerable_drops: int
    coverage_outcome: str  # "pass", "hold", "empty", "fail"
    presence_rate: float
    yield_outcome: str  # "pass", "miss", "suspended"
    yield_suspended: bool
    no_match_rate: float
    complement_trigger_fired: bool
    reason: str | None = None
    comparison_inputs: dict[str, Any]
    observed_values: dict[str, Any]


def _find_budgets_file(budgets_path: Path | str | None = None) -> Path:
    """Find 06.3.3-BUDGETS.md in the repository planning directory."""
    if budgets_path is not None:
        p = Path(budgets_path)
        if not p.is_file():
            raise FileNotFoundError(f"Budgets file not found at: {p}")
        return p

    root = repo_root()
    planning_phases = root / ".planning" / "phases"
    matches = list(planning_phases.glob("*06.3.3*/06.3.3-BUDGETS.md"))
    if not matches:
        raise FileNotFoundError(
            "06.3.3-BUDGETS.md not found in .planning/phases/*06.3.3*/"
        )
    return matches[0]


def read_stage_caps(budgets_path: Path | str | None = None) -> dict[str, float]:
    """Read per-stage spend caps from 06.3.3-BUDGETS.md go/no-go section.

    Raises if the table is missing or if any stage cap cannot be parsed.
    """
    path = _find_budgets_file(budgets_path)
    text = path.read_text(encoding="utf-8")

    # Table under: ### Per-stage caps for 06.3.4 (D-47)
    # | Stage | Cap (USD) | Consumer |
    # | Staged drive | **$2.00** | ...
    # | Full two-arm drive | **$5.00** | ...
    # | Judging | **$5.00** | ...
    pattern = re.compile(
        r"\|\s*([^|]+?)\s*\|\s*(?:\*\*)?\$?([0-9]+(?:\.[0-9]+)?)(?:\*\*)?\s*\|\s*([^|]*)\|"
    )

    caps: dict[str, float] = {}
    found_table = False
    for line in text.splitlines():
        if "Per-stage caps for 06.3.4" in line or "Per-stage caps" in line:
            found_table = True
            continue
        if found_table:
            match = pattern.match(line)
            if match:
                stage_raw = match.group(1).strip()
                val_raw = match.group(2).strip()
                if stage_raw.lower() in ("stage", "---", ":---"):
                    continue
                try:
                    caps[stage_raw] = float(val_raw)
                except ValueError as e:
                    raise ValueError(f"Cannot parse cap for stage '{stage_raw}': {val_raw}") from e

    required_stages = ["Staged drive", "Full two-arm drive", "Judging"]
    for req in required_stages:
        if req not in caps:
            # Try case-insensitive lookup
            matched = False
            for k, v in list(caps.items()):
                if req.lower() in k.lower():
                    caps[req] = v
                    matched = True
                    break
            if not matched:
                raise ValueError(
                    f"Stage cap for '{req}' missing from {path.name}"
                )

    return {
        "staged": caps["Staged drive"],
        "staged_drive": caps["Staged drive"],
        "full": caps["Full two-arm drive"],
        "full_drive": caps["Full two-arm drive"],
        "judging": caps["Judging"],
    }


def get_stage_cap(stage: str, budgets_path: Path | str | None = None) -> float:
    """Get the spend cap in USD for a specific stage from 06.3.3-BUDGETS.md."""
    caps = read_stage_caps(budgets_path)
    stage_key = stage.lower().replace(" ", "_").replace("-", "_")
    if stage_key in caps:
        return caps[stage_key]
    raise KeyError(f"Unknown stage '{stage}'. Expected one of: {list(caps.keys())}")


def _find_store_baseline_file(baseline_path: Path | str | None = None) -> Path:
    """Find 06.3.3-STORE-BASELINE.md in the repository planning directory."""
    if baseline_path is not None:
        p = Path(baseline_path)
        if not p.is_file():
            raise FileNotFoundError(f"Store baseline file not found at: {p}")
        return p

    root = repo_root()
    planning_phases = root / ".planning" / "phases"
    matches = list(planning_phases.glob("*06.3.3*/06.3.3-STORE-BASELINE.md"))
    if not matches:
        raise FileNotFoundError(
            "06.3.3-STORE-BASELINE.md not found in .planning/phases/*06.3.3*/"
        )
    return matches[0]


def read_store_suspension(baseline_path: Path | str | None = None) -> bool:
    """Read store baseline inspection to determine if graph yield floor is suspended.

    Suspended entirely when store inspection found node, edge, and entity counts of zero
    (or unpopulated: true).
    """
    path = _find_store_baseline_file(baseline_path)
    text = path.read_text(encoding="utf-8")

    # Look for unpopulated flag
    unpop_match = re.search(r"unpopulated:\s*(true|false)", text, re.IGNORECASE)
    if unpop_match:
        return unpop_match.group(1).lower() == "true"

    # Alternatively check disposition
    disp_match = re.search(r"graph_disposition:\s*(\w+)", text, re.IGNORECASE)
    if disp_match and disp_match.group(1).lower() == "unpopulated":
        return True

    return False


def evaluate_staged_gate(
    report: CorpusReport,
    is_suspended: bool = False,
    locked_stage_size: int = STAGED_SIZE,
    distinct_questions_in_journal: int | None = None,
) -> StagedGateVerdict:
    """Evaluate a scored report from a staged drive against committed floors.

    Recomputes D-44 coverage as n_pairs / locked_stage_size.
    Fails closed (hold) on short journal where distinct_questions < locked_stage_size.
    Empty input (0 pairs) names empty input as reason without computing ratio.
    """
    dim_ablation = next(
        (d for d in report.dimensions if d.name == "graph_ablation_delta"), None
    )
    if dim_ablation is None:
        raise ValueError("Missing required dimension: graph_ablation_delta")

    required_ablation_keys = [
        "n_pairs",
        "pairing_coverage",
        "null_gold_drops",
        "n_answerable_in_sample",
    ]
    for k in required_ablation_keys:
        if k not in dim_ablation.detail:
            raise ValueError(f"Missing required detail key in graph_ablation_delta: {k}")

    n_pairs = int(dim_ablation.detail["n_pairs"])
    harness_pairing_coverage = float(dim_ablation.detail["pairing_coverage"])
    null_gold_drops = int(dim_ablation.detail["null_gold_drops"])

    d44_coverage_ceiling = (locked_stage_size - null_gold_drops) / float(locked_stage_size)
    headroom_drops = int(round((d44_coverage_ceiling - STAGED_PAIRING_COVERAGE_FLOOR) * locked_stage_size))

    # Evaluate coverage
    distinct_q = (
        distinct_questions_in_journal
        if distinct_questions_in_journal is not None
        else int(dim_ablation.n)
    )

    d44_staged_cov: float | None = None
    coverage_outcome: str
    cov_reason: str | None = None

    if n_pairs == 0:
        coverage_outcome = "empty"
        cov_reason = "Empty input: zero usable pairs produced by pairing join"
    elif distinct_q < locked_stage_size:
        coverage_outcome = "hold"
        d44_staged_cov = n_pairs / float(locked_stage_size)
        cov_reason = (
            f"Short journal: {distinct_q} distinct questions in journal < "
            f"locked stage size {locked_stage_size}"
        )
    else:
        d44_staged_cov = n_pairs / float(locked_stage_size)
        if d44_staged_cov >= STAGED_PAIRING_COVERAGE_FLOOR:
            coverage_outcome = "pass"
        else:
            coverage_outcome = "fail"
            cov_reason = (
                f"D-44 coverage {d44_staged_cov:.4f} fell below floor "
                f"{STAGED_PAIRING_COVERAGE_FLOOR:.2f}"
            )

    # Evaluate yield & presence
    dim_presence = next(
        (d for d in report.dimensions if d.name == "graph_presence_rate"), None
    )
    if dim_presence is None:
        raise ValueError("Missing required dimension: graph_presence_rate")

    if "no_match_rate" not in dim_presence.detail:
        raise ValueError("Missing required detail key in graph_presence_rate: no_match_rate")

    presence_rate = float(dim_presence.score if dim_presence.score is not None else 0.0)
    no_match_rate = float(dim_presence.detail["no_match_rate"])
    complement_trigger_fired = no_match_rate > COMPLEMENT_TRIGGER

    yield_outcome: str
    if is_suspended:
        yield_outcome = "suspended"
    elif presence_rate >= GRAPH_YIELD_INVESTIGATION_FLOOR:
        yield_outcome = "pass"
    else:
        yield_outcome = "miss"

    # Overall verdict
    if coverage_outcome == "empty":
        overall_status = "error"
    elif coverage_outcome == "hold":
        overall_status = "hold"
    elif coverage_outcome == "fail":
        overall_status = "hold"
    elif yield_outcome == "miss":
        overall_status = "investigate"
    else:
        overall_status = "pass"

    reasons: list[str] = []
    if cov_reason:
        reasons.append(cov_reason)
    if complement_trigger_fired:
        reasons.append(
            f"Complement trigger fired: no_match_rate {no_match_rate:.4f} > {COMPLEMENT_TRIGGER:.2f}"
        )
    if yield_outcome == "miss":
        reasons.append(
            f"Graph yield floor missed: presence rate {presence_rate:.4f} < {GRAPH_YIELD_INVESTIGATION_FLOOR:.2f}"
        )
    if is_suspended:
        reasons.append("Graph yield floor suspended due to unpopulated store baseline")

    final_reason = "; ".join(reasons) if reasons else None

    comparison_inputs = {
        "staged_pairing_coverage_floor": STAGED_PAIRING_COVERAGE_FLOOR,
        "graph_yield_investigation_floor": GRAPH_YIELD_INVESTIGATION_FLOOR,
        "complement_trigger": COMPLEMENT_TRIGGER,
        "locked_stage_size": locked_stage_size,
        "calibration_size": CALIBRATION_SIZE,
        "agreement_target": AGREEMENT_TARGET,
    }

    observed_values = {
        "n_pairs": n_pairs,
        "d44_staged_coverage": d44_staged_cov,
        "harness_pairing_coverage": harness_pairing_coverage,
        "distinct_questions_in_journal": distinct_q,
        "presence_rate": presence_rate,
        "no_match_rate": no_match_rate,
        "null_gold_drops": null_gold_drops,
    }

    return StagedGateVerdict(
        overall_status=overall_status,
        d44_staged_coverage=d44_staged_cov,
        harness_pairing_coverage=harness_pairing_coverage,
        distinct_questions_in_journal=distinct_q,
        d44_coverage_ceiling=d44_coverage_ceiling,
        d44_coverage_denominator=locked_stage_size,
        headroom_answerable_drops=headroom_drops,
        coverage_outcome=coverage_outcome,
        presence_rate=presence_rate,
        yield_outcome=yield_outcome,
        yield_suspended=is_suspended,
        no_match_rate=no_match_rate,
        complement_trigger_fired=complement_trigger_fired,
        reason=final_reason,
        comparison_inputs=comparison_inputs,
        observed_values=observed_values,
    )


def render_staged_gate_verdict(
    verdict: StagedGateVerdict,
    run_dir: Path | str,
) -> tuple[Path, Path]:
    """Write machine-readable and human-readable verdict files to the run directory."""
    out_dir = Path(run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "STAGED-GATE.json"
    md_path = out_dir / "STAGED-GATE.md"

    # Write JSON
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(verdict.model_dump_json(indent=2) + "\n")

    # Write Markdown
    cov_str = (
        f"{verdict.d44_staged_coverage:.4f}"
        if verdict.d44_staged_coverage is not None
        else "N/A"
    )
    md_lines = [
        f"# Staged Gate Evaluation Verdict: {verdict.overall_status.upper()}",
        "",
        "## Summary",
        f"- **Overall Status**: `{verdict.overall_status}`",
        f"- **Coverage Outcome**: `{verdict.coverage_outcome}`",
        f"- **Yield Outcome**: `{verdict.yield_outcome}`",
        f"- **Complement Trigger Fired**: `{verdict.complement_trigger_fired}`",
        f"- **Reason**: {verdict.reason or 'All gates passed.'}",
        "",
        "## Metrics Comparison",
        "| Metric | Observed | Floor / Threshold | Result |",
        "|---|---|---|---|",
        f"| D-44 Staged Coverage | {cov_str} | >= {verdict.comparison_inputs['staged_pairing_coverage_floor']:.2f} | {verdict.coverage_outcome} |",
        f"| Harness Pairing Coverage | {verdict.harness_pairing_coverage:.4f} | (journal-relative) | diagnostic |",
        f"| Graph Presence Rate | {verdict.presence_rate:.4f} | >= {verdict.comparison_inputs['graph_yield_investigation_floor']:.2f} | {verdict.yield_outcome} |",
        f"| No-Match Complement Rate | {verdict.no_match_rate:.4f} | <= {verdict.comparison_inputs['complement_trigger']:.2f} | {'TRIGGERED' if verdict.complement_trigger_fired else 'clean'} |",
        "",
        "## Coverage Ceiling & Headroom",
        f"- **Locked Stage Size**: {verdict.d44_coverage_denominator}",
        f"- **Distinct Questions in Journal**: {verdict.distinct_questions_in_journal}",
        f"- **Achievable Coverage Ceiling**: {verdict.d44_coverage_ceiling:.4f}",
        f"- **Headroom in Answerable Drops**: {verdict.headroom_answerable_drops}",
        "",
    ]

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    return json_path, md_path


def derive_judged_slice_size(
    judgeable_count: int,
    stage_spend_cap: float,
    cost_per_question: float,
    cached_verdict_count: int = 0,
) -> tuple[int, str]:
    """Derive judged slice size N from judgeable count and cap-derived bound.

    Returns (slice_size, binding_bound_description).
    Refuses a result below cached_verdict_count.
    """
    if judgeable_count <= 0:
        return 0, "judgeable_count_is_zero"

    if cost_per_question <= 0:
        n_cap = judgeable_count
    else:
        n_cap = int(stage_spend_cap // cost_per_question)

    if n_cap < cached_verdict_count or judgeable_count < cached_verdict_count:
        raise ValueError(
            f"Derived slice size cannot be below cached verdict count {cached_verdict_count}"
        )

    if n_cap < judgeable_count:
        binding = "cap"
        chosen = n_cap
    elif n_cap > judgeable_count:
        binding = "data"
        chosen = judgeable_count
    else:
        binding = "coincident"
        chosen = judgeable_count

    return chosen, binding
