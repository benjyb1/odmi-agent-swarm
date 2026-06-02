"""Regression test: DIY drops deny-listed SERP URLs BEFORE the fetch step.

Fairness confound for the provider comparison (Tavily / Brave vs DIY).
Tavily and Brave exclude deny-listed domains at query time, so such a
domain never consumes one of their result slots. DIY runs a raw Serper
SERP and then fetches/extracts each URL; if a deny-listed URL is only
removed post-hoc by ``_scrub_blocked`` in ``agents.tools.search`` it has
already burned a SERP/fetch slot, which is not comparable.

This test pins the requirement that a deny-listed URL returned by the
SERP is filtered out of the DIY pipeline before the fetch/extract step,
so it never consumes a fetch slot and never reaches the results.

All layers are mocked at the same seams the rest of the DIY suite uses;
no real network, Serper, Playwright, or Claude calls are made.
"""
import pytest
from agents.tools.search import SearchResult
from agents.tools.snippet_picker import PickedChunk
from agents.tools.blocked_domains import is_blocked, BLOCKED_DOMAINS
from agents.models import LLMUsage


_BLOCKED_URL = "https://data.europa.eu/data/datasets/example"
_CLEAN_A = "https://example.gov.fr/open-data/stats"
_CLEAN_B = "https://data.gouv.fr/datasets/national"

# The fixture assumes data.europa.eu is on the deny-list; assert it loudly
# so a future list change surfaces here rather than as a silent pass.
assert is_blocked(_BLOCKED_URL), (
    "Fixture assumes data.europa.eu is deny-listed; update if the list "
    f"changed. BLOCKED_DOMAINS={BLOCKED_DOMAINS}"
)
assert not is_blocked(_CLEAN_A) and not is_blocked(_CLEAN_B)


@pytest.fixture
def recording_layers(monkeypatch, tmp_path):
    """Stub all four DIY layers and RECORD which URLs fetch_html is asked for.

    Returns the list that fetch_html appends to, so a test can assert the
    deny-listed URL was never handed to the fetch step.
    """
    # Isolate the cache to a temp DB so nothing is served from disk.
    import agents.tools.search_cache as cache_mod
    monkeypatch.setattr(cache_mod, "_DB_PATH", tmp_path / "test_denylist.db")
    monkeypatch.setattr(cache_mod, "_TABLES_ENSURED", False)

    # SERP returns one deny-listed URL plus two clean URLs.
    def fake_serper(query, **kw):
        return [
            SearchResult(title="blocked", url=_BLOCKED_URL, snippet="raw",
                         score=1.0, provider="serper"),
            SearchResult(title="clean A", url=_CLEAN_A, snippet="raw A",
                         score=0.8, provider="serper"),
            SearchResult(title="clean B", url=_CLEAN_B, snippet="raw B",
                         score=0.6, provider="serper"),
        ]

    monkeypatch.setattr("agents.tools.search_diy.serper_search", fake_serper)

    # fetch_html records every URL it is asked to fetch.
    fetched_urls: list[str] = []
    from agents.tools.fetch import FetchResult

    def recording_fetch_html(url, **kw):
        fetched_urls.append(url)
        return FetchResult(
            url=url, backend="httpx", status_code=200,
            content=f"FETCHED:{url}", truncated=False, failure_mode=None,
        )

    monkeypatch.setattr(
        "agents.tools.search_diy.fetch_html", recording_fetch_html,
    )

    # extract passthrough -- real trafilatura is exercised elsewhere.
    monkeypatch.setattr(
        "agents.tools.search_diy.extract_text",
        lambda content, url, is_html=True: content,
    )

    # Snippet picker returns one good chunk per URL.
    fake_usage = LLMUsage(
        input_tokens=1, output_tokens=1, wall_clock_ms=1,
        estimated_cost_usd=0.0, model_version="test",
        prompt_version_id=None, condition_label="t", raw_response="{}",
    )

    def fake_picker(*, query, url, page_text, subtrio_id=None):
        return ([PickedChunk(text=f"good chunk for {url}", score=0.9)], fake_usage)

    monkeypatch.setattr("agents.tools.search_diy.pick_snippet", fake_picker)

    return {"fetched_urls": fetched_urls}


def test_denylisted_serp_url_never_fetched(recording_layers):
    """The deny-listed URL must be dropped before fetch and absent from results.

    The two clean URLs must still be fetched and returned, proving the
    filter is targeted, not a blanket drop.
    """
    from agents.tools.search_diy import diy_search
    out = diy_search("test query")

    fetched = recording_layers["fetched_urls"]

    # 1. The deny-listed URL was dropped PRE-fetch: never handed to fetch_html.
    assert _BLOCKED_URL not in fetched, (
        "deny-listed URL reached the fetch step -- it consumed a fetch slot"
    )

    # 2. Both clean URLs were fetched.
    assert _CLEAN_A in fetched
    assert _CLEAN_B in fetched

    # 3. The deny-listed URL is absent from the returned results.
    out_urls = [r.url for r in out]
    assert _BLOCKED_URL not in out_urls

    # 4. The clean URLs survive end-to-end.
    assert _CLEAN_A in out_urls
    assert _CLEAN_B in out_urls
    assert len(out) == 2


def test_denylisted_url_does_not_consume_max_results_slot(recording_layers):
    """With the deny-listed URL filtered pre-fetch, max_results counts only
    eligible URLs. A cap of 2 must still yield both clean results rather than
    being partly spent on the dropped deny-listed hit."""
    from agents.tools.search_diy import diy_search
    out = diy_search("test query", max_results=2)

    out_urls = [r.url for r in out]
    assert _BLOCKED_URL not in out_urls
    assert _CLEAN_A in out_urls
    assert _CLEAN_B in out_urls
    assert len(out) == 2
