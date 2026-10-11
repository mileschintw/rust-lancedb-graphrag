import json
r6 = json.load(open("D:/Repos/lancet/eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout/report.json", encoding="utf-8"))
by = {d["name"]: d for d in r6["dimensions"]}
for n in ("latency_total_ms_delta__hybrid_graph", "retrieve_node_ms_delta__hybrid_graph", "prompt_tokens_delta__hybrid_graph",
          "latency_total_ms_mean__hybrid", "latency_total_ms_mean__hybrid_graph", "retrieve_node_ms_mean__hybrid", "retrieve_node_ms_mean__hybrid_graph"):
    d = by[n]; print(f"dimensions[name={n}]  status={d['status']} score={d['score']} n={d['n']}")
