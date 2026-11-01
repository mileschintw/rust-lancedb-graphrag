"""The exploratory writer grid's pre-registration and corpus (#148).

`PREREGISTRATION_S3M` is S1's constant (`PREREGISTRATION_S1`) narrowed to the small
store's graph reading, read once per writer's graph at K = 2. It decides nothing. These
tests pin that it differs from S1 only where #148 says it does, and that its corpus
matches S1's.
"""

from __future__ import annotations

import dataclasses
import tomllib

from lancet_eval import preregistration, thresholds
from lancet_eval.config import repo_root
from lancet_eval.corpus import load_corpus

TOKEN = "PREREGISTRATION_S3M"
CORPUS = "multihop_rag_s3m_dev"
REFERENCE = "small/hybrid+rerank+metadata"
GRAPH = "small/hybrid+graph+rerank+metadata"
CORPORA = repo_root() / "eval" / "corpora"
#: The sections S3M copies from S1.
COPIED = ("documents", "questions", "document_subset", "split", "preflight")
#: The fields where S3M differs from S1 by design (#148).
OWN = {"test", "default_rule", "provenance"}
ARM_FIELDS = {"reference_arm", "families", "descriptive_arms", "null_guard_arms"}


def _s3m() -> thresholds.StagePreRegistration:
    pre = preregistration.resolve(TOKEN)
    assert isinstance(pre, thresholds.StagePreRegistration)
    return pre


def test_the_constant_pairs_s1s_small_graph_arm_with_its_reference() -> None:
    pre = _s3m()
    assert pre.reference_arm == REFERENCE
    assert [f.arms for f in pre.families] == [(GRAPH,)]
    assert pre.null_guard_arms == (GRAPH,)
    assert pre.descriptive_arms == ()
    assert pre.test == thresholds.REPLICATE_TEST


def test_every_other_field_is_s1s() -> None:
    s1, s3m = thresholds.PREREGISTRATION_S1, _s3m()
    for field in dataclasses.fields(s3m):
        if field.name not in OWN | ARM_FIELDS:
            assert getattr(s3m, field.name) == getattr(s1, field.name), field.name
    assert [(f.primary, f.role, f.alpha) for f in s3m.families] == [
        (f.primary, f.role, f.alpha) for f in s1.families
    ]


def test_the_rule_says_the_run_decides_nothing() -> None:
    pre = _s3m()
    assert "decides nothing" in pre.default_rule
    assert "2 times" in pre.default_rule
    assert "#148" in pre.provenance


def _toml(name: str) -> dict[str, object]:
    return tomllib.loads((CORPORA / f"{name}.toml").read_text(encoding="utf-8"))


def test_the_corpus_copies_s1s_sections_and_names_the_token() -> None:
    s1, s3m = _toml("multihop_rag_s1_dev"), _toml(CORPUS)
    for section in COPIED:
        assert s3m[section] == s1[section], section
    assert s3m["stores"] == {"small": s1["stores"]["small"]}
    assert s3m["preregistration"] == {"token": TOKEN}


def test_the_corpus_loads_with_the_constants_arms() -> None:
    corpus = load_corpus(CORPUS)
    assert corpus.split_role == "dev"
    assert corpus.preregistration_token == TOKEN
    assert list(corpus.arms) == list(preregistration.arms_of(_s3m()))
