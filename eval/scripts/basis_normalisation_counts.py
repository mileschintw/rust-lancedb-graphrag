"""Per-arm, per-question-type counts of normalised records (06.3.5-18, condition 4).

The engine accepts a cited grounded abstention that the model labelled `model_only`
(06.3.5-18). It publishes the answer as `retrieval`, and discloses the override on
every such record with a fixed `BASIS_RECONCILED` notice (typed code 15). The journal
holds no `answer_basis` field, so that notice is the journal-level key. This script
counts, from the journal alone:

- `normalised`: records that carry the fixed notice, and
- `model_only_rejected`: records the engine still rejected with the `model_only`
  message (outcome `error`, a `GenerateAnswer` node failure with that message). These
  are the residual uncited or substantive `model_only` outputs, and pre-fix records.

Counts are per canonical arm (`lancet_eval.arms.canonical_arm`, registry order) and
per `question_type` of the record's corpus. `normalised_not_abstaining` counts
normalised records that the D-118 harness predicate (`metrics.is_abstention`) does not
read as an abstention. The engine's check keys on the same line-start `Answer:` line,
so it must be 0.

It is a standalone read-only diagnostic, not a score or report dimension: the `score`
and `report` path is the D-73 pre-registered analysis, and its shape is pinned by other
tests. It never writes to the run, and imports neither `score` nor `report`. Its only
output is `basis_normalisation.json` under `--out-dir` (default
`<RUN_DIR>/diagnostic`).

An arm label the registry does not know raises `ValueError`, and so does a question ID
absent from its corpus: nothing is silently regrouped or dropped.

Usage: python eval/scripts/basis_normalisation_counts.py RUN_DIR [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lancet_eval.arms import ARM_REGISTRY, canonical_arm
from lancet_eval.corpus import load_sample_questions
from lancet_eval.journal import RunRecord, load_records
from lancet_eval.metrics import is_abstention

#: Typed code of `BASIS_RECONCILED` in `proto` (`NOTICE_CODE_BASIS_RECONCILED`).
BASIS_RECONCILED_TYPED_CODE = 15
#: Byte-equal to `GROUNDED_ABSTENTION_NORMALISED_NOTICE` in
#: `engine/src/generation/mod.rs`. A harness test reads the Rust source and requires
#: equality, so the engine and this script cannot drift apart. The D-18
#: reconciliation notice shares the typed code but not this text.
NORMALISED_NOTICE_MESSAGE = (
    "grounded abstention: the model self-reported answer basis 'model_only' on an "
    "'Answer: Insufficient information' answer that cites the evidence blocks it "
    "checked; the engine normalised the basis to 'retrieval'"
)
#: The message of `validate_output_shape_with_limits` for a `model_only` output.
#: Byte-equal to the literal in `engine/src/generation/mod.rs`; a harness test
#: enforces it.
MODEL_ONLY_REJECTION = (
    "ModelOnly answer basis is not supported on Phase 03 QueryRAG path"
)
#: The node that produces the rejection.
GENERATE_NODE = "GenerateAnswer"
OUT_NAME = "basis_normalisation.json"

KIND_NORMALISED = "normalised"
KIND_REJECTED = "model_only_rejected"


def classify(record: RunRecord) -> str | None:
    """The kind of a record, or `None` when it is neither normalised nor rejected."""
    for notice in record.notices:
        is_reconciled = (
            notice.typed_code == BASIS_RECONCILED_TYPED_CODE
            or notice.code == "BASIS_RECONCILED"
        )
        if is_reconciled and notice.message == NORMALISED_NOTICE_MESSAGE:
            return KIND_NORMALISED
    if record.outcome == "error" and any(
        failure.node_name == GENERATE_NODE
        and failure.error_message == MODEL_ONLY_REJECTION
        for failure in record.node_failures
    ):
        return KIND_REJECTED
    return None


def _empty_block(arms: Sequence[str], question_types: Sequence[str]) -> dict[str, Any]:
    return {
        "total": 0,
        "by_arm": {arm: 0 for arm in arms},
        "by_arm_question_type": {
            arm: {qtype: 0 for qtype in question_types} for arm in arms
        },
    }


def count_records(
    records: Sequence[RunRecord], question_types: Mapping[str, str]
) -> dict[str, Any]:
    """Counts normalised and residual-rejected records per arm and per question type.

    Args:
        records: The journal records, in journal order.
        question_types: Question ID to `question_type` for every question in the
            journal.

    Returns:
        The counts: `records`, `arms`, `question_types`, the `normalised` and
        `model_only_rejected` blocks (`total`, `by_arm`, `by_arm_question_type`, each
        with an explicit 0), `normalised_not_abstaining` and one row per classified
        record.

    Raises:
        ValueError: If a record's arm label is not in the registry, or its question ID
            is not in `question_types`.
    """
    arm_of = [canonical_arm(record.graph_arm) for record in records]
    type_of: list[str] = []
    for record in records:
        if record.question_id not in question_types:
            raise ValueError(
                f"question {record.question_id!r} is not in the corpus "
                f"{record.corpus!r}"
            )
        type_of.append(question_types[record.question_id])

    arms = [arm for arm in ARM_REGISTRY if arm in set(arm_of)]
    present_types = sorted(set(type_of))
    blocks = {
        KIND_NORMALISED: _empty_block(arms, present_types),
        KIND_REJECTED: _empty_block(arms, present_types),
    }
    rows: list[dict[str, Any]] = []
    not_abstaining = 0
    for record, arm, qtype in zip(records, arm_of, type_of, strict=True):
        kind = classify(record)
        if kind is None:
            continue
        block = blocks[kind]
        block["total"] += 1
        block["by_arm"][arm] += 1
        block["by_arm_question_type"][arm][qtype] += 1
        abstains = is_abstention(record)
        if kind == KIND_NORMALISED and not abstains:
            not_abstaining += 1
        rows.append({
            "question_id": record.question_id,
            "arm": arm,
            "question_type": qtype,
            "correlation_id": record.correlation_id,
            "kind": kind,
            "harness_abstains": abstains,
        })
    return {
        "records": len(records),
        "arms": arms,
        "question_types": present_types,
        "normalised": blocks[KIND_NORMALISED],
        "model_only_rejected": blocks[KIND_REJECTED],
        "normalised_not_abstaining": not_abstaining,
        "rows": rows,
    }


def question_type_map(records: Sequence[RunRecord]) -> dict[str, str]:
    """Question ID to `question_type` over every corpus the journal names.

    Raises:
        ValueError: If two corpora give one question ID two different types.
    """
    mapping: dict[str, str] = {}
    for corpus in sorted({record.corpus for record in records}):
        for question in load_sample_questions(corpus):
            known = mapping.get(question.question_id)
            if known is not None and known != question.question_type:
                raise ValueError(
                    f"question {question.question_id!r} has two types across corpora"
                )
            mapping[question.question_id] = question.question_type
    return mapping


def build_counts(run_dir: Path) -> dict[str, Any]:
    """The counts of a run directory's journal.

    Raises:
        FileNotFoundError: If the run has no journal.
        ValueError: If an arm label or a question ID is unknown.
    """
    journal_path = Path(run_dir) / "journal.jsonl"
    if not journal_path.is_file():
        raise FileNotFoundError(f"no journal at {journal_path}")
    records = load_records(journal_path)
    return count_records(records, question_type_map(records))


def render_table(counts: Mapping[str, Any]) -> str:
    """A markdown table of arm by question type, `normalised / model_only_rejected`."""
    qtypes: list[str] = list(counts["question_types"])
    normalised = counts["normalised"]
    rejected = counts["model_only_rejected"]
    lines = [
        "| arm | " + " | ".join(qtypes) + " | total |",
        "|---|" + "---|" * (len(qtypes) + 1),
    ]
    for arm in counts["arms"]:
        cells = [
            f"{normalised['by_arm_question_type'][arm][qtype]} / "
            f"{rejected['by_arm_question_type'][arm][qtype]}"
            for qtype in qtypes
        ]
        total = f"{normalised['by_arm'][arm]} / {rejected['by_arm'][arm]}"
        lines.append(f"| {arm} | " + " | ".join(cells) + f" | {total} |")
    lines.append("")
    lines.append("Cells read `normalised / model_only_rejected`.")
    lines.append(
        f"Totals: normalised {normalised['total']}, "
        f"model_only_rejected {rejected['total']}, "
        f"records {counts['records']}."
    )
    lines.append(f"normalised_not_abstaining: {counts['normalised_not_abstaining']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Writes the counts under `--out-dir` and prints the arm by type table."""
    parser = argparse.ArgumentParser(
        description="Counts of normalised grounded abstentions (read-only)."
    )
    parser.add_argument("run_dir", metavar="RUN_DIR", type=Path)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: <RUN_DIR>/diagnostic).",
    )
    args = parser.parse_args(argv)

    try:
        counts = build_counts(args.run_dir)
    except FileNotFoundError as err:
        print(f"error: {err} (a run directory needs a journal.jsonl)", file=sys.stderr)
        return 2

    out_dir = args.out_dir if args.out_dir is not None else args.run_dir / "diagnostic"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / OUT_NAME, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(counts, indent=2, ensure_ascii=False) + "\n")
    # ASCII only: a redirected Windows stdout in a legacy code page rejects the rest.
    print(render_table(counts).encode("ascii", "replace").decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
