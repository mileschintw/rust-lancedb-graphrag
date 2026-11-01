"""#168: the paired reader difference by an exact sign-flip test, its inverted
interval, the question-level bootstrap and, for contrast, the normal approximation."""

from __future__ import annotations

import math
from fractions import Fraction

import pytest

from lancet_eval import paired_ci
from lancet_eval.corpus import GoldQuestion
from lancet_eval.journal import RunRecord
from lancet_eval.stats import bootstrap_mean_ci, exact_signflip_p

BASE = "full/hybrid+rerank+metadata"
OPUS = f"{BASE}@opus-5.5"


def _question(qid: str, answer: str, null: bool = False) -> GoldQuestion:
    facts = [] if null else ["a fact"]
    return GoldQuestion(
        question_id=qid,
        question=f"{qid}?",
        question_type="null_query" if null else "comparison",
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
    "q1": _question("q1", "Paris"),
    "q2": _question("q2", "Rome"),
    "q3": _question("q3", "Oslo"),
    "qn": _question("qn", "Insufficient information", null=True),
}


def test_usable_is_kept_per_reader_question_and_replicate() -> None:
    records = [
        _record("q1", BASE, "Answer: Paris"),
        _record("q1", BASE, "Answer: Lyon", replicate=2),
        _record("q2", BASE, "", ok=False),
        _record("qn", BASE, "Answer: Insufficient information"),
        _record("q1", OPUS, "Answer: Paris"),
    ]
    usable = paired_ci.usable_by_replicate(records, QUESTIONS)
    assert usable == {
        "deepseek": {"q1": {1: 1.0, 2: 0.0}},
        "opus-5.5": {"q1": {1: 1.0}},
    }


def test_diffs_pair_the_shared_questions_and_average_each_side() -> None:
    reader = {"q1": {1: 1.0}, "q2": {1: 0.0}, "q3": {1: 1.0}}
    base = {"q1": {1: 1.0, 2: 0.0}, "q2": {1: 1.0, 2: 1.0}}
    assert paired_ci.paired_diffs(reader, base) == [Fraction(1, 2), Fraction(-1)]
    # One base replicate alone, for the K sensitivity.
    assert paired_ci.paired_diffs(reader, base, base_replicate=2) == [1, -1]


def test_the_permutation_p_is_exact_and_matches_mcnemar_on_unit_diffs() -> None:
    diffs = [Fraction(1)] * 8 + [Fraction(-1)] + [Fraction(0)] * 11
    result = paired_ci.paired_interval(diffs, draws=2_000)
    assert result.n == 20
    assert result.mean == pytest.approx(7 / 20)
    assert result.permutation_p == exact_signflip_p(8, 1)


def test_the_bootstrap_interval_is_the_repo_percentile_bootstrap() -> None:
    diffs = [Fraction(1)] * 6 + [Fraction(-1, 2)] * 3 + [Fraction(0)] * 11
    result = paired_ci.paired_interval(diffs, draws=2_000)
    _, lo, hi = bootstrap_mean_ci([float(d) for d in diffs])
    assert result.bootstrap_ci == (lo, hi)


def test_the_normal_interval_is_mean_plus_or_minus_196_standard_errors() -> None:
    diffs = [Fraction(1), Fraction(0), Fraction(0), Fraction(-1)]
    result = paired_ci.paired_interval(diffs, draws=500)
    # Sample sd is sqrt(2/3); the standard error is sqrt(2/3)/2.
    half = 1.96 * (2 / 3) ** 0.5 / 2
    assert result.normal_ci == pytest.approx((-half, half))
    # Four questions: the sign-flip test cannot reject below p = 1/8 anywhere.
    assert result.permutation_ci == (-math.inf, math.inf)


def test_the_inverted_permutation_interval_brackets_the_mean_and_excludes_zero() -> (
    None
):
    # 30 questions, the reader wins 14 and loses 2: far from 0.
    diffs = [Fraction(1)] * 14 + [Fraction(-1)] * 2 + [Fraction(0)] * 14
    result = paired_ci.paired_interval(diffs, draws=5_000)
    lo, hi = result.permutation_ci
    assert 0 < lo < result.mean < hi < 1
    # It is about as wide as the bootstrap interval on the same diffs.
    b_lo, b_hi = result.bootstrap_ci
    assert abs((hi - lo) - (b_hi - b_lo)) < 0.12


def test_a_zero_mean_gets_a_p_of_one_and_an_interval_around_zero() -> None:
    diffs = [Fraction(1)] * 5 + [Fraction(-1)] * 5 + [Fraction(0)] * 10
    result = paired_ci.paired_interval(diffs, draws=2_000)
    assert result.permutation_p == 1
    lo, hi = result.permutation_ci
    assert lo < 0 < hi
