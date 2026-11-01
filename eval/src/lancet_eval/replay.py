"""S2 replay runs (#52, D-254, D-257): carried deepseek records and replay provenance.

An S2 run replays an S1 arm's context to Claude readers. Its run directory scores by
itself (Q9), so ``replay_init`` first copies the S1 arm's records (the deepseek
reader's) and their context-export rows into a new S2 journal on the S2 corpus. Only
``corpus`` changes, in the header, every carried record and every carried row: ``score``
reads the corpus's arms and pre-registration from the header and refuses records that
name another corpus. Both corpora must have ``[split] role = "dev"``: an S0 run read
the held-out split, and replaying it would spend a held-out read D-237 does not have.
The journal header records where the carried lines came from under
``REPLAY_SOURCE_KEY``:

- ``run``: the S1 run directory, as given;
- ``corpus``: the S1 run's corpus;
- ``arms``: the carried arm labels, in the order given;
- ``row_sha256``: ``{arm: {question_id: export_row_sha256(row)}}`` for every carried
  row, as carried (under the S2 corpus). The S1 row is that row with ``corpus`` set
  back to the S1 corpus;
- ``pilot``: whether the run is a pilot run (below).

A run is either a run of record or a pilot run (#109). A pilot (``batch submit --limit
N``, D-254) checks the readers' wire behaviour before the S2 constant is final; its
records could not be replaced in a run of record once the pilot moves a reader to
another target (D-260), so it gets its own run directory, made with ``pilot=True``.
``replay_init`` into a run of record refuses before any paid call unless:

- D-73 holds for the S2 corpus's pre-registration: committed in an ancestor of HEAD,
  the tree clean and the value unchanged since (the gate ``score`` and
  ``compare-levers`` apply after the spend; ``batch submit`` repeats it against the
  header's ``created_at``);
- the carried arms are exactly the constant's ``replay_source_arm``, a known arm label
  that is not a reader arm, so a placeholder left before S1's Result is refused;
- the source run is not partial and its arm holds a record of every question of the
  source corpus.

A pilot run skips these three checks, and ``require_replay_provenance`` refuses to
score or compare it.

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

from lancet_eval import gitcheck, preregistration
from lancet_eval.arms import canonical_arm, is_reader_arm
from lancet_eval.context_export import (
    CONTEXT_EXPORT_FILE,
    ContextExportError,
    ContextExportRow,
    read_export,
)
from lancet_eval.corpus import CorpusConfig, CorpusError, load_corpus
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


def _source_records(journal: Path, arms: set[str]) -> list[RunRecord]:
    """The journal's records whose arm is one of ``arms``, in journal order."""
    records: list[RunRecord] = []
    with open(journal, encoding="utf-8") as f:
        for line_num, raw in enumerate(f, 1):
            try:
                data = json.loads(raw)
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
                records.append(record)
    return records


def _export_rows(export: Path) -> dict[tuple[str, str], ContextExportRow]:
    """The export's rows by ``(question_id, arm)``."""
    if not export.is_file():
        return {}
    try:
        rows = read_export(export)
    except ContextExportError as exc:
        raise ReplayError(str(exc)) from exc
    return {(row.question_id, row.arm): row for row in rows}


def _dev_corpus(name: str, which: str) -> CorpusConfig:
    """Loads corpus ``name``; refuses one whose ``[split]`` role is not dev (D-237)."""
    try:
        config = load_corpus(name)
    except CorpusError as exc:
        raise ReplayError(f"the {which} {name!r} does not load: {exc}") from exc
    if config.split_role != "dev":
        raise ReplayError(
            f"D-237: the {which} {name!r} has [split] role {config.split_role!r}, not "
            "'dev'; replaying it to the readers would be a held-out read"
        )
    return config


def is_pilot_run(header: Mapping[str, Any] | None) -> bool:
    """Whether a journal header is a pilot run's (``replay_init(pilot=True)``)."""
    source = (header or {}).get(REPLAY_SOURCE_KEY)
    return isinstance(source, dict) and source.get("pilot") is True


def require_d73(token: str | None, *, created_at: float | None = None) -> None:
    """Refuses unless D-73 holds for ``token`` now, before any paid call (#109).

    The check ``compare-levers`` makes after the spend: the constant committed in an
    ancestor of HEAD, the tree clean, the value unchanged since its commit and, with
    ``created_at``, that commit older than the data.

    Args:
        token: The S2 corpus's pre-registration token.
        created_at: The journal header's epoch seconds; None skips the time check
            (``replay-init`` checks before it stamps the header).

    Raises:
        ReplayError: Naming each problem, or the git failure that hides them.
    """
    if not token:
        raise ReplayError("D-73: the S2 corpus names no pre-registration")
    try:
        problems = gitcheck.preregistration_problems(
            (token,),
            require_clean_tree=True,
            created_at=created_at,
            unchanged_since_introduction=True,
        )
    except gitcheck.GitCheckError as exc:
        raise ReplayError(f"D-73: cannot prove {token} is committed: {exc}") from exc
    if problems:
        raise ReplayError(
            "D-73: refused before any paid call: "
            + "; ".join(problems)
            + f". Commit {token} on a clean tree first, or make a pilot run."
        )


def _declared_source_arm(token: str) -> str:
    """The S1 arm the S2 constant ``token`` says a run of record replays."""
    try:
        prereg = preregistration.resolve(token)
    except preregistration.PreregistrationError as exc:
        raise ReplayError(f"the S2 pre-registration: {exc}") from exc
    declared = getattr(prereg, "replay_source_arm", None)
    problem = None
    if not isinstance(declared, str) or not declared:
        problem = "is not set"
    else:
        try:
            canonical = canonical_arm(declared)
        except ValueError:
            problem = "is not a known arm label (a placeholder?)"
        else:
            if is_reader_arm(canonical):
                problem = "is a reader arm, not the S1 arm it replays"
    if problem is not None:
        raise ReplayError(
            f"{token}.replay_source_arm ({declared!r}) {problem}: a run of record "
            "replays the S1 winner the constant names; fill it in and commit it first"
        )
    return canonical


def _require_complete(
    records: Sequence[RunRecord], arm: str, header: Mapping[str, Any], corpus: str
) -> None:
    """Refuses a partial source run, or a source arm missing a question."""
    if header.get("partial", False):
        raise ReplayError(
            "the source run's journal header is partial: a run of record replays a "
            "complete S1 arm"
        )
    try:
        wanted = [q.question_id for q in load_corpus(corpus).questions]
    except CorpusError as exc:
        raise ReplayError(f"the source run's corpus {corpus!r}: {exc}") from exc
    held = {rec.question_id for rec in records}
    missing = [qid for qid in wanted if qid not in held]
    if missing:
        raise ReplayError(
            f"the source arm {arm!r} is incomplete: {len(missing)} question(s) of "
            f"{corpus!r} have no record: {_listed(missing)}"
        )


def replay_init(
    *,
    source_run: Path | str,
    arms: Sequence[str],
    run: Path | str,
    corpus: str,
    pilot: bool = False,
) -> ReplayInitResult:
    """Carries S1 arms' records and export rows into a new S2 journal (D-257, Q9).

    Every record of each arm is carried, error records included, and the export row of
    each success record with it, each with ``corpus`` set to the S2 corpus and nothing
    else changed. Nothing is written unless every check passes. A run of record also
    needs D-73, the declared source arm and a complete source arm (module docstring).

    Args:
        source_run: The S1 run directory (``journal.jsonl`` and
            ``context_export.jsonl``).
        arms: The S1 arm labels to carry.
        run: The S2 run directory.
        corpus: The S2 corpus, which lists the carried arms and their reader arms.
        pilot: Make a pilot run, which skips the run-of-record checks.

    Returns:
        The paths written and the counts carried.

    Raises:
        ReplayError: If an arm is unknown, repeated, a reader arm, or holds no record
            in the source run; the source run's corpus or the S2 corpus does not load
            or is not a dev corpus (D-237); the S2 corpus does not list a carried arm;
            a success record of a carried arm has no export row; the S2 journal or
            export already holds data; or, for a run of record, D-73 fails, the arms
            are not the declared ``replay_source_arm``, or the source arm is partial
            or incomplete.
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
    records = _source_records(source_journal, set(wanted))
    held = {canonical_arm(rec.graph_arm) for rec in records}
    absent = [arm for arm in wanted if arm not in held]
    if absent:
        in_run = sorted({
            canonical_arm(r.graph_arm) for r in load_records(source_journal)
        })
        raise ReplayError(
            f"arm(s) {absent} hold no record in the source run {source}; its arms are "
            f"{in_run}"
        )
    header = read_journal_header(source_journal) or {}
    source_corpus = str(header.get("corpus") or records[0].corpus)
    _dev_corpus(source_corpus, "source run's corpus")
    s2_config = _dev_corpus(corpus, "S2 corpus")
    listed = {canonical_arm(label) for label in s2_config.arms}
    unlisted = [arm for arm in wanted if arm not in listed]
    if unlisted:
        raise ReplayError(
            f"the S2 corpus {corpus!r} does not list the carried arm(s) {unlisted}; "
            "score would refuse their records"
        )
    if not pilot:
        token = s2_config.preregistration_token
        if not token:
            raise ReplayError("D-73: the S2 corpus names no pre-registration")
        declared = _declared_source_arm(token)
        if wanted != [declared]:
            raise ReplayError(
                f"the S2 pre-registration's replay_source_arm is {declared!r}, but "
                f"--arms carries {wanted}: a run of record replays that arm alone"
            )
        _require_complete(records, wanted[0], header, source_corpus)
        require_d73(token)
    rows = _export_rows(source / CONTEXT_EXPORT_FILE)
    missing = [
        f"{rec.question_id}/{rec.graph_arm}"
        for rec in records
        if rec.outcome == "success" and (rec.question_id, rec.graph_arm) not in rows
    ]
    if missing:
        raise ReplayError(
            f"{len(missing)} success record(s) of the carried arm(s) have no export "
            f"row in {source / CONTEXT_EXPORT_FILE}: {_listed(missing)}"
        )

    carried_rows: dict[tuple[str, str], ContextExportRow] = {}
    for rec in records:
        key = (rec.question_id, rec.graph_arm)
        if key in rows:
            carried_rows[key] = rows[key].model_copy(update={"corpus": corpus})
    hashes: dict[str, dict[str, str]] = {}
    for (qid, arm), row in carried_rows.items():
        hashes.setdefault(canonical_arm(arm), {})[qid] = export_row_sha256(row)

    journal = Journal(journal_path)
    journal.write_header(
        corpus=corpus,
        partial=bool(header.get("partial", False)),
        order_seed=header.get("order_seed"),
        split_sha256=header.get("split_sha256"),
        context_export=True,
        replay_source={
            "run": str(source),
            "corpus": source_corpus,
            "arms": wanted,
            "row_sha256": hashes,
            "pilot": pilot,
        },
    )
    for rec in records:
        journal.append(rec.model_copy(update={"corpus": corpus}))
    with open(export_path, "w", encoding="utf-8") as f:
        f.writelines(
            json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n"
            for row in carried_rows.values()
        )
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
    """Refuses a run whose replay records break a replay clause (D-257, D-274).

    A run with no replay record (a reader arm's, or a deepseek replicate) passes
    untouched. A pilot run with one is refused:
    its reader records are never the S2 result (#109). Otherwise the pre-registration
    ``token`` names must declare each reader, and every reader-arm record is checked
    against the run's context export, the header's carried row hashes and its
    reader's declaration (``provenance.replay_run_failures``).

    Args:
        records: The deduplicated journal records.
        journal_path: The journal; its header and the export beside it are read.
        token: The corpus's pre-registration token.

    Raises:
        ReplayError: If the run is a pilot run, or naming the clause, the arm and the
            question of each failure.
    """
    from lancet_eval import provenance

    if not any(provenance.is_replay_record(r) for r in records):
        return
    journal = Path(journal_path)
    header = read_journal_header(journal)
    if is_pilot_run(header):
        raise ReplayError(
            "#109: a pilot run (replay-init --pilot) is never scored or compared; "
            "report the run of record"
        )
    if not token:
        raise ReplayError(
            "D-257: model: the corpus names no pre-registration, so a reader arm has "
            "no declared reader to be compared with"
        )
    try:
        readers = preregistration.readers_of(preregistration.resolve(token))
    except preregistration.PreregistrationError as exc:
        raise ReplayError(f"D-257: model: {exc}") from exc
    export = journal.parent / CONTEXT_EXPORT_FILE
    try:
        rows = read_export(export) if export.is_file() else []
    except ContextExportError as exc:
        raise ReplayError(f"D-257: row_hash: {exc}") from exc
    failures = provenance.replay_run_failures(
        records,
        export_rows={(row.question_id, row.arm): row for row in rows},
        source_row_sha256=source_row_hashes(header),
        readers=readers,
    )
    if failures:
        listed = _listed([f"{f.code} {f.label} {f.detail}" for f in failures])
        raise ReplayError(
            f"D-257: reader arm provenance failed {len(failures)} time(s) (zero "
            f"tolerance): {listed}"
        )
