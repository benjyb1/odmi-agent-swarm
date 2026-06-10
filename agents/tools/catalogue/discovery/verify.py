"""Route selection and sample verification with caveat auto-detection.

Given the probe evidence for one portal, pick the best harvest route the
existing adapters can serve, verify it by harvesting a small sample, and
record the known caveats the sample exposes:

- The HU/RO pattern: a portal's DCAT-AP RDF feed parses but omits
  `dct:license`, so the licence metrics would read ~0% through RDF. When
  a JSON route also exists and does carry licences, the JSON route wins
  and the RDF omission is recorded as a caveat.
- The FDK pattern: a feed that never emits `dcat:downloadURL`, so Q21
  reads near 0% faithfully to the feed. Recorded, not "fixed".
- JSON routes carry the standing caveat that DCAT-AP conformance
  (Q16/Q17/Q18) is computed over graphs synthesised from JSON.

Route preference is RDF first (real graphs for the conformance metrics),
then CKAN JSON, then uData JSON, then FDK. A stack recognised without an
adapter (`route=None`) makes the country `needs_new_adapter` rather than
`failed`, so the gap is visible and priced, never silent.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Callable, Optional

from agents.tools.catalogue.discovery.probes import ProbeEvidence
from agents.tools.catalogue.model import HarvestedDataset
from agents.tools.catalogue.registry import PortalConfig

# Preference order among routes the adapters can already serve. RDF
# sources first (real graphs for the conformance metrics): a paged feed,
# then a SPARQL endpoint, then the JSON fallbacks.
_ROUTE_PREFERENCE = (
    "dcat_rdf", "sparql_rdf", "ckan_json", "udata_json", "piveau_json",
    "fdk_rdf",
)

# A verification sample must yield at least this many datasets.
_MIN_SAMPLE = 1

# Sampler signature: (route, candidate config) -> harvested datasets.
Sampler = Callable[[str, PortalConfig], list[HarvestedDataset]]


@dataclass
class SampleStats:
    n_datasets: int
    licence_share: float        # datasets with >=1 non-empty licence value
    with_distributions: int
    download_url_share: float   # of datasets that have distributions
    access_url_share: float
    format_share: float
    # Which level the licences live at, for the registry's licence_field.
    dataset_licence_share: float = 0.0
    distribution_licence_share: float = 0.0


@dataclass
class VerifiedRoute:
    route: str
    evidence: ProbeEvidence
    stats: SampleStats
    caveats: list[str] = field(default_factory=list)


@dataclass
class RejectedRoute:
    route: str
    reason: str


@dataclass
class DiscoveryOutcome:
    country_code: str
    country_name: str
    portal_base: str
    status: str  # "verified" | "needs_new_adapter" | "failed"
    chosen: Optional[VerifiedRoute] = None
    rejected: list[RejectedRoute] = field(default_factory=list)
    new_stacks: list[str] = field(default_factory=list)
    error: Optional[str] = None


def sample_stats(datasets: list[HarvestedDataset]) -> SampleStats:
    n = len(datasets)
    if n == 0:
        return SampleStats(0, 0.0, 0, 0.0, 0.0, 0.0)
    licensed = sum(1 for d in datasets if d.all_licences())
    ds_licensed = sum(
        1 for d in datasets if any(l and l.strip() for l in d.dataset_licences)
    )
    dist_licensed = sum(
        1 for d in datasets
        if any(x.licence and x.licence.strip() for x in d.distributions)
    )
    with_dist = [d for d in datasets if d.has_distributions()]
    nd = len(with_dist)

    def _share(pred) -> float:
        if nd == 0:
            return 0.0
        return sum(1 for d in with_dist if pred(d)) / nd

    return SampleStats(
        n_datasets=n,
        licence_share=licensed / n,
        with_distributions=nd,
        download_url_share=_share(
            lambda d: any(x.download_url for x in d.distributions)
        ),
        access_url_share=_share(
            lambda d: any(x.access_url for x in d.distributions)
        ),
        format_share=_share(
            lambda d: any(x.fmt or x.media_type for x in d.distributions)
        ),
        dataset_licence_share=ds_licensed / n,
        distribution_licence_share=dist_licensed / n,
    )


def build_candidate_config(
    country_code: str,
    country_name: str,
    portal_base: str,
    evidence: ProbeEvidence,
) -> PortalConfig:
    """A provisional PortalConfig for sampling, built from probe evidence.

    The licence_field default is "dataset"; the emitter may override it
    from the sample (DE-style distribution-level licences).
    """
    cf = evidence.config_fields
    return PortalConfig(
        country_code=country_code.upper(),
        country_name=country_name,
        portal_base=portal_base,
        stack=evidence.stack,
        harvest_route=evidence.route or "",
        pagination=cf.get("pagination", ""),
        page_size=int(cf.get("page_size", 100)),
        request_delay_s=1.0,
        licence_field="dataset",
        dcat_catalog_url=cf.get("dcat_catalog_url"),
        native_api_url=cf.get("native_api_url"),
        dataset_detail_url=cf.get("dataset_detail_url"),
        total_datasets_hint=evidence.total_datasets,
    )


def _has_class_as_predicate(sample: list[HarvestedDataset]) -> bool:
    """True when dataset graphs carry `dcat:Distribution` (the class) as a
    predicate: a producer bug that hides every distribution from any
    spec-conformant reader, ours included."""
    from rdflib import URIRef

    wrong = URIRef("http://www.w3.org/ns/dcat#Distribution")
    for d in sample:
        if d.graph is not None and (None, wrong, None) in d.graph:
            return True
    return False


def _verify_one(
    route: str,
    evidence: ProbeEvidence,
    config: PortalConfig,
    sampler: Sampler,
) -> tuple[Optional[VerifiedRoute], Optional[RejectedRoute]]:
    try:
        sample = sampler(route, config)
    except Exception as exc:  # noqa: BLE001 - a broken route is a rejection
        return None, RejectedRoute(route, f"sample harvest raised {type(exc).__name__}: {exc}"[:200])
    stats = sample_stats(sample)
    if stats.n_datasets < _MIN_SAMPLE:
        return None, RejectedRoute(route, "sample harvest yielded no datasets")
    if stats.with_distributions == 0:
        reason = "sample has no distributions; the distribution metrics cannot run"
        if _has_class_as_predicate(sample):
            reason += (
                " (malformed feed: dcat:Distribution used as a predicate, the"
                " class-as-property producer bug seen on data.gov.cy)"
            )
        return None, RejectedRoute(route, reason)
    caveats: list[str] = []
    if route in ("ckan_json", "udata_json", "estonia_json", "piveau_json"):
        caveats.append("conformance_synthesised_from_json")
    if stats.download_url_share == 0.0:
        caveats.append("feed_omits_download_url")
    return VerifiedRoute(route, evidence, stats, caveats), None


def choose_and_verify(
    country_code: str,
    country_name: str,
    portal_base: str,
    evidence_list: list[ProbeEvidence],
    *,
    sampler: Optional[Sampler],
) -> DiscoveryOutcome:
    """Pick and verify the best route from the probe evidence.

    RDF is preferred, but is demoted below an available JSON route when
    its sample carries no licence values at all (the HU/RO pattern). All
    decisions, rejections and caveats are recorded in the outcome.
    """
    out = DiscoveryOutcome(
        country_code=country_code.upper(),
        country_name=country_name,
        portal_base=portal_base,
        status="failed",
    )
    routable = [e for e in evidence_list if e.route]
    out.new_stacks = sorted({e.stack for e in evidence_list if e.route is None})

    if not routable:
        out.status = "needs_new_adapter" if out.new_stacks else "failed"
        if out.status == "failed":
            out.error = "no stack fingerprint matched"
        return out
    if sampler is None:
        raise ValueError("a sampler is required when routable evidence exists")

    by_route = {e.route: e for e in routable}
    ordered = [r for r in _ROUTE_PREFERENCE if r in by_route]

    verified: dict[str, VerifiedRoute] = {}
    for route in ordered:
        ev = by_route[route]
        config = build_candidate_config(
            country_code, country_name, portal_base, ev
        )
        ok, rejected = _verify_one(route, ev, config, sampler)
        if rejected is not None:
            out.rejected.append(rejected)
            continue
        verified[route] = ok
        # The RDF route only needs a JSON comparison when it lacks licences;
        # otherwise the first verified route in preference order wins.
        if ok.stats.licence_share > 0.0:
            break

    if not verified:
        out.status = "failed"
        out.error = "every routable candidate failed sample verification"
        return out

    chosen: Optional[VerifiedRoute] = None
    for route in ordered:
        vr = verified.get(route)
        if vr is None:
            continue
        if vr.stats.licence_share > 0.0:
            chosen = vr
            break
        if route == "dcat_rdf":
            # The HU/RO pattern: prefer a JSON route that does carry licences.
            json_with_licence = next(
                (
                    verified[r] for r in ordered
                    if r != "dcat_rdf"
                    and r in verified
                    and verified[r].stats.licence_share > 0.0
                ),
                None,
            )
            if json_with_licence is not None:
                json_with_licence.caveats.insert(0, "rdf_feed_omits_dct_license")
                chosen = json_with_licence
                break
        # No licences anywhere: keep the preferred route, flag it.
        chosen = vr
        chosen.caveats.append("no_licence_metadata_on_any_route")
        break

    out.chosen = chosen
    out.status = "verified"
    return out


def live_sampler(*, max_pages: int = 1) -> Sampler:
    """The real sampler: one page through the route's adapter."""

    def _sample(route: str, config: PortalConfig) -> list[HarvestedDataset]:
        cfg = dataclasses.replace(config, harvest_route=route)
        if route == "dcat_rdf":
            from agents.tools.catalogue.adapters import dcat_rdf
            return list(dcat_rdf.harvest(cfg, max_pages=max_pages))
        if route == "ckan_json":
            from agents.tools.catalogue.adapters import ckan_json
            return list(ckan_json.harvest(cfg, max_pages=max_pages))
        if route == "udata_json":
            from agents.tools.catalogue.adapters import udata_json
            return list(udata_json.harvest(cfg, max_pages=max_pages))
        if route == "sparql_rdf":
            from agents.tools.catalogue.adapters import sparql_rdf
            return list(sparql_rdf.harvest(cfg, max_pages=max_pages))
        if route == "piveau_json":
            from agents.tools.catalogue.adapters import piveau_json
            return list(piveau_json.harvest(cfg, max_pages=max_pages))
        if route == "fdk_rdf":
            from agents.tools.catalogue.adapters import fdk_rdf  # type: ignore[attr-defined]
            return list(fdk_rdf.harvest(cfg, max_pages=max_pages))
        raise ValueError(f"no sampler for route {route!r}")

    return _sample
