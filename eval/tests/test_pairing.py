"""Tests for ablation pairing, deduplication, and bootstrap statistics."""


import pytest

from lancet_eval.client import NodeFailed, Notice
from lancet_eval.corpus import GoldQuestion
from lancet_eval.journal import RunRecord
from lancet_eval.pairing import (
    ArmPair,
    compute_paired_delta,
    deduplicate_by_arm,
    form_pairs,
)
from lancet_eval.stats import bootstrap_mean_ci


def _make_record(
    qid: str,
    arm: str,
    *,
    outcome: str = "success",
    notices: list[Notice] | None = None,
    node_failures: list[NodeFailed] | None = None,
    answer: str = "ans",
) -> RunRecord:
    return RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm=arm,
        outcome=outcome,
        notices=notices or [],
        node_failures=node_failures or [],
        answer=answer,
    )


def _make_gold(
    qid: str, qtype: str = "comparison", is_null: bool = False
) -> GoldQuestion:
    facts = [] if is_null else ["fact1", "fact2"]
    ev_list = [] if is_null else [{"fact": "fact1"}, {"fact": "fact2"}]
    return GoldQuestion(
        question_id=qid,
        question=f"Question {qid}?",
        question_type=qtype,
        gold_facts=facts,
        evidence_list=ev_list,
    )


def test_deduplicate_by_arm_collapses_later_and_preserves_pair() -> None:
    """Proves two records per arm for one question collapse to two and preserve pair."""
    r1_on = _make_record("q1", "graph-on", answer="v1_on")
    r2_on = _make_record("q1", "graph-on", answer="v2_on")
    r1_off = _make_record(
        "q1",
        "graph-off",
        notices=[Notice(code="GRAPH_ABLATION", message="", typed_code=18)],
        answer="v1_off",
    )
    r2_off = _make_record(
        "q1",
        "graph-off",
        notices=[Notice(code="GRAPH_ABLATION", message="", typed_code=18)],
        answer="v2_off",
    )

    records = [r1_on, r1_off, r2_on, r2_off]
    deduped, collapsed = deduplicate_by_arm(records)

    assert collapsed == 2
    assert len(deduped) == 2
    by_arm = {r.graph_arm: r for r in deduped}
    assert by_arm["graph-on"].answer == "v2_on"
    assert by_arm["graph-off"].answer == "v2_off"

    # Form pairs
    gold_map = {"q1": _make_gold("q1")}
    join_res = form_pairs(deduped, gold_map)
    assert len(join_res.pairs) == 1
    assert join_res.pairs[0].graph_on.answer == "v2_on"
    assert join_res.pairs[0].graph_off.answer == "v2_off"


def test_form_pairs_single_arm_usable_drops() -> None:
    """Proves question usable in only one arm yields 0 pairs and counts drop."""
    r_on = _make_record("q1", "graph-on", outcome="success")
    # hard failure makes off unusable
    r_off = _make_record(
        "q1",
        "graph-off",
        outcome="error",
        notices=[Notice(code="GRAPH_ABLATION", message="", typed_code=18)],
    )

    gold_map = {"q1": _make_gold("q1")}
    join_res = form_pairs([r_on, r_off], gold_map)

    assert len(join_res.pairs) == 0
    assert join_res.single_arm_usable_drops == 1
    assert join_res.provenance_drops == 0


def test_form_pairs_provenance_failure_drops() -> None:
    """Proves usable graph-off missing notice 18 drops with provenance bucket."""
    r_on = _make_record("q1", "graph-on", outcome="success")
    # off is usable, but missing notice 18
    r_off_no_notice = _make_record("q1", "graph-off", outcome="success", notices=[])

    gold_map = {"q1": _make_gold("q1")}
    join_res1 = form_pairs([r_on, r_off_no_notice], gold_map)
    assert len(join_res1.pairs) == 0
    assert join_res1.provenance_drops == 1
    assert join_res1.single_arm_usable_drops == 0

    # Sibling test: off has notice 10 (graph unavailable)
    r_off_unavail = _make_record(
        "q1",
        "graph-off",
        outcome="success",
        notices=[
            Notice(code="GRAPH_ABLATION", message="", typed_code=18),
            Notice(code="GRAPH_UNAVAILABLE", message="", typed_code=10),
        ],
    )
    join_res2 = form_pairs([r_on, r_off_unavail], gold_map)
    assert len(join_res2.pairs) == 0
    assert join_res2.provenance_drops == 1
    assert join_res2.single_arm_usable_drops == 0


def test_form_pairs_null_gold_drops_and_counts() -> None:
    """Proves null question usable in both arms yields 0 pairs and counts null drop."""
    r_on = _make_record("q_null", "graph-on")
    r_off = _make_record(
        "q_null",
        "graph-off",
        notices=[Notice(code="GRAPH_ABLATION", message="", typed_code=18)],
    )

    gold_map = {"q_null": _make_gold("q_null", is_null=True)}
    join_res = form_pairs([r_on, r_off], gold_map)

    assert len(join_res.pairs) == 0
    assert join_res.null_gold_drops == 1
    assert join_res.total_distinct_questions == 1


def test_form_pairs_ordering_edge_deterministic_under_shuffle() -> None:
    """Proves shuffling journal input order produces identical sorted pair order."""
    records = []
    gold_map = {}
    for i in range(20):
        qid = f"q{i:02d}"
        gold_map[qid] = _make_gold(qid)
        records.append(_make_record(qid, "graph-on"))
        records.append(
            _make_record(
                qid,
                "graph-off",
                notices=[Notice(code="GRAPH_ABLATION", message="", typed_code=18)],
            )
        )

    res1 = form_pairs(records, gold_map)

    import random

    shuffled = list(records)
    random.Random(42).shuffle(shuffled)
    res2 = form_pairs(shuffled, gold_map)

    assert [p.question_id for p in res1.pairs] == [p.question_id for p in res2.pairs]
    assert [p.question_id for p in res1.pairs] == sorted(
        p.question_id for p in res1.pairs
    )


def test_bootstrap_mean_ci_deterministic_and_edges() -> None:
    """Proves bootstrap raises on empty, returns point on 1, and is bit-identical."""
    with pytest.raises(ValueError, match="n_pairs=0"):
        bootstrap_mean_ci([])

    mu, lo, hi = bootstrap_mean_ci([3.5])
    assert mu == 3.5
    assert lo == 3.5
    assert hi == 3.5

    data = [0.1, -0.2, 0.4, 0.5, -0.1, 0.05, 0.3]
    res1 = bootstrap_mean_ci(data, seed=42)
    res2 = bootstrap_mean_ci(data, seed=42)

    # Bit identical float comparison
    assert res1[0] == res2[0]
    assert res1[1] == res2[1]
    assert res1[2] == res2[2]


def test_compute_paired_delta_unscorable_pairs_and_stratification() -> None:
    """Proves unscorable pair is excluded and stratification groups by question type."""
    q1 = _make_gold("q1", qtype="comparison")
    q2 = _make_gold("q2", qtype="inference")
    q3 = _make_gold("q3", qtype="temporal")

    p1 = ArmPair(
        "q1", _make_record("q1", "graph-on"), _make_record("q1", "graph-off"), q1
    )
    p2 = ArmPair(
        "q2", _make_record("q2", "graph-on"), _make_record("q2", "graph-off"), q2
    )
    p3 = ArmPair(
        "q3", _make_record("q3", "graph-on"), _make_record("q3", "graph-off"), q3
    )

    # Score function: q1 has on=1.0, off=0.5 -> diff=0.5
    # q2 has on=None -> excluded
    # q3 has on=0.8, off=0.2 -> diff=0.6
    def score_fn(rec: RunRecord, gold: GoldQuestion) -> float | None:
        if gold.question_id == "q2" and rec.graph_arm == "graph-on":
            return None
        return 1.0 if rec.graph_arm == "graph-on" else 0.4

    res = compute_paired_delta(
        [p1, p2, p3],
        score_fn,
        coverage_denominator=10,
        answerable_count=3,
    )

    assert res.pair_count == 2
    assert res.excluded_count == 1
    assert res.pairing_coverage == 0.2
    assert res.mean == pytest.approx(0.6)
    # Stratification: comparison and temporal present, inference absent
    assert "comparison" in res.strata
    assert "temporal" in res.strata
    assert "inference" not in res.strata


def test_compute_paired_delta_all_pairs_unscorable_yields_no_score() -> None:
    """Proves all unscorable pairs returns None mean without invoking bootstrap."""
    q1 = _make_gold("q1", qtype="comparison")
    p1 = ArmPair(
        "q1", _make_record("q1", "graph-on"), _make_record("q1", "graph-off"), q1
    )

    res = compute_paired_delta(
        [p1],
        lambda rec, gold: None,
        coverage_denominator=10,
        answerable_count=1,
    )

    assert res.pair_count == 0
    assert res.mean is None
    assert res.ci_lower is None
    assert res.ci_upper is None
    assert res.excluded_count == 1


# ---------------------------------------------------------------------------
# 06.3.5-06 Task 1: registry-driven pairing (D-101)
# ---------------------------------------------------------------------------

_ABLATION = [Notice(code="GRAPH_ABLATION", message="", typed_code=18)]


def _need_arm_pairs():  # type: ignore[no-untyped-def]
    import lancet_eval.pairing as pairing

    fn = getattr(pairing, "form_arm_pairs", None)
    assert fn is not None, "pairing.form_arm_pairs is not defined"
    return fn


def test_form_arm_pairs_matches_the_requested_registry_pair() -> None:
    """`dense-only` against `hybrid` pairs those two records, not graph-on/off."""
    form_arm_pairs = _need_arm_pairs()
    records = [
        _make_record("q1", "dense-only", notices=_ABLATION, answer="dense"),
        _make_record("q1", "hybrid", notices=_ABLATION, answer="hybrid"),
        _make_record("q1", "hybrid+graph", answer="graph"),
        _make_record("q2", "dense-only", notices=_ABLATION),
    ]
    gold = {"q1": _make_gold("q1"), "q2": _make_gold("q2")}

    res = form_arm_pairs(
        records, gold, treatment_arm="dense-only", reference_arm="hybrid"
    )

    assert [p.question_id for p in res.pairs] == ["q1"]
    pair = res.pairs[0]
    assert pair.treatment.answer == "dense"
    assert pair.reference.answer == "hybrid"
    assert res.missing_arm_drops == 1
    assert res.total_distinct_questions == 2


def test_form_arm_pairs_equals_form_pairs_on_legacy_records() -> None:
    """Over legacy-labelled records the canonical pair is `form_pairs`, element by
    element, and the historical field names are the same objects as the aliases."""
    form_arm_pairs = _need_arm_pairs()
    records = []
    gold = {}
    for qid in ("q1", "q2", "q3", "q4"):
        records.append(_make_record(qid, "graph-on", answer=f"on-{qid}"))
        records.append(
            _make_record(qid, "graph-off", notices=_ABLATION, answer=f"off-{qid}")
        )
        gold[qid] = _make_gold(qid, is_null=(qid == "q4"))
    records[2] = _make_record("q2", "graph-on", outcome="error")

    legacy = form_pairs(records, gold)
    canonical = form_arm_pairs(
        records, gold, treatment_arm="hybrid+graph", reference_arm="hybrid"
    )

    assert canonical == legacy
    for pair in canonical.pairs:
        assert pair.treatment is pair.graph_on
        assert pair.reference is pair.graph_off


def test_form_arm_pairs_requires_provenance_on_a_graph_disabled_treatment() -> None:
    form_arm_pairs = _need_arm_pairs()
    records = [
        _make_record("q1", "dense-only"),
        _make_record("q1", "hybrid", notices=_ABLATION),
    ]
    res = form_arm_pairs(
        records,
        {"q1": _make_gold("q1")},
        treatment_arm="dense-only",
        reference_arm="hybrid",
    )
    assert res.pairs == []
    assert res.provenance_drops == 1


def test_form_arm_pairs_refuses_an_alias_and_its_canonical_label() -> None:
    form_arm_pairs = _need_arm_pairs()
    records = [
        _make_record("q1", "graph-off", notices=_ABLATION),
        _make_record("q1", "hybrid", notices=_ABLATION),
        _make_record("q1", "graph-on"),
    ]
    with pytest.raises(ValueError, match="q1"):
        form_arm_pairs(
            records,
            {"q1": _make_gold("q1")},
            treatment_arm="hybrid+graph",
            reference_arm="hybrid",
        )


def test_form_arm_pairs_does_not_demand_ablation_provenance_of_a_graph_reference() -> (
    None
):
    """A graph-enabled reference carries no GRAPH_ABLATION notice; none is required."""
    form_arm_pairs = _need_arm_pairs()
    records = [
        _make_record("q1", "hybrid+graph"),
        _make_record("q1", "hybrid", notices=_ABLATION),
    ]
    res = form_arm_pairs(
        records,
        {"q1": _make_gold("q1")},
        treatment_arm="hybrid",
        reference_arm="hybrid+graph",
    )
    assert [p.question_id for p in res.pairs] == ["q1"]
    assert res.provenance_drops == 0


def test_form_arm_pairs_still_requires_provenance_on_a_graph_disabled_reference() -> (
    None
):
    form_arm_pairs = _need_arm_pairs()
    records = [
        _make_record("q1", "hybrid+graph"),
        _make_record("q1", "hybrid"),
    ]
    res = form_arm_pairs(
        records,
        {"q1": _make_gold("q1")},
        treatment_arm="hybrid+graph",
        reference_arm="hybrid",
    )
    assert res.pairs == []
    assert res.provenance_drops == 1
