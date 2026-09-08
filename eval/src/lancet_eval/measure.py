"""Measurement driver for latency calibration passes and timeout budget derivation."""

from __future__ import annotations

import concurrent.futures
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import ConfigDict

from lancet_eval.client import QueryOutcome, run_query
from lancet_eval.config import EvalSettings, load_settings, pg_schema_of, repo_root
from lancet_eval.corpus import GoldQuestion, load_corpus
from lancet_eval.journal import (
    NodeTiming,
    RunRecord,
    WorkflowWireMeta,
)
from lancet_eval.latency import (
    CensoringLabel,
    NodeDurationExtraction,
    check_harness_ceilings,
    check_nesting_invariants,
    compute_censoring_census,
    derive_budget,
    derive_provider_contract_budget,
    extract_node_durations,
    percentile_with_ci,
)
from lancet_eval.preflight import read_effective_workflow_config
from lancet_eval.thresholds import COMMITTED_THRESHOLDS, DecisionThresholds

if TYPE_CHECKING:
    from lancet_eval.raw_events import RawEventSink

logger = logging.getLogger(__name__)

# Two arms to evaluate for every question
MEASUREMENT_ARMS: tuple[str, str] = ("graph-off", "graph-on")

# Pricing per million tokens (OpenRouter estimates)
GENERATION_INPUT_PRICE_PER_1M = 0.14
GENERATION_OUTPUT_PRICE_PER_1M = 0.28
# Voyage 4 large pricing per million tokens
EMBEDDING_PRICE_PER_1M = 0.12
ESTIMATED_EMBEDDING_TOKENS_PER_QUERY = 120


class MeasurementRecord(RunRecord):
    """Durable record of a measurement run with dispatch ordinal and segment."""

    model_config = ConfigDict(extra="forbid")

    ordinal: int
    segment: str
    warm_up: bool = False
    question_type: str = ""
    dropped_node_timings: int = 0


class SpendHaltError(RuntimeError):
    """Raised when spend cap is exceeded or allowance cannot be verified."""


class SchemaIsolationError(RuntimeError):
    """Raised when database schema is not isolated from eval baseline schema."""


def resolve_measurement_run_dir(corpus_name: str, root: Path | None = None) -> Path:
    """Generate distinct measurement directory un-ignored by git.

    Matches '*-measure-<corpus>' disjoint from benchmark glob '????-??-??-<corpus>'.
    """
    base = root or (repo_root() / "eval" / "runs")
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    return base / f"{date_str}-measure-{corpus_name}"


def compute_spend(
    records: Sequence[RunRecord],
    include_embeddings: bool = True,
) -> tuple[float, bool]:
    """Calculate token-based spend in USD across records.

    Returns (spend_usd, is_lower_bound).
    If include_embeddings is False, returns generation-only spend marked as lower bound.
    """
    total_prompt_tokens = 0
    total_completion_tokens = 0
    query_count = len(records)

    for rec in records:
        if rec.workflow_meta is not None:
            total_prompt_tokens += rec.workflow_meta.prompt_tokens
            total_completion_tokens += rec.workflow_meta.completion_tokens

    gen_spend = (total_prompt_tokens / 1_000_000.0) * GENERATION_INPUT_PRICE_PER_1M + (
        total_completion_tokens / 1_000_000.0
    ) * GENERATION_OUTPUT_PRICE_PER_1M

    if not include_embeddings:
        return gen_spend, True

    # Price embedding model alongside generation model per query
    emb_tokens = query_count * ESTIMATED_EMBEDDING_TOKENS_PER_QUERY
    emb_spend = (emb_tokens / 1_000_000.0) * EMBEDDING_PRICE_PER_1M
    return gen_spend + emb_spend, False


def check_provider_allowance(
    api_key: str | None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Check provider remaining allowance from OpenRouter auth key endpoint.

    Fails closed if the balance/allowance cannot be verified.
    """
    if not api_key or not api_key.strip():
        raise SpendHaltError(
            "OPENROUTER_API_KEY is unset or empty; cannot verify allowance."
        )

    own_client = False
    if client is None:
        client = httpx.Client(timeout=10.0)
        own_client = True

    try:
        resp = client.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key.strip()}"},
        )
        if resp.status_code != 200:
            raise SpendHaltError(
                f"Provider key-status endpoint returned HTTP {resp.status_code}: "
                f"{resp.text[:200]}"
            )
        data = resp.json().get("data", {})
        limit = data.get("limit")
        usage = data.get("usage", 0.0)
        limit_remaining = data.get("limit_remaining")
        return {
            "usage": usage,
            "limit": limit,
            "limit_remaining": limit_remaining,
        }
    except Exception as exc:
        if isinstance(exc, SpendHaltError):
            raise
        raise SpendHaltError(f"Failed to read provider allowance: {exc}") from exc
    finally:
        if own_client:
            client.close()


def assert_measurement_state_isolated(
    target_dsn: str,
    eval_dsn: str,
) -> None:
    """Assert database schema does not collide with eval schema."""
    target_schema = pg_schema_of(target_dsn)
    eval_schema = pg_schema_of(eval_dsn)

    if not target_schema:
        raise SchemaIsolationError("Target database schema cannot be empty.")
    if target_schema == eval_schema:
        raise SchemaIsolationError(
            f"Isolation collision: target schema {target_schema!r} equals "
            f"eval schema {eval_schema!r}. "
            "Measurement pass would contaminate workflow_checkpoints baseline."
        )


def measure_one(
    client: httpx.Client,
    *,
    corpus: str,
    question: GoldQuestion,
    arm: str,
    ordinal: int,
    segment: str,
    warm_up: bool = False,
    deadline_s: float = 600.0,
    read_timeout_s: float | None = None,
    raw_sink: RawEventSink | None = None,
) -> MeasurementRecord:
    """Drive a single measurement query unit and return durable MeasurementRecord.

    Never raises: network errors become error records with ordinal intact.
    """
    disable_graph = arm == "graph-off"

    try:
        outcome: QueryOutcome = run_query(
            client,
            query=question.question,
            disable_graph_context=disable_graph,
            deadline_s=deadline_s,
            read_timeout_s=read_timeout_s,
            capture_raw_events=raw_sink is not None,
        )

        outcome_literal = "error" if outcome.status == "failed" else "success"
        answer_text = outcome.answer.answer if outcome.answer else ""

        snapshot = (
            outcome.answer.snapshot
            if (outcome.answer and outcome.answer.snapshot is not None)
            else outcome.partial_snapshot
        )
        index_generation = snapshot.index_generation if snapshot else ""
        structured_citations = (
            outcome.answer.structured_citations if outcome.answer else []
        )

        node_timings = [
            NodeTiming(
                node_name=t.node_name,
                duration_ms=float(t.duration_ms if t.duration_ms is not None else 0.0),
            )
            for t in outcome.node_timings
            if t.duration_ms is not None
        ]

        workflow_meta = None
        if outcome.workflow_meta is not None:
            workflow_meta = WorkflowWireMeta(
                started_at_ms=outcome.workflow_meta.started_at_ms,
                completed_at_ms=outcome.workflow_meta.completed_at_ms,
                reformulation_used=outcome.workflow_meta.reformulation_used,
                vector_count=outcome.workflow_meta.vector_count,
                bm25_count=outcome.workflow_meta.bm25_count,
                graph_node_count=outcome.workflow_meta.graph_node_count,
                graph_edge_count=outcome.workflow_meta.graph_edge_count,
                prompt_tokens=outcome.workflow_meta.prompt_tokens,
                completion_tokens=outcome.workflow_meta.completion_tokens,
                degraded_mode=outcome.workflow_meta.degraded_mode,
                graph_prompt_fact_count=outcome.workflow_meta.graph_prompt_fact_count,
            )

        return MeasurementRecord(
            corpus=corpus,
            question_id=question.id,
            graph_arm=arm,
            ordinal=ordinal,
            segment=segment,
            warm_up=warm_up,
            question_type=getattr(question, "question_type", ""),
            dropped_node_timings=outcome.dropped_node_timings,
            outcome=outcome_literal,
            answer=answer_text,
            snapshot=snapshot,
            structured_citations=structured_citations,
            notices=outcome.notices,
            node_failures=outcome.node_failures,
            duration_ms=float(outcome.duration_ms),
            session_id=outcome.session_id,
            correlation_id=outcome.correlation_id,
            index_generation=index_generation,
            partial=False,
            node_timings=node_timings,
            workflow_meta=workflow_meta,
        )
    except Exception as exc:
        return MeasurementRecord(
            corpus=corpus,
            question_id=question.id,
            graph_arm=arm,
            ordinal=ordinal,
            segment=segment,
            warm_up=warm_up,
            question_type=getattr(question, "question_type", ""),
            outcome="error",
            partial=False,
            error_type=type(exc).__name__,
            error=str(exc),
        )


@dataclass(frozen=True)
class BudgetDerivation:
    """Pure post-drive budget derivation over already-collected records."""

    census: Any
    durations: NodeDurationExtraction
    censored_by_node: dict[str, int]
    proposed_budgets: dict[str, int]
    proposed_records: list[dict[str, Any]]
    nesting_report: Any
    ceiling_report: Any


def derive_budgets_from_records(
    analysis_records: Sequence[Any],
    effective_cfg: dict[str, Any],
    thresholds: DecisionThresholds,
    sse_read_timeout_s: float,
    question_deadline_s: float,
) -> BudgetDerivation:
    """Derive proposed budgets from records without querying a live gateway."""
    node_to_key = {
        "ReformulateQuery": "reformulate_timeout_ms",
        "RetrieveHybrid": "retrieve_timeout_ms",
        "ExtractGraphContext": "graph_node_timeout_ms",
        "AssemblePrompt": "prompt_timeout_ms",
        "GenerateAnswer": "generation_node_timeout_ms",
    }
    ceilings = {
        node: float(effective_cfg.get(k, float("inf")))
        for node, k in node_to_key.items()
    }
    census = compute_censoring_census(analysis_records, ceilings)
    extraction = extract_node_durations(
        analysis_records, ceilings_by_node=ceilings
    )

    proposed_budgets: dict[str, int] = {}
    proposed_records: list[dict[str, Any]] = []
    censored_by_node: dict[str, int] = {}

    for node, vals in extraction.by_node.items():
        if node == "GenerateAnswer":
            p_rec = derive_provider_contract_budget()
            proposed_budgets["generation_node_timeout_ms"] = p_rec.proposed_ms
            proposed_records.append(p_rec.__dict__)
            censored_by_node[node] = 0
            continue

        if node == "ReformulateQuery":
            censored_by_node[node] = 0
            continue

        node_census = census.node_counts.get(node, {})
        censored = extraction.dropped_at_ceiling.get(node, 0) + node_census.get(
            CensoringLabel.CENSORED_NODE_TIMEOUT.value, 0
        )
        censored_by_node[node] = censored
        cfg_key = node_to_key[node]
        pct = percentile_with_ci(
            vals,
            p=thresholds.derivation_percentile,
            seed=thresholds.bootstrap_seed,
            censored_count=censored,
        )
        if not pct.is_available:
            proposed_records.append({
                "node_or_budget": cfg_key,
                "proposed_ms": None,
                "percentile_value_ms": None,
                "multiplier": thresholds.multiplier,
                "rule": "derivation_refused_empty_or_unavailable",
                "sample_size": pct.sample_size,
                "censored_status": (
                    f"unavailable({pct.reason}; censored_count={censored})"
                ),
                "provenance": thresholds.provenance,
                "is_invariant_driven": False,
            })
            continue
        p_rec = derive_budget(cfg_key, pct, thresholds=thresholds)
        proposed_budgets[cfg_key] = p_rec.proposed_ms
        proposed_records.append(p_rec.__dict__)

    if "query_embedding_timeout_ms" not in proposed_budgets:
        proposed_budgets["query_embedding_timeout_ms"] = effective_cfg.get(
            "query_embedding_timeout_ms", 10000
        )
        proposed_records.append({
            "node_or_budget": "query_embedding_timeout_ms",
            "proposed_ms": proposed_budgets["query_embedding_timeout_ms"],
            "percentile_value_ms": None,
            "multiplier": None,
            "rule": "carried_forward_unmeasured",
            "sample_size": 0,
            "censored_status": "not_applicable_unmeasured_inner",
            "provenance": "effective workflow config (not derived from this pass)",
            "is_invariant_driven": False,
        })
    if "graph_operation_timeout_ms" not in proposed_budgets:
        proposed_budgets["graph_operation_timeout_ms"] = effective_cfg.get(
            "graph_operation_timeout_ms", 4000
        )
        proposed_records.append({
            "node_or_budget": "graph_operation_timeout_ms",
            "proposed_ms": proposed_budgets["graph_operation_timeout_ms"],
            "percentile_value_ms": None,
            "multiplier": None,
            "rule": "carried_forward_unmeasured",
            "sample_size": 0,
            "censored_status": "not_applicable_unmeasured_inner",
            "provenance": "effective workflow config (not derived from this pass)",
            "is_invariant_driven": False,
        })

    nesting_rep = check_nesting_invariants(
        proposed_budgets, required_slack_ms=thresholds.slack_ms
    )
    ceiling_rep = check_harness_ceilings(
        nesting_rep.resolved_budgets,
        sse_read_timeout_s=sse_read_timeout_s,
        question_deadline_s=question_deadline_s,
    )
    return BudgetDerivation(
        census=census,
        durations=extraction,
        censored_by_node=censored_by_node,
        proposed_budgets=nesting_rep.resolved_budgets,
        proposed_records=proposed_records,
        nesting_report=nesting_rep,
        ceiling_report=ceiling_rep,
    )


def run_measurement_pass(
    corpus_name: str = "multihop_rag",
    sample_size_questions: int = 10,
    segment_boundary_ordinal: int = 500,
    warm_up_count: int = 2,
    stage_spend_cap: float = 5.0,
    output_dir: Path | None = None,
    client: httpx.Client | None = None,
    settings: EvalSettings | None = None,
    thresholds: DecisionThresholds | None = None,
    check_allowance: bool = True,
    workers: int = 1,
) -> tuple[Path, dict[str, Any]]:
    """Execute two-armed measurement drive over gold questions.

    For N questions, dispatches 2N queries adjacently across both experimental arms.
    """
    settings = settings or load_settings()
    thresholds = thresholds or COMMITTED_THRESHOLDS
    run_dir = output_dir or resolve_measurement_run_dir(corpus_name)
    run_dir.mkdir(parents=True, exist_ok=True)
    journal_path = run_dir / "journal.jsonl"

    corpus = load_corpus(corpus_name)
    selected_questions = corpus.questions[:sample_size_questions]

    # Preflight allowance check
    if check_allowance:
        check_provider_allowance(settings.openrouter_api_key)

    # State isolation check: verify target does not collide with eval schema
    eval_dsn = settings.database_url
    dev_dsn = settings.dev_database_url
    if dev_dsn and dev_dsn.strip():
        assert_measurement_state_isolated(dev_dsn, eval_dsn)

    # Build work units with assigned monotonic dispatch ordinals
    # Each question generates 2 work units (graph-off, graph-on) dispatched adjacently
    work_units: list[dict[str, Any]] = []
    current_ordinal = 1

    # Warm-up queries
    for q in selected_questions[:warm_up_count]:
        for arm in MEASUREMENT_ARMS:
            work_units.append({
                "question": q,
                "arm": arm,
                "ordinal": current_ordinal,
                "segment": "warm-up",
                "warm_up": True,
            })
            current_ordinal += 1

    # Measured queries
    for q in selected_questions:
        segment = (
            "segment-1" if current_ordinal <= segment_boundary_ordinal else "segment-2"
        )
        for arm in MEASUREMENT_ARMS:
            work_units.append({
                "question": q,
                "arm": arm,
                "ordinal": current_ordinal,
                "segment": segment,
                "warm_up": False,
            })
            current_ordinal += 1

    records: list[MeasurementRecord] = []
    own_client = False
    effective_client = client
    if effective_client is None:
        effective_client = httpx.Client(
            base_url=settings.gateway_url,
            timeout=httpx.Timeout(
                connect=10.0,
                read=settings.gateway_timeout_secs,
                write=30.0,
                pool=10.0,
            ),
        )
        own_client = True

    try:
        with open(journal_path, "a", encoding="utf-8") as jf:
            if workers <= 1:
                for u in work_units:
                    # Check spend stop-rule
                    spend, _ = compute_spend(records, include_embeddings=True)
                    if spend >= stage_spend_cap:
                        logger.warning(
                            "Stage spend cap $%.2f reached. Halting drive.",
                            stage_spend_cap,
                        )
                        break

                    rec = measure_one(
                        effective_client,
                        corpus=corpus_name,
                        question=u["question"],
                        arm=u["arm"],
                        ordinal=u["ordinal"],
                        segment=u["segment"],
                        warm_up=u["warm_up"],
                        deadline_s=settings.question_deadline_secs,
                        read_timeout_s=settings.gateway_timeout_secs,
                    )
                    records.append(rec)
                    jf.write(rec.model_dump_json() + "\n")
                    jf.flush()
            else:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=workers
                ) as executor:
                    futures = [
                        executor.submit(
                            measure_one,
                            effective_client,
                            corpus=corpus_name,
                            question=u["question"],
                            arm=u["arm"],
                            ordinal=u["ordinal"],
                            segment=u["segment"],
                            warm_up=u["warm_up"],
                            deadline_s=settings.question_deadline_secs,
                            read_timeout_s=settings.gateway_timeout_secs,
                        )
                        for u in work_units
                    ]
                    for fut in concurrent.futures.as_completed(futures):
                        rec = fut.result()
                        records.append(rec)
                        jf.write(rec.model_dump_json() + "\n")
                        jf.flush()
    finally:
        if own_client:
            effective_client.close()

    # Post-drive analysis and summary record
    analysis_records = [r for r in records if not r.warm_up]
    effective_cfg = read_effective_workflow_config()
    derivation = derive_budgets_from_records(
        analysis_records,
        effective_cfg,
        thresholds,
        sse_read_timeout_s=settings.gateway_timeout_secs,
        question_deadline_s=settings.question_deadline_secs,
    )
    census = derivation.census
    nesting_rep = derivation.nesting_report
    ceiling_rep = derivation.ceiling_report

    total_spend, is_lower = compute_spend(records, include_embeddings=True)

    summary: dict[str, Any] = {
        "calibration_note": (
            "This micro-pass is calibration of the instrument only and "
            "is not an input to any derived budget."
        ),
        "corpus": corpus_name,
        "sample_size_questions": sample_size_questions,
        "total_records_emitted": len(records),
        "measured_records": len(analysis_records),
        "raised_budgets": effective_cfg,
        "sse_read_timeout_s": settings.gateway_timeout_secs,
        "question_deadline_s": settings.question_deadline_secs,
        "spend_summary": {
            "spend_usd": total_spend,
            "includes_embeddings": not is_lower,
            "stage_spend_cap": stage_spend_cap,
        },
        "censoring_census": {
            "total_records": census.total_records,
            "node_counts": census.node_counts,
            "inner_labels": census.inner_labels,
        },
        "proposed_budgets": nesting_rep.resolved_budgets,
        "proposed_records": derivation.proposed_records,
        "censored_by_node": derivation.censored_by_node,
        "nesting_report": {
            "has_violations": nesting_rep.has_violations,
            "groups": [g.__dict__ for g in nesting_rep.groups],
        },
        "ceiling_report": ceiling_rep.__dict__,
        "run_timestamp": datetime.now(UTC).isoformat(),
    }

    for name in ("run_record.json", "measurement.json"):
        with open(run_dir / name, "w", encoding="utf-8") as sf:
            json.dump(summary, sf, indent=2)

    return run_dir, summary
