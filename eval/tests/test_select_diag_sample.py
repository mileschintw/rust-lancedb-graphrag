"""Tests for eval/scripts/select_diag_sample.py: freezing G/V (D-63/D-82) and
drawing the reproducible diagnostic sample (D-68).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path

import pytest

from lancet_eval.config import repo_root

SCRIPT_PATH = repo_root() / "eval" / "scripts" / "select_diag_sample.py"


def _load_select_diag_sample():
    """Loads select_diag_sample.py by file path (a standalone script, like
    retro_lenient.py -- see test_retro_lenient.py for the identical pattern)."""
    spec = importlib.util.spec_from_file_location("select_diag_sample", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["select_diag_sample"] = module
    spec.loader.exec_module(module)
    return module


_sds = _load_select_diag_sample()
build_selection = _sds.build_selection
largest_remainder_quotas = _sds.largest_remainder_quotas
build_diag_corpus_toml = _sds.build_diag_corpus_toml
SelectionError = _sds.SelectionError

DIAGNOSTIC_DIR = (
    repo_root()
    / ".planning"
    / "phases"
    / "06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair"
    / "diagnostic"
    / "post-reconcile"
)
GOLD_CHUNKS_PATH = DIAGNOSTIC_DIR / "gold_chunks.jsonl"
VECTOR_TOP4_PATH = DIAGNOSTIC_DIR / "vector_top4.jsonl"


def _real_raw_questions_by_id() -> dict[str, dict]:
    path = repo_root() / "eval" / "corpora" / "multihop_rag" / "questions.sample.jsonl"
    by_id: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                raw = json.loads(stripped)
                by_id[raw["question_id"]] = raw
    return by_id


# --- real-data behavior: G/V match 06.3.4.1-09's frozen candidates ------------------


def test_g_and_v_match_09_frozen_candidates_on_real_probe_data() -> None:
    """06.3.4.1-09 froze |G|=398, |V|=291 on the reconciled store; this plan's own
    definition (non-null AND (b) yes for every evidence item, via gold_chunks.jsonl)
    must reproduce exactly the same numbers -- no discrepancy to report."""
    selection = build_selection(
        "multihop_rag",
        GOLD_CHUNKS_PATH,
        VECTOR_TOP4_PATH,
        include_nulls=0,
        seed=42,
    )
    assert selection["g_size"] == 398
    assert selection["v_size"] == 291
    assert selection["strata_counts_in_G"] == {
        "comparison_query": 161,
        "inference_query": 136,
        "temporal_query": 101,
    }
    assert selection["shortfalls"] == {}


def test_quotas_are_largest_remainder_over_actual_g_counts() -> None:
    """Quotas are recomputed via largest-remainder over G's ACTUAL per-type counts
    (161/136/101), not copied verbatim from the full-sample 36/32/22 figure."""
    selection = build_selection(
        "multihop_rag",
        GOLD_CHUNKS_PATH,
        VECTOR_TOP4_PATH,
        include_nulls=0,
        seed=42,
    )
    assert selection["quotas"] == {
        "comparison_query": 36,
        "inference_query": 31,
        "temporal_query": 23,
    }
    assert sum(selection["quotas"].values()) == 90


def test_selection_is_deterministic_across_two_calls() -> None:
    """Two runs over the same inputs produce byte-identical selections."""
    first = build_selection(
        "multihop_rag", GOLD_CHUNKS_PATH, VECTOR_TOP4_PATH, include_nulls=10, seed=42
    )
    second = build_selection(
        "multihop_rag", GOLD_CHUNKS_PATH, VECTOR_TOP4_PATH, include_nulls=10, seed=42
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_include_nulls_zero_omits_null_questions() -> None:
    selection = build_selection(
        "multihop_rag", GOLD_CHUNKS_PATH, VECTOR_TOP4_PATH, include_nulls=0, seed=42
    )
    assert selection["null_included"] == 0
    assert len(selection["drawn_question_ids"]) == 90


def test_include_nulls_ten_draws_ten_null_questions() -> None:
    selection = build_selection(
        "multihop_rag", GOLD_CHUNKS_PATH, VECTOR_TOP4_PATH, include_nulls=10, seed=42
    )
    assert selection["null_included"] == 10
    assert len(selection["drawn_question_ids"]) == 100

    raw_by_id = _real_raw_questions_by_id()
    null_drawn = [
        qid
        for qid in selection["drawn_question_ids"]
        if raw_by_id[qid]["question_type"] == "null_query"
    ]
    assert len(null_drawn) == 10


def test_every_drawn_non_null_question_is_in_g() -> None:
    selection = build_selection(
        "multihop_rag", GOLD_CHUNKS_PATH, VECTOR_TOP4_PATH, include_nulls=10, seed=42
    )
    raw_by_id = _real_raw_questions_by_id()
    g_ids = set(selection["g_question_ids"])
    for qid in selection["drawn_question_ids"]:
        if raw_by_id[qid]["question_type"] != "null_query":
            assert qid in g_ids


def test_source_index_generation_matches_document_map() -> None:
    selection = build_selection(
        "multihop_rag", GOLD_CHUNKS_PATH, VECTOR_TOP4_PATH, include_nulls=0, seed=42
    )
    with open(
        repo_root() / "eval" / "corpora" / "multihop_rag" / "document_map.json",
        encoding="utf-8",
    ) as f:
        doc_map = json.load(f)
    assert selection["source_index_generation"] == doc_map["index_generation"]


def test_invalid_include_nulls_value_raises() -> None:
    with pytest.raises(SelectionError):
        build_selection(
            "multihop_rag", GOLD_CHUNKS_PATH, VECTOR_TOP4_PATH, include_nulls=5, seed=42
        )


# --- largest_remainder_quotas (pure function) ---------------------------------------


def test_largest_remainder_quotas_sums_to_total() -> None:
    quotas = largest_remainder_quotas(
        {"comparison_query": 161, "inference_query": 136, "temporal_query": 101}, 90
    )
    assert quotas == {
        "comparison_query": 36,
        "inference_query": 31,
        "temporal_query": 23,
    }
    assert sum(quotas.values()) == 90


def test_largest_remainder_quotas_breaks_ties_on_name() -> None:
    """Two strata with an identical fractional remainder both get a shot at the
    last seat; the lexicographically smaller name wins, deterministically."""
    quotas = largest_remainder_quotas({"b_stratum": 1, "a_stratum": 1}, 1)
    assert quotas == {"a_stratum": 1, "b_stratum": 0}


def test_largest_remainder_quotas_rejects_empty_population() -> None:
    with pytest.raises(SelectionError):
        largest_remainder_quotas({"a": 0, "b": 0}, 10)


# --- widen-when-stratum-too-small and refuse-to-widen-silently below 60 -------------


def _write_synthetic_corpus(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    strata_pool_sizes: dict[str, int],
    include_null_pool: int = 0,
) -> tuple[Path, Path]:
    """Builds a minimal synthetic multihop_rag corpus under tmp_path and points
    every `repo_root()` this module's dependencies resolve through at it.

    Returns (gold_chunks_path, vector_top4_path) for the synthetic pool: every
    non-null question gets exactly one evidence item, state `in_chunk`, so every
    non-null question drawn here is in G by construction.
    """
    corpora_dir = tmp_path / "eval" / "corpora"
    mh_dir = corpora_dir / "multihop_rag"
    mh_dir.mkdir(parents=True)

    (corpora_dir / "multihop_rag.toml").write_text(
        "[documents]\nchunk_size = 500\n\n"
        '[questions]\nfile = "multihop_rag/questions.sample.jsonl"\n'
        "sample_seed = 42\nsample_size = 500\n",
        encoding="utf-8",
    )
    (mh_dir / "document_map.json").write_text(
        json.dumps(
            {
                "corpus": "multihop_rag",
                "seeded_at": "t",
                "index_generation": "gen-synthetic",
                "entries": {},
            }
        ),
        encoding="utf-8",
    )

    raw_questions: list[dict] = []
    gold_chunk_lines: list[dict] = []
    counter = 0
    for stratum, pool_size in strata_pool_sizes.items():
        for _i in range(pool_size):
            qid = f"syn-{stratum}-{counter:04d}"
            counter += 1
            raw_questions.append(
                {
                    "question_id": qid,
                    "query": f"Question {qid}",
                    "question_type": stratum,
                    "evidence_list": [{"title": "T", "fact": "F"}],
                    "answer": "A",
                }
            )
            gold_chunk_lines.append(
                {
                    "question_id": qid,
                    "evidence_index": 0,
                    "title": "T",
                    "document_id": "doc-1",
                    "state": "in_chunk",
                    "chunk_ids": ["doc-1:0"],
                }
            )
    for i in range(include_null_pool):
        qid = f"syn-null-{i:04d}"
        raw_questions.append(
            {
                "question_id": qid,
                "query": f"Null question {qid}",
                "question_type": "null_query",
                "evidence_list": [],
                "answer": "Insufficient information.",
            }
        )

    with open(mh_dir / "questions.sample.jsonl", "w", encoding="utf-8") as f:
        for raw in raw_questions:
            f.write(json.dumps(raw))
            f.write("\n")

    gold_chunks_path = tmp_path / "gold_chunks.jsonl"
    with open(gold_chunks_path, "w", encoding="utf-8") as f:
        for row in gold_chunk_lines:
            f.write(json.dumps(row))
            f.write("\n")

    vector_top4_path = tmp_path / "vector_top4.jsonl"
    vector_top4_path.write_text("", encoding="utf-8")

    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: tmp_path)
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)
    monkeypatch.setattr(_sds, "repo_root", lambda: tmp_path)

    return gold_chunks_path, vector_top4_path


def test_quota_widens_to_whole_stratum_when_pool_is_smaller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stratum whose G pool is smaller than its proportional-of-90 quota is
    taken whole, with the shortfall recorded rather than silently under-filled."""
    gold_chunks_path, vector_top4_path = _write_synthetic_corpus(
        tmp_path,
        monkeypatch,
        strata_pool_sizes={
            "comparison_query": 70,
            "inference_query": 3,
            "temporal_query": 1,
        },
    )

    selection = build_selection(
        "multihop_rag", gold_chunks_path, vector_top4_path, include_nulls=0, seed=42
    )

    assert selection["strata_counts_in_G"] == {
        "comparison_query": 70,
        "inference_query": 3,
        "temporal_query": 1,
    }
    # Both undersized strata (comparison_query and inference_query) hit their
    # pool ceiling below their computed quota; temporal_query's pool exactly
    # meets its quota, so it is absent from shortfalls.
    assert selection["shortfalls"] == {"comparison_query": 15, "inference_query": 1}
    assert len(selection["drawn_question_ids"]) == 70 + 3 + 1


def test_refuses_to_widen_silently_below_60_drawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fewer than 60 non-null questions drawn into G halts with SelectionError
    instead of silently widening past the committed minimum (D-68)."""
    gold_chunks_path, vector_top4_path = _write_synthetic_corpus(
        tmp_path,
        monkeypatch,
        strata_pool_sizes={
            "comparison_query": 8,
            "inference_query": 1,
            "temporal_query": 1,
        },
    )

    with pytest.raises(SelectionError, match="minimum 60"):
        build_selection(
            "multihop_rag", gold_chunks_path, vector_top4_path, include_nulls=0, seed=42
        )


# --- build_diag_corpus_toml (pure function) ------------------------------------------


_SYNTHETIC_SOURCE_TOML = """[documents]
source = "https://example.invalid/dataset"
license = "odc-by"
count = 609
commit_documents = true
chunk_size = 500

[questions]
file = "multihop_rag/questions.sample.jsonl"
sample_seed = 42
sample_size = 500

[document_subset]
selection_algorithm = "referenced_plus_distractors"
distractor_count = 25

[arms]
arms = ["graph-on", "graph-off"]
"""


def test_build_diag_corpus_toml_adds_map_corpus_label_format_and_file() -> None:
    content = build_diag_corpus_toml(_SYNTHETIC_SOURCE_TOML.splitlines(), 100)
    parsed = tomllib.loads(content)

    assert parsed["documents"]["map_corpus"] == "multihop_rag"
    assert parsed["questions"]["file"] == "multihop_rag/questions.diag.jsonl"
    assert parsed["questions"]["label_format"] == "multihop_rag"
    assert parsed["questions"]["sample_size"] == 100
    # Untouched keys survive verbatim.
    assert parsed["documents"]["chunk_size"] == 500
    assert parsed["questions"]["sample_seed"] == 42
    assert parsed["document_subset"]["distractor_count"] == 25
    assert parsed["arms"]["arms"] == ["graph-on", "graph-off"]


def test_build_diag_corpus_toml_is_deterministic() -> None:
    lines = _SYNTHETIC_SOURCE_TOML.splitlines()
    assert build_diag_corpus_toml(lines, 90) == build_diag_corpus_toml(lines, 90)


_SYNTHETIC_SOURCE_TOML_WITH_LABEL_FORMAT = """[documents]
source = "https://example.invalid/dataset"
license = "odc-by"
count = 609
commit_documents = true
chunk_size = 500

[questions]
file = "multihop_rag/questions.sample.jsonl"
label_format = "multihop_rag"
sample_seed = 42
sample_size = 500

[arms]
arms = ["graph-on", "graph-off"]
"""


def test_build_diag_corpus_toml_overwrites_label_format_without_duplicating() -> None:
    """Regression: the real `multihop_rag.toml` already sets `label_format`.
    A naive unconditional insert right after `file` would duplicate the key
    (two `label_format = ...` lines) instead of overwriting the one that's
    already there."""
    content = build_diag_corpus_toml(
        _SYNTHETIC_SOURCE_TOML_WITH_LABEL_FORMAT.splitlines(), 100
    )
    assert content.count("label_format") == 1
    parsed = tomllib.loads(content)
    assert parsed["questions"]["label_format"] == "multihop_rag"
    assert parsed["questions"]["file"] == "multihop_rag/questions.diag.jsonl"
    assert parsed["questions"]["sample_size"] == 100


# --- load_document_map indirection for the real corpus name (D-68 behavior) ----------


def test_load_document_map_for_diag_corpus_returns_multihop_rag_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpora_dir = tmp_path / "eval" / "corpora"
    mh_dir = corpora_dir / "multihop_rag"
    mh_dir.mkdir(parents=True)
    (mh_dir / "document_map.json").write_text(
        json.dumps(
            {
                "corpus": "multihop_rag",
                "seeded_at": "t",
                "index_generation": "lance-702",
                "entries": {},
            }
        ),
        encoding="utf-8",
    )
    (corpora_dir / "multihop_rag_diag.toml").write_text(
        '[documents]\nmap_corpus = "multihop_rag"\n\n'
        '[questions]\nfile = "multihop_rag/questions.diag.jsonl"\n'
        'label_format = "multihop_rag"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: tmp_path)
    monkeypatch.setattr("lancet_eval.seed.repo_root", lambda: tmp_path)

    from lancet_eval.seed import load_document_map

    result = load_document_map("multihop_rag_diag")
    assert result.corpus == "multihop_rag"
    assert result.index_generation == "lance-702"


# --- completeness_comparison over a synthetic multihop_rag_diag journal -------------


def test_completeness_comparison_over_diag_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finished drive over the diag corpus's own questions file can legitimately
    reach complete (D-68/D-87a) -- and one missing unit reaches incomplete."""
    corpora_dir = tmp_path / "eval" / "corpora"
    mh_dir = corpora_dir / "multihop_rag"
    mh_dir.mkdir(parents=True)

    questions = [
        {
            "question_id": "q1",
            "query": "Q1",
            "question_type": "comparison_query",
            "evidence_list": [{"title": "t", "fact": "f"}],
            "answer": "A",
        },
        {
            "question_id": "q2",
            "query": "Q2",
            "question_type": "inference_query",
            "evidence_list": [{"title": "t2", "fact": "f2"}],
            "answer": "A",
        },
    ]
    with open(mh_dir / "questions.diag.jsonl", "w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q))
            f.write("\n")

    (corpora_dir / "multihop_rag_diag.toml").write_text(
        '[questions]\nfile = "multihop_rag/questions.diag.jsonl"\n'
        'label_format = "multihop_rag"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: tmp_path)

    from lancet_eval.journal import RunRecord, completeness_comparison

    all_units = [
        (q["question_id"], arm) for q in questions for arm in ("graph-on", "graph-off")
    ]

    def _write_journal(path: Path, units: list[tuple[str, str]]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {"type": "header", "corpus": "multihop_rag_diag", "partial": True}
                )
                + "\n"
            )
            for qid, arm in units:
                rec = RunRecord(
                    corpus="multihop_rag_diag",
                    question_id=qid,
                    graph_arm=arm,
                    outcome="success",
                    index_generation="gen-1",
                )
                f.write(rec.model_dump_json() + "\n")

    complete_journal = tmp_path / "complete_journal.jsonl"
    _write_journal(complete_journal, all_units)
    is_complete, missing = completeness_comparison(
        complete_journal, "multihop_rag_diag"
    )
    assert is_complete is True
    assert missing == set()

    incomplete_journal = tmp_path / "incomplete_journal.jsonl"
    _write_journal(incomplete_journal, all_units[:-1])
    is_complete, missing = completeness_comparison(
        incomplete_journal, "multihop_rag_diag"
    )
    assert is_complete is False
    assert len(missing) == 1
