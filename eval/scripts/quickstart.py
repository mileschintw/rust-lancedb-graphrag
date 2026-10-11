"""Ingest and query helper for the README quickstart (06.4 D-68, D-220, D-221).

One script, two subcommands, so PowerShell and bash run the same commands and never
differ in JSON quoting. From the repository root:

    uv run --project eval python eval/scripts/quickstart.py ingest
    uv run --project eval python eval/scripts/quickstart.py query "<question>"
    uv run --project eval python eval/scripts/quickstart.py query "<question>" --graph

and, to run only the levers a request names (none here):

    uv run --project eval python eval/scripts/quickstart.py query Q --no-default-levers

``ingest`` posts every document in the bundled sample manifest
(``eval/corpora/quickstart/documents.json``) to ``POST /documents`` with the three
evidence-metadata form fields (``doc_title``, ``source``, ``published_date``), then
polls ``GET /documents/{id}`` until each document is ``completed`` or ``failed``. One
JSON line per document goes to stdout. A single overall deadline (``--timeout-s``,
default 420) covers every post and every poll, so one call stays bounded; when it
expires the script prints one line per document still pending and exits non-zero.

``query`` sends one question through ``lancet_eval.client.run_query`` with a W3C
``traceparent`` header, so the printed ``trace_id`` is the one to paste into Jaeger.
By default the request names no graph and no lever field, so the engine applies its
configured defaults (graph context off, ``rerank`` and ``evidence_metadata`` levers).
``--graph`` sends ``disable_graph_context: false`` (D-207); ``--no-default-levers``
sends ``disable_default_levers: true`` (D-198). It prints one JSON object.

The script reads no secret and prints no environment value: the only environment
variable it consults is ``LANCET_EVAL__GATEWAY_URL``, for the default gateway URL.
All JSON is printed ASCII-escaped so a Windows console codepage cannot fail on model
text. Exit status: 0 on success, 1 on a failed or pending document, a rejected post
or a query error, 2 on a bad manifest.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from lancet_eval.client import HarnessStreamError, QueryOutcome, run_query
from lancet_eval.config import repo_root

DEFAULT_GATEWAY = "http://127.0.0.1:8080"
GATEWAY_ENV = "LANCET_EVAL__GATEWAY_URL"
DEFAULT_MANIFEST = repo_root() / "eval" / "corpora" / "quickstart" / "documents.json"
DEFAULT_INGEST_TIMEOUT_S = 420.0
DEFAULT_QUERY_TIMEOUT_S = 180.0
POST_TIMEOUT_CAP_S = 60.0
POLL_TIMEOUT_CAP_S = 15.0
ANSWER_LIMIT = 300
ACCEPTED_POST_STATUSES = (200, 201, 202)
TERMINAL_STATUSES = ("completed", "failed")
MANIFEST_FIELDS = ("file", "doc_title", "source", "published_date")


def _default_gateway() -> str:
    return os.environ.get(GATEWAY_ENV) or DEFAULT_GATEWAY


def build_parser() -> argparse.ArgumentParser:
    """Builds the command line; ``--gateway`` is accepted before or after the verb."""
    parser = argparse.ArgumentParser(
        prog="quickstart.py",
        description="Ingest the bundled sample and query the Lancet gateway.",
    )
    parser.add_argument(
        "--gateway",
        default=_default_gateway(),
        help=f"Gateway base URL (default: ${GATEWAY_ENV} or {DEFAULT_GATEWAY}).",
    )
    # SUPPRESS keeps a --gateway given before the verb when none follows the verb.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--gateway", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    verbs = parser.add_subparsers(dest="command", required=True)

    ingest = verbs.add_parser(
        "ingest",
        parents=[shared],
        help="Post the sample documents and wait until each is terminal.",
    )
    ingest.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Manifest of {file, doc_title, source, published_date} rows.",
    )
    ingest.add_argument(
        "--timeout-s",
        type=float,
        default=DEFAULT_INGEST_TIMEOUT_S,
        help="Overall deadline for every post and poll, in seconds (default 420).",
    )
    ingest.set_defaults(func=_ingest)

    query = verbs.add_parser(
        "query", parents=[shared], help="Send one question and print a summary."
    )
    query.add_argument("text", help="The question to ask.")
    query.add_argument(
        "--graph",
        action="store_true",
        help='Send "disable_graph_context": false (graph context on, D-207).',
    )
    query.add_argument(
        "--no-default-levers",
        action="store_true",
        help='Send "disable_default_levers": true (only named levers run, D-198).',
    )
    query.add_argument(
        "--timeout-s",
        type=float,
        default=DEFAULT_QUERY_TIMEOUT_S,
        help="Wall-clock deadline for the whole query, in seconds (default 180).",
    )
    query.set_defaults(func=_query)
    return parser


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload), flush=True)


def _load_manifest(path: Path) -> list[dict[str, str]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("the manifest must be a non-empty JSON list")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"manifest row {index} is not an object")
        for field in MANIFEST_FIELDS:
            if not isinstance(row.get(field), str) or not row[field]:
                raise ValueError(f"manifest row {index} lacks a non-empty {field!r}")
    return rows


def _status_of(data: object) -> str:
    if isinstance(data, dict):
        return str(data.get("status") or data.get("Status") or "")
    return ""


def _post_document(
    client: httpx.Client, entry: dict[str, str], base_dir: Path, remaining: float
) -> dict[str, Any]:
    """Posts one document; returns the state row for it."""
    row: dict[str, Any] = {
        "file": entry["file"],
        "document_id": "",
        "status": "pending",
        "last_status": "",
    }
    content = (base_dir / entry["file"]).read_bytes()
    files = {"file": (entry["file"], content, "text/markdown")}
    form = {field: entry[field] for field in MANIFEST_FIELDS if field != "file"}
    try:
        response = client.post(
            "/documents",
            files=files,
            data=form,
            timeout=httpx.Timeout(min(POST_TIMEOUT_CAP_S, remaining)),
        )
    except httpx.HTTPError as exc:
        row.update(status="post_failed", error=type(exc).__name__)
        return row
    if response.status_code not in ACCEPTED_POST_STATUSES:
        row.update(
            status="post_failed",
            http_status=response.status_code,
            error=response.text[:200],
        )
        return row
    try:
        data = response.json()
    except ValueError:
        data = None
    document_id = ""
    if isinstance(data, dict):
        document_id = str(data.get("id") or data.get("ID") or "")
    if not document_id:
        row.update(status="post_failed", error="the response carried no document id")
        return row
    row["document_id"] = document_id
    row["last_status"] = _status_of(data)
    if row["last_status"] in TERMINAL_STATUSES:
        row["status"] = row["last_status"]
    return row


def _poll_document(client: httpx.Client, row: dict[str, Any], remaining: float) -> None:
    """Polls one document once and updates its row in place."""
    try:
        response = client.get(
            f"/documents/{row['document_id']}",
            timeout=httpx.Timeout(min(POLL_TIMEOUT_CAP_S, remaining)),
        )
    except httpx.HTTPError:
        return
    if response.status_code != 200:
        # A 404 straight after the post means the row is not visible yet: keep waiting.
        return
    try:
        data = response.json()
    except ValueError:
        return
    status = _status_of(data)
    if status:
        row["last_status"] = status
    if status in TERMINAL_STATUSES:
        row["status"] = status
        if status == "failed" and isinstance(data, dict):
            message = data.get("error_message") or data.get("ErrorMessage")
            row["error_message"] = str(message or "unknown error")


def _still_open(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["status"] == "pending" and r["document_id"]]


def _ingest(args: argparse.Namespace) -> int:
    manifest_path: Path = args.manifest
    try:
        entries = _load_manifest(manifest_path)
    except (OSError, ValueError) as exc:
        print(f"quickstart.py: bad manifest {manifest_path}: {exc}", file=sys.stderr)
        return 2
    base_dir = manifest_path.parent
    deadline = time.monotonic() + args.timeout_s

    rows: list[dict[str, Any]] = [
        {"file": e["file"], "document_id": "", "status": "pending", "last_status": ""}
        for e in entries
    ]
    with httpx.Client(base_url=args.gateway) as client:
        for index, entry in enumerate(entries):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                rows[index] = _post_document(client, entry, base_dir, remaining)
            except OSError as exc:
                rows[index].update(status="post_failed", error=type(exc).__name__)

        interval = 0.5
        while _still_open(rows):
            for row in _still_open(rows):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                _poll_document(client, row, remaining)
            if not _still_open(rows):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))
            interval = min(2.0, interval * 1.5)

    for row in rows:
        _emit(row)
    completed = sum(1 for r in rows if r["status"] == "completed")
    print(f"ingest: {completed} of {len(rows)} documents completed", file=sys.stderr)
    return 0 if completed == len(rows) else 1


def _summary(outcome: QueryOutcome, trace_id: str) -> dict[str, Any]:
    meta = outcome.workflow_meta
    snapshot = outcome.answer.snapshot if outcome.answer else None
    if snapshot is None:
        snapshot = outcome.partial_snapshot
    answer = outcome.answer.answer if outcome.answer else ""
    return {
        "trace_id": trace_id,
        "status": outcome.status,
        "degraded_mode": bool(meta.degraded_mode) if meta else False,
        "notice_codes": [n.typed_code for n in outcome.notices],
        "notices": [n.code for n in outcome.notices],
        "levers": list(snapshot.levers) if snapshot else [],
        "graph_path_found": meta.graph_path_found if meta else None,
        "node_timings": [
            {"node_name": t.node_name, "duration_ms": t.duration_ms}
            for t in outcome.node_timings
        ],
        "answer": answer[:ANSWER_LIMIT],
    }


def _query(args: argparse.Namespace) -> int:
    trace_id = secrets.token_hex(16)
    span_id = secrets.token_hex(8)
    # 06-CONTEXT D-28: the gateway honours an inbound W3C traceparent, so this id is the
    # one Jaeger shows for the request.
    headers = {"traceparent": f"00-{trace_id}-{span_id}-01"}
    try:
        with httpx.Client(base_url=args.gateway, headers=headers) as client:
            outcome = run_query(
                client,
                query=args.text,
                disable_graph_context=False if args.graph else None,
                disable_default_levers=True if args.no_default_levers else None,
                deadline_s=args.timeout_s,
            )
    except (HarnessStreamError, httpx.HTTPError) as exc:
        _emit({
            "trace_id": trace_id,
            "error": type(exc).__name__,
            "message": str(exc)[:500],
        })
        return 1
    _emit(_summary(outcome, trace_id))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the chosen subcommand and returns its exit status."""
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
