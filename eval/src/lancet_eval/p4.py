"""The P4 complete-case population and the paired reads over it (D-121, D-122).

P4 is the set of held-out G questions for which **all four arms** have a record that is
`ok` (D-34 usable and provenance-clean, `provenance.is_ok`). Every per-arm cell and
every paired delta of the four-arm table is computed on this one question set, so a
delta equals `mean_X(P4) - mean_hybrid(P4)` exactly and the three comparisons share one
n (AI-SPEC 5 Populations).

A usable record with a blank answer, such as a bm25-only NO_EVIDENCE decline, is *in*
P4: it scores 0 on `answer_usable` and counts as an abstention. Declines are never
dropped from the denominator (D-121).

Pure functions only: no journal I/O, no network, no git.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from statistics import fmean
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from lancet_eval import provenance
from lancet_eval.arms import canonical_arm
from lancet_eval.metrics import is_abstention
from lancet_eval.stats import BOOTSTRAP_B, BOOTSTRAP_SEED, bootstrap_mean_ci
from lancet_eval.usability import is_usable

if TYPE_CHECKING:
    from lancet_eval.journal import RunRecord
    from lancet_eval.split import HeldOutSplit

DEFAULT_REFERENCE_ARM = "hybrid"


class ArmExclusion(BaseModel):
    """Why one arm sees held-out G questions leave P4 (D-122).

    Each question that is not in P4 is counted for the arm in exactly one bucket.

    Attributes:
        own_failure: The arm's own record is missing or not D-34 usable.
        provenance: The arm's own record is usable but fails arm provenance.
        other_arm_failure: The arm's own record is ok; another arm's is not.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    own_failure: int = 0
    provenance: int = 0
    other_arm_failure: int = 0


class P4Population(BaseModel):
    """The complete-case population and what it dropped (D-121, D-122).

    Attributes:
        question_ids: The P4 question IDs, sorted ascending.
        arms: The canonical arm labels the population was built over.
        reference_arm: The canonical reference arm of the pairwise joins.
        excluded: Per canonical arm, the held-out G questions outside P4, by reason.
        pairwise_join_sizes: Per non-reference arm, the held-out G questions where both
            that arm and the reference arm have an ok record (the D-37 join size).
        n_heldout_g: The split's held-out G size, the coverage denominator.
        coverage: `len(question_ids) / n_heldout_g` (0.0 when the split has no G).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    question_ids: tuple[str, ...]
    arms: tuple[str, ...]
    reference_arm: str
    excluded: dict[str, ArmExclusion]
    pairwise_join_sizes: dict[str, int]
    n_heldout_g: int
    coverage: float = Field(ge=0.0, le=1.0)


class PairedDelta(BaseModel):
    """A paired mean difference with its bootstrap CI (D-111, D-120).

    Attributes:
        delta: `mean(values_x) - mean(values_ref)` over the shared questions.
        ci_lower: Lower bound of the 95% percentile bootstrap CI of the mean difference.
        ci_upper: Upper bound.
        n: Number of paired questions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    delta: float
    ci_lower: float
    ci_upper: float
    n: int


class JudgedPairCounts(BaseModel):
    """The selection effect behind a judged delta (AI-SPEC 5, D-118).

    Every P4 question falls in exactly one bucket.

    Attributes:
        both_answered: Both arms answered and both have a usable judged verdict.
        only_x_abstained: Only the compared arm abstained.
        only_reference_abstained: Only the reference arm abstained.
        both_abstained: Both abstained.
        judge_unavailable: Both answered but at least one verdict is missing or an
            error.
        pair_question_ids: The `both_answered` question IDs, sorted ascending.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    both_answered: int
    only_x_abstained: int
    only_reference_abstained: int
    both_abstained: int
    judge_unavailable: int
    pair_question_ids: tuple[str, ...]


def _canonical_arms(arms: Sequence[str]) -> list[str]:
    seen: dict[str, str] = {}
    out: list[str] = []
    for label in arms:
        canonical = canonical_arm(label)
        if canonical in seen:
            raise ValueError(
                f"arms {seen[canonical]!r} and {label!r} are the same arm "
                f"({canonical!r})"
            )
        seen[canonical] = label
        out.append(canonical)
    return out


def _index_records(
    records: Sequence[RunRecord], wanted: set[str], arms: set[str]
) -> dict[tuple[str, str], RunRecord]:
    """Index records by (question_id, canonical arm); a later record wins."""
    stored: dict[tuple[str, str], str] = {}
    index: dict[tuple[str, str], RunRecord] = {}
    for rec in records:
        if rec.question_id not in wanted:
            continue
        try:
            canonical = canonical_arm(rec.graph_arm)
        except ValueError:
            continue
        if canonical not in arms:
            continue
        key = (rec.question_id, canonical)
        seen = stored.setdefault(key, rec.graph_arm)
        if seen != rec.graph_arm:
            raise ValueError(
                f"question {rec.question_id!r} has records under both {seen!r} and "
                f"{rec.graph_arm!r}, which are the same arm ({canonical!r}); "
                "refusing to merge them"
            )
        index[key] = rec
    return index


def build_p4(
    records: Sequence[RunRecord],
    split: HeldOutSplit,
    arms: Sequence[str],
    *,
    reference_arm: str = DEFAULT_REFERENCE_ARM,
    ok: Callable[[RunRecord], bool] = provenance.is_ok,
) -> P4Population:
    """Builds P4: held-out G questions where every arm has an ok record (D-121, D-122).

    Records are matched to an arm by `canonical_arm`, so a legacy label answers to its
    canonical arm; a record outside the held-out G set, or of an arm not in `arms`, is
    ignored. A usable blank-answer NO_EVIDENCE record is ok and stays in P4.

    Args:
        records: Deduplicated journal records of any arms.
        split: The committed held-out split; `heldout_g_ids` is the candidate set.
        arms: The arms every P4 question must have an ok record for (labels or aliases).
        reference_arm: The arm the pairwise join sizes are measured against; it must be
            one of `arms`.
        ok: The ok(r) predicate; `provenance.is_ok` by default.

    Returns:
        The population, the exclusions per arm by reason, the pairwise join sizes with
        the reference arm, and the coverage `|P4| / len(split.heldout_g_ids)`.

    Raises:
        ValueError: If an arm is unknown or repeated, the reference arm is not among
            `arms`, or one question holds records under two stored labels of one arm.
    """
    canonical = _canonical_arms(arms)
    reference = canonical_arm(reference_arm)
    if reference not in canonical:
        raise ValueError(f"reference arm {reference!r} is not among the arms")
    g_ids = list(split.heldout_g_ids)
    index = _index_records(records, set(g_ids), set(canonical))

    def status(qid: str, arm: str) -> str:
        rec = index.get((qid, arm))
        if rec is None or not is_usable(rec):
            return "own"
        return "ok" if ok(rec) else "provenance"

    members: list[str] = []
    excluded = {arm: {"own": 0, "provenance": 0, "other": 0} for arm in canonical}
    join_sizes = {arm: 0 for arm in canonical if arm != reference}
    for qid in sorted(g_ids):
        states = {arm: status(qid, arm) for arm in canonical}
        if all(s == "ok" for s in states.values()):
            members.append(qid)
        else:
            for arm, state in states.items():
                excluded[arm]["other" if state == "ok" else state] += 1
        for arm in join_sizes:
            if states[arm] == "ok" and states[reference] == "ok":
                join_sizes[arm] += 1

    n_g = len(g_ids)
    return P4Population(
        question_ids=tuple(members),
        arms=tuple(canonical),
        reference_arm=reference,
        excluded={
            arm: ArmExclusion(
                own_failure=c["own"],
                provenance=c["provenance"],
                other_arm_failure=c["other"],
            )
            for arm, c in excluded.items()
        },
        pairwise_join_sizes=join_sizes,
        n_heldout_g=n_g,
        coverage=(len(members) / n_g) if n_g else 0.0,
    )


def per_question_values(
    records: Sequence[RunRecord],
    p4: P4Population,
    arm: str,
    value_fn: Callable[[RunRecord], float],
) -> dict[str, float]:
    """One value per P4 question for one arm (D-121).

    Every P4 record is scored, a blank NO_EVIDENCE decline included: `value_fn` decides
    what it is worth (`answer_usable` scores it 0).

    Args:
        records: Journal records containing the arm's P4 records.
        p4: The population.
        arm: A label or alias of one of the population's arms.
        value_fn: Maps a record to its per-question value.

    Returns:
        `{question_id: value}` for the P4 questions, in P4 order.

    Raises:
        ValueError: If the arm is not in the population or a P4 question has no record
            of that arm.
    """
    canonical = canonical_arm(arm)
    if canonical not in p4.arms:
        raise ValueError(f"arm {canonical!r} is not in this P4 population")
    index = _index_records(records, set(p4.question_ids), {canonical})
    values: dict[str, float] = {}
    for qid in p4.question_ids:
        rec = index.get((qid, canonical))
        if rec is None:
            raise ValueError(f"P4 question {qid!r} has no {canonical!r} record")
        values[qid] = float(value_fn(rec))
    return values


def _shared_keys(
    values_x: Mapping[str, float], values_ref: Mapping[str, float]
) -> list[str]:
    if set(values_x) != set(values_ref):
        raise ValueError("the two arms' values do not cover the same questions")
    return sorted(values_x)


def paired_delta(
    values_x: Mapping[str, float],
    values_ref: Mapping[str, float],
    *,
    b: int = BOOTSTRAP_B,
    seed: int = BOOTSTRAP_SEED,
) -> PairedDelta:
    """The paired delta of arm X against the reference over one question set (D-111).

    `delta` is `fmean(values_x) - fmean(values_ref)`, so it equals the difference of
    the two arms' per-arm means over the same questions exactly. The CI is the
    percentile bootstrap of the per-question differences (B = `BOOTSTRAP_B`,
    seed = `BOOTSTRAP_SEED` unless overridden).

    Args:
        values_x: Per-question values of the compared arm.
        values_ref: Per-question values of the reference arm; the same keys.
        b: Bootstrap resamples.
        seed: Bootstrap PRNG seed.

    Returns:
        The delta, its CI and n.

    Raises:
        ValueError: If the key sets differ or are empty.
    """
    keys = _shared_keys(values_x, values_ref)
    if not keys:
        raise ValueError("n=0: no paired questions")
    diffs = [values_x[k] - values_ref[k] for k in keys]
    _, lo, hi = bootstrap_mean_ci(diffs, seed=seed, b=b)
    delta = fmean(values_x[k] for k in keys) - fmean(values_ref[k] for k in keys)
    return PairedDelta(delta=delta, ci_lower=lo, ci_upper=hi, n=len(keys))


def discordant_counts(
    values_x: Mapping[str, float], values_ref: Mapping[str, float]
) -> tuple[int, int]:
    """Counts of discordant pairs, the input of `stats.exact_signflip_p` (D-123).

    Args:
        values_x: Per-question values of the compared arm (0/1 for the primaries).
        values_ref: Per-question values of the reference arm; the same keys.

    Returns:
        `(n_pos, n_neg)`: questions where X scored above, and below, the reference.
        A tie (both 1 or both 0) counts in neither.

    Raises:
        ValueError: If the key sets differ.
    """
    keys = _shared_keys(values_x, values_ref)
    n_pos = sum(1 for k in keys if values_x[k] > values_ref[k])
    n_neg = sum(1 for k in keys if values_x[k] < values_ref[k])
    return n_pos, n_neg


def judged_pairs(
    records: Sequence[RunRecord],
    p4: P4Population,
    arm: str,
    reference: str,
    *,
    judged_ok: Callable[[RunRecord], bool],
) -> JudgedPairCounts:
    """The selection-effect counts behind a judged delta (AI-SPEC 5, D-118, D-121).

    A judged delta runs over the P4 questions where both arms answered and both have a
    usable verdict. The other P4 questions are counted by why they left, so the report
    can show that an arm abstaining on hard questions made the pair set easier.

    Args:
        records: Journal records containing both arms' P4 records.
        p4: The population.
        arm: The compared arm.
        reference: The reference arm.
        judged_ok: Whether a record has a cached, non-error judge verdict.

    Returns:
        The counts and the pair question IDs.

    Raises:
        ValueError: If an arm is not in the population or a P4 question has no record.
    """
    arm_c, ref_c = canonical_arm(arm), canonical_arm(reference)
    for label in (arm_c, ref_c):
        if label not in p4.arms:
            raise ValueError(f"arm {label!r} is not in this P4 population")
    index = _index_records(records, set(p4.question_ids), {arm_c, ref_c})
    both_answered: list[str] = []
    only_x = only_ref = both_abs = unavailable = 0
    for qid in p4.question_ids:
        try:
            x_rec, r_rec = index[(qid, arm_c)], index[(qid, ref_c)]
        except KeyError as exc:
            raise ValueError(f"P4 question {qid!r} lacks a record of an arm") from exc
        x_abs, ref_abs = is_abstention(x_rec), is_abstention(r_rec)
        if x_abs and ref_abs:
            both_abs += 1
        elif x_abs:
            only_x += 1
        elif ref_abs:
            only_ref += 1
        elif judged_ok(x_rec) and judged_ok(r_rec):
            both_answered.append(qid)
        else:
            unavailable += 1
    return JudgedPairCounts(
        both_answered=len(both_answered),
        only_x_abstained=only_x,
        only_reference_abstained=only_ref,
        both_abstained=both_abs,
        judge_unavailable=unavailable,
        pair_question_ids=tuple(both_answered),
    )
