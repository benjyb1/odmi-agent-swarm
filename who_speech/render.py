"""Render a verified briefing pack into the format a given director wants.

Two formats cover the WHO/Europe ask: bullet points (one verified point each,
with its quote and source) and connected paragraphs (a speech-style prose body
plus a sources block). Both come off the same verified point set.

The defensibility spine survives the format choice. The verbatim quote and its
citation always travel in a deterministic sources block, so an optional speech
composer can rewrite the connective prose but can never strip, edit or
fabricate the cited evidence. If no composer is supplied, the paragraph body is
a plain join of the verified point sentences.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from who_speech.verify import tidy_quote

if TYPE_CHECKING:
    from who_speech.swarm import BriefingPack

FORMATS = ("bullets", "paragraphs")

# A composer turns the verified point sentences into speech-style prose. It
# receives the list of point sentences and returns the connective body. It
# never sees or touches the quotes; those are appended deterministically.
Composer = Callable[[list[str]], str]


def _abstain_line(pack: "BriefingPack") -> str:
    note = pack.note or "no defensible points found"
    return f"No defensible points found for: {pack.query}\n({note})"


def _source_lines(pack: "BriefingPack") -> list[str]:
    lines: list[str] = []
    for p in pack.points:
        loc = f" (p.{p.page})" if p.page else ""
        lines.append(f'- "{tidy_quote(p.quote)}"\n  {p.citation}\n  {p.iris_url}{loc}')
    return lines


def render_bullets(pack: "BriefingPack") -> str:
    """One bullet per verified point: the point, its quote, its source."""
    if pack.abstained or not pack.points:
        return _abstain_line(pack)
    blocks: list[str] = []
    for p in pack.points:
        loc = f" (p.{p.page})" if p.page else ""
        blocks.append(
            f"- {p.point}\n"
            f'  "{tidy_quote(p.quote)}"\n'
            f"  {p.citation}\n"
            f"  {p.iris_url}{loc}"
        )
    return "\n".join(blocks)


def render_paragraphs(pack: "BriefingPack", composer: Optional[Composer] = None) -> str:
    """Speech-style prose body, followed by a verbatim sources block.

    With a composer, the body is composed prose; without one, it is a plain
    join of the point sentences. Either way the sources block below carries
    every verbatim quote and citation unchanged.
    """
    if pack.abstained or not pack.points:
        return _abstain_line(pack)
    sentences = [p.point for p in pack.points]
    body = composer(sentences) if composer else " ".join(sentences)
    sources = "\n".join(_source_lines(pack))
    return f"{body}\n\nSources\n{sources}"


def render(pack: "BriefingPack", fmt: str = "bullets", composer: Optional[Composer] = None) -> str:
    """Dispatch to the requested format. Raises ValueError on an unknown format."""
    if fmt == "bullets":
        return render_bullets(pack)
    if fmt == "paragraphs":
        return render_paragraphs(pack, composer=composer)
    raise ValueError(f"unknown format {fmt!r}; expected one of {FORMATS}")
