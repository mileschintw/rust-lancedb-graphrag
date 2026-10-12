"""06.4 D-218 / D-228: the paired-delta forest plot generated from the committed run JSON.

The generator, ``eval/scripts/render_forest_plot.py``, is the only code that reads the
run directories' JSON for the docs. These tests hold it to D-214 (never re-derive): every
plotted number is re-read from the file and JSON path the row records, the two
out-of-family Hits@4 cells carry a footnote and no number (D-228), every drawn cell's
printed value, x position and significance marking agree with its JSON row, two renders
are byte-identical, and the committed ``docs/assets`` files equal a fresh render.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "eval" / "scripts" / "render_forest_plot.py"
COMMITTED_SVG = REPO_ROOT / "docs" / "assets" / "eval-forest.svg"
COMMITTED_JSON = REPO_ROOT / "docs" / "assets" / "eval-forest.json"
LEVERS = "eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout/lever-comparison.json"
BASELINE = "eval/runs/2026-10-07-heldout-multihop_rag_heldout/comparison.json"
D228_FOOTNOTE = "not in the pre-registered Hits@4 family; retrieval unchanged by construction"
CI_LABEL = "unadjusted, estimation only"
SVG_NS = "{http://www.w3.org/2000/svg}"

_PATH_STEP = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\[(\d+)\])?")


def _render(out_dir: Path) -> tuple[Path, Path]:
    svg = out_dir / "eval-forest.svg"
    data = out_dir / "eval-forest.json"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--out-svg", str(svg), "--out-json", str(data)],
        check=True,
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return svg, data


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    svg, data = _render(tmp_path_factory.mktemp("forest"))
    return {
        "svg_path": svg,
        "json_path": data,
        "svg": svg.read_text(encoding="utf-8"),
        "rows": json.loads(data.read_text(encoding="utf-8"))["rows"],
    }


def _resolve(document: Any, path: str) -> Any:
    """Resolve a recorded path such as ``families[1].comparisons[0]`` or
    ``descriptive_rows[2].paper_hits_at_4`` against a parsed JSON document."""
    node = document
    for step in path.split("."):
        match = _PATH_STEP.fullmatch(step)
        assert match is not None, f"bad path step {step!r} in {path!r}"
        node = node[match.group(1)]
        if match.group(2) is not None:
            node = node[int(match.group(2))]
    return node


def _source(row: dict[str, Any]) -> Any:
    source_file = row["source_file"]
    assert not Path(source_file).is_absolute() and "\\" not in source_file
    return json.loads((REPO_ROOT / source_file).read_text(encoding="utf-8"))


def _svg_root(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def _by_class(root: ET.Element, tag: str, cls: str) -> list[ET.Element]:
    return [
        e
        for e in root.iter(f"{SVG_NS}{tag}")
        if cls in (e.get("class") or "").split()
    ]


def _cells(root: ET.Element) -> dict[tuple[str, str, str], ET.Element]:
    return {
        (g.get("data-group"), g.get("data-panel"), g.get("data-arm")): g
        for g in _by_class(root, "g", "cell")
    }


def test_d218_two_renders_are_byte_identical(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = _render(tmp_path / "a")
    second = _render(tmp_path / "b")
    assert first[0].read_bytes() == second[0].read_bytes()
    assert first[1].read_bytes() == second[1].read_bytes()
    assert b"\r\n" not in first[0].read_bytes()
    assert b"\r\n" not in first[1].read_bytes()


def test_d218_every_plotted_value_matches_its_source_path(rendered: dict[str, Any]) -> None:
    rows = rendered["rows"]
    assert len(rows) == 18
    assert {r["source_file"] for r in rows} == {LEVERS, BASELINE}
    plotted = [r for r in rows if r["delta"] is not None]
    assert len(plotted) == 16
    for row in plotted:
        target = _resolve(_source(row), row["source_path"])
        for field in ("delta", "ci_lo", "ci_hi"):
            assert row[field] == target[field], (row["arm"], row["panel"], field)
        assert target["ci_label"] == CI_LABEL
        if row["mark"] == "descriptive":
            parent = _resolve(_source(row), row["source_path"].rsplit(".", 1)[0])
            assert parent["row"] == f"{row['arm']} - {row['reference']}"
            assert row["n_pairs"] == parent["n_pairs"]
            assert row["adjusted_p"] is None and row["raw_p"] is None
            assert row["decision"] is None
        else:
            for field in ("arm", "reference", "adjusted_p", "raw_p", "decision", "n_pairs"):
                assert row[field] == target[field], (row["arm"], row["panel"], field)
            assert re.fullmatch(r"families\[\d\]\.comparisons\[\d\]", row["source_path"])
            family = _resolve(_source(row), row["source_path"].split(".")[0])
            assert family["primary"] == row["panel"]


def test_d228_two_hits_cells_are_footnoted_with_no_number(rendered: dict[str, Any]) -> None:
    rows = rendered["rows"]
    footnoted = [r for r in rows if r["mark"] == "not-in-family"]
    assert sorted((r["arm"], r["panel"]) for r in footnoted) == [
        ("hybrid+answer-format", "paper_hits_at_4"),
        ("hybrid+metadata", "paper_hits_at_4"),
    ]
    for row in footnoted:
        assert row["delta"] is None and row["ci_lo"] is None and row["ci_hi"] is None
        assert row["adjusted_p"] is None and row["raw_p"] is None
        assert row["footnote"] == D228_FOOTNOTE
        # The family the cell is absent from really does not hold the arm.
        family = _resolve(_source(row), row["source_path"])
        assert row["arm"] not in {c["arm"] for c in family}
    for row in rows:
        if row["mark"] != "not-in-family":
            assert row["footnote"] is None

    root = _svg_root(rendered["svg"])
    cells = _cells(root)
    for row in footnoted:
        cell = cells[(row["group"], row["panel"], row["arm"])]
        assert cell.get("data-mark") == "not-in-family"
        assert not _by_class(cell, "line", "ci")
        assert not [e for e in cell.iter() if "point" in (e.get("class") or "").split()]
    assert D228_FOOTNOTE in rendered["svg"]


def test_d218_marks_descriptive_and_holm_rows(rendered: dict[str, Any]) -> None:
    rows = rendered["rows"]
    levers = [r for r in rows if r["source_file"] == LEVERS]
    baselines = [r for r in rows if r["source_file"] == BASELINE]
    assert len(levers) == 12 and len(baselines) == 6
    descriptive = sorted((r["arm"], r["panel"]) for r in rows if r["mark"] == "descriptive")
    assert descriptive == [
        ("hybrid+all", "answer_usable"),
        ("hybrid+all", "paper_hits_at_4"),
        ("hybrid+graph", "answer_usable"),
        ("hybrid+graph", "paper_hits_at_4"),
    ]
    assert all(r["source_file"] == LEVERS for r in rows if r["mark"] == "descriptive")
    # Every group header and the caption say "vs same-day hybrid".
    assert all(r["reference"] == "hybrid" for r in rows), sorted(
        {r["reference"] for r in rows}
    )
    for row in rows:
        if row["mark"] in ("descriptive", "not-in-family"):
            continue
        # The stored vocabulary, spelled out rather than mirrored from the generator.
        assert row["decision"] in {"significant", "not significant"}, (
            row["arm"],
            row["panel"],
            row["decision"],
        )
        assert row["mark"] in {"holm-significant", "not-significant"}
        assert (row["mark"] == "holm-significant") == (row["decision"] == "significant")
    significant = sorted(
        (r["group"].split()[0], r["arm"], r["panel"]) for r in rows if r["mark"] == "holm-significant"
    )
    assert significant == [
        ("06.3.5", "bm25-only", "answer_usable"),
        ("06.3.5", "bm25-only", "paper_hits_at_4"),
        ("06.3.6", "hybrid+metadata", "answer_usable"),
        ("06.3.6", "hybrid+rerank", "answer_usable"),
        ("06.3.6", "hybrid+rerank", "paper_hits_at_4"),
    ]
    not_significant = sorted(
        (r["group"].split()[0], r["arm"], r["panel"])
        for r in rows
        if r["mark"] == "not-significant"
    )
    assert not_significant == [
        ("06.3.5", "dense-only", "answer_usable"),
        ("06.3.5", "dense-only", "paper_hits_at_4"),
        ("06.3.5", "hybrid+graph", "answer_usable"),
        ("06.3.5", "hybrid+graph", "paper_hits_at_4"),
        ("06.3.6", "hybrid+answer-format", "answer_usable"),
        ("06.3.6", "hybrid+graph-v2", "answer_usable"),
        ("06.3.6", "hybrid+graph-v2", "paper_hits_at_4"),
    ]

    root = _svg_root(rendered["svg"])
    assert root.tag == f"{SVG_NS}svg"
    assert root.get("version") == "1.1"
    cells = _cells(root)
    assert len(cells) == 18
    for row in rows:
        cell = cells[(row["group"], row["panel"], row["arm"])]
        assert cell.get("data-mark") == row["mark"]
        if row["delta"] is not None:
            assert len(_by_class(cell, "line", "ci")) == 1
    panels = [g.get("data-panel") for g in _by_class(root, "g", "panel")]
    assert panels == ["answer_usable", "paper_hits_at_4"]
    caption = " ".join((t.text or "") for t in _by_class(root, "text", "caption"))
    assert CI_LABEL in caption
    assert LEVERS in caption and BASELINE in caption
    legend = " ".join((t.text or "") for t in _by_class(root, "text", "legend-label"))
    assert "Holm" in legend and "descriptive" in legend


def _four(value: float) -> str:
    """A value at four decimals, with no `-0.0000`."""
    text = f"{abs(value):.4f}"
    return text if text == "0.0000" or value >= 0 else "-" + text


def _signed_four(value: float) -> str:
    text = _four(value)
    return text if text == "0.0000" or text.startswith("-") else "+" + text


_VALUE_SUFFIX = {"holm-significant": " Holm", "descriptive": " descriptive", "not-significant": ""}
_X_TOLERANCE = 0.02  # two-decimal coordinates, plus the rounding of the tick positions


def _panel_scale(panel: ET.Element) -> tuple[float, float, float, float, float]:
    """`(intercept, slope, zero_x, x_min, x_max)` of one panel, read from the drawn axis only.

    The value-to-x line is fitted through the outermost labelled ticks, so a panel offset, a
    sign flip or a wrong scale in the generator's `x_of` shows up as a point off that line.
    """
    ticks = sorted(
        (float(t.text or ""), float(t.get("x") or ""))
        for t in _by_class(panel, "text", "tick-label")
    )
    assert len(ticks) >= 2, "a panel draws fewer than two labelled ticks"
    (v0, x0), (v1, x1) = ticks[0], ticks[-1]
    slope = (x1 - x0) / (v1 - v0)
    zero = _by_class(panel, "line", "zero-line")
    axis = _by_class(panel, "line", "axis-line")
    assert len(zero) == 1 and len(axis) == 1
    return (
        x0 - slope * v0,
        slope,
        float(zero[0].get("x1") or ""),
        float(axis[0].get("x1") or ""),
        float(axis[0].get("x2") or ""),
    )


_OPEN_FILL = "#ffffff"  # the literal open-marker fill the generator emits


def _colour(value: str | None) -> str:
    """A colour attribute normalised for comparison: trimmed and lower-cased."""
    return (value or "").strip().lower()


def _expected_point_colours(mark: str) -> tuple[str, str]:
    """`(fill, stroke)` the generator emits for a plotted mark, read from its own `COLORS`.

    Holm-significant points are filled with the Holm colour; every other plotted point is
    open (the literal white fill) and stroked in its row's colour.
    """
    colors = _generator().COLORS
    stroke = _colour(colors["descriptive"] if mark == "descriptive" else colors["holm"])
    fill = _colour(colors["holm"]) if mark == "holm-significant" else _OPEN_FILL
    return fill, stroke


def test_d218_each_drawn_cell_matches_its_json_row(rendered: dict[str, Any]) -> None:
    """The SVG is held to the JSON rows, not only to its own structure: the printed value
    text, the x position of the whisker and point, and the significance fill and shape."""
    _check_drawn_cells(_svg_root(rendered["svg"]), rendered["rows"])


def _check_drawn_cells(root: ET.Element, rows: list[dict[str, Any]]) -> None:
    scales = {p.get("data-panel"): _panel_scale(p) for p in _by_class(root, "g", "panel")}
    cells = _cells(root)
    checked = 0
    for row in rows:
        if row["delta"] is None:
            continue
        where = (row["group"], row["panel"], row["arm"])
        cell = cells[where]
        intercept, slope, zero_x, x_min, x_max = scales[row["panel"]]
        assert abs(intercept + slope * 0.0 - zero_x) <= _X_TOLERANCE, row["panel"]

        values = _by_class(cell, "text", "value")
        assert len(values) == 1, where
        expected = (
            f"{_signed_four(row['delta'])} [{_four(row['ci_lo'])}, {_four(row['ci_hi'])}]"
            f"{_VALUE_SUFFIX[row['mark']]}"
        )
        if row["adjusted_p"] == 0.0:
            expected += " (Holm p below stored precision)"
        assert values[0].text == expected, where

        ci = _by_class(cell, "line", "ci")
        assert len(ci) == 1, where
        x1, x2 = float(ci[0].get("x1") or ""), float(ci[0].get("x2") or "")
        assert abs(x1 - (intercept + slope * row["ci_lo"])) <= _X_TOLERANCE, where
        assert abs(x2 - (intercept + slope * row["ci_hi"])) <= _X_TOLERANCE, where
        assert x_min <= x1 <= x2 <= x_max, where

        points = [e for e in cell.iter() if "point" in (e.get("class") or "").split()]
        assert len(points) == 1, where
        point = points[0]
        if row["mark"] == "descriptive":
            assert point.tag == f"{SVG_NS}polygon", where
            cx = float((point.get("points") or "").split()[0].split(",")[0])
        else:
            assert point.tag == f"{SVG_NS}circle", where
            cx = float(point.get("cx") or "")
        assert abs(cx - (intercept + slope * row["delta"])) <= _X_TOLERANCE, where
        assert x1 <= cx <= x2, where
        assert (cx > zero_x) == (row["delta"] > 0) or abs(cx - zero_x) <= _X_TOLERANCE, where
        # The exact fill and stroke for the mark, so an open marker on a significant row
        # (`none`, `white`, `#FFFFFF`, `transparent`, ...) fails, not only the reverse.
        fill, stroke = _colour(point.get("fill")), _colour(point.get("stroke"))
        assert (fill, stroke) == _expected_point_colours(row["mark"]), (
            f"fill/stroke for {row['mark']}",
            where,
            fill,
            stroke,
        )
        checked += 1
    assert checked == 16


def _first_cell(rows: list[dict[str, Any]], mark: str) -> tuple[str, str, str]:
    row = next(r for r in rows if r["mark"] == mark)
    return (row["group"], row["panel"], row["arm"])


def _point(cell: ET.Element) -> ET.Element:
    return next(e for e in cell.iter() if "point" in (e.get("class") or "").split())


@pytest.mark.parametrize("fill", ["none", "white", "#FFFFFF", "#ffffff", "transparent", ""])
def test_d218_a_significant_point_drawn_open_fails_the_cell_check(
    rendered: dict[str, Any], fill: str
) -> None:
    root = _svg_root(rendered["svg"])
    _point(_cells(root)[_first_cell(rendered["rows"], "holm-significant")]).set("fill", fill)
    with pytest.raises(AssertionError, match="fill/stroke for holm-significant"):
        _check_drawn_cells(root, rendered["rows"])


@pytest.mark.parametrize("fill", ["#1f4e79", "none", "white", "transparent"])
def test_d218_an_open_point_drawn_any_other_way_fails_the_cell_check(
    rendered: dict[str, Any], fill: str
) -> None:
    root = _svg_root(rendered["svg"])
    _point(_cells(root)[_first_cell(rendered["rows"], "not-significant")]).set("fill", fill)
    with pytest.raises(AssertionError, match="fill/stroke for not-significant"):
        _check_drawn_cells(root, rendered["rows"])


def test_d218_the_fill_comparison_ignores_case_and_whitespace(rendered: dict[str, Any]) -> None:
    root = _svg_root(rendered["svg"])
    cells = _cells(root)
    _point(cells[_first_cell(rendered["rows"], "holm-significant")]).set("fill", " #1F4E79 ")
    _point(cells[_first_cell(rendered["rows"], "not-significant")]).set("fill", "#FFFFFF")
    _check_drawn_cells(root, rendered["rows"])


def _generator() -> Any:
    """The generator loaded by path, in process, so its row builder runs on edited copies."""
    spec = importlib.util.spec_from_file_location("render_forest_plot_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("source", "field", "value"),
    [
        ("levers", "reference", "dense-only"),
        ("baseline", "reference", "hybrid+graph"),
        ("levers", "decision", "Significant"),
        ("levers", "decision", "significant (Holm)"),
        ("baseline", "decision", None),
        ("baseline", "decision", "not evaluable"),
    ],
)
def test_d218_generator_refuses_a_non_hybrid_reference_or_unknown_decision(
    source: str, field: str, value: Any
) -> None:
    """A family row plotted under "vs hybrid" must compare against hybrid, and its decision
    must be one the legend draws; anything else is a SourceLayoutError, not an open circle."""
    generator = _generator()
    documents = {
        "levers": json.loads((REPO_ROOT / LEVERS).read_text(encoding="utf-8")),
        "baseline": json.loads((REPO_ROOT / BASELINE).read_text(encoding="utf-8")),
    }
    assert len(generator.build_rows(documents["levers"], documents["baseline"])) == 18
    edited = copy.deepcopy(documents)
    edited[source]["families"][1]["comparisons"][0][field] = value
    with pytest.raises(generator.SourceLayoutError, match=field):
        generator.build_rows(edited["levers"], edited["baseline"])


def test_d218_committed_assets_equal_a_fresh_render(rendered: dict[str, Any]) -> None:
    # A Windows checkout with core.autocrlf rewrites line endings; compare the text.
    for committed, fresh in (
        (COMMITTED_SVG, rendered["svg_path"]),
        (COMMITTED_JSON, rendered["json_path"]),
    ):
        assert committed.exists(), f"{committed} is not committed"
        committed_text = committed.read_bytes().replace(b"\r\n", b"\n")
        assert committed_text == fresh.read_bytes(), f"{committed.name} is out of date"


def test_d218_the_generator_reads_only_the_two_run_files() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert LEVERS in text and BASELINE in text
    imports = set(re.findall(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M))
    assert imports <= {"__future__", "argparse", "json", "math", "sys", "pathlib", "typing", "jinja2"}
