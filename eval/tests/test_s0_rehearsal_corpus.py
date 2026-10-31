"""The S0 rehearsal corpus (#76): S0's arms and pre-registration, no held-out read."""

from __future__ import annotations

from pathlib import Path

import pytest

from lancet_eval import preregistration
from lancet_eval.corpus import load_corpus, load_corpus_config
from lancet_eval.external_run import ExternalRunError, run_external

REHEARSAL = "multihop_rag_s0_rehearsal"


def test_the_rehearsal_drives_s0s_arms_under_s0s_constant() -> None:
    rehearsal = load_corpus_config(REHEARSAL)
    s0 = load_corpus_config("multihop_rag_s0_heldout")

    assert rehearsal.preregistration_token == s0.preregistration_token
    assert rehearsal.preregistration_token == "PREREGISTRATION_S0"
    assert list(rehearsal.arms) == list(s0.arms)
    pre = preregistration.resolve(rehearsal.preregistration_token)
    assert set(rehearsal.arms) == set(preregistration.arms_of(pre))


def test_the_rehearsal_reads_the_three_rehearsal_questions_only() -> None:
    config = load_corpus(REHEARSAL)

    assert config.split_role == "rehearsal"
    assert config.questions_file_rel == "multihop_rag/questions.rehearsal.jsonl"
    assert len(config.questions) == 3
    assert config.has_judge is False


def test_run_external_accepts_the_llamaindex_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The arm and split gates pass; the drive stops first at the missing export echo,
    # before any reader is called. D-73's clean-tree rule is lifted so the test holds
    # in a checkout with uncommitted edits; the token and split-hash gates still run.
    monkeypatch.setattr("lancet_eval.gitcheck.is_clean", lambda *a, **k: True)
    with pytest.raises(ExternalRunError, match="cannot read the pipeline echo"):
        run_external(
            corpus=REHEARSAL,
            arm="llamaindex",
            export_path=tmp_path / "context_export.jsonl",
            journal_path=tmp_path / "run" / "journal.jsonl",
            stage_spend_cap=1.0,
        )
