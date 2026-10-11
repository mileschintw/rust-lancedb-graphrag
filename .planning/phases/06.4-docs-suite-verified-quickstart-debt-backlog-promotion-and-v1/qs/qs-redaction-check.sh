#!/bin/sh
# Redaction check (06.4 plan 08, D-220, D-231): counts occurrences of the OpenRouter key
# prefix in every file given and exits 1 if any count is non-zero. Prints file names only,
# never a matching line.
#
#   sh qs-redaction-check.sh FILE [FILE ...]
#
# Exit status: 0 no occurrence in any file, 1 an occurrence found, 2 a file is unreadable
# or no file was given.
PREFIX='sk-or-'
status=0
if [ "$#" -eq 0 ]; then
  echo "usage: qs-redaction-check.sh FILE [FILE ...]" >&2
  exit 2
fi
for f in "$@"; do
  if [ ! -r "$f" ]; then
    echo "UNREADABLE: $f" >&2
    [ "$status" -eq 0 ] && status=2
    continue
  fi
  n=$(grep -c -- "$PREFIX" "$f")
  if [ "${n:-0}" -ne 0 ]; then
    echo "KEY PREFIX FOUND: $f"
    status=1
  fi
done
exit "$status"
