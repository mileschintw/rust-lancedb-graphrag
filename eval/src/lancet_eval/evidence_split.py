"""The evidence split of a replay run's answers (#143, the exploratory S2X run).

Splits each G question by whether every gold fact is in the reader's context
(``metrics.gold_contained``, with its D-276 plural and list folds, over the evidence
texts joined by spaces, so a fact may span two neighbouring entries) and by whether
its gold answer is a bare yes or no, then counts each reader's answers per cell:
``answer_usable`` and the abstention rate (``metrics.is_abstention``) over every
``success`` answer, replicates included. Null questions and error records are left out.
It reads a run; it decides nothing.

A reader arm (``<base>@<reader>``) has no export row of its own: it read the packed
prompt of its base arm's row, so its context is that row's.

Run it as ``python -m lancet_eval.evidence_split --run <run dir> --corpus <corpus>``;
``--moved <export> <before arm> <after arm>`` counts only ``moved_questions``.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from lancet_eval.arms import arm_reader, reader_base_arm
from lancet_eval.context_export import ContextExportRow, read_export
from lancet_eval.corpus import GoldQuestion, load_corpus
from lancet_eval.journal import RunRecord, load_records
from lancet_eval.metrics import answer_usable, gold_contained, is_abstention
from lancet_eval.pairing import deduplicate_by_arm

#: The reader of a base (carried) arm: the engine's generation model.
BASE_READER = "deepseek"
EVIDENCE = ("complete", "partial", "all")
KINDS = ("yes/no", "open", "all")


@dataclass(frozen=True)
class SplitCell:
    """One reader's answers on one evidence and kind cell."""

    reader: str
    evidence: str
    kind: str
    n_questions: int
    n_answers: int
    answer_usable: float
    abstention: float


def evidence_complete(question: GoldQuestion, row: ContextExportRow) -> bool:
    """True when every gold fact is contained in the row's evidence texts, joined."""
    text = " ".join(entry.text for entry in row.evidence)
    return all(gold_contained(fact, text) for fact in question.gold_facts)


def is_yes_no(question: GoldQuestion) -> bool:
    """True when the gold answer is a bare yes or no."""
    return question.gold_answer.strip().lower() in ("yes", "no")


def reader_of(arm: str) -> str:
    """The reader an arm label names: the part after ``@``, else ``BASE_READER``."""
    return arm_reader(arm) or BASE_READER


def moved_questions(
    questions: Mapping[str, GoldQuestion],
    export_rows: Mapping[tuple[str, str], ContextExportRow],
    before: str,
    after: str,
) -> set[str]:
    """The G questions whose evidence is partial under ``before`` and complete under
    ``after`` (both arms' rows in ``export_rows``, as in the S1 run's export)."""
    return {
        qid
        for (qid, arm), row in export_rows.items()
        if arm == before
        and not questions[qid].is_null
        and not evidence_complete(questions[qid], row)
        and evidence_complete(questions[qid], _row(export_rows, qid, after))
    }


def _row(
    export_rows: Mapping[tuple[str, str], ContextExportRow], qid: str, arm: str
) -> ContextExportRow:
    try:
        return export_rows[(qid, arm)]
    except KeyError:
        raise ValueError(f"no context export row for {qid} under {arm}") from None


def split_cells(
    records: Sequence[RunRecord],
    questions: Mapping[str, GoldQuestion],
    export_rows: Mapping[tuple[str, str], ContextExportRow],
    only: Collection[str] | None = None,
) -> list[SplitCell]:
    """Counts each reader's G answers per evidence and kind cell, totals included.

    Args:
        records: A replay run's records, deduplicated: one base arm and its reader
            arms.
        questions: Gold questions by ID.
        export_rows: Context export rows by (question ID, arm).
        only: When given, only these question IDs are counted.

    Returns:
        One cell per reader, evidence (complete, partial, all) and kind (yes/no, open,
        all) that holds at least one answer, readers in first-seen order.

    Raises:
        ValueError: The records hold more than one base arm.
    """
    bases = sorted({reader_base_arm(record.graph_arm) for record in records})
    if len(bases) > 1:
        raise ValueError(f"a replay run has one base arm; got {bases}")
    answers: dict[tuple[str, str, str], list[tuple[str, bool, bool]]] = defaultdict(
        list
    )
    for record in records:
        question = questions[record.question_id]
        if record.outcome != "success" or question.is_null:
            continue
        if only is not None and record.question_id not in only:
            continue
        row = _row(export_rows, record.question_id, bases[0])
        evidence = "complete" if evidence_complete(question, row) else "partial"
        kind = "yes/no" if is_yes_no(question) else "open"
        answer = (
            record.question_id,
            answer_usable(question, record.answer or ""),
            is_abstention(record),
        )
        reader = reader_of(record.graph_arm)
        for e in (evidence, "all"):
            for k in (kind, "all"):
                answers[(reader, e, k)].append(answer)
    readers = list(dict.fromkeys(reader for reader, _, _ in answers))
    cells: list[SplitCell] = []
    for reader in readers:
        for e in EVIDENCE:
            for k in KINDS:
                got = answers.get((reader, e, k))
                if not got:
                    continue
                cells.append(
                    SplitCell(
                        reader=reader,
                        evidence=e,
                        kind=k,
                        n_questions=len({qid for qid, _, _ in got}),
                        n_answers=len(got),
                        answer_usable=sum(u for _, u, _ in got) / len(got),
                        abstention=sum(a for _, _, a in got) / len(got),
                    )
                )
    return cells


def render_markdown(cells: Sequence[SplitCell], store: str) -> str:
    """A Markdown table, one line per cell."""
    lines = [
        "| store | reader | evidence | kind | questions | answers | answer_usable "
        "| abstention |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {store} | {c.reader} | {c.evidence} | {c.kind} | {c.n_questions} "
        f"| {c.n_answers} | {c.answer_usable:.3f} | {c.abstention:.3f} |"
        for c in cells
    ]
    return "\n".join(lines)


def _rows(path: Path) -> dict[tuple[str, str], ContextExportRow]:
    return {(r.question_id, r.arm): r for r in read_export(path)}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument(
        "--moved",
        nargs=3,
        metavar=("EXPORT", "BEFORE_ARM", "AFTER_ARM"),
        help="count only the questions partial under BEFORE_ARM and complete under "
        "AFTER_ARM in that context export",
    )
    args = parser.parse_args(argv)
    records, _ = deduplicate_by_arm(load_records(args.run / "journal.jsonl"))
    questions = {q.question_id: q for q in load_corpus(args.corpus).questions}
    only = None
    if args.moved:
        export, before, after = args.moved
        only = moved_questions(questions, _rows(Path(export)), before, after)
    cells = split_cells(
        records, questions, _rows(args.run / "context_export.jsonl"), only=only
    )
    store = "+".join(sorted({r.graph_arm.partition("/")[0] for r in records}))
    print(render_markdown(cells, store))


if __name__ == "__main__":
    main()
