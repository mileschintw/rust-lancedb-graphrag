"""Tests for wire diagnostics capture, snapshot precedence, and outcome routing."""

import json
from pathlib import Path

import httpx
from pytest_httpx import HTTPXMock

from lancet_eval.client import NodeCompleted, WorkflowMetadata, run_query
from lancet_eval.corpus import GoldQuestion
from lancet_eval.journal import RunRecord
from lancet_eval.run import drive_one
from lancet_eval.usability import is_usable


def test_wire_diagnostics_timing_and_metadata_capture(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    raw_sse = load_sse_fixture("wire_diagnostics.txt")
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={
            "content-type": "text/event-stream",
            "X-Lancet-Session-ID": "sess-diag-1",
            "X-Lancet-Correlation-ID": "corr-diag-1",
        },
        text=raw_sse,
    )

    with httpx.Client(base_url="http://testserver") as client:
        outcome = run_query(client, query="Test query")

    assert outcome.status == "ok"
    assert len(outcome.node_timings) == 2
    assert outcome.node_timings[0].node_name == "RetrieveHybrid"
    assert outcome.node_timings[0].duration_ms == 42.5
    assert outcome.node_timings[1].node_name == "GenerateAnswer"
    assert outcome.node_timings[1].duration_ms == 120.0

    meta = outcome.workflow_meta
    assert meta is not None
    assert meta.vector_count == 5
    assert meta.bm25_count == 3
    assert meta.graph_node_count == 2
    assert meta.graph_edge_count == 1
    assert meta.reformulation_used is True
    assert meta.degraded_mode is False
    assert meta.prompt_tokens == 150
    assert meta.completion_tokens == 40
    assert meta.graph_prompt_fact_count == 2


def test_absent_metadata_and_absent_influence_counter(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    raw_sse = load_sse_fixture("absent_metadata.txt")
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )
    with httpx.Client(base_url="http://testserver") as client:
        outcome = run_query(client, query="q")
    assert outcome.workflow_meta is None

    # Test WorkflowMetadata absent vs zero
    m1 = WorkflowMetadata.model_validate({"vector_count": 3})
    assert m1.graph_prompt_fact_count is None
    m2 = WorkflowMetadata.model_validate({"graph_prompt_fact_count": 0})
    assert m2.graph_prompt_fact_count == 0


def test_node_completed_duration_absent_vs_zero() -> None:
    n1 = NodeCompleted.model_validate({"node_name": "RetrieveHybrid"})
    assert n1.duration_ms is None
    n2 = NodeCompleted.model_validate(
        {"node_name": "RetrieveHybrid", "duration_ms": 0}
    )
    assert n2.duration_ms == 0.0


def test_snapshot_precedence_synthetic_defence(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    raw_sse = load_sse_fixture("snapshot_precedence.txt")
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )
    gq = GoldQuestion(
        question_id="q1",
        question="What is X?",
        answer="A",
        gold_facts=["F"],
        gold_chunk_ids=["c1"],
        query_type="factual",
    )
    client = httpx.Client(base_url="http://testserver")
    rec = drive_one(client, corpus="test", question=gq, arm="graph-on")

    assert rec.snapshot is not None
    assert len(rec.snapshot.retrieved_chunks) == 3
    assert rec.index_generation == "gen-ans"


def test_snapshot_precedence_answer_snapshot_null_falls_back_to_partial(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    raw_sse = load_sse_fixture("snapshot_null_partial.txt")
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )
    gq = GoldQuestion(
        question_id="q1",
        question="What is X?",
        answer="A",
        gold_facts=["F"],
        gold_chunk_ids=["c1"],
        query_type="factual",
    )
    client = httpx.Client(base_url="http://testserver")
    rec = drive_one(client, corpus="test", question=gq, arm="graph-on")

    assert rec.snapshot is not None
    assert rec.index_generation == "gen-part-provenance"


def test_partial_snapshot_fallback_on_failed_retrieval(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    raw_sse = load_sse_fixture("retrieval_failed_partial_snapshot.txt")
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )
    gq = GoldQuestion(
        question_id="q1",
        question="What is X?",
        answer="A",
        gold_facts=["F"],
        gold_chunk_ids=["c1"],
        query_type="factual",
    )
    client = httpx.Client(base_url="http://testserver")
    rec = drive_one(client, corpus="test", question=gq, arm="graph-on")

    assert rec.outcome == "error"
    assert rec.index_generation != ""
    assert rec.snapshot is not None
    assert rec.snapshot.retrieved_chunks == []


def test_outcome_routing_degraded_is_not_error(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    raw_sse = load_sse_fixture("degraded_success.txt")
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )
    gq = GoldQuestion(
        question_id="q1",
        question="What is X?",
        answer="A",
        gold_facts=["F"],
        gold_chunk_ids=["c1"],
        query_type="factual",
    )
    client = httpx.Client(base_url="http://testserver")
    rec = drive_one(client, corpus="test", question=gq, arm="graph-on")

    assert rec.outcome == "success"
    assert is_usable(rec) is True


def test_retryable_node_failure_then_success_is_usable(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    raw_sse = load_sse_fixture("retryable_then_success.txt")
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )
    gq = GoldQuestion(
        question_id="q1",
        question="What is X?",
        answer="A",
        gold_facts=["F"],
        gold_chunk_ids=["c1"],
        query_type="factual",
    )
    client = httpx.Client(base_url="http://testserver")
    rec = drive_one(client, corpus="test", question=gq, arm="graph-on")

    assert rec.outcome == "success"
    assert len(rec.node_failures) == 1
    assert rec.node_failures[0].retryable is True
    assert is_usable(rec) is True


def test_historical_pre_change_journal_loads() -> None:
    line = Path("eval/runs/2026-09-03-multihop_rag/journal.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()[1]
    rec = RunRecord.model_validate(json.loads(line))
    assert rec.node_timings == []
    assert rec.workflow_meta is None
