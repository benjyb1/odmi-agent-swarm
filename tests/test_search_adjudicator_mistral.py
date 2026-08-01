"""Tests for the cross-family (Mistral Large) judge.

All HTTP calls are mocked; there are NO live Mistral calls here. The auth
probe's network path is never reached: it is exercised only for the missing-key
case, which short-circuits before any request. The live auth outcome is recorded
once in the build report, not on every test run.

Coverage:
- parse_mistral_adjudication maps a sample Mistral chat-completions body into an
  AdjudicationResult (winner, supports flags, reasoning, confidence) and
  tolerates a ```json fence.
- probe_auth_mistral returns ok:False cleanly when MISTRAL_API_KEY is unset,
  without raising or touching the network.
- adjudicate_mistral threads a mocked HTTP response into an AdjudicationResult
  and honours answer_blind in the prompt it sends.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import agents.tools.search_adjudicator_mistral as mistral
from agents.tools.search_adjudicator import AdjudicationResult
from agents.tools.search_adjudicator_mistral import (
    MISTRAL_JUDGE_MODEL,
    MistralAuthError,
    adjudicate_mistral,
    parse_mistral_adjudication,
    probe_auth_mistral,
)

# A distinctive gold answer unlikely to appear in any evidence snippet, so the
# omission assertion in the blind test cannot pass by accident.
_GOLD = "ZZQ_GOLD_BAND_42pc"
_QUESTION = "Does the national portal publish a machine-readable catalogue?"
_EVIDENCE_A = [{"url": "https://data.gouv.fr/x", "snippet": "A DCAT-AP feed is published."}]
_EVIDENCE_B = [{"url": "https://example.com/y", "snippet": "Welcome to our homepage."}]


def _mistral_body(payload: dict, *, prompt_tokens: int = 120, out_tokens: int = 40) -> dict:
    """Build a minimal Mistral chat-completions response wrapping a JSON payload.

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


# Mistral response parser


def test_parse_mistral_adjudication_maps_fields():
    payload = {
        "winner": "A",
        "answer_supported_by_a": "yes",
        "answer_supported_by_b": "insufficient evidence",
        "reasoning": "A cites the official portal stating a DCAT-AP feed exists.",
        "confidence": 0.82,
    }
    result = parse_mistral_adjudication(_mistral_body(payload))
    assert isinstance(result, AdjudicationResult)
    assert result.winner == "A"
    assert result.answer_supported_by_a == "yes"
    assert result.answer_supported_by_b == "insufficient evidence"
    assert "official portal" in result.reasoning
    assert result.confidence == pytest.approx(0.82)


def test_parse_mistral_adjudication_tolerates_code_fence():
    payload = {
        "winner": "tie",
        "answer_supported_by_a": "yes",
        "answer_supported_by_b": "yes",
        "reasoning": "Both sets cite the catalogue page.",
        "confidence": 0.5,
    }
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    body = {"choices": [{"message": {"content": fenced}}]}
    result = parse_mistral_adjudication(body)
    assert result.winner == "tie"
    assert result.confidence == pytest.approx(0.5)


def test_parse_mistral_adjudication_raises_on_empty_choices():
    with pytest.raises(ValueError):
        parse_mistral_adjudication({"choices": []})


def test_parse_mistral_adjudication_raises_on_bad_schema():
    bad = {"winner": "diy", "reasoning": "x"}  # winner not in literal set
    with pytest.raises(ValueError):
        parse_mistral_adjudication(_mistral_body(bad))


# _post_chat_completion: throttle + retry-on-429 with backoff


class _FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    """Context-manager httpx.Client stub returning queued responses in order.

    The module makes a fresh httpx.Client() per attempt, so the queue is SHARED
    (not copied): each retry pops the next response from the same list, which is
    how a real sequence of 429-then-200 is reproduced across attempts.
    """

    def __init__(self, responses):
        self._responses = responses

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, *a, **k):
        return self._responses.pop(0)


def _patch_post_path(responses):
    """Patch httpx.Client, time.sleep, and reset the throttle clock for a test."""
    mistral._last_call_at[:] = []
    return (
        patch.object(mistral, "_api_key", lambda: "k"),
        patch.object(mistral.httpx, "Client", lambda *a, **k: _FakeClient(responses)),
        patch.object(mistral.time, "sleep", lambda *_a, **_k: None),
    )


def test_post_retries_429_then_succeeds():
    """A transient 429 is retried with backoff and the next 200 is returned."""
    ok = _mistral_body({"winner": "tie", "answer_supported_by_a": "y",
                         "answer_supported_by_b": "y", "reasoning": "x",
                         "confidence": 0.5})
    responses = [_FakeResp(429, text="rate_limited"), _FakeResp(200, ok)]
    p_key, p_client, p_sleep = _patch_post_path(responses)
    with p_key, p_client, p_sleep:
        body = mistral._post_chat_completion(
            model=MISTRAL_JUDGE_MODEL, messages=[{"role": "user", "content": "x"}],
        )
    assert body == ok  # the 200 body after one retry


def test_post_raises_immediately_on_non_429():
    """A non-429 (e.g. 401) is a hard failure raised at once, not retried."""
    responses = [_FakeResp(401, text="unauthorized"), _FakeResp(200, {})]
    p_key, p_client, p_sleep = _patch_post_path(responses)
    with p_key, p_client, p_sleep:
        with pytest.raises(MistralAuthError) as exc:
            mistral._post_chat_completion(
                model=MISTRAL_JUDGE_MODEL,
                messages=[{"role": "user", "content": "x"}],
            )
    assert "HTTP 401" in str(exc.value)
    # Only the 401 was consumed; the 200 is untouched, so no retry happened.
    assert len(responses) == 1


def test_post_gives_up_after_max_retries_on_persistent_429():
    """Persistent 429s exhaust the retries and raise, not loop forever."""
    responses = [_FakeResp(429, text="rate_limited")] * (mistral._MAX_RETRIES + 1)
    p_key, p_client, p_sleep = _patch_post_path(responses)
    with p_key, p_client, p_sleep:
        with pytest.raises(MistralAuthError) as exc:
            mistral._post_chat_completion(
                model=MISTRAL_JUDGE_MODEL,
                messages=[{"role": "user", "content": "x"}],
            )
    assert "retries" in str(exc.value)


# Auth probe: missing key short-circuits cleanly (no network)


def test_probe_auth_mistral_returns_false_when_key_unset():
    """With MISTRAL_API_KEY unset, probe_auth_mistral reports ok:False with the
    documented error and never touches the network."""
    # patch.dict cannot 'pop' a key, so clear the whole environment for the
    # block (clear=True) to guarantee MISTRAL_API_KEY is absent.
    with patch.dict("os.environ", {}, clear=True):
        out = probe_auth_mistral()
    assert out["ok"] is False
    assert out["error"] == "MISTRAL_API_KEY not set"
    assert out["key_prefix"] is None


# adjudicate_mistral end-to-end (network mocked)


def test_adjudicate_mistral_returns_parsed_verdict_and_usage():
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
        return _mistral_body(payload, prompt_tokens=200, out_tokens=55)

    with patch(
        "agents.tools.search_adjudicator_mistral._post_chat_completion", fake_post
    ), patch(
        "agents.tools.search_adjudicator_mistral.ensure_prompt_version",
        lambda *a, **k: 7,
    ):
        result, usage = adjudicate_mistral(
            question_text=_QUESTION,
            ground_truth=_GOLD,
            evidence_a=_EVIDENCE_A,
            evidence_b=_EVIDENCE_B,
        )

    assert result.winner == "B"
    assert result.answer_supported_by_b == "no"
    # Usage carries Mistral token counts and names the Mistral model; cost is
    # None (off the Claude budget, not in the pricing table).
    assert usage.input_tokens == 200
    assert usage.output_tokens == 55
    assert usage.model_version == MISTRAL_JUDGE_MODEL
    assert usage.estimated_cost_usd is None
    # The default (answer-given) system prompt was sent and the gold answer
    # reached the model.
    assert captured["model"] == MISTRAL_JUDGE_MODEL
    assert captured["response_format"] == {"type": "json_object"}
    messages = captured["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "VERIFIED CORRECT ANSWER" in messages[0]["content"]
    assert _GOLD in messages[1]["content"]


def test_adjudicate_mistral_answer_blind_withholds_gold():
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
        return _mistral_body(payload)

    with patch(
        "agents.tools.search_adjudicator_mistral._post_chat_completion", fake_post
    ), patch(
        "agents.tools.search_adjudicator_mistral.ensure_prompt_version",
        lambda *a, **k: 7,
    ):
        result, _ = adjudicate_mistral(
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
