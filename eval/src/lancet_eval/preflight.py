"""Preflight health, store isolation, and model differentiation checks."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lancet_eval.config import EvalSettings, load_settings, pg_schema_of, repo_root
from lancet_eval.seed import load_document_map

if TYPE_CHECKING:
    import httpx

    from lancet_eval.client import RetrievalSnapshot


class PreflightError(Exception):
    """Raised when one or more preflight checks fail."""


class PreflightCheckResult(BaseModel):
    """Result of an individual preflight check."""

    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    status: Literal["pass", "fail", "accepted_known_miss"] | None = None
    message: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _derive_status(self) -> Self:
        """Fill ``status`` from ``passed``; reject a status that contradicts it."""
        if self.status is None:
            self.status = "pass" if self.passed else "fail"
        elif self.passed != (self.status != "fail"):
            raise ValueError(f"status {self.status!r} contradicts passed={self.passed}")
        return self


class AcceptedKnownMiss(BaseModel):
    """One operator-named floor miss to report instead of failing (D-94)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: str
    graph_arm: Literal["graph-on", "graph-off"]
    check: str
    decision_id: str


class CanaryKnownMissOutcome(BaseModel):
    """What a canary run observed for a named accepted known miss (D-94)."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    graph_arm: Literal["graph-on", "graph-off"]
    check: str
    decision_id: str
    observed_graph_node_count: int
    outcome: Literal["accepted_known_miss", "floor_met"]


# D-94 (06.3.4.1-CONTEXT, 2026-09-29): the graph floor of canary mhr-0d5e238015ef
# (graph-on) is an accepted, reported miss for drive 1's preflight only. Keys are
# (question_id, graph_arm, check); values are the decision ID that grants the exception.
# This registry is the only source of accepted misses: the command line can select an
# entry but can never add one. It expires at 06.3.4.1-18, which re-validates every
# canary live without the option.
ACCEPTED_KNOWN_MISS_REGISTRY: MappingProxyType[tuple[str, str, str], str] = (
    MappingProxyType({("mhr-0d5e238015ef", "graph-on", "require_graph_node"): "D-94"})
)

_ACCEPTED_KNOWN_MISS_SHAPE = "<question_id>:<graph_arm>:<check>:<decision_id>"


def registered_accepted_known_miss_values() -> list[str]:
    """Return the command-line value of every registry entry."""
    return [
        f"{question_id}:{arm}:{check}:{decision_id}"
        for (question_id, arm, check), decision_id in (
            ACCEPTED_KNOWN_MISS_REGISTRY.items()
        )
    ]


def parse_accepted_known_miss(raw: str) -> AcceptedKnownMiss:
    """Parse ``<question_id>:<graph_arm>:<check>:<decision_id>``.

    Raises ``ValueError`` unless there are exactly four non-empty fields and the arm
    is ``graph-on`` or ``graph-off``. Parsing does not consult the registry.
    """
    fields = [part.strip() for part in raw.split(":")]
    if len(fields) != 4 or not all(fields):
        raise ValueError(
            f"accepted known miss {raw!r} must have the shape "
            f"{_ACCEPTED_KNOWN_MISS_SHAPE} with four non-empty fields"
        )
    question_id, graph_arm, check, decision_id = fields
    try:
        return AcceptedKnownMiss(
            question_id=question_id,
            graph_arm=graph_arm,  # type: ignore[arg-type]
            check=check,
            decision_id=decision_id,
        )
    except ValidationError as exc:
        raise ValueError(
            f"accepted known miss {raw!r} must have the shape "
            f"{_ACCEPTED_KNOWN_MISS_SHAPE} with graph_arm graph-on or graph-off"
        ) from exc


def validate_accepted_known_misses(
    misses: Sequence[AcceptedKnownMiss],
    canary_path: Path | str | None = None,
) -> tuple[AcceptedKnownMiss, ...]:
    """Check each miss against the registry and the committed canary manifest.

    Raises ``PreflightError`` for a duplicate, a key that is not in
    ``ACCEPTED_KNOWN_MISS_REGISTRY``, a decision ID other than the registry's, a
    (question, arm) with no manifest row, or a row that does not set the named check
    true. It reads the manifest only and sends no request.
    """
    hint = "; ".join(registered_accepted_known_miss_values())
    canary_p = (
        Path(canary_path)
        if canary_path is not None
        else repo_root() / "eval" / "corpora" / "multihop_rag" / "canary.jsonl"
    )
    seen: set[tuple[str, str, str]] = set()
    rows: list[dict[str, Any]] | None = None
    for miss in misses:
        key = (miss.question_id, miss.graph_arm, miss.check)
        label = f"{miss.question_id}:{miss.graph_arm}:{miss.check}:{miss.decision_id}"
        if key in seen:
            raise PreflightError(f"duplicate accepted known miss {label!r}")
        seen.add(key)
        registered_decision = ACCEPTED_KNOWN_MISS_REGISTRY.get(key)
        if registered_decision is None:
            raise PreflightError(
                f"accepted known miss {label!r} is not registered; "
                f"the only accepted value is {hint}"
            )
        if miss.decision_id != registered_decision:
            raise PreflightError(
                f"accepted known miss {label!r} names decision {miss.decision_id!r}, "
                f"but the registry grants it under {registered_decision!r}"
            )
        if rows is None:
            try:
                rows = [
                    json.loads(line)
                    for line in canary_p.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except Exception as exc:
                raise PreflightError(
                    f"cannot read the canary manifest at {canary_p}: {exc}"
                ) from exc
        row = next(
            (
                r
                for r in rows
                if r.get("question_id") == miss.question_id
                and r.get("graph_arm") == miss.graph_arm
            ),
            None,
        )
        if row is None:
            raise PreflightError(
                f"accepted known miss {label!r} has no canary manifest row"
            )
        if row.get(miss.check) is not True:
            raise PreflightError(
                f"accepted known miss {label!r}: the manifest row does not set "
                f"{miss.check} true"
            )
    return tuple(misses)


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
            detail={"probe_snapshot_missing": True},
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


def corpus_generation_from_canaries(
    corpus_name: str,
    snapshots: Sequence[tuple[str, RetrievalSnapshot]],
) -> PreflightCheckResult:
    """Read the index generation from successful canary answers.

    Used only when the corpus probe's answer carried no snapshot: a single
    generation is rejected about 31% of the time after F-1 (06.3.4.1-26), so the
    probe alone cannot gate a healthy stack. Every generation observed must agree
    and match the document map, and the excerpt budget is checked on each snapshot.
    """
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

    observed = [(label, snap) for label, snap in snapshots if snap.index_generation]
    if not observed:
        return PreflightCheckResult(
            name="corpus_generation",
            passed=False,
            message=(
                "No index_generation observed in preflight query snapshot or in "
                "any successful canary answer."
            ),
        )

    for label, snap in observed:
        if any(chunk.is_truncated for chunk in snap.retrieved_chunks):
            return PreflightCheckResult(
                name="corpus_generation",
                passed=False,
                message=(
                    f"Retrieved chunk excerpt arrived truncated (is_truncated=true) "
                    f"in {label}"
                ),
            )

    generations = sorted({snap.index_generation for _, snap in observed})
    if len(generations) > 1:
        return PreflightCheckResult(
            name="corpus_generation",
            passed=False,
            message=(f"Canary answers disagree on index_generation: {generations}"),
            detail={"index_generations": generations},
        )

    live_gen = generations[0]
    source = observed[0][0]
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
            f"Index generation matched ('{live_gen}') and excerpt budget verified; "
            f"the probe answer carried no snapshot, so it was read from "
            f"{len(observed)} successful canary answer(s), first {source}."
        ),
        detail={
            "index_generation": live_gen,
            "source": source,
            "canary_answers_read": len(observed),
        },
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


# 06.3.4.1 D-80: the manifest holds the seed-to-seed path canary as its eighth row, so
# it is exactly 8 rows over 7 distinct question IDs (06.3.4 had 7 over 6: every ID once,
# and the graph-off ablation twin of mhr-0d5e238015ef beside its graph-on row).
CANARY_MANIFEST_ROW_COUNT: int = 8
CANARY_MANIFEST_DISTINCT_IDS: int = 7


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

        if len(canary_rows) != CANARY_MANIFEST_ROW_COUNT:
            return PreflightCheckResult(
                name="canary_manifest",
                passed=False,
                message=(
                    "Canary manifest must have exactly "
                    f"{CANARY_MANIFEST_ROW_COUNT} rows, got {len(canary_rows)}"
                ),
                detail={"row_count": len(canary_rows)},
            )

        unique_ids = {r["question_id"] for r in canary_rows}
        if len(unique_ids) != CANARY_MANIFEST_DISTINCT_IDS:
            return PreflightCheckResult(
                name="canary_manifest",
                passed=False,
                message=(
                    "Canary manifest must have exactly "
                    f"{CANARY_MANIFEST_DISTINCT_IDS} distinct IDs, "
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


def _seed_path_unmet(
    meta: Any, observed_chunks: int
) -> str | None:
    """The first unmet `require_seed_path` condition, or None when all four hold.

    D-80, in order: `graph_path_found` true, `graph_node_count` at least 1,
    `graph_prompt_fact_count` at least 1, and at least one retrieved chunk. A wire
    field the engine did not report (None) is a miss, never a pass.
    """
    path_found = None if meta is None else meta.graph_path_found
    if path_found is not True:
        return (
            f"graph_path_found is {path_found} "
            "(a seed-to-seed path is required)"
        )
    if meta.graph_node_count < 1:
        return f"graph_node_count is {meta.graph_node_count} (at least 1 is required)"
    facts = meta.graph_prompt_fact_count
    if facts is None or facts < 1:
        return (
            f"graph_prompt_fact_count is {facts} "
            "(at least 1 path fact must reach the prompt)"
        )
    if observed_chunks < 1:
        return f"{observed_chunks} retrieved chunks (at least 1 is required)"
    return None


def check_canary_floors(
    client: httpx.Client,
    canary_path: Path | str | None = None,
    config_path: Path | str | None = None,
    accepted_known_misses: Sequence[AcceptedKnownMiss] = (),
    answered_snapshots: list[tuple[str, RetrievalSnapshot]] | None = None,
) -> PreflightCheckResult:
    """Probe query path against committed canaries and live configured timeouts.

    ``accepted_known_misses`` (D-94) names registry entries whose graph-floor miss
    is reported as ``accepted_known_miss`` instead of failing. Every other floor
    still gates. When ``answered_snapshots`` is given, the snapshot of each canary
    whose answer succeeded is appended to it, labelled by question and arm.

    ``require_seed_path`` (D-80) is a hard floor beside ``require_graph_node``. It is
    never routed through the accepted-known-miss branch: the D-94 registry names
    ``require_graph_node`` on one row and nothing else.
    """
    from lancet_eval.client import run_query
    from lancet_eval.dimensions import NOTICE_CODE_GRAPH_ABLATION

    canary_p = (
        Path(canary_path)
        if canary_path is not None
        else repo_root() / "eval" / "corpora" / "multihop_rag" / "canary.jsonl"
    )
    accepted_by_key: dict[tuple[str, str, str], AcceptedKnownMiss] = {}
    if accepted_known_misses:
        try:
            validated = validate_accepted_known_misses(accepted_known_misses, canary_p)
        except PreflightError as exc:
            return PreflightCheckResult(
                name="canary_floors",
                passed=False,
                message=f"Accepted known miss rejected before any query: {exc}",
            )
        accepted_by_key = {(m.question_id, m.graph_arm, m.check): m for m in validated}
    known_miss_outcomes: list[CanaryKnownMissOutcome] = []
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
        req_seed_path = row.get("require_seed_path", False)
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

        if answered_snapshots is not None and outcome.answer is not None:
            answered_snapshots.append((
                f"canary {qid} ({arm})",
                outcome.answer.snapshot,
            ))

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
            accepted = accepted_by_key.get((qid, arm, "require_graph_node"))
            if graph_nodes < 1:
                miss_text = (
                    f"Canary {qid} ({arm}) graph floor missed: observed {graph_nodes} "
                    "graph nodes (cause: either a graph defect or canary entities "
                    "not in store pending 06.3.3 D-05 inspection)"
                )
                if accepted is None:
                    failures.append(miss_text)
                elif outcome.status != "failed" and outcome.workflow_meta is not None:
                    known_miss_outcomes.append(
                        CanaryKnownMissOutcome(
                            question_id=qid,
                            graph_arm=arm,
                            check="require_graph_node",
                            decision_id=accepted.decision_id,
                            observed_graph_node_count=graph_nodes,
                            outcome="accepted_known_miss",
                        )
                    )
                else:
                    failures.append(
                        f"{miss_text}; not accepted under {accepted.decision_id}: "
                        "the query did not complete with graph metadata"
                    )
            elif accepted is not None:
                known_miss_outcomes.append(
                    CanaryKnownMissOutcome(
                        question_id=qid,
                        graph_arm=arm,
                        check="require_graph_node",
                        decision_id=accepted.decision_id,
                        observed_graph_node_count=graph_nodes,
                        outcome="floor_met",
                    )
                )

        # 2b. Seed-to-seed path check (D-80): never an accepted known miss.
        if req_seed_path:
            unmet = _seed_path_unmet(outcome.workflow_meta, observed_chunks)
            if unmet is not None:
                failures.append(
                    f"Canary {qid} ({arm}) require_seed_path floor missed: {unmet}"
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

    outcome_detail = [o.model_dump() for o in known_miss_outcomes]
    if failures:
        failure_detail: dict[str, Any] = {"failure_count": len(failures)}
        if outcome_detail:
            failure_detail["accepted_known_misses"] = outcome_detail
        return PreflightCheckResult(
            name="canary_floors",
            passed=False,
            message="; ".join(failures),
            detail=failure_detail,
        )

    accepted_misses = [
        o for o in known_miss_outcomes if o.outcome == "accepted_known_miss"
    ]
    if accepted_misses:
        miss_lines = "; ".join(
            f"ACCEPTED KNOWN MISS [{o.decision_id}]: canary {o.question_id} "
            f"({o.graph_arm}) {o.check} observed {o.observed_graph_node_count} "
            "graph nodes"
            for o in accepted_misses
        )
        return PreflightCheckResult(
            name="canary_floors",
            passed=True,
            status="accepted_known_miss",
            message=(
                f"{miss_lines}; {len(rows) - len(accepted_misses)} of {len(rows)} "
                "canary rows met every floor against live engine budgets."
            ),
            detail={"canary_count": len(rows), "accepted_known_misses": outcome_detail},
        )

    message = f"All {len(rows)} canaries passed floors against live engine budgets."
    detail: dict[str, Any] = {"canary_count": len(rows)}
    if known_miss_outcomes:
        message += " " + " ".join(
            f"Canary {o.question_id} ({o.graph_arm}) met its {o.check} floor: "
            f"observed {o.observed_graph_node_count} graph nodes; "
            f"{o.decision_id} exception not used."
            for o in known_miss_outcomes
        )
        detail["accepted_known_misses"] = outcome_detail
    return PreflightCheckResult(
        name="canary_floors",
        passed=True,
        message=message,
        detail=detail,
    )


def check_index_identity(
    settings: EvalSettings, corpus_name: str
) -> PreflightCheckResult:
    """Wrap the three-way identity comparison as a preflight check.

    Never raises: any exception from `compute_identity` (including a missing
    document map) becomes `passed=False` with the exception text as the message.
    """
    from lancet_eval.identity import compute_identity

    try:
        report = compute_identity(settings, corpus_name)
    except Exception as exc:
        return PreflightCheckResult(
            name="index_identity",
            passed=False,
            message=f"Index identity gate could not run: {exc}",
        )

    if not report.passed:
        return PreflightCheckResult(
            name="index_identity",
            passed=False,
            message="Index identity mismatch: " + "; ".join(report.failures),
            detail={
                "failures": report.failures,
                "alias_ids": report.alias_ids,
                "staged_rows": report.staged_rows,
            },
        )

    return PreflightCheckResult(
        name="index_identity",
        passed=True,
        message="PostgreSQL, LanceDB, and document map document IDs agree.",
        detail={"map_size": len(report.map_ids), "staged_rows": report.staged_rows},
    )


def run_preflight_checks(
    corpus_name: str,
    judged: bool = False,
    settings: EvalSettings | None = None,
    client: httpx.Client | None = None,
    generation_model: str = "deepseek/deepseek-v4-flash-0731",
    accepted_known_misses: Sequence[AcceptedKnownMiss] = (),
) -> list[PreflightCheckResult]:
    """Execute the full preflight checklist and return all results.

    Raises ``PreflightError`` before any check or request when an accepted known miss
    (D-94) is not the registered one.
    """
    import httpx

    validate_accepted_known_misses(accepted_known_misses)
    settings = settings or load_settings()
    results: list[PreflightCheckResult] = []

    # 1. Store isolation
    results.append(check_store_isolation(settings))

    # 2. Index identity (must agree across stores before any live check runs)
    results.append(check_index_identity(settings, corpus_name))

    # 3. Canary manifest check (unconditional, independent of gateway/engine)
    results.append(check_canary_manifest())

    # 4. Gateway and engine reachability
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

        # 5. Gated live checks: corpus generation and canary floors
        if gw_check.passed and eng_check.passed:
            generation_check = check_corpus_generation(client, corpus_name)
            answered: list[tuple[str, RetrievalSnapshot]] = []
            canary_check = check_canary_floors(
                client,
                accepted_known_misses=accepted_known_misses,
                answered_snapshots=answered,
            )
            if generation_check.detail.get("probe_snapshot_missing"):
                generation_check = corpus_generation_from_canaries(
                    corpus_name, answered
                )
            results.append(generation_check)
            results.append(canary_check)
    finally:
        if should_close_client:
            client.close()

    # 6. OpenRouter API key check
    api_key = os.getenv("OPENROUTER_API_KEY")
    results.append(check_openrouter_api(api_key, judged))

    # 7. Model differentiation check
    if judged:
        results.append(
            check_model_differentiation(generation_model, settings.judge_model)
        )

    return results
