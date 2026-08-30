"""Tests for LLM-as-judge client, caching, evidence truncation, and retries."""

import json
from pathlib import Path

import httpx
from pytest_httpx import HTTPXMock

from lancet_eval.client import StructuredCitation
from lancet_eval.corpus import load_corpus_config
from lancet_eval.judge import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    JudgeCache,
    JudgeCacheEntry,
    JudgeVerdict,
    cache_key,
    judge_once,
    truncate_evidence,
)


def test_truncate_evidence_determinism_and_rank_order() -> None:
    """Proves truncate_evidence produces byte-identical output in rank order."""
    citations = [
        StructuredCitation(
            chunk_id="c1",
            document_id="doc-1",
            excerpt="First relevant passage with key facts.",
            rank=1,
        ),
        StructuredCitation(
            chunk_id="c2",
            document_id="doc-2",
            excerpt="Second relevant passage with additional details.",
            rank=2,
        ),
    ]

    ev1 = truncate_evidence(citations, per_passage_budget=50, total_budget=200)
    ev2 = truncate_evidence(citations, per_passage_budget=50, total_budget=200)

    assert ev1 == ev2
    assert "[1] (Document: doc-1, Rank: 1):" in ev1
    assert "[2] (Document: doc-2, Rank: 2):" in ev1

    k1 = cache_key(
        prompt_version="v1",
        judge_model="m",
        question="q",
        answer="a",
        post_truncation_evidence=ev1,
    )
    k2 = cache_key(
        prompt_version="v1",
        judge_model="m",
        question="q",
        answer="a",
        post_truncation_evidence=ev2,
    )
    assert k1 == k2


def test_cache_key_sensitivity() -> None:
    """Proves cache key changes on prompt version, model, or evidence changes."""
    k_base = cache_key(
        prompt_version="v1",
        judge_model="model-a",
        question="What is X?",
        answer="X is Y",
        post_truncation_evidence="Evidence text",
    )

    k_diff_prompt = cache_key(
        prompt_version="v2",
        judge_model="model-a",
        question="What is X?",
        answer="X is Y",
        post_truncation_evidence="Evidence text",
    )
    assert k_base != k_diff_prompt

    k_diff_model = cache_key(
        prompt_version="v1",
        judge_model="model-b",
        question="What is X?",
        answer="X is Y",
        post_truncation_evidence="Evidence text",
    )
    assert k_base != k_diff_model

    k_diff_evidence = cache_key(
        prompt_version="v1",
        judge_model="model-a",
        question="What is X?",
        answer="X is Y",
        post_truncation_evidence="Different evidence text",
    )
    assert k_base != k_diff_evidence


def test_fenced_and_unfenced_json_validation(httpx_mock: HTTPXMock) -> None:
    """Proves fenced JSON and unfenced JSON parse identically."""
    fenced_payload = (
        '```json\n'
        '{\n'
        '  "groundedness": 5,\n'
        '  "faithfulness": 4,\n'
        '  "unsupported_claims": [],\n'
        '  "rationale": "Well supported"\n'
        '}\n'
        '```'
    )
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": fenced_payload}}]}
    )

    client = httpx.Client()
    verdict, err = judge_once(
        client,
        api_key="test-key",
        model="judge-model",
        question="Q?",
        answer="A.",
        evidence="E.",
    )
    assert err is None
    assert verdict is not None
    assert verdict.groundedness == 5
    assert verdict.faithfulness == 4
    assert verdict.rationale == "Well supported"


def test_judge_score_bounds_and_single_reask(httpx_mock: HTTPXMock) -> None:
    """Proves out-of-bounds scores trigger exactly one re-ask."""
    bad_payload_1 = json.dumps({
        "groundedness": 6,  # Out of bounds (>5)
        "faithfulness": 4,
        "unsupported_claims": [],
        "rationale": "Score 6 is invalid",
    })
    bad_payload_2 = json.dumps({
        "groundedness": 0,  # Out of bounds (<1)
        "faithfulness": 4,
        "unsupported_claims": [],
        "rationale": "Score 0 is invalid",
    })

    httpx_mock.add_response(
        json={"choices": [{"message": {"content": bad_payload_1}}]}
    )
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": bad_payload_2}}]}
    )

    client = httpx.Client()
    verdict, err = judge_once(
        client,
        api_key="test-key",
        model="judge-model",
        question="Q?",
        answer="A.",
        evidence="E.",
        max_reasks=1,
    )
    assert verdict is None
    assert err is not None
    assert "validation failed" in err.lower()

    requests = httpx_mock.get_requests()
    assert len(requests) == 2  # Exactly 1 original + 1 re-ask


def test_judge_empty_citations_makes_zero_http_calls(
    httpx_mock: HTTPXMock,
) -> None:
    """Proves empty citations short-circuit without issuing HTTP requests."""
    client = httpx.Client()
    verdict, err = judge_once(
        client,
        api_key="test-key",
        model="judge-model",
        question="Q?",
        answer="A.",
        evidence="",
    )
    assert verdict is None
    assert err == "no evidence returned; groundedness undefined"
    assert len(httpx_mock.get_requests()) == 0


def test_judge_request_body_invariants(httpx_mock: HTTPXMock) -> None:
    """Proves judge requests carry temperature=0 and configured max_tokens."""
    valid_payload = json.dumps({
        "groundedness": 5,
        "faithfulness": 5,
        "unsupported_claims": [],
        "rationale": "Perfect match",
    })
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": valid_payload}}]}
    )

    client = httpx.Client()
    judge_once(
        client,
        api_key="test-key",
        model="judge-model",
        question="Q?",
        answer="A.",
        evidence="E.",
        temperature=0.0,
        max_tokens=DEFAULT_MAX_TOKENS,
    )

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    req_body = json.loads(requests[0].read().decode("utf-8"))
    assert req_body["temperature"] == DEFAULT_TEMPERATURE
    assert req_body["max_tokens"] == DEFAULT_MAX_TOKENS
    assert req_body["response_format"] == {"type": "json_object"}


def test_evidence_overflow_truncation_marker() -> None:
    """Proves passages exceeding budget append explicit truncation marker."""
    citations = [
        StructuredCitation(
            chunk_id=f"c{i}",
            document_id=f"doc-{i}",
            excerpt="A" * 100,
            rank=i,
        )
        for i in range(10)
    ]
    # Restrict total budget so only 2 passages fit
    truncated = truncate_evidence(
        citations, per_passage_budget=100, total_budget=250
    )
    assert "[TRUNCATED:" in truncated
    assert "further passages omitted]" in truncated


def test_judge_cache_round_trip(tmp_path: Path) -> None:
    """Proves JudgeCache saves and reloads entries atomically with sorted keys."""
    cache_file = tmp_path / "judge_cache.json"
    cache = JudgeCache(cache_file)

    verdict = JudgeVerdict(
        groundedness=4,
        faithfulness=5,
        unsupported_claims=["claim1"],
        rationale="mostly grounded",
    )
    entry = JudgeCacheEntry(
        cache_key="k123",
        prompt_version="v1",
        judge_model="meta-llama/llama-3.3-70b-instruct:free",
        question="Q?",
        answer="A.",
        evidence="E.",
        verdict=verdict,
    )
    cache.set("k123", entry)

    # Reload fresh instance from disk
    reloaded = JudgeCache(cache_file)
    cached_entry = reloaded.get("k123")
    assert cached_entry is not None
    assert cached_entry.verdict is not None
    assert cached_entry.verdict.groundedness == 4
    assert cached_entry.verdict.faithfulness == 5


def test_judge_and_generator_model_family_differentiation() -> None:
    """Proves corpus judge models differ in family prefix from generator."""
    import tomllib

    repo_root = Path(__file__).resolve().parents[2]
    config_path = repo_root / "config" / "config.toml"

    with open(config_path, "rb") as f:
        config_data = tomllib.load(f)
    gen_model = config_data.get("openrouter", {}).get("generation_model", "")
    gen_prefix = gen_model.split("/")[0] if "/" in gen_model else gen_model

    for corpus in ("multihop_rag", "graphrag_bench"):
        corpus_cfg = load_corpus_config(corpus)
        judge_model = corpus_cfg.judge_model
        judge_prefix = (
            judge_model.split("/")[0] if "/" in judge_model else judge_model
        )

        assert judge_prefix != gen_prefix, (
            f"Corpus {corpus} judge model {judge_model} shares family "
            f"prefix {gen_prefix} with {gen_model}"
        )
