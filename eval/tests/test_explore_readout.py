"""#149's by-hand readout: per-reader figures with per-reader K, null questions apart,
and the paired difference against deepseek over the G questions both answered."""

from __future__ import annotations

import pytest

from lancet_eval import explore_readout
from lancet_eval.corpus import GoldQuestion
from lancet_eval.journal import RunRecord

BASE = "full/hybrid+rerank+metadata"
HAIKU = f"{BASE}@haiku-5.5"
SONNET = f"{BASE}@sonnet-5.5"


def _question(qid: str, answer: str, qtype: str, null: bool = False) -> GoldQuestion:
    facts = [] if null else ["a fact"]
    return GoldQuestion(
        question_id=qid,
        question=f"{qid}?",
        question_type=qtype,
        gold_facts=facts,
        gold_answer=answer,
        evidence_list=[{"fact": f} for f in facts],
    )


def _record(qid: str, arm: str, answer: str, replicate: int = 1, ok: bool = True):  # type: ignore[no-untyped-def]
    return RunRecord(
        corpus="c",
        question_id=qid,
        graph_arm=arm,
        outcome="success" if ok else "error",
        answer=answer,
        replicate=replicate,
    )


QUESTIONS = {
    "q1": _question("q1", "Paris", "comparison"),
    "q2": _question("q2", "Rome", "compositional"),
    "qn": _question("qn", "Insufficient information", "null_query", null=True),
}


def _by_reader(records: list[RunRecord]) -> dict[str, explore_readout.ReaderReadout]:
    return {r.reader: r for r in explore_readout.readout(records, QUESTIONS)}


def test_each_reader_is_read_over_all_its_answers_with_its_own_k() -> None:
    records = [
        _record("q1", BASE, "Answer: Paris"),
        _record("q1", BASE, "Answer: Paris", replicate=2),
        _record("q2", BASE, "Answer: Rome"),
        _record("q2", BASE, "Answer: Insufficient information", replicate=2),
        _record("qn", BASE, "Answer: Insufficient information"),
        # Sonnet at K = 1.
        _record("q1", SONNET, "Answer: Paris"),
        _record("q2", SONNET, "Answer: Insufficient information"),
        _record("qn", SONNET, "Answer: Paris"),
        # An error record is no answer.
        _record("q2", HAIKU, "", ok=False),
        _record("q1", HAIKU, "Answer: Lyon"),
    ]
    rows = _by_reader(records)
    deepseek, sonnet, haiku = rows["deepseek"], rows["sonnet-5.5"], rows["haiku-5.5"]
    assert (deepseek.g_answers, deepseek.answer_usable) == (4, 0.75)
    assert deepseek.abstention == 0.25 and deepseek.null_abstention == 1.0
    assert deepseek.paired_delta is None
    assert (sonnet.g_answers, sonnet.answer_usable, sonnet.null_abstention) == (
        2,
        0.5,
        0.0,
    )
    # Per question: q1 1 - 1, q2 0 - 0.5; the mean is -0.25.
    assert sonnet.paired_n == 2
    assert sonnet.paired_delta == pytest.approx(-0.25)
    assert sonnet.by_type == {"comparison": (1, 1.0), "compositional": (1, 0.0)}
    assert (haiku.g_answers, haiku.paired_n, haiku.null_abstention) == (1, 1, None)


def test_the_markdown_has_a_row_per_reader_and_a_column_per_type() -> None:
    rows = explore_readout.readout(
        [_record("q1", BASE, "Answer: Paris"), _record("q2", SONNET, "Answer: Rome")],
        QUESTIONS,
    )
    text = explore_readout.render_markdown(rows)
    assert "| deepseek | 1 | 1 | 1.000 |" in text
    assert "| reader | comparison | compositional |" in text
