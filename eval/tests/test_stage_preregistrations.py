"""The v1.1 S0 and S1 stage pre-registrations (D-252, D-253, D-261 to D-264).

Each constant resolves through `preregistration.resolve`, fixes exactly the arms its
corpus drives, and fails closed when a copy of it names an arm the registry does not
know or an external arm without a pipeline. The S1 constants also pass through the lever
comparison, so the chunking reading (against the small store) and the merged-store graph
reading (D-263, against merged graph-off) can both be read from one S1 journal.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from levers_fixture import TOKEN, Spec
from test_s1_store_arms import MERGED_OFF, MERGED_ON, SMALL_OFF, SMALL_ON, _build

from lancet_eval import preregistration, thresholds
from lancet_eval.arms import ExternalPipeline
from lancet_eval.corpus import load_corpus_config
from lancet_eval.lever_comparison import build_lever_comparison
from lancet_eval.score import score_run

STAGE_TOKENS = (
    "PREREGISTRATION_S0",
    "PREREGISTRATION_S1",
    "PREREGISTRATION_S1_MERGED_GRAPH",
)


@pytest.mark.parametrize("token", STAGE_TOKENS)
def test_each_stage_constant_resolves(token: str) -> None:
    pre = preregistration.resolve(token)
    assert isinstance(pre, thresholds.StagePreRegistration)
    assert [f.role for f in pre.families] == ["decisional"]
    assert pre.families[0].primary == "answer_usable"


@pytest.mark.parametrize(
    ("corpus", "token"),
    [
        ("multihop_rag_s0_heldout", "PREREGISTRATION_S0"),
        ("multihop_rag_s1_dev", "PREREGISTRATION_S1"),
    ],
)
def test_the_corpus_names_its_constant_and_drives_exactly_its_arms(
    corpus: str, token: str
) -> None:
    config = load_corpus_config(corpus)
    assert config.preregistration_token == token
    pre = preregistration.resolve(token)
    assert set(config.arms) == set(preregistration.arms_of(pre))


def test_s0_reads_the_heldout_split_and_s1_the_dev_pool() -> None:
    s0 = load_corpus_config("multihop_rag_s0_heldout")
    s1 = load_corpus_config("multihop_rag_s1_dev")
    assert (s0.split_role, s0.questions_file_rel, s0.sample_size) == (
        "heldout",
        "multihop_rag/questions.heldout.jsonl",
        351,
    )
    assert (s1.split_role, s1.questions_file_rel, s1.sample_size) == (
        "dev",
        "multihop_rag/questions.diag.jsonl",
        100,
    )


def test_s0_is_lancet_default_against_llamaindex_with_m_1() -> None:
    pre = thresholds.PREREGISTRATION_S0
    assert pre.reference_arm == "hybrid+rerank+metadata"
    assert pre.families[0].arms == ("llamaindex",)
    assert pre.families[0].alpha == 0.05
    assert pre.null_guard_arms == ("llamaindex",)
    assert preregistration.external_pipelines_of(pre) == {
        "llamaindex": ExternalPipeline(
            framework="llama-index-core",
            framework_version="0.14.25",
            chunk_size=256,
            chunk_overlap=25,
            dense_top_k=20,
            rerank_model="voyageai/rerank-2.5-lite",
            keep=8,
        )
    }


def test_the_merged_graph_reading_differs_from_s1_only_in_its_arms() -> None:
    s1 = thresholds.PREREGISTRATION_S1
    graph = thresholds.PREREGISTRATION_S1_MERGED_GRAPH
    assert s1.reference_arm == SMALL_OFF
    assert s1.families[0].arms == (MERGED_OFF, SMALL_ON)
    assert s1.null_guard_arms == (MERGED_OFF, SMALL_ON)
    assert graph.reference_arm == MERGED_OFF
    assert graph.families[0].arms == (MERGED_ON,)
    assert graph.null_guard_arms == (MERGED_ON,)
    assert set(preregistration.arms_of(s1)) == set(preregistration.arms_of(graph))
    arm_fields = {"reference_arm", "families", "descriptive_arms", "null_guard_arms"}
    for field in dataclasses.fields(s1):
        if field.name not in arm_fields | {"default_rule", "provenance"}:
            assert getattr(s1, field.name) == getattr(graph, field.name), field.name


@pytest.mark.parametrize("token", STAGE_TOKENS)
def test_a_copy_naming_an_undeclared_arm_fails_closed(
    token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pre = getattr(thresholds, token)
    bad = dataclasses.replace(
        pre, descriptive_arms=(*pre.descriptive_arms, "hybrid+undeclared")
    )
    monkeypatch.setattr(thresholds, token, bad)
    with pytest.raises(preregistration.PreregistrationError, match="unknown arm"):
        preregistration.resolve(token)


def test_s0_without_its_llamaindex_pipeline_fails_closed() -> None:
    bare = dataclasses.replace(thresholds.PREREGISTRATION_S0, external_pipelines=())
    with pytest.raises(preregistration.PreregistrationError, match="llamaindex"):
        preregistration.external_pipelines_of(bare)


def test_both_s1_readings_pass_through_the_lever_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, preregistered_clean_tree: str
) -> None:
    wrong_merged_off = {f"lv-g00{i}" for i in range(3)}
    wrong_small_off = {f"lv-g00{i}" for i in range(8)}

    def spec(arm: str, qid: str) -> Spec:
        # small-off is wrong on 8 G questions, merged-off on 3, merged-on on none
        wrong = {SMALL_OFF: wrong_small_off, MERGED_OFF: wrong_merged_off}
        return Spec(kind="wrong") if qid in wrong.get(arm, set()) else Spec()

    run, gold, _ = _build(tmp_path, monkeypatch, spec)
    monkeypatch.setattr(thresholds, TOKEN, thresholds.PREREGISTRATION_S1)
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)

    chunking = build_lever_comparison(run, gold_chunks_path=gold)
    rows = {c["arm"]: c for c in chunking["families"][0]["comparisons"]}
    assert set(rows) == {MERGED_OFF, SMALL_ON}
    assert rows[MERGED_OFF]["delta"] == pytest.approx(0.5)

    graph = build_lever_comparison(
        run,
        gold_chunks_path=gold,
        prereg=thresholds.PREREGISTRATION_S1_MERGED_GRAPH,
    )
    assert graph["run"]["reference_arm"] == MERGED_OFF
    (row,) = graph["families"][0]["comparisons"]
    assert row["arm"] == MERGED_ON
    assert row["delta"] == pytest.approx(0.3)
    guard = {g["arm"]: g for g in graph["null_guards"]}
    assert guard[MERGED_ON]["status"] == "PASS"
