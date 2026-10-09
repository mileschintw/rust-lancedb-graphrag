"""Sub-cent authenticated probe that closes verified-facts A7 (06.3.6 lever 1, first task).

PROPOSED helper. NOT RUN AGAINST THE LIVE API at spec time: the spec researcher was told to
make no paid or authenticated call. `--selftest` runs the same code path against an in-process
mock transport and is the only thing that was executed.

Live use (the plan's first lever-1 task). It spends money, so it needs the owner's D-86 checkpoint
authorisation first; nothing in the spec-time transcript shows that authorisation exists yet:

    OPENROUTER_API_KEY=... uv run --project eval python rerank_probe.py --live --out probe-result.json

It sends ONE request of 2 short documents to POST https://openrouter.ai/api/v1/rerank for
`voyageai/rerank-2.5-lite` and records: HTTP status, latency, the response `model` and
`provider`, the result order, and `usage` (including `usage.cost`, which the OpenAPI schema
marks optional). It never prints or stores the key. A non-200 status, a body that is not a
permutation of the 2 inputs, or a missing `usage.cost` makes the exit code non-zero, and
D-131 then stops and the owner is asked (no fallback model). For a missing `usage.cost` the
owner may decide that account-delta-only reconciliation is acceptable; that is the owner's
call, not the script's. The record is evidence for the price: reconcile the reported cost
against the account balance delta, because the OpenRouter model listing shows 0/0 for rerank
(verified-facts A7). In the drive (not here) a single reply without `usage.cost` is counted
as "not reported" and does not stop anything.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict

ENDPOINT = "https://openrouter.ai/api/v1/rerank"
MODEL = "voyageai/rerank-2.5-lite"
QUERY = "Which city is the capital of France?"
DOCUMENTS = ["Berlin is the capital of Germany.", "Paris is the capital of France."]


class _Item(BaseModel):
    model_config = ConfigDict(extra="ignore")
    index: int
    relevance_score: float


class _Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cost: float | None = None
    total_tokens: int | None = None


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    provider: str | None = None
    results: list[_Item]
    usage: _Usage | None = None


def probe(client: httpx.Client, api_key: str) -> dict[str, object]:
    started = time.monotonic()
    resp = client.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": MODEL, "query": QUERY, "documents": DOCUMENTS, "top_n": len(DOCUMENTS)},
        timeout=10.0,
    )
    latency_ms = (time.monotonic() - started) * 1000.0
    record: dict[str, object] = {
        "at": datetime.now(UTC).isoformat(),
        "status": resp.status_code,
        "latency_ms": round(latency_ms, 1),
        "ok": False,
    }
    if resp.status_code != 200:
        record["error_body_prefix"] = resp.text[:200]
        return record
    body = _Body.model_validate(resp.json())
    order = [item.index for item in body.results]
    record.update(
        model=body.model,
        provider=body.provider,
        order=order,
        scores=[item.relevance_score for item in body.results],
        usage=body.usage.model_dump() if body.usage else None,
        cost_reported=bool(body.usage and body.usage.cost is not None),
    )
    record["ok"] = sorted(order) == list(range(len(DOCUMENTS))) and bool(record["cost_reported"])
    return record


def _mock_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == "Bearer test-key"
    sent = json.loads(request.content)
    assert sent["documents"] == DOCUMENTS and sent["model"] == MODEL
    return httpx.Response(200, json={
        "id": "gen-rerank-mock", "model": "voyageai/rerank-2.5-lite-20260727", "provider": "mock",
        "results": [
            {"index": 1, "relevance_score": 0.97, "document": {"text": DOCUMENTS[1]}},
            {"index": 0, "relevance_score": 0.05, "document": {"text": DOCUMENTS[0]}},
        ],
        "usage": {"cost": 2e-7, "total_tokens": 31},
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="send the one real request")
    parser.add_argument("--selftest", action="store_true", help="mock transport, no network")
    parser.add_argument("--out", type=Path, default=Path("probe-result.json"))
    args = parser.parse_args()
    if args.selftest == args.live:
        parser.error("choose exactly one of --live and --selftest")
    if args.selftest:
        with httpx.Client(transport=httpx.MockTransport(_mock_handler)) as client:
            record = probe(client, "test-key")
        assert record["ok"] and record["order"] == [1, 0] and record["cost_reported"], record

        def no_cost(request: httpx.Request) -> httpx.Response:
            body = _mock_handler(request).json()
            body.pop("usage")
            return httpx.Response(200, json=body)

        with httpx.Client(transport=httpx.MockTransport(no_cost)) as client:
            missing = probe(client, "test-key")
        assert not missing["ok"] and not missing["cost_reported"], missing  # a missing usage.cost fails the probe
        print("selftest ok:", json.dumps(record, sort_keys=True))
        return 0
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return 2
    with httpx.Client() as client:
        record = probe(client, key)
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(record, sort_keys=True))
    return 0 if record["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
