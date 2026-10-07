"""Tests for the ordered judged pass of `score_run` (06.3.5-12; D-97, D-112, D-113,
D-118, D-120, D-126, D-40).

A tmp `[split]` corpus declaring `[judge] protocol = "ordered"` (12 comparison, 10
inference and 4 temporal G questions, plus 2 null questions) is driven on all four arms
inside a throwaway git repository. The real judge stage runs against a fake judge, the
real emit draws the slice, and the D-120 sequence (emit commit, owner scores, reveal) is
committed in git, so `score --judged` reads genuine ordering evidence. No test makes a
network call.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any

import httpx
import pytest
from test_calibration import (
    THRESHOLDS_REL,
    THRESHOLDS_TEXT,
    Flow,
    _git,
    verdict_for,
)
from typer.testing import CliRunner

from lancet_eval import calibration, judge, judge_stage
from lancet_eval import score as score_mod
from lancet_eval.arms import ARM_REGISTRY, arm_slug
from lancet_eval.cli import app
from lancet_eval.client import (
    Notice,
    RankedCandidate,
    RetrievalSnapshot,
    StructuredCitation,
)
from lancet_eval.journal import Journal, NodeTiming, RunRecord, WorkflowWireMeta
from lancet_eval.judge import JudgeCache, cache_key, truncate_evidence
from lancet_eval.report import CorpusReport
from lancet_eval.score import (
    ABSTENTION_DIFFERS_FLAG,
    JudgedResult,
    ScoreError,
    score_run,
)

CORPUS = "ordered_judged"
LEGACY_CORPUS = "ordered_judged_legacy"
MODEL = "meta-llama/llama-3.3-70b-instruct"
ARMS = ("dense-only", "bm25-only", "hybrid", "hybrid+graph")
ABLATION = Notice(code="GRAPH_ABLATION", message="", typed_code=18)
NL = chr(10)
HEX = "0" * 64
CMP = "comparison_query"
INF = "inference_query"
TMP = "temporal_query"

CMP_IDS = [f"oj-c{i:02d}" for i in range(12)]
INF_IDS = [f"oj-i{i:02d}" for i in range(10)]
TMP_IDS = [f"oj-t{i:02d}" for i in range(4)]
G_IDS = CMP_IDS + INF_IDS + TMP_IDS
NULL_IDS = ["oj-n1", "oj-n2"]
QTYPE = {**dict.fromkeys(CMP_IDS, CMP), **dict.fromkeys(INF_IDS, INF)}
QTYPE.update(dict.fromkeys(TMP_IDS, TMP))

# Questions each arm abstains on (final line "Answer: Insufficient information").
ABSTAIN: dict[str, set[str]] = {
    "dense-only": set(),
    "bm25-only": {*CMP_IDS[:8], "oj-t00"},
    "hybrid": {"oj-i00", "oj-t00"},
    "hybrid+graph": {"oj-i01"},
}
# The one record whose judge call fails on both attempts: its cache entry is an error.
ERRORED = ("bm25-only", "oj-i05")
ARM_WORD = {
    "dense-only": "alpha",
    "bm25-only": "bravo",
    "hybrid": "charlie",
    "hybrid+graph": "echo",
}


def _doc_id() -> str:
    from lancet_eval.seed import load_document_map

    return next(iter(load_document_map("multihop_rag").entries))


def _tag(qid: str) -> str:
    return hashlib.sha256(qid.encode("utf-8")).hexdigest()[:10]


def make_record(arm: str, qid: str) -> RunRecord:
    """A well-formed, provenance-clean record of a canonical arm."""
    spec = ARM_REGISTRY[arm]
    doc = _doc_id()
    mode = spec.retrieval_mode
    ids = [f"{qid}:a", f"{qid}:b"] + [
        f"{qid}:{arm_slug(arm)}:f{p}" for p in range(3, 13)
    ]
    ranking = [
        RankedCandidate(
            chunk_id=cid,
            document_id=doc,
            fused_rank=i,
            vector_rank=i if mode != "bm25_only" else None,
            bm25_rank=i if mode != "dense_only" else None,
        )
        for i, cid in enumerate(ids, start=1)
    ]
    final = [
        StructuredCitation(
            chunk_id=r.chunk_id,
            document_id=doc,
            excerpt=f"Fact {r.chunk_id} is established in this passage.",
            rank=r.fused_rank,
        )
        for r in ranking[:8]
    ]
    is_null = qid in NULL_IDS
    marker = " ERRMARK" if (arm, qid) == ERRORED else ""
    if is_null or qid in ABSTAIN[arm]:
        answer = f"I cannot tell.{NL}Answer: Insufficient information"
    else:
        answer = f"Reasoning {_tag(qid)} {ARM_WORD[arm]}{marker}.{NL}Answer: Yes"
    return RunRecord(
        corpus=CORPUS,
        question_id=qid,
        graph_arm=arm,
        outcome="success",
        answer=answer,
        index_generation="gen1",
        duration_ms=1000.0,
        notices=[ABLATION] if spec.disable_graph_context else [],
        structured_citations=[] if is_null else final[:2],
        node_timings=[NodeTiming(node_name="RetrieveHybrid", duration_ms=100.0)],
        workflow_meta=WorkflowWireMeta(
            vector_count=0 if mode == "bm25_only" else 8,
            bm25_count=0 if mode == "dense_only" else 8,
            prompt_tokens=500,
            completion_tokens=50,
        ),
        snapshot=RetrievalSnapshot(
            index_generation="gen1",
            vector_weight=1.0,
            bm25_weight=1.0,
            rrf_k=60,
            candidate_limit=32,
            final_limit=8,
            result_hash="abc123",
            retrieved_chunks=final,
            retrieval_mode=mode,
            pre_truncation_ranking=ranking,
        ),
    )


def write_corpus(root: Path, *, protocol: str | None, name: str) -> Path:
    """Writes the tmp `[split]` corpus under `root/eval/corpora`; returns gold."""
    corpora = root / "eval" / "corpora"
    (corpora / "oj").mkdir(parents=True, exist_ok=True)
    arms = ", ".join(f'"{a}"' for a in ARMS)
    lines = [
        "[documents]",
        'map_corpus = "multihop_rag"',
        "chunk_size = 500",
        "[questions]",
        'file = "oj/questions.jsonl"',
        'label_format = "multihop_rag"',
        "sample_seed = 42",
        f"sample_size = {len(G_IDS) + len(NULL_IDS)}",
        "[models]",
        f'judge_model = "{MODEL}"',
        "[arms]",
        f"arms = [{arms}]",
        "[split]",
        'file = "oj/split.json"',
        'role = "heldout"',
    ]
    if protocol is not None:
        lines += ["[judge]", f'protocol = "{protocol}"']
    (corpora / f"{name}.toml").write_text("\n".join([*lines, ""]), encoding="utf-8")
    rows = []
    for qid in G_IDS:
        rows.append({
            "question_id": qid,
            "query": f"Question {qid}?",
            "question_type": QTYPE[qid],
            "answer": "Yes",
            "evidence_list": [
                {"title": "t", "fact": f"Fact {qid}:a is established in this passage."},
                {"title": "t", "fact": f"Fact {qid}:b is established in this passage."},
            ],
        })
    for qid in NULL_IDS:
        rows.append({
            "question_id": qid,
            "query": f"Question {qid}?",
            "question_type": "null_query",
            "answer": "Insufficient information",
            "evidence_list": [],
        })
    (corpora / "oj" / "questions.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    (corpora / "oj" / "split.json").write_text(
        json.dumps({
            "derivation_rule": "test",
            "populations_sha256": HEX,
            "diag_selection_sha256": HEX,
            "questions_sample_sha256": HEX,
            "dev_source": "dev.json",
            "order_seed": 42,
            "dev_ids": ["oj-dev1"],
            "heldout_g_ids": G_IDS,
            "heldout_null_ids": NULL_IDS,
        }),
        encoding="utf-8",
    )
    gold = root / "gold_chunks.jsonl"
    gold.write_text(
        "".join(
            json.dumps({
                "question_id": qid,
                "evidence_index": i,
                "title": "t",
                "document_id": _doc_id(),
                "state": "in_chunk",
                "chunk_ids": [f"{qid}:{which}"],
            })
            + "\n"
            for qid in G_IDS
            for i, which in enumerate(("a", "b"))
        ),
        encoding="utf-8",
    )
    return gold


def judge_fn(client: Any = None, **kwargs: Any) -> Any:
    """A fake judge: a varied verdict per cache key; one answer always errors."""
    if "ERRMARK" in kwargs["answer"]:
        return (None, "judge failed", None)
    key = cache_key(
        prompt_version=kwargs["prompt_version"],
        judge_model=kwargs["model"],
        question=kwargs["question"],
        answer=kwargs["answer"],
        post_truncation_evidence=kwargs["evidence"],
    )
    return (verdict_for(key), None, None)


@dataclass
class Scenario:
    root: Path
    run: Path
    gold: Path
    flow: Flow | None = None


def build_corpus_and_journal(
    base: Path,
    mp: pytest.MonkeyPatch,
    *,
    protocol: str | None = "ordered",
    name: str = CORPUS,
) -> Scenario:
    """The tmp corpus and a closed four-arm journal in a fresh git repository."""
    root = base / "repo"
    (root / "eval" / "src" / "lancet_eval").mkdir(parents=True)
    (base / "empty.gitconfig").write_text("", encoding="utf-8")
    gold = write_corpus(root, protocol=protocol, name=name)
    (root / ".gitignore").write_text("data/\n", encoding="utf-8")
    (root / THRESHOLDS_REL).write_text(THRESHOLDS_TEXT, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".gitignore", THRESHOLDS_REL)
    _git(root, "commit", "-q", "-m", "floor", when=int(time.time()) - 100_000)
    mp.setattr("lancet_eval.corpus._repo_root", lambda: root)
    mp.setenv("OPENROUTER_API_KEY", "sk-test-key-0123456789")
    mp.setattr(judge_stage, "judge_once", judge_fn)
    run = root / "runs" / "run"
    run.mkdir(parents=True)
    journal = Journal(run / "journal.jsonl")
    journal.write_header(corpus=name, partial=False)
    for qid in [*G_IDS, *NULL_IDS]:
        for arm in ARMS:
            journal.append(make_record(arm, qid).model_copy(update={"corpus": name}))
    return Scenario(root=root, run=run, gold=gold)


def build(
    base: Path, mp: pytest.MonkeyPatch, *, score_edit: Any = None, reveal: bool = True
) -> Scenario:
    """The full D-120 sequence in git: stage, emit, E, scores, reveal."""
    sc = build_corpus_and_journal(base, mp)
    judge_stage.run_judge_stage(run_dir=sc.run, stage_cap=5.0, git_repo=sc.root)
    emitted = calibration.emit_worksheet(
        sc.run, keys_root=sc.root / "data" / "calibration-keys", git_repo=sc.root
    )
    flow = Flow(sc.root, sc.run, emitted)
    flow.commit_worksheet()
    flow.fill_scores(score_edit)
    flow.commit_scores()
    if reveal:
        flow.reveal()
    sc.flow = flow
    return sc


def run_score(sc: Scenario, **kwargs: Any) -> CorpusReport:
    assert sc.flow is not None
    options: dict[str, Any] = {
        "run_dir": sc.run,
        "no_judge": True,
        "judged": True,
        "calibration_file": sc.flow.worksheet,
        "calibration_key": sc.flow.key_copy,
        "git_repo": sc.root,
        "gold_chunks_path": sc.gold,
    }
    options.update(kwargs)
    return score_run(**options)


def dim(report: CorpusReport, name: str) -> Any:
    found = [d for d in report.dimensions if d.name == name]
    assert len(found) == 1, f"{name}: {len(found)} dimensions"
    return found[0]


class _NoClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("the judged pass must not construct an HTTP client")


def _boom(*args: Any, **kwargs: Any) -> None:
    raise AssertionError("the judged pass must not call the judge")


@dataclass
class Happy:
    sc: Scenario
    report: CorpusReport
    report_text: str
    sidecar: JudgedResult
    sidecar_text: str
    output: str


@pytest.fixture(scope="module")
def happy(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The calibrated run, scored once per module with every judge entry point armed."""
    mp = pytest.MonkeyPatch()
    base = tmp_path_factory.mktemp("ordered_happy")
    try:
        sc = build(base, mp)
        buffer = io.StringIO()
        with mp.context() as spies, contextlib.redirect_stdout(buffer):
            spies.setattr(score_mod, "judge_once", _boom)
            spies.setattr(judge_stage, "judge_once", _boom)
            spies.setattr(judge, "judge_once", _boom)
            spies.setattr(httpx, "Client", _NoClient)
            report = run_score(sc)
        assert (sc.run / "report.json").is_file()
        assert (sc.run / "judged-result.json").is_file(), "no judged-result.json"
        report_text = (sc.run / "report.json").read_text(encoding="utf-8")
        sidecar_text = (sc.run / "judged-result.json").read_text(encoding="utf-8")
        yield Happy(
            sc=sc,
            report=report,
            report_text=report_text,
            sidecar=JudgedResult.model_validate_json(sidecar_text),
            sidecar_text=sidecar_text,
            output=buffer.getvalue(),
        )
    finally:
        mp.undo()


# --- independent expectations, computed from the journal and the cache ----------------


def _cache(happy: Happy) -> JudgeCache:
    return JudgeCache(happy.sc.run / "judge_cache.json")


def _verdicts(happy: Happy, arm: str) -> dict[str, Any]:
    """Question ID -> verdict for the arm's judged, non-abstaining, non-null records."""
    cache = _cache(happy)
    out: dict[str, Any] = {}
    for qid in G_IDS:
        if qid in ABSTAIN[arm]:
            continue
        rec = make_record(arm, qid)
        entry = cache.get(
            cache_key(
                prompt_version="v1",
                judge_model=MODEL,
                question=f"Question {qid}?",
                answer=rec.answer or "",
                post_truncation_evidence=truncate_evidence(rec.structured_citations),
            )
        )
        assert entry is not None
        if entry.verdict is not None:
            out[qid] = entry.verdict
    return out


# --- the happy path -------------------------------------------------------------------


def test_the_judged_pass_writes_the_report_and_the_sidecar_without_a_judge_call(
    happy: Happy,
) -> None:
    assert (happy.sc.run / "report.json").is_file()
    assert (happy.sc.run / "judged-result.json").is_file()
    assert happy.report.metadata.calibration_completed_n == 20
    # report.json round-trips through the unchanged schema
    assert CorpusReport.model_validate_json(happy.report_text) == happy.report


def test_every_judged_dimension_exists_under_its_exact_name(happy: Happy) -> None:
    names = {d.name for d in happy.report.dimensions}
    for dimension in ("groundedness", "faithfulness"):
        assert f"judge_qwk_{dimension}" in names
        for arm in ARMS:
            assert f"answer_{dimension}__{arm_slug(arm)}" in names
        for arm in ARMS:
            if arm != "hybrid":
                assert f"answer_{dimension}_delta__{arm_slug(arm)}" in names
        assert f"answer_{dimension}_delta__hybrid" not in names


def test_a_per_arm_judged_mean_is_over_the_judged_non_abstaining_answers(
    happy: Happy,
) -> None:
    for arm in ARMS:
        verdicts = _verdicts(happy, arm)
        for dimension in ("groundedness", "faithfulness"):
            d = dim(happy.report, f"answer_{dimension}__{arm_slug(arm)}")
            values = [float(getattr(v, dimension)) for v in verdicts.values()]
            assert d.status == "ok"
            assert d.n == len(values)
            assert d.score == pytest.approx(fmean(values))
            assert d.detail["ci_lower"] <= d.score <= d.detail["ci_upper"]


def test_a_judge_error_is_excluded_from_the_mean_and_counted_per_arm(
    happy: Happy,
) -> None:
    bm25 = dim(happy.report, "answer_groundedness__bm25_only")
    assert bm25.detail["judge_errors"] == 1.0
    assert ERRORED[1] not in _verdicts(happy, "bm25-only")
    for arm in ("dense-only", "hybrid", "hybrid+graph"):
        d = dim(happy.report, f"answer_groundedness__{arm_slug(arm)}")
        assert d.detail["judge_errors"] == 0.0
    # 10 inference questions, one errored: the mean never saw a low value for it
    row = next(
        r
        for r in happy.sidecar.arms
        if r.arm == "bm25-only" and r.dimension == "groundedness"
    )
    assert row.judge_errors == 1
    assert next(s for s in row.strata if s.question_type == INF).n == 9


def test_every_per_arm_judged_mean_sits_beside_its_abstention_rate_and_n(
    happy: Happy,
) -> None:
    for arm in ARMS:
        expected = len(ABSTAIN[arm]) / len(G_IDS)
        for dimension in ("groundedness", "faithfulness"):
            d = dim(happy.report, f"answer_{dimension}__{arm_slug(arm)}")
            assert d.detail["abstention_rate"] == pytest.approx(expected)
            assert d.detail["abstention_n"] == float(len(G_IDS))
    for row in happy.sidecar.arms:
        assert row.abstention_rate == pytest.approx(len(ABSTAIN[row.arm]) / len(G_IDS))
        assert row.abstention_n == len(G_IDS)
        assert row.comparability_note.startswith("different question sets")


def test_a_paired_judged_delta_excludes_the_questions_either_arm_abstained_on(
    happy: Happy,
) -> None:
    hybrid = _verdicts(happy, "hybrid")
    for arm, pairs, only_x, only_hybrid, both, unavailable in (
        ("dense-only", 24, 0, 2, 0, 0),
        ("hybrid+graph", 23, 1, 2, 0, 0),
        ("bm25-only", 15, 8, 1, 1, 1),
    ):
        verdicts = _verdicts(happy, arm)
        shared = sorted(set(verdicts) & set(hybrid))
        assert len(shared) == pairs
        for dimension in ("groundedness", "faithfulness"):
            d = dim(happy.report, f"answer_{dimension}_delta__{arm_slug(arm)}")
            expected = fmean(
                float(getattr(verdicts[q], dimension) - getattr(hybrid[q], dimension))
                for q in shared
            )
            assert d.n == pairs
            assert d.detail["n_pairs"] == float(pairs)
            assert d.score == pytest.approx(expected)
            assert d.detail["dropped_only_arm_abstained"] == float(only_x)
            assert d.detail["dropped_only_hybrid_abstained"] == float(only_hybrid)
            assert d.detail["dropped_both_abstained"] == float(both)
            assert d.detail["dropped_judge_unavailable"] == float(unavailable)
    bm25 = dim(happy.report, "answer_groundedness_delta__bm25_only")
    assert bm25.detail["judge_errors_x"] == 1.0
    assert bm25.detail["judge_errors_hybrid"] == 0.0


def test_the_abstention_companion_is_the_four_arm_dimension_not_a_second_delta(
    happy: Happy,
) -> None:
    for arm in ("dense-only", "bm25-only", "hybrid+graph"):
        companion = dim(happy.report, f"abstention_rate_g_delta__{arm_slug(arm)}")
        for dimension in ("groundedness", "faithfulness"):
            d = dim(happy.report, f"answer_{dimension}_delta__{arm_slug(arm)}")
            assert d.detail["abstention_rate_delta"] == companion.score
            assert (
                d.detail["abstention_rate_delta_ci_lower"]
                == companion.detail["ci_lower"]
            )
        rows = [r for r in happy.sidecar.deltas if r.arm == arm]
        assert len(rows) == 2
        for row in rows:
            assert row.abstention_rate_delta == companion.score
            assert row.abstention_n == len(G_IDS)
            assert row.abstention_rate_arm == pytest.approx(
                len(ABSTAIN[arm]) / len(G_IDS)
            )
            assert row.abstention_rate_reference == pytest.approx(2 / len(G_IDS))


def test_a_row_whose_abstention_delta_excludes_zero_carries_the_flag(
    happy: Happy,
) -> None:
    flagged = {r.arm for r in happy.sidecar.deltas if r.flag is not None}
    assert flagged == {"bm25-only"}
    for r in happy.sidecar.deltas:
        if r.flag is not None:
            assert r.flag == ABSTENTION_DIFFERS_FLAG
    bm25 = dim(happy.report, "answer_groundedness_delta__bm25_only")
    dense = dim(happy.report, "answer_groundedness_delta__dense_only")
    assert bm25.detail["abstention_differs"] == 1.0
    assert dense.detail["abstention_differs"] == 0.0
    assert ABSTENTION_DIFFERS_FLAG in happy.output


def test_no_judged_number_carries_a_p_value_or_a_holm_field(happy: Happy) -> None:
    pattern = re.compile(r"p_value|holm|signflip|significan", re.IGNORECASE)
    for d in happy.report.dimensions:
        if d.name.startswith((
            "answer_groundedness",
            "answer_faithfulness",
            "judge_qwk",
        )):
            assert not any(pattern.search(k) for k in d.detail), d.name
    assert pattern.search(happy.sidecar_text) is None


# --- D-40 judged strata ---------------------------------------------------------------


def test_a_per_arm_judged_mean_carries_the_d40_strata_with_a_ci_only_at_ten(
    happy: Happy,
) -> None:
    d = dim(happy.report, "answer_groundedness__dense_only")
    assert d.detail["type_comparison_query_n"] == 12.0
    assert d.detail["type_inference_query_n"] == 10.0  # n = 10 is evaluable
    assert d.detail["type_temporal_query_n"] == 4.0
    for qtype in (CMP, INF, TMP):
        assert f"type_{qtype}_value" in d.detail
    for qtype in (CMP, INF):
        assert f"type_{qtype}_ci_lower" in d.detail
        assert f"type_{qtype}_ci_upper" in d.detail
    assert "type_temporal_query_ci_lower" not in d.detail
    assert "type_temporal_query_ci_upper" not in d.detail


def test_a_paired_judged_delta_carries_the_d40_strata_with_a_ci_only_at_ten_pairs(
    happy: Happy,
) -> None:
    d = dim(happy.report, "answer_groundedness_delta__dense_only")
    assert d.detail["type_comparison_query_n_pairs"] == 12.0
    assert d.detail["type_inference_query_n_pairs"] == 9.0
    assert d.detail["type_temporal_query_n_pairs"] == 3.0
    assert "type_comparison_query_delta" in d.detail
    assert "type_comparison_query_ci_lower" in d.detail
    assert "type_inference_query_ci_lower" not in d.detail
    assert "type_temporal_query_ci_lower" not in d.detail


def test_the_sidecar_lists_every_stratum_beside_its_abstention_rate(
    happy: Happy,
) -> None:
    for row in happy.sidecar.arms:
        assert [s.question_type for s in row.strata] == [CMP, INF, TMP]
        for s in row.strata:
            total = sum(1 for q in G_IDS if QTYPE[q] == s.question_type)
            expected = (
                len({q for q in ABSTAIN[row.arm] if QTYPE[q] == s.question_type})
                / total
            )
            assert s.abstention_n == total
            assert s.abstention_rate == pytest.approx(expected)
            if s.n < 10:
                assert s.ci_lower is None and s.ci_upper is None
            else:
                assert s.ci_lower is not None and s.ci_upper is not None
    dense = next(
        r
        for r in happy.sidecar.arms
        if r.arm == "dense-only" and r.dimension == "groundedness"
    )
    assert [s.n for s in dense.strata] == [12, 10, 4]


def test_a_delta_stratum_ci_is_labelled_unadjusted_estimation_only(
    happy: Happy,
) -> None:
    seen_ci = 0
    for row in happy.sidecar.deltas:
        for s in row.strata:
            if s.n_pairs >= 10:
                assert s.ci_lower is not None
                assert s.ci_label == "unadjusted, estimation only"
                seen_ci += 1
            else:
                assert s.ci_lower is None and s.ci_label is None
    assert seen_ci > 0


# --- agreement and the labels ---------------------------------------------------------


def test_the_qwk_dimensions_carry_the_label_code_the_floor_and_every_companion(
    happy: Happy,
) -> None:
    for dimension in ("groundedness", "faithfulness"):
        d = dim(happy.report, f"judge_qwk_{dimension}")
        assert d.status == "ok"
        assert d.score == pytest.approx(1.0)  # the owner scored what the judge said
        assert d.detail["d114_label_code"] == 1.0
        assert d.detail["d114_floor"] == 0.70
        for key in (
            "n_pairs",
            "ci_lower",
            "ci_upper",
            "spearman",
            "exact_agreement",
            "mad",
            "mean_signed_difference",
            "joint_5_5_share",
            "qwk_dropped_resamples",
            "judge_marginal_1",
            "human_marginal_5",
        ):
            assert key in d.detail, key
        assert happy.sidecar.labels[dimension] == "calibrated"
    for arm_dim in happy.report.dimensions:
        if arm_dim.name.startswith(("answer_groundedness__", "answer_faithfulness__")):
            assert arm_dim.detail["d114_label_code"] == 1.0


def test_the_legacy_gate_is_printed_as_non_governing(happy: Happy) -> None:
    assert len(happy.sidecar.legacy_lines) == 2
    for line in happy.sidecar.legacy_lines:
        assert line.startswith("legacy (06.3), non-governing")
        assert line in happy.output
    assert "uncalibrated" not in " ".join(happy.sidecar.labels.values())


def test_the_printed_text_carries_the_marginals_and_the_per_arm_exact_counts(
    happy: Happy,
) -> None:
    for dimension in ("groundedness", "faithfulness"):
        d = happy.sidecar.agreement["dimensions"][dimension]
        judge = "/".join(str(d["judge_marginals"][str(v)]) for v in range(1, 6))
        human = "/".join(str(d["human_marginals"][str(v)]) for v in range(1, 6))
        assert (
            f"{dimension} marginal counts over 1..5: judge {judge}, human {human}"
            in (happy.output)
        )
        for arm, counts in d["per_arm_exact_agreement"].items():
            assert f"{arm} {counts['exact']}/{counts['n']}" in happy.output
        assert "resample(s) dropped as undefined" in happy.output


def test_the_judged_result_sidecar_holds_the_text_labels_and_the_commits(
    happy: Happy,
) -> None:
    assert happy.sidecar.labels == {
        "groundedness": "calibrated",
        "faithfulness": "calibrated",
    }
    commits = happy.sidecar.commits
    assert commits.d114_floor == 0.70
    assert (
        len({commits.worksheet_commit, commits.scores_commit, commits.key_commit}) == 3
    )
    assert {r.dimension for r in happy.sidecar.arms} == {"groundedness", "faithfulness"}
    assert len(happy.sidecar.arms) == 8
    assert len(happy.sidecar.deltas) == 6


def test_report_json_carries_only_float_detail_values(happy: Happy) -> None:
    data = json.loads(happy.report_text)
    for d in data["dimensions"]:
        for key, value in d["detail"].items():
            assert isinstance(value, float | int), (d["name"], key)
    assert "calibrated" not in " ".join(
        k for d in data["dimensions"] for k in d["detail"]
    )


# --- the other labels -----------------------------------------------------------------


def test_a_slice_the_judge_disagrees_with_is_published_and_labelled_uncalibrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc = build(tmp_path, monkeypatch, score_edit=lambda sid, g, f: (6 - g, 6 - f))
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        report = run_score(sc)
    for dimension in ("groundedness", "faithfulness"):
        d = dim(report, f"judge_qwk_{dimension}")
        assert d.score is not None and d.score < 0.70
        assert d.detail["d114_label_code"] == 0.0
        assert (
            dim(report, f"answer_{dimension}__dense_only").detail["d114_label_code"]
            == 0.0
        )
    sidecar = JudgedResult.model_validate_json(
        (sc.run / "judged-result.json").read_text(encoding="utf-8")
    )
    assert set(sidecar.labels.values()) == {"uncalibrated"}
    assert "uncalibrated" in buffer.getvalue()


def test_five_judge_errors_on_slice_items_read_slice_attrition_and_list_the_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc = build(tmp_path, monkeypatch)
    assert sc.flow is not None
    cache = JudgeCache(sc.run / "judge_cache.json")
    victims = [sc.flow.key_by_slice()[f"S{i:02d}"] for i in range(1, 6)]
    for key in victims:
        old = cache.get(key.cache_key)
        assert old is not None
        cache.entries[key.cache_key] = old.model_copy(
            update={"verdict": None, "error": "boom"}
        )
    cache.save()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        report = run_score(sc)
    for dimension in ("groundedness", "faithfulness"):
        d = dim(report, f"judge_qwk_{dimension}")
        assert d.detail["n_pairs"] == 15.0
        assert d.detail["d114_label_code"] == -1.0
    sidecar = JudgedResult.model_validate_json(
        (sc.run / "judged-result.json").read_text(encoding="utf-8")
    )
    assert sidecar.dropped_slice_ids == ["S01", "S02", "S03", "S04", "S05"]
    assert set(sidecar.labels.values()) == {"uncalibrated: slice attrition"}
    assert "S01, S02, S03, S04, S05" in buffer.getvalue()


# --- nothing is written when the order does not hold ----------------------------------


def _sentinel(sc: Scenario) -> bytes:
    sentinel = b'{"sentinel": true}\n'
    (sc.run / "report.json").write_bytes(sentinel)
    return sentinel


def test_a_dirty_worksheet_refuses_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc = build(tmp_path, monkeypatch)
    assert sc.flow is not None
    rows = sc.flow.rows()
    rows[0]["notes"] = "edited after the scores commit"
    sc.flow.write_worksheet(sc.flow.header(), rows)
    sentinel = _sentinel(sc)
    with pytest.raises(ScoreError, match="uncommitted change"):
        run_score(sc)
    assert (sc.run / "report.json").read_bytes() == sentinel
    assert not (sc.run / "judged-result.json").exists()


def test_a_key_revealed_with_the_scores_refuses_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc = build_corpus_and_journal(tmp_path, monkeypatch)
    judge_stage.run_judge_stage(run_dir=sc.run, stage_cap=5.0, git_repo=sc.root)
    emitted = calibration.emit_worksheet(
        sc.run, keys_root=sc.root / "data" / "calibration-keys", git_repo=sc.root
    )
    flow = Flow(sc.root, sc.run, emitted)
    flow.commit_worksheet()
    flow.fill_scores()
    flow.copy_reveal()
    flow.commit(
        "scores and key together", flow.worksheet, flow.key_copy, flow.salt_copy
    )
    sc.flow = flow
    sentinel = _sentinel(sc)
    with pytest.raises(ScoreError, match="no later than the scores commit"):
        run_score(sc)
    assert (sc.run / "report.json").read_bytes() == sentinel
    assert not (sc.run / "judged-result.json").exists()


def test_an_unrevealed_key_refuses_and_names_the_condition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc = build(tmp_path, monkeypatch, reveal=False)
    assert sc.flow is not None
    sc.flow.copy_reveal()  # on disk beside the run, never committed
    with pytest.raises(ScoreError, match="is not tracked by git"):
        run_score(sc)
    assert not (sc.run / "judged-result.json").exists()


def test_a_score_without_judged_never_shows_a_judged_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc = build(tmp_path, monkeypatch)
    report = score_run(
        run_dir=sc.run, no_judge=True, git_repo=sc.root, gold_chunks_path=sc.gold
    )
    for d in report.dimensions:
        assert not d.name.startswith(("answer_groundedness__", "answer_faithfulness__"))
        assert not d.name.startswith("judge_qwk")
    assert not (sc.run / "judged-result.json").exists()


# --- the legacy judged inputs refuse on an ordered corpus -----------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"no_judge": False, "stage_spend_cap": 1.0},
        {"emit_calibration_worksheet": "ws.jsonl"},
        {"calibration_file": "cal.jsonl"},
    ],
    ids=["judge", "emit-worksheet", "calibration-file"],
)
def test_the_legacy_judged_inputs_refuse_on_an_ordered_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any]
) -> None:
    sc = build_corpus_and_journal(tmp_path, monkeypatch)
    with pytest.raises(ScoreError) as excinfo:
        score_run(run_dir=sc.run, gold_chunks_path=sc.gold, git_repo=sc.root, **kwargs)
    message = str(excinfo.value)
    assert "lancet-eval judge" in message
    assert "lancet-eval calibration emit" in message
    assert "score --judged" in message
    assert not (sc.run / "report.json").exists()
    assert not (sc.run / "judge_cache.json").exists()


def test_judged_needs_an_ordered_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc = build_corpus_and_journal(
        tmp_path, monkeypatch, protocol=None, name=LEGACY_CORPUS
    )
    with pytest.raises(ScoreError, match='protocol = "ordered"'):
        score_run(
            run_dir=sc.run,
            judged=True,
            calibration_file=tmp_path / "w.jsonl",
            calibration_key=tmp_path / "k.jsonl",
            gold_chunks_path=sc.gold,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        pytest.param({}, "needs both", id="neither"),
        pytest.param({"calibration_file": "w.jsonl"}, "needs both", id="no-key"),
        pytest.param({"calibration_key": "k.jsonl"}, "needs both", id="no-file"),
        pytest.param(
            {
                "calibration_file": "w.jsonl",
                "calibration_key": "k.jsonl",
                "no_judge": False,
            },
            "cache-only",
            id="judge",
        ),
        pytest.param(
            {"calibration_file": "w.jsonl", "calibration_key": "k.jsonl", "sample": 5},
            "judges nothing new",
            id="sample",
        ),
        pytest.param(
            {
                "calibration_file": "w.jsonl",
                "calibration_key": "k.jsonl",
                "emit_calibration_worksheet": "x.jsonl",
            },
            "cache-only",
            id="emit",
        ),
    ],
)
def test_a_malformed_judged_call_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, Any],
    message: str,
) -> None:
    sc = build_corpus_and_journal(tmp_path, monkeypatch)
    with pytest.raises(ScoreError, match=message):
        score_run(
            run_dir=sc.run,
            judged=True,
            gold_chunks_path=sc.gold,
            git_repo=sc.root,
            **kwargs,
        )


def test_a_legacy_corpus_keeps_its_deterministic_report_and_gains_no_judged_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sc = build_corpus_and_journal(
        tmp_path, monkeypatch, protocol=None, name=LEGACY_CORPUS
    )
    report = score_run(
        run_dir=sc.run, no_judge=True, git_repo=sc.root, gold_chunks_path=sc.gold
    )
    assert dim(report, "answer_groundedness").status == "skipped"
    assert not any(d.name.startswith("judge_qwk") for d in report.dimensions)


# --- the command ----------------------------------------------------------------------


def _spy_score(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def spy(**kwargs: Any) -> None:
        seen.update(kwargs)
        raise RuntimeError("stop after recording the call")

    monkeypatch.setattr("lancet_eval.score.score_run", spy)
    return seen


def test_the_score_command_maps_judged_to_the_call_and_reads_the_sibling_salt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _spy_score(monkeypatch)
    key = tmp_path / "calibration-key.jsonl"
    key.write_text("", encoding="utf-8")
    (tmp_path / "calibration-salt.txt").write_text("salt\n", encoding="utf-8")
    worksheet = tmp_path / "calibration-worksheet.jsonl"
    worksheet.write_text("", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "score",
            "--run",
            str(tmp_path),
            "--judged",
            "--calibration-file",
            str(worksheet),
            "--calibration-key",
            str(key),
        ],
    )
    assert result.exit_code == 1  # the spy stops the call
    assert seen["judged"] is True
    assert seen["no_judge"] is True
    assert Path(seen["calibration_file"]) == worksheet
    assert Path(seen["calibration_key"]) == key
    assert "salt" not in seen  # there is no salt flag: the call derives it from the key


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--calibration-file", "w.jsonl"],
        ["--calibration-key", "k.jsonl"],
        [
            "--calibration-file",
            "w.jsonl",
            "--calibration-key",
            "k.jsonl",
            "--judge",
            "--stage-cap",
            "1",
        ],
        [
            "--calibration-file",
            "w.jsonl",
            "--calibration-key",
            "k.jsonl",
            "--emit-calibration-worksheet",
            "x.jsonl",
        ],
    ],
    ids=["neither", "no-key", "no-file", "judge", "emit"],
)
def test_judged_without_both_files_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: list[str]
) -> None:
    seen = _spy_score(monkeypatch)
    result = CliRunner().invoke(
        app, ["score", "--run", str(tmp_path), "--judged", *extra]
    )
    assert result.exit_code == 2, result.output
    assert not seen


def test_a_calibration_key_without_judged_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _spy_score(monkeypatch)
    result = CliRunner().invoke(
        app, ["score", "--run", str(tmp_path), "--calibration-key", "k.jsonl"]
    )
    assert result.exit_code == 2
    assert not seen


def test_a_missing_sibling_salt_file_refuses_and_names_its_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _spy_score(monkeypatch)
    key = tmp_path / "calibration-key.jsonl"
    key.write_text("", encoding="utf-8")
    worksheet = tmp_path / "calibration-worksheet.jsonl"
    worksheet.write_text("", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "score",
            "--run",
            str(tmp_path),
            "--judged",
            "--calibration-file",
            str(worksheet),
            "--calibration-key",
            str(key),
        ],
    )
    assert result.exit_code == 1
    squashed = re.sub(r"\s+", "", result.output)
    assert re.sub(r"\s+", "", str(tmp_path / "calibration-salt.txt")) in squashed
    assert not seen
