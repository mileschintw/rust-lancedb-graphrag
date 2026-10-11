"""Q10: reconcile the graph latency figures from the runs' own JSON (read-only)."""
import json
c5 = json.load(open("D:/Repos/lancet/eval/runs/2026-10-07-heldout-multihop_rag_heldout/comparison.json", encoding="utf-8"))
print("06.3.5 comparison.json arms[*].cells.<metric>.value")
cells = {a["arm"]: a["cells"] for a in c5["arms"]}
for m in ("latency_total_ms_mean", "retrieve_node_ms_mean", "prompt_tokens_mean", "spend_usd_mean"):
    print(f"  {m}:", {a: round(cells[a][m]["value"], 2) for a in cells}, " graph-hybrid =", round(cells["hybrid+graph"][m]["value"] - cells["hybrid"][m]["value"], 2))
r6 = json.load(open("D:/Repos/lancet/eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout/report.json", encoding="utf-8"))
dims = r6["dimensions"]
print("\n06.3.6 report.json dimensions type", type(dims).__name__, "len", len(dims))
d0 = dims[0] if isinstance(dims, list) else None
print("sample dim keys:", list(d0.keys()) if d0 else list(dims.keys())[:10])
names = sorted({d["name"] for d in dims}) if isinstance(dims, list) else []
print("dimension names:", names)
