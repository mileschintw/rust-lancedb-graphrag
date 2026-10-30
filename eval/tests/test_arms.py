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
    # D-198 / D-207: every canonical body states its graph state (false included) and
    # opts out of the configured default levers, so no arm inherits a server default.
    assert request_fields("dense-only") == {
        "retrieval_mode": "dense_only",
        "disable_graph_context": True,
        "disable_default_levers": True,
        "include_pre_truncation_ranking": True,
    }
    assert request_fields("bm25-only") == {
        "retrieval_mode": "bm25_only",
        "disable_graph_context": True,
        "disable_default_levers": True,
        "include_pre_truncation_ranking": True,
    }
    assert request_fields("hybrid") == {
        "retrieval_mode": "hybrid",
        "disable_graph_context": True,
        "disable_default_levers": True,
        "include_pre_truncation_ranking": True,
    }
    assert request_fields("hybrid+graph") == {
        "retrieval_mode": "hybrid",
        "disable_graph_context": False,
        "disable_default_levers": True,
        "include_pre_truncation_ranking": True,
    }


def test_d198_every_canonical_arm_sends_both_explicit_fields() -> None:
    """D-198 / D-207: each canonical arm names its graph state and opts out of defaults."""
    for label, spec in ARM_REGISTRY.items():
        fields = request_fields(label)
        assert fields["disable_graph_context"] is spec.disable_graph_context, label
        assert fields["disable_default_levers"] is True, label
        if spec.levers:
            assert fields["levers"] == list(spec.levers), label
        else:
            assert "levers" not in fields, label


def test_d198_lever_arm_bodies_state_their_graph_and_levers() -> None:
    assert request_fields("hybrid+rerank") == {
        "retrieval_mode": "hybrid",
        "disable_graph_context": True,
        "disable_default_levers": True,
        "include_pre_truncation_ranking": True,
        "levers": ["rerank"],
    }
    if "hybrid+graph-v2" in ARM_REGISTRY:
        assert request_fields("hybrid+graph-v2") == {
            "retrieval_mode": "hybrid",
            "disable_graph_context": False,
            "disable_default_levers": True,
            "include_pre_truncation_ranking": True,
            "levers": ["graph_v2"],
        }


def test_d198_explicit_default_fields_are_the_measurement_helper() -> None:
    from lancet_eval import arms as arms_module

    assert arms_module.explicit_default_fields("graph-on") == {
        "disable_graph_context": False,
        "disable_default_levers": True,
    }
    assert arms_module.explicit_default_fields("graph-off") == {
        "disable_graph_context": True,
        "disable_default_levers": True,
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
    # D-198 / D-207: a control arm now sends the opt-out beside its explicit graph state.
    assert request_fields("hybrid") == {
        "retrieval_mode": "hybrid",
        "disable_graph_context": True,
        "disable_default_levers": True,
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


def _record(label: str, *, notices=(), meta=None):  # type: ignore[no-untyped-def]
    from lancet_eval.client import Notice
    from lancet_eval.journal import RunRecord, WorkflowWireMeta

    return RunRecord(
        corpus="c",
        question_id="q",
        graph_arm=label,
        outcome="success",
        notices=[Notice(**n) for n in notices],
        workflow_meta=WorkflowWireMeta(**meta) if meta is not None else None,
    )


_N18 = {"code": "GRAPH_ABLATION", "typed_code": 18, "message": "m"}
_N24 = {"code": "DEFAULT_LEVER_UNAVAILABLE", "typed_code": 24, "message": "m"}
_N25 = {"code": "GRAPH_DISABLED_BY_CONFIG", "typed_code": 25, "message": "m"}
_N10 = {"code": "GRAPH_UNAVAILABLE", "typed_code": 10, "message": "m"}
_N2 = {"code": "GRAPH_TIMEOUT", "typed_code": 2, "message": "m"}
_RAN = {"graph_node_count": 3, "graph_seed_count": 1}


def test_d199_explicit_field_failures_accepts_a_correct_echo_for_each_graph_state() -> None:
    from lancet_eval.arms import explicit_field_failures

    off = _record("hybrid", notices=[_N18], meta={"graph_node_count": 0})
    on = _record("hybrid+graph", meta=_RAN)
    assert explicit_field_failures(off, resolve_arm("hybrid")) == []
    assert explicit_field_failures(on, resolve_arm("hybrid+graph")) == []


def test_d199_explicit_field_failures_flags_code_24_on_any_arm() -> None:
    from lancet_eval.arms import explicit_field_failures

    for label, notices, meta in (
        ("hybrid", [_N18, _N24], {"graph_node_count": 0}),
        ("hybrid+graph", [_N24], _RAN),
    ):
        failures = explicit_field_failures(
            _record(label, notices=notices, meta=meta), resolve_arm(label)
        )
        assert any("DEFAULT_LEVER_UNAVAILABLE" in f for f in failures), label
        assert all(f.startswith(f"arm {label!r}:") for f in failures)


def test_d199_explicit_field_failures_identifies_notices_by_typed_code_then_name() -> None:
    from lancet_eval.arms import explicit_field_failures

    by_number = {"code": "", "typed_code": 24, "message": "m"}
    by_name = {"code": "DEFAULT_LEVER_UNAVAILABLE", "typed_code": 0, "message": "m"}
    for notice in (by_number, by_name):
        record = _record("hybrid+graph", notices=[notice], meta=_RAN)
        assert explicit_field_failures(record, resolve_arm("hybrid+graph"))


def test_d199_explicit_field_failures_graph_off_arm_rules() -> None:
    from lancet_eval.arms import explicit_field_failures

    spec = resolve_arm("hybrid")
    # no code 18
    assert explicit_field_failures(_record("hybrid", meta={"graph_node_count": 0}), spec)
    # code 25 beside 18: the explicit true did not reach the engine as such
    assert explicit_field_failures(
        _record("hybrid", notices=[_N18, _N25], meta={"graph_node_count": 0}), spec
    )
    # GRAPH_UNAVAILABLE
    assert explicit_field_failures(
        _record("hybrid", notices=[_N18, _N10], meta={"graph_node_count": 0}), spec
    )
    # a non-zero graph counter on a graph-off arm
    assert explicit_field_failures(
        _record("hybrid", notices=[_N18], meta={"graph_node_count": 2}), spec
    )
    assert explicit_field_failures(
        _record("hybrid", notices=[_N18], meta={"graph_seed_count": 1}), spec
    )
    # a graph-off record with no metadata at all still passes on its notices
    assert explicit_field_failures(_record("hybrid", notices=[_N18]), spec) == []


def test_d199_explicit_field_failures_graph_on_arm_rules() -> None:
    from lancet_eval.arms import explicit_field_failures

    spec = resolve_arm("hybrid+graph")
    assert explicit_field_failures(_record("hybrid+graph", notices=[_N18], meta=_RAN), spec)
    assert explicit_field_failures(_record("hybrid+graph", notices=[_N25], meta=_RAN), spec)
    # no sign that the graph node ran
    assert explicit_field_failures(
        _record("hybrid+graph", meta={"graph_node_count": 0}), spec
    )
    assert explicit_field_failures(_record("hybrid+graph"), spec)
    # a graph that failed open still ran
    assert (
        explicit_field_failures(
            _record("hybrid+graph", notices=[_N10], meta={"graph_node_count": 0}), spec
        )
        == []
    )
    assert (
        explicit_field_failures(
            _record("hybrid+graph", notices=[_N2], meta={"graph_node_count": 0}), spec
        )
        == []
    )
    # a measured zero seed count is still proof the node ran
    assert (
        explicit_field_failures(
            _record("hybrid+graph", meta={"graph_node_count": 0, "graph_seed_count": 0}),
            spec,
        )
        == []
    )


def test_d199_legacy_labels_are_held_to_the_same_check() -> None:
    from lancet_eval.arms import explicit_field_failures

    assert explicit_field_failures(
        _record("graph-on", meta={"graph_node_count": 0}), resolve_arm("graph-on")
    )
    assert (
        explicit_field_failures(
            _record("graph-off", notices=[_N18], meta={"graph_node_count": 0}),
            resolve_arm("graph-off"),
        )
        == []
    )


# ---- v1.1: the S0 default row and the external arm kind (D-247) ----------------------


def test_the_s0_default_row_sends_rerank_and_metadata_with_the_graph_off() -> None:
    from lancet_eval.arms import explicit_field_failures
    from lancet_eval.journal import RunRecord

    spec = ARM_REGISTRY["hybrid+rerank+metadata"]
    assert spec.kind == "engine"
    assert request_fields("hybrid+rerank+metadata") == {
        "retrieval_mode": "hybrid",
        "disable_graph_context": True,
        "disable_default_levers": True,
        "include_pre_truncation_ranking": True,
        "levers": ["rerank", "evidence_metadata"],
    }
    from lancet_eval.client import Notice

    live = RunRecord(
        corpus="c",
        question_id="q",
        graph_arm="hybrid+rerank+metadata",
        outcome="success",
        notices=[Notice(code="GRAPH_ABLATION", message="", typed_code=18)],
    )
    assert explicit_field_failures(live, spec) == []


def test_the_external_arm_is_outside_the_engine_registry_and_its_modes() -> None:
    from lancet_eval.arms import EXTERNAL_ARMS, is_external_arm

    assert "llamaindex" not in ARM_REGISTRY
    spec = resolve_arm("llamaindex")
    assert spec is EXTERNAL_ARMS["llamaindex"]
    assert spec.kind == "external"
    assert spec.retrieval_mode == "external"
    assert spec.levers == ()
    assert canonical_arm("llamaindex") == "llamaindex"
    assert arm_slug("llamaindex") == "llamaindex"
    assert is_external_arm("llamaindex")
    assert not any(is_external_arm(label) for label in ARM_REGISTRY)
    assert not is_external_arm("graph-off")
    assert all(s.kind == "engine" for s in ARM_REGISTRY.values())


def test_an_external_arm_has_no_gateway_request() -> None:
    with pytest.raises(ValueError, match="external"):
        request_fields("llamaindex")


@pytest.mark.parametrize(
    "fields",
    [
        {"retrieval_mode": "hybrid", "kind": "external"},
        {"retrieval_mode": "external", "kind": "engine"},
        {"retrieval_mode": "external", "kind": "external", "levers": ("rerank",)},
    ],
)
def test_a_row_mixing_engine_and_external_traits_is_refused(
    fields: dict[str, object],
) -> None:
    from lancet_eval.arms import ArmSpec

    with pytest.raises(ValueError, match="external"):
        ArmSpec(label="llamaindex", disable_graph_context=True, **fields)  # type: ignore[arg-type]
