# DIY-Tavily Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single DIY replication of Tavily's search-snippet pipeline (Serper SERP + parallel Playwright fetch + trafilatura extraction + Claude snippet-picker) and A/B-test it against commercial Tavily, Brave, and raw Serper on 400 stratified ODMI pairs. The headline finding either justifies a primary-provider switch (saves £200+ per full 5,148-pair pass) or quantifies what commercial RAG-tuned snippet selection is actually worth.

**Architecture:** A new module `agents/tools/search_diy.py` composes the four-stage pipeline and exposes the existing `SearchResult` shape. `search()` in `search.py` gains a `provider` parameter that dispatches between Tavily, Brave, raw Serper, and DIY. Three SQLite cache tables (SERP, fetch, snippet) sit underneath so re-runs of the same (query, country) cost nothing. An A/B runner pins a stratified 400-pair sample and varies provider while holding everything else fixed.

**Tech Stack:** Python 3.11, `uv`-managed. New runtime deps: `trafilatura`. Existing: `httpx`, `playwright`, `pydantic`, `anthropic` SDK via CLIProxyAPI (`localhost:8317`), SQLite (`data/odmi.db`).

---

## Locked Design Decisions

### Snippet-picker prompt (final, version 1)

```
SYSTEM:
You are a passage selector for a search pipeline.

You will be given:
- A search query (the information need)
- The cleaned text of one webpage that the search engine returned for that query

Your job: extract up to three passages from the page (each up to 500 characters)
that best answer the query, copied exactly as written. Score each passage
between 0.0 and 1.0 for how directly it answers the query.

Rules:
1. Quote literally. Copy each passage character-for-character from the page
   text. Do not summarise, paraphrase, or stitch separated sentences.
2. Each passage is one contiguous run of consecutive sentences, not fragments
   from different parts of the page.
3. Rank passages by score, highest first. Return only passages that are
   actually relevant; do not pad.
4. If the page contains no passage that addresses the query, return an empty
   list. Do not force a match.
5. Ignore boilerplate: cookie banners, navigation menus, footers, repeated
   legal text, breadcrumbs. These are not valid passages even on keyword match.
6. Score reflects how directly the passage answers the query:
   - 0.8-1.0: passage answers directly with specific facts, dates, or figures
   - 0.5-0.7: passage is on-topic and partially answers
   - 0.2-0.4: passage is tangentially related
   - 0.0-0.1: nothing relevant (omit from the list)
7. The page may be in any language. Pick the best passages in their original
   language; do not translate.

Output schema:
{ "chunks": [ { "text": str (<= 500 chars), "score": float in [0.0, 1.0] }, ... ] }

USER:
Search query: {query}

Page URL: {url}
Page text (cleaned, up to 8000 chars):
{page_text}
```

### Numeric parameters

| Parameter | Value | Reason |
|---|---|---|
| Page text cap (chars) before picker | 8,000 | ~2k tokens; covers the bulk of relevant passages on EU policy pages without runaway cost |
| Snippet length cap | 500 chars | Matches Tavily advanced (`chunks_per_source` × 500) for like-for-like comparison |
| Max chunks per URL | 3 | Matches Tavily advanced default |
| Top-chunk-only threshold | 0.7 | If chunk[0].score ≥ 0.7, return only that chunk; else return the full list up to 3 |
| Multi-chunk separator | `" ... "` | Joins chunks into the single `SearchResult.snippet` string for drop-in compat |
| `SearchResult.score` | chunk[0].score | The top chunk's score becomes the result-level score |
| Drop URL when | chunks empty | A page with no relevant passage is dropped from the result list entirely |

### A/B design

- **Four conditions:** `tavily`, `brave`, `serper_raw`, `diy`.
- **Trusted-domains routing preserved.** All four conditions run the existing narrow-trusted-then-wide chain. The A/B measures end-to-end swarm match rate, which is what the dissertation defends.
- **20-pair shakedown** before the full 400-pair run. Catches pipeline bugs cheaply.
- **400-pair main A/B**, stratified by `dimension × country-group` (~25 per cell). Same `(question, country)` pairs through every condition; query generation seeded so it produces the same queries across runs.
- **One `experiments` row per condition.** Existing `experiment_id` plumbing (D27) carries through.

### Caching

Three new tables in `data/odmi.db`. 30-day TTL across the board.

| Table | Key | Value | Why |
|---|---|---|---|
| `search_cache_serp` | hash(query, max_results, sorted include_domains) | JSON: top URLs + positions + raw snippets | SERP results are stable for days; querying Serper for the same string twice is wasteful |
| `search_cache_fetch` | normalised URL | cleaned text + fetched_at | Saves Playwright launches; pages don't change minute-to-minute |
| `search_cache_snippet` | hash(query, sha256(page_text)) | chunks JSON | Skips Claude pick on identical query+page across re-runs |

---

## File Structure

**New files:**
- `agents/tools/search_diy.py` — DIY pipeline (Serper → fetch → extract → pick)
- `agents/tools/search_serper.py` — Serper API wrapper, raw provider behaviour
- `agents/tools/snippet_picker.py` — Claude snippet-pick wrapper
- `agents/prompts/snippet_picker.py` — Versioned prompt module
- `agents/tools/search_cache.py` — SQLite-backed three-layer cache
- `agents/tools/extract.py` — Thin trafilatura wrapper with PDF passthrough
- `evaluation/search_ab.py` — A/B runner script
- `evaluation/search_ab_report.py` — Aggregator: per-provider match rate, coverage, latency, £
- `tests/test_search_serper.py`
- `tests/test_snippet_picker.py`
- `tests/test_search_diy.py`
- `tests/test_search_cache.py`
- `tests/test_extract.py`

**Modified files:**
- `agents/tools/search.py` — add `provider` parameter, dispatch chain (preserve existing tavily→brave fallback as `provider="auto"`)
- `agents/researcher.py` — pass an experiment-aware provider through the call (one-line change)
- `scripts/setup_sqlite.py` — three new cache tables
- `pyproject.toml` — add `trafilatura>=1.6`
- `.env.example` — add `SERPER_API_KEY` placeholder
- `docs/SPEC.md` — D29 entry (D28 taken by answer-shape decision landed 2026-05-26)

---

## Tasks

### Task 0: Pre-June stub — provider param on search()

Done in May so the heavier June work starts on a clean refactor.

**Files:**
- Modify: `agents/tools/search.py` — add `provider: Literal["auto","tavily","brave"] = "auto"` to `search()` and `search_many()`
- Test: `tests/test_search_provider_arg.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_search_provider_arg.py
import pytest
from unittest.mock import patch
from agents.tools.search import search

def test_provider_auto_keeps_existing_chain(monkeypatch):
    """provider='auto' (default) must preserve tavily-first-then-brave behaviour."""
    calls = []
    def fake_tavily(query, **kw):
        calls.append("tavily")
        return [{"title":"t","url":"https://x","content":"c","score":0.5}]
    monkeypatch.setattr("agents.tools.search._tavily_search",
                        lambda q, **k: [__import__("agents.tools.search").tools.search.SearchResult(
                            title="t", url="https://x", snippet="c", score=0.5, provider="tavily")])
    out = search("test", provider="auto")
    assert all(r.provider == "tavily" for r in out)

def test_provider_brave_skips_tavily(monkeypatch):
    """provider='brave' must NOT call Tavily."""
    monkeypatch.setattr("agents.tools.search._tavily_search",
                        lambda q, **k: pytest.fail("tavily should not be called when provider=brave"))
    from agents.tools.search import SearchResult
    monkeypatch.setattr("agents.tools.search._brave_search",
                        lambda q, **k: [SearchResult(title="b", url="https://y", snippet="s", score=None, provider="brave")])
    out = search("test", provider="brave")
    assert all(r.provider == "brave" for r in out)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_search_provider_arg.py -v
# Expected: FAIL — search() does not accept `provider` kwarg
```

- [ ] **Step 3: Add the provider param**

Modify `agents/tools/search.py`:

```python
from typing import Literal
Provider = Literal["auto", "tavily", "brave"]

def search(
    query: str,
    *,
    max_results: int = 5,
    topic: str = "general",
    include_domains: Optional[List[str]] = None,
    on_call: Optional[CallObserver] = None,
    provider: Provider = "auto",
) -> List[SearchResult]:
    if provider == "tavily":
        return _scrub_blocked(_tavily_search(
            query, max_results=max_results, topic=topic, include_domains=include_domains
        ))
    if provider == "brave":
        return _scrub_blocked(_brave_search(
            query, max_results=max_results, include_domains=include_domains
        ))
    # provider == "auto" — existing chain
    # ... existing body unchanged ...
```

Mirror the kwarg on `search_many()`, plumbing it down to `search()`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_search_provider_arg.py -v
uv run pytest tests/ -k "search" -v
# Expected: PASS for new tests; no regressions on existing search tests
```

- [ ] **Step 5: Commit**

```bash
git add agents/tools/search.py tests/test_search_provider_arg.py
git commit -m "Add provider param to search() for DIY-Tavily A/B groundwork"
git push origin main
```

---

### Task 1: Add trafilatura dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `.env.example`

- [ ] **Step 1: Add `trafilatura>=1.6` to `pyproject.toml` dependencies**
- [ ] **Step 2: Add `SERPER_API_KEY=` to `.env.example`**
- [ ] **Step 3: Run `uv sync` and verify install**

```bash
uv sync
uv run python -c "import trafilatura; print(trafilatura.__version__)"
# Expected: prints version (>=1.6)
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock .env.example
git commit -m "Add trafilatura runtime dep for DIY-Tavily extraction"
git push origin main
```

---

### Task 2: Serper API wrapper (`search_serper.py`)

**Files:**
- Create: `agents/tools/search_serper.py`
- Test: `tests/test_search_serper.py`

- [ ] **Step 1: Write the failing test (mocked HTTP)**

```python
# tests/test_search_serper.py
from unittest.mock import MagicMock, patch
import pytest
from agents.tools.search_serper import serper_search

SAMPLE_RESPONSE = {
    "organic": [
        {"title": "Title A", "link": "https://a.example", "snippet": "Snippet A",
         "position": 1, "date": "2024-01-01"},
        {"title": "Title B", "link": "https://b.example", "snippet": "Snippet B",
         "position": 2},
    ]
}

def test_serper_returns_searchresults(monkeypatch):
    fake_resp = MagicMock(status_code=200)
    fake_resp.json.return_value = SAMPLE_RESPONSE
    fake_resp.raise_for_status = MagicMock()
    with patch("httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.post.return_value = fake_resp
        monkeypatch.setenv("SERPER_API_KEY", "fake")
        results = serper_search("test query", max_results=5)
    assert len(results) == 2
    assert results[0].url == "https://a.example"
    assert results[0].snippet == "Snippet A"
    assert results[0].provider == "serper"
    assert results[0].score is not None  # position-derived

def test_serper_passes_site_clauses(monkeypatch):
    captured = {}
    def fake_post(url, json=None, **kw):
        captured["body"] = json
        m = MagicMock(status_code=200)
        m.json.return_value = {"organic": []}
        m.raise_for_status = MagicMock()
        return m
    with patch("httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.post = fake_post
        monkeypatch.setenv("SERPER_API_KEY", "fake")
        serper_search("test", max_results=5, include_domains=["a.com", "b.com"])
    assert "site:a.com" in captured["body"]["q"] and "site:b.com" in captured["body"]["q"]

def test_serper_missing_key_raises(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SERPER_API_KEY"):
        serper_search("q")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_search_serper.py -v
# Expected: FAIL — module doesn't exist
```

- [ ] **Step 3: Implement `search_serper.py`**

```python
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
from agents.tools.blocked_domains import BLOCKED_DOMAINS

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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_search_serper.py -v
# Expected: 3 PASS
```

- [ ] **Step 5: Manual smoke test against live Serper (optional, costs 1 credit)**

```bash
uv run python -c "
from agents.tools.search_serper import serper_search
r = serper_search('France open data portal', max_results=3)
for x in r: print(x.title, x.url, x.score)
"
# Expected: 3 plausible results, scores 1.0 / 0.5 / 0.333
```

- [ ] **Step 6: Commit**

```bash
git add agents/tools/search_serper.py tests/test_search_serper.py
git commit -m "Add Serper.dev search wrapper"
git push origin main
```

---

### Task 3: Snippet-picker prompt module

**Files:**
- Create: `agents/prompts/snippet_picker.py`
- Test: `tests/test_snippet_picker_prompt.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_snippet_picker_prompt.py
from agents.prompts.snippet_picker import NAME, VERSION, SYSTEM, build_user_message

def test_metadata_present():
    assert NAME == "snippet_picker"
    assert VERSION == 1
    assert "passage selector" in SYSTEM.lower()
    assert "literal" in SYSTEM.lower()
    assert "<= 500" in SYSTEM or "500 characters" in SYSTEM

def test_user_message_truncates_long_pages():
    long_text = "x" * 20000
    msg = build_user_message(query="q", url="https://u", page_text=long_text)
    # 8000 cap + some prelude, but page payload must be capped
    assert msg.count("x") == 8000
    assert "https://u" in msg
    assert "q" in msg
```

- [ ] **Step 2: Run test to verify failure**

- [ ] **Step 3: Implement `agents/prompts/snippet_picker.py`** with the locked prompt above, `PAGE_TEXT_CAP = 8000`, a `build_user_message(query, url, page_text)` helper that truncates to cap.

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add agents/prompts/snippet_picker.py tests/test_snippet_picker_prompt.py
git commit -m "Add snippet-picker prompt (v1) for DIY-Tavily"
git push origin main
```

---

### Task 4: Snippet-picker LLM wrapper

**Files:**
- Create: `agents/tools/snippet_picker.py`
- Test: `tests/test_snippet_picker.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_snippet_picker.py
from unittest.mock import patch
from agents.models import LLMUsage
from agents.tools.snippet_picker import pick_snippet, PickedChunk

def _fake_llm_returns(chunks):
    """Build a fake (parsed, usage) tuple as call_for_structured would."""
    from agents.tools.snippet_picker import _ChunksOut
    parsed = _ChunksOut(chunks=[PickedChunk(**c) for c in chunks])
    usage = LLMUsage(
        input_tokens=10, output_tokens=10, wall_clock_ms=10,
        estimated_cost_usd=0.0, model_version="test",
        prompt_version_id=None, condition_label="test", raw_response="{}",
    )
    return (parsed, usage)

def test_top_chunk_above_threshold_returns_single(monkeypatch):
    monkeypatch.setattr(
        "agents.tools.snippet_picker.call_for_structured",
        lambda **kw: _fake_llm_returns([
            {"text": "the answer", "score": 0.9},
            {"text": "less relevant", "score": 0.4},
        ]),
    )
    chunks, usage = pick_snippet(query="q", url="u", page_text="t")
    assert len(chunks) == 1
    assert chunks[0].text == "the answer"

def test_top_chunk_below_threshold_returns_up_to_three(monkeypatch):
    monkeypatch.setattr(
        "agents.tools.snippet_picker.call_for_structured",
        lambda **kw: _fake_llm_returns([
            {"text": "a", "score": 0.5},
            {"text": "b", "score": 0.4},
            {"text": "c", "score": 0.2},
        ]),
    )
    chunks, _ = pick_snippet(query="q", url="u", page_text="t")
    assert len(chunks) == 3

def test_empty_chunks_means_drop(monkeypatch):
    monkeypatch.setattr(
        "agents.tools.snippet_picker.call_for_structured",
        lambda **kw: _fake_llm_returns([]),
    )
    chunks, _ = pick_snippet(query="q", url="u", page_text="t")
    assert chunks == []

def test_aggregate_snippet_joins_chunks():
    from agents.tools.snippet_picker import aggregate_snippet
    chunks = [
        PickedChunk(text="first", score=0.6),
        PickedChunk(text="second", score=0.5),
    ]
    assert aggregate_snippet(chunks) == "first ... second"

def test_aggregate_score_is_top():
    from agents.tools.snippet_picker import aggregate_score
    chunks = [
        PickedChunk(text="a", score=0.6),
        PickedChunk(text="b", score=0.9),  # not first; aggregate uses index 0
    ]
    assert aggregate_score(chunks) == 0.6
```

- [ ] **Step 2: Run tests to verify failure**

- [ ] **Step 3: Implement `agents/tools/snippet_picker.py`**

```python
"""Claude snippet picker for the DIY-Tavily pipeline.

Given a query and a cleaned page text, returns up to three ranked
passages. Single LLM call via the existing call_for_structured wrapper.

The threshold rule (Task locked decision): if the top chunk's score is
>= TOP_CHUNK_THRESHOLD, return only that chunk; otherwise return the
whole list up to three. Empty list signals "drop this URL".
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from agents.models import LLMUsage
from agents.prompts import snippet_picker as picker_prompt
from agents.tools import db as db_helpers
from agents.tools.llm import call_for_structured

TOP_CHUNK_THRESHOLD = 0.7
MULTI_CHUNK_SEPARATOR = " ... "


class PickedChunk(BaseModel):
    text: str = Field(..., max_length=500)
    score: float = Field(..., ge=0.0, le=1.0)


class _ChunksOut(BaseModel):
    chunks: List[PickedChunk] = Field(default_factory=list, max_length=3)


def pick_snippet(
    *,
    query: str,
    url: str,
    page_text: str,
    subtrio_id: str | None = None,
) -> tuple[List[PickedChunk], LLMUsage]:
    prompt_id = db_helpers.ensure_prompt_version(
        picker_prompt.NAME,
        picker_prompt.VERSION,
        picker_prompt.SYSTEM,
        picker_prompt.DESCRIPTION,
    )
    parsed, usage = call_for_structured(
        system=picker_prompt.SYSTEM,
        user_message=picker_prompt.build_user_message(
            query=query, url=url, page_text=page_text,
        ),
        output_schema=_ChunksOut,
        max_tokens=1500,
        condition_label="snippet_pick",
        prompt_version_id=prompt_id,
        usage_context=f"snippet_pick:{url[:80]}",
        subtrio_id=subtrio_id,
    )
    chunks = parsed.chunks
    if not chunks:
        return [], usage
    if chunks[0].score >= TOP_CHUNK_THRESHOLD:
        return chunks[:1], usage
    return chunks[:3], usage


def aggregate_snippet(chunks: List[PickedChunk]) -> str:
    return MULTI_CHUNK_SEPARATOR.join(c.text for c in chunks)


def aggregate_score(chunks: List[PickedChunk]) -> float | None:
    return chunks[0].score if chunks else None
```

- [ ] **Step 4: Run tests to verify pass**

```bash
uv run pytest tests/test_snippet_picker.py -v
```

- [ ] **Step 5: Commit**

```bash
git add agents/tools/snippet_picker.py tests/test_snippet_picker.py
git commit -m "Add Claude snippet picker with threshold-based chunk count"
git push origin main
```

---

### Task 5: Trafilatura extraction wrapper

**Files:**
- Create: `agents/tools/extract.py`
- Test: `tests/test_extract.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_extract.py
from agents.tools.extract import extract_text

def test_extract_strips_boilerplate():
    html = """<html><body>
      <nav>menu</nav>
      <article><p>The relevant body of the article goes here.</p></article>
      <footer>cookies legal</footer>
    </body></html>"""
    text = extract_text(html, url="https://x")
    assert "relevant body" in text
    assert "menu" not in text and "cookies legal" not in text

def test_extract_returns_empty_on_garbage():
    text = extract_text("<html></html>", url="https://x")
    assert text == ""

def test_extract_on_already_clean_text_is_passthrough():
    # When fetch cache hits, the input is already plain text. Don't re-extract.
    clean = "This is already cleaned plain text from a prior fetch."
    text = extract_text(clean, url="https://x", is_html=False)
    assert text == clean
```

- [ ] **Step 2: Run, fail**

- [ ] **Step 3: Implement `extract.py`** — thin wrapper around `trafilatura.extract` with `favor_recall=True`, `include_comments=False`, `include_tables=True`. Add an `is_html: bool = True` flag: when False, return the input verbatim (caller already has cleaned text). PDFs are out of scope for v1; only HTML is processed.

- [ ] **Step 4: Pass**

- [ ] **Step 5: Commit**

---

### Task 6: SQLite cache schema migration

**Files:**
- Modify: `scripts/setup_sqlite.py` — add 3 cache tables
- Modify: `agents/tools/db.py` — small helpers

- [ ] **Step 1: Write the failing test**

```python
# tests/test_search_cache_schema.py
import sqlite3
def test_three_cache_tables_exist(tmp_path):
    # run setup against a temp DB
    import importlib, agents.tools.db as dbm
    # Easier: just verify against the real DB after re-running setup.
    conn = sqlite3.connect("data/odmi.db")
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "search_cache_serp" in names
    assert "search_cache_fetch" in names
    assert "search_cache_snippet" in names
```

- [ ] **Step 2: Run, fail**

- [ ] **Step 3: Add CREATE TABLE statements to `scripts/setup_sqlite.py`**

```sql
CREATE TABLE IF NOT EXISTS search_cache_serp (
  cache_key   TEXT PRIMARY KEY,           -- hash(query|max|sorted_domains)
  query       TEXT NOT NULL,
  max_results INTEGER NOT NULL,
  payload     TEXT NOT NULL,              -- JSON: [{url,title,snippet,score,position}]
  fetched_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_serp_fetched ON search_cache_serp(fetched_at);

CREATE TABLE IF NOT EXISTS search_cache_fetch (
  url         TEXT PRIMARY KEY,
  content     TEXT NOT NULL,              -- cleaned text
  fetched_at  TEXT NOT NULL,
  status_code INTEGER NOT NULL,
  backend     TEXT NOT NULL               -- httpx | playwright
);
CREATE INDEX IF NOT EXISTS idx_fetch_fetched ON search_cache_fetch(fetched_at);

CREATE TABLE IF NOT EXISTS search_cache_snippet (
  cache_key       TEXT PRIMARY KEY,       -- hash(query|sha256(page_text))
  query           TEXT NOT NULL,
  page_text_hash  TEXT NOT NULL,
  chunks_json     TEXT NOT NULL,
  picked_at       TEXT NOT NULL,
  prompt_version_id INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snip_picked ON search_cache_snippet(picked_at);
```

- [ ] **Step 4: Run setup script and tests**

```bash
uv run python scripts/setup_sqlite.py
uv run pytest tests/test_search_cache_schema.py -v
```

- [ ] **Step 5: Commit**

---

### Task 7: Cache module (`search_cache.py`)

**Files:**
- Create: `agents/tools/search_cache.py`
- Test: `tests/test_search_cache.py`

- [ ] **Step 1: Tests cover** SERP miss → store → hit, fetch miss → store → hit, snippet miss → store → hit, TTL expiry sets miss.

- [ ] **Step 2-4: Implement with three small functions per table — `serp_get/serp_put`, `fetch_get/fetch_put`, `snippet_get/snippet_put`.** TTL is 30 days. Cache key for SERP: `hashlib.sha256(...).hexdigest()` over the parameter tuple. URL normalisation for fetch keys: lowercase scheme/host, strip trailing slash.

- [ ] **Step 5: Commit**

---

### Task 8: DIY pipeline composition (`search_diy.py`)

**Files:**
- Create: `agents/tools/search_diy.py`
- Test: `tests/test_search_diy.py`

- [ ] **Step 1: Write failing test** — mocks Serper + fetch + picker, asserts end-to-end the function returns `SearchResult` rows with `provider="diy"` and properly aggregated snippets.

- [ ] **Step 2: Run, fail**

- [ ] **Step 3: Implement**

```python
"""DIY-Tavily pipeline:
  query → Serper SERP → parallel fetch → trafilatura extract → Claude pick
       → SearchResult(provider="diy")

Uses search_cache at every layer. Drops URLs the picker returns nothing for.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from agents.tools.search import SearchResult
from agents.tools.search_serper import serper_search
from agents.tools.fetch import fetch_text, fetch_rendered_text
from agents.tools.extract import extract_text
from agents.tools.snippet_picker import (
    pick_snippet, aggregate_snippet, aggregate_score,
)
from agents.tools import search_cache as cache

FETCH_PARALLELISM = 5

def diy_search(
    query: str,
    *,
    max_results: int = 5,
    include_domains: Optional[List[str]] = None,
    subtrio_id: str | None = None,
) -> List[SearchResult]:
    # 1. SERP (cached)
    serp = cache.serp_get(query, max_results, include_domains)
    if serp is None:
        serp = serper_search(query, max_results=max_results, include_domains=include_domains)
        cache.serp_put(query, max_results, include_domains, serp)

    # 2. Parallel fetch (cached). Cache stores ALREADY-CLEANED text so
    # we never re-extract on cache hits.
    def _fetch(r: SearchResult) -> tuple[SearchResult, str, bool]:
        """Return (result, text, is_already_clean)."""
        cached = cache.fetch_get(r.url)
        if cached is not None:
            return r, cached, True  # already clean, skip extract
        result = fetch_text(r.url)
        if result.failure_mode in ("empty_after_strip", "timeout") or not result.content:
            result = fetch_rendered_text(r.url)
        if result.failure_mode is not None:
            return r, "", False
        # fetch_text returns tag-stripped text already, so it's "clean enough"
        # for trafilatura's text-pass-through path. Cache stores it as-is.
        cache.fetch_put(r.url, result.content, status_code=result.status_code,
                        backend=result.backend)
        return r, result.content, True

    fetched: list[tuple[SearchResult, str, bool]] = []
    with ThreadPoolExecutor(max_workers=FETCH_PARALLELISM) as pool:
        for fut in as_completed(pool.submit(_fetch, r) for r in serp):
            fetched.append(fut.result())

    # 3. Extract + pick
    out: List[SearchResult] = []
    for r, text, already_clean in fetched:
        if not text:
            continue
        extracted = extract_text(text, url=r.url, is_html=not already_clean)
        if not extracted:
            continue
        cached_chunks = cache.snippet_get(query, extracted)
        if cached_chunks is None:
            chunks, _ = pick_snippet(
                query=query, url=r.url, page_text=extracted, subtrio_id=subtrio_id
            )
            cache.snippet_put(query, extracted, chunks)
        else:
            chunks = cached_chunks
        if not chunks:
            continue
        out.append(SearchResult(
            title=r.title,
            url=r.url,
            snippet=aggregate_snippet(chunks),
            score=aggregate_score(chunks),
            provider="diy",
        ))
        if len(out) >= max_results:
            break
    return out
```

- [ ] **Step 4: Run tests to verify pass**

- [ ] **Step 5: Commit**

---

### Task 9: Wire DIY into `search.py` dispatch

**Files:**
- Modify: `agents/tools/search.py` — add `diy` and `serper_raw` provider values
- Test: extend `tests/test_search_provider_arg.py`

- [ ] **Step 1: Add test for `provider="diy"` and `provider="serper_raw"`**

- [ ] **Step 2: Run, fail**

- [ ] **Step 3: Add branches in `search()`**

```python
Provider = Literal["auto", "tavily", "brave", "serper_raw", "diy"]

# inside search()
if provider == "diy":
    from agents.tools.search_diy import diy_search
    return _scrub_blocked(diy_search(
        query, max_results=max_results, include_domains=include_domains
    ))
if provider == "serper_raw":
    from agents.tools.search_serper import serper_search
    return _scrub_blocked(serper_search(
        query, max_results=max_results, include_domains=include_domains
    ))
```

`on_call` telemetry: emit a single record with `provider="diy"` (or `"serper_raw"`) at the end. Latency includes the full pipeline.

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Commit**

---

### Task 10: Smoke-test end-to-end on one (q, c) pair

Manual integration test before the shakedown. Pick one known-good pair (e.g. `P1 / FR`) and call each provider.

- [ ] **Step 1: Write smoke script**

```bash
# scripts/smoke_diy.py
from agents.tools.search import search
for prov in ("tavily", "brave", "serper_raw", "diy"):
    print(f"=== {prov} ===")
    try:
        results = search("France open data portal national", provider=prov, max_results=3)
        for r in results:
            print(f"  {r.title[:60]} ({r.score}) — {r.snippet[:120]}")
    except Exception as e:
        print(f"  ERROR: {e}")
```

- [ ] **Step 2: Run it**

```bash
uv run python scripts/smoke_diy.py
```

Expected: all four providers return 3 results, DIY's snippets read more like extracted passages than raw Serper descriptions.

- [ ] **Step 3: Eyeball outputs.** If DIY snippets look wrong (truncated mid-word, irrelevant, English-only when page is French), iterate on the prompt before scaling.

- [ ] **Step 4: Commit smoke script**

```bash
git add scripts/smoke_diy.py
git commit -m "Add DIY smoke script for manual one-pair eyeball"
git push origin main
```

---

### Task 11: A/B runner (`evaluation/search_ab.py`)

**Files:**
- Create: `evaluation/search_ab.py`
- Create: `evaluation/__init__.py` (if missing)

- [ ] **Step 1: Sketch the spec inside the file as a docstring** so the script's contract is clear.

The runner:
1. Reads a JSON list of (question_id, country_code) pairs from `--pairs PATH`
2. For each provider in `--providers tavily,brave,serper_raw,diy`:
   - Creates an `experiments` row tagged with provider + run timestamp
   - Dispatches each pair through `dispatch_subtrios.py` (or a thin internal equivalent) with the provider plumbed all the way down, using `experiment_id` for isolation
3. Polls until all subtrios reach a terminal state or a configurable timeout
4. Returns the list of `experiment_id`s for the aggregator to pick up

- [ ] **Step 2: Implement** — re-uses the existing `scripts/dispatch_subtrios.py` machinery; add a `--search-provider` flag there if missing and propagate through `run_coordinator.py`.

**Query-determinism guarantee.** The four conditions must see identical queries per (q,c) pair so the A/B is confounded only by the search backend, not by stochastic LLM query-gen drift. Implementation: on the first condition to run for each (q,c) pair, cache the generated queries into a new SQLite table `ab_query_cache (question_id, country_code, queries_json, created_at)`. Subsequent conditions for the same pair read from this cache instead of calling `generate_queries()`. The A/B runner enforces processing order: `diy` first (highest variability cost to repeat), then the cheaper conditions inherit its queries. Verification: a test asserts that across two consecutive `--search-provider=X --search-provider=Y` runs over the same pair, the `phase2_researcher_runs.search_queries_used` cells are character-identical.

- [ ] **Step 3: Validate** — `uv run python evaluation/search_ab.py --pairs evaluation/pilot_20.json --providers tavily,brave,serper_raw,diy --dry-run` prints the dispatch plan without running.

- [ ] **Step 4: Commit**

---

### Task 12: Pilot sample selection script

**Files:**
- Create: `evaluation/select_pilot.py`

- [ ] **Step 1: Write a script that** picks 20 (q,c) pairs balanced across dimensions and known-difficulty levels (mix some with ground truth = "yes", some "no", some "other"). Writes to `evaluation/pilot_20.json`.

- [ ] **Step 2: Generate `pilot_20.json`** and commit it.

- [ ] **Step 3: Commit**

---

### Task 13: 20-pair shakedown run

Manual step, but document the procedure here.

- [ ] **Step 1: Run the A/B on pilot_20.json**

```bash
uv run python evaluation/search_ab.py \
  --pairs evaluation/pilot_20.json \
  --providers tavily,brave,serper_raw,diy
```

- [ ] **Step 2: Watch the dashboard.** Open `dashboard/Home.py` and filter by the four new experiment_ids. Check finalised count climbs, no failures stack on one provider.

- [ ] **Step 3: Spot-check 5 DIY pairs by hand.** For each, read the Researcher's evidence_quote and check it actually appears in the cited URL. Verify match status against ground truth.

- [ ] **Step 4: Diagnose failures and fix.** Common shakedown issues:
  - Snippet picker quoting from boilerplate (tighten prompt rule 5)
  - Trafilatura missing JS-rendered content (Playwright fallback should fire; verify it does)
  - DIY drops too many URLs (lower TOP_CHUNK_THRESHOLD or relax)

- [ ] **Step 5: When shakedown is clean, commit any prompt/code adjustments** and bump `snippet_picker.VERSION` to 2 if the prompt changed.

---

### Task 14: 400-pair sample selection

**Files:**
- Create: `evaluation/select_ab_sample.py`

- [ ] **Step 1: Build the stratified 400-pair sample.** Cells = dimension × country-group. Aim for ~25 pairs per cell. Include only pairs with non-null ground truth.

Country groups (per ODMI's published clustering): `EU-Trendsetters`, `EU-Fast-trackers`, `EU-Followers`, `EU-Beginners` + `EFTA`. Concentrate on 6-8 countries that span the groups. Pull from the `ground_truth` table.

- [ ] **Step 2: Run, write `evaluation/ab_400.json`**

- [ ] **Step 3: Commit**

---

### Task 15: 400-pair main A/B

- [ ] **Step 1: Estimate cost upfront**

```
400 pairs × 4 conditions × ~3.5 search calls each = 5,600 search calls
- Tavily: ~1,400 (under monthly free credits after June reset)
- Brave: ~1,400 (under free tier)
- Serper raw: ~1,400 × $0.001 = $1.40
- DIY: ~1,400 SERP × $0.001 = $1.40 + Claude picker calls (free under Max)
≈ £3 total spend.
```

- [ ] **Step 2: Run DIY first, in isolation.** The DIY condition makes ~3 extra Claude calls per (q,c) pair (one per fetched URL for the snippet pick) on top of the researcher's main call. At 400 pairs that's ~1,200 extra Claude calls, drawing on the rolling 5-hour Claude Max window (per D20). Run DIY alone so the cheaper conditions don't compete for the same window.

```bash
uv run python evaluation/search_ab.py \
  --pairs evaluation/ab_400.json \
  --providers diy
```

- [ ] **Step 3: Once DIY completes, run the other three together.**

```bash
uv run python evaluation/search_ab.py \
  --pairs evaluation/ab_400.json \
  --providers tavily,brave,serper_raw
```

These three inherit DIY's seeded query cache (per Task 11) so they see identical queries.

- [ ] **Step 4: Wait for completion.** Watch the Run Console page in the dashboard.

---

### Task 16: A/B report (`evaluation/search_ab_report.py`)

**Files:**
- Create: `evaluation/search_ab_report.py`

- [ ] **Step 1: Sketch** — reads experiment_ids, joins to `phase2_final` and `ground_truth`, emits a markdown table + saves a CSV to `evaluation/results/ab_<date>.csv`. Cells: per-provider match rate, coverage (% pairs with non-null final answer), £ per matched pair, mean wall-clock ms per researcher run, mean snippet length.

- [ ] **Step 2: Per-dimension breakdown** for the dissertation tables.

- [ ] **Step 3: Run it on the pilot to validate the report shape before the 400-run lands.**

- [ ] **Step 4: Commit**

---

### Task 17: SPEC D29 entry

D28 is already taken (answer-shape schemas, landed 2026-05-26). Re-check the next free number when executing — if more decisions land between now and June, bump accordingly.

**Files:**
- Modify: `docs/SPEC.md`

- [ ] **Step 1: Draft D29 (or next free Dn) in `docs/SPEC.md`** under the existing decision log. Title: "D29: DIY-Tavily as primary search provider, validated by paired A/B". Cover: motivation (May 2026 quota incident, untested CLAUDE.md claim about Tavily), architecture, A/B design, results table (filled in after the 400 run), and the trade-off accepted (snippet quality is now under our control rather than a vendor's).

- [ ] **Step 2: Add to the SPEC table of contents.**

- [ ] **Step 3: Commit**

---

### Task 18: Sweep ritual

Per the memory `[[feedback-post-change-sweep]]`: this is a substantial change.

- [ ] CLAUDE.md — update the "Tech stack" stanza to reflect Serper + trafilatura + DIY pipeline
- [ ] README.md — same
- [ ] METHODOLOGY.md — add the A/B as a methodology entry
- [ ] PROJECT_LOG.md — log the day's work
- [ ] Regen the slides: `uv run python scripts/generate_slides.py`
- [ ] Commit + push

---

## Acceptance Criteria

The implementation is done when:

1. All test files pass (`uv run pytest`).
2. The smoke script returns plausible results from all four providers for one (q,c) pair.
3. The 20-pair shakedown shows DIY snippets visibly cleaner than Serper-raw on at least 15 of 20 cases (human eyeball).
4. The 400-pair A/B completes with at least 95% pairs reaching a finalised state for every provider.
5. `evaluation/search_ab_report.py` emits a 4-row, 5-column table covering match rate, coverage, £ per matched pair, mean wall-clock ms, mean snippet length.
6. SPEC D28 is filled in with the actual results.

## What an Examiner Will Ask

- "How do you justify your primary-provider choice?" — Point at the table in D28.
- "What's the marginal contribution of the Claude snippet picker over Serper's raw description?" — Compare DIY vs `serper_raw` rows.
- "Why didn't you also test Exa/CSE?" — Honest answer: their addition would not change the headline finding, and the dissertation budget for engineering time was finite.
- "Could trusted-domains routing be confounding the search-provider comparison?" — No: it's held constant across all conditions, so any inter-provider delta is the provider, not the routing layer.
- "Does the new answer-shape work (D28) affect this A/B?" — D28 changes how the swarm expresses its answer (binary vs band vs ordinal). The A/B still measures match-against-ODMI, which is shape-aware, so the comparison is valid. But: the 400-pair sample must be drawn AFTER the answer-shape rebuild has produced enough finalised rows on the new schema, otherwise the pre-D28 wipe leaves no comparable baseline.

## Risks

- **trafilatura extraction quality varies by site.** PDF and heavily-JS portals are weak spots. Mitigation: Playwright fallback already in `fetch.py`; v1 plan does not handle PDFs (acknowledged in D28).
- **Claude proxy concurrency unknown.** Budget says 40k calls over 2 months ≈ 700/day. Even fully serial this is fine. Mitigation: keep `FETCH_PARALLELISM=5` and don't aggressively parallelise picker calls in v1.
- **Cache staleness.** 30-day TTL is a guess. If a portal changes its layout the cached fetch may be wrong. Mitigation: cache_get gates on TTL; for the A/B run, recommend flushing fetch cache first so all conditions see fresh pages.
- **A/B pair selection bias.** Stratification by dimension/country only. Quality dimension is hardest; if 25 Quality pairs all happen to be the easiest 25, the A/B understates difficulty. Mitigation: select within each cell with a fixed seed for reproducibility, and report cell sizes alongside means.
