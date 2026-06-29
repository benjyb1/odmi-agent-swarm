"""Independent-source verification: confirm a quote really is in the cited PDF.

The deterministic quote-gate in the swarm proves the quote matches the passage
the researcher read, which is the Docling extraction. The evaluation showed
that is necessary but not sufficient for the defensibility promise ("you can
find this exact quote in the document"): Docling introduces cosmetic artifacts
(a dropped hyphen so "out-of-pocket" becomes "out-ofpocket", a dropped bullet,
an internal newline) that an independent reader or extractor renders
differently.

This module re-checks a finalised point's quote against an independent
extraction of the same PDF (pypdf, not Docling). Matching is tolerant of the
cosmetic artifacts but still fails a quote that is genuinely absent, so it
catches fabrication and non-reproducible quotes without false-positiving on the
artifacts. The extractor/resolver is injected, so the logic is unit-tested
without network or the pypdf dependency.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

# Characters dropped for loose matching: bullets, every dash/hyphen variant,
# soft hyphen and zero-width marks. Removing all hyphens makes "out-ofpocket"
# and "out-of-pocket" compare equal, which is the artifact we must tolerate.
_DROP = "•·●◦‣▪‐‑‒–—―-­​‌﻿"
_DROP_RE = re.compile("[" + re.escape(_DROP) + "]")
# Bullets/zero-width to strip for display (hyphens are kept when tidying).
_TIDY_RE = re.compile("[•·●◦‣▪­​‌﻿]")


def loose_norm(s: str) -> str:
    """Artifact-tolerant normalisation: drop hyphens/bullets/zero-width and ALL
    whitespace, then casefold. Removing whitespace (not just collapsing it) is
    what makes a line-break hyphen survive: pypdf renders "out-of- pocket"
    (hyphen then space) where Docling joined "out-ofpocket"; both reduce to
    "outofpocket". For matching only, never for display."""
    s = _DROP_RE.sub("", s or "")
    return "".join(s.split()).casefold()


def quote_reproduces(quote: str, source_text: str, min_len: int = 15) -> bool:
    """True iff the quote appears in the source under artifact-tolerant matching."""
    if not quote or len(quote.strip()) < min_len:
        return False
    return loose_norm(quote) in loose_norm(source_text or "")


def tidy_quote(s: str) -> str:
    """Clean a quote for display: strip bullets/soft-hyphen/zero-width and
    collapse internal whitespace (including newlines). Does not attempt to
    reverse a dropped-hyphen artifact, which cannot be done reliably."""
    s = _TIDY_RE.sub(" ", s or "")
    return " ".join(s.split())


@dataclass
class SourceVerification:
    point: str
    reproduced: bool


@dataclass
class PackVerification:
    points: list = field(default_factory=list)   # kept (reproduced in source)
    dropped: list = field(default_factory=list)  # failed reproduction
    results: list = field(default_factory=list)   # SourceVerification per point


# A resolver returns the independently-extracted source text for a point, or
# None if it cannot be fetched.
SourceTextFor = Callable[[object], Optional[str]]


def verify_pack(pack, *, source_text_for: SourceTextFor) -> PackVerification:
    """Re-verify every point's quote against an independent extraction.

    A point with no resolvable source, or whose quote does not reproduce, is
    dropped: a quote a reader cannot find in the document should not reach a
    WHO director.
    """
    out = PackVerification()
    for p in pack.points:
        src = source_text_for(p)
        ok = bool(src) and quote_reproduces(p.quote, src)
        out.results.append(SourceVerification(point=p.point, reproduced=ok))
        (out.points if ok else out.dropped).append(p)
    return out


def make_source_resolver(db_path: str, iris):
    """Production resolver: map a point to its bitstream via the index, download
    it, and extract independently with pypdf. Lazy-imports lancedb and pypdf and
    caches per bitstream. Used when WHO_VERIFY_SOURCE is enabled."""
    import io

    import lancedb
    import pypdf

    from who_speech import config
    from who_speech.models import Bitstream

    rows = lancedb.connect(db_path).open_table("passages").to_arrow().to_pylist()
    text_cache: dict[str, str] = {}

    def _bitstream_for(point) -> Optional[str]:
        nq = loose_norm(point.quote)
        same_doc = [
            r for r in rows
            if r.get("iris_url") == point.iris_url and nq in loose_norm(r.get("text", ""))
        ]
        cand = same_doc or [r for r in rows if nq in loose_norm(r.get("text", ""))]
        return cand[0]["bitstream_uuid"] if cand else None

    def source_text_for(point) -> Optional[str]:
        bsid = _bitstream_for(point)
        if not bsid:
            return None
        if bsid not in text_cache:
            url = config.IRIS_BITSTREAM_CONTENT.format(uuid=bsid)
            content = iris.download(Bitstream(uuid=bsid, name="s.pdf", content_url=url))
            reader = pypdf.PdfReader(io.BytesIO(content))
            text_cache[bsid] = " ".join((pg.extract_text() or "") for pg in reader.pages)
        return text_cache[bsid]

    return source_text_for
