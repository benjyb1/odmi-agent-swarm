"""Live test: snippet picker preserves source language and does not translate.

Marked ``live`` -- skipped by default. Run with::

    uv run pytest tests/test_snippet_picker_multilang.py -m live -v

Each parametrised case loads a plain-text fixture written in a non-English
language, calls ``pick_snippet`` via the real CLIProxyAPI, and verifies that
the returned chunk(s) still contain language-specific characters from the
source text.  If Claude were silently translating to English the assertion
would fail, because English text cannot contain ä/ö/ü/ß, é/è/à/ç, or ą/ć/ł etc.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.tools.snippet_picker import pick_snippet

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "multilang"

_LANG_CASES = [
    ("fr.txt", "Comment publier des données ouvertes en France?", set("éèàçê")),
    ("de.txt", "Wie veröffentlicht Deutschland offene Daten?", set("äöüß")),
    ("pl.txt", "Jak Polska publikuje otwarte dane?", set("ąćłśźż")),
]


@pytest.mark.live
@pytest.mark.parametrize("fixture_name,query,lang_chars", _LANG_CASES)
def test_picker_preserves_source_language(fixture_name, query, lang_chars):
    """Returned chunk(s) must contain source-language characters."""
    page_text = (_FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")

    chunks, _ = pick_snippet(
        query=query,
        url=f"https://example.test/{fixture_name}",
        page_text=page_text,
    )

    # Picker must return at least one chunk -- the passages clearly answer the query
    assert chunks, f"Picker returned no chunks for {fixture_name}"

    # The returned chunk text must contain language-specific characters from the source
    combined = " ".join(c.text for c in chunks)
    found = lang_chars.intersection(set(combined))
    assert found, (
        f"Picker may have translated: returned text has no {fixture_name} "
        f"language characters. Got: {combined[:200]!r}"
    )
