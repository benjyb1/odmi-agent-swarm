"""Offline tests for the Albania custom-API adapter (al_dcat_api route).

opendata.gov.al is an Angular SPA whose data sits behind a .NET DCAT API.
The list endpoint is `POST /api/Dataset/filter` with a `{page, pageSize}`
body returning `{data: {results: [...], pageCount}}`, distributions inline.
Driven here with canned pages; the hit shape mirrors a live filter result.
"""

from __future__ import annotations

from agents.tools.catalogue.adapters import al_dcat_api
from agents.tools.catalogue.registry import ROUTES, PortalConfig


def _config(page_size=2):
    return PortalConfig(
        country_code="AL",
        country_name="Albania",
        portal_base="https://opendata.gov.al",
        stack="custom-dotnet",
        harvest_route="al_dcat_api",
        pagination="page_post",
        page_size=page_size,
        request_delay_s=0,
        licence_field="distribution",
        native_api_url="https://opendata.gov.al/api/Dataset/filter",
    )


_HIT = {
    "id": "994474ac-c327-4e7e-8fb0-4fed5a6e2687",
    "slug": "bizneset_sipas_formes_ligjore__2026_",
    "title": "Bizneset sipas formës ligjore (2026)",
    "description": "Bizneset sipas formës ligjore (2026)",
    "resource": "http://opendata.gov.al/dataset/bizneset_994474ac",
    "publisher": {"name": "Qëndra Kombëtare e Biznesit"},
    "dctLicenseId": None,
    "dcatDistributions": [
        {
            "license": "http://publications.europa.eu/resource/authority/licence/CC_BY_4_0",
            "format": "http://publications.europa.eu/resource/authority/file-type/CSV",
            "mediaType": "text/csv",
            "accessUrl": "https://opendata.gov.al/dataset/bizneset",
            "downloadUrl": "https://opendata.gov.al/download/bizneset.csv",
        },
        {
            "license": None,
            "format": None,
            "accessUrl": "https://opendata.gov.al/dataset/bizneset",
            "downloadUrl": None,
        },
    ],
}


def _page(hits, page_count=2):
    return {"data": {"results": hits, "pageCount": page_count, "rowCount": 3}}


def test_route_is_registered():
    assert "al_dcat_api" in ROUTES


def test_normalise_maps_distribution_fields():
    ds = al_dcat_api.normalise_al_dataset(_HIT)
    assert ds.identifier == "994474ac-c327-4e7e-8fb0-4fed5a6e2687"
    assert ds.source_route == "al_dcat_api"
    assert len(ds.distributions) == 2
    one, two = ds.distributions
    assert one.licence == "http://publications.europa.eu/resource/authority/licence/CC_BY_4_0"
    assert one.fmt == "http://publications.europa.eu/resource/authority/file-type/CSV"
    assert one.media_type == "text/csv"
    assert one.download_url == "https://opendata.gov.al/download/bizneset.csv"
    assert two.licence is None
    assert two.download_url is None
    assert ds.extras["title"] == "Bizneset sipas formës ligjore (2026)"
    assert ds.extras["publisher"] == "Qëndra Kombëtare e Biznesit"


def test_normalise_handles_missing_fields():
    ds = al_dcat_api.normalise_al_dataset({"id": "x"})
    assert ds.identifier == "x"
    assert ds.distributions == []
    assert ds.all_licences() == set()


def test_harvest_paginates_until_empty_page():
    pages = {1: _page([_HIT, {**_HIT, "id": "b"}]), 2: _page([{**_HIT, "id": "c"}]), 3: _page([])}
    seen = []

    def fetch(url, body):
        seen.append(body["page"])
        return pages[body["page"]]

    datasets = list(al_dcat_api.harvest(_config(), fetcher=fetch))
    assert [d.identifier for d in datasets] == [
        "994474ac-c327-4e7e-8fb0-4fed5a6e2687", "b", "c",
    ]
    # pageCount=2 stops paging after page 2 without needing the empty page 3
    assert seen == [1, 2]


def test_harvest_caches_raw_pages_and_replays():
    pages = {1: _page([_HIT], page_count=1)}

    def fetch(url, body):
        return pages[body["page"]]

    cached = []
    list(al_dcat_api.harvest(_config(), fetcher=fetch, on_raw_page=lambda i, p: cached.append(p)))
    assert len(cached) == 1
    replayed = al_dcat_api.normalise_page(cached[0])
    assert [d.identifier for d in replayed] == ["994474ac-c327-4e7e-8fb0-4fed5a6e2687"]


def test_max_pages_caps_paging():
    def fetch(url, body):
        return _page([_HIT], page_count=99)  # never naturally stops

    datasets = list(al_dcat_api.harvest(_config(), fetcher=fetch, max_pages=2))
    assert len(datasets) == 2
