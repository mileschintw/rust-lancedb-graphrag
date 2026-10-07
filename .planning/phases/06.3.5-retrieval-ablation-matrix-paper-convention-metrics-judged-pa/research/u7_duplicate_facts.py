import json
strip=lambda s:s.replace(" ","").replace("\n","")
dup=sub=n=0
for l in open('eval/corpora/multihop_rag/questions.sample.jsonl',encoding='utf-8'):
    if not l.strip(): continue
    r=json.loads(l)
    if r.get('question_type')=='null_query': continue
    f=[strip(e['fact']) for e in r['evidence_list']]
    n+=1
    if len(set(f))<len(f): dup+=1
    if any(a!=b and a in b for a in f for b in f): sub+=1
print('non-null',n,'with duplicate fact',dup,'with fact-in-fact',sub)
