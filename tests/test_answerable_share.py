"""Tests for the per-country answerable-share ceiling computation."""
from __future__ import annotations

import pytest

from evaluation.answerable_share import country_answerable


_CLASS = {
    "WEB1": "web",
    "CAT1": "catalogue",
    "SR1": "self_report",
    "WEBNA": "web",
}


def _rows(cc: str):
    return [
        (cc, "WEB1", "yes"),       # answerable
        (cc, "CAT1", "71-90%"),    # catalogue: answerable only with a registry
        (cc, "SR1", "yes"),        # self-report: never web-answerable
        (cc, "WEBNA", "n/a"),      # n/a gold: not scoreable
    ]


def test_catalogue_blocked_without_registry():
    shares = country_answerable(_rows("XX"), _CLASS, catalogue_countries=set())
    s = shares["XX"]
    assert s.scoreable == 3            # WEBNA excluded (n/a)
    assert s.na == 1
    assert s.web == 1
    assert s.catalogue_blocked == 1
    assert s.catalogue_answerable == 0
    assert s.self_report == 1
    # only the web pair is answerable: 1 / 3
    assert s.ceiling == pytest.approx(1 / 3)


def test_catalogue_recovered_with_registry():
    shares = country_answerable(_rows("FR"), _CLASS, catalogue_countries={"FR"})
    s = shares["FR"]
    assert s.catalogue_answerable == 1
    assert s.catalogue_blocked == 0
    # web + catalogue now answerable: 2 / 3
    assert s.ceiling == pytest.approx(2 / 3)


def test_na_only_country_has_no_ceiling():
    shares = country_answerable(
        [("ZZ", "WEBNA", "not applicable")], _CLASS, set()
    )
    s = shares["ZZ"]
    assert s.scoreable == 0
    assert s.ceiling is None
