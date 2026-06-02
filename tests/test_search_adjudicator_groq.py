"""Tests for the cross-family (Groq / Llama) judge.

All HTTP calls are mocked; there are NO live Groq calls here. The auth probe's
network path is never reached: it is exercised only for the missing-key case,
which short-circuits before any request. The live auth outcome is recorded
once in the build report, not on every test run.

Coverage:
- parse_groq_adjudication maps a sample Groq chat-completions body into an
  AdjudicationResult (winner, supports flags, reasoning, confidence) and
  tolerates a ```json fence.
- probe_auth_groq returns ok:False cleanly when GROQ_API_KEY is unset, without
  raising or touching the network.
- adjudicate_groq threads a mocked HTTP response into an AdjudicationResult and
  honours answer_blind in the prompt it sends.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agents.tools.search_adjudicator import AdjudicationResult
from agents.tools.search_adjudicator_groq import (
    GROQ_JUDGE_MODEL,
    adjudicate_groq,
    parse_groq_adjudication,
    probe_auth_groq,
)

# A distinctive gold answer unlikely to appear in any evidence snippet, so the
# omission assertion in the blind test cannot pass by accident.
_GOLD = "ZZQ_GOLD_BAND_42pc"
_QUESTION = "Does the national portal publish a machine-readable catalogue?"
_EVIDENCE_A = [{"url": "https://data.gouv.fr/x", "snippet": "A DCAT-AP feed is published."}]
_EVIDENCE_B = [{"url": "https://example.com/y", "snippet": "Welcome to our homepage."}]


def _groq_body(payload: dict, *, prompt_tokens: int = 120, out_tokens: int = 40) -> dict:
    """Build a minimal Groq chat-completions response wrapping a JSON payload.

    Mirrors the choices[].message.content + usage shape the real
    OpenAI-compatible API returns.
    """
    return {
        "choices": [
            {"message": {"role": "assistant", "content": json.dumps(payload)}}
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": out_tokens,
        },
    }


# --------------------------------------------------------------------------
# Groq response parser
# --------------------------------------------------------------------------


def test_parse_groq_adjudication_maps_fields():
    payload = {
        "winner": "A",
        "answer_supported_by_a": "yes",
        "answer_supported_by_b": "insufficient evidence",
        "reasoning": "A cites the official portal stating a DCAT-AP feed exists.",
        "confidence": 0.82,
    }
    result = parse_groq_adjudication(_groq_body(payload))
    assert isinstance(result, AdjudicationResult)
    assert result.winner == "A"
    assert result.answer_supported_by_a == "yes"
    assert result.answer_supported_by_b == "insufficient evidence"
    assert "official portal" in result.reasoning
    assert result.confidence == pytest.approx(0.82)


def test_parse_groq_adjudication_tolerates_code_fence():
    payload = {
        "winner": "tie",
        "answer_supported_by_a": "yes",
        "answer_supported_by_b": "yes",
        "reasoning": "Both sets cite the catalogue page.",
        "confidence": 0.5,
    }
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    body = {"choices": [{"message": {"content": fenced}}]}
    result = parse_groq_adjudication(body)
    assert result.winner == "tie"
    assert result.confidence == pytest.approx(0.5)


def test_parse_groq_adjudication_raises_on_empty_choices():
    with pytest.raises(ValueError):
        parse_groq_adjudication({"choices": []})


def test_parse_groq_adjudication_raises_on_bad_schema():
    bad = {"winner": "diy", "reasoning": "x"}  # winner not in literal set
    with pytest.raises(ValueError):
        parse_groq_adjudication(_groq_body(bad))


# --------------------------------------------------------------------------
# Auth probe: missing key short-circuits cleanly (no network)
# --------------------------------------------------------------------------


def test_probe_auth_groq_returns_false_when_key_unset():
    """With GROQ_API_KEY unset, probe_auth_groq reports ok:False with the
    documented error and never touches the network."""
    # patch.dict cannot 'pop' a key, so clear the whole environment for the
    # block (clear=True) to guarantee GROQ_API_KEY is absent.
    with patch.dict("os.environ", {}, clear=True):
        out = probe_auth_groq()
    assert out["ok"] is False
    assert out["error"] == "GROQ_API_KEY not set"
    assert out["key_prefix"] is None


# --------------------------------------------------------------------------
# adjudicate_groq end-to-end (network mocked)
# --------------------------------------------------------------------------


def test_adjudicate_groq_returns_parsed_verdict_and_usage():
    payload = {
        "winner": "B",
        "answer_supported_by_a": "insufficient evidence",
        "answer_supported_by_b": "no",
        "reasoning": "B's official source states the feature is absent.",
        "confidence": 0.7,
    }
    captured = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return _groq_body(payload, prompt_tokens=200, out_tokens=55)

    with patch(
        "agents.tools.search_adjudicator_groq._post_chat_completion", fake_post
    ), patch(
        "agents.tools.search_adjudicator_groq.ensure_prompt_version",
        lambda *a, **k: 7,
    ):
        result, usage = adjudicate_groq(
            question_text=_QUESTION,
            ground_truth=_GOLD,
            evidence_a=_EVIDENCE_A,
            evidence_b=_EVIDENCE_B,
        )

    assert result.winner == "B"
    assert result.answer_supported_by_b == "no"
    # Usage carries Groq token counts and names the Groq model; cost is None
    # (off the Claude budget, not in the pricing table).
    assert usage.input_tokens == 200
    assert usage.output_tokens == 55
    assert usage.model_version == GROQ_JUDGE_MODEL
    assert usage.estimated_cost_usd is None
    # The default (answer-given) system prompt was sent and the gold answer
    # reached the model.
    assert captured["model"] == GROQ_JUDGE_MODEL
    assert captured["response_format"] == {"type": "json_object"}
    messages = captured["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "VERIFIED CORRECT ANSWER" in messages[0]["content"]
    assert _GOLD in messages[1]["content"]


def test_adjudicate_groq_answer_blind_withholds_gold():
    payload = {
        "winner": "A",
        "answer_supported_by_a": "yes",
        "answer_supported_by_b": "insufficient evidence",
        "reasoning": "Only A's evidence settles the question.",
        "confidence": 0.6,
    }
    captured = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return _groq_body(payload)

    with patch(
        "agents.tools.search_adjudicator_groq._post_chat_completion", fake_post
    ), patch(
        "agents.tools.search_adjudicator_groq.ensure_prompt_version",
        lambda *a, **k: 7,
    ):
        result, _ = adjudicate_groq(
            question_text=_QUESTION,
            ground_truth=_GOLD,
            evidence_a=_EVIDENCE_A,
            evidence_b=_EVIDENCE_B,
            answer_blind=True,
        )

    assert result.winner == "A"
    messages = captured["messages"]
    # Neither the system message nor the user message leaks the gold answer.
    assert _GOLD not in messages[0]["content"]
    assert "NOT given the correct answer" in messages[0]["content"]
    assert _GOLD not in messages[1]["content"]
    assert "establishes an answer" in messages[1]["content"]
