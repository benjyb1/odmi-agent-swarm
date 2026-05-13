"""Runtime mode for the dashboard.

Set `ODMI_READ_ONLY=1` (e.g. in Streamlit Community Cloud's app
secrets) to flip the dashboard into a view-only mode. The Run
Console, Verifier Strategies workbench, and Hand-marks form keep
rendering their UI but their submit handlers short-circuit and
show a toast saying the action only runs on a local install.

Why: the LLM dispatch path needs CLIProxyAPI on localhost:8317,
and the hand-mark save path needs a writable filesystem and a git
identity for the D9 commit. Neither survives a hosted deploy.
"""

from __future__ import annotations

import os

import streamlit as st

LOCAL_ONLY_MESSAGE = (
    "This action runs LLM calls or writes to git, which only works "
    "on a local install. Clone the repo and run "
    "`uv run streamlit run dashboard/Home.py`."
)


def is_read_only() -> bool:
    """True when the dashboard should disable write actions."""
    return os.environ.get("ODMI_READ_ONLY", "").strip() in ("1", "true", "yes")


def block_if_read_only() -> bool:
    """Show a toast and return True if the page is in read-only mode.

    Use this inside button-click branches:

        if st.button("Release"):
            if mode.block_if_read_only():
                return
            # ... real dispatch ...
    """
    if is_read_only():
        st.toast(LOCAL_ONLY_MESSAGE, icon="🔒")
        return True
    return False
