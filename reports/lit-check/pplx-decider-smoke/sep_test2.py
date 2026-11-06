"""pplx-decider separation smoke test on MHR S3m dev, reference arm (hybrid+rerank+metadata, DeepSeek reader).

Label: answer_usable of the reader's answer. Signal: noul P(evidence sufficient). Baseline: rerank top score.
Usage: uv run --project eval python <this> <run_dir> <out_jsonl>
"""
import json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

from lancet_eval.corpus import load_corpus
from lancet_eval.journal import load_records
from lancet_eval.metrics import answer_usable

run, out = sys.argv[1], sys.argv[2]
MODELS = sys.argv[3].split(",") if len(sys.argv) > 3 else ["perplexity/pplx-decider-v1.2"]
qs = {q.question_id: q for q in load_corpus("multihop_rag_s3m_dev").questions}
recs = {r.question_id: r for r in load_records(os.path.join(run, "journal.jsonl")) if r.outcome == "success"}
ctx = {}
for line in open(os.path.join(run, "context_export.jsonl"), encoding="utf-8"):
    c = json.loads(line)
    ctx[c["question_id"]] = c

def state_for(c):
    parts = [f"Question: {c['question']}", "", "Evidence:"]
    for e in c["evidence"]:
        m = e.get("document_metadata") or {}
        pub = m.get("published_date") or ""
        parts.append(f"[{e['rank']}] {m.get('doc_title') or e.get('title')} | {m.get('source','')} | published {pub}\n{e['text']}")
    return "\n\n".join(parts)

INSTR = ("Using ONLY the evidence above, could a careful reader answer the question correctly and completely? "
         "Answer true only if every fact the question needs is present in the evidence.")
KEY = os.environ["OPENROUTER_API_KEY"]

def call(job):
    qid, model = job
    c = ctx[qid]
    body = {"model": model, "state": state_for(c),
            "questions": {"sufficient": {"type": "noul", "instructions": INSTR}}}
    req = urllib.request.Request("https://openrouter.ai/api/alpha/decisions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t = time.time()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.load(r)
            break
        except Exception as ex:  # noqa: BLE001
            err = repr(ex); time.sleep(2)
    else:
        return {"question_id": qid, "requested": model, "error": err}
    return {"question_id": qid, "requested": model, "p": resp["answers"]["sufficient"]["noul"], "latency_s": time.time() - t,
            "input_tokens": resp["usage"]["input_tokens"], "cost": resp["usage"].get("cost"), "model": resp.get("model")}

ids = sorted(set(recs) & set(ctx) & set(qs))
with ThreadPoolExecutor(5) as ex:
    results = list(ex.map(call, [(q, m) for q in ids for m in MODELS]))
with open(out, "w", encoding="utf-8") as f:
    for res in results:
        q, r = qs[res["question_id"]], recs[res["question_id"]]
        chunks = list(r.snapshot.retrieved_chunks) if r.snapshot is not None else []
        res.update(is_null=q.is_null, qtype=q.question_type, usable=answer_usable(q, r.answer),
                   rerank_ok=str(getattr(getattr(r.workflow_meta, "rerank", None), "outcome", None)),
                   rerank_top=(chunks[0].score if chunks else None),
                   rerank_gap=(chunks[0].score - chunks[1].score if len(chunks) > 1 else None))
        f.write(json.dumps(res) + "\n")
print("wrote", len(results), "errors", sum(1 for x in results if "error" in x))
