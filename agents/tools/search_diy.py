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
from agents.tools.fetch import fetch_text, fetch_rendered_text
from agents.tools.extract import extract_text
from agents.tools.snippet_picker import (
    pick_snippet, aggregate_snippet, aggregate_score, PickedChunk,
)
from agents.tools import search_cache as cache

FETCH_PARALLELISM = 5


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

    # 2. Parallel fetch (cached). Cache stores ALREADY-CLEANED text so we
    # never re-extract on cache hits.
    def _fetch(r: SearchResult) -> tuple[SearchResult, str, bool]:
        """Return (result, text, is_already_clean)."""
        cached = cache.fetch_get(r.url)
        if cached is not None:
            return r, cached, True  # already clean, skip extract
        result = fetch_text(r.url)
        if (result.failure_mode in ("empty_after_strip", "timeout")
                or not result.content):
            result = fetch_rendered_text(r.url)
        if result.failure_mode is not None:
            return r, "", False
        # fetch_text returns tag-stripped text; treat as already-clean.
        cache.fetch_put(
            r.url, result.content,
            status_code=result.status_code, backend=result.backend,
        )
        return r, result.content, True

    fetched: list[tuple[SearchResult, str, bool]] = []
    with ThreadPoolExecutor(max_workers=FETCH_PARALLELISM) as pool:
        for fut in as_completed(pool.submit(_fetch, r) for r in serp):
            fetched.append(fut.result())

    # 3. Extract (no-op if already_clean) + snippet pick (cached)
    out: List[SearchResult] = []
    for r, text, already_clean in fetched:
        if not text:
            continue
        extracted = extract_text(text, url=r.url, is_html=not already_clean)
        if not extracted:
            continue
        cached_chunks = cache.snippet_get(query, extracted)
        if cached_chunks is None:
            chunks, _ = pick_snippet(
                query=query, url=r.url, page_text=extracted,
                subtrio_id=subtrio_id,
            )
            cache.snippet_put(query, extracted, chunks)
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
