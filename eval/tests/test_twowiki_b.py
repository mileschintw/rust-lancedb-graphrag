"""#149 item B's files: the D-243 split in the drive's model, one seed document per
2Wiki passage, and the dev questions with their supporting sentences as gold facts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lancet_eval import twowiki, twowiki_b
from lancet_eval.config import repo_root
from lancet_eval.corpus import _adapt_multihop_rag
from lancet_eval.split import (
    HeldOutSplit,
    lf_sha256,
    load_split,
    split_input_problems,
    split_sha256,
)

ROOT = repo_root()
CORPORA = ROOT / "eval" / "corpora"
#: The committed drive split's digest (split.split_sha256), also in run B's constant.
S3B_SPLIT_SHA256 = "54a15e0781a51e70551230a5e4bbf44754b57d3f668341850027fa3b5934b76e"
#: The LF sha256 of the generated documents file, pinned in twowiki_s3b_dev.toml.
DOCUMENTS_SHA256 = "57d038e26b2bfc10bdd91afcde3a2df30a79bad583f9b9f4f2aa3002d744e822"
HAS_CACHE = (twowiki.CACHE_DIR / twowiki.PASSAGES_FILE).is_file()


def test_the_drive_split_is_the_d243_split_and_pinned() -> None:
    split = load_split(CORPORA / twowiki_b.DRIVE_SPLIT_REL)
    d243 = twowiki.load_split(twowiki.SPLIT_PATH)
    assert split_sha256(split) == S3B_SPLIT_SHA256
    assert split.dev_ids == d243.dev_ids
    assert split.heldout_ids == d243.heldout_ids
    assert split.heldout_g_ids == split.heldout_null_ids == []
    assert split.order_seed == twowiki.SPLIT_SEED
    assert split.inputs == {twowiki_b.D243_REL: lf_sha256(twowiki.SPLIT_PATH)}
    assert split_input_problems(split, ROOT) == []


def test_a_changed_d243_split_is_named(tmp_path: Path) -> None:
    split = load_split(CORPORA / twowiki_b.DRIVE_SPLIT_REL)
    moved = tmp_path / twowiki_b.D243_REL
    moved.parent.mkdir(parents=True)
    moved.write_text("{}", encoding="utf-8")
    [problem] = split_input_problems(split, tmp_path)
    assert "no longer hashes" in problem and twowiki_b.D243_REL in problem


def test_a_split_records_either_multihop_inputs_or_inputs() -> None:
    base = {
        "derivation_rule": "r",
        "order_seed": 1,
        "dev_ids": ["d"],
        "heldout_g_ids": [],
        "heldout_null_ids": [],
    }
    with pytest.raises(ValidationError, match="records populations_sha256"):
        HeldOutSplit(**base)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="none of the MultiHop-RAG inputs"):
        HeldOutSplit(**base, inputs={"x": "0" * 64}, dev_source="y")  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="not a sha256"):
        HeldOutSplit(**base, inputs={"x": "nope"})  # type: ignore[arg-type]


def test_a_document_is_one_passage_as_given() -> None:
    rows = twowiki_b.document_rows([{"title": "A", "text": "a b"}])
    assert rows == [{"title": "A", "body": "A\na b"}]
    with pytest.raises(ValueError, match="share a title"):
        twowiki_b.document_rows([
            {"title": "A", "text": "x"},
            {"title": "A", "text": "y"},
        ])


def test_a_question_takes_its_supporting_sentences_as_gold_facts() -> None:
    raw = {
        "_id": "q1",
        "question": "Who?",
        "answer": "Ann",
        "type": "compositional",
        "context": [["P", ["s0.", "s1."]], ["Q", ["t0."]]],
        "supporting_facts": [["P", 1], ["Q", 4]],
    }
    row = twowiki_b.question_row(raw)
    gold = _adapt_multihop_rag(row)
    assert (gold.question_id, gold.question, gold.gold_answer) == ("q1", "Who?", "Ann")
    # An index past its paragraph takes the whole paragraph.
    assert gold.gold_facts == ["s1.", "t0."]
    assert not gold.is_null


def test_only_dev_rows_are_written() -> None:
    rows = [
        {
            "_id": i,
            "question": i,
            "answer": "x",
            "type": "t",
            "context": [["P", ["s"]]],
            "supporting_facts": [["P", 0]],
        }
        for i in ("b", "a", "c")
    ]
    assert [
        r["question_id"] for r in twowiki_b.dev_question_rows(rows, ["c", "a"])
    ] == [
        "a",
        "c",
    ]
    with pytest.raises(ValueError, match="have no question"):
        twowiki_b.dev_question_rows(rows, ["z"])


@pytest.mark.skipif(not HAS_CACHE, reason="needs #145's cache (twowiki fetch)")
def test_a_rebuild_from_the_cache_gives_the_pinned_files(tmp_path: Path) -> None:
    corpora = tmp_path / "corpora"
    (corpora / "twowiki").mkdir(parents=True)
    (corpora / twowiki.SPLIT_REL).write_bytes(twowiki.SPLIT_PATH.read_bytes())
    digests = twowiki_b.write(corpora)
    assert digests["split_sha256"] == S3B_SPLIT_SHA256
    assert digests[twowiki_b.DOCUMENTS_REL] == DOCUMENTS_SHA256
    lines = (corpora / twowiki_b.DEV_QUESTIONS_REL).read_text(encoding="utf-8")
    ids = [json.loads(line)["question_id"] for line in lines.splitlines()]
    assert ids == twowiki.load_split(twowiki.SPLIT_PATH).dev_ids
