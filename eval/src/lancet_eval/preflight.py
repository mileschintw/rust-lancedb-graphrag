"""Preflight health, store isolation, and model differentiation checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from lancet_eval.config import EvalSettings, load_settings, pg_schema_of, repo_root
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
        probe_query = "What hospital program helps teenage patients in Nebraska?"
        if doc_map.entries:
            first_entry = next(iter(doc_map.entries.values()))
            if first_entry.title:
                probe_query = first_entry.title

        resp = client.post(
            "/rag/query",
            json={
                "query": probe_query,
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


def check_canary_manifest(
    canary_path: Path | str | None = None,
    sample_path: Path | str | None = None,
) -> PreflightCheckResult:
    """Validate canary manifest exists, matches sample verbatim, and satisfies shape."""
    canary_p = (
        Path(canary_path)
        if canary_path is not None
        else repo_root() / "eval" / "corpora" / "multihop_rag" / "canary.jsonl"
    )
    sample_p = (
        Path(sample_path)
        if sample_path is not None
        else repo_root()
        / "eval"
        / "corpora"
        / "multihop_rag"
        / "questions.sample.jsonl"
    )

    if not canary_p.exists():
        return PreflightCheckResult(
            name="canary_manifest",
            passed=False,
            message=f"Canary manifest missing at expected path: {canary_p}",
            detail={"expected_path": str(canary_p)},
        )

    if not sample_p.exists():
        return PreflightCheckResult(
            name="canary_manifest",
            passed=False,
            message=f"Corpus sample missing at expected path: {sample_p}",
            detail={"expected_path": str(sample_p)},
        )

    try:
        sample_questions: dict[str, str] = {}
        for line in sample_p.read_text(encoding="utf-8").splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            row = json.loads(line_str)
            sample_questions[row["question_id"]] = row["query"]

        canary_rows: list[dict[str, Any]] = []
        for line in canary_p.read_text(encoding="utf-8").splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            canary_rows.append(json.loads(line_str))

        if len(canary_rows) != 7:
            return PreflightCheckResult(
                name="canary_manifest",
                passed=False,
                message=(
                    f"Canary manifest must have exactly 7 rows, got {len(canary_rows)}"
                ),
                detail={"row_count": len(canary_rows)},
            )

        unique_ids = {r["question_id"] for r in canary_rows}
        if len(unique_ids) != 6:
            return PreflightCheckResult(
                name="canary_manifest",
                passed=False,
                message=(
                    "Canary manifest must have exactly 6 distinct IDs, "
                    f"got {len(unique_ids)}"
                ),
                detail={"distinct_ids": len(unique_ids)},
            )

        for idx, row in enumerate(canary_rows):
            qid = row.get("question_id", "")
            qtext = row.get("question", "")
            if qid not in sample_questions:
                return PreflightCheckResult(
                    name="canary_manifest",
                    passed=False,
                    message=f"Canary row {idx} ID '{qid}' not found in corpus sample",
                    detail={"question_id": qid},
                )
            if sample_questions[qid] != qtext:
                return PreflightCheckResult(
                    name="canary_manifest",
                    passed=False,
                    message=(
                        "Canary question text drifted from corpus sample for "
                        f"ID '{qid}'"
                    ),
                    detail={"question_id": qid},
                )

        return PreflightCheckResult(
            name="canary_manifest",
            passed=True,
            message="Canary manifest verified against corpus sample.",
            detail={"row_count": len(canary_rows), "distinct_ids": len(unique_ids)},
        )
    except Exception as exc:
        return PreflightCheckResult(
            name="canary_manifest",
            passed=False,
            message=f"Canary manifest check failed with error: {exc}",
        )


def read_effective_workflow_config(
    config_path: Path | str | None = None,
) -> dict[str, int]:
    """Read effective [engine.workflow] timeouts.

    Resolves base, overlay, and env overrides per engine config model.
    """
    import os
    import tomllib

    if config_path is not None:
        cfg_p = Path(config_path)
    else:
        cfg_dir = os.getenv("LANCET_CONFIG_DIR", "").strip()
        if cfg_dir:
            cfg_p = Path(cfg_dir) / "config.toml"
        else:
            cfg_p = repo_root() / "config" / "config.toml"

    if not cfg_p.exists():
        raise FileNotFoundError(f"Engine config file not found: {cfg_p}")

    with open(cfg_p, "rb") as f:
        data = tomllib.load(f)

    workflow_sec = data.get("engine", {}).get("workflow")
    if not isinstance(workflow_sec, dict):
        raise ValueError("Missing or invalid [engine.workflow] section in config")

    # Mirror LANCET_ENV overlay resolution from engine/src/config.rs:674-679
    env_name = os.getenv("LANCET_ENV", "").strip()
    if env_name:
        overlay_p = cfg_p.parent / f"{cfg_p.stem}.{env_name}.toml"
        if overlay_p.exists():
            with open(overlay_p, "rb") as f:
                overlay_data = tomllib.load(f)
            overlay_sec = overlay_data.get("engine", {}).get("workflow")
            if isinstance(overlay_sec, dict):
                workflow_sec.update(overlay_sec)

    # Mirror explicit environment overrides from engine/src/config.rs:698-732
    prefix = "LANCET_ENGINE__WORKFLOW__"
    key_to_env = {
        "reformulate_timeout_ms": f"{prefix}REFORMULATE_TIMEOUT_MS",
        "query_embedding_timeout_ms": f"{prefix}QUERY_EMBEDDING_TIMEOUT_MS",
        "retrieve_timeout_ms": f"{prefix}RETRIEVE_TIMEOUT_MS",
        "graph_operation_timeout_ms": f"{prefix}GRAPH_OPERATION_TIMEOUT_MS",
        "graph_node_timeout_ms": f"{prefix}GRAPH_NODE_TIMEOUT_MS",
        "prompt_timeout_ms": f"{prefix}PROMPT_TIMEOUT_MS",
        "generation_node_timeout_ms": f"{prefix}GENERATION_NODE_TIMEOUT_MS",
    }

    effective: dict[str, int] = {}
    for key, env_var in key_to_env.items():
        env_val = os.getenv(env_var, "").strip()
        if env_val:
            try:
                effective[key] = int(env_val)
                continue
            except ValueError:
                pass
        val = workflow_sec.get(key)
        if val is not None:
            effective[key] = int(val)

    return effective


def read_workflow_timeouts(config_path: Path | str | None = None) -> dict[str, int]:
    """Read [engine.workflow] timeout keys live using tomllib.

    Returns mapping of node names to configured timeout in milliseconds.
    Never exposes provider keys or other configuration sections.
    """
    effective = read_effective_workflow_config(config_path)

    # Authoritative mapping mirroring engine/src/workflow/runner.rs:298-317
    node_to_key = {
        "ReformulateQuery": "reformulate_timeout_ms",
        "RetrieveHybrid": "retrieve_timeout_ms",
        "ExtractGraphContext": "graph_node_timeout_ms",
        "AssemblePrompt": "prompt_timeout_ms",
        "GenerateAnswer": "generation_node_timeout_ms",
    }

    timeouts: dict[str, int] = {}
    for node_name, key in node_to_key.items():
        val = effective.get(key)
        if val is None:
            raise ValueError(f"Missing timeout key '{key}' in [engine.workflow]")
        timeouts[node_name] = int(val)

    return timeouts


def check_canary_floors(
    client: httpx.Client,
    canary_path: Path | str | None = None,
    config_path: Path | str | None = None,
) -> PreflightCheckResult:
    """Probe query path against committed canaries and live configured timeouts."""
    from lancet_eval.client import run_query
    from lancet_eval.dimensions import NOTICE_CODE_GRAPH_ABLATION

    canary_p = (
        Path(canary_path)
        if canary_path is not None
        else repo_root() / "eval" / "corpora" / "multihop_rag" / "canary.jsonl"
    )
    if not canary_p.exists():
        return PreflightCheckResult(
            name="canary_floors",
            passed=False,
            message=f"Canary file missing: {canary_p}",
        )

    try:
        node_timeouts = read_workflow_timeouts(config_path)
    except Exception as exc:
        return PreflightCheckResult(
            name="canary_floors",
            passed=False,
            message=f"Failed to read engine workflow timeouts: {exc}",
        )

    # Map node name to config key for informative messages
    node_to_key = {
        "ReformulateQuery": "reformulate_timeout_ms",
        "RetrieveHybrid": "retrieve_timeout_ms",
        "ExtractGraphContext": "graph_node_timeout_ms",
        "AssemblePrompt": "prompt_timeout_ms",
        "GenerateAnswer": "generation_node_timeout_ms",
    }

    try:
        rows: list[dict[str, Any]] = [
            json.loads(line)
            for line in canary_p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except Exception as exc:
        return PreflightCheckResult(
            name="canary_floors",
            passed=False,
            message=f"Failed to parse canary rows: {exc}",
        )

    failures: list[str] = []

    for row in rows:
        qid = row["question_id"]
        arm = row["graph_arm"]
        qtext = row["question"]
        min_chunks = row.get("min_retrieved_chunks", 1)
        req_graph = row.get("require_graph_node", False)
        req_retrieval_completed = row.get("require_retrieval_completed_only", False)
        req_ablation = row.get("require_ablation_notice", False)

        disable_graph = arm == "graph-off"

        try:
            outcome = run_query(
                client,
                query=qtext,
                disable_graph_context=disable_graph,
                capture_raw_events=False,
            )
        except Exception as exc:
            failures.append(f"Canary {qid} ({arm}) query failed with exception: {exc}")
            continue

        # 1. Retrieval floor check
        snapshot = (
            outcome.answer.snapshot if outcome.answer else outcome.partial_snapshot
        )
        observed_chunks = len(snapshot.retrieved_chunks) if snapshot else 0
        if req_retrieval_completed:
            # Null canary: permits zero chunks, but retrieval node must have completed
            retrieval_completed = any(
                t.node_name == "RetrieveHybrid" for t in outcome.node_timings
            )
            retrieval_failed = any(
                f.node_name == "RetrieveHybrid" for f in outcome.node_failures
            )
            if retrieval_failed or not retrieval_completed:
                failures.append(
                    f"Canary {qid} ({arm}) null question retrieval node failed "
                    "or did not complete"
                )
        else:
            if observed_chunks < min_chunks:
                failures.append(
                    f"Canary {qid} ({arm}) retrieval floor missed: "
                    f"observed {observed_chunks} chunks, floor is {min_chunks}"
                )

        # 2. Graph node check
        if req_graph:
            graph_nodes = (
                outcome.workflow_meta.graph_node_count
                if outcome.workflow_meta is not None
                else 0
            )
            if graph_nodes < 1:
                failures.append(
                    f"Canary {qid} ({arm}) graph floor missed: observed {graph_nodes} "
                    "graph nodes (cause: either a graph defect or canary entities "
                    "not in store pending 06.3.3 D-05 inspection)"
                )

        # 3. Ablation notice check
        if req_ablation:
            has_ablation = any(
                n.typed_code == NOTICE_CODE_GRAPH_ABLATION
                or n.code == "GRAPH_ABLATION"
                or n.code == str(NOTICE_CODE_GRAPH_ABLATION)
                for n in outcome.notices
            )
            if not has_ablation:
                failures.append(
                    f"Canary {qid} ({arm}) graph-off twin missing required "
                    f"ablation notice (code {NOTICE_CODE_GRAPH_ABLATION})"
                )

        # 4. Duration floors against live config
        for timing in outcome.node_timings:
            node_name = timing.node_name
            if node_name in node_timeouts:
                budget_ms = node_timeouts[node_name]
                cfg_key = node_to_key.get(node_name, node_name)
                dur = timing.duration_ms or 0.0
                if dur >= budget_ms:
                    failures.append(
                        f"Canary {qid} ({arm}) node {node_name} duration {dur}ms "
                        f"exceeded configured budget {budget_ms}ms ({cfg_key})"
                    )

    if failures:
        return PreflightCheckResult(
            name="canary_floors",
            passed=False,
            message="; ".join(failures),
            detail={"failure_count": len(failures)},
        )

    return PreflightCheckResult(
        name="canary_floors",
        passed=True,
        message=f"All {len(rows)} canaries passed floors against live engine budgets.",
        detail={"canary_count": len(rows)},
    )


def run_preflight_checks(
    corpus_name: str,
    judged: bool = False,
    settings: EvalSettings | None = None,
    client: httpx.Client | None = None,
    generation_model: str = "deepseek/deepseek-v4-flash-0731",
) -> list[PreflightCheckResult]:
    """Execute the full preflight checklist and return all results."""
    import httpx

    settings = settings or load_settings()
    results: list[PreflightCheckResult] = []

    # 1. Store isolation
    results.append(check_store_isolation(settings))

    # 2. Canary manifest check (unconditional, independent of gateway/engine)
    results.append(check_canary_manifest())

    # 3. Gateway and engine reachability
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

        # 4. Gated live checks: corpus generation and canary floors
        if gw_check.passed and eng_check.passed:
            results.append(check_corpus_generation(client, corpus_name))
            results.append(check_canary_floors(client))
    finally:
        if should_close_client:
            client.close()

    # 5. OpenRouter API key check
    api_key = os.getenv("OPENROUTER_API_KEY")
    results.append(check_openrouter_api(api_key, judged))

    # 6. Model differentiation check
    if judged:
        results.append(
            check_model_differentiation(generation_model, settings.judge_model)
        )

    return results
