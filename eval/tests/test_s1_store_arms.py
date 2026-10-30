"""Seam S-A for S1 (D-251): four store-prefixed arms pair in one journal.

The small and merged stores' arms live in one `[split]` journal under labels such as
`small/hybrid+rerank+metadata`. `score --no-judge` scores them, reading each arm's
document map from the store its prefix declares, and the lever comparison pairs them
against a pre-registration whose labels carry the same prefixes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from levers_fixture import (
    TOKEN,
    Spec,
    default_spec,
    make_questions,
    make_record,
    write_corpus,
)

from lancet_eval import thresholds
from lancet_eval.arms import arm_slug
from lancet_eval.config import S1_STORE, V1_STORE, EvalStore
from lancet_eval.journal import Journal, RunRecord
from lancet_eval.lever_comparison import build_lever_comparison
from lancet_eval.score import ScoreError, score_run
from lancet_eval.thresholds import FamilySpec, StagePreRegistration

SMALL_OFF = "small/hybrid+rerank+metadata"
SMALL_ON = "small/hybrid+graph+rerank+metadata"
MERGED_OFF = "merged/hybrid+rerank+metadata"
MERGED_ON = "merged/hybrid+graph+rerank+metadata"
S1_ARMS = (SMALL_OFF, SMALL_ON, MERGED_OFF, MERGED_ON)


def _prereg() -> StagePreRegistration:
    """A synthetic S1-shaped pre-registration (never a real stage constant)."""
    return StagePreRegistration(
        reference_arm=SMALL_OFF,
        families=(
            FamilySpec("answer_usable", "decisional", (MERGED_OFF, MERGED_ON), 0.05),
        ),
        descriptive_arms=(SMALL_ON,),
        test="paired_sign_flip_exact_two_sided",
        non_evaluable_rule="p=1_m_unchanged",
        population="pairwise_per_comparison",
        complete_case_floor=0.80,
        matching_rule="chunk_id_via_gold_chunks",
        bootstrap_b=200,
        bootstrap_seed=42,
        null_guard_arms=(MERGED_OFF,),
        null_guard_predicate="metrics.is_abstention",
        null_guard_margin=0.10,
        null_guard_min_pair_fraction=0.80,
        answer_mix_strata=("comparison_query", "binary_gold"),
        sc2_timeout_rate_floor=0.025,
        rerank_degrade_tripwire_rate=0.20,
        rerank_degrade_tripwire_min_calls=50,
        rerank_consecutive_degrade_halt=5,
        default_rule="synthetic test rule",
        provenance="synthetic S1 test pre-registration",
    )


def _record(arm: str, qid: str, spec: Spec, qs, *, doc: str) -> RunRecord:  # type: ignore[no-untyped-def]
    """A levers-fixture record of the base row, relabelled with its store prefix."""
    base = make_record(arm.partition("/")[2], qid, spec, qs)
    snapshot = base.snapshot
    if snapshot is not None:
        snapshot = snapshot.model_copy(
            update={
                "retrieved_chunks": [
                    c.model_copy(update={"document_id": doc})
                    for c in snapshot.retrieved_chunks
                ]
            }
        )
    return base.model_copy(update={"graph_arm": arm, "snapshot": snapshot})


SMALL_DOC = "doc-small-store"
MERGED_DOC = "doc-merged-store"


class _Map:
    def __init__(self, doc: str) -> None:
        self.entries = {doc: object()}
        self.aliases: dict[str, str] = {}


def _maps(seen: list[str]):  # type: ignore[no-untyped-def]
    """`load_document_map` stand-in: each store's map holds only its own document."""

    def load(corpus: str, store: EvalStore = V1_STORE) -> _Map:
        seen.append(store.name)
        return _Map({V1_STORE: SMALL_DOC, S1_STORE: MERGED_DOC}[store])

    return load


def _build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spec_fn=default_spec,  # type: ignore[no-untyped-def]
    *,
    doc_of=None,  # type: ignore[no-untyped-def]
) -> tuple[Path, Path, list[str]]:
    qs = make_questions(10, 5)
    root = tmp_path / "repo"
    gold = write_corpus(root, qs, S1_ARMS)
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr(thresholds, TOKEN, _prereg(), raising=False)
    seen: list[str] = []
    monkeypatch.setattr("lancet_eval.score.load_document_map", _maps(seen))
    run = tmp_path / "run"
    journal = Journal(run / "journal.jsonl")
    journal.write_header(corpus="levers_split", partial=False)
    for qid in [*qs.g_ids, *qs.nulls]:
        for arm in S1_ARMS:
            doc = (doc_of or (lambda a: SMALL_DOC if a.startswith("small/") else MERGED_DOC))(arm)
            journal.append(_record(arm, qid, spec_fn(arm, qid), qs, doc=doc))
    return run, gold, seen


def test_four_store_prefixed_arms_score_with_each_arms_own_document_map(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, seen = _build(tmp_path, monkeypatch)
    report = score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    assert report.metadata.arm_labels == list(S1_ARMS)
    names = {d.name for d in report.dimensions}
    for arm in S1_ARMS:
        assert f"answer_usable_p4__{arm_slug(arm)}" in names
    assert set(seen) == {"eval", "eval-s1"}


def test_a_merged_arm_citing_a_small_store_document_is_refused(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = _build(tmp_path, monkeypatch, doc_of=lambda _arm: SMALL_DOC)
    with pytest.raises(ScoreError, match=f"Unmapped document_id '{SMALL_DOC}'"):
        score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)


def test_the_four_store_prefixed_arms_pair_in_the_lever_comparison(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    wrong = {f"lv-g00{i}" for i in range(8)}

    def spec(arm: str, qid: str) -> Spec:
        # the small-store reference is wrong on 8 G questions; merged-off is right
        return Spec(kind="wrong") if arm == SMALL_OFF and qid in wrong else Spec()

    run, gold, _ = _build(tmp_path, monkeypatch, spec)
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    family = next(f for f in payload["families"] if f["primary"] == "answer_usable")
    rows = {c["arm"]: c for c in family["comparisons"]}
    assert set(rows) == {MERGED_OFF, MERGED_ON}
    assert rows[MERGED_OFF]["n_pos"] == 8
    assert rows[MERGED_OFF]["n_neg"] == 0
    assert rows[MERGED_OFF]["delta"] == pytest.approx(0.8)
