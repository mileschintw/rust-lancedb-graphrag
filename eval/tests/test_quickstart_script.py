"""Tests for eval/scripts/quickstart.py and the D-221 bundled sample.

The script is the cross-shell ingest and query helper behind the README quickstart
(06.4 D-68, D-220, D-221). Everything here runs offline against ``httpx_mock``:
no gateway, no engine and no API key.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
import unicodedata
from datetime import datetime
from types import ModuleType
from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock

from lancet_eval.config import repo_root

SCRIPT_PATH = repo_root() / "eval" / "scripts" / "quickstart.py"
SAMPLE_DIR = repo_root() / "eval" / "corpora" / "quickstart"
GATEWAY = "http://testserver"
TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-[0-9a-f]{16}-01$")
API_KEY_SENTINEL = "sk-or-test-sentinel-do-not-print"


@pytest.fixture
def qs() -> ModuleType:
    """Loads the script by path, the way the other eval/scripts tests do."""
    spec = importlib.util.spec_from_file_location("quickstart_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["quickstart_script"] = module
    spec.loader.exec_module(module)
    return module


def _manifest() -> list[dict[str, str]]:
    return json.loads((SAMPLE_DIR / "documents.json").read_text(encoding="utf-8"))


def _sse(
    *,
    answer: str = "Alder Optics built it, and it is based in Port Marlow.",
    notices: list[tuple[str, int]] | None = None,
    levers: list[str] | None = None,
    degraded: bool = False,
    graph_path_found: bool | None = None,
) -> str:
    notice_rows = [
        {"code": name, "message": name.lower(), "severity": 1, "typed_code": code}
        for name, code in (notices or [])
    ]
    final = {
        "answer": answer,
        "citations": [],
        "session_id": "sess-1",
        "answer_basis": 1,
        "structured_citations": [],
        "notices": notice_rows,
        "snapshot": {
            "index_generation": "gen-1",
            "retrieved_chunks": [],
            "levers": levers if levers is not None else ["rerank"],
        },
    }
    metadata: dict[str, Any] = {"degraded_mode": degraded}
    if graph_path_found is not None:
        metadata["graph_path_found"] = graph_path_found
    completed = {
        "success": True,
        "total_duration_ms": 90,
        "metadata": metadata,
    }
    return (
        'event: node_started\ndata: {"node_name":"RetrieveHybrid"}\n\n'
        "event: node_completed\n"
        'data: {"node_name":"RetrieveHybrid","duration_ms":12.5}\n\n'
        f"event: final_answer\ndata: {json.dumps(final)}\n\n"
        f"event: workflow_completed\ndata: {json.dumps(completed)}\n\n"
    )


def _add_stream(httpx_mock: HTTPXMock, text: str | None = None) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{GATEWAY}/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=text if text is not None else _sse(),
    )


def _run_query_cli(
    qs: ModuleType,
    capsys: pytest.CaptureFixture[str],
    *extra: str,
    text: str = "Who directs Harbor Light Observatory?",
) -> tuple[int, dict[str, Any], str]:
    code = qs.main(["--gateway", GATEWAY, "query", text, *extra])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def _query_body(httpx_mock: HTTPXMock) -> dict[str, Any]:
    posts = [r for r in httpx_mock.get_requests() if r.url.path == "/rag/query"]
    assert len(posts) == 1
    return json.loads(posts[0].content)


def _doc_id(filename: str) -> str:
    return f"id-{filename}"


def _add_document_posts(httpx_mock: HTTPXMock, status: str = "queued") -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        match = re.search(rb'filename="([^"]+)"', request.content)
        assert match is not None, "the multipart body carries no file part"
        filename = match.group(1).decode("utf-8")
        return httpx.Response(202, json={"id": _doc_id(filename), "status": status})

    httpx_mock.add_callback(
        respond, method="POST", url=f"{GATEWAY}/documents", is_reusable=True
    )


def _add_document_polls(
    httpx_mock: HTTPXMock, status: str, error_message: str = ""
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        doc_id = request.url.path.rsplit("/", 1)[-1]
        body: dict[str, Any] = {"id": doc_id, "status": status}
        if error_message:
            body["error_message"] = error_message
        return httpx.Response(200, json=body)

    httpx_mock.add_callback(
        respond,
        method="GET",
        url=re.compile(rf"{GATEWAY}/documents/.+"),
        is_reusable=True,
    )


def _stdout_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


# --- the bundled sample (D-221) -------------------------------------------------


def test_d221_manifest_entries_pass_the_gateway_metadata_limits() -> None:
    manifest = _manifest()
    assert len(manifest) == 5
    for entry in manifest:
        assert set(entry) == {"file", "doc_title", "source", "published_date"}
        assert (SAMPLE_DIR / entry["file"]).is_file()
        # Mirrors gateway validMetaText: at most 512 / 256 runes, no control character.
        assert 0 < len(entry["doc_title"]) <= 512
        assert 0 < len(entry["source"]) <= 256
        for value in (entry["doc_title"], entry["source"]):
            assert not any(unicodedata.category(c) == "Cc" for c in value)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["published_date"])
        datetime.strptime(entry["published_date"], "%Y-%m-%d")


def test_d221_sample_documents_have_a_title_line_and_a_bounded_length() -> None:
    for entry in _manifest():
        text = (SAMPLE_DIR / entry["file"]).read_text(encoding="utf-8")
        assert text.startswith("# ")
        assert 70 <= len(text.split()) <= 200, entry["file"]


def test_d221_example_question_names_two_entities_the_sample_grounds() -> None:
    """The qs-001 canary names Harbor Light Observatory and Marisol Vega (the graph needs
    two named entities to find a path), and the sample grounds every clause of it.

    The Alder Optics profile alone names the builder and its base; the overview is the only
    document that says Marisol Vega directs the observatory. Each bridging entity is also
    repeated verbatim in both documents it links.
    """
    canary = (SAMPLE_DIR / "canary.arms.jsonl").read_text(encoding="utf-8").splitlines()
    question = json.loads(canary[0])["question"]
    assert "Harbor Light Observatory" in question and "Marisol Vega" in question
    read = {
        e["file"]: (SAMPLE_DIR / e["file"]).read_text(encoding="utf-8")
        for e in _manifest()
    }
    overview = read["harbor-light-overview.md"]
    install = read["kestrel-spectrograph-install.md"]
    profile = read["alder-optics-profile.md"]
    assert "Alder Optics built the Kestrel spectrograph for Harbor Light Observatory" in profile
    assert [f for f, text in read.items() if "Marisol Vega" in text] == [
        "harbor-light-overview.md"
    ]
    assert "Marisol Vega directs Harbor Light Observatory" in overview
    assert "Harbor Light Observatory" in install and "Kestrel spectrograph" in install
    assert "Kestrel spectrograph" in overview
    assert "Alder Optics built the Kestrel spectrograph" in install
    assert "Alder Optics is based in Port Marlow" in profile


def test_d221_canary_manifest_ids_cannot_collide_with_multihop_ids() -> None:
    lines = (SAMPLE_DIR / "canary.arms.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    assert [r["question_id"] for r in rows] == ["qs-001", "qs-002", "qs-003"]
    for row in rows:
        assert row["min_retrieved_chunks"] == 1
        assert row["question"].endswith("?")
    assert rows[0]["question"] == (
        "Which company built the spectrograph at Harbor Light Observatory, "
        "which Marisol Vega directs, and where is that company based?"
    )


def test_d221_attribution_names_the_sample_as_project_authored_mit() -> None:
    text = (repo_root() / "eval" / "corpora" / "ATTRIBUTION.md").read_text(
        encoding="utf-8"
    )
    assert "quickstart" in text.lower()
    section = text[text.lower().index("quickstart") :]
    assert "project-authored" in section
    assert "MIT" in section


def test_d221_env_example_carries_an_empty_key_and_no_secret() -> None:
    lines = (repo_root() / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "OPENROUTER_API_KEY=" in lines
    keys = [ln.split("=", 1)[0] for ln in lines if ln and not ln.startswith("#")]
    assert keys == [
        "OPENROUTER_API_KEY",
        "LANCET_GATEWAY__DATABASE_URL",
        "LANCET_EVAL__GATEWAY_URL",
    ]
    # An unquoted ampersand would background the assignment when bash sources the file.
    assert not any("&" in ln for ln in lines if not ln.startswith("#"))


# --- argument handling ----------------------------------------------------------


def test_d221_gateway_defaults_to_the_env_value_then_loopback(
    qs: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LANCET_EVAL__GATEWAY_URL", raising=False)
    assert qs.build_parser().parse_args(["query", "Q"]).gateway == (
        "http://127.0.0.1:8080"
    )
    monkeypatch.setenv("LANCET_EVAL__GATEWAY_URL", "http://127.0.0.1:9999")
    assert qs.build_parser().parse_args(["query", "Q"]).gateway == (
        "http://127.0.0.1:9999"
    )
    args = qs.build_parser().parse_args(["--gateway", "http://x:1", "ingest"])
    assert args.gateway == "http://x:1"
    assert args.timeout_s == 420


# --- ingest ---------------------------------------------------------------------


def test_d221_ingest_posts_every_document_with_metadata_and_polls(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _add_document_posts(httpx_mock)
    _add_document_polls(httpx_mock, "completed")

    code = qs.main(["--gateway", GATEWAY, "ingest"])

    assert code == 0
    lines = _stdout_lines(capsys)
    assert [ln["file"] for ln in lines] == [e["file"] for e in _manifest()]
    assert all(ln["status"] == "completed" for ln in lines)
    assert [ln["document_id"] for ln in lines] == [
        _doc_id(e["file"]) for e in _manifest()
    ]
    posts = [r for r in httpx_mock.get_requests() if r.method == "POST"]
    assert len(posts) == 5
    for post, entry in zip(posts, _manifest(), strict=True):
        body = post.content
        assert post.headers["content-type"].startswith("multipart/form-data")
        assert f'name="file"; filename="{entry["file"]}"'.encode() in body
        for field in ("doc_title", "source", "published_date"):
            part = f'name="{field}"\r\n\r\n{entry[field]}\r\n'.encode()
            assert part in body, field
    polled = {r.url.path for r in httpx_mock.get_requests() if r.method == "GET"}
    assert polled == {f"/documents/{_doc_id(e['file'])}" for e in _manifest()}


def test_d221_ingest_reports_a_failed_document_and_exits_nonzero(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _add_document_posts(httpx_mock)
    _add_document_polls(httpx_mock, "failed", error_message="embedding failed")

    code = qs.main(["--gateway", GATEWAY, "ingest"])

    assert code == 1
    lines = _stdout_lines(capsys)
    assert len(lines) == 5
    assert all(ln["status"] == "failed" for ln in lines)
    assert all(ln["error_message"] == "embedding failed" for ln in lines)


def test_d221_ingest_rejected_post_is_reported_and_exits_nonzero(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{GATEWAY}/documents",
        status_code=400,
        text="invalid published_date",
        is_reusable=True,
    )

    code = qs.main(["--gateway", GATEWAY, "ingest"])

    assert code == 1
    lines = _stdout_lines(capsys)
    assert len(lines) == 5
    assert all(ln["status"] == "post_failed" for ln in lines)
    assert all(ln["document_id"] == "" for ln in lines)
    assert all(ln["http_status"] == 400 for ln in lines)


def test_d221_ingest_deadline_exits_nonzero_with_pending(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _add_document_posts(httpx_mock)
    _add_document_polls(httpx_mock, "processing")

    started = time.monotonic()
    code = qs.main(["--gateway", GATEWAY, "ingest", "--timeout-s", "1"])
    elapsed = time.monotonic() - started

    assert code == 1
    assert elapsed < 10
    lines = _stdout_lines(capsys)
    assert len(lines) == 5
    for line, entry in zip(lines, _manifest(), strict=True):
        assert line["file"] == entry["file"]
        assert line["document_id"] == _doc_id(entry["file"])
        assert line["status"] == "pending"
        assert line["last_status"] == "processing"


def test_d221_ingest_deadline_also_bounds_the_posts(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """An expired budget before the first post sends nothing and lists every file."""
    code = qs.main(["--gateway", GATEWAY, "ingest", "--timeout-s", "0"])

    assert code == 1
    assert httpx_mock.get_requests() == []
    lines = _stdout_lines(capsys)
    assert [ln["file"] for ln in lines] == [e["file"] for e in _manifest()]
    assert all(ln["status"] == "pending" and ln["document_id"] == "" for ln in lines)


# --- query ----------------------------------------------------------------------


def test_d221_query_default_sends_no_graph_or_lever_keys(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _add_stream(httpx_mock)

    code, _, _ = _run_query_cli(qs, capsys)

    assert code == 0
    body = _query_body(httpx_mock)
    assert body["query"] == "Who directs Harbor Light Observatory?"
    assert "disable_graph_context" not in body
    assert "disable_default_levers" not in body


def test_d221_query_graph_flag_sends_disable_graph_context_false(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _add_stream(httpx_mock)

    code, _, _ = _run_query_cli(qs, capsys, "--graph")

    assert code == 0
    body = _query_body(httpx_mock)
    assert body["disable_graph_context"] is False
    assert "disable_default_levers" not in body


def test_d221_query_no_default_levers_flag_sends_true(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _add_stream(httpx_mock)

    code, _, _ = _run_query_cli(qs, capsys, "--no-default-levers")

    assert code == 0
    body = _query_body(httpx_mock)
    assert body["disable_default_levers"] is True
    assert "disable_graph_context" not in body


def test_d221_query_traceparent_header_matches_the_printed_trace_id(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _add_stream(httpx_mock)

    code, printed, _ = _run_query_cli(qs, capsys)

    assert code == 0
    request = httpx_mock.get_requests()[0]
    match = TRACEPARENT.match(request.headers["traceparent"])
    assert match is not None
    assert printed["trace_id"] == match.group(1)
    assert re.fullmatch(r"[0-9a-f]{32}", printed["trace_id"])


def test_d221_query_trace_ids_differ_between_calls(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _add_stream(httpx_mock)
    _add_stream(httpx_mock)

    _, first, _ = _run_query_cli(qs, capsys)
    _, second, _ = _run_query_cli(qs, capsys)

    assert first["trace_id"] != second["trace_id"]


def test_d221_query_prints_notice_codes_as_integers_and_the_lever_echo(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _add_stream(
        httpx_mock,
        _sse(
            notices=[
                ("DEFAULT_LEVER_UNAVAILABLE", 24),
                ("GRAPH_DISABLED_BY_CONFIG", 25),
            ],
            levers=["rerank"],
            degraded=True,
            graph_path_found=False,
        ),
    )

    code, printed, _ = _run_query_cli(qs, capsys)

    assert code == 0
    assert printed["notice_codes"] == [24, 25]
    assert all(isinstance(c, int) for c in printed["notice_codes"])
    assert printed["notices"] == [
        "DEFAULT_LEVER_UNAVAILABLE",
        "GRAPH_DISABLED_BY_CONFIG",
    ]
    assert printed["degraded_mode"] is True
    assert printed["levers"] == ["rerank"]
    assert printed["graph_path_found"] is False
    assert printed["node_timings"][0]["node_name"] == "RetrieveHybrid"
    assert printed["node_timings"][0]["duration_ms"] == 12.5
    assert printed["answer"].startswith("Alder Optics")
    for key in ("trace_id", "degraded_mode", "notice_codes", "notices", "levers"):
        assert key in printed


def test_d221_query_without_notices_or_graph_metadata_prints_empty_values(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _add_stream(httpx_mock, _sse(levers=["rerank", "evidence_metadata"]))

    code, printed, _ = _run_query_cli(qs, capsys)

    assert code == 0
    assert printed["notice_codes"] == []
    assert printed["notices"] == []
    assert printed["degraded_mode"] is False
    assert printed["graph_path_found"] is None
    assert printed["levers"] == ["rerank", "evidence_metadata"]


def test_d221_query_truncates_the_answer_to_300_characters(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    _add_stream(httpx_mock, _sse(answer="x" * 900))

    code, printed, _ = _run_query_cli(qs, capsys)

    assert code == 0
    assert len(printed["answer"]) == 300


def test_d221_query_never_prints_an_environment_value(
    qs: ModuleType,
    httpx_mock: HTTPXMock,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", API_KEY_SENTINEL)
    monkeypatch.setenv("LANCET_GATEWAY__DATABASE_URL", "postgres://u:pw-sentinel@h/d")
    _add_stream(httpx_mock)
    _add_document_posts(httpx_mock)
    _add_document_polls(httpx_mock, "completed")

    qs.main(["--gateway", GATEWAY, "query", "Q"])
    qs.main(["--gateway", GATEWAY, "ingest"])

    captured = capsys.readouterr()
    assert API_KEY_SENTINEL not in captured.out + captured.err
    assert "pw-sentinel" not in captured.out + captured.err
    for request in httpx_mock.get_requests():
        assert API_KEY_SENTINEL not in str(request.headers)


def test_d221_query_pre_stream_error_prints_json_error_and_exits_nonzero(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    httpx_mock.add_response(
        method="POST", url=f"{GATEWAY}/rag/query", status_code=503, text="engine down"
    )

    code = qs.main(["--gateway", GATEWAY, "query", "Q"])

    assert code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["error"] == "PreStreamError"
    assert "503" in printed["message"]
    assert re.fullmatch(r"[0-9a-f]{32}", printed["trace_id"])


def test_d221_query_connection_failure_prints_json_error_and_exits_nonzero(
    qs: ModuleType, httpx_mock: HTTPXMock, capsys: pytest.CaptureFixture[str]
) -> None:
    httpx_mock.add_exception(
        httpx.ConnectError("refused"), method="POST", url=f"{GATEWAY}/rag/query"
    )

    code = qs.main(["--gateway", GATEWAY, "query", "Q"])

    assert code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["error"] == "ConnectError"

