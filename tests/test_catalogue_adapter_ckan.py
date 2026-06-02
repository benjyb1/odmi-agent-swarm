"""Offline tests for the CKAN JSON adapter (catalogue tool, D30).

No network: `normalise_ckan_package` is pure, and `harvest` is driven with
a fake fetcher that serves canned pages.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.tools.catalogue.adapters import ckan_json
from agents.tools.catalogue.registry import PortalConfig

_FIXTURE = Path(__file__).parent / "fixtures" / "catalogue" / "ckan_nl_page.json"


def _load_fixture() -> dict:
    return json.loads(_FIXTURE.read_text())


def test_normalise_maps_licence_and_distributions():
    page = _load_fixture()
    pkg = page["result"]["results"][0]
    ds = ckan_json.normalise_ckan_package(pkg)

    assert ds.identifier == "11111111-1111-1111-1111-111111111111"
    assert ds.dataset_licences == [
        "http://creativecommons.org/publicdomain/zero/1.0/deed.nl"
    ]
    assert ds.identifier_uri == "https://data.overheid.nl/dataset/kadaster-bag"
    assert len(ds.distributions) == 2

    csv = ds.distributions[0]
    assert csv.fmt == "http://publications.europa.eu/resource/authority/file-type/CSV"
    assert csv.media_type == "text/csv"
    assert csv.access_url == "https://example.nl/bag.csv"
    assert csv.download_url == "https://example.nl/bag.csv"

    # Second resource has no explicit download_url; access falls back to url.
    js = ds.distributions[1]
    assert js.access_url == "https://example.nl/bag.json"
    assert js.download_url is None


def test_normalise_empty_resources_is_safe():
    ds = ckan_json.normalise_ckan_package({"id": "x", "resources": []})
    assert ds.identifier == "x"
    assert ds.distributions == []
    assert ds.dataset_licences == []
    assert ds.has_distributions() is False


def test_all_licences_collects_dataset_and_distribution():
    pkg = {
        "id": "d",
        "license_id": "cc-by",
        "resources": [
            {"license": "cc-by"},
            {"license": "cc-zero"},
            {"license": ""},
        ],
    }
    ds = ckan_json.normalise_ckan_package(pkg)
    assert ds.all_licences() == {"cc-by", "cc-zero"}


def test_harvest_paginates_until_count_reached():
    # count=3, page_size=2 -> page 0 has 2, page 1 has 1, then stop.
    pages = {
        0: {"result": {"count": 3, "results": [{"id": "a"}, {"id": "b"}]}},
        1: {"result": {"count": 3, "results": [{"id": "c"}]}},
    }
    seen_pages: list[int] = []

    def fake_fetch(url: str) -> dict:
        # start is encoded in the URL; map start//2 to a page index.
        start = int(url.split("start=")[1])
        return pages[start // 2]

    config = PortalConfig(
        country_code="NL",
        country_name="Netherlands",
        portal_base="https://data.overheid.nl",
        stack="ckan_donl",
        harvest_route="ckan_json",
        pagination="ckan_offset",
        page_size=2,
        request_delay_s=0.0,
        licence_field="dataset",
        native_api_url="https://data.overheid.nl/data/api/3/action/package_search?rows={page_size}&start={start}",
    )

    out = list(
        ckan_json.harvest(
            config,
            fetcher=fake_fetch,
            on_raw_page=lambda idx, payload: seen_pages.append(idx),
        )
    )
    assert [d.identifier for d in out] == ["a", "b", "c"]
    assert seen_pages == [0, 1]


def test_harvest_stops_on_empty_page():
    pages = {
        0: {"result": {"count": 999, "results": [{"id": "a"}]}},
        1: {"result": {"count": 999, "results": []}},
    }

    def fake_fetch(url: str) -> dict:
        start = int(url.split("start=")[1])
        return pages[start // 1]

    config = PortalConfig(
        country_code="NL",
        country_name="Netherlands",
        portal_base="https://data.overheid.nl",
        stack="ckan_donl",
        harvest_route="ckan_json",
        pagination="ckan_offset",
        page_size=1,
        request_delay_s=0.0,
        licence_field="dataset",
        native_api_url="https://x/api/3/action/package_search?rows={page_size}&start={start}",
    )
    out = list(ckan_json.harvest(config, fetcher=fake_fetch))
    assert [d.identifier for d in out] == ["a"]
