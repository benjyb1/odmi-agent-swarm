"""Layer 7: live drift tests.

Three minimal live calls that prove the upstream APIs and the DIY
pipeline as a whole are still functional. Catches silent contract
changes (Serper response shape, Claude proxy connectivity, integration
between layers).

Run with: uv run pytest tests/test_drift_live.py -m live -v
Default: skipped.
"""
from __future__ import annotations

import pytest


@pytest.mark.live
def test_serper_returns_results_for_known_query():
    """Serper end-to-end: real call must return at least 3 results."""
    from agents.tools.search_serper import serper_search
    results = serper_search("France open data portal", max_results=5)
    assert len(results) >= 3, f"Expected >=3 results, got {len(results)}"
    # Plausibility: at least one result mentions France or 'open data'
    haystack = " ".join(f"{r.title} {r.snippet}" for r in results).lower()
    assert "france" in haystack or "data.gouv" in haystack or "open data" in haystack


@pytest.mark.live
def test_claude_snippet_picker_returns_chunk_on_relevant_page():
    """Claude proxy round-trip: feed a tiny relevant passage, expect a chunk back."""
    from agents.tools.snippet_picker import pick_snippet
    page_text = (
        "France publishes open data through data.gouv.fr since 2011. "
        "The platform is run by Etalab under the Prime Minister's office. "
        "Anyone can search and download datasets from public administrations."
    )
    chunks, _ = pick_snippet(
        query="how does France publish open data",
        url="https://example.test/drift",
        page_text=page_text,
    )
    assert chunks, "Picker returned no chunks for a clearly-relevant short page"
    assert chunks[0].score >= 0.3, f"Top chunk score suspiciously low: {chunks[0].score}"


@pytest.mark.live
def test_diy_pipeline_end_to_end():
    """Whole DIY pipeline: SERP -> fetch -> extract -> pick -> SearchResult."""
    from agents.tools.search import search
    results = search(
        "Germany dataset publication policy",
        provider="diy",
        max_results=3,
    )
    # The full pipeline can plausibly drop URLs (picker says no relevant content),
    # so we don't require ALL 3, just at least 1.
    assert len(results) >= 1, f"DIY pipeline returned no results; got {results}"
    assert all(r.provider == "diy" for r in results)
    # Plausibility: at least one result has a non-empty snippet
    assert any(r.snippet.strip() for r in results)
