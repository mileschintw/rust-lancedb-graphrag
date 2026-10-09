"""Tests for two-armed runner, request body invariants, and resume."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from lancet_eval.arms import ARM_REGISTRY
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
    assert "gate_stage" in captured_kwargs
    assert captured_kwargs["gate_stage"] is None


# --- 06.3.4.1-33 Task 1: every superseded attempt is journaled (CR-03) ---

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
    "\"error_message\": \"answer basis 'mixed' requires at least one cited "
    "evidence ID\", "
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
    return GoldQuestion(
        question_id="q1", question="What is Paris?", gold_facts=["Paris"]
    )


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
    """The first attempt of a retried record reads as timeout, like max_retries=0."""
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

    rec = RunRecord(
        corpus="c", question_id="q", graph_arm="graph-on", outcome="success"
    )
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


# --- 06.3.4.1-33 Task 3: gate-stage marker, retry refusal, header guard (D-67) ---

_GATE_HEADER_BASE = {
    "type": "header",
    "corpus": "graphrag_bench",
    "partial": True,
    "created_at": 1.0,
}


def _header(**extra: object) -> dict[str, object]:
    return {**_GATE_HEADER_BASE, **extra}


def _seed_journal(path: Path, header: dict[str, object] | None) -> bytes:
    """Write a non-empty journal (optional header, one record); return its bytes."""
    from lancet_eval.journal import RunRecord

    lines = [] if header is None else [json.dumps(header)]
    lines.append(
        RunRecord(
            corpus="graphrag_bench",
            question_id="seed-q",
            graph_arm="graph-on",
            outcome="success",
        ).model_dump_json()
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path.read_bytes()


def _drive_gate(
    path: Path, *, gate_stage: str | None, max_retries: int, resume: bool = True
) -> int:
    return drive(
        corpus="graphrag_bench",
        journal_path=path,
        stage_spend_cap=10.0,
        limit=1,
        workers=1,
        resume=resume,
        max_retries=max_retries,
        gate_stage=gate_stage,
        client=httpx.Client(base_url="http://testserver"),
    )


def test_gate_stage_drive_refuses_retries_before_any_journal_io(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    j_path = tmp_path / "journal.jsonl"
    for retries in (1, 2):
        with pytest.raises(ValueError, match="--retries 0"):
            _drive_gate(j_path, gate_stage="drive3", max_retries=retries)
    assert not j_path.exists()
    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize(
    "label",
    ["", "has space", "bad/label", "-leading-dash", "x" * 65, "drive3\n"],
)
def test_gate_stage_drive_refuses_a_malformed_label_before_any_journal_io(
    label: str, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    j_path = tmp_path / "journal.jsonl"
    with pytest.raises(ValueError, match="gate-stage label"):
        _drive_gate(j_path, gate_stage=label, max_retries=0)
    assert not j_path.exists()


def test_gate_stage_drive_writes_the_marker_into_the_header(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    from lancet_eval.journal import read_journal_header

    httpx_mock.add_callback(_sse(_SSE_ANSWER_OK), is_reusable=True)
    j_path = tmp_path / "journal.jsonl"

    assert _drive_gate(j_path, gate_stage="drive3", max_retries=0) == 2

    header = read_journal_header(j_path)
    assert header is not None
    assert header["gate_stage"] == "drive3"
    assert header["max_retries"] == 0


def test_non_gate_drive_writes_a_null_gate_stage_and_its_retries(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    from lancet_eval.journal import read_journal_header

    httpx_mock.add_callback(_sse(_SSE_ANSWER_OK), is_reusable=True)
    j_path = tmp_path / "journal.jsonl"

    assert _drive_gate(j_path, gate_stage=None, max_retries=2) == 2

    header = read_journal_header(j_path)
    assert header is not None
    assert header["gate_stage"] is None
    assert header["max_retries"] == 2


@pytest.mark.parametrize("resume", [True, False])
@pytest.mark.parametrize(
    "existing_header",
    [
        pytest.param(_header(), id="unmarked"),
        pytest.param(None, id="no-header"),
        pytest.param(_header(gate_stage="drive2", max_retries=0), id="different-label"),
        pytest.param(_header(gate_stage=None, max_retries=0), id="non-gate-header"),
        pytest.param(
            _header(gate_stage="drive3", max_retries=2), id="different-retries"
        ),
    ],
)
def test_gate_stage_drive_refuses_to_append_to_a_journal_it_does_not_describe(
    existing_header: dict[str, object] | None,
    resume: bool,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
) -> None:
    j_path = tmp_path / "journal.jsonl"
    before = _seed_journal(j_path, existing_header)

    with pytest.raises(ValueError, match="gate_stage"):
        _drive_gate(j_path, gate_stage="drive3", max_retries=0, resume=resume)

    assert j_path.read_bytes() == before, "no record line may be appended"
    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize("resume", [True, False])
@pytest.mark.parametrize(
    ("header", "max_retries"),
    [
        pytest.param(_header(gate_stage="drive3", max_retries=0), 2, id="gate-journal"),
        pytest.param(
            _header(gate_stage=None, max_retries=0), 2, id="other-retries-lower"
        ),
        pytest.param(
            _header(gate_stage=None, max_retries=2), 0, id="other-retries-higher"
        ),
    ],
)
def test_any_drive_refuses_a_journal_whose_marker_differs_from_its_own(
    header: dict[str, object],
    max_retries: int,
    resume: bool,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
) -> None:
    j_path = tmp_path / "journal.jsonl"
    before = _seed_journal(j_path, header)

    with pytest.raises(ValueError, match="gate_stage"):
        _drive_gate(j_path, gate_stage=None, max_retries=max_retries, resume=resume)

    assert j_path.read_bytes() == before
    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize("header", [_header(), None], ids=["unmarked", "no-header"])
def test_non_gate_drive_still_appends_to_an_unmarked_journal(
    header: dict[str, object] | None, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_callback(_sse(_SSE_ANSWER_OK), is_reusable=True)
    j_path = tmp_path / "journal.jsonl"
    _seed_journal(j_path, header)

    assert _drive_gate(j_path, gate_stage=None, max_retries=2) == 2


@pytest.mark.parametrize(
    ("gate_stage", "max_retries"), [("drive3", 0), (None, 2)], ids=["gate", "non-gate"]
)
def test_a_drive_resumes_a_journal_carrying_its_own_marker(
    gate_stage: str | None, max_retries: int, tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_callback(_sse(_SSE_ANSWER_OK), is_reusable=True)
    j_path = tmp_path / "journal.jsonl"
    _seed_journal(j_path, _header(gate_stage=gate_stage, max_retries=max_retries))

    assert _drive_gate(j_path, gate_stage=gate_stage, max_retries=max_retries) == 2


def _invoke_gate_run(tmp_path: Path, extra: list[str]) -> object:
    from typer.testing import CliRunner

    from lancet_eval.cli import app

    return CliRunner().invoke(
        app,
        [
            "run",
            "--corpus",
            "multihop_rag",
            "--stage-cap",
            "0.5",
            "--out",
            str(tmp_path / "journal.jsonl"),
            *extra,
        ],
    )


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(["--gate-stage", "drive3"], id="default-retries"),
        pytest.param(["--gate-stage", "drive3", "--retries", "1"], id="retries-1"),
        pytest.param(["--gate-stage", "drive3", "-r", "2"], id="retries-2"),
    ],
)
def test_run_gate_stage_refuses_retries_other_than_zero(
    extra: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        "lancet_eval.run.drive", lambda *a, **k: calls.append(k) or 0
    )

    res = _invoke_gate_run(tmp_path, extra)

    assert res.exit_code == 2
    assert "--retries" in res.output
    assert calls == []


def test_run_gate_stage_with_zero_retries_forwards_the_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "lancet_eval.run.drive", lambda *a, **k: calls.append(dict(k)) or 0
    )

    res = _invoke_gate_run(tmp_path, ["--gate-stage", "drive3", "--retries", "0"])

    assert res.exit_code == 0
    assert calls[0]["gate_stage"] == "drive3"
    assert calls[0]["max_retries"] == 0


def test_run_without_gate_stage_forwards_none_and_keeps_default_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "lancet_eval.run.drive", lambda *a, **k: calls.append(dict(k)) or 0
    )

    res = _invoke_gate_run(tmp_path, [])

    assert res.exit_code == 0
    assert "gate_stage" in calls[0] and calls[0]["gate_stage"] is None
    assert calls[0]["max_retries"] == 2


@pytest.mark.parametrize("label", ["", "  ", "has space", "tab\there"])
def test_run_gate_stage_refuses_a_blank_or_whitespace_label(
    label: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        "lancet_eval.run.drive", lambda *a, **k: calls.append(k) or 0
    )

    res = _invoke_gate_run(tmp_path, ["--gate-stage", label, "--retries", "0"])

    assert res.exit_code == 2
    assert "--gate-stage" in res.output
    assert "whitespace" in res.output
    assert calls == []


# --- 06.3.5-05 Task 2: every request path sends the registry's flags (D-101, D-100) ---

_GRAPH_ABLATION_NOTICE = {"code": "GRAPH_ABLATION", "message": "", "typed_code": 18}


def _echoing_stream(request: httpx.Request) -> httpx.Response:
    """A stream whose snapshot echoes the request's mode and its graph ablation."""
    body = json.loads(request.read().decode("utf-8"))
    mode = body.get("retrieval_mode")
    snapshot: dict[str, object] = {"index_generation": "gen1"}
    if mode is not None:
        snapshot["retrieval_mode"] = mode
    levers = body.get("levers") or []
    if levers:
        snapshot["levers"] = levers
    answer: dict[str, object] = {"answer": "Paris", "snapshot": snapshot}
    if body.get("disable_graph_context"):
        answer["notices"] = [_GRAPH_ABLATION_NOTICE]
    completed: dict[str, object] = {"success": True, "duration_ms": 100}
    if "rerank" in levers:
        completed["metadata"] = {
            "rerank": {
                "latency_ms": 120,
                "cost_credits": 4.4e-07,
                "cost_reported": True,
                "outcome": "completed",
            }
        }
    text = (
        "event: final_answer\n"
        f"data: {json.dumps(answer)}\n\n"
        "event: workflow_completed\n"
        f"data: {json.dumps(completed)}\n\n"
    )
    return httpx.Response(
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=text,
    )


def test_drive_one_unknown_arm_names_the_valid_labels() -> None:
    client = httpx.Client(base_url="http://testserver")
    with pytest.raises(ValueError) as excinfo:
        drive_one(client, corpus="multihop_rag", question=_q(), arm="bogus")
    message = str(excinfo.value)
    assert message.startswith("Unknown arm 'bogus'. Expected one of:")
    for label in (*ARM_REGISTRY, "graph-on", "graph-off"):
        assert label in message


def test_drive_one_legacy_labels_send_todays_request_bodies(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    client = httpx.Client(base_url="http://testserver")

    drive_one(client, corpus="multihop_rag", question=_q(), arm="graph-off")
    drive_one(client, corpus="multihop_rag", question=_q(), arm="graph-on")

    off, on = (
        json.loads(r.read().decode("utf-8")) for r in httpx_mock.get_requests()
    )
    base = {"query": "What is Paris?", "session_id": ""}
    assert off == {**base, "disable_graph_context": True}
    assert on == base


def test_every_registry_arm_round_trips_request_to_provenance(
    httpx_mock: HTTPXMock,
) -> None:
    """Companion invariant: a new arm without flags or provenance turns this red."""
    from lancet_eval.arms import (
        lever_echo_failures,
        mode_provenance_failures,
        request_fields,
    )

    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    client = httpx.Client(base_url="http://testserver")

    for label in ARM_REGISTRY:
        rec = drive_one(client, corpus="multihop_rag", question=_q(), arm=label)
        assert rec.outcome == "success"
        assert rec.graph_arm == label
        body = json.loads(httpx_mock.get_requests()[-1].read().decode("utf-8"))

        # 1. the request body is exactly query + session + the registry's flags
        assert set(body) == {"query", "session_id", *request_fields(label)}
        assert body["include_pre_truncation_ranking"] is True

        # 2./3. the echoed mode and ablation notice satisfy the provenance check
        assert rec.snapshot is not None
        assert rec.snapshot.retrieval_mode == body["retrieval_mode"]
        assert (
            mode_provenance_failures(label, rec.snapshot.retrieval_mode, rec.notices)
            == []
        )
        assert lever_echo_failures(label, rec.snapshot.levers) == []
        assert body.get("levers", []) == list(ARM_REGISTRY[label].levers)

        # 4. another arm's echo is a failure that names the label
        other_mode = next(
            s.retrieval_mode
            for s in ARM_REGISTRY.values()
            if s.retrieval_mode != ARM_REGISTRY[label].retrieval_mode
        )
        failures = mode_provenance_failures(label, other_mode, rec.notices)
        assert failures
        assert all(label in f for f in failures)


def test_mode_provenance_failures_rules() -> None:
    from lancet_eval.arms import mode_provenance_failures
    from lancet_eval.client import Notice

    ablation = Notice(code="GRAPH_ABLATION", message="", typed_code=18)
    unavailable = Notice(code="GRAPH_UNAVAILABLE", message="", typed_code=10)

    # a missing echo is a failure on a canonical label
    assert mode_provenance_failures("hybrid+graph", None, [])
    # graph-off arms need the ablation notice and not the unavailable one
    assert mode_provenance_failures("dense-only", "dense_only", [])
    assert mode_provenance_failures("dense-only", "dense_only", [ablation, unavailable])
    assert mode_provenance_failures("dense-only", "dense_only", [ablation]) == []
    # hybrid+graph does not need the ablation notice
    assert mode_provenance_failures("hybrid+graph", "hybrid", []) == []
    # legacy labels: graph-off check only, no echo required
    assert mode_provenance_failures("graph-off", None, [ablation]) == []
    assert mode_provenance_failures("graph-off", None, [])
    assert mode_provenance_failures("graph-on", None, []) == []


def test_raw_events_directory_uses_the_slug_for_canonical_labels(
    tmp_path: Path,
) -> None:
    from lancet_eval.raw_events import RawEventSink

    sink = RawEventSink(tmp_path)
    events = [{"event": "x", "data": "{}"}]
    for label in ("hybrid+graph", "graph-on", "dense-only"):
        sink.write_events(corpus="c", question_id="q1", graph_arm=label, events=events)
    raw = tmp_path / "raw_events"
    assert (raw / "hybrid_graph" / "q1.jsonl").is_file()
    assert (raw / "graph-on" / "q1.jsonl").is_file()
    assert (raw / "dense_only" / "q1.jsonl").is_file()
    assert not (raw / "hybrid+graph").exists()


@pytest.mark.parametrize(
    "arm",
    ["dense-only", "bm25-only", "hybrid", "hybrid+graph", "graph-on", "graph-off"],
)
def test_probe_accepts_the_four_labels_and_both_aliases(
    arm: str, httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    from typer.testing import CliRunner

    from lancet_eval.arms import request_fields
    from lancet_eval.cli import app

    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    res = CliRunner().invoke(
        app, ["probe", "-q", "q", "-f", "f", "--arm", arm, "-o", str(tmp_path / "o")]
    )
    assert res.exit_code == 0, res.output
    body = json.loads(httpx_mock.get_requests()[0].read().decode("utf-8"))
    assert set(body) == {"query", "session_id", *request_fields(arm)}


def test_probe_rejects_an_unknown_arm_with_exit_2() -> None:
    from typer.testing import CliRunner

    from lancet_eval.cli import app

    res = CliRunner().invoke(
        app, ["probe", "-q", "q", "-f", "f", "--arm", "dense+graph"]
    )
    assert res.exit_code == 2


# --- 06.3.5-05 Task 3: seeded rotation, split-role refusals, header provenance ---


def _split_path() -> Path:
    from lancet_eval.config import repo_root

    return repo_root() / "eval" / "corpora" / "multihop_rag" / "heldout_split.json"


def _drive_split(
    corpus: str,
    journal: Path,
    *,
    limit: int | None = None,
    resume: bool = True,
) -> int:
    return drive(
        corpus=corpus,
        journal_path=journal,
        stage_spend_cap=10.0,
        limit=limit,
        workers=1,
        resume=resume,
        max_retries=0,
        client=httpx.Client(base_url="http://testserver"),
    )


def _journal_units(path: Path) -> list[tuple[str, str]]:
    from lancet_eval.journal import load_records

    return [(r.question_id, r.graph_arm) for r in load_records(path)]


@pytest.mark.usefixtures("preregistered_clean_tree")
def test_split_drive_follows_the_seeded_rotation_and_limit_takes_whole_questions(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    from lancet_eval.arms import plan_work_units
    from lancet_eval.corpus import load_corpus_config, load_sample_questions
    from lancet_eval.split import load_split

    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    config = load_corpus_config("multihop_rag_heldout")
    planned = plan_work_units(
        load_sample_questions("multihop_rag_heldout"),
        config.arms,
        load_split(_split_path()).order_seed,
    )
    j_path = tmp_path / "journal.jsonl"

    assert _drive_split("multihop_rag_heldout", j_path, limit=3) == 12

    expected = [(q.question_id, arm) for q, arm in planned[:12]]
    assert _journal_units(j_path) == expected
    # the first three questions of the rotated order, all four arms each
    assert len({q for q, _ in expected}) == 3
    assert sorted(a for _, a in expected[:4]) == sorted(config.arms)


@pytest.mark.usefixtures("preregistered_clean_tree")
def test_split_drive_resume_rebuilds_the_same_suffix(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    from lancet_eval.arms import plan_work_units
    from lancet_eval.corpus import load_corpus_config, load_sample_questions
    from lancet_eval.split import load_split

    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    config = load_corpus_config("multihop_rag_heldout")
    planned = plan_work_units(
        load_sample_questions("multihop_rag_heldout"),
        config.arms,
        load_split(_split_path()).order_seed,
    )
    j_path = tmp_path / "journal.jsonl"

    assert _drive_split("multihop_rag_heldout", j_path, limit=25) == 100
    assert _drive_split("multihop_rag_heldout", j_path, limit=30) == 20

    assert _journal_units(j_path) == [(q.question_id, a) for q, a in planned[:120]]


def test_legacy_corpus_work_units_equal_the_old_question_major_comprehension(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    from lancet_eval.corpus import load_corpus_config, load_sample_questions

    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    for corpus in ("multihop_rag_diag", "graphrag_bench"):
        config = load_corpus_config(corpus)
        assert config.split_file is None
        questions = load_sample_questions(corpus)[:2]
        old = [(q.question_id, arm) for q in questions for arm in config.arms]
        j_path = tmp_path / f"{corpus}.jsonl"

        assert _drive_split(corpus, j_path, limit=2) == len(old)
        assert _journal_units(j_path) == old


@pytest.mark.usefixtures("preregistered_clean_tree")
def test_split_drive_header_carries_order_seed_and_split_digest(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    from lancet_eval.journal import read_journal_header
    from lancet_eval.split import load_split, split_sha256

    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    j_path = tmp_path / "journal.jsonl"
    _drive_split("multihop_rag_heldout", j_path, limit=1)

    split = load_split(_split_path())
    header = read_journal_header(j_path)
    assert header is not None
    assert header["order_seed"] == split.order_seed == 42
    assert header["split_sha256"] == split_sha256(split)
    assert "gate_stage" in header and "max_retries" in header


def test_legacy_header_has_no_split_keys(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    from lancet_eval.journal import read_journal_header

    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    j_path = tmp_path / "journal.jsonl"
    _drive_split("graphrag_bench", j_path, limit=1)

    header = read_journal_header(j_path)
    assert header is not None
    assert "order_seed" not in header
    assert "split_sha256" not in header


@pytest.mark.usefixtures("preregistered_clean_tree")
def test_heldout_corpus_that_differs_from_the_split_is_refused_before_any_io(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval.corpus import load_sample_questions

    questions = load_sample_questions("multihop_rag_heldout")
    monkeypatch.setattr(
        "lancet_eval.run.load_sample_questions", lambda _name: questions[:350]
    )
    j_path = tmp_path / "journal.jsonl"

    with pytest.raises(ValueError, match="351") as excinfo:
        _drive_split("multihop_rag_heldout", j_path)
    assert "350" in str(excinfo.value)
    assert not j_path.exists()
    assert httpx_mock.get_requests() == []


@pytest.mark.usefixtures("preregistered_clean_tree")
def test_heldout_corpus_with_a_foreign_question_is_refused(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval.corpus import load_sample_questions
    from lancet_eval.split import load_split

    questions = load_sample_questions("multihop_rag_heldout")
    dev_id = load_split(_split_path()).dev_ids[0]
    swapped = [
        GoldQuestion(question_id=dev_id, question="dev?", gold_facts=[]),
        *questions[1:],
    ]
    monkeypatch.setattr("lancet_eval.run.load_sample_questions", lambda _name: swapped)
    j_path = tmp_path / "journal.jsonl"

    with pytest.raises(ValueError, match="held-out"):
        _drive_split("multihop_rag_heldout", j_path)
    assert not j_path.exists()
    assert httpx_mock.get_requests() == []


@pytest.mark.usefixtures("preregistered_clean_tree")
def test_rehearsal_corpus_holding_a_dev_or_heldout_id_is_refused_before_any_request(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval.corpus import load_sample_questions
    from lancet_eval.split import load_split

    split = load_split(_split_path())
    base = load_sample_questions("multihop_rag_rehearsal")
    leaks = (split.dev_ids[0], split.heldout_g_ids[0], split.heldout_null_ids[0])
    for leaked_id in leaks:
        leaked = [
            *base,
            GoldQuestion(question_id=leaked_id, question="leak?", gold_facts=[]),
        ]
        monkeypatch.setattr(
            "lancet_eval.run.load_sample_questions", lambda _name, qs=leaked: qs
        )
        j_path = tmp_path / f"{leaked_id}.jsonl"
        with pytest.raises(ValueError, match="rehearsal"):
            _drive_split("multihop_rag_rehearsal", j_path)
        assert not j_path.exists()
    assert httpx_mock.get_requests() == []


@pytest.mark.usefixtures("preregistered_clean_tree")
def test_real_rehearsal_corpus_is_disjoint_and_runs_the_rotation(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    j_path = tmp_path / "journal.jsonl"

    assert _drive_split("multihop_rag_rehearsal", j_path) == 12
    assert len({q for q, _ in _journal_units(j_path)}) == 3


# --- 06.3.5 WR-01: a resumed [split] drive proves the journal's split and seed ---


def _split_header(**extra: object) -> dict[str, object]:
    from lancet_eval.split import load_split, split_sha256

    split = load_split(_split_path())
    return {
        "type": "header",
        "corpus": "multihop_rag_heldout",
        "partial": True,
        "created_at": 1.0,
        "gate_stage": None,
        "max_retries": 0,
        "order_seed": split.order_seed,
        "split_sha256": split_sha256(split),
        **extra,
    }


@pytest.mark.usefixtures("preregistered_clean_tree")
@pytest.mark.parametrize(
    "header",
    [
        pytest.param(_split_header(split_sha256="0" * 64), id="other-split"),
        pytest.param(_split_header(order_seed=7), id="other-seed"),
        pytest.param(
            {k: v for k, v in _split_header().items() if k != "split_sha256"},
            id="no-split-digest",
        ),
        pytest.param(
            {k: v for k, v in _split_header().items() if k != "order_seed"},
            id="no-seed",
        ),
    ],
)
def test_resumed_split_drive_refuses_a_journal_begun_under_another_split_or_seed(
    header: dict[str, object], tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    j_path = tmp_path / "journal.jsonl"
    j_path.write_text(json.dumps(header) + "\n", encoding="utf-8")
    before = j_path.read_bytes()

    with pytest.raises(ValueError, match="split and seed"):
        _drive_split("multihop_rag_heldout", j_path, limit=1)
    assert j_path.read_bytes() == before
    assert httpx_mock.get_requests() == []


@pytest.mark.usefixtures("preregistered_clean_tree")
def test_resumed_split_drive_accepts_its_own_header(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    j_path = tmp_path / "journal.jsonl"
    assert _drive_split("multihop_rag_heldout", j_path, limit=1) == 4
    assert _drive_split("multihop_rag_heldout", j_path, limit=2) == 4


def test_split_marker_check_accepts_every_committed_split_journal() -> None:
    from lancet_eval.config import repo_root
    from lancet_eval.run import _require_matching_split_marker
    from lancet_eval.split import load_split

    split = load_split(_split_path())
    journals = [
        repo_root() / "eval" / "runs" / name / "journal.jsonl"
        for name in (
            "2026-10-07-heldout-multihop_rag_heldout",
            "2026-10-07-rehearsal-multihop_rag_rehearsal",
            "2026-10-07-rehearsal2-multihop_rag_rehearsal",
        )
    ]
    for journal in journals:
        assert journal.is_file(), journal
        _require_matching_split_marker(journal, split)


def test_a_drive_without_a_split_refuses_a_split_journal(tmp_path: Path) -> None:
    from lancet_eval.run import _require_matching_split_marker

    j_path = tmp_path / "journal.jsonl"
    j_path.write_text(json.dumps(_split_header()) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="held-out split"):
        _require_matching_split_marker(j_path, None)


@pytest.mark.usefixtures("preregistered_clean_tree")
def test_split_drive_refuses_a_split_whose_input_file_changed(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lancet_eval.split as split_mod

    monkeypatch.setattr(split_mod, "QUESTIONS_SAMPLE_REL", "eval/corpora/ATTRIBUTION.md")
    j_path = tmp_path / "journal.jsonl"

    with pytest.raises(ValueError, match="no longer matches"):
        _drive_split("multihop_rag_heldout", j_path, limit=1)
    assert not j_path.exists()
    assert httpx_mock.get_requests() == []


def test_split_marker_check_accepts_every_tracked_journal_under_eval_runs() -> None:
    """A [split] journal is checked against its split; every other one against None.

    Covers the legacy, diag and headerless measure journals too, so the non-split
    refusal is proven against the real closed artifacts.
    """
    import subprocess

    from lancet_eval.config import repo_root
    from lancet_eval.corpus import load_corpus_config
    from lancet_eval.journal import read_journal_header
    from lancet_eval.run import _require_matching_split_marker
    from lancet_eval.split import load_split

    root = repo_root()
    tracked = subprocess.run(
        ["git", "ls-files", "eval/runs"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    journals = [
        root / rel
        for rel in tracked
        if rel.endswith("/journal.jsonl") and "/raw_events/" not in rel
    ]
    assert len(journals) >= 10
    checked_with_split = 0
    for journal in journals:
        header = read_journal_header(journal) or {}
        corpus = header.get("corpus")
        config = load_corpus_config(corpus) if corpus else None
        if config is not None and config.split_path is not None:
            _require_matching_split_marker(journal, load_split(config.split_path))
            checked_with_split += 1
        else:
            _require_matching_split_marker(journal, None)
    assert checked_with_split == 3


# --- 06.3.6-03: the D-73 gate on the configured token, and the D-170 dev role ---


def _dev_config_and_questions(
    monkeypatch: pytest.MonkeyPatch, extra_ids: tuple[str, ...] = (), n_dev: int = 3
) -> tuple[object, list[GoldQuestion]]:
    """A `[split]` corpus config with role `dev` over the first dev IDs (+ extras)."""
    from lancet_eval.split import load_split

    config = load_corpus_config("multihop_rag_heldout")
    config.split_role = "dev"
    split = load_split(_split_path())
    ids = [*split.dev_ids[:n_dev], *extra_ids]
    questions = [
        GoldQuestion(question_id=qid, question=f"dev question {qid}?", gold_facts=[])
        for qid in ids
    ]
    monkeypatch.setattr("lancet_eval.run.load_corpus_config", lambda _name: config)
    monkeypatch.setattr(
        "lancet_eval.run.load_sample_questions", lambda _name: questions
    )
    return config, questions


def _forbid_the_gate(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    from lancet_eval import gitcheck

    calls: list[tuple[object, ...]] = []

    def record(*args: object, **kwargs: object) -> list[str]:
        calls.append(args)
        return []

    monkeypatch.setattr(gitcheck, "preregistration_problems", record)
    return calls


def test_dev_corpus_runs_the_seeded_rotation_and_never_calls_the_d73_gate(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval.arms import plan_work_units
    from lancet_eval.split import load_split

    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    calls = _forbid_the_gate(monkeypatch)
    config, questions = _dev_config_and_questions(monkeypatch)
    j_path = tmp_path / "journal.jsonl"

    assert _drive_split("multihop_rag_heldout", j_path) == 12

    planned = plan_work_units(
        questions,
        config.arms,  # type: ignore[attr-defined]
        load_split(_split_path()).order_seed,
    )
    assert _journal_units(j_path) == [(q.question_id, arm) for q, arm in planned]
    assert calls == []


@pytest.mark.parametrize("kind", ["heldout_g", "heldout_null", "outside"])
def test_dev_corpus_with_a_non_dev_id_is_refused_before_any_request(
    kind: str,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lancet_eval.split import load_split

    split = load_split(_split_path())
    stray = {
        "heldout_g": split.heldout_g_ids[0],
        "heldout_null": split.heldout_null_ids[0],
        "outside": "not-in-the-split-at-all",
    }[kind]
    _forbid_the_gate(monkeypatch)
    _dev_config_and_questions(monkeypatch, extra_ids=(stray,))
    j_path = tmp_path / "journal.jsonl"

    with pytest.raises(ValueError, match="D-170"):
        _drive_split("multihop_rag_heldout", j_path)
    assert not j_path.exists()
    assert httpx_mock.get_requests() == []


def test_heldout_corpus_calls_the_gate_with_exactly_its_configured_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval import gitcheck

    config = load_corpus_config("multihop_rag_heldout")
    config.preregistration_token = "PREREGISTRATION_X_FOR_TEST"
    monkeypatch.setattr("lancet_eval.run.load_corpus_config", lambda _name: config)
    seen: list[tuple[object, ...]] = []

    def refuse(*args: object, **_kwargs: object) -> list[str]:
        seen.append(args)
        return ["stop here"]

    monkeypatch.setattr(gitcheck, "preregistration_problems", refuse)
    j_path = tmp_path / "journal.jsonl"

    with pytest.raises(gitcheck.PreregistrationError, match="PREREGISTRATION_X"):
        _drive_split("multihop_rag_heldout", j_path)
    assert seen == [(("PREREGISTRATION_X_FOR_TEST",),)]
    assert not j_path.exists()


def test_rehearsal_corpus_keeps_the_gate_on_its_configured_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval import gitcheck

    seen: list[tuple[object, ...]] = []

    def refuse(*args: object, **_kwargs: object) -> list[str]:
        seen.append(args)
        return ["stop here"]

    monkeypatch.setattr(gitcheck, "preregistration_problems", refuse)
    with pytest.raises(gitcheck.PreregistrationError):
        _drive_split("multihop_rag_rehearsal", tmp_path / "journal.jsonl")
    assert seen == [(("PREREGISTRATION_06_3_5",),)]


# --- 06.3.6-07: the D-73 arm-set refusals at drive time (D-73, D-149) ---


def _synthetic_lever_prereg(arms: tuple[str, ...]) -> object:
    """A duck-typed lever pre-registration naming exactly `arms` (reference first)."""
    from types import SimpleNamespace

    return SimpleNamespace(
        reference_arm=arms[0],
        families=(SimpleNamespace(arms=tuple(arms[1:-1])),),
        descriptive_arms=(arms[-1],),
    )


def _split_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: str,
    arms: list[str],
    token: str,
) -> object:
    config = load_corpus_config("multihop_rag_heldout")
    config.split_role = role
    config.arms = arms
    config.preregistration_token = token
    monkeypatch.setattr("lancet_eval.run.load_corpus_config", lambda _name: config)
    return config


@pytest.mark.parametrize("role", ["heldout", "rehearsal"])
def test_a_lever_arm_under_the_06_3_5_token_is_refused_before_any_request(
    role: str,
    tmp_path: Path,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lancet_eval import gitcheck

    _forbid_the_gate(monkeypatch)
    _split_config(
        monkeypatch,
        role=role,
        arms=["hybrid", "hybrid+graph", "hybrid+rerank"],
        token="PREREGISTRATION_06_3_5",
    )
    j_path = tmp_path / "journal.jsonl"

    with pytest.raises(gitcheck.PreregistrationError, match="hybrid\\+rerank"):
        _drive_split("multihop_rag_heldout", j_path)
    assert not j_path.exists()
    assert httpx_mock.get_requests() == []


def test_the_06_3_5_arm_list_is_not_equality_checked(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only lever arms are refused under the 06.3.5 token; its own arms still run."""
    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    _forbid_the_gate(monkeypatch)
    _split_config(
        monkeypatch,
        role="rehearsal",
        arms=["hybrid", "hybrid+graph"],
        token="PREREGISTRATION_06_3_5",
    )
    _dev_questions_for_rehearsal(monkeypatch)

    journal = tmp_path / "journal.jsonl"
    assert _drive_split("multihop_rag_heldout", journal, limit=1) == 2


def _dev_questions_for_rehearsal(monkeypatch: pytest.MonkeyPatch) -> None:
    from lancet_eval.corpus import load_corpus_config as real_load

    questions = real_load("multihop_rag_rehearsal").questions[:3]
    monkeypatch.setattr(
        "lancet_eval.run.load_sample_questions", lambda _name: list(questions)
    )


def test_an_unknown_token_is_refused_before_any_request(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval import gitcheck

    _forbid_the_gate(monkeypatch)
    _split_config(
        monkeypatch,
        role="heldout",
        arms=["hybrid", "hybrid+rerank"],
        token="PREREGISTRATION_NOT_THERE",
    )
    j_path = tmp_path / "journal.jsonl"

    with pytest.raises(gitcheck.PreregistrationError, match="NOT_THERE"):
        _drive_split("multihop_rag_heldout", j_path)
    assert not j_path.exists()
    assert httpx_mock.get_requests() == []


def test_the_gate_still_runs_before_the_arm_set_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval import gitcheck

    seen: list[tuple[object, ...]] = []

    def refuse(*args: object, **_kwargs: object) -> list[str]:
        seen.append(args)
        return ["stop here"]

    monkeypatch.setattr(gitcheck, "preregistration_problems", refuse)
    _split_config(
        monkeypatch,
        role="heldout",
        arms=["hybrid", "hybrid+rerank"],
        token="PREREGISTRATION_NOT_THERE",
    )
    with pytest.raises(gitcheck.PreregistrationError, match="stop here"):
        _drive_split("multihop_rag_heldout", tmp_path / "journal.jsonl")
    assert seen == [(("PREREGISTRATION_NOT_THERE",),)]


def test_a_corpus_arm_list_that_differs_from_the_preregistration_is_refused(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval import gitcheck, thresholds

    monkeypatch.setattr(
        thresholds,
        "PREREGISTRATION_TEST_ARMS",
        _synthetic_lever_prereg(("hybrid", "hybrid+rerank", "hybrid+all")),
        raising=False,
    )
    _forbid_the_gate(monkeypatch)
    _split_config(
        monkeypatch,
        role="heldout",
        arms=["hybrid", "hybrid+rerank"],
        token="PREREGISTRATION_TEST_ARMS",
    )
    j_path = tmp_path / "journal.jsonl"

    with pytest.raises(gitcheck.PreregistrationError, match="hybrid\\+all"):
        _drive_split("multihop_rag_heldout", j_path)
    assert not j_path.exists()
    assert httpx_mock.get_requests() == []


def test_a_corpus_arm_list_equal_to_the_preregistration_is_driven(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval import thresholds

    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    monkeypatch.setattr(
        thresholds,
        "PREREGISTRATION_TEST_ARMS",
        _synthetic_lever_prereg(("hybrid", "hybrid+rerank", "hybrid+all")),
        raising=False,
    )
    _forbid_the_gate(monkeypatch)
    # An alias counts as the arm it names: graph-off is hybrid.
    _split_config(
        monkeypatch,
        role="rehearsal",
        arms=["graph-off", "hybrid+all", "hybrid+rerank"],
        token="PREREGISTRATION_TEST_ARMS",
    )
    _dev_questions_for_rehearsal(monkeypatch)

    journal = tmp_path / "journal.jsonl"
    assert _drive_split("multihop_rag_heldout", journal, limit=1) == 3


def test_a_dev_corpus_is_exempt_from_the_arm_set_refusals(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    calls = _forbid_the_gate(monkeypatch)
    config, _questions = _dev_config_and_questions(monkeypatch)
    config.arms = ["hybrid", "hybrid+rerank"]  # type: ignore[attr-defined]
    config.preregistration_token = "PREREGISTRATION_NOT_YET_FROZEN"  # type: ignore[attr-defined]

    assert _drive_split("multihop_rag_heldout", tmp_path / "journal.jsonl") == 6
    assert calls == []


def test_the_rotation_over_a_lever_arm_list_stays_the_seeded_balanced_one(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval.arms import plan_work_units
    from lancet_eval.split import load_split

    httpx_mock.add_callback(_echoing_stream, is_reusable=True)
    _forbid_the_gate(monkeypatch)
    arms = ["hybrid", "hybrid+graph", "hybrid+rerank", "hybrid+metadata", "hybrid+all"]
    config, questions = _dev_config_and_questions(monkeypatch)
    config.arms = arms  # type: ignore[attr-defined]
    j_path = tmp_path / "journal.jsonl"

    assert _drive_split("multihop_rag_heldout", j_path) == 3 * len(arms)
    planned = plan_work_units(questions, arms, load_split(_split_path()).order_seed)
    assert _journal_units(j_path) == [(q.question_id, arm) for q, arm in planned]
