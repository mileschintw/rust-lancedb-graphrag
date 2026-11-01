"""#165: a constant Yes or No answer, scored by `answer_usable` on yes/no questions."""

from __future__ import annotations

import pytest

from lancet_eval import constant_baseline
from lancet_eval.answer_kinds import kind_split
from lancet_eval.corpus import GoldQuestion


def _question(qid: str, answer: str, null: bool = False) -> GoldQuestion:
    facts = [] if null else ["a fact"]
    return GoldQuestion(
        question_id=qid,
        question=f"{qid}?",
        question_type="null_query" if null else "comparison_query",
        gold_facts=facts,
        gold_answer=answer,
        evidence_list=[{"fact": f} for f in facts],
    )


QUESTIONS = [
    _question("y1", "Yes"),
    _question("y2", "yes"),
    _question("n1", "No"),
    _question("o1", "Paris"),
    _question("null", "Insufficient information.", null=True),
]


def test_a_constant_yes_scores_the_gold_yes_share_of_the_yes_no_questions() -> None:
    result = constant_baseline.constant_scores(QUESTIONS)
    assert (result.n_yes, result.n_no) == (2, 1)
    assert result.always_yes == pytest.approx(2 / 3)
    assert result.always_no == pytest.approx(1 / 3)
    assert result.better == pytest.approx(2 / 3)


def test_the_better_constant_agrees_with_answer_kinds() -> None:
    # `answer_kinds` reports the better constant beside the balanced accuracy (#147).
    answers = [(q, 1.0) for q in QUESTIONS if not q.is_null]
    expected = kind_split(answers).better_constant
    assert constant_baseline.constant_scores(QUESTIONS).better == expected


def test_a_pool_without_yes_no_questions_has_no_score() -> None:
    result = constant_baseline.constant_scores([_question("o1", "Paris")])
    assert (result.n_yes, result.n_no, result.always_yes, result.better) == (
        0,
        0,
        None,
        None,
    )


def test_the_markdown_has_a_row_per_pool() -> None:
    text = constant_baseline.render_markdown([
        ("pool", constant_baseline.constant_scores(QUESTIONS))
    ])
    assert "| pool | 4 | 3 | 2 | 1 | 0.667 | 0.333 |" in text
