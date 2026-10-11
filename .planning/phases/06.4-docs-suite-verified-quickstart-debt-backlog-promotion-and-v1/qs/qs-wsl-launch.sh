#!/usr/bin/env bash
# Starts the engine and the gateway inside the WSL fresh clone and stays alive so the hosting
# wsl.exe keeps the distro up (06.4 plan 10, D-220, D-199). qs-wsl-host.ps1 starts this script
# through WMI so the whole tree sits outside the executor's job object.
#
#   qs-wsl-launch.sh <clone> <ev>
#
# <ev> is /mnt/d/Repos/lancet/data/qs-evidence/wsl-<date>. Writes <ev>/engine.log,
# <ev>/gateway.log and <ev>/pids (one "<role> <process-group-id>" line each).
# Exit codes: 0 both services ended; 3 refused (D-199 override variable, <ev>/launch.refused);
# 4 key missing or too short, or the env file is missing; 5 the engine never reported serving.
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/go/bin:$PATH"

clone="${1:?usage: qs-wsl-launch.sh <clone> <ev>}"
ev="${2:?usage: qs-wsl-launch.sh <clone> <ev>}"
mkdir -p "$ev"
cd "$clone"
rm -f "$ev/launch.refused" "$ev/pids"

find_overrides() {
  env | sed -n 's/^\(LANCET_ENGINE__\(GRAPH\|LEVERS\)__[A-Za-z0-9_]*\)=.*/\1/p'
}

# 1. Drop any inherited key, import the clone's env file with the README's own one-liner, and
#    assert the key by length only.
unset OPENROUTER_API_KEY
if [ ! -f ./.env ]; then
  echo "FATAL: the clone's env file is missing" >&2
  exit 4
fi
set -a; . ./.env; set +a
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
if [ "${#OPENROUTER_API_KEY}" -le 20 ]; then
  echo "FATAL: OPENROUTER_API_KEY is missing or too short (length ${#OPENROUTER_API_KEY})" >&2
  exit 4
fi

# 2. Refuse on the D-199 override variables (names only are written, never values).
overrides="$(find_overrides)"
if [ -n "$overrides" ]; then
  printf '%s\n' "$overrides" > "$ev/launch.refused"
  echo "REFUSED (D-199): override variables present: $(printf '%s' "$overrides" | tr '\n' ' ')" >&2
  exit 3
fi
export NO_COLOR=1

# 3. The README engine command, in its own session so a group kill reaches cargo and the engine.
setsid cargo run --manifest-path engine/Cargo.toml --release --bin engine > "$ev/engine.log" 2>&1 < /dev/null &
engine_pid=$!
sleep 1
engine_pgid="$(ps -o pgid= -p "$engine_pid" | tr -d ' ')"
printf 'engine %s\n' "${engine_pgid:-$engine_pid}" > "$ev/pids"

# README order: the engine serves first. The release build already exists, so this is quick; the
# wait is generous in case `cargo run` has to relink.
engine_up=no
for _ in $(seq 1 360); do
  if sed 's/\x1b\[[0-9;]*[A-Za-z]//g' "$ev/engine.log" 2>/dev/null | grep -qF 'Rust RAG Engine serving'; then
    engine_up=yes
    break
  fi
  if ! kill -0 "$engine_pid" 2>/dev/null; then
    break
  fi
  sleep 5
done
if [ "$engine_up" != yes ]; then
  echo "FATAL: the engine did not report serving (see engine.log)" >&2
  exit 5
fi

# 4. The README gateway command, from gateway/.
(
  cd gateway
  exec setsid go run . > "$ev/gateway.log" 2>&1 < /dev/null
) &
gateway_pid=$!
sleep 1
gateway_pgid="$(ps -o pgid= -p "$gateway_pid" | tr -d ' ')"
printf 'gateway %s\n' "${gateway_pgid:-$gateway_pid}" >> "$ev/pids"

# 5. Stay alive so the hosting wsl.exe, and with it the distro, outlives the short calls.
wait
