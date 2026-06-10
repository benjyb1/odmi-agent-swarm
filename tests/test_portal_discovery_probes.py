"""Stack-fingerprinting probes for the portal-discovery tool.

Offline: every probe is driven with stub fetchers serving canned payloads.
A stub raises httpx.HTTPStatusError for any URL it does not know, the same
failure shape a live 404 produces, so the probes' miss-handling is what is
actually under test.
"""

from __future__ import annotations

import httpx
import pytest

from agents.tools.catalogue._fetch import BlockedEndpointError
from agents.tools.catalogue.discovery import probes


def _http_404(url: str) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", url)
    return httpx.HTTPStatusError(
        "404", request=req, response=httpx.Response(404, request=req)
    )


def _json_stub(known: dict):
    def fetch(url: str) -> dict:
        for prefix, payload in known.items():
            if url.startswith(prefix):
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise _http_404(url)

    return fetch


def _bytes_stub(known: dict):
    def fetch(url: str, *, accept=None) -> bytes:
        for prefix, payload in known.items():
            if url.startswith(prefix):
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise _http_404(url)

    return fetch


_TTL_ONE_DATASET = b"""
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct: <http://purl.org/dc/terms/> .
<https://portal.example/ds/1> a dcat:Dataset ;
    dct:title "One dataset" .
"""


# ------------------------------------------------------------------
# CKAN
# ------------------------------------------------------------------


def test_probe_ckan_detects_standard_prefix():
    fetch = _json_stub({
        "https://portal.example/api/3/action/package_search": {
            "success": True,
            "result": {"count": 1234, "results": [{"id": "a"}]},
        }
    })
    ev = probes.probe_ckan("https://portal.example", fetch_json=fetch)
    assert ev is not None
    assert ev.stack == "ckan"
    assert ev.route == "ckan_json"
    assert ev.total_datasets == 1234
    assert ev.config_fields["native_api_url"] == (
        "https://portal.example/api/3/action/package_search"
        "?rows={page_size}&start={start}"
    )
    assert ev.config_fields["pagination"] == "ckan_offset"


def test_probe_ckan_detects_nonstandard_data_prefix():
    fetch = _json_stub({
        "https://portal.example/data/api/3/action/package_search": {
            "success": True,
            "result": {"count": 7, "results": []},
        }
    })
    ev = probes.probe_ckan("https://portal.example", fetch_json=fetch)
    assert ev is not None
    assert "/data/api/3/action/package_search" in ev.endpoint


def test_probe_ckan_rejects_non_ckan_json():
    fetch = _json_stub({
        "https://portal.example/api/3/action/package_search": {"hello": "world"}
    })
    assert probes.probe_ckan("https://portal.example", fetch_json=fetch) is None


def test_probe_ckan_returns_none_on_404():
    assert probes.probe_ckan("https://portal.example", fetch_json=_json_stub({})) is None


# ------------------------------------------------------------------
# uData
# ------------------------------------------------------------------


def test_probe_udata_detects_api():
    fetch = _json_stub({
        "https://portal.example/api/1/datasets/": {
            "data": [{"id": "x"}],
            "total": 4321,
            "page": 1,
        }
    })
    ev = probes.probe_udata("https://portal.example", fetch_json=fetch)
    assert ev is not None
    assert ev.stack == "udata"
    assert ev.route == "udata_json"
    assert ev.total_datasets == 4321


def test_probe_udata_rejects_other_json():
    fetch = _json_stub({
        "https://portal.example/api/1/datasets/": {"items": []}
    })
    assert probes.probe_udata("https://portal.example", fetch_json=fetch) is None


# ------------------------------------------------------------------
# DCAT-AP RDF feed
# ------------------------------------------------------------------


def test_probe_dcat_feed_detects_paged_turtle():
    fetch = _bytes_stub({
        "https://portal.example/catalog.ttl?page=1": _TTL_ONE_DATASET
    })
    ev = probes.probe_dcat_feed("https://portal.example", fetch_bytes=fetch)
    assert ev is not None
    assert ev.stack == "dcat_feed"
    assert ev.route == "dcat_rdf"
    assert ev.config_fields["dcat_catalog_url"] == (
        "https://portal.example/catalog.ttl?page={page}"
    )
    assert ev.config_fields["pagination"] == "hydra"


def test_probe_dcat_feed_detects_udata_site_catalog():
    fetch = _bytes_stub({
        "https://portal.example/api/1/site/catalog.ttl": _TTL_ONE_DATASET
    })
    ev = probes.probe_dcat_feed("https://portal.example", fetch_bytes=fetch)
    assert ev is not None
    assert "api/1/site/catalog.ttl" in ev.config_fields["dcat_catalog_url"]
    assert "{page}" in ev.config_fields["dcat_catalog_url"]


def test_probe_dcat_feed_rejects_html_shell():
    fetch = _bytes_stub({
        "https://portal.example/catalog.ttl?page=1": b"<!doctype html><html></html>"
    })
    assert probes.probe_dcat_feed("https://portal.example", fetch_bytes=fetch) is None


def test_probe_dcat_feed_rejects_rdf_without_datasets():
    empty = b"@prefix dct: <http://purl.org/dc/terms/> .\n"
    fetch = _bytes_stub({"https://portal.example/catalog.ttl?page=1": empty})
    assert probes.probe_dcat_feed("https://portal.example", fetch_bytes=fetch) is None


# ------------------------------------------------------------------
# Stacks with no adapter yet
# ------------------------------------------------------------------


def test_probe_opendatasoft_reports_no_route():
    fetch = _json_stub({
        "https://portal.example/api/explore/v2.1/catalog/datasets": {
            "total_count": 99,
            "results": [{}],
        }
    })
    ev = probes.probe_opendatasoft("https://portal.example", fetch_json=fetch)
    assert ev is not None
    assert ev.stack == "opendatasoft"
    assert ev.route is None  # needs a new adapter


def test_probe_datajson_reports_no_route():
    fetch = _json_stub({
        "https://portal.example/data.json": {
            "conformsTo": "https://project-open-data.cio.gov/v1.1/schema",
            "dataset": [{"title": "x"}],
        }
    })
    ev = probes.probe_datajson("https://portal.example", fetch_json=fetch)
    assert ev is not None
    assert ev.stack == "datajson"
    assert ev.route is None
    assert ev.total_datasets == 1


def test_probe_sparql_reports_no_route():
    fetch = _json_stub({
        "https://portal.example/sparql": {"head": {}, "boolean": True}
    })
    ev = probes.probe_sparql("https://portal.example", fetch_json=fetch)
    assert ev is not None
    assert ev.stack == "sparql"
    assert ev.route is None


def test_probe_sparql_rejects_false_ask():
    fetch = _json_stub({
        "https://portal.example/sparql": {"head": {}, "boolean": False}
    })
    assert probes.probe_sparql("https://portal.example", fetch_json=fetch) is None


# ------------------------------------------------------------------
# FDK (hint-driven, two-step)
# ------------------------------------------------------------------


def test_probe_fdk_uses_seed_hints():
    def post(url: str, body: dict) -> dict:
        assert url == "https://search.api.example/search/datasets"
        return {"hits": [{"id": "abc"}], "page": {"totalElements": 9054}}

    hints = {
        "fdk_search_api": "https://search.api.example/search/datasets",
        "fdk_dataset_detail_url": "https://catalog.example/datasets/{id}",
    }
    ev = probes.probe_fdk(
        "https://data.example", hints=hints, post_json=post
    )
    assert ev is not None
    assert ev.stack == "fdk"
    assert ev.total_datasets == 9054
    # fdk_rdf is not a registered route on this branch, so no route yet.
    assert ev.route is None


def test_probe_fdk_without_hints_is_none():
    assert probes.probe_fdk("https://data.example", hints=None) is None


# ------------------------------------------------------------------
# probe_all: leakage and aggregation
# ------------------------------------------------------------------


def test_probe_all_refuses_denylisted_base():
    with pytest.raises(BlockedEndpointError):
        probes.probe_all(
            "https://data.europa.eu",
            fetch_json=_json_stub({}),
            fetch_bytes=_bytes_stub({}),
            delay_s=0,
        )


def test_probe_all_never_swallows_blocked_endpoint_error():
    def poisoned(url: str) -> dict:
        raise BlockedEndpointError("redirected to data.europa.eu")

    with pytest.raises(BlockedEndpointError):
        probes.probe_all(
            "https://portal.example",
            fetch_json=poisoned,
            fetch_bytes=_bytes_stub({}),
            delay_s=0,
        )


def test_probe_all_collects_multiple_fingerprints():
    fetch_json = _json_stub({
        "https://portal.example/api/3/action/package_search": {
            "success": True,
            "result": {"count": 10, "results": []},
        },
        "https://portal.example/data.json": {"dataset": [{}]},
    })
    fetch_bytes = _bytes_stub({
        "https://portal.example/catalog.ttl?page=1": _TTL_ONE_DATASET
    })
    found = probes.probe_all(
        "https://portal.example",
        fetch_json=fetch_json,
        fetch_bytes=fetch_bytes,
        delay_s=0,
    )
    stacks = {e.stack for e in found}
    assert {"ckan", "dcat_feed", "datajson"} <= stacks
