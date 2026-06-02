"""udata adapter (data.gouv.fr) — JSON fallback.

France's primary route is `dcat_rdf` (its first-party DCAT-AP feed), which
gives real graphs for the conformance metrics. This adapter is the
presence-only fallback over the udata REST API
`/api/1/datasets/?page&page_size`, following `next_page`.
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


def normalise_udata_dataset(pkg: dict, *, route: str = "udata_json") -> HarvestedDataset:
    identifier = _clean(pkg.get("id")) or _clean(pkg.get("slug")) or ""
    lic = _clean(pkg.get("license"))
    distributions: list[Distribution] = []
    for res in pkg.get("resources") or []:
        if not isinstance(res, dict):
            continue
        url = _clean(res.get("url"))
        distributions.append(
            Distribution(
                licence=_clean(((res.get("extras") or {}).get("dcat:license"))) or lic,
                fmt=_clean(res.get("format")),
                media_type=_clean(res.get("mime")),
                access_url=url,
                download_url=url,  # udata resource url is the file location
            )
        )
    extras = {
        "title": _clean(pkg.get("title")),
        "description": _clean(pkg.get("description")),
        "keywords": [t for t in (pkg.get("tags") or []) if isinstance(t, str)],
    }
    return HarvestedDataset(
        identifier=identifier,
        dataset_licences=[lic] if lic else [],
        distributions=distributions,
        source_route=route,
        identifier_uri=_clean(pkg.get("uri")) or _clean(pkg.get("page")),
        extras={k: v for k, v in extras.items() if v},
    )


def normalise_page(payload: dict, *, route: str = "udata_json") -> list[HarvestedDataset]:
    return [
        normalise_udata_dataset(d, route=route)
        for d in payload.get("data") or []
        if isinstance(d, dict)
    ]


def harvest(
    config: PortalConfig,
    *,
    fetcher: Fetcher = fetch_json,
    on_raw_page: Optional[RawPageSink] = None,
    max_pages: Optional[int] = None,
) -> Iterator[HarvestedDataset]:
    page = 1
    page_idx = 0
    while True:
        url = config.native_api_url.format(page=page, page_size=config.page_size)
        listing = fetcher(url)
        items = listing.get("data") or []
        if on_raw_page is not None:
            on_raw_page(page_idx, listing)
        if not items:
            break
        for d in items:
            if isinstance(d, dict):
                yield normalise_udata_dataset(d, route=config.harvest_route)
        if not listing.get("next_page"):
            break
        page += 1
        page_idx += 1
        if max_pages is not None and page_idx >= max_pages:
            break
        if config.request_delay_s:
            time.sleep(config.request_delay_s)
