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
from dashboard.lib.currency import format_gbp
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

# Dark-first design language. The CSS targets Streamlit's dark theme so
# every surface uses charcoal cards on a near-black page, with a teal
# accent system and an Inter sans-serif stack to keep typography
# consistent across macOS and Windows.
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

      html, body, [class*="css"], [class*="st-"], .stMarkdown, .stText,
      [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
        font-family: "Inter", -apple-system, BlinkMacSystemFont,
                     "Segoe UI", Roboto, "Helvetica Neue", Arial,
                     sans-serif !important;
        font-feature-settings: "ss01", "cv01", "cv11";
      }
      [data-testid="stHeader"] { background: transparent; }
      .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }

      /* The whole page background. Streamlit dark theme is the target. */
      [data-testid="stAppViewContainer"] {
        background: #0B0F19;
      }
      [data-testid="stSidebar"] {
        background: #0B0F19;
        border-right: 1px solid #1F2937;
      }

      .odmi-hero {
        background:
          radial-gradient(120% 100% at 0% 0%, #16B8A4 0%, transparent 38%),
          linear-gradient(135deg, #0E1726 0%, #1E2B45 100%);
        color: #F8FAFC;
        padding: 32px 38px 28px 38px;
        border-radius: 18px;
        margin-bottom: 24px;
        border: 1px solid #1F2A44;
        box-shadow: 0 18px 40px rgba(0, 0, 0, 0.35),
                    inset 0 1px 0 rgba(255, 255, 255, 0.06);
      }
      .odmi-eyebrow {
        color: #5EEAD4;
        font-size: 11px;
        letter-spacing: 0.16em;
        font-weight: 700;
        margin-bottom: 10px;
        text-transform: uppercase;
      }
      .odmi-title {
        font-size: 34px;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.02em;
        color: #F8FAFC;
      }
      .odmi-sub {
        color: #94A3B8;
        font-size: 14px;
        line-height: 1.55;
        margin-top: 10px;
        max-width: 760px;
      }

      .odmi-kpi {
        background: linear-gradient(180deg, #111827 0%, #0F172A 100%);
        border: 1px solid #1F2937;
        border-radius: 14px;
        padding: 18px 20px 16px 20px;
        position: relative;
        overflow: hidden;
        height: 132px;
        transition: transform 0.15s ease, border-color 0.15s ease;
      }
      .odmi-kpi:hover {
        border-color: #2D3B53;
        transform: translateY(-1px);
      }
      .odmi-kpi::before {
        content: "";
        position: absolute;
        left: 0; right: 0; top: 0;
        height: 3px;
        background: var(--accent, #14B8A6);
      }
      .odmi-kpi-label {
        color: #94A3B8;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.10em;
        text-transform: uppercase;
      }
      .odmi-kpi-value {
        color: #F1F5F9;
        font-size: 34px;
        font-weight: 700;
        line-height: 1.05;
        margin: 8px 0 6px 0;
        letter-spacing: -0.02em;
      }
      .odmi-kpi-cap {
        color: #94A3B8;
        font-size: 12px;
        line-height: 1.4;
      }

      .odmi-card {
        background: #111827;
        border: 1px solid #1F2937;
        border-radius: 16px;
        padding: 20px 24px 18px 24px;
        margin-bottom: 18px;
      }
      .odmi-card h3 {
        color: #F1F5F9;
        font-size: 16px;
        font-weight: 700;
        margin: 0 0 14px 0;
        letter-spacing: -0.005em;
      }
      .odmi-card .eyebrow {
        color: #5EEAD4;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        margin-bottom: 6px;
      }
      .odmi-card p, .odmi-card div, .odmi-card span {
        color: #CBD5E0;
      }
      .odmi-divider {
        border-top: 1px solid #1F2937;
        margin: 22px 0;
      }
      .odmi-foot {
        color: #64748B;
        font-size: 11px;
        text-align: center;
        margin-top: 12px;
      }

      /* Streamlit dataframe — dark surface, subtle border. */
      [data-testid="stDataFrame"] {
        border: 1px solid #1F2937;
        border-radius: 12px;
        overflow: hidden;
      }

      /* Tighten altair chart wrapper. */
      [data-testid="stAltairChart"] > div {
        background: transparent !important;
      }

      /* Streamlit's native metric (used in the progress strip and elsewhere). */
      [data-testid="stMetric"] {
        background: #111827;
        border: 1px solid #1F2937;
        border-radius: 12px;
        padding: 14px 16px 12px 16px;
      }
      [data-testid="stMetricLabel"] p,
      [data-testid="stMetricLabel"] {
        color: #94A3B8 !important;
        font-size: 11px !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-weight: 600;
      }
      [data-testid="stMetricValue"] {
        color: #F1F5F9 !important;
      }
      [data-testid="stMetricDelta"] {
        color: #94A3B8 !important;
      }

      /* Section divider lines */
      hr {
        border-color: #1F2937 !important;
      }

      /* Captions and small text everywhere — slate, not the default off-white. */
      .stCaption, [data-testid="stCaptionContainer"] {
        color: #64748B !important;
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

    chip_style = (
        "background: rgba(255,255,255,0.04); border:1px solid #2A3550; "
        "border-radius: 12px; padding: 10px 16px;"
    )
    label_style = (
        "color:#94A3B8; font-size:10px; letter-spacing:0.12em; "
        "font-weight:600; text-transform:uppercase;"
    )
    value_style = (
        "color:#F8FAFC; font-size:22px; font-weight:700; "
        "letter-spacing:-0.01em; margin-top:4px;"
    )

    st.markdown(
        f"""
        <div class="odmi-hero">
          <div class="odmi-eyebrow">ODMI Agent Swarm · Live Control Surface</div>
          <div class="odmi-title">Dashboard</div>
          <div class="odmi-sub">
            A three-agent swarm answering EU Open Data Maturity Index
            questions across 36 countries. Researcher proposes, Verifier
            tries to disprove, Adjudicator decides on retry exhaustion.
            Everything below is read straight from the audit-trail
            SQLite store.
          </div>
          <div style="display:flex; gap:14px; margin-top:22px; flex-wrap:wrap;">
            <div style="{chip_style}">
              <div style="{label_style}">In flight</div>
              <div style="{value_style}">{len(active)}</div>
            </div>
            <div style="{chip_style}">
              <div style="{label_style}">Finalised</div>
              <div style="{value_style}">{len(finals)}</div>
            </div>
            <div style="{chip_style}">
              <div style="{label_style}">5h spend</div>
              <div style="{value_style}">{format_gbp(cost)}</div>
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
    researcher = db.researcher_runs(limit=1000)
    verifier = db.verifier_runs(limit=1000)
    summary = db.rolling_window_summary()
    accuracy = db.accuracy_summary()

    cost = float(summary.get("cost") or 0.0)
    n_calls = int(summary.get("n_calls") or 0)

    if accuracy["accuracy"] is not None:
        acc_value = f"{accuracy['accuracy']:.0%}"
        n_near = accuracy.get("n_near_match", 0)
        n_abstained = accuracy.get("n_abstained", 0)
        within = accuracy.get("accuracy_within_one_band")
        abstain_rate = accuracy.get("abstention_rate")
        abstain_text = (
            f" {n_abstained} abstained ({abstain_rate:.0%})."
            if n_abstained > 0 and abstain_rate is not None else ""
        )
        if n_near > 0 and within is not None:
            acc_caption = (
                f"{accuracy['n_match']} match · {n_near} near · "
                f"{accuracy['n_differ']} differ. "
                f"Within one band: {within:.0%}.{abstain_text}"
            )
        else:
            acc_caption = (
                f"{accuracy['n_match']} match / "
                f"{accuracy['n_differ']} differ vs ODMI 2025.{abstain_text}"
            )
    else:
        acc_value = "—"
        acc_caption = "No comparable pairs yet."

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
                "Pairs finalised",
                str(accuracy["n_finalised"]),
                f"{len(researcher)} R · {len(verifier)} V swarm calls.",
                "#1E3A5F",
            ),
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            _kpi_html(
                "Accuracy vs ODMI", acc_value, acc_caption, "#38A169",
            ),
            unsafe_allow_html=True,
        )
    with cols[3]:
        st.markdown(
            _kpi_html(
                "5h window spend",
                format_gbp(cost),
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
        '<div class="eyebrow">SWARM vs ODMI</div>'
        '<h3>Pairs by country, match vs differ against ODMI 2025</h3>',
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

    _FONT = "Inter, -apple-system, Segoe UI, Roboto, sans-serif"
    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X(
                "country_code:N",
                title="Country",
                sort=country_order,
                axis=alt.Axis(
                    labelFontSize=12, titleFontSize=11,
                    labelColor="#E2E8F0", titleColor="#94A3B8",
                    labelFont=_FONT, titleFont=_FONT,
                    labelFontWeight=600, titleFontWeight=500,
                    domain=False, ticks=False,
                    titlePadding=14,
                ),
            ),
            y=alt.Y(
                "n:Q", title="Finalised pairs", stack="zero",
                axis=alt.Axis(
                    labelFontSize=11, titleFontSize=11,
                    labelColor="#94A3B8", titleColor="#94A3B8",
                    labelFont=_FONT, titleFont=_FONT,
                    titleFontWeight=500,
                    grid=True, gridColor="#1F2937",
                    domain=False, ticks=False,
                    titlePadding=14,
                ),
            ),
            color=alt.Color(
                "outcome:N",
                title="vs ODMI ground truth",
                scale=alt.Scale(
                    domain=[
                        "Matches ODMI",
                        "Near match (adjacent band)",
                        "Differs from ODMI",
                        "Abstained",
                        "No ground truth",
                    ],
                    range=["#10B981", "#D69E2E", "#EF4444",
                           "#64748B", "#475569"],
                ),
                legend=alt.Legend(
                    orient="bottom", labelFontSize=12, titleFontSize=11,
                    labelFont=_FONT, titleFont=_FONT,
                    labelColor="#E2E8F0", titleColor="#94A3B8",
                    symbolType="square", symbolSize=140,
                    padding=14,
                ),
            ),
            tooltip=["country_code", "outcome", "n"],
        )
        .properties(height=320, background="transparent")
        .configure_view(strokeWidth=0)
        .configure(font=_FONT)
    )
    st.altair_chart(chart, use_container_width=True)

    n_match = int(df[df["outcome"] == "Matches ODMI"]["n"].sum())
    n_near = int(df[df["outcome"] == "Near match (adjacent band)"]["n"].sum())
    n_differ = int(df[df["outcome"] == "Differs from ODMI"]["n"].sum())
    n_abstained = int(df[df["outcome"] == "Abstained"]["n"].sum())
    denom = n_match + n_near + n_differ + n_abstained
    pct_match = (n_match / denom) if denom > 0 else 0
    within = ((n_match + n_near) / denom) if denom > 0 else 0
    near_text = f", {n_near} near" if n_near > 0 else ""
    abstain_text = f", {n_abstained} abstained" if n_abstained > 0 else ""
    band_text = (
        f' Within one band: <strong style="color:#5EEAD4;">{within:.0%}</strong>.'
        if n_near > 0 else ""
    )
    st.markdown(
        f'<div style="color:#94A3B8; font-size:12px; margin-top:10px;">'
        f'<strong style="color:#E2E8F0;">{int(totals.sum())}</strong> '
        f'finalised pairs across {len(country_order)} '
        f'country/countries. Exact accuracy vs ODMI 2025: '
        f'<strong style="color:#5EEAD4;">{pct_match:.0%}</strong> '
        f'({n_match} match{near_text}, {n_differ} differ{abstain_text}).{band_text} '
        f'ODMI assessments are one cycle old, so a real-world change '
        f'since 2025 looks like a swarm error here.'
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
        "Retries", "Cost £", "Last message", "Updated",
    ]
    display["Cost £"] = display["Cost £"].apply(
        lambda x: format_gbp(x, places=4) if pd.notna(x) else "—"
    )
    st.dataframe(display, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# Coverage summary + Human queue (right column)
# ============================================================

def render_coverage_summary() -> None:
    """Per-country ground-truth coverage from ODMI 2025."""
    accuracy = db.accuracy_summary()
    gt_total = db.ground_truth_count()
    finals = db.finals(limit=10000)

    st.markdown(
        '<div class="odmi-card">'
        '<div class="eyebrow">GROUND TRUTH · ODMI 2025</div>'
        '<h3>Coverage</h3>',
        unsafe_allow_html=True,
    )

    if gt_total == 0:
        st.warning(
            "No ODMI ground truth loaded. Run "
            "`uv run python scripts/load_ground_truth.py`."
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown(
        f'<div style="color:#94A3B8; font-size:13px; margin-bottom:12px;">'
        f'<strong style="color:#F1F5F9;">{gt_total:,}</strong> ODMI answers '
        f'loaded across 36 countries × 143 questions. Swarm has covered '
        f'<strong style="color:#5EEAD4;">{accuracy["n_finalised"]}</strong> '
        f'pairs so far.'
        f'</div>',
        unsafe_allow_html=True,
    )

    if len(finals) > 0:
        per_country = (
            finals.groupby("country_code").size().to_dict()
        )
        chip_html = '<div style="display:flex; flex-wrap:wrap; gap:8px;">'
        for country, n in sorted(per_country.items()):
            chip_html += (
                '<div style="background:#0F172A; border:1px solid #1F2937; '
                'border-radius:10px; padding:10px 14px; min-width:96px;">'
                f'<div style="color:#94A3B8; font-weight:600; font-size:11px; '
                f'letter-spacing:0.08em;">{country}</div>'
                f'<div style="color:#5EEAD4; font-weight:700; font-size:20px; '
                f'margin-top:2px;">{n}</div>'
                '<div style="color:#64748B; font-size:10px;">pairs run</div>'
                '</div>'
            )
        chip_html += "</div>"
        st.markdown(chip_html, unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


def render_abstentions() -> None:
    st.markdown(
        '<div class="odmi-card">'
        '<div class="eyebrow">OUTCOMES</div>'
        '<h3>Abstentions</h3>',
        unsafe_allow_html=True,
    )

    finals = db.finals(limit=1000)
    if len(finals) == 0:
        st.info("No pairs finalised yet.")
    else:
        # D52: abstained_* are the abstention dispositions; escalated_* are
        # the pre-rename legacy strings, kept so old rows still surface.
        abstained = finals[finals["terminal_status"].isin([
            "abstained_captcha", "abstained_adjudicator",
            "escalated_captcha", "escalated_adjudicator",
        ])]
        if len(abstained) == 0:
            st.success("No abstentions. The swarm committed an answer on "
                       "every pair.")
        else:
            st.write(f"{len(abstained)} pair(s) abstained:")
            st.dataframe(
                abstained[[
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
    render_coverage_summary()
    render_abstentions()

st.markdown(
    '<div class="odmi-foot">'
    "Auto-refresh: KPIs and recent runs reload every three seconds. "
    "The chart reloads every five. Other panels refresh on interaction."
    '</div>',
    unsafe_allow_html=True,
)
