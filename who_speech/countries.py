"""Resolve a common country name to its exact IRIS MeSH geographic heading.

IRIS faceting is exact-match on the MeSH heading (``f.mesh=<heading>,equals``),
so a heading that differs from the everyday country name must be spelled the
MeSH way or the country slice comes back empty. This map holds the headings
known to differ; every other name passes through unchanged.

The map is deliberately conservative: only entries verified against the live
IRIS facet are listed. Extend it as more EURO members are covered, checking
each against ``/server/api/discover/facets/mesh`` rather than guessing. Belarus
is split across two headings in IRIS and needs handling beyond a single
string; it is left to pass through for now.
"""
from __future__ import annotations

# common-name (case/whitespace-normalised) -> exact MeSH geographic heading.
_MESH_OVERRIDES: dict[str, str] = {
    "north macedonia": "Republic of North Macedonia",
    "republic of north macedonia": "Republic of North Macedonia",
    # Plain "Georgia" in MeSH is the US state; the country is "Georgia (Republic)".
    "georgia": "Georgia (Republic)",
    "georgia (republic)": "Georgia (Republic)",
}


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


def resolve_country(name: str) -> str:
    """Return the MeSH heading for a country name, or the name itself if unmapped."""
    return _MESH_OVERRIDES.get(_norm(name), name.strip())


def mapped_countries() -> dict[str, str]:
    """The known overrides, for surfacing in docs and the refresh CLI."""
    return dict(_MESH_OVERRIDES)
