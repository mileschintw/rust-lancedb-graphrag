"""#146 prep: the confirmation stage's two full-corpus stores.

`multihop_rag_confirm_dev` seeds and preflights both stores over the fresh dev
questions. These tests pin that its small store is #149's eval-full as built, its
merged store chunks as S1's merged store does, and both read the same pinned 609
documents and the same fresh split as run C.
"""

from __future__ import annotations

import tomllib

from lancet_eval.arms import arm_store
from lancet_eval.config import FULL_MERGED_STORE, FULL_STORE, repo_root
from lancet_eval.corpus import load_corpus

CORPORA = repo_root() / "eval" / "corpora"


def _toml(name: str) -> dict:
    return tomllib.loads((CORPORA / f"{name}.toml").read_text(encoding="utf-8"))


def test_each_arm_runs_on_one_of_the_two_full_stores() -> None:
    config = load_corpus("multihop_rag_confirm_dev")
    assert [arm_store(a) for a in config.arms] == [
        FULL_STORE.name,
        FULL_MERGED_STORE.name,
    ]


def test_the_small_store_is_run_cs_store_and_the_merged_store_is_s1s() -> None:
    config = load_corpus("multihop_rag_confirm_dev")
    run_c = load_corpus("multihop_rag_full_dev")
    s1 = load_corpus("multihop_rag_s2x_dev")
    assert config.store_chunking["full"] == run_c.store_chunking["full"]
    assert config.store_chunking["fullmerged"] == s1.store_chunking["merged"]


def test_it_reads_run_cs_documents_questions_and_split() -> None:
    own, run_c = _toml("multihop_rag_confirm_dev"), _toml("multihop_rag_full_dev")
    for section in ("documents", "questions", "split", "preflight"):
        assert own[section] == run_c[section], section


def test_it_is_pre_registered_for_no_run() -> None:
    assert "preregistration" not in _toml("multihop_rag_confirm_dev")
