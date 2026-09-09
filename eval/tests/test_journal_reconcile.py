"""Tests for journal completeness comparison and header reconciliation."""

import inspect
import json
from pathlib import Path

import pytest

from lancet_eval.corpus import GoldQuestion, load_corpus_config, load_sample_questions
from lancet_eval.journal import (
    RunRecord,
    completeness_comparison,
    journal_key,
    load_done,
    reconcile_header,
)
from lancet_eval.score import score_run


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

    success, msg = reconcile_header(j_path, corpus)
    assert success is True

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


def test_reconcile_incomplete_makes_no_change(tmp_path: Path) -> None:
    """Proves reconciling incomplete journal makes no change and reports missing keys."""
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    j_path = tmp_path / "journal.jsonl"
    _create_synthetic_journal(j_path, corpus, questions, config.arms, partial=True, omit_last=True)

    with open(j_path, "r", encoding="utf-8") as f:
        orig_content = f.read()

    success, msg = reconcile_header(j_path, corpus)
    assert success is False
    assert "missing 1 work unit" in msg

    with open(j_path, "r", encoding="utf-8") as f:
        new_content = f.read()

    assert new_content == orig_content


def test_reconcile_already_publishable_is_noop(tmp_path: Path) -> None:
    """Proves reconciling already-publishable journal is a no-op."""
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    j_path = tmp_path / "journal.jsonl"
    _create_synthetic_journal(j_path, corpus, questions, config.arms, partial=False)

    with open(j_path, "r", encoding="utf-8") as f:
        orig_content = f.read()

    success, msg = reconcile_header(j_path, corpus)
    assert success is True
    assert "already publishable" in msg

    with open(j_path, "r", encoding="utf-8") as f:
        new_content = f.read()

    assert new_content == orig_content


def test_no_public_entrypoint_can_set_partial_true() -> None:
    """Proves reconcile_header cannot be instructed to set partial: True back."""
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
    success, msg = reconcile_header(j_path, corpus)
    assert success is True

    # Score run offline without judge
    report = score_run(run_dir=run_dir, no_judge=True)
    assert report.metadata.partial is False
    assert report_json.is_file(), "report.json must be written on reconciled journal"
