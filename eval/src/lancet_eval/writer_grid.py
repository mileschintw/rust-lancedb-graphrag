"""S3 MultiHop-RAG writer grid (#148): every chunk of S1's small store, four writers.

A standalone script, run as ``python -m lancet_eval.writer_grid <command>``. It
extracts entities and relations from every extractable chunk of the 346 documents of
``documents.subset.jsonl``, as the v1.0 small store (S1's ``small/`` arms) chunks them,
with deepseek, Haiku 5.5, Sonnet 5.5 and Opus 5.5. The graph import and the reading
are later steps (``experiments/v1.1/EXPLORE-S3-MHR-WRITERS.md``); this script builds no
store and runs no query.

It reuses the writer pilot (#117, ``writer_pilot``) whole: its chunker, request bodies,
estimate, batch submit and fetch, sync runner and summary. What it adds:

- **Chunks.** ``writer_pilot.pilot_chunks`` over every document, so a chunk's
  ``custom_id`` is the pilot's for the same chunk.
- **Opus 5.5.** Thinking on at effort low (owner ruling 2026-11-01), the S2 reader's
  slug and price, on the Batch API.
- **Reuse.** ``reuse`` copies the pilot's succeeded answers for chunks whose text is the
  same into ``<writer>.reused.jsonl``. The request body is a function of the text, so a
  copied answer is the answer this grid would have bought.
- **Pending set.** Each writer runs in its own directory ``<out>/<writer>/``, whose
  ``chunks.jsonl`` holds the chunks it still needs, frozen at first use. The pilot's
  submit and fetch then run there unchanged, and a fetch's gap rows never land on a
  reused chunk.

Outputs go to one directory (default ``experiments/v1.1/s3m-writers``). No key or
environment value is written.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import typer

from lancet_eval import batch_client
from lancet_eval import writer_pilot as wp
from lancet_eval.measure import BATCH_PRICE_FACTOR
from lancet_eval.reader_request import ReaderDeclaration, ReaderPrice

OPUS = "opus-5.5"

#: The pilot's three writers and Opus 5.5 at S2's list price, half price on the Batch
#: API.
WRITERS: dict[str, wp.Writer] = {
    **wp.WRITERS,
    OPUS: wp.Writer(
        OPUS,
        ReaderPrice(4.0, 20.0),
        BATCH_PRICE_FACTOR,
        ReaderDeclaration(
            slug="anthropic/claude-opus-5.5",
            target="openrouter",
            thinking="on",
            effort="low",
            price=ReaderPrice(4.0, 20.0),
        ),
    ),
}

DEFAULT_OUT = Path("experiments") / "v1.1" / "s3m-writers"
PILOT_OUT = wp.DEFAULT_OUT


def grid_chunks(documents: Sequence[dict[str, Any]]) -> list[wp.PilotChunk]:
    """Every extractable chunk of every document, with the pilot's IDs."""
    return wp.pilot_chunks(documents, range(len(documents)))


def _reused_path(writer: wp.Writer, out: Path) -> Path:
    return out / f"{writer.name}.reused.jsonl"


def _work(writer: wp.Writer, out: Path) -> Path:
    return out / writer.name


def reuse(writer: wp.Writer, pilot: Path, out: Path) -> int:
    """Copies the pilot's succeeded answers of chunks with the same text; returns how
    many.

    Raises:
        PilotError: If a pilot chunk's text differs from the grid's chunk of that ID,
            or a copied answer breaks the writer's routing.
    """
    grid = {c.custom_id: c for c in wp.read_chunks(out)}
    pilot_text = {c.custom_id: c.text for c in wp.read_chunks(pilot)}
    copied = []
    for cid, record in wp.read_results(pilot / f"{writer.name}.results.jsonl").items():
        if record["status"] != "succeeded":
            continue
        if cid not in grid or pilot_text.get(cid) != grid[cid].text:
            raise wp.PilotError(
                f"{cid}: the pilot's chunk text differs from the grid's"
            )
        problem = wp.routing_problem(writer, record)
        if problem is not None:
            raise wp.PilotError(f"{writer.name}: {problem}")
        copied.append(record | {"reused_from": pilot.name})
    path = _reused_path(writer, out)
    path.unlink(missing_ok=True)
    wp._append(path, copied)
    return len(copied)


def pending(
    writer: wp.Writer, out: Path, *, freeze: bool = True
) -> list[wp.PilotChunk]:
    """The chunks the writer still needs bought, frozen in its directory at first use.

    Freezing keeps a staged submit's parts stable when more answers arrive later.
    ``freeze=False`` (the estimate) reads a frozen set but writes none.
    """
    work = _work(writer, out)
    if (work / "chunks.jsonl").is_file():
        return wp.read_chunks(work)
    reused = wp.read_results(_reused_path(writer, out))
    done = {cid for cid, r in reused.items() if r["status"] == "succeeded"}
    chunks = [c for c in wp.read_chunks(out) if c.custom_id not in done]
    if freeze:
        wp.write_chunks(work, chunks)
    return chunks


def results(writer: wp.Writer, out: Path) -> dict[str, dict[str, Any]]:
    """Every chunk's answer: reused or bought, a succeeded row winning over a failed
    one."""
    merged = wp.read_results(_reused_path(writer, out))
    bought = wp.read_results(_work(writer, out) / f"{writer.name}.results.jsonl")
    for cid, record in bought.items():
        if record["status"] == "succeeded" or cid not in merged:
            merged[cid] = record
    return merged


def submit(
    writer: wp.Writer,
    client: batch_client.BatchClient,
    out: Path,
    *,
    echo: Callable[[str], None] = print,
    limit: int | None = None,
) -> list[str]:
    """The pilot's batch submit over the writer's pending chunks."""
    chunks = pending(writer, out)
    return wp.submit_batch(
        writer, chunks, client, _work(writer, out), echo=echo, limit=limit
    )


def fetch(
    writer: wp.Writer,
    client: batch_client.BatchClient,
    out: Path,
    *,
    echo: Callable[[str], None] = print,
) -> bool:
    """The pilot's fetch, in the writer's directory."""
    return wp.fetch_batch(writer, client, _work(writer, out), echo=echo)


def _output_tokens(writer: wp.Writer, out: Path) -> float:
    done = [
        r["completion_tokens"]
        for r in results(writer, out).values()
        if r["status"] == "succeeded"
    ]
    return sum(done) / len(done) if done else wp.ASSUMED_OUTPUT_TOKENS


# ---- command line ----------------------------------------------------------------

app = typer.Typer(add_completion=False, help=__doc__)


def _writer(name: str) -> wp.Writer:
    if name not in WRITERS:
        raise typer.BadParameter(f"unknown writer {name!r}; one of {list(WRITERS)}")
    return WRITERS[name]


def _client() -> batch_client.OpenRouterBatchClient:
    return batch_client.OpenRouterBatchClient(os.environ.get("OPENROUTER_API_KEY", ""))


@app.command()
def plan(out: Path = DEFAULT_OUT, pilot: Path = PILOT_OUT) -> None:
    """Free: writes ``chunks.jsonl``, reuses the pilot's answers, prints estimates.

    The estimate uses each writer's measured mean output tokens once it has answers
    (the pilot's included), else the pilot's assumed 400.
    """
    out, pilot = wp._out(out), wp._out(pilot)
    chunks = grid_chunks(wp.load_documents())
    wp.write_chunks(out, chunks)
    typer.echo(
        f"{len({c.doc_index for c in chunks})} documents, {len(chunks)} extractable "
        f"chunks -> {out / 'chunks.jsonl'}"
    )
    for writer in WRITERS.values():
        if (pilot / f"{writer.name}.results.jsonl").is_file() and not (
            _work(writer, out) / "chunks.jsonl"
        ).is_file():
            n = reuse(writer, pilot, out)
            typer.echo(f"{writer.name}: {n} answer(s) reused from {pilot}")
        typer.echo(
            wp.estimate(
                writer, pending(writer, out, freeze=False), _output_tokens(writer, out)
            )
        )


@app.command()
def deepseek(out: Path = DEFAULT_OUT) -> None:
    """Paid: deepseek's pending chunks through the sync API (D-278)."""
    out = wp._out(out)
    writer = WRITERS[wp.DEEPSEEK]
    chunks = pending(writer, out)
    typer.echo(wp.estimate(writer, chunks, _output_tokens(writer, out)))
    wp.run_sync(
        writer, chunks, batch_client.chat_client(), _work(writer, out), echo=typer.echo
    )


@app.command()
def canary(writer: str, out: Path = DEFAULT_OUT) -> None:
    """Paid: one chunk to a Claude writer through the sync API, checking BYOK."""
    w = _writer(writer)
    out = wp._out(out)
    chunk = wp.read_chunks(out)[:1]
    canary_writer = wp.Writer(f"{w.name}.canary", w.price, 1.0, w.declaration)
    typer.echo(wp.estimate(canary_writer, chunk, wp.ASSUMED_OUTPUT_TOKENS))
    wp.run_sync(canary_writer, chunk, batch_client.chat_client(), out, echo=typer.echo)
    for r in wp.read_results(out / f"{canary_writer.name}.results.jsonl").values():
        data, why = wp.parse_extraction(r.get("content") or "")
        typer.echo(
            f"{r['custom_id']}: {r['status']} is_byok={r.get('is_byok')} "
            f"provider={r.get('provider')} "
            f"reasoning_tokens={r.get('reasoning_tokens')} "
            f"tokens={r.get('prompt_tokens')}/{r.get('completion_tokens')} "
            f"schema={'ok' if data else why} error={r.get('error')}"
        )


@app.command("submit")
def submit_command(
    writer: str,
    out: Path = DEFAULT_OUT,
    parts: int | None = typer.Option(None, help="Submit at most this many batches."),
) -> None:
    """Paid: OpenRouter batches of a Claude writer's pending chunks."""
    w = _writer(writer)
    out = wp._out(out)
    typer.echo(wp.estimate(w, pending(w, out), _output_tokens(w, out)))
    submit(w, _client(), out, echo=typer.echo, limit=parts)


@app.command("fetch")
def fetch_command(writer: str, out: Path = DEFAULT_OUT) -> None:
    """Free: writes the results once every submitted batch has finished."""
    fetch(_writer(writer), _client(), wp._out(out), echo=typer.echo)


@app.command()
def report(out: Path = DEFAULT_OUT) -> None:
    """Free: every writer's figures over the whole grid as JSON (``summary.json``)."""
    out = wp._out(out)
    chunks = wp.read_chunks(out)
    publishers = wp._publishers()
    reference = results(WRITERS[wp.DEEPSEEK], out)
    summary = [
        wp.summarise(
            w,
            chunks,
            results(w, out),
            publishers,
            None if w.name == wp.DEEPSEEK else reference,
        )
        for w in WRITERS.values()
    ]
    text = json.dumps(summary, indent=2, ensure_ascii=False)
    (out / "summary.json").write_text(text + "\n", encoding="utf-8")
    typer.echo(text)


if __name__ == "__main__":
    app()
