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
from lancet_eval.corpus import GoldQuestion
from lancet_eval.journal import NodeFailed, NodeTiming, RunRecord
from lancet_eval.unpark_gates import (
    citation_rejection_rate,
    evaluate_sc1,
    evaluate_sc2,
    evaluate_sc3,
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
