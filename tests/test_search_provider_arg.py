"""Tests for the provider kwarg added to search() and search_many().

Behaviour contract:
- provider="auto" (default) preserves the existing Tavily-first-then-Brave
  fallback chain unchanged.
- provider="tavily" calls Tavily only; if Tavily raises, the error propagates
  (no Brave fallback). This is the conservative choice for explicit-provider
  callers: they opted in deliberately and silence would hide failures.
- provider="brave" calls Brave only; Tavily is never touched.

search_many() mirrors the kwarg and plumbs it to each per-query search() call.
"""

import pytest

from agents.tools.search import search, search_many, SearchResult


def _tavily_result(query: str = "q", **_kwargs) -> list[SearchResult]:
    return [SearchResult(title="t", url="https://tavily.example", snippet="c",
                         score=0.5, provider="tavily")]


def _brave_result(query: str = "q", **_kwargs) -> list[SearchResult]:
    return [SearchResult(title="b", url="https://brave.example", snippet="s",
                         score=None, provider="brave")]


# ---------------------------------------------------------------------------
# provider="auto"
# ---------------------------------------------------------------------------

def test_provider_auto_keeps_existing_chain(monkeypatch):
    """provider='auto' (default) must preserve Tavily-first behaviour."""
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: _tavily_result(q, **k),
    )
    out = search("test", provider="auto")
    assert len(out) > 0
    assert all(r.provider == "tavily" for r in out)


def test_provider_default_is_auto(monkeypatch):
    """Omitting provider must behave identically to provider='auto'."""
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: _tavily_result(q, **k),
    )
    out_default = search("test")
    out_auto = search("test", provider="auto")
    assert [r.url for r in out_default] == [r.url for r in out_auto]


# ---------------------------------------------------------------------------
# provider="tavily"
# ---------------------------------------------------------------------------

def test_provider_tavily_returns_tavily_results(monkeypatch):
    """provider='tavily' calls Tavily and returns its results."""
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: _tavily_result(q, **k),
    )
    out = search("test", provider="tavily")
    assert len(out) > 0
    assert all(r.provider == "tavily" for r in out)


def test_provider_tavily_no_brave_fallback(monkeypatch):
    """provider='tavily': if Tavily raises, error propagates — Brave is NOT called."""
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: (_ for _ in ()).throw(RuntimeError("tavily down")),
    )
    monkeypatch.setattr(
        "agents.tools.search._brave_search",
        lambda q, **k: pytest.fail("Brave must not be called when provider='tavily'"),
    )
    with pytest.raises(RuntimeError, match="tavily down"):
        search("test", provider="tavily")


# ---------------------------------------------------------------------------
# provider="brave"
# ---------------------------------------------------------------------------

def test_provider_brave_skips_tavily(monkeypatch):
    """provider='brave' must NOT call Tavily at all."""
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: pytest.fail("Tavily must not be called when provider='brave'"),
    )
    monkeypatch.setattr(
        "agents.tools.search._brave_search",
        lambda q, **k: _brave_result(q, **k),
    )
    out = search("test", provider="brave")
    assert len(out) > 0
    assert all(r.provider == "brave" for r in out)


def test_provider_brave_returns_brave_results(monkeypatch):
    """provider='brave' returns Brave results, not Tavily results."""
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: pytest.fail("Tavily must not be called when provider='brave'"),
    )
    monkeypatch.setattr(
        "agents.tools.search._brave_search",
        lambda q, **k: _brave_result(q, **k),
    )
    out = search("test", provider="brave")
    assert all(r.provider == "brave" for r in out)


# ---------------------------------------------------------------------------
# on_call telemetry
# ---------------------------------------------------------------------------

def test_on_call_fires_for_explicit_tavily(monkeypatch):
    """on_call telemetry must fire for provider='tavily' path."""
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: _tavily_result(q, **k),
    )
    records: list[dict] = []
    search("test", provider="tavily", on_call=records.append)
    assert len(records) == 1
    assert records[0]["provider"] == "tavily"
    assert records[0]["ok"] is True


def test_on_call_fires_for_explicit_brave(monkeypatch):
    """on_call telemetry must fire for provider='brave' path."""
    monkeypatch.setattr(
        "agents.tools.search._brave_search",
        lambda q, **k: _brave_result(q, **k),
    )
    records: list[dict] = []
    search("test", provider="brave", on_call=records.append)
    assert len(records) == 1
    assert records[0]["provider"] == "brave"
    assert records[0]["ok"] is True


def test_on_call_fires_on_tavily_error(monkeypatch):
    """on_call fires with ok=False when provider='tavily' raises."""
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    records: list[dict] = []
    with pytest.raises(RuntimeError):
        search("test", provider="tavily", on_call=records.append)
    assert len(records) == 1
    assert records[0]["ok"] is False


# ---------------------------------------------------------------------------
# search_many() mirrors provider kwarg
# ---------------------------------------------------------------------------

def test_search_many_plumbs_provider_brave(monkeypatch):
    """search_many() with provider='brave' must never call Tavily."""
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: pytest.fail("Tavily must not be called when provider='brave'"),
    )
    monkeypatch.setattr(
        "agents.tools.search._brave_search",
        lambda q, **k: _brave_result(q, **k),
    )
    out = search_many(["q1", "q2"], provider="brave")
    assert all(r.provider == "brave" for r in out)


def test_search_many_plumbs_provider_tavily(monkeypatch):
    """search_many() with provider='tavily' returns Tavily results."""
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: _tavily_result(q, **k),
    )
    out = search_many(["q1", "q2"], provider="tavily")
    assert all(r.provider == "tavily" for r in out)
