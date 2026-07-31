"""Tests for the provider kwarg added to search() and search_many().

Behaviour contract (D43 supersedes the D36 fallback chain):
- provider="auto" (default) is DIY only. On the 20x plan DIY is the sole
  production provider; "auto" is an alias for "diy" so no call site can
  silently fall back to Tavily or Brave. A DIY error propagates; an empty DIY
  result is returned empty (there is no second provider to try).
- provider="diy" is identical to "auto".
- provider="tavily" / "brave" call that provider only and remain in the code
  solely to reproduce the EXP-1 provider comparison; they are never used in
  production. If the provider raises, the error propagates (no fallback).

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


# provider="auto"

def _diy_result(query: str = "q", **_kwargs) -> list[SearchResult]:
    return [SearchResult(title="d", url="https://diy.example", snippet="s",
                         score=0.9, provider="diy")]


def test_provider_auto_is_diy_only(monkeypatch):
    """D43: provider='auto' routes to DIY, never Tavily or Brave."""
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: pytest.fail("Tavily must never be called under D43 auto"),
    )
    monkeypatch.setattr(
        "agents.tools.search._brave_search",
        lambda q, **k: pytest.fail("Brave must never be called under D43 auto"),
    )
    monkeypatch.setattr(
        "agents.tools.search_diy.diy_search",
        lambda q, **k: _diy_result(q, **k),
    )
    records: list[dict] = []
    out = search("test", provider="auto", on_call=records.append)
    assert out and all(r.provider == "diy" for r in out)
    # Exactly one provider attempt, and it is DIY.
    assert [r["provider"] for r in records] == ["diy"]


def test_provider_default_is_diy_only(monkeypatch):
    """Omitting provider must behave identically to provider='auto' (= DIY)."""
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: pytest.fail("Tavily must never be called by default"),
    )
    monkeypatch.setattr(
        "agents.tools.search_diy.diy_search",
        lambda q, **k: _diy_result(q, **k),
    )
    out_default = search("test")
    out_auto = search("test", provider="auto")
    assert [r.url for r in out_default] == [r.url for r in out_auto]
    assert all(r.provider == "diy" for r in out_default)


def test_auto_diy_error_propagates_no_brave(monkeypatch):
    """D43: a DIY failure under auto propagates; Brave is never a fallback."""
    monkeypatch.setattr(
        "agents.tools.search_diy.diy_search",
        lambda q, **k: (_ for _ in ()).throw(RuntimeError("diy down")),
    )
    monkeypatch.setattr(
        "agents.tools.search._brave_search",
        lambda q, **k: pytest.fail("Brave must not be a fallback under D43"),
    )
    records: list[dict] = []
    with pytest.raises(RuntimeError, match="diy down"):
        search("test", provider="auto", on_call=records.append)
    # One telemetry record: diy (fail). No second provider attempted.
    assert [r["provider"] for r in records] == ["diy"]
    assert records[0]["ok"] is False


def test_auto_empty_diy_returns_empty_no_brave(monkeypatch):
    """D43: an empty DIY result is returned empty; no Brave fall-through."""
    monkeypatch.setattr(
        "agents.tools.search_diy.diy_search",
        lambda q, **k: [],  # DIY succeeds but returns nothing
    )
    monkeypatch.setattr(
        "agents.tools.search._brave_search",
        lambda q, **k: pytest.fail("Brave must not be reached on empty DIY"),
    )
    monkeypatch.setattr(
        "agents.tools.search._PROVIDER_USAGE_COUNTERS",
        {"tavily": 0, "diy": 0, "brave": 0},
    )
    records: list[dict] = []
    out = search("test", provider="auto", on_call=records.append)
    assert out == []
    assert [r["provider"] for r in records] == ["diy"]
    assert records[0]["ok"] is True and records[0]["results"] == 0
    from agents.tools.search import _PROVIDER_USAGE_COUNTERS
    assert _PROVIDER_USAGE_COUNTERS["diy"] == 1
    assert _PROVIDER_USAGE_COUNTERS["brave"] == 0


def test_auto_propagates_blocker_shutdown(monkeypatch):
    """D43: a BlockerShutdown from the 30s DIY ceiling rides straight out."""
    from agents.errors import BlockerShutdown

    def _raise_blocker(q, **k):
        raise BlockerShutdown("DIY fetch stage exceeded 30s")

    monkeypatch.setattr("agents.tools.search_diy.diy_search", _raise_blocker)
    with pytest.raises(BlockerShutdown):
        search("test", provider="auto")


# provider="tavily"

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
    """provider='tavily': if Tavily raises, error propagates. Brave is NOT called."""
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


# provider="brave"

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


# on_call telemetry

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


# search_many() mirrors provider kwarg

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


# provider="diy"

def test_provider_diy_dispatches_to_diy_search(monkeypatch):
    """provider='diy' must call diy_search and return its results."""
    monkeypatch.setattr(
        "agents.tools.search_diy.diy_search",
        lambda q, **k: [SearchResult(
            title="t", url="https://x.example", snippet="s",
            score=0.9, provider="diy")],
    )
    out = search("test", provider="diy")
    assert len(out) == 1
    assert out[0].provider == "diy"


# provider="serper_raw"

def test_provider_serper_raw_dispatches(monkeypatch):
    monkeypatch.setattr(
        "agents.tools.search_serper.serper_search",
        lambda q, **k: [SearchResult(
            title="t", url="https://y.example", snippet="s",
            score=1.0, provider="serper")],
    )
    out = search("test", provider="serper_raw")
    assert len(out) == 1
    assert out[0].provider == "serper"
