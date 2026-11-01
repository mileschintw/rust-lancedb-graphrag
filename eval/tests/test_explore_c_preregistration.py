"""#149 item C's pre-registration and corpus: S2X's readers on the full 609-document
store over the fresh dev questions.

`PREREGISTRATION_EXPLORE_C` is `PREREGISTRATION_S2X` moved to the `full/` store, with
Sonnet and Opus at K = 1. These tests pin that it differs from S2X only there, that its
corpus reads the fresh split's dev questions and all 609 documents, and that its run
directory can be committed.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess

import pytest

from lancet_eval import preregistration, thresholds
from lancet_eval.config import FULL_STORE, repo_root
from lancet_eval.corpus import load_corpus
from lancet_eval.split import lf_sha256, load_split, split_sha256

TOKEN = "PREREGISTRATION_EXPLORE_C"
CORPUS = "multihop_rag_full_dev"
SOURCE = "full/hybrid+rerank+metadata"
#: The LF-normalised sha256 of MultiHop-RAG's corpus.json (609 articles), as fetched.
CORPUS_JSON_SHA256 = "20b61b5ab84de84a927420c5d265b7ec8d859ae49980699958a787ade9e4d28f"
FRESH_SPLIT_SHA256 = "30d3dee89824cf4ef89b960a26889a2f1f8bed9128a47d341b93da0376d80e7d"
#: The fields where C differs from S2X by design (#149).
OWN = {"replay_source_arm", "reader_replicates", "default_rule", "provenance"}
ARM_FIELDS = {"reference_arm", "families", "descriptive_arms", "null_guard_arms"}
CACHE = repo_root() / "eval" / "corpora" / "multihop_rag" / ".cache" / "corpus.json"


def _c() -> thresholds.ReplayStagePreRegistration:
    pre = preregistration.resolve(TOKEN)
    assert isinstance(pre, thresholds.ReplayStagePreRegistration)
    return pre


def test_the_constant_replays_the_full_store_arm_with_per_reader_k() -> None:
    pre = _c()
    assert pre.replay_source_arm == pre.reference_arm == SOURCE
    assert pre.replicates == 2
    assert dict(pre.reader_replicates) == {"sonnet-5.5": 1, "opus-5.5": 1}
    assert pre.test == thresholds.REPLICATE_TEST


def test_the_arms_are_s2xs_arms_on_the_full_store() -> None:
    s2x, c = thresholds.PREREGISTRATION_S2X, _c()
    old = s2x.replay_source_arm

    def moved(labels: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(label.replace(old, SOURCE, 1) for label in labels)

    assert [f.arms for f in c.families] == [moved(f.arms) for f in s2x.families]
    assert c.descriptive_arms == moved(s2x.descriptive_arms)
    assert c.null_guard_arms == moved(s2x.null_guard_arms)


def test_every_other_field_is_s2xs() -> None:
    """Readers, prices, thinking and every number are S2X's, so readers compare."""
    s2x, c = thresholds.PREREGISTRATION_S2X, _c()
    for field in dataclasses.fields(c):
        if field.name not in OWN | ARM_FIELDS:
            assert getattr(c, field.name) == getattr(s2x, field.name), field.name


def test_the_rule_says_the_run_decides_nothing_and_cites_the_split() -> None:
    c = _c()
    assert "decides nothing" in c.default_rule
    assert "#149" in c.provenance
    assert FRESH_SPLIT_SHA256 in c.provenance


def test_the_corpus_reads_the_fresh_dev_set_and_all_609_documents() -> None:
    corpus = load_corpus(CORPUS)
    assert corpus.split_role == "dev"
    assert corpus.preregistration_token == TOKEN
    assert list(corpus.arms) == list(preregistration.arms_of(_c()))
    assert corpus.split_path is not None
    split = load_split(corpus.split_path)
    assert split_sha256(split) == FRESH_SPLIT_SHA256
    assert sorted(q.question_id for q in corpus.questions) == split.dev_ids
    assert corpus.documents_file == "multihop_rag/.cache/corpus.json"
    assert corpus.documents_sha256 == CORPUS_JSON_SHA256
    assert not corpus.commit_documents
    chunking = corpus.store_chunking["full"]
    assert (chunking.chunk_strategy, chunking.chunk_size, chunking.chunk_overlap) == (
        "structure-aware",
        500,
        50,
    )
    assert corpus.map_corpus == "multihop_rag_full"


@pytest.mark.skipif(
    not CACHE.is_file(),
    reason="needs the cached corpus.json (lancet-eval corpus fetch)",
)
def test_the_pinned_documents_file_holds_all_609_articles() -> None:
    assert lf_sha256(CACHE) == CORPUS_JSON_SHA256
    titles = {row["title"] for row in json.loads(CACHE.read_text(encoding="utf-8"))}
    assert len(titles) == 609


def test_the_full_store_has_its_own_document_map() -> None:
    from lancet_eval.seed import get_document_map_path

    path = get_document_map_path(CORPUS, FULL_STORE)
    assert path == (
        repo_root()
        / "eval"
        / "corpora"
        / "multihop_rag_full"
        / "document_map.eval-full.json"
    )


def test_the_run_directories_are_not_ignored() -> None:
    for name in ("2026-11-01-explore-c", "2026-11-01-explore-c-drive"):
        rel = f"eval/runs/{name}-{CORPUS}/journal.jsonl"
        result = subprocess.run(
            ["git", "check-ignore", "-q", rel], cwd=repo_root(), check=False
        )
        assert result.returncode == 1, f"{rel} is ignored"
