"""Tests for the D-94 accepted-known-miss option on preflight.

The option lets drive 1's preflight carry exactly one named graph-floor miss
(canary ``mhr-0d5e238015ef``, ``graph-on``, ``require_graph_node``) and nothing else.
Every test here uses stubbed SSE responses: no network access and no provider call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from lancet_eval.cli import app
from lancet_eval.config import EvalSettings, repo_root
from lancet_eval.preflight import (
    ACCEPTED_KNOWN_MISS_REGISTRY,
    AcceptedKnownMiss,
    CanaryKnownMissOutcome,
    PreflightCheckResult,
    PreflightError,
    check_canary_floors,
    parse_accepted_known_miss,
    run_preflight_checks,
    validate_accepted_known_misses,
)

CANARY_PATH = repo_root() / "eval" / "corpora" / "multihop_rag" / "canary.jsonl"
D94_VALUE = "mhr-0d5e238015ef:graph-on:require_graph_node:D-94"
TARGET = ("mhr-0d5e238015ef", "graph-on")
TWIN = ("mhr-0d5e238015ef", "graph-off")
OTHER_GRAPH_CANARY = ("mhr-12912d800c0c", "graph-on")
PROBE_QUERY = "What hospital program helps teenage patients in Nebraska?"

runner = CliRunner()


def _accepted() -> AcceptedKnownMiss:
    return parse_accepted_known_miss(D94_VALUE)


def _query_to_question_id() -> dict[str, str]:
    rows = [
        json.loads(line)
        for line in CANARY_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {row["question"]: row["question_id"] for row in rows}


@dataclass(frozen=True)
class Behaviour:
    """What one (question_id, arm) canary query reports on the wire."""

    chunk_count: int = 2
    graph_nodes: int = 3
    ablation_notice: bool = True
    success: bool = True
    durations: dict[str, float] | None = None


DEFAULT_DURATIONS = {
    "RetrieveHybrid": 100.0,
    "ExtractGraphContext": 200.0,
    "AssemblePrompt": 50.0,
    "GenerateAnswer": 300.0,
}


def _sse(events: list[tuple[str, dict[str, Any]]]) -> str:
    return "".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events
    )


def _canary_events(arm: str, behaviour: Behaviour) -> list[tuple[str, dict[str, Any]]]:
    graph_off = arm == "graph-off"
    notices: list[dict[str, Any]] = []
    if graph_off and behaviour.ablation_notice:
        notices.append(
            {"code": "GRAPH_ABLATION", "typed_code": 18, "message": "Graph disabled"}
        )
    chunks = [
        {"chunk_id": f"c{i}", "document_id": "doc1", "is_truncated": False}
        for i in range(behaviour.chunk_count)
    ]
    events: list[tuple[str, dict[str, Any]]] = []
    if behaviour.success:
        events.append(
            (
                "final_answer",
                {
                    "answer": "Test answer",
                    "notices": notices,
                    "snapshot": {"retrieved_chunks": chunks},
                },
            )
        )
    for node, duration in (behaviour.durations or DEFAULT_DURATIONS).items():
        events.append(("node_completed", {"node_name": node, "duration_ms": duration}))
    completed: dict[str, Any] = {
        "success": behaviour.success,
        "total_duration_ms": 1000,
        "notices": notices,
        "metadata": {
            "vector_count": behaviour.chunk_count,
            "bm25_count": 0,
            "graph_node_count": 0 if graph_off else behaviour.graph_nodes,
        },
    }
    if not behaviour.success:
        completed["error_kind"] = 1
        completed["error_message"] = "stubbed workflow failure"
        completed["partial_snapshot"] = {"retrieved_chunks": chunks}
    events.append(("workflow_completed", completed))
    return events


def _mock_queries(
    httpx_mock: HTTPXMock,
    overrides: dict[tuple[str, str], Behaviour] | None = None,
    *,
    probe_index_generation: str | None = "gen1",
) -> None:
    """Serve every canary query per (question_id, arm), plus the corpus probe."""
    by_query = _query_to_question_id()
    per_key = overrides or {}

    def callback(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        query = body["query"]
        if query not in by_query:
            snapshot: dict[str, Any] = {"retrieved_chunks": []}
            if probe_index_generation is not None:
                snapshot["index_generation"] = probe_index_generation
            text = _sse([("final_answer", {"answer": "A", "snapshot": snapshot})])
        else:
            arm = "graph-off" if body.get("disable_graph_context") else "graph-on"
            behaviour = per_key.get((by_query[query], arm), Behaviour())
            text = _sse(_canary_events(arm, behaviour))
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/event-stream"},
            text=text,
        )

    httpx_mock.add_callback(callback, url="http://testserver/rag/query", is_reusable=True)


def _client() -> httpx.Client:
    return httpx.Client(base_url="http://testserver")


def _budget_config(tmp_path: Path, prompt_ms: int) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f"""
        [engine.workflow]
        reformulate_timeout_ms = 5000
        query_embedding_timeout_ms = 2000
        retrieve_timeout_ms = 2500
        graph_operation_timeout_ms = 10000
        graph_node_timeout_ms = 12500
        prompt_timeout_ms = {prompt_ms}
        generation_node_timeout_ms = 65000
        """,
        encoding="utf-8",
    )
    return path


# --- registry, parser and validator -------------------------------------------------


def test_registry_holds_exactly_the_d94_entry() -> None:
    assert dict(ACCEPTED_KNOWN_MISS_REGISTRY) == {
        ("mhr-0d5e238015ef", "graph-on", "require_graph_node"): "D-94"
    }


def test_registry_key_resolves_to_a_canary_row_that_requires_a_graph_node() -> None:
    (question_id, arm, check), _ = next(iter(ACCEPTED_KNOWN_MISS_REGISTRY.items()))
    rows = [
        json.loads(line)
        for line in CANARY_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matching = [
        r for r in rows if r["question_id"] == question_id and r["graph_arm"] == arm
    ]
    assert len(matching) == 1
    assert matching[0][check] is True


def test_d94_value_parses_and_validates() -> None:
    miss = parse_accepted_known_miss(D94_VALUE)
    assert miss == AcceptedKnownMiss(
        question_id="mhr-0d5e238015ef",
        graph_arm="graph-on",
        check="require_graph_node",
        decision_id="D-94",
    )
    assert validate_accepted_known_misses([miss]) == (miss,)


@pytest.mark.parametrize(
    "raw",
    [
        "mhr-0d5e238015ef:graph-on:require_graph_node",
        "mhr-0d5e238015ef:graph-on:require_graph_node:D-94:extra",
        "mhr-0d5e238015ef:graph-on::D-94",
        ":graph-on:require_graph_node:D-94",
        "",
    ],
)
def test_malformed_value_is_rejected_by_the_parser(raw: str) -> None:
    with pytest.raises(ValueError, match="question_id"):
        parse_accepted_known_miss(raw)


@pytest.mark.parametrize(
    "raw",
    [
        # a real graph canary that is not registered
        "mhr-12912d800c0c:graph-on:require_graph_node:D-94",
        # the ablation twin's arm
        "mhr-0d5e238015ef:graph-off:require_graph_node:D-94",
        # other checks on the registered canary
        "mhr-0d5e238015ef:graph-on:require_ablation_notice:D-94",
        "mhr-0d5e238015ef:graph-on:min_retrieved_chunks:D-94",
        # a different decision ID
        "mhr-0d5e238015ef:graph-on:require_graph_node:D-93",
        # unknown question and unknown arm
        "mhr-000000000000:graph-on:require_graph_node:D-94",
        "mhr-0d5e238015ef:graph-both:require_graph_node:D-94",
    ],
)
def test_unregistered_or_mismatched_value_is_rejected(raw: str) -> None:
    with pytest.raises((ValueError, PreflightError)):
        validate_accepted_known_misses([parse_accepted_known_miss(raw)])


def test_duplicate_value_is_rejected() -> None:
    with pytest.raises(PreflightError, match="duplicate"):
        validate_accepted_known_misses([_accepted(), _accepted()])


def test_registered_key_is_rejected_when_the_manifest_row_does_not_require_it(
    tmp_path: Path,
) -> None:
    rows = [
        json.loads(line)
        for line in CANARY_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for row in rows:
        if (row["question_id"], row["graph_arm"]) == TARGET:
            row["require_graph_node"] = False
    edited = tmp_path / "canary.jsonl"
    edited.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    with pytest.raises(PreflightError, match="require_graph_node"):
        validate_accepted_known_misses([_accepted()], canary_path=edited)


# --- status field -------------------------------------------------------------------


def test_status_is_derived_from_passed_when_not_given() -> None:
    assert PreflightCheckResult(name="x", passed=True).status == "pass"
    assert PreflightCheckResult(name="x", passed=False).status == "fail"


def test_status_accepted_known_miss_requires_passed_true() -> None:
    with pytest.raises(ValidationError):
        PreflightCheckResult(name="x", passed=False, status="accepted_known_miss")
    with pytest.raises(ValidationError):
        PreflightCheckResult(name="x", passed=False, status="pass")
    with pytest.raises(ValidationError):
        PreflightCheckResult(name="x", passed=True, status="fail")
    ok = PreflightCheckResult(name="x", passed=True, status="accepted_known_miss")
    assert ok.status == "accepted_known_miss"


# --- check_canary_floors ------------------------------------------------------------


def test_default_without_the_option_the_miss_still_fails(
    httpx_mock: HTTPXMock,
) -> None:
    _mock_queries(httpx_mock, {TARGET: Behaviour(graph_nodes=0)})
    res = check_canary_floors(_client())
    assert res.passed is False
    assert res.status == "fail"
    assert "graph floor missed" in res.message
    assert "mhr-0d5e238015ef" in res.message


def test_option_accepts_the_single_miss_with_its_own_status(
    httpx_mock: HTTPXMock,
) -> None:
    _mock_queries(httpx_mock, {TARGET: Behaviour(graph_nodes=0)})
    res = check_canary_floors(_client(), accepted_known_misses=[_accepted()])
    assert res.passed is True
    assert res.status == "accepted_known_miss"
    entries = res.detail["accepted_known_misses"]
    assert len(entries) == 1
    assert entries[0]["decision_id"] == "D-94"
    assert entries[0]["observed_graph_node_count"] == 0
    assert entries[0]["outcome"] == "accepted_known_miss"
    assert "ACCEPTED KNOWN MISS" in res.message
    assert "D-94" in res.message
    assert "All 7 canaries passed floors" not in res.message


def test_option_reports_a_met_floor_as_pass_and_floor_met(
    httpx_mock: HTTPXMock,
) -> None:
    _mock_queries(httpx_mock, {TARGET: Behaviour(graph_nodes=3)})
    res = check_canary_floors(_client(), accepted_known_misses=[_accepted()])
    assert res.passed is True
    assert res.status == "pass"
    entries = res.detail["accepted_known_misses"]
    assert [e["outcome"] for e in entries] == ["floor_met"]
    assert entries[0]["observed_graph_node_count"] == 3


def test_option_does_not_excuse_the_other_graph_canary(httpx_mock: HTTPXMock) -> None:
    _mock_queries(
        httpx_mock,
        {TARGET: Behaviour(graph_nodes=0), OTHER_GRAPH_CANARY: Behaviour(graph_nodes=0)},
    )
    res = check_canary_floors(_client(), accepted_known_misses=[_accepted()])
    assert res.passed is False
    assert res.status == "fail"
    assert "mhr-12912d800c0c" in res.message
    assert "graph floor missed" in res.message


def test_option_does_not_excuse_the_graph_off_twin_missing_its_notice(
    httpx_mock: HTTPXMock,
) -> None:
    _mock_queries(
        httpx_mock,
        {TARGET: Behaviour(graph_nodes=0), TWIN: Behaviour(ablation_notice=False)},
    )
    res = check_canary_floors(_client(), accepted_known_misses=[_accepted()])
    assert res.passed is False
    assert "graph-off twin missing required ablation notice" in res.message


def test_option_does_not_excuse_the_canarys_own_retrieval_floor(
    httpx_mock: HTTPXMock,
) -> None:
    _mock_queries(httpx_mock, {TARGET: Behaviour(graph_nodes=0, chunk_count=0)})
    res = check_canary_floors(_client(), accepted_known_misses=[_accepted()])
    assert res.passed is False
    assert "retrieval floor missed" in res.message
    assert "mhr-0d5e238015ef" in res.message


def test_option_does_not_excuse_a_duration_over_the_effective_config_budget(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    slow = dict(DEFAULT_DURATIONS, AssemblePrompt=120.0)
    _mock_queries(httpx_mock, {TARGET: Behaviour(graph_nodes=0, durations=slow)})
    res = check_canary_floors(
        _client(),
        config_path=_budget_config(tmp_path, prompt_ms=120),
        accepted_known_misses=[_accepted()],
    )
    assert res.passed is False
    assert "AssemblePrompt" in res.message
    assert "prompt_timeout_ms" in res.message


def test_option_does_not_accept_a_miss_from_a_failed_workflow(
    httpx_mock: HTTPXMock,
) -> None:
    _mock_queries(httpx_mock, {TARGET: Behaviour(graph_nodes=0, success=False)})
    res = check_canary_floors(_client(), accepted_known_misses=[_accepted()])
    assert res.passed is False
    assert res.status == "fail"
    assert "not accepted under D-94" in res.message


def test_option_does_not_excuse_an_unreadable_config(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    res = check_canary_floors(
        _client(),
        config_path=tmp_path / "missing.toml",
        accepted_known_misses=[_accepted()],
    )
    assert res.passed is False
    assert "Failed to read engine workflow timeouts" in res.message
    assert httpx_mock.get_requests() == []


def test_rejected_option_returns_a_failed_result_before_any_request(
    httpx_mock: HTTPXMock,
) -> None:
    bad = AcceptedKnownMiss(
        question_id="mhr-12912d800c0c",
        graph_arm="graph-on",
        check="require_graph_node",
        decision_id="D-94",
    )
    res = check_canary_floors(_client(), accepted_known_misses=[bad])
    assert res.passed is False
    assert res.status == "fail"
    assert httpx_mock.get_requests() == []


# --- run_preflight_checks -----------------------------------------------------------


def _settings(tmp_path: Path) -> EvalSettings:
    return EvalSettings(
        lancedb_path=str(tmp_path / "lancedb-eval"),
        dev_lancedb_path=str(tmp_path / "lancedb-dev"),
    )


def _patch_run_preflight(
    monkeypatch: pytest.MonkeyPatch, *, identity_passes: bool
) -> None:
    from lancet_eval.seed import DocumentMap

    monkeypatch.setattr(
        "lancet_eval.preflight.load_document_map",
        lambda corpus_name: DocumentMap(corpus=corpus_name, entries={}),
    )
    monkeypatch.setattr(
        "lancet_eval.preflight.check_index_identity",
        lambda settings, corpus_name: PreflightCheckResult(
            name="index_identity",
            passed=identity_passes,
            message="stubbed identity",
        ),
    )


def _mock_health(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://testserver/health",
        status_code=200,
        json={"status": "ok", "engine": {"status": "ok"}},
        is_reusable=True,
    )


def test_run_preflight_with_option_still_fails_a_missing_index_generation(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_run_preflight(monkeypatch, identity_passes=True)
    _mock_health(httpx_mock)
    _mock_queries(
        httpx_mock, {TARGET: Behaviour(graph_nodes=0)}, probe_index_generation=None
    )
    results = run_preflight_checks(
        "multihop_rag_diag",
        settings=_settings(tmp_path),
        client=_client(),
        accepted_known_misses=[_accepted()],
    )
    by_name = {r.name: r for r in results}
    assert by_name["corpus_generation"].passed is False
    assert "No index_generation observed" in by_name["corpus_generation"].message
    assert by_name["canary_floors"].status == "accepted_known_miss"


def test_run_preflight_with_option_still_fails_a_failing_identity_check(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_run_preflight(monkeypatch, identity_passes=False)
    _mock_health(httpx_mock)
    _mock_queries(httpx_mock, {TARGET: Behaviour(graph_nodes=0)})
    results = run_preflight_checks(
        "multihop_rag_diag",
        settings=_settings(tmp_path),
        client=_client(),
        accepted_known_misses=[_accepted()],
    )
    by_name = {r.name: r for r in results}
    assert by_name["index_identity"].passed is False
    assert by_name["corpus_generation"].passed is True
    assert by_name["canary_floors"].status == "accepted_known_miss"


def test_run_preflight_rejects_a_bad_option_before_any_request(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_run_preflight(monkeypatch, identity_passes=True)
    bad = AcceptedKnownMiss(
        question_id="mhr-0d5e238015ef",
        graph_arm="graph-on",
        check="require_graph_node",
        decision_id="D-93",
    )
    with pytest.raises(PreflightError):
        run_preflight_checks(
            "multihop_rag_diag",
            settings=_settings(tmp_path),
            client=_client(),
            accepted_known_misses=[bad],
        )
    assert httpx_mock.get_requests() == []


def test_the_canary_outcome_model_rejects_an_unknown_outcome() -> None:
    with pytest.raises(ValidationError):
        CanaryKnownMissOutcome(
            question_id="mhr-0d5e238015ef",
            graph_arm="graph-on",
            check="require_graph_node",
            decision_id="D-94",
            observed_graph_node_count=0,
            outcome="pass",  # type: ignore[arg-type]
        )


# --- CLI ----------------------------------------------------------------------------


def _outcome(count: int, outcome: str) -> dict[str, Any]:
    return CanaryKnownMissOutcome(
        question_id="mhr-0d5e238015ef",
        graph_arm="graph-on",
        check="require_graph_node",
        decision_id="D-94",
        observed_graph_node_count=count,
        outcome=outcome,  # type: ignore[arg-type]
    ).model_dump()


def _accepted_results() -> list[PreflightCheckResult]:
    return [
        PreflightCheckResult(name="store_isolation", passed=True, message="ok"),
        PreflightCheckResult(
            name="canary_floors",
            passed=True,
            status="accepted_known_miss",
            message="ACCEPTED KNOWN MISS [D-94]: canary mhr-0d5e238015ef",
            detail={"accepted_known_misses": [_outcome(0, "accepted_known_miss")]},
        ),
    ]


def _invoke(*extra: str) -> Any:
    return runner.invoke(
        app,
        ["preflight", "--corpus", "multihop_rag_diag", *extra],
        env={"COLUMNS": "240"},
    )


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_cli_rejects_a_bad_option_with_exit_2_and_never_runs_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        "lancet_eval.preflight.run_preflight_checks",
        lambda *a, **k: calls.append((a, k)) or [],
    )
    result = _invoke("--accept-known-miss", "mhr-12912d800c0c:graph-on:require_graph_node:D-94")
    assert result.exit_code == 2
    assert calls == []
    assert "mhr-0d5e238015ef:graph-on:require_graph_node:D-94" in _flat(result.output)


def test_cli_accepted_miss_exits_0_and_is_reported_not_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake(*args: Any, **kwargs: Any) -> list[PreflightCheckResult]:
        seen.update(kwargs)
        return _accepted_results()

    monkeypatch.setattr("lancet_eval.preflight.run_preflight_checks", fake)
    result = _invoke("--accept-known-miss", D94_VALUE)
    assert result.exit_code == 0
    output = _flat(result.output)
    assert "ACCEPTED KNOWN MISS" in output
    assert "D-94" in output
    assert "observed 0 graph nodes" in output
    assert "Reported, not passed" in output
    assert "All preflight checks passed successfully." not in output
    assert list(seen["accepted_known_misses"]) == [_accepted()]


def test_cli_accepted_miss_with_another_failure_exits_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = [
        *_accepted_results(),
        PreflightCheckResult(name="corpus_generation", passed=False, message="nope"),
    ]
    monkeypatch.setattr(
        "lancet_eval.preflight.run_preflight_checks", lambda *a, **k: results
    )
    result = _invoke("--accept-known-miss", D94_VALUE)
    assert result.exit_code == 1
    assert "Preflight failed" in _flat(result.output)


def test_cli_without_the_option_prints_the_unchanged_success_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake(*args: Any, **kwargs: Any) -> list[PreflightCheckResult]:
        seen.update(kwargs)
        return [PreflightCheckResult(name="store_isolation", passed=True, message="ok")]

    monkeypatch.setattr("lancet_eval.preflight.run_preflight_checks", fake)
    result = _invoke()
    assert result.exit_code == 0
    assert "All preflight checks passed successfully." in _flat(result.output)
    assert "accepted_known_misses" not in seen


def test_cli_reports_a_met_floor_without_using_the_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = [
        PreflightCheckResult(
            name="canary_floors",
            passed=True,
            message="All 7 canaries passed floors against live engine budgets.",
            detail={"accepted_known_misses": [_outcome(3, "floor_met")]},
        )
    ]
    monkeypatch.setattr(
        "lancet_eval.preflight.run_preflight_checks", lambda *a, **k: results
    )
    result = _invoke("--accept-known-miss", D94_VALUE)
    assert result.exit_code == 0
    output = _flat(result.output)
    assert "met its require_graph_node floor" in output
    assert "observed 3 graph nodes" in output
    assert "D-94 exception not used" in output
    assert "All preflight checks passed successfully." in output
