"""D-276 answer normalisation for `gold_contained` and `answer_usable` (#124).

The containment check keeps D-70's whole-token rule and adds two deterministic folds,
applied to every arm: list answers match in any order, and singular and plural fold
together. Each fold can only turn a miss into a hit; the cases below that must still
fail pin what it may not do.
"""

from __future__ import annotations

import pytest

from lancet_eval.corpus import GoldQuestion
from lancet_eval.metrics import answer_usable, gold_contained


def _q(gold: str) -> GoldQuestion:
    return GoldQuestion(question_id="q", question="?", gold_answer=gold)


# The three S1 cases on #124, with each arm's extracted final line.
def test_list_answer_in_another_order_is_usable() -> None:
    """mhr-f0d081eaba78: the small arms wrote the two names the other way round."""
    gold = "Taylor Swift and Travis Kelce"
    assert answer_usable(_q(gold), "Answer: travis kelce and taylor swift")
    assert answer_usable(_q(gold), "Answer: taylor swift and travis kelce")


def test_singular_matches_a_plural_gold() -> None:
    """mhr-ad4eee299dc7: every arm wrote "sportsbook" for the gold "Sportsbooks"."""
    assert answer_usable(_q("Sportsbooks"), "Answer: sportsbook")
    assert answer_usable(_q("sportsbook"), "Answer: Sportsbooks")


def test_the_no_lack_artifact_is_left_to_the_judge() -> None:
    """mhr-ab4e28055c90: gold "no". The reference arm is credited only by the "no" in
    "no lack of functionality", and the other arms say the articles align. The folds
    are lexical, so they change neither; the dual judge (D-276) is what reads it."""
    gold = _q("no")
    assert answer_usable(gold, "Answer: align no lack of functionality")
    assert not answer_usable(
        gold, "Answer: align both portray chatgpt as highly functional"
    )


@pytest.mark.parametrize(
    ("gold", "text"),
    [
        ("no", "I do not know"),  # D-70: "no" never matches inside "not" or "know"
        ("no", "nos"),
        ("Yes", "yesterday"),
        ("Taylor Swift and Travis Kelce", "taylor swift"),  # one item of two
        ("Taylor Swift and Travis Kelce", "taylor kelce and travis swift"),
        ("not", "note"),
        ("Plane", "plan"),  # only a plural ending folds; a final "e" never drops
        ("stripe", "strip"),
        ("paste", "past"),
        ("1990s", "1990"),  # a token with a digit never folds
        ("$1,200", "1 of 200"),  # a comma inside a number does not split a list
        ("Johnson & Johnson", "johnson"),  # each item needs its own span
        ("class", "clas"),  # "ss" is not a plural ending
        ("news", "new"),  # nor are a few common words ending in "s"
        ("bus", "bu"),
        ("Apple, Google and Meta", "apple and google"),
    ],
)
def test_misses_that_stay_misses(gold: str, text: str) -> None:
    assert not gold_contained(gold, text)


@pytest.mark.parametrize(
    ("gold", "text"),
    [
        ("Apple, Google and Meta", "meta google and apple"),
        ("Apple, Google & Meta", "google, apple, meta"),
        ("companies", "company"),
        ("boxes", "box"),
        ("matches", "match"),
        ("houses", "house"),  # -se words fold both ways
        ("caches", "cache"),
        ("classes", "class"),
        ("cases", "case"),
        ("movies", "movie"),
        ("buses", "bus"),
        ("Johnson & Johnson", "johnson and johnson"),
        ("Bears", "the bear"),
        ("Taylor Swift and Travis Kelce", "it was travis kelce with taylor swift"),
    ],
)
def test_hits_the_folds_add(gold: str, text: str) -> None:
    assert gold_contained(gold, text)


@pytest.mark.parametrize(
    ("gold", "text"),
    [
        ("no", "The answer is no."),
        ("Yes", "yes"),
        ("Taylor Swift and Travis Kelce", "taylor swift and travis kelce"),
    ],
)
def test_d70_hits_are_unchanged(gold: str, text: str) -> None:
    assert gold_contained(gold, text)


def test_the_d70_rule_can_be_pinned_for_v1_reproductions() -> None:
    """v1.0's recorded reports were written under D-70; a re-read pins it."""
    from lancet_eval.metrics import answer_rule

    with answer_rule("d70"):
        assert not gold_contained("Sportsbooks", "sportsbook")
        assert not gold_contained(
            "Taylor Swift and Travis Kelce", "travis kelce and taylor swift"
        )
        assert gold_contained("no", "the answer is no")
    assert gold_contained("Sportsbooks", "sportsbook")
    with pytest.raises(ValueError, match="d71"):
        with answer_rule("d71"):  # type: ignore[arg-type]
            pass
