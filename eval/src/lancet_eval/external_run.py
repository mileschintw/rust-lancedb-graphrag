"""Drive an external arm: answer its context export with the generate-only bin (D-247).

An external arm (``arms.EXTERNAL_ARMS``) retrieves outside Lancet and hands over a
context export, e.g. `baselines/llamaindex`'s `context_export.jsonl` with its
`pipeline_config.json` beside it. `run_external` answers that export with the engine's
own packer, schema and `Answer:` rendering through `generate_from_context` and journals
one `RunRecord` per row into the run's `journal.jsonl`, the same file and resume key
as the Lancet arms. The arm's rows are copied into the run's context export before any
reader call, so every journalled record has its row. The rows are answered in batches
(``GENERATE_BATCH_ROWS``), each journalled as it lands.

Everything is refused before any reader call: an external label that is not an arm of
the corpus, an export that fails the context-export validator or holds another arm's,
corpus's or an unknown question's row, a row without exactly ``EXTERNAL_K`` evidence
entries, a missing or incomplete pipeline echo, a journal begun under another split or
as a gate-stage drive, and a row that differs from the one the run's export already
holds for that question. A `[split]` corpus passes the same gates as `run`
(``run.require_split_gates``).

Each row is packed first (no network): the request body gives the generation model
and provider order the engine sends, which the record echoes for `score` to compare
with the Lancet arms'. A row that cannot be packed, a reader failure and a row the bin
wrote no line for each become an error record, never a missing one. The reader runs
with the ``evidence_metadata`` lever only (D-248: the document metadata reaches the
reader in the same DocMeta tags as Lancet's metadata lever).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from lancet_eval import parity
from lancet_eval.arms import ExternalPipeline, canonical_arm, is_external_arm
from lancet_eval.client import Notice, StructuredCitation
from lancet_eval.context_export import (
    CONTEXT_EXPORT_FILE,
    ContextExportError,
    ContextExportRow,
    read_export,
)
from lancet_eval.corpus import load_corpus_config, load_sample_questions
from lancet_eval.journal import (
    ExternalProvenance,
    Journal,
    RunRecord,
    WorkflowWireMeta,
    journal_key,
    read_journal_header,
)
from lancet_eval.provenance import EXTERNAL_K
from lancet_eval.run import (
    _require_matching_split_marker,
    reconcile_quietly,
    require_split_gates,
    resume_state,
)
from lancet_eval.split import split_sha256

#: The pipeline echo `baselines/llamaindex` writes beside its export.
PIPELINE_CONFIG_FILE = "pipeline_config.json"

#: The levers an external arm is read with (D-248).
EXTERNAL_READER_LEVERS: tuple[str, ...] = ("evidence_metadata",)

#: Rows per bin call. Each call has one timeout (`parity.run_bin`), so a batch must
#: finish well inside it at the reader's latency.
GENERATE_BATCH_ROWS = 16

#: Runs `generate_from_context <mode>` over rows under levers; one line per row.
BinRunner = Callable[
    [str, Sequence[ContextExportRow], Sequence[str]], list[dict[str, Any]]
]

#: The real bin, built through cargo. Tests replace it.
bin_runner: BinRunner = parity.run_bin


class ExternalRunError(Exception):
    """An external arm's export, pipeline echo or run directory is refused."""


@dataclass(frozen=True)
class ExternalRunResult:
    """What one invocation did.

    Attributes:
        appended: Records appended to the journal by this invocation.
        errors: How many of them are error records.
        export_path: The run's context export, holding the arm's rows.
    """

    appended: int
    errors: int
    export_path: Path


def load_pipeline_echo(path: Path) -> tuple[ExternalPipeline, str]:
    """The pipeline and index fingerprint a `pipeline_config.json` echoes.

    The pipeline is read from the file's flat top-level keys; every other key is
    descriptive and ignored.

    Raises:
        ExternalRunError: If the file is missing or unreadable, or lacks a key.
    """
    try:
        echo = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExternalRunError(f"cannot read the pipeline echo {path}: {exc}") from exc
    if not isinstance(echo, dict):
        raise ExternalRunError(f"the pipeline echo {path} is not a JSON object")
    keys = ExternalPipeline.__dataclass_fields__
    missing = [k for k in (*keys, "index_fingerprint") if k not in echo]
    if missing:
        raise ExternalRunError(f"the pipeline echo {path} lacks {missing}")
    fingerprint = echo["index_fingerprint"]
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ExternalRunError(f"the pipeline echo {path} has no index_fingerprint")
    try:
        pipeline = ExternalPipeline(**{k: echo[k] for k in keys})
    except ValidationError as exc:
        raise ExternalRunError(f"the pipeline echo {path} is invalid: {exc}") from exc
    return pipeline, fingerprint


def _arm_rows(
    export_path: Path, *, corpus: str, arm: str, question_ids: set[str]
) -> list[ContextExportRow]:
    try:
        rows = read_export(export_path)
    except (OSError, ContextExportError) as exc:
        raise ExternalRunError(f"refusing the export: {exc}") from exc
    problems: list[str] = []
    for row in rows:
        unit = f"{row.question_id}/{row.arm}"
        if row.corpus != corpus:
            problems.append(f"{unit}: corpus {row.corpus!r}, not {corpus!r}")
        if row.arm != arm:
            problems.append(f"{unit}: arm {row.arm!r}, not {arm!r}")
        if row.question_id not in question_ids:
            problems.append(f"{unit}: not a question of corpus {corpus!r}")
        if row.assembled_prompt is not None:
            problems.append(f"{unit}: an external row carries an assembled_prompt")
        if len(row.evidence) != EXTERNAL_K:
            problems.append(
                f"{unit}: {len(row.evidence)} ranked evidence entries, expected "
                f"{EXTERNAL_K}"
            )
    if problems:
        raise ExternalRunError(
            f"refusing the export {export_path}: " + "; ".join(problems[:10])
        )
    return rows


def _require_external_journal(
    journal_path: Path, *, corpus: str, split_sha: str | None, order_seed: int | None
) -> None:
    """Checks an existing journal's header, or writes a v1.1 header to a new one."""
    header = read_journal_header(journal_path)
    if header is not None and header.get("gate_stage") is not None:
        raise ExternalRunError(
            f"journal {journal_path} is a gate-stage drive "
            f"({header['gate_stage']!r}); its gates must see engine attempts only, so "
            "an external arm cannot append to it (D-67)"
        )
    Journal(journal_path).write_header(
        corpus=corpus,
        partial=True,
        order_seed=order_seed,
        split_sha256=split_sha,
        context_export=True,
    )


def _carried_rows(
    run_export: Path, rows: Sequence[ContextExportRow]
) -> list[ContextExportRow]:
    """The run export's rows; refuses one of `rows`' units that holds another row."""
    if not run_export.is_file():
        return []
    try:
        existing = read_export(run_export)
    except ContextExportError as exc:
        raise ExternalRunError(f"refusing the run's export: {exc}") from exc
    ours = {(r.question_id, r.arm): r for r in rows}
    differing = [
        f"{row.question_id}/{row.arm}"
        for row in existing
        if (row.question_id, row.arm) in ours
        and row != ours[(row.question_id, row.arm)]
    ]
    if differing:
        raise ExternalRunError(
            f"{run_export} already holds a different row for {differing[:10]}: the "
            "journalled answer was read over that row, so an export from another "
            "index cannot join this run; use a fresh run directory"
        )
    return existing


def _write_run_export(
    run_export: Path,
    existing: Sequence[ContextExportRow],
    rows: Sequence[ContextExportRow],
) -> None:
    have = {(r.question_id, r.arm) for r in existing}
    merged = [*existing, *(r for r in rows if (r.question_id, r.arm) not in have)]
    tmp = run_export.parent / f".{CONTEXT_EXPORT_FILE}.tmp.{time.time_ns()}"
    try:
        parity.write_rows(merged, tmp)
        read_export(tmp)
        os.replace(tmp, run_export)
    finally:
        tmp.unlink(missing_ok=True)


def _error_record(row: ContextExportRow, error_type: str, error: str) -> RunRecord:
    return RunRecord(
        corpus=row.corpus,
        question_id=row.question_id,
        graph_arm=row.arm,
        outcome="error",
        error_type=error_type,
        error=error,
    )


def _sent(line: dict[str, Any]) -> tuple[str, list[str]]:
    """The model and provider order of a `pack` line's request body."""
    body = json.loads(line["body"])
    model = body["model"]
    order = body.get("provider", {}).get("order", [])
    if not isinstance(model, str) or not model:
        raise ValueError("the request body names no model")
    if not isinstance(order, list) or not all(isinstance(p, str) for p in order):
        raise ValueError("the request body's provider order is not a list of names")
    return model, order


def _success_record(
    row: ContextExportRow,
    line: dict[str, Any],
    *,
    pipeline: ExternalPipeline,
    fingerprint: str,
    sent: tuple[str, list[str]],
) -> RunRecord:
    usage = line.get("usage") or {}
    return RunRecord(
        corpus=row.corpus,
        question_id=row.question_id,
        graph_arm=row.arm,
        outcome="success",
        answer=line.get("answer") or "",
        structured_citations=[
            StructuredCitation.model_validate(c)
            for c in line.get("structured_citations") or []
        ],
        notices=[Notice.model_validate(n) for n in line.get("notices") or []],
        workflow_meta=WorkflowWireMeta(
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        ),
        external=ExternalProvenance(
            pipeline=pipeline,
            index_fingerprint=fingerprint,
            generation_model=sent[0],
            generation_provider_order=sent[1],
        ),
    )


def _lines_by_unit(
    lines: Sequence[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    by_unit: dict[tuple[str, str], dict[str, Any]] = {}
    for line in lines:
        key = (str(line.get("question_id")), str(line.get("arm")))
        by_unit.setdefault(key, line)
    return by_unit


def _read(
    rows: Sequence[ContextExportRow],
    runner: BinRunner,
    *,
    pipeline: ExternalPipeline,
    fingerprint: str,
) -> list[RunRecord]:
    """Packs then generates `rows`; one record per row, in row order."""
    levers = list(EXTERNAL_READER_LEVERS)
    records: dict[tuple[str, str], RunRecord] = {}
    sent: dict[tuple[str, str], tuple[str, list[str]]] = {}
    packed = _lines_by_unit(_bin(runner, "pack", rows, levers))
    for row in rows:
        unit = (row.question_id, row.arm)
        line = packed.get(unit)
        if line is None:
            records[unit] = _error_record(
                row, "PACK_FAILED", "generate_from_context pack wrote no output line"
            )
        elif line.get("outcome") != "success":
            records[unit] = _error_record(
                row, str(line.get("error_type")), str(line.get("error"))
            )
        else:
            try:
                sent[unit] = _sent(line)
            except (KeyError, TypeError, ValueError) as exc:
                records[unit] = _error_record(
                    row, "PACK_FAILED", f"unreadable request body: {exc}"
                )
    readable = [r for r in rows if (r.question_id, r.arm) in sent]
    generated = (
        _lines_by_unit(_bin(runner, "generate", readable, levers)) if readable else {}
    )
    for row in readable:
        unit = (row.question_id, row.arm)
        line = generated.get(unit)
        if line is None:
            records[unit] = _error_record(
                row,
                "GENERATION_FAILED",
                "generate_from_context generate wrote no output line",
            )
        elif line.get("outcome") != "success":
            records[unit] = _error_record(
                row, str(line.get("error_type")), str(line.get("error"))
            )
        else:
            try:
                records[unit] = _success_record(
                    row,
                    line,
                    pipeline=pipeline,
                    fingerprint=fingerprint,
                    sent=sent[unit],
                )
            except (TypeError, ValueError) as exc:
                records[unit] = _error_record(
                    row, "GENERATION_FAILED", f"unreadable generate line: {exc}"
                )
    return [records[(r.question_id, r.arm)] for r in rows]


def _bin(
    runner: BinRunner,
    mode: str,
    rows: Sequence[ContextExportRow],
    levers: Sequence[str],
) -> list[dict[str, Any]]:
    try:
        return runner(mode, rows, levers)
    except parity.PromptParityError as exc:
        raise ExternalRunError(str(exc)) from exc


def run_external(
    *,
    corpus: str,
    arm: str,
    export_path: Path | str,
    journal_path: Path | str,
    pipeline_config: Path | str | None = None,
    resume: bool = True,
    runner: BinRunner | None = None,
    git_repo: Path | None = None,
) -> ExternalRunResult:
    """Answers an external arm's export and appends its records to the run's journal.

    Args:
        corpus: The corpus name; the arm must be one of its arms.
        arm: The external arm's label (``arms.EXTERNAL_ARMS``).
        export_path: The arm's `context_export.jsonl`.
        journal_path: The run's `journal.jsonl`; the run's context export is the
            `context_export.jsonl` beside it.
        pipeline_config: The arm's pipeline echo; `pipeline_config.json` beside
            `export_path` when None.
        resume: Skip questions the journal already holds a record of. Without it the
            journal must hold no record.
        runner: Runs the bin; ``bin_runner`` when None.
        git_repo: The repository the D-73 gate reads; the live one when None.

    Returns:
        How many records were appended, and where the run's export is.

    Raises:
        ExternalRunError: If the arm, the export, the pipeline echo or the run
            directory is refused (nothing is journalled and no reader is called),
            or when a bin call fails (the batches before it stay journalled).
        JournalReuseError: If ``resume`` is False and the journal holds a record.
    """
    export = Path(export_path)
    target = Path(journal_path)
    config = load_corpus_config(corpus)
    if not is_external_arm(arm):
        raise ExternalRunError(
            f"{arm!r} is not an external arm (D-247); drive an engine arm with `run`"
        )
    if canonical_arm(arm) not in {canonical_arm(a) for a in config.arms}:
        raise ExternalRunError(
            f"{arm!r} is not an arm of corpus {corpus!r}; its arms are {config.arms}"
        )
    questions = load_sample_questions(corpus)
    split = require_split_gates(config, questions, git_repo=git_repo)
    pipeline, fingerprint = load_pipeline_echo(
        export.parent / PIPELINE_CONFIG_FILE
        if pipeline_config is None
        else Path(pipeline_config)
    )
    rows = _arm_rows(
        export,
        corpus=corpus,
        arm=arm,
        question_ids={q.question_id for q in questions},
    )
    run_export = target.parent / CONTEXT_EXPORT_FILE
    existing = _carried_rows(run_export, rows)
    _require_matching_split_marker(target, split)
    done, _ = resume_state(target, resume=resume)
    _require_external_journal(
        target,
        corpus=corpus,
        split_sha=split_sha256(split) if split is not None else None,
        order_seed=split.order_seed if split is not None else None,
    )
    remaining = [r for r in rows if journal_key(corpus, r.question_id, arm) not in done]
    # The rows go in first, so every record journalled below already has its row.
    _write_run_export(run_export, existing, rows)
    records: list[RunRecord] = []
    journal = Journal(target)
    try:
        # One bin call per batch: a timeout or crash loses one batch's answers, and
        # the batches journalled before it stay done for the resume.
        for start in range(0, len(remaining), GENERATE_BATCH_ROWS):
            batch = _read(
                remaining[start : start + GENERATE_BATCH_ROWS],
                runner or bin_runner,
                pipeline=pipeline,
                fingerprint=fingerprint,
            )
            for record in batch:
                journal.append(record)
            records.extend(batch)
    finally:
        reconcile_quietly(target, corpus)
    return ExternalRunResult(
        appended=len(records),
        errors=sum(r.outcome == "error" for r in records),
        export_path=run_export,
    )
