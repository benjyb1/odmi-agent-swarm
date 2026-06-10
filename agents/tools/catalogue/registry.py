"""Per-country portal registry.

Loads `data/catalogue/portals/<CC>.json`, the verified endpoints for each
national open data portal (see discovery in SPEC D30). One `PortalConfig`
per country drives the right adapter and pagination style.

Drop a new JSON file under `data/catalogue/portals/` to add a country.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DIR = _REPO_ROOT / "data" / "catalogue" / "portals"

# Harvest routes. `dcat_rdf` is the common path; the JSON routes are for
# portals without a national RDF feed (NL, EE) or as a fallback;
# `sparql_rdf` covers portals whose DCAT graph sits behind a SPARQL
# endpoint only (CZ, HR, SE).
ROUTES = (
    "dcat_rdf", "ckan_json", "udata_json", "estonia_json", "sparql_rdf",
    "piveau_json",
)


@dataclass(frozen=True)
class PortalConfig:
    country_code: str
    country_name: str
    portal_base: str
    stack: str
    harvest_route: str
    pagination: str
    page_size: int
    request_delay_s: float
    licence_field: str
    dcat_catalog_url: Optional[str] = None
    native_api_url: Optional[str] = None
    dataset_detail_url: Optional[str] = None
    total_datasets_hint: Optional[int] = None
    stack_version: Optional[str] = None
    robots_note: str = ""
    verified_at: str = ""
    notes: str = ""


@lru_cache(maxsize=64)
def load_portal(country_code: str) -> PortalConfig:
    """Read the portal config for a country. Raises if the file is missing."""
    cc = country_code.upper()
    path = _DIR / f"{cc}.json"
    if not path.exists():
        raise KeyError(
            f"No portal registry for {cc!r} at {path}. "
            f"Add a data/catalogue/portals/{cc}.json file."
        )
    data = json.loads(path.read_text())
    route = data.get("harvest_route")
    if route not in ROUTES:
        raise ValueError(
            f"{cc}: harvest_route {route!r} not one of {ROUTES}"
        )
    return PortalConfig(
        country_code=data["country_code"],
        country_name=data["country_name"],
        portal_base=data["portal_base"],
        stack=data["stack"],
        harvest_route=route,
        pagination=data["pagination"],
        page_size=int(data["page_size"]),
        request_delay_s=float(data.get("request_delay_s", 1.0)),
        licence_field=data.get("licence_field", "dataset"),
        dcat_catalog_url=data.get("dcat_catalog_url"),
        native_api_url=data.get("native_api_url"),
        dataset_detail_url=data.get("dataset_detail_url"),
        total_datasets_hint=data.get("total_datasets_hint"),
        stack_version=data.get("stack_version"),
        robots_note=data.get("robots_note", ""),
        verified_at=data.get("verified_at", ""),
        notes=data.get("notes", ""),
    )


def available_countries() -> list[str]:
    """List the country codes that have a registry file."""
    if not _DIR.exists():
        return []
    return sorted(p.stem for p in _DIR.glob("*.json"))
