#!/usr/bin/env bash
# Q7: cold `cargo build --release` of the engine from an EMPTY target/ in a fresh clone (separate target dir => dev stack untouched).
set -u
CLONE="$1"
cd "$CLONE"
echo "start: $(date -Is)"; echo "target exists? $(ls engine/target 2>&1 | head -1)"
echo "protoc: $(protoc --version 2>&1)  cargo: $(cargo --version)"
START=$(date +%s)
cargo build --release --locked --manifest-path engine/Cargo.toml 2>&1 | tail -25
echo "exit=${PIPESTATUS[0]}"
END=$(date +%s)
echo "end: $(date -Is)  elapsed_seconds=$((END-START))"
ls -la engine/target/release/*.exe 2>/dev/null
