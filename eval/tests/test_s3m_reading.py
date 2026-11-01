"""The S3M reading across runs (#148): pairing, K = 2 means, null guard, rule."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lancet_eval import s3m_reading as sr

Y, N = sr.Answer(True, False), sr.Answer(False, False)
ABSTAIN = sr.Answer(False, True)


def _q(gold: str, null: bool = False) -> SimpleNamespace:
    return SimpleNamespace(gold_answer=gold, is_null=null)


def test_k2_means_pair_and_scale_to_integer_diffs() -> None:
    arm = {"a": [Y, Y], "b": [Y, N], "c": [N, N]}
    ref = {"a": [Y, N], "b": [Y, N], "c": [Y, Y]}
    c = sr.compare(arm, ref, ["a", "b", "c"])
    assert (c.n_pairs, c.n_pos, c.n_neg) == (3, 1, 1)
    assert c.delta == pytest.approx((0.5 + 0 - 1) / 3)
    # Integer diffs (x2): +1, 0, -2 -> |sum| = 1; sums over the signs: P(|S| >= 1).
    assert c.p_signflip == pytest.approx(1.0)


def test_a_comparison_below_the_floor_is_not_evaluable() -> None:
    arm = {"a": [Y, Y]}
    ref = {"a": [Y, Y], "b": [Y, Y]}
    c = sr.compare(arm, ref, ["a", "b"])
    assert not c.evaluable and c.delta is None


def test_null_guard_counts_the_abstention_drop() -> None:
    nulls = [f"n{i}" for i in range(10)]
    ref = {q: [ABSTAIN, ABSTAIN] for q in nulls}
    arm = {q: [ABSTAIN, ABSTAIN] for q in nulls}
    assert sr.null_guard(arm, ref, nulls).passes
    arm["n0"] = [N, N]  # a drop of 1.0 on 10 pairs: exactly the margin, passes
    assert sr.null_guard(arm, ref, nulls).passes
    arm["n1"] = [N, ABSTAIN]  # 1.5 > 1.0
    assert not sr.null_guard(arm, ref, nulls).passes
    few = sr.null_guard({"n0": [ABSTAIN]}, ref, nulls)
    assert not few.evaluable and not few.passes


def test_writer_reading_splits_yes_no_from_open() -> None:
    questions = {"a": _q("Yes"), "b": _q("Apple"), "n": _q("", null=True)}
    arm = {"a": [Y, Y], "b": [N, N], "n": [ABSTAIN, ABSTAIN]}
    ref = {"a": [N, N], "b": [Y, Y], "n": [ABSTAIN, ABSTAIN]}
    r = sr.read_writer("haiku-5.5", arm, ref, questions, runs=2)
    assert r.yes_no.delta == 1.0 and r.open.delta == -1.0
    assert r.all.n_questions == 2


def _reading(writer: str, delta: float | None) -> SimpleNamespace:
    return SimpleNamespace(writer=writer, all=SimpleNamespace(delta=delta))


@pytest.mark.parametrize(
    ("deltas", "expected"),
    [
        ({"deepseek": -0.09, "sonnet-5.5": 0.0}, "the writer explains the loss"),
        ({"deepseek": -0.09, "sonnet-5.5": -0.01}, "open"),
        (
            {"deepseek": -0.09, "haiku-5.5": -0.10, "sonnet-5.5": -0.05},
            "the writer does not explain the loss",
        ),
        ({"deepseek": -0.09, "sonnet-5.5": -0.04}, "open"),
        ({"sonnet-5.5": 0.05}, "open"),
    ],
)
def test_the_reading_rule(deltas: dict[str, float], expected: str) -> None:
    assert sr.verdict([_reading(w, d) for w, d in deltas.items()]) == expected
