"""Tests for D-34 is_usable and arm provenance predicates."""

from lancet_eval.client import NodeFailed, Notice
from lancet_eval.journal import RunRecord
from lancet_eval.usability import has_arm_provenance, is_usable


def _base_record(**kwargs) -> RunRecord:
    data = {
        "corpus": "test",
        "question_id": "q1",
        "graph_arm": "graph-on",
        "outcome": "success",
        "answer": "Answer",
        "duration_ms": 100.0,
    }
    data.update(kwargs)
    return RunRecord.model_validate(data)


def test_is_usable_basic_and_never_raises() -> None:
    r = _base_record(snapshot=None, workflow_meta=None, node_failures=[], answer=None)
    assert is_usable(r) is True


def test_is_usable_outcome_error_is_unusable() -> None:
    r = _base_record(outcome="error")
    assert is_usable(r) is False


def test_is_usable_hard_failure_retrieve_hybrid_is_unusable() -> None:
    nf = NodeFailed(
        node_name="RetrieveHybrid",
        error_kind=4,
        error_message="failed",
        retryable=False,
    )
    r = _base_record(node_failures=[nf])
    assert is_usable(r) is False


def test_is_usable_hard_failure_assemble_or_generate_is_unusable() -> None:
    for node in ["AssemblePrompt", "GenerateAnswer"]:
        nf = NodeFailed(
            node_name=node,
            error_kind=3,
            error_message="failed",
            retryable=False,
        )
        r = _base_record(node_failures=[nf])
        assert is_usable(r) is False


def test_is_usable_retryable_failure_on_success_is_usable() -> None:
    nf = NodeFailed(
        node_name="GenerateAnswer",
        error_kind=1,
        error_message="timeout",
        retryable=True,
    )
    r = _base_record(outcome="success", node_failures=[nf])
    assert is_usable(r) is True


def test_is_usable_graph_failures_and_notices_are_usable() -> None:
    nf = NodeFailed(
        node_name="ExtractGraphContext",
        error_kind=5,
        error_message="graph error",
        retryable=False,
    )
    notices = [
        Notice(code="GRAPH_TIMEOUT", message="timeout", severity=1, typed_code=2),
        Notice(code="NO_EVIDENCE", message="none", severity=1, typed_code=1),
    ]
    r = _base_record(node_failures=[nf], notices=notices)
    assert is_usable(r) is True


def test_has_arm_provenance() -> None:
    r_valid = _base_record(
        notices=[
            Notice(code="GRAPH_ABLATION", message="", severity=1, typed_code=18)
        ]
    )
    assert has_arm_provenance(r_valid) is True

    r_missing_ablation = _base_record(notices=[])
    assert has_arm_provenance(r_missing_ablation) is False

    r_has_unavailable = _base_record(
        notices=[
            Notice(code="GRAPH_ABLATION", message="", severity=1, typed_code=18),
            Notice(code="GRAPH_UNAVAILABLE", message="", severity=1, typed_code=10),
        ]
    )
    assert has_arm_provenance(r_has_unavailable) is False
