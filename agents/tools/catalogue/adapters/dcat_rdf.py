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

import sys
import time
from typing import Callable, Iterator, Optional

import httpx
from rdflib import BNode, Graph, URIRef
from rdflib.compare import to_canonical_graph
from rdflib.namespace import RDF

from agents.tools.catalogue._fetch import fetch_bytes

# Deep pagination on some Hydra feeds (data.gouv.fr past ~page 200) degrades
# badly: pages balloon to several MB and the server intermittently stalls,
# tripping the read timeout. A single stall used to abort the whole harvest as
# "partial" (FR truncated at 19,700 of ~74k). Retry a stalled page a few times
# with a longer per-attempt timeout before giving up.
_PAGE_FETCH_RETRIES = 7
_PAGE_FETCH_TIMEOUT_S = 120.0
# Exponential backoff (seconds) so a transient network/DNS blip or a
# momentarily overloaded server has time to recover before the harvest gives
# up and truncates. Total patience per page ~2 minutes.
_PAGE_FETCH_BACKOFF = (2.0, 4.0, 8.0, 16.0, 32.0, 60.0)

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

# An injected fetcher is called as `fetcher(url, timeout_s=...)`, so it must
# absorb keyword arguments (the default, `_fetch.fetch_bytes`, does). The
# signature is deliberately loose: pinning it to `Callable[[str], bytes]` said
# something the retry path below no longer honours.
BytesFetcher = Callable[..., bytes]
RawPageSink = Callable[[int, bytes], None]


def _fetch_page(fetcher: BytesFetcher, url: str) -> bytes:
    last_exc: Optional[Exception] = None
    for attempt in range(_PAGE_FETCH_RETRIES):
        try:
            return fetcher(url, timeout_s=_PAGE_FETCH_TIMEOUT_S)
        except (httpx.TimeoutException, httpx.TransportError, OSError) as exc:
            last_exc = exc
            print(
                f"[harvest] page fetch stalled (attempt "
                f"{attempt + 1}/{_PAGE_FETCH_RETRIES}) {type(exc).__name__}: {url}",
                file=sys.stderr,
            )
            if attempt < len(_PAGE_FETCH_BACKOFF):
                time.sleep(_PAGE_FETCH_BACKOFF[attempt])
    assert last_exc is not None
    raise last_exc


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


# rdflib's N-Triples writer raises on a URIRef that carries characters
# illegal in an IRI (a space, angle brackets, control chars). Some national
# feeds emit them: Croatia's, for one, publishes a malformed accessURL
# ("http:// http://servisi.azo.hr/...") with an embedded space. A single
# such triple aborts the serialisation of its whole page, which
# harvest_country catches as a partial harvest, silently truncating the
# catalogue at that page (HR stopped at 1,400 of 3,867). The offending
# terms are unusable to any metric anyway, so drop the individual triples
# (never the datasets) before serialising. Deterministic: the same
# malformed triples drop on every run, so content_sha256 stays reproducible.
_ILLEGAL_URI_CHARS = frozenset('<>" {}|\\^`')


def _uri_serialisable(term: object) -> bool:
    """False for a URIRef that the N-Triples writer would reject."""
    if not isinstance(term, URIRef):
        return True
    u = str(term)
    return bool(u) and not any(c in _ILLEGAL_URI_CHARS or ord(c) < 0x21 for c in u)


def _drop_unserialisable(page: Graph) -> tuple[Graph, int]:
    """Copy of `page` without triples carrying a malformed IRI term."""
    clean = Graph()
    dropped = 0
    for triple in page:
        s, p, o = triple
        if _uri_serialisable(s) and _uri_serialisable(p) and _uri_serialisable(o):
            clean.add(triple)
        else:
            dropped += 1
    return (page, 0) if dropped == 0 else (clean, dropped)


# rdflib's blank-node canonicalisation (to_canonical_graph) is worst-case
# exponential in the number of blank nodes on a page. Sweden's EntryScape feed
# carries ~230 bnodes per 100-dataset page, where canonicalisation takes ~110s
# PER PAGE (a 233-page harvest would need ~7h of pure CPU) — this is the real
# cause of the long-observed "SE SPARQL hang". Above this many bnodes we skip
# canonicalisation: blank-node labels are then not stable across re-harvests,
# so content_sha256 is not cross-run reproducible for that page, but the data
# is complete and replays identically. Feeds with few bnodes (FR, DE, HU, RO)
# stay canonical and reproducible.
_MAX_BNODES_FOR_CANON = 40


def _canonical_turtle_bytes(page: Graph) -> bytes:
    """Serialise a page deterministically for the snapshot cache.

    rdflib's Turtle writer is non-deterministic (blank-node ids and triple
    order vary run to run), so hashing its output makes content_sha256
    irreproducible. Canonicalise the blank nodes, emit N-Triples (which is
    valid Turtle, so the replay path still parses it as Turtle), and sort the
    lines for a stable byte sequence.

    Two guards keep this robust on messy real feeds: malformed-IRI triples are
    dropped first (`_drop_unserialisable`), and canonicalisation is skipped for
    blank-node-heavy pages where it would be pathologically slow (see
    `_MAX_BNODES_FOR_CANON`).
    """
    clean, dropped = _drop_unserialisable(page)
    if dropped:
        print(
            f"[harvest] dropped {dropped} triple(s) with malformed IRIs "
            f"before serialising a page",
            file=sys.stderr,
        )
    n_bnodes = len({t for s, p, o in clean for t in (s, p, o) if isinstance(t, BNode)})
    if n_bnodes <= _MAX_BNODES_FOR_CANON:
        to_serialise = to_canonical_graph(clean)
    else:
        # Skip the exponential canonicaliser; the data is unaffected.
        to_serialise = clean
    nt = to_serialise.serialize(format="nt")
    lines = sorted(line for line in nt.splitlines() if line.strip())
    return ("\n".join(lines) + "\n").encode("utf-8")


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
        raw = _fetch_page(fetcher, url)
        page = Graph()
        page.parse(data=raw, format=rdf_format)

        datasets = _split_page(page)
        if not datasets:
            break

        if on_raw_page is not None:
            # Cache as canonical, sorted N-Triples (valid Turtle) so replay
            # stays single-format and the snapshot hash is reproducible.
            on_raw_page(page_idx, _canonical_turtle_bytes(page))

        for ds in datasets:
            yield ds

        page_idx += 1
        if max_pages is not None and page_idx >= max_pages:
            break
        if config.request_delay_s:
            time.sleep(config.request_delay_s)
