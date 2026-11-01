"""#164: `score` loads the v1.0 document map only for the arms that read it.

A corpus built on #149's stores (all 609 MultiHop-RAG documents, 2Wiki) has no v1.0
`document_map.json`, so a journal with no unprefixed or `small/` arm scores without one.
"""

from __future__ import annotations

import dataclasses

import pytest
import test_s1_store_arms as s1
from levers_fixture import TOKEN

from lancet_eval import thresholds
from lancet_eval.arms import arm_slug
from lancet_eval.config import S1_STORE, V1_STORE, EvalStore
from lancet_eval.score import ScoreError, score_run

MERGED_ARMS = (s1.MERGED_OFF, s1.MERGED_ON)


def _merged_only(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """The S1 scenario with merged-store arms only and no v1.0 document map."""
    monkeypatch.setattr(s1, "S1_ARMS", MERGED_ARMS)
    run, gold, _ = s1._build(tmp_path, monkeypatch)
    prereg = s1._prereg()
    monkeypatch.setattr(
        thresholds,
        TOKEN,
        dataclasses.replace(
            prereg,
            reference_arm=s1.MERGED_OFF,
            families=(dataclasses.replace(prereg.families[0], arms=(s1.MERGED_ON,)),),
            descriptive_arms=(),
            null_guard_arms=(s1.MERGED_ON,),
        ),
        raising=False,
    )
    seen: list[str] = []

    def load(corpus: str, store: EvalStore = V1_STORE) -> s1._Map:
        seen.append(store.name)
        if store != S1_STORE:
            raise FileNotFoundError(f"no document map for store {store.name!r}")
        return s1._Map(s1.MERGED_DOC)

    monkeypatch.setattr("lancet_eval.score.load_document_map", load)
    return run, gold, seen


def test_a_journal_with_no_v1_arm_scores_without_the_v1_map(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, seen = _merged_only(tmp_path, monkeypatch)
    report = score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    names = {d.name for d in report.dimensions}
    for arm in MERGED_ARMS:
        assert f"answer_usable_p4__{arm_slug(arm)}" in names
    assert set(seen) == {S1_STORE.name}


def test_a_v1_arm_still_needs_the_v1_map(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = s1._build(tmp_path, monkeypatch)

    def load(corpus: str, store: EvalStore = V1_STORE) -> s1._Map:
        if store == V1_STORE:
            raise FileNotFoundError("Document map not found")
        return s1._Map(s1.MERGED_DOC)

    monkeypatch.setattr("lancet_eval.score.load_document_map", load)
    with pytest.raises(ScoreError, match="Could not load document map"):
        score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
