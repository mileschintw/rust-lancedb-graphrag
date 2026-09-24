"""Tests for lancet_eval.diagnostic: the per-question diagnostic table builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lancet_eval.client import NodeFailed
from lancet_eval.diagnostic import (
    ArmResult,
    DiagnosticError,
    DiagnosticRow,
    _compose_label,
    build_rows,
    classify_record,
    write_table,
)
from lancet_eval.journal import RunRecord

FIXTURES = Path(__file__).parent / "fixtures" / "diagnostic"
GOLD_CHUNKS = FIXTURES / "gold_chunks.jsonl"
JOURNAL_SLICE = FIXTURES / "journal_slice.jsonl"
CORPUS = "multihop_rag"


def _row(rows: list[DiagnosticRow], question_id: str) -> DiagnosticRow:
    for row in rows:
        if row.question_id == question_id:
            return row
    raise AssertionError(f"question_id {question_id!r} not found in built rows")


def test_build_rows_covers_full_corpus_sorted_by_question_id() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS)
    assert len(rows) == 500
    ids = [row.question_id for row in rows]
    assert ids == sorted(ids)


def test_all_in_chunk_question_is_yes_yes() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS)
    row = _row(rows, "mhr-0073ab564e55")

    assert row.is_null is False
    assert row.a_gold_doc_in_map is True
    assert row.b_items == ["in_chunk", "in_chunk"]
    assert row.b_gold_chunk_in_lancedb is True
    assert row.in_gold_in_index_subset is True

    assert row.arms["graph-off"].outcome == "success"
    assert row.arms["graph-on"].outcome == "error"
    # Task 1 defers answer_usable/error_class/final_answer to Task 2.
    assert row.arms["graph-off"].answer_usable is None
    assert row.arms["graph-off"].error_class is None
    assert row.arms["graph-on"].error_class is None
    assert row.e_answer_usable is None


def test_split_item_question_fails_b_and_index_subset() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS)
    row = _row(rows, "mhr-0085f76defbe")

    assert row.is_null is False
    assert row.a_gold_doc_in_map is True
    assert row.b_items == ["in_chunk", "split_across_chunks"]
    # D-63: question-level (b) is yes only when EVERY item is in_chunk.
    assert row.b_gold_chunk_in_lancedb is False
    # A split fact can never be a Recall@4 hit, so it must not enter G.
    assert row.in_gold_in_index_subset is False

    assert row.arms["graph-off"].outcome == "success"
    # No graph-on record exists for this question in the fixture journal.
    assert row.arms["graph-on"].outcome == "not_run"


def test_null_question_has_none_ab_and_excluded_from_subset() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS)
    row = _row(rows, "mhr-0279d4a349c3")

    assert row.is_null is True
    assert row.a_gold_doc_in_map is None
    assert row.b_items == []
    assert row.b_gold_chunk_in_lancedb is None
    # D-72: null questions are always excluded from the G/SC-3 subset.
    assert row.in_gold_in_index_subset is False

    assert row.arms["graph-off"].outcome == "success"
    assert row.arms["graph-on"].outcome == "not_run"


def test_question_with_no_journal_record_is_not_run_on_every_arm() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS)
    row = _row(rows, "mhr-012f1f51ac88")

    assert row.is_null is False
    assert row.a_gold_doc_in_map is True
    assert row.b_gold_chunk_in_lancedb is True
    assert row.in_gold_in_index_subset is True

    assert row.arms["graph-off"].outcome == "not_run"
    assert row.arms["graph-on"].outcome == "not_run"


def test_build_rows_without_journal_leaves_arms_empty() -> None:
    rows = build_rows(CORPUS, None, GOLD_CHUNKS)
    row = _row(rows, "mhr-0073ab564e55")
    assert row.arms == {}
    # (a)/(b) are independent of the journal and still populate.
    assert row.a_gold_doc_in_map is True
    assert row.b_gold_chunk_in_lancedb is True


def test_duplicate_journal_record_raises_diagnostic_error(tmp_path: Path) -> None:
    lines = JOURNAL_SLICE.read_text(encoding="utf-8").splitlines()
    # Duplicate the graph-off record for mhr-0073ab564e55 (line index 1).
    duplicated = lines + [lines[1]]
    dup_path = tmp_path / "journal_with_duplicate.jsonl"
    dup_path.write_text("\n".join(duplicated) + "\n", encoding="utf-8")

    with pytest.raises(DiagnosticError):
        build_rows(CORPUS, dup_path, GOLD_CHUNKS)


def test_write_table_emits_one_jsonl_line_per_row_and_md_header(tmp_path: Path) -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS)
    subset = rows[:5]

    write_table(
        subset,
        tmp_path,
        label="unit-test",
        journal_path=JOURNAL_SLICE,
        gold_chunks_path=GOLD_CHUNKS,
    )

    jsonl_path = tmp_path / "table.jsonl"
    md_path = tmp_path / "table.md"
    assert jsonl_path.is_file()
    assert md_path.is_file()

    jsonl_lines = jsonl_path.read_text(encoding="utf-8").strip("\n").split("\n")
    assert len(jsonl_lines) == len(subset)
    for line, row in zip(jsonl_lines, subset, strict=True):
        parsed = json.loads(line)
        assert parsed["question_id"] == row.question_id

    md_lines = md_path.read_text(encoding="utf-8").splitlines()
    assert md_lines[0] == "unit-test"
    assert "records=5" in md_lines[1]
    assert "question_id" in md_lines[3]
    assert "graph-on outcome" in md_lines[3]
    assert "final_answer_missing (graph-off)" in md_lines[3]


def test_compose_label_discloses_partial_run_with_count() -> None:
    label = _compose_label("pre-reconcile", JOURNAL_SLICE, row_count=500)
    assert "partial-run diagnostic" in label
    assert "n=500" in label
    assert label.startswith("pre-reconcile")


def test_compose_label_passthrough_without_journal() -> None:
    assert _compose_label("pre-reconcile", None, row_count=500) == "pre-reconcile"


def test_compose_label_passthrough_when_journal_not_partial(tmp_path: Path) -> None:
    non_partial = tmp_path / "journal_complete.jsonl"
    header = {"type": "header", "corpus": "multihop_rag", "partial": False}
    non_partial.write_text(json.dumps(header) + "\n", encoding="utf-8")
    assert _compose_label("full-run", non_partial, row_count=500) == "full-run"


def test_arm_result_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ArmResult(arm="graph-off", outcome="success", not_a_real_field=True)  # type: ignore[call-arg]


# --- D-69/RESEARCH §B: classify_record error-class mapping ---


def _base_record(**overrides: object) -> RunRecord:
    fields: dict[str, object] = {
        "corpus": "multihop_rag",
        "question_id": "q-1",
        "graph_arm": "graph-off",
        "outcome": "error",
    }
    fields.update(overrides)
    return RunRecord(**fields)  # type: ignore[arg-type]


def test_classify_record_none_for_success_outcome() -> None:
    record = RunRecord(
        corpus="multihop_rag",
        question_id="q-1",
        graph_arm="graph-off",
        outcome="success",
        answer="Answer: Yes",
    )
    assert classify_record(record) is None


def test_classify_record_citation_basis_mixed() -> None:
    record = _base_record(
        node_failures=[
            NodeFailed(
                node_name="GenerateAnswer",
                error_kind=3,
                error_message="answer basis 'mixed' requires at least one cited evidence ID",
                retryable=False,
            )
        ]
    )
    assert classify_record(record) == "citation_basis_mixed"


def test_classify_record_citation_basis_retrieval() -> None:
    record = _base_record(
        node_failures=[
            NodeFailed(
                node_name="GenerateAnswer",
                error_kind=3,
                error_message="answer basis 'retrieval' requires at least one cited evidence ID",
                retryable=False,
            )
        ]
    )
    assert classify_record(record) == "citation_basis_retrieval"


def test_classify_record_model_only_unsupported() -> None:
    record = _base_record(
        node_failures=[
            NodeFailed(
                node_name="GenerateAnswer",
                error_kind=3,
                error_message="ModelOnly answer basis is not supported on Phase 03 QueryRAG path",
                retryable=False,
            )
        ]
    )
    assert classify_record(record) == "model_only_unsupported"


def test_classify_record_citation_marker_mismatch() -> None:
    record = _base_record(
        node_failures=[
            NodeFailed(
                node_name="GenerateAnswer",
                error_kind=3,
                error_message="mismatch between cited_evidence_ids ({'1'}) and inline markers (set())",
                retryable=False,
            )
        ]
    )
    assert classify_record(record) == "citation_marker_mismatch"


def test_classify_record_node_timeout_error_kind_one() -> None:
    record = _base_record(
        node_failures=[
            NodeFailed(
                node_name="RetrieveHybrid",
                error_kind=1,
                error_message="node timeout",
                retryable=True,
            )
        ]
    )
    assert classify_record(record) == "timeout"


def test_classify_record_harness_deadline_is_timeout() -> None:
    record = _base_record(error_type="StreamDeadlineExceeded", error="exceeded 600.0s")
    assert classify_record(record) == "timeout"


def test_classify_record_read_timeout_is_timeout() -> None:
    record = _base_record(error_type="ReadTimeout", error="read timed out")
    assert classify_record(record) == "timeout"


def test_classify_record_other_error_type_is_transport() -> None:
    record = _base_record(error_type="ConnectError", error="connection refused")
    assert classify_record(record) == "transport"


def test_classify_record_no_node_failure_or_error_type_is_other() -> None:
    record = _base_record()
    assert classify_record(record) == "other"
