"""Fetch one trace from the local Jaeger and check its span names (06.4 plan 08, D-220).

Stdlib only; read-only GETs against 127.0.0.1:16686.

    python qs-trace.py --trace-id <32 hex> --out <file.json> \
        --expect lancet-gateway-op --expect another-op --forbid some-op

Polls ``/api/traces/<id>`` for up to 60 s until every ``--expect`` operation name is
present, writes the trace JSON to ``--out`` (its parent directory is created), prints the
span count and the sorted unique operation names, and exits 1 when an expectation fails or
a ``--forbid`` name appears.

The gateway installs the W3C TraceContext propagator
(``gateway/internal/telemetry/telemetry.go:136-137``), so the id ``quickstart.py`` sends is
expected to be the trace id. When that id is not found within 60 s the script falls back to
``/api/traces?service=lancet-gateway&lookback=15m&limit=20``, picks the newest trace whose
span set meets the expectations, prints
``inbound traceparent not honoured; matched by content: <id>`` and the transcript records it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

JAEGER = "http://127.0.0.1:16686"
POLL_DEADLINE_S = 60.0
POLL_INTERVAL_S = 2.0
REQUEST_TIMEOUT_S = 20.0
SERVICE = "lancet-gateway"


def _get(url: str) -> dict[str, Any] | None:
    """GET a Jaeger JSON document; None when the trace is not there (yet)."""
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_S) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        print(f"qs-trace.py: HTTP {exc.code} from {url}", file=sys.stderr)
        return None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        print(f"qs-trace.py: {type(exc).__name__} from {url}", file=sys.stderr)
        return None


def _operations(trace: dict[str, Any]) -> set[str]:
    return {str(span.get("operationName", "")) for span in trace.get("spans", [])}


def _check(
    operations: set[str], expect: list[str], forbid: list[str]
) -> tuple[list[str], list[str]]:
    missing = [name for name in expect if name not in operations]
    present_forbidden = [name for name in forbid if name in operations]
    return missing, present_forbidden


def _newest_first(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def started(trace: dict[str, Any]) -> int:
        times = [int(span.get("startTime", 0)) for span in trace.get("spans", [])]
        return max(times) if times else 0

    return sorted(traces, key=started, reverse=True)


def _report(trace: dict[str, Any], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"data": [trace]}, indent=2), encoding="utf-8")
    operations = sorted(_operations(trace))
    print(f"trace_id: {trace.get('traceID', '')}")
    print(f"span_count: {len(trace.get('spans', []))}")
    print("operations: " + ", ".join(operations))
    print(f"wrote: {out}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--expect", action="append", default=[], metavar="NAME")
    parser.add_argument("--forbid", action="append", default=[], metavar="NAME")
    args = parser.parse_args(argv)

    deadline = time.monotonic() + POLL_DEADLINE_S
    found: dict[str, Any] | None = None
    while True:
        document = _get(f"{JAEGER}/api/traces/{args.trace_id}")
        if document and document.get("data"):
            found = document["data"][0]
            missing, _ = _check(_operations(found), args.expect, args.forbid)
            if not missing:
                break
        if time.monotonic() >= deadline:
            break
        time.sleep(POLL_INTERVAL_S)

    if found is not None:
        missing, forbidden = _check(_operations(found), args.expect, args.forbid)
        _report(found, args.out)
        if missing:
            print("FAIL: expected operations missing: " + ", ".join(missing))
        if forbidden:
            print("FAIL: forbidden operations present: " + ", ".join(forbidden))
        return 1 if (missing or forbidden) else 0

    # The id was not found within the deadline: match a recent trace by content.
    listing = _get(
        f"{JAEGER}/api/traces?service={SERVICE}&lookback=15m&limit=20"
    )
    for trace in _newest_first((listing or {}).get("data", [])):
        missing, forbidden = _check(_operations(trace), args.expect, args.forbid)
        if not missing and not forbidden:
            print(
                "inbound traceparent not honoured; matched by content: "
                f"{trace.get('traceID', '')}"
            )
            _report(trace, args.out)
            return 0
    print(f"FAIL: trace {args.trace_id} not found and no recent trace matched")
    return 1


if __name__ == "__main__":
    sys.exit(main())
