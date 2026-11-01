"""The v1.1 S2 pre-registration draft and its corpus (D-252, D-254 to D-265, #110).

D-73 dates a constant by the first commit that adds its name to `thresholds.py`, so
`PREREGISTRATION_S2` is not defined there until RUN-S2.md step 1 pastes in its draft,
the code block in EXPERIMENT-S2.md, with S1's winner in place of
`S1_WINNER_UNSET`. Until then the token names nothing and `resolve` refuses it. These
tests build the draft with each of S1's four arms and check that it resolves, matches
the S2 corpus and keeps S1's numbers, and that a constant pasted in later still equals
its draft. Step 4 commits it.
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lancet_eval import preregistration, thresholds
from lancet_eval.config import repo_root
from lancet_eval.corpus import load_corpus
from lancet_eval.reader_request import ReaderDeclaration, ReaderPrice

TOKEN = "PREREGISTRATION_S2"
S2_CORPUS = "multihop_rag_s2_dev"
PLACEHOLDER = "S1_WINNER_UNSET"
S1_ARMS = preregistration.arms_of(thresholds.PREREGISTRATION_S1)
CORPORA = repo_root() / "eval" / "corpora"
EXPERIMENT = repo_root() / "experiments" / "v1.1" / "EXPERIMENT-S2.md"
#: The sections S2 copies from S1: the same documents, questions, split and stores.
COPIED = ("documents", "questions", "document_subset", "split", "stores")


def draft_source() -> str:
    """The code block under EXPERIMENT-S2.md › The constant (draft)."""
    text = EXPERIMENT.read_text(encoding="utf-8")
    section = text.split("### The constant (draft)", 1)[1]
    (block,) = re.findall(r"^~~~python\n(.*?)^~~~$", section, re.S | re.M)[:1]
    return block


def build_draft(arm: str = PLACEHOLDER) -> Any:
    """The draft constant, its placeholder replaced by `arm`, built in thresholds."""
    namespace = dict(vars(thresholds))
    exec(draft_source().replace(PLACEHOLDER, arm), namespace)  # noqa: S102
    return namespace[TOKEN]


def corpus_source() -> str:
    """The arm the S2 corpus names now: the placeholder until RUN-S2.md step 1."""
    pre = getattr(thresholds, TOKEN, None)
    return PLACEHOLDER if pre is None else pre.replay_source_arm


def _s2_toml_text() -> str:
    return (CORPORA / f"{S2_CORPUS}.toml").read_text(encoding="utf-8")


def _load_filled_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: str
) -> Any:
    """Loads the S2 corpus with the arm it names replaced by `arm`."""
    corpora = tmp_path / "eval" / "corpora"
    corpora.mkdir(parents=True)
    (corpora / f"{S2_CORPUS}.toml").write_text(
        _s2_toml_text().replace(corpus_source(), arm), encoding="utf-8"
    )
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: tmp_path)
    return load_corpus(S2_CORPUS)


def test_the_draft_assigns_only_the_constant() -> None:
    import ast

    body = ast.parse(draft_source()).body
    assert [type(node) for node in body] == [ast.Assign]
    (target,) = body[0].targets  # type: ignore[attr-defined]
    assert target.id == TOKEN


def test_the_constant_is_absent_or_equals_its_draft() -> None:
    """Absent until RUN-S2.md step 4; after it, the draft and the constant agree."""
    pre = getattr(thresholds, TOKEN, None)
    if pre is None:
        with pytest.raises(preregistration.PreregistrationError, match="not defined"):
            preregistration.resolve(TOKEN)
        return
    assert isinstance(pre, thresholds.ReplayStagePreRegistration)
    assert pre.replay_source_arm in S1_ARMS
    assert pre == build_draft(pre.replay_source_arm)


def test_the_draft_holds_no_open_question() -> None:
    """D-267 to D-270 settled every TODO of the draft (2026-10-31)."""
    assert "TODO" not in draft_source()
    assert "TODO" not in EXPERIMENT.read_text(encoding="utf-8")


def test_an_unfilled_draft_and_corpus_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match=PLACEHOLDER):
        _load_filled_corpus(tmp_path, monkeypatch, PLACEHOLDER)
    monkeypatch.setattr(thresholds, TOKEN, build_draft(), raising=False)
    with pytest.raises(preregistration.PreregistrationError, match="unknown arm"):
        preregistration.resolve(TOKEN)


@pytest.mark.parametrize("arm", S1_ARMS)
def test_each_s1_winner_builds_a_constant_that_resolves(
    arm: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(thresholds, TOKEN, build_draft(arm), raising=False)
    pre = preregistration.resolve(TOKEN)
    assert pre.replay_source_arm == pre.reference_arm == arm
    assert pre.families[0].arms == (f"{arm}@haiku-5.5", f"{arm}@sonnet-5.5")
    assert pre.null_guard_arms == pre.families[0].arms
    assert pre.descriptive_arms == (f"{arm}@opus-5.5",)  # D-267
    assert set(preregistration.readers_of(pre)) == {
        "haiku-5.5",
        "sonnet-5.5",
        "opus-5.5",
    }


def test_the_corpus_copies_s1s_sections() -> None:
    import tomllib

    s1 = tomllib.loads((CORPORA / "multihop_rag_s1_dev.toml").read_text("utf-8"))
    s2 = tomllib.loads(_s2_toml_text())
    for section in COPIED:
        assert s2[section] == s1[section], section
    assert s2["preregistration"]["token"] == TOKEN
    bases = {label.partition("@")[0] for label in s2["arms"]["arms"]}
    assert bases == {corpus_source()}


@pytest.mark.parametrize("arm", S1_ARMS)
def test_each_s1_winner_fills_a_corpus_that_matches_s1_and_the_draft(
    arm: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s1 = load_corpus("multihop_rag_s1_dev")
    s2 = _load_filled_corpus(tmp_path, monkeypatch, arm)
    assert s2.split_role == "dev"
    assert s2.preregistration_token == TOKEN
    assert (s2.questions_file_rel, s2.sample_size) == (
        s1.questions_file_rel,
        s1.sample_size,
    )
    assert set(s2.arms) == set(preregistration.arms_of(build_draft(arm)))


def test_the_reader_table_is_the_decided_one() -> None:
    readers = dict(build_draft().readers)
    assert readers["haiku-5.5"] == ReaderDeclaration(
        slug="anthropic/claude-haiku-5.5",
        target="openrouter",
        thinking="off",
        price=ReaderPrice(input_per_mtok=0.10, output_per_mtok=0.50),
    )
    sonnet = readers["sonnet-5.5"]
    assert sonnet.thinking == "between_tools"
    assert sonnet.price == ReaderPrice(input_per_mtok=2.0, output_per_mtok=10.0)
    assert (sonnet.target, sonnet.slug) in {
        ("openrouter", "anthropic/claude-sonnet-5.5"),
        ("anthropic", "claude-sonnet-5-5"),
    }
    # D-269: Anthropic's list price, read 2026-10-31; over OpenRouter like Haiku.
    assert readers["opus-5.5"] == ReaderDeclaration(
        slug="anthropic/claude-opus-5.5",
        target="openrouter",
        thinking="on",
        effort="low",
        price=ReaderPrice(input_per_mtok=4.0, output_per_mtok=20.0),
    )


def test_the_numbers_are_s1s() -> None:
    s1 = thresholds.PREREGISTRATION_S1
    s2 = build_draft()
    arm_fields = {"reference_arm", "families", "descriptive_arms", "null_guard_arms"}
    own = {
        "default_rule",
        "provenance",
        "readers",
        "replay_source_arm",
        "replicates",
        "reference_price",
    }
    # D-274: replicates replace the sign test with the sign-flip permutation.
    assert s2.test == thresholds.REPLICATE_TEST and s2.replicates == 5
    own.add("test")
    for field in dataclasses.fields(s2):
        if field.name not in arm_fields | own:
            assert getattr(s2, field.name) == getattr(s1, field.name), field.name
    assert [(f.primary, f.role, f.alpha) for f in s2.families] == [
        ("answer_usable", "decisional", 0.05)
    ]
    assert s2.descriptive_arms == ("S1_WINNER_UNSET@opus-5.5",)


@pytest.mark.parametrize(
    "change",
    [
        {"reference_arm": "small/hybrid+rerank+metadata"},
        {"null_guard_arms": ("small/hybrid+rerank+metadata@haiku-5.5",)},
        {"descriptive_arms": ("small/hybrid+rerank+metadata@opus-5.5",)},
    ],
    ids=["reference", "guard", "descriptive"],
)
def test_an_arm_off_the_source_arm_is_refused(change: dict[str, Any]) -> None:
    pre = build_draft("merged/hybrid+rerank+metadata")
    with pytest.raises(thresholds.ThresholdError, match="replay_source_arm"):
        dataclasses.replace(pre, **change)


def test_the_s2_run_directory_is_not_ignored() -> None:
    rel = f"eval/runs/2026-11-02-s2-{S2_CORPUS}/journal.jsonl"
    result = subprocess.run(
        ["git", "check-ignore", "-q", rel], cwd=repo_root(), check=False
    )
    assert result.returncode == 1, f"{rel} is ignored"


def test_score_and_compare_levers_read_opus_as_a_descriptive_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, preregistered_clean_tree: str
) -> None:
    """D-267: an Opus arm with records is scored and reported, outside the family."""
    import replay_fixture as rf
    from test_reader_comparison import OPUS_ARM, _compare, _group, _s2, _score

    # The fixture run holds one answer per question and arm, so the draft is read at
    # one replicate (D-274's K = 5 path is test_replicates.py's).
    prereg = dataclasses.replace(
        build_draft(rf.BASE), replicates=1, test="paired_sign_flip_exact_two_sided"
    )
    s2, gold, qs = _s2(tmp_path, monkeypatch, prereg=prereg)
    _score(s2, gold)
    payload = _compare(s2, gold)

    (family,) = payload["families"]
    assert [c["arm"] for c in family["comparisons"]] == [
        f"{rf.BASE}@haiku-5.5",
        f"{rf.BASE}@sonnet-5.5",
    ]
    rows = {r["arm"]: r for r in _group(payload)["readers"]}
    opus = rows[OPUS_ARM]
    assert opus["answer_usable"]["n_usable"] == len(qs.g_ids) - 1
    assert opus["cost"]["n_answered"] == opus["answer_usable"]["n_usable"]
    assert opus["cost"]["per_answered_usd"] > 0
