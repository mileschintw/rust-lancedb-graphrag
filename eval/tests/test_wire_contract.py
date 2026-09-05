"""Tests for wire contract conformance and self-contradiction predicate."""

from __future__ import annotations

import pytest

from lancet_eval.client import NodeFailed, Notice, RetrievalSnapshot, StructuredCitation
from lancet_eval.dimensions import (
    NOTICE_CODE_NO_EVIDENCE,
    make_wire_contract_conformance,
)
from lancet_eval.journal import RunRecord, WorkflowWireMeta
from lancet_eval.usability import is_self_contradictory


def test_violation_success_with_hard_retrieve_failure() -> None:
    """Record with success alongside hard RetrieveHybrid failure is a violation."""
    rec = RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm="graph-on",
        outcome="success",
        answer="Answer",
        snapshot=RetrievalSnapshot(
            index_generation="gen-1",
            retrieved_chunks=[
                StructuredCitation(chunk_id="c1", document_id="doc-1", rank=1)
            ],
        ),
        node_failures=[
            NodeFailed(
                node_name="RetrieveHybrid",
                error_kind=4,
                error_message="Hard retrieval failure",
                retryable=False,
            )
        ],
    )
    assert is_self_contradictory(rec) is True


def test_violation_success_empty_answer_with_failures() -> None:
    """Record with success, empty answer, and node failures is a violation."""
    rec = RunRecord(

        corpus="multihop_rag",
        question_id="q1",
        graph_arm="graph-on",
        outcome="success",
        answer="",  # Empty answer
        snapshot=RetrievalSnapshot(
            index_generation="gen-1",
            retrieved_chunks=[
                StructuredCitation(chunk_id="c1", document_id="doc-1", rank=1)
            ],
        ),
        node_failures=[
            NodeFailed(
                node_name="ExtractGraphContext",
                error_kind=5,
                error_message="Graph failed",
                retryable=True,
            )
        ],
    )
    assert is_self_contradictory(rec) is True


def test_violation_success_no_snapshot_and_failed_retrieve() -> None:
    """Record reporting success with no snapshot and failed retrieve is a violation."""
    rec = RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm="graph-on",
        outcome="success",
        answer="Answer",
        snapshot=None,  # No snapshot
        node_failures=[
            NodeFailed(
                node_name="RetrieveHybrid",
                error_kind=4,
                error_message="Retrieve failed",
                retryable=True,
            )
        ],
    )
    assert is_self_contradictory(rec) is True


def test_violation_success_empty_chunks_and_failed_retrieve() -> None:
    """Success with empty-chunk snapshot and failed retrieve is a violation."""
    rec = RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm="graph-on",
        outcome="success",
        answer="Answer",
        snapshot=RetrievalSnapshot(
            index_generation="gen-1",
            retrieved_chunks=[],  # D-33 partial empty snapshot
        ),
        node_failures=[
            NodeFailed(
                node_name="RetrieveHybrid",
                error_kind=4,
                error_message="Retrieve failed",
                retryable=True,
            )
        ],
    )
    assert is_self_contradictory(rec) is True


def test_no_evidence_carveout_is_not_violation() -> None:
    """A completed retrieve returning 0 chunks with NO_EVIDENCE is NOT a violation."""
    rec = RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm="graph-on",
        outcome="success",
        answer="I have no evidence to answer this query.",
        snapshot=RetrievalSnapshot(
            index_generation="gen-1",
            retrieved_chunks=[],  # Found nothing
        ),
        notices=[
            Notice(
                code="NO_EVIDENCE",
                message="No evidence found",
                typed_code=NOTICE_CODE_NO_EVIDENCE,
            )
        ],
        node_failures=[],  # Completed normally, not failed!
    )
    assert is_self_contradictory(rec) is False


def test_violation_degraded_mode_false_with_hard_failure() -> None:
    """Record with degraded_mode=False alongside hard node failure is a violation."""
    rec = RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm="graph-on",
        outcome="success",
        answer="Answer",
        snapshot=RetrievalSnapshot(
            index_generation="gen-1",
            retrieved_chunks=[
                StructuredCitation(chunk_id="c1", document_id="doc-1", rank=1)
            ],
        ),
        node_failures=[
            NodeFailed(
                node_name="AssemblePrompt",
                error_kind=6,
                error_message="Prompt error",
                retryable=False,
            )
        ],
        workflow_meta=WorkflowWireMeta(
            degraded_mode=False,  # Contradicts presence of hard failure
        ),
    )
    assert is_self_contradictory(rec) is True


def test_absent_workflow_meta_tolerated_in_degraded_clause() -> None:
    """Absent workflow_meta is not judged a violation by degraded_mode clause alone."""
    rec = RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm="graph-on",
        outcome="success",
        answer="Answer",
        snapshot=RetrievalSnapshot(
            index_generation="gen-1",
            retrieved_chunks=[
                StructuredCitation(chunk_id="c1", document_id="doc-1", rank=1)
            ],
        ),
        node_failures=[
            NodeFailed(
                node_name="ExtractGraphContext",
                error_kind=5,
                error_message="Graph error",
                retryable=False,
            )
        ],
        workflow_meta=None,  # Pre-06.3.1 record
    )
    # ExtractGraphContext failure is not RetrieveHybrid failure, answer is present,
    # and workflow_meta is None so degraded_mode clause does not fire
    assert is_self_contradictory(rec) is False


def test_healthy_record_is_not_violation() -> None:
    """Healthy record with answer, snapshot and no failures is not a violation."""
    rec = RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm="graph-on",
        outcome="success",
        answer="Valid answer",
        snapshot=RetrievalSnapshot(
            index_generation="gen-1",
            retrieved_chunks=[
                StructuredCitation(chunk_id="c1", document_id="doc-1", rank=1)
            ],
        ),
        node_failures=[],
        workflow_meta=WorkflowWireMeta(degraded_mode=False),
    )
    assert is_self_contradictory(rec) is False


def test_honesty_edge_and_unparseable_violation() -> None:
    """Honest engine failure with error_type=None is NOT a violation.

    Non-null error_type IS a violation.
    Together proves inherited clause is keyed on error_type, not journal outcome.
    """
    honest_engine_failure = RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm="graph-on",
        outcome="error",
        answer=None,
        snapshot=None,
        node_failures=[
            NodeFailed(
                node_name="RetrieveHybrid",
                error_kind=1,
                error_message="Timeout",
                retryable=False,
            )
        ],
        error_type=None,  # Harness parsed stream cleanly; engine reported failure
        error=None,
    )
    assert is_self_contradictory(honest_engine_failure) is False

    harness_parse_break = RunRecord(
        corpus="multihop_rag",
        question_id="q2",
        graph_arm="graph-on",
        outcome="error",
        answer=None,
        snapshot=None,
        error_type="StreamFrameContractError",  # Harness exception / contract break
        error="Stream ended prematurely",
    )
    assert is_self_contradictory(harness_parse_break) is True


def test_ten_record_journal_with_five_honest_failures_scores_one() -> None:
    """Proves wire_contract_conformance scores 1.0 on honest engine failures."""
    records = []

    for i in range(5):
        records.append(
            RunRecord(
                corpus="multihop_rag",
                question_id=f"q_ok_{i}",
                graph_arm="graph-on",
                outcome="success",
                answer="Answer",
                snapshot=RetrievalSnapshot(
                    index_generation="gen-1",
                    retrieved_chunks=[
                        StructuredCitation(chunk_id="c1", document_id="doc-1", rank=1)
                    ],
                ),
                node_failures=[],
                error_type=None,
            )
        )
    for i in range(5):
        records.append(
            RunRecord(
                corpus="multihop_rag",
                question_id=f"q_err_{i}",
                graph_arm="graph-on",
                outcome="error",
                answer=None,
                snapshot=None,
                node_failures=[
                    NodeFailed(
                        node_name="RetrieveHybrid",
                        error_kind=1,
                        error_message="Engine timeout",
                        retryable=False,
                    )
                ],
                error_type=None,  # Honest engine failure
            )
        )

    res = make_wire_contract_conformance(records=records)
    assert res.status == "ok"
    assert res.score == pytest.approx(1.0)
    assert res.detail["conforming_n"] == 10.0
    assert res.detail["violations_n"] == 0.0

