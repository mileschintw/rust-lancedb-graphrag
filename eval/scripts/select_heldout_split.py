"""Freezes the D-105 dev / held-out split and the D-124 / D-108 rehearsal picks.

Reads, read-only, the committed `questions.sample.jsonl`, `diag_selection.json`
(the 100 dev IDs) and the 06.3.4.1 `populations.json` (the G population).
Writes four files into `--out-dir` (default `eval/corpora/multihop_rag`):

* `heldout_split.json`: the D-105 split (every non-dev sample question in G,
  plus every non-dev null) with the LF-normalised sha256 of the three inputs.
* `questions.heldout.jsonl`: the held-out sample rows, verbatim.
* `questions.rehearsal.jsonl`: the D-108 rehearsal rows, verbatim.
* `canary.arms.jsonl`: the D-124 arm-mode canaries.

Canary and rehearsal questions come only from the rehearsal pool (non-dev,
non-G, non-null sample questions), so neither can touch dev or held-out.

Deterministic and byte-identical: two runs over the same inputs produce the
same files (repudiation control, T-06.3.5-05). Every sha256 goes through
`lancet_eval.split.lf_sha256`, never raw working-tree bytes. Never writes to
LanceDB, PostgreSQL or any live store -- every write here is a plain file.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from lancet_eval.config import repo_root
from lancet_eval.split import POPULATIONS_REL, HeldOutSplit, lf_sha256

CORPUS_NAME = "multihop_rag"
NULL_QUESTION_TYPE = "null_query"
ORDER_SEED = 42
PICK_TYPES = ("comparison_query", "inference_query", "temporal_query")
DERIVATION_RULE = "every non-dev sample question in G, plus every non-dev null"
DEV_SOURCE = "eval/corpora/multihop_rag/diag_selection.json"
OUTPUT_FILES = (
    "heldout_split.json",
    "questions.heldout.jsonl",
    "questions.rehearsal.jsonl",
    "canary.arms.jsonl",
)


class SelectionError(Exception):
    """Raised when the split or the rehearsal picks cannot be drawn as specified."""


def _question_id_of(raw: dict[str, Any]) -> str:
    return str(raw.get("question_id") or raw.get("query_id") or raw.get("id") or "")


def _load_sample(path: Path) -> list[tuple[str, dict[str, Any], str]]:
    """Returns (question_id, parsed row, verbatim line text) per non-blank line."""
    rows: list[tuple[str, dict[str, Any], str]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            raw = json.loads(stripped)
            qid = _question_id_of(raw)
            if not qid:
                raise SelectionError(f"Sample row without a question_id in {path}")
            rows.append((qid, raw, stripped))
    if len({qid for qid, _, _ in rows}) != len(rows):
        raise SelectionError(f"Duplicate question_ids in {path}")
    return rows


def _pick_per_type(
    rng: random.Random, pool_by_type: dict[str, list[str]], excluded: set[str]
) -> list[str]:
    """One `rng.choice` per type over the sorted candidates not yet excluded."""
    picks: list[str] = []
    for qtype in PICK_TYPES:
        candidates = sorted(i for i in pool_by_type.get(qtype, []) if i not in excluded)
        if not candidates:
            raise SelectionError(
                f"No rehearsal-pool candidate left for question_type {qtype}"
            )
        picks.append(rng.choice(candidates))
    return picks


def build_outputs(root: Path) -> tuple[dict[str, str], str]:
    """Computes the split and returns (filename -> file text, stdout report).

    Args:
        root: Repository root the three inputs are read from.

    Returns:
        The four output files keyed by name, and the human-readable report.

    Raises:
        SelectionError: If an input is inconsistent or a type has no candidate.
    """
    sample_path = root / "eval" / "corpora" / CORPUS_NAME / "questions.sample.jsonl"
    diag_path = root / "eval" / "corpora" / CORPUS_NAME / "diag_selection.json"
    populations_path = root / POPULATIONS_REL

    sample = _load_sample(sample_path)
    lines_by_id = {qid: line for qid, _, line in sample}
    type_by_id = {qid: str(raw.get("question_type", "")) for qid, raw, _ in sample}
    query_by_id = {qid: str(raw.get("query", "")) for qid, raw, _ in sample}

    dev_ids = set(
        json.loads(diag_path.read_text(encoding="utf-8"))["drawn_question_ids"]
    )
    g_ids = set(
        json.loads(populations_path.read_text(encoding="utf-8"))["g_question_ids"]
    )
    sample_ids = set(lines_by_id)
    if not dev_ids <= sample_ids:
        raise SelectionError("Dev IDs are not all in questions.sample.jsonl")
    if not g_ids <= sample_ids:
        raise SelectionError("G IDs are not all in questions.sample.jsonl")

    null_ids = {i for i in sample_ids if type_by_id[i] == NULL_QUESTION_TYPE}
    heldout_g = sorted(i for i in sample_ids if i in g_ids and i not in dev_ids)
    heldout_null = sorted(i for i in null_ids if i not in dev_ids)
    pool = sorted(i for i in sample_ids if i not in dev_ids | g_ids | null_ids)
    pool_by_type: dict[str, list[str]] = {}
    for qid in pool:
        pool_by_type.setdefault(type_by_id[qid], []).append(qid)

    rng = random.Random(ORDER_SEED)
    canary_ids = _pick_per_type(rng, pool_by_type, set())
    rehearsal_ids = _pick_per_type(rng, pool_by_type, set(canary_ids))

    split = HeldOutSplit(
        derivation_rule=DERIVATION_RULE,
        populations_sha256=lf_sha256(populations_path),
        diag_selection_sha256=lf_sha256(diag_path),
        questions_sample_sha256=lf_sha256(sample_path),
        dev_source=DEV_SOURCE,
        order_seed=ORDER_SEED,
        dev_ids=sorted(dev_ids),
        heldout_g_ids=heldout_g,
        heldout_null_ids=heldout_null,
    )

    heldout_all = sorted(heldout_g + heldout_null)
    canary_rows = [
        {
            "question_id": qid,
            "question": query_by_id[qid],
            "question_type": type_by_id[qid],
            "min_retrieved_chunks": 1,
        }
        for qid in sorted(canary_ids)
    ]
    files = {
        "heldout_split.json": json.dumps(split.model_dump(), indent=2) + "\n",
        "questions.heldout.jsonl": "".join(lines_by_id[i] + "\n" for i in heldout_all),
        "questions.rehearsal.jsonl": "".join(
            lines_by_id[i] + "\n" for i in sorted(rehearsal_ids)
        ),
        "canary.arms.jsonl": "".join(
            json.dumps(row, ensure_ascii=False) + "\n" for row in canary_rows
        ),
    }

    g_types = Counter(type_by_id[i] for i in heldout_g)
    pool_types = Counter(type_by_id[i] for i in pool)
    report_lines = [
        f"dev: {len(split.dev_ids)} "
        f"({len(dev_ids & g_ids)} G + {len(dev_ids & null_ids)} null)",
        f"heldout G: {len(heldout_g)} "
        + " ".join(f"{t}={g_types[t]}" for t in PICK_TYPES),
        f"heldout null: {len(heldout_null)}",
        f"heldout total: {len(heldout_all)}",
        f"rehearsal pool: {len(pool)} "
        + " ".join(f"{t}={pool_types[t]}" for t in PICK_TYPES),
        f"populations_sha256 (LF): {split.populations_sha256}",
        f"diag_selection_sha256 (LF): {split.diag_selection_sha256}",
        f"questions_sample_sha256 (LF): {split.questions_sample_sha256}",
        f"order_seed: {split.order_seed}",
        "canary picks (D-124): "
        + ", ".join(f"{i} [{type_by_id[i]}]" for i in sorted(canary_ids)),
        "rehearsal picks (D-108): "
        + ", ".join(f"{i} [{type_by_id[i]}]" for i in sorted(rehearsal_ids)),
    ]
    return files, "\n".join(report_lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: `python eval/scripts/select_heldout_split.py [--out-dir D]`."""
    parser = argparse.ArgumentParser(prog="select_heldout_split")
    parser.add_argument(
        "--out-dir",
        dest="out_dir",
        default=None,
        help="Output directory (default eval/corpora/multihop_rag).",
    )
    args = parser.parse_args(argv)

    root = repo_root()
    out_dir = (
        Path(args.out_dir) if args.out_dir else root / "eval" / "corpora" / CORPUS_NAME
    )
    try:
        files, report = build_outputs(root)
    except SelectionError as exc:
        print(f"select_heldout_split: {exc}", flush=True)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        with open(out_dir / name, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    print(report, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
