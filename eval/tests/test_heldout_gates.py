"""Tests for `unpark_gates --stage heldout` (06.3.5-09 Task 1, D-109).

The held-out drive's gates are 06.3.4.1's SC-1 (completeness) and SC-2 (error mode and
retrieval flatness), read per arm and pooled, so a failing arm cannot hide in the pool.
SC-3, SC-4 and SC-5 are not computed for this stage.

Each fixture holds 12 questions per arm, not 5: the D-89 flatness verdict reads
`unavailable` below 8 usable records, so a smaller fixture could never read PASS.
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import lancet_eval.unpark_gates as gates
from lancet_eval.corpus import GoldQuestion
from lancet_eval.decay import DecayAnalysisError
from lancet_eval.flatness import flatness_verdict, records_from_run_journal
from lancet_eval.journal import AttemptRecord, NodeFailed, NodeTiming, RunRecord

ARMS = ["dense-only", "bm25-only", "hybrid", "hybrid+graph"]
CORPUS = "multihop_rag_heldout"
N_QUESTIONS = 12
POOLED = "pooled"


def _questions(n: int = N_QUESTIONS) -> list[GoldQuestion]:
    return [
        GoldQuestion(
            question_id=f"q{i:02d}",
            question="q",
            gold_facts=["a gold fact"],
            gold_answer="a",
            evidence_list=[{"title": "doc", "fact": "a gold fact"}],
        )
        for i in range(n)
    ]


def _patch_corpus(
    monkeypatch: pytest.MonkeyPatch, questions: list[GoldQuestion] | None = None
) -> list[GoldQuestion]:
    """Make the held-out corpus 12 small questions under the four registry arms.

    `completeness_comparison` imports the loaders lazily from `lancet_eval.corpus`;
    `unpark_gates` binds the same names at import. Both are patched.
    """
    import lancet_eval.corpus as corpus_module

    qs = _questions() if questions is None else questions
    config = SimpleNamespace(arms=list(ARMS))
    for module in (corpus_module, gates):
        monkeypatch.setattr(module, "load_corpus_config", lambda name: config)
        monkeypatch.setattr(module, "load_sample_questions", lambda name: list(qs))
    return qs


def _ok(question_id: str, arm: str, index: int) -> RunRecord:
    return RunRecord(
        corpus=CORPUS,
        question_id=question_id,
        graph_arm=arm,
        outcome="success",
        answer="A",
        index_generation="gen-1",
        node_timings=[
            NodeTiming(node_name="RetrieveHybrid", duration_ms=100.0 + index % 3),
            NodeTiming(node_name="GenerateAnswer", duration_ms=10.0),
        ],
    )


def _generate_timeout(question_id: str, arm: str, index: int) -> RunRecord:
    """A node timeout on GenerateAnswer: class `timeout`, RetrieveHybrid unaffected."""
    return _ok(question_id, arm, index).model_copy(
        update={
            "outcome": "error",
            "answer": None,
            "node_failures": [
                NodeFailed(
                    node_name="GenerateAnswer",
                    error_kind=1,
                    error_message="node deadline",
                    retryable=True,
                )
            ],
        }
    )


def _transport_error(question_id: str, arm: str, index: int) -> RunRecord:
    return _ok(question_id, arm, index).model_copy(
        update={"outcome": "error", "answer": None, "error_type": "ConnectError"}
    )


def _write_run(
    tmp_path: Path,
    questions: list[GoldQuestion],
    *,
    skip: set[tuple[str, str]] | None = None,
    override: dict[tuple[str, str], Any] | None = None,
    gate_stage: str = "heldout",
    max_retries: int = 0,
) -> Path:
    """A journal the held-out drive would write: question-major, arms rotated."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    header = {
        "type": "header",
        "corpus": CORPUS,
        "partial": False,
        "gate_stage": gate_stage,
        "max_retries": max_retries,
    }
    skip = skip or set()
    override = override or {}
    with open(run_dir / "journal.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for index, q in enumerate(questions):
            offset = index % len(ARMS)
            for arm in ARMS[offset:] + ARMS[:offset]:
                if (q.question_id, arm) in skip:
                    continue
                make = override.get((q.question_id, arm), _ok)
                f.write(make(q.question_id, arm, index).model_dump_json() + "\n")
    (run_dir / "report.json").write_text("{}", encoding="utf-8")
    return run_dir


def _run(
    tmp_path: Path, run_dir: Path, *, pid_after: int = 1
) -> tuple[dict[str, Any], str]:
    out = tmp_path / "out" / "gates-heldout.md"
    code = gates.main(
        [
            "--stage",
            "heldout",
            "--run",
            str(run_dir),
            "--engine-pid-before",
            "1",
            "--engine-pid-after",
            str(pid_after),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    payload = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    return payload, out.read_text(encoding="utf-8")


def _forbid(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    def _forbidden(name: str) -> Any:
        def _raise(*args: Any, **kwargs: Any) -> None:
            raise AssertionError(f"{name} computed")

        return _raise

    for name in names:
        monkeypatch.setattr(gates, name, _forbidden(name), raising=False)


_NOT_COMPUTED_FOR_HELDOUT = (
    "evaluate_sc3",
    "evaluate_sc4",
    "evaluate_sc5",
    "build_rows",
    "graph_off_invariance",
)
_PER_ARM_COMPUTATIONS = (
    "evaluate_sc2",
    "evaluate_sc2_arm",
    "citation_rejection_rate",
    "_citation_rejection_from_records",
)


def test_the_stage_label_is_heldout() -> None:
    assert gates.HELDOUT_STAGE == "heldout"


def test_a_complete_four_arm_journal_passes_per_arm_and_pooled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _patch_corpus(monkeypatch)
    _forbid(monkeypatch, *_NOT_COMPUTED_FOR_HELDOUT)
    run_dir = _write_run(tmp_path, qs)

    payload, markdown = _run(tmp_path, run_dir)

    for gate in ("SC-1", "SC-2"):
        assert list(payload[gate]) == [*ARMS, POOLED]
        for label in (*ARMS, POOLED):
            reading = payload[gate][label]
            assert reading["status"] == "PASS", (gate, label, reading["reason"])
    for arm in ARMS:
        assert payload["SC-1"][arm]["detail"]["n_expected"] == N_QUESTIONS
        assert payload["SC-1"][arm]["n"] == N_QUESTIONS
        assert payload["SC-2"][arm]["n"] == N_QUESTIONS
    assert payload["SC-1"][POOLED]["n"] == N_QUESTIONS * len(ARMS)
    assert list(payload["D-69 companion"]) == [*ARMS, POOLED]
    assert set(payload["not_computed"]) == {"SC-3", "SC-4", "SC-5"}
    for reason in payload["not_computed"].values():
        assert "heldout" in reason
    assert "retry_provenance" in payload
    assert "# Unpark Gates (heldout)" in markdown
    assert "| Reading | dense-only | bm25-only | hybrid | hybrid+graph | pooled |" in (
        markdown
    )
    assert f"| SC-1 | PASS ({N_QUESTIONS}) |" in markdown
    assert "SC-3, SC-4, SC-5 are not computed for the heldout stage" in markdown


def test_populations_and_gold_chunks_are_not_required_for_heldout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _patch_corpus(monkeypatch)
    run_dir = _write_run(tmp_path, qs)
    out = tmp_path / "out" / "gates-heldout.md"
    code = gates.main(
        [
            "--stage",
            "heldout",
            "--run",
            str(run_dir),
            "--engine-pid-before",
            "1",
            "--engine-pid-after",
            "1",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert out.is_file()
    assert out.with_suffix(".json").is_file()


@pytest.mark.parametrize("stage", ["drive1", "drive1b", "drive2"])
def test_the_other_stages_still_require_populations_and_gold_chunks(
    tmp_path: Path, stage: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        gates.main(
            [
                "--stage",
                stage,
                "--run",
                str(tmp_path),
                "--engine-pid-before",
                "1",
                "--engine-pid-after",
                "1",
                "--out",
                str(tmp_path / "out.md"),
            ]
        )
    assert exc.value.code == 2


def test_missing_units_miss_the_failing_arm_and_pooled_but_not_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _patch_corpus(monkeypatch)
    _forbid(monkeypatch, *_NOT_COMPUTED_FOR_HELDOUT, *_PER_ARM_COMPUTATIONS)
    run_dir = _write_run(
        tmp_path, qs, skip={("q00", "bm25-only"), ("q01", "bm25-only")}
    )

    payload, markdown = _run(tmp_path, run_dir)

    sc1 = payload["SC-1"]
    assert sc1["bm25-only"]["status"] == "MISS"
    assert "bm25-only" in sc1["bm25-only"]["reason"]
    assert "2 of 12" in sc1["bm25-only"]["reason"]
    assert sc1["bm25-only"]["detail"]["missing_units"] == 2
    assert sc1["bm25-only"]["n"] == N_QUESTIONS - 2
    assert sc1[POOLED]["status"] == "MISS"
    for arm in ("dense-only", "hybrid", "hybrid+graph"):
        assert sc1[arm]["status"] == "PASS", (arm, sc1[arm]["reason"])
        assert sc1[arm]["n"] == N_QUESTIONS
    # Nothing is computed from an incomplete journal: every SC-2 reading is MISS.
    for label in (*ARMS, POOLED):
        assert payload["SC-2"][label]["status"] == "MISS", label
        assert "journal incomplete" in payload["SC-2"][label]["reason"]
    assert "MISS (10): " in markdown


def test_an_arm_with_zero_records_reads_miss_with_n_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _patch_corpus(monkeypatch)
    skip = {(q.question_id, "hybrid+graph") for q in qs}
    run_dir = _write_run(tmp_path, qs, skip=skip)

    payload, _ = _run(tmp_path, run_dir)

    reading = payload["SC-1"]["hybrid+graph"]
    assert reading["status"] == "MISS"
    assert reading["n"] == 0
    assert "n=0" in reading["reason"]
    assert payload["SC-2"]["hybrid+graph"]["status"] == "MISS"
    assert payload["SC-2"]["hybrid+graph"]["n"] == 0
    for arm in ("dense-only", "bm25-only", "hybrid"):
        assert payload["SC-1"][arm]["status"] == "PASS"


def test_an_empty_corpus_never_passes_vacuously(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _patch_corpus(monkeypatch, questions=[])
    run_dir = _write_run(tmp_path, qs)

    payload, _ = _run(tmp_path, run_dir)

    for label in (*ARMS, POOLED):
        for gate in ("SC-1", "SC-2"):
            assert payload[gate][label]["status"] == "MISS", (gate, label)
    assert payload["SC-1"]["dense-only"]["detail"]["n_expected"] == 0
    assert payload["SC-1"]["dense-only"]["n"] == 0


def test_timeouts_dominant_on_one_arm_miss_that_arm_while_the_pool_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _patch_corpus(monkeypatch)
    override: dict[tuple[str, str], Any] = {
        # Three GenerateAnswer timeouts, all on dense-only.
        ("q00", "dense-only"): _generate_timeout,
        ("q01", "dense-only"): _generate_timeout,
        ("q02", "dense-only"): _generate_timeout,
        # Five transport errors elsewhere: the pooled plurality is not timeout.
        ("q03", "bm25-only"): _transport_error,
        ("q04", "bm25-only"): _transport_error,
        ("q05", "hybrid"): _transport_error,
        ("q06", "hybrid"): _transport_error,
        ("q07", "hybrid+graph"): _transport_error,
    }
    run_dir = _write_run(tmp_path, qs, override=override)

    payload, _ = _run(tmp_path, run_dir)

    pooled = payload["SC-2"][POOLED]
    assert pooled["detail"]["class_counts"] == {"timeout": 3.0, "transport": 5.0}
    assert pooled["detail"]["timeout_dominant"] is False
    assert pooled["status"] == "PASS", pooled["reason"]

    dense = payload["SC-2"]["dense-only"]
    assert dense["status"] == "MISS"
    assert dense["detail"]["timeout_dominant"] is True
    assert "dense-only" in dense["reason"]
    for arm in ("bm25-only", "hybrid", "hybrid+graph"):
        assert payload["SC-2"][arm]["status"] == "PASS", (
            arm,
            payload["SC-2"][arm]["reason"],
        )
    # The completeness reading is untouched by error modes.
    for label in (*ARMS, POOLED):
        assert payload["SC-1"][label]["status"] == "PASS"


def test_per_arm_flatness_over_an_interleaved_journal_renumbers_ordinals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _patch_corpus(monkeypatch)
    run_dir = _write_run(tmp_path, qs)

    # Negative control: one arm's records, left at their journal ordinals, have gaps.
    flat = records_from_run_journal(run_dir / "journal.jsonl")
    one_arm = [r for r in flat if r.graph_arm == "hybrid"]
    with pytest.raises(DecayAnalysisError):
        flatness_verdict(one_arm)

    payload, _ = _run(tmp_path, run_dir)

    for arm in ARMS:
        reading = payload["SC-2"][arm]
        assert reading["status"] == "PASS", (arm, reading["reason"])
        assert reading["detail"]["flatness_reason"] == "flat"


def test_a_journal_driven_as_another_stage_misses_every_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _patch_corpus(monkeypatch)
    _forbid(monkeypatch, *_PER_ARM_COMPUTATIONS)
    run_dir = _write_run(tmp_path, qs, gate_stage="drive2")

    payload, _ = _run(tmp_path, run_dir)

    for gate in ("SC-1", "SC-2"):
        for label in (*ARMS, POOLED):
            reading = payload[gate][label]
            assert reading["status"] == "MISS", (gate, label)
            assert "gate_stage" in reading["reason"], (gate, label)


def test_a_journal_with_a_retry_misses_every_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _patch_corpus(monkeypatch)
    _forbid(monkeypatch, *_PER_ARM_COMPUTATIONS)
    retried = AttemptRecord(attempt=1, outcome="error", error_type="ReadTimeout")

    def _with_retry(question_id: str, arm: str, index: int) -> RunRecord:
        return _ok(question_id, arm, index).model_copy(
            update={"prior_attempts": [retried]}
        )

    run_dir = _write_run(tmp_path, qs, override={("q00", "hybrid"): _with_retry})

    payload, _ = _run(tmp_path, run_dir)

    for gate in ("SC-1", "SC-2"):
        for label in (*ARMS, POOLED):
            reading = payload[gate][label]
            assert reading["status"] == "MISS", (gate, label)
            assert "retried attempts" in reading["reason"], (gate, label)


def test_unequal_engine_pids_miss_sc2_for_every_arm_and_pooled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _patch_corpus(monkeypatch)
    run_dir = _write_run(tmp_path, qs)

    payload, _ = _run(tmp_path, run_dir, pid_after=2)

    for label in (*ARMS, POOLED):
        assert payload["SC-2"][label]["status"] == "MISS", label
        assert "engine restarted" in payload["SC-2"][label]["reason"], label
        assert payload["SC-1"][label]["status"] == "PASS", label


def test_a_missing_journal_misses_every_reading_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_corpus(monkeypatch)
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    payload, _ = _run(tmp_path, run_dir)

    for gate in ("SC-1", "SC-2"):
        assert payload[gate][POOLED]["status"] == "MISS"
        assert "no journal file" in payload[gate][POOLED]["reason"]


def test_no_heldout_helper_indexes_an_arm_map_with_a_legacy_literal() -> None:
    import ast
    import inspect

    source = inspect.getsource(gates)
    tree = ast.parse(source)
    wanted = {
        "evaluate_sc1_arm",
        "evaluate_sc2_arm",
        "_heldout_readings",
        "_heldout_markdown",
    }
    found = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    }
    assert set(found) == wanted
    for name, node in found.items():
        literals = {
            n.value
            for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        }
        assert not literals & {"graph-on", "graph-off"}, name


# --- 06.3.6-07: lever arm lists, the D-151 SC-2 floor and the O14 series ------------------

SEVEN_ARMS = [
    "dense-only",
    "hybrid",
    "hybrid+graph",
    "hybrid+rerank",
    "hybrid+metadata",
    "hybrid+answer-format",
    "hybrid+all",
]
SIX_ARMS = [
    "hybrid",
    "hybrid+graph",
    "hybrid+rerank",
    "hybrid+metadata",
    "hybrid+answer-format",
    "hybrid+all",
]


def _patch_arms(
    monkeypatch: pytest.MonkeyPatch,
    arms: list[str],
    *,
    token: str | None = None,
    questions: list[GoldQuestion] | None = None,
) -> list[GoldQuestion]:
    """The held-out corpus on an arbitrary arm list, optionally on a named token."""
    import lancet_eval.corpus as corpus_module

    qs = _questions() if questions is None else questions
    config = SimpleNamespace(arms=list(arms))
    if token is not None:
        config.preregistration_token = token
    for module in (corpus_module, gates):
        monkeypatch.setattr(module, "load_corpus_config", lambda name: config)
        monkeypatch.setattr(module, "load_sample_questions", lambda name: list(qs))
    return qs


def _write_run_arms(
    tmp_path: Path,
    questions: list[GoldQuestion],
    arms: list[str],
    *,
    make: Any = None,
) -> Path:
    """A journal over `arms`, question-major, arms rotated as the drive rotates them."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    header = {
        "type": "header",
        "corpus": CORPUS,
        "partial": False,
        "gate_stage": "heldout",
        "max_retries": 0,
    }
    with open(run_dir / "journal.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for index, q in enumerate(questions):
            offset = index % len(arms)
            for arm in arms[offset:] + arms[:offset]:
                record = (make or _ok)(q.question_id, arm, index)
                f.write(record.model_dump_json() + "\n")
    (run_dir / "report.json").write_text("{}", encoding="utf-8")
    return run_dir


@pytest.mark.parametrize("arms", [SEVEN_ARMS, SIX_ARMS], ids=["7-arm", "6-arm"])
def test_a_lever_arm_journal_reads_per_arm_plus_pooled_from_the_corpus_config(
    arms: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _patch_arms(monkeypatch, arms)
    _forbid(monkeypatch, *_NOT_COMPUTED_FOR_HELDOUT)
    run_dir = _write_run_arms(tmp_path, qs, arms)

    payload, markdown = _run(tmp_path, run_dir)

    assert payload["arms"] == arms
    for gate in ("SC-1", "SC-2"):
        assert list(payload[gate]) == [*arms, POOLED]
        for label in (*arms, POOLED):
            assert payload[gate][label]["status"] == "PASS", (gate, label)
    assert payload["SC-1"][POOLED]["n"] == N_QUESTIONS * len(arms)
    header = next(line for line in markdown.splitlines() if line.startswith("| Reading"))
    for label in arms:
        assert label in header


def test_a_missing_lever_arm_unit_misses_only_that_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _patch_arms(monkeypatch, SIX_ARMS)
    run_dir = _write_run_arms(
        tmp_path,
        qs,
        SIX_ARMS,
        make=lambda qid, arm, i: _ok(qid, arm, i),
    )
    lines = (run_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    kept = [
        line
        for line in lines
        if not ('"graph_arm":"hybrid+rerank"' in line and '"question_id":"q03"' in line)
    ]
    assert len(kept) == len(lines) - 1
    (run_dir / "journal.jsonl").write_text("\n".join(kept) + "\n", encoding="utf-8")

    payload, _ = _run(tmp_path, run_dir)

    assert payload["SC-1"]["hybrid+rerank"]["status"] == "MISS"
    assert payload["SC-1"]["hybrid"]["status"] == "PASS"


# --- D-151 / D-164: the SC-2 error-mode clause under the pre-registered rate floor ---------

FLOOR = Fraction(1, 40)


def _floor() -> Any:
    return gates.SC2TimeoutFloor(rate=FLOOR, problem=None)


def test_the_floor_is_one_fortieth_of_the_records_in_the_reading() -> None:
    assert Fraction(str(0.025)) == FLOOR


@pytest.mark.parametrize(
    ("n", "timeouts", "fails"),
    [
        (351, 9, True),
        (351, 8, False),
        (100, 3, True),
        (100, 2, False),
        (200, 5, True),
        (200, 4, False),
        (1404, 36, True),
        (1404, 35, False),
    ],
)
def test_a_dominant_timeout_class_fails_only_at_the_rate_floor(
    n: int, timeouts: int, fails: bool
) -> None:
    result = gates._error_mode_clause({"timeout": timeouts}, n, _floor())
    assert result.fails is fails
    if not fails:
        assert result.note == (
            f"reported: timeout dominant, not material ({timeouts} of {n})"
        )
    else:
        assert result.note is None


def test_a_legacy_reading_fails_on_any_dominant_timeout() -> None:
    legacy = gates.SC2TimeoutFloor(rate=None, problem=None)
    assert gates._error_mode_clause({"timeout": 1}, 351, legacy).fails is True
    assert gates._error_mode_clause({"timeout": 1}, 351, legacy).note is None


def test_a_timeout_that_is_not_dominant_never_fails_or_reports() -> None:
    result = gates._error_mode_clause({"timeout": 1, "rejected": 3}, 351, _floor())
    assert result.fails is False
    assert result.note is None
    assert gates._error_mode_clause({}, 351, _floor()).fails is False


def test_a_tie_at_the_plurality_count_is_still_dominant() -> None:
    assert gates._error_mode_clause({"timeout": 9, "other": 9}, 351, _floor()).fails
    quiet = gates._error_mode_clause({"timeout": 8, "other": 8}, 351, _floor())
    assert quiet.fails is False
    assert quiet.note is not None


def test_the_floor_reproduces_the_ai_spec_table_of_the_recorded_readings() -> None:
    """AI-SPEC 5 D-151: drives 1, 1b, 2 unchanged; the 06.3.5 held-out rows read reported."""
    rows = {
        "drive1 pooled": (200, {"other": 9}, False, None),
        "drive1b pooled": (200, {}, False, None),
        "drive2 pooled": (200, {"timeout": 1, "other": 2}, False, None),
        "heldout dense-only": (351, {"timeout": 4, "other": 1}, False, 4),
        "heldout bm25-only": (351, {}, False, None),
        "heldout hybrid": (351, {"timeout": 6}, False, 6),
        "heldout hybrid+graph": (351, {"timeout": 2}, False, 2),
        "heldout pooled": (1404, {"timeout": 12, "other": 1}, False, 12),
    }
    for name, (n, counts, fails, reported) in rows.items():
        result = gates._error_mode_clause(counts, n, _floor())
        assert result.fails is fails, name
        if reported is None:
            assert result.note is None, name
        else:
            assert result.note == (
                f"reported: timeout dominant, not material ({reported} of {n})"
            ), name


def test_an_unresolved_token_is_a_fail_closed_problem() -> None:
    floor = gates.SC2TimeoutFloor(rate=None, problem="token X names nothing")
    result = gates._error_mode_clause({}, 351, floor)
    assert result.fails is True
    assert "token X names nothing" in str(result.problem)


def _timeouts_journal(
    tmp_path: Path, arms: list[str], per_arm_timeouts: dict[str, int], n_questions: int
) -> Path:
    qs = _questions(n_questions)
    done: dict[str, int] = dict.fromkeys(arms, 0)

    def make(qid: str, arm: str, index: int) -> RunRecord:
        if done[arm] < per_arm_timeouts.get(arm, 0):
            done[arm] += 1
            return _generate_timeout(qid, arm, index)
        return _ok(qid, arm, index)

    return _write_run_arms(tmp_path, qs, arms, make=make)


def test_a_351_record_arm_reads_miss_at_nine_timeouts_and_reported_at_eight(
    tmp_path: Path,
) -> None:
    nine = tmp_path / "nine"
    nine.mkdir()
    eight = tmp_path / "eight"
    eight.mkdir()
    arms = ["hybrid"]
    run9 = _timeouts_journal(nine, arms, {"hybrid": 9}, 351)
    run8 = _timeouts_journal(eight, arms, {"hybrid": 8}, 351)

    miss = gates.evaluate_sc2_arm(
        run9 / "journal.jsonl", "hybrid", 1, 1, timeout_floor=_floor()
    )
    reported = gates.evaluate_sc2_arm(
        run8 / "journal.jsonl", "hybrid", 1, 1, timeout_floor=_floor()
    )

    assert miss.status == "MISS"
    assert "timeout is a dominant error class" in miss.reason
    assert miss.n == 351
    assert reported.status == "PASS"
    assert "reported: timeout dominant, not material (8 of 351)" in reported.reason
    assert reported.detail["timeout_dominant"] is True
    assert reported.detail["sc2_timeout_rate_floor"] == "1/40"
    # Without the floor the same eight timeouts keep the legacy MISS.
    legacy = gates.evaluate_sc2_arm(
        run8 / "journal.jsonl",
        "hybrid",
        1,
        1,
        timeout_floor=gates.SC2TimeoutFloor(rate=None, problem=None),
    )
    assert legacy.status == "MISS"


def test_the_pooled_reading_uses_its_own_n(tmp_path: Path) -> None:
    """One timeout is 1 of 12 on its arm (material) and 1 of 48 pooled (not)."""
    arms = list(ARMS)
    run = _timeouts_journal(tmp_path, arms, {"hybrid": 1}, 12)
    journal = run / "journal.jsonl"

    arm = gates.evaluate_sc2_arm(journal, "hybrid", 1, 1, timeout_floor=_floor())
    pooled = gates.evaluate_sc2(
        journal, 1, 1, roles=gates.HELDOUT_ARM_ROLES, timeout_floor=_floor()
    )

    assert arm.status == "MISS" and arm.n == 12
    assert pooled.status == "PASS" and pooled.n == 48
    assert "reported: timeout dominant, not material (1 of 48)" in pooled.reason


def test_a_token_that_resolves_to_a_lever_preregistration_supplies_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval import thresholds
    from lancet_eval.thresholds import FamilySpec, LeverPreRegistration

    prereg = LeverPreRegistration(
        reference_arm="hybrid",
        families=(
            FamilySpec(
                primary="answer_usable",
                role="decisional",
                arms=("hybrid+rerank",),
                alpha=0.05,
            ),
        ),
        descriptive_arms=("hybrid+all",),
        test="paired_sign_flip_exact_two_sided",
        non_evaluable_rule="p=1_m_unchanged",
        population="pairwise_per_comparison",
        complete_case_floor=0.80,
        matching_rule="chunk_id_via_gold_chunks",
        bootstrap_b=10_000,
        bootstrap_seed=42,
        null_guard_arms=(),
        null_guard_predicate="metrics.is_abstention",
        null_guard_margin=0.10,
        null_guard_min_pair_fraction=0.80,
        answer_mix_strata=(),
        sc2_timeout_rate_floor=0.025,
        rerank_degrade_tripwire_rate=0.20,
        rerank_degrade_tripwire_min_calls=50,
        rerank_consecutive_degrade_halt=5,
        default_rule="test",
        provenance="test",
    )
    monkeypatch.setattr(thresholds, "PREREG_TEST_FLOOR", prereg, raising=False)
    arms = ["hybrid", "hybrid+rerank", "hybrid+all"]
    _patch_arms(monkeypatch, arms, token="PREREG_TEST_FLOOR")
    run = _timeouts_journal(tmp_path, ["hybrid"], {"hybrid": 1}, 12)
    journal = run / "journal.jsonl"

    # 1 of 12 = 0.083 >= 1/40, so the floor read from the token makes it material.
    assert gates.evaluate_sc2_arm(journal, "hybrid", 1, 1).status == "MISS"
    floor = gates.sc2_timeout_floor_for(journal)
    assert floor.rate == FLOOR
    assert floor.problem is None


def test_a_token_that_resolves_to_the_06_3_5_object_keeps_the_legacy_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_arms(monkeypatch, list(ARMS), token="PREREGISTRATION_06_3_5")
    run = _timeouts_journal(tmp_path, ["hybrid"], {"hybrid": 1}, 12)
    floor = gates.sc2_timeout_floor_for(run / "journal.jsonl")
    assert floor.rate is None and floor.problem is None


def test_a_corpus_without_a_token_or_an_unloadable_corpus_keeps_the_legacy_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_corpus(monkeypatch)  # a config with no preregistration_token
    run = _timeouts_journal(tmp_path, ["hybrid"], {"hybrid": 1}, 12)
    journal = run / "journal.jsonl"
    assert gates.sc2_timeout_floor_for(journal) == gates.SC2TimeoutFloor(None, None)

    import lancet_eval.corpus as corpus_module

    def boom(name: str) -> None:
        raise FileNotFoundError(name)

    for module in (corpus_module, gates):
        monkeypatch.setattr(module, "load_corpus_config", boom)
    assert gates.sc2_timeout_floor_for(journal) == gates.SC2TimeoutFloor(None, None)


def test_a_token_that_names_nothing_reads_miss_with_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_arms(monkeypatch, list(ARMS), token="PREREGISTRATION_NOT_THERE")
    run = _timeouts_journal(tmp_path, list(ARMS), {}, 12)
    journal = run / "journal.jsonl"

    arm = gates.evaluate_sc2_arm(journal, "hybrid", 1, 1)
    pooled = gates.evaluate_sc2(journal, 1, 1, roles=gates.HELDOUT_ARM_ROLES)

    for reading in (arm, pooled):
        assert reading.status == "MISS"
        assert "PREREGISTRATION_NOT_THERE" in reading.reason


# --- O14 / D-175: the RetrieveHybrid minus rerank.latency_ms series -----------------------


def _rerank_ok(question_id: str, arm: str, index: int) -> RunRecord:
    from lancet_eval.client import RerankMeta

    record = _ok(question_id, arm, index)
    if "rerank" not in arm and arm != "hybrid+all":
        return record
    timings = [
        NodeTiming(node_name="RetrieveHybrid", duration_ms=400.0 + index % 3),
        NodeTiming(node_name="GenerateAnswer", duration_ms=10.0),
    ]
    return record.model_copy(
        update={
            "node_timings": timings,
            "workflow_meta": WorkflowWireMeta(
                rerank=RerankMeta(
                    latency_ms=300,
                    cost_credits=4.4e-07,
                    cost_reported=True,
                    outcome="completed",
                )
            ),
        }
    )


def test_a_rerank_bearing_arm_prints_the_subtracted_series_beside_the_flatness(
    tmp_path: Path,
) -> None:
    arms = ["hybrid", "hybrid+rerank"]
    run = _write_run_arms(tmp_path, _questions(), arms, make=_rerank_ok)
    journal = run / "journal.jsonl"

    reading = gates.evaluate_sc2_arm(journal, "hybrid+rerank", 1, 1)

    series = reading.detail["rerank_subtracted_flatness"]
    assert series["n"] == N_QUESTIONS
    # 400 + (0..2) minus 300: the node time without the provider call.
    assert series["slice_medians_ms"] == [pytest.approx(101.0)]
    assert series["median_rerank_latency_ms"] == pytest.approx(300.0)
    assert "reason" in series
    assert "RetrieveHybrid minus rerank.latency_ms" in reading.reason
    # The 06.3.4.1 reading is unchanged and still there.
    assert reading.detail["flatness_reason"] == "flat"
    assert reading.status == "PASS"


def test_the_subtracted_series_never_changes_the_status(tmp_path: Path) -> None:
    def make(question_id: str, arm: str, index: int) -> RunRecord:
        record = _rerank_ok(question_id, arm, index)
        if arm != "hybrid+rerank":
            return record
        # A latency drift inside the rerank call: the node grows, the series stays flat.
        timings = [
            NodeTiming(node_name="RetrieveHybrid", duration_ms=400.0 + 60.0 * index),
            NodeTiming(node_name="GenerateAnswer", duration_ms=10.0),
        ]
        assert record.workflow_meta is not None and record.workflow_meta.rerank
        meta = record.workflow_meta.model_copy(
            update={
                "rerank": record.workflow_meta.rerank.model_copy(
                    update={"latency_ms": 300 + 60 * index}
                )
            }
        )
        return record.model_copy(update={"node_timings": timings, "workflow_meta": meta})

    run = _write_run_arms(tmp_path, _questions(), ["hybrid", "hybrid+rerank"], make=make)

    reading = gates.evaluate_sc2_arm(run / "journal.jsonl", "hybrid+rerank", 1, 1)

    assert reading.detail["flatness_reason"] == "decay_present"
    assert reading.status == "MISS"
    assert reading.detail["rerank_subtracted_flatness"]["reason"] == "flat"
    assert "provider latency drift" in reading.detail["o14_note"]


def test_an_arm_without_rerank_has_no_subtracted_series(tmp_path: Path) -> None:
    run = _write_run_arms(
        tmp_path, _questions(), ["hybrid", "hybrid+rerank"], make=_rerank_ok
    )
    reading = gates.evaluate_sc2_arm(run / "journal.jsonl", "hybrid", 1, 1)
    assert "rerank_subtracted_flatness" not in reading.detail
    assert "rerank.latency_ms" not in reading.reason
