"""#149's fresh MultiHop-RAG split: built from question IDs alone, disjoint from every
question an earlier run read, and pinned by its sha256."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lancet_eval import fresh_split
from lancet_eval.config import repo_root
from lancet_eval.split import load_split, split_input_problems, split_sha256

#: The committed fresh split's sha256 (split.split_sha256), also in the run C corpus.
FRESH_SPLIT_SHA256 = "30d3dee89824cf4ef89b960a26889a2f1f8bed9128a47d341b93da0376d80e7d"
#: The D-105 split's digest before `heldout_ids` existed, as every journal records it.
D105_SPLIT_SHA256 = "d0d56609752d9dc87d6bd10a1954983fbf975a849d8a27294ee98c90f21361c2"

ROOT = repo_root()


def _split():  # type: ignore[no-untyped-def]
    return load_split(ROOT / fresh_split.SPLIT_REL)


def test_the_d105_split_keeps_its_digest() -> None:
    d105 = load_split(ROOT / fresh_split.D105_SPLIT_REL)
    assert split_sha256(d105) == D105_SPLIT_SHA256


def test_the_fresh_split_is_pinned_and_its_inputs_unchanged() -> None:
    split = _split()
    assert split_sha256(split) == FRESH_SPLIT_SHA256
    assert split_input_problems(split, ROOT) == []
    assert split.order_seed == fresh_split.SEED
    assert len(split.dev_ids) == fresh_split.DEV_SIZE
    assert split.heldout_g_ids == split.heldout_null_ids == []
    assert len(split.heldout_ids) == 2556 - 500 - fresh_split.DEV_SIZE


def test_no_fresh_question_was_read_by_an_earlier_run() -> None:
    split = _split()
    read = fresh_split.excluded_ids(ROOT)
    assert len(read) == 500
    assert not read & (set(split.dev_ids) | set(split.heldout_ids))


def test_the_dev_question_file_holds_exactly_the_dev_ids() -> None:
    path = ROOT / fresh_split.DEV_QUESTIONS_REL
    ids = [
        fresh_split.question_id(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(ids) == len(set(ids))
    assert sorted(ids) == _split().dev_ids


def test_carve_is_seeded_and_sorted() -> None:
    pool = [f"q{i:03d}" for i in range(50)]
    dev, held = fresh_split.carve(reversed(pool), seed=7, dev_size=20)
    assert (dev, held) == fresh_split.carve(pool, seed=7, dev_size=20)
    assert dev == sorted(dev) and held == sorted(held)
    assert sorted(dev + held) == pool
    assert fresh_split.carve(pool, seed=8, dev_size=20)[0] != dev
    with pytest.raises(ValueError, match="not more than dev size"):
        fresh_split.carve(pool, dev_size=50)


def test_build_refuses_a_repeated_id() -> None:
    row = {"query": "Same?", "answer": "Yes", "evidence_list": []}
    with pytest.raises(ValueError, match="share the ID"):
        fresh_split.build([row, dict(row)], ROOT)


@pytest.mark.skipif(
    not (ROOT / fresh_split.DATASET_REL).is_file(),
    reason="needs the cached MultiHopRAG.json (lancet-eval corpus fetch)",
)
def test_a_rebuild_from_the_dataset_gives_the_committed_split(tmp_path: Path) -> None:
    dataset = json.loads((ROOT / fresh_split.DATASET_REL).read_text(encoding="utf-8"))
    split, rows = fresh_split.build(dataset, ROOT)
    assert split_sha256(split) == FRESH_SPLIT_SHA256
    committed = (ROOT / fresh_split.DEV_QUESTIONS_REL).read_text(encoding="utf-8")
    assert [json.loads(line) for line in committed.splitlines()] == rows
