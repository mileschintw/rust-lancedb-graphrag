"""Tests for preflight checks and store isolation verification."""

import json
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from lancet_eval.config import EvalSettings, repo_root
from lancet_eval.preflight import (
    PreflightCheckResult,
    check_corpus_generation,
    check_gateway_and_engine,
    check_index_identity,
    check_model_differentiation,
    check_openrouter_api,
    check_store_isolation,
    read_effective_workflow_config,
    run_preflight_checks,
)
from lancet_eval.seed import DocumentMap, DocumentMapEntry, save_document_map_atomic


def test_check_store_isolation_collision(tmp_path: Path) -> None:
    # Colliding LanceDB
    settings_lance_collide = EvalSettings(
        lancedb_path=str(tmp_path / "data" / "lancedb"),
        dev_lancedb_path=str(tmp_path / "data" / "lancedb-eval"),
        database_url="postgres://localhost/lancet?search_path=lancet_eval",
        dev_database_url="postgres://localhost/lancet?search_path=public",
    )
    # Mutate to bypass EvalSettings __init__ validation
    settings_lance_collide.dev_lancedb_path = settings_lance_collide.lancedb_path
    res_lance = check_store_isolation(settings_lance_collide)
    assert not res_lance.passed
    assert "collides with dev path" in res_lance.message

    # Colliding Postgres schema
    settings_pg_collide = EvalSettings(
        lancedb_path=str(tmp_path / "data" / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "data" / "lancedb"),
        database_url="postgres://localhost/lancet?search_path=lancet_eval",
        dev_database_url="postgres://localhost/lancet?search_path=public",
    )
    settings_pg_collide.dev_database_url = settings_pg_collide.database_url
    res_pg = check_store_isolation(settings_pg_collide)
    assert not res_pg.passed
    assert "collides with dev schema" in res_pg.message


def test_check_gateway_and_engine(httpx_mock: HTTPXMock) -> None:
    # 1. Happy path: HTTP 200
    httpx_mock.add_response(
        url="http://testserver:8080/health",
        status_code=200,
        json={"status": "ok", "engine": {"status": "ok"}},
    )
    with httpx.Client(base_url="http://testserver:8080") as client:
        gw_ok, eng_ok = check_gateway_and_engine(client)
    assert gw_ok.passed
    assert eng_ok.passed

    # 2. Degraded path: Gateway 503 with Engine Error
    httpx_mock.add_response(
        url="http://testserver:8080/health",
        status_code=503,
        json={
            "status": "unavailable",
            "engine": {"error": "connection refused [::1]:50051"},
        },
    )
    with httpx.Client(base_url="http://testserver:8080") as client:
        gw_res, eng_res = check_gateway_and_engine(client)
    assert gw_res.passed
    assert not eng_res.passed
    assert "connection refused" in eng_res.message


def test_check_corpus_generation_match_and_mismatch(
    httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch
) -> None:
    corpus_dir = tmp_path / "eval" / "corpora" / "multihop_rag"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)

    # Seed document map with gen-001
    doc_map = DocumentMap(
        corpus="multihop_rag",
        seeded_at="2026-08-29T00:00:00Z",
        index_generation="gen-001",
        entries={
            "doc-1": DocumentMapEntry(
                corpus_id="art-1", document_id="doc-1", title="Title"
            )
        },
    )
    save_document_map_atomic(doc_map)

    # Response with matching gen-001
    httpx_mock.add_response(
        url="http://testserver:8080/rag/query",
        status_code=200,
        text=(
            "event: final_answer\n"
            'data: {"answer":"ok","snapshot":{"index_generation":"gen-001",'
            '"retrieved_chunks":[{"chunk_id":"c1","is_truncated":false}]}}\n\n'
        ),
    )
    with httpx.Client(base_url="http://testserver:8080") as client:
        res_match = check_corpus_generation(client, "multihop_rag")
    assert res_match.passed
    assert "matched" in res_match.message

    # Response with mismatched gen-002
    httpx_mock.add_response(
        url="http://testserver:8080/rag/query",
        status_code=200,
        text=(
            "event: final_answer\n"
            'data: {"answer":"ok","snapshot":{"index_generation":"gen-002",'
            '"retrieved_chunks":[]}}\n\n'
        ),
    )
    with httpx.Client(base_url="http://testserver:8080") as client:
        res_mismatch = check_corpus_generation(client, "multihop_rag")
    assert not res_mismatch.passed
    assert "mismatch" in res_mismatch.message

    # Response with truncated chunk
    httpx_mock.add_response(
        url="http://testserver:8080/rag/query",
        status_code=200,
        text=(
            "event: final_answer\n"
            'data: {"answer":"ok","snapshot":{"index_generation":"gen-001",'
            '"retrieved_chunks":[{"chunk_id":"c1","is_truncated":true}]}}\n\n'
        ),
    )
    with httpx.Client(base_url="http://testserver:8080") as client:
        res_trunc = check_corpus_generation(client, "multihop_rag")
    assert not res_trunc.passed
    assert "truncated" in res_trunc.message

    # D-198 / D-207: the probe states its graph state and opts out of default levers.
    for request in httpx_mock.get_requests():
        body = json.loads(request.read().decode("utf-8"))
        assert body["disable_graph_context"] is False
        assert body["disable_default_levers"] is True


def test_check_openrouter_api_and_model_differentiation() -> None:
    # Deterministic does not need key
    res_det = check_openrouter_api(api_key=None, is_judged_requested=False)
    assert res_det.passed

    # Judged requires key
    res_judged_nokey = check_openrouter_api(api_key=None, is_judged_requested=True)
    assert not res_judged_nokey.passed

    res_judged_withkey = check_openrouter_api(
        api_key="sk-or-test-key", is_judged_requested=True
    )
    assert res_judged_withkey.passed

    # Model differentiation
    res_same = check_model_differentiation("openai/gpt-4o", "openai/gpt-4o")
    assert not res_same.passed
    assert "matches generation model" in res_same.message

    res_diff = check_model_differentiation(
        "deepseek/deepseek-v4-flash-0731", "openai/gpt-4o-mini"
    )
    assert res_diff.passed


def test_check_index_identity_passes_and_reports_failure_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """check_index_identity wraps compute_identity: passes when equal, fails with
    the symmetric differences in detail when it does not."""
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    doc_map = DocumentMap(
        corpus="multihop_rag",
        entries={
            "doc-1": DocumentMapEntry(corpus_id="a", document_id="doc-1", title="a"),
        },
    )
    save_document_map_atomic(doc_map)

    settings = EvalSettings(
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
    )

    # Passing case: the autouse identity fixture mirrors the map for equal sets.
    res_pass = check_index_identity(settings, "multihop_rag")
    assert res_pass.name == "index_identity"
    assert res_pass.passed is True

    # Failing case: force a mismatch by overriding the faked LanceDB listing.
    import lancet_eval.identity as identity_mod

    monkeypatch.setattr(
        identity_mod,
        "list_lancedb_document_ids",
        lambda path: {
            "documents": [],
            "nodes": [],
            "edges": [],
            "entity_edges": [],
            "staged_documents_v2_rows": 0,
        },
    )
    res_fail = check_index_identity(settings, "multihop_rag")
    assert res_fail.name == "index_identity"
    assert res_fail.passed is False
    assert res_fail.detail.get("failures")


def test_check_index_identity_never_raises_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check_index_identity converts any exception (missing map, store error) into
    passed=False rather than propagating it."""
    import lancet_eval.identity as identity_mod

    def boom(settings: EvalSettings, corpus_name: str) -> None:
        raise RuntimeError("store unreachable")

    monkeypatch.setattr(identity_mod, "compute_identity", boom)

    settings = EvalSettings(lancedb_path="./x-lancedb", dev_lancedb_path="./y-lancedb")
    res = check_index_identity(settings, "multihop_rag")
    assert res.passed is False
    assert "store unreachable" in res.message


def test_run_preflight_checks_index_identity_follows_store_isolation(
    httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-199: drive_environment runs first, then store_isolation, then index_identity."""
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    doc_map = DocumentMap(corpus="multihop_rag", entries={})
    save_document_map_atomic(doc_map)

    def error_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    httpx_mock.add_callback(error_handler, is_reusable=True)

    settings = EvalSettings(
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
    )

    results = run_preflight_checks(corpus_name="multihop_rag", settings=settings)
    assert results[0].name == "drive_environment"
    assert results[1].name == "store_isolation"
    assert results[2].name == "index_identity"


def test_effective_workflow_config_same_under_eval_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With LANCET_ENV=eval, read_effective_workflow_config returns the same eight
    workflow values as for the base config (D-66): the restored lancedb_path-only
    overlay carries no [engine.workflow] table, so nothing overrides the base."""
    for env_var in (
        "LANCET_ENGINE__WORKFLOW__REFORMULATE_TIMEOUT_MS",
        "LANCET_ENGINE__WORKFLOW__QUERY_EMBEDDING_TIMEOUT_MS",
        "LANCET_ENGINE__WORKFLOW__RETRIEVE_TIMEOUT_MS",
        "LANCET_ENGINE__WORKFLOW__RERANK_TIMEOUT_MS",
        "LANCET_ENGINE__WORKFLOW__GRAPH_OPERATION_TIMEOUT_MS",
        "LANCET_ENGINE__WORKFLOW__GRAPH_NODE_TIMEOUT_MS",
        "LANCET_ENGINE__WORKFLOW__PROMPT_TIMEOUT_MS",
        "LANCET_ENGINE__WORKFLOW__GENERATION_NODE_TIMEOUT_MS",
    ):
        monkeypatch.delenv(env_var, raising=False)

    base_config = repo_root() / "config" / "config.toml"

    monkeypatch.delenv("LANCET_ENV", raising=False)
    base_values = read_effective_workflow_config(base_config)

    monkeypatch.setenv("LANCET_ENV", "eval")
    eval_values = read_effective_workflow_config(base_config)

    assert len(base_values) == 8
    assert base_values["rerank_timeout_ms"] > 0
    assert eval_values == base_values


def test_effective_workflow_config_mirrors_the_rerank_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine reads LANCET_ENGINE__WORKFLOW__RERANK_TIMEOUT_MS (config.rs), so the
    harness's effective view of the budgets must follow it: the run of record reports
    the rerank timeout the engine actually ran with (06.3.6-09 gap, closed in 06.3.6-18)."""
    base_config = repo_root() / "config" / "config.toml"
    monkeypatch.delenv("LANCET_ENV", raising=False)
    monkeypatch.delenv("LANCET_ENGINE__WORKFLOW__RERANK_TIMEOUT_MS", raising=False)
    from_file = read_effective_workflow_config(base_config)["rerank_timeout_ms"]

    monkeypatch.setenv("LANCET_ENGINE__WORKFLOW__RERANK_TIMEOUT_MS", str(from_file + 1))
    overridden = read_effective_workflow_config(base_config)["rerank_timeout_ms"]
    assert overridden == from_file + 1

    monkeypatch.setenv("LANCET_ENGINE__WORKFLOW__RERANK_TIMEOUT_MS", "not-a-number")
    assert read_effective_workflow_config(base_config)["rerank_timeout_ms"] == from_file


def test_gateway_failure_message_names_service_and_remedy(
    httpx_mock: HTTPXMock,
) -> None:
    """Proves preflight failure when gateway is down carries remedy string."""

    def error_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    httpx_mock.add_callback(error_handler)

    with httpx.Client(base_url="http://testserver:8080") as client:
        gw_check, eng_check = check_gateway_and_engine(client)

    assert not gw_check.passed
    assert "Gateway" in gw_check.message
    assert "LANCET_ENV=eval" in gw_check.message
    assert "docker compose up -d db" in gw_check.message

    assert not eng_check.passed
    assert "gateway is down" in eng_check.message.lower()
    assert "engine failed" not in eng_check.message.lower()


# --- S1 store isolation (D-251) ------------------------------------------------------


def _store_settings(lancedb_path: str, schema: str) -> EvalSettings:
    return EvalSettings(
        lancedb_path=lancedb_path,
        dev_lancedb_path="./data/lancedb",
        database_url=f"postgres://localhost/lancet?search_path={schema}",
        dev_database_url="postgres://localhost/lancet?search_path=public",
    )


@pytest.fixture
def s1_overlay_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp repo root and cwd whose S1 overlay names the S1 path."""
    monkeypatch.setattr("lancet_eval.config.repo_root", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.eval-s1.toml").write_text(
        '[engine]\nlancedb_path = "./data/lancedb-eval-s1"\n', encoding="utf-8"
    )
    return tmp_path


def test_store_isolation_reports_the_s1_store_and_schema_it_checked(
    s1_overlay_root: Path,
) -> None:
    from lancet_eval.config import S1_STORE

    res = check_store_isolation(
        _store_settings("./data/lancedb-eval-s1", "lancet_eval_s1"), S1_STORE
    )

    assert res.passed, res.message
    assert "eval-s1" in res.message
    assert "./data/lancedb-eval-s1" in res.message
    assert "lancet_eval_s1" in res.message
    assert res.detail["store"] == "eval-s1"
    assert res.detail["eval_schema"] == "lancet_eval_s1"
    assert res.detail["overlay_lancedb"] == "./data/lancedb-eval-s1"


@pytest.mark.parametrize(
    ("lancedb_path", "schema", "refused"),
    [
        ("./data/lancedb-eval", "lancet_eval_s1", "data/lancedb-eval"),
        ("./data/lancedb-eval-s1", "lancet_eval", "lancet_eval"),
    ],
)
def test_store_isolation_with_s1_selected_refuses_the_v1_store(
    s1_overlay_root: Path, lancedb_path: str, schema: str, refused: str
) -> None:
    from lancet_eval.config import S1_STORE

    res = check_store_isolation(_store_settings(lancedb_path, schema), S1_STORE)

    assert not res.passed
    assert "v1.0" in res.message
    assert refused in res.message.replace("\\", "/")


def test_store_isolation_fails_when_overlay_and_harness_paths_differ(
    s1_overlay_root: Path,
) -> None:
    """The engine reads its store from the overlay, the harness from its settings;
    preflight fails when the two name different paths."""
    from lancet_eval.config import S1_STORE

    (s1_overlay_root / "config" / "config.eval-s1.toml").write_text(
        '[engine]\nlancedb_path = "./data/lancedb-eval-s1-old"\n', encoding="utf-8"
    )
    res = check_store_isolation(
        _store_settings("./data/lancedb-eval-s1", "lancet_eval_s1"), S1_STORE
    )

    assert not res.passed
    assert "overlay" in res.message
    assert "./data/lancedb-eval-s1-old" in res.message


def test_store_isolation_fails_when_the_s1_overlay_is_missing(
    s1_overlay_root: Path,
) -> None:
    from lancet_eval.config import S1_STORE

    (s1_overlay_root / "config" / "config.eval-s1.toml").unlink()
    res = check_store_isolation(
        _store_settings("./data/lancedb-eval-s1", "lancet_eval_s1"), S1_STORE
    )

    assert not res.passed
    assert "overlay" in res.message


def test_store_isolation_default_store_reports_eval_and_lancet_eval(
    tmp_path: Path,
) -> None:
    """v1.0 behaviour is unchanged (any isolated path passes); the result now names the
    store and schema it checked."""
    res = check_store_isolation(
        _store_settings(str(tmp_path / "lancedb-eval"), "lancet_eval")
    )

    assert res.passed, res.message
    assert "'eval'" in res.message
    assert "lancet_eval" in res.message
    assert res.detail["store"] == "eval"


def test_run_preflight_checks_passes_the_selected_store_to_store_isolation(
    httpx_mock: HTTPXMock,
    s1_overlay_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lancet_eval.config import S1_STORE

    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: s1_overlay_root)
    save_document_map_atomic(DocumentMap(corpus="multihop_rag", entries={}))

    def error_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    httpx_mock.add_callback(error_handler, is_reusable=True)

    results = run_preflight_checks(
        corpus_name="multihop_rag",
        settings=_store_settings("./data/lancedb-eval", "lancet_eval"),
        store=S1_STORE,
    )

    isolation = next(r for r in results if r.name == "store_isolation")
    assert not isolation.passed
    assert "v1.0" in isolation.message


def test_cli_preflight_store_option_selects_the_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner

    from lancet_eval import preflight as preflight_module
    from lancet_eval.cli import app
    from lancet_eval.config import S1_STORE

    seen: dict[str, object] = {}

    def fake_checks(**kwargs: object) -> list[PreflightCheckResult]:
        seen.update(kwargs)
        return [PreflightCheckResult(name="store_isolation", passed=True, message="ok")]

    monkeypatch.setattr(preflight_module, "run_preflight_checks", fake_checks)
    result = CliRunner().invoke(app, ["preflight", "--store", "eval-s1"])

    assert result.exit_code == 0, result.output
    assert seen["store"] is S1_STORE
    assert seen["corpus_name"] == "multihop_rag"


def test_cli_preflight_refuses_an_unknown_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner

    from lancet_eval import preflight as preflight_module
    from lancet_eval.cli import app

    monkeypatch.setattr(
        preflight_module,
        "run_preflight_checks",
        lambda **k: pytest.fail("an unknown store must not reach preflight"),
    )
    result = CliRunner().invoke(app, ["preflight", "--store", "eval-s2"])

    assert result.exit_code == 2
    assert "eval-s2" in result.output


def test_run_preflight_checks_without_settings_loads_the_selected_store(
    httpx_mock: HTTPXMock,
    s1_overlay_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no settings passed (the CLI path), preflight loads the S1 store's path and
    schema, so --store eval-s1 checks the S1 store even over v1.0 env values."""
    from lancet_eval.config import S1_STORE

    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: s1_overlay_root)
    monkeypatch.setenv("LANCET_EVAL__LANCEDB_PATH", "./data/lancedb-eval")
    save_document_map_atomic(DocumentMap(corpus="multihop_rag"), S1_STORE)

    def error_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    httpx_mock.add_callback(error_handler, is_reusable=True)

    results = run_preflight_checks(corpus_name="multihop_rag", store=S1_STORE)

    isolation = next(r for r in results if r.name == "store_isolation")
    assert isolation.passed, isolation.message
    assert isolation.detail["eval_lancedb"] == "./data/lancedb-eval-s1"
    assert isolation.detail["eval_schema"] == "lancet_eval_s1"


# --- Per-store document map readers (#18) --------------------------------------------

_DOC_V1 = "doc-v1"
_DOC_S1 = "doc-s1"


@pytest.fixture
def two_maps(s1_overlay_root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A v1.0 map holding doc-v1 and an S1 map holding doc-s1, in one temp repo."""
    from lancet_eval.config import S1_STORE, V1_STORE

    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: s1_overlay_root)
    for store, doc_id, generation in (
        (V1_STORE, _DOC_V1, "lance-v1"),
        (S1_STORE, _DOC_S1, "lance-s1"),
    ):
        doc_map = DocumentMap(
            corpus="multihop_rag",
            index_generation=generation,
            entries={
                doc_id: DocumentMapEntry(
                    corpus_id=doc_id, document_id=doc_id, title=f"Title {doc_id}"
                )
            },
        )
        save_document_map_atomic(doc_map, store)
    return s1_overlay_root


def _patch_stores(monkeypatch: pytest.MonkeyPatch, doc_id: str) -> None:
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids",
        lambda path: {
            "documents": [doc_id],
            "nodes": [doc_id],
            "edges": [],
            "entity_edges": [],
            "staged_documents_v2_rows": 0,
        },
    )
    monkeypatch.setattr(
        "lancet_eval.identity.list_pg_documents",
        lambda settings: {doc_id: "completed"},
    )


def test_store_for_settings_follows_the_lancedb_path(s1_overlay_root: Path) -> None:
    from lancet_eval.config import S1_STORE, V1_STORE, store_for_settings

    assert (
        store_for_settings(_store_settings("./data/lancedb-eval-s1", "lancet_eval_s1"))
        is S1_STORE
    )
    assert (
        store_for_settings(_store_settings("./data/lancedb-eval", "lancet_eval"))
        is V1_STORE
    )
    other = _store_settings(str(s1_overlay_root / "elsewhere"), "lancet_eval")
    assert store_for_settings(other) is V1_STORE


def test_index_identity_reads_the_map_of_the_store_in_use(
    two_maps: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#18: S1 settings check the S1 map, and the result names the map it checked;
    v1.0 settings still check document_map.json."""
    _patch_stores(monkeypatch, _DOC_S1)
    s1 = check_index_identity(
        _store_settings("./data/lancedb-eval-s1", "lancet_eval_s1"), "multihop_rag"
    )
    assert s1.passed, s1.message
    assert "document_map.eval-s1.json" in s1.message
    assert s1.detail["document_map"].endswith("document_map.eval-s1.json")

    _patch_stores(monkeypatch, _DOC_V1)
    v1 = check_index_identity(
        _store_settings("./data/lancedb-eval", "lancet_eval"), "multihop_rag"
    )
    assert v1.passed, v1.message
    assert "(document_map.json)" in v1.message


def test_corpus_generation_reads_the_selected_stores_map(
    two_maps: Path, httpx_mock: HTTPXMock
) -> None:
    """#18: the generation probe asks with the selected store's first title and
    compares with that map's generation."""
    from lancet_eval.config import S1_STORE

    httpx_mock.add_response(
        url="http://testserver:8080/rag/query",
        status_code=200,
        text=(
            'data: {"snapshot": {"index_generation": "lance-s1", "excerpts": []}}\n\n'
        ),
    )
    with httpx.Client(base_url="http://testserver:8080") as client:
        check_corpus_generation(client, "multihop_rag", S1_STORE)

    request = httpx_mock.get_requests()[0]
    assert json.loads(request.content)["query"] == f"Title {_DOC_S1}"


def test_corpus_generation_without_the_stores_map_fails(
    s1_overlay_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the v1.0 map exists: the S1 generation check fails on the missing S1 map
    instead of reading v1.0's."""
    from lancet_eval.config import S1_STORE

    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: s1_overlay_root)
    save_document_map_atomic(DocumentMap(corpus="multihop_rag"))
    with httpx.Client(base_url="http://testserver:8080") as client:
        res = check_corpus_generation(client, "multihop_rag", S1_STORE)
    assert not res.passed
    assert "document_map.eval-s1.json" in res.message.replace("\\", "/")


def test_cli_identity_check_store_option_checks_the_s1_map(
    two_maps: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from lancet_eval.cli import app

    _patch_stores(monkeypatch, _DOC_S1)
    result = CliRunner().invoke(app, ["identity", "check", "--store", "eval-s1"])
    assert result.exit_code == 0, result.output

    result = CliRunner().invoke(app, ["identity", "check"])
    assert result.exit_code == 1, result.output


def test_diagnostic_readers_take_the_selected_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#18: the diagnostic table reads the map of the store it is given; v1.0 by
    default."""
    from lancet_eval import diagnostic
    from lancet_eval.config import S1_STORE, V1_STORE

    seen: list[object] = []

    def fake_load(corpus_name: str, store: object = V1_STORE) -> DocumentMap:
        seen.append(store)
        raise RuntimeError("stop after the map lookup")

    monkeypatch.setattr(diagnostic, "load_sample_questions", lambda corpus: [])
    monkeypatch.setattr(diagnostic, "load_document_map", fake_load)
    for kwargs in ({}, {"store": S1_STORE}):
        with pytest.raises(RuntimeError, match="stop after"):
            diagnostic.build_rows("multihop_rag", None, "gold.jsonl", **kwargs)
    assert seen == [V1_STORE, S1_STORE]


def test_default_store_refuses_settings_on_the_s1_path(s1_overlay_root: Path) -> None:
    """#18: the v1.0 store with settings on the S1 LanceDB path fails closed, so one
    preflight never checks the S1 map for identity and the v1.0 map for generation."""
    res = check_store_isolation(
        _store_settings("./data/lancedb-eval-s1", "lancet_eval_s1")
    )

    assert not res.passed
    assert "--store eval-s1" in res.message


# --- S1 store-prefixed arms: the stack's store is the arms' store (D-251) ------------

_SMALL = ("small/hybrid+rerank+metadata", "small/hybrid+graph+rerank+metadata")
_MERGED = ("merged/hybrid+rerank+metadata", "merged/hybrid+graph+rerank+metadata")


def _s1_settings() -> EvalSettings:
    return _store_settings("./data/lancedb-eval-s1", "lancet_eval_s1")


def _v1_settings() -> EvalSettings:
    return _store_settings("./data/lancedb-eval", "lancet_eval")


@pytest.mark.parametrize(
    ("arms", "settings"),
    [(_MERGED, _s1_settings), (_SMALL, _v1_settings)],
    ids=["merged-on-s1", "small-on-v1"],
)
def test_arm_store_passes_when_the_stack_serves_the_arms_store(
    s1_overlay_root: Path, arms: tuple[str, ...], settings
) -> None:  # type: ignore[no-untyped-def]
    from lancet_eval.preflight import check_arm_store

    res = check_arm_store(settings(), arms, {})
    assert res.name == "arm_store"
    assert res.passed, res.message


@pytest.mark.parametrize(
    ("arms", "settings", "environ", "named"),
    [
        (_MERGED, _v1_settings, {}, "eval-s1"),
        (_SMALL, _s1_settings, {}, "eval-s1"),
        (_MERGED, _s1_settings, {"LANCET_ENV": "eval"}, "LANCET_ENV=eval"),
        (_SMALL, _v1_settings, {"LANCET_ENV": "eval-s1"}, "LANCET_ENV=eval-s1"),
    ],
    ids=["merged-on-v1", "small-on-s1", "merged-under-v1-env", "small-under-s1-env"],
)
def test_arm_store_fails_when_the_stack_serves_another_store(
    s1_overlay_root: Path, arms, settings, environ, named: str
) -> None:  # type: ignore[no-untyped-def]
    from lancet_eval.preflight import check_arm_store

    res = check_arm_store(settings(), arms, environ)
    assert not res.passed
    assert named in res.message


def test_arm_store_refuses_arms_from_two_stores(s1_overlay_root: Path) -> None:
    from lancet_eval.preflight import check_arm_store

    res = check_arm_store(_s1_settings(), (*_SMALL, *_MERGED), {})
    assert not res.passed
    assert "two stores" in res.message


def test_arm_store_passes_unprefixed_arms_unchanged(tmp_path: Path) -> None:
    from lancet_eval.preflight import check_arm_store

    res = check_arm_store(
        _store_settings(str(tmp_path / "x"), "lancet_eval"),
        ("hybrid", "hybrid+graph"),
        {"LANCET_ENV": "eval-s1"},
    )
    assert res.passed, res.message


def _s1_preflight(
    httpx_mock: HTTPXMock,
    s1_overlay_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings: EvalSettings,
):  # type: ignore[no-untyped-def]
    from lancet_eval.config import S1_STORE

    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: s1_overlay_root)
    monkeypatch.delenv("LANCET_ENV", raising=False)
    save_document_map_atomic(DocumentMap(corpus="multihop_rag"), S1_STORE)
    httpx_mock.add_exception(httpx.ConnectError("refused"), is_reusable=True)
    return run_preflight_checks(
        corpus_name="multihop_rag_s1_dev", settings=settings, store=S1_STORE
    )


def test_preflight_of_an_s1_store_checks_that_stores_arms(
    httpx_mock: HTTPXMock, s1_overlay_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = _s1_preflight(httpx_mock, s1_overlay_root, monkeypatch, _s1_settings())
    arm_store = next(r for r in results if r.name == "arm_store")
    assert arm_store.passed, arm_store.message
    assert arm_store.detail["arms"] == list(_MERGED)


def test_preflight_fails_when_the_stack_is_not_the_arms_store(
    httpx_mock: HTTPXMock, s1_overlay_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = _s1_preflight(httpx_mock, s1_overlay_root, monkeypatch, _v1_settings())
    arm_store = next(r for r in results if r.name == "arm_store")
    assert not arm_store.passed


def test_preflight_of_an_unprefixed_corpus_has_no_arm_store_check(
    httpx_mock: HTTPXMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    save_document_map_atomic(DocumentMap(corpus="multihop_rag", entries={}))
    httpx_mock.add_exception(httpx.ConnectError("refused"), is_reusable=True)
    results = run_preflight_checks(
        corpus_name="multihop_rag",
        settings=_store_settings(str(tmp_path / "lancedb-eval"), "lancet_eval"),
    )
    assert "arm_store" not in [r.name for r in results]


# --- Store chunking (#67) -------------------------------------------------------------


def _s1_chunking_settings() -> EvalSettings:
    return _store_settings("./data/lancedb-eval-s1", "lancet_eval_s1")


def _stub_psql(monkeypatch: pytest.MonkeyPatch, output: str) -> list[str]:
    """Answer the store's documents query with `output`; return the SQL it got."""
    seen: list[str] = []

    def fake_psql(settings: EvalSettings, sql: str, **kw: object) -> str:
        seen.append(sql)
        return output

    monkeypatch.setattr("lancet_eval.preflight.run_psql", fake_psql)
    return seen


def test_store_chunking_passes_when_every_document_used_the_declared_chunking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lancet_eval.config import S1_STORE
    from lancet_eval.corpus import load_corpus_config
    from lancet_eval.preflight import check_store_chunking

    seen = _stub_psql(monkeypatch, "structure-merge|256|25|346\n")

    res = check_store_chunking(
        _s1_chunking_settings(), load_corpus_config("multihop_rag_s1_dev"), S1_STORE
    )

    assert res.passed, res.message
    assert res.name == "store_chunking"
    assert '"lancet_eval_s1".documents' in seen[0]
    assert "structure-merge" in res.message


@pytest.mark.parametrize(
    "rows",
    [
        "structure-aware|500|50|346\n",
        "structure-merge|256|25|345\nstructure-aware|500|50|1\n",
        "structure-merge|500|50|346\n",
        "",
    ],
)
def test_store_chunking_fails_when_documents_used_another_chunking(
    monkeypatch: pytest.MonkeyPatch, rows: str
) -> None:
    """#67: a store built with the v1.0 chunker (or a mix, other sizes, or no
    documents at all) fails the S1 preflight."""
    from lancet_eval.config import S1_STORE
    from lancet_eval.corpus import load_corpus_config
    from lancet_eval.preflight import check_store_chunking

    _stub_psql(monkeypatch, rows)

    res = check_store_chunking(
        _s1_chunking_settings(), load_corpus_config("multihop_rag_s1_dev"), S1_STORE
    )

    assert not res.passed
    assert "structure-merge" in res.message


def test_store_chunking_fails_closed_without_the_corpus_stores_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lancet_eval.config import S1_STORE
    from lancet_eval.corpus import load_corpus_config
    from lancet_eval.preflight import check_store_chunking

    seen = _stub_psql(monkeypatch, "structure-merge|256|25|1\n")

    res = check_store_chunking(
        _s1_chunking_settings(), load_corpus_config("multihop_rag"), S1_STORE
    )

    assert not res.passed
    assert "[stores.merged]" in res.message
    assert seen == []


def test_store_chunking_never_raises_on_a_psql_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lancet_eval.config import S1_STORE
    from lancet_eval.corpus import load_corpus_config
    from lancet_eval.preflight import check_store_chunking
    from lancet_eval.seed import SeedError

    def failing_psql(settings: EvalSettings, sql: str, **kw: object) -> str:
        raise SeedError("psql command failed (exit 2): connection refused")

    monkeypatch.setattr("lancet_eval.preflight.run_psql", failing_psql)

    res = check_store_chunking(
        _s1_chunking_settings(), load_corpus_config("multihop_rag_s1_dev"), S1_STORE
    )

    assert not res.passed
    assert "connection refused" in res.message


@pytest.mark.parametrize("store_name", ["eval", "eval-s1"])
def test_run_preflight_checks_checks_chunking_only_off_the_v1_store(
    httpx_mock: HTTPXMock,
    s1_overlay_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    store_name: str,
) -> None:
    """#67: `preflight --store eval-s1` reports `store_chunking`; a v1.0 preflight
    runs exactly the checks it ran before."""
    from lancet_eval.config import get_eval_store

    store = get_eval_store(store_name)
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: s1_overlay_root)
    save_document_map_atomic(DocumentMap(corpus="multihop_rag"), store)
    _stub_psql(monkeypatch, "structure-aware|500|50|346\n")

    def error_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    httpx_mock.add_callback(error_handler, is_reusable=True)

    results = run_preflight_checks(
        corpus_name="multihop_rag_s1_dev",
        settings=_store_settings(store.lancedb_path, store.pg_schema),
        store=store,
    )

    chunking = [r for r in results if r.name == "store_chunking"]
    if store_name == "eval":
        assert chunking == []
    else:
        assert len(chunking) == 1
        assert not chunking[0].passed


def test_s1_preflight_passes_identity_and_chunking_on_a_correct_s1_store(
    httpx_mock: HTTPXMock,
    s1_overlay_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#67, #69: on an S1 store whose PostgreSQL rows, LanceDB rows and S1 map agree
    and whose documents used structure-merge 256/25, `preflight --corpus
    multihop_rag_s1_dev --store eval-s1` passes index_identity and store_chunking,
    reading only the S1 schema."""
    from lancet_eval.config import S1_STORE

    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: s1_overlay_root)
    save_document_map_atomic(
        DocumentMap(
            corpus="multihop_rag_s1_dev",
            entries={
                _DOC_S1: DocumentMapEntry(corpus_id="Article S1", document_id=_DOC_S1)
            },
        ),
        S1_STORE,
    )
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids",
        lambda path: {
            "documents": [_DOC_S1],
            "nodes": [_DOC_S1],
            "edges": [],
            "entity_edges": [],
            "staged_documents_v2_rows": 0,
        },
    )
    sql_seen: list[str] = []

    def fake_psql(settings: EvalSettings, sql: str, **kw: object) -> str:
        sql_seen.append(sql)
        if "chunk_strategy" in sql:
            return "structure-merge|256|25|1\n"
        return f"{_DOC_S1}|completed\n"

    # conftest fakes `list_pg_documents` outside test_identity.py; load a fresh copy
    # of the real one, so the S1 schema's SQL runs through `run_psql`.
    import importlib.util

    spec = importlib.util.find_spec("lancet_eval.identity")
    assert spec is not None and spec.loader is not None
    real_identity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real_identity)
    monkeypatch.setattr(real_identity, "run_psql", fake_psql)
    monkeypatch.setattr(
        "lancet_eval.identity.list_pg_documents", real_identity.list_pg_documents
    )
    monkeypatch.setattr("lancet_eval.preflight.run_psql", fake_psql)

    def error_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    httpx_mock.add_callback(error_handler, is_reusable=True)

    results = {
        r.name: r
        for r in run_preflight_checks(
            corpus_name="multihop_rag_s1_dev",
            settings=_s1_chunking_settings(),
            store=S1_STORE,
        )
    }

    assert results["store_isolation"].passed, results["store_isolation"].message
    assert results["index_identity"].passed, results["index_identity"].message
    assert results["store_chunking"].passed, results["store_chunking"].message
    assert len(sql_seen) == 2
    assert all("lancet_eval_s1" in sql for sql in sql_seen)
