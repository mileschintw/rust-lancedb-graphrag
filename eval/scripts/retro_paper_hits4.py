"""D-104 read-only retro: paper-convention Hits@4 on the drive-2 journal (dev only).

Computes MultiHop-RAG's own Hits@4 over the usable dev-G records of the committed
drive-2 journal, from ``snapshot.retrieved_chunks[:4]``, under the chunk-ID rule
(a retrieved chunk is relevant to a gold fact when its ID is in that fact's
``gold_chunks.jsonl`` set). It is the free dev baseline 06.3.6 reads. It never
enters a held-out decision (D-106).

This script NEVER imports the fail-closed scorer or report generator, opens no
subprocess, and writes to no path except the markdown file named by ``--out``. The
run directory it reads stays byte-identical (D-74).

Only the rank-4 cut-off is computed: the drive-2 journal holds the final eight chunks,
so ranks 9-10 are absent and nothing beyond rank 4 can be computed from it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lancet_eval.arms import canonical_arm
from lancet_eval.journal import RunRecord, load_records
from lancet_eval.metrics import id_matcher, load_gold_chunk_sets, paper_question_scores
from lancet_eval.stats import wilson_ci
from lancet_eval.usability import is_usable

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOURNAL = (
    REPO_ROOT
    / "eval"
    / "runs"
    / "2026-10-06-drive2-multihop_rag_diag"
    / "journal.jsonl"
)
_POST_RECONCILE = (
    REPO_ROOT
    / ".planning"
    / "phases"
    / "06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair"
    / "diagnostic"
    / "post-reconcile"
)
DEFAULT_GOLD_CHUNKS = _POST_RECONCILE / "gold_chunks.jsonl"
DEFAULT_POPULATIONS = _POST_RECONCILE / "populations.json"

LABEL = "dev-only, paper-convention @4"
HITS_CUTOFF = 4


def _display(path: Path) -> str:
    """A repository-relative posix path when the file is inside the repository."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _arm_name(stored: str) -> str:
    canonical = canonical_arm(stored)
    return canonical if canonical == stored else f"{canonical} (stored {stored})"


def _in_population(record: RunRecord, dev_g: set[str]) -> bool:
    """Usable dev-G record with a retrieval snapshot (the preview's definition)."""
    return (
        record.question_id in dev_g
        and record.outcome == "success"
        and record.snapshot is not None
        and is_usable(record)
    )


def build_report(
    journal_path: Path = DEFAULT_JOURNAL,
    gold_chunks_path: Path = DEFAULT_GOLD_CHUNKS,
    populations_path: Path = DEFAULT_POPULATIONS,
) -> str:
    """Computes the D-104 retro and returns it as markdown text.

    Never writes any file itself: ``main`` is the only caller that persists the
    result, to the ``--out`` path.

    Args:
        journal_path: The drive journal to read (read-only).
        gold_chunks_path: ``gold_chunks.jsonl`` (the D-61 gold-chunk table).
        populations_path: ``populations.json``; its ``g_question_ids`` are dev-G.

    Returns:
        The report. Its first line is ``dev-only, paper-convention @4``.

    Raises:
        KeyError: If a dev-G question has no gold-chunk row (fail closed).
    """
    gold_sets = load_gold_chunk_sets(gold_chunks_path)
    populations = json.loads(populations_path.read_text(encoding="utf-8"))
    dev_g = set(populations["g_question_ids"])
    records = load_records(journal_path)

    lines: list[str] = [LABEL, ""]
    lines.append(
        f"Read-only D-104 retro over `{_display(journal_path)}`. Dev-G records only "
        "(G questions of the diagnostic dev sample, disjoint from the held-out "
        "split): it never enters a held-out decision (D-106), and it is never "
        "scored, never published as a complete run (OBS-05)."
    )
    lines.append("")
    lines.append("## Method")
    lines.append(
        f"- Per record: `retrieved_chunks[:{HITS_CUTOFF}]` chunk IDs against the "
        "question's `gold_chunks` sets, under the chunk-ID rule, with the official "
        "`calculate_metrics` semantics at "
        "yixuantt/MultiHop-RAG@c1c1287aa60a94acf9c4d20c891c9cd611a0f6e8 "
        "(`metrics.paper_question_scores`, proven against golden vectors)."
    )
    lines.append(
        "- Population per stored arm: dev-G question, `outcome == success`, a "
        "retrieval snapshot present, and D-34 usable."
    )
    lines.append(
        "- A `split_across_chunks` fact has an empty gold set and never matches. "
        "A fact whose text also sits in a chunk that `gold_chunks` does not list "
        "counts as a miss under the ID rule but a hit under the official text rule. "
        "That divergence is not measured here."
    )
    lines.append("")
    lines.append("## Hits@4 by arm")
    stored_arms = sorted({r.graph_arm for r in records})
    for stored in stored_arms:
        arm_records = [r for r in records if r.graph_arm == stored]
        selected = [r for r in arm_records if _in_population(r, dev_g)]
        n = len(selected)
        hits = 0
        for record in selected:
            assert record.snapshot is not None
            top4 = [c.chunk_id for c in record.snapshot.retrieved_chunks[:HITS_CUTOFF]]
            scores = paper_question_scores(
                top4, gold_sets[record.question_id], id_matcher
            )
            hits += bool(scores["hit4"])
        p, lo, hi = wilson_ci(hits, n) if n else (0.0, 0.0, 0.0)
        lines.append(
            f"- {_arm_name(stored)}: {hits}/{n} = {p:.4f} "
            f"(Wilson 95% CI [{lo:.3f}, {hi:.3f}])"
        )
        lines.append(
            f"  - {len(arm_records)} journal records, {n} in the population, "
            f"{len(arm_records) - n} left out (not dev-G, or not usable)."
        )
    lines.append("")
    lines.append("## Scope")
    lines.append(
        "The journal holds ranks 1-8 only (the final eight chunks), so ranks 9-10 are "
        "absent. This report computes the rank-4 cut-off alone and reports no "
        "figure that needs a deeper ranking. 06.3.6 reads the baseline above as the "
        "dev reference for the paper convention."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: writes the retro markdown to ``--out``."""
    parser = argparse.ArgumentParser(
        description=(
            "D-104 read-only paper-convention Hits@4 retro over a committed "
            "journal (dev only; never scores, never publishes)."
        )
    )
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--gold-chunks", type=Path, default=DEFAULT_GOLD_CHUNKS)
    parser.add_argument("--populations", type=Path, default=DEFAULT_POPULATIONS)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    report = build_report(args.journal, args.gold_chunks, args.populations)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(report)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
