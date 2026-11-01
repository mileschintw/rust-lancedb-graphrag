"""S3's writer pre-registration (#145, D-73).

`WriterPreRegistration` fixes what the 2Wiki writer extraction depends on: the pinned
passages, the extraction unit, the engine's request body and each writer's model and
thinking. These tests check that the class refuses an inconsistent constant, and that
`PREREGISTRATION_S3_WRITERS` matches the fetched source and the owner's thinking ruling.
"""

from __future__ import annotations

import dataclasses
import subprocess
from typing import Any

import pytest

from lancet_eval import thresholds, twowiki
from lancet_eval.config import repo_root
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


# ---- the frozen constant ---------------------------------------------------------


def _s3() -> thresholds.WriterPreRegistration:
    return thresholds.PREREGISTRATION_S3_WRITERS


def test_the_constant_pins_the_fetched_passages() -> None:
    pre = _s3()
    assert pre.dataset == twowiki.DATASET
    assert pre.dataset_revision == twowiki.REVISION
    assert pre.passages_file == twowiki.PASSAGES_FILE
    assert pre.passages_sha256 == twowiki.SOURCE_SHA256[twowiki.PASSAGES_FILE]
    assert pre.passage_count == twowiki.PASSAGE_COUNT


def test_the_engines_extraction_source_is_unchanged_since_the_freeze() -> None:
    """A change to the prompt or schema needs a new constant, not a silent drift."""
    pre = _s3()
    blob = subprocess.run(
        ["git", "rev-parse", f"HEAD:{pre.extraction_source}"],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert blob == pre.extraction_source_blob


def test_the_writers_and_their_thinking() -> None:
    """Owner rulings 2026-11-01: the lowest setting on the Batch API; Opus joins."""
    writers = dict(_s3().writers)
    assert {n: (d.thinking, d.effort) for n, d in writers.items()} == {
        "deepseek": ("off", None),
        "haiku-5.5": ("off", None),
        "sonnet-5.5": ("on", "low"),
        "opus-5.5": ("on", "low"),
    }
    assert writers["deepseek"].slug == "deepseek/deepseek-v4-flash-0731"
    # The engine extracts with its generation model (OpenRouterGenerationConfig).
    config = (repo_root() / "config" / "config.toml").read_text(encoding="utf-8")
    assert f'generation_model = "{writers["deepseek"].slug}"' in config
    assert dict(_s3().transports) == dict.fromkeys(writers, "openrouter_batch")


def test_the_claude_writers_match_s2s_slugs_and_prices() -> None:
    s2 = dict(thresholds.PREREGISTRATION_S2.readers)
    for name, declaration in _s3().writers:
        if name in s2:
            assert declaration.slug == s2[name].slug, name
            assert declaration.price == s2[name].price, name
            assert declaration.target == s2[name].target, name
