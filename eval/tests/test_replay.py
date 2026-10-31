"""S2 reader arms (#52, D-257): labels, the replay record kind and `replay-init`.

Seam S-F: a fixture S1 run (`replay_fixture`) is carried into an S2 journal by
`replay-init`; a reader arm's records are then appended as `batch fetch` (#53) will
write them, and the run scores with the deepseek arm and the reader arm paired.
"""

from __future__ import annotations

import pytest

from lancet_eval.arms import (
    READERS,
    arm_reader,
    arm_slug,
    arm_store,
    canonical_arm,
    in_registry_order,
    is_external_arm,
    is_reader_arm,
    judged_arms,
    reader_base_arm,
    request_fields,
    resolve_arm,
)

# ---- reader-arm labels ------------------------------------------------------------


def test_a_reader_arm_keeps_its_suffix_and_resolves_to_the_base_row() -> None:
    label = "merged/hybrid+rerank+metadata@haiku-5.5"
    assert canonical_arm(label) == label
    assert resolve_arm(label) == resolve_arm("hybrid+rerank+metadata")
    assert arm_store(label) == "eval-s1"
    assert arm_reader(label) == "haiku-5.5"
    assert reader_base_arm(label) == "merged/hybrid+rerank+metadata"
    assert is_reader_arm(label)
    assert not is_external_arm(label)


def test_the_base_arm_resolves_as_before() -> None:
    assert canonical_arm("graph-off") == "hybrid"
    assert arm_reader("merged/hybrid+rerank+metadata") is None
    assert not is_reader_arm("merged/hybrid+rerank+metadata")
    assert not is_reader_arm("no-such-arm@haiku-5.5")


@pytest.mark.parametrize(
    "label",
    [
        "hybrid@gpt-9",  # unknown reader
        "hybrid@",  # empty reader
        "no-such-arm@haiku-5.5",  # unknown base
        "graph-off@haiku-5.5",  # a legacy alias is never a base
        "hybrid@haiku-5.5@sonnet-5.5",  # two readers
        "tiny/hybrid@haiku-5.5",  # unknown store prefix
    ],
)
def test_a_bad_reader_arm_fails_closed_naming_the_label(label: str) -> None:
    with pytest.raises(ValueError, match="reader|arm|prefix"):
        canonical_arm(label)


def test_every_declared_reader_name_is_accepted() -> None:
    assert {"haiku-5.5", "sonnet-5.5", "opus-5.5"} <= set(READERS)
    for reader in READERS:
        assert arm_reader(f"hybrid+rerank+metadata@{reader}") == reader


def test_a_reader_arm_sends_no_gateway_request() -> None:
    with pytest.raises(ValueError, match="reader arm"):
        request_fields("hybrid+rerank+metadata@haiku-5.5")


def test_reader_arms_sort_after_their_base_and_are_never_judged() -> None:
    base = "merged/hybrid+rerank+metadata"
    labels = [f"{base}@sonnet-5.5", f"{base}@haiku-5.5", base, "hybrid"]
    assert in_registry_order(labels) == [
        "hybrid",
        base,
        f"{base}@haiku-5.5",
        f"{base}@sonnet-5.5",
    ]
    assert judged_arms(labels) == ["hybrid", base]


def test_a_reader_arm_slug_is_filesystem_safe() -> None:
    slug = arm_slug("merged/hybrid+rerank+metadata@haiku-5.5")
    assert slug == "merged_hybrid_rerank_metadata_haiku_5_5"
