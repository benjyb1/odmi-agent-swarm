"""Albania custom-API adapter (opendata.gov.al).

The national portal is an Angular single-page app: the served HTML is an
empty shell, so the search index, trafilatura and the static discovery
adapters all see nothing (see docs/LANGUAGE_FRAMEWORK_DEEPDIVE.md section F).
The data sits behind a documented .NET DCAT API. The list endpoint
`POST /api/Dataset/filter` with `{"page": n, "pageSize": m}` returns
`{data: {results: [...], rowCount, pageCount}}`, and each result already
carries its DCAT distributions inline under `dcatDistributions[]`, so no
per-dataset detail fetch is needed. Licence and format are EU authority URIs
at the distribution level (dataset-level `dctLicenseId` is usually null).
"""

from __future__ import annotations

import time
from typing import Callable, Iterator, Optional
from urllib.parse import urljoin

from agents.tools.catalogue._fetch import post_json
from agents.tools.catalogue.model import Distribution, HarvestedDataset
from agents.tools.catalogue.registry import PortalConfig

# (url, body) -> json. POST, because the list endpoint is a filter query.
Fetcher = Callable[[str, dict], dict]
RawPageSink = Callable[[int, dict], None]

# The portal serves distribution download URLs as site-relative paths
# (`/files/Dataset/...`), so they must be resolved against the portal base
# before they are valid IRIs; otherwise the DCAT-AP mandatory SHACL (Q16)
# rejects every dataset on dcat:downloadURL nodeKind.
_DEFAULT_BASE = "https://opendata.gov.al"


def _clean(value: object) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _abs_url(value: object, base: str) -> Optional[str]:
    """Resolve a possibly site-relative URL against the portal base."""
    s = _clean(value)
    return urljoin(base, s) if s else None


def normalise_al_dataset(
    item: dict, *, route: str = "al_dcat_api", base: str = _DEFAULT_BASE
) -> HarvestedDataset:
    """Map one opendata.gov.al filter result onto a HarvestedDataset.

    Pure and offline-testable: it reads a single result dict and does no
    network. Distributions are inline under `dcatDistributions`; their
    access and download URLs are resolved against `base` because the portal
    emits download URLs as site-relative paths.
    """
    identifier = _clean(item.get("id")) or _clean(item.get("slug")) or ""
    dataset_licence = _clean(item.get("dctLicenseId"))

    distributions: list[Distribution] = []
    for dist in item.get("dcatDistributions") or []:
        if not isinstance(dist, dict):
            continue
        distributions.append(
            Distribution(
                licence=_clean(dist.get("license") or dist.get("dctLicenseId")),
                fmt=_clean(dist.get("format")),
                media_type=_clean(dist.get("mediaType")),
                access_url=_abs_url(dist.get("accessUrl"), base),
                download_url=_abs_url(dist.get("downloadUrl"), base),
            )
        )

    publisher = item.get("publisher")
    extras = {
        "title": _clean(item.get("title") or item.get("description")),
        "description": _clean(item.get("description")),
        "publisher": _clean(publisher.get("name")) if isinstance(publisher, dict) else None,
        "issued": _clean(item.get("issued")),
        "modified": _clean(item.get("modified")),
        "landing_page": _clean(item.get("landingPage")),
        "access_rights": _clean(item.get("accessRights")),
        "keywords": [k for k in (item.get("keywords") or []) if isinstance(k, str)],
    }

    return HarvestedDataset(
        identifier=identifier,
        dataset_licences=[dataset_licence] if dataset_licence else [],
        distributions=distributions,
        source_route=route,
        identifier_uri=_clean(item.get("resource") or item.get("identifier")),
        extras={k: v for k, v in extras.items() if v},
    )


def normalise_page(payload: dict, *, route: str = "al_dcat_api") -> list[HarvestedDataset]:
    """Replay a cached page (a list of result dicts under 'results')."""
    return [
        normalise_al_dataset(d, route=route)
        for d in payload.get("results") or []
        if isinstance(d, dict)
    ]


def harvest(
    config: PortalConfig,
    *,
    fetcher: Fetcher = post_json,
    on_raw_page: Optional[RawPageSink] = None,
    max_pages: Optional[int] = None,
) -> Iterator[HarvestedDataset]:
    """Drive the `POST /api/Dataset/filter` pagination, yield normalised
    datasets, and hand each raw page (the `results` list) to `on_raw_page`
    for the disk cache."""
    if not config.native_api_url:
        raise ValueError(f"{config.country_code}: al_dcat_api needs native_api_url")

    page = 1
    page_idx = 0
    page_count: Optional[int] = None

    while True:
        payload = fetcher(config.native_api_url, {"page": page, "pageSize": config.page_size})
        data = payload.get("data") or {}
        results = data.get("results") or []
        if page_count is None:
            page_count = data.get("pageCount")
        if not results:
            break

        if on_raw_page is not None:
            on_raw_page(page_idx, {"results": results})

        for item in results:
            yield normalise_al_dataset(
                item, route=config.harvest_route, base=config.portal_base
            )

        page += 1
        page_idx += 1
        if page_count is not None and page > page_count:
            break
        if max_pages is not None and page_idx >= max_pages:
            break
        if config.request_delay_s:
            time.sleep(config.request_delay_s)
