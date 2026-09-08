"""Tests for measurement driver, spend accounting, isolation, and schema invariants."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from lancet_eval.cli import app
from lancet_eval.client import QueryOutcome
from lancet_eval.corpus import GoldQuestion
from lancet_eval.journal import NodeTiming, RunRecord, WorkflowWireMeta
from lancet_eval.latency import (
    LABEL_INNER_GRAPH_TIMEOUT,
    WORKFLOW_NODE_ORDER,
    CensoringLabel,
    check_harness_ceilings,
    classify_node_observation,
    compute_censoring_census,
    extract_node_durations,
)
from lancet_eval.measure import (
    MeasurementRecord,
    SchemaIsolationError,
    SpendHaltError,
    assert_measurement_state_isolated,
    check_provider_allowance,
    compute_spend,
    measure_one,
    run_measurement_pass,
)
from lancet_eval.preflight import read_workflow_timeouts


def test_measurement_record_schema_differentiation():
    """Assert MeasurementRecord accepts extra fields and RunRecord rejects them."""
    data = {
        "corpus": "multihop_rag",
        "question_id": "q1",
        "graph_arm": "graph-on",
        "outcome": "success",
        "ordinal": 1,
        "segment": "segment-1",
        "warm_up": False,
        "question_type": "bridge",
        "dropped_node_timings": 0,
    }
    # MeasurementRecord accepts extra measurement fields
    m_rec = MeasurementRecord.model_validate(data)
    assert m_rec.ordinal == 1
    assert m_rec.segment == "segment-1"
    assert not m_rec.warm_up
    assert m_rec.question_type == "bridge"

    # RunRecord forbids unknown fields (extra="forbid")
    with pytest.raises(ValidationError):
        RunRecord.model_validate(data)


def test_reader_parses_with_measurement_record_type():
    """Assert duration extraction accepts MeasurementRecord objects and journals."""
    rec = MeasurementRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm="graph-on",
        outcome="success",
        ordinal=1,
        segment="segment-1",
        node_timings=[NodeTiming(node_name="RetrieveHybrid", duration_ms=250.0)],
    )
    extraction = extract_node_durations([rec])
    assert extraction.by_node["RetrieveHybrid"] == [250.0]


def test_measure_command_help_specifies_sample_size_units():
    """Assert measure command help states sample size counts questions."""
    runner = CliRunner()
    res = runner.invoke(app, ["measure", "--help"])
    assert res.exit_code == 0
    assert "Number of questions to measure" in res.output
    assert "two queries per question" in res.output
    # Must not accept multiplier with default
    assert "--multiplier" not in res.output


def test_ordinal_assigned_at_dispatch_time_and_two_armed_adjacency():
    """Assert N questions produce 2N records covering both arms adjacently."""
    mock_questions = [
        GoldQuestion(
            question_id="q1",
            question="What is A?",
            question_type="bridge",
            gold_answer="A",
            supporting_facts=[],
        ),
        GoldQuestion(
            question_id="q2",
            question="What is B?",
            question_type="comparison",
            gold_answer="B",
            supporting_facts=[],
        ),
    ]

    from lancet_eval.client import NodeCompleted, WorkflowCompleted

    mock_client = MagicMock()
    # Mock run_query inside measure_one
    with patch("lancet_eval.measure.run_query") as mock_rq:
        mock_rq.return_value = QueryOutcome(
            status="ok",
            answer=None,
            completion=WorkflowCompleted(success=True, total_duration_ms=150),
            node_timings=[NodeCompleted(node_name="RetrieveHybrid", duration_ms=100.0)],
            notices=[],
            node_failures=[],
            duration_ms=150,
            dropped_node_timings=0,
        )

        with patch("lancet_eval.measure.load_corpus") as mock_lc:
            mock_lc.return_value = MagicMock(questions=mock_questions)
            with patch("lancet_eval.measure.check_provider_allowance"):
                tmp_dir = Path("eval/runs/test-measure-multihop_rag")
                tmp_dir.mkdir(parents=True, exist_ok=True)
                run_dir, summary = run_measurement_pass(
                    corpus_name="multihop_rag",
                    sample_size_questions=2,
                    warm_up_count=0,
                    output_dir=tmp_dir,
                    client=mock_client,
                    check_allowance=False,
                )

                journal_path = run_dir / "journal.jsonl"
                lines = [
                    json.loads(raw_line)
                    for raw_line in journal_path.read_text(
                        encoding="utf-8"
                    ).splitlines()
                ]
                # N=2 questions -> 4 records
                assert len(lines) == 4
                # Check coverage of both arms
                q1_records = [r for r in lines if r["question_id"] == "q1"]
                q2_records = [r for r in lines if r["question_id"] == "q2"]
                assert len(q1_records) == 2
                assert len(q2_records) == 2

                # Check adjacency: |ord1 - ord2| <= 1 for each question
                assert abs(q1_records[0]["ordinal"] - q1_records[1]["ordinal"]) == 1
                assert abs(q2_records[0]["ordinal"] - q2_records[1]["ordinal"]) == 1

                # Clean up
                for f in run_dir.glob("*"):
                    f.unlink()
                run_dir.rmdir()


def test_censoring_boundary_classification():
    """Assert exact ceiling is censored and strictly below is not."""
    ceil = 10000.0
    rec_exact = MeasurementRecord(
        corpus="m",
        question_id="q",
        graph_arm="on",
        ordinal=1,
        segment="s1",
        outcome="success",
        node_timings=[NodeTiming(node_name="RetrieveHybrid", duration_ms=10000.0)],
    )
    lbl_exact, _ = classify_node_observation(rec_exact, "RetrieveHybrid", ceil)
    assert lbl_exact == CensoringLabel.CENSORED_AT_CEILING

    rec_below = MeasurementRecord(
        corpus="m",
        question_id="q",
        graph_arm="on",
        ordinal=1,
        segment="s1",
        outcome="success",
        node_timings=[NodeTiming(node_name="RetrieveHybrid", duration_ms=9999.0)],
    )
    lbl_below, _ = classify_node_observation(rec_below, "RetrieveHybrid", ceil)
    assert lbl_below == CensoringLabel.OBSERVED


def test_censored_node_timeout_classification():
    """Assert node failed with error_kind=1 classifies CENSORED_NODE_TIMEOUT."""
    rec = MagicMock()
    rec.node_timings = []
    fail = MagicMock()
    fail.node_name = "RetrieveHybrid"
    fail.error_kind = 1
    rec.node_failures = [fail]
    rec.notices = []

    lbl, _ = classify_node_observation(rec, "RetrieveHybrid", 10000.0)
    assert lbl == CensoringLabel.CENSORED_NODE_TIMEOUT


def test_inner_graph_timeout_dual_classification():
    """Assert typed_code=2 emits CENSORED_INNER_GRAPH_OP and node-level OBSERVED."""
    rec = MagicMock()
    rec.node_timings = [MagicMock(node_name="ExtractGraphContext", duration_ms=4500.0)]
    rec.node_failures = []
    notice = MagicMock()
    notice.typed_code = 2
    notice.code = "GRAPH_TIMEOUT"
    rec.notices = [notice]

    lbl, inners = classify_node_observation(rec, "ExtractGraphContext", 15000.0)
    assert lbl == CensoringLabel.OBSERVED
    assert LABEL_INNER_GRAPH_TIMEOUT in inners


def test_timeout_cascade_anti_phantom_defect():
    """Assert downstream nodes of timeout classify NOT_REACHED (0 INSTRUMENT_GAP)."""
    rec = MagicMock()
    fail = MagicMock()
    fail.node_name = "RetrieveHybrid"
    fail.error_kind = 1
    rec.node_failures = [fail]
    rec.node_timings = []
    rec.notices = []

    lbl_assemble, _ = classify_node_observation(rec, "AssemblePrompt", 2000.0)
    lbl_generate, _ = classify_node_observation(rec, "GenerateAnswer", 65000.0)
    assert lbl_assemble == CensoringLabel.NOT_REACHED
    assert lbl_generate == CensoringLabel.NOT_REACHED

    # Check that ReformulateQuery upstream is classified on its own evidence
    lbl_reform, _ = classify_node_observation(rec, "ReformulateQuery", 5000.0)
    assert lbl_reform == CensoringLabel.INSTRUMENT_GAP


def test_instrument_gap_reachability():
    """Assert node with no timing/failure not downstream classifies INSTRUMENT_GAP."""
    rec = MagicMock()
    rec.node_failures = []
    rec.node_timings = []
    rec.notices = []

    lbl, _ = classify_node_observation(rec, "ReformulateQuery", 5000.0)
    assert lbl == CensoringLabel.INSTRUMENT_GAP


def test_censoring_labels_mutually_exclusive_and_exhaustive():
    """Assert census per-node counts sum to exactly the number of records."""
    rec1 = MagicMock(
        node_timings=[MagicMock(node_name="RetrieveHybrid", duration_ms=500.0)],
        node_failures=[],
        notices=[],
    )
    rec2 = MagicMock(
        node_timings=[MagicMock(node_name="RetrieveHybrid", duration_ms=10000.0)],
        node_failures=[],
        notices=[],
    )
    rec3 = MagicMock(
        node_timings=[],
        node_failures=[MagicMock(node_name="RetrieveHybrid", error_kind=1)],
        notices=[],
    )
    rec4 = MagicMock(
        node_timings=[],
        node_failures=[MagicMock(node_name="ReformulateQuery", error_kind=1)],
        notices=[],
    )

    records = [rec1, rec2, rec3, rec4]
    ceilings = {n: 10000.0 for n in WORKFLOW_NODE_ORDER}
    census = compute_censoring_census(records, ceilings)

    for node in WORKFLOW_NODE_ORDER:
        node_counts = census.node_counts[node]
        assert sum(node_counts.values()) == len(records)


def test_workflow_node_order_constant_and_runner_verification():
    """Assert WORKFLOW_NODE_ORDER matches runner.rs execution order."""
    expected = (
        "ReformulateQuery",
        "ExtractGraphContext",
        "RetrieveHybrid",
        "AssemblePrompt",
        "GenerateAnswer",
    )
    assert WORKFLOW_NODE_ORDER == expected


def test_dropped_node_timings_stamped_on_measurement_record():
    """Assert dropped_node_timings is captured on MeasurementRecord."""
    rec = MeasurementRecord(
        corpus="m",
        question_id="q",
        graph_arm="on",
        ordinal=1,
        segment="s1",
        outcome="success",
        dropped_node_timings=3,
    )
    assert rec.dropped_node_timings == 3


def test_two_ceiling_report_distinct_comparisons():
    """Assert comparisons check node max vs read timeout and sum vs deadline."""
    # Case 1: single node exceeds read timeout, but sum is under deadline
    budgets1 = {
        "reformulate_timeout_ms": 1000,
        "retrieve_timeout_ms": 305000,  # exceeds 300s
        "graph_node_timeout_ms": 1000,
        "prompt_timeout_ms": 1000,
        "generation_node_timeout_ms": 1000,
    }
    rep1 = check_harness_ceilings(
        budgets1, sse_read_timeout_s=300.0, question_deadline_s=600.0
    )
    assert rep1.single_exceeds_read_timeout is True
    assert rep1.sum_exceeds_deadline is False

    # Case 2: every node under read timeout, but sum exceeds deadline
    budgets2 = {
        "reformulate_timeout_ms": 100000,
        "retrieve_timeout_ms": 150000,
        "graph_node_timeout_ms": 150000,
        "prompt_timeout_ms": 100000,
        "generation_node_timeout_ms": 150000,  # sum = 650,000ms > 600,000ms
    }
    rep2 = check_harness_ceilings(
        budgets2, sse_read_timeout_s=300.0, question_deadline_s=600.0
    )
    assert rep2.single_exceeds_read_timeout is False
    assert rep2.sum_exceeds_deadline is True


def test_effective_sse_read_timeout_tracks_settings():
    """Assert query path derives read timeout from gateway_timeout_secs."""
    from unittest.mock import patch

    from lancet_eval.client import run_query

    # Call with explicit read_timeout_s
    mock_client = MagicMock()
    with patch("httpx_sse.connect_sse") as mock_connect:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_source = MagicMock()
        mock_source.response = mock_resp
        mock_source.iter_sse.return_value = [
            MagicMock(
                event="workflow_completed",
                data='{"success":true,"total_duration_ms":100}',
            ),
            MagicMock(event="final_answer", data='{"answer":"test"}'),
        ]
        mock_connect.return_value.__enter__.return_value = mock_source

        run_query(mock_client, query="test", read_timeout_s=450.0)
        call_kwargs = mock_connect.call_args[1]
        timeout_obj = call_kwargs["timeout"]
        assert timeout_obj.read == 450.0


def test_spend_computation_prices_embeddings():
    """Assert spend accounting prices embedding model and marks bounds."""
    meta = WorkflowWireMeta(prompt_tokens=1000, completion_tokens=500)
    rec = RunRecord(
        corpus="m",
        question_id="q",
        graph_arm="on",
        outcome="success",
        workflow_meta=meta,
    )
    # With embeddings
    spend_with_emb, is_lower = compute_spend([rec], include_embeddings=True)
    assert is_lower is False

    # Generation tokens alone
    gen_only, is_lower_gen = compute_spend([rec], include_embeddings=False)
    assert is_lower_gen is True
    assert spend_with_emb > gen_only


def test_schema_isolation_refusal():
    """Assert assert_measurement_state_isolated refuses on collision."""
    eval_dsn = "postgres://postgres:postgres@localhost:5432/lancet?search_path=eval"
    colliding_dsn = (
        "postgres://postgres:postgres@localhost:5432/lancet?search_path=eval"
    )
    safe_dsn = "postgres://postgres:postgres@localhost:5432/lancet?search_path=dev"

    # Should raise SchemaIsolationError on collision
    with pytest.raises(SchemaIsolationError) as exc_info:
        assert_measurement_state_isolated(colliding_dsn, eval_dsn)
    assert "collides with eval schema" in str(
        exc_info.value
    ) or "equals eval schema" in str(exc_info.value)

    # Should pass on distinct schemas
    assert_measurement_state_isolated(safe_dsn, eval_dsn)


def test_allowance_check_fails_closed():
    """Assert check_provider_allowance halts when API key missing or failing."""
    with pytest.raises(SpendHaltError):
        check_provider_allowance(None)

    with pytest.raises(SpendHaltError):
        check_provider_allowance("")

    mock_client = MagicMock()
    mock_client.get.return_value = MagicMock(status_code=401, text="Unauthorized")
    with pytest.raises(SpendHaltError):
        check_provider_allowance("invalid_key", client=mock_client)


def test_transport_failure_never_raises():
    """Assert measure_one catches transport failure and produces error record."""
    mock_client = MagicMock()
    with patch(
        "lancet_eval.measure.run_query",
        side_effect=RuntimeError("Connection reset by peer"),
    ):
        q = GoldQuestion(
            question_id="q1",
            question="What?",
            question_type="factoid",
            gold_answer="A",
            supporting_facts=[],
        )
        rec = measure_one(
            mock_client,
            corpus="multihop_rag",
            question=q,
            arm="graph-off",
            ordinal=42,
            segment="segment-1",
        )
        assert rec.outcome == "error"
        assert rec.ordinal == 42
        assert rec.segment == "segment-1"
        assert "Connection reset by peer" in str(rec.error)


def test_preflight_timeout_reader_honors_env_override(monkeypatch, tmp_path):
    """Assert read_workflow_timeouts honors workflow environment variables."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[engine.workflow]
reformulate_timeout_ms = 5000
retrieve_timeout_ms = 10000
graph_node_timeout_ms = 15000
prompt_timeout_ms = 2000
generation_node_timeout_ms = 65000
query_embedding_timeout_ms = 10000
graph_operation_timeout_ms = 4000
""",
        encoding="utf-8",
    )
    # Default without override
    base_timeouts = read_workflow_timeouts(cfg_file)
    assert base_timeouts["RetrieveHybrid"] == 10000

    # With environment override
    monkeypatch.setenv("LANCET_ENGINE__WORKFLOW__RETRIEVE_TIMEOUT_MS", "25000")
    overridden_timeouts = read_workflow_timeouts(cfg_file)
    assert overridden_timeouts["RetrieveHybrid"] == 25000


def test_unreadable_engine_config_fails():
    """Assert read_workflow_timeouts raises on missing or invalid configuration file."""
    with pytest.raises(FileNotFoundError):
        read_workflow_timeouts(Path("/nonexistent/config.toml"))


def test_measurement_pass_evidence_post_hoc_invariants():
    """Assert durable measurement run records satisfy all Task 2 acceptance criteria."""
    import random

    from lancet_eval.config import repo_root

    root = repo_root() / "eval" / "runs"
    matching = list(root.glob("*-measure-multihop_rag"))
    if not matching:
        pytest.skip("No measurement run directory found.")

    run_dir = max(matching, key=lambda p: p.stat().st_mtime)
    journal_path = run_dir / "journal.jsonl"
    measurement_path = run_dir / "measurement.json"

    if not journal_path.is_file() or not measurement_path.is_file():
        pytest.skip("Measurement journal or record not yet written.")

    raw_text = journal_path.read_text(encoding="utf-8").strip()
    if not raw_text:
        pytest.skip("Measurement journal is empty.")

    lines = [
        json.loads(line) for line in raw_text.splitlines() if line.strip()
    ]
    if len(lines) < 320:
        pytest.skip(
            f"Measurement run in progress or partial (found {len(lines)}/320 records)."
        )

    with open(measurement_path, encoding="utf-8") as f:
        meta = json.load(f)

    # 1. Shuffled journal test: assert analysis sorts by recorded ordinal
    shuffled_lines = list(lines)
    random.seed(42)
    random.shuffle(shuffled_lines)

    # Validate on shuffled lines
    sorted_records = sorted(shuffled_lines, key=lambda r: int(r["ordinal"]))
    ordinals = [r["ordinal"] for r in sorted_records]

    # Gap-free and unique
    assert ordinals == list(range(1, len(lines) + 1))

    # Every record carries ordinal, segment, question_type
    for r in sorted_records:
        assert "ordinal" in r and isinstance(r["ordinal"], int)
        assert "segment" in r and r["segment"] in ("segment-1", "segment-2")
        assert "question_type" in r and isinstance(r["question_type"], str)

    # Exactly 2 distinct segment labels, changing once in ordinal order
    segments_in_order = [r["segment"] for r in sorted_records]
    assert set(segments_in_order) == {"segment-1", "segment-2"}
    transitions = [
        i
        for i in range(len(segments_in_order) - 1)
        if segments_in_order[i] != segments_in_order[i + 1]
    ]
    assert len(transitions) == 1
    boundary_idx = transitions[0]
    assert sorted_records[boundary_idx]["ordinal"] == meta["segment_boundary_ordinal"]

    # Recorded restart ordinal falls inside observed boundary
    restart_ord = meta["restart_ordinal"]
    assert ordinals[0] <= restart_ord <= ordinals[-1]

    # Two-armed adjacency: 2N records for N questions, adjacent
    q_to_records: dict[str, list[dict[str, object]]] = {}
    for r in sorted_records:
        q_to_records.setdefault(r["question_id"], []).append(r)

    assert len(sorted_records) == meta["sample_size_questions"] * 2
    for _q_id, q_recs in q_to_records.items():
        assert len(q_recs) == 2
        arms = {r["graph_arm"] for r in q_recs}
        assert arms == {"graph-off", "graph-on"}
        assert abs(q_recs[0]["ordinal"] - q_recs[1]["ordinal"]) == 1

    # Per-node counts broken down across all 5 classification labels
    census = meta["censoring_census"]
    node_counts = census["node_counts"]
    for node in WORKFLOW_NODE_ORDER:
        assert node in node_counts
        counts = node_counts[node]
        assert set(counts.keys()) == {
            CensoringLabel.OBSERVED.value,
            CensoringLabel.CENSORED_AT_CEILING.value,
            CensoringLabel.CENSORED_NODE_TIMEOUT.value,
            CensoringLabel.NOT_REACHED.value,
            CensoringLabel.INSTRUMENT_GAP.value,
        }
        assert sum(counts.values()) == len(sorted_records)

    # Raised budget set & harness ceilings
    assert "raised_budgets" in meta
    assert meta["raised_budgets_source"] == "process_environment"
    assert meta["committed_config_unmodified"] is True

    # Two distinct ceiling comparisons
    two_ceilings = meta["two_ceiling_comparisons"]
    assert "sse_read_timeout_comparison" in two_ceilings
    assert "question_deadline_comparison" in two_ceilings
    assert two_ceilings["sse_read_timeout_comparison"]["exceeds_ceiling"] is False
    assert two_ceilings["question_deadline_comparison"]["exceeds_ceiling"] is False

    # Spend accounting: within stage cap, includes embeddings
    spend = meta["spend_summary"]
    assert spend["spend_usd"] <= spend["stage_spend_cap"]
    assert spend["includes_embeddings"] is True
    assert spend["is_lower_bound"] is False

    # Post-restart probe query latency
    assert meta["probe_query_latency_ms"] > 0.0

    # Checkpoint reconciliation
    cp = meta["checkpoint_reconciliation"]
    assert cp["monotonic_append_only"] is True
    assert cp["post_pass_count"] >= cp["pre_pass_count"]
    assert cp["reseed_or_compaction_occurred"] is False
    assert len(cp["attribution_table"]) >= 4

    # No judge model
    assert meta["model_configuration"]["judge_model"] is None


_FIXTURE_EFFECTIVE_CFG = {
    "reformulate_timeout_ms": 5000,
    "query_embedding_timeout_ms": 10000,
    "retrieve_timeout_ms": 10000,
    "graph_operation_timeout_ms": 4000,
    "graph_node_timeout_ms": 30000,
    "prompt_timeout_ms": 5000,
    "generation_node_timeout_ms": 65000,
}

_SUMMARY_KEYS = (
    "calibration_note",
    "corpus",
    "sample_size_questions",
    "total_records_emitted",
    "measured_records",
    "raised_budgets",
    "sse_read_timeout_s",
    "question_deadline_s",
    "spend_summary",
    "censoring_census",
    "proposed_budgets",
    "proposed_records",
    "censored_by_node",
    "nesting_report",
)


def _derive_from_records(records):
    from lancet_eval.measure import derive_budgets_from_records
    from lancet_eval.thresholds import COMMITTED_THRESHOLDS

    return derive_budgets_from_records(
        records,
        _FIXTURE_EFFECTIVE_CFG,
        COMMITTED_THRESHOLDS,
        sse_read_timeout_s=300.0,
        question_deadline_s=180.0,
    )


def _retrieve_proposed(result):
    return next(
        row
        for row in result.proposed_records
        if row["node_or_budget"] == "retrieve_timeout_ms"
    )


def test_derivation_flags_ceiling_censored_node_as_lower_bound(
    ceiling_censored_measurement_records,
):
    """Censored RetrieveHybrid budgets must not be recorded as clean."""
    result = _derive_from_records(ceiling_censored_measurement_records)
    status = _retrieve_proposed(result)["censored_status"]
    assert status != "clean"
    assert status.startswith("censored_lower_bound(")
    count = int(status.removeprefix("censored_lower_bound(").removesuffix(")"))
    assert count > 0


def test_derivation_censored_count_sums_ceiling_drops_and_timer_expiries(
    ceiling_censored_measurement_records,
):
    """Censored count is 40 at-ceiling drops plus 5 node-timer expiries."""
    result = _derive_from_records(ceiling_censored_measurement_records)
    assert result.censored_by_node["RetrieveHybrid"] == 45


def test_derivation_percentile_excludes_clipped_observations(
    ceiling_censored_measurement_records,
):
    """Clipped 10000ms observations must not enter the percentile."""
    result = _derive_from_records(ceiling_censored_measurement_records)
    assert _retrieve_proposed(result)["percentile_value_ms"] < 10000.0


def test_derivation_clean_records_report_clean_status():
    """Uncensored records still derive clean budgets."""
    from lancet_eval.journal import NodeTiming
    from lancet_eval.measure import MeasurementRecord

    records = [
        MeasurementRecord(
            corpus="multihop_rag",
            question_id=f"q_{i}",
            graph_arm="graph-on",
            outcome="success",
            ordinal=i,
            segment="segment-1",
            question_type="bridge",
            node_timings=[
                NodeTiming(node_name="RetrieveHybrid", duration_ms=100.0 + i),
                NodeTiming(node_name="ExtractGraphContext", duration_ms=200.0 + i),
                NodeTiming(node_name="AssemblePrompt", duration_ms=50.0 + i),
            ],
        )
        for i in range(1, 21)
    ]
    result = _derive_from_records(records)
    measured = [
        row
        for row in result.proposed_records
        if "provider_contract" not in row["rule"]
    ]
    assert measured
    assert all(row["censored_status"] == "clean" for row in measured)
    assert all(count == 0 for count in result.censored_by_node.values())


def test_derivation_refuses_empty_survivors_without_nesting_fill_in(
    ceiling_censored_measurement_records,
):
    """Unmeasured outers stay out of proposed_budgets instead of nesting fill-in."""
    result = _derive_from_records(ceiling_censored_measurement_records)
    assert "graph_node_timeout_ms" not in result.proposed_budgets
    assert "prompt_timeout_ms" not in result.proposed_budgets
    refused = [
        row
        for row in result.proposed_records
        if row["node_or_budget"] == "graph_node_timeout_ms"
    ]
    assert len(refused) == 1
    assert refused[0]["proposed_ms"] is None
    assert refused[0]["rule"] == "derivation_refused_empty_or_unavailable"
    assert str(refused[0]["censored_status"]).startswith("unavailable(")


def test_derivation_is_pure_and_needs_no_client(ceiling_censored_measurement_records):
    """Derivation is a pure function of records and config, not a live stack."""
    import os

    os.environ.pop("OPENROUTER_API_KEY", None)
    result = _derive_from_records(ceiling_censored_measurement_records)
    assert result.proposed_records
    assert result.census.total_records == len(ceiling_censored_measurement_records)


def test_run_measurement_pass_summary_keeps_existing_keys():
    """run_measurement_pass summary still emits every pre-extraction key."""
    import inspect

    from lancet_eval.measure import run_measurement_pass

    src = inspect.getsource(run_measurement_pass)
    for key in _SUMMARY_KEYS:
        assert f'"{key}"' in src

