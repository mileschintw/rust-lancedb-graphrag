#!/usr/bin/env bash
set -euo pipefail

phase_dir=".planning/phases/02-ingestion-chunking-vector-storage"
challenge_file="${phase_dir}/.02-LIVE-CHALLENGE.json"
evidence_out="${EVIDENCE_OUT:-${phase_dir}/02-LIVE-EVIDENCE.json}"
gateway_url="${GATEWAY_URL:-http://127.0.0.1:8080}"
sample_file=""
while (($#)); do
  case "$1" in
    --challenge-file) challenge_file="$2"; shift 2 ;;
    --evidence) evidence_out="$2"; shift 2 ;;
    --managed-services) shift ;; # services must already be configured; this never prints their environment.
    *) sample_file="$1"; shift ;;
  esac
done
[[ -n "${OPENROUTER_API_KEY:-}" ]] || { echo "OPENROUTER_API_KEY is required" >&2; exit 1; }
[[ -f "$challenge_file" ]] || { echo "pre-issued challenge file is required" >&2; exit 1; }
challenge_json="$(python3 -c 'import json,sys; x=json.load(open(sys.argv[1])); assert x.get("schema_version")==1 and x.get("challenge") and x.get("run_id") and x.get("issued_at"); print(json.dumps(x))' "$challenge_file")"
run_started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mkdir -p "$(dirname "$evidence_out")"
tmp="$(mktemp "$(dirname "$evidence_out")/.evidence.XXXXXX")"; trap 'rm -f "$tmp"' EXIT; umask 077
if [[ -z "$sample_file" ]]; then sample_file="$(mktemp)"; printf '# Lancet live verification\n\nOpenRouter-backed indexing proof.\n' > "$sample_file"; trap 'rm -f "$tmp" "$sample_file"' EXIT; fi
response="$(curl --fail --silent --show-error -X POST -F "file=@${sample_file};filename=$(basename "$sample_file")" "${gateway_url}/documents")"
document_id="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ID"])')"
for _ in $(seq 1 "${POLL_LIMIT:-60}"); do
  response="$(curl --fail --silent --show-error "${gateway_url}/documents/${document_id}")"
  status="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Status"])')"
  [[ "$status" == completed ]] && break
  [[ "$status" != failed ]] || { echo "ingestion failed" >&2; exit 1; }; sleep "${POLL_INTERVAL_SECONDS:-2}"
done
[[ "${status:-}" == completed ]] || { echo "ingestion did not complete" >&2; exit 1; }
gateway_count="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ChunkCount"])')"
postgres="$(docker compose exec -T db psql -U postgres -d lancet -Atc "SELECT status || ':' || chunk_count FROM documents WHERE id = '${document_id}'")"
inspect="$(cargo run --quiet --manifest-path engine/Cargo.toml --bin inspect_lancedb -- --document-id "$document_id")"
python3 - "$challenge_json" "$inspect" "$document_id" "$gateway_count" "$postgres" "$run_started_at" > "$tmp" <<'PY'
import json,sys,datetime
c,i,id,g,p,started=map(str,sys.argv[1:]); c=json.loads(c); i=json.loads(i); status,count=p.split(':',1)
assert status=='completed' and int(g)>0 and int(g)==int(count)==i['node_rows']
assert i['document_rows']==1 and i['staged_document_rows']==0 and i['embedding_width']==2048 and not i['stale_generation']
assert i['embedding_model']=='nvidia/llama-nemotron-embed-vl-1b-v2:free'
print(json.dumps({'schema_version':1,'success_sentinel':'Ingestion validation: SUCCESS','challenge':c['challenge'],'run_id':c['run_id'],'issued_at':c['issued_at'],'run_started_at':started,'generated_at':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),'document_id':id,'provider':'openrouter','embedding_model':i['embedding_model'],'gateway_chunk_count':int(g),'postgres_status':status,'postgres_chunk_count':int(count),'document_rows':i['document_rows'],'staged_document_rows':i['staged_document_rows'],'node_rows':i['node_rows'],'edge_rows':i['edge_rows'],'embedding_width':i['embedding_width'],'duplicate_generation':False,'stale_generation':False},sort_keys=True))
PY
chmod 600 "$tmp" 2>/dev/null || true; mv -f "$tmp" "$evidence_out"; trap - EXIT
cat "$evidence_out"; echo 'Ingestion validation: SUCCESS'
