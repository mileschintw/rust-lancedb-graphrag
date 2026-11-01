"""How a corpus reaches a reader-grid run plan (D-291, #163).

A corpus names the plan's constant in ``[preregistration] token`` and one of its
columns in ``column``. ``preregistration.resolve`` then returns that column's view,
which the replay harness reads like a replay pre-registration. Without a column, a run
plan is refused: that is how ``score`` and ``compare-levers`` stay blind to it (they
never pass one).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_reader_grid_run_plan import _valid

from lancet_eval import preregistration, thresholds
from lancet_eval.corpus import CorpusConfig, CorpusError


@pytest.fixture
def plan(monkeypatch: pytest.MonkeyPatch) -> thresholds.ReaderGridRunPlan:
    grid = _valid()
    monkeypatch.setattr(thresholds, "GRID_UNDER_TEST", grid, raising=False)
    return grid


def test_a_column_resolves_to_its_view(plan: thresholds.ReaderGridRunPlan) -> None:
    view = preregistration.resolve("GRID_UNDER_TEST", column="hybrid")
    assert isinstance(view, thresholds.ColumnRunPlan)
    assert view == plan.column_plan("hybrid", plan="GRID_UNDER_TEST")
    assert preregistration.arms_of(view) == (
        "twowiki/hybrid+rerank+metadata",
        "twowiki/hybrid+rerank+metadata@haiku-5.5",
        "twowiki/hybrid+rerank+metadata@opus-5.5",
    )
    assert set(preregistration.readers_of(view)) == {"haiku-5.5", "opus-5.5"}


def test_a_run_plan_without_a_column_is_refused(
    plan: thresholds.ReaderGridRunPlan,
) -> None:
    with pytest.raises(preregistration.PreregistrationError, match="D-291"):
        preregistration.resolve("GRID_UNDER_TEST")


def test_an_unknown_column_is_refused(plan: thresholds.ReaderGridRunPlan) -> None:
    with pytest.raises(preregistration.PreregistrationError, match="no column"):
        preregistration.resolve("GRID_UNDER_TEST", column="graph-nobody")


def test_a_column_on_a_stage_constant_is_refused() -> None:
    with pytest.raises(preregistration.PreregistrationError, match="not a run plan"):
        preregistration.resolve("PREREGISTRATION_EXPLORE_B", column="hybrid")


def _corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    corpora = tmp_path / "eval" / "corpora"
    corpora.mkdir(parents=True)
    (corpora / "grid.toml").write_text(text, encoding="utf-8")
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: tmp_path)


def test_resolve_corpus_passes_the_corpus_column(
    plan: thresholds.ReaderGridRunPlan,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _corpus(
        tmp_path,
        monkeypatch,
        '[documents]\nfile = "d.jsonl"\ncount = 1\n'
        '[questions]\nfile = "q.jsonl"\nlabel_format = "multihop_rag"\n'
        '[arms]\narms = ["twowiki/hybrid+rerank+metadata"]\n'
        '[stores.twowiki]\nchunk_strategy = "fixed-size"\nchunk_size = 8192\n'
        "chunk_overlap = 0\n"
        '[preregistration]\ntoken = "GRID_UNDER_TEST"\ncolumn = "hybrid"\n',
    )
    config = CorpusConfig("grid")
    assert config.preregistration_column == "hybrid"
    view = preregistration.resolve_corpus(config)
    assert view.column == "hybrid"


def test_a_corpus_column_must_be_a_non_empty_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _corpus(
        tmp_path,
        monkeypatch,
        '[documents]\nfile = "d.jsonl"\ncount = 1\n'
        '[questions]\nfile = "q.jsonl"\nlabel_format = "multihop_rag"\n'
        '[arms]\narms = ["hybrid"]\n'
        '[preregistration]\ntoken = "GRID_UNDER_TEST"\ncolumn = ""\n',
    )
    with pytest.raises(CorpusError, match="column"):
        CorpusConfig("grid")
