"""Source domain trust check.

Per Q10 in SPEC.md, trusted-domain lists live at
`data/trusted_domains/<country>.json`. For Phase A the file may not
exist yet; this module falls back to a small built-in seed list so
the Researcher can start producing rows.

The validator returns a score in [0.0, 1.0]:
- 1.0 for an explicit trusted domain
- 0.6 for a clearly authoritative-looking domain (e.g. .gov, .gouv, .europa.eu)
- 0.3 for any other domain
- 0.0 for malformed URLs

The score is passed to the Verifier; it is not a gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse


_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "trusted_domains"

# Seed list for Phase A France. Expand per country via the JSON files
# in `data/trusted_domains/` as the project progresses.
_DEFAULT_TRUSTED = {
    "FR": [
        "data.gouv.fr",
        "etalab.gouv.fr",
        "legifrance.gouv.fr",
        "service-public.fr",
        "data.europa.eu",
        "digital-strategy.ec.europa.eu",
        "interoperable-europe.ec.europa.eu",
    ],
    "EU": [
        "data.europa.eu",
        "digital-strategy.ec.europa.eu",
        "europa.eu",
        "ec.europa.eu",
    ],
}


def _load_country_list(country_code: str) -> list[str]:
    file = _DATA_DIR / f"{country_code}.json"
    if file.exists():
        try:
            data = json.loads(file.read_text())
            return [d.lower() for d in data.get("trusted", [])]
        except (json.JSONDecodeError, OSError):
            pass
    return [d.lower() for d in _DEFAULT_TRUSTED.get(country_code, [])]


def _looks_authoritative(domain: str) -> bool:
    """Heuristic: government, EU institution, or known portal patterns."""
    domain = domain.lower()
    return (
        ".gov" in domain
        or ".gouv." in domain
        or domain.endswith(".gouv.fr")
        or domain.endswith(".europa.eu")
        or domain.endswith(".ec.europa.eu")
        or domain.endswith(".gov.uk")
    )


def trust_score(url: str, *, country_code: str) -> float:
    """Return a 0.0-1.0 trust score for the URL's domain."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        host = host.lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return 0.0

    if not host:
        return 0.0

    trusted = _load_country_list(country_code)
    eu_trusted = _load_country_list("EU")

    if host in trusted or host in eu_trusted:
        return 1.0
    if any(host.endswith("." + t) or host == t for t in trusted + eu_trusted):
        return 1.0
    if _looks_authoritative(host):
        return 0.6
    return 0.3
