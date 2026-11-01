"""Reported secondaries of `answer_usable` by answer kind and evidence (#147, D-286).

A yes/no question's `answer_usable` rewards guessing: a constant Yes scores the gold-Yes
share. These figures split the score by kind, adjust the yes/no part for guessing with
balanced accuracy, and split it by whether the context held every gold fact.
"""

from __future__ import annotations

import pytest

from lancet_eval import answer_kinds
from lancet_eval.corpus import GoldQuestion


def _q(qid: str, answer: str) -> GoldQuestion:
    return GoldQuestion(
        question_id=qid,
        question=f"{qid}?",
        gold_facts=["f"],
        gold_answer=answer,
        evidence_list=[{"fact": "f"}],
    )


YES1, YES2, YES3 = _q("y1", "Yes"), _q("y2", "yes"), _q("y3", " YES ")
NO1 = _q("n1", "No")
OPEN = _q("o1", "Paris")


def test_a_constant_yes_scores_its_gold_share_but_chance_balanced_accuracy() -> None:
    split = answer_kinds.kind_split([(YES1, 1.0), (YES2, 1.0), (YES3, 1.0), (NO1, 0.0)])
    assert split.yes_no.mean == pytest.approx(0.75)
    assert split.balanced_accuracy == pytest.approx(0.5)
    assert split.better_constant == pytest.approx(0.75)


def test_balanced_accuracy_is_the_mean_of_the_two_gold_classes() -> None:
    split = answer_kinds.kind_split([(YES1, 1.0), (YES2, 0.0), (NO1, 1.0), (OPEN, 1.0)])
    assert split.gold_yes.mean == pytest.approx(0.5)
    assert split.gold_no.mean == pytest.approx(1.0)
    assert split.balanced_accuracy == pytest.approx(0.75)


def test_an_abstainer_scores_zero_balanced_accuracy() -> None:
    split = answer_kinds.kind_split([(YES1, 0.0), (NO1, 0.0)])
    assert split.balanced_accuracy == 0.0


def test_open_questions_are_counted_apart_from_yes_no() -> None:
    split = answer_kinds.kind_split([(YES1, 1.0), (OPEN, 0.0), (OPEN, 1.0)])
    assert (split.open.n, split.open.mean) == (2, pytest.approx(0.5))
    assert (split.yes_no.n, split.yes_no.mean) == (1, 1.0)


def test_balanced_accuracy_is_undefined_with_one_gold_class_missing() -> None:
    split = answer_kinds.kind_split([(YES1, 1.0), (OPEN, 1.0)])
    assert split.balanced_accuracy is None
    assert split.gold_no == answer_kinds.Share(0, None)


def test_an_empty_input_has_no_means() -> None:
    split = answer_kinds.kind_split([])
    assert split.yes_no == split.open == answer_kinds.Share(0, None)
    assert split.better_constant is None


def test_the_evidence_split_counts_complete_and_partial_apart() -> None:
    split = answer_kinds.by_evidence([(True, 1.0), (True, 0.0), (False, 0.0)])
    assert split.complete == answer_kinds.Share(2, 0.5)
    assert split.partial == answer_kinds.Share(1, 0.0)
