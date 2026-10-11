"""Tests for the D-199 drive-environment refusal (06.4-03).

The harness cannot read the engine's own environment, so the refusal covers the shell
that launches the drive. These tests pin the two refused prefixes, the warn-only set,
the placement (first in `run_preflight_checks`, before journal I/O in a gate-stage
drive) and that a variable's value never reaches a message.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from lancet_eval import preflight
from lancet_eval.run import drive

_SECRET = "sk-or-v1-not-a-real-key-but-shaped-like-one"


@pytest.mark.parametrize(
    "name",
    [
        "LANCET_ENGINE__LEVERS__DEFAULTS",
        "LANCET_ENGINE__GRAPH__SEED_MATCH_MIN_SCORE",
        "LANCET_ENGINE__GRAPH__CONTEXT_DEFAULT_ENABLED",
        "LANCET_ENGINE__GRAPH__GRAPH_V2_CHUNK_PRECISION",
    ],
)
def test_d199_each_refused_prefix_fails_and_names_the_variable(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    monkeypatch.setenv(name, _SECRET)

    res = preflight.check_drive_environment(os.environ)

    assert res.name == "drive_environment"
    assert res.passed is False
    assert name in res.message
    assert _SECRET not in res.message
    assert _SECRET not in str(res.detail)
    assert "unset it" in res.message


def test_d199_a_lower_case_name_is_refused_too() -> None:
    res = preflight.check_drive_environment(
        {"lancet_engine__graph__max_seeds": _SECRET}
    )

    assert res.passed is False
    assert "lancet_engine__graph__max_seeds" in res.message
    assert _SECRET not in res.message


def test_d199_the_empty_value_is_still_a_set_variable() -> None:
    """A blank `LANCET_ENGINE__LEVERS__DEFAULTS` means "no default lever" to the engine."""
    res = preflight.check_drive_environment({"LANCET_ENGINE__LEVERS__DEFAULTS": ""})

    assert res.passed is False
    assert "LANCET_ENGINE__LEVERS__DEFAULTS" in res.message


def test_d199_every_refused_variable_is_named() -> None:
    res = preflight.check_drive_environment(
        {
            "LANCET_ENGINE__LEVERS__DEFAULTS": "rerank",
            "LANCET_ENGINE__GRAPH__MAX_SEEDS": "9",
            "PATH": "/usr/bin",
        }
    )

    assert res.passed is False
    assert "LANCET_ENGINE__LEVERS__DEFAULTS" in res.message
    assert "LANCET_ENGINE__GRAPH__MAX_SEEDS" in res.message
    assert "PATH" not in res.message


@pytest.mark.parametrize(
    "name",
    [
        "RUST_LOG",
        "LANCET_CONFIG_DIR",
        "LANCET_ENGINE__WORKFLOW__RETRIEVE_TIMEOUT_MS",
        "LANCET_OPENROUTER__RERANK_ENDPOINT",
    ],
)
def test_d199_the_warn_only_set_passes_and_is_reported_in_the_detail(name: str) -> None:
    res = preflight.check_drive_environment({name: _SECRET, "HOME": "/home/x"})

    assert res.passed is True
    assert name in res.detail["warned_variables"]
    assert res.detail["warn_only"]
    assert "RUST_LOG" in res.detail["warn_only"]
    assert _SECRET not in res.message
    assert _SECRET not in str(res.detail)


def test_d199_a_clean_environment_passes() -> None:
    res = preflight.check_drive_environment({"PATH": "/usr/bin"})

    assert res.passed is True
    assert res.detail["refused_variables"] == []
    assert res.detail["warned_variables"] == []


def test_d199_preflight_runs_the_environment_check_first_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.setenv("LANCET_ENGINE__GRAPH__SEED_MATCH_MIN_SCORE", _SECRET)

    with httpx.Client(base_url="http://testserver") as client:
        results = preflight.run_preflight_checks("multihop_rag_heldout", client=client)

    assert [r.name for r in results] == ["drive_environment"]
    assert results[0].passed is False
    assert httpx_mock.get_requests() == []


def test_d199_a_gate_stage_drive_refuses_before_any_journal_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.setenv("LANCET_ENGINE__GRAPH__SEED_MATCH_MIN_SCORE", _SECRET)
    j_path = tmp_path / "journal.jsonl"

    with pytest.raises(ValueError, match="LANCET_ENGINE__GRAPH__SEED_MATCH_MIN_SCORE") as exc:
        drive(
            corpus="graphrag_bench",
            journal_path=j_path,
            stage_spend_cap=10.0,
            limit=1,
            workers=1,
            max_retries=0,
            gate_stage="s1",
            client=httpx.Client(base_url="http://testserver"),
        )

    assert _SECRET not in str(exc.value)
    assert not j_path.exists()
    assert list(tmp_path.iterdir()) == []
    assert httpx_mock.get_requests() == []


def test_d199_a_gate_stage_drive_refuses_the_levers_prefix_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock
) -> None:
    monkeypatch.setenv("LANCET_ENGINE__LEVERS__DEFAULTS", "")

    with pytest.raises(ValueError, match="LANCET_ENGINE__LEVERS__DEFAULTS"):
        drive(
            corpus="graphrag_bench",
            journal_path=tmp_path / "journal.jsonl",
            stage_spend_cap=10.0,
            limit=1,
            max_retries=0,
            gate_stage="s1",
            client=httpx.Client(base_url="http://testserver"),
        )

    assert httpx_mock.get_requests() == []


def test_d199_explicit_field_checks_stay_out_of_the_score_path() -> None:
    """Orchestrator note 10: `score` must keep scoring the frozen runs of record.

    The per-arm explicit-field check runs only where a live response exists (the arm
    canaries and the gate-stage first-record gate). A new clause letter in
    `provenance_failures` would be evaluated on every record of the committed journals
    and would raise `KeyError` in the tally.
    """
    import inspect

    from lancet_eval import provenance, score

    assert provenance.ZERO_TOLERANCE_CODES == frozenset("abcdfhj")
    assert provenance._OK_CODES == frozenset("abcdefhij")
    for source in (
        inspect.getsource(provenance.provenance_failures),
        inspect.getsource(score._provenance_scan),
    ):
        assert "explicit_field_failures" not in source
    assert 'dict.fromkeys("abcdefghij", 0)' in inspect.getsource(score._provenance_scan)
    assert 'frozenset("abcdfhj")' in inspect.getsource(provenance)
