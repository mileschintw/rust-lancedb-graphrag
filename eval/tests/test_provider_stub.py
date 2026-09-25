"""Tests for the loopback-only OpenRouter provider stub (06.3.4.1-07 Task 2)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from lancet_eval.provider_stub import (
    HostNotAllowedError,
    StubStats,
    assert_loopback_host,
    build_chat_completion_response,
    build_embeddings_response,
    build_models_response,
    delay_for_call,
    embedding_for,
    hash_vector,
    load_vector_map,
    run_server,
)


# --- assert_loopback_host -----------------------------------------------------------------


def test_assert_loopback_host_allows_127_0_0_1():
    assert_loopback_host("127.0.0.1")  # does not raise


def test_assert_loopback_host_allows_ipv6_loopback():
    assert_loopback_host("::1")  # does not raise


def test_assert_loopback_host_rejects_non_loopback():
    with pytest.raises(HostNotAllowedError):
        assert_loopback_host("0.0.0.0")


def test_assert_loopback_host_rejects_public_ip():
    with pytest.raises(HostNotAllowedError):
        assert_loopback_host("203.0.113.5")


def test_run_server_refuses_non_loopback_before_binding():
    with pytest.raises(HostNotAllowedError):
        run_server(
            host="0.0.0.0",
            port=0,
            model_id="test-model",
            vectors_path=None,
            embed_delay_ms=0,
            chat_delay_ms=0,
        )


# --- hash_vector -----------------------------------------------------------------------


def test_hash_vector_is_deterministic():
    v1 = hash_vector("some question text")
    v2 = hash_vector("some question text")
    assert v1 == v2


def test_hash_vector_differs_for_different_text():
    v1 = hash_vector("question A")
    v2 = hash_vector("question B")
    assert v1 != v2


def test_hash_vector_has_configured_dimensions():
    v = hash_vector("x", dimensions=2048)
    assert len(v) == 2048


def test_hash_vector_is_unit_normalized():
    v = hash_vector("normalize me")
    norm = sum(x * x for x in v) ** 0.5
    assert abs(norm - 1.0) < 1e-6


# --- load_vector_map / embedding_for ----------------------------------------------------


def test_load_vector_map_reads_jsonl(tmp_path: Path):
    path = tmp_path / "vectors.jsonl"
    path.write_text(
        json.dumps({"text": "hello", "embedding": [0.1, 0.2, 0.3]}) + "\n", encoding="utf-8"
    )
    vmap = load_vector_map(path)
    assert vmap["hello"] == [0.1, 0.2, 0.3]


def test_load_vector_map_missing_file_returns_empty(tmp_path: Path):
    assert load_vector_map(tmp_path / "nope.jsonl") == {}


def test_load_vector_map_none_path_returns_empty():
    assert load_vector_map(None) == {}


def test_embedding_for_uses_map_when_present():
    vmap = {"known question": [1.0, 2.0]}
    vec, from_map = embedding_for("known question", vmap, dimensions=2)
    assert vec == [1.0, 2.0]
    assert from_map is True


def test_embedding_for_falls_back_to_hash_when_absent():
    vec, from_map = embedding_for("unknown question", {}, dimensions=16)
    assert from_map is False
    assert len(vec) == 16


# --- build_models_response ----------------------------------------------------------------


def test_build_models_response_includes_configured_model_id():
    resp = build_models_response("my-model")
    assert resp["data"][0]["id"] == "my-model"


def test_build_models_response_advertises_structured_outputs():
    resp = build_models_response("my-model")
    supported = resp["data"][0]["supported_parameters"]
    assert "response_format" in supported
    assert "structured_outputs" in supported
    assert "json_schema" in supported


# --- build_chat_completion_response ---------------------------------------------------------


def test_build_chat_completion_response_content_parses_as_valid_model_output():
    resp = build_chat_completion_response(prompt_tokens_estimate=2000)
    content = resp["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    assert set(parsed.keys()) == {
        "answer",
        "cited_evidence_ids",
        "answer_basis",
        "notices",
        "warnings",
        "usage",
    }
    assert parsed["answer_basis"] == "retrieval"
    assert parsed["cited_evidence_ids"] == ["[1]"]
    assert "[1]" in parsed["answer"]


def test_build_chat_completion_response_has_stop_finish_reason():
    resp = build_chat_completion_response(prompt_tokens_estimate=2000)
    assert resp["choices"][0]["finish_reason"] == "stop"


def test_build_chat_completion_response_has_nonzero_usage():
    resp = build_chat_completion_response(prompt_tokens_estimate=2000)
    usage = resp["usage"]
    assert usage["prompt_tokens"] == 2000
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]


# --- build_embeddings_response ---------------------------------------------------------


def test_build_embeddings_response_one_vector_per_input():
    resp, fallback = build_embeddings_response(["a", "b", "c"], {}, dimensions=4)
    assert len(resp["data"]) == 3
    assert all(len(row["embedding"]) == 4 for row in resp["data"])


def test_build_embeddings_response_reports_fallback_count():
    vmap = {"known": [0.1, 0.2]}
    resp, fallback = build_embeddings_response(["known", "unknown1", "unknown2"], vmap, dimensions=2)
    assert fallback == 2


def test_build_embeddings_response_zero_fallback_when_all_known():
    vmap = {"a": [0.1, 0.2], "b": [0.3, 0.4]}
    resp, fallback = build_embeddings_response(["a", "b"], vmap, dimensions=2)
    assert fallback == 0


# --- delay_for_call: per-slice delay schedule (06.3.4.1-07 Task 4 Route B step 4, stub -------
# pacing to production's growing per-slice medians -- the one step-4 factor with no existing
# equivalent: pre-warm is covered by -WarmupQuestions, journaled variants are confirmed equal
# via workflow_meta.reformulation_used, but nothing paces the stub's OWN response latency to
# grow across the run the way production's real provider apparently did.


def test_delay_for_call_first_slice():
    assert delay_for_call([100, 200, 300], call_index=0, slice_calls=50) == 100
    assert delay_for_call([100, 200, 300], call_index=49, slice_calls=50) == 100


def test_delay_for_call_advances_to_next_slice_at_the_boundary():
    assert delay_for_call([100, 200, 300], call_index=50, slice_calls=50) == 200
    assert delay_for_call([100, 200, 300], call_index=99, slice_calls=50) == 200


def test_delay_for_call_holds_the_last_slice_past_the_schedule_end():
    # A run longer than the schedule (e.g. 350 records against a 7-slice schedule covering
    # only production's slices 0-6) must not extrapolate or index out of range.
    assert delay_for_call([100, 200, 300], call_index=1000, slice_calls=50) == 300


def test_delay_for_call_empty_schedule_returns_zero():
    assert delay_for_call([], call_index=0, slice_calls=50) == 0


def test_stub_stats_increment_and_get_returns_post_increment_count():
    stats = StubStats()
    assert stats.increment_and_get("embeddings") == 1
    assert stats.increment_and_get("embeddings") == 2
    assert stats.increment_and_get("chat_completions") == 1
    # Final snapshot counts are unaffected by using increment_and_get instead of increment.
    snap = stats.snapshot()
    assert snap["embeddings"] == 2
    assert snap["chat_completions"] == 1


# --- Live server integration (real socket, real HTTP) -----------------------------------


@pytest.fixture
def live_server():
    server = run_server(
        host="127.0.0.1",
        port=0,
        model_id="stub-test-model",
        vectors_path=None,
        embed_delay_ms=0,
        chat_delay_ms=0,
    )
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def _get(url: str) -> tuple[int, dict]:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _post(url: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_live_server_models_endpoint(live_server: str):
    status, body = _get(f"{live_server}/models")
    assert status == 200
    assert body["data"][0]["id"] == "stub-test-model"


def test_live_server_embeddings_endpoint(live_server: str):
    status, body = _post(
        f"{live_server}/embeddings", {"model": "x", "input": ["hello"], "dimensions": 2048}
    )
    assert status == 200
    assert len(body["data"][0]["embedding"]) == 2048


def test_live_server_chat_completions_endpoint(live_server: str):
    status, body = _post(f"{live_server}/chat/completions", {"messages": [{"role": "user", "content": "hi"}]})
    assert status == 200
    parsed = json.loads(body["choices"][0]["message"]["content"])
    assert parsed["answer_basis"] == "retrieval"


def test_live_server_stats_endpoint_counts_requests(live_server: str):
    _get(f"{live_server}/models")
    _post(f"{live_server}/embeddings", {"input": ["x"]})
    _post(f"{live_server}/chat/completions", {"messages": []})
    status, stats = _get(f"{live_server}/__stub/stats")
    assert status == 200
    assert stats["models"] == 1
    assert stats["embeddings"] == 1
    assert stats["chat_completions"] == 1


def test_live_server_unknown_path_returns_404(live_server: str):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _get(f"{live_server}/unknown")
    assert exc_info.value.code == 404
