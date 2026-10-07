import json,glob,hashlib
root='.'
pop=json.load(open(glob.glob('.planning/phases/06.3.4.1-*/diagnostic/post-reconcile/populations.json')[0],encoding='utf-8'))
g=set(pop['g_question_ids'])
def qid(r):
    q=r.get('question_id') or r.get('query_id') or r.get('id') or ''
    return q or 'mhr-'+hashlib.sha256((r.get('query') or '').encode()).hexdigest()[:12]
sample={qid(json.loads(x)):json.loads(x) for x in open('eval/corpora/multihop_rag/questions.sample.jsonl',encoding='utf-8') if x.strip()}
dev={qid(json.loads(x)) for x in open('eval/corpora/multihop_rag/questions.diag.jsonl',encoding='utf-8') if x.strip()}
for l in open('eval/corpora/multihop_rag/canary.jsonl',encoding='utf-8'):
    r=json.loads(l); q=r['question_id']
    kind='null' if sample.get(q,{}).get('question_type')=='null_query' else ('G' if q in g else 'nonG')
    where='dev' if q in dev else ('HELD-OUT' if (q in g or kind=='null') else 'rehearsal-pool(non-dev,non-G,non-null)')
    print(q, r['graph_arm'], kind, where, 'in_sample' if q in sample else 'NOT_IN_SAMPLE')
