"""Benchmark runner driving queries across the arms a corpus declares."""

from __future__ import annotations

import concurrent.futures
import logging
import re
import time
from pathlib import Path

import httpx

from lancet_eval import gitcheck
from lancet_eval.arms import plan_work_units, request_fields, resolve_arm
from lancet_eval.client import run_query
from lancet_eval.config import EvalSettings, repo_root
from lancet_eval.corpus import (
    CorpusConfig,
    GoldQuestion,
    load_corpus_config,
    load_sample_questions,
)
from lancet_eval.identity import require_index_identity
from lancet_eval.journal import (
    AttemptRecord,
    Journal,
    JournalReuseError,
    NodeTiming,
    RunRecord,
    WorkflowWireMeta,
    journal_key,
    load_done,
    load_records,
    read_journal_header,
    reconcile_header,
)
from lancet_eval.measure import compute_spend
from lancet_eval.raw_events import RawEventSink, baseline_sample_ids
from lancet_eval.split import (
    HeldOutSplit,
    load_split,
    split_input_problems,
    split_sha256,
)

logger = logging.getLogger(__name__)


class DriveResult(int):
    """Result of drive() execution with spend and cap reporting."""

    executed_count: int
    stopped_by_cap: bool
    observed_spend: float

    def __new__(
        cls,
        executed_count: int,
        stopped_by_cap: bool = False,
        observed_spend: float = 0.0,
    ) -> DriveResult:
        val = super().__new__(cls, executed_count)
        val.executed_count = executed_count
        val.stopped_by_cap = stopped_by_cap
        val.observed_spend = observed_spend
        return val

    @property
    def capped(self) -> bool:
        return self.stopped_by_cap

# Legacy read-only view of the two drive 1/1b/2 labels. The sole durable arm-to-flag
# mapping is `lancet_eval.arms.ARM_REGISTRY` (D-101); requests derive from it.
GRAPH_ARMS: dict[str, bool] = {
    "graph-on": False,
    "graph-off": True,
}


# A gate-stage label is the one `unpark_gates --stage` will be given; short ASCII keeps
# the journal header and the gate markdown free of whitespace and control characters.
_GATE_STAGE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _require_matching_journal_marker(
    path: Path, *, gate_stage: str | None, max_retries: int
) -> None:
    """Refuse to append to a journal whose header does not describe this drive.

    The header written by the first invocation must describe every record after it
    (06.3.4.1-33, D-67), with or without ``--resume``. A header that carries a marker
    must equal this drive's ``(gate_stage, max_retries)``; an unmarked or missing header
    is refused only by a gate-stage drive. A new or empty file is always fine: the
    header is written after this check.
    """
    if not path.is_file() or path.stat().st_size == 0:
        return
    header = read_journal_header(path)
    if header is not None and ("gate_stage" in header or "max_retries" in header):
        found = (header.get("gate_stage"), header.get("max_retries"))
        if found != (gate_stage, max_retries):
            raise ValueError(
                f"journal {path} was started with gate_stage={found[0]!r}, "
                f"max_retries={found[1]!r} but this drive has "
                f"gate_stage={gate_stage!r}, max_retries={max_retries!r}; "
                "refusing to append records its header does not describe"
            )
        return
    if gate_stage is not None:
        raise ValueError(
            f"journal {path} has no gate_stage marker in its header, so a gate-stage "
            f"drive (gate_stage={gate_stage!r}) cannot append to it; use a new journal"
        )


def _require_matching_split_marker(path: Path, split: HeldOutSplit | None) -> None:
    """Refuse to append to a journal begun under a different split or seed (D-107).

    A ``[split]`` drive records ``order_seed`` and ``split_sha256`` in the header it
    writes. An existing non-empty journal must carry both and they must equal this
    drive's, so a resumed drive never recomputes the rotation from a split file that
    changed since the journal was started. A drive without a split refuses a journal
    whose header carries either marker. A new or empty file is always fine.
    """
    if not path.is_file() or path.stat().st_size == 0:
        return
    header = read_journal_header(path) or {}
    carried = {k: header[k] for k in ("order_seed", "split_sha256") if k in header}
    if split is None:
        if carried:
            raise ValueError(
                f"journal {path} was started under a held-out split ({sorted(carried)} "
                "in its header) but this drive has none; refusing to append"
            )
        return
    expected = {"order_seed": split.order_seed, "split_sha256": split_sha256(split)}
    if carried != expected:
        missing = sorted(set(expected) - set(carried))
        detail = (
            f"its header lacks {missing}"
            if missing
            else f"its header has {carried}, this drive has {expected}"
        )
        raise ValueError(
            f"journal {path} was not started under this split and seed: {detail}; "
            "refusing to append records its header does not describe (D-107)"
        )


def _enforce_split_role(
    config: CorpusConfig, split: HeldOutSplit, questions: list[GoldQuestion]
) -> None:
    """Refuse a corpus whose question IDs do not fit its declared split role.

    A ``heldout`` corpus must hold exactly the split's held-out IDs (D-105). A
    ``rehearsal`` corpus must hold none of the dev or held-out IDs (D-106), so the
    paid rehearsal can never spend a held-out or dev question. A ``dev`` corpus must
    hold only dev IDs: a subset of the split's dev IDs, disjoint from the held-out
    IDs (D-170). Runs before any journal I/O and before any request.
    """
    ids = [q.question_id for q in questions]
    heldout = set(split.heldout_g_ids) | set(split.heldout_null_ids)
    if config.split_role == "heldout":
        got = set(ids)
        if len(ids) != len(got) or got != heldout:
            raise ValueError(
                f"heldout corpus {config.name!r} holds {len(ids)} question IDs "
                f"({len(got)} distinct) but the committed split's held-out set has "
                f"{len(heldout)} ({len(split.heldout_g_ids)} G + "
                f"{len(split.heldout_null_ids)} null): {len(heldout - got)} missing, "
                f"{len(got - heldout)} outside the held-out split; refusing to drive"
            )
    elif config.split_role == "dev":
        outside = set(ids) - set(split.dev_ids)
        leaked_heldout = set(ids) & heldout
        if outside or leaked_heldout:
            raise ValueError(
                f"dev corpus {config.name!r} holds {len(outside | leaked_heldout)} "
                f"question ID(s) outside the committed split's dev IDs "
                f"({len(leaked_heldout)} of them held-out); a dev corpus must be a "
                "subset of the dev IDs and disjoint from the held-out IDs (D-170); "
                "refusing to drive"
            )
    elif config.split_role == "rehearsal":
        leaked = set(ids) & (heldout | set(split.dev_ids))
        if leaked:
            raise ValueError(
                f"rehearsal corpus {config.name!r} holds {len(leaked)} dev or "
                "held-out question ID(s); a rehearsal must be disjoint from both "
                "(D-106); refusing to drive"
            )


def _attempt_of(record: RunRecord, attempt: int) -> AttemptRecord:
    """The AttemptRecord a retry is about to supersede (06.3.4.1-33, CR-03)."""
    return AttemptRecord(
        attempt=attempt,
        outcome=record.outcome,
        answer_chars=len(record.answer or ""),
        error_type=record.error_type,
        error=record.error,
        node_failures=list(record.node_failures),
        node_timings=list(record.node_timings),
        workflow_meta=record.workflow_meta,
        duration_ms=record.duration_ms,
        correlation_id=record.correlation_id,
        session_id=record.session_id,
    )


def drive_one(
    client: httpx.Client,
    *,
    corpus: str,
    question: GoldQuestion,
    arm: str,
    partial: bool = False,
    deadline_s: float = 600.0,
    read_timeout_s: float | None = None,
    raw_sink: RawEventSink | None = None,
    baseline_ids: set[str] | None = None,
    max_retries: int = 0,
) -> RunRecord:
    """Drive a single question work unit through the gateway.

    Guaranteed never to raise: transport failures, stream abortions, and validation
    errors become durable error records with outcome='error' so sibling results are
    never discarded. Retries up to max_retries on transient failure or early termination.
    """
    # Fails closed on an unknown label (D-101); the flags come from ARM_REGISTRY.
    resolve_arm(arm)
    arm_request_fields = request_fields(arm)

    last_record: RunRecord | None = None
    # Every attempt a retry supersedes stays on the returned record (CR-03, D-67).
    superseded: list[AttemptRecord] = []
    for attempt in range(max_retries + 1):
        try:
            outcome = run_query(
                client,
                query=question.question,
                deadline_s=deadline_s,
                read_timeout_s=read_timeout_s,
                capture_raw_events=raw_sink is not None,
                **arm_request_fields,
            )

            outcome_literal = "error" if outcome.status == "failed" else "success"
            answer_text = outcome.answer.answer if outcome.answer else ""

            # Answer snapshot takes precedence; fallback to failure-path partial_snapshot
            snapshot = (
                outcome.answer.snapshot
                if (outcome.answer and outcome.answer.snapshot is not None)
                else outcome.partial_snapshot
            )
            snapshot_index_generation = snapshot.index_generation if snapshot else ""
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
                    graph_seed_count=outcome.workflow_meta.graph_seed_count,
                    graph_path_found=outcome.workflow_meta.graph_path_found,
                    graph_boosted_chunk_count=outcome.workflow_meta.graph_boosted_chunk_count,
                    graph_degree_capped_count=outcome.workflow_meta.graph_degree_capped_count,
                    graph_seed_document_ids=outcome.workflow_meta.graph_seed_document_ids,
                    rerank=outcome.workflow_meta.rerank,
                    query_embedding_retries=outcome.workflow_meta.query_embedding_retries,
                )

            # Raw event retention: keep when node failure occurred or in baseline set
            if raw_sink is not None and outcome.raw_events is not None:
                should_retain = bool(outcome.node_failures) or (
                    baseline_ids is not None and question.id in baseline_ids
                )
                if should_retain:
                    try:
                        raw_sink.write_events(
                            corpus=corpus,
                            question_id=question.id,
                            graph_arm=arm,
                            events=outcome.raw_events,
                            dropped_frames=outcome.raw_events_dropped_frames,
                            truncated=outcome.raw_events_truncated,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Swallowing raw_sink error for %s:%s: %s",
                            arm,
                            question.id,
                            exc,
                        )

            last_record = RunRecord(
                corpus=corpus,
                question_id=question.id,
                graph_arm=arm,
                outcome=outcome_literal,
                answer=answer_text,
                snapshot=snapshot,
                structured_citations=structured_citations,
                notices=outcome.notices,
                node_failures=outcome.node_failures,
                duration_ms=float(outcome.duration_ms),
                session_id=outcome.session_id,
                correlation_id=outcome.correlation_id,
                index_generation=snapshot_index_generation,
                partial=partial,
                node_timings=node_timings,
                workflow_meta=workflow_meta,
                prior_attempts=list(superseded),
            )

            # If success and non-empty answer, return immediately
            if outcome_literal == "success" and answer_text.strip():
                return last_record

            if attempt < max_retries:
                logger.warning(
                    "Query %s:%s early terminated or failed (outcome=%s, answer_len=%d); retrying (attempt %d/%d)...",
                    question.id,
                    arm,
                    outcome_literal,
                    len(answer_text),
                    attempt + 1,
                    max_retries,
                )
                time.sleep(1.0 * (attempt + 1))
                superseded.append(_attempt_of(last_record, attempt + 1))
                continue

            return last_record

        except Exception as exc:
            last_record = RunRecord(
                corpus=corpus,
                question_id=question.id,
                graph_arm=arm,
                outcome="error",
                partial=partial,
                error_type=type(exc).__name__,
                error=str(exc),
                prior_attempts=list(superseded),
            )
            if attempt < max_retries:
                logger.warning(
                    "Query %s:%s raised exception %s; retrying (attempt %d/%d)...",
                    question.id,
                    arm,
                    exc,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(1.0 * (attempt + 1))
                superseded.append(_attempt_of(last_record, attempt + 1))
                continue
            return last_record

    return last_record or RunRecord(
        corpus=corpus,
        question_id=question.id,
        graph_arm=arm,
        outcome="error",
        partial=partial,
        prior_attempts=list(superseded),
    )


def drive(
    *,
    corpus: str,
    journal_path: Path | str,
    stage_spend_cap: float,
    settings: EvalSettings | None = None,
    limit: int | None = None,
    resume: bool = True,
    workers: int = 1,
    client: httpx.Client | None = None,
    max_retries: int = 0,
    gate_stage: str | None = None,
    git_repo: Path | None = None,
) -> DriveResult:
    """Drive questions across the corpus's arms into a journal.

    Enforces fail-closed stage spend cap in-process with a bounded in-flight window.
    Returns DriveResult with executed count, stopped_by_cap status, and observed spend.

    ``gate_stage`` declares a gate-stage drive (D-67): it requires ``max_retries == 0``,
    is recorded in the journal header with ``max_retries``, and the drive refuses to
    append to a journal whose header marker differs from its own. ``resume=False``
    refuses a journal that already holds records (`JournalReuseError`, WR-03).

    A `[split]` corpus is refused, before any journal I/O, unless the commit introducing
    `PREREGISTRATION_06_3_5` is an ancestor of HEAD and `eval/src/lancet_eval/` has no
    uncommitted change (D-73). ``git_repo`` points that check at another repository; it
    is the live repository when None.
    """
    eval_settings = settings or EvalSettings()
    require_index_identity(eval_settings, corpus)

    if gate_stage is not None:
        if not _GATE_STAGE_LABEL.fullmatch(gate_stage):
            raise ValueError(
                f"invalid gate-stage label {gate_stage!r}: expected 1-64 characters "
                "from A-Z a-z 0-9 . _ -, starting with a letter or digit"
            )
        if max_retries != 0:
            raise ValueError(
                "gate-stage drives require --retries 0 (D-67): a retry would replace "
                f"an attempt the gates must see (got max_retries={max_retries})"
            )

    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    is_limited = limit is not None
    split: HeldOutSplit | None = None
    if config.split_file is not None:
        # D-73: the pre-registration is committed before any paid held-out request, on
        # the corpus's own configured token. D-170: a `dev` corpus is exempt, because
        # dev reads precede the freeze commit that introduces the 06.3.6 token.
        if config.split_role != "dev":
            problems = gitcheck.preregistration_problems(
                (config.preregistration_token,),
                require_clean_tree=True,
                unchanged_since_introduction=True,
                repo=git_repo,
            )
            if problems:
                raise gitcheck.PreregistrationError(
                    f"D-73: refusing to drive the [split] corpus {corpus!r}: "
                    + "; ".join(problems)
                    + f". {config.preregistration_token} must be committed in "
                    f"{gitcheck.THRESHOLDS_PATH} before the first paid request."
                )
        # D-105/D-106/D-107: a [split] corpus is refused before any journal I/O unless
        # its IDs fit its role, then driven in the seeded balanced rotation.
        split = load_split(config.split_path)
        # The split records the hash of each file it was derived from; a changed
        # input (or a missing one) means the held-out set is no longer the pinned one.
        input_problems = split_input_problems(split, repo_root())
        if input_problems:
            raise ValueError(
                f"split {config.split_path} no longer matches the files it was "
                "derived from: " + "; ".join(input_problems) + "; refusing to drive"
            )
        _enforce_split_role(config, split, questions)
        work_units = plan_work_units(questions, config.arms, split.order_seed)
        if limit is not None:
            # --limit takes the first N questions of the rotated order, whole.
            work_units = work_units[: limit * len(config.arms)]
        questions = list(dict.fromkeys(q.question_id for q, _ in work_units))
        by_id = {q.question_id: q for q, _ in work_units}
        questions = [by_id[qid] for qid in questions]
    else:
        if limit is not None:
            questions = questions[:limit]

        # Build work units: cross product of questions and confirmed arms
        work_units = [(q, arm) for q in questions for arm in config.arms]

    target_path = Path(journal_path)
    _require_matching_journal_marker(
        target_path, gate_stage=gate_stage, max_retries=max_retries
    )
    _require_matching_split_marker(target_path, split)
    if not resume and load_records(target_path):
        # WR-03: spend is accumulated per invocation, so re-driving every unit into a
        # journal that already holds records restarts spend at zero and duplicates keys.
        raise JournalReuseError(
            f"drive with resume=False refused: {target_path} already holds records, "
            "and the stage spend cap is per invocation. Use --resume to continue it "
            "or a fresh run directory for a new drive."
        )
    done_keys = load_done(target_path) if resume else set()
    records: list[RunRecord] = load_records(target_path) if resume else []

    remaining_units = [
        (q, arm)
        for q, arm in work_units
        if journal_key(corpus, q.id, arm) not in done_keys
    ]

    journal = Journal(target_path)
    journal.write_header(
        corpus=corpus,
        partial=True,
        gate_stage=gate_stage,
        max_retries=max_retries,
        order_seed=split.order_seed if split is not None else None,
        split_sha256=split_sha256(split) if split is not None else None,
    )

    def _safe_reconcile() -> None:
        try:
            reconcile_header(target_path, corpus)
        except Exception as exc:
            logger.warning("Failed to reconcile header for %s: %s", target_path, exc)

    try:
        if not remaining_units:
            spend_so_far, _ = compute_spend(records)
            return DriveResult(0, stopped_by_cap=False, observed_spend=spend_so_far)

        # Check if accumulator already reached cap before dispatching any unit
        initial_spend, _ = compute_spend(records)
        if initial_spend >= stage_spend_cap:
            return DriveResult(0, stopped_by_cap=True, observed_spend=initial_spend)

        baseline_ids = baseline_sample_ids(questions)
        raw_sink = RawEventSink(target_path.parent)

        effective_workers = max(1, workers)
        limits = httpx.Limits(
            max_connections=effective_workers,
            max_keepalive_connections=effective_workers,
        )

        should_close_client = client is None
        eval_client = client or httpx.Client(
            base_url=eval_settings.gateway_url,
            limits=limits,
            timeout=httpx.Timeout(
                connect=10.0,
                read=eval_settings.gateway_timeout_secs,
                write=30.0,
                pool=10.0,
            ),
        )

        executed_count = 0
        stopped_by_cap = False
        remaining_iter = iter(remaining_units)
        in_flight: set[concurrent.futures.Future[RunRecord]] = set()

        try:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=effective_workers
            ) as executor:
                # Prime the window with at most effective_workers
                for _ in range(effective_workers):
                    try:
                        q, arm = next(remaining_iter)
                    except StopIteration:
                        break
                    fut = executor.submit(
                        drive_one,
                        eval_client,
                        corpus=corpus,
                        question=q,
                        arm=arm,
                        partial=is_limited,
                        deadline_s=eval_settings.question_deadline_secs,
                        read_timeout_s=eval_settings.gateway_timeout_secs,
                        raw_sink=raw_sink,
                        baseline_ids=baseline_ids,
                        max_retries=max_retries,
                    )
                    in_flight.add(fut)

                while in_flight:
                    done, in_flight = concurrent.futures.wait(
                        in_flight,
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )
                    for fut in done:
                        record = fut.result()
                        journal.append(record)
                        records.append(record)
                        executed_count += 1

                    # Take the next unit before the cap check (WR-01): a drive is
                    # "stopped by cap" only if a unit was still waiting when the cap
                    # was reached, so a complete drive is never labelled capped.
                    while len(in_flight) < effective_workers and not stopped_by_cap:
                        try:
                            q, arm = next(remaining_iter)
                        except StopIteration:
                            break
                        current_spend, _ = compute_spend(records)
                        if current_spend >= stage_spend_cap:
                            stopped_by_cap = True
                            break
                        fut = executor.submit(
                            drive_one,
                            eval_client,
                            corpus=corpus,
                            question=q,
                            arm=arm,
                            partial=is_limited,
                            deadline_s=eval_settings.question_deadline_secs,
                            read_timeout_s=eval_settings.gateway_timeout_secs,
                            raw_sink=raw_sink,
                            baseline_ids=baseline_ids,
                            max_retries=max_retries,
                        )
                        in_flight.add(fut)
        finally:
            if should_close_client:
                eval_client.close()

        total_spend, _ = compute_spend(records)
        return DriveResult(executed_count, stopped_by_cap=stopped_by_cap, observed_spend=total_spend)
    finally:
        _safe_reconcile()

