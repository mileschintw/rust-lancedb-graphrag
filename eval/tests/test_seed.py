"""Tests for document seeding, resuming, mapping, and reseeding."""

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from lancet_eval.config import EvalSettings
from lancet_eval.seed import (
    DocumentMap,
    DocumentMapEntry,
    SeedError,
    reseed_corpus,
    save_document_map_atomic,
    seed_corpus,
)


def test_document_map_lookup_and_unmapped_raises(tmp_path: Path) -> None:
    doc_map = DocumentMap(
        corpus="test_corpus",
        seeded_at="2026-08-29T00:00:00Z",
        index_generation="gen-test-01",
        entries={
            "doc-gw-1": DocumentMapEntry(
                corpus_id="Article 1",
                document_id="doc-gw-1",
                title="Article 1",
                url="https://example.com/1",
            ),
        },
    )

    entry = doc_map.get_by_document_id("doc-gw-1")
    assert entry.corpus_id == "Article 1"
    assert entry.document_id == "doc-gw-1"

    with pytest.raises(KeyError, match="not found in map"):
        doc_map.get_by_document_id("unknown-doc-id")


def test_seed_corpus_multipart_no_chunk_overrides(
    httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Point corpus documents.subset.jsonl and document_map.json to tmp_path
    corpus_dir = tmp_path / "eval" / "corpora" / "multihop_rag"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    subset_file = corpus_dir / "documents.subset.jsonl"
    with open(subset_file, "w", encoding="utf-8") as f:
        f.write(
            json.dumps({
                "title": "Article Alpha",
                "text": "Alpha body text.",
                "url": "https://example.com/alpha",
            })
            + "\n"
        )

    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)

    httpx_mock.add_response(
        url="http://testgateway:8080/documents",
        method="POST",
        status_code=202,
        json={"id": "doc-gw-alpha", "status": "completed"},
    )
    httpx_mock.add_response(
        url="http://testgateway:8080/rag/query",
        method="POST",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=(
            "event: final_answer\n"
            'data: {"answer":"ok","snapshot":{"index_generation":"gen-alpha-01"}}\n\n'
            "event: workflow_completed\n"
            'data: {"success":true}\n\n'
        ),
    )

    settings = EvalSettings(
        gateway_url="http://testgateway:8080",
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
    )

    doc_map = seed_corpus("multihop_rag", settings=settings)

    assert "doc-gw-alpha" in doc_map.entries
    assert doc_map.entries["doc-gw-alpha"].corpus_id == "Article Alpha"
    assert doc_map.index_generation == "gen-alpha-01"

    # Verify upload request has file part and neither chunk_size nor chunk_overlap
    requests = [r for r in httpx_mock.get_requests() if r.url.path == "/documents"]
    assert len(requests) == 1
    req_body = requests[0].read().decode("utf-8", errors="ignore")
    assert 'name="file"' in req_body
    assert "chunk_size" not in req_body
    assert "chunk_overlap" not in req_body


def test_seed_corpus_resumes_without_reupload(
    httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus_dir = tmp_path / "eval" / "corpora" / "multihop_rag"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    subset_file = corpus_dir / "documents.subset.jsonl"
    with open(subset_file, "w", encoding="utf-8") as f:
        f.write(
            json.dumps({
                "title": "Article Alpha",
                "text": "Alpha body text.",
                "url": "https://example.com/alpha",
            })
            + "\n"
        )

    # Pre-populate document_map.json
    doc_map_init = DocumentMap(
        corpus="multihop_rag",
        seeded_at="2026-08-29T00:00:00Z",
        index_generation="gen-existing",
        entries={
            "doc-gw-alpha": DocumentMapEntry(
                corpus_id="Article Alpha",
                document_id="doc-gw-alpha",
                title="Article Alpha",
            ),
        },
    )
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    save_document_map_atomic(doc_map_init)

    httpx_mock.add_response(
        url="http://testgateway:8080/rag/query",
        method="POST",
        status_code=200,
        text='data: {"snapshot":{"index_generation":"gen-existing"}}\n\n',
    )

    settings = EvalSettings(
        gateway_url="http://testgateway:8080",
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
    )

    seed_corpus("multihop_rag", settings=settings)

    # 0 POST /documents requests issued because article was already mapped
    upload_requests = [
        r for r in httpx_mock.get_requests() if r.url.path == "/documents"
    ]
    assert len(upload_requests) == 0


def test_seed_corpus_upload_failure_raises(
    httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus_dir = tmp_path / "eval" / "corpora" / "multihop_rag"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    subset_file = corpus_dir / "documents.subset.jsonl"
    with open(subset_file, "w", encoding="utf-8") as f:
        f.write(
            json.dumps({
                "title": "Article Error",
                "text": "Text",
                "url": "https://example.com/err",
            })
            + "\n"
        )

    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)

    httpx_mock.add_response(
        url="http://testgateway:8080/documents",
        method="POST",
        status_code=500,
        text="Internal Server Error",
    )

    settings = EvalSettings(
        gateway_url="http://testgateway:8080",
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
    )

    with pytest.raises(SeedError, match="Upload failed for article 'Article Error'"):
        seed_corpus("multihop_rag", settings=settings)


def test_reseed_requires_confirmation_and_isolation_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)

    settings = EvalSettings(
        gateway_url="http://testgateway:8080",
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
    )

    # Without confirmation -> raises
    with pytest.raises(SeedError, match="Pass confirmation=True"):
        reseed_corpus("multihop_rag", confirmation=False, settings=settings)


def test_reset_refuses_default_schema() -> None:
    """Proves assert_schema_isolated refuses default public schema."""
    from lancet_eval.seed import assert_schema_isolated

    settings = EvalSettings.model_construct(
        database_url="postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable",
        dev_database_url="postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=dev",
    )
    with pytest.raises(SeedError) as exc_info:
        assert_schema_isolated(settings)
    assert "public" in str(exc_info.value)


def test_reset_refuses_dev_equal_schema() -> None:
    """Proves assert_schema_isolated refuses schema colliding with dev schema."""
    from lancet_eval.seed import assert_schema_isolated

    settings = EvalSettings.model_construct(
        database_url="postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=colliding_schema",
        dev_database_url="postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=colliding_schema",
    )
    with pytest.raises(SeedError) as exc_info:
        assert_schema_isolated(settings)
    assert "colliding_schema" in str(exc_info.value)


def test_reseed_resets_postgres_before_lancedb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves reseed runs PostgreSQL reset before LanceDB removal."""
    import subprocess

    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)

    lance_eval = tmp_path / "lancedb-eval"
    lance_eval.mkdir(parents=True, exist_ok=True)
    canary = lance_eval / "canary.txt"
    canary.write_text("survives", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        # Fail on psql reset
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="psql simulated connection error"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    settings = EvalSettings(
        gateway_url="http://testgateway:8080",
        lancedb_path=str(lance_eval),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
        database_url="postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval",
        dev_database_url="postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable",
    )

    with pytest.raises(SeedError, match="psql schema reset failed"):
        reseed_corpus("multihop_rag", confirmation=True, settings=settings)

    # LanceDB directory still exists because reset aborted before rmtree
    assert lance_eval.exists()
    assert canary.exists()
    assert "psql" in calls[0]


@pytest.mark.parametrize(
    "bad_schema",
    ["lancet_eval,public", "lancet eval", "1eval", 'eval";DROP'],
)
def test_reset_refuses_non_identifier_schema_name(
    bad_schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves non-identifier schema names are rejected without running subprocess."""
    import subprocess

    from lancet_eval.seed import assert_schema_isolated, reset_eval_schema

    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    settings = EvalSettings.model_construct(
        database_url=f"postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path={bad_schema}",
        dev_database_url="postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable",
    )

    with pytest.raises(SeedError) as exc_info:
        assert_schema_isolated(settings)
    assert bad_schema in str(exc_info.value)

    with pytest.raises(SeedError) as exc_info2:
        reset_eval_schema(settings)
    assert bad_schema in str(exc_info2.value)

    # Subprocess.run was never called
    assert len(calls) == 0


@pytest.mark.parametrize(
    ("eval_dsn", "admin_dsn", "expected_match"),
    [
        (
            "postgres://postgres:postgres@127.0.0.1:5432/lancet?search_path=lancet_eval",
            "postgres://postgres:postgres@127.0.0.2:5432/lancet",
            "host",
        ),
        (
            "postgres://postgres:postgres@127.0.0.1:5432/lancet?search_path=lancet_eval",
            "postgres://postgres:postgres@127.0.0.1:5433/lancet",
            "port",
        ),
        (
            "postgres://postgres:postgres@127.0.0.1:5432/lancet?search_path=lancet_eval",
            "postgres://postgres:postgres@127.0.0.1:5432/other_db",
            "db",
        ),
    ],
)
def test_reset_refuses_dsn_with_foreign_host_or_dbname(
    eval_dsn: str, admin_dsn: str, expected_match: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves mismatching admin DSN is rejected with no subprocess spawned."""
    import subprocess

    from lancet_eval.seed import (
        assert_admin_dsn_targets_eval_database,
        reset_eval_schema,
    )

    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    with pytest.raises(SeedError) as exc_info:
        assert_admin_dsn_targets_eval_database(eval_dsn, admin_dsn)
    assert admin_dsn in str(exc_info.value)

    settings = EvalSettings.model_construct(
        database_url=eval_dsn,
        dev_database_url=admin_dsn,
    )
    with pytest.raises(SeedError) as exc_info2:
        reset_eval_schema(settings)
    assert admin_dsn in str(exc_info2.value)

    assert len(calls) == 0

