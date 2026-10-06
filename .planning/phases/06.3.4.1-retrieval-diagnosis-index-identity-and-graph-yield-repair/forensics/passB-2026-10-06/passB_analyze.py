"""06.3.4.1-18 pass B analysis: graph budget derivation and report-only readings.

Read-only over the pass B journal and `measurement.json`. It derives
`graph_operation_timeout_ms` with the committed rule (`latency.percentile_with_ci` then
`latency.derive_budget` under `COMMITTED_THRESHOLDS`, p95 x 1.5), re-runs the nesting and
harness-ceiling checks over all seven budgets, and computes the extra readings the user
asked for on 2026-10-06 that need no engine and no database: graph-on `RetrieveHybrid`
p95 against the retrieve budget, the graph-on prompt-token maximum, the seeding
diagnostic distributions, the `ExtractGraphContext` slope and the `GRAPH_TIMEOUT` rate.

Usage: uv run --project eval python <this file> <run_dir> <out_json>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from lancet_eval.decay_materiality import analyze_material_decay
from lancet_eval.flatness import load_measurement_records
from lancet_eval.latency import (
    check_harness_ceilings,
    check_nesting_invariants,
    derive_budget,
    percentile_with_ci,
)
from lancet_eval.measure import compute_spend
from lancet_eval.thresholds import COMMITTED_THRESHOLDS

# The seven committed budgets before pass B (BUDGETS "D-93 amendment"): only
# graph_operation_timeout_ms is swapped by the derivation.
COMMITTED_BUDGETS: dict[str, int] = {
    "reformulate_timeout_ms": 5000,
    "query_embedding_timeout_ms": 2000,
    "retrieve_timeout_ms": 2500,
    "graph_operation_timeout_ms": 10000,
    "graph_node_timeout_ms": 12500,
    "prompt_timeout_ms": 120,
    "generation_node_timeout_ms": 65000,
}
GRAPH_NODE = "ExtractGraphContext"
RETRIEVE_NODE = "RetrieveHybrid"
EVIDENCE_TOKEN_BUDGET = 8192


def durations(records: list[Any], node: str) -> list[float]:
    """Observed durations of one node across records, in record order."""
    out: list[float] = []
    for rec in records:
        for t in rec.node_timings:
            if t.node_name == node and t.duration_ms is not None:
                out.append(float(t.duration_ms))
    return out


def stats(values: list[float]) -> dict[str, Any]:
    """Nearest-rank summary of a duration list, empty-safe."""
    if not values:
        return {"n": 0}
    pct = percentile_with_ci(values, p=0.95, seed=42)
    ordered = sorted(values)
    return {
        "n": len(values),
        "median_ms": ordered[len(ordered) // 2],
        "p95_nearest_rank_ms": pct.percentile,
        "p95_ci_low_ms": pct.ci_low,
        "p95_ci_high_ms": pct.ci_high,
        "max_ms": ordered[-1],
    }


def renumber(records: list[Any]) -> list[Any]:
    """Return copies with ordinals 1..n in order, as the D-92 loader does."""
    return [r.model_copy(update={"ordinal": i}) for i, r in enumerate(records, 1)]


def decay_summary(records: list[Any], node: str) -> dict[str, Any]:
    """D-89 material-decay reading of one node over the given records."""
    verdict = analyze_material_decay(renumber(records), node_name=node)
    payload = verdict.to_dict()
    payload["node"] = node
    payload["n"] = len(records)
    return payload


def distribution(values: list[int | float | bool]) -> dict[str, Any]:
    """Min, median, p95, max, mean and a value histogram for small integer series."""
    if not values:
        return {"n": 0}
    nums = [float(v) for v in values]
    ordered = sorted(nums)
    n = len(ordered)
    return {
        "n": n,
        "min": ordered[0],
        "median": ordered[n // 2],
        "p95": ordered[max(0, min(n - 1, -(-95 * n // 100) - 1))],
        "max": ordered[-1],
        "mean": sum(nums) / n,
        "histogram": dict(sorted(Counter(int(v) for v in nums).items())),
    }


def main(run_dir: Path, out_path: Path) -> None:
    journal = run_dir / "journal.jsonl"
    measurement = json.loads((run_dir / "measurement.json").read_text("utf-8"))
    all_records = load_measurement_records(journal, include_warm_up=True)
    measured = [r for r in all_records if not r.warm_up]
    warm = [r for r in all_records if r.warm_up]
    on = [r for r in measured if r.graph_arm == "graph-on"]
    off = [r for r in measured if r.graph_arm == "graph-off"]
    warm_on = [r for r in warm if r.graph_arm == "graph-on"]

    ceilings = measurement["raised_budgets"]
    graph_node_ceiling = float(ceilings["graph_node_timeout_ms"])

    # Graph budget derivation (reply 2): the graph-on ExtractGraphContext node duration is
    # an upper-bound proxy for the graph operation, because it includes the query embedding.
    on_graph = durations(on, GRAPH_NODE)
    survivors = [d for d in on_graph if d < graph_node_ceiling]
    censored = len(on_graph) - len(survivors)
    pct = percentile_with_ci(
        survivors, p=COMMITTED_THRESHOLDS.derivation_percentile,
        seed=COMMITTED_THRESHOLDS.bootstrap_seed, censored_count=censored,
    )
    derived = derive_budget("graph_operation_timeout_ms", pct, thresholds=COMMITTED_THRESHOLDS)
    over_budget = [d for d in on_graph if d > derived.proposed_ms]
    proposed = dict(COMMITTED_BUDGETS)
    proposed["graph_operation_timeout_ms"] = derived.proposed_ms
    nesting = check_nesting_invariants(proposed, required_slack_ms=COMMITTED_THRESHOLDS.slack_ms)
    harness = check_harness_ceilings(
        nesting.resolved_budgets,
        sse_read_timeout_s=measurement["sse_read_timeout_s"],
        question_deadline_s=measurement["question_deadline_s"],
    )

    # GRAPH_TIMEOUT: the engine's own graph-operation timeout notice, graph-on records.
    notice_counts: Counter[str] = Counter()
    graph_timeout = 0
    for r in on:
        for n in r.notices:
            code = str(getattr(n, "code", n))
            notice_counts[code] += 1
            if "TIMEOUT" in code.upper() and "GRAPH" in code.upper():
                graph_timeout += 1

    wm_on = [r.workflow_meta for r in on if r.workflow_meta is not None]
    wm_off = [r.workflow_meta for r in off if r.workflow_meta is not None]
    prompt_tokens_on = [w.prompt_tokens for w in wm_on if w.prompt_tokens]
    retrieve_on = durations(on, RETRIEVE_NODE)
    retrieve_budget = COMMITTED_BUDGETS["retrieve_timeout_ms"]
    spend, is_lower = compute_spend(all_records, include_embeddings=True)

    payload = {
        "run_dir": str(run_dir),
        "records": {"total": len(all_records), "warm_up": len(warm),
                    "measured": len(measured), "graph_on": len(on), "graph_off": len(off)},
        "outcomes": {f"{a}:{o}": c for (a, o), c in sorted(
            Counter((r.graph_arm, r.outcome) for r in measured).items())},
        "spend_estimate_usd": spend, "spend_estimate_is_lower_bound": is_lower,
        "graph_budget_derivation": {
            "proxy": "graph-on ExtractGraphContext node duration (includes the query embedding)",
            "censoring_ceiling_ms": graph_node_ceiling,
            "n_observed": len(on_graph), "n_censored_at_ceiling": censored,
            "p95_nearest_rank_ms": pct.percentile,
            "p95_ci_ms": [pct.ci_low, pct.ci_high],
            "multiplier": derived.multiplier,
            "derived_graph_operation_timeout_ms": derived.proposed_ms,
            "recompute_matches": derived.recompute() == derived.proposed_ms,
            "over_budget_count": len(over_budget),
            "over_budget_share": len(over_budget) / len(on_graph) if on_graph else None,
            "max_tolerated_over_budget_share": COMMITTED_THRESHOLDS.max_tolerated_graph_timeout_rate,
            "over_budget_values_ms": sorted(over_budget),
            "graph_timeout_notices_in_graph_on_records": graph_timeout,
            "graph_timeout_note": "reads 0 by construction: the engine ran at the 120000 ms graph_operation ceiling",
        },
        "warm_up_graph_on_extract_graph_context_ms": durations(warm_on, GRAPH_NODE),
        "first_five_measured_graph_on_extract_graph_context_ms": on_graph[:5],
        "nesting": {
            "proposed_input": proposed,
            "has_violations": nesting.has_violations,
            "resolved_budgets": nesting.resolved_budgets,
            "groups": [g.__dict__ for g in nesting.groups],
        },
        "harness_ceilings": harness.__dict__,
        "node_stats_ms": {
            f"{arm}:{node}": stats(durations(recs, node))
            for arm, recs in (("graph-on", on), ("graph-off", off))
            for node in ("ReformulateQuery", GRAPH_NODE, RETRIEVE_NODE, "AssemblePrompt")
        },
        "reading_a_retrieve_hybrid_graph_on": {
            **stats(retrieve_on),
            "retrieve_timeout_ms": retrieve_budget,
            "p95_exceeds_budget": bool(retrieve_on) and percentile_with_ci(retrieve_on, p=0.95, seed=42).percentile > retrieve_budget,
            "max_exceeds_budget": bool(retrieve_on) and max(retrieve_on) > retrieve_budget,
            "count_above_budget": sum(1 for d in retrieve_on if d > retrieve_budget),
            "rule_value_p95_x_1_5_ms": (
                -(-int(percentile_with_ci(retrieve_on, p=0.95, seed=42).percentile * 15) // 10)
                if retrieve_on else None),
        },
        "reading_c_prompt_tokens_graph_on": {
            "n": len(prompt_tokens_on),
            "max": max(prompt_tokens_on) if prompt_tokens_on else None,
            "p95": (sorted(prompt_tokens_on)[max(0, -(-95 * len(prompt_tokens_on) // 100) - 1)]
                    if prompt_tokens_on else None),
            "evidence_token_budget": EVIDENCE_TOKEN_BUDGET,
            "max_exceeds_budget": bool(prompt_tokens_on) and max(prompt_tokens_on) > EVIDENCE_TOKEN_BUDGET,
            "note": "prompt_tokens is the provider-reported prompt size (includes the template), reported against 8192 as asked",
        },
        "distributions_graph_on": {
            "graph_seed_count": distribution([w.graph_seed_count for w in wm_on if w.graph_seed_count is not None]),
            "graph_path_found_rate": (sum(1 for w in wm_on if w.graph_path_found) / len(wm_on)) if wm_on else None,
            "graph_boosted_chunk_count": distribution([w.graph_boosted_chunk_count for w in wm_on if w.graph_boosted_chunk_count is not None]),
            "graph_prompt_fact_count": distribution([w.graph_prompt_fact_count for w in wm_on if w.graph_prompt_fact_count is not None]),
            "graph_degree_capped_count": distribution([w.graph_degree_capped_count for w in wm_on if w.graph_degree_capped_count is not None]),
            "graph_node_count": distribution([w.graph_node_count for w in wm_on]),
            "records_with_any_boosted_chunk": sum(1 for w in wm_on if (w.graph_boosted_chunk_count or 0) > 0),
            "records_with_path": sum(1 for w in wm_on if w.graph_path_found),
            "notice_codes": dict(sorted(notice_counts.items())),
        },
        "distributions_graph_off_must_be_zero": {
            "any_seed": sum(1 for w in wm_off if (w.graph_seed_count or 0) > 0),
            "any_path": sum(1 for w in wm_off if w.graph_path_found),
            "any_boosted": sum(1 for w in wm_off if (w.graph_boosted_chunk_count or 0) > 0),
        },
        "extract_graph_context_slope": {
            "all_measured_records": decay_summary(measured, GRAPH_NODE),
            "graph_on_only": decay_summary(on, GRAPH_NODE),
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", "utf-8")
    print(json.dumps({k: payload[k] for k in ("records", "outcomes", "graph_budget_derivation", "nesting", "harness_ceilings")}, indent=1, default=str))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
