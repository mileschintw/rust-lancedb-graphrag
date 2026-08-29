"""Golden vector tests for deterministic IR and answer metrics."""

import math
import subprocess
import sys
from dataclasses import dataclass

import pytest

from lancet_eval.client import StructuredCitation
from lancet_eval.corpus import GoldQuestion
from lancet_eval.metrics import (
    MatchVerdict,
    abstention_outcome,
    boundary_attributable,
    context_precision_at_k,
    em_f1,
    fact_matches_excerpt,
    hits_at_k,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)


@dataclass
class MockNotice:
    typed_code: int


def _make_citation(
    chunk_id: str,
    rank: int,
    excerpt: str,
    is_truncated: bool = False,
) -> StructuredCitation:
    return StructuredCitation(
        chunk_id=chunk_id,
        document_id="doc-1",
        title="Doc Title",
        section_path="/sec",
        excerpt=excerpt,
        is_truncated=is_truncated,
        score=0.9,
        rank=rank,
        content_type="text/markdown",
    )


def test_network_freedom_import_isolated() -> None:
    code = (
        "import sys, lancet_eval.metrics; "
        "forbidden = {'httpx', 'requests', 'urllib.request', 'http.client', 'socket'}; "
        "loaded = set(sys.modules.keys()); "
        "found = forbidden.intersection(loaded); "
        "assert not found, f'Forbidden network modules loaded: {found}'"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, f"Import loaded forbidden modules:\n{res.stderr}"


def test_matching_verdicts_and_boundary_diagnostic() -> None:
    fact_long = (
        "The quick brown fox jumps over the lazy dog and runs across "
        "the wide open meadow into the sunset."
    )
    assert len(fact_long) > 60

    # 1. Exact containment -> HIT
    chunk_hit = _make_citation("c1", 1, f"Notice: {fact_long} Indeed.")
    assert fact_matches_excerpt(fact_long, chunk_hit) == MatchVerdict.HIT

    # 2. Complete absence -> MISS
    chunk_miss = _make_citation("c2", 2, "Completely unrelated text about cats.")
    assert fact_matches_excerpt(fact_long, chunk_miss) == MatchVerdict.MISS
    assert not boundary_attributable(fact_long, chunk_miss)

    # 3. Boundary straddle above 60 char floor -> MISS + boundary_attributable
    min_len = max(60, int(math.ceil(0.5 * len(fact_long))))
    prefix_str = fact_long[:65].strip()
    assert len(prefix_str) >= min_len
    chunk_boundary = _make_citation(
        "c3", 3, f"Earlier context ending with {prefix_str}"
    )
    assert fact_matches_excerpt(fact_long, chunk_boundary) == MatchVerdict.MISS
    assert boundary_attributable(fact_long, chunk_boundary)

    # 4. Boundary straddle below 60 char floor -> MISS but NOT boundary_attributable
    fact_short = "Small short fact here."
    chunk_short_boundary = _make_citation("c4", 4, f"Ending with {fact_short[:15]}")
    assert fact_matches_excerpt(fact_short, chunk_short_boundary) == MatchVerdict.MISS
    assert not boundary_attributable(fact_short, chunk_short_boundary)

    # 5. Truncated chunk -> UNDECIDABLE, no boundary diagnostic
    chunk_trunc = _make_citation("c5", 5, f"Prefix: {fact_long}", is_truncated=True)
    assert fact_matches_excerpt(fact_long, chunk_trunc) == MatchVerdict.UNDECIDABLE
    assert not boundary_attributable(fact_long, chunk_trunc)


def test_recall_at_k_and_overlength_exclusion() -> None:
    q = GoldQuestion(
        question_id="q1",
        question="Question 1?",
        gold_facts=[
            "First normal fact.",
            "Second normal fact.",
            "X" * 538,  # Overlength fact
        ],
        evidence_list=[{"fact": "f1"}, {"fact": "f2"}, {"fact": "f3"}],
    )

    # Chunk matching first fact at rank 1, second fact at rank 3
    retrieved = [
        _make_citation("c1", 1, "Context with First normal fact. inside."),
        _make_citation("c2", 3, "Context with Second normal fact. inside."),
    ]

    res = recall_at_k(q, retrieved, k=4, chunk_size=500)
    assert res.status == "ok"
    # Denominator is 2 because the 538 char fact is excluded
    assert res.score == 1.0
    assert res.detail["hits"] == 2.0
    assert res.detail["denominator"] == 2.0
    assert res.detail["gold_facts_longer_than_chunk"] == 1.0

    # At k=2, only rank 1 is captured -> score = 1/2 = 0.5
    res_k2 = recall_at_k(q, retrieved, k=2, chunk_size=500)
    assert res_k2.score == 0.5
    assert res_k2.detail["hits"] == 1.0


def test_context_precision_at_k_denominator_is_returned_chunks() -> None:
    q = GoldQuestion(
        question_id="q1",
        question="Question 1?",
        gold_facts=["Fact alpha.", "Fact beta."],
        evidence_list=[{"fact": "Fact alpha."}],
    )

    # Response returning 2 chunks at k=4, 1 match -> precision = 1/2 = 0.5
    retrieved_2 = [
        _make_citation("c1", 1, "Has Fact alpha. inside."),
        _make_citation("c2", 2, "No match here."),
    ]
    res_2 = context_precision_at_k(q, retrieved_2, k=4)
    assert res_2.score == 0.5
    assert res_2.detail["returned_chunks"] == 2.0

    # Response returning 4 chunks at k=4, 1 match -> precision = 1/4 = 0.25
    retrieved_4 = [
        _make_citation("c1", 1, "Has Fact alpha. inside."),
        _make_citation("c2", 2, "No match here."),
        _make_citation("c3", 3, "No match here."),
        _make_citation("c4", 4, "No match here."),
    ]
    res_4 = context_precision_at_k(q, retrieved_4, k=4)
    assert res_4.score == 0.25
    assert res_4.detail["returned_chunks"] == 4.0

    # Context precision is unaffected by gold facts longer than chunk
    q_overlength = GoldQuestion(
        question_id="q1",
        question="Question 1?",
        gold_facts=["Fact alpha.", "Z" * 600],
        evidence_list=[{"fact": "Fact alpha."}],
    )
    res_over = context_precision_at_k(q_overlength, retrieved_2, k=4)
    assert res_over.score == 0.5


def test_mrr_at_k_and_discriminating_first_rank() -> None:
    q = GoldQuestion(
        question_id="q1",
        question="Question?",
        gold_facts=["Fact 1", "Fact 2", "Fact 3", "Fact 4"],
        evidence_list=[{"fact": "Fact 1"}],
    )

    # Match at rank 3 -> MRR = 1/3
    retrieved_rank3 = [
        _make_citation("c1", 1, "Irrelevant 1"),
        _make_citation("c2", 2, "Irrelevant 2"),
        _make_citation("c3", 3, "Has Fact 1"),
    ]
    res = mrr_at_k(q, retrieved_rank3, k=10)
    assert abs(res.score - (1.0 / 3.0)) < 1e-9

    # MRR does not distinguish 1 match at rank 1 from 4 matches starting at rank 1
    retrieved_1_of_4 = [_make_citation("c1", 1, "Has Fact 1")]
    retrieved_4_of_4 = [
        _make_citation("c1", 1, "Has Fact 1"),
        _make_citation("c2", 2, "Has Fact 2"),
        _make_citation("c3", 3, "Has Fact 3"),
        _make_citation("c4", 4, "Has Fact 4"),
    ]
    assert mrr_at_k(q, retrieved_1_of_4, k=10).score == 1.0
    assert mrr_at_k(q, retrieved_4_of_4, k=10).score == 1.0


def test_ndcg_at_k_worked_vector_and_gold_set_idcg() -> None:
    # 2 gold facts, matches at ranks 1 and 3
    q = GoldQuestion(
        question_id="q1",
        question="Question?",
        gold_facts=["Fact 1", "Fact 2"],
        evidence_list=[{"fact": "Fact 1"}, {"fact": "Fact 2"}],
    )

    retrieved = [
        _make_citation("c1", 1, "Has Fact 1"),
        _make_citation("c2", 2, "Irrelevant"),
        _make_citation("c3", 3, "Has Fact 2"),
    ]

    expected_ndcg = (1.0 / math.log2(2) + 1.0 / math.log2(4)) / (
        1.0 / math.log2(2) + 1.0 / math.log2(3)
    )

    res = ndcg_at_k(q, retrieved, k=4, chunk_size=500)
    assert abs(res.score - expected_ndcg) < 1e-9

    # Perfect run yields exactly 1.0
    retrieved_perfect = [
        _make_citation("c1", 1, "Has Fact 1"),
        _make_citation("c2", 2, "Has Fact 2"),
    ]
    assert ndcg_at_k(q, retrieved_perfect, k=4, chunk_size=500).score == 1.0

    # 1 of 4 gold facts yields strictly less than 1.0
    q4 = GoldQuestion(
        question_id="q4",
        question="Question 4?",
        gold_facts=["F1", "F2", "F3", "F4"],
        evidence_list=[{"fact": "F1"}],
    )
    retrieved_1 = [_make_citation("c1", 1, "Has F1")]
    res_1_of_4 = ndcg_at_k(q4, retrieved_1, k=4, chunk_size=500)
    assert res_1_of_4.score < 1.0


def test_squad_em_f1_token_overlap() -> None:
    # Exact match after lowercasing and article stripping
    em, f1 = em_f1("The Sam Altman", "sam altman")
    assert em == 1.0
    assert f1 == 1.0

    # Partial overlap
    em_p, f1_p = em_f1("The CEO is Sam Altman.", "Sam Altman")
    assert em_p == 0.0
    assert f1_p > 0.0

    # Mismatch with shared token: Sam Altman vs Sam Bankman-Fried
    em_m, f1_m = em_f1("Sam Altman", "Sam Bankman-Fried")
    assert em_m == 0.0
    assert f1_m < 1.0
    assert f1_m > 0.0


def test_null_query_raises_on_retrieval_metrics() -> None:
    null_q = GoldQuestion(
        question_id="q_null",
        question="Unanswerable question?",
        gold_facts=[],
        evidence_list=[],
    )
    assert null_q.is_null

    retrieved = [_make_citation("c1", 1, "Some text")]

    with pytest.raises(ValueError, match="Null-slice"):
        recall_at_k(null_q, retrieved)

    with pytest.raises(ValueError, match="Null-slice"):
        hits_at_k(null_q, retrieved)

    with pytest.raises(ValueError, match="Null-slice"):
        context_precision_at_k(null_q, retrieved)

    with pytest.raises(ValueError, match="Null-slice"):
        mrr_at_k(null_q, retrieved)

    with pytest.raises(ValueError, match="Null-slice"):
        ndcg_at_k(null_q, retrieved)


def test_abstention_outcomes_on_null_query() -> None:
    null_q = GoldQuestion(
        question_id="q_null",
        question="Unanswerable question?",
        gold_facts=[],
        evidence_list=[],
    )

    # 1. Notice code 1 (NO_EVIDENCE) -> correct_abstention
    assert (
        abstention_outcome(null_q, [MockNotice(1)], "No answer.", [])
        == "correct_abstention"
    )

    # 2. Refusal phrase in answer -> correct_abstention
    assert (
        abstention_outcome(
            null_q, [], "There is insufficient information to answer.", []
        )
        == "correct_abstention"
    )

    # 3. Confident answer with citations -> hallucinated_on_null
    assert (
        abstention_outcome(null_q, [], "The founder is John Doe.", ["citation-1"])
        == "hallucinated_on_null"
    )


def test_snapshot_absent_vs_empty_distinction() -> None:
    q = GoldQuestion(
        question_id="q1",
        question="Q?",
        gold_facts=["Fact 1"],
        evidence_list=[{"fact": "Fact 1"}],
    )

    # Absent snapshot (None) -> status="skipped"
    res_absent = recall_at_k(q, None)
    assert res_absent.status == "skipped"
    assert res_absent.score is None

    # Empty retrieved_chunks list ([]) -> status="ok", score=0.0
    res_empty = recall_at_k(q, [])
    assert res_empty.status == "ok"
    assert res_empty.score == 0.0


def test_rank_le_k_rule_versus_list_index() -> None:
    q = GoldQuestion(
        question_id="q1",
        question="Q?",
        gold_facts=["Fact 1"],
        evidence_list=[{"fact": "Fact 1"}],
    )

    # Matching chunk is 2nd in list but has rank 9 -> at k=4, scores 0.0
    retrieved_rank9 = [
        _make_citation("c1", 1, "Irrelevant"),
        _make_citation("c2", 9, "Has Fact 1"),
    ]
    assert recall_at_k(q, retrieved_rank9, k=4).score == 0.0

    # Matching chunk is 2nd in list with rank 3 -> at k=4, scores 1.0
    retrieved_rank3 = [
        _make_citation("c1", 1, "Irrelevant"),
        _make_citation("c2", 3, "Has Fact 1"),
    ]
    assert recall_at_k(q, retrieved_rank3, k=4).score == 1.0


def test_undecidable_rate_exceeding_threshold_fails_loud() -> None:
    q = GoldQuestion(
        question_id="q1",
        question="Q?",
        gold_facts=["Fact 1"],
        evidence_list=[{"fact": "Fact 1"}],
    )

    # List of 100 chunks with 2 truncated (2% > 1% threshold)
    retrieved_truncated = [
        _make_citation(f"c{i}", i, f"Text {i}", is_truncated=(i <= 2))
        for i in range(1, 101)
    ]
    res = recall_at_k(q, retrieved_truncated, k=100)
    assert res.status == "error"
    assert res.score is None
    assert "Undecidable rate" in res.reason
    assert "exceeds 1%" in res.reason


def test_metrics_read_retrieved_chunks_not_cited_subset() -> None:
    q = GoldQuestion(
        question_id="q1",
        question="Q?",
        gold_facts=["Secret Gold Fact"],
        evidence_list=[{"fact": "Secret Gold Fact"}],
    )

    # retrieved_chunks does NOT contain Secret Gold Fact
    retrieved_chunks = [
        _make_citation("c1", 1, "Unrelated chunk excerpt 1"),
        _make_citation("c2", 2, "Unrelated chunk excerpt 2"),
    ]

    assert recall_at_k(q, retrieved_chunks, k=4).score == 0.0
    assert context_precision_at_k(q, retrieved_chunks, k=4).score == 0.0
    assert mrr_at_k(q, retrieved_chunks, k=10).score == 0.0
    assert ndcg_at_k(q, retrieved_chunks, k=4).score == 0.0
    assert hits_at_k(q, retrieved_chunks, k=4).score == 0.0


def test_rank_wire_order_tie_break() -> None:
    q = GoldQuestion(
        question_id="q1",
        question="Q?",
        gold_facts=["Fact alpha", "Fact beta"],
        evidence_list=[{"fact": "Fact alpha"}, {"fact": "Fact beta"}],
    )

    # First entry in list has rank 5, second has rank 2 (matching alpha),
    # third has rank 2 (matching beta)
    retrieved = [
        _make_citation("c1", 5, "Has Fact ignored at rank 5"),
        _make_citation("c2", 2, "Has Fact alpha"),
        _make_citation("c3", 2, "Has Fact beta"),
    ]

    # At k=3, only rank 2 entries are in top-k
    res = recall_at_k(q, retrieved, k=3)
    assert res.score == 1.0
    assert res.detail["hits"] == 2.0

    # First match in MRR is at rank 2
    res_mrr = mrr_at_k(q, retrieved, k=10)
    assert res_mrr.score == 0.5
