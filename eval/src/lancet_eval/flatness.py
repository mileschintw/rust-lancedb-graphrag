"""OI-02 flatness adapters (06.3.4.1-03, D-64/D-65).

Thin shims onto the unmodified `lancet_eval.decay.analyze_decay` — this module never edits
`decay.py` or `thresholds.py` (a plan prohibition, enforced by a `git diff --quiet` check).

Two record sources feed the same verdict function:

- `records_from_soak_jsonl` reads a `retrieval_soak` (P0, `engine/src/bin/retrieval_soak.rs`)
  JSONL file — one arm, gap-free ordinals in line order.
- `records_from_run_journal` reads a paid-drive run journal (P2) via the canonical
  `lancet_eval.journal.load_records` loader — ordinals assigned in journal line order (the
  loader itself skips the header and any half-written trailing line).

Both produce lightweight, duck-typed record objects carrying exactly the attributes
`lancet_eval.decay.validate_and_sort_records`/`analyze_decay` read (`ordinal`, `segment`,
`graph_arm`, `question_type`, `node_timings`, `node_failures`) — they are not `RunRecord` or
`MeasurementRecord` subclasses, just plain dataclasses with those fields.

See Pitfall 6 (RESEARCH): a censored set must read `unavailable`, never `flat`. `flatness_verdict`
enforces this by requiring both `analyze_decay` prongs `is_available` before ever reading
`verdict_decay_present`.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lancet_eval import decay
from lancet_eval.journal import load_records
from lancet_eval.thresholds import COMMITTED_THRESHOLDS

#: RetrieveHybrid is the only node this OI-02 investigation profiles (D-64/D-65).
_NODE_NAME = "RetrieveHybrid"

#: Harness-level `error_type` values that mean "the RetrieveHybrid observation for this record
#: is unusable/unknown", conservatively treated as censoring rather than silently dropped.
#: Mirrors `lancet_eval.diagnostic._HARNESS_TIMEOUT_ERROR_TYPES` (not imported directly — that
#: name is module-private; kept in sync by hand, both are small and stable).
_HARNESS_TIMEOUT_ERROR_TYPES = ("StreamDeadlineExceeded", "ReadTimeout")


@dataclass(frozen=True)
class SoakNodeTiming:
    """Duck-typed stand-in for `lancet_eval.journal.NodeTiming`."""

    node_name: str
    duration_ms: float


@dataclass(frozen=True)
class SoakNodeFailure:
    """Duck-typed stand-in for `lancet_eval.client.NodeFailed` (only the two fields
    `decay.analyze_decay` reads: `node_name`, `error_kind`)."""

    node_name: str
    error_kind: int


@dataclass(frozen=True)
class FlatnessRecord:
    """A record shaped exactly as `decay.validate_and_sort_records`/`analyze_decay` require.

    Not a `RunRecord`/`MeasurementRecord` subclass — `analyze_decay` reads these attributes via
    `getattr` with defaults, so any object carrying them works.
    """

    ordinal: int
    segment: str = "segment-1"
    graph_arm: str = ""
    question_type: str = ""
    node_timings: list[SoakNodeTiming] = field(default_factory=list)
    node_failures: list[SoakNodeFailure] = field(default_factory=list)


@dataclass(frozen=True)
class FlatnessResult:
    """OI-02 flatness verdict — a thin, testable projection of `decay.DecayVerdict`."""

    passed: bool
    reason: str
    trend_available: bool
    window_available: bool
    decay_present: bool
    slope_ms_per_query: float
    window_delta_ms: float
    censored_count: int
    unusable_dropped_count: int
    slice_medians_ms: list[float]
    n: int


def records_from_soak_jsonl(path: str | Path, arm: str) -> list[FlatnessRecord]:
    """Reads a `retrieval_soak` JSONL file for one arm into gap-free-ordinal records.

    Ordinals are assigned 1..n in line order (skipping the header line and any line for a
    different `arm`, defensive against a hand-concatenated multi-arm file). A line with
    `graph_timed_out: true` does NOT censor RetrieveHybrid — the graph sub-operation timing out
    is a separate, `graph_ms`-only observation; the node's own execution still succeeded (`ok:
    true`) whenever the RetrieveHybrid step itself completed. A line with `ok: false` (the node
    itself failed) is censored: a synthetic `RetrieveHybrid` node failure with `error_kind=1` is
    recorded so a saturated/broken soak reads `unavailable`, never `flat` (Pitfall 6).
    """
    records: list[FlatnessRecord] = []
    ordinal = 0
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or data.get("header"):
                continue
            if data.get("arm") != arm:
                continue

            ordinal += 1
            ok = bool(data.get("ok", True))
            retrieve_ms = data.get("retrieve_ms")

            node_timings: list[SoakNodeTiming] = []
            node_failures: list[SoakNodeFailure] = []
            if ok and retrieve_ms is not None:
                node_timings.append(
                    SoakNodeTiming(node_name=_NODE_NAME, duration_ms=float(retrieve_ms))
                )
            else:
                node_failures.append(SoakNodeFailure(node_name=_NODE_NAME, error_kind=1))

            records.append(
                FlatnessRecord(
                    ordinal=ordinal,
                    segment="segment-1",
                    graph_arm=str(data.get("arm", arm)),
                    node_timings=node_timings,
                    node_failures=node_failures,
                )
            )
    return records


def records_from_run_journal(journal_path: str | Path) -> list[FlatnessRecord]:
    """Reads a paid-drive run journal into gap-free-ordinal records via `journal.load_records`.

    `load_records` already skips the header line and any half-written trailing line, and
    preserves file order, so ordinals are assigned 1..n in that same journal line order.

    A `RetrieveHybrid` node failure with `error_kind == 1` censors the observation (handled by
    `decay.analyze_decay` itself, since `node_failures` passes through unchanged). A record
    whose top-level `error_type` is a harness deadline or read timeout
    (`_HARNESS_TIMEOUT_ERROR_TYPES`) has no RetrieveHybrid-specific failure entry to censor on —
    the harness gave up before or during the node, so this adapter synthesizes one, conservatively
    treating "unknown" as censored rather than silently dropping the record (Pitfall 6).
    """
    raw_records = load_records(journal_path)
    out: list[FlatnessRecord] = []
    for index, record in enumerate(raw_records, start=1):
        node_timings = [
            SoakNodeTiming(node_name=t.node_name, duration_ms=t.duration_ms)
            for t in record.node_timings
        ]
        node_failures = [
            SoakNodeFailure(node_name=f.node_name, error_kind=f.error_kind)
            for f in record.node_failures
        ]
        already_censors = any(
            f.node_name == _NODE_NAME and f.error_kind == 1 for f in node_failures
        )
        if not already_censors and record.error_type in _HARNESS_TIMEOUT_ERROR_TYPES:
            node_failures.append(SoakNodeFailure(node_name=_NODE_NAME, error_kind=1))

        out.append(
            FlatnessRecord(
                ordinal=index,
                segment="segment-1",
                graph_arm=record.graph_arm,
                node_timings=node_timings,
                node_failures=node_failures,
            )
        )
    return out


def slice_medians(records: Sequence[Any], size: int = 50) -> list[float]:
    """Per-`size`-record medians of the RetrieveHybrid duration, in ordinal order.

    Censored and unusable (no RetrieveHybrid timing) records are excluded, matching
    `decay.analyze_decay`'s own `paired`/`latencies` construction — this reports medians over
    the exact same observation set the trend and window prongs consume (Pitfall 7: report
    slice medians beside the verdict so a threshold-noise firing at small n is visible).
    """
    sorted_records = decay.validate_and_sort_records(records)
    durations: list[float] = []
    for record in sorted_records:
        failures = getattr(record, "node_failures", []) or []
        if any(
            getattr(f, "node_name", "") == _NODE_NAME and getattr(f, "error_kind", None) == 1
            for f in failures
        ):
            continue
        timings = getattr(record, "node_timings", []) or []
        timing = next(
            (t for t in timings if getattr(t, "node_name", "") == _NODE_NAME), None
        )
        if timing is not None and getattr(timing, "duration_ms", None) is not None:
            durations.append(float(timing.duration_ms))

    medians: list[float] = []
    for start in range(0, len(durations), size):
        chunk = durations[start : start + size]
        medians.append(statistics.median(chunk))
    return medians


def flatness_verdict(records: Sequence[Any]) -> FlatnessResult:
    """The OI-02 flatness verdict: `passed=True` only when both prongs are available and

    neither fired. A censored or too-small set is `passed=False, reason="unavailable"` — never
    read as flat (Pitfall 6). An empty input is `passed=False, reason="n=0"`.
    """
    n = len(records)
    if n == 0:
        return FlatnessResult(
            passed=False,
            reason="n=0",
            trend_available=False,
            window_available=False,
            decay_present=False,
            slope_ms_per_query=0.0,
            window_delta_ms=0.0,
            censored_count=0,
            unusable_dropped_count=0,
            slice_medians_ms=[],
            n=0,
        )

    verdict = decay.analyze_decay(
        records, COMMITTED_THRESHOLDS, restart_ordinal=None, node_name=_NODE_NAME
    )
    trend_available = verdict.trend_result.is_available
    window_available = verdict.window_result.is_available
    censored_count = max(
        verdict.trend_result.censored_count, verdict.window_result.censored_count
    )

    if not trend_available or not window_available:
        passed, reason = False, "unavailable"
    elif verdict.verdict_decay_present:
        passed, reason = False, "decay_present"
    else:
        passed, reason = True, "flat"

    return FlatnessResult(
        passed=passed,
        reason=reason,
        trend_available=trend_available,
        window_available=window_available,
        decay_present=verdict.verdict_decay_present,
        slope_ms_per_query=verdict.slope_statistic,
        window_delta_ms=verdict.window_delta_ms,
        censored_count=censored_count,
        unusable_dropped_count=verdict.unusable_dropped_count,
        slice_medians_ms=slice_medians(records),
        n=n,
    )
