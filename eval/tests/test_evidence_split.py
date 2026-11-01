"""The evidence split of a replay run's answers (#143).

Each G question is split by whether every gold fact is in the reader's context
(`metrics.gold_contained`) and by whether its gold answer is yes or no; each reader's
answers are then counted per cell.
"""

from __future__ import annotations

from typing import Any

import pytest

from lancet_eval import evidence_split
from lancet_eval.context_export import ContextExportRow
from lancet_eval.corpus import GoldQuestion
from lancet_eval.journal import RunRecord

BASE = "merged/hybrid+rerank+metadata"


def _question(qid: str, answer: str, facts: list[str]) -> GoldQuestion:
    return GoldQuestion(
        question_id=qid,
        question=f"question {qid}?",
        gold_facts=facts,
        gold_answer=answer,
        evidence_list=[{"fact": f} for f in facts],
    )


def _row(qid: str, *texts: str) -> ContextExportRow:
    entry: dict[str, Any] = {
        "chunk_id": "c",
        "document_id": "d",
        "title": None,
        "section_path": None,
        "content_type": None,
        "score": 1.0,
        "suspicious": False,
        "document_metadata": {
            "source": None,
            "doc_title": None,
            "published_date": None,
        },
    }
    return ContextExportRow(
        corpus="c",
        question_id=qid,
        arm=BASE,
        question=f"question {qid}?",
        evidence=[{**entry, "rank": i, "text": t} for i, t in enumerate(texts, 1)],
        graph_facts=[],
    )


def _record(
    qid: str, arm: str, answer: str | None, replicate: int = 1, ok: bool = True
) -> RunRecord:
    return RunRecord(
        corpus="c",
        question_id=qid,
        graph_arm=arm,
        outcome="success" if ok else "error",
        answer=answer,
        replicate=replicate,
    )


QUESTIONS = {
    # complete: both facts in the context
    "q-yes": _question("q-yes", "Yes", ["the cat sat", "on the mat"]),
    # partial: one of two facts
    "q-open": _question("q-open", "Paris", ["capital is Paris", "a river runs"]),
    # null: never counted
    "q-null": _question("q-null", "Insufficient information", []),
}
ROWS = {
    ("q-yes", BASE): _row("q-yes", "the cat sat", "and stayed on the mat"),
    ("q-open", BASE): _row("q-open", "The capital is Paris."),
    ("q-null", BASE): _row("q-null", "nothing"),
}


def _cells(
    records: list[RunRecord],
) -> dict[tuple[str, str, str], evidence_split.SplitCell]:
    cells = evidence_split.split_cells(records, QUESTIONS, ROWS)
    return {(c.reader, c.evidence, c.kind): c for c in cells}


def test_evidence_is_complete_only_when_every_gold_fact_is_in_the_context() -> None:
    assert evidence_split.evidence_complete(QUESTIONS["q-yes"], ROWS["q-yes", BASE])
    assert not evidence_split.evidence_complete(
        QUESTIONS["q-open"], ROWS["q-open", BASE]
    )


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("Yes", True), (" no ", True), ("Paris", False), ("Yes, twice", False)],
)
def test_a_yes_no_question_has_a_bare_yes_or_no_gold(
    answer: str, expected: bool
) -> None:
    assert evidence_split.is_yes_no(_question("q", answer, ["f"])) is expected


def test_the_reader_is_the_label_after_the_at_or_deepseek_for_the_base() -> None:
    assert evidence_split.reader_of(f"{BASE}@sonnet-5.5") == "sonnet-5.5"
    assert evidence_split.reader_of(BASE) == "deepseek"


def test_answers_are_counted_per_reader_evidence_and_kind() -> None:
    records = [
        _record("q-yes", BASE, "Answer: Yes"),
        _record("q-yes", BASE, "Answer: No", replicate=2),
        _record("q-open", BASE, "Answer: Paris"),
        _record("q-open", BASE, "Answer: insufficient information", replicate=2),
        _record("q-yes", f"{BASE}@opus-5.5", "Answer: insufficient information"),
        _record("q-null", BASE, "Answer: insufficient information"),
    ]
    cells = _cells(records)

    complete = cells["deepseek", "complete", "yes/no"]
    assert (complete.n_questions, complete.n_answers) == (1, 2)
    assert complete.answer_usable == 0.5 and complete.abstention == 0.0

    partial = cells["deepseek", "partial", "open"]
    assert (partial.n_questions, partial.n_answers) == (1, 2)
    assert partial.answer_usable == 0.5 and partial.abstention == 0.5

    every = cells["deepseek", "all", "all"]
    assert (every.n_questions, every.n_answers) == (2, 4)
    assert every.answer_usable == 0.5 and every.abstention == 0.25

    opus = cells["opus-5.5", "complete", "all"]
    assert opus.n_answers == 1 and opus.abstention == 1.0


def test_error_records_and_null_questions_are_left_out() -> None:
    records = [
        _record("q-yes", BASE, "Answer: Yes"),
        _record("q-yes", BASE, None, replicate=2, ok=False),
        _record("q-null", BASE, "Answer: Yes"),
    ]
    every = _cells(records)["deepseek", "all", "all"]
    assert (every.n_questions, every.n_answers) == (1, 1)


def test_a_reader_arm_reads_its_base_arms_context() -> None:
    """A reader arm has no export row of its own: it read the base arm's prompt."""
    records = [_record("q-open", f"{BASE}@haiku-5.5", "Answer: Paris")]
    cells = _cells(records)
    assert cells["haiku-5.5", "partial", "open"].answer_usable == 1.0
    assert ("haiku-5.5", "complete", "open") not in cells


def test_the_table_has_one_line_per_cell() -> None:
    records = [_record("q-yes", BASE, "Answer: Yes")]
    cells = evidence_split.split_cells(records, QUESTIONS, ROWS)
    table = evidence_split.render_markdown(cells, store="merged")
    lines = table.splitlines()
    assert lines[0].startswith("| store | reader | evidence | kind |")
    assert len(lines) == 2 + len(cells)
    assert "| merged | deepseek | complete | yes/no | 1 | 1 | 1.000 | 0.000 |" in lines


def test_moved_questions_are_partial_before_and_complete_after() -> None:
    small = "small/hybrid+rerank+metadata"
    rows = {
        **ROWS,
        ("q-yes", small): _row("q-yes", "the cat sat"),
        ("q-open", small): _row("q-open", "The capital is Paris."),
        ("q-null", small): _row("q-null", "nothing"),
    }
    assert evidence_split.moved_questions(QUESTIONS, rows, small, BASE) == {"q-yes"}
    assert evidence_split.moved_questions(QUESTIONS, rows, BASE, small) == set()


def test_only_keeps_the_named_questions() -> None:
    records = [
        _record("q-yes", BASE, "Answer: Yes"),
        _record("q-open", BASE, "Answer: Paris"),
    ]
    cells = evidence_split.split_cells(records, QUESTIONS, ROWS, only={"q-open"})
    assert {c.n_questions for c in cells} == {1}
    assert {(c.evidence, c.kind) for c in cells} == {
        ("partial", "open"),
        ("partial", "all"),
        ("all", "open"),
        ("all", "all"),
    }


def test_a_run_with_two_base_arms_is_refused() -> None:
    """A reader is named per base arm, so two base arms would pool unlike answers."""
    small = "small/hybrid+rerank+metadata"
    rows = {**ROWS, ("q-yes", small): _row("q-yes", "the cat sat")}
    records = [_record("q-yes", BASE, "Answer: Yes"), _record("q-yes", small, "x")]
    with pytest.raises(ValueError, match="one base arm"):
        evidence_split.split_cells(records, QUESTIONS, rows)
