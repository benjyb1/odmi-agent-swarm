"""Tests for evidence normalisation in the blind search adjudicator.

The blind judge could otherwise guess the provider from two fingerprints:
(a) one arm returning more passages than the other, and (b) full URLs that
reveal the host. These tests cover the two pure helpers that remove those
fingerprints. All pure: no network, no DB, no LLM calls.

  - _equalise_counts: truncates both arms to min length, top-ranked first,
    order preserved.
  - _registrable_domain: reduces a full URL to its registrable domain
    (public suffix + one label), stripping scheme, path and a www. prefix.
"""
from __future__ import annotations

from agents.prompts.search_adjudicator import _format_evidence, _registrable_domain
from agents.tools.search_adjudicator import _equalise_counts


# ---------------------------------------------------------------------------
# _equalise_counts: equal passage count across the two arms
# ---------------------------------------------------------------------------

def test_equalise_counts_truncates_longer_arm_to_shorter():
    a = [{"url": "1"}, {"url": "2"}, {"url": "3"}, {"url": "4"}, {"url": "5"}]
    b = [{"url": "x"}, {"url": "y"}]
    a2, b2 = _equalise_counts(a, b)
    assert len(a2) == len(b2) == 2


def test_equalise_counts_truncates_when_b_is_longer():
    a = [{"url": "1"}]
    b = [{"url": "x"}, {"url": "y"}, {"url": "z"}]
    a2, b2 = _equalise_counts(a, b)
    assert len(a2) == len(b2) == 1


def test_equalise_counts_keeps_top_ranked_and_preserves_order():
    # Passages arrive already ranked best-first; truncation must keep the
    # top n and leave their order untouched.
    a = [{"url": "a1"}, {"url": "a2"}, {"url": "a3"}, {"url": "a4"}]
    b = [{"url": "b1"}, {"url": "b2"}]
    a2, b2 = _equalise_counts(a, b)
    assert [p["url"] for p in a2] == ["a1", "a2"]
    assert [p["url"] for p in b2] == ["b1", "b2"]


def test_equalise_counts_equal_inputs_unchanged():
    a = [{"url": "a1"}, {"url": "a2"}]
    b = [{"url": "b1"}, {"url": "b2"}]
    a2, b2 = _equalise_counts(a, b)
    assert [p["url"] for p in a2] == ["a1", "a2"]
    assert [p["url"] for p in b2] == ["b1", "b2"]


def test_equalise_counts_empty_arm_yields_two_empties():
    a = [{"url": "a1"}, {"url": "a2"}]
    b: list[dict] = []
    a2, b2 = _equalise_counts(a, b)
    assert a2 == [] and b2 == []


def test_equalise_counts_does_not_mutate_inputs():
    a = [{"url": "a1"}, {"url": "a2"}, {"url": "a3"}]
    b = [{"url": "b1"}]
    _equalise_counts(a, b)
    assert len(a) == 3 and len(b) == 1


# ---------------------------------------------------------------------------
# _registrable_domain: strip the provider-revealing host detail
# ---------------------------------------------------------------------------

def test_registrable_domain_plain_com():
    assert _registrable_domain("https://example.com/a/b?c=d") == "example.com"


def test_registrable_domain_strips_www_prefix():
    assert _registrable_domain("https://www.example.com/path") == "example.com"


def test_registrable_domain_co_uk_keeps_two_labels():
    # A two-part public suffix: the registrable domain is example.co.uk,
    # not the bare co.uk.
    assert _registrable_domain("https://www.example.co.uk/a/b") == "example.co.uk"


def test_registrable_domain_subdomain_reduced_to_registrable():
    assert _registrable_domain("https://data.gov.fr/dataset/123") == "gov.fr"


def test_registrable_domain_bare_host_no_scheme():
    assert _registrable_domain("www.example.org") == "example.org"


def test_registrable_domain_empty_or_missing_is_safe():
    assert _registrable_domain("") == ""
    assert _registrable_domain(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Renderer: domains in, full paths and scores out
# ---------------------------------------------------------------------------

def test_format_evidence_shows_domain_not_full_url_or_score():
    block = _format_evidence(
        "A",
        [{"url": "https://www.example.co.uk/secret/path",
          "snippet": "An RSS feed is available.",
          "title": "Portal", "score": 0.97123}],
    )
    assert "example.co.uk" in block
    # The provider-revealing path must not leak through.
    assert "/secret/path" not in block
    # The numeric score must not reach the judge.
    assert "0.97" not in block
