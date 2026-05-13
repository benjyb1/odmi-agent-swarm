"""Verifier Strategies — compare the four adversarial prompt strategies
on the same Researcher row (D15, Q12)."""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib import db
from dashboard.lib.sidebar import page_header, render_session_widget


st.set_page_config(page_title="Verifier Strategies", page_icon="⚖", layout="wide")
page_header(
    "Verifier Strategies",
    "Compare the four adversarial prompt strategies (disprove, negation, "
    "steelman, blind) on the same Researcher row. Used to decide which "
    "strategy catches errors most reliably (D15, Q12).",
)
render_session_widget()


# Step 1: pick a Researcher row.
rdf = db.researcher_runs(limit=500)
if len(rdf) == 0:
    st.warning("No Researcher rows in the DB yet. Run the Coordinator first.")
    st.stop()

rdf["label"] = rdf.apply(
    lambda r: f"#{r['id']}  {r['question_id']}/{r['country_code']}  "
              f"{r['answer']} ({r['answer_confidence']:.2f})",
    axis=1,
)
picked_label = st.selectbox(
    "Pick a Researcher row to verify:",
    rdf["label"].tolist(),
)
picked_id = int(picked_label.split()[0].lstrip("#"))
picked_row = rdf[rdf["id"] == picked_id].iloc[0]

with st.expander("Researcher details", expanded=False):
    st.json(picked_row.to_dict())

st.divider()

# Step 2: existing verifier rows for this researcher row.
vdf = db.verifier_runs(limit=500)
existing = vdf[vdf["researcher_run_id"] == picked_id]

if len(existing) > 0:
    st.subheader(f"Existing Verifier runs for Researcher row #{picked_id}")
    pivot = existing.groupby("strategy_label").agg(
        n=("id", "count"),
        verdict=("verdict", "first"),
        ver_answer=("verifier_answer", "first"),
        confidence=("verifier_confidence", "mean"),
        cost=("estimated_cost_usd", "mean"),
    ).reset_index()
    st.dataframe(pivot, use_container_width=True, hide_index=True)
else:
    st.info("No Verifier runs yet for this Researcher row.")

st.divider()

# Step 3: run missing strategies.
strategies = [
    "verifier-disprove",
    "verifier-negation",
    "verifier-steelman",
    "verifier-blind",
]
already = set(existing["strategy_label"].dropna().unique().tolist())
missing = [s for s in strategies if s not in already]

st.subheader("Run all four strategies (or only missing)")
st.caption(
    "Each click spawns a separate run_verifier.py subprocess against this "
    "Researcher row. They run sequentially because they share the row."
)

col_a, col_b = st.columns(2)
with col_a:
    if missing:
        if st.button(f"▶ Run missing strategies: {', '.join(missing)}",
                     type="primary", use_container_width=True):
            _launch_strategies(picked_row, missing)
    else:
        st.success("All four strategies already run for this row.")
with col_b:
    if st.button("▶ Re-run ALL four strategies", use_container_width=True):
        _launch_strategies(picked_row, strategies)


def _launch_strategies(row, strategy_list):
    log_dir = REPO_ROOT / "dashboard" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    for s in strategy_list:
        cmd = [
            sys.executable, str(REPO_ROOT / "scripts" / "run_verifier.py"),
            row["question_id"], row["country_code"],
            "--strategy", s,
            "--researcher-run-id", str(int(row["id"])),
        ]
        log_path = log_dir / f"strategy_{s}_{uuid.uuid4().hex[:6]}.log"
        with open(log_path, "w") as lh:
            subprocess.Popen(cmd, cwd=str(REPO_ROOT),
                             stdout=lh, stderr=subprocess.STDOUT)
        st.toast(f"Started {s}. Log: {log_path.name}")
    st.info("Strategies launched. Reload the page in ~60s to see results.")
