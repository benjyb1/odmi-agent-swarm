"""Front-end smoke tests for the ODMI dashboard.

Walks the probable user paths via Playwright. The Streamlit app must be
running on localhost:8520. Run with:

    streamlit run dashboard/Home.py --server.headless true \
        --server.port 8520 --server.address 127.0.0.1 \
        --browser.gatherUsageStats false &

    uv run python dashboard/tests/test_user_paths.py

Reports any Streamlit error banners (the red boxes that appear when a
Python exception fires in a page). The goal is to surface front-end
errors that static analysis would miss.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, Browser, sync_playwright

BASE_URL = "http://127.0.0.1:8520"

# Each tuple: (label, path, optional click after load)
PAGES = [
    ("home",                 "/"),
    ("run_console",          "/Run_Console"),
    ("results",              "/Results"),
    ("questions",            "/Questions"),
    ("verifier_strategies",  "/Verifier_Strategies"),
    ("models",               "/Models"),
    ("costs",                "/Costs"),
    ("prompts",              "/Prompts"),
]


def _collect_errors(page: Page) -> list[dict]:
    """Return any Streamlit error / exception banners visible on the page."""
    findings = []
    # Streamlit renders exceptions inside a div with data-testid="stException".
    # Errors inside st.error() use data-testid="stAlert" with role="alert".
    for selector, kind in [
        ("[data-testid='stException']", "exception"),
        ("[data-testid='stAlert']", "alert"),
        ("div[role='alert']", "role-alert"),
    ]:
        elements = page.locator(selector)
        n = elements.count()
        for i in range(n):
            try:
                text = elements.nth(i).inner_text(timeout=500).strip()
                if not text:
                    continue
                # Streamlit shows info/warn/error all as alerts; only flag
                # if the text actually looks like an error.
                lower = text.lower()
                is_error = (
                    kind == "exception"
                    or "traceback" in lower
                    or "exception" in lower
                    or "error" in lower
                    or "refused" in lower
                )
                findings.append({
                    "selector": selector, "kind": kind,
                    "is_error": is_error,
                    "text": text[:300],
                })
            except Exception:  # noqa: BLE001
                pass
    return findings


def _wait_for_streamlit_ready(page: Page, timeout_s: float = 12.0) -> None:
    """Wait until Streamlit shows it's idle (running indicator gone)."""
    end = time.time() + timeout_s
    while time.time() < end:
        # The running indicator is the spinner in the header.
        try:
            spinning = page.locator("[data-testid='stStatusWidget']").count() > 0
            running_text = ""
            if spinning:
                running_text = page.locator("[data-testid='stStatusWidget']").first.inner_text(timeout=200)
        except Exception:  # noqa: BLE001
            running_text = ""
        if "running" not in running_text.lower():
            # Also wait for at least one content block to render.
            if page.locator("main").count() > 0:
                page.wait_for_timeout(400)
                return
        page.wait_for_timeout(200)


def test_page(browser: Browser, label: str, url_path: str) -> dict:
    """Load one page, collect any error banners."""
    print(f"\n[{label}] loading {url_path} ...", flush=True)
    ctx = browser.new_context(viewport={"width": 1500, "height": 900})
    page = ctx.new_page()
    console_msgs: list[dict] = []

    # Streamlit pages each load a favicon that Streamlit doesn't serve;
    # the browser logs a 404 console error every time. That's noise — we
    # only care about errors from our own code.
    IGNORE_CONSOLE = (
        "favicon",
        "Failed to load resource: the server responded with a status of 404",
    )

    def on_console(msg):
        text = msg.text[:200]
        if any(p in text for p in IGNORE_CONSOLE):
            return
        console_msgs.append({"type": msg.type, "text": text})

    def on_pageerror(err):
        text = str(err)[:300]
        if any(p in text for p in IGNORE_CONSOLE):
            return
        console_msgs.append({"type": "pageerror", "text": text})

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)

    result = {
        "label": label, "url_path": url_path,
        "load_status": None, "errors": [], "console": [],
        "title": None, "screenshot": None,
    }

    try:
        resp = page.goto(BASE_URL + url_path, wait_until="domcontentloaded", timeout=15000)
        result["load_status"] = resp.status if resp else None
        _wait_for_streamlit_ready(page)
        result["title"] = page.title()
        result["errors"] = _collect_errors(page)

        # Screenshot for inspection later.
        shot_dir = Path("dashboard/tests/screenshots")
        shot_dir.mkdir(parents=True, exist_ok=True)
        shot_path = shot_dir / f"{label}.png"
        page.screenshot(path=str(shot_path), full_page=True)
        result["screenshot"] = str(shot_path)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append({
            "kind": "playwright", "text": f"{type(exc).__name__}: {exc}",
            "is_error": True,
        })
    finally:
        # Filter console messages: surface errors only.
        result["console"] = [
            c for c in console_msgs
            if c["type"] in ("error", "pageerror")
        ]
        ctx.close()

    err_count = sum(1 for e in result["errors"] if e.get("is_error"))
    if err_count > 0 or result["console"]:
        print(f"  ⚠ ERRORS detected on {label}: {err_count} alerts, "
              f"{len(result['console'])} console errors")
    else:
        print(f"  ✓ {label} OK")
    return result


def test_questions_to_run_console_flow(browser: Browser) -> dict:
    """Walk the Questions → Run Console state hand-off."""
    print("\n[questions_to_run_console] testing hand-off...", flush=True)
    ctx = browser.new_context(viewport={"width": 1500, "height": 900})
    page = ctx.new_page()
    result = {"label": "questions_to_run_console", "errors": [], "notes": []}

    try:
        page.goto(BASE_URL + "/Questions", timeout=15000)
        _wait_for_streamlit_ready(page)

        # Find the "Select question(s) to stage" multiselect by its label.
        # Streamlit renders the label as a `<label>` sibling of the widget.
        # We click the label, which focuses the widget, then type to filter
        # and Enter to select the first match.
        label = page.get_by_text(
            "Select question(s) to stage for the Run Console:",
            exact=False,
        )
        if label.count() == 0:
            result["errors"].append({
                "kind": "missing", "is_error": True,
                "text": "Could not find the 'Select question(s) to stage' label.",
            })
        else:
            # The interactive multiselect div is the next sibling group;
            # clicking the label opens the dropdown.
            label.first.click()
            page.wait_for_timeout(500)
            # Type the first available question id to filter the dropdown.
            page.keyboard.type("P1", delay=50)
            page.wait_for_timeout(500)
            page.keyboard.press("Enter")
            _wait_for_streamlit_ready(page)
            result["notes"].append("selected P1 via keyboard")

        # Click the "Send" button.
        send_btn = page.locator("button:has-text('Send')")
        if send_btn.count() > 0:
            # Find the first enabled Send button.
            n = send_btn.count()
            clicked = False
            for i in range(n):
                btn = send_btn.nth(i)
                if not btn.is_disabled(timeout=500):
                    btn.click()
                    clicked = True
                    break
            if clicked:
                _wait_for_streamlit_ready(page)
                result["notes"].append("clicked Send")
            else:
                result["errors"].append({
                    "kind": "disabled", "is_error": True,
                    "text": "Send button found but all instances disabled.",
                })
        else:
            result["errors"].append({
                "kind": "missing", "is_error": True,
                "text": "Send button not found.",
            })

        # Go to Run Console and verify chips pre-populated.
        page.goto(BASE_URL + "/Run_Console", timeout=15000)
        _wait_for_streamlit_ready(page)
        result["errors"].extend(_collect_errors(page))
    except Exception as exc:  # noqa: BLE001
        result["errors"].append({
            "kind": "playwright", "text": str(exc), "is_error": True,
        })
    finally:
        ctx.close()

    err_count = sum(1 for e in result["errors"] if e.get("is_error"))
    if err_count > 0:
        print(f"  ⚠ ERRORS detected: {err_count}")
    else:
        print(f"  ✓ hand-off flow OK")
    return result


def main() -> int:
    print("Front-end test runner — ODMI dashboard")
    print(f"Base URL: {BASE_URL}")

    results: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for label, url_path in PAGES:
            results.append(test_page(browser, label, url_path))

        # The Questions → Run Console hand-off workflow is covered by
        # `test_apptest_handoff.py`, which uses Streamlit's first-party
        # AppTest framework. Driving the baseweb multiselect from outside
        # the React tree via Playwright is unreliable across versions.

        browser.close()

    # Summarise.
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    n_pass = sum(
        1 for r in results
        if not any(e.get("is_error") for e in r.get("errors", []))
        and not r.get("console")
    )
    n_total = len(results)
    print(f"{n_pass} / {n_total} pages clean")

    failures = [
        r for r in results
        if any(e.get("is_error") for e in r.get("errors", []))
        or r.get("console")
    ]
    if failures:
        print(f"\n{len(failures)} failures:")
        for f in failures:
            print(f"\n--- {f['label']} ({f.get('url_path', '')}) ---")
            for e in f.get("errors", []):
                if e.get("is_error"):
                    print(f"  ERROR ({e.get('kind')}): {e.get('text', '')[:200]}")
            for c in f.get("console", []):
                print(f"  CONSOLE ({c['type']}): {c['text'][:200]}")

    # Save full output.
    out = Path("dashboard/tests/test_user_paths_report.json")
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nFull report: {out}")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
