"""#149's paired reader differences (B and C), by permutation and bootstrap (#168).

`explore_readout` reports each reader's mean per-question difference against deepseek
with a percentile bootstrap interval. Here the same differences are read four ways:

- the exact two-sided paired sign-flip permutation p
  (``stats.exact_signflip_p_integer``, no seed);
- a 95% interval by inverting that test: every shift ``d`` whose shifted differences
  ``x - d`` the sign-flip test keeps at 0.05, the p drawn from ``draws`` seeded sign
  vectors (one set of draws serves every ``d``);
- the question-level percentile bootstrap (``stats.bootstrap_mean_ci``, seed 42,
  10,000 resamples), as `explore_readout` reports it;
- for contrast only, the normal approximation, mean +/- 1.96 standard errors.

A reader's per-question value is the mean of its ``success`` answers on a G question, so
a K=1 reader against K=2 deepseek compares one answer with a two-answer mean; the CLI
also pairs each reader with each single deepseek replicate. It reads a run and decides
nothing. Run it as ``python -m lancet_eval.paired_ci --journal <file> --corpus <c>``.
"""

from __future__ import annotations

import argparse
import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from lancet_eval.corpus import GoldQuestion, load_corpus
from lancet_eval.evidence_split import BASE_READER, reader_of
from lancet_eval.journal import RunRecord, load_records
from lancet_eval.metrics import answer_usable
from lancet_eval.pairing import deduplicate_by_arm
from lancet_eval.stats import bootstrap_mean_ci, exact_signflip_p_integer

DRAWS = 20_000
SEED = 42
ALPHA = 0.05

#: reader -> question -> replicate -> 0/1 `answer_usable`.
Usable = dict[str, dict[str, dict[int, float]]]


@dataclass(frozen=True)
class PairedInterval:
    """One paired difference, read four ways."""

    n: int
    mean: float
    permutation_p: Fraction
    permutation_ci: tuple[float, float]
    bootstrap_ci: tuple[float, float]
    normal_ci: tuple[float, float]


def usable_by_replicate(
    records: Sequence[RunRecord], questions: Mapping[str, GoldQuestion]
) -> Usable:
    """`answer_usable` of every ``success`` answer to a G question, by reader."""
    out: Usable = defaultdict(lambda: defaultdict(dict))
    for record in records:
        question = questions[record.question_id]
        if record.outcome != "success" or question.is_null:
            continue
        ok = float(answer_usable(question, record.answer or ""))
        out[reader_of(record.graph_arm)][record.question_id][record.replicate] = ok
    return {reader: dict(per_q) for reader, per_q in out.items()}


def paired_diffs(
    reader: Mapping[str, Mapping[int, float]],
    base: Mapping[str, Mapping[int, float]],
    *,
    base_replicate: int | None = None,
) -> list[Fraction]:
    """Per shared question, the reader's mean minus the base's, sorted by question.

    With ``base_replicate`` the base side is that one replicate, and a question the
    base did not answer in it is left out.
    """

    def mean(values: Mapping[int, float]) -> Fraction:
        return Fraction(sum(Fraction(v) for v in values.values()), len(values))

    out: list[Fraction] = []
    for qid in sorted(set(reader) & set(base)):
        if base_replicate is None:
            other = mean(base[qid])
        elif base_replicate in base[qid]:
            other = Fraction(base[qid][base_replicate])
        else:
            continue
        out.append(mean(reader[qid]) - other)
    return out


def paired_interval(
    diffs: Sequence[Fraction], *, draws: int = DRAWS, seed: int = SEED
) -> PairedInterval:
    """The four readings of ``diffs`` (see the module docstring).

    Raises:
        ValueError: ``diffs`` is empty.
    """
    n = len(diffs)
    if n == 0:
        raise ValueError("no paired question")
    scale = math.lcm(*(d.denominator for d in diffs))
    p = exact_signflip_p_integer([int(d * scale) for d in diffs])
    xs = [float(d) for d in diffs]
    mu, b_lo, b_hi = bootstrap_mean_ci(xs)
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    half = 1.96 * sd / math.sqrt(n)
    return PairedInterval(
        n=n,
        mean=mu,
        permutation_p=p,
        permutation_ci=_inverted_signflip_ci(xs, draws=draws, seed=seed),
        bootstrap_ci=(b_lo, b_hi),
        normal_ci=(mu - half, mu + half),
    )


def _inverted_signflip_ci(
    xs: Sequence[float], *, draws: int, seed: int
) -> tuple[float, float]:
    """The shifts ``d`` the two-sided sign-flip test of ``x - d`` keeps at ALPHA.

    For a sign vector ``e``, ``sum(e * (x - d)) = A - d * B`` with ``A = sum(e * x)``
    and ``B = sum(e)``, so one set of drawn ``(A, B)`` pairs prices every ``d``. The p
    counts the observed vector, ``(1 + hits) / (draws + 1)``. Each bound is found by
    bisection between the mean (p = 1) and a shift the test rejects.
    """
    n = len(xs)
    total = sum(xs)
    mean = total / n
    rng = random.Random(seed)
    pairs: list[tuple[float, int]] = []
    for _ in range(draws):
        bits = rng.getrandbits(n)
        a = 0.0
        b = 0
        for i, x in enumerate(xs):
            if bits >> i & 1:
                a += x
                b += 1
            else:
                a -= x
                b -= 1
        pairs.append((a, b))

    def kept(d: float) -> bool:
        observed = abs(total - n * d) - 1e-9
        hits = sum(1 for a, b in pairs if abs(a - d * b) >= observed)
        return (1 + hits) / (draws + 1) > ALPHA

    def bound(direction: int) -> float:
        # A difference lies in [-1, 1], so a shift of 2 past the mean is as extreme as
        # the data allows; a test that keeps it there (too few questions) has no bound.
        inside, outside = mean, mean + 2 * direction
        if kept(outside):
            return math.inf * direction
        for _ in range(40):
            mid = (inside + outside) / 2
            if kept(mid):
                inside = mid
            else:
                outside = mid
        return inside

    return bound(-1), bound(1)


def render_markdown(rows: Sequence[tuple[str, PairedInterval]]) -> str:
    """One row per comparison, in points (x100)."""
    lines = [
        "| comparison | n | delta | exact sign-flip p | permutation 95% CI "
        "| bootstrap 95% CI | normal 95% CI |",
        "|---|---|---|---|---|---|---|",
    ]

    def ci(pair: tuple[float, float]) -> str:
        return f"[{100 * pair[0]:+.1f}, {100 * pair[1]:+.1f}]"

    for label, r in rows:
        lines.append(
            f"| {label} | {r.n} | {100 * r.mean:+.1f} | {float(r.permutation_p):.2g} "
            f"| {ci(r.permutation_ci)} | {ci(r.bootstrap_ci)} | {ci(r.normal_ci)} |"
        )
    return "\n".join(lines)


def comparisons(usable: Usable) -> list[tuple[str, PairedInterval]]:
    """Each reader against deepseek's mean, then against each deepseek replicate."""
    base = usable[BASE_READER]
    replicates = sorted({r for reps in base.values() for r in reps})
    rows: list[tuple[str, PairedInterval]] = []
    for reader, per_q in usable.items():
        if reader == BASE_READER:
            continue
        rows.append((
            f"{reader} - deepseek",
            paired_interval(paired_diffs(per_q, base)),
        ))
        if len(replicates) > 1:
            for rep in replicates:
                diffs = paired_diffs(per_q, base, base_replicate=rep)
                rows.append((f"{reader} - deepseek r{rep}", paired_interval(diffs)))
    return rows


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--corpus", required=True)
    args = parser.parse_args(argv)
    records, _ = deduplicate_by_arm(load_records(args.journal))
    questions = {q.question_id: q for q in load_corpus(args.corpus).questions}
    print(render_markdown(comparisons(usable_by_replicate(records, questions))))


if __name__ == "__main__":
    main()
