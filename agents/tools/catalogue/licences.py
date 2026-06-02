"""Licence canonicalisation for the catalogue metrics.

Portals express licences in heterogeneous ways: udata short codes
(`lov2`, `cc-by`), CKAN codes (`CC-BY-4.0`, `cc-nc`), DCAT-AP.de URIs
(`http://dcat-ap.de/def/licenses/dl-by-de/2.0`), Creative Commons URIs
(`http://creativecommons.org/licenses/by/4.0/deed.nl`), and Estonia's
enum (`CC_BY_4.0`). This module folds them onto a small set of canonical
families so the metrics can decide:

  - is this dataset licensed at all (Q12)?
  - how many distinct licences are in use (Q13)?
  - is the licence open under the Open Definition (Q25)?

The open-family list is data-driven (`data/catalogue/open_licences.json`)
so the openness judgement is auditable, not buried in code.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from agents.tools.catalogue.model import HarvestedDataset

_REPO_ROOT = Path(__file__).resolve().parents[3]
_OPEN_LICENCES_FILE = _REPO_ROOT / "data" / "catalogue" / "open_licences.json"

# Values that explicitly mean "no licence stated". Compared against the
# canonical family, so per-portal spellings collapse here.
_SENTINEL_FAMILIES = frozenset({"sentinel"})

# Raw tokens (after lowercasing) that signal "no licence". Matched as
# substrings so URI and code spellings both land here.
_SENTINEL_PATTERNS = (
    "notspecified",
    "licentieonbekend",
    "licence-unknown",
    "license-unknown",
    "unknown",
    "i don't know",
    "other-at",
    "other-open",
    "other-pd",
)

# Ordered family detectors: first match wins. Order matters, e.g. the
# non-commercial / no-derivatives CC variants must be tested before plain
# cc-by so a CC-BY-NC is not mistaken for an open CC-BY.
_FAMILY_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"pddl|publicdomain/zero|cc[-_]?0|cc[-_]?zero"), "cc0"),
    (re.compile(r"publicdomain/mark|public-?domain|/pdm|\bpd\b|other-pd"), "pd"),
    (re.compile(r"by-?nc-?sa|by_nc_sa"), "cc-by-nc-sa"),
    (re.compile(r"by-?nc-?nd|by_nc_nd"), "cc-by-nc-nd"),
    (re.compile(r"by-?nd|by_nd"), "cc-by-nd"),
    (re.compile(r"by-?nc|by_nc|cc-?nc"), "cc-by-nc"),
    (re.compile(r"odbl|odc-?odbl|opendatabase"), "odbl"),
    (re.compile(r"odc-?by"), "odc-by"),
    (re.compile(r"by-?sa|by_sa"), "cc-by-sa"),
    (re.compile(r"dl-?by-?de|dl-?de/?by|datenlizenz.*namensnennung"), "dl-de-by"),
    (re.compile(r"dl-?zero-?de|dl-?de/?zero|dl-?de-?0"), "dl-de-zero"),
    (re.compile(r"etalab|licence-?ouverte|open-?licence|open licence|lov2|fr-?lo"), "etalab"),
    (re.compile(r"\bogl\b|ogl-?rou|open-?government-?licence|open government licence"), "ogl"),
    (re.compile(r"creativecommons.*\bby\b|cc-?by|cc_?by"), "cc-by"),
)

_VERSION_RE = re.compile(r"(\d+\.\d+|\d+)")


@lru_cache(maxsize=1)
def _open_families() -> frozenset[str]:
    data = json.loads(_OPEN_LICENCES_FILE.read_text())
    return frozenset(data.get("open_families", []))


def is_sentinel_raw(raw: str) -> bool:
    s = (raw or "").strip().lower()
    if not s:
        return True
    return any(pat in s for pat in _SENTINEL_PATTERNS)


def licence_family(raw: str) -> Optional[str]:
    """Map a raw licence value to a canonical family, or None if empty.

    Returns "sentinel" for values that mean "no licence stated".
    Returns "other" for a non-empty value we do not recognise (still a
    real licence for Q12/Q13, just not classifiable as open).
    """
    if raw is None:
        return None
    s = raw.strip().lower()
    if not s:
        return None
    if is_sentinel_raw(s):
        return "sentinel"
    for pattern, family in _FAMILY_RULES:
        if pattern.search(s):
            return family
    return "other"


def canonical_licence(raw: str) -> Optional[str]:
    """A compact, version-aware licence id for the distinct-count metric.

    e.g. `http://creativecommons.org/licenses/by/4.0/deed.nl` -> `cc-by-4.0`,
    `CC_BY_SA_3.0` -> `cc-by-sa-3.0`, `lov2` -> `etalab-2`. Returns the
    family alone when no version is present, "sentinel" for no-licence
    values, and None for empty input.
    """
    family = licence_family(raw)
    if family is None or family in ("sentinel",):
        return family
    version_match = _VERSION_RE.search(raw or "")
    if version_match and family != "other":
        return f"{family}-{version_match.group(1)}"
    if family == "other":
        # Keep the cleaned raw so distinct unknown licences stay distinct.
        return "other:" + re.sub(r"\s+", " ", (raw or "").strip().lower())
    return family


def is_sentinel(canonical: Optional[str]) -> bool:
    if canonical is None:
        return True
    return canonical in _SENTINEL_FAMILIES or canonical == "sentinel"


def is_open_licence(raw: str) -> bool:
    """True if the raw licence maps to an open family (Open Definition)."""
    return licence_family(raw) in _open_families()


# ------------------------------------------------------------------
# Dataset-level decisions used by the metrics.
# ------------------------------------------------------------------


def dataset_is_licensed(dataset: HarvestedDataset) -> bool:
    """A dataset is licensed if any of its licence values is a real
    licence (not a no-licence sentinel and not empty)."""
    for raw in dataset.all_licences():
        if not is_sentinel_raw(raw):
            return True
    return False


def dataset_is_open(dataset: HarvestedDataset) -> bool:
    """A dataset is open-licensed if any of its licence values maps to an
    open family."""
    for raw in dataset.all_licences():
        if is_open_licence(raw):
            return True
    return False


def distinct_licence_keys(datasets) -> set[str]:
    """Distinct canonical licence ids across the catalogue (Q13).

    Sentinels and empties are excluded: a portal that records "licence
    unknown" everywhere is not using a licence."""
    keys: set[str] = set()
    for d in datasets:
        for raw in d.all_licences():
            c = canonical_licence(raw)
            if c and not is_sentinel(c):
                keys.add(c)
    return keys
