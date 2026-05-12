"""Costs — D12 cost surface."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib import db
from dashboard.lib.sidebar import page_header, render_session_widget


st.set_page_config(page_title="Costs", page_icon="💰", layout="wide")
page_header("Costs", "Token usage and arithmetic-equivalent cost. CLIProxyAPI is a flat fee; figures are reproducible USD equivalents (Q9 in SPEC.md).")
render_session_widget()


summary = db.rolling_window_summary()

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Window calls (5h)", int(summary.get("n_calls") or 0))
with col2:
    st.metric("Tokens (in)", f"{int(summary.get('in_tok') or 0):,}")
with col3:
    st.metric("Tokens (out)", f"{int(summary.get('out_tok') or 0):,}")
with col4:
    cost = float(summary.get("cost") or 0.0)
    st.metric("Window cost", f"${cost:.2f}")

st.divider()


st.subheader("Cost per day (last 30 days)")
daily = db.cost_by_day(days=30)
if len(daily) == 0:
    st.info("No usage records yet.")
else:
    chart = px.bar(daily, x="day", y="cost",
                   labels={"cost": "Cost ($)", "day": "Date"})
    chart.update_layout(height=300, margin=dict(t=10, b=10))
    st.plotly_chart(chart, use_container_width=True)
    st.dataframe(daily, use_container_width=True, hide_index=True)

st.divider()


st.subheader("Cost surface by dimension (Researcher runs)")
sql = """
SELECT q.dimension, r.country_code,
       COUNT(*) AS n,
       AVG(r.estimated_cost_usd) AS avg_cost,
       SUM(r.estimated_cost_usd) AS total_cost
FROM phase2_researcher_runs r
LEFT JOIN questions q ON q.question_id = r.question_id
GROUP BY q.dimension, r.country_code
ORDER BY total_cost DESC
"""
by_dim = db.read_sql(sql)
if len(by_dim) > 0:
    by_dim["avg_cost"] = by_dim["avg_cost"].round(4)
    by_dim["total_cost"] = by_dim["total_cost"].round(4)
    st.dataframe(by_dim, use_container_width=True, hide_index=True)
else:
    st.info("No Researcher runs joined to questions yet.")

st.divider()

st.subheader("Recent usage log (last 100 calls)")
log = db.usage_log(limit=100)
if len(log) == 0:
    st.info("Nothing in the usage log yet.")
else:
    st.dataframe(log, use_container_width=True, hide_index=True)
