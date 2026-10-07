"""Tests for eval/scripts/select_heldout_split.py and lancet_eval.split (D-105,
D-106, D-108, D-124): the held-out split, the rehearsal-pool canary and
rehearsal picks, and the LF-normalised hashing rule (RESEARCH Pitfall 1).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from lancet_eval.config import repo_root
from lancet_eval.corpus import load_corpus_config, load_sample_questions
from lancet_eval.split import (
    HeldOutSplit,
    lf_sha256,
    load_split,
    split_sha256,
)

SCRIPT_PATH = repo_root() / "eval" / "scripts" / "select_heldout_split.py"
CORPUS_DIR = repo_root() / "eval" / "corpora" / "multihop_rag"
POPULATIONS_PATH = (
    repo_root()
    / ".planning"
    / "phases"
    / "06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair"
    / "diagnostic"
    / "post-reconcile"
    / "populations.json"
)
POPULATIONS_LF_SHA256 = (
    "81a3cc2a11a42ec19cfd19a210304b89a6a59e0e2d35d8eea746019f178268d1"
)
DIAG_SELECTION_LF_SHA256 = (
    "c69d9a5dd0d99e4f59120d23708575f29be1629b639aacbaee3aed822cffa2d8"
)
SHA_A = "a" * 64


def _load_script():
    """Loads select_heldout_split.py by file path (a standalone script)."""
    spec = importlib.util.spec_from_file_location("select_heldout_split", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["select_heldout_split"] = module
    spec.loader.exec_module(module)
    return module


_shs = _load_script()


def _read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _sample_by_id() -> dict[str, dict]:
    return {
        r["question_id"]: r for r in _read_jsonl(CORPUS_DIR / "questions.sample.jsonl")
    }


def _lf(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("split_out")
    assert _shs.main(["--out-dir", str(out)]) == 0
    return out


# --- counts and hashes (D-105) -------------------------------------------------------


def test_split_counts_per_set_and_type(generated: Path) -> None:
    split = load_split(generated / "heldout_split.json")
    by_id = _sample_by_id()

    assert len(split.heldout_g_ids) == 308
    assert len(split.heldout_null_ids) == 43
    assert len(split.heldout_g_ids) + len(split.heldout_null_ids) == 351
    assert len(split.dev_ids) == 100

    g_types = Counter(by_id[i]["question_type"] for i in split.heldout_g_ids)
    assert g_types == {
        "comparison_query": 125,
        "inference_query": 105,
        "temporal_query": 78,
    }
    assert {by_id[i]["question_type"] for i in split.heldout_null_ids} == {"null_query"}

    dev, g, null = (
        set(split.dev_ids),
        set(split.heldout_g_ids),
        set(split.heldout_null_ids),
    )
    assert not (dev & g or dev & null or g & null)
    assert split.order_seed == 42
    assert split.derivation_rule == (
        "every non-dev sample question in G, plus every non-dev null"
    )
    assert split.dev_source == "eval/corpora/multihop_rag/diag_selection.json"


def test_recorded_input_hashes_are_lf_normalised(generated: Path) -> None:
    split = load_split(generated / "heldout_split.json")
    assert lf_sha256(POPULATIONS_PATH) == POPULATIONS_LF_SHA256
    assert split.populations_sha256 == POPULATIONS_LF_SHA256
    assert split.diag_selection_sha256 == DIAG_SELECTION_LF_SHA256
    assert split.questions_sample_sha256 == lf_sha256(
        CORPUS_DIR / "questions.sample.jsonl"
    )


def test_lf_sha256_is_the_same_for_lf_and_crlf_bytes(tmp_path: Path) -> None:
    lf_file = tmp_path / "lf.txt"
    crlf_file = tmp_path / "crlf.txt"
    lf_file.write_bytes(b"a\nb\n")
    crlf_file.write_bytes(b"a\r\nb\r\n")
    assert lf_sha256(lf_file) == lf_sha256(crlf_file)


def test_split_sha256_is_the_same_from_lf_and_crlf_files(
    generated: Path, tmp_path: Path
) -> None:
    lf_bytes = (generated / "heldout_split.json").read_bytes().replace(b"\r\n", b"\n")
    crlf_path = tmp_path / "crlf.json"
    crlf_path.write_bytes(lf_bytes.replace(b"\n", b"\r\n"))
    assert split_sha256(load_split(generated / "heldout_split.json")) == split_sha256(
        load_split(crlf_path)
    )


# --- output files --------------------------------------------------------------------


def test_question_file_line_counts_and_ids(generated: Path) -> None:
    split = load_split(generated / "heldout_split.json")
    heldout_rows = _read_jsonl(generated / "questions.heldout.jsonl")
    assert len(heldout_rows) == 351
    assert [r["question_id"] for r in heldout_rows] == sorted(
        split.heldout_g_ids + split.heldout_null_ids
    )
    assert len(_read_jsonl(generated / "questions.rehearsal.jsonl")) == 3
    assert len(_read_jsonl(generated / "canary.arms.jsonl")) == 3


def test_written_files_use_lf_only(generated: Path) -> None:
    for name in _shs.OUTPUT_FILES:
        assert b"\r" not in (generated / name).read_bytes()


def test_generator_is_byte_identical_across_runs(
    generated: Path, tmp_path: Path
) -> None:
    second = tmp_path / "second"
    assert _shs.main(["--out-dir", str(second)]) == 0
    for name in _shs.OUTPUT_FILES:
        assert (generated / name).read_bytes() == (second / name).read_bytes()


# --- rehearsal pool, canary picks and rehearsal picks (D-108, D-124) ------------------


def test_rehearsal_pool_is_49_ids_and_picks_come_from_it(
    generated: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    split = load_split(generated / "heldout_split.json")
    by_id = _sample_by_id()
    excluded = (
        set(split.dev_ids) | set(split.heldout_g_ids) | set(split.heldout_null_ids)
    )
    pool = {i for i in by_id if i not in excluded}
    assert len(pool) == 49
    assert Counter(by_id[i]["question_type"] for i in pool) == {
        "inference_query": 22,
        "comparison_query": 18,
        "temporal_query": 9,
    }

    canary = _read_jsonl(generated / "canary.arms.jsonl")
    rehearsal = _read_jsonl(generated / "questions.rehearsal.jsonl")
    canary_ids = {r["question_id"] for r in canary}
    rehearsal_ids = {r["question_id"] for r in rehearsal}

    assert canary_ids <= pool
    assert rehearsal_ids <= pool
    assert not canary_ids & rehearsal_ids
    for ids in (canary_ids, rehearsal_ids):
        assert Counter(by_id[i]["question_type"] for i in ids) == {
            "comparison_query": 1,
            "inference_query": 1,
            "temporal_query": 1,
        }
    for row in canary:
        assert row["question"] == by_id[row["question_id"]]["query"]
        assert row["question_type"] == by_id[row["question_id"]]["question_type"]
        assert row["min_retrieved_chunks"] == 1
    # The rehearsal rows are the sample rows, verbatim.
    for row in rehearsal:
        assert row == by_id[row["question_id"]]
    capsys.readouterr()


def test_stdout_report_carries_the_checkpoint_facts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _shs.main(["--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert (
        "heldout G: 308 comparison_query=125 inference_query=105 temporal_query=78"
        in out
    )
    assert "heldout null: 43" in out
    assert "heldout total: 351" in out
    assert "rehearsal pool: 49" in out
    assert POPULATIONS_LF_SHA256 in out
    assert DIAG_SELECTION_LF_SHA256 in out
    assert "canary picks (D-124):" in out
    assert "rehearsal picks (D-108):" in out


def test_main_writes_nothing_into_the_corpus_dir_by_default_arguments_only_out_dir(
    tmp_path: Path,
) -> None:
    before = {p.name for p in CORPUS_DIR.iterdir()}
    assert _shs.main(["--out-dir", str(tmp_path)]) == 0
    assert {p.name for p in CORPUS_DIR.iterdir()} == before


def test_pick_raises_when_a_type_has_no_candidate() -> None:
    import random

    with pytest.raises(_shs.SelectionError):
        _shs._pick_per_type(
            random.Random(42),
            {"comparison_query": ["a"], "inference_query": ["b"]},
            set(),
        )


# --- HeldOutSplit model --------------------------------------------------------------


def _split_kwargs(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "derivation_rule": "rule",
        "populations_sha256": SHA_A,
        "diag_selection_sha256": SHA_A,
        "questions_sample_sha256": SHA_A,
        "dev_source": "x.json",
        "order_seed": 42,
        "dev_ids": ["d1"],
        "heldout_g_ids": ["g1"],
        "heldout_null_ids": ["n1"],
    }
    base.update(over)
    return base


def test_model_accepts_a_valid_split() -> None:
    assert HeldOutSplit(**_split_kwargs()).order_seed == 42  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "over",
    [
        {"heldout_g_ids": ["d1"]},
        {"heldout_null_ids": ["d1"]},
        {"heldout_null_ids": ["g1"]},
        {"heldout_g_ids": ["g1", "g1"]},
        {"dev_ids": ["d1", "d1"]},
        {"populations_sha256": "ABC"},
        {"diag_selection_sha256": "g" * 64},
        {"questions_sample_sha256": SHA_A.upper()},
    ],
)
def test_model_rejects_overlap_duplicates_and_bad_sha(over: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        HeldOutSplit(**_split_kwargs(**over))  # type: ignore[arg-type]


def test_model_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        HeldOutSplit(**_split_kwargs(surprise=1))  # type: ignore[arg-type]


# --- committed-file pins (D-105, D-106, D-108, D-124) --------------------------------

COMMITTED_FILES = (
    "heldout_split.json",
    "questions.heldout.jsonl",
    "questions.rehearsal.jsonl",
    "canary.arms.jsonl",
)
FOUR_ARMS = ["dense-only", "bm25-only", "hybrid", "hybrid+graph"]


def test_committed_files_equal_a_fresh_regeneration_after_lf_normalisation(
    generated: Path,
) -> None:
    for name in COMMITTED_FILES:
        assert _lf(CORPUS_DIR / name) == _lf(generated / name), name


def test_committed_split_has_the_d105_shape() -> None:
    split = load_split(CORPUS_DIR / "heldout_split.json")
    assert len(split.dev_ids) == 100
    assert len(split.heldout_g_ids) == 308
    assert len(split.heldout_null_ids) == 43
    assert split.order_seed == 42
    assert split.populations_sha256 == POPULATIONS_LF_SHA256
    assert split.diag_selection_sha256 == DIAG_SELECTION_LF_SHA256


def test_four_arm_corpora_declare_the_four_arms_and_diag_keeps_its_two() -> None:
    assert load_corpus_config("multihop_rag_heldout").arms == FOUR_ARMS
    assert load_corpus_config("multihop_rag_rehearsal").arms == FOUR_ARMS
    assert load_corpus_config("multihop_rag_diag").arms == ["graph-on", "graph-off"]


def test_committed_question_files_match_the_split_lists() -> None:
    split = load_split(CORPUS_DIR / "heldout_split.json")
    heldout = {r["question_id"] for r in _read_jsonl(CORPUS_DIR / COMMITTED_FILES[1])}
    rehearsal = {r["question_id"] for r in _read_jsonl(CORPUS_DIR / COMMITTED_FILES[2])}
    assert heldout == set(split.heldout_g_ids) | set(split.heldout_null_ids)
    assert not rehearsal & (heldout | set(split.dev_ids))


def test_no_canary_or_rehearsal_id_is_in_dev_or_heldout() -> None:
    split = load_split(CORPUS_DIR / "heldout_split.json")
    used = set(split.dev_ids) | set(split.heldout_g_ids) | set(split.heldout_null_ids)
    canary = {r["question_id"] for r in _read_jsonl(CORPUS_DIR / COMMITTED_FILES[3])}
    rehearsal = {r["question_id"] for r in _read_jsonl(CORPUS_DIR / COMMITTED_FILES[2])}
    assert len(canary) == 3
    assert len(rehearsal) == 3
    assert not (canary | rehearsal) & used
    assert not canary & rehearsal


def test_load_sample_questions_returns_exactly_the_351_split_ids() -> None:
    split = load_split(CORPUS_DIR / "heldout_split.json")
    loaded = load_sample_questions("multihop_rag_heldout")
    assert len(loaded) == 351
    assert {q.question_id for q in loaded} == set(split.heldout_g_ids) | set(
        split.heldout_null_ids
    )
