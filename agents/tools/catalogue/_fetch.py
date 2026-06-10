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


def _guard_response(resp: httpx.Response) -> None:
    """Re-check after redirects: a clean URL must not land on a deny-listed
    host via a 30x chain. Checked before the body is read into the caller."""
    final_url = str(resp.url)
    if is_blocked(final_url):
        raise BlockedEndpointError(
            "refusing response: redirect chain landed on a deny-listed "
            f"endpoint ({blocked_reason(final_url)}): {final_url}"
        )
    for r in resp.history:
        hop = str(r.url)
        if is_blocked(hop):
            raise BlockedEndpointError(
                "refusing response: redirect chain passed through a "
                f"deny-listed endpoint ({blocked_reason(hop)}): {hop}"
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
        _guard_response(resp)
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
        _guard_response(resp)
        resp.raise_for_status()
        return resp.content


def post_json(
    url: str, body: dict, *, timeout_s: float = DEFAULT_TIMEOUT_S
) -> dict:
    """POST a JSON body and parse the JSON response, with the same guard.

    Used by search-service routes (the FDK pattern) where dataset ids are
    enumerated by POSTing a query rather than GETting a feed.
    """
    _guard(url)
    with httpx.Client(
        timeout=timeout_s,
        follow_redirects=True,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
    ) as client:
        resp = client.post(url, json=body)
        _guard_response(resp)
        resp.raise_for_status()
        return resp.json()
