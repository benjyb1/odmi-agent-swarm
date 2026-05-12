"""ODMI Swarm Dashboard — Home page.

Entry point. Run with:
    streamlit run dashboard/Home.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Make `dashboard.lib` importable when run via `streamlit run`.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib import db
from dashboard.lib.sidebar import page_header, render_session_widget


st.set_page_config(
    page_title="ODMI Swarm",
    page_icon="🐝",
    layout="wide",
    initial_sidebar_state="expanded",
)

page_header("ODMI Swarm Dashboard",
            "Live control surface for the agent swarm.")

# Session widget pinned to sidebar.
render_session_widget()


# ============================================================
# Live widgets — refresh every 2 seconds.
# ============================================================

@st.fragment(run_every=2)
def kpi_tiles() -> None:
    active = db.active_subtrios()
    finals = db.finals(limit=1000)
    researcher = db.researcher_runs(limit=1000)
    verifier = db.verifier_runs(limit=1000)
    summary = db.rolling_window_summary()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Active subtrios", len(active))
        if len(active) > 0:
            preview = ", ".join(
                f"{r['question_id']}/{r['country_code']}"
                for _, r in active.head(3).iterrows()
            )
            st.caption(preview)
    with c2:
        st.metric(
            "Total runs",
            f"{len(researcher)} R / {len(verifier)} V",
        )
        st.caption(f"{len(finals)} pairs finalised")
    with c3:
        if len(verifier) > 0:
            pass_count = (verifier["verdict"] == "pass").sum()
            rate = pass_count / len(verifier)
            colour_rate = f"{rate:.0%}"
        else:
            colour_rate = "—"
        st.metric("Verifier pass rate", colour_rate)
        if len(verifier) > 0:
            st.caption(f"{(verifier['verdict']=='pass').sum()} of {len(verifier)}")
    with c4:
        cost = float(summary.get("cost") or 0.0)
        st.metric("Window spend ($)", f"{cost:.2f}")
        st.caption(f"{summary.get('n_calls') or 0} calls in 5h")


@st.fragment(run_every=2)
def recent_runs_panel() -> None:
    st.subheader("Recent subtrios")
    recent = db.recent_subtrios(limit=10)
    if len(recent) == 0:
        st.info("No subtrios run yet. Open the Run Console to release one.")
        return
    display = recent[[
        "question_id", "country_code", "stage", "final_verdict",
        "retry_count", "cumulative_cost_usd", "last_message",
        "updated_at",
    ]].copy()
    display.columns = [
        "Question", "Country", "Stage", "Verdict",
        "Retries", "Cost $", "Last message", "Updated",
    ]
    if "Cost $" in display:
        display["Cost $"] = display["Cost $"].apply(
            lambda x: f"{x:.4f}" if pd.notna(x) else "—"
        )
    st.dataframe(display, use_container_width=True, hide_index=True)


def hand_marks_and_queue() -> None:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Hand-marks status")
        hm = db.hand_marks()
        questions = db.all_questions()
        if len(questions) == 0:
            st.warning("No questions loaded.")
        else:
            if len(hm) == 0:
                st.warning(
                    f"0 of {len(questions)} questions hand-marked. "
                    "Hand-marks must be locked (D9) before swarm runs "
                    "count as evidence."
                )
            else:
                by_country = hm.groupby("country_code").size().to_dict()
                for country, n in by_country.items():
                    st.write(
                        f"**{country}**: {n} / {len(questions)} hand-marked "
                        f"({n / len(questions):.1%})"
                    )

    with col2:
        st.subheader("Human queue")
        finals = db.finals(limit=1000)
        if len(finals) == 0:
            st.info("Nothing escalated yet.")
        else:
            escalated = finals[finals["terminal_status"].isin([
                "escalated_captcha", "escalated_adjudicator",
            ])]
            if len(escalated) == 0:
                st.success("No escalations.")
            else:
                st.write(f"{len(escalated)} pair(s) escalated for review:")
                st.dataframe(
                    escalated[[
                        "question_id", "country_code",
                        "terminal_status", "final_failure_reason",
                    ]].rename(columns={
                        "question_id": "Q", "country_code": "Country",
                        "terminal_status": "Reason",
                        "final_failure_reason": "Detail",
                    }),
                    use_container_width=True, hide_index=True,
                )


# ============================================================
# Layout
# ============================================================

kpi_tiles()
st.divider()
recent_runs_panel()
st.divider()
hand_marks_and_queue()

st.caption(
    "Auto-refresh: KPIs and recent runs reload every 2 seconds. "
    "Other panels refresh on page interaction."
)
