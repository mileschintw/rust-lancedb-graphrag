"""Preflight health, store isolation, and model differentiation checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from lancet_eval.config import EvalSettings, load_settings, pg_schema_of
from lancet_eval.seed import load_document_map

if TYPE_CHECKING:
    import httpx


class PreflightError(Exception):
    """Raised when one or more preflight checks fail."""


class PreflightCheckResult(BaseModel):
    """Result of an individual preflight check."""

    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    message: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


def check_store_isolation(settings: EvalSettings) -> PreflightCheckResult:
    """Verify evaluation store isolation from development store paths."""
    eval_lance = str(Path(settings.lancedb_path).resolve())
    dev_lance = str(Path(settings.dev_lancedb_path).resolve())

    if eval_lance == dev_lance:
        return PreflightCheckResult(
            name="store_isolation",
            passed=False,
            message=(
                f"Eval LanceDB path '{settings.lancedb_path}' collides with "
                f"dev path '{settings.dev_lancedb_path}'"
            ),
        )

    eval_schema = pg_schema_of(settings.database_url)
    dev_schema = pg_schema_of(settings.dev_database_url)

    if eval_schema and dev_schema and eval_schema == dev_schema:
        return PreflightCheckResult(
            name="store_isolation",
            passed=False,
            message=(
                f"Eval PostgreSQL schema '{eval_schema}' collides with "
                f"dev schema '{dev_schema}'"
            ),
        )

    return PreflightCheckResult(
        name="store_isolation",
        passed=True,
        message="Eval LanceDB and PostgreSQL schema are fully isolated from dev.",
        detail={
            "eval_lancedb": settings.lancedb_path,
            "eval_schema": eval_schema,
        },
    )


def check_gateway_and_engine(
    client: httpx.Client,
) -> tuple[PreflightCheckResult, PreflightCheckResult]:
    """Check gateway and engine health without conflating failure modes."""
    try:
        resp = client.get("/health")
    except Exception as exc:
        gw_check = PreflightCheckResult(
            name="gateway_reachable",
            passed=False,
            message=(
                f"Gateway connection failed: {exc}. Start the gateway with "
                "LANCET_ENV=eval after starting PostgreSQL with "
                "docker compose up -d db."
            ),
        )
        engine_check = PreflightCheckResult(
            name="engine_reachable",
            passed=False,
            message="Engine unreachable because gateway is down.",
        )
        return gw_check, engine_check

    if resp.status_code == 200:
        gw_check = PreflightCheckResult(
            name="gateway_reachable",
            passed=True,
            message="Gateway is reachable (HTTP 200).",
        )
        engine_check = PreflightCheckResult(
            name="engine_reachable",
            passed=True,
            message="Engine is reachable and healthy.",
        )
        return gw_check, engine_check

    # If gateway returns 503 with JSON body detailing engine status
    try:
        data = resp.json()
        gw_check = PreflightCheckResult(
            name="gateway_reachable",
            passed=True,
            message=f"Gateway responded (HTTP {resp.status_code}).",
        )
        engine_msg = data.get("engine", {}).get("error") or data.get("error", resp.text)
        engine_check = PreflightCheckResult(
            name="engine_reachable",
            passed=False,
            message=f"Engine unavailable: {engine_msg}",
        )
        return gw_check, engine_check
    except Exception:
        gw_check = PreflightCheckResult(
            name="gateway_reachable",
            passed=False,
            message=(
                f"Gateway returned unparseable status HTTP {resp.status_code}: "
                f"{resp.text}"
            ),
        )
        engine_check = PreflightCheckResult(
            name="engine_reachable",
            passed=False,
            message="Engine status unknown due to gateway error.",
        )
        return gw_check, engine_check


def check_corpus_generation(
    client: httpx.Client, corpus_name: str
) -> PreflightCheckResult:
    """Probe /rag/query, check generation and truncation budget."""
    try:
        doc_map = load_document_map(corpus_name)
    except Exception as exc:
        return PreflightCheckResult(
            name="corpus_generation",
            passed=False,
            message=(
                f"Missing document map for corpus '{corpus_name}': {exc}. "
                "Run 'seed' first."
            ),
        )

    try:
        resp = client.post(
            "/rag/query",
            json={
                "query": "preflight throwaway query",
                "disable_graph_context": False,
            },
        )
    except Exception as exc:
        return PreflightCheckResult(
            name="corpus_generation",
            passed=False,
            message=f"Preflight /rag/query probe failed: {exc}",
        )

    if resp.status_code != 200:
        return PreflightCheckResult(
            name="corpus_generation",
            passed=False,
            message=(
                f"Preflight /rag/query returned HTTP {resp.status_code}: {resp.text}"
            ),
        )

    live_gen = ""
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            try:
                event_data = json.loads(line[5:].strip())
                snap = event_data.get("snapshot") or (
                    event_data.get("final_response", {}).get("snapshot")
                )
                if snap and snap.get("index_generation"):
                    live_gen = snap["index_generation"]
                    # Assert truncation budget
                    chunks = snap.get("retrieved_chunks", [])
                    for c in chunks:
                        if c.get("is_truncated", False):
                            return PreflightCheckResult(
                                name="corpus_generation",
                                passed=False,
                                message=(
                                    "Retrieved chunk excerpt arrived truncated "
                                    "(is_truncated=true)"
                                ),
                            )
                    break
            except Exception:
                pass

    if not live_gen:
        return PreflightCheckResult(
            name="corpus_generation",
            passed=False,
            message="No index_generation observed in preflight query snapshot.",
        )

    if doc_map.index_generation and doc_map.index_generation != live_gen:
        return PreflightCheckResult(
            name="corpus_generation",
            passed=False,
            message=(
                f"Index generation mismatch: store has '{live_gen}' but "
                f"document map was seeded at '{doc_map.index_generation}'. "
                "Reseed required."
            ),
        )

    return PreflightCheckResult(
        name="corpus_generation",
        passed=True,
        message=(
            f"Index generation matched ('{live_gen}') and excerpt budget verified."
        ),
        detail={"index_generation": live_gen},
    )


def check_openrouter_api(
    api_key: str | None, is_judged_requested: bool
) -> PreflightCheckResult:
    """Check OpenRouter API key presence when judged evaluation is requested."""
    if not is_judged_requested:
        return PreflightCheckResult(
            name="openrouter_api",
            passed=True,
            message="Deterministic evaluation path requires no OpenRouter API key.",
        )

    if not api_key or not api_key.strip():
        return PreflightCheckResult(
            name="openrouter_api",
            passed=False,
            message=("Judged evaluation requested but OPENROUTER_API_KEY is not set."),
        )

    return PreflightCheckResult(
        name="openrouter_api",
        passed=True,
        message="OPENROUTER_API_KEY is configured for judge evaluations.",
    )


def check_model_differentiation(
    generation_model: str, judge_model: str
) -> PreflightCheckResult:
    """Assert judge model differs from generation model."""
    gen_norm = generation_model.strip() if generation_model else ""
    judge_norm = judge_model.strip() if judge_model else ""

    if gen_norm and judge_norm and gen_norm == judge_norm:
        return PreflightCheckResult(
            name="model_differentiation",
            passed=False,
            message=(
                f"Judge model '{judge_model}' matches generation model "
                f"'{generation_model}'. Pinned judge model must be distinct."
            ),
        )

    return PreflightCheckResult(
        name="model_differentiation",
        passed=True,
        message=(
            f"Judge model ('{judge_model}') is distinct from "
            f"generation model ('{generation_model}')."
        ),
    )


def run_preflight_checks(
    corpus_name: str,
    judged: bool = False,
    settings: EvalSettings | None = None,
    client: httpx.Client | None = None,
    generation_model: str = "dots-studio/dots-3-note-preview:free",
) -> list[PreflightCheckResult]:
    """Execute the full preflight checklist and return all results."""
    import httpx

    settings = settings or load_settings()
    results: list[PreflightCheckResult] = []

    # 1. Store isolation
    results.append(check_store_isolation(settings))

    # 2. Gateway and engine reachability
    should_close_client = False
    if client is None:
        client = httpx.Client(
            base_url=settings.gateway_url,
            timeout=settings.gateway_timeout_secs,
        )
        should_close_client = True

    try:
        gw_check, eng_check = check_gateway_and_engine(client)
        results.append(gw_check)
        results.append(eng_check)

        # 3. Corpus generation check (only if gateway & engine are up)
        if gw_check.passed and eng_check.passed:
            results.append(check_corpus_generation(client, corpus_name))
    finally:
        if should_close_client:
            client.close()

    # 4. OpenRouter API key check
    api_key = os.getenv("OPENROUTER_API_KEY")
    results.append(check_openrouter_api(api_key, judged))

    # 5. Model differentiation check
    if judged:
        results.append(
            check_model_differentiation(generation_model, settings.judge_model)
        )

    return results
