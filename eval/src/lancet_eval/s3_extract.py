"""S3's writer extraction over the 2Wiki passages (#145), on #117's writer pilot.

Run as ``python -m lancet_eval.s3_extract <command>``. Every choice the extraction
depends on is ``thresholds.PREREGISTRATION_S3_WRITERS`` (D-73), with deepseek's
transport from its addendum ``PREREGISTRATION_S3_WRITERS_SYNC`` (D-290):

- **Units.** Each of the 6,119 passages is one request, ``twowiki.passage_unit`` (title
  and text), in file order, with no chunking and no length floor. ``custom_id`` is
  ``tw-<index>``, zero-padded so that IDs sort in submission order (``fetch_batch``
  assigns a request to its batch by ID range).
- **Requests and transport.** #117's ``writer_pilot``: the engine's extraction body,
  rewritten per Claude writer (slug, BYOK pin, no temperature or top_p, its thinking),
  submitted to OpenRouter's Batch API in parts of 500 and fetched with its routing
  check (``is_byok`` true, provider Anthropic). deepseek gets the engine's body
  unrewritten, posted one passage at a time to the sync API (``writer_pilot.run_sync``,
  D-278, D-290), and stops at the first answer whose ``is_byok`` is not false.
- **Estimate.** Printed before every submit (D-258). Input is the o200k tokens of the
  unit plus the per-request overhead Claude billed in #117's pilot; output is a linear
  fit of completion tokens on chunk tokens, capped at the largest answer seen. The fit
  comes from the writer's own results here once it has some, else from #117's pilot
  (Opus, absent from the pilot, borrows Sonnet's). deepseek is billed at full price.
- **Report.** Per writer: requests, failures, schema-invalid answers, runaways
  (``finish_reason: length``, #156), tokens including reasoning tokens, spend at its
  billed price and routing breaks.

Outputs go to ``experiments/v1.1/s3-extract``: ``chunks.jsonl``, each writer's
``<writer>.results.jsonl``, the batch manifests and ``summary.json``, all committed
(owner, 2026-11-01). No key or environment value is written.
"""

from __future__ import annotations

import json
import os
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import tiktoken
import typer

from lancet_eval import batch_client, twowiki
from lancet_eval import writer_pilot as wp
from lancet_eval.config import repo_root
from lancet_eval.measure import BATCH_PRICE_FACTOR
from lancet_eval.thresholds import (
    PREREGISTRATION_S3_WRITERS,
    PREREGISTRATION_S3_WRITERS_SYNC,
)

PRE = PREREGISTRATION_S3_WRITERS
#: Each writer's transport: the frozen constant's, with D-290's addendum applied.
TRANSPORTS = PREREGISTRATION_S3_WRITERS_SYNC.transports_for(PRE)
DEFAULT_OUT = Path("experiments") / "v1.1" / "s3-extract"
PILOT_OUT = Path("experiments") / "v1.1" / "writer-pilot"
#: The pilot writer whose token model a writer borrows before it has results here.
PILOT_PROXY = {
    "deepseek": "deepseek",
    "haiku-5.5": "haiku-5.5",
    "sonnet-5.5": "sonnet-5.5",
    "opus-5.5": "sonnet-5.5",
}


def custom_id(index: int) -> str:
    return f"tw-{index:04d}"


def passage_chunks(passages: Iterable[Mapping[str, Any]]) -> list[wp.PilotChunk]:
    """Every passage as one request, in file order (``PRE.unit``)."""
    return [
        wp.PilotChunk(custom_id(i), i, 0, str(p["title"]), "", twowiki.passage_unit(p))
        for i, p in enumerate(passages)
    ]


def writers() -> dict[str, wp.Writer]:
    """The pre-registration's writers, each billed at its transport's price."""
    out = {}
    for name, declaration in PRE.writers:
        if name == wp.DEEPSEEK:
            # The engine's body, unrewritten, at full price on the sync API (D-290).
            out[name] = wp.Writer(name, declaration.price, 1.0)
        else:
            out[name] = wp.Writer(
                name, declaration.price, BATCH_PRICE_FACTOR, declaration
            )
    return out


@cache
def _o200k_encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


def o200k(text: str) -> int:
    return len(_o200k_encoding().encode_ordinary(text))


@dataclass(frozen=True)
class TokenModel:
    """Billed tokens of one request from the o200k tokens of its unit.

    Attributes:
        overhead: Mean billed prompt tokens beyond the unit's o200k count.
        intercept: Completion tokens at a unit of 0 tokens.
        slope: Completion tokens per unit token.
        cap: The largest completion seen; no prediction exceeds it.
    """

    overhead: float
    intercept: float
    slope: float
    cap: int

    @classmethod
    def fit(
        cls,
        chunks: Sequence[wp.PilotChunk],
        results: Mapping[str, Mapping[str, Any]],
    ) -> TokenModel:
        """Fits the model on every succeeded answer of `results`."""
        text = {c.custom_id: c.text for c in chunks}
        rows = [
            (o200k(text[cid]), r["prompt_tokens"], r["completion_tokens"])
            for cid, r in results.items()
            if r["status"] == "succeeded" and cid in text
        ]
        if len(rows) < 2:
            raise wp.PilotError(f"{len(rows)} answer(s) cannot fit a token model")
        units = [u for u, _, _ in rows]
        completions = [c for _, _, c in rows]
        line = statistics.linear_regression(units, completions)
        return cls(
            overhead=statistics.fmean(p - u for u, p, _ in rows),
            intercept=line.intercept,
            slope=line.slope,
            cap=max(completions),
        )

    def prompt(self, unit_tokens: int) -> float:
        return self.overhead + unit_tokens

    def completion(self, unit_tokens: int) -> float:
        return max(0.0, min(self.intercept + self.slope * unit_tokens, self.cap))


def estimate(
    writer: wp.Writer, chunks: Sequence[wp.PilotChunk], model: TokenModel
) -> tuple[float, float, float]:
    """Expected USD, prompt tokens and completion tokens for `chunks`."""
    units = [o200k(c.text) for c in chunks]
    prompt = sum(model.prompt(u) for u in units)
    completion = sum(model.completion(u) for u in units)
    return wp.usd(writer, prompt, completion), prompt, completion


def summarise(
    writer: wp.Writer,
    chunks: Sequence[wp.PilotChunk],
    results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """One writer's record over the passages it has results for."""
    done = [results[c.custom_id] for c in chunks if c.custom_id in results]
    ok = [r for r in done if r["status"] == "succeeded"]
    prompt = sum(r.get("prompt_tokens") or 0 for r in ok)
    completion = sum(r.get("completion_tokens") or 0 for r in ok)
    declaration = writer.declaration
    return {
        "writer": writer.name,
        "slug": declaration.slug if declaration else "deepseek (engine body)",
        "thinking": declaration.thinking if declaration else "off",
        "effort": declaration.effort if declaration else None,
        "passages": len(chunks),
        "answered": len(done),
        "succeeded": len(ok),
        "errored": len(done) - len(ok),
        "runaways": [r["custom_id"] for r in ok if r.get("finish_reason") == "length"],
        "schema_invalid": sum(
            wp.parse_extraction(r.get("content") or "")[0] is None for r in ok
        ),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        # batch_client writes -1 when OpenRouter leaves the count out.
        "reasoning_tokens": sum(max(r.get("reasoning_tokens") or 0, 0) for r in ok),
        "reasoning_missing": sum((r.get("reasoning_tokens") or 0) < 0 for r in ok),
        "usd": round(wp.usd(writer, prompt, completion), 4),
        "routing_breaks": [p for r in done if (p := wp.routing_problem(writer, r))],
    }


def keep_succeeded(path: Path, before: Mapping[str, Mapping[str, Any]]) -> int:
    """Restores each answer that succeeded before a re-fetch and does not now.

    ``fetch_batch`` re-reads every submitted batch and appends all of it, and the latest
    line per request wins; a staged writer's earlier batch fetched again after its
    results expired would replace good answers with errors.

    Returns:
        How many earlier answers were appended again.
    """
    now = wp.read_results(path)
    lost = [
        r
        for cid, r in before.items()
        if r["status"] == "succeeded" and now.get(cid, {}).get("status") != "succeeded"
    ]
    wp._append(path, lost)
    return len(lost)


# ---- command line ----------------------------------------------------------------

app = typer.Typer(add_completion=False, help=__doc__)


def _out(out: Path) -> Path:
    return out if out.is_absolute() else repo_root() / out


def _writer(name: str) -> wp.Writer:
    found = writers()
    if name not in found:
        raise typer.BadParameter(f"unknown writer {name!r}; one of {list(found)}")
    return found[name]


def _results(out: Path, name: str) -> dict[str, dict[str, Any]]:
    """A writer's answers, its shard files' included; a succeeded answer wins."""
    merged = wp.read_results(out / f"{name}.results.jsonl")
    for path in sorted(out.glob(f"{name}.shard*.results.jsonl")):
        for cid, record in wp.read_results(path).items():
            if record["status"] == "succeeded" or cid not in merged:
                merged[cid] = record
    return merged


def shard(
    out: Path, writer: wp.Writer, index: int, count: int
) -> tuple[wp.Writer, list[wp.PilotChunk]]:
    """One of `count` disjoint parts of the passages still without a succeeded answer,
    and the writer that records it in its own ``<writer>.shard<index>.results.jsonl``,
    so parallel runs never share a file (owner, 2026-11-01: "Allow 8 shards").
    """
    if not 0 <= index < count:
        raise wp.PilotError(f"shard {index} is not in 0..{count - 1}")
    chunks = [c for i, c in enumerate(_unanswered(out, writer)) if i % count == index]
    part = wp.Writer(
        f"{writer.name}.shard{index}",
        writer.price,
        writer.price_factor,
        writer.declaration,
    )
    return part, chunks


def token_model(out: Path, writer: wp.Writer) -> tuple[TokenModel, str]:
    """The writer's own token model once it has 50 answers here, else the pilot's."""
    own = _results(out, writer.name)
    if sum(r["status"] == "succeeded" for r in own.values()) >= 50:
        return TokenModel.fit(wp.read_chunks(out), own), f"{writer.name}, this run"
    proxy = PILOT_PROXY[writer.name]
    pilot = _out(PILOT_OUT)
    return (
        TokenModel.fit(wp.read_chunks(pilot), _results(pilot, proxy)),
        f"{proxy}, #117 pilot",
    )


def _print_estimate(
    out: Path, writer: wp.Writer, chunks: Sequence[wp.PilotChunk]
) -> float:
    model, source = token_model(out, writer)
    usd, prompt, completion = estimate(writer, chunks, model)
    typer.echo(
        f"{writer.name}: {len(chunks)} passage(s) to {_slug(writer)} "
        f"at {writer.price_factor} x ${writer.price.input_per_mtok}/"
        f"${writer.price.output_per_mtok} per MTok: about ${usd:.2f} "
        f"(~{prompt / 1e6:.2f}M input, ~{completion / 1e6:.2f}M output tokens; "
        f"token model from {source}: overhead {model.overhead:.0f}, "
        f"{model.intercept:.0f} + {model.slope:.2f} x unit, cap {model.cap})"
    )
    return usd


def _slug(writer: wp.Writer) -> str:
    if writer.declaration is not None:
        return writer.declaration.slug
    return dict(PRE.writers)[writer.name].slug


def _pending(out: Path, writer: wp.Writer) -> list[wp.PilotChunk]:
    """The passages of the parts not yet submitted for `writer`."""
    chunks = wp.read_chunks(out)
    manifest = out / f"{writer.name}.batch.json"
    sent = (
        sum(b["requests"] for b in json.loads(manifest.read_text("utf-8"))["batches"])
        if manifest.is_file()
        else 0
    )
    return chunks[sent:]


@app.command()
def plan(out: Path = DEFAULT_OUT) -> None:
    """Free: writes ``chunks.jsonl`` from the checked passages and prints estimates."""
    out = _out(out)
    chunks = passage_chunks(twowiki.load_passages())
    if len(chunks) != PRE.passage_count:
        raise wp.PilotError(f"{len(chunks)} passages, expected {PRE.passage_count}")
    wp.write_chunks(out, chunks)
    typer.echo(f"{len(chunks)} passages -> {out / 'chunks.jsonl'}")
    total = 0.0
    for writer in writers().values():
        if writer.declaration is not None:
            total += _print_estimate(out, writer, _pending(out, writer))
    typer.echo(f"Claude writers, not yet submitted: about ${total:.2f}")
    deepseek = writers()[wp.DEEPSEEK]
    _print_estimate(out, deepseek, _unanswered(out, deepseek))


def _unanswered(out: Path, writer: wp.Writer) -> list[wp.PilotChunk]:
    """The passages without a succeeded answer from `writer`."""
    done = {
        cid
        for cid, r in _results(out, writer.name).items()
        if r["status"] == "succeeded"
    }
    return [c for c in wp.read_chunks(out) if c.custom_id not in done]


@app.command()
def submit(
    writer: str,
    out: Path = DEFAULT_OUT,
    parts: int | None = typer.Option(None, help="Submit at most this many batches."),
) -> None:
    """Paid: OpenRouter batches of the remaining passages for a Claude writer."""
    w = _writer(writer)
    out = _out(out)
    pending = _pending(out, w)
    shown = pending[: parts * wp.BATCH_PART] if parts is not None else pending
    _print_estimate(out, w, shown)
    client = batch_client.OpenRouterBatchClient(
        os.environ.get("OPENROUTER_API_KEY", "")
    )
    wp.submit_batch(w, wp.read_chunks(out), client, out, echo=typer.echo, limit=parts)


@app.command()
def deepseek(
    out: Path = DEFAULT_OUT,
    shard_index: int = typer.Option(0, "--shard", help="This run's shard."),
    shards: int = typer.Option(1, help="Parallel runs, each with its own --shard."),
) -> None:
    """Paid: deepseek's extraction of the unanswered passages through the sync API.

    Each run posts one passage at a time (D-290); with ``--shards N`` the owner allowed
    N such runs in parallel, each on its own share of the unanswered passages and its
    own results file. Each answer is journalled as it arrives, so a rerun sends only
    the rest. A run stops at the first answer whose ``is_byok`` is not false.
    """
    if TRANSPORTS[wp.DEEPSEEK] != "openrouter_sync":
        raise wp.PilotError(f"deepseek's transport is {TRANSPORTS[wp.DEEPSEEK]!r}")
    out = _out(out)
    base = writers()[wp.DEEPSEEK]
    w, chunks = shard(out, base, shard_index, shards)
    if shards == 1:
        w = base
    _print_estimate(out, base, chunks)
    wp.run_sync(w, chunks, batch_client.chat_client(), out, echo=typer.echo)


@app.command()
def fetch(writer: str, out: Path = DEFAULT_OUT) -> None:
    """Free: writes the results once every submitted batch of a writer finished."""
    w = _writer(writer)
    client = batch_client.OpenRouterBatchClient(
        os.environ.get("OPENROUTER_API_KEY", "")
    )
    out = _out(out)
    path = out / f"{w.name}.results.jsonl"
    before = wp.read_results(path)
    if wp.fetch_batch(w, client, out, echo=typer.echo):
        kept = keep_succeeded(path, before)
        if kept:
            typer.echo(f"{w.name}: kept {kept} earlier succeeded answer(s)")


@app.command()
def report(out: Path = DEFAULT_OUT) -> None:
    """Free: every writer's record as JSON (``summary.json``) and on stdout."""
    out = _out(out)
    chunks = wp.read_chunks(out)
    summary = [summarise(w, chunks, _results(out, w.name)) for w in writers().values()]
    text = json.dumps(summary, indent=2, ensure_ascii=False)
    (out / "summary.json").write_text(text + "\n", encoding="utf-8")
    typer.echo(text)


if __name__ == "__main__":
    app()
