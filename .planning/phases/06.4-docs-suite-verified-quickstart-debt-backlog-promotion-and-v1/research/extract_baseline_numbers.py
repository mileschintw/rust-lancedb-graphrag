"""Q11/Q9: 06.3.5 four-arm baseline numbers with file + JSON key path (read-only)."""
import json
R = "D:/Repos/lancet/eval/runs/2026-10-07-heldout-multihop_rag_heldout/"
C = json.load(open(R + "comparison.json", encoding="utf-8"))
print("comparison.json run:", C["run"])
for fi, f in enumerate(C["families"]):
    print(f"families[{fi}] primary={f['primary']} reference={f['reference']} m={f['m']} alpha={f['alpha']} evaluable={f['evaluable']} matching_rule={f['matching_rule']}")
    for ci, c in enumerate(f["comparisons"]):
        print("  ", f"families[{fi}].comparisons[{ci}]", {k: (round(v, 6) if isinstance(v, float) else v) for k, v in c.items() if k not in ("strata", "exclusions")})
print("\narms[*].cells keys:", list(C["arms"][0]["cells"].keys())[:30] if isinstance(C["arms"][0]["cells"], dict) else type(C["arms"][0]["cells"]))
for ai, a in enumerate(C["arms"]):
    cells = a["cells"]
    print(f"arms[{ai}] arm={a['arm']} slug={a['slug']}")
    if isinstance(cells, dict):
        for k, v in list(cells.items())[:40]:
            print("     ", k, v if not isinstance(v, dict) else {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()})
print("\npaper_reference.rows"); [print("  ", r) for r in C["paper_reference"]["rows"]]
print("paper_reference.lancet_line:", C["paper_reference"]["lancet_line"]); print("comparable_line:", C["paper_reference"]["comparable_line"])
print("p4:", C["p4"]); print("disclosures.gates:", json.dumps(C["disclosures"]["gates"])[:900])
G = json.load(open(R + "gates-heldout.json", encoding="utf-8"))
print("\ngates-heldout.json keys", list(G.keys()))
for k in ("SC-1", "SC-2"):
    print(k, json.dumps(G[k])[:1400])
