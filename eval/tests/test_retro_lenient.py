"""Tests for eval/scripts/retro_lenient.py: the D-74 read-only retro."""

from __future__ import annotations

import ast
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from lancet_eval.config import repo_root

SCRIPT_PATH = repo_root() / "eval" / "scripts" / "retro_lenient.py"


def _load_retro_lenient():
    """Loads retro_lenient.py by file path (it is a standalone script, not a
    package member — see the module docstring's import-surface contract)."""
    spec = importlib.util.spec_from_file_location("retro_lenient", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["retro_lenient"] = module
    spec.loader.exec_module(module)
    return module


_retro_lenient = _load_retro_lenient()
build_report = _retro_lenient.build_report
main = _retro_lenient.main

JOURNAL = repo_root() / "eval" / "runs" / "2026-09-09-multihop_rag" / "journal.jsonl"
RUN_DIR = repo_root() / "eval" / "runs" / "2026-09-09-multihop_rag"

FORBIDDEN_MODULES = {
    "lancet_eval.score",
    "lancet_eval.report",
}


def test_build_report_reproduces_91_of_147_whole_token_hits() -> None:
    report = build_report(JOURNAL)
    assert "91/147" in report


def test_build_report_first_line_is_the_partial_run_label() -> None:
    report = build_report(JOURNAL)
    first_line = report.splitlines()[0]
    assert first_line == (
        "partial-run diagnostic (06.3.4 journal, graph-off successes), n=147"
    )


def test_build_report_reproduces_substring_and_d69_numbers() -> None:
    report = build_report(JOURNAL)
    assert "106/150" in report
    assert "0/150" in report  # Answer: line presence
    assert "43/355" in report
    assert "29/42" in report
    assert "14/313" in report
    assert "citation_basis_mixed: 25" in report
    assert "citation_basis_retrieval: 8" in report
    assert "model_only_unsupported: 10" in report


def test_build_report_reproduces_per_type_split() -> None:
    report = build_report(JOURNAL)
    assert "inference_query: 50/51" in report
    assert "comparison_query: 32/68" in report
    assert "temporal_query: 9/28" in report


def test_main_writes_no_report_json_under_a_tmp_copy_of_the_run_dir(
    tmp_path: Path,
) -> None:
    tmp_run_dir = tmp_path / "2026-09-09-multihop_rag"
    shutil.copytree(RUN_DIR, tmp_run_dir)
    tmp_journal = tmp_run_dir / "journal.jsonl"

    out_path = tmp_path / "retro.md"
    exit_code = main(["--journal", str(tmp_journal), "--out", str(out_path)])
    assert exit_code == 0
    assert out_path.is_file()

    for path in tmp_run_dir.rglob("*"):
        assert path.name != "report.json"
        assert path.name != "report.md"


def test_main_rejects_missing_out_argument() -> None:
    with pytest.raises(SystemExit):
        main(["--journal", str(JOURNAL)])


def test_script_imports_no_scoring_or_report_module() -> None:
    """AST inspection: the script must never import lancet_eval.score/report."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SCRIPT_PATH))

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module)

    forbidden_hits = {
        module
        for module in imported_modules
        if module in FORBIDDEN_MODULES
        or any(module.startswith(f"{forbidden}.") for forbidden in FORBIDDEN_MODULES)
    }
    assert not forbidden_hits, f"forbidden imports found: {forbidden_hits}"


def test_script_never_calls_subprocess() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SCRIPT_PATH))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module)
    assert "subprocess" not in imported_modules
