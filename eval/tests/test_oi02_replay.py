"""Tests for OI-02 replay summarisation and arm verification (06.3.4.1-07 Task 2:
`replay-summary`, `check-arm`, `classify_m1`, `classify_m2`)."""

from __future__ import annotations

import json
from pathlib import Path

from lancet_eval.oi02 import CheckArmResult, check_arm, classify_m1, classify_m2, replay_summary


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def _run_record_line(
    question_id: str,
    *,
    started_at_ms: int,
    completed_at_ms: int,
    retrieve_ms: float | None,
    graph_arm: str = "graph-on",
    node_failures: list[dict] | None = None,
) -> dict:
    node_timings = [{"node_name": "ReformulateQuery", "duration_ms": 1.0}]
    if retrieve_ms is not None:
        node_timings.append({"node_name": "RetrieveHybrid", "duration_ms": retrieve_ms})
    node_timings.append({"node_name": "AssemblePrompt", "duration_ms": 5.0})
    return {
        "corpus": "multihop_rag",
        "question_id": question_id,
        "graph_arm": graph_arm,
        "outcome": "success",
        "answer": "answer",
        "notices": [],
        "node_failures": node_failures or [],
        "duration_ms": completed_at_ms - started_at_ms,
        "session_id": "",
        "correlation_id": "",
        "index_generation": "lance-701",
        "partial": False,
        "error_type": None,
        "error": None,
        "node_timings": node_timings,
        "workflow_meta": {
            "started_at_ms": started_at_ms,
            "completed_at_ms": completed_at_ms,
            "reformulation_used": False,
            "vector_count": 10,
            "bm25_count": 10,
            "graph_node_count": 0,
            "graph_edge_count": 0,
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "degraded_mode": False,
            "graph_prompt_fact_count": None,
        },
    }


# --- classify_m2 -----------------------------------------------------------------------


def test_classify_m2_grows_when_ratio_and_window_delta_exceed_thresholds():
    slices = [100.0, 120.0, 140.0, 160.0]  # slice3/slice0 = 1.6 >= 1.5
    assert classify_m2(slices, window_delta_ms=600.0) == "grows"


def test_classify_m2_not_grows_when_ratio_and_window_delta_under_thresholds():
    slices = [100.0, 105.0, 108.0, 110.0]  # ratio 1.1 < 1.2
    assert classify_m2(slices, window_delta_ms=100.0) == "not grows"


def test_classify_m2_ambiguous_otherwise():
    slices = [100.0, 110.0, 125.0, 130.0]  # ratio 1.3, between 1.2 and 1.5
    assert classify_m2(slices, window_delta_ms=200.0) == "ambiguous"


def test_classify_m2_ambiguous_with_fewer_than_two_slices():
    assert classify_m2([100.0], window_delta_ms=0.0) == "ambiguous"


def test_classify_m2_not_grows_reads_the_last_full_slice_not_a_fixed_slice_3():
    """Task 2's primary/primary-r2 scale (7 slices, 350 records): the plan's "not grows" rule is
    "the last full slice's median is under 1.2x the slice-0 median" -- for a 7-slice run that is
    slice 6, not slice 3. slice-3 is flat (ratio 1.05, under both the 1.2 "not grows" ceiling and
    the 1.5 "grows" floor) but slice 6 sits at 1.21x -- just over the "not grows" ceiling, so the
    correct classification is "ambiguous", not "not grows" (06.3.4.1-07 primary-r2 self-review)."""
    slices = [1441.5, 1483.5, 1311.0, 1405.5, 1304.5, 1569.0, 1747.5]  # slice3/0=0.975, slice6/0=1.212
    assert classify_m2(slices, window_delta_ms=265.0) == "ambiguous"


# --- classify_m1 -----------------------------------------------------------------------


def test_classify_m1_met_within_band():
    # target_ratio=17, actual ratio = 5000/300 = 16.67, within [8.5, 34]
    status, ratio = classify_m1(5000.0, 300.0, 17.0)
    assert status == "met"
    assert abs(ratio - 16.6667) < 0.01


def test_classify_m1_not_met_outside_band():
    status, ratio = classify_m1(100.0, 300.0, 17.0)
    assert status == "not met"


# --- replay_summary ---------------------------------------------------------------------


def test_replay_summary_writes_summary_json_with_slices_and_verdict(tmp_path: Path):
    arm_dir = tmp_path / "arm"
    arm_dir.mkdir()
    lines = [
        _run_record_line(f"q{i}", started_at_ms=1000 + i * 100, completed_at_ms=1050 + i * 100, retrieve_ms=50.0 + i)
        for i in range(1, 6)
    ]
    _write_jsonl(arm_dir / "journal.jsonl", lines)

    summary = replay_summary(arm_dir)
    assert (arm_dir / "summary.json").exists()
    assert summary["record_count"] == 5
    assert "flatness_verdict_full" in summary
    assert "slices_ordinal_50" in summary


def test_replay_summary_missing_journal_records_error(tmp_path: Path):
    arm_dir = tmp_path / "empty_arm"
    arm_dir.mkdir()
    summary = replay_summary(arm_dir)
    assert "error" in summary


def test_replay_summary_uncensored_prefix_stops_at_first_censored_record(tmp_path: Path):
    arm_dir = tmp_path / "arm"
    arm_dir.mkdir()
    lines = [
        _run_record_line("q1", started_at_ms=1000, completed_at_ms=1100, retrieve_ms=50.0),
        _run_record_line("q2", started_at_ms=1200, completed_at_ms=1300, retrieve_ms=60.0),
        _run_record_line(
            "q3",
            started_at_ms=1400,
            completed_at_ms=1500,
            retrieve_ms=None,
            node_failures=[
                {
                    "node_name": "RetrieveHybrid",
                    "error_kind": 1,
                    "error_message": "timeout",
                    "retryable": False,
                }
            ],
        ),
        _run_record_line("q4", started_at_ms=1600, completed_at_ms=1700, retrieve_ms=70.0),
    ]
    _write_jsonl(arm_dir / "journal.jsonl", lines)
    summary = replay_summary(arm_dir)
    assert summary["uncensored_prefix_n"] == 2


def test_replay_summary_order_match_against_production(tmp_path: Path):
    prod_dir = tmp_path / "prod"
    prod_dir.mkdir()
    prod_lines = [
        _run_record_line("q1", started_at_ms=1000, completed_at_ms=1100, retrieve_ms=50.0, graph_arm="graph-on"),
        _run_record_line("q2", started_at_ms=1200, completed_at_ms=1300, retrieve_ms=60.0, graph_arm="graph-off"),
    ]
    _write_jsonl(prod_dir / "journal.jsonl", prod_lines)

    arm_dir = tmp_path / "arm"
    arm_dir.mkdir()
    _write_jsonl(arm_dir / "journal.jsonl", prod_lines)  # same order

    summary = replay_summary(arm_dir, production_journal=prod_dir / "journal.jsonl")
    assert summary["order_match_production"] is True


def test_replay_summary_order_mismatch_detected(tmp_path: Path):
    prod_dir = tmp_path / "prod"
    prod_dir.mkdir()
    prod_lines = [
        _run_record_line("q1", started_at_ms=1000, completed_at_ms=1100, retrieve_ms=50.0),
        _run_record_line("q2", started_at_ms=1200, completed_at_ms=1300, retrieve_ms=60.0),
    ]
    _write_jsonl(prod_dir / "journal.jsonl", prod_lines)

    arm_dir = tmp_path / "arm"
    arm_dir.mkdir()
    _write_jsonl(arm_dir / "journal.jsonl", list(reversed(prod_lines)))  # different order

    summary = replay_summary(arm_dir, production_journal=prod_dir / "journal.jsonl")
    assert summary["order_match_production"] is False


# --- replay_summary: M1 formula depends on the arm's store_source (06.3.4.1-07 Task 4 --------
# drive-era arm self-review: replay_summary always used the ratio formula against
# soak_w_ms_reconciled, even for a pre-reconcile-store arm, where the plan requires a direct
# slice-0-vs-m1_reference_ms comparison instead (both arms run on the SAME store production
# did, so no soak-baseline denominator is needed or correct).


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_replay_summary_m1_reconciled_arm_uses_ratio_against_soak_baseline(tmp_path: Path):
    arm_dir = tmp_path / "arm"
    arm_dir.mkdir()
    lines = [_run_record_line(f"q{i}", started_at_ms=i * 100, completed_at_ms=i * 100 + 50, retrieve_ms=100.0) for i in range(1, 3)]
    _write_jsonl(arm_dir / "journal.jsonl", lines)
    _write_json(arm_dir / "header.json", {"store_source": "reconciled"})

    forensics = tmp_path / "forensics.json"
    _write_json(forensics, {"m1_prod_ratio": {"debug": 2.0}, "m1_reference_ms": 999.0})
    soak_baseline = tmp_path / "soak-baseline.json"
    _write_json(soak_baseline, {"soak_w_ms_reconciled": 50.0})

    summary = replay_summary(arm_dir, forensics_json=forensics, soak_baseline_json=soak_baseline)

    # slice0=100.0, denominator=50.0 -> ratio 2.0, target 2.0 (band 1.0-4.0) -> met
    assert summary["m1"] == {
        "status": "met",
        "ratio": 2.0,
        "target_ratio": 2.0,
        "primary_slice0_ms": 100.0,
        "denominator_ms": 50.0,
        "formula": "ratio",
    }


def test_replay_summary_m1_pre_reconcile_arm_compares_slice0_directly_to_reference(tmp_path: Path):
    arm_dir = tmp_path / "arm"
    arm_dir.mkdir()
    lines = [_run_record_line(f"q{i}", started_at_ms=i * 100, completed_at_ms=i * 100 + 50, retrieve_ms=100.0) for i in range(1, 3)]
    _write_jsonl(arm_dir / "journal.jsonl", lines)
    _write_json(arm_dir / "header.json", {"store_source": "pre-reconcile"})

    forensics = tmp_path / "forensics.json"
    # m1_prod_ratio/soak baseline are irrelevant here -- a pre-reconcile arm runs on the SAME
    # store production did, so it compares directly against m1_reference_ms, not a ratio.
    _write_json(forensics, {"m1_prod_ratio": {"debug": 999.0}, "m1_reference_ms": 200.0})
    soak_baseline = tmp_path / "soak-baseline.json"
    _write_json(soak_baseline, {"soak_w_ms_reconciled": 999.0})

    summary = replay_summary(arm_dir, forensics_json=forensics, soak_baseline_json=soak_baseline)

    # slice0=100.0 vs m1_reference_ms=200.0 -> ratio 0.5 (band 0.5-2.0, inclusive) -> met
    assert summary["m1"] == {
        "status": "met",
        "ratio": 0.5,
        "target_ratio": 1.0,
        "primary_slice0_ms": 100.0,
        "denominator_ms": 200.0,
        "formula": "store_matched",
    }


def test_replay_summary_m1_pre_reconcile_arm_not_met_outside_band(tmp_path: Path):
    arm_dir = tmp_path / "arm"
    arm_dir.mkdir()
    lines = [_run_record_line(f"q{i}", started_at_ms=i * 100, completed_at_ms=i * 100 + 50, retrieve_ms=100.0) for i in range(1, 3)]
    _write_jsonl(arm_dir / "journal.jsonl", lines)
    _write_json(arm_dir / "header.json", {"store_source": "pre-reconcile"})

    forensics = tmp_path / "forensics.json"
    _write_json(forensics, {"m1_reference_ms": 4910.5})  # slice0=100.0, ratio 0.02 -- way under 0.5

    summary = replay_summary(arm_dir, forensics_json=forensics)

    assert summary["m1"]["status"] == "not met"
    assert summary["m1"]["formula"] == "store_matched"


def test_replay_summary_m1_defaults_to_ratio_formula_when_header_missing(tmp_path: Path):
    # No header.json at all -- must not crash, and must fall back to the pre-existing ratio
    # behavior (every arm this tool has ever produced a header for was reconciled-store, so
    # a missing header is not itself evidence of a pre-reconcile arm).
    arm_dir = tmp_path / "arm"
    arm_dir.mkdir()
    lines = [_run_record_line(f"q{i}", started_at_ms=i * 100, completed_at_ms=i * 100 + 50, retrieve_ms=100.0) for i in range(1, 3)]
    _write_jsonl(arm_dir / "journal.jsonl", lines)

    forensics = tmp_path / "forensics.json"
    _write_json(forensics, {"m1_prod_ratio": {"debug": 2.0}})
    soak_baseline = tmp_path / "soak-baseline.json"
    _write_json(soak_baseline, {"soak_w_ms_reconciled": 50.0})

    summary = replay_summary(arm_dir, forensics_json=forensics, soak_baseline_json=soak_baseline)
    assert summary["m1"]["formula"] == "ratio"


# --- check_arm -------------------------------------------------------------------------


def _valid_header(**overrides) -> dict:
    base = {
        "arm_kind": "full-stack",
        "label": "smoke",
        "commit": "abc123",
        "dirty": False,
        "launch_command": "cargo run --bin engine",
        "binary_path": "engine.exe",
        "observability": "on",
        "telemetry": {"engine": "otlp", "gateway": "otlp"},
        "stderr_sink": "console",
        "stub_delays": {"embed_ms": 100, "chat_ms": 200},
        "warmup_n": 0,
        "limit": 2,
        "retries": {"value": 2, "mode": "fixed"},
        "workers": 1,
        "store_source": "reconciled",
        "start_utc": "2026-09-24T00:00:00Z",
        "end_utc": "2026-09-24T00:01:00Z",
        "egress_443_max": 0,
        "paid": False,
        "spend_guard": "dummy key",
        "otlp_4317_conns_max": {"engine": 1, "gateway": 1},
    }
    base.update(overrides)
    return base


def _write_header(arm_dir: Path, header: dict) -> None:
    (arm_dir / "header.json").write_bytes(json.dumps(header).encode("utf-8"))


def _write_equal_live_state(arm_dir: Path) -> None:
    state = {"nodes": 701, "edges": 701}
    (arm_dir / "live-state.before.json").write_text(json.dumps(state), encoding="utf-8")
    (arm_dir / "live-state.after.json").write_text(json.dumps(state), encoding="utf-8")
    (arm_dir / "copy-state.before.json").write_text(json.dumps(state), encoding="utf-8")
    (arm_dir / "copy-state.after.json").write_text(json.dumps(state), encoding="utf-8")


def test_check_arm_passes_for_a_well_formed_full_stack_arm(tmp_path: Path):
    arm_dir = tmp_path / "smoke"
    arm_dir.mkdir()
    _write_header(arm_dir, _valid_header())
    _write_equal_live_state(arm_dir)
    lines = [
        _run_record_line(f"q{i}", started_at_ms=1000 + i * 100, completed_at_ms=1050 + i * 100, retrieve_ms=50.0)
        for i in range(1, 5)
    ]
    _write_jsonl(arm_dir / "journal.jsonl", lines)
    (arm_dir / "stub-stats.json").write_text(
        json.dumps({"models": 1, "embeddings": 4, "chat_completions": 4}), encoding="utf-8"
    )
    result = check_arm(arm_dir, min_records=4)
    assert result.ok, result.failures


def test_check_arm_fails_when_header_missing(tmp_path: Path):
    arm_dir = tmp_path / "arm"
    arm_dir.mkdir()
    result = check_arm(arm_dir)
    assert not result.ok


def test_check_arm_fails_on_lossy_serialization_marker(tmp_path: Path):
    arm_dir = tmp_path / "arm"
    arm_dir.mkdir()
    header = _valid_header()
    header["launch_command"] = "System.Collections.Generic.List something"
    _write_header(arm_dir, header)
    _write_equal_live_state(arm_dir)
    _write_jsonl(arm_dir / "journal.jsonl", [_run_record_line("q1", started_at_ms=1, completed_at_ms=2, retrieve_ms=1.0)])
    result = check_arm(arm_dir)
    assert not result.ok
    assert any("System.Collections" in f for f in result.failures)


def test_check_arm_fails_when_live_state_differs(tmp_path: Path):
    arm_dir = tmp_path / "arm"
    arm_dir.mkdir()
    _write_header(arm_dir, _valid_header())
    (arm_dir / "live-state.before.json").write_text(json.dumps({"nodes": 701}), encoding="utf-8")
    (arm_dir / "live-state.after.json").write_text(json.dumps({"nodes": 702}), encoding="utf-8")
    (arm_dir / "copy-state.before.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    (arm_dir / "copy-state.after.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    _write_jsonl(arm_dir / "journal.jsonl", [_run_record_line("q1", started_at_ms=1, completed_at_ms=2, retrieve_ms=1.0)])
    result = check_arm(arm_dir)
    assert not result.ok
    assert any("live-state" in f for f in result.failures)


def test_check_arm_fails_when_below_min_records(tmp_path: Path):
    arm_dir = tmp_path / "arm"
    arm_dir.mkdir()
    _write_header(arm_dir, _valid_header())
    _write_equal_live_state(arm_dir)
    _write_jsonl(arm_dir / "journal.jsonl", [_run_record_line("q1", started_at_ms=1, completed_at_ms=2, retrieve_ms=1.0)])
    result = check_arm(arm_dir, min_records=10)
    assert not result.ok
    assert any("min-records" in f for f in result.failures)


def test_check_arm_fails_when_egress_nonzero_for_unpaid_arm(tmp_path: Path):
    arm_dir = tmp_path / "arm"
    arm_dir.mkdir()
    _write_header(arm_dir, _valid_header(egress_443_max=1))
    _write_equal_live_state(arm_dir)
    _write_jsonl(arm_dir / "journal.jsonl", [_run_record_line("q1", started_at_ms=1, completed_at_ms=2, retrieve_ms=1.0)])
    (arm_dir / "stub-stats.json").write_text(json.dumps({"embeddings": 1, "chat_completions": 1}), encoding="utf-8")
    result = check_arm(arm_dir)
    assert not result.ok
    assert any("egress_443_max" in f for f in result.failures)


def test_check_arm_same_config_as_detects_mismatch(tmp_path: Path):
    arm_a = tmp_path / "a"
    arm_a.mkdir()
    _write_header(arm_a, _valid_header())
    _write_equal_live_state(arm_a)
    _write_jsonl(arm_a / "journal.jsonl", [_run_record_line("q1", started_at_ms=1, completed_at_ms=2, retrieve_ms=1.0)])
    (arm_a / "stub-stats.json").write_text(json.dumps({"embeddings": 1, "chat_completions": 1}), encoding="utf-8")

    arm_b = tmp_path / "b"
    arm_b.mkdir()
    _write_header(arm_b, _valid_header(workers=4))  # different workers
    _write_equal_live_state(arm_b)
    _write_jsonl(arm_b / "journal.jsonl", [_run_record_line("q1", started_at_ms=1, completed_at_ms=2, retrieve_ms=1.0)])
    (arm_b / "stub-stats.json").write_text(json.dumps({"embeddings": 1, "chat_completions": 1}), encoding="utf-8")

    result = check_arm(arm_a, same_config_as=arm_b)
    assert not result.ok
    assert any("workers" in f for f in result.failures)


def test_check_arm_same_config_as_passes_when_equal(tmp_path: Path):
    arm_a = tmp_path / "a"
    arm_a.mkdir()
    _write_header(arm_a, _valid_header())
    _write_equal_live_state(arm_a)
    _write_jsonl(arm_a / "journal.jsonl", [_run_record_line("q1", started_at_ms=1, completed_at_ms=2, retrieve_ms=1.0)])
    (arm_a / "stub-stats.json").write_text(json.dumps({"embeddings": 1, "chat_completions": 1}), encoding="utf-8")

    arm_b = tmp_path / "b"
    arm_b.mkdir()
    _write_header(arm_b, _valid_header(label="other"))  # label is not a same-config field
    _write_equal_live_state(arm_b)
    _write_jsonl(arm_b / "journal.jsonl", [_run_record_line("q1", started_at_ms=1, completed_at_ms=2, retrieve_ms=1.0)])
    (arm_b / "stub-stats.json").write_text(json.dumps({"embeddings": 1, "chat_completions": 1}), encoding="utf-8")

    result = check_arm(arm_a, same_config_as=arm_b)
    assert result.ok, result.failures
