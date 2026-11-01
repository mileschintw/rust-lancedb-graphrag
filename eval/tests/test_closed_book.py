"""The closed-book column of a reader grid (D-291, #163).

`closed_book_init` writes one model-only export row per question and a replay header,
and no record; `batch submit` then sends deepseek's replicates 1 to K and each reader's
answers over those rows, every bin call with model-only answers allowed. The run plan,
corpus, bin and endpoints are fakes (`replay_fixture`, `test_replicates`); nothing is
sent anywhere.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import levers_fixture as fx
import pytest
import replay_fixture as rf
from test_replicates import Endpoint, PinnedBin

from lancet_eval import batch, thresholds
from lancet_eval.closed_book import closed_book_init
from lancet_eval.context_export import CONTEXT_EXPORT_FILE, read_export
from lancet_eval.journal import load_records, read_journal_header
from lancet_eval.pairing import deduplicate_by_arm
from lancet_eval.replay import REPLAY_SOURCE_KEY, ReplayError

pytestmark = pytest.mark.usefixtures("preregistered_clean_tree")

CB = "twowiki/closed-book"
CB_READER = f"{CB}@{rf.READER}"
HYBRID = "twowiki/hybrid+rerank+metadata"


def _plan(source: str = CB) -> thresholds.ReaderGridRunPlan:
    return thresholds.ReaderGridRunPlan(
        benchmark="levers",
        split_file="eval/corpora/levers/split.json",
        split_sha256="a" * 64,
        population="held-out",
        question_count=15,
        columns=(("cb", thresholds.GridColumn(source_arm=source)),),
        readers=((rf.READER, rf.HAIKU),),
        replicates=2,
        reader_replicates=((rf.READER, 1),),
        reference_price=thresholds.ReaderPrice(0.0448, 0.30),
        cells=(("cb", "deepseek", "core"), ("cb", rf.READER, "core")),
        transports=(
            ("deepseek", "engine_drive_then_openrouter_sync"),
            (rf.READER, "openrouter_batch"),
        ),
        rerank_degrade_tripwire_rate=0.20,
        rerank_degrade_tripwire_min_calls=50,
        rerank_consecutive_degrade_halt=5,
        blinding_rule="no score",
        order_rule="any",
        report_rule="run dirs",
        provenance="test",
    )


class ModelOnlyBin(PinnedBin):
    """`PinnedBin` that records the `model_only` flag of every call."""

    def __init__(self) -> None:
        super().__init__()
        self.model_only: list[tuple[str, bool]] = []

    def __call__(self, mode, rows, levers, results=None, *, model_only=False):  # type: ignore[no-untyped-def]
        self.model_only.append((mode, model_only))
        return super().__call__(mode, rows, levers, results)


def _setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source: str = CB,
    column: bool = True,
) -> tuple[Path, fx.Questions, Endpoint, ModelOnlyBin]:
    qs = fx.make_questions(6, 2)
    root = tmp_path / "repo"
    arms = (source, f"{source}@{rf.READER}")
    fx.write_corpus(root, qs, arms, role="heldout")
    toml = root / "eval" / "corpora" / f"{fx.CORPUS}.toml"
    extra = 'column = "cb"\n' if column else ""
    extra += (
        '[stores.twowiki]\nchunk_strategy = "fixed-size"\nchunk_size = 8192\n'
        "chunk_overlap = 0\n"
    )
    toml.write_text(toml.read_text(encoding="utf-8") + extra, encoding="utf-8")
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    # The fixture split records placeholder input hashes (as in test_run_external).
    monkeypatch.setattr("lancet_eval.run.split_input_problems", lambda *_a: [])
    monkeypatch.setattr(thresholds, fx.TOKEN, _plan(source), raising=False)
    endpoint = Endpoint({q: a for q, _, a in qs.g})
    binary = ModelOnlyBin()
    monkeypatch.setattr(batch, "client_factory", lambda target: endpoint)
    monkeypatch.setattr(batch, "chat_client_factory", lambda: endpoint)
    monkeypatch.setattr(batch, "bin_runner", binary)
    return tmp_path / "run", qs, endpoint, binary


def _all(qs: fx.Questions) -> list[str]:
    return [*qs.g_ids, *qs.nulls]


def test_closed_book_init_writes_a_model_only_row_per_question_and_no_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, qs, _, binary = _setup(tmp_path, monkeypatch)
    result = closed_book_init(run=run, corpus=fx.CORPUS)
    assert (result.records, result.rows) == (0, len(_all(qs)))
    rows = read_export(run / CONTEXT_EXPORT_FILE)
    assert sorted(r.question_id for r in rows) == sorted(_all(qs))
    assert all(r.arm == CB and r.evidence == [] and r.graph_facts == [] for r in rows)
    assert all(r.correlation_id == f"closed-book-{r.question_id}" for r in rows)
    assert all(r.assembled_prompt for r in rows)
    assert binary.model_only == [("pack", True)]
    header = read_journal_header(run / "journal.jsonl")
    source = header[REPLAY_SOURCE_KEY]
    assert source["closed_book"] is True and source["arms"] == [CB]
    assert set(source["row_sha256"][CB]) == set(_all(qs))
    assert load_records(run / "journal.jsonl") == []


def test_every_cell_of_the_column_is_read_with_model_only_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, qs, endpoint, binary = _setup(tmp_path, monkeypatch)
    closed_book_init(run=run, corpus=fx.CORPUS)
    batch.submit(run=run, arm=CB, echo=lambda _: None)
    batch.submit(run=run, arm=CB_READER, echo=lambda _: None)
    batch.fetch(run=run, echo=lambda _: None)
    records, _ = deduplicate_by_arm(load_records(run / "journal.jsonl"))
    units: dict[str, set[tuple[str, int]]] = {}
    for r in records:
        assert r.outcome == "success", (r.graph_arm, r.question_id, r.error)
        units.setdefault(r.graph_arm, set()).add((r.question_id, r.replicate))
    assert units[CB] == {(q, k) for q in _all(qs) for k in (1, 2)}
    assert units[CB_READER] == {(q, 1) for q in _all(qs)}
    assert len(endpoint.sync_calls) == 2 * len(_all(qs))
    assert binary.model_only and all(flag for _, flag in binary.model_only)
    levers = {tuple(call[2]) for call in binary.calls}
    assert levers == {()}


def test_closed_book_init_refuses_a_corpus_without_a_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _, _, _ = _setup(tmp_path, monkeypatch, column=False)
    with pytest.raises(ReplayError, match="D-237"):
        closed_book_init(run=run, corpus=fx.CORPUS)
    assert not (run / "journal.jsonl").exists()


def test_closed_book_init_refuses_a_column_with_a_drive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _, _, _ = _setup(tmp_path, monkeypatch, source=HYBRID)
    with pytest.raises(ReplayError, match="not the closed-book arm"):
        closed_book_init(run=run, corpus=fx.CORPUS)
    assert not (run / "journal.jsonl").exists()


def test_closed_book_init_refuses_a_row_the_bin_cannot_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, qs, _, _ = _setup(tmp_path, monkeypatch)

    def failing(mode: str, rows: Any, levers: Any, results: Any = None, **_: Any):  # type: ignore[no-untyped-def]
        return [
            {
                "question_id": r.question_id,
                "arm": r.arm,
                "outcome": "error",
                "error": "no evidence fits",
            }
            for r in rows
        ]

    monkeypatch.setattr(batch, "bin_runner", failing)
    with pytest.raises(ReplayError, match="did not pack") as excinfo:
        closed_book_init(run=run, corpus=fx.CORPUS)
    assert qs.g_ids[0] in str(excinfo.value)
    assert not (run / "journal.jsonl").exists()


def test_the_real_runner_sets_the_model_only_setting_only_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lancet_eval import parity

    seen: list[dict[str, str] | None] = []

    class Done:
        returncode = 0
        stdout = json.dumps({"question_id": "q", "arm": "a", "outcome": "success"})
        stderr = ""

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs.get("env"))
        return Done()

    monkeypatch.setattr(parity.subprocess, "run", fake_run)
    parity.run_bin("pack", [], [])
    parity.run_bin("pack", [], [], model_only=True)
    assert seen[0] is None
    assert seen[1] is not None and seen[1][parity.MODEL_ONLY_ENV] == "true"


def test_no_run_of_a_run_plan_is_scored_or_read_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval import evidence_split, explore_readout
    from lancet_eval.lever_comparison import (
        LeverComparisonError,
        build_lever_comparison,
    )
    from lancet_eval.score import ScoreError, score_run

    run, _, _, _ = _setup(tmp_path, monkeypatch)
    closed_book_init(run=run, corpus=fx.CORPUS)
    batch.submit(run=run, arm=CB, echo=lambda _: None)
    with pytest.raises(ScoreError, match="D-291"):
        score_run(run_dir=run, no_judge=True)
    with pytest.raises(LeverComparisonError, match="D-291"):
        build_lever_comparison(run)
    for module in (explore_readout, evidence_split):
        with pytest.raises(SystemExit, match="D-291"):
            module.main(["--run", str(run), "--corpus", fx.CORPUS])


def test_no_judge_or_gate_reads_a_run_of_a_run_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lancet_eval import judge_stage, unpark_gates
    from lancet_eval.answer_judge import AnswerJudgeError, judge_answers
    from lancet_eval.diagnostic import DiagnosticError, build_rows

    run, _, _, _ = _setup(tmp_path, monkeypatch)
    closed_book_init(run=run, corpus=fx.CORPUS)
    batch.submit(run=run, arm=CB, echo=lambda _: None)
    with pytest.raises(AnswerJudgeError, match="D-291"):
        judge_answers(run, estimate_only=True, echo=lambda _: None)
    with pytest.raises(judge_stage.JudgeStageError, match="D-291"):
        judge_stage.load_inputs(run)
    with pytest.raises(SystemExit):
        unpark_gates.main([
            "--stage",
            unpark_gates.HELDOUT_STAGE,
            "--run",
            str(run),
            "--engine-pid-before",
            "1",
            "--engine-pid-after",
            "1",
            "--out",
            str(tmp_path / "gates.json"),
        ])
    assert "D-291" in capsys.readouterr().err
    assert not (tmp_path / "gates.json").exists()
    with pytest.raises(DiagnosticError, match="D-291"):
        build_rows(fx.CORPUS, run / "journal.jsonl", tmp_path / "gold.json")


def test_the_estimate_counts_output_before_deepseek_has_answered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, _, _, _ = _setup(tmp_path, monkeypatch)
    closed_book_init(run=run, corpus=fx.CORPUS)
    lines: list[str] = []
    batch.submit(run=run, arm=CB_READER, echo=lines.append)
    [estimate] = [line for line in lines if line.startswith("Cost estimate")]
    expected = float(estimate.split("about $")[1].split(" ")[0])
    bound = float(estimate.split("at most $")[1].split(" ")[0])
    assert expected > 0 and expected == bound
