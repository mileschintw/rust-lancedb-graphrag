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


import statistics as _statistics  # noqa: E402  (grouped with the rest of stdlib imports above ordinarily; kept local to the Task 2 section to minimise the Task 1 diff)

from lancet_eval import decay as _decay
from lancet_eval.flatness import (
    FlatnessRecord as _FlatnessRecord,
    flatness_verdict as _flatness_verdict,
    records_from_run_journal as _records_from_run_journal,
    slice_medians as _slice_medians,
)
from lancet_eval.thresholds import COMMITTED_THRESHOLDS as _COMMITTED_THRESHOLDS

#: M2 growth thresholds (Task 2 <action> "Readings" -- fixed before any data, must not be
#: tuned after seeing it).
_M2_GROWTH_RATIO = 1.5
_M2_GROWTH_WINDOW_DELTA_MS = 500.0
_M2_FLAT_RATIO = 1.2
_M2_FLAT_WINDOW_DELTA_MS = 500.0

#: M1 store-matched ratio band (0.5x-2x of the forensics-derived m1_prod_ratio).
_M1_RATIO_LOW = 0.5
_M1_RATIO_HIGH = 2.0

#: header.json values that indicate a lossy PowerShell-to-JSON serialisation (check-arm gate).
_LOSSY_SERIALIZATION_MARKER = "System.Collections"

_REQUIRED_HEADER_KEYS = (
    "arm_kind",
    "label",
    "commit",
    "dirty",
    "launch_command",
    "binary_path",
    "observability",
    "telemetry",
    "stderr_sink",
    "stub_delays",
    "warmup_n",
    "limit",
    "retries",
    "workers",
    "store_source",
    "start_utc",
    "end_utc",
    "egress_443_max",
    "paid",
    "spend_guard",
)

#: header.json fields `check-arm --same-config-as` compares for equality (Task 2 <behavior>).
_SAME_CONFIG_FIELDS = (
    "arm_kind",
    "build_profile",
    "stderr_sink",
    "observability",
    "telemetry",
    "config_dir_diff",
    "env_vars",
    "stub_delays",
    "stub_vector_source",
    "retries",
    "workers",
    "warmup_n",
    "store_source",
)


def _uncensored_prefix(records: list[_FlatnessRecord]) -> list[_FlatnessRecord]:
    """Records before the first censored (unusable) `RetrieveHybrid` observation, renumbered
    1..k so ordinals stay gap-free (`validate_and_sort_records` requires this)."""
    prefix: list[_FlatnessRecord] = []
    for record in sorted(records, key=lambda r: r.ordinal):
        censored = any(
            f.node_name == _NODE_NAME and f.error_kind == 1 for f in record.node_failures
        )
        has_timing = any(t.node_name == _NODE_NAME for t in record.node_timings)
        if censored or not has_timing:
            break
        prefix.append(record)
    renumbered = [
        _FlatnessRecord(
            ordinal=i,
            segment=r.segment,
            graph_arm=r.graph_arm,
            question_type=r.question_type,
            node_timings=r.node_timings,
            node_failures=r.node_failures,
        )
        for i, r in enumerate(prefix, start=1)
    ]
    return renumbered


def _graph_notice_counts(rows: list[TimelineRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for code in row.graph_notice_codes:
            counts[code] = counts.get(code, 0) + 1
    return counts


def _outcome_counts(rows: list[TimelineRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.outcome] = counts.get(row.outcome, 0) + 1
    return counts


def _find_journal_file(arm_dir: Path) -> Path | None:
    for name in ("journal.jsonl",):
        candidate = arm_dir / name
        if candidate.exists():
            return candidate
    return None


def classify_m2(
    slices: list[float], window_delta_ms: float
) -> str:
    """Classifies growth as `grows`, `not grows`, or `ambiguous` per Task 2's fixed thresholds.
    `slices` are 50-record RetrieveHybrid slice medians in ordinal order; `window_delta_ms` is
    `decay.analyze_decay`'s own window-prong delta on the uncensored prefix."""
    return "ambiguous"


def classify_m1(
    primary_slice0_ms: float,
    denominator_ms: float,
    target_ratio: float,
) -> tuple[str, float]:
    """Returns `(met|not met, ratio)`. `ratio` is `primary_slice0_ms / denominator_ms`; `met`
    iff that ratio is within [0.5x, 2x] of `target_ratio`."""
    return "not met", 0.0


def replay_summary(
    arm_dir: str | Path,
    *,
    production_journal: str | Path | None = None,
    forensics_json: str | Path | None = None,
    soak_baseline_json: str | Path | None = None,
) -> dict[str, Any]:
    """Implements the `replay-summary` subcommand: writes `<arm_dir>/summary.json` with per-node
    slice medians (50-record and 15-minute), graph notice/outcome counts, `flatness_verdict`
    (full run, uncensored-prefix, and first-200), M1/M2 readings when reference data is
    available, and an order-match check against `production_journal`'s prefix.
    """
    return {}

@dataclass
class CheckArmResult:
    ok: bool
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "failures": self.failures}


def _load_header(arm_dir: Path) -> dict[str, Any] | None:
    header_path = arm_dir / "header.json"
    if not header_path.exists():
        return None
    raw = header_path.read_bytes()
    # UTF-8 without BOM (Task 2 <behavior>): reject a leading BOM outright rather than
    # silently stripping it, since a BOM is itself evidence of the wrong write path
    # (`Out-File`/default PowerShell encoding instead of the mandated UTF8Encoding($false)).
    if raw[:3] == b"\xef\xbb\xbf":
        return None
    try:
        text = raw.decode("utf-8")
        return json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _json_equal_files(a: Path, b: Path) -> bool:
    if not a.exists() or not b.exists():
        return False
    try:
        return json.loads(a.read_text(encoding="utf-8")) == json.loads(b.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False


def check_arm(
    arm_dir: str | Path,
    *,
    min_records: int | None = None,
    require_flat: bool = False,
    same_config_as: str | Path | None = None,
    production_journal: str | Path | None = None,
) -> CheckArmResult:
    """Implements the `check-arm` subcommand's verification rules (Task 2 <behavior>)."""
    return CheckArmResult(ok=False, failures=["stub"])


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

    summary_parser = subparsers.add_parser(
        "replay-summary", help="Summarise a replay arm directory (Task 2)."
    )
    summary_parser.add_argument("arm_dir")
    summary_parser.add_argument("--production-journal", default=None)
    summary_parser.add_argument("--forensics-json", default=None)
    summary_parser.add_argument("--soak-baseline-json", default=None)

    check_parser = subparsers.add_parser(
        "check-arm", help="Verify a replay arm directory (Task 2)."
    )
    check_parser.add_argument("arm_dir")
    check_parser.add_argument("--min-records", type=int, default=None)
    check_parser.add_argument("--require-flat", action="store_true")
    check_parser.add_argument("--same-config-as", default=None)
    check_parser.add_argument("--production-journal", default=None)

    args = parser.parse_args(argv)

    if args.command == "forensics":
        run_forensics(
            journal=args.journal,
            raw_events=args.raw_events,
            contrast=args.contrast,
            out=args.out,
        )
        return 0

    if args.command == "replay-summary":
        replay_summary(
            args.arm_dir,
            production_journal=args.production_journal,
            forensics_json=args.forensics_json,
            soak_baseline_json=args.soak_baseline_json,
        )
        return 0

    if args.command == "check-arm":
        result = check_arm(
            args.arm_dir,
            min_records=args.min_records,
            require_flat=args.require_flat,
            same_config_as=args.same_config_as,
            production_journal=args.production_journal,
        )
        if not result.ok:
            for failure in result.failures:
                print(f"FAIL: {failure}")
            return 1
        print("check-arm: ok")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
