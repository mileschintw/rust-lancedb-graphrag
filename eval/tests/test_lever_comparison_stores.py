"""#125: a two-store journal scores each arm against its own store.

The gold-chunk table maps gold evidence to v1.0-store chunk IDs, so the chunk-ID
secondaries of an arm on another store (D-251) are not evaluable instead of a false 0.
`coverage_at_4` drops gold facts by the arm's own store chunk size, in that store's
unit (o200k tokens for `structure-merge`).

#128: with a chunk-text dump of the merged store, its arms read gold sets built from
that store's own chunks, so the chunk-ID secondaries become evaluable.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from levers_fixture import (
    CORPUS,
    TOKEN,
    Spec,
    _excerpt,
    fact,
    make_prereg,
    make_questions,
    make_record,
    write_corpus,
)
from test_lever_comparison import _minimal_report

from lancet_eval import thresholds
from lancet_eval.journal import Journal, RunRecord, load_records
from lancet_eval.lever_comparison import LeverComparisonError, build_lever_comparison
from lancet_eval.metrics import context_tokens

SMALL = "small/hybrid+rerank+metadata"
SMALL_GRAPH = "small/hybrid+graph+rerank+metadata"
MERGED = "merged/hybrid+rerank+metadata"
STORE_ARMS = (SMALL, SMALL_GRAPH, MERGED)
CHUNK_ID_METRICS = ("paper_hits_at_10", "paper_mrr_at_10", "paper_map_at_10")


def _fact_tokens() -> int:
    return context_tokens([fact("lv-g000", "a")])


def _merged_ids(rec: RunRecord) -> RunRecord:
    """The merged store's own chunk IDs: never equal to a v1.0-store ID (#128)."""
    assert rec.snapshot is not None
    ranking = [
        c.model_copy(update={"chunk_id": f"m-{c.chunk_id}"})
        for c in rec.snapshot.pre_truncation_ranking
    ]
    snapshot = rec.snapshot.model_copy(update={"pre_truncation_ranking": ranking})
    return rec.model_copy(update={"snapshot": snapshot})


def _merged_dump(path: Path, run: Path) -> Path:
    """A `--chunk-text` dump of every merged chunk ranked, text as the excerpts."""
    rows = {}
    for rec in load_records(run / "journal.jsonl"):
        if rec.graph_arm != MERGED or rec.snapshot is None:
            continue
        for c in rec.snapshot.pre_truncation_ranking:
            text = _excerpt(c.chunk_id.removeprefix("m-"))
            rows[c.chunk_id] = {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "chunk_index": 0,
                "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text": text,
            }
    path.write_text("".join(json.dumps(r) + "\n" for r in rows.values()), "utf-8")
    return path


def _build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    merged_chunk_size: int,
    merged_dump: bool = False,
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
            rec = rec.model_copy(update={"graph_arm": arm})
            journal.append(_merged_ids(rec) if arm == MERGED else rec)
    _minimal_report(run)
    chunk_text = (
        {"merged": _merged_dump(tmp_path / "merged.jsonl", run)}
        if merged_dump
        else None
    )
    return build_lever_comparison(run, gold_chunks_path=gold, chunk_text=chunk_text)


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


def test_a_merged_dump_makes_its_chunk_id_secondaries_evaluable(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    # The merged arm ranks the same facts at the same ranks under its own chunk IDs,
    # so its store's gold sets score it exactly as the table scores the small arm.
    payload = _build(tmp_path, monkeypatch, merged_chunk_size=256, merged_dump=True)
    for metric in (*CHUNK_ID_METRICS, "all_gold_at_4"):
        row = _secondary(payload, metric)
        assert row["n_pairs"] == 10, metric
        assert row["mean_arm"] > 0, metric
        assert row["mean_arm"] == row["mean_reference"], metric


def test_a_merged_dump_missing_a_ranked_chunk_refuses(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    full_dump = _merged_dump

    def short_dump(path: Path, run: Path) -> Path:
        full = full_dump(path, run)
        lines = full.read_text("utf-8").splitlines(keepends=True)
        full.write_text("".join(lines[1:]), "utf-8")
        return full

    monkeypatch.setattr(f"{__name__}._merged_dump", short_dump)
    with pytest.raises(LeverComparisonError, match="#128: the chunk-text dump lacks"):
        _build(tmp_path, monkeypatch, merged_chunk_size=256, merged_dump=True)
