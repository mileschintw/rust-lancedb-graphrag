"""Render the D-218 paired-delta forest plot for docs/evaluation.md (Phase 6.4).

Usage (from the repo root)::

    uv run --project eval python eval/scripts/render_forest_plot.py \
        --out-svg docs/assets/eval-forest.svg --out-json docs/assets/eval-forest.json

This is the only code that reads raw run JSON for the docs. It reads two committed files,
read-only, and nothing else:

- the 06.3.6 lever comparison (``LEVERS``): ``families[0]`` is the decisional
  ``answer_usable`` family, ``families[1]`` the supporting ``paper_hits_at_4`` family,
  and ``descriptive_rows[0]`` / ``[2]`` are ``hybrid+graph - hybrid`` and
  ``hybrid+all - hybrid``;
- the 06.3.5 four-arm comparison (``BASELINE``): ``families[0]`` is ``paper_hits_at_4``
  and ``families[1]`` is ``answer_usable``.

Every plotted delta and CI is copied from its file and recorded with that file and its JSON
path, so ``eval-forest.json`` lets a test re-read each value (D-214: never re-derive). The
two Hits@4 cells for ``hybrid+metadata`` and ``hybrid+answer-format`` have no paired value in
the lever comparison (they are outside the pre-registered Hits@4 family), so they carry the
D-228 footnote and no number. P-values are carried exactly as stored. The SVG prints each
plotted value at four decimals, the rendering the generated ``lever-comparison.md`` and
``comparison.md`` tables use.

The SVG is rendered from a Jinja2 template with precomputed geometry at fixed two-decimal
coordinates, and the JSON is written with sorted keys and LF line endings, so two renders
of the same inputs are byte-identical. No plotting library is used (06.3 AI-SPEC: no
native-toolchain dependency in the eval environment).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
GENERATOR = "eval/scripts/render_forest_plot.py"

LEVERS = "eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout/lever-comparison.json"
BASELINE = "eval/runs/2026-10-07-heldout-multihop_rag_heldout/comparison.json"

LEVER_GROUP = "06.3.6 levers (held-out, vs same-day hybrid)"
BASELINE_GROUP = "06.3.5 baselines (held-out, vs same-day hybrid)"
PANELS = ("answer_usable", "paper_hits_at_4")
PANEL_TITLES = {
    "answer_usable": "answer_usable (paired delta)",
    "paper_hits_at_4": "paper-convention Hits@4 (paired delta)",
}
CI_LABEL = "unadjusted, estimation only"
D228_FOOTNOTE = "not in the pre-registered Hits@4 family; retrieval unchanged by construction"

# Fixed layout, in SVG user units.
WIDTH = 1320
ROW_H = 26
TOP = 100
LABEL_X = 20
PANEL_X0 = (270, 790)
PANEL_W = 300
VALUE_GAP = 12
COLORS = {"holm": "#1f4e79", "descriptive": "#777777", "axis": "#333333", "grid": "#dddddd"}


class SourceLayoutError(Exception):
    """A source file does not hold the arms at the paths this generator reads."""


def _load(relative: str) -> dict[str, Any]:
    with (REPO_ROOT / relative).open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise SourceLayoutError(f"{relative} does not hold a JSON object")
    return document


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise SourceLayoutError(message)


def _family(document: dict[str, Any], index: int, primary: str, source: str) -> list[dict[str, Any]]:
    family = document["families"][index]
    _expect(
        family.get("primary") == primary,
        f"{source} families[{index}] is {family.get('primary')!r}, expected {primary!r}",
    )
    return family["comparisons"]


def _mark(decision: str) -> str:
    return "holm-significant" if decision == "significant" else "not-significant"


def _family_row(
    group: str, panel: str, comparison: dict[str, Any], source: str, path: str
) -> dict[str, Any]:
    _expect(
        comparison.get("ci_label") == CI_LABEL,
        f"{source} {path} ci_label is {comparison.get('ci_label')!r}",
    )
    return {
        "group": group,
        "panel": panel,
        "arm": comparison["arm"],
        "reference": comparison["reference"],
        "delta": comparison["delta"],
        "ci_lo": comparison["ci_lo"],
        "ci_hi": comparison["ci_hi"],
        "ci_label": comparison["ci_label"],
        "raw_p": comparison["raw_p"],
        "adjusted_p": comparison["adjusted_p"],
        "decision": comparison["decision"],
        "n_pairs": comparison["n_pairs"],
        "mark": _mark(comparison["decision"]),
        "footnote": None,
        "source_file": source,
        "source_path": path,
    }


def _descriptive_row(
    panel: str, descriptive: dict[str, Any], index: int, arm: str
) -> dict[str, Any]:
    label = descriptive["row"]
    _expect(
        label == f"{arm} - hybrid",
        f"{LEVERS} descriptive_rows[{index}] is {label!r}, expected '{arm} - hybrid'",
    )
    cell = descriptive[panel]
    _expect(cell.get("ci_label") == CI_LABEL, f"{LEVERS} descriptive_rows[{index}] ci_label")
    return {
        "group": LEVER_GROUP,
        "panel": panel,
        "arm": arm,
        "reference": "hybrid",
        "delta": cell["delta"],
        "ci_lo": cell["ci_lo"],
        "ci_hi": cell["ci_hi"],
        "ci_label": cell["ci_label"],
        "raw_p": None,
        "adjusted_p": None,
        "decision": None,
        "n_pairs": descriptive["n_pairs"],
        "mark": "descriptive",
        "footnote": None,
        "source_file": LEVERS,
        "source_path": f"descriptive_rows[{index}].{panel}",
    }


def _footnoted_row(arm: str) -> dict[str, Any]:
    return {
        "group": LEVER_GROUP,
        "panel": "paper_hits_at_4",
        "arm": arm,
        "reference": "hybrid",
        "delta": None,
        "ci_lo": None,
        "ci_hi": None,
        "ci_label": None,
        "raw_p": None,
        "adjusted_p": None,
        "decision": None,
        "n_pairs": None,
        "mark": "not-in-family",
        "footnote": D228_FOOTNOTE,
        "source_file": LEVERS,
        "source_path": "families[1].comparisons",
    }


def build_rows(levers: dict[str, Any], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """Every plotted cell, in a fixed order: group, then arm, then panel."""
    usable = _family(levers, 0, "answer_usable", LEVERS)
    hits = _family(levers, 1, "paper_hits_at_4", LEVERS)
    usable_arms = [c["arm"] for c in usable]
    hits_arms = [c["arm"] for c in hits]
    _expect(
        usable_arms == ["hybrid+rerank", "hybrid+graph-v2", "hybrid+metadata", "hybrid+answer-format"],
        f"{LEVERS} families[0] arms are {usable_arms}",
    )
    _expect(hits_arms == ["hybrid+rerank", "hybrid+graph-v2"], f"{LEVERS} families[1] arms are {hits_arms}")

    rows: list[dict[str, Any]] = []
    for i, arm in enumerate(usable_arms):
        rows.append(
            _family_row(LEVER_GROUP, "answer_usable", usable[i], LEVERS, f"families[0].comparisons[{i}]")
        )
        if arm in hits_arms:
            j = hits_arms.index(arm)
            rows.append(
                _family_row(LEVER_GROUP, "paper_hits_at_4", hits[j], LEVERS, f"families[1].comparisons[{j}]")
            )
        else:
            rows.append(_footnoted_row(arm))
    for index, arm in ((0, "hybrid+graph"), (2, "hybrid+all")):
        descriptive = levers["descriptive_rows"][index]
        for panel in PANELS:
            rows.append(_descriptive_row(panel, descriptive, index, arm))

    base_hits = _family(baseline, 0, "paper_hits_at_4", BASELINE)
    base_usable = _family(baseline, 1, "answer_usable", BASELINE)
    base_arms = [c["arm"] for c in base_usable]
    _expect(base_arms == ["dense-only", "bm25-only", "hybrid+graph"], f"{BASELINE} families[1] arms are {base_arms}")
    _expect([c["arm"] for c in base_hits] == base_arms, f"{BASELINE} families[0] arms differ from families[1]")
    for i in range(len(base_arms)):
        rows.append(
            _family_row(BASELINE_GROUP, "answer_usable", base_usable[i], BASELINE, f"families[1].comparisons[{i}]")
        )
        rows.append(
            _family_row(BASELINE_GROUP, "paper_hits_at_4", base_hits[i], BASELINE, f"families[0].comparisons[{i}]")
        )
    return rows


def _f2(value: float) -> str:
    """A coordinate at a fixed two decimals, never `-0.00`."""
    text = f"{value:.2f}"
    return "0.00" if text == "-0.00" else text


def _f4(value: float) -> str:
    text = f"{value:.4f}"
    return "0.0000" if text == "-0.0000" else text


def _value_text(row: dict[str, Any]) -> str:
    delta = _f4(row["delta"])
    if not delta.startswith("-") and delta != "0.0000":
        delta = "+" + delta
    text = f"{delta} [{_f4(row['ci_lo'])}, {_f4(row['ci_hi'])}]"
    if row["mark"] == "holm-significant":
        text += " Holm"
    elif row["mark"] == "descriptive":
        text += " descriptive"
    if row["adjusted_p"] == 0.0:  # defensive: no current source row stores 0.0
        text += " (Holm p below stored precision)"
    return text


def _domain(rows: list[dict[str, Any]]) -> float:
    """Half-width of a symmetric x scale, the largest |CI bound| rounded up to 0.05."""
    largest = max(max(abs(r["ci_lo"]), abs(r["ci_hi"])) for r in rows if r["delta"] is not None)
    return math.ceil(largest * 20 - 1e-9) / 20


def _geometry(rows: list[dict[str, Any]]) -> dict[str, Any]:
    half = _domain(rows)

    def x_of(panel_index: int, value: float) -> float:
        return PANEL_X0[panel_index] + (value + half) / (2 * half) * PANEL_W

    slots: list[dict[str, Any]] = []
    arms_by_group: dict[str, list[str]] = {}
    for row in rows:
        arms = arms_by_group.setdefault(row["group"], [])
        if row["arm"] not in arms:
            arms.append(row["arm"])
    for group, arms in arms_by_group.items():
        slots.append({"kind": "header", "group": group})
        for arm in arms:
            slots.append({"kind": "arm", "group": group, "arm": arm})
    bottom = TOP + len(slots) * ROW_H

    headers: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    slot_y: dict[tuple[str, str], float] = {}
    for i, slot in enumerate(slots):
        y = TOP + i * ROW_H + ROW_H / 2
        if slot["kind"] == "header":
            headers.append({"text": slot["group"], "x": _f2(LABEL_X), "y": _f2(y + 4)})
            continue
        slot_y[(slot["group"], slot["arm"])] = y
        mark = next(r["mark"] for r in rows if r["group"] == slot["group"] and r["arm"] == slot["arm"])
        text = f"{slot['arm']} (descriptive)" if mark == "descriptive" else slot["arm"]
        labels.append({"text": text, "x": _f2(LABEL_X + 12), "y": _f2(y + 4)})

    ticks: list[int] = list(range(-math.floor(half * 10 + 1e-9), math.floor(half * 10 + 1e-9) + 1))
    panels: list[dict[str, Any]] = []
    for p, panel in enumerate(PANELS):
        cells: list[dict[str, Any]] = []
        for row in rows:
            if row["panel"] != panel:
                continue
            y = slot_y[(row["group"], row["arm"])]
            cell: dict[str, Any] = {
                "group": row["group"],
                "panel": panel,
                "arm": row["arm"],
                "mark": row["mark"],
                "y": _f2(y),
            }
            if row["delta"] is None:
                cell["note"] = {
                    "x": _f2(PANEL_X0[p] + PANEL_W + VALUE_GAP),
                    "y": _f2(y + 4),
                    "text": "no number: see note [1]",
                }
                cell["ci"] = None
            else:
                cx = x_of(p, row["delta"])
                color = COLORS["descriptive"] if row["mark"] == "descriptive" else COLORS["holm"]
                cell["note"] = None
                cell["ci"] = {
                    "x1": _f2(x_of(p, row["ci_lo"])),
                    "x2": _f2(x_of(p, row["ci_hi"])),
                    "cap_top": _f2(y - 4),
                    "cap_bottom": _f2(y + 4),
                    "color": color,
                    "dash": "4 3" if row["mark"] == "descriptive" else "",
                }
                cell["point"] = {
                    "shape": "diamond" if row["mark"] == "descriptive" else "circle",
                    "cx": _f2(cx),
                    "cy": _f2(y),
                    "fill": color if row["mark"] == "holm-significant" else "#ffffff",
                    "stroke": color,
                    "diamond": " ".join(
                        f"{_f2(px)},{_f2(py)}"
                        for px, py in ((cx, y - 5), (cx + 5, y), (cx, y + 5), (cx - 5, y))
                    ),
                }
                cell["value"] = {
                    "x": _f2(PANEL_X0[p] + PANEL_W + VALUE_GAP),
                    "y": _f2(y + 4),
                    "text": _value_text(row),
                }
            cells.append(cell)
        panels.append(
            {
                "panel": panel,
                "title": PANEL_TITLES[panel],
                "x0": _f2(PANEL_X0[p]),
                "x1": _f2(PANEL_X0[p] + PANEL_W),
                "title_y": _f2(TOP - 14),
                "zero_x": _f2(x_of(p, 0.0)),
                "ticks": [
                    {"x": _f2(x_of(p, k / 10)), "label": f"{k / 10:.1f}"} for k in ticks
                ],
                "cells": cells,
            }
        )

    legend_y = bottom + 46
    legend = [
        {"kind": "circle-filled", "x": 270, "text": "Holm-significant (the family's recorded decision)"},
        {"kind": "circle-open", "x": 620, "text": "not significant after Holm"},
        {"kind": "diamond", "x": 840, "text": "descriptive, decides nothing (outside every Holm family)"},
    ]
    legend_items = []
    for item in legend:
        cx = item["x"]
        legend_items.append(
            {
                "kind": item["kind"],
                "cx": _f2(cx),
                "cy": _f2(legend_y),
                "diamond": " ".join(
                    f"{_f2(px)},{_f2(py)}"
                    for px, py in ((cx, legend_y - 5), (cx + 5, legend_y), (cx, legend_y + 5), (cx - 5, legend_y))
                ),
                "text_x": _f2(cx + 12),
                "text_y": _f2(legend_y + 4),
                "text": item["text"],
            }
        )

    notes_y0 = legend_y + 30
    footnotes = [
        f"[1] {D228_FOOTNOTE} (D-228): no paired Hits@4 value exists for this arm, so none is drawn.",
        "The 06.3.6 hybrid+graph and hybrid+all rows are descriptive rows of the lever comparison; they decide nothing.",
    ]
    captions = [
        f"Dot: paired mean difference against the same-day hybrid. Whisker: 95% bootstrap CI, {CI_LABEL}.",
        f"Sources: {LEVERS} (06.3.6 levers)",
        f"and {BASELINE} (06.3.5 baselines).",
        f"Generated by {GENERATOR} from those two files only; values printed at four decimals, as the generated comparison tables print them.",
    ]
    lines: list[dict[str, Any]] = []
    y = notes_y0
    for text in footnotes:
        lines.append({"cls": "footnote", "y": _f2(y), "text": text})
        y += 16
    y += 6
    for text in captions:
        lines.append({"cls": "caption", "y": _f2(y), "text": text})
        y += 16
    height = y + 10

    return {
        "width": WIDTH,
        "height": _f2(height),
        "title": "Paired deltas against the same-day hybrid, held-out MultiHop-RAG",
        "subtitle": "06.3.6 lever arms and 06.3.5 retrieval baselines, each against the hybrid arm of its own drive",
        "desc": (
            "Forest plot of paired deltas with 95% bootstrap confidence intervals on answer_usable and "
            "paper-convention Hits@4. Holm-significant rows are filled, descriptive rows are diamonds, and "
            "the two lever arms outside the Hits@4 family carry a footnote instead of a number."
        ),
        "label_x": _f2(LABEL_X),
        "top": _f2(TOP),
        "bottom": _f2(bottom),
        "tick_label_y": _f2(bottom + 16),
        "headers": headers,
        "labels": labels,
        "panels": panels,
        "legend": legend_items,
        "lines": lines,
        "colors": COLORS,
    }


def render_svg(rows: list[dict[str, Any]]) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR, encoding="utf-8"),
        undefined=StrictUndefined,
        autoescape=True,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("forest.svg.j2").render(g=_geometry(rows))


def render_json(rows: list[dict[str, Any]]) -> str:
    document = {
        "generator": GENERATOR,
        "ci_label": CI_LABEL,
        "sources": [LEVERS, BASELINE],
        "d228_footnote": D228_FOOTNOTE,
        "rows": rows,
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out-svg", type=Path, default=REPO_ROOT / "docs" / "assets" / "eval-forest.svg")
    parser.add_argument("--out-json", type=Path, default=REPO_ROOT / "docs" / "assets" / "eval-forest.json")
    args = parser.parse_args(argv)
    try:
        rows = build_rows(_load(LEVERS), _load(BASELINE))
    except (SourceLayoutError, KeyError, IndexError) as error:
        print(f"render_forest_plot: {error}", file=sys.stderr)
        return 1
    _write(args.out_svg, render_svg(rows))
    _write(args.out_json, render_json(rows))
    print(f"wrote {args.out_svg} and {args.out_json} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
