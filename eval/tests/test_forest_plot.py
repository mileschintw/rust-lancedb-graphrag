"""06.4 D-218 / D-228: the paired-delta forest plot generated from the committed run JSON.

The generator, ``eval/scripts/render_forest_plot.py``, is the only code that reads the
run directories' JSON for the docs. These tests hold it to D-214 (never re-derive): every
plotted number is re-read from the file and JSON path the row records, the two
out-of-family Hits@4 cells carry a footnote and no number (D-228), two renders are
byte-identical, and the committed ``docs/assets`` files equal a fresh render.
"""

from __future__ import annotations

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
    for row in rows:
        if row["mark"] in ("descriptive", "not-in-family"):
            continue
        expected = "holm-significant" if row["decision"] == "significant" else "not-significant"
        assert row["mark"] == expected, (row["arm"], row["panel"])
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
