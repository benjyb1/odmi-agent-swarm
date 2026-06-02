"""DIY-Tavily pipeline.

  query → Serper SERP → parallel Playwright fetch → trafilatura extract
       → Claude snippet-picker → SearchResult(provider="diy")

Composes the four layers behind the existing SearchResult interface so the
rest of the swarm sees no API difference between Tavily and DIY. Caches at
every layer via agents/tools/search_cache.py to make re-runs cheap.

URLs whose pages yield no relevant chunks (picker returns []) are dropped
from the result list entirely. Result length never exceeds max_results.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from agents.tools.search import SearchResult
from agents.tools.search_serper import serper_search
from agents.tools.blocked_domains import is_blocked
from agents.tools.fetch import fetch_html, fetch_rendered_html
from agents.tools.extract import extract_text
from agents.tools.snippet_picker import (
    pick_snippet, aggregate_snippet, aggregate_score, PickedChunk,
)
from agents.tools import search_cache as cache

FETCH_PARALLELISM = 5


def _fetch_and_clean(url: str) -> str:
    """Fetch RAW HTML and return trafilatura-extracted main content.

    This is the methodological core of the DIY pipeline. Extraction runs on
    the raw DOM, never on tag-stripped or pre-truncated text, so the main
    content survives for the snippet picker. httpx first; the Playwright
    raw-HTML fallback handles JS-rendered portals.

    Returns "" when the page cannot be fetched or yields no extractable
    content; the caller drops such URLs.
    """
    result = fetch_html(url)
    if (result.failure_mode in ("empty_after_strip", "timeout")
            or not result.content):
        result = fetch_rendered_html(url)
    if result.failure_mode is not None or not result.content:
        return ""
    return extract_text(result.content, url=url, is_html=True)


def diy_search(
    query: str,
    *,
    max_results: int = 5,
    include_domains: Optional[List[str]] = None,
    subtrio_id: str | None = None,
) -> List[SearchResult]:
    """Run the full DIY pipeline and return Tavily-shaped SearchResults."""

    # 1. SERP (cached)
    serp = cache.serp_get(query, max_results, include_domains)
    if serp is None:
        serp = serper_search(
            query, max_results=max_results, include_domains=include_domains,
        )
        cache.serp_put(query, max_results, include_domains, serp)

    # 1b. Deny-list filter BEFORE the fetch step (fairness, see D29). Tavily
    # and Brave exclude deny-listed domains at query time, so such a domain
    # never costs them a result slot. The raw Serper SERP has no such hint,
    # so a deny-listed hit would otherwise burn a fetch/extract slot here and
    # only be removed post-hoc by _scrub_blocked in agents.tools.search. We
    # drop those URLs now so they never consume a fetch slot, making the DIY
    # cost/quality comparison against Tavily/Brave like-for-like. The post-hoc
    # _scrub_blocked remains a backstop for anything a redirect sneaks past.
    serp = [r for r in serp if not is_blocked(r.url)]

    # 2. Parallel fetch + extract (cached). Raw HTML is fetched and run
    # through trafilatura HERE so the picker only ever sees clean main
    # content. The cache stores the already-extracted text, so cache hits
    # skip both fetch and extract.
    def _fetch(r: SearchResult) -> tuple[SearchResult, str]:
        """Return (result, clean_text). clean_text is "" on fetch failure."""
        cached = cache.fetch_get(r.url)
        if cached is not None:
            return r, cached
        clean = _fetch_and_clean(r.url)
        if not clean:
            return r, ""
        cache.fetch_put(r.url, clean, status_code=200, backend="diy")
        return r, clean

    fetched: list[tuple[SearchResult, str]] = []
    with ThreadPoolExecutor(max_workers=FETCH_PARALLELISM) as pool:
        for fut in as_completed(pool.submit(_fetch, r) for r in serp):
            fetched.append(fut.result())

    # 3. Snippet pick (cached). Text is already clean main content.
    out: List[SearchResult] = []
    for r, text in fetched:
        if not text:
            continue
        cached_chunks = cache.snippet_get(query, text)
        if cached_chunks is None:
            chunks, _ = pick_snippet(
                query=query, url=r.url, page_text=text,
                subtrio_id=subtrio_id,
            )
            cache.snippet_put(query, text, chunks)
        else:
            chunks = cached_chunks
        if not chunks:
            continue
        out.append(SearchResult(
            title=r.title,
            url=r.url,
            snippet=aggregate_snippet(chunks),
            score=aggregate_score(chunks),
            provider="diy",
        ))
        if len(out) >= max_results:
            break
    return out
