"""Tests for the three-way index identity gate and the guarded PostgreSQL delete."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from lancet_eval.config import EvalSettings
from lancet_eval.identity import (
    IdentityGateError,
    compute_identity,
    delete_pg_extras,
    list_lancedb_document_ids,
    list_pg_documents,
    require_index_identity,
)
from lancet_eval.seed import (
    DocumentMap,
    DocumentMapEntry,
    SeedError,
    save_document_map_atomic,
)

DOC_A = "01070ac6-0fc0-464d-9f1f-756573b99c0e"
DOC_B = "01c8bfa7-09e6-450d-939a-44886b8d00d5"
ALIAS_ID = "0370301a-0000-0000-0000-000000000000"


def _settings(tmp_path: Path) -> EvalSettings:
    return EvalSettings(
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
        database_url=(
            "postgres://postgres:postgres@127.0.0.1:5432/lancet"
            "?sslmode=disable&search_path=lancet_eval"
        ),
        dev_database_url=(
            "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable"
        ),
    )


def _write_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    corpus: str = "multihop_rag",
    entries: dict[str, str] | None = None,
    aliases: dict[str, str] | None = None,
) -> None:
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    entries = entries if entries is not None else {DOC_A: "Article A", DOC_B: "Article B"}
    doc_map = DocumentMap(
        corpus=corpus,
        seeded_at="2026-09-01T00:00:00Z",
        index_generation="lance-900",
        entries={
            doc_id: DocumentMapEntry(corpus_id=title, document_id=doc_id, title=title)
            for doc_id, title in entries.items()
        },
        aliases=aliases or {},
    )
    save_document_map_atomic(doc_map)


def _lance_ok(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "documents": [DOC_A, DOC_B],
        "nodes": [DOC_A, DOC_B],
        "edges": [],
        "entity_edges": [],
        "staged_documents_v2_rows": 0,
    }
    base.update(overrides)
    return base


def _pg_ok(**overrides: dict[str, str]) -> dict[str, str]:
    base = {DOC_A: "completed", DOC_B: "completed"}
    base.update(overrides)
    return base


def test_equal_sets_and_zero_staged_rows_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Equal sets and 0 staged rows: IdentityReport.passed is True."""
    _write_map(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids", lambda path: _lance_ok()
    )
    monkeypatch.setattr("lancet_eval.identity.list_pg_documents", lambda settings: _pg_ok())

    report = compute_identity(_settings(tmp_path), "multihop_rag")
    assert report.passed is True
    assert report.failures == []
    require_index_identity(_settings(tmp_path), "multihop_rag")  # does not raise


def test_extra_id_in_lancedb_documents_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An extra ID in LanceDB documents fails, naming the symmetric difference."""
    _write_map(tmp_path, monkeypatch)
    extra = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids",
        lambda path: _lance_ok(documents=[DOC_A, DOC_B, extra]),
    )
    monkeypatch.setattr("lancet_eval.identity.list_pg_documents", lambda settings: _pg_ok())

    report = compute_identity(_settings(tmp_path), "multihop_rag")
    assert report.passed is False
    assert any(extra in f for f in report.failures)
    with pytest.raises(IdentityGateError, match=extra):
        require_index_identity(_settings(tmp_path), "multihop_rag")


def test_map_id_missing_from_nodes_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A map ID missing from nodes fails, naming the symmetric difference."""
    _write_map(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids",
        lambda path: _lance_ok(nodes=[DOC_A]),
    )
    monkeypatch.setattr("lancet_eval.identity.list_pg_documents", lambda settings: _pg_ok())

    report = compute_identity(_settings(tmp_path), "multihop_rag")
    assert report.passed is False
    assert any("nodes" in f and DOC_B in f for f in report.failures)


def test_extra_postgresql_id_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An extra PostgreSQL ID fails, naming the symmetric difference."""
    _write_map(tmp_path, monkeypatch)
    extra = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids", lambda path: _lance_ok()
    )
    monkeypatch.setattr(
        "lancet_eval.identity.list_pg_documents",
        lambda settings: _pg_ok(**{extra: "completed"}),
    )

    report = compute_identity(_settings(tmp_path), "multihop_rag")
    assert report.passed is False
    assert any(extra in f for f in report.failures)


def test_entity_edges_ids_outside_map_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """entity_edges IDs outside the map fail."""
    _write_map(tmp_path, monkeypatch)
    outside = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids",
        lambda path: _lance_ok(entity_edges=[outside]),
    )
    monkeypatch.setattr("lancet_eval.identity.list_pg_documents", lambda settings: _pg_ok())

    report = compute_identity(_settings(tmp_path), "multihop_rag")
    assert report.passed is False
    assert any("entity_edges" in f and outside in f for f in report.failures)


def test_edges_ids_outside_map_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """edges IDs outside the map fail."""
    _write_map(tmp_path, monkeypatch)
    outside = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids",
        lambda path: _lance_ok(edges=[outside]),
    )
    monkeypatch.setattr("lancet_eval.identity.list_pg_documents", lambda settings: _pg_ok())

    report = compute_identity(_settings(tmp_path), "multihop_rag")
    assert report.passed is False
    assert any("edges" in f and outside in f for f in report.failures)


def test_alias_present_in_lancedb_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The alias ID present in LanceDB fails with reason alias_present (D-60)."""
    _write_map(tmp_path, monkeypatch, aliases={ALIAS_ID: DOC_A})
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids",
        lambda path: _lance_ok(documents=[DOC_A, DOC_B, ALIAS_ID]),
    )
    monkeypatch.setattr("lancet_eval.identity.list_pg_documents", lambda settings: _pg_ok())

    report = compute_identity(_settings(tmp_path), "multihop_rag")
    assert report.passed is False
    assert any("alias_present" in f for f in report.failures)


def test_alias_present_in_postgresql_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The alias ID present in PostgreSQL fails with reason alias_present (D-60)."""
    _write_map(tmp_path, monkeypatch, aliases={ALIAS_ID: DOC_A})
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids", lambda path: _lance_ok()
    )
    monkeypatch.setattr(
        "lancet_eval.identity.list_pg_documents",
        lambda settings: _pg_ok(**{ALIAS_ID: "completed"}),
    )

    report = compute_identity(_settings(tmp_path), "multihop_rag")
    assert report.passed is False
    assert any("alias_present" in f for f in report.failures)


def test_staged_rows_present_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """staged_documents_v2_rows > 0 fails with reason staged_rows_present."""
    _write_map(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids",
        lambda path: _lance_ok(staged_documents_v2_rows=3),
    )
    monkeypatch.setattr("lancet_eval.identity.list_pg_documents", lambda settings: _pg_ok())

    report = compute_identity(_settings(tmp_path), "multihop_rag")
    assert report.passed is False
    assert any("staged_rows_present" in f for f in report.failures)
    assert report.staged_rows == 3


def test_postgresql_row_not_completed_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PostgreSQL row whose status is not completed fails."""
    _write_map(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids", lambda path: _lance_ok()
    )
    monkeypatch.setattr(
        "lancet_eval.identity.list_pg_documents",
        lambda settings: _pg_ok(**{DOC_A: "processing"}),
    )

    report = compute_identity(_settings(tmp_path), "multihop_rag")
    assert report.passed is False
    assert any("not completed" in f for f in report.failures)


def test_list_lancedb_document_ids_parses_subprocess_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """list_lancedb_document_ids parses the --document-ids JSON contract from stdout."""
    payload = (
        '{"documents": ["a"], "nodes": ["a"], "edges": [], "entity_edges": [], '
        '"staged_documents_v2_rows": 0}'
    )

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert "--document-ids" in cmd
        assert "--lancedb-path" in cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=payload, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = list_lancedb_document_ids(str(tmp_path / "lancedb-eval"))
    assert result["documents"] == ["a"]
    assert result["staged_documents_v2_rows"] == 0


def test_list_lancedb_document_ids_raises_on_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_lancedb_document_ids raises IdentityGateError on a non-zero exit."""

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="boom"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(IdentityGateError, match="boom"):
        list_lancedb_document_ids("./data/lancedb-eval")


def test_list_lancedb_document_ids_raises_on_unparseable_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_lancedb_document_ids raises IdentityGateError on unparseable stdout."""

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="not json", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(IdentityGateError):
        list_lancedb_document_ids("./data/lancedb-eval")


def test_list_pg_documents_parses_run_psql_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """list_pg_documents parses unaligned tuples-only psql output via run_psql."""

    def fake_run_psql(settings: EvalSettings, sql: str, **kwargs: object) -> str:
        assert "lancet_eval.documents" in sql
        return f"{DOC_A}|completed\n{DOC_B}|processing\n"

    monkeypatch.setattr("lancet_eval.identity.run_psql", fake_run_psql)

    result = list_pg_documents(_settings(tmp_path))
    assert result == {DOC_A: "completed", DOC_B: "processing"}


def test_delete_pg_extras_apply_without_dump_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """delete_pg_extras(apply=True) without an existing non-empty pg_dump_path raises."""
    monkeypatch.setattr(
        "lancet_eval.identity.list_pg_documents",
        lambda settings: _pg_ok(**{"eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee": "completed"}),
    )

    with pytest.raises(SeedError, match="pg_dump_path"):
        delete_pg_extras(
            _settings(tmp_path), allow_ids={DOC_A, DOC_B}, apply=True, pg_dump_path=None
        )


def test_delete_pg_extras_refuses_non_lancet_eval_schema(
    tmp_path: Path,
) -> None:
    """delete_pg_extras with a non-lancet_eval schema raises via the schema check."""
    settings = EvalSettings(
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
        database_url=(
            "postgres://postgres:postgres@127.0.0.1:5432/lancet"
            "?sslmode=disable&search_path=other_eval"
        ),
        dev_database_url=(
            "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable"
        ),
    )

    with pytest.raises(SeedError, match="lancet_eval"):
        delete_pg_extras(settings, allow_ids={DOC_A}, apply=False, pg_dump_path=None)


def test_delete_pg_extras_refuses_non_uuid_id_before_any_sql(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-UUID allow_id raises before any SQL is built (no subprocess call)."""
    calls: list[object] = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(a))

    with pytest.raises(SeedError, match="non-UUID"):
        delete_pg_extras(
            _settings(tmp_path),
            allow_ids={"not-a-uuid"},
            apply=False,
            pg_dump_path=None,
        )
    assert calls == []


def test_delete_pg_extras_refuses_empty_allow_ids(tmp_path: Path) -> None:
    """An empty allow_ids is refused rather than deleting every document."""
    with pytest.raises(SeedError, match="empty allow_ids"):
        delete_pg_extras(_settings(tmp_path), allow_ids=set(), apply=False, pg_dump_path=None)


def test_delete_pg_extras_dry_run_returns_extras_and_executes_no_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dry-run returns the extra IDs and executes no DELETE."""
    extra = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    sql_seen: list[str] = []

    def fake_run_psql(settings: EvalSettings, sql: str, **kwargs: object) -> str:
        sql_seen.append(sql)
        return f"{DOC_A}|completed\n{extra}|completed\n"

    monkeypatch.setattr("lancet_eval.identity.run_psql", fake_run_psql)

    result = delete_pg_extras(
        _settings(tmp_path), allow_ids={DOC_A}, apply=False, pg_dump_path=None
    )
    assert result == [extra]
    assert all("DELETE" not in sql for sql in sql_seen)


def test_delete_pg_extras_apply_runs_single_transaction_and_returns_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """apply=True with a valid dump path runs one transaction and returns deleted IDs."""
    dump_path = tmp_path / "backup.sql"
    dump_path.write_text("-- pg_dump contents\n", encoding="utf-8")

    extra = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    call_count = {"n": 0}

    def fake_run_psql(settings: EvalSettings, sql: str, **kwargs: object) -> str:
        call_count["n"] += 1
        if "DELETE" in sql:
            assert sql.count("BEGIN;") == 1
            assert sql.count("COMMIT;") == 1
            return ""
        # SELECT calls: before delete both rows exist, after delete only DOC_A remains
        if call_count["n"] == 1:
            return f"{DOC_A}|completed\n{extra}|completed\n"
        return f"{DOC_A}|completed\n"

    monkeypatch.setattr("lancet_eval.identity.run_psql", fake_run_psql)

    result = delete_pg_extras(
        _settings(tmp_path), allow_ids={DOC_A}, apply=True, pg_dump_path=dump_path
    )
    assert result == [extra]
