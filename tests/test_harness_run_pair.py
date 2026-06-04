"""Unit test for harness.py `run-pair` command construction.

run_coordinator.py takes question_id and country_code as POSITIONAL
arguments and defines no --question-id / --country flags, so the built
command must pass the two values positionally in that order. A flag-based
command would make run_coordinator.py exit 2.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import harness


def _run_pair_cmd(monkeypatch, **overrides) -> list[str]:
    captured: dict[str, list[str]] = {}

    def _fake_call(cmd, *_a, **_k):
        captured["cmd"] = cmd
        return 0

    monkeypatch.setattr(harness.subprocess, "call", _fake_call)

    args = argparse.Namespace(
        question_id="P1", country="FR", strategy=None, yes=True,
    )
    for k, v in overrides.items():
        setattr(args, k, v)
    harness.cmd_run_pair(args)
    return captured["cmd"]


def test_run_pair_passes_question_and_country_positionally(monkeypatch):
    cmd = _run_pair_cmd(monkeypatch)

    # No flag form that run_coordinator.py would reject.
    assert "--question-id" not in cmd
    assert "--country" not in cmd

    # Positional question_id then country_code, right after the script path.
    script_idx = next(
        i for i, part in enumerate(cmd) if part.endswith("run_coordinator.py")
    )
    assert cmd[script_idx + 1] == "P1"
    assert cmd[script_idx + 2] == "FR"


def test_run_pair_forwards_strategy_flag(monkeypatch):
    cmd = _run_pair_cmd(monkeypatch, strategy="verifier-blind")
    assert "--strategy" in cmd
    assert cmd[cmd.index("--strategy") + 1] == "verifier-blind"
