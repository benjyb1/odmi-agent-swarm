"""Harvest orchestration with a gzipped disk cache (D30).

`harvest_country(cc)` picks the adapter for a country's route, streams the
raw pages to disk (gzipped), and writes a `catalogue_snapshots` receipt
row plus a `manifest.json`. `load_cached_snapshot(cc)` replays the most
recent cache into normalised records, so a metric computation is
reproducible from the cache alone, with no further network calls.

Snapshots live under `data/catalogue_snapshots/<CC>/<UTC-timestamp>/`,
which is gitignored: FR is ~74k datasets and DE ~151k, far too large to
commit. The committed receipt is the DB row and the manifest's checksums.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from agents.tools.catalogue.model import HarvestedDataset
from agents.tools.catalogue.registry import PortalConfig, load_portal
from agents.tools.db import connect

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CACHE_ROOT = _REPO_ROOT / "data" / "catalogue_snapshots"


# Adapter registry. Each route plugs in a harvest generator, a
# page-normaliser (for replay), and a page format ("json" | "rdf") so
# the cache writer knows how to serialise the raw page.


@dataclass(frozen=True)
class Adapter:
    harvest: Callable
    normalise_page: Callable
    page_format: str = "json"  # "json" -> dict pages; "rdf" -> raw bytes pages


def _build_adapter_registry() -> dict[str, Adapter]:
    from agents.tools.catalogue.adapters import ckan_json

    registry: dict[str, Adapter] = {
        "ckan_json": Adapter(ckan_json.harvest, ckan_json.normalise_page, "json"),
    }
    # The remaining routes (dcat_rdf, udata_json, estonia_json) register
    # here once their adapters land (build step 6).
    try:
        from agents.tools.catalogue.adapters import dcat_rdf
        registry["dcat_rdf"] = Adapter(
            dcat_rdf.harvest, dcat_rdf.normalise_page, "rdf"
        )
    except Exception:  # noqa: BLE001 - adapter not built yet
        pass
    try:
        from agents.tools.catalogue.adapters import udata_json
        registry["udata_json"] = Adapter(
            udata_json.harvest, udata_json.normalise_page, "json"
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        from agents.tools.catalogue.adapters import estonia_json
        registry["estonia_json"] = Adapter(
            estonia_json.harvest, estonia_json.normalise_page, "json"
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        from agents.tools.catalogue.adapters import sparql_rdf
        registry["sparql_rdf"] = Adapter(
            sparql_rdf.harvest, sparql_rdf.normalise_page, "rdf"
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        from agents.tools.catalogue.adapters import piveau_json
        registry["piveau_json"] = Adapter(
            piveau_json.harvest, piveau_json.normalise_page, "json"
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        from agents.tools.catalogue.adapters import al_dcat_api
        registry["al_dcat_api"] = Adapter(
            al_dcat_api.harvest, al_dcat_api.normalise_page, "json"
        )
    except Exception:  # noqa: BLE001
        pass
    return registry


@dataclass
class Snapshot:
    snapshot_id: str
    country_code: str
    harvest_route: str
    source_endpoint: str
    fetched_at: str
    cache_dir: Path
    page_count: int
    dataset_count: int
    content_sha256: str
    partial: bool
    datasets: list[HarvestedDataset] = field(default_factory=list)
    error: Optional[str] = None


def _utc_stamp() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def _page_bytes(payload: object, page_format: str) -> bytes:
    if page_format == "rdf":
        if isinstance(payload, bytes):
            return payload
        return str(payload).encode("utf-8")
    # JSON route: deterministic serialisation for a stable checksum.
    return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _ext(page_format: str) -> str:
    return "ttl" if page_format == "rdf" else "json"


def harvest_country(
    country_code: str,
    *,
    max_pages: Optional[int] = None,
    write_db: bool = True,
    delay_s: Optional[float] = None,
) -> Snapshot:
    """Harvest a country's catalogue to disk and return the snapshot.

    Writes one gzipped file per raw page plus a manifest, and (unless
    `write_db=False`) a `catalogue_snapshots` row. A network failure
    mid-harvest is caught: the snapshot is marked `partial` and whatever
    was collected is kept, rather than silently truncating to nothing.

    `delay_s` overrides the registry's per-request delay for this run (used
    by the FR validation, where the portal has no hard rate limit).
    """
    import dataclasses

    config = load_portal(country_code)
    if delay_s is not None:
        config = dataclasses.replace(config, request_delay_s=delay_s)
    adapter = _build_adapter_registry().get(config.harvest_route)
    if adapter is None:
        raise NotImplementedError(
            f"{config.country_code}: no adapter registered for route "
            f"{config.harvest_route!r} yet."
        )

    fetched_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    snapshot_id = f"{config.country_code}-{_utc_stamp()}"
    cache_dir = _CACHE_ROOT / config.country_code / snapshot_id
    cache_dir.mkdir(parents=True, exist_ok=True)

    hasher = hashlib.sha256()
    page_count = 0

    def _sink(idx: int, payload: object) -> None:
        nonlocal page_count
        raw = _page_bytes(payload, adapter.page_format)
        hasher.update(raw)
        fn = cache_dir / f"page-{idx:04d}.{_ext(adapter.page_format)}.gz"
        fn.write_bytes(gzip.compress(raw))
        page_count = max(page_count, idx + 1)

    datasets: list[HarvestedDataset] = []
    partial = False
    error: Optional[str] = None
    try:
        for ds in adapter.harvest(
            config, on_raw_page=_sink, max_pages=max_pages
        ):
            datasets.append(ds)
    except Exception as exc:  # noqa: BLE001 - surface a partial harvest
        partial = True
        error = f"{type(exc).__name__}: {exc}"[:300]
        print(f"[harvest] {config.country_code} partial: {error}", file=sys.stderr)

    source_endpoint = config.dcat_catalog_url or config.native_api_url or ""
    content_sha256 = hasher.hexdigest()

    manifest = {
        "snapshot_id": snapshot_id,
        "country_code": config.country_code,
        "harvest_route": config.harvest_route,
        "source_endpoint": source_endpoint,
        "fetched_at": fetched_at,
        "page_count": page_count,
        "dataset_count": len(datasets),
        "content_sha256": content_sha256,
        "partial": partial,
        "page_format": adapter.page_format,
        "error": error,
    }
    (cache_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    snapshot = Snapshot(
        snapshot_id=snapshot_id,
        country_code=config.country_code,
        harvest_route=config.harvest_route,
        source_endpoint=source_endpoint,
        fetched_at=fetched_at,
        cache_dir=cache_dir,
        page_count=page_count,
        dataset_count=len(datasets),
        content_sha256=content_sha256,
        partial=partial,
        datasets=datasets,
        error=error,
    )

    if write_db:
        _write_snapshot_row(snapshot)

    return snapshot


def _write_snapshot_row(s: Snapshot) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO catalogue_snapshots (
                snapshot_id, country_code, harvest_route, source_endpoint,
                fetched_at, dataset_count, page_count, content_sha256,
                cache_path, partial, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                s.snapshot_id, s.country_code, s.harvest_route, s.source_endpoint,
                s.fetched_at, s.dataset_count, s.page_count, s.content_sha256,
                str(s.cache_dir.relative_to(_REPO_ROOT)),
                1 if s.partial else 0,
                s.error,
            ),
        )
        conn.commit()


# Replay from cache


def find_latest_snapshot_dir(country_code: str) -> Optional[Path]:
    country_dir = _CACHE_ROOT / country_code.upper()
    if not country_dir.exists():
        return None
    snaps = sorted(p for p in country_dir.iterdir() if p.is_dir())
    return snaps[-1] if snaps else None


def load_cached_snapshot(
    country_code: str, *, snapshot_dir: Optional[Path] = None
) -> Optional[Snapshot]:
    """Replay the most recent (or a given) cached snapshot into records.

    Returns None if no cache exists. Re-runs the route's page normaliser
    over the gzipped raw pages; no network calls.
    """
    if snapshot_dir is None:
        snapshot_dir = find_latest_snapshot_dir(country_code)
    if snapshot_dir is None:
        return None

    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text())

    route = manifest["harvest_route"]
    page_format = manifest.get("page_format", "json")
    adapter = _build_adapter_registry().get(route)
    if adapter is None:
        raise NotImplementedError(f"No adapter for cached route {route!r}.")

    datasets: list[HarvestedDataset] = []
    page_files = sorted(snapshot_dir.glob(f"page-*.{_ext(page_format)}.gz"))
    for pf in page_files:
        raw = gzip.decompress(pf.read_bytes())
        if page_format == "rdf":
            datasets.extend(adapter.normalise_page(raw, route=route))
        else:
            payload = json.loads(raw.decode("utf-8"))
            datasets.extend(adapter.normalise_page(payload, route=route))

    return Snapshot(
        snapshot_id=manifest["snapshot_id"],
        country_code=manifest["country_code"],
        harvest_route=route,
        source_endpoint=manifest.get("source_endpoint", ""),
        fetched_at=manifest.get("fetched_at", ""),
        cache_dir=snapshot_dir,
        page_count=manifest.get("page_count", len(page_files)),
        dataset_count=len(datasets),
        content_sha256=manifest.get("content_sha256", ""),
        partial=bool(manifest.get("partial", False)),
        datasets=datasets,
        error=manifest.get("error"),
    )


def get_snapshot(
    country_code: str, *, refresh: bool = False, max_pages: Optional[int] = None
) -> Snapshot:
    """Return a usable snapshot: the cached one, or a fresh harvest.

    `refresh=True` always harvests. Otherwise the most recent cache is
    replayed if present, else a harvest runs.
    """
    if not refresh:
        cached = load_cached_snapshot(country_code)
        if cached is not None and cached.datasets:
            return cached
    return harvest_country(country_code, max_pages=max_pages)


# CLI


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Harvest a national catalogue (D30).")
    parser.add_argument("country_code", help="e.g. FR, DE, NL")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Cap the number of pages (smoke test).")
    parser.add_argument("--no-db", action="store_true",
                        help="Do not write a catalogue_snapshots row.")
    parser.add_argument("--from-cache", action="store_true",
                        help="Replay the latest cache instead of harvesting.")
    args = parser.parse_args()

    if args.from_cache:
        snap = load_cached_snapshot(args.country_code)
        if snap is None:
            print(f"No cache for {args.country_code}.")
            return 1
    else:
        snap = harvest_country(
            args.country_code, max_pages=args.max_pages, write_db=not args.no_db
        )

    print(f"snapshot_id     {snap.snapshot_id}")
    print(f"route           {snap.harvest_route}")
    print(f"endpoint        {snap.source_endpoint}")
    print(f"pages           {snap.page_count}")
    print(f"datasets        {snap.dataset_count}")
    print(f"sha256          {snap.content_sha256[:16]}...")
    print(f"partial         {snap.partial}")
    print(f"cache_dir       {snap.cache_dir}")
    if snap.error:
        print(f"error           {snap.error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
