#!/usr/bin/env bash
set -euo pipefail

gateway_url="${GATEWAY_URL:-http://127.0.0.1:8080}"
sample_file="${1:-}"
poll_limit="${POLL_LIMIT:-60}"
poll_interval="${POLL_INTERVAL_SECONDS:-2}"

cleanup_file=""
if [[ -z "$sample_file" ]]; then
  cleanup_file="$(mktemp)"
  sample_file="$cleanup_file"
  printf '# Lancet ingestion verification\n\nThis document validates background indexing.\n' > "$sample_file"
fi
trap '[[ -z "$cleanup_file" ]] || rm -f "$cleanup_file"' EXIT

if [[ ! -f "$sample_file" ]]; then
  echo "Sample file does not exist: $sample_file" >&2
  exit 1
fi

response="$(curl --fail --silent --show-error \
  -X POST \
  -F "file=@${sample_file};filename=$(basename "$sample_file")" \
  "${gateway_url}/documents")"
document_id="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ID"])')"
status_url="${gateway_url}/documents/${document_id}"

for ((attempt = 1; attempt <= poll_limit; attempt++)); do
  response="$(curl --fail --silent --show-error "$status_url")"
  status="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Status"])')"
  case "$status" in
    completed)
      chunk_count="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ChunkCount"])')"
      if [[ "$chunk_count" -le 0 ]]; then
        echo "Ingestion completed without chunks: $response" >&2
        exit 1
      fi
      break
      ;;
    failed)
      echo "Ingestion failed: $response" >&2
      exit 1
      ;;
    queued|processing)
      sleep "$poll_interval"
      ;;
    *)
      echo "Unexpected ingestion status '$status': $response" >&2
      exit 1
      ;;
  esac
done

if [[ "${status:-}" != "completed" ]]; then
  echo "Timed out polling $status_url after $poll_limit attempts" >&2
  exit 1
fi

database_status="$(docker compose exec -T db \
  psql -U postgres -d lancet -Atc \
  "SELECT status || ':' || chunk_count FROM documents WHERE id = '${document_id}'")"
if [[ "$database_status" != "completed:${chunk_count}" ]]; then
  echo "PostgreSQL state mismatch: expected completed:${chunk_count}, got ${database_status:-<missing>}" >&2
  exit 1
fi

echo "Ingestion validation: SUCCESS (${document_id}, ${chunk_count} chunks)"
