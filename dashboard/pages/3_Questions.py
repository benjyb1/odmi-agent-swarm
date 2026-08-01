"""Questions: browsable table; tick rows and send to Run Console."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib import db
from dashboard.lib.sidebar import page_header, render_session_widget


st.set_page_config(page_title="Questions", page_icon="❓", layout="wide")
page_header("Questions", "Browse the 143 ODMI questions, multi-select, and push to the Run Console.")
render_session_widget()


qs = db.all_questions()
if len(qs) == 0:
    st.error("No questions loaded. Run scripts/parse_questions.py first.")
    st.stop()

# How many swarm pairs have already been finalised per question_id.
# Useful when picking questions: avoid duplicating ones already covered.
finals = db.finals(limit=10000)
runs_per_qid = (
    finals.groupby("question_id").size().to_dict()
    if len(finals) > 0 and "question_id" in finals.columns else {}
)

# Filters

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    search = st.text_input("Search question text", value="", key="q_search")
with col2:
    dimensions = sorted(qs["dimension"].dropna().unique().tolist())
    dim_filter = st.multiselect("Dimension", dimensions, default=dimensions)
with col3:
    indicators = sorted(qs["indicator"].dropna().unique().tolist())
    ind_filter = st.multiselect(
        "Indicator", indicators, default=indicators,
    )

filtered = qs.copy()
filtered = filtered[filtered["dimension"].isin(dim_filter)]
filtered = filtered[filtered["indicator"].isin(ind_filter)]
if search:
    needle = search.lower()
    filtered = filtered[
        filtered["question_text"].fillna("").str.lower().str.contains(needle)
        | filtered["question_id"].fillna("").str.lower().str.contains(needle)
    ]

filtered["runs"] = filtered["question_id"].map(
    lambda q: runs_per_qid.get(q, 0)
)

# Selection widget + table

# The matching rows are shown read-only. Selection happens through a
# proper multiselect below the table so it works reliably across
# Streamlit versions and is testable with normal locators.

display_cols = ["question_id", "dimension", "indicator",
                "answer_shape", "question_text", "runs"]
display_cols = [c for c in display_cols if c in filtered.columns]

st.dataframe(
    filtered[display_cols],
    use_container_width=True,
    hide_index=True,
    column_config={
        "question_id": st.column_config.TextColumn("Q ID", width="small"),
        "dimension": st.column_config.TextColumn("Dim", width="small"),
        "indicator": st.column_config.TextColumn("Indicator", width="medium"),
        "answer_shape": st.column_config.TextColumn(
            "Shape", width="small",
            help=(
                "D28: per-question answer shape. binary / percentage_band "
                "/ ordinal_magnitude / count_band / categorical."
            ),
        ),
        "question_text": st.column_config.TextColumn("Question", width="large"),
        "runs": st.column_config.NumberColumn(
            "Swarm runs", help="Finalised pairs across all countries.",
            width="small",
        ),
    },
)

selected = st.multiselect(
    "Select question(s) to stage for the Run Console:",
    options=filtered["question_id"].tolist(),
    default=[
        q for q in st.session_state.get("queued_questions", [])
        if q in filtered["question_id"].tolist()
    ],
    placeholder="pick one or more…",
    key="questions_picker",
)
st.caption(f"{len(selected)} of {len(filtered)} matching questions selected.")

col_send, col_clear = st.columns([1, 1])
with col_send:
    if st.button(f"Send {len(selected)} → Run Console",
                 type="primary", use_container_width=True,
                 disabled=(len(selected) == 0)):
        st.session_state["queued_questions"] = selected
        st.success(
            f"Staged {len(selected)} question(s) for the Run Console. "
            "Open the Run Console page from the sidebar."
        )
with col_clear:
    if st.button("Clear staged questions", use_container_width=True):
        st.session_state["queued_questions"] = []
        st.info("Cleared.")
        st.rerun()
