"""Deterministic evaluation metrics computed from gold labels without LLMs."""

from __future__ import annotations

import math
import re
import string
from collections import Counter
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lancet_eval.client import StructuredCitation
from lancet_eval.corpus import GoldQuestion


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
