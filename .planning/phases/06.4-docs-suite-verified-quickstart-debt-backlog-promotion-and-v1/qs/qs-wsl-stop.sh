#!/usr/bin/env bash
# Stops the engine and gateway that qs-wsl-launch.sh started (06.4 plan 10, D-220, D-230, W-2).
#
#   qs-wsl-stop.sh <ev>
#
# Kills both process groups listed in <ev>/pids (a no-op when the file is absent), then asserts
# nothing listens on 8080 or 50051. The Windows side ends the hosting wsl.exe afterwards with
# `qs-wsl-host.ps1 -Stop` (plan 06.4-11 does this).
# Exit codes: 0 stopped and ports free; 1 a listener remains; 2 usage.
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/go/bin:$PATH"

ev="${1:?usage: qs-wsl-stop.sh <ev>}"
pids="$ev/pids"

if [ -f "$pids" ]; then
  while read -r role pgid; do
    [ -n "${pgid:-}" ] || continue
    if kill -0 -- "-$pgid" 2>/dev/null; then
      kill -TERM -- "-$pgid" 2>/dev/null || true
      echo "role=$role pgid=$pgid: sent TERM"
    else
      echo "role=$role pgid=$pgid: already gone"
    fi
  done < "$pids"
  sleep 3
  while read -r role pgid; do
    [ -n "${pgid:-}" ] || continue
    if kill -0 -- "-$pgid" 2>/dev/null; then
      kill -KILL -- "-$pgid" 2>/dev/null || true
      echo "role=$role pgid=$pgid: still running, sent KILL"
    fi
  done < "$pids"
else
  echo "nothing to stop: no pids file"
fi

sleep 1
busy=0
for port in 8080 50051; do
  if ss -ltn | awk 'NR > 1 { print $4 }' | grep -qE ":${port}\$"; then
    echo "STILL LISTENING: port $port"
    busy=1
  fi
done
if [ "$busy" -ne 0 ]; then
  exit 1
fi
echo "verified: nothing listens on 8080 or 50051"
