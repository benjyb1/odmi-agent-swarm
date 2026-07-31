"""A CLIProxyAPI 503 must shut the coordinator down cleanly, not crash it.

Observed 2026-07-02: the shared Claude Max auth-file pool ran out of a free
session under concurrent-window load and CLIProxyAPI returned a 503. That
propagated as an uncaught `anthropic.InternalServerError`, crashing the
coordinator subprocess mid-stage with no DB update, the subtrio_status row
was orphaned and no phase2_final row was ever written, so the pair silently
vanished from the resume set. These tests pin the fix: the 503 is caught in
`call_for_structured` and re-raised as `AuthUnavailableShutdown`, a
`RateLimitedShutdown` subclass that reuses the whole 429 shutdown contract
(same subtrio_status stage, same EXIT_CODE_RATE_LIMITED, same dispatcher
global-stop-and-resume) but records an honest `final_failure_reason`.
"""
from __future__ import annotations

import httpx
import pytest
from pydantic import BaseModel

import agents.tools.llm as llm
from agents.errors import AuthUnavailableShutdown, RateLimitedShutdown


class _Out(BaseModel):
    answer: str
    confidence: float


def _fake_internal_server_error() -> Exception:
    import anthropic
    request = httpx.Request("POST", "http://localhost:8317/v1/messages")
    response = httpx.Response(
        status_code=503,
        request=request,
        json={"type": "error", "error": {
            "type": "api_error",
            "message": "auth_unavailable: no auth available (providers=claude, "
                       "model=claude-sonnet-4-6)",
        }},
    )
    return anthropic.InternalServerError(
        "auth_unavailable", response=response, body=None,
    )


class TestAuthUnavailableShutdown:
    def test_is_a_rate_limited_shutdown(self):
        # Subclass relationship is the whole point: every existing
        # `except RateLimitedShutdown` handler must keep catching this.
        assert issubclass(AuthUnavailableShutdown, RateLimitedShutdown)

    def test_503_raises_auth_unavailable_not_a_crash(self, monkeypatch):
        class _FakeClient:
            class messages:
                @staticmethod
                def create(**kw):
                    raise _fake_internal_server_error()

        logged = []
        monkeypatch.setattr(llm, "_make_client", lambda: _FakeClient())
        monkeypatch.setattr(
            llm, "_log_claude_usage", lambda **kw: logged.append(kw),
        )

        with pytest.raises(AuthUnavailableShutdown):
            llm.call_for_structured(
                system="s", user_message="u", output_schema=_Out,
                model="claude-sonnet-4-6",
            )

        # A usage row is still written (rate_limited=True), same as a 429,
        # so the DB never silently loses the fact that a call was attempted.
        assert len(logged) == 1
        assert logged[0]["rate_limited"] is True

    def test_429_still_raises_plain_rate_limited_shutdown(self, monkeypatch):
        # The pre-existing 429 path must be unaffected: it raises the base
        # class, not the new subclass, so the Coordinator's reason-string
        # branch (auth_unavailable vs anthropic_rate_limit) picks correctly.
        import anthropic

        class _FakeClient:
            class messages:
                @staticmethod
                def create(**kw):
                    request = httpx.Request(
                        "POST", "http://localhost:8317/v1/messages",
                    )
                    response = httpx.Response(
                        status_code=429, request=request,
                        json={"type": "error", "error": {
                            "type": "rate_limit_error", "message": "rate limited",
                        }},
                    )
                    raise anthropic.RateLimitError(
                        "rate limited", response=response, body=None,
                    )

        monkeypatch.setattr(llm, "_make_client", lambda: _FakeClient())
        monkeypatch.setattr(llm, "_log_claude_usage", lambda **kw: None)

        with pytest.raises(RateLimitedShutdown) as excinfo:
            llm.call_for_structured(
                system="s", user_message="u", output_schema=_Out,
                model="claude-sonnet-4-6",
            )
        assert not isinstance(excinfo.value, AuthUnavailableShutdown)
