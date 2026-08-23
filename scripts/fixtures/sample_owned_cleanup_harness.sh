#!/usr/bin/env bash
set -euo pipefail

caller_cwd="$(pwd)"
sample_file=""
sample_owned="${SAMPLE_OWNED:-false}"
mode="${MODE:-early_fail}"
export_temp_path="${EXPORT_TEMP_PATH:-}"

while (($#)); do
  case "$1" in
    --mode)
      mode="$2"
      shift 2
      ;;
    --export-temp-path)
      export_temp_path="$2"
      shift 2
      ;;
    --sample-owned)
      sample_owned="$2"
      shift 2
      ;;
    *)
      sample_file="$1"
      shift
      ;;
  esac
done

cleanup() {
  if [[ "$sample_owned" == "true" && -n "$sample_file" ]]; then
    rm -f -- "$sample_file"
  fi
}
trap cleanup EXIT

if [[ -z "$sample_file" ]]; then
  sample_file="$(mktemp "${TMPDIR:-/tmp}/.sample_owned_harness.XXXXXX")"
  sample_owned=true
  printf 'temporary test sample data\n' > "$sample_file"
  echo "CREATED_TEMP_SAMPLE:${sample_file}"
  if [[ -n "$export_temp_path" ]]; then
    printf '%s\n' "$sample_file" > "$export_temp_path"
  fi
fi

case "$mode" in
  early_fail)
    echo "simulating early failure" >&2
    exit 1
    ;;
  post_upload_fail)
    echo "simulating post-upload failure" >&2
    exit 1
    ;;
  success)
    echo "simulating success"
    exit 0
    ;;
  *)
    echo "unknown mode: $mode" >&2
    exit 2
    ;;
esac
