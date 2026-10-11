"""Q11: 06.3.5 four-arm per-arm cells and both runs' SC-1/SC-2 gate readings, with file + JSON key paths (read-only)."""
import json
R5 = "D:/Repos/lancet/eval/runs/2026-10-07-heldout-multihop_rag_heldout/"
R6 = "D:/Repos/lancet/eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout/"
C = json.load(open(R5 + "comparison.json", encoding="utf-8"))
M = ("paper_hits_at_4", "paper_hits_at_10", "paper_mrr_at_10", "paper_map_at_10", "answer_usable_p4", "final_answer_em", "coverage_at_4", "gold_containment", "abstention_rate_g", "null_abstention_correctness")
print("06.3.5 comparison.json  arms[i].cells.<metric>.{value,ci_lo,ci_hi,n}")
for i, a in enumerate(C["arms"]):
    print(f" arms[{i}] {a['arm']}")
    for m in M:
        c = a["cells"][m]
        print(f"    {m:<28} value={c['value']:.4f} CI=[{c['ci_lo']:.4f},{c['ci_hi']:.4f}] n={c['n']}")
print("paper_reference.rows:", C["paper_reference"]["rows"])
print("p4:", C["p4"])
for tag, path in (("06.3.5", R5), ("06.3.6", R6)):
    g = json.load(open(path + "gates-heldout.json", encoding="utf-8"))
    print(f"\n{tag} gates-heldout.json keys: {list(g.keys())}")
    for k in ("SC-1", "SC-2"):
        print(f" {k}:", json.dumps(g[k])[:1500])
