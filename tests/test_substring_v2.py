"""Tests for the v2 grounding matcher (EXP-11 P4).

The required cases from docs/EXPERIMENTS_VERIFIER_REDESIGN.md S0.1:
junction-stitch rejected, within-snippet elision accepted, short
fragment rejected, order violation rejected, NFKC cases preserved.
"""

from __future__ import annotations

from agents.tools import substring
from agents.tools.substring import contains_v2


# Two snippets from different sources. A quote that spans the boundary
# is a splice, not a real passage.
SNIP_A = "Malta's open data portal data.gov.mt provides datasets in CSV format."
SNIP_B = "The national API gateway supports automated harvesting of metadata."


def test_plain_single_fragment_matches_in_one_snippet():
    res = contains_v2([SNIP_A, SNIP_B], "provides datasets in CSV format")
    assert res.matched is True
    assert res.snippet_index == 0
    assert res.n_fragments == 1


def test_junction_stitch_is_rejected_as_cross_snippet():
    # Fragments either side of the snippet boundary. v1 waves it through.
    stitched = "datasets in CSV format ... The national API gateway supports"
    assert substring.contains("\n\n".join([SNIP_A, SNIP_B]), stitched) is True
    res = contains_v2([SNIP_A, SNIP_B], stitched)
    assert res.matched is False
    assert res.reason == "cross_snippet_only"
    assert res.n_fragments == 2


def test_within_snippet_elision_is_accepted():
    snip = (
        "The portal provides open datasets in machine readable formats "
        "and also supports bulk download through a documented API."
    )
    quote = "The portal provides open datasets ... supports bulk download through a documented API"
    res = contains_v2([snip, SNIP_B], quote)
    assert res.matched is True
    assert res.snippet_index == 0
    assert res.n_fragments == 2


def test_short_fragment_is_rejected():
    # Second fragment normalises to under MIN_FRAGMENT_CHARS.
    quote = "provides datasets in CSV format ... metadata"
    res = contains_v2([SNIP_A, SNIP_B], quote)
    assert res.matched is False
    assert res.reason == "fragment_too_short"


def test_short_single_quote_is_rejected():
    res = contains_v2([SNIP_A], "open data")
    assert res.matched is False
    assert res.reason == "fragment_too_short"


def test_order_violation_is_rejected():
    snip = (
        "The portal provides open datasets in machine readable formats "
        "and also supports bulk download through a documented API."
    )
    # Fragments present but in the wrong order within the snippet.
    quote = "supports bulk download through a documented API ... The portal provides open datasets"
    res = contains_v2([snip], quote)
    assert res.matched is False
    # Both fragments live in the one snippet but not in order, and the
    # reversed concatenation is not a v1 corpus substring either.
    assert res.reason in ("no_match", "cross_snippet_only")


def test_absent_quote_is_no_match():
    res = contains_v2([SNIP_A, SNIP_B], "the portal exposes a SPARQL endpoint for linked data")
    assert res.matched is False
    assert res.reason == "no_match"


def test_nfkc_smart_quotes_and_nbsp_still_match():
    # Snippet uses a non-breaking space and a smart apostrophe.
    snip = "Loi pour une République numérique was enacted in 2016."
    quote = "Loi pour une Republique numerique was enacted"  # accents differ, NBSP vs space
    # NFKC + casefold should fold these together.
    res = contains_v2([snip], "Loi pour une République numérique was enacted")
    assert res.matched is True
    # And the punctuation/whitespace-insensitive nature is intact.
    assert contains_v2([snip], "République numérique was enacted in 2016").matched is True


def test_empty_and_whitespace_quote_is_no_match():
    assert contains_v2([SNIP_A], "").matched is False
    assert contains_v2([SNIP_A], "   ").matched is False


def test_empty_snippet_list_is_no_match():
    res = contains_v2([], "provides datasets in CSV format")
    assert res.matched is False
    assert res.reason == "no_match"


def test_skips_empty_snippets_without_indexing_error():
    res = contains_v2(["", SNIP_A, ""], "provides datasets in CSV format")
    assert res.matched is True
    assert res.snippet_index == 1


def test_bracketed_ellipsis_marker_splits():
    snip = (
        "The strategy commits to publishing high value datasets and, "
        "separately, to maintaining an open licence across the catalogue."
    )
    quote = "The strategy commits to publishing high value datasets [...] maintaining an open licence across the catalogue"
    res = contains_v2([snip], quote)
    assert res.matched is True
    assert res.n_fragments == 2


def test_decimal_point_does_not_split():
    snip = "Licence coverage reached 38.5 percent across the national catalogue last year."
    quote = "Licence coverage reached 38.5 percent across the national catalogue"
    res = contains_v2([snip], quote)
    # The single dot in 38.5 must not be read as an ellipsis.
    assert res.matched is True
    assert res.n_fragments == 1
