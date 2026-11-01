"""The exploratory merged-store reader run's pre-registration and corpus (#143).

`PREREGISTRATION_S2X` is S2's constant (`PREREGISTRATION_S2`) moved to S1's merged
graph-off arm at K = 2: the same readers, prices, thinking and numbers, so each reader
compares with S2 directly. It decides nothing. These tests pin that it differs from
S2 only where #143 says it does, and that its corpus matches S2's.
"""

from __future__ import annotations

import dataclasses
import subprocess
import tomllib

from lancet_eval import preregistration, thresholds
from lancet_eval.config import repo_root
from lancet_eval.corpus import load_corpus

TOKEN = "PREREGISTRATION_S2X"
CORPUS = "multihop_rag_s2x_dev"
SOURCE = "merged/hybrid+rerank+metadata"
CORPORA = repo_root() / "eval" / "corpora"
#: The sections S2X copies from S2, and so from S1.
COPIED = ("documents", "questions", "document_subset", "split", "stores")
#: The fields where S2X differs from S2 by design (#143).
OWN = {"replay_source_arm", "replicates", "default_rule", "provenance"}
ARM_FIELDS = {"reference_arm", "families", "descriptive_arms", "null_guard_arms"}


def _s2x() -> thresholds.ReplayStagePreRegistration:
    pre = preregistration.resolve(TOKEN)
    assert isinstance(pre, thresholds.ReplayStagePreRegistration)
    return pre


def test_the_constant_replays_s1s_merged_arm_at_two_replicates() -> None:
    pre = _s2x()
    assert pre.replay_source_arm == pre.reference_arm == SOURCE
    assert SOURCE in preregistration.arms_of(thresholds.PREREGISTRATION_S1)
    assert pre.replicates == 2
    assert pre.test == thresholds.REPLICATE_TEST


def test_the_arms_are_s2s_arms_on_the_merged_store() -> None:
    s2, s2x = thresholds.PREREGISTRATION_S2, _s2x()
    old = s2.replay_source_arm

    def moved(labels: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(label.replace(old, SOURCE, 1) for label in labels)

    assert [f.arms for f in s2x.families] == [moved(f.arms) for f in s2.families]
    assert s2x.descriptive_arms == moved(s2.descriptive_arms)
    assert s2x.null_guard_arms == moved(s2.null_guard_arms)


def test_every_other_field_is_s2s() -> None:
    """Readers, prices, thinking and every number are S2's, so readers compare."""
    s2, s2x = thresholds.PREREGISTRATION_S2, _s2x()
    for field in dataclasses.fields(s2x):
        if field.name not in OWN | ARM_FIELDS:
            assert getattr(s2x, field.name) == getattr(s2, field.name), field.name
    assert [(f.primary, f.role, f.alpha) for f in s2x.families] == [
        (f.primary, f.role, f.alpha) for f in s2.families
    ]


def test_the_rule_says_the_run_decides_nothing() -> None:
    assert "decides nothing" in _s2x().default_rule
    assert "#143" in _s2x().provenance


def _toml(name: str) -> dict[str, object]:
    return tomllib.loads((CORPORA / f"{name}.toml").read_text(encoding="utf-8"))


def test_the_corpus_copies_s2s_sections_and_names_the_token() -> None:
    s2, s2x = _toml("multihop_rag_s2_dev"), _toml(CORPUS)
    for section in COPIED:
        assert s2x[section] == s2[section], section
    assert s2x["preregistration"] == {"token": TOKEN}


def test_the_corpus_loads_with_the_constants_arms() -> None:
    corpus = load_corpus(CORPUS)
    assert corpus.split_role == "dev"
    assert corpus.preregistration_token == TOKEN
    assert list(corpus.arms) == list(preregistration.arms_of(_s2x()))


def test_the_run_directory_is_not_ignored_and_reads_as_a_lever_run() -> None:
    """Its name holds `-s2-`, which test_journal's lever-run exemption reads."""
    rel = f"eval/runs/2026-11-01-s2-{CORPUS}/journal.jsonl"
    result = subprocess.run(
        ["git", "check-ignore", "-q", rel], cwd=repo_root(), check=False
    )
    assert result.returncode == 1, f"{rel} is ignored"
