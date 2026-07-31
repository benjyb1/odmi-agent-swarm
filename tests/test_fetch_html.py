"""Tests for raw-HTML fetching (agents/tools/fetch.fetch_html).

The DIY-Tavily pipeline needs the RAW HTML so trafilatura can find the main
content. fetch_text (the Researcher/Verifier path) strips tags and caps at
4000 chars, which destroys the DOM before extraction can run. fetch_html
returns the unmodified response body with a generous cap.

httpx is mocked throughout; no real network calls.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


from agents.tools.fetch import (
    fetch_html,
    fetch_rendered_html,
    fetch_rendered_text,
    head_ok,
    _challenge_unresolved,
    FetchResult,
)


_HTML = (
    "<!DOCTYPE html><html><head><title>T</title>"
    "<style>.x{color:red}</style></head>"
    "<body><nav>Home Datasets</nav>"
    "<article><h1>Report</h1><p>France scored 87%.</p></article>"
    "<footer>Cookie policy</footer></body></html>"
)


def _mock_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


def _client_returning(resp: MagicMock) -> MagicMock:
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get = MagicMock(return_value=resp)
    return client


def test_fetch_html_returns_raw_tags_intact():
    """fetch_html must return the HTML with tags intact (not tag-stripped)."""
    with patch("httpx.Client", return_value=_client_returning(_mock_response(_HTML))):
        result = fetch_html("https://example.com/report")
    assert result.failure_mode is None
    assert "<article>" in result.content
    assert "<nav>" in result.content
    # The raw body is preserved verbatim.
    assert result.content == _HTML


def test_fetch_html_does_not_cap_at_4000():
    """A page larger than fetch_text's 4000-char cap must survive intact."""
    big = "<html><body>" + ("<p>padding</p>" * 1000) + "<p>TARGET-SENTENCE</p></body></html>"
    assert len(big) > 4000
    with patch("httpx.Client", return_value=_client_returning(_mock_response(big))):
        result = fetch_html("https://example.com/big")
    assert result.failure_mode is None
    assert "TARGET-SENTENCE" in result.content
    assert result.truncated is False


def test_fetch_html_non_200_is_failure():
    """A non-200 status returns a failure_mode and empty content."""
    with patch("httpx.Client", return_value=_client_returning(_mock_response("nope", 404))):
        result = fetch_html("https://example.com/missing")
    assert result.failure_mode == "http_status_404"
    assert result.content == ""


def test_fetch_html_refuses_blocked_domain():
    """Blocked (data-leakage) domains must be refused before any network call."""
    # data.europa.eu is on the deny-list per D24.
    result = fetch_html("https://data.europa.eu/some/answer/page")
    assert result.failure_mode is not None
    assert result.failure_mode.startswith("blocked_data_leakage")
    assert result.content == ""


def test_fetch_rendered_html_refuses_blocked_domain():
    """The Playwright raw-HTML fallback must also refuse blocked domains."""
    result = fetch_rendered_html("https://data.europa.eu/some/answer/page")
    assert result.failure_mode is not None
    assert result.failure_mode.startswith("blocked_data_leakage")
    assert result.content == ""


_CHALLENGE_HTML = (
    "<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
    "<body><div class='cf-browser-verification'>Checking your browser</div>"
    "<div id='challenge-platform'></div></body></html>"
)


def _playwright_page(content_html: str, *, goto_status=None):
    """Build a mocked Playwright stack whose page renders `content_html`."""
    page = MagicMock()
    goto_return = MagicMock(status=goto_status) if goto_status is not None else MagicMock()
    page.goto = MagicMock(return_value=goto_return)
    page.wait_for_timeout = MagicMock()
    page.wait_for_load_state = MagicMock()
    page.content = MagicMock(return_value=content_html)

    context = MagicMock()
    context.new_page = MagicMock(return_value=page)
    browser = MagicMock()
    browser.new_context = MagicMock(return_value=context)
    chromium = MagicMock()
    chromium.launch = MagicMock(return_value=browser)

    pw = MagicMock()
    pw.__enter__ = MagicMock(return_value=MagicMock(chromium=chromium))
    pw.__exit__ = MagicMock(return_value=False)

    fake_module = MagicMock()
    fake_module.sync_playwright = MagicMock(return_value=pw)
    fake_module.TimeoutError = type("PWTimeout", (Exception,), {})
    return fake_module


def test_challenge_unresolved_detects_markers():
    """A body still carrying a Cloudflare marker is an unresolved challenge."""
    assert _challenge_unresolved(_CHALLENGE_HTML) is True


def test_challenge_unresolved_false_on_clean_page():
    """A normal page body is not a challenge."""
    assert _challenge_unresolved(_HTML) is False


def test_fetch_rendered_html_unresolved_challenge_is_failure():
    """A Cloudflare interstitial that never clears must be a failure carrying
    the real status, not a 200 success that poisons the cache."""
    fake_module = _playwright_page(_CHALLENGE_HTML, goto_status=403)
    with patch.dict("sys.modules", {"playwright.sync_api": fake_module}):
        result = fetch_rendered_html("https://portal.data.gov.mt/")
    assert result.failure_mode == "waf_challenge_unresolved"
    assert result.content == ""
    assert result.status_code == 403


def test_fetch_rendered_text_unresolved_challenge_is_failure():
    """The text renderer (head_ok's path) must also fail on an unresolved
    challenge rather than return the interstitial as live content."""
    fake_module = _playwright_page(_CHALLENGE_HTML, goto_status=403)
    with patch.dict("sys.modules", {"playwright.sync_api": fake_module}):
        result = fetch_rendered_text("https://portal.data.gov.mt/")
    assert result.failure_mode == "waf_challenge_unresolved"
    assert result.content == ""
    assert result.status_code == 403


def _client_403() -> MagicMock:
    """An httpx client whose HEAD and GET both return 403 (a WAF block)."""
    resp = _mock_response("blocked", 403)
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.head = MagicMock(return_value=resp)
    client.get = MagicMock(return_value=resp)
    return client


def test_head_ok_true_when_render_clears_waf_challenge():
    """A 403 WAF block that the browser render clears (real content, no
    challenge marker) is reachable, even though the initial goto status was
    403. head_ok must key off usable content, not the numeric status."""
    cleared = FetchResult(
        url="https://portal.data.gov.mt/", backend="playwright",
        status_code=403, content="Real Maltese portal content here",
        truncated=False, failure_mode=None,
    )
    with patch("httpx.Client", return_value=_client_403()), \
         patch("agents.tools.fetch.fetch_rendered_text", return_value=cleared):
        ok, _status = head_ok("https://portal.data.gov.mt/")
    assert ok is True


def test_head_ok_false_when_waf_challenge_unresolved():
    """An unresolved challenge (failure_mode set, empty content) is not
    reachable, even though it now carries the real 403 status."""
    unresolved = FetchResult(
        url="https://portal.data.gov.mt/", backend="playwright",
        status_code=403, content="", truncated=False,
        failure_mode="waf_challenge_unresolved",
    )
    with patch("httpx.Client", return_value=_client_403()), \
         patch("agents.tools.fetch.fetch_rendered_text", return_value=unresolved):
        ok, _status = head_ok("https://portal.data.gov.mt/")
    assert ok is False


def test_fetch_rendered_html_returns_raw_body():
    """fetch_rendered_html returns the rendered page's raw HTML, tags intact."""
    page = MagicMock()
    page.goto = MagicMock()
    page.wait_for_timeout = MagicMock()
    page.content = MagicMock(return_value=_HTML)

    context = MagicMock()
    context.new_page = MagicMock(return_value=page)
    browser = MagicMock()
    browser.new_context = MagicMock(return_value=context)
    chromium = MagicMock()
    chromium.launch = MagicMock(return_value=browser)

    pw = MagicMock()
    pw.__enter__ = MagicMock(return_value=MagicMock(chromium=chromium))
    pw.__exit__ = MagicMock(return_value=False)

    fake_module = MagicMock()
    fake_module.sync_playwright = MagicMock(return_value=pw)
    fake_module.TimeoutError = type("PWTimeout", (Exception,), {})

    with patch.dict("sys.modules", {"playwright.sync_api": fake_module}):
        result = fetch_rendered_html("https://example.com/spa")
    assert result.failure_mode is None
    assert "<article>" in result.content
    assert result.content == _HTML


# D43 total-budget discipline (2026-06-11): launch, goto, and the
# challenge-settle waits all draw from one `timeout_s` budget, so a
# WAF-challenged URL can never spend more than the render timeout and
# trip the DIY stage ceiling on its own.

def test_settle_waits_are_bounded_by_remaining_budget():
    """With 6s of budget left, the settle wait is half the remainder and the
    networkidle wait is the rest; together they never exceed the budget."""
    from agents.tools.fetch import _settle_through_challenge

    page = MagicMock()
    page.content = MagicMock(return_value=_CHALLENGE_HTML)
    _settle_through_challenge(page, remaining_s=6.0)
    page.wait_for_timeout.assert_called_once_with(3000)
    page.wait_for_load_state.assert_called_once_with("networkidle", timeout=3000)


def test_settle_skips_waits_when_budget_exhausted():
    """Under 1s of remaining budget: no waits at all, the interstitial body is
    returned and the caller reports waf_challenge_unresolved."""
    from agents.tools.fetch import _settle_through_challenge

    page = MagicMock()
    page.content = MagicMock(return_value=_CHALLENGE_HTML)
    body = _settle_through_challenge(page, remaining_s=0.4)
    page.wait_for_timeout.assert_not_called()
    page.wait_for_load_state.assert_not_called()
    assert body == _CHALLENGE_HTML


def test_settle_caps_initial_wait_at_4s_with_ample_budget():
    """With a large remaining budget the settle wait keeps its original 4s
    figure; the bound only bites when the budget is tight."""
    from agents.tools.fetch import _settle_through_challenge

    page = MagicMock()
    page.content = MagicMock(return_value=_CHALLENGE_HTML)
    _settle_through_challenge(page, remaining_s=20.0)
    page.wait_for_timeout.assert_called_once_with(4000)
    page.wait_for_load_state.assert_called_once_with("networkidle", timeout=16000)


def test_rendered_html_launch_is_inside_the_budget():
    """The browser launch gets the budget as its timeout, and the goto timeout
    is the budget minus elapsed time, never more than the budget itself."""
    fake_module = _playwright_page(_HTML)
    with patch.dict("sys.modules", {"playwright.sync_api": fake_module}):
        result = fetch_rendered_html("https://example.com/spa", timeout_s=13.0)
    assert result.failure_mode is None
    chromium = fake_module.sync_playwright.return_value.__enter__.return_value.chromium
    launch_kwargs = chromium.launch.call_args.kwargs
    assert launch_kwargs["timeout"] == 13.0 * 1000
    page = (chromium.launch.return_value.new_context.return_value
            .new_page.return_value)
    goto_timeout = page.goto.call_args.kwargs["timeout"]
    assert 0 < goto_timeout <= 13.0 * 1000
