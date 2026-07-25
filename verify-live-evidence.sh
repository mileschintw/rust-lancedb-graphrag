#!/usr/bin/env bash
set -euo pipefail
phase_dir=".planning/phases/02-ingestion-chunking-vector-storage"
challenge="${phase_dir}/.02-LIVE-CHALLENGE.json"; evidence="${phase_dir}/02-LIVE-EVIDENCE.json"
mode="${1:-}"; shift || true
while (($#)); do case "$1" in --challenge) challenge="$2"; shift 2;; --evidence) evidence="$2"; shift 2;; *) exit 2;; esac; done
case "$mode" in
  --self-test) bash -n "$0"; python3 - <<'PY'
import json; assert json.loads('{"schema_version":1}')['schema_version']==1
PY
  ;;
  --prepare-gate)
    [[ "$challenge" == "$phase_dir"/* && "$evidence" == "$phase_dir"/* ]] || { echo "gate artifacts must stay phase-local" >&2; exit 1; }
    rm -f "$evidence"; mkdir -p "$phase_dir"; umask 077; tmp="$(mktemp "$phase_dir/.challenge.XXXXXX")"
    python3 - "$tmp" <<'PY'
import json,sys,secrets,uuid,datetime
json.dump({'schema_version':1,'challenge':secrets.token_urlsafe(32),'run_id':str(uuid.uuid4()),'issued_at':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ)},open(sys.argv[1],'w'))
PY
    chmod 600 "$tmp" 2>/dev/null || true; mv -f "$tmp" "$challenge"; echo "Run ./verify-ingestion.sh --challenge-file $challenge" ;;
  --validate-gate)
    python3 - "$challenge" "$evidence" <<'PY'
import json,sys,uuid,datetime
c=json.load(open(sys.argv[1])); e=json.load(open(sys.argv[2])); allowed={'schema_version','success_sentinel','challenge','run_id','issued_at','run_started_at','generated_at','document_id','provider','embedding_model','gateway_chunk_count','postgres_status','postgres_chunk_count','document_rows','staged_document_rows','node_rows','edge_rows','embedding_width','duplicate_generation','stale_generation'}
assert set(e)<=allowed and e['success_sentinel']=='Ingestion validation: SUCCESS'
assert all(e[k]==c[k] for k in ('challenge','run_id','issued_at')) and e['provider']=='openrouter' and e['embedding_model']=='nvidia/llama-nemotron-embed-vl-1b-v2:free'
uuid.UUID(e['document_id']); assert e['postgres_status']=='completed' and e['gateway_chunk_count']==e['postgres_chunk_count']==e['node_rows']>0
assert e['document_rows']==1 and e['staged_document_rows']==0 and e['embedding_width']==2048 and not e['duplicate_generation'] and not e['stale_generation'] and e['edge_rows']>=0
parse=lambda x: datetime.datetime.fromisoformat(x.replace('Z','+00:00')); assert parse(c['issued_at'])<=parse(e['run_started_at'])<=parse(e['generated_at'])
PY
    rm -f "$challenge"; echo 'Live evidence validated' ;;
  *) echo 'usage: verify-live-evidence.sh --prepare-gate|--validate-gate|--self-test' >&2; exit 2;;
esac
