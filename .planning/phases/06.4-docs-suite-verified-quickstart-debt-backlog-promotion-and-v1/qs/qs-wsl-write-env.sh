#!/usr/bin/env bash
# Writes the WSL clone's env file from the key on STDIN (06.4 plan 10, note 8c, T-06.4-30).
#
#   <key> | qs-wsl-write-env.sh <clone>
#
# The key arrives on stdin only: never in argv, WSLENV, a log or a transcript. A PowerShell pipe
# appends CRLF, so every CR and LF byte is stripped first (W-4). The script then
#   - refuses (exit 1, printing only the length) a stripped key of 20 characters or fewer;
#   - copies <clone>/.env.example to <clone>/.env under umask 077 and rewrites the
#     OPENROUTER_API_KEY= line with the stripped value (handed to awk through its environment,
#     so it never appears in argv);
#   - refuses (exit 1) if the written file holds a CR byte;
# and prints only "key_len=<n>". Exit codes: 0 ok; 1 refused; 2 usage or missing example file.
set -euo pipefail
umask 077

clone="${1:-}"
if [ -z "$clone" ] || [ ! -f "$clone/.env.example" ]; then
  echo "usage: <key on stdin> | qs-wsl-write-env.sh <clone containing .env.example>" >&2
  exit 2
fi

key="$(tr -d '\r\n')"
len="${#key}"
if [ "$len" -le 20 ]; then
  echo "refused: stripped key length is $len (must be greater than 20)" >&2
  exit 1
fi

out="$clone/.env"
tmp="$out.tmp.$$"
trap 'rm -f "$tmp"' EXIT
QS_KEY_VALUE="$key" awk '
  BEGIN { k = ENVIRON["QS_KEY_VALUE"]; n = 0 }
  /^OPENROUTER_API_KEY=/ { print "OPENROUTER_API_KEY=" k; n++; next }
  { print }
  END { if (n != 1) exit 3 }
' "$clone/.env.example" > "$tmp" || {
  echo "refused: expected exactly one OPENROUTER_API_KEY= line in .env.example" >&2
  exit 1
}
mv -f "$tmp" "$out"
trap - EXIT
chmod 600 "$out"

cr="$(tr -cd '\r' < "$out" | wc -c | tr -d ' ')"
if [ "$cr" -ne 0 ]; then
  echo "refused: the written env file holds $cr CR byte(s)" >&2
  exit 1
fi
echo "key_len=$len"
