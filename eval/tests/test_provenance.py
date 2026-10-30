"""Tests for provenance.py: the one arm-provenance conformance check (AI-SPEC 5 #1)."""

from __future__ import annotations

import pytest

from lancet_eval.arms import ARM_REGISTRY
from lancet_eval.client import (
    LEVER_ORDER,
    NodeFailed,
    Notice,
    RankedCandidate,
    RerankMeta,
    RetrievalSnapshot,
    StructuredCitation,
)
from lancet_eval.journal import RunRecord, WorkflowWireMeta
from lancet_eval.provenance import (
    EXTERNAL_CODES,
    SNAPSHOT_EXPECTATIONS,
    ZERO_TOLERANCE_CODES,
    ProvenanceFailure,
    is_ok,
    provenance_failures,
)

ABLATION = Notice(code="GRAPH_ABLATION", message="", typed_code=18)
UNAVAILABLE = Notice(code="GRAPH_UNAVAILABLE", message="", typed_code=10)
CANONICAL = tuple(ARM_REGISTRY)


def _graph_on(arm: str) -> bool:
    return not ARM_REGISTRY[arm].disable_graph_context


def _ranking(arm: str, n: int) -> list[RankedCandidate]:
    mode = ARM_REGISTRY[arm].retrieval_mode
    out: list[RankedCandidate] = []
    for i in range(1, n + 1):
        out.append(
            RankedCandidate(
                chunk_id=f"d{i}:0",
                document_id=f"d{i}",
                fused_rank=i,
                vector_rank=i if mode != "bm25_only" else None,
                bm25_rank=i if mode != "dense_only" else None,
                graph_rank=2 if _graph_on(arm) and i == 3 else None,
                graph_boosted=_graph_on(arm) and i == 3,
            )
        )
    return out


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
    *,
    n_ranking: int = 12,
    ablation: bool | None = None,
) -> RunRecord:
    """A well-formed record of a canonical arm."""
    spec = ARM_REGISTRY[arm]
    ranking = _ranking(arm, n_ranking)
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
        levers=list(spec.levers),
    )
    with_ablation = spec.disable_graph_context if ablation is None else ablation
    return RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm=arm,
        outcome="success",
        answer="An answer",
        snapshot=snapshot,
        notices=[ABLATION] if with_ablation else [],
        workflow_meta=WorkflowWireMeta(
            vector_count=0 if spec.retrieval_mode == "bm25_only" else 8,
            bm25_count=0 if spec.retrieval_mode == "dense_only" else 8,
            rerank=(
                RerankMeta(
                    latency_ms=120,
                    cost_credits=4.4e-07,
                    cost_reported=True,
                    outcome="completed",
                )
                if "rerank" in spec.levers
                else None
            ),
        ),
    )


def _codes(record: RunRecord) -> set[str]:
    return {f.code for f in provenance_failures(record)}


def _with_snapshot(record: RunRecord, **changes: object) -> RunRecord:
    assert record.snapshot is not None
    return record.model_copy(
        update={"snapshot": record.snapshot.model_copy(update=changes)}
    )


# --- the well-formed record ---------------------------------------------------------


@pytest.mark.parametrize("arm", CANONICAL)
def test_a_well_formed_record_of_each_canonical_arm_has_no_failure(arm: str) -> None:
    record = _record(arm)
    assert provenance_failures(record) == []
    assert is_ok(record)


def test_every_registry_arm_round_trips_through_provenance_failures() -> None:
    """Extends 06.3.5-05's round trip: a new arm without shape rules turns this red."""
    from lancet_eval.arms import mode_provenance_failures, request_fields

    for label, spec in ARM_REGISTRY.items():
        rec = _record(label)
        fields = request_fields(label)
        assert fields["retrieval_mode"] == spec.retrieval_mode
        assert rec.snapshot is not None
        assert rec.snapshot.retrieval_mode == fields["retrieval_mode"]
        assert (
            mode_provenance_failures(label, rec.snapshot.retrieval_mode, rec.notices)
            == []
        )
        assert provenance_failures(rec) == [], label


def test_snapshot_expectations_match_drive_two() -> None:
    assert SNAPSHOT_EXPECTATIONS.rrf_k == 60
    assert SNAPSHOT_EXPECTATIONS.candidate_limit == 32
    assert SNAPSHOT_EXPECTATIONS.final_limit == 8
    assert SNAPSHOT_EXPECTATIONS.vector_weight == 1.0
    assert SNAPSHOT_EXPECTATIONS.bm25_weight == 1.0
    assert frozenset("abcdfhj") == ZERO_TOLERANCE_CODES


def test_a_failure_carries_its_code_label_and_detail() -> None:
    record = _with_snapshot(_record("dense-only"), retrieval_mode="hybrid")
    failures = provenance_failures(record)
    assert [f.code for f in failures] == ["a"]
    assert isinstance(failures[0], ProvenanceFailure)
    assert failures[0].label == "dense-only"
    assert "retrieval_mode" in failures[0].detail


# --- (a) mode echo ------------------------------------------------------------------


def test_a_wrong_mode_echo_is_clause_a() -> None:
    record = _with_snapshot(_record("hybrid"), retrieval_mode="bm25_only")
    assert _codes(record) == {"a"}
    assert not is_ok(record)


def test_a_missing_mode_echo_on_a_canonical_arm_is_clause_a() -> None:
    record = _with_snapshot(_record("hybrid+graph"), retrieval_mode=None)
    assert _codes(record) == {"a"}
    assert not is_ok(record)


# --- (b) ranking present and bounded -------------------------------------------------


def test_a_ranking_longer_than_the_candidate_limit_is_clause_b() -> None:
    base = _record("hybrid")
    record = _with_snapshot(
        base,
        pre_truncation_ranking=_ranking("hybrid", 33),
        retrieved_chunks=_final(_ranking("hybrid", 33)),
    )
    assert _codes(record) == {"b"}
    assert not is_ok(record)


def test_an_absent_ranking_beside_retrieved_chunks_is_clause_b() -> None:
    record = _with_snapshot(_record("hybrid"), pre_truncation_ranking=[])
    assert _codes(record) == {"b"}
    assert not is_ok(record)


def test_an_absent_ranking_with_no_retrieved_chunks_is_valid_omitempty() -> None:
    record = _with_snapshot(
        _record("hybrid"), pre_truncation_ranking=[], retrieved_chunks=[]
    )
    assert provenance_failures(record) == []
    assert is_ok(record)


# --- (c) prefix equality -------------------------------------------------------------


def test_a_swapped_order_is_clause_c() -> None:
    base = _record("hybrid")
    assert base.snapshot is not None
    chunks = list(base.snapshot.retrieved_chunks)
    chunks[0], chunks[1] = chunks[1], chunks[0]
    record = _with_snapshot(base, retrieved_chunks=chunks)
    assert _codes(record) == {"c"}
    assert not is_ok(record)


def test_a_rank_mismatch_is_clause_c() -> None:
    base = _record("hybrid")
    assert base.snapshot is not None
    chunks = [c.model_copy() for c in base.snapshot.retrieved_chunks]
    chunks[2] = chunks[2].model_copy(update={"rank": 9})
    assert _codes(_with_snapshot(base, retrieved_chunks=chunks)) == {"c"}


def test_a_graph_boosted_mismatch_is_clause_c() -> None:
    base = _record("hybrid+graph")
    assert base.snapshot is not None
    chunks = list(base.snapshot.retrieved_chunks)
    chunks[2] = chunks[2].model_copy(update={"graph_boosted": False})
    record = _with_snapshot(base, retrieved_chunks=chunks)
    assert _codes(record) == {"c"}
    assert not is_ok(record)


def test_a_gap_in_fused_rank_is_clause_c() -> None:
    base = _record("hybrid")
    assert base.snapshot is not None
    ranking = list(base.snapshot.pre_truncation_ranking)
    ranking[10] = ranking[10].model_copy(update={"fused_rank": 99})
    record = _with_snapshot(base, pre_truncation_ranking=ranking)
    assert _codes(record) == {"c"}
    assert not is_ok(record)


def test_a_final_list_shorter_than_the_final_limit_is_clause_c() -> None:
    base = _record("hybrid")
    assert base.snapshot is not None
    record = _with_snapshot(base, retrieved_chunks=base.snapshot.retrieved_chunks[:5])
    assert _codes(record) == {"c"}


def test_a_ranking_shorter_than_the_final_list_is_clause_c() -> None:
    base = _record("hybrid", n_ranking=3)
    assert base.snapshot is not None
    padded = _final(_ranking("hybrid", 8))
    record = _with_snapshot(base, retrieved_chunks=padded)
    assert "c" in _codes(record)


def test_a_short_ranking_that_equals_the_final_list_is_valid() -> None:
    record = _record("hybrid", n_ranking=5)
    assert provenance_failures(record) == []


# --- (d) per-arm rank shape ----------------------------------------------------------


def test_a_bm25_rank_on_dense_only_is_clause_d() -> None:
    base = _record("dense-only")
    assert base.snapshot is not None
    ranking = list(base.snapshot.pre_truncation_ranking)
    ranking[4] = ranking[4].model_copy(update={"bm25_rank": 5})
    record = _with_snapshot(base, pre_truncation_ranking=ranking)
    assert _codes(record) == {"d"}
    assert not is_ok(record)


def test_a_vector_rank_on_bm25_only_is_clause_d() -> None:
    base = _record("bm25-only")
    assert base.snapshot is not None
    ranking = list(base.snapshot.pre_truncation_ranking)
    ranking[0] = ranking[0].model_copy(update={"vector_rank": 1})
    record = _with_snapshot(base, pre_truncation_ranking=ranking)
    assert _codes(record) == {"d"}
    assert not is_ok(record)


@pytest.mark.parametrize("arm", ["dense-only", "bm25-only", "hybrid"])
def test_a_graph_rank_on_any_graph_off_arm_is_clause_d(arm: str) -> None:
    base = _record(arm)
    assert base.snapshot is not None
    ranking = list(base.snapshot.pre_truncation_ranking)
    ranking[6] = ranking[6].model_copy(update={"graph_rank": 3})
    record = _with_snapshot(base, pre_truncation_ranking=ranking)
    assert _codes(record) == {"d"}
    assert not is_ok(record)


def test_a_graph_rank_is_allowed_on_hybrid_plus_graph() -> None:
    record = _record("hybrid+graph")
    assert record.snapshot is not None
    assert any(r.graph_rank for r in record.snapshot.pre_truncation_ranking)
    assert provenance_failures(record) == []


def test_a_zero_rank_counts_as_absent() -> None:
    base = _record("dense-only")
    assert base.snapshot is not None
    ranking = list(base.snapshot.pre_truncation_ranking)
    ranking[1] = ranking[1].model_copy(update={"bm25_rank": 0})
    assert provenance_failures(_with_snapshot(base, pre_truncation_ranking=ranking)) == []


# --- (e) GRAPH_ABLATION --------------------------------------------------------------


@pytest.mark.parametrize("arm", ["dense-only", "bm25-only", "hybrid"])
def test_a_missing_graph_ablation_on_a_graph_off_arm_is_clause_e(arm: str) -> None:
    record = _record(arm, ablation=False)
    assert _codes(record) == {"e"}
    assert not is_ok(record)


def test_graph_unavailable_beside_the_ablation_notice_is_clause_e() -> None:
    record = _record("hybrid").model_copy(update={"notices": [ABLATION, UNAVAILABLE]})
    assert _codes(record) == {"e"}


def test_clause_e_is_reported_once_not_twice_for_a_graph_off_arm() -> None:
    record = _record("dense-only", ablation=False)
    assert [f.code for f in provenance_failures(record)] == ["e"]


# --- (f) snapshot config -------------------------------------------------------------


def test_a_candidate_limit_of_31_is_clause_f() -> None:
    record = _with_snapshot(_record("hybrid"), candidate_limit=31)
    assert _codes(record) == {"f"}
    assert not is_ok(record)


@pytest.mark.parametrize(
    "change",
    [
        {"rrf_k": 61},
        {"final_limit": 7},
        {"vector_weight": 0.75},
        {"bm25_weight": 0.5},
    ],
)
def test_each_drive_two_config_field_is_checked(change: dict[str, object]) -> None:
    base = _record("hybrid+graph")
    record = _with_snapshot(
        base,
        **change,
        # keep (c) quiet when final_limit changes: the final list is unchanged
    )
    assert "f" in _codes(record)


def test_an_explicit_expectation_overrides_the_default() -> None:
    from dataclasses import replace

    record = _with_snapshot(_record("hybrid"), candidate_limit=31)
    wanted = replace(SNAPSHOT_EXPECTATIONS, candidate_limit=31)
    assert provenance_failures(record, expected=wanted) == []


# --- (g) corroboration ---------------------------------------------------------------


def test_a_nonzero_bm25_count_on_dense_only_is_g_and_ok_stays_true() -> None:
    base = _record("dense-only")
    record = base.model_copy(
        update={"workflow_meta": WorkflowWireMeta(vector_count=8, bm25_count=3)}
    )
    assert _codes(record) == {"g"}
    assert is_ok(record)


def test_a_nonzero_vector_count_on_bm25_only_is_g_and_ok_stays_true() -> None:
    base = _record("bm25-only")
    record = base.model_copy(
        update={"workflow_meta": WorkflowWireMeta(vector_count=2, bm25_count=8)}
    )
    assert _codes(record) == {"g"}
    assert is_ok(record)


def test_g_never_rescues_a_zero_tolerance_failure() -> None:
    record = _with_snapshot(_record("dense-only"), retrieval_mode="hybrid").model_copy(
        update={"workflow_meta": WorkflowWireMeta(vector_count=8, bm25_count=3)}
    )
    assert _codes(record) == {"a", "g"}
    assert not is_ok(record)


# --- records whose RetrieveHybrid never completed -------------------------------------


def test_a_record_with_no_snapshot_is_not_checked_for_a_to_d_and_is_not_ok() -> None:
    record = RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm="hybrid+graph",
        outcome="error",
        node_failures=[
            NodeFailed(
                node_name="RetrieveHybrid",
                error_kind=1,
                error_message="boom",
                retryable=False,
            )
        ],
    )
    assert provenance_failures(record) == []
    assert not is_ok(record)


def test_a_partial_snapshot_with_an_empty_result_hash_is_not_checked() -> None:
    base = _record("hybrid+graph")
    partial = _with_snapshot(
        base,
        result_hash="",
        retrieval_mode="dense_only",
        pre_truncation_ranking=[],
        candidate_limit=0,
    ).model_copy(
        update={
            "outcome": "error",
            "node_failures": [
                NodeFailed(
                    node_name="RetrieveHybrid",
                    error_kind=1,
                    error_message="partial",
                    retryable=False,
                )
            ],
        }
    )
    assert provenance_failures(partial) == []
    assert not is_ok(partial)


def test_is_ok_requires_a_usable_record_even_with_clean_provenance() -> None:
    record = _record("hybrid").model_copy(
        update={
            "node_failures": [
                NodeFailed(
                    node_name="GenerateAnswer",
                    error_kind=1,
                    error_message="rejected",
                    retryable=False,
                )
            ]
        }
    )
    assert provenance_failures(record) == []
    assert not is_ok(record)


# --- legacy labels ---------------------------------------------------------------------


def _legacy(label: str, *, ablation: bool, **snapshot: object) -> RunRecord:
    fields: dict[str, object] = {
        "index_generation": "gen1",
        "vector_weight": 1.0,
        "bm25_weight": 1.0,
        "rrf_k": 60,
        "candidate_limit": 32,
        "final_limit": 8,
        "result_hash": "abc",
        "retrieved_chunks": _final(_ranking("hybrid", 8)),
    }
    fields.update(snapshot)
    return RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm=label,
        outcome="success",
        answer="A",
        snapshot=RetrievalSnapshot.model_validate(fields),
        notices=[ABLATION] if ablation else [],
    )


def test_a_legacy_graph_off_record_without_echo_or_ranking_passes() -> None:
    record = _legacy("graph-off", ablation=True)
    assert provenance_failures(record) == []
    assert is_ok(record)


def test_a_legacy_graph_on_record_passes_without_any_notice() -> None:
    record = _legacy("graph-on", ablation=False)
    assert provenance_failures(record) == []
    assert is_ok(record)


def test_a_legacy_graph_off_record_is_checked_for_e_and_f_only() -> None:
    no_ablation = _legacy("graph-off", ablation=False)
    assert _codes(no_ablation) == {"e"}
    bad_config = _legacy("graph-off", ablation=True, candidate_limit=31)
    assert _codes(bad_config) == {"f"}
    # No echo, no ranking, and a short final list are all fine on a legacy label.
    assert provenance_failures(_legacy("graph-on", ablation=False, final_limit=8)) == []


def test_an_unknown_arm_label_fails_closed() -> None:
    record = _legacy("graph-sideways", ablation=True)
    with pytest.raises(ValueError, match="Unknown arm"):
        provenance_failures(record)


# --- D-158 IN-04: clause (a) does not read message text -------------------------


def test_clause_a_calls_echo_failures_not_a_substring_of_the_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reworded echo message (no 'retrieval_mode' in it) still lands in clause (a)."""
    import lancet_eval.provenance as provenance_module

    monkeypatch.setattr(
        provenance_module,
        "echo_failures",
        lambda label, echo: ["the mode echo is wrong"],
    )
    failures = provenance_failures(_record("hybrid"))
    assert [f.code for f in failures] == ["a"]
    assert failures[0].detail == "the mode echo is wrong"


def test_rewording_the_ablation_message_moves_no_failure_into_clause_a(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ablation check is clause (e) only, whatever its message says."""
    import lancet_eval.arms as arms_module

    monkeypatch.setattr(
        arms_module,
        "ablation_failures",
        lambda label, notices: ["retrieval_mode is mentioned here too"],
    )
    assert provenance_failures(_record("dense-only")) == []


def test_mode_provenance_failures_is_the_composition_of_the_two_checks() -> None:
    from lancet_eval.arms import (
        ablation_failures,
        echo_failures,
        mode_provenance_failures,
    )

    rec = _record("dense-only")
    assert rec.snapshot is not None
    assert echo_failures("dense-only", rec.snapshot.retrieval_mode) == []
    assert ablation_failures("dense-only", rec.notices) == []
    bad_echo = echo_failures("dense-only", "hybrid")
    assert len(bad_echo) == 1 and "retrieval_mode" in bad_echo[0]
    assert echo_failures("graph-off", None) == []
    assert mode_provenance_failures("dense-only", "hybrid", []) == (
        echo_failures("dense-only", "hybrid") + ablation_failures("dense-only", [])
    )
    assert len(mode_provenance_failures("dense-only", "hybrid", [])) == 2


# --- 06.3.6-07: clauses (h), (i), (j) and (e) on graph-on arms (D-134, D-161) ---

RERANK_DEGRADED = Notice(code="RERANK_DEGRADED", message="", typed_code=23)
LEVER_ARMS = (
    "hybrid+rerank",
    "hybrid+metadata",
    "hybrid+answer-format",
    "hybrid+all",
    *(("hybrid+graph-v2",) if "graph_v2" in LEVER_ORDER else ()),
)


def _with_meta(record: RunRecord, **changes: object) -> RunRecord:
    assert record.workflow_meta is not None
    return record.model_copy(
        update={"workflow_meta": record.workflow_meta.model_copy(update=changes)}
    )


def test_the_code_sets_carry_the_new_clauses() -> None:
    from lancet_eval.provenance import _OK_CODES

    from lancet_eval.provenance import is_zero_tolerance

    # The engine clauses keep their 06.3.6 sets; every external clause (D-247) is
    # zero tolerance on its own.
    assert frozenset("abcdfhj") == ZERO_TOLERANCE_CODES
    assert frozenset("abcdefhij") == _OK_CODES
    assert not set(EXTERNAL_CODES) & (ZERO_TOLERANCE_CODES | _OK_CODES)
    assert all(is_zero_tolerance(code) for code in EXTERNAL_CODES)
    assert "i" not in ZERO_TOLERANCE_CODES


@pytest.mark.parametrize("arm", LEVER_ARMS)
def test_a_well_formed_lever_arm_record_passes(arm: str) -> None:
    record = _record(arm)
    assert provenance_failures(record) == []
    assert is_ok(record)


@pytest.mark.parametrize("arm", LEVER_ARMS)
def test_an_empty_levers_echo_on_a_lever_arm_is_clause_h(arm: str) -> None:
    record = _with_snapshot(_record(arm), levers=[])
    assert _codes(record) == {"h"}
    assert not is_ok(record)
    assert "h" in ZERO_TOLERANCE_CODES


def test_a_different_levers_echo_is_clause_h() -> None:
    record = _with_snapshot(_record("hybrid+rerank"), levers=["evidence_metadata"])
    assert _codes(record) == {"h"}


def test_a_lever_echo_on_a_lever_free_arm_is_clause_h() -> None:
    record = _with_snapshot(_record("hybrid"), levers=["rerank"])
    assert "h" in _codes(record)


def test_hybrid_against_a_pre_06_3_6_record_passes_clause_h() -> None:
    """A journal written before the field existed echoes no levers."""
    record = _record("hybrid")
    assert record.snapshot is not None
    assert record.snapshot.levers == []
    assert provenance_failures(record) == []
    for label in ("graph-off", "graph-on"):
        assert "h" not in _codes(_legacy_record(label))


def _legacy_record(label: str) -> RunRecord:
    return RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm=label,
        outcome="success",
        answer="An answer",
        snapshot=RetrievalSnapshot(
            index_generation="gen1",
            vector_weight=1.0,
            bm25_weight=1.0,
            rrf_k=60,
            candidate_limit=32,
            final_limit=8,
            result_hash="abc123",
        ),
        notices=[ABLATION] if label == "graph-off" else [],
    )


def test_clause_h_is_not_checked_without_a_completed_retrieval() -> None:
    record = _with_snapshot(_record("hybrid+rerank"), levers=[], result_hash="")
    assert "h" not in _codes(record)


def test_a_rerank_arm_record_with_code_23_is_clause_i_and_not_zero_tolerance() -> None:
    record = _record("hybrid+rerank").model_copy(
        update={"notices": [ABLATION, RERANK_DEGRADED]}
    )
    record = _with_meta(
        record,
        rerank=RerankMeta(latency_ms=3000, outcome="degraded_timeout"),
    )
    assert _codes(record) == {"i"}
    assert not is_ok(record)
    assert "i" not in ZERO_TOLERANCE_CODES


def test_code_23_alone_satisfies_the_telemetry_half_of_clause_j() -> None:
    record = _with_meta(_record("hybrid+rerank"), rerank=None).model_copy(
        update={"notices": [ABLATION, RERANK_DEGRADED]}
    )
    assert _codes(record) == {"i"}


def test_a_typed_code_23_without_the_code_string_is_clause_i() -> None:
    notice = Notice(code="", message="", typed_code=23)
    record = _record("hybrid+rerank").model_copy(update={"notices": [ABLATION, notice]})
    assert "i" in _codes(record)


def test_clause_i_never_fires_on_a_rerank_free_arm() -> None:
    record = _record("hybrid")
    assert "i" not in _codes(record)


def test_a_rerank_telemetry_leak_onto_hybrid_is_clause_j() -> None:
    record = _with_meta(
        _record("hybrid"),
        rerank=RerankMeta(latency_ms=10, outcome="completed"),
    )
    assert _codes(record) == {"j"}
    assert not is_ok(record)
    assert "j" in ZERO_TOLERANCE_CODES


def test_a_code_23_leak_onto_hybrid_is_clause_j() -> None:
    record = _record("hybrid").model_copy(
        update={"notices": [ABLATION, RERANK_DEGRADED]}
    )
    assert "j" in _codes(record)
    assert "i" not in _codes(record)


@pytest.mark.parametrize("arm", ["dense-only", "bm25-only", "hybrid+graph"])
def test_a_rerank_leak_onto_any_non_rerank_arm_is_clause_j(arm: str) -> None:
    record = _with_meta(
        _record(arm), rerank=RerankMeta(latency_ms=10, outcome="completed")
    )
    assert "j" in _codes(record)


def test_a_rerank_arm_without_telemetry_or_the_notice_is_clause_j() -> None:
    record = _with_meta(_record("hybrid+rerank"), rerank=None)
    assert _codes(record) == {"j"}
    assert not is_ok(record)


def test_a_rerank_arm_without_workflow_metadata_is_clause_j() -> None:
    record = _record("hybrid+rerank").model_copy(update={"workflow_meta": None})
    assert _codes(record) == {"j"}


def test_clause_j_is_not_checked_without_a_completed_retrieval() -> None:
    record = _with_snapshot(_record("hybrid+rerank"), result_hash="")
    record = _with_meta(record, rerank=None)
    assert "j" not in _codes(record)


@pytest.mark.parametrize(
    "arm", [a for a in ARM_REGISTRY if not ARM_REGISTRY[a].disable_graph_context]
)
def test_graph_ablation_on_a_graph_on_arm_is_clause_e(arm: str) -> None:
    record = _record(arm).model_copy(update={"notices": [ABLATION]})
    assert _codes(record) == {"e"}
    assert not is_ok(record)


def test_a_legacy_graph_on_record_carrying_ablation_is_clause_e() -> None:
    record = _legacy_record("graph-on").model_copy(update={"notices": [ABLATION]})
    assert "e" in _codes(record)


def test_clauses_h_and_j_call_their_functions_not_message_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lancet_eval.provenance as provenance_module

    monkeypatch.setattr(
        provenance_module, "lever_echo_failures", lambda label, echo: ["reworded"]
    )
    failures = provenance_failures(_record("hybrid"))
    assert [f.code for f in failures] == ["h"]
    assert failures[0].detail == "reworded"


def test_the_ablation_function_flags_a_graph_on_arm_carrying_the_notice() -> None:
    from lancet_eval.arms import ablation_failures

    assert ablation_failures("hybrid+graph", [ABLATION])
    assert ablation_failures("hybrid+graph", []) == []
    assert ablation_failures("hybrid+rerank", []) != []


# ---- v1.1 external records (D-247), seam S-A ----------------------------------------


def _external_fixture():  # type: ignore[no-untyped-def]
    import levers_fixture

    return levers_fixture


def test_engine_clauses_never_run_on_a_clean_external_record() -> None:
    fx = _external_fixture()
    qs = fx.make_questions(1, 0)
    rec = fx.make_external_record(qs.g_ids[0], fx.Spec(), qs)
    assert rec.snapshot is None
    assert rec.notices == []
    assert provenance_failures(rec) == []
    assert is_ok(rec)


def test_an_external_record_with_a_faked_snapshot_fails_the_record_clause() -> None:
    fx = _external_fixture()
    qs = fx.make_questions(1, 0)
    engine = fx.make_record("hybrid", qs.g_ids[0], fx.Spec(), qs)
    faked = fx.make_external_record(qs.g_ids[0], fx.Spec(), qs).model_copy(
        update={"snapshot": engine.snapshot}
    )
    codes = [f.code for f in provenance_failures(faked)]
    assert codes == ["external_record"]
    assert "external_record" in EXTERNAL_CODES
    assert not is_ok(faked)


def test_an_external_success_record_without_its_block_fails_and_an_error_passes() -> (
    None
):
    fx = _external_fixture()
    qs = fx.make_questions(1, 0)
    qid = qs.g_ids[0]
    bare = fx.make_external_record(qid, fx.Spec(), qs).model_copy(
        update={"external": None}
    )
    assert [f.code for f in provenance_failures(bare)] == ["external_record"]
    errored = fx.make_external_record(qid, fx.Spec(errored=True), qs)
    assert provenance_failures(errored) == []
    assert not is_ok(errored)


def test_an_engine_record_carrying_an_external_block_fails() -> None:
    fx = _external_fixture()
    qs = fx.make_questions(1, 0)
    qid = qs.g_ids[0]
    block = fx.make_external_record(qid, fx.Spec(), qs).external
    rec = fx.make_record("hybrid", qid, fx.Spec(), qs).model_copy(
        update={"external": block}
    )
    assert [f.code for f in provenance_failures(rec)] == ["external_record"]


S0_REFERENCE = "hybrid+rerank+metadata"


def _s0_prereg(pipeline=None):  # type: ignore[no-untyped-def]
    """A synthetic S0-shaped stage constant: one Lancet arm, one external arm."""
    import dataclasses

    from lancet_eval.thresholds import FamilySpec, LeverPreRegistration

    fx = _external_fixture()

    @dataclasses.dataclass(frozen=True)
    class StagePreRegistration(LeverPreRegistration):
        external_pipelines: tuple[tuple[str, object], ...] = ()

    base = fx.make_prereg()
    fields = {f.name: getattr(base, f.name) for f in dataclasses.fields(base)}
    fields.update(
        reference_arm=S0_REFERENCE,
        families=(FamilySpec("answer_usable", "decisional", (fx.EXTERNAL,), 0.05),),
        descriptive_arms=(),
        null_guard_arms=(fx.EXTERNAL,),
    )
    return StagePreRegistration(
        **fields,
        external_pipelines=((fx.EXTERNAL, pipeline or fx.external_pipeline()),),
    )


def _s0_run(  # type: ignore[no-untyped-def]
    tmp_path,
    monkeypatch,
    *,
    external=None,
    lancet=None,
    export=None,
    prereg=None,
):
    """Seam S-A: a `[split]` run of one Lancet arm and one external arm.

    `external(qid, qs)` and `lancet(qid, qs)` build each arm's record; `export` is
    passed to `write_external_export` as keyword arguments.
    """
    from lancet_eval import thresholds
    from lancet_eval.journal import Journal

    fx = _external_fixture()

    def default_lancet(qid, qs):  # type: ignore[no-untyped-def]
        return fx.make_record(S0_REFERENCE, qid, fx.Spec(), qs)

    def default_external(qid, qs):  # type: ignore[no-untyped-def]
        return fx.make_external_record(qid, fx.Spec(), qs)

    qs = fx.make_questions(10, 5)
    root = tmp_path / "repo"
    gold = fx.write_corpus(root, qs, (S0_REFERENCE, fx.EXTERNAL))
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr(thresholds, fx.TOKEN, prereg or _s0_prereg(), raising=False)
    run = tmp_path / "run"
    journal = Journal(run / "journal.jsonl")
    journal.write_header(corpus=fx.CORPUS, partial=False, context_export=True)
    records = []
    for qid in [*qs.g_ids, *qs.nulls]:
        for build in (lancet or default_lancet, external or default_external):
            rec = build(qid, qs)
            journal.append(rec)
            records.append(rec)
    fx.write_external_export(run, records, **(export or {}))
    return run, gold, qs


def _score(run, gold):  # type: ignore[no-untyped-def]
    from lancet_eval.score import score_run

    return score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)


def test_s_a_score_and_the_lever_comparison_pair_a_lancet_and_an_external_arm(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from lancet_eval.lever_comparison import build_lever_comparison

    fx = _external_fixture()

    def external(qid, qs):  # type: ignore[no-untyped-def]
        wrong = qid in {"lv-g000", "lv-g001", "lv-g002"}
        return fx.make_external_record(
            qid, fx.Spec(kind="wrong" if wrong else "ok"), qs
        )

    run, gold, qs = _s0_run(tmp_path, monkeypatch, external=external)
    report = _score(run, gold)
    assert (run / "report.json").is_file()
    assert report.metadata.index_generation == "gen1"
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    family = next(f for f in payload["families"] if f["primary"] == "answer_usable")
    row = next(c for c in family["comparisons"] if c["arm"] == fx.EXTERNAL)
    assert row["n_pairs"] == len(qs.g_ids)
    assert (row["n_pos"], row["n_neg"]) == (0, 3)
    assert row["delta"] == pytest.approx(-0.3)


def _refusal(tmp_path, monkeypatch, **kwargs) -> str:  # type: ignore[no-untyped-def]
    from lancet_eval.score import ScoreError

    run, gold, _ = _s0_run(tmp_path, monkeypatch, **kwargs)
    with pytest.raises(ScoreError) as excinfo:
        _score(run, gold)
    return str(excinfo.value)


def test_s_a_an_export_row_without_eight_entries_is_refused_as_export_k8(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    fx = _external_fixture()

    def count(rec):  # type: ignore[no-untyped-def]
        return 7 if (rec.graph_arm, rec.question_id) == (fx.EXTERNAL, "lv-g004") else 8

    message = _refusal(tmp_path, monkeypatch, export={"evidence_count": count})
    assert "export_k8 llamaindex lv-g004: 7 ranked evidence entries" in message


def test_s_a_an_unmapped_document_id_is_refused_as_document_map(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    fx = _external_fixture()
    doc = fx.doc_id()

    def document_id(rec, rank):  # type: ignore[no-untyped-def]
        if (rec.graph_arm, rec.question_id, rank) == (fx.EXTERNAL, "lv-g002", 5):
            return "not-a-document"
        return doc

    message = _refusal(tmp_path, monkeypatch, export={"document_id": document_id})
    assert "document_map llamaindex lv-g002" in message
    assert "not-a-document" in message


def test_s_a_a_drifted_pipeline_echo_is_refused_as_pipeline_echo(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    fx = _external_fixture()

    def external(qid, qs):  # type: ignore[no-untyped-def]
        pipeline = fx.external_pipeline(chunk_size=512) if qid == "lv-g001" else None
        return fx.make_external_record(qid, fx.Spec(), qs, pipeline=pipeline)

    message = _refusal(tmp_path, monkeypatch, external=external)
    assert "pipeline_echo llamaindex lv-g001: chunk_size 512 != 256" in message


def test_s_a_a_stage_without_the_arm_pipeline_is_refused_as_pipeline_echo(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    import dataclasses

    prereg = dataclasses.replace(_s0_prereg(), external_pipelines=())
    message = _refusal(tmp_path, monkeypatch, prereg=prereg)
    assert "pipeline_echo" in message and "llamaindex" in message


def test_s_a_two_index_fingerprints_in_one_arm_are_refused(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    fx = _external_fixture()

    def external(qid, qs):  # type: ignore[no-untyped-def]
        fingerprint = "reindexed" if qid == "lv-n004" else fx.EXTERNAL_FINGERPRINT
        return fx.make_external_record(
            qid, fx.Spec(), qs, index_fingerprint=fingerprint
        )

    message = _refusal(tmp_path, monkeypatch, external=external)
    assert "index_fingerprint llamaindex *: 2 index fingerprints" in message


@pytest.mark.parametrize(
    ("change", "shown"),
    [
        ({"generation_model": "anthropic/claude-haiku-5-5"}, "generation model"),
        ({"generation_provider_order": ["somebody-else"]}, "provider order"),
    ],
)
def test_s_a_another_reader_or_provider_is_refused_as_generation_model(
    tmp_path, monkeypatch, preregistered_clean_tree, change, shown
) -> None:
    fx = _external_fixture()

    def external(qid, qs):  # type: ignore[no-untyped-def]
        extra = change if qid == "lv-g007" else {}
        return fx.make_external_record(qid, fx.Spec(), qs, **extra)

    message = _refusal(tmp_path, monkeypatch, external=external)
    assert f"generation_model llamaindex lv-g007: {shown}" in message


def test_s_a_a_faked_engine_snapshot_on_an_external_record_is_refused(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    fx = _external_fixture()

    def external(qid, qs):  # type: ignore[no-untyped-def]
        rec = fx.make_external_record(qid, fx.Spec(), qs)
        if qid != "lv-g003":
            return rec
        faked = fx.make_record(S0_REFERENCE, qid, fx.Spec(), qs).snapshot
        return rec.model_copy(update={"snapshot": faked})

    message = _refusal(tmp_path, monkeypatch, external=external)
    assert "lv-g003/llamaindex/external_record" in message


def test_s_a_each_arm_may_carry_its_own_index_generation(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    fx = _external_fixture()

    def external(qid, qs):  # type: ignore[no-untyped-def]
        rec = fx.make_external_record(qid, fx.Spec(), qs)
        return rec.model_copy(update={"index_generation": "llamaindex-gen"})

    run, gold, _ = _s0_run(tmp_path, monkeypatch, external=external)
    report = _score(run, gold)
    assert report.metadata.index_generation == (
        "hybrid+rerank+metadata=gen1; llamaindex=llamaindex-gen"
    )


def test_s_a_two_index_generations_within_one_arm_are_refused(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    fx = _external_fixture()

    def lancet(qid, qs):  # type: ignore[no-untyped-def]
        rec = fx.make_record(S0_REFERENCE, qid, fx.Spec(), qs)
        if qid == "lv-g005":
            return rec.model_copy(update={"index_generation": "gen2"})
        return rec

    message = _refusal(tmp_path, monkeypatch, lancet=lancet)
    assert "Mixed index generations detected in arm 'hybrid+rerank+metadata'" in message


def test_s_a_the_lever_comparison_re_checks_the_external_clauses(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from lancet_eval.lever_comparison import (
        LeverComparisonError,
        build_lever_comparison,
    )

    fx = _external_fixture()
    run, gold, _ = _s0_run(tmp_path, monkeypatch)
    _score(run, gold)
    from lancet_eval.journal import load_records

    records = load_records(run / "journal.jsonl")
    fx.write_external_export(run, records, evidence_count=lambda _rec: 4)
    with pytest.raises(LeverComparisonError, match="export_k8 llamaindex"):
        build_lever_comparison(run, gold_chunks_path=gold)


def test_s_a_chunk_id_secondaries_leave_the_external_arm_unscored(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from lancet_eval.lever_comparison import build_lever_comparison

    fx = _external_fixture()
    run, gold, qs = _s0_run(tmp_path, monkeypatch)
    _score(run, gold)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    rows = {r["metric"]: r for r in payload["secondaries"] if r["arm"] == fx.EXTERNAL}
    assert rows, "the external arm has secondary rows"
    for metric in (
        "paper_hits_at_10",
        "paper_mrr_at_10",
        "paper_map_at_10",
        "all_gold_at_4",
    ):
        assert rows[metric]["n_pairs"] == 0, metric
        assert rows[metric]["n_unscorable"] == len(qs.g_ids), metric
    assert rows["final_answer_em"]["n_pairs"] == len(qs.g_ids)


def test_s_a_an_unreadable_engine_generation_model_is_refused_as_generation_model(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from lancet_eval import score as score_mod

    monkeypatch.setattr(score_mod, "_get_engine_generation_model", lambda: "")
    message = _refusal(tmp_path, monkeypatch)
    assert "generation_model: cannot read [openrouter] generation_model" in message


def test_s_a_a_token_that_does_not_resolve_never_defaults_the_p4_reference(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from lancet_eval import score as score_mod

    run, gold, _ = _s0_run(tmp_path, monkeypatch)
    real_resolve = score_mod.preregistration.resolve
    calls = {"n": 0}

    def resolve_once(token: str):  # type: ignore[no-untyped-def]
        # The external clauses resolve the token first; the P4 reference is next.
        calls["n"] += 1
        if calls["n"] > 1:
            raise score_mod.preregistration.PreregistrationError("gone")
        return real_resolve(token)

    monkeypatch.setattr(score_mod.preregistration, "resolve", resolve_once)
    with pytest.raises(score_mod.ScoreError, match="Cannot build P4: gone"):
        _score(run, gold)
