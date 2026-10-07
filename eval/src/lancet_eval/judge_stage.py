"""The 06.3.5 cache-only, counts-only judge stage (D-112, D-120 step 1).

D-120 fixes the order of the judged pass. This stage is its first step: it judges every
06.3.5-judgeable record of every registry arm over the held-out G questions, caches each
verdict in `judge_cache.json`, and writes a counts-only `judge-stage.json`. The second
step (`calibration.emit_worksheet`) draws the blinded calibration slice from a finished
stage. The judged aggregates are computed only after the owner's scores are committed,
in 06.3.5-12.

**This module never computes, writes or prints a judged score, mean, delta or agreement
figure.** It does not import `score_run`, it never writes `report.json`, and neither the
stage record nor the command's output holds a verdict, a judge error text or a rubric
dimension name: only counts, spend and timings. The cap on spend is a refusal before the
first call, never a subset: there is no `--sample` and no cap-bound subsetting.

Mechanics:

* The population is every record whose arm resolves through `canonical_arm` and that
  passes `score._is_judgeable(policy="06.3.5")`, restricted to the split's held-out G
  question IDs. In `rehearsal` mode it is every such record of the rehearsal journal
  itself (D-106 c, D-108).
* Calls are deduplicated by `judge.cache_key`: identical answer and post-truncation
  evidence across arms is one call. A shared key is judged once and its `judged_now` and
  `re_attempted` are charged to the first arm in registry order; `cached_before`,
  `errors` and `not_attempted` are reported for every arm that holds the key.
* A cache entry that holds an error is attempted again. An error is re-attempted once
  inside the stage, and errors are counted after that re-attempt.
* Tripwires (D-112, D-86), counted per judged key after its re-attempt: the stage halts
  when `errors / keys_attempted` exceeds `JUDGE_ERROR_RATE_TRIPWIRE` once
  `keys_attempted >= JUDGE_ERROR_TRIPWIRE_MIN_CALLS`, or after
  `JUDGE_CONSECUTIVE_ERROR_HALT` consecutive errors. A halt, like a spend-cap stop, is
  recorded in `stop_reason` and leaves the stage incomplete; resuming needs a new D-86
  checkpoint, and the calibration emit refuses an incomplete stage.
* Spend is accumulated per call from the reported usage (the worst-case estimate when
  the provider reported none) and checked before every call, a re-attempt included.

Everything the stage refuses, it refuses before the first call.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from lancet_eval import gitcheck
from lancet_eval.arms import ARM_REGISTRY, canonical_arm
from lancet_eval.corpus import (
    CorpusConfig,
    GoldQuestion,
    load_corpus_config,
    load_sample_questions,
)
from lancet_eval.journal import RunRecord, read_journal_header
from lancet_eval.judge import (
    JudgeCache,
    JudgeCacheEntry,
    JudgeVerdict,
    cache_key,
    judge_once,
    truncate_evidence,
)
from lancet_eval.measure import compute_judge_spend, estimate_judge_cost_per_question
from lancet_eval.pairing import deduplicate_by_arm
from lancet_eval.score import _get_engine_generation_model, _is_judgeable
from lancet_eval.split import HeldOutSplit, load_split
from lancet_eval.thresholds import (
    JUDGE_CONSECUTIVE_ERROR_HALT,
    JUDGE_ERROR_RATE_TRIPWIRE,
    JUDGE_ERROR_TRIPWIRE_MIN_CALLS,
)

STAGE_FILE = "judge-stage.json"
CACHE_FILE = "judge_cache.json"
_ARM_ORDER = {label: i for i, label in enumerate(ARM_REGISTRY)}


class JudgeStageError(Exception):
    """Raised when the judge stage refuses to run, before any call is made."""


class JudgeArmCounts(BaseModel):
    """The counts of one canonical arm; every field is a count of judge cache keys.

    Attributes:
        judgeable: 06.3.5-judgeable records of the arm in the stage's population.
        unique_keys: Distinct cache keys among them (a key shared with another arm
            counts for both arms).
        cached_before: Keys that already held a verdict when the stage started.
        judged_now: Keys that got a verdict in this stage and were first held by this
            arm in registry order (a shared key is judged, and counted, once).
        errors: Keys whose cache entry is an error after the stage.
        re_attempted: Keys of this arm that needed a second call in this stage.
        not_attempted: Keys with no cache entry because the stage stopped early.
    """

    model_config = ConfigDict(extra="forbid")

    judgeable: int = 0
    unique_keys: int = 0
    cached_before: int = 0
    judged_now: int = 0
    errors: int = 0
    re_attempted: int = 0
    not_attempted: int = 0


class JudgeStageRecord(BaseModel):
    """What `judge-stage.json` holds: counts, spend and timings, never a score.

    Attributes:
        mode: `heldout` or `rehearsal`.
        judge_model: The corpus TOML's judge model.
        judge_prompt_version: The corpus TOML's prompt version.
        stage_cap: The cap the owner authorised, in USD.
        calls: `judge_once` invocations made, re-attempts included.
        keys_attempted: Distinct keys the stage attempted.
        unique_keys_total: Distinct cache keys in the population.
        spend_usd: Accumulated spend of this stage.
        wall_clock_s: Wall-clock time of the call loop.
        arms: Counts per canonical arm, in registry order.
        stop_reason: None when the stage completed; why it stopped otherwise.
        per_call_latency_ms_p50: Median latency of one `judge_once` call; absent when no
            call was made.
        per_call_latency_ms_p95: 95th-percentile latency of one call.
    """

    model_config = ConfigDict(extra="forbid")

    mode: str = "heldout"
    judge_model: str = ""
    judge_prompt_version: str = ""
    stage_cap: float = 0.0
    calls: int = 0
    keys_attempted: int = 0
    unique_keys_total: int = 0
    spend_usd: float = 0.0
    wall_clock_s: float = 0.0
    arms: dict[str, JudgeArmCounts] = Field(default_factory=dict)
    stop_reason: str | None = None
    per_call_latency_ms_p50: float | None = None
    per_call_latency_ms_p95: float | None = None


@dataclass(frozen=True)
class StageInputs:
    """The validated, closed-journal inputs the stage and the emit step share."""

    run_dir: Path
    header: dict[str, Any]
    records: list[RunRecord]
    config: CorpusConfig
    gold_map: dict[str, GoldQuestion]
    split: HeldOutSplit
    rehearsal: bool


@dataclass(frozen=True)
class JudgeItem:
    """One judgeable record of the population, with its judge-call inputs."""

    arm: str
    question_id: str
    question_type: str
    key: str
    question: str
    answer: str
    evidence: str


def check_cap(stage_cap: float) -> float:
    """Returns the cap when it can fire; raises `JudgeStageError` otherwise."""
    if (
        isinstance(stage_cap, bool)
        or not isinstance(stage_cap, int | float)
        or not (math.isfinite(stage_cap) and stage_cap > 0)
    ):
        raise JudgeStageError(
            f"the stage cap must be a finite positive USD amount (got {stage_cap!r})"
        )
    return float(stage_cap)


def require_floor_ordering(header: dict[str, Any], git_repo: Path | None) -> None:
    """D-73: the trust floor is committed, at an ancestor of a clean HEAD, first.

    Args:
        header: The journal header; its `created_at` must be numeric.
        git_repo: Repository to query; the live repository when None.

    Raises:
        JudgeStageError: If the floor commit is absent, not an ancestor of HEAD, not
            older than the journal, or `eval/src/lancet_eval/` has uncommitted changes.
    """
    created_at = header.get("created_at")
    if isinstance(created_at, bool) or not isinstance(created_at, int | float):
        raise JudgeStageError(
            "D-73: the journal header must carry a numeric created_at to prove the "
            f"calibration floor predates it (got {created_at!r})"
        )
    try:
        problems = gitcheck.preregistration_problems(
            (gitcheck.TRUST_FLOOR_TOKEN,),
            created_at=float(created_at),
            require_clean_tree=True,
            repo=git_repo,
        )
    except gitcheck.GitCheckError as exc:
        raise JudgeStageError(f"D-73: git could not prove the ordering: {exc}") from exc
    if problems:
        raise JudgeStageError(
            "D-73: refusing the judged pass: "
            + "; ".join(problems)
            + f". {gitcheck.TRUST_FLOOR_TOKEN} must be committed before the data "
            "exists, with a clean source tree."
        )


def _read_records(run_dir: Path) -> list[RunRecord]:
    journal = run_dir / "journal.jsonl"
    if not journal.is_file():
        journal = run_dir / "journal.json"
    if not journal.is_file():
        raise JudgeStageError(f"no journal file found in {run_dir}")
    records: list[RunRecord] = []
    with open(journal, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            text = line.strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except ValueError as exc:
                raise JudgeStageError(
                    f"corrupt JSON in the journal at line {line_num}: {exc}"
                ) from exc
            if isinstance(data, dict) and data.get("type") == "header":
                continue
            if isinstance(data, dict) and "question_id" in data:
                try:
                    records.append(RunRecord.model_validate(data))
                except ValueError as exc:
                    raise JudgeStageError(
                        f"invalid record in the journal at line {line_num}"
                    ) from exc
    if not records:
        raise JudgeStageError(f"journal {journal} holds no records")
    return records


def load_inputs(run_dir: Path | str, *, rehearsal: bool = False) -> StageInputs:
    """Reads and validates a closed run for the judge stage or the calibration emit.

    Args:
        run_dir: The run directory holding `journal.jsonl`.
        rehearsal: Whether the run is a rehearsal (D-106 c, D-108).

    Returns:
        The header, the deduplicated records, the corpus config, the gold questions and
        the split.

    Raises:
        JudgeStageError: If the journal has no header or is open, the corpus has no
            split or the wrong role, a rehearsal question is in the split, a record's
            arm is not in the registry, or a record cannot be read.
    """
    run = Path(run_dir)
    header = read_journal_header(run / "journal.jsonl")
    if header is None:
        raise JudgeStageError(f"the journal in {run} has no header line")
    if header.get("partial") is not False:
        raise JudgeStageError(
            "the journal is open (header partial is not false): the judged "
            "population must be read from a closed journal (D-112)"
        )
    corpus = header.get("corpus")
    if not isinstance(corpus, str) or not corpus:
        raise JudgeStageError("the journal header names no corpus")
    config = load_corpus_config(corpus)
    if config.split_path is None or config.split_role is None:
        raise JudgeStageError(f"corpus {corpus!r} declares no [split]")
    want = "rehearsal" if rehearsal else "heldout"
    if config.split_role != want:
        hint = "" if rehearsal else " (a rehearsal corpus needs --rehearsal)"
        raise JudgeStageError(
            f"corpus {corpus!r} has split role {config.split_role!r}; this judge "
            f"stage needs a {want}-role corpus{hint}"
        )
    split = load_split(config.split_path)
    gold_map = {q.question_id: q for q in load_sample_questions(corpus)}
    records = _read_records(run)
    for rec in records:
        try:
            canonical_arm(rec.graph_arm)
        except ValueError as exc:
            raise JudgeStageError(
                f"record {rec.question_id!r} is labelled {rec.graph_arm!r}, which is "
                "not in the arm registry (D-120)"
            ) from exc
    records, _ = deduplicate_by_arm(records)
    stored: dict[tuple[str, str], str] = {}
    for rec in records:
        slot = (rec.question_id, canonical_arm(rec.graph_arm))
        if stored.setdefault(slot, rec.graph_arm) != rec.graph_arm:
            raise JudgeStageError(
                f"question {rec.question_id!r} has records under both "
                f"{stored[slot]!r} and {rec.graph_arm!r}, which are one arm"
            )
    if rehearsal:
        in_split = set(split.dev_ids) | set(split.heldout_g_ids)
        in_split |= set(split.heldout_null_ids)
        seen = set(gold_map) | {r.question_id for r in records}
        clash = sorted(seen & in_split)
        if clash:
            raise JudgeStageError(
                f"{len(clash)} rehearsal question ID(s) are in the split's dev or "
                f"held-out lists (first: {clash[0]!r}); a rehearsal is disjoint "
                "from both (D-106 c)"
            )
    return StageInputs(
        run_dir=run,
        header=header,
        records=records,
        config=config,
        gold_map=gold_map,
        split=split,
        rehearsal=rehearsal,
    )


def select_population(inputs: StageInputs) -> list[JudgeItem]:
    """Every 06.3.5-judgeable record of the stage's population, in a fixed order.

    The order is registry arm first, then question ID, so the first holder of a shared
    cache key is the first arm in registry order.

    Args:
        inputs: The validated run.

    Returns:
        One item per judgeable record, with its judge-call inputs and cache key.
    """
    g_ids = None if inputs.rehearsal else set(inputs.split.heldout_g_ids)
    items: list[JudgeItem] = []
    for rec in inputs.records:
        if g_ids is not None and rec.question_id not in g_ids:
            continue
        if not _is_judgeable(rec, inputs.gold_map, policy="06.3.5"):
            continue
        gold = inputs.gold_map[rec.question_id]
        answer = rec.answer or ""
        evidence = truncate_evidence(rec.structured_citations)
        items.append(
            JudgeItem(
                arm=canonical_arm(rec.graph_arm),
                question_id=rec.question_id,
                question_type=gold.question_type,
                key=cache_key(
                    prompt_version=inputs.config.judge_prompt_version,
                    judge_model=inputs.config.judge_model,
                    question=gold.question,
                    answer=answer,
                    post_truncation_evidence=evidence,
                ),
                question=gold.question,
                answer=answer,
                evidence=evidence,
            )
        )
    items.sort(key=lambda i: (_ARM_ORDER[i.arm], i.question_id))
    return items


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _write_stage(run_dir: Path, record: JudgeStageRecord) -> None:
    path = run_dir / STAGE_FILE
    tmp = path.with_suffix(f".tmp-{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(record.model_dump_json(indent=2))
        f.write("\n")
    tmp.replace(path)


def run_judge_stage(
    *,
    run_dir: Path | str,
    stage_cap: float,
    rehearsal: bool = False,
    client: httpx.Client | None = None,
    api_key: str | None = None,
    git_repo: Path | None = None,
) -> JudgeStageRecord:
    """Judges every judgeable record of every arm, caches the verdicts, shows counts.

    Args:
        run_dir: A closed run directory holding `journal.jsonl`.
        stage_cap: The USD cap the owner authorised for this stage (D-86).
        rehearsal: Judge a rehearsal-role corpus's own records instead (D-106 c).
        client: HTTP client for the judge; a fresh one per call when None.
        api_key: The key; `OPENROUTER_API_KEY` from the environment when None.
        git_repo: Repository the D-73 ordering is read from; the live one when None.

    Returns:
        The stage record, also written to `judge-stage.json`. A stage that stopped
        early carries a `stop_reason`.

    Raises:
        JudgeStageError: Before the first call, when the cap is invalid, the journal is
            open, the key is empty, the floor is not committed at an ancestor of a clean
            HEAD, the corpus or its split does not fit the mode, a record's arm is not
            in the registry, the judge is the generator, a rehearsal has nothing
            judgeable, or the uncached estimate exceeds the cap.
    """
    cap = check_cap(stage_cap)
    inputs = load_inputs(run_dir, rehearsal=rehearsal)
    key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
    if not key.strip():
        raise JudgeStageError(
            "OPENROUTER_API_KEY is empty: the judge would cache an error per record"
        )
    require_floor_ordering(inputs.header, git_repo)
    config = inputs.config
    generator = _get_engine_generation_model().strip()
    if not generator:
        raise JudgeStageError(
            "could not read the engine generation model, so the judge cannot be "
            "shown distinct from it"
        )
    if config.judge_model.strip() == generator:
        raise JudgeStageError(
            f"the judge model {config.judge_model!r} equals the engine generation "
            "model; a judge cannot evaluate its own model"
        )

    items = select_population(inputs)
    if rehearsal and not items:
        raise JudgeStageError("no judgeable rehearsal record: nothing to time")
    unique: dict[str, JudgeItem] = {}
    arm_keys: dict[str, set[str]] = {arm: set() for arm in ARM_REGISTRY}
    arm_judgeable = dict.fromkeys(ARM_REGISTRY, 0)
    for item in items:
        unique.setdefault(item.key, item)
        arm_keys[item.arm].add(item.key)
        arm_judgeable[item.arm] += 1

    cache = JudgeCache(inputs.run_dir / CACHE_FILE)
    cached_before = {
        k for k in unique if (e := cache.get(k)) is not None and e.verdict is not None
    }
    to_call = [k for k in unique if k not in cached_before]
    cost = estimate_judge_cost_per_question(config.judge_max_tokens)
    if len(to_call) * cost > cap:
        raise JudgeStageError(
            f"{len(to_call)} uncached key(s) x ${cost:.6f} = "
            f"${len(to_call) * cost:.6f} exceeds the stage cap ${cap:.6f}; the "
            "stage never judges a cap-bound subset"
        )

    judged_now: set[str] = set()
    re_attempted: set[str] = set()
    latencies_ms: list[float] = []
    spend = 0.0
    calls = 0
    keys_attempted = 0
    errors = 0
    consecutive = 0
    stop_reason: str | None = None

    def attempt(item: JudgeItem) -> tuple[JudgeVerdict | None, str | None]:
        nonlocal spend, calls
        started = time.perf_counter()
        verdict, error, usage = judge_once(
            client=client,
            api_key=key,
            model=config.judge_model,
            question=item.question,
            answer=item.answer,
            evidence=item.evidence,
            prompt_version=config.judge_prompt_version,
            temperature=config.judge_temperature,
            max_tokens=config.judge_max_tokens,
        )
        latencies_ms.append((time.perf_counter() - started) * 1000.0)
        calls += 1
        if usage is not None:
            spend += compute_judge_spend(usage.prompt_tokens, usage.completion_tokens)
        else:
            spend += cost
        return verdict, error

    def over_cap() -> bool:
        return spend + cost > cap

    def store(
        item: JudgeItem, verdict: JudgeVerdict | None, error: str | None
    ) -> None:
        cache.set(
            item.key,
            JudgeCacheEntry(
                cache_key=item.key,
                prompt_version=config.judge_prompt_version,
                judge_model=config.judge_model,
                question=item.question,
                answer=item.answer,
                evidence=item.evidence,
                verdict=verdict,
                error=error,
            ),
        )

    cap_reason = (
        f"spend cap reached: the next call would exceed the stage cap ${cap:.6f}"
    )
    loop_started = time.perf_counter()
    for k in to_call:
        item = unique[k]
        if over_cap():
            stop_reason = cap_reason
            break
        verdict, error = attempt(item)
        if verdict is None:
            if over_cap():
                store(item, None, error)
                keys_attempted += 1
                errors += 1
                stop_reason = cap_reason
                break
            re_attempted.add(k)
            verdict, error = attempt(item)
        store(item, verdict, error)
        keys_attempted += 1
        if verdict is not None:
            judged_now.add(k)
            consecutive = 0
        else:
            errors += 1
            consecutive += 1
            if consecutive >= JUDGE_CONSECUTIVE_ERROR_HALT:
                stop_reason = f"{consecutive} consecutive judge errors"
                break
        if (
            keys_attempted >= JUDGE_ERROR_TRIPWIRE_MIN_CALLS
            and errors / keys_attempted > JUDGE_ERROR_RATE_TRIPWIRE
        ):
            stop_reason = (
                f"judge error rate {errors}/{keys_attempted} exceeds the "
                f"{JUDGE_ERROR_RATE_TRIPWIRE} tripwire"
            )
            break
    wall_clock = time.perf_counter() - loop_started

    arms: dict[str, JudgeArmCounts] = {}
    for arm in ARM_REGISTRY:
        keys = arm_keys[arm]
        first_held = {k for k in keys if unique[k].arm == arm}
        entries = [cache.get(k) for k in keys]
        arms[arm] = JudgeArmCounts(
            judgeable=arm_judgeable[arm],
            unique_keys=len(keys),
            cached_before=len(keys & cached_before),
            judged_now=len(first_held & judged_now),
            errors=sum(1 for e in entries if e is not None and e.verdict is None),
            re_attempted=len(first_held & re_attempted),
            not_attempted=sum(1 for e in entries if e is None),
        )
    record = JudgeStageRecord(
        mode="rehearsal" if rehearsal else "heldout",
        judge_model=config.judge_model,
        judge_prompt_version=config.judge_prompt_version,
        stage_cap=cap,
        calls=calls,
        keys_attempted=keys_attempted,
        unique_keys_total=len(unique),
        spend_usd=spend,
        wall_clock_s=wall_clock,
        arms=arms,
        stop_reason=stop_reason,
        per_call_latency_ms_p50=_percentile(latencies_ms, 0.50),
        per_call_latency_ms_p95=_percentile(latencies_ms, 0.95),
    )
    _write_stage(inputs.run_dir, record)
    return record
