"""Tests for two-armed runner, request body invariants, and resume."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from lancet_eval.corpus import GoldQuestion, load_corpus_config
from lancet_eval.identity import IdentityGateError
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


def test_unknown_arm_raises_value_error() -> None:
    """Proves unrecognised arm raises ValueError naming the arm and valid keys (WR-01)."""
    client = httpx.Client(base_url="http://testserver")
    q = GoldQuestion(question_id="q1", question="What is Paris?", gold_facts=["Paris"])
    with pytest.raises(ValueError, match="Unknown arm 'unknown-arm'"):
        drive_one(client, corpus="multihop_rag", question=q, arm="unknown-arm")


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
        stage_spend_cap=10.0,
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
        stage_spend_cap=10.0,
        limit=1,
        client=client,
    )
    assert count1 == 2
    assert len(httpx_mock.get_requests()) == 2

    # Second run with resume=True
    count2 = drive(
        corpus="graphrag_bench",
        journal_path=j_path,
        stage_spend_cap=10.0,
        limit=1,
        resume=True,
        client=client,
    )
    assert count2 == 0
    # Zero additional HTTP requests issued
    assert len(httpx_mock.get_requests()) == 2


def test_drive_raises_identity_gate_error_before_journal_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """drive() raises IdentityGateError before the journal header is created or read
    when the identity report fails, and the journal path does not exist afterwards."""
    import lancet_eval.identity as identity_mod

    monkeypatch.setattr(
        identity_mod,
        "list_lancedb_document_ids",
        lambda path: {
            "documents": ["extra-doc-id"],
            "nodes": ["extra-doc-id"],
            "edges": [],
            "entity_edges": [],
            "staged_documents_v2_rows": 0,
        },
    )

    client = httpx.Client(base_url="http://testserver")
    j_path = tmp_path / "journal.jsonl"

    with pytest.raises(IdentityGateError):
        drive(
            corpus="graphrag_bench",
            journal_path=j_path,
            stage_spend_cap=10.0,
            limit=1,
            client=client,
        )

    assert not j_path.exists()


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
        stage_spend_cap=10.0,
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
        ["run", "--corpus", "multihop_rag", "--stage-cap", "2.0", "--out", str(tmp_path / "journal.jsonl")],
    )
    assert res.exit_code == 0
    assert "settings" in captured_kwargs
    forwarded_settings = captured_kwargs["settings"]
    assert isinstance(forwarded_settings, EvalSettings)
    assert forwarded_settings.question_deadline_secs == 789.0
    assert captured_kwargs.get("stage_spend_cap") == 2.0




# --- 06.3.4.1-33 Task 1: every superseded attempt is journaled (CR-03, D-67) ---

_SSE_ANSWER_OK = (
    "event: final_answer\n"
    'data: {"answer": "Paris", "snapshot": {"index_generation": "gen1"}}\n\n'
    "event: workflow_completed\n"
    'data: {"success": true, "duration_ms": 100}\n\n'
)
_SSE_ANSWER_EMPTY = (
    "event: final_answer\n"
    'data: {"answer": ""}\n\n'
    "event: workflow_completed\n"
    'data: {"success": true, "duration_ms": 40}\n\n'
)
_SSE_D69_REJECTION = (
    "event: node_failed\n"
    'data: {"node_name": "GenerateAnswer", "error_kind": 3, '
    "\"error_message\": \"answer basis 'mixed' requires at least one cited evidence ID\", "
    '"retryable": false}\n\n'
    "event: workflow_completed\n"
    'data: {"success": false, "duration_ms": 55, "error_kind": 3, '
    '"error_message": "generation failed", '
    '"metadata": {"prompt_tokens": 700, "completion_tokens": 30}}\n\n'
)


def _sse(body: str) -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            text=body,
        )

    return respond


def _read_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("read timed out")


def _register(
    httpx_mock: HTTPXMock, *callbacks: Callable[[httpx.Request], httpx.Response]
) -> None:
    """Register one non-reusable callback per request, matched in dispatch order."""
    for cb in callbacks:
        httpx_mock.add_callback(cb)


@pytest.fixture
def no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lancet_eval.run.time.sleep", lambda _s: None)


def _q() -> GoldQuestion:
    return GoldQuestion(question_id="q1", question="What is Paris?", gold_facts=["Paris"])


def test_retried_timeout_stays_on_the_record_as_a_prior_attempt(
    httpx_mock: HTTPXMock, no_retry_sleep: None
) -> None:
    """CR-03: a timeout that succeeds on retry is journaled, not erased."""
    _register(httpx_mock, _read_timeout, _sse(_SSE_ANSWER_OK))
    client = httpx.Client(base_url="http://testserver")

    rec = drive_one(
        client, corpus="multihop_rag", question=_q(), arm="graph-on", max_retries=1
    )

    assert rec.outcome == "success"
    assert len(rec.prior_attempts) == 1
    first = rec.prior_attempts[0]
    assert first.attempt == 1
    assert first.outcome == "error"
    assert first.error_type == "ReadTimeout"
    assert "read timed out" in (first.error or "")
    assert len(httpx_mock.get_requests()) == 2


def test_first_attempt_view_classifies_like_a_single_attempt_run(
    httpx_mock: HTTPXMock, no_retry_sleep: None
) -> None:
    """The retried record's first attempt reads as timeout, the class max_retries=0 gets."""
    from lancet_eval.diagnostic import classify_record
    from lancet_eval.journal import first_attempt_view

    client = httpx.Client(base_url="http://testserver")

    _register(httpx_mock, _read_timeout)
    single = drive_one(
        client, corpus="multihop_rag", question=_q(), arm="graph-on", max_retries=0
    )
    assert single.outcome == "error"
    assert single.prior_attempts == []

    _register(httpx_mock, _read_timeout, _sse(_SSE_ANSWER_OK))
    retried = drive_one(
        client, corpus="multihop_rag", question=_q(), arm="graph-on", max_retries=1
    )

    assert classify_record(single) == "timeout"
    assert classify_record(retried) is None  # the final attempt succeeded
    assert classify_record(first_attempt_view(retried)) == "timeout"
    assert classify_record(first_attempt_view(retried)) == classify_record(single)


def test_two_failures_then_success_keep_two_prior_attempts_in_order(
    httpx_mock: HTTPXMock, no_retry_sleep: None
) -> None:
    _register(httpx_mock, _read_timeout, _sse(_SSE_D69_REJECTION), _sse(_SSE_ANSWER_OK))
    client = httpx.Client(base_url="http://testserver")

    rec = drive_one(
        client, corpus="multihop_rag", question=_q(), arm="graph-on", max_retries=2
    )

    assert rec.outcome == "success"
    assert [a.attempt for a in rec.prior_attempts] == [1, 2]
    assert rec.prior_attempts[0].error_type == "ReadTimeout"
    second = rec.prior_attempts[1]
    assert second.outcome == "error"
    assert [f.node_name for f in second.node_failures] == ["GenerateAnswer"]
    assert second.workflow_meta is not None
    assert second.workflow_meta.prompt_tokens == 700
    assert second.workflow_meta.completion_tokens == 30


def test_d69_rejection_attempt_classifies_after_the_retry_succeeds(
    httpx_mock: HTTPXMock, no_retry_sleep: None
) -> None:
    from lancet_eval.diagnostic import classify_record
    from lancet_eval.journal import first_attempt_view

    _register(httpx_mock, _sse(_SSE_D69_REJECTION), _sse(_SSE_ANSWER_OK))
    client = httpx.Client(base_url="http://testserver")

    rec = drive_one(
        client, corpus="multihop_rag", question=_q(), arm="graph-on", max_retries=1
    )

    assert rec.outcome == "success"
    assert classify_record(first_attempt_view(rec)) == "citation_basis_mixed"


def test_empty_answer_success_that_is_retried_is_kept_as_a_prior_attempt(
    httpx_mock: HTTPXMock, no_retry_sleep: None
) -> None:
    _register(httpx_mock, _sse(_SSE_ANSWER_EMPTY), _sse(_SSE_ANSWER_OK))
    client = httpx.Client(base_url="http://testserver")

    rec = drive_one(
        client, corpus="multihop_rag", question=_q(), arm="graph-on", max_retries=1
    )

    assert rec.answer == "Paris"
    assert len(rec.prior_attempts) == 1
    assert rec.prior_attempts[0].outcome == "success"
    assert rec.prior_attempts[0].answer_chars == 0


def test_exhausted_retries_keep_every_earlier_attempt_on_the_final_error_record(
    httpx_mock: HTTPXMock, no_retry_sleep: None
) -> None:
    _register(httpx_mock, _read_timeout, _read_timeout, _read_timeout)
    client = httpx.Client(base_url="http://testserver")

    rec = drive_one(
        client, corpus="multihop_rag", question=_q(), arm="graph-on", max_retries=2
    )

    assert rec.outcome == "error"
    assert rec.error_type == "ReadTimeout"
    assert [a.attempt for a in rec.prior_attempts] == [1, 2]


def test_first_attempt_view_returns_the_record_itself_when_it_ran_once() -> None:
    from lancet_eval.journal import RunRecord, first_attempt_view

    rec = RunRecord(corpus="c", question_id="q", graph_arm="graph-on", outcome="success")
    assert first_attempt_view(rec) is rec


def test_drive_journals_prior_attempts_and_they_survive_the_round_trip(
    httpx_mock: HTTPXMock, tmp_path: Path, no_retry_sleep: None
) -> None:
    """End to end: stub gateway, drive(max_retries=1), journal, load_records."""
    from lancet_eval.journal import load_records

    # 1 question x 2 arms, workers=1: unit 1 times out then answers, unit 2 answers.
    _register(
        httpx_mock, _read_timeout, _sse(_SSE_ANSWER_OK), _sse(_SSE_ANSWER_OK)
    )
    client = httpx.Client(base_url="http://testserver")
    j_path = tmp_path / "journal.jsonl"

    count = drive(
        corpus="graphrag_bench",
        journal_path=j_path,
        stage_spend_cap=10.0,
        limit=1,
        workers=1,
        max_retries=1,
        client=client,
    )

    assert count == 2
    records = load_records(j_path)
    assert len(records) == 2
    assert records[0].outcome == "success"
    assert len(records[0].prior_attempts) == 1
    assert records[0].prior_attempts[0].error_type == "ReadTimeout"
    assert records[1].prior_attempts == []
