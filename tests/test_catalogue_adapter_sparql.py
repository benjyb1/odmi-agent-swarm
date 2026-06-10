"""Offline tests for the SPARQL DCAT adapter (sparql_rdf route).

Drives `harvest` with a stubbed fetcher serving canned Turtle pages. One
paged CONSTRUCT (dataset triples UNION distribution triples, dataset set
bounded by an inlined ordered subquery) is the whole protocol; the live
shape was timed on data.gov.cz (108 KB in 0.3 s for a 20-dataset page,
where a three-level OPTIONAL CONSTRUCT timed out).
"""

from __future__ import annotations

from urllib.parse import unquote

from agents.tools.catalogue.adapters import sparql_rdf
from agents.tools.catalogue.registry import ROUTES, PortalConfig


def _config(page_size=2):
    return PortalConfig(
        country_code="CZ",
        country_name="Czechia",
        portal_base="https://data.gov.cz",
        stack="sparql",
        harvest_route="sparql_rdf",
        pagination="sparql_offset",
        page_size=page_size,
        request_delay_s=0,
        licence_field="distribution",
        native_api_url="https://data.gov.cz/sparql",
    )


_TTL_PAGE = b"""
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
<https://data.gov.cz/ds/1> a dcat:Dataset ;
    dct:title "Dataset one" ;
    dcat:distribution <https://data.gov.cz/dist/1> .
<https://data.gov.cz/dist/1> a dcat:Distribution ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> ;
    dct:format "CSV" ;
    dcat:accessURL <https://data.gov.cz/file/1.csv> ;
    dcat:downloadURL <https://data.gov.cz/file/1.csv> .
<https://data.gov.cz/ds/2> a dcat:Dataset ;
    dct:title "Dataset two" .
"""

_TTL_EMPTY = b"@prefix dcat: <http://www.w3.org/ns/dcat#> .\n"


def _stub(pages):
    """Serve `pages[i]` for the i-th request; empty Turtle beyond."""
    calls = {"urls": [], "accepts": []}

    def fetch(url, *, accept=None, **kw):
        calls["urls"].append(url)
        calls["accepts"].append(accept)
        i = len(calls["urls"]) - 1
        return pages[i] if i < len(pages) else _TTL_EMPTY

    return fetch, calls


def test_route_is_registered():
    assert "sparql_rdf" in ROUTES


def test_harvest_yields_datasets_with_graphs_and_distributions():
    fetch, calls = _stub([_TTL_PAGE])
    datasets = list(sparql_rdf.harvest(_config(), fetcher=fetch))
    assert len(datasets) == 2
    by_id = {d.identifier: d for d in datasets}
    one = by_id["https://data.gov.cz/ds/1"]
    assert one.graph is not None
    assert one.source_route == "sparql_rdf"
    assert one.distributions[0].licence == (
        "https://creativecommons.org/licenses/by/4.0/"
    )
    assert one.distributions[0].fmt == "CSV"
    # Page 1 had datasets, page 2 empty -> exactly two requests.
    assert len(calls["urls"]) == 2


def test_query_pages_with_limit_and_offset():
    fetch, calls = _stub([_TTL_PAGE, _TTL_PAGE])
    list(sparql_rdf.harvest(_config(page_size=2), fetcher=fetch))
    q0, q1 = unquote(calls["urls"][0]), unquote(calls["urls"][1])
    assert "LIMIT 2 OFFSET 0" in q0
    assert "LIMIT 2 OFFSET 2" in q1
    assert "CONSTRUCT" in q0 and "UNION" in q0


def test_max_pages_caps_the_paging():
    fetch, calls = _stub([_TTL_PAGE, _TTL_PAGE, _TTL_PAGE])
    list(sparql_rdf.harvest(_config(), fetcher=fetch, max_pages=2))
    assert len(calls["urls"]) == 2


def test_uses_turtle_content_negotiation():
    fetch, calls = _stub([_TTL_PAGE])
    list(sparql_rdf.harvest(_config(), fetcher=fetch))
    assert all(a == "text/turtle" for a in calls["accepts"])


def test_raw_pages_are_cached_as_canonical_turtle_and_replay():
    fetch, _ = _stub([_TTL_PAGE])
    pages = []
    list(sparql_rdf.harvest(
        _config(), fetcher=fetch, on_raw_page=lambda i, b: pages.append((i, b))
    ))
    assert len(pages) == 1
    replayed = sparql_rdf.normalise_page(pages[0][1])
    assert {d.identifier for d in replayed} == {
        "https://data.gov.cz/ds/1", "https://data.gov.cz/ds/2"
    }
    assert all(d.source_route == "sparql_rdf" for d in replayed)
