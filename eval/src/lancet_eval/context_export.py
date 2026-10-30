"""Context export: what the reader saw, one row per question and arm (D-249).

Every v1.1 run directory carries `context_export.jsonl` beside its journal. For Lancet
arms the rows come from the engine's `terminal_success` checkpoints, joined on the
record's `correlation_id` (the engine's `trace_id`); other producers (the generate-only
bin, the LlamaIndex project) write the same rows. `validate_row` and `read_export` are
the one validator every producer is checked against.

A row carries the corpus, question ID, arm and question; the ranked evidence (rank,
chunk ID, document ID, full text, title, section path, content type, score, suspicious
flag, document metadata); the graph facts; and, for Lancet arms, `assembled_prompt` and
`correlation_id`. A row has both of the last two or neither. A record that ended with no
evidence exports an empty evidence list, which is distinct from a missing row.

Checkpoints are read through the `CheckpointSource` port: `PostgresCheckpointSource`
for a live store and `InMemoryCheckpointSource` for tests. The export fails closed: a
success record with no checkpoint, or one that cannot be joined, names its question and
arm, and no file is written.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lancet_eval.config import EvalSettings, pg_schema_of
from lancet_eval.journal import RunRecord, load_records, read_journal_header
from lancet_eval.pairing import deduplicate_by_arm
from lancet_eval.seed import SeedError, run_psql

CONTEXT_EXPORT_FILE = "context_export.jsonl"


class ContextExportError(Exception):
    """A context export could not be built, or a row breaks the contract."""


class DocumentMetadata(BaseModel):
    """The publication, document title and date of an evidence entry's document."""

    model_config = ConfigDict(extra="forbid")

    source: str | None
    doc_title: str | None
    published_date: str | None


class EvidenceEntry(BaseModel):
    """One ranked evidence entry handed to the reader."""

    model_config = ConfigDict(extra="forbid")

    rank: int
    chunk_id: str
    document_id: str
    text: str
    title: str | None
    section_path: str | None
    content_type: str | None
    score: float
    suspicious: bool
    document_metadata: DocumentMetadata


class ContextExportRow(BaseModel):
    """One question under one arm, as the reader saw it.

    Evidence ranks start at 1 and strictly increase. A Lancet row carries both
    `assembled_prompt` and `correlation_id`; an external row carries neither.
    """

    model_config = ConfigDict(extra="forbid")

    corpus: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    arm: str = Field(min_length=1)
    question: str
    evidence: list[EvidenceEntry]
    graph_facts: list[dict[str, Any]]
    assembled_prompt: str | None = None
    correlation_id: str | None = None

    @model_validator(mode="after")
    def _check_contract(self) -> Self:
        ranks = [entry.rank for entry in self.evidence]
        if ranks and (ranks[0] < 1 or any(b <= a for a, b in pairwise(ranks))):
            raise ValueError(
                "evidence ranks must start at 1 or above and strictly increase, "
                f"got {ranks}"
            )
        if (self.assembled_prompt is None) != (self.correlation_id is None):
            raise ValueError(
                "assembled_prompt and correlation_id must be both or neither present"
            )
        return self


@dataclass(frozen=True)
class CheckpointRow:
    """One `terminal_success` checkpoint: its trace ID and parsed context snapshot."""

    trace_id: str
    snapshot: Mapping[str, Any]


class CheckpointSource(Protocol):
    """Reads `terminal_success` checkpoints by trace ID."""

    def terminal_success(self, trace_ids: Collection[str]) -> list[CheckpointRow]:
        """The `terminal_success` checkpoints whose trace ID is in `trace_ids`."""
        ...


class InMemoryCheckpointSource:
    """A checkpoint source over rows held in memory, for tests."""

    def __init__(self, rows: Iterable[CheckpointRow]) -> None:
        self._rows = list(rows)

    def terminal_success(self, trace_ids: Collection[str]) -> list[CheckpointRow]:
        wanted = set(trace_ids)
        return [row for row in self._rows if row.trace_id in wanted]


#: A trace ID the Postgres source puts in a SQL literal; anything else is refused.
_SAFE_TRACE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_SAFE_SCHEMA = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgresCheckpointSource:
    """Reads checkpoints from the eval schema's `workflow_checkpoints` table via psql.

    The schema is the `search_path` of `settings.database_url`. Trace IDs are queried
    in batches so no statement grows without bound.
    """

    def __init__(self, settings: EvalSettings, *, batch_size: int = 200) -> None:
        self._settings = settings
        self._batch_size = batch_size

    def terminal_success(self, trace_ids: Collection[str]) -> list[CheckpointRow]:
        schema = pg_schema_of(self._settings.database_url)
        if not _SAFE_SCHEMA.match(schema):
            raise ContextExportError(
                f"eval schema {schema!r} from database_url is not a plain SQL "
                "identifier"
            )
        ids = sorted(set(trace_ids))
        unsafe = [t for t in ids if not _SAFE_TRACE_ID.match(t)]
        if unsafe:
            raise ContextExportError(
                f"refusing to query trace_id(s) outside [A-Za-z0-9._:-]: {unsafe[:3]}"
            )
        rows: list[CheckpointRow] = []
        for start in range(0, len(ids), self._batch_size):
            batch = ids[start : start + self._batch_size]
            literals = ", ".join(f"'{t}'" for t in batch)
            sql = (
                "SELECT json_build_object('trace_id', trace_id, 'snapshot', "
                f"context_snapshot)::text FROM {schema}.workflow_checkpoints "
                f"WHERE node_name = 'terminal_success' AND trace_id IN ({literals});\n"
            )
            try:
                output = run_psql(self._settings, sql, timeout_s=120.0)
            except SeedError as exc:
                raise ContextExportError(f"reading checkpoints failed: {exc}") from exc
            for line in output.splitlines():
                if line.strip():
                    data = json.loads(line)
                    rows.append(
                        CheckpointRow(
                            trace_id=data["trace_id"], snapshot=data["snapshot"]
                        )
                    )
        return rows


def _evidence_entry(block: Mapping[str, Any]) -> dict[str, Any]:
    meta = block.get("evidence_meta") or {}
    return {
        "rank": block.get("rank"),
        "chunk_id": block.get("chunk_id"),
        "document_id": block.get("document_id"),
        "text": block.get("text"),
        "title": block.get("title"),
        "section_path": block.get("section_path"),
        "content_type": block.get("content_type"),
        "score": block.get("score"),
        "suspicious": block.get("suspicious"),
        "document_metadata": {
            "source": meta.get("source"),
            "doc_title": meta.get("doc_title"),
            "published_date": meta.get("published_date"),
        },
    }


def _row_from_checkpoint(
    record: RunRecord, snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "corpus": record.corpus,
        "question_id": record.question_id,
        "arm": record.graph_arm,
        "question": snapshot.get("original_query"),
        "evidence": [_evidence_entry(b) for b in snapshot.get("evidence_blocks") or []],
        "graph_facts": snapshot.get("graph_facts"),
        "assembled_prompt": snapshot.get("assembled_prompt"),
        "correlation_id": record.correlation_id,
    }


def validate_row(data: object) -> ContextExportRow:
    """Checks one decoded row against the contract; raises `ContextExportError`."""
    try:
        return ContextExportRow.model_validate(data)
    except ValidationError as exc:
        raise ContextExportError(
            f"row breaks the context-export contract: {exc}"
        ) from exc


def read_export(path: Path | str) -> list[ContextExportRow]:
    """Reads and validates a whole export: every row, and one row per question and arm.

    Raises `ContextExportError` naming the first bad line.
    """
    rows: list[ContextExportRow] = []
    seen: set[tuple[str, str]] = set()
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = validate_row(json.loads(line))
            except (ValueError, ContextExportError) as exc:
                raise ContextExportError(f"{path} line {line_num}: {exc}") from exc
            key = (row.question_id, row.arm)
            if key in seen:
                raise ContextExportError(
                    f"{path} line {line_num}: a second row for "
                    f"{row.question_id}/{row.arm}"
                )
            seen.add(key)
            rows.append(row)
    return rows


#: How many missing or stale units a refusal lists before it says how many more.
_LISTED = 10


def _listed(problems: list[str]) -> str:
    more = len(problems) - _LISTED
    return "; ".join(problems[:_LISTED]) + (f" (and {more} more)" if more > 0 else "")


def require_export_rows(journal_path: Path | str) -> None:
    """Refuses a v1.1 run whose export lacks a row for a success record (D-249).

    A journal whose header has no ``context_export`` marker predates the context
    export and needs none. Otherwise every success record needs a valid row for its
    question and arm and, when the row carries a `correlation_id`, the record's own.
    Raises `ContextExportError` naming each unit that fails.
    """
    journal = Path(journal_path)
    header = read_journal_header(journal) or {}
    if not header.get("context_export"):
        return
    records, _ = deduplicate_by_arm(load_records(journal))
    successes = [r for r in records if r.outcome == "success"]
    export_path = journal.parent / CONTEXT_EXPORT_FILE
    if not export_path.is_file():
        if successes:
            units = [f"{r.question_id}/{r.graph_arm}" for r in successes]
            raise ContextExportError(
                f"{export_path} is missing, so {len(units)} success record(s) have no "
                f"export row: {_listed(units)}. Rebuild it with "
                "`lancet-eval export-context --run <dir>`"
            )
        return
    by_unit = {(row.question_id, row.arm): row for row in read_export(export_path)}
    problems: list[str] = []
    for record in successes:
        unit = f"{record.question_id}/{record.graph_arm}"
        row = by_unit.get((record.question_id, record.graph_arm))
        if row is None:
            problems.append(f"{unit}: no export row")
        elif (
            row.correlation_id is not None
            and row.correlation_id != record.correlation_id
        ):
            problems.append(
                f"{unit}: the export row is from correlation_id "
                f"{row.correlation_id!r}, "
                f"the record from {record.correlation_id!r}"
            )
    if problems:
        raise ContextExportError(
            f"{export_path} does not cover {len(problems)} success record(s): "
            f"{_listed(problems)}. Rebuild it with "
            "`lancet-eval export-context --run <dir>`"
        )


def export_context(journal_path: Path | str, source: CheckpointSource) -> Path:
    """Writes `context_export.jsonl` beside `journal_path` from its success records.

    Returns the written path. Raises `ContextExportError`, writing nothing, when a
    success record has no checkpoint or cannot be joined.
    """
    journal = Path(journal_path)
    records, _ = deduplicate_by_arm(load_records(journal))
    successes = [r for r in records if r.outcome == "success"]
    by_trace: dict[str, list[Mapping[str, Any]]] = {}
    wanted = {r.correlation_id for r in successes if r.correlation_id}
    for checkpoint in source.terminal_success(wanted) if wanted else []:
        by_trace.setdefault(checkpoint.trace_id, []).append(checkpoint.snapshot)
    rows: list[ContextExportRow] = []
    failures: list[str] = []
    for record in successes:
        unit = f"{record.question_id}/{record.graph_arm}"
        cid = record.correlation_id
        snapshots = by_trace.get(cid, []) if cid else []
        if not cid:
            failures.append(f"{unit}: the record has no correlation_id to join on")
        elif not snapshots:
            failures.append(
                f"{unit}: no terminal_success checkpoint for correlation_id {cid!r}"
            )
        elif len(snapshots) > 1:
            failures.append(
                f"{unit}: {len(snapshots)} terminal_success checkpoints for "
                f"correlation_id {cid!r}"
            )
        elif snapshots[0].get("trace_id") != cid:
            failures.append(
                f"{unit}: the checkpoint's snapshot trace_id "
                f"{snapshots[0].get('trace_id')!r} is not {cid!r}"
            )
        else:
            try:
                rows.append(validate_row(_row_from_checkpoint(record, snapshots[0])))
            except ContextExportError as exc:
                failures.append(f"{unit}: {exc}")
    if failures:
        raise ContextExportError(
            f"context export failed closed on {len(failures)} success record(s): "
            + "; ".join(failures)
        )
    target = journal.parent / CONTEXT_EXPORT_FILE
    tmp = journal.parent / f".{CONTEXT_EXPORT_FILE}.tmp.{time.time_ns()}"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(
                    json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n"
                )
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return target
