"""pytest configuration and shared fixtures for the ODMI test suite."""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests marked ``live`` unless ``-m live`` is passed explicitly."""
    run_live = config.getoption("-m", default="") == "live"
    skip_live = pytest.mark.skip(reason="live test -- pass -m live to run")
    for item in items:
        if "live" in item.keywords and not run_live:
            item.add_marker(skip_live)
