"""#125: a two-store journal scores each arm against its own store.

The gold-chunk table maps gold evidence to v1.0-store chunk IDs, so the chunk-ID
secondaries of an arm on another store (D-251) are not evaluable instead of a false 0.
`coverage_at_4` drops gold facts by the arm's own store chunk size, in that store's
unit (o200k tokens for `structure-merge`).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from levers_fixture import (
    CORPUS,
    TOKEN,
    Spec,
    fact,
    make_prereg,
    make_questions,
    make_record,
    write_corpus,
)
from test_lever_comparison import _minimal_report

from lancet_eval import thresholds
from lancet_eval.journal import Journal
from lancet_eval.lever_comparison import build_lever_comparison
from lancet_eval.metrics import context_tokens

SMALL = "small/hybrid+rerank+metadata"
SMALL_GRAPH = "small/hybrid+graph+rerank+metadata"
MERGED = "merged/hybrid+rerank+metadata"
STORE_ARMS = (SMALL, SMALL_GRAPH, MERGED)
CHUNK_ID_METRICS = ("paper_hits_at_10", "paper_mrr_at_10", "paper_map_at_10")


def _fact_tokens() -> int:
    return context_tokens([fact("lv-g000", "a")])


def _build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, merged_chunk_size: int
) -> dict:  # type: ignore[type-arg]
    qs = make_questions(10, 5)
    root = tmp_path / "repo"
    gold = write_corpus(root, qs, STORE_ARMS)
    toml = root / "eval" / "corpora" / f"{CORPUS}.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + "[stores.small]\n"
        'chunk_strategy = "structure-aware"\nchunk_size = 500\nchunk_overlap = 50\n'
        "[stores.merged]\n"
        'chunk_strategy = "structure-merge"\n'
        f"chunk_size = {merged_chunk_size}\nchunk_overlap = 1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    template = make_prereg(())
    prereg = dataclasses.replace(
        template,
        reference_arm=SMALL,
        families=(
            dataclasses.replace(template.families[0], arms=(SMALL_GRAPH, MERGED)),
            dataclasses.replace(template.families[1], arms=()),
        ),
        null_guard_arms=(SMALL_GRAPH, MERGED),
    )
    monkeypatch.setattr(thresholds, TOKEN, prereg, raising=False)
    run = tmp_path / "run"
    journal = Journal(run / "journal.jsonl")
    journal.write_header(corpus=CORPUS, partial=False)
    for qid in [*qs.g_ids, *qs.nulls]:
        for arm in STORE_ARMS:
            # The fixture builds the base row; the label carries the store.
            base = arm.partition("/")[2]
            rec = make_record(base, qid, Spec(), qs)
            journal.append(rec.model_copy(update={"graph_arm": arm}))
    _minimal_report(run)
    return build_lever_comparison(run, gold_chunks_path=gold)


def _secondary(  # type: ignore[type-arg]
    payload: dict, metric: str, arm: str = MERGED
) -> dict:
    return next(
        s for s in payload["secondaries"] if s["arm"] == arm and s["metric"] == metric
    )


def test_merged_chunk_id_secondaries_are_not_evaluable_instead_of_zero(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    payload = _build(tmp_path, monkeypatch, merged_chunk_size=256)
    for metric in (*CHUNK_ID_METRICS, "all_gold_at_4"):
        row = _secondary(payload, metric)
        assert row["n_pairs"] == 0, metric
        assert row["mean_arm"] is None, metric
        assert row["delta"] is None, metric
        assert row["n_unscorable"] == 10, metric


def test_coverage_counts_the_merged_store_chunk_size_in_tokens(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    # Longer than the size in characters, within it in tokens: every fact fits.
    size = _fact_tokens() + 2
    assert len(fact("lv-g000", "a")) > size
    row = _secondary(
        _build(tmp_path, monkeypatch, merged_chunk_size=size), "coverage_at_4"
    )
    assert row["n_pairs"] == 10
    assert row["mean_arm"] == pytest.approx(1.0)


def test_coverage_drops_facts_longer_than_the_merged_store_chunk(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    # The run-wide 500 would keep every fact; the merged store's own size keeps none.
    size = _fact_tokens() - 1
    row = _secondary(
        _build(tmp_path, monkeypatch, merged_chunk_size=size), "coverage_at_4"
    )
    assert row["n_pairs"] == 0
    assert row["mean_arm"] is None


def test_a_small_store_arm_keeps_its_chunk_id_secondaries(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    payload = _build(tmp_path, monkeypatch, merged_chunk_size=256)
    for metric in (*CHUNK_ID_METRICS, "all_gold_at_4"):
        row = _secondary(payload, metric, SMALL_GRAPH)
        assert row["n_pairs"] == 10, metric
        assert row["mean_arm"] > 0, metric
        assert row["mean_arm"] == row["mean_reference"], metric
