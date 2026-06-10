"""The committed, human-verified seed list of national portal base URLs.

`data/catalogue/portal_seeds.json` holds one entry per ODMI-assessed
country. The list is treated as public infrastructure metadata under the
D24 rule: it was compiled without consulting the EU aggregator, every
entry carries a `source` annotation saying how the URL was found, and the
loader refuses any entry that lands on the deny-list. Probing the seeds
live is what turns "publicly known domain" into "verified endpoint".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agents.tools.blocked_domains import blocked_reason, is_blocked
from agents.tools.catalogue._fetch import BlockedEndpointError

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SEEDS_PATH = _REPO_ROOT / "data" / "catalogue" / "portal_seeds.json"


@dataclass(frozen=True)
class Seed:
    country_code: str
    country_name: str
    portal_base: str
    source: str                 # how this URL was found, for the receipt
    alternates: tuple[str, ...] = ()
    hints: dict = field(default_factory=dict)  # e.g. the FDK endpoints
    notes: str = ""


def load_seeds(path: Optional[Path] = None) -> list[Seed]:
    """Load and validate the seed list. Raises on any deny-listed URL."""
    path = path or DEFAULT_SEEDS_PATH
    data = json.loads(path.read_text())
    seeds: list[Seed] = []
    for entry in data["seeds"]:
        seed = Seed(
            country_code=entry["country_code"].upper(),
            country_name=entry["country_name"],
            portal_base=entry["portal_base"].rstrip("/"),
            source=entry["source"],
            alternates=tuple(u.rstrip("/") for u in entry.get("alternates", [])),
            hints=entry.get("hints", {}),
            notes=entry.get("notes", ""),
        )
        for url in (seed.portal_base, *seed.alternates, *(
            v for v in seed.hints.values() if isinstance(v, str) and "://" in v
        )):
            if is_blocked(url):
                raise BlockedEndpointError(
                    f"seed {seed.country_code} carries a deny-listed URL "
                    f"({blocked_reason(url)}): {url}"
                )
        seeds.append(seed)
    return seeds
