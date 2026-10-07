"""U7 research snippet: PREVIEW of the D-104 retro (paper-convention Hits@4, ID rule) on drive 2.

Read-only. Never imports lancet_eval.score / lancet_eval.report. Run from repo root:
uv run --project eval python .planning/phases/06.3.5-*/research/u7_retro_hits4_preview.py
The implementation of record is PROPOSED (eval/scripts/retro_paper_hits4.py + metrics.paper_metrics_by_id);
this file only proves the mechanics against real data and is not a deliverable.
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

from lancet_eval.journal import load_records

root = Path(".")
gold_path = next(root.glob(".planning/phases/06.3.4.1-*/diagnostic/post-reconcile/gold_chunks.jsonl"))
rows = [json.loads(x) for x in gold_path.read_text(encoding="utf-8").splitlines() if x.strip()]
by_q: dict[str, dict[int, frozenset[str]]] = defaultdict(dict)
state = Counter()
for r in rows:
    by_q[r["question_id"]][r["evidence_index"]] = frozenset(r["chunk_ids"]) if r["state"] == "in_chunk" else frozenset()
    state[r["state"]] += 1
print("gold rows:", len(rows), dict(state), "questions:", len(by_q))

pop = json.loads(next(root.glob(".planning/phases/06.3.4.1-*/diagnostic/post-reconcile/populations.json")).read_text(encoding="utf-8"))
g = set(pop["g_question_ids"])


def gold_sets(qid):
    d = by_q[qid]
    return [d[i] for i in sorted(d)]


def paper_metrics_by_id(ranked_ids, gold_chunk_sets, ks=(4, 10)):
    """Official calculate_metrics semantics at c1c1287, over chunk IDs (see AI-SPEC section 3)."""
    h = {k: 0 for k in ks}
    ap, rr = [], []
    for ranked, gold in zip(ranked_ids, gold_chunk_sets, strict=True):
        found, ap_sum, first = set(), 0.0, None
        for rank, cid in enumerate(ranked[:10], start=1):
            if any(cid in s for s in gold):
                new = [i for i, s in enumerate(gold) if cid in s and i not in found]
                first = first or rank
                found.update(new)
                ap_sum += len(new) / rank
        for k in ks:
            h[k] += first is not None and first <= k
        ap.append(ap_sum / min(len(gold), 10))
        rr.append(1 / first if first else 0)
    n = len(gold_chunk_sets)
    return {f"Hits@{k}": h[k] / n for k in ks} | {"MAP@10": sum(ap) / n, "MRR@10": sum(rr) / n, "n": n}


recs = load_records("eval/runs/2026-10-06-drive2-multihop_rag_diag/journal.jsonl")
print("drive-2 records:", len(recs), Counter(r.graph_arm for r in recs))
for arm in ("graph-off", "graph-on"):
    sel = [r for r in recs if r.graph_arm == arm and r.question_id in g and r.outcome == "success" and r.snapshot]
    ranked = [[c.chunk_id for c in r.snapshot.retrieved_chunks] for r in sel]
    gs = [gold_sets(r.question_id) for r in sel]
    print(arm, "dev-G usable n=", len(sel), paper_metrics_by_id(ranked, gs))
    # only the final 8 exist in this journal: @10 metrics are NOT computable (rank 9-10 missing) -> only Hits@4 is valid
    print("  retrieved_chunks length distribution:", Counter(len(x) for x in ranked))
    print("  snapshot has pre_truncation_ranking attr?:", hasattr(sel[0].snapshot, "pre_truncation_ranking"))
