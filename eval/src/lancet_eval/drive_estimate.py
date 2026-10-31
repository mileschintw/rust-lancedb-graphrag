"""The D-258 cost estimate printed before a paid drive; it never refuses (#77).

`lancet-eval run`, `lancet-eval run-external` and `lancet-llamaindex export` print one
line before their first paid request: questions x arms x a per-question figure built
from `measure`'s price constants. Each figure is an upper bound, the same charges the
stage cap uses:

- generation: one attempt at the engine's token ceilings
  (`measure.failed_generation_attempt_usd`, 8192 prompt and 2048 completion tokens at
  the committed generation prices);
- query embedding: `ESTIMATED_EMBEDDING_TOKENS_PER_QUERY` at `EMBEDDING_PRICE_PER_1M`,
  on every arm that embeds (not `bm25-only` with graph context off, D-125);
- rerank: `RERANK_UNREPORTED_CALL_CEILING_USD` per call, on an arm with the rerank
  lever.

A `batch submit` prints its own estimate (`batch.cost_estimate`, #53).
"""

from __future__ import annotations

from collections.abc import Sequence

from lancet_eval.arms import is_external_arm, is_reader_arm, resolve_arm
from lancet_eval.measure import (
    EMBEDDING_PRICE_PER_1M,
    ESTIMATED_EMBEDDING_TOKENS_PER_QUERY,
    RERANK_UNREPORTED_CALL_CEILING_USD,
    failed_generation_attempt_usd,
)

_PREFIX = "Cost estimate (D-258, never refuses)"
# The usual English-text rate; the export prices its document text at it.
CHARS_PER_TOKEN = 4


def _query_embedding_usd() -> float:
    return ESTIMATED_EMBEDDING_TOKENS_PER_QUERY / 1_000_000.0 * EMBEDDING_PRICE_PER_1M


def arm_question_usd(arm: str) -> float:
    """One question's upper-bound cost on `arm`, for one attempt.

    An external or reader arm is priced at the generation ceiling alone: its retrieval
    was paid for when its context was built.
    """
    usd = failed_generation_attempt_usd()
    if is_external_arm(arm) or is_reader_arm(arm):
        return usd
    spec = resolve_arm(arm)
    if not (spec.retrieval_mode == "bm25_only" and spec.disable_graph_context):
        usd += _query_embedding_usd()
    if "rerank" in spec.levers:
        usd += RERANK_UNREPORTED_CALL_CEILING_USD
    return usd


def drive_estimate(questions: int, arms: Sequence[str], *, retries: int = 0) -> str:
    """The line `run` and `run-external` print before their first request.

    Args:
        questions: The questions the drive may send (after `--limit`).
        arms: The arms it drives.
        retries: The retry budget per work unit; a positive one adds a bound.
    """
    per_question = sum(arm_question_usd(arm) for arm in arms)
    total = questions * per_question
    line = (
        f"{_PREFIX}: {questions} question(s) x {len(arms)} arm(s) at most "
        f"${per_question:.4f} per question over the arms: at most ${total:.4f} for "
        "one attempt each"
    )
    if retries > 0:
        line += (
            f", ${total * (1 + retries):.4f} if every unit used all {retries} retries"
        )
    return line + ". A resume skips the units the journal already holds."


def export_estimate(questions: int, document_chars: int) -> str:
    """The line `lancet-llamaindex export` prints before it embeds anything.

    Indexing embeds the documents once (their text at `CHARS_PER_TOKEN`); each
    question then embeds its query and makes one rerank call.
    """
    documents = document_chars / CHARS_PER_TOKEN / 1_000_000.0 * EMBEDDING_PRICE_PER_1M
    per_question = _query_embedding_usd() + RERANK_UNREPORTED_CALL_CEILING_USD
    total = documents + questions * per_question
    return (
        f"{_PREFIX}: indexing about ${documents:.4f} ({document_chars} document "
        f"characters), then {questions} question(s) x 1 arm at most "
        f"${per_question:.6f} each: at most ${total:.4f}."
    )
