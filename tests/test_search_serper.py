"""Tests for the Serper.dev Google-SERP wrapper.

Covers:
- Happy path: mocked response → SearchResult list with correct provider and scores.
- Score arithmetic: rank 1 → 1.0, rank 2 → 0.5, rank 3 → 0.333.
- Include-domains capped at 8: 12 domains passed → only 8 appear as site: clauses.
- Include-domains absent: query body contains the query verbatim, no site: clauses.
- Missing SERPER_API_KEY: raises RuntimeError mentioning the env var.
- Empty organic array: returns an empty list.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agents.tools.search_serper import serper_search


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_organic(*positions: int) -> list[dict]:
    """Build a minimal organic results list with the given positions."""
    return [
        {
            "title": f"Result {pos}",
            "link": f"https://example.com/result-{pos}",
            "snippet": f"Snippet for position {pos}",
            "position": pos,
        }
        for pos in positions
    ]


def _mock_response(payload: dict, status_code: int = 200) -> MagicMock:
    """Return a mock httpx response that returns `payload` as JSON."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def _make_client_mock(payload: dict) -> MagicMock:
    """Return a mock httpx.Client context manager that captures the POST call."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(return_value=_mock_response(payload))
    return client


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_happy_path_returns_search_results(monkeypatch):
    """Mocked Serper response produces a list of SearchResult with provider='serper'."""
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    payload = {"organic": _make_organic(1, 2, 3)}
    client_mock = _make_client_mock(payload)

    with patch("agents.tools.search_serper.httpx.Client", return_value=client_mock):
        results = serper_search("open data maturity france", max_results=3)

    assert len(results) == 3
    assert all(r.provider == "serper" for r in results)
    assert all(r.url.startswith("https://") for r in results)
    assert all(r.title for r in results)
    assert all(r.snippet for r in results)


# ---------------------------------------------------------------------------
# Score arithmetic
# ---------------------------------------------------------------------------

def test_score_rank_1_is_1_0(monkeypatch):
    """Rank 1 result must have score 1.0."""
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    payload = {"organic": _make_organic(1)}
    client_mock = _make_client_mock(payload)

    with patch("agents.tools.search_serper.httpx.Client", return_value=client_mock):
        results = serper_search("q", max_results=5)

    assert results[0].score == 1.0


def test_score_rank_2_is_0_5(monkeypatch):
    """Rank 2 result must have score 0.5 (= 1/2)."""
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    payload = {"organic": _make_organic(1, 2)}
    client_mock = _make_client_mock(payload)

    with patch("agents.tools.search_serper.httpx.Client", return_value=client_mock):
        results = serper_search("q", max_results=5)

    assert results[1].score == 0.5


def test_score_rank_3_is_0_333(monkeypatch):
    """Rank 3 result must have score 0.333 (= round(1/3, 3))."""
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    payload = {"organic": _make_organic(1, 2, 3)}
    client_mock = _make_client_mock(payload)

    with patch("agents.tools.search_serper.httpx.Client", return_value=client_mock):
        results = serper_search("q", max_results=5)

    assert results[2].score == pytest.approx(0.333, abs=0.001)


# ---------------------------------------------------------------------------
# include_domains capped at 8
# ---------------------------------------------------------------------------

def test_include_domains_capped_at_8(monkeypatch):
    """Passing 12 domains must result in only 8 site: clauses in the query body."""
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    payload = {"organic": []}
    client_mock = _make_client_mock(payload)

    domains = [f"domain{i}.example.com" for i in range(12)]

    with patch("agents.tools.search_serper.httpx.Client", return_value=client_mock):
        serper_search("open data", include_domains=domains)

    call_kwargs = client_mock.post.call_args
    body: dict = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json") or call_kwargs[0][1]
    q: str = body["q"]

    site_clause_count = q.count("site:")
    assert site_clause_count == 8, (
        f"Expected 8 site: clauses but got {site_clause_count}. Query was: {q!r}"
    )
    # First 8 domains must be present; the last 4 must not.
    for d in domains[:8]:
        assert f"site:{d}" in q
    for d in domains[8:]:
        assert f"site:{d}" not in q


# ---------------------------------------------------------------------------
# include_domains absent
# ---------------------------------------------------------------------------

def test_no_include_domains_query_verbatim(monkeypatch):
    """When include_domains is not passed, the query body contains the query verbatim."""
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    payload = {"organic": []}
    client_mock = _make_client_mock(payload)

    raw_query = "what is open data maturity"

    with patch("agents.tools.search_serper.httpx.Client", return_value=client_mock):
        serper_search(raw_query)

    call_kwargs = client_mock.post.call_args
    body: dict = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json") or call_kwargs[0][1]
    q: str = body["q"]

    assert q == raw_query, f"Expected verbatim query {raw_query!r}, got {q!r}"
    assert "site:" not in q


# ---------------------------------------------------------------------------
# Missing SERPER_API_KEY
# ---------------------------------------------------------------------------

def test_missing_api_key_raises_runtime_error(monkeypatch):
    """If SERPER_API_KEY is not set, serper_search must raise RuntimeError."""
    monkeypatch.delenv("SERPER_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SERPER_API_KEY"):
        serper_search("some query")


# ---------------------------------------------------------------------------
# Empty organic array
# ---------------------------------------------------------------------------

def test_empty_organic_returns_empty_list(monkeypatch):
    """An empty organic array must return an empty list, not raise."""
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    payload = {"organic": []}
    client_mock = _make_client_mock(payload)

    with patch("agents.tools.search_serper.httpx.Client", return_value=client_mock):
        results = serper_search("q")

    assert results == []


# ---------------------------------------------------------------------------
# max_results is respected
# ---------------------------------------------------------------------------

def test_max_results_respected(monkeypatch):
    """serper_search must return at most max_results items."""
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    # API returns 10 results but we only want 3.
    payload = {"organic": _make_organic(*range(1, 11))}
    client_mock = _make_client_mock(payload)

    with patch("agents.tools.search_serper.httpx.Client", return_value=client_mock):
        results = serper_search("q", max_results=3)

    assert len(results) == 3


# ---------------------------------------------------------------------------
# num in body is capped at 20
# ---------------------------------------------------------------------------

def test_num_body_capped_at_20(monkeypatch):
    """The `num` field in the POST body must never exceed 20."""
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    payload = {"organic": []}
    client_mock = _make_client_mock(payload)

    with patch("agents.tools.search_serper.httpx.Client", return_value=client_mock):
        serper_search("q", max_results=100)

    call_kwargs = client_mock.post.call_args
    body: dict = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json") or call_kwargs[0][1]
    assert body["num"] <= 20
