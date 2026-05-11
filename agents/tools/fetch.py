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

DEFAULT_USER_AGENT = (
    "ODMI-Swarm-Research/0.1 "
    "(MSc dissertation; King's College London; "
    "contact: benjaminbream@gmail.com)"
)

DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_CHARS = 4000


FetchBackend = Literal["httpx", "playwright"]


class FetchResult(BaseModel):
    url: str
    backend: FetchBackend
    status_code: int                      # 0 if the fetch never completed
    content: str                          # truncated to max_chars
    truncated: bool
    failure_mode: Optional[str] = None    # null on success


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
    """Plain httpx GET. Returns text content with HTML tags stripped."""
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


def fetch_rendered_text(
    url: str,
    *,
    timeout_s: float = 30.0,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> FetchResult:
    """Playwright fallback for JS-heavy portals. Lazy-imports Playwright.

    Use only when `fetch_text` returns an empty body or a known
    CAPTCHA/blocking marker. Slower than httpx.
    """
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
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=DEFAULT_USER_AGENT)
            page = context.new_page()
            try:
                page.goto(url, timeout=timeout_s * 1000, wait_until="domcontentloaded")
                page.wait_for_timeout(500)  # let JS settle briefly
                body = page.content()
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


def head_ok(url: str, *, timeout_s: float = 8.0) -> tuple[bool, int]:
    """HEAD-check that a URL returns HTTP 200. Used by the Researcher's
    post-call validation per AGENT_DESIGN section 3.5.

    Returns (ok, status_code). Some servers reject HEAD; on 4xx/5xx we
    fall back to a small GET so we don't misclassify a working URL.
    """
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
            return resp.status_code < 400, resp.status_code
    except httpx.HTTPError:
        return False, 0
