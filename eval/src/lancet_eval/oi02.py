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
    """Classifies growth as `grows`, `not grows`, or `ambiguous` per Task 2/Task 4's fixed
    thresholds. `slices` are 50-record RetrieveHybrid slice medians in ordinal order;
    `window_delta_ms` is `decay.analyze_decay`'s own window-prong delta on the uncensored
    prefix.

    The plan states two DIFFERENT slice references, not one shared "later slice" (06.3.4.1-07
    primary-r2 self-review, #bug -- both were read from a single `min(3, len-1)` index until
    this fix, which is correct only when a run has exactly 4 slices):
    - "grows": "the slice-3 median is at least 1.5x the slice-0 median" -- a fixed early-growth
      checkpoint. At Task 4's 150-record/3-slice arm scale, slice 3 doesn't exist, so this reads
      the last available slice instead (Task 4's own text separately calls that "slice-2").
    - "not grows": "the last full slice's median is under 1.2x the slice-0 median" -- literally
      the LAST slice, whatever the run length. At Task 2's 350-record/7-slice primary scale this
      is slice 6, not slice 3 -- a materially different check for any run with more than 4
      slices.
    """
    if len(slices) < 2:
        return "ambiguous"
    slice0 = slices[0]
    if slice0 <= 0:
        return "ambiguous"
    growth_index = min(3, len(slices) - 1)
    growth_ratio = slices[growth_index] / slice0
    flat_ratio = slices[-1] / slice0
    grows = growth_ratio >= _M2_GROWTH_RATIO and window_delta_ms >= _M2_GROWTH_WINDOW_DELTA_MS
    not_grows = flat_ratio < _M2_FLAT_RATIO and window_delta_ms < _M2_FLAT_WINDOW_DELTA_MS
    if grows:
        return "grows"
    if not_grows:
        return "not grows"
    return "ambiguous"


def classify_m1(
    primary_slice0_ms: float,
    denominator_ms: float,
    target_ratio: float,
) -> tuple[str, float]:
    """Returns `(met|not met, ratio)`. `ratio` is `primary_slice0_ms / denominator_ms`; `met`
    iff that ratio is within [0.5x, 2x] of `target_ratio`."""
    if denominator_ms <= 0 or target_ratio <= 0:
        return "not met", 0.0
    ratio = primary_slice0_ms / denominator_ms
    low = target_ratio * _M1_RATIO_LOW
    high = target_ratio * _M1_RATIO_HIGH
    met = low <= ratio <= high
    return ("met" if met else "not met"), ratio


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
    arm_path = Path(arm_dir)
    journal_path = _find_journal_file(arm_path)
    summary: dict[str, Any] = {"arm_dir": str(arm_path)}

    if journal_path is None:
        summary["error"] = "no journal.jsonl found in arm_dir"
        (arm_path / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    rows = journal_timeline(journal_path)
    flat_records = _records_from_run_journal(journal_path)

    summary["record_count"] = len(rows)
    summary["outcome_counts"] = _outcome_counts(rows)
    summary["graph_notice_counts"] = _graph_notice_counts(rows)
    summary["slices_ordinal_50"] = slice_table(rows, by="ordinal", size=50)
    summary["slices_wallclock_15m"] = slice_table(rows, by="wallclock", minutes=15)

    full_verdict = _flatness_verdict(flat_records)
    summary["flatness_verdict_full"] = {
        "passed": full_verdict.passed,
        "reason": full_verdict.reason,
        "trend_available": full_verdict.trend_available,
        "window_available": full_verdict.window_available,
        "decay_present": full_verdict.decay_present,
        "slope_ms_per_query": full_verdict.slope_ms_per_query,
        "window_delta_ms": full_verdict.window_delta_ms,
        "censored_count": full_verdict.censored_count,
        "n": full_verdict.n,
    }

    first200 = [r for r in sorted(flat_records, key=lambda r: r.ordinal) if r.ordinal <= 200]
    first200_verdict = _flatness_verdict(first200) if first200 else None
    if first200_verdict is not None:
        summary["flatness_verdict_first_200"] = {
            "passed": first200_verdict.passed,
            "reason": first200_verdict.reason,
            "trend_available": first200_verdict.trend_available,
            "window_available": first200_verdict.window_available,
            "decay_present": first200_verdict.decay_present,
            "slope_ms_per_query": first200_verdict.slope_ms_per_query,
            "window_delta_ms": first200_verdict.window_delta_ms,
            "censored_count": first200_verdict.censored_count,
            "n": first200_verdict.n,
        }

    uncensored = _uncensored_prefix(flat_records)
    summary["uncensored_prefix_n"] = len(uncensored)
    if uncensored:
        uncensored_verdict = _decay.analyze_decay(
            uncensored, _COMMITTED_THRESHOLDS, restart_ordinal=None, node_name=_NODE_NAME
        )
        summary["uncensored_prefix_verdict"] = {
            "decay_present": uncensored_verdict.verdict_decay_present,
            "slope_ms_per_query": uncensored_verdict.slope_statistic,
            "window_delta_ms": uncensored_verdict.window_delta_ms,
            "trend_available": uncensored_verdict.trend_result.is_available,
            "window_available": uncensored_verdict.window_result.is_available,
        }
        window_delta = uncensored_verdict.window_delta_ms
    else:
        window_delta = 0.0

    rh_slices = [
        s["RetrieveHybrid"] for s in summary["slices_ordinal_50"] if s.get("RetrieveHybrid") is not None
    ]
    m2_class = classify_m2(rh_slices, window_delta)
    summary["m2"] = {
        "class": m2_class,
        "slice0_ms": rh_slices[0] if rh_slices else None,
        # Two distinct reference slices per classify_m2's docstring: "grows" reads a fixed
        # early-growth checkpoint (slice-3, or the last slice on a shorter run); "not grows"
        # reads literally the last full slice. These are the SAME slice only on a run with
        # exactly 4 slices (e.g. Task 4's 150-record/3-slice arms) -- on Task 2's 350-record/
        # 7-slice primary scale they differ (slice 3 vs slice 6).
        "growth_check_slice_ms": rh_slices[min(3, len(rh_slices) - 1)] if len(rh_slices) >= 2 else None,
        "last_slice_ms": rh_slices[-1] if len(rh_slices) >= 2 else None,
        "window_delta_ms": window_delta,
        "committed_flatness_verdict_passed": full_verdict.passed,
    }

    # M1 formula depends on the arm's own store_source (header.json), per the plan's Task 2
    # text: a RECONCILED-store arm is D-88 non-comparable with production's lance-701 numbers,
    # so it compares a RATIO (slice0 / soak_w_ms_reconciled) against m1_prod_ratio. A
    # PRE-RECONCILE-store arm runs on the SAME store production did, so it compares slice-0
    # DIRECTLY against m1_reference_ms (no soak-baseline denominator needed or correct) -- both
    # use the shared 0.5x-2x band via `classify_m1`, just with a different denominator/target.
    # Unknown/missing store_source defaults to "reconciled" (every arm this tool produced a
    # header for before this fix was reconciled-store; a missing header is not itself evidence
    # of a pre-reconcile arm).
    m1_result: dict[str, Any] = {"status": "unavailable"}
    if forensics_json is not None and rh_slices:
        try:
            forensics_data = json.loads(Path(forensics_json).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            forensics_data = {}

        store_source = "reconciled"
        header_path = arm_path / "header.json"
        if header_path.exists():
            try:
                header_data = json.loads(header_path.read_text(encoding="utf-8"))
                store_source = header_data.get("store_source") or "reconciled"
            except (OSError, json.JSONDecodeError):
                pass

        if store_source == "pre-reconcile":
            reference_ms = forensics_data.get("m1_reference_ms")
            if reference_ms:
                status, ratio = classify_m1(rh_slices[0], reference_ms, 1.0)
                m1_result = {
                    "status": status,
                    "ratio": ratio,
                    "target_ratio": 1.0,
                    "primary_slice0_ms": rh_slices[0],
                    "denominator_ms": reference_ms,
                    "formula": "store_matched",
                }
        else:
            ratio_data = forensics_data.get("m1_prod_ratio")
            target_ratio = None
            if isinstance(ratio_data, dict):
                target_ratio = ratio_data.get("debug") or ratio_data.get("release")
            denominator = None
            if soak_baseline_json is not None:
                try:
                    soak_data = json.loads(Path(soak_baseline_json).read_text(encoding="utf-8"))
                    denominator = soak_data.get("soak_w_ms_reconciled")
                except (OSError, json.JSONDecodeError):
                    denominator = None
            if target_ratio and denominator:
                status, ratio = classify_m1(rh_slices[0], denominator, target_ratio)
                m1_result = {
                    "status": status,
                    "ratio": ratio,
                    "target_ratio": target_ratio,
                    "primary_slice0_ms": rh_slices[0],
                    "denominator_ms": denominator,
                    "formula": "ratio",
                }
    summary["m1"] = m1_result

    # Order match against production's prefix, and a fidelity table (production slices 0-6
    # vs this arm's own, per node) when a production journal is available.
    if production_journal is not None and Path(production_journal).exists():
        prod_rows = journal_timeline(production_journal)
        prod_prefix = sorted(prod_rows, key=lambda r: r.ordinal)[: len(rows)]
        this_sorted = sorted(rows, key=lambda r: r.ordinal)
        order_match = [(r.question_id, r.graph_arm) for r in prod_prefix] == [
            (r.question_id, r.graph_arm) for r in this_sorted
        ]
        summary["order_match_production"] = order_match

        prod_slices = slice_table(prod_rows, by="ordinal", size=50)
        fidelity = []
        for i in range(min(7, len(summary["slices_ordinal_50"]), len(prod_slices))):
            this_slice = summary["slices_ordinal_50"][i]
            prod_slice = prod_slices[i]
            row_entry = {"slice": i}
            for node in ("RetrieveHybrid", "AssemblePrompt", "ExtractGraphContext", "GenerateAnswer"):
                row_entry[node] = {
                    "replay": this_slice.get(node),
                    "production": prod_slice.get(node),
                }
            fidelity.append(row_entry)
        summary["fidelity_vs_production"] = fidelity

    (arm_path / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


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
    arm_path = Path(arm_dir)
    failures: list[str] = []

    header = _load_header(arm_path)
    if header is None:
        return CheckArmResult(ok=False, failures=["header.json missing, not UTF-8, or has a BOM"])

    arm_kind = header.get("arm_kind")
    if arm_kind not in ("full-stack", "grpc-direct", "soak-inprocess"):
        return CheckArmResult(ok=False, failures=[f"unknown arm_kind: {arm_kind!r}"])

    missing_keys = [k for k in _REQUIRED_HEADER_KEYS if k not in header]
    if missing_keys:
        failures.append(f"header.json missing required keys: {missing_keys}")

    header_text = json.dumps(header)
    if _LOSSY_SERIALIZATION_MARKER in header_text:
        failures.append("header.json contains a lossy-serialization marker (System.Collections)")

    live_before = arm_path / "live-state.before.json"
    live_after = arm_path / "live-state.after.json"
    if not _json_equal_files(live_before, live_after):
        failures.append("live-state.before.json != live-state.after.json")

    copy_before = arm_path / "copy-state.before.json"
    copy_after = arm_path / "copy-state.after.json"
    if not _json_equal_files(copy_before, copy_after):
        failures.append("copy-state.before.json != copy-state.after.json")

    journal_path = _find_journal_file(arm_path)
    record_count = 0
    if journal_path is not None:
        record_count = len(journal_timeline(journal_path))
    elif arm_kind == "full-stack":
        failures.append("full-stack arm has no journal.jsonl")

    if min_records is not None and record_count < min_records:
        failures.append(f"record count {record_count} < --min-records {min_records}")

    paid = bool(header.get("paid", False))
    if arm_kind in ("full-stack", "grpc-direct") and not paid:
        egress_max = header.get("egress_443_max")
        if egress_max != 0:
            failures.append(f"egress_443_max is {egress_max!r}, expected 0 for a non-paid arm")
        stub_stats_path = arm_path / "stub-stats.json"
        if stub_stats_path.exists():
            try:
                stats = json.loads(stub_stats_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                stats = {}
            if stats.get("embeddings", 0) == 0 or stats.get("chat_completions", 0) == 0:
                failures.append("stub embeddings/chat_completions counts are zero")
        else:
            failures.append("stub-stats.json missing for a non-paid full-stack/grpc-direct arm")

    telemetry = header.get("telemetry")
    observability = header.get("observability")
    if isinstance(telemetry, dict):
        for process, mode in telemetry.items():
            conns_key = f"otlp_4317_conns_max"
            conns = header.get(conns_key, {})
            process_conns = conns.get(process) if isinstance(conns, dict) else None
            if mode == "console-only" and process_conns not in (0, None):
                failures.append(f"{process} declares console-only telemetry but otlp_4317_conns_max={process_conns}")
            if mode == "otlp" and observability == "on" and process_conns is not None and process_conns < 1:
                failures.append(f"{process} declares otlp telemetry with observability on but otlp_4317_conns_max={process_conns}")

    if production_journal is not None and Path(production_journal).exists() and journal_path is not None:
        prod_rows = journal_timeline(production_journal)
        this_rows = journal_timeline(journal_path)
        prod_prefix = sorted(prod_rows, key=lambda r: r.ordinal)[: len(this_rows)]
        this_sorted = sorted(this_rows, key=lambda r: r.ordinal)
        if [(r.question_id, r.graph_arm) for r in prod_prefix] != [
            (r.question_id, r.graph_arm) for r in this_sorted
        ]:
            failures.append("(question_id, graph_arm) order does not match production journal prefix")

    if require_flat:
        summary_path = arm_path / "summary.json"
        if not summary_path.exists():
            failures.append("--require-flat given but summary.json missing (run replay-summary first)")
        else:
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                summary = {}
            verdict = summary.get("flatness_verdict_full", {})
            if not (
                verdict.get("passed")
                and verdict.get("trend_available")
                and verdict.get("window_available")
            ):
                failures.append("--require-flat: flatness_verdict_full is not passed=True with both prongs available")

    if same_config_as is not None:
        other_header_path = Path(same_config_as) / "header.json"
        other_header = _load_header(Path(same_config_as))
        if other_header is None:
            failures.append(f"--same-config-as header missing/invalid: {other_header_path}")
        else:
            for field_name in _SAME_CONFIG_FIELDS:
                if header.get(field_name) != other_header.get(field_name):
                    failures.append(
                        f"--same-config-as mismatch on {field_name!r}: "
                        f"{header.get(field_name)!r} != {other_header.get(field_name)!r}"
                    )

    return CheckArmResult(ok=not failures, failures=failures)


# --- Stub vector-map builder (Task 3 checkpoint resolution: rerun-primary with real vectors) --
#
# The first primary replay served 100% hash-fallback embedding vectors: `data/replay/
# stub-vectors.jsonl` was never built. A random query vector suppresses graph traversal (no
# real seeds to visit), so ExtractGraphContext never ran the work it does in production. This
# builder closes that gap: for each replay question, it finds the top-ranked chunk production
# actually retrieved for that same question, exports that chunk's own stored vector from the
# store copy (via `retrieval_soak --export-embeddings`, run externally), and keys the stub's
# vector map by the exact question text the engine embeds (`ctx.variants[0]`, which is
# `ctx.original_query` unmodified whenever no query reformulation fires -- true for every
# record in the first primary replay). A question with no resolvable chunk/embedding/text
# falls back to the stub's deterministic hash vector, which is not a hard failure -- it is
# counted and disclosed.


def _ordered_question_ids(journal_path: str | Path) -> list[str]:
    """Unique `question_id`s from a journal file, in first-seen line order (header skipped)."""
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_line in Path(journal_path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        record = json.loads(line)
        if record.get("type") == "header":
            continue
        question_id = record.get("question_id")
        if question_id and question_id not in seen:
            seen.add(question_id)
            ordered.append(question_id)
    return ordered


def extract_chunk_ids_for_replay(
    replay_journal: str | Path,
    prod_journal: str | Path,
) -> tuple[dict[str, str], list[str]]:
    """Builds `{question_id: top_ranked_chunk_id}` for every question_id appearing in
    `replay_journal` (first-seen order), looked up from `prod_journal`'s per-question
    `snapshot.retrieved_chunks` (`rank == 1`). Prefers the `graph-off` arm's record when a
    question_id has both arms in production (graph-off isolates pure retrieval ranking from
    graph traversal); falls back to whichever arm is present. A question_id absent from
    `prod_journal`, or whose top record carries no chunks, is omitted from the returned map --
    the caller then hash-falls-back it.

    Returns `(question_id -> chunk_id map, ordered unique chunk_ids)`, the second element being
    the exact input `retrieval_soak --export-embeddings` needs.
    """
    replay_question_ids = _ordered_question_ids(replay_journal)

    prod_top_chunk: dict[str, dict[str, str | None]] = {}
    for raw_line in Path(prod_journal).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        record = json.loads(line)
        if record.get("type") == "header":
            continue
        question_id = record.get("question_id")
        arm = record.get("graph_arm")
        if not question_id or arm not in ("graph-off", "graph-on"):
            continue
        chunks = (record.get("snapshot") or {}).get("retrieved_chunks") or []
        top_chunk_id = next((c.get("chunk_id") for c in chunks if c.get("rank") == 1), None)
        prod_top_chunk.setdefault(question_id, {})[arm] = top_chunk_id

    question_to_chunk: dict[str, str] = {}
    for question_id in replay_question_ids:
        arms = prod_top_chunk.get(question_id)
        if not arms:
            continue
        chunk_id = arms.get("graph-off") or arms.get("graph-on")
        if chunk_id:
            question_to_chunk[question_id] = chunk_id

    ordered_chunk_ids: list[str] = []
    seen_chunks: set[str] = set()
    for question_id in replay_question_ids:
        chunk_id = question_to_chunk.get(question_id)
        if chunk_id and chunk_id not in seen_chunks:
            seen_chunks.add(chunk_id)
            ordered_chunk_ids.append(chunk_id)

    return question_to_chunk, ordered_chunk_ids


def load_chunk_embeddings(embeddings_jsonl: str | Path) -> dict[str, list[float]]:
    """Loads `retrieval_soak --export-embeddings`'s `{chunk_id, embedding}` JSONL output."""
    out: dict[str, list[float]] = {}
    for raw_line in Path(embeddings_jsonl).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        record = json.loads(line)
        chunk_id = record.get("chunk_id")
        embedding = record.get("embedding")
        if isinstance(chunk_id, str) and isinstance(embedding, list):
            out[chunk_id] = [float(x) for x in embedding]
    return out


def load_question_texts(questions_path: str | Path) -> dict[str, str]:
    """Loads a corpus questions JSONL's `question_id -> query` text mapping (the exact string
    the harness sends as `RunQueryRequest.query`, unmodified end to end through to the
    embedding client whenever no reformulation fires)."""
    out: dict[str, str] = {}
    for raw_line in Path(questions_path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        record = json.loads(line)
        question_id = record.get("question_id")
        query = record.get("query")
        if isinstance(question_id, str) and isinstance(query, str):
            out[question_id] = query
    return out


def build_stub_vectors(
    question_to_chunk: dict[str, str],
    chunk_embeddings: dict[str, list[float]],
    question_texts: dict[str, str],
    replay_question_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Assembles the stub vector-map rows (`{"text": ..., "embedding": [...]}`,
    `provider_stub.load_vector_map`'s exact shape) for every replay question_id resolvable
    end to end: replay -> production top chunk -> exported embedding -> corpus query text.

    Returns `(rows, counts)`. `counts` breaks every replay question_id down by outcome --
    `total`, `no_prod_chunk` (absent from `question_to_chunk`), `no_embedding` (chunk_id absent
    from `chunk_embeddings`, e.g. not present in the reconciled store copy),
    `no_question_text` (question_id absent from `question_texts`), and `matched` -- so the
    caller can disclose the fallback count rather than bury it.
    """
    rows: list[dict[str, Any]] = []
    counts = {
        "total": len(replay_question_ids),
        "no_prod_chunk": 0,
        "no_embedding": 0,
        "no_question_text": 0,
        "matched": 0,
    }
    for question_id in replay_question_ids:
        chunk_id = question_to_chunk.get(question_id)
        if not chunk_id:
            counts["no_prod_chunk"] += 1
            continue
        embedding = chunk_embeddings.get(chunk_id)
        if embedding is None:
            counts["no_embedding"] += 1
            continue
        text = question_texts.get(question_id)
        if text is None:
            counts["no_question_text"] += 1
            continue
        rows.append({"text": text, "embedding": embedding})
        counts["matched"] += 1
    return rows, counts


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

    extract_parser = subparsers.add_parser(
        "extract-chunk-ids",
        help="Build question->production-top-chunk map + chunk_ids.json for --export-embeddings (Task 3 checkpoint: rerun-primary).",
    )
    extract_parser.add_argument("--replay-journal", required=True)
    extract_parser.add_argument("--prod-journal", required=True)
    extract_parser.add_argument("--out-chunk-ids", required=True)
    extract_parser.add_argument("--out-map", required=True)

    vectors_parser = subparsers.add_parser(
        "build-stub-vectors",
        help="Assemble data/replay/stub-vectors.jsonl from the question->chunk map, retrieval_soak --export-embeddings output, and the corpus questions file.",
    )
    vectors_parser.add_argument("--replay-journal", required=True)
    vectors_parser.add_argument("--map", required=True, dest="map_path")
    vectors_parser.add_argument("--embeddings", required=True)
    vectors_parser.add_argument("--questions", required=True)
    vectors_parser.add_argument("--out", required=True)

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

    if args.command == "extract-chunk-ids":
        question_to_chunk, ordered_chunk_ids = extract_chunk_ids_for_replay(
            args.replay_journal, args.prod_journal
        )
        replay_question_ids = _ordered_question_ids(args.replay_journal)
        Path(args.out_chunk_ids).write_text(
            json.dumps(ordered_chunk_ids, indent=2), encoding="utf-8"
        )
        Path(args.out_map).write_text(
            json.dumps(question_to_chunk, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "replay_questions": len(replay_question_ids),
                    "matched_to_prod_top_chunk": len(question_to_chunk),
                    "unique_chunk_ids": len(ordered_chunk_ids),
                }
            )
        )
        return 0

    if args.command == "build-stub-vectors":
        question_to_chunk = json.loads(Path(args.map_path).read_text(encoding="utf-8"))
        chunk_embeddings = load_chunk_embeddings(args.embeddings)
        question_texts = load_question_texts(args.questions)
        replay_question_ids = _ordered_question_ids(args.replay_journal)
        rows, counts = build_stub_vectors(
            question_to_chunk, chunk_embeddings, question_texts, replay_question_ids
        )
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
        print(json.dumps(counts))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
