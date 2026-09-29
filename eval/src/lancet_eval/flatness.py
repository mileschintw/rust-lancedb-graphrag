"""OI-02 flatness adapters (06.3.4.1-03, D-64/D-65; D-89/D-92 in 06.3.4.1-21).

Thin shims onto the unmodified `lancet_eval.decay.analyze_decay`. This module never
edits `decay.py`. Plan 03 also promised never to edit `thresholds.py`; D-89 superseded
that note, and the verdict now reads `COMMITTED_DECAY_THRESHOLDS_06341` through
`decay_materiality.analyze_material_decay`. 06.3.3's `COMMITTED_THRESHOLDS` is
unchanged.

Two record sources feed the same verdict function:

- `records_from_soak_jsonl` reads a `retrieval_soak` (P0,
  `engine/src/bin/retrieval_soak.rs`) JSONL file: one arm, gap-free ordinals in line
  order.
- `records_from_run_journal` reads a run journal (P2). A drive journal (`RunRecord`
  lines) goes through the canonical `lancet_eval.journal.load_records` loader, with
  ordinals assigned in journal line order (the loader itself skips the header and any
  half-written trailing line). A `measure` journal (`MeasurementRecord` lines, D-92)
  goes through `load_measurement_records`: warm-up records are excluded and ordinals
  are renumbered 1..n in the native dispatch-ordinal order.

Both produce lightweight, duck-typed record objects carrying exactly the attributes
`lancet_eval.decay.validate_and_sort_records`/`analyze_decay` read (`ordinal`,
`segment`, `graph_arm`, `question_type`, `node_timings`, `node_failures`). They are not
`RunRecord` or `MeasurementRecord` subclasses, just plain dataclasses with those fields.

See Pitfall 6 (RESEARCH): a censored set must read `unavailable`, never `flat`.
`flatness_verdict` enforces this by requiring both D-89 prongs available before ever
reading `decay_present`.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lancet_eval import decay
from lancet_eval.decay_materiality import analyze_material_decay
from lancet_eval.journal import load_records
from lancet_eval.measure import MeasurementRecord

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
    #: D-89 additions. `decay_present` carries the D-89 verdict; `window_delta_ms` and
    #: `slope_ms_per_query` stay the base statistics.
    projected_growth_ms: float = 0.0
    materiality_threshold_ms: float | None = None
    rule: str = "D-89"


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


def _iter_record_lines(journal_path: Path) -> list[dict[str, Any]]:
    """The record-shaped JSON objects of a journal, in file order.

    A record line is a JSON object carrying `corpus`, `question_id` and `graph_arm`: the
    same predicate `journal.load_records` uses. Blank lines, unparseable or half-written
    lines, headers and other non-record lines are skipped.
    """
    if not journal_path.exists():
        return []
    lines: list[dict[str, Any]] = []
    with open(journal_path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(data, dict)
                and "corpus" in data
                and "question_id" in data
                and "graph_arm" in data
            ):
                lines.append(data)
    return lines


def _journal_shape(record_lines: Sequence[dict[str, Any]], path: Path) -> str:
    """The journal shape: `"measure"`, `"drive"` or `"empty"`.

    Raises `ValueError` on a mixed or ambiguous file. Detected from the raw keys before
    any validation, so a journal mixing both shapes cannot be half-skipped by a
    validator that rejects the other shape's lines.
    """
    measure = 0
    drive = 0
    for data in record_lines:
        has_ordinal = "ordinal" in data
        has_segment = "segment" in data
        if has_ordinal and has_segment:
            measure += 1
        elif not has_ordinal and not has_segment:
            drive += 1
        else:
            raise ValueError(
                f"{path}: record line carries only one of `ordinal`/`segment`; "
                "neither a measure nor a drive record"
            )
    if measure and drive:
        raise ValueError(
            f"{path}: journal mixes {measure} measure-shaped and {drive} drive-shaped "
            "record lines"
        )
    if measure:
        return "measure"
    if drive:
        return "drive"
    return "empty"


def load_measurement_records(
    journal_path: str | Path, include_warm_up: bool = False
) -> list[MeasurementRecord]:
    """Reads a `measure` journal (D-92) as `MeasurementRecord`s by native ordinal.

    Blank, unparseable and half-written lines and non-record lines (headers) are skipped
    exactly as `journal.load_records` skips them. Every remaining record line is
    validated as `MeasurementRecord`; a line that fails validation raises rather than
    being dropped, so a wrong-shape journal can never read as n = 0 again. Warm-up
    records are dropped unless `include_warm_up`. A duplicate native ordinal raises
    `ValueError`.
    """
    path = Path(journal_path)
    records = [
        MeasurementRecord.model_validate(data) for data in _iter_record_lines(path)
    ]
    seen: set[int] = set()
    for record in records:
        if record.ordinal in seen:
            raise ValueError(f"{path}: duplicate measurement ordinal {record.ordinal}")
        seen.add(record.ordinal)
    if not include_warm_up:
        records = [record for record in records if not record.warm_up]
    return sorted(records, key=lambda record: record.ordinal)


def records_from_run_journal(journal_path: str | Path) -> list[FlatnessRecord]:
    """Reads a run journal into gap-free-ordinal records.

    A drive journal loads via `journal.load_records`, which already skips the header
    line and any half-written trailing line and preserves file order, so ordinals are
    assigned 1..n in that same journal line order. A `measure` journal (lines carrying
    `ordinal` and `segment`, D-92) loads via `load_measurement_records`: warm-up
    records are excluded and ordinals are renumbered 1..n in native-ordinal order. A
    file mixing both shapes raises `ValueError`.

    A `RetrieveHybrid` node failure with `error_kind == 1` censors the observation
    (handled by `decay.analyze_decay` itself, since `node_failures` passes through
    unchanged). A record whose top-level `error_type` is a harness deadline or read
    timeout (`_HARNESS_TIMEOUT_ERROR_TYPES`) has no RetrieveHybrid-specific failure
    entry to censor on: the harness gave up before or during the node, so this adapter
    synthesizes one, conservatively treating "unknown" as censored rather than silently
    dropping the record (Pitfall 6).
    """
    path = Path(journal_path)
    shape = _journal_shape(_iter_record_lines(path), path)
    raw_records: Sequence[Any]
    if shape == "measure":
        raw_records = load_measurement_records(path)
    else:
        raw_records = load_records(path)
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
    """The OI-02 flatness verdict under D-89.

    `passed=True` only when both D-89 prongs are available and neither fired. A censored
    or too-small set is `passed=False, reason="unavailable"`, never read as flat
    (Pitfall 6). An empty input is `passed=False, reason="n=0"`. The rule is
    `COMMITTED_DECAY_THRESHOLDS_06341`: materiality max(25% of the early-window p95,
    25 ms) on both prongs, with the slope projected over 658 records.
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

    material = analyze_material_decay(records, node_name=_NODE_NAME)
    trend_available = material.slope_prong_available
    window_available = material.window_prong_available

    if not trend_available or not window_available:
        passed, reason = False, "unavailable"
    elif material.decay_present:
        passed, reason = False, "decay_present"
    else:
        passed, reason = True, "flat"

    return FlatnessResult(
        passed=passed,
        reason=reason,
        trend_available=trend_available,
        window_available=window_available,
        decay_present=material.decay_present,
        slope_ms_per_query=material.slope_ms_per_query,
        window_delta_ms=material.window_delta_ms,
        censored_count=material.censored_count,
        unusable_dropped_count=material.unusable_dropped_count,
        slice_medians_ms=slice_medians(records),
        n=n,
        projected_growth_ms=material.projected_growth_ms,
        materiality_threshold_ms=material.materiality_threshold_ms,
    )
