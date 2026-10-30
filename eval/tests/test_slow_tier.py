"""The slow tier is opt-in: `slow` tests skip unless `LANCET_SLOW_TESTS=1` (#44)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import slow_tier

HERE = Path(__file__).resolve().parent

SAMPLE = """
import pytest

@pytest.mark.slow
def test_slow():
    pass

def test_fast():
    pass
"""


def _run(tmp_path: Path, env_value: str | None) -> str:
    (tmp_path / "test_sample.py").write_text(SAMPLE, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(HERE))
    env.pop(slow_tier.ENV, None)
    if env_value is not None:
        env[slow_tier.ENV] = env_value
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "slow_tier",
            "-rs",
            "-q",
            "-p",
            "no:cacheprovider",
            str(tmp_path),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def test_a_slow_test_skips_by_default_naming_the_switch(tmp_path: Path) -> None:
    out = _run(tmp_path, None)
    assert "1 passed, 1 skipped" in out
    assert f"set {slow_tier.ENV}=1" in out


def test_a_slow_test_runs_when_the_tier_is_opted_in(tmp_path: Path) -> None:
    assert "2 passed" in _run(tmp_path, "1")


def test_any_other_value_keeps_the_slow_tier_off(tmp_path: Path) -> None:
    assert "1 passed, 1 skipped" in _run(tmp_path, "true")


def test_the_marker_is_registered(tmp_path: Path) -> None:
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "slow_tier", "--markers"],
        cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=str(HERE)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    ).stdout
    assert "@pytest.mark.slow:" in out
