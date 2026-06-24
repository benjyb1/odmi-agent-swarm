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

import sys
from concurrent.futures import (
    ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout,
)
from typing import List, Optional

from agents.errors import BlockerShutdown
from agents.tools.search import SearchResult
from agents.tools.search_serper import serper_search
from agents.tools.blocked_domains import is_blocked
from agents.tools.fetch import fetch_html, fetch_rendered_html
from agents.tools.extract import extract_text
from agents.tools.snippet_picker import (
    pick_snippet, aggregate_snippet, aggregate_score, PickedChunk,
)
from agents.prompts.snippet_picker import PAGE_TEXT_CAP
from agents.tools import search_cache as cache

FETCH_PARALLELISM = 5

# Defaults for the EXP-17 snippet-funnel knobs. They reproduce current
# production behaviour exactly: the LLM picker runs, keeps up to three
# chunks, and a page is truncated to PAGE_TEXT_CAP before the picker sees
# it. See agents/tools/snippet_picker.py and docs for the funnel rationale.
PICKER_MAX_CHUNKS_DEFAULT = 3
PAGE_TEXT_CAP_DEFAULT = PAGE_TEXT_CAP

# Per-URL fetch timeouts inside the DIY pipeline (D43). Deliberately tighter than
# the module defaults in agents/tools/fetch.py (httpx 15s, Playwright 30s). The
# worst case for one URL is httpx, then the Playwright fallback. Since 2026-06-11
# the render timeout is a TOTAL budget inside fetch_rendered_html: browser
# launch (which balloons under concurrency), goto, and the Cloudflare settle
# waits all draw from the one figure. Worst case per URL is therefore
# httpx 8s + render 13s = 21s, with real headroom under the 30s stage ceiling.
# Before that fix the settle waits (4s + a networkidle wait of up to the full
# render timeout) and the launch sat OUTSIDE the goto timeout, so one
# WAF-challenged URL could spend ~38s and trip the ceiling, which is what
# killed the 2026-06-09 EXP-9 haiku arm and the 2026-06-11 EXP-7 baseline arm
# (both on data.gov.mt fetches under machine contention). A challenge that
# cannot settle inside the budget fails fast and the URL is dropped: a stage
# that still blows 30s means something is broken at the machine level, not a
# heavy page.
# (Timeouts tightened from 10s/16s on 2026-06-09.)
DIY_HTTPX_TIMEOUT_S = 8.0
DIY_RENDER_TIMEOUT_S = 13.0

# Wall-clock ceiling on the DIY network fetch/extract stage, per query (D43).
# DIY is the sole provider on the 20x plan and must be fast. With the per-URL
# timeouts above, the parallel fetch stage clears well within 30s in the normal
# case. Exceeding it is treated as a real blocker, not a slow page: we stop the
# whole run loudly via BlockerShutdown so a human pauses and fixes the cause.
# The ceiling covers only the network stage where blockers live; the Claude
# snippet-picker that follows is metered Claude latency, not a blocker, so it is
# deliberately outside the window.
DIY_FETCH_DEADLINE_S = 30.0


def _fetch_and_clean(url: str) -> str:
    """Fetch RAW HTML and return trafilatura-extracted main content.

    This is the methodological core of the DIY pipeline. Extraction runs on
    the raw DOM, never on tag-stripped or pre-truncated text, so the main
    content survives for the snippet picker. httpx first; the Playwright
    raw-HTML fallback handles JS-rendered portals.

    Returns "" when the page cannot be fetched or yields no extractable
    content; the caller drops such URLs.
    """
    result = fetch_html(url, timeout_s=DIY_HTTPX_TIMEOUT_S)
    if (result.failure_mode in ("empty_after_strip", "timeout")
            or not result.content):
        result = fetch_rendered_html(url, timeout_s=DIY_RENDER_TIMEOUT_S)
    if result.failure_mode is not None or not result.content:
        return ""
    return extract_text(result.content, url=url, is_html=True)


def diy_search(
    query: str,
    *,
    max_results: int = 5,
    include_domains: Optional[List[str]] = None,
    subtrio_id: str | None = None,
    use_snippet_picker: bool = True,
    picker_max_chunks: int = PICKER_MAX_CHUNKS_DEFAULT,
    page_text_cap: int = PAGE_TEXT_CAP_DEFAULT,
) -> List[SearchResult]:
    """Run the full DIY pipeline and return Tavily-shaped SearchResults.

    EXP-17 funnel knobs (all default to current production behaviour):

    - ``use_snippet_picker`` (default True): when False, BYPASS the LLM
      snippet-picker. The cleaned trafilatura page text is used directly as
      the snippet (truncated to ``page_text_cap``), so a URL is NOT dropped
      just because the picker chose nothing. This tests whether the picker
      is binning the answer. The picker is not called at all in this mode.
    - ``picker_max_chunks`` (default 3): the most chunks the picker keeps
      for a non-confident page (the confident-top-hit path still returns one).
    - ``page_text_cap`` (default 16000): characters of cleaned page text the
      picker sees before truncation.
    """

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

    # Results are keyed by submission index so the final order matches the
    # SERP order, not thread-completion order. as_completed yields futures as
    # they finish (non-deterministic), which would otherwise leak into the
    # result order and make runs irreproducible (D-level requirement: every
    # evaluation must replay identically from logs).
    results_by_index: dict[int, tuple[SearchResult, str]] = {}
    pool = ThreadPoolExecutor(max_workers=FETCH_PARALLELISM)
    timed_out = False
    try:
        futures = {pool.submit(_fetch, r): i for i, r in enumerate(serp)}
        # as_completed's own timeout enforces the stage deadline. We avoid the
        # `with` context manager because its __exit__ would block on the hung
        # fetch we are trying to escape; shutdown(wait=False) abandons it (the
        # per-fetch httpx/Playwright timeouts bound it) and we stop now.
        for fut in as_completed(futures, timeout=DIY_FETCH_DEADLINE_S):
            results_by_index[futures[fut]] = fut.result()
    except FuturesTimeout:
        # D43 (revised 2026-06-24): a slow fetch stage is a PER-PAIR event, not a
        # batch blocker. A single slow national portal must never stop the whole
        # run. The 30s deadline still guards against a fetch spinning forever -
        # we abandon the hung futures here - but instead of raising
        # BlockerShutdown (which dispatch treated like a 429 and halted every pair
        # in the batch), we keep whatever returned in time and let THIS pair carry
        # on with partial evidence. Its own retry loop re-queries if that is too
        # thin. The leaked threads are bounded by the per-fetch httpx/Playwright
        # timeouts.
        timed_out = True
        pool.shutdown(wait=False, cancel_futures=True)
        print(
            f"[search_diy] fetch stage exceeded {DIY_FETCH_DEADLINE_S:.0f}s for "
            f"query {query!r}; proceeding with {len(results_by_index)}/{len(serp)} "
            f"fetched (per-pair, no batch stop)",
            file=sys.stderr,
        )
    if not timed_out:
        pool.shutdown(wait=True)
    # Reassemble in submission (SERP) order. A URL that did not return in time
    # counts as an empty fetch, exactly like a 404 or an extraction miss.
    fetched: list[tuple[SearchResult, str]] = [
        results_by_index.get(i, (serp[i], "")) for i in range(len(serp))
    ]

    # 3. Snippet pick (cached). Text is already clean main content.
    out: List[SearchResult] = []
    for r, text in fetched:
        if not text:
            continue

        if not use_snippet_picker:
            # EXP-17 picker-bypass arm. Skip the LLM picker entirely and use
            # the cleaned page text directly as the snippet (truncated to
            # page_text_cap). No URL is dropped for an empty pick, and the
            # snippet cache is left untouched because it stores picker output
            # only. score is None: there is no picker confidence here.
            out.append(SearchResult(
                title=r.title,
                url=r.url,
                snippet=text[:page_text_cap],
                score=None,
                provider="diy",
            ))
            if len(out) >= max_results:
                break
            continue

        cached_chunks = cache.snippet_get(query, text)
        if cached_chunks is None:
            # Pass the funnel knobs only when they differ from the picker's
            # own defaults, so the default production call is byte-identical
            # to before EXP-17 and existing call-site mocks keep working.
            picker_kwargs = {}
            if picker_max_chunks != PICKER_MAX_CHUNKS_DEFAULT:
                picker_kwargs["max_chunks"] = picker_max_chunks
            if page_text_cap != PAGE_TEXT_CAP_DEFAULT:
                picker_kwargs["page_text_cap"] = page_text_cap
            chunks, _ = pick_snippet(
                query=query, url=r.url, page_text=text,
                subtrio_id=subtrio_id,
                **picker_kwargs,
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
