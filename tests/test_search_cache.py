"""Tests for agents/tools/search_cache.py.

Each test redirects the module's _DB_PATH to a temp file so that
data/odmi.db is never touched.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import pytest

import agents.tools.search_cache as sc
from agents.tools.search import SearchResult
from agents.tools.snippet_picker import PickedChunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_results(n: int = 2) -> List[SearchResult]:
    return [
        SearchResult(
            title=f"Title {i}",
            url=f"https://example.com/{i}",
            snippet=f"Snippet {i}",
            score=0.9 - i * 0.1,
            provider="tavily",
        )
        for i in range(n)
    ]


def _make_chunks(n: int = 2) -> List[PickedChunk]:
    return [PickedChunk(text=f"chunk {i}", score=0.8 - i * 0.1) for i in range(n)]


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the cache module at a throwaway DB and reset module state."""
    monkeypatch.setattr(sc, "_DB_PATH", tmp_path / "test_cache.db")
    monkeypatch.setattr(sc, "_TABLES_ENSURED", False)
    # Reset the cold-cache toggle so a prior test cannot leak a disabled-read
    # state into these read/write assertions.
    monkeypatch.setattr(sc, "_READ_DISABLED", False)


# ---------------------------------------------------------------------------
# ensure_tables
# ---------------------------------------------------------------------------

class TestEnsureTables:
    def test_creates_all_three_tables(self) -> None:
        sc.ensure_tables()
        conn = sqlite3.connect(sc._DB_PATH)
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn.close()
        assert "search_cache_serp" in names
        assert "search_cache_fetch" in names
        assert "search_cache_snippet" in names

    def test_idempotent(self) -> None:
        sc.ensure_tables()
        sc.ensure_tables()  # must not raise

    def test_flag_set_after_first_call(self) -> None:
        assert sc._TABLES_ENSURED is False
        sc.ensure_tables()
        assert sc._TABLES_ENSURED is True


# ---------------------------------------------------------------------------
# SERP cache
# ---------------------------------------------------------------------------

class TestSerpCache:
    def test_miss_on_empty(self) -> None:
        assert sc.serp_get("odmi policy", 5, None) is None

    def test_put_then_get(self) -> None:
        results = _make_results(3)
        sc.serp_put("odmi policy", 5, None, results)
        hit = sc.serp_get("odmi policy", 5, None)
        assert hit is not None
        assert len(hit) == 3
        assert hit[0].title == "Title 0"
        assert hit[0].url == "https://example.com/0"
        assert hit[0].snippet == "Snippet 0"
        assert hit[0].score == pytest.approx(0.9)

    def test_different_include_domains_different_keys(self) -> None:
        results = _make_results()
        sc.serp_put("odmi policy", 5, ["gov.uk"], results)
        assert sc.serp_get("odmi policy", 5, ["ec.europa.eu"]) is None

    def test_include_domains_order_insensitive(self) -> None:
        results = _make_results()
        sc.serp_put("odmi policy", 5, ["b.com", "a.com"], results)
        hit = sc.serp_get("odmi policy", 5, ["a.com", "b.com"])
        assert hit is not None

    def test_none_and_empty_list_same_key(self) -> None:
        results = _make_results()
        sc.serp_put("odmi policy", 5, None, results)
        hit = sc.serp_get("odmi policy", 5, [])
        assert hit is not None

    def test_different_max_results_different_keys(self) -> None:
        results = _make_results()
        sc.serp_put("odmi policy", 5, None, results)
        assert sc.serp_get("odmi policy", 10, None) is None

    def test_ttl_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        results = _make_results()
        sc.serp_put("odmi policy", 5, None, results)

        # Backdate the stored timestamp by 31 days
        conn = sqlite3.connect(sc._DB_PATH)
        old_ts = (
            datetime.now(timezone.utc) - timedelta(days=31)
        ).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE search_cache_serp SET fetched_at = ?",
            (old_ts,),
        )
        conn.commit()
        conn.close()

        assert sc.serp_get("odmi policy", 5, None) is None

    def test_provider_field_preserved(self) -> None:
        results = [
            SearchResult(title="T", url="https://x.com", snippet="S",
                         score=0.5, provider="brave")
        ]
        sc.serp_put("query", 5, None, results)
        hit = sc.serp_get("query", 5, None)
        assert hit is not None
        assert hit[0].provider == "brave"


# ---------------------------------------------------------------------------
# Fetch cache
# ---------------------------------------------------------------------------

class TestFetchCache:
    def test_miss_on_empty(self) -> None:
        assert sc.fetch_get("https://example.com/page") is None

    def test_put_then_get(self) -> None:
        sc.fetch_put(
            "https://example.com/page",
            "cleaned page text",
            status_code=200,
            backend="httpx",
        )
        hit = sc.fetch_get("https://example.com/page")
        assert hit == "cleaned page text"

    def test_url_normalisation_trailing_slash(self) -> None:
        sc.fetch_put(
            "https://example.com/path/",
            "content",
            status_code=200,
            backend="httpx",
        )
        assert sc.fetch_get("https://example.com/path") == "content"

    def test_url_normalisation_scheme_host_case(self) -> None:
        sc.fetch_put(
            "HTTPS://A.COM/path/",
            "case content",
            status_code=200,
            backend="playwright",
        )
        assert sc.fetch_get("https://a.com/path") == "case content"

    def test_ttl_expiry(self) -> None:
        sc.fetch_put(
            "https://example.com/old",
            "stale",
            status_code=200,
            backend="httpx",
        )
        old_ts = (
            datetime.now(timezone.utc) - timedelta(days=31)
        ).isoformat(timespec="seconds")
        conn = sqlite3.connect(sc._DB_PATH)
        conn.execute(
            "UPDATE search_cache_fetch SET fetched_at = ?",
            (old_ts,),
        )
        conn.commit()
        conn.close()

        assert sc.fetch_get("https://example.com/old") is None

    def test_missing_url_returns_none(self) -> None:
        assert sc.fetch_get("https://not-stored.example.com") is None


# ---------------------------------------------------------------------------
# Snippet cache
# ---------------------------------------------------------------------------

class TestSnippetCache:
    def test_miss_on_empty(self) -> None:
        assert sc.snippet_get("odmi policy", "some page text") is None

    def test_put_then_get(self) -> None:
        chunks = _make_chunks(2)
        sc.snippet_put("odmi policy", "some page text", chunks)
        hit = sc.snippet_get("odmi policy", "some page text")
        assert hit is not None
        assert len(hit) == 2
        assert hit[0].text == "chunk 0"
        assert hit[0].score == pytest.approx(0.8)

    def test_different_page_text_different_key(self) -> None:
        chunks = _make_chunks()
        sc.snippet_put("odmi policy", "page A", chunks)
        assert sc.snippet_get("odmi policy", "page B") is None

    def test_different_query_different_key(self) -> None:
        chunks = _make_chunks()
        sc.snippet_put("query A", "page text", chunks)
        assert sc.snippet_get("query B", "page text") is None

    def test_ttl_expiry(self) -> None:
        chunks = _make_chunks()
        sc.snippet_put("odmi policy", "page text", chunks)
        old_ts = (
            datetime.now(timezone.utc) - timedelta(days=31)
        ).isoformat(timespec="seconds")
        conn = sqlite3.connect(sc._DB_PATH)
        conn.execute(
            "UPDATE search_cache_snippet SET picked_at = ?",
            (old_ts,),
        )
        conn.commit()
        conn.close()

        assert sc.snippet_get("odmi policy", "page text") is None

    def test_empty_chunks_roundtrip(self) -> None:
        sc.snippet_put("query", "page", [])
        hit = sc.snippet_get("query", "page")
        assert hit == []

    def test_different_picker_model_different_key(self) -> None:
        # A row written by one picker model must not be served to another.
        # This is the core invariant for the picker_model knob.
        chunks_opus = _make_chunks(2)
        sc.snippet_put("q", "page", chunks_opus, picker_model="claude-opus-4-6")
        # Sonnet must miss the Opus row.
        assert sc.snippet_get("q", "page", picker_model="claude-sonnet-4-6") is None
        # The default (production) None must also miss the Opus row.
        assert sc.snippet_get("q", "page") is None
        # Opus still hits its own row.
        hit = sc.snippet_get("q", "page", picker_model="claude-opus-4-6")
        assert hit is not None
        assert len(hit) == 2

    def test_picker_model_none_vs_named_distinct_keys(self) -> None:
        # _snippet_key must produce distinct hashes for None and a named
        # model on the same (query, page_text). This pins the migration
        # behaviour: production (None) keeps its own namespace, and any
        # experiment that overrides picker_model writes a fresh row.
        k_none = sc._snippet_key("q", "page")
        k_opus = sc._snippet_key("q", "page", picker_model="claude-opus-4-6")
        k_sonnet = sc._snippet_key("q", "page", picker_model="claude-sonnet-4-6")
        assert k_none != k_opus
        assert k_none != k_sonnet
        assert k_opus != k_sonnet

    def test_default_get_hits_default_put(self) -> None:
        # Production reads (picker_model=None) must keep hitting production
        # writes (picker_model=None). This guards against the migration
        # accidentally making None its own special key.
        chunks = _make_chunks(2)
        sc.snippet_put("q", "page", chunks)
        hit = sc.snippet_get("q", "page")
        assert hit is not None
        assert len(hit) == 2
