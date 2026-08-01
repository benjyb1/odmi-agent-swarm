"""call_for_structured routes a Mistral model off CLIProxyAPI (EXP-9 arm).

The swarm's structured output is prompt-based JSON, not Anthropic tool-use, so a
Mistral model id reuses the same parse/retry/usage loop. These tests pin the
contract without any network: the Anthropic client is never constructed for a
Mistral model, the Mistral HTTP call is stubbed, and usage logging is captured
so nothing touches the real DB.
"""
from pydantic import BaseModel

import agents.tools.llm as llm


class _Out(BaseModel):
    answer: str
    confidence: float


def _canned_mistral_body(content: str) -> dict:
    return {
        "model": "mistral-large-latest",
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


def test_mistral_model_routes_off_proxy(monkeypatch):
    """A 'mistral-*' model parses via Mistral and never builds the Claude client."""
    monkeypatch.setattr(
        llm, "_make_client",
        lambda: (_ for _ in ()).throw(AssertionError("Anthropic client must not be built for Mistral")),
    )
    monkeypatch.setattr(
        "agents.tools.search_adjudicator_mistral._post_chat_completion",
        lambda **kw: _canned_mistral_body('{"answer": "yes", "confidence": 0.9}'),
    )
    logged: list[dict] = []
    monkeypatch.setattr(llm, "_log_claude_usage", lambda **kw: logged.append(kw))

    parsed, usage = llm.call_for_structured(
        system="s", user_message="u", output_schema=_Out,
        model="mistral-large-latest",
    )

    assert parsed.answer == "yes" and parsed.confidence == 0.9
    assert usage.model_version == "mistral-large-latest"
    assert usage.input_tokens == 11 and usage.output_tokens == 7
    # Cost endpoint: Mistral Large is priced, so the figure is not None.
    assert usage.estimated_cost_usd is not None and usage.estimated_cost_usd > 0
    assert logged and logged[0]["model"] == "mistral-large-latest"


def test_mistral_passes_json_response_format(monkeypatch):
    """The Mistral call requests json_object mode and a system+user message pair."""
    captured: dict = {}

    def _spy(**kw):
        captured.update(kw)
        return _canned_mistral_body('{"answer": "no", "confidence": 0.5}')

    monkeypatch.setattr(llm, "_make_client", lambda: None)
    monkeypatch.setattr(
        "agents.tools.search_adjudicator_mistral._post_chat_completion", _spy,
    )
    monkeypatch.setattr(llm, "_log_claude_usage", lambda **kw: None)

    llm.call_for_structured(
        system="sys", user_message="usr", output_schema=_Out,
        model="mistral-large-latest",
    )

    assert captured["response_format"] == {"type": "json_object"}
    roles = [m["role"] for m in captured["messages"]]
    assert roles == ["system", "user"]


def test_non_mistral_model_unaffected(monkeypatch):
    """A Claude model still goes through the Anthropic client (no Mistral path)."""
    monkeypatch.setattr(
        "agents.tools.search_adjudicator_mistral._post_chat_completion",
        lambda **kw: (_ for _ in ()).throw(AssertionError("Mistral must not be called for a Claude model")),
    )

    class _FakeUsage:
        input_tokens = 5
        output_tokens = 3

    class _FakeResp:
        model = "claude-sonnet-4-6"
        usage = _FakeUsage()
        content = [type("C", (), {"text": '{"answer": "yes", "confidence": 0.8}'})()]

    class _FakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                return _FakeResp()

    monkeypatch.setattr(llm, "_make_client", lambda: _FakeClient())
    monkeypatch.setattr(llm, "_log_claude_usage", lambda **kw: None)

    parsed, usage = llm.call_for_structured(
        system="s", user_message="u", output_schema=_Out,
        model="claude-sonnet-4-6",
    )
    assert parsed.answer == "yes"
    assert usage.model_version == "claude-sonnet-4-6"
