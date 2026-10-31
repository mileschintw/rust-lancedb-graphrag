"""S2 replay runs (#52, D-254, D-257): carried deepseek records and replay provenance.

An S2 run replays an S1 arm's context to Claude readers. Its run directory scores by
itself (Q9), so ``replay_init`` first copies the S1 arm's records (the deepseek
reader's) and their context-export rows into a new S2 journal, byte for byte. The
journal header records where they came from under ``REPLAY_SOURCE_KEY``:

- ``run``: the S1 run directory, as given;
- ``arms``: the carried arm labels, in the order given;
- ``row_sha256``: ``{arm: {question_id: export_row_sha256(row)}}`` for every carried
  row.

The reader arms' records (``<arm>@<reader>``, ``journal.ReplayProvenance``) are
appended later by ``batch fetch`` (#53), each with an export row that is the carried
row under the reader arm's label. ``require_replay_provenance`` runs the replay clauses
(``provenance.REPLAY_CODES``) over them when the run is scored.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lancet_eval.arms import canonical_arm, is_reader_arm
from lancet_eval.context_export import (
    CONTEXT_EXPORT_FILE,
    ContextExportError,
    ContextExportRow,
    read_export,
)
from lancet_eval.journal import (
    Journal,
    RunRecord,
    load_records,
    read_journal_header,
)

#: The S2 journal header key that records the carried source (module docstring).
REPLAY_SOURCE_KEY = "replay_source"
JOURNAL_FILE = "journal.jsonl"
_LISTED = 20


class ReplayError(ValueError):
    """A replay run could not be carried, or its replay provenance fails."""


def export_row_sha256(row: ContextExportRow) -> str:
    """SHA-256 of a context-export row's canonical JSON (sorted keys, compact)."""
    canonical = json.dumps(
        row.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReplayInitResult:
    """What ``replay_init`` carried."""

    journal_path: Path
    export_path: Path
    records: int
    rows: int


def _listed(problems: Sequence[str]) -> str:
    shown = "; ".join(problems[:_LISTED])
    more = len(problems) - _LISTED
    return shown + (f" (and {more} more)" if more > 0 else "")


def _canonical_arms(arms: Sequence[str]) -> list[str]:
    if not arms:
        raise ReplayError("--arms names no arm")
    seen: list[str] = []
    for label in arms:
        try:
            canonical = canonical_arm(label)
        except ValueError as exc:
            raise ReplayError(str(exc)) from exc
        if is_reader_arm(canonical):
            raise ReplayError(
                f"{label!r} is a reader arm: replay-init carries the S1 arm a reader "
                "arm replays, not a reader arm (D-257)"
            )
        if canonical in seen:
            raise ReplayError(f"--arms names {label!r} twice")
        seen.append(canonical)
    return seen


def _refuse_populated(path: Path) -> None:
    if path.is_file() and path.stat().st_size > 0:
        raise ReplayError(
            f"replay-init refused: {path} already holds data; carry into a fresh "
            "run directory"
        )


def _record_lines(journal: Path, arms: set[str]) -> list[tuple[str, RunRecord]]:
    """The journal's record lines whose arm is one of ``arms``, as written."""
    lines: list[tuple[str, RunRecord]] = []
    with open(journal, encoding="utf-8") as f:
        for line_num, raw in enumerate(f, 1):
            text = raw.rstrip("\r\n")
            try:
                data = json.loads(text)
            except ValueError:
                continue
            if not isinstance(data, dict) or "graph_arm" not in data:
                continue
            try:
                record = RunRecord.model_validate(data)
                arm = canonical_arm(record.graph_arm)
            except ValueError as exc:
                raise ReplayError(f"{journal} line {line_num}: {exc}") from exc
            if arm in arms:
                lines.append((text, record))
    return lines


def _export_lines(export: Path) -> dict[tuple[str, str], tuple[str, ContextExportRow]]:
    """The export's rows by ``(question_id, arm)``, each with its line as written."""
    if not export.is_file():
        return {}
    try:
        rows = read_export(export)
    except ContextExportError as exc:
        raise ReplayError(str(exc)) from exc
    texts = [
        line.rstrip("\r\n")
        for line in export.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {
        (row.question_id, row.arm): (text, row)
        for text, row in zip(texts, rows, strict=True)
    }


def replay_init(
    *, source_run: Path | str, arms: Sequence[str], run: Path | str
) -> ReplayInitResult:
    """Carries S1 arms' records and export rows into a new S2 journal (D-257, Q9).

    Every record of each arm is copied as written, error records included, and the
    export row of each success record with it. Nothing is written unless every check
    passes.

    Args:
        source_run: The S1 run directory (``journal.jsonl`` and
            ``context_export.jsonl``).
        arms: The S1 arm labels to carry.
        run: The S2 run directory.

    Returns:
        The paths written and the counts carried.

    Raises:
        ReplayError: If an arm is unknown, repeated, a reader arm, or holds no record
            in the source run; a success record of a carried arm has no export row; or
            the S2 journal or export already holds data.
    """
    source = Path(source_run)
    target = Path(run)
    wanted = _canonical_arms(arms)
    journal_path = target / JOURNAL_FILE
    export_path = target / CONTEXT_EXPORT_FILE
    _refuse_populated(journal_path)
    _refuse_populated(export_path)

    source_journal = source / JOURNAL_FILE
    if not source_journal.is_file():
        raise ReplayError(f"the source run has no journal: {source_journal}")
    records = _record_lines(source_journal, set(wanted))
    held = {canonical_arm(rec.graph_arm) for _, rec in records}
    absent = [arm for arm in wanted if arm not in held]
    if absent:
        in_run = sorted({
            canonical_arm(r.graph_arm) for r in load_records(source_journal)
        })
        raise ReplayError(
            f"arm(s) {absent} hold no record in the source run {source}; its arms are "
            f"{in_run}"
        )
    rows = _export_lines(source / CONTEXT_EXPORT_FILE)
    missing = [
        f"{rec.question_id}/{rec.graph_arm}"
        for _, rec in records
        if rec.outcome == "success" and (rec.question_id, rec.graph_arm) not in rows
    ]
    if missing:
        raise ReplayError(
            f"{len(missing)} success record(s) of the carried arm(s) have no export "
            f"row in {source / CONTEXT_EXPORT_FILE}: {_listed(missing)}"
        )

    carried_rows: dict[tuple[str, str], tuple[str, ContextExportRow]] = {}
    for _, rec in records:
        key = (rec.question_id, rec.graph_arm)
        if key in rows:
            carried_rows[key] = rows[key]
    hashes: dict[str, dict[str, str]] = {}
    for (qid, arm), (_, row) in carried_rows.items():
        hashes.setdefault(canonical_arm(arm), {})[qid] = export_row_sha256(row)

    header = read_journal_header(source_journal) or {}
    Journal(journal_path).write_header(
        corpus=str(header.get("corpus") or records[0][1].corpus),
        partial=bool(header.get("partial", False)),
        order_seed=header.get("order_seed"),
        split_sha256=header.get("split_sha256"),
        context_export=True,
        replay_source={"run": str(source), "arms": wanted, "row_sha256": hashes},
    )
    with open(journal_path, "a", encoding="utf-8") as f:
        f.writelines(text + "\n" for text, _ in records)
    with open(export_path, "w", encoding="utf-8") as f:
        f.writelines(text + "\n" for text, _ in carried_rows.values())
    return ReplayInitResult(
        journal_path=journal_path,
        export_path=export_path,
        records=len(records),
        rows=len(carried_rows),
    )


def source_row_hashes(header: Mapping[str, Any] | None) -> dict[tuple[str, str], str]:
    """The carried rows' hashes a journal header records, by ``(question_id, arm)``.

    Empty for a header without ``REPLAY_SOURCE_KEY`` or with a malformed one: the
    ``row_hash`` clause then fails for every reader record.
    """
    source = (header or {}).get(REPLAY_SOURCE_KEY)
    by_arm = source.get("row_sha256") if isinstance(source, dict) else None
    if not isinstance(by_arm, dict):
        return {}
    return {
        (qid, arm): digest
        for arm, by_qid in by_arm.items()
        if isinstance(by_qid, dict)
        for qid, digest in by_qid.items()
        if isinstance(digest, str)
    }


def require_replay_provenance(
    records: Sequence[RunRecord], journal_path: Path | str, token: str | None
) -> None:
    """Refuses a run whose reader-arm records break a replay clause (D-257).

    A run with no reader-arm record passes untouched. Otherwise the pre-registration
    ``token`` names must declare each reader, and every reader-arm record is checked
    against the run's context export, the header's carried row hashes and its
    reader's declaration (``provenance.replay_run_failures``).

    Args:
        records: The deduplicated journal records.
        journal_path: The journal; its header and the export beside it are read.
        token: The corpus's pre-registration token.

    Raises:
        ReplayError: Naming the clause, the arm and the question of each failure.
    """
    from lancet_eval import preregistration, provenance

    if not any(is_reader_arm(r.graph_arm) for r in records):
        return
    if not token:
        raise ReplayError(
            "D-257: model: the corpus names no pre-registration, so a reader arm has "
            "no declared reader to be compared with"
        )
    try:
        readers = preregistration.readers_of(preregistration.resolve(token))
    except preregistration.PreregistrationError as exc:
        raise ReplayError(f"D-257: model: {exc}") from exc
    journal = Path(journal_path)
    export = journal.parent / CONTEXT_EXPORT_FILE
    try:
        rows = read_export(export) if export.is_file() else []
    except ContextExportError as exc:
        raise ReplayError(f"D-257: row_hash: {exc}") from exc
    failures = provenance.replay_run_failures(
        records,
        export_rows={(row.question_id, row.arm): row for row in rows},
        source_row_sha256=source_row_hashes(read_journal_header(journal)),
        readers=readers,
    )
    if failures:
        listed = _listed([f"{f.code} {f.label} {f.detail}" for f in failures])
        raise ReplayError(
            f"D-257: reader arm provenance failed {len(failures)} time(s) (zero "
            f"tolerance): {listed}"
        )
