"""CKAN Action-API adapter (`package_search`).

Covers NL (data.overheid.nl DONL) on the JSON-only path, and serves as a
fallback for the CKAN portals that also expose RDF (DE, RO, HU).

Native shape: `package_search` returns `result.count` (total) and
`result.results[]` (datasets). Each dataset has dataset-level
`license_id`/`license_url` and a `resources[]` array; each resource has
`format`, `mimetype`, `url`, and sometimes `license`, `access_url`,
`download_url`.

Limitation: plain CKAN JSON does not split `dcat:accessURL` from
`dcat:downloadURL` the way the DCAT-AP RDF feed does. The resource `url` is
treated as the access URL; `download_url` is only set when the portal
exposes it explicitly. Q21 (download-URL presence) is therefore an
approximation on the JSON route and authoritative only on `dcat_rdf`.
"""

from __future__ import annotations

import time
from typing import Callable, Iterator, Optional

from agents.tools.catalogue._fetch import fetch_json
from agents.tools.catalogue.model import Distribution, HarvestedDataset
from agents.tools.catalogue.registry import PortalConfig

Fetcher = Callable[[str], dict]
RawPageSink = Callable[[int, dict], None]


def _clean(value: object) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def normalise_ckan_package(pkg: dict, *, route: str = "ckan_json") -> HarvestedDataset:
    """Map one CKAN dataset dict onto a HarvestedDataset. Pure, offline."""
    identifier = _clean(pkg.get("id")) or _clean(pkg.get("name")) or ""

    dataset_licences: list[str] = []
    lic = _clean(pkg.get("license_id"))
    if lic:
        dataset_licences.append(lic)

    distributions: list[Distribution] = []
    for res in pkg.get("resources") or []:
        if not isinstance(res, dict):
            continue
        distributions.append(
            Distribution(
                licence=_clean(res.get("license") or res.get("license_id")),
                fmt=_clean(res.get("format")),
                media_type=_clean(res.get("mimetype")),
                access_url=_clean(res.get("access_url") or res.get("url")),
                download_url=_clean(res.get("download_url")),
            )
        )

    tags = pkg.get("tags") or []
    keywords = [
        _clean(t.get("name")) for t in tags
        if isinstance(t, dict) and _clean(t.get("name"))
    ]
    org = pkg.get("organization") or {}
    extras = {
        "title": _clean(pkg.get("title")),
        "description": _clean(pkg.get("notes")),
        "keywords": keywords,
        "publisher": _clean(org.get("title")) if isinstance(org, dict) else None,
        "issued": _clean(pkg.get("metadata_created")),
        "modified": _clean(pkg.get("metadata_modified")),
    }

    return HarvestedDataset(
        identifier=identifier,
        dataset_licences=dataset_licences,
        distributions=distributions,
        source_route=route,
        identifier_uri=_clean(pkg.get("uri")),
        extras={k: v for k, v in extras.items() if v},
    )


def normalise_page(payload: dict, *, route: str = "ckan_json") -> list[HarvestedDataset]:
    """Normalise every dataset in one cached `package_search` page.

    Used on the replay path: harvest.py reads the gzipped raw pages back
    from disk and re-normalises them, so a computation is reproducible
    from the cache alone.
    """
    result = payload.get("result") or {}
    out: list[HarvestedDataset] = []
    for pkg in result.get("results") or []:
        if isinstance(pkg, dict):
            out.append(normalise_ckan_package(pkg, route=route))
    return out


def harvest(
    config: PortalConfig,
    *,
    fetcher: Fetcher = fetch_json,
    on_raw_page: Optional[RawPageSink] = None,
    max_pages: Optional[int] = None,
) -> Iterator[HarvestedDataset]:
    """Page through `package_search`, yielding normalised datasets.

    `native_api_url` is a template carrying `{page_size}` and `{start}`.
    Stops when a page is empty or `result.count` is reached.
    """
    if not config.native_api_url:
        raise ValueError(f"{config.country_code}: no native_api_url for ckan_json route")

    page_size = config.page_size
    start = 0
    page_idx = 0
    total: Optional[int] = None

    while True:
        url = config.native_api_url.format(
            page_size=page_size, start=start, page=page_idx + 1
        )
        payload = fetcher(url)
        if on_raw_page is not None:
            on_raw_page(page_idx, payload)

        result = payload.get("result") or {}
        if total is None:
            total = result.get("count")
        packages = result.get("results") or []
        if not packages:
            break

        for pkg in packages:
            if isinstance(pkg, dict):
                yield normalise_ckan_package(pkg, route=config.harvest_route)

        start += page_size
        page_idx += 1
        if total is not None and start >= total:
            break
        if max_pages is not None and page_idx >= max_pages:
            break
        if config.request_delay_s:
            time.sleep(config.request_delay_s)
