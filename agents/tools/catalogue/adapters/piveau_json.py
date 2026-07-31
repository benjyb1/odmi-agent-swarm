"""piveau hub-search adapter (AT): the data.europa.eu software family,
nationally hosted.

Austria's data.gv.at relaunched on piveau. The hub-search API pages the
dataset index as JSON (`/api/hub/search/search?filters=dataset`), and
each hit carries the distribution fields the presence metrics read:
`license.resource`, `format.resource/id`, `access_url[]`,
`download_url[]`. The `dataScope` facet on data.gv.at reports the whole
index as countryData (the eu and io scopes are empty), so no scope
filtering is needed there; a future piveau portal that does federate
EU-scope datasets must add a scope filter before computing metrics.

Conformance metrics (Q16/Q17/Q18) on this route run over DCAT-AP graphs
synthesised from the JSON, the same caveat as the CKAN/udata JSON routes.
Upgrade path: piveau also serves real per-dataset Turtle at
`/api/hub/repo/datasets/{id}.ttl`, but one GET per dataset across ~71k
datasets needs FDK-style sampling, so v1 stays on the JSON pages.
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


def _first(value: object) -> Optional[str]:
    """First entry of a piveau list field (access_url, download_url)."""
    if isinstance(value, list):
        for v in value:
            s = _clean(v)
            if s:
                return s
        return None
    return _clean(value)


def _ref(value: object) -> Optional[str]:
    """A piveau vocabulary reference: {'resource': URI, 'id': ..., 'label': ...}."""
    if isinstance(value, dict):
        return _clean(value.get("resource")) or _clean(value.get("id"))
    return _clean(value)


def _lang_text(value: object) -> Optional[str]:
    """A language-keyed text dict ({'en': ...} / {'de': ...}); first value."""
    if isinstance(value, dict):
        for v in value.values():
            s = _clean(v)
            if s:
                return s
        return None
    return _clean(value)


def normalise_piveau_dataset(
    hit: dict, *, route: str = "piveau_json"
) -> HarvestedDataset:
    """Map one hub-search hit onto a HarvestedDataset. Pure, offline."""
    identifier = _clean(hit.get("id")) or ""

    distributions: list[Distribution] = []
    for dist in hit.get("distributions") or []:
        if not isinstance(dist, dict):
            continue
        access = _first(dist.get("access_url"))
        distributions.append(
            Distribution(
                licence=_ref(dist.get("license") or dist.get("licence")),
                fmt=_ref(dist.get("format")),
                media_type=_ref(dist.get("media_type")),
                access_url=access,
                download_url=_first(dist.get("download_url")),
            )
        )

    publisher = hit.get("publisher") or {}
    extras = {
        "title": _lang_text(hit.get("title")),
        "description": _lang_text(hit.get("description")),
        "keywords": [k for k in (hit.get("keywords") or []) if _clean(k)],
        "publisher": _clean(publisher.get("name")) if isinstance(publisher, dict) else None,
        "issued": _clean(hit.get("issued")),
        "modified": _clean(hit.get("modified")),
    }

    return HarvestedDataset(
        identifier=identifier,
        dataset_licences=[],  # piveau carries licences on distributions
        distributions=distributions,
        source_route=route,
        extras={k: v for k, v in extras.items() if v},
    )


def normalise_page(payload: dict, *, route: str = "piveau_json") -> list[HarvestedDataset]:
    hits = ((payload.get("result") or {}).get("results")) or []
    return [
        normalise_piveau_dataset(h, route=route)
        for h in hits if isinstance(h, dict)
    ]


def harvest(
    config: PortalConfig,
    *,
    fetcher: Fetcher = fetch_json,
    on_raw_page: Optional[RawPageSink] = None,
    max_pages: Optional[int] = None,
) -> Iterator[HarvestedDataset]:
    """Page the hub-search index; stop at the first empty page."""
    if not config.native_api_url:
        raise ValueError(
            f"{config.country_code}: no native_api_url for piveau_json route"
        )
    page_idx = 0
    while True:
        url = config.native_api_url.format(
            page=page_idx, page_size=config.page_size
        )
        payload = fetcher(url)
        datasets = normalise_page(payload)
        if not datasets:
            break
        if on_raw_page is not None:
            on_raw_page(page_idx, payload)
        for d in datasets:
            yield d
        page_idx += 1
        if max_pages is not None and page_idx >= max_pages:
            break
        if config.request_delay_s:
            time.sleep(config.request_delay_s)
