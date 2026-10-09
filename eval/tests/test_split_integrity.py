"""WR-01: the split's recorded hashes and the journal's split markers are verified.

Every check here also runs against the committed split and the committed `[split]`
journals, so a check that refused a closed artifact fails this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lancet_eval.config import repo_root
from lancet_eval.journal import read_journal_header
from lancet_eval.score import ScoreError, _require_split_marker_matches
from lancet_eval.split import (
    POPULATIONS_REL,
    QUESTIONS_SAMPLE_REL,
    HeldOutSplit,
    lf_sha256,
    load_split,
    split_input_problems,
    split_sha256,
)

_SPLIT_PATH = repo_root() / "eval" / "corpora" / "multihop_rag" / "heldout_split.json"
_SPLIT_RUNS = (
    "2026-10-07-heldout-multihop_rag_heldout",
    "2026-10-07-rehearsal-multihop_rag_rehearsal",
    "2026-10-07-rehearsal2-multihop_rag_rehearsal",
)


def test_the_committed_split_matches_the_files_it_was_derived_from() -> None:
    assert split_input_problems(load_split(_SPLIT_PATH), repo_root()) == []


@pytest.mark.parametrize("run", _SPLIT_RUNS)
def test_every_committed_split_journal_names_the_committed_split(run: str) -> None:
    split = load_split(_SPLIT_PATH)
    header = read_journal_header(repo_root() / "eval" / "runs" / run / "journal.jsonl")
    assert header is not None
    assert header["order_seed"] == split.order_seed
    assert header["split_sha256"] == split_sha256(split)
    # the score-time check accepts the committed artifact
    _require_split_marker_matches(
        {k: header[k] for k in ("order_seed", "split_sha256")}, split
    )


def _tmp_repo(tmp_path: Path) -> tuple[HeldOutSplit, Path]:
    """A throwaway repository holding copies of the three inputs and their split."""
    real = repo_root()
    base = load_split(_SPLIT_PATH)
    for rel in (POPULATIONS_REL, base.dev_source, QUESTIONS_SAMPLE_REL):
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((real / rel).read_bytes())
    return base, tmp_path


def test_a_copy_of_the_inputs_verifies_and_a_crlf_copy_does_too(
    tmp_path: Path,
) -> None:
    split, root = _tmp_repo(tmp_path)
    assert split_input_problems(split, root) == []
    sample = root / QUESTIONS_SAMPLE_REL
    sample.write_bytes(sample.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert split_input_problems(split, root) == []


@pytest.mark.parametrize(
    ("rel_name", "label"),
    [
        ("POPULATIONS_REL", "populations"),
        ("dev_source", "diag_selection"),
        ("QUESTIONS_SAMPLE_REL", "questions_sample"),
    ],
)
def test_a_changed_or_missing_input_is_named(
    rel_name: str, label: str, tmp_path: Path
) -> None:
    split, root = _tmp_repo(tmp_path)
    rel = split.dev_source if rel_name == "dev_source" else globals()[rel_name]
    target = root / rel
    target.write_bytes(target.read_bytes() + b" ")
    problems = split_input_problems(split, root)
    assert len(problems) == 1
    assert label in problems[0]
    assert "no longer hashes" in problems[0]
    assert lf_sha256(target) != getattr(split, f"{label}_sha256")

    target.unlink()
    problems = split_input_problems(split, root)
    assert len(problems) == 1
    assert "missing" in problems[0]


def test_the_score_check_refuses_a_marker_that_differs_and_ignores_an_absent_one() -> (
    None
):
    split = load_split(_SPLIT_PATH)
    _require_split_marker_matches({}, split)
    with pytest.raises(ScoreError, match="split_sha256"):
        _require_split_marker_matches({"split_sha256": "0" * 64}, split)
    with pytest.raises(ScoreError, match="order_seed"):
        _require_split_marker_matches({"order_seed": split.order_seed + 1}, split)

