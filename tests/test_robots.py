"""robots.txt compliance on the Researcher/Verifier fetch layer.

The repo-wide conftest switches robots enforcement off so that ordinary
unit tests never make a robots.txt request. These tests switch it back on
and serve both robots.txt and the page itself from an httpx MockTransport,
so the behaviour is pinned without touching the network.

What matters here, in order: a disallowed path is refused before the page
is requested at all; an unreadable robots.txt fails open rather than
silently dropping evidence from a run; and robots.txt is read once per
host, not once per page.
"""

from __future__ import annotations

import httpx
import pytest

from agents.tools import fetch, robots


ALLOW_ALL = "User-agent: *\nDisallow:\n"
DISALLOW_PRIVATE = "User-agent: *\nDisallow: /private/\n"
DISALLOW_ALL = "User-agent: *\nDisallow: /\n"


@pytest.fixture(autouse=True)
def _enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn enforcement on for this module and start from a cold cache."""
    monkeypatch.setattr(robots, "ROBOTS_ENFORCED", True)
    robots.clear_cache()
    yield
    robots.clear_cache()


def _serve(monkeypatch, robots_body: str | None, *, robots_status: int = 200):
    """Point robots.py at a MockTransport serving `robots_body`.

    Returns a list that records every path requested, so a test can assert
    robots.txt was read once and no more.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            if robots_body is None:
                raise httpx.ConnectError("robots.txt unreachable")
            return httpx.Response(robots_status, text=robots_body)
        return httpx.Response(200, text="<html><body>page</body></html>")

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_with_transport(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(robots.httpx, "Client", client_with_transport)
    return seen


def test_disallowed_path_is_refused(monkeypatch):
    _serve(monkeypatch, DISALLOW_PRIVATE)
    reason = robots.robots_disallows(
        "https://portal.example/private/x", fetch.DEFAULT_USER_AGENT
    )
    assert reason == "robots_disallowed:portal.example"


def test_allowed_path_passes(monkeypatch):
    _serve(monkeypatch, DISALLOW_PRIVATE)
    assert (
        robots.robots_disallows(
            "https://portal.example/datasets", fetch.DEFAULT_USER_AGENT
        )
        is None
    )


def test_missing_robots_fails_open(monkeypatch):
    _serve(monkeypatch, "not found", robots_status=404)
    assert (
        robots.robots_disallows(
            "https://portal.example/anything", fetch.DEFAULT_USER_AGENT
        )
        is None
    )


def test_unreachable_robots_fails_open(monkeypatch):
    _serve(monkeypatch, None)
    assert (
        robots.robots_disallows(
            "https://portal.example/anything", fetch.DEFAULT_USER_AGENT
        )
        is None
    )


def test_non_http_url_is_allowed(monkeypatch):
    _serve(monkeypatch, DISALLOW_ALL)
    assert robots.robots_disallows("ftp://portal.example/x", "ua") is None


def test_robots_is_read_once_per_origin(monkeypatch):
    seen = _serve(monkeypatch, DISALLOW_PRIVATE)
    for path in ("/a", "/b", "/c"):
        robots.robots_disallows(
            f"https://portal.example{path}", fetch.DEFAULT_USER_AGENT
        )
    assert seen.count("/robots.txt") == 1


def test_crawl_delay_is_read(monkeypatch):
    _serve(monkeypatch, "User-agent: *\nCrawl-delay: 2\nDisallow:\n")
    delay = robots.crawl_delay_s(
        "https://portal.example/x", fetch.DEFAULT_USER_AGENT
    )
    assert delay == 2.0


def test_crawl_delay_absent_is_none(monkeypatch):
    _serve(monkeypatch, ALLOW_ALL)
    assert (
        robots.crawl_delay_s("https://portal.example/x", fetch.DEFAULT_USER_AGENT)
        is None
    )


def test_fetch_text_refuses_before_requesting_the_page(monkeypatch):
    """The refusal must happen before the page request, not after."""
    seen = _serve(monkeypatch, DISALLOW_ALL)
    result = fetch.fetch_text("https://portal.example/datasets")
    assert result.failure_mode == "robots_disallowed:portal.example"
    assert result.status_code == 0
    assert result.content == ""
    assert "/datasets" not in seen


def test_head_ok_refuses_disallowed_url(monkeypatch):
    _serve(monkeypatch, DISALLOW_ALL)
    assert fetch.head_ok("https://portal.example/datasets") == (False, 0)


def test_robots_refusal_is_distinct_from_leakage_refusal(monkeypatch):
    """The two guards answer different questions and must not blur in the
    logs: one is the portal's instruction, the other is our own deny-list."""
    _serve(monkeypatch, DISALLOW_ALL)
    robots_refusal = fetch.fetch_text("https://portal.example/x")
    leakage_refusal = fetch.fetch_text("https://data.europa.eu/x")
    assert robots_refusal.failure_mode.startswith("robots_disallowed:")
    assert leakage_refusal.failure_mode.startswith("blocked_data_leakage:")
