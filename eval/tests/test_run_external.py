"""`lancet-eval run-external` drives an external arm (#14, D-247).

The offline tests drive `run_external` with a fake bin that answers as
`generate_from_context` does: `pack` with the engine's request body, `generate` with an
`Answer:` line. The corpus is the levers fixture's S0 shape, one Lancet arm and the
`llamaindex` external arm, and the journal is scored with `score_run` (seam S-A).

The integration test runs the real bin against the loopback `provider_stub` (seam S-C).
It is skipped unless `LANCET_EVAL_INTEGRATION=1` and never calls OpenRouter.
"""

from __future__ import annotations

import dataclasses
import json
import os
import threading
import tomllib
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import levers_fixture as fx
import pytest
from typer.testing import CliRunner

from lancet_eval import external_run, parity, thresholds
from lancet_eval.cli import app
from lancet_eval.config import repo_root
from lancet_eval.context_export import (
    CONTEXT_EXPORT_FILE,
    CheckpointRow,
    ContextExportError,
    ContextExportRow,
    InMemoryCheckpointSource,
    read_export,
)
from lancet_eval.external_run import ExternalRunError, run_external
from lancet_eval.journal import (
    Journal,
    JournalReuseError,
    load_records,
    read_journal_header,
)
from lancet_eval.measure import compute_spend
from lancet_eval.run import write_context_export
from lancet_eval.score import score_run
from lancet_eval.thresholds import FamilySpec, LeverPreRegistration

REFERENCE = "hybrid+rerank+metadata"
EXTERNAL = fx.EXTERNAL
#: A stage cap no test drive reaches.
OPEN_CAP = 100.0

integration = pytest.mark.skipif(
    os.environ.get("LANCET_EVAL_INTEGRATION") != "1",
    reason="integration test (seam S-C): set LANCET_EVAL_INTEGRATION=1 to build "
    "and run the generate_from_context bin against provider_stub",
)


def _engine_generation() -> tuple[str, list[str]]:
    with open(repo_root() / "config" / "config.toml", "rb") as f:
        openrouter = tomllib.load(f)["openrouter"]
    return openrouter["generation_model"], list(openrouter["generation_provider_order"])


def _s0_prereg() -> LeverPreRegistration:
    """A synthetic S0-shaped stage constant: one Lancet arm, one external arm."""

    @dataclasses.dataclass(frozen=True)
    class StagePreRegistration(LeverPreRegistration):
        external_pipelines: tuple[tuple[str, object], ...] = ()

    base = fx.make_prereg()
    fields = {f.name: getattr(base, f.name) for f in dataclasses.fields(base)}
    fields.update(
        reference_arm=REFERENCE,
        families=(FamilySpec("answer_usable", "decisional", (EXTERNAL,), 0.05),),
        descriptive_arms=(),
        null_guard_arms=(EXTERNAL,),
    )
    return StagePreRegistration(
        **fields, external_pipelines=((EXTERNAL, fx.external_pipeline()),)
    )


@dataclasses.dataclass
class S0:
    """A tmp S0 corpus, run directory and external arm export."""

    qs: fx.Questions
    gold: Path
    run: Path
    export: Path

    @property
    def journal(self) -> Path:
        return self.run / "journal.jsonl"


def _pipeline_config(**changes: object) -> dict[str, Any]:
    """`pipeline_config.json` as `baselines/llamaindex` writes it."""
    echo: dict[str, Any] = {
        **dataclasses.asdict(fx.external_pipeline()),
        "splitter": {"type": "SentenceSplitter", "chunk_size": 256},
        "embedding": {"model": "voyageai/voyage-4-large"},
        "documents": 346,
        "chunks": 4000,
        "index_fingerprint": fx.EXTERNAL_FINGERPRINT,
    }
    echo.update(changes)
    return echo


def _write_export(
    directory: Path, rows: Sequence[dict[str, Any]], config: dict[str, Any] | None
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / CONTEXT_EXPORT_FILE
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    if config is not None:
        (directory / "pipeline_config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
    return path


@pytest.fixture
def s0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, preregistered_clean_tree: str
) -> S0:
    """Three G questions; the Lancet arm already driven, as `run` leaves it."""
    qs = fx.make_questions(3, 0)
    root = tmp_path / "repo"
    gold = fx.write_corpus(root, qs, (REFERENCE, EXTERNAL))
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr(thresholds, fx.TOKEN, _s0_prereg(), raising=False)
    # The fixture split records placeholder input hashes (levers_fixture.write_corpus).
    monkeypatch.setattr("lancet_eval.run.split_input_problems", lambda *_a: [])
    run = tmp_path / "run"
    journal = Journal(run / "journal.jsonl")
    journal.write_header(
        corpus=fx.CORPUS,
        partial=True,
        gate_stage=None,
        max_retries=2,
        order_seed=42,
        split_sha256=_split_sha(root),
        context_export=True,
    )
    lancet = [
        fx.make_record(REFERENCE, q, fx.Spec(), qs).model_copy(
            update={"correlation_id": f"trace-{q}"}
        )
        for q in qs.g_ids
    ]
    for rec in lancet:
        journal.append(rec)
    fx.write_external_export(run, lancet)
    rows = [fx.make_evidence_export_row(EXTERNAL, q, qs) for q in qs.g_ids]
    export = _write_export(tmp_path / "llamaindex", rows, _pipeline_config())
    return S0(qs=qs, gold=gold, run=run, export=export)


def _split_sha(root: Path) -> str:
    from lancet_eval.split import load_split, split_sha256

    return split_sha256(load_split(root / "eval" / "corpora" / "levers" / "split.json"))


class FakeBin:
    """Answers as `generate_from_context` does; records each call."""

    def __init__(
        self,
        *,
        errors: dict[str, str] | None = None,
        drop: Sequence[str] = (),
        model: str | None = None,
    ) -> None:
        self.calls: list[tuple[str, list[str], list[str]]] = []
        self.errors = errors or {}
        self.drop = set(drop)
        default_model, self.order = _engine_generation()
        self.model = model or default_model

    def __call__(
        self, mode: str, rows: Sequence[ContextExportRow], levers: Sequence[str]
    ) -> list[dict[str, Any]]:
        self.calls.append((mode, [r.question_id for r in rows], list(levers)))
        lines = []
        for row in rows:
            if row.question_id in self.drop:
                continue
            line: dict[str, Any] = {
                "question_id": row.question_id,
                "arm": row.arm,
                "outcome": "success",
            }
            if mode == "pack":
                line["body"] = json.dumps({
                    "model": self.model,
                    "messages": [{"role": "user", "content": row.question}],
                    "provider": {"order": self.order, "require_parameters": True},
                })
            elif row.question_id in self.errors:
                line = {
                    **line,
                    "outcome": "error",
                    "error_type": "GENERATION_FAILED",
                    "error": self.errors[row.question_id],
                }
            else:
                line.update(
                    answer="Acme bought Globex [1].\nAnswer: Yes",
                    final_answer="Yes",
                    citations=["[1]"],
                    structured_citations=[],
                    notices=[{"code": "X", "message": "m", "severity": 1}],
                    answer_basis="ANSWER_BASIS_EVIDENCE",
                    usage={
                        "prompt_tokens": 2000,
                        "completion_tokens": 40,
                        "total_tokens": 2040,
                    },
                )
            lines.append(line)
        return lines

    @property
    def generated(self) -> list[str]:
        return [q for mode, qids, _ in self.calls if mode == "generate" for q in qids]


def _run(s0: S0, fake: FakeBin, **kwargs: Any) -> external_run.ExternalRunResult:
    options: dict[str, Any] = {
        "corpus": fx.CORPUS,
        "arm": EXTERNAL,
        "export_path": s0.export,
        "journal_path": s0.journal,
        "runner": fake,
        "stage_spend_cap": OPEN_CAP,
    }
    return run_external(**{**options, **kwargs})


def _external_records(s0: S0) -> list[Any]:
    return [r for r in load_records(s0.journal) if r.graph_arm == EXTERNAL]


def test_three_rows_become_three_external_records_that_score_accepts(s0: S0) -> None:
    fake = FakeBin()

    result = _run(s0, fake)

    assert result.appended == 3
    records = _external_records(s0)
    assert [r.question_id for r in records] == s0.qs.g_ids
    model, order = _engine_generation()
    for rec in records:
        assert rec.outcome == "success"
        assert rec.answer.splitlines()[-1] == "Answer: Yes"
        assert rec.snapshot is None, "no engine snapshot is faked (D-247)"
        assert rec.external is not None
        assert rec.external.pipeline == fx.external_pipeline()
        assert rec.external.index_fingerprint == fx.EXTERNAL_FINGERPRINT
        assert rec.external.generation_model == model
        assert rec.external.generation_provider_order == order
        assert rec.workflow_meta is not None
        assert rec.workflow_meta.prompt_tokens == 2000
    report = score_run(run_dir=s0.run, no_judge=True, gold_chunks_path=s0.gold)
    assert EXTERNAL in report.metadata.arm_labels


def test_the_reader_runs_with_the_metadata_lever_only(s0: S0) -> None:
    fake = FakeBin()

    _run(s0, fake)

    assert {tuple(levers) for _, _, levers in fake.calls} == {("evidence_metadata",)}


def test_generation_model_and_provider_come_from_the_sent_body(s0: S0) -> None:
    _run(s0, FakeBin(model="other/model"))

    assert {r.external.generation_model for r in _external_records(s0)} == {
        "other/model"
    }


def test_the_arm_rows_join_the_run_export_beside_the_lancet_rows(s0: S0) -> None:
    _run(s0, FakeBin())

    rows = read_export(s0.run / CONTEXT_EXPORT_FILE)
    assert sorted((r.arm, r.question_id) for r in rows) == sorted(
        (arm, q) for arm in (REFERENCE, EXTERNAL) for q in s0.qs.g_ids
    )
    lancet = [r for r in rows if r.arm == REFERENCE]
    assert all(r.assembled_prompt is not None for r in lancet)


def _checkpoints(s0: S0) -> InMemoryCheckpointSource:
    """The Lancet arm's `terminal_success` checkpoints, as Postgres would hold them."""
    rows = []
    for row in read_export(s0.run / CONTEXT_EXPORT_FILE):
        if row.arm != REFERENCE:
            continue
        snapshot = {
            "trace_id": row.correlation_id,
            "original_query": row.question,
            "evidence_blocks": [
                {**e.model_dump(), "evidence_meta": e.document_metadata.model_dump()}
                for e in row.evidence
            ],
            "graph_facts": row.graph_facts,
            "assembled_prompt": row.assembled_prompt,
        }
        rows.append(CheckpointRow(trace_id=row.correlation_id or "", snapshot=snapshot))
    return InMemoryCheckpointSource(rows)


def test_the_end_of_drive_export_of_a_shared_journal_keeps_the_external_rows(
    s0: S0,
) -> None:
    _run(s0, FakeBin())
    source = _checkpoints(s0)
    before = {(r.question_id, r.arm): r for r in read_export(s0.export)}

    write_context_export(s0.journal, source)

    rows = read_export(s0.run / CONTEXT_EXPORT_FILE)
    assert len(rows) == 6
    for row in rows:
        if row.arm == EXTERNAL:
            assert row == before[(row.question_id, row.arm)]
        else:
            assert row.correlation_id == f"trace-{row.question_id}"
    score_run(run_dir=s0.run, no_judge=True, gold_chunks_path=s0.gold)


def test_cli_export_context_rebuilds_a_shared_journal_export(
    s0: S0, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lancet_eval.context_export as context_export_mod

    _run(s0, FakeBin())
    source = _checkpoints(s0)
    export = s0.run / CONTEXT_EXPORT_FILE
    expected = sorted((r.question_id, r.arm) for r in read_export(export))
    # Only the external rows survive; the Lancet rows come back from the checkpoints.
    parity.write_rows(read_export(s0.export), export)
    monkeypatch.setattr(
        context_export_mod, "PostgresCheckpointSource", lambda settings: source
    )

    result = CliRunner().invoke(app, ["export-context", "--run", str(s0.run)])

    assert result.exit_code == 0, result.output
    assert sorted((r.question_id, r.arm) for r in read_export(export)) == expected


def test_the_end_of_drive_export_fails_closed_on_an_external_record_without_a_row(
    s0: S0,
) -> None:
    _run(s0, FakeBin())
    export = s0.run / CONTEXT_EXPORT_FILE
    dropped = (s0.qs.g_ids[1], EXTERNAL)
    kept = [r for r in read_export(export) if (r.question_id, r.arm) != dropped]
    parity.write_rows(kept, export)

    with pytest.raises(ContextExportError, match=f"{s0.qs.g_ids[1]}/{EXTERNAL}"):
        write_context_export(s0.journal, _checkpoints(s0))


def test_a_second_invocation_resumes_and_appends_nothing(s0: S0) -> None:
    _run(s0, FakeBin())
    before = s0.journal.read_bytes()
    again = FakeBin()

    result = _run(s0, again)

    assert result.appended == 0
    assert again.generated == []
    assert s0.journal.read_bytes() == before
    assert len(read_export(s0.run / CONTEXT_EXPORT_FILE)) == 6


def test_a_resume_drives_only_the_questions_not_yet_done(s0: S0) -> None:
    _run(s0, FakeBin(drop=[s0.qs.g_ids[2]]))
    # A dropped line still becomes a record; drop it from the journal to simulate a
    # crash before the third record was written.
    lines = s0.journal.read_text(encoding="utf-8").splitlines(keepends=True)
    s0.journal.write_text("".join(lines[:-1]), encoding="utf-8")
    again = FakeBin()

    result = _run(s0, again)

    assert result.appended == 1
    assert again.generated == [s0.qs.g_ids[2]]


def test_a_failed_bin_call_keeps_the_batches_journalled_before_it(
    s0: S0, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(external_run, "GENERATE_BATCH_ROWS", 1)
    inner = FakeBin()

    def timing_out(
        mode: str, rows: Sequence[ContextExportRow], levers: Sequence[str]
    ) -> list[dict[str, Any]]:
        if mode == "generate" and rows[0].question_id == s0.qs.g_ids[1]:
            raise parity.PromptParityError("generate_from_context generate failed")
        return inner(mode, rows, levers)

    with pytest.raises(ExternalRunError, match="generate failed"):
        _run(s0, timing_out)  # type: ignore[arg-type]

    assert [r.question_id for r in _external_records(s0)] == [s0.qs.g_ids[0]]
    rows = read_export(s0.run / CONTEXT_EXPORT_FILE)
    assert sum(r.arm == EXTERNAL for r in rows) == 3
    again = FakeBin()
    assert _run(s0, again).appended == 2
    assert again.generated == s0.qs.g_ids[1:]


def test_no_resume_refuses_a_journal_that_holds_records(s0: S0) -> None:
    fake = FakeBin()
    with pytest.raises(JournalReuseError):
        _run(s0, fake, resume=False)
    assert fake.calls == []


def test_a_reader_failure_becomes_an_error_record(s0: S0) -> None:
    failing = s0.qs.g_ids[1]

    _run(s0, FakeBin(errors={failing: "provider returned 502"}))

    records = {r.question_id: r for r in _external_records(s0)}
    assert len(records) == 3
    error = records[failing]
    assert error.outcome == "error"
    assert error.error_type == "GENERATION_FAILED"
    assert error.error == "provider returned 502"
    assert error.external is None


def test_a_row_the_bin_wrote_no_line_for_becomes_an_error_record(s0: S0) -> None:
    missing = s0.qs.g_ids[0]

    _run(s0, FakeBin(drop=[missing]))

    records = {r.question_id: r for r in _external_records(s0)}
    assert records[missing].outcome == "error"
    assert "no output line" in (records[missing].error or "")


def _refused(s0: S0, match: str, **kwargs: Any) -> None:
    fake = FakeBin()
    before = s0.journal.read_bytes()
    with pytest.raises(ExternalRunError, match=match):
        _run(s0, fake, **kwargs)
    assert fake.calls == [], "refused before any reader call"
    assert s0.journal.read_bytes() == before


def test_an_export_that_fails_validation_is_refused(s0: S0) -> None:
    rows = [fx.make_evidence_export_row(EXTERNAL, q, s0.qs) for q in s0.qs.g_ids]
    rows[1]["evidence"][0]["rank"] = 2
    _write_export(s0.export.parent, rows, None)
    _refused(s0, "context-export contract")


def test_an_export_row_without_eight_entries_is_refused(s0: S0) -> None:
    rows = [fx.make_evidence_export_row(EXTERNAL, q, s0.qs) for q in s0.qs.g_ids]
    rows[2]["evidence"] = rows[2]["evidence"][:7]
    _write_export(s0.export.parent, rows, None)
    _refused(s0, "7 ranked evidence entries")


def test_an_export_row_of_another_arm_or_an_unknown_question_is_refused(
    s0: S0,
) -> None:
    rows = [fx.make_evidence_export_row(EXTERNAL, q, s0.qs) for q in s0.qs.g_ids]
    rows.append(fx.make_evidence_export_row(EXTERNAL, "lv-zzz", s0.qs))
    _write_export(s0.export.parent, rows, None)
    _refused(s0, "lv-zzz")

    rows = [fx.make_evidence_export_row(REFERENCE, q, s0.qs) for q in s0.qs.g_ids]
    _write_export(s0.export.parent, rows, None)
    _refused(s0, "arm")


def test_an_arm_outside_the_corpus_arm_list_is_refused(s0: S0) -> None:
    fx.write_corpus(s0.gold.parent, s0.qs, (REFERENCE, "hybrid"), name="other_corpus")
    fake = FakeBin()
    with pytest.raises(ExternalRunError, match="not an arm of corpus"):
        run_external(
            corpus="other_corpus",
            arm=EXTERNAL,
            export_path=s0.export,
            journal_path=s0.run / "other" / "journal.jsonl",
            runner=fake,
            stage_spend_cap=OPEN_CAP,
        )
    assert fake.calls == []


def test_an_engine_arm_is_refused(s0: S0) -> None:
    _refused(s0, "not an external arm", arm=REFERENCE)


def test_a_missing_or_incomplete_pipeline_config_is_refused(s0: S0) -> None:
    config = s0.export.parent / "pipeline_config.json"
    config.unlink()
    _refused(s0, "pipeline_config.json")

    echo = _pipeline_config()
    del echo["dense_top_k"]
    config.write_text(json.dumps(echo), encoding="utf-8")
    _refused(s0, "dense_top_k")


def test_a_run_export_row_that_differs_from_the_arm_export_is_refused(s0: S0) -> None:
    _run(s0, FakeBin())
    rows = [fx.make_evidence_export_row(EXTERNAL, q, s0.qs) for q in s0.qs.g_ids]
    rows[0]["evidence"][3]["text"] = "a re-indexed passage"
    _write_export(s0.export.parent, rows, _pipeline_config())
    _refused(s0, rf"{s0.qs.g_ids[0]}/{EXTERNAL}")


def test_a_journal_from_another_split_is_refused(s0: S0) -> None:
    text = s0.journal.read_text(encoding="utf-8").splitlines(keepends=True)
    header = json.loads(text[0])
    header["split_sha256"] = "f" * 64
    s0.journal.write_text(json.dumps(header) + "\n" + "".join(text[1:]), "utf-8")
    fake = FakeBin()
    with pytest.raises(ValueError, match="not started under this split"):
        _run(s0, fake)
    assert fake.calls == []


def test_a_gate_stage_journal_is_refused(s0: S0) -> None:
    text = s0.journal.read_text(encoding="utf-8").splitlines(keepends=True)
    header = json.loads(text[0])
    header.update(gate_stage="S0-gate", max_retries=0)
    s0.journal.write_text(json.dumps(header) + "\n" + "".join(text[1:]), "utf-8")
    _refused(s0, "gate-stage")


def test_a_new_journal_gets_a_v1_1_header(s0: S0) -> None:
    journal = s0.run / "fresh" / "journal.jsonl"

    run_external(
        corpus=fx.CORPUS,
        arm=EXTERNAL,
        export_path=s0.export,
        journal_path=journal,
        runner=FakeBin(),
        stage_spend_cap=OPEN_CAP,
    )

    header = read_journal_header(journal)
    assert header is not None
    assert header["context_export"] is True
    assert header["corpus"] == fx.CORPUS
    assert header["split_sha256"] == _split_sha(s0.gold.parent)


def test_cli_run_external_appends_and_reports(
    s0: S0, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBin()
    monkeypatch.setattr(external_run, "bin_runner", fake)
    runner = CliRunner()

    ok = runner.invoke(
        app,
        [
            "run-external",
            "--corpus",
            fx.CORPUS,
            "--arm",
            EXTERNAL,
            "--export",
            str(s0.export),
            "--out",
            str(s0.journal),
            "--stage-cap",
            str(OPEN_CAP),
        ],
    )

    assert ok.exit_code == 0, ok.output
    assert "3" in ok.output
    assert len(_external_records(s0)) == 3

    bad = runner.invoke(
        app,
        [
            "run-external",
            "--corpus",
            fx.CORPUS,
            "--arm",
            REFERENCE,
            "--export",
            str(s0.export),
            "--out",
            str(s0.journal),
            "--stage-cap",
            str(OPEN_CAP),
        ],
    )
    assert bad.exit_code == 1
    assert "not an external arm" in bad.output


# --- The stage spend cap (#46, D-86) -------------------------------------------------


def _spend(s0: S0) -> float:
    return compute_spend(load_records(s0.journal))[0]


def test_the_drive_stops_at_the_cap_and_keeps_the_finished_batches(
    s0: S0, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(external_run, "GENERATE_BATCH_ROWS", 1)
    # The Lancet arm's records already count; one more batch reaches the cap.
    cap = _spend(s0) + 1e-9
    fake = FakeBin()

    result = _run(s0, fake, stage_spend_cap=cap)

    assert result.stopped_by_cap
    assert result.appended == 1
    assert fake.generated == [s0.qs.g_ids[0]]
    assert [r.question_id for r in _external_records(s0)] == [s0.qs.g_ids[0]]
    assert result.observed_spend == pytest.approx(_spend(s0))
    assert result.observed_spend >= cap
    rows = read_export(s0.run / CONTEXT_EXPORT_FILE)
    assert sum(r.arm == EXTERNAL for r in rows) == 3


def test_a_spend_already_at_the_cap_sends_nothing(s0: S0) -> None:
    fake = FakeBin()

    result = _run(s0, fake, stage_spend_cap=_spend(s0))

    assert result.stopped_by_cap
    assert result.appended == 0
    assert fake.calls == []
    assert _external_records(s0) == []


def test_a_resume_under_a_raised_cap_continues(
    s0: S0, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(external_run, "GENERATE_BATCH_ROWS", 1)
    assert _run(s0, FakeBin(), stage_spend_cap=_spend(s0) + 1e-9).stopped_by_cap
    again = FakeBin()

    result = _run(s0, again, stage_spend_cap=OPEN_CAP)

    assert not result.stopped_by_cap
    assert result.appended == 2
    assert again.generated == s0.qs.g_ids[1:]
    assert [r.question_id for r in _external_records(s0)] == s0.qs.g_ids


def test_a_complete_drive_is_not_labelled_capped(s0: S0) -> None:
    result = _run(s0, FakeBin())
    assert not result.stopped_by_cap
    assert result.observed_spend == pytest.approx(_spend(s0))

    # Nothing is left to send, so a cap below the spend stops nothing.
    again = _run(s0, FakeBin(), stage_spend_cap=_spend(s0) / 2)
    assert not again.stopped_by_cap
    assert again.appended == 0


@pytest.mark.parametrize("cap", [0.0, -1.0, float("nan"), float("inf")])
def test_a_cap_that_cannot_fire_is_refused_before_any_call(s0: S0, cap: float) -> None:
    before = s0.journal.read_bytes()
    fake = FakeBin()

    with pytest.raises(ExternalRunError, match="stage spend cap"):
        _run(s0, fake, stage_spend_cap=cap)

    assert fake.calls == []
    assert s0.journal.read_bytes() == before
    rows = read_export(s0.run / CONTEXT_EXPORT_FILE)
    assert not any(r.arm == EXTERNAL for r in rows)


def _cli(s0: S0, *cap: str) -> Any:
    return CliRunner().invoke(
        app,
        [
            "run-external",
            "--corpus",
            fx.CORPUS,
            "--arm",
            EXTERNAL,
            "--export",
            str(s0.export),
            "--out",
            str(s0.journal),
            *cap,
        ],
    )


@pytest.mark.parametrize("cap", [[], ["--stage-cap", "0"], ["--stage-cap", "nan"]])
def test_cli_run_external_refuses_a_missing_or_invalid_cap(
    s0: S0, monkeypatch: pytest.MonkeyPatch, cap: list[str]
) -> None:
    fake = FakeBin()
    monkeypatch.setattr(external_run, "bin_runner", fake)

    result = _cli(s0, *cap)

    assert result.exit_code == 2, result.output
    assert fake.calls == []
    assert _external_records(s0) == []


def test_cli_run_external_says_it_stopped_at_the_cap(
    s0: S0, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBin()
    monkeypatch.setattr(external_run, "bin_runner", fake)

    result = _cli(s0, "--stage-cap", repr(_spend(s0)))

    assert result.exit_code == 0, result.output
    assert "stage spend cap" in result.output
    assert fake.calls == []


# --- Integration (seam S-C): the real bin, the loopback provider stub ---------------


@pytest.fixture
def stub_reader(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Points the bin's reader at a loopback `provider_stub`; never at OpenRouter.

    The stub answers as the configured generation model, so the records carry the
    model and provider order `score` compares with config.toml.
    """
    from lancet_eval.provider_stub import run_server

    model, _ = _engine_generation()
    server = run_server(
        host="127.0.0.1",
        port=0,
        model_id=model,
        vectors_path=None,
        embed_delay_ms=0,
        chat_delay_ms=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("OPENROUTER_API_KEY", "stub-key")
    monkeypatch.setenv("LANCET_OPENROUTER__CHAT_ENDPOINT", f"{base}/chat/completions")
    monkeypatch.setenv("LANCET_OPENROUTER__MODEL_METADATA_ENDPOINT", f"{base}/models")
    yield base
    server.shutdown()
    server.server_close()


@integration
def test_s_c_the_real_bin_over_three_rows_writes_records_score_accepts(
    s0: S0, stub_reader: str
) -> None:
    result = run_external(
        corpus=fx.CORPUS,
        arm=EXTERNAL,
        export_path=s0.export,
        journal_path=s0.journal,
        stage_spend_cap=OPEN_CAP,
    )

    assert result.appended == 3
    records = _external_records(s0)
    assert [r.outcome for r in records] == ["success"] * 3, [r.error for r in records]
    assert all(r.answer.splitlines()[-1].startswith("Answer:") for r in records)
    score_run(run_dir=s0.run, no_judge=True, gold_chunks_path=s0.gold)

    again = run_external(
        corpus=fx.CORPUS,
        arm=EXTERNAL,
        export_path=s0.export,
        journal_path=s0.journal,
        stage_spend_cap=OPEN_CAP,
    )
    assert again.appended == 0
