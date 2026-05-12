"""Results — browse Researcher / Verifier / Final rows."""

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


st.set_page_config(page_title="Results", page_icon="📋", layout="wide")
page_header("Results", "Every Researcher, Verifier, and Final row.")
render_session_widget()


tab_r, tab_v, tab_f = st.tabs(["Researcher runs", "Verifier runs", "Finals"])

with tab_r:
    rdf = db.researcher_runs(limit=500)
    if len(rdf) == 0:
        st.info("No Researcher runs yet.")
    else:
        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            countries = sorted(rdf["country_code"].dropna().unique().tolist())
            country_filter = st.multiselect(
                "Country", countries, default=countries, key="r_country",
            )
        with col2:
            answers = sorted(rdf["answer"].dropna().unique().tolist())
            answer_filter = st.multiselect(
                "Answer", answers, default=answers, key="r_answer",
            )
        with col3:
            models = sorted(rdf["model_version"].dropna().unique().tolist())
            model_filter = st.multiselect(
                "Model", models, default=models, key="r_model",
            )
        filtered = rdf[
            rdf["country_code"].isin(country_filter)
            & rdf["answer"].isin(answer_filter)
            & rdf["model_version"].isin(model_filter)
        ]
        st.caption(f"{len(filtered)} of {len(rdf)} rows shown.")
        st.dataframe(filtered, use_container_width=True, hide_index=True)

        # Drawer for single row.
        if len(filtered) > 0:
            picked = st.selectbox(
                "Inspect row id", [None] + filtered["id"].tolist(),
                format_func=lambda v: "select…" if v is None else str(v),
                key="r_inspect",
            )
            if picked is not None:
                row = filtered[filtered["id"] == picked].iloc[0]
                with st.expander(f"Row {picked} — {row['question_id']}/{row['country_code']}",
                                 expanded=True):
                    st.json(row.to_dict())

with tab_v:
    vdf = db.verifier_runs(limit=500)
    if len(vdf) == 0:
        st.info("No Verifier runs yet.")
    else:
        col1, col2, col3 = st.columns(3)
        with col1:
            strategies = sorted(vdf["strategy_label"].dropna().unique().tolist())
            strat_filter = st.multiselect(
                "Strategy", strategies, default=strategies, key="v_strat",
            )
        with col2:
            verdicts = sorted(vdf["verdict"].dropna().unique().tolist())
            v_filter = st.multiselect(
                "Verdict", verdicts, default=verdicts, key="v_verdict",
            )
        with col3:
            countries = sorted(vdf["country_code"].dropna().unique().tolist())
            c_filter = st.multiselect(
                "Country", countries, default=countries, key="v_country",
            )
        filtered = vdf[
            vdf["strategy_label"].isin(strat_filter)
            & vdf["verdict"].isin(v_filter)
            & vdf["country_code"].isin(c_filter)
        ]
        st.caption(f"{len(filtered)} of {len(vdf)} rows shown.")
        st.dataframe(filtered, use_container_width=True, hide_index=True)

        if len(filtered) > 0:
            picked = st.selectbox(
                "Inspect row id", [None] + filtered["id"].tolist(),
                format_func=lambda v: "select…" if v is None else str(v),
                key="v_inspect",
            )
            if picked is not None:
                row = filtered[filtered["id"] == picked].iloc[0]
                with st.expander(f"Row {picked} — {row['question_id']}/{row['country_code']}",
                                 expanded=True):
                    st.json(row.to_dict())

with tab_f:
    fdf = db.finals(limit=500)
    if len(fdf) == 0:
        st.info("No finalised pairs yet. Run a Coordinator pass.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            statuses = sorted(fdf["terminal_status"].dropna().unique().tolist())
            status_filter = st.multiselect(
                "Terminal status", statuses, default=statuses, key="f_status",
            )
        with col2:
            countries = sorted(fdf["country_code"].dropna().unique().tolist())
            c_filter = st.multiselect(
                "Country", countries, default=countries, key="f_country",
            )
        filtered = fdf[
            fdf["terminal_status"].isin(status_filter)
            & fdf["country_code"].isin(c_filter)
        ]
        st.caption(f"{len(filtered)} of {len(fdf)} rows shown.")
        st.dataframe(filtered, use_container_width=True, hide_index=True)
