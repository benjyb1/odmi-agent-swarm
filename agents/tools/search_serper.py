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
import threading
from typing import List, Optional

import httpx

from agents.tools.search import SearchResult

_ENDPOINT = "https://google.serper.dev/search"
_INCLUDE_DOMAIN_CAP = 8

# Wall-clock backstop for the whole SERP request. httpx's 20s timeout only
# covers connect/read once a socket exists; OS-level DNS resolution
# (getaddrinfo) runs before it and can block forever after a sleep/wake or
# network handover. Observed 2026-07-10..12: ~26 pairs hung indefinitely at
# `search_start` with no error trail. Must stay above the httpx timeout so it
# only fires on hangs the client timeout cannot see.
SERPER_WALL_CLOCK_DEADLINE_S = 45.0


class SerperDeadlineError(RuntimeError):
    """The Serper request exceeded the wall-clock deadline (likely a DNS hang)."""


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

    # The request runs in a daemon thread so the caller can enforce a
    # wall-clock deadline. A thread stuck in getaddrinfo cannot be killed,
    # but the pair now fails loudly instead of hanging the coordinator
    # subprocess, and a daemon thread never blocks interpreter exit
    # (a ThreadPoolExecutor worker would, via its atexit join).
    outcome: dict = {}
    done = threading.Event()

    def _do_post() -> None:
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post(_ENDPOINT, headers=headers, json=body)
                response.raise_for_status()
                outcome["payload"] = response.json()
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
            outcome["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=_do_post, daemon=True, name="serper-post")
    worker.start()
    if not done.wait(timeout=SERPER_WALL_CLOCK_DEADLINE_S):
        raise SerperDeadlineError(
            f"Serper SERP call exceeded {SERPER_WALL_CLOCK_DEADLINE_S:.0f}s "
            f"wall-clock deadline (query={q[:80]!r}); likely an OS-level "
            "DNS hang after sleep/wake."
        )
    if "error" in outcome:
        raise outcome["error"]
    payload = outcome["payload"]

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
