"""Tavily web search wrapper. Used by Researcher and Verifier.

The wrapper centralises retry/timeout policy and gives both agents a
single Pydantic-typed result so they don't reinvent it.
"""

from __future__ import annotations

import os
from typing import List, Optional

from dotenv import load_dotenv
from pathlib import Path
from pydantic import BaseModel
from tavily import TavilyClient

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=True)


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    score: Optional[float] = None


def _client() -> TavilyClient:
    return TavilyClient(api_key=os.environ["TAVILY_API_KEY"])


def search(
    query: str,
    *,
    max_results: int = 5,
    topic: str = "general",
    include_domains: Optional[List[str]] = None,
) -> List[SearchResult]:
    """Run a single Tavily search and return typed results.

    `topic` defaults to "general" per Q8. Re-evaluate if ODMI policy
    questions need news-style retrieval.
    """
    response = _client().search(
        query=query,
        max_results=max_results,
        topic=topic,
        include_domains=include_domains or [],
    )
    out: List[SearchResult] = []
    for r in response.get("results", []):
        out.append(
            SearchResult(
                title=str(r.get("title") or "").strip(),
                url=str(r.get("url") or "").strip(),
                snippet=str(r.get("content") or "").strip(),
                score=float(r.get("score")) if r.get("score") is not None else None,
            )
        )
    return out


def search_many(
    queries: List[str],
    *,
    max_results_per_query: int = 5,
    topic: str = "general",
) -> List[SearchResult]:
    """Run several queries, deduplicate by URL, preserve order of first occurrence."""
    seen: set[str] = set()
    out: List[SearchResult] = []
    for q in queries:
        for r in search(q, max_results=max_results_per_query, topic=topic):
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
        lines.append(f"[{i}] {r.title}\n    URL: {r.url}\n    Snippet: {snippet}")
    return "\n\n".join(lines)
