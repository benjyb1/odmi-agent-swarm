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
    # Reset the cold-cache toggle so the cache-hit assertions below are not
    # affected by a prior test leaving reads disabled.
    monkeypatch.setattr(cache_mod, "_READ_DISABLED", False)

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

    # Mock fetch_html (the DIY pipeline fetches raw HTML)
    from agents.tools.fetch import FetchResult

    def fake_fetch_html(url, **kw):
        return FetchResult(
            url=url, backend="httpx", status_code=200,
            content=f"FETCHED:{url}", truncated=False, failure_mode=None,
        )

    monkeypatch.setattr("agents.tools.search_diy.fetch_html", fake_fetch_html)

    # Mock extract -- passthrough (real trafilatura is exercised separately)
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
    """If fetch_html returns empty, fetch_rendered_html must be tried."""
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

    monkeypatch.setattr("agents.tools.search_diy.fetch_html", empty_httpx)
    monkeypatch.setattr("agents.tools.search_diy.fetch_rendered_html", fake_rendered)

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

    monkeypatch.setattr("agents.tools.search_diy.fetch_html", fail_httpx)
    monkeypatch.setattr("agents.tools.search_diy.fetch_rendered_html", fail_rendered)

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


# ---------------------------------------------------------------------------
# Root-cause fix: extraction must run on RAW HTML before any truncation.
# These exercise the real trafilatura extract (not the passthrough mock).
# ---------------------------------------------------------------------------

_RAW_ARTICLE = """
<!DOCTYPE html><html lang="en"><head><title>Portal</title>
<style>.nav{color:#333}</style><script>var t=1;function f(){return 2;}</script></head>
<body>
  <nav><ul><li><a href="/">Home</a></li><li><a href="/data">Datasets</a></li></ul></nav>
  <article>
    <h1>Open Data Maturity 2024</h1>
    <p>France published a national RSS feed so users are notified of every new dataset.</p>
    <p>The Impact dimension improved markedly over the previous cycle.</p>
  </article>
  <footer><p>Cookie policy | Privacy notice | Contact</p></footer>
</body></html>
"""


def _raw_fetch_result(url, html):
    from agents.tools.fetch import FetchResult
    return FetchResult(url=url, backend="httpx", status_code=200,
                       content=html, truncated=False, failure_mode=None)


def test_fetch_and_clean_runs_trafilatura_on_raw_html(monkeypatch):
    """_fetch_and_clean must return trafilatura-extracted main content:
    article body present, nav/footer boilerplate stripped, HTML tags gone."""
    monkeypatch.setattr(
        "agents.tools.search_diy.fetch_html",
        lambda url, **kw: _raw_fetch_result(url, _RAW_ARTICLE),
    )
    from agents.tools.search_diy import _fetch_and_clean
    text = _fetch_and_clean("https://x.example/report")

    assert "national RSS feed" in text          # article body survives
    assert "Cookie policy" not in text           # footer boilerplate stripped
    assert "<article>" not in text and "<nav>" not in text  # tags gone
    assert "function f()" not in text            # inline script content gone


def test_fetch_and_clean_keeps_content_past_4000_chars(monkeypatch):
    """The old 4000-char fetch cap dropped answers deep in long pages.
    Extraction on raw HTML must keep a target sentence past char 4000."""
    padding = "<p>Filler sentence about open data policy context.</p>" * 200
    big = (f"<html><body><article><h1>Long Report</h1>{padding}"
           f"<p>The decisive figure is that the portal hosts 87 percent of datasets.</p>"
           f"</article></body></html>")
    assert len(big) > 4000
    monkeypatch.setattr(
        "agents.tools.search_diy.fetch_html",
        lambda url, **kw: _raw_fetch_result(url, big),
    )
    from agents.tools.search_diy import _fetch_and_clean
    text = _fetch_and_clean("https://x.example/long")
    assert "87 percent of datasets" in text


def test_fetch_and_clean_falls_back_to_rendered_html(monkeypatch):
    """When httpx raw fetch yields nothing, the Playwright raw-HTML fallback
    is used and its content is extracted."""
    from agents.tools.fetch import FetchResult

    def empty_html(url, **kw):
        return FetchResult(url=url, backend="httpx", status_code=200,
                           content="", truncated=False,
                           failure_mode="empty_after_strip")

    monkeypatch.setattr("agents.tools.search_diy.fetch_html", empty_html)
    monkeypatch.setattr(
        "agents.tools.search_diy.fetch_rendered_html",
        lambda url, **kw: _raw_fetch_result(url, _RAW_ARTICLE),
    )
    from agents.tools.search_diy import _fetch_and_clean
    text = _fetch_and_clean("https://x.example/spa")
    assert "national RSS feed" in text


def test_diy_fetch_cache_hit_skips_fetch_html(mock_layers, monkeypatch):
    """After a URL is fetched once, a second call for the same URL must NOT
    re-invoke fetch_html (the fetch cache should serve it)."""
    fetch_html_calls = []
    from agents.tools.fetch import FetchResult

    def counting_fetch(url, **kw):
        fetch_html_calls.append(url)
        return FetchResult(
            url=url, backend="httpx", status_code=200,
            content=f"FETCHED:{url}", truncated=False, failure_mode=None,
        )

    monkeypatch.setattr("agents.tools.search_diy.fetch_html", counting_fetch)

    from agents.tools.search_diy import diy_search
    diy_search("test query")
    first_count = len(fetch_html_calls)
    diy_search("test query")  # SERP cached; fetch cache should also be warm
    second_count = len(fetch_html_calls)
    # No new fetch_html calls on the second run
    assert second_count == first_count


# ---------------------------------------------------------------------------
# 30s fetch-stage ceiling (D43)
# ---------------------------------------------------------------------------

def test_fetch_stage_deadline_returns_partial_no_blocker(monkeypatch, tmp_path):
    """A fetch stage that blows the wall-clock ceiling returns partial results.

    D43 revised 2026-06-24: a slow fetch stage is now a PER-PAIR event, not a
    batch blocker. The deadline still abandons the hung futures so a single
    pair doesn't spin forever, but the function returns what was fetched in
    time (possibly nothing) rather than raising BlockerShutdown and stopping
    the whole batch on one slow national portal.

    A stall is still recorded via _record_fetch_stall so the dispatch's
    systemic breaker can tell one slow portal from a batch-wide block.
    """
    import time as _time
    import agents.tools.search_cache as cache_mod
    import agents.tools.search_diy as diy
    from agents.errors import BlockerShutdown
    from agents.tools.fetch import FetchResult

    monkeypatch.setattr(cache_mod, "_DB_PATH", tmp_path / "deadline.db")
    monkeypatch.setattr(cache_mod, "_TABLES_ENSURED", False)
    monkeypatch.setattr(cache_mod, "_READ_DISABLED", False)
    # Tight ceiling so the test is fast; production is DIY_FETCH_DEADLINE_S=30.
    monkeypatch.setattr(diy, "DIY_FETCH_DEADLINE_S", 0.3)

    monkeypatch.setattr(diy, "serper_search", lambda q, **k: [
        SearchResult(title="A", url="https://slow.example", snippet="s",
                     score=1.0, provider="serper"),
    ])

    def slow_fetch_html(url, **kw):
        _time.sleep(2.0)  # far exceeds the 0.3s ceiling
        return FetchResult(url=url, backend="httpx", status_code=200,
                           content="x", truncated=False, failure_mode=None)

    monkeypatch.setattr(diy, "fetch_html", slow_fetch_html)

    stall_calls: list[None] = []
    monkeypatch.setattr(diy, "_record_fetch_stall",
                        lambda: stall_calls.append(None))

    try:
        results = diy.diy_search("q", max_results=3)
    except BlockerShutdown:
        pytest.fail("diy_search must not raise BlockerShutdown on a slow "
                    "fetch stage (D43 revised 2026-06-24)")

    assert results == [], "no URL returned in time, so the result list is empty"
    assert len(stall_calls) == 1, (
        "the fetch-stage stall must be recorded for the dispatch's systemic "
        "breaker"
    )
