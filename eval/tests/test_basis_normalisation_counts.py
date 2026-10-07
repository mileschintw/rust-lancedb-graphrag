"""Tests for `eval/scripts/basis_normalisation_counts.py` (06.3.5-18 Task 2).

The engine accepts a cited grounded abstention that the model labelled `model_only`,
and discloses each one with a fixed `BASIS_RECONCILED` notice (owner condition 4). The
script counts those records, and the residual `model_only` rejections, per canonical
arm and per `question_type` from the journal alone. It is read-only: it never opens a
run file for writing.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from lancet_eval.config import repo_root
from lancet_eval.corpus import load_sample_questions
from lancet_eval.journal import RunRecord

SCRIPT_PATH = repo_root() / "eval" / "scripts" / "basis_normalisation_counts.py"
ENGINE_GENERATION_SOURCE = repo_root() / "engine" / "src" / "generation" / "mod.rs"
DRIVE2_DIR = repo_root() / "eval" / "runs" / "2026-10-06-drive2-multihop_rag_diag"
REHEARSAL_CORPUS = "multihop_rag_rehearsal"
ARMS = ["dense-only", "bm25-only", "hybrid", "hybrid+graph"]
ABSTAINING_ANSWER = "Checked blocks [1] and [2].\nAnswer: Insufficient information"


def _load_script() -> Any:
    """Loads the script by file path (a standalone script, not a package member)."""
    spec = importlib.util.spec_from_file_location(
        "basis_normalisation_counts", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["basis_normalisation_counts"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()

NORMALISED_NOTICE = {
    "code": "BASIS_RECONCILED",
    "typed_code": 15,
    "message": script.NORMALISED_NOTICE_MESSAGE,
}


def _record(
    question_id: str,
    arm: str,
    *,
    kind: str = "plain",
    corpus: str = REHEARSAL_CORPUS,
) -> RunRecord:
    """One journal record of the given kind, keyed `cid-<question>-<arm>`."""
    base: dict[str, Any] = {
        "corpus": corpus,
        "question_id": question_id,
        "graph_arm": arm,
        "correlation_id": f"cid-{question_id}-{arm}",
    }
    if kind == "normalised":
        return RunRecord(
            **base,
            outcome="success",
            answer=ABSTAINING_ANSWER,
            notices=[NORMALISED_NOTICE],
        )
    if kind == "normalised_but_answers":
        return RunRecord(
            **base,
            outcome="success",
            answer="A committed answer [1].\nAnswer: Yes",
            notices=[NORMALISED_NOTICE],
        )
    if kind == "rejected":
        return RunRecord(
            **base,
            outcome="error",
            node_failures=[
                {
                    "node_name": "GenerateAnswer",
                    "error_kind": 0,
                    "error_message": script.MODEL_ONLY_REJECTION,
                    "retryable": False,
                }
            ],
        )
    if kind == "other_error":
        return RunRecord(
            **base,
            outcome="error",
            node_failures=[
                {
                    "node_name": "ExtractGraphContext",
                    "error_kind": 0,
                    "error_message": "Query embedding timed out",
                    "retryable": True,
                }
            ],
        )
    if kind == "d18_reconciled":
        return RunRecord(
            **base,
            outcome="success",
            answer="Prose [1].\nAnswer: Yes",
            notices=[
                {
                    "code": "BASIS_RECONCILED",
                    "typed_code": 15,
                    "message": (
                        "model self-reported basis 'retrieval' but the engine observed "
                        "'model_only'; reconciled to the more conservative basis "
                        "'model_only'"
                    ),
                }
            ],
        )
    return RunRecord(
        **base, outcome="success", answer="Prose [1].\nAnswer: Yes", notices=[]
    )


def _types(question_ids: list[str], types: list[str]) -> dict[str, str]:
    return dict(zip(question_ids, types, strict=True))


def _synthetic() -> tuple[list[RunRecord], dict[str, str]]:
    """Four arms over three questions, with a known mix of record kinds."""
    records = [
        _record("q1", "dense-only", kind="normalised"),
        _record("q2", "graph-on", kind="normalised"),  # legacy alias of hybrid+graph
        _record("q1", "bm25-only", kind="rejected"),
        _record("q3", "hybrid", kind="d18_reconciled"),  # code 15, other message
        _record("q2", "dense-only"),
        _record("q3", "bm25-only", kind="other_error"),
        _record("q1", "hybrid"),
        _record("q3", "hybrid+graph"),
    ]
    return records, _types(["q1", "q2", "q3"], ["temporal", "comparison", "null"])


def test_counts_are_exact_per_arm_and_per_question_type() -> None:
    records, types = _synthetic()

    counts = script.count_records(records, types)

    assert counts["records"] == 8
    assert counts["arms"] == ARMS
    assert counts["question_types"] == ["comparison", "null", "temporal"]
    assert counts["normalised"]["total"] == 2
    assert counts["normalised"]["by_arm"] == {
        "dense-only": 1,
        "bm25-only": 0,
        "hybrid": 0,
        "hybrid+graph": 1,
    }
    assert counts["normalised"]["by_arm_question_type"] == {
        "dense-only": {"comparison": 0, "null": 0, "temporal": 1},
        "bm25-only": {"comparison": 0, "null": 0, "temporal": 0},
        "hybrid": {"comparison": 0, "null": 0, "temporal": 0},
        "hybrid+graph": {"comparison": 1, "null": 0, "temporal": 0},
    }
    assert counts["model_only_rejected"]["total"] == 1
    assert counts["model_only_rejected"]["by_arm"] == {
        "dense-only": 0,
        "bm25-only": 1,
        "hybrid": 0,
        "hybrid+graph": 0,
    }
    assert counts["model_only_rejected"]["by_arm_question_type"]["bm25-only"] == {
        "comparison": 0,
        "null": 0,
        "temporal": 1,
    }
    assert counts["normalised_not_abstaining"] == 0


def test_a_code_15_notice_with_another_message_is_not_counted() -> None:
    # The D-18 reconciliation notice shares typed code 15 but not the fixed message.
    records = [_record("q1", "hybrid", kind="d18_reconciled")]

    counts = script.count_records(records, {"q1": "temporal"})

    assert counts["normalised"]["total"] == 0
    assert counts["rows"] == []


def test_only_a_generate_answer_model_only_failure_is_a_residual_rejection() -> None:
    records = [
        _record("q1", "hybrid", kind="other_error"),
        _record("q2", "hybrid", kind="rejected"),
    ]

    counts = script.count_records(records, {"q1": "temporal", "q2": "temporal"})

    assert counts["model_only_rejected"]["total"] == 1
    assert [row["question_id"] for row in counts["rows"]] == ["q2"]
    assert counts["rows"][0]["kind"] == "model_only_rejected"


def test_rows_name_every_classified_record_in_journal_order() -> None:
    records, types = _synthetic()

    rows = script.count_records(records, types)["rows"]

    assert [(row["question_id"], row["arm"], row["kind"]) for row in rows] == [
        ("q1", "dense-only", "normalised"),
        ("q2", "hybrid+graph", "normalised"),
        ("q1", "bm25-only", "model_only_rejected"),
    ]
    assert rows[1]["question_type"] == "comparison"
    assert rows[1]["correlation_id"] == "cid-q2-graph-on"
    assert [row["harness_abstains"] for row in rows] == [True, True, False]


def test_an_unknown_arm_label_raises() -> None:
    records = [_record("q1", "hybrid"), _record("q1", "no-such-arm")]

    with pytest.raises(ValueError, match="no-such-arm"):
        script.count_records(records, {"q1": "temporal"})


def test_a_question_absent_from_its_corpus_raises_naming_the_id() -> None:
    records = [_record("q1", "hybrid"), _record("q-missing", "hybrid")]

    with pytest.raises(ValueError, match="q-missing"):
        script.count_records(records, {"q1": "temporal"})


def test_a_normalised_record_that_does_not_abstain_is_flagged() -> None:
    records = [
        _record("q1", "hybrid", kind="normalised"),
        _record("q2", "hybrid", kind="normalised_but_answers"),
    ]

    counts = script.count_records(records, {"q1": "temporal", "q2": "temporal"})

    assert counts["normalised"]["total"] == 2
    assert counts["normalised_not_abstaining"] == 1
    assert [row["harness_abstains"] for row in counts["rows"]] == [True, False]


def _engine_literal(pattern: str) -> str:
    source = ENGINE_GENERATION_SOURCE.read_text(encoding="utf-8")
    found = re.search(pattern, source, flags=re.DOTALL)
    assert found is not None, f"engine source has no match for {pattern!r}"
    literal = found.group(1)
    assert "\\" not in literal, "a Rust escape would make byte equality ambiguous"
    return literal


def test_the_notice_message_equals_the_engine_constant() -> None:
    engine = _engine_literal(
        r'pub const GROUNDED_ABSTENTION_NORMALISED_NOTICE: &str = "([^"\n]*)";'
    )

    assert script.NORMALISED_NOTICE_MESSAGE == engine


def test_the_rejection_message_equals_the_engine_validation_message() -> None:
    engine = _engine_literal(
        r"fn validate_output_shape_with_limits.*?SchemaValidation,\s*\"([^\"]*)\""
    )

    assert script.MODEL_ONLY_REJECTION == engine


def test_the_drive_2_journal_reads_zero_normalised_and_two_rejections(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "out"

    exit_code = script.main([str(DRIVE2_DIR), "--out-dir", str(out_dir)])

    assert exit_code == 0
    data = json.loads((out_dir / script.OUT_NAME).read_text(encoding="utf-8"))
    assert data["records"] == 200
    assert data["arms"] == ["hybrid", "hybrid+graph"]
    assert data["normalised"]["total"] == 0
    assert data["model_only_rejected"]["total"] == 2
    assert data["model_only_rejected"]["by_arm"] == {"hybrid": 1, "hybrid+graph": 1}
    assert {row["question_id"] for row in data["rows"]} == {"mhr-dd03ecc9ba3d"}
    assert {row["question_type"] for row in data["rows"]} == {"null_query"}
    assert data["normalised_not_abstaining"] == 0
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", str(DRIVE2_DIR)],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout.strip() == ""


def _write_journal(run_dir: Path, records: list[RunRecord]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    journal = run_dir / "journal.jsonl"
    with open(journal, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"type": "header", "corpus": REHEARSAL_CORPUS}) + "\n")
        for record in records:
            handle.write(record.model_dump_json() + "\n")
    return journal


def test_a_run_never_changes_the_journal_and_writes_one_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    question_ids = [q.question_id for q in load_sample_questions(REHEARSAL_CORPUS)]
    records = [
        _record(question_ids[0], "dense-only", kind="normalised"),
        _record(question_ids[1], "bm25-only", kind="rejected"),
        _record(question_ids[2], "hybrid"),
        _record(question_ids[0], "hybrid+graph"),
    ]
    run_dir = tmp_path / "run"
    journal = _write_journal(run_dir, records)
    before = hashlib.sha256(journal.read_bytes()).hexdigest()
    out_dir = tmp_path / "diagnostic"

    assert script.main([str(run_dir), "--out-dir", str(out_dir)]) == 0

    assert hashlib.sha256(journal.read_bytes()).hexdigest() == before
    assert [p.name for p in out_dir.iterdir()] == [script.OUT_NAME]
    assert sorted(p.name for p in run_dir.iterdir()) == ["journal.jsonl"]
    text = (out_dir / script.OUT_NAME).read_text(encoding="utf-8")
    assert text.endswith("\n")
    data = json.loads(text)
    assert data["normalised"]["total"] == 1
    assert data["model_only_rejected"]["total"] == 1
    table_lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("| ") and "---" not in line
    ]
    # One header row, then one row per arm present.
    assert [line.split("|")[1].strip() for line in table_lines[1:]] == [
        "dense-only",
        "bm25-only",
        "hybrid",
        "hybrid+graph",
    ]


def test_the_default_out_dir_is_the_diagnostic_directory_of_the_run(
    tmp_path: Path,
) -> None:
    question_ids = [q.question_id for q in load_sample_questions(REHEARSAL_CORPUS)]
    run_dir = tmp_path / "run"
    _write_journal(run_dir, [_record(question_ids[0], "hybrid")])

    assert script.main([str(run_dir)]) == 0

    assert (run_dir / "diagnostic" / script.OUT_NAME).is_file()


def test_a_run_without_a_journal_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main([str(tmp_path)]) == 2
    assert "journal" in capsys.readouterr().err
