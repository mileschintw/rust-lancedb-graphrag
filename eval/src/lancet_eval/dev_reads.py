"""Dev reads: session analysis, the rerank timeout derivation and the dev-read ledger.

06.3.6 plan 10 (D-135, D-154, D-129, D-139, D-138). Run as `python -m
lancet_eval.dev_reads <command>` or `lancet-eval dev-reads <command>`:

* `analyse --run <dir> --session <s1|s2> --out <json>`: the measurements of one dev
  session: a paired delta of `answer_usable` per lever arm against the session's own
  `hybrid` (bootstrap CI, no p-value), null pairs, Hits@4 for the rerank and graph-v2
  arms, Yes/No/abstain shares on the comparison questions, prompt tokens, degrade and
  retry counts and spend. Dev numbers decide nothing on held-out.
* `derive-rerank-timeout --run <dir> --retrieve-timeout-ms <n> --out <json>`: the
  censoring-aware D-135 derivation. A timeout degrade is a censored observation at its
  latency; a status, malformed or transport degrade is not a latency observation and is
  excluded and counted. The p95 is exact iff `k <= n - ceil(0.95 n)` and every
  censoring time is at or above the 95th order statistic (labelled
  `censored_above_p95_rank(k)`, or `exact` when `k = 0`); otherwise it is a lower bound.
  `T = ceil(1.5 x p95)` through `latency.derive_budget`; it nests iff
  `T + 294 + 500 <= retrieve_timeout_ms`.
* `ledger-add`, `render-ledger`, `lint-ledger`: the machine-checkable dev protocol
  (D-154): at most 2 reads per lever, the read-2 reason committed before read 2, dev IDs
  only, the rules entry before read 1 and the freeze before the first held-out-side
  journal. `lint-ledger` exits non-zero on any violation.

A ledger entry is one JSON line `{"kind": ..., **payload, "entry_id": ...}`. The
payload is stored verbatim, with any keys. The `entry_id` is unique so the linter can
find the commit that introduced the entry with `git log -S`.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

from lancet_eval import gitcheck
from lancet_eval import p4 as p4_mod
from lancet_eval.arms import canonical_arm, resolve_arm
from lancet_eval.config import repo_root
from lancet_eval.corpus import (
    NO_JUDGE_PREREGISTRATION_TOKENS,
    load_corpus_config,
    load_sample_questions,
)
from lancet_eval.journal import RunRecord, load_records, read_journal_header
from lancet_eval.latency import (
    RETRIEVE_SEARCH_ALLOWANCE_MS,
    PercentileResult,
    derive_budget,
    percentile_with_ci,
)
from lancet_eval.lever_comparison import _final_line, _shares
from lancet_eval.measure import compute_spend
from lancet_eval.metrics import (
    answer_usable,
    id_matcher,
    is_abstention,
    load_gold_chunk_sets,
    paper_question_scores,
)
from lancet_eval.pairing import deduplicate_by_arm
from lancet_eval.score import _default_gold_chunks_path
from lancet_eval.split import HeldOutSplit, load_split
from lancet_eval.thresholds import COMMITTED_THRESHOLDS, DecisionThresholds
from lancet_eval.usability import carries_rerank_degraded

SCHEMA_VERSION = 1
LABEL_UNADJUSTED = "unadjusted, estimation only"
REFERENCE_ARM = "hybrid"
PHASE_DIR_REL = (
    ".planning/phases/"
    "06.3.6-quality-levers-measured-as-arms-reranker-graph-repair-by-dia"
)
LEDGER_REL = f"{PHASE_DIR_REL}/diagnostic/dev-reads.jsonl"
RENDERED_NAME = "dev-reads.md"
SPLIT_REL = "eval/corpora/multihop_rag/heldout_split.json"
KINDS = ("rule", "read", "read2_reason", "derivation", "freeze")
DEV_PROTOCOL_RULE_ID = "dev-protocol-o7-o12-o13"
MAX_READS_PER_LEVER = 2
_HELDOUT_ROLES = ("heldout", "rehearsal")
_EXCLUDED_OUTCOMES = {
    "degraded_status": "status",
    "degraded_malformed": "malformed",
    "degraded_transport": "transport",
}


class DevReadsError(Exception):
    """Raised when an analysis or a ledger operation cannot proceed."""


# ---- the censoring-aware rerank timeout (D-135) --------------------------------------


def _unavailable(
    arm: str, n: int, k: int, excluded: Mapping[str, int], retrieve_timeout_ms: int
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "arm": arm,
        "n": n,
        "k": k,
        "excluded": dict(excluded),
        "label": "unavailable",
        "decision": "unavailable",
        "reason": f"{n} latency observation(s): too few for a percentile",
        "p95_ms": None,
        "ci_low_ms": None,
        "ci_high_ms": None,
        "ci_high_unbounded": False,
        "is_lower_bound": None,
        "t_ms": None,
        "nests": None,
        "required_retrieve_ms": None,
        "retrieve_timeout_ms": retrieve_timeout_ms,
        "search_allowance_ms": RETRIEVE_SEARCH_ALLOWANCE_MS,
    }


def derive_from_observations(
    uncensored: Sequence[float],
    censored: Sequence[float],
    *,
    retrieve_timeout_ms: int,
    excluded: Mapping[str, int] | None = None,
    arm: str = "hybrid+rerank",
    thresholds: DecisionThresholds = COMMITTED_THRESHOLDS,
) -> dict[str, Any]:
    """The D-135 derivation record of a rerank latency sample with censoring.

    `censored` holds the allowed time of each timeout degrade: the true latency is at
    least that. Observations are ordered by time, an uncensored one first on a tie. With
    `n` observations, `k` censored, and `r = ceil(0.95 n)`, the 95th order statistic is
    uncensored, and so exact, iff `k <= n - r` and every censoring time is at or above
    it; otherwise the p95 is a lower bound (the 06.3.3 convention).

    Args:
        uncensored: Latencies of reranks that completed.
        censored: The time each timeout degrade was allowed.
        retrieve_timeout_ms: The ceiling `retrieve_timeout_ms` the rerank must nest in.
        excluded: Counts of degrades excluded from the sample, by class.
        arm: The arm the sample came from.
        thresholds: The committed derivation thresholds (multiplier, percentile, slack).

    Returns:
        A JSON-serialisable record: n, k, the label (`exact`,
        `censored_above_p95_rank(k)` or `lower_bound`), the p95 and its CI (the upper
        end is `None`, "unbounded", for an exact p95 with censoring), T, `nests`, the
        decision and `required_retrieve_ms`.
    """
    excl = dict(excluded or {})
    obs = sorted(
        [(float(t), False) for t in uncensored] + [(float(t), True) for t in censored],
        key=lambda o: (o[0], o[1]),
    )
    n, k = len(obs), len(censored)
    if n < 2:
        return _unavailable(arm, n, k, excl, retrieve_timeout_ms)
    percentile = thresholds.derivation_percentile
    rank = math.ceil(Fraction(str(percentile)) * n)
    value, value_censored = obs[rank - 1]
    exact = k == 0 or (
        k <= n - rank
        and not value_censored
        and all(float(t) >= value for t in censored)
    )
    label = (
        "exact"
        if k == 0
        else f"censored_above_p95_rank({k})"
        if exact
        else "lower_bound"
    )
    res: PercentileResult = percentile_with_ci(
        [t for t, _ in obs],
        p=percentile,
        seed=thresholds.bootstrap_seed,
        censored_count=k,
    )
    if res.percentile != value:
        res = dataclasses.replace(res, percentile=value)
    if exact and k > 0:
        res = dataclasses.replace(res, is_lower_bound=False)
    budget = derive_budget("rerank_timeout_ms", res, thresholds=thresholds)
    t_ms = budget.proposed_ms
    required = math.ceil(RETRIEVE_SEARCH_ALLOWANCE_MS + t_ms + thresholds.slack_ms)
    fits = required <= retrieve_timeout_ms
    if exact:
        decision = "nests" if fits else "does_not_fit"
        nests: bool | None = fits
    elif not fits:
        decision, nests = "does_not_fit", False
    else:
        decision, nests = "undecided_lower_bound", None
    unbounded = exact and k > 0
    return {
        "schema_version": SCHEMA_VERSION,
        "arm": arm,
        "n": n,
        "k": k,
        "excluded": excl,
        "label": label,
        "percentile": percentile,
        "p95_ms": value,
        "ci_low_ms": res.ci_low,
        "ci_high_ms": None if unbounded else res.ci_high,
        "ci_high_unbounded": unbounded,
        "is_lower_bound": res.is_lower_bound,
        "multiplier": thresholds.multiplier,
        "t_ms": t_ms,
        "budget_rule": budget.rule,
        "budget_censored_status": budget.censored_status,
        "retrieve_timeout_ms": retrieve_timeout_ms,
        "search_allowance_ms": RETRIEVE_SEARCH_ALLOWANCE_MS,
        "slack_ms": thresholds.slack_ms,
        "required_retrieve_ms": required,
        "nests": nests,
        "decision": decision,
    }


def _journal_file(run: Path) -> Path:
    journal = run / "journal.jsonl"
    if not journal.is_file():
        journal = run / "journal.json"
    if not journal.is_file():
        raise DevReadsError(f"no journal file in {run}")
    return journal


def derive_rerank_timeout(
    run_dir: Path | str,
    *,
    retrieve_timeout_ms: int,
    arm: str = "hybrid+rerank",
) -> dict[str, Any]:
    """The D-135 derivation over one dev journal's rerank-arm telemetry.

    Args:
        run_dir: A dev session run directory.
        retrieve_timeout_ms: The ceiling the rerank must nest in (2500).
        arm: The rerank arm whose `workflow_meta.rerank.latency_ms` is the sample.

    Returns:
        The record of `derive_from_observations`.

    Raises:
        DevReadsError: If the journal is missing or the arm has no rerank lever.
    """
    run = Path(run_dir)
    if "rerank" not in resolve_arm(arm).levers:
        raise DevReadsError(f"arm {arm!r} names no rerank lever")
    label = canonical_arm(arm)
    records, _ = deduplicate_by_arm(load_records(_journal_file(run)))
    uncensored: list[float] = []
    censored: list[float] = []
    excluded = {
        "status": 0,
        "malformed": 0,
        "transport": 0,
        "unspecified": 0,
        "no_telemetry": 0,
    }
    for rec in records:
        if canonical_arm(rec.graph_arm) != label:
            continue
        meta = rec.workflow_meta.rerank if rec.workflow_meta is not None else None
        if meta is None:
            if carries_rerank_degraded(rec):
                excluded["no_telemetry"] += 1
            continue
        outcome = meta.outcome.lower()
        if outcome == "completed":
            uncensored.append(float(meta.latency_ms))
        elif outcome == "degraded_timeout":
            censored.append(float(meta.latency_ms))
        elif outcome in _EXCLUDED_OUTCOMES:
            excluded[_EXCLUDED_OUTCOMES[outcome]] += 1
        else:
            excluded["unspecified"] += 1
    return derive_from_observations(
        uncensored,
        censored,
        retrieve_timeout_ms=retrieve_timeout_ms,
        excluded=excluded,
        arm=label,
    )


# ---- the dev-session analysis --------------------------------------------------------


def _mean(values: Sequence[float]) -> float | None:
    return float(sum(values) / len(values)) if values else None


def _rerank_outcomes(records: Sequence[RunRecord]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for rec in records:
        meta = rec.workflow_meta.rerank if rec.workflow_meta is not None else None
        if meta is not None:
            counts[meta.outcome.lower() or "unspecified"] += 1
        elif carries_rerank_degraded(rec):
            counts["degraded_no_telemetry"] += 1
    return dict(sorted(counts.items()))


def _load_gold_sets(
    path: Path | str | None,
) -> tuple[dict[str, list[frozenset[str]]] | None, str | None]:
    gold_path = Path(path) if path is not None else _default_gold_chunks_path()
    if not gold_path.is_file():
        return None, f"gold-chunk table not found at {gold_path}"
    try:
        return load_gold_chunk_sets(gold_path), None
    except (OSError, ValueError, KeyError) as exc:
        return None, f"cannot read the gold-chunk table: {exc}"


def analyse(
    run_dir: Path | str,
    session: str,
    *,
    gold_chunks_path: Path | str | None = None,
) -> dict[str, Any]:
    """Analyses one dev session journal against its own `hybrid` (D-154, O13).

    Every number is a dev reading: a paired delta with a bootstrap CI and no p-value,
    labelled "unadjusted, estimation only". It chooses between a lever's two dev
    readings and decides nothing on held-out.

    Args:
        run_dir: The dev session run directory.
        session: A label for the session (`s1` or `s2`).
        gold_chunks_path: The gold-chunk table for Hits@4; the committed post-reconcile
            table when None. Without a row for a question, that question is left out of
            Hits@4 and counted.

    Returns:
        A JSON-serialisable analysis.

    Raises:
        DevReadsError: If the journal holds a question that is not a dev ID, has no
            `hybrid` arm, or its corpus declares no `[split]`.
    """
    run = Path(run_dir)
    journal = _journal_file(run)
    header = read_journal_header(journal)
    corpus = header.get("corpus") if header else None
    if not isinstance(corpus, str) or not corpus:
        raise DevReadsError("the journal header names no corpus")
    config = load_corpus_config(corpus)
    if config.split_path is None:
        raise DevReadsError(f"corpus {corpus!r} declares no [split]")
    split = load_split(config.split_path)
    gold_map = {q.question_id: q for q in load_sample_questions(corpus)}
    records, _ = deduplicate_by_arm(load_records(journal))
    dev = set(split.dev_ids)
    stray = sorted({r.question_id for r in records} - dev)
    if stray:
        raise DevReadsError(
            f"a dev journal holds dev IDs only (D-106); not dev IDs: {stray[:5]}"
        )
    present = {canonical_arm(r.graph_arm) for r in records}
    if REFERENCE_ARM not in present:
        raise DevReadsError(f"the session has no {REFERENCE_ARM!r} arm (O13)")
    dev_g = [q for q in split.dev_ids if q in gold_map and not gold_map[q].is_null]
    dev_null = [q for q in split.dev_ids if q in gold_map and gold_map[q].is_null]
    scoped: HeldOutSplit = split.model_copy(
        update={"heldout_g_ids": dev_g, "heldout_null_ids": dev_null}
    )
    by_key = {(r.question_id, canonical_arm(r.graph_arm)): r for r in records}
    gold_sets, gold_note = _load_gold_sets(gold_chunks_path)

    def usable(rec: RunRecord) -> float:
        return (
            1.0 if answer_usable(gold_map[rec.question_id], rec.answer or "") else 0.0
        )

    def hit4(rec: RunRecord) -> float | None:
        if gold_sets is None or not gold_sets.get(rec.question_id):
            return None
        ids = (
            [c.chunk_id for c in rec.snapshot.pre_truncation_ranking]
            if rec.snapshot is not None
            else []
        )
        return float(
            paper_question_scores(ids, gold_sets[rec.question_id], id_matcher)["hit4"]
        )

    def pairs(
        pop: p4_mod.P4Population, arm: str, fn: Any
    ) -> tuple[dict[str, float], dict[str, float]]:
        vx: dict[str, float] = {}
        vr: dict[str, float] = {}
        for qid in pop.question_ids:
            x, r = fn(by_key[(qid, arm)]), fn(by_key[(qid, REFERENCE_ARM)])
            if x is not None and r is not None:
                vx[qid], vr[qid] = float(x), float(r)
        return vx, vr

    arms_out: list[dict[str, Any]] = []
    reference_shares: dict[str, Any] | None = None
    for arm in sorted(present - {REFERENCE_ARM}, key=lambda a: list(present).index(a)):
        spec = resolve_arm(arm)
        arm_records = [r for r in records if canonical_arm(r.graph_arm) == arm]
        pop = p4_mod.build_p4(
            records, scoped, (REFERENCE_ARM, arm), reference_arm=REFERENCE_ARM
        )
        vx, vr = pairs(pop, arm, usable)
        pd = p4_mod.paired_delta(vx, vr) if vx else None
        n_pos, n_neg = p4_mod.discordant_counts(vx, vr) if vx else (0, 0)
        null_scoped = scoped.model_copy(update={"heldout_g_ids": dev_null})
        null_pop = p4_mod.build_p4(
            records, null_scoped, (REFERENCE_ARM, arm), reference_arm=REFERENCE_ARM
        )
        b = c = 0
        for qid in null_pop.question_ids:
            h_abs = is_abstention(by_key[(qid, REFERENCE_ARM)])
            x_abs = is_abstention(by_key[(qid, arm)])
            if h_abs and not x_abs:
                b += 1
            elif x_abs and not h_abs:
                c += 1
        hits: dict[str, Any] | None = None
        if "rerank" in spec.levers or "graph_v2" in spec.levers:
            hx, hr = pairs(pop, arm, hit4)
            hpd = p4_mod.paired_delta(hx, hr) if hx else None
            hits = {
                "n": len(hx),
                "available": gold_sets is not None,
                "note": gold_note,
                "mean_arm": _mean(list(hx.values())),
                "mean_hybrid": _mean(list(hr.values())),
                "delta": None if hpd is None else hpd.delta,
                "ci_lo": None if hpd is None else hpd.ci_lower,
                "ci_hi": None if hpd is None else hpd.ci_upper,
                "ci_label": LABEL_UNADJUSTED,
            }
        comparison = [
            q
            for q in pop.question_ids
            if gold_map[q].question_type == "comparison_query"
        ]
        arm_shares = _shares([_final_line(by_key[(q, arm)]) for q in comparison])
        reference_shares = _shares([
            _final_line(by_key[(q, REFERENCE_ARM)]) for q in comparison
        ])
        tokens = [
            float(by_key[(q, arm)].workflow_meta.prompt_tokens)
            for q in pop.question_ids
            if by_key[(q, arm)].workflow_meta is not None
        ]
        retries = [
            r.workflow_meta.query_embedding_retries
            for r in arm_records
            if r.workflow_meta is not None
        ]
        arms_out.append({
            "arm": arm,
            "levers": list(spec.levers),
            "records": len(arm_records),
            "n_pairs": len(vx),
            "mean_arm": _mean(list(vx.values())),
            "mean_hybrid": _mean(list(vr.values())),
            "delta": None if pd is None else pd.delta,
            "ci_lo": None if pd is None else pd.ci_lower,
            "ci_hi": None if pd is None else pd.ci_upper,
            "ci_label": LABEL_UNADJUSTED,
            "no_p_value": True,
            "n_pos": n_pos,
            "n_neg": n_neg,
            "null_pairs": {"n": len(null_pop.question_ids), "b": b, "c": c},
            "hits_at_4": hits,
            "comparison_shares": {
                "n": len(comparison),
                "arm": arm_shares,
                "hybrid": reference_shares,
            },
            "mean_prompt_tokens": _mean(tokens),
            "rerank_outcomes": _rerank_outcomes(arm_records),
            "query_embedding_retries": int(sum(retries)),
            "records_with_retries": sum(1 for x in retries if x > 0),
        })
    spend, lower_bound = compute_spend(records)
    return {
        "schema_version": SCHEMA_VERSION,
        "session": session,
        "run": run.resolve().name,
        "corpus": corpus,
        "reference_arm": REFERENCE_ARM,
        "decides": "nothing on held-out; chooses between a lever's two dev readings",
        "population": {"dev_g": len(dev_g), "dev_null": len(dev_null)},
        "n_records": len(records),
        "arms": arms_out,
        "reference_comparison_shares": reference_shares,
        "spend_usd": float(spend),
        "spend_is_lower_bound": bool(lower_bound),
    }


# ---- the ledger ----------------------------------------------------------------------


def read_ledger(path: Path | str) -> list[dict[str, Any]]:
    """The ledger's entries in file order.

    Raises:
        DevReadsError: If the file cannot be read or a line is not a JSON object.
    """
    ledger = Path(path)
    try:
        text = ledger.read_text(encoding="utf-8")
    except OSError as exc:
        raise DevReadsError(f"cannot read the ledger {ledger}: {exc}") from exc
    entries: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError as exc:
            raise DevReadsError(f"{ledger}:{number}: not valid JSON: {exc}") from exc
        if not isinstance(entry, dict):
            raise DevReadsError(f"{ledger}:{number}: not valid JSON object")
        entries.append(entry)
    return entries


def ledger_add(
    path: Path | str, kind: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Appends one entry: the payload verbatim under a top-level `kind`.

    Args:
        path: The ledger file; created with its parent directory when absent.
        kind: One of `rule`, `read`, `read2_reason`, `derivation`, `freeze`.
        payload: Any JSON object. A `kind` key must match `kind`; an `entry_id` key is
            kept, else a unique one is added.

    Returns:
        The entry that was appended.

    Raises:
        DevReadsError: If `kind` is unknown or the payload is not a JSON object.
    """
    if kind not in KINDS:
        raise DevReadsError(f"unknown ledger kind {kind!r}; expected one of {KINDS}")
    if not isinstance(payload, Mapping):
        raise DevReadsError("a ledger payload must be a JSON object")
    if payload.get("kind", kind) != kind:
        raise DevReadsError(
            f"the payload carries kind {payload['kind']!r}, but --kind is {kind!r}"
        )
    entry: dict[str, Any] = {"kind": kind, **payload}
    entry.setdefault("entry_id", f"{kind}-{uuid.uuid4().hex[:12]}")
    line = json.dumps(entry, ensure_ascii=False, allow_nan=False)
    ledger = Path(path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    return entry


def render_ledger(path: Path | str) -> Path:
    """Writes `dev-reads.md` beside the ledger and returns its path."""
    ledger = Path(path)
    entries = read_ledger(ledger)
    out = [
        "# Dev reads ledger (D-154)",
        "",
        f"Rendered from `{ledger.name}`: {len(entries)} entr"
        f"{'y' if len(entries) == 1 else 'ies'}, in file order. The jsonl is the "
        "record; this file is derived from it.",
        "",
    ]
    for number, entry in enumerate(entries, start=1):
        head = f"## {number}. {entry.get('kind', '?')}"
        if "lever" in entry:
            head += f": {entry['lever']}"
        if "read" in entry:
            head += f" (read {entry['read']})"
        if "rule_id" in entry:
            head += f" [{entry['rule_id']}]"
        out += [head, "", f"- entry_id: `{entry.get('entry_id', 'none')}`"]
        for key, value in entry.items():
            if key in ("kind", "entry_id"):
                continue
            text = (
                value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False, sort_keys=True)
            )
            out.append(f"- {key}: {text}")
        out.append("")
    target = ledger.with_name(RENDERED_NAME)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(out))
    return target


def _relative(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


class _Linter:
    """One lint pass; collects every violation instead of stopping at the first."""

    def __init__(self, ledger: Path, repo: Path, split_path: Path | None) -> None:
        self.ledger = ledger
        self.repo = repo
        self.rel = _relative(ledger, repo)
        self.split_path = split_path
        self.problems: list[str] = []
        self._split: HeldOutSplit | None = None
        self._commit_cache: dict[str, int | None] = {}

    def fail(self, text: str) -> None:
        self.problems.append(text)

    def commit_time(self, entry: Mapping[str, Any]) -> int | None:
        """The commit time of the commit that introduced `entry`; None if none did."""
        if self.rel is None:
            return None
        token = str(entry.get("entry_id") or json.dumps(entry, ensure_ascii=False))
        if token not in self._commit_cache:
            sha = gitcheck.introducing_commit(token, self.rel, repo=self.repo)
            self._commit_cache[token] = (
                None if sha is None else gitcheck.commit_time(sha, repo=self.repo)
            )
        return self._commit_cache[token]

    def split(self) -> HeldOutSplit | None:
        if self._split is None:
            path = self.split_path or self.repo / SPLIT_REL
            try:
                self._split = load_split(path)
            except (OSError, ValueError) as exc:
                self.fail(f"cannot load the split {path} to check dev IDs: {exc}")
        return self._split

    def run_path(self, run_dir: str) -> Path:
        path = Path(run_dir)
        return path if path.is_absolute() else self.repo / path

    def created_at(self, journal: Path) -> float | None:
        header = read_journal_header(journal)
        value = None if header is None else header.get("created_at")
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)


def _lint_entries(lint: _Linter, entries: Sequence[dict[str, Any]]) -> None:
    ids = Counter(str(e["entry_id"]) for e in entries if "entry_id" in e)
    for entry_id, count in ids.items():
        if count > 1:
            lint.fail(f"entry_id {entry_id!r} appears {count} times")
    for number, entry in enumerate(entries, start=1):
        kind = entry.get("kind")
        if kind not in KINDS:
            lint.fail(f"entry {number}: unknown kind {kind!r}")
        elif kind in ("read", "read2_reason") and not isinstance(
            entry.get("lever"), str
        ):
            lint.fail(f"entry {number} ({kind}): needs a string `lever`")
        elif kind == "read" and (
            not isinstance(entry.get("read"), int)
            or isinstance(entry.get("read"), bool)
            or not isinstance(entry.get("run_dir"), str)
        ):
            lint.fail(f"entry {number} (read): needs an integer `read` and a `run_dir`")

    reads = [
        e
        for e in entries
        if e.get("kind") == "read" and isinstance(e.get("lever"), str)
    ]
    rules = [
        e
        for e in entries
        if e.get("kind") == "rule" and e.get("rule_id") == DEV_PROTOCOL_RULE_ID
    ]
    needs_rule = bool(reads)
    if len(rules) > 1:
        lint.fail(
            f"the ledger holds {len(rules)} `{DEV_PROTOCOL_RULE_ID}` rules entries"
        )
    if needs_rule and not rules:
        lint.fail(
            f"a read exists but the `{DEV_PROTOCOL_RULE_ID}` rule entry is missing"
        )

    # at most 2 reads per lever, numbered 1 and 2, each once
    by_lever: dict[str, list[dict[str, Any]]] = {}
    for entry in reads:
        by_lever.setdefault(entry["lever"], []).append(entry)
    for lever, items in by_lever.items():
        if len(items) > MAX_READS_PER_LEVER:
            lint.fail(
                f"lever {lever!r} has {len(items)} reads; at most "
                f"{MAX_READS_PER_LEVER} reads per lever (D-154)"
            )
        numbers = [e.get("read") for e in items]
        for number in sorted({n for n in numbers if isinstance(n, int)}):
            if number not in (1, 2):
                lint.fail(f"lever {lever!r}: read number {number} is not 1 or 2")
            if numbers.count(number) > 1:
                lint.fail(f"lever {lever!r}: read {number} is listed more than once")
        if 2 in numbers and 1 not in numbers:
            lint.fail(f"lever {lever!r}: read 2 without a read 1")

    # per read: its journal, dev IDs only, the rules entry and the read-2 reason
    split = lint.split() if reads else None
    for entry in reads:
        lever, number, run_dir = entry["lever"], entry.get("read"), entry.get("run_dir")
        if not isinstance(run_dir, str):
            continue
        journal = lint.run_path(run_dir) / "journal.jsonl"
        created = lint.created_at(journal)
        if created is None:
            lint.fail(
                f"read {number} of {lever!r}: {run_dir} has no journal header with a "
                "numeric created_at"
            )
            continue
        if split is not None:
            ids = {r.question_id for r in load_records(journal)}
            heldout = sorted(
                ids & (set(split.heldout_g_ids) | set(split.heldout_null_ids))
            )
            other = sorted(ids - set(split.dev_ids) - set(heldout))
            if heldout or other:
                lint.fail(
                    f"read {number} of {lever!r}: a dev journal holds dev IDs only "
                    f"(D-106); held-out IDs {heldout[:5]}, unknown IDs {other[:5]}"
                )
        if number == 1 and rules:
            when = lint.commit_time(rules[0])
            if when is None:
                lint.fail(
                    f"read 1 of {lever!r}: the rules entry is not committed, so it "
                    "cannot precede read 1"
                )
            elif not when < created:
                lint.fail(
                    f"read 1 of {lever!r}: the rules entry was committed after read 1 "
                    f"began (journal created_at {created:.0f}, commit {when})"
                )
        if number == 2:
            reasons = [
                e
                for e in entries
                if e.get("kind") == "read2_reason" and e.get("lever") == lever
            ]
            if not reasons:
                lint.fail(f"read 2 of {lever!r}: no read2_reason entry for the lever")
            else:
                times = [lint.commit_time(r) for r in reasons]
                if not any(t is not None and t < created for t in times):
                    lint.fail(
                        f"read 2 of {lever!r}: the read2_reason entry was not "
                        "committed before the read-2 journal's created_at "
                        f"({created:.0f}); commits {times}"
                    )

    # the freeze: after it no read or reason; before it no held-out-side journal
    freeze_at = next(
        (i for i, e in enumerate(entries) if e.get("kind") == "freeze"), None
    )
    if freeze_at is not None:
        later = [
            e
            for e in entries[freeze_at + 1 :]
            if e.get("kind") in ("read", "read2_reason")
        ]
        if later:
            lint.fail(
                f"{len(later)} read or read2_reason entr"
                f"{'y' if len(later) == 1 else 'ies'} listed after the freeze (D-154)"
            )


def heldout_side_journals(runs_root: Path) -> list[Path]:
    """Journals of 06.3.6 corpora with a held-out or rehearsal split role.

    A corpus counts only if its pre-registration token is a no-judge (06.3.6) token, so
    the committed 06.3.5 held-out journal is never read as "before the freeze".
    """
    found: list[Path] = []
    if not runs_root.is_dir():
        return found
    for journal in sorted(runs_root.glob("*/journal.jsonl")):
        header = read_journal_header(journal)
        corpus = header.get("corpus") if header else None
        if not isinstance(corpus, str):
            continue
        try:
            config = load_corpus_config(corpus)
        except Exception:
            continue
        if (
            config.split_role in _HELDOUT_ROLES
            and config.preregistration_token in NO_JUDGE_PREREGISTRATION_TOKENS
        ):
            found.append(journal)
    return found


def lint_ledger(
    ledger: Path | str,
    *,
    repo: Path | None = None,
    split_path: Path | None = None,
    runs_root: Path | None = None,
    heldout_journals: Sequence[Path] | None = None,
) -> list[str]:
    """Checks the dev protocol of a ledger (D-154, D-129); empty when it holds.

    Checks: every line is a known entry; at most 2 reads per lever; a read 2 has a
    `read2_reason` entry committed before the read-2 journal's `created_at`; a dev
    journal holds dev IDs only; the `dev-protocol-o7-o12-o13` rules entry was committed
    before read 1 (required once any read exists); no read follows the freeze entry; and
    no held-out-side journal was created before the freeze entry's commit. An entry that
    is not committed fails only a check that needs its commit time.

    Args:
        ledger: The ledger file inside the repository.
        repo: The repository whose history gives the commit times; the live repository
            when None.
        split_path: The held-out split; the committed one when None.
        runs_root: Where held-out-side journals are discovered; `eval/runs` when None.
        heldout_journals: Explicit held-out-side journals, replacing the discovery.

    Returns:
        One sentence per violation.
    """
    root = repo_root() if repo is None else Path(repo)
    ledger_path = Path(ledger)
    lint = _Linter(ledger_path, root, split_path)
    try:
        entries = read_ledger(ledger_path)
    except DevReadsError as exc:
        return [str(exc)]
    if lint.rel is None:
        lint.fail(f"the ledger {ledger_path} is not inside the repository {root}")
    _lint_entries(lint, entries)
    journals = (
        list(heldout_journals)
        if heldout_journals is not None
        else heldout_side_journals(
            Path(runs_root) if runs_root is not None else root / "eval" / "runs"
        )
    )
    freezes = [e for e in entries if e.get("kind") == "freeze"]
    for journal in journals:
        created = lint.created_at(Path(journal))
        if created is None:
            lint.fail(f"held-out-side journal {journal} has no numeric created_at")
            continue
        times = [lint.commit_time(f) for f in freezes]
        if not freezes:
            lint.fail(
                f"held-out-side journal {journal} exists but the ledger has no freeze "
                "entry (D-154)"
            )
        elif not any(t is not None and t < created for t in times):
            lint.fail(
                f"held-out-side journal {journal} was created before the freeze "
                f"entry's commit (created_at {created:.0f}; freeze commits {times})"
            )
    return lint.problems


# ---- the command line ----------------------------------------------------------------


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
        handle.write("\n")


def _payload(text: str) -> Any:
    if text.startswith("@"):
        text = Path(text[1:]).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except ValueError as exc:
        raise DevReadsError(f"--json is not valid JSON: {exc}") from exc


def _ledger_arg(value: str | None) -> Path:
    return Path(value) if value else repo_root() / LEDGER_REL


def main(argv: Sequence[str] | None = None) -> int:
    """The `dev_reads` command line; returns the exit code."""
    parser = argparse.ArgumentParser(
        prog="dev_reads", description="06.3.6 dev reads, derivation and ledger"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("analyse", help="analyse one dev session journal")
    p.add_argument("--run", required=True)
    p.add_argument("--session", required=True, choices=("s1", "s2"))
    p.add_argument("--out", required=True)
    p.add_argument("--gold-chunks")
    p = sub.add_parser("derive-rerank-timeout", help="the censoring-aware D-135 value")
    p.add_argument("--run", required=True)
    p.add_argument("--retrieve-timeout-ms", required=True, type=int)
    p.add_argument("--out", required=True)
    p.add_argument("--arm", default="hybrid+rerank")
    p = sub.add_parser("ledger-add", help="append one ledger entry")
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--json", required=True, help="the payload, or @file")
    p.add_argument("--ledger")
    p = sub.add_parser("render-ledger", help="write dev-reads.md beside the ledger")
    p.add_argument("--ledger")
    p = sub.add_parser(
        "lint-ledger", help="check the dev protocol; exit 1 on a violation"
    )
    p.add_argument("--ledger")
    p.add_argument("--repo")
    p.add_argument("--split")
    p.add_argument("--runs")
    p.add_argument("--heldout-journal", action="append")
    args = parser.parse_args(None if argv is None else list(argv))
    try:
        if args.command == "analyse":
            result = analyse(args.run, args.session, gold_chunks_path=args.gold_chunks)
            _write_json(Path(args.out), result)
            print(f"Wrote {args.out}")
        elif args.command == "derive-rerank-timeout":
            result = derive_rerank_timeout(
                args.run, retrieve_timeout_ms=args.retrieve_timeout_ms, arm=args.arm
            )
            _write_json(Path(args.out), result)
            print(
                f"{result['label']}: n={result['n']}, k={result['k']}, "
                f"T={result['t_ms']}, nests={result['nests']} ({result['decision']}); "
                f"wrote {args.out}"
            )
        elif args.command == "ledger-add":
            entry = ledger_add(_ledger_arg(args.ledger), args.kind, _payload(args.json))
            print(f"Appended {entry['kind']} {entry['entry_id']}")
        elif args.command == "render-ledger":
            print(f"Wrote {render_ledger(_ledger_arg(args.ledger))}")
        else:
            problems = lint_ledger(
                _ledger_arg(args.ledger),
                repo=Path(args.repo) if args.repo else None,
                split_path=Path(args.split) if args.split else None,
                runs_root=Path(args.runs) if args.runs else None,
                heldout_journals=[Path(j) for j in args.heldout_journal]
                if args.heldout_journal
                else None,
            )
            for problem in problems:
                print(f"LINT: {problem}", file=sys.stderr)
            if problems:
                return 1
            print("lint-ledger: the dev protocol holds")
    except (DevReadsError, gitcheck.GitCheckError, ValueError) as exc:
        print(f"dev_reads {args.command}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
