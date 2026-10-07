"""Tests for the D-101 arm registry: labels, aliases, request flags and rotation."""

import pytest

from lancet_eval.arms import (
    ARM_REGISTRY,
    arm_slug,
    canonical_arm,
    is_legacy_label,
    request_fields,
    resolve_arm,
)


def test_registry_has_exactly_the_four_d101_labels_in_order() -> None:
    """D-116: no dense+graph or bm25+graph row exists."""
    assert set(ARM_REGISTRY) == {"dense-only", "bm25-only", "hybrid", "hybrid+graph"}
    assert list(ARM_REGISTRY) == ["dense-only", "bm25-only", "hybrid", "hybrid+graph"]


@pytest.mark.parametrize(
    ("stored", "canonical"),
    [
        ("graph-off", "hybrid"),
        ("graph-on", "hybrid+graph"),
        ("hybrid", "hybrid"),
        ("hybrid+graph", "hybrid+graph"),
        ("dense-only", "dense-only"),
        ("bm25-only", "bm25-only"),
    ],
)
def test_canonical_arm_resolves_aliases_at_lookup(stored: str, canonical: str) -> None:
    assert canonical_arm(stored) == canonical


@pytest.mark.parametrize("label", ["bm25+graph", "dense+graph", "", "Hybrid"])
def test_canonical_arm_rejects_an_unknown_label_naming_it(label: str) -> None:
    with pytest.raises(ValueError, match=repr(label).replace("+", r"\+")):
        canonical_arm(label)


def test_resolve_arm_unknown_label_message_keeps_the_legacy_prefix() -> None:
    with pytest.raises(ValueError) as excinfo:
        resolve_arm("unknown-arm")
    message = str(excinfo.value)
    assert message.startswith("Unknown arm 'unknown-arm'. Expected one of:")
    for label in (*ARM_REGISTRY, "graph-on", "graph-off"):
        assert label in message


def test_resolve_arm_accepts_aliases_and_returns_the_canonical_spec() -> None:
    assert resolve_arm("graph-off") is ARM_REGISTRY["hybrid"]
    assert resolve_arm("graph-on") is ARM_REGISTRY["hybrid+graph"]


@pytest.mark.parametrize(
    ("label", "slug"),
    [
        ("hybrid+graph", "hybrid_graph"),
        ("dense-only", "dense_only"),
        ("bm25-only", "bm25_only"),
        ("hybrid", "hybrid"),
    ],
)
def test_arm_slug(label: str, slug: str) -> None:
    assert arm_slug(label) == slug


def test_is_legacy_label_is_true_only_for_the_two_aliases() -> None:
    assert is_legacy_label("graph-on")
    assert is_legacy_label("graph-off")
    assert not any(is_legacy_label(label) for label in ARM_REGISTRY)
    assert not is_legacy_label("bogus")


def test_request_fields_legacy_bodies_are_byte_identical_to_drives_1_to_2() -> None:
    assert request_fields("graph-off") == {"disable_graph_context": True}
    assert request_fields("graph-on") == {}


def test_request_fields_canonical_labels_carry_mode_and_ranking_flag() -> None:
    assert request_fields("dense-only") == {
        "retrieval_mode": "dense_only",
        "disable_graph_context": True,
        "include_pre_truncation_ranking": True,
    }
    assert request_fields("bm25-only") == {
        "retrieval_mode": "bm25_only",
        "disable_graph_context": True,
        "include_pre_truncation_ranking": True,
    }
    assert request_fields("hybrid") == {
        "retrieval_mode": "hybrid",
        "disable_graph_context": True,
        "include_pre_truncation_ranking": True,
    }
    assert request_fields("hybrid+graph") == {
        "retrieval_mode": "hybrid",
        "include_pre_truncation_ranking": True,
    }


def test_request_fields_unknown_label_raises() -> None:
    with pytest.raises(ValueError, match="Unknown arm 'nope'"):
        request_fields("nope")


def test_no_deferred_d116_label_in_the_harness_source() -> None:
    from pathlib import Path

    import lancet_eval

    root = Path(lancet_eval.__file__).parent
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "dense+graph" not in text, path
        assert "bm25+graph" not in text, path
