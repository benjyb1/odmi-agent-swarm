"""Tests for the cross-family (Gemini) judge and the answer-blind prompt.

All LLM calls are mocked; there are NO live Gemini calls here. The live auth
probe is exercised only for callability (its network call is patched out),
since the actual auth outcome is recorded once in the build report, not on
every test run.

Coverage:
- The answer-blind prompt variant omits the gold answer string and the
  answer-given variant still includes it (and is byte-for-byte unchanged).
- parse_gemini_adjudication maps a sample Gemini generateContent body into an
  AdjudicationResult (winner, supports flags, reasoning).
- adjudicate_gemini threads the parsed verdict and usage through with the
  network call mocked, and selects the blind system prompt when asked.
- The auth-probe function exists and is callable.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agents.prompts import search_adjudicator as prompt
from agents.tools.search_adjudicator import AdjudicationResult
from agents.tools.search_adjudicator_gemini import (
    GEMINI_JUDGE_MODEL,
    adjudicate_gemini,
    parse_gemini_adjudication,
    probe_auth,
)

# A distinctive gold answer unlikely to appear in any evidence snippet, so the
# omission assertion cannot pass by accident.
_GOLD = "ZZQ_GOLD_BAND_42pc"
_QUESTION = "Does the national portal publish a machine-readable catalogue?"
_EVIDENCE_A = [{"url": "https://data.gouv.fr/x", "snippet": "A DCAT-AP feed is published."}]
_EVIDENCE_B = [{"url": "https://example.com/y", "snippet": "Welcome to our homepage."}]


def _gemini_body(payload: dict, *, prompt_tokens: int = 120, out_tokens: int = 40) -> dict:
    """Build a minimal Gemini generateContent response wrapping a JSON payload.

    Mirrors the candidates[].content.parts[].text + usageMetadata shape the
    real API returns.
    """
    return {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(payload)}]}}
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": out_tokens,
        },
    }


# Answer-blind prompt variant


def test_answer_blind_user_message_omits_gold_answer():
    blind = prompt.build_user_message(
        question_text=_QUESTION,
        ground_truth=_GOLD,
        evidence_a=_EVIDENCE_A,
        evidence_b=_EVIDENCE_B,
        answer_blind=True,
    )
    assert _GOLD not in blind
    # The gold-answer scaffolding line is gone too, not just the value.
    assert "Verified correct answer" not in blind
    # It still poses the question and asks the blind form.
    assert _QUESTION in blind
    assert "establishes an answer" in blind


def test_answer_given_user_message_still_includes_gold_answer():
    given = prompt.build_user_message(
        question_text=_QUESTION,
        ground_truth=_GOLD,
        evidence_a=_EVIDENCE_A,
        evidence_b=_EVIDENCE_B,
        answer_blind=False,
    )
    assert _GOLD in given
    assert "Verified correct answer" in given


def test_answer_given_rendering_unchanged_by_default():
    """The default (answer_blind=False) output is unchanged from explicit
    False, so the existing answer-given path is untouched."""
    default = prompt.build_user_message(
        question_text=_QUESTION,
        ground_truth=_GOLD,
        evidence_a=_EVIDENCE_A,
        evidence_b=_EVIDENCE_B,
    )
    explicit = prompt.build_user_message(
        question_text=_QUESTION,
        ground_truth=_GOLD,
        evidence_a=_EVIDENCE_A,
        evidence_b=_EVIDENCE_B,
        answer_blind=False,
    )
    assert default == explicit


def test_system_for_blind_withholds_gold_and_differs():
    assert prompt.system_for(False) == prompt.SYSTEM
    blind_system = prompt.system_for(True)
    assert blind_system == prompt.SYSTEM_ANSWER_BLIND
    assert blind_system != prompt.SYSTEM
    # The blind system tells the judge it is NOT given the answer.
    assert "NOT given the correct answer" in blind_system


# Gemini response parser


def test_parse_gemini_adjudication_maps_fields():
    payload = {
        "winner": "A",
        "answer_supported_by_a": "yes",
        "answer_supported_by_b": "insufficient evidence",
        "reasoning": "A cites the official portal stating a DCAT-AP feed exists.",
        "confidence": 0.82,
    }
    result = parse_gemini_adjudication(_gemini_body(payload))
    assert isinstance(result, AdjudicationResult)
    assert result.winner == "A"
    assert result.answer_supported_by_a == "yes"
    assert result.answer_supported_by_b == "insufficient evidence"
    assert "official portal" in result.reasoning
    assert result.confidence == pytest.approx(0.82)


def test_parse_gemini_adjudication_tolerates_code_fence():
    payload = {
        "winner": "tie",
        "answer_supported_by_a": "yes",
        "answer_supported_by_b": "yes",
        "reasoning": "Both sets cite the catalogue page.",
        "confidence": 0.5,
    }
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    body = {"candidates": [{"content": {"parts": [{"text": fenced}]}}]}
    result = parse_gemini_adjudication(body)
    assert result.winner == "tie"


def test_parse_gemini_adjudication_raises_on_empty_candidates():
    with pytest.raises(ValueError):
        parse_gemini_adjudication({"candidates": []})


def test_parse_gemini_adjudication_raises_on_bad_schema():
    bad = {"winner": "diy", "reasoning": "x"}  # winner not in literal set
    with pytest.raises(ValueError):
        parse_gemini_adjudication(_gemini_body(bad))


# adjudicate_gemini end-to-end (network mocked)


def test_adjudicate_gemini_returns_parsed_verdict_and_usage():
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
        return _gemini_body(payload, prompt_tokens=200, out_tokens=55)

    with patch(
        "agents.tools.search_adjudicator_gemini._post_generate_content", fake_post
    ), patch(
        "agents.tools.search_adjudicator_gemini.ensure_prompt_version",
        lambda *a, **k: 7,
    ):
        result, usage = adjudicate_gemini(
            question_text=_QUESTION,
            ground_truth=_GOLD,
            evidence_a=_EVIDENCE_A,
            evidence_b=_EVIDENCE_B,
        )

    assert result.winner == "B"
    assert result.answer_supported_by_b == "no"
    # Usage carries Gemini token counts and names the Gemini model; cost is
    # None (off the Claude budget, not in the pricing table).
    assert usage.input_tokens == 200
    assert usage.output_tokens == 55
    assert usage.model_version == GEMINI_JUDGE_MODEL
    assert usage.estimated_cost_usd is None
    # The default (answer-given) system prompt was sent and the gold answer
    # reached the model.
    assert captured["model"] == GEMINI_JUDGE_MODEL
    assert "VERIFIED CORRECT ANSWER" in captured["system_instruction"]
    sent_text = captured["contents"][0]["parts"][0]["text"]
    assert _GOLD in sent_text


def test_adjudicate_gemini_answer_blind_withholds_gold():
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
        return _gemini_body(payload)

    with patch(
        "agents.tools.search_adjudicator_gemini._post_generate_content", fake_post
    ), patch(
        "agents.tools.search_adjudicator_gemini.ensure_prompt_version",
        lambda *a, **k: 7,
    ):
        result, _ = adjudicate_gemini(
            question_text=_QUESTION,
            ground_truth=_GOLD,
            evidence_a=_EVIDENCE_A,
            evidence_b=_EVIDENCE_B,
            answer_blind=True,
        )

    assert result.winner == "A"
    # Neither the system instruction nor the user message leaks the gold answer.
    assert _GOLD not in captured["system_instruction"]
    assert "NOT given the correct answer" in captured["system_instruction"]
    sent_text = captured["contents"][0]["parts"][0]["text"]
    assert _GOLD not in sent_text
    assert "establishes an answer" in sent_text


# Auth probe callability (no live call)


def test_probe_auth_is_callable_and_reports_outcome():
    """probe_auth exists, is callable, and returns an outcome dict. The
    network call is patched so this never touches Google."""
    fake = _gemini_body({"x": 1})  # body shape is irrelevant for a probe
    fake["candidates"][0]["content"]["parts"] = [{"text": "pong"}]
    with patch(
        "agents.tools.search_adjudicator_gemini._post_generate_content",
        lambda **k: fake,
    ), patch.dict("os.environ", {"GEMINI_API_KEY": "AQ.test-key"}):
        out = probe_auth()
    assert out["ok"] is True
    assert out["text"] == "pong"
    assert out["key_prefix"] == "AQ."


def test_probe_auth_reports_failure_without_raising():
    from agents.tools.search_adjudicator_gemini import GeminiAuthError

    def boom(**kwargs):
        raise GeminiAuthError("HTTP 429 RESOURCE_EXHAUSTED")

    with patch(
        "agents.tools.search_adjudicator_gemini._post_generate_content", boom
    ), patch.dict("os.environ", {"GEMINI_API_KEY": "AQ.test-key"}):
        out = probe_auth()
    assert out["ok"] is False
    assert "RESOURCE_EXHAUSTED" in out["error"]
