"""06.4 D-212 IN-05: gen_paper_golden.py verifies the fetched file before exec."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen_paper_golden.py"
FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "multihop_rag_calculate_metrics_golden.json"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_paper_golden", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sentinel_file(tmp_path: Path) -> tuple[Path, Path]:
    """A stand-in 'official' file that records, on disk, that it was executed."""
    sentinel = tmp_path / "executed.sentinel"
    official = tmp_path / "retrieval_evaluate.py"
    official.write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('ran', encoding='utf-8')\n"
        "def calculate_metrics(*args, **kwargs):\n"
        "    return {}\n",
        encoding="utf-8",
    )
    return official, sentinel


def test_d212_in05_mismatched_file_is_refused_before_exec(tmp_path: Path) -> None:
    script = _load_script()
    official, sentinel = _sentinel_file(tmp_path)
    actual = hashlib.sha256(official.read_bytes()).hexdigest()
    assert actual != script.OFFICIAL_FILE_SHA256

    with pytest.raises(SystemExit) as excinfo:
        script.load_official(official)

    message = str(excinfo.value)
    assert script.OFFICIAL_FILE_SHA256 in message
    assert actual in message
    assert not sentinel.exists(), "the unverified file was executed"


def test_d212_in05_a_matching_file_is_executed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _load_script()
    official, sentinel = _sentinel_file(tmp_path)
    monkeypatch.setattr(
        script,
        "OFFICIAL_FILE_SHA256",
        hashlib.sha256(official.read_bytes()).hexdigest(),
    )

    module = script.load_official(official)

    assert sentinel.read_text(encoding="utf-8") == "ran"
    assert hasattr(module, "calculate_metrics")


def test_d212_in05_pinned_hash_equals_the_fixture_header() -> None:
    header = json.loads(FIXTURE.read_text(encoding="utf-8"))["header"]

    assert _load_script().OFFICIAL_FILE_SHA256 == header["official_file_sha256"]
