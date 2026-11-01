"""#163 (D-291): the files S3's held-out reader grid on 2Wiki reads.

The grid drives and replays the 900 held-out questions of the D-243 split
(``twowiki/split.json``). Its corpora (``twowiki_s3h_*.toml``) read the documents file
``twowiki_b`` writes and two files this module writes:

- ``twowiki/s3h_split.json`` (committed): the D-243 split in the drive's split model
  (`split.HeldOutSplit`), dev IDs copied, every held-out ID in G and none null. Every
  2Wiki question has a gold answer and supporting facts (the dataset has no
  unanswerable question type), so the sort reads no question's content. It records the
  D-243 file's hash under ``inputs``. It is written from ``split.json`` alone.
- ``twowiki/.cache/questions.heldout.jsonl``: the 900 held-out questions in the corpus
  adapter's MultiHop-RAG shape (``twowiki_b.question_row``). Wikipedia text, so never
  committed (ATTRIBUTION.md). It holds the gold answers the drive journals and a later
  scoring reads; nothing in this lane prints or reads them (D-291).
- ``twowiki/.cache/question_types.heldout.json``: ``{question ID: 2Wiki type}`` for the
  900, with no answer or evidence. RUN-S3-HELDOUT.md's record step copies it into each
  run directory of the grid, so the analysis can split by question type (#167) from
  the run directories alone.

`python -m lancet_eval.twowiki_h` rewrites both and prints the split's digest and the
questions file's sha256; `python -m lancet_eval.twowiki_h split` rewrites the split
only, with no cached source file needed.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lancet_eval import twowiki, twowiki_b
from lancet_eval.split import HeldOutSplit, lf_sha256, split_sha256

CORPORA = twowiki_b.CORPORA
HELDOUT_SPLIT_REL = "twowiki/s3h_split.json"
HELDOUT_QUESTIONS_REL = "twowiki/.cache/questions.heldout.jsonl"
QUESTION_TYPES_REL = "twowiki/.cache/question_types.heldout.json"

DERIVATION_RULE = (
    "#163 (D-291): the D-243 split (eval/corpora/twowiki/split.json) as written, dev "
    "IDs copied; every held-out ID is in G and none is null, since every 2Wiki "
    "question has a gold answer and supporting facts, so the sort reads no question's "
    "content"
)


def heldout_split(d243: twowiki.TwoWikiSplit, d243_sha256: str) -> HeldOutSplit:
    """The D-243 split in the drive's model, every held-out ID in G."""
    return HeldOutSplit(
        derivation_rule=DERIVATION_RULE,
        order_seed=d243.seed,
        dev_ids=list(d243.dev_ids),
        heldout_g_ids=list(d243.heldout_ids),
        heldout_null_ids=[],
        inputs={twowiki_b.D243_REL: d243_sha256},
    )


def heldout_question_rows(
    questions: Sequence[Mapping[str, Any]], heldout_ids: Sequence[str]
) -> list[dict[str, Any]]:
    """The held-out rows, sorted by ID.

    Raises:
        ValueError: If a held-out ID has no question.
    """
    wanted = set(heldout_ids)
    rows = [twowiki_b.question_row(q) for q in questions if str(q["_id"]) in wanted]
    missing = wanted - {r["question_id"] for r in rows}
    if missing:
        raise ValueError(f"{len(missing)} held-out ID(s) have no question")
    return sorted(rows, key=lambda r: r["question_id"])


def question_types(rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """``{question ID: question type}`` of question rows, sorted by ID; nothing else."""
    return {
        str(r["question_id"]): str(r["question_type"])
        for r in sorted(rows, key=lambda r: str(r["question_id"]))
    }


def write_split(corpora: Path = CORPORA) -> str:
    """Rewrites the held-out drive split; returns its digest (``split_sha256``)."""
    d243_path = corpora / twowiki.SPLIT_REL
    d243 = twowiki.load_split(d243_path)
    split = heldout_split(d243, lf_sha256(d243_path))
    (corpora / HELDOUT_SPLIT_REL).write_text(
        json.dumps(split.model_dump(exclude_defaults=True), indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return split_sha256(split)


def write(
    corpora: Path = CORPORA, cache_dir: Path = twowiki.CACHE_DIR
) -> dict[str, str]:
    """Rewrites the three files; returns the split's digest and each file's sha256."""
    digest = write_split(corpora)
    d243 = twowiki.load_split(corpora / twowiki.SPLIT_REL)
    questions_path = cache_dir / twowiki.QUESTIONS_FILE
    twowiki.check_source(questions_path)
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    rows = heldout_question_rows(questions, d243.heldout_ids)
    out = corpora / HELDOUT_QUESTIONS_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    types = corpora / QUESTION_TYPES_REL
    types.write_text(
        json.dumps(question_types(rows), indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "split_sha256": digest,
        HELDOUT_QUESTIONS_REL: lf_sha256(out),
        QUESTION_TYPES_REL: lf_sha256(types),
    }


if __name__ == "__main__":
    if sys.argv[1:] == ["split"]:
        print(f"split_sha256: {write_split()}")
    else:
        for name, value in write().items():
            print(f"{name}: {value}")
