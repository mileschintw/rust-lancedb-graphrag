"""The closed-book column of a reader grid (D-291): the question, no context.

A closed-book cell asks a reader the question with no evidence and no graph facts, so
it measures what the reader already knows (the plan's guard against memorised
Wikipedia answers). It has no drive. ``closed_book_init`` starts its run directory the
way ``replay-init`` starts a column with a drive, so ``batch submit`` and ``fetch``
read it unchanged:

- one export row per corpus question under the column's source arm (the closed-book
  arm, ``twowiki/closed-book``), with no evidence and no graph facts. Its
  ``assembled_prompt`` is the user message ``generate_from_context pack`` builds for
  it with model-only answers allowed (the engine's model-only prompt), and its
  ``correlation_id`` is ``closed-book-<question ID>``;
- a journal header that carries those rows' hashes under ``replay_source``, with
  ``closed_book: true`` and no source run, and no record. ``batch submit`` then sends
  deepseek's replicates 1 to K through the sync API and each reader's through its
  batch, every question replayed (``batch._base_records``).

It refuses, before writing anything: a corpus that names no run-plan column, a column
whose source arm is not the closed-book arm, a failed D-73 or split gate (as ``run``
applies them), a run directory that already holds a journal or export, and any row the
bin cannot pack. ``pack`` makes no network call, so this step is free.
"""

from __future__ import annotations

import json
from pathlib import Path

from lancet_eval import batch, gitcheck, parity
from lancet_eval.arms import is_closed_book_arm
from lancet_eval.context_export import CONTEXT_EXPORT_FILE, ContextExportRow
from lancet_eval.journal import Journal
from lancet_eval.replay import (
    JOURNAL_FILE,
    ReplayError,
    ReplayInitResult,
    _declared_source_arm,
    _dev_corpus,
    _listed,
    _refuse_populated,
    export_row_sha256,
    require_d73,
)
from lancet_eval.run import require_split_gates
from lancet_eval.split import split_sha256

CORRELATION_PREFIX = "closed-book-"


def closed_book_init(*, run: Path | str, corpus: str) -> ReplayInitResult:
    """Writes a closed-book column's journal header and export rows (module docstring).

    Args:
        run: The new run directory.
        corpus: The column's corpus: a run-plan corpus whose column's source arm is
            the closed-book arm.

    Returns:
        The paths written; ``records`` is 0.

    Raises:
        ReplayError: If any check in the module docstring fails.
    """
    target = Path(run)
    journal_path = target / JOURNAL_FILE
    export_path = target / CONTEXT_EXPORT_FILE
    _refuse_populated(journal_path)
    _refuse_populated(export_path)
    config = _dev_corpus(corpus, "corpus")
    if config.preregistration_column is None:
        raise ReplayError(
            f"D-291: the corpus {corpus!r} names no run-plan column; a closed-book run "
            "reads a column of a frozen run plan"
        )
    arm = _declared_source_arm(config)
    if not is_closed_book_arm(arm):
        raise ReplayError(
            f"D-291: the corpus {corpus!r} reads column "
            f"{config.preregistration_column!r}, whose source arm {arm!r} is not the "
            "closed-book arm; drive it and carry it with replay-init"
        )
    require_d73(config.preregistration_token)
    questions = config.questions
    try:
        split = require_split_gates(config, questions)
    except (gitcheck.PreregistrationError, ValueError) as exc:
        raise ReplayError(str(exc)) from exc
    rows = [
        ContextExportRow(
            corpus=corpus,
            question_id=q.question_id,
            arm=arm,
            question=q.question,
            evidence=[],
            graph_facts=[],
        )
        for q in questions
    ]
    rows = _with_prompts(rows)
    target.mkdir(parents=True, exist_ok=True)
    Journal(journal_path).write_header(
        corpus=corpus,
        partial=False,
        order_seed=None if split is None else split.order_seed,
        split_sha256=None if split is None else split_sha256(split),
        context_export=True,
        replay_source={
            "run": None,
            "corpus": corpus,
            "arms": [arm],
            "row_sha256": {arm: {r.question_id: export_row_sha256(r) for r in rows}},
            "pilot": False,
            "closed_book": True,
        },
    )
    with open(export_path, "w", encoding="utf-8") as f:
        f.writelines(
            json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n"
            for row in rows
        )
    return ReplayInitResult(
        journal_path=journal_path, export_path=export_path, records=0, rows=len(rows)
    )


def _with_prompts(rows: list[ContextExportRow]) -> list[ContextExportRow]:
    """Each row with the user message the bin packs for it, model-only allowed."""
    try:
        lines = batch.bin_runner("pack", rows, [], model_only=True)
    except parity.PromptParityError as exc:
        raise ReplayError(str(exc)) from exc
    by_qid = {
        str(line.get("question_id")): line
        for line in lines
        if line.get("arm") == (rows[0].arm if rows else None)
    }
    problems: list[str] = []
    out: list[ContextExportRow] = []
    for row in rows:
        line = by_qid.get(row.question_id)
        if line is None or line.get("outcome") != "success":
            why = "no line" if line is None else line.get("error")
            problems.append(f"{row.question_id}: pack failed: {why}")
            continue
        try:
            prompt = parity.user_message(str(line["body"]))
        except (KeyError, TypeError, ValueError) as exc:
            problems.append(f"{row.question_id}: {exc}")
            continue
        out.append(
            row.model_copy(
                update={
                    "assembled_prompt": prompt,
                    "correlation_id": f"{CORRELATION_PREFIX}{row.question_id}",
                }
            )
        )
    if problems:
        raise ReplayError(
            f"closed-book-init refused: {len(problems)} row(s) did not pack: "
            f"{_listed(problems)}"
        )
    return out
