"""The 2WikiMultiHopQA corpus for S3 (#145): pinned source, passages and D-243 split.

The raw files are fetched from `osunlp/HippoRAG_2` at one pinned revision into a
gitignored `.cache/` and checked against their recorded sha256; none is committed. The
committed split is checked without them: it is rebuilt from its own IDs and seed.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from lancet_eval import twowiki
from lancet_eval.config import repo_root
from lancet_eval.corpus import load_corpus
from lancet_eval.split import lf_sha256

CORPORA = repo_root() / "eval" / "corpora"


def _ids(n: int) -> list[str]:
    return [f"{i:032x}" for i in range(n)]


def test_the_split_is_seeded_disjoint_and_complete() -> None:
    ids = _ids(50)
    dev, heldout = twowiki.build_split(list(reversed(ids)), seed=7, dev_size=10)
    assert len(dev) == 10 and len(heldout) == 40
    assert set(dev) | set(heldout) == set(ids)
    assert not set(dev) & set(heldout)
    assert dev == sorted(dev) and heldout == sorted(heldout)
    # Input order does not matter; the seed does.
    assert twowiki.build_split(ids, seed=7, dev_size=10) == (dev, heldout)
    assert twowiki.build_split(ids, seed=8, dev_size=10)[0] != dev


def test_the_split_refuses_duplicates_and_an_oversized_dev() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        twowiki.build_split(["a", "a", "b"], seed=1, dev_size=1)
    with pytest.raises(ValueError, match="dev_size"):
        twowiki.build_split(["a", "b"], seed=1, dev_size=2)


def test_question_ids_reads_the_id_field_only(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text(
        json.dumps([{"_id": "x1", "question": "q?"}, {"_id": "x2", "answer": "a"}]),
        encoding="utf-8",
    )
    assert twowiki.question_ids(path) == ["x1", "x2"]


def test_a_passage_is_its_title_and_text() -> None:
    """HippoRAG 2's own form; 37% of the passages do not name their title."""
    assert (
        twowiki.passage_unit({"title": "Obata Toramori", "text": "He was the father."})
        == "Obata Toramori\nHe was the father."
    )


def test_a_cached_file_with_other_bytes_is_refused(tmp_path: Path) -> None:
    path = tmp_path / twowiki.PASSAGES_FILE
    path.write_bytes(b"[]")
    with pytest.raises(twowiki.SourceError, match="sha256"):
        twowiki.check_source(path)


def test_the_committed_split_rebuilds_from_its_seed() -> None:
    split = twowiki.load_split(CORPORA / twowiki.SPLIT_REL)
    assert len(split.dev_ids) == split.dev_size == twowiki.DEV_SIZE
    assert len(split.dev_ids) + len(split.heldout_ids) == twowiki.QUESTION_COUNT
    assert split.revision == twowiki.REVISION
    assert split.questions_sha256 == twowiki.SOURCE_SHA256[twowiki.QUESTIONS_FILE]
    rebuilt = twowiki.build_split(
        split.dev_ids + split.heldout_ids, seed=split.seed, dev_size=split.dev_size
    )
    assert rebuilt == (split.dev_ids, split.heldout_ids)


def test_the_corpus_file_records_the_source_and_the_splits_sha256() -> None:
    data = tomllib.loads((CORPORA / "twowiki.toml").read_text(encoding="utf-8"))
    documents, split = data["documents"], data["d243_split"]
    assert documents["revision"] == twowiki.REVISION
    assert documents["count"] == twowiki.PASSAGE_COUNT
    assert documents["commit_documents"] is False
    assert split["file"] == twowiki.SPLIT_REL
    assert split["sha256"] == lf_sha256(CORPORA / twowiki.SPLIT_REL)
    assert split["seed"] == twowiki.SPLIT_SEED
    corpus = load_corpus("twowiki")
    assert corpus.license == "apache-2.0"
    assert not corpus.commit_documents


def test_no_raw_file_is_committed() -> None:
    for name in twowiki.SOURCE_SHA256:
        assert not (CORPORA / "twowiki" / name).exists(), name


def test_the_attribution_names_the_source_and_its_licence() -> None:
    text = (CORPORA / "ATTRIBUTION.md").read_text(encoding="utf-8")
    section = text.split("## 2WikiMultiHopQA", 1)[1]
    assert "Apache License 2.0" in section
    assert twowiki.REVISION in section
