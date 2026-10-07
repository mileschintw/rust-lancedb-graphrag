"""Tests for strata.py: D-40 per-question_type strata as float detail keys."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from lancet_eval import strata
from lancet_eval.p4 import paired_delta
from lancet_eval.stats import (
    BOOTSTRAP_B,
    BOOTSTRAP_SEED,
    bootstrap_mean_ci,
    percentile,
    wilson_ci,
)
from lancet_eval.strata import (
    STRATUM_TYPES,
    constant_yes_baselines,
    paired_delta_strata,
    type_strata,
)
from lancet_eval.thresholds import COMMITTED_THRESHOLDS

THRESHOLD = COMMITTED_THRESHOLDS.min_stratum_cell_size
CMP = "comparison_query"
INF = "inference_query"
TMP = "temporal_query"


def _ids(prefix: str, n: int) -> list[str]:
    return [f"{prefix}{i:03d}" for i in range(n)]


def _of(qids: list[str], qtype: str) -> dict[str, str]:
    return dict.fromkeys(qids, qtype)


def test_the_stratum_types_are_the_three_g_types() -> None:
    assert STRATUM_TYPES == (CMP, INF, TMP)


def test_below_the_cell_size_a_stratum_carries_n_and_value_but_no_ci() -> None:
    qids = _ids("a", THRESHOLD - 1)
    values = {q: float(i % 2) for i, q in enumerate(qids)}
    out = type_strata(values, _of(qids, CMP), interval="wilson")
    assert out[f"type_{CMP}_n"] == float(THRESHOLD - 1)
    assert out[f"type_{CMP}_value"] == pytest.approx(sum(values.values()) / len(qids))
    assert not [k for k in out if "_ci_" in k]


def test_at_the_cell_size_a_wilson_stratum_gains_both_ci_keys() -> None:
    qids = _ids("a", THRESHOLD)
    values = {q: float(i % 3 == 0) for i, q in enumerate(qids)}
    out = type_strata(values, _of(qids, INF), interval="wilson")
    _, lo, hi = wilson_ci(round(sum(values.values())), THRESHOLD)
    assert out[f"type_{INF}_ci_lower"] == pytest.approx(lo)
    assert out[f"type_{INF}_ci_upper"] == pytest.approx(hi)


def test_a_bootstrap_stratum_uses_the_percentile_bootstrap_at_the_fixed_seed() -> None:
    qids = _ids("a", THRESHOLD)
    values = {q: i * 0.37 for i, q in enumerate(qids)}
    out = type_strata(values, _of(qids, TMP), interval="bootstrap")
    _, lo, hi = bootstrap_mean_ci(
        [values[q] for q in sorted(qids)], seed=BOOTSTRAP_SEED, b=BOOTSTRAP_B
    )
    assert out[f"type_{TMP}_ci_lower"] == lo
    assert out[f"type_{TMP}_ci_upper"] == hi


def test_interval_none_never_emits_a_ci_key() -> None:
    qids = _ids("a", THRESHOLD + 5)
    values = {q: float(i) for i, q in enumerate(qids)}
    out = type_strata(values, _of(qids, CMP), interval="none")
    assert f"type_{CMP}_value" in out
    assert not [k for k in out if "_ci_" in k]


@pytest.mark.parametrize(("statistic", "q"), [("p50", 0.50), ("p95", 0.95)])
def test_a_percentile_statistic_reports_the_percentile_as_the_value(
    statistic: str, q: float
) -> None:
    qids = _ids("a", THRESHOLD + 3)
    values = {qid: float(i * i) for i, qid in enumerate(qids)}
    out = type_strata(
        values, _of(qids, CMP), statistic=statistic, interval="none"  # type: ignore[arg-type]
    )
    want = percentile(list(values.values()), q)
    assert out[f"type_{CMP}_value"] == pytest.approx(want)


def test_summarize_reads_the_mean_and_the_percentiles_of_the_values() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 9.0]
    assert strata.summarize(xs) == pytest.approx(3.8)
    assert strata.summarize(xs, "p50") == pytest.approx(percentile(xs, 0.50))
    assert strata.summarize(xs, "p95") == pytest.approx(percentile(xs, 0.95))
    with pytest.raises(ValueError, match="empty"):
        strata.summarize([])


def test_a_type_with_no_value_emits_a_zero_n_and_no_value_key() -> None:
    qids = _ids("a", 3)
    out = type_strata({q: 1.0 for q in qids}, _of(qids, CMP), interval="wilson")
    assert out[f"type_{INF}_n"] == 0.0
    assert out[f"type_{TMP}_n"] == 0.0
    assert f"type_{INF}_value" not in out
    assert f"type_{TMP}_value" not in out


def test_every_returned_value_is_a_float() -> None:
    qids = _ids("a", THRESHOLD)
    values = {q: 1 for q in qids}  # ints in, floats out
    out = type_strata(values, _of(qids, CMP), interval="wilson")  # type: ignore[arg-type]
    assert out
    assert all(type(v) is float for v in out.values())


def test_the_strata_n_values_sum_to_the_number_of_values() -> None:
    qids = _ids("a", 9)
    qtype_of = {**_of(qids[:4], CMP), **_of(qids[4:7], INF), **_of(qids[7:], TMP)}
    out = type_strata({q: 0.0 for q in qids}, qtype_of, interval="none")
    assert sum(out[f"type_{t}_n"] for t in STRATUM_TYPES) == 9.0


@pytest.mark.parametrize("bad", ["null_query", "unknown"])
def test_a_question_outside_the_three_types_raises_naming_it(bad: str) -> None:
    with pytest.raises(ValueError, match="q-odd"):
        type_strata({"q-odd": 1.0}, {"q-odd": bad}, interval="none")


def test_a_question_missing_from_the_type_map_raises_naming_it() -> None:
    with pytest.raises(ValueError, match="q-lost"):
        type_strata({"q-lost": 1.0}, {}, interval="none")


def test_a_wilson_stratum_over_non_binary_values_is_refused() -> None:
    qids = _ids("a", 3)
    with pytest.raises(ValueError, match="0/1"):
        type_strata({q: 0.5 for q in qids}, _of(qids, CMP), interval="wilson")


def test_the_constant_yes_share_is_read_per_type_from_the_gold_answers() -> None:
    answers = {"y1": "Yes", "y2": " yes ", "n1": "No", "p1": "Paris"}
    gold = {
        q: SimpleNamespace(gold_answer=a, question_type=CMP)
        for q, a in answers.items()
    }
    out = constant_yes_baselines(list(answers), gold)
    assert out == {f"type_{CMP}_constant_yes_baseline": 0.5}


def test_the_constant_yes_share_covers_exactly_the_question_ids_given() -> None:
    gold = {
        "a": SimpleNamespace(gold_answer="Yes", question_type=CMP),
        "b": SimpleNamespace(gold_answer="No", question_type=CMP),
        "c": SimpleNamespace(gold_answer="Yes", question_type=INF),
    }
    out = constant_yes_baselines(["a", "c"], gold)
    assert out[f"type_{CMP}_constant_yes_baseline"] == 1.0
    assert out[f"type_{INF}_constant_yes_baseline"] == 1.0
    assert f"type_{TMP}_constant_yes_baseline" not in out


def test_the_constant_yes_share_refuses_a_question_outside_the_three_types() -> None:
    gold = {"z": SimpleNamespace(gold_answer="Yes", question_type="null_query")}
    with pytest.raises(ValueError, match="z"):
        constant_yes_baselines(["z"], gold)


def test_paired_delta_strata_gives_the_mean_paired_difference_per_type() -> None:
    qids = _ids("a", 4)
    x = {q: v for q, v in zip(qids, [1.0, 0.0, 1.0, 1.0], strict=True)}
    ref = {q: v for q, v in zip(qids, [0.0, 0.0, 1.0, 0.0], strict=True)}
    out = paired_delta_strata(x, ref, _of(qids, CMP))
    assert out[f"type_{CMP}_n_pairs"] == 4.0
    assert out[f"type_{CMP}_delta"] == pytest.approx(0.5)
    assert not [k for k in out if "_ci_" in k]
    assert out[f"type_{INF}_n_pairs"] == 0.0
    assert f"type_{INF}_delta" not in out
    assert all(type(v) is float for v in out.values())


def test_paired_delta_strata_adds_the_bootstrap_ci_at_the_cell_size() -> None:
    qids = _ids("a", THRESHOLD)
    x = {q: float(i % 4) for i, q in enumerate(qids)}
    ref = {q: float(i % 3) for i, q in enumerate(qids)}
    out = paired_delta_strata(x, ref, _of(qids, TMP))
    want = paired_delta(x, ref)
    assert out[f"type_{TMP}_delta"] == pytest.approx(want.delta)
    assert out[f"type_{TMP}_ci_lower"] == want.ci_lower
    assert out[f"type_{TMP}_ci_upper"] == want.ci_upper


def test_paired_delta_strata_is_one_below_the_cell_size_without_ci() -> None:
    qids = _ids("a", THRESHOLD - 1)
    x = {q: 1.0 for q in qids}
    ref = {q: 0.0 for q in qids}
    out = paired_delta_strata(x, ref, _of(qids, CMP))
    assert not [k for k in out if "_ci_" in k]


def test_paired_delta_strata_refuses_an_unknown_type() -> None:
    with pytest.raises(ValueError, match="q-odd"):
        paired_delta_strata({"q-odd": 1.0}, {"q-odd": 0.0}, {"q-odd": "unknown"})


def test_paired_delta_strata_refuses_value_maps_over_different_questions() -> None:
    with pytest.raises(ValueError, match="same questions"):
        paired_delta_strata({"a": 1.0}, {"b": 1.0}, {"a": CMP, "b": CMP})


def test_the_module_hard_codes_no_cell_size_threshold() -> None:
    source = Path(strata.__file__).read_text(encoding="utf-8")
    assert "min_stratum_cell_size" in source
    assert not re.search(r"(?<![\w.])10(?![\w.])", source)
