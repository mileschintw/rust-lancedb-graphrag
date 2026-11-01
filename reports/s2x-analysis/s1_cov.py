import json, sys
from collections import Counter, defaultdict
from pathlib import Path
repo=Path(sys.argv[1]); sys.path.insert(0,str(repo/"eval"/"src"))
from lancet_eval.corpus import _adapt_multihop_rag
from lancet_eval.metrics import gold_contained, answer_usable, extract_final_answer
run=repo/"eval/runs/2026-10-31-s1-multihop_rag_s1_dev"
rows=[json.loads(l) for l in open(run/"context_export.jsonl",encoding="utf-8")]
qids={r["question_id"] for r in rows}
gold={}
for l in open(repo/"eval/corpora/multihop_rag/questions.diag.jsonl",encoding="utf-8"):
    q=_adapt_multihop_rag(json.loads(l))
    if q.question_id in qids: gold[q.question_id]=q
recs={(r["graph_arm"],r["question_id"]):r for r in (json.loads(l) for l in open(run/"journal.jsonl",encoding="utf-8")) if "question_id" in r}
for arm in ("small/hybrid+rerank+metadata","merged/hybrid+rerank+metadata"):
    c=Counter(); toks=[]; nchunk=[]; u=defaultdict(list)
    for r in rows:
        if r["arm"]!=arm: continue
        q=gold[r["question_id"]]
        if q.is_null: continue
        t=" ".join(e["text"] for e in r["evidence"]); toks.append(len(t.split())); nchunk.append(len(r["evidence"]))
        h=sum(gold_contained(f,t) for f in q.gold_facts); k="all" if h==len(q.gold_facts) else ("some" if h else "none")
        c[k]+=1
        rec=recs.get((arm,q.question_id))
        if rec and rec["outcome"]=="success": u[k].append(answer_usable(q,rec["answer"] or ""))
    print(arm,dict(c),"words/context",round(sum(toks)/len(toks)),"chunks",round(sum(nchunk)/len(nchunk),1),
          {k:(len(v),round(sum(v)/len(v),3)) for k,v in u.items()})
