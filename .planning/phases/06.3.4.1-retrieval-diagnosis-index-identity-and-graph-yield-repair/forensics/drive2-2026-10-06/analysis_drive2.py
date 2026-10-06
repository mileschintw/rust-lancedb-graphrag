"""Drive 2 extra readings (06.3.4.1-19 Task 2). Read-only on the run directory.

Adds, beside `unpark_gates --stage drive2` and `diagnostic table`:
  - the generic drive-1b counts (errors, tokens, flatness detail);
  - graph-on wire distributions (seeds, path, boosted chunks, prompt facts, degree caps);
  - `GRAPH_TIMEOUT` and `GRAPH_UNAVAILABLE` notice counts, kept separate, by ordinal;
  - the graph-step durations against the 2424 ms graph-operation budget. The journal's
    graph-step duration is the `ExtractGraphContext` NODE, which includes the query
    embedding, so it is an upper-bound PROXY for the operation the budget bounds;
  - column (d) rates and the AI-SPEC section 7 smart-sampling lists.

Usage: uv run --project eval python analysis_drive2.py <RUN> <out.json>
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from lancet_eval.decay_materiality import analyze_material_decay
from lancet_eval.flatness import flatness_verdict, records_from_run_journal
from lancet_eval.journal import load_records
from lancet_eval.measure import compute_spend
from lancet_eval.pairing import deduplicate_by_arm, form_pairs
from lancet_eval.corpus import load_sample_questions
from lancet_eval.stats import wilson_ci
from lancet_eval.unpark_gates import _composition_change

GRAPH_OPERATION_BUDGET_MS = 2424
GRAPH_NODE = "ExtractGraphContext"


def med(vals: list[Any]) -> Any:
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def dist(values: list[Any]) -> dict[str, Any]:
    nums = sorted(float(v) for v in values if v is not None)
    if not nums:
        return {"n": 0}
    n = len(nums)
    return {
        "n": n,
        "min": nums[0],
        "median": nums[n // 2],
        "p95": nums[max(0, -(-95 * n // 100) - 1)],
        "max": nums[-1],
        "mean": sum(nums) / n,
        "histogram": dict(sorted(Counter(int(v) for v in nums).items())),
    }


def rate(k: int, n: int) -> dict[str, Any]:
    if n <= 0:
        return {"k": k, "n": n, "rate": None, "wilson": None}
    p, lo, hi = wilson_ci(k, n)
    return {"k": k, "n": n, "rate": float(p), "wilson": [float(lo), float(hi)]}


def main(run: Path, out_path: Path) -> None:
    out: dict[str, Any] = {}
    journal = run / "journal.jsonl"

    recs = records_from_run_journal(journal)
    fv = flatness_verdict(recs)
    mat = analyze_material_decay(recs, node_name="RetrieveHybrid")
    out["flatness"] = {
        "passed": fv.passed,
        "reason": fv.reason,
        "n": fv.n,
        "trend_available": fv.trend_available,
        "window_available": fv.window_available,
        "decay_present": fv.decay_present,
        "slope": fv.slope_ms_per_query,
        "projected_growth_658": fv.projected_growth_ms,
        "window_delta": fv.window_delta_ms,
        "threshold": fv.materiality_threshold_ms,
        "censored": fv.censored_count,
        "unusable": fv.unusable_dropped_count,
        "slice_medians": fv.slice_medians_ms,
        "material": {
            k: getattr(mat, k)
            for k in (
                "slope_prong_available",
                "slope_prong_fired",
                "window_prong_available",
                "window_prong_fired",
                "slope_ms_per_query",
                "slope_p_value",
                "projected_growth_ms",
                "early_p95_ms",
                "late_p95_ms",
                "window_delta_ms",
                "materiality_threshold_ms",
                "censored_count",
                "unusable_dropped_count",
            )
        },
    }

    raw = [json.loads(line) for line in open(journal, encoding="utf-8") if line.strip()]
    header = raw[0] if raw and raw[0].get("type") == "header" else {}
    out["header"] = header
    r = [x for x in raw if isinstance(x, dict) and x.get("question_id")]
    out["records"] = len(r)
    out["questions"] = len({x["question_id"] for x in r})
    out["outcomes"] = dict(Counter(x["outcome"] for x in r))
    out["errors_by_arm"] = {
        a: sum(1 for x in r if x["graph_arm"] == a and x["outcome"] != "success")
        for a in ("graph-off", "graph-on")
    }
    out["error_types"] = dict(Counter(str(x.get("error_type")) for x in r if x["outcome"] != "success"))
    out["node_failures_total"] = sum(len(x.get("node_failures") or []) for x in r)

    def wm(x: dict, key: str) -> Any:
        return (x.get("workflow_meta") or {}).get(key)

    for arm in ("graph-off", "graph-on", None):
        sel = [x for x in r if arm is None or x["graph_arm"] == arm]
        tag = arm or "all"
        out[f"median_prompt_tokens_{tag}"] = med([wm(x, "prompt_tokens") for x in sel])
        out[f"max_prompt_tokens_{tag}"] = max([wm(x, "prompt_tokens") for x in sel if wm(x, "prompt_tokens") is not None] or [None])
        out[f"median_completion_tokens_{tag}"] = med([wm(x, "completion_tokens") for x in sel])
        out[f"median_duration_ms_{tag}"] = med([x.get("duration_ms") for x in sel])
    cts = [wm(x, "completion_tokens") for x in r if wm(x, "completion_tokens") is not None]
    out["max_completion_tokens"] = max(cts) if cts else None
    out["answers_with_linebreak"] = sum(1 for x in r if "\n" in (x.get("answer") or ""))
    out["answers_nonempty"] = sum(1 for x in r if (x.get("answer") or "").strip())

    # Notices: GRAPH_TIMEOUT and GRAPH_UNAVAILABLE stay separate (the graph operation's
    # timeout degrades silently to chunk-only context; UNAVAILABLE is "no graph entities").
    notice_codes: dict[str, Counter] = {"graph-off": Counter(), "graph-on": Counter()}
    timeout_rows: list[dict[str, Any]] = []
    unavailable_rows: list[dict[str, Any]] = []
    for idx, x in enumerate(r, 1):
        for n in x.get("notices") or []:
            code = str(n.get("code") if isinstance(n, dict) else n)
            notice_codes[x["graph_arm"]][code] += 1
            row = {"ordinal": idx, "question_id": x["question_id"], "graph_arm": x["graph_arm"]}
            if code == "GRAPH_TIMEOUT":
                timeout_rows.append(row)
            elif code == "GRAPH_UNAVAILABLE":
                unavailable_rows.append(row)
    out["notice_codes_by_arm"] = {a: dict(sorted(c.items())) for a, c in notice_codes.items()}
    gon = [x for x in r if x["graph_arm"] == "graph-on"]
    goff = [x for x in r if x["graph_arm"] == "graph-off"]
    out["graph_timeout"] = {
        "count": len(timeout_rows),
        "rate_over_graph_on_records": rate(len(timeout_rows), len(gon)),
        "tolerance": 0.10,
        "by_ordinal": timeout_rows,
    }
    out["graph_unavailable"] = {
        "count": len(unavailable_rows),
        "rate_over_graph_on_records": rate(len(unavailable_rows), len(gon)),
        "by_ordinal": unavailable_rows,
    }

    # Graph-step durations (proxy) against the committed graph-operation budget.
    def node_ms(x: dict, name: str) -> float | None:
        for t in x.get("node_timings") or []:
            if isinstance(t, dict) and t.get("node_name") == name and t.get("duration_ms") is not None:
                return float(t["duration_ms"])
        return None

    gdur = [(idx, x, node_ms(x, GRAPH_NODE)) for idx, x in enumerate(r, 1) if x["graph_arm"] == "graph-on"]
    vals = sorted(d for _, _, d in gdur if d is not None)
    over = [(idx, x["question_id"], d) for idx, x, d in gdur if d is not None and d > GRAPH_OPERATION_BUDGET_MS]
    out["graph_step_durations_proxy"] = {
        "label": (
            "ExtractGraphContext NODE duration (includes the query embedding): an upper-bound "
            "proxy for the graph operation that graph_operation_timeout_ms bounds; only the "
            "graph_traversal span in Jaeger is the bounded operation itself"
        ),
        "budget_ms": GRAPH_OPERATION_BUDGET_MS,
        "n": len(vals),
        "median_ms": med(vals),
        "p95_ms": vals[max(0, -(-95 * len(vals) // 100) - 1)] if vals else None,
        "max_ms": vals[-1] if vals else None,
        "count_over_budget": len(over),
        "over_budget": [{"ordinal": i, "question_id": q, "ms": d} for i, q, d in over],
        "count_ge_90pct_of_budget": sum(1 for d in vals if d >= 0.9 * GRAPH_OPERATION_BUDGET_MS),
    }
    # Records with seeds but no graph nodes and no graph timeout notice: silent-degrade candidates.
    out["graph_on_seeds_but_no_nodes"] = [
        {"ordinal": idx, "question_id": x["question_id"], "seeds": wm(x, "graph_seed_count"), "node_ms": d}
        for idx, x, d in gdur
        if (wm(x, "graph_seed_count") or 0) > 0 and (wm(x, "graph_node_count") or 0) == 0
    ]

    # Graph-on wire distributions.
    out["graph_on_distributions"] = {
        "graph_seed_count": dist([wm(x, "graph_seed_count") for x in gon]),
        "graph_node_count": dist([wm(x, "graph_node_count") for x in gon]),
        "graph_edge_count": dist([wm(x, "graph_edge_count") for x in gon]),
        "graph_prompt_fact_count": dist([wm(x, "graph_prompt_fact_count") for x in gon]),
        "graph_boosted_chunk_count": dist([wm(x, "graph_boosted_chunk_count") for x in gon]),
        "graph_degree_capped_count": dist([wm(x, "graph_degree_capped_count") for x in gon]),
        "path_found": rate(sum(1 for x in gon if wm(x, "graph_path_found")), len(gon)),
        "any_boosted_chunk": rate(sum(1 for x in gon if (wm(x, "graph_boosted_chunk_count") or 0) > 0), len(gon)),
        "any_prompt_fact": rate(sum(1 for x in gon if (wm(x, "graph_prompt_fact_count") or 0) > 0), len(gon)),
        "any_graph_node": rate(sum(1 for x in gon if (wm(x, "graph_node_count") or 0) > 0), len(gon)),
        "records_at_max_path_facts_8": sum(1 for x in gon if (wm(x, "graph_prompt_fact_count") or 0) >= 8),
    }
    out["graph_off_must_be_zero"] = {
        "any_seed": sum(1 for x in goff if (wm(x, "graph_seed_count") or 0) > 0),
        "any_path": sum(1 for x in goff if wm(x, "graph_path_found")),
        "any_boosted": sum(1 for x in goff if (wm(x, "graph_boosted_chunk_count") or 0) > 0),
        "any_graph_node": sum(1 for x in goff if (wm(x, "graph_node_count") or 0) > 0),
        "n": len(goff),
    }

    # Table-derived readings.
    table = [json.loads(line) for line in open(run / "diagnostic" / "table.jsonl", encoding="utf-8") if line.strip()]

    def arm(t: dict, a: str) -> dict:
        return (t.get("arms") or {}).get(a) or {}

    nonnull = [t for t in table if not t.get("is_null")]
    d_eval = [t for t in nonnull if t.get("d_graph_seed_hit") is not None]
    d_yes = [t for t in d_eval if t["d_graph_seed_hit"]]
    out["d_seed_hit"] = {
        "all_answerable": rate(len(d_yes), len(d_eval)),
        "in_G": rate(
            sum(1 for t in d_eval if t.get("in_gold_in_index_subset") and t["d_graph_seed_hit"]),
            sum(1 for t in d_eval if t.get("in_gold_in_index_subset")),
        ),
        "in_V": rate(
            sum(1 for t in d_eval if t.get("in_gold_in_index_subset") and t.get("c_gold_in_vector_top4") is True and t["d_graph_seed_hit"]),
            sum(1 for t in d_eval if t.get("in_gold_in_index_subset") and t.get("c_gold_in_vector_top4") is True),
        ),
    }
    out["seed_count_table"] = dist([t.get("seed_count") for t in table])
    out["path_found_table"] = rate(sum(1 for t in table if t.get("path_found")), sum(1 for t in table if t.get("path_found") is not None))

    # Pairing and composition (for "(d) yes with no composition change").
    gold = {q.question_id: q for q in load_sample_questions(header.get("corpus") or "multihop_rag_diag")}
    records, _ = deduplicate_by_arm(load_records(journal))
    join = form_pairs(records, gold)
    comp = _composition_change(join.pairs)
    measured_ids = []
    for p in join.pairs:
        snap = p.graph_on.snapshot
        chunks = snap.retrieved_chunks if snap is not None else []
        if snap is None or (chunks and all(c.graph_boosted is None for c in chunks)):
            continue
        measured_ids.append(p.question_id)
    changed = set(comp["changed_ids"])
    d_yes_ids = {t["question_id"] for t in d_yes}
    out["d_yes_no_composition_change"] = sorted(q for q in measured_ids if q in d_yes_ids and q not in changed)
    out["d_yes_composition_change"] = sorted(q for q in measured_ids if q in d_yes_ids and q in changed)
    out["composition_pairs_A"] = {k: comp[k] for k in ("n", "changed_n", "rate", "ci_lower", "ci_upper", "unmeasured_n")}

    off_usable = {t["question_id"]: arm(t, "graph-off").get("answer_usable") for t in table}
    flipped = []
    gained = []
    for t in nonnull:
        a_off, a_on = arm(t, "graph-off"), arm(t, "graph-on")
        if a_off.get("outcome") == "success" and a_on.get("outcome") == "success":
            if a_off.get("answer_usable") and not a_on.get("answer_usable"):
                flipped.append(t["question_id"])
            if not a_off.get("answer_usable") and a_on.get("answer_usable"):
                gained.append(t["question_id"])
    out["graph_on_e_flipped_yes_to_no"] = sorted(flipped)
    out["graph_on_e_flipped_no_to_yes"] = sorted(gained)
    out["graph_on_usable"] = [
        sum(1 for t in nonnull if arm(t, "graph-on").get("outcome") == "success" and arm(t, "graph-on").get("answer_usable")),
        sum(1 for t in nonnull if arm(t, "graph-on").get("outcome") == "success"),
    ]
    out["graph_off_usable_answerable"] = [
        sum(1 for t in nonnull if arm(t, "graph-off").get("outcome") == "success" and arm(t, "graph-off").get("answer_usable")),
        sum(1 for t in nonnull if arm(t, "graph-off").get("outcome") == "success"),
    ]
    G = [t for t in nonnull if arm(t, "graph-off").get("outcome") == "success"]
    out["c_yes_e_no_graph_off"] = sorted(
        t["question_id"] for t in G if t.get("c_gold_in_vector_top4") is True and not arm(t, "graph-off").get("answer_usable")
    )
    out["final_answer_missing"] = {
        a: sum(1 for t in nonnull if arm(t, a).get("final_answer_missing")) for a in ("graph-off", "graph-on")
    }
    out["final_answer_missing_n"] = {
        a: sum(1 for t in nonnull if arm(t, a).get("outcome") == "success") for a in ("graph-off", "graph-on")
    }
    out["null_final_answers"] = {
        a: dict(Counter(str(arm(t, a).get("final_answer")) for t in table if t.get("is_null"))) for a in ("graph-off", "graph-on")
    }
    out["error_classes"] = dict(
        Counter(
            f"{a}:{arm(t, a).get('error_class')}"
            for t in table
            for a in ("graph-off", "graph-on")
            if arm(t, a).get("outcome") == "error"
        )
    )
    spend, lower = compute_spend(load_records(journal), include_embeddings=True)
    out["spend_estimate_usd"] = spend
    out["spend_estimate_is_lower_bound"] = lower
    out["_off_usable_n"] = len(off_usable)
    out.pop("_off_usable_n")
    out_path.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("records", "outcomes", "graph_timeout", "graph_step_durations_proxy", "d_seed_hit")}, indent=1, default=str))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
