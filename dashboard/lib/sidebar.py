"""Shared sidebar widget rendered on every page.

Pins the Claude session status at the bottom. Reads claude_usage_log
to estimate the rolling 5-hour window. The soft limit is a config
value (Q-DASH-1, set to $5 by default).
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from dashboard.lib import db, mode


DEFAULT_SOFT_LIMIT_USD = 5.0


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
              The dashboard reads from a snapshot of the SQLite store.
              Buttons that would dispatch LLM calls or commit hand-marks
              are disabled and will pop a toast instead.
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_session_widget() -> None:
    """Pin the Claude session widget to the sidebar."""
    render_read_only_banner()
    soft_limit = st.session_state.get("soft_limit_usd", DEFAULT_SOFT_LIMIT_USD)
    summary = db.rolling_window_summary()

    cost = float(summary.get("cost") or 0.0)
    in_tok = int(summary.get("in_tok") or 0)
    out_tok = int(summary.get("out_tok") or 0)
    n_calls = int(summary.get("n_calls") or 0)
    rl_hits = int(summary.get("rate_limit_hits") or 0)
    pct_used = min(1.0, cost / soft_limit) if soft_limit > 0 else 0.0

    with st.sidebar:
        st.markdown("---")
        st.caption("**CLAUDE SESSION (rolling 5h)**")
        st.progress(pct_used, text=f"${cost:.2f} / ${soft_limit:.2f}")
        st.caption(
            f"Calls: {n_calls}  |  Tokens: {in_tok + out_tok:,}  "
            f"|  In: {in_tok:,}  |  Out: {out_tok:,}"
        )
        if rl_hits > 0:
            st.error(f"{rl_hits} rate-limit hit(s) in window")
        with st.expander("Adjust soft limit", expanded=False):
            new_limit = st.number_input(
                "Soft limit ($)", min_value=0.5, max_value=100.0,
                value=float(soft_limit), step=0.5, key="_soft_limit_input",
            )
            if new_limit != soft_limit:
                st.session_state["soft_limit_usd"] = new_limit


def page_header(title: str, subtitle: str | None = None) -> None:
    """Render a consistent header across all pages."""
    st.title(title)
    if subtitle:
        st.caption(subtitle)
