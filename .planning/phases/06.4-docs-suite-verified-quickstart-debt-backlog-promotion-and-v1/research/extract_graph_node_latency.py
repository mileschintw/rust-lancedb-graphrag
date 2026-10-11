"""Q10 (advisor check 3): reconcile graph cost on the graph node's own timing: graph_latency_ms, graph_ablation_latency_delta, retrieve_latency_ms."""
import json
RUNS = {
  "06.3.4.1 drive2": "2026-10-06-drive2-multihop_rag_diag",
  "06.3.5 heldout": "2026-10-07-heldout-multihop_rag_heldout",
  "06.3.6 levers": "2026-10-10-levers-heldout-multihop_rag_levers_heldout",
}
for label, d in RUNS.items():
    r = json.load(open(f"D:/Repos/lancet/eval/runs/{d}/report.json", encoding="utf-8"))
    by = {x["name"]: x for x in r["dimensions"]}
    print(f"\n== {label}  eval/runs/{d}/report.json  dimensions[name=...]")
    for n in ("graph_latency_ms", "graph_ablation_latency_delta", "graph_ablation_prompt_token_delta", "retrieve_latency_ms", "graph_presence_rate", "graph_influence_rate"):
        x = by.get(n)
        if x is None: print("  ", n, "-> absent"); continue
        det = x.get("detail") or {}
        short = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in det.items() if k in ("p50", "p95", "mean", "ci_lo", "ci_hi", "n_pairs", "delta", "graph_on_mean", "graph_off_mean", "n", "ci_label")}
        print(f"   {n}: status={x['status']} score={x['score']} n={x['n']} detail~{short}")
