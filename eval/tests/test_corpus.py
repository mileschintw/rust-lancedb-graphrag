"""Tests for corpus loading, sampling determinism, and subset validation."""

import hashlib
import json
import random

import pytest

from lancet_eval.config import repo_root
from lancet_eval.corpus import (
    CorpusConfig,
    GoldQuestion,
    load_corpus,
    sample_questions,
)


@pytest.mark.parametrize("corpus_name", ["multihop_rag", "graphrag_bench"])
def test_corpus_agnostic_loader(corpus_name: str) -> None:
    cfg = load_corpus(corpus_name)
    assert isinstance(cfg, CorpusConfig)
    assert cfg.name == corpus_name
    assert cfg.chunk_size == 500
    assert len(cfg.arms) >= 2

    # Asserts that questions parse into GoldQuestion objects offline
    qs = cfg.questions
    assert len(qs) >= 1
    for q in qs:
        assert isinstance(q, GoldQuestion)
        assert q.question_id
        assert q.question


def test_sampling_determinism_and_shuffle_invariance() -> None:
    raw_questions = [
        {
            "query_id": f"q_{i:04d}",
            "query": f"Question {i}",
            "question_type": "type_a",
            "evidence_list": [{"fact": f"Fact {i}"}],
            "answer": f"Answer {i}",
        }
        for i in range(100)
    ]

    # Determinism across two invocations
    sample1 = sample_questions(raw_questions, n=20, seed=42)
    sample2 = sample_questions(raw_questions, n=20, seed=42)

    bytes1 = json.dumps(sample1).encode("utf-8")
    bytes2 = json.dumps(sample2).encode("utf-8")
    assert hashlib.sha256(bytes1).hexdigest() == hashlib.sha256(bytes2).hexdigest()

    # Invariance to input list shuffling
    shuffled = list(raw_questions)
    random.Random(999).shuffle(shuffled)
    sample_shuffled = sample_questions(shuffled, n=20, seed=42)

    ids1 = [q["query_id"] for q in sample1]
    ids_shuffled = [q["query_id"] for q in sample_shuffled]
    assert ids1 == ids_shuffled


def test_committed_multihop_rag_sample_integrity() -> None:
    cfg = load_corpus("multihop_rag")
    qs = cfg.questions

    assert len(qs) == 500, f"Expected 500 questions, got {len(qs)}"

    null_count = sum(1 for q in qs if q.is_null)
    assert null_count > 0, "Committed sample must contain null-query items"
    assert null_count == 53


def test_committed_subset_selection_metadata() -> None:
    root = repo_root()
    subset_json = root / "eval" / "corpora" / "multihop_rag" / "subset_selection.json"
    subset_jsonl = root / "eval" / "corpora" / "multihop_rag" / "documents.subset.jsonl"

    assert subset_json.is_file(), f"Missing {subset_json}"
    assert subset_jsonl.is_file(), f"Missing {subset_jsonl}"

    with open(subset_json, encoding="utf-8") as f:
        meta = json.load(f)

    assert meta["algorithm"] == "referenced_plus_distractors"
    assert meta["seed"] == 42
    assert meta["referenced_count"] > 0
    assert meta["distractor_count"] == 25
    assert meta["total_count"] == meta["referenced_count"] + meta["distractor_count"]

    with open(subset_jsonl, encoding="utf-8") as f:
        doc_lines = [line for line in f if line.strip()]

    assert len(doc_lines) == meta["total_count"]


def test_attribution_file_content() -> None:
    attr_path = repo_root() / "eval" / "corpora" / "ATTRIBUTION.md"
    assert attr_path.is_file()
    with open(attr_path, encoding="utf-8") as f:
        content = f.read()

    assert "Tang" in content
    assert "Yang" in content
    assert "ODC-BY" in content
    assert "https://huggingface.co/datasets/yixuantt/MultiHopRAG" in content
    assert "unspecified" in content.lower()
