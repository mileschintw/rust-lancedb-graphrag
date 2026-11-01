"""D-276 dual answer judge: the secondary beside the normalised `answer_usable`.

`answer_usable` (D-70 with D-276's folds) stays the primary. This module asks two
judges, `openai/gpt-4o-mini` (the v1.0 judge, a family distinct from every S2 reader)
and Claude Sonnet 5.5 over OpenRouter BYOK, whether each record's extracted final line
is equivalent to the gold answer. A judge sees only the question, the gold answer and
the line: never the arm, the reader or the prose. So one verdict serves every arm that
wrote the same line for the same question, and the arms are judged blind.

The Sonnet judge reads Claude readers' lines, which the v1.0 rule (a judge is never the
generator, `score.py`) forbids. D-276 allows it for this secondary only: the two
judges are compared, and their disagreements on Claude arms measure self-preference.
`score.py`'s guard is unchanged for v1.0 scoring.

`judge_answers` prints a cost estimate first (D-258: it never refuses), asks each
judge once per distinct prompt (verdicts are cached in the run directory, errors are
not), and writes `answer-judge.json`: per-arm rates for the primary and both judges
over the G population, and every record where the three disagree. No paid call
happens in tests: the transport is a parameter.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from lancet_eval.corpus import GoldQuestion, load_sample_questions
from lancet_eval.journal import RunRecord, load_records, read_journal_header
from lancet_eval.judge import DEFAULT_CHAT_ENDPOINT, _post_judge
from lancet_eval.metrics import answer_usable, context_tokens, final_answer_line

PROMPT_VERSION = "answer-judge-v1"
REPORT_FILE = "answer-judge.json"
CACHE_FILE = "answer-judge-cache.json"
#: Completion tokens one verdict is estimated at: a boolean and a short rationale.
ESTIMATED_COMPLETION_TOKENS = 80
MAX_TOKENS = 300

SYSTEM_PROMPT = """\
You judge whether a short answer to a question says the same thing as the gold \
answer.

Equivalent: it names the same entity, value or yes/no as the gold answer. Ignore \
capitalisation, word order, singular or plural, articles, and extra words that do \
not change the meaning. A list answer is equivalent when it names the same items, \
in any order.

Not equivalent: it names something else, adds a wrong item, hedges between options, \
contradicts the gold answer, or declines to answer.

Use only the question, the gold answer and the answer to judge. Reply with a JSON \
object: {"equivalent": true or false, "rationale": "<at most 300 characters>"}"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "equivalent": {"type": "boolean"},
        "rationale": {"type": "string"},
    },
    "required": ["equivalent", "rationale"],
    "additionalProperties": False,
}

Transport = Callable[[dict[str, Any], str], dict[str, Any]]


class AnswerJudgeError(ValueError):
    """A run this module cannot judge, or a judge it cannot reach."""


@dataclass(frozen=True)
class AnswerJudge:
    """One judge: its report name, OpenRouter slug, sync list price and body fields.

    `body` holds the fields this judge's request adds beside `model`, `messages`,
    `max_tokens` and `response_format`.
    """

    name: str
    slug: str
    input_per_mtok: float
    output_per_mtok: float
    body: Mapping[str, Any] = field(default_factory=dict, hash=False, compare=False)


#: The v1.0 judge. Price from OpenRouter's models API, read 2026-10-31.
GPT_4O_MINI = AnswerJudge(
    name="gpt-4o-mini",
    slug="openai/gpt-4o-mini",
    input_per_mtok=0.15,
    output_per_mtok=0.60,
    body={"temperature": 0.0},
)
#: Sonnet 5.5 as the S2 readers' requests send it (D-255, D-260): pinned to the BYOK
#: Anthropic provider, `between_tools` thinking, no temperature. Price as D-269.
SONNET = AnswerJudge(
    name="sonnet-5.5",
    slug="anthropic/claude-sonnet-5.5",
    input_per_mtok=2.0,
    output_per_mtok=10.0,
    body={
        "provider": {"only": ["anthropic"], "allow_fallbacks": False},
        "thinking": {"type": "between_tools"},
    },
)
JUDGES: tuple[AnswerJudge, ...] = (GPT_4O_MINI, SONNET)


@dataclass(frozen=True)
class _Item:
    """One record of the G population: its final line, and its primary verdict."""

    question: GoldQuestion
    arm: str
    replicate: int
    line: str | None
    primary: bool


def _messages(question: str, gold: str, line: str) -> list[dict[str, str]]:
    user = f"Question: {question}\nGold answer: {gold}\nAnswer to judge: {line}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _payload(judge: AnswerJudge, question: str, gold: str, line: str) -> dict[str, Any]:
    return {
        "model": judge.slug,
        "messages": _messages(question, gold, line),
        "max_tokens": MAX_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "verdict", "strict": True, "schema": _SCHEMA},
        },
        **judge.body,
    }


def _key(judge: AnswerJudge, question: str, gold: str, line: str) -> str:
    raw = "\x1f".join((PROMPT_VERSION, judge.slug, question, gold, line))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def openrouter_transport(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    """Posts one judge request to OpenRouter, with `judge.py`'s retry on 429/5xx."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client() as client:
        return _post_judge(
            client, endpoint=DEFAULT_CHAT_ENDPOINT, headers=headers, payload=payload
        )


def _parse(response: dict[str, Any]) -> tuple[bool | None, str, tuple[int, int]]:
    """(verdict or None, rationale or error, (prompt, completion) tokens)."""
    usage = response.get("usage") or {}
    tokens = (
        int(usage.get("prompt_tokens") or 0),
        int(usage.get("completion_tokens") or 0),
    )
    choices = response.get("choices") or []
    if not choices:
        return None, "the judge returned no choices", tokens
    content = (choices[0].get("message") or {}).get("content") or ""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None, f"the judge reply is not JSON: {content[:200]!r}", tokens
    if not isinstance(data, dict) or not isinstance(data.get("equivalent"), bool):
        return (
            None,
            f"the judge reply has no boolean 'equivalent': {content[:200]!r}",
            tokens,
        )
    return data["equivalent"], str(data.get("rationale", ""))[:300], tokens


def _items(run: Path) -> list[_Item]:
    journal = run / "journal.jsonl"
    if not journal.is_file():
        raise AnswerJudgeError(f"no journal in {run}")
    records = _latest_per_replicate(load_records(journal))
    header = read_journal_header(journal) or {}
    corpus = str(header.get("corpus") or (records[0].corpus if records else ""))
    if not corpus:
        raise AnswerJudgeError(f"{journal} names no corpus")
    gold = {q.question_id: q for q in load_sample_questions(corpus)}
    items: list[_Item] = []
    for rec in records:
        question = gold.get(rec.question_id)
        if question is None or question.is_null or not question.gold_answer:
            continue
        line = final_line(rec.answer) if rec.outcome == "success" else None
        items.append(
            _Item(
                question=question,
                arm=rec.graph_arm,
                replicate=_replicate(rec),
                line=line,
                primary=_primary(question, rec),
            )
        )
    return items


def final_line(answer: str | None) -> str | None:
    """The line the judges read: the final `Answer:` line as written (D-276)."""
    return final_answer_line(answer)


def _replicate(rec: RunRecord) -> int:
    """The record's replicate; 1 for a journal written before replicates existed."""
    return int(getattr(rec, "replicate", 1) or 1)


def _latest_per_replicate(records: Sequence[RunRecord]) -> list[RunRecord]:
    """The later record of each (question, arm, replicate), sorted by that key.

    A resumed drive appends a later record for the same unit; replicates of one
    question and arm are separate units, each judged.
    """
    latest: dict[tuple[str, str, int], RunRecord] = {}
    for rec in records:
        latest[(rec.graph_arm, rec.question_id, _replicate(rec))] = rec
    return [latest[k] for k in sorted(latest)]


def _primary(question: GoldQuestion, rec: RunRecord) -> bool:
    return rec.outcome == "success" and answer_usable(question, rec.answer or "")


def _load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(f".tmp-{os.getpid()}")
    text = json.dumps(
        payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    )
    tmp.write_text(text + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)


def cost_estimate(
    prompts: Mapping[AnswerJudge, Sequence[list[dict[str, str]]]],
) -> tuple[str, float]:
    """The D-258 line printed before any call, and its total in USD; never refuses.

    Prompt tokens are the o200k count of each request's messages; completion tokens
    are `ESTIMATED_COMPLETION_TOKENS` a verdict. Priced at each judge's sync list price.
    """
    parts: list[str] = []
    total = 0.0
    for judge, batch in prompts.items():
        prompt_tokens = sum(
            context_tokens([m["content"] for m in msgs]) for msgs in batch
        )
        completion_tokens = ESTIMATED_COMPLETION_TOKENS * len(batch)
        usd = (
            prompt_tokens * judge.input_per_mtok
            + completion_tokens * judge.output_per_mtok
        ) / 1e6
        total += usd
        parts.append(f"{judge.name}: {len(batch)} call(s), about ${usd:.4f}")
    line = (
        "Cost estimate (D-258, never refuses): "
        + "; ".join(parts)
        + f"; total about ${total:.4f} at sync list price"
    )
    return line, total


def judge_answers(
    run: Path | str,
    *,
    judges: Sequence[AnswerJudge] = JUDGES,
    transport: Transport | None = None,
    echo: Callable[[str], None] = print,
    estimate_only: bool = False,
) -> dict[str, Any] | None:
    """Judges every G record's final line with each judge and writes the report.

    Args:
        run: The run directory (`journal.jsonl`; its header names the corpus).
        judges: The judges, in report order.
        transport: Sends one request and returns the response JSON; defaults to
            `openrouter_transport`.
        echo: Where the estimate and progress lines go.
        estimate_only: Print the estimate and stop: no call, no file written.

    Returns:
        The report written to `<run>/answer-judge.json`, or None with
        `estimate_only`.

    Raises:
        AnswerJudgeError: If the run has no journal or corpus, or
            `OPENROUTER_API_KEY` is not set when a call is needed (after the estimate).
    """
    run_dir = Path(run)
    send = transport or openrouter_transport
    items = _items(run_dir)
    cache_path = run_dir / CACHE_FILE
    cache = _load_cache(cache_path)

    todo: dict[AnswerJudge, dict[str, list[dict[str, str]]]] = {j: {} for j in judges}
    for item in items:
        if item.line is None:
            continue
        q, gold = item.question.question, item.question.gold_answer
        for judge in judges:
            key = _key(judge, q, gold, item.line)
            if key not in cache:
                todo[judge].setdefault(key, _messages(q, gold, item.line))
    estimate, _ = cost_estimate({j: list(t.values()) for j, t in todo.items()})
    echo(estimate)
    if estimate_only:
        return None

    calls = sum(len(t) for t in todo.values())
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if calls and not api_key.strip():
        raise AnswerJudgeError("OPENROUTER_API_KEY is not set")

    errors: dict[str, str] = {}
    usage = {j.name: [0, 0] for j in judges}
    for item in items:
        if item.line is None:
            continue
        q, gold = item.question.question, item.question.gold_answer
        for judge in judges:
            key = _key(judge, q, gold, item.line)
            if key in cache or key in errors:
                continue
            try:
                response = send(_payload(judge, q, gold, item.line), api_key)
            except Exception as exc:  # noqa: BLE001 - recorded, never cached
                errors[key] = f"transport failure: {exc}"
                continue
            verdict, note, tokens = _parse(response)
            usage[judge.name][0] += tokens[0]
            usage[judge.name][1] += tokens[1]
            if verdict is None:
                errors[key] = note
                continue
            cache[key] = {"judge": judge.name, "equivalent": verdict, "rationale": note}
            _write_json(cache_path, cache)
    if errors:
        echo(f"{len(errors)} judge request(s) failed; they are not cached")

    report = _report(items, judges, cache, errors, usage, estimate)
    _write_json(run_dir / REPORT_FILE, report)
    echo(f"Wrote {run_dir / REPORT_FILE}")
    return report


def _report(
    items: Sequence[_Item],
    judges: Sequence[AnswerJudge],
    cache: Mapping[str, Mapping[str, Any]],
    errors: Mapping[str, str],
    usage: Mapping[str, Sequence[int]],
    estimate: str,
) -> dict[str, Any]:
    arms = sorted({i.arm for i in items})
    names = ["primary", *(j.name for j in judges)]
    counts = {
        (n, a): {"n": 0, "n_equivalent": 0, "n_error": 0, "n_no_final_line": 0}
        for n in names
        for a in arms
    }
    disagreements: list[dict[str, Any]] = []
    for item in items:
        verdicts: dict[str, bool | None] = {"primary": item.primary}
        counts[("primary", item.arm)]["n"] += 1
        counts[("primary", item.arm)]["n_equivalent"] += int(item.primary)
        for judge in judges:
            c = counts[(judge.name, item.arm)]
            c["n"] += 1
            if item.line is None:
                c["n_no_final_line"] += 1
                verdicts[judge.name] = False
                continue
            key = _key(
                judge, item.question.question, item.question.gold_answer, item.line
            )
            if key in cache:
                verdicts[judge.name] = bool(cache[key]["equivalent"])
                c["n_equivalent"] += int(verdicts[judge.name] or 0)
            else:
                c["n_error"] += 1
                verdicts[judge.name] = None
        if (
            item.line is not None
            and len({v for v in verdicts.values() if v is not None}) > 1
        ):
            disagreements.append({
                "question_id": item.question.question_id,
                "arm": item.arm,
                "replicate": item.replicate,
                "question": item.question.question,
                "gold": item.question.gold_answer,
                "final_line": item.line,
                "verdicts": verdicts,
            })
    rates = [
        {
            "judge": n,
            "arm": a,
            **c,
            # Judged records only: a failed request is reported in n_error and is
            # neither equivalent nor not.
            "rate": (
                c["n_equivalent"] / (c["n"] - c["n_error"])
                if c["n"] > c["n_error"]
                else None
            ),
        }
        for (n, a), c in counts.items()
    ]
    spend = {
        j.name: {
            "prompt_tokens": usage[j.name][0],
            "completion_tokens": usage[j.name][1],
            "usd_at_list_price": (
                usage[j.name][0] * j.input_per_mtok
                + usage[j.name][1] * j.output_per_mtok
            )
            / 1e6,
        }
        for j in judges
    }
    return {
        "rule": (
            "D-276: primary is answer_usable with D-276's folds; the judges are a "
            "secondary, blind to the arm, given the question, the gold answer and the "
            "extracted final line only. G population; a record with no final line is "
            "not equivalent for every judge and is never sent."
        ),
        "prompt_version": PROMPT_VERSION,
        "judges": [{"name": j.name, "slug": j.slug} for j in judges],
        "estimate": estimate,
        "spend_this_invocation": spend,
        "n_errors_this_invocation": len(errors),
        "rates": rates,
        "disagreements": disagreements,
    }
