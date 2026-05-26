"""Unit tests for agents/tools/search_diy.py.

All network calls are mocked at each layer seam. No real HTTP, Serper,
Playwright, or Claude calls are made.
"""
import pytest
from unittest.mock import patch, MagicMock
from agents.tools.search import SearchResult
from agents.tools.snippet_picker import PickedChunk
from agents.models import LLMUsage


# ---------------------------------------------------------------------------
# Shared fixture: isolate cache to a temp DB and stub all four layers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_layers(monkeypatch, tmp_path):
    """Mock all four layers so diy_search runs without network."""
    # Isolate cache to a temp DB
    import agents.tools.search_cache as cache_mod
    monkeypatch.setattr(cache_mod, "_DB_PATH", tmp_path / "test_diy.db")
    monkeypatch.setattr(cache_mod, "_TABLES_ENSURED", False)

    # Mock serper_search at the import seam used by search_diy
    serper_calls = []

    def fake_serper(query, **kw):
        serper_calls.append(query)
        return [
            SearchResult(title="A", url="https://a.example", snippet="raw A",
                         score=1.0, provider="serper"),
            SearchResult(title="B", url="https://b.example", snippet="raw B",
                         score=0.5, provider="serper"),
        ]

    monkeypatch.setattr("agents.tools.search_diy.serper_search", fake_serper)

    # Mock fetch_text
    from agents.tools.fetch import FetchResult

    def fake_fetch_text(url, **kw):
        return FetchResult(
            url=url, backend="httpx", status_code=200,
            content=f"FETCHED:{url}", truncated=False, failure_mode=None,
        )

    monkeypatch.setattr("agents.tools.search_diy.fetch_text", fake_fetch_text)

    # Mock extract -- passthrough
    monkeypatch.setattr(
        "agents.tools.search_diy.extract_text",
        lambda content, url, is_html=True: content,
    )

    # Mock pick_snippet
    fake_usage = LLMUsage(
        input_tokens=1, output_tokens=1, wall_clock_ms=1,
        estimated_cost_usd=0.0, model_version="test",
        prompt_version_id=None, condition_label="t", raw_response="{}",
    )

    def fake_picker(*, query, url, page_text, subtrio_id=None):
        return ([PickedChunk(text=f"good chunk for {url}", score=0.9)], fake_usage)

    monkeypatch.setattr("agents.tools.search_diy.pick_snippet", fake_picker)

    return {"serper_calls": serper_calls}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_diy_returns_searchresults_with_provider_diy(mock_layers):
    from agents.tools.search_diy import diy_search
    out = diy_search("test query")
    assert len(out) == 2
    assert all(r.provider == "diy" for r in out)
    assert all(r.snippet.startswith("good chunk") for r in out)


def test_diy_drops_urls_with_empty_chunks(mock_layers, monkeypatch):
    """If picker returns no chunks for a URL, that URL drops out of results."""
    fake_usage = LLMUsage(
        input_tokens=1, output_tokens=1, wall_clock_ms=1,
        estimated_cost_usd=0.0, model_version="test",
        prompt_version_id=None, condition_label="t", raw_response="{}",
    )

    def picker_drops_a(*, query, url, page_text, subtrio_id=None):
        if "a.example" in url:
            return ([], fake_usage)
        return ([PickedChunk(text="kept", score=0.8)], fake_usage)

    monkeypatch.setattr("agents.tools.search_diy.pick_snippet", picker_drops_a)

    from agents.tools.search_diy import diy_search
    out = diy_search("test query")
    assert len(out) == 1
    assert "b.example" in out[0].url


def test_diy_max_results_cap(mock_layers):
    from agents.tools.search_diy import diy_search
    out = diy_search("test query", max_results=1)
    assert len(out) == 1


def test_diy_serp_cache_hit_skips_serper(mock_layers):
    """Second call with same query must NOT re-call serper."""
    from agents.tools.search_diy import diy_search
    diy_search("test query")
    diy_search("test query")  # second call
    # serper should have been called only once
    assert len(mock_layers["serper_calls"]) == 1


def test_diy_uses_fetch_rendered_when_httpx_empty(mock_layers, monkeypatch):
    """If fetch_text returns empty, fetch_rendered_text must be tried."""
    from agents.tools.fetch import FetchResult

    def empty_httpx(url, **kw):
        return FetchResult(url=url, backend="httpx", status_code=200,
                           content="", truncated=False,
                           failure_mode="empty_after_strip")

    rendered_calls = []

    def fake_rendered(url, **kw):
        rendered_calls.append(url)
        return FetchResult(url=url, backend="playwright", status_code=200,
                           content=f"PW:{url}", truncated=False,
                           failure_mode=None)

    monkeypatch.setattr("agents.tools.search_diy.fetch_text", empty_httpx)
    monkeypatch.setattr("agents.tools.search_diy.fetch_rendered_text", fake_rendered)

    from agents.tools.search_diy import diy_search
    out = diy_search("test query")
    assert len(rendered_calls) == 2  # both URLs fell through to Playwright


def test_diy_drops_url_when_all_fetches_fail(mock_layers, monkeypatch):
    """If both fetch backends fail, the URL is dropped."""
    from agents.tools.fetch import FetchResult

    def fail_httpx(url, **kw):
        return FetchResult(url=url, backend="httpx", status_code=0,
                           content="", truncated=False, failure_mode="timeout")

    def fail_rendered(url, **kw):
        return FetchResult(url=url, backend="playwright", status_code=0,
                           content="", truncated=False, failure_mode="timeout")

    monkeypatch.setattr("agents.tools.search_diy.fetch_text", fail_httpx)
    monkeypatch.setattr("agents.tools.search_diy.fetch_rendered_text", fail_rendered)

    from agents.tools.search_diy import diy_search
    out = diy_search("test query")
    assert out == []


def test_diy_empty_serp_returns_empty(mock_layers, monkeypatch):
    """If Serper returns no results, diy_search returns an empty list."""
    monkeypatch.setattr(
        "agents.tools.search_diy.serper_search",
        lambda query, **kw: [],
    )
    from agents.tools.search_diy import diy_search
    out = diy_search("test query")
    assert out == []


def test_diy_score_comes_from_aggregate_score(mock_layers, monkeypatch):
    """SearchResult.score must equal the top PickedChunk's score."""
    fake_usage = LLMUsage(
        input_tokens=1, output_tokens=1, wall_clock_ms=1,
        estimated_cost_usd=0.0, model_version="test",
        prompt_version_id=None, condition_label="t", raw_response="{}",
    )

    def picker_with_known_score(*, query, url, page_text, subtrio_id=None):
        return ([PickedChunk(text="passage", score=0.77)], fake_usage)

    monkeypatch.setattr("agents.tools.search_diy.pick_snippet", picker_with_known_score)

    from agents.tools.search_diy import diy_search
    out = diy_search("test query")
    assert len(out) == 2
    for r in out:
        assert r.score == pytest.approx(0.77)


def test_diy_fetch_cache_hit_skips_fetch_text(mock_layers, monkeypatch):
    """After a URL is fetched once, a second call for the same URL must NOT
    re-invoke fetch_text (the fetch cache should serve it)."""
    fetch_text_calls = []
    from agents.tools.fetch import FetchResult

    def counting_fetch(url, **kw):
        fetch_text_calls.append(url)
        return FetchResult(
            url=url, backend="httpx", status_code=200,
            content=f"FETCHED:{url}", truncated=False, failure_mode=None,
        )

    monkeypatch.setattr("agents.tools.search_diy.fetch_text", counting_fetch)

    from agents.tools.search_diy import diy_search
    diy_search("test query")
    first_count = len(fetch_text_calls)
    diy_search("test query")  # SERP cached; fetch cache should also be warm
    second_count = len(fetch_text_calls)
    # No new fetch_text calls on the second run
    assert second_count == first_count
