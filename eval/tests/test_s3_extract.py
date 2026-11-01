"""S3's writer extraction over the 2Wiki passages (#145, step 4).

No test sends a request: the batch client is a fake.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lancet_eval import s3_extract as s3
from lancet_eval import thresholds
from lancet_eval import writer_pilot as wp
from lancet_eval.batch_client import BatchResult, BatchResults, ReaderOutput
from lancet_eval.measure import BATCH_PRICE_FACTOR

PRE = thresholds.PREREGISTRATION_S3_WRITERS
PASSAGES = [
    {"title": "Teutberga", "text": "Teutberga was a queen of Lotharingia."},
    {"title": "Shima (film)", "text": "Shima is a 2007 film."},
    {"title": "Obata Toramori", "text": "He was the father of Obata Masamori."},
]


def test_every_passage_is_one_chunk_in_file_order() -> None:
    chunks = s3.passage_chunks(PASSAGES)
    assert [c.custom_id for c in chunks] == ["tw-0000", "tw-0001", "tw-0002"]
    assert chunks[2].text == "Obata Toramori\nHe was the father of Obata Masamori."
    assert chunks[1].title == "Shima (film)"
    # No length floor: the 30-byte unit is kept (PREREGISTRATION_S3_WRITERS.unit).
    assert len(chunks[1].text.encode()) < wp.MIN_CHUNK_CONTENT_LENGTH


def test_custom_ids_sort_in_submission_order() -> None:
    """fetch_batch assigns a chunk to a batch by its custom_id range."""
    ids = [s3.custom_id(i) for i in range(PRE.passage_count)]
    assert ids == sorted(ids)


def test_the_writers_are_the_preregistrations() -> None:
    writers = s3.writers()
    assert list(writers) == [name for name, _ in PRE.writers]
    for name, declaration in PRE.writers:
        if name == "deepseek":
            assert writers[name].declaration is None
        else:
            assert writers[name].declaration == declaration
            assert writers[name].price_factor == BATCH_PRICE_FACTOR
        assert writers[name].price == declaration.price


def test_opus_gets_the_engine_body_rewritten_at_effort_low() -> None:
    (chunk,) = s3.passage_chunks(PASSAGES[:1])
    body = json.loads(wp.writer_body(s3.writers()["opus-5.5"], chunk.text))
    assert body["model"] == "anthropic/claude-opus-5.5"
    assert body["provider"] == {"only": ["anthropic"], "allow_fallbacks": False}
    assert body["reasoning"] == {"effort": "low"}
    assert body["messages"][1]["content"] == wp.USER_PREFIX + chunk.text
    assert "temperature" not in body and "top_p" not in body


def test_deepseek_is_not_submitted_as_a_batch(tmp_path: Path) -> None:
    with pytest.raises(wp.PilotError, match="deepseek"):
        wp.submit_batch(
            s3.writers()["deepseek"], s3.passage_chunks(PASSAGES), None, tmp_path
        )


def _record(cid: str, prompt: int, completion: int, **extra: object) -> dict:
    return {
        "custom_id": cid,
        "status": "succeeded",
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": 0,
        "finish_reason": "stop",
        "content": '{"entities": [], "relations": []}',
        "is_byok": True,
        "provider": "Anthropic",
    } | extra


def test_the_token_model_is_fitted_and_capped() -> None:
    chunks = [
        wp.PilotChunk(f"c{i}", 0, i, "", "", "word " * n)
        for i, n in enumerate((10, 20, 30))
    ]
    results = {
        "c0": _record("c0", 600, 100),
        "c1": _record("c1", 610, 200),
        "c2": _record("c2", 620, 300),
    }
    model = s3.TokenModel.fit(chunks, results)
    assert model.cap == 300
    assert model.completion(s3.o200k("word " * 20)) == pytest.approx(200, abs=1)
    assert model.completion(10_000) == 300


def test_the_estimate_prices_input_and_capped_output() -> None:
    model = s3.TokenModel(overhead=500.0, intercept=100.0, slope=0.0, cap=100)
    writer = s3.writers()["sonnet-5.5"]
    chunks = s3.passage_chunks(PASSAGES)
    usd, prompt, completion = s3.estimate(writer, chunks, model)
    assert completion == 300
    assert prompt == sum(500 + s3.o200k(c.text) for c in chunks)
    assert usd == pytest.approx((prompt * 2.0 + completion * 10.0) * 0.5 / 1e6)


def test_the_summary_counts_runaways_invalid_answers_and_routing() -> None:
    chunks = s3.passage_chunks(PASSAGES)
    results = {
        "tw-0000": _record("tw-0000", 600, 100, reasoning_tokens=7),
        "tw-0001": _record(
            "tw-0001", 600, 16_384, finish_reason="length", content=" " * 50
        ),
        "tw-0002": {"custom_id": "tw-0002", "status": "errored", "error": "x"},
    }
    summary = s3.summarise(s3.writers()["haiku-5.5"], chunks, results)
    assert summary["passages"] == 3
    assert summary["succeeded"] == 2
    assert summary["errored"] == 1
    assert summary["runaways"] == ["tw-0001"]
    assert summary["schema_invalid"] == 1
    assert summary["reasoning_tokens"] == 7
    assert summary["routing_breaks"] == []
    assert summary["thinking"] == "off"


def test_fetch_writes_results_from_the_fake_batch(tmp_path: Path) -> None:
    chunks = s3.passage_chunks(PASSAGES)
    wp.write_chunks(tmp_path, chunks)
    writer = s3.writers()["haiku-5.5"]

    class Fake:
        endpoint = "https://fake.test/batches"

        def submit(self, requests):
            self.sent = list(requests)
            return "batch-1"

        def results(self, batch_id):
            output = ReaderOutput(
                content='{"entities": [], "relations": []}',
                finish_reason="stop",
                prompt_tokens=600,
                completion_tokens=50,
                total_tokens=650,
                model="anthropic/claude-haiku-5.5",
                provider="Anthropic",
                is_byok=True,
                reasoning_tokens=0,
                content_block_types=None,
            )
            return BatchResults([
                BatchResult(r.custom_id, "succeeded", output=output) for r in self.sent
            ])

    fake = Fake()
    wp.submit_batch(writer, chunks, fake, tmp_path, echo=lambda _: None)
    assert wp.fetch_batch(writer, fake, tmp_path, echo=lambda _: None)
    results = wp.read_results(tmp_path / "haiku-5.5.results.jsonl")
    assert sorted(results) == ["tw-0000", "tw-0001", "tw-0002"]


def test_a_missing_reasoning_count_is_counted_not_subtracted() -> None:
    chunks = s3.passage_chunks(PASSAGES[:2])
    results = {
        "tw-0000": _record("tw-0000", 600, 100, reasoning_tokens=-1),
        "tw-0001": _record("tw-0001", 600, 100, reasoning_tokens=5),
    }
    summary = s3.summarise(s3.writers()["sonnet-5.5"], chunks, results)
    assert summary["reasoning_tokens"] == 5
    assert summary["reasoning_missing"] == 1


def test_a_refetch_keeps_earlier_succeeded_answers(tmp_path: Path) -> None:
    path = tmp_path / "opus-5.5.results.jsonl"
    good = _record("tw-0000", 600, 100)
    path.write_text(json.dumps(good) + "\n", encoding="utf-8")
    before = wp.read_results(path)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"custom_id": "tw-0000", "status": "expired"}) + "\n")
    assert s3.keep_succeeded(path, before) == 1
    assert wp.read_results(path)["tw-0000"] == good
    assert s3.keep_succeeded(path, wp.read_results(path)) == 0


def test_pending_skips_the_submitted_parts(tmp_path: Path) -> None:
    wp.write_chunks(tmp_path, s3.passage_chunks(PASSAGES))
    writer = s3.writers()["opus-5.5"]
    assert len(s3._pending(tmp_path, writer)) == 3
    (tmp_path / "opus-5.5.batch.json").write_text(
        json.dumps({"batches": [{"requests": 2}]}), encoding="utf-8"
    )
    assert [c.custom_id for c in s3._pending(tmp_path, writer)] == ["tw-0002"]


# ---- deepseek through the sync API (D-290) ------------------------------------------


def test_deepseek_alone_runs_on_the_sync_api() -> None:
    assert s3.TRANSPORTS == {
        "deepseek": "openrouter_sync",
        "haiku-5.5": "openrouter_batch",
        "sonnet-5.5": "openrouter_batch",
        "opus-5.5": "openrouter_batch",
    }
    deepseek = s3.writers()["deepseek"]
    assert deepseek.price_factor == 1.0
    assert s3._slug(deepseek) == "deepseek/deepseek-v4-flash-0731"


def test_deepseek_sends_the_engine_body_once_per_unanswered_passage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunks = s3.passage_chunks(PASSAGES)
    wp.write_chunks(tmp_path, chunks)
    wp._append(
        tmp_path / "deepseek.results.jsonl",
        [_record("tw-0000", 100, 50, is_byok=False, provider="Wafer")],
    )
    sent: list[str] = []

    class FakeChat:
        def complete(self, request):
            sent.append(request.custom_id)
            assert request.body_json == wp.deepseek_body(
                chunks[int(request.custom_id[3:])].text
            )
            output = ReaderOutput(
                content='{"entities": [], "relations": []}',
                finish_reason="length" if request.custom_id == "tw-0002" else "stop",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                model="deepseek/deepseek-v4-flash-0731",
                provider="Wafer",
                is_byok=False,
                reasoning_tokens=0,
                content_block_types=None,
            )
            return BatchResult(request.custom_id, "succeeded", output=output)

    monkeypatch.setattr(s3.batch_client, "chat_client", FakeChat)
    monkeypatch.setattr(
        s3, "token_model", lambda out, w: (s3.TokenModel(100, 50, 0, 50), "test")
    )
    s3.deepseek(tmp_path, shard_index=0, shards=1)
    assert sent == ["tw-0001", "tw-0002"]
    summary = s3.summarise(
        s3.writers()["deepseek"],
        chunks,
        wp.read_results(tmp_path / "deepseek.results.jsonl"),
    )
    assert summary["succeeded"] == 3
    assert summary["runaways"] == ["tw-0002"]
    assert summary["routing_breaks"] == []
    assert summary["usd"] == pytest.approx((300 * 0.0448 + 150 * 0.30) / 1e6, abs=1e-4)


def test_shards_split_the_unanswered_passages_and_merge_back(tmp_path: Path) -> None:
    chunks = s3.passage_chunks(PASSAGES * 3)
    wp.write_chunks(tmp_path, chunks)
    deepseek = s3.writers()["deepseek"]
    wp._append(
        tmp_path / "deepseek.results.jsonl",
        [_record("tw-0000", 100, 50, is_byok=False)],
    )
    parts = [s3.shard(tmp_path, deepseek, i, 3) for i in range(3)]
    ids = [c.custom_id for _, part in parts for c in part]
    assert sorted(ids) == [c.custom_id for c in chunks[1:]]
    assert [w.name for w, _ in parts] == [f"deepseek.shard{i}" for i in range(3)]
    writer, part = parts[1]
    wp._append(
        tmp_path / f"{writer.name}.results.jsonl",
        [_record(c.custom_id, 100, 50, is_byok=False) for c in part],
    )
    merged = s3._results(tmp_path, "deepseek")
    assert set(merged) == {"tw-0000"} | {c.custom_id for c in part}
    assert len(s3._unanswered(tmp_path, deepseek)) == 9 - 1 - len(part)
    with pytest.raises(wp.PilotError, match="shard 3"):
        s3.shard(tmp_path, deepseek, 3, 3)
