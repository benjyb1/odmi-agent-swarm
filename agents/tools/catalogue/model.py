"""Normalised harvest records shared by every adapter and metric.

Adapters map their native shape (udata JSON, CKAN JSON, custom JSON, or
DCAT-AP RDF) onto these dataclasses. The metric functions only ever see
the normalised model, so a metric is written once and runs against any
portal.

These are plain dataclasses, not Pydantic, because a `HarvestedDataset`
can carry an `rdflib.Graph` (for the SHACL conformance metrics) which does
not round-trip through Pydantic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from rdflib import Graph


@dataclass
class Distribution:
    """One distribution (resource) of a dataset.

    Every field is optional because portals vary in what they expose. A
    field left None means "not present in the harvested metadata", which
    is exactly the signal the presence metrics count.
    """

    licence: Optional[str] = None       # raw licence id/URI as harvested
    fmt: Optional[str] = None           # format token or EU file-type URI
    media_type: Optional[str] = None    # IANA media type if given separately
    access_url: Optional[str] = None    # dcat:accessURL
    download_url: Optional[str] = None  # dcat:downloadURL


@dataclass
class HarvestedDataset:
    """One dataset's normalised metadata.

    `dataset_licences` holds licence values declared at the dataset level
    (CKAN `license_id`, udata `license`). Distribution-level licences live
    on each `Distribution`. The "is this dataset licensed" decision (which
    level to trust, which sentinels mean "none") lives in the licence
    helpers, not here, so it is documented and tested in one place.
    """

    identifier: str
    dataset_licences: list[str] = field(default_factory=list)
    distributions: list[Distribution] = field(default_factory=list)
    # Per-dataset DCAT-AP graph, populated by the RDF route (or synthesised
    # from JSON for NL/EE). None on the plain-JSON presence path.
    graph: Optional["Graph"] = None
    source_route: str = ""
    # Optional reference to a dataset-level identifier URI, for the flagged
    # Q28 metric. Kept even though Q28 is not built in v1.
    identifier_uri: Optional[str] = None
    # Spare DCAT-relevant fields captured by the JSON adapters (title,
    # description, publisher, keywords, themes, ...). The RDF route leaves
    # this empty because it carries a real `graph`. `synthesise.py` reads
    # `extras` to build a DCAT-AP graph for NL/EE conformance.
    extras: dict = field(default_factory=dict)

    def all_licences(self) -> set[str]:
        """Every non-empty raw licence string seen, dataset or distribution.

        Whitespace-stripped; empties dropped. Sentinel filtering ("this
        means no licence") is the caller's job via the licence helpers.
        """
        out: set[str] = set()
        for lic in self.dataset_licences:
            if lic and lic.strip():
                out.add(lic.strip())
        for dist in self.distributions:
            if dist.licence and dist.licence.strip():
                out.add(dist.licence.strip())
        return out

    def has_distributions(self) -> bool:
        return len(self.distributions) > 0
