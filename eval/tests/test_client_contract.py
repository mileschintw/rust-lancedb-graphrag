"""Tests for the contract-asserting SSE client and settings configuration."""

import inspect
import json

import httpx
import pytest
from pytest_httpx import HTTPXMock

from lancet_eval.client import (
    ContractViolation,
    PreStreamError,
    StreamAborted,
    StreamDeadlineExceeded,
    StructuredCitation,
    run_query,
)
from lancet_eval.config import EvalConfigError, EvalSettings


def test_happy_path_sse_and_citation_separation(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    raw_sse = load_sse_fixture("happy.txt")
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={
            "content-type": "text/event-stream",
            "X-Lancet-Session-ID": "sess-1",
            "X-Lancet-Correlation-ID": "corr-1",
        },
        text=raw_sse,
    )

    with httpx.Client(base_url="http://testserver") as client:
        outcome = run_query(client, query="Who is the CEO of OpenAI?")

    assert outcome.status == "ok"
    assert outcome.session_id == "sess-1"
    assert outcome.correlation_id == "corr-1"
    assert outcome.duration_ms == 120
    assert outcome.answer is not None
    assert outcome.answer.answer == "The answer is Sam Altman."
    assert len(outcome.notices) == 1
    assert outcome.notices[0].message == "Success"

    # Citation separation checks:
    structured = outcome.answer.structured_citations
    snapshot = outcome.answer.snapshot
    assert snapshot is not None
    retrieved = snapshot.retrieved_chunks

    assert len(structured) == 1
    assert len(retrieved) == 4
    assert structured[0].chunk_id == "chunk-cited-1"
    assert [c.chunk_id for c in retrieved] == [
        "chunk-ret-1",
        "chunk-ret-2",
        "chunk-ret-3",
        "chunk-ret-4",
    ]
    assert all(isinstance(c, StructuredCitation) for c in structured)
    assert all(isinstance(c, StructuredCitation) for c in retrieved)


def test_degraded_terminal_only(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    raw_sse = load_sse_fixture("degraded_terminal_only.txt")
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )

    with httpx.Client(base_url="http://testserver") as client:
        outcome = run_query(client, query="Unknown query")

    assert outcome.status == "degraded"
    assert outcome.answer is None
    assert len(outcome.notices) == 1
    assert outcome.notices[0].code == "NO_EVIDENCE"
    assert outcome.notices[0].typed_code == 1


def test_node_failure_then_success(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    raw_sse = load_sse_fixture("node_failed_then_success.txt")
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )

    with httpx.Client(base_url="http://testserver") as client:
        outcome = run_query(client, query="Query with node failure")

    assert outcome.status == "ok"
    assert len(outcome.node_failures) == 1
    assert outcome.node_failures[0].node_name == "ExtractGraphContext"
    assert outcome.node_failures[0].error_kind == 3
    assert outcome.node_failures[0].retryable is False


def test_duplicate_final_answer_raises_contract_violation(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    raw_sse = load_sse_fixture("duplicate_final_answer.txt")
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )

    with httpx.Client(base_url="http://testserver") as client:
        with pytest.raises(ContractViolation, match="2 final_answer frames"):
            run_query(client, query="Duplicate test")


def test_missing_terminal_raises_stream_aborted(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    raw_sse = load_sse_fixture("missing_terminal.txt")
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )

    with httpx.Client(base_url="http://testserver") as client:
        with pytest.raises(StreamAborted, match="without workflow_completed"):
            run_query(client, query="Missing terminal test")


def test_stream_error_frame_raises_stream_aborted(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    raw_sse = load_sse_fixture("stream_error.txt")
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )

    with httpx.Client(base_url="http://testserver") as client:
        with pytest.raises(StreamAborted, match="STREAM_EOF_WITHOUT_TERMINAL"):
            run_query(client, query="Stream error test")


def test_pre_stream_plain_text_error_raises_pre_stream_error(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=400,
        headers={"content-type": "text/plain; charset=utf-8"},
        text="unknown field 'bogus'",
    )

    with httpx.Client(base_url="http://testserver") as client:
        with pytest.raises(PreStreamError, match="HTTP 400"):
            run_query(client, query="Bad request")


def test_stream_deadline_exceeded(httpx_mock: HTTPXMock) -> None:
    raw_sse = (
        'event: node_started\ndata: {"node_name":"Retrieve"}\n\n'
        'event: answer_chunk\ndata: {"chunk_text":"chunk 1"}\n\n'
    )
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )

    with httpx.Client(base_url="http://testserver") as client:
        with pytest.raises(StreamDeadlineExceeded, match="wall-clock deadline"):
            run_query(client, query="Slow query", deadline_s=-1.0)


def test_workflow_completed_success_false_returns_failed_status(
    httpx_mock: HTTPXMock,
) -> None:
    raw_sse = (
        'event: node_started\ndata: {"node_name":"Generate"}\n\n'
        "event: workflow_completed\n"
        'data: {"success":false,"error_kind":2,'
        '"error_message":"generation model failed","total_duration_ms":80,'
        '"notices":[{"code":"GEN_FAIL","message":"model error","severity":2,'
        '"typed_code":20}]}\n\n'
    )
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )

    with httpx.Client(base_url="http://testserver") as client:
        outcome = run_query(client, query="Failed query")

    assert outcome.status == "failed"
    assert outcome.completion.success is False
    assert outcome.completion.error_kind == 2
    assert outcome.completion.error_message == "generation model failed"
    assert len(outcome.notices) == 1
    assert outcome.notices[0].code == "GEN_FAIL"


def test_workflow_completed_with_both_final_response_and_notices(
    httpx_mock: HTTPXMock,
) -> None:
    raw_sse = (
        "event: workflow_completed\n"
        'data: {"success":true,"final_response":{"answer":"ok"},'
        '"notices":[{"code":"WARN","message":"msg"}]}\n\n'
    )
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )

    with httpx.Client(base_url="http://testserver") as client:
        with pytest.raises(
            ContractViolation,
            match="cannot carry both final_response and top-level notices",
        ):
            run_query(client, query="Invalid terminal")


def test_disable_graph_context_body_serialization(httpx_mock: HTTPXMock) -> None:
    resp_text = (
        "event: workflow_completed\n"
        'data: {"success":true,"final_response":{"answer":"ok"}}\n\n'
    )
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=resp_text,
    )
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=resp_text,
    )

    sig = inspect.signature(run_query)
    assert "disable_graph_context" in sig.parameters
    assert sig.parameters["disable_graph_context"].annotation in (bool, "bool")

    with httpx.Client(base_url="http://testserver") as client:
        run_query(client, query="graph off", disable_graph_context=True)
        run_query(client, query="graph on", disable_graph_context=False)

    requests = httpx_mock.get_requests()
    assert len(requests) == 2

    body_off = json.loads(requests[0].read().decode("utf-8"))
    assert "disable_graph_context" in body_off
    assert body_off["disable_graph_context"] is True

    body_on = json.loads(requests[1].read().decode("utf-8"))
    assert "disable_graph_context" not in body_on


def test_snapshot_null_vs_empty_distinction(httpx_mock: HTTPXMock) -> None:
    # Snapshot null
    sse_null_snapshot = (
        'event: final_answer\ndata: {"answer":"ans1","snapshot":null}\n\n'
        "event: workflow_completed\n"
        'data: {"success":true,"final_response":{"answer":"ans1","snapshot":null}}\n\n'
    )
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=sse_null_snapshot,
    )

    # Snapshot empty retrieved chunks
    sse_empty_retrieved = (
        'event: final_answer\ndata: {"answer":"ans2",'
        '"snapshot":{"index_generation":"gen-1","retrieved_chunks":[]}}\n\n'
        "event: workflow_completed\n"
        'data: {"success":true,"final_response":{"answer":"ans2",'
        '"snapshot":{"index_generation":"gen-1","retrieved_chunks":[]}}}\n\n'
    )
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=sse_empty_retrieved,
    )

    with httpx.Client(base_url="http://testserver") as client:
        outcome_null = run_query(client, query="q1")
        outcome_empty = run_query(client, query="q2")

    assert outcome_null.answer is not None
    assert outcome_null.answer.snapshot is None

    assert outcome_empty.answer is not None
    assert outcome_empty.answer.snapshot is not None
    assert outcome_empty.answer.snapshot.retrieved_chunks == []


def test_eval_settings_validation_and_field_inventory() -> None:
    with pytest.raises(EvalConfigError):
        EvalSettings(max_workers=0)

    with pytest.raises(EvalConfigError):
        EvalSettings(judge_endpoint="http://insecure.endpoint")

    with pytest.raises(EvalConfigError):
        EvalSettings(question_deadline_secs=-5.0)

    expected_fields = {
        "gateway_url",
        "gateway_timeout_secs",
        "question_deadline_secs",
        "lancedb_path",
        "database_url",
        "dev_lancedb_path",
        "dev_database_url",
        "judge_model",
        "judge_temperature",
        "judge_max_tokens",
        "judge_prompt_version",
        "judge_endpoint",
        "max_workers",
        "sample_seed",
    }
    assert set(EvalSettings.model_fields.keys()) == expected_fields
