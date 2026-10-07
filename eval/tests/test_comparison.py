"""Tests for the four-arm comparison (06.3.5-13; D-103, D-111, D-115, D-121 to D-126,
D-40, D-42, D-70, D-102, D-123, D-124, D-125).

The pure maths (Holm families, coverage, robustness, stratum cells) is tested on
hand-chosen per-question maps whose exact p-values are written down here as literals.
The integration tests read a real `score --judged` run (the throwaway-repo scenario of
`test_score_judged_ordered`), so the reader is held to the shape the producer writes.
No test makes a network call.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import test_score_judged_ordered as sj
from typer.testing import CliRunner

from lancet_eval import comparison as cmp_mod
from lancet_eval.cli import app
from lancet_eval.comparison import (
    APPROXIMATION_LABEL,
    D124_DISCLOSURE,
    D124_IDS,
    FWER_STATEMENT,
    LABEL_UNADJUSTED,
    NON_COMPARABILITY_CAVEAT,
    PAPER_REFERENCE_TABLE5,
    SECONDARY_DELTA_BASES,
    SIDECAR_FILES,
    Comparison,
    ComparisonError,
    build_chart_data,
    build_comparison,
    coverage_evaluable,
    format_number,
    format_stratum_cell,
    holm_family,
    render_chart_svg,
    write_comparison,
)
from lancet_eval.judge import JudgeCache
from lancet_eval.score import JudgedResult
from lancet_eval.stats import exact_signflip_p, holm_stepdown

COMPARISON_ARMS = ("dense-only", "bm25-only", "hybrid+graph")
SLUG = {
    "dense-only": "dense_only",
    "bm25-only": "bm25_only",
    "hybrid": "hybrid",
    "hybrid+graph": "hybrid_graph",
}
SECONDARY_HEADING = (
    "Secondary paired deltas against hybrid (unadjusted, estimation only)"
)
STRATA_HEADING = "Per-type strata (D-40; secondary, never decisive)"
UNADJUSTED = "unadjusted, estimation only"
NOT_ROBUST = "not robust to the matching rule"
APPROXIMATION = "approximation; official text rule not verified"
EXCLUDES_ZERO_NOTE = "CI excludes 0; not significant after Holm"
REPO = Path(__file__).resolve().parents[2]

# ---- pure helpers -----------------------------------------------------------------


def _qids(n: int) -> list[str]:
    return [f"q{i:03d}" for i in range(n)]


def values_from_counts(
    n: int, discordant: Mapping[str, tuple[int, int]]
) -> dict[str, dict[str, float]]:
    """Per-arm 0/1 maps over `n` questions with the given (n_pos, n_neg) vs hybrid.

    The hybrid arm scores 1 on the first half of the questions and 0 on the rest.
    An arm with `n_pos` pairs above and `n_neg` below the reference flips exactly
    that many questions and ties on every other.
    """
    qids = _qids(n)
    half = n // 2
    hybrid = {q: 1.0 if i < half else 0.0 for i, q in enumerate(qids)}
    out = {"hybrid": hybrid}
    for arm in COMPARISON_ARMS:
        n_pos, n_neg = discordant[arm]
        assert n_neg <= half and n_pos <= n - half
        vals = dict(hybrid)
        for q in qids[:n_neg]:  # hybrid 1 -> arm 0
            vals[q] = 0.0
        for q in qids[half : half + n_pos]:  # hybrid 0 -> arm 1
            vals[q] = 1.0
        out[arm] = vals
    return out


def _family(counts: Mapping[str, tuple[int, int]], n: int = 40, **kwargs: Any):  # type: ignore[no-untyped-def]
    return holm_family(
        "answer_usable",
        values_from_counts(n, counts),
        evaluable=True,
        **kwargs,
    )


def by_arm(family):  # type: ignore[no-untyped-def]
    return {c.arm: c for c in family.comparisons}


# ---- Holm families: exact p, adjusted p, decisions ---------------------------------


def test_each_comparison_reports_exact_p_holm_adjustment_and_decision() -> None:
    # (n_pos, n_neg): dense 0/6 -> p 2/64; bm25 0/9 -> p 2/512; hybrid+graph 3/2 -> p 1.
    family = _family(
        {"dense-only": (0, 6), "bm25-only": (0, 9), "hybrid+graph": (3, 2)}
    )
    rows = by_arm(family)
    assert [c.arm for c in family.comparisons] == list(COMPARISON_ARMS)
    assert family.m == 3 and family.alpha == 0.05
    assert rows["dense-only"].raw_p == pytest.approx(2 / 64)
    assert rows["bm25-only"].raw_p == pytest.approx(2 / 512)
    assert rows["hybrid+graph"].raw_p == pytest.approx(1.0)
    for arm in COMPARISON_ARMS:
        assert rows[arm].n_pairs == 40
    assert (rows["bm25-only"].n_pos, rows["bm25-only"].n_neg) == (0, 9)
    # Holm: bm25 0.0039 <= 0.05/3 rejects; dense 0.03125 > 0.05/2 stops the procedure.
    assert rows["bm25-only"].adjusted_p == pytest.approx(3 * 2 / 512)
    assert rows["dense-only"].adjusted_p == pytest.approx(2 * 2 / 64)
    assert rows["hybrid+graph"].adjusted_p == pytest.approx(1.0)
    assert rows["bm25-only"].decision == "significant"
    assert rows["dense-only"].decision == "not significant"
    assert rows["hybrid+graph"].decision == "not significant"
    # and the module agrees with the library it wraps, row by row
    ps = [float(exact_signflip_p(*divmod_pair(rows[a]))) for a in COMPARISON_ARMS]
    reject, adjusted = holm_stepdown(ps, alpha=0.05)
    assert [rows[a].decision == "significant" for a in COMPARISON_ARMS] == reject
    assert [rows[a].adjusted_p for a in COMPARISON_ARMS] == pytest.approx(adjusted)


def divmod_pair(row: Any) -> tuple[int, int]:
    return row.n_pos, row.n_neg


def test_significant_appears_only_on_a_rejected_row() -> None:
    family = _family(
        {"dense-only": (0, 6), "bm25-only": (0, 9), "hybrid+graph": (3, 2)}
    )
    decisions = {c.arm: c.decision for c in family.comparisons}
    assert decisions == {
        "dense-only": "not significant",
        "bm25-only": "significant",
        "hybrid+graph": "not significant",
    }
    for c in family.comparisons:
        rejected = c.raw_p <= 0.05 / 3 and c.arm == "bm25-only"
        assert (c.decision == "significant") == rejected


def test_the_step_down_stops_at_the_first_failure() -> None:
    # bm25 p = 2/512 rejects, dense p = 2/64 > 0.05/2 fails, and hybrid+graph p = 20/512
    # = 0.039 would pass 0.05 alone but is retained because the procedure has stopped.
    family = _family(
        {"dense-only": (0, 6), "bm25-only": (0, 9), "hybrid+graph": (1, 8)}
    )
    rows = by_arm(family)
    assert rows["hybrid+graph"].raw_p == pytest.approx(20 / 512)
    assert rows["hybrid+graph"].raw_p <= 0.05
    assert rows["bm25-only"].decision == "significant"
    assert rows["dense-only"].decision == "not significant"
    assert rows["hybrid+graph"].decision == "not significant"
    assert rows["hybrid+graph"].adjusted_p == pytest.approx(2 * 2 / 64)


def test_nothing_is_rejected_when_the_smallest_p_misses_its_threshold() -> None:
    family = _family(
        {"dense-only": (0, 6), "bm25-only": (0, 5), "hybrid+graph": (1, 1)}
    )
    assert all(c.decision == "not significant" for c in family.comparisons)
    assert min(c.raw_p for c in family.comparisons) > 0.05 / 3


def test_a_ci_that_excludes_zero_without_a_rejection_reads_as_exactly_that() -> None:
    family = _family(
        {"dense-only": (0, 6), "bm25-only": (0, 9), "hybrid+graph": (3, 2)}
    )
    rows = by_arm(family)
    dense = rows["dense-only"]
    # the precondition: the CI really excludes 0 and Holm did not reject
    assert dense.ci_hi is not None and dense.ci_hi < 0
    assert dense.decision == "not significant"
    assert dense.ci_note == "CI excludes 0; not significant after Holm"
    assert EXCLUDES_ZERO_NOTE == dense.ci_note
    # a rejected row and a CI that includes 0 carry no such note
    assert rows["bm25-only"].ci_note is None
    assert rows["hybrid+graph"].ci_lo is not None and rows["hybrid+graph"].ci_lo < 0
    assert rows["hybrid+graph"].ci_note is None


def test_every_ci_is_labelled_unadjusted_estimation_only_with_the_delta_and_n() -> None:
    family = _family(
        {"dense-only": (0, 6), "bm25-only": (0, 9), "hybrid+graph": (3, 2)}
    )
    assert LABEL_UNADJUSTED == UNADJUSTED
    for c in family.comparisons:
        assert c.ci_label == UNADJUSTED
        assert c.delta == pytest.approx((c.n_pos - c.n_neg) / c.n_pairs)
    assert family.comparisons[1].delta == pytest.approx(-9 / 40)


def test_coverage_below_the_floor_makes_every_comparison_not_evaluable() -> None:
    assert not coverage_evaluable(246, 308)  # 0.7987
    assert coverage_evaluable(247, 308)
    assert coverage_evaluable(8, 10)  # exactly 0.80
    assert coverage_evaluable(4, 5)
    assert not coverage_evaluable(799, 1000)
    assert coverage_evaluable(800, 1000)
    assert not coverage_evaluable(0, 308)
    values = values_from_counts(
        40, {"dense-only": (0, 9), "bm25-only": (0, 9), "hybrid+graph": (0, 9)}
    )
    for primary in ("paper_hits_at_4", "answer_usable"):
        family = holm_family(primary, values, evaluable=False)
        assert family.evaluable is False
        assert len(family.comparisons) == 3
        for c in family.comparisons:
            assert c.decision == "not evaluable: coverage"
            assert c.raw_p is None and c.adjusted_p is None
            assert c.ci_note is None


def test_a_flipped_decision_under_the_text_rule_reads_not_robust() -> None:
    id_values = values_from_counts(
        40, {"dense-only": (0, 6), "bm25-only": (0, 9), "hybrid+graph": (3, 2)}
    )
    text_values = values_from_counts(
        40, {"dense-only": (0, 6), "bm25-only": (0, 5), "hybrid+graph": (3, 2)}
    )
    family = holm_family(
        "paper_hits_at_4",
        id_values,
        evaluable=True,
        matching_rule="ID rule",
        text_values=text_values,
    )
    rows = by_arm(family)
    assert rows["bm25-only"].decision == "significant"
    assert rows["bm25-only"].text_rule_decision == "not significant"
    assert rows["bm25-only"].robustness == NOT_ROBUST
    assert rows["dense-only"].text_rule_decision == "not significant"
    assert rows["dense-only"].robustness == "robust to the matching rule"
    assert rows["bm25-only"].text_rule_raw_p == pytest.approx(2 / 32)


def test_no_text_values_means_no_robustness_claim() -> None:
    family = _family(
        {"dense-only": (0, 6), "bm25-only": (0, 9), "hybrid+graph": (3, 2)}
    )
    for c in family.comparisons:
        assert c.robustness is None and c.text_rule_decision is None


# ---- strata cells -----------------------------------------------------------------


def test_a_stratum_below_ten_has_no_ci_and_at_ten_it_has_one() -> None:
    assert format_stratum_cell(0.5, None, None, 9) == "0.5000 (n = 9; n < 10, no CI)"
    assert format_stratum_cell(0.5, 0.25, 0.75, 10) == "0.5000 [0.2500, 0.7500] (10)"
    assert format_stratum_cell(None, None, None, 0) == "n/a (n = 0; n < 10, no CI)"


# ---- constants quoted from the sources ---------------------------------------------


def test_the_paper_reference_rows_are_table_5_without_reranker_verbatim() -> None:
    rows = {r["embedding"]: r for r in PAPER_REFERENCE_TABLE5["rows"]}
    assert set(rows) == {"bge-large-en-v1.5", "voyage-02"}
    assert rows["bge-large-en-v1.5"]["mrr_at_10"] == 0.4298
    assert rows["bge-large-en-v1.5"]["map_at_10"] == 0.3423
    assert rows["bge-large-en-v1.5"]["hits_at_10"] == 0.6718
    assert rows["bge-large-en-v1.5"]["hits_at_4"] == 0.5221
    assert rows["voyage-02"]["mrr_at_10"] == 0.3934
    assert rows["voyage-02"]["map_at_10"] == 0.3143
    assert rows["voyage-02"]["hits_at_10"] == 0.6506
    assert rows["voyage-02"]["hits_at_4"] == 0.4619
    assert PAPER_REFERENCE_TABLE5["citation"] == "arXiv 2401.15391 v1, Table 5"
    assert PAPER_REFERENCE_TABLE5["configuration"] == "Without Reranker"
    assert (
        PAPER_REFERENCE_TABLE5["caption"]
        == "Retrieval performance of different embedding models."
    )


def test_the_caveat_names_a_to_f_population_subset_chunker_and_embedder() -> None:
    text = " ".join(NON_COMPARABILITY_CAVEAT)
    for needle in (
        "(a)",
        "(b)",
        "(c)",
        "(d)",
        "(e)",
        "(f)",
        "no BM25 or hybrid",
        "256-token",
        "bge-reranker-large",
        "any relevant chunk",
        "text matching",
        "chunk-ID matching",
        "NULL queries are excluded",
        "all non-null queries",
        "346",
        "chunker",
        "embedder",
    ):
        assert needle in text, needle


def test_the_four_d124_ids_are_held_out_and_were_in_the_legacy_canary_file() -> None:
    ids = (
        "mhr-0073ab564e55",
        "mhr-00fc91a80765",
        "mhr-12912d800c0c",
        "mhr-0279d4a349c3",
    )
    assert D124_IDS == ids
    for qid in ids:
        assert qid in D124_DISCLOSURE
    split = json.loads(
        (REPO / "eval/corpora/multihop_rag/heldout_split.json").read_text("utf-8")
    )
    heldout = set(split["heldout_g_ids"]) | set(split["heldout_null_ids"])
    canary = (REPO / "eval/corpora/multihop_rag/canary.jsonl").read_text("utf-8")
    for qid in ids:
        assert qid in heldout
        assert qid in canary
    assert "drives 1b and 2" in D124_DISCLOSURE


def test_the_fwer_statement_and_the_approximation_label_are_planned() -> None:
    assert "can reach 0.10" in FWER_STATEMENT
    assert APPROXIMATION_LABEL == APPROXIMATION


def test_the_module_lists_the_thirteen_secondary_delta_metrics() -> None:
    assert len(SECONDARY_DELTA_BASES) == 13
    assert all(b.endswith("_delta") for b in SECONDARY_DELTA_BASES)


# ---- the AST pin: no second judged-aggregate path ----------------------------------


def _imported_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            names.update(f"{module}.{a.name}" for a in node.names)
    return names


@pytest.mark.parametrize("forbidden", ["judge", "judge_stage", "calibration"])
def test_comparison_py_never_imports_the_judge_or_the_calibration_modules(
    forbidden: str,
) -> None:
    source = Path(cmp_mod.__file__).read_text(encoding="utf-8")
    imported = _imported_names(source)
    assert f"lancet_eval.{forbidden}" not in imported
    assert not any(n.startswith(f"lancet_eval.{forbidden}.") for n in imported)
    assert f"lancet_eval.{forbidden}" not in {
        n for n in imported if n.count(".") == 1
    }


def test_the_pin_catches_the_form_score_py_uses() -> None:
    assert "lancet_eval.calibration" in _imported_names(
        "def f():\n    from lancet_eval import calibration\n"
    )
    assert "lancet_eval.judge_stage" in _imported_names(
        "from lancet_eval.judge_stage import run_judge_stage\n"
    )
    assert "lancet_eval.judge" in _imported_names("import lancet_eval.judge\n")


# ---- integration: a real `score --judged` run --------------------------------------


@pytest.fixture(scope="module")
def ordered(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The calibrated four-arm run, scored once; the corpus patch stays alive."""
    mp = pytest.MonkeyPatch()
    base = tmp_path_factory.mktemp("compare_ordered")
    try:
        sc = sj.build(base, mp)
        sj.run_score(sc)
        pristine = base / "pristine"
        shutil.copytree(sc.run, pristine)
        yield sc, pristine
    finally:
        mp.undo()


def fresh_run(ordered: Any, tmp_path: Path) -> Path:
    sc, pristine = ordered
    dest = tmp_path / "run"
    shutil.copytree(pristine, dest)
    return dest


@pytest.fixture(scope="module")
def written(ordered: Any, tmp_path_factory: pytest.TempPathFactory) -> Any:
    sc, pristine = ordered
    dest = tmp_path_factory.mktemp("compare_written") / "run"
    shutil.copytree(pristine, dest)
    report_bytes = (dest / "report.json").read_bytes()
    comparison = write_comparison(dest, gold_chunks_path=sc.gold)
    return {
        "dir": dest,
        "comparison": comparison,
        "md": (dest / "comparison.md").read_text(encoding="utf-8"),
        "json": json.loads((dest / "comparison.json").read_text(encoding="utf-8")),
        "report": json.loads((dest / "report.json").read_text(encoding="utf-8")),
        "report_bytes_before": report_bytes,
        "sidecar": JudgedResult.model_validate_json(
            (dest / "judged-result.json").read_text(encoding="utf-8")
        ),
    }


def dims_of(report: Mapping[str, Any]) -> dict[str, Any]:
    return {d["name"]: d for d in report["dimensions"]}


def section(md: str, heading: str) -> str:
    start = md.index(f"## {heading}")
    nxt = md.find("\n## ", start + 1)
    return md[start : nxt if nxt != -1 else len(md)]


def holm_section(md: str) -> str:
    start = md.index("## Pre-registered inference")
    nxt = md.find("\n## ", start + 1)
    return md[start : nxt if nxt != -1 else len(md)]


def test_the_comparison_validates_and_names_the_four_arms_and_both_conventions(
    written: Any,
) -> None:
    comp = written["comparison"]
    assert isinstance(comp, Comparison)
    assert Comparison.model_validate(written["json"]) == comp
    md = written["md"]
    for arm in sj.ARMS:
        assert arm in md
    for metric in (
        "paper_hits_at_4",
        "paper_hits_at_10",
        "paper_mrr_at_10",
        "paper_map_at_10",
        "coverage_at_4",
        "precision_at_4",
        "answer_usable_p4",
        "abstention_rate_g",
        "null_abstention_correctness",
        "answer_groundedness",
        "answer_faithfulness",
        "latency_total_ms_p50",
        "latency_total_ms_p95",
        "retrieve_node_ms_p50",
        "prompt_tokens_mean",
        "spend_usd_mean",
    ):
        assert metric in md, metric
    assert "script-faithful" in md
    assert "Paper reference (cited; not comparable, see caveat)" in md
    assert [a.arm for a in comp.arms] == list(sj.ARMS)


def test_the_run_wrote_its_comparison_sidecars_and_left_report_json_alone(
    written: Any,
) -> None:
    run = written["dir"]
    for name in ("comparison.json", "comparison.md"):
        assert (run / name).is_file(), name
    assert (run / "report.json").read_bytes() == written["report_bytes_before"]
    assert not list(run.glob("*.png"))


def test_p4_size_coverage_and_exclusions_are_printed(written: Any) -> None:
    comp = written["comparison"]
    assert comp.p4.n_p4 == len(sj.G_IDS) == 26
    assert comp.p4.n_heldout_g == 26
    assert comp.p4.coverage == pytest.approx(1.0)
    assert comp.p4.evaluable is True
    assert set(comp.p4.excluded) == set(sj.ARMS)
    assert "26 of 26" in written["md"]


def _usable_counts(arm: str) -> tuple[int, int]:
    n_pos = n_neg = 0
    for qid in sj.G_IDS:
        arm_ok = qid not in sj.ABSTAIN[arm]
        ref_ok = qid not in sj.ABSTAIN["hybrid"]
        n_pos += int(arm_ok and not ref_ok)
        n_neg += int(ref_ok and not arm_ok)
    return n_pos, n_neg


def test_the_real_run_yields_the_known_answer_usable_family(written: Any) -> None:
    comp = written["comparison"]
    fam = {f.primary: f for f in comp.families}
    assert set(fam) == {"paper_hits_at_4", "answer_usable"}
    rows = by_arm(fam["answer_usable"])
    assert (rows["dense-only"].n_pos, rows["dense-only"].n_neg) == _usable_counts(
        "dense-only"
    ) == (2, 0)
    assert (rows["bm25-only"].n_pos, rows["bm25-only"].n_neg) == _usable_counts(
        "bm25-only"
    ) == (1, 8)
    assert (rows["hybrid+graph"].n_pos, rows["hybrid+graph"].n_neg) == _usable_counts(
        "hybrid+graph"
    ) == (2, 1)
    assert rows["dense-only"].raw_p == pytest.approx(0.5)
    assert rows["bm25-only"].raw_p == pytest.approx(20 / 512)
    assert rows["hybrid+graph"].raw_p == pytest.approx(1.0)
    assert all(c.n_pairs == 26 for c in rows.values())
    # 20/512 = 0.039 misses the first Holm threshold 0.05/3, so nothing is rejected
    assert all(c.decision == "not significant" for c in rows.values())
    assert rows["bm25-only"].delta == pytest.approx(-7 / 26)
    assert rows["bm25-only"].ci_hi is not None and rows["bm25-only"].ci_hi < 0
    assert rows["bm25-only"].ci_note == EXCLUDES_ZERO_NOTE


def test_every_hit_at_four_pair_is_a_tie_on_this_run(written: Any) -> None:
    fam = {f.primary: f for f in written["comparison"].families}["paper_hits_at_4"]
    for c in fam.comparisons:
        assert (c.n_pos, c.n_neg) == (0, 0)
        assert c.raw_p == pytest.approx(1.0)
        assert c.decision == "not significant"
        assert c.ci_note is None
    assert fam.matching_rule == "ID rule"


def test_the_markdown_prints_a_holm_table_and_the_fwer_statement(written: Any) -> None:
    md = written["md"]
    holm = holm_section(md)
    assert "can reach 0.10" in holm
    assert "20/512" not in holm  # the p-value is printed as a number, not a fraction
    assert "0.0391" in holm
    assert EXCLUDES_ZERO_NOTE in holm
    assert "unadjusted, estimation only" in holm
    assert "significant" not in md.replace(holm, "")


def test_the_markdown_outside_the_holm_section_never_says_significant(
    written: Any,
) -> None:
    md = written["md"]
    assert "significant" in holm_section(md)
    rest = md.replace(holm_section(md), "")
    assert "significant" not in rest.lower()


# ---- secondary paired deltas ---------------------------------------------------------


def test_secondary_deltas_are_read_from_report_json_one_row_per_dimension(
    written: Any,
) -> None:
    rows = written["json"]["secondary_deltas"]
    dims = dims_of(written["report"])
    assert len(rows) == 13 * 3
    seen = set()
    for row in rows:
        base = row["metric"] + "_delta"
        assert base in SECONDARY_DELTA_BASES
        dim = dims[f"{base}__{SLUG[row['arm']]}"]
        seen.add((row["metric"], row["arm"]))
        assert row["delta"] == dim["score"]
        assert row["ci_lo"] == dim["detail"]["ci_lower"]
        assert row["ci_hi"] == dim["detail"]["ci_upper"]
        assert row["n_pairs"] == int(dim["detail"]["n_pairs"])
        assert row["mean_arm"] == dim["detail"]["mean_x"]
        assert row["mean_hybrid"] == dim["detail"]["mean_hybrid"]
        assert row["label"] == UNADJUSTED
        assert not {"p", "p_value", "raw_p", "adjusted_p", "decision"} & set(row)
    assert len(seen) == 39
    assert {r["arm"] for r in rows} == set(COMPARISON_ARMS)


def test_the_secondary_section_has_its_heading_a_row_per_delta_and_no_p_value(
    written: Any,
) -> None:
    md = written["md"]
    sec = section(md, SECONDARY_HEADING)
    comp = written["comparison"]
    for row in comp.secondary_deltas:
        assert row.metric in sec
    assert sec.count("n_pairs") >= 1 or "n pairs" in sec.lower()
    assert "p-value" not in sec.lower() and "adjusted" not in sec.lower().replace(
        UNADJUSTED, ""
    )
    assert "significant" not in sec.lower()


def test_a_secondary_whose_ci_excludes_zero_is_printed_without_the_word_significant(
    written: Any,
) -> None:
    excluding = [
        r
        for r in written["comparison"].secondary_deltas
        if r.ci_lo is not None and r.ci_hi is not None and (r.ci_lo > 0 or r.ci_hi < 0)
    ]
    assert excluding, "the fixture must contain a secondary whose CI excludes 0"
    sec = section(written["md"], SECONDARY_HEADING)
    for r in excluding:
        line = next(
            ln
            for ln in sec.splitlines()
            if ln.startswith("|") and f"`{r.metric}`" in ln and r.arm in ln
        )
        assert "significant" not in line.lower()
        assert format_number(r.delta) in line
    # and no secondary is a member of any Holm family
    members = {c.arm for f in written["comparison"].families for c in f.comparisons}
    assert members == set(COMPARISON_ARMS)
    assert {f.primary for f in written["comparison"].families} == {
        "paper_hits_at_4",
        "answer_usable",
    }


def test_latency_percentiles_are_descriptive_with_no_delta_beside_the_per_question_note(
    written: Any,
) -> None:
    sec = section(written["md"], SECONDARY_HEADING)
    assert "per-question mean" in sec
    for metric in ("latency_total_ms", "retrieve_node_ms"):
        for stat in ("p50", "p95"):
            assert f"{metric}_{stat}" in written["md"]
            assert f"{metric}_{stat}_delta" not in written["md"]
    dims = dims_of(written["report"])
    assert not [n for n in dims if "_p50_delta" in n or "_p95_delta" in n]


def test_the_bm25_only_rows_carry_no_embedding_caveat_label(written: Any) -> None:
    md = written["md"]
    assert "includes the query embedding" not in md
    assert "includes the query embedding" not in json.dumps(written["json"])


# ---- D-40 strata ---------------------------------------------------------------------

STRATA_METRICS_REPORT = (
    "paper_hits_at_4",
    "paper_hits_at_10",
    "paper_mrr_at_10",
    "paper_map_at_10",
    "paper_hits_at_4_script_faithful",
    "answer_usable_p4",
    "answer_usable_sc3_definition",
    "abstention_rate_g",
    "final_answer_em",
    "gold_containment",
    "final_answer_missing_rate",
    "coverage_at_4",
    "precision_at_4",
    "prompt_tokens_mean",
    "latency_total_ms_p50",
    "latency_total_ms_p95",
    "retrieve_node_ms_p50",
    "retrieve_node_ms_p95",
)
TYPES = ("comparison_query", "inference_query", "temporal_query")


def test_strata_rows_exist_for_every_metric_arm_and_type_with_the_report_values(
    written: Any,
) -> None:
    rows = written["json"]["strata"]
    dims = dims_of(written["report"])
    index = {(r["metric"], r["arm"], r["question_type"]): r for r in rows}
    for metric in STRATA_METRICS_REPORT:
        for arm in sj.ARMS:
            for qt in TYPES:
                row = index[(metric, arm, qt)]
                detail = dims[f"{metric}__{SLUG[arm]}"]["detail"]
                assert row["n"] == int(detail[f"type_{qt}_n"])
                assert row["value"] == detail.get(f"type_{qt}_value")
                assert row["ci_lo"] == detail.get(f"type_{qt}_ci_lower")
                assert row["ci_hi"] == detail.get(f"type_{qt}_ci_upper")
    for metric in ("answer_groundedness", "answer_faithfulness"):
        for arm in sj.ARMS:
            for qt in TYPES:
                assert (metric, arm, qt) in index
    scanned = {
        n.split("__")[0]
        for n, d in dims.items()
        if "__" in n
        and "_delta__" not in n
        and not n.startswith(("answer_groundedness", "answer_faithfulness"))
        and "type_comparison_query_n" in d["detail"]
    }
    assert set(STRATA_METRICS_REPORT) <= scanned
    assert len(rows) == (len(scanned) + 2) * 4 * 3


def test_a_stratum_has_a_ci_only_at_ten_or_more(written: Any) -> None:
    rows = written["json"]["strata"]
    cell = 10
    seen_with = seen_without = 0
    for r in rows:
        if r["n"] >= cell and r["metric"] in (
            "paper_hits_at_4",
            "answer_usable_p4",
        ):
            assert r["ci_lo"] is not None and r["ci_hi"] is not None
            seen_with += 1
        if r["n"] < cell:
            assert r["ci_lo"] is None and r["ci_hi"] is None, r
            seen_without += 1
    assert seen_with and seen_without
    inference = next(
        r
        for r in rows
        if r["metric"] == "paper_hits_at_4"
        and r["arm"] == "hybrid"
        and r["question_type"] == "inference_query"
    )
    temporal = next(
        r
        for r in rows
        if r["metric"] == "paper_hits_at_4"
        and r["arm"] == "hybrid"
        and r["question_type"] == "temporal_query"
    )
    assert inference["n"] == 10 and inference["ci_lo"] is not None
    assert temporal["n"] == 4 and temporal["ci_lo"] is None


def test_the_strata_section_prints_cells_in_the_planned_format(written: Any) -> None:
    sec = section(written["md"], STRATA_HEADING)
    assert re.search(r"\d\.\d{4} \[\d\.\d{4}, \d\.\d{4}\] \(10\)", sec)
    assert re.search(r"\d\.\d{4} \(n = 4; n < 10, no CI\)", sec)


def test_answer_usable_strata_carry_the_constant_yes_baseline_beside_them(
    written: Any,
) -> None:
    rows = written["json"]["strata"]
    for r in rows:
        if r["metric"] in ("answer_usable_p4", "answer_usable_sc3_definition"):
            assert r["constant_yes_baseline"] == pytest.approx(1.0)  # every gold is Yes
        else:
            assert r["constant_yes_baseline"] is None
    sec = section(written["md"], STRATA_HEADING)
    assert "constant-Yes" in sec


def test_the_primary_delta_strata_are_the_paired_delta_strata_of_the_p4_values(
    written: Any,
) -> None:
    rows = written["json"]["primary_delta_strata"]
    assert len(rows) == 2 * 3 * 3
    index = {(r["metric"], r["arm"], r["question_type"]): r for r in rows}
    bm25_cmp = index[("answer_usable", "bm25-only", "comparison_query")]
    assert bm25_cmp["n_pairs"] == 12
    assert bm25_cmp["delta"] == pytest.approx(-8 / 12)
    assert bm25_cmp["ci_lo"] is not None and bm25_cmp["ci_hi"] is not None
    assert bm25_cmp["ci_label"] == UNADJUSTED
    bm25_tmp = index[("answer_usable", "bm25-only", "temporal_query")]
    assert bm25_tmp["n_pairs"] == 4 and bm25_tmp["ci_lo"] is None
    assert bm25_tmp["ci_label"] is None
    bm25_inf = index[("answer_usable", "bm25-only", "inference_query")]
    assert bm25_inf["n_pairs"] == 10 and bm25_inf["delta"] == pytest.approx(1 / 10)
    assert bm25_inf["ci_lo"] is not None
    for r in rows:
        assert r["label"] == UNADJUSTED
        if r["ci_lo"] is not None:
            assert r["ci_label"] == UNADJUSTED
    hits = index[("paper_hits_at_4", "dense-only", "comparison_query")]
    assert hits["delta"] == 0.0


def test_judged_delta_strata_are_labelled_and_read_from_the_judged_sidecar(
    written: Any,
) -> None:
    rows = written["json"]["judged_delta_strata"]
    sidecar = written["sidecar"]
    n_expected = sum(len(d.strata) for d in sidecar.deltas)
    assert len(rows) == n_expected > 0
    for r in rows:
        assert r["label"] == UNADJUSTED
        if r["ci_lo"] is not None:
            assert r["ci_label"] == UNADJUSTED


def test_no_stratum_is_called_significant_or_enters_a_holm_family(written: Any) -> None:
    sec = section(written["md"], STRATA_HEADING)
    assert "significant" not in sec.lower()
    assert "p-value" not in sec.lower()
    rows = written["json"]["strata"] + written["json"]["primary_delta_strata"]
    for r in rows:
        assert not {"p", "raw_p", "adjusted_p", "decision"} & set(r)
    for fam in written["json"]["families"]:
        assert len(fam["comparisons"]) == 3


def test_the_strata_section_has_the_judged_rows_beside_their_abstention_rate(
    written: Any,
) -> None:
    sec = section(written["md"], STRATA_HEADING)
    assert "answer_groundedness" in sec and "answer_faithfulness" in sec
    assert "abstention" in sec.lower()


# ---- judged rows, labels, lines and disclosures --------------------------------------


def test_the_judged_rows_show_abstention_n_errors_and_the_d114_label_with_its_qwk_ci(
    written: Any,
) -> None:
    md = written["md"]
    sidecar = written["sidecar"]
    for dim in ("groundedness", "faithfulness"):
        agreement = sidecar.agreement["dimensions"][dim]
        assert sidecar.labels[dim] in md
        assert f"{agreement['qwk_ci_lower']:.4f}" in md
        assert f"{agreement['qwk_ci_upper']:.4f}" in md
    for row in sidecar.arms:
        assert row.d114_label in md
    judged = written["comparison"].arms[1].judged  # bm25-only carries the error
    assert judged["groundedness"].judge_errors == 1 or judged[
        "faithfulness"
    ].judge_errors == 1
    for line in sidecar.legacy_lines:
        assert line in md
    assert "non-governing" in md


def test_the_d121_and_d122_lines_are_labelled_and_decide_nothing(written: Any) -> None:
    md = written["md"]
    assert "SC-3 definition" in md
    assert "not directly comparable to drive 2's 0.58" in md
    assert "script-faithful" in md and "denominator 26" in md
    codes = {line.code for line in written["comparison"].lines}
    assert {"D-121", "D-122"} <= codes
    for line in written["comparison"].lines:
        assert "decides nothing" in line.text


def test_the_d124_disclosure_and_the_fwer_statement_are_in_the_markdown(
    written: Any,
) -> None:
    md = written["md"]
    for qid in D124_IDS:
        assert qid in md
    assert "reached the live system earlier" in md
    assert "can reach 0.10" in md


def test_the_reference_row_is_cited_with_its_caveat_and_no_superlative_label(
    written: Any,
) -> None:
    md = written["md"]
    sec = section(md, "Paper reference row (cited; not comparable)")
    for needle in (
        "0.4298",
        "0.3423",
        "0.6718",
        "0.5221",
        "0.3934",
        "0.3143",
        "0.6506",
        "0.4619",
    ):
        assert needle in sec
    assert "arXiv 2401.15391 v1, Table 5" in sec
    assert "Without Reranker" in sec
    caveat = written["comparison"].paper_reference.caveat
    assert len(caveat) == len(NON_COMPARABILITY_CAVEAT)
    for sentence in caveat:
        assert sentence in sec
    assert "26 G-restricted held-out questions" in sec
    assert "sota" not in md.lower()
    assert "state-of-the-art" not in md.lower()
    # the lancet line named as comparable, and its rule, with no cross-check
    assert "script-faithful" in sec
    assert APPROXIMATION in sec


def test_without_the_crosscheck_every_id_rule_paper_row_carries_the_approximation_label(
    written: Any,
) -> None:
    comp = written["comparison"]
    assert comp.robustness.ran is False
    assert comp.robustness.paper_rows_label == APPROXIMATION
    md = written["md"]
    assert md.count(APPROXIMATION) >= 4
    for fam in comp.families:
        for c in fam.comparisons:
            assert c.robustness is None


# ---- robustness with a cross-check ---------------------------------------------------


def write_crosscheck(
    run: Path,
    *,
    text_hit4: Mapping[str, Mapping[str, int]],
    index_generation: str = "gen1",
    p4_ids: list[str] | None = None,
) -> None:
    ids = p4_ids if p4_ids is not None else sorted(sj.G_IDS)
    arms: dict[str, Any] = {}
    for i, arm in enumerate(sj.ARMS):
        arms[arm] = {
            "p4": {
                "n": len(ids),
                "disagree_hit4": 3 + i,
                "disagree_hit10": 4 + i,
                "disagree_first_hit_rank": 5 + i,
                "disagree_ap": 6 + i,
                "id_rule": {},
                "text_rule": {},
            },
            "script_faithful": {
                "n": len(ids),
                "n_no_valid_ranking": 0,
                "disagree_hit4": 0,
                "disagree_hit10": 0,
                "disagree_first_hit_rank": 0,
                "disagree_ap": 0,
                "text_rule": {
                    "paper_hits_at_4": 0.25 + i / 100,
                    "paper_hits_at_10": 0.5,
                    "paper_mrr_at_10": 0.4,
                    "paper_map_at_10": 0.3,
                },
            },
        }
    payload = {
        "index_generation": index_generation,
        "official_commit": "c1c1287",
        "excerpt_max_chars": 512,
        "n_heldout_g": len(sj.G_IDS),
        "n_p4": len(ids),
        "p4_question_ids": ids,
        "records": [],
        "arms": arms,
        "per_arm_text_hit4_p4": {a: dict(v) for a, v in text_hit4.items()},
    }
    (run / "diagnostic").mkdir(exist_ok=True)
    (run / "diagnostic" / "text_crosscheck.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _text_hit4(flip_bm25: bool) -> dict[str, dict[str, int]]:
    out = {a: dict.fromkeys(sj.G_IDS, 1) for a in sj.ARMS}
    if flip_bm25:
        for qid in sj.G_IDS[:10]:
            out["bm25-only"][qid] = 0
    return out


def test_a_crosscheck_that_flips_a_decision_marks_that_row_not_robust(
    ordered: Any, tmp_path: Path
) -> None:
    sc, _ = ordered
    run = fresh_run(ordered, tmp_path)
    write_crosscheck(run, text_hit4=_text_hit4(True))
    comp = build_comparison(run, gold_chunks_path=sc.gold)
    fam = {f.primary: f for f in comp.families}["paper_hits_at_4"]
    rows = by_arm(fam)
    assert rows["bm25-only"].decision == "not significant"  # the ID rule
    assert rows["bm25-only"].text_rule_decision == "significant"  # 0/10 -> 2/1024
    assert rows["bm25-only"].robustness == NOT_ROBUST
    assert rows["dense-only"].robustness == "robust to the matching rule"
    assert comp.robustness.ran is True
    assert comp.robustness.paper_rows_label is None
    assert [r.arm for r in comp.robustness.per_arm] == list(sj.ARMS)
    assert comp.robustness.per_arm[1].disagree_hit4 == 4
    # the answer_usable family is not part of the robustness check
    usable = {f.primary: f for f in comp.families}["answer_usable"]
    assert all(c.robustness is None for c in usable.comparisons)


def test_the_crosscheck_table_prints_the_per_arm_disagreement_counts(
    ordered: Any, tmp_path: Path
) -> None:
    sc, _ = ordered
    run = fresh_run(ordered, tmp_path)
    write_crosscheck(run, text_hit4=_text_hit4(True))
    write_comparison(run, gold_chunks_path=sc.gold)
    md = (run / "comparison.md").read_text(encoding="utf-8")
    assert NOT_ROBUST in md
    assert APPROXIMATION not in md
    row = next(ln for ln in md.splitlines() if ln.startswith("| bm25-only | 26 |"))
    for count in ("4", "5", "6", "7"):
        assert f"| {count} " in row or f"| {count} |" in row
    # the comparable lancet line is now the text-rule script-faithful line
    sec = section(md, "Paper reference row (cited; not comparable)")
    assert "text rule" in sec
    assert "0.2600" in sec  # bm25-only text-rule script-faithful Hits@4 = 0.25 + 1/100


def test_a_crosscheck_without_a_flip_reads_robust_everywhere(
    ordered: Any, tmp_path: Path
) -> None:
    sc, _ = ordered
    run = fresh_run(ordered, tmp_path)
    write_crosscheck(run, text_hit4=_text_hit4(False))
    comp = build_comparison(run, gold_chunks_path=sc.gold)
    fam = {f.primary: f for f in comp.families}["paper_hits_at_4"]
    assert all(c.robustness == "robust to the matching rule" for c in fam.comparisons)


def test_a_stale_crosscheck_refuses(ordered: Any, tmp_path: Path) -> None:
    sc, _ = ordered
    run = fresh_run(ordered, tmp_path)
    write_crosscheck(
        run, text_hit4=_text_hit4(False), p4_ids=sorted(sj.G_IDS)[:-1]
    )
    with pytest.raises(ComparisonError, match="cross-check"):
        build_comparison(run, gold_chunks_path=sc.gold)
    run2 = tmp_path / "run2"
    shutil.copytree(run, run2)
    write_crosscheck(run2, text_hit4=_text_hit4(False), index_generation="gen9")
    with pytest.raises(ComparisonError, match="index_generation"):
        build_comparison(run2, gold_chunks_path=sc.gold)


def test_a_coverage_below_the_floor_reads_not_evaluable_end_to_end(
    ordered: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc, _ = ordered
    run = fresh_run(ordered, tmp_path)
    monkeypatch.setattr(cmp_mod, "coverage_evaluable", lambda *a, **k: False)
    comp = build_comparison(run, gold_chunks_path=sc.gold)
    assert comp.p4.evaluable is False
    for fam in comp.families:
        assert fam.evaluable is False
        for c in fam.comparisons:
            assert c.decision == "not evaluable: coverage"
            assert c.raw_p is None and c.delta is None
    assert "|P4| / |H_G| is below" in cmp_mod.render_markdown(comp)


# ---- refusals ------------------------------------------------------------------------


def _no_sidecars(run: Path) -> None:
    for name in ("comparison.json", "comparison.md", "chart.json", "chart.svg"):
        assert not (run / name).exists(), name


def test_compare_refuses_without_judged_result_json(
    ordered: Any, tmp_path: Path
) -> None:
    sc, _ = ordered
    run = fresh_run(ordered, tmp_path)
    (run / "judged-result.json").unlink()
    with pytest.raises(ComparisonError, match="judged-result.json"):
        write_comparison(run, gold_chunks_path=sc.gold)
    _no_sidecars(run)


def test_compare_refuses_a_report_without_the_judged_dimensions(
    ordered: Any, tmp_path: Path
) -> None:
    sc, _ = ordered
    run = fresh_run(ordered, tmp_path)
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    report["dimensions"] = [
        d for d in report["dimensions"] if "groundedness" not in d["name"]
    ]
    (run / "report.json").write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ComparisonError, match="judged"):
        write_comparison(run, gold_chunks_path=sc.gold)
    _no_sidecars(run)


def test_compare_refuses_a_report_that_disagrees_with_the_journal(
    ordered: Any, tmp_path: Path
) -> None:
    sc, _ = ordered
    run = fresh_run(ordered, tmp_path)
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    for d in report["dimensions"]:
        if d["name"] == "answer_usable_p4__hybrid":
            d["score"] = 0.5
    (run / "report.json").write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ComparisonError, match="answer_usable_p4__hybrid"):
        write_comparison(run, gold_chunks_path=sc.gold)
    _no_sidecars(run)


def test_compare_refuses_a_judged_result_of_another_corpus(
    ordered: Any, tmp_path: Path
) -> None:
    sc, _ = ordered
    run = fresh_run(ordered, tmp_path)
    data = json.loads((run / "judged-result.json").read_text(encoding="utf-8"))
    data["corpus"] = "some_other_corpus"
    (run / "judged-result.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ComparisonError, match="corpus"):
        write_comparison(run, gold_chunks_path=sc.gold)
    _no_sidecars(run)


def test_compare_refuses_an_unknown_delta_dimension(
    ordered: Any, tmp_path: Path
) -> None:
    sc, _ = ordered
    run = fresh_run(ordered, tmp_path)
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    extra = dict(next(d for d in report["dimensions"] if "_delta__" in d["name"]))
    extra["name"] = "mystery_delta__dense_only"
    report["dimensions"].append(extra)
    (run / "report.json").write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ComparisonError, match="mystery_delta__dense_only"):
        write_comparison(run, gold_chunks_path=sc.gold)


def test_compare_never_opens_the_judge_cache_and_is_idempotent(
    ordered: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc, _ = ordered
    run = fresh_run(ordered, tmp_path)
    (run / "judge_cache.json").unlink()

    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("compare must not open the judge cache")

    monkeypatch.setattr(JudgeCache, "__init__", boom)
    write_comparison(run, gold_chunks_path=sc.gold)
    first = {n: (run / n).read_bytes() for n in ("comparison.json", "comparison.md")}
    write_comparison(run, gold_chunks_path=sc.gold)
    second = {n: (run / n).read_bytes() for n in first}
    assert first == second
    assert all(b"\r\n" not in v for v in first.values())


# ---- the command ---------------------------------------------------------------------


def test_the_compare_command_writes_the_sidecars_and_exits_zero(
    ordered: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc, _ = ordered
    run = fresh_run(ordered, tmp_path)
    real = cmp_mod.write_comparison
    monkeypatch.setattr(
        cmp_mod,
        "write_comparison",
        lambda run_dir, **kw: real(run_dir, gold_chunks_path=sc.gold),
    )
    result = CliRunner().invoke(app, ["compare", "--run", str(run)])
    assert result.exit_code == 0, result.output
    for name in ("comparison.json", "comparison.md", "chart.json", "chart.svg"):
        assert (run / name).is_file()
    assert not list(run.glob("*.png"))
    assert "chart.svg" in result.output


def test_the_compare_command_exits_one_when_it_refuses(
    ordered: Any, tmp_path: Path
) -> None:
    run = fresh_run(ordered, tmp_path)
    (run / "judged-result.json").unlink()
    result = CliRunner().invoke(app, ["compare", "--run", str(run)])
    assert result.exit_code == 1
    assert "judged-result.json" in result.output
    _no_sidecars(run)


# ---- Task 2: chart.json and the deterministic chart.svg ---------------------------

CHART_KEYS = {"schema_version", "run", "arms", "series", "paper_reference", "caveat"}
SERIES_KEYS = {"metric", "arm", "value", "ci_lo", "ci_hi", "n"}
SVG_NS = "{http://www.w3.org/2000/svg}"


def _svg_root(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def _by_class(root: ET.Element, tag: str, cls: str) -> list[ET.Element]:
    return [
        e
        for e in root.iter(f"{SVG_NS}{tag}")
        if cls in (e.get("class") or "").split()
    ]


def test_the_sidecar_list_names_all_four_files() -> None:
    assert SIDECAR_FILES == (
        "comparison.json",
        "comparison.md",
        "chart.json",
        "chart.svg",
    )


def test_chart_data_has_the_planned_keys_arms_and_series(written: Any) -> None:
    comp = written["comparison"]
    data = build_chart_data(comp)
    assert set(data) == CHART_KEYS
    assert data["schema_version"] == 1
    assert data["run"] == comp.run.run
    assert data["arms"] == list(sj.ARMS)
    series = data["series"]
    assert len(series) == 2 * 4
    assert {r["metric"] for r in series} == {"paper_hits_at_4", "answer_usable_p4"}
    dims = dims_of(written["report"])
    for row in series:
        assert set(row) == SERIES_KEYS
        dim = dims[f"{row['metric']}__{SLUG[row['arm']]}"]
        assert row["value"] == dim["score"]
        assert row["ci_lo"] == dim["detail"]["ci_lower"]  # the Wilson interval
        assert row["ci_hi"] == dim["detail"]["ci_upper"]
        assert row["n"] == dim["n"] == 26
    order = [(r["metric"], r["arm"]) for r in series]
    expected = [
        (m, a) for m in ("paper_hits_at_4", "answer_usable_p4") for a in sj.ARMS
    ]
    assert order == expected


def test_chart_data_carries_the_paper_reference_and_the_caveat(written: Any) -> None:
    data = build_chart_data(written["comparison"])
    ref = data["paper_reference"]
    assert ref["citation"] == PAPER_REFERENCE_TABLE5["citation"]
    assert ref["configuration"] == "Without Reranker"
    assert ref["rows"] == PAPER_REFERENCE_TABLE5["rows"]
    assert "not comparable" in data["caveat"]
    assert APPROXIMATION in data["caveat"]  # no cross-check on this run
    assert "sota" not in json.dumps(data).lower()


def test_the_svg_is_well_formed_with_a_group_per_metric_and_a_bar_per_arm(
    written: Any,
) -> None:
    svg = render_chart_svg(build_chart_data(written["comparison"]))
    root = _svg_root(svg)
    assert root.tag == f"{SVG_NS}svg"
    assert root.get("version") == "1.1"
    groups = _by_class(root, "g", "bar-group")
    assert [g.get("data-metric") for g in groups] == [
        "paper_hits_at_4",
        "answer_usable_p4",
    ]
    for group in groups:
        bars = _by_class(group, "rect", "bar")
        assert [b.get("data-arm") for b in bars] == list(sj.ARMS)
        assert len(_by_class(group, "line", "errbar")) == 4
    assert len(_by_class(root, "rect", "bar")) == 8
    assert len(_by_class(root, "line", "errbar")) == 8


def test_bar_heights_and_error_bars_follow_a_fixed_zero_to_one_scale(
    written: Any,
) -> None:
    data = build_chart_data(written["comparison"])
    root = _svg_root(render_chart_svg(data))
    usable = next(
        g
        for g in _by_class(root, "g", "bar-group")
        if g.get("data-metric") == "answer_usable_p4"
    )
    bars = {b.get("data-arm"): b for b in _by_class(usable, "rect", "bar")}
    values = {r["arm"]: r for r in data["series"] if r["metric"] == "answer_usable_p4"}
    assert values["dense-only"]["value"] == 1.0
    scale = float(bars["dense-only"].get("height"))  # pixels per unit of value
    for arm, bar in bars.items():
        assert float(bar.get("height")) == pytest.approx(
            values[arm]["value"] * scale, abs=0.02
        )
    errbars = {e.get("data-arm"): e for e in _by_class(usable, "line", "errbar")}
    bm25 = bars["bm25-only"]
    bottom = float(bm25.get("y")) + float(bm25.get("height"))
    err = errbars["bm25-only"]
    assert float(err.get("y1")) == pytest.approx(
        bottom - values["bm25-only"]["ci_hi"] * scale, abs=0.02
    )
    assert float(err.get("y2")) == pytest.approx(
        bottom - values["bm25-only"]["ci_lo"] * scale, abs=0.02
    )


def test_the_svg_labels_the_axis_the_legend_the_source_and_the_owner(
    written: Any,
) -> None:
    svg = render_chart_svg(build_chart_data(written["comparison"]))
    root = _svg_root(svg)
    texts = [(t.text or "").strip() for t in root.iter(f"{SVG_NS}text")]
    for arm in sj.ARMS:
        assert arm in texts
    assert "0.0" in texts and "1.0" in texts
    footnote = " ".join(texts)
    assert "chart.json" in footnote
    assert "Phase 6.4" in footnote
    assert "Wilson" in footnote
    assert "sota" not in svg.lower()


def test_two_renders_of_the_same_chart_json_are_byte_identical(written: Any) -> None:
    data = build_chart_data(written["comparison"])
    first = render_chart_svg(data)
    assert render_chart_svg(data) == first
    assert render_chart_svg(json.loads(json.dumps(data))) == first
    assert "\r" not in first
    # coordinates use a fixed number of decimals, never full float precision
    assert not re.search(r"=\"-?\d+\.\d{3,}\"", first)
    assert not re.search(r"\d[eE]-\d", first)


def test_a_missing_value_draws_no_bar_and_text_is_escaped() -> None:
    data = {
        "schema_version": 1,
        "run": "run <1> & more",
        "arms": ["dense-only", "hybrid"],
        "series": [
            {
                "metric": "paper_hits_at_4",
                "arm": "dense-only",
                "value": None,
                "ci_lo": None,
                "ci_hi": None,
                "n": 0,
            },
            {
                "metric": "paper_hits_at_4",
                "arm": "hybrid",
                "value": 0.5,
                "ci_lo": 0.25,
                "ci_hi": 0.75,
                "n": 4,
            },
        ],
        "paper_reference": {
            "citation": "arXiv 2401.15391 v1, Table 5",
            "caption": "x",
            "configuration": "Without Reranker",
            "rows": [],
        },
        "caveat": 'quotes " and <tags> & ampersands',
    }
    root = _svg_root(render_chart_svg(data))
    bars = _by_class(root, "rect", "bar")
    assert [b.get("data-arm") for b in bars] == ["hybrid"]


def test_compare_writes_chart_json_and_chart_svg_from_the_same_data(
    written: Any,
) -> None:
    run = written["dir"]
    text = (run / "chart.json").read_text(encoding="utf-8")
    assert text.endswith("}\n")
    data = json.loads(text)
    assert set(data) == CHART_KEYS
    assert text == json.dumps(data, indent=2, sort_keys=True) + "\n"
    assert data == json.loads(json.dumps(build_chart_data(written["comparison"])))
    svg = (run / "chart.svg").read_text(encoding="utf-8")
    assert svg == render_chart_svg(data)  # chart.svg is rendered from chart.json alone
    _svg_root(svg)
    assert not list(run.glob("*.png"))
    assert "\r\n" not in text and "\r\n" not in svg


# ---- review additions: downstream-facing columns and the optional sidecar readers ----


def test_the_answer_usable_strata_have_a_column_named_constant_yes_baseline(
    written: Any,
) -> None:
    sec = section(written["md"], STRATA_HEADING)
    block = sec[sec.index("### `answer_usable_p4`") :]
    block = block[: block.index("\n### ", 5)]
    header = next(ln for ln in block.splitlines() if ln.startswith("| arm |"))
    assert "constant-Yes baseline" in header
    row = next(
        ln for ln in block.splitlines() if ln.startswith("| dense-only | comparison")
    )
    # every gold answer in the fixture is Yes, so the baseline is 1.0000
    assert row.rstrip().endswith("| 1.0000 |")


def test_the_judged_rows_sit_inside_the_four_arm_table_section(written: Any) -> None:
    md = written["md"]
    four_arm = section(md, "Four-arm table")
    assert "### Judged rows" in four_arm
    assert "## Judged rows" not in md.replace("### Judged rows", "")


def test_the_agreement_companions_and_the_slice_attrition_line_are_printed(
    written: Any,
) -> None:
    md = written["md"]
    sidecar = written["sidecar"]
    for dim in ("groundedness", "faithfulness"):
        d = sidecar.agreement["dimensions"][dim]
        marginals = "/".join(str(d["judge_marginals"][str(v)]) for v in range(1, 6))
        row = next(
            ln
            for ln in md.splitlines()
            if ln.startswith(f"| {dim} | ") and marginals in ln
        )
        assert f"{d['mad']:.4f}" in row
        assert f"{d['mean_signed_difference']:.4f}" in row
        assert f"{d['joint_5_5_share']:.4f}" in row
        dropped = f"{d['qwk_dropped_resamples']} / {d['spearman_dropped_resamples']}"
        assert dropped in row
    assert "No slice item was dropped for a judge error." in md
    assert written["json"]["dropped_slice_ids"] == []


def test_the_abstention_census_prints_the_leak_and_no_evidence_counts(
    written: Any,
) -> None:
    md = written["md"]
    dims = dims_of(written["report"])
    for arm in sj.ARMS:
        detail = dims[f"null_abstention_correctness__{SLUG[arm]}"]["detail"]
        row = next(
            ln
            for ln in md.splitlines()
            if ln.startswith(f"| {arm} | ") and "(n=2)" in ln
        )
        assert f"| {int(detail['hallucinated_on_null'])} | " in row
        assert f"| {int(detail['no_evidence_count'])} | " in row
        assert f"| {int(detail['leak_count'])} | " in row


def test_the_gate_and_provider_readers_take_the_real_producer_shapes(
    ordered: Any, tmp_path: Path
) -> None:
    sc, _ = ordered
    run = fresh_run(ordered, tmp_path)
    # the payload `unpark_gates._main_heldout` writes: gate -> label -> asdict(reading),
    # plus non-gate keys that must not be read as gate rows
    (run / "gates-heldout.json").write_text(
        json.dumps(
            {
                "stage": "heldout",
                "arms": list(sj.ARMS),
                "SC-1": {
                    "dense-only": {"gate": "SC-1", "status": "PASS", "n": 26},
                    "pooled": {"gate": "SC-1", "status": "MISS", "n": 104},
                },
                "SC-2": {"hybrid": {"gate": "SC-2", "status": "PASS", "n": 26}},
                "not_computed": {"SC-3": "not computed", "SC-4": "not computed"},
                "retry_provenance": "gate-stage marker present",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "diagnostic").mkdir(exist_ok=True)
    (run / "diagnostic" / "provider_format_map-summary.json").write_text(
        json.dumps(
            {
                "records": 4,
                "by_arm_provider": {
                    "dense-only": {"OpenInference": 3, "null": 1},
                    "hybrid": {"OpenInference": 2, "Sail Research": 2},
                },
                "unmatched_count": 1,
            }
        ),
        encoding="utf-8",
    )
    comp = build_comparison(run, gold_chunks_path=sc.gold)
    gates = {(g.gate, g.arm): g.status for g in comp.disclosures.gates}
    assert gates == {
        ("SC-1", "dense-only"): "PASS",
        ("SC-1", "pooled"): "MISS",
        ("SC-2", "hybrid"): "PASS",
    }
    providers = {(p.arm, p.provider): p.records for p in comp.disclosures.providers}
    assert providers == {
        ("dense-only", "OpenInference"): 3,
        ("dense-only", "null"): 1,
        ("hybrid", "OpenInference"): 2,
        ("hybrid", "Sail Research"): 2,
    }
    assert comp.disclosures.provider_unmatched == 1
    md = cmp_mod.render_markdown(comp)
    assert "Sail Research" in md and "| SC-1 | pooled | MISS |" in md
    assert "1 record(s) had no served line" in md
