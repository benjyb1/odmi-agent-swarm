"""Emit a verified discovery outcome as a portal registry file.

The output is the same shape as the six hand-authored
`data/catalogue/portals/<CC>.json` files, so `registry.load_portal` and
the harvest pipeline pick it up unchanged. Three extra keys record the
provenance: `discovery_method` ("auto"), `discovery_evidence` (what the
fingerprint matched) and `caveats` (the machine-readable list backing the
prose in `notes`). `load_portal` reads named keys only, so the extras are
inert to the harvest.

Leakage gate: every URL in the outgoing registry is checked against the
D24 deny-list before a byte is written. A registry that points the
harvester at data.europa.eu or a mirror must be impossible to produce.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

from agents.tools.blocked_domains import blocked_reason, is_blocked
from agents.tools.catalogue import _fetch
from agents.tools.catalogue._fetch import BlockedEndpointError
from agents.tools.catalogue.discovery.verify import DiscoveryOutcome

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PORTALS_DIR = _REPO_ROOT / "data" / "catalogue" / "portals"


def _guard_urls(payload: dict) -> None:
    """Refuse any deny-listed URL anywhere in the outgoing registry."""
    def walk(value: object) -> None:
        if isinstance(value, str) and "://" in value:
            # Endpoint templates carry {page}-style placeholders; the host
            # is what the deny-list checks, so guard the template as-is.
            if is_blocked(value):
                raise BlockedEndpointError(
                    "refusing to emit registry with deny-listed URL "
                    f"({blocked_reason(value)}): {value}"
                )
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                walk(v)

    walk(payload)


def _robots_note(portal_base: str, robots_fetcher) -> str:
    """Summarise the portal's robots.txt for the registry receipt.

    Records the lines that matter to a polite harvester (Disallow on API
    paths, Crawl-delay); an unreachable robots.txt is recorded as absent,
    the same convention the EE hand-authored registry uses."""
    try:
        raw = robots_fetcher(f"{portal_base}/robots.txt")
    except Exception:  # noqa: BLE001 - absence is a finding, not an error
        return "No robots.txt reachable at probe time. Throttle, descriptive UA."
    text = raw.decode("utf-8", errors="replace")[:4000]
    interesting = [
        line.strip()
        for line in text.splitlines()
        if line.strip().lower().startswith(("disallow:", "crawl-delay:"))
        and ("api" in line.lower() or "crawl-delay" in line.lower()
             or line.strip().rstrip() in ("Disallow: /", "Disallow: *"))
    ]
    if not interesting:
        return ("robots.txt present, no Disallow on the API paths used. "
                "Throttle, descriptive UA.")
    return ("robots.txt: " + "; ".join(interesting[:6])
            + ". Throttle, descriptive UA.")


def _notes(outcome: DiscoveryOutcome) -> str:
    chosen = outcome.chosen
    assert chosen is not None
    stats = chosen.stats
    parts = [
        f"Auto-discovered route ({chosen.evidence.stack}): {chosen.evidence.detail}.",
        (
            f"Sample of {stats.n_datasets} datasets: "
            f"licence {stats.licence_share:.0%}, "
            f"access-URL {stats.access_url_share:.0%}, "
            f"download-URL {stats.download_url_share:.0%}, "
            f"format {stats.format_share:.0%}."
        ),
    ]
    if chosen.caveats:
        parts.append("Caveats: " + ", ".join(chosen.caveats) + ".")
    if outcome.rejected:
        parts.append(
            "Rejected routes: "
            + "; ".join(f"{r.route} ({r.reason})" for r in outcome.rejected)
            + "."
        )
    parts.append("data.europa.eu not used (D24).")
    return " ".join(parts)


def emit_registry(
    outcome: DiscoveryOutcome,
    *,
    portals_dir: Path = DEFAULT_PORTALS_DIR,
    force: bool = False,
    verified_at: Optional[str] = None,
    robots_fetcher=_fetch.fetch_bytes,
) -> Path:
    """Write `<CC>.json` for a verified outcome and return the path.

    Refuses an unverified outcome, an existing file unless `force` (the
    six hand-authored registries must never be clobbered by accident),
    and any deny-listed URL in the payload.
    """
    if outcome.status != "verified" or outcome.chosen is None:
        raise ValueError(
            f"cannot emit registry for {outcome.country_code}: "
            f"status is {outcome.status!r}"
        )
    chosen = outcome.chosen
    stats = chosen.stats
    cf = chosen.evidence.config_fields

    licence_field = (
        "distribution"
        if stats.distribution_licence_share > stats.dataset_licence_share
        else "dataset"
    )

    payload = {
        "country_code": outcome.country_code,
        "country_name": outcome.country_name,
        "portal_base": outcome.portal_base,
        "stack": chosen.evidence.stack,
        "stack_version": None,
        "harvest_route": chosen.route,
        "dcat_catalog_url": cf.get("dcat_catalog_url"),
        "native_api_url": cf.get("native_api_url"),
        "dataset_detail_url": cf.get("dataset_detail_url"),
        "pagination": cf.get("pagination", ""),
        "page_size": int(cf.get("page_size", 100)),
        "request_delay_s": 1.0,
        "total_datasets_hint": chosen.evidence.total_datasets,
        "licence_field": licence_field,
        "robots_note": _robots_note(outcome.portal_base, robots_fetcher),
        "verified_at": verified_at or date.today().isoformat(),
        "discovery_method": "auto",
        "discovery_evidence": f"{chosen.evidence.endpoint} -> {chosen.evidence.detail}",
        "caveats": list(chosen.caveats),
        "notes": _notes(outcome),
    }
    payload = {k: v for k, v in payload.items() if v is not None or k in (
        "dcat_catalog_url", "native_api_url", "stack_version"
    )}
    _guard_urls(payload)

    portals_dir.mkdir(parents=True, exist_ok=True)
    path = portals_dir / f"{outcome.country_code}.json"
    if path.exists() and not force:
        raise FileExistsError(
            f"{path} already exists; pass force=True to overwrite a "
            "hand-authored or previously discovered registry"
        )
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return path
