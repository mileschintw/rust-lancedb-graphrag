"""The writer pilot (#117): chunks, request bodies, runners and summary.

No test sends a request: the batch and sync clients are fakes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from lancet_eval import writer_pilot as wp
from lancet_eval.batch_client import (
    BatchRequest,
    BatchResult,
    BatchResults,
    ReaderOutput,
)
from lancet_eval.config import repo_root

EXTRACTION_RS = repo_root() / "engine" / "src" / "graph" / "extraction.rs"


# ---- chunks ----------------------------------------------------------------------


def test_short_paragraphs_are_one_chunk_each() -> None:
    text = "First paragraph.\n\nSecond paragraph.\n\n\n\nThird."
    assert wp.chunk_structure_aware(text) == [
        "First paragraph.\n\n",
        "Second paragraph.\n\n",
        "Third.",
    ]


def test_long_paragraph_splits_in_overlapping_windows() -> None:
    text = "".join(chr(ord("a") + i % 26) for i in range(1000))
    chunks = wp.chunk_structure_aware(text, size=500, overlap=50)
    assert [len(c) for c in chunks] == [500, 500, 100]
    assert chunks[1] == text[450:950]
    assert chunks[2] == text[900:]


def test_windows_count_chars_not_bytes() -> None:
    text = "é" * 600
    assert [len(c) for c in wp.chunk_structure_aware(text, 500, 50)] == [500, 150]


def test_a_heading_like_line_is_refused() -> None:
    with pytest.raises(wp.PilotError):
        wp.chunk_structure_aware("Title\n=====\n\nbody")
    with pytest.raises(wp.PilotError):
        wp.chunk_structure_aware("## Section\n\nbody")


def test_short_chunks_are_not_extracted() -> None:
    assert not wp.extractable("  " + "x" * 39 + "\n\n")
    assert wp.extractable("x" * 40)
    # Bytes, as the engine's `str::len`: 20 two-byte chars pass.
    assert wp.extractable("é" * 20)


def test_pilot_chunks_keep_engine_chunk_indices() -> None:
    docs = [
        {"title": "A", "source": "Wire", "body": "short\n\n" + "x" * 60},
        {"title": "B", "source": "Wire", "body": "y" * 60},
    ]
    chunks = wp.pilot_chunks(docs, [0, 1])
    assert [c.custom_id for c in chunks] == ["d000-c001", "d001-c000"]
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", c.custom_id) for c in chunks)


def test_selection_is_seeded_and_ordered() -> None:
    first = wp.select_documents(346)
    assert first == wp.select_documents(346)
    assert first == sorted(first) and len(set(first)) == wp.PILOT_DOCUMENTS


def test_the_corpus_has_no_heading_the_port_misses() -> None:
    docs = wp.load_documents()
    chunks = wp.pilot_chunks(docs, wp.select_documents(len(docs)))
    assert 30 <= len({c.doc_index for c in chunks}) <= 50


# ---- request bodies --------------------------------------------------------------


def test_prompt_and_limits_match_the_engine_source() -> None:
    source = EXTRACTION_RS.read_text(encoding="utf-8")
    assert f'let system_msg = "{wp.SYSTEM_MESSAGE}";' in source
    assert '"Extract entities and relationships:\\n\\nText:\\n{}"' in source
    assert "EXTRACTION_MAX_COMPLETION_TOKENS: usize = 16_384;" in source
    assert "MIN_CHUNK_CONTENT_LENGTH: usize = 40;" in source
    for limit in (
        '"maxLength": 128',
        '"maxLength": 64',
        '"maxItems": 32',
        '"maxItems": 64',
    ):
        assert limit in source
    assert '"name": "knowledge_graph_extraction"' in source
    assert '"reasoning": { "effort": "none" }' in source


def test_deepseek_body_is_the_engines_with_the_d271_pin() -> None:
    body = json.loads(wp.deepseek_body("Some text."))
    assert list(body) == [
        "model",
        "messages",
        "temperature",
        "top_p",
        "max_completion_tokens",
        "reasoning",
        "response_format",
        "provider",
    ]
    assert body["model"] == "deepseek/deepseek-v4-flash-0731"
    assert body["messages"][1]["content"] == wp.USER_PREFIX + "Some text."
    assert body["provider"] == {
        "order": ["wafer/us"],
        "allow_fallbacks": False,
        "max_price": {"prompt": 0.07, "completion": 0.45},
    }
    assert body["reasoning"] == {"effort": "none"}
    assert body["response_format"]["json_schema"]["strict"] is True


def test_claude_bodies_pin_anthropic_and_set_lowest_thinking() -> None:
    haiku = json.loads(wp.writer_body(wp.WRITERS[wp.HAIKU], "Some text."))
    sonnet = json.loads(wp.writer_body(wp.WRITERS[wp.SONNET], "Some text."))
    deepseek = json.loads(wp.deepseek_body("Some text."))
    for body in (haiku, sonnet):
        assert body["provider"] == {"only": ["anthropic"], "allow_fallbacks": False}
        assert "temperature" not in body and "top_p" not in body
        assert body["messages"] == deepseek["messages"]
        assert body["response_format"] == deepseek["response_format"]
        assert body["max_completion_tokens"] == 16_384
    assert haiku["model"] == "anthropic/claude-haiku-5.5"
    assert haiku["reasoning"] == {"enabled": False}
    assert sonnet["model"] == "anthropic/claude-sonnet-5.5"
    assert sonnet["reasoning"] == {"effort": "low"}


def test_estimate_prices_input_and_output() -> None:
    chunk = wp.PilotChunk("d000-c000", 0, 0, "A", "Wire", "x" * 100)
    text = wp.estimate(wp.WRITERS[wp.SONNET], [chunk], 400)
    assert "0.5 x $2.0/$10.0" in text and "1 chunk(s)" in text
    assert wp.usd(wp.WRITERS[wp.SONNET], 1_000_000, 0) == pytest.approx(1.0)
    assert wp.usd(wp.WRITERS[wp.DEEPSEEK], 0, 1_000_000) == pytest.approx(0.30)


# ---- runners ---------------------------------------------------------------------


def _output(
    content: str, *, byok: bool | None, provider: str = "Anthropic"
) -> ReaderOutput:
    return ReaderOutput(
        content=content,
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


ANSWER = json.dumps({
    "entities": [
        {"name": "OpenAI", "entity_type": "ORG"},
        {"name": "November", "entity_type": "DATE"},
        {"name": "TechCrunch", "entity_type": "ORG"},
    ],
    "relations": [
        {
            "source": "OpenAI",
            "target": "TechCrunch",
            "relation_type": "x",
            "confidence": 0.9,
        },
        {
            "source": "OpenAI",
            "target": "Nobody",
            "relation_type": "y",
            "confidence": 0.5,
        },
    ],
})


class FakeChat:
    endpoint = "https://fake.test/chat"

    def __init__(self, byok: bool | None) -> None:
        self.byok = byok
        self.sent: list[BatchRequest] = []

    def complete(self, request: BatchRequest) -> BatchResult:
        self.sent.append(request)
        return BatchResult(
            request.custom_id,
            "succeeded",
            output=_output(ANSWER, byok=self.byok, provider="Wafer"),
        )


class FakeBatch:
    """Batches in memory: each submit gets the next ID; `fail_at` refuses one submit."""

    endpoint = "https://fake.test/batches"

    def __init__(self, results: dict[str, BatchResults] | None = None) -> None:
        self._results = results or {}
        self.submitted: list[list[BatchRequest]] = []
        self.fail_at: int | None = None

    def submit(self, requests):
        if self.fail_at == len(self.submitted):
            self.fail_at = None
            raise RuntimeError("refused")
        self.submitted.append(list(requests))
        return f"batch-{len(self.submitted)}"

    def results(self, batch_id):
        return self._results.get(batch_id)


def _chunks(n: int) -> list[wp.PilotChunk]:
    return [
        wp.PilotChunk(f"d000-c{i:03d}", 0, i, "A", "TechCrunch", "x" * 60)
        for i in range(n)
    ]


def test_sync_run_resumes_and_writes_no_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret-value")
    chunks = _chunks(3)
    client = FakeChat(byok=False)
    wp.run_sync(
        wp.WRITERS[wp.DEEPSEEK], chunks[:2], client, tmp_path, echo=lambda _: None
    )
    wp.run_sync(wp.WRITERS[wp.DEEPSEEK], chunks, client, tmp_path, echo=lambda _: None)
    assert [r.custom_id for r in client.sent] == ["d000-c000", "d000-c001", "d000-c002"]
    text = (tmp_path / "deepseek.results.jsonl").read_text(encoding="utf-8")
    assert "sk-or-secret-value" not in text


def test_sync_run_stops_on_a_routing_break(tmp_path: Path) -> None:
    client = FakeChat(byok=False)  # a Claude writer must be BYOK
    with pytest.raises(wp.PilotError, match="routing break"):
        wp.run_sync(
            wp.WRITERS[wp.HAIKU], _chunks(3), client, tmp_path, echo=lambda _: None
        )
    assert len(client.sent) == 1


def test_batches_split_resume_and_refuse_a_second_submit(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(wp, "BATCH_PART", 2)
    chunks = _chunks(5)
    client = FakeBatch()
    client.fail_at = 1
    with pytest.raises(RuntimeError):
        wp.submit_batch(wp.WRITERS[wp.HAIKU], chunks, client, tmp_path, echo=print)
    assert [len(p) for p in client.submitted] == [2]
    # The rerun sends only the parts the manifest lacks.
    wp.submit_batch(wp.WRITERS[wp.HAIKU], chunks, client, tmp_path, echo=print)
    assert [len(p) for p in client.submitted] == [2, 2, 1]
    assert client.submitted[2][0].custom_id == "d000-c004"
    with pytest.raises(wp.PilotError, match="already submitted"):
        wp.submit_batch(wp.WRITERS[wp.HAIKU], chunks, client, tmp_path, echo=print)


def test_fetch_waits_for_every_batch_and_fills_gaps(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(wp, "BATCH_PART", 2)
    chunks = _chunks(4)
    wp.write_chunks(tmp_path, chunks)
    client = FakeBatch()
    wp.submit_batch(wp.WRITERS[wp.HAIKU], chunks, client, tmp_path, echo=print)
    ok = BatchResult("d000-c000", "succeeded", output=_output(ANSWER, byok=True))
    client._results = {"batch-1": BatchResults([ok])}
    assert not wp.fetch_batch(wp.WRITERS[wp.HAIKU], client, tmp_path, echo=print)
    assert not (tmp_path / "haiku-5.5.results.jsonl").exists()

    client._results["batch-2"] = BatchResults([], error="thinking refused")
    assert wp.fetch_batch(wp.WRITERS[wp.HAIKU], client, tmp_path, echo=print)
    results = wp.read_results(tmp_path / "haiku-5.5.results.jsonl")
    assert results["d000-c000"]["status"] == "succeeded"
    assert results["d000-c001"]["error"] == "no batch returned a result"
    assert results["d000-c002"]["error"] == "thinking refused"
    assert results["d000-c003"]["batch_id"] == "batch-2"


def test_staged_submit_and_fetch_of_the_first_part(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(wp, "BATCH_PART", 2)
    chunks = _chunks(5)
    wp.write_chunks(tmp_path, chunks)
    client = FakeBatch()
    wp.submit_batch(wp.WRITERS[wp.SONNET], chunks, client, tmp_path, limit=1)
    assert [len(p) for p in client.submitted] == [2]
    client._results = {"batch-1": BatchResults([])}
    assert wp.fetch_batch(wp.WRITERS[wp.SONNET], client, tmp_path, echo=print)
    results = wp.read_results(tmp_path / "sonnet-5.5.results.jsonl")
    assert sorted(results) == ["d000-c000", "d000-c001"]
    wp.submit_batch(wp.WRITERS[wp.SONNET], chunks, client, tmp_path)
    assert [len(p) for p in client.submitted] == [2, 2, 1]


def test_deepseek_has_no_batch(tmp_path: Path) -> None:
    with pytest.raises(wp.PilotError, match="D-278"):
        wp.submit_batch(wp.WRITERS[wp.DEEPSEEK], _chunks(1), FakeBatch(), tmp_path)


# ---- reading the answers ---------------------------------------------------------


def test_parse_refuses_what_the_engine_refuses() -> None:
    assert wp.parse_extraction(ANSWER)[0] is not None
    assert wp.parse_extraction('{"entities": [], "relations": [], "x": 1}')[0] is None
    relation = {"source": "a", "target": "b", "relation_type": "r", "confidence": 1.5}
    bad = json.dumps({"entities": [], "relations": [relation]})
    assert wp.parse_extraction(bad)[1].startswith("confidence")
    assert wp.parse_extraction('{"entities": [')[0] is None


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("November", "date"),
        ("Nov.", "date"),
        ("October 7, 2023", "date"),
        ("2023", "date"),
        ("Friday", "date"),
        ("TechCrunch", "publisher"),
        ("the verge", "publisher"),
        ("OpenAI", None),
        ("May Mobility", None),
    ],
)
def test_junk_kinds(name: str, kind: str | None) -> None:
    assert wp.junk_kind(name, ["TechCrunch", "The Verge"]) == kind


def test_summary_counts_tokens_cost_junk_and_overlap() -> None:
    chunks = _chunks(2)
    ok = wp.result_record(
        BatchResult("d000-c000", "succeeded", output=_output(ANSWER, byok=True)), "b"
    )
    failed = {
        "custom_id": "d000-c001",
        "status": "errored",
        "batch_id": "b",
        "error": "e",
    }
    results = {"d000-c000": ok, "d000-c001": failed}
    s = wp.summarise(
        wp.WRITERS[wp.SONNET],
        chunks,
        results,
        ["TechCrunch"],
        reference={"d000-c000": ok},
    )
    assert (s["answered"], s["valid"], s["missing"]) == (1, 1, 1)
    assert (s["entities"], s["relations"], s["dangling_relations"]) == (3, 2, 1)
    assert s["junk"] == {"date": 1, "publisher": 1}
    assert s["cost_usd"] == pytest.approx((300 * 2.0 + 120 * 10.0) * 0.5 / 1e6)
    assert s["entity_jaccard_vs_deepseek"] == pytest.approx(1.0)
    assert s["relation_pair_jaccard_vs_deepseek"] == pytest.approx(1.0)
    assert (s["model"], s["thinking"]) == (
        "anthropic/claude-sonnet-5.5",
        "on (effort low)",
    )
    assert s["is_byok"] == ["True"]


def test_relation_pairs_ignore_direction_and_type() -> None:
    a = {"relations": [{"source": "A", "target": "B", "relation_type": "x"}]}
    b = {"relations": [{"source": "b", "target": "a", "relation_type": "y"}]}
    assert wp._relation_pairs(a) == wp._relation_pairs(b)
