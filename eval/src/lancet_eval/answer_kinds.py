"""Reported secondaries of `answer_usable` by answer kind and evidence (#147, D-286).

On a yes/no question `answer_usable` rewards a guess: a constant Yes scores the share of
gold-Yes questions (about 0.66 in S2), so a reader that answers on partial evidence
beats one that abstains. These figures read the score apart, and decide nothing:

* by kind: yes/no questions (``evidence_split.is_yes_no``) and open questions;
* guessing-adjusted, for yes/no only: balanced accuracy, the mean of `answer_usable` on
  gold-Yes and on gold-No questions. Any constant answer scores 0.5 whatever the gold
  mix, and abstaining on every question scores 0. The better constant's share is
  reported beside it for context;
* by evidence: complete when every gold fact is in the reader's context
  (``evidence_split.evidence_complete``), else partial (``by_evidence``).

A frozen pre-registration's decisional metric is unchanged; callers report these only.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from lancet_eval.corpus import GoldQuestion
from lancet_eval.evidence_split import is_yes_no


@dataclass(frozen=True)
class Share:
    """The mean of n 0/1 `answer_usable` values; None when n is 0."""

    n: int
    mean: float | None


@dataclass(frozen=True)
class KindSplit:
    """`answer_usable` by answer kind, with the guessing-adjusted yes/no figure."""

    yes_no: Share
    open: Share
    gold_yes: Share
    gold_no: Share
    #: Mean of `gold_yes` and `gold_no`; None when either class is empty.
    balanced_accuracy: float | None
    #: What the better constant answer (always Yes, or always No) scores on yes/no.
    better_constant: float | None


@dataclass(frozen=True)
class EvidenceSplit:
    """`answer_usable` by whether the context held every gold fact."""

    complete: Share
    partial: Share


def _share(values: list[float]) -> Share:
    return Share(len(values), sum(values) / len(values) if values else None)


def kind_split(answers: Iterable[tuple[GoldQuestion, float]]) -> KindSplit:
    """Splits answers, each a gold question and its `answer_usable`, by kind.

    A value is 0/1, or a question's mean over its K replicates (D-274). `compare-levers`
    passes every replicate's answer, so a question answered K times counts K times;
    `score` passes one replicate mean per question.
    """
    by: dict[str, list[float]] = {"yes": [], "no": [], "open": []}
    for question, value in answers:
        key = question.gold_answer.strip().lower() if is_yes_no(question) else "open"
        by[key].append(float(value))
    yes, no = _share(by["yes"]), _share(by["no"])
    n_yes_no = yes.n + no.n
    return KindSplit(
        yes_no=_share(by["yes"] + by["no"]),
        open=_share(by["open"]),
        gold_yes=yes,
        gold_no=no,
        balanced_accuracy=(
            None if yes.mean is None or no.mean is None else (yes.mean + no.mean) / 2
        ),
        better_constant=max(yes.n, no.n) / n_yes_no if n_yes_no else None,
    )


def by_evidence(answers: Iterable[tuple[bool, float]]) -> EvidenceSplit:
    """Splits answers, each an evidence-complete flag and its 0/1 `answer_usable`."""
    complete: list[float] = []
    partial: list[float] = []
    for is_complete, value in answers:
        (complete if is_complete else partial).append(float(value))
    return EvidenceSplit(complete=_share(complete), partial=_share(partial))
