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
    settings = seen["settings"]
    assert isinstance(settings, EvalSettings)
    assert settings.lancedb_path == S1_STORE.lancedb_path


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
