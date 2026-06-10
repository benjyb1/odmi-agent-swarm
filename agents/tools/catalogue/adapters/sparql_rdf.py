"""SPARQL DCAT adapter (CZ, HR, SE): harvest a catalogue through its
public SPARQL endpoint.

Some national portals expose no paged RDF feed and no JSON catalogue API;
their DCAT graph lives behind a SPARQL endpoint (Czechia's NKOD, Croatia's
data.gov.hr, Sweden's EntryScape on admin.dataportal.se). The harvest is
ONE query per page:

    CONSTRUCT { ?s ?p ?o . ?d ?dp ?do }
    WHERE {
      { SELECT DISTINCT ?s WHERE { ?s a dcat:Dataset }
        ORDER BY ?s LIMIT {page_size} OFFSET {offset} }
      { ?s ?p ?o } UNION { ?s dcat:distribution ?d . ?d ?dp ?do }
    }

The inlined ordered subquery makes the paging deterministic, and the
UNION pulls each dataset's own triples plus its distributions' triples,
which covers the licence, format and URL fields the presence metrics read.
This shape was timed live on data.gov.cz: a 20-dataset page returns in
under a second, where a generic three-level OPTIONAL CONSTRUCT timed out.
Deeper sub-nodes (publisher Agent, contact vCard bodies) are not pulled,
so SHACL conformance over this route reads the dataset and distribution
levels only; recorded as a per-route caveat in docs/CATALOGUE_METRICS.md.

The Turtle result is re-serialised canonically and split into per-dataset
bounded descriptions by the same helpers the `dcat_rdf` route uses. Stops
at the first page with no `dcat:Dataset`.

`native_api_url` in the registry is the bare SPARQL endpoint URL.
"""

from __future__ import annotations

import time
from typing import Callable, Iterator, Optional
from urllib.parse import quote

from rdflib import Graph

from agents.tools.catalogue._fetch import fetch_bytes
from agents.tools.catalogue.adapters.dcat_rdf import (
    _canonical_turtle_bytes,
    _split_page,
)
from agents.tools.catalogue.model import HarvestedDataset
from agents.tools.catalogue.registry import PortalConfig

BytesFetcher = Callable[..., bytes]
RawPageSink = Callable[[int, bytes], None]

_ACCEPT = "text/turtle"

_PAGE_QUERY = (
    "CONSTRUCT {{ ?s ?p ?o . ?d ?dp ?do }} "
    "WHERE {{ "
    "{{ SELECT DISTINCT ?s WHERE {{ ?s a <http://www.w3.org/ns/dcat#Dataset> }} "
    "ORDER BY ?s LIMIT {limit} OFFSET {offset} }} "
    "{{ ?s ?p ?o }} UNION "
    "{{ ?s <http://www.w3.org/ns/dcat#distribution> ?d . ?d ?dp ?do }} "
    "}}"
)


def _endpoint(config: PortalConfig) -> str:
    if not config.native_api_url:
        raise ValueError(
            f"{config.country_code}: no native_api_url (SPARQL endpoint) "
            "for sparql_rdf route"
        )
    return config.native_api_url


def _page_url(endpoint: str, *, limit: int, offset: int) -> str:
    query = _PAGE_QUERY.format(limit=limit, offset=offset)
    return f"{endpoint}?query={quote(query)}"


def normalise_page(payload, *, route: str = "sparql_rdf") -> list[HarvestedDataset]:
    """Replay a cached Turtle page into datasets with graphs."""
    page = Graph()
    if isinstance(payload, (bytes, bytearray)):
        page.parse(data=payload, format="turtle")
    else:
        page.parse(data=str(payload), format="turtle")
    out = _split_page(page)
    for d in out:
        d.source_route = route
    return out


def harvest(
    config: PortalConfig,
    *,
    fetcher: BytesFetcher = fetch_bytes,
    on_raw_page: Optional[RawPageSink] = None,
    max_pages: Optional[int] = None,
) -> Iterator[HarvestedDataset]:
    """Page the SPARQL endpoint; yield datasets with bounded graphs."""
    endpoint = _endpoint(config)
    page_idx = 0
    while True:
        url = _page_url(
            endpoint,
            limit=config.page_size,
            offset=page_idx * config.page_size,
        )
        raw = fetcher(url, accept=_ACCEPT)
        page = Graph()
        page.parse(data=raw, format="turtle")
        datasets = _split_page(page)
        if not datasets:
            break
        for d in datasets:
            d.source_route = "sparql_rdf"
        if on_raw_page is not None:
            on_raw_page(page_idx, _canonical_turtle_bytes(page))
        for d in datasets:
            yield d
        page_idx += 1
        if max_pages is not None and page_idx >= max_pages:
            break
        if config.request_delay_s:
            time.sleep(config.request_delay_s)
