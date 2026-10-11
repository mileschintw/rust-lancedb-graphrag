#!/usr/bin/env bash
# Q7: read-only WSL prerequisite probe (no installs, no apt update).
for c in go atlas protoc pkg-config cmake curl git uv cargo rustc gcc make docker node chromium google-chrome; do printf "%-14s %s\n" "$c" "$(command -v $c || echo MISSING)"; done
for p in libssl-dev pkg-config protobuf-compiler cmake build-essential; do printf "%-20s %s\n" "$p" "$(dpkg -s $p 2>/dev/null | grep -E '^(Status|Version)' | tr '\n' ' ' || true)"; done
echo "--- apt candidates (local cache, read-only)"
apt-cache policy golang-go protobuf-compiler libssl-dev pkg-config 2>/dev/null | grep -E "^[a-z]|Candidate" | tr '\n' ' '; echo
echo "autocrlf: [$(git config --global core.autocrlf)]"; echo "nproc: $(nproc)  mem: $(free -g | awk '/Mem/{print $2" GB"}')"; cat /etc/os-release | head -2
