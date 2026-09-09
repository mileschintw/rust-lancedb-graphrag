"""Tests for fail-closed stage spend cap enforcement in drive loop."""

import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from lancet_eval.cli import app
from lancet_eval.client import RetrievalSnapshot
from lancet_eval.journal import RunRecord, WorkflowWireMeta, journal_key, load_done, load_records
from lancet_eval.run import DriveResult, drive


def test_drive_stage_spend_cap_signature() -> None:
    """Proves drive() accepts stage_spend_cap as keyword-only parameter with no default."""
    sig = inspect.signature(drive)
    param = sig.parameters.get("stage_spend_cap")
    assert param is not None, "stage_spend_cap parameter must exist"
    assert param.kind == inspect.Parameter.KEYWORD_ONLY, "Must be keyword-only"
    assert param.default == inspect.Parameter.empty, "Must have no default value"


def test_drive_without_stage_spend_cap_raises() -> None:
    """Proves invoking drive() without stage_spend_cap raises TypeError."""
    with pytest.raises(TypeError, match="stage_spend_cap"):
        drive(corpus="multihop_rag", journal_path="dummy.jsonl")  # type: ignore[call-arg]


def test_drive_reports_cap_stop_distinguishably(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves stop by cap is reported distinguishably via stopped_by_cap / capped."""
    j_path = tmp_path / "journal.jsonl"

    # Mock drive_one to return records with large tokens
    def mock_drive_one(*args: object, **kwargs: object) -> RunRecord:
        return RunRecord(
            corpus="graphrag_bench",
            question_id=str(kwargs.get("question", MagicMock()).id),
            graph_arm=str(kwargs.get("arm")),
            outcome="success",
            workflow_meta=WorkflowWireMeta(prompt_tokens=10_000_000, completion_tokens=10_000_000),
        )

    monkeypatch.setattr("lancet_eval.run.drive_one", mock_drive_one)

    client = httpx.Client(base_url="http://testserver")
    res = drive(
        corpus="graphrag_bench",
        journal_path=j_path,
        stage_spend_cap=0.01,  # very low cap, exceeded immediately
        limit=5,
        workers=1,
        client=client,
    )
    assert isinstance(res, DriveResult)
    assert res.stopped_by_cap is True
    assert res.capped is True
    assert res > 0  # Executed at least 1 unit before stopping


def test_cap_stops_dispatch_bounded_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves bounded-window dispatch stops submitting once cap is hit.

    With workers=1, priming window is 1. Once completed, spend is evaluated.
    If cap is hit, at most 1 query is ever submitted in flight, never all units.
    """
    j_path = tmp_path / "journal.jsonl"
    submit_call_count = 0

    from concurrent.futures import ThreadPoolExecutor

    orig_submit = ThreadPoolExecutor.submit

    def counting_submit(self: ThreadPoolExecutor, fn: object, *args: object, **kwargs: object) -> object:
        nonlocal submit_call_count
        submit_call_count += 1
        return orig_submit(self, fn, *args, **kwargs)

    monkeypatch.setattr(ThreadPoolExecutor, "submit", counting_submit)

    def mock_drive_one(*args: object, **kwargs: object) -> RunRecord:
        return RunRecord(
            corpus="graphrag_bench",
            question_id=str(kwargs.get("question", MagicMock()).id),
            graph_arm=str(kwargs.get("arm")),
            outcome="success",
            workflow_meta=WorkflowWireMeta(prompt_tokens=5_000_000, completion_tokens=5_000_000),
        )

    monkeypatch.setattr("lancet_eval.run.drive_one", mock_drive_one)

    client = httpx.Client(base_url="http://testserver")
    # Limit = 10 questions x 2 arms = 20 total work units
    res = drive(
        corpus="graphrag_bench",
        journal_path=j_path,
        stage_spend_cap=0.01,
        limit=10,
        workers=1,
        client=client,
    )
    assert res.stopped_by_cap is True
    # With workers=1, 1 was primed, finished, spend evaluated (exceeded), 0 more submitted.
    # Total submitted should be 1 (or at most effective_workers + 1 = 2), NEVER 20.
    assert submit_call_count <= 2
    assert submit_call_count < 20


def test_accumulator_is_cumulative_over_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves resume=True seeds spend from journal and dispatches 0 units if already over cap."""
    j_path = tmp_path / "journal.jsonl"

    # Pre-populate journal with high token counts
    with open(j_path, "w", encoding="utf-8") as f:
        f.write('{"type": "header", "corpus": "graphrag_bench", "partial": true}\n')
        rec = RunRecord(
            corpus="graphrag_bench",
            question_id="pre-existing-q1",
            graph_arm="graph-on",
            outcome="success",
            workflow_meta=WorkflowWireMeta(prompt_tokens=10_000_000, completion_tokens=10_000_000),
        )
        f.write(rec.model_dump_json() + "\n")

    dispatched = 0

    def mock_drive_one(*args: object, **kwargs: object) -> RunRecord:
        nonlocal dispatched
        dispatched += 1
        return RunRecord(
            corpus="graphrag_bench",
            question_id="new-q",
            graph_arm="graph-on",
            outcome="success",
        )

    monkeypatch.setattr("lancet_eval.run.drive_one", mock_drive_one)

    client = httpx.Client(base_url="http://testserver")
    # Test resume=True: already exceeds cap 0.05 USD -> dispatches ZERO units
    res_resume = drive(
        corpus="graphrag_bench",
        journal_path=j_path,
        stage_spend_cap=0.05,
        resume=True,
        workers=1,
        client=client,
    )
    assert res_resume.stopped_by_cap is True
    assert dispatched == 0

    # Companion: resume=False starts accumulator empty
    res_no_resume = drive(
        corpus="graphrag_bench",
        journal_path=j_path,
        stage_spend_cap=5.0,
        resume=False,
        limit=1,
        workers=1,
        client=client,
    )
    assert dispatched > 0


def test_load_records_matches_load_done_parity(tmp_path: Path) -> None:
    """Proves load_records skips unparseable lines on exactly the same lines load_done skips them."""
    j_path = tmp_path / "journal.jsonl"

    valid_rec1 = RunRecord(corpus="c", question_id="q1", graph_arm="graph-on", outcome="success")
    valid_rec2 = RunRecord(corpus="c", question_id="q2", graph_arm="graph-off", outcome="success")

    with open(j_path, "w", encoding="utf-8") as f:
        f.write('{"type": "header", "corpus": "c", "partial": true}\n')
        f.write(valid_rec1.model_dump_json() + "\n")
        f.write('{"corrupt": "middle line not valid run record"}\n')
        f.write(valid_rec2.model_dump_json() + "\n")
        f.write('unparseable trailing garbage')

    done_keys = load_done(j_path)
    records = load_records(j_path)

    record_keys = {journal_key(r.corpus, r.question_id, r.graph_arm) for r in records}
    assert done_keys == record_keys
    assert len(records) == 2
    assert [r.question_id for r in records] == ["q1", "q2"]


def test_cli_run_without_stage_cap_exits_nonzero() -> None:
    """Proves invoking lancet-eval run without --stage-cap exits non-zero with missing option error."""
    runner = CliRunner()
    res = runner.invoke(app, ["run", "--corpus", "multihop_rag"])
    assert res.exit_code != 0
    assert "Missing option" in res.output or "--stage-cap" in res.output
