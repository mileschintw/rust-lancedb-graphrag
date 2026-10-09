"""Wave 0 (RESEARCH assumption A2): `score --no-judge` and `report` over lever arms.

Synthetic `[split]` journals are built from `arms.ARM_REGISTRY` and the committed
graph-diagnosis selection, so a selection of `none` (branch C) is exercised with its 6
registered arms and branches A and B with 7 (`hybrid+graph-v2` included). Each shape is
also run in a reduced form of the same registered labels, so two arm counts are
exercised in every branch (plan 06.3.6-10 Task 3, D-149, D-153, D-161).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from levers_fixture import (
    ARMS,
    CORPUS,
    DECISIONAL,
    TOKEN,
    Spec,
    default_spec,
    make_prereg,
    make_questions,
    write_corpus,
    write_journal,
)

from lancet_eval import thresholds
from lancet_eval.arms import ARM_REGISTRY, arm_slug
from lancet_eval.client import LEVER_ORDER
from lancet_eval.report import CorpusReport, render_json, render_markdown
from lancet_eval.score import score_run

RERANK = "hybrid+rerank"
ALL_ARM_LABEL = "all-arm P_all, not the decisional population"
REDUCED = tuple(a for a in ARMS if a != "hybrid+all")
SHAPES = {"full": ARMS, "reduced": REDUCED}


def _build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arms: tuple[str, ...],
    spec_fn=default_spec,  # type: ignore[no-untyped-def]
    *,
    n_g: int = 10,
) -> tuple[Path, Path]:
    qs = make_questions(n_g, 5)
    root = tmp_path / "repo"
    gold = write_corpus(root, qs, arms)
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    run = tmp_path / "run"
    write_journal(run, qs, spec_fn, arms)
    return run, gold


def _dim(report: CorpusReport, name: str):  # type: ignore[no-untyped-def]
    found = [d for d in report.dimensions if d.name == name]
    assert len(found) == 1, f"{name}: {len(found)} dimensions"
    return found[0]


def _degrade_rerank(qids: set[str]):  # type: ignore[no-untyped-def]
    def spec(arm: str, qid: str) -> Spec:
        return Spec(degraded=True) if arm == RERANK and qid in qids else Spec()

    return spec


def test_the_arm_lists_come_from_the_registry_and_the_selection() -> None:
    expected = 7 if "graph_v2" in LEVER_ORDER else 6
    assert len(ARMS) == expected
    assert ("hybrid+graph-v2" in ARM_REGISTRY) == ("graph_v2" in LEVER_ORDER)
    assert set(ARMS) <= set(ARM_REGISTRY)
    assert len(REDUCED) == len(ARMS) - 1
    assert all(label in ARM_REGISTRY for label in REDUCED)


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_score_no_judge_writes_one_cell_set_per_arm_in_registry_order_and_report_renders(
    shape, tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    arms = SHAPES[shape]
    run, gold = _build(tmp_path, monkeypatch, arms, _degrade_rerank({"lv-g003"}))
    report = score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    assert (run / "report.json").is_file()
    assert report.metadata.arm_labels == list(arms)
    names = [d.name for d in report.dimensions]
    first_seen = [
        n.removeprefix("answer_usable_p4__")
        for n in names
        if n.startswith("answer_usable_p4__")
    ]
    assert first_seen == [arm_slug(a) for a in ARM_REGISTRY if a in arms]
    for arm in arms:
        for base in ("answer_usable_p4", "paper_hits_at_4", "null_abstention_correctness"):
            assert f"{base}__{arm_slug(arm)}" in names
    # the one degraded rerank record is off-arm: it leaves P_all, and is counted
    p4 = _dim(report, "p4_size")
    assert p4.score == 9.0
    assert p4.detail[f"excluded_provenance__{arm_slug(RERANK)}"] == 1.0
    conformance = _dim(report, "arm_provenance_conformance")
    assert conformance.detail["code_i"] == 1.0
    assert conformance.detail["code_h"] == 0.0
    assert conformance.detail["code_j"] == 0.0
    assert conformance.detail["records_failing_zero_tolerance"] == 0.0
    # P_all is labelled, never the decisional population
    assert ALL_ARM_LABEL in report.metadata.notes
    markdown = render_markdown(report)
    assert ALL_ARM_LABEL in markdown
    assert render_json(report)
    on_disk = CorpusReport.model_validate_json(
        (run / "report.json").read_text(encoding="utf-8")
    )
    assert on_disk.metadata.arm_labels == list(arms)


def test_the_report_command_renders_the_lever_arm_report(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from typer.testing import CliRunner

    from lancet_eval.cli import app

    run, gold = _build(tmp_path, monkeypatch, ARMS)
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    result = CliRunner().invoke(app, ["report", "--run", str(run)])
    assert result.exit_code == 0, result.output
    assert (run / "report.md").is_file()


def test_a_low_p_all_still_writes_report_json_and_keeps_every_pairwise_population(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    # 5 of 10 rerank records degrade: P_all is 5 of 10, far below 0.80, while every
    # other lever's two-arm population is the full 10 (D-161: no all-arm refusal).
    degraded = {f"lv-g00{i}" for i in range(5)}
    run, gold = _build(tmp_path, monkeypatch, ARMS, _degrade_rerank(degraded))
    report = score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    assert (run / "report.json").is_file()
    p4 = _dim(report, "p4_size")
    assert p4.score == 5.0
    assert p4.detail["coverage"] == pytest.approx(0.5)
    assert ALL_ARM_LABEL in report.metadata.notes
    assert "coverage 0.500" in report.metadata.notes
    for arm in DECISIONAL:
        if arm == RERANK:
            assert p4.detail[f"pairwise_join_size__{arm_slug(arm)}"] == 5.0
        else:
            assert p4.detail[f"pairwise_join_size__{arm_slug(arm)}"] == 10.0
    assert render_markdown(report)


def test_the_all_p_all_below_the_floor_still_reads_by_pairwise_populations(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from lancet_eval.lever_comparison import build_lever_comparison

    degraded = {f"lv-g00{i}" for i in range(5)}
    run, gold = _build(tmp_path, monkeypatch, ARMS, _degrade_rerank(degraded))
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    monkeypatch.setattr(thresholds, TOKEN, make_prereg(ARMS), raising=False)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    usable = next(f for f in payload["families"] if f["primary"] == "answer_usable")
    by_arm = {c["arm"]: c for c in usable["comparisons"]}
    assert by_arm[RERANK]["evaluable"] is False
    assert by_arm[RERANK]["n_pairs"] == 5
    for arm in DECISIONAL:
        if arm != RERANK:
            assert by_arm[arm]["evaluable"] is True
            assert by_arm[arm]["n_pairs"] == 10
    assert usable["m"] == len(DECISIONAL)


def test_a_legacy_four_arm_corpus_keeps_its_report_unlabelled(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    legacy = ("dense-only", "bm25-only", "hybrid", "hybrid+graph")
    qs = make_questions(6, 2)
    root = tmp_path / "repo"
    gold = write_corpus(root, qs, legacy, token=None)
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    run = tmp_path / "run"
    write_journal(run, qs, default_spec, legacy)
    report = score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    assert ALL_ARM_LABEL not in report.metadata.notes
    conformance = _dim(report, "arm_provenance_conformance")
    assert set(conformance.detail) == {
        *(f"code_{c}" for c in "abcdefg"),
        "records_checked",
        "records_failing_zero_tolerance",
    }


def test_the_corpus_fixture_names_the_06_3_6_token() -> None:
    assert CORPUS == "levers_split"
    assert json.dumps(list(ARMS))
