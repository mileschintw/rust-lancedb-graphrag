"""Tests for the no-judge lever comparison (plan 06.3.6-10, Task 1).

Pure statistics are tested on hand-built vectors; the builder is tested over synthetic
`[split]` journals whose arms come from the registry and whose pre-registration is a
synthetic `LeverPreRegistration` (never the real 06.3.6 constant, which does not exist
until the freeze commit).
"""

from __future__ import annotations

import inspect
import json
import math
from fractions import Fraction
from pathlib import Path

import pytest
from levers_fixture import (
    ARMS,
    CORPUS,
    DECISIONAL,
    TOKEN,
    Questions,
    Spec,
    default_spec,
    make_prereg,
    make_questions,
    write_corpus,
    write_journal,
)

from lancet_eval import gitcheck, lever_comparison, thresholds
from lancet_eval import p4 as p4_mod
from lancet_eval.client import RankedCandidate
from lancet_eval.lever_comparison import (
    LeverComparisonError,
    all_gold_at_4,
    build_lever_comparison,
    coverage_floor_met,
    decide_default,
    evaluate_null_guard,
    holm_fixed_m,
    net_loss_upper_bound,
    transition_counts,
    write_lever_comparison,
)
from lancet_eval.report import CorpusReport, RunMetadata
from lancet_eval.dimensions import DimensionResult

REF = "hybrid"
RERANK = "hybrid+rerank"
METADATA = "hybrid+metadata"
FORMAT = "hybrid+answer-format"


# ---- pure statistics -----------------------------------------------------------------


def test_holm_with_four_comparisons_stops_at_the_second() -> None:
    reject, adjusted = holm_fixed_m(
        (0.004, 0.02, 0.03, 0.5), (True, True, True, True), 0.05
    )
    assert reject == [True, False, False, False]
    assert adjusted == pytest.approx([0.016, 0.06, 0.06, 0.5])


def test_a_non_evaluable_comparison_enters_as_p_one_and_m_stays_four() -> None:
    reject, adjusted = holm_fixed_m(
        (0.001, 0.001, 0.001, 0.0), (True, True, True, False), 0.05
    )
    assert reject == [True, True, True, False]
    # m is 4, not 3: the first adjusted value is 4 x 0.001
    assert adjusted[0] == pytest.approx(0.004)
    assert adjusted[3] == 1.0


def test_the_coverage_floor_is_exact_at_247_and_246_of_308() -> None:
    assert coverage_floor_met(247, 308, 0.80) is True
    assert coverage_floor_met(246, 308, 0.80) is False
    assert Fraction(247, 308) >= Fraction("0.80") > Fraction(246, 308)
    assert coverage_floor_met(0, 308, 0.80) is False
    assert coverage_floor_met(5, 0, 0.80) is False


def test_a_family_of_one_is_an_unadjusted_exact_test() -> None:
    reject, adjusted = holm_fixed_m((0.03,), (True,), 0.05)
    assert reject == [True]
    assert adjusted == [0.03]


def test_no_discordant_pair_gives_p_one() -> None:
    n_pos, n_neg, p = lever_comparison.sign_flip({"a": 1.0, "b": 0.0}, {"a": 1.0, "b": 0.0})
    assert (n_pos, n_neg, p) == (0, 0, 1.0)


@pytest.mark.parametrize(
    ("b", "c", "n_pairs", "passes"),
    [
        (4, 0, 43, True),
        (5, 0, 43, False),
        (5, 1, 43, True),
        (6, 1, 43, False),
        (4, 0, 40, True),
        (5, 0, 40, False),
        (0, 9, 43, True),
    ],
)
def test_guard_one_count_rule(b: int, c: int, n_pairs: int, passes: bool) -> None:
    g = evaluate_null_guard(
        b, c, n_pairs, 43, margin=0.10, min_pair_fraction=0.80, arm=METADATA
    )
    assert g.evaluable is True
    assert g.passes is passes
    assert g.status == ("PASS" if passes else "FAIL")


def test_guard_one_equality_passes_at_exactly_the_margin() -> None:
    # 4 of 40 is exactly 0.10: equality passes (exact fractions, not floats)
    g = evaluate_null_guard(4, 0, 40, 43, margin=0.10, min_pair_fraction=0.80)
    assert Fraction(4, 40) == Fraction("0.10")
    assert g.passes is True


def test_guard_one_fails_closed_below_35_pairs() -> None:
    g = evaluate_null_guard(0, 0, 34, 43, margin=0.10, min_pair_fraction=0.80)
    assert g.min_pairs == 35
    assert g.evaluable is False
    assert g.passes is False
    assert "NOT EVALUABLE" in g.status
    ok = evaluate_null_guard(0, 0, 35, 43, margin=0.10, min_pair_fraction=0.80)
    assert ok.evaluable is True


def test_a_non_decisional_guard_reads_would_pass_or_would_fail() -> None:
    g = evaluate_null_guard(
        5, 0, 43, 43, margin=0.10, min_pair_fraction=0.80, decisional=False
    )
    assert g.status == "would fail"
    g = evaluate_null_guard(
        0, 0, 43, 43, margin=0.10, min_pair_fraction=0.80, decisional=False
    )
    assert g.status == "would pass"


def test_the_net_loss_bound_reproduces_the_ai_spec_figure() -> None:
    # AI-SPEC section 5: d = 4 discordant pairs, three of them a loss, is "3.2
    # questions, 7.5 points" of 43 (stdlib Clopper-Pearson).
    assert net_loss_upper_bound(3, 1, 43) == pytest.approx(0.075, abs=0.002)
    assert net_loss_upper_bound(0, 0, 43) == 0.0
    big = evaluate_null_guard(5, 0, 43, 43, margin=0.10, min_pair_fraction=0.80)
    assert big.ni_label == "non-inferiority not demonstrable at this n"


def test_all_gold_at_4_needs_every_gold_set_in_the_top_four() -> None:
    gold = [frozenset({"a"}), frozenset({"b", "b2"})]
    assert all_gold_at_4(["a", "x", "b2", "y", "z"], gold) is True
    assert all_gold_at_4(["a", "x", "y", "z", "b"], gold) is False
    assert all_gold_at_4(["a", "b"], [frozenset({"a"}), frozenset()]) is False
    assert all_gold_at_4(["a"], []) is False


def test_the_transition_table_reconciles_with_the_delta() -> None:
    pairs = (
        [("abstain", "correct")] * 3
        + [("wrong", "correct")] * 4
        + [("correct", "wrong")] * 2
        + [("correct", "abstain")] * 1
        + [("wrong", "abstain")] * 2
        + [("correct", "correct")] * 5
        + [("wrong", "wrong")] * 6
        + [("abstain", "wrong")] * 1
    )
    t = transition_counts(pairs)
    n_correct_h = sum(1 for h, _ in pairs if h == "correct")
    n_correct_x = sum(1 for _, x in pairs if x == "correct")
    assert n_correct_x - n_correct_h == (
        t["abstain_to_correct"] + t["wrong_to_correct"]
    ) - (t["correct_to_wrong"] + t["correct_to_abstain"])
    assert t["answer_to_abstain"] == 3
    assert t["n"] == len(pairs)


# ---- default decisions ---------------------------------------------------------------

GOOD = {"hybrid SC-1": "PASS", "hybrid SC-2": "PASS", "x SC-1": "PASS", "x SC-2": "PASS"}


def _decide(**over):  # type: ignore[no-untyped-def]
    args = dict(
        in_decisional_family=True,
        evaluable=True,
        rejected=True,
        delta=0.1,
        guard=None,
        provenance_passed=True,
        gate_reads=GOOD,
    )
    args.update(over)
    return decide_default(**args)


def test_a_rejection_with_a_positive_delta_and_passing_gates_is_a_default() -> None:
    assert _decide()[0] == "default"


def test_a_rejection_with_a_negative_delta_is_significantly_worse() -> None:
    assert _decide(delta=-0.1)[0] == "significantly worse, stays off"


def test_no_rejection_or_no_coverage_stays_off() -> None:
    assert _decide(rejected=False)[0] == "stays off: not significant"
    assert _decide(evaluable=False)[0] == "stays off: not evaluable: coverage"


def test_a_non_evaluable_or_failed_guard_on_a_bound_arm_stays_off() -> None:
    pending = evaluate_null_guard(0, 0, 20, 43, margin=0.10, min_pair_fraction=0.80)
    failed = evaluate_null_guard(6, 0, 43, 43, margin=0.10, min_pair_fraction=0.80)
    passing = evaluate_null_guard(0, 0, 43, 43, margin=0.10, min_pair_fraction=0.80)
    assert _decide(guard=pending)[0] == "stays off: guard not evaluable"
    assert _decide(guard=failed)[0] == "stays off: null guard failed"
    assert _decide(guard=passing)[0] == "default"


def test_the_provenance_block_and_gates_gate_a_default() -> None:
    assert _decide(provenance_passed=False)[0] == "stays off: provenance block not passed"
    assert _decide(gate_reads=None)[0] == "stays off: gates not read"
    miss = {**GOOD, "x SC-2": "MISS"}
    decision, reasons = _decide(gate_reads=miss)
    assert decision.startswith("owner disposition")
    assert reasons == ["x SC-2 reads MISS"]


# ---- the builder over synthetic journals ---------------------------------------------


def _minimal_report(run: Path) -> None:
    report = CorpusReport(
        corpus=CORPUS,
        metadata=RunMetadata(
            corpus=CORPUS,
            run_date="2026-10-09T00:00:00+00:00",
            commit_sha="deadbeef",
            generation_model="g",
            embedding_model="e",
            judge_model="j",
            judge_prompt_version="v1",
            index_generation="gen1",
            result_hash="abc",
            arm_labels=list(ARMS),
            dependency_lock_hash="lock",
        ),
        dimensions=[
            DimensionResult(
                name="arm_provenance_conformance",
                status="ok",
                score=1.0,
                detail={"records_failing_zero_tolerance": 0.0},
                n=1,
            )
        ],
    )
    (run / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")


def _setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spec_fn=default_spec,  # type: ignore[no-untyped-def]
    *,
    qs: Questions | None = None,
    arms=ARMS,  # type: ignore[no-untyped-def]
    prereg=None,  # type: ignore[no-untyped-def]
) -> tuple[Path, Path, Questions]:
    qs = qs or make_questions(10, 5)
    root = tmp_path / "repo"
    gold = write_corpus(root, qs, arms)
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr(
        thresholds, TOKEN, prereg or make_prereg(arms), raising=False
    )
    run = tmp_path / "run"
    write_journal(run, qs, spec_fn, arms)
    _minimal_report(run)
    return run, gold, qs


def _row(payload, primary: str, arm: str):  # type: ignore[no-untyped-def]
    fam = next(f for f in payload["families"] if f["primary"] == primary)
    return next(c for c in fam["comparisons"] if c["arm"] == arm)


def _beats(arm: str, qids: set[str]):  # type: ignore[no-untyped-def]
    """`arm` answers wrong everywhere except `qids`; every other arm is right."""

    def spec(a: str, q: str) -> Spec:
        if a == arm and q not in qids:
            return Spec(kind="wrong")
        return Spec()

    return spec


def test_a_clear_lever_win_is_significant_with_a_positive_delta(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    def spec(a: str, q: str) -> Spec:
        # hybrid is wrong on the first 8 G questions, the metadata arm is right
        if a == REF and q in {f"lv-g00{i}" for i in range(8)}:
            return Spec(kind="wrong")
        return Spec()

    run, gold, _ = _setup(tmp_path, monkeypatch, spec)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    row = _row(payload, "answer_usable", METADATA)
    assert row["n_pos"] == 8
    assert row["n_neg"] == 0
    assert row["raw_p"] == pytest.approx(2 / 2**8)
    assert row["decision"] == "significant"
    assert row["delta"] == pytest.approx(0.8)
    assert row["ci_label"] == "unadjusted, estimation only"
    fam = next(f for f in payload["families"] if f["primary"] == "answer_usable")
    assert fam["m"] == len(DECISIONAL)


def test_delta_equals_the_difference_of_means_on_p_x_and_hybrid_is_printed_per_p_x(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = _setup(
        tmp_path, monkeypatch, _beats(FORMAT, {"lv-g000", "lv-g001", "lv-g002"})
    )
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    row = _row(payload, "answer_usable", FORMAT)
    assert row["mean_arm"] == pytest.approx(0.3)
    assert row["mean_reference"] == pytest.approx(1.0)
    assert row["delta"] == pytest.approx(row["mean_arm"] - row["mean_reference"])
    assert row["decision"] == "not significant"
    assert row["n_neg"] == 7
    assert row["n_pos"] == 0


def test_a_rerank_degrade_removes_the_question_from_p_rerank_only(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    def spec(a: str, q: str) -> Spec:
        return Spec(degraded=True) if a == RERANK and q == "lv-g003" else Spec()

    run, gold, qs = _setup(tmp_path, monkeypatch, spec)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    n = len(qs.g_ids)
    assert _row(payload, "answer_usable", RERANK)["n_pairs"] == n - 1
    assert _row(payload, "answer_usable", METADATA)["n_pairs"] == n
    assert _row(payload, "answer_usable", RERANK)["exclusions"]["rerank_degrade"] == 1
    # the intention-to-treat line keeps the degraded record
    itt = payload["sensitivity"]["rerank_itt"]
    assert itt["n_pairs"] == n
    assert itt["label"] == "sensitivity line, decides nothing"
    rerank_ops = [r for r in payload["rerank_operation"] if r["arm"] == RERANK][0]
    assert rerank_ops["degrades"] == 1
    assert rerank_ops["degrades_by_class"]["timeout"] == 1


def test_a_comparison_below_the_floor_is_not_evaluable_and_m_stays(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    # 10 G questions, floor 0.80: 8 pairs pass, 7 do not
    def spec(a: str, q: str) -> Spec:
        if a == RERANK and q in {"lv-g000", "lv-g001", "lv-g002"}:
            return Spec(errored=True)
        return Spec()

    run, gold, _ = _setup(tmp_path, monkeypatch, spec)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    row = _row(payload, "answer_usable", RERANK)
    assert row["n_pairs"] == 7
    assert row["evaluable"] is False
    assert row["decision"] == "not evaluable: coverage"
    assert row["raw_p"] is None
    fam = next(f for f in payload["families"] if f["primary"] == "answer_usable")
    assert fam["m"] == len(DECISIONAL)
    # the other comparisons stand
    assert _row(payload, "answer_usable", METADATA)["evaluable"] is True
    decision = next(d for d in payload["default_decisions"] if d["lever"] == RERANK)
    assert decision["decision"] == "stays off: not evaluable: coverage"

    def spec8(a: str, q: str) -> Spec:
        if a == RERANK and q in {"lv-g000", "lv-g001"}:
            return Spec(errored=True)
        return Spec()

    run2, gold2, _ = _setup(tmp_path / "again", monkeypatch, spec8)
    row8 = _row(build_lever_comparison(run2, gold_chunks_path=gold2), "answer_usable", RERANK)
    assert row8["n_pairs"] == 8
    assert row8["evaluable"] is True


def test_branch_c_shape_has_families_of_three_and_one(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    arms = [a for a in ARMS if a != "hybrid+graph-v2"]
    prereg = make_prereg(arms)
    run, gold, _ = _setup(tmp_path, monkeypatch, arms=arms, prereg=prereg)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    usable = next(f for f in payload["families"] if f["primary"] == "answer_usable")
    hits = next(f for f in payload["families"] if f["primary"] == "paper_hits_at_4")
    assert (usable["m"], hits["m"]) == (3, 1)
    only = hits["comparisons"][0]
    assert only["arm"] == RERANK
    assert only["raw_p"] == 1.0
    assert only["adjusted_p"] == only["raw_p"]


def test_a_hits_at_4_win_alone_never_makes_a_default(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    def spec(a: str, q: str) -> Spec:
        # hybrid misses the gold in the top 4 on 8 questions; rerank finds it
        if a == REF and q in {f"lv-g00{i}" for i in range(8)}:
            return Spec(ranks=(9, 10))
        return Spec()

    run, gold, _ = _setup(tmp_path, monkeypatch, spec)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    assert _row(payload, "paper_hits_at_4", RERANK)["decision"] == "significant"
    assert _row(payload, "answer_usable", RERANK)["decision"] == "not significant"
    decision = next(d for d in payload["default_decisions"] if d["lever"] == RERANK)
    assert decision["decision"] == "stays off: not significant"
    assert decision["hits_at_4_support"] == "significant"
    assert "retrieval claim only" in decision["hits_at_4_note"]


def _null_spec(arm: str, drop: int, n_null: int = 5):  # type: ignore[no-untyped-def]
    """`arm` answers (does not abstain) on the first `drop` nulls; others abstain."""

    def spec(a: str, q: str) -> Spec:
        if a == arm and q.startswith("lv-n") and int(q[4:]) < drop:
            return Spec(kind="answer_yes")
        return Spec()

    return spec


def test_guard_one_reads_the_null_pairs_and_names_the_predicate(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    qs = make_questions(10, 43)
    run, gold, _ = _setup(tmp_path, monkeypatch, _null_spec(FORMAT, 5), qs=qs)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    guard = next(g for g in payload["null_guards"] if g["arm"] == FORMAT)
    assert (guard["b"], guard["c"], guard["n_pairs"]) == (5, 0, 43)
    assert guard["passes"] is False
    assert guard["predicate"] == "metrics.is_abstention"
    assert guard["decisional"] is True
    assert guard["min_pairs"] == 35
    # rerank is not bound: the same reading is would-pass / would-fail
    rerank_guard = next(g for g in payload["null_guards"] if g["arm"] == RERANK)
    assert rerank_guard["decisional"] is False
    assert rerank_guard["status"] == "would pass"
    text = lever_comparison.render_markdown(payload)
    assert "metrics.is_abstention" in text


def test_a_blank_no_evidence_answer_counts_as_an_abstention_in_guard_one(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    qs = make_questions(10, 5)

    def spec(a: str, q: str) -> Spec:
        if q.startswith("lv-n") and a == REF:
            return Spec(kind="answer_yes")
        if q.startswith("lv-n") and a == METADATA:
            return Spec(kind="blank_no_evidence")
        return Spec()

    run, gold, _ = _setup(tmp_path, monkeypatch, spec, qs=qs)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    guard = next(g for g in payload["null_guards"] if g["arm"] == METADATA)
    # hybrid answers on all 5, the metadata arm abstains (NO_EVIDENCE) on all 5: c = 5
    assert (guard["b"], guard["c"]) == (0, 5)
    assert guard["net_loss_rate"] < 0


def test_the_answer_mix_shares_sum_to_one_and_the_twin_baselines_match(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    def spec(a: str, q: str) -> Spec:
        if a == FORMAT and q in {"lv-g000", "lv-g003"}:
            return Spec(kind="abstain")
        if a == FORMAT and q == "lv-g001":
            return Spec(kind="wrong")
        return Spec()

    run, gold, qs = _setup(tmp_path, monkeypatch, spec)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    block = next(b for b in payload["answer_mix"] if b["arm"] == FORMAT)
    for m in block["mix"]:
        assert sum(m["arm"].values()) == pytest.approx(1.0)
        assert sum(m["reference"].values()) == pytest.approx(1.0)
        assert sum(m["gold"].values()) == pytest.approx(1.0)
    binary = next(m for m in block["mix"] if m["subset"] == "binary_gold")
    golds = [qs.gold[q][1].lower() for q in qs.g_ids if qs.gold[q][1] in ("Yes", "No")]
    assert binary["constant_yes_answer_usable"] == pytest.approx(
        golds.count("yes") / len(golds)
    )
    assert binary["constant_no_answer_usable"] == pytest.approx(
        golds.count("no") / len(golds)
    )
    t = block["transitions"]["all"]
    # lv-g000 (Yes): correct -> abstain; lv-g003 (Yes): correct -> abstain;
    # lv-g001 (No): correct -> wrong
    assert t["correct_to_abstain"] == 2
    assert t["correct_to_wrong"] == 1
    row = _row(payload, "answer_usable", FORMAT)
    n = row["n_pairs"]
    assert round(row["delta"] * n) == (
        t["abstain_to_correct"] + t["wrong_to_correct"]
    ) - (t["correct_to_wrong"] + t["correct_to_abstain"])


def test_descriptive_rows_and_sensitivity_lines_decide_nothing(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = _setup(tmp_path, monkeypatch)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    rows = {d["row"]: d for d in payload["descriptive_rows"]}
    assert "hybrid+graph - hybrid" in rows
    assert "hybrid+all - hybrid" in rows
    for d in rows.values():
        assert d["label"] == "descriptive, decides nothing"
    pdec = payload["sensitivity"]["p_dec"]
    assert pdec["label"] == "sensitivity line, decides nothing"
    assert pdec["n_pdec"] == 10
    text = lever_comparison.render_markdown(payload)
    assert "can reach 0.10" in text
    assert "unadjusted, estimation only" in text


def test_the_default_row_is_one_per_lever_and_reads_the_gate_file(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    def spec(a: str, q: str) -> Spec:
        if a == REF and q in {f"lv-g00{i}" for i in range(8)}:
            return Spec(kind="wrong")
        return Spec()

    run, gold, _ = _setup(tmp_path, monkeypatch, spec)
    gates = {
        gate: {a: {"status": "PASS"} for a in (*ARMS, "pooled")}
        for gate in ("SC-1", "SC-2")
    }
    payload = build_lever_comparison(run, gates=gates, gold_chunks_path=gold)
    decisions = {d["lever"]: d for d in payload["default_decisions"]}
    assert set(decisions) == set(DECISIONAL)
    # the null guard of the metadata arm has only 5 nulls: not evaluable
    assert decisions[METADATA]["decision"] == "stays off: guard not evaluable"
    assert decisions[RERANK]["decision"] == "default"
    miss = {**gates, "SC-2": {**gates["SC-2"], RERANK: {"status": "MISS"}}}
    payload = build_lever_comparison(run, gates=miss, gold_chunks_path=gold)
    decisions = {d["lever"]: d for d in payload["default_decisions"]}
    assert decisions[RERANK]["decision"].startswith("owner disposition")
    no_gates = build_lever_comparison(run, gold_chunks_path=gold)
    assert (
        next(d for d in no_gates["default_decisions"] if d["lever"] == RERANK)["decision"]
        == "stays off: gates not read"
    )


# ---- D-73 and the write path ---------------------------------------------------------


def test_write_refuses_and_writes_nothing_when_the_d73_gate_reports_a_problem(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        gitcheck,
        "preregistration_problems",
        lambda *a, **k: ["the commit introducing the token is not older"],
    )
    with pytest.raises(LeverComparisonError, match="D-73"):
        write_lever_comparison(run, gold_chunks_path=gold)
    for name in lever_comparison.OUTPUT_FILES:
        assert not (run / name).exists()


def test_the_gate_receives_the_corpus_token_with_every_check_on(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = _setup(tmp_path, monkeypatch)
    seen: dict[str, object] = {}

    def spy(tokens, **kwargs):  # type: ignore[no-untyped-def]
        seen["tokens"] = tokens
        seen.update(kwargs)
        return []

    monkeypatch.setattr(gitcheck, "preregistration_problems", spy)
    build_lever_comparison(run, gold_chunks_path=gold)
    assert seen["tokens"] == (TOKEN,)
    assert seen["require_clean_tree"] is True
    assert seen["unchanged_since_introduction"] is True
    assert isinstance(seen["created_at"], float)


def test_write_needs_no_judged_result_and_writes_both_files(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = _setup(tmp_path, monkeypatch)
    assert not list(run.glob("judged*"))
    payload = write_lever_comparison(run, gold_chunks_path=gold)
    data = json.loads((run / "lever-comparison.json").read_text(encoding="utf-8"))
    assert data["run"]["judged"] is False
    assert data["families"][0]["primary"] == payload["families"][0]["primary"]
    assert "Holm family" in (run / "lever-comparison.md").read_text(encoding="utf-8")


def test_a_corpus_left_on_the_065_token_is_refused(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    qs = make_questions(10, 5)
    root = tmp_path / "repo"
    gold = write_corpus(root, qs, ARMS, token="PREREGISTRATION_06_3_5")
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    run = tmp_path / "run"
    write_journal(run, qs, default_spec, ARMS)
    _minimal_report(run)
    with pytest.raises(LeverComparisonError):
        build_lever_comparison(run, gold_chunks_path=gold)


def test_the_module_never_names_a_judged_result_file_and_gates_before_it_writes() -> None:
    source = inspect.getsource(lever_comparison)
    assert "judged-result" not in source
    assert source.index("preregistration_problems(") < source.index("open(run / name")
    assert "PREREGISTRATION_06_3_5" not in source


def test_a_pairwise_population_comes_from_build_p4(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = _setup(tmp_path, monkeypatch)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    assert p4_mod.build_p4  # the population builder the plan names
    for fam in payload["families"]:
        for c in fam["comparisons"]:
            assert c["n_pairs"] == 10
            assert math.isclose(c["coverage"], 1.0)


def test_ranked_candidate_import_is_available() -> None:
    assert RankedCandidate.model_fields["chunk_id"] is not None
