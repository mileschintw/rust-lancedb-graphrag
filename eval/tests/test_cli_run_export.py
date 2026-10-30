"""`lancet-eval run` reports a failed end-of-drive context export (#20, D-249)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lancet_eval.cli import app
from lancet_eval.run import DriveResult


def _invoke_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, result: DriveResult):
    monkeypatch.setattr("lancet_eval.run.drive", lambda *a, **k: result)
    run_dir = tmp_path / "run-2026"
    return CliRunner().invoke(
        app,
        [
            "run",
            "--corpus",
            "multihop_rag_heldout",
            "--stage-cap",
            "0.5",
            "--out",
            str(run_dir / "journal.jsonl"),
        ],
        terminal_width=400,
    )


def _flat(output: str) -> str:
    return " ".join(output.split())


def test_run_exits_non_zero_and_prints_the_export_error_and_rebuild_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = "context export missing rows for q1/graph-on; q2/graph-off"

    res = _invoke_run(tmp_path, monkeypatch, DriveResult(2, context_export_error=error))

    assert res.exit_code == 1, res.output
    output = _flat(res.output)
    assert error in output
    assert "lancet-eval export-context --run" in output
    assert "run-2026" in output


def test_run_exits_zero_when_the_export_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    res = _invoke_run(tmp_path, monkeypatch, DriveResult(2))

    assert res.exit_code == 0, res.output
    assert "export-context" not in res.output


def test_run_reports_the_export_error_after_a_cap_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    res = _invoke_run(
        tmp_path,
        monkeypatch,
        DriveResult(1, stopped_by_cap=True, context_export_error="export boom"),
    )

    assert res.exit_code == 1, res.output
    assert "export boom" in _flat(res.output)


def test_run_escapes_markup_in_the_export_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    res = _invoke_run(
        tmp_path,
        monkeypatch,
        DriveResult(1, context_export_error="row [q1/graph-on] bad"),
    )

    assert res.exit_code == 1, res.output
    assert "[q1/graph-on]" in _flat(res.output)
