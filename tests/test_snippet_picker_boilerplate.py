"""Live behavioural test: snippet picker must reject boilerplate pages.

These tests call real Claude via CLIProxyAPI (localhost:8317). They are marked
``live`` and are skipped by default. Run with::

    uv run pytest tests/test_snippet_picker_boilerplate.py -v -m live

Each fixture contains keyword matches for "France open data portal" ONLY inside
obvious boilerplate text (cookie banners, nav menus, footers, breadcrumbs, or
repeated legal notices). No answering passages appear in the body.

A passing result is either:
- ``chunks`` is empty (picker correctly returned nothing relevant), OR
- all chunks have ``score < 0.4`` (picker found something but ranked it low).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.tools.snippet_picker import pick_snippet

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "boilerplate"


@pytest.mark.live
@pytest.mark.parametrize("fixture_name", [
    "cookie_banner.txt",
    "nav_menu.txt",
    "footer.txt",
    "breadcrumb.txt",
    "legal_repeated.txt",
])
def test_picker_rejects_boilerplate(fixture_name):
    """Picker must not surface boilerplate passages as relevant answers."""
    page_text = (_FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")
    chunks, _ = pick_snippet(
        query="France open data portal",
        url=f"https://example.test/{fixture_name}",
        page_text=page_text,
    )
    if chunks:
        assert all(c.score < 0.4 for c in chunks), (
            f"Picker chose a high-score chunk from boilerplate in {fixture_name!r}: "
            f"{[(c.text[:80], c.score) for c in chunks]}"
        )
