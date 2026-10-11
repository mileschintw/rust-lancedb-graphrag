"""Q11/Q9: print the 06.3.6 lever-table numbers with file + JSON key path (read-only). Quote, never re-derive (D-214)."""
import json, sys
RUN = "D:/Repos/lancet/eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout/"
L = json.load(open(RUN + "lever-comparison.json", encoding="utf-8"))
G = json.load(open(RUN + "gates-heldout.json", encoding="utf-8"))
print("FILE lever-comparison.json  schema_version", L["schema_version"], " run:", L["run"])
for fi, fam in enumerate(L["families"]):
    print(f"\nfamilies[{fi}] primary={fam['primary']} role={fam['role']} m={fam['m']} alpha={fam['alpha']}")
    for ci, c in enumerate(fam["comparisons"]):
        p = f"families[{fi}].comparisons[{ci}]"
        print(f"  {p} arm={c['arm']} ref={c['reference']} n_pairs={c['n_pairs']} n_pos={c['n_pos']} n_neg={c['n_neg']} "
              f"mean_arm={c['mean_arm']:.4f} mean_ref={c['mean_reference']:.4f} delta={c['delta']:.6f} "
              f"CI=[{c['ci_lo']:.6f},{c['ci_hi']:.6f}] ({c['ci_label']}) raw_p={c['raw_p']:.6g} adj_p={c['adjusted_p']:.6g} "
              f"rejected={c['rejected']} decision={c['decision']} coverage={c['coverage']}")
print("\ndefault_decisions")
for i, d in enumerate(L["default_decisions"]):
    print(f"  default_decisions[{i}] lever={d['lever']} decision={d['decision']!r} delta={d['delta']:.6f} "
          f"answer_usable_decision={d['answer_usable_decision']} hits_at_4_support={d['hits_at_4_support']} gate_reads={d['gate_reads']} reasons={d['reasons']}")
print("\ndescriptive_rows")
for i, r in enumerate(L["descriptive_rows"]):
    au, h4 = r["answer_usable"], r["paper_hits_at_4"]
    print(f"  descriptive_rows[{i}] row={r['row']!r} n_pairs={r['n_pairs']} label={r['label']!r}")
    for nm, m in (("answer_usable", au), ("paper_hits_at_4", h4)):
        print(f"     .{nm}: delta={m['delta']:.6f} CI=[{m['ci_lo']:.6f},{m['ci_hi']:.6f}] mean_arm={m['mean_arm']:.4f} mean_ref={m['mean_reference']:.4f} n_pos={m['n_pos']} n_neg={m['n_neg']}")
print("\nnull_guards")
for i, g in enumerate(L["null_guards"]):
    print(f"  null_guards[{i}] arm={g['arm']} n_pairs={g['n_pairs']} b={g['b']} c={g['c']} net_loss_rate={g['net_loss_rate']:.4f} upper95={g['upper_bound_95']:.4f} margin={g['margin']} passes={g['passes']} status={g['status']} decisional={g['decisional']} note={g['note']!r}")
print("\ngate_readings", json.dumps(L["gate_readings"], sort_keys=True))
print("\npopulations", {k: v for k, v in L["populations"].items()})
print("\nrerank_operation")
for i, r in enumerate(L["rerank_operation"]):
    print(f"  rerank_operation[{i}] arm={r['arm']} attempts={r['attempts']} degrades={r['degrades']} p50={r['latency_ms_p50']} p95={r['latency_ms_p95']} max={r['latency_ms_max']} cost_sum={r['cost_credits_reported_sum']}")
print("\ngraph_state"); [print("  ", g) for g in L["graph_state"]]
print("\nprovenance_counts"); [print("  ", g) for g in L["provenance_counts"]]
print("\nsecondaries metrics:", sorted({s["metric"] for s in L["secondaries"]}))
print("\nsensitivity.rerank_itt", {k: L["sensitivity"]["rerank_itt"][k] for k in ("arm","delta","ci_lo","ci_hi","raw_p","adjusted_p","decision","n_pairs")})
print("\nFILE gates-heldout.json top keys:", list(G.keys()))
