"""Wall-clock deadline on the Serper SERP call.

httpx's timeout does not cover OS-level DNS resolution (getaddrinfo runs
before the socket connect timeout applies), so after a sleep/wake or network
handover the POST can hang indefinitely. Observed 2026-07-10..12: ~26 pairs
stuck at the researcher's `search_start` substage with no error trail. The
guard runs the request in a worker thread and raises SerperDeadlineError once
the wall-clock budget is spent, so the pair fails visibly instead of hanging.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from agents.tools.search_serper import (
    SERPER_WALL_CLOCK_DEADLINE_S,
    SerperDeadlineError,
    serper_search,
)


def _hanging_client(release: threading.Event) -> MagicMock:
    """A mock httpx.Client whose post() blocks until `release` is set."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)

    def _blocked_post(*args, **kwargs):
        release.wait(timeout=30.0)
        raise AssertionError("post returned; deadline should have fired first")

    client.post = MagicMock(side_effect=_blocked_post)
    return client


def test_hanging_post_raises_deadline_error(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    release = threading.Event()
    try:
        with patch(
            "agents.tools.search_serper.httpx.Client",
            return_value=_hanging_client(release),
        ), patch(
            "agents.tools.search_serper.SERPER_WALL_CLOCK_DEADLINE_S", 0.2
        ):
            started = time.monotonic()
            with pytest.raises(SerperDeadlineError):
                serper_search("open data portal Malta")
            elapsed = time.monotonic() - started
            assert elapsed < 5.0, "deadline did not cut the hang short"
    finally:
        release.set()  # unblock the abandoned worker thread


def test_normal_response_unaffected(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "organic": [
            {
                "title": "Result 1",
                "link": "https://example.com/1",
                "snippet": "snippet",
                "position": 1,
            }
        ]
    }
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(return_value=resp)

    with patch("agents.tools.search_serper.httpx.Client", return_value=client):
        out = serper_search("open data portal Malta")
    assert len(out) == 1
    assert out[0].url == "https://example.com/1"


def test_deadline_exceeds_httpx_timeout():
    # The wall-clock guard is a backstop for hangs the 20s client timeout
    # cannot see; it must never fire before the client timeout would.
    assert SERPER_WALL_CLOCK_DEADLINE_S > 20.0
