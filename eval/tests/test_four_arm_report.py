"""Tests for the four-arm `[split]` report of `score_run` (06.3.5-10, D-126).

A tmp `[split]` corpus (6 G questions, 2 per question_type, plus 2 null questions)
is scored over all four arms with every record provenance-clean, then individual
records are mutated to exercise populations, denominators and refusals.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from pathlib import Path
from statistics import fmean

import pytest

from lancet_eval import p4 as p4_mod
from lancet_eval.arms import ARM_REGISTRY, arm_slug
from lancet_eval.client import (
    Notice,
    RankedCandidate,
    RetrievalSnapshot,
    StructuredCitation,
)
from lancet_eval.corpus import GoldQuestion
from lancet_eval.journal import Journal, NodeTiming, RunRecord, WorkflowWireMeta
from lancet_eval.measure import (
    EMBEDDING_PRICE_PER_1M,
    ESTIMATED_EMBEDDING_TOKENS_PER_QUERY,
    compute_spend,
)
from lancet_eval.metrics import (
    answer_usable,
    final_answer_em,
    gold_contained,
)
from lancet_eval.report import CorpusReport, render_json
from lancet_eval.score import ScoreError, score_run
from lancet_eval.stats import bootstrap_mean_ci, wilson_ci
from lancet_eval.strata import STRATUM_TYPES

CORPUS = "fourarm_split"
ARMS = ("dense-only", "bm25-only", "hybrid", "hybrid+graph")
CMP, INF, TMP = STRATUM_TYPES
ABLATION = Notice(code="GRAPH_ABLATION", message="", typed_code=18)
NO_EVIDENCE = Notice(code="NO_EVIDENCE", message="", typed_code=1)
HEX = "0" * 64
NL = chr(10)  # the `Answer:` line must start its own line to be extracted

# (question_id, question_type, gold answer)
G_QUESTIONS = [
    ("fx-c1", CMP, "Yes"),
    ("fx-c2", CMP, "Yes"),
    ("fx-i1", INF, "Yes"),
    ("fx-i2", INF, "Paris"),
    ("fx-t1", TMP, "No"),
    ("fx-t2", TMP, "Berlin"),
]
G_IDS = [q for q, _, _ in G_QUESTIONS]
G_BY_ID = {q: (t, a) for q, t, a in G_QUESTIONS}
NULL_IDS = ["fx-n1", "fx-n2"]

# Rank (1-based, in the pre-truncation ranking) of gold fact a and gold fact b; None
# when the fact's chunk is not in the ranking at all. The ranking is 12 long.
RANKS: dict[str, dict[str, tuple[int | None, int | None]]] = {
    "hybrid": {
        "fx-c1": (1, 2),
        "fx-c2": (3, 7),
        "fx-i1": (6, None),
        "fx-i2": (None, None),
        "fx-t1": (2, 9),
        "fx-t2": (4, 5),
    },
    "hybrid+graph": {
        "fx-c1": (1, 2),
        "fx-c2": (2, 3),
        "fx-i1": (1, None),
        "fx-i2": (8, None),
        "fx-t1": (2, 9),
        "fx-t2": (None, None),
    },
    "dense-only": {
        "fx-c1": (2, 5),
        "fx-c2": (None, None),
        "fx-i1": (3, 4),
        "fx-i2": (11, None),
        "fx-t1": (1, None),
        "fx-t2": (5, 6),
    },
    "bm25-only": {
        "fx-c1": (4, None),
        "fx-c2": (1, 2),
        "fx-i1": (None, None),
        "fx-i2": (2, 3),
        "fx-t1": (7, 8),
        "fx-t2": (1, 10),
    },
}

# ok: exact "Answer: <gold>"; wrong; noline: gold is in the text but no Answer line;
# contained: the Answer line contains gold plus extra words (not an exact match).
KINDS: dict[str, dict[str, str]] = {
    "hybrid": dict(zip(G_IDS, ["ok", "ok", "ok", "wrong", "ok", "wrong"], strict=True)),
    "hybrid+graph": dict(
        zip(G_IDS, ["ok", "wrong", "ok", "noline", "wrong", "ok"], strict=True)
    ),
    "dense-only": dict(
        zip(G_IDS, ["ok", "ok", "wrong", "ok", "ok", "wrong"], strict=True)
    ),
    "bm25-only": dict(
        zip(G_IDS, ["wrong", "contained", "ok", "ok", "ok", "ok"], strict=True)
    ),
}

DURATION = {
    "dense-only": 800.0,
    "bm25-only": 600.0,
    "hybrid": 1000.0,
    "hybrid+graph": 1200.0,
}
RETRIEVE_MS = {
    "dense-only": 90.0,
    "bm25-only": 40.0,
    "hybrid": 100.0,
    "hybrid+graph": 150.0,
}
PROMPT_TOKENS = {
    "dense-only": 400,
    "bm25-only": 300,
    "hybrid": 500,
    "hybrid+graph": 600,
}
COMPLETION_TOKENS = 50


def _doc_id() -> str:
    from lancet_eval.seed import load_document_map

    return next(iter(load_document_map("multihop_rag").entries))


def _fact(qid: str, which: str) -> str:
    return f"Fact {qid} {which} is established in this passage."


def _chunk_id(qid: str, which: str) -> str:
    return f"{qid}:{which}"


def _ranking_ids(arm: str, qid: str) -> list[str]:
    """Twelve chunk IDs with the gold chunks at the table's ranks."""
    ids = [f"{qid}:{arm_slug(arm)}:f{pos}" for pos in range(1, 13)]
    if qid in RANKS[arm]:
        ra, rb = RANKS[arm][qid]
        if ra is not None:
            ids[ra - 1] = _chunk_id(qid, "a")
        if rb is not None:
            ids[rb - 1] = _chunk_id(qid, "b")
    return ids


def _excerpt(chunk_id: str) -> str:
    qid, _, tail = chunk_id.partition(":")
    if tail in ("a", "b"):
        return f"... {_fact(qid, tail)} ..."
    return "unrelated filler text"


def _answer(arm: str, qid: str) -> str:
    gold = G_BY_ID[qid][1]
    kind = KINDS[arm][qid]
    return {
        "ok": f"Based on the evidence.{NL}Answer: {gold}",
        "wrong": f"Based on the evidence.{NL}Answer: Wrong guess",
        "noline": f"I believe it is {gold}.",
        "contained": f"Answer: {gold}, indeed",
    }[kind]


def make_record(arm: str, qid: str) -> RunRecord:
    """A well-formed, provenance-clean record of a canonical arm."""
    spec = ARM_REGISTRY[arm]
    doc = _doc_id()
    ids = _ranking_ids(arm, qid) if qid in RANKS[arm] else [
        f"{qid}:{arm_slug(arm)}:f{pos}" for pos in range(1, 13)
    ]
    mode = spec.retrieval_mode
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
            excerpt=_excerpt(r.chunk_id),
            rank=r.fused_rank,
        )
        for r in ranking[:8]
    ]
    is_null = qid in NULL_IDS
    return RunRecord(
        corpus=CORPUS,
        question_id=qid,
        graph_arm=arm,
        outcome="success",
        answer="Answer: Insufficient information" if is_null else _answer(arm, qid),
        index_generation="gen1",
        duration_ms=DURATION[arm],
        notices=[ABLATION] if spec.disable_graph_context else [],
        structured_citations=[] if is_null else final[:1],
        node_timings=[
            NodeTiming(node_name="RetrieveHybrid", duration_ms=RETRIEVE_MS[arm])
        ],
        workflow_meta=WorkflowWireMeta(
            vector_count=0 if mode == "bm25_only" else 8,
            bm25_count=0 if mode == "dense_only" else 8,
            prompt_tokens=PROMPT_TOKENS[arm],
            completion_tokens=COMPLETION_TOKENS,
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


Mutations = dict[tuple[str, str], Callable[[RunRecord], RunRecord]]


def _write_corpus(root: Path, qtype_override: dict[str, str] | None = None) -> Path:
    """Writes the tmp `[split]` corpus under `root/eval/corpora`; returns gold."""
    corpora = root / "eval" / "corpora"
    (corpora / "fourarm").mkdir(parents=True)
    arms = ", ".join(f'"{a}"' for a in ARMS)
    (corpora / f"{CORPUS}.toml").write_text(
        "\n".join(
            [
                "[documents]",
                'map_corpus = "multihop_rag"',
                "chunk_size = 500",
                "[questions]",
                'file = "fourarm/questions.jsonl"',
                'label_format = "multihop_rag"',
                "sample_seed = 42",
                "sample_size = 8",
                "[models]",
                'judge_model = "meta-llama/llama-3.3-70b-instruct"',
                "[arms]",
                f"arms = [{arms}]",
                "[split]",
                'file = "fourarm/split.json"',
                'role = "heldout"',
                "[judge]",
                'protocol = "ordered"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    rows = []
    for qid, qtype, answer in G_QUESTIONS:
        rows.append(
            {
                "question_id": qid,
                "query": f"Question {qid}?",
                "question_type": (qtype_override or {}).get(qid, qtype),
                "answer": answer,
                "evidence_list": [
                    {"title": "t", "fact": _fact(qid, "a")},
                    {"title": "t", "fact": _fact(qid, "b")},
                ],
            }
        )
    for qid in NULL_IDS:
        rows.append(
            {
                "question_id": qid,
                "query": f"Question {qid}?",
                "question_type": "null_query",
                "answer": "Insufficient information",
                "evidence_list": [],
            }
        )
    (corpora / "fourarm" / "questions.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    (corpora / "fourarm" / "split.json").write_text(
        json.dumps(
            {
                "derivation_rule": "test",
                "populations_sha256": HEX,
                "diag_selection_sha256": HEX,
                "questions_sample_sha256": HEX,
                "dev_source": "dev.json",
                "order_seed": 42,
                "dev_ids": ["fx-dev1"],
                "heldout_g_ids": G_IDS,
                "heldout_null_ids": NULL_IDS,
            }
        ),
        encoding="utf-8",
    )
    gold = root / "gold_chunks.jsonl"
    gold.write_text(
        "".join(
            json.dumps(
                {
                    "question_id": qid,
                    "evidence_index": i,
                    "title": "t",
                    "document_id": _doc_id(),
                    "state": "in_chunk",
                    "chunk_ids": [_chunk_id(qid, which)],
                }
            )
            + "\n"
            for qid in G_IDS
            for i, which in enumerate(("a", "b"))
        ),
        encoding="utf-8",
    )
    return gold


def build_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutations: Mutations | None = None,
    qtype_override: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """Writes the corpus and a complete journal; returns (run_dir, gold_chunks)."""
    root = tmp_path / "repo"
    gold = _write_corpus(root, qtype_override)
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    run_dir = tmp_path / "run"
    journal = Journal(run_dir / "journal.jsonl")
    journal.write_header(corpus=CORPUS, partial=False)
    mutations = mutations or {}
    for qid in [*G_IDS, *NULL_IDS]:
        for arm in ARMS:
            rec = make_record(arm, qid)
            if (arm, qid) in mutations:
                rec = mutations[(arm, qid)](rec)
            journal.append(rec)
    return run_dir, gold


_CACHE: dict[str, CorpusReport] = {}
_RUN_DIRS: dict[str, Path] = {}


def scored(
    name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preregistered_clean_tree: str,
    mutations: Mutations | None = None,
) -> CorpusReport:
    """Scores a named scenario once per session (the report is read-only data)."""
    assert preregistered_clean_tree
    if name not in _CACHE:
        run_dir, gold = build_run(tmp_path, monkeypatch, mutations)
        _CACHE[name] = score_run(run_dir=run_dir, no_judge=True, gold_chunks_path=gold)
        _RUN_DIRS[name] = run_dir
    return _CACHE[name]


def dim(report: CorpusReport, name: str):  # type: ignore[no-untyped-def]
    found = [d for d in report.dimensions if d.name == name]
    assert len(found) == 1, f"{name}: {len(found)} dimensions"
    return found[0]


# ---- scenario mutations -----------------------------------------------------------


def _errored(rec: RunRecord) -> RunRecord:
    return rec.model_copy(
        update={
            "outcome": "error",
            "answer": None,
            "snapshot": None,
            "error_type": "timeout",
            "error": "boom",
            "structured_citations": [],
        }
    )


def _blank_no_evidence(rec: RunRecord) -> RunRecord:
    assert rec.snapshot is not None
    return rec.model_copy(
        update={
            "answer": "",
            "structured_citations": [],
            "notices": [*rec.notices, NO_EVIDENCE],
            "workflow_meta": WorkflowWireMeta(vector_count=0, bm25_count=8),
            "snapshot": rec.snapshot.model_copy(
                update={"retrieved_chunks": [], "pre_truncation_ranking": []}
            ),
        }
    )


ERRORED: Mutations = {("dense-only", "fx-c2"): _errored}
BLANK: Mutations = {("bm25-only", "fx-i1"): _blank_no_evidence}

# ---- expected values, from the tables above --------------------------------------


def paper_q(arm: str, qid: str) -> dict[str, float]:
    ra, rb = RANKS[arm][qid]
    found = [r for r in (ra, rb) if r is not None and r <= 10]
    first = min(found) if found else None
    return {
        "hit4": float(first is not None and first <= 4),
        "hit10": float(first is not None),
        "rr": 1 / first if first else 0.0,
        "ap": sum(1 / r for r in found) / 2,
    }


def gold_question(qid: str) -> GoldQuestion:
    qtype, answer = G_BY_ID[qid]
    return GoldQuestion(
        question_id=qid,
        question=f"Question {qid}?",
        question_type=qtype,
        gold_answer=answer,
        gold_facts=[_fact(qid, "a"), _fact(qid, "b")],
        evidence_list=[{"fact": _fact(qid, "a")}, {"fact": _fact(qid, "b")}],
    )


SLUGS = {arm: arm_slug(arm) for arm in ARMS}
assert SLUGS == {
    "dense-only": "dense_only",
    "bm25-only": "bm25_only",
    "hybrid": "hybrid",
    "hybrid+graph": "hybrid_graph",
}

PAPER = [
    "paper_hits_at_4",
    "paper_hits_at_10",
    "paper_mrr_at_10",
    "paper_map_at_10",
]
SCRIPT_FAITHFUL = [f"{m}_script_faithful" for m in PAPER]
TASK1_PER_ARM = [
    *PAPER,
    *SCRIPT_FAITHFUL,
    "answer_usable_p4",
    "answer_usable_sc3_definition",
    "abstention_rate_g",
    "null_abstention_correctness",
    "final_answer_em",
    "gold_containment",
    "final_answer_missing_rate",
    "coverage_at_4",
    "precision_at_4",
    "latency_total_ms_p50",
    "latency_total_ms_p95",
    "retrieve_node_ms_p50",
    "retrieve_node_ms_p95",
    "prompt_tokens_mean",
]
# every per-arm dimension over G questions carries strata; the null line does not
STRATIFIED = [n for n in TASK1_PER_ARM if n != "null_abstention_correctness"]


# ---- Task 1 -----------------------------------------------------------------------


def test_every_per_arm_dimension_exists_under_its_exact_name(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    names = {d.name for d in report.dimensions}
    for slug in SLUGS.values():
        for base in TASK1_PER_ARM:
            assert f"{base}__{slug}" in names, f"{base}__{slug}"
    assert "paper_hits_at_4__hybrid_graph" in names
    assert "paper_hits_at_4_script_faithful__bm25_only" in names
    assert "answer_usable_p4__hybrid" in names
    assert "answer_usable_sc3_definition__dense_only" in names
    assert "p4_size" in names


def test_every_detail_value_is_a_float_and_the_report_renders(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    for d in report.dimensions:
        assert all(type(v) is float for v in d.detail.values()), d.name
        assert d.status == "ok" or d.reason
    assert render_json(report)
    assert (_RUN_DIRS["base"] / "report.json").is_file()


def test_the_headline_paper_metrics_are_computed_on_p4_with_their_cis(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    for arm, slug in SLUGS.items():
        scores = {q: paper_q(arm, q) for q in G_IDS}
        for metric, key, ci in (
            ("paper_hits_at_4", "hit4", "wilson"),
            ("paper_hits_at_10", "hit10", "wilson"),
            ("paper_mrr_at_10", "rr", "bootstrap"),
            ("paper_map_at_10", "ap", "bootstrap"),
        ):
            d = dim(report, f"{metric}__{slug}")
            vals = [scores[q][key] for q in sorted(G_IDS)]
            assert d.n == 6
            assert d.score == pytest.approx(fmean(vals))
            assert d.detail["n_excluded"] == 0.0
            if ci == "wilson":
                _, lo, hi = wilson_ci(round(sum(vals)), 6)
            else:
                _, lo, hi = bootstrap_mean_ci(vals, seed=42, b=10_000)
            assert d.detail["ci_lower"] == pytest.approx(lo)
            assert d.detail["ci_upper"] == pytest.approx(hi)


def test_an_errored_record_leaves_p4_for_every_arm_but_not_the_script_faithful_line(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("errored", tmp_path, monkeypatch, preregistered_clean_tree, ERRORED)
    for slug in SLUGS.values():
        d = dim(report, f"paper_hits_at_4__{slug}")
        assert d.n == 5
        assert d.detail["n_excluded"] == 1.0
    dense = dim(report, "paper_hits_at_4_script_faithful__dense_only")
    assert dense.n == 6
    assert dense.detail["n_no_valid_ranking"] == 1.0
    hits = [paper_q("dense-only", q)["hit4"] for q in G_IDS if q != "fx-c2"]
    assert dense.score == pytest.approx(sum(hits) / 6)  # the errored question is a miss
    other = dim(report, "paper_hits_at_4_script_faithful__hybrid")
    assert other.n == 6
    assert other.detail["n_no_valid_ranking"] == 0.0
    p4 = dim(report, "p4_size")
    assert p4.score == 5.0
    assert p4.detail["coverage"] == pytest.approx(5 / 6)
    assert p4.detail["excluded_own_failure__dense_only"] == 1.0
    assert p4.detail["excluded_other_arm_failure__hybrid"] == 1.0
    assert p4.detail["excluded_own_failure__hybrid"] == 0.0


def test_a_usable_blank_no_evidence_answer_scores_zero_and_is_an_abstention(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("blank", tmp_path, monkeypatch, preregistered_clean_tree, BLANK)
    d = dim(report, "answer_usable_p4__bm25_only")
    assert d.n == 6  # the decline stays in the P4 denominator (D-121)
    kinds = KINDS["bm25-only"]
    usable = [
        0.0
        if q == "fx-i1"
        else float(answer_usable(gold_question(q), _answer("bm25-only", q)))
        for q in G_IDS
    ]
    assert kinds["fx-i1"] == "ok"  # it would have scored 1 but for the decline
    assert d.score == pytest.approx(sum(usable) / 6)
    assert d.detail["usable_blank_answer_count"] == 1.0
    hybrid_usable = dim(report, "answer_usable_p4__hybrid")
    assert hybrid_usable.detail["usable_blank_answer_count"] == 0.0
    ab = dim(report, "abstention_rate_g__bm25_only")
    assert ab.score == pytest.approx(1 / 6)
    assert ab.n == 6
    lo_hi = wilson_ci(1, 6)
    assert ab.detail["ci_lower"] == pytest.approx(lo_hi[1])
    assert ab.detail["ci_upper"] == pytest.approx(lo_hi[2])
    # the 06.3.4.1 SC-3 definition excludes the blank-answer record
    sc3 = dim(report, "answer_usable_sc3_definition__bm25_only")
    assert sc3.n == 5
    assert sc3.score == pytest.approx(
        sum(
            float(answer_usable(gold_question(q), _answer("bm25-only", q)))
            for q in G_IDS
            if q != "fx-i1"
        )
        / 5
    )
    assert dim(report, "answer_usable_sc3_definition__hybrid").n == 6


def test_the_d70_secondaries_and_legacy_retrieval_metrics_are_per_arm_on_p4(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    for arm, slug in SLUGS.items():
        golds = {q: gold_question(q) for q in G_IDS}
        ans = {q: _answer(arm, q) for q in G_IDS}
        em = [final_answer_em(golds[q], ans[q]).score for q in sorted(G_IDS)]
        cont = [
            float(gold_contained(golds[q].gold_answer, ans[q])) for q in sorted(G_IDS)
        ]
        em_dim = dim(report, f"final_answer_em__{slug}")
        assert em_dim.score == pytest.approx(fmean(em))
        cont_dim = dim(report, f"gold_containment__{slug}")
        assert cont_dim.score == pytest.approx(fmean(cont))
        missing = [float(KINDS[arm][q] == "noline") for q in sorted(G_IDS)]
        d = dim(report, f"final_answer_missing_rate__{slug}")
        assert d.score == pytest.approx(fmean(missing))
        cov = [
            sum(1 for r in RANKS[arm][q] if r is not None and r <= 4) / 2
            for q in sorted(G_IDS)
        ]
        prec = [
            sum(1 for r in RANKS[arm][q] if r is not None and r <= 4) / 4
            for q in sorted(G_IDS)
        ]
        assert dim(report, f"coverage_at_4__{slug}").score == pytest.approx(fmean(cov))
        prec_dim = dim(report, f"precision_at_4__{slug}")
        assert prec_dim.score == pytest.approx(fmean(prec))


def test_null_questions_appear_only_in_the_null_abstention_dimension(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    for slug in SLUGS.values():
        d = dim(report, f"null_abstention_correctness__{slug}")
        assert d.n == 2
        assert d.score == 1.0
        assert d.detail["hallucinated_on_null"] == 0.0
        assert d.detail["no_evidence_count"] == 0.0
        assert d.detail["leak_count"] == 0.0
        assert not [k for k in d.detail if k.startswith("type_")]
        for base in STRATIFIED:
            assert dim(report, f"{base}__{slug}").n <= 6


def test_p4_size_carries_the_coverage_and_the_per_arm_exclusions(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    d = dim(report, "p4_size")
    assert d.score == 6.0
    assert d.n == 6
    assert d.detail["coverage"] == 1.0
    assert not [k for k in d.detail if k.startswith("type_")]
    for slug in SLUGS.values():
        for reason in ("own_failure", "provenance", "other_arm_failure"):
            assert d.detail[f"excluded_{reason}__{slug}"] == 0.0


def test_the_legacy_named_dimensions_are_computed_on_hybrid_plus_graph(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    legacy = dim(report, "retrieval_evidence_coverage")
    assert legacy.score == pytest.approx(
        dim(report, "coverage_at_4__hybrid_graph").score
    )
    assert dim(report, "answer_usable").score == pytest.approx(
        dim(report, "answer_usable_p4__hybrid_graph").score
    )


def test_the_d40_strata_sum_to_n_and_carry_no_ci_below_the_cell_size(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    for slug in SLUGS.values():
        for base in STRATIFIED:
            d = dim(report, f"{base}__{slug}")
            total = sum(d.detail[f"type_{t}_n"] for t in STRATUM_TYPES)
            assert total == float(d.n), d.name
            for t in STRATUM_TYPES:
                assert f"type_{t}_value" in d.detail, d.name
            assert not [k for k in d.detail if k.startswith("type_") and "_ci_" in k]
    assert "type_temporal_query_n" in dim(report, "paper_hits_at_4__hybrid").detail
    hits = dim(report, "paper_hits_at_4__hybrid")
    assert hits.detail[f"type_{CMP}_value"] == pytest.approx(
        fmean(paper_q("hybrid", q)["hit4"] for q in ("fx-c1", "fx-c2"))
    )


def test_answer_usable_carries_the_constant_yes_baseline_per_type(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    want = {CMP: 1.0, INF: 0.5, TMP: 0.0}
    for slug in SLUGS.values():
        for name in ("answer_usable_p4", "answer_usable_sc3_definition"):
            d = dim(report, f"{name}__{slug}")
            for t, share in want.items():
                assert d.detail[f"type_{t}_constant_yes_baseline"] == share
    assert "type_comparison_query_constant_yes_baseline" in dim(
        report, "answer_usable_p4__hybrid"
    ).detail
    assert not [
        k
        for k in dim(report, "paper_hits_at_4__hybrid").detail
        if "constant_yes" in k
    ]


def test_the_script_faithful_line_covers_every_g_question(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    for slug in SLUGS.values():
        for base in SCRIPT_FAITHFUL:
            d = dim(report, f"{base}__{slug}")
            assert d.n == 6
            assert d.detail["n_no_valid_ranking"] == 0.0


def test_a_legacy_corpus_gets_no_four_arm_dimensions(tmp_path: Path) -> None:
    from lancet_eval.corpus import load_sample_questions
    from lancet_eval.seed import load_document_map

    qid = load_sample_questions("multihop_rag")[0].question_id
    doc = next(iter(load_document_map("multihop_rag").entries))
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(
        RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer="London",
            index_generation="gen-1",
            snapshot=RetrievalSnapshot(
                index_generation="gen-1",
                retrieved_chunks=[
                    StructuredCitation(chunk_id="c1", document_id=doc, rank=1)
                ],
            ),
        )
    )
    report = score_run(run_dir=tmp_path, no_judge=True)
    assert not [d.name for d in report.dimensions if "__" in d.name]
    assert not [
        k for d in report.dimensions for k in d.detail if k.startswith("type_")
    ]
    assert "p4_size" not in {d.name for d in report.dimensions}


def test_the_report_schema_is_unchanged() -> None:
    from lancet_eval.config import repo_root
    from lancet_eval.report import emit_schema

    schema = (repo_root() / "eval" / "report.schema.json").read_text(encoding="utf-8")
    assert emit_schema() == schema


def test_p4_helper_agrees_with_the_report_population(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    # the report's P4 is the p4 module's, not a second definition
    report = scored("errored", tmp_path, monkeypatch, preregistered_clean_tree, ERRORED)
    assert dim(report, "p4_size").n == len(
        [q for q in G_IDS if q != "fx-c2"]
    )
    assert p4_mod.DEFAULT_REFERENCE_ARM == "hybrid"
    assert not math.isnan(dim(report, "p4_size").score or 0.0)


# ---- Task 2: provenance refusal, per-arm means, spend, paired deltas ---------------

COMPARISON_SLUGS = ("dense_only", "bm25_only", "hybrid_graph")
DELTA_NAMES = [
    "paper_hits_at_10_delta",
    "paper_mrr_at_10_delta",
    "paper_map_at_10_delta",
    "final_answer_em_delta",
    "gold_containment_delta",
    "final_answer_missing_rate_delta",
    "coverage_at_4_delta",
    "precision_at_4_delta",
    "abstention_rate_g_delta",
    "latency_total_ms_delta",
    "retrieve_node_ms_delta",
    "prompt_tokens_delta",
    "spend_usd_delta",
]
MEAN_NAMES = [
    "latency_total_ms_mean",
    "retrieve_node_ms_mean",
    "spend_usd_mean",
]


def _snapshot(rec: RunRecord, **update: object) -> RunRecord:
    assert rec.snapshot is not None
    return rec.model_copy(update={"snapshot": rec.snapshot.model_copy(update=update)})


def _echo_hybrid(rec: RunRecord) -> RunRecord:  # clause (a)
    return _snapshot(rec, retrieval_mode="hybrid")


def _drop_ranking(rec: RunRecord) -> RunRecord:  # clause (b)
    return _snapshot(rec, pre_truncation_ranking=[])


def _break_prefix(rec: RunRecord) -> RunRecord:  # clause (c)
    assert rec.snapshot is not None
    final = list(rec.snapshot.retrieved_chunks)
    final[0] = final[0].model_copy(update={"chunk_id": "not-the-ranking"})
    return _snapshot(rec, retrieved_chunks=final)


def _bm25_rank_on_dense(rec: RunRecord) -> RunRecord:  # clause (d)
    assert rec.snapshot is not None
    ranking = list(rec.snapshot.pre_truncation_ranking)
    ranking[0] = ranking[0].model_copy(update={"bm25_rank": 1})
    return _snapshot(rec, pre_truncation_ranking=ranking)


def _wrong_rrf_k(rec: RunRecord) -> RunRecord:  # clause (f)
    return _snapshot(rec, rrf_k=61)


def _drop_ablation(rec: RunRecord) -> RunRecord:  # clause (e)
    return rec.model_copy(update={"notices": []})


def _bm25_count_on_dense(rec: RunRecord) -> RunRecord:  # clause (g)
    return rec.model_copy(
        update={"workflow_meta": WorkflowWireMeta(vector_count=8, bm25_count=3)}
    )


@pytest.mark.parametrize(
    ("code", "arm", "mutate"),
    [
        ("a", "dense-only", _echo_hybrid),
        ("b", "hybrid", _drop_ranking),
        ("c", "hybrid", _break_prefix),
        ("d", "dense-only", _bm25_rank_on_dense),
        ("f", "hybrid+graph", _wrong_rrf_k),
    ],
)
def test_a_zero_tolerance_provenance_failure_refuses_the_report(
    code, arm, mutate, tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    assert preregistered_clean_tree
    run_dir, gold = build_run(tmp_path, monkeypatch, {(arm, "fx-c1"): mutate})
    with pytest.raises(ScoreError) as exc_info:
        score_run(run_dir=run_dir, no_judge=True, gold_chunks_path=gold)
    message = str(exc_info.value)
    assert f"fx-c1/{arm}/{code}" in message
    assert "D-110" in message
    assert "1 record(s)" in message
    assert not (run_dir / "report.json").exists()


def test_more_than_twenty_failing_records_lists_twenty_and_states_the_total(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    assert preregistered_clean_tree
    every = {
        (arm, qid): _wrong_rrf_k
        for arm in ARMS
        for qid in [*G_IDS, *NULL_IDS]
        if (arm, qid) != ("dense-only", "fx-c1")
    }
    assert len(every) == 31
    run_dir, gold = build_run(tmp_path, monkeypatch, every)
    with pytest.raises(ScoreError) as exc_info:
        score_run(run_dir=run_dir, no_judge=True, gold_chunks_path=gold)
    message = str(exc_info.value)
    assert "31 record(s)" in message
    assert len(re.findall(r"fx-[a-z0-9]+/[a-z0-9+-]+/f", message)) == 20


def test_a_missing_graph_ablation_is_counted_and_excluded_not_refused(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored(
        "e",
        tmp_path,
        monkeypatch,
        preregistered_clean_tree,
        {("hybrid", "fx-c1"): _drop_ablation},
    )
    size = dim(report, "p4_size")
    assert size.score == 5.0
    assert size.detail["excluded_provenance__hybrid"] == 1.0
    assert size.detail["excluded_other_arm_failure__dense_only"] == 1.0
    conformance = dim(report, "arm_provenance_conformance")
    assert conformance.detail["code_e"] == 1.0
    assert conformance.score == 1.0  # no zero-tolerance failure


def test_a_corroboration_failure_is_counted_and_changes_nothing_else(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored(
        "g",
        tmp_path,
        monkeypatch,
        preregistered_clean_tree,
        {("dense-only", "fx-c1"): _bm25_count_on_dense},
    )
    assert dim(report, "p4_size").score == 6.0
    conformance = dim(report, "arm_provenance_conformance")
    assert conformance.detail["code_g"] == 1.0
    assert conformance.detail["code_e"] == 0.0


def test_arm_provenance_conformance_is_one_with_zero_counts_on_a_clean_drive(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    d = dim(report, "arm_provenance_conformance")
    assert d.score == 1.0
    assert d.n == 32
    for code in "abcdefg":
        assert d.detail[f"code_{code}"] == 0.0
    assert d.detail["records_failing_zero_tolerance"] == 0.0
    assert not [k for k in d.detail if k.startswith("type_")]


def test_every_secondary_delta_exists_for_the_three_comparison_arms_only(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    names = {d.name for d in report.dimensions}
    for slug in COMPARISON_SLUGS:
        for base in DELTA_NAMES:
            assert f"{base}__{slug}" in names, f"{base}__{slug}"
        for base in MEAN_NAMES:
            assert f"{base}__{slug}" in names
    assert "paper_mrr_at_10_delta__dense_only" in names
    assert "final_answer_em_delta__hybrid_graph" in names
    assert "coverage_at_4_delta__bm25_only" in names
    assert "latency_total_ms_delta__bm25_only" in names
    assert "spend_usd_delta__hybrid_graph" in names
    assert not [n for n in names if n.endswith("_delta__hybrid")]
    # the primaries' deltas belong to 06.3.5-13, inside their Holm families
    assert not [n for n in names if n.startswith("paper_hits_at_4_delta")]
    assert not [n for n in names if n.startswith("answer_usable") and "_delta" in n]
    # a difference of two percentiles is not a paired per-question statistic
    assert not [n for n in names if "_p50_delta" in n or "_p95_delta" in n]


def _expected_spend(arm: str, qid: str) -> float:
    rec = make_record(arm, qid)
    embeds = not (
        ARM_REGISTRY[arm].retrieval_mode == "bm25_only"
        and ARM_REGISTRY[arm].disable_graph_context
    )
    return compute_spend([rec], include_embeddings=embeds)[0]


def _expected_values(arm: str, metric: str) -> dict[str, float]:
    """Per-question P4 values of one secondary, derived from the tables."""
    out: dict[str, float] = {}
    for qid in G_IDS:
        gold = gold_question(qid)
        ans = _answer(arm, qid)
        ranks = RANKS[arm][qid]
        in4 = sum(1 for r in ranks if r is not None and r <= 4)
        out[qid] = {
            "paper_hits_at_10": paper_q(arm, qid)["hit10"],
            "paper_mrr_at_10": paper_q(arm, qid)["rr"],
            "paper_map_at_10": paper_q(arm, qid)["ap"],
            "final_answer_em": float(final_answer_em(gold, ans).score or 0.0),
            "gold_containment": float(gold_contained(gold.gold_answer, ans)),
            "final_answer_missing_rate": float(KINDS[arm][qid] == "noline"),
            "coverage_at_4": in4 / 2,
            "precision_at_4": in4 / 4,
            "abstention_rate_g": 0.0,
            "latency_total_ms": DURATION[arm],
            "retrieve_node_ms": RETRIEVE_MS[arm],
            "prompt_tokens": float(PROMPT_TOKENS[arm]),
            "spend_usd": _expected_spend(arm, qid),
        }[metric]
    return out


def test_each_delta_equals_the_p4_mean_difference_with_the_p4_bootstrap_ci(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    for arm in ("dense-only", "bm25-only", "hybrid+graph"):
        slug = SLUGS[arm]
        for base in DELTA_NAMES:
            metric = base.removesuffix("_delta")
            x = _expected_values(arm, metric)
            ref = _expected_values("hybrid", metric)
            want = p4_mod.paired_delta(x, ref)
            d = dim(report, f"{base}__{slug}")
            assert d.n == 6, d.name
            assert d.score == pytest.approx(
                fmean(x.values()) - fmean(ref.values()), abs=1e-9
            ), d.name
            assert d.score == pytest.approx(want.delta, abs=1e-9), d.name
            assert d.detail["n_pairs"] == 6.0
            assert d.detail["ci_lower"] == pytest.approx(want.ci_lower, abs=1e-9)
            assert d.detail["ci_upper"] == pytest.approx(want.ci_upper, abs=1e-9)
            assert d.detail["mean_x"] == pytest.approx(fmean(x.values()), abs=1e-9)
            assert d.detail["mean_hybrid"] == pytest.approx(
                fmean(ref.values()), abs=1e-9
            )
            for qtype in STRATUM_TYPES:
                assert f"type_{qtype}_n_pairs" in d.detail, d.name
                assert f"type_{qtype}_delta" in d.detail, d.name
            assert not [k for k in d.detail if k.startswith("type_") and "_ci_" in k]


def test_the_latency_delta_is_the_paired_per_question_difference(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    assert dim(report, "latency_total_ms_delta__hybrid_graph").score == 200.0
    assert dim(report, "latency_total_ms_delta__dense_only").score == -200.0
    assert dim(report, "retrieve_node_ms_delta__bm25_only").score == -60.0
    assert dim(report, "prompt_tokens_delta__hybrid_graph").score == 100.0


def test_the_missing_rate_delta_carries_the_counts(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    d = dim(report, "final_answer_missing_rate_delta__hybrid_graph")
    assert (d.detail["count_x"], d.detail["count_hybrid"]) == (1.0, 0.0)
    assert d.detail["count_delta"] == 1.0
    b = dim(report, "final_answer_missing_rate_delta__bm25_only")
    assert (b.detail["count_x"], b.detail["count_hybrid"]) == (0.0, 0.0)
    assert b.detail["count_delta"] == 0.0


def test_the_abstention_delta_reads_a_decline_against_hybrid(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("blank", tmp_path, monkeypatch, preregistered_clean_tree, BLANK)
    d = dim(report, "abstention_rate_g_delta__bm25_only")
    assert d.score == pytest.approx(1 / 6)
    assert d.detail["mean_x"] == pytest.approx(1 / 6)
    assert d.detail["mean_hybrid"] == 0.0


def test_no_secondary_delta_carries_a_p_value_or_a_holm_field(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    for d in report.dimensions:
        for key in d.detail:
            assert "p_value" not in key, (d.name, key)
            assert "holm" not in key, (d.name, key)
        assert "holm" not in d.name
        assert "p_value" not in d.name
        if "_delta__" in d.name:
            assert all(type(v) is float for v in d.detail.values())


def test_the_per_arm_means_carry_a_bootstrap_ci_and_strata_percentiles_do_not(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    report = scored("base", tmp_path, monkeypatch, preregistered_clean_tree)
    for arm, slug in SLUGS.items():
        for base, per_q in (
            ("latency_total_ms_mean", [DURATION[arm]] * 6),
            ("retrieve_node_ms_mean", [RETRIEVE_MS[arm]] * 6),
            ("spend_usd_mean", [_expected_spend(arm, q) for q in sorted(G_IDS)]),
        ):
            d = dim(report, f"{base}__{slug}")
            _, lo, hi = bootstrap_mean_ci(per_q, seed=42, b=10_000)
            assert d.score == pytest.approx(fmean(per_q), abs=1e-12)
            assert d.detail["ci_lower"] == pytest.approx(lo, abs=1e-9)
            assert d.detail["ci_upper"] == pytest.approx(hi, abs=1e-9)
            assert sum(d.detail[f"type_{t}_n"] for t in STRATUM_TYPES) == 6.0
        pct = dim(report, f"latency_total_ms_p95__{slug}")
        assert "ci_lower" not in pct.detail


def test_bm25_only_carries_no_embedding_charge_and_dense_only_does() -> None:
    """D-125: bm25-only with the graph off embeds nothing; measure.py is unchanged."""
    from lancet_eval.score import _record_spend_usd

    meta = WorkflowWireMeta(prompt_tokens=500, completion_tokens=50)

    def with_tokens(arm: str) -> RunRecord:
        return make_record(arm, "fx-c1").model_copy(update={"workflow_meta": meta})

    dense, bm25, graph = (
        with_tokens("dense-only"),
        with_tokens("bm25-only"),
        with_tokens("hybrid+graph"),
    )
    one_embedding = ESTIMATED_EMBEDDING_TOKENS_PER_QUERY * EMBEDDING_PRICE_PER_1M / 1e6
    generation = compute_spend([bm25], include_embeddings=False)[0]
    assert _record_spend_usd(bm25) == pytest.approx(generation, abs=1e-15)
    assert _record_spend_usd(dense) - _record_spend_usd(bm25) == pytest.approx(
        one_embedding, abs=1e-15
    )
    assert _record_spend_usd(graph) == pytest.approx(
        generation + one_embedding, abs=1e-15
    )


def test_a_superseded_attempt_is_priced_with_its_own_embedding() -> None:
    from lancet_eval.journal import AttemptRecord
    from lancet_eval.score import _record_spend_usd

    base = make_record("dense-only", "fx-c1")
    prior = AttemptRecord(
        attempt=1, outcome="error", error_type="timeout", error="slow"
    )
    retried = base.model_copy(update={"prior_attempts": [prior]})
    one_embedding = ESTIMATED_EMBEDDING_TOKENS_PER_QUERY * EMBEDDING_PRICE_PER_1M / 1e6
    gap = _record_spend_usd(retried) - _record_spend_usd(base)
    assert gap == pytest.approx(one_embedding, abs=1e-15)


@pytest.mark.parametrize("bad_type", ["unknown", "null_query"])
def test_a_held_out_g_question_outside_the_three_types_refuses_before_scoring(
    bad_type, tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    assert preregistered_clean_tree
    run_dir, gold = build_run(
        tmp_path, monkeypatch, qtype_override={"fx-i2": bad_type}
    )
    with pytest.raises(ScoreError) as exc_info:
        score_run(run_dir=run_dir, no_judge=True, gold_chunks_path=gold)
    message = str(exc_info.value)
    assert "fx-i2" in message
    assert "not a G stratum" in message
    assert not (run_dir / "report.json").exists()
