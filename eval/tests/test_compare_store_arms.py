"""`compare` on a store-prefixed judged run (#34, D-251).

`compare` is the 06.3.5 four-arm comparison: its Holm families, P4 rebuild and strata
are fixed by `PREREGISTRATION_06_3_5`. A run whose corpus names another
pre-registration (#30's S1 fixture, on prefixed arms) is refused up front with a
message naming that mismatch, never the D-120 "run score --judged first" message its
prefixed judged dimensions used to trigger. No test makes a network call.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_score_judged_ordered import Scenario
from test_score_judged_store_arms import TOKEN, _build
from typer.testing import CliRunner

from lancet_eval import comparison as cmp_mod
from lancet_eval.cli import app
from lancet_eval.comparison import ComparisonError, build_comparison
from lancet_eval.gitcheck import PREREGISTRATION_TOKEN


@pytest.fixture(scope="module")
def prefixed(tmp_path_factory: pytest.TempPathFactory) -> Any:
    mp = pytest.MonkeyPatch()
    try:
        yield _build(tmp_path_factory.mktemp("compare-store-arms"), mp)
    finally:
        mp.undo()


def test_compare_refuses_a_run_under_another_preregistration(
    prefixed: Scenario,
) -> None:
    with pytest.raises(ComparisonError) as info:
        build_comparison(
            prefixed.run, gold_chunks_path=prefixed.gold, git_repo=prefixed.root
        )
    message = str(info.value)
    assert TOKEN in message
    assert PREREGISTRATION_TOKEN in message
    assert "compare-levers" in message
    assert "D-120" not in message
    assert "score --judged" not in message


def test_compare_refuses_prefixed_arms_left_on_the_06_3_5_token(
    prefixed: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = cmp_mod.load_corpus_config

    def default_token(corpus: str) -> Any:
        config = real(corpus)
        config.preregistration_token = PREREGISTRATION_TOKEN
        return config

    monkeypatch.setattr(cmp_mod, "load_corpus_config", default_token)
    with pytest.raises(ComparisonError) as info:
        build_comparison(
            prefixed.run, gold_chunks_path=prefixed.gold, git_repo=prefixed.root
        )
    message = str(info.value)
    assert "merged/hybrid+graph" in message
    assert PREREGISTRATION_TOKEN in message
    assert "D-120" not in message
    assert "compare-levers" not in message


def test_the_compare_command_exits_one_with_the_mismatch_and_writes_nothing(
    prefixed: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = cmp_mod.write_comparison
    monkeypatch.setattr(
        cmp_mod,
        "write_comparison",
        lambda run_dir, **kw: real(
            run_dir, gold_chunks_path=prefixed.gold, git_repo=prefixed.root
        ),
    )
    result = CliRunner().invoke(app, ["compare", "--run", str(prefixed.run)])
    assert result.exit_code == 1
    assert TOKEN in result.output
    assert "D-120" not in result.output
    for name in ("comparison.json", "comparison.md", "chart.json", "chart.svg"):
        assert not (prefixed.run / name).exists()


def test_the_unused_arm_slug_table_is_gone() -> None:
    assert not hasattr(cmp_mod, "_ARM_SLUGS")
