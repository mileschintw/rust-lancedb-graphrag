"""The engine and gateway test-target gates check floors, not exact counts (#44).

Each gate runs under `sh` with a fake `cargo` or `go` first on PATH that prints a recorded
listing, so no build runs. Skipped when no `sh` is on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SH = shutil.which("sh")

pytestmark = pytest.mark.skipif(SH is None, reason="needs a POSIX sh on PATH")

ENGINE_TARGETS = {
    "unittests src\\lib.rs": 854,
    "unittests src\\main.rs": 0,
    "unittests src\\bin\\inspect_lancedb.rs": 58,
    "unittests src\\bin\\reconcile_eval_store.rs": 18,
    "unittests src\\bin\\backfill_evidence_metadata.rs": 14,
    "unittests src\\bin\\generate_from_context.rs": 9,
    "tests\\config_startup.rs": 27,
}

GATEWAY_PACKAGES = {
    "gateway": 83,
    "gateway/db": 7,
    "gateway/internal/config": 4,
    "gateway/internal/engineclient": 1,
    "gateway/internal/sse": 17,
    "gateway/internal/telemetry": 11,
    "gateway/internal/notests": 0,
}


def _cargo_listing(targets: dict[str, int]) -> str:
    lines = ["   Compiling engine v0.1.0", "    Finished `test` profile"]
    for target, count in targets.items():
        lines.append(f"     Running {target} (engine\\target\\debug\\deps\\x.exe)")
        lines.extend(f"t{i}: test" for i in range(count))
        lines.append(f"{count} tests, 0 benchmarks")
    return "\n".join(lines) + "\n"


def _go_listing(packages: dict[str, int]) -> str:
    lines = []
    for pkg, count in packages.items():
        path = f"github.com/lancet/{pkg}"
        if count == 0:
            lines.append(f"?   \t{path}\t[no test files]")
            continue
        lines.extend(f"TestT{i}" for i in range(count))
        lines.append(f"ok  \t{path}\t0.012s")
    return "\n".join(lines) + "\n"


def _run(tmp_path: Path, tool: str, listing: str, script: str) -> tuple[int, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "listing.txt").write_text(listing, encoding="utf-8", newline="\n")
    fake = bin_dir / tool
    fake.write_text(
        f'#!/bin/sh\ncat "{(tmp_path / "listing.txt").as_posix()}"\n',
        encoding="utf-8",
        newline="\n",
    )
    fake.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    done = subprocess.run(
        [SH, f"scripts/{script}"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


def _engine(tmp_path: Path, targets: dict[str, int]) -> tuple[int, str]:
    return _run(tmp_path, "cargo", _cargo_listing(targets), "engine-test-targets.sh")


def _gateway(tmp_path: Path, packages: dict[str, int]) -> tuple[int, str]:
    return _run(tmp_path, "go", _go_listing(packages), "gateway-test-targets.sh")


def test_the_engine_gate_passes_at_its_floors(tmp_path: Path) -> None:
    code, out = _engine(tmp_path, ENGINE_TARGETS)
    assert code == 0, out
    assert "TOTAL: 980" in out


def test_the_engine_gate_passes_when_a_lane_adds_tests(tmp_path: Path) -> None:
    code, out = _engine(tmp_path, {**ENGINE_TARGETS, "unittests src\\lib.rs": 900})
    assert code == 0, out


def test_the_engine_gate_fails_a_target_below_its_floor(tmp_path: Path) -> None:
    targets = {**ENGINE_TARGETS, "unittests src\\bin\\inspect_lancedb.rs": 57}
    code, out = _engine(tmp_path, targets)
    assert code == 1
    assert "src/bin/inspect_lancedb.rs has 57 tests, below its floor of 58" in out


def test_the_engine_gate_fails_a_missing_target(tmp_path: Path) -> None:
    targets = {k: v for k, v in ENGINE_TARGETS.items() if "config_startup" not in k}
    code, out = _engine(tmp_path, targets)
    assert code == 1
    assert "tests/config_startup.rs is absent" in out


def test_the_engine_gate_fails_a_new_target_with_no_floor(tmp_path: Path) -> None:
    code, out = _engine(tmp_path, {**ENGINE_TARGETS, "tests\\new_suite.rs": 3})
    assert code == 1
    assert "tests/new_suite.rs reports 3 tests but has no floor" in out


def test_the_engine_gate_fails_when_nothing_is_listed(tmp_path: Path) -> None:
    code, out = _run(
        tmp_path, "cargo", "error[E0425]: oops\n", "engine-test-targets.sh"
    )
    assert code == 1
    assert "listed no target" in out


def test_the_gateway_gate_passes_at_and_above_its_floors(tmp_path: Path) -> None:
    code, out = _gateway(tmp_path, {**GATEWAY_PACKAGES, "gateway": 90})
    assert code == 0, out
    assert "TOTAL: 130" in out


def test_the_gateway_gate_fails_a_package_below_its_floor(tmp_path: Path) -> None:
    code, out = _gateway(tmp_path, {**GATEWAY_PACKAGES, "gateway/internal/sse": 16})
    assert code == 1
    assert "gateway/internal/sse has 16 tests, below its floor of 17" in out


def test_the_gateway_gate_fails_a_missing_package(tmp_path: Path) -> None:
    packages = {k: v for k, v in GATEWAY_PACKAGES.items() if k != "gateway/db"}
    code, out = _gateway(tmp_path, packages)
    assert code == 1
    assert "package gateway/db is absent" in out


def test_the_gateway_gate_fails_a_new_package_with_no_floor(tmp_path: Path) -> None:
    code, out = _gateway(tmp_path, {**GATEWAY_PACKAGES, "gateway/internal/new": 2})
    assert code == 1
    assert "gateway/internal/new reports 2 tests but has no floor" in out
