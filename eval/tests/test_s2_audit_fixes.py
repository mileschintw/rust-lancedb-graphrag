"""The audit-s2 findings on the S2 batch path (#133: L5, L6).

L6: a billed reader record that `render` rejected (an error record with a `replay`
block) is checked by the request and target clauses, so a misrouted request is found
even when its answer did not render. L5: `batch fetch` prints, per arm, how many of the
records it journalled break `is_byok` or the provider, so a misroute shows before the
other arms have spent.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import levers_fixture as fx
import pytest
import replay_fixture as rf

from lancet_eval import batch, provenance
from lancet_eval.preregistration import readers_of
from lancet_eval.reader_request import ReaderPrice

pytestmark = pytest.mark.usefixtures("preregistered_clean_tree")


def _render_rejected(qs: fx.Questions, **changes: object):  # type: ignore[no-untyped-def]
    def build(qid, qs_, row):  # type: ignore[no-untyped-def]
        rec = rf.make_replay_record(qid, qs_, row, **changes)
        return rec.model_copy(
            update={"outcome": "error", "error_type": "render", "answer": None}
        )

    return build


def _failures(run: Path) -> list[provenance.ProvenanceFailure]:
    from lancet_eval.context_export import read_export
    from lancet_eval.journal import load_records, read_journal_header
    from lancet_eval.pairing import deduplicate_by_arm
    from lancet_eval.replay import source_row_hashes

    records, _ = deduplicate_by_arm(load_records(run / "journal.jsonl"))
    rows = {
        (r.question_id, r.arm): r for r in read_export(run / "context_export.jsonl")
    }
    return provenance.replay_run_failures(
        records,
        export_rows=rows,
        source_row_sha256=source_row_hashes(read_journal_header(run / "journal.jsonl")),
        readers=readers_of(rf.s2_prereg()),
    )


@pytest.fixture
def carried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from lancet_eval import thresholds
    from lancet_eval.replay import replay_init

    qs = fx.make_questions(4, 1)
    root = tmp_path / "repo"
    rf.write_corpora(root, qs)
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr(thresholds, fx.TOKEN, rf.s2_prereg(), raising=False)
    s1 = tmp_path / "s1"
    rf.write_s1_run(s1, qs)
    run = tmp_path / "s2"
    replay_init(source_run=s1, arms=[rf.BASE], run=run, corpus=fx.CORPUS)
    return run, qs


def test_a_render_rejected_record_billed_off_byok_fails_its_target_clauses(
    carried,
) -> None:
    run, qs = carried
    rf.append_reader_arm(
        run, qs, build=_render_rejected(qs, is_byok=False, provider="Amazon Bedrock")
    )
    codes = {f.code for f in _failures(run)}
    assert {"is_byok", "provider"} <= codes
    assert "row_hash" not in codes  # a rejected answer has no reader row to check


def test_a_clean_render_rejected_record_passes(carried) -> None:
    run, qs = carried
    rf.append_reader_arm(run, qs, build=_render_rejected(qs))
    assert _failures(run) == []


def test_fetch_prints_per_arm_routing_mismatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_batch import _make_s2

    run, qs, _, client, _ = _make_s2(tmp_path, monkeypatch)
    batch.submit(run=run, arm=rf.READER_ARM, echo=lambda _: None)
    original = client.results

    def misrouted(batch_id):  # type: ignore[no-untyped-def]
        out = original(batch_id)
        first = out[0]
        out[0] = dataclasses.replace(
            first,
            output=dataclasses.replace(
                first.output, is_byok=False, provider="Amazon Bedrock"
            ),
        )
        return out

    client.results = misrouted  # type: ignore[method-assign]
    lines: list[str] = []
    batch.fetch(run=run, echo=lines.append)
    (summary,) = [line for line in lines if line.startswith("Routing")]
    assert rf.READER_ARM in summary
    assert f"1 of {len(qs.g_ids) + len(qs.nulls)}" in summary


# ---- D-277: deepseek's price is declared in the pre-registration -------------------

WAFER = ReaderPrice(input_per_mtok=0.0434, output_per_mtok=0.30)


def test_the_deepseek_row_and_replicates_read_the_declared_price(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import test_replicates as tr

    from lancet_eval import thresholds
    from lancet_eval.lever_comparison import build_lever_comparison
    from lancet_eval.replay import replay_init
    from lancet_eval.score import score_run

    qs = fx.make_questions(10, 5)
    root = tmp_path / "repo"
    gold = rf.write_corpora(root, qs)
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    prereg = dataclasses.replace(tr._prereg(), reference_price=WAFER)
    monkeypatch.setattr(thresholds, fx.TOKEN, prereg, raising=False)
    s1 = tmp_path / "s1"
    rf.write_s1_run(s1, qs)
    run = tmp_path / "s2"
    replay_init(source_run=s1, arms=[rf.BASE], run=run, corpus=fx.CORPUS)
    endpoint = tr.Endpoint({q: a for q, _, a in qs.g})
    monkeypatch.setattr(batch, "client_factory", lambda target: endpoint)
    monkeypatch.setattr(batch, "chat_client_factory", lambda: endpoint)
    monkeypatch.setattr(batch, "bin_runner", tr.PinnedBin())

    lines: list[str] = []
    batch.submit(run=run, arm=rf.BASE, echo=lines.append)
    assert any("$0.0434/$0.3 per MTok" in line for line in lines)
    batch.submit(run=run, arm=rf.READER_ARM, echo=lambda _: None)
    batch.fetch(run=run, echo=lambda _: None)
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    (group,) = build_lever_comparison(run, gold_chunks_path=gold)["reader_comparison"][
        "groups"
    ]
    deepseek = next(r for r in group["readers"] if r["arm"] == rf.BASE)
    assert deepseek["price"] == {
        "input_per_mtok": 0.0434,
        "output_per_mtok": 0.30,
        "source": "preregistration",
    }


# ---- B1, D-278: deepseek replicates through the sync chat-completions API ----------


class _Posts:
    """Stands in for `httpx.post`: answers each body as OpenRouter's chat API would,
    records what was posted, and can fail or stop at a given call."""

    def __init__(self, *, fail_at: int | None = None, stop_at: int | None = None):
        self.posts: list[tuple[str, bytes]] = []
        self.fail_at, self.stop_at = fail_at, stop_at

    def __call__(self, url, *, content, headers, timeout):  # type: ignore[no-untyped-def]
        import httpx

        self.posts.append((url, content))
        n = len(self.posts)
        if n == self.stop_at:
            raise KeyboardInterrupt  # a crash mid-run
        request = httpx.Request("POST", url)
        if n == self.fail_at:
            return httpx.Response(503, text="upstream busy", request=request)
        body = json.loads(content)
        reply = {
            "model": body["model"],
            "provider": "Wafer",
            "choices": [
                {
                    "message": {"content": "Based on the evidence.\nAnswer: Yes"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 500,
                "completion_tokens": 40,
                "total_tokens": 540,
                "is_byok": False,
                "completion_tokens_details": {"reasoning_tokens": 0},
            },
        }
        return httpx.Response(200, json=reply, request=request)


@pytest.fixture
def sync_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    import test_replicates as tr

    from lancet_eval import batch_client, thresholds
    from lancet_eval.replay import replay_init

    qs = fx.make_questions(4, 1)
    root = tmp_path / "repo"
    gold = rf.write_corpora(root, qs)
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr(thresholds, fx.TOKEN, tr._prereg(), raising=False)
    s1 = tmp_path / "s1"
    rf.write_s1_run(s1, qs)
    run = tmp_path / "s2"
    replay_init(source_run=s1, arms=[rf.BASE], run=run, corpus=fx.CORPUS)
    monkeypatch.setattr(batch, "bin_runner", tr.PinnedBin())
    monkeypatch.setattr(batch, "SYNC_CHUNK", 3)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    # The real client: only httpx is stubbed.
    monkeypatch.setattr(batch, "chat_client_factory", batch_client.chat_client)
    return run, qs, gold, tr


def _deepseek_units(run: Path) -> dict[tuple[str, int], object]:
    from lancet_eval.journal import load_records
    from lancet_eval.pairing import deduplicate_by_arm

    records, _ = deduplicate_by_arm(load_records(run / "journal.jsonl"))
    return {
        (r.question_id, r.replicate): r
        for r in records
        if r.graph_arm == rf.BASE and r.replicate > 1
    }


def test_deepseek_replicates_post_the_pinned_body_to_chat_completions(
    sync_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval import batch_client

    run, qs, gold, tr = sync_run
    posts = _Posts()
    monkeypatch.setattr(batch_client.httpx, "post", posts)
    lines: list[str] = []
    sent = batch.submit(run=run, arm=rf.BASE, echo=lines.append)

    n = (len(qs.g_ids) + len(qs.nulls)) * (tr.K - 1)
    assert len(posts.posts) == sent.requests == n
    assert {url for url, _ in posts.posts} == {batch_client.OPENROUTER_CHAT_URL}
    for _, content in posts.posts:
        body = json.loads(content)
        assert body["provider"] == tr.PIN  # D-271's pin, in full
    assert any(line.startswith("Cost estimate (D-258") for line in lines)
    assert lines.index(
        next(line for line in lines if line.startswith("Cost estimate"))
    ) < lines.index(next(line for line in lines if "sync" in line))
    assert any(line.startswith("Routing") and " 0 of " in line for line in lines)
    units = _deepseek_units(run)
    assert len(units) == n and all(r.outcome == "success" for r in units.values())
    assert batch.read_manifest(sent.manifest_path)["state"] == "fetched"
    assert batch.read_manifest(sent.manifest_path)["target"] == batch.SYNC_TARGET
    assert _failures_k(run, tr) == []


def _failures_k(run: Path, tr) -> list[provenance.ProvenanceFailure]:  # type: ignore[no-untyped-def]
    from lancet_eval.context_export import read_export
    from lancet_eval.journal import load_records, read_journal_header
    from lancet_eval.pairing import deduplicate_by_arm
    from lancet_eval.replay import source_row_hashes

    records, _ = deduplicate_by_arm(load_records(run / "journal.jsonl"))
    rows = {
        (r.question_id, r.arm): r for r in read_export(run / "context_export.jsonl")
    }
    header = read_journal_header(run / "journal.jsonl")
    return provenance.replay_run_failures(
        records,
        export_rows=rows,
        source_row_sha256=source_row_hashes(header),
        readers=readers_of(tr._prereg()),
    )


def test_a_failed_sync_request_is_a_retryable_error_record(
    sync_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval import batch_client

    run, qs, *_ = sync_run
    monkeypatch.setattr(batch_client.httpx, "post", _Posts(fail_at=2))
    batch.submit(run=run, arm=rf.BASE, echo=lambda _: None)
    errors = [r for r in _deepseek_units(run).values() if r.outcome == "error"]
    assert [r.error_type for r in errors] == [batch.RESULT_ERRORS["errored"]]

    again = _Posts()
    monkeypatch.setattr(batch_client.httpx, "post", again)
    batch.submit(run=run, arm=rf.BASE, retry_errors=True, echo=lambda _: None)
    assert len(again.posts) == 1
    assert all(r.outcome == "success" for r in _deepseek_units(run).values())


def test_a_crashed_sync_run_resumes_with_only_the_unrecorded_replicates(
    sync_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval import batch_client

    run, qs, _, tr = sync_run
    n = (len(qs.g_ids) + len(qs.nulls)) * (tr.K - 1)
    # The 5th post crashes: the first chunk of 3 is journalled, the 4th is lost.
    monkeypatch.setattr(batch_client.httpx, "post", _Posts(stop_at=5))
    with pytest.raises(KeyboardInterrupt):
        batch.submit(run=run, arm=rf.BASE, echo=lambda _: None)
    assert len(_deepseek_units(run)) == 3

    rest = _Posts()
    monkeypatch.setattr(batch_client.httpx, "post", rest)
    batch.submit(run=run, arm=rf.BASE, echo=lambda _: None)
    assert len(rest.posts) == n - 3
    assert len(_deepseek_units(run)) == n
    assert batch.fetch(run=run, echo=lambda _: None).pending == ()
