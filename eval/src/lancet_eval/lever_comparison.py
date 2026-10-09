"""The no-judge lever comparison of a scored 06.3.6 run (plan 06.3.6-10).

`lancet-eval compare-levers --run <dir>` reads a run directory that
`score --no-judge` has already scored and writes `lever-comparison.json` and
`lever-comparison.md`. It decides nothing by itself: every family, arm set, floor,
guard margin and default rule is read from the pre-registration the corpus token names
(`preregistration.resolve`), never imported by name (D-73, D-158).

What it computes (06.3.6 AI-SPEC section 5):

* two Holm families, one per primary (D-150): `answer_usable` (decisional) and
  `paper_hits_at_4` (supporting, never makes a default), each comparison X against the
  reference on its own pairwise population P_X (D-160, D-161), the D-123 exact two-sided
  paired sign-flip test, Holm step-down at the family alpha with m fixed at the
  registered arm count; a comparison below the coverage floor enters as p = 1 and m does
  not change;
* guard 1, the null-abstention paired drop on N_X (D-148, D-162, D-163), and guard 2,
  the answer-mix disclosure (reported only);
* the D-140 descriptive rows and the P_dec and rerank intention-to-treat sensitivity
  lines, which decide nothing;
* one `default_decision` row per lever (D-150, O16).

No judge runs here and no judged result exists in this phase (D-153): this module never
opens one. Bootstrap CIs and Wilson intervals are estimation only and are labelled so.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from fractions import Fraction
from math import comb
from pathlib import Path
from statistics import fmean
from typing import Any

from lancet_eval import gitcheck, preregistration, provenance
from lancet_eval import p4 as p4_mod
from lancet_eval.arms import canonical_arm, resolve_arm
from lancet_eval.corpus import GoldQuestion, load_corpus_config, load_sample_questions
from lancet_eval.journal import RunRecord, load_records, read_journal_header
from lancet_eval.metrics import (
    answer_usable,
    extract_final_answer,
    final_answer_em,
    gold_contained,
    id_matcher,
    is_abstention,
    load_gold_chunk_sets,
    paper_question_scores,
    recall_at_k,
)
from lancet_eval.pairing import deduplicate_by_arm
from lancet_eval.report import CorpusReport
from lancet_eval.score import _default_gold_chunks_path, _record_spend_usd
from lancet_eval.split import HeldOutSplit, load_split
from lancet_eval.stats import exact_signflip_p, holm_stepdown, percentile
from lancet_eval.strata import STRATUM_TYPES
from lancet_eval.thresholds import (
    COMMITTED_THRESHOLDS,
    FINAL_ANSWER_MISSING_REVIEW_RATE,
)
from lancet_eval.usability import (
    carries_rerank_degraded,
    has_rerank_telemetry,
    is_usable,
)

SCHEMA_VERSION = 1
OUTPUT_FILES: tuple[str, ...] = ("lever-comparison.json", "lever-comparison.md")
GATES_FILE = "gates-heldout.json"

LABEL_UNADJUSTED = "unadjusted, estimation only"
LABEL_DESCRIPTIVE = "descriptive, decides nothing"
LABEL_SENSITIVITY = "sensitivity line, decides nothing"
LABEL_ALL_ARM = "all-arm P_all, not the decisional population"
DECISION_SIGNIFICANT = "significant"
DECISION_NOT_SIGNIFICANT = "not significant"
DECISION_NOT_EVALUABLE = "not evaluable: coverage"
CI_EXCLUDES_ZERO_NOTE = "CI excludes 0; not significant after Holm"
NI_NOT_DEMONSTRABLE = "non-inferiority not demonstrable at this n"

DEFAULT = "default"
WORSE = "significantly worse, stays off"
OFF_NOT_SIGNIFICANT = "stays off: not significant"
OFF_NOT_EVALUABLE = "stays off: not evaluable: coverage"
OFF_NO_POSITIVE_DELTA = "stays off: no positive delta"
OFF_PROVENANCE = "stays off: provenance block not passed"
OFF_GUARD_NOT_EVALUABLE = "stays off: guard not evaluable"
OFF_GUARD_FAILED = "stays off: null guard failed"
OFF_GATES_NOT_READ = "stays off: gates not read"
OWNER_DISPOSITION = (
    "owner disposition: SC-1/SC-2 not PASS (disclosed, never mechanical)"
)

FWER_STATEMENT = (
    "Two Holm families, one per primary, each at its family-wise error rate (m "
    "fixed at "
    "the registered arm count). Across both families the family-wise error rate can "
    "reach 0.10 (the Bonferroni bound over two families), and this report states it. "
    "Defaults read only the decisional family (at most 0.05). The guards can only veto "
    "a rejection, so they never raise the error rate."
)
INTERACTION_CAVEAT = (
    "If two levers win, D-157 flips both. The combination is never tested "
    "decisionally; hybrid+all is its only, descriptive, evidence."
)
CROSS_FAMILY_NOTE = (
    "Bootstrap CIs are 95% percentile intervals, labelled 'unadjusted, estimation "
    "only'. A CI that excludes 0 without a Holm rejection is not significant."
)

_ANSWER_STATES = ("correct", "abstain", "wrong")
_BINARY_GOLD = ("yes", "no")


class LeverComparisonError(Exception):
    """Raised when the comparison cannot be built; the command exits 1."""


# ---- pure statistics -----------------------------------------------------------------


def coverage_floor_met(n_pairs: int, n_g: int, floor: float) -> bool:
    """Whether `|P_X| / |H_G|` reaches the pre-registered floor, as an exact fraction.

    A coverage of exactly the floor is evaluable. The floor is always passed in: it is
    the pre-registered value, never a module default.

    Args:
        n_pairs: The size of the comparison's pairwise population.
        n_g: The held-out G size, the coverage denominator.
        floor: The pre-registered floor.

    Returns:
        False for an empty population or an empty split.
    """
    if n_g <= 0 or n_pairs <= 0:
        return False
    return Fraction(n_pairs, n_g) >= Fraction(str(floor))


def holm_fixed_m(
    raw_ps: Sequence[float], evaluable: Sequence[bool], alpha: float
) -> tuple[list[bool], list[float]]:
    """Holm step-down with m fixed at the family's registered size (D-160, D-150).

    A comparison that is not evaluable enters as p = 1 and is never rejected; m is the
    number of registered comparisons, whatever the coverage turned out to be.

    Args:
        raw_ps: The family's raw p-values in registered order.
        evaluable: Per comparison, whether its coverage floor was met.
        alpha: The family-wise error rate.

    Returns:
        `(reject, adjusted)` in the input order.
    """
    if len(raw_ps) != len(evaluable):
        raise ValueError("raw_ps and evaluable differ in length")
    ps = [p if ok else 1.0 for p, ok in zip(raw_ps, evaluable, strict=True)]
    reject, adjusted = holm_stepdown(ps, alpha=alpha)
    return (
        [r and ok for r, ok in zip(reject, evaluable, strict=True)],
        adjusted,
    )


def sign_flip(
    values_x: Mapping[str, float], values_ref: Mapping[str, float]
) -> tuple[int, int, float]:
    """The discordant counts and the exact two-sided sign-flip p (1 when n_d = 0)."""
    n_pos, n_neg = p4_mod.discordant_counts(values_x, values_ref)
    return n_pos, n_neg, float(exact_signflip_p(n_pos, n_neg))


def _binom_cdf(k: int, n: int, p: float) -> float:
    return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))


def _cp_upper(b: int, d: int, alpha: float = 0.05) -> float:
    """One-sided (1 - alpha) Clopper-Pearson upper bound on p, b successes of d."""
    if d <= 0 or b >= d:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if _binom_cdf(b, d, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def net_loss_upper_bound(b: int, c: int, n_pairs: int) -> float:
    """The one-sided 95% upper bound on the net-loss rate `(b - c) / n_pairs`.

    Conditional on `d = b + c` discordant pairs, `b ~ Binomial(d, theta)`; the bound is
    `d * (2 * theta_upper - 1) / n_pairs` with a Clopper-Pearson `theta_upper`
    (stdlib arithmetic, no scipy). It is printed beside the count rule and never
    decides: formal non-inferiority fails a harmless lever from about d = 6 at n = 43.

    Args:
        b: Pairs where the reference abstains and the arm does not.
        c: The reverse.
        n_pairs: The pair count the rate is over.

    Returns:
        The bound as a rate; 0.0 when there is no discordant pair.
    """
    d = b + c
    if d == 0 or n_pairs <= 0:
        return 0.0
    return d * (2 * _cp_upper(b, d) - 1) / n_pairs


@dataclass(frozen=True)
class NullGuard:
    """Guard 1 of one arm (D-148, D-162, D-163)."""

    arm: str
    predicate: str
    decisional: bool
    n_heldout_null: int
    n_pairs: int
    min_pairs: int
    b: int
    c: int
    net_loss_rate: float
    margin: float
    evaluable: bool
    passes: bool
    status: str
    upper_bound_95: float
    ni_label: str | None
    note: str


def evaluate_null_guard(
    b: int,
    c: int,
    n_pairs: int,
    n_heldout_null: int,
    *,
    margin: float,
    min_pair_fraction: float,
    arm: str = "",
    predicate: str = "metrics.is_abstention",
    decisional: bool = True,
) -> NullGuard:
    """Guard 1: PASS iff `|N_X| >= ceil(min_pair_fraction x |H_N|)` and the net loss is
    at most the margin, both exact (equality passes; fewer pairs fail closed, O5).

    Args:
        b: Pairs where the reference abstains and the arm does not.
        c: The reverse.
        n_pairs: `|N_X|`.
        n_heldout_null: The held-out null count (43), the floor's base.
        margin: The pre-registered margin (0.10).
        min_pair_fraction: The pre-registered pair fraction (0.80).
        arm: The compared arm.
        predicate: The abstention predicate's name.
        decisional: Whether the guard vetoes (O4 arms) or only reads.

    Returns:
        The guard reading with the one-sided 95% net-loss bound beside it.
    """
    min_pairs = math.ceil(Fraction(str(min_pair_fraction)) * n_heldout_null)
    evaluable = n_pairs >= min_pairs and n_pairs > 0
    rate = Fraction(b - c, n_pairs) if n_pairs > 0 else Fraction(0)
    passes = evaluable and rate <= Fraction(str(margin))
    bound = net_loss_upper_bound(b, c, n_pairs)
    if not evaluable:
        status = "NOT EVALUABLE (fails closed)"
        note = (
            f"{n_pairs} null pairs, fewer than the {min_pairs} needed "
            f"(ceil({min_pair_fraction} x {n_heldout_null}))"
        )
    elif passes:
        status = "PASS"
        note = f"net loss {b - c} of {n_pairs}, at most the margin {margin}"
    else:
        status = "FAIL"
        note = f"net loss {b - c} of {n_pairs}, above the margin {margin}"
    if not decisional:
        status = f"would {'pass' if passes else 'fail'}" + (
            "" if evaluable else " (not evaluable)"
        )
    return NullGuard(
        arm=arm,
        predicate=predicate,
        decisional=decisional,
        n_heldout_null=n_heldout_null,
        n_pairs=n_pairs,
        min_pairs=min_pairs,
        b=b,
        c=c,
        net_loss_rate=float(rate),
        margin=margin,
        evaluable=evaluable,
        passes=passes,
        status=status,
        upper_bound_95=bound,
        ni_label=NI_NOT_DEMONSTRABLE if evaluable and bound > margin else None,
        note=note,
    )


def all_gold_at_4(
    ranking_ids: Sequence[str], gold_sets: Sequence[frozenset[str]]
) -> bool:
    """Whether every gold set has a chunk within rank 4 of the D-100 ranking (ID rule).

    Descriptive only, and not a paper metric: the paper's Hits@4 needs any one gold
    chunk. A gold unit that matches nothing (a fact split across chunks) never hits.
    """
    if not gold_sets:
        return False
    top = set(ranking_ids[:4])
    return all(bool(unit & top) for unit in gold_sets)


def answer_state(record: RunRecord, gold: GoldQuestion) -> str:
    """`correct`, `abstain` or `wrong` for one G record (correct wins over abstain)."""
    if answer_usable(gold, record.answer or ""):
        return "correct"
    return "abstain" if is_abstention(record) else "wrong"


def transition_counts(pairs: Sequence[tuple[str, str]]) -> dict[str, int]:
    """The transition table of `(reference_state, arm_state)` pairs.

    `answer_to_abstain` is the reference answering (correct or wrong) and the arm
    abstaining, so it includes `correct_to_abstain`. The first four rows reconcile with
    the paired delta exactly: `n x delta = (abstain_to_correct + wrong_to_correct) -
    (correct_to_wrong + correct_to_abstain)`.
    """
    table = Counter(pairs)
    return {
        "abstain_to_correct": table[("abstain", "correct")],
        "wrong_to_correct": table[("wrong", "correct")],
        "correct_to_wrong": table[("correct", "wrong")],
        "correct_to_abstain": table[("correct", "abstain")],
        "answer_to_abstain": table[("correct", "abstain")]
        + table[("wrong", "abstain")],
        "other_transitions": sum(
            n
            for (h, x), n in table.items()
            if h != x
            and (h, x)
            not in {
                ("abstain", "correct"),
                ("wrong", "correct"),
                ("correct", "wrong"),
                ("correct", "abstain"),
            }
        ),
        "unchanged": sum(n for (h, x), n in table.items() if h == x),
        "n": len(pairs),
    }


def decide_default(
    *,
    in_decisional_family: bool,
    evaluable: bool,
    rejected: bool,
    delta: float | None,
    guard: NullGuard | None,
    provenance_passed: bool,
    gate_reads: Mapping[str, str | None] | None,
) -> tuple[str, list[str]]:
    """One lever's default reading, applying the pre-registered rule (D-150, O16).

    A lever becomes a default only on a Holm rejection in the decisional family with a
    positive delta, coverage at the floor, the post-drive provenance block passed, its
    guard (when bound) evaluable and passing, and SC-1 and SC-2 PASS on the reference
    and on the lever. A rejection with a negative delta is significantly worse. When
    only the gate condition fails the default is an owner disposition, never mechanical.

    Args:
        in_decisional_family: Whether the lever's comparison is in the decisional
            family.
        evaluable: Whether its coverage floor was met.
        rejected: Whether Holm rejected it.
        delta: The paired delta on P_X (None when the population is empty).
        guard: Its null guard when the lever is bound to one, else None.
        provenance_passed: Whether the post-drive provenance block passed.
        gate_reads: `{"<arm> SC-1": status, ...}` for the reference and the lever, or
            None when the gate file was not read.

    Returns:
        `(decision, reasons)`; the reasons list every condition that did not hold.
    """
    reasons: list[str] = []
    if not in_decisional_family:
        return "stays off: not in the decisional family", [
            "not in the decisional family"
        ]
    if not evaluable:
        return OFF_NOT_EVALUABLE, ["coverage below the pre-registered floor"]
    if not rejected:
        return OFF_NOT_SIGNIFICANT, ["no Holm rejection"]
    if delta is None or delta < 0:
        return WORSE, ["Holm rejection with a negative delta"]
    if delta == 0:
        return OFF_NO_POSITIVE_DELTA, ["delta is not positive"]
    if not provenance_passed:
        reasons.append("post-drive provenance block not passed")
        return OFF_PROVENANCE, reasons
    if guard is not None:
        if not guard.evaluable:
            return OFF_GUARD_NOT_EVALUABLE, [guard.note]
        if not guard.passes:
            return OFF_GUARD_FAILED, [guard.note]
    if gate_reads is None:
        return OFF_GATES_NOT_READ, ["gates-heldout.json was not read"]
    failing = sorted(k for k, v in gate_reads.items() if v != "PASS")
    if failing:
        return OWNER_DISPOSITION, [f"{k} reads {gate_reads[k]}" for k in failing]
    return DEFAULT, []


# ---- loading -------------------------------------------------------------------------


def _journal_path(run: Path) -> Path:
    journal = run / "journal.jsonl"
    if not journal.is_file():
        journal = run / "journal.json"
    if not journal.is_file():
        raise LeverComparisonError(f"no journal file in {run}")
    return journal


def _require_preregistered(
    journal: Path, token: str, git_repo: Path | None
) -> dict[str, Any]:
    """D-73: the pre-registration token's commit must be older than the data.

    It needs no judged result (D-153). Returns the journal header.
    """
    header = read_journal_header(journal)
    created_at = None if header is None else header.get("created_at")
    if isinstance(created_at, bool) or not isinstance(created_at, int | float):
        raise LeverComparisonError(
            "D-73: the journal header must carry a numeric created_at to prove the "
            f"pre-registration predates the data (got {created_at!r})"
        )
    problems = gitcheck.preregistration_problems(
        (token,),
        created_at=float(created_at),
        require_clean_tree=True,
        unchanged_since_introduction=True,
        repo=git_repo,
    )
    if problems:
        raise LeverComparisonError(
            "D-73: refusing to compare: "
            + "; ".join(problems)
            + f". {token} must be committed before the data exists."
        )
    assert header is not None
    return header


def load_gates(run: Path) -> dict[str, Any] | None:
    """The run's `gates-heldout.json`, or None when it is absent or unreadable."""
    path = run / GATES_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _gate_status(gates: Mapping[str, Any], gate: str, arm: str) -> str | None:
    block = gates.get(gate)
    if not isinstance(block, dict):
        return None
    reading = block.get(arm)
    if not isinstance(reading, dict):
        return None
    status = reading.get("status")
    return str(status) if status is not None else None


def _load_report(run: Path) -> CorpusReport:
    path = run / "report.json"
    if not path.is_file():
        raise LeverComparisonError(
            f"{path} is missing; run `lancet-eval score --no-judge` first (D-153)"
        )
    try:
        return CorpusReport.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise LeverComparisonError(f"report.json does not validate: {exc}") from exc


# ---- the build context ---------------------------------------------------------------


@dataclass
class _Ctx:
    """Everything the builders share; read-only after construction."""

    records: list[RunRecord]
    by_key: dict[tuple[str, str], RunRecord]
    split: HeldOutSplit
    gold_map: dict[str, GoldQuestion]
    gold_sets: dict[str, list[frozenset[str]]]
    qtype_of: dict[str, str]
    prereg: Any
    reference: str
    b: int
    seed: int
    chunk_size: int
    pops: dict[tuple[str, bool], p4_mod.P4Population]

    @property
    def g_ids(self) -> list[str]:
        return list(self.split.heldout_g_ids)

    @property
    def n_g(self) -> int:
        return len(self.split.heldout_g_ids)

    @property
    def n_null(self) -> int:
        return len(self.split.heldout_null_ids)

    def rec(self, qid: str, arm: str) -> RunRecord:
        try:
            return self.by_key[(qid, canonical_arm(arm))]
        except KeyError as exc:
            raise LeverComparisonError(f"no {arm!r} record for {qid!r}") from exc

    def pop(self, arm: str, *, null: bool = False) -> p4_mod.P4Population:
        """The pairwise population of `arm` against the reference (P_X or N_X)."""
        key = (canonical_arm(arm), null)
        if key not in self.pops:
            self.pops[key] = _pairwise(
                self.records, self.split, self.reference, arm, null=null
            )
        return self.pops[key]

    def delta(
        self, vx: Mapping[str, float], vref: Mapping[str, float]
    ) -> p4_mod.PairedDelta | None:
        if not vx:
            return None
        return p4_mod.paired_delta(vx, vref, b=self.b, seed=self.seed)


def _pairwise(
    records: Sequence[RunRecord],
    split: HeldOutSplit,
    reference: str,
    arm: str,
    *,
    null: bool = False,
    ok: Callable[[RunRecord], bool] = provenance.is_ok,
) -> p4_mod.P4Population:
    scoped = (
        split.model_copy(update={"heldout_g_ids": list(split.heldout_null_ids)})
        if null
        else split
    )
    try:
        return p4_mod.build_p4(
            records, scoped, (reference, arm), reference_arm=reference, ok=ok
        )
    except ValueError as exc:
        raise LeverComparisonError(
            f"cannot build the population of {arm}: {exc}"
        ) from exc


def _ranking_ids(rec: RunRecord) -> list[str]:
    if rec.snapshot is None:
        return []
    return [c.chunk_id for c in rec.snapshot.pre_truncation_ranking]


def _values(
    ctx: _Ctx,
    pop: p4_mod.P4Population,
    arm: str,
    fn: Callable[[RunRecord], float | None],
) -> dict[str, float]:
    """Per-question values of one arm over a population; None values are dropped."""
    out: dict[str, float] = {}
    for qid in pop.question_ids:
        value = fn(ctx.rec(qid, arm))
        if value is not None:
            out[qid] = float(value)
    return out


def _paired(
    ctx: _Ctx,
    pop: p4_mod.P4Population,
    arm: str,
    fn: Callable[[RunRecord], float | None],
    *,
    reference: str | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    """Values of `arm` and the reference over the questions both can score."""
    ref = reference or ctx.reference
    vx = _values(ctx, pop, arm, fn)
    vr = _values(ctx, pop, ref, fn)
    keys = sorted(set(vx) & set(vr))
    return {k: vx[k] for k in keys}, {k: vr[k] for k in keys}


def _usable_value(ctx: _Ctx) -> Callable[[RunRecord], float | None]:
    return lambda r: (
        1.0 if answer_usable(ctx.gold_map[r.question_id], r.answer or "") else 0.0
    )


def _hit4_value(ctx: _Ctx) -> Callable[[RunRecord], float | None]:
    return lambda r: float(
        paper_question_scores(
            _ranking_ids(r), ctx.gold_sets[r.question_id], id_matcher
        )["hit4"]
    )


def _primary_fn(ctx: _Ctx, primary: str) -> Callable[[RunRecord], float | None]:
    if primary == "answer_usable":
        return _usable_value(ctx)
    if primary == "paper_hits_at_4":
        return _hit4_value(ctx)
    raise LeverComparisonError(f"unknown primary {primary!r} in the pre-registration")


def _mean(values: Mapping[str, float]) -> float | None:
    return float(fmean(values.values())) if values else None


def _stratum_rows(
    ctx: _Ctx, vx: Mapping[str, float], vr: Mapping[str, float]
) -> list[dict[str, Any]]:
    """D-40 per-type paired deltas: a secondary, no p-value, no CI below the cell."""
    rows: list[dict[str, Any]] = []
    cell = COMMITTED_THRESHOLDS.min_stratum_cell_size
    for qtype in STRATUM_TYPES:
        ids = sorted(q for q in vx if ctx.qtype_of.get(q) == qtype)
        row: dict[str, Any] = {"stratum": qtype, "n": len(ids)}
        if ids:
            x = {q: vx[q] for q in ids}
            r = {q: vr[q] for q in ids}
            row["delta"] = float(fmean(x.values()) - fmean(r.values()))
            if len(ids) >= cell:
                pd = p4_mod.paired_delta(x, r, b=ctx.b, seed=ctx.seed)
                row["ci_lo"], row["ci_hi"] = pd.ci_lower, pd.ci_upper
        rows.append(row)
    return rows


# ---- the families --------------------------------------------------------------------


def _exclusions(ctx: _Ctx, arm: str, pop: p4_mod.P4Population) -> dict[str, int]:
    """Why G questions are outside P_X, by reason (AI-SPEC 5 item 7)."""
    own = pop.excluded[canonical_arm(arm)]
    ref = pop.excluded[canonical_arm(ctx.reference)]
    degraded = 0
    for qid in ctx.g_ids:
        rec = ctx.by_key.get((qid, canonical_arm(arm)))
        if rec is not None and is_usable(rec) and carries_rerank_degraded(rec):
            degraded += 1
    return {
        "own_failure": own.own_failure,
        "own_provenance": own.provenance,
        "rerank_degrade": degraded,
        "reference_failure": ref.own_failure + own.other_arm_failure,
        "reference_provenance": ref.provenance,
    }


def _comparison_rows(ctx: _Ctx, family: Any, *, floor: float) -> list[dict[str, Any]]:
    fn = _primary_fn(ctx, family.primary)
    rows: list[dict[str, Any]] = []
    raw: list[float] = []
    evaluable: list[bool] = []
    for arm in family.arms:
        pop = ctx.pop(arm)
        vx, vr = _paired(ctx, pop, arm, fn)
        ok = coverage_floor_met(len(pop.question_ids), ctx.n_g, floor)
        n_pos = n_neg = None
        p = 1.0
        if ok and vx:
            n_pos, n_neg, p = sign_flip(vx, vr)
        pd = ctx.delta(vx, vr) if ok else None
        raw.append(p)
        evaluable.append(ok and bool(vx))
        rows.append({
            "arm": arm,
            "reference": ctx.reference,
            "n_pairs": len(pop.question_ids),
            "coverage": len(pop.question_ids) / ctx.n_g if ctx.n_g else 0.0,
            "evaluable": ok and bool(vx),
            "n_pos": n_pos,
            "n_neg": n_neg,
            "raw_p": p if ok else None,
            "mean_arm": _mean(vx),
            "mean_reference": _mean(vr),
            "delta": None if pd is None else pd.delta,
            "ci_lo": None if pd is None else pd.ci_lower,
            "ci_hi": None if pd is None else pd.ci_upper,
            "ci_label": LABEL_UNADJUSTED,
            "exclusions": _exclusions(ctx, arm, pop),
            "strata": _stratum_rows(ctx, vx, vr) if ok else [],
        })
    reject, adjusted = holm_fixed_m(raw, evaluable, family.alpha)
    for row, rej, adj, ok in zip(rows, reject, adjusted, evaluable, strict=True):
        row["adjusted_p"] = adj if ok else None
        row["rejected"] = rej
        row["decision"] = (
            DECISION_NOT_EVALUABLE
            if not ok
            else DECISION_SIGNIFICANT
            if rej
            else DECISION_NOT_SIGNIFICANT
        )
        excludes = (
            row["ci_lo"] is not None
            and row["ci_hi"] is not None
            and (row["ci_lo"] > 0 or row["ci_hi"] < 0)
        )
        row["ci_note"] = CI_EXCLUDES_ZERO_NOTE if excludes and not rej else None
    return rows


def _family_block(ctx: _Ctx, family: Any) -> dict[str, Any]:
    floor = float(ctx.prereg.complete_case_floor)
    return {
        "primary": family.primary,
        "role": family.role,
        "alpha": family.alpha,
        "m": len(family.arms),
        "matching_rule": ctx.prereg.matching_rule
        if family.primary == "paper_hits_at_4"
        else None,
        "comparisons": _comparison_rows(ctx, family, floor=floor),
    }


# ---- guards --------------------------------------------------------------------------


def _null_guards(ctx: _Ctx, arms: Sequence[str]) -> list[NullGuard]:
    guards: list[NullGuard] = []
    prereg = ctx.prereg
    for arm in arms:
        pop = ctx.pop(arm, null=True)
        b = c = 0
        for qid in pop.question_ids:
            h = is_abstention(ctx.rec(qid, ctx.reference))
            x = is_abstention(ctx.rec(qid, arm))
            if h and not x:
                b += 1
            elif x and not h:
                c += 1
        guards.append(
            evaluate_null_guard(
                b,
                c,
                len(pop.question_ids),
                ctx.n_null,
                margin=float(prereg.null_guard_margin),
                min_pair_fraction=float(prereg.null_guard_min_pair_fraction),
                arm=arm,
                predicate=str(prereg.null_guard_predicate),
                decisional=arm in prereg.null_guard_arms,
            )
        )
    return guards


def _final_line(rec: RunRecord) -> str:
    if is_abstention(rec):
        return "insufficient_information"
    extracted = extract_final_answer(rec.answer)
    if extracted == "yes":
        return "yes"
    if extracted == "no":
        return "no"
    return "other"


def _shares(labels: Sequence[str]) -> dict[str, float]:
    n = len(labels)
    keys = ("yes", "no", "insufficient_information", "other")
    count = Counter(labels)
    return {k: (count[k] / n if n else 0.0) for k in keys}


def _gold_label(gold: GoldQuestion) -> str:
    text = gold.gold_answer.strip().lower()
    return text if text in _BINARY_GOLD else "other"


def _mix_block(ctx: _Ctx, arm: str, ids: Sequence[str], name: str) -> dict[str, Any]:
    gold_labels = [_gold_label(ctx.gold_map[q]) for q in ids]
    n = len(ids)
    yes = sum(1 for g in gold_labels if g == "yes")
    no = sum(1 for g in gold_labels if g == "no")
    return {
        "subset": name,
        "n": n,
        "arm": _shares([_final_line(ctx.rec(q, arm)) for q in ids]),
        "reference": _shares([_final_line(ctx.rec(q, ctx.reference)) for q in ids]),
        "gold": {
            "yes": yes / n if n else 0.0,
            "no": no / n if n else 0.0,
            "other": (n - yes - no) / n if n else 0.0,
        },
        "constant_yes_answer_usable": yes / n if n else None,
        "constant_no_answer_usable": no / n if n else None,
    }


def _answer_mix(ctx: _Ctx, arm: str) -> dict[str, Any]:
    pop = ctx.pop(arm)
    ids = list(pop.question_ids)
    comparison = [q for q in ids if ctx.qtype_of.get(q) == "comparison_query"]
    binary = [q for q in ids if _gold_label(ctx.gold_map[q]) in _BINARY_GOLD]
    nonbinary = [q for q in ids if q not in set(binary)]
    usable = _usable_value(ctx)
    vx = {q: float(usable(ctx.rec(q, arm)) or 0.0) for q in nonbinary}
    vr = {q: float(usable(ctx.rec(q, ctx.reference)) or 0.0) for q in nonbinary}
    pd = ctx.delta(vx, vr)
    states = {
        q: (
            answer_state(ctx.rec(q, ctx.reference), ctx.gold_map[q]),
            answer_state(ctx.rec(q, arm), ctx.gold_map[q]),
        )
        for q in ids
    }
    by_stratum = {
        t: transition_counts([states[q] for q in ids if ctx.qtype_of.get(q) == t])
        for t in STRATUM_TYPES
    }
    return {
        "arm": arm,
        "label": "reported only, never decisional; beating constant-Yes is not a "
        "default condition",
        "mix": [
            _mix_block(ctx, arm, comparison, "comparison_query"),
            _mix_block(ctx, arm, binary, "binary_gold"),
        ],
        "transitions": {"all": transition_counts(list(states.values())), **by_stratum},
        "non_binary_gold": {
            "n": len(nonbinary),
            "mean_arm": _mean(vx),
            "mean_reference": _mean(vr),
            "delta": None if pd is None else pd.delta,
            "ci_lo": None if pd is None else pd.ci_lower,
            "ci_hi": None if pd is None else pd.ci_upper,
            "ci_label": LABEL_UNADJUSTED,
        },
    }


# ---- descriptive rows and sensitivity lines ------------------------------------------


def _descriptive_row(ctx: _Ctx, arm: str, against: str, label: str) -> dict[str, Any]:
    pop = _pairwise(ctx.records, ctx.split, against, arm, ok=provenance.is_ok)
    out: dict[str, Any] = {
        "row": f"{arm} - {against}",
        "label": label,
        "n_pairs": len(pop.question_ids),
    }
    for primary in ("answer_usable", "paper_hits_at_4"):
        fn = _primary_fn(ctx, primary)
        vx = _values(ctx, pop, arm, fn)
        vr = _values(ctx, pop, against, fn)
        pd = ctx.delta(vx, vr)
        n_pos, n_neg = p4_mod.discordant_counts(vx, vr) if vx else (0, 0)
        out[primary] = {
            "mean_arm": _mean(vx),
            "mean_reference": _mean(vr),
            "delta": None if pd is None else pd.delta,
            "ci_lo": None if pd is None else pd.ci_lower,
            "ci_hi": None if pd is None else pd.ci_upper,
            "ci_label": LABEL_UNADJUSTED,
            "n_pos": n_pos,
            "n_neg": n_neg,
        }
    return out


def _descriptive_rows(ctx: _Ctx) -> list[dict[str, Any]]:
    arms = set(preregistration.arms_of(ctx.prereg))
    rows: list[dict[str, Any]] = []
    plan = (
        ("hybrid+graph", ctx.reference),
        ("hybrid+graph-v2", "hybrid+graph"),
        ("hybrid+all", ctx.reference),
    )
    for arm, against in plan:
        if arm in arms and against in arms:
            rows.append(_descriptive_row(ctx, arm, against, LABEL_DESCRIPTIVE))
    return rows


def _graph_state(ctx: _Ctx) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for arm in preregistration.arms_of(ctx.prereg):
        if resolve_arm(arm).disable_graph_context:
            continue
        recs = [r for (_, a), r in ctx.by_key.items() if a == canonical_arm(arm)]
        capped = [
            r.workflow_meta.graph_degree_capped_count
            for r in recs
            if r.workflow_meta is not None
            and r.workflow_meta.graph_degree_capped_count is not None
        ]
        out.append({
            "arm": arm,
            "records": len(recs),
            "degree_capped_count": int(sum(capped)),
            "records_with_degree_capped_field": len(capped),
        })
    return out


def _decisional_family(prereg: Any) -> Any:
    for family in prereg.families:
        if family.role == "decisional":
            return family
    raise LeverComparisonError("the pre-registration has no decisional family")


def _p_dec_line(ctx: _Ctx) -> dict[str, Any]:
    """The decisional family re-read on P_dec: ok on the reference and every lever."""
    family = _decisional_family(ctx.prereg)
    try:
        pop = p4_mod.build_p4(
            ctx.records,
            ctx.split,
            (ctx.reference, *family.arms),
            reference_arm=ctx.reference,
        )
    except ValueError as exc:
        raise LeverComparisonError(f"cannot build P_dec: {exc}") from exc
    floor = float(ctx.prereg.complete_case_floor)
    ok = coverage_floor_met(len(pop.question_ids), ctx.n_g, floor)
    fn = _primary_fn(ctx, family.primary)
    raw: list[float] = []
    rows: list[dict[str, Any]] = []
    for arm in family.arms:
        vx, vr = _paired(ctx, pop, arm, fn)
        n_pos, n_neg, p = sign_flip(vx, vr) if (ok and vx) else (None, None, 1.0)
        pd = ctx.delta(vx, vr) if ok else None
        raw.append(p)
        rows.append({
            "arm": arm,
            "n_pairs": len(vx),
            "n_pos": n_pos,
            "n_neg": n_neg,
            "raw_p": p if ok else None,
            "delta": None if pd is None else pd.delta,
        })
    reject, adjusted = holm_fixed_m(raw, [ok] * len(raw), family.alpha)
    for row, rej, adj in zip(rows, reject, adjusted, strict=True):
        row["adjusted_p"] = adj if ok else None
        row["decision"] = (
            DECISION_NOT_EVALUABLE
            if not ok
            else DECISION_SIGNIFICANT
            if rej
            else DECISION_NOT_SIGNIFICANT
        )
    return {
        "label": LABEL_SENSITIVITY,
        "population": "P_dec: ok on the reference and on every decisional lever arm",
        "n_pdec": len(pop.question_ids),
        "coverage": len(pop.question_ids) / ctx.n_g if ctx.n_g else 0.0,
        "evaluable": ok,
        "comparisons": rows,
    }


_ITT_OK_CODES = frozenset("abcdefhj")


def _itt_ok(rec: RunRecord) -> bool:
    """Usable and clean in every clause but (i): a degraded rerank record stays in."""
    return is_usable(rec) and not any(
        f.code in _ITT_OK_CODES for f in provenance.provenance_failures(rec)
    )


def _rerank_itt_line(ctx: _Ctx) -> dict[str, Any] | None:
    """Rerank only: a degraded record counts as the arm with its fused-order outcome."""
    family = _decisional_family(ctx.prereg)
    arm = "hybrid+rerank"
    if arm not in family.arms:
        return None
    pop = _pairwise(ctx.records, ctx.split, ctx.reference, arm, ok=_itt_ok)
    fn = _primary_fn(ctx, family.primary)
    vx, vr = _paired(ctx, pop, arm, fn)
    floor = float(ctx.prereg.complete_case_floor)
    ok = coverage_floor_met(len(pop.question_ids), ctx.n_g, floor) and bool(vx)
    n_pos, n_neg, p = sign_flip(vx, vr) if ok else (None, None, 1.0)
    main = {c["arm"]: c for c in _comparison_rows(ctx, family, floor=floor)}
    raw = [p if a == arm else (main[a]["raw_p"] or 1.0) for a in family.arms]
    evaluable = [ok if a == arm else bool(main[a]["evaluable"]) for a in family.arms]
    reject, adjusted = holm_fixed_m(raw, evaluable, family.alpha)
    i = list(family.arms).index(arm)
    pd = ctx.delta(vx, vr) if ok else None
    return {
        "label": LABEL_SENSITIVITY,
        "arm": arm,
        "population": "intention to treat: degraded rerank records kept with their "
        "fused-order outcome",
        "n_pairs": len(vx),
        "evaluable": ok,
        "n_pos": n_pos,
        "n_neg": n_neg,
        "raw_p": p if ok else None,
        "adjusted_p": adjusted[i] if ok else None,
        "decision": DECISION_NOT_EVALUABLE
        if not ok
        else DECISION_SIGNIFICANT
        if reject[i]
        else DECISION_NOT_SIGNIFICANT,
        "delta": None if pd is None else pd.delta,
        "ci_lo": None if pd is None else pd.ci_lower,
        "ci_hi": None if pd is None else pd.ci_upper,
        "ci_label": LABEL_UNADJUSTED,
    }


# ---- secondaries and operation tables ------------------------------------------------


def _secondary_fns(ctx: _Ctx) -> dict[str, Callable[[RunRecord], float | None]]:
    def paper(key: str) -> Callable[[RunRecord], float | None]:
        def fn(r: RunRecord) -> float | None:
            return float(
                paper_question_scores(
                    _ranking_ids(r), ctx.gold_sets[r.question_id], id_matcher
                )[key]
            )

        return fn

    def gold(r: RunRecord) -> GoldQuestion:
        return ctx.gold_map[r.question_id]

    def recall4(r: RunRecord) -> float | None:
        if r.snapshot is None:
            return None
        out = recall_at_k(
            gold(r), r.snapshot.retrieved_chunks, k=4, chunk_size=ctx.chunk_size
        )
        return (
            float(out.score) if out.status == "ok" and out.score is not None else None
        )

    def retrieve_ms(r: RunRecord) -> float | None:
        for nt in r.node_timings:
            if nt.node_name == "RetrieveHybrid":
                return float(nt.duration_ms)
        return None

    return {
        "paper_hits_at_10": paper("hit10"),
        "paper_mrr_at_10": paper("rr"),
        "paper_map_at_10": paper("ap"),
        "coverage_at_4": recall4,
        "all_gold_at_4": lambda r: float(
            all_gold_at_4(_ranking_ids(r), ctx.gold_sets[r.question_id])
        ),
        "final_answer_em": lambda r: float(
            final_answer_em(gold(r), r.answer or "").score or 0.0
        ),
        "gold_containment": lambda r: float(
            gold_contained(gold(r).gold_answer, r.answer or "")
        ),
        "final_answer_missing_rate": lambda r: (
            1.0 if extract_final_answer(r.answer) is None else 0.0
        ),
        "abstention_rate_g": lambda r: 1.0 if is_abstention(r) else 0.0,
        "prompt_tokens_mean": lambda r: float(
            r.workflow_meta.prompt_tokens if r.workflow_meta else 0
        ),
        "latency_total_ms_mean": lambda r: float(r.duration_ms),
        "retrieve_node_ms_mean": retrieve_ms,
        "spend_usd_mean": _record_spend_usd,
    }


def _secondaries(ctx: _Ctx, arms: Sequence[str]) -> list[dict[str, Any]]:
    """Dimensions 7 to 12 secondaries on P_X: a paired delta and CI, never a p-value."""
    rows: list[dict[str, Any]] = []
    fns = _secondary_fns(ctx)
    for arm in arms:
        pop = ctx.pop(arm)
        for metric, fn in fns.items():
            vx, vr = _paired(ctx, pop, arm, fn)
            pd = ctx.delta(vx, vr)
            row: dict[str, Any] = {
                "metric": metric,
                "arm": arm,
                "n_pairs": len(vx),
                "n_unscorable": len(pop.question_ids) - len(vx),
                "mean_arm": _mean(vx),
                "mean_reference": _mean(vr),
                "delta": None if pd is None else pd.delta,
                "ci_lo": None if pd is None else pd.ci_lower,
                "ci_hi": None if pd is None else pd.ci_upper,
                "label": LABEL_UNADJUSTED,
            }
            if metric == "final_answer_missing_rate" and pd is not None:
                row["parser_parity_review"] = (
                    abs(pd.delta) > FINAL_ANSWER_MISSING_REVIEW_RATE
                )
            rows.append(row)
    return rows


def _degrade_class(rec: RunRecord) -> str | None:
    meta = rec.workflow_meta.rerank if rec.workflow_meta else None
    outcome = (meta.outcome if meta else "").lower()
    if outcome.startswith("degraded_"):
        return outcome.removeprefix("degraded_")
    if carries_rerank_degraded(rec):
        return "unknown"
    return None


def _operation_tables(ctx: _Ctx) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Per-arm rerank operation (dimension 11) and per-arm provenance counts."""
    rerank_rows: list[dict[str, Any]] = []
    prov_rows: list[dict[str, Any]] = []
    for arm in preregistration.arms_of(ctx.prereg):
        label = canonical_arm(arm)
        recs = [r for (_, a), r in ctx.by_key.items() if a == label]
        codes = Counter(f.code for r in recs for f in provenance.provenance_failures(r))
        prov_rows.append({
            "arm": arm,
            "records": len(recs),
            "clause_h_failures": codes["h"],
            "clause_j_failures": codes["j"],
            "clause_i_degraded": codes["i"],
            "query_embedding_retries": sum(
                r.workflow_meta.query_embedding_retries
                for r in recs
                if r.workflow_meta is not None
            ),
        })
        if "rerank" not in resolve_arm(arm).levers:
            continue
        classes = Counter(c for r in recs if (c := _degrade_class(r)) is not None)
        attempts = [
            r for r in recs if has_rerank_telemetry(r) or carries_rerank_degraded(r)
        ]
        latencies = [
            float(r.workflow_meta.rerank.latency_ms)
            for r in recs
            if r.workflow_meta is not None and r.workflow_meta.rerank is not None
        ]
        calls = [
            r.workflow_meta.rerank
            for r in recs
            if r.workflow_meta is not None and r.workflow_meta.rerank is not None
        ]
        degrades = sum(classes.values())
        rerank_rows.append({
            "arm": arm,
            "records": len(recs),
            "attempts": len(attempts),
            "degrades": degrades,
            "degrade_rate": degrades / len(attempts) if attempts else None,
            "degrades_by_class": {
                k: classes[k]
                for k in ("timeout", "status", "malformed", "transport", "unknown")
            },
            "latency_ms_p50": percentile(latencies, 0.5) if latencies else None,
            "latency_ms_p95": percentile(latencies, 0.95) if latencies else None,
            "latency_ms_max": max(latencies) if latencies else None,
            "cost_credits_reported_sum": float(
                sum(m.cost_credits for m in calls if m.cost_reported)
            ),
            "calls_without_reported_cost": sum(1 for m in calls if not m.cost_reported),
        })
    return rerank_rows, prov_rows


# ---- assembly ------------------------------------------------------------------------


def _provenance_passed(report: CorpusReport) -> bool:
    for dim in report.dimensions:
        if dim.name == "arm_provenance_conformance":
            return (
                dim.status == "ok"
                and dim.detail.get("records_failing_zero_tolerance", 1.0) == 0.0
            )
    return False


def _load_inputs(
    run: Path,
    config: Any,
    gold_chunks_path: Path | str | None,
) -> tuple[list[RunRecord], HeldOutSplit, dict[str, GoldQuestion], dict[str, Any]]:
    records, _ = deduplicate_by_arm(load_records(_journal_path(run)))
    if config.split_path is None:
        raise LeverComparisonError(
            f"corpus {config.name!r} declares no [split]; the populations need one"
        )
    try:
        split = load_split(config.split_path)
        gold_map = {q.question_id: q for q in load_sample_questions(config.name)}
    except Exception as exc:
        raise LeverComparisonError(
            f"cannot load corpus {config.name!r} inputs: {exc}"
        ) from exc
    gold_path = (
        Path(gold_chunks_path)
        if gold_chunks_path is not None
        else _default_gold_chunks_path()
    )
    if not gold_path.is_file():
        raise LeverComparisonError(f"gold-chunk table not found at {gold_path} (D-102)")
    try:
        gold_sets = load_gold_chunk_sets(gold_path)
    except (OSError, ValueError, KeyError) as exc:
        raise LeverComparisonError(f"cannot read the gold-chunk table: {exc}") from exc
    problems = []
    for qid in split.heldout_g_ids:
        gold = gold_map.get(qid)
        if gold is None or gold.is_null:
            problems.append(f"{qid}: not a held-out G question of the corpus")
        elif gold.question_type not in STRATUM_TYPES:
            problems.append(f"{qid}: question_type {gold.question_type!r}")
        elif not gold_sets.get(qid):
            problems.append(f"{qid}: no gold-chunk row")
    for qid in split.heldout_null_ids:
        if qid not in gold_map:
            problems.append(f"{qid}: held-out null question missing from the corpus")
    if problems:
        raise LeverComparisonError(
            f"{len(problems)} held-out question(s) cannot be scored: "
            + "; ".join(problems[:10])
        )
    return records, split, gold_map, gold_sets


def build_lever_comparison(
    run_dir: Path | str,
    *,
    config: Any = None,
    prereg: Any = None,
    gates: Mapping[str, Any] | None = None,
    gold_chunks_path: Path | str | None = None,
    git_repo: Path | None = None,
) -> dict[str, Any]:
    """Builds the lever comparison of a scored run directory, in memory.

    The D-73 gate runs first (the pre-registration token's commit older than the journal
    header's `created_at`, a clean source tree, the pre-registered value unchanged), so
    no library caller can skip it, and it needs no judged result (D-153). Nothing is
    written.

    Args:
        run_dir: A run directory that `score --no-judge` has scored.
        config: The corpus config; loaded from the journal header when None.
        prereg: The pre-registration object; resolved from the corpus token when None.
        gates: The `gates-heldout.json` content; read from the run directory when None.
        gold_chunks_path: The gold-chunk table; the committed post-reconcile table when
            None.
        git_repo: Repository the D-73 check queries; the live repository when None.

    Returns:
        A JSON-serialisable payload.

    Raises:
        LeverComparisonError: If the D-73 ordering does not hold, the pre-registration
            is not a lever pre-registration, or an input is missing or inconsistent.
    """
    run = Path(run_dir)
    journal = _journal_path(run)
    header = read_journal_header(journal)
    corpus = header.get("corpus") if header else None
    if config is None:
        if not isinstance(corpus, str) or not corpus:
            raise LeverComparisonError("the journal header names no corpus")
        try:
            config = load_corpus_config(corpus)
        except Exception as exc:
            raise LeverComparisonError(f"cannot load corpus {corpus!r}: {exc}") from exc
    token = config.preregistration_token
    _require_preregistered(journal, token, git_repo)
    if prereg is None:
        try:
            prereg = preregistration.resolve(token)
        except preregistration.PreregistrationError as exc:
            raise LeverComparisonError(str(exc)) from exc
    if not hasattr(prereg, "families"):
        raise LeverComparisonError(
            f"{token} is not a lever pre-registration (no families): a corpus left on "
            "the 06.3.5 token cannot be compared with compare-levers"
        )
    arm_set = {canonical_arm(a) for a in config.arms}
    if arm_set != set(preregistration.arms_of(prereg)):
        raise LeverComparisonError(
            f"corpus {config.name!r} runs arms {sorted(arm_set)}, not the "
            f"pre-registered {sorted(preregistration.arms_of(prereg))}"
        )
    report = _load_report(run)
    records, split, gold_map, gold_sets = _load_inputs(run, config, gold_chunks_path)
    if gates is None:
        gates = load_gates(run)
    ctx = _Ctx(
        records=records,
        by_key={(r.question_id, canonical_arm(r.graph_arm)): r for r in records},
        split=split,
        gold_map=gold_map,
        gold_sets=gold_sets,
        qtype_of={q: str(gold_map[q].question_type) for q in split.heldout_g_ids},
        prereg=prereg,
        reference=prereg.reference_arm,
        b=int(prereg.bootstrap_b),
        seed=int(prereg.bootstrap_seed),
        chunk_size=int(config.chunk_size),
        pops={},
    )

    families = [_family_block(ctx, f) for f in prereg.families]
    decisional = _decisional_family(prereg)
    lever_arms = list(dict.fromkeys(a for f in prereg.families for a in f.arms))
    guards = _null_guards(ctx, lever_arms)
    guard_of = {g.arm: g for g in guards}
    decisional_rows = {
        c["arm"]: c
        for f in families
        if f["role"] == "decisional"
        for c in f["comparisons"]
    }
    supporting_rows = {
        c["arm"]: c
        for f in families
        if f["role"] == "supporting"
        for c in f["comparisons"]
    }
    prov_ok = _provenance_passed(report)

    decisions: list[dict[str, Any]] = []
    for arm in decisional.arms:
        row = decisional_rows[arm]
        reads: dict[str, str | None] | None = None
        if gates is not None:
            reads = {
                f"{a} {gate}": _gate_status(gates, gate, a)
                for a in (ctx.reference, arm)
                for gate in ("SC-1", "SC-2")
            }
        decision, reasons = decide_default(
            in_decisional_family=True,
            evaluable=bool(row["evaluable"]),
            rejected=bool(row["rejected"]),
            delta=row["delta"],
            guard=guard_of.get(arm) if arm in prereg.null_guard_arms else None,
            provenance_passed=prov_ok,
            gate_reads=reads,
        )
        support = supporting_rows.get(arm)
        decisions.append({
            "kind": "default_decision",
            "lever": arm,
            "decision": decision,
            "reasons": reasons,
            "answer_usable_decision": row["decision"],
            "delta": row["delta"],
            "hits_at_4_support": None if support is None else support["decision"],
            "hits_at_4_note": None
            if support is None
            else "a retrieval claim only; never a default on its own (D-150)",
            "gate_reads": reads,
            "interaction_caveat": INTERACTION_CAVEAT,
        })

    rerank_rows, prov_rows = _operation_tables(ctx)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "run": run.resolve().name,
            "corpus": config.name,
            "preregistration_token": token,
            "reference_arm": ctx.reference,
            "arms": sorted(arm_set),
            "journal_created_at": header.get("created_at") if header else None,
            "index_generation": report.metadata.index_generation,
            "judged": False,
        },
        "preregistration": asdict(prereg),
        "populations": {
            "n_heldout_g": ctx.n_g,
            "n_heldout_null": ctx.n_null,
            "floor": float(prereg.complete_case_floor),
            "p_all_label": LABEL_ALL_ARM,
            "provenance_block_passed": prov_ok,
        },
        "fwer_statement": FWER_STATEMENT,
        "ci_statement": CROSS_FAMILY_NOTE,
        "families": families,
        "null_guards": [asdict(g) for g in guards],
        "answer_mix": [_answer_mix(ctx, a) for a in lever_arms],
        "descriptive_rows": _descriptive_rows(ctx),
        "graph_state": _graph_state(ctx),
        "sensitivity": {
            "p_dec": _p_dec_line(ctx),
            "rerank_itt": _rerank_itt_line(ctx),
        },
        "secondaries": _secondaries(ctx, lever_arms),
        "rerank_operation": rerank_rows,
        "provenance_counts": prov_rows,
        "gate_readings": None
        if gates is None
        else {
            f"{a} {gate}": _gate_status(gates, gate, a)
            for a in preregistration.arms_of(prereg)
            for gate in ("SC-1", "SC-2")
        },
        "default_decisions": decisions,
    }
    return payload


# ---- rendering -----------------------------------------------------------------------


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _row(*cols: object) -> str:
    return "| " + " | ".join(str(c) for c in cols) + " |"


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    return [
        _row(*header),
        _row(*("---" for _ in header)),
        *(_row(*r) for r in rows),
        "",
    ]


def render_markdown(payload: Mapping[str, Any]) -> str:
    """Renders the payload as `lever-comparison.md`."""
    run = payload["run"]
    pops = payload["populations"]
    out: list[str] = [
        f"# Lever comparison: {run['corpus']}",
        "",
        f"- Run: `{run['run']}`; pre-registration `{run['preregistration_token']}`; "
        f"reference arm `{run['reference_arm']}`.",
        "- No judge ran and no judged figure exists in this phase (D-153).",
        f"- |H_G| = {pops['n_heldout_g']}, |H_N| = {pops['n_heldout_null']}; "
        f"coverage floor {pops['floor']} per comparison (exact).",
        f"- `report.json` cells are on the {pops['p_all_label']}.",
        "",
        "## Familywise error",
        "",
        payload["fwer_statement"],
        "",
        payload["ci_statement"],
        "",
    ]
    for fam in payload["families"]:
        out += [
            f"## Holm family `{fam['primary']}` ({fam['role']}; m = {fam['m']}, "
            f"alpha = {fam['alpha']})",
            "",
        ]
        out += _table(
            [
                "arm",
                "n (P_X)",
                "coverage",
                "n_pos",
                "n_neg",
                "p",
                "Holm p",
                "decision",
                "delta",
                "95% CI (unadjusted, estimation only)",
                "mean arm",
                "mean hybrid on P_X",
            ],
            [
                (
                    c["arm"],
                    c["n_pairs"],
                    _fmt(c["coverage"], 3),
                    _fmt(c["n_pos"]),
                    _fmt(c["n_neg"]),
                    _fmt(c["raw_p"]),
                    _fmt(c["adjusted_p"]),
                    c["decision"] + (f" ({c['ci_note']})" if c["ci_note"] else ""),
                    _fmt(c["delta"]),
                    f"[{_fmt(c['ci_lo'])}, {_fmt(c['ci_hi'])}]",
                    _fmt(c["mean_arm"]),
                    _fmt(c["mean_reference"]),
                )
                for c in fam["comparisons"]
            ],
        )
        out += _table(
            [
                "arm",
                "own failure",
                "own provenance",
                "rerank degrade",
                "reference failure",
                "reference provenance",
            ],
            [
                (
                    c["arm"],
                    c["exclusions"]["own_failure"],
                    c["exclusions"]["own_provenance"],
                    c["exclusions"]["rerank_degrade"],
                    c["exclusions"]["reference_failure"],
                    c["exclusions"]["reference_provenance"],
                )
                for c in fam["comparisons"]
            ],
        )
    out += ["## Guard 1: null-abstention paired drop (D-148)", ""]
    out += _table(
        [
            "arm",
            "decisional",
            "predicate",
            "N_X",
            "needs",
            "b",
            "c",
            "net loss",
            "margin",
            "reading",
            "one-sided 95% bound",
            "note",
        ],
        [
            (
                g["arm"],
                g["decisional"],
                f"`{g['predicate']}`",
                g["n_pairs"],
                g["min_pairs"],
                g["b"],
                g["c"],
                _fmt(g["net_loss_rate"]),
                g["margin"],
                g["status"],
                _fmt(g["upper_bound_95"]),
                (g["ni_label"] + "; " if g["ni_label"] else "") + g["note"],
            )
            for g in payload["null_guards"]
        ],
    )
    out += ["## Guard 2: answer-mix disclosure (reported only)", ""]
    for block in payload["answer_mix"]:
        out += [f"### {block['arm']}", "", f"_{block['label']}_", ""]
        out += _table(
            ["subset", "n", "side", "yes", "no", "insufficient", "other"],
            [
                row
                for m in block["mix"]
                for row in (
                    (
                        m["subset"],
                        m["n"],
                        "arm",
                        *(
                            _fmt(m["arm"][k], 3)
                            for k in ("yes", "no", "insufficient_information", "other")
                        ),
                    ),
                    (
                        m["subset"],
                        m["n"],
                        "hybrid",
                        *(
                            _fmt(m["reference"][k], 3)
                            for k in ("yes", "no", "insufficient_information", "other")
                        ),
                    ),
                    (
                        m["subset"],
                        m["n"],
                        "gold",
                        _fmt(m["gold"]["yes"], 3),
                        _fmt(m["gold"]["no"], 3),
                        "-",
                        _fmt(m["gold"]["other"], 3),
                    ),
                    (
                        m["subset"],
                        m["n"],
                        "constant-Yes / constant-No answer_usable",
                        _fmt(m["constant_yes_answer_usable"], 3),
                        _fmt(m["constant_no_answer_usable"], 3),
                        "-",
                        "-",
                    ),
                )
            ],
        )
        out += _table(
            [
                "stratum",
                "abstain->correct",
                "wrong->correct",
                "correct->wrong",
                "correct->abstain",
                "answer->abstain",
                "n",
            ],
            [
                (
                    k,
                    t["abstain_to_correct"],
                    t["wrong_to_correct"],
                    t["correct_to_wrong"],
                    t["correct_to_abstain"],
                    t["answer_to_abstain"],
                    t["n"],
                )
                for k, t in block["transitions"].items()
            ],
        )
        nb = block["non_binary_gold"]
        out += [
            f"Non-binary gold (n = {nb['n']}): arm {_fmt(nb['mean_arm'])}, hybrid "
            f"{_fmt(nb['mean_reference'])}, delta {_fmt(nb['delta'])} "
            f"[{_fmt(nb['ci_lo'])}, {_fmt(nb['ci_hi'])}] ({nb['ci_label']}).",
            "",
        ]
    out += ["## D-140 descriptive rows", ""]
    out += _table(
        [
            "row",
            "n",
            "primary",
            "delta",
            "95% CI (unadjusted, estimation only)",
            "n_pos",
            "n_neg",
            "label",
        ],
        [
            (
                d["row"],
                d["n_pairs"],
                p,
                _fmt(d[p]["delta"]),
                f"[{_fmt(d[p]['ci_lo'])}, {_fmt(d[p]['ci_hi'])}]",
                d[p]["n_pos"],
                d[p]["n_neg"],
                d["label"],
            )
            for d in payload["descriptive_rows"]
            for p in ("answer_usable", "paper_hits_at_4")
        ],
    )
    out += _table(
        ["graph-on arm", "records", "degree_capped_count"],
        [
            (g["arm"], g["records"], g["degree_capped_count"])
            for g in payload["graph_state"]
        ],
    )
    sens = payload["sensitivity"]
    pdec = sens["p_dec"]
    out += [
        f"## Sensitivity: P_dec ({pdec['label']})",
        "",
        f"{pdec['population']}; n = {pdec['n_pdec']}, "
        f"coverage {_fmt(pdec['coverage'], 3)}.",
        "",
    ]
    out += _table(
        ["arm", "n", "p", "Holm p", "decision", "delta"],
        [
            (
                c["arm"],
                c["n_pairs"],
                _fmt(c["raw_p"]),
                _fmt(c["adjusted_p"]),
                c["decision"],
                _fmt(c["delta"]),
            )
            for c in pdec["comparisons"]
        ],
    )
    itt = sens["rerank_itt"]
    if itt is not None:
        out += [
            f"## Sensitivity: rerank intention to treat ({itt['label']})",
            "",
            f"{itt['population']}; n = {itt['n_pairs']}, p = {_fmt(itt['raw_p'])}, "
            f"Holm p = {_fmt(itt['adjusted_p'])}, {itt['decision']}, delta "
            f"{_fmt(itt['delta'])} [{_fmt(itt['ci_lo'])}, {_fmt(itt['ci_hi'])}] "
            f"({itt['ci_label']}).",
            "",
        ]
    out += ["## Secondaries on P_X (no p-value; unadjusted, estimation only)", ""]
    out += _table(
        ["arm", "metric", "n", "mean arm", "mean hybrid", "delta", "95% CI"],
        [
            (
                s["arm"],
                s["metric"],
                s["n_pairs"],
                _fmt(s["mean_arm"]),
                _fmt(s["mean_reference"]),
                _fmt(s["delta"]),
                f"[{_fmt(s['ci_lo'])}, {_fmt(s['ci_hi'])}]"
                + (" parser-parity review" if s.get("parser_parity_review") else ""),
            )
            for s in payload["secondaries"]
        ],
    )
    out += ["## Rerank operation", ""]
    out += _table(
        [
            "arm",
            "attempts",
            "degrades",
            "rate",
            "timeout",
            "status",
            "malformed",
            "transport",
            "unknown",
            "p50 ms",
            "p95 ms",
            "max ms",
            "cost credits",
            "calls without cost",
        ],
        [
            (
                r["arm"],
                r["attempts"],
                r["degrades"],
                _fmt(r["degrade_rate"], 3),
                *(
                    r["degrades_by_class"][k]
                    for k in ("timeout", "status", "malformed", "transport", "unknown")
                ),
                _fmt(r["latency_ms_p50"], 1),
                _fmt(r["latency_ms_p95"], 1),
                _fmt(r["latency_ms_max"], 1),
                _fmt(r["cost_credits_reported_sum"], 6),
                r["calls_without_reported_cost"],
            )
            for r in payload["rerank_operation"]
        ],
    )
    out += ["## Provenance and retry counts", ""]
    out += _table(
        [
            "arm",
            "records",
            "(h) failures",
            "(j) failures",
            "(i) degraded",
            "query_embedding_retries",
        ],
        [
            (
                p["arm"],
                p["records"],
                p["clause_h_failures"],
                p["clause_j_failures"],
                p["clause_i_degraded"],
                p["query_embedding_retries"],
            )
            for p in payload["provenance_counts"]
        ],
    )
    out += ["## Default decisions (D-150, O16)", ""]
    out += _table(
        ["lever", "decision", "answer_usable", "delta", "Hits@4 support", "reasons"],
        [
            (
                d["lever"],
                d["decision"],
                d["answer_usable_decision"],
                _fmt(d["delta"]),
                d["hits_at_4_support"] or "n/a (not in the supporting family)",
                "; ".join(d["reasons"]) or "all conditions hold",
            )
            for d in payload["default_decisions"]
        ],
    )
    out += [INTERACTION_CAVEAT, ""]
    return "\n".join(out)


def _dump_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"


def write_lever_comparison(
    run_dir: Path | str,
    *,
    gold_chunks_path: Path | str | None = None,
    git_repo: Path | None = None,
) -> dict[str, Any]:
    """Builds the comparison and writes `lever-comparison.json` and `.md` into the run.

    Everything is built in memory first (the D-73 gate inside the build), so a refusal
    leaves nothing written. `report.json` is never touched.

    Args:
        run_dir: A run directory that `score --no-judge` has scored.
        gold_chunks_path: See `build_lever_comparison`.
        git_repo: See `build_lever_comparison`.

    Returns:
        The payload that was written.

    Raises:
        LeverComparisonError: If the comparison cannot be built.
    """
    run = Path(run_dir)
    payload = build_lever_comparison(
        run, gold_chunks_path=gold_chunks_path, git_repo=git_repo
    )
    text_json = _dump_json(payload)
    text_md = render_markdown(payload)
    for name, text in zip(OUTPUT_FILES, (text_json, text_md), strict=True):
        with open(run / name, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    return payload
