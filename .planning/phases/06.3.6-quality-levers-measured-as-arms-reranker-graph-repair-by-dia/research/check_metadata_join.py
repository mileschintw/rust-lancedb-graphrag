"""Read-only check of the D-144 backfill inputs (06.3.6 AI-SPEC section 4, lever 3).

Reads only committed corpus files under eval/corpora/multihop_rag/. It never opens
data/lancedb-eval and makes no network call. Run from the repo root:

    python -I .planning/phases/06.3.6-.../research/check_metadata_join.py

What it checks, and why:
  1. document_map.json entries -> documents.subset.jsonl rows, joined on
     entries[].corpus_id == the JSONL title string (seed.py:408-410 derives corpus_id as
     title or url or id). The join must be 1:1 with 346 of 346 matched.
  2. html.unescape(title) is a fixed point after one pass (no double-escaped title).
  3. published_at parses as ISO 8601 and renders as YYYY-MM-DD.
  4. The rendered header text does not exceed a sane bound.
"""

from __future__ import annotations

import html
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CORPUS = ROOT / "eval" / "corpora" / "multihop_rag"
ENTITY_RE = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")


def main() -> int:
    rows = [
        json.loads(line)
        for line in (CORPUS / "documents.subset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    doc_map = json.loads((CORPUS / "document_map.json").read_text(encoding="utf-8"))
    entries = doc_map["entries"]
    by_title: dict[str, list[dict]] = {}
    for row in rows:
        key = str(row.get("title") or row.get("url") or row.get("id") or "").strip()
        by_title.setdefault(key, []).append(row)

    matched = 0
    ambiguous = 0
    unmatched: list[str] = []
    items = entries.items() if isinstance(entries, dict) else enumerate(entries)
    n_entries = 0
    for _, entry in items:
        n_entries += 1
        hits = by_title.get(str(entry["corpus_id"]).strip(), [])
        if len(hits) == 1:
            matched += 1
        elif len(hits) > 1:
            ambiguous += 1
        else:
            unmatched.append(str(entry["corpus_id"])[:60])

    titles_with_entity = [r["title"] for r in rows if ENTITY_RE.search(r["title"])]
    not_fixed = [t for t in titles_with_entity if html.unescape(t) != html.unescape(html.unescape(t))]
    residual = [t for t in titles_with_entity if ENTITY_RE.search(html.unescape(t))]
    sources_with_entity = [r["source"] for r in rows if ENTITY_RE.search(r["source"])]

    bad_dates: list[str] = []
    rendered: Counter[str] = Counter()
    offsets: Counter[str] = Counter()
    prefix_equals_utc_date = 0
    for row in rows:
        try:
            parsed = datetime.fromisoformat(row["published_at"])
            rendered[parsed.date().isoformat()] += 1
            offsets[str(parsed.utcoffset())] += 1
            # The engine stores the rendered date, so the UTC date must equal the 10-char prefix.
            if parsed.astimezone(UTC).date().isoformat() == row["published_at"][:10]:
                prefix_equals_utc_date += 1
        except (ValueError, KeyError):
            bad_dates.append(str(row.get("published_at")))

    print(f"documents.subset rows        : {len(rows)}")
    print(f"document_map entries         : {n_entries}")
    print(f"join matched 1:1             : {matched}")
    print(f"join ambiguous (>1 row)      : {ambiguous}")
    print(f"join unmatched               : {len(unmatched)} {unmatched[:3]}")
    print(f"titles with an HTML entity   : {len(titles_with_entity)}")
    print(f"  not a fixed point (2 passes differ): {len(not_fixed)}")
    print(f"  still hold an entity after 1 unescape: {len(residual)}")
    print(f"sources with an HTML entity  : {len(sources_with_entity)}")
    print(f"published_at unparseable     : {len(bad_dates)} {bad_dates[:3]}")
    print(f"distinct rendered dates      : {len(rendered)} (min {min(rendered)}, max {max(rendered)})")
    print(f"UTC offsets                  : {dict(offsets)}")
    print(f"UTC date == 10-char prefix   : {prefix_equals_utc_date} of {len(rows)}")
    longest = max(len(r["title"]) for r in rows), max(len(r["source"]) for r in rows)
    print(f"longest title / source (chars): {longest[0]} / {longest[1]}")
    ok = (
        matched == len(entries) == len(rows)
        and ambiguous == 0
        and not bad_dates
        and prefix_equals_utc_date == len(rows)
    )
    print("RESULT:", "join is 1:1 and all dates parse" if ok else "CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
