"""The S1 run guide's store checks agree with the code (#79)."""

from __future__ import annotations

import re

from lancet_eval.config import repo_root

GUIDE = repo_root() / "experiments" / "v1.1" / "RUN-S0-S1.md"


def _guide_sql() -> list[str]:
    text = GUIDE.read_text(encoding="utf-8")
    return re.findall(r'psql -U postgres -d lancet -c "([^"]+)"', text)


def test_step_1_4_count_ignores_failed_upload_rows() -> None:
    """A failed row left by seed's retry must not raise the S1 count above 346."""
    counts = [
        sql for sql in _guide_sql() if "count(*)" in sql and "lancet_eval_s1" in sql
    ]

    assert counts, "step 1.4's count query not found"
    assert all("WHERE status = 'completed'" in sql for sql in counts)


def test_guide_lists_the_rows_the_recovery_step_removes() -> None:
    listing = [sql for sql in _guide_sql() if "status <> 'completed'" in sql]

    assert listing == [
        "SELECT id, status, error_message FROM lancet_eval_s1.documents "
        "WHERE status <> 'completed';"
    ]
    assert "identity pg-delete-extras --store eval-s1" in GUIDE.read_text(
        encoding="utf-8"
    )
