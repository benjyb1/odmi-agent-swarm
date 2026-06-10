"""Stack fingerprinting from public API signatures.

Each probe hits one or two well-known endpoints under the portal base and
returns `ProbeEvidence` when the response carries the stack's signature,
or None on a miss. Probes are deliberately cheap (one item per request)
and tolerate any HTTP or parse failure as "not this stack". The one
exception is `BlockedEndpointError`: a deny-list refusal is never treated
as a miss, it aborts the probe run, because a portal that redirects to
data.europa.eu must surface as a leakage event, not as "stack unknown".

Routes map to the existing adapters in `registry.ROUTES`. A probe that
recognises a stack with no adapter yet (OpenDataSoft, data.json, SPARQL,
FDK on this branch) reports `route=None`: the country is then flagged
"needs a new adapter" rather than silently failing.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import quote

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from agents.tools.catalogue import _fetch
from agents.tools.catalogue._fetch import BlockedEndpointError
from agents.tools.catalogue.registry import ROUTES

JsonFetcher = Callable[[str], dict]
BytesFetcher = Callable[..., bytes]
JsonPoster = Callable[[str, dict], dict]

_DCAT_DATASET = URIRef("http://www.w3.org/ns/dcat#Dataset")

# CKAN portals mount the Action API under these prefixes. "" is standard;
# "/data" is the data.overheid.nl pattern.
_CKAN_PREFIXES = ("", "/data")

_SPARQL_ASK = "ASK { ?s a <http://www.w3.org/ns/dcat#Dataset> }"


@dataclass
class ProbeEvidence:
    """One positive fingerprint: which stack answered, where, and the
    registry fields the match implies."""

    stack: str
    route: Optional[str]  # an entry of registry.ROUTES, or None
    endpoint: str         # the URL that answered
    detail: str           # what matched, for the receipt
    total_datasets: Optional[int] = None
    config_fields: dict = field(default_factory=dict)


def _safe(fn: Callable[[], Optional[ProbeEvidence]]) -> Optional[ProbeEvidence]:
    """Run one probe attempt; any failure except a deny-list refusal is a
    miss. The deny-list error must propagate (leakage is never a miss)."""
    try:
        return fn()
    except BlockedEndpointError:
        raise
    except Exception:  # noqa: BLE001 - 404s, timeouts, bad JSON are misses
        return None


def probe_ckan(
    base: str, *, fetch_json: JsonFetcher = _fetch.fetch_json
) -> Optional[ProbeEvidence]:
    """CKAN Action API: `package_search` returns `success` and a count."""
    for prefix in _CKAN_PREFIXES:
        api_base = f"{base}{prefix}/api/3/action/package_search"

        def attempt(api_base: str = api_base, prefix: str = prefix):
            payload = fetch_json(f"{api_base}?rows=1")
            if not isinstance(payload, dict) or payload.get("success") is not True:
                return None
            result = payload.get("result")
            if not isinstance(result, dict) or "count" not in result:
                return None
            return ProbeEvidence(
                stack="ckan",
                route="ckan_json",
                endpoint=f"{api_base}?rows=1",
                detail=(
                    f"package_search success=true, count={result['count']}"
                    + (f", prefix {prefix!r}" if prefix else "")
                ),
                total_datasets=int(result["count"]),
                config_fields={
                    "native_api_url": f"{api_base}?rows={{page_size}}&start={{start}}",
                    "pagination": "ckan_offset",
                    "page_size": 500,
                },
            )

        ev = _safe(attempt)
        if ev is not None:
            return ev
    return None


def probe_udata(
    base: str, *, fetch_json: JsonFetcher = _fetch.fetch_json
) -> Optional[ProbeEvidence]:
    """uData REST API: `/api/1/datasets/` returns `data` plus `total`."""
    url = f"{base}/api/1/datasets/?page_size=1"

    def attempt():
        payload = fetch_json(url)
        if not isinstance(payload, dict):
            return None
        if "data" not in payload or "total" not in payload:
            return None
        if not isinstance(payload["data"], list):
            return None
        return ProbeEvidence(
            stack="udata",
            route="udata_json",
            endpoint=url,
            detail=f"udata /api/1/datasets/ total={payload['total']}",
            total_datasets=int(payload["total"]),
            config_fields={
                "native_api_url": f"{base}/api/1/datasets/?page_size={{page_size}}&page={{page}}",
                "pagination": "udata_page",
                "page_size": 100,
            },
        )

    return _safe(attempt)


def _dcat_feed_candidates(base: str) -> list[tuple[str, str, str]]:
    """(probe_url, template, rdflib format) for the known feed shapes."""
    return [
        (f"{base}/catalog.ttl?page=1",
         f"{base}/catalog.ttl?page={{page}}", "turtle"),
        (f"{base}/catalog.xml?page=1",
         f"{base}/catalog.xml?page={{page}}", "xml"),
        (f"{base}/catalog.rdf?page=1",
         f"{base}/catalog.rdf?page={{page}}", "xml"),
        # udata first-party site catalogue (the FR pattern).
        (f"{base}/api/1/site/catalog.ttl?page=1&page_size=10",
         f"{base}/api/1/site/catalog.ttl?page={{page}}&page_size={{page_size}}",
         "turtle"),
    ]


def probe_dcat_feed(
    base: str, *, fetch_bytes: BytesFetcher = _fetch.fetch_bytes
) -> Optional[ProbeEvidence]:
    """A paged national DCAT-AP RDF feed that parses and carries at least
    one `dcat:Dataset`. An HTML shell or an empty graph is a miss."""
    for probe_url, template, rdf_format in _dcat_feed_candidates(base):

        def attempt(probe_url=probe_url, template=template, rdf_format=rdf_format):
            raw = fetch_bytes(probe_url)
            head = raw.lstrip()[:200].lower()
            if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
                return None
            g = Graph()
            g.parse(data=raw, format=rdf_format)
            n = sum(1 for _ in g.subjects(RDF.type, _DCAT_DATASET))
            if n == 0:
                return None
            return ProbeEvidence(
                stack="dcat_feed",
                route="dcat_rdf",
                endpoint=probe_url,
                detail=f"RDF feed parsed ({rdf_format}), {n} dcat:Dataset on page 1",
                config_fields={
                    "dcat_catalog_url": template,
                    "pagination": "hydra",
                    "page_size": 100,
                },
            )

        ev = _safe(attempt)
        if ev is not None:
            return ev
    return None


def probe_opendatasoft(
    base: str, *, fetch_json: JsonFetcher = _fetch.fetch_json
) -> Optional[ProbeEvidence]:
    """OpenDataSoft Explore API v2: `total_count` over catalog/datasets."""
    url = f"{base}/api/explore/v2.1/catalog/datasets?limit=1"

    def attempt():
        payload = fetch_json(url)
        if not isinstance(payload, dict) or "total_count" not in payload:
            return None
        return ProbeEvidence(
            stack="opendatasoft",
            route=None,  # no adapter yet
            endpoint=url,
            detail=f"ODS explore v2.1, total_count={payload['total_count']}",
            total_datasets=int(payload["total_count"]),
        )

    return _safe(attempt)


def probe_datajson(
    base: str, *, fetch_json: JsonFetcher = _fetch.fetch_json
) -> Optional[ProbeEvidence]:
    """Project Open Data / DKAN style `/data.json` catalogue dump."""
    url = f"{base}/data.json"

    def attempt():
        payload = fetch_json(url)
        if not isinstance(payload, dict):
            return None
        datasets = payload.get("dataset")
        if not isinstance(datasets, list) or not datasets:
            return None
        return ProbeEvidence(
            stack="datajson",
            route=None,  # no adapter yet
            endpoint=url,
            detail=f"data.json with {len(datasets)} datasets",
            total_datasets=len(datasets),
        )

    return _safe(attempt)


def probe_piveau(
    base: str, *, fetch_json: JsonFetcher = _fetch.fetch_json
) -> Optional[ProbeEvidence]:
    """piveau hub-search (the data.europa.eu software family, nationally
    hosted, e.g. data.gv.at since its relaunch): `result.count` over the
    dataset index. National piveau hubs can federate EU-scope datasets,
    so an eventual adapter must filter to the national scope."""
    url = f"{base}/api/hub/search/search?filters=dataset&limit=1"

    def attempt():
        payload = fetch_json(url)
        if not isinstance(payload, dict):
            return None
        result = payload.get("result")
        if not isinstance(result, dict) or result.get("index") != "dataset":
            return None
        if "count" not in result:
            return None
        return ProbeEvidence(
            stack="piveau",
            route=None,  # no adapter yet
            endpoint=url,
            detail=f"piveau hub-search, count={result['count']}",
            total_datasets=int(result["count"]),
        )

    return _safe(attempt)


def probe_sparql(
    base: str,
    *,
    hints: Optional[dict] = None,
    fetch_bytes: BytesFetcher = _fetch.fetch_bytes,
) -> Optional[ProbeEvidence]:
    """A SPARQL endpoint that answers ASK {?s a dcat:Dataset} with true.

    Some portals host the endpoint on a sibling domain (Sweden's
    EntryScape puts it on admin.dataportal.se), so a seed hint
    `sparql_endpoint` overrides the default `{base}/sparql` guess.

    Uses the bytes fetcher so the Accept header can negotiate
    `application/sparql-results+json`: Virtuoso endpoints (data.gov.cz)
    answer 406 to a plain `Accept: application/json`."""
    endpoint = (hints or {}).get("sparql_endpoint") or f"{base}/sparql"
    url = f"{endpoint}?query={quote(_SPARQL_ASK)}&format=json"

    def attempt():
        raw = fetch_bytes(url, accept="application/sparql-results+json")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("boolean") is not True:
            return None
        return ProbeEvidence(
            stack="sparql",
            route=None,  # no adapter yet
            endpoint=url,
            detail="SPARQL ASK dcat:Dataset returned true",
        )

    return _safe(attempt)


def probe_fdk(
    base: str,
    *,
    hints: Optional[dict] = None,
    post_json: JsonPoster = _fetch.post_json,
) -> Optional[ProbeEvidence]:
    """The FDK pattern (Norway): a POST search service enumerating dataset
    ids plus per-dataset RDF by content negotiation. The search-service
    host differs from the portal base, so this probe only fires when the
    seed carries the endpoints as hints; there is no generic signature to
    guess from the base URL alone."""
    if not hints or "fdk_search_api" not in hints:
        return None
    search_api = hints["fdk_search_api"]

    def attempt():
        payload = post_json(
            search_api, {"filters": {}, "pagination": {"page": 0, "size": 1}}
        )
        hits = payload.get("hits")
        total = (payload.get("page") or {}).get("totalElements")
        if not isinstance(hits, list) or total is None:
            return None
        return ProbeEvidence(
            stack="fdk",
            # Resolved dynamically: once the fdk_rdf adapter merges and joins
            # registry.ROUTES, discovery starts emitting it.
            route="fdk_rdf" if "fdk_rdf" in ROUTES else None,
            endpoint=search_api,
            detail=f"FDK search service, totalElements={total}",
            total_datasets=int(total),
            config_fields={
                "native_api_url": search_api,
                "dataset_detail_url": hints.get("fdk_dataset_detail_url"),
                "pagination": "fdk_search",
                "page_size": 1000,
            },
        )

    return _safe(attempt)


def probe_all(
    base: str,
    *,
    hints: Optional[dict] = None,
    fetch_json: JsonFetcher = _fetch.fetch_json,
    fetch_bytes: BytesFetcher = _fetch.fetch_bytes,
    post_json: JsonPoster = _fetch.post_json,
    delay_s: float = 1.0,
) -> list[ProbeEvidence]:
    """Run every probe against one portal base and collect the hits.

    Refuses a deny-listed base outright. Probes run in a fixed order with
    a politeness delay between them; all hits are returned so the route
    chooser can weigh RDF against JSON evidence (the HU/RO licence caveat
    needs both).
    """
    if _fetch.is_blocked(base):
        raise BlockedEndpointError(
            f"refusing to probe deny-listed portal base: {base}"
        )
    base = base.rstrip("/")

    attempts = [
        lambda: probe_dcat_feed(base, fetch_bytes=fetch_bytes),
        lambda: probe_ckan(base, fetch_json=fetch_json),
        lambda: probe_udata(base, fetch_json=fetch_json),
        lambda: probe_fdk(base, hints=hints, post_json=post_json),
        lambda: probe_opendatasoft(base, fetch_json=fetch_json),
        lambda: probe_piveau(base, fetch_json=fetch_json),
        lambda: probe_datajson(base, fetch_json=fetch_json),
        lambda: probe_sparql(base, hints=hints, fetch_bytes=fetch_bytes),
    ]
    found: list[ProbeEvidence] = []
    for i, attempt in enumerate(attempts):
        ev = attempt()
        if ev is not None:
            found.append(ev)
        if delay_s and i < len(attempts) - 1:
            time.sleep(delay_s)
    return found
