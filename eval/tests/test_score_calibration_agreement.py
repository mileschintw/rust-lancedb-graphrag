"""Tests for calibration agreement metrics, states, and report integration."""

import json
import math
from pathlib import Path

from lancet_eval.agreement import (
    CALIBRATION_STATE_BELOW_TARGET,
    CALIBRATION_STATE_NONE,
    CALIBRATION_STATE_SATISFIED,
    KAPPA_STATE_COMPUTED,
    KAPPA_STATE_UNDEFINED_EXPECTED_AGREEMENT,
    SPEARMAN_STATE_COMPUTED,
    SPEARMAN_STATE_UNDEFINED_ZERO_VARIANCE,
)
from lancet_eval.client import RetrievalSnapshot, StructuredCitation
from lancet_eval.config import repo_root
from lancet_eval.corpus import load_sample_questions
from lancet_eval.gate import AGREEMENT_TARGET, CALIBRATION_SIZE
from lancet_eval.journal import Journal, RunRecord
from lancet_eval.judge import (
    JudgeCache,
    JudgeCacheEntry,
    JudgeVerdict,
    cache_key,
    truncate_evidence,
)
from lancet_eval.report import CorpusReport, RunMetadata, render_json, render_markdown
from lancet_eval.score import score_run


def _get_valid_doc_id() -> str:
    try:
        from lancet_eval.seed import load_document_map

        doc_map = load_document_map("multihop_rag")
        return next(iter(doc_map.entries.keys()))
    except Exception:
        return "0abbe020-d26d-41e6-8d5f-f7867a3608db"


def _create_synthetic_run(
    tmp_path: Path,
    n_questions: int = 12,
    judge_verdicts: list[tuple[int, int]] | None = None,
) -> tuple[list[RunRecord], list[str]]:
    """Create a synthetic run directory with journal and judge cache."""
    q_pool = load_sample_questions("multihop_rag")
    doc_id = _get_valid_doc_id()
    journal = Journal(tmp_path / "journal.jsonl")
    cache = JudgeCache(tmp_path / "judge_cache.json")

    records = []
    keys = []
    for i in range(n_questions):
        qid = q_pool[i % len(q_pool)].question_id
        # Use arm graph-on for judged items
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer text for question {i}",
            index_generation="gen-test-1",
            snapshot=RetrievalSnapshot(
                index_generation="gen-test-1",
                retrieved_chunks=[
                    StructuredCitation(
                        chunk_id="c1",
                        document_id=doc_id,
                        excerpt="Evidence excerpt",
                        rank=1,
                    )
                ],
            ),
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Evidence excerpt",
                    rank=1,
                )
            ],
        )
        journal.append(rec)
        records.append(rec)

        q_obj = next(q for q in q_pool if q.question_id == qid)
        ev = truncate_evidence(rec.structured_citations)
        ck = cache_key(
            prompt_version="v1",
            judge_model="meta-llama/llama-3.3-70b-instruct",
            question=q_obj.question,
            answer=rec.answer,
            post_truncation_evidence=ev,
        )
        keys.append(ck)

        if judge_verdicts and i < len(judge_verdicts):
            gv, fv = judge_verdicts[i]
            cache.entries[ck] = JudgeCacheEntry(
                cache_key=ck,
                prompt_version="v1",
                judge_model="meta-llama/llama-3.3-70b-instruct",
                question=q_obj.question,
                answer=rec.answer,
                evidence=ev,
                verdict=JudgeVerdict(
                    groundedness=gv,
                    faithfulness=fv,
                    unsupported_claims=[],
                    rationale="ok",
                ),
                error=None,
            )

    cache.save()
    return records, keys


def _write_calibration_worksheet(
    path: Path,
    keys: list[str],
    human_ratings: list[tuple[int, int]],
    qids: list[str] | None = None,
) -> None:
    """Write synthetic calibration worksheet with header and human ratings."""
    with open(path, "w", encoding="utf-8") as f:
        header = {"type": "header", "judge_prompt_version": "v1"}
        f.write(json.dumps(header) + "\n")
        for i, (ck, (hg, hf)) in enumerate(
            zip(keys, human_ratings, strict=False)
        ):
            row = {
                "question_id": qids[i] if qids else f"q-{i}",
                "cache_key": ck,
                "human_groundedness": hg,
                "human_faithfulness": hf,
                "notes": "",
            }
            f.write(json.dumps(row) + "\n")


def test_gate_constants_parity() -> None:
    """Proves target and calibration size match committed gate.py constants."""
    assert AGREEMENT_TARGET == 0.70
    assert CALIBRATION_SIZE == 12


def test_disjoint_state_bands() -> None:
    """Proves the three state code sets occupy disjoint numeric bands."""
    overall_states = {
        CALIBRATION_STATE_NONE,
        CALIBRATION_STATE_BELOW_TARGET,
        CALIBRATION_STATE_SATISFIED,
    }
    kappa_states = {
        KAPPA_STATE_COMPUTED,
        KAPPA_STATE_UNDEFINED_EXPECTED_AGREEMENT,
    }
    spearman_states = {
        SPEARMAN_STATE_COMPUTED,
        SPEARMAN_STATE_UNDEFINED_ZERO_VARIANCE,
    }

    # Verify bands
    for s in overall_states:
        assert 0.0 <= s <= 2.0
    for s in kappa_states:
        assert 10.0 <= s <= 11.0
    for s in spearman_states:
        assert 20.0 <= s <= 21.0

    # Verify disjointness
    assert overall_states.isdisjoint(kappa_states)
    assert overall_states.isdisjoint(spearman_states)
    assert kappa_states.isdisjoint(spearman_states)

    # Verify degenerate states specifically
    assert KAPPA_STATE_UNDEFINED_EXPECTED_AGREEMENT == 11.0
    assert SPEARMAN_STATE_UNDEFINED_ZERO_VARIANCE == 21.0


def test_no_calibration_state_and_completed_n_zero(tmp_path: Path) -> None:
    """Proves uncalibrated run sets state 0.0, completed 0, and notes."""
    _create_synthetic_run(
        tmp_path,
        n_questions=3,
        judge_verdicts=[(5, 5), (4, 4), (3, 3)],
    )

    report = score_run(run_dir=tmp_path, no_judge=False, api_key="dummy")
    assert report.metadata.calibration_completed_n == 0
    expected_note = (
        "No judge-versus-human calibration was performed; "
        "judged dimensions are uncalibrated."
    )
    assert expected_note in report.metadata.notes

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    f_dim = next(d for d in report.dimensions if d.name == "answer_faithfulness")

    assert g_dim.status == "ok"
    assert g_dim.detail["calibration_state"] == CALIBRATION_STATE_NONE
    assert "calibration_kappa" not in g_dim.detail
    assert "calibration_spearman" not in g_dim.detail

    assert f_dim.status == "ok"
    assert f_dim.detail["calibration_state"] == CALIBRATION_STATE_NONE


def test_calibration_exact_target_match_satisfied(tmp_path: Path) -> None:
    """Proves a statistic exactly equal to the 0.70 target satisfies it."""
    verdicts = [
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (3, 3),
        (4, 4),
    ]
    human = [
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (3, 3),
        (4, 4),
    ]

    records, keys = _create_synthetic_run(
        tmp_path, n_questions=12, judge_verdicts=verdicts
    )
    ws_path = tmp_path / "calibration.jsonl"
    _write_calibration_worksheet(ws_path, keys, human, [r.question_id for r in records])

    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        calibration_file=ws_path,
        api_key="dummy",
    )

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    f_dim = next(d for d in report.dimensions if d.name == "answer_faithfulness")

    assert g_dim.detail["calibration_state"] == CALIBRATION_STATE_SATISFIED
    assert f_dim.detail["calibration_state"] == CALIBRATION_STATE_SATISFIED
    assert report.metadata.notes == ""  # No shortfall sentence
    assert report.metadata.calibration_completed_n == 12


def test_calibration_below_target_notes_and_state(tmp_path: Path) -> None:
    """Proves below-target ratings set state 1.0 and name stat in notes."""
    # Systematic disagreement: judge says 5, human says 1
    verdicts = [(5, 5)] * 6 + [(1, 1)] * 6
    human = [(1, 1)] * 6 + [(5, 5)] * 6  # opposite

    records, keys = _create_synthetic_run(
        tmp_path, n_questions=12, judge_verdicts=verdicts
    )
    ws_path = tmp_path / "calibration.jsonl"
    _write_calibration_worksheet(ws_path, keys, human, [r.question_id for r in records])

    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        calibration_file=ws_path,
        api_key="dummy",
    )

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    f_dim = next(d for d in report.dimensions if d.name == "answer_faithfulness")

    assert g_dim.detail["calibration_state"] == CALIBRATION_STATE_BELOW_TARGET
    assert f_dim.detail["calibration_state"] == CALIBRATION_STATE_BELOW_TARGET

    notes = report.metadata.notes
    assert "Calibration agreement fell below target" in notes
    assert "kappa" in notes
    assert "spearman" in notes
    k_val = g_dim.detail["calibration_kappa"]
    assert str(k_val)[:4] in notes or f"{k_val:.4f}" in notes


def test_distinguishable_states_without_parsing_prose(tmp_path: Path) -> None:
    """Proves 0.0, 1.0, 2.0 states are distinguishable purely through numeric codes."""
    # State 0.0: No calibration
    p0 = tmp_path / "run0"
    p0.mkdir()
    _create_synthetic_run(
        p0, n_questions=4, judge_verdicts=[(1, 1), (2, 2), (3, 3), (4, 4)]
    )
    r0 = score_run(run_dir=p0, no_judge=False, api_key="dummy")
    g0 = next(d for d in r0.dimensions if d.name == "answer_groundedness")
    assert g0.detail["calibration_state"] == 0.0

    # State 1.0: Below target
    p1 = tmp_path / "run1"
    p1.mkdir()
    v1 = [(5, 5)] * 6 + [(1, 1)] * 6
    h1 = [(1, 1)] * 6 + [(5, 5)] * 6
    recs1, keys1 = _create_synthetic_run(p1, n_questions=12, judge_verdicts=v1)
    ws1 = p1 / "calibration.jsonl"
    _write_calibration_worksheet(ws1, keys1, h1, [r.question_id for r in recs1])
    r1 = score_run(run_dir=p1, no_judge=False, calibration_file=ws1, api_key="dummy")
    g1 = next(d for d in r1.dimensions if d.name == "answer_groundedness")
    assert g1.detail["calibration_state"] == 1.0

    # State 2.0: Satisfied
    p2 = tmp_path / "run2"
    p2.mkdir()
    v2 = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)] * 2 + [(3, 3), (4, 4)]
    h2 = list(v2)
    recs2, keys2 = _create_synthetic_run(p2, n_questions=12, judge_verdicts=v2)
    ws2 = p2 / "calibration.jsonl"
    _write_calibration_worksheet(ws2, keys2, h2, [r.question_id for r in recs2])
    r2 = score_run(run_dir=p2, no_judge=False, calibration_file=ws2, api_key="dummy")
    g2 = next(d for d in r2.dimensions if d.name == "answer_groundedness")
    assert g2.detail["calibration_state"] == 2.0

    # All three numeric codes differ and notes differ
    assert {
        g0.detail["calibration_state"],
        g1.detail["calibration_state"],
        g2.detail["calibration_state"],
    } == {0.0, 1.0, 2.0}
    assert r0.metadata.notes != r1.metadata.notes
    assert r1.metadata.notes != r2.metadata.notes


def test_calibrated_run_dimension_result_reason_none(tmp_path: Path) -> None:
    """Proves calibrated run produces DimensionResults with reason=None, status=ok."""
    verdicts = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)] * 2 + [(3, 3), (4, 4)]
    records, keys = _create_synthetic_run(
        tmp_path, n_questions=12, judge_verdicts=verdicts
    )
    ws_path = tmp_path / "calibration.jsonl"
    _write_calibration_worksheet(
        ws_path, keys, list(verdicts), [r.question_id for r in records]
    )

    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        calibration_file=ws_path,
        api_key="dummy",
    )

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    f_dim = next(d for d in report.dimensions if d.name == "answer_faithfulness")

    assert g_dim.status == "ok"
    assert g_dim.reason is None
    assert f_dim.status == "ok"
    assert f_dim.reason is None


def test_degenerate_statistic_omits_detail_key_companion_state(tmp_path: Path) -> None:
    """Proves degenerate stat omits detail key and sets companion state float."""
    # When rater uses identical ratings throughout (all 5s), expected agreement is 1
    verdicts = [(5, 5)] * 12
    human = [(5, 5)] * 12

    records, keys = _create_synthetic_run(
        tmp_path, n_questions=12, judge_verdicts=verdicts
    )
    ws_path = tmp_path / "calibration.jsonl"
    _write_calibration_worksheet(ws_path, keys, human, [r.question_id for r in records])

    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        calibration_file=ws_path,
        api_key="dummy",
    )

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")

    assert "calibration_kappa" not in g_dim.detail
    assert "calibration_spearman" not in g_dim.detail
    assert "calibration_kappa_ci_lower" not in g_dim.detail
    assert "calibration_spearman_ci_lower" not in g_dim.detail

    assert (
        g_dim.detail["calibration_kappa_state"]
        == KAPPA_STATE_UNDEFINED_EXPECTED_AGREEMENT
    )
    assert (
        g_dim.detail["calibration_spearman_state"]
        == SPEARMAN_STATE_UNDEFINED_ZERO_VARIANCE
    )

    # Assert no NaN in any detail value
    for k, v in g_dim.detail.items():
        assert not math.isnan(v), f"Key {k} contains NaN"


def test_per_dimension_not_pooled(tmp_path: Path) -> None:
    """Proves kappa is computed independently per dimension, not pooled or copied."""
    # Groundedness agrees strongly (identical)
    # Faithfulness disagrees completely
    verdicts = [
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (3, 3),
        (4, 4),
    ]
    human = [
        (1, 5),
        (2, 4),
        (3, 3),
        (4, 2),
        (5, 1),
        (1, 5),
        (2, 4),
        (3, 3),
        (4, 2),
        (5, 1),
        (3, 3),
        (4, 2),
    ]

    records, keys = _create_synthetic_run(
        tmp_path, n_questions=12, judge_verdicts=verdicts
    )
    ws_path = tmp_path / "calibration.jsonl"
    _write_calibration_worksheet(ws_path, keys, human, [r.question_id for r in records])

    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        calibration_file=ws_path,
        api_key="dummy",
    )

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    f_dim = next(d for d in report.dimensions if d.name == "answer_faithfulness")

    assert g_dim.detail["calibration_kappa"] != f_dim.detail["calibration_kappa"]
    assert g_dim.detail["calibration_kappa"] == 1.0
    assert f_dim.detail["calibration_kappa"] < 0.0

    assert g_dim.detail["calibration_pairs_n"] == 12.0
    assert f_dim.detail["calibration_pairs_n"] == 12.0


def test_bootstrap_ci_brackets_point_estimate_and_reproducible(tmp_path: Path) -> None:
    """Proves bootstrap CI brackets point estimate and is reproducible under seed."""
    verdicts = [
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (1, 2),
        (2, 3),
        (3, 4),
        (4, 5),
        (5, 4),
        (3, 2),
        (4, 3),
    ]
    human = [
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (3, 3),
        (4, 4),
    ]

    records, keys = _create_synthetic_run(
        tmp_path, n_questions=12, judge_verdicts=verdicts
    )
    ws_path = tmp_path / "calibration.jsonl"
    _write_calibration_worksheet(ws_path, keys, human, [r.question_id for r in records])

    r1 = score_run(
        run_dir=tmp_path, no_judge=False, calibration_file=ws_path, api_key="dummy"
    )
    r2 = score_run(
        run_dir=tmp_path, no_judge=False, calibration_file=ws_path, api_key="dummy"
    )

    g1 = next(d for d in r1.dimensions if d.name == "answer_groundedness")
    g2 = next(d for d in r2.dimensions if d.name == "answer_groundedness")

    # Brackets point estimate
    k_pt = g1.detail["calibration_kappa"]
    k_lo = g1.detail["calibration_kappa_ci_lower"]
    k_hi = g1.detail["calibration_kappa_ci_upper"]
    assert k_lo <= k_pt + 1e-9
    assert k_hi >= k_pt - 1e-9

    s_pt = g1.detail["calibration_spearman"]
    s_lo = g1.detail["calibration_spearman_ci_lower"]
    s_hi = g1.detail["calibration_spearman_ci_upper"]
    assert s_lo <= s_pt + 1e-9
    assert s_hi >= s_pt - 1e-9

    # Reproducible
    assert (
        g1.detail["calibration_kappa_ci_lower"]
        == g2.detail["calibration_kappa_ci_lower"]
    )
    assert (
        g1.detail["calibration_kappa_ci_upper"]
        == g2.detail["calibration_kappa_ci_upper"]
    )
    assert (
        g1.detail["calibration_spearman_ci_lower"]
        == g2.detail["calibration_spearman_ci_lower"]
    )
    assert (
        g1.detail["calibration_spearman_ci_upper"]
        == g2.detail["calibration_spearman_ci_upper"]
    )


def test_pass_fail_on_point_estimate_alone(tmp_path: Path) -> None:
    """Proves decision rule is point estimate alone: CI straddling target satisfies."""
    # Ratings where point estimate >= 0.70 but bootstrap CI lower < 0.70
    # 10 pairs agree, 2 pairs disagree (2, 4) vs (4, 2)
    v_seq = [1, 2, 3, 4, 5, 1, 2, 3, 4, 5, 2, 4]
    h_seq = [1, 2, 3, 4, 5, 1, 2, 3, 4, 5, 4, 2]
    verdicts = [(x, x) for x in v_seq]
    human = [(x, x) for x in h_seq]

    records, keys = _create_synthetic_run(
        tmp_path, n_questions=12, judge_verdicts=verdicts
    )
    ws_path = tmp_path / "calibration.jsonl"
    _write_calibration_worksheet(ws_path, keys, human, [r.question_id for r in records])

    report = score_run(
        run_dir=tmp_path, no_judge=False, calibration_file=ws_path, api_key="dummy"
    )
    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")

    # Point estimate is >= 0.70
    assert g_dim.detail["calibration_kappa"] >= AGREEMENT_TARGET
    assert g_dim.detail["calibration_spearman"] >= AGREEMENT_TARGET
    # Lower CI straddles (falls below) target
    assert g_dim.detail["calibration_kappa_ci_lower"] < AGREEMENT_TARGET
    assert g_dim.detail["calibration_spearman_ci_lower"] < AGREEMENT_TARGET
    # Status is satisfied (2.0) even though lower CI is below target
    assert g_dim.detail["calibration_state"] == CALIBRATION_STATE_SATISFIED


def test_excluded_row_accounting_when_cache_verdict_missing(tmp_path: Path) -> None:
    """Proves worksheet row whose key has no verdict is counted as excluded."""
    verdicts = [
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (3, 3),
        (4, 4),
    ]
    human = list(verdicts)

    records, keys = _create_synthetic_run(
        tmp_path, n_questions=12, judge_verdicts=verdicts
    )

    # Modify one key in worksheet so it has no verdict in judge_cache
    keys_with_missing = list(keys)
    keys_with_missing[0] = "non_existent_cache_key_xyz"

    ws_path = tmp_path / "calibration.jsonl"
    _write_calibration_worksheet(
        ws_path, keys_with_missing, human, [r.question_id for r in records]
    )

    report = score_run(
        run_dir=tmp_path, no_judge=False, calibration_file=ws_path, api_key="dummy"
    )
    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")

    assert g_dim.detail["calibration_pairs_n"] == 11.0
    assert g_dim.detail["calibration_excluded_n"] == 1.0
    assert report.metadata.calibration_completed_n == 12


def test_run_metadata_declares_calibration_completed_n_field() -> None:
    """Proves RunMetadata explicitly declares calibration_completed_n."""
    assert "calibration_completed_n" in RunMetadata.model_fields
    field = RunMetadata.model_fields["calibration_completed_n"]
    assert field.annotation is int
    assert field.default == 0


def test_rendered_report_metadata_table_and_schema_validation(tmp_path: Path) -> None:
    """Proves report contains Completed Calibration Dual Scores and valid schema."""
    verdicts = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)] * 2 + [(3, 3), (4, 4)]
    records, keys = _create_synthetic_run(
        tmp_path, n_questions=12, judge_verdicts=verdicts
    )
    ws_path = tmp_path / "calibration.jsonl"
    _write_calibration_worksheet(
        ws_path, keys, list(verdicts), [r.question_id for r in records]
    )

    report = score_run(
        run_dir=tmp_path, no_judge=False, calibration_file=ws_path, api_key="dummy"
    )

    # Render markdown and verify table row
    md = render_markdown(report)
    assert "| **Completed Calibration Dual Scores** | `12` |" in md

    # Validate against JSON schema
    schema_path = repo_root() / "eval" / "report.schema.json"
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    json_str = render_json(report)
    validated_report = CorpusReport.model_validate_json(json_str)
    assert validated_report.metadata.calibration_completed_n == 12

    # Verify field conforms to schema definition
    meta_props = schema["$defs"]["RunMetadata"]["properties"]
    assert "calibration_completed_n" in meta_props
    assert meta_props["calibration_completed_n"]["type"] == "integer"
