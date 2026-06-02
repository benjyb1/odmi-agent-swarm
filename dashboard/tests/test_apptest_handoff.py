"""Hand-off test using Streamlit's AppTest framework.

Playwright struggles to drive Streamlit's baseweb multiselect from
outside the React tree. Streamlit's first-party AppTest framework runs
the page in-process and lets us interact with widgets by key.

Run:
    uv run python dashboard/tests/test_apptest_handoff.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from streamlit.testing.v1 import AppTest


def test_questions_to_run_console() -> bool:
    """Open Questions, select P1, click Send, verify session_state."""
    print("\n[apptest_handoff] starting Questions page test...")

    at = AppTest.from_file("dashboard/pages/3_Questions.py", default_timeout=30)
    at.run()

    if at.exception:
        print(f"  ✗ Questions page raised: {at.exception}")
        return False

    # Find the questions_picker multiselect.
    pickers = [w for w in at.multiselect if w.key == "questions_picker"]
    if not pickers:
        print("  ✗ questions_picker multiselect not found")
        return False

    # Pick P1.
    picker = pickers[0]
    if "P1" not in picker.options:
        print(f"  ✗ P1 not in picker options ({picker.options[:5]}...)")
        return False
    picker.set_value(["P1"]).run()

    if at.exception:
        print(f"  ✗ select raised: {at.exception}")
        return False

    # Find and click the Send button.
    send = [b for b in at.button if "Send" in b.label]
    if not send:
        print("  ✗ No Send button found")
        return False
    send[0].click().run()

    if at.exception:
        print(f"  ✗ Send click raised: {at.exception}")
        return False

    # Verify session_state. AppTest's session_state supports subscript.
    try:
        queued = at.session_state["queued_questions"]
    except (KeyError, AttributeError):
        queued = None
    if queued == ["P1"]:
        print(f"  ✓ session_state.queued_questions = {queued}")
    else:
        print(f"  ✗ session_state.queued_questions = {queued!r}, expected ['P1']")
        return False

    # Now load the Run Console with that state primed.
    at2 = AppTest.from_file("dashboard/pages/1_Run_Console.py", default_timeout=30)
    at2.session_state["queued_questions"] = ["P1"]
    at2.run()

    if at2.exception:
        print(f"  ✗ Run Console raised: {at2.exception}")
        return False

    # Verify the questions multiselect picked up the staged P1.
    rc_pickers = [w for w in at2.multiselect if "question" in (w.label or "").lower()]
    if not rc_pickers:
        print("  ✗ No question multiselect on Run Console")
        return False

    found = any("P1" in (rc_pickers[0].value or []) for _ in [None])
    if found:
        print(f"  ✓ Run Console pre-populated with P1: {rc_pickers[0].value}")
    else:
        print(f"  ✗ Run Console multiselect missing P1 (value={rc_pickers[0].value})")
        return False

    return True


def test_models_page_load() -> bool:
    """Open Models page; verify defaults render and analytics don't crash."""
    print("\n[apptest_models] opening Models page...")
    at = AppTest.from_file("dashboard/pages/6_Models.py", default_timeout=30)
    at.run()
    if at.exception:
        print(f"  ✗ Models raised: {at.exception}")
        return False
    # Should have three default selectboxes.
    selects = at.selectbox
    if len(selects) < 3:
        print(f"  ✗ Expected ≥3 selectboxes (defaults), found {len(selects)}")
        return False
    print(f"  ✓ {len(selects)} selectboxes rendered, no exceptions")
    return True


def test_costs_page_load() -> bool:
    """Costs page must render even with no data."""
    print("\n[apptest_costs] opening Costs page...")
    at = AppTest.from_file("dashboard/pages/7_Costs.py", default_timeout=30)
    at.run()
    if at.exception:
        print(f"  ✗ Costs raised: {at.exception}")
        return False
    print("  ✓ Costs page rendered")
    return True


def test_strategy_lab_page_load() -> bool:
    """Strategy Lab; should not crash even with limited Researcher rows."""
    print("\n[apptest_strategy] opening Strategy Lab...")
    at = AppTest.from_file("dashboard/pages/4_Verifier_Strategies.py", default_timeout=30)
    at.run()
    if at.exception:
        print(f"  ✗ Strategy Lab raised: {at.exception}")
        return False
    print("  ✓ Strategy Lab rendered")
    return True


def main() -> int:
    tests = [
        test_questions_to_run_console,
        test_models_page_load,
        test_costs_page_load,
        test_strategy_lab_page_load,
    ]
    results = []
    for t in tests:
        try:
            results.append((t.__name__, t()))
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {t.__name__} crashed: {exc}")
            results.append((t.__name__, False))

    print("\n" + "=" * 50)
    print(f"{sum(1 for _, r in results if r)}/{len(results)} apptest cases passed")
    print("=" * 50)
    for name, ok in results:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}")

    return 0 if all(r for _, r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
