"""Tests for the 06.3.5 calibration emit (D-113, D-118, D-120; AI-SPEC 5).

The emit draws a seeded, arm-stratified, blinded 20-item slice from a finished judge
stage, writes the owner-facing worksheet into the run directory and the key and salt
outside it. The fixtures reuse the judge-stage test builders and run the real stage with
a fake `judge_once`, so no test makes a network call. Keys are written under a tmp
`keys_root`, never under the real `data/calibration-keys/`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from test_judge_stage import (
    API_KEY,
    ARMS,
    FORBIDDEN,
    HELDOUT,
    _gold,
    build_run,
    g_ids,
    install_fake,
    make_record,
    real_split,
    standard_records,
)
from typer.testing import CliRunner

from lancet_eval import calibration, gitcheck, thresholds
from lancet_eval.calibration import (
    MECHANICS_LINE,
    CalibrationError,
    CalibrationHeader,
    CalibrationKeyRow,
    CalibrationWorksheetRow,
    draw_slice,
    emit_worksheet,
    key_digest,
    read_key_file,
    rubric_block,
)
from lancet_eval.cli import app
from lancet_eval.config import repo_root
from lancet_eval.judge import (
    JUDGE_SYSTEM_V1,
    JudgeCache,
    JudgeCacheEntry,
    cache_key,
)
from lancet_eval.judge_stage import run_judge_stage

MODEL = "meta-llama/llama-3.3-70b-instruct"
SHA = "b" * 40
RUN_NAME = "run"


@pytest.fixture
def emit_env(
    monkeypatch: pytest.MonkeyPatch, preregistered_clean_tree: str
) -> None:
    """A key for the fake judge, the D-73 gates passing and the committed floor text."""
    monkeypatch.setenv("OPENROUTER_API_KEY", API_KEY)
    install_fake(monkeypatch)
    text = Path(thresholds.__file__).read_text(encoding="utf-8")
    monkeypatch.setattr(
        gitcheck, "show_blob", lambda sha, path, *, repo=None: text
    )


def closed_run(
    tmp_path: Path,
    *,
    records: list[Any] | None = None,
    name: str = RUN_NAME,
) -> Path:
    """A closed four-arm run (30 questions: 12 comparison, 12 inference, 6 temporal)
    whose judge stage has completed."""
    recs = records if records is not None else standard_records(g_ids(12, 12, 6))
    run = build_run(tmp_path, recs, name=name)
    result = run_judge_stage(run_dir=run, stage_cap=5.0)
    assert result.stop_reason is None
    return run


def read_worksheet(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[0]), [json.loads(line) for line in lines[1:]]


def emit(run: Path, tmp_path: Path, **kwargs: Any) -> calibration.EmitResult:
    return emit_worksheet(run, keys_root=tmp_path / "keys", **kwargs)


def key_rows(result: calibration.EmitResult) -> list[CalibrationKeyRow]:
    return read_key_file(result.key_path)


def draw(records: list[Any], seed: int = 42) -> list[calibration.DrawnItem]:
    return draw_slice(
        records,
        real_split(),
        ARMS,
        _gold(HELDOUT),
        seed=seed,
        prompt_version="v1",
        judge_model=MODEL,
    )


# --- the slice ---------------------------------------------------------------------


def test_the_worksheet_holds_20_blinded_rows_s01_to_s20(
    tmp_path: Path, emit_env: None
) -> None:
    run = closed_run(tmp_path)
    result = emit(run, tmp_path)

    header, rows = read_worksheet(result.worksheet_path)
    assert result.worksheet_path == run / "calibration-worksheet.jsonl"
    assert result.n_items == 20
    assert [r["slice_id"] for r in rows] == [f"S{i:02d}" for i in range(1, 21)]
    keys = key_rows(result)
    assert [k.slice_id for k in keys] == [f"S{i:02d}" for i in range(1, 21)]
    assert {a: sum(k.arm == a for k in keys) for a in ARMS} == dict.fromkeys(ARMS, 5)
    types = {k.question_type for k in keys}
    by_type = {t: sum(k.question_type == t for k in keys) for t in types}
    assert by_type == {
        "comparison_query": 8,
        "inference_query": 8,
        "temporal_query": 4,
    }
    assert len({k.question_id for k in keys}) == 20
    assert len({k.cache_key for k in keys}) == 20
    assert header["type"] == "header"


def test_the_worksheet_rows_carry_exactly_the_judge_inputs(
    tmp_path: Path, emit_env: None
) -> None:
    run = closed_run(tmp_path)
    result = emit(run, tmp_path)
    _, rows = read_worksheet(result.worksheet_path)
    cache = JudgeCache(run / "judge_cache.json")
    for row, key in zip(rows, key_rows(result), strict=True):
        assert set(row) == {
            "slice_id",
            "question",
            "answer",
            "evidence",
            "human_groundedness",
            "human_faithfulness",
            "notes",
        }
        assert row["human_groundedness"] is None
        assert row["human_faithfulness"] is None
        assert row["notes"] == ""
        # the row text is the judge's own input: same key, same cached entry
        recomputed = cache_key(
            prompt_version="v1",
            judge_model=MODEL,
            question=row["question"],
            answer=row["answer"],
            post_truncation_evidence=row["evidence"],
        )
        assert recomputed == key.cache_key
        assert cache.get(key.cache_key) is not None
        assert row["question"] == _gold(HELDOUT)[key.question_id].question


def test_no_row_carries_an_arm_a_verdict_a_cache_key_or_a_question_id(
    tmp_path: Path, emit_env: None
) -> None:
    run = closed_run(tmp_path)
    result = emit(run, tmp_path)
    text = result.worksheet_path.read_text(encoding="utf-8")
    _, rows = read_worksheet(result.worksheet_path)
    for key in key_rows(result):
        assert key.cache_key not in text
        assert key.question_id not in text
    for row in rows:
        for banned in ("arm", "verdict", "cache_key", "question_id", "question_type"):
            assert banned not in row


def test_two_emits_over_the_same_closed_run_are_identical(
    tmp_path: Path, emit_env: None
) -> None:
    run_a = closed_run(tmp_path / "a")
    shutil.copytree(run_a, tmp_path / "b" / RUN_NAME)
    run_b = tmp_path / "b" / RUN_NAME
    res_a = emit_worksheet(run_a, keys_root=tmp_path / "keys-a")
    res_b = emit_worksheet(run_b, keys_root=tmp_path / "keys-b")
    head_a, rows_a = read_worksheet(res_a.worksheet_path)
    head_b, rows_b = read_worksheet(res_b.worksheet_path)
    assert rows_a == rows_b
    assert key_rows(res_a) == key_rows(res_b)
    # the salt is random, so the digest differs; nothing else in the header does
    head_a.pop("key_sha256")
    head_b.pop("key_sha256")
    assert head_a == head_b
    assert res_a.key_sha256 != res_b.key_sha256


def test_a_cache_full_of_errors_draws_the_same_20_items(
    tmp_path: Path, emit_env: None
) -> None:
    run_a = closed_run(tmp_path / "a")
    shutil.copytree(run_a, tmp_path / "b" / RUN_NAME)
    run_b = tmp_path / "b" / RUN_NAME
    cache = JudgeCache(run_b / "judge_cache.json")
    for key, entry in list(cache.entries.items()):
        cache.entries[key] = JudgeCacheEntry(
            cache_key=key,
            prompt_version=entry.prompt_version,
            judge_model=entry.judge_model,
            question=entry.question,
            answer=entry.answer,
            evidence=entry.evidence,
            error="every call failed",
        )
    cache.save()
    res_a = emit_worksheet(run_a, keys_root=tmp_path / "keys-a")
    res_b = emit_worksheet(run_b, keys_root=tmp_path / "keys-b")
    assert read_worksheet(res_a.worksheet_path)[1] == read_worksheet(
        res_b.worksheet_path
    )[1]
    assert key_rows(res_a) == key_rows(res_b)


def test_the_draw_is_a_pure_function_of_records_and_seed() -> None:
    records = standard_records(g_ids(12, 12, 6))
    first = draw(records)
    assert first == draw(list(reversed(records)))
    assert len(first) == 20
    assert [i.slice_id for i in first] == [f"S{n:02d}" for n in range(1, 21)]
    assert [i.question_id for i in first] != [i.question_id for i in draw(records, 7)]


def test_the_pool_is_p4_records_that_are_judgeable_under_the_06_3_5_policy() -> None:
    qids = g_ids(12, 12, 6)
    null_id = real_split().heldout_null_ids[0]
    out_of_p4 = qids[0]  # hybrid errored: no question of it is in P4
    abstained = qids[1]  # dense-only abstained: in P4, but not judgeable for that arm
    uncited = qids[2]
    provenance = qids[3]
    records = standard_records(
        qids,
        **{
            f"hybrid|{out_of_p4}": make_record("hybrid", out_of_p4, error=True),
            f"dense-only|{abstained}": make_record(
                "dense-only", abstained, no_evidence=True
            ),
            f"bm25-only|{uncited}": make_record("bm25-only", uncited, uncited=True),
            f"hybrid|{provenance}": make_record(
                "hybrid", provenance, drop_ablation=True
            ),
        },
    )
    records += [make_record(arm, null_id) for arm in ARMS]
    for seed in range(25):
        drawn = {(i.arm, i.question_id) for i in draw(records, seed)}
        assert not {q for _, q in drawn} & {out_of_p4, null_id}
        assert ("dense-only", abstained) not in drawn
        assert ("bm25-only", uncited) not in drawn
        # a provenance failure leaves P4, so no arm draws that question
        assert provenance not in {q for _, q in drawn}


def test_an_empty_cell_is_filled_comparison_then_inference_then_temporal() -> None:
    qids = g_ids(12, 12, 6)
    gold = _gold(HELDOUT)
    temporal = [q for q in qids if gold[q].question_type == "temporal_query"]
    records = standard_records(
        qids,
        **{
            f"dense-only|{q}": make_record("dense-only", q, no_evidence=True)
            for q in temporal
        },
    )
    drawn = draw(records)
    dense = [i for i in drawn if i.arm == "dense-only"]
    assert len(dense) == 5
    assert sorted(i.question_type for i in dense) == [
        "comparison_query",
        "comparison_query",
        "comparison_query",
        "inference_query",
        "inference_query",
    ]
    noted = [i for i in dense if i.notes]
    assert len(noted) == 1
    assert "temporal" in noted[0].notes and "comparison" in noted[0].notes
    assert all(not i.notes for i in drawn if i.arm != "dense-only")


def test_an_empty_comparison_cell_falls_back_to_inference() -> None:
    qids = g_ids(12, 12, 6)
    gold = _gold(HELDOUT)
    comparison = [q for q in qids if gold[q].question_type == "comparison_query"]
    records = standard_records(
        qids,
        **{
            f"dense-only|{q}": make_record("dense-only", q, no_evidence=True)
            for q in comparison
        },
    )
    dense = [i for i in draw(records) if i.arm == "dense-only"]
    assert sorted(i.question_type for i in dense) == [
        "inference_query",
        "inference_query",
        "inference_query",
        "inference_query",
        "temporal_query",
    ]
    noted = [i for i in dense if i.notes]
    assert len(noted) == 2
    assert all("comparison" in i.notes and "inference" in i.notes for i in noted)


def test_an_arm_with_four_eligible_records_refuses() -> None:
    records = standard_records(g_ids(2, 1, 1))  # four questions per arm
    with pytest.raises(CalibrationError, match="fewer than 5"):
        draw(records)


def test_an_arm_whose_pool_the_distinctness_rule_exhausts_refuses() -> None:
    records = standard_records(g_ids(2, 2, 1))  # five questions: one arm takes all
    with pytest.raises(CalibrationError, match="no eligible"):
        draw(records)


def test_arms_sharing_a_cache_key_yield_at_most_one_row_and_both_are_listed() -> None:
    qids = g_ids(12, 12, 6)
    shared: dict[str, Any] = {}
    for q in qids:
        text = f"Shared answer for {q}. Answer: Yes"
        shared[f"hybrid|{q}"] = make_record("hybrid", q, answer=text)
        shared[f"hybrid+graph|{q}"] = make_record("hybrid+graph", q, answer=text)
    drawn = draw(standard_records(qids, **shared))
    assert len({i.cache_key for i in drawn}) == len(drawn) == 20
    for item in drawn:
        if item.arm in ("hybrid", "hybrid+graph"):
            assert item.shared_arms == ("hybrid", "hybrid+graph")
        else:
            assert item.shared_arms == (item.arm,)


def test_the_key_file_names_every_arm_that_shares_the_key(
    tmp_path: Path, emit_env: None
) -> None:
    qids = g_ids(12, 12, 6)
    shared: dict[str, Any] = {}
    for q in qids:
        text = f"Shared answer for {q}. Answer: Yes"
        shared[f"hybrid|{q}"] = make_record("hybrid", q, answer=text)
        shared[f"hybrid+graph|{q}"] = make_record("hybrid+graph", q, answer=text)
    run = closed_run(tmp_path, records=standard_records(qids, **shared))
    keys = key_rows(emit(run, tmp_path))
    sharing = [k for k in keys if k.arm in ("hybrid", "hybrid+graph")]
    assert sharing
    assert all(k.shared_arms == ["hybrid", "hybrid+graph"] for k in sharing)


# --- the worksheet and key models ----------------------------------------------------


@pytest.mark.parametrize("extra", ["arm", "cache_key", "question_id", "verdict"])
def test_a_worksheet_row_rejects_an_arm_a_key_or_an_id(extra: str) -> None:
    base = {"slice_id": "S01", "question": "q", "answer": "a", "evidence": "e"}
    CalibrationWorksheetRow.model_validate(base)
    with pytest.raises(ValidationError):
        CalibrationWorksheetRow.model_validate({**base, extra: "x"})


@pytest.mark.parametrize("score", [0, 6])
def test_a_worksheet_row_rejects_a_score_outside_1_to_5(score: int) -> None:
    base = {"slice_id": "S01", "question": "q", "answer": "a", "evidence": "e"}
    with pytest.raises(ValidationError):
        CalibrationWorksheetRow.model_validate({**base, "human_groundedness": score})
    with pytest.raises(ValidationError):
        CalibrationWorksheetRow.model_validate({**base, "human_faithfulness": score})


def test_a_worksheet_row_rejects_a_malformed_slice_id() -> None:
    with pytest.raises(ValidationError):
        CalibrationWorksheetRow(slice_id="s1", question="q", answer="a", evidence="e")


def test_a_key_row_needs_a_registry_arm_and_a_hex_key() -> None:
    good = {
        "slice_id": "S01",
        "arm": "hybrid",
        "question_id": "q",
        "question_type": "comparison_query",
        "cache_key": "0" * 64,
    }
    row = CalibrationKeyRow.model_validate(good)
    assert row.notes == "" and row.shared_arms == []
    with pytest.raises(ValidationError):
        CalibrationKeyRow.model_validate({**good, "arm": "graph-sideways"})
    with pytest.raises(ValidationError):
        CalibrationKeyRow.model_validate({**good, "cache_key": "xyz"})


def test_the_header_rejects_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        CalibrationHeader.model_validate({"type": "header", "arm": "hybrid"})


# --- the header ----------------------------------------------------------------------


def test_the_rubric_block_is_sliced_verbatim_from_the_judge_prompt() -> None:
    block = rubric_block()
    assert block.startswith("Your job is to grade the answer strictly")
    assert block.endswith("or answers from model priors.")
    assert block in JUDGE_SYSTEM_V1
    assert "Output Format" not in block
    assert "You are an evaluation judge" not in block
    assert "Groundedness (1-5)" in block and "Faithfulness (1-5)" in block
    expected = JUDGE_SYSTEM_V1.split("Your job is to grade", 1)[1]
    expected = "Your job is to grade" + expected.split("\nOutput Format:", 1)[0]
    assert block == expected.rstrip()


def test_the_header_carries_provenance_floor_digest_rubric_and_mechanics(
    tmp_path: Path, emit_env: None
) -> None:
    run = closed_run(tmp_path)
    result = emit(run, tmp_path)
    header, _ = read_worksheet(result.worksheet_path)
    assert set(header) == {
        "type",
        "corpus",
        "judge_prompt_version",
        "judge_model",
        "seed",
        "emitted_at_sha",
        "d114_floor",
        "key_sha256",
        "rubric",
        "mechanics",
    }
    assert header["corpus"] == HELDOUT
    assert header["judge_prompt_version"] == "v1"
    assert header["judge_model"] == MODEL
    assert header["seed"] == thresholds.CALIBRATION_DRAW_SEED == 42
    assert header["emitted_at_sha"] == SHA == result.emitted_at_sha
    assert header["d114_floor"] == 0.70 == thresholds.JUDGE_QWK_TRUST_FLOOR
    assert header["rubric"] == rubric_block()
    assert header["mechanics"] == MECHANICS_LINE
    assert "1–5" in MECHANICS_LINE
    assert header["key_sha256"] == result.key_sha256


def test_the_worksheet_is_utf_8_with_lf_line_endings(
    tmp_path: Path, emit_env: None
) -> None:
    run = closed_run(tmp_path)
    result = emit(run, tmp_path)
    raw = result.worksheet_path.read_bytes()
    assert b"\r" not in raw
    assert "–".encode() in raw


def test_a_floor_that_differs_from_the_committed_constant_is_refused(
    tmp_path: Path, emit_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = closed_run(tmp_path)
    monkeypatch.setattr(
        gitcheck,
        "show_blob",
        lambda sha, path, *, repo=None: "JUDGE_QWK_TRUST_FLOOR: float = 0.65\n",
    )
    with pytest.raises(CalibrationError, match="floor"):
        emit(run, tmp_path)
    assert not (run / "calibration-worksheet.jsonl").exists()
    assert not (tmp_path / "keys").exists()


def test_a_blob_with_no_floor_is_refused(
    tmp_path: Path, emit_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = closed_run(tmp_path)
    monkeypatch.setattr(
        gitcheck, "show_blob", lambda sha, path, *, repo=None: "OTHER = 1\n"
    )
    with pytest.raises(CalibrationError, match="floor"):
        emit(run, tmp_path)


def test_an_uncommitted_floor_or_dirty_source_tree_is_refused(
    tmp_path: Path, emit_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = closed_run(tmp_path)
    monkeypatch.setattr(gitcheck, "is_clean", lambda *paths, repo=None: False)
    with pytest.raises(CalibrationError, match="uncommitted"):
        emit(run, tmp_path)
    assert not (run / "calibration-worksheet.jsonl").exists()


# --- the key, the salt and the digest -----------------------------------------------


def test_the_key_and_salt_sit_outside_the_run_directory(
    tmp_path: Path, emit_env: None
) -> None:
    run = closed_run(tmp_path)
    result = emit(run, tmp_path)
    key_dir = tmp_path / "keys" / RUN_NAME
    assert result.key_path == key_dir / "calibration-key.jsonl"
    assert result.salt_path == key_dir / "calibration-salt.txt"
    assert result.key_path.is_file() and result.salt_path.is_file()
    assert sorted(p.name for p in run.iterdir()) == [
        "calibration-worksheet.jsonl",
        "journal.jsonl",
        "judge-stage.json",
        "judge_cache.json",
    ]
    salt = result.salt_path.read_text(encoding="utf-8").strip()
    assert len(salt) == 64 and int(salt, 16) >= 0
    for path in run.iterdir():
        assert salt not in path.read_text(encoding="utf-8")


def test_the_header_digest_is_reproducible_from_the_salt_and_the_key_file(
    tmp_path: Path, emit_env: None
) -> None:
    run = closed_run(tmp_path)
    result = emit(run, tmp_path)
    salt = result.salt_path.read_text(encoding="utf-8").strip()
    header, _ = read_worksheet(result.worksheet_path)
    assert key_digest(salt, read_key_file(result.key_path)) == header["key_sha256"]


def _rows(n: int = 3) -> list[CalibrationKeyRow]:
    return [
        CalibrationKeyRow(
            slice_id=f"S{i:02d}",
            arm="hybrid",
            question_id=f"q{i}",
            question_type="comparison_query",
            cache_key=f"{i:064x}",
        )
        for i in range(1, n + 1)
    ]


def test_the_digest_changes_when_the_salt_or_any_key_row_changes() -> None:
    rows = _rows()
    base = key_digest("salt", rows)
    assert len(base) == 64
    assert key_digest("salt2", rows) != base
    for field, value in (
        ("arm", "bm25-only"),
        ("question_id", "other"),
        ("question_type", "temporal_query"),
        ("cache_key", "f" * 64),
        ("notes", "x"),
        ("shared_arms", ["hybrid"]),
    ):
        changed = [rows[0].model_copy(update={field: value}), *rows[1:]]
        assert key_digest("salt", changed) != base, field
    assert key_digest("salt", rows[:2]) != base


def test_the_digest_does_not_depend_on_row_order() -> None:
    rows = _rows()
    assert key_digest("salt", list(reversed(rows))) == key_digest("salt", rows)


def test_the_digest_is_the_same_from_an_lf_or_a_crlf_key_file(tmp_path: Path) -> None:
    rows = _rows()
    lines = [r.model_dump_json() for r in rows]
    lf = tmp_path / "lf.jsonl"
    crlf = tmp_path / "crlf.jsonl"
    lf.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    crlf.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    assert read_key_file(lf) == rows == read_key_file(crlf)
    assert key_digest("s", read_key_file(lf)) == key_digest("s", read_key_file(crlf))


# --- refusals ------------------------------------------------------------------------


def test_a_second_emit_refuses_to_overwrite_and_changes_nothing(
    tmp_path: Path, emit_env: None
) -> None:
    run = closed_run(tmp_path)
    result = emit(run, tmp_path)
    before = (
        result.worksheet_path.read_bytes(),
        result.key_path.read_bytes(),
        result.salt_path.read_bytes(),
    )
    with pytest.raises(CalibrationError, match="already exists"):
        emit(run, tmp_path)
    after = (
        result.worksheet_path.read_bytes(),
        result.key_path.read_bytes(),
        result.salt_path.read_bytes(),
    )
    assert before == after


@pytest.mark.parametrize("remaining", ["calibration-key.jsonl", "calibration-salt.txt"])
def test_an_existing_key_or_salt_alone_also_refuses_a_redraw(
    tmp_path: Path, emit_env: None, remaining: str
) -> None:
    run = closed_run(tmp_path)
    result = emit(run, tmp_path)
    result.worksheet_path.unlink()
    for name in ("calibration-key.jsonl", "calibration-salt.txt"):
        if name != remaining:
            (result.key_path.parent / name).unlink()
    with pytest.raises(CalibrationError, match="already exists"):
        emit(run, tmp_path)
    assert not result.worksheet_path.exists()


def test_an_incomplete_stage_cache_is_refused(
    tmp_path: Path, emit_env: None
) -> None:
    run = closed_run(tmp_path)
    cache = JudgeCache(run / "judge_cache.json")
    del cache.entries[sorted(cache.entries)[0]]
    cache.save()
    with pytest.raises(CalibrationError, match="no cache entry"):
        emit(run, tmp_path)
    assert not (run / "calibration-worksheet.jsonl").exists()
    assert not (tmp_path / "keys").exists()


def test_a_stage_that_stopped_early_is_refused(
    tmp_path: Path, emit_env: None
) -> None:
    run = closed_run(tmp_path)
    stage = json.loads((run / "judge-stage.json").read_text(encoding="utf-8"))
    stage["stop_reason"] = "5 consecutive judge errors"
    (run / "judge-stage.json").write_text(json.dumps(stage), encoding="utf-8")
    with pytest.raises(CalibrationError, match="stopped early"):
        emit(run, tmp_path)


def test_a_missing_stage_record_is_refused(tmp_path: Path, emit_env: None) -> None:
    run = closed_run(tmp_path)
    (run / "judge-stage.json").unlink()
    with pytest.raises(CalibrationError, match="judge-stage.json"):
        emit(run, tmp_path)


def test_a_rehearsal_stage_record_is_refused(tmp_path: Path, emit_env: None) -> None:
    run = closed_run(tmp_path)
    stage = json.loads((run / "judge-stage.json").read_text(encoding="utf-8"))
    stage["mode"] = "rehearsal"
    (run / "judge-stage.json").write_text(json.dumps(stage), encoding="utf-8")
    with pytest.raises(CalibrationError, match="rehearsal"):
        emit(run, tmp_path)


def test_an_open_journal_is_refused(tmp_path: Path, emit_env: None) -> None:
    run = closed_run(tmp_path)
    journal = run / "journal.jsonl"
    text = journal.read_text(encoding="utf-8").replace(
        '"partial": false', '"partial": true', 1
    )
    journal.write_text(text, encoding="utf-8")
    with pytest.raises(CalibrationError, match="open"):
        emit(run, tmp_path)


def test_calibration_never_calls_the_judge(
    tmp_path: Path, emit_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = closed_run(tmp_path)

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("the emit makes no API call")

    from lancet_eval import judge, judge_stage

    monkeypatch.setattr(judge, "judge_once", boom)
    monkeypatch.setattr(judge_stage, "judge_once", boom)
    emit(run, tmp_path)


# --- ignored paths, against a throwaway repository -----------------------------------


def _git(repo: Path, *args: str, when: int | None = None) -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(repo.parent / "empty.gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    for leaky in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(leaky, None)
    if when is not None:
        env["GIT_AUTHOR_DATE"] = f"{when} +0000"
        env["GIT_COMMITTER_DATE"] = f"{when} +0000"
    res = subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        cwd=repo,
        shell=False,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if res.returncode not in (0, 1):
        raise AssertionError(res.stderr)
    return res.stdout.strip() + ("" if res.returncode == 0 else "\n<exit 1>")


def test_the_key_and_salt_are_git_ignored_and_the_real_floor_is_read_from_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "throwaway"
    (repo / "eval" / "src" / "lancet_eval").mkdir(parents=True)
    (tmp_path / "empty.gitconfig").write_text("", encoding="utf-8")
    (repo / ".gitignore").write_text("data/\n", encoding="utf-8")
    (repo / "eval" / "src" / "lancet_eval" / "thresholds.py").write_text(
        "JUDGE_QWK_TRUST_FLOOR: float = 0.70\n", encoding="utf-8"
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "floor", when=int(time.time()) - 100_000)
    head = _git(repo, "rev-parse", "HEAD")

    monkeypatch.setenv("OPENROUTER_API_KEY", API_KEY)
    install_fake(monkeypatch)
    run = build_run(tmp_path, standard_records(g_ids(12, 12, 6)))
    run_judge_stage(run_dir=run, stage_cap=5.0, git_repo=repo)

    keys_root = repo / "data" / "calibration-keys"
    result = emit_worksheet(run, keys_root=keys_root, git_repo=repo)

    header, _ = read_worksheet(result.worksheet_path)
    assert header["emitted_at_sha"] == head
    assert header["d114_floor"] == 0.70
    for path in (result.key_path, result.salt_path):
        rel = path.relative_to(repo).as_posix()
        assert _git(repo, "check-ignore", "-q", rel) == ""
        assert _git(repo, "status", "--porcelain", "--", rel) == ""
    assert _git(repo, "status", "--porcelain") == ""  # the keys do not show up at all


def test_the_live_gitignore_covers_the_default_key_location() -> None:
    root = repo_root()
    for name in ("calibration-key.jsonl", "calibration-salt.txt"):
        res = subprocess.run(
            ["git", "check-ignore", "-q", f"data/calibration-keys/some-run/{name}"],
            cwd=root,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, name
    assert calibration.default_keys_root() == root / "data" / "calibration-keys"


# --- the command ---------------------------------------------------------------------


def test_the_emit_command_prints_counts_and_the_worksheet_pathspec_only(
    tmp_path: Path, emit_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calibration, "repo_root", lambda: tmp_path / "repo")
    run = closed_run(tmp_path)
    result = CliRunner().invoke(app, ["calibration", "emit", "--run", str(run)])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "20" in out
    assert "git add" in out and "calibration-worksheet.jsonl" in out
    assert FORBIDDEN.search(out) is None
    assert API_KEY not in out
    for arm in ARMS:
        assert arm not in out
    keys = read_key_file(
        tmp_path / "repo" / "data" / "calibration-keys" / RUN_NAME
        / "calibration-key.jsonl"
    )
    for key in keys:
        assert key.cache_key not in out and key.question_id not in out
    assert not (run / "report.json").exists()


def test_the_emit_command_exits_nonzero_on_a_refusal(
    tmp_path: Path, emit_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calibration, "repo_root", lambda: tmp_path / "repo")
    run = closed_run(tmp_path)
    (run / "judge-stage.json").unlink()
    result = CliRunner().invoke(app, ["calibration", "emit", "--run", str(run)])
    assert result.exit_code == 1
    assert not (tmp_path / "repo").exists()


def test_the_emit_command_requires_a_run() -> None:
    result = CliRunner().invoke(app, ["calibration", "emit"])
    assert result.exit_code == 2
