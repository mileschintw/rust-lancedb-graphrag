"""U6 research snippet: re-derive the D-105 held-out split counts. Read-only. Run from repo root:
uv run --project eval python .planning/phases/06.3.5-*/research/u6_split_counts.py
"""
import hashlib
import json
from collections import Counter
from pathlib import Path

root = Path(".")
pop_path = next(root.glob(".planning/phases/06.3.4.1-*/diagnostic/post-reconcile/populations.json"))
pop = json.loads(pop_path.read_text(encoding="utf-8"))
g = set(pop["g_question_ids"])
sel = json.loads((root / "eval/corpora/multihop_rag/diag_selection.json").read_text(encoding="utf-8"))
print("diag_selection keys:", list(sel.keys()))
dev_drawn = set(sel["drawn_question_ids"])
print("drawn_question_ids:", len(dev_drawn))

def qid(raw):
    q = raw.get("question_id") or raw.get("query_id") or raw.get("id") or ""
    if not q:
        q = "mhr-" + hashlib.sha256((raw.get("query") or "").encode()).hexdigest()[:12]
    return q

sample = [json.loads(x) for x in (root / "eval/corpora/multihop_rag/questions.sample.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
diag = [json.loads(x) for x in (root / "eval/corpora/multihop_rag/questions.diag.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
dev_all = {qid(r) for r in diag}
print("sample:", len(sample), "diag file:", len(diag), "dev_all:", len(dev_all))
by_id = {qid(r): r for r in sample}
null_ids = {i for i, r in by_id.items() if r.get("question_type") == "null_query"}
print("null in sample:", len(null_ids), "null in dev:", len(null_ids & dev_all))
held_g = sorted(i for i in by_id if i in g and i not in dev_all)
held_n = sorted(i for i in null_ids if i not in dev_all)
print("held-out G:", len(held_g), Counter(by_id[i]["question_type"] for i in held_g))
print("held-out null:", len(held_n))
print("total held-out:", len(held_g) + len(held_n))
print("dev & g:", len(dev_all & g), "dev non-null not in G:", len({i for i in dev_all if i not in g and i not in null_ids}))
rest = [i for i in by_id if i not in dev_all and i not in g and i not in null_ids]
print("non-dev, non-G, non-null (rehearsal pool):", len(rest), Counter(by_id[i]["question_type"] for i in rest))
print("populations sha256:", hashlib.sha256(pop_path.read_bytes()).hexdigest())
print("diag_selection sha256:", hashlib.sha256((root / "eval/corpora/multihop_rag/diag_selection.json").read_bytes()).hexdigest())
print("G subset of sample:", g <= set(by_id))
