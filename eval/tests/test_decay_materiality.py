"""Tests for the D-89 materiality rule (06.3.4.1-21).

Boundary cases run on hand-constructed `decay.TrendResult`,
`WindowComparisonResult` and `DecayVerdict` objects, not synthetic series: float
products of a fitted slope rarely land exactly on a threshold, and D-89 says equality
fires.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lancet_eval import decay
from lancet_eval.decay_materiality import (
    NOISE_ESCALATION_FRACTION,
    NOISE_WINDOW_RECORDS,
    analyze_material_decay,
    contiguous_window_noise,
    evaluate_material_decay,
    first_uncensored,
    main,
    noise_escalation,
    replay_arm_flips,
)
from lancet_eval.flatness import (
    FlatnessRecord,
    SoakNodeFailure,
    SoakNodeTiming,
    flatness_verdict,
    records_from_run_journal,
)
from lancet_eval.thresholds import (
    COMMITTED_DECAY_THRESHOLDS_06341,
    COMMITTED_THRESHOLDS,
    MaterialDecayThresholds,
    ThresholdError,
)


def _verdict(
    *,
    slope: float = 0.0,
    significant: bool = False,
    early_p95: float = 200.0,
    delta: float = 0.0,
    trend_available: bool = True,
    window_available: bool = True,
    censored: int = 0,
) -> decay.DecayVerdict:
    trend = decay.TrendResult(
        slope=slope,
        p_value=0.001 if significant else 0.9,
        is_significant=significant,
        is_censored=censored > 0,
        censored_count=censored,
        is_available=trend_available,
        reason="hand-built",
    )
    window = decay.WindowComparisonResult(
        early_window_size=80 if window_available else 0,
        early_percentile_ms=early_p95 if window_available else 0.0,
        late_window_size=80 if window_available else 0,
        late_percentile_ms=(early_p95 + delta) if window_available else 0.0,
        delta_ms=delta if window_available else 0.0,
        materiality_threshold_ms=500.0,
        is_materially_elevated=False,
        is_censored=censored > 0,
        censored_count=censored,
        is_available=window_available,
        reason="hand-built",
    )
    return decay.DecayVerdict(
        verdict_decay_present=False,
        prong_slope_fired=False,
        prong_window_fired=False,
        slope_statistic=slope,
        slope_threshold=0.05,
        window_delta_ms=delta if window_available else 0.0,
        window_threshold_ms=500.0,
        trend_result=trend,
        window_result=window,
        restart_result=None,
    )


# --- the committed D-89 set ----------------------------------------------------


def test_d89_set_carries_the_user_decided_numbers():
    rule = COMMITTED_DECAY_THRESHOLDS_06341

    assert rule.projection_horizon_records == 658
    assert rule.relative_materiality_fraction == 0.25
    assert rule.materiality_floor_ms == 25.0
    assert rule.base is COMMITTED_THRESHOLDS
    assert "D-89" in rule.provenance
    assert "D-64" in rule.provenance
    rule.validate()


def test_06_3_3_committed_thresholds_stay_byte_identical():
    # D-89 / D-64: 06.3.3's serialized decision inputs must not move.
    assert COMMITTED_THRESHOLDS.to_dict() == {
        "multiplier": 1.5,
        "derivation_percentile": 0.95,
        "decay_significance_threshold": 0.05,
        "materiality_delta_ms": 500.0,
        "window_fractions": [0.25, 0.25],
        "segment_boundary_sizes": [30, 30],
        "min_stratum_cell_size": 10,
        "max_tolerated_graph_timeout_rate": 0.10,
        "bootstrap_seed": 42,
        "slack_ms": 500.0,
        "provenance": (
            "Committed decision inputs per Phase 06.3.3: D-14 (multiplier=1.5, p95), "
            "D-18/D-19 (decay alpha=0.05, delta=500ms, window fractions 25%/25%), "
            "D-21 (segment boundary sizes 30/30), AI-SPEC bootstrap seed=42, "
            "min stratum cell size=10, max tolerated graph timeout rate=0.10, "
            "nesting invariant slack=500ms."
        ),
    }


def test_materiality_threshold_is_max_of_fraction_and_floor():
    rule = COMMITTED_DECAY_THRESHOLDS_06341

    assert rule.materiality_threshold_ms(200.0) == 50.0
    assert rule.materiality_threshold_ms(199.0) == 49.75
    assert rule.materiality_threshold_ms(80.0) == 25.0
    assert rule.materiality_threshold_ms(10.0) == 25.0


@pytest.mark.parametrize(
    ("horizon", "fraction", "floor"),
    [(0, 0.25, 25.0), (658, 0.0, 25.0), (658, 1.0, 25.0), (658, 0.25, -1.0)],
)
def test_material_decay_thresholds_validate_rejects_bad_inputs(
    horizon, fraction, floor
):
    bad = MaterialDecayThresholds(
        base=COMMITTED_THRESHOLDS,
        projection_horizon_records=horizon,
        relative_materiality_fraction=fraction,
        materiality_floor_ms=floor,
        provenance="test",
    )

    with pytest.raises(ThresholdError):
        bad.validate()


# --- boundary cases on hand-built verdicts --------------------------------------


def test_window_prong_fires_at_exact_equality_and_not_below():
    # early p95 200 ms -> threshold 50 ms.
    at_boundary = evaluate_material_decay(_verdict(early_p95=200.0, delta=50.0))
    below = evaluate_material_decay(_verdict(early_p95=200.0, delta=49.9))

    assert at_boundary.window_prong_fired is True
    assert at_boundary.decay_present is True
    assert at_boundary.materiality_threshold_ms == 50.0
    assert below.window_prong_fired is False
    assert below.decay_present is False


def test_window_prong_floor_governs_a_fast_node():
    # early p95 80 ms -> 25% is 20 ms, so the 25 ms floor applies.
    at_floor = evaluate_material_decay(_verdict(early_p95=80.0, delta=25.0))
    below_floor = evaluate_material_decay(_verdict(early_p95=80.0, delta=24.9))

    assert at_floor.materiality_threshold_ms == 25.0
    assert at_floor.window_prong_fired is True
    assert below_floor.window_prong_fired is False


def test_slope_prong_fires_at_exact_projected_boundary():
    # early p95 2632 ms -> threshold 658 ms; slope 1.0 ms/query projects exactly 658 ms.
    at_boundary = evaluate_material_decay(
        _verdict(slope=1.0, significant=True, early_p95=2632.0)
    )
    below = evaluate_material_decay(
        _verdict(slope=0.999, significant=True, early_p95=2632.0)
    )

    assert at_boundary.materiality_threshold_ms == 658.0
    assert at_boundary.projected_growth_ms == 658.0
    assert at_boundary.slope_prong_fired is True
    assert at_boundary.decay_present is True
    assert below.slope_prong_fired is False
    assert below.decay_present is False


def test_slope_prong_needs_significance():
    # 10 ms/query would project 6580 ms, but the trend is not significant.
    verdict = evaluate_material_decay(
        _verdict(slope=10.0, significant=False, early_p95=200.0)
    )

    assert verdict.slope_prong_available is True
    assert verdict.slope_prong_fired is False
    assert verdict.decay_present is False


def test_significant_negative_slope_does_not_fire():
    verdict = evaluate_material_decay(
        _verdict(slope=-5.0, significant=True, early_p95=200.0)
    )

    assert verdict.slope_prong_fired is False
    assert verdict.decay_present is False


def test_pass_a_shaped_slope_is_below_threshold():
    # BUDGETS' figures: slope +0.0330 ms/query, early p95 199.0 -> 21.7 ms < 49.75 ms.
    verdict = evaluate_material_decay(
        _verdict(slope=0.0330, significant=True, early_p95=199.0, delta=-6.0)
    )

    assert verdict.projected_growth_ms == pytest.approx(0.0330 * 658)
    assert verdict.materiality_threshold_ms == 49.75
    assert verdict.decay_present is False


def test_unavailable_window_makes_both_prongs_unavailable_never_flat():
    # A huge significant slope must not leak through when the window prong is
    # unavailable: the threshold cannot be computed without the early-window p95.
    verdict = evaluate_material_decay(
        _verdict(
            slope=50.0,
            significant=True,
            window_available=False,
            censored=1,
            trend_available=False,
        )
    )

    assert verdict.slope_prong_available is False
    assert verdict.window_prong_available is False
    assert verdict.materiality_threshold_ms is None
    assert verdict.decay_present is False
    assert verdict.reason == "unavailable"
    assert verdict.censored_count == 1


def test_window_unavailable_with_trend_available_still_reads_unavailable():
    verdict = evaluate_material_decay(
        _verdict(slope=50.0, significant=True, window_available=False)
    )

    assert verdict.slope_prong_available is False
    assert verdict.window_prong_available is False
    assert verdict.materiality_threshold_ms is None
    assert verdict.slope_prong_fired is False


# --- analyze_material_decay on record sets --------------------------------------


def _flat(n: int = 40, duration_ms: float = 100.0) -> list[FlatnessRecord]:
    return [
        FlatnessRecord(
            ordinal=i,
            node_timings=[
                SoakNodeTiming(node_name="RetrieveHybrid", duration_ms=duration_ms)
            ],
        )
        for i in range(1, n + 1)
    ]


def test_analyze_material_decay_flat_series_is_available_and_not_present():
    verdict = analyze_material_decay(_flat(40, 100.0))

    assert verdict.slope_prong_available is True
    assert verdict.window_prong_available is True
    assert verdict.decay_present is False
    assert verdict.reason == "flat"
    assert verdict.materiality_threshold_ms == 25.0
    assert verdict.rule_provenance == COMMITTED_DECAY_THRESHOLDS_06341.provenance


def test_analyze_material_decay_growing_series_is_present():
    records = [
        FlatnessRecord(
            ordinal=i,
            node_timings=[
                SoakNodeTiming(node_name="RetrieveHybrid", duration_ms=100.0 + i * 5.0)
            ],
        )
        for i in range(1, 41)
    ]

    verdict = analyze_material_decay(records)

    assert verdict.decay_present is True
    assert verdict.slope_prong_fired is True
    assert verdict.window_prong_fired is True
    assert verdict.reason == "decay_present"


def test_analyze_material_decay_censored_set_is_unavailable_not_flat():
    records = _flat(40, 100.0)
    records[10] = FlatnessRecord(
        ordinal=11,
        node_failures=[SoakNodeFailure(node_name="RetrieveHybrid", error_kind=1)],
    )

    verdict = analyze_material_decay(records)

    assert verdict.slope_prong_available is False
    assert verdict.window_prong_available is False
    assert verdict.decay_present is False
    assert verdict.reason == "unavailable"
    assert verdict.censored_count == 1


def test_analyze_material_decay_empty_and_tiny_sets_are_unavailable():
    for records in ([], _flat(3), _flat(7)):
        verdict = analyze_material_decay(records)

        assert verdict.window_prong_available is False
        assert verdict.slope_prong_available is False
        assert verdict.decay_present is False
        assert verdict.reason == "unavailable"


# --- historical series, pinned from the committed journals (read in place) -----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PASS_A_JOURNAL = (
    _REPO_ROOT
    / "eval"
    / "runs"
    / "2026-09-28-passA-measure-multihop_rag"
    / "journal.jsonl"
)
_DRIVE_0634_JOURNAL = (
    _REPO_ROOT / "eval" / "runs" / "2026-09-09-multihop_rag" / "journal.jsonl"
)


def test_06_3_4_first_350_uncensored_records_read_decay_present():
    records = records_from_run_journal(_DRIVE_0634_JOURNAL)

    first350 = first_uncensored(records, 350)

    assert len(first350) == 350
    assert [r.ordinal for r in first350] == list(range(1, 351))
    verdict = analyze_material_decay(first350)
    assert verdict.slope_prong_available is True
    assert verdict.window_prong_available is True
    assert verdict.decay_present is True


def test_06_3_4_full_journal_is_censored_so_unavailable_never_flat():
    # The full 658-record drive contains harness timeouts: both prongs unavailable.
    records = records_from_run_journal(_DRIVE_0634_JOURNAL)

    verdict = analyze_material_decay(records)
    result = flatness_verdict(records)

    assert verdict.slope_prong_available is False
    assert verdict.window_prong_available is False
    assert verdict.decay_present is False
    assert result.reason == "unavailable"
    assert result.passed is False


def test_pass_a_measured_records_are_not_decay_present_under_d89():
    records = records_from_run_journal(_PASS_A_JOURNAL)

    verdict = analyze_material_decay(records)

    assert verdict.slope_prong_available is True
    assert verdict.window_prong_available is True
    assert verdict.decay_present is False
    assert verdict.early_p95_ms == 199.0
    assert verdict.late_p95_ms == 193.0
    assert verdict.materiality_threshold_ms == 49.75


def test_first_uncensored_skips_censored_records_and_renumbers_from_one():
    records = _flat(10, 100.0)
    records[2] = FlatnessRecord(
        ordinal=3,
        node_failures=[SoakNodeFailure(node_name="RetrieveHybrid", error_kind=1)],
    )
    records[4] = FlatnessRecord(ordinal=5, node_timings=[])  # no RetrieveHybrid timing

    kept = first_uncensored(records, 5)

    assert [r.ordinal for r in kept] == [1, 2, 3, 4, 5]
    assert all(r.node_failures == [] for r in kept)
    assert all(len(r.node_timings) == 1 for r in kept)


def test_first_uncensored_returns_fewer_when_the_series_is_short():
    assert len(first_uncensored(_flat(6, 100.0), 10)) == 6


def test_a_censored_record_in_the_set_reads_unavailable_via_flatness_verdict():
    records = _flat(40, 100.0)
    records[3] = FlatnessRecord(
        ordinal=4,
        node_failures=[SoakNodeFailure(node_name="RetrieveHybrid", error_kind=1)],
    )

    assert analyze_material_decay(records).decay_present is False
    assert flatness_verdict(records).reason == "unavailable"


# --- consumer invariant (assumption-delta companion) ---------------------------------


def test_flatness_verdict_agrees_with_analyze_material_decay_on_every_fixture():
    censored = _flat(40, 100.0)
    censored[7] = FlatnessRecord(
        ordinal=8,
        node_failures=[SoakNodeFailure(node_name="RetrieveHybrid", error_kind=1)],
    )
    growing = [
        FlatnessRecord(
            ordinal=i,
            node_timings=[
                SoakNodeTiming(node_name="RetrieveHybrid", duration_ms=100.0 + i * 5.0)
            ],
        )
        for i in range(1, 41)
    ]
    fixtures = [
        records_from_run_journal(_PASS_A_JOURNAL),
        first_uncensored(records_from_run_journal(_DRIVE_0634_JOURNAL), 350),
        censored,
        growing,
        _flat(40, 100.0),
    ]

    for records in fixtures:
        assert (
            flatness_verdict(records).decay_present
            == analyze_material_decay(records).decay_present
        )


# --- the 200-record noise check ------------------------------------------------------


def test_noise_constants_are_the_committed_escalation_rule():
    assert NOISE_WINDOW_RECORDS == 200
    assert NOISE_ESCALATION_FRACTION == 0.05


def test_noise_escalation_rule_boundaries():
    # first-200 or last-200 window fires, or at least 5% of windows fire.
    assert noise_escalation(121, 0, False, False) is False
    assert noise_escalation(121, 6, False, False) is False  # 4.96%
    assert noise_escalation(121, 7, False, False) is True  # 5.79%
    assert noise_escalation(20, 1, False, False) is True  # exactly 5%
    assert noise_escalation(21, 1, False, False) is False  # 4.76%
    assert noise_escalation(121, 1, True, False) is True
    assert noise_escalation(121, 1, False, True) is True


def test_contiguous_window_noise_flat_320_records_has_121_windows_and_no_fires():
    result = contiguous_window_noise(_flat(320, 160.0))

    assert result["windows"] == 121
    assert len(result["rows"]) == 121
    assert result["fired_either"] == 0
    assert result["fired_fraction"] == 0.0
    assert result["first_window_fired"] is False
    assert result["last_window_fired"] is False
    assert result["escalate"] is False
    assert result["unavailable"] == 0


def test_contiguous_window_noise_counts_fires_per_prong_and_escalates_on_fraction():
    # 40 flat records with one 200 ms spike at 0-based index 24. With a 20-record window
    # the late window holds the spike for offsets 5..9 (window prong fires), the first
    # (offset 0) and last (offset 20) windows stay quiet.
    records = _flat(40, 100.0)
    records[24] = FlatnessRecord(
        ordinal=25,
        node_timings=[SoakNodeTiming(node_name="RetrieveHybrid", duration_ms=200.0)],
    )

    result = contiguous_window_noise(records, window=20)

    assert result["windows"] == 21
    assert result["fired_window"] == 5
    assert result["fired_either"] == 5
    assert result["fired_slope"] == 0
    assert result["first_window_fired"] is False
    assert result["last_window_fired"] is False
    assert result["fired_fraction"] == pytest.approx(5 / 21)
    assert result["escalate"] is True
    fired_offsets = [row["offset"] for row in result["rows"] if row["decay_present"]]
    assert fired_offsets == [5, 6, 7, 8, 9]


def test_contiguous_window_noise_flags_a_fired_last_window():
    records = [
        FlatnessRecord(
            ordinal=i,
            node_timings=[
                SoakNodeTiming(
                    node_name="RetrieveHybrid",
                    duration_ms=100.0 if i <= 30 else 400.0,
                )
            ],
        )
        for i in range(1, 41)
    ]

    result = contiguous_window_noise(records, window=20)

    assert result["last_window_fired"] is True
    assert result["escalate"] is True


def test_contiguous_window_noise_refuses_a_series_shorter_than_the_window():
    with pytest.raises(ValueError, match="window"):
        contiguous_window_noise(_flat(10, 100.0), window=20)


def test_contiguous_window_noise_reports_unavailable_windows_as_inconclusive():
    records = _flat(40, 100.0)
    records[10] = FlatnessRecord(
        ordinal=11,
        node_failures=[SoakNodeFailure(node_name="RetrieveHybrid", error_kind=1)],
    )

    result = contiguous_window_noise(records, window=20)

    assert result["unavailable"] > 0
    assert result["conclusive"] is False
    assert result["fired_either"] == 0


# --- the replay-arm flip reporter -----------------------------------------------------


def _drive_line(question_id: str, retrieve_ms: float) -> dict:
    return {
        "corpus": "multihop_rag",
        "question_id": question_id,
        "graph_arm": "graph-on",
        "outcome": "success",
        "node_timings": [{"node_name": "RetrieveHybrid", "duration_ms": retrieve_ms}],
        "node_failures": [],
    }


def _write_journal(path: Path, durations: list[float]) -> None:
    lines = [{"type": "header", "corpus": "multihop_rag", "partial": False}]
    lines += [_drive_line(f"q{i}", d) for i, d in enumerate(durations, start=1)]
    path.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )


def _old_verdict(passed: bool, decay_present: bool) -> dict:
    return {
        "flatness_verdict_full": {
            "passed": passed,
            "reason": "flat" if passed else "decay_present",
            "decay_present": decay_present,
            "trend_available": True,
            "window_available": True,
            "slope_ms_per_query": 0.0,
            "window_delta_ms": 0.0,
            "censored_count": 0,
            "n": 20,
        }
    }


def _snapshot(root: Path) -> dict[str, tuple[int, float]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_replay_arm_flips_reports_old_new_and_flipped_without_writing(tmp_path: Path):
    root = tmp_path / "pre-fix"
    flat_arm = root / "flat-arm"
    same_arm = root / "same-arm"
    for arm in (flat_arm, same_arm):
        arm.mkdir(parents=True)
        _write_journal(arm / "journal.jsonl", [100.0] * 20)
    (flat_arm / "summary.json").write_text(
        json.dumps(_old_verdict(passed=False, decay_present=True)), encoding="utf-8"
    )
    (same_arm / "summary.json").write_text(
        json.dumps(_old_verdict(passed=True, decay_present=False)), encoding="utf-8"
    )
    nested = flat_arm / "warmup"
    nested.mkdir()
    _write_journal(nested / "journal.jsonl", [100.0] * 20)
    before = _snapshot(root)

    report = replay_arm_flips(root)

    assert _snapshot(root) == before
    by_arm = {row["arm"]: row for row in report["arms"]}
    assert sorted(by_arm) == ["flat-arm", "same-arm"]
    assert by_arm["flat-arm"]["flipped"] is True
    assert by_arm["flat-arm"]["old"]["decay_present"] is True
    assert by_arm["flat-arm"]["new"]["decay_present"] is False
    assert by_arm["flat-arm"]["new"]["passed"] is True
    assert by_arm["same-arm"]["flipped"] is False
    assert report["flipped_arms"] == ["flat-arm"]


def test_replay_arm_flips_records_a_missing_summary_without_asserting_a_flip(
    tmp_path: Path,
):
    root = tmp_path / "pre-fix"
    arm = root / "no-summary"
    arm.mkdir(parents=True)
    _write_journal(arm / "journal.jsonl", [100.0] * 20)

    report = replay_arm_flips(root)

    row = report["arms"][0]
    assert row["old"] is None
    assert row["flipped"] is None
    assert row["new"]["passed"] is True


def test_replay_arm_flips_adds_the_contrast_first_n_reading(tmp_path: Path):
    root = tmp_path / "pre-fix"
    arm = root / "a"
    arm.mkdir(parents=True)
    _write_journal(arm / "journal.jsonl", [100.0] * 20)
    contrast = tmp_path / "contrast.jsonl"
    _write_journal(contrast, [100.0 + 10.0 * i for i in range(20)])

    report = replay_arm_flips(root, contrast_journal=contrast, contrast_first_n=12)

    reading = report["contrast_first_n"]
    assert reading["n"] == 12
    assert reading["requested_n"] == 12
    assert reading["decay_present"] is True
    assert reading["slope_prong_available"] is True


# --- the CLI -------------------------------------------------------------------------


def _measure_journal(path: Path, durations: list[float]) -> None:
    lines = []
    for i, d in enumerate(durations, start=1):
        line = _drive_line(f"q{i}", d)
        line.update({"ordinal": i, "segment": "segment-1", "warm_up": False})
        lines.append(line)
    path.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )


def test_cli_help_lists_the_three_subcommands(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for name in ("regate", "noise", "arms"):
        assert name in out


def test_cli_regate_writes_the_verdict_json(tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    _measure_journal(journal, [100.0] * 20)
    out = tmp_path / "out" / "regate.json"

    code = main(["regate", "--journal", str(journal), "--out", str(out)])

    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["n"] == 20
    assert data["slope_prong_available"] is True
    assert data["window_prong_available"] is True
    assert data["decay_present"] is False
    assert data["passed"] is True
    assert data["materiality_threshold_ms"] == 25.0
    assert data["may_derive_budgets"] is True
    assert data["rule"] == "D-89"
    assert data["thresholds"]["projection_horizon_records"] == 658


def test_cli_regate_on_a_censored_journal_may_not_derive(tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    _measure_journal(journal, [100.0] * 20)
    lines = journal.read_text(encoding="utf-8").splitlines()
    censored = json.loads(lines[5])
    censored["node_timings"] = []
    censored["node_failures"] = [
        {
            "node_name": "RetrieveHybrid",
            "error_kind": 1,
            "error_message": "timeout",
            "retryable": False,
        }
    ]
    lines[5] = json.dumps(censored)
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / "regate.json"

    assert main(["regate", "--journal", str(journal), "--out", str(out)]) == 0

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["window_prong_available"] is False
    assert data["may_derive_budgets"] is False
    assert data["reason"] == "unavailable"


def test_cli_noise_writes_the_window_check(tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    _measure_journal(journal, [100.0] * 40)
    out = tmp_path / "noise.json"

    code = main(
        ["noise", "--journal", str(journal), "--window", "20", "--out", str(out)]
    )

    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["windows"] == 21
    assert data["escalate"] is False
    assert data["escalation_rule"]


def test_cli_arms_writes_the_flip_report(tmp_path: Path):
    root = tmp_path / "pre-fix"
    (root / "a").mkdir(parents=True)
    _write_journal(root / "a" / "journal.jsonl", [100.0] * 20)
    out = tmp_path / "arms.json"

    code = main(["arms", "--replay-root", str(root), "--out", str(out)])

    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [row["arm"] for row in data["arms"]] == ["a"]


def test_cli_refuses_an_out_path_under_eval_runs(tmp_path: Path, capsys):
    journal = tmp_path / "journal.jsonl"
    _measure_journal(journal, [100.0] * 20)
    target = _REPO_ROOT / "eval" / "runs" / "zz-d89-refusal-test" / "out.json"

    code = main(["regate", "--journal", str(journal), "--out", str(target)])

    assert code == 2
    assert "refusing" in capsys.readouterr().err
    assert not target.exists()
    assert not target.parent.exists()


def test_cli_refuses_an_out_path_under_the_replay_root(tmp_path: Path, capsys):
    root = tmp_path / "pre-fix"
    (root / "a").mkdir(parents=True)
    _write_journal(root / "a" / "journal.jsonl", [100.0] * 20)
    target = root / "a" / "d89.json"

    code = main(["arms", "--replay-root", str(root), "--out", str(target)])

    assert code == 2
    assert "refusing" in capsys.readouterr().err
    assert not target.exists()


def test_cli_refuses_an_out_path_equal_to_the_input_journal(tmp_path: Path, capsys):
    journal = tmp_path / "journal.jsonl"
    _measure_journal(journal, [100.0] * 20)
    before = journal.read_text(encoding="utf-8")

    code = main(["regate", "--journal", str(journal), "--out", str(journal)])

    assert code == 2
    assert "refusing" in capsys.readouterr().err
    assert journal.read_text(encoding="utf-8") == before
