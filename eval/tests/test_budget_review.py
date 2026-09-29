"""Tests for the pass-A budget derivation options and hazards (06.3.4.1-24, G2).

The committed 06.3.3 derivation rule (p95 x 1.5, 500 ms nesting slack, harness
ceilings) is used unchanged. These tests pin the two things this plan adds around it:
swapping only the two unmeasured inner budgets, and counting pass A's observed
durations against each resulting budget.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lancet_eval import budget_review
from lancet_eval.budget_review import (
    INNER_SOURCE_OPTIONS,
    derive_option,
    hazards_report,
    main,
    node_exceedances,
    noise_summary,
    prompt_floor_table,
)
from lancet_eval.client import NodeFailed
from lancet_eval.journal import NodeTiming
from lancet_eval.measure import MeasurementRecord

REPO_ROOT = Path(__file__).resolve().parents[2]
PASS_A_DIR = REPO_ROOT / "eval" / "runs" / "2026-09-28-passA-measure-multihop_rag"
PASS_A_JOURNAL = PASS_A_DIR / "journal.jsonl"
PASS_A_MEASUREMENT = PASS_A_DIR / "measurement.json"
FORENSICS = (
    REPO_ROOT
    / ".planning"
    / "phases"
    / "06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair"
    / "forensics"
    / "passA-2026-09-28"
)
REGATE = FORENSICS / "d89-regate.json"

NODES = (
    "ReformulateQuery",
    "RetrieveHybrid",
    "ExtractGraphContext",
    "AssemblePrompt",
    "GenerateAnswer",
)
BUDGET_KEYS = (
    "reformulate_timeout_ms",
    "query_embedding_timeout_ms",
    "retrieve_timeout_ms",
    "graph_operation_timeout_ms",
    "graph_node_timeout_ms",
    "prompt_timeout_ms",
    "generation_node_timeout_ms",
)

pass_a_only = pytest.mark.skipif(
    not (PASS_A_JOURNAL.exists() and PASS_A_MEASUREMENT.exists() and REGATE.exists()),
    reason="pass A evidence not present",
)


def _record(
    ordinal: int,
    timings: dict[str, float],
    *,
    generation_failed: bool = False,
) -> MeasurementRecord:
    return MeasurementRecord(
        corpus="multihop_rag",
        question_id=f"q{ordinal}",
        graph_arm="graph-on",
        ordinal=ordinal,
        segment="seg",
        outcome="error" if generation_failed else "success",
        node_failures=[
            NodeFailed(
                node_name="GenerateAnswer",
                error_kind=3,
                error_message="answer basis 'mixed' requires at least one cited ID",
                retryable=False,
            )
        ]
        if generation_failed
        else [],
        node_timings=[
            NodeTiming(node_name=node, duration_ms=ms) for node, ms in timings.items()
        ],
    )


def _series(count: int = 20) -> list[MeasurementRecord]:
    """Twenty records with a known spread, large enough for a nearest-rank p95."""
    return [
        _record(
            i + 1,
            {
                "ReformulateQuery": 0.0,
                "RetrieveHybrid": 1000.0 + 10.0 * i,
                "ExtractGraphContext": 5000.0 + 100.0 * i,
                "AssemblePrompt": 5.0 + i,
                "GenerateAnswer": 1000.0,
            },
        )
        for i in range(count)
    ]


MEASUREMENT = {
    "raised_budgets": {
        "reformulate_timeout_ms": 5000,
        "query_embedding_timeout_ms": 30000,
        "retrieve_timeout_ms": 120000,
        "graph_operation_timeout_ms": 120000,
        "graph_node_timeout_ms": 150500,
        "prompt_timeout_ms": 120000,
        "generation_node_timeout_ms": 65000,
    },
    "sse_read_timeout_s": 300.0,
    "question_deadline_s": 600.0,
}


def _budgets(**overrides: int) -> dict[str, int]:
    base = {
        "reformulate_timeout_ms": 5000,
        "query_embedding_timeout_ms": 645,
        "retrieve_timeout_ms": 1145,
        "graph_operation_timeout_ms": 38595,
        "graph_node_timeout_ms": 39740,
        "prompt_timeout_ms": 11,
        "generation_node_timeout_ms": 65000,
    }
    base.update(overrides)
    return base


# --- node_exceedances --------------------------------------------------------


def test_exceedance_counts_only_durations_strictly_above_the_budget() -> None:
    records = [
        _record(i + 1, {"RetrieveHybrid": ms})
        for i, ms in enumerate([100.0, 200.0, 300.0, 300.0, 301.0, 450.0])
    ]
    result = node_exceedances(records, _budgets(retrieve_timeout_ms=300))
    assert result["RetrieveHybrid"]["n"] == 6
    assert result["RetrieveHybrid"]["above"] == 2  # 301 and 450, not the two 300s
    assert result["RetrieveHybrid"]["max_ms"] == 450.0
    assert result["RetrieveHybrid"]["budget_ms"] == 300
    assert result["RetrieveHybrid"]["budget_key"] == "retrieve_timeout_ms"


def test_exceedances_map_each_node_to_its_own_budget_key() -> None:
    records = [
        _record(
            1,
            {
                "ReformulateQuery": 6000.0,
                "RetrieveHybrid": 20.0,
                "ExtractGraphContext": 30.0,
                "AssemblePrompt": 40.0,
                "GenerateAnswer": 70000.0,
            },
        )
    ]
    budgets = _budgets(
        retrieve_timeout_ms=10,
        graph_node_timeout_ms=10,
        prompt_timeout_ms=10,
    )
    result = node_exceedances(records, budgets)
    assert {node: result[node]["budget_key"] for node in NODES} == {
        "ReformulateQuery": "reformulate_timeout_ms",
        "RetrieveHybrid": "retrieve_timeout_ms",
        "ExtractGraphContext": "graph_node_timeout_ms",
        "AssemblePrompt": "prompt_timeout_ms",
        "GenerateAnswer": "generation_node_timeout_ms",
    }
    assert {node: result[node]["above"] for node in NODES} == {
        "ReformulateQuery": 1,
        "RetrieveHybrid": 1,
        "ExtractGraphContext": 1,
        "AssemblePrompt": 1,
        "GenerateAnswer": 1,
    }


def test_generation_is_counted_over_successful_records_only() -> None:
    records = [
        _record(1, {"GenerateAnswer": 1000.0}),
        _record(2, {"GenerateAnswer": 2000.0}),
        # A failed generation may still carry a timing; it is not a success.
        _record(3, {"GenerateAnswer": 90000.0}, generation_failed=True),
    ]
    result = node_exceedances(records, _budgets(generation_node_timeout_ms=1500))
    assert result["GenerateAnswer"]["n"] == 2
    assert result["GenerateAnswer"]["above"] == 1
    assert result["GenerateAnswer"]["max_ms"] == 2000.0


def test_a_node_without_timings_reports_zero_observations() -> None:
    result = node_exceedances([_record(1, {"RetrieveHybrid": 5.0})], _budgets())
    assert result["AssemblePrompt"]["n"] == 0
    assert result["AssemblePrompt"]["above"] == 0
    assert result["AssemblePrompt"]["max_ms"] is None


# --- derive_option -----------------------------------------------------------


def test_rule_values_do_not_depend_on_the_inner_source() -> None:
    records = _series()
    small = derive_option(records, MEASUREMENT, (100, 200))
    large = derive_option(records, MEASUREMENT, (645, 38595))
    for key in ("retrieve_timeout_ms", "graph_node_timeout_ms", "prompt_timeout_ms"):
        assert small["rule"][key] == large["rule"][key], key
    # p95 x 1.5, ceil, nearest-rank over 20 records = the 19th value.
    assert small["rule"]["retrieve_timeout_ms"] == 1770  # ceil(1180 * 1.5)
    assert small["rule"]["graph_node_timeout_ms"] == 10200  # ceil(6800 * 1.5)
    assert small["rule"]["prompt_timeout_ms"] == 35  # ceil(23 * 1.5)
    assert small["rule"]["generation_node_timeout_ms"] == 65000
    assert small["census"] == large["census"]


def test_only_the_two_inner_keys_are_swapped() -> None:
    result = derive_option(_series(), MEASUREMENT, (645, 38595))
    assert result["inner"] == {
        "query_embedding_timeout_ms": 645,
        "graph_operation_timeout_ms": 38595,
    }
    assert result["rule"]["query_embedding_timeout_ms"] == 645
    assert result["rule"]["graph_operation_timeout_ms"] == 38595
    # The reformulate budget is not derived; it is carried from pass A's own value.
    assert result["rule"]["reformulate_timeout_ms"] == 5000
    assert result["resolved"]["reformulate_timeout_ms"] == 5000
    assert set(result["resolved"]) == set(BUDGET_KEYS)
    assert set(result["rule"]) == set(BUDGET_KEYS)


def test_nesting_raises_an_outer_budget_to_inner_sum_plus_slack() -> None:
    result = derive_option(_series(), MEASUREMENT, (645, 38595))
    # Rule values 1770 / 10200 sit below 645 + 500 and 645 + 38595 + 500.
    assert result["rule"]["retrieve_timeout_ms"] == 1770
    assert result["resolved"]["retrieve_timeout_ms"] == 1770  # 1770 > 645 + 500
    assert result["rule"]["graph_node_timeout_ms"] == 10200
    assert result["resolved"]["graph_node_timeout_ms"] == 645 + 38595 + 500
    assert result["nesting"]["has_violations"] is True
    graph_group = next(
        g
        for g in result["nesting"]["groups"]
        if g["outer_name"] == "graph_node_timeout_ms"
    )
    assert graph_group["is_invariant_driven"] is True
    assert graph_group["adjusted_outer_ms"] == 39740

    raised = derive_option(_series(), MEASUREMENT, (2000, 200))
    assert raised["rule"]["retrieve_timeout_ms"] == 1770
    assert raised["resolved"]["retrieve_timeout_ms"] == 2500  # 2000 + 500


def test_resolved_budgets_are_never_below_the_rule_values() -> None:
    result = derive_option(_series(), MEASUREMENT, (645, 38595))
    for key in BUDGET_KEYS:
        assert result["resolved"][key] >= result["rule"][key], key


def test_exceedances_are_counted_against_both_rule_and_resolved_values() -> None:
    records = _series()
    option = derive_option(records, MEASUREMENT, (645, 38595))
    rule = node_exceedances(records, option["rule"])
    resolved = node_exceedances(records, option["resolved"])
    # 20 durations 1000..1190 against a 1770 budget: nothing above.
    assert rule["RetrieveHybrid"]["above"] == 0
    assert resolved["RetrieveHybrid"]["above"] == 0
    assert rule["AssemblePrompt"]["n"] == 20


# --- options -----------------------------------------------------------------


def test_the_measurement_ceiling_option_is_ineligible_with_a_reason() -> None:
    query_embedding, graph_operation, eligible, provenance = INNER_SOURCE_OPTIONS[
        "measurement_ceiling_passA"
    ]
    assert (query_embedding, graph_operation) == (30000, 120000)
    assert eligible is False
    assert "temporary" in provenance.lower()


def test_the_two_committed_sources_are_eligible_with_their_provenance() -> None:
    config_rs = INNER_SOURCE_OPTIONS["config_rs_0633"]
    toml = INNER_SOURCE_OPTIONS["toml_33e774b"]
    assert config_rs[:3] == (645, 38595, True)
    assert "leaking" in config_rs[3]
    assert toml[:3] == (15000, 40000, True)
    assert "33e774b" in toml[3]


def test_substage_option_is_ineligible_and_carries_no_values() -> None:
    query_embedding, graph_operation, eligible, reason = INNER_SOURCE_OPTIONS[
        "substage_measured"
    ]
    assert (query_embedding, graph_operation) == (None, None)
    assert eligible is False
    assert reason


def test_substage_eligibility_needs_full_coverage_and_both_operations_timed() -> None:
    status = budget_review.substage_status
    assert status(
        measured=320, events=320, timed=("query_embedding", "graph_operation")
    )[0]
    assert not status(
        measured=320, events=236, timed=("query_embedding", "graph_operation")
    )[0]
    assert not status(measured=320, events=320, timed=("dense",))[0]
    ok, reason = status(measured=324, events=236, timed=())
    assert not ok
    assert "236" in reason and "324" in reason


# --- prompt floor table ------------------------------------------------------


def test_prompt_floor_table_counts_assemble_prompt_durations_above_each_floor() -> None:
    records = [
        _record(i + 1, {"AssemblePrompt": ms})
        for i, ms in enumerate([5.0, 10.0, 12.0, 20.0, 44.0])
    ]
    table = prompt_floor_table(records, floors=(11, 20, 44))
    assert [(row["floor_ms"], row["above"], row["n"]) for row in table] == [
        (11, 3, 5),  # 12, 20, 44
        (20, 1, 5),  # 44 only: 20 is not strictly above 20
        (44, 0, 5),
    ]


@pass_a_only
def test_pass_a_report_lists_the_assemble_prompt_durations_above_the_rule_value(
    pass_a_report: dict,
) -> None:
    prompt = pass_a_report["assemble_prompt"]
    assert prompt["rule_ms"] == 11
    assert prompt["n"] == 320
    assert len(prompt["durations_above_rule_ms"]) == 7
    assert max(prompt["durations_above_rule_ms"]) == 43.0
    floors = {row["floor_ms"]: row["above"] for row in prompt["floor_table"]}
    assert floors[11] == 7
    assert floors[43] == 0


# --- noise summary -----------------------------------------------------------


def _noise_row(
    offset: int,
    *,
    projected: float,
    slope_threshold: float,
    delta: float,
    fired: bool = False,
) -> dict[str, object]:
    return {
        "offset": offset,
        "decay_present": fired,
        "slope_prong_available": True,
        "window_prong_available": True,
        "slope_prong_fired": False,
        "window_prong_fired": False,
        "projected_growth_ms": projected,
        "materiality_threshold_ms": slope_threshold,
        "window_delta_ms": delta,
        "slope_ms_per_query": projected / 658.0,
        "slope_p_value": 0.01,
        "early_p95_ms": slope_threshold * 4.0,
        "late_p95_ms": slope_threshold * 4.0 + delta,
    }


def test_noise_summary_reports_the_nearest_misses_as_percentages() -> None:
    noise = {
        "windows": 3,
        "records": 202,
        "window": 200,
        "fired_either": 0,
        "fired_slope": 0,
        "fired_window": 0,
        "fired_fraction": 0.0,
        "unavailable": 0,
        "conclusive": True,
        "escalate": False,
        "first_window_fired": False,
        "last_window_fired": False,
        "escalation_rule": "rule text",
        "rows": [
            _noise_row(0, projected=10.0, slope_threshold=50.0, delta=-4.0),
            _noise_row(1, projected=40.0, slope_threshold=50.0, delta=30.0),
            _noise_row(2, projected=20.0, slope_threshold=40.0, delta=10.0),
        ],
    }
    summary = noise_summary(noise)
    assert summary["windows"] == 3
    assert summary["fired_fraction"] == 0.0
    assert summary["escalate"] is False
    assert summary["nearest_slope_miss"]["offset"] == 1
    assert summary["nearest_slope_miss"]["percent_of_threshold"] == pytest.approx(80.0)
    assert summary["nearest_window_miss"]["offset"] == 1
    assert summary["nearest_window_miss"]["percent_of_threshold"] == pytest.approx(60.0)
    assert summary["first_window"]["offset"] == 0
    assert summary["last_window"]["offset"] == 2
    assert "rows" not in summary


# --- pass A ------------------------------------------------------------------


@pytest.fixture(scope="module")
def pass_a_report() -> dict:
    return hazards_report(PASS_A_JOURNAL, PASS_A_MEASUREMENT, REGATE)


@pass_a_only
def test_pass_a_ceiling_option_reproduces_the_void_proposed_budgets(
    pass_a_report: dict,
) -> None:
    """The swap goes through the committed path: same inputs, same void output."""
    measurement = json.loads(PASS_A_MEASUREMENT.read_text(encoding="utf-8"))
    option = pass_a_report["options"]["measurement_ceiling_passA"]
    assert option["eligible"] is False
    for key, value in measurement["proposed_budgets"].items():
        assert option["resolved"][key] == value, key


@pass_a_only
@pytest.mark.parametrize(
    ("name", "min_retrieve", "min_graph_node"),
    [("config_rs_0633", 1145, 39740), ("toml_33e774b", 15500, 55500)],
)
def test_pass_a_eligible_options_nest_by_the_committed_rule(
    pass_a_report: dict, name: str, min_retrieve: int, min_graph_node: int
) -> None:
    option = pass_a_report["options"][name]
    resolved = option["resolved"]
    inner_qe = resolved["query_embedding_timeout_ms"]
    inner_go = resolved["graph_operation_timeout_ms"]
    assert option["eligible"] is True
    assert resolved["retrieve_timeout_ms"] >= inner_qe + 500
    assert resolved["graph_node_timeout_ms"] >= inner_qe + inner_go + 500
    assert resolved["retrieve_timeout_ms"] >= min_retrieve
    assert resolved["graph_node_timeout_ms"] >= min_graph_node


@pass_a_only
def test_pass_a_rule_values_are_identical_across_options(pass_a_report: dict) -> None:
    options = pass_a_report["options"]
    derived = [o for o in options.values() if o["rule"] is not None]
    assert len(derived) == 3
    for key in ("retrieve_timeout_ms", "graph_node_timeout_ms", "prompt_timeout_ms"):
        assert len({o["rule"][key] for o in derived}) == 1, key


@pass_a_only
def test_pass_a_counts_cover_all_320_measured_records(pass_a_report: dict) -> None:
    resolved = pass_a_report["options"]["config_rs_0633"]["exceedances_resolved"]
    assert resolved["AssemblePrompt"]["n"] == 320
    assert resolved["RetrieveHybrid"]["n"] == 320
    assert resolved["ExtractGraphContext"]["n"] == 320
    assert resolved["GenerateAnswer"]["n"] == 186
    assert pass_a_report["n_measured"] == 320


@pass_a_only
def test_pass_a_rule_output_exceedances(pass_a_report: dict) -> None:
    rule = pass_a_report["options"]["config_rs_0633"]["exceedances_rule"]
    assert rule["AssemblePrompt"]["budget_ms"] == 11
    assert rule["AssemblePrompt"]["above"] == 7
    assert rule["AssemblePrompt"]["max_ms"] == 43.0
    assert rule["RetrieveHybrid"]["max_ms"] == 403.0
    assert rule["ExtractGraphContext"]["max_ms"] == 1438.0


@pass_a_only
def test_pass_a_nesting_lifts_the_outer_budgets_clear_of_the_pass_a_maxima(
    pass_a_report: dict,
) -> None:
    for name in ("config_rs_0633", "toml_33e774b"):
        resolved = pass_a_report["options"][name]["exceedances_resolved"]
        assert resolved["RetrieveHybrid"]["above"] == 0, name
        assert resolved["ExtractGraphContext"]["above"] == 0, name


@pass_a_only
def test_pass_a_brief_figures_are_compared_with_the_rule_output(
    pass_a_report: dict,
) -> None:
    mismatch = {row["node"]: row for row in pass_a_report["brief_mismatch"]}
    assert set(mismatch) == {"RetrieveHybrid", "ExtractGraphContext", "AssemblePrompt"}
    for row in mismatch.values():
        assert row["agrees"] == (row["rule_ms"] == row["brief_rule_ms"])
    assert mismatch["RetrieveHybrid"]["brief_rule_ms"] == 294
    assert mismatch["RetrieveHybrid"]["rule_ms"] == 294
    assert mismatch["RetrieveHybrid"]["agrees"] is True


@pass_a_only
def test_pass_a_report_carries_the_noise_summary(pass_a_report: dict) -> None:
    noise = pass_a_report["noise"]
    assert noise["windows"] == 121
    assert noise["fired_either"] == 0
    assert noise["escalate"] is False
    assert "rows" not in noise


@pass_a_only
def test_pass_a_substage_option_is_ineligible_for_the_recorded_reason(
    pass_a_report: dict,
) -> None:
    option = pass_a_report["options"]["substage_measured"]
    assert option["eligible"] is False
    assert option["rule"] is None
    assert option["resolved"] is None


# --- CLI ---------------------------------------------------------------------


def _regate_variant(tmp_path: Path, **changes: object) -> Path:
    data = json.loads(REGATE.read_text(encoding="utf-8"))
    data.update(changes)
    path = tmp_path / "regate.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _cli(regate: Path, out: Path) -> int:
    return main([
        "hazards",
        "--journal",
        str(PASS_A_JOURNAL),
        "--measurement",
        str(PASS_A_MEASUREMENT),
        "--regate",
        str(regate),
        "--out",
        str(out),
    ])


@pass_a_only
@pytest.mark.parametrize(
    "changes",
    [
        {"decay_present": True},
        {"slope_prong_available": False},
        {"window_prong_available": False},
    ],
)
def test_cli_refuses_and_writes_nothing_when_the_regate_does_not_clear(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    out = tmp_path / "out" / "hazards.json"
    rc = _cli(_regate_variant(tmp_path, **changes), out)
    assert rc != 0
    assert not out.exists()
    assert not out.parent.exists()


@pass_a_only
def test_cli_refuses_an_output_under_eval_runs(tmp_path: Path) -> None:
    out = PASS_A_DIR / "hazards-should-never-exist.json"
    try:
        rc = _cli(REGATE, out)
        assert rc != 0
        assert not out.exists()
    finally:
        out.unlink(missing_ok=True)


@pass_a_only
def test_cli_refuses_to_overwrite_an_input(tmp_path: Path) -> None:
    regate_copy = tmp_path / "regate.json"
    regate_copy.write_text(REGATE.read_text(encoding="utf-8"), encoding="utf-8")
    before = regate_copy.read_text(encoding="utf-8")
    rc = _cli(regate_copy, regate_copy)
    assert rc != 0
    assert regate_copy.read_text(encoding="utf-8") == before


@pass_a_only
def test_cli_writes_the_hazards_file_for_pass_a(tmp_path: Path) -> None:
    out = tmp_path / "budget-hazards.json"
    assert _cli(REGATE, out) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["options"]["measurement_ceiling_passA"]["eligible"] is False
    assert {"config_rs_0633", "toml_33e774b"} <= set(data["options"])
    assert data["n_measured"] == 320
    assert "p95_by_node" in data
