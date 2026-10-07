"""Tests for p4.py: the P4 population and the paired reads (D-121, D-122)."""

from __future__ import annotations

import pytest

from lancet_eval.arms import ARM_REGISTRY
from lancet_eval.client import (
    Notice,
    RankedCandidate,
    RetrievalSnapshot,
    StructuredCitation,
)
from lancet_eval.corpus import GoldQuestion
from lancet_eval.journal import RunRecord, WorkflowWireMeta
from lancet_eval.metrics import answer_usable
from lancet_eval.p4 import (
    build_p4,
    discordant_counts,
    judged_pairs,
    paired_delta,
    per_question_values,
)
from lancet_eval.split import HeldOutSplit
from lancet_eval.stats import BOOTSTRAP_B, BOOTSTRAP_SEED, bootstrap_mean_ci

ARMS = ("dense-only", "bm25-only", "hybrid", "hybrid+graph")
ABLATION = Notice(code="GRAPH_ABLATION", message="", typed_code=18)
NO_EVIDENCE = Notice(code="NO_EVIDENCE", message="", typed_code=1)
HEX = "0" * 64


def _split(n_g: int = 10, n_null: int = 2) -> HeldOutSplit:
    return HeldOutSplit(
        derivation_rule="test",
        populations_sha256=HEX,
        diag_selection_sha256=HEX,
        questions_sample_sha256=HEX,
        dev_source="dev.json",
        order_seed=1,
        dev_ids=["dev1"],
        heldout_g_ids=[f"g{i:02d}" for i in range(n_g)],
        heldout_null_ids=[f"n{i:02d}" for i in range(n_null)],
    )


def _ranking(arm: str, n: int) -> list[RankedCandidate]:
    mode = ARM_REGISTRY[arm].retrieval_mode
    return [
        RankedCandidate(
            chunk_id=f"d{i}:0",
            document_id=f"d{i}",
            fused_rank=i,
            vector_rank=i if mode != "bm25_only" else None,
            bm25_rank=i if mode != "dense_only" else None,
            graph_rank=None,
            graph_boosted=False,
        )
        for i in range(1, n + 1)
    ]


def _final(ranking: list[RankedCandidate], limit: int = 8) -> list[StructuredCitation]:
    return [
        StructuredCitation(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            rank=r.fused_rank,
            graph_boosted=r.graph_boosted,
        )
        for r in ranking[:limit]
    ]


def _record(
    arm: str,
    qid: str,
    *,
    answer: str = "Answer: Yes",
    error: bool = False,
    no_evidence: bool = False,
    drop_ablation: bool = False,
) -> RunRecord:
    """A well-formed record of a canonical arm, with the knobs the tests turn."""
    spec = ARM_REGISTRY[arm]
    ranking = [] if no_evidence else _ranking(arm, 12)
    snapshot = RetrievalSnapshot(
        index_generation="gen1",
        vector_weight=1.0,
        bm25_weight=1.0,
        rrf_k=60,
        candidate_limit=32,
        final_limit=8,
        result_hash="abc123",
        retrieved_chunks=_final(ranking),
        retrieval_mode=spec.retrieval_mode,
        pre_truncation_ranking=ranking,
    )
    notices: list[Notice] = []
    if spec.disable_graph_context and not drop_ablation:
        notices.append(ABLATION)
    if no_evidence:
        notices.append(NO_EVIDENCE)
    return RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm=arm,
        outcome="error" if error else "success",
        answer="" if no_evidence else answer,
        snapshot=snapshot,
        notices=notices,
        structured_citations=[] if no_evidence else _final(ranking)[:1],
        workflow_meta=WorkflowWireMeta(
            vector_count=0 if spec.retrieval_mode == "bm25_only" else 8,
            bm25_count=0 if spec.retrieval_mode == "dense_only" else 8,
        ),
    )


def _journal(split: HeldOutSplit, **overrides: RunRecord) -> list[RunRecord]:
    """Every arm answers every G question; `overrides` replace `arm|qid` records."""
    out: list[RunRecord] = []
    for qid in split.heldout_g_ids:
        for arm in ARMS:
            out.append(overrides.get(f"{arm}|{qid}") or _record(arm, qid))
    return out


def _flawed_journal(split: HeldOutSplit) -> list[RunRecord]:
    """g03: dense-only errored. g07: bm25-only lost its GRAPH_ABLATION notice."""
    return _journal(
        split,
        **{
            "dense-only|g03": _record("dense-only", "g03", error=True),
            "bm25-only|g07": _record("bm25-only", "g07", drop_ablation=True),
        },
    )


def test_build_p4_drops_an_error_and_a_provenance_failure() -> None:
    split = _split()
    p4 = build_p4(_flawed_journal(split), split, ARMS)
    assert len(p4.question_ids) == 8
    assert "g03" not in p4.question_ids
    assert "g07" not in p4.question_ids
    assert p4.question_ids == tuple(sorted(p4.question_ids))
    assert p4.arms == ARMS
    assert p4.n_heldout_g == 10
    assert p4.coverage == pytest.approx(0.8)


def test_build_p4_reports_exclusions_per_arm_by_reason() -> None:
    split = _split()
    ex = build_p4(_flawed_journal(split), split, ARMS).excluded
    assert (ex["dense-only"].own_failure, ex["dense-only"].provenance) == (1, 0)
    assert ex["dense-only"].other_arm_failure == 1
    assert (ex["bm25-only"].own_failure, ex["bm25-only"].provenance) == (0, 1)
    assert ex["bm25-only"].other_arm_failure == 1
    for arm in ("hybrid", "hybrid+graph"):
        assert ex[arm].own_failure == 0
        assert ex[arm].provenance == 0
        assert ex[arm].other_arm_failure == 2


def test_build_p4_reports_each_pairwise_join_with_hybrid() -> None:
    split = _split()
    p4 = build_p4(_flawed_journal(split), split, ARMS)
    assert p4.reference_arm == "hybrid"
    assert p4.pairwise_join_sizes == {
        "dense-only": 9,  # g03 is dense-only's own failure
        "bm25-only": 9,  # g07 fails bm25-only's provenance
        "hybrid+graph": 10,
    }


def test_build_p4_matches_arms_by_canonical_label() -> None:
    split = _split(n_g=2)
    records = [
        _record("hybrid", "g00").model_copy(update={"graph_arm": "graph-off"}),
        _record("hybrid+graph", "g00").model_copy(update={"graph_arm": "graph-on"}),
        _record("hybrid", "g01").model_copy(update={"graph_arm": "graph-off"}),
        _record("hybrid+graph", "g01").model_copy(update={"graph_arm": "graph-on"}),
    ]
    p4 = build_p4(records, split, ("graph-off", "graph-on"))
    assert p4.question_ids == ("g00", "g01")
    assert p4.arms == ("hybrid", "hybrid+graph")


def test_build_p4_ignores_questions_outside_heldout_g() -> None:
    split = _split(n_g=2)
    records = _journal(split) + [_record(a, "stray") for a in ARMS]
    p4 = build_p4(records, split, ARMS)
    assert p4.question_ids == ("g00", "g01")


def test_a_missing_record_is_the_arms_own_failure() -> None:
    split = _split(n_g=3)
    records = [
        r
        for r in _journal(split)
        if not (r.graph_arm == "hybrid" and r.question_id == "g01")
    ]
    p4 = build_p4(records, split, ARMS)
    assert "g01" not in p4.question_ids
    assert p4.excluded["hybrid"].own_failure == 1


def test_build_p4_validates_arms() -> None:
    split = _split(n_g=1)
    with pytest.raises(ValueError, match="same arm"):
        build_p4([], split, ("hybrid", "graph-off"))
    with pytest.raises(ValueError):
        build_p4([], split, ("hybrid", "nonsense"))
    with pytest.raises(ValueError, match="reference"):
        build_p4([], split, ("dense-only", "bm25-only"))


def test_an_empty_split_has_zero_coverage() -> None:
    split = _split(n_g=0)
    assert build_p4([], split, ARMS).coverage == 0.0


def test_a_blank_no_evidence_record_stays_in_p4_scores_zero_and_abstains() -> None:
    split = _split(n_g=4)
    declined = _record("bm25-only", "g02", no_evidence=True)
    records = _journal(split, **{"bm25-only|g02": declined})
    p4 = build_p4(records, split, ARMS)
    assert "g02" in p4.question_ids
    assert p4.coverage == 1.0
    gold = GoldQuestion(
        question_id="g02", question="q?", gold_facts=["f"], gold_answer="Yes"
    )

    def value(rec: RunRecord) -> float:
        return float(answer_usable(gold, rec.answer or ""))

    values = per_question_values(records, p4, "bm25-only", value)
    assert values["g02"] == 0.0
    assert values["g00"] == 1.0
    from lancet_eval.metrics import is_abstention

    assert is_abstention(declined)


def test_per_question_values_are_in_p4_order_and_reject_a_foreign_arm() -> None:
    split = _split(n_g=3)
    records = _journal(split)
    p4 = build_p4(records, split, ("hybrid", "dense-only"))
    values = per_question_values(records, p4, "dense-only", lambda r: 1.0)
    assert list(values) == list(p4.question_ids)
    with pytest.raises(ValueError, match="not in this P4"):
        per_question_values(records, p4, "bm25-only", lambda r: 1.0)


def test_paired_delta_equals_the_difference_of_means_exactly() -> None:
    x = {"a": 1.0, "b": 1.0, "c": 0.0, "d": 1.0, "e": 0.0, "f": 1.0, "g": 1.0}
    ref = {"a": 1.0, "b": 0.0, "c": 0.0, "d": 0.0, "e": 0.0, "f": 1.0, "g": 0.0}
    result = paired_delta(x, ref)
    assert result.n == 7
    assert result.delta == sum(x.values()) / 7 - sum(ref.values()) / 7
    diffs = [x[k] - ref[k] for k in sorted(x)]
    _, lo, hi = bootstrap_mean_ci(diffs, seed=BOOTSTRAP_SEED, b=BOOTSTRAP_B)
    assert (result.ci_lower, result.ci_upper) == (lo, hi)
    assert result.ci_lower <= result.delta <= result.ci_upper


def test_paired_delta_uses_b_10000_and_seed_42_by_default() -> None:
    assert BOOTSTRAP_B == 10_000
    assert BOOTSTRAP_SEED == 42
    x = {str(i): float(i % 2) for i in range(20)}
    ref = {str(i): float(i % 3 == 0) for i in range(20)}
    assert paired_delta(x, ref) == paired_delta(x, ref, b=10_000, seed=42)


def test_paired_delta_refuses_mismatched_or_empty_inputs() -> None:
    with pytest.raises(ValueError, match="same questions"):
        paired_delta({"a": 1.0}, {"b": 1.0})
    with pytest.raises(ValueError, match="n=0"):
        paired_delta({}, {})


def test_discordant_counts_ignore_ties() -> None:
    x = {"a": 1.0, "b": 1.0, "c": 0.0, "d": 0.0, "e": 1.0}
    ref = {"a": 0.0, "b": 1.0, "c": 1.0, "d": 0.0, "e": 0.0}
    assert discordant_counts(x, ref) == (2, 1)
    assert discordant_counts(ref, x) == (1, 2)
    with pytest.raises(ValueError, match="same questions"):
        discordant_counts({"a": 1.0}, {"z": 1.0})


def test_judged_pairs_counts_each_selection_bucket() -> None:
    split = _split(n_g=6)
    abstain = "Answer: Insufficient information"
    records = _journal(
        split,
        **{
            # g01: only X (dense-only) abstains
            "dense-only|g01": _record("dense-only", "g01", answer=abstain),
            # g02: only the reference abstains
            "hybrid|g02": _record("hybrid", "g02", answer=abstain),
            # g03: both abstain
            "dense-only|g03": _record("dense-only", "g03", answer=abstain),
            "hybrid|g03": _record("hybrid", "g03", answer=abstain),
        },
    )
    p4 = build_p4(records, split, ARMS)
    assert len(p4.question_ids) == 6

    def judged_ok(rec: RunRecord) -> bool:
        return not (rec.question_id == "g05" and rec.graph_arm == "hybrid")

    counts = judged_pairs(records, p4, "dense-only", "hybrid", judged_ok=judged_ok)
    assert counts.only_x_abstained == 1
    assert counts.only_reference_abstained == 1
    assert counts.both_abstained == 1
    assert counts.judge_unavailable == 1
    assert counts.both_answered == 2
    assert counts.pair_question_ids == ("g00", "g04")
    assert (
        counts.both_answered
        + counts.only_x_abstained
        + counts.only_reference_abstained
        + counts.both_abstained
        + counts.judge_unavailable
        == len(p4.question_ids)
    )


def test_judged_pairs_rejects_an_arm_outside_the_population() -> None:
    split = _split(n_g=2)
    records = _journal(split)
    p4 = build_p4(records, split, ("hybrid", "dense-only"))
    with pytest.raises(ValueError, match="not in this P4"):
        judged_pairs(records, p4, "bm25-only", "hybrid", judged_ok=lambda r: True)
