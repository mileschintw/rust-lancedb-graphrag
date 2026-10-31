"""Seam S-F (#52, D-257): a fixture S1 run and the S2 run replayed from it.

The S1 run holds the deepseek arm `BASE` (and a second engine arm that is not
replayed) with a context export. `replay-init` carries `BASE` into an S2 run; the
reader arm's records are then appended the way `batch fetch` (#53) will write them:
one replay record and one export row (the base row under the reader arm's label) per
question. Every record is provenance-clean unless a test changes it.

Built on `levers_fixture`, whose corpus, questions and engine records it reuses.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import levers_fixture as fx

from lancet_eval.context_export import CONTEXT_EXPORT_FILE, ContextExportRow
from lancet_eval.journal import Journal, ReplayProvenance, RunRecord, WorkflowWireMeta
from lancet_eval.reader_request import ReaderDeclaration, ReaderPrice, rewrite_pack_body
from lancet_eval.replay import export_row_sha256
from lancet_eval.thresholds import FamilySpec, StagePreRegistration

BASE = "hybrid+rerank+metadata"
OTHER = "hybrid"
READER = "haiku-5.5"
READER_ARM = f"{BASE}@{READER}"
BATCH_ID = "gen-batch-0001"
HAIKU = ReaderDeclaration(
    slug="anthropic/claude-haiku-5.5",
    target="openrouter",
    thinking="off",
    price=ReaderPrice(input_per_mtok=0.10, output_per_mtok=0.50),
)
OPUS = ReaderDeclaration(
    slug="anthropic/claude-opus-5.5",
    target="openrouter",
    thinking="on",
    effort="low",
    price=ReaderPrice(input_per_mtok=5.0, output_per_mtok=25.0),
)

_PACK_BODY = (
    (Path(__file__).parent / "fixtures" / "reader_request" / "pack_body.json")
    .read_text(encoding="utf-8")
    .rstrip("\r\n")
)


def pack_body(qid: str) -> str:
    """The fixture `pack` body with the question ID in its user message."""
    body = json.loads(_PACK_BODY)
    body["messages"][1]["content"] = (
        f"Question {qid}?\n{body['messages'][1]['content']}"
    )
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def write_s1_run(
    run_dir: Path,
    qs: fx.Questions,
    arms: Iterable[str] = (BASE, OTHER),
    *,
    spec_fn: fx.SpecFn = fx.default_spec,
) -> list[RunRecord]:
    """An S1 run: a context-export journal and one export row per success record."""
    journal = Journal(run_dir / "journal.jsonl")
    journal.write_header(corpus=fx.CORPUS, partial=False, context_export=True)
    records: list[RunRecord] = []
    rows: list[str] = []
    for qid in [*qs.g_ids, *qs.nulls]:
        for arm in arms:
            spec = spec_fn(arm, qid)
            rec = fx.make_record(arm, qid, spec, qs)
            journal.append(rec)
            records.append(rec)
            if not spec.errored:
                row = fx.make_evidence_export_row(arm, qid, qs, ranks=spec.ranks)
                rows.append(json.dumps(row) + fx.NL)
    (run_dir / CONTEXT_EXPORT_FILE).write_text("".join(rows), encoding="utf-8")
    return records


def read_rows(run_dir: Path) -> dict[tuple[str, str], ContextExportRow]:
    """The run's export rows by `(question_id, arm)`."""
    from lancet_eval.context_export import read_export

    return {
        (r.question_id, r.arm): r for r in read_export(run_dir / CONTEXT_EXPORT_FILE)
    }


def make_replay_record(
    qid: str,
    qs: fx.Questions,
    source_row: ContextExportRow,
    *,
    spec: fx.Spec = fx.Spec(),  # noqa: B008 - a frozen value
    reader: ReaderDeclaration = HAIKU,
    arm: str = READER_ARM,
    **changes: Any,
) -> RunRecord:
    """One reader-arm record for `qid`, provenance-clean unless `changes` say otherwise.

    `changes` replace fields of the replay block.
    """
    if spec.errored:
        return RunRecord(
            corpus=fx.CORPUS,
            question_id=qid,
            graph_arm=arm,
            outcome="error",
            error_type="batch_errored",
            error="boom",
        )
    kind = "abstain" if qid in qs.nulls and spec.kind == "ok" else spec.kind
    gold = "" if qid in qs.nulls else qs.gold[qid][1]
    body = pack_body(qid)
    request = rewrite_pack_body(body, reader)
    replay: dict[str, Any] = {
        "export_row_sha256": export_row_sha256(source_row),
        "pack_body": body,
        "sent_body_sha256": hashlib.sha256(
            request.body_json.encode("utf-8")
        ).hexdigest(),
        "rewritten_fields": list(request.rewritten_fields),
        "model": reader.slug,
        "provider": "Anthropic",
        "is_byok": True,
        "reasoning_tokens": 0,
        "batch_id": BATCH_ID,
    }
    replay.update(changes)
    return RunRecord(
        corpus=fx.CORPUS,
        question_id=qid,
        graph_arm=arm,
        outcome="success",
        answer=fx._answer(kind, gold),
        workflow_meta=WorkflowWireMeta(prompt_tokens=500, completion_tokens=40),
        replay=ReplayProvenance(**replay),
    )


ReplayFn = Callable[[str, fx.Questions, ContextExportRow], RunRecord]


def append_reader_arm(
    s2_run: Path,
    qs: fx.Questions,
    *,
    build: ReplayFn | None = None,
    row_fn: Callable[[ContextExportRow], ContextExportRow] | None = None,
    arm: str = READER_ARM,
) -> list[RunRecord]:
    """Appends the reader arm's records and export rows to a carried S2 run.

    Each row is the carried base row under the reader arm's label; `row_fn` may change
    it first.
    """
    rows = read_rows(s2_run)
    base = arm.partition("@")[0]

    def default(qid: str, qs: fx.Questions, row: ContextExportRow) -> RunRecord:
        return make_replay_record(qid, qs, row, arm=arm)

    journal = Journal(s2_run / "journal.jsonl")
    written: list[RunRecord] = []
    lines: list[str] = []
    for qid in [*qs.g_ids, *qs.nulls]:
        source = rows[(qid, base)]
        rec = (build or default)(qid, qs, source)
        journal.append(rec)
        written.append(rec)
        if rec.outcome == "success":
            row = source.model_copy(update={"arm": arm})
            if row_fn is not None:
                row = row_fn(row)
            lines.append(row.model_dump_json() + fx.NL)
    with open(s2_run / CONTEXT_EXPORT_FILE, "a", encoding="utf-8") as f:
        f.writelines(lines)
    return written


def s2_prereg(
    *,
    readers: tuple[tuple[str, ReaderDeclaration], ...] = ((READER, HAIKU),),
    arm: str = READER_ARM,
) -> StagePreRegistration:
    """A synthetic S2 stage constant: the deepseek arm against one reader arm."""
    base = fx.make_prereg()
    fields = {f.name: getattr(base, f.name) for f in dataclasses.fields(base)}
    fields.update(
        reference_arm=BASE,
        families=(FamilySpec("answer_usable", "decisional", (arm,), 0.05),),
        descriptive_arms=(),
        null_guard_arms=(arm,),
    )
    return StagePreRegistration(**fields, readers=readers)
