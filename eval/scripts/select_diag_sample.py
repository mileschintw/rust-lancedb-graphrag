"""Freezes G/V (D-63/D-82) and draws the reproducible diagnostic sample (D-68).

Reads only the committed `questions.sample.jsonl`, the `--gold-chunks`/
`--vector-top4` probe outputs (already committed by 06.3.4.1-09), and
`document_map.json`. Writes `questions.diag.jsonl`, `diag_selection.json`, and
the sibling `multihop_rag_diag.toml` corpus config that points at them through
the `[documents] map_corpus` indirection (D-68), so a diagnostic drive can
share the one seeded store without its own copy of `document_map.json`.

Deterministic: two runs over the same inputs produce byte-identical
`questions.diag.jsonl` and `diag_selection.json` (repudiation control,
T-06.3.4.1-10-03). Never writes to LanceDB, PostgreSQL, or any live store --
every write here is a plain file under `eval/corpora/`.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from lancet_eval.config import repo_root
from lancet_eval.corpus import sample_questions
from lancet_eval.diagnostic import build_rows, compute_populations
from lancet_eval.seed import load_document_map

CORPUS_NAME = "multihop_rag"
DIAG_CORPUS_NAME = "multihop_rag_diag"
NON_NULL_SAMPLE_TARGET = 90
MIN_DRAWN_NON_NULL_IN_G = 60
NULL_QUESTION_TYPE = "null_query"


class SelectionError(Exception):
    """Raised when the diagnostic sample cannot be drawn as specified (D-68)."""


def _question_id_of(raw: dict[str, Any]) -> str:
    return str(raw.get("question_id") or raw.get("query_id") or raw.get("id") or "")


def _load_raw_questions(questions_path: Path) -> list[dict[str, Any]]:
    """Parses every non-blank line of a `questions.sample.jsonl`-shaped file."""
    raw_questions: list[dict[str, Any]] = []
    with open(questions_path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                raw_questions.append(json.loads(stripped))
    return raw_questions


def _load_raw_lines_by_id(questions_path: Path) -> dict[str, str]:
    """Maps question_id -> the exact original line text (verbatim, no newline).

    `questions.diag.jsonl` is written from these original lines, never from a
    re-serialization of the parsed dict, so it stays byte-identical to its
    source line in `questions.sample.jsonl`.
    """
    by_id: dict[str, str] = {}
    with open(questions_path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            qid = _question_id_of(json.loads(stripped))
            if qid:
                by_id[qid] = stripped
    return by_id


def largest_remainder_quotas(
    strata_counts: dict[str, int], total: int
) -> dict[str, int]:
    """Largest-remainder (Hamilton) proportional allocation of `total` seats.

    Deterministic: a tie in the fractional remainder breaks on the stratum
    name (lexicographic), never on dict/set iteration order or randomness.
    """
    if total < 0:
        raise SelectionError(f"Cannot allocate a negative total of {total}")
    denominator = sum(strata_counts.values())
    if denominator == 0:
        raise SelectionError("Cannot allocate quotas over an empty population")

    exact_shares = {
        name: total * count / denominator for name, count in strata_counts.items()
    }
    quotas = {name: int(share) for name, share in exact_shares.items()}
    remainder = total - sum(quotas.values())
    ranked = sorted(
        strata_counts,
        key=lambda name: (-(exact_shares[name] - quotas[name]), name),
    )
    for name in ranked[:remainder]:
        quotas[name] += 1
    return quotas


def build_selection(
    corpus_name: str,
    gold_chunks_path: str | Path,
    vector_top4_path: str | Path,
    *,
    include_nulls: int,
    seed: int,
) -> dict[str, Any]:
    """Computes G/V and draws the sample; returns the `diag_selection.json` payload.

    Relies only on `lancet_eval.diagnostic.build_rows`/`compute_populations`
    (D-63/D-82's one shared definition of G/V) and
    `lancet_eval.corpus.sample_questions` (the one committed sampling rule,
    D-68) -- no ground truth is re-derived here.
    """
    if include_nulls not in (0, 10):
        raise SelectionError(f"--include-nulls must be 0 or 10, got {include_nulls}")

    corpus_dir = repo_root() / "eval" / "corpora" / corpus_name
    questions_path = corpus_dir / "questions.sample.jsonl"

    rows = build_rows(corpus_name, None, gold_chunks_path, vector_top4_path)
    populations = compute_populations(rows)
    g_ids: set[str] = set(populations["g_question_ids"])
    v_ids: set[str] = set(populations["v_question_ids"])
    strata_counts_in_g: dict[str, int] = dict(populations["g_by_type"])

    raw_questions = _load_raw_questions(questions_path)
    quotas = largest_remainder_quotas(strata_counts_in_g, NON_NULL_SAMPLE_TARGET)

    drawn_ids: list[str] = []
    shortfalls: dict[str, int] = {}
    for stratum in sorted(strata_counts_in_g):
        pool = [
            raw
            for raw in raw_questions
            if raw.get("question_type") == stratum
            and _question_id_of(raw) in g_ids
        ]
        quota = quotas.get(stratum, 0)
        if len(pool) < quota:
            shortfalls[stratum] = quota - len(pool)
            quota = len(pool)
        drawn = sample_questions(pool, quota, seed)
        drawn_ids.extend(_question_id_of(raw) for raw in drawn)

    non_null_drawn = len(drawn_ids)
    if non_null_drawn < MIN_DRAWN_NON_NULL_IN_G:
        raise SelectionError(
            f"Only {non_null_drawn} non-null questions drawn into G "
            f"(minimum {MIN_DRAWN_NON_NULL_IN_G}); refusing to widen silently -- "
            "this needs a user decision before drive 1 (D-68)."
        )

    if include_nulls:
        null_pool = [
            raw
            for raw in raw_questions
            if raw.get("question_type") == NULL_QUESTION_TYPE
        ]
        drawn_nulls = sample_questions(null_pool, include_nulls, seed)
        drawn_ids.extend(_question_id_of(raw) for raw in drawn_nulls)

    drawn_ids = sorted(drawn_ids)
    if len(set(drawn_ids)) != len(drawn_ids):
        raise SelectionError(
            "Drawn question_ids are not unique -- refusing to write a corrupt selection"
        )

    doc_map = load_document_map(corpus_name)

    return {
        "method": (
            "corpus.sample_questions per stratum (sort-by-id, "
            "random.Random(seed).sample, re-sort), quotas via largest-remainder "
            f"proportional allocation of {NON_NULL_SAMPLE_TARGET} over G's actual "
            "per-question_type counts (D-68)"
        ),
        "seed": seed,
        "quotas": quotas,
        "strata_counts_in_G": strata_counts_in_g,
        "shortfalls": shortfalls,
        "drawn_question_ids": drawn_ids,
        "g_question_ids": sorted(g_ids),
        "v_question_ids": sorted(v_ids),
        "g_size": len(g_ids),
        "v_size": len(v_ids),
        "null_included": include_nulls,
        "source_index_generation": doc_map.index_generation,
        "date": date.today().isoformat(),
    }


def build_diag_corpus_toml(source_lines: list[str], drawn_count: int) -> str:
    """Builds `multihop_rag_diag.toml`'s content from `multihop_rag.toml`'s lines.

    Repoints `[questions] file` at the diagnostic sample, sets `sample_size` to
    the drawn count, and ensures `label_format` is pinned to the source
    corpus's own name -- overwriting it in place if the source already sets
    one (as `multihop_rag.toml` does), or inserting it right after `file` if
    not. Either way this must never default: an unset `label_format` falls
    back to the corpus's own name (`multihop_rag_diag`), which has no
    `LABEL_ADAPTERS` entry and crashes `CorpusConfig.adapter`. Also adds
    `[documents] map_corpus` so the diagnostic corpus shares the one committed
    document map instead of carrying a copy (D-68's prohibition).
    """
    has_label_format = any(
        line.strip().startswith("label_format") for line in source_lines
    )
    out: list[str] = []
    section = ""
    for line in source_lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            out.append(line)
            if section == "documents":
                out.append(f'map_corpus = "{CORPUS_NAME}"')
            continue
        if section == "questions" and stripped.startswith("file ="):
            out.append(f'file = "{CORPUS_NAME}/questions.diag.jsonl"')
            if not has_label_format:
                out.append(f'label_format = "{CORPUS_NAME}"')
            continue
        if section == "questions" and stripped.startswith("label_format"):
            out.append(f'label_format = "{CORPUS_NAME}"')
            continue
        if section == "questions" and stripped.startswith("sample_size ="):
            out.append(f"sample_size = {drawn_count}")
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: `python eval/scripts/select_diag_sample.py --gold-chunks ...`"""
    parser = argparse.ArgumentParser(prog="select_diag_sample")
    parser.add_argument("--gold-chunks", dest="gold_chunks", required=True)
    parser.add_argument("--vector-top4", dest="vector_top4", required=True)
    parser.add_argument(
        "--include-nulls",
        dest="include_nulls",
        type=int,
        choices=(0, 10),
        default=10,
    )
    parser.add_argument("--seed", dest="seed", type=int, default=42)
    args = parser.parse_args(argv)

    try:
        selection = build_selection(
            CORPUS_NAME,
            args.gold_chunks,
            args.vector_top4,
            include_nulls=args.include_nulls,
            seed=args.seed,
        )
    except SelectionError as exc:
        print(f"select_diag_sample: {exc}", flush=True)
        return 1

    corpus_dir = repo_root() / "eval" / "corpora" / CORPUS_NAME
    questions_sample_path = corpus_dir / "questions.sample.jsonl"
    lines_by_id = _load_raw_lines_by_id(questions_sample_path)

    diag_questions_path = corpus_dir / "questions.diag.jsonl"
    with open(diag_questions_path, "w", encoding="utf-8", newline="\n") as f:
        for qid in selection["drawn_question_ids"]:
            f.write(lines_by_id[qid])
            f.write("\n")

    selection_path = corpus_dir / "diag_selection.json"
    with open(selection_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(selection, f, indent=2)
        f.write("\n")

    source_toml_path = repo_root() / "eval" / "corpora" / f"{CORPUS_NAME}.toml"
    diag_toml_path = repo_root() / "eval" / "corpora" / f"{DIAG_CORPUS_NAME}.toml"
    source_lines = source_toml_path.read_text(encoding="utf-8").splitlines()
    diag_toml_content = build_diag_corpus_toml(
        source_lines, len(selection["drawn_question_ids"])
    )
    with open(diag_toml_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(diag_toml_content)

    print(
        f"select_diag_sample: g_size={selection['g_size']} "
        f"v_size={selection['v_size']} "
        f"drawn={len(selection['drawn_question_ids'])} "
        f"quotas={selection['quotas']} shortfalls={selection['shortfalls']} "
        f"null_included={selection['null_included']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
