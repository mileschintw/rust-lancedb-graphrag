"""#149: the fresh MultiHop-RAG split, carved from questions no run has read.

Run C of #149 (experiments/v1.1/EXPLORE-C-MHR-FULL.md) reads dev questions that no
earlier run sent to a reader, and reserves the rest as a held-out set for #146's
confirmation stage. The split is built from question IDs alone:

- the pool is every question of the full dataset (`MultiHopRAG.json`, 2,556
  questions), each ID the corpus adapter's (`mhr-` plus 12 hex of the query's sha256);
- it drops every ID any committed MultiHop-RAG question file holds
  (`questions.*.jsonl` and `canary*.jsonl` under `eval/corpora/multihop_rag/`) and every
  ID of the D-105 split (`heldout_split.json`), read for its IDs only;
- the sorted pool is shuffled with `SEED`; the first `DEV_SIZE` IDs are the dev set, the
  rest the held-out set, each kept sorted.

The held-out questions are never classified into G and null: that would read their
evidence. They go to `HeldOutSplit.heldout_ids`. Only the dev rows are written out, to
`questions.fresh_dev.jsonl`.

`python -m lancet_eval.fresh_split` rebuilds both files from the cached dataset
(`lancet-eval corpus fetch --corpus multihop_rag`) and prints the split's sha256.
"""

from __future__ import annotations

import json
import random
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from lancet_eval.corpus import _adapt_multihop_rag
from lancet_eval.split import (
    POPULATIONS_REL,
    QUESTIONS_SAMPLE_REL,
    HeldOutSplit,
    lf_sha256,
    split_sha256,
)

#: The fresh split's shuffle seed (#149).
SEED = 149
#: Fresh dev questions: #149 asks for up to 1,000.
DEV_SIZE = 1000
CORPUS_DIR_REL = "eval/corpora/multihop_rag"
SPLIT_REL = f"{CORPUS_DIR_REL}/fresh_split.json"
DEV_QUESTIONS_REL = f"{CORPUS_DIR_REL}/questions.fresh_dev.jsonl"
DATASET_REL = f"{CORPUS_DIR_REL}/.cache/MultiHopRAG.json"
D105_SPLIT_REL = f"{CORPUS_DIR_REL}/heldout_split.json"
DIAG_SELECTION_REL = f"{CORPUS_DIR_REL}/diag_selection.json"
#: The committed question files whose IDs leave the pool (globbed in CORPUS_DIR_REL).
READ_FILE_GLOBS = ("questions.*.jsonl", "canary*.jsonl")

DERIVATION_RULE = (
    "#149 fresh split: every MultiHopRAG.json question whose ID is in no committed "
    "MultiHop-RAG question file (questions.*.jsonl, canary*.jsonl) and not in "
    f"heldout_split.json; the sorted pool shuffled with seed {SEED}; the first "
    f"{DEV_SIZE} are dev, the rest held-out (unsorted into G and null, never read)"
)


def question_id(raw: Mapping[str, Any]) -> str:
    """The ID the corpus adapter gives a raw MultiHop-RAG row."""
    return _adapt_multihop_rag(dict(raw)).question_id


def read_ids(path: Path) -> set[str]:
    """The question IDs of one committed JSONL file, read from each row's
    ``question_id`` field alone (every committed MultiHop-RAG file carries one).

    Raises:
        ValueError: If a row has no ``question_id``.
    """
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            qid = json.loads(line).get("question_id")
            if not qid:
                raise ValueError(f"{path.name}: a row has no question_id")
            ids.add(str(qid))
    return ids


def excluded_ids(repo: Path) -> set[str]:
    """Every ID a committed MultiHop-RAG question file or the D-105 split holds."""
    corpus_dir = repo / CORPUS_DIR_REL
    ids: set[str] = set()
    for pattern in READ_FILE_GLOBS:
        for path in sorted(corpus_dir.glob(pattern)):
            if path.name != Path(DEV_QUESTIONS_REL).name:
                ids |= read_ids(path)
    d105 = json.loads((repo / D105_SPLIT_REL).read_text(encoding="utf-8"))
    for key in ("dev_ids", "heldout_g_ids", "heldout_null_ids"):
        ids |= set(d105[key])
    return ids


def carve(
    pool: Iterable[str], *, seed: int = SEED, dev_size: int = DEV_SIZE
) -> tuple[list[str], list[str]]:
    """Splits the pool into sorted dev and held-out ID lists.

    Raises:
        ValueError: If the pool holds no more than `dev_size` IDs, so no held-out
            set would be left.
    """
    ordered = sorted(set(pool))
    if len(ordered) <= dev_size:
        raise ValueError(
            f"the pool holds {len(ordered)} questions, not more than dev size "
            f"{dev_size}"
        )
    shuffled = list(ordered)
    random.Random(seed).shuffle(shuffled)
    return sorted(shuffled[:dev_size]), sorted(shuffled[dev_size:])


def build(
    dataset: Sequence[Mapping[str, Any]], repo: Path
) -> tuple[HeldOutSplit, list[Mapping[str, Any]]]:
    """The fresh split and its dev rows, in the dataset's order.

    Raises:
        ValueError: If two dataset rows share an ID, or the pool is too small.
    """
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in dataset:
        qid = question_id(row)
        if qid in by_id:
            raise ValueError(f"two dataset rows share the ID {qid}")
        by_id[qid] = row
    excluded = excluded_ids(repo)
    dev, heldout = carve(set(by_id) - excluded)
    split = HeldOutSplit(
        derivation_rule=DERIVATION_RULE,
        populations_sha256=lf_sha256(repo / POPULATIONS_REL),
        diag_selection_sha256=lf_sha256(repo / DIAG_SELECTION_REL),
        questions_sample_sha256=lf_sha256(repo / QUESTIONS_SAMPLE_REL),
        dev_source=DIAG_SELECTION_REL,
        order_seed=SEED,
        dev_ids=dev,
        heldout_g_ids=[],
        heldout_null_ids=[],
        heldout_ids=heldout,
    )
    wanted = set(dev)
    return split, [row for qid, row in by_id.items() if qid in wanted]


def write(repo: Path) -> str:
    """Rebuilds the split file and the dev question file; returns the split's sha256."""
    dataset = json.loads((repo / DATASET_REL).read_text(encoding="utf-8"))
    split, rows = build(dataset, repo)
    (repo / SPLIT_REL).write_text(
        json.dumps(split.model_dump(exclude={"inputs"}), indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with open(repo / DEV_QUESTIONS_REL, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return split_sha256(split)


if __name__ == "__main__":
    from lancet_eval.config import repo_root

    print(write(repo_root()))
    sys.exit(0)
