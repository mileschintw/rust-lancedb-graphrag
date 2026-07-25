#!/usr/bin/env bash
set -euo pipefail

phase_dir=".planning/phases/02-ingestion-chunking-vector-storage"
challenge="${phase_dir}/.02-LIVE-CHALLENGE.json"
evidence="${phase_dir}/02-LIVE-EVIDENCE.json"
mode="${1:-}"
shift || true

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
    --challenge) challenge="$2"; shift 2 ;;
    --evidence) evidence="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

require_phase_local_paths() {
  [[ "$challenge" == "${phase_dir}/.02-LIVE-CHALLENGE.json" ]] || {
    echo "challenge path must be the phase-local runtime path" >&2; exit 1;
  }
  [[ "$evidence" == "${phase_dir}/02-LIVE-EVIDENCE.json" ]] || {
    echo "evidence path must be the phase-local runtime path" >&2; exit 1;
  }
}

assert_safe_runtime_path() {
  local path="$1"
  [[ ! -L "$path" ]] || { echo "runtime artifacts must not be symlinks" >&2; exit 1; }
  [[ ! -e "$path" || -f "$path" ]] || { echo "runtime artifact path is not a regular file" >&2; exit 1; }
  git ls-files --error-unmatch -- "$path" >/dev/null 2>&1 && {
    echo "runtime artifacts must remain untracked" >&2; exit 1;
  }
  [[ -z "$(git diff --cached --name-only -- "$path")" ]] || {
    echo "runtime artifacts must not be staged" >&2; exit 1;
  }
}

parse_and_validate_gate() {
  "$python_cmd" - "$challenge" "$evidence" <<'PY'
import datetime as dt
import json
import sys
import uuid

challenge_path, evidence_path = sys.argv[1:]
with open(challenge_path, encoding="utf-8") as stream:
    challenge = json.load(stream)
with open(evidence_path, encoding="utf-8") as stream:
    evidence = json.load(stream)

challenge_keys = {"schema_version", "challenge", "run_id", "issued_at"}
evidence_keys = {
    "schema_version", "success_sentinel", "challenge", "run_id", "issued_at",
    "run_started_at", "generated_at", "document_id", "provider", "embedding_model",
    "gateway_chunk_count", "postgres_status", "postgres_chunk_count", "document_rows",
    "staged_document_rows", "node_rows", "edge_rows", "embedding_width",
    "duplicate_generation", "stale_generation",
}
assert set(challenge) == challenge_keys
assert set(evidence) == evidence_keys
assert challenge["schema_version"] == evidence["schema_version"] == 1
assert isinstance(challenge["challenge"], str) and len(challenge["challenge"]) >= 32
assert isinstance(challenge["run_id"], str) and uuid.UUID(challenge["run_id"]).version == 4
assert all(evidence[key] == challenge[key] for key in ("challenge", "run_id", "issued_at"))
assert evidence["success_sentinel"] == "Ingestion validation: SUCCESS"
assert evidence["provider"] == "openrouter"
assert evidence["embedding_model"] == "nvidia/llama-nemotron-embed-vl-1b-v2:free"
assert uuid.UUID(evidence["document_id"]).version == 4
assert evidence["postgres_status"] == "completed"
assert all(isinstance(evidence[key], int) and not isinstance(evidence[key], bool) for key in (
    "gateway_chunk_count", "postgres_chunk_count", "document_rows", "staged_document_rows",
    "node_rows", "edge_rows", "embedding_width"))
assert evidence["gateway_chunk_count"] == evidence["postgres_chunk_count"] == evidence["node_rows"] > 0
assert evidence["document_rows"] == 1 and evidence["staged_document_rows"] == 0
assert evidence["edge_rows"] >= 0 and evidence["embedding_width"] == 2048
assert evidence["duplicate_generation"] is False and evidence["stale_generation"] is False
parse = lambda value: dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
issued, started, generated = map(parse, (challenge["issued_at"], evidence["run_started_at"], evidence["generated_at"]))
assert issued.tzinfo is not None and started.tzinfo is not None and generated.tzinfo is not None
assert issued <= started <= generated
assert dt.datetime.now(dt.timezone.utc) - generated <= dt.timedelta(minutes=30)
assert generated <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)
print(evidence["document_id"])
PY
}

case "$mode" in
  --self-test)
    bash -n "$0"
    "$python_cmd" - <<'PY'
import json
assert json.loads('{"schema_version":1}')["schema_version"] == 1
PY
    ;;
  --prepare-gate)
    require_phase_local_paths
    mkdir -p "$phase_dir"
    assert_safe_runtime_path "$challenge"
    assert_safe_runtime_path "$evidence"
    for command in cargo docker; do command -v "$command" >/dev/null || {
      echo "required command is unavailable: $command" >&2; exit 1;
    }; done
    bash -n "$0"
    bash -n verify-ingestion.sh
    cargo check --quiet --manifest-path engine/Cargo.toml --bin inspect_lancedb
    docker compose up -d db
    for _ in $(seq 1 30); do
      [[ "$(docker inspect --format '{{.State.Health.Status}}' lancet-postgres 2>/dev/null || true)" == "healthy" ]] && break
      sleep 2
    done
    [[ "$(docker inspect --format '{{.State.Health.Status}}' lancet-postgres 2>/dev/null || true)" == "healthy" ]] || {
      echo "PostgreSQL did not become healthy" >&2; exit 1;
    }
    assert_safe_runtime_path "$challenge"
    assert_safe_runtime_path "$evidence"
    rm -f -- "$evidence" "$challenge"
    umask 077
    tmp="$(mktemp "${phase_dir}/.challenge.XXXXXX")"
    trap 'rm -f -- "$tmp"' EXIT
    "$python_cmd" - "$tmp" <<'PY'
import datetime as dt
import json
import os
import secrets
import sys
import uuid

payload = {
    "schema_version": 1,
    "challenge": secrets.token_urlsafe(32),
    "run_id": str(uuid.uuid4()),
    "issued_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
with open(sys.argv[1], "w", encoding="utf-8") as stream:
    json.dump(payload, stream, separators=(",", ":"))
os.chmod(sys.argv[1], 0o600)
PY
    chmod 600 "$tmp" 2>/dev/null || true
    mv -f -- "$tmp" "$challenge"
    trap - EXIT
    echo "Run exactly: bash ./verify-ingestion.sh --managed-services --challenge-file ${challenge} --evidence ${evidence}"
    ;;
  --validate-gate)
    require_phase_local_paths
    assert_safe_runtime_path "$challenge"
    assert_safe_runtime_path "$evidence"
    [[ -s "$challenge" && -s "$evidence" ]] || { echo "challenge and evidence are required" >&2; exit 1; }
    document_id="$(parse_and_validate_gate)"
    postgres="$(docker compose exec -T db psql -U postgres -d lancet -Atc "SELECT status || ':' || chunk_count FROM documents WHERE id = '${document_id}'")"
    inspection="$(cargo run --quiet --manifest-path engine/Cargo.toml --bin inspect_lancedb -- --document-id "$document_id")"
    "$python_cmd" - "$evidence" "$postgres" "$inspection" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    evidence = json.load(stream)
status, count = sys.argv[2].split(":", 1)
inspection = json.loads(sys.argv[3])
assert status == evidence["postgres_status"] == "completed"
assert int(count) == evidence["postgres_chunk_count"] == evidence["node_rows"] > 0
for key in ("document_id", "provider", "embedding_model", "document_rows", "staged_document_rows", "node_rows", "edge_rows", "embedding_width", "stale_generation"):
    assert inspection[key] == evidence[key]
assert inspection["document_rows"] == 1 and inspection["staged_document_rows"] == 0
assert inspection["node_rows"] > 0 and inspection["edge_rows"] >= 0
assert inspection["embedding_width"] == 2048 and inspection["stale_generation"] is False
PY
    rm -f -- "$challenge"
    echo "Live evidence validated"
    ;;
  *)
    echo "usage: verify-live-evidence.sh --prepare-gate|--validate-gate|--self-test" >&2
    exit 2
    ;;
esac
