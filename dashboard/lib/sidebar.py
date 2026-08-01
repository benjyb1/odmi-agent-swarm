"""Shared sidebar widget rendered on every page.

Pins the Claude session status at the bottom. Reads claude_usage_log to
show the rolling 5-hour spend. This is an information meter only: there
is no soft limit and nothing here blocks a run (the soft limit was
removed because it only got in the way). The cost is stored internally
in USD because Anthropic pricing arrives in USD, and rendered in £.
"""

from __future__ import annotations

import streamlit as st

from dashboard.lib import db, mode
from dashboard.lib.currency import format_gbp


def render_read_only_banner() -> None:
    """Show a small badge in the sidebar when ODMI_READ_ONLY is set."""
    if not mode.is_read_only():
        return
    with st.sidebar:
        st.markdown(
            """
            <div style="background:#0F766E; color:#FFFFFF; padding:10px 12px;
                        border-radius:8px; margin-bottom:14px;
                        font-size:12px; line-height:1.45;">
              <div style="font-weight:700; letter-spacing:0.08em;
                          font-size:11px; margin-bottom:4px;">
                🔒 READ-ONLY DEMO
              </div>
              This is a public mirror of a private local dashboard.
              Live ODMI ground-truth comparison and historical swarm
              runs are visible. Buttons that would dispatch new LLM
              calls are disabled and will pop a toast instead.
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_session_widget() -> None:
    """Pin the Claude session widget to the sidebar."""
    render_read_only_banner()
    summary = db.rolling_window_summary()

    cost = float(summary.get("cost") or 0.0)
    in_tok = int(summary.get("in_tok") or 0)
    out_tok = int(summary.get("out_tok") or 0)
    n_calls = int(summary.get("n_calls") or 0)
    rl_hits = int(summary.get("rate_limit_hits") or 0)

    with st.sidebar:
        st.markdown("---")
        st.caption("**CLAUDE SESSION (rolling 5h)**")
        st.metric("Spend (5h)", format_gbp(cost))
        st.caption(
            f"Calls: {n_calls}  |  Tokens: {in_tok + out_tok:,}  "
            f"|  In: {in_tok:,}  |  Out: {out_tok:,}"
        )
        if rl_hits > 0:
            st.error(f"{rl_hits} rate-limit hit(s) in window")


def page_header(title: str, subtitle: str | None = None) -> None:
    """Render a consistent header across all pages."""
    st.title(title)
    if subtitle:
        st.caption(subtitle)
