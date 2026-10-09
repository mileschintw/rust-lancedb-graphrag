"""Tests for `eval/scripts/build_metadata_sidecar.py` (D-144 backfill, 06.3.6-08)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

from lancet_eval.config import repo_root
from lancet_eval.evidence_meta import normalise

SCRIPT_PATH = repo_root() / "eval" / "scripts" / "build_metadata_sidecar.py"
CORPUS = repo_root() / "eval" / "corpora" / "multihop_rag"


def _load_script() -> Any:
    """Loads the script by file path (a standalone script, not a package member)."""
    spec = importlib.util.spec_from_file_location("build_metadata_sidecar", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_metadata_sidecar"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


def _uuid4() -> str:
    return str(uuid.uuid4())


def test_committed_corpus_joins_346_of_346() -> None:
    entries = script.load_entries(CORPUS / "document_map.json")
    documents = script.load_documents(CORPUS / "documents.subset.jsonl")
    sidecar = script.build_sidecar(entries, documents)

    assert sidecar["schema"] == 1
    rows = sidecar["rows"]
    assert len(rows) == 346 == len(entries) == len(documents)
    for document_id, row in rows.items():
        parsed = uuid.UUID(document_id)
        assert parsed.version == 4
        assert str(parsed) == document_id
        assert set(row) == {"doc_title", "source", "published_date"}
        assert row["doc_title"] is not None
        assert row["published_date"] is not None
        assert len(row["doc_title"]) <= 512
        assert row["source"] is None or len(row["source"]) <= 256


def test_backfill_equals_what_fresh_ingest_sends() -> None:
    entries = script.load_entries(CORPUS / "document_map.json")
    documents = script.load_documents(CORPUS / "documents.subset.jsonl")
    sidecar = script.build_sidecar(entries, documents)
    by_title = {str(d["title"]).strip(): d for d in documents}
    for document_id, entry in entries.items():
        expected = normalise(by_title[str(entry["corpus_id"]).strip()])
        assert sidecar["rows"][document_id] == expected


def test_duplicate_title_in_documents_raises() -> None:
    documents = [
        {"title": "Same", "source": "A", "published_at": "2023-10-07T00:00:00+00:00"},
        {"title": "Same", "source": "B", "published_at": "2023-10-08T00:00:00+00:00"},
    ]
    entries = {_uuid4(): {"corpus_id": "Same"}}
    with pytest.raises(script.SidecarError, match="ambiguous title"):
        script.build_sidecar(entries, documents)


def test_unmatched_entry_raises() -> None:
    documents = [{"title": "Present"}]
    entries = {_uuid4(): {"corpus_id": "Absent"}}
    with pytest.raises(script.SidecarError, match="no corpus row"):
        script.build_sidecar(entries, documents)


def test_duplicate_corpus_id_in_entries_raises() -> None:
    documents = [{"title": "One"}]
    entries = {_uuid4(): {"corpus_id": "One"}, _uuid4(): {"corpus_id": "One"}}
    with pytest.raises(script.SidecarError, match="ambiguous corpus_id"):
        script.build_sidecar(entries, documents)


def test_non_uuid4_document_id_raises() -> None:
    documents = [{"title": "One"}]
    with pytest.raises(script.SidecarError, match="UUIDv4"):
        script.build_sidecar({"not-a-uuid": {"corpus_id": "One"}}, documents)
    # A valid UUID of another version is not a v4 document id either.
    with pytest.raises(script.SidecarError, match="UUIDv4"):
        script.build_sidecar({str(uuid.uuid1()): {"corpus_id": "One"}}, documents)


def test_cli_writes_deterministic_sidecar_and_prints_hash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "nested" / "sidecar.json"
    argv = [
        "--document-map",
        str(CORPUS / "document_map.json"),
        "--documents",
        str(CORPUS / "documents.subset.jsonl"),
        "--out",
        str(out),
    ]
    assert script.main(argv) == 0
    first = out.read_bytes()
    printed = capsys.readouterr().out
    assert "rows: 346" in printed
    assert f"sha256: {hashlib.sha256(first).hexdigest()}" in printed
    assert json.loads(first)["schema"] == 1

    assert script.main(argv) == 0
    assert out.read_bytes() == first


def test_cli_refuses_ambiguity_with_nonzero_exit(tmp_path: Path) -> None:
    doc_map = tmp_path / "map.json"
    doc_map.write_text(
        json.dumps({"entries": {_uuid4(): {"corpus_id": "Same"}}}), encoding="utf-8"
    )
    documents = tmp_path / "docs.jsonl"
    documents.write_text('{"title": "Same"}\n{"title": "Same"}\n', encoding="utf-8")
    out = tmp_path / "out.json"
    code = script.main([
        "--document-map",
        str(doc_map),
        "--documents",
        str(documents),
        "--out",
        str(out),
    ])
    assert code == 1
    assert not out.exists()
