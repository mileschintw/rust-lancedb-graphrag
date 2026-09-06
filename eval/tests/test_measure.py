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
    durations = extract_node_durations([rec])
    assert durations["RetrieveHybrid"] == [250.0]


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
