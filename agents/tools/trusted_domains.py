"""Trusted-domain registry per country.

For each ODMI country we list the authoritative web sources that
deserve preference: the national open-data portal, the relevant
ministry, the EU-level reference, and a small set of statistics or
legal-archive domains. The Researcher passes these to the search
wrapper as `include_domains` to focus results on sources we already
trust.

Drop a new JSON file under `data/trusted_domains/<cc>.json` to extend
coverage. Shape:

    {
      "country_code": "FR",
      "country_name": "France",
      "portal_url": "https://www.data.gouv.fr/",
      "trusted_domains": [
        "data.gouv.fr",
        "www.data.gouv.fr",
        ...
      ],
      "notes": "Anything an examiner should know."
    }
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DIR = _REPO_ROOT / "data" / "trusted_domains"


@lru_cache(maxsize=64)
def _load_country(country_code: str) -> Optional[dict]:
    """Read the trusted-domain JSON for a country, return None if missing."""
    path = _DIR / f"{country_code.upper()}.json"
    if not path.exists():
        path = _DIR / f"{country_code.lower()}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001 - best-effort
        return None


def trusted_domains_for(country_code: str) -> List[str]:
    """Return the trusted-domain list for a country, or [] if no file."""
    data = _load_country(country_code)
    if not data:
        return []
    raw = data.get("trusted_domains") or []
    return [d.strip().lower() for d in raw if d.strip()]


def portal_url_for(country_code: str) -> Optional[str]:
    data = _load_country(country_code)
    if not data:
        return None
    url = data.get("portal_url")
    return url or None
