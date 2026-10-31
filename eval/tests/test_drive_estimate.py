"""The D-258 cost estimate `run` and `run-external` print before a request (#77)."""

from __future__ import annotations

from pathlib import Path

import levers_fixture as fx
import pytest
from typer.testing import CliRunner

from lancet_eval import external_run
from lancet_eval import run as run_mod
from lancet_eval.cli import app
from lancet_eval.drive_estimate import arm_question_usd, drive_estimate, export_estimate
from lancet_eval.measure import (
    EMBEDDING_PRICE_PER_1M,
    ESTIMATED_EMBEDDING_TOKENS_PER_QUERY,
    RERANK_UNREPORTED_CALL_CEILING_USD,
    failed_generation_attempt_usd,
)

GENERATION = failed_generation_attempt_usd()
QUERY_EMBEDDING = ESTIMATED_EMBEDDING_TOKENS_PER_QUERY / 1e6 * EMBEDDING_PRICE_PER_1M


@pytest.mark.parametrize(
    ("arm", "expected"),
    [
        ("bm25-only", GENERATION),
        ("hybrid", GENERATION + QUERY_EMBEDDING),
        (
            "hybrid+rerank+metadata",
            GENERATION + QUERY_EMBEDDING + RERANK_UNREPORTED_CALL_CEILING_USD,
        ),
        (
            "small/hybrid+rerank+metadata",
            GENERATION + QUERY_EMBEDDING + RERANK_UNREPORTED_CALL_CEILING_USD,
        ),
        ("llamaindex", GENERATION),
    ],
)
def test_each_arm_is_priced_at_the_measure_ceilings(arm: str, expected: float) -> None:
    assert arm_question_usd(arm) == pytest.approx(expected)


def test_the_drive_line_multiplies_questions_by_the_arms() -> None:
    arms = ["hybrid", "bm25-only"]
    total = 10 * (arm_question_usd("hybrid") + arm_question_usd("bm25-only"))

    line = drive_estimate(10, arms)

    assert "D-258" in line
    assert "10 question(s) x 2 arm(s)" in line
    assert f"${total:.4f}" in line
    assert "retries" not in line


def test_a_retry_budget_adds_its_bound() -> None:
    total = 4 * arm_question_usd("hybrid")

    line = drive_estimate(4, ["hybrid"], retries=2)

    assert f"${total:.4f}" in line
    assert f"${total * 3:.4f}" in line


def test_the_export_line_prices_indexing_and_each_question() -> None:
    chars = 4_000_000
    indexing = chars / 4 / 1e6 * EMBEDDING_PRICE_PER_1M
    per_question = QUERY_EMBEDDING + RERANK_UNREPORTED_CALL_CEILING_USD

    line = export_estimate(5, chars)

    assert f"${indexing:.4f}" in line
    assert "5 question(s)" in line
    assert f"${indexing + 5 * per_question:.4f}" in line


# --- The commands print it before the first request ----------------------------------


class _Stop(Exception):
    """Raised by a fake drive: the first request would have been sent here."""


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> fx.Questions:
    """The tmp `[split]` corpus with one engine arm and the external arm."""
    qs = fx.make_questions(3, 2)
    root = tmp_path / "repo"
    fx.write_corpus(root, qs, ("hybrid+rerank+metadata", fx.EXTERNAL))
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    return qs


def test_run_prints_the_estimate_before_driving(
    corpus: fx.Questions, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_drive(**_kwargs: object) -> int:
        raise _Stop("first request")

    monkeypatch.setattr(run_mod, "drive", fake_drive)
    monkeypatch.setattr("lancet_eval.cli.load_settings", lambda **_k: object())

    res = CliRunner().invoke(
        app,
        [
            "run",
            "--corpus",
            fx.CORPUS,
            "--arms",
            "hybrid+rerank+metadata",
            "--limit",
            "2",
            "--retries",
            "0",
            "--stage-cap",
            "1",
            "--out",
            str(tmp_path / "run" / "journal.jsonl"),
        ],
    )

    output = res.output.replace("\n", " ")
    assert "D-258" in output
    assert "2 question(s) x 1 arm(s)" in output
    assert output.index("D-258") < output.index("first request")


def test_run_external_prints_the_estimate_before_reading(
    corpus: fx.Questions, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run_external(**_kwargs: object) -> None:
        raise _Stop("first read")

    monkeypatch.setattr(external_run, "run_external", fake_run_external)

    res = CliRunner().invoke(
        app,
        [
            "run-external",
            "--corpus",
            fx.CORPUS,
            "--arm",
            fx.EXTERNAL,
            "--export",
            str(tmp_path / "export.jsonl"),
            "--out",
            str(tmp_path / "run" / "journal.jsonl"),
            "--stage-cap",
            "1",
        ],
    )

    output = res.output.replace("\n", " ")
    assert "5 question(s) x 1 arm(s)" in output
    assert f"all {external_run.EXTERNAL_RETRIES} retries" in output
    assert output.index("D-258") < output.index("first read")
