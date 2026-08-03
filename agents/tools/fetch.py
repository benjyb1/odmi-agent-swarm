"""URL fetching shared by Researcher and Verifier.

Two backends:

- `fetch_text`: httpx GET with a polite User-Agent. The default. Fast
  and stateless. Returns the response body as text, capped.
- `fetch_rendered_text` (lazy import of Playwright): JS-rendered fetch
  for portals that put their content behind dynamic rendering. Used
  as a fallback when `fetch_text` returns a near-empty body or a
  CAPTCHA marker.

Both return a `FetchResult` so the caller can log the failure mode if
the fetch did not produce usable content.
"""

from __future__ import annotations

import re
import time
from typing import Literal, Optional

import httpx
from pydantic import BaseModel

from agents.tools.blocked_domains import blocked_reason, is_blocked
from agents.tools.robots import robots_disallows

DEFAULT_USER_AGENT = (
    "ODMI-Swarm-Research/0.1 "
    "(MSc dissertation; King's College London; "
    "contact: benjaminbream@gmail.com)"
)

DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_CHARS = 4000
# Raw-HTML cap for the DIY pipeline. Generous: trafilatura needs the whole
# DOM to find main content, so we must not truncate before extraction. Set
# high enough to keep real pages intact (observed pages run to ~900 KB) while
# still bounding pathological responses.
RAW_HTML_MAX_CHARS = 2_000_000


FetchBackend = Literal["httpx", "playwright"]


class FetchResult(BaseModel):
    url: str
    backend: FetchBackend
    status_code: int                      # 0 if the fetch never completed
    content: str                          # truncated to max_chars
    truncated: bool
    failure_mode: Optional[str] = None    # null on success


def _blocked_result(url: str, backend: FetchBackend) -> FetchResult:
    reason = blocked_reason(url) or "blocked"
    return FetchResult(
        url=url,
        backend=backend,
        status_code=0,
        content="",
        truncated=False,
        failure_mode=f"blocked_data_leakage:{reason}",
    )


def _robots_result(url: str, backend: FetchBackend, reason: str) -> FetchResult:
    """A refusal caused by the host's robots.txt rather than by our own
    deny-list. Kept as a distinct failure mode so the two never blur in the
    logs: one is the portal's instruction, the other is our leakage guard."""
    return FetchResult(
        url=url,
        backend=backend,
        status_code=0,
        content="",
        truncated=False,
        failure_mode=reason,
    )


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _html_to_text(html: str, max_chars: int) -> tuple[str, bool]:
    text = _TAG_RE.sub(" ", html)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


def fetch_text(
    url: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> FetchResult:
    """Plain httpx GET. Returns text content with HTML tags stripped.

    Refuses URLs on the data-leakage deny-list before any network call.
    """
    if is_blocked(url):
        return _blocked_result(url, "httpx")
    disallowed = robots_disallows(url, DEFAULT_USER_AGENT)
    if disallowed:
        return _robots_result(url, "httpx", disallowed)
    try:
        with httpx.Client(
            timeout=timeout_s,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        ) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            return FetchResult(
                url=url,
                backend="httpx",
                status_code=resp.status_code,
                content="",
                truncated=False,
                failure_mode=f"http_status_{resp.status_code}",
            )
        text, truncated = _html_to_text(resp.text, max_chars)
        if not text.strip():
            return FetchResult(
                url=url,
                backend="httpx",
                status_code=200,
                content="",
                truncated=False,
                failure_mode="empty_after_strip",
            )
        return FetchResult(
            url=url,
            backend="httpx",
            status_code=200,
            content=text,
            truncated=truncated,
            failure_mode=None,
        )
    except httpx.TimeoutException:
        return FetchResult(
            url=url, backend="httpx", status_code=0, content="",
            truncated=False, failure_mode="timeout",
        )
    except httpx.HTTPError as exc:
        return FetchResult(
            url=url, backend="httpx", status_code=0, content="",
            truncated=False, failure_mode=f"http_error:{type(exc).__name__}",
        )


def fetch_html(
    url: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_chars: int = RAW_HTML_MAX_CHARS,
) -> FetchResult:
    """Plain httpx GET returning RAW HTML, tags intact.

    Unlike `fetch_text`, this does not strip tags and uses a generous cap.
    The DIY-Tavily pipeline needs the full DOM so trafilatura can locate the
    main content; stripping tags or capping at 4000 chars (as `fetch_text`
    does) destroys the structure before extraction can run.

    Refuses URLs on the data-leakage deny-list before any network call.
    """
    if is_blocked(url):
        return _blocked_result(url, "httpx")
    disallowed = robots_disallows(url, DEFAULT_USER_AGENT)
    if disallowed:
        return _robots_result(url, "httpx", disallowed)
    try:
        with httpx.Client(
            timeout=timeout_s,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        ) as client:
            resp = client.get(url)
        if resp.status_code != 200:
            return FetchResult(
                url=url,
                backend="httpx",
                status_code=resp.status_code,
                content="",
                truncated=False,
                failure_mode=f"http_status_{resp.status_code}",
            )
        html = resp.text
        truncated = len(html) > max_chars
        html = html[:max_chars] if truncated else html
        if not html.strip():
            return FetchResult(
                url=url, backend="httpx", status_code=200, content="",
                truncated=False, failure_mode="empty_after_strip",
            )
        return FetchResult(
            url=url, backend="httpx", status_code=200, content=html,
            truncated=truncated, failure_mode=None,
        )
    except httpx.TimeoutException:
        return FetchResult(
            url=url, backend="httpx", status_code=0, content="",
            truncated=False, failure_mode="timeout",
        )
    except httpx.HTTPError as exc:
        return FetchResult(
            url=url, backend="httpx", status_code=0, content="",
            truncated=False, failure_mode=f"http_error:{type(exc).__name__}",
        )


# Anti-automation hardening for the Playwright fallback. Cloudflare's passive
# JS challenge (seen on data.gov.mt) clears for a real browser but is quicker to
# refuse an obviously-automated one. These options make the headless browser
# look ordinary; the settle step waits out the challenge redirect to content.
_PW_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
_PW_CONTEXT_KWARGS = {
    "locale": "en-GB",
    "timezone_id": "Europe/London",
    "viewport": {"width": 1280, "height": 800},
}
_CF_CHALLENGE_MARKERS = (
    "Attention Required", "cf-browser-verification", "challenge-platform",
    "Just a moment", "_cf_chl_",
)


def _challenge_unresolved(body: str) -> bool:
    """True if the rendered body still carries a Cloudflare / WAF challenge
    marker after the settle wait. A body that is still the interstitial is not
    usable content: returning it as a 200 success would poison the fetch cache
    with challenge HTML (FM register: WAF challenge cached as evidence)."""
    return any(marker in body for marker in _CF_CHALLENGE_MARKERS)


def _goto_status(resp, default: int = 200) -> int:
    """The real HTTP status from a Playwright goto Response, or `default` when
    the navigation returned no response (data: URLs, some redirects) or a
    test double whose status is not an integer."""
    status = getattr(resp, "status", None)
    return status if isinstance(status, int) else default


def _settle_through_challenge(page, remaining_s: float) -> str:
    """Return the page HTML, waiting out a Cloudflare passive challenge when
    the first paint is the interstitial rather than the real page.

    `remaining_s` is what is left of the caller's TOTAL render budget. The
    settle waits are bounded by it, so a challenge that refuses to clear can
    never drag the fetch past the budget. The D43 stage ceiling arithmetic
    (search_diy.py) assumes this bound holds; before 2026-06-11 the waits sat
    on top of the goto timeout and a challenged URL could spend goto + 4s +
    networkidle, roughly 2.3x the nominal render timeout, which is what blew
    the 30s ceiling and killed batches."""
    body = page.content()
    if _challenge_unresolved(body) and remaining_s > 1.0:
        try:
            settle_ms = min(4000, int(remaining_s * 1000 / 2))
            page.wait_for_timeout(settle_ms)
            idle_ms = int(remaining_s * 1000) - settle_ms
            if idle_ms > 500:
                page.wait_for_load_state("networkidle", timeout=idle_ms)
        except Exception:  # noqa: BLE001
            pass
        body = page.content()
    return body


def fetch_rendered_text(
    url: str,
    *,
    timeout_s: float = 30.0,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> FetchResult:
    """Playwright fallback for JS-heavy portals. Lazy-imports Playwright.

    Use only when `fetch_text` returns an empty body or a known
    CAPTCHA/blocking marker. Slower than httpx.

    Refuses URLs on the data-leakage deny-list before launching a
    browser.
    """
    if is_blocked(url):
        return _blocked_result(url, "playwright")
    disallowed = robots_disallows(url, DEFAULT_USER_AGENT)
    if disallowed:
        return _robots_result(url, "playwright", disallowed)
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError as exc:
        return FetchResult(
            url=url, backend="playwright", status_code=0, content="",
            truncated=False,
            failure_mode=f"playwright_not_installed:{exc}",
        )

    try:
        # `timeout_s` is a TOTAL budget: driver start, browser launch, goto,
        # and the challenge-settle waits all draw from it. Launch time is the
        # piece that balloons under concurrency (several coordinators starting
        # Chromium at once), and before 2026-06-11 it sat outside every
        # timeout, so the D43 per-URL bound did not actually hold.
        start = time.monotonic()
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, args=_PW_LAUNCH_ARGS, timeout=timeout_s * 1000
            )
            context = browser.new_context(
                user_agent=DEFAULT_USER_AGENT, **_PW_CONTEXT_KWARGS
            )
            page = context.new_page()
            try:
                remaining = timeout_s - (time.monotonic() - start)
                if remaining <= 0.5:
                    raise PWTimeout("render budget exhausted before goto")
                resp = page.goto(url, timeout=remaining * 1000, wait_until="domcontentloaded")
                page.wait_for_timeout(500)  # let JS settle briefly
                body = _settle_through_challenge(
                    page, timeout_s - (time.monotonic() - start)
                )
                status = _goto_status(resp)
            except PWTimeout:
                return FetchResult(
                    url=url, backend="playwright", status_code=0, content="",
                    truncated=False, failure_mode="timeout",
                )
            finally:
                context.close()
                browser.close()
        if _challenge_unresolved(body):
            return FetchResult(
                url=url, backend="playwright", status_code=status, content="",
                truncated=False, failure_mode="waf_challenge_unresolved",
            )
        text, truncated = _html_to_text(body, max_chars)
        if not text.strip():
            return FetchResult(
                url=url, backend="playwright", status_code=status,
                content="", truncated=False, failure_mode="empty_after_strip",
            )
        return FetchResult(
            url=url, backend="playwright", status_code=status,
            content=text, truncated=truncated, failure_mode=None,
        )
    except Exception as exc:  # noqa: BLE001
        return FetchResult(
            url=url, backend="playwright", status_code=0, content="",
            truncated=False, failure_mode=f"playwright_error:{type(exc).__name__}:{exc}",
        )


def fetch_rendered_html(
    url: str,
    *,
    timeout_s: float = 30.0,
    max_chars: int = RAW_HTML_MAX_CHARS,
) -> FetchResult:
    """Playwright fallback returning RAW rendered HTML, tags intact.

    The raw-HTML counterpart of `fetch_rendered_text`, for the DIY pipeline:
    JS-heavy portals need a rendered DOM, and trafilatura needs that DOM
    intact (not tag-stripped) to find the main content.

    Refuses URLs on the data-leakage deny-list before launching a browser.
    """
    if is_blocked(url):
        return _blocked_result(url, "playwright")
    disallowed = robots_disallows(url, DEFAULT_USER_AGENT)
    if disallowed:
        return _robots_result(url, "playwright", disallowed)
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError as exc:
        return FetchResult(
            url=url, backend="playwright", status_code=0, content="",
            truncated=False, failure_mode=f"playwright_not_installed:{exc}",
        )

    try:
        # Same total-budget discipline as fetch_rendered_text: launch, goto,
        # and settle all draw from `timeout_s`, so the DIY stage ceiling
        # arithmetic in search_diy.py holds (D43).
        start = time.monotonic()
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, args=_PW_LAUNCH_ARGS, timeout=timeout_s * 1000
            )
            context = browser.new_context(
                user_agent=DEFAULT_USER_AGENT, **_PW_CONTEXT_KWARGS
            )
            page = context.new_page()
            try:
                remaining = timeout_s - (time.monotonic() - start)
                if remaining <= 0.5:
                    raise PWTimeout("render budget exhausted before goto")
                resp = page.goto(url, timeout=remaining * 1000, wait_until="domcontentloaded")
                page.wait_for_timeout(500)  # let JS settle briefly
                body = _settle_through_challenge(
                    page, timeout_s - (time.monotonic() - start)
                )
                status = _goto_status(resp)
            except PWTimeout:
                return FetchResult(
                    url=url, backend="playwright", status_code=0, content="",
                    truncated=False, failure_mode="timeout",
                )
            finally:
                context.close()
                browser.close()
        if _challenge_unresolved(body):
            return FetchResult(
                url=url, backend="playwright", status_code=status, content="",
                truncated=False, failure_mode="waf_challenge_unresolved",
            )
        truncated = len(body) > max_chars
        body = body[:max_chars] if truncated else body
        if not body.strip():
            return FetchResult(
                url=url, backend="playwright", status_code=status,
                content="", truncated=False, failure_mode="empty_after_strip",
            )
        return FetchResult(
            url=url, backend="playwright", status_code=status,
            content=body, truncated=truncated, failure_mode=None,
        )
    except Exception as exc:  # noqa: BLE001
        return FetchResult(
            url=url, backend="playwright", status_code=0, content="",
            truncated=False, failure_mode=f"playwright_error:{type(exc).__name__}:{exc}",
        )


# Status codes a Cloudflare / WAF challenge returns to a non-browser
# client. A real browser executing the challenge JS clears them, so a
# Playwright render is the right tie-breaker before calling a URL dead.
_WAF_BLOCK_STATUSES = frozenset({403, 429, 503})


def head_ok(url: str, *, timeout_s: float = 8.0) -> tuple[bool, int]:
    """HEAD-check that a URL returns HTTP 200. Used by the Researcher's
    post-call validation per AGENT_DESIGN section 3.5.

    Returns (ok, status_code). Some servers reject HEAD; on 4xx/5xx we
    fall back to a small GET so we don't misclassify a working URL.

    A WAF block (403/429/503 from a Cloudflare-style challenge) is not
    proof the URL is dead: government portals such as data.gov.mt 403 every
    non-browser client but serve a real browser fine. On those statuses we
    confirm with a Playwright render before reporting the URL unreachable,
    so a reachable-but-WAF-protected source is not lost as `url_unreachable`.

    Refuses URLs on the data-leakage deny-list before any network call.
    """
    if is_blocked(url):
        return False, 0
    if robots_disallows(url, DEFAULT_USER_AGENT):
        return False, 0
    status = 0
    try:
        with httpx.Client(
            timeout=timeout_s,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        ) as client:
            resp = client.head(url)
            if resp.status_code < 400:
                return True, resp.status_code
            # Some servers reject HEAD; try a tiny GET.
            resp = client.get(url, headers={"Range": "bytes=0-1023"})
            if resp.status_code < 400:
                return True, resp.status_code
            status = resp.status_code
    except httpx.HTTPError:
        status = 0

    # httpx was blocked or errored. If it looks like a WAF challenge, give
    # the URL one chance through a real browser before declaring it dead.
    if status in _WAF_BLOCK_STATUSES or status == 0:
        rendered = fetch_rendered_text(url, timeout_s=max(timeout_s, 25.0))
        # Reachability is about whether the render produced usable content,
        # not the numeric status: a cleared WAF challenge yields real content
        # while the initial goto status stays 403, and an unresolved challenge
        # now carries failure_mode='waf_challenge_unresolved' with no content.
        if rendered.failure_mode is None and rendered.content.strip():
            return True, 200
    return False, status
