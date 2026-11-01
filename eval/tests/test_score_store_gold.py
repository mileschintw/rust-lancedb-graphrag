"""#128: `score` reads each arm's chunk-ID metrics against its own store.

The gold-chunk table holds v1.0-store chunk IDs. A merged-store arm with no chunk-text
dump of its store is left out of the chunk-ID dimensions instead of scoring 0; with a
dump, it reads the gold sets built from that store's chunk text.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from levers_fixture import _excerpt
from test_s1_store_arms import MERGED_OFF, MERGED_ON, S1_ARMS, SMALL_OFF, SMALL_ON
from test_s1_store_arms import _build as _build_s1

from lancet_eval.arms import arm_slug
from lancet_eval.journal import load_records
from lancet_eval.score import ScoreError, score_run

CHUNK_ID = ("paper_hits_at_4", "paper_hits_at_10", "paper_mrr_at_10", "paper_map_at_10")


def _dump(path: Path, run: Path, *, drop_first: bool = False) -> Path:
    """A `--chunk-text` dump of every merged chunk ranked, text as the excerpts."""
    rows: dict[str, str] = {}
    for rec in load_records(run / "journal.jsonl"):
        if not rec.graph_arm.startswith("merged/") or rec.snapshot is None:
            continue
        for c in rec.snapshot.pre_truncation_ranking:
            text = _excerpt(c.chunk_id)
            rows[c.chunk_id] = json.dumps({
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "chunk_index": 0,
                "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text": text,
            })
    lines = list(rows.values())[1 if drop_first else 0 :]
    path.write_text("".join(f"{line}\n" for line in lines), "utf-8")
    return path


def _scores(report) -> dict[str, float | None]:  # type: ignore[no-untyped-def]
    return {d.name: d.score for d in report.dimensions}


def test_merged_chunk_id_dimensions_are_left_out_without_a_dump(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = _build_s1(tmp_path, monkeypatch)
    scores = _scores(score_run(run_dir=run, no_judge=True, gold_chunks_path=gold))
    for metric in CHUNK_ID:
        for arm in (SMALL_OFF, SMALL_ON):
            assert scores[f"{metric}__{arm_slug(arm)}"] > 0, (metric, arm)
        for arm in (MERGED_OFF, MERGED_ON):
            assert f"{metric}__{arm_slug(arm)}" not in scores, (metric, arm)
            assert f"{metric}_script_faithful__{arm_slug(arm)}" not in scores
    assert f"paper_hits_at_10_delta__{arm_slug(MERGED_OFF)}" not in scores
    # The other dimensions keep every arm.
    for arm in S1_ARMS:
        assert f"answer_usable_p4__{arm_slug(arm)}" in scores


def test_a_merged_dump_scores_merged_arms_from_their_own_chunk_text(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = _build_s1(tmp_path, monkeypatch)
    dump = _dump(tmp_path / "merged.jsonl", run)
    scores = _scores(
        score_run(
            run_dir=run,
            no_judge=True,
            gold_chunks_path=gold,
            chunk_text={"merged": dump},
        )
    )
    for metric in CHUNK_ID:
        for suffix in ("", "_script_faithful"):
            small = scores[f"{metric}{suffix}__{arm_slug(SMALL_OFF)}"]
            merged = scores[f"{metric}{suffix}__{arm_slug(MERGED_OFF)}"]
            # The fixture ranks the same facts at the same ranks in both stores.
            assert merged == pytest.approx(small), (metric, suffix)
            assert merged > 0, (metric, suffix)
    assert scores[f"paper_hits_at_10_delta__{arm_slug(MERGED_OFF)}"] == pytest.approx(
        0.0
    )


def test_a_dump_missing_a_ranked_chunk_refuses(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = _build_s1(tmp_path, monkeypatch)
    dump = _dump(tmp_path / "merged.jsonl", run, drop_first=True)
    with pytest.raises(ScoreError, match="#128: the chunk-text dump lacks 1"):
        score_run(
            run_dir=run,
            no_judge=True,
            gold_chunks_path=gold,
            chunk_text={"merged": dump},
        )


def test_coverage_reads_the_merged_store_chunk_size(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    # No gold fact fits a two-token merged chunk, so the merged arms' coverage has no
    # value (at the run-wide 500 characters every fact would fit).
    run, gold, _ = _build_s1(tmp_path, monkeypatch)
    toml = tmp_path / "repo" / "eval" / "corpora" / "levers_split.toml"
    text = toml.read_text(encoding="utf-8")
    merged = "chunk_size = 256\nchunk_overlap = 25"
    assert merged in text
    toml.write_text(text.replace(merged, "chunk_size = 2\nchunk_overlap = 1"), "utf-8")
    dims = {
        d.name: d
        for d in score_run(run_dir=run, no_judge=True, gold_chunks_path=gold).dimensions
    }
    # A four-arm metric reads the questions every arm can score, so every arm's cell
    # counts the ten questions the merged arms cannot.
    for arm in S1_ARMS:
        cell = dims[f"coverage_at_4__{arm_slug(arm)}"]
        assert cell.score is None, arm
        assert cell.detail["n_unscorable"] == 10, arm


def test_a_merged_question_with_no_record_scores_as_a_miss(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = _build_s1(tmp_path, monkeypatch)
    journal = run / "journal.jsonl"
    lines = journal.read_text("utf-8").splitlines(keepends=True)
    gap = '"question_id":"lv-g000"'
    kept = [
        line
        for line in lines
        if not (gap in line.replace(" ", "") and '"merged/' in line)
    ]
    assert len(kept) == len(lines) - 2
    journal.write_text("".join(kept), "utf-8")
    dump = _dump(tmp_path / "merged.jsonl", run)
    scores = _scores(
        score_run(
            run_dir=run,
            no_judge=True,
            gold_chunks_path=gold,
            chunk_text={"merged": dump},
        )
    )
    small = scores[f"paper_hits_at_10_script_faithful__{arm_slug(SMALL_OFF)}"]
    merged = scores[f"paper_hits_at_10_script_faithful__{arm_slug(MERGED_OFF)}"]
    assert merged == pytest.approx(small - 0.1)


def test_a_reference_arm_with_no_gold_sets_drops_the_deltas(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    import dataclasses

    from levers_fixture import TOKEN
    from test_s1_store_arms import _prereg

    from lancet_eval import thresholds

    run, gold, _ = _build_s1(tmp_path, monkeypatch)
    prereg = _prereg()
    family = dataclasses.replace(prereg.families[0], arms=(SMALL_OFF, MERGED_ON))
    monkeypatch.setattr(
        thresholds,
        TOKEN,
        dataclasses.replace(
            prereg,
            reference_arm=MERGED_OFF,
            families=(family,),
            null_guard_arms=(SMALL_OFF,),
        ),
        raising=False,
    )
    scores = _scores(score_run(run_dir=run, no_judge=True, gold_chunks_path=gold))
    assert f"paper_hits_at_10__{arm_slug(SMALL_OFF)}" in scores
    assert not any(name.startswith("paper_hits_at_10_delta__") for name in scores)
    assert f"answer_usable_p4__{arm_slug(SMALL_OFF)}" in scores
