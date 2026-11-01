"""#149 item B: the files the 2Wiki reader run reads (EXPLORE-B-2WIKI-READERS.md).

Run B drives `twowiki/hybrid+rerank+metadata` over the 100 D-243 dev questions of
#145's 2Wiki corpus. The run's corpus (`twowiki_s3b_dev.toml`) reads three files that
this module writes, all from #145's sha-checked cache (`python -m lancet_eval.twowiki
fetch`):

- ``twowiki/s3b_split.json`` (committed): the D-243 split in the drive's split model
  (`split.HeldOutSplit`), dev and held-out IDs copied from ``twowiki/split.json``, whose
  hash it records under ``inputs``. Its held-out IDs stay unsorted into G and null.
- ``twowiki/.cache/documents.jsonl``: one document per passage, ingested as given.
  Its body is the passage's extraction unit (``twowiki.passage_unit``: title, a
  newline, text), its title the passage title, which is unique across the 6,119.
- ``twowiki/.cache/questions.dev.jsonl``: the 100 dev questions in the corpus
  adapter's MultiHop-RAG shape. Each gold fact is a supporting sentence, read from the
  question's own context.

The two `.cache` files hold Wikipedia text, so they are never committed (#145,
ATTRIBUTION.md); the corpus pins the documents file's sha256. Only dev rows are
written: a held-out row is read for its ``_id`` alone.

`python -m lancet_eval.twowiki_b` rewrites all three and prints each digest.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lancet_eval import twowiki
from lancet_eval.config import repo_root
from lancet_eval.split import HeldOutSplit, lf_sha256, split_sha256

CORPORA = repo_root() / "eval" / "corpora"
DRIVE_SPLIT_REL = "twowiki/s3b_split.json"
DOCUMENTS_REL = "twowiki/.cache/documents.jsonl"
DEV_QUESTIONS_REL = "twowiki/.cache/questions.dev.jsonl"
D243_REL = f"eval/corpora/{twowiki.SPLIT_REL}"

DERIVATION_RULE = (
    "#149 item B: the D-243 split (eval/corpora/twowiki/split.json) as written, dev "
    "and held-out IDs copied; the held-out IDs are not sorted into G and null"
)


def drive_split(d243: twowiki.TwoWikiSplit, d243_sha256: str) -> HeldOutSplit:
    """The D-243 split in the drive's model, recording the file it was copied from."""
    return HeldOutSplit(
        derivation_rule=DERIVATION_RULE,
        order_seed=d243.seed,
        dev_ids=list(d243.dev_ids),
        heldout_g_ids=[],
        heldout_null_ids=[],
        heldout_ids=list(d243.heldout_ids),
        inputs={D243_REL: d243_sha256},
    )


def document_rows(passages: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """One seed row per passage, in file order.

    Raises:
        ValueError: If two passages share a title, which `seed` keys documents by.
    """
    rows = [
        {"title": str(p["title"]), "body": twowiki.passage_unit(dict(p))}
        for p in passages
    ]
    titles = [r["title"] for r in rows]
    if len(set(titles)) != len(titles):
        raise ValueError("two passages share a title; seed keys documents by title")
    return rows


def question_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    """One 2Wiki question in the corpus adapter's shape, its supporting sentences as
    gold facts.

    A supporting fact whose sentence index is past its paragraph (a defect of a few
    2Wiki rows) takes the whole paragraph, sentences joined by spaces, as its fact.

    Raises:
        ValueError: If a supporting fact names a paragraph its context lacks.
    """
    context = {str(title): list(sentences) for title, sentences in raw["context"]}
    evidence = []
    for title, index in raw["supporting_facts"]:
        sentences = context.get(str(title))
        if not sentences:
            raise ValueError(f"{raw['_id']}: no paragraph {title!r} in its context")
        fact = (
            sentences[int(index)]
            if 0 <= int(index) < len(sentences)
            else " ".join(sentences)
        )
        evidence.append({"title": str(title), "fact": str(fact)})
    return {
        "question_id": str(raw["_id"]),
        "query": str(raw["question"]),
        "answer": str(raw["answer"]),
        "question_type": str(raw["type"]),
        "evidence_list": evidence,
    }


def dev_question_rows(
    questions: Sequence[Mapping[str, Any]], dev_ids: Sequence[str]
) -> list[dict[str, Any]]:
    """The dev rows, sorted by ID; every other row is read for its ``_id`` alone.

    Raises:
        ValueError: If a dev ID has no question.
    """
    wanted = set(dev_ids)
    rows = [question_row(q) for q in questions if str(q["_id"]) in wanted]
    missing = wanted - {r["question_id"] for r in rows}
    if missing:
        raise ValueError(f"{len(missing)} dev ID(s) have no question")
    return sorted(rows, key=lambda r: r["question_id"])


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write(
    corpora: Path = CORPORA, cache_dir: Path = twowiki.CACHE_DIR
) -> dict[str, str]:
    """Rewrites the three files; returns the split's digest and each file's sha256."""
    d243_path = corpora / twowiki.SPLIT_REL
    d243 = twowiki.load_split(d243_path)
    split = drive_split(d243, lf_sha256(d243_path))
    (corpora / DRIVE_SPLIT_REL).write_text(
        json.dumps(split.model_dump(exclude_defaults=True), indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_jsonl(
        corpora / DOCUMENTS_REL, document_rows(twowiki.load_passages(cache_dir))
    )
    questions_path = cache_dir / twowiki.QUESTIONS_FILE
    twowiki.check_source(questions_path)
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    _write_jsonl(
        corpora / DEV_QUESTIONS_REL, dev_question_rows(questions, d243.dev_ids)
    )
    return {
        "split_sha256": split_sha256(split),
        DOCUMENTS_REL: lf_sha256(corpora / DOCUMENTS_REL),
        DEV_QUESTIONS_REL: lf_sha256(corpora / DEV_QUESTIONS_REL),
    }


if __name__ == "__main__":
    for name, digest in write().items():
        print(f"{name}: {digest}")
