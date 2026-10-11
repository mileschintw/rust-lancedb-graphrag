"""Q10/Q11: per-arm latency, retrieve-node time, prompt tokens, spend deltas vs hybrid from lever-comparison.json secondaries[]."""
import json
RUN = "D:/Repos/lancet/eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout/"
L = json.load(open(RUN + "lever-comparison.json", encoding="utf-8"))
for i, s in enumerate(L["secondaries"]):
    if s["metric"] in ("latency_total_ms_mean", "retrieve_node_ms_mean", "prompt_tokens_mean", "spend_usd_mean", "paper_hits_at_10"):
        print(f"secondaries[{i}] {s['metric']:<24} arm={s['arm']:<22} mean_arm={s['mean_arm']:.4f} mean_ref={s['mean_reference']:.4f} delta={s['delta']:.4f} n_pairs={s['n_pairs']} CI=[{s['ci_lo']:.4f},{s['ci_hi']:.4f}]")
