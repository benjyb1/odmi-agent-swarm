"""Sonnet 5 was cut 2026-07-09 (D59). Its name is kept in the decision history,
but it must never be dispatched. Two guards enforce that:

  1. `llm.call_for_structured` refuses a banned model before any API call.
  2. `run_experiments.preflight` rejects any spec that pins a banned model, so a
     stale pin fails at dry-run rather than mid-run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.tools import llm


class _Out(BaseModel):
    answer: str


@pytest.mark.parametrize("model", ["claude-sonnet-5", "claude-sonnet-5-20260601"])
def test_call_refuses_banned_model(model):
    with pytest.raises(ValueError, match="banned"):
        llm.call_for_structured(
            system="s", user_message="u", output_schema=_Out, model=model,
        )


def test_call_allows_production_model(monkeypatch):
    """The guard must not trip on the production model (or its escalation
    siblings); it raises only for the banned prefix."""
    # Stop before any real network call: the guard runs first, so reaching the
    # client construction means the model was allowed through.
    sentinel = RuntimeError("reached client construction (model allowed)")

    def _boom():
        raise sentinel

    monkeypatch.setattr(llm, "_make_client", _boom)
    for model in ("claude-sonnet-4-6", "claude-sonnet-4-5-20250929",
                  "claude-opus-4-8"):
        with pytest.raises(RuntimeError, match="reached client construction"):
            llm.call_for_structured(
                system="s", user_message="u", output_schema=_Out, model=model,
            )


def test_preflight_rejects_banned_model_pin():
    from scripts import run_experiments as rx

    spec = {
        "run_id": "t", "global_parallel": 1, "budget_calls": 100,
        "experiments": [{
            "experiment_id": "t_exp", "type": "accuracy",
            "countries": ["NL"], "questions_from": "data/questions/all_questions.json",
            "baseline_knobs": {"researcher_model": "claude-sonnet-5"},
            "arms": [{"condition_label": "a", "knobs": {}}],
        }],
    }
    errors = rx.preflight(spec)
    assert any("cut model" in e and "researcher_model" in e for e in errors), errors
