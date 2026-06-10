"""Offline tests for the piveau hub-search adapter (piveau_json route).

Covers AT (data.gv.at since its relaunch on the piveau stack, the same
software family as data.europa.eu but nationally hosted). Driven with
canned search pages; the hit shape mirrors a live data.gv.at response.
"""

from __future__ import annotations

from agents.tools.catalogue.adapters import piveau_json
from agents.tools.catalogue.registry import ROUTES, PortalConfig


def _config(page_size=2):
    return PortalConfig(
        country_code="AT",
        country_name="Austria",
        portal_base="https://www.data.gv.at",
        stack="piveau",
        harvest_route="piveau_json",
        pagination="piveau_page",
        page_size=page_size,
        request_delay_s=0,
        licence_field="distribution",
        native_api_url=(
            "https://www.data.gv.at/api/hub/search/search"
            "?filters=dataset&limit={page_size}&page={page}"
        ),
    )


_HIT = {
    "id": "46032b35-a027-4ffb-83fa-a1da564f713e",
    "title": {"en": "Rechnungsabschluss Siegendorf 2022"},
    "description": {"en": "Einnahmen und Ausgaben"},
    "publisher": {"name": "Gemeinde Siegendorf", "type": "Agent"},
    "keywords": [],
    "distributions": [
        {
            "id": "d1",
            "license": {"resource": "https://creativecommons.org/licenses/by/4.0/"},
            "format": {
                "resource": "http://publications.europa.eu/resource/authority/file-type/CSV",
                "id": "CSV",
                "label": "CSV",
            },
            "access_url": ["https://example.at/file.csv"],
            "download_url": ["https://example.at/file.csv"],
        },
        {
            "id": "d2",
            "license": None,
            "format": None,
            "access_url": ["https://example.at/page"],
            "download_url": None,
        },
    ],
}


def _page(hits, count=3):
    return {"result": {"index": "dataset", "count": count, "results": hits}}


def test_route_is_registered():
    assert "piveau_json" in ROUTES


def test_normalise_maps_distribution_fields():
    ds = piveau_json.normalise_piveau_dataset(_HIT)
    assert ds.identifier == "46032b35-a027-4ffb-83fa-a1da564f713e"
    assert ds.source_route == "piveau_json"
    assert len(ds.distributions) == 2
    one, two = ds.distributions
    assert one.licence == "https://creativecommons.org/licenses/by/4.0/"
    assert one.fmt == (
        "http://publications.europa.eu/resource/authority/file-type/CSV"
    )
    assert one.access_url == "https://example.at/file.csv"
    assert one.download_url == "https://example.at/file.csv"
    assert two.licence is None
    assert two.download_url is None
    assert ds.extras["title"] == "Rechnungsabschluss Siegendorf 2022"
    assert ds.extras["publisher"] == "Gemeinde Siegendorf"


def test_normalise_handles_missing_fields():
    ds = piveau_json.normalise_piveau_dataset({"id": "x"})
    assert ds.identifier == "x"
    assert ds.distributions == []
    assert ds.all_licences() == set()


def test_harvest_paginates_until_empty_page():
    pages = {
        0: _page([_HIT, {**_HIT, "id": "b"}]),
        1: _page([{**_HIT, "id": "c"}]),
        2: _page([]),
    }
    seen_urls = []

    def fetch(url):
        seen_urls.append(url)
        page_no = int(url.split("page=")[1])
        return pages[page_no]

    datasets = list(piveau_json.harvest(_config(), fetcher=fetch))
    assert [d.identifier for d in datasets] == [
        "46032b35-a027-4ffb-83fa-a1da564f713e", "b", "c",
    ]
    assert len(seen_urls) == 3


def test_harvest_caches_raw_pages_and_replays():
    pages = {0: _page([_HIT]), 1: _page([])}

    def fetch(url):
        return pages[int(url.split("page=")[1])]

    cached = []
    list(piveau_json.harvest(
        _config(), fetcher=fetch, on_raw_page=lambda i, p: cached.append(p)
    ))
    assert len(cached) == 1
    replayed = piveau_json.normalise_page(cached[0])
    assert [d.identifier for d in replayed] == [
        "46032b35-a027-4ffb-83fa-a1da564f713e"
    ]


def test_max_pages_caps_paging():
    def fetch(url):
        return _page([_HIT])  # never empty

    datasets = list(
        piveau_json.harvest(_config(), fetcher=fetch, max_pages=2)
    )
    assert len(datasets) == 2
