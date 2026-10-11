"""Read settled OpenRouter usage without printing the key (06.4 plan 08, D-222).

Stdlib only. Reads ``OPENROUTER_API_KEY`` from the environment; the value is used only as
a request header and is never printed, logged or written.

Takes readings of ``GET https://openrouter.ai/api/v1/auth/key`` ``data.usage`` 60 s apart
until two consecutive readings agree (the account figure lags, 06.3.4.1-27), with a 20 s
timeout on each request and a hard overall deadline of 420 s from start, so one call never
exceeds about 7.5 minutes. This is the 06.3.5/06.3.6 settled-reading method.

Writes ``{settled_usage, settled_at, readings: [{at, usage}]}`` to ``--out`` and stdout.
Exit status: 0 settled, 1 no key, a rejected key (HTTP 401 or 403) or no usable reading, 2 the readings
had not settled by the deadline (``settled_usage`` is then null).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

URL = "https://openrouter.ai/api/v1/auth/key"
INTERVAL_S = 60.0
REQUEST_TIMEOUT_S = 20.0
OVERALL_DEADLINE_S = 420.0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AuthRejected(Exception):
    """The key-status endpoint rejected the key; retrying cannot help."""


def _read_usage(api_key: str, timeout_s: float) -> float | None:
    request = urllib.request.Request(URL, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f"qs-settle.py: HTTP {exc.code} from the key-status endpoint", file=sys.stderr)
        if exc.code in (401, 403):
            raise AuthRejected from exc
        return None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        print(f"qs-settle.py: {type(exc).__name__} reading the key-status endpoint", file=sys.stderr)
        return None
    usage = (payload.get("data") or {}).get("usage")
    return float(usage) if isinstance(usage, (int, float)) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        print("qs-settle.py: OPENROUTER_API_KEY is not set", file=sys.stderr)
        return 1

    started = time.monotonic()
    deadline = started + OVERALL_DEADLINE_S
    readings: list[dict[str, Any]] = []
    settled: float | None = None
    settled_at: str | None = None
    while True:
        remaining = deadline - time.monotonic()
        try:
            usage = _read_usage(api_key, min(REQUEST_TIMEOUT_S, max(remaining, 1.0)))
        except AuthRejected:
            return 1
        if usage is not None:
            readings.append({"at": _now(), "usage": usage})
            if len(readings) >= 2 and readings[-1]["usage"] == readings[-2]["usage"]:
                settled = readings[-1]["usage"]
                settled_at = readings[-1]["at"]
                break
        if time.monotonic() + INTERVAL_S >= deadline:
            break
        time.sleep(INTERVAL_S)

    result = {"settled_usage": settled, "settled_at": settled_at, "readings": readings}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if settled is not None:
        return 0
    return 2 if readings else 1


if __name__ == "__main__":
    sys.exit(main())
