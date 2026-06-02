"""HTTP helpers for the catalogue harvest, with the D24 leakage guard.

Every catalogue fetch goes through here so the deny-list assertion and the
polite User-Agent are applied uniformly. A blocked endpoint raises rather
than returning data: the harvester must never read data.europa.eu or any
mirror, even by misconfiguration.
"""

from __future__ import annotations

from typing import Optional

import httpx

from agents.tools.blocked_domains import blocked_reason, is_blocked
from agents.tools.fetch import DEFAULT_USER_AGENT

DEFAULT_TIMEOUT_S = 30.0


class BlockedEndpointError(RuntimeError):
    """Raised when a catalogue endpoint lands on the D24 deny-list."""


def _guard(url: str) -> None:
    if is_blocked(url):
        raise BlockedEndpointError(
            f"refusing to fetch deny-listed endpoint ({blocked_reason(url)}): {url}"
        )


def fetch_json(url: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict:
    """GET a URL and parse JSON. Raises on deny-list, non-200, or bad JSON."""
    _guard(url)
    with httpx.Client(
        timeout=timeout_s,
        follow_redirects=True,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


def fetch_bytes(
    url: str, *, timeout_s: float = 60.0, accept: Optional[str] = None
) -> bytes:
    """GET a URL and return the raw body bytes (for RDF feeds)."""
    _guard(url)
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    if accept:
        headers["Accept"] = accept
    with httpx.Client(
        timeout=timeout_s, follow_redirects=True, headers=headers
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content
