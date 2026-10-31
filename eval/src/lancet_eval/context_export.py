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
for a live store and `InMemoryCheckpointSource` for tests. An S1 journal holds arms of
two stores (D-251), each store's checkpoints in its own schema, so the export can take
one source per store (`store_checkpoint_sources`) and reads each record from the store
its arm label declares (#65). The export fails closed: a success record with no
checkpoint, one that cannot be joined, or one whose store has no source, names its
question and arm, and no file is written.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lancet_eval.arms import arm_store
from lancet_eval.config import (
    EVAL_STORES,
    V1_STORE,
    EvalSettings,
    pg_schema_of,
    store_for_settings,
    with_search_path,
)
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

    Evidence ranks are exactly 1..n in order. A Lancet row carries both
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
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError(f"evidence ranks must be 1..n in order, got {ranks}")
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
_TRACE_IDS_PER_QUERY = 200


class PostgresCheckpointSource:
    """Reads checkpoints from the eval schema's `workflow_checkpoints` table via psql.

    The schema is the `search_path` of `settings.database_url`. Trace IDs are queried
    in batches of `_TRACE_IDS_PER_QUERY` so no statement grows without bound. Every
    failure, psql's or a row's, is raised as `ContextExportError`.
    """

    def __init__(self, settings: EvalSettings) -> None:
        self._settings = settings

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
        for start in range(0, len(ids), _TRACE_IDS_PER_QUERY):
            batch = ids[start : start + _TRACE_IDS_PER_QUERY]
            literals = ", ".join(f"'{t}'" for t in batch)
            sql = (
                "SELECT json_build_object('trace_id', trace_id, 'snapshot', "
                f"context_snapshot)::text FROM {schema}.workflow_checkpoints "
                f"WHERE node_name = 'terminal_success' AND trace_id IN ({literals});\n"
            )
            try:
                output = run_psql(self._settings, sql, timeout_s=120.0)
            except (SeedError, OSError, subprocess.SubprocessError) as exc:
                raise ContextExportError(f"reading checkpoints failed: {exc}") from exc
            for line in output.splitlines():
                if line.strip():
                    rows.append(_parse_checkpoint_line(line))
        return rows


#: One checkpoint source per eval store name (`config.EVAL_STORES`).
StoreSources = Mapping[str, CheckpointSource]


def store_checkpoint_sources(settings: EvalSettings) -> dict[str, CheckpointSource]:
    """A Postgres checkpoint source for each known eval store, keyed by store name.

    The store `settings` target keeps `settings` as they are; every other store reads
    the same database with its own schema as the `search_path` (D-251).
    """
    own = store_for_settings(settings)
    sources: dict[str, CheckpointSource] = {}
    for store in EVAL_STORES.values():
        store_settings = (
            settings
            if store == own
            else settings.model_copy(
                update={
                    "database_url": with_search_path(
                        settings.database_url, store.pg_schema
                    )
                }
            )
        )
        sources[store.name] = PostgresCheckpointSource(store_settings)
    return sources


def _parse_checkpoint_line(line: str) -> CheckpointRow:
    try:
        data = json.loads(line)
        trace_id, snapshot = data["trace_id"], data["snapshot"]
        if not isinstance(trace_id, str) or not isinstance(snapshot, dict):
            raise TypeError("trace_id must be a string and snapshot an object")
        return CheckpointRow(trace_id=trace_id, snapshot=snapshot)
    except (ValueError, KeyError, TypeError) as exc:
        raise ContextExportError(
            f"unreadable checkpoint row from psql: {line[:200]!r}"
        ) from exc


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


#: How many failing units a refusal lists before it says how many more.
_MAX_LISTED_UNITS = 10
_REBUILD_HINT = "Rebuild it with `lancet-eval export-context --run <dir>`"


def _listed(problems: list[str]) -> str:
    more = len(problems) - _MAX_LISTED_UNITS
    listed = "; ".join(problems[:_MAX_LISTED_UNITS])
    return listed + (f" (and {more} more)" if more > 0 else "")


def _unit(record: RunRecord) -> str:
    return f"{record.question_id}/{record.graph_arm}"


def _success_records(journal: Path) -> list[RunRecord]:
    """The journal's success records, one per question and arm (the later one wins)."""
    records, _ = deduplicate_by_arm(load_records(journal))
    return [r for r in records if r.outcome == "success"]


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
    successes = _success_records(journal)
    export_path = journal.parent / CONTEXT_EXPORT_FILE
    if not export_path.is_file():
        if successes:
            units = [_unit(r) for r in successes]
            raise ContextExportError(
                f"{export_path} is missing, so {len(units)} success record(s) have no "
                f"export row: {_listed(units)}. {_REBUILD_HINT}"
            )
        return
    by_unit = {(row.question_id, row.arm): row for row in read_export(export_path)}
    problems: list[str] = []
    for record in successes:
        unit = _unit(record)
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
            f"{_listed(problems)}. {_REBUILD_HINT}"
        )


def _store_name(label: str) -> str:
    """The eval store a label's checkpoints live in; unprefixed labels are v1.0's."""
    return arm_store(label) or V1_STORE.name


def _checkpoints_by_trace(
    records: list[RunRecord], source: CheckpointSource
) -> dict[str, list[Mapping[str, Any]]]:
    """`records`' checkpoints in `source`, by trace ID; one query for all of them."""
    by_trace: dict[str, list[Mapping[str, Any]]] = {}
    wanted = {r.correlation_id for r in records if r.correlation_id}
    for checkpoint in source.terminal_success(wanted) if wanted else []:
        by_trace.setdefault(checkpoint.trace_id, []).append(checkpoint.snapshot)
    return by_trace


def _join_failure(record: RunRecord, snapshots: list[Mapping[str, Any]]) -> str | None:
    """Why `record` cannot be joined on `snapshots`, its checkpoints; None if it can."""
    cid = record.correlation_id
    if not cid:
        return "the record has no correlation_id to join on"
    if not snapshots:
        return f"no terminal_success checkpoint for correlation_id {cid!r}"
    if len(snapshots) > 1:
        return (
            f"{len(snapshots)} terminal_success checkpoints for correlation_id {cid!r}"
        )
    if snapshots[0].get("trace_id") != cid:
        return (
            f"the checkpoint's snapshot trace_id {snapshots[0].get('trace_id')!r} "
            f"is not {cid!r}"
        )
    return None


def export_context(
    journal_path: Path | str, source: CheckpointSource | StoreSources
) -> Path:
    """Writes `context_export.jsonl` beside `journal_path` from its success records.

    `source` is one checkpoint source for every record, or one source per eval store
    name (`store_checkpoint_sources`): then each record is read from the store its arm
    label declares, and a record whose store has no source fails (#65). Rows follow
    the journal's order either way.

    Returns the written path. Raises `ContextExportError`, writing nothing, when a
    success record has no checkpoint, cannot be joined, or has no store source.
    """
    journal = Path(journal_path)
    successes = _success_records(journal)
    per_store = isinstance(source, Mapping)
    # One source alone serves every record under the key "".
    sources: Mapping[str, CheckpointSource] = source if per_store else {"": source}
    failures: list[str] = []
    store_of: dict[int, str] = {}
    for i, record in enumerate(successes):
        try:
            store = _store_name(record.graph_arm) if per_store else ""
        except ValueError as exc:
            failures.append(f"{_unit(record)}: {exc}")
            continue
        if store in sources:
            store_of[i] = store
        else:
            failures.append(
                f"{_unit(record)}: no checkpoint source for store {store!r}"
            )
    by_store = {
        store: _checkpoints_by_trace(
            [successes[i] for i, s in store_of.items() if s == store], sources[store]
        )
        for store in dict.fromkeys(store_of.values())
    }
    rows: list[ContextExportRow] = []
    for i, store in store_of.items():
        record = successes[i]
        snapshots = by_store[store].get(record.correlation_id or "", [])
        failure = _join_failure(record, snapshots)
        if failure is not None:
            failures.append(f"{_unit(record)}: {failure}")
            continue
        try:
            rows.append(validate_row(_row_from_checkpoint(record, snapshots[0])))
        except ContextExportError as exc:
            failures.append(f"{_unit(record)}: {exc}")
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
