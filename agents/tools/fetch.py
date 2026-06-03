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
from typing import Literal, Optional

import httpx
from pydantic import BaseModel

from agents.tools.blocked_domains import blocked_reason, is_blocked

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


def _settle_through_challenge(page, timeout_s: float) -> str:
    """Return the page HTML, waiting out a Cloudflare passive challenge when
    the first paint is the interstitial rather than the real page."""
    body = page.content()
    if any(marker in body for marker in _CF_CHALLENGE_MARKERS):
        try:
            page.wait_for_timeout(4000)
            page.wait_for_load_state("networkidle", timeout=int(timeout_s * 1000))
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
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError as exc:
        return FetchResult(
            url=url, backend="playwright", status_code=0, content="",
            truncated=False,
            failure_mode=f"playwright_not_installed:{exc}",
        )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=_PW_LAUNCH_ARGS)
            context = browser.new_context(
                user_agent=DEFAULT_USER_AGENT, **_PW_CONTEXT_KWARGS
            )
            page = context.new_page()
            try:
                page.goto(url, timeout=timeout_s * 1000, wait_until="domcontentloaded")
                page.wait_for_timeout(500)  # let JS settle briefly
                body = _settle_through_challenge(page, timeout_s)
                status = 200
            except PWTimeout:
                return FetchResult(
                    url=url, backend="playwright", status_code=0, content="",
                    truncated=False, failure_mode="timeout",
                )
            finally:
                context.close()
                browser.close()
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
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError as exc:
        return FetchResult(
            url=url, backend="playwright", status_code=0, content="",
            truncated=False, failure_mode=f"playwright_not_installed:{exc}",
        )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=_PW_LAUNCH_ARGS)
            context = browser.new_context(
                user_agent=DEFAULT_USER_AGENT, **_PW_CONTEXT_KWARGS
            )
            page = context.new_page()
            try:
                page.goto(url, timeout=timeout_s * 1000, wait_until="domcontentloaded")
                page.wait_for_timeout(500)  # let JS settle briefly
                body = _settle_through_challenge(page, timeout_s)
                status = 200
            except PWTimeout:
                return FetchResult(
                    url=url, backend="playwright", status_code=0, content="",
                    truncated=False, failure_mode="timeout",
                )
            finally:
                context.close()
                browser.close()
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
        if rendered.status_code == 200 and rendered.content.strip():
            return True, 200
    return False, status
