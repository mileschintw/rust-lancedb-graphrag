"""The by-hand readout of #149's exploratory reader runs (B and C).

`compare-levers` reads one K for every arm, and B and C give Sonnet and Opus one
answer where deepseek and Haiku give two (``reader_replicates``), so these runs are
read here. Per reader it prints, over every ``success`` answer of the run's base arm
and its reader arms (error records left out, as in ``evidence_split``):

- ``answer_usable`` and the abstention rate (``metrics.is_abstention``) on the G
  questions, and the abstention rate on the null questions;
- ``answer_usable`` per question type, and #147's yes/no figures
  (``answer_kinds.kind_split`` over every answer): yes/no and open ``answer_usable``,
  and the yes/no balanced accuracy beside the better constant's share;
- the paired difference against deepseek: the mean over the G questions both answered
  of (the reader's per-question mean minus deepseek's), with a bootstrap 95% interval
  (``stats.bootstrap_mean_ci``, seed 42, 10,000 resamples);
- ``reasoning_tokens``, total and per answer, over every answer (null ones too).

The evidence and yes/no split is ``evidence_split``'s. It reads a run; it decides
nothing. Run it as ``python -m lancet_eval.explore_readout --run <dir> --corpus <c>``.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from lancet_eval.answer_kinds import KindSplit, kind_split
from lancet_eval.corpus import GoldQuestion, load_corpus
from lancet_eval.evidence_split import BASE_READER, reader_of
from lancet_eval.journal import RunRecord, load_records
from lancet_eval.metrics import answer_usable, is_abstention
from lancet_eval.pairing import deduplicate_by_arm
from lancet_eval.preregistration import PreregistrationError, require_unblinded
from lancet_eval.stats import bootstrap_mean_ci


@dataclass(frozen=True)
class ReaderReadout:
    """One reader's figures over a run."""

    reader: str
    g_questions: int
    g_answers: int
    answer_usable: float
    abstention: float
    null_answers: int
    null_abstention: float | None
    by_type: dict[str, tuple[int, float]]
    paired_n: int
    paired_delta: float | None
    paired_ci: tuple[float, float] | None
    reasoning_tokens: int
    answers: int
    kinds: KindSplit


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def readout(
    records: Sequence[RunRecord], questions: Mapping[str, GoldQuestion]
) -> list[ReaderReadout]:
    """Each reader's figures, readers in first-seen order, deepseek's delta None.

    Raises:
        KeyError: A record names a question the corpus lacks.
    """
    usable: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    abstain: dict[str, list[float]] = defaultdict(list)
    null_abstain: dict[str, list[float]] = defaultdict(list)
    by_type: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    reasoning: dict[str, int] = defaultdict(int)
    answered: dict[str, int] = defaultdict(int)
    kind_answers: dict[str, list[tuple[GoldQuestion, float]]] = defaultdict(list)
    for record in records:
        if record.outcome != "success":
            continue
        question = questions[record.question_id]
        reader = reader_of(record.graph_arm)
        answered[reader] += 1
        if record.replay is not None:
            reasoning[reader] += record.replay.reasoning_tokens
        if question.is_null:
            null_abstain[reader].append(float(is_abstention(record)))
            continue
        ok = float(answer_usable(question, record.answer or ""))
        usable[reader][record.question_id].append(ok)
        abstain[reader].append(float(is_abstention(record)))
        by_type[reader][question.question_type].append(ok)
        kind_answers[reader].append((question, ok))
    base = {qid: _mean(v) for qid, v in usable.get(BASE_READER, {}).items()}
    out: list[ReaderReadout] = []
    for reader, per_question in usable.items():
        answers = [ok for oks in per_question.values() for ok in oks]
        delta: float | None = None
        ci: tuple[float, float] | None = None
        shared = sorted(set(per_question) & set(base))
        if reader != BASE_READER and shared:
            diffs = [_mean(per_question[q]) - base[q] for q in shared]
            delta, lo, hi = bootstrap_mean_ci(diffs)
            ci = (lo, hi)
        nulls = null_abstain.get(reader, [])
        out.append(
            ReaderReadout(
                reader=reader,
                g_questions=len(per_question),
                g_answers=len(answers),
                answer_usable=_mean(answers),
                abstention=_mean(abstain[reader]),
                null_answers=len(nulls),
                null_abstention=_mean(nulls) if nulls else None,
                by_type={
                    t: (len(v), _mean(v)) for t, v in sorted(by_type[reader].items())
                },
                paired_n=len(shared) if reader != BASE_READER else 0,
                paired_delta=delta,
                paired_ci=ci,
                reasoning_tokens=reasoning[reader],
                answers=answered[reader],
                kinds=kind_split(kind_answers[reader]),
            )
        )
    return out


def render_markdown(rows: Sequence[ReaderReadout]) -> str:
    """Two Markdown tables: the per-reader figures, then answer_usable per type."""
    lines = [
        "| reader | G questions | G answers | answer_usable | abstention "
        "| null abstention | delta vs deepseek [95% CI] | reasoning tokens |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        null = "–" if r.null_abstention is None else f"{r.null_abstention:.3f}"
        if r.paired_delta is None or r.paired_ci is None:
            delta = "–"
        else:
            delta = (
                f"{r.paired_delta:+.3f} [{r.paired_ci[0]:+.3f}, {r.paired_ci[1]:+.3f}]"
                f" (n={r.paired_n})"
            )
        per_answer = r.reasoning_tokens / r.answers if r.answers else 0.0
        lines.append(
            f"| {r.reader} | {r.g_questions} | {r.g_answers} | {r.answer_usable:.3f} "
            f"| {r.abstention:.3f} | {null} | {delta} "
            f"| {r.reasoning_tokens} ({per_answer:.0f}/answer) |"
        )
    types = sorted({t for r in rows for t in r.by_type})
    lines += ["", "| reader | " + " | ".join(types) + " |"]
    lines.append("|---|" + "---|" * len(types))
    for r in rows:
        cells = [
            f"{r.by_type[t][1]:.3f} (n={r.by_type[t][0]})" if t in r.by_type else "–"
            for t in types
        ]
        lines.append(f"| {r.reader} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "| reader | yes/no usable | open usable | yes/no balanced accuracy "
        "| better constant |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        k = r.kinds
        lines.append(
            f"| {r.reader} | {_share(k.yes_no.n, k.yes_no.mean)} "
            f"| {_share(k.open.n, k.open.mean)} | {_figure(k.balanced_accuracy)} "
            f"| {_figure(k.better_constant)} |"
        )
    return "\n".join(lines)


def _figure(value: float | None) -> str:
    return "–" if value is None else f"{value:.3f}"


def _share(n: int, mean: float | None) -> str:
    return "–" if mean is None else f"{mean:.3f} (n={n})"


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--corpus", required=True)
    args = parser.parse_args(argv)
    config = load_corpus(args.corpus)
    try:
        require_unblinded(config)
    except PreregistrationError as exc:
        raise SystemExit(str(exc)) from exc
    records, _ = deduplicate_by_arm(load_records(args.run / "journal.jsonl"))
    questions = {q.question_id: q for q in config.questions}
    print(render_markdown(readout(records, questions)))


if __name__ == "__main__":
    main()
