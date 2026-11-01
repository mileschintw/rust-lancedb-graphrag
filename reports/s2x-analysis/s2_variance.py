"""Per-question replicate analysis of the S2 run of record (read-only)."""
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / "eval" / "src"))
from lancet_eval.corpus import _adapt_multihop_rag  # noqa: E402
from lancet_eval.metrics import answer_usable, extract_final_answer  # noqa: E402

run = repo / "eval/runs/2026-11-01-s2-multihop_rag_s2_dev"
recs = []
with open(run / "journal.jsonl", encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if r.get("type") == "header" or "question_id" not in r:
            continue
        recs.append(r)
qids = {r["question_id"] for r in recs}
gold = {}
with open(repo / "eval/corpora/multihop_rag/questions.diag.jsonl", encoding="utf-8") as f:
    for line in f:
        q = _adapt_multihop_rag(json.loads(line))
        if q.question_id in qids:
            gold[q.question_id] = q

cells = defaultdict(lambda: defaultdict(list))  # arm -> qid -> [usable]
abst = defaultdict(lambda: [0, 0])
for r in recs:
    q = gold[r["question_id"]]
    if q.is_null or r["outcome"] != "success":
        continue
    arm = r["graph_arm"].split("@")[-1] if "@" in r["graph_arm"] else "deepseek"
    u = answer_usable(q, r["answer"] or "")
    cells[arm][q.question_id].append(u)
    abst[arm][0] += extract_final_answer(r["answer"]) == "insufficient information"
    abst[arm][1] += 1

print("arm mean | all5 right | all5 wrong | mixed | mean within-q var | between-q var | abstain rate")
for arm, qs in cells.items():
    means = [sum(v) / len(v) for v in qs.values()]
    allr = sum(m == 1 for m in means)
    allw = sum(m == 0 for m in means)
    within = st.mean([st.pvariance([float(x) for x in v]) for v in qs.values()])
    print(arm, round(st.mean(means), 4), allr, allw, len(means) - allr - allw,
          round(within, 4), round(st.pvariance(means), 4),
          round(abst[arm][0] / abst[arm][1], 3), "n_q", len(means),
          "reps", sorted({len(v) for v in qs.values()}))

# paired per-question differences vs deepseek
ref = {q: sum(v) / len(v) for q, v in cells["deepseek"].items()}
for arm in cells:
    if arm == "deepseek":
        continue
    d = [sum(v) / len(v) - ref[q] for q, v in cells[arm].items()]
    sd = st.stdev(d)
    # questions needed to detect a 5-pt paired difference at alpha .05, power .8
    n5 = ((1.96 + 0.84) * sd / 0.05) ** 2
    print(f"{arm} - deepseek: delta {st.mean(d):+.4f} sd_d {sd:.4f} "
          f"n_q for 5pt {n5:.0f}, for 3pt {n5 * (5 / 3) ** 2:.0f}")

# how much K helps: simulate K=1..5 by taking first k replicates
for arm in cells:
    if arm == "deepseek":
        continue
    for k in (1, 2, 3, 5):
        d = [sum(v[:k]) / k - sum(cells["deepseek"][q][:k]) / k for q, v in cells[arm].items()]
        print(arm, "K", k, "sd_d", round(st.stdev(d), 4))
