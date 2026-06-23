"""Client for the WHO IRIS repository (DSpace 7.6 REST API), scoped to the
Regional Office for Europe.

Stage 0 of the pipeline. It identifies and fetches a bounded country slice:
faceted search for items "about" a country (the MeSH heading, which is the
precise field; free-text country search is a near-zero-precision recall
sponge), reads each item's licence, and downloads the ORIGINAL-bundle PDFs.

Politeness and the licensing posture are baked in (see config). This is for a
one-off, bounded PoC slice; corpus-scale harvesting needs WHO sign-off.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

from who_speech import config
from who_speech.models import Bitstream, IrisItem


# --- response parsing --------------------------------------------------------

def _objects(data: dict) -> list[dict]:
    """The list of search hits, tolerant of the two DSpace envelope shapes."""
    emb = data.get("_embedded", {})
    if "objects" in emb:
        return emb["objects"]
    return emb.get("searchResult", {}).get("_embedded", {}).get("objects", [])


def _page_block(data: dict) -> dict:
    if "page" in data:
        return data["page"]
    return data.get("_embedded", {}).get("searchResult", {}).get("page", {})


def _first(meta: dict, key: str) -> Optional[str]:
    vals = meta.get(key)
    return vals[0].get("value") if vals else None


def _all(meta: dict, key: str) -> list[str]:
    return [v.get("value") for v in meta.get(key, []) if v.get("value")]


def _year(meta: dict) -> Optional[int]:
    raw = _first(meta, "dc.date.issued")
    if not raw:
        return None
    head = raw.strip()[:4]
    return int(head) if head.isdigit() else None


def _item_from_indexable(obj: dict) -> IrisItem:
    meta = obj.get("metadata", {})
    return IrisItem(
        uuid=obj.get("uuid") or obj.get("id"),
        handle=obj.get("handle"),
        title=_first(meta, "dc.title") or "(untitled)",
        year=_year(meta),
        language=_first(meta, "dc.language.iso"),
        item_type=_first(meta, "dc.type"),
        rights=_first(meta, "dc.rights"),
        rights_uri=_first(meta, "dc.rights.uri"),
        mesh=_all(meta, "dc.subject.mesh"),
        authors=_all(meta, "dc.contributor.author"),
        abstract=_first(meta, "dc.description.abstract"),
    )


# --- client ------------------------------------------------------------------

class IrisClient:
    """Thin, polite wrapper over the DSpace REST API."""

    def __init__(self, delay: float = config.IRIS_REQUEST_DELAY_S) -> None:
        self._delay = delay
        self._last = 0.0
        self._http = httpx.Client(
            headers={"Accept": "application/json", "User-Agent": config.IRIS_USER_AGENT},
            timeout=60.0,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "IrisClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        wait = self._delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _get(self, url: str, params: Optional[list] = None) -> dict:
        last: Optional[httpx.Response] = None
        for attempt in range(3):
            self._throttle()
            last = self._http.get(url, params=params)
            if last.status_code == 200:
                return last.json()
            if last.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            break
        assert last is not None
        last.raise_for_status()
        return {}

    # --- search / count ------------------------------------------------------

    def _search_page(
        self,
        *,
        query: Optional[str] = None,
        scope: Optional[str] = config.EURO_SCOPE,
        filters: Optional[dict] = None,
        page: int = 0,
        size: int = config.IRIS_PAGE_SIZE,
        sort: Optional[str] = None,
    ) -> dict:
        params: list[tuple[str, str]] = [
            ("dsoType", "item"),
            ("page", str(page)),
            ("size", str(size)),
        ]
        if query:
            params.append(("query", query))
        if scope:
            params.append(("scope", scope))
        if sort:
            params.append(("sort", sort))
        # A filter value may be a plain term ("Kyrgyzstan") or a range
        # ("[2020 TO 2026]"); both take the ",equals" operator.
        for facet, value in (filters or {}).items():
            params.append((f"f.{facet}", f"{value},equals"))
        return self._get(config.IRIS_SEARCH, params=params)

    def count(
        self,
        *,
        query: Optional[str] = None,
        scope: Optional[str] = config.EURO_SCOPE,
        filters: Optional[dict] = None,
    ) -> int:
        data = self._search_page(query=query, scope=scope, filters=filters, size=1)
        return int(_page_block(data).get("totalElements", 0))

    def search(
        self,
        *,
        query: Optional[str] = None,
        scope: Optional[str] = config.EURO_SCOPE,
        filters: Optional[dict] = None,
        sort: str = "dc.date.issued,DESC",
        max_items: Optional[int] = None,
    ) -> list[IrisItem]:
        items: list[IrisItem] = []
        page = 0
        while True:
            data = self._search_page(
                query=query, scope=scope, filters=filters,
                page=page, size=config.IRIS_PAGE_SIZE, sort=sort,
            )
            objs = _objects(data)
            if not objs:
                break
            for o in objs:
                indexable = o.get("_embedded", {}).get("indexableObject", {})
                if indexable:
                    items.append(_item_from_indexable(indexable))
                    if max_items and len(items) >= max_items:
                        return items
            block = _page_block(data)
            if page + 1 >= int(block.get("totalPages", 0)):
                break
            page += 1
        return items

    # --- bitstreams ----------------------------------------------------------

    def pdf_bitstreams(self, item_uuid: str) -> list[Bitstream]:
        """PDF files in the item's ORIGINAL bundle (main doc + any annexes)."""
        data = self._get(f"{config.IRIS_ITEM}/{item_uuid}/bundles", params=[("size", "50")])
        out: list[Bitstream] = []
        for bundle in data.get("_embedded", {}).get("bundles", []):
            if bundle.get("name") != "ORIGINAL":
                continue
            streams = self._get(
                f"{config.IRIS_BUNDLES}/{bundle['uuid']}/bitstreams",
                params=[("size", "100")],
            )
            for s in streams.get("_embedded", {}).get("bitstreams", []):
                name = s.get("name", "")
                if not name.lower().endswith(".pdf"):
                    continue
                out.append(
                    Bitstream(
                        uuid=s["uuid"],
                        name=name,
                        size_bytes=s.get("sizeBytes"),
                        content_url=config.IRIS_BITSTREAM_CONTENT.format(uuid=s["uuid"]),
                    )
                )
        return out

    def download(self, bitstream: Bitstream) -> bytes:
        self._throttle()
        resp = self._http.get(bitstream.content_url)
        resp.raise_for_status()
        return resp.content

    # --- convenience ---------------------------------------------------------

    def country_slice(
        self,
        mesh_heading: str,
        *,
        year_range: Optional[tuple[int, int]] = None,
        language: Optional[str] = None,
        quotable_only: bool = False,
        max_items: Optional[int] = None,
        attach_bitstreams: bool = True,
    ) -> list[IrisItem]:
        """The bounded slice for a country: items 'about' it, newest first.

        `mesh_heading` must be the exact MeSH geographic heading (e.g.
        'Republic of North Macedonia', 'Georgia (Republic)'), not always the
        common country name.
        """
        filters: dict[str, str] = {"mesh": mesh_heading}
        if year_range:
            filters["dateIssued"] = f"[{year_range[0]} TO {year_range[1]}]"
        if language:
            filters["language"] = language
        items = self.search(filters=filters, max_items=max_items)
        if quotable_only:
            items = [it for it in items if it.quotable]
        if attach_bitstreams:
            for it in items:
                it.pdf_bitstreams = self.pdf_bitstreams(it.uuid)
        return items


if __name__ == "__main__":
    # Smoke test against live IRIS: confirm counts, parsing, licence read,
    # and a real PDF download for the Kyrgyzstan demo slice.
    with IrisClient() as iris:
        mesh = "Kyrgyzstan"
        total = iris.count(filters={"mesh": mesh})
        recent = iris.count(filters={"mesh": mesh, "dateIssued": "[2020 TO 2026]"})
        print(f"{mesh}: {total} items about (MeSH), {recent} since 2020")

        items = iris.search(
            filters={"mesh": mesh, "dateIssued": "[2020 TO 2026]"}, max_items=8
        )
        print(f"\nNewest {len(items)} items:")
        for it in items:
            print(f"  [{it.year}] {it.title[:72]}")
            print(f"        lang={it.language} rights={it.rights} quotable={it.quotable}")

        if items:
            first = items[0]
            streams = iris.pdf_bitstreams(first.uuid)
            print(f"\nORIGINAL PDFs on '{first.title[:50]}': "
                  f"{[(b.name, b.size_bytes) for b in streams]}")
            if streams:
                blob = iris.download(streams[0])
                print(f"downloaded {len(blob)} bytes; header={blob[:5]!r}")
