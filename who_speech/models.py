"""Provenance-rich data models for the WHO speech-writer PoC.

Distinct from the ODMI swarm's web-oriented SearchResult: every passage here
carries its document, bitstream, page and character span, so a quoted claim
can be hash-gated back to a frozen source. The licence travels with the item
so the quote gate can refuse non-CC sources.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from who_speech import config


class Bitstream(BaseModel):
    """A single downloadable file (we keep only ORIGINAL-bundle PDFs)."""

    uuid: str
    name: str
    size_bytes: Optional[int] = None
    content_url: str


class IrisItem(BaseModel):
    """An IRIS repository item, parsed from the DSpace search index."""

    uuid: str
    handle: Optional[str] = None
    title: str
    year: Optional[int] = None
    language: Optional[str] = None
    item_type: Optional[str] = None
    rights: Optional[str] = None
    rights_uri: Optional[str] = None
    mesh: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    abstract: Optional[str] = None
    pdf_bitstreams: list[Bitstream] = Field(default_factory=list)

    @property
    def iris_url(self) -> Optional[str]:
        if not self.handle:
            return None
        return config.IRIS_HANDLE_URL.format(handle=self.handle)

    @property
    def quotable(self) -> bool:
        """True if the item carries a permissive CC licence we may quote."""
        rights = (self.rights or "").upper()
        return any(marker.upper() in rights for marker in config.QUOTABLE_LICENCE_MARKERS)

    def citation(self) -> str:
        """WHO-format attribution line for a quoted passage."""
        year = self.year or "n.d."
        licence = self.rights or "rights unspecified"
        return f"{self.title}. World Health Organization; {year}. Licence: {licence}"
