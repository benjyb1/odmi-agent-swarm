"""Dual-format rendering of a briefing pack (bullets and paragraphs).

The load-bearing property: whichever format is chosen, every verbatim quote
and its citation survive unchanged. A speech composer may rewrite the
connective prose, but it can never strip or alter the cited evidence.
"""
from __future__ import annotations

import pytest

from who_speech.render import render, render_bullets, render_paragraphs
from who_speech.swarm import BriefingPack, BriefingPoint


def _point(
    point="WHO supported a health financing reform.",
    quote="WHO supported the introduction of a single-payer system.",
    citation="Some Report. World Health Organization; 2021. Licence: CC BY 3.0 IGO",
    iris_url="https://iris.who.int/handle/10665/1",
    page=12,
):
    return BriefingPoint(
        point=point, quote=quote, citation=citation,
        iris_url=iris_url, page=page, confidence=0.8,
    )


def _pack(points, abstained=False, note=""):
    return BriefingPack(
        query="What has WHO done in X?", points=points,
        abstained=abstained, note=note,
    )


def test_bullets_include_point_quote_and_citation():
    out = render_bullets(_pack([_point()]))
    assert "WHO supported a health financing reform." in out
    assert "WHO supported the introduction of a single-payer system." in out
    assert "iris.who.int/handle/10665/1" in out
    assert "CC BY 3.0 IGO" in out


def test_bullets_abstained_states_no_points():
    out = render_bullets(_pack([], abstained=True, note="nothing solid"))
    assert "no" in out.lower()


def test_paragraphs_without_composer_strings_points_into_prose():
    pts = [_point(point="First thing."), _point(point="Second thing.")]
    out = render_paragraphs(_pack(pts))
    assert "First thing." in out
    assert "Second thing." in out
    assert "Sources" in out


def test_paragraphs_sources_carry_verbatim_quote():
    out = render_paragraphs(_pack([_point(quote="A precise verbatim sentence.")]))
    assert "A precise verbatim sentence." in out


def test_paragraphs_composer_prose_used_but_quotes_still_carried():
    p = _point(point="WHO did a thing.", quote="EXACT QUOTE TEXT.")

    def composer(points):
        return "Ladies and gentlemen, WHO did a thing this year."

    out = render_paragraphs(_pack([p]), composer=composer)
    assert "Ladies and gentlemen" in out       # composer prose present
    assert "EXACT QUOTE TEXT." in out           # verbatim quote still carried


def test_render_rejects_unknown_format():
    with pytest.raises(ValueError):
        render(_pack([_point()]), "sonnet")


def test_render_dispatches_by_format():
    pack = _pack([_point()])
    assert render(pack, "bullets") == render_bullets(pack)
    assert render(pack, "paragraphs") == render_paragraphs(pack)
