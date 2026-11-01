"""MultiHop-RAG's official `qa_evaluate.py` against `answer_usable`, per answer (#166).

The official scorer (yixuantt/MultiHop-RAG, ``qa_evaluate.py``) counts an answer correct
when its lower-cased text, split on whitespace, shares any token with the lower-cased
gold. It takes the text inside ``The answer to the question is "..."`` when present,
else the whole answer. Our readers answer with a final ``Answer:`` line, so each answer
is scored two ways:

- ``line``: the raw text of the last ``Answer:`` line (``metrics._ANSWER_LINE``, the
  line `answer_usable` reads, before its normalisation), the closest to the paper's
  setup;
- ``full``: the whole answer, which is what the official file scores when it finds no
  quoted answer.

The official file is never installed or vendored: ``load_official`` imports it from a
path, with a stand-in for its one third-party import (``tqdm``, a progress bar) when
that is missing, and ``run_official_main`` runs its own ``main`` on a run's answers. It
reads a run and decides nothing. Run it as ``python -m lancet_eval.official_scorer
--official <qa_evaluate.py> --journal <file> --corpus <c> --work <dir>``.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import runpy
import sys
import types
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from lancet_eval.corpus import GoldQuestion, load_corpus
from lancet_eval.evidence_split import reader_of
from lancet_eval.journal import RunRecord, load_records
from lancet_eval.metrics import _ANSWER_LINE, answer_usable, is_abstention
from lancet_eval.pairing import deduplicate_by_arm

Variant = Literal["line", "full"]


@dataclass(frozen=True)
class AnswerScore:
    """One answer to a G question under both scorers."""

    ours: bool
    official_line: bool
    official_full: bool
    abstained: bool


@dataclass(frozen=True)
class ReaderComparison:
    """One reader's answers counted under both scorers (counts, not rates)."""

    reader: str
    g_answers: int
    ours: int
    official_line: int
    official_full: int
    #: Answers our scorer passes and the official one (``line``) fails, and back.
    ours_only_line: int
    official_only_line: int
    abstained: int
    abstained_official_line: int
    abstained_official_full: int
    null_answers: int
    #: Null-question answers the official scorer (``line``) passes.
    null_official_line: int


@contextlib.contextmanager
def _tqdm_stand_in() -> Iterator[None]:
    """Makes ``from tqdm import tqdm`` give the identity when tqdm is not installed."""
    if importlib.util.find_spec("tqdm") is not None:
        yield
        return
    stub = types.ModuleType("tqdm")
    stub.tqdm = lambda iterable, *args, **kwargs: iterable  # type: ignore[attr-defined]
    sys.modules["tqdm"] = stub
    try:
        yield
    finally:
        sys.modules.pop("tqdm", None)


def load_official(path: Path | str) -> types.ModuleType:
    """Imports the official ``qa_evaluate.py`` from ``path`` (its ``main`` not run)."""
    spec = importlib.util.spec_from_file_location("mhr_qa_evaluate", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    with _tqdm_stand_in():
        spec.loader.exec_module(module)
    return module


def final_line(answer: str | None) -> str:
    """The raw text of the last ``Answer:`` line; empty when there is none."""
    matches = list(_ANSWER_LINE.finditer(answer or ""))
    return matches[-1].group("a") if matches else ""


def _model_answer(record: RunRecord, variant: Variant) -> str:
    return final_line(record.answer) if variant == "line" else record.answer or ""


def _official(official: types.ModuleType, text: str, gold: str) -> bool:
    # As the official `calculate_metrics`: lower-case both after `extract_answer`.
    return bool(
        official.has_intersection(official.extract_answer(text).lower(), gold.lower())
    )


def score_answer(
    official: types.ModuleType, question: GoldQuestion, record: RunRecord
) -> AnswerScore:
    """One answer under `answer_usable` and the official scorer's two inputs."""
    gold = question.gold_answer
    return AnswerScore(
        ours=answer_usable(question, record.answer or ""),
        official_line=_official(official, _model_answer(record, "line"), gold),
        official_full=_official(official, _model_answer(record, "full"), gold),
        abstained=is_abstention(record),
    )


def compare(
    official: types.ModuleType,
    records: Iterable[RunRecord],
    questions: Mapping[str, GoldQuestion],
) -> list[ReaderComparison]:
    """Each reader's ``success`` answers counted under both scorers, readers in
    first-seen order."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for record in records:
        if record.outcome != "success":
            continue
        question = questions[record.question_id]
        c = counts[reader_of(record.graph_arm)]
        if question.is_null:
            c["null_answers"] += 1
            line = _model_answer(record, "line")
            c["null_official_line"] += _official(official, line, question.gold_answer)
            continue
        s = score_answer(official, question, record)
        c["g_answers"] += 1
        c["ours"] += s.ours
        c["official_line"] += s.official_line
        c["official_full"] += s.official_full
        c["ours_only_line"] += s.ours and not s.official_line
        c["official_only_line"] += s.official_line and not s.ours
        c["abstained"] += s.abstained
        c["abstained_official_line"] += s.abstained and s.official_line
        c["abstained_official_full"] += s.abstained and s.official_full
    fields = ReaderComparison.__dataclass_fields__
    return [
        ReaderComparison(reader=reader, **{k: c[k] for k in fields if k != "reader"})
        for reader, c in counts.items()
    ]


def run_official_main(
    official_path: Path | str,
    records: Iterable[RunRecord],
    questions: Mapping[str, GoldQuestion],
    work: Path,
    *,
    variant: Variant,
) -> str:
    """Writes the answers as the official input file and runs its ``main``.

    Every ``success`` record is one item (null questions too, as the official file
    scores them); the queries file holds the same golds. Returns what ``main`` printed.
    """
    work.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for record in records:
        if record.outcome != "success":
            continue
        q = questions[record.question_id]
        items.append({
            "query": q.question,
            "model_answer": _model_answer(record, variant),
            "gold_answer": q.gold_answer,
            "question_type": q.question_type,
        })
    answers = work / f"{variant}.json"
    queries = work / "queries.json"
    answers.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    golds = [{"query": q.question, "answer": q.gold_answer} for q in questions.values()]
    queries.write_text(json.dumps(golds, ensure_ascii=False), encoding="utf-8")
    out = io.StringIO()
    argv = sys.argv
    sys.argv = [str(official_path), "--file", str(answers), "--queries", str(queries)]
    try:
        with _tqdm_stand_in(), contextlib.redirect_stdout(out):
            runpy.run_path(str(official_path), run_name="__main__")
    finally:
        sys.argv = argv
    return out.getvalue()


def render_markdown(rows: Sequence[ReaderComparison]) -> str:
    """One row per reader: rates over its G answers, then the disagreement counts."""

    def rate(k: int, n: int) -> str:
        return f"{k / n:.3f}" if n else "–"

    lines = [
        "| reader | G answers | answer_usable | official (line) | official (full) "
        "| ours only / official only (line) | abstained | abstained, official passes "
        "(line / full) | null answers official passes (line) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r.reader} | {r.g_answers} | {rate(r.ours, r.g_answers)} "
            f"| {rate(r.official_line, r.g_answers)} "
            f"| {rate(r.official_full, r.g_answers)} "
            f"| {r.ours_only_line} / {r.official_only_line} | {r.abstained} "
            f"| {r.abstained_official_line} / {r.abstained_official_full} "
            f"| {r.null_official_line} of {r.null_answers} |"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args(argv)
    records, _ = deduplicate_by_arm(load_records(args.journal))
    questions = {q.question_id: q for q in load_corpus(args.corpus).questions}
    official = load_official(args.official)
    print(render_markdown(compare(official, records, questions)))
    for variant in ("line", "full"):
        printed = run_official_main(
            args.official, records, questions, args.work, variant=variant
        )
        overall = printed[printed.index("Overall Metrics:") :].strip().splitlines()
        print(f"\nOfficial main, all answers, {variant}: {overall[-1].strip()}")


if __name__ == "__main__":
    main()
