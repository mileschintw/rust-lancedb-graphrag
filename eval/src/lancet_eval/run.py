"""Two-armed benchmark runner driving queries across graph-on and graph-off arms."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path

import httpx

from lancet_eval.client import run_query
from lancet_eval.config import EvalSettings
from lancet_eval.corpus import GoldQuestion, load_corpus_config, load_sample_questions
from lancet_eval.journal import Journal, RunRecord, journal_key, load_done

# The sole durable arm-to-flag mapping in the evaluation harness (Task 1 / D-47).
GRAPH_ARMS: dict[str, bool] = {
    "graph-on": False,
    "graph-off": True,
}


def drive_one(
    client: httpx.Client,
    *,
    corpus: str,
    question: GoldQuestion,
    arm: str,
    partial: bool = False,
    deadline_s: float = 600.0,
) -> RunRecord:
    """Drive a single question work unit through the gateway.

    Guaranteed never to raise: transport failures, stream abortions, and validation
    errors become durable error records with outcome='error' so sibling results are
    never discarded.
    """
    disable_graph_context = GRAPH_ARMS.get(arm, False)

    try:
        outcome = run_query(
            client,
            query=question.question,
            disable_graph_context=disable_graph_context,
            deadline_s=deadline_s,
        )

        answer_text = outcome.answer.answer if outcome.answer else ""
        snapshot = outcome.answer.snapshot if outcome.answer else None
        index_generation = snapshot.index_generation if snapshot else ""
        structured_citations = (
            outcome.answer.structured_citations if outcome.answer else []
        )

        return RunRecord(
            corpus=corpus,
            question_id=question.id,
            graph_arm=arm,
            outcome="success",
            answer=answer_text,
            snapshot=snapshot,
            structured_citations=structured_citations,
            notices=outcome.notices,
            node_failures=outcome.node_failures,
            duration_ms=float(outcome.duration_ms),
            session_id=outcome.session_id,
            correlation_id=outcome.correlation_id,
            index_generation=index_generation,
            partial=partial,
        )
    except Exception as exc:
        return RunRecord(
            corpus=corpus,
            question_id=question.id,
            graph_arm=arm,
            outcome="error",
            partial=partial,
            error_type=type(exc).__name__,
            error=str(exc),
        )


def drive(
    *,
    corpus: str,
    journal_path: Path | str,
    settings: EvalSettings | None = None,
    limit: int | None = None,
    resume: bool = True,
    workers: int = 1,
    client: httpx.Client | None = None,
) -> int:
    """Drive questions across graph-on and graph-off arms into a journal.

    Returns the number of executed work units.
    """
    eval_settings = settings or EvalSettings()
    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    partial = limit is not None
    if limit is not None:
        questions = questions[:limit]

    # Build work units: cross product of questions and confirmed arms
    work_units: list[tuple[GoldQuestion, str]] = [
        (q, arm) for q in questions for arm in config.arms
    ]

    target_path = Path(journal_path)
    done_keys = load_done(target_path) if resume else set()

    remaining_units = [
        (q, arm)
        for q, arm in work_units
        if journal_key(corpus, q.id, arm) not in done_keys
    ]

    journal = Journal(target_path)
    journal.write_header(corpus=corpus, partial=partial)

    if not remaining_units:
        return 0

    effective_workers = max(1, workers)
    limits = httpx.Limits(
        max_connections=effective_workers,
        max_keepalive_connections=effective_workers,
    )

    should_close_client = client is None
    eval_client = client or httpx.Client(
        base_url=eval_settings.gateway_url,
        limits=limits,
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0),
    )

    executed_count = 0
    try:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=effective_workers
        ) as executor:
            future_to_unit = {
                executor.submit(
                    drive_one,
                    eval_client,
                    corpus=corpus,
                    question=q,
                    arm=arm,
                    partial=partial,
                    deadline_s=eval_settings.question_deadline_secs,
                ): (q, arm)
                for q, arm in remaining_units
            }

            for future in concurrent.futures.as_completed(future_to_unit):
                record = future.result()
                journal.append(record)
                executed_count += 1
    finally:
        if should_close_client:
            eval_client.close()

    return executed_count
