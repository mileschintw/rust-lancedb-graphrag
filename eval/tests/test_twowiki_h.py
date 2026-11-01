"""#163's held-out files (D-291): the D-243 split with every held-out ID in G, and the
held-out questions in the corpus adapter's shape."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lancet_eval import twowiki, twowiki_b, twowiki_h
from lancet_eval.config import repo_root
from lancet_eval.split import lf_sha256, load_split, split_input_problems, split_sha256

ROOT = repo_root()
CORPORA = ROOT / "eval" / "corpora"
#: The committed held-out drive split's digest, also in the S3 held-out run plan.
S3H_SPLIT_SHA256 = "7590e2b3281dfa2c9299714d9c49fce3b0a5fa25c454e88f9eb1855883c88a07"


def test_the_heldout_split_is_the_d243_split_with_every_heldout_id_in_g() -> None:
    split = load_split(CORPORA / twowiki_h.HELDOUT_SPLIT_REL)
    d243 = twowiki.load_split(twowiki.SPLIT_PATH)
    assert split_sha256(split) == S3H_SPLIT_SHA256
    assert split.dev_ids == d243.dev_ids
    assert split.heldout_g_ids == d243.heldout_ids
    assert len(split.heldout_g_ids) == 900
    assert split.heldout_null_ids == split.heldout_ids == []
    assert split.order_seed == twowiki.SPLIT_SEED
    assert split.inputs == {twowiki_b.D243_REL: lf_sha256(twowiki.SPLIT_PATH)}
    assert split_input_problems(split, ROOT) == []


def test_the_committed_split_is_what_write_split_writes(tmp_path: Path) -> None:
    corpora = tmp_path / "eval" / "corpora"
    (corpora / "twowiki").mkdir(parents=True)
    (corpora / twowiki.SPLIT_REL).write_bytes(twowiki.SPLIT_PATH.read_bytes())
    assert twowiki_h.write_split(corpora) == S3H_SPLIT_SHA256
    written = json.loads((corpora / twowiki_h.HELDOUT_SPLIT_REL).read_text("utf-8"))
    committed = json.loads(
        (CORPORA / twowiki_h.HELDOUT_SPLIT_REL).read_text(encoding="utf-8")
    )
    assert written == committed


def _raw(qid: str) -> dict[str, object]:
    return {
        "_id": qid,
        "question": f"Who is {qid}?",
        "answer": "x",
        "type": "compositional",
        "supporting_facts": [["A", 0]],
        "context": [["A", ["a sentence."]]],
    }


def test_heldout_rows_are_the_heldout_ids_only_sorted() -> None:
    rows = twowiki_h.heldout_question_rows(
        [_raw("c"), _raw("a"), _raw("dev")], ["c", "a"]
    )
    assert [r["question_id"] for r in rows] == ["a", "c"]
    assert rows[0]["evidence_list"] == [{"title": "A", "fact": "a sentence."}]


def test_a_heldout_id_without_a_question_is_refused() -> None:
    with pytest.raises(ValueError, match="1 held-out ID"):
        twowiki_h.heldout_question_rows([_raw("a")], ["a", "b"])


def test_the_type_map_holds_the_question_type_and_nothing_else() -> None:
    rows = twowiki_h.heldout_question_rows([_raw("c"), _raw("a")], ["a", "c"])
    rows[0]["question_type"] = "comparison"
    assert twowiki_h.question_types(rows) == {"a": "comparison", "c": "compositional"}
