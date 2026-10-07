"""Deterministic evaluation metrics computed from gold labels without LLMs."""

from __future__ import annotations

import json
import math
import re
import string
from collections import Counter
from collections.abc import Callable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from lancet_eval.client import StructuredCitation
from lancet_eval.corpus import GoldQuestion


class _AnswerRecord(Protocol):
    """What the abstention predicate reads: a `RunRecord` or a look-alike."""

    @property
    def answer(self) -> str | None: ...

    @property
    def notices(self) -> Sequence[Any]: ...


class MatchVerdict(StrEnum):
    """Verdict of matching a gold fact against a retrieved chunk excerpt."""

    HIT = "hit"
    MISS = "miss"
    UNDECIDABLE = "undecidable"


class MetricOutcome(BaseModel):
    """Result of computing a metric over a single query or dataset."""

    model_config = ConfigDict(extra="forbid")

    status: str = "ok"  # "ok", "skipped", "error"
    score: float | None = None
    reason: str | None = None
    detail: dict[str, float] = Field(default_factory=dict)
    n: int = 0


def normalize_ws(text: str) -> str:
    """Whitespace and case normalization for evidence containment matching."""
    return " ".join(text.split()).lower()


def squad_normalize(text: str) -> str:
    """SQuAD v1.1 text normalization for answer EM and F1 computation."""

    def remove_articles(s: str) -> str:
        return re.sub(r"\b(a|an|the)\b", " ", s)

    def white_space_fix(s: str) -> str:
        return " ".join(s.split())

    def remove_punc(s: str) -> str:
        exclude = set(string.punctuation)
        return "".join(ch for ch in s if ch not in exclude)

    def lower(s: str) -> str:
        return s.lower()

    return white_space_fix(remove_articles(remove_punc(lower(text))))


# D-71 final-answer line: "Answer: <short>", tolerating leading blockquote/emphasis
# markers and surrounding emphasis punctuation. The last match in the text wins
# (D-70/D-74): a model that restates its answer keeps only the final line.
_ANSWER_LINE = re.compile(r"(?im)^[ \t>*_-]*answer[ \t*_]*:[ \t]*(?P<a>.+?)[ \t]*$")
# Inline citation markers like [1], [12] stripped from the extracted answer line
# before normalization (D-70) — they are not part of the short answer itself.
_MARKER = re.compile(r"\[\s*\d+\s*\]")


def extract_final_answer(answer: str | None) -> str | None:
    """Extracts and normalizes the last `Answer: <short>` line from `answer`.

    Stable across `**Answer:**`, `Answer: X [1]`, and repeated Answer lines
    (last one wins). Returns None if no line matches or nothing survives
    normalization (D-70/D-74: this is `final_answer_missing`).
    """
    matches = list(_ANSWER_LINE.finditer(answer or ""))
    if not matches:
        return None
    text = _MARKER.sub("", matches[-1].group("a")).replace("*", "").replace("_", " ")
    norm = squad_normalize(text)
    return norm or None


def gold_contained(gold: str, text: str) -> bool:
    """Whole-token containment of `squad_normalize(gold)` in `squad_normalize(text)`.

    Token-boundary aware, so a gold of "no" never matches inside "not" or
    "know" (D-70) the way a raw substring check would.
    """
    gold_tokens = squad_normalize(gold).split()
    text_tokens = squad_normalize(text).split()
    if not gold_tokens:
        return False
    span = len(gold_tokens)
    return any(
        text_tokens[i : i + span] == gold_tokens
        for i in range(len(text_tokens) - span + 1)
    )


def final_answer_em(question: GoldQuestion, answer: str) -> MetricOutcome:
    """Exact match between the extracted final-answer line and the gold answer (D-70).

    Scores 0.0 with `detail={"final_answer_missing": True}` when no line
    could be extracted — a miss that stays in the denominator (D-74).
    """
    extracted = extract_final_answer(answer)
    if extracted is None:
        return MetricOutcome(
            status="ok",
            score=0.0,
            detail={"final_answer_missing": 1.0},
            n=1,
        )
    score = 1.0 if extracted == squad_normalize(question.gold_answer) else 0.0
    return MetricOutcome(status="ok", score=score, n=1)


def answer_usable(question: GoldQuestion, answer: str) -> bool:
    """Column (e): whether the extracted final-answer line contains the gold answer.

    Judged on the extracted line ONLY, never the full explanation (D-70) — a
    missing line is False, not skipped.
    """
    extracted = extract_final_answer(answer)
    if extracted is None:
        return False
    return gold_contained(question.gold_answer, extracted)


def null_abstention_correct(question: GoldQuestion, answer: str) -> MetricOutcome:
    """Whether the extracted final-answer line correctly abstains (D-72).

    Raises ValueError on a non-null question (same guard as `abstention_outcome`).
    """
    if not question.is_null:
        raise ValueError("null_abstention_correct requires a null question")
    extracted = extract_final_answer(answer)
    score = 1.0 if extracted == "insufficient information" else 0.0
    return MetricOutcome(status="ok", score=score, n=1)


# D-118: the typed NO_EVIDENCE notice code (dimensions.NOTICE_CODE_NO_EVIDENCE); kept
# local so this module stays free of the dimensions import graph.
_NO_EVIDENCE_TYPED_CODE = 1
_ABSTENTION_ANSWER = "insufficient information"
_LEAK_PHRASES = ("insufficient information", "cannot answer")


def _has_no_evidence_notice(record: _AnswerRecord) -> bool:
    return any(
        getattr(n, "typed_code", None) == _NO_EVIDENCE_TYPED_CODE
        or getattr(n, "code", "") == "NO_EVIDENCE"
        for n in record.notices
    )


def is_abstention(record: _AnswerRecord) -> bool:
    """The single abstention predicate (D-118, owner-approved 2026-10-06).

    True when the record carries a NO_EVIDENCE notice (typed code 1 or the string
    code), or when the extracted final `Answer:` line, after the D-70 normalisation,
    equals `insufficient information` (the D-72 equality). It never reads the prose
    fallback of `abstention_outcome`: a hedge such as `Evidence says insufficient
    information` followed by `Answer: Yes` is not an abstention and is counted by
    `abstention_leak` instead. A blank answer without NO_EVIDENCE is not one.

    Args:
        record: Any object with `.answer` (str or None) and `.notices`.

    Returns:
        True when the record abstains.
    """
    if _has_no_evidence_notice(record):
        return True
    return extract_final_answer(record.answer) == _ABSTENTION_ANSWER


def abstention_leak(record: _AnswerRecord) -> bool:
    """True for a non-abstaining record whose prose holds an abstention phrase (D-118).

    The whitespace-normalised, lower-cased answer contains `insufficient information`
    or `cannot answer`, yet `is_abstention` is false: a hedge that goes on to commit.
    It is reported as a count, never used to classify a record.
    """
    if is_abstention(record):
        return False
    text = normalize_ws(record.answer or "")
    return any(phrase in text for phrase in _LEAK_PHRASES)


def fact_matches_excerpt(fact: str, chunk: StructuredCitation) -> MatchVerdict:
    """Primary evidence-matching rule using normalized containment."""
    if chunk.is_truncated:
        return MatchVerdict.UNDECIDABLE

    norm_fact = normalize_ws(fact)
    norm_excerpt = normalize_ws(chunk.excerpt)

    if norm_fact in norm_excerpt:
        return MatchVerdict.HIT
    return MatchVerdict.MISS


def boundary_attributable(fact: str, chunk: StructuredCitation) -> bool:
    """Diagnostic check for a fact straddling a chunk boundary."""
    if chunk.is_truncated:
        return False

    norm_fact = normalize_ws(fact)
    norm_excerpt = normalize_ws(chunk.excerpt)

    min_len = max(60, int(math.ceil(0.5 * len(norm_fact))))
    if len(norm_fact) < min_len or len(norm_excerpt) < min_len:
        return False

    max_k = min(len(norm_fact), len(norm_excerpt))
    for k in range(min_len, max_k + 1):
        if norm_excerpt.endswith(norm_fact[:k]):
            return True
        if norm_excerpt.startswith(norm_fact[-k:]):
            return True

    return False


def gold_fact_longer_than_chunk(fact: str, chunk_size: int = 500) -> bool:
    """True if fact length exceeds chunk size and cannot fit in any single chunk."""
    return len(fact) > chunk_size


def _check_undecidable_rate(
    undecidable_count: int, total_examined: int
) -> MetricOutcome | None:
    if total_examined > 0:
        rate = undecidable_count / total_examined
        if rate > 0.01:
            return MetricOutcome(
                status="error",
                reason=(
                    f"Undecidable rate {rate:.2%} exceeds 1% threshold "
                    f"({undecidable_count}/{total_examined} chunks truncated)"
                ),
            )
    return None


def recall_at_k(
    question: GoldQuestion,
    retrieved_chunks: list[StructuredCitation] | None,
    k: int = 4,
    chunk_size: int = 500,
) -> MetricOutcome:
    """Compute evidence recall@k for a single question."""
    if question.is_null:
        raise ValueError("Null-slice question cannot enter retrieval metrics")

    if retrieved_chunks is None:
        return MetricOutcome(
            status="skipped",
            reason="no retrieval snapshot on the response",
            n=len(question.gold_facts),
        )

    # Exclude gold facts longer than chunk size from recall denominator
    eligible_facts = [
        f for f in question.gold_facts if not gold_fact_longer_than_chunk(f, chunk_size)
    ]
    excluded_facts_count = len(question.gold_facts) - len(eligible_facts)

    if not eligible_facts:
        return MetricOutcome(
            status="skipped",
            reason="all gold facts exceed corpus chunk size",
            detail={"gold_facts_longer_than_chunk": float(excluded_facts_count)},
            n=len(question.gold_facts),
        )

    top_k = [c for c in retrieved_chunks if c.rank <= k]

    undecidable_count = sum(1 for c in top_k if c.is_truncated)
    err = _check_undecidable_rate(undecidable_count, len(top_k))
    if err is not None:
        return err

    matched_facts = 0
    boundary_misses = 0

    for fact in eligible_facts:
        hit = False
        for c in top_k:
            if fact_matches_excerpt(fact, c) == MatchVerdict.HIT:
                hit = True
                break
        if hit:
            matched_facts += 1
        else:
            if any(boundary_attributable(fact, c) for c in top_k):
                boundary_misses += 1

    score = matched_facts / len(eligible_facts)
    return MetricOutcome(
        status="ok",
        score=score,
        detail={
            "hits": float(matched_facts),
            "denominator": float(len(eligible_facts)),
            "boundary_attributable_misses": float(boundary_misses),
            "undecidable_retrieved_chunks": float(undecidable_count),
            "gold_facts_longer_than_chunk": float(excluded_facts_count),
        },
        n=len(eligible_facts),
    )


def hits_at_k(
    question: GoldQuestion,
    retrieved_chunks: list[StructuredCitation] | None,
    k: int = 4,
) -> MetricOutcome:
    """Compute binary hits@k for a single question."""
    if question.is_null:
        raise ValueError("Null-slice question cannot enter retrieval metrics")

    if retrieved_chunks is None:
        return MetricOutcome(
            status="skipped",
            reason="no retrieval snapshot on the response",
            n=len(question.gold_facts),
        )

    top_k = [c for c in retrieved_chunks if c.rank <= k]
    undecidable_count = sum(1 for c in top_k if c.is_truncated)
    err = _check_undecidable_rate(undecidable_count, len(top_k))
    if err is not None:
        return err

    has_hit = any(
        fact_matches_excerpt(fact, c) == MatchVerdict.HIT
        for fact in question.gold_facts
        for c in top_k
    )

    score = 1.0 if has_hit else 0.0
    return MetricOutcome(
        status="ok",
        score=score,
        detail={
            "hits": 1.0 if has_hit else 0.0,
            "denominator": 1.0,
            "undecidable_retrieved_chunks": float(undecidable_count),
        },
        n=1,
    )


def context_precision_at_k(
    question: GoldQuestion,
    retrieved_chunks: list[StructuredCitation] | None,
    k: int = 4,
) -> MetricOutcome:
    """Compute context precision@k (denominator is returned chunks at rank<=k)."""
    if question.is_null:
        raise ValueError("Null-slice question cannot enter retrieval metrics")

    if retrieved_chunks is None:
        return MetricOutcome(
            status="skipped",
            reason="no retrieval snapshot on the response",
            n=len(question.gold_facts),
        )

    top_k = [c for c in retrieved_chunks if c.rank <= k]
    undecidable_count = sum(1 for c in top_k if c.is_truncated)
    err = _check_undecidable_rate(undecidable_count, len(top_k))
    if err is not None:
        return err

    if not top_k:
        return MetricOutcome(
            status="ok",
            score=0.0,
            detail={
                "matched_chunks": 0.0,
                "returned_chunks": 0.0,
                "undecidable_retrieved_chunks": 0.0,
            },
            n=0,
        )

    matched_chunks = sum(
        1
        for c in top_k
        if any(
            fact_matches_excerpt(f, c) == MatchVerdict.HIT for f in question.gold_facts
        )
    )

    score = matched_chunks / len(top_k)
    return MetricOutcome(
        status="ok",
        score=score,
        detail={
            "matched_chunks": float(matched_chunks),
            "returned_chunks": float(len(top_k)),
            "undecidable_retrieved_chunks": float(undecidable_count),
        },
        n=len(top_k),
    )


def mrr_at_k(
    question: GoldQuestion,
    retrieved_chunks: list[StructuredCitation] | None,
    k: int = 10,
) -> MetricOutcome:
    """Compute Mean Reciprocal Rank at k for a single question."""
    if question.is_null:
        raise ValueError("Null-slice question cannot enter retrieval metrics")

    if retrieved_chunks is None:
        return MetricOutcome(
            status="skipped",
            reason="no retrieval snapshot on the response",
            n=len(question.gold_facts),
        )

    top_k = [c for c in retrieved_chunks if c.rank <= k]
    undecidable_count = sum(1 for c in top_k if c.is_truncated)
    err = _check_undecidable_rate(undecidable_count, len(top_k))
    if err is not None:
        return err

    first_rank: int | None = None
    for c in top_k:
        if any(
            fact_matches_excerpt(f, c) == MatchVerdict.HIT for f in question.gold_facts
        ):
            first_rank = c.rank
            break

    score = (1.0 / first_rank) if first_rank and first_rank > 0 else 0.0
    return MetricOutcome(
        status="ok",
        score=score,
        detail={
            "first_rank": float(first_rank or 0),
            "undecidable_retrieved_chunks": float(undecidable_count),
        },
        n=1,
    )


def ndcg_at_k(
    question: GoldQuestion,
    retrieved_chunks: list[StructuredCitation] | None,
    k: int = 10,
    chunk_size: int = 500,
) -> MetricOutcome:
    """Compute normalized Discounted Cumulative Gain at k for a single question."""
    if question.is_null:
        raise ValueError("Null-slice question cannot enter retrieval metrics")

    if retrieved_chunks is None:
        return MetricOutcome(
            status="skipped",
            reason="no retrieval snapshot on the response",
            n=len(question.gold_facts),
        )

    eligible_facts = [
        f for f in question.gold_facts if not gold_fact_longer_than_chunk(f, chunk_size)
    ]
    excluded_facts_count = len(question.gold_facts) - len(eligible_facts)

    if not eligible_facts:
        return MetricOutcome(
            status="skipped",
            reason="all gold facts exceed corpus chunk size",
            detail={"gold_facts_longer_than_chunk": float(excluded_facts_count)},
            n=len(question.gold_facts),
        )

    top_k = [c for c in retrieved_chunks if c.rank <= k]
    undecidable_count = sum(1 for c in top_k if c.is_truncated)
    err = _check_undecidable_rate(undecidable_count, len(top_k))
    if err is not None:
        return err

    # Compute DCG
    dcg = 0.0
    for c in top_k:
        if any(fact_matches_excerpt(f, c) == MatchVerdict.HIT for f in eligible_facts):
            if c.rank > 0:
                dcg += 1.0 / math.log2(c.rank + 1)

    # Compute IDCG from eligible gold set
    ideal_len = min(len(eligible_facts), k)
    idcg = sum(1.0 / math.log2(pos + 1) for pos in range(1, ideal_len + 1))

    score = (dcg / idcg) if idcg > 0.0 else 0.0
    return MetricOutcome(
        status="ok",
        score=score,
        detail={
            "dcg": dcg,
            "idcg": idcg,
            "undecidable_retrieved_chunks": float(undecidable_count),
            "gold_facts_longer_than_chunk": float(excluded_facts_count),
        },
        n=len(eligible_facts),
    )


def em_f1(gold_answer: str, predicted_answer: str) -> tuple[float, float]:
    """Compute SQuAD exact match (EM) and token F1 scores."""
    norm_gold = squad_normalize(gold_answer)
    norm_pred = squad_normalize(predicted_answer)

    em = 1.0 if norm_gold == norm_pred else 0.0

    gold_tokens = norm_gold.split()
    pred_tokens = norm_pred.split()

    if not gold_tokens or not pred_tokens:
        return (em, 1.0 if gold_tokens == pred_tokens else 0.0)

    common = Counter(gold_tokens) & Counter(pred_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return (em, 0.0)

    precision = num_same / len(pred_tokens)
    recall = num_same / len(gold_tokens)
    f1 = (2 * precision * recall) / (precision + recall)
    return (em, f1)


def squad_em(question: GoldQuestion, predicted_answer: str) -> MetricOutcome:
    """Compute SQuAD exact match (EM) for a single question."""
    if not question.gold_answer:
        return MetricOutcome(
            status="skipped",
            reason="Question has no gold answer",
            n=0,
        )
    em, _ = em_f1(question.gold_answer, predicted_answer)
    return MetricOutcome(
        status="ok",
        score=em,
        n=1,
    )


def squad_f1(question: GoldQuestion, predicted_answer: str) -> MetricOutcome:
    """Compute SQuAD token F1 for a single question."""
    if not question.gold_answer:
        return MetricOutcome(
            status="skipped",
            reason="Question has no gold answer",
            n=0,
        )
    _, f1 = em_f1(question.gold_answer, predicted_answer)
    return MetricOutcome(
        status="ok",
        score=f1,
        n=1,
    )


def abstention_outcome(
    question: GoldQuestion, notices: list[Any], answer: str, citations: list[Any]
) -> str:
    """Classify abstention behavior on null queries."""
    if not question.is_null:
        raise ValueError("Non-null question cannot enter abstention evaluation")

    # 1. Prefer typed notice code NOTICE_CODE_NO_EVIDENCE = 1 or GRAPH_ABLATION = 18
    for n in notices:
        typed_code = getattr(n, "typed_code", None)
        if typed_code == 1:
            return "correct_abstention"

    # 2. Fall back to normalized refusal match on answer text
    norm_ans = normalize_ws(answer)
    if "insufficient information" in norm_ans or "cannot answer" in norm_ans:
        return "correct_abstention"

    # 3. Confident answer with non-empty citations
    if answer.strip() and citations:
        return "hallucinated_on_null"

    return "other"


def abstention_rate(
    question: GoldQuestion,
    answer: str,
    citations: list[Any] | None = None,
    notices: list[Any] | None = None,
) -> MetricOutcome:
    """Compute binary abstention success for a null question."""
    outcome = abstention_outcome(question, notices or [], answer, citations or [])
    score = 1.0 if outcome == "correct_abstention" else 0.0
    return MetricOutcome(
        status="ok",
        score=score,
        detail={"outcome": 1.0 if outcome == "correct_abstention" else 0.0},
        n=1,
    )


def reference_convention_map_at_10(
    question: GoldQuestion,
    retrieved_chunks: list[StructuredCitation] | None,
    chunk_size: int = 500,
) -> MetricOutcome:
    """Compute MultiHop-RAG reference scorer convention MAP@10."""
    if question.is_null:
        raise ValueError("Null-slice question cannot enter retrieval metrics")

    if retrieved_chunks is None:
        return MetricOutcome(
            status="skipped",
            reason="no retrieval snapshot on the response",
            n=len(question.gold_facts),
        )

    eligible_facts = [
        f for f in question.gold_facts if not gold_fact_longer_than_chunk(f, chunk_size)
    ]
    if not eligible_facts:
        return MetricOutcome(
            status="skipped",
            reason="all gold facts exceed corpus chunk size",
            n=len(question.gold_facts),
        )

    ideal_len = min(len(eligible_facts), 10)
    top_10 = [c for c in retrieved_chunks if c.rank <= 10]

    seen_facts: set[str] = set()
    accrued = 0.0

    for c in top_10:
        for f in eligible_facts:
            if f not in seen_facts and fact_matches_excerpt(f, c) == MatchVerdict.HIT:
                seen_facts.add(f)
                if c.rank > 0:
                    accrued += 1.0 / c.rank

    score = (accrued / ideal_len) if ideal_len > 0 else 0.0
    return MetricOutcome(
        status="ok",
        score=score,
        detail={"accrued": accrued, "ideal_len": float(ideal_len)},
        n=len(eligible_facts),
    )


# --- D-102 paper-convention metrics (06.3.5-07) -------------------------------------
#
# These follow the official MultiHop-RAG ``calculate_metrics`` at
# yixuantt/MultiHop-RAG@c1c1287aa60a94acf9c4d20c891c9cd611a0f6e8
# (retrieval_evaluate.py), and are proven equal to its outputs by the committed
# golden vectors. They are
# deliberately separate from ``hits_at_k``, ``mrr_at_k`` and
# ``reference_convention_map_at_10``, which match on 512-character wire excerpts over
# the final eight chunks and are not the paper convention.
OFFICIAL_COMMIT = "c1c1287aa60a94acf9c4d20c891c9cd611a0f6e8"
PAPER_RANK_CUTOFF = 10
PAPER_HITS_CUTOFF = 4


class PaperMetricsResult(BaseModel):
    """Paper-convention retrieval metrics of one arm (AI-SPEC 4b, D-102).

    The ``paper_`` prefix keeps these apart from the excerpt-matched, final-eight
    ``mrr_at_k`` that ``score.py`` already reports under a similar name.

    Attributes:
        arm: Canonical arm label.
        official_commit: The MultiHop-RAG commit whose arithmetic these equal.
        matching_rule: ``chunk_id_via_gold_chunks`` (the ID rule through the D-61
            gold-chunk table) or ``store_text_official`` (the official text rule
            over stored chunk text).
        n_queries: Questions in the denominator.
        n_excluded: Questions left out before scoring.
        paper_hits_at_4: Share of questions with a relevant chunk in the top 4.
        paper_hits_at_10: Share with a relevant chunk in the top 10.
        paper_mrr_at_10: Mean reciprocal rank of the first relevant chunk, rank <= 10.
        paper_map_at_10: The script's non-standard MAP@10: facts first found at a
            rank, over that rank, divided by ``min(len(gold), 10)``. Each fact is
            credited once at no more than 1/rank, so the value is at most 1.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    arm: str
    official_commit: Literal["c1c1287aa60a94acf9c4d20c891c9cd611a0f6e8"]
    matching_rule: Literal["chunk_id_via_gold_chunks", "store_text_official"]
    n_queries: int = Field(ge=0)
    n_excluded: int = Field(ge=0)
    paper_hits_at_4: float = Field(ge=0.0, le=1.0)
    paper_hits_at_10: float = Field(ge=0.0, le=1.0)
    paper_mrr_at_10: float = Field(ge=0.0, le=1.0)
    paper_map_at_10: float = Field(ge=0.0, le=1.0)


def id_matcher(chunk_id: str, gold_set: frozenset[str]) -> bool:
    """ID rule: a chunk is relevant to a gold unit if its ID is in the unit's set."""
    return chunk_id in gold_set


def text_matcher(text: str, fact: str) -> bool:
    """Official text rule: the fact is a substring of the chunk text.

    Both sides lose every space and newline first, and the test is case-sensitive.
    An empty ``fact`` matches, exactly as in the official function.
    """
    return fact.replace(" ", "").replace("\n", "") in text.replace(" ", "").replace(
        "\n", ""
    )


def paper_question_scores[R, G](
    ranked: Sequence[R],
    gold: Sequence[G],
    matches: Callable[[R, G], bool],
) -> dict[str, Any]:
    """Scores one question with the official ``calculate_metrics`` semantics.

    Walks ranks 1..10. An item is relevant when it matches any gold unit. ``hit4``
    and ``hit10`` follow the first relevant rank, ``rr`` is ``1 / first``, and ``ap``
    is the script's non-standard MAP: for each relevant rank, the gold units first
    found there, over the rank, summed and divided by ``min(len(gold), 10)``. A unit
    that matches nothing (a fact split across two chunks, an empty ID set) never
    matches but still counts in that divisor.

    The ID form passes chunk IDs and ``frozenset`` units with ``id_matcher``. The
    text form passes chunk texts and fact strings with ``text_matcher``. Two gold
    units with the same text are the one input where this differs from the official
    function (it tracks found facts by text, this by index); real facts carry no
    duplicates in the 06.3.5 sample.

    Args:
        ranked: Retrieved items in rank order; only the first ten are read.
        gold: The question's gold units, one per evidence fact.
        matches: ``matches(item, unit)``.

    Returns:
        ``{"hit4": bool, "hit10": bool, "rr": float, "ap": float}``.

    Raises:
        ValueError: If ``gold`` is empty (the official function divides by zero).
    """
    if not gold:
        raise ValueError("gold must hold at least one unit")
    found: set[int] = set()
    ap_sum = 0.0
    first: int | None = None
    for rank, item in enumerate(ranked[:PAPER_RANK_CUTOFF], start=1):
        matched = [i for i, unit in enumerate(gold) if matches(item, unit)]
        if not matched:
            continue
        if first is None:
            first = rank
        new = [i for i in matched if i not in found]
        found.update(new)
        ap_sum += len(new) / rank
    return {
        "hit4": first is not None and first <= PAPER_HITS_CUTOFF,
        "hit10": first is not None,
        "rr": 1 / first if first is not None else 0.0,
        "ap": ap_sum / min(len(gold), PAPER_RANK_CUTOFF),
    }


def load_gold_chunk_sets(path: Path | str) -> dict[str, list[frozenset[str]]]:
    """Reads ``gold_chunks.jsonl`` into one chunk-ID set per evidence row.

    Each question maps to its sets in ``evidence_index`` order. An ``in_chunk`` row
    becomes ``frozenset(chunk_ids)``. A ``split_across_chunks`` row becomes
    ``frozenset()``, which never matches but still counts in ``min(len(gold), 10)``.

    Args:
        path: The JSONL table (row shape ``{question_id, evidence_index, title,
            document_id, state, chunk_ids}``).

    Returns:
        ``question_id`` to the question's gold sets, ordered by ``evidence_index``.

    Raises:
        ValueError: On an unknown ``state``, an ``in_chunk`` row without chunk IDs, or
            a repeated ``(question_id, evidence_index)``.
    """
    by_question: dict[str, dict[int, frozenset[str]]] = {}
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            qid, idx, state = row["question_id"], row["evidence_index"], row["state"]
            if state == "in_chunk":
                chunk_ids = frozenset(row["chunk_ids"])
                if not chunk_ids:
                    raise ValueError(
                        f"{path}:{line_no}: in_chunk row for {qid}[{idx}] "
                        "has no chunk_ids"
                    )
            elif state == "split_across_chunks":
                chunk_ids = frozenset()
            else:
                raise ValueError(
                    f"{path}:{line_no}: unknown state {state!r} for {qid}[{idx}]"
                )
            slot = by_question.setdefault(qid, {})
            if idx in slot:
                raise ValueError(
                    f"{path}:{line_no}: duplicate row for ({qid}, {idx})"
                )
            slot[idx] = chunk_ids
    return {
        qid: [slot[i] for i in sorted(slot)] for qid, slot in by_question.items()
    }


def paper_metrics(per_question: list[dict[str, Any]]) -> dict[str, float]:
    """Averages ``paper_question_scores`` results over the questions.

    Args:
        per_question: One ``paper_question_scores`` dict per question.

    Returns:
        ``paper_hits_at_4``, ``paper_hits_at_10``, ``paper_mrr_at_10`` and
        ``paper_map_at_10``, each the mean over the list.

    Raises:
        ValueError: If the list is empty.
    """
    if not per_question:
        raise ValueError("cannot average an empty list of per-question scores")
    n = len(per_question)
    return {
        "paper_hits_at_4": sum(1 for s in per_question if s["hit4"]) / n,
        "paper_hits_at_10": sum(1 for s in per_question if s["hit10"]) / n,
        "paper_mrr_at_10": sum(s["rr"] for s in per_question) / n,
        "paper_map_at_10": sum(s["ap"] for s in per_question) / n,
    }
