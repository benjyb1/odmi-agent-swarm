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
import time
from typing import Callable, List, Literal, Optional

# Explicit provider selection for search() and search_many().
# "auto"   — existing Tavily-first-then-Brave fallback chain (default).
# "tavily" — Tavily only; errors propagate, no Brave fallback.
# "brave"  — Brave only; Tavily is never called.
# Future values ("diy", "serper_raw", …) will extend this union.
Provider = Literal["auto", "tavily", "brave", "diy", "serper_raw"]

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
    # The deny-list is enforced by `_scrub_blocked` post-filter, not in the
    # query: Brave rejects queries with too many operators (~35 ops in the
    # ODMI case → 422 Unprocessable Entity).
    site_clause = ""
    if include_domains:
        capped = list(include_domains)[:8]
        site_clause = " (" + " OR ".join(
            f"site:{d}" for d in capped
        ) + ")"
    q = f"{query}{site_clause}"

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


CallObserver = Callable[[dict], None]


def search(
    query: str,
    *,
    max_results: int = 5,
    topic: str = "general",
    include_domains: Optional[List[str]] = None,
    on_call: Optional[CallObserver] = None,
    provider: Provider = "auto",
) -> List[SearchResult]:
    """Run one search, dispatching to the requested provider(s).

    `provider` controls which search backend is used:

    - ``"auto"`` (default) — Tavily first; if Tavily's quota is
      exhausted or raises a rate/quota/credit error, falls back to
      Brave. This is unchanged from the original behaviour.
    - ``"tavily"`` — Tavily only. If Tavily raises for any reason the
      error propagates immediately; Brave is never called. Use this
      when you need deterministic provider selection (e.g. A/B
      experiments where Brave must not silently substitute).
    - ``"brave"`` — Brave only. Tavily is never called.

    `topic` is Tavily-specific; Brave ignores it. `include_domains`
    works on both (Brave gets it via `site:` clauses).

    Blocked domains (see `agents.tools.blocked_domains`) are excluded
    from all providers' results regardless of `include_domains`.

    `on_call(payload)` fires once per outbound provider call. In
    ``"auto"`` mode a Tavily failure followed by a Brave success emits
    two records. Payload keys: ``provider``, ``ms``, ``results``,
    ``ok``, ``error``. Use this for per-call telemetry without relying
    on the module-level counters.
    """
    global _TAVILY_QUOTA_EXHAUSTED

    def _emit(prov: str, started_at: float, results: List[SearchResult],
              ok: bool, error: Optional[str]) -> None:
        if on_call is None:
            return
        on_call({
            "provider": prov,
            "ms": int((time.perf_counter() - started_at) * 1000),
            "results": len(results),
            "ok": ok,
            "error": error,
        })

    # ------------------------------------------------------------------
    # Explicit single-provider paths (no fallback in either direction)
    # ------------------------------------------------------------------

    if provider == "tavily":
        t0 = time.perf_counter()
        try:
            results = _tavily_search(
                query,
                max_results=max_results,
                topic=topic,
                include_domains=include_domains,
            )
            _PROVIDER_USAGE_COUNTERS["tavily"] += 1
            _emit("tavily", t0, results, ok=True, error=None)
            return _scrub_blocked(results)
        except Exception as exc:
            _emit("tavily", t0, [], ok=False, error=str(exc)[:200])
            raise

    if provider == "brave":
        t0 = time.perf_counter()
        try:
            results = _brave_search(
                query, max_results=max_results, include_domains=include_domains,
            )
            _PROVIDER_USAGE_COUNTERS["brave"] += 1
            _emit("brave", t0, results, ok=True, error=None)
            return _scrub_blocked(results)
        except Exception as exc:
            _emit("brave", t0, [], ok=False, error=str(exc)[:200])
            raise

    if provider == "diy":
        from agents.tools.search_diy import diy_search  # local import
        t0 = time.perf_counter()
        try:
            results = diy_search(
                query, max_results=max_results, include_domains=include_domains,
            )
            _emit("diy", t0, results, ok=True, error=None)
            return _scrub_blocked(results)
        except Exception as exc:
            _emit("diy", t0, [], ok=False, error=str(exc)[:200])
            raise

    if provider == "serper_raw":
        from agents.tools.search_serper import serper_search  # local import
        t0 = time.perf_counter()
        try:
            results = serper_search(
                query, max_results=max_results, include_domains=include_domains,
            )
            _emit("serper_raw", t0, results, ok=True, error=None)
            return _scrub_blocked(results)
        except Exception as exc:
            _emit("serper_raw", t0, [], ok=False, error=str(exc)[:200])
            raise

    # ------------------------------------------------------------------
    # provider == "auto" — original Tavily-first-then-Brave chain
    # ------------------------------------------------------------------

    if not _TAVILY_QUOTA_EXHAUSTED:
        t0 = time.perf_counter()
        try:
            results = _tavily_search(
                query,
                max_results=max_results,
                topic=topic,
                include_domains=include_domains,
            )
            _PROVIDER_USAGE_COUNTERS["tavily"] += 1
            _emit("tavily", t0, results, ok=True, error=None)
            return _scrub_blocked(results)
        except UsageLimitExceededError as exc:
            _TAVILY_QUOTA_EXHAUSTED = True
            _emit("tavily", t0, [], ok=False, error=f"quota:{exc}"[:200])
            # fall through to Brave
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            _emit("tavily", t0, [], ok=False, error=str(exc)[:200])
            if "rate" in msg or "quota" in msg or "limit" in msg or "credit" in msg:
                _TAVILY_QUOTA_EXHAUSTED = True
            else:
                raise

    t0 = time.perf_counter()
    try:
        results = _brave_search(
            query, max_results=max_results, include_domains=include_domains,
        )
        _PROVIDER_USAGE_COUNTERS["brave"] += 1
        _emit("brave", t0, results, ok=True, error=None)
        return _scrub_blocked(results)
    except Exception as exc:
        _emit("brave", t0, [], ok=False, error=str(exc)[:200])
        raise


def search_many(
    queries: List[str],
    *,
    max_results_per_query: int = 5,
    topic: str = "general",
    include_domains: Optional[List[str]] = None,
    on_call: Optional[CallObserver] = None,
    provider: Provider = "auto",
) -> List[SearchResult]:
    """Run several queries, deduplicate by URL, preserve order of first occurrence.

    ``provider`` is forwarded to each per-query ``search()`` call.
    See ``search()`` for full provider semantics and ``on_call`` behaviour.
    """
    seen: set[str] = set()
    out: List[SearchResult] = []
    for q in queries:
        for r in search(
            q,
            max_results=max_results_per_query,
            topic=topic,
            include_domains=include_domains,
            on_call=on_call,
            provider=provider,
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
