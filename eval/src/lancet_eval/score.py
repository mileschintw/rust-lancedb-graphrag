"""Offline deterministic and cached LLM-judged evaluation scorer."""

from __future__ import annotations

import json
import logging
import math
import os
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

from lancet_eval.agreement import (
    CALIBRATION_STATE_BELOW_TARGET,
    CALIBRATION_STATE_NONE,
    CALIBRATION_STATE_SATISFIED,
    KAPPA_STATE_COMPUTED,
    KAPPA_STATE_UNDEFINED_EXPECTED_AGREEMENT,
    SPEARMAN_STATE_COMPUTED,
    SPEARMAN_STATE_UNDEFINED_ZERO_VARIANCE,
    bootstrap_agreement_ci,
    quadratic_weighted_kappa,
    spearman_rank_correlation,
)
from lancet_eval.config import get_commit_sha
from lancet_eval.corpus import (
    load_corpus_config,
    load_sample_questions,
    sample_questions,
)
from lancet_eval.dimensions import (
    JUDGED_SLICE_STATE_CAP_BOUND,
    JUDGED_SLICE_STATE_CAP_STOPPED,
    JUDGED_SLICE_STATE_COMPLETED,
    JUDGED_SLICE_STATE_NOT_JUDGED,
    JUDGED_SLICE_STATES,
    NOTICE_CODE_GRAPH_ABLATION,
    NOTICE_CODE_GRAPH_UNAVAILABLE,
    OBS_04_PLACEHOLDER,
    DimensionResult,
    make_bm25_yield,
    make_faithfulness_result,
    make_graph_influence_rate,
    make_graph_latency_ms,
    make_graph_presence_rate,
    make_groundedness_result,
    make_paired_ablation_delta,
    make_retrieve_latency_ms,
    make_unusable_record_rate,
    make_vector_yield,
    make_wire_contract_conformance,
)
from lancet_eval.gate import AGREEMENT_TARGET, derive_judged_slice_size
from lancet_eval.journal import RunRecord, completeness_comparison
from lancet_eval.judge import (
    JudgeCache,
    JudgeCacheEntry,
    cache_key,
    judge_once,
    truncate_evidence,
)
from lancet_eval.measure import (
    EMBEDDING_PRICE_PER_1M,
    ESTIMATED_EMBEDDING_TOKENS_PER_QUERY,
    compute_judge_spend,
    compute_spend,
    estimate_judge_cost_per_question,
)
from lancet_eval.arms import ARM_REGISTRY, arm_slug, canonical_arm, resolve_arm
from lancet_eval.metrics import (
    abstention_leak,
    abstention_rate,
    context_precision_at_k,
    extract_final_answer,
    final_answer_em,
    gold_contained,
    id_matcher,
    is_abstention,
    load_gold_chunk_sets,
    mrr_at_k,
    ndcg_at_k,
    null_abstention_correct,
    paper_question_scores,
    recall_at_k,
    squad_em,
    squad_f1,
)
from lancet_eval.metrics import answer_usable as compute_answer_usable
from lancet_eval import gitcheck, provenance
from lancet_eval import p4 as p4_mod
from lancet_eval import strata
from lancet_eval.split import HeldOutSplit, load_split, split_sha256
from lancet_eval.stats import (
    BOOTSTRAP_B,
    BOOTSTRAP_SEED,
    bootstrap_mean_ci,
    wilson_ci,
)
from lancet_eval.pairing import (
    compute_paired_delta,
    deduplicate_by_arm,
    form_arm_pairs,
)
from lancet_eval.report import (
    CorpusReport,
    RunMetadata,
    compute_result_hash,
    get_lock_hash,
    render_json,
)
from lancet_eval.seed import load_document_map
from lancet_eval.usability import (
    has_arm_provenance,
    has_scorable_payload,
    is_usable,
)

logger = logging.getLogger(__name__)


class ScoreError(Exception):
    """Raised when score encounters corrupt, invalid, or unmapped data."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _get_engine_generation_model() -> str:
    """Read generation_model from config/config.toml, logging warning on failure."""
    cfg_path = _repo_root() / "config" / "config.toml"
    if not cfg_path.is_file():
        logger.warning("Config file not found at %s (FileNotFoundError)", cfg_path)
        return ""
    try:
        with open(cfg_path, "rb") as f:
            data = tomllib.load(f)
        return str(data.get("openrouter", {}).get("generation_model", ""))
    except Exception as e:
        logger.warning(
            "Failed to read engine generation model from %s (%s)",
            cfg_path,
            type(e).__name__,
        )
        return ""


def _check_provenance(record: RunRecord) -> bool:
    """Verify that a graph-off record carries ablation notice and not unavailable."""
    has_ablation = any(
        n.typed_code == NOTICE_CODE_GRAPH_ABLATION or n.code == "GRAPH_ABLATION"
        for n in record.notices
    )
    has_unavailable = any(
        n.typed_code == NOTICE_CODE_GRAPH_UNAVAILABLE or n.code == "GRAPH_UNAVAILABLE"
        for n in record.notices
    )
    return has_ablation and not has_unavailable


def _group_records_by_arm(
    records: list[RunRecord], configured_arms: list[str]
) -> dict[str, list[RunRecord]]:
    """D-101/D-120: group records under the corpus's configured arm labels.

    A record belongs to the configured label whose `canonical_arm` equals its stored
    label's, so a legacy corpus keeps keying `graph-on` / `graph-off` and a registry
    corpus keys its canonical labels. The stored label is never rewritten.

    Raises:
        ScoreError: If a configured label is unknown or two configured labels are
            one arm; a stored label is not in the registry, or names an arm the
            corpus does not configure (counted per label, never dropped); or one
            question holds records under two stored labels of one arm (an alias and
            its canonical label), which `deduplicate_by_arm` would keep both of.
    """
    by_canonical: dict[str, str] = {}
    for label in configured_arms:
        try:
            canonical = canonical_arm(label)
        except ValueError as exc:
            raise ScoreError(f"Configured arm {label!r} is not a known arm") from exc
        if canonical in by_canonical:
            raise ScoreError(
                f"Configured arms {by_canonical[canonical]!r} and {label!r} are the "
                f"same arm ({canonical!r})"
            )
        by_canonical[canonical] = label

    unknown: dict[str, int] = {}
    unconfigured: dict[str, int] = {}
    stored_by_slot: dict[tuple[str, str], str] = {}
    grouped: dict[str, list[RunRecord]] = {label: [] for label in configured_arms}
    for rec in records:
        try:
            canonical = canonical_arm(rec.graph_arm)
        except ValueError:
            unknown[rec.graph_arm] = unknown.get(rec.graph_arm, 0) + 1
            continue
        configured = by_canonical.get(canonical)
        if configured is None:
            unconfigured[rec.graph_arm] = unconfigured.get(rec.graph_arm, 0) + 1
            continue
        seen = stored_by_slot.setdefault((rec.question_id, canonical), rec.graph_arm)
        if seen != rec.graph_arm:
            raise ScoreError(
                f"Question {rec.question_id!r} has records under both {seen!r} and "
                f"{rec.graph_arm!r}, which are the same arm ({canonical!r}); "
                "refusing to merge them"
            )
        grouped[configured].append(rec)

    if unknown:
        listing = ", ".join(
            f"{k!r} ({v} record(s))" for k, v in sorted(unknown.items())
        )
        raise ScoreError(
            f"Unknown arm label(s) in journal, not in the registry: {listing}"
        )
    if unconfigured:
        listing = ", ".join(
            f"{k!r} ({v} record(s))" for k, v in sorted(unconfigured.items())
        )
        raise ScoreError(
            f"Arm label(s) in journal not configured for this corpus "
            f"(arms {list(configured_arms)}): {listing}"
        )
    return grouped


def _primary_arm(configured_arms: list[str], totals: dict[str, int]) -> str:
    """The arm the legacy-named dimensions are computed over (D-101, WR-03).

    The configured label whose canonical form is `hybrid+graph`, else `hybrid`, else
    the first configured label with records; each only when it has records.
    """
    for wanted in ("hybrid+graph", "hybrid"):
        for label in configured_arms:
            if canonical_arm(label) == wanted and totals.get(label, 0) > 0:
                return label
    for label in configured_arms:
        if totals.get(label, 0) > 0:
            return label
    return configured_arms[0]


def _require_preregistered_before(created_at: object, repo: Path | None) -> None:
    """D-73: a `[split]` corpus's report needs the pre-registration older than its data.

    Raises:
        ScoreError: If the journal header carries no numeric `created_at`, the
            commits introducing `PREREGISTRATION_06_3_5` and `JUDGE_QWK_TRUST_FLOOR` are
            absent, not ancestors of HEAD, or not strictly older than `created_at`, the
            source tree has an uncommitted change, or either constant differs from the
            value its introducing commit set (WR-02).
    """
    if isinstance(created_at, bool) or not isinstance(created_at, int | float):
        raise ScoreError(
            "D-73: a [split] corpus's journal header must carry a numeric created_at "
            f"to prove the pre-registration predates it (got {created_at!r})"
        )
    problems = gitcheck.preregistration_problems(
        (gitcheck.PREREGISTRATION_TOKEN, gitcheck.TRUST_FLOOR_TOKEN),
        created_at=float(created_at),
        require_clean_tree=True,
        unchanged_since_introduction=True,
        repo=repo,
    )
    if problems:
        raise ScoreError(
            "D-73: refusing to score a [split] corpus's report: "
            + "; ".join(problems)
            + f". {gitcheck.PREREGISTRATION_TOKEN} and {gitcheck.TRUST_FLOOR_TOKEN} "
            "must be committed before the data exists."
        )


def _require_split_marker_matches(
    marker: Mapping[str, Any], split: HeldOutSplit
) -> None:
    """Refuse a journal whose header names a different split or seed than the one loaded.

    The drive records ``split_sha256`` and ``order_seed`` in the header (D-107). When
    the header carries one, it must equal the value computed from the split file the
    report is about to be built on; a split edited after the drive passes no other gate.
    A header without a marker is not refused here: journals older than the marker, and
    the fixtures that build one by hand, carry none.

    Raises:
        ScoreError: If a recorded marker differs from the loaded split's.
    """
    expected = {"order_seed": split.order_seed, "split_sha256": split_sha256(split)}
    for key, want in expected.items():
        if key in marker and marker[key] != want:
            raise ScoreError(
                f"the journal header records {key}={marker[key]!r} but the split on "
                f"disk has {want!r}: the split or seed changed since the drive"
            )


_JUDGEABLE_POLICIES = ("legacy", "06.3.5")


def _is_judgeable(
    rec: RunRecord, gold_map: dict[str, Any], *, policy: str = "legacy"
) -> bool:
    """T-06.3.4-42: Single judgeable predicate read by candidate selection, judge loop, and calibration worksheet.

    Policy `"legacy"` (the default, byte for byte the 06.3.4 predicate): gold is present
    for the record's question_id and it carries non-empty structured_citations.

    Policy `"06.3.5"` (D-112 / D-118): additionally the question is not a null question,
    `provenance.is_ok(rec)` holds (D-34 usable, no clause a to f failure), and
    `not is_abstention(rec)`. The judge stage, the calibration draw and the judged
    aggregates all call this one predicate; a null, an abstention, an uncited, an
    unusable or a provenance-failed record is never judgeable under it.

    Raises:
        ValueError: If `policy` is not a known policy.
    """
    if policy not in _JUDGEABLE_POLICIES:
        raise ValueError(
            f"Unknown judgeable policy {policy!r}; expected {_JUDGEABLE_POLICIES}"
        )
    gold = gold_map.get(rec.question_id)
    legacy = bool(gold) and bool(rec.structured_citations)
    if policy == "legacy":
        return legacy
    if not legacy:
        return False
    if gold.is_null or gold.question_type == "null_query":
        return False
    return provenance.is_ok(rec) and not is_abstention(rec)


def _reusable_verdict_count(
    cache: JudgeCache,
    prompt_version: str,
    judge_model: str,
    records: list[RunRecord],
    gold_map: dict[str, Any],
) -> int:
    """WR-07/WR-03: Count only cache entries reachable from the current judgeable population.

    WR-07 scoped this count to entries whose stored `prompt_version`/`judge_model` fields
    matched the configured values. That is necessary but not sufficient: on a corrected
    re-drive into the same run_dir, a stale entry can still match on those two fields while
    being unreachable for any other reason -- the cache key also embeds the record's answer
    and post-truncation evidence, either of which a corrected engine run can change for the
    same question_id.

    Rather than comparing stored fields, recompute the exact cache_key each currently
    judgeable record would produce under the *current* prompt_version/judge_model and count
    only the cache hits among those keys. Since prompt_version and judge_model are inputs to
    the key's hash, a stored entry from a superseded prompt version or a different judge
    model naturally fails to match (same guarantee as WR-07); a stored entry that is stale by
    answer/evidence content also naturally fails to match (the new WR-03 guarantee) -- both
    without any separate field comparison.
    """
    count = 0
    for rec in records:
        if not _is_judgeable(rec, gold_map):
            continue
        gold = gold_map[rec.question_id]
        k = cache_key(
            prompt_version=prompt_version,
            judge_model=judge_model,
            question=gold.question,
            answer=rec.answer or "",
            post_truncation_evidence=truncate_evidence(rec.structured_citations),
        )
        entry = cache.get(k)
        if entry is not None and entry.verdict is not None:
            count += 1
    return count


# --- 06.3.5-10: four-arm per-arm dimensions on P4 (D-126) ----------------------------
#
# A `[split]` corpus's report gains numeric dimensions named `<dimension>__<arm_slug>`
# through the unchanged fail-closed score/report path. `report.schema.json` does not
# change: every dimension is a `DimensionResult`, and every `detail` value is a float.


def _default_gold_chunks_path() -> Path:
    """The 06.3.4.1 post-reconcile gold-chunk table (D-61), the ID rule's gold sets."""
    return (
        _repo_root()
        / ".planning"
        / "phases"
        / "06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair"
        / "diagnostic"
        / "post-reconcile"
        / "gold_chunks.jsonl"
    )


@dataclass(frozen=True)
class _SplitInputs:
    """What a `[split]` corpus's four-arm report reads besides the journal."""

    split: HeldOutSplit
    gold_sets: dict[str, list[frozenset[str]]]


def _load_split_inputs(
    config: Any,
    gold_map: Mapping[str, Any],
    gold_chunks_path: Path | str | None,
) -> _SplitInputs:
    """Loads the held-out split and the gold chunk sets; fails closed on any gap.

    Raises:
        ScoreError: If the split or the gold-chunk table cannot be read, or a held-out
            G question has no gold question, is a null question, is not one of the
            three G question types, or has no gold set.
    """
    try:
        split = load_split(config.split_path)
    except (OSError, ValueError) as exc:
        raise ScoreError(
            f"Could not load the held-out split {config.split_path}: {exc}"
        ) from exc
    path = (
        Path(gold_chunks_path)
        if gold_chunks_path is not None
        else _default_gold_chunks_path()
    )
    if not path.is_file():
        raise ScoreError(
            f"Gold-chunk table not found at {path}; the ID rule (D-102) needs it"
        )
    try:
        gold_sets = load_gold_chunk_sets(path)
    except (OSError, ValueError, KeyError) as exc:
        raise ScoreError(f"Could not read the gold-chunk table {path}: {exc}") from exc
    problems: list[str] = []
    for qid in split.heldout_g_ids:
        gold = gold_map.get(qid)
        if gold is None:
            problems.append(f"{qid}: not in the corpus's question file")
        elif gold.is_null:
            problems.append(f"{qid}: a held-out G question with no gold evidence")
        elif gold.question_type not in strata.STRATUM_TYPES:
            problems.append(
                f"{qid}: question_type {gold.question_type!r} is not a G stratum"
            )
        elif not gold_sets.get(qid):
            problems.append(f"{qid}: no row in the gold-chunk table")
    if problems:
        raise ScoreError(
            f"{len(problems)} held-out G question(s) cannot be scored: "
            + "; ".join(problems[:20])
        )
    return _SplitInputs(split=split, gold_sets=gold_sets)


def _interval(
    xs: Sequence[float], kind: Literal["wilson", "bootstrap"]
) -> tuple[float, float]:
    """The 95% interval of the mean of `xs` (Wilson for 0/1, else the bootstrap)."""
    if kind == "wilson":
        _, lo, hi = wilson_ci(round(sum(xs)), len(xs))
    else:
        _, lo, hi = bootstrap_mean_ci(list(xs), seed=BOOTSTRAP_SEED, b=BOOTSTRAP_B)
    return lo, hi


def _per_arm_dimension(
    name: str,
    values: Mapping[str, float],
    *,
    kind: Literal["wilson", "bootstrap", "none"],
    statistic: Literal["mean", "p50", "p95"] = "mean",
    qtype_of: Mapping[str, str],
    detail: Mapping[str, float],
    empty_reason: str,
) -> DimensionResult:
    """One per-arm dimension over a per-question value map, with its D-40 strata.

    `detail` carries the dimension's own counts; the interval and the strata are added
    here. An empty map is a skipped dimension, because Wilson and the bootstrap are
    undefined at n = 0.
    """
    if not values:
        return DimensionResult(
            name=name, status="skipped", reason=empty_reason, detail=dict(detail), n=0
        )
    xs = [float(values[q]) for q in sorted(values)]
    score = strata.summarize(xs, statistic)
    out: dict[str, float] = {k: float(v) for k, v in detail.items()}
    if kind == "wilson":
        out["successes"] = float(round(sum(xs)))
    if kind != "none":
        lo, hi = _interval(xs, kind)
        out["ci_lower"] = float(lo)
        out["ci_upper"] = float(hi)
    out.update(strata.type_strata(values, qtype_of, statistic=statistic, interval=kind))
    return DimensionResult(name=name, status="ok", score=score, detail=out, n=len(xs))


def _delta_dimension(
    name: str,
    values_x: Mapping[str, float],
    values_ref: Mapping[str, float],
    *,
    qtype_of: Mapping[str, str],
    counts: bool,
    detail: Mapping[str, float],
    empty_reason: str,
) -> DimensionResult:
    """A secondary paired delta of arm X against `hybrid` over one question set.

    `score` is the mean paired difference, which equals `mean_x - mean_hybrid` over the
    same questions, and `n` is the number of pairs. The CI is the percentile bootstrap
    of `p4.paired_delta` (B and seed from `stats`). There is no p-value and no Holm
    field: a secondary delta is estimation only and is never called significant
    (D-111, D-123).
    """
    if not values_x:
        return DimensionResult(
            name=name, status="skipped", reason=empty_reason, detail=dict(detail), n=0
        )
    pd = p4_mod.paired_delta(values_x, values_ref)
    keys = sorted(values_x)
    out: dict[str, float] = {k: float(v) for k, v in detail.items()}
    out["ci_lower"] = float(pd.ci_lower)
    out["ci_upper"] = float(pd.ci_upper)
    out["n_pairs"] = float(pd.n)
    out["mean_x"] = float(fmean(values_x[k] for k in keys))
    out["mean_hybrid"] = float(fmean(values_ref[k] for k in keys))
    if counts:
        out["count_x"] = float(sum(values_x[k] for k in keys))
        out["count_hybrid"] = float(sum(values_ref[k] for k in keys))
        out["count_delta"] = out["count_x"] - out["count_hybrid"]
    out.update(strata.paired_delta_strata(values_x, values_ref, qtype_of))
    return DimensionResult(
        name=name, status="ok", score=float(pd.delta), detail=out, n=pd.n
    )


def _record_ranking_ids(rec: RunRecord) -> list[str]:
    """The D-100 pre-truncation ranking's chunk IDs, in order (empty without one)."""
    if rec.snapshot is None:
        return []
    return [c.chunk_id for c in rec.snapshot.pre_truncation_ranking]


def _has_valid_ranking(rec: RunRecord | None) -> bool:
    """A record that is ok(r) and whose RetrieveHybrid completed with a snapshot."""
    return (
        rec is not None
        and rec.snapshot is not None
        and rec.snapshot.result_hash != ""
        and provenance.is_ok(rec)
    )


def _retrieve_node_ms(rec: RunRecord) -> float | None:
    for nt in rec.node_timings:
        if nt.node_name == "RetrieveHybrid":
            return float(nt.duration_ms)
    return None


def _record_spend_usd(rec: RunRecord) -> float:
    """One record's spend in USD: wire tokens, the failed-generation ceiling, embedding.

    The generation part is `measure.compute_spend([rec], include_embeddings=False)`,
    which already prices every superseded attempt and the failed-generation ceiling.
    The per-query embedding estimate is added once per attempt, and only on an arm that
    embeds: `bm25-only` with graph context off embeds nothing (D-125, pinned by
    06.3.5-04). `measure.compute_spend` is not edited, so the stage cap keeps its
    conservative per-query embedding charge.
    """
    generation, _ = compute_spend([rec], include_embeddings=False)
    spec = resolve_arm(rec.graph_arm)
    if spec.retrieval_mode == "bm25_only" and spec.disable_graph_context:
        return generation
    attempts = 1 + len(rec.prior_attempts)
    embedding = (
        attempts * ESTIMATED_EMBEDDING_TOKENS_PER_QUERY / 1_000_000.0
    ) * EMBEDDING_PRICE_PER_1M
    return generation + embedding


def _provenance_scan(
    records: Sequence[RunRecord],
) -> tuple[dict[str, int], list[tuple[str, str, str]]]:
    """Counts every provenance code over the records; lists the zero-tolerance failures.

    Returns:
        `(counts, failing)`: the number of records failing each code `a` to `g`, and
        `(question_id, arm_label, codes)` for each record with a zero-tolerance
        failure (clauses a, b, c, d, f), sorted by question and arm.
    """
    counts = dict.fromkeys("abcdefg", 0)
    failing: list[tuple[str, str, str]] = []
    for rec in records:
        codes = sorted({f.code for f in provenance.provenance_failures(rec)})
        for code in codes:
            counts[code] += 1
        fatal = [c for c in codes if c in provenance.ZERO_TOLERANCE_CODES]
        if fatal:
            failing.append((rec.question_id, rec.graph_arm, ",".join(fatal)))
    failing.sort()
    return counts, failing


_PROVENANCE_REFUSAL_LISTED = 20


def _prompt_tokens(rec: RunRecord) -> float:
    """Wire prompt tokens; 0 for a record that skipped generation or has no meta."""
    return float(rec.workflow_meta.prompt_tokens) if rec.workflow_meta else 0.0


@dataclass(frozen=True)
class _Metric:
    """One per-arm dimension over the P4 per-question values."""

    name: str
    value: Callable[[RunRecord], float | None]
    kind: Literal["wilson", "bootstrap"]
    delta_name: str | None = None
    counts: bool = False


def _four_arm_dimensions(
    *,
    records: Sequence[RunRecord],
    config: Any,
    inputs: _SplitInputs,
    gold_map: Mapping[str, Any],
    arm_metrics: Mapping[str, Mapping[str, Any]],
    provenance_counts: Mapping[str, int],
) -> list[DimensionResult]:
    """The four-arm per-arm dimensions of a `[split]` corpus (06.3.5-10, D-126).

    Every P4 dimension is computed from one per-question value map per arm, so the
    strata sum to the dimension's n by construction. A metric that has no value for
    some P4 question on some arm (a skipped recall, a record with no RetrieveHybrid
    timing) is computed over the questions where every arm has one; the questions left
    out are counted in `n_unscorable`.

    Raises:
        ScoreError: If the arms cannot form P4.
    """
    split = inputs.split
    gold_sets = inputs.gold_sets
    g_ids = list(split.heldout_g_ids)
    n_g = len(g_ids)
    try:
        pop = p4_mod.build_p4(records, split, config.arms)
    except ValueError as exc:
        raise ScoreError(f"Cannot build P4: {exc}") from exc
    arms = [a for a in ARM_REGISTRY if a in pop.arms]
    label_of = {canonical_arm(label): label for label in config.arms}
    qtype_of = {q: str(gold_map[q].question_type) for q in g_ids}
    index = {(r.question_id, canonical_arm(r.graph_arm)): r for r in records}
    p4_ids = list(pop.question_ids)
    n_excluded = float(n_g - len(p4_ids))
    chunk_size = int(config.chunk_size)

    def paper(rec: RunRecord) -> dict[str, Any]:
        return paper_question_scores(
            _record_ranking_ids(rec), gold_sets[rec.question_id], id_matcher
        )

    def retrieval(fn: Callable[..., Any]) -> Callable[[RunRecord], float | None]:
        def value(rec: RunRecord) -> float | None:
            if rec.snapshot is None:
                return None
            out = fn(gold_map[rec.question_id], rec.snapshot.retrieved_chunks)
            return float(out.score) if out.status == "ok" else None

        return value

    def answer_of(rec: RunRecord) -> str:
        return rec.answer or ""

    def duration(rec: RunRecord) -> float | None:
        return float(rec.duration_ms)

    # The primaries' paired deltas (paper_hits_at_4, answer_usable) are not written
    # here: 06.3.5-13 computes them inside their Holm families. Every other row with a
    # delta_name is a secondary: a paired delta against hybrid with a bootstrap CI, no
    # p-value, never Holm-tested (D-111, D-115, D-123).
    metrics = [
        _Metric("paper_hits_at_4", lambda r: float(paper(r)["hit4"]), "wilson"),
        _Metric(
            "paper_hits_at_10",
            lambda r: float(paper(r)["hit10"]),
            "wilson",
            "paper_hits_at_10_delta",
        ),
        _Metric(
            "paper_mrr_at_10",
            lambda r: float(paper(r)["rr"]),
            "bootstrap",
            "paper_mrr_at_10_delta",
        ),
        _Metric(
            "paper_map_at_10",
            lambda r: float(paper(r)["ap"]),
            "bootstrap",
            "paper_map_at_10_delta",
        ),
        _Metric(
            "answer_usable_p4",
            lambda r: float(
                compute_answer_usable(gold_map[r.question_id], answer_of(r))
            ),
            "wilson",
        ),
        _Metric(
            "abstention_rate_g",
            lambda r: 1.0 if is_abstention(r) else 0.0,
            "wilson",
            "abstention_rate_g_delta",
        ),
        _Metric(
            "final_answer_em",
            lambda r: float(
                final_answer_em(gold_map[r.question_id], answer_of(r)).score or 0.0
            ),
            "wilson",
            "final_answer_em_delta",
        ),
        _Metric(
            "gold_containment",
            lambda r: float(
                gold_contained(gold_map[r.question_id].gold_answer, answer_of(r))
            ),
            "wilson",
            "gold_containment_delta",
        ),
        _Metric(
            "final_answer_missing_rate",
            lambda r: 1.0 if extract_final_answer(r.answer) is None else 0.0,
            "wilson",
            "final_answer_missing_rate_delta",
            counts=True,
        ),
        _Metric(
            "coverage_at_4",
            retrieval(lambda g, c: recall_at_k(g, c, k=4, chunk_size=chunk_size)),
            "bootstrap",
            "coverage_at_4_delta",
        ),
        _Metric(
            "precision_at_4",
            retrieval(lambda g, c: context_precision_at_k(g, c, k=4)),
            "bootstrap",
            "precision_at_4_delta",
        ),
        _Metric(
            "prompt_tokens_mean", _prompt_tokens, "bootstrap", "prompt_tokens_delta"
        ),
        # D-42 route: the paired difference is taken per question and reported as a
        # mean difference with its bootstrap CI. The p50 / p95 dimensions below stay
        # per-arm and descriptive: a difference of two arms' percentiles is not a
        # paired per-question statistic.
        _Metric(
            "latency_total_ms_mean", duration, "bootstrap", "latency_total_ms_delta"
        ),
        _Metric(
            "retrieve_node_ms_mean",
            _retrieve_node_ms,
            "bootstrap",
            "retrieve_node_ms_delta",
        ),
        _Metric("spend_usd_mean", _record_spend_usd, "bootstrap", "spend_usd_delta"),
    ]
    percentile_metrics = [
        ("latency_total_ms", duration),
        ("retrieve_node_ms", _retrieve_node_ms),
    ]
    reference = pop.reference_arm
    comparison_arms = [a for a in arms if a != reference]

    def p4_values(
        fn: Callable[[RunRecord], float | None],
    ) -> tuple[dict[str, dict[str, float]], int]:
        """Per-arm value maps over the P4 questions every arm can score."""
        raw = {
            arm: p4_mod.per_question_values(
                records,
                pop,
                arm,
                lambda rec: math.nan if (v := fn(rec)) is None else v,
            )
            for arm in arms
        }
        common = [
            q for q in p4_ids if all(not math.isnan(raw[arm][q]) for arm in arms)
        ]
        return (
            {arm: {q: raw[arm][q] for q in common} for arm in arms},
            len(p4_ids) - len(common),
        )

    dims: list[DimensionResult] = []
    empty = "P4 is empty: no held-out G question has an ok record on every arm"

    # p4_size: |P4|, the coverage and the per-arm exclusions (D-122).
    size_detail: dict[str, float] = {
        "coverage": float(pop.coverage),
        "n_heldout_g": float(n_g),
        "n_heldout_null": float(len(split.heldout_null_ids)),
    }
    for arm in arms:
        slug = arm_slug(arm)
        excl = pop.excluded[arm]
        size_detail[f"excluded_own_failure__{slug}"] = float(excl.own_failure)
        size_detail[f"excluded_provenance__{slug}"] = float(excl.provenance)
        size_detail[f"excluded_other_arm_failure__{slug}"] = float(
            excl.other_arm_failure
        )
        if arm in pop.pairwise_join_sizes:
            size_detail[f"pairwise_join_size__{slug}"] = float(
                pop.pairwise_join_sizes[arm]
            )
    dims.append(
        DimensionResult(
            name="p4_size",
            status="ok",
            score=float(len(p4_ids)),
            detail=size_detail,
            n=len(p4_ids),
        )
    )

    # Arm provenance (AI-SPEC 5 #1): reaching this point means no zero-tolerance
    # failure exists (score_run refused otherwise), so the score is 1.0. The counts
    # include (e), which excludes the record from P4, and (g), corroboration only.
    dims.append(
        DimensionResult(
            name="arm_provenance_conformance",
            status="ok",
            score=1.0,
            detail={
                **{f"code_{c}": float(provenance_counts[c]) for c in "abcdefg"},
                "records_checked": float(len(records)),
                "records_failing_zero_tolerance": 0.0,
            },
            n=len(records),
        )
    )

    for metric in metrics:
        by_arm, n_unscorable = p4_values(metric.value)
        for arm in arms:
            values = by_arm[arm]
            detail = {
                "n_excluded": n_excluded,
                "n_unscorable": float(n_unscorable),
            }
            if metric.name == "answer_usable_p4":
                detail["usable_blank_answer_count"] = float(
                    sum(
                        1
                        for q in values
                        if not (index[(q, arm)].answer or "").strip()
                    )
                )
            dim = _per_arm_dimension(
                f"{metric.name}__{arm_slug(arm)}",
                values,
                kind=metric.kind,
                qtype_of=qtype_of,
                detail=detail,
                empty_reason=empty,
            )
            if dim.status == "ok" and metric.name == "answer_usable_p4":
                dim.detail.update(strata.constant_yes_baselines(list(values), gold_map))
            dims.append(dim)
        if metric.delta_name is None:
            continue
        for arm in comparison_arms:
            dims.append(
                _delta_dimension(
                    f"{metric.delta_name}__{arm_slug(arm)}",
                    by_arm[arm],
                    by_arm[reference],
                    qtype_of=qtype_of,
                    counts=metric.counts,
                    detail={
                        "n_excluded": n_excluded,
                        "n_unscorable": float(n_unscorable),
                    },
                    empty_reason=empty,
                )
            )

    for base, fn in percentile_metrics:
        by_arm, n_unscorable = p4_values(fn)
        for arm in arms:
            for statistic in ("p50", "p95"):
                dims.append(
                    _per_arm_dimension(
                        f"{base}_{statistic}__{arm_slug(arm)}",
                        by_arm[arm],
                        kind="none",
                        statistic=statistic,  # type: ignore[arg-type]
                        qtype_of=qtype_of,
                        detail={
                            "n_excluded": n_excluded,
                            "n_unscorable": float(n_unscorable),
                        },
                        empty_reason=empty,
                    )
                )

    # D-122 script-faithful line: every held-out G question per arm; a record with no
    # valid ranking scores as an empty ranking (a miss). Labelled, never decisive.
    for arm in arms:
        scores: dict[str, dict[str, Any]] = {}
        no_ranking = 0
        for qid in g_ids:
            rec = index.get((qid, arm))
            valid = _has_valid_ranking(rec)
            if not valid:
                no_ranking += 1
            ids = _record_ranking_ids(rec) if valid and rec is not None else []
            scores[qid] = paper_question_scores(ids, gold_sets[qid], id_matcher)
        for name, key, kind in (
            ("paper_hits_at_4_script_faithful", "hit4", "wilson"),
            ("paper_hits_at_10_script_faithful", "hit10", "wilson"),
            ("paper_mrr_at_10_script_faithful", "rr", "bootstrap"),
            ("paper_map_at_10_script_faithful", "ap", "bootstrap"),
        ):
            dims.append(
                _per_arm_dimension(
                    f"{name}__{arm_slug(arm)}",
                    {q: float(scores[q][key]) for q in g_ids},
                    kind=kind,  # type: ignore[arg-type]
                    qtype_of=qtype_of,
                    detail={
                        "n_excluded": 0.0,
                        "n_no_valid_ranking": float(no_ranking),
                    },
                    empty_reason="the split has no held-out G question",
                )
            )

    # D-121 comparison line: the 06.3.4.1 SC-3 definition, per-arm usable records with
    # the inherited exclusions. Decides nothing.
    g_set = set(g_ids)
    for arm in arms:
        scored_by_qid: Mapping[str, float] = arm_metrics[label_of[arm]][
            "answer_usable_by_qid"
        ]
        values = {q: v for q, v in scored_by_qid.items() if q in g_set}
        dim = _per_arm_dimension(
            f"answer_usable_sc3_definition__{arm_slug(arm)}",
            values,
            kind="wilson",
            qtype_of=qtype_of,
            detail={"n_excluded": float(n_g - len(values))},
            empty_reason="no usable held-out G record carries a scorable payload",
        )
        if dim.status == "ok":
            dim.detail.update(strata.constant_yes_baselines(list(values), gold_map))
        dims.append(dim)

    # D-118 / D-105: null questions feed only this dimension, over the arm's ok(r)
    # null records. They never enter a retrieval or answer denominator.
    null_ids = list(split.heldout_null_ids)
    for arm in arms:
        null_recs = [
            rec
            for qid in null_ids
            if (rec := index.get((qid, arm))) is not None and provenance.is_ok(rec)
        ]
        name = f"null_abstention_correctness__{arm_slug(arm)}"
        if not null_recs:
            dims.append(
                DimensionResult(
                    name=name,
                    status="skipped",
                    reason="no ok record of this arm on a held-out null question",
                    detail={"n_excluded": float(len(null_ids))},
                    n=0,
                )
            )
            continue
        abstained = [1.0 if is_abstention(r) else 0.0 for r in null_recs]
        lo, hi = _interval(abstained, "wilson")
        dims.append(
            DimensionResult(
                name=name,
                status="ok",
                score=float(fmean(abstained)),
                detail={
                    "successes": float(sum(abstained)),
                    "ci_lower": float(lo),
                    "ci_upper": float(hi),
                    "n_excluded": float(len(null_ids) - len(null_recs)),
                    "hallucinated_on_null": float(
                        sum(
                            1
                            for r in null_recs
                            if not is_abstention(r) and r.structured_citations
                        )
                    ),
                    "no_evidence_count": float(
                        sum(
                            1
                            for r in null_recs
                            if any(
                                n.typed_code == 1 or n.code == "NO_EVIDENCE"
                                for n in r.notices
                            )
                        )
                    ),
                    "leak_count": float(
                        sum(1 for r in null_recs if abstention_leak(r))
                    ),
                },
                n=len(null_recs),
            )
        )
    return dims


# --- 06.3.5-12: the ordered judged pass (D-97, D-112, D-113, D-118, D-120, D-126) ---
#
# `score_run(judged=True)` is the only path that computes or writes judged
# aggregates for a corpus declaring `[judge] protocol = "ordered"`. It runs
# `calibration.ingest_and_verify` first, so every aggregate below exists only
# after the emit -> owner scores -> reveal order is proven from git. It reads
# `judge_cache.json` and makes no API call.

JUDGED_DIMENSIONS = ("groundedness", "faithfulness")
JUDGED_RESULT_FILE = "judged-result.json"
ABSTENTION_DIFFERS_FLAG = (
    "abstention differs: conditional on both arms answering; "
    "not an arm effect on grounding"
)
DELTA_STRATUM_LABEL = "unadjusted, estimation only"
ARM_MEANS_NOTE = "different question sets; compare arms only through the paired delta"
_ORDERED_REFUSAL = (
    'this corpus declares [judge] protocol = "ordered" (D-113, D-120), so {used} '
    "would compute judged aggregates before the owner's calibration scores are "
    "committed. Run `lancet-eval judge`, then `lancet-eval calibration emit`, have the "
    "owner score and commit the worksheet, reveal the key, and then run "
    "`lancet-eval score --judged --calibration-file <W> --calibration-key <K>`."
)


class JudgedStratum(BaseModel):
    """One D-40 stratum of a per-arm judged mean, beside that type's abstention rate."""

    model_config = ConfigDict(extra="forbid")

    question_type: str
    n: int
    mean: float | None = None
    ci: tuple[float, float] | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    abstention_rate: float | None = None
    abstention_n: int = 0


class JudgedArmRow(BaseModel):
    """A per-arm judged mean over J_a, always beside the arm's abstention rate."""

    model_config = ConfigDict(extra="forbid")

    arm: str
    dimension: str
    n: int
    mean: float | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    judge_errors: int
    abstention_rate: float | None = None
    abstention_n: int
    d114_label: str
    comparability_note: str = ARM_MEANS_NOTE
    strata: list[JudgedStratum]


class JudgedDeltaStratum(BaseModel):
    """One D-40 stratum of a paired judged delta; a CI is estimation only (D-123)."""

    model_config = ConfigDict(extra="forbid")

    question_type: str
    n_pairs: int
    delta: float | None = None
    ci: tuple[float, float] | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    ci_label: str | None = None
    abstention_rate_arm: float | None = None
    abstention_rate_reference: float | None = None
    abstention_n: int = 0


class JudgedDeltaRow(BaseModel):
    """A paired judged delta against the reference with selection-effect columns."""

    model_config = ConfigDict(extra="forbid")

    arm: str
    reference: str
    dimension: str
    n_pairs: int
    delta: float | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    dropped_only_arm_abstained: int
    dropped_only_reference_abstained: int
    dropped_both_abstained: int
    dropped_judge_unavailable: int
    judge_errors_arm: int
    judge_errors_reference: int
    abstention_rate_arm: float | None = None
    abstention_rate_reference: float | None = None
    abstention_n: int
    abstention_rate_delta: float | None = None
    abstention_rate_delta_ci_lower: float | None = None
    abstention_rate_delta_ci_upper: float | None = None
    flag: str | None = None
    d114_label: str
    strata: list[JudgedDeltaStratum]


class JudgedCommits(BaseModel):
    """The commits that prove the D-120 order."""

    model_config = ConfigDict(extra="forbid")

    emitted_at_sha: str
    worksheet_commit: str
    scores_commit: str
    key_commit: str
    salt_commit: str
    d114_floor: float


class JudgedResult(BaseModel):
    """`judged-result.json`: every text label of the judged pass (D-126).

    `report.json` carries only floats; the labels, the lines and the selection-effect
    text live here. No row carries a p-value: judged numbers are secondaries.
    """

    model_config = ConfigDict(extra="forbid")

    corpus: str
    judge_model: str
    judge_prompt_version: str
    commits: JudgedCommits
    labels: dict[str, str]
    agreement: dict[str, Any]
    legacy_lines: list[str]
    divergence_lines: list[str]
    dropped_slice_ids: list[str]
    arms: list[JudgedArmRow]
    deltas: list[JudgedDeltaRow]
    report_lines: list[str]


def _ordered_protocol_guard(
    config: Any,
    *,
    judged: bool,
    no_judge: bool,
    sample: int | None,
    emit_calibration_worksheet: Path | str | None,
    calibration_file: Path | str | None,
    calibration_key: Path | str | None,
    stage_spend_cap: float | None,
) -> None:
    """Refuses legacy judged inputs on an ordered corpus and a malformed `--judged`.

    Raises:
        ScoreError: Naming `lancet-eval judge`, `lancet-eval calibration emit` and
            `score --judged` when a legacy judged input meets an ordered corpus, or the
            reason a `--judged` call cannot proceed.
    """
    ordered = getattr(config, "judge_protocol", "legacy") == "ordered"
    if not judged:
        if ordered:
            used = []
            if not no_judge:
                used.append("`score --judge`")
            if emit_calibration_worksheet is not None:
                used.append("`--emit-calibration-worksheet`")
            if calibration_file is not None:
                used.append("`--calibration-file` without `--judged`")
            if calibration_key is not None:
                used.append("`--calibration-key` without `--judged`")
            if used:
                raise ScoreError(_ORDERED_REFUSAL.format(used=" and ".join(used)))
        return
    if not ordered:
        raise ScoreError(
            '--judged needs a corpus that declares [judge] protocol = "ordered"; '
            f"corpus {config.name!r} does not (use the legacy `score --judge`)"
        )
    if config.split_file is None:
        raise ScoreError("--judged needs a corpus that declares a [split] (P4, D-121)")
    if not no_judge or emit_calibration_worksheet is not None:
        raise ScoreError(
            "--judged is cache-only: it cannot be combined with --judge or "
            "--emit-calibration-worksheet (D-113)"
        )
    if sample is not None or stage_spend_cap is not None:
        raise ScoreError(
            "--judged judges nothing new, so --sample and --stage-cap do not apply; "
            "the judged population is the whole cached stage (D-112)"
        )
    if calibration_file is None or calibration_key is None:
        raise ScoreError("--judged needs both --calibration-file and --calibration-key")


def _stratum_rows(
    detail: Mapping[str, float], abstention: Mapping[str, float]
) -> list[JudgedStratum]:
    rows = []
    for qtype in strata.STRATUM_TYPES:
        lower = detail.get(f"type_{qtype}_ci_lower")
        upper = detail.get(f"type_{qtype}_ci_upper")
        rows.append(
            JudgedStratum(
                question_type=qtype,
                n=int(detail.get(f"type_{qtype}_n", 0)),
                mean=detail.get(f"type_{qtype}_value"),
                ci=(lower, upper) if lower is not None and upper is not None else None,
                ci_lower=lower,
                ci_upper=upper,
                abstention_rate=abstention.get(f"type_{qtype}_value"),
                abstention_n=int(abstention.get(f"type_{qtype}_n", 0)),
            )
        )
    return rows


def _delta_stratum_rows(
    detail: Mapping[str, float],
    arm_abstention: Mapping[str, float],
    reference_abstention: Mapping[str, float],
) -> list[JudgedDeltaStratum]:
    """The paired-delta strata beside both arms' per-type abstention rate (D-118)."""
    rows = []
    for qtype in strata.STRATUM_TYPES:
        lower = detail.get(f"type_{qtype}_ci_lower")
        upper = detail.get(f"type_{qtype}_ci_upper")
        rows.append(
            JudgedDeltaStratum(
                question_type=qtype,
                n_pairs=int(detail.get(f"type_{qtype}_n_pairs", 0)),
                delta=detail.get(f"type_{qtype}_delta"),
                ci=(lower, upper) if lower is not None and upper is not None else None,
                ci_lower=lower,
                ci_upper=upper,
                ci_label=DELTA_STRATUM_LABEL if lower is not None else None,
                abstention_rate_arm=arm_abstention.get(f"type_{qtype}_value"),
                abstention_rate_reference=reference_abstention.get(
                    f"type_{qtype}_value"
                ),
                abstention_n=int(arm_abstention.get(f"type_{qtype}_n", 0)),
            )
        )
    return rows


def _qwk_dimension(dimension: str, d: Mapping[str, Any]) -> DimensionResult:
    """`judge_qwk_<dimension>`: the QWK point estimate and its float companions."""
    detail: dict[str, float] = {
        "n_pairs": float(d["n_pairs"]),
        "d114_floor": float(d["floor"]),
        "d114_label_code": float(d["label_code"]),
        "qwk_dropped_resamples": float(d["qwk_dropped_resamples"]),
        "spearman_dropped_resamples": float(d["spearman_dropped_resamples"]),
    }
    optional = {
        "ci_lower": d["qwk_ci_lower"],
        "ci_upper": d["qwk_ci_upper"],
        "spearman": d["spearman"],
        "spearman_ci_lower": d["spearman_ci_lower"],
        "spearman_ci_upper": d["spearman_ci_upper"],
        "exact_agreement": d["exact_agreement"],
        "mad": d["mad"],
        "mean_signed_difference": d["mean_signed_difference"],
        "joint_5_5_share": d["joint_5_5_share"],
    }
    for key, value in optional.items():
        if value is not None:
            detail[key] = float(value)
    for value in range(1, 6):
        detail[f"judge_marginal_{value}"] = float(d["judge_marginals"][str(value)])
        detail[f"human_marginal_{value}"] = float(d["human_marginals"][str(value)])
    for arm, counts in d["per_arm_exact_agreement"].items():
        detail[f"exact_agreement_n__{arm_slug(arm)}"] = float(counts["n"])
        detail[f"exact_agreement_exact__{arm_slug(arm)}"] = float(counts["exact"])
    name = f"judge_qwk_{dimension}"
    if d["qwk"] is None:
        return DimensionResult(
            name=name,
            status="skipped",
            reason=(
                f"{d['label']}: the QWK state is {d['qwk_state']} on "
                f"{d['n_pairs']} scored pair(s)"
            ),
            detail=detail,
            n=int(d["n_pairs"]),
        )
    return DimensionResult(
        name=name,
        status="ok",
        score=float(d["qwk"]),
        detail=detail,
        n=int(d["n_pairs"]),
    )


def _judged_dimensions(
    *,
    records: Sequence[RunRecord],
    config: Any,
    inputs: _SplitInputs,
    gold_map: Mapping[str, Any],
    cache: JudgeCache,
    verified: Any,
    four_arm: Sequence[DimensionResult],
) -> tuple[list[DimensionResult], JudgedResult]:
    """The judged dimensions and the sidecar of a verified ordered run (06.3.5-12).

    Per-arm judged means are over J_a (P4, 06.3.5-judgeable, non-error verdict) and are
    always carried beside the arm's abstention rate and its n. Paired judged deltas
    against `hybrid` cover the P4 questions where both arms gave a judged,
    non-abstaining answer, with the selection-effect counts and the paired
    abstention-rate delta read from the four-arm dimensions already computed (one
    definition, no second delta).

    Raises:
        ScoreError: If the arms cannot form P4 or the agreement cannot be summarised.
    """
    from lancet_eval import calibration  # imported late: calibration imports score

    try:
        summary = calibration.agreement_summary(verified, cache)
        pop = p4_mod.build_p4(records, inputs.split, config.arms)
    except (calibration.CalibrationError, ValueError) as exc:
        raise ScoreError(f"Cannot compute the judged pass: {exc}") from exc
    arms = [a for a in ARM_REGISTRY if a in pop.arms]
    reference = pop.reference_arm
    index = {(r.question_id, canonical_arm(r.graph_arm)): r for r in records}
    qtype_of = {q: str(gold_map[q].question_type) for q in inputs.split.heldout_g_ids}
    by_name = {d.name: d for d in four_arm}
    labels = {d: summary["dimensions"][d]["label"] for d in JUDGED_DIMENSIONS}
    codes = {
        d: float(summary["dimensions"][d]["label_code"]) for d in JUDGED_DIMENSIONS
    }

    def verdict_of(rec: RunRecord) -> Any:
        gold = gold_map[rec.question_id]
        entry = cache.get(
            cache_key(
                prompt_version=config.judge_prompt_version,
                judge_model=config.judge_model,
                question=gold.question,
                answer=rec.answer or "",
                post_truncation_evidence=truncate_evidence(rec.structured_citations),
            )
        )
        return None if entry is None else entry.verdict

    def judgeable(rec: RunRecord) -> bool:
        return _is_judgeable(rec, gold_map, policy="06.3.5")

    def judged_ok(rec: RunRecord) -> bool:
        return judgeable(rec) and verdict_of(rec) is not None

    def score_of(rec: RunRecord, dimension: str) -> float:
        verdict = verdict_of(rec)
        return float(getattr(verdict, dimension))

    errors = {
        arm: sum(
            1
            for q in pop.question_ids
            if judgeable(index[(q, arm)]) and verdict_of(index[(q, arm)]) is None
        )
        for arm in arms
    }

    def abstention(arm: str) -> DimensionResult | None:
        dim = by_name.get(f"abstention_rate_g__{arm_slug(arm)}")
        return dim if dim is not None and dim.status == "ok" else None

    dims: list[DimensionResult] = []
    arm_rows: list[JudgedArmRow] = []
    delta_rows: list[JudgedDeltaRow] = []
    empty = "no judged, non-abstaining answer of this arm in P4"
    for arm in arms:
        slug = arm_slug(arm)
        abs_dim = abstention(arm)
        abs_rate = abs_dim.score if abs_dim is not None else None
        abs_n = abs_dim.n if abs_dim is not None else 0
        j_a = {
            q: index[(q, arm)]
            for q in pop.question_ids
            if judged_ok(index[(q, arm)])
        }
        for dimension in JUDGED_DIMENSIONS:
            detail: dict[str, float] = {
                "judge_errors": float(errors[arm]),
                "n_p4": float(len(pop.question_ids)),
                "abstention_n": float(abs_n),
                "d114_label_code": codes[dimension],
            }
            if abs_rate is not None:
                detail["abstention_rate"] = float(abs_rate)
            dim = _per_arm_dimension(
                f"answer_{dimension}__{slug}",
                {q: score_of(r, dimension) for q, r in j_a.items()},
                kind="bootstrap",
                qtype_of=qtype_of,
                detail=detail,
                empty_reason=empty,
            )
            dims.append(dim)
            arm_rows.append(
                JudgedArmRow(
                    arm=arm,
                    dimension=dimension,
                    n=dim.n,
                    mean=dim.score,
                    ci_lower=dim.detail.get("ci_lower"),
                    ci_upper=dim.detail.get("ci_upper"),
                    judge_errors=errors[arm],
                    abstention_rate=abs_rate,
                    abstention_n=abs_n,
                    d114_label=labels[dimension],
                    strata=_stratum_rows(
                        dim.detail, abs_dim.detail if abs_dim is not None else {}
                    ),
                )
            )

    ref_abs = abstention(reference)
    for arm in arms:
        if arm == reference:
            continue
        slug = arm_slug(arm)
        try:
            counts = p4_mod.judged_pairs(
                records, pop, arm, reference, judged_ok=judged_ok
            )
        except ValueError as exc:
            raise ScoreError(f"Cannot form the judged pairs: {exc}") from exc
        pairs = list(counts.pair_question_ids)
        arm_abs = abstention(arm)
        abs_delta = by_name.get(f"abstention_rate_g_delta__{slug}")
        delta_ok = abs_delta is not None and abs_delta.status == "ok"
        for dimension in JUDGED_DIMENSIONS:
            detail = {
                "dropped_only_arm_abstained": float(counts.only_x_abstained),
                "dropped_only_hybrid_abstained": float(counts.only_reference_abstained),
                "dropped_both_abstained": float(counts.both_abstained),
                "dropped_judge_unavailable": float(counts.judge_unavailable),
                "judge_errors_x": float(errors[arm]),
                "judge_errors_hybrid": float(errors[reference]),
                "abstention_n": float(len(pop.question_ids)),
                "d114_label_code": codes[dimension],
            }
            if arm_abs is not None and arm_abs.score is not None:
                detail["abstention_rate_x"] = float(arm_abs.score)
            if ref_abs is not None and ref_abs.score is not None:
                detail["abstention_rate_hybrid"] = float(ref_abs.score)
            differs = False
            if delta_ok and abs_delta is not None and abs_delta.score is not None:
                lo = abs_delta.detail.get("ci_lower")
                hi = abs_delta.detail.get("ci_upper")
                detail["abstention_rate_delta"] = float(abs_delta.score)
                if lo is not None and hi is not None:
                    detail["abstention_rate_delta_ci_lower"] = float(lo)
                    detail["abstention_rate_delta_ci_upper"] = float(hi)
                    differs = lo > 0 or hi < 0
            detail["abstention_differs"] = 1.0 if differs else 0.0
            dim = _delta_dimension(
                f"answer_{dimension}_delta__{slug}",
                {q: score_of(index[(q, arm)], dimension) for q in pairs},
                {q: score_of(index[(q, reference)], dimension) for q in pairs},
                qtype_of=qtype_of,
                counts=False,
                detail=detail,
                empty_reason="no P4 question where both arms gave a judged answer",
            )
            dims.append(dim)
            delta_rows.append(
                JudgedDeltaRow(
                    arm=arm,
                    reference=reference,
                    dimension=dimension,
                    n_pairs=dim.n,
                    delta=dim.score,
                    ci_lower=dim.detail.get("ci_lower"),
                    ci_upper=dim.detail.get("ci_upper"),
                    dropped_only_arm_abstained=counts.only_x_abstained,
                    dropped_only_reference_abstained=counts.only_reference_abstained,
                    dropped_both_abstained=counts.both_abstained,
                    dropped_judge_unavailable=counts.judge_unavailable,
                    judge_errors_arm=errors[arm],
                    judge_errors_reference=errors[reference],
                    abstention_rate_arm=arm_abs.score if arm_abs is not None else None,
                    abstention_rate_reference=(
                        ref_abs.score if ref_abs is not None else None
                    ),
                    abstention_n=len(pop.question_ids),
                    abstention_rate_delta=detail.get("abstention_rate_delta"),
                    abstention_rate_delta_ci_lower=detail.get(
                        "abstention_rate_delta_ci_lower"
                    ),
                    abstention_rate_delta_ci_upper=detail.get(
                        "abstention_rate_delta_ci_upper"
                    ),
                    flag=ABSTENTION_DIFFERS_FLAG if differs else None,
                    d114_label=labels[dimension],
                    strata=_delta_stratum_rows(
                        dim.detail,
                        arm_abs.detail if arm_abs is not None else {},
                        ref_abs.detail if ref_abs is not None else {},
                    ),
                )
            )

    for dimension in JUDGED_DIMENSIONS:
        dims.append(_qwk_dimension(dimension, summary["dimensions"][dimension]))

    lines = _judged_report_lines(summary, arm_rows, delta_rows)
    result = JudgedResult(
        corpus=config.name,
        judge_model=config.judge_model,
        judge_prompt_version=config.judge_prompt_version,
        commits=JudgedCommits(
            emitted_at_sha=verified.emitted_at_sha,
            worksheet_commit=verified.worksheet_commit,
            scores_commit=verified.scores_commit,
            key_commit=verified.key_commit,
            salt_commit=verified.salt_commit,
            d114_floor=verified.floor,
        ),
        labels=labels,
        agreement=summary,
        legacy_lines=summary["legacy_lines"],
        divergence_lines=summary["divergence_lines"],
        dropped_slice_ids=summary["dropped_slice_ids"],
        arms=arm_rows,
        deltas=delta_rows,
        report_lines=lines,
    )
    return dims, result


def _fmt_num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _fmt_ci(lower: float | None, upper: float | None) -> str:
    if lower is None or upper is None:
        return "no CI"
    return f"95% CI [{lower:.4f}, {upper:.4f}]"


def _judged_report_lines(
    summary: Mapping[str, Any],
    arm_rows: Sequence[JudgedArmRow],
    delta_rows: Sequence[JudgedDeltaRow],
) -> list[str]:
    """The printed text of the judged pass; ASCII only."""
    lines: list[str] = []
    for dimension in JUDGED_DIMENSIONS:
        d = summary["dimensions"][dimension]
        lines.append(
            f"judge-human agreement, {dimension}: n={d['n_pairs']} "
            f"QWK {_fmt_num(d['qwk'])} {_fmt_ci(d['qwk_ci_lower'], d['qwk_ci_upper'])} "
            f"(B=10000, {d['qwk_dropped_resamples']} resample(s) dropped as "
            "undefined), "
            f"Spearman {_fmt_num(d['spearman'])} "
            f"{_fmt_ci(d['spearman_ci_lower'], d['spearman_ci_upper'])}; "
            f"exact {_fmt_num(d['exact_agreement'])}, MAD {_fmt_num(d['mad'])}, "
            f"mean signed difference (judge - human) "
            f"{_fmt_num(d['mean_signed_difference'])}, joint 5/5 share "
            f"{_fmt_num(d['joint_5_5_share'])}; D-114 label: {d['label']}"
        )
        marginals = ", ".join(
            f"{who} "
            + "/".join(str(d[f"{who}_marginals"][str(v)]) for v in range(1, 6))
            for who in ("judge", "human")
        )
        per_arm = ", ".join(
            f"{arm} {c['exact']}/{c['n']}"
            for arm, c in d["per_arm_exact_agreement"].items()
        )
        lines.append(
            f"  {dimension} marginal counts over 1..5: {marginals}; per-arm exact "
            f"agreement (no statistic at this n): {per_arm}"
        )
    lines.extend(summary["legacy_lines"])
    lines.extend(summary["divergence_lines"])
    if summary["dropped_slice_ids"]:
        lines.append(
            "slice items dropped (judge error, no redraw): "
            + ", ".join(summary["dropped_slice_ids"])
        )
    for row in arm_rows:
        lines.append(
            f"{row.arm} {row.dimension}: mean {_fmt_num(row.mean)} "
            f"{_fmt_ci(row.ci_lower, row.ci_upper)} n={row.n} "
            f"judge errors {row.judge_errors}; abstention rate "
            f"{_fmt_num(row.abstention_rate)} (n={row.abstention_n}); "
            f"{row.d114_label} ({row.comparability_note})"
        )
    for drow in delta_rows:
        flag = f" [{drow.flag}]" if drow.flag else ""
        abstention_ci = _fmt_ci(
            drow.abstention_rate_delta_ci_lower, drow.abstention_rate_delta_ci_upper
        )
        lines.append(
            f"{drow.arm} - {drow.reference} {drow.dimension}: delta "
            f"{_fmt_num(drow.delta)} {_fmt_ci(drow.ci_lower, drow.ci_upper)} "
            f"n_pairs={drow.n_pairs}; dropped only-{drow.arm} "
            f"{drow.dropped_only_arm_abstained}, only-{drow.reference} "
            f"{drow.dropped_only_reference_abstained}, both "
            f"{drow.dropped_both_abstained}, judge unavailable "
            f"{drow.dropped_judge_unavailable}; judge errors {drow.arm} "
            f"{drow.judge_errors_arm}, {drow.reference} "
            f"{drow.judge_errors_reference}; abstention rate {drow.arm} "
            f"{_fmt_num(drow.abstention_rate_arm)} (n={drow.abstention_n}), "
            f"{drow.reference} {_fmt_num(drow.abstention_rate_reference)} "
            f"(n={drow.abstention_n}); abstention delta "
            f"{_fmt_num(drow.abstention_rate_delta)} "
            f"{abstention_ci}; {drow.d114_label}{flag}"
        )
    return lines


def score_run(
    *,
    run_dir: Path | str,
    no_judge: bool = True,
    sample: int | None = None,
    emit_calibration_worksheet: Path | str | None = None,
    calibration_file: Path | str | None = None,
    api_key: str | None = None,
    client: httpx.Client | None = None,
    stage_spend_cap: float | None = None,
    git_repo: Path | None = None,
    gold_chunks_path: Path | str | None = None,
    judged: bool = False,
    calibration_key: Path | str | None = None,
) -> CorpusReport:
    """Read a run journal and produce a scored evaluation report.

    A `[split]` corpus's journal is refused (D-73) unless the commits introducing
    `PREREGISTRATION_06_3_5` and `JUDGE_QWK_TRUST_FLOOR` are ancestors of HEAD and
    older than the journal header's `created_at`. `git_repo` points that check at
    another repository; it is the live repository when None.

    A corpus declaring `[judge] protocol = "ordered"` refuses `no_judge=False`,
    `emit_calibration_worksheet` and a `calibration_file` without `judged=True`
    (D-113, D-120). `judged=True` with `calibration_file` (the owner-scored worksheet)
    and `calibration_key` is the only path that computes judged aggregates for such a
    corpus: it first proves the emit -> scores -> reveal order from git, reads the
    salt from `calibration-salt.txt` beside the key, makes no API call, and writes
    `judged-result.json` next to `report.json`.
    """
    dir_path = Path(run_dir)
    journal_path = dir_path / "journal.jsonl"
    if not journal_path.is_file():
        journal_path = dir_path / "journal.json"
    if not journal_path.is_file():
        raise ScoreError(f"No journal file found in {dir_path}")

    # Read journal records
    records: list[RunRecord] = []
    header_corpus: str | None = None
    header_partial: bool | None = None
    header_created_at: object = None
    header_split_marker: dict[str, Any] = {}
    with open(journal_path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
            except Exception as e:
                raise ScoreError(
                    f"Corrupted JSON in journal at line {line_num}: {e}"
                ) from e

            if isinstance(data, dict) and data.get("type") == "header":
                header_corpus = data.get("corpus")
                header_created_at = data.get("created_at")
                header_split_marker = {
                    k: data[k] for k in ("order_seed", "split_sha256") if k in data
                }
                if "partial" in data:
                    header_partial = bool(data["partial"])
                continue

            if isinstance(data, dict) and "question_id" in data:
                try:
                    rec = RunRecord.model_validate(data)
                    records.append(rec)
                except Exception as e:
                    raise ScoreError(
                        f"Invalid RunRecord at line {line_num}: {e}"
                    ) from e

    if not records:
        raise ScoreError(f"Journal {journal_path} contains no evaluation records")

    # WR-02: Deduplicate records journal-wide per (question_id, graph_arm)
    records, collapsed_records_n = deduplicate_by_arm(records)

    corpus_name = header_corpus or records[0].corpus

    # 1. Structural Guard: Refuse mixed index_generation
    distinct_gens: set[str] = set()
    for rec in records:
        if rec.index_generation:
            distinct_gens.add(rec.index_generation)
    if len(distinct_gens) > 1:
        gens_list = sorted(distinct_gens)
        raise ScoreError(
            f"Mixed index generations detected in journal: "
            f"{gens_list[0]} vs {gens_list[1]}"
        )

    # 2. Structural Guard: Validate all document_ids against document_map.json
    try:
        doc_map = load_document_map(corpus_name)
    except Exception as e:
        raise ScoreError(
            f"Could not load document map for corpus '{corpus_name}': {e}"
        ) from e

    for rec in records:
        if rec.snapshot and rec.snapshot.retrieved_chunks:
            for chunk in rec.snapshot.retrieved_chunks:
                if (
                    chunk.document_id not in doc_map.entries
                    and chunk.document_id not in doc_map.aliases
                ):
                    raise ScoreError(
                        f"Unmapped document_id '{chunk.document_id}' in record "
                        f"for question '{rec.question_id}'"
                    )

    # Load gold questions and config
    config = load_corpus_config(corpus_name)
    _ordered_protocol_guard(
        config,
        judged=judged,
        no_judge=no_judge,
        sample=sample,
        emit_calibration_worksheet=emit_calibration_worksheet,
        calibration_file=calibration_file,
        calibration_key=calibration_key,
        stage_spend_cap=stage_spend_cap,
    )
    # The legacy ingest below never sees the ordered worksheet.
    legacy_calibration_file = None if judged else calibration_file
    if config.split_file is not None:
        _require_preregistered_before(header_created_at, git_repo)
    sampled_questions = load_sample_questions(corpus_name)
    gold_map = {q.question_id: q for q in sampled_questions}

    # Group records by the corpus's configured arm labels (D-101, D-120); a label that
    # cannot be attributed raises rather than being dropped.
    records_by_arm = _group_records_by_arm(records, config.arms)

    # A `[split]` corpus's four-arm report reads the split and the gold-chunk table;
    # a gap in either refuses before any judge spend (06.3.5-10).
    split_inputs: _SplitInputs | None = None
    provenance_counts: dict[str, int] = {}
    if config.split_file is not None:
        # AI-SPEC 6, "Provenance in the paid drive": a zero-tolerance failure (clauses
        # a, b, c, d, f) means the plumbing is wrong for an unknown share of records,
        # so the report is refused, not counted as an exclusion. (e) keeps its
        # count-and-exclude rule and (g) is counted only. Legacy corpora never run this.
        provenance_counts, failing = _provenance_scan(records)
        if failing:
            listed = ", ".join(
                f"{qid}/{arm}/{codes}"
                for qid, arm, codes in failing[:_PROVENANCE_REFUSAL_LISTED]
            )
            more = len(failing) - _PROVENANCE_REFUSAL_LISTED
            tail = f" (and {more} more)" if more > 0 else ""
            raise ScoreError(
                f"arm provenance failed on {len(failing)} record(s) (zero tolerance, "
                "AI-SPEC §6); D-110 allows one bounded re-drive after a plumbing fix: "
                f"{listed}{tail}"
            )
        split_inputs = _load_split_inputs(config, gold_map, gold_chunks_path)
        _require_split_marker_matches(header_split_marker, split_inputs.split)

    # D-113 / D-120 step 7: nothing judged exists before the order is proven.
    verified: Any = None
    judged_cache: JudgeCache | None = None
    if judged:
        from lancet_eval import calibration  # late: calibration imports score

        assert calibration_file is not None and calibration_key is not None
        key_path = Path(calibration_key)
        try:
            verified = calibration.ingest_and_verify(
                dir_path,
                calibration_file,
                key_path,
                key_path.parent / calibration.SALT_FILE,
                repo=git_repo,
            )
        except calibration.CalibrationError as exc:
            raise ScoreError(f"D-120: refusing the judged pass: {exc}") from exc
        judged_cache = JudgeCache(dir_path / calibration.CACHE_FILE)

    # Compute deterministic scores for every configured arm
    arm_metrics: dict[str, dict[str, Any]] = {}

    for arm, arm_records in records_by_arm.items():
        # D-101: the GRAPH_ABLATION provenance check holds every arm that switches
        # graph context off, not only the literal `graph-off`.
        needs_ablation_provenance = resolve_arm(arm).disable_graph_context
        total_records = len(arm_records)
        unusable_records = [r for r in arm_records if not is_usable(r)]
        usable_records = [r for r in arm_records if is_usable(r)]

        recalls: list[float] = []
        precisions: list[float] = []
        mrrs: list[float] = []
        ndcgs: list[float] = []
        ems: list[float] = []
        f1s: list[float] = []
        abstentions: list[float] = []
        final_answer_ems: list[float] = []
        final_answer_containments: list[float] = []
        answer_usables: list[float] = []
        answer_usable_by_qid: dict[str, float] = {}
        final_answer_missings: list[float] = []
        null_abstention_corrects: list[float] = []
        payload_excluded_answerable_count = 0
        payload_excluded_unanswerable_count = 0
        provenance_error_count = 0

        for rec in usable_records:
            gold = gold_map.get(rec.question_id)
            if not gold:
                continue

            # Provenance check on every graph-context-off arm
            if needs_ablation_provenance and not has_arm_provenance(rec):
                provenance_error_count += 1
                continue

            # Scorable payload guard: must carry retrieval snapshot and non-blank answer
            if not has_scorable_payload(rec):
                if gold.is_null:
                    payload_excluded_unanswerable_count += 1
                else:
                    payload_excluded_answerable_count += 1
                continue

            # Retrieval dimensions strictly read snapshot.retrieved_chunks
            chunks = rec.snapshot.retrieved_chunks
            if not gold.is_null:
                # Recall@4
                r_out = recall_at_k(gold, chunks, k=4, chunk_size=config.chunk_size)
                if r_out.status == "ok" and r_out.score is not None:
                    recalls.append(r_out.score)
                # Precision@4
                p_out = context_precision_at_k(gold, chunks, k=4)
                if p_out.status == "ok" and p_out.score is not None:
                    precisions.append(p_out.score)
                # MRR@10
                m_out = mrr_at_k(gold, chunks, k=10)
                if m_out.status == "ok" and m_out.score is not None:
                    mrrs.append(m_out.score)
                # nDCG@10
                n_out = ndcg_at_k(gold, chunks, k=10, chunk_size=config.chunk_size)
                if n_out.status == "ok" and n_out.score is not None:
                    ndcgs.append(n_out.score)

            # Answer metrics
            if rec.answer is not None and not gold.is_null:
                em_out = squad_em(gold, rec.answer)
                if em_out.status == "ok" and em_out.score is not None:
                    ems.append(em_out.score)
                f1_out = squad_f1(gold, rec.answer)
                if f1_out.status == "ok" and f1_out.score is not None:
                    f1s.append(f1_out.score)

                # D-70: metrics on the extracted `Answer:` line (next to the
                # unchanged full-explanation EM/F1 above). final_answer_missing
                # records stay in every one of these denominators (D-34/D-74).
                fa_em_out = final_answer_em(gold, rec.answer)
                if fa_em_out.status == "ok" and fa_em_out.score is not None:
                    final_answer_ems.append(fa_em_out.score)
                final_answer_containments.append(
                    1.0 if gold_contained(gold.gold_answer, rec.answer) else 0.0
                )
                usable_value = 1.0 if compute_answer_usable(gold, rec.answer) else 0.0
                answer_usables.append(usable_value)
                answer_usable_by_qid[rec.question_id] = usable_value
                final_answer_missings.append(
                    1.0 if extract_final_answer(rec.answer) is None else 0.0
                )

            # Abstention on unanswerable
            if gold.is_null:
                snap_chunks = rec.snapshot.retrieved_chunks if rec.snapshot else None
                abs_out = abstention_rate(
                    gold, rec.answer or "", snap_chunks, rec.notices
                )
                if abs_out.status == "ok" and abs_out.score is not None:
                    abstentions.append(abs_out.score)
                # D-72: null_abstention_correctness, null_query records only.
                nac_out = null_abstention_correct(gold, rec.answer or "")
                if nac_out.status == "ok" and nac_out.score is not None:
                    null_abstention_corrects.append(nac_out.score)

        arm_metrics[arm] = {
            "total": total_records,
            "errors": len(unusable_records) + provenance_error_count,
            "success": len(usable_records) - provenance_error_count,
            "provenance_excluded": provenance_error_count,
            "payload_excluded_answerable": payload_excluded_answerable_count,
            "payload_excluded_unanswerable": payload_excluded_unanswerable_count,
            "recalls": recalls,
            "precisions": precisions,
            "mrrs": mrrs,
            "ndcgs": ndcgs,
            "ems": ems,
            "f1s": f1s,
            "abstentions": abstentions,
            "final_answer_ems": final_answer_ems,
            "final_answer_containments": final_answer_containments,
            "answer_usables": answer_usables,
            "answer_usable_by_qid": answer_usable_by_qid,
            "final_answer_missings": final_answer_missings,
            "null_abstention_corrects": null_abstention_corrects,
            "usable_records": [
                r
                for r in usable_records
                if not needs_ablation_provenance or has_arm_provenance(r)
            ],
        }

    # WR-03: Primary scoring arm is chosen from the arm that actually has records
    primary_arm = _primary_arm(
        config.arms, {label: m["total"] for label, m in arm_metrics.items()}
    )
    p_data = arm_metrics[primary_arm]
    p_records = records_by_arm.get(primary_arm, [])

    # LLM-as-judge evaluation pass
    groundedness_scores: list[int | float] = []
    faithfulness_scores: list[int | float] = []
    judge_errors = 0
    skipped_no_evidence = 0
    judged_sample_count = 0
    cache_path = dir_path / "judge_cache.json"
    cache = JudgeCache(cache_path)
    judged_qids: set[str] = set()
    judge_stop_note: str = ""
    sample_clamp_note: str = ""
    cap_stop_discloses_fallback: bool = False
    cached_verdict_count = _reusable_verdict_count(
        cache,
        prompt_version=config.judge_prompt_version,
        judge_model=config.judge_model,
        records=p_records,
        gold_map=gold_map,
    )
    judged_slice_committed: int = 0
    verdicts_obtained: int = 0
    judged_slice_state_code: float = JUDGED_SLICE_STATE_NOT_JUDGED
    judged_slice_state: str = JUDGED_SLICE_STATES[JUDGED_SLICE_STATE_NOT_JUDGED]
    usage_absent_fallback_count: int = 0

    if legacy_calibration_file is not None:
        if no_judge and cached_verdict_count > 0:
            raise ScoreError(
                "calibration_file was provided with --no-judge, but "
                f"judge_cache.json already has {cached_verdict_count} cached "
                "verdict(s) from a prior --judge invocation. Running without "
                "--judge here would silently discard that judged population "
                "when report.json is rewritten (score_run always rewrites "
                "report.json on a non-partial run). Re-run with --judge "
                "(same --sample scope used to build the cache) to feed "
                "calibration scores back safely."
            )
        if sample is not None and sample < cached_verdict_count:
            raise ScoreError(
                f"calibration_file was provided with --sample {sample}, "
                f"narrower than the {cached_verdict_count} verdict(s) already "
                "cached in judge_cache.json from a prior, larger judging "
                "invocation. This would silently shrink the judged population "
                "report.json records. Re-run without --sample (or with a "
                "value >= the cached verdict count) before feeding back "
                "calibration scores."
            )

    if not no_judge:
        # Check judge model distinctness from generator model
        gen_model = _get_engine_generation_model()
        if not gen_model or not gen_model.strip():
            raise ScoreError(
                "Could not read engine generation model from configuration. "
                "Judging cannot proceed because distinctness of judge and generation "
                "models cannot be verified."
            )
        judge_model = config.judge_model
        if judge_model and gen_model.strip() == judge_model.strip():
            raise ScoreError(
                f"Configured judge model '{judge_model}' equals engine generation "
                f"model '{gen_model}'. A judge cannot evaluate its own model family."
            )

        if stage_spend_cap is None:
            raise ScoreError(
                "Judged evaluation requires an explicit stage_spend_cap. "
                "Specify --stage-cap to bound provider spend."
            )

        api_key_val = api_key or os.environ.get("OPENROUTER_API_KEY", "")

        accumulated_judge_spend = 0.0
        cap_stopped = False
        verdicts_obtained = 0
        usage_absent_fallback_count = 0

        # Select judged question subset via derive_judged_slice_size
        distinct_qids = [
            {"question_id": q.question_id}
            for q in sampled_questions
            if any(r.question_id == q.question_id and _is_judgeable(r, gold_map) for r in p_records)
        ]
        judgeable_count = len(distinct_qids)
        skipped_no_evidence = sum(
            1
            for r in p_records
            if gold_map.get(r.question_id) and not r.structured_citations
        )
        cost_per_question = estimate_judge_cost_per_question(
            judge_max_tokens=config.judge_max_tokens
        )
        try:
            derived_slice_size, judged_slice_binding = derive_judged_slice_size(
                judgeable_count=judgeable_count,
                stage_spend_cap=stage_spend_cap,
                cost_per_question=cost_per_question,
                cached_verdict_count=cached_verdict_count,
            )
        except ValueError as exc:
            raise ScoreError(str(exc)) from exc

        if sample is not None and sample > derived_slice_size:
            if judged_slice_binding == "cap":
                raise ScoreError(
                    f"--sample {sample} exceeds the cap-derived bound of {derived_slice_size} "
                    f"(stage_spend_cap={stage_spend_cap}, estimated cost per question={cost_per_question:.4f}). "
                    f"Reduce --sample to <= {derived_slice_size} or increase --stage-cap."
                )
            sample_clamp_note = (
                f"--sample {sample} exceeded the judgeable population ({derived_slice_size}); "
                f"judged slice was clamped to {derived_slice_size}."
            )
            slice_count = derived_slice_size
        elif sample is not None and sample > 0:
            slice_count = sample
        else:
            slice_count = derived_slice_size

        judged_slice_committed = slice_count

        if slice_count < len(distinct_qids):
            sampled_q_dicts = sample_questions(
                distinct_qids, n=slice_count, seed=config.sample_seed
            )
            judged_qids = {d["question_id"] for d in sampled_q_dicts}
        else:
            judged_qids = {d["question_id"] for d in distinct_qids}

        for rec in p_records:
            if rec.question_id not in judged_qids:
                continue
            if not _is_judgeable(rec, gold_map):
                continue
            gold = gold_map[rec.question_id]

            judged_sample_count += 1

            ev = truncate_evidence(rec.structured_citations)
            k = cache_key(
                prompt_version=config.judge_prompt_version,
                judge_model=judge_model,
                question=gold.question,
                answer=rec.answer or "",
                post_truncation_evidence=ev,
            )

            cached_entry = cache.get(k)
            if cached_entry is not None:
                if cached_entry.verdict is not None:
                    groundedness_scores.append(cached_entry.verdict.groundedness)
                    faithfulness_scores.append(cached_entry.verdict.faithfulness)
                    verdicts_obtained += 1
                elif cached_entry.error is not None:
                    judge_errors += 1
            else:
                if stage_spend_cap is not None and accumulated_judge_spend >= stage_spend_cap:
                    cap_stopped = True
                    break

                verdict, err, usage = judge_once(
                    client=client,
                    api_key=api_key_val,
                    model=judge_model,
                    question=gold.question,
                    answer=rec.answer or "",
                    evidence=ev,
                    prompt_version=config.judge_prompt_version,
                    temperature=config.judge_temperature,
                    max_tokens=config.judge_max_tokens,
                )
                if usage is not None:
                    accumulated_judge_spend += compute_judge_spend(
                        usage.prompt_tokens, usage.completion_tokens
                    )
                else:
                    accumulated_judge_spend += cost_per_question
                    usage_absent_fallback_count += 1

                entry = JudgeCacheEntry(
                    cache_key=k,
                    prompt_version=config.judge_prompt_version,
                    judge_model=judge_model,
                    question=gold.question,
                    answer=rec.answer or "",
                    evidence=ev,
                    verdict=verdict,
                    error=err,
                )
                cache.set(k, entry)
                if verdict is not None:
                    groundedness_scores.append(verdict.groundedness)
                    faithfulness_scores.append(verdict.faithfulness)
                    verdicts_obtained += 1
                else:
                    judge_errors += 1

        if cap_stopped:
            if usage_absent_fallback_count > 0:
                judge_stop_note = (
                    f"Judged pass stopped by spend cap "
                    f"(${accumulated_judge_spend:.6f} spent >= ${stage_spend_cap:.6f} cap, "
                    f"including {usage_absent_fallback_count} call{'s' if usage_absent_fallback_count != 1 else ''} charged at estimated cost)."
                )
                cap_stop_discloses_fallback = True
            else:
                judge_stop_note = (
                    f"Judged pass stopped by spend cap "
                    f"(${accumulated_judge_spend:.6f} spent >= ${stage_spend_cap:.6f} cap)."
                )
            judged_slice_state_code = JUDGED_SLICE_STATE_CAP_STOPPED
        elif judged_slice_binding == "cap":
            judged_slice_state_code = JUDGED_SLICE_STATE_CAP_BOUND
        else:
            judged_slice_state_code = JUDGED_SLICE_STATE_COMPLETED

        judged_slice_state = JUDGED_SLICE_STATES[judged_slice_state_code]

    # Calibration evaluation
    g_calibration_em: float | None = None
    g_calibration_mad: float | None = None
    f_calibration_em: float | None = None
    f_calibration_mad: float | None = None

    g_calibration_kappa: float | None = None
    g_calibration_spearman: float | None = None
    g_calibration_kappa_state: float | None = None
    g_calibration_spearman_state: float | None = None
    g_calibration_state: float | None = None
    g_calibration_kappa_ci_lower: float | None = None
    g_calibration_kappa_ci_upper: float | None = None
    g_calibration_spearman_ci_lower: float | None = None
    g_calibration_spearman_ci_upper: float | None = None
    g_calibration_pairs_n: float | None = None
    g_calibration_excluded_n: float | None = None

    f_calibration_kappa: float | None = None
    f_calibration_spearman: float | None = None
    f_calibration_kappa_state: float | None = None
    f_calibration_spearman_state: float | None = None
    f_calibration_state: float | None = None
    f_calibration_kappa_ci_lower: float | None = None
    f_calibration_kappa_ci_upper: float | None = None
    f_calibration_spearman_ci_lower: float | None = None
    f_calibration_spearman_ci_upper: float | None = None
    f_calibration_pairs_n: float | None = None
    f_calibration_excluded_n: float | None = None

    completed_dual_scores: int = 0
    calibration_notes: str = ""

    if legacy_calibration_file is None:
        g_calibration_state = CALIBRATION_STATE_NONE
        f_calibration_state = CALIBRATION_STATE_NONE
        calibration_notes = (
            "No judge-versus-human calibration was performed; "
            "judged dimensions are uncalibrated."
        )
    else:
        calib_path = Path(legacy_calibration_file)
        if not calib_path.is_file():
            raise ScoreError(f"Calibration file not found at {calib_path}")

        g_matches: list[float] = []
        g_diffs: list[float] = []
        f_matches: list[float] = []
        f_diffs: list[float] = []

        g_human: list[int] = []
        g_judge: list[int] = []
        f_human: list[int] = []
        f_judge: list[int] = []
        g_excluded = 0
        f_excluded = 0

        with open(calib_path, encoding="utf-8") as f:
            for line_idx, line in enumerate(f, 1):
                clean_l = line.strip()
                if not clean_l:
                    continue
                row = json.loads(clean_l)
                if row.get("type") == "header":
                    hdr_ver = row.get("judge_prompt_version")
                    if hdr_ver != config.judge_prompt_version:
                        raise ScoreError(
                            f"Calibration prompt version '{hdr_ver}' does not match "
                            f"configured '{config.judge_prompt_version}'"
                        )
                    continue

                row_id = row.get("question_id") or f"line-{line_idx}"
                hg = row.get("human_groundedness")
                hf = row.get("human_faithfulness")

                hg_blank = hg is None or str(hg).strip() == ""
                hf_blank = hf is None or str(hf).strip() == ""
                if hg_blank or hf_blank:
                    raise ScoreError(
                        f"Row '{row_id}' in calibration worksheet has blank human score"
                    )

                try:
                    hg_val = int(hg)
                    hf_val = int(hf)
                except ValueError as e:
                    raise ScoreError(
                        f"Row '{row_id}' has invalid human score: {hg}, {hf}"
                    ) from e

                if not (1 <= hg_val <= 5 and 1 <= hf_val <= 5):
                    raise ScoreError(
                        f"Row '{row_id}' human score outside 1..5: {hg_val}, {hf_val}"
                    )

                completed_dual_scores += 1

                c_key = row.get("cache_key", "")
                cached = cache.get(c_key)
                if cached and cached.verdict:
                    g_matches.append(
                        1.0 if hg_val == cached.verdict.groundedness else 0.0
                    )
                    g_diffs.append(abs(hg_val - cached.verdict.groundedness))
                    f_matches.append(
                        1.0 if hf_val == cached.verdict.faithfulness else 0.0
                    )
                    f_diffs.append(abs(hf_val - cached.verdict.faithfulness))

                    g_human.append(hg_val)
                    g_judge.append(cached.verdict.groundedness)
                    f_human.append(hf_val)
                    f_judge.append(cached.verdict.faithfulness)
                else:
                    g_excluded += 1
                    f_excluded += 1

        if g_matches:
            g_calibration_em = sum(g_matches) / len(g_matches)
            g_calibration_mad = sum(g_diffs) / len(g_diffs)
            f_calibration_em = sum(f_matches) / len(f_matches)
            f_calibration_mad = sum(f_diffs) / len(f_diffs)

        g_calibration_pairs_n = float(len(g_human))
        g_calibration_excluded_n = float(g_excluded)
        if g_human:
            res_kappa = quadratic_weighted_kappa(
                g_human, g_judge, min_rating=1, max_rating=5
            )
            if res_kappa.value is not None:
                g_calibration_kappa = res_kappa.value
                g_calibration_kappa_state = KAPPA_STATE_COMPUTED
                ci_k = bootstrap_agreement_ci(
                    g_human,
                    g_judge,
                    "kappa",
                    min_rating=1,
                    max_rating=5,
                    seed=config.sample_seed,
                )
                if ci_k is not None:
                    g_calibration_kappa_ci_lower, g_calibration_kappa_ci_upper = ci_k
            else:
                g_calibration_kappa = None
                if res_kappa.state == "undefined_expected_agreement":
                    g_calibration_kappa_state = KAPPA_STATE_UNDEFINED_EXPECTED_AGREEMENT

            res_spearman = spearman_rank_correlation(g_human, g_judge)
            if res_spearman.value is not None:
                g_calibration_spearman = res_spearman.value
                g_calibration_spearman_state = SPEARMAN_STATE_COMPUTED
                ci_s = bootstrap_agreement_ci(
                    g_human,
                    g_judge,
                    "spearman",
                    seed=config.sample_seed,
                )
                if ci_s is not None:
                    g_calibration_spearman_ci_lower, g_calibration_spearman_ci_upper = (
                        ci_s
                    )
            else:
                g_calibration_spearman = None
                if res_spearman.state == "undefined_zero_variance":
                    g_calibration_spearman_state = (
                        SPEARMAN_STATE_UNDEFINED_ZERO_VARIANCE
                    )

        f_calibration_pairs_n = float(len(f_human))
        f_calibration_excluded_n = float(f_excluded)
        if f_human:
            res_kappa = quadratic_weighted_kappa(
                f_human, f_judge, min_rating=1, max_rating=5
            )
            if res_kappa.value is not None:
                f_calibration_kappa = res_kappa.value
                f_calibration_kappa_state = KAPPA_STATE_COMPUTED
                ci_k = bootstrap_agreement_ci(
                    f_human,
                    f_judge,
                    "kappa",
                    min_rating=1,
                    max_rating=5,
                    seed=config.sample_seed,
                )
                if ci_k is not None:
                    f_calibration_kappa_ci_lower, f_calibration_kappa_ci_upper = ci_k
            else:
                f_calibration_kappa = None
                if res_kappa.state == "undefined_expected_agreement":
                    f_calibration_kappa_state = KAPPA_STATE_UNDEFINED_EXPECTED_AGREEMENT

            res_spearman = spearman_rank_correlation(f_human, f_judge)
            if res_spearman.value is not None:
                f_calibration_spearman = res_spearman.value
                f_calibration_spearman_state = SPEARMAN_STATE_COMPUTED
                ci_s = bootstrap_agreement_ci(
                    f_human,
                    f_judge,
                    "spearman",
                    seed=config.sample_seed,
                )
                if ci_s is not None:
                    f_calibration_spearman_ci_lower, f_calibration_spearman_ci_upper = (
                        ci_s
                    )
            else:
                f_calibration_spearman = None
                if res_spearman.state == "undefined_zero_variance":
                    f_calibration_spearman_state = (
                        SPEARMAN_STATE_UNDEFINED_ZERO_VARIANCE
                    )

        if completed_dual_scores == 0:
            g_calibration_state = CALIBRATION_STATE_NONE
            f_calibration_state = CALIBRATION_STATE_NONE
            calibration_notes = (
                "No judge-versus-human calibration was performed; "
                "judged dimensions are uncalibrated."
            )
        else:
            g_kappa_satisfied = (
                g_calibration_kappa is not None
                and g_calibration_kappa >= AGREEMENT_TARGET
            )
            g_spearman_satisfied = (
                g_calibration_spearman is not None
                and g_calibration_spearman >= AGREEMENT_TARGET
            )
            f_kappa_satisfied = (
                f_calibration_kappa is not None
                and f_calibration_kappa >= AGREEMENT_TARGET
            )
            f_spearman_satisfied = (
                f_calibration_spearman is not None
                and f_calibration_spearman >= AGREEMENT_TARGET
            )

            g_calibration_state = (
                CALIBRATION_STATE_SATISFIED
                if (g_kappa_satisfied and g_spearman_satisfied)
                else CALIBRATION_STATE_BELOW_TARGET
            )
            f_calibration_state = (
                CALIBRATION_STATE_SATISFIED
                if (f_kappa_satisfied and f_spearman_satisfied)
                else CALIBRATION_STATE_BELOW_TARGET
            )

            shortfalls = []
            if not g_kappa_satisfied:
                val_repr = (
                    f"{g_calibration_kappa:.4f}"
                    if g_calibration_kappa is not None
                    else "undefined"
                )
                shortfalls.append(f"groundedness kappa={val_repr}")
            if not g_spearman_satisfied:
                val_repr = (
                    f"{g_calibration_spearman:.4f}"
                    if g_calibration_spearman is not None
                    else "undefined"
                )
                shortfalls.append(f"groundedness spearman={val_repr}")
            if not f_kappa_satisfied:
                val_repr = (
                    f"{f_calibration_kappa:.4f}"
                    if f_calibration_kappa is not None
                    else "undefined"
                )
                shortfalls.append(f"faithfulness kappa={val_repr}")
            if not f_spearman_satisfied:
                val_repr = (
                    f"{f_calibration_spearman:.4f}"
                    if f_calibration_spearman is not None
                    else "undefined"
                )
                shortfalls.append(f"faithfulness spearman={val_repr}")

            if shortfalls:
                prefix = (
                    f"Calibration agreement fell below target "
                    f"({AGREEMENT_TARGET:.2f}) for: "
                )
                calibration_notes = f"{prefix}{', '.join(shortfalls)}."
            else:
                calibration_notes = ""

    if judged:
        completed_dual_scores = len(verified.pairs)
        calibration_notes = (
            "Ordered judged protocol (D-113, D-120): the D-114 labels and the "
            f"selection-effect text are in {JUDGED_RESULT_FILE}."
        )

    # Emit calibration worksheet if requested
    if emit_calibration_worksheet is not None:
        # CR-01: Refuse to emit worksheet without judging enabled
        if no_judge:
            raise ScoreError(
                "Cannot emit calibration worksheet (--emit-calibration-worksheet) "
                "when judging is disabled (--no-judge). Generating a valid "
                "calibration worksheet requires cache-verified verdicts from "
                "the judge model. Re-run with judging enabled (--judge) to "
                "produce a valid calibration worksheet."
            )
        out_ws_path = Path(emit_calibration_worksheet)
        out_ws_path.parent.mkdir(parents=True, exist_ok=True)

        worksheet_rows: list[dict[str, Any]] = [
            {
                "type": "header",
                "corpus": corpus_name,
                "judge_prompt_version": config.judge_prompt_version,
                "judge_model": config.judge_model,
                "generated_at": datetime.now(UTC).isoformat(),
            }
        ]

        # Select up to 20 representative items across query types
        selected_records = []
        if judged_qids:
            for r in p_records:
                if r.question_id not in judged_qids:
                    continue
                if not _is_judgeable(r, gold_map):
                    continue
                gold = gold_map[r.question_id]
                ev = truncate_evidence(r.structured_citations)
                k = cache_key(
                    prompt_version=config.judge_prompt_version,
                    judge_model=config.judge_model,
                    question=gold.question,
                    answer=r.answer or "",
                    post_truncation_evidence=ev,
                )
                entry = cache.get(k)
                if entry is not None and entry.verdict is not None:
                    selected_records.append(r)
                if len(selected_records) == 20:
                    break

        for r in selected_records:
            gold = gold_map.get(r.question_id)
            if not gold:
                continue
            ev = (
                truncate_evidence(r.structured_citations)
                if r.structured_citations
                else ""
            )
            k = cache_key(
                prompt_version=config.judge_prompt_version,
                judge_model=config.judge_model,
                question=gold.question,
                answer=r.answer or "",
                post_truncation_evidence=ev,
            )
            worksheet_rows.append({
                "question_id": r.question_id,
                "query_type": gold.question_type,
                "cache_key": k,
                "question": gold.question,
                "answer": r.answer or "",
                "evidence": ev,
                "human_groundedness": None,
                "human_faithfulness": None,
                "notes": "",
            })

        with open(out_ws_path, "w", encoding="utf-8", newline="\n") as f:
            for w_row in worksheet_rows:
                f.write(json.dumps(w_row, ensure_ascii=False) + "\n")

        count_emitted = len(worksheet_rows) - 1
        print(f"Emitted {count_emitted} calibration worksheet rows to {out_ws_path}")

    dimensions: list[DimensionResult] = []

    # 0. Integrity & path health dimensions
    dimensions.append(
        make_unusable_record_rate(
            records=records, collapsed_records_n=collapsed_records_n
        )
    )

    usable_primary_records = p_data.get("usable_records", [])

    # Extract RetrieveHybrid durations once from usable primary records
    retrieve_latencies: list[float] = []
    for r in usable_primary_records:
        for nt in r.node_timings:
            if nt.node_name == "RetrieveHybrid":
                retrieve_latencies.append(nt.duration_ms)
                break

    dimensions.append(
        make_vector_yield(
            records=usable_primary_records,
            retrieve_latencies=retrieve_latencies,
        )
    )
    dimensions.append(
        make_bm25_yield(
            records=usable_primary_records,
            retrieve_latencies=retrieve_latencies,
        )
    )
    dimensions.append(make_retrieve_latency_ms(records=usable_primary_records))
    dimensions.append(make_graph_presence_rate(records=usable_primary_records))
    dimensions.append(make_graph_influence_rate(records=usable_primary_records))
    dimensions.append(make_graph_latency_ms(records=usable_primary_records))

    # Helper for building mean score dimension

    def _build_mean_dim(
        name: str,
        values: list[float],
        errors: int,
        total: int,
        extra_detail: dict[str, float] | None = None,
    ) -> DimensionResult:
        merged_detail = dict(extra_detail) if extra_detail else {}
        if not values:
            if errors == total and total > 0:
                return DimensionResult(
                    name=name,
                    status="error",
                    reason=f"All {total} records failed execution with errors",
                    detail=merged_detail,
                    n=0,
                )
            return DimensionResult(
                name=name,
                status="skipped",
                reason="No valid records available to compute metric",
                detail=merged_detail,
                n=0,
            )
        mean_val = sum(values) / len(values)
        ok_detail = {
            "errors": float(errors),
            "sample_size": float(len(values)),
        }
        if extra_detail:
            ok_detail.update(extra_detail)
        return DimensionResult(
            name=name,
            status="ok",
            score=mean_val,
            detail=ok_detail,
            n=len(values),
        )

    answerable_payload_detail = {
        "excluded_payload_records": float(p_data.get("payload_excluded_answerable", 0))
    }

    # 1. retrieval_evidence_coverage
    dimensions.append(
        _build_mean_dim(
            "retrieval_evidence_coverage",
            p_data["recalls"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 2. context_precision_at_k
    dimensions.append(
        _build_mean_dim(
            "context_precision_at_k",
            p_data["precisions"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 3. ranking_quality (MRR@10)
    dimensions.append(
        _build_mean_dim(
            "ranking_quality",
            p_data["mrrs"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 4. answer_exact_match
    dimensions.append(
        _build_mean_dim(
            "answer_exact_match",
            p_data["ems"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 5. answer_f1
    dimensions.append(
        _build_mean_dim(
            "answer_f1",
            p_data["f1s"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 5a. final_answer_em (D-70): EM on the extracted `Answer:` line
    dimensions.append(
        _build_mean_dim(
            "final_answer_em",
            p_data["final_answer_ems"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 5b. final_answer_containment (D-70): whole-token gold containment on the
    # full answer text (secondary/context metric, not gated)
    dimensions.append(
        _build_mean_dim(
            "final_answer_containment",
            p_data["final_answer_containments"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 5c. answer_usable (D-70): final_answer_em OR gold_contained(extracted
    # line) -- the SC-3 headline metric, judged on the extracted line only
    dimensions.append(
        _build_mean_dim(
            "answer_usable",
            p_data["answer_usables"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 5d. final_answer_missing_rate (D-70/D-74): rate of non-null records with
    # no extractable `Answer:` line; these records stay in every denominator
    # above (D-34) rather than being excluded
    dimensions.append(
        _build_mean_dim(
            "final_answer_missing_rate",
            p_data["final_answer_missings"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 6. answer_faithfulness
    if no_judge:
        dimensions.append(
            DimensionResult(
                name="answer_faithfulness",
                status="skipped",
                reason="Deferred to LLM-as-judge scoring pass (--no-judge specified)",
                detail={
                    "judged_slice_committed": float(judged_slice_committed),
                    "verdicts_obtained": float(verdicts_obtained),
                    "judged_slice_state": float(judged_slice_state_code),
                    "usage_absent_fallback_count": 0.0,
                },
                n=0,
            )
        )
    else:
        dimensions.append(
            make_faithfulness_result(
                verdicts=faithfulness_scores,
                judge_errors=judge_errors,
                skipped_no_evidence=skipped_no_evidence,
                total_sampled=skipped_no_evidence + judged_sample_count,
                calibration_exact_match=f_calibration_em,
                calibration_mad=f_calibration_mad,
                calibration_kappa=f_calibration_kappa,
                calibration_spearman=f_calibration_spearman,
                calibration_kappa_state=f_calibration_kappa_state,
                calibration_spearman_state=f_calibration_spearman_state,
                calibration_state=f_calibration_state,
                calibration_kappa_ci_lower=f_calibration_kappa_ci_lower,
                calibration_kappa_ci_upper=f_calibration_kappa_ci_upper,
                calibration_spearman_ci_lower=f_calibration_spearman_ci_lower,
                calibration_spearman_ci_upper=f_calibration_spearman_ci_upper,
                calibration_pairs_n=f_calibration_pairs_n,
                calibration_excluded_n=f_calibration_excluded_n,
                judged_slice_committed=judged_slice_committed,
                verdicts_obtained=verdicts_obtained,
                judged_slice_state=judged_slice_state_code,
                usage_absent_fallback_count=usage_absent_fallback_count,
            )
        )

    # 7. answer_groundedness
    if no_judge:
        dimensions.append(
            DimensionResult(
                name="answer_groundedness",
                status="skipped",
                reason="Deferred to LLM-as-judge scoring pass (--no-judge specified)",
                detail={
                    "judged_slice_committed": float(judged_slice_committed),
                    "verdicts_obtained": float(verdicts_obtained),
                    "judged_slice_state": float(judged_slice_state_code),
                    "usage_absent_fallback_count": 0.0,
                },
                n=0,
            )
        )
    else:
        dimensions.append(
            make_groundedness_result(
                verdicts=groundedness_scores,
                judge_errors=judge_errors,
                skipped_no_evidence=skipped_no_evidence,
                total_sampled=skipped_no_evidence + judged_sample_count,
                calibration_exact_match=g_calibration_em,
                calibration_mad=g_calibration_mad,
                calibration_kappa=g_calibration_kappa,
                calibration_spearman=g_calibration_spearman,
                calibration_kappa_state=g_calibration_kappa_state,
                calibration_spearman_state=g_calibration_spearman_state,
                calibration_state=g_calibration_state,
                calibration_kappa_ci_lower=g_calibration_kappa_ci_lower,
                calibration_kappa_ci_upper=g_calibration_kappa_ci_upper,
                calibration_spearman_ci_lower=g_calibration_spearman_ci_lower,
                calibration_spearman_ci_upper=g_calibration_spearman_ci_upper,
                calibration_pairs_n=g_calibration_pairs_n,
                calibration_excluded_n=g_calibration_excluded_n,
                judged_slice_committed=judged_slice_committed,
                verdicts_obtained=verdicts_obtained,
                judged_slice_state=judged_slice_state_code,
                usage_absent_fallback_count=usage_absent_fallback_count,
            )
        )

    # 8. graph_ablation_delta (redefined paired difference of evidence coverage)
    # Form pairs once from deduplicated records
    join_res = form_arm_pairs(
        records, gold_map, treatment_arm="hybrid+graph", reference_arm="hybrid"
    )
    pairs = join_res.pairs

    # Distinct questions attempted in this journal across both arms
    coverage_denom = join_res.total_distinct_questions
    answerable_n = sum(1 for q in sampled_questions if not q.is_null)

    # 8a. Evidence coverage (primary ablation delta)
    def _score_evidence_coverage(rec: RunRecord, gold: Any) -> float | None:
        if not has_scorable_payload(rec):
            return None
        out = recall_at_k(
            gold, rec.snapshot.retrieved_chunks, k=4, chunk_size=config.chunk_size
        )
        return out.score if out.status == "ok" else None

    res_coverage = compute_paired_delta(
        pairs,
        _score_evidence_coverage,
        coverage_denominator=coverage_denom,
        answerable_count=answerable_n,
        join_result=join_res,
    )
    dimensions.append(
        make_paired_ablation_delta(
            name="graph_ablation_delta",
            paired_result=res_coverage,
        )
    )

    # 8b. Exact Match delta
    def _score_em(rec: RunRecord, gold: Any) -> float | None:
        if not has_scorable_payload(rec) or gold.is_null:
            return None
        out = squad_em(gold, rec.answer)
        return out.score if out.status == "ok" else None

    res_em = compute_paired_delta(
        pairs,
        _score_em,
        coverage_denominator=coverage_denom,
        answerable_count=answerable_n,
    )
    dimensions.append(
        make_paired_ablation_delta(
            name="graph_ablation_delta_exact_match",
            paired_result=res_em,
        )
    )

    # 8c. F1 delta
    def _score_f1(rec: RunRecord, gold: Any) -> float | None:
        if not has_scorable_payload(rec) or gold.is_null:
            return None
        out = squad_f1(gold, rec.answer)
        return out.score if out.status == "ok" else None

    res_f1 = compute_paired_delta(
        pairs,
        _score_f1,
        coverage_denominator=coverage_denom,
        answerable_count=answerable_n,
    )
    dimensions.append(
        make_paired_ablation_delta(
            name="graph_ablation_delta_f1",
            paired_result=res_f1,
        )
    )

    # 8d. Context Precision delta
    def _score_cp(rec: RunRecord, gold: Any) -> float | None:
        if not has_scorable_payload(rec):
            return None
        out = context_precision_at_k(gold, rec.snapshot.retrieved_chunks, k=4)
        return out.score if out.status == "ok" else None

    res_cp = compute_paired_delta(
        pairs,
        _score_cp,
        coverage_denominator=coverage_denom,
        answerable_count=answerable_n,
    )
    dimensions.append(
        make_paired_ablation_delta(
            name="graph_ablation_delta_context_precision",
            paired_result=res_cp,
        )
    )

    # 8e. Ranking Quality (MRR@10) delta
    def _score_mrr(rec: RunRecord, gold: Any) -> float | None:
        if not has_scorable_payload(rec):
            return None
        out = mrr_at_k(gold, rec.snapshot.retrieved_chunks, k=10)
        return out.score if out.status == "ok" else None

    res_mrr = compute_paired_delta(
        pairs,
        _score_mrr,
        coverage_denominator=coverage_denom,
        answerable_count=answerable_n,
    )
    dimensions.append(
        make_paired_ablation_delta(
            name="graph_ablation_delta_ranking_quality",
            paired_result=res_mrr,
        )
    )

    # 8f. Latency delta (duration_ms)
    def _score_latency(rec: RunRecord, gold: Any) -> float | None:
        return float(rec.duration_ms)

    res_lat = compute_paired_delta(
        pairs,
        _score_latency,
        coverage_denominator=coverage_denom,
        answerable_count=answerable_n,
    )
    dimensions.append(
        make_paired_ablation_delta(
            name="graph_ablation_latency_delta",
            paired_result=res_lat,
        )
    )

    # 8g. Prompt token delta
    has_any_tokens = any(
        (
            p.graph_on.workflow_meta is not None
            and p.graph_on.workflow_meta.prompt_tokens > 0
        )
        or (
            p.graph_off.workflow_meta is not None
            and p.graph_off.workflow_meta.prompt_tokens > 0
        )
        for p in pairs
    )
    if pairs and not has_any_tokens:
        dimensions.append(
            DimensionResult(
                name="graph_ablation_prompt_token_delta",
                status="skipped",
                reason="No records in join carry workflow_meta.prompt_tokens",
                detail={
                    "n_pairs": float(len(pairs)),
                    "pairing_coverage": float(len(pairs) / coverage_denom)
                    if coverage_denom > 0
                    else 0.0,
                },
                n=0,
            )
        )
    else:

        def _score_tokens(rec: RunRecord, gold: Any) -> float | None:
            if rec.workflow_meta is None:
                return None
            return float(rec.workflow_meta.prompt_tokens)

        res_tokens = compute_paired_delta(
            pairs,
            _score_tokens,
            coverage_denominator=coverage_denom,
            answerable_count=answerable_n,
        )
        dimensions.append(
            make_paired_ablation_delta(
                name="graph_ablation_prompt_token_delta",
                paired_result=res_tokens,
            )
        )

    # 9. abstention_on_unanswerable
    unanswerable_payload_excluded = float(
        p_data.get("payload_excluded_unanswerable", 0)
    )
    if p_data["abstentions"]:
        abs_mean = sum(p_data["abstentions"]) / len(p_data["abstentions"])
        dimensions.append(
            DimensionResult(
                name="abstention_on_unanswerable",
                status="ok",
                score=abs_mean,
                detail={
                    "null_samples": float(len(p_data["abstentions"])),
                    "excluded_payload_records": unanswerable_payload_excluded,
                },
                n=len(p_data["abstentions"]),
            )
        )
    else:
        if unanswerable_payload_excluded > 0:
            skip_reason = (
                "All unanswerable-question records lacked scorable payload "
                "(excluded by the payload rule); none were scored"
            )
        else:
            skip_reason = "Corpus contains no unanswerable questions"
        dimensions.append(
            DimensionResult(
                name="abstention_on_unanswerable",
                status="skipped",
                reason=skip_reason,
                detail={
                    "excluded_payload_records": unanswerable_payload_excluded,
                },
                n=0,
            )
        )

    # 9a. null_abstention_correctness (D-72): scored on null_query records
    # only; never enters answer_usable's denominator (see the answerable-only
    # guard around answer_usables above)
    if p_data["null_abstention_corrects"]:
        nac_mean = sum(p_data["null_abstention_corrects"]) / len(
            p_data["null_abstention_corrects"]
        )
        dimensions.append(
            DimensionResult(
                name="null_abstention_correctness",
                status="ok",
                score=nac_mean,
                detail={
                    "null_samples": float(len(p_data["null_abstention_corrects"])),
                    "excluded_payload_records": unanswerable_payload_excluded,
                },
                n=len(p_data["null_abstention_corrects"]),
            )
        )
    else:
        if unanswerable_payload_excluded > 0:
            nac_skip_reason = (
                "All unanswerable-question records lacked scorable payload "
                "(excluded by the payload rule); none were scored"
            )
        else:
            nac_skip_reason = "Corpus contains no unanswerable questions"
        dimensions.append(
            DimensionResult(
                name="null_abstention_correctness",
                status="skipped",
                reason=nac_skip_reason,
                detail={
                    "excluded_payload_records": unanswerable_payload_excluded,
                },
                n=0,
            )
        )

    # 10. wire_contract_conformance
    dimensions.append(make_wire_contract_conformance(records=records))

    # 11. community_summary_quality (placeholder)
    dimensions.append(OBS_04_PLACEHOLDER)

    # 12. run_traceability
    total_recs = len(records)
    traced_count = sum(
        1 for r in records if r.session_id and r.correlation_id and r.index_generation
    )
    traceability_rate = (traced_count / total_recs) if total_recs > 0 else 0.0

    dimensions.append(
        DimensionResult(
            name="run_traceability",
            status="ok",
            score=traceability_rate,
            detail={
                "traced_records": float(traced_count),
                "total_records": float(total_recs),
            },
            n=total_recs,
        )
    )

    judged_result: JudgedResult | None = None
    if split_inputs is not None:
        four_arm = _four_arm_dimensions(
            records=records,
            config=config,
            inputs=split_inputs,
            gold_map=gold_map,
            arm_metrics=arm_metrics,
            provenance_counts=provenance_counts,
        )
        dimensions.extend(four_arm)
        if judged and judged_cache is not None:
            judged_dims, judged_result = _judged_dimensions(
                records=records,
                config=config,
                inputs=split_inputs,
                gold_map=gold_map,
                cache=judged_cache,
                verified=verified,
                four_arm=four_arm,
            )
            dimensions.extend(judged_dims)

    res_hash = compute_result_hash(dimensions)
    lock_hash = get_lock_hash()
    index_gen = sorted(distinct_gens)[0] if distinct_gens else "unknown-gen"
    gen_model_name = _get_engine_generation_model() or "unknown-generation-model"

    # Find embedding model from first available snapshot or fallback
    emb_model = "unknown-embedding-model"
    for r in records:
        if r.snapshot and getattr(r.snapshot, "embedding_model", None):
            if r.snapshot.embedding_model and r.snapshot.embedding_model.strip():
                emb_model = r.snapshot.embedding_model
                break

    record_corpora = {r.corpus for r in records if r.corpus}
    records_corpus = next(iter(record_corpora)) if len(record_corpora) == 1 else None
    corpus_disagreement = (
        records_corpus is None
        or (header_corpus is not None and header_corpus != records_corpus)
    )

    effective_partial = True
    missing_units_note: str | None = None

    if header_partial is False and not corpus_disagreement and records_corpus is not None:
        is_complete, missing = completeness_comparison(journal_path, records_corpus)
        if is_complete:
            effective_partial = False
        else:
            effective_partial = True
            missing_units_note = (
                f"Completeness comparison contradicted publishable header: "
                f"missing {len(missing)} work unit{'s' if len(missing) != 1 else ''}."
            )

    fallback_note: str | None = None
    if usage_absent_fallback_count > 0 and not cap_stop_discloses_fallback:
        fallback_note = (
            f"Provider omitted usage for {usage_absent_fallback_count} judged call{'s' if usage_absent_fallback_count != 1 else ''}; "
            f"spend was charged at estimated cost per question."
        )

    final_notes = calibration_notes
    if judge_stop_note:
        final_notes = (
            f"{final_notes} {judge_stop_note}".strip()
            if final_notes
            else judge_stop_note
        )
    if sample_clamp_note:
        final_notes = (
            f"{final_notes} {sample_clamp_note}".strip()
            if final_notes
            else sample_clamp_note
        )
    if fallback_note:
        final_notes = (
            f"{final_notes} {fallback_note}".strip()
            if final_notes
            else fallback_note
        )
    if missing_units_note:
        final_notes = (
            f"{final_notes} {missing_units_note}".strip()
            if final_notes
            else missing_units_note
        )

    metadata = RunMetadata(
        corpus=corpus_name,
        run_date=datetime.now(UTC).isoformat(),
        commit_sha=os.environ.get("GIT_COMMIT_SHA") or get_commit_sha(),
        generation_model=gen_model_name,
        embedding_model=emb_model,
        judge_model=config.judge_model,
        judge_temperature=config.judge_temperature,
        judge_prompt_version=config.judge_prompt_version,
        sampling_seed=config.sample_seed,
        sample_size_deterministic=len(sampled_questions),
        sample_size_judged=judged_sample_count,
        calibration_completed_n=completed_dual_scores,
        index_generation=index_gen,
        result_hash=res_hash,
        arm_labels=config.arms,
        dependency_lock_hash=lock_hash,
        partial=effective_partial,
        notes=final_notes,
        judged_slice_committed=judged_slice_committed,
        verdicts_obtained=verdicts_obtained,
        judged_slice_state=judged_slice_state,
    )

    report = CorpusReport(
        corpus=corpus_name,
        metadata=metadata,
        dimensions=dimensions,
    )

    # Write report.json to run_dir if not partial
    if not effective_partial:
        if judged_result is not None:
            with open(
                dir_path / JUDGED_RESULT_FILE, "w", encoding="utf-8", newline="\n"
            ) as f:
                f.write(judged_result.model_dump_json(indent=2) + "\n")
            for text in judged_result.report_lines:
                print(text)
        report_json_path = dir_path / "report.json"
        with open(report_json_path, "w", encoding="utf-8") as f:
            f.write(render_json(report))

    return report
