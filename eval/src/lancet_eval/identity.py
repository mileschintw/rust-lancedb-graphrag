"""Index identity comparison between PostgreSQL, LanceDB, and the document map.

Compares the document-ID sets recorded in PostgreSQL (`lancet_eval.documents`),
LanceDB (`documents`, distinct `nodes.document_id`, and `edges`/
`entity_edges.document_id` as subsets), and the committed `document_map.json`
for a corpus. The gate exists to prevent a drive or measurement pass from
running against a store whose contents have drifted from what the harness
believes it seeded (D-61).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lancet_eval.config import EvalSettings, repo_root
from lancet_eval.seed import (
    SeedError,
    assert_schema_isolated,
    load_document_map,
    run_psql,
)

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class IdentityGateError(RuntimeError):
    """Raised when the three-way document identity comparison fails or cannot run."""


class IdentityReport(BaseModel):
    """Result of comparing document ID sets across PostgreSQL, LanceDB, and the map."""

    model_config = ConfigDict(extra="forbid")

    map_ids: list[str] = Field(default_factory=list)
    lance_documents: list[str] = Field(default_factory=list)
    lance_nodes: list[str] = Field(default_factory=list)
    lance_edges: list[str] = Field(default_factory=list)
    lance_entity_edges: list[str] = Field(default_factory=list)
    pg_status: dict[str, str] = Field(default_factory=dict)
    staged_rows: int = 0
    alias_ids: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    passed: bool = True


def list_lancedb_document_ids(lancedb_path: str) -> dict[str, Any]:
    """Run `inspect_lancedb --document-ids` and parse its JSON contract.

    Returns a dict with keys `documents`, `nodes`, `edges`, `entity_edges` (each a
    list of document_id strings) and `staged_documents_v2_rows` (an int). The first
    invocation compiles the binary via `cargo run`, which is why the timeout is long.
    """
    cmd = [
        "cargo",
        "run",
        "--manifest-path",
        "engine/Cargo.toml",
        "--release",
        "--quiet",
        "--bin",
        "inspect_lancedb",
        "--",
        "--document-ids",
        "--lancedb-path",
        str(lancedb_path),
    ]
    try:
        res = subprocess.run(
            cmd,
            cwd=repo_root(),
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except subprocess.TimeoutExpired as exc:
        raise IdentityGateError(
            f"inspect_lancedb --document-ids timed out: {exc}"
        ) from exc

    if res.returncode != 0:
        err = res.stderr or res.stdout
        raise IdentityGateError(
            f"inspect_lancedb --document-ids failed (exit {res.returncode}): {err}"
        )

    try:
        data = json.loads(res.stdout)
    except Exception as exc:
        raise IdentityGateError(
            f"inspect_lancedb --document-ids produced unparseable output: {exc}"
        ) from exc

    required = (
        "documents",
        "nodes",
        "edges",
        "entity_edges",
        "staged_documents_v2_rows",
    )
    missing = [k for k in required if k not in data]
    if missing:
        raise IdentityGateError(
            f"inspect_lancedb --document-ids output missing keys: {missing}"
        )
    return data


def list_pg_documents(settings: EvalSettings) -> dict[str, str]:
    """List PostgreSQL `lancet_eval.documents` IDs and statuses via `run_psql`."""
    sql = "SELECT id, status FROM lancet_eval.documents ORDER BY id;"
    output = run_psql(settings, sql)
    result: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("|", 1)
        if len(parts) != 2:
            continue
        doc_id, status = parts
        result[doc_id.strip()] = status.strip()
    return result


def compute_identity(settings: EvalSettings, corpus_name: str) -> IdentityReport:
    """Compare document ID sets across PostgreSQL, LanceDB, and the committed map.

    Uses `load_document_map(corpus_name)` so a corpus that indirects through
    `map_corpus` (e.g. a diagnostic corpus) resolves to the one shared map.
    """
    doc_map = load_document_map(corpus_name)
    map_ids = set(doc_map.entries.keys())
    # Only the alias *keys* (stale IDs that resolve elsewhere via aliasing) must be
    # absent from the stores. Alias *values* are the canonical current document_id
    # they resolve to and are expected to be present as ordinary map entries (D-60).
    alias_ids = set(doc_map.aliases.keys())

    lance_data = list_lancedb_document_ids(settings.lancedb_path)
    pg_status = list_pg_documents(settings)

    lance_documents = set(lance_data.get("documents", []))
    lance_nodes = set(lance_data.get("nodes", []))
    lance_edges = set(lance_data.get("edges", []))
    lance_entity_edges = set(lance_data.get("entity_edges", []))
    staged_rows = int(lance_data.get("staged_documents_v2_rows", 0))

    pg_ids = set(pg_status.keys())

    failures: list[str] = []

    extra_in_lance_docs = lance_documents - map_ids
    missing_from_lance_docs = map_ids - lance_documents
    if extra_in_lance_docs or missing_from_lance_docs:
        failures.append(
            "LanceDB documents vs map mismatch: "
            f"extra_in_lance={sorted(extra_in_lance_docs)}, "
            f"missing_from_lance={sorted(missing_from_lance_docs)}"
        )

    extra_in_nodes = lance_nodes - map_ids
    missing_from_nodes = map_ids - lance_nodes
    if extra_in_nodes or missing_from_nodes:
        failures.append(
            "LanceDB nodes vs map mismatch: "
            f"extra_in_nodes={sorted(extra_in_nodes)}, "
            f"missing_from_nodes={sorted(missing_from_nodes)}"
        )

    extra_entity_edges = lance_entity_edges - map_ids
    if extra_entity_edges:
        failures.append(
            f"entity_edges document_id outside map: {sorted(extra_entity_edges)}"
        )

    extra_edges = lance_edges - map_ids
    if extra_edges:
        failures.append(f"edges document_id outside map: {sorted(extra_edges)}")

    extra_in_pg = pg_ids - map_ids
    missing_from_pg = map_ids - pg_ids
    if extra_in_pg or missing_from_pg:
        failures.append(
            "PostgreSQL documents vs map mismatch: "
            f"extra_in_pg={sorted(extra_in_pg)}, "
            f"missing_from_pg={sorted(missing_from_pg)}"
        )

    non_completed = {
        doc_id: status for doc_id, status in pg_status.items() if status != "completed"
    }
    if non_completed:
        failures.append(
            f"PostgreSQL rows not completed: {sorted(non_completed.items())}"
        )

    alias_present_lance = alias_ids & (
        lance_documents | lance_nodes | lance_edges | lance_entity_edges
    )
    alias_present_pg = alias_ids & pg_ids
    if alias_present_lance or alias_present_pg:
        failures.append(
            "alias_present: "
            f"lance={sorted(alias_present_lance)}, pg={sorted(alias_present_pg)}"
        )

    if staged_rows > 0:
        failures.append(
            f"staged_rows_present: {staged_rows} row(s) in staged_documents_v2"
        )

    return IdentityReport(
        map_ids=sorted(map_ids),
        lance_documents=sorted(lance_documents),
        lance_nodes=sorted(lance_nodes),
        lance_edges=sorted(lance_edges),
        lance_entity_edges=sorted(lance_entity_edges),
        pg_status=pg_status,
        staged_rows=staged_rows,
        alias_ids=sorted(alias_ids),
        failures=failures,
        passed=not failures,
    )


def require_index_identity(settings: EvalSettings, corpus_name: str) -> IdentityReport:
    """Compute the identity report and raise `IdentityGateError` if it fails.

    There is no parameter, keyword argument, or environment variable that skips this
    check (T-06.3.4.1-02-02). Callers that need to bypass it for testing patch
    `list_lancedb_document_ids` / `list_pg_documents`, not this function.
    """
    try:
        report = compute_identity(settings, corpus_name)
    except IdentityGateError:
        raise
    except SeedError as exc:
        raise IdentityGateError(f"Identity gate could not run: {exc}") from exc
    if not report.passed:
        raise IdentityGateError(
            "Index identity gate failed: " + "; ".join(report.failures)
        )
    return report


def delete_pg_extras(
    settings: EvalSettings,
    allow_ids: set[str],
    *,
    apply: bool,
    pg_dump_path: Path | None = None,
) -> list[str]:
    """Delete PostgreSQL documents not present in `allow_ids`.

    Refuses to run against anything but the isolated `lancet_eval` schema, refuses
    an empty `allow_ids` (which would otherwise delete every document), and refuses
    any non-UUID allow_id before any SQL is built. In apply mode, refuses to run
    without an existing non-empty `pg_dump_path` snapshot, executes the delete as a
    single transaction, and returns the deleted IDs re-listed afterwards to confirm
    the set. Dry-run (the default) returns the extra IDs and executes no DELETE.
    """
    schema_name = assert_schema_isolated(settings)
    if schema_name != "lancet_eval":
        raise SeedError(
            f"delete_pg_extras refuses non-'lancet_eval' schema, got {schema_name!r}"
        )
    if not allow_ids:
        raise SeedError(
            "delete_pg_extras refuses an empty allow_ids (would delete every document)"
        )
    for doc_id in allow_ids:
        if not _UUID_RE.match(doc_id):
            raise SeedError(f"delete_pg_extras refuses non-UUID allow_id: {doc_id!r}")

    current = list_pg_documents(settings)
    extra_ids = sorted(set(current.keys()) - set(allow_ids))

    if not apply:
        return extra_ids

    if not extra_ids:
        return extra_ids

    if pg_dump_path is None:
        raise SeedError(
            "delete_pg_extras refuses to apply without an existing non-empty "
            "pg_dump_path"
        )
    dump_path = Path(pg_dump_path)
    if not dump_path.is_file() or dump_path.stat().st_size == 0:
        raise SeedError(
            f"delete_pg_extras refuses to apply: pg_dump_path {dump_path} "
            "does not exist or is empty"
        )

    quoted_ids = ", ".join(f"'{doc_id}'" for doc_id in sorted(allow_ids))
    sql = (
        f"BEGIN; DELETE FROM lancet_eval.documents WHERE id NOT IN ({quoted_ids}); "
        "COMMIT;"
    )
    run_psql(settings, sql)

    after = list_pg_documents(settings)
    deleted_ids = sorted(set(current.keys()) - set(after.keys()))
    return deleted_ids


__all__ = [
    "IdentityGateError",
    "IdentityReport",
    "compute_identity",
    "delete_pg_extras",
    "list_lancedb_document_ids",
    "list_pg_documents",
    "require_index_identity",
]
