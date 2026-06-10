"""Serper.dev Google-SERP wrapper.

POST https://google.serper.dev/search with X-API-KEY. Returns the same
SearchResult shape as the rest of the search module. Score is derived
from the result's `position` (1/position) so the highest-ranked hit
scores 1.0 and rank 10 scores 0.1.

`include_domains` is rendered as `site:` clauses appended to the
query, capped at 8 to avoid Brave-style operator-limit failures.
"""
from __future__ import annotations

import os
from typing import List, Optional

import httpx

from agents.tools.search import SearchResult

_ENDPOINT = "https://google.serper.dev/search"
_INCLUDE_DOMAIN_CAP = 8


def _build_query(query: str, include_domains: Optional[List[str]]) -> str:
    if not include_domains:
        return query
    capped = list(include_domains)[:_INCLUDE_DOMAIN_CAP]
    site_clause = " (" + " OR ".join(f"site:{d}" for d in capped) + ")"
    return f"{query}{site_clause}"


def serper_search(
    query: str,
    *,
    max_results: int = 5,
    include_domains: Optional[List[str]] = None,
) -> List[SearchResult]:
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "SERPER_API_KEY is not set. Add it to .env to enable Serper."
        )

    q = _build_query(query, include_domains)
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    # Serper's `num` parameter is capped at 20 per request by the upstream API.
    body = {"q": q, "num": min(max_results, 20)}

    with httpx.Client(timeout=20.0) as client:
        response = client.post(_ENDPOINT, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()

    out: List[SearchResult] = []
    for r in payload.get("organic", [])[:max_results]:
        position = r.get("position") or (len(out) + 1)
        out.append(SearchResult(
            title=str(r.get("title") or "").strip(),
            url=str(r.get("link") or "").strip(),
            snippet=str(r.get("snippet") or "").strip(),
            score=round(1.0 / max(position, 1), 3),
            provider="serper",
        ))
    return out


def check_serper_credits() -> tuple[bool, str]:
    """Preflight: is Serper usable right now?

    Returns (ok, reason). ok=False with a human-readable reason when the key is
    missing or the account is out of credits (Serper returns HTTP 400
    {"message": "Not enough credits"}). Used to fail an experiment loudly the
    moment its sole search provider is unavailable, rather than degrading
    silently. A tiny 1-result probe; cheap when credits exist.
    """
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        return False, "SERPER_API_KEY is not set in .env"
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                _ENDPOINT,
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": "test", "num": 1},
            )
        if resp.status_code == 200:
            return True, "ok"
        try:
            msg = resp.json().get("message", resp.text[:120])
        except Exception:
            msg = resp.text[:120]
        return False, f"Serper HTTP {resp.status_code}: {msg}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Serper probe failed: {type(exc).__name__}: {str(exc)[:120]}"
