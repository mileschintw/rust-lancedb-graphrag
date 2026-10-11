#!/usr/bin/env bash
# Runs ONE named README quickstart step inside the WSL fresh clone (06.4 plan 10, D-220, D-68).
#
#   qs-wsl-run.sh <clone> <ev> <step> [arg] [arg2]
#
# <clone> is /home/<user>/lqs/wsl-<date>; <ev> is /mnt/d/Repos/lancet/data/qs-evidence/wsl-<date>.
# Every step's commands are the README's bash commands, verbatim. A comment above each step names
# its README step number. A fresh `wsl.exe` call keeps no environment, so this script exports PATH,
# sources the clone's env file (when the step needs the key) and cd's into the clone itself.
#
# Output of each step is teed to <ev>/<step>.log (<ev>/<step>-<arg>.log when an <arg> is given), and
# its exit code is written LAST to <ev>/<step>.exit (same stem). The script exits with that code.
#
# Steps: compose-up migrate health query-before query-after two-hop two-hop-graph ingest wait-swap
#        settle-before settle-after rescore teardown preflight-start <n> preflight-wait <n> <seconds>
#        preflight-kill <n> alive ports-free clone-facts build
#
# Harness additions, recorded in the transcript: NO_COLOR=1 for every step, and
# LANCET_EVAL__GATEWAY_TIMEOUT_SECS=90 for the query steps (caps each request at 90 s; the settings
# default is 300 s).
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/go/bin:$PATH"

clone="${1:?usage: qs-wsl-run.sh <clone> <ev> <step> [arg] [arg2]}"
ev="${2:?usage: qs-wsl-run.sh <clone> <ev> <step> [arg] [arg2]}"
step="${3:?usage: qs-wsl-run.sh <clone> <ev> <step> [arg] [arg2]}"
arg="${4:-}"
arg2="${5:-}"

qs_wsl="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$ev"
cd "$clone"

stem="$step"
if [ -n "$arg" ]; then stem="$step-$arg"; fi
log="$ev/$stem.log"
exitfile="$ev/$stem.exit"

export NO_COLOR=1

case "$step" in
  build | clone-facts | alive | ports-free | teardown | preflight-kill | preflight-wait) ;;
  *)
    # The documented env flow (README step 2): drop any inherited key, then export the clone's file.
    unset OPENROUTER_API_KEY
    if [ -f ./.env ]; then
      set -a; . ./.env; set +a
    fi
    ;;
esac

strip_ansi() { sed 's/\x1b\[[0-9;]*[A-Za-z]//g' "$@"; }

# The quickstart canary texts (qs-001 is the two-entity question, qs-002 the single-entity one),
# read from the committed file the README's questions are pinned to.
canary() {
  local text
  text="$(grep "\"question_id\": \"$1\"" eval/corpora/quickstart/canary.arms.jsonl | sed -E 's/.*"question": "([^"]*)".*/\1/')"
  if [ -z "$text" ]; then echo "canary $1 not found" >&2; return 1; fi
  printf '%s' "$text"
}

listening() { # port -> 0 when something listens on it
  ss -ltn | awk 'NR > 1 { print $4 }' | grep -qE ":$1\$"
}

pgid_alive() { kill -0 -- "-$1" 2>/dev/null; }

# README step 3.
step_compose_up() {
  docker compose -p lancet-qs --profile observability up -d
  local i states total bad
  for i in $(seq 1 36); do
    states="$(docker compose -p lancet-qs ps --format '{{.Service}} {{.State}} {{.Health}}')"
    total="$(printf '%s\n' "$states" | grep -c . || true)"
    bad="$(printf '%s\n' "$states" | grep -vE '^[^ ]+ running( healthy)? *$' | grep -c . || true)"
    echo "poll $i: services=$total not-ready=$bad"
    if [ "$total" -ge 6 ] && [ "$bad" -eq 0 ]; then
      docker compose -p lancet-qs ps
      return 0
    fi
    sleep 5
  done
  docker compose -p lancet-qs ps || true
  echo "compose-up: the stack was not fully up after 3 minutes" >&2
  return 1
}

# README step 4.
step_migrate() {
  cd gateway
  atlas schema apply --env local --auto-approve
  cd ..
}

# README step 8: the curl, repeated every 5 s for up to 360 s (the first `go run .` compiles).
step_health() {
  local i code
  for i in $(seq 1 72); do
    code="$(curl -s -o "$ev/health.body" -w '%{http_code}' http://127.0.0.1:8080/health || true)"
    echo "poll $i: http $code"
    if [ "$code" = "200" ]; then
      cat "$ev/health.body"; echo
      return 0
    fi
    sleep 5
  done
  echo "health: no 200 within 360 s" >&2
  return 1
}

run_query() { # text, extra flags...
  local text="$1"; shift
  export LANCET_EVAL__GATEWAY_TIMEOUT_SECS=90
  uv run --project eval python eval/scripts/quickstart.py query "$text" "$@" | tee "$ev/$stem.json"
}

# README step 9 (before ingesting) and step 11 (the same query again).
step_query_before() { run_query "$(canary qs-002)"; }
step_query_after() { run_query "$(canary qs-002)"; }
# README step 11: the two-hop question with the defaults, then with the graph opted in.
step_two_hop() { run_query "$(canary qs-001)"; }
step_two_hop_graph() { run_query "$(canary qs-001)" --graph; }

# README step 10.
step_ingest() {
  uv run --project eval python eval/scripts/quickstart.py ingest | tee "$ev/$stem.json"
}

# README step 10, the wait: two independent waits for the contract C1 literals.
step_wait_swap() {
  local cov='index.swap.metadata_coverage: documents_with_metadata=5 documents=5'
  local avail='evidence_metadata became available again'
  local copy="$ev/engine.stripped.log" i got_cov=no got_avail=no
  for i in $(seq 1 36); do
    strip_ansi "$ev/engine.log" > "$copy" 2>/dev/null || true
    if [ "$got_cov" = no ] && grep -qF "$cov" "$copy"; then got_cov=yes; fi
    if [ "$got_avail" = no ] && grep -qF "$avail" "$copy"; then got_avail=yes; fi
    if [ "$got_cov" = yes ] && [ "$got_avail" = yes ]; then break; fi
    sleep 5
  done
  echo "--- coverage literal: $got_cov"
  grep -F "$cov" "$copy" | tail -n 1 || true
  echo "--- availability literal: $got_avail"
  grep -F "$avail" "$copy" | tail -n 1 || true
  if [ "$got_cov" = yes ] && [ "$got_avail" = yes ]; then return 0; fi
  echo "wait-swap: a contract C1 literal is missing after 180 s" >&2
  return 1
}

# D-222 settled-spend reading, bounded by its own 420 s deadline.
step_settle_before() { uv run --project eval python "$qs_wsl/qs-settle.py" --out "$ev/$stem.json"; }
step_settle_after() { uv run --project eval python "$qs_wsl/qs-settle.py" --out "$ev/$stem.json"; }

# README step 13 (offline re-score).
step_rescore() {
  local RUN TMP
  RUN=eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout
  TMP=$(mktemp -d) && cp "$RUN/journal.jsonl" "$TMP/"
  uv run --project eval lancet-eval score --run "$TMP" --no-judge
  uv run --project eval lancet-eval report --run "$TMP"
  uv run --project eval python eval/scripts/compare_rescore.py "$RUN" "$TMP"
  local dirty
  dirty="$(git status --porcelain -- eval/runs)"
  if [ -n "$dirty" ]; then
    echo "git status printed (it must print nothing):"
    printf '%s\n' "$dirty"
    return 5
  fi
  echo "git status printed nothing"
}

# README step 15 (the stack only; the engine and gateway are stopped by qs-wsl-stop.sh first).
step_teardown() {
  docker compose -p lancet-qs --profile observability down -v
}

# README step 14, started detached. The WMI-hosted wsl.exe keeps the distro up, so the preflight
# outlives this short call.
step_preflight_start() {
  local n="${arg:?preflight-start needs an attempt number}" pg real
  rm -f "$ev/preflight-$n.txt" "$ev/preflight-$n.exit" "$ev/preflight-$n.pgid"
  setsid nohup bash -c 'uv run --project eval lancet-eval preflight --stack > "$1/preflight-$2.txt" 2>&1; echo "$?" > "$1/preflight-$2.exit"' _ "$ev" "$n" < /dev/null > /dev/null 2>&1 &
  pg=$!
  sleep 1
  real="$(ps -o pgid= -p "$pg" | tr -d ' ')"
  echo "${real:-$pg}" > "$ev/preflight-$n.pgid"
  echo "preflight $n started, process group ${real:-$pg}"
}

# Exits with the preflight's exit code when it ended; 75 still running; 76 group gone with no exit file.
step_preflight_wait() {
  local n="${arg:?preflight-wait needs an attempt number}" secs="${arg2:-420}" waited=0 pg
  if [ "$secs" -gt 420 ]; then secs=420; fi
  pg="$(cat "$ev/preflight-$n.pgid" 2>/dev/null || true)"
  while true; do
    if [ -f "$ev/preflight-$n.exit" ]; then
      local rc
      rc="$(tr -d ' \r\n' < "$ev/preflight-$n.exit")"
      echo "preflight $n ended with exit code $rc"
      return "$rc"
    fi
    if [ -n "$pg" ] && ! pgid_alive "$pg"; then
      sleep 2
      if [ -f "$ev/preflight-$n.exit" ]; then continue; fi
      echo "preflight $n: process group $pg is gone and no exit file was written" >&2
      return 76
    fi
    if [ "$waited" -ge "$secs" ]; then
      echo "preflight $n: still running after $secs s"
      return 75
    fi
    sleep 5
    waited=$((waited + 5))
  done
}

step_preflight_kill() {
  local n="${arg:?preflight-kill needs an attempt number}" pg
  pg="$(cat "$ev/preflight-$n.pgid" 2>/dev/null || true)"
  if [ -z "$pg" ] || ! pgid_alive "$pg"; then
    echo "preflight $n: nothing to kill"
    return 0
  fi
  kill -TERM -- "-$pg" 2>/dev/null || true
  sleep 3
  if pgid_alive "$pg"; then kill -KILL -- "-$pg" 2>/dev/null || true; fi
  echo "preflight $n: process group $pg killed"
}

# kill -0 on both process groups in <ev>/pids.
step_alive() {
  local role pgid dead=0
  if [ ! -f "$ev/pids" ]; then echo "no pids file" >&2; return 1; fi
  while read -r role pgid; do
    [ -n "${pgid:-}" ] || continue
    if pgid_alive "$pgid"; then
      echo "role=$role pgid=$pgid: alive"
    else
      echo "role=$role pgid=$pgid: DEAD"
      dead=1
    fi
  done < "$ev/pids"
  return "$dead"
}

# W-2: nothing may already listen where the clone binds.
step_ports_free() {
  local port busy=0
  for port in 8080 50051 5432; do
    if listening "$port"; then
      echo "PORT BUSY: $port"
      busy=1
    fi
  done
  if [ "$busy" -ne 0 ]; then return 1; fi
  echo "PORTS FREE: nothing listens on 8080, 50051 or 5432"
}

# Machine-checked clone facts. Never prints the key.
step_clone_facts() {
  local head shallow autocrlf ignored key_len=0 env_cr=0 ok=0
  head="$(git rev-parse HEAD)"
  shallow="$(git rev-parse --is-shallow-repository)"
  autocrlf="$(git config core.autocrlf || true)"
  [ -n "$autocrlf" ] || autocrlf=unset
  if git check-ignore -q .env; then ignored=yes; else ignored=no; fi
  if [ -f .env ]; then
    key_len="$(sed -n 's/^OPENROUTER_API_KEY=//p' .env | tr -d '\r\n' | wc -c | tr -d ' ')"
    env_cr="$(tr -cd '\r' < .env | wc -c | tr -d ' ')"
  else
    ok=1
  fi
  echo "head=$head"
  echo "shallow=$shallow"
  echo "autocrlf=$autocrlf"
  echo "env_ignored=$ignored"
  echo "key_len=$key_len"
  echo "env_cr=$env_cr"
  if [ "$shallow" != false ] || [ "$ignored" != yes ] || [ "$key_len" -le 20 ] || [ "$env_cr" -ne 0 ]; then ok=1; fi
  return "$ok"
}

# The cold release build. No time bound: the orchestrator waits on it. build.exit is written last by
# the wrapper, after build.times holds both the start and the end.
step_build() {
  export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-4}"
  date -u +%Y-%m-%dT%H:%M:%SZ > "$ev/build.times"
  local rc=0
  cargo build --release --locked --manifest-path engine/Cargo.toml || rc=$?
  date -u +%Y-%m-%dT%H:%M:%SZ >> "$ev/build.times"
  return "$rc"
}

fn="step_${step//-/_}"
if ! declare -F "$fn" > /dev/null; then
  echo "unknown step: $step" >&2
  exit 2
fi

rm -f "$exitfile"
set +e
( set -e; "$fn" ) 2>&1 | tee "$log"
rc="${PIPESTATUS[0]}"
set -e
echo "$rc" > "$exitfile"
exit "$rc"
