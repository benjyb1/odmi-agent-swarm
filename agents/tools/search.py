"""Web-search wrapper with a Tavily → Brave fallback.

Tavily is the primary search provider; result quality is best for the
ODMI-style questions the swarm asks. Brave Search is the fallback when
Tavily's monthly credits are exhausted. The wrapper centralises retry
policy, returns a single Pydantic-typed result type, and exposes a
session-state record so the dashboard can show which provider served
which query.

Optional include-domains routing piggybacks on the per-country trusted
domains JSONs in `data/trusted_domains/<cc>.json` — see
`agents/tools/trusted_domains.py`.
"""

from __future__ import annotations

import os
from typing import List, Optional

import httpx
from dotenv import load_dotenv
from pathlib import Path
from pydantic import BaseModel
from tavily import TavilyClient, UsageLimitExceededError

from agents.tools.blocked_domains import BLOCKED_DOMAINS, is_blocked

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=True)


_PROVIDER_USAGE_COUNTERS: dict[str, int] = {"tavily": 0, "brave": 0}
_TAVILY_QUOTA_EXHAUSTED: bool = False
_BLOCKED_RESULT_COUNTER: int = 0


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    score: Optional[float] = None
    provider: str = "tavily"


# ============================================================
# Tavily
# ============================================================

def _tavily_client() -> TavilyClient:
    return TavilyClient(api_key=os.environ["TAVILY_API_KEY"])


def _tavily_search(
    query: str,
    *,
    max_results: int,
    topic: str,
    include_domains: Optional[List[str]],
) -> List[SearchResult]:
    response = _tavily_client().search(
        query=query,
        max_results=max_results,
        topic=topic,
        include_domains=include_domains or [],
        exclude_domains=list(BLOCKED_DOMAINS),
    )
    out: List[SearchResult] = []
    for r in response.get("results", []):
        out.append(
            SearchResult(
                title=str(r.get("title") or "").strip(),
                url=str(r.get("url") or "").strip(),
                snippet=str(r.get("content") or "").strip(),
                score=float(r.get("score")) if r.get("score") is not None else None,
                provider="tavily",
            )
        )
    return out


# ============================================================
# Brave Search (fallback)
# ============================================================

_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


def _brave_search(
    query: str,
    *,
    max_results: int,
    include_domains: Optional[List[str]],
) -> List[SearchResult]:
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        raise RuntimeError(
            "BRAVE_SEARCH_API_KEY is not set. Add it to .env to enable "
            "the Tavily fallback."
        )

    # Brave doesn't take include_domains directly; we add `site:` clauses.
    # We also append a `-site:` clause for every entry on the hard
    # deny-list so leakage sources are excluded at the query level too.
    site_clause = ""
    if include_domains:
        site_clause = " (" + " OR ".join(
            f"site:{d}" for d in include_domains
        ) + ")"
    block_clause = " " + " ".join(f"-site:{d}" for d in BLOCKED_DOMAINS)
    q = f"{query}{site_clause}{block_clause}"

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {"q": q, "count": min(max_results, 20)}

    with httpx.Client(timeout=20.0) as client:
        response = client.get(_BRAVE_ENDPOINT, headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()

    out: List[SearchResult] = []
    for r in payload.get("web", {}).get("results", [])[:max_results]:
        out.append(
            SearchResult(
                title=str(r.get("title") or "").strip(),
                url=str(r.get("url") or "").strip(),
                snippet=str(r.get("description") or "").strip(),
                score=None,
                provider="brave",
            )
        )
    return out


# ============================================================
# Public interface
# ============================================================

def _scrub_blocked(results: List[SearchResult]) -> List[SearchResult]:
    """Last-line defence: drop any result whose URL hits the deny-list.

    Both Tavily and Brave receive deny-list hints at query time, but a
    provider can ignore those hints, especially when a mirror domain
    sneaks in via a redirect. This pass guarantees the deny-list is
    honoured regardless.
    """
    global _BLOCKED_RESULT_COUNTER
    keep: List[SearchResult] = []
    for r in results:
        if is_blocked(r.url):
            _BLOCKED_RESULT_COUNTER += 1
            continue
        keep.append(r)
    return keep


def search(
    query: str,
    *,
    max_results: int = 5,
    topic: str = "general",
    include_domains: Optional[List[str]] = None,
) -> List[SearchResult]:
    """Run one search with automatic Tavily → Brave fallback.

    `topic` is Tavily-specific; Brave ignores it. `include_domains`
    works on both (Brave gets it via `site:` clauses).

    If Tavily reports its monthly credit ceiling as exhausted, the
    wrapper sticks to Brave for the rest of the session.

    Blocked domains (see `agents.tools.blocked_domains`) are excluded
    from both providers' results regardless of `include_domains`.
    """
    global _TAVILY_QUOTA_EXHAUSTED

    if not _TAVILY_QUOTA_EXHAUSTED:
        try:
            results = _tavily_search(
                query,
                max_results=max_results,
                topic=topic,
                include_domains=include_domains,
            )
            _PROVIDER_USAGE_COUNTERS["tavily"] += 1
            return _scrub_blocked(results)
        except UsageLimitExceededError:
            _TAVILY_QUOTA_EXHAUSTED = True
            # fall through to Brave
        except Exception as exc:  # noqa: BLE001
            # Network or other transient error. Try Brave once before
            # giving up; this keeps the swarm rolling on flaky Tavily
            # responses too.
            msg = str(exc).lower()
            if "rate" in msg or "quota" in msg or "limit" in msg or "credit" in msg:
                _TAVILY_QUOTA_EXHAUSTED = True
            else:
                raise

    results = _brave_search(
        query, max_results=max_results, include_domains=include_domains,
    )
    _PROVIDER_USAGE_COUNTERS["brave"] += 1
    return _scrub_blocked(results)


def search_many(
    queries: List[str],
    *,
    max_results_per_query: int = 5,
    topic: str = "general",
    include_domains: Optional[List[str]] = None,
) -> List[SearchResult]:
    """Run several queries, deduplicate by URL, preserve order of first occurrence."""
    seen: set[str] = set()
    out: List[SearchResult] = []
    for q in queries:
        for r in search(
            q,
            max_results=max_results_per_query,
            topic=topic,
            include_domains=include_domains,
        ):
            if r.url in seen:
                continue
            seen.add(r.url)
            out.append(r)
    return out


def format_for_prompt(results: List[SearchResult], *, max_chars_per_snippet: int = 600) -> str:
    """Format results as a numbered block to paste into an LLM prompt."""
    if not results:
        return "(no results)"
    lines: List[str] = []
    for i, r in enumerate(results, 1):
        snippet = r.snippet[:max_chars_per_snippet]
        if len(r.snippet) > max_chars_per_snippet:
            snippet += " ..."
        lines.append(
            f"[{i}] {r.title}\n    URL: {r.url}\n    "
            f"Snippet: {snippet}\n    (via {r.provider})"
        )
    return "\n\n".join(lines)


def session_usage() -> dict:
    """Snapshot of which provider served how many queries this process."""
    return {
        **_PROVIDER_USAGE_COUNTERS,
        "tavily_quota_exhausted": _TAVILY_QUOTA_EXHAUSTED,
        "blocked_results_scrubbed": _BLOCKED_RESULT_COUNTER,
    }
