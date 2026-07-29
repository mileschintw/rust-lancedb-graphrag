#!/usr/bin/env bash
set -euo pipefail
if ! command -v cargo >/dev/null 2>&1 && ! command -v cargo.exe >/dev/null 2>&1; then
  if [[ -d "/c/Users/user3/.cargo/bin" ]]; then
    export PATH="$PATH:/c/Users/user3/.cargo/bin"
  elif [[ -d "/mnt/c/Users/user3/.cargo/bin" ]]; then
    export PATH="$PATH:/mnt/c/Users/user3/.cargo/bin"
  fi
fi
if command -v cargo >/dev/null 2>&1; then
  cargo_cmd="cargo"
elif command -v cargo.exe >/dev/null 2>&1; then
  cargo_cmd="cargo.exe"
else
  cargo_cmd="cargo"
fi
if [[ -n "${DOCKER_CMD:-}" ]]; then
  docker_cmd="$DOCKER_CMD"
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker_cmd="docker"
elif command -v docker.exe >/dev/null 2>&1; then
  docker_cmd="docker.exe"
elif command -v docker >/dev/null 2>&1; then
  docker_cmd="docker"
else
  docker_cmd="docker"
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

phase_dir=".planning/phases/02-ingestion-chunking-vector-storage"
challenge="${phase_dir}/.02-LIVE-CHALLENGE.json"
evidence="${phase_dir}/02-LIVE-EVIDENCE.json"
evidence_helper="scripts/phase02_live_evidence.py"
verification_environment="verify"
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
  "$python_cmd" -I "$evidence_helper" validate-gate --challenge "$challenge" --evidence "$evidence"
}

case "$mode" in
  --self-test)
    bash -n "$0"
    "$python_cmd" -I "$evidence_helper" self-test
    ;;
  --prepare-gate)
    require_phase_local_paths
    mkdir -p "$phase_dir"
    assert_safe_runtime_path "$challenge"
    assert_safe_runtime_path "$evidence"
    for command in cargo docker; do command -v "$command" >/dev/null 2>&1 || command -v "${command}.exe" >/dev/null 2>&1 || {
      echo "required command is unavailable: $command" >&2; exit 1;
    }; done
    bash -n "$0"
    bash -n verify-ingestion.sh
    "$python_cmd" -I "$evidence_helper" self-test
    "$cargo_cmd" check --quiet --offline --manifest-path engine/Cargo.toml --bin inspect_lancedb
    "$docker_cmd" compose up -d db
    for _ in $(seq 1 30); do
      [[ "$("$docker_cmd" inspect --format '{{.State.Health.Status}}' lancet-postgres 2>/dev/null || true)" == "healthy" ]] && break
      sleep 2
    done
    [[ "$("$docker_cmd" inspect --format '{{.State.Health.Status}}' lancet-postgres 2>/dev/null || true)" == "healthy" ]] || {
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
    export LANCET_ENV="$verification_environment"
    require_phase_local_paths
    assert_safe_runtime_path "$challenge"
    assert_safe_runtime_path "$evidence"
    [[ -s "$challenge" && -s "$evidence" ]] || { echo "challenge and evidence are required" >&2; exit 1; }
    verification_lancedb_path="$("$python_cmd" -I "$evidence_helper" resolve-store-path)"
    document_id="$(parse_and_validate_gate)"
    echo "TRACE DOCKER_CMD='${DOCKER_CMD:-}' docker_cmd='${docker_cmd:-}'" >&2
    postgres="$(${DOCKER_CMD:-$docker_cmd} compose exec -T db psql -U postgres -d lancet -Atc "SELECT status || ':' || chunk_count FROM documents WHERE id = '${document_id}'")"
    echo "TRACE postgres='$postgres'" >&2
    inspection="$("$cargo_cmd" run --quiet --manifest-path engine/Cargo.toml --bin inspect_lancedb -- --document-id "$document_id" --lancedb-path "$verification_lancedb_path")"
    printf '%s\n' "$inspection" | "$python_cmd" -I "$evidence_helper" compare-live-state \
      --challenge "$challenge" --evidence "$evidence" --postgres "$postgres" --inspection-json -
    rm -f -- "$challenge" "$evidence"
    echo "Live evidence validated"
    ;;
  *)
    echo "usage: verify-live-evidence.sh --prepare-gate|--validate-gate|--self-test" >&2
    exit 2
    ;;
esac
