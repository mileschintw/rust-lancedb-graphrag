"""#149 item B's pre-registration and corpus: C's readers and K on a hybrid 2Wiki store
over the 100 D-243 dev questions.

`PREREGISTRATION_EXPLORE_B` is `PREREGISTRATION_EXPLORE_C` moved to the `twowiki/`
store. These tests pin that it differs from C only there, and that its corpus reads
#145's pinned passages, one chunk each, and the D-243 dev set.
"""

from __future__ import annotations

import dataclasses
import subprocess

import pytest

from lancet_eval import preregistration, thresholds, twowiki
from lancet_eval.config import TWOWIKI_STORE, repo_root
from lancet_eval.corpus import load_corpus
from lancet_eval.split import load_split, split_sha256

TOKEN = "PREREGISTRATION_EXPLORE_B"
CORPUS = "twowiki_s3b_dev"
SOURCE = "twowiki/hybrid+rerank+metadata"
S3B_SPLIT_SHA256 = "54a15e0781a51e70551230a5e4bbf44754b57d3f668341850027fa3b5934b76e"
DOCUMENTS_SHA256 = "57d038e26b2bfc10bdd91afcde3a2df30a79bad583f9b9f4f2aa3002d744e822"
OWN = {"replay_source_arm", "default_rule", "provenance"}
ARM_FIELDS = {"reference_arm", "families", "descriptive_arms", "null_guard_arms"}


def _b() -> thresholds.ReplayStagePreRegistration:
    pre = preregistration.resolve(TOKEN)
    assert isinstance(pre, thresholds.ReplayStagePreRegistration)
    return pre


def test_the_constant_is_cs_on_the_twowiki_store() -> None:
    c, b = thresholds.PREREGISTRATION_EXPLORE_C, _b()
    assert b.replay_source_arm == b.reference_arm == SOURCE

    def moved(labels: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(label.replace(c.replay_source_arm, SOURCE, 1) for label in labels)

    assert [f.arms for f in b.families] == [moved(f.arms) for f in c.families]
    assert b.descriptive_arms == moved(c.descriptive_arms)
    assert b.null_guard_arms == moved(c.null_guard_arms)
    for field in dataclasses.fields(b):
        if field.name not in OWN | ARM_FIELDS:
            assert getattr(b, field.name) == getattr(c, field.name), field.name


def test_the_rule_says_the_run_decides_nothing_and_cites_its_inputs() -> None:
    b = _b()
    assert "decides nothing" in b.default_rule
    assert "#149" in b.provenance
    assert S3B_SPLIT_SHA256 in b.provenance
    assert twowiki.REVISION in b.provenance


def test_the_corpus_reads_the_pinned_passages_one_chunk_each() -> None:
    corpus = load_corpus(CORPUS)
    assert corpus.split_role == "dev"
    assert corpus.preregistration_token == TOKEN
    assert list(corpus.arms) == list(preregistration.arms_of(_b()))
    assert corpus.split_path is not None
    assert split_sha256(load_split(corpus.split_path)) == S3B_SPLIT_SHA256
    assert corpus.documents_file == "twowiki/.cache/documents.jsonl"
    assert corpus.documents_sha256 == DOCUMENTS_SHA256
    assert not corpus.commit_documents
    chunking = corpus.store_chunking["twowiki"]
    assert (chunking.chunk_strategy, chunking.chunk_overlap) == ("fixed-size", 0)
    assert chunking.chunk_size == 8192


@pytest.mark.skipif(
    not (
        repo_root() / "eval" / "corpora" / "twowiki" / ".cache" / "documents.jsonl"
    ).is_file(),
    reason="needs python -m lancet_eval.twowiki_b",
)
def test_every_passage_fits_one_chunk_and_the_questions_are_the_dev_set() -> None:
    import json

    corpus = load_corpus(CORPUS)
    bodies = [
        json.loads(line)["body"]
        for line in corpus.documents_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(bodies) == twowiki.PASSAGE_COUNT
    assert (
        max(len(body) for body in bodies) <= corpus.store_chunking["twowiki"].chunk_size
    )
    split = load_split(corpus.split_path)  # type: ignore[arg-type]
    assert sorted(q.question_id for q in corpus.questions) == split.dev_ids


def test_the_twowiki_store_has_its_own_document_map() -> None:
    from lancet_eval.seed import get_document_map_path

    path = get_document_map_path(CORPUS, TWOWIKI_STORE)
    assert path == repo_root() / "eval" / "corpora" / "twowiki" / (
        "document_map.eval-2wiki.json"
    )


def test_the_run_directories_are_not_ignored() -> None:
    for name in ("2026-11-01-explore-b", "2026-11-01-explore-b-drive"):
        rel = f"eval/runs/{name}-{CORPUS}/journal.jsonl"
        result = subprocess.run(
            ["git", "check-ignore", "-q", rel], cwd=repo_root(), check=False
        )
        assert result.returncode == 1, f"{rel} is ignored"
