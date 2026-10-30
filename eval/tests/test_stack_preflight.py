"""06.4 D-200: `lancet-eval preflight --stack` and the split-less arm-mode canaries.

The stack preflight is the one live check each platform runs against a quickstart stack
that has no eval store: the D-199 drive-environment check, gateway and engine
reachability, and the arm-mode canaries of every registry arm over the committed
`qs-` manifest. These tests prove it offline with `httpx_mock` stubs.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock
from test_preflight_canary import (
    SPLIT_FILE,
    _mock_arm_responses,
    _request_bodies,
)
from typer.testing import CliRunner

import lancet_eval.preflight as preflight_module
from lancet_eval.arms import ARM_REGISTRY
from lancet_eval.cli import app
from lancet_eval.config import EvalSettings
from lancet_eval.preflight import (
    PreflightCheckResult,
    check_arm_mode_canaries,
)

runner = CliRunner()

_STACK_CHECK_NAMES = [
    "drive_environment",
    "gateway_reachable",
    "engine_reachable",
    "arm_mode_canaries",
]
_SECRET = "sk-or-v1-a-secret-that-must-never-be-printed"


@pytest.fixture(autouse=True)
def _clean_engine_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No engine graph or lever override variable leaks in from the host shell."""
    import os

    for name in list(os.environ):
        if name.upper().startswith((
            "LANCET_ENGINE__GRAPH__",
            "LANCET_ENGINE__LEVERS__",
        )):
            monkeypatch.delenv(name, raising=False)


def _settings() -> EvalSettings:
    return EvalSettings(gateway_url="http://testserver")


def _write_manifest(
    tmp_path: Path, ids: tuple[str, ...] = ("qs-one", "qs-two", "qs-three")
) -> Path:
    path = tmp_path / "canary.arms.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({
                "question_id": qid,
                "question": f"What does quickstart sample {qid} say?",
                "min_retrieved_chunks": 1,
            })
            for qid in ids
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _mock_health(httpx_mock: HTTPXMock, status_code: int = 200) -> None:
    body: dict[str, Any] = (
        {"status": "ok", "engine": {"status": "ok"}}
        if status_code == 200
        else {"status": "unavailable", "engine": {"error": "connection refused"}}
    )
    httpx_mock.add_response(
        url="http://testserver/health",
        status_code=status_code,
        json=body,
        is_reusable=True,
    )


def _rag_bodies(httpx_mock: HTTPXMock) -> list[dict[str, Any]]:
    return _request_bodies(httpx_mock)


def test_d200_stack_preflight_passes_in_order_with_no_store_checks(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    _mock_health(httpx_mock)
    _mock_arm_responses(httpx_mock)
    manifest = _write_manifest(tmp_path)

    with httpx.Client(base_url="http://testserver") as client:
        results = preflight_module.run_stack_preflight(
            _settings(), manifest, client=client
        )

    assert [r.name for r in results] == _STACK_CHECK_NAMES
    assert all(r.passed for r in results), [r.message for r in results if not r.passed]
    names = {r.name for r in results}
    assert names.isdisjoint({"store_isolation", "index_identity", "openrouter_api"})
    # Rows x registry arms, by construction: 3 x 9 = 27 for the quickstart manifest.
    assert len(_rag_bodies(httpx_mock)) == 3 * len(ARM_REGISTRY)


def test_d200_stack_preflight_builds_and_closes_its_own_client(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    _mock_health(httpx_mock)
    _mock_arm_responses(httpx_mock)

    results = preflight_module.run_stack_preflight(
        _settings(), _write_manifest(tmp_path)
    )

    assert [r.name for r in results] == _STACK_CHECK_NAMES
    assert all(r.passed for r in results)


def test_d200_stack_preflight_fails_at_drive_environment_before_any_request(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LANCET_ENGINE__LEVERS__DEFAULTS", "")

    def _no_client(*args: Any, **kwargs: Any) -> httpx.Client:
        raise AssertionError("a client was built after a drive-environment refusal")

    monkeypatch.setattr(httpx, "Client", _no_client)

    results = preflight_module.run_stack_preflight(
        _settings(), _write_manifest(tmp_path)
    )

    assert [r.name for r in results] == ["drive_environment"]
    assert not results[0].passed
    assert "LANCET_ENGINE__LEVERS__DEFAULTS" in results[0].message
    assert httpx_mock.get_requests() == []


def test_d200_stack_preflight_unreachable_gateway_sends_no_canary(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_exception(
        httpx.ConnectError("refused"), url="http://testserver/health"
    )

    with httpx.Client(base_url="http://testserver") as client:
        results = preflight_module.run_stack_preflight(
            _settings(), _write_manifest(tmp_path), client=client
        )

    assert [r.name for r in results] == [
        "drive_environment",
        "gateway_reachable",
        "engine_reachable",
    ]
    assert results[0].passed
    assert not results[1].passed
    assert not results[2].passed
    assert _rag_bodies(httpx_mock) == []


def test_d200_stack_preflight_unhealthy_engine_sends_no_canary(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    _mock_health(httpx_mock, status_code=503)

    with httpx.Client(base_url="http://testserver") as client:
        results = preflight_module.run_stack_preflight(
            _settings(), _write_manifest(tmp_path), client=client
        )

    assert [r.name for r in results][-1] == "engine_reachable"
    assert results[1].passed
    assert not results[2].passed
    assert _rag_bodies(httpx_mock) == []


def test_d200_stack_preflight_reports_a_failed_canary(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    _mock_health(httpx_mock)
    _mock_arm_responses(httpx_mock, omit_ablation=("hybrid",))

    with httpx.Client(base_url="http://testserver") as client:
        results = preflight_module.run_stack_preflight(
            _settings(), _write_manifest(tmp_path), client=client
        )

    assert [r.name for r in results] == _STACK_CHECK_NAMES
    assert not results[-1].passed
    assert "qs-one (hybrid)" in results[-1].message


def test_d200_arm_canaries_without_a_split_read_no_split_and_send_qs_rows(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lancet_eval.split as split_module

    def _must_not_load(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("load_split was called with split_path=None")

    monkeypatch.setattr(split_module, "load_split", _must_not_load)
    _mock_arm_responses(httpx_mock)
    arms = ("dense-only", "hybrid", "hybrid+graph")

    with httpx.Client(base_url="http://testserver") as client:
        res = check_arm_mode_canaries(
            client,
            arms=arms,
            canary_path=_write_manifest(tmp_path),
            split_path=None,
        )

    assert res.name == "arm_mode_canaries"
    assert res.passed, res.message
    assert len(_rag_bodies(httpx_mock)) == 3 * len(arms)


def test_d200_arm_canaries_without_a_split_refuse_a_non_qs_id_before_any_request(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    manifest = _write_manifest(tmp_path, ids=("qs-one", "mhr-0d5e238015ef"))

    with httpx.Client(base_url="http://testserver") as client:
        res = check_arm_mode_canaries(
            client, arms=("hybrid",), canary_path=manifest, split_path=None
        )

    assert not res.passed
    assert "mhr-0d5e238015ef" in res.message
    assert "qs-" in res.message
    assert res.detail["refused_ids"] == ["mhr-0d5e238015ef"]
    assert "qs-one" not in res.detail["refused_ids"]
    assert httpx_mock.get_requests() == []


def test_d200_arm_canaries_with_a_split_still_refuse_dev_and_heldout_ids(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    from lancet_eval.split import load_split

    banned = sorted(load_split(SPLIT_FILE).dev_ids)[0]
    manifest = _write_manifest(tmp_path, ids=(banned,))

    with httpx.Client(base_url="http://testserver") as client:
        res = check_arm_mode_canaries(
            client, arms=("hybrid",), canary_path=manifest, split_path=SPLIT_FILE
        )

    assert not res.passed
    assert banned in res.message
    assert httpx_mock.get_requests() == []


def test_d200_arm_canaries_with_a_split_do_not_require_the_qs_prefix(
    tmp_path: Path, httpx_mock: HTTPXMock
) -> None:
    """A given split path behaves as before: only dev and held-out IDs are barred."""
    _mock_arm_responses(httpx_mock)
    manifest = _write_manifest(tmp_path, ids=("not-in-any-split",))

    with httpx.Client(base_url="http://testserver") as client:
        res = check_arm_mode_canaries(
            client, arms=("hybrid",), canary_path=manifest, split_path=SPLIT_FILE
        )

    assert res.passed, res.message


def _fake_stack(calls: list[tuple[Any, ...]], *, fail: bool = False) -> Any:
    def fake(
        settings: Any, canary_path: Path, client: Any = None
    ) -> list[PreflightCheckResult]:
        calls.append((settings, canary_path, client))
        return [
            PreflightCheckResult(name="drive_environment", passed=True, message="ok"),
            PreflightCheckResult(
                name="arm_mode_canaries",
                passed=not fail,
                message="all canaries passed"
                if not fail
                else "Canary qs-one (hybrid) failed",
            ),
        ]

    return fake


def test_d200_cli_stack_exits_0_on_all_pass_and_never_prints_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setenv("OPENROUTER_API_KEY", _SECRET)
    monkeypatch.setattr(preflight_module, "run_stack_preflight", _fake_stack(calls))
    monkeypatch.setattr(
        preflight_module,
        "run_preflight_checks",
        lambda *a, **k: pytest.fail("--stack must not run the corpus preflight"),
    )

    result = runner.invoke(
        app,
        ["preflight", "--stack", "--corpus", "ignored_corpus"],
        env={"COLUMNS": "240"},
    )

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert (
        str(calls[0][1])
        .replace("\\", "/")
        .endswith("eval/corpora/quickstart/canary.arms.jsonl")
    )
    assert "drive_environment" in result.output
    assert "arm_mode_canaries" in result.output
    assert _SECRET not in result.output


def test_d200_cli_stack_passes_the_canaries_option_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(preflight_module, "run_stack_preflight", _fake_stack(calls))
    manifest = _write_manifest(tmp_path)

    result = runner.invoke(
        app,
        ["preflight", "--stack", "--canaries", str(manifest)],
        env={"COLUMNS": "240"},
    )

    assert result.exit_code == 0, result.output
    assert Path(calls[0][1]) == manifest


def test_d200_cli_stack_exits_1_on_a_failed_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setenv("OPENROUTER_API_KEY", _SECRET)
    monkeypatch.setattr(
        preflight_module, "run_stack_preflight", _fake_stack(calls, fail=True)
    )

    result = runner.invoke(app, ["preflight", "--stack"], env={"COLUMNS": "240"})

    assert result.exit_code == 1
    assert "Canary qs-one (hybrid) failed" in " ".join(result.output.split())
    assert _SECRET not in result.output


@pytest.mark.parametrize(
    "extra",
    [
        ["--judged"],
        ["--accept-known-miss", "q:graph-on:require_graph_node:D-94"],
        ["--store", "eval-s1"],
    ],
)
def test_d200_cli_stack_rejects_options_it_cannot_honour(
    extra: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(preflight_module, "run_stack_preflight", _fake_stack(calls))

    result = runner.invoke(
        app, ["preflight", "--stack", *extra], env={"COLUMNS": "240"}
    )

    assert result.exit_code == 2
    assert calls == []
