"""Builds the D-144 evidence-metadata backfill sidecar (06.3.6 plan 08).

Joins `eval/corpora/multihop_rag/document_map.json` (`entries[].corpus_id`) to the
title of each row in `documents.subset.jsonl`, applies the one normaliser the
fresh-ingest path also uses (`lancet_eval.evidence_meta.normalise`), and writes

    {"schema": 1, "rows": {"<document_id>": {"doc_title", "source", "published_date"}}}

to a path the caller names. The join must be 1:1: a duplicate title in the JSONL, a
duplicate `corpus_id` in the map, an entry whose `corpus_id` matches no row, or a key
that is not a UUIDv4 document id is an error, never a silent skip. It is read-only over
the corpus files and never opens the LanceDB store or the network.

Usage:
    python eval/scripts/build_metadata_sidecar.py \\
        --document-map PATH --documents PATH --out PATH
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lancet_eval.evidence_meta import normalise

SCHEMA_VERSION = 1


class SidecarError(ValueError):
    """The corpus files cannot be joined 1:1."""


def _row_key(row: Mapping[str, Any]) -> str:
    """The corpus id `seed.py` derives for a row: title, else url, else id."""
    return str(row.get("title") or row.get("url") or row.get("id") or "").strip()


def _is_uuid4(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


def build_sidecar(
    entries: Mapping[str, Mapping[str, Any]],
    documents: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Joins map entries to corpus rows on `corpus_id` == title, then normalises."""
    by_title: dict[str, Mapping[str, Any]] = {}
    for row in documents:
        key = _row_key(row)
        if not key:
            continue
        if key in by_title:
            raise SidecarError(
                f"ambiguous title shared by two corpus rows: {key[:80]!r}"
            )
        by_title[key] = row

    rows: dict[str, dict[str, str | None]] = {}
    seen_corpus_ids: set[str] = set()
    for document_id, entry in entries.items():
        if not _is_uuid4(document_id):
            raise SidecarError(f"document id is not a UUIDv4: {document_id!r}")
        corpus_id = str(entry.get("corpus_id", "")).strip()
        if corpus_id in seen_corpus_ids:
            raise SidecarError(
                f"ambiguous corpus_id shared by two map entries: {corpus_id[:80]!r}"
            )
        seen_corpus_ids.add(corpus_id)
        row = by_title.get(corpus_id)
        if row is None:
            raise SidecarError(f"no corpus row matches corpus_id {corpus_id[:80]!r}")
        rows[document_id] = normalise(row)
    return {"schema": SCHEMA_VERSION, "rows": rows}


def load_entries(path: Path) -> dict[str, Mapping[str, Any]]:
    """Reads `document_map.json` and returns its `entries` object."""
    doc_map = json.loads(path.read_text(encoding="utf-8"))
    entries = doc_map.get("entries")
    if not isinstance(entries, dict):
        raise SidecarError(f"{path} has no `entries` object")
    return entries


def load_documents(path: Path) -> list[dict[str, Any]]:
    """Reads a JSONL corpus file, skipping blank lines."""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def render(sidecar: Mapping[str, Any]) -> bytes:
    """Serialises the sidecar deterministically (sorted keys, LF newlines, UTF-8)."""
    text = json.dumps(sidecar, ensure_ascii=False, sort_keys=True, indent=2)
    return (text + "\n").encode("utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--document-map", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        sidecar = build_sidecar(
            load_entries(args.document_map), load_documents(args.documents)
        )
    except SidecarError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = render(sidecar)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(payload)
    print(f"rows: {len(sidecar['rows'])}")
    print(f"sha256: {hashlib.sha256(payload).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
