"""Writer pilot for the S3 grill (#117): graph extraction by three writers.

A standalone script, run as ``python -m lancet_eval.writer_pilot <command>``. It
builds no store and runs no query. It extracts entities and relations from the chunks
of a small, seeded subset of ``documents.subset.jsonl`` with Haiku 5.5, Sonnet 5.5 and
deepseek, and reports tokens, cost, counts and junk entities per writer, for the S3
writer-vs-writer question (``experiments/v1.1/PLAN.md``).

- **Chunks.** The engine's ``structure-aware`` chunking at the gateway default of
  500/50 characters (the v1.0 small store S1 kept), ported from
  ``engine/src/chunker/mod.rs`` (``chunk_markdown``, ``append_region``,
  ``split_window``). The port covers text without markdown headings only, and refuses
  a document with a heading-like line; no MultiHop-RAG document has one. Chunks the
  engine would not extract (``MIN_CHUNK_CONTENT_LENGTH``) are dropped.
- **Request.** deepseek gets the engine's extraction body
  (``OpenRouterExtractionGenerator::build_request_payload``), with the same fields and
  values; only the key order differs, since the engine's ``serde_json`` (no
  ``preserve_order``) sorts a ``json!`` object's keys and this body keeps the Rust
  source's order. The body carries its system and user
  messages, strict ``json_schema``, ``max_completion_tokens`` 16,384 (D-272) and
  ``reasoning: {effort: none}``, pinned to ``config.toml``'s D-271 provider pin, posted
  alone to the sync API (D-278). Each Claude writer gets that body rewritten as S2's
  readers are (``reader_request.rewrite_pack_body``): its slug, ``provider: {only:
  ["anthropic"], allow_fallbacks: false}`` (BYOK, D-265), no temperature or top_p, and
  its thinking setting, the lowest it supports (owner ruling 2026-11-01): Haiku 5.5
  off, Sonnet 5.5 on at effort low. The Claude writers run on OpenRouter's Batch API
  at half price; ``canary`` sends one chunk through the sync API first.
- **Spend.** Every paid command prints its D-258 estimate first; nothing is paid until
  the owner says yes, so ``plan`` (free) prints the estimate for every writer.

Outputs go to one directory (default ``experiments/v1.1/writer-pilot``):
``chunks.jsonl``, ``<writer>.results.jsonl`` (one line per chunk request, the latest
wins) and ``<writer>.batch.json`` (the batch manifest). No key or environment value is
written.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import random
import re
import time
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import tiktoken
import typer

from lancet_eval import batch_client
from lancet_eval.batch_client import BatchClient, BatchRequest, BatchResult
from lancet_eval.config import repo_root
from lancet_eval.measure import BATCH_PRICE_FACTOR
from lancet_eval.reader_request import (
    ReaderDeclaration,
    ReaderPrice,
    rewrite_pack_body,
)

#: The pilot's documents: 40 of the 346, drawn with seed 42 (#117 asks for 30 to 50).
PILOT_DOCUMENTS = 40
PILOT_SEED = 42
#: The gateway's default chunking, which the v1.0 small store (S1's choice) was built
#: with.
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
#: ``engine/src/graph/extraction.rs``: chunks shorter than this (trimmed, in bytes)
#: are not extracted.
MIN_CHUNK_CONTENT_LENGTH = 40
#: ``engine/src/graph/extraction.rs`` (D-272).
EXTRACTION_MAX_COMPLETION_TOKENS = 16_384
#: ``engine/src/chunker/mod.rs``: a window never splits deeper than this.
_MAX_SPLIT_DEPTH = 10

SYSTEM_MESSAGE = (
    "You are an entity and relationship extraction engine. Extract key entities and "
    "relationships from the provided text block into the requested JSON schema. Do not "
    "extract trivial or stopword entities."
)
USER_PREFIX = "Extract entities and relationships:\n\nText:\n"

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "maxLength": 128},
                    "entity_type": {"type": "string", "maxLength": 64},
                },
                "required": ["name", "entity_type"],
                "additionalProperties": False,
            },
            "maxItems": 32,
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "maxLength": 128},
                    "target": {"type": "string", "maxLength": 128},
                    "relation_type": {"type": "string", "maxLength": 64},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
                "required": ["source", "target", "relation_type", "confidence"],
                "additionalProperties": False,
            },
            "maxItems": 64,
        },
    },
    "required": ["entities", "relations"],
    "additionalProperties": False,
}

DEEPSEEK = "deepseek"
HAIKU = "haiku-5.5"
SONNET = "sonnet-5.5"


@dataclass(frozen=True)
class Writer:
    """One writer: its declaration (None for deepseek, whose body is the engine's) and
    the share of list price it is billed at."""

    name: str
    price: ReaderPrice
    price_factor: float
    declaration: ReaderDeclaration | None = None


#: deepseek at Wafer's wafer/us price (D-277), full price through the sync API (D-278).
#: Haiku 5.5 and Sonnet 5.5 at the S2 list prices (decisions 2026-10-30), half price on
#: the Batch API.
WRITERS: dict[str, Writer] = {
    DEEPSEEK: Writer(DEEPSEEK, ReaderPrice(0.0448, 0.30), 1.0),
    HAIKU: Writer(
        HAIKU,
        ReaderPrice(0.10, 0.50),
        BATCH_PRICE_FACTOR,
        ReaderDeclaration(
            slug="anthropic/claude-haiku-5.5",
            target="openrouter",
            thinking="off",
            price=ReaderPrice(0.10, 0.50),
        ),
    ),
    SONNET: Writer(
        SONNET,
        ReaderPrice(2.0, 10.0),
        BATCH_PRICE_FACTOR,
        ReaderDeclaration(
            slug="anthropic/claude-sonnet-5.5",
            target="openrouter",
            thinking="on",
            effort="low",
            price=ReaderPrice(2.0, 10.0),
        ),
    ),
}


class PilotError(ValueError):
    """An input or state the pilot refuses."""


# ---- chunks ----------------------------------------------------------------------

_HEADING_LIKE = re.compile(r"^ {0,3}(#{1,6}(\s|$)|=+\s*$|-+\s*$)", re.MULTILINE)


def _split_inclusive(text: str, sep: str) -> list[str]:
    # Rust's `str::split_inclusive`: each part keeps its separator, no empty tail.
    parts, start = [], 0
    while (i := text.find(sep, start)) != -1:
        parts.append(text[start : i + len(sep)])
        start = i + len(sep)
    if start < len(text):
        parts.append(text[start:])
    return parts


def _split_window(text: str, size: int, overlap: int, depth: int = 0) -> list[str]:
    if not text or size == 0:
        return []
    if len(text) <= size or depth >= _MAX_SPLIT_DEPTH:
        return [text]
    step = size - min(overlap, size - 1)
    windows, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        window = text[start:end]
        if window.strip():
            windows.append(window)
        if end == len(text):
            break
        start += step
    return windows


def chunk_structure_aware(
    text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """The engine's ``structure-aware`` chunks of a text without markdown headings.

    Raises:
        PilotError: If a line could be a markdown heading, which the port does not
            cover.
    """
    if _HEADING_LIKE.search(text):
        raise PilotError("the text has a heading-like line; the port covers none")
    chunks: list[str] = []
    for paragraph in _split_inclusive(text, "\n\n"):
        if paragraph.strip():
            chunks.extend(_split_window(paragraph, size, overlap))
    return chunks


def extractable(chunk: str) -> bool:
    """Whether the engine extracts the chunk (``MIN_CHUNK_CONTENT_LENGTH``)."""
    return len(chunk.strip().encode("utf-8")) >= MIN_CHUNK_CONTENT_LENGTH


@dataclass(frozen=True)
class PilotChunk:
    """One chunk sent to every writer; ``custom_id`` is its request ID everywhere."""

    custom_id: str
    doc_index: int
    chunk_index: int
    title: str
    source: str
    text: str


def load_documents(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or (
        repo_root() / "eval" / "corpora" / "multihop_rag" / "documents.subset.jsonl"
    )
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def select_documents(
    count: int, n: int = PILOT_DOCUMENTS, seed: int = PILOT_SEED
) -> list[int]:
    """The pilot's document indices: a seeded sample, in file order."""
    return sorted(random.Random(seed).sample(range(count), n))


def pilot_chunks(
    documents: Sequence[Mapping[str, Any]], indices: Iterable[int]
) -> list[PilotChunk]:
    """The extractable chunks of the selected documents, as the engine chunks them.

    A chunk's index counts every chunk of its document, as the engine's chunk IDs do.
    """
    chunks = []
    for d in indices:
        doc = documents[d]
        body = str(doc.get("text") or doc.get("body") or doc.get("content") or "")
        for i, text in enumerate(chunk_structure_aware(body)):
            if extractable(text):
                chunks.append(
                    PilotChunk(
                        custom_id=f"d{d:03d}-c{i:03d}",
                        doc_index=d,
                        chunk_index=i,
                        title=str(doc.get("title", "")),
                        source=str(doc.get("source", "")),
                        text=text,
                    )
                )
    return chunks


# ---- request bodies --------------------------------------------------------------


def _dumps(value: Any) -> str:
    # serde_json's compact form; the engine's keys are sorted, these keep source order.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _engine_settings() -> tuple[str, float, float, dict[str, Any]]:
    with (repo_root() / "config" / "config.toml").open("rb") as f:
        openrouter = tomllib.load(f)["openrouter"]
    pin: dict[str, Any] = {}
    order = openrouter.get("generation_provider_order") or []
    if order:
        pin = {"order": order, "allow_fallbacks": False}
    caps = {
        key: openrouter[f"generation_max_price_{key}"]
        for key in ("prompt", "completion")
        if f"generation_max_price_{key}" in openrouter
    }
    if caps:
        pin["max_price"] = caps
    return (
        openrouter["generation_model"],
        float(openrouter["temperature"]),
        float(openrouter["top_p"]),
        pin,
    )


def deepseek_body(chunk_text: str) -> str:
    """The engine's extraction body for a chunk, with ``config.toml``'s model, pin."""
    model, temperature, top_p, pin = _engine_settings()
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": USER_PREFIX + chunk_text},
        ],
        "temperature": temperature,
        "top_p": top_p,
        "max_completion_tokens": EXTRACTION_MAX_COMPLETION_TOKENS,
        "reasoning": {"effort": "none"},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "knowledge_graph_extraction",
                "strict": True,
                "schema": EXTRACTION_SCHEMA,
            },
        },
    }
    if pin:
        body["provider"] = pin
    return _dumps(body)


def writer_body(writer: Writer, chunk_text: str) -> str:
    """The body `writer` is sent for one chunk: the engine's, or its Claude rewrite."""
    body = deepseek_body(chunk_text)
    if writer.declaration is None:
        return body
    return rewrite_pack_body(body, writer.declaration).body_json


def requests_for(writer: Writer, chunks: Iterable[PilotChunk]) -> list[BatchRequest]:
    return [BatchRequest(c.custom_id, writer_body(writer, c.text)) for c in chunks]


# ---- estimate --------------------------------------------------------------------

#: The output tokens per chunk assumed before any writer has answered: about 15 entities
#: and 10 relations of compact JSON. Replaced by deepseek's measured mean once it has
#: run.
ASSUMED_OUTPUT_TOKENS = 400


def _o200k() -> tiktoken.Encoding:
    return tiktoken.get_encoding("o200k_base")


def input_tokens(chunk_text: str) -> int:
    """An o200k estimate of one request's input: both messages and the schema.

    Claude's tokenizer differs; the estimate is a proxy, and the measured counts
    replace it.
    """
    enc = _o200k()
    text = SYSTEM_MESSAGE + USER_PREFIX + chunk_text + _dumps(EXTRACTION_SCHEMA)
    return len(enc.encode_ordinary(text))


def usd(writer: Writer, prompt: float, completion: float) -> float:
    p = writer.price
    return (
        (prompt * p.input_per_mtok + completion * p.output_per_mtok)
        * writer.price_factor
        / 1_000_000
    )


def estimate(writer: Writer, chunks: Sequence[PilotChunk], output_tokens: float) -> str:
    """The D-258 estimate printed before a writer is paid for; it never refuses."""
    prompt = sum(input_tokens(c.text) for c in chunks)
    expected = usd(writer, prompt, output_tokens * len(chunks))
    bound = usd(writer, prompt, EXTRACTION_MAX_COMPLETION_TOKENS * len(chunks))
    slug = writer.declaration.slug if writer.declaration else "deepseek (engine body)"
    return (
        f"{writer.name}: {len(chunks)} chunk(s) to {slug} at {writer.price_factor} x "
        f"${writer.price.input_per_mtok}/${writer.price.output_per_mtok} per MTok: "
        f"about ${expected:.4f} (~{prompt} input tokens, o200k, and "
        f"{output_tokens:.0f} "
        f"output tokens a chunk), at most ${bound:.2f} if every answer reached "
        f"{EXTRACTION_MAX_COMPLETION_TOKENS} tokens."
    )


# ---- results ---------------------------------------------------------------------


def result_record(result: BatchResult, batch_id: str) -> dict[str, Any]:
    """One results line. It holds the answer and usage, never a key."""
    record: dict[str, Any] = {
        "custom_id": result.custom_id,
        "status": result.status,
        "batch_id": batch_id,
        "error": result.error,
    }
    if result.output is not None:
        record |= asdict(result.output)
    return record


def read_results(path: Path) -> dict[str, dict[str, Any]]:
    """The latest results line per chunk."""
    if not path.is_file():
        return {}
    latest: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                latest[record["custom_id"]] = record
    return latest


def _append(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(_dumps(r) + "\n")


def routing_problem(writer: Writer, record: Mapping[str, Any]) -> str | None:
    """Why a succeeded answer broke the writer's routing, or None.

    A Claude writer must be served by Anthropic over BYOK (``is_byok`` true, D-265,
    D-279); deepseek by the pinned endpoint with OpenRouter credit (``is_byok`` false).
    """
    if record["status"] != "succeeded":
        return None
    if writer.declaration is not None:
        if record.get("is_byok") is not True:
            return f"{record['custom_id']}: is_byok is {record.get('is_byok')!r}"
        if record.get("provider") != "Anthropic":
            return f"{record['custom_id']}: provider is {record.get('provider')!r}"
    elif record.get("is_byok") is not False:
        return f"{record['custom_id']}: is_byok is {record.get('is_byok')!r}"
    return None


def run_sync(
    writer: Writer,
    chunks: Sequence[PilotChunk],
    client: batch_client.OpenRouterChatClient,
    out: Path,
    *,
    echo: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Posts each chunk without a succeeded answer, one at a time; stops at a routing
    break.

    Each answer is appended as it arrives, so a rerun sends only the rest.
    """
    path = out / f"{writer.name}.results.jsonl"
    done = {cid for cid, r in read_results(path).items() if r["status"] == "succeeded"}
    records = []
    for request in requests_for(writer, [c for c in chunks if c.custom_id not in done]):
        record = result_record(client.complete(request), f"sync-{writer.name}")
        _append(path, [record])
        records.append(record)
        problem = routing_problem(writer, record)
        if problem is not None:
            raise PilotError(f"{writer.name} stopped on a routing break: {problem}")
    echo(f"{writer.name}: {len(records)} request(s) sent, {len(done)} already answered")
    return records


def _manifest_path(out: Path, writer: Writer) -> Path:
    return out / f"{writer.name}.batch.json"


#: Requests per OpenRouter batch: the S2 readers' batches of 500 ran whole (D-279).
BATCH_PART = 500


def submit_batch(
    writer: Writer,
    chunks: Sequence[PilotChunk],
    client: BatchClient,
    out: Path,
    *,
    echo: Callable[[str], None] = print,
    limit: int | None = None,
) -> list[str]:
    """Submits every chunk in batches of ``BATCH_PART``, in chunk order.

    The manifest is written after each part, so a rerun after a failed submit sends
    only the parts it lacks, and a writer whose parts are all submitted is refused.
    ``limit`` submits at most that many parts this call (a staged spend).

    Raises:
        PilotError: For deepseek, which has no batch (D-278), or if every part was
            submitted.
    """
    if writer.declaration is None:
        raise PilotError("deepseek has no batch variant; use `deepseek` (D-278)")
    path = _manifest_path(out, writer)
    requests = requests_for(writer, chunks)
    parts = [requests[i : i + BATCH_PART] for i in range(0, len(requests), BATCH_PART)]
    manifest: dict[str, Any] = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.is_file()
        else {"writer": writer.name, "endpoint": client.endpoint, "batches": []}
    )
    if len(manifest["batches"]) >= len(parts):
        raise PilotError(f"{path}: this writer's batches are already submitted")
    submitted = []
    todo = parts[len(manifest["batches"]) :]
    for part in todo[:limit] if limit is not None else todo:
        batch_id = client.submit(part)
        manifest["batches"].append({
            "batch_id": batch_id,
            "requests": len(part),
            "first": part[0].custom_id,
            "last": part[-1].custom_id,
            "bodies_sha256": hashlib.sha256(
                "\n".join(r.body_json for r in part).encode("utf-8")
            ).hexdigest(),
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        path.write_text(_dumps(manifest) + "\n", encoding="utf-8")
        submitted.append(batch_id)
        echo(f"{writer.name}: batch {batch_id} submitted, {len(part)} request(s)")
    return submitted


def fetch_batch(
    writer: Writer,
    client: BatchClient,
    out: Path,
    *,
    echo: Callable[[str], None] = print,
) -> bool:
    """Writes the results once every submitted batch has finished; False while one
    processes.

    A request of a submitted batch that returned no result for it gets an ``errored``
    line, with its batch's error when the batch failed whole. Chunks of parts not yet
    submitted get no line.
    """
    path = _manifest_path(out, writer)
    if not path.is_file():
        raise PilotError(f"no batch submitted for {writer.name} ({path} is missing)")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    finished = []
    for part in manifest["batches"]:
        results = client.results(part["batch_id"])
        if results is None:
            echo(f"{writer.name}: batch {part['batch_id']} is still processing")
            return False
        finished.append((part["batch_id"], results))
    records = []
    errors = {}
    for batch_id, results in finished:
        records += [result_record(r, batch_id) for r in results]
        errors[batch_id] = getattr(results, "error", None)
    returned = {r["custom_id"] for r in records}
    chunks = read_chunks(out)
    batch_of = {}
    for part in manifest["batches"]:
        for c in chunks:
            if part["first"] <= c.custom_id <= part["last"]:
                batch_of[c.custom_id] = part["batch_id"]
    records += [
        {
            "custom_id": cid,
            "status": "errored",
            "batch_id": batch_id,
            "error": errors.get(batch_id) or "no batch returned a result",
        }
        for cid, batch_id in batch_of.items()
        if cid not in returned
    ]
    _append(out / f"{writer.name}.results.jsonl", records)
    broken = [p for r in records if (p := routing_problem(writer, r))]
    echo(
        f"{writer.name}: {sum(r['status'] == 'succeeded' for r in records)} of "
        f"{len(records)} succeeded; routing breaks: {broken or 'none'}"
    )
    return True


# ---- reading the answers ---------------------------------------------------------


def parse_extraction(content: str) -> tuple[dict[str, Any] | None, str | None]:
    """The answer as ``ExtractionOutput``, or why the engine would refuse it.

    The engine deserialises with ``deny_unknown_fields`` and rejects a relation
    confidence outside [0, 1] (``validate_extraction_output``).
    """
    try:
        data = json.loads(content)
    except ValueError as exc:
        return None, f"not JSON: {exc}"
    if not isinstance(data, dict) or set(data) != {"entities", "relations"}:
        return None, "not an object of exactly entities and relations"
    entities, relations = data["entities"], data["relations"]
    if not isinstance(entities, list) or not isinstance(relations, list):
        return None, "entities or relations is not a list"
    for e in entities:
        if (
            not isinstance(e, dict)
            or set(e) != {"name", "entity_type"}
            or not all(isinstance(v, str) for v in e.values())
        ):
            return None, f"bad entity {e!r}"
    for r in relations:
        if not isinstance(r, dict) or set(r) != {
            "source",
            "target",
            "relation_type",
            "confidence",
        }:
            return None, f"bad relation {r!r}"
        c = r["confidence"]
        if isinstance(c, bool) or not isinstance(c, int | float) or not 0 <= c <= 1:
            return None, f"confidence out of range: {c!r}"
    return data, None


_MONTHS = {m.casefold() for m in calendar.month_name[1:] + calendar.month_abbr[1:]}
_WEEKDAYS = {d.casefold() for d in calendar.day_name}
_MONTH = "(" + "|".join(sorted(_MONTHS)) + ")"
#: A year, a month with an optional day and year, a day and month, or an ISO date.
_DATE_LIKE = re.compile(
    rf"^(\d{{4}}|{_MONTH}\.?( \d{{1,2}}(st|nd|rd|th)?)?(,? \d{{4}})?"
    rf"|\d{{1,2}} {_MONTH}( \d{{4}})?|\d{{4}}-\d{{2}}(-\d{{2}})?)$"
)


def _norm(name: str) -> str:
    return " ".join(name.casefold().split())


def junk_kind(name: str, publishers: Iterable[str]) -> str | None:
    """``date`` for a month, weekday, year or date; ``publisher`` for a corpus source
    (#126's junk entities); else None."""
    n = _norm(name)
    if n in _WEEKDAYS or _DATE_LIKE.match(n):
        return "date"
    if n in {_norm(p) for p in publishers}:
        return "publisher"
    return None


def read_chunks(out: Path) -> list[PilotChunk]:
    with (out / "chunks.jsonl").open(encoding="utf-8") as f:
        return [PilotChunk(**json.loads(line)) for line in f if line.strip()]


def write_chunks(out: Path, chunks: Iterable[PilotChunk]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(_dumps(asdict(c)) + "\n")


def summarise(
    writer: Writer,
    chunks: Sequence[PilotChunk],
    results: Mapping[str, Mapping[str, Any]],
    publishers: Iterable[str],
    reference: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """One writer's figures over the pilot's chunks (cost at list price x its factor).

    An ungrounded entity's normalised name is not in the chunk's normalised text: a
    paraphrase, or a name the writer brought from outside the chunk.
    ``reference`` (deepseek's results) adds the mean Jaccard overlap of normalised
    entity names, and of relation end pairs, on the chunks both answered validly.
    """
    publishers = list(publishers)
    ok = invalid = missing = 0
    prompt = completion = reasoning = 0
    reasoning_missing = 0
    entities = relations = dangling = ungrounded = 0
    junk: dict[str, int] = {"date": 0, "publisher": 0}
    junk_names: dict[str, int] = {}
    byok: set[Any] = set()
    overlaps: list[float] = []
    relation_overlaps: list[float] = []
    for c in chunks:
        r = results.get(c.custom_id)
        if r is None or r["status"] != "succeeded":
            missing += 1
            continue
        prompt += r["prompt_tokens"]
        completion += r["completion_tokens"]
        byok.add(r.get("is_byok"))
        if r["reasoning_tokens"] < 0:
            reasoning_missing += 1
        else:
            reasoning += r["reasoning_tokens"]
        data, _ = parse_extraction(r["content"])
        if data is None:
            invalid += 1
            continue
        ok += 1
        names = {_norm(e["name"]) for e in data["entities"]}
        entities += len(data["entities"])
        text = _norm(c.text)
        ungrounded += sum(_norm(e["name"]) not in text for e in data["entities"])
        relations += len(data["relations"])
        dangling += sum(
            _norm(x["source"]) not in names or _norm(x["target"]) not in names
            for x in data["relations"]
        )
        for e in data["entities"]:
            kind = junk_kind(e["name"], publishers)
            if kind:
                junk[kind] += 1
                junk_names[e["name"]] = junk_names.get(e["name"], 0) + 1
        ref = (reference or {}).get(c.custom_id)
        if ref is not None and ref["status"] == "succeeded":
            ref_data, _ = parse_extraction(ref["content"])
            if ref_data is not None:
                ref_names = {_norm(e["name"]) for e in ref_data["entities"]}
                overlaps.append(_jaccard(names, ref_names))
                relation_overlaps.append(
                    _jaccard(_relation_pairs(data), _relation_pairs(ref_data))
                )
    answered = len(chunks) - missing
    docs = len({c.doc_index for c in chunks})
    cost = usd(writer, prompt, completion)
    declaration = writer.declaration
    return {
        "writer": writer.name,
        "model": declaration.slug if declaration else _engine_settings()[0],
        "thinking": (
            f"{declaration.thinking}"
            + (f" (effort {declaration.effort})" if declaration.effort else "")
            if declaration
            else "reasoning effort none (engine body)"
        ),
        "price_factor": writer.price_factor,
        "chunks": len(chunks),
        "documents": docs,
        "answered": answered,
        "valid": ok,
        "invalid": invalid,
        "missing": missing,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "reasoning_unreported": reasoning_missing,
        "is_byok": sorted(map(str, byok)),
        "cost_usd": cost,
        "cost_per_chunk_usd": cost / answered if answered else None,
        "cost_per_document_usd": cost / docs if docs else None,
        "prompt_per_chunk": prompt / answered if answered else None,
        "completion_per_chunk": completion / answered if answered else None,
        "entities": entities,
        "relations": relations,
        "entities_per_chunk": entities / ok if ok else None,
        "relations_per_chunk": relations / ok if ok else None,
        "dangling_relations": dangling,
        "ungrounded_entities": ungrounded,
        "junk": junk,
        "top_junk": sorted(junk_names.items(), key=lambda kv: -kv[1])[:10],
        "entity_jaccard_vs_deepseek": (
            sum(overlaps) / len(overlaps) if overlaps else None
        ),
        "relation_pair_jaccard_vs_deepseek": (
            sum(relation_overlaps) / len(relation_overlaps)
            if relation_overlaps
            else None
        ),
    }


def _jaccard(a: set[Any], b: set[Any]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 1.0


def _relation_pairs(data: Mapping[str, Any]) -> set[tuple[str, str]]:
    # A relation as its unordered pair of normalised ends; the type's wording varies.
    return {
        tuple(sorted((_norm(r["source"]), _norm(r["target"]))))
        for r in data["relations"]
    }


# ---- command line ----------------------------------------------------------------

DEFAULT_OUT = Path("experiments") / "v1.1" / "writer-pilot"

app = typer.Typer(add_completion=False, help=__doc__)


def _writer(name: str) -> Writer:
    if name not in WRITERS:
        raise typer.BadParameter(f"unknown writer {name!r}; one of {list(WRITERS)}")
    return WRITERS[name]


def _out(out: Path) -> Path:
    return out if out.is_absolute() else repo_root() / out


def _publishers() -> list[str]:
    return sorted({str(d.get("source", "")) for d in load_documents()} - {""})


def _output_tokens(out: Path) -> float:
    ds = [
        r["completion_tokens"]
        for r in read_results(out / f"{DEEPSEEK}.results.jsonl").values()
        if r["status"] == "succeeded"
    ]
    return sum(ds) / len(ds) if ds else ASSUMED_OUTPUT_TOKENS


@app.command()
def plan(out: Path = DEFAULT_OUT) -> None:
    """Free: selects the documents, writes ``chunks.jsonl``, prints every estimate."""
    out = _out(out)
    documents = load_documents()
    chunks = pilot_chunks(documents, select_documents(len(documents)))
    write_chunks(out, chunks)
    typer.echo(
        f"{len({c.doc_index for c in chunks})} documents, {len(chunks)} extractable "
        f"chunks -> {out / 'chunks.jsonl'}"
    )
    tokens = _output_tokens(out)
    for writer in WRITERS.values():
        typer.echo(estimate(writer, chunks, tokens))


@app.command()
def deepseek(out: Path = DEFAULT_OUT) -> None:
    """Paid: deepseek's extraction of every chunk through the sync API (D-278)."""
    out = _out(out)
    chunks = read_chunks(out)
    writer = WRITERS[DEEPSEEK]
    typer.echo(estimate(writer, chunks, _output_tokens(out)))
    run_sync(writer, chunks, batch_client.chat_client(), out, echo=typer.echo)


@app.command()
def canary(writer: str, out: Path = DEFAULT_OUT) -> None:
    """Paid: one chunk to a Claude writer through the sync API, checking BYOK first."""
    w = _writer(writer)
    out = _out(out)
    chunk = read_chunks(out)[:1]
    canary_writer = Writer(f"{w.name}.canary", w.price, 1.0, w.declaration)
    typer.echo(estimate(canary_writer, chunk, _output_tokens(out)))
    run_sync(canary_writer, chunk, batch_client.chat_client(), out, echo=typer.echo)
    # A rerun sends nothing once the chunk is answered; show the recorded answer.
    for r in read_results(out / f"{canary_writer.name}.results.jsonl").values():
        data, why = parse_extraction(r.get("content") or "")
        typer.echo(
            f"{r['custom_id']}: {r['status']} is_byok={r.get('is_byok')} "
            f"provider={r.get('provider')} "
            f"reasoning_tokens={r.get('reasoning_tokens')} "
            f"tokens={r.get('prompt_tokens')}/{r.get('completion_tokens')} "
            f"schema={'ok' if data else why} error={r.get('error')}"
        )


@app.command()
def submit(
    writer: str,
    out: Path = DEFAULT_OUT,
    parts: int | None = typer.Option(None, help="Submit at most this many batches."),
) -> None:
    """Paid: OpenRouter batches of every chunk for a Claude writer."""
    w = _writer(writer)
    out = _out(out)
    chunks = read_chunks(out)
    typer.echo(estimate(w, chunks, _output_tokens(out)))
    client = batch_client.OpenRouterBatchClient(
        os.environ.get("OPENROUTER_API_KEY", "")
    )
    submit_batch(w, chunks, client, out, echo=typer.echo, limit=parts)


@app.command()
def fetch(writer: str, out: Path = DEFAULT_OUT) -> None:
    """Free: writes a finished batch's results."""
    w = _writer(writer)
    client = batch_client.OpenRouterBatchClient(
        os.environ.get("OPENROUTER_API_KEY", "")
    )
    fetch_batch(w, client, _out(out), echo=typer.echo)


@app.command()
def report(out: Path = DEFAULT_OUT) -> None:
    """Free: every writer's figures as JSON (``summary.json``) and on stdout."""
    out = _out(out)
    chunks = read_chunks(out)
    publishers = _publishers()
    reference = read_results(out / f"{DEEPSEEK}.results.jsonl")
    summary = [
        summarise(
            w,
            chunks,
            read_results(out / f"{w.name}.results.jsonl"),
            publishers,
            None if w.name == DEEPSEEK else reference,
        )
        for w in WRITERS.values()
    ]
    text = json.dumps(summary, indent=2, ensure_ascii=False)
    (out / "summary.json").write_text(text + "\n", encoding="utf-8")
    typer.echo(text)


if __name__ == "__main__":
    app()
