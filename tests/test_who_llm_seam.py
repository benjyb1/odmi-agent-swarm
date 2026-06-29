"""The model seam: who_speech calls one structured() function that dispatches
to the configured backend (Claude via the proxy by default, Azure OpenAI when
WHO_LLM_BACKEND says so), so the swarm is not hardwired to any one provider.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from who_speech import llm


class Out(BaseModel):
    ok: bool
    n: int = 0


def test_defaults_to_claude_backend_and_passes_result_through(monkeypatch):
    monkeypatch.delenv("WHO_LLM_BACKEND", raising=False)
    seen = {}

    def fake_claude(**kw):
        seen.update(kw)
        return Out(ok=True, n=7), {"backend": "claude"}

    monkeypatch.setattr(llm, "_claude_structured", fake_claude)
    obj, _meta = llm.structured(
        system="s", user_message="u", output_schema=Out, usage_context="who_speech:test"
    )
    assert obj == Out(ok=True, n=7)
    assert seen["usage_context"] == "who_speech:test"


def test_azure_backend_routes_to_azure_not_claude(monkeypatch):
    monkeypatch.setenv("WHO_LLM_BACKEND", "azure_openai")

    def boom(**kw):
        raise AssertionError("claude path must not be called when backend=azure_openai")

    monkeypatch.setattr(llm, "_claude_structured", boom)
    monkeypatch.setattr(llm, "_azure_structured", lambda **kw: (Out(ok=True), {"backend": "azure_openai"}))
    _obj, meta = llm.structured(system="s", user_message="u", output_schema=Out, usage_context="x")
    assert meta["backend"] == "azure_openai"


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("WHO_LLM_BACKEND", "ollama")
    with pytest.raises(ValueError):
        llm.structured(system="s", user_message="u", output_schema=Out, usage_context="x")


def test_azure_structured_parses_json_content(monkeypatch):
    monkeypatch.setenv("WHO_LLM_BACKEND", "azure_openai")

    class _Msg:
        content = '{"ok": true, "n": 3}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Completions:
        def create(self, **kw):
            return _Resp()

    class _Client:
        class chat:
            completions = _Completions()

    monkeypatch.setattr(llm, "_azure_client", lambda: (_Client(), "deployment-x"))
    obj, meta = llm.structured(system="s", user_message="u", output_schema=Out, usage_context="x")
    assert obj == Out(ok=True, n=3)
    assert meta["backend"] == "azure_openai"
