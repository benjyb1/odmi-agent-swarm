"""Hand-marks — read-only view of the audit-trail rubric scores."""

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


st.set_page_config(page_title="Hand-marks", page_icon="✍", layout="wide")
page_header(
    "Hand-marks",
    "Read-only. Editing happens in the CSV files in data/hand_marks/ and is "
    "committed to git (D9 lock rule).",
)
render_session_widget()


hm = db.hand_marks()

if len(hm) == 0:
    st.info(
        "No hand-marks in the DB yet. The CSV workspace lives at "
        "`data/hand_marks/<country>_handmarks.csv`. Migrating from the "
        "Word doc to CSV is a separate task per `data/hand_marks/PROTOCOL.md`."
    )
    st.stop()


# Summary
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total hand-marks", len(hm))
with col2:
    locked = hm[hm["locked_by_commit"].notna()]
    st.metric("Locked", f"{len(locked)} / {len(hm)}")
with col3:
    countries = hm["country_code"].nunique()
    st.metric("Countries", countries)

st.divider()

# Filter
col_c, col_t = st.columns(2)
with col_c:
    chosen_countries = st.multiselect(
        "Country",
        sorted(hm["country_code"].unique().tolist()),
        default=sorted(hm["country_code"].unique().tolist()),
    )
with col_t:
    tiers = ["Highly Likely", "Likely", "Unlikely", "Very Unlikely"]
    tier_filter = st.multiselect("Tier", tiers, default=tiers)

filtered = hm[hm["country_code"].isin(chosen_countries)]
if "tier" in filtered.columns:
    filtered = filtered[filtered["tier"].isin(tier_filter)]

# Show table.
show_cols = [
    "question_id", "country_code",
    "evidence_score", "determinism_score", "complexity_score",
    "composite_score", "tier",
    "locked_by_commit", "marker", "marked_at",
]
show_cols = [c for c in show_cols if c in filtered.columns]
st.dataframe(filtered[show_cols], use_container_width=True, hide_index=True)

# Edit instructions.
st.divider()
st.markdown(
    "**To add or edit a hand-mark:**\n\n"
    "1. Open the CSV: `data/hand_marks/<country>_handmarks.csv`.\n"
    "2. Edit, save.\n"
    "3. Commit to git. The `locked_by_commit` column tracks the SHA.\n"
    "4. Re-run `scripts/import_handmarks.py` (TBD) to mirror into the DB.\n\n"
    "The CSV remains canonical because the D9 lock rule requires git "
    "commits to certify the temporal lock."
)
