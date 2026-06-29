"""Country name -> IRIS MeSH geographic heading resolution."""
from __future__ import annotations

from who_speech.countries import resolve_country


def test_known_nonobvious_heading_is_mapped():
    assert resolve_country("North Macedonia") == "Republic of North Macedonia"


def test_resolution_is_case_insensitive():
    assert resolve_country("north macedonia") == "Republic of North Macedonia"


def test_georgia_resolves_to_the_republic_not_the_us_state():
    assert resolve_country("Georgia") == "Georgia (Republic)"


def test_obvious_name_passes_through():
    assert resolve_country("France") == "France"


def test_unknown_name_passes_through_trimmed():
    assert resolve_country("  Ruritania ") == "Ruritania"
