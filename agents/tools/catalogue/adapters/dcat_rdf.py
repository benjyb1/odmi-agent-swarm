"""DCAT-AP RDF feed adapter (FR, DE, RO, HU).

The common path. Pages the portal's `catalog.{ttl,xml}` Hydra-paged feed,
parses each page with rdflib, and splits it into one bounded-description
graph per `dcat:Dataset`. That graph powers both the presence metrics
(licence, formats, URLs read off the triples) and the SHACL conformance
metrics (Q16/Q17/Q18).

The raw page is re-serialised to Turtle before caching so the replay path
parses a single format regardless of whether the portal served Turtle
(FR, DE) or RDF/XML (RO, HU).
"""

from __future__ import annotations

import time
from typing import Callable, Iterator, Optional

from rdflib import BNode, Graph, URIRef
from rdflib.namespace import RDF

from agents.tools.catalogue._fetch import fetch_bytes
from agents.tools.catalogue.model import Distribution, HarvestedDataset
from agents.tools.catalogue.registry import PortalConfig

DCAT = URIRef("http://www.w3.org/ns/dcat#")
_DCAT = "http://www.w3.org/ns/dcat#"
_DCT = "http://purl.org/dc/terms/"

DCAT_DATASET = URIRef(_DCAT + "Dataset")
DCAT_DISTRIBUTION = URIRef(_DCAT + "distribution")
DCT_LICENSE = URIRef(_DCT + "license")
DCT_FORMAT = URIRef(_DCT + "format")
DCAT_MEDIATYPE = URIRef(_DCAT + "mediaType")
DCAT_ACCESS_URL = URIRef(_DCAT + "accessURL")
DCAT_DOWNLOAD_URL = URIRef(_DCAT + "downloadURL")
DCT_IDENTIFIER = URIRef(_DCT + "identifier")

BytesFetcher = Callable[[str], bytes]
RawPageSink = Callable[[int, bytes], None]


def _rdf_format_for(url: str) -> str:
    u = url.lower()
    if ".ttl" in u:
        return "turtle"
    if ".jsonld" in u:
        return "json-ld"
    return "xml"  # .xml / .rdf


def _extract_dataset_graph(page: Graph, dataset: URIRef) -> Graph:
    """Bounded description of one dataset: its triples plus those of the
    blank nodes and local non-Dataset resources it references (one
    component), so a Distribution's own triples travel with it. Stops at
    other dcat:Dataset nodes so datasets do not bleed into each other.
    """
    out = Graph()
    seen: set = set()
    queue: list = [dataset]
    while queue:
        node = queue.pop()
        if node in seen:
            continue
        seen.add(node)
        for p, o in page.predicate_objects(node):
            out.add((node, p, o))
            follow = isinstance(o, BNode) or (
                isinstance(o, URIRef)
                and (o, None, None) in page
                and (o, RDF.type, DCAT_DATASET) not in page
            )
            if follow and o not in seen:
                queue.append(o)
    return out


def _normalise_dataset(graph: Graph, dataset: URIRef) -> HarvestedDataset:
    dataset_licences = [str(o) for o in graph.objects(dataset, DCT_LICENSE)]

    distributions: list[Distribution] = []
    for dist in graph.objects(dataset, DCAT_DISTRIBUTION):
        lic = next(graph.objects(dist, DCT_LICENSE), None)
        fmt = next(graph.objects(dist, DCT_FORMAT), None)
        mt = next(graph.objects(dist, DCAT_MEDIATYPE), None)
        au = next(graph.objects(dist, DCAT_ACCESS_URL), None)
        du = next(graph.objects(dist, DCAT_DOWNLOAD_URL), None)
        distributions.append(
            Distribution(
                licence=str(lic) if lic is not None else None,
                fmt=str(fmt) if fmt is not None else None,
                media_type=str(mt) if mt is not None else None,
                access_url=str(au) if au is not None else None,
                download_url=str(du) if du is not None else None,
            )
        )

    ident = str(dataset)
    return HarvestedDataset(
        identifier=ident,
        dataset_licences=dataset_licences,
        distributions=distributions,
        graph=graph,
        source_route="dcat_rdf",
        identifier_uri=ident if ident.startswith("http") else None,
    )


def _split_page(page: Graph) -> list[HarvestedDataset]:
    out: list[HarvestedDataset] = []
    for ds in page.subjects(RDF.type, DCAT_DATASET):
        sub = _extract_dataset_graph(page, ds)
        out.append(_normalise_dataset(sub, ds))
    return out


def normalise_page(payload, *, route: str = "dcat_rdf") -> list[HarvestedDataset]:
    """Replay a cached Turtle page into datasets with graphs."""
    page = Graph()
    if isinstance(payload, (bytes, bytearray)):
        page.parse(data=payload, format="turtle")
    else:
        page.parse(data=str(payload), format="turtle")
    return _split_page(page)


def harvest(
    config: PortalConfig,
    *,
    fetcher: BytesFetcher = fetch_bytes,
    on_raw_page: Optional[RawPageSink] = None,
    max_pages: Optional[int] = None,
) -> Iterator[HarvestedDataset]:
    """Page the Hydra catalogue feed; yield datasets with bounded graphs.

    Stops when a page contains no `dcat:Dataset` (the Hydra over-range
    page) or `max_pages` is reached.
    """
    if not config.dcat_catalog_url:
        raise ValueError(f"{config.country_code}: no dcat_catalog_url for dcat_rdf route")

    rdf_format = _rdf_format_for(config.dcat_catalog_url)
    page_idx = 0
    while True:
        url = config.dcat_catalog_url.format(
            page=page_idx + 1, page_size=config.page_size
        )
        raw = fetcher(url)
        page = Graph()
        page.parse(data=raw, format=rdf_format)

        datasets = _split_page(page)
        if not datasets:
            break

        if on_raw_page is not None:
            # Cache as Turtle so replay is single-format.
            on_raw_page(page_idx, page.serialize(format="turtle").encode("utf-8"))

        for ds in datasets:
            yield ds

        page_idx += 1
        if max_pages is not None and page_idx >= max_pages:
            break
        if config.request_delay_s:
            time.sleep(config.request_delay_s)
