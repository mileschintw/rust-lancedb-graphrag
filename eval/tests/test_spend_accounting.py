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
from typing import Literal

import pytest

from lancet_eval import measure
from lancet_eval.client import NodeFailed
from lancet_eval.journal import (
    AttemptRecord,
    NodeTiming,
    RunRecord,
    WorkflowWireMeta,
    first_attempt_view,
)
from lancet_eval.measure import MeasurementRecord, compute_spend

REPO_ROOT = Path(__file__).resolve().parents[2]
PASS_A_JOURNAL = (
    REPO_ROOT
    / "eval"
    / "runs"
    / "2026-09-28-passA-measure-multihop_rag"
    / "journal.jsonl"
)
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
# retries only GenerationErrorKind::Timeout and ::ProviderError (generate.rs
# is_retryable).
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
    completion = sum(
        r.workflow_meta.completion_tokens for r in records if r.workflow_meta
    )
    gen = (prompt / 1_000_000.0) * measure.GENERATION_INPUT_PRICE_PER_1M + (
        completion / 1_000_000.0
    ) * measure.GENERATION_OUTPUT_PRICE_PER_1M
    if not include_embeddings:
        return gen
    emb = (
        len(records) * measure.ESTIMATED_EMBEDDING_TOKENS_PER_QUERY / 1_000_000.0
    ) * (measure.EMBEDDING_PRICE_PER_1M)
    return gen + emb


def _failed_generation_record(message: str, qid: str = "q") -> RunRecord:
    """A record shaped like pass A's 135: AssemblePrompt done, GenerateAnswer failed."""
    return RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-on",
        outcome="error",
        node_failures=[
            NodeFailed(
                node_name="GenerateAnswer",
                error_kind=3,
                error_message=message,
                retryable=False,
            )
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
        workflow_meta=WorkflowWireMeta(
            prompt_tokens=prompt, completion_tokens=completion
        ),
    )


def _load_pass_a() -> list[MeasurementRecord]:
    with open(PASS_A_JOURNAL, encoding="utf-8") as f:
        return [
            MeasurementRecord.model_validate_json(line) for line in f if line.strip()
        ]


# --- charge rules through the public compute_spend API -------------------------


def test_failed_generation_record_is_charged_one_ceiling() -> None:
    """A GenerateAnswer failure with zero wire tokens is billed one ceiling."""
    rec = _failed_generation_record(SCHEMA_CLASSES[0])
    spend, is_lower = compute_spend([rec], include_embeddings=False)
    assert is_lower is True
    assert spend == pytest.approx(_ceiling_usd())


@pytest.mark.parametrize("message", RETRIED_MESSAGES)
def test_retried_failure_classes_are_charged_two_ceilings(message: str) -> None:
    """The node retries Timeout and ProviderError once: two attempts may be billed."""
    spend, _ = compute_spend(
        [_failed_generation_record(message)], include_embeddings=False
    )
    assert spend == pytest.approx(2 * _ceiling_usd())


@pytest.mark.parametrize("message", NOT_RETRIED_MESSAGES)
def test_non_retried_failure_classes_are_charged_one_ceiling(message: str) -> None:
    spend, _ = compute_spend(
        [_failed_generation_record(message)], include_embeddings=False
    )
    assert spend == pytest.approx(_ceiling_usd())


def test_node_timeout_kind_is_charged_two_ceilings() -> None:
    """A GenerateAnswer failure of node error kind Timeout (1) is a retried class."""
    rec = _failed_generation_record("Node 'GenerateAnswer' timed out")
    rec.node_failures[0].error_kind = 1
    spend, _ = compute_spend([rec], include_embeddings=False)
    assert spend == pytest.approx(2 * _ceiling_usd())


def test_assembled_prompt_with_no_generation_outcome_is_charged_one_ceiling() -> None:
    """Harness deadline or read timeout during generation.

    AssemblePrompt done, no GenerateAnswer failure and no completed GenerateAnswer
    timing, zero wire tokens. May still be billed.
    """
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
        measure.ESTIMATED_EMBEDDING_TOKENS_PER_QUERY
        * measure.EMBEDDING_PRICE_PER_1M
        / 1_000_000.0
    )


# --- successful records are charged exactly as before --------------------------


def test_successful_records_charge_equals_old_formula(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old versus new, identical to the cent, even with a multiplier set."""
    records = [
        _success_record(1500 + 37 * i, 200 + 11 * i, qid=f"s{i}") for i in range(40)
    ]
    for with_emb in (True, False):
        assert compute_spend(records, include_embeddings=with_emb)[0] == pytest.approx(
            _old_spend(records, with_emb), abs=1e-12
        )
    monkeypatch.setattr(
        measure, "FAILED_GENERATION_CHARGE_MULTIPLIER", 5.0, raising=False
    )
    assert compute_spend(records)[0] == pytest.approx(_old_spend(records), abs=1e-12)


def test_multiplier_scales_only_the_failed_generation_charge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ok = _success_record(4000, 300)
    bad = _failed_generation_record(RETRIED_MESSAGES[0])
    mixed = [ok, bad]
    base, _ = compute_spend(mixed, include_embeddings=False)
    monkeypatch.setattr(
        measure, "FAILED_GENERATION_CHARGE_MULTIPLIER", 2.0, raising=False
    )
    scaled, _ = compute_spend(mixed, include_embeddings=False)
    success_part = _old_spend([ok], include_embeddings=False)
    failed_part = 2 * _ceiling_usd()
    assert base == pytest.approx(success_part + failed_part)
    # measure reads the constant at call time: a multiplier of 2 doubles only failures.
    assert scaled == pytest.approx(success_part + 2.0 * failed_part)
    # embeddings are never scaled
    with_emb, _ = compute_spend(mixed, include_embeddings=True)
    assert with_emb - scaled == pytest.approx(
        2
        * measure.ESTIMATED_EMBEDDING_TOKENS_PER_QUERY
        * measure.EMBEDDING_PRICE_PER_1M
        / 1_000_000.0
    )


def test_new_estimate_never_below_old_for_any_mix() -> None:
    """Monotonicity: the corrected estimate can only grow against the old formula."""
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
            assert (
                compute_spend(subset, include_embeddings=with_emb)[0]
                >= _old_spend(subset, with_emb) - 1e-15
            )
    assert compute_spend(_load_pass_a())[0] >= _old_spend(list(_load_pass_a()))


# --- pass A calibration --------------------------------------------------------


def test_pass_a_corrected_estimate_covers_the_provider_bill() -> None:
    """Pass A: 324 records, 135 failed generations, $0.2178 billed, $0.0748 old."""
    records = _load_pass_a()
    assert len(records) == 324
    spend, is_lower = compute_spend(records, include_embeddings=True)
    assert is_lower is False
    assert spend >= BILLED_PASS_A_USD, (
        f"corrected estimate {spend:.4f} is below the {BILLED_PASS_A_USD} bill"
    )
    assert spend > OLD_PASS_A_ESTIMATE_USD * 2


def test_pass_a_failed_generation_count_is_the_135_journal_failures() -> None:
    records = _load_pass_a()
    failed = [
        r
        for r in records
        if any(f.node_name == "GenerateAnswer" for f in r.node_failures)
    ]
    assert len(failed) == 135
    # all seven classes are SchemaValidation: one attempt each, so 135 attempts in total
    assert measure.count_failed_generation_attempts(records) == 135


# --- constants and the new API surface -----------------------------------------


def test_ceiling_constants_agree_with_config_toml() -> None:
    """The ceiling is the engine's own bound (evidence budget, max output tokens)."""
    with open(REPO_ROOT / "config" / "config.toml", "rb") as f:
        cfg = tomllib.load(f)
    assert (
        measure.FAILED_GENERATION_PROMPT_TOKENS
        == cfg["engine"]["retrieval"]["evidence_token_budget"]
    )
    assert (
        measure.FAILED_GENERATION_COMPLETION_TOKENS
        == cfg["openrouter"]["max_output_tokens"]
    )
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
    assert (
        measure.count_failed_generation_attempts([
            _failed_generation_record(SCHEMA_CLASSES[0])
        ])
        == 1
    )
    assert (
        measure.count_failed_generation_attempts([
            _failed_generation_record(RETRIED_MESSAGES[0])
        ])
        == 2
    )
    assert (
        measure.count_failed_generation_attempts([
            _failed_generation_record(SCHEMA_CLASSES[0]),
            _failed_generation_record(RETRIED_MESSAGES[4]),
        ])
        == 3
    )


# --- every attempt is charged (06.3.4.1-33, CR-03, D-86) ------------------------


def _attempt(
    *,
    outcome: Literal["success", "error"] = "error",
    prompt: int = 0,
    completion: int = 0,
    failure: str | None = None,
    reached_generation: bool = False,
    error_type: str | None = None,
    attempt: int = 1,
) -> AttemptRecord:
    """An attempt a retry superseded, shaped like the records the charge reads."""
    timings = (
        [NodeTiming(node_name="AssemblePrompt", duration_ms=12.0)]
        if reached_generation
        else []
    )
    failures = (
        [
            NodeFailed(
                node_name="GenerateAnswer",
                error_kind=3,
                error_message=failure,
                retryable=False,
            )
        ]
        if failure is not None
        else []
    )
    return AttemptRecord(
        attempt=attempt,
        outcome=outcome,
        node_failures=failures,
        node_timings=timings,
        workflow_meta=WorkflowWireMeta(
            prompt_tokens=prompt, completion_tokens=completion
        ),
        error_type=error_type,
    )


_PRIOR_ATTEMPT_KINDS = {
    "wire_tokens": lambda: _attempt(outcome="success", prompt=4000, completion=300),
    "zero_token_failure_one_ceiling": lambda: _attempt(
        failure=SCHEMA_CLASSES[0], reached_generation=True
    ),
    "zero_token_failure_retried_class": lambda: _attempt(
        failure=RETRIED_MESSAGES[0], reached_generation=True
    ),
    "transport_timeout_never_reached_generation": lambda: _attempt(
        error_type="ReadTimeout"
    ),
}


@pytest.mark.parametrize("kind", sorted(_PRIOR_ATTEMPT_KINDS))
def test_retried_record_spend_is_first_attempt_plus_final_attempt_exactly(
    kind: str,
) -> None:
    """The decomposition: spend(R) == spend(first attempt) + spend(R without priors)."""
    prior = _PRIOR_ATTEMPT_KINDS[kind]()
    final = _success_record(6000, 250)
    retried = final.model_copy(update={"prior_attempts": [prior]})

    total, _ = compute_spend([retried])
    first_only, _ = compute_spend([first_attempt_view(retried)])
    final_only, _ = compute_spend([final])

    assert total == pytest.approx(first_only + final_only)
    assert total > final_only  # an attempt always costs at least its embedding estimate


def test_prior_attempt_wire_tokens_are_priced_like_a_record_with_those_tokens() -> None:
    prior = _attempt(outcome="success", prompt=4000, completion=300)
    retried = _success_record(0, 0).model_copy(update={"prior_attempts": [prior]})
    spend, _ = compute_spend([retried], include_embeddings=False)
    expected = (4000 / 1_000_000.0) * measure.GENERATION_INPUT_PRICE_PER_1M + (
        300 / 1_000_000.0
    ) * measure.GENERATION_OUTPUT_PRICE_PER_1M
    assert spend == pytest.approx(expected)


def test_prior_attempt_failure_charges_one_ceiling_or_two_for_a_retried_class() -> None:
    base = _success_record(0, 0)
    one_ceiling = _PRIOR_ATTEMPT_KINDS["zero_token_failure_one_ceiling"]()
    one = base.model_copy(update={"prior_attempts": [one_ceiling]})
    two = base.model_copy(
        update={
            "prior_attempts": [
                _PRIOR_ATTEMPT_KINDS["zero_token_failure_retried_class"]()
            ]
        }
    )
    assert compute_spend([one], include_embeddings=False)[0] == pytest.approx(
        _ceiling_usd()
    )
    assert compute_spend([two], include_embeddings=False)[0] == pytest.approx(
        2 * _ceiling_usd()
    )


def test_count_failed_generation_attempts_covers_every_attempt() -> None:
    prior = _attempt(failure=RETRIED_MESSAGES[0], reached_generation=True)  # 2
    final = _failed_generation_record(SCHEMA_CLASSES[0])  # 1
    retried = final.model_copy(update={"prior_attempts": [prior]})
    assert measure.count_failed_generation_attempts([retried]) == 3
    assert measure.count_failed_generation_attempts([final]) == 1


def test_embedding_estimate_counts_one_per_attempt() -> None:
    retried = _success_record(1000, 100).model_copy(
        update={
            "prior_attempts": [
                _attempt(error_type="ReadTimeout", attempt=1),
                _attempt(error_type="ReadTimeout", attempt=2),
            ]
        }
    )
    with_emb, _ = compute_spend([retried], include_embeddings=True)
    without_emb, _ = compute_spend([retried], include_embeddings=False)
    one_embedding = (
        measure.ESTIMATED_EMBEDDING_TOKENS_PER_QUERY
        * measure.EMBEDDING_PRICE_PER_1M
        / 1_000_000.0
    )
    # two prior attempts plus the final record: three embedding estimates
    assert with_emb - without_emb == pytest.approx(3 * one_embedding)


def test_records_without_prior_attempts_price_exactly_as_before() -> None:
    recs = [
        _success_record(5000, 200, qid="a"),
        _failed_generation_record(SCHEMA_CLASSES[0], qid="b"),
        _failed_generation_record(RETRIED_MESSAGES[0], qid="c"),
    ]
    assert all(r.prior_attempts == [] for r in recs)
    with_emb, _ = compute_spend(recs)
    without_emb, _ = compute_spend(recs, include_embeddings=False)
    assert without_emb == pytest.approx(
        _old_spend(recs, include_embeddings=False) + 3 * _ceiling_usd()
    )
    assert with_emb == pytest.approx(_old_spend(recs) + 3 * _ceiling_usd())


# --- 06.3.6-07: the O15 rerank spend line (D-176, T-06.3.6-23) ---------------------------

SPEND_BEFORE_THE_RERANK_LINE = (
    Path(__file__).parent
    / "fixtures"
    / "compute_spend_before_the_rerank_line_685258c1.json"
)
PROBE_FILE = (
    REPO_ROOT
    / ".planning"
    / "phases"
    / "06.3.6-quality-levers-measured-as-arms-reranker-graph-repair-by-dia"
    / "06.3.6-PROBE.md"
)


def _rerank_record(
    qid: str,
    *,
    cost: float | None,
    arm: str = "hybrid+rerank",
    outcome: str = "completed",
) -> RunRecord:
    """A rerank-arm record whose rerank attempt reported `cost` (None: unreported)."""
    from lancet_eval.client import RerankMeta

    return RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm=arm,
        outcome="success",
        node_timings=[
            NodeTiming(node_name="AssemblePrompt", duration_ms=12.0),
            NodeTiming(node_name="GenerateAnswer", duration_ms=900.0),
        ],
        workflow_meta=WorkflowWireMeta(
            prompt_tokens=1000,
            completion_tokens=100,
            rerank=RerankMeta(
                latency_ms=120,
                cost_credits=cost or 0.0,
                cost_reported=cost is not None,
                outcome=outcome,
            ),
        ),
    )


def _without_rerank(records: list[RunRecord]) -> list[RunRecord]:
    out = []
    for rec in records:
        meta = rec.workflow_meta
        assert meta is not None
        stripped = meta.model_copy(update={"rerank": None})
        out.append(rec.model_copy(update={"workflow_meta": stripped}))
    return out


def test_the_unreported_call_ceiling_is_the_probe_value() -> None:
    """C13: the provisional ceiling is the value plan 06.3.6-01 recorded."""
    import re

    text = PROBE_FILE.read_text(encoding="utf-8")
    match = re.search(
        r"Provisional RERANK_UNREPORTED_CALL_CEILING_USD:\s*([0-9.eE+-]+)", text
    )
    assert match is not None
    assert measure.RERANK_UNREPORTED_CALL_CEILING_USD == float(match.group(1))
    assert measure.RERANK_UNREPORTED_CALL_CEILING_USD == pytest.approx(6.6e-07)


def test_every_committed_journal_prices_byte_identically() -> None:
    """The rerank line is added only when `workflow_meta.rerank` is present."""
    import json

    from lancet_eval.journal import load_records

    golden = json.loads(SPEND_BEFORE_THE_RERANK_LINE.read_text(encoding="utf-8"))
    assert len(golden) == 13
    for rel, expected in golden.items():
        if "spend_usd" not in expected:
            continue
        records = load_records(REPO_ROOT / rel)
        assert len(records) == expected["records"], rel
        assert not any(
            r.workflow_meta is not None and r.workflow_meta.rerank is not None
            for r in records
        ), rel
        with_emb, _ = compute_spend(records)
        without_emb, _ = compute_spend(records, include_embeddings=False)
        assert repr(with_emb) == expected["spend_usd"], rel
        assert repr(without_emb) == expected["spend_usd_no_embeddings"], rel


def test_two_reported_rerank_costs_and_one_unreported_call_are_added() -> None:
    c1, c2 = 1.5e-06, 2.5e-06
    records = [
        _rerank_record("a", cost=c1),
        _rerank_record("b", cost=c2),
        _rerank_record("c", cost=None),
    ]
    added = compute_spend(records)[0] - compute_spend(_without_rerank(records))[0]
    assert added == pytest.approx(
        c1 + c2 + measure.RERANK_UNREPORTED_CALL_CEILING_USD, abs=1e-15
    )


def test_the_rerank_line_is_priced_with_or_without_embeddings() -> None:
    records = [_rerank_record("a", cost=3e-06)]
    for include in (True, False):
        added = (
            compute_spend(records, include_embeddings=include)[0]
            - compute_spend(_without_rerank(records), include_embeddings=include)[0]
        )
        assert added == pytest.approx(3e-06, abs=1e-15)


def test_a_degraded_rerank_attempt_is_priced_like_any_other() -> None:
    records = [
        _rerank_record("a", cost=None, outcome="degraded_timeout"),
        _rerank_record("b", cost=2e-06, outcome="degraded_status"),
    ]
    added = compute_spend(records)[0] - compute_spend(_without_rerank(records))[0]
    assert added == pytest.approx(
        measure.RERANK_UNREPORTED_CALL_CEILING_USD + 2e-06, abs=1e-15
    )


def test_a_rerank_attempt_on_a_prior_attempt_is_charged_too() -> None:
    from lancet_eval.client import RerankMeta

    final = _rerank_record("a", cost=1e-06)
    prior = AttemptRecord(
        attempt=1,
        outcome="error",
        workflow_meta=WorkflowWireMeta(
            rerank=RerankMeta(
                latency_ms=90,
                cost_credits=4e-06,
                cost_reported=True,
                outcome="completed",
            )
        ),
    )
    with_prior = final.model_copy(update={"prior_attempts": [prior]})
    added = compute_spend([with_prior])[0] - compute_spend([final])[0]
    embedding_of_one_more_attempt = (
        measure.ESTIMATED_EMBEDDING_TOKENS_PER_QUERY
        * measure.EMBEDDING_PRICE_PER_1M
        / 1_000_000.0
    )
    assert added == pytest.approx(4e-06 + embedding_of_one_more_attempt, abs=1e-15)


def test_a_record_without_rerank_telemetry_adds_no_rerank_line() -> None:
    records = [_success_record(5000, 200)]
    assert compute_spend(records)[0] == pytest.approx(_old_spend(records))
