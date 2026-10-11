#!/usr/bin/env bash
# Q7: boot the freshly built release engine (fresh clone) over an EMPTY store with a dummy key (as engine/tests/config_startup.rs does).
# No OpenRouter call is made at boot; isolated port + store; OTLP pointed at a dead port so the dev stack sees nothing.
set -u
CLONE="$1"; PORT=50977
BASE="$(mktemp -d)"; STORE="$BASE/lancedb"
cd "$CLONE"
OPENROUTER_API_KEY=test-key LANCET_ENGINE__GRPC_ADDR=127.0.0.1:$PORT LANCET_ENGINE__LANCEDB_PATH="$STORE" \
  LANCET_ENGINE__TELEMETRY__OTLP_ENDPOINT=http://127.0.0.1:1 NO_COLOR=1 \
  ./engine/target/release/engine.exe > "$BASE/engine.log" 2>&1 &
PID=$!
sleep 12
echo "engine pid $PID alive? $(kill -0 $PID 2>/dev/null && echo yes || echo no)"
echo "--- non-lance log lines (ANSI stripped)"
grep -v -E "lance::|load: lance" "$BASE/engine.log" | sed 's/\x1b\[[0-9;]*m//g' | cut -c1-400 | head -30
kill $PID 2>/dev/null; sleep 1; taskkill //F //PID $PID >/dev/null 2>&1
