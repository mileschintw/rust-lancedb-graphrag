"""Tests for retrieval and graph path health dimensions."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from lancet_eval.client import NodeFailed, Notice, RetrievalSnapshot, StructuredCitation
from lancet_eval.dimensions import (
    NOTICE_CODE_GRAPH_TIMEOUT,
    make_bm25_yield,
    make_graph_influence_rate,
    make_graph_latency_ms,
    make_graph_presence_rate,
    make_retrieve_latency_ms,
    make_vector_yield,
)
from lancet_eval.journal import Journal, NodeTiming, RunRecord, WorkflowWireMeta
from lancet_eval.score import score_run
from lancet_eval.stats import percentile


def test_percentile_empty_raises_value_error() -> None:
    """Proves percentile on empty list raises ValueError and not IndexError."""
    with pytest.raises(ValueError, match="must not be empty"):
        percentile([], 0.5)


def test_percentile_calculations() -> None:
    """Test percentile interpolation and boundary conditions."""
    assert percentile([5.0], 0.5) == 5.0
    assert percentile([0.0, 10.0], 0.5) == 5.0
    assert percentile([0.0, 1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    assert percentile([10.0, 20.0], 0.95) == 19.5


def test_shared_retrieval_percentile_pair_in_one_place() -> None:
    """Asserts shared retrieval latency pair is computed once in make_vector_yield.

    Proves make_vector_yield accepts retrieve_latencies and score.py does not
    contain a second percentile call for the retrieval node.
    """
    import lancet_eval.score as score_module

    sig = inspect.signature(make_vector_yield)
    assert "retrieve_latencies" in sig.parameters

    # Check score.py source has no second percentile call
    source = inspect.getsource(score_module)
    # percentile should not be called in score.py for retrieve
    assert source.count("percentile(") == 0


def test_bm25_yield_scoring_and_wilson_bounds() -> None:
    """Builds usable records where half carry positive BM25 count."""
    records = [
        RunRecord(
            corpus="multihop_rag",
            question_id=f"q{i}",
            graph_arm="graph-on",
            outcome="success",
            workflow_meta=WorkflowWireMeta(
                bm25_count=1 if i % 2 == 0 else 0,
            ),
        )
        for i in range(10)
    ]
    res = make_bm25_yield(records=records)
    assert res.status == "ok"
    assert res.score == pytest.approx(0.5)
    assert res.detail["ci_lower"] < 0.5 < res.detail["ci_upper"]
    assert res.detail["mean_count"] == 0.5


def test_missing_workflow_meta_in_yield() -> None:
    """Asserts usable record lacking workflow_meta raises missing_meta_n by 1.

    It does not lower the yield score.
    """
    records = [
        RunRecord(
            corpus="multihop_rag",
            question_id="q1",
            graph_arm="graph-on",
            outcome="success",
            workflow_meta=WorkflowWireMeta(bm25_count=5),
        ),
        RunRecord(
            corpus="multihop_rag",
            question_id="q2",
            graph_arm="graph-on",
            outcome="success",
            workflow_meta=None,  # Missing meta
        ),
    ]
    res = make_bm25_yield(records=records)
    assert res.status == "ok"
    assert res.score == 1.0  # 1 out of 1 evaluated is positive
    assert res.detail["missing_meta_n"] == 1.0
    assert res.detail["n_eval"] == 1.0


def test_missing_retrieve_timing() -> None:
    """Asserts usable record lacking RetrieveHybrid timing raises missing_timing_n by 1.

    It is absent from the p50 input.
    """
    records = [
        RunRecord(
            corpus="multihop_rag",
            question_id="q1",
            graph_arm="graph-on",
            outcome="success",
            node_timings=[NodeTiming(node_name="RetrieveHybrid", duration_ms=100.0)],
        ),
        RunRecord(
            corpus="multihop_rag",
            question_id="q2",
            graph_arm="graph-on",
            outcome="success",
            node_timings=[],  # Missing timing
        ),
    ]
    res = make_retrieve_latency_ms(records=records)
    assert res.status == "ok"
    assert res.score == 100.0
    assert res.detail["missing_timing_n"] == 1.0
    assert res.detail["n_eval"] == 1.0


def test_all_missing_retrieve_timing_skipped() -> None:
    """Asserts that when all records lack RetrieveHybrid timing, status is skipped."""
    records = [
        RunRecord(
            corpus="multihop_rag",
            question_id="q1",
            graph_arm="graph-on",
            outcome="success",
            node_timings=[],
        )
    ]
    res = make_retrieve_latency_ms(records=records)
    assert res.status == "skipped"
    assert res.score is None
    assert res.detail["missing_timing_n"] == 1.0


def test_vector_and_bm25_identical_retrieve_p50() -> None:
    """Asserts vector_yield and bm25_yield report identical retrieve_p50_ms."""
    latencies = [50.0, 100.0, 150.0]
    records = [
        RunRecord(
            corpus="multihop_rag",
            question_id="q1",
            graph_arm="graph-on",
            outcome="success",
            workflow_meta=WorkflowWireMeta(vector_count=2, bm25_count=3),
        )
    ]
    v_res = make_vector_yield(records=records, retrieve_latencies=latencies)
    b_res = make_bm25_yield(records=records, retrieve_latencies=latencies)
    assert v_res.detail["retrieve_p50_ms"] == b_res.detail["retrieve_p50_ms"] == 100.0
    assert v_res.detail["retrieve_p95_ms"] == b_res.detail["retrieve_p95_ms"] == 145.0


def test_graph_presence_rate_excludes_graph_off() -> None:
    """Builds 10 graph-on and 10 graph-off records; asserts denominator is 10."""
    records = []
    for i in range(10):
        records.append(
            RunRecord(
                corpus="multihop_rag",
                question_id=f"q_on_{i}",
                graph_arm="graph-on",
                outcome="success",
                workflow_meta=WorkflowWireMeta(graph_node_count=2, graph_edge_count=1),
            )
        )
        records.append(
            RunRecord(
                corpus="multihop_rag",
                question_id=f"q_off_{i}",
                graph_arm="graph-off",
                outcome="success",
                workflow_meta=WorkflowWireMeta(graph_node_count=0, graph_edge_count=0),
            )
        )
    res = make_graph_presence_rate(records=records)
    assert res.status == "ok"
    assert res.score == 1.0
    assert res.n == 10  # Only graph-on
    assert res.detail["n_eval"] == 10.0


def test_graph_presence_floor_miss_is_flag_not_error() -> None:
    """Presence rate below 0.20 yields ok status with floor_miss == 1.0."""
    records = [
        RunRecord(
            corpus="multihop_rag",
            question_id=f"q{i}",
            graph_arm="graph-on",
            outcome="success",
            workflow_meta=WorkflowWireMeta(
                graph_node_count=1 if i == 0 else 0,
                graph_edge_count=0,
            ),
        )
        for i in range(10)
    ]
    res = make_graph_presence_rate(records=records)
    assert res.status == "ok"
    assert res.score == pytest.approx(0.10)
    assert res.detail["floor_miss"] == 1.0
    assert res.detail["investigation_floor"] == 0.20


def test_all_empty_graph_does_not_fail_score_run(tmp_path: Path) -> None:
    """Scoring all-empty-graph records produces no error status on graph emptiness."""
    from lancet_eval.corpus import load_sample_questions
    from lancet_eval.seed import load_document_map

    doc_map = load_document_map("multihop_rag")
    doc_id = next(iter(doc_map.entries.keys()))
    questions = [q for q in load_sample_questions("multihop_rag") if not q.is_null]

    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for i in range(5):
        journal.append(
            RunRecord(
                corpus="multihop_rag",
                question_id=questions[i].question_id,
                graph_arm="graph-on",
                outcome="success",
                answer="Answer",
                index_generation="gen-1",
                snapshot=RetrievalSnapshot(
                    index_generation="gen-1",
                    retrieved_chunks=[
                        StructuredCitation(chunk_id="c1", document_id=doc_id, rank=1)
                    ],
                ),
                workflow_meta=WorkflowWireMeta(
                    vector_count=2,
                    bm25_count=2,
                    graph_node_count=0,
                    graph_edge_count=0,
                ),
            )
        )

    report = score_run(run_dir=tmp_path, no_judge=True)
    presence_dim = next(d for d in report.dimensions if d.name == "graph_presence_rate")
    assert presence_dim.status == "ok"
    assert presence_dim.score == 0.0
    assert presence_dim.detail["floor_miss"] == 1.0


def test_graph_influence_absent_vs_explicit_zero() -> None:
    """Absent influence counter -> skipped; explicit 0 -> ok with score 0.0."""
    absent_records = [
        RunRecord(
            corpus="multihop_rag",
            question_id="q1",
            graph_arm="graph-on",
            outcome="success",
            workflow_meta=WorkflowWireMeta(graph_prompt_fact_count=None),
        )
    ]
    res_absent = make_graph_influence_rate(records=absent_records)
    assert res_absent.status == "skipped"
    assert res_absent.score is None
    assert "graph_prompt_fact_count" in (res_absent.reason or "")

    zero_records = [
        RunRecord(
            corpus="multihop_rag",
            question_id="q1",
            graph_arm="graph-on",
            outcome="success",
            workflow_meta=WorkflowWireMeta(graph_prompt_fact_count=0),
        )
    ]
    res_zero = make_graph_influence_rate(records=zero_records)
    assert res_zero.status == "ok"
    assert res_zero.score == 0.0


def test_graph_latency_excludes_graph_off() -> None:
    """Graph-off record's duration never enters graph_latency_ms."""
    records = [
        RunRecord(
            corpus="multihop_rag",
            question_id="q1",
            graph_arm="graph-on",
            outcome="success",
            node_timings=[
                NodeTiming(node_name="ExtractGraphContext", duration_ms=50.0)
            ],
        ),
        RunRecord(
            corpus="multihop_rag",
            question_id="q2",
            graph_arm="graph-off",
            outcome="success",
            node_timings=[
                NodeTiming(node_name="ExtractGraphContext", duration_ms=9999.0)
            ],
        ),
    ]
    res = make_graph_latency_ms(records=records)
    assert res.status == "ok"
    assert res.score == 50.0
    assert res.n == 1


def test_graph_timeout_included_in_attempt_and_presence() -> None:
    """Graph-on record with graph node failure (timeout) in latency and presence."""
    records = [
        RunRecord(
            corpus="multihop_rag",
            question_id="q1",
            graph_arm="graph-on",
            outcome="success",
            node_timings=[
                NodeTiming(node_name="ExtractGraphContext", duration_ms=250.0)
            ],
            node_failures=[
                NodeFailed(
                    node_name="ExtractGraphContext",
                    error_kind=1,
                    error_message="timeout",
                    retryable=False,
                )
            ],
            workflow_meta=WorkflowWireMeta(
                graph_node_count=0,
                graph_edge_count=0,
            ),
        )
    ]
    lat_res = make_graph_latency_ms(records=records)
    assert lat_res.status == "ok"
    assert lat_res.score == 250.0

    pres_res = make_graph_presence_rate(records=records)
    assert pres_res.status == "ok"
    assert pres_res.score == 0.0


def test_inner_graph_timeout_notice_on_completed_node_is_attempt() -> None:
    """Graph node completed normally, timing present, no failure, GRAPH_TIMEOUT notice.

    Counted as an attempt: appears in graph_latency_ms with real duration and
    in graph_presence_rate as a zero.
    """
    records = [
        RunRecord(
            corpus="multihop_rag",
            question_id="q1",
            graph_arm="graph-on",
            outcome="success",
            node_timings=[
                NodeTiming(node_name="ExtractGraphContext", duration_ms=300.0)
            ],
            node_failures=[],  # Node completed normally!
            notices=[
                Notice(
                    code="GRAPH_TIMEOUT",
                    message="Graph inner timeout",
                    typed_code=NOTICE_CODE_GRAPH_TIMEOUT,
                )
            ],
            workflow_meta=WorkflowWireMeta(
                graph_node_count=0,
                graph_edge_count=0,
            ),
        )
    ]
    lat_res = make_graph_latency_ms(records=records)
    assert lat_res.status == "ok"
    assert lat_res.score == 300.0

    pres_res = make_graph_presence_rate(records=records)
    assert pres_res.status == "ok"
    assert pres_res.score == 0.0
    # GRAPH_TIMEOUT notice prevents counting in completed_graph_records
    assert pres_res.detail["completed_graph_n"] == 0.0


