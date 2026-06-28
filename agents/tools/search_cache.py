"""Three-layer SQLite-backed cache for the DIY-Tavily pipeline.

Layers
------
1. SERP cache      -- deduplicates outbound search-engine calls.
2. Fetch cache     -- deduplicates page fetches.
3. Snippet cache   -- deduplicates Claude snippet-picker calls.

All three layers share a 30-day TTL.  Expired rows are *not* deleted on
read; they remain as an audit trail and are simply treated as misses.

Schema is created lazily on first use via ``ensure_tables()``.  This
avoids coupling to ``scripts/setup_sqlite.py``, which is managed
separately.  It is safe to call ``ensure_tables()`` repeatedly; a
module-level flag prevents redundant CREATE statements within a process.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse, urlunparse

from agents.tools.search import SearchResult
from agents.tools.snippet_picker import PickedChunk

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DB_PATH: Path = Path(__file__).resolve().parents[2] / "data" / "odmi.db"

TTL_DAYS: int = 30

_TABLES_ENSURED: bool = False

# Cold-cache toggle (EXP-2). When True, every read function (serp_get,
# fetch_get, snippet_get) short-circuits to a miss, so the DIY pipeline
# recomputes each SERP, fetch, and snippet-pick live. Writes are unaffected,
# so the cache still fills as an audit record; only reads are bypassed.
# This makes search cost comparable across experiment conditions that run
# one after another: a later condition cannot read a hit a previous one
# wrote, so it pays its own full cold cost. Process-scoped (dispatch spawns
# one subprocess per pair), set via set_read_disabled() from the
# --no-cache flag. Default False keeps normal behaviour unchanged.
_READ_DISABLED: bool = False

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS search_cache_serp (
  cache_key   TEXT PRIMARY KEY,
  query       TEXT NOT NULL,
  max_results INTEGER NOT NULL,
  payload     TEXT NOT NULL,
  fetched_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_serp_fetched_at
  ON search_cache_serp (fetched_at);

CREATE TABLE IF NOT EXISTS search_cache_fetch (
  url         TEXT PRIMARY KEY,
  content     TEXT NOT NULL,
  fetched_at  TEXT NOT NULL,
  status_code INTEGER NOT NULL,
  backend     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fetch_fetched_at
  ON search_cache_fetch (fetched_at);

CREATE TABLE IF NOT EXISTS search_cache_snippet (
  cache_key       TEXT PRIMARY KEY,
  query           TEXT NOT NULL,
  page_text_hash  TEXT NOT NULL,
  chunks_json     TEXT NOT NULL,
  picked_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snippet_picked_at
  ON search_cache_snippet (picked_at);
"""

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_within_ttl(ts: str) -> bool:
    """Return True if the ISO-8601 UTC timestamp is within TTL_DAYS of now."""
    stored = datetime.fromisoformat(ts)
    # Ensure timezone-aware comparison
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stored) <= timedelta(days=TTL_DAYS)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), timeout=5.0)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _serp_key(query: str, max_results: int, include_domains: Optional[List[str]]) -> str:
    domains_part = ",".join(sorted(include_domains or []))
    raw = f"{query}|{max_results}|{domains_part}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _snippet_key(
    query: str,
    page_text: str,
    picker_model: Optional[str] = None,
) -> str:
    # picker_model is part of the key because a different model picks
    # different chunks from the same page. Production calls pass None
    # (the picker runs on DEFAULT_MODEL), so old rows written before
    # this argument existed still hit on the None branch. Experiments
    # that pin a specific picker model write under a distinct key.
    page_hash = hashlib.sha256(page_text.encode()).hexdigest()
    model_part = picker_model or ""
    raw = f"{query}|{page_hash}|{model_part}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _normalise_url(url: str) -> str:
    """Lowercase scheme + host, strip trailing slash from path."""
    parsed = urlparse(url)
    normalised = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=parsed.path.rstrip("/"),
    )
    return urlunparse(normalised)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def set_read_disabled(value: bool) -> None:
    """Enable or disable cache reads process-wide (cold-cache mode, EXP-2).

    When disabled, serp_get / fetch_get / snippet_get always return a miss
    so the DIY pipeline recomputes everything live. Writes keep working.
    """
    global _READ_DISABLED
    _READ_DISABLED = bool(value)


def ensure_tables() -> None:
    """Idempotently create the three cache tables if they don't exist.

    Safe to call repeatedly. Every cache function calls this automatically
    on first use, so callers don't need to invoke it explicitly.
    """
    global _TABLES_ENSURED
    if _TABLES_ENSURED:
        return
    conn = _connect()
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()
    _TABLES_ENSURED = True


# ---- SERP layer ------------------------------------------------------------


def serp_get(
    query: str,
    max_results: int,
    include_domains: Optional[List[str]],
) -> Optional[List[SearchResult]]:
    """Return cached SERP results if present and within TTL, else None."""
    if _READ_DISABLED:
        return None
    ensure_tables()
    key = _serp_key(query, max_results, include_domains)
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT payload, fetched_at FROM search_cache_serp WHERE cache_key = ?",
            (key,),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    payload, fetched_at = row
    if not _is_within_ttl(fetched_at):
        return None
    return [SearchResult(**d) for d in json.loads(payload)]


def serp_put(
    query: str,
    max_results: int,
    include_domains: Optional[List[str]],
    results: List[SearchResult],
) -> None:
    """Store SERP results."""
    ensure_tables()
    key = _serp_key(query, max_results, include_domains)
    payload = json.dumps([r.model_dump() for r in results])
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO search_cache_serp (cache_key, query, max_results, payload, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
              payload    = excluded.payload,
              fetched_at = excluded.fetched_at
            """,
            (key, query, max_results, payload, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


# ---- Fetch layer ------------------------------------------------------------


def fetch_get(url: str) -> Optional[str]:
    """Return cached cleaned text for URL if present and within TTL, else None."""
    if _READ_DISABLED:
        return None
    ensure_tables()
    norm = _normalise_url(url)
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT content, fetched_at FROM search_cache_fetch WHERE url = ?",
            (norm,),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    content, fetched_at = row
    if not _is_within_ttl(fetched_at):
        return None
    return content


def fetch_put(
    url: str,
    content: str,
    *,
    status_code: int,
    backend: str,
) -> None:
    """Store fetched cleaned text. backend is "httpx" or "playwright"."""
    ensure_tables()
    norm = _normalise_url(url)
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO search_cache_fetch (url, content, fetched_at, status_code, backend)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
              content     = excluded.content,
              fetched_at  = excluded.fetched_at,
              status_code = excluded.status_code,
              backend     = excluded.backend
            """,
            (norm, content, _now_iso(), status_code, backend),
        )
        conn.commit()
    finally:
        conn.close()


# ---- Snippet layer ----------------------------------------------------------


def snippet_get(
    query: str,
    page_text: str,
    picker_model: Optional[str] = None,
) -> Optional[List[PickedChunk]]:
    """Return cached PickedChunks if present and within TTL, else None.

    ``picker_model`` is part of the cache key because a different model
    picks different chunks from the same page text. Defaults to None so
    production (picker on DEFAULT_MODEL) still hits the rows written
    before this argument existed.
    """
    if _READ_DISABLED:
        return None
    ensure_tables()
    key = _snippet_key(query, page_text, picker_model)
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT chunks_json, picked_at FROM search_cache_snippet WHERE cache_key = ?",
            (key,),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    chunks_json, picked_at = row
    if not _is_within_ttl(picked_at):
        return None
    return [PickedChunk(**d) for d in json.loads(chunks_json)]


def snippet_put(
    query: str,
    page_text: str,
    chunks: List[PickedChunk],
    picker_model: Optional[str] = None,
) -> None:
    """Store picked chunks. ``picker_model`` is part of the cache key."""
    ensure_tables()
    key = _snippet_key(query, page_text, picker_model)
    page_text_hash = hashlib.sha256(page_text.encode()).hexdigest()
    chunks_json = json.dumps([c.model_dump() for c in chunks])
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO search_cache_snippet
              (cache_key, query, page_text_hash, chunks_json, picked_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
              chunks_json = excluded.chunks_json,
              picked_at   = excluded.picked_at
            """,
            (key, query, page_text_hash, chunks_json, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
