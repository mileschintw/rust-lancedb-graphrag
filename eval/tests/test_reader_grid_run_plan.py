"""The reader-grid run plan (D-291, #163).

`ReaderGridRunPlan` freezes which cells of a reader grid run, before any of them runs,
without an analysis plan: no Holm family, no decision rule. Each column is read through
`column_plan`, the view the replay harness reads (source arm, reader arms, K, prices,
the drive's tripwire). These tests check that the class refuses an inconsistent plan
and that a column's view carries exactly that column's cells.
"""

from __future__ import annotations

from typing import Any

import pytest

from lancet_eval import thresholds
from lancet_eval.reader_request import ReaderDeclaration, ReaderPrice

HAIKU = ReaderDeclaration(
    slug="anthropic/claude-haiku-5.5",
    target="openrouter",
    thinking="off",
    price=ReaderPrice(0.10, 0.50),
)
OPUS = ReaderDeclaration(
    slug="anthropic/claude-opus-5.5",
    target="openrouter",
    thinking="on",
    effort="low",
    price=ReaderPrice(4.0, 20.0),
)


def _valid(**over: Any) -> thresholds.ReaderGridRunPlan:
    fields: dict[str, Any] = {
        "benchmark": "twowiki",
        "split_file": "eval/corpora/twowiki/split.json",
        "split_sha256": "a" * 64,
        "population": "held-out",
        "question_count": 900,
        "columns": (
            ("closed-book", thresholds.GridColumn(source_arm="twowiki/closed-book")),
            (
                "hybrid",
                thresholds.GridColumn(source_arm="twowiki/hybrid+rerank+metadata"),
            ),
            (
                "graph-haiku",
                thresholds.GridColumn(
                    source_arm="twowiki/hybrid+graph+rerank+metadata",
                    graph_writer="haiku-5.5",
                ),
            ),
        ),
        "readers": (("haiku-5.5", HAIKU), ("opus-5.5", OPUS)),
        "replicates": 2,
        "reader_replicates": (("opus-5.5", 1),),
        "reference_price": ReaderPrice(0.0448, 0.30),
        "cells": (
            ("closed-book", "deepseek", "core"),
            ("closed-book", "haiku-5.5", "core"),
            ("hybrid", "deepseek", "core"),
            ("hybrid", "haiku-5.5", "core"),
            ("hybrid", "opus-5.5", "core"),
            ("graph-haiku", "deepseek", "core"),
            ("graph-haiku", "opus-5.5", "optional"),
        ),
        "transports": (
            ("deepseek", "engine_drive_then_openrouter_sync"),
            ("haiku-5.5", "openrouter_batch"),
            ("opus-5.5", "openrouter_batch"),
        ),
        "rerank_degrade_tripwire_rate": 0.20,
        "rerank_degrade_tripwire_min_calls": 50,
        "rerank_consecutive_degrade_halt": 5,
        "blinding_rule": "no score",
        "order_rule": "closed-book first",
        "report_rule": "run dirs and spend",
        "provenance": "test",
    }
    fields.update(over)
    return thresholds.ReaderGridRunPlan(**fields)


def test_a_consistent_plan_builds() -> None:
    plan = _valid()
    assert [name for name, _ in plan.columns] == [
        "closed-book",
        "hybrid",
        "graph-haiku",
    ]


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"columns": ()}, "columns"),
        (
            {
                "columns": (
                    ("hybrid", thresholds.GridColumn(source_arm="twowiki/hybrid")),
                    ("hybrid", thresholds.GridColumn(source_arm="twowiki/hybrid")),
                )
            },
            "columns",
        ),
        ({"cells": (("nowhere", "deepseek", "core"),)}, "column"),
        ({"cells": (("hybrid", "sonnet-5.5", "core"),)}, "reader"),
        ({"cells": (("hybrid", "haiku-5.5", "maybe"),)}, "tier"),
        (
            {
                "cells": (
                    ("hybrid", "haiku-5.5", "core"),
                    ("hybrid", "haiku-5.5", "optional"),
                )
            },
            "twice",
        ),
        ({"transports": (("deepseek", "openrouter_batch"),)}, "transports"),
        (
            {
                "transports": (
                    ("deepseek", "engine_drive_then_openrouter_sync"),
                    ("haiku-5.5", "pigeon"),
                    ("opus-5.5", "openrouter_batch"),
                )
            },
            "unknown transports",
        ),
        ({"reader_replicates": (("opus-5.5", 3),)}, "reader_replicates"),
        ({"replicates": 0}, "replicates"),
        ({"question_count": 0}, "question_count"),
        ({"split_sha256": "XYZ"}, "split_sha256"),
    ],
)
def test_an_inconsistent_plan_is_refused(over: dict[str, Any], message: str) -> None:
    with pytest.raises(thresholds.ThresholdError, match=message):
        _valid(**over)


def test_a_column_source_arm_must_be_a_plain_known_arm() -> None:
    with pytest.raises(thresholds.ThresholdError, match="source_arm"):
        _valid(
            columns=(
                (
                    "hybrid",
                    thresholds.GridColumn(
                        source_arm="twowiki/hybrid+rerank+metadata@haiku-5.5"
                    ),
                ),
            ),
            cells=(("hybrid", "deepseek", "core"),),
        )


def test_only_a_graph_source_arm_names_a_writer() -> None:
    with pytest.raises(thresholds.ThresholdError, match="graph_writer"):
        _valid(
            columns=(
                (
                    "hybrid",
                    thresholds.GridColumn(
                        source_arm="twowiki/hybrid+rerank+metadata",
                        graph_writer="haiku-5.5",
                    ),
                ),
            ),
            cells=(("hybrid", "deepseek", "core"),),
        )
    with pytest.raises(thresholds.ThresholdError, match="graph_writer"):
        _valid(
            columns=(
                (
                    "graph",
                    thresholds.GridColumn(
                        source_arm="twowiki/hybrid+graph+rerank+metadata"
                    ),
                ),
            ),
            cells=(("graph", "deepseek", "core"),),
        )


def test_between_tools_thinking_is_refused_on_the_batch_transport() -> None:
    sonnet = ReaderDeclaration(
        slug="anthropic/claude-sonnet-5.5",
        target="openrouter",
        thinking="between_tools",
        price=ReaderPrice(2.0, 10.0),
    )
    with pytest.raises(thresholds.ThresholdError, match="between_tools"):
        _valid(
            readers=(("haiku-5.5", HAIKU), ("opus-5.5", OPUS), ("sonnet-5.5", sonnet)),
            transports=(
                ("deepseek", "engine_drive_then_openrouter_sync"),
                ("haiku-5.5", "openrouter_batch"),
                ("opus-5.5", "openrouter_batch"),
                ("sonnet-5.5", "openrouter_batch"),
            ),
        )


def test_a_column_plan_carries_that_columns_cells_only() -> None:
    plan = _valid()
    view = plan.column_plan("hybrid")
    assert view.reference_arm == "twowiki/hybrid+rerank+metadata"
    assert view.replay_source_arm == "twowiki/hybrid+rerank+metadata"
    assert view.families == ()
    assert view.descriptive_arms == (
        "twowiki/hybrid+rerank+metadata@haiku-5.5",
        "twowiki/hybrid+rerank+metadata@opus-5.5",
    )
    assert dict(view.readers) == {"haiku-5.5": HAIKU, "opus-5.5": OPUS}
    assert view.replicates == 2
    assert view.reader_replicates == (("opus-5.5", 1),)
    assert view.reference_price == ReaderPrice(0.0448, 0.30)
    assert view.rerank_degrade_tripwire_rate == 0.20
    assert view.graph_writer is None
    assert view.column == "hybrid"


def test_a_graph_column_plan_names_its_writer_and_optional_cells() -> None:
    view = _valid().column_plan("graph-haiku")
    assert view.graph_writer == "haiku-5.5"
    assert view.descriptive_arms == ("twowiki/hybrid+graph+rerank+metadata@opus-5.5",)
    assert dict(view.readers) == {"opus-5.5": OPUS}


def test_a_closed_book_column_has_no_drive_and_no_tripwire() -> None:
    view = _valid().column_plan("closed-book")
    assert view.reference_arm == "twowiki/closed-book"
    assert view.rerank_degrade_tripwire_rate is None


def test_an_unknown_column_is_refused() -> None:
    with pytest.raises(thresholds.ThresholdError, match="no column"):
        _valid().column_plan("graph-nobody")


def test_a_column_without_its_deepseek_cell_is_refused() -> None:
    with pytest.raises(thresholds.ThresholdError, match="deepseek"):
        _valid(cells=(("hybrid", "haiku-5.5", "core"),))
