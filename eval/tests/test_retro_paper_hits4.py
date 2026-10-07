"""Tests for eval/scripts/retro_paper_hits4.py: the D-104 read-only dev retro."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

from lancet_eval.config import repo_root

SCRIPT_PATH = repo_root() / "eval" / "scripts" / "retro_paper_hits4.py"


def _load_retro_paper_hits4():
    """Loads the script by file path (a standalone script, not a package member)."""
    spec = importlib.util.spec_from_file_location("retro_paper_hits4", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["retro_paper_hits4"] = module
    spec.loader.exec_module(module)
    return module


_retro = _load_retro_paper_hits4()
build_report = _retro.build_report
main = _retro.main

RUN_DIR = repo_root() / "eval" / "runs" / "2026-10-06-drive2-multihop_rag_diag"
JOURNAL = RUN_DIR / "journal.jsonl"
DIAGNOSTIC = (
    repo_root()
    / ".planning"
    / "phases"
    / "06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair"
    / "diagnostic"
    / "post-reconcile"
)
GOLD_CHUNKS = DIAGNOSTIC / "gold_chunks.jsonl"
POPULATIONS = DIAGNOSTIC / "populations.json"

FORBIDDEN_MODULES = {"lancet_eval.score", "lancet_eval.report"}
ALLOWED_LANCET_MODULES = {
    "lancet_eval.arms",
    "lancet_eval.corpus",
    "lancet_eval.journal",
    "lancet_eval.metrics",
    "lancet_eval.stats",
    "lancet_eval.usability",
}


def _report() -> str:
    return build_report(JOURNAL, GOLD_CHUNKS, POPULATIONS)


def _imported_modules() -> set[str]:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"), filename=str(SCRIPT_PATH))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_build_report_reproduces_68_of_90_hybrid_and_65_of_89_hybrid_plus_graph() -> (
    None
):
    report = _report()
    assert "68/90" in report
    assert "65/89" in report
    assert "hybrid (stored graph-off): 68/90 = 0.7556" in report
    assert "hybrid+graph (stored graph-on): 65/89 = 0.7303" in report
    assert report.count("Wilson 95% CI") >= 2


def test_report_first_line_is_exactly_the_dev_only_label() -> None:
    assert _report().splitlines()[0] == "dev-only, paper-convention @4"


def test_report_carries_no_metric_beyond_rank_four_and_says_why() -> None:
    report = _report()
    for token in ("@10", "MRR", "MAP", "mrr", "map_at"):
        assert token not in report, token
    assert "ranks 1-8" in report
    assert "ranks 9-10 are absent" in report


def test_report_states_the_id_rule_and_the_dev_only_scope() -> None:
    report = _report()
    assert "retrieved_chunks[:4]" in report
    assert "gold_chunks" in report
    assert "D-106" in report
    assert "\\" not in report  # posix paths only


def test_main_writes_only_the_out_file_and_leaves_the_run_directory_unchanged(
    tmp_path: Path,
) -> None:
    tmp_run_dir = tmp_path / RUN_DIR.name
    shutil.copytree(RUN_DIR, tmp_run_dir)
    before = _hash_tree(tmp_run_dir)

    out_path = tmp_path / "retro.md"
    exit_code = main(
        [
            "--journal",
            str(tmp_run_dir / "journal.jsonl"),
            "--gold-chunks",
            str(GOLD_CHUNKS),
            "--populations",
            str(POPULATIONS),
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 0
    assert out_path.read_text(encoding="utf-8").splitlines()[0] == (
        "dev-only, paper-convention @4"
    )
    assert _hash_tree(tmp_run_dir) == before
    assert {p.name for p in tmp_path.iterdir()} == {RUN_DIR.name, "retro.md"}


def test_main_rejects_a_missing_out_argument() -> None:
    with pytest.raises(SystemExit):
        main(["--journal", str(JOURNAL)])


def test_script_imports_no_scoring_or_report_module() -> None:
    imported = _imported_modules()
    forbidden = {
        m
        for m in imported
        if m in FORBIDDEN_MODULES
        or any(m.startswith(f"{forbidden}.") for forbidden in FORBIDDEN_MODULES)
    }
    assert not forbidden, f"forbidden imports found: {forbidden}"


def test_script_never_imports_subprocess() -> None:
    assert "subprocess" not in _imported_modules()


def test_script_imports_only_the_narrow_lancet_surface() -> None:
    lancet = {m for m in _imported_modules() if m.startswith("lancet_eval")}
    assert lancet <= ALLOWED_LANCET_MODULES, lancet - ALLOWED_LANCET_MODULES
    assert "lancet_eval.metrics" in lancet
