"""Tests for `unpark_gates --stage heldout` (06.3.5-09 Task 1, D-109).

The held-out drive's gates are 06.3.4.1's SC-1 (completeness) and SC-2 (error mode and
retrieval flatness), read per arm and pooled, so a failing arm cannot hide in the pool.
SC-3, SC-4 and SC-5 are not computed for this stage.

Each fixture holds 12 questions per arm, not 5: the D-89 flatness verdict reads
`unavailable` below 8 usable records, so a smaller fixture could never read PASS.
"""

from __future__ import annotations

import json
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
