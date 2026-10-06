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
from lancet_eval.journal import (
    JournalReuseError,
    RunRecord,
    WorkflowWireMeta,
    journal_key,
    load_done,
    load_records,
)
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

    # Companion (WR-03): resume=False no longer re-drives into a populated journal. The
    # stage cap is per invocation, so that would restart spend at zero.
    before = j_path.read_bytes()
    with pytest.raises(JournalReuseError, match="already holds records"):
        drive(
            corpus="graphrag_bench",
            journal_path=j_path,
            stage_spend_cap=5.0,
            resume=False,
            limit=1,
            workers=1,
            client=client,
        )
    assert dispatched == 0
    assert j_path.read_bytes() == before


def _stub_drive_one(monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_drive_one(*args: object, **kwargs: object) -> RunRecord:
        return RunRecord(
            corpus="graphrag_bench",
            question_id=str(kwargs["question"].id),  # type: ignore[attr-defined]
            graph_arm=str(kwargs["arm"]),
            outcome="success",
        )

    monkeypatch.setattr("lancet_eval.run.drive_one", mock_drive_one)


def test_drive_without_resume_refuses_a_populated_journal_and_leaves_it_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-03: `drive(resume=False)` on a journal that holds records is refused before
    anything is appended."""
    _stub_drive_one(monkeypatch)
    client = httpx.Client(base_url="http://testserver")
    j_path = tmp_path / "journal.jsonl"

    first = drive(
        corpus="graphrag_bench",
        journal_path=j_path,
        stage_spend_cap=5.0,
        resume=False,
        limit=1,
        workers=1,
        client=client,
    )
    assert first.executed_count == 2
    before = j_path.read_bytes()

    with pytest.raises(JournalReuseError, match=r"journal\.jsonl"):
        drive(
            corpus="graphrag_bench",
            journal_path=j_path,
            stage_spend_cap=5.0,
            resume=False,
            limit=1,
            workers=1,
            client=client,
        )

    assert j_path.read_bytes() == before


def test_drive_without_resume_still_works_on_a_missing_or_empty_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-03: a fresh run (no journal, or an empty file) is not refused."""
    _stub_drive_one(monkeypatch)
    client = httpx.Client(base_url="http://testserver")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")

    for journal in (tmp_path / "missing.jsonl", empty):
        result = drive(
            corpus="graphrag_bench",
            journal_path=journal,
            stage_spend_cap=5.0,
            resume=False,
            limit=1,
            workers=1,
            client=client,
        )
        assert result.executed_count == 2, journal.name


def test_drive_with_resume_is_unchanged_on_a_populated_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-03: `resume=True` still continues a populated journal."""
    _stub_drive_one(monkeypatch)
    client = httpx.Client(base_url="http://testserver")
    j_path = tmp_path / "journal.jsonl"

    def run_resumed() -> int:
        return drive(
            corpus="graphrag_bench",
            journal_path=j_path,
            stage_spend_cap=5.0,
            resume=True,
            limit=1,
            workers=1,
            client=client,
        ).executed_count

    assert run_resumed() == 2
    assert run_resumed() == 0


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


def test_cap_counts_failed_generations_and_stops_earlier_than_the_old_estimator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """06.3.4.1-23 (G4 cost item, D-86): failed generations were billed.

    Records whose GenerateAnswer failed carry zero wire tokens but were billed. The cap
    must be reached on the corrected estimate, not on embeddings alone.

    Each mocked record charges one per-attempt ceiling (~$0.0018), so a $0.005 cap is
    crossed at the third record. The old estimator charged only ~$0.0000144 of
    embeddings per record and would have dispatched every unit.
    """
    from lancet_eval.client import NodeFailed
    from lancet_eval.journal import NodeTiming
    from lancet_eval.measure import (
        EMBEDDING_PRICE_PER_1M,
        ESTIMATED_EMBEDDING_TOKENS_PER_QUERY,
        compute_spend,
    )

    j_path = tmp_path / "journal.jsonl"

    def mock_drive_one(*args: object, **kwargs: object) -> RunRecord:
        return RunRecord(
            corpus="graphrag_bench",
            question_id=str(kwargs.get("question", MagicMock()).id),
            graph_arm=str(kwargs.get("arm")),
            outcome="error",
            node_failures=[
                NodeFailed(
                    node_name="GenerateAnswer",
                    error_kind=3,
                    error_message=(
                        "answer basis 'mixed' requires at least one cited evidence ID"
                    ),
                    retryable=False,
                )
            ],
            node_timings=[NodeTiming(node_name="AssemblePrompt", duration_ms=12.0)],
            workflow_meta=WorkflowWireMeta(prompt_tokens=0, completion_tokens=0),
        )

    monkeypatch.setattr("lancet_eval.run.drive_one", mock_drive_one)

    cap = 0.005
    client = httpx.Client(base_url="http://testserver")
    res = drive(
        corpus="graphrag_bench",
        journal_path=j_path,
        stage_spend_cap=cap,
        limit=10,  # 20 work units
        workers=1,
        client=client,
    )

    journaled = load_records(j_path)
    assert res.stopped_by_cap is True
    assert len(journaled) == 3, "cap must be crossed at the third failed generation"
    assert res.executed_count == 3

    # Counterfactual: the old estimator (embeddings only for token-less records)
    # never reaches the cap.
    old_per_record = (
        ESTIMATED_EMBEDDING_TOKENS_PER_QUERY * EMBEDDING_PRICE_PER_1M / 1_000_000.0
    )
    assert 20 * old_per_record < cap
    assert compute_spend(journaled)[0] >= cap
    assert compute_spend(journaled[:2])[0] < cap


def _wr01_stub_drive_one(*args: object, **kwargs: object) -> RunRecord:
    return RunRecord(
        corpus="graphrag_bench",
        question_id=str(kwargs.get("question", MagicMock()).id),
        graph_arm=str(kwargs.get("arm")),
        outcome="success",
    )


def test_drive_complete_run_is_not_labelled_capped_when_last_record_crosses_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-01 (06.3.4.1-31): a cap first reached by the final record, with no unit left
    to dispatch, must not read as a capped drive.

    3 questions x 2 arms = 6 units; spend is $0.01 per record, so the 6th record
    brings spend to exactly the cap with nothing left waiting.
    """
    dispatched = 0

    def counting_drive_one(*args: object, **kwargs: object) -> RunRecord:
        nonlocal dispatched
        dispatched += 1
        return _wr01_stub_drive_one(*args, **kwargs)

    monkeypatch.setattr("lancet_eval.run.drive_one", counting_drive_one)
    monkeypatch.setattr(
        "lancet_eval.run.compute_spend",
        lambda records, include_embeddings=True: (0.01 * len(records), False),
    )

    res = drive(
        corpus="graphrag_bench",
        journal_path=tmp_path / "journal.jsonl",
        stage_spend_cap=0.01 * 6,
        limit=3,
        workers=1,
        client=httpx.Client(base_url="http://testserver"),
    )
    assert dispatched == 6
    assert res.executed_count == 6
    assert res.stopped_by_cap is False
    assert res.capped is False


def test_drive_is_labelled_capped_when_cap_reached_with_units_still_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-01 companion: cap reached after the 2nd of 6 records leaves work undone."""
    dispatched = 0

    def counting_drive_one(*args: object, **kwargs: object) -> RunRecord:
        nonlocal dispatched
        dispatched += 1
        return _wr01_stub_drive_one(*args, **kwargs)

    monkeypatch.setattr("lancet_eval.run.drive_one", counting_drive_one)
    monkeypatch.setattr(
        "lancet_eval.run.compute_spend",
        lambda records, include_embeddings=True: (0.01 * len(records), False),
    )

    res = drive(
        corpus="graphrag_bench",
        journal_path=tmp_path / "journal.jsonl",
        stage_spend_cap=0.01 * 2,
        limit=3,
        workers=1,
        client=httpx.Client(base_url="http://testserver"),
    )
    assert dispatched == 2
    assert res.executed_count == 2
    assert res.stopped_by_cap is True
    assert res.capped is True


# ---------------------------------------------------------------------------
# 06.3.4.1-31 (WR-02, D-86): --stage-cap rejects values that cannot fire.
# ---------------------------------------------------------------------------

_BAD_CAPS = ["nan", "inf", "-inf", "0", "-1"]


def _invoke_run(tmp_path: Path, cap_args: list[str]) -> object:
    return CliRunner().invoke(
        app,
        [
            "run",
            "--corpus",
            "multihop_rag",
            *cap_args,
            "--out",
            str(tmp_path / "j.jsonl"),
        ],
    )


@pytest.mark.parametrize("bad_cap", _BAD_CAPS)
def test_cli_run_rejects_stage_cap_that_cannot_fire(
    bad_cap: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        "lancet_eval.run.drive", lambda *a, **k: calls.append(k) or DriveResult(0)
    )
    res = _invoke_run(tmp_path, [f"--stage-cap={bad_cap}"])
    assert res.exit_code == 2
    assert "--stage-cap" in res.output
    assert calls == []


@pytest.mark.parametrize("bad_cap", _BAD_CAPS)
def test_cli_measure_rejects_stage_cap_that_cannot_fire(
    bad_cap: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []

    def fake_measure(*a: object, **k: object) -> tuple[Path, dict[str, object]]:
        calls.append(k)
        return Path("stub-run-dir"), {"total_records_emitted": 0}

    monkeypatch.setattr("lancet_eval.measure.run_measurement_pass", fake_measure)
    res = CliRunner().invoke(app, ["measure", f"--stage-cap={bad_cap}"])
    assert res.exit_code == 2
    assert "--stage-cap" in res.output
    assert calls == []


@pytest.mark.parametrize("bad_cap", _BAD_CAPS)
def test_cli_score_rejects_stage_cap_that_cannot_fire(
    bad_cap: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        "lancet_eval.score.score_run", lambda *a, **k: calls.append(k) or MagicMock()
    )
    monkeypatch.setattr("lancet_eval.cli.render_markdown", lambda *a, **k: "report")
    res = CliRunner().invoke(
        app, ["score", "--run", str(tmp_path), f"--stage-cap={bad_cap}"]
    )
    assert res.exit_code == 2
    assert "--stage-cap" in res.output
    assert calls == []


def test_cli_measure_without_stage_cap_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`measure --stage-cap` is required: the silent $5.00 default is gone."""
    calls: list[object] = []

    def fake_measure(*a: object, **k: object) -> tuple[Path, dict[str, object]]:
        calls.append(k)
        return Path("stub-run-dir"), {"total_records_emitted": 0}

    monkeypatch.setattr("lancet_eval.measure.run_measurement_pass", fake_measure)
    res = CliRunner().invoke(app, ["measure"])
    assert res.exit_code != 0
    assert "--stage-cap" in res.output
    assert calls == []


def test_cli_score_without_stage_cap_still_reaches_score_run_with_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, object]] = []

    def fake_score_run(*args: object, **kwargs: object) -> MagicMock:
        seen.append(dict(kwargs))
        return MagicMock()

    monkeypatch.setattr("lancet_eval.score.score_run", fake_score_run)
    monkeypatch.setattr("lancet_eval.cli.render_markdown", lambda *a, **k: "report")
    res = CliRunner().invoke(app, ["score", "--run", str(tmp_path)])
    assert res.exit_code == 0
    assert seen[0]["stage_spend_cap"] is None


def test_cli_valid_stage_cap_reaches_each_callee_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_seen: list[dict[str, object]] = []
    measure_seen: list[dict[str, object]] = []
    score_seen: list[dict[str, object]] = []

    def fake_drive(*args: object, **kwargs: object) -> DriveResult:
        run_seen.append(dict(kwargs))
        return DriveResult(0)

    def fake_measure(*args: object, **kwargs: object) -> tuple[Path, dict[str, object]]:
        measure_seen.append(dict(kwargs))
        return tmp_path, {"total_records_emitted": 0, "work_units_planned": 0}

    def fake_score_run(*args: object, **kwargs: object) -> MagicMock:
        score_seen.append(dict(kwargs))
        return MagicMock()

    monkeypatch.setattr("lancet_eval.run.drive", fake_drive)
    monkeypatch.setattr("lancet_eval.measure.run_measurement_pass", fake_measure)
    monkeypatch.setattr("lancet_eval.score.score_run", fake_score_run)
    monkeypatch.setattr("lancet_eval.cli.render_markdown", lambda *a, **k: "report")

    runner = CliRunner()
    assert _invoke_run(tmp_path, ["--stage-cap", "0.5"]).exit_code == 0
    assert runner.invoke(app, ["measure", "--stage-cap", "0.5"]).exit_code == 0
    assert (
        runner.invoke(
            app, ["score", "--run", str(tmp_path), "--stage-cap", "0.5"]
        ).exit_code
        == 0
    )
    assert run_seen[0]["stage_spend_cap"] == 0.5
    assert measure_seen[0]["stage_spend_cap"] == 0.5
    assert score_seen[0]["stage_spend_cap"] == 0.5


def _drive_with_stubbed_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_prior_attempt: bool,
    cap: float,
) -> tuple[DriveResult, list[RunRecord]]:
    """Drive 20 units whose stub records each cost the same wire tokens."""
    from lancet_eval.journal import AttemptRecord

    def stub(*args: object, **kwargs: object) -> RunRecord:
        meta = WorkflowWireMeta(prompt_tokens=20_000, completion_tokens=5_000)
        prior = (
            [
                AttemptRecord(
                    attempt=1,
                    outcome="success",
                    answer_chars=0,
                    workflow_meta=meta,
                )
            ]
            if with_prior_attempt
            else []
        )
        return RunRecord(
            corpus="graphrag_bench",
            question_id=str(kwargs.get("question", MagicMock()).id),
            graph_arm=str(kwargs.get("arm")),
            outcome="success",
            workflow_meta=meta,
            prior_attempts=prior,
        )

    monkeypatch.setattr("lancet_eval.run.drive_one", stub)
    sub = tmp_path / ("with" if with_prior_attempt else "without")
    res = drive(
        corpus="graphrag_bench",
        journal_path=sub / "journal.jsonl",
        stage_spend_cap=cap,
        limit=10,  # 20 work units
        workers=1,
        client=httpx.Client(base_url="http://testserver"),
    )
    return res, load_records(sub / "journal.jsonl")


def test_cap_sees_retried_spend_and_stops_earlier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-03 (D-86): a billed attempt a retry replaced still counts toward the cap.

    Each stub record costs about $0.0044 of wire tokens. With a $0.01 cap the drive
    crosses it at the third record; when every record also carries one prior attempt
    with the same tokens, each unit costs double and the drive crosses it at the second.
    """
    cap = 0.01
    plain, plain_records = _drive_with_stubbed_records(
        tmp_path, monkeypatch, with_prior_attempt=False, cap=cap
    )
    retried, retried_records = _drive_with_stubbed_records(
        tmp_path, monkeypatch, with_prior_attempt=True, cap=cap
    )

    assert plain.stopped_by_cap is True
    assert retried.stopped_by_cap is True
    assert len(plain_records) == 3
    assert len(retried_records) == 2
    assert retried.executed_count < plain.executed_count
    assert retried.observed_spend >= cap
