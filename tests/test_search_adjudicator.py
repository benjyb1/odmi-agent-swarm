"""Tests for agents/tools/search_adjudicator.py.

The LLM call is mocked; no real Claude calls. Verifies the adjudicate()
wrapper passes the right prompt/schema/model through and returns the parsed
verdict.
"""
from __future__ import annotations

from unittest.mock import patch

from agents.models import LLMUsage
from agents.tools.search_adjudicator import (
    AdjudicationResult, adjudicate, ADJUDICATOR_MODEL,
)


def _fake_usage() -> LLMUsage:
    return LLMUsage(
        input_tokens=1, output_tokens=1, wall_clock_ms=1,
        estimated_cost_usd=0.0, model_version="test",
        prompt_version_id=None, condition_label="t", raw_response="{}",
    )


def test_adjudicator_model_is_opus():
    """The higher-order judge must run on an Opus-tier model, not the
    swarm's default Sonnet."""
    assert "opus" in ADJUDICATOR_MODEL.lower()


def test_adjudicate_returns_parsed_verdict():
    verdict = AdjudicationResult(
        winner="A",
        answer_supported_by_a="yes",
        answer_supported_by_b="insufficient evidence",
        reasoning="A cites the official portal page stating the feed exists.",
        confidence=0.8,
    )
    captured = {}

    def fake_call(**kwargs):
        captured.update(kwargs)
        return verdict, _fake_usage()

    with patch("agents.tools.search_adjudicator.call_for_structured", fake_call):
        with patch("agents.tools.search_adjudicator.ensure_prompt_version", lambda *a, **k: 42):
            result, usage = adjudicate(
                question_text="Does the portal offer an RSS feed?",
                ground_truth="yes",
                evidence_a=[{"url": "https://a.gov", "snippet": "An RSS feed is available."}],
                evidence_b=[{"url": "https://b.com", "snippet": "Welcome to our site."}],
            )

    assert result.winner == "A"
    assert usage.input_tokens == 1
    # Runs on Opus and registers the versioned prompt.
    assert captured["model"] == ADJUDICATOR_MODEL
    assert captured["prompt_version_id"] == 42
    # Both evidence sets reach the judge.
    assert "a.gov" in captured["user_message"]
    assert "b.com" in captured["user_message"]
    # Ground truth reaches the judge.
    assert "yes" in captured["user_message"]


def test_adjudicate_winner_must_be_valid_literal():
    """The schema rejects a winner outside the allowed set."""
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AdjudicationResult(
            winner="diy",  # not allowed; must be A/B/tie/both_fail
            answer_supported_by_a="yes", answer_supported_by_b="no",
            reasoning="x", confidence=0.5,
        )
