"""S3's writer pre-registration (#145, D-73).

`WriterPreRegistration` fixes what the 2Wiki writer extraction depends on: the pinned
passages, the extraction unit, the engine's request body and each writer's model and
thinking. These tests check that the class refuses an inconsistent constant.
"""

from __future__ import annotations

import dataclasses
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


def _valid(**over: Any) -> thresholds.WriterPreRegistration:
    fields: dict[str, Any] = {
        "dataset": "osunlp/HippoRAG_2",
        "dataset_revision": "a" * 40,
        "passages_file": "2wikimultihopqa_corpus.json",
        "passages_sha256": "b" * 64,
        "passage_count": 3,
        "unit": "one passage",
        "extraction_source": "engine/src/graph/extraction.rs",
        "extraction_source_blob": "c" * 40,
        "request_rule": "the engine's body",
        "writers": (("haiku-5.5", HAIKU),),
        "transports": (("haiku-5.5", "openrouter_batch"),),
        "report_rule": "everything",
        "provenance": "test",
    }
    fields.update(over)
    return thresholds.WriterPreRegistration(**fields)


def test_a_consistent_constant_builds() -> None:
    assert dict(_valid().writers) == {"haiku-5.5": HAIKU}


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"writers": ()}, "non-empty"),
        (
            {"writers": (("haiku-5.5", HAIKU), ("haiku-5.5", HAIKU))},
            "unique",
        ),
        ({"transports": (("sonnet-5.5", "openrouter_batch"),)}, "transports name"),
        ({"transports": (("haiku-5.5", "sync"),)}, "unknown transports"),
        (
            {
                "writers": (
                    ("haiku-5.5", dataclasses.replace(HAIKU, thinking="between_tools")),
                )
            },
            "between_tools",
        ),
        ({"dataset_revision": "main"}, "dataset_revision"),
        ({"passages_sha256": "B" * 64}, "passages_sha256"),
        ({"extraction_source_blob": "c" * 39}, "extraction_source_blob"),
        ({"passage_count": 0}, "passage_count"),
    ],
)
def test_an_inconsistent_constant_is_refused(
    over: dict[str, Any], message: str
) -> None:
    with pytest.raises(thresholds.ThresholdError, match=message):
        _valid(**over)
