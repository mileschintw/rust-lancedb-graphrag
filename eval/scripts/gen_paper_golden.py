"""D-102 golden-vector generator: official MultiHop-RAG ``calculate_metrics`` outputs.

Writes ``eval/tests/fixtures/multihop_rag_calculate_metrics_golden.json`` from a
local copy of the official ``retrieval_evaluate.py`` at
``yixuantt/MultiHop-RAG@c1c1287aa60a94acf9c4d20c891c9cd611a0f6e8``.

The official file is NEVER committed to this repository: its licence has not been
checked. Fetch it outside the repository (a scratch or ``$TEMP`` directory), for
example::

    https://raw.githubusercontent.com/yixuantt/MultiHop-RAG/c1c1287aa60a94acf9c4d20c891c9cd611a0f6e8/retrieval_evaluate.py

then run ``python eval/scripts/gen_paper_golden.py --official <that path>``. Only the
generated JSON (inputs plus the official outputs, with the commit and the file's
sha256 in its header) is committed.

Every per-question value comes straight from the official function, called with
single-question lists. The generator uses only the standard library, so it runs
without the evaluation package installed. Cases are drawn from a seeded
``random.Random(42)``.

Duplicate gold facts are the one input where an index-tracked "found" set differs
from the official function, which tracks found facts by their stripped text (two
identical facts count once in the numerator and twice in the divisor). The random
cases therefore drop any question with a duplicate fact; a fact that merely sits
inside another fact is kept, because both implementations agree on it.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import sys
from pathlib import Path
from typing import Any

OFFICIAL_REPO = "yixuantt/MultiHop-RAG"
OFFICIAL_COMMIT = "c1c1287aa60a94acf9c4d20c891c9cd611a0f6e8"
OFFICIAL_FILE = "retrieval_evaluate.py"
SEED = 42
RANDOM_TRIALS = 240
DEFAULT_OUT = Path("eval/tests/fixtures/multihop_rag_calculate_metrics_golden.json")

_WORDS = "alpha beta gamma delta eps zeta eta theta iota kappa lam mu".split()


def strip_ws(text: str) -> str:
    """The official normalisation: drop every space and newline."""
    return text.replace(" ", "").replace("\n", "")


def load_official(path: Path) -> Any:
    """Imports the official module from a local file path."""
    spec = importlib.util.spec_from_file_location("official_retrieval_evaluate", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path} as a Python module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "calculate_metrics"):
        raise SystemExit(f"{path} defines no calculate_metrics")
    return module


def textbook_ap(ranked_texts: list[str], facts: list[str]) -> float:
    """Textbook-style AP: cumulative distinct facts found over the rank.

    Used only as the negative control: it is NOT what the official script computes.
    """
    gold = [strip_ws(f) for f in facts]
    found: set[str] = set()
    total = 0.0
    for rank, text in enumerate(ranked_texts[:10], start=1):
        body = strip_ws(text)
        hit = [g for g in gold if g in body]
        if hit:
            found.update(hit)
            total += len(found) / rank
    return total / min(len(gold), 10)


def build_case(
    official: Any,
    case_id: str,
    kind: str,
    chunks: dict[str, str],
    ranked_ids: list[str],
    facts: list[str],
) -> dict[str, Any]:
    """One fixture case: the inputs in both forms plus the official outputs."""
    ranked_texts = [chunks[c] for c in ranked_ids]
    got = official.calculate_metrics([ranked_texts], [facts])
    gold_id_sets = [
        sorted(c for c, t in chunks.items() if strip_ws(f) in strip_ws(t))
        for f in facts
    ]
    return {
        "id": case_id,
        "kind": kind,
        "ranked_ids": ranked_ids,
        "ranked_texts": ranked_texts,
        "facts": facts,
        "gold_id_sets": gold_id_sets,
        "official": {
            "hit4": got["Hits@4"],
            "hit10": got["Hits@10"],
            "mrr": got["MRR@10"],
            "map": got["MAP@10"],
        },
    }


def _has_duplicate_fact(facts: list[str]) -> bool:
    return len({strip_ws(f) for f in facts}) < len(facts)


def _random_cases(official: Any, rng: random.Random) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    while len(cases) < RANDOM_TRIALS:
        chunks = {
            f"c{i}": " ".join(rng.choice(_WORDS) for _ in range(12)) for i in range(40)
        }
        facts: list[str] = []
        for _ in range(rng.randint(1, 4)):
            src = chunks[rng.choice(list(chunks))].split()
            start = rng.randint(0, 8)
            facts.append(" ".join(src[start : start + rng.randint(3, 4)]))
        if _has_duplicate_fact(facts):
            continue
        # Facts with an embedded newline exercise the newline strip in the text form.
        if rng.random() < 0.3:
            facts[0] = facts[0].replace(" ", "\n", 1)
        ranked = rng.sample(list(chunks), rng.randint(0, 14))
        if rng.random() < 0.6:
            gold_chunks = [
                c
                for c, t in chunks.items()
                if any(strip_ws(f) in strip_ws(t) for f in facts)
            ]
            for c in rng.sample(gold_chunks, min(len(gold_chunks), rng.randint(1, 3))):
                if c not in ranked:
                    ranked.insert(rng.randint(0, len(ranked)), c)
        cases.append(
            build_case(
                official, f"random-{len(cases):03d}", "random", chunks, ranked, facts
            )
        )
    return cases


def _special_cases(official: Any) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    # Negative control: facts found at ranks 1 and 2 give official AP 0.75 and a
    # textbook AP of 1.0.
    chunks = {
        "n1": "first unique fact stands here",
        "n2": "second unique fact stands here",
        "n3": "filler words only",
    }
    facts = ["first unique fact", "second unique fact"]
    case = build_case(
        official,
        "negative-control",
        "negative_control",
        chunks,
        ["n1", "n2", "n3"],
        facts,
    )
    case["textbook_ap"] = textbook_ap(case["ranked_texts"], facts)
    cases.append(case)

    # An empty gold unit: a fact split across two chunks is a substring of neither.
    chunks = {
        "s1": "opening words splitleft",
        "s2": "splitright closing words",
        "s3": "only the first unit lives here",
    }
    facts = ["only the first unit", "splitleft splitright"]
    cases.append(
        build_case(
            official,
            "empty-gold-unit",
            "empty_gold_unit",
            chunks,
            ["s3", "s1", "s2"],
            facts,
        )
    )

    # A hit only at rank 11 never counts.
    chunks = {f"r{i}": f"filler{i} text{i} words{i}" for i in range(11)}
    chunks["r10"] = "the lone gold fact sits at rank eleven"
    cases.append(
        build_case(
            official,
            "rank-11-only",
            "rank_11",
            chunks,
            [f"r{i}" for i in range(11)],
            ["the lone gold fact"],
        )
    )

    # Boundary ranks: first hit exactly at rank 4 and exactly at rank 10.
    for rank in (4, 5, 10):
        chunks = {f"b{i}": f"filler{i} text{i} words{i}" for i in range(rank)}
        chunks[f"b{rank - 1}"] = f"the boundary fact {rank} is here"
        cases.append(
            build_case(
                official,
                f"first-hit-rank-{rank}",
                "boundary",
                chunks,
                [f"b{i}" for i in range(rank)],
                [f"the boundary fact {rank}"],
            )
        )

    # An empty ranking is a miss, not an error.
    cases.append(
        build_case(
            official,
            "empty-ranking",
            "empty_ranking",
            {"e1": "some text"},
            [],
            ["some text"],
        )
    )
    return cases


def generate(official_path: Path) -> dict[str, Any]:
    """Builds the whole fixture document from the official file at ``official_path``."""
    official = load_official(official_path)
    rng = random.Random(SEED)
    cases = _special_cases(official) + _random_cases(official, rng)
    return {
        "header": {
            "official_repo": OFFICIAL_REPO,
            "official_commit": OFFICIAL_COMMIT,
            "official_file": OFFICIAL_FILE,
            "official_file_sha256": hashlib.sha256(
                official_path.read_bytes()
            ).hexdigest(),
            "generator": "eval/scripts/gen_paper_golden.py",
            "seed": SEED,
            "n_cases": len(cases),
        },
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    doc = generate(args.official)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(c, sort_keys=True) for c in doc["cases"]]
    header = json.dumps(doc["header"], sort_keys=True)
    body = '{"header": ' + header + ', "cases": [\n' + ",\n".join(lines) + "\n]}\n"
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    print(f"wrote {len(lines)} cases to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
