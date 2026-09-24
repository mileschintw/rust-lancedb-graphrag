"""D-74 read-only retro: format-vs-fix attribution baseline on the 06.3.4 journal.

Reproduces the whole-token-vs-substring containment split and the D-69
citation-constraint rejection baseline over the committed
`eval/runs/2026-09-09-multihop_rag/journal.jsonl`, entirely offline and
read-only.

This script NEVER imports the fail-closed scorer or report generator, opens
no subprocess, and writes to no path except the markdown file named by
`--out`. Its output is always labelled a partial-run diagnostic with its
sample size `n` — it must never be mistaken for a complete scored run
(OBS-05). The 06.3.4 and 2026-09-03 EM/Token-F1 numbers are non-comparable
with any run made after the index/prompt/seeding changes in this phase
(06.3.1 D-43 pattern) and are not reproduced here.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from lancet_eval.corpus import GoldQuestion, load_sample_questions
from lancet_eval.journal import RunRecord, load_records
from lancet_eval.metrics import gold_contained, squad_normalize
from lancet_eval.stats import wilson_ci

DEFAULT_JOURNAL = Path("eval/runs/2026-09-09-multihop_rag/journal.jsonl")
DEFAULT_CORPUS = "multihop_rag"

# D-69 message prefixes, reimplemented locally (not imported from
# lancet_eval.diagnostic) so this script's import surface stays limited to
# journal/corpus/metrics/stats — see module docstring and the AST-inspection
# test that pins this.
_D69_MIXED = "answer basis 'mixed' requires at least one cited evidence ID"
_D69_RETRIEVAL = "answer basis 'retrieval' requires at least one cited evidence ID"
_D69_MODEL_ONLY = "ModelOnly answer basis is not supported"

# Matches an "Answer:" label line the same way the D-71 extraction rule does,
# used here only to COUNT whether such a line is present (RESEARCH §G).
_ANSWER_LINE = re.compile(r"(?im)^[ \t>*_-]*answer[ \t*_]*:")


def substring_contained(gold: str, text: str) -> bool:
    """Character-substring containment of the normalized gold in normalized text.

    The looser of the two containment rules this retro compares (D-74); never
    used for any production metric.
    """
    norm_gold = squad_normalize(gold)
    norm_text = squad_normalize(text)
    return bool(norm_gold) and norm_gold in norm_text


def _has_answer_line(text: str) -> bool:
    return bool(_ANSWER_LINE.search(text))


def _reached_generate_answer(record: RunRecord) -> bool:
    """True if the record's workflow reached the GenerateAnswer node at all."""
    if record.outcome == "success":
        return True
    return any(nf.node_name == "GenerateAnswer" for nf in record.node_failures)


def _generate_answer_rejection_class(record: RunRecord) -> str | None:
    """D-69 class for a GenerateAnswer-node rejection, or None if not one."""
    for node_failure in record.node_failures:
        if node_failure.node_name != "GenerateAnswer":
            continue
        message = node_failure.error_message
        if message.startswith(_D69_MIXED):
            return "citation_basis_mixed"
        if message.startswith(_D69_RETRIEVAL):
            return "citation_basis_retrieval"
        if message.startswith(_D69_MODEL_ONLY):
            return "model_only_unsupported"
    return None


def _eligible_graph_off_successes(
    records: list[RunRecord], questions: dict[str, GoldQuestion]
) -> list[RunRecord]:
    """Graph-off, successful, non-empty-answer records (all question types)."""
    return [
        record
        for record in records
        if record.graph_arm == "graph-off"
        and record.outcome == "success"
        and record.answer
    ]


def build_report(journal_path: Path, corpus_name: str = DEFAULT_CORPUS) -> str:
    """Computes the D-74/D-69 retro and returns it as markdown text.

    Never writes any file itself — `main` is the only caller that persists
    the result, to the `--out` path.
    """
    questions = {q.question_id: q for q in load_sample_questions(corpus_name)}
    records = load_records(journal_path)

    graph_off_successes = _eligible_graph_off_successes(records, questions)
    non_null_successes = [
        r for r in graph_off_successes if not questions[r.question_id].is_null
    ]
    n = len(non_null_successes)

    label = f"partial-run diagnostic (06.3.4 journal, graph-off successes), n={n}"

    lines: list[str] = [label, ""]
    lines.append(
        "Read-only D-74 attribution baseline over "
        f"`{journal_path}`. Never scored, never published as a complete run "
        "(OBS-05). The 06.3.4 and 2026-09-03 EM/Token-F1 numbers are "
        "NON-COMPARABLE with any run made after this phase's index/prompt/"
        "seeding changes (06.3.1 D-43 pattern) and are not reproduced here."
    )
    lines.append("")

    # --- Whole-token vs substring containment ---
    whole_token_hits = sum(
        gold_contained(questions[r.question_id].gold_answer, r.answer)
        for r in non_null_successes
    )
    substring_hits = sum(
        substring_contained(questions[r.question_id].gold_answer, r.answer)
        for r in graph_off_successes
    )
    _, wt_lo, wt_hi = wilson_ci(whole_token_hits, n) if n else (0.0, 0.0, 0.0)

    lines.append("## Containment (D-74)")
    lines.append(
        f"- Whole-token containment (full answer, non-null): {whole_token_hits}/{n} "
        f"(Wilson 95% CI [{wt_lo:.3f}, {wt_hi:.3f}])"
    )
    lines.append(
        f"- Character-substring containment (all graph-off successes, incl. null): "
        f"{substring_hits}/{len(graph_off_successes)}"
    )

    lines.append("")
    lines.append("### By question_type (whole-token)")
    by_type: dict[str, list[int]] = {}
    for record in non_null_successes:
        question = questions[record.question_id]
        counts = by_type.setdefault(question.question_type, [0, 0])
        counts[1] += 1
        if gold_contained(question.gold_answer, record.answer):
            counts[0] += 1
    for question_type, (hits, total) in sorted(by_type.items()):
        _, lo, hi = wilson_ci(hits, total) if total else (0.0, 0.0, 0.0)
        lines.append(f"- {question_type}: {hits}/{total} (CI [{lo:.3f}, {hi:.3f}])")

    # --- Answer: line presence (D-71 predates this journal) ---
    answer_line_count = sum(
        1 for r in graph_off_successes if _has_answer_line(r.answer)
    )
    lines.append("")
    lines.append("### `Answer:` line presence")
    lines.append(
        f"- {answer_line_count}/{len(graph_off_successes)} graph-off successes "
        "contain an `Answer:` line — this journal predates the D-71 prompt "
        "change, so 0 is expected."
    )

    # --- Stricter proxy: drop hits whose gold ('no') already echoes the question ---
    stricter_hits = 0
    dropped_echoes = 0
    for record in non_null_successes:
        question = questions[record.question_id]
        is_hit = gold_contained(question.gold_answer, record.answer)
        if not is_hit:
            continue
        gold_norm = squad_normalize(question.gold_answer)
        if gold_norm == "no" and gold_contained("no", question.question):
            dropped_echoes += 1
            continue
        stricter_hits += 1
    _, st_lo, st_hi = wilson_ci(stricter_hits, n) if n else (0.0, 0.0, 0.0)
    lines.append("")
    lines.append(
        "### Stricter proxy (drops `no`-gold hits already echoed in the question)"
    )
    lines.append(
        f"- {stricter_hits}/{n} ({dropped_echoes} whole-token hits dropped as "
        f"question-echoes) (Wilson 95% CI [{st_lo:.3f}, {st_hi:.3f}])"
    )

    # --- D-69 baseline over records that reached GenerateAnswer ---
    reached = [r for r in records if _reached_generate_answer(r)]
    reached_null = [r for r in reached if questions[r.question_id].is_null]
    reached_non_null = [
        r for r in reached if not questions[r.question_id].is_null
    ]

    rejections = [
        (r, _generate_answer_rejection_class(r))
        for r in reached
        if _generate_answer_rejection_class(r) is not None
    ]
    rejections_null = [
        r for r, _ in rejections if questions[r.question_id].is_null
    ]
    rejections_non_null = [
        r for r, _ in rejections if not questions[r.question_id].is_null
    ]

    lines.append("")
    lines.append("## D-69 citation-constraint baseline")
    lines.append(
        "Recorded under `--retries 2`; only the LAST attempt is journaled "
        "(`run.py:87-215`), so this is a LOWER BOUND on the single-attempt "
        "(`--retries 0`) rejection rate."
    )
    lines.append(
        f"- Total: {len(rejections)}/{len(reached)} records that reached "
        f"GenerateAnswer (null {len(rejections_null)}/{len(reached_null)}, "
        f"non-null {len(rejections_non_null)}/{len(reached_non_null)})"
    )

    d69_classes = (
        "citation_basis_mixed",
        "citation_basis_retrieval",
        "model_only_unsupported",
    )

    class_counts = Counter(cls for _, cls in rejections)
    lines.append("")
    lines.append("### By class")
    for cls in d69_classes:
        lines.append(f"- {cls}: {class_counts.get(cls, 0)}")

    class_arm_counts = Counter((cls, r.graph_arm) for r, cls in rejections)
    lines.append("")
    lines.append("### By class and arm")
    for cls in d69_classes:
        for arm in ("graph-off", "graph-on"):
            count = class_arm_counts.get((cls, arm), 0)
            if count:
                lines.append(f"- {cls} / {arm}: {count}")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: writes the retro markdown to `--out`."""
    parser = argparse.ArgumentParser(
        description=(
            "D-74 read-only retro over a committed journal "
            "(never scores, never publishes)."
        )
    )
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--corpus", default=DEFAULT_CORPUS)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    report = build_report(args.journal, args.corpus)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(report)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
