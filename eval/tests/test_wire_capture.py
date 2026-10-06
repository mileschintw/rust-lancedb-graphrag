"""Tests for wire diagnostics capture, snapshot precedence, and outcome routing."""

import json
import re
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


# 06.3.4.1-16 (D-79, D-81): the seeding diagnostics and the per-chunk graph flag.

SEED_KEYS = (
    "graph_seed_count",
    "graph_path_found",
    "graph_boosted_chunk_count",
    "graph_degree_capped_count",
    "graph_seed_document_ids",
)
SEED_FIXTURE_VALUES = {
    "graph_seed_count": 2,
    "graph_path_found": True,
    "graph_boosted_chunk_count": 1,
    "graph_degree_capped_count": 3,
    "graph_seed_document_ids": ["d1", "d2"],
}
_MISSING = "<field missing from the model>"


def _seed_gold_question() -> GoldQuestion:
    return GoldQuestion(
        question_id="q-seed",
        question="Who is linked to whom?",
        answer="A",
        gold_facts=["F"],
        gold_chunk_ids=["c1"],
        query_type="factual",
    )


def _add_seed_response(httpx_mock: HTTPXMock, load_sse_fixture) -> None:
    httpx_mock.add_response(
        url="http://testserver/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=load_sse_fixture("graph_seed_fields.txt"),
    )


def test_graph_seed_fields_parse_into_the_client_models(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    _add_seed_response(httpx_mock, load_sse_fixture)
    with httpx.Client(base_url="http://testserver") as client:
        outcome = run_query(client, query="Test query")

    assert outcome.workflow_meta is not None
    dumped = outcome.workflow_meta.model_dump()
    assert {key: dumped.get(key, _MISSING) for key in SEED_KEYS} == SEED_FIXTURE_VALUES
    assert outcome.answer is not None and outcome.answer.snapshot is not None
    chunks = outcome.answer.snapshot.retrieved_chunks
    assert [chunk.chunk_id for chunk in chunks] == ["c1", "c2"]
    assert [chunk.model_dump().get("graph_boosted", _MISSING) for chunk in chunks] == [
        False,
        True,
    ]


def test_graph_seed_fields_reach_the_journal_record(
    httpx_mock: HTTPXMock, load_sse_fixture
) -> None:
    _add_seed_response(httpx_mock, load_sse_fixture)
    client = httpx.Client(base_url="http://testserver")
    rec = drive_one(
        client, corpus="test", question=_seed_gold_question(), arm="graph-on"
    )

    assert rec.outcome == "success"
    assert rec.workflow_meta is not None
    dumped = rec.workflow_meta.model_dump()
    assert {key: dumped.get(key, _MISSING) for key in SEED_KEYS} == SEED_FIXTURE_VALUES
    assert rec.snapshot is not None
    flags = [
        c.model_dump().get("graph_boosted", _MISSING)
        for c in rec.snapshot.retrieved_chunks
    ]
    assert flags == [False, True]

    # The journal line is what plans 17 to 19 read back, so the values must survive it.
    reloaded = RunRecord.model_validate_json(rec.model_dump_json())
    assert reloaded.workflow_meta is not None
    reloaded_dump = reloaded.workflow_meta.model_dump()
    assert {
        key: reloaded_dump.get(key, _MISSING) for key in SEED_KEYS
    } == SEED_FIXTURE_VALUES
    assert reloaded.snapshot is not None
    assert [
        c.model_dump().get("graph_boosted", _MISSING)
        for c in reloaded.snapshot.retrieved_chunks
    ] == [False, True]


def test_absent_seed_fields_are_none_not_zero() -> None:
    # A record that predates the fields must stay distinguishable from a measured zero.
    older = WorkflowMetadata.model_validate({"vector_count": 3})
    dumped = older.model_dump()
    assert all(dumped.get(key, _MISSING) is None for key in SEED_KEYS)
    measured = WorkflowMetadata.model_validate({
        "graph_seed_count": 0,
        "graph_path_found": False,
        "graph_seed_document_ids": [],
    })
    dumped = measured.model_dump()
    assert dumped.get("graph_seed_count", _MISSING) == 0
    assert dumped.get("graph_path_found", _MISSING) is False
    assert dumped.get("graph_seed_document_ids", _MISSING) == []


def test_committed_pre_change_journal_loads_with_the_new_fields_unset() -> None:
    # Read-only: the committed journal is never rewritten.
    path = Path("eval/runs/2026-09-09-multihop_rag/journal.jsonl")
    loaded = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if "question_id" not in data:
            continue  # the journal header line
        rec = RunRecord.model_validate(data)
        loaded += 1
        if rec.workflow_meta is not None:
            dumped = rec.workflow_meta.model_dump()
            assert all(dumped.get(key, _MISSING) is None for key in SEED_KEYS)
        if rec.snapshot is not None:
            for chunk in rec.snapshot.retrieved_chunks:
                assert chunk.model_dump().get("graph_boosted", _MISSING) is None
    assert loaded > 0


def test_every_wire_metadata_field_is_mapped_at_each_drive_site() -> None:
    from lancet_eval.journal import WorkflowWireMeta

    # A field the client reads but a drive site forgets to copy is dropped without
    # any error, because the journal model defaults it. Keep both models and all
    # three sites in step.
    assert set(WorkflowMetadata.model_fields) == set(WorkflowWireMeta.model_fields)
    names = set(WorkflowWireMeta.model_fields) | set(SEED_KEYS)
    for site in (
        "eval/src/lancet_eval/run.py",
        "eval/src/lancet_eval/measure.py",
        "eval/scripts/drive_measurement_pass.py",
    ):
        source = Path(site).read_text(encoding="utf-8")
        for name in sorted(names):
            pattern = rf"{name}\s*=\s*outcome\.workflow_meta\.{name}"
            assert re.search(pattern, source), f"{site} does not map {name}"
