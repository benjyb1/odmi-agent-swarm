"""Lock the verbatim quote-gate: the deterministic anti-hallucination spine.

A real quote must survive trivial whitespace reflow and case differences; a
paraphrase (different words) and a too-short fragment must not pass.
"""
from __future__ import annotations

from who_speech.swarm import quote_in_passage


def test_verbatim_quote_matches_despite_whitespace_reflow():
    assert quote_in_passage("WHO supported the reform", "...WHO  supported\nthe reform...")


def test_casefold_difference_still_matches():
    assert quote_in_passage("who supported the reform", "WHO SUPPORTED THE REFORM today")


def test_paraphrase_does_not_match():
    assert not quote_in_passage(
        "WHO backed the reform programme", "WHO supported the reform programme"
    )


def test_too_short_quote_is_rejected():
    assert not quote_in_passage("WHO", "WHO did many things here in 2021")
