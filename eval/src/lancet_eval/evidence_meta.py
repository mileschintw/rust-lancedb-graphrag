"""Evidence-metadata normalisation shared by fresh ingest and the backfill (D-142).

One function, `normalise`, turns a raw corpus row into the three values the gateway
accepts as the multipart form fields `doc_title`, `source` and `published_date`. Both
`seed.py` (fresh ingest) and `eval/scripts/build_metadata_sidecar.py` (backfill) call
it, so a backfilled value equals what a fresh ingest writes by construction. The Rust
engine grows no entity decoder: HTML entities are decoded here, once, before the value
leaves the harness.

Rules (D-142):

- `doc_title`: `html.unescape(title).strip()`.
- `source`: `source.strip()`.
- `published_date`: the UTC calendar date `YYYY-MM-DD` of an ISO 8601 `published_at`,
  or `None` when it does not parse. A timestamp with no offset is read as UTC.
- Every empty or missing value is `None`. `normalise` never raises on a malformed row.

The gateway bounds (`doc_title` at most 512 characters, `source` at most 256) are not
enforced here: an over-length value is refused at the edge with a 400, not silently
truncated into a value the backfill would then disagree with.
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from datetime import UTC, datetime

#: The multipart form-field names, in the order the gateway documents them.
FIELD_NAMES = ("doc_title", "source", "published_date")


def _clean_text(value: object, *, unescape: bool) -> str | None:
    """Strips a string, optionally decoding HTML entities. Non-strings give `None`."""
    if not isinstance(value, str):
        return None
    text = html.unescape(value) if unescape else value
    text = text.strip()
    return text or None


def _utc_date(value: object) -> str | None:
    """Renders an ISO 8601 timestamp as its UTC `YYYY-MM-DD` date, or `None`."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).date().isoformat()


def normalise(raw: Mapping[str, object]) -> dict[str, str | None]:
    """Normalises a raw corpus row into `doc_title`, `source` and `published_date`.

    Reads the keys `title`, `source` and `published_at`. All three result keys are
    always present; an absent, empty or unparseable input gives `None`.
    """
    return {
        "doc_title": _clean_text(raw.get("title"), unescape=True),
        "source": _clean_text(raw.get("source"), unescape=False),
        "published_date": _utc_date(raw.get("published_at")),
    }
