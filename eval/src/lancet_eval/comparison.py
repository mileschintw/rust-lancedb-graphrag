"""The four-arm comparison of a scored, judged run (06.3.5-13; D-103, D-111, D-115).

`lancet-eval compare --run <dir>` reads a run directory that `score --judged` has
already passed through its ordering gates and writes the text-bearing sidecars that
`report.json` cannot hold (D-126): `comparison.json` and `comparison.md`, and the chart
data and interim chart `chart.json` and `chart.svg`.

Nothing judged is recomputed here. The judged rows, labels and strata are read from
`judged-result.json`, every deterministic per-arm number and every secondary paired
delta is read from `report.json`, and this module never imports the judge, the judge
stage or the calibration module and never opens the judge cache (D-113, D-120). The
only things it computes are the two pre-registered inference families (D-111, D-123)
and the per-type paired deltas of the primaries, both from the per-question 0/1 values
it rebuilds from the journal and cross-checks against `report.json`.

Inference (AI-SPEC 5 "Pre-registration block"): one Holm family per primary
(`paper_hits_at_4` under the ID rule, and `answer_usable`), each with m = 3 comparisons
against `hybrid` on P4, the exact two-sided paired sign-flip p, Holm at FWER 0.05 and a
bootstrap CI that is labelled estimation only. Only a Holm rejection is `significant`.
Every other number, every D-40 stratum included, is a secondary with no inferential
claim, and results are published in either direction (D-49).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ConfigDict

from lancet_eval import p4 as p4_mod
from lancet_eval import strata as strata_mod
from lancet_eval.arms import ARM_REGISTRY, arm_slug, canonical_arm
from lancet_eval.corpus import load_corpus_config, load_sample_questions
from lancet_eval.journal import RunRecord, load_records
from lancet_eval.metrics import answer_usable as compute_answer_usable
from lancet_eval.metrics import id_matcher, load_gold_chunk_sets, paper_question_scores
from lancet_eval.pairing import deduplicate_by_arm
from lancet_eval.report import CorpusReport
from lancet_eval.score import JudgedResult, _default_gold_chunks_path
from lancet_eval.split import load_split
from lancet_eval.stats import exact_signflip_p, holm_stepdown
from lancet_eval.thresholds import COMMITTED_THRESHOLDS, PREREGISTRATION_06_3_5

SCHEMA_VERSION = 1
SIDECAR_FILES: tuple[str, ...] = ("comparison.json", "comparison.md")

# ---- labels and fixed texts ----------------------------------------------------------

LABEL_UNADJUSTED = "unadjusted, estimation only"
APPROXIMATION_LABEL = "approximation; official text rule not verified"
ID_RULE_LABEL = "ID rule"
DECISION_SIGNIFICANT = "significant"
DECISION_NOT_SIGNIFICANT = "not significant"
DECISION_NOT_EVALUABLE = "not evaluable: coverage"
CI_EXCLUDES_ZERO_NOTE = "CI excludes 0; not significant after Holm"
ROBUST = "robust to the matching rule"
NOT_ROBUST = "not robust to the matching rule"
PAPER_ROW_LABEL = "Paper reference (cited; not comparable, see caveat)"
FWER_STATEMENT = (
    "Two Holm families, one per primary, each at familywise error rate 0.05 (m = 3). "
    "Across both primaries the familywise error rate can reach 0.10 (the Bonferroni "
    "bound), and this report states it."
)
D124_IDS: tuple[str, ...] = (
    "mhr-0073ab564e55",
    "mhr-00fc91a80765",
    "mhr-12912d800c0c",
    "mhr-0279d4a349c3",
)
D124_DISCLOSURE = (
    f"Four held-out question IDs ({', '.join(D124_IDS)}) reached the live system "
    "earlier, as floor-only canary checks in drives 1b and 2, before the held-out "
    "split existed (D-124). The four-arm preflight used the rehearsal pool only."
)
COVERAGE_NOT_EVALUABLE_NOTE = (
    "|P4| / |H_G| is below the pre-registered complete-case floor, so no primary "
    "comparison is evaluable (D-110 applies)."
)

# arXiv 2401.15391 v1 (the only version), Table 5, the "Without Reranker" half,
# verbatim from the AI-SPEC section 1b (D-103). Production runs a no-op reranker, so no
# reranker column is cited. Values are as printed in the paper.
PAPER_REFERENCE_TABLE5: dict[str, Any] = {
    "citation": "arXiv 2401.15391 v1, Table 5",
    "caption": "Retrieval performance of different embedding models.",
    "configuration": "Without Reranker",
    "rows": [
        {
            "embedding": "bge-large-en-v1.5",
            "mrr_at_10": 0.4298,
            "map_at_10": 0.3423,
            "hits_at_10": 0.6718,
            "hits_at_4": 0.5221,
        },
        {
            "embedding": "voyage-02",
            "mrr_at_10": 0.3934,
            "map_at_10": 0.3143,
            "hits_at_10": 0.6506,
            "hits_at_4": 0.4619,
        },
    ],
}

# (a)-(f) of AI-SPEC 5 #14, then the population, subset, chunker and embedder sentences.
# `{n_g}` and `{embedding_model}` are filled at build time.
NON_COMPARABILITY_CAVEAT: tuple[str, ...] = (
    "(a) The paper's setup is dense-only, and the paper has no BM25 or hybrid row; "
    "lancet's arms include BM25-only, hybrid and hybrid+graph.",
    "(b) The paper uses LlamaIndex with 256-token chunks and cosine top-K retrieval.",
    "(c) The paper's reranker columns re-rank 20 retrieved chunks with "
    "bge-reranker-large; they are not cited here, because production runs a no-op "
    "reranker.",
    "(d) The paper's prose defines Hit@K as the fraction of evidence that appears in "
    "the top-K retrieved set, but the pinned official script counts a query as a hit "
    "if any relevant chunk is in the top K, and D-102 says the script governs.",
    "(e) The official script uses text matching, while lancet's headline figures use "
    "chunk-ID matching through the gold-chunk table (the text rule is a cross-check).",
    '(f) The paper excludes nulls ("NULL queries are excluded in this experiment").',
    "Lancet's population here is the {n_g} G-restricted held-out questions, while the "
    "paper averages over all non-null queries of its 2,556-question set; "
    "G-restriction removes questions whose evidence is split across chunks or absent "
    "from the index, which raises lancet's figures relative to a full-population "
    "reading.",
    "Lancet indexes a 346-document subset of the MultiHop-RAG corpus, not the paper's "
    "full document set.",
    "Lancet's chunker and embedder (`{embedding_model}`) differ from the paper's.",
)

# The 13 deterministic secondaries that carry a paired delta against hybrid in
# `report.json` (06.3.5-10). The primaries' deltas live in the Holm families, and the
# judged deltas in the judged section (06.3.5-12).
SECONDARY_DELTA_BASES: tuple[str, ...] = (
    "paper_hits_at_10_delta",
    "paper_mrr_at_10_delta",
    "paper_map_at_10_delta",
    "abstention_rate_g_delta",
    "final_answer_em_delta",
    "gold_containment_delta",
    "final_answer_missing_rate_delta",
    "coverage_at_4_delta",
    "precision_at_4_delta",
    "prompt_tokens_delta",
    "latency_total_ms_delta",
    "retrieve_node_ms_delta",
    "spend_usd_delta",
)
JUDGED_DELTA_BASES: tuple[str, ...] = (
    "answer_groundedness_delta",
    "answer_faithfulness_delta",
)
JUDGED_DIMENSIONS = ("groundedness", "faithfulness")

# Per-arm dimensions of the four-arm table (06.3.5-10), grouped as the report prints.
PAPER_METRICS = (
    "paper_hits_at_4",
    "paper_hits_at_10",
    "paper_mrr_at_10",
    "paper_map_at_10",
)
SCRIPT_FAITHFUL_METRICS = tuple(f"{m}_script_faithful" for m in PAPER_METRICS)
ANSWER_METRICS = (
    "answer_usable_p4",
    "answer_usable_sc3_definition",
    "final_answer_em",
    "gold_containment",
    "final_answer_missing_rate",
)
LEGACY_RETRIEVAL_METRICS = ("coverage_at_4", "precision_at_4")
ABSTENTION_METRICS = ("abstention_rate_g", "null_abstention_correctness")
LATENCY_COST_METRICS = (
    "latency_total_ms_p50",
    "latency_total_ms_p95",
    "latency_total_ms_mean",
    "retrieve_node_ms_p50",
    "retrieve_node_ms_p95",
    "retrieve_node_ms_mean",
    "prompt_tokens_mean",
    "spend_usd_mean",
)
TABLE_METRICS = (
    *PAPER_METRICS,
    *SCRIPT_FAITHFUL_METRICS,
    *ANSWER_METRICS,
    *LEGACY_RETRIEVAL_METRICS,
    *ABSTENTION_METRICS,
    *LATENCY_COST_METRICS,
)
CONSTANT_YES_METRICS = ("answer_usable_p4", "answer_usable_sc3_definition")
_ARM_SLUGS = {arm_slug(arm): arm for arm in ARM_REGISTRY}


class ComparisonError(Exception):
    """Raised when the comparison cannot be built; the command exits 1."""


# ---- models --------------------------------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunInfo(_Model):
    """What identifies the scored run."""

    run: str
    corpus: str
    run_date: str
    commit_sha: str
    index_generation: str
    judge_model: str
    judge_prompt_version: str
    embedding_model: str
    arms: list[str]
    reference_arm: str


class ArmExclusionView(_Model):
    """Why one arm sees held-out G questions leave P4, and its pairwise join size."""

    own_failure: int
    provenance: int
    other_arm_failure: int
    pairwise_join_size: int | None = None


class P4Info(_Model):
    """P4 size, coverage against the pre-registered floor, and the exclusions."""

    n_p4: int
    n_heldout_g: int
    n_heldout_null: int
    coverage: float
    floor: float
    evaluable: bool
    excluded: dict[str, ArmExclusionView]


class MetricCell(_Model):
    """One per-arm number read from `report.json`, with its interval and n."""

    value: float | None
    ci_lo: float | None = None
    ci_hi: float | None = None
    n: int = 0
    status: str = "ok"
    reason: str | None = None
    detail: dict[str, float] = {}


class JudgedCell(_Model):
    """A per-arm judged mean beside the arm's abstention rate (read, not recomputed)."""

    dimension: str
    n: int
    mean: float | None
    ci_lo: float | None
    ci_hi: float | None
    judge_errors: int
    abstention_rate: float | None
    abstention_n: int
    d114_label: str
    qwk: float | None
    qwk_ci_lo: float | None
    qwk_ci_hi: float | None
    qwk_n_pairs: int


class ArmRow(_Model):
    """One arm of the four-arm table."""

    arm: str
    slug: str
    cells: dict[str, MetricCell]
    judged: dict[str, JudgedCell]


class HolmComparison(_Model):
    """One arm-versus-reference comparison of a Holm family (D-111, D-123)."""

    arm: str
    reference: str
    n_pairs: int
    n_pos: int | None = None
    n_neg: int | None = None
    raw_p: float | None = None
    adjusted_p: float | None = None
    decision: str
    ci_note: str | None = None
    delta: float | None = None
    ci_lo: float | None = None
    ci_hi: float | None = None
    ci_label: str = LABEL_UNADJUSTED
    robustness: str | None = None
    text_rule_decision: str | None = None
    text_rule_raw_p: float | None = None
    text_rule_adjusted_p: float | None = None


class HolmFamily(_Model):
    """One pre-registered family: one primary, m = 3 comparisons against hybrid."""

    primary: str
    matching_rule: str | None
    reference: str
    alpha: float
    m: int
    evaluable: bool
    comparisons: list[HolmComparison]


class SecondaryDeltaRow(_Model):
    """A secondary's paired delta against hybrid, read from `report.json`."""

    metric: str
    arm: str
    delta: float | None
    ci_lo: float | None
    ci_hi: float | None
    n_pairs: int
    mean_arm: float | None
    mean_hybrid: float | None
    label: str = LABEL_UNADJUSTED
    reason: str | None = None


class StratumRow(_Model):
    """One D-40 stratum of one per-arm metric (secondary, never decisive)."""

    metric: str
    arm: str
    question_type: str
    n: int
    value: float | None
    ci_lo: float | None
    ci_hi: float | None
    constant_yes_baseline: float | None = None
    abstention_rate: float | None = None
    abstention_n: int | None = None


class StratumDeltaRow(_Model):
    """One D-40 stratum of a paired delta; any CI is estimation only (D-123)."""

    metric: str
    arm: str
    reference: str
    question_type: str
    n_pairs: int
    delta: float | None
    ci_lo: float | None
    ci_hi: float | None
    ci_label: str | None
    label: str = LABEL_UNADJUSTED
    abstention_rate_arm: float | None = None
    abstention_rate_reference: float | None = None
    abstention_n: int | None = None


class AgreementView(_Model):
    """The judge-human agreement of one dimension and its D-114 label."""

    dimension: str
    n_pairs: int
    qwk: float | None
    qwk_ci_lo: float | None
    qwk_ci_hi: float | None
    floor: float
    label: str
    spearman: float | None
    exact_agreement: float | None


class JudgedDeltaView(_Model):
    """A paired judged delta with its selection-effect columns (D-118)."""

    arm: str
    reference: str
    dimension: str
    n_pairs: int
    delta: float | None
    ci_lo: float | None
    ci_hi: float | None
    ci_label: str = LABEL_UNADJUSTED
    dropped_only_arm_abstained: int
    dropped_only_reference_abstained: int
    dropped_both_abstained: int
    dropped_judge_unavailable: int
    judge_errors_arm: int
    judge_errors_reference: int
    abstention_rate_arm: float | None
    abstention_rate_reference: float | None
    abstention_n: int
    abstention_rate_delta: float | None
    abstention_rate_delta_ci_lo: float | None
    abstention_rate_delta_ci_hi: float | None
    flag: str | None
    d114_label: str


class ArmDisagreement(_Model):
    """Per-arm matching-rule disagreement counts over P4 (AI-SPEC 5 #5)."""

    arm: str
    n: int
    disagree_hit4: int
    disagree_hit10: int
    disagree_first_hit_rank: int
    disagree_ap: int


class Robustness(_Model):
    """The D-102 matching-rule cross-check, or the label its absence puts on rows."""

    ran: bool
    paper_rows_label: str | None
    index_generation: str | None = None
    official_commit: str | None = None
    per_arm: list[ArmDisagreement] = []


class PaperRow(_Model):
    """One cited row of the paper's Table 5."""

    embedding: str
    mrr_at_10: float
    map_at_10: float
    hits_at_10: float
    hits_at_4: float


class LineRow(_Model):
    """One arm's value on a labelled comparison line."""

    arm: str
    value: float | None
    ci_lo: float | None = None
    ci_hi: float | None = None
    n: int = 0


class PaperReference(_Model):
    """The cited reference row, its caveat and the lancet line comparable to it."""

    label: str
    citation: str
    caption: str
    configuration: str
    rows: list[PaperRow]
    caveat: list[str]
    comparable_line: str
    lancet_line_rule: str
    lancet_line: list[LineRow]


class ComparisonLine(_Model):
    """A labelled line that decides nothing (D-121, D-122)."""

    code: str
    title: str
    text: str
    rows: list[LineRow]


class GateReading(_Model):
    """One run-integrity gate reading (D-109), as `unpark_gates` wrote it."""

    gate: str
    arm: str
    status: str


class ProviderRow(_Model):
    """Records served by one provider for one arm (D-107)."""

    arm: str
    provider: str
    records: int


class Disclosures(_Model):
    """The disclosures that travel with the run of record."""

    d124: str
    gates: list[GateReading]
    providers: list[ProviderRow]
    provider_unmatched: int | None = None


class Comparison(_Model):
    """`comparison.json`: every text label of the four-arm comparison (D-126)."""

    schema_version: int = SCHEMA_VERSION
    run: RunInfo
    p4: P4Info
    fwer_statement: str
    arms: list[ArmRow]
    families: list[HolmFamily]
    secondary_deltas: list[SecondaryDeltaRow]
    strata: list[StratumRow]
    primary_delta_strata: list[StratumDeltaRow]
    judged_agreement: list[AgreementView]
    judged_deltas: list[JudgedDeltaView]
    judged_delta_strata: list[StratumDeltaRow]
    legacy_lines: list[str]
    divergence_lines: list[str]
    robustness: Robustness
    paper_reference: PaperReference
    lines: list[ComparisonLine]
    disclosures: Disclosures


# ---- pure inference ------------------------------------------------------------------


def coverage_evaluable(n_p4: int, n_g: int, floor: float | None = None) -> bool:
    """Whether `|P4| / |H_G|` reaches the pre-registered complete-case floor.

    The comparison is exact (a `Fraction` against the floor's decimal text), so a
    coverage of exactly 0.80 is evaluable and 0.799 is not (AI-SPEC 5 item 7).

    Args:
        n_p4: The size of P4.
        n_g: The held-out G size, the coverage denominator.
        floor: The floor; the pre-registered 0.80 when None.

    Returns:
        False for an empty P4 or an empty split.
    """
    if n_g <= 0 or n_p4 <= 0:
        return False
    limit = PREREGISTRATION_06_3_5.complete_case_floor if floor is None else floor
    return Fraction(n_p4, n_g) >= Fraction(str(limit))


def _holm_run(
    values: Mapping[str, Mapping[str, float]],
    arms: Sequence[str],
    reference: str,
    alpha: float,
) -> tuple[list[tuple[int, int]], list[float], list[bool], list[float]]:
    counts = [p4_mod.discordant_counts(values[arm], values[reference]) for arm in arms]
    ps = [float(exact_signflip_p(n_pos, n_neg)) for n_pos, n_neg in counts]
    reject, adjusted = holm_stepdown(ps, alpha=alpha)
    return counts, ps, reject, adjusted


def _decision(rejected: bool) -> str:
    return DECISION_SIGNIFICANT if rejected else DECISION_NOT_SIGNIFICANT


def holm_family(
    primary: str,
    values: Mapping[str, Mapping[str, float]],
    *,
    evaluable: bool,
    matching_rule: str | None = None,
    text_values: Mapping[str, Mapping[str, float]] | None = None,
) -> HolmFamily:
    """One pre-registered Holm family over per-question 0/1 values on P4 (D-123).

    The comparisons are the pre-registered arms against the reference arm, in the
    pre-registered order. Each carries the exact two-sided paired sign-flip p over the
    discordant pairs, the Holm step-down adjusted p and decision at the family's FWER,
    and a bootstrap CI of the paired delta labelled estimation only. Only a Holm
    rejection reads `significant`; a CI that excludes 0 without one reads exactly that.

    Args:
        primary: The primary's name.
        values: Arm label to question ID to the 0/1 value, covering the reference arm
            and every comparison arm over the same questions.
        evaluable: Whether the coverage floor is met. When false, every comparison
            reads `not evaluable: coverage` and carries no p-value or interval.
        matching_rule: The matching rule label of the values, if the primary has one.
        text_values: The same map under the official text rule; when given and the
            family is evaluable, Holm is re-run on it and every row reads robust or
            not robust to the matching rule.

    Returns:
        The family.

    Raises:
        ValueError: If an evaluable family has no questions or an arm is missing.
    """
    pre = PREREGISTRATION_06_3_5
    reference = pre.reference_arm
    arms = pre.comparison_arms
    alpha = pre.family_alpha
    rows: list[HolmComparison] = []
    if not evaluable:
        n_pairs = len(values[reference]) if reference in values else 0
        rows = [
            HolmComparison(
                arm=arm,
                reference=reference,
                n_pairs=n_pairs,
                decision=DECISION_NOT_EVALUABLE,
            )
            for arm in arms
        ]
        return HolmFamily(
            primary=primary,
            matching_rule=matching_rule,
            reference=reference,
            alpha=alpha,
            m=len(arms),
            evaluable=False,
            comparisons=rows,
        )
    counts, ps, reject, adjusted = _holm_run(values, arms, reference, alpha)
    text_run = (
        _holm_run(text_values, arms, reference, alpha)
        if text_values is not None
        else None
    )
    for i, arm in enumerate(arms):
        pd = p4_mod.paired_delta(values[arm], values[reference])
        excludes = pd.ci_lower > 0 or pd.ci_upper < 0
        row = HolmComparison(
            arm=arm,
            reference=reference,
            n_pairs=pd.n,
            n_pos=counts[i][0],
            n_neg=counts[i][1],
            raw_p=ps[i],
            adjusted_p=adjusted[i],
            decision=_decision(reject[i]),
            ci_note=CI_EXCLUDES_ZERO_NOTE if excludes and not reject[i] else None,
            delta=pd.delta,
            ci_lo=pd.ci_lower,
            ci_hi=pd.ci_upper,
        )
        if text_run is not None:
            _, text_ps, text_reject, text_adjusted = text_run
            row.text_rule_decision = _decision(text_reject[i])
            row.text_rule_raw_p = text_ps[i]
            row.text_rule_adjusted_p = text_adjusted[i]
            row.robustness = ROBUST if text_reject[i] == reject[i] else NOT_ROBUST
        rows.append(row)
    return HolmFamily(
        primary=primary,
        matching_rule=matching_rule,
        reference=reference,
        alpha=alpha,
        m=len(arms),
        evaluable=True,
        comparisons=rows,
    )


# ---- formatting ----------------------------------------------------------------------


def format_number(value: float | None) -> str:
    """A number at a precision that suits its magnitude (counts of ms, USD, ratios)."""
    if value is None:
        return "n/a"
    magnitude = abs(value)
    if magnitude >= 100:
        return f"{value:.1f}"
    if 0 < magnitude < 0.001:
        return f"{value:.6f}"
    return f"{value:.4f}"


def _cell_size() -> int:
    return COMMITTED_THRESHOLDS.min_stratum_cell_size


def format_stratum_cell(
    value: float | None, ci_lo: float | None, ci_hi: float | None, n: int
) -> str:
    """A D-40 stratum cell: `value [ci_lo, ci_hi] (n)`, or no CI below the cell size."""
    text = "n/a" if value is None else f"{value:.4f}"
    if ci_lo is not None and ci_hi is not None and n >= _cell_size():
        return f"{text} [{ci_lo:.4f}, {ci_hi:.4f}] ({n})"
    return f"{text} (n = {n}; n < {_cell_size()}, no CI)"


def _cell_text(cell: MetricCell) -> str:
    if cell.value is None:
        return f"n/a ({cell.reason or cell.status})"
    text = format_number(cell.value)
    if cell.ci_lo is not None and cell.ci_hi is not None:
        text += f" [{format_number(cell.ci_lo)}, {format_number(cell.ci_hi)}]"
    return f"{text} (n={cell.n})"


# ---- reading `report.json` -----------------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ComparisonError(f"cannot read {path.name}: {exc}") from exc


def _load_report(run: Path) -> CorpusReport:
    path = run / "report.json"
    if not path.is_file():
        raise ComparisonError(
            f"{path} is missing; run `lancet-eval score --judged` first (D-120)"
        )
    try:
        return CorpusReport.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ComparisonError(f"report.json does not validate: {exc}") from exc


def _load_judged(run: Path, corpus: str) -> JudgedResult:
    path = run / "judged-result.json"
    if not path.is_file():
        raise ComparisonError(
            "judged-result.json is missing: `lancet-eval score --judged` has not "
            "passed its ordering gates for this run (D-113, D-120)"
        )
    try:
        result = JudgedResult.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ComparisonError(f"judged-result.json does not validate: {exc}") from exc
    if result.corpus != corpus:
        raise ComparisonError(
            f"judged-result.json is for corpus {result.corpus!r}, but the report is "
            f"for corpus {corpus!r}"
        )
    return result


def _dim_cell(dim: Any) -> MetricCell:
    detail = dim.detail
    return MetricCell(
        value=dim.score,
        ci_lo=detail.get("ci_lower"),
        ci_hi=detail.get("ci_upper"),
        n=int(dim.n),
        status=dim.status,
        reason=dim.reason,
        detail={
            k: float(v)
            for k, v in sorted(detail.items())
            if not k.startswith("type_") and k not in ("ci_lower", "ci_upper")
        },
    )


def _require(dims: Mapping[str, Any], name: str) -> Any:
    if name not in dims:
        raise ComparisonError(
            f"report.json has no dimension {name!r}; it is not a scored four-arm "
            "report (run `lancet-eval score --judged`)"
        )
    return dims[name]


def _check_judged_dimensions(dims: Mapping[str, Any], arms: Sequence[str]) -> None:
    missing = [
        name
        for dimension in JUDGED_DIMENSIONS
        for name in (
            *(f"answer_{dimension}__{arm_slug(arm)}" for arm in arms),
            f"judge_qwk_{dimension}",
        )
        if name not in dims
    ]
    if missing:
        raise ComparisonError(
            "report.json lacks the judged dimensions (" + ", ".join(missing[:6]) + "); "
            "run `lancet-eval score --judged` first (D-120)"
        )


def _secondary_deltas(
    dims: Mapping[str, Any], arms: Sequence[str]
) -> list[SecondaryDeltaRow]:
    known = {*SECONDARY_DELTA_BASES, *JUDGED_DELTA_BASES}
    for name in sorted(dims):
        if "_delta__" in name and name.split("_delta__")[0] + "_delta" not in known:
            raise ComparisonError(
                f"report.json carries the unrecognised delta dimension {name!r}"
            )
    rows: list[SecondaryDeltaRow] = []
    for base in SECONDARY_DELTA_BASES:
        for arm in arms:
            dim = _require(dims, f"{base}__{arm_slug(arm)}")
            detail = dim.detail
            rows.append(
                SecondaryDeltaRow(
                    metric=base.removesuffix("_delta"),
                    arm=arm,
                    delta=dim.score,
                    ci_lo=detail.get("ci_lower"),
                    ci_hi=detail.get("ci_upper"),
                    n_pairs=int(detail.get("n_pairs", dim.n)),
                    mean_arm=detail.get("mean_x"),
                    mean_hybrid=detail.get("mean_hybrid"),
                    reason=dim.reason,
                )
            )
    return rows


def _report_strata(dims: Mapping[str, Any], arms: Sequence[str]) -> list[StratumRow]:
    metrics: list[str] = []
    for name in sorted(dims):
        if "__" not in name or "_delta__" in name:
            continue
        base = name.split("__")[0]
        if base.startswith(("answer_groundedness", "answer_faithfulness")):
            continue
        if f"type_{strata_mod.STRATUM_TYPES[0]}_n" in dims[name].detail:
            if base not in metrics:
                metrics.append(base)
    rows: list[StratumRow] = []
    for metric in metrics:
        for arm in arms:
            dim = dims.get(f"{metric}__{arm_slug(arm)}")
            if dim is None:
                continue
            detail = dim.detail
            for qtype in strata_mod.STRATUM_TYPES:
                baseline = (
                    detail.get(f"type_{qtype}_constant_yes_baseline")
                    if metric in CONSTANT_YES_METRICS
                    else None
                )
                rows.append(
                    StratumRow(
                        metric=metric,
                        arm=arm,
                        question_type=qtype,
                        n=int(detail.get(f"type_{qtype}_n", 0)),
                        value=detail.get(f"type_{qtype}_value"),
                        ci_lo=detail.get(f"type_{qtype}_ci_lower"),
                        ci_hi=detail.get(f"type_{qtype}_ci_upper"),
                        constant_yes_baseline=baseline,
                    )
                )
    return rows


# ---- rebuilding the primaries --------------------------------------------------------


def _ranking_ids(rec: RunRecord) -> list[str]:
    if rec.snapshot is None:
        return []
    return [c.chunk_id for c in rec.snapshot.pre_truncation_ranking]


@dataclass(frozen=True)
class _Primaries:
    """The per-question 0/1 values of both primaries on P4, per canonical arm."""

    pop: p4_mod.P4Population
    hits: dict[str, dict[str, float]]
    usable: dict[str, dict[str, float]]
    qtype_of: dict[str, str]


def _rebuild_primaries(
    run: Path,
    report: CorpusReport,
    dims: Mapping[str, Any],
    gold_chunks_path: Path | str | None,
) -> _Primaries:
    corpus = report.metadata.corpus
    journal = run / "journal.jsonl"
    if not journal.is_file():
        journal = run / "journal.json"
    if not journal.is_file():
        raise ComparisonError(f"no journal file in {run}; P4 cannot be rebuilt")
    records, _ = deduplicate_by_arm(load_records(journal))
    try:
        config = load_corpus_config(corpus)
        gold_map = {q.question_id: q for q in load_sample_questions(corpus)}
    except Exception as exc:
        raise ComparisonError(f"cannot load corpus {corpus!r}: {exc}") from exc
    if config.split_path is None:
        raise ComparisonError(f"corpus {corpus!r} declares no [split]; P4 needs one")
    arm_set = {canonical_arm(a) for a in config.arms}
    pre = PREREGISTRATION_06_3_5
    if arm_set != {pre.reference_arm, *pre.comparison_arms}:
        raise ComparisonError(
            f"corpus {corpus!r} runs arms {sorted(arm_set)}, not the pre-registered "
            f"{sorted({pre.reference_arm, *pre.comparison_arms})}"
        )
    try:
        split = load_split(config.split_path)
    except (OSError, ValueError) as exc:
        raise ComparisonError(f"cannot load the held-out split: {exc}") from exc
    gold_path = (
        Path(gold_chunks_path)
        if gold_chunks_path is not None
        else _default_gold_chunks_path()
    )
    if not gold_path.is_file():
        raise ComparisonError(f"gold-chunk table not found at {gold_path} (D-102)")
    try:
        gold_sets = load_gold_chunk_sets(gold_path)
    except (OSError, ValueError, KeyError) as exc:
        raise ComparisonError(f"cannot read the gold-chunk table: {exc}") from exc
    problems = []
    for qid in split.heldout_g_ids:
        gold = gold_map.get(qid)
        if gold is None or gold.is_null:
            problems.append(f"{qid}: not a held-out G question of the corpus")
        elif gold.question_type not in strata_mod.STRATUM_TYPES:
            problems.append(f"{qid}: question_type {gold.question_type!r}")
        elif not gold_sets.get(qid):
            problems.append(f"{qid}: no gold-chunk row")
    if problems:
        raise ComparisonError(
            f"{len(problems)} held-out G question(s) cannot be scored: "
            + "; ".join(problems[:10])
        )
    try:
        pop = p4_mod.build_p4(records, split, config.arms)
    except ValueError as exc:
        raise ComparisonError(f"cannot build P4: {exc}") from exc
    hits: dict[str, dict[str, float]] = {}
    usable: dict[str, dict[str, float]] = {}
    for arm in pop.arms:
        hits[arm] = p4_mod.per_question_values(
            records,
            pop,
            arm,
            lambda rec: float(
                paper_question_scores(
                    _ranking_ids(rec), gold_sets[rec.question_id], id_matcher
                )["hit4"]
            ),
        )
        usable[arm] = p4_mod.per_question_values(
            records,
            pop,
            arm,
            lambda rec: (
                1.0
                if compute_answer_usable(gold_map[rec.question_id], rec.answer or "")
                else 0.0
            ),
        )
    size = _require(dims, "p4_size")
    if int(round(size.score or 0)) != len(pop.question_ids):
        raise ComparisonError(
            f"p4_size in report.json is {size.score}, but the journal gives a P4 of "
            f"{len(pop.question_ids)} questions; report.json and the journal disagree"
        )
    for metric, by_arm in (
        ("paper_hits_at_4", hits),
        ("answer_usable_p4", usable),
    ):
        for arm in pop.arms:
            name = f"{metric}__{arm_slug(arm)}"
            dim = _require(dims, name)
            mean = sum(by_arm[arm].values()) / len(by_arm[arm]) if by_arm[arm] else None
            if (
                dim.score is None
                or mean is None
                or not math.isclose(dim.score, mean, abs_tol=1e-9)
                or int(dim.n) != len(by_arm[arm])
            ):
                raise ComparisonError(
                    f"{name} in report.json ({dim.score}, n={dim.n}) disagrees with "
                    f"the journal ({mean}, n={len(by_arm[arm])}); refusing to compare "
                    "two sources that drifted apart"
                )
    qtype_of = {q: str(gold_map[q].question_type) for q in split.heldout_g_ids}
    return _Primaries(pop, hits, usable, qtype_of)


def _primary_delta_strata(prim: _Primaries) -> list[StratumDeltaRow]:
    pre = PREREGISTRATION_06_3_5
    rows: list[StratumDeltaRow] = []
    for primary, values in (
        ("paper_hits_at_4", prim.hits),
        ("answer_usable", prim.usable),
    ):
        for arm in pre.comparison_arms:
            keyed = strata_mod.paired_delta_strata(
                values[arm], values[pre.reference_arm], prim.qtype_of
            )
            for qtype in strata_mod.STRATUM_TYPES:
                lo = keyed.get(f"type_{qtype}_ci_lower")
                hi = keyed.get(f"type_{qtype}_ci_upper")
                rows.append(
                    StratumDeltaRow(
                        metric=primary,
                        arm=arm,
                        reference=pre.reference_arm,
                        question_type=qtype,
                        n_pairs=int(keyed.get(f"type_{qtype}_n_pairs", 0)),
                        delta=keyed.get(f"type_{qtype}_delta"),
                        ci_lo=lo,
                        ci_hi=hi,
                        ci_label=LABEL_UNADJUSTED if lo is not None else None,
                    )
                )
    return rows


# ---- the judged half (read from judged-result.json) ----------------------------------


def _agreement_views(judged: JudgedResult) -> list[AgreementView]:
    views = []
    for dimension in JUDGED_DIMENSIONS:
        d = judged.agreement["dimensions"][dimension]
        views.append(
            AgreementView(
                dimension=dimension,
                n_pairs=int(d["n_pairs"]),
                qwk=d["qwk"],
                qwk_ci_lo=d["qwk_ci_lower"],
                qwk_ci_hi=d["qwk_ci_upper"],
                floor=float(d["floor"]),
                label=str(d["label"]),
                spearman=d["spearman"],
                exact_agreement=d["exact_agreement"],
            )
        )
    return views


def _judged_cells(
    judged: JudgedResult, agreement: Sequence[AgreementView]
) -> dict[str, dict[str, JudgedCell]]:
    by_dim = {a.dimension: a for a in agreement}
    out: dict[str, dict[str, JudgedCell]] = {}
    for row in judged.arms:
        a = by_dim[row.dimension]
        out.setdefault(row.arm, {})[row.dimension] = JudgedCell(
            dimension=row.dimension,
            n=row.n,
            mean=row.mean,
            ci_lo=row.ci_lower,
            ci_hi=row.ci_upper,
            judge_errors=row.judge_errors,
            abstention_rate=row.abstention_rate,
            abstention_n=row.abstention_n,
            d114_label=row.d114_label,
            qwk=a.qwk,
            qwk_ci_lo=a.qwk_ci_lo,
            qwk_ci_hi=a.qwk_ci_hi,
            qwk_n_pairs=a.n_pairs,
        )
    return out


def _judged_strata(judged: JudgedResult) -> list[StratumRow]:
    rows = []
    for row in judged.arms:
        for s in row.strata:
            rows.append(
                StratumRow(
                    metric=f"answer_{row.dimension}",
                    arm=row.arm,
                    question_type=s.question_type,
                    n=s.n,
                    value=s.mean,
                    ci_lo=s.ci_lower,
                    ci_hi=s.ci_upper,
                    abstention_rate=s.abstention_rate,
                    abstention_n=s.abstention_n,
                )
            )
    return rows


def _judged_deltas(
    judged: JudgedResult,
) -> tuple[list[JudgedDeltaView], list[StratumDeltaRow]]:
    views: list[JudgedDeltaView] = []
    strata_rows: list[StratumDeltaRow] = []
    for d in judged.deltas:
        views.append(
            JudgedDeltaView(
                arm=d.arm,
                reference=d.reference,
                dimension=d.dimension,
                n_pairs=d.n_pairs,
                delta=d.delta,
                ci_lo=d.ci_lower,
                ci_hi=d.ci_upper,
                dropped_only_arm_abstained=d.dropped_only_arm_abstained,
                dropped_only_reference_abstained=d.dropped_only_reference_abstained,
                dropped_both_abstained=d.dropped_both_abstained,
                dropped_judge_unavailable=d.dropped_judge_unavailable,
                judge_errors_arm=d.judge_errors_arm,
                judge_errors_reference=d.judge_errors_reference,
                abstention_rate_arm=d.abstention_rate_arm,
                abstention_rate_reference=d.abstention_rate_reference,
                abstention_n=d.abstention_n,
                abstention_rate_delta=d.abstention_rate_delta,
                abstention_rate_delta_ci_lo=d.abstention_rate_delta_ci_lower,
                abstention_rate_delta_ci_hi=d.abstention_rate_delta_ci_upper,
                flag=d.flag,
                d114_label=d.d114_label,
            )
        )
        for s in d.strata:
            strata_rows.append(
                StratumDeltaRow(
                    metric=f"answer_{d.dimension}",
                    arm=d.arm,
                    reference=d.reference,
                    question_type=s.question_type,
                    n_pairs=s.n_pairs,
                    delta=s.delta,
                    ci_lo=s.ci_lower,
                    ci_hi=s.ci_upper,
                    ci_label=LABEL_UNADJUSTED if s.ci_lower is not None else None,
                    abstention_rate_arm=s.abstention_rate_arm,
                    abstention_rate_reference=s.abstention_rate_reference,
                    abstention_n=s.abstention_n,
                )
            )
    return views, strata_rows


# ---- the optional sidecars -----------------------------------------------------------


def _load_crosscheck(
    run: Path, report: CorpusReport, prim: _Primaries
) -> tuple[dict[str, Any] | None, dict[str, dict[str, float]] | None]:
    path = run / "diagnostic" / "text_crosscheck.json"
    if not path.is_file():
        return None, None
    data = _read_json(path)
    try:
        generation = str(data["index_generation"])
        p4_ids = list(data["p4_question_ids"])
        text_hit4 = data["per_arm_text_hit4_p4"]
        arms = data["arms"]
    except (KeyError, TypeError) as exc:
        raise ComparisonError(f"text_crosscheck.json lacks {exc}") from exc
    if generation != report.metadata.index_generation:
        raise ComparisonError(
            f"text_crosscheck.json was built at index_generation {generation!r}, "
            f"but this run's is {report.metadata.index_generation!r}; the cross-check "
            "is stale"
        )
    if sorted(p4_ids) != sorted(prim.pop.question_ids):
        raise ComparisonError(
            "text_crosscheck.json is stale: its P4 differs from this run's P4 "
            f"({len(p4_ids)} against {len(prim.pop.question_ids)} questions); rerun "
            "the cross-check on this journal"
        )
    values: dict[str, dict[str, float]] = {}
    for arm in prim.pop.arms:
        if arm not in text_hit4 or arm not in arms:
            raise ComparisonError(f"text_crosscheck.json has no entry for arm {arm!r}")
        by_q = text_hit4[arm]
        if set(by_q) != set(prim.pop.question_ids):
            raise ComparisonError(
                f"text_crosscheck.json covers other questions than P4 for arm {arm!r}"
            )
        values[arm] = {q: float(by_q[q]) for q in prim.pop.question_ids}
    return data, values


def _robustness(data: dict[str, Any] | None, arms: Sequence[str]) -> Robustness:
    if data is None:
        return Robustness(ran=False, paper_rows_label=APPROXIMATION_LABEL)
    per_arm = []
    for arm in arms:
        p4 = data["arms"][arm]["p4"]
        per_arm.append(
            ArmDisagreement(
                arm=arm,
                n=int(p4["n"]),
                disagree_hit4=int(p4["disagree_hit4"]),
                disagree_hit10=int(p4["disagree_hit10"]),
                disagree_first_hit_rank=int(p4["disagree_first_hit_rank"]),
                disagree_ap=int(p4["disagree_ap"]),
            )
        )
    return Robustness(
        ran=True,
        paper_rows_label=None,
        index_generation=str(data["index_generation"]),
        official_commit=str(data.get("official_commit")),
        per_arm=per_arm,
    )


def _load_disclosures(run: Path) -> Disclosures:
    gates: list[GateReading] = []
    for candidate in (
        run / "gates-heldout.json",
        run / "diagnostic" / "gates-heldout.json",
    ):
        if candidate.is_file():
            payload = _read_json(candidate)
            for gate, by_arm in payload.items():
                if not isinstance(by_arm, dict):
                    continue
                for arm, reading in by_arm.items():
                    if isinstance(reading, dict) and "status" in reading:
                        gates.append(
                            GateReading(
                                gate=str(gate),
                                arm=str(arm),
                                status=str(reading["status"]),
                            )
                        )
            break
    providers: list[ProviderRow] = []
    unmatched: int | None = None
    summary = run / "diagnostic" / "provider_format_map-summary.json"
    if summary.is_file():
        data = _read_json(summary)
        for arm, by_provider in sorted(data.get("by_arm_provider", {}).items()):
            for provider, count in sorted(by_provider.items()):
                providers.append(
                    ProviderRow(
                        arm=str(arm), provider=str(provider), records=int(count)
                    )
                )
        if "unmatched_count" in data:
            unmatched = int(data["unmatched_count"])
    return Disclosures(
        d124=D124_DISCLOSURE,
        gates=gates,
        providers=providers,
        provider_unmatched=unmatched,
    )


# ---- assembling ----------------------------------------------------------------------


def _paper_reference(
    arms: Sequence[str],
    cells: Mapping[str, Mapping[str, MetricCell]],
    robustness: Robustness,
    crosscheck: dict[str, Any] | None,
    n_g: int,
    embedding_model: str,
) -> PaperReference:
    caveat = [
        s.format(n_g=n_g, embedding_model=embedding_model)
        for s in NON_COMPARABILITY_CAVEAT
    ]
    description = (
        f"the script-faithful line (all {n_g} held-out G questions per arm; a record "
        f"without a valid ranking scored as a miss; denominator {n_g})"
    )
    if crosscheck is not None:
        rule = "official text rule (cross-check ran)"
        comparable = (
            f"The comparable lancet line is {description}, under the official text "
            "rule because the cross-check ran (D-122). It stays G-restricted, while "
            "the paper averages over all non-null queries."
        )
        line = []
        for arm in arms:
            sf = crosscheck["arms"][arm]["script_faithful"]
            text_rule = sf.get("text_rule") or {}
            line.append(
                LineRow(
                    arm=arm,
                    value=text_rule.get("paper_hits_at_4"),
                    n=int(sf.get("n", 0)),
                )
            )
    else:
        rule = f"{ID_RULE_LABEL}; {APPROXIMATION_LABEL}"
        comparable = (
            f"The comparable lancet line is {description}, under the ID rule, "
            f"labelled {APPROXIMATION_LABEL} (D-122). It stays G-restricted, while "
            "the paper averages over all non-null queries."
        )
        line = []
        for arm in arms:
            c = cells[arm]["paper_hits_at_4_script_faithful"]
            line.append(
                LineRow(arm=arm, value=c.value, ci_lo=c.ci_lo, ci_hi=c.ci_hi, n=c.n)
            )
    return PaperReference(
        label=PAPER_ROW_LABEL,
        citation=PAPER_REFERENCE_TABLE5["citation"],
        caption=PAPER_REFERENCE_TABLE5["caption"],
        configuration=PAPER_REFERENCE_TABLE5["configuration"],
        rows=[PaperRow(**row) for row in PAPER_REFERENCE_TABLE5["rows"]],
        caveat=caveat,
        comparable_line=comparable,
        lancet_line_rule=rule,
        lancet_line=line,
    )


def _comparison_lines(
    arms: Sequence[str], cells: Mapping[str, Mapping[str, MetricCell]], n_g: int
) -> list[ComparisonLine]:
    def rows(metric: str) -> list[LineRow]:
        return [
            LineRow(
                arm=arm,
                value=cells[arm][metric].value,
                ci_lo=cells[arm][metric].ci_lo,
                ci_hi=cells[arm][metric].ci_hi,
                n=cells[arm][metric].n,
            )
            for arm in arms
        ]

    return [
        ComparisonLine(
            code="D-121",
            title="answer_usable, 06.3.4.1 SC-3 definition (comparison line)",
            text=(
                "The 06.3.4.1 SC-3 definition on per-arm usable records with the "
                "inherited exclusions. It bridges to drive 2's figure, but the P4 "
                "primary (answer_usable on P4, where a blank answer scores 0) is not "
                "directly comparable to drive 2's 0.58. This line decides nothing."
            ),
            rows=rows("answer_usable_sc3_definition"),
        ),
        ComparisonLine(
            code="D-122",
            title="Script-faithful paper line (all held-out G questions)",
            text=(
                f"Paper-convention Hits@4 over all {n_g} held-out G questions per arm "
                f"(denominator {n_g}); a record without a valid ranking scores as a "
                "miss. It is a labelled sensitivity line and decides nothing."
            ),
            rows=rows("paper_hits_at_4_script_faithful"),
        ),
    ]


def build_comparison(
    run_dir: Path | str, *, gold_chunks_path: Path | str | None = None
) -> Comparison:
    """Builds the four-arm comparison of a scored, judged run directory.

    Reads `report.json`, `judged-result.json` and the journal, and the optional
    `diagnostic/text_crosscheck.json`, `gates-heldout.json` and
    `diagnostic/provider_format_map-summary.json`. It writes nothing, never opens the
    judge cache and never calls the judge.

    Args:
        run_dir: A run directory that `score --judged` has passed.
        gold_chunks_path: The gold-chunk table; the committed post-reconcile table when
            None (the same default `score` uses).

    Returns:
        The validated comparison.

    Raises:
        ComparisonError: If an input is missing, stale or inconsistent with another.
    """
    run = Path(run_dir)
    report = _load_report(run)
    corpus = report.metadata.corpus
    judged = _load_judged(run, corpus)
    dims = {d.name: d for d in report.dimensions}
    pre = PREREGISTRATION_06_3_5
    arms = [a for a in ARM_REGISTRY if a in {pre.reference_arm, *pre.comparison_arms}]
    _check_judged_dimensions(dims, arms)
    prim = _rebuild_primaries(run, report, dims, gold_chunks_path)
    n_p4 = len(prim.pop.question_ids)
    n_g = prim.pop.n_heldout_g
    evaluable = coverage_evaluable(n_p4, n_g)

    crosscheck, text_hit4 = _load_crosscheck(run, report, prim)
    families = [
        holm_family(
            "paper_hits_at_4",
            prim.hits,
            evaluable=evaluable,
            matching_rule=ID_RULE_LABEL,
            text_values=text_hit4,
        ),
        holm_family("answer_usable", prim.usable, evaluable=evaluable),
    ]
    cells = {
        arm: {
            metric: _dim_cell(_require(dims, f"{metric}__{arm_slug(arm)}"))
            for metric in TABLE_METRICS
        }
        for arm in arms
    }
    agreement = _agreement_views(judged)
    judged_cells = _judged_cells(judged, agreement)
    arm_rows = [
        ArmRow(
            arm=arm,
            slug=arm_slug(arm),
            cells=cells[arm],
            judged=judged_cells.get(arm, {}),
        )
        for arm in arms
    ]
    judged_deltas, judged_delta_strata = _judged_deltas(judged)
    robustness = _robustness(crosscheck, arms)
    size = dims["p4_size"]
    excluded = {
        arm: ArmExclusionView(
            own_failure=prim.pop.excluded[arm].own_failure,
            provenance=prim.pop.excluded[arm].provenance,
            other_arm_failure=prim.pop.excluded[arm].other_arm_failure,
            pairwise_join_size=prim.pop.pairwise_join_sizes.get(arm),
        )
        for arm in arms
    }
    return Comparison(
        run=RunInfo(
            run=run.resolve().name,
            corpus=corpus,
            run_date=report.metadata.run_date,
            commit_sha=report.metadata.commit_sha,
            index_generation=report.metadata.index_generation,
            judge_model=report.metadata.judge_model,
            judge_prompt_version=report.metadata.judge_prompt_version,
            embedding_model=report.metadata.embedding_model,
            arms=arms,
            reference_arm=pre.reference_arm,
        ),
        p4=P4Info(
            n_p4=n_p4,
            n_heldout_g=n_g,
            n_heldout_null=int(size.detail.get("n_heldout_null", 0)),
            coverage=prim.pop.coverage,
            floor=pre.complete_case_floor,
            evaluable=evaluable,
            excluded=excluded,
        ),
        fwer_statement=FWER_STATEMENT,
        arms=arm_rows,
        families=families,
        secondary_deltas=_secondary_deltas(dims, pre.comparison_arms),
        strata=[*_report_strata(dims, arms), *_judged_strata(judged)],
        primary_delta_strata=_primary_delta_strata(prim),
        judged_agreement=agreement,
        judged_deltas=judged_deltas,
        judged_delta_strata=judged_delta_strata,
        legacy_lines=list(judged.legacy_lines),
        divergence_lines=list(judged.divergence_lines),
        robustness=robustness,
        paper_reference=_paper_reference(
            arms, cells, robustness, crosscheck, n_g, report.metadata.embedding_model
        ),
        lines=_comparison_lines(arms, cells, n_g),
        disclosures=_load_disclosures(run),
    )


# ---- rendering -----------------------------------------------------------------------


def _row(*cols: object) -> str:
    return "| " + " | ".join(str(c) for c in cols) + " |"


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    out = [_row(*header), _row(*["---"] * len(header))]
    out.extend(_row(*r) for r in rows)
    return out


def _p(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _ci(lo: float | None, hi: float | None) -> str:
    if lo is None or hi is None:
        return "no CI"
    return f"[{format_number(lo)}, {format_number(hi)}]"


def _family_view(fam: HolmFamily, ran_crosscheck: bool) -> dict[str, Any]:
    header = [
        "comparison",
        "n pairs",
        "discordant (+/-)",
        "raw p (exact)",
        "Holm-adjusted p",
        "decision",
        "delta",
        f"95% CI ({LABEL_UNADJUSTED})",
        "note",
    ]
    if ran_crosscheck and fam.matching_rule is not None:
        header += ["text-rule decision", "matching-rule robustness"]
    rows = []
    for c in fam.comparisons:
        discordant = "n/a" if c.n_pos is None else f"{c.n_pos}/{c.n_neg}"
        row: list[object] = [
            f"{c.arm} - {c.reference}",
            c.n_pairs,
            discordant,
            _p(c.raw_p),
            _p(c.adjusted_p),
            c.decision,
            format_number(c.delta),
            _ci(c.ci_lo, c.ci_hi),
            c.ci_note or "",
        ]
        if ran_crosscheck and fam.matching_rule is not None:
            row += [c.text_rule_decision or "n/a", c.robustness or "n/a"]
        rows.append(row)
    title = f"`{fam.primary}`" + (
        f" ({fam.matching_rule})" if fam.matching_rule else " (on P4)"
    )
    return {"title": title, "table": _table(header, rows), "evaluable": fam.evaluable}


def _arm_table(
    comp: Comparison, metrics: Sequence[str], *, label: str | None = None
) -> list[str]:
    header = ["metric", *[a.arm for a in comp.arms]]
    if label is not None:
        header.append("label")
    rows = []
    for metric in metrics:
        row: list[object] = [f"`{metric}`"]
        row += [_cell_text(a.cells[metric]) for a in comp.arms]
        if label is not None:
            row.append(label)
        rows.append(row)
    return _table(header, rows)


def _paper_table(comp: Comparison) -> list[str]:
    label = comp.robustness.paper_rows_label
    header = ["row", "Hits@4", "Hits@10", "MRR@10", "MAP@10", "label"]
    out = []
    for arm in comp.arms:
        c = arm.cells
        out.append(
            [
                f"{arm.arm} (P4)",
                _cell_text(c["paper_hits_at_4"]),
                _cell_text(c["paper_hits_at_10"]),
                _cell_text(c["paper_mrr_at_10"]),
                _cell_text(c["paper_map_at_10"]),
                label or ID_RULE_LABEL,
            ]
        )
    for arm in comp.arms:
        c = arm.cells
        out.append(
            [
                f"{arm.arm} (script-faithful, all {comp.p4.n_heldout_g} G)",
                _cell_text(c["paper_hits_at_4_script_faithful"]),
                _cell_text(c["paper_hits_at_10_script_faithful"]),
                _cell_text(c["paper_mrr_at_10_script_faithful"]),
                _cell_text(c["paper_map_at_10_script_faithful"]),
                label or ID_RULE_LABEL,
            ]
        )
    for ref in comp.paper_reference.rows:
        out.append(
            [
                f"{comp.paper_reference.label}: {ref.embedding}",
                ref.hits_at_4,
                ref.hits_at_10,
                ref.mrr_at_10,
                ref.map_at_10,
                comp.paper_reference.citation,
            ]
        )
    return _table(header, out)


def _judged_tables(comp: Comparison) -> dict[str, list[str]]:
    agreement = _table(
        [
            "dimension",
            "scored pairs",
            "QWK",
            "QWK 95% CI",
            "floor",
            "D-114 label",
            "Spearman",
            "exact agreement",
        ],
        [
            [
                a.dimension,
                a.n_pairs,
                _p(a.qwk),
                _ci(a.qwk_ci_lo, a.qwk_ci_hi),
                _p(a.floor),
                a.label,
                _p(a.spearman),
                _p(a.exact_agreement),
            ]
            for a in comp.judged_agreement
        ],
    )
    per_arm = []
    for arm in comp.arms:
        for dimension in JUDGED_DIMENSIONS:
            j = arm.judged.get(dimension)
            if j is None:
                continue
            per_arm.append(
                [
                    arm.arm,
                    dimension,
                    _cell_text(
                        MetricCell(value=j.mean, ci_lo=j.ci_lo, ci_hi=j.ci_hi, n=j.n)
                    ),
                    j.judge_errors,
                    f"{_p(j.abstention_rate)} (n={j.abstention_n})",
                    f"{j.d114_label} (QWK {_p(j.qwk)}, 95% CI "
                    f"{_ci(j.qwk_ci_lo, j.qwk_ci_hi)}, n={j.qwk_n_pairs})",
                ]
            )
    arms_table = _table(
        [
            "arm",
            "dimension",
            "mean over J_a (95% CI)",
            "judge errors",
            "abstention rate (n)",
            "D-114 label",
        ],
        per_arm,
    )
    deltas = _table(
        [
            "comparison",
            "dimension",
            f"delta (95% CI, {LABEL_UNADJUSTED})",
            "n pairs",
            "dropped: only arm / only hybrid / both / judge unavailable",
            "judge errors arm / hybrid",
            "abstention rate arm (n) / hybrid (n)",
            "abstention delta (95% CI)",
            "flag",
            "D-114 label",
        ],
        [
            [
                f"{d.arm} - {d.reference}",
                d.dimension,
                f"{format_number(d.delta)} {_ci(d.ci_lo, d.ci_hi)}",
                d.n_pairs,
                f"{d.dropped_only_arm_abstained} / "
                f"{d.dropped_only_reference_abstained} / {d.dropped_both_abstained} / "
                f"{d.dropped_judge_unavailable}",
                f"{d.judge_errors_arm} / {d.judge_errors_reference}",
                f"{_p(d.abstention_rate_arm)} (n={d.abstention_n}) / "
                f"{_p(d.abstention_rate_reference)} (n={d.abstention_n})",
                f"{format_number(d.abstention_rate_delta)} "
                f"{_ci(d.abstention_rate_delta_ci_lo, d.abstention_rate_delta_ci_hi)}",
                d.flag or "",
                d.d114_label,
            ]
            for d in comp.judged_deltas
        ],
    )
    return {"agreement": agreement, "arms": arms_table, "deltas": deltas}


def _secondary_table(comp: Comparison) -> list[str]:
    return _table(
        [
            "metric",
            "arm - hybrid",
            "delta",
            "95% CI",
            "n_pairs",
            "mean (arm)",
            "mean (hybrid)",
            "label",
        ],
        [
            [
                f"`{r.metric}`",
                f"{r.arm} - {comp.run.reference_arm}",
                format_number(r.delta),
                _ci(r.ci_lo, r.ci_hi),
                r.n_pairs,
                format_number(r.mean_arm),
                format_number(r.mean_hybrid),
                r.label,
            ]
            for r in comp.secondary_deltas
        ],
    )


def _strata_tables(comp: Comparison) -> list[dict[str, Any]]:
    metrics: list[str] = []
    for r in comp.strata:
        if r.metric not in metrics:
            metrics.append(r.metric)
    out = []
    for metric in metrics:
        rows = []
        for arm in comp.run.arms:
            row: list[object] = [arm]
            for qtype in strata_mod.STRATUM_TYPES:
                r = next(
                    s
                    for s in comp.strata
                    if s.metric == metric and s.arm == arm and s.question_type == qtype
                )
                text = format_stratum_cell(r.value, r.ci_lo, r.ci_hi, r.n)
                if r.constant_yes_baseline is not None:
                    text += f"; constant-Yes {r.constant_yes_baseline:.4f}"
                if r.abstention_n is not None:
                    text += (
                        f"; abstention {_p(r.abstention_rate)} (n = {r.abstention_n})"
                    )
                row.append(text)
            rows.append(row)
        out.append(
            {
                "metric": metric,
                "table": _table(["arm", *strata_mod.STRATUM_TYPES], rows),
            }
        )
    return out


def _delta_strata_tables(
    rows: Sequence[StratumDeltaRow], arms: Sequence[str]
) -> list[dict[str, Any]]:
    metrics: list[str] = []
    for r in rows:
        if r.metric not in metrics:
            metrics.append(r.metric)
    out = []
    for metric in metrics:
        table_rows = []
        for arm in arms:
            cells: list[object] = [f"{arm} - hybrid"]
            for qtype in strata_mod.STRATUM_TYPES:
                match = [
                    r
                    for r in rows
                    if r.metric == metric and r.arm == arm and r.question_type == qtype
                ]
                if not match:
                    cells.append("n/a")
                    continue
                r = match[0]
                text = format_stratum_cell(
                    r.delta, r.ci_lo, r.ci_hi, r.n_pairs
                ).replace(f"(n = {r.n_pairs};", f"(n_pairs = {r.n_pairs};")
                if r.ci_label is not None:
                    text += f" {r.ci_label}"
                cells.append(text)
            table_rows.append(cells)
        out.append(
            {
                "metric": metric,
                "table": _table(["comparison", *strata_mod.STRATUM_TYPES], table_rows),
            }
        )
    return out


def _line_cell(row: LineRow) -> str:
    return _cell_text(
        MetricCell(value=row.value, ci_lo=row.ci_lo, ci_hi=row.ci_hi, n=row.n)
    )


def render_markdown(comp: Comparison) -> str:
    """Renders `comparison.md` through `templates/comparison.md.j2`."""
    view: dict[str, Any] = {
        "families": [
            _family_view(f, comp.robustness.ran) for f in comp.families
        ],
        "paper_table": _paper_table(comp),
        "answer_table": _arm_table(comp, ANSWER_METRICS),
        "legacy_table": _arm_table(comp, LEGACY_RETRIEVAL_METRICS),
        "abstention_table": _arm_table(comp, ABSTENTION_METRICS),
        "latency_table": _arm_table(comp, LATENCY_COST_METRICS),
        "judged": _judged_tables(comp),
        "secondary_table": _secondary_table(comp),
        "strata": _strata_tables(comp),
        "primary_delta_strata": _delta_strata_tables(
            comp.primary_delta_strata, PREREGISTRATION_06_3_5.comparison_arms
        ),
        "judged_delta_strata": _delta_strata_tables(
            comp.judged_delta_strata, PREREGISTRATION_06_3_5.comparison_arms
        ),
        "exclusion_table": _table(
            [
                "arm",
                "own failure",
                "provenance",
                "other arm's failure",
                "pairwise join",
            ],
            [
                [
                    arm,
                    e.own_failure,
                    e.provenance,
                    e.other_arm_failure,
                    "-" if e.pairwise_join_size is None else e.pairwise_join_size,
                ]
                for arm, e in comp.p4.excluded.items()
            ],
        ),
        "robustness_table": _table(
            [
                "arm",
                "P4 n",
                "hit@4 differs",
                "hit@10 differs",
                "first-hit rank differs",
                "AP differs",
            ],
            [
                [
                    r.arm,
                    r.n,
                    r.disagree_hit4,
                    r.disagree_hit10,
                    r.disagree_first_hit_rank,
                    r.disagree_ap,
                ]
                for r in comp.robustness.per_arm
            ],
        ),
        "paper_line_table": _table(
            ["arm", "Hits@4 (lancet comparable line)", "n"],
            [
                [r.arm, _line_cell(r), r.n]
                for r in comp.paper_reference.lancet_line
            ],
        ),
        "line_tables": [
            _table(
                ["arm", "value (95% CI)", "n"],
                [
                    [r.arm, _line_cell(r), r.n]
                    for r in line.rows
                ],
            )
            for line in comp.lines
        ],
        "gate_table": _table(
            ["gate", "arm", "status"],
            [[g.gate, g.arm, g.status] for g in comp.disclosures.gates],
        ),
        "provider_table": _table(
            ["arm", "provider", "records"],
            [[p.arm, p.provider, p.records] for p in comp.disclosures.providers],
        ),
        "coverage_pct": f"{comp.p4.coverage:.4f}",
        "cell_size": _cell_size(),
        "unadjusted": LABEL_UNADJUSTED,
        "not_evaluable_note": COVERAGE_NOT_EVALUABLE_NOTE,
    }
    template_dir = Path(__file__).resolve().parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir, encoding="utf-8"),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("comparison.md.j2").render(c=comp, v=view)


def _dump_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _write_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write_comparison(
    run_dir: Path | str, *, gold_chunks_path: Path | str | None = None
) -> Comparison:
    """Builds the comparison and writes `comparison.json` and `comparison.md`.

    Everything is built in memory before anything is written, so a refusal leaves no
    partial sidecar. `report.json` and `report.schema.json` are never touched.

    Args:
        run_dir: A run directory that `score --judged` has passed.
        gold_chunks_path: See `build_comparison`.

    Returns:
        The comparison that was written.

    Raises:
        ComparisonError: If the comparison cannot be built.
    """
    run = Path(run_dir)
    comparison = build_comparison(run, gold_chunks_path=gold_chunks_path)
    comparison_json = _dump_json(comparison.model_dump(mode="json"))
    comparison_md = render_markdown(comparison)
    _write_text(run / "comparison.json", comparison_json)
    _write_text(run / "comparison.md", comparison_md)
    return comparison


def build_chart_data(comparison: Comparison) -> dict[str, Any]:
    """RED stub."""
    raise NotImplementedError


def render_chart_svg(chart_data: Mapping[str, Any]) -> str:
    """RED stub."""
    raise NotImplementedError
