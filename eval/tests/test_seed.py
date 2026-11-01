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
    get_document_map_path,
    load_document_map,
    record_index_generation,
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

    # D-198: the index-generation probe must not make a paid rerank call under the
    # configured default levers.
    probes = [r for r in httpx_mock.get_requests() if r.url.path == "/rag/query"]
    assert len(probes) == 1
    probe_body = json.loads(probes[0].read().decode("utf-8"))
    assert probe_body["disable_default_levers"] is True


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


def test_record_index_generation_writes_atomically(
    httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mocked SSE body with snapshot.index_generation writes that value atomically."""
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    doc_map = DocumentMap(corpus="multihop_rag", entries={})
    save_document_map_atomic(doc_map)

    httpx_mock.add_response(
        url="http://testgateway:8080/rag/query",
        method="POST",
        status_code=200,
        text='data: {"snapshot":{"index_generation":"lance-802"}}\n\n',
    )

    settings = EvalSettings(
        gateway_url="http://testgateway:8080",
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
    )

    result = record_index_generation(settings, "multihop_rag")
    assert result == "lance-802"

    reloaded = load_document_map("multihop_rag")
    assert reloaded.index_generation == "lance-802"


def test_record_index_generation_raises_and_leaves_file_unchanged(
    httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no generation in the response body, raises SeedError and leaves the file
    byte-identical rather than silently swallowing the missing value."""
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    doc_map = DocumentMap(corpus="multihop_rag", index_generation="", entries={})
    save_document_map_atomic(doc_map)
    path = get_document_map_path("multihop_rag")
    before_bytes = path.read_bytes()

    httpx_mock.add_response(
        url="http://testgateway:8080/rag/query",
        method="POST",
        status_code=200,
        text='data: {"snapshot":{}}\n\n',
    )

    settings = EvalSettings(
        gateway_url="http://testgateway:8080",
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
    )

    with pytest.raises(SeedError, match="No index_generation observed"):
        record_index_generation(settings, "multihop_rag")

    assert path.read_bytes() == before_bytes


def _seed_one_row(
    httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: dict
) -> bytes:
    corpus_dir = tmp_path / "eval" / "corpora" / "multihop_rag"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "documents.subset.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    httpx_mock.add_response(
        url="http://testgateway:8080/documents",
        method="POST",
        status_code=202,
        json={"id": "doc-gw-meta", "status": "completed"},
    )
    httpx_mock.add_response(
        url="http://testgateway:8080/rag/query",
        method="POST",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=(
            "event: final_answer\n"
            'data: {"answer":"ok","snapshot":{"index_generation":"gen-meta-01"}}\n\n'
            "event: workflow_completed\n"
            'data: {"success":true}\n\n'
        ),
    )
    settings = EvalSettings(
        gateway_url="http://testgateway:8080",
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
    )
    seed_corpus("multihop_rag", settings=settings)
    uploads = [r for r in httpx_mock.get_requests() if r.url.path == "/documents"]
    assert len(uploads) == 1
    return uploads[0].read()


def test_seed_corpus_sends_normalised_evidence_metadata_fields(
    httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _seed_one_row(
        httpx_mock,
        tmp_path,
        monkeypatch,
        {
            "title": "&#039;Alpha&#039; &amp; Beta",
            "text": "Body.",
            "source": "  The Verge ",
            "published_at": "2023-10-07T23:30:00-05:00",
        },
    ).decode("utf-8", errors="ignore")
    assert 'name="doc_title"' in body
    assert "'Alpha' & Beta" in body
    assert 'name="source"' in body
    assert "The Verge" in body
    assert 'name="published_date"' in body
    assert "2023-10-08" in body
    assert 'name="file"' in body


def test_seed_corpus_omits_absent_evidence_metadata_fields(
    httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _seed_one_row(
        httpx_mock,
        tmp_path,
        monkeypatch,
        {"title": "Only Title", "text": "Body.", "published_at": "not a date"},
    ).decode("utf-8", errors="ignore")
    assert 'name="doc_title"' in body
    assert 'name="source"' not in body
    assert 'name="published_date"' not in body


# --- S1 store isolation (D-251) ------------------------------------------------------


def _s1_layout(root: Path) -> tuple[Path, Path]:
    """Lay out a repo-shaped temp dir holding both stores, each with a canary file."""
    (root / "config").mkdir()
    (root / "config" / "config.eval-s1.toml").write_text(
        '[engine]\nlancedb_path = "./data/lancedb-eval-s1"\n', encoding="utf-8"
    )
    canaries = []
    for name in ("lancedb-eval", "lancedb-eval-s1"):
        store_dir = root / "data" / name
        store_dir.mkdir(parents=True)
        canary = store_dir / "canary.txt"
        canary.write_text("survives", encoding="utf-8")
        canaries.append(canary)
    return canaries[0], canaries[1]


def _s1_settings(lancedb_path: str, schema: str) -> EvalSettings:
    return EvalSettings(
        gateway_url="http://testgateway:8080",
        lancedb_path=lancedb_path,
        dev_lancedb_path="./data/lancedb",
        database_url=(
            "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable"
            f"&search_path={schema}"
        ),
        dev_database_url="postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable",
    )


@pytest.fixture
def s1_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A temp repo root (cwd included) with both stores; subprocess must never run."""
    import subprocess

    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    monkeypatch.setattr("lancet_eval.config.repo_root", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: pytest.fail(f"a refused reseed ran {cmd!r}"),
    )
    return _s1_layout(tmp_path)


@pytest.mark.parametrize(
    ("lancedb_path", "schema", "refused"),
    [
        ("./data/lancedb-eval", "lancet_eval_s1", "data/lancedb-eval"),
        ("./data/lancedb-eval-s1", "lancet_eval", "lancet_eval"),
        ("./data/lancedb-eval", "lancet_eval", "data/lancedb-eval"),
    ],
)
def test_s1_reseed_refuses_the_v1_store_and_deletes_nothing(
    s1_repo: tuple[Path, Path], lancedb_path: str, schema: str, refused: str
) -> None:
    """D-251: with the S1 store selected, reseed refuses the v1.0 path or schema before
    any psql, Atlas or file deletion, so both stores' files survive."""
    from lancet_eval.config import S1_STORE

    v1_canary, s1_canary = s1_repo
    with pytest.raises(SeedError, match="v1.0") as exc_info:
        reseed_corpus(
            "multihop_rag",
            confirmation=True,
            settings=_s1_settings(lancedb_path, schema),
            store=S1_STORE,
        )

    assert refused in str(exc_info.value).replace("\\", "/")
    assert v1_canary.read_text(encoding="utf-8") == "survives"
    assert s1_canary.read_text(encoding="utf-8") == "survives"


def test_s1_seed_refuses_the_v1_store(s1_repo: tuple[Path, Path]) -> None:
    """D-251: seed with the S1 store selected refuses the v1.0 path before uploading."""
    from lancet_eval.config import S1_STORE

    with pytest.raises(SeedError, match="v1.0"):
        seed_corpus(
            "multihop_rag",
            settings=_s1_settings("./data/lancedb-eval", "lancet_eval_s1"),
            store=S1_STORE,
        )


def test_s1_reseed_refuses_settings_that_name_another_store(
    s1_repo: tuple[Path, Path],
) -> None:
    """A path or schema that is neither store's is refused too: the S1 store is named
    explicitly, and the settings must target exactly it."""
    from lancet_eval.config import S1_STORE

    v1_canary, s1_canary = s1_repo
    with pytest.raises(SeedError, match="lancet_eval_other"):
        reseed_corpus(
            "multihop_rag",
            confirmation=True,
            settings=_s1_settings("./data/lancedb-eval-s1", "lancet_eval_other"),
            store=S1_STORE,
        )
    assert v1_canary.exists()
    assert s1_canary.exists()


def test_s1_reseed_refuses_an_overlay_that_points_elsewhere(
    s1_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    """The engine reads its store from the overlay; a harness that targets the S1 path
    while the overlay names another path is refused before anything is reset."""
    from lancet_eval.config import S1_STORE

    (tmp_path / "config" / "config.eval-s1.toml").write_text(
        '[engine]\nlancedb_path = "./data/lancedb-eval"\n', encoding="utf-8"
    )
    v1_canary, s1_canary = s1_repo
    with pytest.raises(SeedError, match="overlay"):
        reseed_corpus(
            "multihop_rag",
            confirmation=True,
            settings=_s1_settings("./data/lancedb-eval-s1", "lancet_eval_s1"),
            store=S1_STORE,
        )
    assert v1_canary.exists()
    assert s1_canary.exists()


def test_s1_reseed_resets_only_the_s1_schema_and_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-251: an S1 reseed drops lancet_eval_s1, applies Atlas env eval-s1, and removes
    only data/lancedb-eval-s1; the v1.0 store directory survives."""
    import subprocess

    from lancet_eval.config import S1_STORE

    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    monkeypatch.setattr("lancet_eval.config.repo_root", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    v1_canary, s1_canary = _s1_layout(tmp_path)

    calls: list[tuple[list[str], str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((cmd, str(kwargs.get("input") or "")))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        "lancet_eval.seed.seed_corpus",
        lambda corpus, **kw: DocumentMap(corpus=corpus),
    )

    reseed_corpus(
        "multihop_rag_s1_dev",
        confirmation=True,
        settings=_s1_settings("./data/lancedb-eval-s1", "lancet_eval_s1"),
        store=S1_STORE,
    )

    psql_sql = calls[0][1]
    assert 'DROP SCHEMA IF EXISTS "lancet_eval_s1" CASCADE;' in psql_sql
    assert '"lancet_eval"' not in psql_sql
    atlas_apply = ["atlas", "schema", "apply", "--env", "eval-s1", "--auto-approve"]
    assert calls[1][0] == atlas_apply
    assert not s1_canary.exists()
    assert v1_canary.read_text(encoding="utf-8") == "survives"


def test_v1_reseed_still_applies_atlas_env_eval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default store is unchanged: reseed without a store applies Atlas env eval."""
    import subprocess

    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        "lancet_eval.seed.seed_corpus",
        lambda corpus, **kw: DocumentMap(corpus=corpus),
    )
    settings = EvalSettings(
        gateway_url="http://testgateway:8080",
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
    )

    reseed_corpus("multihop_rag", confirmation=True, settings=settings)

    assert calls[1] == ["atlas", "schema", "apply", "--env", "eval", "--auto-approve"]


def test_load_settings_for_the_s1_store_selects_its_path_and_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selecting the S1 store sets its path and schema even over v1.0 env values, and
    keeps the rest of the DSN; the default store reads settings as before."""
    from lancet_eval.config import S1_STORE, load_settings, pg_schema_of

    monkeypatch.setenv("LANCET_EVAL__LANCEDB_PATH", "./data/lancedb-eval")
    monkeypatch.setenv(
        "LANCET_EVAL__DATABASE_URL",
        "postgres://u:p@db.local:6543/lancet?sslmode=disable&search_path=lancet_eval",
    )
    missing = tmp_path / "absent.toml"

    s1 = load_settings(missing, store=S1_STORE)
    assert s1.lancedb_path == "./data/lancedb-eval-s1"
    assert pg_schema_of(s1.database_url) == "lancet_eval_s1"
    assert s1.database_url.startswith("postgres://u:p@db.local:6543/lancet?")
    assert "sslmode=disable" in s1.database_url

    v1 = load_settings(missing)
    assert v1.lancedb_path == "./data/lancedb-eval"
    assert pg_schema_of(v1.database_url) == "lancet_eval"


def test_get_eval_store_names_both_stores_and_refuses_others() -> None:
    from lancet_eval.config import (
        S1_STORE,
        V1_STORE,
        EvalConfigError,
        get_eval_store,
    )

    assert get_eval_store("eval") is V1_STORE
    assert get_eval_store("eval-s1") is S1_STORE
    with pytest.raises(EvalConfigError, match="eval, eval-s1, eval-full, eval-2wiki"):
        get_eval_store("eval-s2")


def test_committed_overlays_name_their_store_paths() -> None:
    """Each store's committed LANCET_ENV overlay names that store's LanceDB path, and
    the v1.0 overlay is unchanged."""
    from lancet_eval.config import EVAL_STORES, overlay_lancedb_path

    for store in EVAL_STORES.values():
        assert overlay_lancedb_path(store) == store.lancedb_path, store.name


def test_atlas_env_eval_s1_applies_the_eval_schema_renamed() -> None:
    """D-251: Atlas env eval-s1 targets lancet_eval_s1 with the same tables as env
    eval: its schema file is schema.eval.hcl with only the schema name changed."""
    import re

    from lancet_eval.config import repo_root

    gateway = repo_root() / "gateway"
    atlas = (gateway / "atlas.hcl").read_text(encoding="utf-8")
    env_block = re.search(r'env "eval-s1" \{(.*?)\n\}', atlas, re.S)
    assert env_block is not None
    assert 'src = "file://db/schema.eval-s1.hcl"' in env_block.group(1)
    assert "url = var.eval_s1_db_url" in env_block.group(1)
    assert re.search(
        r'variable "eval_s1_db_url" \{[^}]*search_path=lancet_eval_s1"', atlas
    )

    v1 = (gateway / "db" / "schema.eval.hcl").read_text(encoding="utf-8")
    s1 = (gateway / "db" / "schema.eval-s1.hcl").read_text(encoding="utf-8")
    renamed = re.sub(r"\blancet_eval\b", "lancet_eval_s1", v1)
    # Line 1 is each file's provenance comment; every line after it must match.
    assert s1.splitlines()[0].startswith("// schema.eval.hcl with the schema renamed")
    assert s1.splitlines()[1:] == renamed.splitlines()[1:]


def test_s1_reseed_keeps_the_v1_document_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-251: the S1 store has its own document map file, so an S1 reseed deletes only
    that file and the committed v1.0 map stays byte-identical."""
    import subprocess

    from lancet_eval.config import S1_STORE

    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    monkeypatch.setattr("lancet_eval.config.repo_root", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    _s1_layout(tmp_path)
    v1_map = get_document_map_path("multihop_rag")
    s1_map = get_document_map_path("multihop_rag", S1_STORE)
    assert s1_map.parent == v1_map.parent
    assert s1_map.name == "document_map.eval-s1.json"
    save_document_map_atomic(DocumentMap(corpus="multihop_rag", index_generation="v1"))
    save_document_map_atomic(
        DocumentMap(corpus="multihop_rag", index_generation="s1"), S1_STORE
    )
    v1_bytes = v1_map.read_bytes()
    assert load_document_map("multihop_rag", S1_STORE).index_generation == "s1"

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    seeded: dict[str, object] = {}
    monkeypatch.setattr(
        "lancet_eval.seed.seed_corpus",
        lambda corpus, **kw: seeded.update(kw) or DocumentMap(corpus=corpus),
    )

    reseed_corpus(
        "multihop_rag_s1_dev",
        confirmation=True,
        settings=_s1_settings("./data/lancedb-eval-s1", "lancet_eval_s1"),
        store=S1_STORE,
    )

    assert not s1_map.exists()
    assert v1_map.read_bytes() == v1_bytes
    assert seeded["store"] is S1_STORE


@pytest.mark.parametrize(
    ("lancet_env", "store_name"), [("eval-s1", "eval"), ("eval", "eval-s1")]
)
def test_reseed_refuses_a_lancet_env_that_names_the_other_store(
    s1_repo: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    lancet_env: str,
    store_name: str,
) -> None:
    """A shell whose LANCET_ENV names one store never reseeds the other: a forgotten
    --store under LANCET_ENV=eval-s1 does not fall back to wiping v1.0."""
    from lancet_eval.config import get_eval_store

    monkeypatch.setenv("LANCET_ENV", lancet_env)
    store = get_eval_store(store_name)
    v1_canary, s1_canary = s1_repo
    with pytest.raises(SeedError, match=f"LANCET_ENV={lancet_env}"):
        reseed_corpus(
            "multihop_rag",
            confirmation=True,
            settings=_s1_settings(store.lancedb_path, store.pg_schema),
            store=store,
        )
    with pytest.raises(SeedError, match=f"LANCET_ENV={lancet_env}"):
        seed_corpus(
            "multihop_rag",
            settings=_s1_settings(store.lancedb_path, store.pg_schema),
            store=store,
        )
    assert v1_canary.exists()
    assert s1_canary.exists()


def test_default_store_seed_refuses_settings_on_the_s1_path(
    s1_repo: tuple[Path, Path],
) -> None:
    """#18: seeding the v1.0 store with settings on the S1 path is refused, so the
    v1.0 map never receives S1 document IDs."""
    with pytest.raises(SeedError, match="--store eval-s1"):
        seed_corpus(
            "multihop_rag",
            settings=_s1_settings("./data/lancedb-eval-s1", "lancet_eval_s1"),
        )


# --- Per-store chunking (#67) ---------------------------------------------------------

_V1_ROW = {
    "title": "Article Alpha",
    "text": "Alpha body text.",
    "url": "https://example.com/alpha",
    "source": "The Verge",
    "published_at": "2023-10-07T23:30:00-05:00",
}

# The v1.0 upload of `_V1_ROW` as `main` sent it before #67, multipart boundary
# replaced by BOUNDARY: no chunk_* field, the gateway's default chunking applies.
_V1_UPLOAD = (
    b'--BOUNDARY\r\nContent-Disposition: form-data; name="doc_title"\r\n\r\n'
    b"Article Alpha\r\n"
    b'--BOUNDARY\r\nContent-Disposition: form-data; name="source"\r\n\r\n'
    b"The Verge\r\n"
    b'--BOUNDARY\r\nContent-Disposition: form-data; name="published_date"\r\n\r\n'
    b"2023-10-08\r\n"
    b'--BOUNDARY\r\nContent-Disposition: form-data; name="file"; '
    b'filename="Article_Alpha.txt"\r\nContent-Type: text/plain\r\n\r\n'
    b"Alpha body text.\r\n--BOUNDARY--\r\n"
)


def _mock_seed_gateway(httpx_mock: HTTPXMock, uploads: int) -> None:
    for i in range(uploads):
        httpx_mock.add_response(
            url="http://testgateway:8080/documents",
            method="POST",
            status_code=202,
            json={"id": f"doc-gw-{i}", "status": "completed"},
        )
    httpx_mock.add_response(
        url="http://testgateway:8080/rag/query",
        method="POST",
        text='data: {"snapshot":{"index_generation":"gen-chunk-01"}}\n\n',
    )


def _write_subset(root: Path, rows: list[dict]) -> None:
    corpus_dir = root / "eval" / "corpora" / "multihop_rag"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "documents.subset.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )


def _uploads(httpx_mock: HTTPXMock) -> list[bytes]:
    """Each upload body with its multipart boundary replaced by BOUNDARY."""
    bodies = []
    for request in httpx_mock.get_requests():
        if request.url.path != "/documents":
            continue
        boundary = request.headers["content-type"].split("boundary=")[1].encode()
        bodies.append(request.read().replace(boundary, b"BOUNDARY"))
    return bodies


def _form_field(body: bytes, name: str) -> str | None:
    marker = f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
    if marker not in body:
        return None
    return body.split(marker, 1)[1].split(b"\r\n", 1)[0].decode()


@pytest.mark.parametrize("corpus", ["multihop_rag", "multihop_rag_s1_dev"])
def test_v1_seed_upload_is_byte_for_byte_unchanged(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corpus: str,
) -> None:
    """#67: a v1.0 seed sends no chunk_* field, even for a corpus with [stores]."""
    _write_subset(tmp_path, [_V1_ROW])
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    _mock_seed_gateway(httpx_mock, uploads=1)

    seed_corpus(
        corpus,
        settings=EvalSettings(
            gateway_url="http://testgateway:8080",
            lancedb_path=str(tmp_path / "lancedb-eval"),
            dev_lancedb_path=str(tmp_path / "lancedb-dev"),
        ),
    )

    assert _uploads(httpx_mock) == [_V1_UPLOAD]


def test_s1_seed_sends_the_merged_store_chunking_with_every_upload(
    httpx_mock: HTTPXMock, s1_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    """#67: `seed --corpus multihop_rag_s1_dev --store eval-s1` sends the corpus's
    [stores.merged] chunking, and otherwise the v1.0 fields, with every upload."""
    from lancet_eval.config import S1_STORE

    second = {**_V1_ROW, "title": "Article Beta", "url": "https://example.com/beta"}
    _write_subset(tmp_path, [_V1_ROW, second])
    _mock_seed_gateway(httpx_mock, uploads=2)

    seed_corpus(
        "multihop_rag_s1_dev",
        settings=_s1_settings("./data/lancedb-eval-s1", "lancet_eval_s1"),
        store=S1_STORE,
    )

    uploads = _uploads(httpx_mock)
    assert len(uploads) == 2
    for body in uploads:
        assert _form_field(body, "chunk_strategy") == "structure-merge"
        assert _form_field(body, "chunk_size") == "256"
        assert _form_field(body, "chunk_overlap") == "25"
        assert _form_field(body, "doc_title") is not None
        assert b'name="file"' in body
    assert get_document_map_path("multihop_rag_s1_dev", S1_STORE).is_file()


def test_s1_seed_without_the_stores_entry_is_refused_before_any_upload(
    httpx_mock: HTTPXMock, s1_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    """#67: a corpus with no [stores.merged] entry cannot seed the S1 store, so it
    never falls back to the gateway's default chunking."""
    from lancet_eval.config import S1_STORE

    _write_subset(tmp_path, [_V1_ROW])

    with pytest.raises(SeedError, match=r"\[stores\.merged\]"):
        seed_corpus(
            "multihop_rag",
            settings=_s1_settings("./data/lancedb-eval-s1", "lancet_eval_s1"),
            store=S1_STORE,
        )

    assert httpx_mock.get_requests() == []
    assert not get_document_map_path("multihop_rag", S1_STORE).exists()


def test_s1_reseed_without_the_stores_entry_deletes_nothing(
    httpx_mock: HTTPXMock, s1_repo: tuple[Path, Path]
) -> None:
    """#67: reseed checks the corpus's chunking before it drops the schema or the
    store, so a corpus with no [stores.merged] entry never wipes a built S1 store."""
    from lancet_eval.config import S1_STORE

    v1_canary, s1_canary = s1_repo
    with pytest.raises(SeedError, match=r"\[stores\.merged\]"):
        reseed_corpus(
            "multihop_rag",
            confirmation=True,
            settings=_s1_settings("./data/lancedb-eval-s1", "lancet_eval_s1"),
            store=S1_STORE,
        )
    assert v1_canary.exists()
    assert s1_canary.exists()
    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize(
    ("store", "schema"),
    [("eval-full", "lancet_eval_full"), ("eval-2wiki", "lancet_eval_2wiki")],
)
def test_the_149_stores_have_an_atlas_env_and_the_eval_schema_renamed(
    store: str, schema: str
) -> None:
    """#149: each hybrid-only store has its Atlas env, its schema file is
    schema.eval.hcl renamed, and its overlay builds no graph."""
    import re
    import tomllib

    from lancet_eval.config import get_eval_store, repo_root

    assert get_eval_store(store).pg_schema == schema
    gateway = repo_root() / "gateway"
    atlas = (gateway / "atlas.hcl").read_text(encoding="utf-8")
    env_block = re.search(rf'env "{store}" \{{(.*?)\n\}}', atlas, re.S)
    assert env_block is not None
    var = store.replace("-", "_") + "_db_url"
    assert f'src = "file://db/schema.{store}.hcl"' in env_block.group(1)
    assert f"url = var.{var}" in env_block.group(1)
    assert re.search(rf'variable "{var}" \{{[^}}]*search_path={schema}"', atlas)

    v1 = (gateway / "db" / "schema.eval.hcl").read_text(encoding="utf-8")
    own = (gateway / "db" / f"schema.{store}.hcl").read_text(encoding="utf-8")
    renamed = re.sub(r"\blancet_eval\b", schema, v1)
    assert own.splitlines()[0].startswith("// schema.eval.hcl with the schema renamed")
    assert own.splitlines()[1:] == renamed.splitlines()[1:]

    overlay = repo_root() / "config" / f"config.{store}.toml"
    graph = tomllib.loads(overlay.read_text(encoding="utf-8"))["engine"]["graph"]
    assert graph == {"ingest_extraction": False}
