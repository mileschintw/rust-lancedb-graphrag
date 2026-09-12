"""Tests for journal completeness comparison and header reconciliation."""

import inspect
import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from lancet_eval.cli import app
from lancet_eval.corpus import GoldQuestion, load_corpus_config, load_sample_questions
from lancet_eval.journal import (
    RunRecord,
    completeness_comparison,
    journal_key,
    load_done,
    reconcile_header,
)
from lancet_eval.report import ReportError, render_markdown
from lancet_eval.run import drive
from lancet_eval.score import ScoreError, score_run


def _create_synthetic_journal(
    path: Path,
    corpus: str,
    questions: list[GoldQuestion],
    arms: list[str],
    partial: bool = True,
    omit_last: bool = False,
    include_corrupt_middle: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        header = {"type": "header", "corpus": corpus, "partial": partial, "created_at": 1000.0}
        f.write(json.dumps(header) + "\n")

        all_units = [(q, arm) for q in questions for arm in arms]
        if omit_last and all_units:
            all_units = all_units[:-1]

        for i, (q, arm) in enumerate(all_units):
            if include_corrupt_middle and i == len(all_units) // 2:
                f.write('{"corrupted": "bad line"}\n')
                continue
            rec = RunRecord(
                corpus=corpus,
                question_id=q.id,
                graph_arm=arm,
                outcome="success",
                index_generation="gen-1",
            )
            f.write(rec.model_dump_json() + "\n")


def test_completeness_comparison_delegates_to_load_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves completeness comparison delegates to load_done and cannot drift into separate parser."""
    called_load_done = False

    orig_load_done = load_done

    def mock_load_done(p: Path | str) -> set[str]:
        nonlocal called_load_done
        called_load_done = True
        return orig_load_done(p)

    monkeypatch.setattr("lancet_eval.journal.load_done", mock_load_done)

    j_path = tmp_path / "journal.jsonl"
    j_path.write_text('{"type": "header", "corpus": "graphrag_bench", "partial": true}\n')

    is_complete, missing = completeness_comparison(j_path, "graphrag_bench")
    assert called_load_done is True
    assert not is_complete


def test_completeness_comparison_complete_journal(tmp_path: Path) -> None:
    """Proves completeness comparison returns True on full cross-product journal."""
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    j_path = tmp_path / "journal.jsonl"
    _create_synthetic_journal(j_path, corpus, questions, config.arms, partial=True)

    is_complete, missing = completeness_comparison(j_path, corpus)
    assert is_complete is True
    assert len(missing) == 0


def test_completeness_comparison_incomplete_journal_names_missing(tmp_path: Path) -> None:
    """Proves completeness comparison against journal missing 1 unit returns False and names that key."""
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    j_path = tmp_path / "journal.jsonl"
    _create_synthetic_journal(j_path, corpus, questions, config.arms, partial=True, omit_last=True)

    is_complete, missing = completeness_comparison(j_path, corpus)
    assert is_complete is False
    assert len(missing) == 1
    expected_missing_key = journal_key(corpus, questions[-1].id, config.arms[-1])
    assert expected_missing_key in missing


def test_corrupt_middle_line_agreement_with_load_done(tmp_path: Path) -> None:
    """Proves journal with corrupt middle line is handled identically by completeness and load_done."""
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    j_path = tmp_path / "journal.jsonl"
    _create_synthetic_journal(j_path, corpus, questions, config.arms, partial=True, include_corrupt_middle=True)

    done_keys = load_done(j_path)
    is_complete, missing = completeness_comparison(j_path, corpus)
    # The corrupt line didn't form a valid record, so that unit is missing
    assert len(missing) > 0
    for m in missing:
        assert m not in done_keys


def test_reconcile_header_byte_identical_record_lines(tmp_path: Path) -> None:
    """Proves successful reconciliation rewrites ONLY header line and preserves records byte-identical."""
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    j_path = tmp_path / "journal.jsonl"
    _create_synthetic_journal(j_path, corpus, questions, config.arms, partial=True)

    # Read original lines
    with open(j_path, "r", encoding="utf-8") as f:
        orig_lines = f.readlines()

    publishable, changed, msg = reconcile_header(j_path, corpus)
    assert publishable is True
    assert changed is True

    # Read new lines
    with open(j_path, "r", encoding="utf-8") as f:
        new_lines = f.readlines()

    assert len(new_lines) == len(orig_lines)
    # Header differs (partial: true -> false)
    orig_header = json.loads(orig_lines[0])
    new_header = json.loads(new_lines[0])
    assert orig_header["partial"] is True
    assert new_header["partial"] is False

    # Record lines are byte-identical
    assert new_lines[1:] == orig_lines[1:]


def test_reconcile_incomplete_staged_makes_no_change(tmp_path: Path) -> None:
    """Proves reconciling incomplete journal with staged header makes no change and reports missing keys."""
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    j_path = tmp_path / "journal.jsonl"
    _create_synthetic_journal(j_path, corpus, questions, config.arms, partial=True, omit_last=True)

    with open(j_path, "r", encoding="utf-8") as f:
        orig_content = f.read()

    publishable, changed, msg = reconcile_header(j_path, corpus)
    assert publishable is False
    assert changed is False
    assert "missing 1 work unit" in msg

    with open(j_path, "r", encoding="utf-8") as f:
        new_content = f.read()

    assert new_content == orig_content


def test_reconcile_incomplete_publishable_header_corrected_to_staged(tmp_path: Path) -> None:
    """Proves reconciling incomplete journal with publishable header corrects header to staged and preserves records."""
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    j_path = tmp_path / "journal.jsonl"
    _create_synthetic_journal(j_path, corpus, questions, config.arms, partial=False, omit_last=True)

    with open(j_path, "r", encoding="utf-8") as f:
        orig_lines = f.readlines()

    publishable, changed, msg = reconcile_header(j_path, corpus)
    assert publishable is False
    assert changed is True
    assert "missing 1 work unit" in msg

    with open(j_path, "r", encoding="utf-8") as f:
        new_lines = f.readlines()

    assert len(new_lines) == len(orig_lines)
    orig_header = json.loads(orig_lines[0])
    new_header = json.loads(new_lines[0])
    assert orig_header["partial"] is False
    assert new_header["partial"] is True

    # Record lines are byte-identical
    assert new_lines[1:] == orig_lines[1:]


def test_reconcile_already_publishable_is_noop(tmp_path: Path) -> None:
    """Proves reconciling already-publishable journal is a no-op."""
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    j_path = tmp_path / "journal.jsonl"
    _create_synthetic_journal(j_path, corpus, questions, config.arms, partial=False)

    with open(j_path, "r", encoding="utf-8") as f:
        orig_content = f.read()

    publishable, changed, msg = reconcile_header(j_path, corpus)
    assert publishable is True
    assert changed is False
    assert "already publishable" in msg

    with open(j_path, "r", encoding="utf-8") as f:
        new_content = f.read()

    assert new_content == orig_content


def test_cannot_mark_complete_journal_staged_and_no_override_param(tmp_path: Path) -> None:
    """Proves complete journal cannot be marked staged by reconcile, and no override param exists."""
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    j_path = tmp_path / "journal.jsonl"
    _create_synthetic_journal(j_path, corpus, questions, config.arms, partial=False)

    publishable, changed, msg = reconcile_header(j_path, corpus)
    assert publishable is True
    assert changed is False

    with open(j_path, "r", encoding="utf-8") as f:
        header = json.loads(f.readline())
    assert header["partial"] is False

    sig = inspect.signature(reconcile_header)
    param_names = list(sig.parameters.keys())
    assert "partial" not in param_names
    assert "set_partial" not in param_names
    assert "staged" not in param_names
    assert param_names == ["journal_path", "corpus"]


def test_interrupted_write_leaves_original_intact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves interrupted write leaves original journal readable and unchanged."""
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    j_path = tmp_path / "journal.jsonl"
    _create_synthetic_journal(j_path, corpus, questions, config.arms, partial=True)

    with open(j_path, "r", encoding="utf-8") as f:
        orig_content = f.read()

    # Simulate crash during os.replace
    import os
    def failing_replace(src: Path | str, dst: Path | str) -> None:
        raise OSError("Simulated atomic write interruption")

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(OSError, match="Simulated atomic write interruption"):
        reconcile_header(j_path, corpus)

    with open(j_path, "r", encoding="utf-8") as f:
        new_content = f.read()

    assert new_content == orig_content


def test_score_run_on_reconciled_writes_report_json(tmp_path: Path) -> None:
    """Proves score_run writes report.json on a reconciled (publishable) complete journal."""
    corpus = "multihop_rag"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    run_dir = tmp_path / "run_complete"
    j_path = run_dir / "journal.jsonl"
    _create_synthetic_journal(j_path, corpus, questions, config.arms, partial=True)

    # Before reconcile: partial is True
    report_json = run_dir / "report.json"
    assert not report_json.exists()

    # Reconcile
    publishable, changed, msg = reconcile_header(j_path, corpus)
    assert publishable is True
    assert changed is True

    # Score run offline without judge
    report = score_run(run_dir=run_dir, no_judge=True)
    assert report.metadata.partial is False
    assert report_json.is_file(), "report.json must be written on reconciled journal"


def test_reconcile_cli_outcomes(tmp_path: Path) -> None:
    """Proves lancet-eval reconcile CLI handles all three outcomes with correct exit codes."""
    runner = CliRunner()
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    # 1. Complete journal with staged header -> reconciled to publishable (exit 0)
    run_dir_1 = tmp_path / "run_complete_staged"
    j_1 = run_dir_1 / "journal.jsonl"
    _create_synthetic_journal(j_1, corpus, questions, config.arms, partial=True)
    res_1 = runner.invoke(app, ["reconcile", "--run", str(run_dir_1), "--corpus", corpus])
    assert res_1.exit_code == 0
    assert "reconciled" in res_1.output.lower() or "publishable" in res_1.output.lower()

    # 2. Incomplete journal with publishable header -> corrected to staged, still unpublishable (exit 1)
    run_dir_2 = tmp_path / "run_incomplete_publishable"
    j_2 = run_dir_2 / "journal.jsonl"
    _create_synthetic_journal(j_2, corpus, questions, config.arms, partial=False, omit_last=True)
    res_2 = runner.invoke(app, ["reconcile", "--run", str(run_dir_2), "--corpus", corpus])
    assert res_2.exit_code == 1
    assert "corrected" in res_2.output.lower()
    assert "unpublishable" in res_2.output.lower()

    # 3. Incomplete journal with staged header -> rejected unchanged (exit 1)
    run_dir_3 = tmp_path / "run_incomplete_staged"
    j_3 = run_dir_3 / "journal.jsonl"
    _create_synthetic_journal(j_3, corpus, questions, config.arms, partial=True, omit_last=True)
    res_3 = runner.invoke(app, ["reconcile", "--run", str(run_dir_3), "--corpus", corpus])
    assert res_3.exit_code == 1
    assert "reconciliation rejected" in res_3.output.lower()


def test_drive_header_staged_mid_run_and_publishable_on_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves drive() leaves header staged when stopped early and reconciles to publishable on full completion."""
    corpus = "graphrag_bench"
    j_path = tmp_path / "journal.jsonl"

    def mock_drive_one(client, *, corpus, question, arm, partial=False, **kwargs) -> RunRecord:
        return RunRecord(
            corpus=corpus,
            question_id=question.id,
            graph_arm=arm,
            outcome="success",
            index_generation="gen-1",
            partial=partial,
        )

    monkeypatch.setattr("lancet_eval.run.drive_one", mock_drive_one)

    fake_client = httpx.Client(base_url="http://testserver")

    # Step 1: Drive with limit=2 (2 questions x 2 arms = 4 units out of 10)
    res_1 = drive(
        client=fake_client,
        corpus=corpus,
        journal_path=j_path,
        limit=2,
        stage_spend_cap=10.0,
        workers=1,
    )
    assert res_1.executed_count == 4
    with open(j_path, "r", encoding="utf-8") as f:
        hdr_1 = json.loads(f.readline())
    assert hdr_1["partial"] is True, "Header must remain staged when drive is partial"

    # Step 2: Resume with no limit to complete remaining 6 units
    res_2 = drive(
        client=fake_client,
        corpus=corpus,
        journal_path=j_path,
        stage_spend_cap=10.0,
        workers=1,
        resume=True,
    )
    assert res_2.executed_count == 6
    with open(j_path, "r", encoding="utf-8") as f:
        hdr_2 = json.loads(f.readline())
    assert hdr_2["partial"] is False, "Header must be reconciled to publishable on full completion"


def test_drive_resume_no_remaining_units_reconciles_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves drive() on resume with zero remaining units reconciles an un-reconciled header to publishable."""
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)
    j_path = tmp_path / "journal.jsonl"

    # Create synthetic journal with all 10 units complete, but header still staged (partial=True)
    _create_synthetic_journal(j_path, corpus, questions, config.arms, partial=True)

    fake_client = httpx.Client(base_url="http://testserver")

    res = drive(
        client=fake_client,
        corpus=corpus,
        journal_path=j_path,
        stage_spend_cap=10.0,
        workers=1,
        resume=True,
    )
    assert res.executed_count == 0, "No remaining units should be executed"
    with open(j_path, "r", encoding="utf-8") as f:
        hdr = json.loads(f.readline())
    assert hdr["partial"] is False, "Resume with zero remaining units must reconcile header to publishable"


def test_score_run_missing_header_resolves_incomplete(tmp_path: Path) -> None:
    """Proves a journal with no header line scores as incomplete and fails closed."""
    corpus = "multihop_rag"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)[:2]
    run_dir = tmp_path / "no_header"
    j_path = run_dir / "journal.jsonl"
    run_dir.mkdir(parents=True, exist_ok=True)

    with open(j_path, "w", encoding="utf-8") as f:
        for q in questions:
            for arm in config.arms:
                rec = RunRecord(
                    corpus=corpus,
                    question_id=q.id,
                    graph_arm=arm,
                    outcome="success",
                    index_generation="gen-1",
                )
                f.write(rec.model_dump_json() + "\n")

    report = score_run(run_dir=run_dir, no_judge=True)
    assert report.metadata.partial is True
    assert not (run_dir / "report.json").exists()
    with pytest.raises(ReportError):
        render_markdown(report)


def test_score_run_header_missing_partial_key_resolves_incomplete(tmp_path: Path) -> None:
    """Proves a journal whose header omits the 'partial' key scores as incomplete."""
    corpus = "multihop_rag"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)[:2]
    run_dir = tmp_path / "missing_partial_key"
    j_path = run_dir / "journal.jsonl"
    run_dir.mkdir(parents=True, exist_ok=True)

    with open(j_path, "w", encoding="utf-8") as f:
        hdr = {"type": "header", "corpus": corpus, "created_at": 1000.0}
        f.write(json.dumps(hdr) + "\n")
        for q in questions:
            for arm in config.arms:
                rec = RunRecord(
                    corpus=corpus,
                    question_id=q.id,
                    graph_arm=arm,
                    outcome="success",
                    index_generation="gen-1",
                )
                f.write(rec.model_dump_json() + "\n")

    report = score_run(run_dir=run_dir, no_judge=True)
    assert report.metadata.partial is True
    assert not (run_dir / "report.json").exists()


def test_score_run_staged_header_with_complete_records_trusted_as_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves an explicit staged header (partial: true) is trusted even when records are complete."""
    corpus = "multihop_rag"
    config = load_corpus_config(corpus)
    sample_q = load_sample_questions(corpus)[:2]
    monkeypatch.setattr("lancet_eval.corpus.load_sample_questions", lambda c: sample_q)

    run_dir = tmp_path / "staged_complete"
    j_path = run_dir / "journal.jsonl"

    _create_synthetic_journal(j_path, corpus, sample_q, config.arms, partial=True)

    report = score_run(run_dir=run_dir, no_judge=True)
    assert report.metadata.partial is True
    assert not (run_dir / "report.json").exists()


def test_score_run_publishable_header_with_missing_units_resolves_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves publishable header contradicted by missing work units scores as incomplete and notes name missing count."""
    corpus = "multihop_rag"
    config = load_corpus_config(corpus)
    sample_q = load_sample_questions(corpus)[:2]
    monkeypatch.setattr("lancet_eval.corpus.load_sample_questions", lambda c: sample_q)

    run_dir = tmp_path / "falsely_publishable"
    j_path = run_dir / "journal.jsonl"

    _create_synthetic_journal(j_path, corpus, sample_q, config.arms, partial=False, omit_last=True)

    report = score_run(run_dir=run_dir, no_judge=True)
    assert report.metadata.partial is True
    assert not (run_dir / "report.json").exists()
    assert "missing 1 work unit" in report.metadata.notes.lower()


def test_score_run_records_corpus_disagreement_resolves_incomplete(tmp_path: Path) -> None:
    """Proves records disagreeing with header corpus fails closed as incomplete."""
    config = load_corpus_config("multihop_rag")
    questions = load_sample_questions("multihop_rag")[:2]
    run_dir = tmp_path / "corpus_disagreement"
    j_path = run_dir / "journal.jsonl"
    run_dir.mkdir(parents=True, exist_ok=True)

    with open(j_path, "w", encoding="utf-8") as f:
        # Header claims multihop_rag, but records claim other_corpus
        hdr = {"type": "header", "corpus": "multihop_rag", "partial": False, "created_at": 1000.0}
        f.write(json.dumps(hdr) + "\n")
        for q in questions:
            for arm in config.arms:
                rec = RunRecord(
                    corpus="other_corpus",
                    question_id=q.id,
                    graph_arm=arm,
                    outcome="success",
                    index_generation="gen-1",
                )
                f.write(rec.model_dump_json() + "\n")

    report = score_run(run_dir=run_dir, no_judge=True)
    assert report.metadata.partial is True
    assert not (run_dir / "report.json").exists()


def test_score_run_zero_records_raises_score_error(tmp_path: Path) -> None:
    """Proves a journal with zero records still raises the existing ScoreError."""
    run_dir = tmp_path / "empty_journal"
    j_path = run_dir / "journal.jsonl"
    run_dir.mkdir(parents=True, exist_ok=True)
    j_path.write_text('{"type": "header", "corpus": "multihop_rag", "partial": false}\n')

    with pytest.raises(ScoreError, match="contains no evaluation records"):
        score_run(run_dir=run_dir, no_judge=True)

