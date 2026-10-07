"""Golden vector tests for deterministic IR and answer metrics."""

import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from lancet_eval.client import RetrievalSnapshot, StructuredCitation
from lancet_eval.config import repo_root
from lancet_eval.corpus import GoldQuestion
from lancet_eval.metrics import (
    MatchVerdict,
    PaperMetricsResult,
    id_matcher,
    load_gold_chunk_sets,
    paper_metrics,
    paper_question_scores,
    text_matcher,
    abstention_outcome,
    abstention_rate,
    answer_usable,
    boundary_attributable,
    context_precision_at_k,
    em_f1,
    extract_final_answer,
    fact_matches_excerpt,
    final_answer_em,
    gold_contained,
    hits_at_k,
    mrr_at_k,
    ndcg_at_k,
    null_abstention_correct,
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


# --- D-70/D-71/D-72/D-74: final-answer extraction and lenient metrics ---


def _null_question(question_id: str = "null-1") -> GoldQuestion:
    return GoldQuestion(
        question_id=question_id,
        question="Is there a fact for this?",
        question_type="null_query",
        gold_facts=[],
        gold_answer="",
        evidence_list=[],
    )


def _yes_no_question(gold_answer: str, question_id: str = "q1") -> GoldQuestion:
    return GoldQuestion(
        question_id=question_id,
        question="Does X hold?",
        question_type="comparison_query",
        gold_facts=["Some supporting fact."],
        gold_answer=gold_answer,
        evidence_list=[{"title": "Doc", "fact": "Some supporting fact."}],
    )


def test_extract_final_answer_basic_yes() -> None:
    assert extract_final_answer("Some explanation. [1]\nAnswer: Yes") == "yes"


def test_extract_final_answer_strips_bold_marker_on_label() -> None:
    assert extract_final_answer("Explanation.\n**Answer:** Yes") == "yes"


def test_extract_final_answer_strips_bold_marker_on_label_and_value() -> None:
    assert extract_final_answer("Explanation.\n**Answer**: **Yes**") == "yes"


def test_extract_final_answer_strips_citation_markers() -> None:
    assert extract_final_answer("Explanation. [1]\nAnswer: Yes [1]") == "yes"


def test_extract_final_answer_last_line_wins() -> None:
    text = "Draft thought.\nAnswer: No\nMore reasoning.\nAnswer: Yes"
    assert extract_final_answer(text) == "yes"


def test_extract_final_answer_missing_line_is_none() -> None:
    assert extract_final_answer("No answer line here at all.") is None


def test_extract_final_answer_empty_after_label_is_none() -> None:
    assert extract_final_answer("Explanation.\nAnswer:") is None


def test_extract_final_answer_none_input_is_none() -> None:
    assert extract_final_answer(None) is None


def test_gold_contained_whole_token_no_does_not_match_inside_not_or_know() -> None:
    assert gold_contained("no", "I do not know") is False


def test_gold_contained_whole_token_no_matches_standalone_word() -> None:
    assert gold_contained("no", "The answer is no.") is True


def test_answer_usable_loophole_closed_by_extracted_line_only() -> None:
    # Full explanation says "yes" but the final line says "No" — (e) must be
    # judged on the extracted line only, closing the yes/no loophole.
    q = _yes_no_question(gold_answer="Yes")
    answer = "The evidence strongly suggests yes based on the sources. [1]\nAnswer: No"
    assert answer_usable(q, answer) is False


def test_answer_usable_true_when_extracted_line_contains_gold() -> None:
    q = _yes_no_question(gold_answer="Yes")
    answer = "Explanation of the evidence. [1]\nAnswer: Yes"
    assert answer_usable(q, answer) is True


def test_answer_usable_false_when_line_missing() -> None:
    q = _yes_no_question(gold_answer="Yes")
    assert answer_usable(q, "No answer line was produced.") is False


def test_final_answer_em_true_when_extracted_line_equals_gold() -> None:
    q = _yes_no_question(gold_answer="Yes")
    outcome = final_answer_em(q, "Explanation. [1]\nAnswer: Yes")
    assert outcome.score == 1.0


def test_final_answer_em_false_when_extracted_line_differs() -> None:
    q = _yes_no_question(gold_answer="Yes")
    outcome = final_answer_em(q, "Explanation. [1]\nAnswer: No")
    assert outcome.score == 0.0


def test_final_answer_em_missing_line_scores_zero_and_flags_missing() -> None:
    q = _yes_no_question(gold_answer="Yes")
    outcome = final_answer_em(q, "No answer line was produced.")
    assert outcome.score == 0.0
    assert outcome.detail.get("final_answer_missing") == 1.0


def test_null_abstention_correct_true_on_insufficient_information() -> None:
    q = _null_question()
    answer = "I checked the evidence.\nAnswer: Insufficient information"
    outcome = null_abstention_correct(q, answer)
    assert outcome.score == 1.0


def test_null_abstention_correct_false_on_confident_answer() -> None:
    q = _null_question()
    outcome = null_abstention_correct(q, "I checked the evidence.\nAnswer: Yes")
    assert outcome.score == 0.0


def test_null_abstention_correct_raises_on_non_null_question() -> None:
    q = _yes_no_question(gold_answer="Yes")
    with pytest.raises(ValueError, match="null"):
        null_abstention_correct(q, "Answer: Yes")


def test_em_f1_and_abstention_rate_unchanged_by_d70() -> None:
    """D-70: em_f1 and abstention_rate stay byte-identical bodies — smoke-check
    their existing behavior still holds after this module gained new siblings."""
    assert em_f1("Yes", "Yes") == (1.0, 1.0)
    q = _null_question()
    outcome = abstention_rate(q, "Insufficient information here.")
    assert outcome.score == 1.0


# D-95 (06.3.4.1-29): the engine writes `Answer: <final_answer>` as the last line of the
# answer text. The literal below is shared with the Rust test
# `d95_rendered_answer_ends_with_a_line_start_answer_line`; `extract_final_answer` is
# unchanged and reads it.
_D95_PROSE = "The articles name ChatGPT as the chatbot they compare [1]."
_D95_RENDERED = _D95_PROSE + "\nAnswer: ChatGPT"


def test_extract_final_answer_reads_the_d95_rendered_line() -> None:
    assert extract_final_answer(_D95_RENDERED) == "chatgpt"
    assert extract_final_answer(_D95_PROSE) is None


def test_extract_final_answer_reads_the_d95_line_after_a_kept_bracketed_answer() -> None:
    # The engine keeps a model-written Answer segment that carries a marker and still renders
    # its own line; the last line-start match wins.
    text = "The source says so [1]. Answer: ChatGPT [1]\nAnswer: ChatGPT"
    assert extract_final_answer(text) == "chatgpt"


def test_extract_final_answer_still_misses_an_inline_only_answer() -> None:
    # The committed rule is unchanged (drive 1's reading stands, D-87a): an inline
    # `... Answer: X` with no line start is a miss.
    assert extract_final_answer("The source says so [1]. Answer: ChatGPT") is None


# --- D-102 paper-convention metrics (06.3.5-07) -------------------------------------

GOLDEN_PATH = (
    repo_root()
    / "eval"
    / "tests"
    / "fixtures"
    / "multihop_rag_calculate_metrics_golden.json"
)
OFFICIAL_COMMIT = "c1c1287aa60a94acf9c4d20c891c9cd611a0f6e8"


def _golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _gold_chunks_path() -> Path:
    matches = list(
        repo_root().glob(
            ".planning/phases/06.3.4.1-*/diagnostic/post-reconcile/gold_chunks.jsonl"
        )
    )
    assert len(matches) == 1
    return matches[0]


def _textbook_ap(ranked_texts: list[str], facts: list[str]) -> float:
    """Cumulative distinct facts found over the rank: NOT the official arithmetic."""

    def strip(s: str) -> str:
        return s.replace(" ", "").replace("\n", "")

    gold = [strip(f) for f in facts]
    found: set[str] = set()
    total = 0.0
    for rank, text in enumerate(ranked_texts[:10], start=1):
        hit = [g for g in gold if g in strip(text)]
        if hit:
            found.update(hit)
            total += len(found) / rank
    return total / min(len(gold), 10)


def test_golden_fixture_header_names_the_official_commit_and_file_hash() -> None:
    header = _golden()["header"]
    assert header["official_commit"] == OFFICIAL_COMMIT
    assert header["official_repo"] == "yixuantt/MultiHop-RAG"
    assert header["official_file"] == "retrieval_evaluate.py"
    assert re.fullmatch(r"[0-9a-f]{64}", header["official_file_sha256"])


def test_golden_fixture_holds_the_required_special_cases() -> None:
    cases = _golden()["cases"]
    assert len(cases) >= 200
    kinds = {c["kind"] for c in cases}
    assert {"negative_control", "empty_gold_unit", "rank_11"} <= kinds
    empty = next(c for c in cases if c["kind"] == "empty_gold_unit")
    assert any(not s for s in empty["gold_id_sets"])
    assert sum(1 for c in cases if c["official"]["hit4"] > 0) > 20
    assert sum(1 for c in cases if c["official"]["map"] > 0) > 20


def test_paper_question_scores_equals_official_in_id_form_on_every_case() -> None:
    for case in _golden()["cases"]:
        gold = [frozenset(s) for s in case["gold_id_sets"]]
        got = paper_question_scores(case["ranked_ids"], gold, id_matcher)
        want = case["official"]
        assert float(got["hit4"]) == want["hit4"], case["id"]
        assert float(got["hit10"]) == want["hit10"], case["id"]
        assert got["rr"] == pytest.approx(want["mrr"], abs=1e-12), case["id"]
        assert got["ap"] == pytest.approx(want["map"], abs=1e-12), case["id"]


def test_paper_question_scores_equals_official_in_text_form_on_every_case() -> None:
    for case in _golden()["cases"]:
        got = paper_question_scores(
            case["ranked_texts"], case["facts"], text_matcher
        )
        want = case["official"]
        assert float(got["hit4"]) == want["hit4"], case["id"]
        assert float(got["hit10"]) == want["hit10"], case["id"]
        assert got["rr"] == pytest.approx(want["mrr"], abs=1e-12), case["id"]
        assert got["ap"] == pytest.approx(want["map"], abs=1e-12), case["id"]


def test_negative_control_textbook_ap_differs_from_the_official_value() -> None:
    case = next(c for c in _golden()["cases"] if c["kind"] == "negative_control")
    gold = [frozenset(s) for s in case["gold_id_sets"]]
    harness = paper_question_scores(case["ranked_ids"], gold, id_matcher)["ap"]
    textbook = _textbook_ap(case["ranked_texts"], case["facts"])
    assert abs(textbook - case["official"]["map"]) > 1e-6
    assert case["textbook_ap"] == pytest.approx(textbook, abs=1e-12)
    assert harness == pytest.approx(case["official"]["map"], abs=1e-12)
    assert abs(harness - textbook) > 1e-6


def test_paper_question_scores_hits_at_4_on_a_parsed_ranking() -> None:
    snapshot = RetrievalSnapshot.model_validate(
        {
            "retrieval_mode": "hybrid",
            "candidate_limit": 32,
            "final_limit": 8,
            "pre_truncation_ranking": [
                {"chunk_id": f"d{i}:0", "document_id": f"d{i}", "fused_rank": i}
                for i in range(1, 7)
            ],
        }
    )
    ranked = [c.chunk_id for c in snapshot.pre_truncation_ranking]
    hit = paper_question_scores(ranked, [frozenset({"d3:0"})], id_matcher)
    assert hit["hit4"] is True
    assert hit["rr"] == pytest.approx(1 / 3)
    miss = paper_question_scores(ranked, [frozenset({"zz:0"})], id_matcher)
    assert miss["hit4"] is False
    assert miss["rr"] == 0


def test_an_empty_gold_unit_never_matches_but_counts_in_the_divisor() -> None:
    got = paper_question_scores(["c1"], [frozenset({"c1"}), frozenset()], id_matcher)
    assert got["ap"] == pytest.approx(0.5)
    assert got["hit4"] is True


def test_ranks_beyond_ten_never_count() -> None:
    ranked = [f"x{i}" for i in range(10)] + ["gold"]
    got = paper_question_scores(ranked, [frozenset({"gold"})], id_matcher)
    assert got["hit10"] is False
    assert got["hit4"] is False
    assert got["rr"] == 0
    assert got["ap"] == 0
    at_ten = [f"x{i}" for i in range(9)] + ["gold"]
    got = paper_question_scores(at_ten, [frozenset({"gold"})], id_matcher)
    assert got["hit10"] is True
    assert got["hit4"] is False
    assert got["rr"] == pytest.approx(0.1)


def test_ap_divisor_is_capped_at_ten_gold_units() -> None:
    gold = [frozenset({f"g{i}"}) for i in range(12)]
    got = paper_question_scores(["g0"], gold, id_matcher)
    assert got["ap"] == pytest.approx(1.0 / 10)


def test_a_chunk_holding_two_new_facts_credits_both_at_its_rank() -> None:
    gold = [frozenset({"a"}), frozenset({"a", "b"})]
    got = paper_question_scores(["z", "a", "b"], gold, id_matcher)
    # rank 2: facts 0 and 1 are both new -> 2/2; rank 3: no new fact -> 0
    assert got["ap"] == pytest.approx((2 / 2) / 2)


def test_paper_question_scores_rejects_an_empty_gold_list() -> None:
    with pytest.raises(ValueError, match="gold"):
        paper_question_scores(["a"], [], id_matcher)


def test_text_matcher_strips_every_space_and_newline_on_both_sides() -> None:
    assert text_matcher("the quick  brown\nfox jumps", "quick brown fox")
    assert text_matcher("thequickbrownfox", "the quick\nbrown fox")
    assert not text_matcher("The Quick", "the quick")  # case-sensitive, like the script
    assert id_matcher("c1", frozenset({"c1", "c2"}))
    assert not id_matcher("c3", frozenset({"c1", "c2"}))


def test_load_gold_chunk_sets_over_the_real_table() -> None:
    path = _gold_chunks_path()
    sets = load_gold_chunk_sets(path)
    assert len(sets) == 447
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
    split_rows = [r for r in rows if r["state"] == "split_across_chunks"]
    assert split_rows
    for r in split_rows:
        assert sets[r["question_id"]][r["evidence_index"]] == frozenset()
    in_chunk = [r for r in rows if r["state"] == "in_chunk"]
    for r in in_chunk:
        assert sets[r["question_id"]][r["evidence_index"]] == frozenset(r["chunk_ids"])
    assert sum(len(v) for v in sets.values()) == len(rows)


def test_load_gold_chunk_sets_orders_by_evidence_index_and_fails_closed(
    tmp_path: Path,
) -> None:
    def row(qid: str, idx: int, state: str, ids: list[str]) -> str:
        return json.dumps(
            {
                "question_id": qid,
                "evidence_index": idx,
                "title": "t",
                "document_id": "d",
                "state": state,
                "chunk_ids": ids,
            }
        )

    ok = tmp_path / "ok.jsonl"
    ok.write_text(
        "\n".join(
            [
                row("q1", 1, "split_across_chunks", []),
                row("q1", 0, "in_chunk", ["a:0", "a:1"]),
                row("q2", 0, "in_chunk", ["b:0"]),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    sets = load_gold_chunk_sets(ok)
    assert sets["q1"] == [frozenset({"a:0", "a:1"}), frozenset()]
    assert sets["q2"] == [frozenset({"b:0"})]

    bad_state = tmp_path / "bad_state.jsonl"
    bad_state.write_text(row("q1", 0, "mystery", []) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="state"):
        load_gold_chunk_sets(bad_state)

    duplicate = tmp_path / "dup.jsonl"
    duplicate.write_text(
        row("q1", 0, "in_chunk", ["a"]) + "\n" + row("q1", 0, "in_chunk", ["b"]) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_gold_chunk_sets(duplicate)


def test_paper_metrics_averages_and_rejects_an_empty_list() -> None:
    scores = [
        {"hit4": True, "hit10": True, "rr": 1.0, "ap": 0.5},
        {"hit4": False, "hit10": True, "rr": 0.25, "ap": 0.25},
        {"hit4": False, "hit10": False, "rr": 0.0, "ap": 0.0},
        {"hit4": True, "hit10": True, "rr": 0.5, "ap": 0.25},
    ]
    got = paper_metrics(scores)
    assert got == {
        "paper_hits_at_4": pytest.approx(0.5),
        "paper_hits_at_10": pytest.approx(0.75),
        "paper_mrr_at_10": pytest.approx(0.4375),
        "paper_map_at_10": pytest.approx(0.25),
    }
    with pytest.raises(ValueError, match="empty"):
        paper_metrics([])


def test_paper_metrics_result_is_frozen_and_pins_the_official_commit() -> None:
    result = PaperMetricsResult(
        arm="hybrid",
        official_commit=OFFICIAL_COMMIT,
        matching_rule="chunk_id_via_gold_chunks",
        n_queries=10,
        n_excluded=1,
        paper_hits_at_4=0.5,
        paper_hits_at_10=0.7,
        paper_mrr_at_10=0.4,
        paper_map_at_10=0.3,
    )
    with pytest.raises(ValueError, match="frozen"):
        result.n_queries = 11  # type: ignore[misc]
    with pytest.raises(ValueError, match="official_commit"):
        PaperMetricsResult(
            arm="hybrid",
            official_commit="deadbeef",  # type: ignore[arg-type]
            matching_rule="chunk_id_via_gold_chunks",
            n_queries=1,
            n_excluded=0,
            paper_hits_at_4=0.0,
            paper_hits_at_10=0.0,
            paper_mrr_at_10=0.0,
            paper_map_at_10=0.0,
        )
    with pytest.raises(ValueError, match="paper_hits_at_4"):
        PaperMetricsResult(
            arm="hybrid",
            official_commit=OFFICIAL_COMMIT,
            matching_rule="store_text_official",
            n_queries=1,
            n_excluded=0,
            paper_hits_at_4=1.5,
            paper_hits_at_10=0.0,
            paper_mrr_at_10=0.0,
            paper_map_at_10=0.0,
        )


def test_the_official_script_is_not_tracked_in_the_repository() -> None:
    res = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=repo_root(),
        shell=False,
        check=True,
    )
    tracked = [p for p in res.stdout.splitlines() if p.endswith("retrieval_evaluate.py")]
    assert tracked == []
