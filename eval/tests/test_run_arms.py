"""Tests for two-armed runner, request body invariants, and resume."""

import json
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from lancet_eval.corpus import GoldQuestion, load_corpus_config
from lancet_eval.journal import load_done
from lancet_eval.run import GRAPH_ARMS, drive, drive_one


def test_arm_vocabulary_consistency() -> None:
    """Proves arm labels agree across corpus config, GRAPH_ARMS, and cli."""
    config_mhr = load_corpus_config("multihop_rag")
    config_grb = load_corpus_config("graphrag_bench")

    assert config_mhr.arms == ["graph-on", "graph-off"]
    assert config_grb.arms == ["graph-on", "graph-off"]
    assert list(GRAPH_ARMS.keys()) == ["graph-on", "graph-off"]
    assert GRAPH_ARMS["graph-on"] is False
    assert GRAPH_ARMS["graph-off"] is True


def test_request_body_polarity_and_model_only_absence(httpx_mock: HTTPXMock) -> None:
    """Proves graph-off sends disable_graph_context: True, graph-on omits key."""
    def sse_response(request: httpx.Request) -> httpx.Response:
        data = (
            'event: final_answer\n'
            'data: {"answer": "Paris", "snapshot": {"index_generation": "gen1"}}\n\n'
            'event: workflow_completed\n'
            'data: {"success": true, "duration_ms": 100}\n\n'
        )
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            text=data,
        )

    httpx_mock.add_callback(sse_response, is_reusable=True)

    client = httpx.Client(base_url="http://testserver")
    q = GoldQuestion(question_id="q1", question="What is Paris?", gold_facts=["Paris"])

    # Drive graph-on
    rec_on = drive_one(client, corpus="multihop_rag", question=q, arm="graph-on")
    assert rec_on.outcome == "success"

    # Drive graph-off
    rec_off = drive_one(client, corpus="multihop_rag", question=q, arm="graph-off")
    assert rec_off.outcome == "success"

    requests = httpx_mock.get_requests()
    assert len(requests) == 2

    req_on_body = json.loads(requests[0].read().decode("utf-8"))
    req_off_body = json.loads(requests[1].read().decode("utf-8"))

    assert "disable_graph_context" not in req_on_body
    assert "allow_model_only" not in req_on_body

    assert req_off_body.get("disable_graph_context") is True
    assert "allow_model_only" not in req_off_body


def test_drive_one_catches_all_exceptions_without_raising(
    httpx_mock: HTTPXMock,
) -> None:
    """Proves drive_one converts transport errors into durable error records."""
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    httpx_mock.add_callback(timeout_handler)

    client = httpx.Client(base_url="http://testserver")
    q = GoldQuestion(question_id="q1", question="What is Paris?", gold_facts=["Paris"])

    rec = drive_one(client, corpus="multihop_rag", question=q, arm="graph-on")
    assert rec.outcome == "error"
    assert rec.error_type == "ReadTimeout"
    assert "read timed out" in (rec.error or "")


def test_drive_sibling_isolation_on_failure(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves one failing question does not discard sibling completed units."""
    call_count = 0

    def alternating_response(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ReadTimeout("timed out")
        data = (
            'event: final_answer\n'
            'data: {"answer": "Paris", "snapshot": {"index_generation": "gen1"}}\n\n'
            'event: workflow_completed\n'
            'data: {"success": true, "duration_ms": 100}\n\n'
        )
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            text=data,
        )

    httpx_mock.add_callback(alternating_response, is_reusable=True)

    client = httpx.Client(base_url="http://testserver")
    j_path = tmp_path / "journal.jsonl"

    count = drive(
        corpus="graphrag_bench",
        journal_path=j_path,
        limit=2,
        client=client,
    )
    # 2 questions x 2 arms = 4 work units
    assert count == 4

    done = load_done(j_path)
    assert len(done) == 4


def test_drive_resume_issues_zero_requests_when_done(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves drive --resume against a complete journal makes no HTTP calls."""
    def sse_response(request: httpx.Request) -> httpx.Response:
        data = (
            'event: final_answer\n'
            'data: {"answer": "Paris", "snapshot": {"index_generation": "gen1"}}\n\n'
            'event: workflow_completed\n'
            'data: {"success": true, "duration_ms": 100}\n\n'
        )
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            text=data,
        )

    httpx_mock.add_callback(sse_response, is_reusable=True)

    client = httpx.Client(base_url="http://testserver")
    j_path = tmp_path / "journal.jsonl"

    # First run: 1 question x 2 arms = 2 work units
    count1 = drive(
        corpus="graphrag_bench",
        journal_path=j_path,
        limit=1,
        client=client,
    )
    assert count1 == 2
    assert len(httpx_mock.get_requests()) == 2

    # Second run with resume=True
    count2 = drive(
        corpus="graphrag_bench",
        journal_path=j_path,
        limit=1,
        resume=True,
        client=client,
    )
    assert count2 == 0
    # Zero additional HTTP requests issued
    assert len(httpx_mock.get_requests()) == 2


def test_resolve_run_dir_reuses_newest_dated_dir_on_resume(tmp_path: Path) -> None:
    """Proves resolve_run_dir reuses latest dated dir on resume."""
    from datetime import UTC, datetime

    from lancet_eval.cli import resolve_run_dir

    # Create test directories in tmp_path
    dir_old = tmp_path / "2026-08-28-multihop_rag"
    dir_new = tmp_path / "2026-08-30-multihop_rag"
    dir_decoy = tmp_path / "zzz-multihop_rag"
    dir_other = tmp_path / "2026-08-31-other_corpus"

    dir_old.mkdir()
    dir_new.mkdir()
    dir_decoy.mkdir()
    dir_other.mkdir()

    # On resume=True, pick newest dated directory and ignore non-dated decoy
    resumed = resolve_run_dir("multihop_rag", resume=True, runs_root=tmp_path)
    assert resumed == dir_new
    assert "multihop_rag" in resumed.name
    assert "_" in resumed.name

    # On resume=False, should return today's dated directory
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    fresh = resolve_run_dir("multihop_rag", resume=False, runs_root=tmp_path)
    assert fresh == tmp_path / f"{today}-multihop_rag"


def test_drive_passes_configured_deadline_to_run_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proves configured deadline reaches run_query for both arms."""
    from lancet_eval.client import QueryOutcome, RagAnswer, WorkflowCompleted
    from lancet_eval.config import EvalSettings

    deadlines_seen: list[float] = []

    def mock_run_query(
        client: httpx.Client,
        *,
        query: str,
        deadline_s: float = 600.0,
        **kwargs: object,
    ) -> QueryOutcome:
        deadlines_seen.append(deadline_s)
        return QueryOutcome(
            status="ok",
            answer=RagAnswer(answer="ans"),
            completion=WorkflowCompleted(success=True),
        )

    monkeypatch.setattr("lancet_eval.run.run_query", mock_run_query)

    settings = EvalSettings(
        question_deadline_secs=456.7,
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
    )

    client = httpx.Client(base_url="http://testserver")
    drive(
        corpus="graphrag_bench",
        journal_path=tmp_path / "journal.jsonl",
        limit=1,
        settings=settings,
        client=client,
    )

    # 1 question x 2 arms = 2 calls
    assert len(deadlines_seen) == 2
    assert deadlines_seen == [456.7, 456.7]


def test_run_command_loads_settings_and_forwards_to_drive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proves CLI run command loads TOML settings and forwards them to drive."""
    from typer.testing import CliRunner

    from lancet_eval.cli import app
    from lancet_eval.config import EvalSettings

    runner = CliRunner()

    eval_dir = tmp_path / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    config_file = eval_dir / "config.toml"
    config_file.write_text('question_deadline_secs = 789.0\n', encoding="utf-8")

    monkeypatch.setattr("lancet_eval.config.repo_root", lambda: tmp_path)
    monkeypatch.setattr("lancet_eval.cli.repo_root", lambda: tmp_path)

    captured_kwargs: dict[str, object] = {}

    def mock_drive(*args: object, **kwargs: object) -> int:
        captured_kwargs.update(kwargs)
        return 0

    monkeypatch.setattr("lancet_eval.run.drive", mock_drive)

    res = runner.invoke(
        app,
        ["run", "--corpus", "multihop_rag", "--out", str(tmp_path / "journal.jsonl")],
    )
    assert res.exit_code == 0
    assert "settings" in captured_kwargs
    forwarded_settings = captured_kwargs["settings"]
    assert isinstance(forwarded_settings, EvalSettings)
    assert forwarded_settings.question_deadline_secs == 789.0


