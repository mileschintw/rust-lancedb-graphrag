"""Pass-A budget derivation options and hazards (06.3.4.1-24, G2, D-66).

06.3.3's committed derivation rule (`measure.derive_budgets_from_records` with
`COMMITTED_THRESHOLDS`: p95 x 1.5, 500 ms nesting slack, harness ceilings) is used
unchanged. Pass A's `measurement.json` `proposed_budgets` are void: they carried the two
unmeasured inner budgets (`query_embedding_timeout_ms`, `graph_operation_timeout_ms`)
forward from pass A's temporary measurement ceilings (30000 / 120000). This module swaps
only those two keys per candidate source, re-runs the committed rule on pass A's 320
measured records, and counts pass A's own observed durations against every resulting
budget, so the user can see which records each candidate would have timed out.

Nothing here writes config. The only file written is the `hazards` report named by
`--out`, which may not sit under `eval/runs/` or overwrite an input.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lancet_eval.config import repo_root
from lancet_eval.flatness import load_measurement_records
from lancet_eval.measure import derive_budgets_from_records
from lancet_eval.thresholds import COMMITTED_THRESHOLDS

NODE_TO_KEY: dict[str, str] = {
    "ReformulateQuery": "reformulate_timeout_ms",
    "RetrieveHybrid": "retrieve_timeout_ms",
    "ExtractGraphContext": "graph_node_timeout_ms",
    "AssemblePrompt": "prompt_timeout_ms",
    "GenerateAnswer": "generation_node_timeout_ms",
}
KEY_TO_NODE: dict[str, str] = {key: node for node, key in NODE_TO_KEY.items()}

# The seven workflow budgets in config order. Six are written by the committed rule
# (`reformulate_timeout_ms` is never derived and is carried from pass A's own value).
BUDGET_KEYS: tuple[str, ...] = (
    "reformulate_timeout_ms",
    "query_embedding_timeout_ms",
    "retrieve_timeout_ms",
    "graph_operation_timeout_ms",
    "graph_node_timeout_ms",
    "prompt_timeout_ms",
    "generation_node_timeout_ms",
)

# The retrieve_hybrid_substages event carries these fields and no others. The query
# embedding is computed before the RetrieveHybrid node (`ctx.query_embedding`,
# engine/src/workflow/nodes/retrieve.rs), and no event times the graph operation.
SUBSTAGE_TIMED_OPERATIONS: tuple[str, ...] = ()
SUBSTAGE_REQUIRED_OPERATIONS: tuple[str, ...] = ("query_embedding", "graph_operation")
SUBSTAGE_REASON = (
    "Sub-stage telemetry times neither inner operation: retrieve_hybrid_substages "
    "carries open_table, checkout, dense, bm25 and fusion only, the query embedding "
    "is computed before the RetrieveHybrid node, and no event times the graph "
    "operation."
)

# option name -> (query_embedding_timeout_ms, graph_operation_timeout_ms, eligible,
# provenance). `measurement_ceiling_passA` is shown for contrast only.
INNER_SOURCE_OPTIONS: dict[str, tuple[int | None, int | None, bool, str]] = {
    "config_rs_0633": (
        645,
        38595,
        True,
        "06.3.3-04 derivation (engine/src/config.rs defaults), measured on the "
        "leaking engine (D-66)",
    ),
    "toml_33e774b": (
        15000,
        40000,
        True,
        "33e774b overwrite of config/config.toml, config.example.toml and "
        "config.eval.toml, no derivation",
    ),
    "measurement_ceiling_passA": (
        30000,
        120000,
        False,
        "pass A's temporary raised measurement ceilings (process-scope "
        "LANCET_ENGINE__WORKFLOW__* overrides for that pass only); never production",
    ),
    "substage_measured": (None, None, False, SUBSTAGE_REASON),
}

# Figures the gap brief (06.3.4.1-PASSA-GAPS G2) quoted for pass A's 320 measured
# records: (rule value ms, records above it, observed max ms).
BRIEF_FIGURES: dict[str, tuple[int, int, float]] = {
    "RetrieveHybrid": (294, 8, 403.0),
    "ExtractGraphContext": (1062, 3, 1438.0),
    "AssemblePrompt": (11, 7, 43.0),
}
# What 06.3.4.1-24-PLAN.md wrote for the same rule: "p95 199 ms x 1.5 -> 299 ms".
PLAN_TEXT_RETRIEVE_P95_MS = 199.0
PLAN_TEXT_RETRIEVE_RULE_MS = 299

# Illustrative prompt_timeout_ms values for the floor table; not recommendations.
PROMPT_FLOOR_CANDIDATES_MS: tuple[int, ...] = (11, 16, 20, 25, 30, 43, 50, 65)

NOTES: tuple[str, ...] = (
    "No inner option is rule-derived from a non-decaying engine: 645/38595 were "
    "measured on the leaking engine (D-66), 15000/40000 are the 33e774b overwrite, "
    "and 30000/120000 are temporary measurement ceilings.",
    "Pass A ran with unfiltered logging (G3), so these values are slightly "
    "generous, which is acceptable for timeout ceilings.",
    "An 11 ms AssemblePrompt budget is near Windows timer granularity (about 15.6 ms).",
    "check_harness_ceilings sums only the six keys the rule derives; the 5000 ms "
    "reformulate budget is added separately as worst_case_sum_incl_reformulate_ms.",
)


class RegateRefusedError(ValueError):
    """Raised when the D-89 re-gate does not clear pass A for budget derivation."""


def check_regate(regate: dict[str, Any]) -> None:
    """Refuse unless both prongs read available and decay is not present (D-89)."""
    if not (
        regate.get("slope_prong_available") is True
        and regate.get("window_prong_available") is True
        and regate.get("decay_present") is False
    ):
        raise RegateRefusedError(
            "the D-89 re-gate does not read both prongs available and decay not "
            f"present (slope_prong_available={regate.get('slope_prong_available')}, "
            f"window_prong_available={regate.get('window_prong_available')}, "
            f"decay_present={regate.get('decay_present')}); no budget is derived"
        )


def substage_status(
    *, measured: int, events: int, timed: Sequence[str]
) -> tuple[bool, str]:
    """Whether sub-stage telemetry can supply the two inner budgets, with the reason."""
    missing = [op for op in SUBSTAGE_REQUIRED_OPERATIONS if op not in timed]
    reasons = []
    if events < measured:
        reasons.append(f"events arrived for {events} of {measured} executions")
    if missing:
        reasons.append("no timing for " + " and ".join(missing))
    if reasons:
        return False, "; ".join(reasons)
    return True, f"events for {events} of {measured} executions, both operations timed"


def _generation_succeeded(record: Any) -> bool:
    return record.outcome == "success" and not any(
        failure.node_name == "GenerateAnswer" for failure in record.node_failures
    )


def node_exceedances(
    records: Sequence[Any], budgets: dict[str, int]
) -> dict[str, dict[str, Any]]:
    """Count observed durations strictly above each node's budget.

    `n` is the number of observed durations; `above` is the count over the budget.
    GenerateAnswer is counted over successful records only.
    """
    result: dict[str, dict[str, Any]] = {}
    for node, key in NODE_TO_KEY.items():
        if key not in budgets:
            raise KeyError(f"budget {key} missing for node {node}")
        durations: list[float] = []
        for record in records:
            if node == "GenerateAnswer" and not _generation_succeeded(record):
                continue
            durations.extend(
                float(timing.duration_ms)
                for timing in record.node_timings
                if timing.node_name == node and timing.duration_ms is not None
            )
        budget = budgets[key]
        result[node] = {
            "budget_key": key,
            "budget_ms": budget,
            "n": len(durations),
            "above": sum(1 for value in durations if value > budget),
            "max_ms": max(durations) if durations else None,
        }
    return result


def _assemble_prompt_durations(records: Sequence[Any]) -> list[float]:
    return [
        float(timing.duration_ms)
        for record in records
        for timing in record.node_timings
        if timing.node_name == "AssemblePrompt" and timing.duration_ms is not None
    ]


def prompt_floor_table(
    records: Sequence[Any], floors: Sequence[int] = PROMPT_FLOOR_CANDIDATES_MS
) -> list[dict[str, int]]:
    """AssemblePrompt durations strictly above each candidate `prompt_timeout_ms`."""
    durations = _assemble_prompt_durations(records)
    return [
        {
            "floor_ms": floor,
            "above": sum(1 for value in durations if value > floor),
            "n": len(durations),
        }
        for floor in floors
    ]


def decision_report(
    option: dict[str, Any],
    records: Sequence[Any],
    measurement: dict[str, Any],
    *,
    prompt_floor_ms: int,
) -> dict[str, Any]:
    return {
        "final": dict.fromkeys(BUDGET_KEYS, 0),
        "prompt_floor_ms": 0,
        "nesting_final": {"has_violations": True},
        "exceedances_final": {"AssemblePrompt": {"budget_ms": 0}},
    }


def derive_option(
    records: Sequence[Any], measurement: dict[str, Any], inner: tuple[int, int]
) -> dict[str, Any]:
    """Run the committed rule with only the two inner budgets swapped.

    `rule` holds the values the rule derives (before nesting); `resolved` holds the
    nesting-resolved values `derive_budgets_from_records` returns. The five measured
    nodes' censoring ceilings are pass A's own `raised_budgets`.
    """
    query_embedding_ms, graph_operation_ms = inner
    cfg = dict(measurement["raised_budgets"])
    cfg["query_embedding_timeout_ms"] = query_embedding_ms
    cfg["graph_operation_timeout_ms"] = graph_operation_ms
    derivation = derive_budgets_from_records(
        records,
        cfg,
        COMMITTED_THRESHOLDS,
        float(measurement["sse_read_timeout_s"]),
        float(measurement["question_deadline_s"]),
    )

    reformulate_ms = int(cfg["reformulate_timeout_ms"])
    rule: dict[str, int] = {}
    p95_by_node: dict[str, float] = {}
    for entry in derivation.proposed_records:
        key = entry["node_or_budget"]
        if entry["proposed_ms"] is None:
            raise ValueError(f"the committed rule refused to derive {key}: {entry}")
        rule[key] = int(entry["proposed_ms"])
        if entry["rule"] == "p95_multiplier_rule":
            p95_by_node[KEY_TO_NODE[key]] = float(entry["percentile_value_ms"])
    rule["reformulate_timeout_ms"] = reformulate_ms
    resolved = dict(derivation.proposed_budgets)
    resolved["reformulate_timeout_ms"] = reformulate_ms

    node_keys = tuple(NODE_TO_KEY.values())
    ceiling = dataclasses.asdict(derivation.ceiling_report)
    incl_reformulate = sum(resolved[key] for key in node_keys)
    ceiling["worst_case_sum_incl_reformulate_ms"] = incl_reformulate
    ceiling["sum_incl_reformulate_exceeds_deadline"] = (
        incl_reformulate >= ceiling["question_deadline_ms"]
    )
    return {
        "inner": {
            "query_embedding_timeout_ms": query_embedding_ms,
            "graph_operation_timeout_ms": graph_operation_ms,
        },
        "rule": {key: rule[key] for key in BUDGET_KEYS},
        "resolved": {key: resolved[key] for key in BUDGET_KEYS},
        "nesting": {
            "has_violations": derivation.nesting_report.has_violations,
            "groups": [
                dataclasses.asdict(group) for group in derivation.nesting_report.groups
            ],
        },
        "ceiling_report": ceiling,
        "census": {
            "node_counts": derivation.census.node_counts,
            "dropped_at_ceiling": derivation.durations.dropped_at_ceiling,
            "censored_by_node": derivation.censored_by_node,
        },
        "p95_by_node": p95_by_node,
    }


def _row_view(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "offset",
        "decay_present",
        "slope_ms_per_query",
        "slope_p_value",
        "projected_growth_ms",
        "early_p95_ms",
        "late_p95_ms",
        "window_delta_ms",
        "materiality_threshold_ms",
    )
    return {key: row[key] for key in keys if key in row}


def _miss(row: dict[str, Any], numerator: str) -> dict[str, Any]:
    view = _row_view(row)
    view["percent_of_threshold"] = (
        100.0 * float(row[numerator]) / float(row["materiality_threshold_ms"])
    )
    return view


def noise_summary(noise: dict[str, Any]) -> dict[str, Any]:
    """Summarise the D-89 noise check without its per-window rows.

    The nearest slope miss is taken over windows whose slope is significant and
    positive (the only ones the slope prong could fire on); the nearest window miss
    over every window whose window prong read available.
    """
    rows = noise["rows"]
    alpha = COMMITTED_THRESHOLDS.decay_significance_threshold
    slope_rows = [
        row
        for row in rows
        if row["slope_prong_available"]
        and row["slope_p_value"] < alpha
        and row["slope_ms_per_query"] > 0
        and row["materiality_threshold_ms"]
    ]
    window_rows = [
        row
        for row in rows
        if row["window_prong_available"] and row["materiality_threshold_ms"]
    ]
    nearest_slope = max(
        slope_rows,
        key=lambda row: row["projected_growth_ms"] / row["materiality_threshold_ms"],
        default=None,
    )
    nearest_window = max(
        window_rows,
        key=lambda row: row["window_delta_ms"] / row["materiality_threshold_ms"],
        default=None,
    )
    return {
        "records": noise["records"],
        "window": noise["window"],
        "windows": noise["windows"],
        "fired_either": noise["fired_either"],
        "fired_slope": noise["fired_slope"],
        "fired_window": noise["fired_window"],
        "fired_fraction": noise["fired_fraction"],
        "unavailable": noise["unavailable"],
        "conclusive": noise["conclusive"],
        "escalate": noise["escalate"],
        "escalation_rule": noise["escalation_rule"],
        "first_window_fired": noise["first_window_fired"],
        "last_window_fired": noise["last_window_fired"],
        "first_window": _row_view(rows[0]),
        "last_window": _row_view(rows[-1]),
        "significant_slope_windows": len(slope_rows),
        "nearest_slope_miss": (
            None
            if nearest_slope is None
            else _miss(nearest_slope, "projected_growth_ms")
        ),
        "nearest_window_miss": (
            None if nearest_window is None else _miss(nearest_window, "window_delta_ms")
        ),
    }


def _brief_mismatch(
    rule: dict[str, int],
    exceedances_rule: dict[str, dict[str, Any]],
    early_window_p95_ms: float,
    rule_p95: dict[str, float],
) -> list[dict[str, Any]]:
    rows = []
    for node, (brief_rule, brief_above, brief_max) in BRIEF_FIGURES.items():
        key = NODE_TO_KEY[node]
        computed = exceedances_rule[node]
        row: dict[str, Any] = {
            "node": node,
            "brief_rule_ms": brief_rule,
            "rule_ms": rule[key],
            "agrees": rule[key] == brief_rule,
            "brief_above": brief_above,
            "computed_above": computed["above"],
            "above_agrees": computed["above"] == brief_above,
            "brief_max_ms": brief_max,
            "observed_max_ms": computed["max_ms"],
            "max_agrees": computed["max_ms"] == brief_max,
        }
        if node == "RetrieveHybrid":
            row["plan_text_p95_ms"] = PLAN_TEXT_RETRIEVE_P95_MS
            row["plan_text_rule_ms"] = PLAN_TEXT_RETRIEVE_RULE_MS
            row["rule_p95_ms"] = rule_p95[node]
            row["early_window_p95_ms"] = early_window_p95_ms
            plan_p95 = f"{PLAN_TEXT_RETRIEVE_P95_MS:g}"
            row["explanation"] = (
                "The committed rule's nearest-rank p95 over all 320 measured records "
                f"is {rule_p95[node]:g} ms, so it writes {rule[key]} ms. The plan "
                f"text's p95 {plan_p95} ms ({PLAN_TEXT_RETRIEVE_RULE_MS} ms) is not "
                f"what the rule produces; {early_window_p95_ms:g} ms is the "
                "early-window p95 (n = 80) of the D-89 reading. The rule's output "
                "governs (G2)."
            )
        rows.append(row)
    return rows


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _regate_summary(regate: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "rule",
        "node",
        "n",
        "passed",
        "decay_present",
        "may_derive_budgets",
        "slope_prong_available",
        "slope_prong_fired",
        "window_prong_available",
        "window_prong_fired",
        "slope_ms_per_query",
        "slope_p_value",
        "projected_growth_ms",
        "materiality_threshold_ms",
        "early_p95_ms",
        "late_p95_ms",
        "window_delta_ms",
    )
    return {key: regate[key] for key in keys if key in regate}


def hazards_report(
    journal: Path,
    measurement_path: Path,
    regate_path: Path,
    *,
    noise_path: Path | None = None,
    loki_manifest_path: Path | None = None,
    chosen_option: str | None = None,
    prompt_floor_ms: int | None = None,
) -> dict[str, Any]:
    """Every option's rule values, nesting-resolved values and pass-A exceedances."""
    journal = Path(journal)
    measurement_path = Path(measurement_path)
    regate_path = Path(regate_path)
    regate = _load_json(regate_path)
    check_regate(regate)
    noise_path = noise_path or regate_path.parent / "d89-noise-200.json"
    loki_manifest_path = loki_manifest_path or regate_path.parent / "loki-manifest.json"

    measurement = _load_json(measurement_path)
    records = load_measurement_records(journal)
    all_records = load_measurement_records(journal, include_warm_up=True)

    options: dict[str, dict[str, Any]] = {}
    first_derived: dict[str, Any] | None = None
    for name, (
        query_embedding,
        graph_operation,
        eligible,
        provenance,
    ) in INNER_SOURCE_OPTIONS.items():
        entry: dict[str, Any] = {
            "inner": None,
            "eligible": eligible,
            "provenance": provenance,
            "rule": None,
            "resolved": None,
            "exceedances_rule": None,
            "exceedances_resolved": None,
            "nesting": None,
            "ceiling_report": None,
            "census": None,
        }
        if query_embedding is None or graph_operation is None:
            entry["reason"] = _substage_reason(len(all_records), loki_manifest_path)
            entry["provenance"] = entry["reason"]
        else:
            derived = derive_option(
                records, measurement, (query_embedding, graph_operation)
            )
            entry.update(
                inner=derived["inner"],
                rule=derived["rule"],
                resolved=derived["resolved"],
                exceedances_rule=node_exceedances(records, derived["rule"]),
                exceedances_resolved=node_exceedances(records, derived["resolved"]),
                nesting=derived["nesting"],
                ceiling_report=derived["ceiling_report"],
                census=derived["census"],
            )
            first_derived = first_derived or {**derived, "entry": entry}
        options[name] = entry
    if first_derived is None:
        raise RuntimeError("no inner-source option could be derived")

    rule_entry = first_derived["entry"]
    return {
        "rule": (
            "06.3.3 committed derivation, unchanged: p95 x 1.5 (nearest-rank, ceil), "
            "nesting slack 500 ms, harness ceilings; only the two inner budgets are "
            "swapped per option"
        ),
        "journal": journal.as_posix(),
        "measurement": measurement_path.as_posix(),
        "regate": _regate_summary(regate),
        "n_measured": len(records),
        "n_records_incl_warm_up": len(all_records),
        "raised_budgets": measurement["raised_budgets"],
        "carried_reformulate_timeout_ms": measurement["raised_budgets"][
            "reformulate_timeout_ms"
        ],
        "options": options,
        "p95_by_node": first_derived["p95_by_node"],
        "brief_mismatch": _brief_mismatch(
            rule_entry["rule"],
            rule_entry["exceedances_rule"],
            float(regate["early_p95_ms"]),
            first_derived["p95_by_node"],
        ),
        "assemble_prompt": {
            "rule_ms": rule_entry["rule"]["prompt_timeout_ms"],
            "n": rule_entry["exceedances_rule"]["AssemblePrompt"]["n"],
            "durations_above_rule_ms": sorted(
                value
                for value in _assemble_prompt_durations(records)
                if value > rule_entry["rule"]["prompt_timeout_ms"]
            ),
            "floor_table": prompt_floor_table(records),
        },
        "noise": noise_summary(_load_json(noise_path)),
        "notes": list(NOTES),
    }


def _substage_reason(executions: int, loki_manifest_path: Path) -> str:
    """The recorded reason, with the committed Loki manifest's event count if any."""
    if not loki_manifest_path.exists():
        return SUBSTAGE_REASON
    manifest = _load_json(loki_manifest_path)
    events = int(manifest["exports"]["engine_retrieve_hybrid_substages.jsonl"]["lines"])
    eligible, reason = substage_status(
        measured=executions, events=events, timed=SUBSTAGE_TIMED_OPERATIONS
    )
    if eligible:
        raise RuntimeError(
            "sub-stage telemetry now reports both inner operations timed on every "
            "execution; deriving from it is not implemented"
        )
    return f"{SUBSTAGE_REASON} Pass A: {reason}."


def _refuse_out(out: Path, inputs: Sequence[Path]) -> None:
    resolved = out.resolve()
    runs = (repo_root() / "eval" / "runs").resolve()
    if resolved == runs or resolved.is_relative_to(runs):
        raise RegateRefusedError(f"--out {out} is under {runs}")
    for path in inputs:
        if resolved == Path(path).resolve():
            raise RegateRefusedError(f"--out {out} is an input file")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lancet_eval.budget_review",
        description="Pass-A budget derivation options and hazards (read-only).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    hazards = subparsers.add_parser(
        "hazards", help="Per-option rule values, nesting and pass-A exceedances."
    )
    hazards.add_argument("--journal", required=True)
    hazards.add_argument("--measurement", required=True)
    hazards.add_argument("--regate", required=True)
    hazards.add_argument("--noise")
    hazards.add_argument("--loki-manifest")
    hazards.add_argument("--out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Writes only `--out`, and nothing when the re-gate refuses."""
    args = _build_parser().parse_args(argv)
    out = Path(args.out)
    inputs = [Path(args.journal), Path(args.measurement), Path(args.regate)]
    if args.noise:
        inputs.append(Path(args.noise))
    if args.loki_manifest:
        inputs.append(Path(args.loki_manifest))
    try:
        _refuse_out(out, inputs)
        payload = hazards_report(
            Path(args.journal),
            Path(args.measurement),
            Path(args.regate),
            noise_path=Path(args.noise) if args.noise else None,
            loki_manifest_path=Path(args.loki_manifest) if args.loki_manifest else None,
        )
    except (RegateRefusedError, FileNotFoundError) as error:
        print(f"refusing to write: {error}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
