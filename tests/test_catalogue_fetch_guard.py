"""D24 leakage guard on the catalogue fetch layer, including redirects.

The existing guard checks the requested URL. These tests pin the harder
case: a clean URL whose redirect chain lands on a deny-listed host must
also be refused, because a portal could 302 to data.europa.eu and leak
ODMI's own publishing surface into a harvest. No network: httpx
MockTransport serves canned responses.
"""

from __future__ import annotations

import httpx
import pytest

from agents.tools.catalogue import _fetch
from agents.tools.catalogue._fetch import BlockedEndpointError


def _patched_client(monkeypatch, handler):
    """Make _fetch's httpx.Client use a MockTransport serving `handler`."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_with_transport(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(_fetch.httpx, "Client", client_with_transport)


def _redirecting_handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "portal.example":
        return httpx.Response(
            302, headers={"location": "https://data.europa.eu/api/datasets"}
        )
    return httpx.Response(200, json={"leaked": True})


def test_fetch_json_refuses_redirect_to_denylisted_host(monkeypatch):
    _patched_client(monkeypatch, _redirecting_handler)
    with pytest.raises(BlockedEndpointError):
        _fetch.fetch_json("https://portal.example/api/3/action/package_search")


def test_fetch_bytes_refuses_redirect_to_denylisted_host(monkeypatch):
    _patched_client(monkeypatch, _redirecting_handler)
    with pytest.raises(BlockedEndpointError):
        _fetch.fetch_bytes("https://portal.example/catalog.ttl")


def test_fetch_json_clean_redirect_still_works(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "old.example":
            return httpx.Response(
                301, headers={"location": "https://new.example/api"}
            )
        return httpx.Response(200, json={"ok": True})

    _patched_client(monkeypatch, handler)
    assert _fetch.fetch_json("https://old.example/api") == {"ok": True}


def test_post_json_refuses_denylisted_url():
    with pytest.raises(BlockedEndpointError):
        _fetch.post_json("https://data.europa.eu/search", {"q": "x"})


def test_post_json_refuses_redirect_to_denylisted_host(monkeypatch):
    _patched_client(monkeypatch, _redirecting_handler)
    with pytest.raises(BlockedEndpointError):
        _fetch.post_json("https://portal.example/search/datasets", {"q": "x"})


def test_post_json_posts_body_and_parses_response(monkeypatch):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["body"] = request.content
        return httpx.Response(200, json={"hits": []})

    _patched_client(monkeypatch, handler)
    out = _fetch.post_json("https://portal.example/search", {"page": 0})
    assert out == {"hits": []}
    assert seen["method"] == "POST"
    assert b'"page"' in seen["body"]
