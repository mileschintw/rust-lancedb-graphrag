"""Tests for `lancet_eval.evidence_meta.normalise` (D-142, D-144)."""

from __future__ import annotations

import pytest

from lancet_eval.evidence_meta import FIELD_NAMES, normalise


def test_title_entities_are_unescaped() -> None:
    raw = {
        "title": "&#039;Massive intel failure by Mossad&#039;: Hamas&#039; attack",
    }
    title = normalise(raw)["doc_title"]
    assert title is not None
    assert title.startswith("'Massive intel failure by Mossad'")
    assert "&#039;" not in title


def test_amp_unescapes_and_whitespace_is_stripped() -> None:
    assert normalise({"title": "  Tom &amp; Jerry \n"})["doc_title"] == "Tom & Jerry"


def test_source_is_stripped_but_not_unescaped() -> None:
    assert normalise({"source": "  The Verge  "})["source"] == "The Verge"
    assert normalise({"source": "A &amp; B"})["source"] == "A &amp; B"


@pytest.mark.parametrize("empty", ["", "   ", "\n\t", None, 7])
def test_empty_or_non_string_values_become_none(empty: object) -> None:
    result = normalise({"title": empty, "source": empty, "published_at": empty})
    assert result == {"doc_title": None, "source": None, "published_date": None}


@pytest.mark.parametrize(
    ("published_at", "expected"),
    [
        ("2023-10-07T15:37:43+00:00", "2023-10-07"),
        ("2023-10-07T23:30:00-05:00", "2023-10-08"),
        ("2023-10-08T01:30:00+05:00", "2023-10-07"),
        ("2023-10-07T15:37:43", "2023-10-07"),
        ("not a date", None),
        ("07/10/2023", None),
    ],
)
def test_published_at_renders_as_utc_date(
    published_at: str, expected: str | None
) -> None:
    assert normalise({"published_at": published_at})["published_date"] == expected


def test_missing_keys_never_raise_and_all_keys_are_present() -> None:
    result = normalise({})
    assert tuple(result) == FIELD_NAMES
    assert all(value is None for value in result.values())
    assert normalise({"title": "T"})["source"] is None


def test_normalise_is_idempotent_on_its_own_output_title() -> None:
    once = normalise({"title": "&amp;amp; kept"})["doc_title"]
    # One decode pass only: a double-escaped entity decodes exactly once.
    assert once == "&amp; kept"
