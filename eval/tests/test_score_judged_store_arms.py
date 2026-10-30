"""The ordered judged pass on store-prefixed arms (#30, D-251).

The ordered judged fixture of `test_score_judged_ordered` is relabelled onto the
store-prefixed arms S1 drives: its four arms run on the small store or the merged store
under labels such as `merged/hybrid`, declared in the corpus's `[stores.*]` tables. The
real judge stage runs against the fake judge and the D-120 sequence is committed in git,
so `score --judged` sees every prefixed arm. No test makes a network call.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_calibration import THRESHOLDS_REL, THRESHOLDS_TEXT, Flow
from test_s1_store_arms import STORES, _prereg
from test_score_judged_ordered import (
    ARMS,
    CORPUS,
    G_IDS,
    NULL_IDS,
    Scenario,
    _boom,
    _git,
    _NoClient,
    judge_fn,
    make_record,
    write_corpus,
)

from lancet_eval import calibration, judge, judge_stage, thresholds
from lancet_eval import score as score_mod
from lancet_eval.arms import arm_slug
from lancet_eval.journal import Journal
from lancet_eval.judge_stage import JudgeStageRecord
from lancet_eval.report import CorpusReport
from lancet_eval.score import JUDGED_DIMENSIONS as JUDGED
from lancet_eval.score import JudgedResult, score_run
from lancet_eval.seed import load_document_map

# Each arm runs on one store. ORDER is in_registry_order: the small store's arms first,
# each store's arms in registry order.
STORE_OF = {
    "dense-only": "merged",
    "bm25-only": "small",
    "hybrid": "small",
    "hybrid+graph": "merged",
}
PREFIXED = {arm: f"{STORE_OF[arm]}/{arm}" for arm in ARMS}
ORDER = ["small/bm25-only", "small/hybrid", "merged/dense-only", "merged/hybrid+graph"]
TOKEN = "PREREGISTRATION_JUDGED_STORE_ARMS_TEST"
# the v1.0 names of a judged delta's reference-arm keys, kept for a `hybrid` reference
V1_REFERENCE_KEYS = (
    "dropped_only_hybrid_abstained",
    "judge_errors_hybrid",
    "abstention_rate_hybrid",
)
# the v1.0 names of every paired delta's reference-arm mean and count (#39)
V1_DELTA_REFERENCE_KEYS = ("mean_hybrid", "count_hybrid")


def _store_prereg() -> Any:
    """#15's synthetic S1 pre-registration, moved onto this fixture's arms."""
    base = _prereg()
    family = replace(
        base.families[0], arms=("merged/dense-only", "merged/hybrid+graph")
    )
    return replace(
        base,
        reference_arm="small/hybrid",
        families=(family,),
        descriptive_arms=("small/bm25-only",),
        null_guard_arms=("merged/dense-only",),
    )


def _build(base: Path, mp: pytest.MonkeyPatch) -> Scenario:
    """The ordered fixture on prefixed arms: stage, emit, scores, reveal, score."""
    root = base / "repo"
    (root / "eval" / "src" / "lancet_eval").mkdir(parents=True)
    gold = write_corpus(root, protocol="ordered", name=CORPUS)
    toml = root / "eval" / "corpora" / f"{CORPUS}.toml"
    bare = ", ".join(f'"{a}"' for a in ARMS)
    # the arms line lists the prefixed labels out of registry order on purpose
    prefixed = ", ".join(f'"{PREFIXED[a]}"' for a in reversed(ARMS))
    text = toml.read_text(encoding="utf-8").replace(
        f"arms = [{bare}]", f"arms = [{prefixed}]"
    )
    toml.write_text(
        text + f'[preregistration]\ntoken = "{TOKEN}"\n' + STORES, encoding="utf-8"
    )
    mp.setattr(thresholds, TOKEN, _store_prereg(), raising=False)
    (root / ".gitignore").write_text("data/\n", encoding="utf-8")
    (root / THRESHOLDS_REL).write_text(
        f"{THRESHOLDS_TEXT}{TOKEN} = 1\n", encoding="utf-8"
    )
    _git(root, "init", "-q")
    _git(root, "add", ".gitignore", THRESHOLDS_REL)
    _git(root, "commit", "-q", "-m", "floor", when=int(time.time()) - 100_000)
    mp.setattr("lancet_eval.corpus._repo_root", lambda: root)
    mp.setenv("OPENROUTER_API_KEY", "sk-test-key-0123456789")
    mp.setattr(judge_stage, "judge_once", judge_fn)
    # both stores map the fixture's one document (the stores' maps are not under test)
    v1_map = load_document_map("multihop_rag")
    mp.setattr(
        "lancet_eval.score.load_document_map", lambda corpus, store=None: v1_map
    )
    run = root / "runs" / "run"
    run.mkdir(parents=True)
    journal = Journal(run / "journal.jsonl")
    journal.write_header(corpus=CORPUS, partial=False)
    for qid in [*G_IDS, *NULL_IDS]:
        for arm in ARMS:
            journal.append(
                make_record(arm, qid).model_copy(update={"graph_arm": PREFIXED[arm]})
            )
    sc = Scenario(root=root, run=run, gold=gold)
    judge_stage.run_judge_stage(run_dir=run, stage_cap=5.0, git_repo=root)
    emitted = calibration.emit_worksheet(
        run, keys_root=root / "data" / "calibration-keys", git_repo=root
    )
    flow = Flow(root, run, emitted)
    flow.commit_worksheet()
    flow.fill_scores(None)
    flow.commit_scores()
    flow.reveal()
    sc.flow = flow
    with mp.context() as spies:
        spies.setattr(score_mod, "judge_once", _boom)
        spies.setattr(judge_stage, "judge_once", _boom)
        spies.setattr(judge, "judge_once", _boom)
        spies.setattr(httpx, "Client", _NoClient)
        score_run(
            run_dir=run,
            no_judge=True,
            judged=True,
            calibration_file=flow.worksheet,
            calibration_key=flow.key_copy,
            git_repo=root,
            gold_chunks_path=gold,
        )
    return sc


@pytest.fixture(scope="module")
def prefixed(tmp_path_factory: pytest.TempPathFactory) -> Any:
    mp = pytest.MonkeyPatch()
    try:
        yield _build(tmp_path_factory.mktemp("judged_store_arms"), mp)
    finally:
        mp.undo()


def test_the_judged_pass_keeps_every_prefixed_arm_in_registry_order(
    prefixed: Scenario,
) -> None:
    sidecar = JudgedResult.model_validate_json(
        (prefixed.run / "judged-result.json").read_text(encoding="utf-8")
    )
    assert [r.arm for r in sidecar.arms] == [a for a in ORDER for _ in JUDGED]
    assert [r.dimension for r in sidecar.arms] == list(JUDGED) * len(ORDER)
    # the deltas are against the pre-registration's reference arm, not `hybrid`
    others = [a for a in ORDER if a != "small/hybrid"]
    assert [r.arm for r in sidecar.deltas] == [a for a in others for _ in JUDGED]
    assert {r.reference for r in sidecar.deltas} == {"small/hybrid"}


def test_every_prefixed_arm_carries_its_judged_dimensions(prefixed: Scenario) -> None:
    report = CorpusReport.model_validate_json(
        (prefixed.run / "report.json").read_text(encoding="utf-8")
    )
    names = {d.name for d in report.dimensions}
    for arm in ORDER:
        for dimension in JUDGED:
            assert f"answer_{dimension}__{arm_slug(arm)}" in names


def test_the_per_arm_agreement_counts_every_prefixed_arm(prefixed: Scenario) -> None:
    sidecar = JudgedResult.model_validate_json(
        (prefixed.run / "judged-result.json").read_text(encoding="utf-8")
    )
    for dimension in JUDGED:
        per_arm = sidecar.agreement["dimensions"][dimension]["per_arm_exact_agreement"]
        assert list(per_arm) == ORDER
        assert sum(c["n"] for c in per_arm.values()) == 20


def test_the_judge_stage_counts_every_prefixed_arm_in_registry_order(
    prefixed: Scenario,
) -> None:
    record = JudgeStageRecord.model_validate_json(
        (prefixed.run / judge_stage.STAGE_FILE).read_text(encoding="utf-8")
    )
    assert list(record.arms) == ORDER
    assert all(c.judgeable > 0 for c in record.arms.values())


def test_a_judged_delta_names_its_reference_arm_neutrally(prefixed: Scenario) -> None:
    # #36: the reference is `small/hybrid`, so its detail keys may not call it `hybrid`
    report = CorpusReport.model_validate_json(
        (prefixed.run / "report.json").read_text(encoding="utf-8")
    )
    prefixes = tuple(f"answer_{dimension}_delta__" for dimension in JUDGED)
    deltas = [d for d in report.dimensions if d.name.startswith(prefixes)]
    assert len(deltas) == (len(ORDER) - 1) * len(JUDGED)
    for d in deltas:
        for v1_name in V1_REFERENCE_KEYS:
            assert v1_name not in d.detail, d.name
        assert "dropped_only_reference_abstained" in d.detail
        assert "judge_errors_reference" in d.detail
        assert "abstention_rate_reference" in d.detail


def test_every_paired_delta_names_its_reference_mean_and_count_neutrally(
    prefixed: Scenario,
) -> None:
    # #39: `_delta_dimension`'s own reference keys follow the same rule as #36's
    report = CorpusReport.model_validate_json(
        (prefixed.run / "report.json").read_text(encoding="utf-8")
    )
    deltas = [d for d in report.dimensions if "_delta__" in d.name and d.status == "ok"]
    assert any(d.name.startswith("answer_") for d in deltas)
    assert any(not d.name.startswith("answer_") for d in deltas)
    counted = [d for d in deltas if "count_x" in d.detail]
    assert counted
    for d in deltas:
        for v1_name in V1_DELTA_REFERENCE_KEYS:
            assert v1_name not in d.detail, d.name
        assert "mean_reference" in d.detail, d.name
    for d in counted:
        assert d.detail["count_delta"] == (
            d.detail["count_x"] - d.detail["count_reference"]
        )
