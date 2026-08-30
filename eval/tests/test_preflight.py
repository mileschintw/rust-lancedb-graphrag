"""Tests for preflight checks and store isolation verification."""

from pathlib import Path

import httpx
from pytest_httpx import HTTPXMock

from lancet_eval.config import EvalSettings
from lancet_eval.preflight import (
    check_corpus_generation,
    check_gateway_and_engine,
    check_model_differentiation,
    check_openrouter_api,
    check_store_isolation,
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
        "dots-studio/dots-3-note-preview:free", "openai/gpt-4o-mini"
    )
    assert res_diff.passed


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

