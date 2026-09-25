"""OI-02 full-pipeline diagnosis tooling (06.3.4.1-07).

Zero-cost journal forensics (Task 1: `forensics`) and, added in Task 2, full-stack
replay summarisation and header/live-state verification (`replay-summary`, `check-arm`).

This module never edits `decay.py` or `thresholds.py` — it reuses `flatness.py`'s
unmodified `flatness_verdict`/`records_from_run_journal` for any pass/fail reading.

Two record shapes are read from a journal line, in this preference order:

- 06.3.3 `MeasurementRecord` shape (carries its own `ordinal`/`segment`) -- tried first,
  since it is a strict superset of `RunRecord`'s fields (`extra="forbid"` on both models
  means a 06.3.4-shaped line, which lacks the required `ordinal`/`segment` fields, fails
  `MeasurementRecord` validation and falls through to `RunRecord` below).
- 06.3.4 `RunRecord` shape -- ordinal assigned 1..n in journal line order (header line
  skipped, matching `journal.load_records`'s own skip rule), segment fixed at
  ``"segment-1"``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from lancet_eval.journal import RunRecord
from lancet_eval.measure import MeasurementRecord

#: The only node this OI-02 investigation profiles for growth (matches flatness.py).
_NODE_NAME = "RetrieveHybrid"

#: Default hidden-gap flag threshold (ms) -- a gap over this is flagged as retries/idle time.
_DEFAULT_HIDDEN_GAP_THRESHOLD_MS = 2000.0

#: Required top-level keys the plan's Task 1 <verify> asserts on forensics.json. Keys this
#: module does NOT itself compute (fresh_process, m1_reference_ms, m1_prod_ratio,
#: stub_delay_defaults, production_launch, drive_era_commit, proto_changed_since_drive_era)
#: are seeded here as "unknown" placeholders on first write, and preserved verbatim on every
#: later run unless a caller/human has already overwritten them with real values -- this
#: subcommand is deliberately non-destructive of externally-gathered evidence (Prometheus,
#: Loki, git, transcripts), per this task's own §1/§4/§5 action items.
_EXTERNAL_EVIDENCE_KEYS = (
    "fresh_process",
    "prior_query_count",
    "m1_reference_ms",
    "m1_reference_provenance",
    "m1_alt_reference_ms",
    "m1_prod_ratio",
    "stub_delay_defaults",
    "production_launch",
    "drive_era_commit",
    "proto_changed_since_drive_era",
)


@dataclass(frozen=True)
class TimelineRow:
    """One row of `journal_timeline`'s output -- see the Task 1 <behavior> spec."""

    ordinal: int
    segment: str
    question_id: str
    graph_arm: str
    outcome: str
    error_type: str | None
    started_at_ms: int
    completed_at_ms: int
    duration_ms: float
    node_durations: dict[str, float]
    graph_notice_codes: list[str]
    reformulation_used: bool
    prompt_tokens: int
    question_text_len: int
    hidden_gap_ms: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "segment": self.segment,
            "question_id": self.question_id,
            "graph_arm": self.graph_arm,
            "outcome": self.outcome,
            "error_type": self.error_type,
            "started_at_ms": self.started_at_ms,
            "completed_at_ms": self.completed_at_ms,
            "duration_ms": self.duration_ms,
            "node_durations": self.node_durations,
            "graph_notice_codes": self.graph_notice_codes,
            "reformulation_used": self.reformulation_used,
            "prompt_tokens": self.prompt_tokens,
            "question_text_len": self.question_text_len,
            "hidden_gap_ms": self.hidden_gap_ms,
        }


def _load_any_record(data: dict[str, Any]) -> tuple[Any, bool]:
    """Try `MeasurementRecord` (06.3.3 shape) first, fall back to `RunRecord` (06.3.4 shape).

    Returns (record, is_measurement_record). Raises `pydantic.ValidationError` if neither
    shape validates (an unrecognised or corrupt line).
    """
    try:
        return MeasurementRecord.model_validate(data), True
    except ValidationError:
        pass
    return RunRecord.model_validate(data), False


def load_timeline_records(journal_path: str | Path) -> list[tuple[Any, bool]]:
    """Reads a journal file into `(record, is_measurement_record)` pairs, file order,
    skipping the header line and any half-written/unparseable trailing line (matching
    `journal.load_records`'s own skip contract)."""
    path = Path(journal_path)
    out: list[tuple[Any, bool]] = []
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                not isinstance(data, dict)
                or "corpus" not in data
                or "question_id" not in data
                or "graph_arm" not in data
            ):
                continue
            try:
                out.append(_load_any_record(data))
            except ValidationError:
                continue
    return out


def _question_text_lengths(contrast_or_journal_dir: Path) -> dict[str, int]:
    """Best-effort question-text lengths from a sibling `raw_events/*/<question_id>.jsonl`
    file's first captured request, if present. Returns an empty map when unavailable --
    RunRecord/MeasurementRecord carry no question text, so this is opportunistic, not a
    contract any caller may rely on."""
    lengths: dict[str, int] = {}
    raw_events_dir = contrast_or_journal_dir / "raw_events"
    if not raw_events_dir.is_dir():
        return lengths
    for arm_dir in raw_events_dir.iterdir():
        if not arm_dir.is_dir():
            continue
        for qfile in arm_dir.glob("*.jsonl"):
            qid = qfile.stem
            if qid in lengths:
                continue
            try:
                with open(qfile, encoding="utf-8") as fh:
                    for raw_line in fh:
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            evt = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        text = None
                        if isinstance(evt, dict):
                            text = evt.get("query") or evt.get("question")
                        if isinstance(text, str) and text:
                            lengths[qid] = len(text)
                            break
            except OSError:
                continue
    return lengths


def journal_timeline(
    journal_path: str | Path,
    *,
    hidden_gap_threshold_ms: float = _DEFAULT_HIDDEN_GAP_THRESHOLD_MS,
) -> list[TimelineRow]:
    """Builds the per-record timeline table.

    `hidden_gap_ms` for record i is `started_at[i] - completed_at[i-1]` (the first record has
    no gap: `None`). Question text length is best-effort via a sibling `raw_events/` directory,
    when present; otherwise 0.
    """
    loaded = load_timeline_records(journal_path)
    journal_dir = Path(journal_path).parent
    qlens = _question_text_lengths(journal_dir)

    rows: list[TimelineRow] = []
    prev_completed_at_ms: int | None = None
    for idx, (rec, is_measurement) in enumerate(loaded, start=1):
        ordinal = rec.ordinal if is_measurement else idx
        segment = rec.segment if is_measurement else "segment-1"
        node_durations = {t.node_name: t.duration_ms for t in rec.node_timings}
        wm = rec.workflow_meta
        started_at_ms = int(wm.started_at_ms) if wm else 0
        completed_at_ms = int(wm.completed_at_ms) if wm else 0

        hidden_gap_ms: float | None = None
        if prev_completed_at_ms is not None and started_at_ms:
            hidden_gap_ms = float(started_at_ms - prev_completed_at_ms)
        if completed_at_ms:
            prev_completed_at_ms = completed_at_ms

        notices = getattr(rec, "notices", None) or []
        graph_notice_codes = sorted({n.code for n in notices})

        rows.append(
            TimelineRow(
                ordinal=ordinal,
                segment=segment,
                question_id=rec.question_id,
                graph_arm=rec.graph_arm,
                outcome=rec.outcome,
                error_type=rec.error_type,
                started_at_ms=started_at_ms,
                completed_at_ms=completed_at_ms,
                duration_ms=float(rec.duration_ms or 0.0),
                node_durations=node_durations,
                graph_notice_codes=graph_notice_codes,
                reformulation_used=bool(wm.reformulation_used) if wm else False,
                prompt_tokens=int(wm.prompt_tokens) if wm else 0,
                question_text_len=qlens.get(rec.question_id, 0),
                hidden_gap_ms=hidden_gap_ms,
            )
        )
    return rows


def hidden_gaps(
    rows: list[TimelineRow], *, threshold_ms: float = _DEFAULT_HIDDEN_GAP_THRESHOLD_MS
) -> list[dict[str, Any]]:
    """Rows whose `hidden_gap_ms` exceeds `threshold_ms`, flagged as retries-or-idle-time."""
    flagged = []
    for row in rows:
        if row.hidden_gap_ms is not None and row.hidden_gap_ms > threshold_ms:
            flagged.append(
                {
                    "ordinal": row.ordinal,
                    "question_id": row.question_id,
                    "hidden_gap_ms": row.hidden_gap_ms,
                }
            )
    return flagged


def slice_table(
    rows: list[TimelineRow],
    *,
    by: str = "ordinal",
    size: int = 50,
    minutes: int = 15,
) -> list[dict[str, Any]]:
    """Per-slice medians per node, in order. `by="ordinal"` groups every `size` records in
    ordinal order; `by="wallclock"` groups by `minutes`-wide windows since the first record's
    `started_at_ms`. A slice with no completed RetrieveHybrid reports it as ``None``
    (unavailable), never as 0."""
    if by not in ("ordinal", "wallclock"):
        raise ValueError(f"Unknown slice_table 'by': {by!r}")

    node_names: set[str] = {_NODE_NAME}
    for row in rows:
        node_names.update(row.node_durations.keys())
    node_names_sorted = sorted(node_names)

    def _slice_summary(chunk: list[TimelineRow], label: Any) -> dict[str, Any]:
        summary: dict[str, Any] = {"slice": label, "n": len(chunk)}
        for node in node_names_sorted:
            durations = [
                row.node_durations[node] for row in chunk if node in row.node_durations
            ]
            summary[node] = statistics.median(durations) if durations else None
        return summary

    slices: list[dict[str, Any]] = []
    if by == "ordinal":
        sorted_rows = sorted(rows, key=lambda r: r.ordinal)
        for start in range(0, len(sorted_rows), size):
            chunk = sorted_rows[start : start + size]
            slices.append(_slice_summary(chunk, start // size))
    else:
        timed_rows = sorted(
            (r for r in rows if r.started_at_ms), key=lambda r: r.started_at_ms
        )
        if not timed_rows:
            return []
        first_ms = timed_rows[0].started_at_ms
        window_ms = minutes * 60_000
        buckets: dict[int, list[TimelineRow]] = {}
        for row in timed_rows:
            bucket = (row.started_at_ms - first_ms) // window_ms
            buckets.setdefault(bucket, []).append(row)
        for bucket in sorted(buckets):
            slices.append(_slice_summary(buckets[bucket], bucket))
    return slices


def idle_recovery(
    rows: list[TimelineRow], *, window: int = 10, threshold_ms: float = _DEFAULT_HIDDEN_GAP_THRESHOLD_MS
) -> list[dict[str, Any]]:
    """Compares RetrieveHybrid medians of the `window` records before and after each of the
    largest idle gaps (hidden_gap_ms over `threshold_ms`)."""
    sorted_rows = sorted(rows, key=lambda r: r.ordinal)
    gaps = hidden_gaps(sorted_rows, threshold_ms=threshold_ms)
    if not gaps:
        return []
    gaps_sorted = sorted(gaps, key=lambda g: g["hidden_gap_ms"], reverse=True)

    by_ordinal = {row.ordinal: row for row in sorted_rows}
    ordinals = [row.ordinal for row in sorted_rows]

    results = []
    for gap in gaps_sorted:
        idx = ordinals.index(gap["ordinal"])
        before = ordinals[max(0, idx - window) : idx]
        after = ordinals[idx : idx + window]

        def _median_for(ords: list[int]) -> float | None:
            vals = [
                by_ordinal[o].node_durations[_NODE_NAME]
                for o in ords
                if _NODE_NAME in by_ordinal[o].node_durations
            ]
            return statistics.median(vals) if vals else None

        results.append(
            {
                "gap_ordinal": gap["ordinal"],
                "hidden_gap_ms": gap["hidden_gap_ms"],
                "before_median_ms": _median_for(before),
                "after_median_ms": _median_for(after),
            }
        )
    return results


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def compute_drive_era_facts(
    *, before_iso: str = "2026-09-09T21:05:40Z", ref: str = "main"
) -> dict[str, Any]:
    """Computes `drive_era_commit` (earliest commit containing every flag/code path the
    recorded invocation needed -- per this task's own action item 4, that is the commit that
    introduced `--retries`) and `proto_changed_since_drive_era`.

    Read-only: runs `git log`/`git diff` against the working tree's own history, never writes.
    """
    last_before = _git("log", "-1", "--format=%H", f"--before={before_iso}", ref)
    drive_era_commit = _git(
        "log",
        "--all",
        "--format=%H",
        "-S",
        "--retries",
        "--reverse",
        "--",
        "eval/src/lancet_eval/cli.py",
    )
    first_retries_commit = drive_era_commit.splitlines()[0] if drive_era_commit else ""
    resolved = first_retries_commit or last_before

    proto_diff = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            resolved,
            "HEAD",
            "--",
            "proto/",
            "engine/src/pb",
            "gateway/proto",
        ],
        capture_output=True,
        check=False,
    )
    proto_changed = proto_diff.returncode != 0

    return {
        "last_commit_before_drive": last_before,
        "drive_era_commit": resolved,
        "drive_era_commit_source": "earliest commit adding --retries to cli.py run command (-S search)",
        "proto_changed_since_drive_era": proto_changed,
    }


def _read_existing(out_dir: Path) -> dict[str, Any]:
    forensics_path = out_dir / "forensics.json"
    if forensics_path.exists():
        try:
            return json.loads(forensics_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def run_forensics(
    *,
    journal: str | Path,
    raw_events: str | Path | None,
    contrast: str | Path | None,
    out: str | Path,
) -> dict[str, Any]:
    """Implements the `forensics` subcommand: computes the journal-derived outputs, merges
    them (non-destructively -- see `_EXTERNAL_EVIDENCE_KEYS`) into `<out>/forensics.json`,
    and writes the timeline/slice-table artefacts alongside it.
    """
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = journal_timeline(journal)
    row_dicts = [r.as_dict() for r in rows]
    slices_ordinal = slice_table(rows, by="ordinal", size=50)
    slices_wallclock = slice_table(rows, by="wallclock", minutes=15)
    gaps = hidden_gaps(rows)
    recovery = idle_recovery(rows)

    contrast_rows_dicts: list[dict[str, Any]] = []
    contrast_slices: list[dict[str, Any]] = []
    if contrast:
        contrast_rows = journal_timeline(contrast)
        contrast_rows_dicts = [r.as_dict() for r in contrast_rows]
        contrast_slices = slice_table(contrast_rows, by="ordinal", size=50)

    (out_dir / "timeline.json").write_text(
        json.dumps(row_dicts, indent=2), encoding="utf-8"
    )
    (out_dir / "slices_ordinal.json").write_text(
        json.dumps(slices_ordinal, indent=2), encoding="utf-8"
    )
    (out_dir / "slices_wallclock.json").write_text(
        json.dumps(slices_wallclock, indent=2), encoding="utf-8"
    )
    (out_dir / "hidden_gaps.json").write_text(json.dumps(gaps, indent=2), encoding="utf-8")
    (out_dir / "idle_recovery.json").write_text(
        json.dumps(recovery, indent=2), encoding="utf-8"
    )
    if contrast:
        (out_dir / "contrast_timeline.json").write_text(
            json.dumps(contrast_rows_dicts, indent=2), encoding="utf-8"
        )
        (out_dir / "contrast_slices_ordinal.json").write_text(
            json.dumps(contrast_slices, indent=2), encoding="utf-8"
        )

    git_facts = compute_drive_era_facts()

    merged = _read_existing(out_dir)
    # Seed any never-before-set external-evidence key as an explicit "unknown" placeholder --
    # never overwrite a key a human/earlier run already populated with real evidence.
    for key in _EXTERNAL_EVIDENCE_KEYS:
        merged.setdefault(key, "unknown")
    # git-derived facts are cheap and deterministic to recompute -- always refresh them.
    merged["drive_era_commit"] = git_facts["drive_era_commit"]
    merged["proto_changed_since_drive_era"] = git_facts["proto_changed_since_drive_era"]
    merged["_drive_era_commit_source"] = git_facts["drive_era_commit_source"]
    merged["_last_commit_before_drive"] = git_facts["last_commit_before_drive"]
    merged["journal_record_count"] = len(rows)
    merged["journal_hidden_gaps_over_threshold"] = len(gaps)
    if contrast:
        merged["contrast_record_count"] = len(contrast_rows_dicts)

    (out_dir / "forensics.json").write_text(
        json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8"
    )
    return merged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m lancet_eval.oi02")
    subparsers = parser.add_subparsers(dest="command", required=True)

    forensics_parser = subparsers.add_parser(
        "forensics", help="Zero-cost journal/git forensics (Task 1)."
    )
    forensics_parser.add_argument("--journal", required=True)
    forensics_parser.add_argument("--raw-events", dest="raw_events", default=None)
    forensics_parser.add_argument("--contrast", default=None)
    forensics_parser.add_argument("--out", required=True)

    args = parser.parse_args(argv)

    if args.command == "forensics":
        run_forensics(
            journal=args.journal,
            raw_events=args.raw_events,
            contrast=args.contrast,
            out=args.out,
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
