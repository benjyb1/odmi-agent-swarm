"""Unit tests for the Mistral provider path (no network).

These prove the delegation contract holds without a live key: model routing,
structured parse with code-fence tolerance, real-cost computation, the one-retry
loop on a bad first reply, and a clean error when both attempts fail. The HTTP
POST is monkeypatched so nothing leaves the machine.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from agents.tools import mistral_provider as mp


class _Answer(BaseModel):
    answer: str
    confidence: float


def _chat_body(content: str, *, prompt_tokens: int = 100, completion_tokens: int = 20,
               model: str = "mistral-large-latest") -> dict:
    """A minimal OpenAI-shaped chat-completions body."""
    return {
        "model": model,
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def test_is_mistral_model_routing():
    assert mp.is_mistral_model("mistral-large-latest")
    assert mp.is_mistral_model("Mistral-Small-Latest")
    assert not mp.is_mistral_model("claude-sonnet-4-6")
    assert not mp.is_mistral_model(None)
    assert not mp.is_mistral_model("")


def test_estimate_cost_real_mistral_price():
    # 1M input + 1M output on large = 2.0 + 6.0.
    assert mp.estimate_cost_usd("mistral-large-latest", 1_000_000, 1_000_000) == 8.0
    # Unknown model returns None, not zero.
    assert mp.estimate_cost_usd("mistral-future-x", 100, 100) is None


def test_call_structured_happy_path(monkeypatch):
    captured = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return _chat_body('{"answer": "yes", "confidence": 0.9}')

    monkeypatch.setattr(mp, "_post_chat_completion", fake_post)

    parsed, usage = mp.call_mistral_structured(
        system="sys", user_message="msg", output_schema=_Answer,
        model="mistral-large-latest", condition_label="exp9_mistral",
    )
    assert parsed.answer == "yes"
    assert parsed.confidence == 0.9
    assert usage.model_version == "mistral-large-latest"
    assert usage.input_tokens == 100 and usage.output_tokens == 20
    assert usage.estimated_cost_usd == pytest.approx(2.0 * 100 / 1e6 + 6.0 * 20 / 1e6)
    assert usage.condition_label == "exp9_mistral"
    # Schema is appended to the system message and a JSON object is requested.
    assert "Return JSON matching this schema" in captured["messages"][0]["content"]
    assert captured["response_format"] == {"type": "json_object"}


def test_call_structured_tolerates_code_fence(monkeypatch):
    fenced = '```json\n{"answer": "no", "confidence": 0.5}\n```'
    monkeypatch.setattr(mp, "_post_chat_completion", lambda **k: _chat_body(fenced))
    parsed, _ = mp.call_mistral_structured(
        system="s", user_message="m", output_schema=_Answer, model="mistral-large-latest",
    )
    assert parsed.answer == "no"


def test_call_structured_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_post(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _chat_body("not json at all")
        return _chat_body('{"answer": "yes", "confidence": 0.8}')

    monkeypatch.setattr(mp, "_post_chat_completion", fake_post)
    parsed, usage = mp.call_mistral_structured(
        system="s", user_message="m", output_schema=_Answer, model="mistral-large-latest",
    )
    assert calls["n"] == 2
    assert parsed.answer == "yes"
    # Tokens accumulate across both attempts.
    assert usage.input_tokens == 200


def test_call_structured_raises_after_two_bad_attempts(monkeypatch):
    from agents.tools.llm import StructuredOutputError

    monkeypatch.setattr(mp, "_post_chat_completion", lambda **k: _chat_body("garbage"))
    with pytest.raises(StructuredOutputError):
        mp.call_mistral_structured(
            system="s", user_message="m", output_schema=_Answer, model="mistral-large-latest",
        )


def test_missing_key_is_clean_dict(monkeypatch):
    monkeypatch.setattr(mp, "_api_key", lambda: None)
    out = mp.probe_mistral_key()
    assert out["ok"] is False
    assert "not set" in out["error"]


def test_llm_dispatch_routes_to_mistral(monkeypatch):
    """call_for_structured must hand a Mistral model to the provider untouched."""
    import agents.tools.llm as llm

    seen = {}

    def fake_call(**kwargs):
        seen.update(kwargs)
        return _Answer(answer="ok", confidence=1.0), object()

    monkeypatch.setattr(llm, "call_mistral_structured", fake_call)
    llm.call_for_structured(
        system="s", user_message="m", output_schema=_Answer,
        model="mistral-large-latest",
    )
    assert seen["model"] == "mistral-large-latest"
    assert seen["output_schema"] is _Answer
