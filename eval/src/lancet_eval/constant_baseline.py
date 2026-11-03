"""What a constant Yes (or No) answer scores on a pool's yes/no questions (#165).

Each G question of the pool (null questions left out, as `answer_usable` leaves them) is
answered ``Answer: Yes`` and ``Answer: No`` and scored by ``metrics.answer_usable``, so
the figure is the metric's own, not a count of golds. The yes/no questions are
``evidence_split.is_yes_no``'s. `answer_kinds.kind_split` reports the better of the two
as ``better_constant`` (#147, D-286); the two agree by construction, and a test pins it.

It reads the committed question files only; it decides nothing. Run it as
``python -m lancet_eval.constant_baseline --corpus <c> [--corpus <c> ...]``.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lancet_eval.corpus import GoldQuestion, load_corpus
from lancet_eval.evidence_split import is_yes_no
from lancet_eval.metrics import answer_usable


@dataclass(frozen=True)
class ConstantBaseline:
    """A pool's G questions and what each constant answer scores on its yes/no ones."""

    n_g: int
    n_yes: int
    n_no: int
    always_yes: float | None
    always_no: float | None
    better: float | None


def constant_scores(questions: Iterable[GoldQuestion]) -> ConstantBaseline:
    """Scores ``Answer: Yes`` and ``Answer: No`` on every yes/no G question."""
    g = [q for q in questions if not q.is_null]
    yes_no = [q for q in g if is_yes_no(q)]
    n_yes = sum(1 for q in yes_no if q.gold_answer.strip().lower() == "yes")
    if not yes_no:
        return ConstantBaseline(len(g), 0, 0, None, None, None)
    always_yes = sum(answer_usable(q, "Answer: Yes") for q in yes_no) / len(yes_no)
    always_no = sum(answer_usable(q, "Answer: No") for q in yes_no) / len(yes_no)
    return ConstantBaseline(
        n_g=len(g),
        n_yes=n_yes,
        n_no=len(yes_no) - n_yes,
        always_yes=always_yes,
        always_no=always_no,
        better=max(always_yes, always_no),
    )


def render_markdown(rows: Sequence[tuple[str, ConstantBaseline]]) -> str:
    """One row per pool."""

    def figure(value: float | None) -> str:
        return "–" if value is None else f"{value:.3f}"

    lines = [
        "| pool | G questions | yes/no | gold Yes | gold No | always Yes | always No |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, r in rows:
        lines.append(
            f"| {name} | {r.n_g} | {r.n_yes + r.n_no} | {r.n_yes} | {r.n_no} "
            f"| {figure(r.always_yes)} | {figure(r.always_no)} |"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", action="append", required=True)
    args = parser.parse_args(argv)
    rows = [
        (name, constant_scores(load_corpus(name).questions)) for name in args.corpus
    ]
    print(render_markdown(rows))


if __name__ == "__main__":
    main()
