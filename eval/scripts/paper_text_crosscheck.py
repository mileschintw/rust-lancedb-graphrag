"""D-102 text-rule cross-check of the paper metrics (AI-SPEC section 5 #5, read-only).

The four-arm report scores the MultiHop-RAG paper metrics under the ID rule: a ranked
chunk is relevant to a gold fact when its ID is in the fact's `gold_chunks.jsonl` set.
The official script (`yixuantt/MultiHop-RAG` at `metrics.OFFICIAL_COMMIT`) instead
matches by text: a fact is relevant to a chunk when it is a substring of the chunk's
text with spaces and newlines removed. This script recomputes the same metrics under
the text rule over the chunk text the engine ranked, and counts where the two rules
disagree, so the primary can be checked for robustness to the matching rule.

Two modes, both read-only:

* `--emit-ids PATH` lists the distinct chunk IDs of every record's
  `pre_truncation_ranking[:10]` as `{"chunk_id": ...}` lines and prints the single
  `index_generation`. Feed that file to `inspect_lancedb --chunk-text IDS --generation
  <index_generation>` to dump the chunk text at the drive's table version.
* The main mode reads that dump, the sample's gold facts, the split and the gold-chunk
  table, and writes `--out` (`diagnostic/text_crosscheck.json`): per-record text-rule
  verdicts and per-arm disagreement counts against the ID rule, over P4 and over the
  script-faithful population. It exits non-zero, writing nothing, when a ranked ID is
  missing from the dump (exit 3) or when a final-eight excerpt in the journal is not
  the engine's bounded excerpt of the dumped text (exit 4, the store-drift tripwire).

The output holds rank positions, 0/1 values and chunk IDs only. It never holds chunk
text, and no error message prints any. This script never imports `lancet_eval.score` or
`lancet_eval.report`, opens no subprocess and writes no path but the one it is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from lancet_eval import provenance
from lancet_eval.arms import ARM_REGISTRY, canonical_arm
from lancet_eval.corpus import LABEL_ADAPTERS
from lancet_eval.journal import RunRecord, load_records
from lancet_eval.metrics import (
    OFFICIAL_COMMIT,
    id_matcher,
    load_gold_chunk_sets,
    paper_metrics,
    paper_question_scores,
    text_matcher,
)
from lancet_eval.p4 import build_p4
from lancet_eval.pairing import deduplicate_by_arm
from lancet_eval.split import load_split

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUESTIONS = (
    REPO_ROOT / "eval" / "corpora" / "multihop_rag" / "questions.sample.jsonl"
)
# `engine.retrieval.excerpt_max_chars` (config/config.toml, engine/src/config.rs): the
# engine keeps the first N Unicode code points of a chunk as the
# `retrieved_chunks[].excerpt`
# (`prompt::bounded_unicode_excerpt`), and sets `is_truncated` when the chunk is longer.
DEFAULT_EXCERPT_MAX_CHARS = 512
RANK_CUTOFF = 10
_AP_TOLERANCE = 1e-12

EXIT_OK = 0
EXIT_INPUT = 2
EXIT_MISSING_ID = 3
EXIT_DRIFT = 4
_LISTED = 20


class CrosscheckError(Exception):
    """A refusal with its exit status. The message names IDs only, never chunk text."""

    def __init__(self, message: str, exit_code: int = EXIT_INPUT) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _ranked_ids(rec: RunRecord) -> list[str]:
    """The first ten chunk IDs of the D-100 pre-truncation ranking."""
    if rec.snapshot is None:
        return []
    return [c.chunk_id for c in rec.snapshot.pre_truncation_ranking[:RANK_CUTOFF]]


def _single_generation(records: list[RunRecord]) -> str:
    generations = {r.index_generation for r in records if r.index_generation}
    if not generations:
        raise CrosscheckError("no record carries an index_generation")
    if len(generations) > 1:
        raise CrosscheckError(
            f"mixed index generations in the journal: {sorted(generations)}"
        )
    return next(iter(generations))


def emit_ids(journal_path: Path, out_path: Path) -> str:
    """Writes the distinct ranked chunk IDs of the journal and returns its generation.

    Args:
        journal_path: The closed drive journal (read-only).
        out_path: JSONL file of `{"chunk_id": ...}` lines, in first-seen order.

    Returns:
        The journal's single `index_generation`.

    Raises:
        CrosscheckError: If the journal has no generation or mixed generations.
    """
    records, _ = deduplicate_by_arm(load_records(journal_path))
    generation = _single_generation(records)
    seen: dict[str, None] = {}
    for rec in records:
        for chunk_id in _ranked_ids(rec):
            seen.setdefault(chunk_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for chunk_id in seen:
            f.write(json.dumps({"chunk_id": chunk_id}) + "\n")
    return generation


def load_dump(path: Path) -> dict[str, str]:
    """Reads the `--chunk-text` dump and checks each row's `content_sha256`.

    Raises:
        CrosscheckError: On a malformed row or a text that does not match its digest
            (the message names the line or the chunk ID, never the text).
    """
    texts: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                chunk_id, text, digest = (
                    row["chunk_id"],
                    row["text"],
                    row["content_sha256"],
                )
            except (ValueError, KeyError, TypeError) as exc:
                raise CrosscheckError(f"dump line {line_no} is malformed") from exc
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
                raise CrosscheckError(
                    f"dump text of chunk {chunk_id!r} does not match its content_sha256"
                )
            texts[chunk_id] = text
    return texts


def load_facts(path: Path) -> dict[str, list[str]]:
    """The raw `evidence_list[].fact` strings of each question, in order.

    The official script averages over every evidence entry and divides by
    `min(len(gold), 10)`, so the strings are kept exactly as written: an empty or
    padded fact is not dropped here, unlike `GoldQuestion.gold_facts`.

    Raises:
        CrosscheckError: If an evidence entry has no `fact` key.
    """
    adapt = LABEL_ADAPTERS["multihop_rag"]
    facts: dict[str, list[str]] = {}
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            raw = json.loads(line)
            qid = adapt(raw).question_id
            entries = raw.get("evidence_list") or []
            try:
                facts[qid] = [str(entry["fact"]) for entry in entries]
            except (KeyError, TypeError) as exc:
                raise CrosscheckError(
                    f"question {qid!r} (line {line_no}) has an evidence entry "
                    "without a fact"
                ) from exc
    return facts


def _first_rank(scores: dict[str, Any]) -> int | None:
    rr = float(scores["rr"])
    return round(1 / rr) if rr > 0 else None


def _verdict(prefix: str, scores: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{prefix}_hit4": int(bool(scores["hit4"])),
        f"{prefix}_hit10": int(bool(scores["hit10"])),
        f"{prefix}_first_hit_rank": _first_rank(scores),
        f"{prefix}_ap": float(scores["ap"]),
    }


def _check_store(
    records: list[RunRecord],
    dump: dict[str, str],
    excerpt_max_chars: int,
) -> None:
    """The store-drift tripwire: ranked IDs exist and excerpts match the dumped text."""
    missing: set[str] = set()
    for rec in records:
        if rec.snapshot is None:
            continue
        missing.update(c for c in _ranked_ids(rec) if c not in dump)
        missing.update(
            c.chunk_id
            for c in rec.snapshot.retrieved_chunks
            if c.chunk_id not in dump
        )
    if missing:
        listed = ", ".join(sorted(missing)[:_LISTED])
        raise CrosscheckError(
            f"{len(missing)} ranked chunk ID(s) missing from the dump: {listed}",
            EXIT_MISSING_ID,
        )
    drift: list[str] = []
    for rec in records:
        if rec.snapshot is None:
            continue
        for chunk in rec.snapshot.retrieved_chunks:
            text = dump[chunk.chunk_id]
            expected = text[:excerpt_max_chars]
            if chunk.excerpt != expected or chunk.is_truncated != (
                len(text) > excerpt_max_chars
            ):
                drift.append(f"{chunk.chunk_id} ({rec.question_id}/{rec.graph_arm})")
    if drift:
        raise CrosscheckError(
            f"{len(drift)} final-eight excerpt(s) do not match the dumped chunk text "
            f"(store drift): {', '.join(sorted(drift)[:_LISTED])}",
            EXIT_DRIFT,
        )


def _arm_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Disagreement counts and both rules' averages over one arm's records."""
    id_scores = [e["_id_scores"] for e in entries]
    text_scores = [e["_text_scores"] for e in entries]
    out: dict[str, Any] = {"n": len(entries)}
    for key in ("hit4", "hit10", "first_hit_rank", "ap"):
        out[f"disagree_{key}"] = sum(1 for e in entries if e[f"disagree_{key}"])
    if entries:
        out["id_rule"] = paper_metrics(id_scores)
        out["text_rule"] = paper_metrics(text_scores)
    return out


def build_crosscheck(
    *,
    journal_path: Path,
    split_path: Path,
    gold_chunks_path: Path,
    questions_path: Path,
    dump_path: Path,
    excerpt_max_chars: int = DEFAULT_EXCERPT_MAX_CHARS,
) -> dict[str, Any]:
    """Computes the text-rule verdicts and the per-arm disagreement counts.

    Args:
        journal_path: The closed drive journal (read-only).
        split_path: The committed held-out split.
        gold_chunks_path: `gold_chunks.jsonl` (the ID rule's gold sets).
        questions_path: The question sample holding `evidence_list[].fact`.
        dump_path: The `inspect_lancedb --chunk-text` dump at the drive's generation.
        excerpt_max_chars: The engine's excerpt bound in Unicode code points.

    Returns:
        The JSON-serialisable result: no chunk text, only IDs, ranks and 0/1 values.

    Raises:
        CrosscheckError: On a missing ID (exit 3), store drift (exit 4) or bad input
            (exit 2).
    """
    split = load_split(split_path)
    gold_sets = load_gold_chunk_sets(gold_chunks_path)
    facts = load_facts(questions_path)
    dump = load_dump(dump_path)
    g_ids = list(split.heldout_g_ids)
    for qid in g_ids:
        if not gold_sets.get(qid):
            raise CrosscheckError(f"held-out G question {qid!r} has no gold-chunk row")
        if not facts.get(qid):
            raise CrosscheckError(f"held-out G question {qid!r} has no gold fact")

    records, _ = deduplicate_by_arm(load_records(journal_path))
    g_set = set(g_ids)
    g_records = [r for r in records if r.question_id in g_set]
    generation = _single_generation(g_records)
    _check_store(g_records, dump, excerpt_max_chars)

    present = {canonical_arm(r.graph_arm) for r in g_records}
    arms = [a for a in ARM_REGISTRY if a in present]
    try:
        pop = build_p4(g_records, split, arms)
    except ValueError as exc:
        raise CrosscheckError(f"cannot build P4: {exc}") from exc
    p4_ids = set(pop.question_ids)
    index = {(r.question_id, canonical_arm(r.graph_arm)): r for r in g_records}

    entries: list[dict[str, Any]] = []
    for arm in arms:
        for qid in sorted(g_ids):
            rec = index.get((qid, arm))
            valid = (
                rec is not None
                and rec.snapshot is not None
                and rec.snapshot.result_hash != ""
                and provenance.is_ok(rec)
            )
            ids = _ranked_ids(rec) if valid and rec is not None else []
            id_scores = paper_question_scores(ids, gold_sets[qid], id_matcher)
            text_scores = paper_question_scores(
                [dump[i] for i in ids], facts[qid], text_matcher
            )
            entry: dict[str, Any] = {
                "question_id": qid,
                "arm": arm,
                "in_p4": qid in p4_ids,
                "valid_ranking": bool(valid),
                **_verdict("text", text_scores),
                **_verdict("id", id_scores),
            }
            entry["disagree_hit4"] = entry["text_hit4"] != entry["id_hit4"]
            entry["disagree_hit10"] = entry["text_hit10"] != entry["id_hit10"]
            entry["disagree_first_hit_rank"] = (
                entry["text_first_hit_rank"] != entry["id_first_hit_rank"]
            )
            entry["disagree_ap"] = (
                abs(entry["text_ap"] - entry["id_ap"]) > _AP_TOLERANCE
            )
            entry["_id_scores"] = id_scores
            entry["_text_scores"] = text_scores
            entries.append(entry)

    per_arm: dict[str, Any] = {}
    text_hit4: dict[str, dict[str, int]] = {}
    for arm in arms:
        arm_entries = [e for e in entries if e["arm"] == arm]
        p4_entries = [e for e in arm_entries if e["in_p4"]]
        script = _arm_summary(arm_entries)
        script["n_no_valid_ranking"] = sum(
            1 for e in arm_entries if not e["valid_ranking"]
        )
        per_arm[arm] = {"p4": _arm_summary(p4_entries), "script_faithful": script}
        text_hit4[arm] = {e["question_id"]: e["text_hit4"] for e in p4_entries}

    for entry in entries:
        del entry["_id_scores"]
        del entry["_text_scores"]
    return {
        "index_generation": generation,
        "official_commit": OFFICIAL_COMMIT,
        "excerpt_max_chars": excerpt_max_chars,
        "n_heldout_g": len(g_ids),
        "n_p4": len(p4_ids),
        "p4_question_ids": sorted(p4_ids),
        "records": entries,
        "arms": per_arm,
        "per_arm_text_hit4_p4": text_hit4,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit status."""
    parser = argparse.ArgumentParser(
        description=(
            "D-102 text-rule cross-check of the paper metrics (read-only; writes "
            "only --out, or --emit-ids)."
        )
    )
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--emit-ids", dest="emit_ids", type=Path)
    parser.add_argument("--split", type=Path)
    parser.add_argument("--gold-chunks", dest="gold_chunks", type=Path)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--dump", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--excerpt-max-chars",
        dest="excerpt_max_chars",
        type=int,
        default=DEFAULT_EXCERPT_MAX_CHARS,
    )
    args = parser.parse_args(argv)
    try:
        if args.emit_ids is not None:
            generation = emit_ids(args.journal, args.emit_ids)
            print(f"index_generation: {generation}")
            return EXIT_OK
        required = {
            "--split": args.split,
            "--gold-chunks": args.gold_chunks,
            "--dump": args.dump,
            "--out": args.out,
        }
        absent = [flag for flag, value in required.items() if value is None]
        if absent:
            parser.error(f"the main mode needs {', '.join(absent)}")
        result = build_crosscheck(
            journal_path=args.journal,
            split_path=args.split,
            gold_chunks_path=args.gold_chunks,
            questions_path=args.questions,
            dump_path=args.dump,
            excerpt_max_chars=args.excerpt_max_chars,
        )
    except CrosscheckError as exc:
        print(f"paper_text_crosscheck: {exc}", file=sys.stderr)
        return exc.exit_code
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.out}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
