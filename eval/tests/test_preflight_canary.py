"""Tests for preflight canary checks (manifest and live query floors)."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock

from lancet_eval.preflight import (
    check_canary_floors,
    check_canary_manifest,
    read_workflow_timeouts,
    run_preflight_checks,
)


def _make_sse_stream(events: list[tuple[str, dict[str, Any]]]) -> str:
    parts = []
    for ev_type, ev_data in events:
        parts.append(f"event: {ev_type}\ndata: {json.dumps(ev_data)}\n\n")
    return "".join(parts)


def test_canary_manifest_committed_file_passes() -> None:
    """Proves committed canary manifest passes validation against committed sample."""
    res = check_canary_manifest()
    assert res.passed
    assert "Canary manifest verified" in res.message
    assert res.detail.get("row_count") == 7
    assert res.detail.get("distinct_ids") == 6


def test_canary_manifest_missing_file_fails(tmp_path: Path) -> None:
    """Proves missing canary file fails loudly naming the expected path."""
    fake_path = tmp_path / "nonexistent.jsonl"
    res = check_canary_manifest(canary_path=fake_path)
    assert not res.passed
    assert "Canary manifest missing at expected path" in res.message
    assert str(fake_path) in res.message


def test_canary_manifest_drifted_question_fails(tmp_path: Path) -> None:
    """Proves canary row with modified text fails naming the question ID."""
    # Write 6 sample questions
    sample_rows = [
        {"question_id": f"q{i}", "query": f"Original query {i}?"}
        for i in range(1, 7)
    ]
    sample_p = tmp_path / "sample.jsonl"
    sample_p.write_text(
        "\n".join(json.dumps(r) for r in sample_rows) + "\n",
        encoding="utf-8",
    )

    # 7 canary rows, 6 distinct IDs (q1 has two rows), q1 drifted
    canary_p = tmp_path / "canary.jsonl"
    canary_rows = [
        {"question_id": "q1", "question": "Tampered query?", "graph_arm": "graph-on"},
        {"question_id": "q2", "question": "Original query 2?", "graph_arm": "graph-on"},
        {"question_id": "q3", "question": "Original query 3?", "graph_arm": "graph-on"},
        {"question_id": "q4", "question": "Original query 4?", "graph_arm": "graph-on"},
        {"question_id": "q5", "question": "Original query 5?", "graph_arm": "graph-on"},
        {"question_id": "q6", "question": "Original query 6?", "graph_arm": "graph-on"},
        {
            "question_id": "q1",
            "question": "Original query 1?",
            "graph_arm": "graph-off",
        },
    ]
    canary_p.write_text(
        "\n".join(json.dumps(r) for r in canary_rows) + "\n",
        encoding="utf-8",
    )

    res = check_canary_manifest(canary_path=canary_p, sample_path=sample_p)
    assert not res.passed
    assert "drifted" in res.message
    assert "q1" in res.message


def test_read_workflow_timeouts_live_and_no_secrets(tmp_path: Path) -> None:
    """Proves timeouts are read from [engine.workflow] and secrets are not leaked."""
    secret_key = "sk-openrouter-secret-key-12345"
    cfg = f"""
    [engine.providers]
    openrouter_api_key = "{secret_key}"

    [engine.workflow]
    reformulate_timeout_ms = 4000
    retrieve_timeout_ms = 8000
    graph_node_timeout_ms = 12000
    prompt_timeout_ms = 1500
    generation_node_timeout_ms = 50000
    """
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(cfg, encoding="utf-8")

    timeouts = read_workflow_timeouts(cfg_file)
    assert timeouts["RetrieveHybrid"] == 8000
    assert timeouts["ExtractGraphContext"] == 12000
    assert timeouts["GenerateAnswer"] == 50000

    # Ensure secret is nowhere in timeouts
    assert secret_key not in str(timeouts)


def test_read_workflow_timeouts_malformed_config_raises(tmp_path: Path) -> None:
    """Proves malformed config raises error rather than silently defaulting."""
    cfg_file = tmp_path / "broken.toml"
    cfg_file.write_text("[engine]\n# no workflow section\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing or invalid"):
        read_workflow_timeouts(cfg_file)


def _mock_canary_responses(
    httpx_mock: HTTPXMock,
    *,
    chunk_count: int = 2,
    graph_nodes: int = 3,
    durations: dict[str, float] | None = None,
    include_ablation_notice: bool = True,
) -> None:
    """Helper to mock SSE responses for all 7 canaries."""
    dur_map = durations or {
        "RetrieveHybrid": 100.0,
        "ExtractGraphContext": 200.0,
        "AssemblePrompt": 50.0,
        "GenerateAnswer": 300.0,
    }

    def sse_cb(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        is_graph_off = body.get("disable_graph_context", False)

        events: list[tuple[str, dict[str, Any]]] = []
        notices = []
        if is_graph_off and include_ablation_notice:
            notices.append({
                "code": "GRAPH_ABLATION",
                "typed_code": 18,
                "message": "Graph disabled by request",
            })

        retrieved_chunks = [
            {"chunk_id": f"c{i}", "document_id": "doc1", "is_truncated": False}
            for i in range(chunk_count)
        ]

        # final_answer frame
        events.append(
            (
                "final_answer",
                {
                    "answer": "Test answer",
                    "notices": notices,
                    "snapshot": {"retrieved_chunks": retrieved_chunks},
                },
            )
        )

        # node timings
        for nname, dur in dur_map.items():
            events.append(
                (
                    "node_completed",
                    {"node_name": nname, "duration_ms": dur},
                )
            )

        # workflow_completed
        events.append(
            (
                "workflow_completed",
                {
                    "success": True,
                    "total_duration_ms": 1000,
                    "notices": notices,
                    "metadata": {
                        "vector_count": chunk_count,
                        "bm25_count": 0,
                        "graph_node_count": 0 if is_graph_off else graph_nodes,
                    },
                },
            )
        )

        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            text=_make_sse_stream(events),
        )

    httpx_mock.add_callback(sse_cb, is_reusable=True)


def test_canary_floors_all_met_passes(httpx_mock: HTTPXMock) -> None:
    """Proves check_canary_floors passes when all floors are satisfied."""
    _mock_canary_responses(httpx_mock)
    client = httpx.Client(base_url="http://testserver")
    res = check_canary_floors(client)
    assert res.passed
    assert "All 7 canaries passed floors" in res.message


def test_canary_floors_retrieval_floor_missed_fails_with_qid(
    httpx_mock: HTTPXMock,
) -> None:
    """Proves canary returning zero chunks fails and names the canary QID."""
    _mock_canary_responses(httpx_mock, chunk_count=0)
    client = httpx.Client(base_url="http://testserver")
    res = check_canary_floors(client)
    assert not res.passed
    assert "retrieval floor missed" in res.message
    # Must name offending canary QID
    assert "mhr-0073ab564e55" in res.message


def test_canary_floors_graph_floor_missed_fails_with_remedy(
    httpx_mock: HTTPXMock,
) -> None:
    """Proves designated graph canary missing graph node fails with D-05 remedy note."""
    _mock_canary_responses(httpx_mock, graph_nodes=0)
    client = httpx.Client(base_url="http://testserver")
    res = check_canary_floors(client)
    assert not res.passed
    assert "graph floor missed" in res.message
    assert "mhr-0d5e238015ef" in res.message
    assert "06.3.3 D-05 inspection" in res.message


def test_canary_floors_twin_missing_ablation_fails(httpx_mock: HTTPXMock) -> None:
    """Proves graph-off twin missing notice 18 fails."""
    _mock_canary_responses(httpx_mock, include_ablation_notice=False)
    client = httpx.Client(base_url="http://testserver")
    res = check_canary_floors(client)
    assert not res.passed
    assert "graph-off twin missing required ablation notice" in res.message
    assert "18" in res.message


def test_canary_floors_duration_floor_live_config_and_key_name(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """Proves duration floor is evaluated live against config and names config key."""
    # Mock node duration at 1500ms
    _mock_canary_responses(
        httpx_mock,
        durations={
            "RetrieveHybrid": 1500.0,
            "ExtractGraphContext": 200.0,
            "AssemblePrompt": 50.0,
            "GenerateAnswer": 300.0,
        },
    )

    client = httpx.Client(base_url="http://testserver")

    # Config 1: generous budget (2000ms) -> PASS
    cfg_generous = tmp_path / "cfg_generous.toml"
    cfg_generous.write_text(
        """
        [engine.workflow]
        reformulate_timeout_ms = 5000
        retrieve_timeout_ms = 2000
        graph_node_timeout_ms = 15000
        prompt_timeout_ms = 2000
        generation_node_timeout_ms = 65000
        """,
        encoding="utf-8",
    )
    res_pass = check_canary_floors(client, config_path=cfg_generous)
    assert res_pass.passed

    # Config 2: tight budget (1000ms) -> FAIL naming key
    cfg_tight = tmp_path / "cfg_tight.toml"
    cfg_tight.write_text(
        """
        [engine.workflow]
        reformulate_timeout_ms = 5000
        retrieve_timeout_ms = 1000
        graph_node_timeout_ms = 15000
        prompt_timeout_ms = 2000
        generation_node_timeout_ms = 65000
        """,
        encoding="utf-8",
    )
    res_fail = check_canary_floors(client, config_path=cfg_tight)
    assert not res_fail.passed
    assert "RetrieveHybrid" in res_fail.message
    assert "retrieve_timeout_ms" in res_fail.message
    assert "1500.0ms" in res_fail.message


def test_aggregation_canary_manifest_always_present_and_floors_gated(
    httpx_mock: HTTPXMock,
) -> None:
    """Proves canary_manifest is present always, canary_floors only when reachable."""
    # 1. Gateway DOWN
    httpx_mock.add_exception(httpx.ConnectError("Gateway down"), url="http://testserver/health")
    with httpx.Client(base_url="http://testserver") as client:
        results_down = run_preflight_checks("multihop_rag", client=client)

    names_down = [r.name for r in results_down]
    assert "canary_manifest" in names_down
    assert "canary_floors" not in names_down
    # manifest passes
    man_down = next(r for r in results_down if r.name == "canary_manifest")
    assert man_down.passed

    # 2. Gateway and Engine UP
    httpx_mock.reset()
    httpx_mock.add_response(
        url="http://testserver/health",
        status_code=200,
        json={"status": "ok", "engine": {"status": "ok"}},
    )
    # Mock corpus generation probe
    doc_probe_data = (
        'event: final_answer\n'
        'data: {"answer": "A", "snapshot": {"index_generation": "gen1"}}\n\n'
    )
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=doc_probe_data,
    )
    # Mock canary queries
    _mock_canary_responses(httpx_mock)

    with httpx.Client(base_url="http://testserver") as client:
        results_up = run_preflight_checks("multihop_rag", client=client)

    names_up = [r.name for r in results_up]
    assert "canary_manifest" in names_up
    assert "canary_floors" in names_up
