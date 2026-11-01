"""The S3M writer grid's reading (#148, experiments/v1.1/EXPLORE-S3-MHR-WRITERS.md).

Each writer's graph-on arm and the graph-off reference are driven in runs of their own,
one answer per question a run, so `compare-levers` (which pairs arms within one run)
cannot read them. This module pairs them across runs as `PREREGISTRATION_S3M` says:

- a question's score on an arm is the mean ``answer_usable`` of its ``success``
  answers over the arm's runs (K = 2);
- per writer, the paired delta against the reference on the G questions, with n_pos,
  n_neg and the exact sign-flip p on the per-question mean differences (D-274),
  reported and not used; a comparison is evaluable when at least 0.80 of the G
  questions pair;
- the same split into yes/no and open questions;
- the null guard on the null questions: the net abstention drop (reference abstention
  rate minus the arm's, summed over the paired nulls) fails above 0.10 of the null
  pairs, and is not evaluable below 0.80 of the nulls paired (D-264);
- the reading rule: the writer explains the loss iff a Claude writer's delta is at
  least 0 and at least 5 points above deepseek's; does not iff every Claude writer's
  delta is below 0 and within 5 points of deepseek's; else (or without deepseek) open.

Run it as ``python -m lancet_eval.s3m_reading --corpus multihop_rag_s3m_dev
--reference <run> <run> --writer deepseek <run> <run> --writer haiku-5.5 <run> <run>
...``. It reads runs; it decides nothing.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from lancet_eval import thresholds
from lancet_eval.corpus import GoldQuestion, load_corpus
from lancet_eval.evidence_split import is_yes_no
from lancet_eval.journal import load_records
from lancet_eval.metrics import answer_usable, is_abstention
from lancet_eval.pairing import deduplicate_by_arm
from lancet_eval.stats import exact_signflip_p_integer

PRE = thresholds.PREREGISTRATION_S3M
REFERENCE_WRITER = "deepseek"
#: The rule's margin: 5 points.
RULE_MARGIN = 0.05


@dataclass(frozen=True)
class Answer:
    """One ``success`` answer: whether it is usable, whether it abstains."""

    usable: bool
    abstained: bool


#: An arm's answers by question ID, over all its runs.
Answers = Mapping[str, Sequence[Answer]]


@dataclass(frozen=True)
class Comparison:
    """One arm against the reference on one set of G questions."""

    n_questions: int
    n_pairs: int
    evaluable: bool
    arm_mean: float | None
    reference_mean: float | None
    delta: float | None
    n_pos: int
    n_neg: int
    p_signflip: float | None


@dataclass(frozen=True)
class NullGuard:
    n_nulls: int
    n_pairs: int
    evaluable: bool
    net_drop: float
    passes: bool


@dataclass(frozen=True)
class WriterReading:
    writer: str
    runs: int
    all: Comparison
    yes_no: Comparison
    open: Comparison
    null_guard: NullGuard


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def compare(
    arm: Answers, reference: Answers, qids: Sequence[str], k: int = 2
) -> Comparison:
    """Pairs the arm with the reference on ``qids`` (both need a ``success`` answer)."""
    pairs = [
        (
            _mean([a.usable for a in arm[q]]),
            _mean([a.usable for a in reference[q]]),
        )
        for q in qids
        if arm.get(q) and reference.get(q)
    ]
    evaluable = bool(qids) and len(pairs) >= PRE.complete_case_floor * len(qids)
    if not evaluable or not pairs:
        return Comparison(len(qids), len(pairs), False, None, None, None, 0, 0, None)
    diffs = [a - r for a, r in pairs]
    return Comparison(
        n_questions=len(qids),
        n_pairs=len(pairs),
        evaluable=True,
        arm_mean=_mean([a for a, _ in pairs]),
        reference_mean=_mean([r for _, r in pairs]),
        delta=_mean(diffs),
        n_pos=sum(d > 0 for d in diffs),
        n_neg=sum(d < 0 for d in diffs),
        p_signflip=float(exact_signflip_p_integer([round(d * k) for d in diffs])),
    )


def null_guard(arm: Answers, reference: Answers, nulls: Sequence[str]) -> NullGuard:
    """D-264's guard on mean abstention rates (K answers a question)."""
    pairs = [
        (
            _mean([a.abstained for a in reference[q]]),
            _mean([a.abstained for a in arm[q]]),
        )
        for q in nulls
        if arm.get(q) and reference.get(q)
    ]
    evaluable = bool(nulls) and len(pairs) >= PRE.null_guard_min_pair_fraction * len(
        nulls
    )
    drop = sum(r - a for r, a in pairs)
    passes = evaluable and drop <= PRE.null_guard_margin * len(pairs)
    return NullGuard(len(nulls), len(pairs), evaluable, drop, passes)


def read_writer(
    writer: str,
    arm: Answers,
    reference: Answers,
    questions: Mapping[str, GoldQuestion],
    runs: int,
) -> WriterReading:
    g = sorted(q for q, gq in questions.items() if not gq.is_null)
    nulls = sorted(q for q, gq in questions.items() if gq.is_null)
    yes_no = [q for q in g if is_yes_no(questions[q])]
    open_ = [q for q in g if not is_yes_no(questions[q])]
    return WriterReading(
        writer=writer,
        runs=runs,
        all=compare(arm, reference, g),
        yes_no=compare(arm, reference, yes_no),
        open=compare(arm, reference, open_),
        null_guard=null_guard(arm, reference, nulls),
    )


def verdict(readings: Sequence[WriterReading]) -> str:
    """The pre-registered reading rule over the writers' G deltas."""
    by = {r.writer: r.all.delta for r in readings}
    base = by.get(REFERENCE_WRITER)
    claude = [d for w, d in by.items() if w != REFERENCE_WRITER]
    if base is None or not claude or any(d is None for d in claude):
        return "open"
    eps = 1e-9
    if any(d >= -eps and d - base >= RULE_MARGIN - eps for d in claude):
        return "the writer explains the loss"
    if all(d < -eps and d - base < RULE_MARGIN - eps for d in claude):
        return "the writer does not explain the loss"
    return "open"


def load_answers(
    run_dirs: Sequence[Path], arm: str, questions: Mapping[str, GoldQuestion]
) -> Answers:
    """The `success` answers of `arm` in each run's journal, deduplicated per run."""
    got: dict[str, list[Answer]] = defaultdict(list)
    for run in run_dirs:
        records, _ = deduplicate_by_arm(load_records(run / "journal.jsonl"))
        for r in records:
            if r.graph_arm == arm and r.outcome == "success":
                usable = answer_usable(questions[r.question_id], r.answer or "")
                got[r.question_id].append(Answer(usable, is_abstention(r)))
    return got


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--reference", nargs="+", type=Path, required=True)
    parser.add_argument(
        "--writer", nargs="+", action="append", required=True, metavar="NAME RUN"
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    questions = {q.question_id: q for q in load_corpus(args.corpus).questions}
    reference = load_answers(args.reference, PRE.reference_arm, questions)
    (graph_arm,) = PRE.families[0].arms
    readings = []
    for name, *runs in args.writer:
        arm = load_answers([Path(r) for r in runs], graph_arm, questions)
        readings.append(read_writer(name, arm, reference, questions, len(runs)))
    report = {
        "preregistration": "PREREGISTRATION_S3M",
        "reference_runs": [str(r) for r in args.reference],
        "writers": [asdict(r) for r in readings],
        "verdict": verdict(readings),
    }
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
