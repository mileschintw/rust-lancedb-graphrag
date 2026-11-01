"""The S3 MultiHop-RAG writer grid (#148): chunks, reuse, pending sets, results.

No test sends a request: the batch client is a fake.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lancet_eval import writer_grid as wg
from lancet_eval import writer_pilot as wp
from lancet_eval.batch_client import BatchResult, BatchResults, ReaderOutput

ANSWER = json.dumps({
    "entities": [{"name": "OpenAI", "entity_type": "org"}],
    "relations": [],
})


def _output(byok: bool | None = True, provider: str = "Anthropic") -> ReaderOutput:
    return ReaderOutput(
        content=ANSWER,
        finish_reason="stop",
        prompt_tokens=300,
        completion_tokens=120,
        total_tokens=420,
        model="m",
        provider=provider,
        is_byok=byok,
        reasoning_tokens=0,
        content_block_types=None,
    )


def _chunk(cid: str, text: str = "x" * 60) -> wp.PilotChunk:
    doc, chunk = cid.split("-")
    return wp.PilotChunk(cid, int(doc[1:]), int(chunk[1:]), "A", "Wire", text)


def _ok(cid: str, **kw) -> dict:
    return wp.result_record(
        BatchResult(cid, "succeeded", output=_output(**kw)), "batch-pilot"
    )


class FakeBatch:
    endpoint = "https://fake.test/batches"

    def __init__(self) -> None:
        self.submitted: list[list] = []
        self.results_by_id: dict[str, BatchResults] = {}

    def submit(self, requests):
        self.submitted.append(list(requests))
        return f"batch-{len(self.submitted)}"

    def results(self, batch_id):
        return self.results_by_id.get(batch_id)


def test_grid_chunks_cover_every_document_with_pilot_ids() -> None:
    docs = [
        {"title": "A", "source": "Wire", "body": "short\n\n" + "x" * 60},
        {"title": "B", "source": "Wire", "body": "y" * 60},
    ]
    assert [c.custom_id for c in wg.grid_chunks(docs)] == ["d000-c001", "d001-c000"]


def test_the_grid_has_four_writers_and_opus_at_effort_low() -> None:
    assert list(wg.WRITERS) == ["deepseek", "haiku-5.5", "sonnet-5.5", "opus-5.5"]
    opus = wg.WRITERS["opus-5.5"]
    body = json.loads(wp.writer_body(opus, "some chunk text"))
    assert body["model"] == "anthropic/claude-opus-5.5"
    assert body["provider"] == {"only": ["anthropic"], "allow_fallbacks": False}
    assert body["reasoning"] == {"effort": "low"}
    assert opus.price_factor == wp.WRITERS["sonnet-5.5"].price_factor
    assert (opus.price.input_per_mtok, opus.price.output_per_mtok) == (4.0, 20.0)


def _pilot(tmp_path: Path, chunks, records) -> Path:
    pilot = tmp_path / "pilot"
    wp.write_chunks(pilot, chunks)
    with (pilot / "haiku-5.5.results.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return pilot


def test_reuse_copies_succeeded_rows_of_identical_chunks(tmp_path: Path) -> None:
    grid = [_chunk("d000-c000"), _chunk("d000-c001"), _chunk("d001-c000")]
    failed = {"custom_id": "d000-c001", "status": "errored", "error": "e"}
    pilot = _pilot(tmp_path, grid[:2], [_ok("d000-c000"), failed])
    out = tmp_path / "grid"
    wp.write_chunks(out, grid)
    assert wg.reuse(wg.WRITERS["haiku-5.5"], pilot, out) == 1
    reused = wp.read_results(out / "haiku-5.5.reused.jsonl")
    assert list(reused) == ["d000-c000"]
    assert reused["d000-c000"]["reused_from"] == "pilot"


def test_reuse_refuses_a_chunk_whose_text_differs(tmp_path: Path) -> None:
    pilot = _pilot(tmp_path, [_chunk("d000-c000", "a" * 60)], [_ok("d000-c000")])
    out = tmp_path / "grid"
    wp.write_chunks(out, [_chunk("d000-c000", "b" * 60)])
    with pytest.raises(wp.PilotError, match="text differs"):
        wg.reuse(wg.WRITERS["haiku-5.5"], pilot, out)


def test_reuse_refuses_a_routing_break(tmp_path: Path) -> None:
    pilot = _pilot(tmp_path, [_chunk("d000-c000")], [_ok("d000-c000", byok=False)])
    out = tmp_path / "grid"
    wp.write_chunks(out, [_chunk("d000-c000")])
    with pytest.raises(wp.PilotError, match="is_byok"):
        wg.reuse(wg.WRITERS["haiku-5.5"], pilot, out)


def test_pending_is_frozen_at_first_use_and_skips_reused(tmp_path: Path) -> None:
    out = tmp_path
    wp.write_chunks(out, [_chunk("d000-c000"), _chunk("d000-c001")])
    with (out / "haiku-5.5.reused.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps(_ok("d000-c000")) + "\n")
    w = wg.WRITERS["haiku-5.5"]
    assert [c.custom_id for c in wg.pending(w, out)] == ["d000-c001"]
    # Later reuse does not move a frozen pending set.
    (out / "haiku-5.5.reused.jsonl").unlink()
    assert [c.custom_id for c in wg.pending(w, out)] == ["d000-c001"]


def test_batches_cover_only_pending_and_errors_stay_inside_the_part(
    tmp_path: Path,
) -> None:
    out = tmp_path
    grid = [_chunk("d000-c000"), _chunk("d000-c001"), _chunk("d000-c002")]
    wp.write_chunks(out, grid)
    with (out / "haiku-5.5.reused.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps(_ok("d000-c001")) + "\n")
    w = wg.WRITERS["haiku-5.5"]
    client = FakeBatch()
    wg.submit(w, client, out, echo=lambda _: None)
    assert [r.custom_id for r in client.submitted[0]] == ["d000-c000", "d000-c002"]
    client.results_by_id["batch-1"] = BatchResults([
        BatchResult("d000-c000", "succeeded", output=_output())
    ])
    assert wg.fetch(w, client, out, echo=lambda _: None)
    results = wg.results(w, out)
    # The reused chunk sits inside the part's first..last range but keeps its row.
    assert results["d000-c001"]["status"] == "succeeded"
    assert results["d000-c001"]["batch_id"] == "batch-pilot"
    assert results["d000-c000"]["batch_id"] == "batch-1"
    assert results["d000-c002"]["status"] == "errored"


def test_results_prefer_a_succeeded_row(tmp_path: Path) -> None:
    out = tmp_path
    wp.write_chunks(out, [_chunk("d000-c000")])
    w = wg.WRITERS["sonnet-5.5"]
    with (out / "sonnet-5.5.reused.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps(_ok("d000-c000")) + "\n")
    work = out / "sonnet-5.5"
    work.mkdir()
    err = {
        "custom_id": "d000-c000",
        "status": "errored",
        "batch_id": "b2",
        "error": "e",
    }
    (work / "sonnet-5.5.results.jsonl").write_text(json.dumps(err) + "\n", "utf-8")
    assert wg.results(w, out)["d000-c000"]["status"] == "succeeded"


def test_an_estimate_freezes_no_pending_set(tmp_path: Path) -> None:
    wp.write_chunks(tmp_path, [_chunk("d000-c000")])
    w = wg.WRITERS["opus-5.5"]
    assert len(wg.pending(w, tmp_path, freeze=False)) == 1
    assert not (tmp_path / "opus-5.5" / "chunks.jsonl").exists()


def test_opus_is_a_spot_check_on_the_pilots_chunks(tmp_path: Path) -> None:
    pilot = tmp_path / "pilot"
    wp.write_chunks(pilot, [_chunk("d001-c000")])
    out = tmp_path / "grid"
    wp.write_chunks(out, [_chunk("d000-c000"), _chunk("d001-c000")])
    opus, sonnet = wg.WRITERS["opus-5.5"], wg.WRITERS["sonnet-5.5"]
    assert wg.scope(sonnet, pilot) is None
    client = FakeBatch()
    wg.submit(opus, client, out, echo=lambda _: None, only=wg.scope(opus, pilot))
    assert [r.custom_id for r in client.submitted[0]] == ["d001-c000"]


def test_a_pilot_writer_without_its_reused_file_is_refused(tmp_path: Path) -> None:
    wp.write_chunks(tmp_path, [_chunk("d000-c000")])
    with pytest.raises(wp.PilotError, match="plan --pilot"):
        wg.pending(wg.WRITERS["sonnet-5.5"], tmp_path)


def test_shards_split_the_unanswered_chunks_and_results_merge_them(
    tmp_path: Path,
) -> None:
    out = tmp_path
    chunks = [_chunk(f"d000-c{i:03d}") for i in range(5)]
    wp.write_chunks(out, chunks)
    (out / "deepseek.reused.jsonl").write_text("", encoding="utf-8")
    ds = wg.WRITERS["deepseek"]
    work = out / "deepseek"
    work.mkdir()
    done = _ok("d000-c000", byok=False)
    (work / "deepseek.results.jsonl").write_text(json.dumps(done) + "\n", "utf-8")
    parts = [wg.shard(ds, out, i, 2) for i in range(2)]
    ids = [[c.custom_id for c in chunks] for _, chunks in parts]
    assert ids == [["d000-c002", "d000-c004"], ["d000-c001", "d000-c003"]]
    assert [w.name for w, _ in parts] == ["deepseek.shard0", "deepseek.shard1"]
    row = _ok("d000-c003", byok=False)
    shard1 = work / "deepseek.shard1.results.jsonl"
    shard1.write_text(json.dumps(row) + "\n", "utf-8")
    assert sorted(wg.results(ds, out)) == ["d000-c000", "d000-c003"]
    with pytest.raises(wp.PilotError):
        wg.shard(ds, out, 2, 2)


def test_answers_keep_only_what_the_engine_accepts_and_runaways_count(
    tmp_path: Path,
) -> None:
    chunks = [_chunk("d000-c000", "a" * 60), _chunk("d000-c001", "b" * 60)]
    wp.write_chunks(tmp_path, chunks)
    good = _ok("d000-c000")
    runaway = _ok("d000-c001") | {"content": "   ", "finish_reason": "length"}
    with (tmp_path / "haiku-5.5.reused.jsonl").open("w", encoding="utf-8") as f:
        for r in (good, runaway):
            f.write(json.dumps(r) + "\n")
    w = wg.WRITERS["haiku-5.5"]
    assert wg.answers(w, tmp_path, chunks) == [{"text": "a" * 60, "content": ANSWER}]
    assert wg.runaways(wg.results(w, tmp_path).values()) == 1
