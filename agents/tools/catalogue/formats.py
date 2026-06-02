"""Format classification for Q27 (open and machine-readable formats).

Portals give a distribution's format as a plain token (`CSV`), an EU
file-type authority URI (`.../authority/file-type/CSV`), or a media type
(`text/csv`). This module normalises any of those to a token and checks
membership of the open and machine-readable set, which is data-driven in
`data/catalogue/open_formats.json`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
_OPEN_FORMATS_FILE = _REPO_ROOT / "data" / "catalogue" / "open_formats.json"

# Media-type tails mapped to canonical tokens. Only the cases that do not
# already fall out of the subtype are listed.
_MEDIA_TYPE_TOKEN = {
    "csv": "csv",
    "tab-separated-values": "tsv",
    "json": "json",
    "ld+json": "jsonld",
    "geo+json": "geojson",
    "xml": "xml",
    "rdf+xml": "rdf",
    "turtle": "ttl",
    "n-triples": "nt",
    "n3": "n3",
    "vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "vnd.oasis.opendocument.spreadsheet": "ods",
    "vnd.geo+json": "geojson",
    "vnd.google-earth.kml+xml": "kml",
    "gml+xml": "gml",
    "x-netcdf": "netcdf",
    "vnd.apache.parquet": "parquet",
    "geopackage+sqlite3": "gpkg",
}


@lru_cache(maxsize=1)
def _open_tokens() -> frozenset[str]:
    data = json.loads(_OPEN_FORMATS_FILE.read_text())
    return frozenset(t.lower() for t in data.get("open_machine_readable", []))


def normalise_format(fmt: Optional[str], media_type: Optional[str] = None) -> Optional[str]:
    """Reduce a format/media-type to a canonical lowercase token.

    Prefers the explicit format token; falls back to the media type.
    Strips EU file-type authority URIs to their last path segment.
    """
    token = _token_from_format(fmt)
    if token:
        return token
    return _token_from_media_type(media_type)


def _token_from_format(fmt: Optional[str]) -> Optional[str]:
    if not fmt:
        return None
    s = fmt.strip().lower()
    if not s:
        return None
    if "://" in s or "/" in s:
        # EU authority URI or a path; take the last meaningful segment.
        s = s.rstrip("/").rsplit("/", 1)[-1]
    # Drop a leading dot and surrounding noise.
    s = s.lstrip(".").strip()
    # Common spelling folds.
    if s in ("text/csv",):
        return "csv"
    s = s.replace("application/", "").replace("text/", "")
    folds = {
        "turtle": "ttl",
        "n-triples": "nt",
        "ntriples": "nt",
        "json-ld": "jsonld",
        "ld+json": "jsonld",
        "geo+json": "geojson",
        "rdf+xml": "rdf",
        "rdfxml": "rdf",
        "geopackage": "gpkg",
        "shapefile": "shp",
        "ms-excel": "xls",
        "x-spreadsheet": "xls",
    }
    return folds.get(s, s)


def _token_from_media_type(media_type: Optional[str]) -> Optional[str]:
    if not media_type:
        return None
    s = media_type.strip().lower()
    if "/" not in s:
        return _token_from_format(s)
    subtype = s.split("/", 1)[1]
    if subtype in _MEDIA_TYPE_TOKEN:
        return _MEDIA_TYPE_TOKEN[subtype]
    # Strip an "x-" vendor prefix and try again.
    subtype = subtype.removeprefix("x-")
    return _MEDIA_TYPE_TOKEN.get(subtype, subtype)


def is_open_machine_readable(
    fmt: Optional[str], media_type: Optional[str] = None
) -> bool:
    token = normalise_format(fmt, media_type)
    if not token:
        return False
    return token in _open_tokens()
