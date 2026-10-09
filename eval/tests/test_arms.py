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


def test_registry_keeps_the_four_d101_labels_first_in_order() -> None:
    """D-116: no dense+graph or bm25+graph row exists; 06.3.6 appends lever arms."""
    labels = list(ARM_REGISTRY)
    assert labels[:4] == ["dense-only", "bm25-only", "hybrid", "hybrid+graph"]
    assert not {"dense+graph", "bm25+graph"} & set(labels)
    assert len(labels) == len(set(labels))


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


# --- 06.3.5-05 Task 3: seeded balanced rotation (D-107) ---


def _heldout_questions() -> list:
    from lancet_eval.corpus import load_sample_questions

    return load_sample_questions("multihop_rag_heldout")


def _split_seed() -> int:
    from lancet_eval.config import repo_root
    from lancet_eval.split import load_split

    split = load_split(
        repo_root() / "eval" / "corpora" / "multihop_rag" / "heldout_split.json"
    )
    return split.order_seed


def _legacy_arms() -> tuple[str, ...]:
    from lancet_eval.arms import LEGACY_ARM_LABELS

    return LEGACY_ARM_LABELS


def test_rotation_is_balanced_over_the_committed_351_question_split() -> None:
    from collections import Counter

    from lancet_eval.arms import plan_work_units

    arms = list(_legacy_arms())
    questions = _heldout_questions()
    assert len(questions) == 351
    units = plan_work_units(questions, arms, _split_seed())
    assert len(units) == 351 * 4

    # No question repeats, and each question's four arms run back to back.
    blocks = [units[i : i + 4] for i in range(0, len(units), 4)]
    assert len({b[0][0].question_id for b in blocks}) == 351
    for block in blocks:
        assert len({q.question_id for q, _ in block}) == 1
        assert sorted(a for _, a in block) == sorted(arms)

    first = Counter(block[0][1] for block in blocks)
    assert sorted(first.values(), reverse=True) == [88, 88, 88, 87]
    for position in range(4):
        held = Counter(block[position][1] for block in blocks)
        assert sorted(held.values(), reverse=True) == [88, 88, 88, 87]


def test_rotation_is_pure_and_independent_of_input_order() -> None:
    from lancet_eval.arms import plan_work_units

    arms = list(_legacy_arms())
    questions = _heldout_questions()
    seed = _split_seed()
    once = plan_work_units(questions, arms, seed)
    again = plan_work_units(list(questions), arms, seed)
    reversed_input = plan_work_units(list(reversed(questions)), arms, seed)

    def key(units: list) -> list[tuple[str, str]]:
        return [(q.question_id, a) for q, a in units]

    assert key(once) == key(again) == key(reversed_input)
    assert key(plan_work_units(questions, arms, seed + 1)) != key(once)


def test_rotation_with_fewer_questions_than_arms_still_runs_every_arm() -> None:
    from lancet_eval.arms import plan_work_units

    arms = list(_legacy_arms())
    units = plan_work_units(_heldout_questions()[:3], arms, 42)
    assert len(units) == 12


# --- 06.3.6-07: the lever arms (D-149, D-140, D-141) ---


def _selected() -> str:
    import json

    from lancet_eval.config import repo_root

    path = (
        repo_root()
        / ".planning"
        / "phases"
        / "06.3.6-quality-levers-measured-as-arms-reranker-graph-repair-by-dia"
        / "diagnostic"
        / "graph_diagnosis_selection.json"
    )
    return str(json.loads(path.read_text(encoding="utf-8"))["selected"])


def test_lever_arm_set_follows_selection() -> None:
    """`hybrid+graph-v2` exists iff the committed selection is not `none` (D-141)."""
    from lancet_eval.client import LEVER_ORDER

    built = _selected() != "none"
    assert ("hybrid+graph-v2" in ARM_REGISTRY) is built
    assert ("graph_v2" in LEVER_ORDER) is built
    for label in (
        "hybrid+rerank",
        "hybrid+metadata",
        "hybrid+answer-format",
        "hybrid+all",
    ):
        assert label in ARM_REGISTRY
    everything = ARM_REGISTRY["hybrid+all"]
    assert everything.levers == LEVER_ORDER
    assert everything.disable_graph_context is not ("graph_v2" in LEVER_ORDER)
    if built:
        v2 = ARM_REGISTRY["hybrid+graph-v2"]
        assert v2.levers == ("graph_v2",)
        assert v2.disable_graph_context is False


def test_the_control_arms_are_unchanged_and_carry_no_lever() -> None:
    for label in ("dense-only", "bm25-only", "hybrid", "hybrid+graph"):
        assert ARM_REGISTRY[label].levers == ()
    assert ARM_REGISTRY["hybrid"].disable_graph_context is True
    assert ARM_REGISTRY["hybrid+graph"].disable_graph_context is False


def test_single_lever_arms_switch_the_graph_off_and_name_one_lever() -> None:
    expected = {
        "hybrid+rerank": ("rerank",),
        "hybrid+metadata": ("evidence_metadata",),
        "hybrid+answer-format": ("binary_answer_format",),
    }
    for label, levers in expected.items():
        spec = ARM_REGISTRY[label]
        assert spec.retrieval_mode == "hybrid"
        assert spec.levers == levers
        assert spec.disable_graph_context is True


@pytest.mark.parametrize(
    ("levers", "disable", "needle"),
    [
        (("rerank", "rerank"), True, "duplicate"),
        (("evidence_metadata", "rerank"), True, "canonical"),
        (("not_a_lever",), True, "not_a_lever"),
        (("graph_v2",), True, "graph_v2"),
    ],
)
def test_arm_spec_refuses_a_bad_lever_list(
    levers: tuple[str, ...], disable: bool, needle: str
) -> None:
    from lancet_eval.arms import ArmSpec

    with pytest.raises(ValueError, match=needle):
        ArmSpec(
            label="hybrid+all",
            retrieval_mode="hybrid",
            disable_graph_context=disable,
            levers=levers,  # type: ignore[arg-type]
        )


def test_request_fields_add_levers_only_for_a_lever_arm() -> None:
    assert request_fields("hybrid+rerank")["levers"] == ["rerank"]
    assert request_fields("hybrid+all")["levers"] == list(
        ARM_REGISTRY["hybrid+all"].levers
    )
    for label in ("dense-only", "bm25-only", "hybrid", "hybrid+graph"):
        assert "levers" not in request_fields(label)
    assert request_fields("graph-off") == {"disable_graph_context": True}
    assert request_fields("graph-on") == {}
    assert request_fields("hybrid") == {
        "retrieval_mode": "hybrid",
        "disable_graph_context": True,
        "include_pre_truncation_ranking": True,
    }


def test_lever_echo_failures_compare_the_arm_levers_exactly() -> None:
    from lancet_eval.arms import lever_echo_failures

    assert lever_echo_failures("hybrid", []) == []
    assert lever_echo_failures("hybrid", None) == []
    assert lever_echo_failures("graph-off", []) == []
    assert lever_echo_failures("hybrid+rerank", ["rerank"]) == []
    for echo in ([], ["evidence_metadata"], ["rerank", "evidence_metadata"]):
        failures = lever_echo_failures("hybrid+rerank", echo)
        assert failures
        assert all("hybrid+rerank" in f for f in failures)
    assert lever_echo_failures("hybrid", ["rerank"])


def test_arm_slugs_of_the_lever_arms_are_filesystem_safe() -> None:
    assert arm_slug("hybrid+rerank") == "hybrid_rerank"
    assert arm_slug("hybrid+answer-format") == "hybrid_answer_format"
    assert arm_slug("hybrid+all") == "hybrid_all"


@pytest.mark.parametrize("n_arms", [6, 7])
def test_rotation_is_balanced_for_six_and_seven_arms(n_arms: int) -> None:
    from collections import Counter

    from lancet_eval.arms import plan_work_units

    arms = list(ARM_REGISTRY)[2 : 2 + n_arms]
    questions = _heldout_questions()
    units = plan_work_units(questions, arms, _split_seed())
    assert len(units) == len(questions) * n_arms
    blocks = [units[i : i + n_arms] for i in range(0, len(units), n_arms)]
    for block in blocks:
        assert len({q.question_id for q, _ in block}) == 1
        assert sorted(a for _, a in block) == sorted(arms)
    base, extra = divmod(len(questions), n_arms)
    for position in range(n_arms):
        held = Counter(block[position][1] for block in blocks)
        assert sorted(held.values()) == [base] * (n_arms - extra) + [base + 1] * extra
