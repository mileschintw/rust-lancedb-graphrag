"""Stage-cap spend accounting for failed generations (06.3.4.1-23, G4 cost item, D-86).

Pass A billed $0.2178 while the harness estimated $0.0748: the 135 records whose
``GenerateAnswer`` node failed carry zero wire tokens, yet the provider billed the
generation. ``compute_spend`` is what both ``run.drive`` and ``run_measurement_pass``
enforce their stage caps on, so it must charge those records at the per-attempt
ceiling.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from lancet_eval import measure
from lancet_eval.client import NodeFailed
from lancet_eval.journal import NodeTiming, RunRecord, WorkflowWireMeta
from lancet_eval.measure import MeasurementRecord, compute_spend

REPO_ROOT = Path(__file__).resolve().parents[2]
PASS_A_JOURNAL = REPO_ROOT / "eval" / "runs" / "2026-09-28-passA-measure-multihop_rag" / "journal.jsonl"
BILLED_PASS_A_USD = 0.2178
OLD_PASS_A_ESTIMATE_USD = 0.0748

# The engine's own wording for each failure class, as the journal records it.
SCHEMA_CLASSES = [
    "answer basis 'mixed' requires at least one cited evidence ID",
    "ModelOnly answer basis is not supported on Phase 03 QueryRAG path",
    "failed to deserialize ModelOutput schema: trailing characters at line 3 column 1",
    "answer basis 'retrieval' requires at least one cited evidence ID",
    "Model answer text must not be empty or blank",
    "OpenRouter completion incomplete: finish_reason 'length'",
    "notice length exceeds limit 1024",
]
# Engine literals (generation/openrouter.rs) for the classes the node retries: the node
# retries only GenerationErrorKind::Timeout and ::ProviderError (generate.rs is_retryable).
RETRIED_MESSAGES = [
    "OpenRouter chat completion timed out",
    "OpenRouter request timed out at boundary limit",
    "OpenRouter request failed: error sending request for url (https://openrouter.ai)",
    "failed to read OpenRouter response body: connection reset",
    "OpenRouter chat completion returned HTTP 500 Internal Server Error",
    "OpenRouter chat completion returned HTTP 503 Service Unavailable",
    "OpenRouter chat completion returned HTTP 429 Too Many Requests",
]
NOT_RETRIED_MESSAGES = [
    # 4xx other than 429 is InvalidRequest: one attempt.
    "OpenRouter chat completion returned HTTP 400 Bad Request",
    "OpenRouter chat completion returned HTTP 401 Unauthorized",
    *SCHEMA_CLASSES,
]

CEILING_PROMPT_TOKENS = 8192
CEILING_COMPLETION_TOKENS = 2048


def _ceiling_usd() -> float:
    """One billed attempt at the ceiling, from the module's own price constants."""
    return (
        CEILING_PROMPT_TOKENS * measure.GENERATION_INPUT_PRICE_PER_1M
        + CEILING_COMPLETION_TOKENS * measure.GENERATION_OUTPUT_PRICE_PER_1M
    ) / 1_000_000.0


def _old_spend(records: list[RunRecord], include_embeddings: bool = True) -> float:
    """The pre-06.3.4.1-23 estimator, verbatim, at the current price constants."""
    prompt = sum(r.workflow_meta.prompt_tokens for r in records if r.workflow_meta)
    completion = sum(r.workflow_meta.completion_tokens for r in records if r.workflow_meta)
    gen = (prompt / 1_000_000.0) * measure.GENERATION_INPUT_PRICE_PER_1M + (
        completion / 1_000_000.0
    ) * measure.GENERATION_OUTPUT_PRICE_PER_1M
    if not include_embeddings:
        return gen
    emb = (len(records) * measure.ESTIMATED_EMBEDDING_TOKENS_PER_QUERY / 1_000_000.0) * (
        measure.EMBEDDING_PRICE_PER_1M
    )
    return gen + emb


def _failed_generation_record(message: str, qid: str = "q") -> RunRecord:
    """A record shaped like pass A's 135: AssemblePrompt completed, GenerateAnswer failed."""
    return RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-on",
        outcome="error",
        node_failures=[
            NodeFailed(node_name="GenerateAnswer", error_kind=3, error_message=message, retryable=False)
        ],
        node_timings=[NodeTiming(node_name="AssemblePrompt", duration_ms=12.0)],
        workflow_meta=WorkflowWireMeta(prompt_tokens=0, completion_tokens=0),
    )


def _success_record(prompt: int, completion: int, qid: str = "s") -> RunRecord:
    return RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-off",
        outcome="success",
        node_timings=[
            NodeTiming(node_name="AssemblePrompt", duration_ms=12.0),
            NodeTiming(node_name="GenerateAnswer", duration_ms=900.0),
        ],
        workflow_meta=WorkflowWireMeta(prompt_tokens=prompt, completion_tokens=completion),
    )


def _load_pass_a() -> list[MeasurementRecord]:
    with open(PASS_A_JOURNAL, encoding="utf-8") as f:
        return [MeasurementRecord.model_validate_json(line) for line in f if line.strip()]


# --- charge rules through the public compute_spend API ------------------------------------


def test_failed_generation_record_is_charged_one_ceiling() -> None:
    """A GenerateAnswer failure with zero wire tokens is billed one per-attempt ceiling."""
    rec = _failed_generation_record(SCHEMA_CLASSES[0])
    spend, is_lower = compute_spend([rec], include_embeddings=False)
    assert is_lower is True
    assert spend == pytest.approx(_ceiling_usd())


@pytest.mark.parametrize("message", RETRIED_MESSAGES)
def test_retried_failure_classes_are_charged_two_ceilings(message: str) -> None:
    """The node retries Timeout and ProviderError once, so two attempts may be billed."""
    spend, _ = compute_spend([_failed_generation_record(message)], include_embeddings=False)
    assert spend == pytest.approx(2 * _ceiling_usd())


@pytest.mark.parametrize("message", NOT_RETRIED_MESSAGES)
def test_non_retried_failure_classes_are_charged_one_ceiling(message: str) -> None:
    spend, _ = compute_spend([_failed_generation_record(message)], include_embeddings=False)
    assert spend == pytest.approx(_ceiling_usd())


def test_node_timeout_kind_is_charged_two_ceilings() -> None:
    """A GenerateAnswer failure of node error kind Timeout (1) is a retried class."""
    rec = _failed_generation_record("Node 'GenerateAnswer' timed out")
    rec.node_failures[0].error_kind = 1
    spend, _ = compute_spend([rec], include_embeddings=False)
    assert spend == pytest.approx(2 * _ceiling_usd())


def test_assembled_prompt_with_no_generation_outcome_is_charged_one_ceiling() -> None:
    """Harness deadline or read timeout during generation: AssemblePrompt done, no GenerateAnswer
    failure and no completed GenerateAnswer timing, zero wire tokens. May still be billed."""
    rec = RunRecord(
        corpus="multihop_rag",
        question_id="q",
        graph_arm="graph-on",
        outcome="error",
        error_type="ReadTimeout",
        error="gateway read timed out",
        node_timings=[NodeTiming(node_name="AssemblePrompt", duration_ms=12.0)],
        workflow_meta=WorkflowWireMeta(),
    )
    spend, _ = compute_spend([rec], include_embeddings=False)
    assert spend == pytest.approx(_ceiling_usd())


def test_record_that_never_reached_assemble_prompt_gains_no_charge() -> None:
    rec = RunRecord(
        corpus="multihop_rag",
        question_id="q",
        graph_arm="graph-on",
        outcome="error",
        node_failures=[
            NodeFailed(
                node_name="RetrieveHybrid",
                error_kind=1,
                error_message="Node 'RetrieveHybrid' timed out",
                retryable=False,
            )
        ],
        node_timings=[NodeTiming(node_name="ExtractGraphContext", duration_ms=40.0)],
        workflow_meta=WorkflowWireMeta(),
    )
    spend, _ = compute_spend([rec], include_embeddings=False)
    assert spend == 0.0
    # a bare record with no meta and no timings is not charged either
    bare = RunRecord(corpus="c", question_id="q", graph_arm="graph-on", outcome="error")
    assert compute_spend([bare], include_embeddings=False)[0] == 0.0


def test_failed_generation_with_billed_tokens_is_not_double_charged() -> None:
    """If wire tokens were reported the token formula already prices the record."""
    rec = _failed_generation_record(SCHEMA_CLASSES[0])
    assert rec.workflow_meta is not None
    rec.workflow_meta.prompt_tokens = 5000
    rec.workflow_meta.completion_tokens = 100
    assert compute_spend([rec]) == (_old_spend([rec]), False)


def test_embedding_estimate_still_added_per_record() -> None:
    rec = _failed_generation_record(SCHEMA_CLASSES[0])
    with_emb, is_lower = compute_spend([rec], include_embeddings=True)
    without_emb, _ = compute_spend([rec], include_embeddings=False)
    assert is_lower is False
    assert with_emb - without_emb == pytest.approx(
        measure.ESTIMATED_EMBEDDING_TOKENS_PER_QUERY * measure.EMBEDDING_PRICE_PER_1M / 1_000_000.0
    )


# --- successful records are charged exactly as before ----------------------------------------


def test_successful_records_charge_equals_old_formula(monkeypatch: pytest.MonkeyPatch) -> None:
    """Old versus new, identical to the cent, even with a failed-generation multiplier set."""
    records = [_success_record(1500 + 37 * i, 200 + 11 * i, qid=f"s{i}") for i in range(40)]
    for with_emb in (True, False):
        assert compute_spend(records, include_embeddings=with_emb)[0] == pytest.approx(
            _old_spend(records, with_emb), abs=1e-12
        )
    monkeypatch.setattr(measure, "FAILED_GENERATION_CHARGE_MULTIPLIER", 5.0, raising=False)
    assert compute_spend(records)[0] == pytest.approx(_old_spend(records), abs=1e-12)


def test_multiplier_scales_only_the_failed_generation_charge(monkeypatch: pytest.MonkeyPatch) -> None:
    ok = _success_record(4000, 300)
    bad = _failed_generation_record(RETRIED_MESSAGES[0])
    mixed = [ok, bad]
    base, _ = compute_spend(mixed, include_embeddings=False)
    monkeypatch.setattr(measure, "FAILED_GENERATION_CHARGE_MULTIPLIER", 2.0, raising=False)
    scaled, _ = compute_spend(mixed, include_embeddings=False)
    success_part = _old_spend([ok], include_embeddings=False)
    failed_part = 2 * _ceiling_usd()
    assert base == pytest.approx(success_part + failed_part)
    # measure reads the constant at call time, so a multiplier of 2 doubles only failures.
    assert scaled == pytest.approx(success_part + 2.0 * failed_part)
    # embeddings are never scaled
    with_emb, _ = compute_spend(mixed, include_embeddings=True)
    assert with_emb - scaled == pytest.approx(
        2 * measure.ESTIMATED_EMBEDDING_TOKENS_PER_QUERY * measure.EMBEDDING_PRICE_PER_1M / 1_000_000.0
    )


def test_new_estimate_never_below_old_for_any_mix() -> None:
    """Monotonicity: the corrected estimate can only grow relative to the old formula."""
    pool: list[RunRecord] = [
        _success_record(3000, 250, "a"),
        _success_record(0, 0, "zero-success"),
        _failed_generation_record(SCHEMA_CLASSES[2], "b"),
        _failed_generation_record(RETRIED_MESSAGES[1], "c"),
        RunRecord(corpus="c", question_id="d", graph_arm="graph-on", outcome="error"),
    ]
    for size in range(len(pool) + 1):
        subset = pool[:size]
        for with_emb in (True, False):
            assert compute_spend(subset, include_embeddings=with_emb)[0] >= _old_spend(
                subset, with_emb
            ) - 1e-15
    assert compute_spend(_load_pass_a())[0] >= _old_spend(list(_load_pass_a()))


# --- pass A calibration -------------------------------------------------------------------


def test_pass_a_corrected_estimate_covers_the_provider_bill() -> None:
    """Pass A: 324 records, 135 failed generations, $0.2178 billed, $0.0748 old estimate."""
    records = _load_pass_a()
    assert len(records) == 324
    spend, is_lower = compute_spend(records, include_embeddings=True)
    assert is_lower is False
    assert spend >= BILLED_PASS_A_USD, f"corrected estimate {spend:.4f} is below the {BILLED_PASS_A_USD} bill"
    assert spend > OLD_PASS_A_ESTIMATE_USD * 2


def test_pass_a_failed_generation_count_is_the_135_journal_failures() -> None:
    records = _load_pass_a()
    failed = [r for r in records if any(f.node_name == "GenerateAnswer" for f in r.node_failures)]
    assert len(failed) == 135
    # all seven classes are SchemaValidation: one attempt each, so 135 attempts in total
    assert measure.count_failed_generation_attempts(records) == 135


# --- constants and the new API surface ---------------------------------------------------


def test_ceiling_constants_agree_with_config_toml() -> None:
    """The ceiling is the engine's own bound: evidence_token_budget and max_output_tokens."""
    with open(REPO_ROOT / "config" / "config.toml", "rb") as f:
        cfg = tomllib.load(f)
    assert measure.FAILED_GENERATION_PROMPT_TOKENS == cfg["engine"]["retrieval"]["evidence_token_budget"]
    assert measure.FAILED_GENERATION_COMPLETION_TOKENS == cfg["openrouter"]["max_output_tokens"]
    assert measure.FAILED_GENERATION_PROMPT_TOKENS == CEILING_PROMPT_TOKENS
    assert measure.FAILED_GENERATION_COMPLETION_TOKENS == CEILING_COMPLETION_TOKENS


def test_failed_generation_attempt_usd_is_the_priced_ceiling() -> None:
    assert measure.failed_generation_attempt_usd() == pytest.approx(_ceiling_usd())


def test_generation_prices_are_not_below_the_recorded_listing() -> None:
    """Prices only move up to OpenRouter's listing (checked 2026-09-29 against
    deepseek/deepseek-v4-flash-0731: $0.018 prompt, $0.32 completion per 1M)."""
    assert measure.GENERATION_INPUT_PRICE_PER_1M >= 0.018
    assert measure.GENERATION_OUTPUT_PRICE_PER_1M >= 0.32


def test_count_failed_generation_attempts_rules() -> None:
    assert measure.count_failed_generation_attempts([]) == 0
    assert measure.count_failed_generation_attempts([_success_record(10, 5)]) == 0
    assert measure.count_failed_generation_attempts([_failed_generation_record(SCHEMA_CLASSES[0])]) == 1
    assert measure.count_failed_generation_attempts([_failed_generation_record(RETRIED_MESSAGES[0])]) == 2
    assert (
        measure.count_failed_generation_attempts(
            [_failed_generation_record(SCHEMA_CLASSES[0]), _failed_generation_record(RETRIED_MESSAGES[4])]
        )
        == 3
    )
