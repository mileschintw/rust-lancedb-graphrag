"""Tests for bounded raw-SSE stream event retention and deterministic
baseline selection.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock

from lancet_eval.client import run_query
from lancet_eval.corpus import GoldQuestion
from lancet_eval.raw_events import (
    RawEventSink,
    baseline_sample_ids,
)
from lancet_eval.run import drive_one


def _make_sse_stream(events: list[tuple[str, dict[str, Any]]]) -> str:
    parts = []
    for ev_type, ev_data in events:
        parts.append(f"event: {ev_type}\ndata: {json.dumps(ev_data)}\n\n")
    return "".join(parts)


def test_baseline_deterministic_under_shuffle() -> None:
    """Proves baseline set is identical when questions are shuffled."""
    import random

    questions = [
        GoldQuestion(question_id=f"mhr-{i:04d}", question=f"Q {i}?", gold_facts=[])
        for i in range(100)
    ]
    set1 = baseline_sample_ids(questions)

    shuffled = list(questions)
    random.Random(42).shuffle(shuffled)
    set2 = baseline_sample_ids(shuffled)

    assert set1 == set2
    assert len(set1) == 25
    expected = {f"mhr-{i:04d}" for i in range(25)}
    assert set1 == expected


def test_failure_retention_replays_frames(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """Proves a stream with node_failed writes a raw file replaying frames in order."""
    events = [
        ("node_started", {"node_name": "RetrieveHybrid"}),
        (
            "node_failed",
            {
                "node_name": "RetrieveHybrid",
                "error_kind": 1,
                "error_message": "LanceDB crash",
                "retryable": False,
            },
        ),
        (
            "workflow_completed",
            {
                "success": False,
                "error_kind": 1,
                "error_message": "node failure",
                "total_duration_ms": 50,
                "notices": [],
            },
        ),
    ]
    sse_text = _make_sse_stream(events)

    httpx_mock.add_response(
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=sse_text,
    )

    client = httpx.Client(base_url="http://testserver")
    q = GoldQuestion(question_id="mhr-9999", question="Fail query?", gold_facts=[])
    sink = RawEventSink(tmp_path)

    record = drive_one(
        client,
        corpus="multihop_rag",
        question=q,
        arm="graph-on",
        raw_sink=sink,
        baseline_ids=set(),
    )

    assert record.outcome == "error"
    raw_file = tmp_path / "raw_events" / "graph-on" / "mhr-9999.jsonl"
    assert raw_file.exists()

    lines = raw_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["seq"] == 0
    assert parsed[0]["event"] == "node_started"
    assert parsed[1]["seq"] == 1
    assert parsed[1]["event"] == "node_failed"
    assert parsed[2]["seq"] == 2
    assert parsed[2]["event"] == "workflow_completed"


def test_baseline_retention_success_in_and_out_of_sample(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """Proves clean success in baseline leaves file, outside baseline leaves none."""
    events = [
        ("final_answer", {"answer": "Paris", "snapshot": {"index_generation": "g1"}}),
        ("workflow_completed", {"success": True, "total_duration_ms": 100}),
    ]
    sse_text = _make_sse_stream(events)

    httpx_mock.add_response(
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=sse_text,
    )
    httpx_mock.add_response(
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=sse_text,
    )

    client = httpx.Client(base_url="http://testserver")
    q_in = GoldQuestion(question_id="mhr-0001", question="Q1?", gold_facts=[])
    q_out = GoldQuestion(question_id="mhr-0100", question="Q100?", gold_facts=[])
    baseline_ids = {"mhr-0001"}
    sink = RawEventSink(tmp_path)

    rec_in = drive_one(
        client,
        corpus="multihop_rag",
        question=q_in,
        arm="graph-on",
        raw_sink=sink,
        baseline_ids=baseline_ids,
    )
    assert rec_in.outcome == "success"
    file_in = tmp_path / "raw_events" / "graph-on" / "mhr-0001.jsonl"
    assert file_in.exists()

    rec_out = drive_one(
        client,
        corpus="multihop_rag",
        question=q_out,
        arm="graph-on",
        raw_sink=sink,
        baseline_ids=baseline_ids,
    )
    assert rec_out.outcome == "success"
    file_out = tmp_path / "raw_events" / "graph-on" / "mhr-0100.jsonl"
    assert not file_out.exists()


def test_byte_cap_truncation_records_unwritten_count(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves stream exceeding cap ends with truncation record and dropped count."""
    import lancet_eval.raw_events as raw_events_mod

    monkeypatch.setattr(raw_events_mod, "RAW_EVENT_BYTES_PER_UNIT", 300)

    # Use valid SSE events (answer_chunk, node_started, etc.)
    events = [
        ("answer_chunk", {"delta": f"chunk-{i:02d}-with-some-text-padding-here"})
        for i in range(10)
    ]
    events.append(
        (
            "node_failed",
            {
                "node_name": "TestNode",
                "error_kind": 1,
                "error_message": "forced failure",
                "retryable": False,
            },
        )
    )
    events.append(
        (
            "workflow_completed",
            {
                "success": False,
                "error_kind": 1,
                "error_message": "failed",
                "total_duration_ms": 500,
            },
        )
    )

    sse_text = _make_sse_stream(events)
    httpx_mock.add_response(
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=sse_text,
    )

    client = httpx.Client(base_url="http://testserver")
    q = GoldQuestion(question_id="mhr-overflow", question="Q?", gold_facts=[])
    sink = RawEventSink(tmp_path)

    rec = drive_one(
        client,
        corpus="multihop_rag",
        question=q,
        arm="graph-on",
        raw_sink=sink,
        baseline_ids=set(),
    )
    assert rec.outcome == "error"

    raw_file = tmp_path / "raw_events" / "graph-on" / "mhr-overflow.jsonl"
    assert raw_file.exists()

    lines = raw_file.read_text(encoding="utf-8").strip().split("\n")
    last_record = json.loads(lines[-1])
    assert last_record["event"] == "truncation"
    assert last_record["data"]["truncated"] is True
    assert last_record["data"]["unwritten_frames"] > 0


def test_no_secrets_in_retained_lines(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves no HTTP headers, base URLs, or env vars are written to raw events."""
    secret_env = "SUPER_SECRET_ENV_TOKEN_XYZ_123"
    monkeypatch.setenv("SECRET_TEST_TOKEN", secret_env)
    base_url = "http://super-secret-gateway-domain:8080"

    events = [
        (
            "node_failed",
            {
                "node_name": "ExtractGraph",
                "error_kind": 2,
                "error_message": "timeout",
                "retryable": True,
            },
        ),
        (
            "workflow_completed",
            {
                "success": False,
                "error_kind": 2,
                "error_message": "timeout",
                "total_duration_ms": 100,
            },
        ),
    ]
    sse_text = _make_sse_stream(events)

    httpx_mock.add_response(
        status_code=200,
        headers={
            "content-type": "text/event-stream",
            "X-Lancet-Internal-Secret": "sensitive-token-12345",
        },
        text=sse_text,
    )

    client = httpx.Client(base_url=base_url)
    q = GoldQuestion(question_id="mhr-nosecrets", question="Q?", gold_facts=[])
    sink = RawEventSink(tmp_path)

    drive_one(
        client,
        corpus="multihop_rag",
        question=q,
        arm="graph-on",
        raw_sink=sink,
        baseline_ids=set(),
    )

    raw_file = tmp_path / "raw_events" / "graph-on" / "mhr-nosecrets.jsonl"
    raw_content = raw_file.read_text(encoding="utf-8")

    assert "super-secret-gateway-domain" not in raw_content
    assert "sensitive-token" not in raw_content
    assert "X-Lancet-Internal-Secret" not in raw_content
    assert secret_env not in raw_content


def test_run_query_without_capture_returns_no_raw_payload(
    httpx_mock: HTTPXMock,
) -> None:
    """Proves run_query default capture_raw_events=False leaves raw_events None."""
    events = [
        ("final_answer", {"answer": "Yes"}),
        ("workflow_completed", {"success": True, "total_duration_ms": 50}),
    ]
    sse_text = _make_sse_stream(events)
    httpx_mock.add_response(
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=sse_text,
    )

    client = httpx.Client(base_url="http://testserver")
    outcome = run_query(client, query="Test?", capture_raw_events=False)
    assert outcome.raw_events is None
    assert outcome.raw_events_truncated is False
    assert outcome.raw_events_dropped_frames == 0


def test_unwritable_sink_never_raises_and_preserves_record(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves drive_one never raises and preserves RunRecord even if sink fails."""
    events = [
        (
            "node_failed",
            {
                "node_name": "NodeX",
                "error_kind": 1,
                "error_message": "boom",
                "retryable": False,
            },
        ),
        (
            "workflow_completed",
            {
                "success": False,
                "error_kind": 1,
                "error_message": "failed",
                "total_duration_ms": 50,
            },
        ),
    ]
    sse_text = _make_sse_stream(events)
    httpx_mock.add_response(
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=sse_text,
    )

    client = httpx.Client(base_url="http://testserver")
    q = GoldQuestion(question_id="mhr-sinkfail", question="Q?", gold_facts=[])
    sink = RawEventSink(tmp_path)

    def broken_write(*args: Any, **kwargs: Any) -> Any:
        raise OSError("Permission denied / disk full")

    monkeypatch.setattr(sink, "write_events", broken_write)

    record = drive_one(
        client,
        corpus="multihop_rag",
        question=q,
        arm="graph-on",
        raw_sink=sink,
        baseline_ids=set(),
    )

    assert record.outcome == "error"
    assert record.question_id == "mhr-sinkfail"
    assert len(record.node_failures) == 1
    assert record.node_failures[0].node_name == "NodeX"
    assert record.error_type is None


def test_concurrent_writes_produce_distinct_non_interleaved_files(
    tmp_path: Path,
) -> None:
    """Proves concurrent sink writes to different units produce clean separate files."""
    import concurrent.futures

    sink = RawEventSink(tmp_path)
    events_1 = [
        {"event": "frame_A", "data": json.dumps({"val": i})} for i in range(50)
    ]
    events_2 = [
        {"event": "frame_B", "data": json.dumps({"val": i})} for i in range(50)
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(
            sink.write_events,
            corpus="multihop_rag",
            question_id="q1",
            graph_arm="graph-on",
            events=events_1,
        )
        f2 = executor.submit(
            sink.write_events,
            corpus="multihop_rag",
            question_id="q2",
            graph_arm="graph-off",
            events=events_2,
        )
        p1 = f1.result()
        p2 = f2.result()

    assert p1 is not None and p1.exists()
    assert p2 is not None and p2.exists()
    assert p1 != p2

    lines1 = p1.read_text(encoding="utf-8").strip().split("\n")
    lines2 = p2.read_text(encoding="utf-8").strip().split("\n")

    assert len(lines1) == 50
    assert len(lines2) == 50
    for line in lines1:
        assert "frame_A" in line
        assert "frame_B" not in line
    for line in lines2:
        assert "frame_B" in line
        assert "frame_A" not in line
