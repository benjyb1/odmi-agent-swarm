"""Models — defaults + analytics."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib import db
from dashboard.lib.sidebar import page_header, render_session_widget


st.set_page_config(page_title="Models", page_icon="🤖", layout="wide")
page_header("Models",
            "Top: default model per agent role. Bottom: per-model analytics.")
render_session_widget()


MODEL_OPTIONS = [
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-opus-4-6",
]


# ============================================================
# Defaults
# ============================================================

st.subheader("Defaults")
defaults = db.model_defaults()

cols = st.columns(3)
for i, role in enumerate(["researcher", "verifier", "adjudicator"]):
    with cols[i]:
        current = defaults[defaults["agent_role"] == role]
        current_model = current.iloc[0]["model"] if len(current) else MODEL_OPTIONS[0]
        new = st.selectbox(
            f"{role.capitalize()}",
            MODEL_OPTIONS,
            index=MODEL_OPTIONS.index(current_model) if current_model in MODEL_OPTIONS else 0,
            key=f"default_{role}",
        )
        if new != current_model:
            db.set_model_default(role, new)
            st.success(f"Saved: {role} → {new}")

st.divider()

# ============================================================
# Analytics
# ============================================================

st.subheader("Researcher analytics by model")
r_an = db.model_analytics_researcher()
if len(r_an) == 0:
    st.info("No Researcher runs yet.")
else:
    r_an["avg_cost"] = r_an["avg_cost"].round(4)
    r_an["avg_ms"] = r_an["avg_ms"].round(0)
    r_an["avg_answer_conf"] = r_an["avg_answer_conf"].round(2)
    r_an["avg_retr_conf"] = r_an["avg_retr_conf"].round(2)
    st.dataframe(r_an, use_container_width=True, hide_index=True)


st.subheader("Verifier analytics by (model × strategy)")
v_an = db.model_analytics_verifier()
if len(v_an) == 0:
    st.info("No Verifier runs yet.")
else:
    v_an["pass_rate"] = (v_an["pass_rate"] * 100).round(1)
    v_an["avg_cost"] = v_an["avg_cost"].round(4)
    v_an["avg_conf"] = v_an["avg_conf"].round(2)
    v_an = v_an.rename(columns={"pass_rate": "pass_rate_%"})
    st.dataframe(v_an, use_container_width=True, hide_index=True)


# ============================================================
# Cross-product heatmap (researcher model × verifier model → pass rate)
# Per D18.
# ============================================================

st.subheader("Researcher × Verifier pass-rate heatmap (D18)")

cross = db.read_sql(
    """SELECT r.model_version AS researcher_model,
              v.model_version AS verifier_model,
              COUNT(*) AS n,
              AVG(CASE WHEN v.verdict='pass' THEN 1.0 ELSE 0.0 END) AS pass_rate
       FROM phase2_verifier_runs v
       JOIN phase2_researcher_runs r ON v.researcher_run_id = r.id
       WHERE r.model_version IS NOT NULL
         AND v.model_version IS NOT NULL
       GROUP BY r.model_version, v.model_version"""
)
if len(cross) == 0:
    st.info("Not enough runs to build the heatmap yet.")
else:
    heatmap = cross.pivot(
        index="researcher_model", columns="verifier_model", values="pass_rate"
    )
    counts = cross.pivot(
        index="researcher_model", columns="verifier_model", values="n",
    )
    st.write("Pass rate (label = pass_rate / n):")
    # Build the annotated grid as object dtype from the start so pandas
    # does not reject string values into a float column.
    annotated = pd.DataFrame(
        index=heatmap.index, columns=heatmap.columns, dtype=object,
    )
    for r in heatmap.index:
        for c in heatmap.columns:
            v = heatmap.loc[r, c]
            n = counts.loc[r, c]
            if pd.isna(v):
                annotated.loc[r, c] = "—"
            else:
                annotated.loc[r, c] = f"{v:.0%} (n={int(n)})"
    st.dataframe(annotated, use_container_width=True)
