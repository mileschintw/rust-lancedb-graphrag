"""S2 reader comparison and cost per answered question (#54, D-245, D-252, D-257).

Seam S-F: the #52 fixture S1 run is carried into an S2 run, three reader arms are
appended the way `batch fetch` (#53) will write them, and `score` plus
`compare-levers` read the run. For each reader the comparison reports
`answer_usable` on G, the paired differences and the null guard against every other
reader, and the cost per answered question at the declared sync list price; the
actual batch spend is a separate figure, read from the records' usage.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from itertools import combinations, permutations
from pathlib import Path
from typing import Any

import levers_fixture as fx
import pytest
import replay_fixture as rf

from lancet_eval import measure, thresholds
from lancet_eval.arms import arm_slug
from lancet_eval.journal import RunRecord, WorkflowWireMeta
from lancet_eval.replay import replay_init

HAIKU_ARM = rf.READER_ARM
SONNET_ARM = f"{rf.BASE}@sonnet-5.5"
OPUS_ARM = f"{rf.BASE}@opus-5.5"
READER_ARMS = (HAIKU_ARM, SONNET_ARM, OPUS_ARM)
ALL_ARMS = (rf.BASE, *READER_ARMS)
DECLARED = (("haiku-5.5", rf.HAIKU), ("sonnet-5.5", rf.SONNET), ("opus-5.5", rf.OPUS))
DECLARATION = dict(zip(READER_ARMS, (rf.HAIKU, rf.SONNET, rf.OPUS), strict=True))

#: The usage each reader's records carry; Opus thinks, so its completion tokens hold
#: its 200 reasoning tokens (the provider bills reasoning as output).
USAGE = {
    HAIKU_ARM: (500, 40, 0),
    SONNET_ARM: (500, 40, 0),
    OPUS_ARM: (500, 240, 200),
}
#: G questions each reader answers wrongly; every other G question is answered right.
WRONG_G = {
    HAIKU_ARM: {"lv-g000", "lv-g001"},
    SONNET_ARM: set(),
    OPUS_ARM: {"lv-g000"},
}
#: Null questions each reader answers instead of abstaining.
ANSWERS_NULL = {HAIKU_ARM: {"lv-n000"}, SONNET_ARM: set(), OPUS_ARM: set()}


def _builder(arm: str, usage: tuple[int, int, int] | None = None):  # type: ignore[no-untyped-def]
    prompt, completion, reasoning = usage or USAGE[arm]

    def build(qid: str, qs: fx.Questions, row: Any) -> RunRecord:
        wrong = qid in WRONG_G[arm] or qid in ANSWERS_NULL[arm]
        rec = rf.make_replay_record(
            qid,
            qs,
            row,
            spec=fx.Spec(kind="wrong" if wrong else "ok"),
            reader=DECLARATION[arm],
            arm=arm,
            reasoning_tokens=reasoning,
        )
        return rec.model_copy(
            update={
                "workflow_meta": WorkflowWireMeta(
                    prompt_tokens=prompt, completion_tokens=completion
                )
            }
        )

    return build


def _s2(  # type: ignore[no-untyped-def]
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    prereg: Any = None,
    usage: dict[str, tuple[int, int, int]] | None = None,
    reader_arms: tuple[str, ...] = READER_ARMS,
):
    """An S2 run of the carried deepseek arm and `reader_arms`, plus its gold table."""
    qs = fx.make_questions(10, 5)
    root = tmp_path / "repo"
    gold = fx.write_corpus(root, qs, (rf.BASE, *reader_arms))
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    declared = tuple(
        (name, decl) for name, decl in DECLARED if f"{rf.BASE}@{name}" in reader_arms
    )
    monkeypatch.setattr(
        thresholds,
        fx.TOKEN,
        prereg or rf.s2_prereg(readers=declared, arms=reader_arms),
        raising=False,
    )
    s1 = tmp_path / "s1"
    rf.write_s1_run(s1, qs)
    s2 = tmp_path / "s2"
    replay_init(source_run=s1, arms=[rf.BASE], run=s2)
    for arm in reader_arms:
        rf.append_reader_arm(
            s2, qs, build=_builder(arm, (usage or {}).get(arm)), arm=arm
        )
    return s2, gold, qs


def _score(run: Path, gold: Path) -> None:
    from lancet_eval.score import score_run

    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)


def _compare(run: Path, gold: Path, **kwargs: Any) -> dict[str, Any]:
    from lancet_eval.lever_comparison import build_lever_comparison

    return build_lever_comparison(run, gold_chunks_path=gold, **kwargs)


def _group(payload: dict[str, Any]) -> dict[str, Any]:
    (group,) = payload["reader_comparison"]["groups"]
    return group


def _sync_usd(
    prompt: int, completion: int, input_rate: float, output_rate: float
) -> float:
    return prompt / 1e6 * input_rate + completion / 1e6 * output_rate


# ---- the report on the #52 fixture ---------------------------------------------------


def test_the_report_holds_every_reader_figure_for_three_readers(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    s2, gold, qs = _s2(tmp_path, monkeypatch)
    _score(s2, gold)
    group = _group(_compare(s2, gold))

    assert group["base"] == rf.BASE
    rows = {r["arm"]: r for r in group["readers"]}
    assert list(rows) == list(ALL_ARMS)
    assert [rows[a]["reader"] for a in ALL_ARMS] == [None, *[n for n, _ in DECLARED]]

    n_g = len(qs.g_ids)
    usable = {rf.BASE: n_g, HAIKU_ARM: n_g - 2, SONNET_ARM: n_g, OPUS_ARM: n_g - 1}
    for arm, n_usable in usable.items():
        au = rows[arm]["answer_usable"]
        assert (au["n"], au["n_usable"]) == (n_g, n_usable)
        assert au["mean"] == pytest.approx(n_usable / n_g)

    # Paired differences against every other reader, p reported but not used.
    pairs = {(p["arm"], p["against"]): p for p in group["pairs"]}
    assert set(pairs) == {(b, a) for a, b in combinations(ALL_ARMS, 2)}
    haiku_vs_base = pairs[(HAIKU_ARM, rf.BASE)]
    assert haiku_vs_base["n_pairs"] == n_g
    assert (haiku_vs_base["n_pos"], haiku_vs_base["n_neg"]) == (0, 2)
    assert haiku_vs_base["delta"] == pytest.approx(-0.2)
    assert haiku_vs_base["raw_p"] == pytest.approx(0.5)
    assert pairs[(OPUS_ARM, SONNET_ARM)]["delta"] == pytest.approx(-0.1)
    assert all(p["p_label"] == group["p_label"] for p in group["pairs"])
    assert "not used" in group["p_label"]

    # The null guard of each reader against every other reader.
    guards = {(g["arm"], g["against"]): g for g in group["null_guards"]}
    assert set(guards) == set(permutations(ALL_ARMS, 2))
    haiku_guard = guards[(HAIKU_ARM, SONNET_ARM)]
    assert (haiku_guard["b"], haiku_guard["c"]) == (1, 0)
    assert haiku_guard["n_pairs"] == len(qs.nulls)
    assert (
        guards[(SONNET_ARM, HAIKU_ARM)]["b"],
        guards[(SONNET_ARM, HAIKU_ARM)]["c"],
    ) == (0, 1)


def test_cost_per_answered_question_uses_the_declared_sync_prices(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    s2, gold, qs = _s2(tmp_path, monkeypatch)
    _score(s2, gold)
    rows = {r["arm"]: r for r in _group(_compare(s2, gold))["readers"]}
    n_g = len(qs.g_ids)

    for arm in READER_ARMS:
        price = DECLARATION[arm].price
        assert rows[arm]["price"] == {
            "input_per_mtok": price.input_per_mtok,
            "output_per_mtok": price.output_per_mtok,
            "source": "preregistration",
        }
        prompt, completion, _ = USAGE[arm]
        sync = n_g * _sync_usd(
            prompt, completion, price.input_per_mtok, price.output_per_mtok
        )
        cost = rows[arm]["cost"]
        assert cost["sync_usd"] == pytest.approx(sync)
        assert cost["n_answered"] == rows[arm]["answer_usable"]["n_usable"]
        assert cost["per_answered_usd"] == pytest.approx(sync / cost["n_answered"])

    # The carried deepseek arm is costed at the engine reader's list price.
    base = rows[rf.BASE]
    assert base["price"]["source"] == "measure.GENERATION_*_PRICE_PER_1M"
    per_record = _sync_usd(
        500,
        50,
        measure.GENERATION_INPUT_PRICE_PER_1M,
        measure.GENERATION_OUTPUT_PRICE_PER_1M,
    )
    assert base["cost"]["per_answered_usd"] == pytest.approx(per_record)


def test_a_thinking_on_reader_is_costed_with_its_reasoning_tokens(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    s2, gold, qs = _s2(tmp_path, monkeypatch)
    _score(s2, gold)
    opus = next(
        r for r in _group(_compare(s2, gold))["readers"] if r["arm"] == OPUS_ARM
    )
    without_reasoning = len(qs.g_ids) * _sync_usd(500, 40, 5.0, 25.0)
    assert opus["cost"]["reasoning_tokens"] == 200 * len(qs.g_ids)
    assert opus["cost"]["sync_usd"] == pytest.approx(
        without_reasoning + len(qs.g_ids) * 200 / 1e6 * 25.0
    )


def test_usage_whose_reasoning_exceeds_the_completion_tokens_fails_closed(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from lancet_eval.lever_comparison import LeverComparisonError

    s2, gold, _ = _s2(tmp_path, monkeypatch, usage={OPUS_ARM: (500, 40, 200)})
    with pytest.raises(LeverComparisonError, match="reasoning"):
        _compare(s2, gold)


def test_the_batch_spend_is_a_separate_figure_read_from_the_records(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    usage = {
        HAIKU_ARM: (700, 30, 0),
        SONNET_ARM: (500, 40, 0),
        OPUS_ARM: (500, 240, 200),
    }
    s2, gold, qs = _s2(tmp_path, monkeypatch, usage=usage)
    _score(s2, gold)
    rows = {r["arm"]: r for r in _group(_compare(s2, gold))["readers"]}

    n_records = len(qs.g_ids) + len(qs.nulls)
    for arm in READER_ARMS:
        price = DECLARATION[arm].price
        prompt, completion, _ = usage[arm]
        expected = (
            n_records
            * _sync_usd(prompt, completion, price.input_per_mtok, price.output_per_mtok)
            * measure.BATCH_PRICE_FACTOR
        )
        spend = rows[arm]["batch_spend"]
        assert spend["usd"] == pytest.approx(expected)
        assert spend["n_records"] == n_records
    # The carried deepseek arm was bought in S1, not in a batch.
    assert rows[rf.BASE]["batch_spend"] == {"usd": None, "n_records": 0, "note": "none"}


def test_a_reader_arm_with_no_batch_record_yet_reports_none(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    def errored(qid, qs, row):  # type: ignore[no-untyped-def]
        return rf.make_replay_record(qid, qs, row, spec=fx.Spec(errored=True))

    qs = fx.make_questions(10, 5)
    root = tmp_path / "repo"
    gold = fx.write_corpus(root, qs, (rf.BASE, HAIKU_ARM))
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr(thresholds, fx.TOKEN, rf.s2_prereg(), raising=False)
    s1 = tmp_path / "s1"
    rf.write_s1_run(s1, qs)
    s2 = tmp_path / "s2"
    replay_init(source_run=s1, arms=[rf.BASE], run=s2)
    rf.append_reader_arm(s2, qs, build=errored)
    _score(s2, gold)
    rows = {r["arm"]: r for r in _group(_compare(s2, gold))["readers"]}
    assert rows[HAIKU_ARM]["batch_spend"]["note"] == "none"
    assert rows[HAIKU_ARM]["cost"]["per_answered_usd"] is None


# ---- fail closed ---------------------------------------------------------------------


def test_a_reader_with_no_declared_price_fails_closed(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from lancet_eval.lever_comparison import LeverComparisonError

    s2, gold, _ = _s2(tmp_path, monkeypatch)
    _score(s2, gold)
    undeclared = rf.s2_prereg(readers=DECLARED[:2], arms=READER_ARMS)
    with pytest.raises(LeverComparisonError, match="opus-5.5.*no declared price"):
        _compare(s2, gold, prereg=undeclared)


def test_compute_spend_prices_reader_records_at_the_batch_rate() -> None:
    qs = fx.make_questions(1, 0)
    row = fx.make_evidence_export_row(rf.BASE, "lv-g000", qs)
    from lancet_eval.context_export import ContextExportRow

    source = ContextExportRow.model_validate(row)
    rec = _builder(OPUS_ARM)("lv-g000", qs, source)
    readers = dict(DECLARED)
    spend, _ = measure.compute_spend([rec], include_embeddings=False, readers=readers)
    assert spend == pytest.approx(
        _sync_usd(500, 240, 5.0, 25.0) * measure.BATCH_PRICE_FACTOR
    )
    # An errored batch request carries no usage and is not billed.
    errored = rf.make_replay_record(
        "lv-g000", qs, source, spec=fx.Spec(errored=True), arm=OPUS_ARM
    )
    assert measure.compute_spend([errored], readers=readers) == (0.0, False)


def test_compute_spend_refuses_a_reader_record_with_no_declared_price() -> None:
    qs = fx.make_questions(1, 0)
    from lancet_eval.context_export import ContextExportRow

    source = ContextExportRow.model_validate(
        fx.make_evidence_export_row(rf.BASE, "lv-g000", qs)
    )
    rec = _builder(SONNET_ARM)("lv-g000", qs, source)
    with pytest.raises(measure.ReaderPriceError, match="sonnet-5.5"):
        measure.compute_spend([rec])
    with pytest.raises(measure.ReaderPriceError, match="sonnet-5.5"):
        measure.compute_spend([rec], readers={"haiku-5.5": rf.HAIKU})


# ---- no Hits@4 for reader arms ------------------------------------------------------


def _dicts(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _dicts(value)


def test_the_report_holds_no_hits_at_4_for_reader_arms(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from lancet_eval.lever_comparison import render_markdown

    s2, gold, _ = _s2(tmp_path, monkeypatch)
    _score(s2, gold)

    # score: no Hits@4 dimension of either kind for a reader arm; the base has both.
    report = json.loads((s2 / "report.json").read_text(encoding="utf-8"))
    names = [d["name"] for d in report["dimensions"]]
    for arm in READER_ARMS:
        slug = arm_slug(arm)
        assert not [n for n in names if "hits_at_4" in n and n.endswith(f"__{slug}")]
    base = arm_slug(rf.BASE)
    assert f"paper_hits_at_4__{base}" in names
    assert f"evidence_hits_at_4__{base}" in names

    # compare-levers: no row about a reader arm carries a Hits@4 value.
    payload = _compare(s2, gold)
    for row in _dicts(payload):
        if row.get("arm") in READER_ARMS or row.get("lever") in READER_ARMS:
            held = {k: v for k, v in row.items() if "hits_at_4" in k and v is not None}
            assert not held, (row.get("arm"), row.get("metric"), held)
    assert "## Readers" in render_markdown(payload)
