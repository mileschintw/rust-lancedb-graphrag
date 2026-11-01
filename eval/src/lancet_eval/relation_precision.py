"""Precision of the relations one writer extracts and another does not (#169).

On #117's writer pilot (`experiments/v1.1/writer-pilot`, 1,803 chunks), Haiku 5.5
returns about 40% more relations per chunk than deepseek. A relation is *extra* when its
unordered pair of normalised ends (``writer_pilot._relation_pairs``, the pilot's own
relation Jaccard) is absent from the other writer's answer for the same chunk; only
chunks both writers answered validly count. ``sample`` draws, with a seed, distinct
chunks that have an extra relation and one extra relation from each (stratified by
chunk), for Haiku over deepseek and, as a control, deepseek over Haiku. Each sampled
relation is then judged supported by its chunk's text or not:

- ``judge``: by a cheap non-Claude model on OpenRouter (``JUDGE_MODEL``, temperature 0),
  one sync request per relation, after printing an estimate against ``--ceiling``;
- ``hand``: filled into the sample file by the lane's agent (a Claude model) from a
  shuffled list that hides the writer; not a human's labels.

``report`` prints each writer's precision under each judge (Wilson 95% interval) and
the two judges' agreement. The sample takes one relation per chunk, so a precision is
a mean over chunks, not over relations. It reads committed pilot files and decides
nothing. Run it as ``python -m lancet_eval.relation_precision sample|judge|report``.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from lancet_eval import writer_pilot as wp
from lancet_eval.batch_client import BatchRequest, OpenRouterChatClient
from lancet_eval.stats import wilson_ci

PILOT = Path("experiments") / "v1.1" / "writer-pilot"
SAMPLE = Path("experiments") / "v1.1" / "relation-precision" / "sample.jsonl"
SEED = 169
JUDGE_MODEL = "meta-llama/llama-3.3-70b-instruct"
#: USD per million tokens, input and output (OpenRouter's list price, 2026-11-01).
JUDGE_PRICE = (0.10, 0.32)
JUDGE_MAX_TOKENS = 60
#: How `report` names the ``hand`` verdicts.
HAND_LABEL = "agent, writer hidden"

JUDGE_PROMPT = """You check a knowledge-graph relation against a news text.

Text:
\"\"\"{text}\"\"\"

Relation: ({source}) -[{relation_type}]-> ({target})

Is this relation stated in the text, or directly implied by it, with both ends being \
things the text talks about? A relation that needs outside knowledge, reverses the \
text's meaning, or links things the text does not connect is not supported.

Reply with only a JSON object: {{"supported": true}} or {{"supported": false}}."""


@dataclass(frozen=True)
class Relation:
    """One sampled extra relation and its verdicts (None until judged)."""

    id: str
    custom_id: str
    writer: str
    other: str
    source: str
    relation_type: str
    target: str
    judge: bool | None = None
    hand: bool | None = None


def _valid(results: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for cid, record in results.items():
        if record.get("status") != "succeeded":
            continue
        data, _ = wp.parse_extraction(record.get("content") or "")
        if data is not None:
            out[cid] = data
    return out


def extra_relations(
    writer: Mapping[str, Mapping[str, Any]], other: Mapping[str, Mapping[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Per chunk both answered validly, ``writer``'s relations whose end pair ``other``
    lacks, in answer order, one per pair."""
    out: dict[str, list[dict[str, Any]]] = {}
    for cid, data in writer.items():
        if cid not in other:
            continue
        theirs = wp._relation_pairs(other[cid])
        seen: set[tuple[str, ...]] = set()
        extra = []
        for r in data["relations"]:
            pair = tuple(sorted((wp._norm(r["source"]), wp._norm(r["target"]))))
            if pair not in theirs and pair not in seen:
                seen.add(pair)
                extra.append(r)
        if extra:
            out[cid] = extra
    return out


def stratified_sample(
    extra: Mapping[str, Sequence[Mapping[str, Any]]],
    n: int,
    *,
    writer: str,
    other: str,
    rng: random.Random,
    prefix: str,
) -> list[Relation]:
    """``n`` distinct chunks drawn from ``rng``, one extra relation from each."""
    chunks = rng.sample(sorted(extra), min(n, len(extra)))
    out: list[Relation] = []
    for i, cid in enumerate(sorted(chunks), start=1):
        r = rng.choice(list(extra[cid]))
        out.append(
            Relation(
                id=f"{prefix}{i:03d}",
                custom_id=cid,
                writer=writer,
                other=other,
                source=r["source"],
                relation_type=r["relation_type"],
                target=r["target"],
            )
        )
    return out


def judge_body(relation: Relation, text: str) -> str:
    """The chat-completions body that asks the judge about one relation."""
    prompt = JUDGE_PROMPT.format(
        text=text,
        source=relation.source,
        relation_type=relation.relation_type,
        target=relation.target,
    )
    return json.dumps({
        "model": JUDGE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": JUDGE_MAX_TOKENS,
    })


def parse_verdict(content: str) -> bool | None:
    """The judge's ``supported`` flag; None when the reply is not that object."""
    text = (
        content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    )
    try:
        data = json.loads(text.strip())
    except ValueError:
        return None
    value = data.get("supported") if isinstance(data, dict) else None
    return value if isinstance(value, bool) else None


def estimate_usd(bodies: Sequence[str]) -> float:
    """An upper estimate: about 4 characters a token in, every reply at the cap."""
    return usd(sum(len(b) for b in bodies) / 4, JUDGE_MAX_TOKENS * len(bodies))


def usd(prompt_tokens: float, completion_tokens: float) -> float:
    """The judge's price of the given tokens, at ``JUDGE_PRICE``."""
    return (prompt_tokens * JUDGE_PRICE[0] + completion_tokens * JUDGE_PRICE[1]) / 1e6


@dataclass(frozen=True)
class Precision:
    """One writer's precision under one judge."""

    writer: str
    judge: str
    judged: int
    supported: int
    ci: tuple[float, float]


def precision(rows: Sequence[Relation], judge: str) -> list[Precision]:
    """Each writer's share of supported relations among those ``judge`` decided."""
    out: list[Precision] = []
    for writer in sorted({r.writer for r in rows}):
        verdicts = [getattr(r, judge) for r in rows if r.writer == writer]
        decided = [v for v in verdicts if v is not None]
        if not decided:
            continue
        k = sum(decided)
        _, lo, hi = wilson_ci(k, len(decided))
        out.append(Precision(writer, judge, len(decided), k, (lo, hi)))
    return out


def agreement(rows: Sequence[Relation]) -> tuple[int, int]:
    """(agreeing, both decided) between the model judge and the hand labels."""
    both = [
        (r.judge, r.hand) for r in rows if r.judge is not None and r.hand is not None
    ]
    return sum(1 for a, b in both if a == b), len(both)


def read_sample(path: Path) -> list[Relation]:
    """The sample file's relations, in file order."""
    with open(path, encoding="utf-8") as f:
        return [Relation(**json.loads(line)) for line in f if line.strip()]


def write_sample(path: Path, rows: Sequence[Relation]) -> None:
    """Writes ``rows`` as JSON lines, LF line ends."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")


def _texts(pilot: Path) -> dict[str, str]:
    return {c.custom_id: c.text for c in wp.read_chunks(pilot)}


def _sample(args: argparse.Namespace) -> None:
    haiku = _valid(wp.read_results(args.pilot / "haiku-5.5.results.jsonl"))
    deepseek = _valid(wp.read_results(args.pilot / "deepseek.results.jsonl"))
    rng = random.Random(SEED)
    rows = stratified_sample(
        extra_relations(haiku, deepseek),
        args.haiku,
        writer="haiku-5.5",
        other="deepseek",
        rng=rng,
        prefix="h",
    ) + stratified_sample(
        extra_relations(deepseek, haiku),
        args.deepseek,
        writer="deepseek",
        other="haiku-5.5",
        rng=rng,
        prefix="d",
    )
    write_sample(args.sample, rows)
    print(f"wrote {len(rows)} relations to {args.sample}")


def _judge(args: argparse.Namespace) -> None:
    rows = read_sample(args.sample)
    texts = _texts(args.pilot)
    todo = [r for r in rows if r.judge is None]
    bodies = [judge_body(r, texts[r.custom_id]) for r in todo]
    cost = estimate_usd(bodies)
    print(
        f"{len(todo)} requests to {JUDGE_MODEL}, estimate ${cost:.4f}, "
        f"ceiling ${args.ceiling}"
    )
    if cost > args.ceiling or not args.go:
        print("not sent (pass --go under the ceiling to send)")
        return
    client = OpenRouterChatClient(os.environ.get("OPENROUTER_API_KEY", ""))
    done: dict[str, bool | None] = {}
    spent_tokens = [0, 0]
    for r, body in zip(todo, bodies, strict=True):
        result = client.complete(BatchRequest(custom_id=r.id, body_json=body))
        if result.output is None:
            print(f"{r.id}: {result.status} {result.error}")
            continue
        spent_tokens[0] += result.output.prompt_tokens
        spent_tokens[1] += result.output.completion_tokens
        done[r.id] = parse_verdict(result.output.content)
        if done[r.id] is None:
            print(f"{r.id}: unreadable reply {result.output.content!r}")
    merged = [
        Relation(**{**asdict(r), "judge": done[r.id]}) if r.id in done else r
        for r in rows
    ]
    write_sample(args.sample, merged)
    print(
        f"judged {len(done)}; tokens in {spent_tokens[0]}, "
        f"out {spent_tokens[1]}, ~${usd(*spent_tokens):.4f}"
    )


def render_markdown(rows: Sequence[Relation]) -> str:
    """Each writer's precision under each judge, then the judges' agreement."""
    lines = [
        "| writer (extra over) | judge | judged | supported | precision [Wilson 95%] |",
        "|---|---|---|---|---|",
    ]
    other = {r.writer: r.other for r in rows}
    for judge in ("judge", "hand"):
        for p in precision(rows, judge):
            name = JUDGE_MODEL if judge == "judge" else HAND_LABEL
            lines.append(
                f"| {p.writer} (over {other[p.writer]}) | {name} "
                f"| {p.judged} | {p.supported} "
                f"| {p.supported / p.judged:.2f} [{p.ci[0]:.2f}, {p.ci[1]:.2f}] |"
            )
    agree, both = agreement(rows)
    if both:
        lines.append(f"\nJudges agree on {agree} of {both}.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("sample", "judge", "report"):
        p = sub.add_parser(name)
        p.add_argument("--pilot", type=Path, default=PILOT)
        p.add_argument("--sample", type=Path, default=SAMPLE)
        if name == "sample":
            p.add_argument("--haiku", type=int, default=100)
            p.add_argument("--deepseek", type=int, default=50)
        if name == "judge":
            p.add_argument("--ceiling", type=float, default=1.0)
            p.add_argument("--go", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "sample":
        _sample(args)
    elif args.command == "judge":
        _judge(args)
    else:
        print(render_markdown(read_sample(args.sample)))


if __name__ == "__main__":
    main()
