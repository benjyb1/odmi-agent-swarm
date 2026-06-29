"""Independent-source verification of quotes.

The deterministic quote-gate proves a quote matches the Docling extraction. The
evaluation showed that is not the same as the quote being reproducible in the
source PDF: Docling introduces artifacts (a dropped hyphen "out-ofpocket", a
dropped bullet, an internal newline) that a different extractor renders
differently. This layer re-checks the quote against an independent extraction,
tolerant of those cosmetic artifacts but not of a quote that is genuinely
absent.
"""
from __future__ import annotations

from who_speech import verify
from who_speech.swarm import BriefingPack, BriefingPoint


def _point(point="P", quote="a sufficiently long verbatim quote here"):
    return BriefingPoint(
        point=point, quote=quote, citation="C", iris_url="U", page=1, confidence=0.8)


def _pack(points):
    return BriefingPack(query="q", points=points, abstained=False, note="")


# --- loose_norm: tolerant of hyphenation, bullets, whitespace, case ----------

def test_loose_norm_makes_hyphenation_artifact_match_real_word():
    assert verify.loose_norm("out-ofpocket") == verify.loose_norm("out-of-pocket")


def test_loose_norm_strips_bullets_and_collapses_newlines():
    assert verify.loose_norm("pay.\n•  Cat") == verify.loose_norm("pay. Cat")


# --- quote_reproduces --------------------------------------------------------

def test_reproduces_despite_hyphenation_artifact():
    quote = "the majority of out-ofpocket payments are incurred"
    source = "suggests the majority of out-of-pocket payments are incurred as a result"
    assert verify.quote_reproduces(quote, source) is True


def test_reproduces_despite_dropped_bullet_and_newline():
    quote = "out-of-pocket payments.\nCatastrophic spending is concentrated"
    source = "after out-of-pocket payments. • Catastrophic spending is concentrated in"
    assert verify.quote_reproduces(quote, source) is True


def test_fabricated_quote_does_not_reproduce():
    quote = "WHO doubled the national health budget"
    assert verify.quote_reproduces(quote, "WHO supported the health budget review") is False


def test_too_short_quote_does_not_reproduce():
    assert verify.quote_reproduces("WHO did", "WHO did many things in the document") is False


# --- tidy_quote: display cleanup (only the fixable artifacts) -----------------

def test_tidy_quote_collapses_newline_and_strips_bullet():
    assert verify.tidy_quote("pay.\n•  Catastrophic") == "pay. Catastrophic"


def test_tidy_quote_leaves_clean_quote_unchanged():
    q = "WHO supported the reform in 2021."
    assert verify.tidy_quote(q) == q


def test_tidy_quote_does_not_pretend_to_repair_dropped_hyphen():
    # Honest limitation: a dropped-hyphen artifact cannot be reversed here.
    assert verify.tidy_quote("out-ofpocket") == "out-ofpocket"


# --- verify_pack: keep reproduced points, drop the rest ----------------------

def test_verify_pack_keeps_reproduced_and_drops_absent():
    pa = _point(point="A", quote="a real quote present in the source")
    pb = _point(point="B", quote="a fabricated quote not in any source")
    pack = _pack([pa, pb])

    def resolver(p):
        if p.point == "A":
            return "here is a real quote present in the source document"
        return "unrelated text"

    v = verify.verify_pack(pack, source_text_for=resolver)
    assert [p.point for p in v.points] == ["A"]
    assert [p.point for p in v.dropped] == ["B"]


def test_verify_pack_treats_missing_source_as_unverified():
    pack = _pack([_point(point="A", quote="a real quote present in the source")])
    v = verify.verify_pack(pack, source_text_for=lambda p: None)
    assert v.points == []
    assert [p.point for p in v.dropped] == ["A"]
