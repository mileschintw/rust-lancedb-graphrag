"""Tests for the OI-02 flatness adapters (06.3.4.1-03): soak/journal record adapters and the
flatness verdict shim onto `lancet_eval.decay.analyze_decay`.
"""

from __future__ import annotations

import json
from pathlib import Path

from lancet_eval.flatness import (
    FlatnessRecord,
    SoakNodeFailure,
    SoakNodeTiming,
    flatness_verdict,
    records_from_run_journal,
    records_from_soak_jsonl,
    slice_medians,
)


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def _soak_line(ordinal: int, arm: str = "R", **overrides) -> dict:
    base = {
        "arm": arm,
        "ordinal": ordinal,
        "unix_ms": 1_700_000_000_000 + ordinal,
        "ok": True,
        "retrieve_ms": 100.0 + ordinal,
        "open_table_ms": 1.0,
        "checkout_ms": 0.2,
        "dense_ms": 60.0,
        "bm25_ms": 20.0,
        "fusion_ms": 0.1,
        "pack_ms": None,
        "graph_ms": None,
        "graph_timed_out": None,
        "alive_tasks": 3,
        "global_queue_depth": 0,
        "rss_hint": None,
    }
    base.update(overrides)
    return base


# --- records_from_soak_jsonl -------------------------------------------------------------


def test_records_from_soak_jsonl_assigns_gapfree_ordinals_and_skips_header(tmp_path: Path):
    path = tmp_path / "R.jsonl"
    _write_jsonl(
        path,
        [
            {"header": True, "arm": "R", "iterations": 3},
            _soak_line(1, retrieve_ms=101.0),
            _soak_line(2, retrieve_ms=102.0),
            _soak_line(3, retrieve_ms=103.0),
        ],
    )

    records = records_from_soak_jsonl(path, "R")

    assert [r.ordinal for r in records] == [1, 2, 3]
    assert all(r.segment == "segment-1" for r in records)
    durations = [r.node_timings[0].duration_ms for r in records]
    assert durations == [101.0, 102.0, 103.0]
    assert all(r.node_timings[0].node_name == "RetrieveHybrid" for r in records)
    assert all(r.node_failures == [] for r in records)


def test_records_from_soak_jsonl_graph_timed_out_does_not_censor(tmp_path: Path):
    path = tmp_path / "RGT.jsonl"
    _write_jsonl(
        path,
        [
            {"header": True, "arm": "RGT"},
            _soak_line(1, arm="RGT", ok=True, graph_ms=210.0, graph_timed_out=True),
        ],
    )

    records = records_from_soak_jsonl(path, "RGT")

    assert len(records) == 1
    assert records[0].node_failures == []
    assert len(records[0].node_timings) == 1
    assert records[0].node_timings[0].duration_ms == 101.0


def test_records_from_soak_jsonl_not_ok_censors(tmp_path: Path):
    path = tmp_path / "R.jsonl"
    _write_jsonl(
        path,
        [
            {"header": True, "arm": "R"},
            _soak_line(1, ok=False, retrieve_ms=None),
        ],
    )

    records = records_from_soak_jsonl(path, "R")

    assert len(records) == 1
    assert records[0].node_timings == []
    assert records[0].node_failures == [
        SoakNodeFailure(node_name="RetrieveHybrid", error_kind=1)
    ]


def test_records_from_soak_jsonl_filters_by_arm(tmp_path: Path):
    path = tmp_path / "mixed.jsonl"
    _write_jsonl(
        path,
        [
            {"header": True, "arm": "R"},
            _soak_line(1, arm="R"),
            _soak_line(1, arm="RP", pack_ms=50.0),
            _soak_line(2, arm="R"),
        ],
    )

    records = records_from_soak_jsonl(path, "R")

    assert [r.ordinal for r in records] == [1, 2]
    assert all(r.graph_arm == "R" for r in records)


# --- records_from_run_journal ------------------------------------------------------------


def _journal_record(**overrides) -> dict:
    base = {
        "corpus": "multihop_rag",
        "question_id": "q1",
        "graph_arm": "graph-off",
        "outcome": "success",
        "node_timings": [{"node_name": "RetrieveHybrid", "duration_ms": 150.0}],
        "node_failures": [],
    }
    base.update(overrides)
    return base


def test_records_from_run_journal_skips_header_and_assigns_line_order_ordinals(
    tmp_path: Path,
):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [
            {"type": "header", "partial": False},
            _journal_record(question_id="q1"),
            _journal_record(question_id="q2", node_timings=[{"node_name": "RetrieveHybrid", "duration_ms": 200.0}]),
        ],
    )

    records = records_from_run_journal(path)

    assert [r.ordinal for r in records] == [1, 2]
    assert records[0].node_timings[0].duration_ms == 150.0
    assert records[1].node_timings[0].duration_ms == 200.0


def test_records_from_run_journal_maps_node_failure_error_kind_1_to_censored(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [
            {"type": "header", "partial": False},
            _journal_record(
                outcome="error",
                node_timings=[],
                node_failures=[
                    {
                        "node_name": "RetrieveHybrid",
                        "error_kind": 1,
                        "error_message": "timeout",
                        "retryable": True,
                    }
                ],
            ),
        ],
    )

    records = records_from_run_journal(path)

    assert len(records) == 1
    assert records[0].node_failures == [
        SoakNodeFailure(node_name="RetrieveHybrid", error_kind=1)
    ]


def test_records_from_run_journal_harness_deadline_error_type_censors(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [
            {"type": "header", "partial": False},
            _journal_record(
                outcome="error",
                node_timings=[],
                node_failures=[],
                error_type="StreamDeadlineExceeded",
                error="deadline exceeded",
            ),
        ],
    )

    records = records_from_run_journal(path)

    assert len(records) == 1
    assert records[0].node_failures == [
        SoakNodeFailure(node_name="RetrieveHybrid", error_kind=1)
    ]


def test_records_from_run_journal_read_timeout_error_type_censors(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [
            {"type": "header", "partial": False},
            _journal_record(
                outcome="error",
                node_timings=[],
                node_failures=[],
                error_type="ReadTimeout",
                error="read timed out",
            ),
        ],
    )

    records = records_from_run_journal(path)

    assert records[0].node_failures == [
        SoakNodeFailure(node_name="RetrieveHybrid", error_kind=1)
    ]


def test_records_from_run_journal_ordinary_error_type_does_not_censor(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [
            {"type": "header", "partial": False},
            _journal_record(
                outcome="error",
                node_timings=[{"node_name": "RetrieveHybrid", "duration_ms": 300.0}],
                node_failures=[],
                error_type="ValueError",
                error="unrelated failure",
            ),
        ],
    )

    records = records_from_run_journal(path)

    assert records[0].node_failures == []
    assert records[0].node_timings[0].duration_ms == 300.0


# --- flatness_verdict ---------------------------------------------------------------------


def _flat_records(n: int = 20, duration_ms: float = 100.0) -> list[FlatnessRecord]:
    return [
        FlatnessRecord(
            ordinal=i,
            node_timings=[SoakNodeTiming(node_name="RetrieveHybrid", duration_ms=duration_ms)],
        )
        for i in range(1, n + 1)
    ]


def test_flatness_verdict_flat_series_passes(tmp_path: Path):
    records = _flat_records(20, 100.0)

    result = flatness_verdict(records)

    assert result.passed is True
    assert result.reason == "flat"
    assert result.trend_available is True
    assert result.window_available is True
    assert result.decay_present is False
    assert result.n == 20


def test_flatness_verdict_growing_series_fails_as_decay_present():
    records = [
        FlatnessRecord(
            ordinal=i,
            node_timings=[
                SoakNodeTiming(node_name="RetrieveHybrid", duration_ms=100.0 + i * 100.0)
            ],
        )
        for i in range(1, 21)
    ]

    result = flatness_verdict(records)

    assert result.passed is False
    assert result.reason == "decay_present"
    assert result.decay_present is True


def test_flatness_verdict_censored_observation_reads_unavailable_not_flat():
    records = _flat_records(20, 100.0)
    records[5] = FlatnessRecord(
        ordinal=6,
        node_failures=[SoakNodeFailure(node_name="RetrieveHybrid", error_kind=1)],
    )

    result = flatness_verdict(records)

    assert result.passed is False
    assert result.reason == "unavailable"
    assert result.trend_available is False
    assert result.window_available is False
    assert result.censored_count == 1


def test_flatness_verdict_empty_input_is_n0():
    result = flatness_verdict([])

    assert result.passed is False
    assert result.reason == "n=0"
    assert result.n == 0


# --- slice_medians ---------------------------------------------------------------------


def test_slice_medians_returns_per_slice_medians_in_ordinal_order():
    records = [
        FlatnessRecord(
            ordinal=i,
            node_timings=[SoakNodeTiming(node_name="RetrieveHybrid", duration_ms=float(i))],
        )
        for i in range(1, 121)
    ]

    medians = slice_medians(records, size=50)

    # slice 1: durations 1..50 -> median 25.5; slice 2: 51..100 -> median 75.5; slice 3: 101..120 -> median 110.5
    assert medians == [25.5, 75.5, 110.5]


def test_slice_medians_excludes_censored_and_unusable_records():
    records = [
        FlatnessRecord(
            ordinal=1,
            node_timings=[SoakNodeTiming(node_name="RetrieveHybrid", duration_ms=10.0)],
        ),
        FlatnessRecord(
            ordinal=2,
            node_failures=[SoakNodeFailure(node_name="RetrieveHybrid", error_kind=1)],
        ),
        FlatnessRecord(ordinal=3, node_timings=[]),
        FlatnessRecord(
            ordinal=4,
            node_timings=[SoakNodeTiming(node_name="RetrieveHybrid", duration_ms=30.0)],
        ),
    ]

    medians = slice_medians(records, size=50)

    assert medians == [20.0]
