"""Real-data checks for the unpark gates (06.3.4.1-32, G-06.3.4.1-3a, CR-02/WR-04).

Two things are pinned against the recorded drives, never against synthetic fixtures:

* a truncated copy of the drive-2 journal (an honest `partial: true` header, no
  `report.json`) reads MISS on every reading through `main`; and
* the recorded drive 1, 1b and 2 verdicts are unchanged when the gates are re-read
  under the current code.

Everything is written under `tmp_path`. Nothing here creates, modifies or deletes a
file under `eval/runs/`; the recorded journals and `gates-*` files are hashed before
and after to prove it. A re-read is a labelled disclosure
(`REREAD-<stage>-disclosure.md`), not a gate verdict (D-73: the recorded gates were
read under the literals committed before each drive).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from lancet_eval import thresholds
from lancet_eval.config import repo_root
from lancet_eval.unpark_gates import main

_PHASE_DIR = (
    ".planning/phases/"
    "06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair"
)
_GOLD_CHUNKS = f"{_PHASE_DIR}/diagnostic/post-reconcile/gold_chunks.jsonl"
_POPULATIONS = "eval/corpora/multihop_rag/diag_selection.json"
_DRIVE1 = "eval/runs/2026-09-30-drive1-multihop_rag_diag"
_DRIVE1B = "eval/runs/2026-10-01-drive1b-multihop_rag_diag"
_DRIVE2 = "eval/runs/2026-10-06-drive2-multihop_rag_diag"

#: stage -> (run dir, engine PID before/after as recorded, baseline run for drive 2).
_RECORDED: dict[str, tuple[str, int, str | None]] = {
    "drive1": (_DRIVE1, 2316, None),
    "drive1b": (_DRIVE1B, 35940, None),
    "drive2": (_DRIVE2, 7372, _DRIVE1B),
}

_READINGS = ("SC-1", "SC-2", "D-69 companion", "SC-3", "SC-4", "SC-5")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _args(
    stage: str, run: Path, baseline: Path | None, out: Path, pid: int
) -> list[str]:
    root = repo_root()
    args = [
        "--stage",
        stage,
        "--run",
        str(run),
        "--gold-chunks",
        str(root / _GOLD_CHUNKS),
        "--populations",
        str(root / _POPULATIONS),
        "--engine-pid-before",
        str(pid),
        "--engine-pid-after",
        str(pid),
        "--out",
        str(out),
    ]
    if baseline is not None:
        args += ["--baseline-run", str(baseline)]
    return args


def _drive2_truncation(tmp_path: Path, n_records: int) -> Path:
    """The drive-2 journal cut to its first `n_records` records, header partial=true,
    and no `report.json`: what a drive halted early leaves on disk (marked)."""
    source = repo_root() / _DRIVE2 / "journal.jsonl"
    lines = source.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    assert header["type"] == "header"
    header["partial"] = True
    # A truncation no longer matches the registered record digest (WR-01), so carry the
    # gate-stage marker a --gate-stage drive writes: the readings then fail on the
    # missing units alone, which is what these tests pin.
    header["gate_stage"] = "drive2"
    header["max_retries"] = 0
    run = tmp_path / "run"
    run.mkdir()
    with open(run / "journal.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(header) + "\n")
        for line in lines[1 : 1 + n_records]:
            f.write(line + "\n")
    return run


@pytest.mark.parametrize(("n_records", "missing"), [(40, 160), (2, 198)])
def test_a_truncated_drive2_journal_reads_miss_on_every_reading(
    tmp_path: Path, n_records: int, missing: int
) -> None:
    run = _drive2_truncation(tmp_path, n_records)
    out = tmp_path / "out" / "REREAD-drive2-truncated-disclosure.md"
    baseline = repo_root() / _DRIVE1B

    code = main(_args("drive2", run, baseline, out, 7372))

    assert code == 0
    payload = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    for name in _READINGS:
        assert payload[name]["status"] == "MISS", (name, payload[name]["reason"])
    reason = f"journal incomplete: {missing} work unit(s) missing"
    for name in _READINGS[1:]:
        assert payload[name]["reason"] == reason, name
    assert reason in payload["SC-1"]["reason"]
    assert payload["SC-1"]["detail"]["journal_complete"] is False
    assert payload["graph-off invariance"] == {"not_computed": reason}


def _recorded_gates(stage: str) -> dict[str, Any]:
    run, _, _ = _RECORDED[stage]
    path = repo_root() / run / f"gates-{stage}.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def _rereads(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """Re-read each recorded drive once, hashing the recorded files around the run."""
    root = repo_root()
    results: dict[str, dict[str, Any]] = {}
    for stage, (run, pid, baseline) in _RECORDED.items():
        run_dir = root / run
        watched = [
            run_dir / "journal.jsonl",
            run_dir / f"gates-{stage}.md",
            run_dir / f"gates-{stage}.json",
        ]
        before = {path: _sha256(path) for path in watched}
        out = tmp_path_factory.mktemp(stage) / f"REREAD-{stage}-disclosure.md"
        code = main(
            _args(stage, run_dir, root / baseline if baseline else None, out, pid)
        )
        assert code == 0
        assert {path: _sha256(path) for path in watched} == before, (
            f"{stage}: a recorded file changed"
        )
        results[stage] = json.loads(out.with_suffix(".json").read_text("utf-8"))
    return results


@pytest.mark.parametrize("stage", list(_RECORDED))
def test_the_recorded_verdicts_are_unchanged_on_a_reread(
    _rereads: dict[str, dict[str, Any]], stage: str
) -> None:
    recorded = _recorded_gates(stage)
    reread = _rereads[stage]
    assert list(reread) == list(recorded)
    gated = [name for name, entry in recorded.items() if "status" in entry]
    assert gated
    for name in gated:
        for field in ("status", "n", "value"):
            assert reread[name][field] == recorded[name][field], (stage, name, field)


@pytest.mark.parametrize("stage", list(_RECORDED))
def test_the_recorded_drives_read_as_legacy_retry_provenance(
    _rereads: dict[str, dict[str, Any]], stage: str
) -> None:
    """06.3.4.1-34: the three drives predate the gate-stage marker, so they read under
    the closed registry. The text says so, and no reading carries a provenance MISS."""
    provenance = _rereads[stage]["SC-1"]["detail"].get("retry_provenance") or ""
    assert provenance.startswith("legacy"), provenance
    for name, entry in _rereads[stage].items():
        if "reason" in entry:
            assert "gate-stage marker" not in entry["reason"], (stage, name)
            assert "retried attempts" not in entry["reason"], (stage, name)


def test_the_legacy_registry_is_exactly_the_three_recorded_drives() -> None:
    """06.3.4.1-34: the registry is closed and keyed on each recorded header's own
    `(corpus, created_at)`; each drive's console records `retries=0` (D-67), and each
    entry binds the drive's record count and content digest (WR-01)."""
    import re

    from lancet_eval import unpark_gates
    from lancet_eval.journal import load_records

    registry = unpark_gates._LEGACY_UNMARKED_GATE_DRIVES
    root = repo_root()
    expected: dict[tuple[str, float], str] = {}
    for stage, (run, _, _) in _RECORDED.items():
        journal = root / run / "journal.jsonl"
        header = json.loads(journal.read_text(encoding="utf-8").splitlines()[0])
        assert header["type"] == "header"
        assert "gate_stage" not in header and "max_retries" not in header, stage
        expected[(header["corpus"], header["created_at"])] = stage
        console = (root / run / "drive-console.txt").read_text(encoding="utf-8")
        banners = re.findall(r"retries=(\d+)", console)
        assert banners, stage
        assert all(int(value) == 0 for value in banners), (stage, banners)
        records = load_records(journal)
        entry = registry[(header["corpus"], header["created_at"])]
        assert entry.n_records == len(records), stage
        digest = unpark_gates.legacy_records_digest(records)
        assert entry.records_sha256 == digest, stage
    assert len(registry) == 3
    assert {key: entry.label for key, entry in registry.items()} == expected
    for entry in registry.values():
        run = _RECORDED[entry.label][0]
        assert entry.evidence == f"{run}/drive-console.txt records retries=0", entry


@pytest.mark.parametrize(
    ("stage", "readings", "expected_key", "expected"),
    [
        ("drive1", ("SC-3",), "G", 90),
        ("drive1b", ("SC-3",), "G", 90),
        ("drive2", ("SC-3", "SC-4"), "G", 90),
        ("drive2", ("SC-5",), "V", 65),
    ],
)
def test_the_reread_coverages_clear_the_floor_over_sample_scoped_denominators(
    _rereads: dict[str, dict[str, Any]],
    stage: str,
    readings: tuple[str, ...],
    expected_key: str,
    expected: int,
) -> None:
    """A disclosure of the recorded coverages, not a new verdict (D-73): the floor
    postdates these drives, and at 0.80 no recorded status changes. The denominators
    are |sample & G| = 90 and |sample & V| = 65, never the corpus-wide 398 / 291."""
    for name in readings:
        detail = _rereads[stage][name]["detail"]
        assert detail["coverage_expected"] == expected, (stage, name, expected_key)
        assert detail["coverage"] >= thresholds.UNPARK_GATE_COVERAGE_FLOOR, (
            stage,
            name,
        )
        assert detail["coverage"] == detail["coverage_n"] / expected
