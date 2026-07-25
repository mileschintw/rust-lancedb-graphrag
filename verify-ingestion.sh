#!/usr/bin/env bash
set -euo pipefail

phase_dir=".planning/phases/02-ingestion-chunking-vector-storage"
challenge_file="${phase_dir}/.02-LIVE-CHALLENGE.json"
evidence_out="${phase_dir}/02-LIVE-EVIDENCE.json"
gateway_url="${GATEWAY_URL:-http://127.0.0.1:8080}"
managed_services=false
sample_file=""
engine_pid=""
gateway_pid=""
engine_log=""
gateway_log=""

cleanup() {
  [[ -z "$gateway_pid" ]] || kill "$gateway_pid" 2>/dev/null || true
  [[ -z "$engine_pid" ]] || kill "$engine_pid" 2>/dev/null || true
  [[ -z "$gateway_log" ]] || rm -f -- "$gateway_log"
  [[ -z "$engine_log" ]] || rm -f -- "$engine_log"
  [[ -z "$sample_file" ]] || rm -f -- "$sample_file"
}
trap cleanup EXIT

if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys' >/dev/null 2>&1; then
  python_cmd=python3
elif command -v python >/dev/null 2>&1 && python -c 'import sys' >/dev/null 2>&1; then
  python_cmd=python
else
  echo "a working Python 3 interpreter is required" >&2
  exit 1
fi

while (($#)); do
  case "$1" in
    --challenge-file) challenge_file="$2"; shift 2 ;;
    --evidence) evidence_out="$2"; shift 2 ;;
    --managed-services) managed_services=true; shift ;;
    *) sample_file="$1"; shift ;;
  esac
done

[[ "$challenge_file" == "${phase_dir}/.02-LIVE-CHALLENGE.json" ]] || {
  echo "challenge path must be the phase-local runtime path" >&2; exit 1;
}
[[ "$evidence_out" == "${phase_dir}/02-LIVE-EVIDENCE.json" ]] || {
  echo "evidence path must be the phase-local runtime path" >&2; exit 1;
}
[[ -n "${OPENROUTER_API_KEY:-}" ]] || { echo "OPENROUTER_API_KEY is required" >&2; exit 1; }
[[ -f "$challenge_file" && ! -L "$challenge_file" ]] || { echo "pre-issued challenge file is required" >&2; exit 1; }
[[ ! -e "$evidence_out" || ( -f "$evidence_out" && ! -L "$evidence_out" ) ]] || {
  echo "evidence path is unsafe" >&2; exit 1;
}
git ls-files --error-unmatch -- "$challenge_file" >/dev/null 2>&1 && {
  echo "challenge file must remain untracked" >&2; exit 1;
}
git ls-files --error-unmatch -- "$evidence_out" >/dev/null 2>&1 && {
  echo "evidence file must remain untracked" >&2; exit 1;
}
[[ -z "$(git diff --cached --name-only -- "$challenge_file" "$evidence_out")" ]] || {
  echo "runtime artifacts must not be staged" >&2; exit 1;
}

challenge_json="$("$python_cmd" - "$challenge_file" <<'PY'
import datetime as dt
import json
import sys
import uuid

with open(sys.argv[1], encoding="utf-8") as stream:
    challenge = json.load(stream)
assert set(challenge) == {"schema_version", "challenge", "run_id", "issued_at"}
assert challenge["schema_version"] == 1
assert isinstance(challenge["challenge"], str) and len(challenge["challenge"]) >= 32
assert uuid.UUID(challenge["run_id"]).version == 4
issued = dt.datetime.fromisoformat(challenge["issued_at"].replace("Z", "+00:00"))
assert issued.tzinfo is not None
print(json.dumps(challenge, separators=(",", ":")))
PY
)"
run_started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

start_managed_services() {
  docker compose up -d db >/dev/null
  for _ in $(seq 1 30); do
    [[ "$(docker inspect --format '{{.State.Health.Status}}' lancet-postgres 2>/dev/null || true)" == "healthy" ]] && break
    sleep 2
  done
  [[ "$(docker inspect --format '{{.State.Health.Status}}' lancet-postgres 2>/dev/null || true)" == "healthy" ]] || {
    echo "PostgreSQL did not become healthy" >&2; return 1;
  }
  schema_tables="$(docker compose exec -T db psql -U postgres -d lancet -Atc \
    "SELECT (to_regclass('public.users') IS NOT NULL)::int || '|' || (to_regclass('public.documents') IS NOT NULL)::int")"
  case "$schema_tables" in
    "1|1")
      ;;
    "0|0")
      docker compose exec -T db psql -U postgres -d lancet -v ON_ERROR_STOP=1 -f - \
        < gateway/db/schema.sql >/dev/null
      ;;
    *)
      echo "PostgreSQL schema is partial; refusing to overwrite the existing volume" >&2
      return 1
      ;;
  esac
  if curl --silent --max-time 1 "${gateway_url}/documents/not-a-uuid" -o /dev/null; then
    echo "gateway port is already occupied; refuse to trust an unmanaged service" >&2; return 1
  fi
  engine_log="$(mktemp)"
  gateway_log="$(mktemp)"
  cargo run --quiet --manifest-path engine/Cargo.toml --bin engine >"$engine_log" 2>&1 & engine_pid=$!
  sleep 1
  go run ./gateway >"$gateway_log" 2>&1 & gateway_pid=$!
  for _ in $(seq 1 45); do
    if curl --silent --max-time 1 "${gateway_url}/documents/not-a-uuid" -o /dev/null; then return 0; fi
    kill -0 "$engine_pid" 2>/dev/null && kill -0 "$gateway_pid" 2>/dev/null || {
      echo "managed engine or gateway failed to start" >&2; return 1;
    }
    sleep 2
  done
  echo "managed gateway did not become ready" >&2
  return 1
}

if "$managed_services"; then start_managed_services; fi

if [[ -z "$sample_file" ]]; then
  sample_file="$(mktemp)"
  printf '# Lancet live verification\n\nOpenRouter-backed indexing proof.\n' > "$sample_file"
fi
response="$(curl --fail --silent --show-error -X POST -F "file=@${sample_file};filename=$(basename "$sample_file")" "${gateway_url}/documents")"
document_id="$(printf '%s' "$response" | "$python_cmd" -c 'import json,sys; print(json.load(sys.stdin)["ID"])')"
"$python_cmd" - "$document_id" <<'PY'
import sys
import uuid
assert uuid.UUID(sys.argv[1]).version == 4
PY
for _ in $(seq 1 "${POLL_LIMIT:-60}"); do
  response="$(curl --fail --silent --show-error "${gateway_url}/documents/${document_id}")"
  status="$(printf '%s' "$response" | "$python_cmd" -c 'import json,sys; print(json.load(sys.stdin)["Status"])')"
  [[ "$status" == completed ]] && break
  [[ "$status" != failed ]] || { echo "ingestion failed" >&2; exit 1; }
  sleep "${POLL_INTERVAL_SECONDS:-2}"
done
[[ "${status:-}" == completed ]] || { echo "ingestion did not complete" >&2; exit 1; }
gateway_count="$(printf '%s' "$response" | "$python_cmd" -c 'import json,sys; print(json.load(sys.stdin)["ChunkCount"])')"
postgres="$(docker compose exec -T db psql -U postgres -d lancet -Atc "SELECT status || ':' || chunk_count FROM documents WHERE id = '${document_id}'")"
inspection="$(cargo run --quiet --manifest-path engine/Cargo.toml --bin inspect_lancedb -- --document-id "$document_id")"

umask 077
tmp="$(mktemp "${phase_dir}/.evidence.XXXXXX")"
"$python_cmd" - "$challenge_json" "$inspection" "$document_id" "$gateway_count" "$postgres" "$run_started_at" > "$tmp" <<'PY'
import datetime as dt
import json
import sys

challenge, inspection, document_id, gateway_count, postgres, started = map(str, sys.argv[1:])
challenge = json.loads(challenge)
inspection = json.loads(inspection)
status, count = postgres.split(':', 1)
assert status == 'completed'
assert int(gateway_count) > 0 and int(gateway_count) == int(count) == inspection['node_rows']
assert inspection['document_id'] == document_id and inspection['provider'] == 'openrouter'
assert inspection['document_rows'] == 1 and inspection['staged_document_rows'] == 0
assert inspection['embedding_width'] == 2048 and not inspection['stale_generation']
assert inspection['embedding_model'] == 'nvidia/llama-nemotron-embed-vl-1b-v2:free'
issued = dt.datetime.fromisoformat(challenge['issued_at'].replace('Z', '+00:00'))
started_at = dt.datetime.fromisoformat(started.replace('Z', '+00:00'))
assert started_at >= issued
payload = {
    'schema_version': 1,
    'success_sentinel': 'Ingestion validation: SUCCESS',
    'challenge': challenge['challenge'],
    'run_id': challenge['run_id'],
    'issued_at': challenge['issued_at'],
    'run_started_at': started,
    'generated_at': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    'document_id': document_id,
    'provider': inspection['provider'],
    'embedding_model': inspection['embedding_model'],
    'gateway_chunk_count': int(gateway_count),
    'postgres_status': status,
    'postgres_chunk_count': int(count),
    'document_rows': inspection['document_rows'],
    'staged_document_rows': inspection['staged_document_rows'],
    'node_rows': inspection['node_rows'],
    'edge_rows': inspection['edge_rows'],
    'embedding_width': inspection['embedding_width'],
    'duplicate_generation': False,
    'stale_generation': inspection['stale_generation'],
}
print(json.dumps(payload, separators=(',', ':'), sort_keys=True))
PY
chmod 600 "$tmp" 2>/dev/null || true
mv -f -- "$tmp" "$evidence_out"
echo 'Ingestion validation: SUCCESS'
