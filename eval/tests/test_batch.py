"""`batch submit` and `batch fetch` (#53, D-254) over seam S-F.

A fixture S1 run (`replay_fixture`) is carried into an S2 run by `replay-init`; the
reader arm is then submitted and fetched through a fake batch client and a fake bin
(`pack` emits the fixture body, `render` turns a result's content into the answer).
No test sends a request anywhere. The integration test at the end runs the real bin
and is skipped unless `LANCET_EVAL_INTEGRATION=1`.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import levers_fixture as fx
import pytest
import replay_fixture as rf
from typer.testing import CliRunner

from lancet_eval import batch, parity, thresholds
from lancet_eval.batch_client import (
    MISSING_REASONING_TOKENS,
    BatchRequest,
    BatchResult,
    ReaderOutput,
    _payload,
    anthropic_output,
    openrouter_output,
)
from lancet_eval.context_export import CONTEXT_EXPORT_FILE, ContextExportRow
from lancet_eval.journal import RunRecord, load_records
from lancet_eval.measure import compute_spend
from lancet_eval.pairing import deduplicate_by_arm
from lancet_eval.preregistration import readers_of
from lancet_eval.reader_request import rewrite_pack_body
from lancet_eval.replay import replay_init

ARM = rf.READER_ARM
REJECT = "REJECT"


# ---- fakes -----------------------------------------------------------------------


class FakeClient:
    """A batch endpoint in memory: each submit gets a batch ID, results on demand."""

    endpoint = "https://fake.test/api/v1/batches"

    def __init__(self) -> None:
        self.batches: dict[str, list[BatchRequest]] = {}
        self.events: list[str] = []
        #: question ID → status (default `succeeded`); content per question.
        self.status: dict[str, str] = {}
        self.content: dict[str, str] = {}
        self.processing = False
        self.drop: set[str] = set()

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        batch_id = f"batch-{len(self.batches) + 1}"
        self.batches[batch_id] = list(requests)
        self.events.append(f"submit {batch_id}")
        return batch_id

    def results(self, batch_id: str) -> list[BatchResult] | None:
        if self.processing:
            return None
        out: list[BatchResult] = []
        for req in self.batches[batch_id]:
            qid = req.custom_id
            if qid in self.drop:
                continue
            status = self.status.get(qid, "succeeded")
            if status != "succeeded":
                out.append(BatchResult(qid, status, error=f"{status} by the fake"))  # type: ignore[arg-type]
                continue
            out.append(
                BatchResult(
                    qid,
                    "succeeded",
                    output=ReaderOutput(
                        content=self.content.get(qid, f"Answer: {qid}"),
                        finish_reason="stop",
                        prompt_tokens=500,
                        completion_tokens=40,
                        total_tokens=540,
                        model=rf.HAIKU.slug,
                        provider="Anthropic",
                        is_byok=True,
                        reasoning_tokens=0,
                        content_block_types=None,
                    ),
                )
            )
        return out


class FakeBin:
    """`pack` emits the fixture body; `render` answers with each result's content."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], list[str]]] = []

    def __call__(
        self,
        mode: str,
        rows: Sequence[ContextExportRow],
        levers: Sequence[str],
        results: Sequence[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((mode, [r.question_id for r in rows], list(levers)))
        if mode == "pack":
            return [
                {
                    "question_id": r.question_id,
                    "arm": r.arm,
                    "outcome": "success",
                    "body": rf.pack_body(r.question_id),
                }
                for r in rows
            ]
        assert mode == "render" and results is not None
        by_key = {(x["question_id"], x["arm"]): x for x in results}
        lines = []
        for r in rows:
            content = by_key[(r.question_id, r.arm)]["content"]
            if content == REJECT:
                lines.append({
                    "question_id": r.question_id,
                    "arm": r.arm,
                    "outcome": "error",
                    "error_type": "NODE_ERROR_KIND_LLM_GENERATION_FAILED",
                    "error": "failed to deserialize ModelOutput schema",
                })
            else:
                lines.append({
                    "question_id": r.question_id,
                    "arm": r.arm,
                    "outcome": "success",
                    "answer": content,
                })
        return lines


# ---- the S-F run -----------------------------------------------------------------


def _with_correlation_ids(s1: Path) -> None:
    """Gives every S1 record and row its own correlation ID (the fixture's are "")."""
    for name in ("journal.jsonl", CONTEXT_EXPORT_FILE):
        path = s1 / name
        lines = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            data = json.loads(raw)
            if "question_id" in data:
                arm = data.get("graph_arm", data.get("arm"))
                data["correlation_id"] = f"corr-{data['question_id']}-{arm}"
            lines.append(json.dumps(data) + "\n")
        path.write_text("".join(lines), encoding="utf-8")


@pytest.fixture
def s2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """An S2 run carried from the fixture S1 run, the fakes installed."""
    return _make_s2(tmp_path, monkeypatch)


def _make_s2(tmp_path, monkeypatch, spec_fn=fx.default_spec):  # type: ignore[no-untyped-def]
    qs = fx.make_questions(6, 2)
    root = tmp_path / "repo"
    gold = rf.write_corpora(root, qs)
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr(thresholds, fx.TOKEN, rf.s2_prereg(), raising=False)
    s1 = tmp_path / "s1"
    rf.write_s1_run(s1, qs, spec_fn=spec_fn)
    _with_correlation_ids(s1)
    run = tmp_path / "s2"
    replay_init(source_run=s1, arms=[rf.BASE], run=run, corpus=fx.CORPUS)
    client, binary = FakeClient(), FakeBin()
    monkeypatch.setattr(batch, "client_factory", lambda target: client)
    monkeypatch.setattr(batch, "bin_runner", binary)
    for qid in qs.g_ids:
        client.content[qid] = fx._answer("ok", qs.gold[qid][1])
    return run, qs, gold, client, binary


def _reader(run: Path) -> list[RunRecord]:
    return [r for r in load_records(run / "journal.jsonl") if r.graph_arm == ARM]


def _latest(run: Path) -> dict[str, RunRecord]:
    records, _ = deduplicate_by_arm(_reader(run))
    return {r.question_id: r for r in records}


def _all(qs: fx.Questions) -> list[str]:
    return [*qs.g_ids, *qs.nulls]


# ---- acceptance criteria ---------------------------------------------------------


def test_submit_then_fetch_journals_one_record_per_question_that_scores(
    s2, preregistered_clean_tree
) -> None:
    from lancet_eval.score import score_run

    run, qs, gold, client, _ = s2
    sent = batch.submit(run=run, arm=ARM, echo=lambda _: None)
    assert sent.requests == len(_all(qs))
    assert [r.custom_id for r in client.batches[sent.batch_id]] == _all(qs)

    fetched = batch.fetch(run=run, echo=lambda _: None)

    assert (fetched.successes, fetched.errors, fetched.pending) == (
        len(_all(qs)),
        0,
        (),
    )
    reader = _reader(run)
    assert [r.question_id for r in reader] == _all(qs)
    base = {
        r.question_id: r
        for r in load_records(run / "journal.jsonl")
        if r.graph_arm == rf.BASE
    }
    for rec in reader:
        assert rec.outcome == "success" and rec.corpus == fx.CORPUS
        assert rec.correlation_id == base[rec.question_id].correlation_id != ""
        assert rec.session_id == sent.batch_id
        assert rec.replay is not None and rec.replay.batch_id == sent.batch_id
        assert rec.workflow_meta is not None
        assert (
            rec.workflow_meta.prompt_tokens,
            rec.workflow_meta.completion_tokens,
        ) == (
            500,
            40,
        )
    rows = rf.read_rows(run)
    for qid in _all(qs):
        assert rows[(qid, ARM)] == rows[(qid, rf.BASE)].model_copy(update={"arm": ARM})
    # The replay clauses, the export coverage (correlation_id) and completeness hold.
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    assert (run / "report.json").is_file()


def test_the_manifest_body_hashes_are_the_hashes_the_replay_clauses_check(s2) -> None:
    run, qs, _, client, _ = s2
    sent = batch.submit(run=run, arm=ARM, echo=lambda _: None)
    manifest = batch.read_manifest(sent.manifest_path)
    assert manifest["batch_id"] == sent.batch_id and manifest["state"] == "submitted"
    assert (manifest["endpoint"], manifest["model"]) == (
        FakeClient.endpoint,
        rf.HAIKU.slug,
    )
    for req in client.batches[sent.batch_id]:
        expected = rewrite_pack_body(rf.pack_body(req.custom_id), rf.HAIKU)
        digest = hashlib.sha256(expected.body_json.encode("utf-8")).hexdigest()
        assert req.body_json == expected.body_json
        assert manifest["requests"][req.custom_id]["body_sha256"] == digest

    batch.fetch(run=run, echo=lambda _: None)
    for qid, rec in _latest(run).items():
        assert rec.replay is not None
        assert rec.replay.sent_body_sha256 == manifest["requests"][qid]["body_sha256"]


def test_a_second_submit_refuses_while_the_arm_has_a_pending_batch(s2) -> None:
    run, _, _, client, _ = s2
    batch.submit(run=run, arm=ARM, limit=2, echo=lambda _: None)
    with pytest.raises(batch.BatchError, match="pending batch"):
        batch.submit(run=run, arm=ARM, echo=lambda _: None)
    assert len(client.batches) == 1


def test_a_batch_still_processing_journals_nothing_and_stays_pending(s2) -> None:
    run, _, _, client, _ = s2
    sent = batch.submit(run=run, arm=ARM, echo=lambda _: None)
    client.processing = True
    fetched = batch.fetch(run=run, echo=lambda _: None)
    assert fetched.pending == (sent.batch_id,) and _reader(run) == []
    with pytest.raises(batch.BatchError, match="pending"):
        batch.submit(run=run, arm=ARM, echo=lambda _: None)


def test_a_re_run_fetch_adds_nothing(s2) -> None:
    run, _, _, _, _ = s2
    batch.submit(run=run, arm=ARM, echo=lambda _: None)
    batch.fetch(run=run, echo=lambda _: None)
    journal = (run / "journal.jsonl").read_text(encoding="utf-8")
    export = (run / CONTEXT_EXPORT_FILE).read_text(encoding="utf-8")

    again = batch.fetch(run=run, echo=lambda _: None)

    assert (again.successes, again.errors) == (0, 0)
    assert (run / "journal.jsonl").read_text(encoding="utf-8") == journal
    assert (run / CONTEXT_EXPORT_FILE).read_text(encoding="utf-8") == export


def test_an_interrupted_fetch_journals_only_what_is_missing(s2) -> None:
    run, qs, _, _, _ = s2
    sent = batch.submit(run=run, arm=ARM, echo=lambda _: None)
    batch.fetch(run=run, echo=lambda _: None)
    # As if the fetch died after journalling: the manifest still says submitted.
    manifest = batch.read_manifest(sent.manifest_path)
    manifest["state"] = "submitted"
    sent.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    again = batch.fetch(run=run, echo=lambda _: None)

    assert (again.successes, again.errors) == (0, 0)
    assert len(_reader(run)) == len(_all(qs))


def test_errored_and_expired_requests_become_error_records_and_retry_resubmits_them(
    s2,
) -> None:
    run, qs, _, client, _ = s2
    errored, expired = qs.g_ids[1], qs.g_ids[3]
    client.status = {errored: "errored", expired: "expired"}
    batch.submit(run=run, arm=ARM, echo=lambda _: None)
    fetched = batch.fetch(run=run, echo=lambda _: None)

    assert (fetched.successes, fetched.errors) == (len(_all(qs)) - 2, 2)
    latest = _latest(run)
    assert latest[errored].error_type == "batch_errored"
    assert latest[expired].error_type == "batch_expired"
    for qid in (errored, expired):
        # Nothing was billed for them: no replay block, no export row.
        assert latest[qid].outcome == "error" and latest[qid].replay is None
        assert (qid, ARM) not in rf.read_rows(run)

    client.status = {}
    retry = batch.submit(run=run, arm=ARM, retry_errors=True, echo=lambda _: None)
    assert [r.custom_id for r in client.batches[retry.batch_id]] == [errored, expired]
    batch.fetch(run=run, echo=lambda _: None)
    assert all(r.outcome == "success" for r in _latest(run).values())
    assert (errored, ARM) in rf.read_rows(run)


def test_a_request_the_batch_returned_no_result_for_is_an_error_record(s2) -> None:
    run, qs, _, client, _ = s2
    client.drop = {qs.g_ids[0]}
    batch.submit(run=run, arm=ARM, echo=lambda _: None)
    batch.fetch(run=run, echo=lambda _: None)
    assert _latest(run)[qs.g_ids[0]].error_type == batch.NO_RESULT


def test_limit_3_submits_three_and_the_next_submit_takes_the_rest(s2) -> None:
    run, qs, _, client, _ = s2
    pilot = batch.submit(run=run, arm=ARM, limit=3, echo=lambda _: None)
    assert [r.custom_id for r in client.batches[pilot.batch_id]] == _all(qs)[:3]
    batch.fetch(run=run, echo=lambda _: None)
    assert all(r.partial for r in _reader(run))

    rest = batch.submit(run=run, arm=ARM, echo=lambda _: None)
    assert [r.custom_id for r in client.batches[rest.batch_id]] == _all(qs)[3:]


def test_submit_refuses_when_every_question_already_has_a_record(s2) -> None:
    run, qs, _, client, _ = s2
    client.status = {qs.g_ids[0]: "errored"}
    batch.submit(run=run, arm=ARM, echo=lambda _: None)
    batch.fetch(run=run, echo=lambda _: None)
    with pytest.raises(batch.BatchError, match="success record") as excinfo:
        batch.submit(run=run, arm=ARM, echo=lambda _: None)
    assert "--retry-errors" in str(excinfo.value)
    assert len(client.batches) == 1


def test_the_cost_estimate_is_printed_before_the_submit_and_does_not_block_it(
    s2,
) -> None:
    run, qs, _, client, _ = s2
    events = client.events

    batch.submit(run=run, arm=ARM, echo=lambda line: events.append(f"echo {line}"))

    assert events[0].startswith("echo Cost estimate (D-258")
    assert events[1] == "submit batch-1"
    # The fixture's deepseek records carry no usage: the estimate prices the bound.
    assert f"{len(_all(qs))} request(s) to {rf.HAIKU.slug}" in events[0]


def test_a_base_error_gets_one_reader_error_record_and_is_never_submitted(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from lancet_eval.score import score_run

    def spec_fn(arm: str, qid: str) -> fx.Spec:
        return fx.Spec(errored=qid == "lv-g002")

    run, qs, gold, client, _ = _make_s2(tmp_path, monkeypatch, spec_fn=spec_fn)
    sent = batch.submit(run=run, arm=ARM, echo=lambda _: None)
    assert sent.base_errors == 1
    assert "lv-g002" not in [r.custom_id for r in client.batches[sent.batch_id]]
    batch.fetch(run=run, echo=lambda _: None)

    latest = _latest(run)
    assert set(latest) == set(_all(qs))
    assert latest["lv-g002"].error_type == batch.BASE_ERROR
    with pytest.raises(batch.BatchError, match="nothing to submit"):
        batch.submit(run=run, arm=ARM, retry_errors=True, echo=lambda _: None)
    # Every question has a record under every arm, so the report is complete.
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    assert (run / "report.json").is_file()


def test_an_answer_render_rejects_keeps_its_replay_block_and_usage(s2) -> None:
    run, qs, _, client, _ = s2
    client.content[qs.g_ids[0]] = REJECT
    batch.submit(run=run, arm=ARM, echo=lambda _: None)
    batch.fetch(run=run, echo=lambda _: None)

    rec = _latest(run)[qs.g_ids[0]]
    assert rec.outcome == "error"
    assert rec.error_type == "NODE_ERROR_KIND_LLM_GENERATION_FAILED"
    assert rec.replay is not None and rec.workflow_meta is not None
    readers = readers_of(rf.s2_prereg())
    one, _ = compute_spend([rec], include_embeddings=False, readers=readers)
    assert one > 0
    assert (qs.g_ids[0], ARM) not in rf.read_rows(run)


def test_pack_and_render_run_under_the_base_records_levers(s2) -> None:
    run, _, _, _, binary = s2
    base = {
        r.question_id: r
        for r in load_records(run / "journal.jsonl")
        if r.graph_arm == rf.BASE
    }
    batch.submit(run=run, arm=ARM, echo=lambda _: None)
    batch.fetch(run=run, echo=lambda _: None)
    for mode, qids, levers in binary.calls:
        assert mode in {"pack", "render"}
        for qid in qids:
            snapshot = base[qid].snapshot
            assert snapshot is not None and levers == list(snapshot.levers)


def test_submit_refuses_a_row_whose_packed_prompt_differs(s2, monkeypatch) -> None:
    run, qs, _, client, binary = s2

    def pack(mode, rows, levers, results=None):  # type: ignore[no-untyped-def]
        lines = binary(mode, rows, levers, results)
        lines[0]["body"] = rf.pack_body("someone-else")
        return lines

    monkeypatch.setattr(batch, "bin_runner", pack)
    with pytest.raises(batch.BatchError, match="assembled_prompt"):
        batch.submit(run=run, arm=ARM, echo=lambda _: None)
    assert client.batches == {} and not (run / batch.MANIFEST_DIR).exists()


def test_submit_refuses_an_arm_that_is_not_a_declared_reader_arm(s2) -> None:
    run, _, _, _, _ = s2
    with pytest.raises(batch.BatchError, match="not a reader arm"):
        batch.submit(run=run, arm=rf.BASE, echo=lambda _: None)
    with pytest.raises(batch.BatchError, match="does not list"):
        batch.submit(run=run, arm=f"{rf.BASE}@sonnet-5.5", echo=lambda _: None)


def test_a_submit_the_endpoint_rejects_leaves_no_pending_batch(s2) -> None:
    from lancet_eval.batch_client import BatchClientError

    run, _, _, client, _ = s2

    def refuse(requests):  # type: ignore[no-untyped-def]
        raise BatchClientError("HTTP 400")

    client.submit = refuse  # type: ignore[method-assign]
    with pytest.raises(BatchClientError):
        batch.submit(run=run, arm=ARM, echo=lambda _: None)
    [path] = batch.manifest_paths(run, ARM)
    assert batch.read_manifest(path)["state"] == "rejected"
    del client.submit
    batch.submit(run=run, arm=ARM, echo=lambda _: None)


def test_the_cli_submits_and_fetches(s2) -> None:
    from lancet_eval.cli import app

    run, qs, _, _, _ = s2
    runner = CliRunner()
    sub = runner.invoke(app, ["batch", "submit", "--run", str(run), "--arm", ARM])
    assert sub.exit_code == 0, sub.output
    assert "Cost estimate" in sub.output and "batch-1" in sub.output
    again = runner.invoke(app, ["batch", "submit", "--run", str(run), "--arm", ARM])
    assert again.exit_code == 1 and "pending batch" in again.output
    got = runner.invoke(app, ["batch", "fetch", "--run", str(run), "--arm", ARM])
    assert got.exit_code == 0, got.output
    assert len(_reader(run)) == len(_all(qs))


# ---- check-prompt-parity skips reader rows ----------------------------------------


def test_prompt_parity_skips_reader_rows(s2) -> None:
    run, qs, _, _, _ = s2
    batch.submit(run=run, arm=ARM, echo=lambda _: None)
    batch.fetch(run=run, echo=lambda _: None)

    def packer(rows, levers):  # type: ignore[no-untyped-def]
        return FakeBin()("pack", rows, levers)

    result = parity.check_prompt_parity(run, packer=packer)
    assert result == parity.ParityResult(
        checked=len(_all(qs)), external=0, readers=len(_all(qs))
    )


# ---- response normalisation -------------------------------------------------------


def test_an_openrouter_response_normalises_with_its_provider_and_reasoning() -> None:
    out = openrouter_output({
        "model": "anthropic/claude-haiku-5.5",
        "provider": "Anthropic",
        "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 900,
            "completion_tokens": 40,
            "total_tokens": 940,
            "is_byok": True,
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    })
    assert (out.model, out.provider, out.is_byok, out.reasoning_tokens) == (
        "anthropic/claude-haiku-5.5",
        "Anthropic",
        True,
        0,
    )
    assert (out.prompt_tokens, out.completion_tokens, out.total_tokens) == (
        900,
        40,
        940,
    )
    assert out.content_block_types is None


def test_an_openrouter_response_without_a_reasoning_count_fails_closed() -> None:
    out = openrouter_output({
        "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })
    assert out.reasoning_tokens == MISSING_REASONING_TOKENS
    assert out.is_byok is None and out.provider == ""


def test_an_anthropic_message_normalises_to_chat_completions_values() -> None:
    out = anthropic_output({
        "model": "claude-sonnet-5-5",
        "stop_reason": "end_turn",
        "content": [
            {"type": "text", "text": '{"answer":'},
            {"type": "text", "text": "1}"},
        ],
        "usage": {"input_tokens": 900, "output_tokens": 40},
    })
    assert out.content == '{"answer":1}' and out.finish_reason == "stop"
    assert (out.prompt_tokens, out.completion_tokens, out.total_tokens) == (
        900,
        40,
        940,
    )
    assert (out.provider, out.is_byok, out.reasoning_tokens) == (
        "api.anthropic.com",
        None,
        0,
    )
    assert out.content_block_types == ("text", "text")
    assert (
        anthropic_output({
            "stop_reason": "max_tokens",
            "content": [],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }).finish_reason
        == "length"
    )


def test_the_payload_embeds_each_body_byte_for_byte() -> None:
    body = rewrite_pack_body(rf.pack_body("q-1"), rf.HAIKU).body_json
    payload = _payload([BatchRequest("q-1", body)], "body").decode()
    assert f'"body":{body}}}' in payload
    assert json.loads(payload) == {
        "requests": [{"custom_id": "q-1", "body": json.loads(body)}]
    }


def test_an_openrouter_response_with_null_content_keeps_its_usage() -> None:
    out = openrouter_output({
        "choices": [{"message": {"content": None}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 1, "total_tokens": 10},
    })
    assert out.content == "" and out.prompt_tokens == 9


def test_a_response_that_cannot_be_read_is_unreadable_not_errored() -> None:
    from lancet_eval.batch_client import _anthropic_result, _openrouter_result

    assert _openrouter_result({"custom_id": "q", "response": {}}).status == (
        "unreadable"
    )
    assert _anthropic_result({
        "custom_id": "q",
        "result": {"type": "succeeded", "message": {"content": "x"}},
    }).status == ("unreadable")
    assert _openrouter_result({"custom_id": "q", "error": {"message": "x"}}).status == (
        "errored"
    )


def test_retry_errors_leaves_billed_answers_render_rejected_or_unreadable(s2) -> None:
    run, qs, _, client, _ = s2
    rejected, unreadable, errored = qs.g_ids[0], qs.g_ids[1], qs.g_ids[2]
    client.content[rejected] = REJECT
    client.status = {unreadable: "unreadable", errored: "errored"}
    batch.submit(run=run, arm=ARM, echo=lambda _: None)
    batch.fetch(run=run, echo=lambda _: None)
    latest = _latest(run)
    assert latest[unreadable].error_type == "batch_unreadable_response"

    client.status = {}
    retry = batch.submit(run=run, arm=ARM, retry_errors=True, echo=lambda _: None)

    assert [r.custom_id for r in client.batches[retry.batch_id]] == [errored]


def test_a_refused_submit_journals_nothing(tmp_path, monkeypatch) -> None:
    def spec_fn(arm: str, qid: str) -> fx.Spec:
        return fx.Spec(errored=qid == "lv-g002")

    run, _, _, _, binary = _make_s2(tmp_path, monkeypatch, spec_fn=spec_fn)
    journal = (run / "journal.jsonl").read_text(encoding="utf-8")

    def pack(mode, rows, levers, results=None):  # type: ignore[no-untyped-def]
        raise parity.PromptParityError("generate_from_context pack exited 101")

    monkeypatch.setattr(batch, "bin_runner", pack)
    with pytest.raises(batch.BatchError, match="exited 101"):
        batch.submit(run=run, arm=ARM, echo=lambda _: None)
    assert (run / "journal.jsonl").read_text(encoding="utf-8") == journal


# ---- integration: the real bin ----------------------------------------------------

integration = pytest.mark.skipif(
    os.environ.get("LANCET_EVAL_INTEGRATION") != "1",
    reason="integration test: set LANCET_EVAL_INTEGRATION=1 to build and run the "
    "generate_from_context bin (pack and render; no network)",
)


@integration
def test_pack_rewrite_fake_submit_render_with_the_built_bin() -> None:
    from lancet_eval.batch_client import openrouter_output as normalise
    from lancet_eval.provider_stub import build_chat_completion_response

    row = ContextExportRow.model_validate({
        "corpus": "multihop_rag",
        "question_id": "q1",
        "arm": rf.BASE,
        "question": "Who bought Globex?",
        "evidence": [
            {
                "rank": 1,
                "chunk_id": "doc-a:0",
                "document_id": "doc-a",
                "text": "Acme announced that it will buy Globex.",
                "title": "acme-globex.md",
                "section_path": "Root",
                "content_type": "text/markdown",
                "score": 0.9,
                "suspicious": False,
                "document_metadata": {
                    "source": "The Verge",
                    "doc_title": "Acme to buy Globex",
                    "published_date": "2023-10-02",
                },
            }
        ],
        "graph_facts": [],
    })
    levers = ["evidence_metadata"]
    [packed] = parity.run_bin("pack", [row], levers)
    assert packed["outcome"] == "success", packed
    request = rewrite_pack_body(packed["body"], rf.HAIKU)

    client = FakeClient()
    batch_id = client.submit([BatchRequest("q1", request.body_json)])
    assert client.batches[batch_id][0].body_json == request.body_json

    response = build_chat_completion_response(900)
    response["usage"]["completion_tokens_details"] = {"reasoning_tokens": 0}
    out = normalise(response)
    reader_row = row.model_copy(update={"arm": ARM})
    [line] = parity.run_bin(
        "render", [reader_row], levers, [batch.render_line("q1", ARM, out)]
    )
    assert line["outcome"] == "success", line
    assert line["arm"] == ARM
    assert line["answer"].splitlines()[-1].startswith("Answer:")
