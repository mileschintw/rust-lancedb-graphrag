"""Tests for preflight canary checks (manifest and live query floors)."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock

import lancet_eval.preflight as preflight_module
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
    assert res.detail.get("row_count") == 8
    assert res.detail.get("distinct_ids") == 7


def test_canary_manifest_missing_file_fails(tmp_path: Path) -> None:
    """Proves missing canary file fails loudly naming the expected path."""
    fake_path = tmp_path / "nonexistent.jsonl"
    res = check_canary_manifest(canary_path=fake_path)
    assert not res.passed
    assert "Canary manifest missing at expected path" in res.message
    assert str(fake_path) in res.message


def test_canary_manifest_drifted_question_fails(tmp_path: Path) -> None:
    """Proves canary row with modified text fails naming the question ID."""
    # Write 7 sample questions
    sample_rows = [
        {"question_id": f"q{i}", "query": f"Original query {i}?"}
        for i in range(1, 8)
    ]
    sample_p = tmp_path / "sample.jsonl"
    sample_p.write_text(
        "\n".join(json.dumps(r) for r in sample_rows) + "\n",
        encoding="utf-8",
    )

    # 8 canary rows, 7 distinct IDs (q1 has two rows), q1 drifted
    canary_p = tmp_path / "canary.jsonl"
    canary_rows = [
        {"question_id": "q1", "question": "Tampered query?", "graph_arm": "graph-on"},
        {"question_id": "q2", "question": "Original query 2?", "graph_arm": "graph-on"},
        {"question_id": "q3", "question": "Original query 3?", "graph_arm": "graph-on"},
        {"question_id": "q4", "question": "Original query 4?", "graph_arm": "graph-on"},
        {"question_id": "q5", "question": "Original query 5?", "graph_arm": "graph-on"},
        {"question_id": "q6", "question": "Original query 6?", "graph_arm": "graph-on"},
        {"question_id": "q7", "question": "Original query 7?", "graph_arm": "graph-on"},
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
    path_found: bool | None = True,
    prompt_facts: int | None = 2,
) -> None:
    """Helper to mock SSE responses for all 8 canaries."""
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
                        # D-79/D-80: the seeding diagnostics a path canary reads. A
                        # None is omitted from the wire, as for an older engine.
                        **(
                            {}
                            if is_graph_off or path_found is None
                            else {"graph_path_found": path_found}
                        ),
                        **(
                            {}
                            if is_graph_off or prompt_facts is None
                            else {"graph_prompt_fact_count": prompt_facts}
                        ),
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
    assert "All 8 canaries passed floors" in res.message


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


# --- 06.3.4.1-17 D-80: the seed-to-seed path canary --------------------------------

PATH_CANARY_ID = "mhr-3b0dac3a26bd"
CANARY_FILE = (
    Path(__file__).resolve().parents[1] / "corpora" / "multihop_rag" / "canary.jsonl"
)


def _committed_canary_rows() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in CANARY_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_canary_manifest_counts_are_named_constants() -> None:
    """D-80 moves the hard-coded counts from 7 rows / 6 IDs to 8 / 7."""
    assert hasattr(preflight_module, "CANARY_MANIFEST_ROW_COUNT")
    assert hasattr(preflight_module, "CANARY_MANIFEST_DISTINCT_IDS")
    assert preflight_module.CANARY_MANIFEST_ROW_COUNT == 8
    assert preflight_module.CANARY_MANIFEST_DISTINCT_IDS == 7


def _manifest_files(tmp_path: Path, *, rows: int, ids: int) -> tuple[Path, Path]:
    """A sample of `ids` questions and a manifest of `rows` rows over `ids` IDs."""
    sample_rows = [
        {"question_id": f"q{i}", "query": f"Original query {i}?"} for i in range(ids)
    ]
    canary_rows = [
        {
            "question_id": f"q{i % ids}",
            "question": f"Original query {i % ids}?",
            "graph_arm": "graph-on",
        }
        for i in range(rows)
    ]
    sample_p = tmp_path / "sample.jsonl"
    sample_p.write_text(
        "\n".join(json.dumps(r) for r in sample_rows) + "\n", encoding="utf-8"
    )
    canary_p = tmp_path / "canary.jsonl"
    canary_p.write_text(
        "\n".join(json.dumps(r) for r in canary_rows) + "\n", encoding="utf-8"
    )
    return canary_p, sample_p


def test_canary_manifest_accepts_exactly_eight_rows_over_seven_ids(
    tmp_path: Path,
) -> None:
    canary_p, sample_p = _manifest_files(tmp_path, rows=8, ids=7)
    res = check_canary_manifest(canary_path=canary_p, sample_path=sample_p)
    assert res.passed, res.message
    assert res.detail == {"row_count": 8, "distinct_ids": 7}


@pytest.mark.parametrize(("rows", "ids"), [(7, 6), (9, 8)])
def test_canary_manifest_rejects_the_neighbouring_counts(
    tmp_path: Path, rows: int, ids: int
) -> None:
    canary_p, sample_p = _manifest_files(tmp_path, rows=rows, ids=ids)
    res = check_canary_manifest(canary_path=canary_p, sample_path=sample_p)
    assert not res.passed
    assert "exactly 8 rows" in res.message
    assert f"got {rows}" in res.message


def test_canary_manifest_rejects_eight_rows_over_six_ids(tmp_path: Path) -> None:
    canary_p, sample_p = _manifest_files(tmp_path, rows=8, ids=6)
    res = check_canary_manifest(canary_path=canary_p, sample_path=sample_p)
    assert not res.passed
    assert "exactly 7 distinct IDs" in res.message


def test_the_committed_canary_file_has_one_path_canary_and_keeps_its_old_rows() -> None:
    rows = _committed_canary_rows()
    assert len(rows) == 8
    assert len({r["question_id"] for r in rows}) == 7
    path_rows = [r for r in rows if r.get("require_seed_path")]
    assert [(r["question_id"], r["graph_arm"]) for r in path_rows] == [
        (PATH_CANARY_ID, "graph-on")
    ]
    row = path_rows[0]
    assert row["min_retrieved_chunks"] == 1
    assert row["require_graph_node"] is True
    assert row["require_retrieval_completed_only"] is False
    assert row["require_ablation_notice"] is False
    # The seven earlier rows never carry the new key.
    assert sum(1 for r in rows if "require_seed_path" in r) == 1


def _path_canary_file(tmp_path: Path, *, require_graph_node: bool = False) -> Path:
    path = tmp_path / "path_canary.jsonl"
    path.write_text(
        json.dumps(
            {
                "question_id": "qp",
                "graph_arm": "graph-on",
                "question": "A path question?",
                "question_type": "comparison",
                "min_retrieved_chunks": 1,
                "require_graph_node": require_graph_node,
                "require_retrieval_completed_only": False,
                "require_ablation_notice": False,
                "require_seed_path": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_seed_path_floor_met_passes(tmp_path: Path, httpx_mock: HTTPXMock) -> None:
    _mock_canary_responses(httpx_mock)
    client = httpx.Client(base_url="http://testserver")
    res = check_canary_floors(client, canary_path=_path_canary_file(tmp_path))
    assert res.passed, res.message


@pytest.mark.parametrize(
    ("mock_kwargs", "unmet"),
    [
        ({"path_found": False}, "graph_path_found"),
        ({"path_found": None}, "graph_path_found"),
        ({"graph_nodes": 0}, "graph_node_count"),
        ({"prompt_facts": 0}, "graph_prompt_fact_count"),
        ({"prompt_facts": None}, "graph_prompt_fact_count"),
        ({"chunk_count": 0}, "retrieved chunks"),
    ],
)
def test_seed_path_floor_names_the_unmet_condition(
    tmp_path: Path,
    httpx_mock: HTTPXMock,
    mock_kwargs: dict[str, Any],
    unmet: str,
) -> None:
    _mock_canary_responses(httpx_mock, **mock_kwargs)
    client = httpx.Client(base_url="http://testserver")
    res = check_canary_floors(client, canary_path=_path_canary_file(tmp_path))
    assert not res.passed
    assert "qp" in res.message
    assert "require_seed_path" in res.message
    assert unmet in res.message


def test_seed_path_floor_reports_only_the_first_unmet_condition(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    # The path flag, the graph node count and the prompt facts are all unmet at once.
    _mock_canary_responses(
        httpx_mock, path_found=False, graph_nodes=0, prompt_facts=0
    )
    client = httpx.Client(base_url="http://testserver")
    res = check_canary_floors(client, canary_path=_path_canary_file(tmp_path))
    seed_path_failures = [
        part for part in res.message.split("; ") if "require_seed_path" in part
    ]
    assert len(seed_path_failures) == 1
    assert "graph_path_found" in seed_path_failures[0]
    assert "graph_node_count" not in seed_path_failures[0]
    assert "graph_prompt_fact_count" not in seed_path_failures[0]


# --- 06.3.5-09 D-108, D-124, D-106: arm-mode canaries from the rehearsal pool ---------

_ARMS = ["dense-only", "bm25-only", "hybrid", "hybrid+graph"]
_CORPORA = Path(__file__).resolve().parents[1] / "corpora"
ARM_CANARY_FILE = _CORPORA / "multihop_rag" / "canary.arms.jsonl"
SPLIT_FILE = _CORPORA / "multihop_rag" / "heldout_split.json"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _arm_of_body(body: dict[str, Any]) -> str:
    """The arm a request body asks for, by the fields `request_fields` produces."""
    mode = body.get("retrieval_mode")
    if mode == "dense_only":
        return "dense-only"
    if mode == "bm25_only":
        return "bm25-only"
    if mode == "hybrid":
        return "hybrid" if body.get("disable_graph_context") else "hybrid+graph"
    return "legacy"


def _mock_arm_responses(
    httpx_mock: HTTPXMock,
    *,
    echo: dict[str, str] | None = None,
    drop_ranking: tuple[str, ...] = (),
    omit_ablation: tuple[str, ...] = (),
    bm25_count_on_dense: int = 0,
    chunk_count: int = 2,
    retrieve_ms: float = 100.0,
) -> None:
    """A well-formed answer for each arm, and one fault per keyword when asked."""

    def sse_cb(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        arm = _arm_of_body(body)
        graph_off = bool(body.get("disable_graph_context"))
        mode = body.get("retrieval_mode") or "hybrid"
        notices = []
        if graph_off and arm not in omit_ablation:
            notices.append(
                {
                    "code": "GRAPH_ABLATION",
                    "typed_code": 18,
                    "message": "Graph disabled by request",
                }
            )
        chunks = [
            {
                "chunk_id": f"c{i}",
                "document_id": "doc1",
                "rank": i + 1,
                "graph_boosted": False,
            }
            for i in range(chunk_count)
        ]
        ranking = [
            {
                "chunk_id": f"c{i}",
                "document_id": "doc1",
                "fused_rank": i + 1,
                **({} if arm == "bm25-only" else {"vector_rank": i + 1}),
                **({} if arm == "dense-only" else {"bm25_rank": i + 1}),
            }
            for i in range(chunk_count)
        ]
        snapshot: dict[str, Any] = {
            "index_generation": "gen1",
            "retrieval_mode": (echo or {}).get(arm, mode),
            "result_hash": "abc123",
            "rrf_k": 60,
            "candidate_limit": 32,
            "final_limit": 8,
            "vector_weight": 1.0,
            "bm25_weight": 1.0,
            "retrieved_chunks": chunks,
        }
        if arm not in drop_ranking:
            snapshot["pre_truncation_ranking"] = ranking
        events: list[tuple[str, dict[str, Any]]] = [
            (
                "final_answer",
                {"answer": "Test answer", "notices": notices, "snapshot": snapshot},
            ),
            (
                "node_completed",
                {"node_name": "RetrieveHybrid", "duration_ms": retrieve_ms},
            ),
            (
                "workflow_completed",
                {
                    "success": True,
                    "total_duration_ms": 1000,
                    "notices": notices,
                    "metadata": {
                        "vector_count": 0 if arm == "bm25-only" else chunk_count,
                        "bm25_count": (
                            bm25_count_on_dense
                            if arm == "dense-only"
                            else chunk_count
                        ),
                        "graph_node_count": 0,
                    },
                },
            ),
        ]
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            text=_make_sse_stream(events),
        )

    httpx_mock.add_callback(sse_cb, is_reusable=True)


def _request_bodies(httpx_mock: HTTPXMock) -> list[dict[str, Any]]:
    return [
        json.loads(r.read().decode("utf-8"))
        for r in httpx_mock.get_requests()
        if r.url.path == "/rag/query"
    ]


def _run_arm_canaries(client: httpx.Client, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "arms": _ARMS,
        "canary_path": ARM_CANARY_FILE,
        "split_path": SPLIT_FILE,
    }
    kwargs.update(overrides)
    return preflight_module.check_arm_mode_canaries(client, **kwargs)


def test_arm_mode_canaries_run_every_row_under_every_arm(
    httpx_mock: HTTPXMock,
) -> None:
    from lancet_eval.arms import request_fields

    _mock_arm_responses(httpx_mock)
    client = httpx.Client(base_url="http://testserver")

    res = _run_arm_canaries(client)

    assert res.name == "arm_mode_canaries"
    assert res.passed, res.message
    rows = _jsonl(ARM_CANARY_FILE)
    assert len(rows) == 3
    bodies = _request_bodies(httpx_mock)
    assert len(bodies) == 12
    expected = [
        {"query": row["question"], "session_id": "", **request_fields(arm)}
        for row in rows
        for arm in _ARMS
    ]
    key = lambda b: json.dumps(b, sort_keys=True)  # noqa: E731
    assert sorted(map(key, bodies)) == sorted(map(key, expected))


@pytest.mark.parametrize(
    ("fault", "mock_kwargs", "arm", "needle"),
    [
        (
            "a wrong echo on one arm",
            {"echo": {"bm25-only": "hybrid"}},
            "bm25-only",
            "retrieval_mode",
        ),
        (
            "an absent ranking beside non-empty chunks",
            {"drop_ranking": ("hybrid",)},
            "hybrid",
            "pre_truncation_ranking",
        ),
        (
            "a missing GRAPH_ABLATION on a graph-off arm",
            {"omit_ablation": ("hybrid",)},
            "hybrid",
            "GRAPH_ABLATION",
        ),
        (
            "a non-zero bm25_count on dense-only",
            {"bm25_count_on_dense": 3},
            "dense-only",
            "bm25_count",
        ),
        (
            "zero retrieved chunks",
            {"chunk_count": 0},
            "hybrid+graph",
            "retrieval floor",
        ),
    ],
)
def test_arm_mode_canary_faults_fail_naming_the_question_and_the_arm(
    httpx_mock: HTTPXMock,
    fault: str,
    mock_kwargs: dict[str, Any],
    arm: str,
    needle: str,
) -> None:
    _mock_arm_responses(httpx_mock, **mock_kwargs)
    client = httpx.Client(base_url="http://testserver")

    res = _run_arm_canaries(client)

    assert not res.passed, fault
    qid = _jsonl(ARM_CANARY_FILE)[0]["question_id"]
    assert f"{qid} ({arm})" in res.message, fault
    assert needle in res.message, fault


def test_arm_mode_canary_duration_floor_is_read_from_the_live_config(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    _mock_arm_responses(httpx_mock, retrieve_ms=1500.0)
    client = httpx.Client(base_url="http://testserver")
    template = """
    [engine.workflow]
    reformulate_timeout_ms = 5000
    retrieve_timeout_ms = {retrieve}
    graph_node_timeout_ms = 15000
    prompt_timeout_ms = 2000
    generation_node_timeout_ms = 65000
    """
    generous = tmp_path / "generous.toml"
    generous.write_text(template.format(retrieve=2000), encoding="utf-8")
    tight = tmp_path / "tight.toml"
    tight.write_text(template.format(retrieve=1000), encoding="utf-8")

    assert _run_arm_canaries(client, config_path=generous).passed
    res = _run_arm_canaries(client, config_path=tight)

    assert not res.passed
    assert "RetrieveHybrid" in res.message
    assert "retrieve_timeout_ms" in res.message


def _split_ids() -> dict[str, str]:
    split = json.loads(SPLIT_FILE.read_text(encoding="utf-8"))
    return {
        "a dev ID": split["dev_ids"][0],
        "a held-out G ID": split["heldout_g_ids"][0],
        "a held-out null ID": split["heldout_null_ids"][0],
    }


@pytest.mark.parametrize("which", sorted(_split_ids()))
def test_a_manifest_holding_a_dev_or_heldout_id_is_refused_before_any_request(
    tmp_path: Path, httpx_mock: HTTPXMock, which: str
) -> None:
    banned = _split_ids()[which]
    rows = _jsonl(ARM_CANARY_FILE)
    rows.append({"question_id": banned, "question": "A banned question?"})
    manifest = tmp_path / "canary.arms.jsonl"
    manifest.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    client = httpx.Client(base_url="http://testserver")

    res = _run_arm_canaries(client, canary_path=manifest)

    assert not res.passed
    assert banned in res.message
    assert "D-124" in res.message
    assert httpx_mock.get_requests() == []


def test_the_committed_arm_manifest_holds_no_dev_or_heldout_id() -> None:
    split = json.loads(SPLIT_FILE.read_text(encoding="utf-8"))
    banned = set(split["dev_ids"]) | set(split["heldout_g_ids"])
    banned |= set(split["heldout_null_ids"])
    assert not {r["question_id"] for r in _jsonl(ARM_CANARY_FILE)} & banned


def _legacy_only_texts() -> set[str]:
    arm_texts = {r["question"] for r in _jsonl(ARM_CANARY_FILE)}
    legacy = _jsonl(_CORPORA / "multihop_rag" / "canary.jsonl")
    return {r["question"] for r in legacy} - arm_texts


def _health_ok(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://testserver/health",
        status_code=200,
        json={"status": "ok", "engine": {"status": "ok"}},
    )


def test_heldout_preflight_skips_the_legacy_canaries_and_runs_the_arm_canaries(
    httpx_mock: HTTPXMock,
) -> None:
    _health_ok(httpx_mock)
    _mock_arm_responses(httpx_mock)

    with httpx.Client(base_url="http://testserver") as client:
        results = run_preflight_checks("multihop_rag_heldout", client=client)

    by_name = {r.name: r for r in results}
    for name in ("canary_manifest", "canary_floors"):
        skipped = by_name[name]
        assert skipped.passed
        assert skipped.detail.get("skipped") is True
        assert "D-124" in skipped.message
    assert by_name["arm_mode_canaries"].passed, by_name["arm_mode_canaries"].message

    arm_texts = {r["question"] for r in _jsonl(ARM_CANARY_FILE)}
    bodies = _request_bodies(httpx_mock)
    sent = [b["query"] for b in bodies]
    # None of the 7 legacy canary questions is sent (the one shared with the arm
    # manifest is sent only as an arm canary: 3 rows x 4 arms and nothing else).
    assert not set(sent) & _legacy_only_texts()
    assert sum(1 for q in sent if q in arm_texts) == 12


def test_legacy_corpora_run_exactly_the_checks_they_ran_before(
    httpx_mock: HTTPXMock,
) -> None:
    _health_ok(httpx_mock)
    _mock_canary_responses(httpx_mock)

    with httpx.Client(base_url="http://testserver") as client:
        results = run_preflight_checks("multihop_rag_diag", client=client)

    by_name = {r.name: r for r in results}
    assert "arm_mode_canaries" not in by_name
    assert "skipped" not in by_name["canary_manifest"].detail
    assert "skipped" not in by_name["canary_floors"].detail
    legacy_texts = {
        r["question"] for r in _jsonl(_CORPORA / "multihop_rag" / "canary.jsonl")
    }
    sent = [b["query"] for b in _request_bodies(httpx_mock)]
    assert sum(1 for q in sent if q in legacy_texts) == 8
