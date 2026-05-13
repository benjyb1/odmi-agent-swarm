"""ODMI Swarm Dashboard — Home page.

Entry point. Run with:
    streamlit run dashboard/Home.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# Make `dashboard.lib` importable when run via `streamlit run`.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib import db
from dashboard.lib.sidebar import render_session_widget


# ============================================================
# Page setup + theme
# ============================================================

st.set_page_config(
    page_title="ODMI Swarm",
    page_icon="🐝",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inline styles. Mirrors the palette of MSc Progress Slides 3.pptx.
st.markdown(
    """
    <style>
      html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Inter",
                     "Segoe UI", Roboto, "Helvetica Neue",
                     "Calibri", Arial, sans-serif;
      }
      [data-testid="stHeader"] { background: transparent; }
      .block-container { padding-top: 1rem; padding-bottom: 2rem; }

      .odmi-hero {
        background: linear-gradient(135deg, #1A202C 0%, #1E3A5F 100%);
        color: #FFFFFF;
        padding: 28px 36px 26px 36px;
        border-radius: 14px;
        margin-bottom: 22px;
        box-shadow: 0 12px 30px rgba(26, 32, 44, 0.18);
      }
      .odmi-eyebrow {
        color: #14B8A6;
        font-size: 11px;
        letter-spacing: 0.16em;
        font-weight: 700;
        margin-bottom: 8px;
        text-transform: uppercase;
      }
      .odmi-title {
        font-size: 32px;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.01em;
      }
      .odmi-sub {
        color: #CBD5E0;
        font-size: 14px;
        margin-top: 8px;
        max-width: 720px;
      }

      .odmi-kpi {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 16px 18px 14px 18px;
        position: relative;
        overflow: hidden;
        height: 124px;
      }
      .odmi-kpi::before {
        content: "";
        position: absolute;
        left: 0; right: 0; top: 0;
        height: 4px;
        background: var(--accent, #0D9488);
      }
      .odmi-kpi-label {
        color: #718096;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.09em;
        text-transform: uppercase;
      }
      .odmi-kpi-value {
        color: #1A202C;
        font-size: 32px;
        font-weight: 700;
        line-height: 1.1;
        margin: 6px 0 4px 0;
      }
      .odmi-kpi-cap {
        color: #4A5568;
        font-size: 12px;
      }

      .odmi-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 18px 22px 16px 22px;
        margin-bottom: 16px;
      }
      .odmi-card h3 {
        color: #1A202C;
        font-size: 16px;
        font-weight: 700;
        margin: 0 0 12px 0;
      }
      .odmi-card .eyebrow {
        color: #0D9488;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        margin-bottom: 4px;
      }
      .odmi-divider {
        border-top: 1px solid #E2E8F0;
        margin: 22px 0;
      }
      .odmi-foot {
        color: #718096;
        font-size: 11px;
        text-align: center;
        margin-top: 12px;
      }

      /* Streamlit dataframe — tighten borders. */
      [data-testid="stDataFrame"] {
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        overflow: hidden;
      }

      /* Tighten altair chart wrapper. */
      [data-testid="stAltairChart"] > div {
        background: transparent;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

render_session_widget()


# ============================================================
# Hero
# ============================================================

def render_hero() -> None:
    summary = db.rolling_window_summary()
    finals = db.finals(limit=1000)
    active = db.active_subtrios()
    cost = float(summary.get("cost") or 0.0)

    st.markdown(
        f"""
        <div class="odmi-hero">
          <div class="odmi-eyebrow">ODMI Agent Swarm · Live Control Surface</div>
          <div class="odmi-title">Dashboard</div>
          <div class="odmi-sub">
            Three-agent swarm answering EU Open Data Maturity Index
            questions across 36 countries. Researcher proposes, Verifier
            tries to disprove, Adjudicator decides on retry exhaustion.
            Everything you see below is read straight from the audit-trail
            SQLite store.
          </div>
          <div style="display:flex; gap:34px; margin-top:18px;">
            <div>
              <div style="color:#A0AEC0; font-size:11px; letter-spacing:0.09em;
                          text-transform:uppercase;">In flight</div>
              <div style="color:#FFFFFF; font-size:22px; font-weight:700;">
                {len(active)}
              </div>
            </div>
            <div>
              <div style="color:#A0AEC0; font-size:11px; letter-spacing:0.09em;
                          text-transform:uppercase;">Finalised</div>
              <div style="color:#FFFFFF; font-size:22px; font-weight:700;">
                {len(finals)}
              </div>
            </div>
            <div>
              <div style="color:#A0AEC0; font-size:11px; letter-spacing:0.09em;
                          text-transform:uppercase;">5h spend</div>
              <div style="color:#FFFFFF; font-size:22px; font-weight:700;">
                ${cost:.2f}
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# KPI tiles
# ============================================================

def _kpi_html(label: str, value: str, caption: str, accent: str) -> str:
    return (
        f'<div class="odmi-kpi" style="--accent: {accent};">'
        f'  <div class="odmi-kpi-label">{label}</div>'
        f'  <div class="odmi-kpi-value">{value}</div>'
        f'  <div class="odmi-kpi-cap">{caption}</div>'
        f'</div>'
    )


@st.fragment(run_every=3)
def kpi_tiles() -> None:
    active = db.active_subtrios()
    finals = db.finals(limit=1000)
    researcher = db.researcher_runs(limit=1000)
    verifier = db.verifier_runs(limit=1000)
    summary = db.rolling_window_summary()

    cost = float(summary.get("cost") or 0.0)
    n_calls = int(summary.get("n_calls") or 0)

    if len(verifier) > 0:
        pass_count = int((verifier["verdict"] == "pass").sum())
        pass_rate = f"{pass_count / len(verifier):.0%}"
        pass_cap = f"{pass_count} of {len(verifier)} runs passed."
    else:
        pass_rate = "—"
        pass_cap = "No Verifier runs yet."

    active_cap = "Coordinators idle."
    if len(active) > 0:
        preview = ", ".join(
            f"{r['question_id']}/{r['country_code']}"
            for _, r in active.head(3).iterrows()
        )
        active_cap = f"In flight now: {preview}"

    cols = st.columns(4)
    with cols[0]:
        st.markdown(
            _kpi_html(
                "Active subtrios", str(len(active)),
                active_cap, "#14B8A6",
            ),
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            _kpi_html(
                "Total runs",
                f"{len(researcher)} / {len(verifier)}",
                f"{len(finals)} pairs finalised. R / V counts.",
                "#1E3A5F",
            ),
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            _kpi_html(
                "Verifier pass rate", pass_rate, pass_cap, "#38A169",
            ),
            unsafe_allow_html=True,
        )
    with cols[3]:
        st.markdown(
            _kpi_html(
                "5h window spend",
                f"${cost:.2f}",
                f"{n_calls} LLM calls in the rolling window.",
                "#0D9488",
            ),
            unsafe_allow_html=True,
        )


# ============================================================
# Country chart
# ============================================================

@st.fragment(run_every=5)
def country_outcomes_chart() -> None:
    df = db.country_outcome_counts()

    st.markdown(
        '<div class="odmi-card">'
        '<div class="eyebrow">FINALISED PAIRS</div>'
        '<h3>Pairs by country, success vs failure</h3>',
        unsafe_allow_html=True,
    )

    if len(df) == 0:
        st.info(
            "No finalised pairs yet. Once the Coordinator writes "
            "`phase2_final` rows, this chart populates."
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    totals = df.groupby("country_code")["n"].sum().sort_values(ascending=False)
    country_order = totals.index.tolist()

    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X(
                "country_code:N",
                title="Country",
                sort=country_order,
                axis=alt.Axis(
                    labelFontSize=12, titleFontSize=12,
                    labelColor="#1A202C", titleColor="#718096",
                    labelFont="Calibri", titleFont="Calibri",
                    domain=False, ticks=False,
                ),
            ),
            y=alt.Y(
                "n:Q", title="Finalised pairs", stack="zero",
                axis=alt.Axis(
                    labelFontSize=11, titleFontSize=12,
                    labelColor="#718096", titleColor="#718096",
                    labelFont="Calibri", titleFont="Calibri",
                    grid=True, gridColor="#EDF2F7", domain=False,
                ),
            ),
            color=alt.Color(
                "outcome:N",
                title="Outcome",
                scale=alt.Scale(
                    domain=["Successful", "Failed"],
                    range=["#38A169", "#C53030"],
                ),
                legend=alt.Legend(
                    orient="bottom", labelFontSize=11,
                    titleFontSize=11, labelFont="Calibri",
                    titleFont="Calibri",
                ),
            ),
            tooltip=["country_code", "outcome", "n"],
        )
        .properties(height=300, background="transparent")
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(chart, use_container_width=True)

    pct_success = (
        df[df["outcome"] == "Successful"]["n"].sum() / df["n"].sum()
        if df["n"].sum() > 0 else 0
    )
    st.markdown(
        f'<div style="color:#718096; font-size:12px; margin-top:8px;">'
        f'{int(totals.sum())} finalised pairs across {len(country_order)} '
        f'country/countries. Overall accept rate: {pct_success:.0%}. '
        f'Success = accepted_by_verifier or accepted_by_adjudicator. '
        f'Failure includes rejected_* and escalated_*.'
        f'</div>'
        '</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# Recent runs (left column)
# ============================================================

@st.fragment(run_every=3)
def recent_runs_panel() -> None:
    st.markdown(
        '<div class="odmi-card">'
        '<div class="eyebrow">LIVE ACTIVITY</div>'
        '<h3>Recent subtrios</h3>',
        unsafe_allow_html=True,
    )

    recent = db.recent_subtrios(limit=10)
    if len(recent) == 0:
        st.info("No subtrios run yet. Open the Run Console to release one.")
        st.markdown("</div>", unsafe_allow_html=True)
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
    display["Cost $"] = display["Cost $"].apply(
        lambda x: f"${x:.4f}" if pd.notna(x) else "—"
    )
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# Hand-marks status + Human queue (right column)
# ============================================================

def render_hand_marks_status() -> None:
    hm = db.hand_marks()
    questions = db.all_questions()

    st.markdown(
        '<div class="odmi-card">'
        '<div class="eyebrow">AUDIT TRAIL · D9 LOCK</div>'
        '<h3>Hand-marks status</h3>',
        unsafe_allow_html=True,
    )

    if len(questions) == 0:
        st.warning("No questions loaded. Run `scripts/load_questions.py`.")
    elif len(hm) == 0:
        st.warning(
            f"0 of {len(questions)} questions hand-marked. "
            "Hand-marks must be locked (D9) before swarm runs count as evidence."
        )
    else:
        by_country = hm.groupby("country_code").size().to_dict()
        chip_html = '<div style="display:flex; flex-wrap:wrap; gap:8px;">'
        for country, n in sorted(by_country.items()):
            pct = n / len(questions)
            chip_html += (
                '<div style="background:#F7FAFC; border:1px solid #E2E8F0; '
                'border-radius:8px; padding:8px 12px; min-width:90px;">'
                f'<div style="color:#1A202C; font-weight:700; font-size:14px;">{country}</div>'
                f'<div style="color:#0F766E; font-weight:700; font-size:18px;">{n}</div>'
                f'<div style="color:#718096; font-size:10px;">'
                f'of {len(questions)} · {pct:.0%}</div>'
                '</div>'
            )
        chip_html += "</div>"
        st.markdown(chip_html, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


def render_human_queue() -> None:
    st.markdown(
        '<div class="odmi-card">'
        '<div class="eyebrow">REVIEWER ACTION</div>'
        '<h3>Human queue</h3>',
        unsafe_allow_html=True,
    )

    finals = db.finals(limit=1000)
    if len(finals) == 0:
        st.info("Nothing escalated yet.")
    else:
        escalated = finals[finals["terminal_status"].isin([
            "escalated_captcha", "escalated_adjudicator",
        ])]
        if len(escalated) == 0:
            st.success("No escalations. The swarm has resolved every "
                       "pair without needing a human.")
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

    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# Layout
# ============================================================

render_hero()

kpi_tiles()

st.write("")  # tiny breathing space

country_outcomes_chart()

left, right = st.columns([3, 2])
with left:
    recent_runs_panel()
with right:
    render_hand_marks_status()
    render_human_queue()

st.markdown(
    '<div class="odmi-foot">'
    "Auto-refresh: KPIs and recent runs reload every three seconds. "
    "The chart reloads every five. Other panels refresh on interaction."
    '</div>',
    unsafe_allow_html=True,
)
