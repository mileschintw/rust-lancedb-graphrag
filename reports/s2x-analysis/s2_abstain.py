import json, sys
from collections import defaultdict, Counter
from pathlib import Path
repo = Path(sys.argv[1]); sys.path.insert(0, str(repo/"eval"/"src"))
from lancet_eval.corpus import _adapt_multihop_rag
from lancet_eval.metrics import answer_usable, extract_final_answer, gold_contained
run = repo/"eval/runs/2026-11-01-s2-multihop_rag_s2_dev"
recs=[json.loads(l) for l in open(run/"journal.jsonl",encoding="utf-8")]
recs=[r for r in recs if "question_id" in r]
qids={r["question_id"] for r in recs}
gold={}
for l in open(repo/"eval/corpora/multihop_rag/questions.diag.jsonl",encoding="utf-8"):
    q=_adapt_multihop_rag(json.loads(l))
    if q.question_id in qids: gold[q.question_id]=q
ctx={}
for l in open(run/"context_export.jsonl",encoding="utf-8"):
    r=json.loads(l); ctx[r["question_id"]]=" ".join(e["text"] for e in r["evidence"])
def cov(q):
    t=ctx.get(q.question_id,"")
    hit=sum(gold_contained(f,t) for f in q.gold_facts)
    return hit,len(q.gold_facts)
st=defaultdict(lambda: defaultdict(lambda:[0,0]))  # arm,q -> [usable, abstain]
for r in recs:
    q=gold[r["question_id"]]
    if q.is_null or r["outcome"]!="success": continue
    arm=r["graph_arm"].split("@")[1] if "@" in r["graph_arm"] else "deepseek"
    st[arm][q.question_id][0]+=answer_usable(q,r["answer"] or "")
    st[arm][q.question_id][1]+=extract_final_answer(r["answer"])=="insufficient information"
binary=lambda q: q.gold_answer.strip().lower() in ("yes","no")
# context coverage overall
c=Counter()
for qid,q in gold.items():
    if q.is_null: continue
    h,n=cov(q); c["all" if h==n else ("some" if h else "none")]+=1
print("gold facts in context (90 G):",dict(c))
for arm in ("haiku-5.5","sonnet-5.5","opus-5.5"):
    lost=[q for q in st[arm] if st["deepseek"][q][0]>=3 and st[arm][q][1]>=3]
    rows=Counter()
    for qid in lost:
        q=gold[qid]; h,n=cov(q)
        rows[(("binary" if binary(q) else "open"), "all" if h==n else ("some" if h else "none"))]+=1
    print(arm,"deepseek-right & arm-abstains:",len(lost),dict(rows))
# deepseek correctness on questions where evidence incomplete
for arm in ("deepseek","haiku-5.5","sonnet-5.5","opus-5.5"):
    for k in ("all","partial"):
        qs=[q for q in gold.values() if not q.is_null and ((cov(q)[0]==cov(q)[1])==(k=="all"))]
        u=sum(st[arm][q.question_id][0] for q in qs)/ (5*len(qs)); a=sum(st[arm][q.question_id][1] for q in qs)/(5*len(qs))
        print(arm,k,"n",len(qs),"usable",round(u,3),"abstain",round(a,3))
