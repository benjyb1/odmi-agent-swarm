"""Hard deny-list for ODMI data-leakage avoidance.

The swarm validates its own answers against ODMI's published responses
in `ground_truth`. Any source that quotes, mirrors, archives, or cites
ODMI's own published answers therefore leaks the very signal we are
trying to predict.

This module is the single source of truth for "do not look here". It is
imported by `agents.tools.search`, `agents.tools.fetch`, and
`agents.tools.validator`, plus the audit script
`scripts/check_data_leakage.py`. The deny-list is intentionally a hard
rule: a blocked URL is never fetched, never scored, never shown to a
prompt.

Update policy. New entries to `BLOCKED_DOMAINS` or
`BLOCKED_PATH_FRAGMENTS` require a numbered SPEC.md decision. The list
should grow over time as new mirrors surface; it should never shrink
without a written rationale in SPEC.md.
"""

from __future__ import annotations

from urllib.parse import urlparse


# Hard ban. Any URL whose hostname matches one of these (exact or as a
# suffix after a leading dot) is refused at the search, fetch, and
# validator layers.
BLOCKED_DOMAINS: tuple[str, ...] = (
    # ODMI's own publishing surface on the EU Data Portal.
    "data.europa.eu",
    # Legacy redirect, still cited in older policy documents.
    "europeandataportal.eu",
    # EU Publications Office surfaces that host the annual ODMI report.
    "publications.europa.eu",
    "op.europa.eu",
    # Web archive caches that can return ODMI content even after the
    # source page is moved or taken down.
    "web.archive.org",
    "archive.org",
    "archive.today",
    "archive.ph",
    "archive.is",
    "webcache.googleusercontent.com",
    "cachedview.com",
    "cache.google.com",
)


# URL path fragments that are suspicious regardless of host. Catches
# republished ODMI material on third-party domains, third-party blog
# write-ups of the ODMI ranking, and Capgemini's own report-hosting
# pages.
BLOCKED_PATH_FRAGMENTS: tuple[str, ...] = (
    "/open-data-maturity",
    "/odmi",
    "open-data-maturity-report",
    "open-data-maturity-index",
    "2025_odm_questionnaire",
    "2024_odm_questionnaire",
    "merged_responses",
)


def _normalise_host(host: str | None) -> str:
    if not host:
        return ""
    host = host.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def is_blocked(url: str) -> bool:
    """Return True if `url` lands on the hard deny-list.

    A URL is blocked if its host matches a `BLOCKED_DOMAINS` entry
    exactly, sits underneath one as a subdomain, or its path contains
    one of `BLOCKED_PATH_FRAGMENTS`. Falls open (returns False) on a
    URL we cannot parse; the search and fetch layers handle malformed
    URLs separately.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    host = _normalise_host(parsed.hostname)
    if host:
        for d in BLOCKED_DOMAINS:
            if host == d or host.endswith("." + d):
                return True
    path = (parsed.path or "").lower()
    for frag in BLOCKED_PATH_FRAGMENTS:
        if frag in path:
            return True
    return False


def blocked_reason(url: str) -> str | None:
    """Return a short tag identifying why a URL is blocked, for logs."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return None
    host = _normalise_host(parsed.hostname)
    for d in BLOCKED_DOMAINS:
        if host == d or host.endswith("." + d):
            return f"domain:{d}"
    path = (parsed.path or "").lower()
    for frag in BLOCKED_PATH_FRAGMENTS:
        if frag in path:
            return f"path:{frag}"
    return None


def filter_blocked(urls: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Split a list of URLs into (allowed, dropped_with_reason)."""
    allowed: list[str] = []
    dropped: list[tuple[str, str]] = []
    for u in urls:
        reason = blocked_reason(u)
        if reason is None:
            allowed.append(u)
        else:
            dropped.append((u, reason))
    return allowed, dropped
