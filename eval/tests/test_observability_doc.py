"""The observability walkthrough's span tables come from the committed Jaeger exports.

06-CONTEXT D-72 / 06.4 D-217: ``docs/observability.md`` follows one question through
two traces. 06.4 D-214: the page publishes no number it did not quote. Every row of the
two span tables is checked against the trace JSON it came from, so a value cannot be
invented, re-derived or drift from the evidence:

- the span name must be an ``operationName`` in the trace;
- the duration must be that operation's first span (earliest ``startTime``) in
  microseconds, divided by 1000 and rounded half up to one decimal; on an exact
  ``.x5`` tie Python's ``round()`` is accepted too;
- the parent cell must name the span's actual parent, or name no span when the parent
  was never exported (the client span behind the inbound ``traceparent``);
- every ``key`` = ``value`` pair in the attributes cell must equal that span's tag.
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from lancet_eval.config import repo_root

DOC = Path("docs/observability.md")
DEFAULT_TRACE = Path("docs/assets/jaeger-default-query.trace.json")
OPTIN_TRACE = Path("docs/assets/jaeger-graph-optin.trace.json")
HEADER = ["span", "parent", "duration (ms)", "key attributes"]

ATTRIBUTE = re.compile(r"`([^`]+)` = `([^`]*)`")


def _doc_text() -> str:
    return (repo_root() / DOC).read_text(encoding="utf-8")


def _trace(path: Path) -> dict[str, Any]:
    data = json.loads((repo_root() / path).read_text(encoding="utf-8"))
    traces = data["data"]
    assert len(traces) == 1, f"{path} must hold one trace, found {len(traces)}"
    return traces[0]


def _table_rows(text: str, table: str) -> list[list[str]]:
    """Return the body rows between the table's start/end markers as cell lists."""
    start = f"<!-- span-table:{table}:start -->"
    end = f"<!-- span-table:{table}:end -->"
    assert text.count(start) == 1, f"expected exactly one {start!r} marker"
    assert text.count(end) == 1, f"expected exactly one {end!r} marker"
    block = text.split(start, 1)[1].split(end, 1)[0]
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    assert len(lines) >= 3, f"span table {table!r} has no body rows"
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    assert header == HEADER, header
    assert set(lines[1].replace("|", "").strip()) <= {"-", ":", " "}, lines[1]
    rows = []
    for line in lines[2:]:
        assert line.startswith("|") and line.endswith("|"), f"not a row: {line!r}"
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        assert len(cells) == 4, f"expected 4 cells, got {len(cells)}: {line!r}"
        rows.append(cells)
    return rows


def _unquote(cell: str) -> str:
    return cell.strip().strip("`")


def _tag_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _accepted_durations(micros: int) -> set[str]:
    """The writer's rule (Decimal, half up), plus ``round()`` on an exact tie only."""
    exact = Decimal(micros) / 1000
    accepted = {str(exact.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))}
    if micros % 100 == 50:
        accepted.add(f"{round(micros / 1000, 1):.1f}")
    return accepted


def _parent_of(span: dict[str, Any], by_id: dict[str, Any]) -> dict[str, Any] | None:
    for ref in span.get("references", []):
        if ref["refType"] == "CHILD_OF":
            return by_id.get(ref["spanID"])
    return None


def _row_errors(rows: list[list[str]], trace: dict[str, Any]) -> list[str]:
    """Every way a row disagrees with the trace JSON; empty when all rows match."""
    spans = trace["spans"]
    by_id = {span["spanID"]: span for span in spans}
    first: dict[str, dict[str, Any]] = {}
    for span in sorted(spans, key=lambda s: s["startTime"]):
        first.setdefault(span["operationName"], span)
    names = set(first)

    errors: list[str] = []
    for name_cell, parent_cell, duration_cell, attributes_cell in rows:
        name = _unquote(name_cell)
        span = first.get(name)
        if span is None:
            errors.append(f"{name!r}: no span with this operationName in the JSON")
            continue

        accepted = _accepted_durations(int(span["duration"]))
        if duration_cell not in accepted:
            errors.append(
                f"{name!r}: duration {duration_cell!r} is not {sorted(accepted)} "
                f"(first span {span['duration']} us)"
            )

        parent = _parent_of(span, by_id)
        if parent is not None:
            actual = parent["operationName"]
            if parent_cell != f"`{actual}`":
                errors.append(
                    f"{name!r}: parent {parent_cell!r}, trace says {actual!r}"
                )
        elif parent_cell.startswith("`") or _unquote(parent_cell) in names:
            errors.append(
                f"{name!r}: parent {parent_cell!r} names a span, "
                "but the parent is not in the trace"
            )

        tags = {tag["key"]: tag["value"] for tag in span.get("tags", [])}
        for key, value in ATTRIBUTE.findall(attributes_cell):
            if key not in tags:
                errors.append(f"{name!r}: attribute {key!r} is not on the span")
            elif _tag_text(tags[key]) != value:
                errors.append(
                    f"{name!r}: {key} = {value!r}, trace says {_tag_text(tags[key])!r}"
                )
    return errors


def _names(rows: list[list[str]]) -> list[str]:
    return [_unquote(row[0]) for row in rows]


def _real_duration(rows: list[list[str]], name: str) -> str:
    return next(row[2] for row in rows if _unquote(row[0]) == name)


def test_d217_default_span_table_matches_the_trace_json() -> None:
    """Every default-table row is a span in the default trace JSON, with its values."""
    rows = _table_rows(_doc_text(), "default")
    assert _row_errors(rows, _trace(DEFAULT_TRACE)) == []
    names = _names(rows)
    assert len(names) == len(set(names)), "a span appears twice in the default table"
    assert "graph_traversal" not in names, (
        "the default request runs no graph traversal (D-207)"
    )


def test_d217_optin_span_table_matches_the_trace_json() -> None:
    """Every opt-in-table row is a span in the opt-in trace JSON, with its values."""
    rows = _table_rows(_doc_text(), "optin")
    assert _row_errors(rows, _trace(OPTIN_TRACE)) == []
    names = _names(rows)
    assert len(names) == len(set(names)), "a span appears twice in the opt-in table"
    assert "graph_traversal" in names, (
        "the opt-in table must show the Cypher traversal leaf (D-217)"
    )


def test_d227_default_table_shows_the_rerank_leaf() -> None:
    """The default table shows the D-227 rerank_request leaf under hybrid_retrieval."""
    rows = _table_rows(_doc_text(), "default")
    rerank = [row for row in rows if _unquote(row[0]) == "rerank_request"]
    assert len(rerank) == 1, (
        "the default table must carry exactly one rerank_request row"
    )
    assert rerank[0][1] == "`hybrid_retrieval`"
    assert "`lancet.rerank.outcome` = " in rerank[0][3]


def test_a_row_naming_a_span_absent_from_the_trace_json_fails() -> None:
    """The checker has teeth: an invented span, duration, parent or value fails."""
    trace = _trace(DEFAULT_TRACE)
    real = _table_rows(_doc_text(), "default")
    assert _row_errors(real, trace) == []

    invented_span = [["`rerank_cache_lookup`", "`hybrid_retrieval`", "1.0", ""]]
    assert any(
        "no span with this operationName" in e
        for e in _row_errors(invented_span, trace)
    )

    rerank_ms = _real_duration(real, "rerank_request")
    wrong = {
        "duration": ["`rerank_request`", "`hybrid_retrieval`", "999.9", ""],
        "parent": ["`rerank_request`", "`query_rag`", rerank_ms, ""],
        "attribute": [
            "`rerank_request`",
            "`hybrid_retrieval`",
            rerank_ms,
            "`lancet.rerank.outcome` = `timeout`",
        ],
    }
    for kind, row in wrong.items():
        assert _row_errors([row], trace), f"an invented {kind} was not reported"


def test_tie_rule_accepts_half_up_and_python_round_only_on_an_exact_tie() -> None:
    assert _accepted_durations(256007) == {"256.0"}
    assert _accepted_durations(4349) == {"4.3"}
    assert _accepted_durations(4351) == {"4.4"}
    # Exact ties: half up gives 4.3 and 4.4; float round() gives 4.2 (banker's
    # rounding) and 4.3 (4.35 is not exact in binary). Both writers pass.
    assert _accepted_durations(4250) == {"4.3", "4.2"}
    assert _accepted_durations(4350) == {"4.4", "4.3"}
