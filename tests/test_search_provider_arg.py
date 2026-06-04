"""Tests for the provider kwarg added to search() and search_many().

Behaviour contract:
- provider="auto" (default) is a Tavily → DIY → Brave fallback chain (D36):
  Tavily first, DIY when Tavily's quota fails, Brave only if DIY also fails.
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


def _diy_result(query: str = "q", **_kwargs) -> list[SearchResult]:
    return [SearchResult(title="d", url="https://diy.example", snippet="s",
                         score=0.9, provider="diy")]


def test_auto_falls_back_to_diy_when_tavily_quota_fails(monkeypatch):
    """D36: when Tavily hits its quota, auto falls back to DIY, not Brave."""
    monkeypatch.setattr("agents.tools.search._TAVILY_QUOTA_EXHAUSTED", False)
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: (_ for _ in ()).throw(RuntimeError("quota exhausted")),
    )
    monkeypatch.setattr(
        "agents.tools.search_diy.diy_search",
        lambda q, **k: _diy_result(q, **k),
    )
    monkeypatch.setattr(
        "agents.tools.search._brave_search",
        lambda q, **k: pytest.fail("Brave must not be called while DIY succeeds"),
    )
    out = search("test", provider="auto")
    assert out and all(r.provider == "diy" for r in out)


def test_auto_falls_through_diy_to_brave(monkeypatch):
    """D36: Brave is the last resort, reached only when both Tavily and DIY fail."""
    monkeypatch.setattr("agents.tools.search._TAVILY_QUOTA_EXHAUSTED", False)
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: (_ for _ in ()).throw(RuntimeError("quota exhausted")),
    )
    monkeypatch.setattr(
        "agents.tools.search_diy.diy_search",
        lambda q, **k: (_ for _ in ()).throw(RuntimeError("diy down")),
    )
    monkeypatch.setattr(
        "agents.tools.search._brave_search",
        lambda q, **k: _brave_result(q, **k),
    )
    records: list[dict] = []
    out = search("test", provider="auto", on_call=records.append)
    assert out and all(r.provider == "brave" for r in out)
    # One telemetry record per attempt: tavily (fail), diy (fail), brave (ok).
    assert [r["provider"] for r in records] == ["tavily", "diy", "brave"]
    assert records[0]["ok"] is False and records[1]["ok"] is False
    assert records[2]["ok"] is True


def test_auto_empty_diy_falls_through_to_brave(monkeypatch):
    """An empty DIY result (no error) must still fall through to Brave."""
    monkeypatch.setattr("agents.tools.search._TAVILY_QUOTA_EXHAUSTED", False)
    monkeypatch.setattr(
        "agents.tools.search._tavily_search",
        lambda q, **k: (_ for _ in ()).throw(RuntimeError("quota exhausted")),
    )
    monkeypatch.setattr(
        "agents.tools.search_diy.diy_search",
        lambda q, **k: [],  # DIY succeeds but returns nothing
    )
    monkeypatch.setattr(
        "agents.tools.search._brave_search",
        lambda q, **k: _brave_result(q, **k),
    )
    monkeypatch.setattr(
        "agents.tools.search._PROVIDER_USAGE_COUNTERS",
        {"tavily": 0, "diy": 0, "brave": 0},
    )
    records: list[dict] = []
    out = search("test", provider="auto", on_call=records.append)
    assert out and all(r.provider == "brave" for r in out)
    # tavily (fail), diy (ok but empty), brave (ok).
    assert [r["provider"] for r in records] == ["tavily", "diy", "brave"]
    assert records[1]["ok"] is True and records[1]["results"] == 0
    assert records[2]["ok"] is True
    # DIY counted exactly once; not double-counted by the fall-through.
    from agents.tools.search import _PROVIDER_USAGE_COUNTERS
    assert _PROVIDER_USAGE_COUNTERS["diy"] == 1
    assert _PROVIDER_USAGE_COUNTERS["brave"] == 1


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


# ---------------------------------------------------------------------------
# provider="diy"
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# provider="serper_raw"
# ---------------------------------------------------------------------------

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
