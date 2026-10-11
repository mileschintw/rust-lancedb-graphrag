"""06.4 D-200 / D-201: the committed re-score equality checker."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_rescore.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("compare_rescore", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(**metadata: Any) -> dict[str, Any]:
    base_metadata: dict[str, Any] = {
        "result_hash": "abc123",
        "commit_sha": "5f8324fe",
        "run_date": "2026-10-10T16:47:29+00:00",
        "dependency_lock_hash": "8e71ea9ce7a3532b",
        "corpus": "multihop_rag_levers_heldout",
    }
    base_metadata.update(metadata)
    return {
        "dimensions": {"hybrid": {"recall": 0.5}, "hybrid+graph": {"recall": 0.6}},
        "metadata": base_metadata,
    }


def _write_run(directory: Path, report: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return directory


def _pair(
    tmp_path: Path,
    rescored: dict[str, Any],
    committed: dict[str, Any] | None = None,
) -> tuple[Path, Path]:
    return (
        _write_run(tmp_path / "committed", committed or _report()),
        _write_run(tmp_path / "rescored", rescored),
    )


def _run(committed: Path, rescored: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(committed), str(rescored)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_d200_compare_rescore_equal_dirs_exit_0(tmp_path: Path) -> None:
    committed, rescored = _pair(tmp_path, _report())

    proc = _run(committed, rescored)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "re-score reproduces the published values" in proc.stdout


def test_d200_compare_rescore_a_differing_dimension_exits_1(tmp_path: Path) -> None:
    changed = _report()
    changed["dimensions"]["hybrid"]["recall"] = 0.51
    committed, rescored = _pair(tmp_path, changed)

    proc = _run(committed, rescored)

    assert proc.returncode == 1
    assert "dimensions" in proc.stdout
    assert "reproduces the published values" not in proc.stdout


def test_d200_compare_rescore_a_differing_result_hash_exits_1(tmp_path: Path) -> None:
    committed, rescored = _pair(tmp_path, _report(result_hash="zzz999"))

    proc = _run(committed, rescored)

    assert proc.returncode == 1
    assert "result_hash" in proc.stdout


@pytest.mark.parametrize(
    "key,value",
    [
        ("run_date", "2026-10-11T02:15:38+00:00"),
        ("commit_sha", "8c26f0cc"),
        ("dependency_lock_hash", "b92e433bda70a6de"),
    ],
)
def test_d200_compare_rescore_allowed_metadata_differences_exit_0(
    tmp_path: Path, key: str, value: str
) -> None:
    committed, rescored = _pair(tmp_path, _report(**{key: value}))

    proc = _run(committed, rescored)

    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_d200_compare_rescore_all_three_allowed_keys_together_exit_0(
    tmp_path: Path,
) -> None:
    committed, rescored = _pair(
        tmp_path,
        _report(
            run_date="2026-10-11",
            commit_sha="8c26f0cc",
            dependency_lock_hash="b92e433bda70a6de",
        ),
    )

    assert _run(committed, rescored).returncode == 0


def test_d200_compare_rescore_another_metadata_key_exits_1_and_names_it(
    tmp_path: Path,
) -> None:
    committed, rescored = _pair(tmp_path, _report(corpus="another_corpus"))

    proc = _run(committed, rescored)

    assert proc.returncode == 1
    assert "corpus" in proc.stdout


def test_d200_compare_rescore_a_metadata_key_present_on_one_side_only_exits_1(
    tmp_path: Path,
) -> None:
    committed, rescored = _pair(tmp_path, _report(extra_key="x"))

    proc = _run(committed, rescored)

    assert proc.returncode == 1
    assert "extra_key" in proc.stdout


def test_d200_compare_rescore_reports_every_failing_reason(tmp_path: Path) -> None:
    changed = _report(result_hash="zzz999", corpus="another_corpus")
    changed["dimensions"]["hybrid"]["recall"] = 0.51
    committed, rescored = _pair(tmp_path, changed)

    proc = _run(committed, rescored)

    assert proc.returncode == 1
    assert "dimensions" in proc.stdout
    assert "result_hash" in proc.stdout
    assert "corpus" in proc.stdout


def test_d200_compare_rescore_missing_report_exits_1(tmp_path: Path) -> None:
    committed = _write_run(tmp_path / "committed", _report())
    empty = tmp_path / "rescored"
    empty.mkdir()

    proc = _run(committed, empty)

    assert proc.returncode == 1
    assert "report.json" in proc.stdout + proc.stderr


def test_d200_compare_rescore_usage_error_exits_2() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert proc.returncode == 2


def test_d200_compare_rescore_writes_nothing_in_either_directory(
    tmp_path: Path,
) -> None:
    committed, rescored = _pair(tmp_path, _report(run_date="2026-10-11"))
    before = {
        d: sorted((p.name, p.read_bytes()) for p in d.iterdir())
        for d in (committed, rescored)
    }

    assert _run(committed, rescored).returncode == 0

    after = {
        d: sorted((p.name, p.read_bytes()) for p in d.iterdir())
        for d in (committed, rescored)
    }
    assert before == after


def test_d200_compare_rescore_imports_only_the_standard_library() -> None:
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names), imported
    assert {"json", "sys", "pathlib"} >= imported - {"__future__"}


def test_d200_compare_rescore_allowed_keys_are_exactly_the_three() -> None:
    assert _load_script().ALLOWED_METADATA_DIFFERENCES == frozenset({
        "commit_sha",
        "run_date",
        "dependency_lock_hash",
    })
