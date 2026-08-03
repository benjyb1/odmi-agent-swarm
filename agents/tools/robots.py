"""robots.txt compliance for the Researcher and Verifier fetch layer.

The swarm reads public pages on government open-data portals. Those pages
are published for people to read, but a portal operator still has a
standard way of saying which paths automated clients should leave alone,
and honouring it is ordinary good practice for a crawler that identifies
itself the way ours does.

This module is the single source of truth for "does robots.txt permit
this fetch". It sits alongside `blocked_domains`, which answers a
different question (does this URL leak ODMI's own answers). Both are
consulted before any network call in `agents.tools.fetch`.

Policy decisions, made explicitly rather than inherited:

- **Fail open.** If robots.txt cannot be retrieved, or the host returns a
  4xx, the fetch is allowed. A missing robots.txt is the conventional
  signal that everything is permitted, and a portal that is briefly down
  should not silently remove evidence from a run. The alternative, fail
  closed, drops pages for a reason that has nothing to do with the
  portal's wishes.
- **One retrieval per host per process.** The parsed result is cached, so
  a run that reads forty pages from one portal asks for robots.txt once.
  Negative results are cached too, so an unreachable robots.txt is not
  re-requested on every page.
- **Full User-Agent match.** `RobotFileParser` matches an agent line
  against a prefix of the string we pass, so passing the complete
  `DEFAULT_USER_AGENT` honours both a generic `User-agent: *` group and a
  group naming this crawler specifically.
- **Crawl-delay is read, not ignored.** `crawl_delay_s` exposes any delay
  the host asks for so callers can pace themselves. Hosts that specify
  nothing get no artificial delay.

Enforcement can be switched off with `ROBOTS_ENFORCED = False`. The test
suite does exactly that, so unit tests never reach for the network; the
tests covering this module turn it back on for their duration.
"""

from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

# Flipped to False by the test suite (see conftest.py) so that unit tests
# never make a robots.txt request. Production code leaves it True.
ROBOTS_ENFORCED = True

# How long to wait for a robots.txt. Deliberately shorter than a page
# fetch: robots is a small static file, and a host that is slow to serve
# it should not hold up the page we actually want.
ROBOTS_TIMEOUT_S = 5.0

# origin -> parser, or None when robots.txt could not be read (fail open).
_CACHE: dict[str, RobotFileParser | None] = {}


def _origin(url: str) -> str | None:
    """The scheme://host[:port] a robots.txt would live under, or None if
    the URL is not http(s)."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def _parser_for(origin: str, user_agent: str) -> RobotFileParser | None:
    """Fetch and parse the origin's robots.txt, or None when it cannot be
    read. Cached, including the None case."""
    if origin in _CACHE:
        return _CACHE[origin]

    parser: RobotFileParser | None = None
    try:
        with httpx.Client(
            timeout=ROBOTS_TIMEOUT_S,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        ) as client:
            resp = client.get(f"{origin}/robots.txt")
        if resp.status_code == 200:
            parser = RobotFileParser()
            parser.parse(resp.text.splitlines())
        # Any other status, including 404, means no usable rules: fail open
        # by leaving parser as None.
    except Exception:  # noqa: BLE001 - network failure must not stop a run
        parser = None

    _CACHE[origin] = parser
    return parser


def robots_disallows(url: str, user_agent: str) -> str | None:
    """Return a short reason string when robots.txt forbids fetching `url`,
    or None when the fetch is permitted.

    Permitted covers every fail-open case: enforcement switched off, a
    non-http URL, an unreachable robots.txt, or a robots.txt with no rule
    matching this path.
    """
    if not ROBOTS_ENFORCED:
        return None
    origin = _origin(url)
    if origin is None:
        return None
    parser = _parser_for(origin, user_agent)
    if parser is None:
        return None
    if parser.can_fetch(user_agent, url):
        return None
    return f"robots_disallowed:{urlparse(url).netloc}"


def crawl_delay_s(url: str, user_agent: str) -> float | None:
    """The crawl delay the host asks of this agent, in seconds, or None if
    it asks for none (or robots.txt could not be read)."""
    if not ROBOTS_ENFORCED:
        return None
    origin = _origin(url)
    if origin is None:
        return None
    parser = _parser_for(origin, user_agent)
    if parser is None:
        return None
    try:
        delay = parser.crawl_delay(user_agent)
    except Exception:  # noqa: BLE001 - malformed robots must not stop a run
        return None
    return float(delay) if delay is not None else None


def clear_cache() -> None:
    """Drop the per-origin robots cache. Used by tests, and available for a
    long-lived process that wants to re-read robots between runs."""
    _CACHE.clear()
