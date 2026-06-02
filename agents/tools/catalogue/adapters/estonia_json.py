"""Estonia custom-API adapter (andmed.eesti.ee).

Not CKAN: a custom NestJS API. The list endpoint
`/api/datasets?page&limit=75` returns `{data: [...], metadata: {total}}`;
licence and format live on the per-dataset detail
`/api/datasets/{id}` under `distributions[]`. There is no national RDF
feed, so conformance metrics run over a graph synthesised from this JSON
(see synthesise.py).
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


def normalise_estonia_detail(detail: dict, *, route: str = "estonia_json") -> HarvestedDataset:
    """Map one Estonia dataset-detail dict onto a HarvestedDataset."""
    identifier = (
        _clean(detail.get("id"))
        or _clean(detail.get("slug"))
        or _clean(detail.get("dct_identifier"))
        or ""
    )

    distributions: list[Distribution] = []
    for dist in detail.get("distributions") or []:
        if not isinstance(dist, dict):
            continue
        access_urls = dist.get("accessUrls") or []
        access_url = _clean(access_urls[0]) if access_urls else None
        distributions.append(
            Distribution(
                licence=_clean(dist.get("license")),
                fmt=_clean(dist.get("format")),
                media_type=_clean(dist.get("mediaType")),
                access_url=access_url,
                download_url=access_url,  # EE exposes access URLs only
            )
        )

    extras = {
        "title": _clean(detail.get("titleEn") or detail.get("title")),
        "description": _clean(detail.get("descriptionEn") or detail.get("description")),
        "keywords": [k for k in (detail.get("keywords") or []) if isinstance(k, str)],
        "issued": _clean(detail.get("issued")),
        "modified": _clean(detail.get("modified")),
        "publisher": _clean((detail.get("organization") or {}).get("name"))
        if isinstance(detail.get("organization"), dict)
        else None,
    }

    return HarvestedDataset(
        identifier=identifier,
        dataset_licences=[],  # EE has no dataset-level licence
        distributions=distributions,
        source_route=route,
        identifier_uri=_clean(detail.get("dct_identifier")),
        extras={k: v for k, v in extras.items() if v},
    )


def normalise_page(payload: dict, *, route: str = "estonia_json") -> list[HarvestedDataset]:
    """Replay a cached page (a list of detail dicts under 'details')."""
    return [
        normalise_estonia_detail(d, route=route)
        for d in payload.get("details") or []
        if isinstance(d, dict)
    ]


def harvest(
    config: PortalConfig,
    *,
    fetcher: Fetcher = fetch_json,
    detail_fetcher: Optional[Fetcher] = None,
    on_raw_page: Optional[RawPageSink] = None,
    max_pages: Optional[int] = None,
) -> Iterator[HarvestedDataset]:
    detail_fetcher = detail_fetcher or fetcher
    if not config.native_api_url or not config.dataset_detail_url:
        raise ValueError(f"{config.country_code}: estonia_json needs native_api_url + dataset_detail_url")

    page = 1
    page_idx = 0
    total: Optional[int] = None
    collected = 0

    while True:
        url = config.native_api_url.format(page=page, page_size=config.page_size)
        listing = fetcher(url)
        items = listing.get("data") or []
        if total is None:
            total = (listing.get("metadata") or {}).get("total")
        if not items:
            break

        details: list[dict] = []
        for item in items:
            ident = item.get("id") or item.get("slug")
            if not ident:
                continue
            detail = detail_fetcher(config.dataset_detail_url.format(id=ident))
            details.append(detail)
            collected += 1

        if on_raw_page is not None:
            on_raw_page(page_idx, {"details": details})

        for d in details:
            yield normalise_estonia_detail(d, route=config.harvest_route)

        page += 1
        page_idx += 1
        if total is not None and collected >= total:
            break
        if max_pages is not None and page_idx >= max_pages:
            break
        if config.request_delay_s:
            time.sleep(config.request_delay_s)
