"""#164: an external arm's document IDs are checked against `external_store`.

A corpus whose Lancet arms run on another store than v1.0 names the store the
external arm (D-247) read its documents from; unset keeps the v1.0 map.
"""

from __future__ import annotations

import levers_fixture as fx
import pytest
from test_run_external import S0, FakeBin, _run, s0  # noqa: F401 (fixture)

from lancet_eval import corpus
from lancet_eval.config import S1_STORE, V1_STORE, EvalStore
from lancet_eval.corpus import CorpusError, load_corpus_config
from lancet_eval.score import ScoreError, score_run
from lancet_eval.seed import load_document_map


class _Map:
    def __init__(self, *docs: str) -> None:
        self.entries = dict.fromkeys(docs, object())
        self.aliases: dict[str, str] = {}


def _set_external_store(prefix: str) -> None:
    """Adds `external_store` to the fixture corpus (under the patched repo root)."""
    path = corpus._repo_root() / "eval" / "corpora" / f"{fx.CORPUS}.toml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("[documents]\n", f'[documents]\nexternal_store = "{prefix}"\n'),
        encoding="utf-8",
    )


def _maps(monkeypatch: pytest.MonkeyPatch, merged: _Map) -> list[str]:
    """The real v1.0 map for the Lancet arm; `merged` for the S1 store."""
    seen: list[str] = []

    def load(corpus: str, store: EvalStore = V1_STORE):  # type: ignore[no-untyped-def]
        seen.append(store.name)
        return merged if store == S1_STORE else load_document_map(corpus, store)

    monkeypatch.setattr("lancet_eval.score.load_document_map", load)
    return seen


def test_the_external_arm_reads_the_store_the_corpus_names(
    s0: S0,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run(s0, FakeBin())
    _set_external_store("merged")
    # The fixture's external rows cite the v1.0 document; the merged map holds it too.
    seen = _maps(monkeypatch, _Map(fx.doc_id()))
    score_run(run_dir=s0.run, no_judge=True, gold_chunks_path=s0.gold)
    assert S1_STORE.name in seen


def test_an_external_id_from_the_other_store_is_refused(
    s0: S0,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run(s0, FakeBin())
    _set_external_store("merged")
    # The merged map lacks the v1.0 document the external rows cite.
    _maps(monkeypatch, _Map("doc-merged-store"))
    with pytest.raises(ScoreError, match="D-247"):
        score_run(run_dir=s0.run, no_judge=True, gold_chunks_path=s0.gold)


def test_external_store_defaults_to_none_and_an_unknown_prefix_is_refused(
    s0: S0,  # noqa: F811
) -> None:
    assert load_corpus_config(fx.CORPUS).external_store is None
    _set_external_store("nowhere")
    with pytest.raises(CorpusError, match="external_store"):
        load_corpus_config(fx.CORPUS)


def test_compare_levers_reads_the_same_external_store(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from test_provenance import _s0_run, _score

    from lancet_eval.lever_comparison import (
        LeverComparisonError,
        build_lever_comparison,
    )

    run, gold, _ = _s0_run(tmp_path, monkeypatch)
    _score(run, gold)
    _set_external_store("merged")

    def load(corpus: str, store: EvalStore = V1_STORE):  # type: ignore[no-untyped-def]
        if store == S1_STORE:
            return _Map("doc-merged-store")
        return load_document_map(corpus, store)

    monkeypatch.setattr("lancet_eval.lever_comparison.load_document_map", load)
    with pytest.raises(LeverComparisonError, match="D-247"):
        build_lever_comparison(run, gold_chunks_path=gold)


def test_a_non_string_external_store_is_refused(s0: S0) -> None:  # noqa: F811
    path = corpus._repo_root() / "eval" / "corpora" / f"{fx.CORPUS}.toml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("[documents]\n", '[documents]\nexternal_store = ["full"]\n'),
        encoding="utf-8",
    )
    with pytest.raises(CorpusError, match="external_store"):
        load_corpus_config(fx.CORPUS)
