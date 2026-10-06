"""Tests for lancet_eval.unpark_gates: SC-1, SC-2, D-69 companion tripwire, and SC-3.

Every gate reading is a COMPUTED PASS/MISS against literals committed to
`thresholds.py` (D-73) -- these tests pin the exact behaviour bullets from
06.3.4.1-05-PLAN.md Task 2, not just "it runs".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import lancet_eval.thresholds as thresholds_module
from lancet_eval.client import Notice, RetrievalSnapshot, StructuredCitation
from lancet_eval.corpus import GoldQuestion
from lancet_eval.journal import NodeFailed, NodeTiming, RunRecord, WorkflowWireMeta
from lancet_eval.unpark_gates import (
    citation_rejection_rate,
    evaluate_sc1,
    evaluate_sc2,
    evaluate_sc3,
    evaluate_sc4,
    evaluate_sc5,
    graph_off_invariance,
    main,
)

# --- fixtures / helpers ---------------------------------------------------------------


def _set_vector_baseline_usable_floor(
    monkeypatch: pytest.MonkeyPatch, value: float
) -> None:
    """Monkeypatch the not-yet-committed VECTOR_BASELINE_USABLE_FLOOR literal.

    `evaluate_sc3` reads it via `getattr(thresholds, "VECTOR_BASELINE_USABLE_FLOOR",
    None)` off the SAME module object `unpark_gates.thresholds` is bound to, so
    patching the attribute here is visible to `evaluate_sc3` without further wiring.
    """
    monkeypatch.setattr(
        thresholds_module, "VECTOR_BASELINE_USABLE_FLOOR", value, raising=False
    )


def _gold_question(
    question_id: str,
    *,
    is_null: bool = False,
    question_type: str = "inference_query",
    gold_answer: str = "entity",
) -> GoldQuestion:
    if is_null:
        return GoldQuestion(
            question_id=question_id, question="q", question_type=question_type
        )
    return GoldQuestion(
        question_id=question_id,
        question="q",
        question_type=question_type,
        gold_facts=["a gold fact"],
        gold_answer=gold_answer,
        evidence_list=[{"title": "doc", "fact": "a gold fact"}],
    )


def _generate_answer_success(question_id: str) -> RunRecord:
    return RunRecord(
        corpus="graphrag_bench",
        question_id=question_id,
        graph_arm="graph-off",
        outcome="success",
        answer="Answer: entity",
        index_generation="gen-1",
        node_timings=[NodeTiming(node_name="GenerateAnswer", duration_ms=10.0)],
    )


def _generate_answer_rejection(
    question_id: str, error_message: str, *, graph_arm: str = "graph-off"
) -> RunRecord:
    return RunRecord(
        corpus="graphrag_bench",
        question_id=question_id,
        graph_arm=graph_arm,
        outcome="error",
        index_generation="gen-1",
        node_failures=[
            NodeFailed(
                node_name="GenerateAnswer",
                error_kind=0,
                error_message=error_message,
                retryable=False,
            )
        ],
    )


def _write_journal(
    path: Path, records: list[RunRecord], *, corpus: str = "graphrag_bench"
) -> None:
    with open(path, "w", encoding="utf-8") as f:
        header = {"type": "header", "corpus": corpus, "partial": True}
        f.write(json.dumps(header) + "\n")
        for rec in records:
            f.write(rec.model_dump_json() + "\n")


# --- citation_rejection_rate ----------------------------------------------------------


def test_citation_rejection_rate_marker_mismatch_forces_miss(tmp_path: Path) -> None:
    """1 citation_marker_mismatch gives MISS regardless of otherwise-clean rates."""
    j_path = tmp_path / "journal.jsonl"
    records = [
        _generate_answer_rejection(
            "q-mismatch", "mismatch between cited_evidence_ids and answer markers"
        )
    ]
    records += [_generate_answer_success(f"q-ok-{i}") for i in range(49)]
    _write_journal(j_path, records)
    questions = [_gold_question("q-mismatch")] + [
        _gold_question(f"q-ok-{i}") for i in range(49)
    ]

    reading = citation_rejection_rate(j_path, questions)

    assert reading.status == "MISS"
    assert reading.detail["marker_mismatch_count"] == 1.0


def test_citation_rejection_rate_total_above_tripwire_is_miss(tmp_path: Path) -> None:
    """total 20/100 (> 0.159) gives MISS."""
    j_path = tmp_path / "journal.jsonl"
    records = [
        _generate_answer_rejection(
            f"q-rej-{i}",
            "answer basis 'mixed' requires at least one cited evidence ID: none",
        )
        for i in range(20)
    ]
    records += [_generate_answer_success(f"q-ok-{i}") for i in range(80)]
    _write_journal(j_path, records)
    questions = [_gold_question(f"q-rej-{i}") for i in range(20)] + [
        _gold_question(f"q-ok-{i}") for i in range(80)
    ]

    reading = citation_rejection_rate(j_path, questions)

    assert reading.status == "MISS"
    assert reading.detail["total"] == 100.0
    assert reading.detail["total_rate"] == pytest.approx(0.20)


def test_citation_rejection_rate_null_baseline_exceeded_is_miss(tmp_path: Path) -> None:
    """null rejections 30/40 (> 29/42) gives MISS."""
    j_path = tmp_path / "journal.jsonl"
    records = [
        _generate_answer_rejection(
            f"q-null-rej-{i}",
            "answer basis 'mixed' requires at least one cited evidence ID: none",
        )
        for i in range(30)
    ]
    records += [_generate_answer_success(f"q-null-ok-{i}") for i in range(10)]
    _write_journal(j_path, records)
    questions = [
        _gold_question(f"q-null-rej-{i}", is_null=True) for i in range(30)
    ] + [_gold_question(f"q-null-ok-{i}", is_null=True) for i in range(10)]

    reading = citation_rejection_rate(j_path, questions)

    assert reading.status == "MISS"
    assert reading.detail["null_total"] == 40.0
    assert reading.detail["null_rejections"] == 30.0
    assert reading.detail["null_rate"] == pytest.approx(0.75)


def test_citation_rejection_rate_otherwise_pass(tmp_path: Path) -> None:
    """No mismatch, total rate <= 0.159, null rate <= baseline -> PASS."""
    j_path = tmp_path / "journal.jsonl"
    records = [
        _generate_answer_rejection(
            f"q-rej-{i}",
            "answer basis 'retrieval' requires at least one cited evidence ID: none",
        )
        for i in range(15)
    ]
    records += [_generate_answer_success(f"q-ok-{i}") for i in range(85)]
    _write_journal(j_path, records)
    questions = [_gold_question(f"q-rej-{i}") for i in range(15)] + [
        _gold_question(f"q-ok-{i}") for i in range(85)
    ]

    reading = citation_rejection_rate(j_path, questions)

    assert reading.status == "PASS"
    assert reading.detail["marker_mismatch_count"] == 0.0


def test_citation_rejection_rate_reports_null_and_nonnull_separately(
    tmp_path: Path,
) -> None:
    """Null and non-null rejection rates are reported separately in detail."""
    j_path = tmp_path / "journal.jsonl"
    records = [
        _generate_answer_success(f"q-null-{i}") for i in range(5)
    ] + [_generate_answer_success(f"q-nonnull-{i}") for i in range(5)]
    _write_journal(j_path, records)
    questions = [_gold_question(f"q-null-{i}", is_null=True) for i in range(5)] + [
        _gold_question(f"q-nonnull-{i}") for i in range(5)
    ]

    reading = citation_rejection_rate(j_path, questions)

    assert reading.detail["null_total"] == 5.0
    assert reading.detail["nonnull_total"] == 5.0
    assert "null_rate" in reading.detail
    assert "nonnull_rate" in reading.detail


def test_citation_rejection_rate_empty_population_is_miss_n0(tmp_path: Path) -> None:
    """Specless edge: no record reaching GenerateAnswer is a MISS n=0 population."""
    j_path = tmp_path / "journal.jsonl"
    _write_journal(j_path, [])

    reading = citation_rejection_rate(j_path, [])

    assert reading.status == "MISS"
    assert reading.reason == "n=0"
    assert reading.n == 0


# --- evaluate_sc2 ---------------------------------------------------------------------


def _flat_generate_records(n: int = 20, duration_ms: float = 100.0) -> list[RunRecord]:
    return [
        RunRecord(
            corpus="graphrag_bench",
            question_id=f"q-flat-{i}",
            graph_arm="graph-off",
            outcome="success",
            index_generation="gen-1",
            node_timings=[
                NodeTiming(node_name="RetrieveHybrid", duration_ms=duration_ms)
            ],
        )
        for i in range(n)
    ]


def test_evaluate_sc2_engine_restart_is_miss(tmp_path: Path) -> None:
    j_path = tmp_path / "journal.jsonl"
    _write_journal(j_path, _flat_generate_records())

    reading = evaluate_sc2(j_path, engine_pid_before=111, engine_pid_after=222)

    assert reading.status == "MISS"
    assert reading.reason == "engine restarted"


def test_evaluate_sc2_timeout_tied_dominant_class_is_miss(tmp_path: Path) -> None:
    """errors {timeout: 5, citation_basis_mixed: 5} gives MISS (a tie is dominant)."""
    j_path = tmp_path / "journal.jsonl"
    records = _flat_generate_records(20)
    records += [
        RunRecord(
            corpus="graphrag_bench",
            question_id=f"q-timeout-{i}",
            graph_arm="graph-off",
            outcome="error",
            index_generation="gen-1",
            node_failures=[
                NodeFailed(
                    node_name="RetrieveHybrid",
                    error_kind=1,
                    error_message="deadline exceeded",
                    retryable=False,
                )
            ],
        )
        for i in range(5)
    ]
    records += [
        _generate_answer_rejection(
            f"q-mixed-{i}",
            "answer basis 'mixed' requires at least one cited evidence ID: none",
        )
        for i in range(5)
    ]
    _write_journal(j_path, records)

    reading = evaluate_sc2(j_path, engine_pid_before=1, engine_pid_after=1)

    assert reading.status == "MISS"
    assert reading.detail["timeout_dominant"] is True


def test_evaluate_sc2_timeout_not_dominant_error_mode_clause_passes(
    tmp_path: Path,
) -> None:
    """{timeout: 3, transport: 5} gives PASS for the error-mode clause. The 3 real
    RetrieveHybrid timeouts still censor the flatness clause (any error_kind==1
    RetrieveHybrid failure censors the whole set, per decay.py's own False-flat trap),
    so the OVERALL reading is still MISS here -- only the error-mode clause is proven
    passing by this fixture; see test_evaluate_sc2_overall_pass_requires_both_clauses
    for a fixture where both clauses genuinely pass.
    """
    j_path = tmp_path / "journal.jsonl"
    records = _flat_generate_records(20)
    records += [
        RunRecord(
            corpus="graphrag_bench",
            question_id=f"q-timeout-{i}",
            graph_arm="graph-off",
            outcome="error",
            index_generation="gen-1",
            node_failures=[
                NodeFailed(
                    node_name="RetrieveHybrid",
                    error_kind=1,
                    error_message="deadline exceeded",
                    retryable=False,
                )
            ],
        )
        for i in range(3)
    ]
    records += [
        RunRecord(
            corpus="graphrag_bench",
            question_id=f"q-transport-{i}",
            graph_arm="graph-off",
            outcome="error",
            index_generation="gen-1",
            error_type="ConnectionResetError",
        )
        for i in range(5)
    ]
    _write_journal(j_path, records)

    reading = evaluate_sc2(j_path, engine_pid_before=1, engine_pid_after=1)

    assert reading.detail["timeout_dominant"] is False
    # Error-mode clause passes, but the fixture's real timeouts censor flatness --
    # overall MISS is correct here (both clauses must pass).
    assert reading.status == "MISS"
    assert "flatness" in reading.reason


def test_evaluate_sc2_overall_pass_requires_both_clauses(tmp_path: Path) -> None:
    """The overall SC-2 reading is PASS only when both the error-mode clause and the
    flatness clause pass -- proven here with zero timeout-classified records (so the
    error-mode clause trivially passes) atop a flat, uncensored RetrieveHybrid series.
    """
    j_path = tmp_path / "journal.jsonl"
    records = _flat_generate_records(20)
    records += [
        RunRecord(
            corpus="graphrag_bench",
            question_id=f"q-transport-{i}",
            graph_arm="graph-off",
            outcome="error",
            index_generation="gen-1",
            error_type="ConnectionResetError",
        )
        for i in range(3)
    ]
    _write_journal(j_path, records)

    reading = evaluate_sc2(j_path, engine_pid_before=1, engine_pid_after=1)

    assert reading.detail["timeout_dominant"] is False
    assert reading.status == "PASS"


def test_evaluate_sc2_censored_flatness_set_is_miss_flatness_unavailable(
    tmp_path: Path,
) -> None:
    """A censored flatness set gives MISS with reason 'flatness unavailable'."""
    j_path = tmp_path / "journal.jsonl"
    records = _flat_generate_records(20)
    records[5] = RunRecord(
        corpus="graphrag_bench",
        question_id="q-censored",
        graph_arm="graph-off",
        outcome="success",
        index_generation="gen-1",
        node_failures=[
            NodeFailed(
                node_name="RetrieveHybrid",
                error_kind=1,
                error_message="deadline exceeded",
                retryable=False,
            )
        ],
    )
    _write_journal(j_path, records)

    reading = evaluate_sc2(j_path, engine_pid_before=1, engine_pid_after=1)

    assert reading.status == "MISS"
    assert reading.reason == "flatness unavailable"


def test_evaluate_sc2_prints_both_arm_error_question_count(tmp_path: Path) -> None:
    j_path = tmp_path / "journal.jsonl"
    records = _flat_generate_records(20)
    for arm in ("graph-on", "graph-off"):
        records.append(
            RunRecord(
                corpus="graphrag_bench",
                question_id="q-both-arm-error",
                graph_arm=arm,
                outcome="error",
                index_generation="gen-1",
                error_type="ConnectionResetError",
            )
        )
    _write_journal(j_path, records)

    reading = evaluate_sc2(j_path, engine_pid_before=1, engine_pid_after=1)

    assert reading.detail["both_arm_error_question_count"] == 1.0


def test_evaluate_sc2_empty_journal_is_miss_n0(tmp_path: Path) -> None:
    j_path = tmp_path / "journal.jsonl"
    _write_journal(j_path, [])

    reading = evaluate_sc2(j_path, engine_pid_before=1, engine_pid_after=1)

    assert reading.status == "MISS"
    assert reading.reason == "n=0"


def test_evaluate_sc2_unknown_dominance_rule_is_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-73: SC2_TIMEOUT_DOMINANCE_RULE is a committed literal, actually read --
    an unrecognised value refuses rather than silently reinterpreting policy."""
    import lancet_eval.unpark_gates as unpark_gates_module

    monkeypatch.setattr(
        unpark_gates_module, "SC2_TIMEOUT_DOMINANCE_RULE", "some_future_rule"
    )

    j_path = tmp_path / "journal.jsonl"
    _write_journal(j_path, _flat_generate_records(20))

    reading = evaluate_sc2(j_path, engine_pid_before=1, engine_pid_after=1)

    assert reading.status == "MISS"
    assert "unknown dominance rule" in reading.reason


# --- evaluate_sc1 ---------------------------------------------------------------------


def _write_sc1_journal(
    path: Path,
    *,
    corpus: str,
    questions: list[GoldQuestion],
    arms: list[str],
    header_partial: bool,
    omit_last: bool = False,
) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            json.dumps({"type": "header", "corpus": corpus, "partial": header_partial})
            + "\n"
        )
        units = [(q, arm) for q in questions for arm in arms]
        if omit_last and units:
            units = units[:-1]
        for q, arm in units:
            rec = RunRecord(
                corpus=corpus,
                question_id=q.question_id,
                graph_arm=arm,
                outcome="success",
                index_generation="gen-1",
            )
            f.write(rec.model_dump_json() + "\n")


def test_evaluate_sc1_pass_when_header_matches_and_report_exists(
    tmp_path: Path,
) -> None:
    from lancet_eval.corpus import load_corpus_config, load_sample_questions

    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    run_dir = tmp_path
    j_path = run_dir / "journal.jsonl"
    _write_sc1_journal(
        j_path,
        corpus=corpus,
        questions=questions,
        arms=config.arms,
        header_partial=False,
    )
    (run_dir / "report.json").write_text("{}", encoding="utf-8")

    reading = evaluate_sc1(run_dir)

    assert reading.status == "PASS"


def test_evaluate_sc1_missing_unit_is_miss(tmp_path: Path) -> None:
    from lancet_eval.corpus import load_corpus_config, load_sample_questions

    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    run_dir = tmp_path
    j_path = run_dir / "journal.jsonl"
    _write_sc1_journal(
        j_path,
        corpus=corpus,
        questions=questions,
        arms=config.arms,
        header_partial=False,
        omit_last=True,
    )
    (run_dir / "report.json").write_text("{}", encoding="utf-8")

    reading = evaluate_sc1(run_dir)

    assert reading.status == "MISS"


def test_evaluate_sc1_no_report_json_is_miss(tmp_path: Path) -> None:
    from lancet_eval.corpus import load_corpus_config, load_sample_questions

    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    run_dir = tmp_path
    j_path = run_dir / "journal.jsonl"
    _write_sc1_journal(
        j_path,
        corpus=corpus,
        questions=questions,
        arms=config.arms,
        header_partial=False,
    )
    # No report.json written.

    reading = evaluate_sc1(run_dir)

    assert reading.status == "MISS"


def test_evaluate_sc1_no_journal_is_miss(tmp_path: Path) -> None:
    reading = evaluate_sc1(tmp_path)

    assert reading.status == "MISS"


def test_evaluate_sc1_an_honest_partial_journal_without_a_report_is_miss(
    tmp_path: Path,
) -> None:
    """CR-02: header `partial: true` on an INCOMPLETE journal is honest metadata, but
    SC-1 also needs the journal to be complete (D-87a: a halted drive is never reported
    as complete). It read PASS before the completeness precondition."""
    from lancet_eval.corpus import load_corpus_config, load_sample_questions

    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)
    _write_sc1_journal(
        tmp_path / "journal.jsonl",
        corpus=corpus,
        questions=questions,
        arms=config.arms,
        header_partial=True,
        omit_last=True,
    )
    # No report.json: the fail-closed path left none for the halted run.

    reading = evaluate_sc1(tmp_path)

    assert reading.status == "MISS"
    assert "journal incomplete: 1 work unit(s) missing" in reading.reason
    assert reading.detail["journal_complete"] is False


def test_evaluate_sc1_reports_journal_complete_on_a_complete_journal(
    tmp_path: Path,
) -> None:
    from lancet_eval.corpus import load_corpus_config, load_sample_questions

    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    _write_sc1_journal(
        tmp_path / "journal.jsonl",
        corpus=corpus,
        questions=load_sample_questions(corpus),
        arms=config.arms,
        header_partial=False,
    )
    (tmp_path / "report.json").write_text("{}", encoding="utf-8")

    reading = evaluate_sc1(tmp_path)

    assert reading.status == "PASS"
    assert reading.detail["journal_complete"] is True


# --- evaluate_sc3 ---------------------------------------------------------------------


@pytest.fixture()
def _sc3_row_cls():
    from dataclasses import dataclass as _dc

    @_dc(frozen=True)
    class _Row:
        question_id: str
        question_type: str = "inference_query"
        e_answer_usable: bool | None = None

    return _Row


def _write_populations(
    path: Path, g_question_ids: list[str], corpus: str | None = None
) -> None:
    payload: dict[str, Any] = {"g_question_ids": g_question_ids}
    if corpus is not None:
        payload["corpus"] = corpus
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_evaluate_sc3_floor_absent_is_miss_floor_not_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _sc3_row_cls
) -> None:
    monkeypatch.delattr(
        thresholds_module, "VECTOR_BASELINE_USABLE_FLOOR", raising=False
    )

    pop_path = tmp_path / "diag_selection.json"
    _write_populations(pop_path, ["q1", "q2"])
    rows = [_sc3_row_cls(question_id="q1", e_answer_usable=True)]

    reading = evaluate_sc3(rows, pop_path)

    assert reading.status == "MISS"
    assert reading.reason == "floor not committed"


def test_evaluate_sc3_floor_present_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _sc3_row_cls
) -> None:
    """floor 0.47 and 40/80 usable gives PASS."""
    _set_vector_baseline_usable_floor(monkeypatch, 0.47)

    pop_path = tmp_path / "diag_selection.json"
    ids = [f"q{i}" for i in range(80)]
    _write_populations(pop_path, ids)
    rows = [
        _sc3_row_cls(question_id=qid, e_answer_usable=(i < 40))
        for i, qid in enumerate(ids)
    ]

    reading = evaluate_sc3(rows, pop_path)

    assert reading.status == "PASS"
    assert reading.n == 80
    assert reading.value == pytest.approx(0.5)


def test_evaluate_sc3_below_floor_is_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _sc3_row_cls
) -> None:
    _set_vector_baseline_usable_floor(monkeypatch, 0.47)

    pop_path = tmp_path / "diag_selection.json"
    ids = [f"q{i}" for i in range(80)]
    _write_populations(pop_path, ids)
    rows = [
        _sc3_row_cls(question_id=qid, e_answer_usable=(i < 10))
        for i, qid in enumerate(ids)
    ]

    reading = evaluate_sc3(rows, pop_path)

    assert reading.status == "MISS"


def test_evaluate_sc3_empty_population_is_miss_n0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _sc3_row_cls
) -> None:
    """Specless edge: an empty population returns MISS n=0, never PASS."""
    _set_vector_baseline_usable_floor(monkeypatch, 0.47)

    pop_path = tmp_path / "diag_selection.json"
    _write_populations(pop_path, [])

    reading = evaluate_sc3([], pop_path)

    assert reading.status == "MISS"
    assert reading.reason == "n=0"


def test_evaluate_sc3_carries_wilson_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _sc3_row_cls
) -> None:
    _set_vector_baseline_usable_floor(monkeypatch, 0.40)

    pop_path = tmp_path / "diag_selection.json"
    ids = [f"q{i}" for i in range(20)]
    _write_populations(pop_path, ids)
    rows = [
        _sc3_row_cls(question_id=qid, e_answer_usable=(i < 10))
        for i, qid in enumerate(ids)
    ]

    reading = evaluate_sc3(rows, pop_path)

    assert reading.ci is not None
    ci_lo, ci_hi = reading.ci
    assert ci_lo < reading.value < ci_hi


def test_evaluate_sc3_strata_present_with_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Output carries strata by question_type and binary-vs-entity gold, each with its
    constant-Yes baseline, when the populations file names a corpus."""
    _set_vector_baseline_usable_floor(monkeypatch, 0.10)

    from lancet_eval.corpus import load_sample_questions
    from lancet_eval.diagnostic import ArmResult, DiagnosticRow

    corpus = "graphrag_bench"
    questions = load_sample_questions(corpus)
    pop_path = tmp_path / "diag_selection.json"
    ids = [q.question_id for q in questions]
    _write_populations(pop_path, ids, corpus=corpus)

    rows = [
        DiagnosticRow(
            question_id=q.question_id,
            question_type=q.question_type,
            is_null=q.is_null,
            a_gold_doc_in_map=True,
            b_gold_chunk_in_lancedb=True,
            e_answer_usable=True,
            arms={
                "graph-off": ArmResult(
                    arm="graph-off", outcome="success", answer_usable=True
                )
            },
            in_gold_in_index_subset=True,
        )
        for q in questions
    ]

    reading = evaluate_sc3(rows, pop_path)

    assert "strata" in reading.detail
    assert reading.detail["strata"]


def test_evaluate_sc3_corpus_kwarg_works_without_selection_corpus_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real diag_selection.json (06.3.4.1-10's schema: method/seed/quotas/
    g_question_ids/...) carries no `corpus` key -- the caller (main, from the
    journal header) must supply it via the keyword-only `corpus=` argument."""
    _set_vector_baseline_usable_floor(monkeypatch, 0.10)

    from lancet_eval.corpus import load_sample_questions
    from lancet_eval.diagnostic import ArmResult, DiagnosticRow

    corpus = "graphrag_bench"
    questions = load_sample_questions(corpus)
    pop_path = tmp_path / "diag_selection.json"
    ids = [q.question_id for q in questions]
    _write_populations(pop_path, ids)  # no corpus= kwarg -> no "corpus" key

    rows = [
        DiagnosticRow(
            question_id=q.question_id,
            question_type=q.question_type,
            is_null=q.is_null,
            a_gold_doc_in_map=True,
            b_gold_chunk_in_lancedb=True,
            e_answer_usable=True,
            arms={
                "graph-off": ArmResult(
                    arm="graph-off", outcome="success", answer_usable=True
                )
            },
            in_gold_in_index_subset=True,
        )
        for q in questions
    ]

    reading = evaluate_sc3(rows, pop_path, corpus=corpus)

    assert "strata" in reading.detail
    assert reading.detail["strata"]


def test_evaluate_sc3_excludes_d69_generate_answer_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-34: excluded_generate_answer_failures counts graph-off GenerateAnswer
    failures classified into a D-69/marker-mismatch class (AI-SPEC #5), not every
    row lacking a usable answer (not_run/timeout/transport must not count here)."""
    _set_vector_baseline_usable_floor(monkeypatch, 0.10)

    from lancet_eval.diagnostic import ArmResult, DiagnosticRow

    pop_path = tmp_path / "diag_selection.json"
    ids = [f"q{i}" for i in range(4)]
    _write_populations(pop_path, ids)

    rows = [
        DiagnosticRow(
            question_id="q0",
            question_type="inference_query",
            is_null=False,
            a_gold_doc_in_map=True,
            b_gold_chunk_in_lancedb=True,
            e_answer_usable=True,
            arms={
                "graph-off": ArmResult(
                    arm="graph-off", outcome="success", answer_usable=True
                )
            },
            in_gold_in_index_subset=True,
        ),
        # D-69 rejection: MUST count.
        DiagnosticRow(
            question_id="q1",
            question_type="inference_query",
            is_null=False,
            a_gold_doc_in_map=True,
            b_gold_chunk_in_lancedb=True,
            e_answer_usable=None,
            arms={
                "graph-off": ArmResult(
                    arm="graph-off",
                    outcome="error",
                    error_class="citation_basis_mixed",
                )
            },
            in_gold_in_index_subset=True,
        ),
        # transport error: must NOT count (not a GenerateAnswer/D-69 failure).
        DiagnosticRow(
            question_id="q2",
            question_type="inference_query",
            is_null=False,
            a_gold_doc_in_map=True,
            b_gold_chunk_in_lancedb=True,
            e_answer_usable=None,
            arms={
                "graph-off": ArmResult(
                    arm="graph-off", outcome="error", error_class="transport"
                )
            },
            in_gold_in_index_subset=True,
        ),
        # not_run: must NOT count.
        DiagnosticRow(
            question_id="q3",
            question_type="inference_query",
            is_null=False,
            a_gold_doc_in_map=True,
            b_gold_chunk_in_lancedb=True,
            e_answer_usable=None,
            arms={"graph-off": ArmResult(arm="graph-off", outcome="error")},
            in_gold_in_index_subset=True,
        ),
    ]

    reading = evaluate_sc3(rows, pop_path)

    assert reading.detail["excluded_generate_answer_failures"] == 1.0


def test_evaluate_sc3_final_answer_missing_review_triggered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FINAL_ANSWER_MISSING_REVIEW_RATE (D-73) is actually read: a final_answer_missing
    rate above it sets final_answer_missing_review_triggered (AI-SPEC #6)."""
    _set_vector_baseline_usable_floor(monkeypatch, 0.10)

    from lancet_eval.diagnostic import ArmResult, DiagnosticRow

    pop_path = tmp_path / "diag_selection.json"
    ids = [f"q{i}" for i in range(10)]
    _write_populations(pop_path, ids)

    rows = [
        DiagnosticRow(
            question_id=f"q{i}",
            question_type="inference_query",
            is_null=False,
            a_gold_doc_in_map=True,
            b_gold_chunk_in_lancedb=True,
            e_answer_usable=True,
            arms={
                "graph-off": ArmResult(
                    arm="graph-off",
                    outcome="success",
                    answer_usable=True,
                    # 3/10 = 0.30 > FINAL_ANSWER_MISSING_REVIEW_RATE (0.10)
                    final_answer_missing=(i < 3),
                )
            },
            in_gold_in_index_subset=True,
        )
        for i in range(10)
    ]

    reading = evaluate_sc3(rows, pop_path)

    assert reading.detail["final_answer_missing_rate"] == pytest.approx(0.30)
    assert reading.detail["final_answer_missing_review_triggered"] is True


# --- main -----------------------------------------------------------------------------


def test_main_writes_markdown_and_json_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_vector_baseline_usable_floor(monkeypatch, 0.10)

    # graphrag_bench has no seeded document_map.json (it's a fixture-only corpus);
    # stub load_document_map so build_rows (called from main()) doesn't need one.
    import lancet_eval.diagnostic as diagnostic_module
    from lancet_eval.seed import DocumentMap

    monkeypatch.setattr(
        diagnostic_module,
        "load_document_map",
        lambda corpus_name: DocumentMap(corpus=corpus_name),
    )

    corpus = "graphrag_bench"
    from lancet_eval.corpus import load_corpus_config, load_sample_questions

    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    j_path = run_dir / "journal.jsonl"
    _write_sc1_journal(
        j_path,
        corpus=corpus,
        questions=questions,
        arms=config.arms,
        header_partial=True,
    )

    gold_chunks_path = tmp_path / "gold_chunks.jsonl"
    with open(gold_chunks_path, "w", encoding="utf-8") as f:
        for q in questions:
            for ev_idx, _item in enumerate(q.evidence_list):
                f.write(
                    json.dumps(
                        {
                            "question_id": q.question_id,
                            "evidence_index": ev_idx,
                            "state": "in_chunk",
                        }
                    )
                    + "\n"
                )

    pop_path = tmp_path / "diag_selection.json"
    _write_populations(pop_path, [q.question_id for q in questions], corpus=corpus)

    out_path = tmp_path / "out" / "UNPARK-GATES.md"

    exit_code = main(
        [
            "--stage",
            "drive1",
            "--run",
            str(run_dir),
            "--gold-chunks",
            str(gold_chunks_path),
            "--populations",
            str(pop_path),
            "--engine-pid-before",
            "1",
            "--engine-pid-after",
            "1",
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 0
    assert out_path.is_file()
    json_path = out_path.with_suffix(".json")
    assert json_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "SC-1" in payload
    assert "SC-2" in payload
    assert "SC-3" in payload


# --- drive 2: SC-4, SC-5 and graph-off invariance (06.3.4.1-17) -----------------------

_ABLATION = Notice(code="GRAPH_ABLATION", message="graph ablated", typed_code=18)
_GOLD_FACT = "a gold fact"


def _chunk(
    chunk_id: str,
    *,
    boosted: bool | None = None,
    gold: bool = False,
    rank: int = 1,
) -> StructuredCitation:
    return StructuredCitation(
        chunk_id=chunk_id,
        document_id=chunk_id.split(":")[0],
        excerpt=_GOLD_FACT if gold else "unrelated text",
        rank=rank,
        graph_boosted=boosted,
    )


def _arm_record(
    question_id: str,
    arm: str,
    *,
    chunks: list[StructuredCitation] | None = None,
    answer: str = "Answer: entity",
    graph_nodes: int = 0,
    graph_edges: int = 0,
    prompt_facts: int | None = None,
    prompt_tokens: int = 100,
    duration_ms: float = 1000.0,
    outcome: str = "success",
) -> RunRecord:
    is_off = arm == "graph-off"
    return RunRecord(
        corpus="multihop_rag",
        question_id=question_id,
        graph_arm=arm,
        outcome=outcome,  # type: ignore[arg-type]
        answer=answer if outcome == "success" else None,
        snapshot=RetrievalSnapshot(retrieved_chunks=chunks or []),
        notices=[_ABLATION] if is_off else [],
        index_generation="gen-1",
        duration_ms=duration_ms,
        workflow_meta=WorkflowWireMeta(
            graph_node_count=graph_nodes,
            graph_edge_count=graph_edges,
            graph_prompt_fact_count=prompt_facts,
            prompt_tokens=prompt_tokens,
        ),
    )


def _qid(i: int) -> str:
    return f"q{i:03d}"


def _gold_map(
    n: int, *, question_type: str = "inference_query"
) -> dict[str, GoldQuestion]:
    return {
        _qid(i): _gold_question(_qid(i), question_type=question_type) for i in range(n)
    }


def _write_selection(
    path: Path, *, g: list[str], v: list[str] | None = None
) -> Path:
    payload: dict[str, Any] = {"g_question_ids": g}
    if v is not None:
        payload["v_question_ids"] = v
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _presence_journal(
    tmp_path: Path, *, n: int, present: int
) -> tuple[Path, Path, dict[str, GoldQuestion]]:
    """n dual-success pairs, the first `present` with graph facts on graph-on."""
    records: list[RunRecord] = []
    for i in range(n):
        records.append(
            _arm_record(_qid(i), "graph-on", graph_nodes=3 if i < present else 0)
        )
        records.append(_arm_record(_qid(i), "graph-off"))
    journal = tmp_path / "journal.jsonl"
    _write_journal(journal, records, corpus="multihop_rag")
    selection = _write_selection(
        tmp_path / "diag_selection.json", g=[_qid(i) for i in range(n)]
    )
    return journal, selection, _gold_map(n)


# SC-4 -------------------------------------------------------------------------------


def test_sc4_ten_of_forty_pairs_in_g_with_presence_passes(tmp_path: Path) -> None:
    journal, selection, gold = _presence_journal(tmp_path, n=40, present=10)
    reading = evaluate_sc4(journal, selection, gold_questions=gold)
    assert reading.gate == "SC-4"
    assert reading.status == "PASS", reading.reason
    assert reading.value == pytest.approx(0.25)
    assert reading.n == 40
    assert reading.ci is not None and 0.13 < reading.ci[0] < 0.16


def test_sc4_five_of_forty_misses_the_investigation_floor(tmp_path: Path) -> None:
    journal, selection, gold = _presence_journal(tmp_path, n=40, present=5)
    reading = evaluate_sc4(journal, selection, gold_questions=gold)
    assert reading.status == "MISS"
    assert reading.value == pytest.approx(0.125)
    assert "0.20" in reading.reason


def test_sc4_one_of_five_misses_on_the_wilson_clause_only(tmp_path: Path) -> None:
    journal, selection, gold = _presence_journal(tmp_path, n=5, present=1)
    reading = evaluate_sc4(journal, selection, gold_questions=gold)
    assert reading.value == pytest.approx(0.20), "0.20 meets the floor itself"
    assert reading.ci is not None and 0.03 < reading.ci[0] < 0.04
    assert reading.status == "MISS"
    assert "Wilson" in reading.reason
    assert "investigation floor" not in reading.reason


def test_sc4_without_a_pair_in_g_is_miss_n0(tmp_path: Path) -> None:
    journal, _, gold = _presence_journal(tmp_path, n=10, present=10)
    selection = _write_selection(tmp_path / "other.json", g=["not-in-the-journal"])
    reading = evaluate_sc4(journal, selection, gold_questions=gold)
    assert reading.status == "MISS"
    assert reading.reason == "n=0"
    assert reading.n == 0


def test_sc4_restricts_the_headline_to_g_and_reports_a_and_all_usable(
    tmp_path: Path,
) -> None:
    # 40 pairs; G is the first 20 and none of them show the graph, the other 20 all do.
    records: list[RunRecord] = []
    for i in range(40):
        records.append(
            _arm_record(
                _qid(i), "graph-on", graph_nodes=0 if i < 20 else 2, prompt_facts=0
            )
        )
        records.append(_arm_record(_qid(i), "graph-off"))
    # One graph-on record whose graph-off twin errored: usable, but in no pair.
    records.append(_arm_record("lone", "graph-on", graph_nodes=1, prompt_facts=1))
    records.append(_arm_record("lone", "graph-off", outcome="error"))
    journal = tmp_path / "journal.jsonl"
    _write_journal(journal, records, corpus="multihop_rag")
    selection = _write_selection(tmp_path / "sel.json", g=[_qid(i) for i in range(20)])
    gold = {**_gold_map(40), "lone": _gold_question("lone")}

    reading = evaluate_sc4(journal, selection, gold_questions=gold)

    assert reading.status == "MISS"
    assert reading.value == pytest.approx(0.0), "the headline is over pairs(G) only"
    populations = reading.detail["populations"]
    assert populations["pairs_G"]["n"] == 20
    assert populations["pairs_A"]["n"] == 40
    assert populations["pairs_A"]["rate"] == pytest.approx(0.5)
    assert populations["all_usable_graph_on"]["n"] == 41
    assert populations["all_usable_graph_on"]["positive_n"] == 21


def test_sc4_carries_influence_and_no_match_rates(tmp_path: Path) -> None:
    records: list[RunRecord] = []
    for i in range(10):
        records.append(
            _arm_record(
                _qid(i),
                "graph-on",
                graph_nodes=1 if i < 4 else 0,
                prompt_facts=2 if i < 2 else 0,
            )
        )
        records.append(_arm_record(_qid(i), "graph-off"))
    journal = tmp_path / "journal.jsonl"
    _write_journal(journal, records, corpus="multihop_rag")
    selection = _write_selection(tmp_path / "sel.json", g=[_qid(i) for i in range(10)])

    reading = evaluate_sc4(journal, selection, gold_questions=_gold_map(10))

    pairs_g = reading.detail["populations"]["pairs_G"]
    assert pairs_g["positive_n"] == 4
    assert pairs_g["influence_n"] == 10
    assert pairs_g["influence_positive_n"] == 2
    assert pairs_g["influence_rate"] == pytest.approx(0.2)
    assert "no_match_rate" in pairs_g


def test_sc4_influence_is_unreported_when_the_field_is_absent(tmp_path: Path) -> None:
    journal, selection, gold = _presence_journal(tmp_path, n=10, present=5)
    reading = evaluate_sc4(journal, selection, gold_questions=gold)
    pairs_g = reading.detail["populations"]["pairs_G"]
    assert pairs_g["influence_n"] == 0
    assert pairs_g["influence_rate"] is None, "None is not zero"


# SC-5 -------------------------------------------------------------------------------


def _composition_journal(
    tmp_path: Path,
    *,
    n: int,
    boosted_for: set[int] | None = None,
    on_gold_for: set[int] | None = None,
    off_gold_for: set[int] | None = None,
    on_answer_correct_for: set[int] | None = None,
    off_answer_correct_for: set[int] | None = None,
) -> tuple[Path, Path, dict[str, GoldQuestion]]:
    """n dual-success pairs, all of them in V (and G).

    Graph-on's final set always differs from graph-off's by a chunk id, so a plain
    set difference is everywhere; only the pairs in `boosted_for` carry a
    `graph_boosted` chunk the graph-off set lacks.
    """
    boosted_for = boosted_for or set()
    on_gold_for = on_gold_for or set()
    off_gold_for = off_gold_for or set()
    on_ok = on_answer_correct_for or set()
    off_ok = off_answer_correct_for or set()
    records: list[RunRecord] = []
    for i in range(n):
        qid = _qid(i)
        on_chunks = [_chunk(f"d-on-{i}:0", gold=i in on_gold_for, boosted=False)]
        if i in boosted_for:
            on_chunks.append(_chunk(f"d-boost-{i}:1", boosted=True, rank=2))
        else:
            on_chunks.append(_chunk(f"d-plain-{i}:1", boosted=False, rank=2))
        off_chunks = [_chunk(f"d-off-{i}:0", gold=i in off_gold_for)]
        records.append(
            _arm_record(
                qid,
                "graph-on",
                chunks=on_chunks,
                answer="Answer: entity" if i in on_ok else "Answer: wrong",
                graph_nodes=1,
            )
        )
        records.append(
            _arm_record(
                qid,
                "graph-off",
                chunks=off_chunks,
                answer="Answer: entity" if i in off_ok else "Answer: wrong",
            )
        )
    journal = tmp_path / "journal.jsonl"
    _write_journal(journal, records, corpus="multihop_rag")
    ids = [_qid(i) for i in range(n)]
    selection = _write_selection(tmp_path / "sel.json", g=ids, v=ids)
    return journal, selection, _gold_map(n)


def test_sc5_composition_five_of_forty_meets_the_floor(tmp_path: Path) -> None:
    journal, selection, gold = _composition_journal(
        tmp_path, n=40, boosted_for=set(range(5))
    )
    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)
    assert reading.gate == "SC-5"
    assert reading.status == "PASS", reading.reason
    composition = reading.detail["populations"]["pairs_V"]["composition"]
    assert composition["changed_n"] == 5
    assert composition["n"] == 40
    assert composition["rate"] == pytest.approx(0.125)


def test_sc5_two_of_forty_composition_passes_through_a_coverage_delta(
    tmp_path: Path,
) -> None:
    # Graph-on holds the gold fact in every pair and graph-off in none: delta +1.
    journal, selection, gold = _composition_journal(
        tmp_path, n=40, boosted_for={0, 1}, on_gold_for=set(range(40))
    )
    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)
    assert reading.status == "PASS", reading.reason
    pairs_v = reading.detail["populations"]["pairs_V"]
    assert pairs_v["composition"]["rate"] == pytest.approx(0.05)
    delta = pairs_v["deltas"]["coverage_at_4"]
    assert delta["mean"] == pytest.approx(1.0)
    assert delta["ci_lower"] > 0
    assert delta["n_pairs"] == 40
    assert reading.detail["negative"] is False


def test_sc5_two_of_forty_composition_with_a_ci_through_zero_misses(
    tmp_path: Path,
) -> None:
    # Half the pairs gain the gold fact and half lose it: the mean delta is 0.
    journal, selection, gold = _composition_journal(
        tmp_path,
        n=40,
        boosted_for={0, 1},
        on_gold_for=set(range(20)),
        off_gold_for=set(range(20, 40)),
    )
    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)
    assert reading.status == "MISS"
    delta = reading.detail["populations"]["pairs_V"]["deltas"]["coverage_at_4"]
    assert delta["ci_lower"] <= 0 <= delta["ci_upper"]


def test_sc5_a_plain_set_difference_is_not_a_composition_change(
    tmp_path: Path,
) -> None:
    # Every pair's final sets differ (reformulation), but no chunk is graph_boosted.
    journal, selection, gold = _composition_journal(tmp_path, n=40, boosted_for=set())
    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)
    composition = reading.detail["populations"]["pairs_V"]["composition"]
    assert composition["n"] == 40
    assert composition["changed_n"] == 0
    assert reading.status == "MISS"


def test_sc5_a_boosted_chunk_that_graph_off_also_holds_is_not_a_change(
    tmp_path: Path,
) -> None:
    records = []
    for i in range(10):
        records.append(
            _arm_record(
                _qid(i), "graph-on", chunks=[_chunk(f"shared-{i}:0", boosted=True)]
            )
        )
        records.append(
            _arm_record(_qid(i), "graph-off", chunks=[_chunk(f"shared-{i}:0")])
        )
    journal = tmp_path / "journal.jsonl"
    _write_journal(journal, records, corpus="multihop_rag")
    ids = [_qid(i) for i in range(10)]
    selection = _write_selection(tmp_path / "sel.json", g=ids, v=ids)
    reading = evaluate_sc5(
        journal, selection, gold_questions=_gold_map(10), chunk_size=500
    )
    composition = reading.detail["populations"]["pairs_V"]["composition"]
    assert composition["n"] == 10
    assert composition["changed_n"] == 0


def test_sc5_one_pair_without_a_composition_change_misses(tmp_path: Path) -> None:
    # n = 1: the paired CI collapses to a point, so there is no interval to exclude 0.
    journal, selection, gold = _composition_journal(
        tmp_path, n=1, on_gold_for={0}, on_answer_correct_for={0}
    )
    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)
    assert reading.status == "MISS"
    delta = reading.detail["populations"]["pairs_V"]["deltas"]["coverage_at_4"]
    assert delta["n_pairs"] == 1
    assert delta["is_degenerate"] is True


def test_sc5_one_pair_with_a_composition_change_passes(tmp_path: Path) -> None:
    journal, selection, gold = _composition_journal(tmp_path, n=1, boosted_for={0})
    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)
    assert reading.status == "PASS", reading.reason


def test_sc5_without_a_pair_in_v_is_miss_n0(tmp_path: Path) -> None:
    journal, _, gold = _composition_journal(tmp_path, n=5, boosted_for={0, 1, 2})
    selection = _write_selection(
        tmp_path / "other.json", g=[_qid(0)], v=["not-in-the-journal"]
    )
    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)
    assert reading.status == "MISS"
    assert reading.reason == "n=0"


def test_sc5_negative_delta_with_a_ci_excluding_zero_passes_and_is_flagged(
    tmp_path: Path,
) -> None:
    # Graph-off holds the gold fact in every pair and graph-on in none: delta -1.
    journal, selection, gold = _composition_journal(
        tmp_path, n=10, off_gold_for=set(range(10))
    )
    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)
    assert reading.status == "PASS", "direction is not part of the rule (D-82)"
    assert reading.detail["negative"] is True
    assert "negative" in reading.reason


def test_sc5_an_answer_usable_delta_also_qualifies(tmp_path: Path) -> None:
    journal, selection, gold = _composition_journal(
        tmp_path, n=10, on_answer_correct_for=set(range(10))
    )
    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)
    assert reading.status == "PASS", reading.reason
    delta = reading.detail["populations"]["pairs_V"]["deltas"]["answer_usable"]
    assert delta["mean"] == pytest.approx(1.0)


def test_sc5_unmeasured_composition_is_not_a_zero(tmp_path: Path) -> None:
    # Every graph-on chunk lacks the flag (a journal that predates it).
    records = []
    for i in range(10):
        records.append(
            _arm_record(_qid(i), "graph-on", chunks=[_chunk(f"on-{i}:0", boosted=None)])
        )
        records.append(
            _arm_record(_qid(i), "graph-off", chunks=[_chunk(f"off-{i}:0")])
        )
    journal = tmp_path / "journal.jsonl"
    _write_journal(journal, records, corpus="multihop_rag")
    ids = [_qid(i) for i in range(10)]
    selection = _write_selection(tmp_path / "sel.json", g=ids, v=ids)
    reading = evaluate_sc5(
        journal, selection, gold_questions=_gold_map(10), chunk_size=500
    )
    composition = reading.detail["populations"]["pairs_V"]["composition"]
    assert composition["n"] == 0
    assert composition["unmeasured_n"] == 10
    assert composition["rate"] is None
    assert reading.status == "MISS"


def test_sc5_reports_v_g_and_a_with_cost_deltas_and_strata(tmp_path: Path) -> None:
    journal, selection, gold = _composition_journal(
        tmp_path, n=6, boosted_for={0}, on_gold_for={0, 1}
    )
    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)
    populations = reading.detail["populations"]
    assert set(populations) == {"pairs_V", "pairs_G", "pairs_A"}
    deltas = populations["pairs_V"]["deltas"]
    assert set(deltas) == {
        "coverage_at_4",
        "answer_usable",
        "final_answer_em",
        "latency_ms",
        "prompt_tokens",
    }
    coverage = deltas["coverage_at_4"]
    assert {"n_pairs", "pairing_coverage", "strata", "mean"} <= set(coverage)
    assert coverage["strata"] == {"inference_query": pytest.approx(1 / 3)}


def test_sc5_requires_the_committed_v_population(tmp_path: Path) -> None:
    journal, _, gold = _composition_journal(tmp_path, n=5, boosted_for={0})
    selection = _write_selection(tmp_path / "no_v.json", g=[_qid(0)])
    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)
    assert reading.status == "MISS"
    assert "v_question_ids" in reading.reason


def test_the_drive2_literals_are_committed_with_their_values() -> None:
    assert thresholds_module.GRAPH_COMPOSITION_CHANGE_FLOOR == pytest.approx(0.10)
    assert thresholds_module.GRAPH_PRESENCE_WILSON_LOWER_FLOOR == pytest.approx(0.098)
    assert thresholds_module.SC5_VISIBILITY_RULE == (
        "composition_floor_or_paired_ci_excludes_zero_n_ge_2"
    )


# graph-off invariance ---------------------------------------------------------------


def _off_journal(
    path: Path,
    specs: dict[str, tuple[str, list[str]]],
    *,
    extra: list[RunRecord] | None = None,
) -> Path:
    records = [
        _arm_record(
            qid,
            "graph-off",
            answer=answer,
            chunks=[_chunk(cid) for cid in chunk_ids],
        )
        for qid, (answer, chunk_ids) in specs.items()
    ]
    # A graph-on record must never be compared.
    records.append(_arm_record("q000", "graph-on", answer="Answer: other"))
    records.extend(extra or [])
    _write_journal(path, records, corpus="multihop_rag")
    return path


def test_invariance_of_identical_graph_off_arms_reports_no_difference(
    tmp_path: Path,
) -> None:
    specs = {
        "q000": ("Answer: entity", ["a:0", "b:1"]),
        "q001": ("Answer: wrong", ["c:0"]),
    }
    baseline = _off_journal(tmp_path / "base.jsonl", specs)
    drive2 = _off_journal(tmp_path / "d2.jsonl", specs)
    report = graph_off_invariance(baseline, drive2, gold_questions=_gold_map(2))
    assert report.n_common == 2
    assert report.answer_usable_agree_n == 2
    assert report.retrieved_set_equal_n == 2
    assert report.retrieved_order_equal_n == 2
    assert report.any_difference is False


def test_invariance_names_the_questions_that_changed(tmp_path: Path) -> None:
    baseline = _off_journal(
        tmp_path / "base.jsonl",
        {
            "q000": ("Answer: entity", ["a:0", "b:1"]),
            "q001": ("Answer: wrong", ["c:0"]),
            "q002": ("Answer: entity", ["d:0", "e:0"]),
        },
    )
    drive2 = _off_journal(
        tmp_path / "d2.jsonl",
        {
            "q000": ("Answer: wrong", ["a:0", "b:1"]),
            "q001": ("Answer: wrong", ["c:0", "z:9"]),
            "q002": ("Answer: entity", ["e:0", "d:0"]),
        },
    )
    report = graph_off_invariance(baseline, drive2, gold_questions=_gold_map(3))
    assert report.answer_usable_agree_n == 2
    assert report.answer_usable_disagree_ids == ["q000"]
    assert report.retrieved_set_differ_ids == ["q001"]
    assert report.retrieved_set_equal_n == 2
    assert report.retrieved_order_equal_n == 1, "q002 holds the same set in a new order"
    assert report.any_difference is True


def test_invariance_lists_questions_present_in_only_one_journal(
    tmp_path: Path,
) -> None:
    baseline = _off_journal(
        tmp_path / "base.jsonl",
        {"q000": ("Answer: entity", ["a:0"]), "q001": ("Answer: entity", ["b:0"])},
    )
    drive2 = _off_journal(
        tmp_path / "d2.jsonl",
        {"q000": ("Answer: entity", ["a:0"]), "q002": ("Answer: entity", ["c:0"])},
    )
    report = graph_off_invariance(baseline, drive2, gold_questions=_gold_map(3))
    assert report.n_common == 1
    assert report.only_in_baseline == ["q001"]
    assert report.only_in_drive2 == ["q002"]


def test_invariance_reports_collapsed_duplicate_records(tmp_path: Path) -> None:
    baseline = _off_journal(
        tmp_path / "base.jsonl",
        {"q000": ("Answer: entity", ["a:0"])},
        extra=[_arm_record("q000", "graph-off", answer="Answer: wrong")],
    )
    drive2 = _off_journal(tmp_path / "d2.jsonl", {"q000": ("Answer: wrong", ["a:0"])})
    report = graph_off_invariance(baseline, drive2, gold_questions=_gold_map(1))
    assert report.collapsed_duplicates == {"baseline": 1, "drive2": 0}
    # The later duplicate wins, as `deduplicate_by_arm` does everywhere else.
    assert report.answer_usable_agree_n == 1


def test_invariance_does_not_compare_an_errored_graph_off_record(
    tmp_path: Path,
) -> None:
    baseline = _off_journal(
        tmp_path / "base.jsonl", {"q000": ("Answer: entity", ["a:0"])}
    )
    drive2 = tmp_path / "d2.jsonl"
    _write_journal(
        drive2,
        [_arm_record("q000", "graph-off", outcome="error")],
        corpus="multihop_rag",
    )
    report = graph_off_invariance(baseline, drive2, gold_questions=_gold_map(1))
    assert report.n_common == 1
    assert report.n_comparable == 0
    assert report.not_comparable_ids == ["q000"]
    assert report.answer_usable_agree_n == 0


# main --stage drive2 ----------------------------------------------------------------


def _main_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path, Path]:
    _set_vector_baseline_usable_floor(monkeypatch, 0.10)
    import lancet_eval.diagnostic as diagnostic_module
    from lancet_eval.corpus import load_corpus_config, load_sample_questions
    from lancet_eval.seed import DocumentMap

    monkeypatch.setattr(
        diagnostic_module,
        "load_document_map",
        lambda corpus_name: DocumentMap(corpus=corpus_name),
    )
    corpus = "graphrag_bench"
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_sc1_journal(
        run_dir / "journal.jsonl",
        corpus=corpus,
        questions=questions,
        arms=config.arms,
        header_partial=True,
    )
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    _write_sc1_journal(
        baseline_dir / "journal.jsonl",
        corpus=corpus,
        questions=questions,
        arms=config.arms,
        header_partial=True,
    )
    gold_chunks = tmp_path / "gold_chunks.jsonl"
    with open(gold_chunks, "w", encoding="utf-8") as f:
        for q in questions:
            for ev_idx, _item in enumerate(q.evidence_list):
                f.write(
                    json.dumps(
                        {
                            "question_id": q.question_id,
                            "evidence_index": ev_idx,
                            "state": "in_chunk",
                        }
                    )
                    + "\n"
                )
    ids = [q.question_id for q in questions]
    selection = _write_selection(tmp_path / "diag_selection.json", g=ids, v=ids)
    return run_dir, baseline_dir, gold_chunks, selection


def _main_args(
    stage: str, run_dir: Path, gold_chunks: Path, selection: Path, out: Path
) -> list[str]:
    return [
        "--stage",
        stage,
        "--run",
        str(run_dir),
        "--gold-chunks",
        str(gold_chunks),
        "--populations",
        str(selection),
        "--engine-pid-before",
        "1",
        "--engine-pid-after",
        "1",
        "--out",
        str(out),
    ]


@pytest.mark.parametrize("stage", ["drive1", "drive1b"])
def test_main_for_the_earlier_stages_writes_exactly_the_four_readings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    run_dir, _, gold_chunks, selection = _main_fixture(tmp_path, monkeypatch)
    out = tmp_path / "out" / "GATES.md"
    code = main(_main_args(stage, run_dir, gold_chunks, selection, out))
    assert code == 0
    payload = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert list(payload) == ["SC-1", "SC-2", "D-69 companion", "SC-3"]
    assert f"# Unpark Gates ({stage})" in out.read_text(encoding="utf-8")


def test_main_drive2_requires_a_baseline_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, _, gold_chunks, selection = _main_fixture(tmp_path, monkeypatch)
    out = tmp_path / "out" / "GATES.md"
    with pytest.raises(SystemExit) as exc:
        main(_main_args("drive2", run_dir, gold_chunks, selection, out))
    assert exc.value.code == 2
    assert not out.exists()


def test_main_drive2_adds_sc4_sc5_and_the_invariance_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir, baseline_dir, gold_chunks, selection = _main_fixture(tmp_path, monkeypatch)
    out = tmp_path / "out" / "GATES.md"
    code = main(
        [
            *_main_args("drive2", run_dir, gold_chunks, selection, out),
            "--baseline-run",
            str(baseline_dir),
        ]
    )
    assert code == 0
    payload = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert list(payload) == [
        "SC-1",
        "SC-2",
        "D-69 companion",
        "SC-3",
        "SC-4",
        "SC-5",
        "graph-off invariance",
    ]
    assert payload["SC-4"]["gate"] == "SC-4"
    markdown = out.read_text(encoding="utf-8")
    assert "# Unpark Gates (drive2)" in markdown
    assert "disclosure" in markdown.lower()


def _unpaired_boost_journal(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, GoldQuestion]]:
    """Three V pairs plus graph-on records that sit in no pair.

    q000 holds a boosted chunk, q001 an unboosted one, q002 only unflagged chunks (a
    record that predates the flag). `lone` is a usable graph-on record whose graph-off
    twin errored (boosted); `broken` is a graph-on record that errored itself.
    """
    records = [
        _arm_record(
            "q000", "graph-on", chunks=[_chunk("on-0:0", boosted=True)], graph_nodes=1
        ),
        _arm_record("q000", "graph-off", chunks=[_chunk("off-0:0")]),
        _arm_record(
            "q001", "graph-on", chunks=[_chunk("on-1:0", boosted=False)], graph_nodes=1
        ),
        _arm_record("q001", "graph-off", chunks=[_chunk("off-1:0")]),
        _arm_record(
            "q002", "graph-on", chunks=[_chunk("on-2:0", boosted=None)], graph_nodes=1
        ),
        _arm_record("q002", "graph-off", chunks=[_chunk("off-2:0")]),
        _arm_record("lone", "graph-on", chunks=[_chunk("on-l:0", boosted=True)]),
        _arm_record("lone", "graph-off", outcome="error"),
        _arm_record("broken", "graph-on", outcome="error"),
        _arm_record("broken", "graph-off", chunks=[_chunk("off-b:0")]),
    ]
    journal = tmp_path / "journal.jsonl"
    _write_journal(journal, records, corpus="multihop_rag")
    ids = ["q000", "q001", "q002"]
    selection = _write_selection(tmp_path / "sel.json", g=ids, v=ids)
    gold = {
        **_gold_map(3),
        "lone": _gold_question("lone"),
        "broken": _gold_question("broken"),
    }
    return journal, selection, gold


def test_sc5_discloses_the_unpaired_boost_share_over_all_usable_graph_on(
    tmp_path: Path,
) -> None:
    journal, selection, gold = _unpaired_boost_journal(tmp_path)
    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)
    block = reading.detail["unpaired_all_usable_graph_on"]
    # q000, q001 and lone are measured; q002 predates the flag; broken is unusable.
    assert block["n"] == 3
    assert block["boosted_n"] == 2
    assert block["rate"] == pytest.approx(2 / 3)
    assert block["unmeasured_n"] == 1
    assert block["paired"] is False


def test_sc5_unpaired_boost_share_never_feeds_the_pass_rule(tmp_path: Path) -> None:
    # Every V pair is unboosted, so the paired composition is 0; the unpaired block
    # (here 40/40 boosted) must not turn that MISS into a PASS.
    records: list[RunRecord] = []
    for i in range(3):
        records.append(
            _arm_record(
                _qid(i), "graph-on", chunks=[_chunk(f"on-{i}:0", boosted=False)]
            )
        )
        records.append(_arm_record(_qid(i), "graph-off", chunks=[_chunk(f"off-{i}:0")]))
    for i in range(40):
        records.append(
            _arm_record(
                f"lone{i}", "graph-on", chunks=[_chunk(f"l-{i}:0", boosted=True)]
            )
        )
    journal = tmp_path / "journal.jsonl"
    _write_journal(journal, records, corpus="multihop_rag")
    ids = [_qid(i) for i in range(3)]
    selection = _write_selection(tmp_path / "sel.json", g=ids, v=ids)
    gold = {
        **_gold_map(3),
        **{f"lone{i}": _gold_question(f"lone{i}") for i in range(40)},
    }
    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)
    # 3 unboosted pair records + 40 boosted lone records: 40 of 43.
    assert reading.detail["unpaired_all_usable_graph_on"]["rate"] == pytest.approx(
        40 / 43
    )
    assert reading.status == "MISS"


def test_sc5_unpaired_boost_share_is_none_without_a_usable_graph_on_record(
    tmp_path: Path,
) -> None:
    records = [
        _arm_record("q000", "graph-on", outcome="error"),
        _arm_record("q000", "graph-off", chunks=[_chunk("off-0:0")]),
    ]
    journal = tmp_path / "journal.jsonl"
    _write_journal(journal, records, corpus="multihop_rag")
    selection = _write_selection(tmp_path / "sel.json", g=["q000"], v=["q000"])
    reading = evaluate_sc5(
        journal, selection, gold_questions=_gold_map(1), chunk_size=500
    )
    block = reading.detail["unpaired_all_usable_graph_on"]
    assert (block["n"], block["rate"]) == (0, None)


# --- main: completeness precondition (06.3.4.1-32, CR-02) ---------------------------

_INCOMPLETE_REASON = "journal incomplete: 1 work unit(s) missing"
_EARLIER_STAGE_KEYS = ["SC-1", "SC-2", "D-69 companion", "SC-3"]
_DRIVE2_READING_KEYS = [*_EARLIER_STAGE_KEYS, "SC-4", "SC-5"]


def _truncate_last_record(journal: Path) -> None:
    lines = journal.read_text(encoding="utf-8").splitlines()
    journal.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")


def _forbid_reading_computation(monkeypatch: pytest.MonkeyPatch) -> None:
    """No reading may be computed from the records of an incomplete journal."""
    import lancet_eval.unpark_gates as module

    def _forbidden(name: str):
        def _raise(*args: Any, **kwargs: Any) -> None:
            raise AssertionError(f"{name} computed from an incomplete journal")

        return _raise

    for name in (
        "evaluate_sc2",
        "citation_rejection_rate",
        "build_rows",
        "evaluate_sc3",
        "evaluate_sc4",
        "evaluate_sc5",
        "graph_off_invariance",
    ):
        monkeypatch.setattr(module, name, _forbidden(name))


def _run_main(
    stage: str,
    tmp_path: Path,
    fixture: tuple[Path, Path, Path, Path],
) -> tuple[dict[str, Any], str]:
    run_dir, baseline_dir, gold_chunks, selection = fixture
    out = tmp_path / "out" / "GATES.md"
    args = _main_args(stage, run_dir, gold_chunks, selection, out)
    if stage == "drive2":
        args += ["--baseline-run", str(baseline_dir)]
    assert main(args) == 0
    payload = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    return payload, out.read_text(encoding="utf-8")


@pytest.mark.parametrize("stage", ["drive1", "drive2"])
def test_main_misses_every_reading_on_an_incomplete_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    fixture = _main_fixture(tmp_path, monkeypatch)
    _truncate_last_record(fixture[0] / "journal.jsonl")
    _forbid_reading_computation(monkeypatch)

    payload, markdown = _run_main(stage, tmp_path, fixture)

    keys = _DRIVE2_READING_KEYS if stage == "drive2" else _EARLIER_STAGE_KEYS
    expected_order = [*keys, "graph-off invariance"] if stage == "drive2" else keys
    assert list(payload) == expected_order
    for name in keys:
        assert payload[name]["status"] == "MISS", name
    assert _INCOMPLETE_REASON in payload["SC-1"]["reason"]
    assert payload["SC-1"]["detail"]["journal_complete"] is False
    for name in keys[1:]:
        assert payload[name]["gate"] == (
            "citation_rejection_rate" if name == "D-69 companion" else name
        )
        assert payload[name]["reason"] == _INCOMPLETE_REASON, name
        assert payload[name]["detail"]["journal_complete"] is False
        assert payload[name]["detail"]["missing_units"] == 1
    assert f"# Unpark Gates ({stage})" in markdown
    if stage == "drive2":
        assert payload["graph-off invariance"] == {"not_computed": _INCOMPLETE_REASON}
        assert f"not computed: {_INCOMPLETE_REASON}" in markdown
        assert "## Gates" in markdown


def test_main_misses_every_reading_when_the_run_has_no_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _main_fixture(tmp_path, monkeypatch)
    (fixture[0] / "journal.jsonl").unlink()
    _forbid_reading_computation(monkeypatch)

    payload, _ = _run_main("drive1", tmp_path, fixture)

    assert list(payload) == _EARLIER_STAGE_KEYS
    for name in _EARLIER_STAGE_KEYS:
        assert payload[name]["status"] == "MISS", name
        assert payload[name]["reason"] == "no journal file", name


def test_main_a_complete_journal_with_a_dishonest_header_misses_sc1_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `_main_fixture` writes a COMPLETE journal under header partial=true: a header
    # mismatch is a different condition from incompleteness and MISSes SC-1 alone.
    fixture = _main_fixture(tmp_path, monkeypatch)

    payload, _ = _run_main("drive1", tmp_path, fixture)

    assert payload["SC-1"]["status"] == "MISS"
    assert "header partial=True" in payload["SC-1"]["reason"]
    assert payload["SC-1"]["detail"]["journal_complete"] is True
    for name in ("SC-2", "D-69 companion", "SC-3"):
        assert "journal incomplete" not in payload[name]["reason"], name


@pytest.mark.parametrize("truncate", [False, True])
def test_main_measures_completeness_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, truncate: bool
) -> None:
    import lancet_eval.unpark_gates as module

    fixture = _main_fixture(tmp_path, monkeypatch)
    if truncate:
        _truncate_last_record(fixture[0] / "journal.jsonl")
    calls: list[tuple[Any, ...]] = []
    real = module.completeness_comparison

    def _counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "completeness_comparison", _counting)

    _run_main("drive1", tmp_path, fixture)

    assert len(calls) == 1


# --- coverage floor (06.3.4.1-32, CR-02/WR-04) ---------------------------------------


def test_the_coverage_floor_is_committed_and_equals_the_gate_literal() -> None:
    """D-73 / 06.3.1 D-44: the 0.80 reuses `gate.py`'s literal, fixed on 2026-09-09
    (commit eb893ba1), before any 06.3.4.1 drive data existed. It is not an import:
    `gate.py` imports `thresholds`."""
    from lancet_eval import gate

    assert thresholds_module.UNPARK_GATE_COVERAGE_FLOOR == pytest.approx(0.80)
    assert (
        thresholds_module.UNPARK_GATE_COVERAGE_FLOOR
        == gate.STAGED_PAIRING_COVERAGE_FLOOR
    )


def _sc3_coverage_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sc3_row_cls: Any,
    *,
    scored: int,
) -> tuple[list[Any], Path]:
    """Ten G questions; the first `scored` carry a usable answer (rate 1.0), the rest
    were dropped from `scored_rows` (e_answer_usable None)."""
    _set_vector_baseline_usable_floor(monkeypatch, 0.47)
    ids = [f"q{i}" for i in range(10)]
    pop_path = tmp_path / "diag_selection.json"
    _write_populations(pop_path, ids)
    rows = [
        sc3_row_cls(question_id=qid, e_answer_usable=True if i < scored else None)
        for i, qid in enumerate(ids)
    ]
    return rows, pop_path


def test_sc3_seven_of_ten_misses_on_coverage_despite_a_passing_usable_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _sc3_row_cls
) -> None:
    rows, pop_path = _sc3_coverage_fixture(
        tmp_path, monkeypatch, _sc3_row_cls, scored=7
    )

    reading = evaluate_sc3(rows, pop_path, expected_g=10)

    assert reading.status == "MISS"
    assert "7/10" in reading.reason
    assert "0.80" in reading.reason
    assert reading.value == pytest.approx(1.0)
    assert reading.detail["coverage_n"] == 7
    assert reading.detail["coverage_expected"] == 10
    assert reading.detail["coverage"] == pytest.approx(0.7)
    assert reading.detail["coverage_floor"] == pytest.approx(0.80)


def test_sc3_eight_of_ten_meets_the_coverage_floor_at_or_above(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _sc3_row_cls
) -> None:
    rows, pop_path = _sc3_coverage_fixture(
        tmp_path, monkeypatch, _sc3_row_cls, scored=8
    )

    reading = evaluate_sc3(rows, pop_path, expected_g=10)

    assert reading.status == "PASS", reading.reason
    assert reading.reason == "usable rate 1.0000 >= floor 0.4700"
    assert reading.detail["coverage"] == pytest.approx(0.8)


def test_sc3_a_coverage_miss_joins_a_usable_rate_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _sc3_row_cls
) -> None:
    _set_vector_baseline_usable_floor(monkeypatch, 0.47)
    ids = [f"q{i}" for i in range(10)]
    pop_path = tmp_path / "diag_selection.json"
    _write_populations(pop_path, ids)
    rows = [
        _sc3_row_cls(question_id=qid, e_answer_usable=False if i < 7 else None)
        for i, qid in enumerate(ids)
    ]

    reading = evaluate_sc3(rows, pop_path, expected_g=10)

    assert reading.status == "MISS"
    assert "usable rate 0.0000 < floor 0.4700" in reading.reason
    assert "7/10" in reading.reason


def test_sc3_without_an_expected_population_skips_only_the_coverage_clause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _sc3_row_cls
) -> None:
    rows, pop_path = _sc3_coverage_fixture(
        tmp_path, monkeypatch, _sc3_row_cls, scored=7
    )

    reading = evaluate_sc3(rows, pop_path)

    assert reading.status == "PASS"
    assert reading.detail["coverage"] is None
    assert reading.detail["coverage_note"] == "coverage not assessed"


def test_sc3_an_empty_expected_population_is_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _sc3_row_cls
) -> None:
    rows, pop_path = _sc3_coverage_fixture(
        tmp_path, monkeypatch, _sc3_row_cls, scored=8
    )

    reading = evaluate_sc3(rows, pop_path, expected_g=0)

    assert reading.status == "MISS"
    assert "expected population is empty" in reading.reason


def test_sc3_counts_every_graph_off_error_class_over_g_not_only_d69(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-04: a non-D-69 graph-off error shrinks n too, so it is disclosed by class."""
    from dataclasses import dataclass as _dc

    from lancet_eval.diagnostic import ArmResult

    @_dc(frozen=True)
    class _Row:
        question_id: str
        arms: dict[str, ArmResult]
        question_type: str = "inference_query"
        e_answer_usable: bool | None = None

    def _off(outcome: str, error_class: str | None = None) -> dict[str, ArmResult]:
        return {
            "graph-off": ArmResult(
                arm="graph-off", outcome=outcome, error_class=error_class
            )  # type: ignore[arg-type]
        }

    _set_vector_baseline_usable_floor(monkeypatch, 0.10)
    ids = [f"q{i}" for i in range(6)]
    pop_path = tmp_path / "diag_selection.json"
    _write_populations(pop_path, ids)
    rows = [
        _Row("q0", _off("success"), e_answer_usable=True),
        _Row("q1", _off("error", "timeout")),
        _Row("q2", _off("error", "transport")),
        _Row("q3", _off("error", "citation_basis_mixed")),
        _Row("q4", _off("error", None)),
        _Row("q5", _off("error", "timeout")),
    ]

    reading = evaluate_sc3(rows, pop_path)

    assert reading.detail["excluded_by_class"] == {
        "timeout": 2,
        "transport": 1,
        "citation_basis_mixed": 1,
        "unclassified": 1,
    }
    assert reading.detail["excluded_generate_answer_failures"] == 1


def test_sc4_misses_on_coverage_even_when_presence_and_wilson_pass(
    tmp_path: Path,
) -> None:
    journal, selection, gold = _presence_journal(tmp_path, n=40, present=10)

    reading = evaluate_sc4(journal, selection, gold_questions=gold, expected_g=80)

    assert reading.status == "MISS"
    assert "40/80" in reading.reason
    assert "presence rate" not in reading.reason
    assert reading.detail["coverage_n"] == 40
    assert reading.detail["coverage_expected"] == 80
    assert reading.detail["coverage"] == pytest.approx(0.5)


def test_sc4_at_full_coverage_keeps_its_recorded_reason(tmp_path: Path) -> None:
    journal, selection, gold = _presence_journal(tmp_path, n=40, present=10)
    bare = evaluate_sc4(journal, selection, gold_questions=gold)

    reading = evaluate_sc4(journal, selection, gold_questions=gold, expected_g=40)

    assert reading.status == "PASS", reading.reason
    assert reading.reason == bare.reason
    assert reading.detail["coverage"] == pytest.approx(1.0)
    assert bare.detail["coverage"] is None
    assert bare.detail["coverage_note"] == "coverage not assessed"


def test_sc4_an_empty_expected_population_is_miss(tmp_path: Path) -> None:
    journal, selection, gold = _presence_journal(tmp_path, n=40, present=10)

    reading = evaluate_sc4(journal, selection, gold_questions=gold, expected_g=0)

    assert reading.status == "MISS"
    assert "expected population is empty" in reading.reason


def test_sc5_one_pair_with_a_composition_change_misses_on_thin_v_coverage(
    tmp_path: Path,
) -> None:
    journal, selection, gold = _composition_journal(tmp_path, n=1, boosted_for={0})

    thin = evaluate_sc5(
        journal, selection, gold_questions=gold, chunk_size=500, expected_v=4
    )
    full = evaluate_sc5(
        journal, selection, gold_questions=gold, chunk_size=500, expected_v=1
    )

    assert thin.status == "MISS"
    assert "1/4" in thin.reason
    assert thin.n == 1, "the headline n stays n_pairs(V)"
    assert thin.detail["coverage_n"] == 1
    assert thin.detail["coverage_expected"] == 4
    assert thin.detail["n_pairs"] == 1
    assert full.status == "PASS", full.reason
    assert full.detail["coverage"] == pytest.approx(1.0)


def test_sc5_coverage_counts_the_composition_population_not_unmeasured_pairs(
    tmp_path: Path,
) -> None:
    # Ten V pairs whose graph-on chunks all lack the flag: pairs(V) is 10, but the
    # composition population is 0, so there is nothing for the coverage clause to count.
    records = []
    for i in range(10):
        records.append(
            _arm_record(_qid(i), "graph-on", chunks=[_chunk(f"on-{i}:0", boosted=None)])
        )
        records.append(
            _arm_record(_qid(i), "graph-off", chunks=[_chunk(f"off-{i}:0")])
        )
    journal = tmp_path / "journal.jsonl"
    _write_journal(journal, records, corpus="multihop_rag")
    ids = [_qid(i) for i in range(10)]
    selection = _write_selection(tmp_path / "sel.json", g=ids, v=ids)

    reading = evaluate_sc5(
        journal,
        selection,
        gold_questions=_gold_map(10),
        chunk_size=500,
        expected_v=10,
    )

    assert reading.status == "MISS"
    assert reading.detail["coverage_n"] == 0
    assert reading.detail["n_pairs"] == 10


def test_sc5_an_empty_expected_population_is_miss(tmp_path: Path) -> None:
    journal, selection, gold = _composition_journal(tmp_path, n=1, boosted_for={0})

    reading = evaluate_sc5(
        journal, selection, gold_questions=gold, chunk_size=500, expected_v=0
    )

    assert reading.status == "MISS"
    assert "expected population is empty" in reading.reason


def test_sc5_without_an_expected_population_skips_only_the_coverage_clause(
    tmp_path: Path,
) -> None:
    journal, selection, gold = _composition_journal(tmp_path, n=1, boosted_for={0})

    reading = evaluate_sc5(journal, selection, gold_questions=gold, chunk_size=500)

    assert reading.status == "PASS"
    assert reading.detail["coverage"] is None
    assert reading.detail["coverage_note"] == "coverage not assessed"


def test_main_passes_sample_scoped_integer_denominators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-02/WR-04: the denominators are |sample & G| and |sample & V|, never the
    corpus-wide len(g_ids)/len(v_ids), and never None."""
    import lancet_eval.unpark_gates as module

    fixture = _main_fixture(tmp_path, monkeypatch)
    sample_ids = json.loads(fixture[3].read_text(encoding="utf-8"))["g_question_ids"]
    # G and V reach well beyond the sample (the real populations are corpus-wide).
    _write_selection(
        fixture[3],
        g=[*sample_ids, "outside-1", "outside-2", "outside-3"],
        v=[*sample_ids[:2], "outside-1"],
    )
    seen: dict[str, dict[str, Any]] = {}

    def _spy(name: str) -> None:
        real = getattr(module, name)

        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            seen[name] = kwargs
            return real(*args, **kwargs)

        monkeypatch.setattr(module, name, _wrapper)

    for name in ("evaluate_sc3", "evaluate_sc4", "evaluate_sc5"):
        _spy(name)

    _run_main("drive2", tmp_path, fixture)

    assert seen["evaluate_sc3"]["expected_g"] == len(sample_ids)
    assert seen["evaluate_sc4"]["expected_g"] == len(sample_ids)
    assert seen["evaluate_sc5"]["expected_v"] == 2
    for kwargs in seen.values():
        for key in ("expected_g", "expected_v"):
            if key in kwargs:
                assert type(kwargs[key]) is int


def test_main_passes_zero_for_a_population_the_selection_lacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lancet_eval.unpark_gates as module

    fixture = _main_fixture(tmp_path, monkeypatch)
    sample_ids = json.loads(fixture[3].read_text(encoding="utf-8"))["g_question_ids"]
    _write_selection(fixture[3], g=sample_ids)  # no v_question_ids
    seen: dict[str, Any] = {}
    real = module.evaluate_sc5

    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "evaluate_sc5", _wrapper)

    _run_main("drive2", tmp_path, fixture)

    assert seen["expected_v"] == 0
    assert type(seen["expected_v"]) is int
